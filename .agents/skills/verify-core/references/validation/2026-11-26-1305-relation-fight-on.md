# relation-fight-on: `relation_fight_on` on by default

Follows `2026-11-23-0500-relation-fight.md`. This run is on branch `relation-fight-on`, commit `0f743d6ab`, on origin/main `9cbb8d50c`. `living/` had no uncommitted changes.

- **Machine:** the Spark (aarch64), rustc as `just living-check` builds it.
- **Server:** a private SpacetimeDB 2.14.1 `slop-rfon-20261126` (`127.0.0.1:3641`, `LIVING_STDB_CONTAINER`/`LIVING_STDB_URL`).
- **det_compare:** its own server `slop-rfon-det-20261126` (`:3642`), with copies on `:3643`–`:3646`.
- **Build:** a private `CARGO_TARGET_DIR` (`~/slop-rfon-target`), built through `~/slop-mq/build-slot`.
- **Lock:** every launch ran under `flock -s ~/slop-mq/trial-activity.lock`.
- **Models:** fake model only, no paid calls.

## The change

The law's default flips in two places: `laws()` in `living/scripts/skills.rhai` and `Laws::default()` in `living/rules/src/script.rs`. The rules test `attention_cues_are_the_world_s_laws` asserts that both are on. The law is still ordinary, and a world can still set it false.

The decision behind the flip was the general coordinator's (2026-11-23): merge the law off, run one paid real-mind island comparison of off against on, and switch it on by default unless law-on shows more than a modest effect on violence against rival or outlaw people.

The paid run is `relation-island-paid` `f84d93533`, `docs/RELATION_ISLAND_PAID.md` there; it cost $2.38. It found zero attacks, threats or fight starts against rival or outlaw people in either arm, and zero deaths.

That run's open observation, recorded in docs/WORLD_RULES.md "Default on": law-on had seven wolf attacks on Wren Ashby, against none with the law off. Wolves' graphs do not read the law, so this is probably chance, but the cause is undetermined.

Scenes that depend on the default now set the law explicitly:

- **verify-core `relation_fight`:** sets it off for stage 0 and on for stages 1–4, then restores the shipped value (on).
- **verify-player `strike`:** sets it on explicitly.
- **verify-minds `fight-field`:** sets it on explicitly.

The mind test `whom_one_fights_is_told_only_under_its_law` now checks that the shipped deliberation and consolidation prompts carry the order and the `fight` field, and that the law parses off.

## Checks

| Check | Run / evidence | Result |
| --- | --- | --- |
| `just living-check` | `.local/relation-fight-on/check.log` | ok in 608 s. Covers the authority, mind+viewer, game, game-tests, authority-tests (53), viewer-wasm, rules-tests (380 passed, 17 ignored) and the script gate. |
| living-mind cargo tests | `.local/relation-fight-on/mind-tests.log` | 147 passed, 14 ignored, including `whom_one_fights_is_told_only_under_its_law` |
| Fresh worlds carry the law on | `core-rfon-132815-skirmish/script-row.json` | The island world's installed `script` reads `relation_fight_on: true` |
| verify-core `relation_fight` (default seed) | `core-rfon-132815` | PASS 12/12. Law set off: a neutral row hides the war. Law on: A attacks B1 past the neutral row. A truce on B2 sends A to B3. `spare` over a hostile row on B4 sends A to B5. A person of no side is attacked only after A says `enemy`. `""` takes the word back. `mind_fight` refuses `never`. |
| verify-core `skirmish` (island) | `core-rfon-132815-skirmish` | PASS 8/8 |
| verify-core `sides_battle` (Cullet) | `core-rfon-132815-sides` | PASS 12/12: 60 fighters, 1,978 uses, 13 fallen by 30 s and 24 by 60 s. No use at a resident or at one's own side, and no resident dead. |
| verify-core `sides_layout` (same world) | `core-rfon-132815-sides` | PASS 12/12 |
| `verify_mechanics.py`, including the force and killing checks | `core-rfon-132815-mechanics` | 23/23 |
| verify-player `combat.py`, all scenes (island) | `player-rfon-133729` (`combat.txt`, `combat.json`) | 60/60. Includes "the player's strike makes the one struck its character's enemy (relation_fight: enemy, by player)". A first attempt stopped before any check: no player was joined (`combat-nojoin.txt`). |
| verify-minds `fight-field`, `roundtrip`, `conversation` (`--no-unit-tests`) | `minds-rfon-133753-*`, `.local/relation-fight-on/minds-rfon-133753.txt` | All pass. In roundtrip and conversation the law was left at its default, and the deliberation prompt and the consolidation prompt both carry the gloss "Whom your body counts as an enemy". The one consolidation request without the gloss is the starting-identity prompt. |
| det_compare melee, default seed, `spawn_battle_sides(60, 2)`, 3,600 ticks | `.local/relation-fight-on/det/melee/run/det-compare.json` | **identical:** 113 tables and 30,855 rows |
| det_compare island, no battle, 7,200 ticks | `.local/relation-fight-on/det/island/run/det-compare.json` | **differs, as expected:** see below |

### How the det_compare runs were set up

Both copies ran the same branch wasm. Each copy had a different script installed (`run --scripts`): main's shipped `skills.rhai` (law off) or the branch's (law on). The two scripts differ only in the law's value.

The only other difference between the builds is `Laws::default()`, and it applies only to a script without the key. Both scripts have the key, so this isolates the change.

### What the island det_compare shows

The island copies first differ at tick 38, in `activity`, `body`, `doing`, `skill_use`, `vitals` and `mind_state`. These are the residents' routines, which read `relation: enemy`/`friend` and the seed's regard stances. The differing `skill_use` samples are `face` and `step_aside` uses.

The divergence then spreads. One conception (`expecting`, "Sorrel and Clover are expecting a child") happens only in the base copy.

At the stop, 310 characters are alive in both copies, and `combat_seen` and `act_outcome` are 0 in both. The default changes where residents look and step, not whether anyone fights in these 2 game hours. The free island run of 2026-11-23 found the same with the law set on.

## Cleanup

- Every scratch world was deleted: pause, then SQL confirming the pause, then delete, with SQL now 404. This covers the harness cleanups and `det_compare.py delete` for `verify-det-1126-134212` and `verify-det-1126-134534`. The minds runs delete their own worlds.
- Both private servers were stopped with SIGINT after their logs were saved to `.local/relation-fight-on/server-logs/`. Both exited 0. The scene server's log has three WARN lines, all "Websocket receive error … Connection reset" when the mind services stopped; there are no panics.
- Evidence is archived in `~/slop-evidence/relation-fight-on-20261126.tar.zst` with its `.sha256`, before the containers, their volumes, the det template volumes and the wasm mounts were removed.

## Not covered

- Real minds with the law on by default beyond the paid island run. No paid calls were made here.
- Long runs, other seeds' residents (Cullet's routines with relation rows) and performance. The prompts grow by the gloss and the `fight` field, and that cost on model calls was not measured.
- Existing worlds: an existing world takes the new default only at `just living-publish`'s script install, unless it set its own value. A world whose script predates 2026-11-23 takes it at its next update. Neither path was driven here; the path is the one act-replace-on measured (docs/INPUT_LATENCY.md "How a law default reaches a world").
- The scene gate was not run as a whole.
- verify-client was not run: no table, view, reducer or subscription changed.
