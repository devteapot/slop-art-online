# The hem against the ground (hem-ground)

Status: **built on branch `hem-ground`** (2026-11-21, from main `b20dea4b7`), not merged. It needs a dev-box render pass first: it changes the toon shaders. Client-only: `living/game/src/characters.rs`, `style.rs`, `toon_light.wesl`, `toon_vertex.wesl`, `toon_prepass.wesl`, `live.rs` (a log line), `perf.rs` (a doc line), the measuring tool `living/tools/characters/cloth_check.py`, and verify-ui's `seat` scenario. No server read, write, subscription or authority change, so no SpacetimeDB feature is involved.

It follows coat chains v2 ([coat-port/README.md](coat-port/README.md)) and the laptop's gate of it (`origin/coat-v2-2a`, `docs/seat-contact/coat-port/laptop-2a.md`), whose first next step was "a hem-against-ground constraint in the client's spring step".

## Where the residual was

Before building anything, `cloth_check.py`'s own poses were taken apart per vertex on the render gate's pinned asset set `79072c65d37f` (16 poses a clip, springs and the 2a contact on). These are the coat vertices deepest under the terrain, and the bones that carry them:

| Fitting | Clip | Deepest | Its weights (bind height) | Chain roots |
| --- | --- | ---: | --- | --- |
| Woman, cut 2 | all three | 18.8–19.2 mm | upper leg 0.60, hips 0.25, `CoatSide` 0.12–0.15 (0.835 m) | `J_Sec_{L,R}_CoatSide` heads 22–24 mm **under** the ground |
| Elder, cut 2 | descent | 27.2 mm | hips 1.00 (rear centre, 0.88 m) | all above |
| Elder, cut 2 | rise | 26.7 mm | `CoatSide2` 0.90, hips 0.10 (hem, 0.689 m) | `CoatSide` head 5 mm, `CoatSide2` 3 mm |
| Man, cut 0 | descent | 3.9 mm | hips 1.00 (rear centre) | all above |

Weighted by depth, the woman's under-ground vertices ride the upper leg 40%, the hips 23% and the chains 24%. So **a constraint on the spring joints alone cannot reach the 5 mm target**. A joint moves its vertices by their weight on it, and the woman's worst vertex has 15% there. Measured, the chain part of the design below (`cloth_check.py --hem joints`) leaves the woman at 15.9 / 15.4 / 15.4 mm and the elder at 27.2 / 0 / 22.1 mm. Coat-port's own trial of moving those weights onto the chains brought walk and run crossings, so weights are not the fix either.

## The constraint

Both parts use 2a's seat contact as it is: the plane through the terrain 0.39 m behind the body, with the terrain's normal, weighted by the clips' time (`anim::seat_of`), lowered `SEAT_SINK` (0.25 m) at weight 0. They hold everything `SEAT_MARGIN` (3 mm) above it. Weight comes in over 0.2 s up to 1.2 s into `sit_ground_down`, holds through `sit_ground`, and goes after 1.3 s of `stand_up_ground`. So both blend in and out with the sit, and nothing pops: at weight 0 the plane is 0.25 m under the ground.

1. **The chains, in the spring step** (`characters::Springs::pass`). A cloth chain's root (`Skirt`/`Coat` group, a joint hung on a body bone) that the pose puts under the plane is lifted onto it along the normal. Its offset from its bone moves with it and is written to the joint's `Transform.translation`: only cloth roots, and only when it changes. The chain then lies on the ground from there, and 2a's tail rule (a radius above the plane, flat at most when the root is low) does the rest. The woman's side chains, rooted on her thighs, were 22–25 mm under the ground in the client (the dev-box gate's red `on` arm). Cost: one plane test per cloth root a step.
2. **The skinned cloth, in the toon vertex shaders** (`characters::seat_clamp`, `toon_light.wesl` `seat_clamp`). A seated character's skirted pieces (`SKIRTED_PIECES`: coats, skirted smocks, aprons, as `cloth_check.py`'s `OUTER`; near and far meshes) are drawn with that character's own copy of their shared toon. The copy's new `seat` parameter holds the weighted plane, the margin up. `toon_vertex.wesl` and `toon_prepass.wesl` move every vertex below it onto it along the normal, after the plants' sway, so the main pass, the depth and normal prepass (lines) and the shadows agree. A coat panel pressed under a thigh then lies flat on the ground. Every shared toon has `seat` zero, which the shader skips: nobody standing or walking draws differently. Only a seated character's skirted pieces leave their batch, one copy for each character and shared toon. At weight 0, or when the anchor goes, they take the shared toon back and the copy drops with its last handle. `style::apply`, which rewrites every toon's parameters on a style change, keeps `seat`.

