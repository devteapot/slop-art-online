# What someone is visibly doing

Since `doing-percept` (2026-11-12; docs/PERCEPTION.md, "What someone is visibly doing"; docs/COMBAT_MIND.md §3.2). What another creature's body shows, and how far into it, is read from the rows a player's client draws from: its `fighter` row's move (a combat move, by its timing) and else its `doing` row (a skill with an act card). The same sight rule decides who it reaches (`perception::sensed`: sight, the field when `fov_on` is on, the sight line). No table, column, view or subscription changed.

## Source

- `living/rules/src/doing.rs`: the phases (`winding up`, `about to release`, `releasing`, `recovering`, `holding`, `under way`), `move_phase`, `act_phase`, the kind words (`hostile`, `melee`, `missile`, `guard`, `dash`, an act card's look), `is` (name, label or kind word). Cargo: `doing::tests`.
- `living/rules/src/graph.rs` `Cond::Doing` / `DoingCond`, its check and `describe_cond`; `living/rules/src/normalize.rs` (`doing`, `is_doing`, `visibly`; `act`/`skill` for `is`, `"at": "me"` for `at_me`). Cargo: `normalize::tests::doing_reads_what_someone_visibly_does`.
- `living/authority/src/perception.rs` `visibly` / `Visibly::at` / `Visibly::is` (two point lookups). Cargo: `perception::doing_tests::a_move_is_at_me_by_its_target_or_its_drawn_aim`.
- `living/authority/src/brain.rs` `Cond::Doing` (over the evaluation's scene; span `brain.doing`); `living/authority/src/perceive.rs` `scene_json` (each creature's `visibly`: `is`, `phase`, `at` = `you` or the id of a target in sight).

## Sub-features

- **The routine reacts at the phase** (`scenes.py doing_seen`, default seed, about 2 min). On an open line W faces east; its routine dodges when a person in sight is about to release a hostile move at it. Field on (near ring 0.5 m): A's attack 2 m ahead is dodged in the second half of its 650 ms windup (`skill_use.at_ms` of the dodge against the attack's `accepted_ms`/`released_ms`); B's attack from 2 m behind is not dodged. Field off: the dodge again starts in the second half, A's blow does not land, and W's scene (a `think` in the branch) shows A `visibly` `{is: attack, phase: about to release, at: you}`.
- **Far and beyond** (same scene). An overlay of `perceived_of` makes anyone beyond 3 m too far away to make out. W's routine reacts to a person holding up a guard: F's guard 5 m off triggers it, and W's scene lists F as `someone too far away to make out` with `visibly` `{is: block, phase: holding}` (and `at: you` when F happens to face W: a guard's drawn aim); G's guard 14 m off (beyond the day's 11 m sight) does not.
- **A dodge runs its course** (since `committed-moves`, 2026-11-12; was a known XFAIL): with the field on, the dash turns W's back on A and the routine's condition stops holding, but the dodge is committed (docs/COMBAT.md "Committed moves"): it ends `made way` and A's blow misses. Before, it was broken off about 66 ms in and the blow landed.
- **Held between two uses** (since `doing-renew`, 2026-11-19; `scenes.py doing_renew`, default seed, about 2 min). A continuous shown activity (an act card that is not a gesture, a turn or a pace aside: `town::continuous`; rest, sleep, work, eating, play) that ends well, for a body no person plays and under the `renew_in_place` law, keeps its `doing` row as it was (`town::hold`, in `act::finish_as`). A `doing` row with no activity behind it is held. At the body's next evaluation: `act::begin` with nothing under way lets it give way (`town::unhold`; the same activity shown again in that transaction keeps its `since_ms`, `town::shown`, so subscribers get one update); an evaluation that leaves the body with nothing under way deletes it (`town::settle`), unless it is the one that read that activity's end (`brain.rs` `read_end`; not a finished `seq` plan, not a played body). `perception::visibly` reads a held row as under way past its end and `perception::doing_of` names its skill. The begin timing is unchanged. The scene: a resident under a lone rest desire, polled every ~25 ms for 34 s: no sample lacks the row, the next rest begins about a second after the last ended as before (median 500 ms or more, none past 1.1 s), `since_ms` kept; the same under a `first` root; a graph that walks it off removes the row within a second (walking is not shown); with `renew_in_place` off the row is absent after each rest again. `--baseline` on a build before doing-renew records the old gaps without asserting.
- **What subscribers get** (`scripts/doing_deltas.py --run "$R" [--battle N]`, a measurement, no pass mark): the owner's `SELECT * FROM doing` and a joined player's `SELECT * FROM seen_doing` through verify-client's probe for 60 s, the player at the busiest spot (or beside `spawn_battle N`); inserts, deletes, updates, row operations and blinks (a row deleted and inserted again within 1.5 s) per second, and the tiers' and cues' counts. Turns (`face`) and a walk between two plays or two bushes still blink: each is a different activity.
- **Cost** (`scenes.py doing_cost`, a measurement, no pass mark): `spawn_battle` N (default 100) spear fighters within 14 m; two `bench.py` windows, the battle's `threatened` graphs, then the same graphs guarded by `doing`. Reports `brain.doing`, `brain.scene`, `tick.combat` and the tick in `doing_cost-cost.json`. `DOING_COST_N`, `DOING_COST_S` set the size and window.

## Driving it

```bash
python3 .agents/skills/verify-core/scripts/scenes.py doing_seen --run "$R" > ".local/living/verify/$R/doing_seen.txt" 2>&1
python3 .agents/skills/verify-core/scripts/scenes.py doing_renew --run "$R" > ".local/living/verify/$R/doing_renew.txt" 2>&1
python3 .agents/skills/verify-core/scripts/scenes.py doing_cost --run "$R" > ".local/living/verify/$R/doing_cost.txt" 2>&1
# Measurements (the probe built, verify-client SKILL.md): a town (--seed cullet) or a battle.
python3 .agents/skills/verify-core/scripts/doing_deltas.py --run "$R" --seconds 60
python3 .agents/skills/verify-core/scripts/doing_deltas.py --run "$R" --seconds 60 --battle 100
```

Evidence: `doing_seen-scene-front.json`, `doing_seen-scene-far.json`, `doing_seen-uses-*.json`, `doing_seen-cast.json`, `doing_seen-actions.jsonl`; `doing_cost-bench-*.json`, `doing_cost-cost.json`; `doing_renew-samples-*.json`, `doing_renew-renewals-*.json`, `doing_renew-summary.json`; `doing-deltas-<town|battle>.json` and its two streams.

## Gotchas

- The scene snapshot is the `deliberation` row's latest `scene`: a blow that lands asks again ("… is attacking you!") and overwrites it. The scene check therefore runs in the all-round probe, where the dodge carries through and no blow lands.
- A `think` asks only 45 s after the character arrived; the scene sleeps until then.
- `doing_cost` leaves its fighters on `wait` graphs; run it last on a run, or on its own.
- The far overlay and the field laws are restored in a `finally`; a run interrupted mid-scene keeps them until cleanup deletes the database.
- `doing_renew` reads the rest's length (8 s, `rest_duration`) to time each renewal: a script that changes it changes the authority gaps the scene computes.
- In `doing_deltas.py --battle`, the fighters attack the nearest person, the player too: it is soon dead and its `seen_doing` stream says little. The owner's `doing` stream there is mostly the world's residents gathering; fighting moves have no act card.
