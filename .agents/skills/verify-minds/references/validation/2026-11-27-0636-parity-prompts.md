# parity-prompts: `prompt_parity` world law (default off)

Branch `parity-prompts` from `origin/main` `e220bea8e`. Spark (aarch64), private SpacetimeDB 2.14.1 container `slop-parity-p1-stdb` (`127.0.0.1:3384`), private `CARGO_TARGET_DIR` (`.local/parity-target`), builds through `~/slop-mq/build-slot`, launches under `flock -s ~/slop-mq/trial-activity.lock`. Fake model only; no paid calls.

## Change

Adds the ordinary world law `prompt_parity` (default `false` in `living/scripts/skills.rhai` and `living/rules/src/script.rs`; read by `living-mind` via `prompts::prompt_parity()`, covered by `the_laws_minds_read_change_by_an_install`). When `prompt_parity` is `true`:

- **Authority (`perceive.rs`, `brain.rs`):** omits others' hunger (`"starving"`/`"hungry"`) and infant hunger/cold `body_state` overrides while keeping the character's own vitals/hunger/felt body; degrades visible `AboutToRelease` to `WindingUp`; omits others' `yielded` countdown, far-figure `family`, private `bond_offer` and `join_request` listings, and private structure `contents`; skips the global `know_how` scan behind `sole` and the private `rhythm` new-day trigger.
- **Mind (`mind.rs`, `mind/talk.rs`, `prompts.rs`):** omits private `rhythm` lines from persona, private `bond_offer` lines from `talk` `# Now` (keeping `trade_offer`), degrades `"about to release"` to `"winding up"` across `FAST_WAYS`/balanced fast frame, deliberation grammar, heed grammar, and `notice` cues, and omits private-table grammar terms (`bedtime`, `evening`, `work_hours`, `suitor`, `courted`).

No SpacetimeDB table, view, reducer, or subscription changed.

## Checks

| Check | Run / evidence | Result |
| --- | --- | --- |
| `just living-check` | `.local/parity-evidence/build-prompts.log` | PASS (all 8 steps, including `prompt_parity_is_the_world_s_law`) |
| `living-authority --lib` tests | `.local/parity-evidence/build-prompts.log` | 63 passed, 0 failed |
| `living-mind` cargo tests | `.local/parity-evidence/build-prompts.log` | 149 passed, 0 failed, 14 ignored (incl. `prompt_parity_degrades_about_to_release_and_omits_private_table_terms`, `the_laws_minds_read_change_by_an_install`) |
| `det_compare` law OFF vs `origin/main` (Cullet 200 + 16 players, 1,800 ticks) | `.local/parity-evidence/det-prompts-cullet200/det-compare.json` | **identical:** `ticks_compared=1800`, `ticks_differ=0`, 113 tables, 46,624 rows |
| `verify-minds` `roundtrip` | `minds-parity-prompts-20261127-061309-roundtrip` | PASS |
| `verify-minds` `conversation` | `minds-parity-prompts-20261127-061309-conversation` | PASS |
| `verify-minds` `prompts` (new case) | `minds-parity-prompts3-20261127-062427-prompts` | PASS (13/13: starving seen/unseen omitted, own hunger & felt body kept, rhythm/bond_offer/storage contents omitted, `about to release` degraded) |
| Cullet town + battle OFF vs ON real prompt diffs (fake model) | `.local/parity-evidence/prompts-cullet-diff/` (`town/diff-think.txt`, `town/diff-talk.txt`, `battle/diff-fast-sys.txt`) | Confirmed live reload on rev bump: town strips starving `#65`, `Your days`, `asked of you` (`bond_offer`), talk `# Now` `bond_offer`, storage `contents`; battle fast prompt degrades `"about to release"` to `"winding up"`; own `you.hunger` (`25->26`) kept; fake-model deliberation outputs remained valid (`wait` / `keep`). |

## Cleanup & Not Covered

- Every scratch database was paused and deleted via `verify.py cleanup` or `world_delete.py` (SQL 404 confirmed).
- Not covered: paid real-model behavioral drift under `prompt_parity=true`; `verify-client` (no table/view/reducer/subscription changed).