`LIVING_GAME_SEAT_HEM=0` turns both off and keeps 2a's contact. `LIVING_GAME_SEAT_CONTACT=0` turns everything off. `cloth_check.py --hem` models both parts (`--hem joints` the chains alone). `SEAT_MARGIN` and `SKIRTED_PIECES` are the client's and the tool's both.

**Why not per-joint hem radii.** The brief suggested a per-joint clamp with a skin offset or hem radius. The table above is why it is not enough here: two of the four worst cases are carried by the hips or the upper leg, not a chain. A radius large enough to keep a chain's skin above the ground would also stand the chain up off the ground. The elder's rise hem lies 30 mm under its flat chain, so the chain would rise about 20°: a hovering hem rather than cloth on the ground. The vertex clamp is exact and costs one dot product a vertex on seated cloth only.

## Results

### Ground (the 12 numbers)

`cloth_check.py LINE --clip sit_ground_down,sit_ground,stand_up_ground --frames 16 --seat-contact --ground-clips select --heights …`, as laptop-2a ran it, with `--hem` added: fitted bounds, the height-dependent hips blend, the rise at 1.6×, the woman on the female clips. The lines are the four shipped fittings (`docs/char-port-1/fittings.json` `port`). The styles, types and clips are the pinned render set `79072c65d37f`, copied from dev-box. Maximum coat depth under the terrain (mm):

| Fitting | Phase | Laptop v2 (laptop-2a) | Pinned set, 2a contact | Chains only (`--hem joints`) | hem-ground (`--hem`) |
| --- | --- | ---: | ---: | ---: | ---: |
| Woman, cut 2 | Descent | 17.90 | 19.2 | 15.9 | **0.0** |
| Woman, cut 2 | Seated | 17.52 | 18.8 | 15.4 | **0.0** |
| Woman, cut 2 | Rise | 17.52 | 18.8 | 15.4 | **0.0** |
| Man, cut 0 | Descent | 3.90 | 3.9 | 3.9 | **0.0** |
| Man, cut 0 | Seated | 0.00 | 0.0 | 0.0 | **0.0** |
| Man, cut 0 | Rise | 0.00 | 0.0 | 0.0 | **0.0** |
| Elder, cut 2 | Descent | 26.04 | 27.2 | 27.2 | **0.0** |
| Elder, cut 2 | Seated | 0.00 | 0.0 | 0.0 | **0.0** |
| Elder, cut 2 | Rise | 25.60 | 26.7 | 22.1 | **0.0** |
| Girl, cut 1 | Descent | 0.00 | 0.0 | 0.0 | **0.0** |
| Girl, cut 1 | Seated | 0.00 | 0.0 | 0.0 | **0.0** |
| Girl, cut 1 | Rise | 0.00 | 0.0 | 0.0 | **0.0** |

- **The 0.0 is by construction.** The clamp holds the vertices `SEAT_MARGIN` above the weighted plane, and every worst pose falls where the weight is 1. The "chains only" column is how far the shader moves the deepest vertex: at most 27 mm, on the elder's rear centre in the descent.
- **The pinned set reads 1.1–1.3 mm deeper than laptop-2a's v2 archive** on the woman and the elder (same generation `c4-cbcc40bf`). The set's bundle is from a later commit (`3c509fc3`). The difference is in the inputs, not the method: both columns use the same tool.
- **Layer crossings:** every pair and clip maximum with `--hem` equals the run without it. For example, the woman's trousers through the coat stay at 36.4 mm in the loop, and the elder's jersey through the coat at 20.3 mm. Those are coat-port's known layering cases, assigned to Astra.

### Gaits and idle

`--clip idle,walk,walk_brisk,run --frames 16`, springs off, springs on, and springs on with `--hem`, for the four fittings:

