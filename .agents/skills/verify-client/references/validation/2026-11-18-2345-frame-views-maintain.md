# frame-views: maintain-verification-skill, scoped (verify-client)

Follows `2026-11-18-2334-frame-views.md`. Outcome: **changed**, in the same branch as the surface change (no separate PR): frame-views changed the perception feature's shape (six tier views, three public cue event tables under row-level security).

Scope: the perception feature and the harness files this change touches; not the full source wave over every feature file (one subagent per file was not run). Source: the map was written from `living/authority/src/frame.rs`, `perception.rs` (the tier views) and `tables.rs` (`near`, `by_viewer_near`, the cue tables), and checked against `drive.py`'s inventories, which read the sources. Live: the fixed suite (`client-views-2313`, all 45 checks), `cues.py` (`client-viewsq-2324`, 14 of 14), `sweep_rows.py` on both arms with `--compare` (`-2324`, identical at 7 steps) and `look_rows.py` (`client-viewsl-2305`, 15) on the worker's own v2.14.1 server.

Corrections shipped:
- `features/perception.md`: a "Cues and tiers" bullet; `features/README.md`: its row (placed alphabetically; the map's older rows out of order, `Body sex` after `Identity-scoped`, were left as they were).
- `SKILL.md`: a "Cues and tiers" section for `scripts/cues.py` (new, executable).
- `scripts/drive.py`: `VIEWS` lists the six tier views (the inventory guard stopped the suite).
- `scripts/run.py`: the cleanup proof accepts the harness's "(name no longer resolves)" as well as "(SQL now 404)"; it failed on main's wording for runs that record a database identity (drift, not product).
- `scripts/probe`: streams the tier views and the cue tables (inserts only), and stamps each streamed change with its receipt time (`ms`).

Harness gap noted, not fixed: `scripts/sweep_rows.py` is not executable on main though the skill shows it run directly; run it with `python3`. Product gaps: none found.
