# Seated cloth on the ground

Seat contact, stage 2a (docs/seat-contact/). A resident who rests outdoors in dry weather sits on the ground (`town.rs`: `sit_ground_down`, then the `sit_ground` loop; about three in ten stand at ease instead, by `world::hash(id, 0x5e47)`). When it gets up, it rises where it sat (`live.rs` `STAND_UP`, `stand_up_ground` at 1.6), and logs `seat: #ID gets up at (X, Y)`.

Staying seated (seat-glitches):

- **Rest renewals:** before doing-renew, the authority renewed a rest (an 8 s activity) by deleting its `doing` row and writing the next at the resident's next evaluation (`tick.rs` slots, once a second), which a viewer's frame delivers up to 200 ms later: 0.03–1.05 s without a row in the seat runs. `town.rs` keeps a sitter seated while its row is gone, for up to `RENEW_MS` (1.6 s), as long as it keeps still (no velocity on its motion row) and no other activity row comes. A new rest row in that time continues the sit, timed from the first row's `since_ms`, so settling down does not replay. `LIVING_GAME_PERF=seat` logs `seat: #ID rest renewed (row since A after B), N ms without a row: still seated`. Before, each renewal showed `stand_up_ground` for 0.03–1.0 s, then the whole `sit_ground_down` from standing.
- **No turn takes:** a seated or rising body plays no turn take (a standing clip that lifted it to its feet) and keeps its legs' yaw, so its seat behind it stays where its cloth's plane is. The head and chest still take a look. A standing body's turn target is its segment's turn end, `heading + turn × turn_s` (`turn` is a rate). The old `heading + turn` put it 55° or more off for 94 of 127 standing bodies in one world, and the turn take that never landed repeated every 1.3 s (seen on a held sitter in the verify-sync-match runs).
- **Far and near:** a far/near swap only changes which meshes show (`lookdev::far_models`); the animation runs on both. The far model's cloth (`FarCloth`) is skinned to the spring joints too, about an eighth of its weight. So resting springs keep the rotations they were last drawn with, instead of going back to the rigid pose. On waking they are settled from those rotations, and what is drawn eases from them to the simulation over 0.3 s (`characters.rs` `WAKE_EASE_S`). Before, the hem popped to the rigid pose at near → far and back 16–35° at far → near. The ease is needed because the seated loop turns the head 15–30°: held hair is off its hanging pose by the time it wakes, so taking the settled chains at once popped it, and resuming from the held pose swung it 17–33° a frame. While it sits and gets up, `live.rs` holds a `characters::SeatAnchor` on its body. This is a world-space plane through the terrain at the clips' seat, 0.39 m behind where the body is drawn, with the terrain's normal there. The plane is fixed for the sit. Its cloth spring groups are those whose VRM `comment` is `Skirt` or `Coat` (`characters::CLOTH_GROUPS`). Their tails are kept on the ground's side of the plane, after the legs' spheres. The contact's weight comes from the clips' own time (`anim::Anim::ground_seat`, `anim::seat_of`):

- it ramps in over 0.2 s up to 1.2 s into `sit_ground_down`;
- it is full through `sit_ground`;
- it is full in `stand_up_ground` until 1.3 s, then fades over 0.2 s of display time.

At weight 0 the plane lies `SEAT_SINK` (0.25 m) under the ground and rises with the weight, so cloth is lifted out, never thrown. The anchor goes once the clips have the body off the ground. No server read, write or subscription is involved.

The hem against the ground (hem-ground, `docs/seat-contact/hem-ground.md`) works on the same weighted plane, `SEAT_MARGIN` (3 mm) above it:

