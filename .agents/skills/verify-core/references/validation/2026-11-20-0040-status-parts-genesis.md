# status-parts-genesis: the island's init back under its energy budget

Follows [status-parts merged](2026-11-19-2240-status-parts-merge.md). Main b5a3a3c4 (status-parts) made the island seed's `init` run out of energy at publish (SpacetimeDB 2.14.1's 120e9 per call; dev-box). Branch `status-parts-genesis` on main 3ed22a74; the code as measured is 25e967df. Private scratch server `sao-statusparts-fuel` (`clockworklabs/spacetime:v2.14.1`, 127.0.0.1:3420), no mind service, no model calls.

## The cause and the fix

Nothing status-related runs per body at `init`: `status_of` is asked only from brain evaluations (`brain::alerts`, AI-held bodies), which `init` never runs. The cost was the install check (`check.rs` `body`), run by every `validate` (`init` validates the shipped script, and `floor::check` again with a seed's laws): for each of 189 sample bodies it ran every part, the parts path and the whole law twice. Now, when `status_of` is written as its declared parts joined in order (`fields::is_join` over the AST: as shipped, and in every floor that keeps it), the install runs the parts over the samples (their answers checked, mostly from memo) and the law once for the fuel report; any other `status_of` is still compared sample by sample, the law run once per state it can tell apart. The comments added to `skills.rhai` were shortened: each `init` compiles the source several times.

## init fuel

`reducer_wasmtime_fuel_used{reducer="init"}` over the two inits a `verify.py launch` runs (`spacetime_reducer_plus_query_duration_sec_count` 2), per init. Fuel repeats exactly for one build (three island launches of each arm); builds that differ in Rust code move it by up to about ±0.15e9 on the island and Cullet.

| Seed | 5bea89b5 | main 3ed22a74 | branch 25e967df |
| --- | ---: | ---: | ---: |
| island (also the player worlds) | 118.52e9 | 118.73e9 | 118.32e9 |
| Cullet | 91.02e9 | 91.83e9 | 90.74e9 |
| default | 17.30e9 | 17.61e9 | 17.31e9 |

These absolute values are about 1.3e9 below dev-box's for the same commit (5bea89b5's island 119.79e9 there); compare differences.

## Checks

- Island publish; scene gate (`scene_gate.py run --cases skirmish,combat,cues,motion_tables`): skirmish pass (island), combat pass (player, island), motion_tables pass, cues flaky-pass (the first run, beside a `just living-check` build, missed "A receives each of B's strike windups first by a cue, within 100 ms"; the retry on a fresh world passed).
- `core-spg-005701`: `status_parts` 7/7, `alarms` 6/6, `cheap_alarms` 3/3. `player-spg-005701`: verify-player `status.py` 6/6.
- `just living-check` passed all nine steps (584 s); rules 358 passed, 17 ignored (the new `is_join` cases in `each_part_is_kept_on_what_it_reads`).

Evidence: `~/slop-evidence/status-parts-genesis-2026-11-20.tar.zst` (fuel logs and metrics per launch, the variant patches, the cold-memo runs, the gate's and the scenes' run folders).
