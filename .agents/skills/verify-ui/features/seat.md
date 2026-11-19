# Seated cloth on the ground

Seat contact, stage 2a (docs/seat-contact/). A resident who rests outdoors in dry weather sits on the ground (`town.rs`: `sit_ground_down`, then the `sit_ground` loop; about three in ten stand at ease instead, by `world::hash(id, 0x5e47)`). When it gets up, it rises where it sat (`live.rs` `STAND_UP`, `stand_up_ground` at 1.6). While it sits and gets up, `live.rs` holds a `characters::SeatAnchor` on its body. This is a world-space plane through the terrain at the clips' seat, 0.39 m behind where the body is drawn, with the terrain's normal there. The plane is fixed for the sit. Its cloth spring groups are those whose VRM `comment` is `Skirt` or `Coat` (`characters::CLOTH_GROUPS`). Their tails are kept on the ground's side of the plane, after the legs' spheres. The contact's weight comes from the clips' own time (`anim::Anim::ground_seat`, `anim::seat_of`):

- it ramps in over 0.2 s up to 1.2 s into `sit_ground_down`;
- it is full through `sit_ground`;
- it is full in `stand_up_ground` until 1.3 s, then fades over 0.2 s of display time.

At weight 0 the plane lies `SEAT_SINK` (0.25 m) under the ground and rises with the weight, so cloth is lifted out, never thrown. The anchor goes once the clips have the body off the ground. No server read, write or subscription is involved.

The body itself is placed by `characters::hips` (sit-hips, `docs/seat-contact/sit-hips.md`). In the ground clips' share of the pose (`anim::Anim::ground_share`), the hips' height goes from `hips_k` to 1 as the clip's hips come down from 0.45 to 0.17 of their rest height (`anim::ground_hips`). A short-legged child then rests on its seat, not 17 mm under it. Out of those clips the placement is unchanged. The asset view takes the same path for a ground clip's shot, and `cloth_check.py --terrain` places bodies the same way (`--compare-client` checks the hips and feet against a view's joint dump).

What a sitter plays is resolved per body when its clips are bound (sit-f-select, `docs/seat-contact/sit-f-select.md`). A generated adult wearing `trousers-f` and `boots-f` plays `sit_ground_down_f`, `sit_ground_f` and `stand_up_ground_f`; everyone else plays the originals (`living/game/assets/characters/clip_variants.json`, `anim::variants`). Everything above keys off the logical names. The `seat: #ID sits on the ground …` line ends with `plays CLIP`, the seated loop's animation. `LIVING_GAME_CLIP_VARIANTS=0` plays the logical clips for everyone, for an A/B on one binary.

## Sub-features

- `contact`: cloth tails stay at or above the ground while seated and getting up. Hair and every other group are untouched.
- `release`: everyone who sat is let go once up: one `seat: #ID is off the ground` line per `seat: #ID sits on the ground` line.
- `variants`: each sitter's `plays` is what its look line selects (`check.py`'s `seat_clips`, from the same `clip_variants.json`). The scene seats at least one variant sitter and one on the originals.
- `segments`: one variant sitter is followed in the feet log (`LIVING_GAME_FEET`, `LIVING_GAME_FEET_ID`, its `hips_at`). `seat.json`'s `on.segments` gives each ground one-shot's peak speed of the hips and feet from the root, over the 0.12 s crossfade in and after it, and the hips' mean height over the ground in the loop. It is evidence, not a pass mark: compare with a run under `LIVING_GAME_CLIP_VARIANTS=0` (where the `variants` checks fail by design).
- `wake`: a seated character whose springs rest and wake (camera far, then near: spring-near's far→near re-entry, reseeded and settled 60 steps with the contact) shows no swing after waking.
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
- `set_behavior {"do": "wander"}` and then `refree` (each put back on its own tile) get them up. A new graph alone does not end a rest, and since iter-11's needs pacing wander or `goto` home leave them seated 47 s later; a placement ends it.

`LIVING_GAME_PERF=seat` logs each seated character's cloth against its ground every 3 s (`seat: NAME ENTITY: N cloth joints, lowest tail X mm above the ground`), and `springwake` logs each waking.

## Evidence

- `seat-on/`, `seat-off/`: stills `00_standing` to `07_up`, dumps `standing`, `seated`, `rewoken` and `up`, `client.log` and `frames.csv`.
- `seat-on/feet.jsonl`: the variant sitter's frames.
- `seat.json`: per arm, who sat and who rose, what each sitter's loop played and what its line selects (`plays`, `selected`), the variant sitter's `segments` (on), the cloth reports, the seated characters' wakes, the springs line's µs per character-step, and frame p50 and p99.

## Limits

- The camera is top-down: the stills show who sits, not the cloth against the ground. Use the asset view's side stills for that.
- With today's assets (play-test 10's bundle) the skirts' tails do not reach the ground seated: lowest 34–78 mm above it. The rise brings them to 5–14 mm with the contact and −0.1–4.8 mm without. Coats have no spring chains yet, so the contact cannot move them (docs/seat-contact/COAT_CHAINS.md).
- Chairs and benches are not covered: they wait for seat markers in world data.
- Taking the camera far (`notches:-30`) makes a seated resident start getting up and sit again 0.2 s later, in both clip families (2026-11-19, sit-f-select): the interrupted rise crossfades to the descent's standing start in 0.09 s, the largest peak in `segments`.
