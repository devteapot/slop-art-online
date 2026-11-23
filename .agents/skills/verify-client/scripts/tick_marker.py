#!/usr/bin/env python3
"""The step marker (`tick_marker_on`, docs/TICK_RATE.md "The step marker"): with the law off no tick
writes `tick_mark`; with it on each tick does, its count with the tick's; off again, it stops. The
table is private: refused to an anonymous connection's SQL.

    tick_marker.py --run client-...      (a run launched with verify.py launch, any seed)

Checks, in order (owner SQL; the law set through `set_world_law`, a `law_override` row):

- off (the world's default): no tick writes `tick_mark` (no row, or one whose tick stays) over 1.5 s
  while `clock`'s tick moved on;
- on: within 2 s the row appears; five reads 0.4 s apart each find its tick between the two reads of
  `clock`'s around it, and its tick moving on with `clock`'s; over the reads, its µs time moved by
  14-20 ms a tick on average (`start_us`, the tick's reducer timestamp);
- anonymous SQL of `tick_mark` is refused (private);
- off again: the row's tick stays where it was 1.5 s later while `clock`'s moved on.

The law is put back as the world had it. Writes `RUN/tick_marker.json`. Python standard library only.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from earshot import ROOT, V, call, run, sql  # noqa: E402
sys.path.insert(0, str(ROOT / "living/tools"))
from law_values import own_laws  # noqa: E402

LAW = "tick_marker_on"
RESULTS = []


def check(name, ok, detail):
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS" if ok else "FAIL"), name, json.dumps(detail, default=str)[:300], flush=True)


def mark(rid):
    rows = sql(rid, "SELECT * FROM tick_mark")
    return rows[0] if rows else None


def clock_tick(rid):
    return sql(rid, "SELECT tick FROM clock")[0]["tick"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    rid = a.run
    was = own_laws(lambda q: sql(rid, q)).get(LAW, "false")
    try:
        call(rid, "set_world_law", [LAW, "false"])
        time.sleep(0.5)
        m0, k0 = mark(rid), clock_tick(rid)
        time.sleep(1.5)
        m1, k1 = mark(rid), clock_tick(rid)
        # No row, or (on a world where the law was on before) a row no tick moves.
        still = (m0 is None and m1 is None) or (m0 is not None and m1 is not None and m0["tick"] == m1["tick"])
        check("off: no tick writes tick_mark", still and k1 > k0, {"rows": [m0, m1], "clock": [k0, k1]})

        call(rid, "set_world_law", [LAW, "true"])
        t = time.time() + 2
        while time.time() < t and mark(rid) is None:
            time.sleep(0.1)
        # Each read of the row lies between two reads of `clock` (one SQL call each, a few hundred
        # ms apart): a row written by every tick holds a count between them.
        reads = []
        for _ in range(5):
            before = clock_tick(rid)
            m = mark(rid)
            after = clock_tick(rid)
            reads.append((m and m["tick"], before, after, m and m["start_us"]))
            time.sleep(0.4)
        current = all(m is not None and kb <= m <= ka for m, kb, ka, _ in reads)
        moving = all(b[0] > a[0] for a, b in zip(reads, reads[1:]) if a[0] is not None and b[0] is not None)
        check("on: each tick writes its count (between two reads of clock's), moving on with it", current and moving, reads)
        first, last = reads[0], reads[-1]
        per = (last[3] - first[3]) / 1000 / (last[0] - first[0]) if first[0] and last[0] and last[0] > first[0] else None
        check("on: its µs time moves 14-20 ms a tick on average", per is not None and 14.0 <= per <= 20.0, {"ms_per_tick": per})

        p = subprocess.run([sys.executable, str(V), "sql", "--run", rid, "SELECT * FROM tick_mark", "--anonymous"], capture_output=True, text=True, cwd=ROOT, timeout=120)
        said = (p.stdout + p.stderr).strip()
        check("private: anonymous SQL of tick_mark is refused", p.returncode != 0 and "tick_mark" in said, said[-200:])

        call(rid, "set_world_law", [LAW, "false"])
        time.sleep(0.5)
        m2, k2 = mark(rid), clock_tick(rid)
        time.sleep(1.5)
        m3, k3 = mark(rid), clock_tick(rid)
        check("off again: the row stops while the clock moves on", m2 and m3 and m2["tick"] == m3["tick"] and k3 > k2, {"rows": [m2, m3], "clock": [k2, k3]})
    finally:
        call(rid, "set_world_law", [LAW, json.dumps(json.loads(was)) if was else "false"])
    d = ROOT / ".local/living/verify" / rid
    d.mkdir(parents=True, exist_ok=True)
    (d / "tick_marker.json").write_text(json.dumps(RESULTS, indent=1) + "\n")
    bad = [r for r in RESULTS if not r["ok"]]
    print(f"{len(RESULTS) - len(bad)} of {len(RESULTS)} checks pass")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