- **Gaits:** none comes through by more than 2 mm in any of them.
- **Idle:** the springs carry the cloth at most 1 mm in idle (v2: 1.08 mm).
- **`--hem`:** its output is byte-identical to without, as it must be: no ground clip, no anchor.
- **In the client:** a body that is not sitting has no anchor, so the spring step takes the same path as before. Its skirted pieces keep their shared toons, whose `seat` is zero.

### Spring step cost

`perf.sh` (`.local/hem/`): eight near (me, four skirted and three coated residents in a ring 2.2 m round me in the crowded street), Middle camera, a dry noon, windowed Metal at 1600×900, stock presentation (about 120 Hz). Each run had 18 s of warm-up and a 32 s window. The same tree's binary without the change ("base") alternated with this branch's ("hem") on one scratch world. Medians of three seated pairs and two standing pairs:

| Arm | Spring CPU µs/frame | µs/character-step | Spring wall µs/frame | Frame p50 / p95 / p99 ms |
| --- | ---: | ---: | ---: | ---: |
| base, seated | 9.20 | 2.30 | 14.1 | 8.18 / 9.87 / 10.10 |
| hem, seated | 13.02 | 2.42 | 19.9 | 8.24 / 10.44 / 11.10 |
| base, standing | 13.48 | 3.37 | 19.4 | 8.14 / 9.92 / 10.20 |
| hem, standing | 12.46 | 3.11 | 19.0 | 8.13 / 9.91 / 10.20 |

- **Seated:** the per character-step pairs were 2.21 → 2.35, 2.30 → 2.42 and 3.16 → 3.94 µs (+5%, +5%, +25%). The per-frame median includes the one hem window that dropped to 95 fps, with 5.2 characters a frame against 4.0 (p95 17.3 ms), like laptop-2a's run 6.
- **Standing:** standing (where hem-ground does nothing) read higher than seated in both arms, run later on a warmer machine. So the host's drift is of the same size as the difference.
- **Against laptop-2a's baseline:** its 6.18 µs a frame came from its eight-coat Cullet fixture, whose scripts were not kept. These eight carry four 12-joint smocks, so the two absolute numbers do not compare.
- **What this shows:** the chain lift adds at most a few tenths of a µs per character-step while seated, and nothing standing.
- **The vertex clamp:** its GPU cost is one dot product a vertex on seated skirted pieces. Frame times stay at the display's 8.3 ms in both arms.

Evidence: `.local/living/verify/ui-hem-a/ui/perf-{base,hem}-{s1..s3,t1,t2}/` (client.log, frames.csv), summary `.local/hem/perf.json`.

## The "never let go of the ground" fail

dev-box's red `seat` (`gate-1121003721-recheck-seat-render-isl`, `off` arm: sat [2, 7, 9], let go [2, 7]) is **neither cloth nor the authority**. It is the client's sight path racing the rise:

