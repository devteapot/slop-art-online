"""One serial, explicitly selected external controller process per actor.

The worker retains its MCP connection. The pilot still owns the schedule, each
responsibility's deadline, and cancellation. Failed workers are never restarted.
"""
import json
import os
import queue
import signal
import subprocess
import threading
import time

PROTOCOL = "sao-external-worker-v1"
MAX_ACK_BYTES = 1024 * 1024


class ExternalWorker:
    def __init__(self, command, *, cwd, env, log_path):
        self.command = list(command)
        self.cwd = cwd
        self.env = env
        self.log_path = log_path
        self.process = None
        self.log = None
        self.reader = None
        self.messages = queue.Queue()
        self.unavailable = None
        self.last_id = 0
        self.closed = False
        self.cleanup_error = None

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(MAX_ACK_BYTES + 1)
                if not line:
                    self.messages.put(("error", "persistent worker stdout closed"))
                    return
                if len(line) > MAX_ACK_BYTES or not line.endswith(b"\n"):
                    raise ValueError("invalid persistent worker acknowledgement framing")
                self.messages.put(("ack", json.loads(line)))
        except (OSError, ValueError, UnicodeError) as error:
            self.messages.put(("error", str(error)))

    def _start(self):
        if self.process is not None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open("ab")
        try:
            self.process = subprocess.Popen(
                self.command, cwd=self.cwd, env=self.env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                start_new_session=True,
            )
        except BaseException:
            self.log.close()
            self.log = None
            raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _send(self, value):
        body = json.dumps(dict(protocol=PROTOCOL, **value), separators=(",", ":")).encode() + b"\n"
        self.process.stdin.write(body)
        self.process.stdin.flush()

    @staticmethod
    def _ack(value, job_id):
        if not isinstance(value, dict) or value.get("protocol") != PROTOCOL:
            raise ValueError("invalid persistent worker protocol")
        if type(value.get("id")) is not int or value["id"] != job_id:
            raise ValueError("persistent worker acknowledgement has wrong job ID")
        if value.get("phase") not in ("completed", "failed", "interrupted"):
            raise ValueError("invalid persistent worker job phase")
        if type(value.get("exit_code")) is not int or value["exit_code"] not in (0, 1):
            raise ValueError("invalid persistent worker job exit code")
        if (value["phase"] == "completed") != (value["exit_code"] == 0):
            raise ValueError("inconsistent persistent worker job outcome")
        if type(value.get("worker_reusable")) is not bool:
            raise ValueError("missing persistent worker transport status")
        if value.get("error") is not None and not isinstance(value["error"], str):
            raise ValueError("invalid persistent worker error")
        return value

    def run(self, job_id, responsibility, config, output, *, deadline, cancelled, alive, on_start=None):
        """Run exactly one scheduled job; deadline already includes lazy startup."""
        if type(job_id) is not int or job_id <= self.last_id:
            raise ValueError("persistent job IDs must strictly increase")
        self.last_id = job_id
        base = dict(phase="failed", exit_code=1, interruption=None)
        if self.unavailable:
            return dict(base, error=self.unavailable, worker_reusable=False)
        interruption = None
        try:
            if cancelled() or not alive() or time.monotonic() >= deadline:
                return dict(base, phase="interrupted", interruption="pilot ended, actor stopped, or process deadline",
                            error="job cancelled before worker dispatch", worker_reusable=self.process is not None)
            self._start()
            if on_start:
                on_start(self.process)
            if cancelled() or not alive() or time.monotonic() >= deadline:
                self.unavailable = "persistent worker cancelled before dispatch"
                self.stop(grace=3)
                return dict(base, phase="interrupted", interruption="pilot ended, actor stopped, or process deadline",
                            error=self.unavailable, worker_reusable=False)
            self._send(dict(op="job", id=job_id, config_path=str(config),
                            responsibility=responsibility, output=output))
            while True:
                if cancelled() or not alive() or time.monotonic() >= deadline:
                    interruption = "pilot ended, actor stopped, or process deadline"
                    # Cancellation cleanup has its own short bound, just as the
                    # one-shot process termination path does. No further model
                    # attempt or operation dispatch is authorized by this grace.
                    try:
                        self._send(dict(op="cancel", id=job_id, reason=interruption))
                    except (OSError, ValueError):
                        pass
                    self.unavailable = "persistent worker cancelled; no automatic restart"
                    self.stop(grace=3)
                    return dict(base, phase="interrupted", interruption=interruption,
                                error=self.unavailable, worker_reusable=False)
                try:
                    kind, value = self.messages.get(timeout=min(.25, max(.001, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                if kind == "error":
                    raise ValueError(value)
                ack = self._ack(value, job_id)
                if not ack["worker_reusable"]:
                    self.unavailable = ack.get("error") or "persistent worker is no longer reusable"
                    self.stop(grace=3)
                return dict(base, **{k: ack[k] for k in ("phase", "exit_code")},
                            error=ack.get("error"), worker_reusable=ack["worker_reusable"],
                            acknowledgement=ack, worker_pid=self.process.pid)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.unavailable = "persistent worker unavailable: " + str(error)
            self.stop(grace=3)
            return dict(base, interruption=interruption, error=self.unavailable, worker_reusable=False)

    def _wait_without_reaping(self, seconds):
        until = time.monotonic() + seconds
        while True:
            # Keep the leader's PID reserved until all members of its owned
            # process group have been signalled. poll()/wait() would reap an
            # exited leader too early while an MCP descendant could remain.
            try:
                if os.waitid(os.P_PID, self.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                    return True
            except ChildProcessError:
                self.cleanup_error = "persistent worker leader was reaped outside its owner"
                return True
            if time.monotonic() >= until:
                return False
            time.sleep(.01)

    def stop(self, grace=3):
        """Request shutdown and reap the owned group with finite waits."""
        process = self.process
        if process is None or self.closed:
            return
        self.closed = True
        try:
            try:
                self._send(dict(op="shutdown"))
            except (OSError, ValueError):
                pass
            self._wait_without_reaping(grace)
            if self.cleanup_error is None:
                # The unreaped leader reserves this process-group identity,
                # including when it exited before an inherited pipe closed.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                self._wait_without_reaping(3)
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=3)
        except (OSError, subprocess.SubprocessError) as error:
            self.cleanup_error = "persistent worker cleanup failed: " + str(error)
        finally:
            if process.stdin:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            if self.reader:
                self.reader.join(timeout=1)
            if process.stdout and not (self.reader and self.reader.is_alive()):
                try:
                    process.stdout.close()
                except (OSError, ValueError):
                    pass
            elif self.reader and self.reader.is_alive():
                # Closing a buffered stream under its blocked reader can wait
                # forever for the stream lock. Report incomplete cleanup instead.
                self.cleanup_error = self.cleanup_error or "persistent worker stdout remains open after group cleanup"
            if self.log:
                self.log.close()
                self.log = None
