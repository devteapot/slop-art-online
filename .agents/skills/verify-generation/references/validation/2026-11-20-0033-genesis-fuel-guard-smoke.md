# Generation smoke in the scene gate, and seed freshness

Validated on the Spark on branch `genesis-fuel-guard`, rebased onto `origin/main` `bfbbc079`. Tooling, skill scripts and documentation only. Builds through `build-slot` with a private `CARGO_TARGET_DIR`, rustc 1.99.1 (aarch64). Server: a private `clockworklabs/spacetime:v2.14.1` container, `slop-genesisguard-opus` on `127.0.0.1:3445`. No model service, no Neo4j.

## What changed

`generation.py --run RUN --smoke` runs `check_seed` and the secrets check on a world launched by someone else (the scene gate's genesis fuel worlds), pausing it first. It does not run native digests, repeatability, floors or a build, and keeps the table snapshots only when a check fails. The gate registers it as `generation-default` (world), `generation-island` (island) and `generation-cullet` (cullet, cullet-laws). `living/tools/seed_fresh.py` (`scene_gate.py seeds`, run by `living-merge` before the check) compares the compiled seeds with `living/seeds/worlds/` without a publish or a build.

## Live checks

- `gate-1120012132-5bacae` (main `7fff6a61` plus this branch, `--cases generation-default,generation-island,generation-cullet --force --no-main-check`, `SLOP_GATE_GENESIS_HEADROOM=0`): world passed 60 of 60 checks and island 993 of 993. cullet failed 2 of 349: "the cases are of the world's generation" and "each band case's resident wears its entry, in its band, with its line, at its stage (11 cases)". cullet-laws failed 1 of 47: "the seed's laws are composed over the shipped script". The retry on fresh worlds (`-g1-cullet`, `-g2-cullet-laws`) failed the same way. The gate exited 1, and generation-cullet was `fail-unjudged` with the main check off.
- Those three checks and `seeds:cullet:looks` were then listed on the shared red-on-main list (main `bfbbc079`).
- `gate-1120013026-b6936e` (main `bfbbc079` plus this branch, same command): all three cases passed in the first pass, which added 0 s at scene time because it read the genesis worlds. generation-cullet passed with the note "only listed red checks failed", naming those three checks. The gate passed in 182 s, genesis included. The passing worlds kept 84 KB (world) and 5.9 MB (island) of evidence.
- `seed_fresh.py`: aske-coast and island fresh; cullet stale (look generation `c4-e61b01c0` in the seed against `c4-cbcc40bf` in `worlds/cullet/looks.json`, and 55 residents' looks), 0.17 s. `cullet_plan.py --check` passes.

## Not covered

The full suite (`generation.py --run generation-…`): only the smoke ran. Native digests, repeatability, floors (`cullet-laws-floor`, where the laws check is also reported red), authored compilation and guards. The cause of the cullet-laws laws-composition failure: it is fixed separately. Sheet freshness beyond names and narratives.