- **Where #9 sat:** in that world #9 rested 8.7 m from the player, against 2–3 m in the passing run. The sight there is 11 m.
- **What the log shows:** at `sync:up` the authority walked it home at once, while its drawn body stayed at its seat for the 1.54 s rise (`live.rs` `STAND_UP`). It logged `gets up` at 23:42:22.07 and never `is off the ground`, though the client ran 6.1 s more (#7, 2.4 m away, was let go 1.65 s after its `gets up`). By the `up` dump #9 was neither perceived nor drawn (`perceived` [6, 29, 39, 48, me]).
- **What happened in the client:** a body the authority no longer sends leaves `live.shown` through the fading path. The release (`ground_seat() <= 0` while `shown`) is never reached for it. Its anchor goes with its fading body, which is right: the fading figure stays seated where it was last drawn.
- **The pass:** the passing run had its sitters 2–3 m away, and all were let go in sight.

The authority's `doing` rows were sound: held0 → held1 extended in place for every sitter, and the `goto home` behaviour took. No authority change is needed.

**The fix.** `live.rs` now logs `seat: #ID leaves sight seated|getting up, D m from me by the authority` when a body that holds a seat leaves sight. `check.py seat`'s release check counts a sitter that left sight getting up after `up` as accounted for. It still fails a sitter that left sight seated, or one never accounted for, and needs at least one let go in sight. The check is renamed "everyone who sat got up and was let go of the ground after up (or left sight getting up, its seat with it)".

## The red `on` arm

dev-box's `on` fail ("seated cloth tails … lowest −24.9 mm", 43 reports) and its pass differ in one thing. In the fail, the woman in the coat (#9, `lk_ad820ac25bdef562`, `sit_ground_f`) was drawn near and simulated: her tails read −21.4 to −24.9 mm, her coat's side chains rooted on her thighs under the ground. In the pass she was on the far model (`lod` far: 9, 10), so she was not simulated and sent no report. The near cap (eight nearest the camera) decides that by chance, so the case was intermittent.

On this laptop, with the pinned set, she was drawn near in several runs:

- **Main's binary:** −22.0 mm in the contact-off arm (run hem-1), and −25.8 / −39.4 mm in the cost runs.
- **hem-ground:** 2.0 to 4.2 mm.

## verify-ui on the pinned set

The laptop runs used set `79072c65d37f`, copied read-only from dev-box (`render_set.py check`: ok; linked with `render_set.py link`), on the island world `verify-ui-hem-a`, with headless release clients.

- **`seat`:** 5 runs of the final binary, **5 green** (20 passed, 0 failed each), plus one green run of an earlier build of the same change (`hem-1`).
  - **The coated woman:** `lk_ad820…` was drawn near and simulated in every run. Contact on, her lowest tail was 2.0–2.1 mm. Contact off (hem off with it), −22.0 to −39.4 mm, the condition that turned dev-box red.
  - **Everyone else:** all four sitters were let go in sight in every run.
  - **Wakes:** under 3° a frame after waking, 0.0° at waking.
- **`seat` with main's binary:** one green run, in which the coated woman was on the far model. The cost runs, where she was near, showed main's tails at −25.8 and −39.4 mm, which fail its `on` check.
- **The sight race,** driven alone (`edge.sh`: #9 rested 8.7 m away, as in dev-box's fail, and #7 2.2 m away, both then sent home):
  - **Main's binary:** #9 `gets up` and is never let go, as on dev-box.
  - **This branch:** `#9 leaves sight getting up, 11.6 m from me` 1.06 s into its rise, and #7 is let go after 1.64 s.
- **`skirt-scale`:** 5 passed. **`camera-lod`:** 15 + 8 passed.
- **`look-walk`:** 92 passed, 8 failed, with this branch's binary and with main's alike, on the same world and set. The failing checks are the legs' eased turn (`head`, `chest`, `loose`), their steady offset, and the cursor's strafe and backpedal gaits. So they are red on main with this set on the laptop, not caused by this change, which touches nothing a standing or walking body draws.

Evidence (laptop, `.local/`, not committed):

- **`seat` runs:** `.local/hem/runs/{hem-1,final-1..5,base-1}/`.
- **The other cases:** `.local/hem/runs/others-hem/`, logs `.local/hem/others-hem.log` and `.local/hem/lookwalk-base.log`.
- **The sight race:** `.local/hem/runs/edge/`.
- **Side stills of the coated woman seated:** `.local/hem/stills/` (`pair-*.png`: hem off left, on right).
- **cloth_check logs:** `.local/hem/{base,joints,hem,gaits}/`.

## Limits

- **The clamp flattens, it does not drape.** Vertices pressed under the plane are moved onto it and keep their normals, so a flattened patch shades as the cloth's own surface. Seen from the game's top-down camera, the patch is under the body. The asset view's side stills show it (`LIVING_GAME_VIEW` with a ground clip).
- **Only composed skirted pieces.** VRoid-base outfits (`outfit::Piece` with a VRoid slot) and trousers and boots are not clamped. The trousers lie at 2 mm or more over the ground in all four fittings, per the heights CSVs.
- **The outline hull** (`bevy_mod_outline`) has its own vertex shader and is not clamped. Where a pressed panel is flattened, the hull stays under the ground and is hidden by it.
- **One material copy for each seated character and shared toon** (in practice one, for the outfit pieces' toon). Each copy is a batch of its own in each pass while the character sits, then is dropped.
- **Chair sitting is not covered.** It still waits for seat markers.
