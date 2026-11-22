# Gate case on the Spark's X925 cores (gate216-x925, 2026-11-22)

A measuring branch at gate-remeasure 8b233ed9d, never for main. The case is 100 human fighters and 116 walkers on Cullet, with the
dev-box recipe's `series.sh`. The settings were warm (`poller.py`), L0 (`--no-profile`), a 20 s warmup and a 60 s window, and a fresh
world per run. Between runs the server was stopped and its replicas were cleared.

- Modules: main came from 4b9fa89cc. Its source is identical to that of gate-driver-main 05d6e6d04 outside `living/tools`, and it was
  built there. The relay arm came from 8b233ed9d, and the relay+(c) and relay-d40 arms came from d40a876f0. All were built with
  LIVING_SEED=cullet. Hashes are in `binaries.sha256`.
- Placement: the server container was pinned with `--cpuset-cpus 5-9,15-19` (X925). The driver, series, gate-load, relay-proto, poller
  and runners were run under `taskset -c 0-4,10-14` (A725). `cores.py` sampled each thread's CPU every second. The governor was
  `performance`, with cpufreq at 3.9 GHz (X925) and 2.8 GHz (A725) throughout.
- Order: main, relay, main, relay, then relay+(c) and relay-d40 interleaved (`plan.txt`, `plan-cuts.txt`). The driver is `driver3.sh`,
  run with `flock ~/slop-mq/battle.lock`.
- Load rule: a run had to start at a 1-minute load under 4. The run's own placement burst lifts the load to 10–14 during warmup, so the
  driver redoes a run when the window's load ends above 8 or rises more than 1.0 above its running minimum. This is stricter than
  "max > 8" for quiet runs. Redone runs are in `x925-summary-redo.json`.
- Results: `x925-summary.json` (per run) and `tables.json` (`tables.py`). The evidence is in
  `~/slop-evidence/gate216-x925-20261122.tar.zst`.
