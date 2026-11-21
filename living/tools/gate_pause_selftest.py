#!/usr/bin/env python3
"""gate_pause.sh on a fake command (docs/TOOLING.md, "Heavy work during a gate").

    python3 living/tools/gate_pause_selftest.py [--blender]

--blender runs every case through blender_gate.sh (SLOP_BLENDER_REAL = the fake) instead of
`gate_pause.sh -- fake`. The fake (a shell script) writes its process group and its open
descriptors at start, then appends a tick to a file every 0.1 s for a set time, and exits with a
set code. A test lock file stands in for gate.lock. A gate is a separate process holding it
(a Python process with an exclusive flock), not an ancestor of the command; the caller holding it is this test
process. Cases:
- the exit code passes through;
- a running command pauses while a gate holds the lock and resumes after (no ticks during the hold);
- the cap: a hold longer than SLOP_GATE_PAUSE_CAP_S continues it while the lock is still held;
- INT to the wrapper ends the command's whole group, also while paused (no orphan);
- no descriptor on the lock reaches the command, even one the caller passed down (and then the
  command is not paused: the caller holds the lock);
- the caller holding the lock without passing its descriptor down (a gate's Python, whose
  children do not inherit it): no wait at start, and no pause when the caller takes it mid-run;
- the wait at start: the command starts only once the gate releases the lock;
- SLOP_GATE_WAIT=0 runs the command straight;
- (gate_pause.sh only) no command: exit 2;
- (gate_pause.sh only) nested, `gate_pause.sh -- gate_pause.sh -- fake` (and through blender_gate.sh):
  the command runs in the outer call's group, which pauses while a gate holds the lock.
Prints one line per case and exits 1 on any failure.
"""

import fcntl
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPER = HERE / "gate_pause.sh"
BLENDER = HERE / "blender_gate.sh"
FAKE = r"""#!/usr/bin/env bash
out=$FAKE_OUT
echo "pgid $(ps -o pgid= -p $$ | tr -d ' ') pid $$" > "$out.start"
ls -l /proc/$$/fd > "$out.fds" 2>&1
end=$(( $(date +%s%N) / 1000000 + ${FAKE_MS:-3000} ))
while [ $(( $(date +%s%N) / 1000000 )) -lt $end ]; do
  echo "$(date +%s%N)" >> "$out.ticks"
  sleep 0.1
done
exit ${FAKE_EXIT:-0}
"""


def ticks(out):
    p = Path(f"{out}.ticks")
    return [int(x) / 1e9 for x in p.read_text().split()] if p.exists() else []


