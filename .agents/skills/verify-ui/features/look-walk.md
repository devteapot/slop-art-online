# Looking aside while walking

In the cursor scheme my character walks where the keys go and looks where the cursor points. The head turns toward the look first, then the chest, each up to its limit. Past them the legs come round toward the look on an eased curve, at most 45° off the travel (the diagonal takes). Past the back limit the legs walk backwards. The gait is always the file's directional takes for the travel as seen from where the legs face *now*. A sudden turn of the travel with the look held therefore sidesteps, crossing the legs, until the body has come round. Steady walking within the head and chest limits never crosses. The owner, play-test 5: "rotating the head with that movement, and only when you get past some degrees start to rotate the body"; and on crossing: "if you … just go full right … it makes sense that you're still crossing your legs". Code: `living/game/src/twist.rs` (`LookWalk`, the bone turns), `live.rs` (the legs' goal and easing), `gait.rs` (`blend_toward`, the feet log).

## Sub-features

- `presets`: `head` (head to 60°, no chest, the body brisk, `body_s` 0.22, backwards past 130°), `chest` (the default: head 50° + chest 40°, `body_s` 0.35, backwards past 135°) and `loose` (head 60° + chest 55°, `body_s` 0.6, backwards past 155°). The body's limit is 45° for all three, and the eyes take up to 12–15° more.
- `settings`: Settings › Play › "Looking aside" (`settings:look_walk:head|chest|loose`), kept in the settings file as `look_walk`. `LIVING_GAME_LOOK_WALK=<preset>[,head=…,chest=…,body=…,body_s=…,body_dps=…,back=…,eyes=…]` wins over the file. The live script's `lookwalk:SPEC` sets it mid-run.
- `head-first`: the neck and head take the turn up to `head`, then the spine and chest up to `chest` (`Motion::neck`, `Motion::twist`). Holding a look, the head chain loses the clip's own turn about its axis: the diagonal takes turn the head about 30° by themselves.
- `body-curve`: the legs approach their goal by `1 − exp(−dt / body_s)` a frame, capped at `body_dps` (450°/s for `chest`).
- `sidestep`: after a sudden turn of the travel with the look held, the crossover takes play until the legs have come round.
- `speed`: the look changes nothing the authority does with speed. The client sends no look while walking until look-2; then, per dev-box, velocity stays on the keys.

## How to get to it (user POV)

- F3 to "Face the cursor", or Settings › Play › Facing. Walk with WASD while the cursor points elsewhere.
- Settings › Play › Looking aside picks the preset.

## Driving it with drive.py

Preconditions: a scratch island world (`--seed island`). The scenario places the player on open grass west of Brackenford at (300, 330), by admin `place_at` (scene setup), and waits 5 s for the drawn body to catch up the teleport. It runs `LIVING_GAME_CONTROL=cursor` with the feet log on (`LIVING_GAME_FEET=<evidence>/feet.jsonl`).

- **Steady.** For looks 0°, 45°, 90° and 135° off the travel: `look:L;hold:W;wait:4;shot:steadyN;wait:2;stop`, walking east and west in turn.
- **Sudden 90°.** `look:0;hold:0;wait:3;hold:90`: walking north looking north, then east with the look held.
- **Sudden 180°.** `look:180;hold:180;wait:3;hold:0`: walking south looking south, then north (backwards) with the look held.
- Scenario: `check.py --run $R look-walk` (every preset; `LOOK_WALK_PRESETS=chest` for one). `LOOK_WALK_RECORD=1` also records each drive (`LIVING_GAME_RECORD=<evidence>/record`). `LOOK_WALK_REUSE=1` checks the last drives' logs again without driving. `LOOK_WALK_TAG=before` with another client's `CARGO_TARGET_DIR` keeps a second set beside them: an older client's feet log lacks `sim`, `heading`, `look` and the bones' yaws, so only its photographs and recording compare.

Checks, per preset (21 each):
- what was asked of the neck and chest is within the limits, exactly;
- as drawn, the head from the chest and the chest from the legs, median within 8° of what was asked;
- the head never more than its limit + 15° from the chest;
- no frame turns the legs more than 15° (frames over 50 ms, headless hitches, left out);
- each steady look: no crossing, and the legs settled where the preset puts them (±8°);
- each steady look: the authority's ground speed (segment speed) as straight (±2%), and the drawn speed as straight (±8%);
- after each sudden turn, any crossing ends within 3 × `body_s` + 0.6 s.

"Crossing" is either of two things. The crossover takes (`strafe_walk_cross_*`) weigh over 0.25. Or, while a forward or back gait dominates, the ankles cross by more than 3 cm in the legs' own frame. The diagonals' feet trace across the legs' frame by design (accepted in the clip lab), so they count only through the first test.

## Gotchas

- The feet log's yaws are Bevy's, each bone's +Z on the ground, which is the sim angle + 180°. The checks compare differences, and the legs against `heading` + 180°.
- `heading` is the authority's segment heading, which is the direction of motion: the legs are drawn on it. Under fov-1's `human_face` (not sent while walking until look-2) the travel itself bends up to `look_walk_deg`; the legs still follow it.
- The newcomer walks at 2.43 m/s here (2.6 × the speed gene, × 0.6 at energy under 10 for a fresh `Bender`). The speed check compares like with like within one drive.
- Brackenford's square is no place for this: separation from residents and roads (× 1.4) swing the heading and the speed.
- Only frames from the first scripted `look:` count. Before it the body stands wherever the last drive left it, and the first-time tip's click can strike. Since fov-client, `human_face` turns a standing body toward the cursor, so a run after `field` used to fail the leg-jump and chest checks on those setup frames alone.
