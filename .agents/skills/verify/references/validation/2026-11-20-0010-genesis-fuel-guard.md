# Scene gate: genesis fuel guard

Validated on the Spark on branch `genesis-fuel-guard`, rebased onto `origin/main` `7fff6a61` (rounds 1–3 on `3ed22a74`; its module is battle-views' `a407be01` with status-parts). Tooling and documentation only. Builds through `build-slot` with a private `CARGO_TARGET_DIR` (`~/slop-genesisguard-target/check`), rustc 1.99.1 (aarch64). Server: a private `clockworklabs/spacetime:v2.14.1` container, `slop-genesisguard-opus` on `127.0.0.1:3445`, removed by name afterwards. No model service, no Neo4j.

## Design

The gate publishes one fresh `verify-gate-<stamp>-fuel-<seed>` world per seed in `GENESIS_SEEDS`, reads `reducer_wasmtime_fuel_used` and `spacetime_reducer_plus_query_duration_sec_count` for that database identity and `reducer="init"` from `/v1/metrics`, and deletes the world through `verify.py cleanup` (pause, confirmed pause, delete; `world_delete.py`). It reads one metrics page per seed and adds no reducers, tables or subscriptions. Sources (v2.14.1, tag `a0bf6be1`) and the rules are in docs/TOOLING.md, "Genesis fuel".

## Live checks

- Three `--genesis-only` rounds on `3ed22a74`'s module (`gate-1120005238-50ce8d`, `gate-1120005551-c76f94`, `gate-1120005916-53fcd0`) and one on the rebased tree (`gate-1120010442-615c1d`). Every publish ran `init` twice. `init_fuel` per run was identical in all four for island 118,734,992,179, cullet 91,829,020,112, plan-test 26,997,746,345 and world 17,614,179,252, and 62,997,679,071.5–147.5 for cullet-laws. The island failed (98.95%, no baseline), the rest passed; island, cullet and cullet-laws warned (over 50%). Exit 1 each, 158–210 s.
- Must-not-rise, live (`gate-1120010733-9c6226`): with a scratch island baseline recorded by `genesis-baseline` from the round above and committed only to a dropped local commit, the island passed under `baseline + 0.1%` (limit 118.854e9) and the gate exited 0 (`passed genesis`, 158 s).
- All 20 scratch worlds were deleted: each `state.json` reads `published: false`, and the server listed no databases afterwards.
- Evidence: `.local/living/verify/gate-*` above, `.local/genesisguard/evidence/` (`main-1..3.json`, `final-1.json`, `baseline-live-1.json`, `measure-*.log`), archived in `~/slop-evidence/genesis-fuel-guard-2026-11-20.tar.zst`.

## Self-tests

`scene_gate_selftest.py`: all 60 checks passed, covering pass; fail under 10% headroom; an over-90% seed with no baseline; must-not-rise passing and failing; graduation; another rustc's baseline not used; a missing fuel or call-count metric (pure and through `Runner.genesis` on a fake server); one init run; a refused publish reporting its fuel; a failed cleanup; per-step pass, warn and fail of a staged report; the reporter run as a subprocess; `SLOP_GATE_GENESIS_HEADROOM` (5, invalid values) and `SLOP_GATE_GENESIS_CHECK=0` through the CLI; and `genesis-baseline`. `merge_selftest.py`: all 41 passed, including the genesis summary line on a failed gate.

## Not covered

A real out-of-energy `init` (no seed on this main exceeds the budget on rustc 1.99.1; the refused-publish path is covered with a fake server only). A real `genesis_fuel.py` (it does not exist yet; covered by fixtures in dev-box's format). Dev-box's toolchain. The island's real baseline, which waits for the status-parts revert on main. A full `living-merge --scenes` gate with scenes after genesis.