- **The chains:** a cloth chain's root that the pose puts under the plane is lifted onto it in the spring step, its offset from its bone moved with it (`characters::Springs::pass`, the joint's `Transform.translation`). A coat's side chains, rooted on a thigh lying on the ground in the female sit, were 22–25 mm under it.
- **The skinned cloth:** the seated character's skirted pieces (`characters::SKIRTED_PIECES`: coats, skirted smocks, aprons) are drawn with its own copy of their shared toon carrying the plane (`characters::seat_clamp`), and `toon_light.wesl` `seat_clamp` keeps every vertex above it in the main pass, the prepass and the shadows. Most of a coat's side panel at the seat rides the upper leg and hips, which no chain moves.
- `LIVING_GAME_SEAT_HEM=0` turns both off and leaves the 2a contact.

The body itself is placed by `characters::hips` (sit-hips, `docs/seat-contact/sit-hips.md`). In the ground clips' share of the pose (`anim::Anim::ground_share`), the hips' height goes from `hips_k` to 1 as the clip's hips come down from 0.45 to 0.17 of their rest height (`anim::ground_hips`). A short-legged child then rests on its seat, not 17 mm under it. Out of those clips the placement is unchanged. The asset view takes the same path for a ground clip's shot, and `cloth_check.py --terrain` places bodies the same way (`--compare-client` checks the hips and feet against a view's joint dump).

What a sitter plays is resolved per body when its clips are bound (sit-f-select, `docs/seat-contact/sit-f-select.md`). A generated adult wearing `trousers-f` and `boots-f` plays `sit_ground_down_f`, `sit_ground_f` and `stand_up_ground_f`; everyone else plays the originals (`living/game/assets/characters/clip_variants.json`, `anim::variants`). Everything above keys off the logical names. The `seat: #ID sits on the ground …` line ends with `plays CLIP`, the seated loop's animation. `LIVING_GAME_CLIP_VARIANTS=0` plays the logical clips for everyone, for an A/B on one binary.

## Sub-features

- `contact`: cloth tails stay at or above the ground while seated and getting up (at most 5 mm under). Hair and every other group are untouched. Whether a coated woman (`sit_ground_f`, coat chains rooted on her thighs) is simulated depends on the near-model cap (eight nearest the camera), so main passed or failed this by who was drawn near: −22 to −25 mm when she was, before hem-ground.
- `release` requires, for each fixture resident who sat before the wait, a `seat: #ID is off the ground` line after `sync:up`, or a `seat: #ID leaves sight getting up, D m from me` line (at least one sitter must be let go in sight, and none may leave sight seated). The authority walks a rising resident off at once while its drawn body still gets up at its seat; one that sat near the edge of sight (11 m) can leave sight before the clips have it off the ground, and its seat then goes with its fading body. That race made `off` red on dev-box's render gate (`gate-1121003721-recheck-seat-render-isl`: #9 sat 8.7 m away and was dropped from sight 0.4–1.6 s into its rise; hem-ground).
- `variants`: each sitter's `plays` is what its look line selects (`check.py`'s `seat_clips`, from the same `clip_variants.json`). The scene seats at least one variant sitter and one on the originals.
- `segments`: one variant sitter is followed in the feet log (`LIVING_GAME_FEET`, `LIVING_GAME_FEET_ID`, its `hips_at`). `seat.json`'s `on.segments` gives each ground one-shot's peak speed of the hips and feet from the root, over the 0.12 s crossfade in and after it, and the hips' mean height over the ground in the loop. It is evidence, not a pass mark: compare with a run under `LIVING_GAME_CLIP_VARIANTS=0` (where the `variants` checks fail by design).
- `renewal`: nobody seated rises across the authority's rest renewals (two in the scene; `doing` snapshots `held0` and `held1` show the row extended in place, a later `until_ms` with the same `since_ms` since doing-renew, or a new `since_ms` on older modules). The watched sitter's feet log has no one-shot over it and its hips stay under 0.35 m over the ground from the seated dump to `up`. Every sitter's one `seat: #ID gets up` line comes after `up`.
- `zoom`: across Far → Near → Far, the watched sitter stays seated by the same measure.
- `wake`: a seated character whose springs rest and wake (camera far, then near) starts where its chains were drawn (under 5° at waking) and does not swing (under 10° a frame after). Main's binary failed both: 23.9–34.9° at waking.
- `cost`: the contact on against off (`LIVING_GAME_SEAT_CONTACT=0`) with eight near characters in the crowded street.
- `view`: the asset view seats a model on its checker for a ground clip's shot (`view.rs`: an anchor at y 0 weighted by `seat_of` at the shot's time). Side stills of the contact on and off: `LIVING_GAME_VIEW=look:lk_… LIVING_GAME_VIEW_CLIP=sit_ground_down,sit_ground,stand_up_ground LIVING_GAME_VIEW_SHOTS="sit_ground@4.98/120:4:0.55:0.12,…"`.

