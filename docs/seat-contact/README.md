# Seat contact: handoff notes

Status: **2a client side built (branch `seat-2a`); the coat chains are specified for the generator; chairs wait.** Handed to the laptop coordinator on 2026-11-19 (general coordinator's decision). Order of work: **2a, ground sitting first** (a ground collider plus coat and skirt spring chains), **then chairs** (with authority and seed seat markers). It is client-system work, built by Opus.

- [PROPOSAL.md](PROPOSAL.md): the dev-box design note, verified against the client at `29735dbe9`: where the sitting signal comes from, the proposed seat, back and ground spheres, the timing ramp, the coat chains in `person.py`, and the cost and proof plan.
- [COAT_CHAINS.md](COAT_CHAINS.md): exactly what the generator must write for coat chains (8 joints a coat, the `Coat` group), and its acceptance.
- [2a/](2a/): this stage's `cloth_check` logs (the five lines below, with and without the contact, and the gaits).

## Stage 2a: what was built (seat-2a)

All of it is client-side: no server read, write, subscription or authority change.

- **The cloth flag:** the VRM spring group's `comment` is now kept at parse time (`characters.rs` `GroupDef.comment`). A group is cloth when it reads `Skirt` or `Coat` (`CLOTH_GROUPS`, `is_cloth`).
- **The ground anchor** (`characters::SeatAnchor`, set by `live.rs` `seat_anchor`):
  - **Where:** a plane through the terrain sampled 0.39 m behind the drawn body. That is the ground clips' seat: `sit_ground_down` ends with the hips 0.39 m back, where `sit_ground` and `stand_up_ground` keep them. The plane takes the terrain's normal, from samples 0.25 m either side.
  - **When:** fixed when the body sits (town::Show `idle = sit_ground`, live::Shown `sitting`), and kept through the rise (`rising`) until the clips have the body off the ground.
  - **Redraws:** carried over when a person is redrawn for a new look (`swap_look`).
- **A plane, not the proposal's 2 m sphere:** the plane is that sphere's limit. A 2 m sphere's surface falls d²/4 below its top: 22 mm at the knees, 0.3 m to the side, and 40 mm at 0.4 m. That alone would miss the ≤5 mm target. Chairs can still use spheres or bounded planes.
- **The contact:** in the spring step, after the legs' spheres, a cloth group's tail is kept a joint's radius above the plane, its length held. A chain whose root is itself under the plane lies flat at most, rather than being pushed up through the body.
- **The timing:** the weight comes from the played clips' times and weights (`anim::Anim::ground_seat`, `anim::seat_of`). One-shots are counted over the standing loop as `play` blends them, and the loop only as far as the body is out of its gait.
  - `sit_ground_down` ramps from 0 to 1 over 0.2 s, ending at 1.2 s: the cloth comes within 20 mm of the ground at 1.17–1.33 s on all five lines.
  - `sit_ground` is held at 1.
  - `stand_up_ground` holds 1 until 1.3 s, then fades over 0.2 s of display time (0.32 s of clip at its 1.6 rate). The cloth presses deepest at 0.8–1.2 s and is 46–126 mm clear at 1.4 s.
  - At weight w the plane lies 0.25 × (1 − w) m under the ground (`SEAT_SINK`), so cloth is lifted out, never thrown.
- **Re-entry:** spring-near's reseed (tails at rest, then 60 settling steps) takes the contact, so a seated character whose springs wake starts on the ground. `check.py seat` takes the camera far and back near while they sit. One seated skirted resident was caught waking in each arm:
  - **Waking frame:** its joints turn 26.0° with the contact and 15.3° without. This is the change from the rigid joints, which were not on screen: the far model was drawn until that frame.
  - **After:** 3.5° and 5.8° a frame, the seated loop's own motion, with no swing in.
- **Switches:** `LIVING_GAME_SEAT_CONTACT=0` turns the contact off. `LIVING_GAME_PERF=seat` logs each seated character's lowest cloth tail above its ground every 3 s.
- **The asset view:** for a shot of a ground clip, the view seats its model on the checker, so side stills show the contact.
- **The coat chains:** generator work, specified in [COAT_CHAINS.md](COAT_CHAINS.md). The client already treats a `Coat` group as cloth.

## Stage 2a: the result

Measured on play-test 10's bundle (`/Users/carlid/dev/slop-play10/living/game/assets/`), not main's from 2026-11-19 morning. Hence coat-f's ground figure today is 38.6 mm (8 poses) where the table above has 32.6.

### Under the terrain, as the client places the body

`cloth_check.py --terrain`, then `--seat-contact`. Springs are simulated, 16 poses per clip, with `stand_up_ground` at the client's 1.6 rate. Each cell gives the most under the terrain, without → with the contact:

| Line | `sit_ground_down` | `sit_ground` | `stand_up_ground` |
| --- | ---: | ---: | ---: |
| smock_58-f + apron (`lk_000f47c0d8aa4056`) | 0.0 → 0.0 | 0.0 → 0.0 | 0.0 → 0.0 |
| smock_50-f + apron (`lk_008a817294ca922f`) | 0.0 → 0.0 | 0.0 → 0.0 | 1.6 → 1.6 |
| smock_74-m (`lk_00d11055a17bf658`) | 0.0 → 0.0 | 0.0 → 0.0 | 12.2 → 12.2 |
| coat-f (`lk_055747dcef6a3b03`) | 36.7 → 36.7 | 16.0 → 16.0 | 74.7 → 74.7 |
| coat-m (`lk_003e6108dbe72915`) | 16.1 → 16.1 | 0.0 → 0.0 | 31.5 → 31.5 |

The depths did not move, for three reasons:

- **The skirts rarely reach the terrain.** In the client the seated body is drawn on the clip's hips' place times `hips_k`, and its lowest trousers stand −18 to +43 mm off the terrain through the loop. The seated skirts' spring tails never come within 34 mm of the ground (`check.py seat`: 34–78 mm). The asset view's side stills show seated bodies visibly above the checker. That float is the clip's and the fit's to fix, not the cloth's.
- **smock_74-m's 12.2 mm on the rise is skin round a chain root.** It all lies on `J_Sec_L_SkirtSide`, whose root on the thigh's side is at the ground. That joint's tail is 5–7 mm off the ground, so a tail contact cannot lift the skin.
- **The coats have no chains,** so nothing can move their cloth. Their depths wait for [COAT_CHAINS.md](COAT_CHAINS.md). The coat vertices under the terrain are all side panels above the knee, plus some rear, and none front, so the specified side and rear chains cover them.

### Against the body's own seat (the table above's measure)

The lowest seated trousers or boots, 16 poses, terrain placement:

| Piece | Without | With |
| --- | ---: | ---: |
| coat-f | 42.1 mm | 42.1 mm |
| coat-m | 7.2 mm | 7.2 mm |
| smock_58-f | 29.7 mm | 29.7 mm |
| smock_50-f | 14.2 mm | 14.2 mm |

There, a skirt hangs below the trousers' seat while still above the terrain.

### Layer crossings

Trousers through coat-f in `sit_ground` measure 37.4 mm, unchanged: they lie on `J_Bip_C_Hips` at the seat, body against body, out of a ground contact's reach. Trousers through smock_58-f measure 37.1 mm and through smock_50-f 38.8 mm, both unchanged. No new crossings: every pair and clip with the contact equals the run without it, the ground clips included.

### In the game client

From `check.py seat`, crowded street, eight near:

| Arm | Seated skirt tails | Rising skirt tails |
| --- | --- | --- |
| Contact on | 34–78 mm above the ground | 5.1 and 13.5 mm |
| Contact off | 34–78 mm above the ground | −0.1 and 4.8 mm |

Coated residents report no cloth joints (none in their files).

### Gaits

Walk, brisk walk and run in `cloth_check --springs` are byte-identical with and without `--seat-contact` (coat-f, smock_58-f, smock_74-m: none through by more than 2 mm). In the client a body that is not sitting has no anchor, so the step is the same.

### Cost

Crowded street, eight near (me and seven: four skirted, three coated), seated then rising, frame rate uncapped, same binary:

| Arm | Spring CPU | Frame p50 / p99 |
| --- | --- | --- |
| Contact on | 2.0–2.7 µs a character-step | 4.58 / 5.62 ms |
| Contact off | 2.0–3.1 µs a character-step | 4.54 / 5.68 ms |

The difference is within the run's noise. The contact adds one plane test per cloth joint a step (12 joints on a long smock, 8 planned on a coat).

## What 2a does not do

- **Coats:** without the generator's chains they are unchanged ([COAT_CHAINS.md](COAT_CHAINS.md)).
- **The seated body's float:** −18 to +43 mm in the loop, which the side stills show. This belongs to the clip and fit.
- **Hip-region crossings:** trousers through coat or smock at the seat, 33–39 mm. These need weights, not a contact.
- **Chairs and benches:** they need seat markers in world data first.

## Measured garment depths today (generator `cloth_check.py`, 8 sampled frames per clip)

Measured by char-4-detail on 2026-11-19, on main `49adf9a36` plus body-joins `b670baba2` (generator-side, no client contact). How far the outer garment ends up inside the support. The authored panels change none of these: panelled runs match the unpanelled control. The panelled logs are kept beside the control logs.

| Piece | Ground sit: below ground | Chair sit: below seat top | Chair sit: behind seat back |
|---|---:|---:|---:|
| coat-m (Aldric) | 0.0 mm | 79.0 mm | 127.3 mm |
| coat-f (violet coat) | 32.6 mm (78 vertices beyond 5 mm) | 98.8 mm | 115.7 mm (618 vertices beyond 5 mm in one pose) |

Layer crossings during ground sitting on the female coat: trousers through the coat by up to 37.8 mm (8 of 8 poses), the jersey through the coat by 20.6 mm (7 of 8), the jersey through the trousers by 13.3 mm (8 of 8). On the male coat, the jersey goes through the trousers by 7.6 mm in 2 of 8 poses. Full logs: `control-*-seat.log` and `panels-*-seat.log`.

Earlier baselines from the proposal: 85–119 mm into the seat and 113–124 mm behind the back on the chair clips. Target from the proposal: ≤5 mm residual inside the seat and back footprints after settling, no new body intersections, no visible pop.

## What is already on main

- Sitting stage 1 (`0457ec509`): matched hip-zone weights in the 28 outfit files (chair-seated crossings 8 → 2), and the chair in `cloth_check` (`--chair`).
- body-joins (`b670baba2`, not yet on main; folding into the next character bundle): the heavy-build upper-only fit added 0 new crossings in 242 sitting comparisons over 14 wearers.
- Skirt spring chains exist (char-4-skirts, `04b9ccc21`). Coat chains do not yet. The proposal gives the bone layout.
