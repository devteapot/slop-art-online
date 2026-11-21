#!/usr/bin/env python3
"""blender_gate.sh on a fake Blender (docs/TOOLING.md, "Blender during a gate").

    python3 living/tools/blender_gate_selftest.py

The fake `blender` (a shell script) writes its process group and its open descriptors at start,
then appends a tick to a file every 0.1 s for a set time, and exits with a set code. A test lock
file stands in for gate.lock, held exclusively from Python as a gate holds it. Cases:
- the exit code passes through;
- a running Blender pauses while the lock is held and resumes after (no ticks during the hold);
- the cap: a hold longer than SLOP_GATE_PAUSE_CAP_S continues Blender while the lock is still held;
- INT to the wrapper ends Blender's whole group (no orphan);
- no descriptor on the lock reaches Blender, even one the caller passed down (and then Blender is
  not paused: the caller holds the lock);
- the wait at start: Blender starts only once the lock is released;
- SLOP_GATE_WAIT=0 runs Blender straight.
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

WRAPPER = Path(__file__).resolve().parent / "blender_gate.sh"
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
    fails = 0

    def case(name, ok, detail=""):
        nonlocal fails
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f" ({detail})" if detail else ""))
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        fake = d / "blender"
        fake.write_text(FAKE)
        fake.chmod(0o755)
        lock = d / "gate.lock"
        lock.touch()
        base = dict(os.environ, SLOP_BLENDER_REAL=str(fake), SLOP_GATE_LOCK=str(lock), SLOP_GATE_LOG=str(d / "gate.log"),
                    SLOP_GATE_POLL_S="0.2", SLOP_GATE_PAUSE_CAP_S="60")
        base.pop("SLOP_GATE_WAIT", None)

        def run(name, extra=None, **kw):
            out = d / name
            env = dict(base, FAKE_OUT=str(out), **(extra or {}))
            return out, subprocess.Popen(["bash", str(WRAPPER)], env=env, **kw)

        def hold():
            fd = os.open(lock, os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX)
            return fd

        def release(fd):
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

        # 1. The exit code.
        out, p = run("exit", {"FAKE_MS": "300", "FAKE_EXIT": "7"})
        case("the exit code passes through", p.wait(20) == 7, f"exit {p.returncode}")

        # 2. Pause while held, resume after.
        out, p = run("pause", {"FAKE_MS": "4000"})
        time.sleep(1.0)
        fd = hold()
        t_hold = time.time()
        time.sleep(2.0)
        during = [t for t in ticks(out) if t_hold + 0.6 < t < time.time()]
        n_before_release = len(ticks(out))
        release(fd)
        t_rel = time.time()
        rc = p.wait(30)
        after = [t for t in ticks(out) if t > t_rel]
        case("paused while the lock is held", not during, f"{len(during)} ticks during the hold")
        case("resumed after the release, and finished", bool(after) and rc == 0, f"{len(after)} ticks after, exit {rc}")
        case("the pause and the resume are logged", "paused" in (d / "gate.log").read_text() and "continued after" in (d / "gate.log").read_text())

        # 3. The cap.
        out, p = run("cap", {"FAKE_MS": "3000", "SLOP_GATE_PAUSE_CAP_S": "1"})
        time.sleep(0.8)
        fd = hold()
        t_hold = time.time()
        time.sleep(3.0)
        late = [t for t in ticks(out) if t > t_hold + 1.8]
        release(fd)
        p.wait(30)
        case("the cap continues Blender while the lock is still held", bool(late), f"{len(late)} ticks after the cap")
        case("the cap is logged as a warning", "WARNING: paused 1 s" in (d / "gate.log").read_text())

        # 4. INT ends the group, also while paused.
        out, p = run("int", {"FAKE_MS": "20000"})
        time.sleep(1.0)
        fd = hold()
        time.sleep(0.8)
        pgid = int(Path(f"{out}.start").read_text().split()[1])
        p.send_signal(signal.SIGINT)
        try:
            rc = p.wait(15)
        except subprocess.TimeoutExpired:
            rc = None
        release(fd)
        time.sleep(0.3)
        alive = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True).stdout.split()
        case("INT ends Blender's group, even while paused", rc is not None and not alive, f"exit {rc}, left {alive}")

        # 5. No lock descriptor reaches Blender; one passed down means the caller holds it.
        out, p = run("fds", {"FAKE_MS": "300"})
        p.wait(20)
        case("Blender holds no descriptor on the lock", str(lock) not in Path(f"{out}.fds").read_text())
        fd = hold()
        os.set_inheritable(fd, True)
        out, p = run("inherit", {"FAKE_MS": "1500"}, pass_fds=(fd,))
        rc = p.wait(20)
        release(fd)
        fds = Path(f"{out}.fds").read_text()
        case("a descriptor the caller passes down is closed before Blender starts", str(lock) not in fds)
        case("and Blender is not paused when the caller holds the lock", rc == 0 and len(ticks(out)) >= 10, f"{len(ticks(out))} ticks")

        # 6. The wait at start.
        fd = hold()
        out, p = run("start", {"FAKE_MS": "500"})
        time.sleep(1.5)
        started_early = Path(f"{out}.start").exists()
        release(fd)
        t_rel = time.time()
        p.wait(20)
        first = min(ticks(out)) if ticks(out) else 0
        case("waits at start while the lock is held", not started_early and first >= t_rel - 0.05, f"first tick {first - t_rel:+.2f} s from the release")

        # 7. SLOP_GATE_WAIT=0.
        fd = hold()
        out, p = run("nowait", {"FAKE_MS": "500", "SLOP_GATE_WAIT": "0"})
        rc = p.wait(20)
        release(fd)
        case("SLOP_GATE_WAIT=0 runs straight", rc == 0 and len(ticks(out)) >= 3)

    print(f"blender_gate_selftest: {'all passed' if not fails else f'{fails} failed'}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