def main():
    blender = "--blender" in sys.argv[1:]
    fails = 0

    def case(name, ok, detail=""):
        nonlocal fails
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" ({detail})" if detail else ""))
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        fake = d / "fake"
        fake.write_text(FAKE)
        fake.chmod(0o755)
        lock = d / "gate.lock"
        lock.touch()
        log = d / "gate.log"
        base = dict(os.environ, SLOP_GATE_LOCK=str(lock), SLOP_GATE_LOG=str(log),
                    SLOP_GATE_POLL_S="0.2", SLOP_GATE_PAUSE_CAP_S="60",
                    SLOP_BLENDER_REAL=str(fake), SLOP_GATE_PAUSE=str(HELPER))
        base.pop("SLOP_GATE_WAIT", None)
        argv = ["bash", str(BLENDER)] if blender else ["bash", str(HELPER), "--", str(fake)]

        def run(name, extra=None, **kw):
            out = d / name
            env = dict(base, FAKE_OUT=str(out), **(extra or {}))
            return out, subprocess.Popen(argv, env=env, **kw)

        def held():
            return subprocess.run(["flock", "-n", "-s", str(lock), "true"]).returncode != 0

        def gate():
            """A gate: another process holding the lock exclusively, not an ancestor of the command."""
            g = subprocess.Popen([sys.executable, "-c", "import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_RDWR); "
                                  "fcntl.flock(fd, fcntl.LOCK_EX); time.sleep(600)", str(lock)])
            while not held():
                time.sleep(0.02)
            return g

        def release(g):
            g.terminate()
            g.wait(10)

        def caller_hold():
            fd = os.open(lock, os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX)
            return fd

        def caller_release(fd):
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

        # 1. The exit code.
        out, p = run("exit", {"FAKE_MS": "300", "FAKE_EXIT": "7"})
        case("the exit code passes through", p.wait(20) == 7, f"exit {p.returncode}")

        # 2. Pause while a gate holds the lock, resume after.
        out, p = run("pause", {"FAKE_MS": "4000"})
        time.sleep(1.0)
        g = gate()
        t_hold = time.time()
        time.sleep(2.0)
        during = [t for t in ticks(out) if t_hold + 0.6 < t < time.time()]
        release(g)
        t_rel = time.time()
        rc = p.wait(30)
        after = [t for t in ticks(out) if t > t_rel]
        case("paused while a gate holds the lock", not during, f"{len(during)} ticks during the hold")
        case("resumed after the release, and finished", bool(after) and rc == 0, f"{len(after)} ticks after, exit {rc}")
        text = log.read_text()
        case("the pause and the resume are logged", "paused" in text and "continued after" in text)

        # 3. The cap.
        out, p = run("cap", {"FAKE_MS": "3000", "SLOP_GATE_PAUSE_CAP_S": "1"})
        time.sleep(0.8)
        g = gate()
        t_hold = time.time()
        time.sleep(3.0)
        late = [t for t in ticks(out) if t > t_hold + 1.8]
        release(g)
        p.wait(30)
        case("the cap continues the command while the lock is still held", bool(late), f"{len(late)} ticks after the cap")
        case("the cap is logged as a warning", "WARNING: paused 1 s" in log.read_text())

        # 4. INT ends the group, also while paused.
        out, p = run("int", {"FAKE_MS": "20000"})
        time.sleep(1.0)
        g = gate()
        time.sleep(0.8)
        pgid = int(Path(f"{out}.start").read_text().split()[1])
        p.send_signal(signal.SIGINT)
        try:
            rc = p.wait(15)
        except subprocess.TimeoutExpired:
            rc = None
        release(g)
        time.sleep(0.3)
        alive = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True).stdout.split()
        case("INT ends the command's group, even while paused", rc is not None and not alive, f"exit {rc}, left {alive}")

        # 5. No lock descriptor reaches the command; one passed down means the caller holds it.
        out, p = run("fds", {"FAKE_MS": "300"})
        p.wait(20)
        case("the command holds no descriptor on the lock", str(lock) not in Path(f"{out}.fds").read_text())
        fd = caller_hold()
        os.set_inheritable(fd, True)
        out, p = run("inherit", {"FAKE_MS": "1500"}, pass_fds=(fd,))
        rc = p.wait(20)
        caller_release(fd)
        case("a descriptor the caller passes down is closed before the command starts", str(lock) not in Path(f"{out}.fds").read_text())
        case("and the command is not paused when the caller holds the lock", rc == 0 and len(ticks(out)) >= 10, f"{len(ticks(out))} ticks")

        # 6. The caller holds the lock without passing it down (a gate's Python child).
        fd = caller_hold()
        out, p = run("ancestor", {"FAKE_MS": "1500"})
        rc = p.wait(20)
        caller_release(fd)
        case("the caller holding the lock (not passed down): no wait, no pause", rc == 0 and len(ticks(out)) >= 10,
             f"exit {rc}, {len(ticks(out))} ticks")
        case("and it is logged", "the caller holds the gate lock" in log.read_text())
        out, p = run("ancestor-mid", {"FAKE_MS": "3000"})
        time.sleep(0.8)
        fd = caller_hold()
        t_hold = time.time()
        time.sleep(1.5)
        during = [t for t in ticks(out) if t > t_hold + 0.6]
        caller_release(fd)
        rc = p.wait(20)
        case("the caller taking the lock mid-run: not paused", bool(during) and rc == 0, f"{len(during)} ticks during the hold")

        # 7. The wait at start.
        g = gate()
        out, p = run("start", {"FAKE_MS": "500"})
        time.sleep(1.5)
        started_early = Path(f"{out}.start").exists()
        release(g)
        t_rel = time.time()
        p.wait(20)
        first = min(ticks(out)) if ticks(out) else 0
        case("waits at start while a gate holds the lock", not started_early and first >= t_rel - 0.05, f"first tick {first - t_rel:+.2f} s from the release")

        # 8. SLOP_GATE_WAIT=0.
        g = gate()
        out, p = run("nowait", {"FAKE_MS": "500", "SLOP_GATE_WAIT": "0"})
        rc = p.wait(20)
        release(g)
        case("SLOP_GATE_WAIT=0 runs straight", rc == 0 and len(ticks(out)) >= 3)

        # 9. No command.
        if not blender:
            r = subprocess.run(["bash", str(HELPER), "--"], capture_output=True, text=True, env=base)
            case("no command: exit 2 with the usage", r.returncode == 2 and "usage" in r.stderr)

        # 10. Nested: one group, paused by the outer call.
        if not blender:
            for label, inner in (("gate_pause.sh", ["bash", str(HELPER), "--", str(fake)]), ("blender_gate.sh", ["bash", str(BLENDER)])):
                out = d / f"nested-{label}"
                p = subprocess.Popen(["bash", str(HELPER), "--", *inner], env=dict(base, FAKE_OUT=str(out), FAKE_MS="4000"))
                time.sleep(1.0)
                g = gate()
                t_hold = time.time()
                time.sleep(2.0)
                during = [t for t in ticks(out) if t_hold + 0.6 < t < time.time()]
                release(g)
                rc = p.wait(30)
                pgid = int(Path(f"{out}.start").read_text().split()[1])
                case(f"nested through {label}: paused by the outer call", not during and rc == 0,
                     f"{len(during)} ticks during the hold, exit {rc}, command's group {pgid}")

    name = "blender_gate (through gate_pause)" if blender else "gate_pause_selftest"
    print(f"{name}: {'all passed' if not fails else f'{fails} failed'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