## How to get to it

```bash
$S/check.py --run $R seat        # an island world; about 2 minutes, two drives
```

The scene is set up only through admin calls:

- `place_at` puts me in the crowded street (420.5, 255.5);
- `--place-free` puts four skirted and three coated residents in a ring 2.2 m round me, chosen by their look line's outfit;
- `set_weather false 900`, the epoch set to noon and `fov_on false` give a dry, lit, unscoped view;
- `set_behavior {"do": "rest"}` sits them;
- `sync:held0` (right after the seated dump) and `sync:held1` (just before `up`) snapshot their `doing` rows (owner SQL, `scene.json` `snaps`);
- the camera goes Far (`notches:-30`), Near, Far and Near while they sit, about 18 s in all;
- `sync:up` replaces their rest graphs with `set_behavior {"do": "goto", "target": "home"}`. The built-in home target resolves to each resident’s home on the island, and they rise without another placement.

`LIVING_GAME_PERF=seat` logs each seated character's cloth against its ground every 3 s (`seat: NAME ENTITY: N cloth joints, lowest tail X mm above the ground`), and `springwake` logs each waking. A sitter whose body leaves sight before it is let go logs `seat: #ID leaves sight seated|getting up, D m from me by the authority`.

## Evidence

- `seat-on/`, `seat-off/`: stills `00_standing` to `07_up` (with `04b_renewed`), dumps `standing`, `seated`, `rewoken`, `renewed` and `up`, `client.log`, `frames.csv` and `scene.json` (the `held0`/`held1` snapshots).
- `seat-on/feet.jsonl`: the variant sitter's frames.
- `seat.json`: per arm, who sat and who rose, who got up after `sit` (`gets_up`), the watched sitter's frames off the seated loop (`seated_off_loop`, on), what each sitter's loop played and what its line selects (`plays`, `selected`), the variant sitter's `segments` (on), the cloth reports, the seated characters' wakes, the springs line's µs per character-step, and frame p50 and p99.

## Limits

- The camera is top-down: the stills show who sits, not the cloth against the ground. Use the asset view's side stills for that.
- With play-test 10's bundle the skirts' tails did not reach the ground seated (lowest 34–78 mm above it). On the render gate's pinned set (`79072c65d37f`, coat chains v2) the coats carry chains; see hem-ground for what each sitter reports.
- The check reads the chains' tails, not the drawn vertices: the vertex clamp is measured by `cloth_check.py --hem` (docs/seat-contact/hem-ground.md), not here.
- Chairs and benches are not covered: they wait for seat markers in world data.
- The fixture uses play-test 10's assets, whose smock and apron files carry `Skirt` spring groups. Linked skirt files without them give no seated cloth or wake samples, and three checks fail for that, on main as well (handmade-hair record).
- The rise and settle-again first logged as "taking the camera far" (sit-f-select) was the 8 s rest renewal coinciding with the zoom. It is fixed above (seat-glitches).
- Only one sitter is followed frame by frame (`LIVING_GAME_FEET_ID`). The others are covered by their `gets up` lines and wakes.
- The wake checks cover seated characters with cloth chains (from their `seat:` reports). Hair on a seated coat wearer's body is not in the check.
- The renewal bridge keeps a sitter whose rest truly ended, with no motion and no new activity, seated up to 1.6 s longer.
- Since doing-renew (main ba63a7c0) the authority extends a continuing rest's `doing` row in place, so there is no gap; the `town.rs` bridge stays as a backstop.
