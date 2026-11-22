#!/usr/bin/env python3
"""Selftest of the spend guard (`act_trial.py watch`): a guard can never silently not guard.

usage: act_trial_guard_selftest.py [--mind-bin PATH]

Free, local, no server: the "runner" is a `sleep`, the journals are files this test writes.
- a --journal that is a directory, or a pattern that names no .jsonl files, is refused at start
  (exit 2) and the runner is stopped; no ready file is written;
- a journal folder that never appears: refused after --ready-wait-s (exit 2), runner stopped;
- a valid pattern whose folder exists but where no journal file ever appears: the guard is ready,
  then stops the runner after --first-journal-s and exits 3, its ledger entry "unguarded";
- --pid-file: the guard starts first and says ready; the runner starts only after that, and its
  journaled spend is counted; two runs' journals of one file name both count;
- E5's rules: `--fail-last 50` stops at more than 10% failing of the last 50 calls (and not at 10%
  or less); `--max-calls-min N` stops above 2N calls over 2 minutes;
- with --mind-bin, `living-mind fast-replay` without a ready guard makes no call (exits non-zero,
  its journal folder empty).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WATCH = [sys.executable, "-I", str(HERE / "act_trial.py"), "watch"]
FAILS = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        FAILS.append(what)


def runner():
    return subprocess.Popen(["sleep", "60"])


def watch(tmp, name, journals, *extra, pid=None, timeout=30):
    args = WATCH + ["--arm", name, "--group", "selftest", "--ledger", str(tmp / "ledger.json"), "--log", str(tmp / f"{name}.log"),
                    "--group-cap", "1", "--total-cap", "1", "--margin", "0", "--interval", "0.5"]
    for j in journals:
        args += ["--journal", str(j)]
    if pid is not None:
        args += ["--pid", str(pid)]
    return subprocess.run(args + list(extra), capture_output=True, text=True, timeout=timeout)


def entry(at_ms, tokens=1000, error=None):
    return json.dumps({"at_ms": at_ms, "model": "deepseek-v4-1-flash-1017", "purpose": "fast", "prompt_tokens": tokens,
                       "cached_tokens": 0, "completion_tokens": 100, "error": error, "latency_ms": 500, "queue_wait_ms": 0}) + "\n"


def e5_rule(tmp, name, lines, *extra):
    """A guard over one journal written before it starts; True when it stopped its runner."""
    d = tmp / name
    d.mkdir()
    (d / "A1.jsonl").write_text("".join(lines))
    r = subprocess.Popen(["sleep", "8"])
    # Reaped as soon as it ends, so a stopped runner is not a zombie the guard still sees alive.
    threading.Thread(target=r.wait, daemon=True).start()
    out = watch(tmp, name, [d / "*.jsonl"], "--group-cap", "100", "--total-cap", "100", *extra, pid=r.pid)
    return "STOP" in out.stdout, out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mind-bin", help="a built living-mind, to check fast-replay holds its calls without a guard")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="guard-selftest-"))
    jdir = tmp / "journal"
    jdir.mkdir()

    # 1. A directory, not its journal files.
    r = runner()
    out = watch(tmp, "dir", [jdir], "--ready", str(tmp / "dir.ready"), pid=r.pid)
    r.wait(timeout=10)
    check(out.returncode == 2 and "is a directory" in out.stderr, f"a directory is refused (exit {out.returncode})")
    check(r.returncode is not None, "the runner is stopped when the guard refuses")
    check(not (tmp / "dir.ready").exists(), "a refused guard writes no ready file")

    # 2. A pattern that names no journal files.
    r = runner()
    out = watch(tmp, "txt", [jdir / "*.txt"], pid=r.pid)
    r.wait(timeout=10)
    check(out.returncode == 2 and "does not name .jsonl" in out.stderr, f"a pattern naming no .jsonl files is refused (exit {out.returncode})")

    # 3. A journal folder that never appears.
    r = runner()
    out = watch(tmp, "nofolder", [tmp / "missing" / "*.jsonl"], "--ready-wait-s", "1", pid=r.pid)
    r.wait(timeout=10)
    check(out.returncode == 2 and "no journal folder" in out.stderr, f"a missing journal folder is refused (exit {out.returncode})")

    # 4. Ready, but no journal file ever: stopped, exit 3, ledger says unguarded.
    empty = tmp / "empty"
    empty.mkdir()
    r = runner()
    out = watch(tmp, "silent", [empty / "*.jsonl"], "--ready", str(tmp / "silent.ready"), "--first-journal-s", "2", pid=r.pid)
    r.wait(timeout=10)
    led = json.loads((tmp / "ledger.json").read_text())
    silent = next((x for x in led["arms"] if x["arm"] == "silent"), {})
    check((tmp / "silent.ready").exists(), "a valid folder makes the guard ready")
    check(out.returncode == 3 and "no journal file matched" in out.stderr, f"no journal in time stops the runner (exit {out.returncode})")
    check(silent.get("status") == "unguarded", f"the ledger records it as unguarded ({silent.get('status')})")

    # 5. --pid-file: the guard first, the runner after its ready file; two journals of one name.
    a1, a2 = tmp / "run1", tmp / "run2"
    a1.mkdir()
    a2.mkdir()
    pid_file, ready = tmp / "runner.pid", tmp / "runner.ready"
    args = WATCH + ["--arm", "paired", "--group", "selftest", "--ledger", str(tmp / "ledger.json"), "--log", str(tmp / "paired.log"),
                    "--group-cap", "1", "--total-cap", "1", "--margin", "0", "--interval", "0.5", "--pid-file", str(pid_file),
                    "--ready", str(ready), "--first-journal-s", "20", "--journal", str(a1 / "*.jsonl"), "--journal", str(a2 / "*.jsonl")]
    g = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 10
    while not ready.exists() and time.time() < deadline:
        time.sleep(0.1)
    check(ready.exists(), "with --pid-file the guard is ready before any runner exists")
    r = subprocess.Popen(["sleep", "3"])
    pid_file.write_text(str(r.pid))
    now = int(time.time() * 1000)
    (a1 / "Walker1.jsonl").write_text(entry(now, 1000))
    (a2 / "Walker1.jsonl").write_text(entry(now + 1, 1000))
    r.wait()
    out, err = g.communicate(timeout=30)
    led = json.loads((tmp / "ledger.json").read_text())
    paired = next((x for x in led["arms"] if x["arm"] == "paired"), {})
    calls = sum(m.get("calls", 0) for m in (paired.get("by_model") or {}).values())
    check(g.returncode == 0 and paired.get("status") == "ended", f"the guarded runner ends normally (exit {g.returncode}, {paired.get('status')})")
    check(calls == 2, f"two runs' journals of one file name both count ({calls} calls)")

    # 6. E5's frozen rules: failures over the last 50 calls (the earlier calls all fine, so the
    # 2-minute rule over every call stays quiet), and the runaway rate.
    now = int(time.time() * 1000)
    ok_then_bad = [entry(now - 60_000 + i) for i in range(400)] + [entry(now - 1000 + i, error=("x" if i < 6 else None)) for i in range(50)]
    stopped, out = e5_rule(tmp, "fail6", ok_then_bad, "--fail-last", "50")
    check(stopped and "in the last 50 calls" in out.stdout, "6 of the last 50 failing stops the runner (--fail-last 50)")
    ok_then_5 = [entry(now - 60_000 + i) for i in range(400)] + [entry(now - 1000 + i, error=("x" if i < 5 else None)) for i in range(50)]
    stopped, out = e5_rule(tmp, "fail5", ok_then_5, "--fail-last", "50")
    check(not stopped, "5 of the last 50 failing (10%) does not stop it")
    burst = [entry(now - 90_000 + i * 40) for i in range(2100)]
    stopped, out = e5_rule(tmp, "runaway", burst, "--max-calls-min", "1000")
    check(stopped and "runaway" in out.stdout, "2,100 calls over 2 minutes stops the runner (--max-calls-min 1000)")
    stopped, out = e5_rule(tmp, "busy", burst[:1900], "--max-calls-min", "1000")
    check(not stopped, "1,900 calls over 2 minutes does not")

    # 7. fast-replay without a ready guard makes no call.
    if a.mind_bin:
        out_file = tmp / "replay.jsonl"
        env = {k: v for k, v in os.environ.items() if k != "LIVING_REPLAY_UNGUARDED"}
        for extra, what in (([], "with no guard"), (["--guard-ready", str(tmp / "never.ready"), "--guard-wait-s", "1"], "with a guard that is never ready")):
            p = subprocess.run([a.mind_bin, "fast-replay", "--frame", "balanced", "--out", str(out_file)] + extra, capture_output=True, text=True, env=env, timeout=60)
            journal = out_file.with_suffix(".journal")
            files = list(journal.glob("*")) if journal.exists() else []
            check(p.returncode != 0 and not files, f"fast-replay {what} makes no call (exit {p.returncode}, {len(files)} journal files)")
    print(f"{'FAILED' if FAILS else 'passed'}: evidence in {tmp}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
