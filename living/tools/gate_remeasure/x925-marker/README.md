# Gate case on X925 against the server step marker (gate216-marker, 2026-11-23)

A measuring branch at npc-measure `b18402236`, never for main. The case is 100 human fighters and 116 walkers on Cullet, relay arm,
with the step marker on (`--law tick_marker_on=true --tick-marker`), with and without (M) (`--law memory_off=1`). The idle world (Cullet's
64 residents, no battle, same build, marker on, `--no-profile`) ran FIRST in the same session (`series_idle.sh`), and again at the end as a
drift check.

- Module: `b18402236` built with `LIVING_SEED=cullet`, plus `gate-load` and `relay_proto` from the same tree (`binaries.sha256`).
- Analysis: dev-box's `living/tools/marker_steps.py` at `e16a43e5e` UNMODIFIED (the GC's idle clause: bound = max(17.5, idle p99 + 0.5)),
  its selftest 17/17 first; `python3 marker_steps.py --idle runs/idle-r1 runs/...` (`marker_steps.json`). No wrapper of our own.
- Placement: the server container `--cpuset-cpus 5-9,15-19` (X925); driver, series, gate-load, relay, poller and samplers under
  `taskset -c 0-4,10-14` (A725). `cores.py` per run: server CPU 100% on X925, host side 0% on X925, X925 at 3.9 GHz throughout.
- Order (`plan.txt`): idle, marker, marker+(M) out, marker, marker+(M) out, idle; warm (`poller.py`); fresh world per run; the server
  stopped by SIGINT (exit 0, never forced; logs read and kept) with replicas cleared between runs; `battle.lock` held for the series.
- Load rule: each run starts under a 1-minute load of 4; a run is redone when the window's load ends above 8 or rises more than 1.0 above
  its running minimum (mo-r1 and idle-r2 were redone once each). Others' CPU in each window: `others.py` (0.5-0.7 cores mean in the arms).
- Results: `marker_steps.json`, `summary.jsonl` (`summarize.py`: DB ms/s, placement, loads). Evidence:
  `~/slop-evidence/gate216-marker-20261123.tar.zst`.
