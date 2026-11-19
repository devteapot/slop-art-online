# Mechanics fixture validation

The four failures in the read-only `ea041af1` comparison were a wound cutoff set at five HP, a full pack at fishing and clearing, and smoking attempted without fish after fishing failed. The fixture now waits for a new attack experience from the scripted attacker, checks a drop relative to the reported damage, and requires a new care experience plus HP recovery above the projected natural rate. The fishing fixture clears the pack, provides three fiber, stocks a nearby fishing node, and verifies two fish from one gather. The crafting fixture clears the pack and supplies its own fish, wood, fiber, stone, and hide. The clearing fixture starts with an empty pack and verifies two wood.

All standalone runs used a scoped `world` seed authority on `slop-trials-stdb`, SpacetimeDB 2.14.1 at `127.0.0.1:3320`. The proof module was built from `f592a072`. The independently rebuilt `ac601063` authority matched the proof module in every standard WebAssembly section. Only the custom name section differed. The branch is based on `e382e06a`, which has the same default-seed authority inputs as that rebuild. See `module-parity.txt` in the evidence archive. Fixture inputs and effects were driven by existing reducers and read back with indexed inventory, experience, and vitals queries. [SpacetimeDB index guidance](https://spacetimedb.com/docs/tables/indexes/)

The driver published each database directly, under `flock ~/slop-mq/battle.lock`. Run 1's recorded clearing action awarded two wood 224 seconds after publish, and cleanup issued its pause at 253 seconds. Runs 2 and 3 sampled the running world at launch and after 120 seconds. Both later samples returned `paused = false` with advancing ticks (7,363 → 7,483 and 7,423 → 7,543). The failure messages in the original comparison record live action refusals. The orphan guard was not involved in the standalone proofs.

Each fresh run saved `mechanics.txt`, `mechanics.json`, and `stdb-actions.jsonl` in its `.local/living/verify/<run>/` directory. Run time starts once the battle lock is acquired and includes pause, deletion, and SQL 404 confirmation.

| Run | Checks | Time |
| --- | ---: | ---: |
| `core-mechanics-fixture-1119-084036-1` | 23/23 | 263.94 s |
| `core-mechanics-fixture-1119-084036-2` | 23/23 | 251.16 s |
| `core-mechanics-fixture-1119-084036-3` | 23/23 | 258.22 s |

Evidence archive is `~/slop-evidence/mechanics-fixture-2026-11-19.tar.zst` with its SHA-256 sidecar. `just living-check` passed. Coverage is the mechanics scene, the project checks, and the gate dispatch dry run. The full live merge gate and scale workloads are outside this proof.
