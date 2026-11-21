# char-port-2 · S7 · The four must-fixes (checkpoint)

Each measure here passed its known-answer test first (PLAN.md §7). All the changes are behind port flags: `jaw` (S1's, extended), and two new ones, `eyes` and `beard`. With no port, `cage_accept` and `face_types check` give the same numbers as main; flag-off parity in full is frame-views' run before the merge.

## The face factors: re-derived in the measuring view (step 3)

**The GC's step 3** (2026-11-21): each class's factor is 1.751 over its mean at 1.0, measured in the measuring view at the landmark row ([ortho/](ortho/README.md)). The children aim at 1.80 (rounder).

| Class | Mean at 1.0 | Factor |
|---|---|---|
| adult-f | 1.774 | 0.987 |
| youth-f | 1.774 | 0.987 |
| adult-m | 1.822 | 0.961 |
| youth-m | 1.814 | 0.965 |
| elder-m | 1.804 | **0.962**: bounded by `cage_accept`, not the formula (accepted, 2026-11-21). The formula's 0.970 takes elder-m-a's chin to 0.031 H, over its 0.030. 0.962 is the widest factor that holds 21/21; it is within ±2% and closer to 1.751. |
| elder-f | 1.871 | 0.936 |
| child-u | 1.873 | 0.961 (to 1.80) |

**The acceptance:** each class within ±2% of its target; `cage_accept` 21/21; the jaw order and `face_types check` unchanged; the eye spacing unmoved.

**Result** (n3: built at `66d440787`, measured in the measuring view at the landmark row; [ortho/step3.json](ortho/step3.json)):

| Class | Factor | At 1.0 | Step 3 | Target | Off |
|---|---|---|---|---|---|
| adult-f | 0.987 | 1.774 | 1.762 | 1.751 | +0.6% |
| youth-f | 0.987 | 1.774 | 1.764 | 1.751 | +0.8% |
| adult-m | 0.961 | 1.822 | 1.782 | 1.751 | +1.8% |
| youth-m | 0.965 | 1.814 | 1.781 | 1.751 | +1.7% |
| elder-m | 0.962 | 1.804 | 1.768 | 1.751 | +1.0% |
| elder-f | 0.936 | 1.871 | 1.758 | 1.751 | +0.4% |
| child-u | 0.961 | 1.873 | 1.818 | 1.80 | +1.0% |

- **Every class is within ±2%.** The cheek row narrows by about half to all of the factor, because the factor fades out by the chin.
- **`cage_accept`:** 21 of 21.
- **The jaw order:** kept in all 35 cells.
- **`face_types check`:** 60,648 of 60,648 valid.
- **brows and eye colours:** clean.
- **Eye spacing:** unmoved (0.0 mm on every type), so the hair cuts are unchanged.

[ortho/before-after.png](ortho/before-after.png): child-u and elder-f at 1.0 and at step 3, idle front and three-quarter, and bind front.

**The ears' lower end at 1.0, in the measuring view:** 0.462–0.480 of eye-to-chin under the eye line, 42 of 42 ears within 0.47 ± 3% ([ortho/ears.json](ortho/ears.json)). Nothing changes there.

### Before: interim neutral, pending the ortho re-measure

**The decision** (the GC's, 2026-11-21, after the [bind re-measure](bind/README.md)): every class's `faceprop` width is now 1.0 in `port.json`. S6b's 0.935–0.973 were derived on idle frames, which turn the head 11–12° and widen the face's outline at the cheek row.
- **What keeps the faceprop flag:** the ears' lower end (0.47), the expression clearance and the lid ink clearance. All of these are reopened in step 3, not now.
- **What stays as landed:** the jaw fix and `cage_accept` (3D).
- **Nothing builds on the narrowing:** no §6 cost runs and no bundle until step 3, the combined re-tune after the ortho known-answer test.

## 4. `cage_accept.py`: fixed (A) and re-baselined (B)

[cage-accept.md](cage-accept.md) has the diagnosis and S1's quoted intent; [cage/after-fp.json](cage/after-fp.json) the run.

**The known-answer test** ([cage_accept_selftest.py](../../../living/tools/characters/cage_accept_selftest.py)): **21 of 21 checks pass**.
- the synthetic head's widths, eye height and spacing (18);
- adult-f-b as built, within its tapered record;
- **a narrowing beyond the taper fails:** 12% more on the lower face, only when the taper is on. Without the guard it would pass as "taper";
- **a narrowing in both builds fails** (a plain defect).

**A, the jaw rising sooner behind the chin** (`cage_head` `Plan.jaw_line` `rise`; the port's `jaw`: (0.25, 0.7), the men's classes (0.3, 0.8)):
- below a quarter of its height the jaw line climbs out of the chin sooner; above, it is as before;
- **`cage_accept`: 21 of 21 within 0.03 H** with main's whole port (8 of 21 before). The worst against the tapered record is 0.030 (elder-m-a); against the raw record 0.060 (adult-f-a, its taper's own);
- the c lines' coverage is not changed: they fit with the rest, so `cage_accept` still measures the skin it did;
- adult-f-c's 0.032 at 0.12 H is 0.026 after A.

**B, S1's taper re-baselined:** `cage_accept` holds a tapered type to its record times the taper it took, at most the cage's declared factor (`cage_head.taper_factor`, the function the cage builds with). It prints and keeps the raw departure beside it.

**What must not move:**

| | Result |
|---|---|
| The 2D face measure (S6b's acceptance) | within +0.002 on 20 types; **child-u-a −0.040** (1.764 → 1.724), the child class's mean 1.791 → 1.777 |
| The 3D slice at the cheek row | unchanged (child-u-a 1.707 → 1.708) |
| The jaw lines' order | kept at every height in every class |
| `face_types.py check` | 60,648 of 60,648 value ends; every type ok |
| Crossings | 0 new in every mouth shape on the four bodies and in `MTH_A` on the 21 types; no type with more blink pairs than unnarrowed |
| [jaw-rise.png](jaw-rise.png) | the four bodies before and after, side and three-quarter, close on the chin |

- **Why child-u-a moves in 2D and not in 3D:**
  - the rise moves the face's sample rows up the side of the face in the columns behind the chin;
  - the surface's width at the cheek row is the same, but on a child's short face the outline the camera sees from slightly above ends 3 px sooner on one side, short of the ear;
  - repeatable to the pixel over three runs.
  - **Since the bind re-measure: an idle-pose artefact.** In bind S6b's and S7's child-u-a read the same (1.379 at pitch 8, 1.487 at pitch 0; [bind/](bind/README.md)). The turned head showed the jaw's side; square-on, the rise doesn't reach the cheek row.
- **One trap found on the way:** rebuilding one type alone re-writes the shared tint page for all of them, and it read as a second 2D move. All measures here are on sets built in one go.

**And one build fix it needed:** `person.expression_clearance` (S6b's mouth clearance) stopped youth-m-a's build after the rise, on a rounding sliver in its head-frame stage. That stage now hands over to the file-frame stage, which already holds such slivers still. Only the file-frame stage may stop a build. Types that converged before are unchanged.

## 1. The eye-joy sliver: fixed (port `eyes`)

**The measure** ([eye_id.py](eye_id.py), [eye_count.py](eye_count.py), [eye_closed.py](eye_closed.py)):
- the eye white and iris drawn in cyan, each key that closes an eye held at full weight;
- the close front and three-quarter;
- the eye pixels that show;
- its test, [eye_count_selftest.py](eye_count_selftest.py): 8 of 8.

**Before** ([eyes-before.json](eyes-before.json)):
- blink, left and right: 0 on all 25 heads;
- **eye-joy: 78–358 px on every woman and child and the men's round line**, a crescent above the arc's inner half.

**The cause:** the eye's parts are placed against a plane fitted to the lids' ring as the state leaves it. Eye-joy folds the ring onto one arc, and a plane fitted to a line is free to tip: it carried the iris forward through the skin above the arc.

**The fix:** that plane is the open eye's in every state (`CageFace._eye`). Open eyes are unchanged by construction.

**After** ([eyes-after.json](eyes-after.json), [eye-joy.png](eye-joy.png)):
- **0 eye pixels in every closing key** (blink, left, right, eye-joy), front and three-quarter, **on all 25 heads**: the 21 types and the four bodies, with every S7 port on. For the one-eye keys (`Close_L`, `Close_R`), the count is the closing eye's side of the frame, split at the gap between the eyes in the open still; the other eye stays open and shows its open count. Corrected at the final run: the earlier summary gave 0 for left and right without saying it counted one side, and the whole-frame counts (eyes.json) show the open eye. Final run: [final/eyes-sides.json](final/eyes-sides.json), 0 on the closing side on all 25 heads;
- the open eye, the control, shows 608 px or more on each.

## 3. The beard: ported (port `beard`); one look for the GC

**What it is:** `8d1659ec5` and `537eb0457`'s face paint, onto main's code. Main had not touched those regions since the branch, so nothing conflicted. The neck lift is left out (§9).

**What it does:**
- the beard drawn in hairs, its upper edge feathered;
- cheek hair thinning to the sideburn, the mouth's corners bare;
- the overlay's alpha the painted coverage, a soft edge;
- the far beard 1.5 mm off;
- `shade_mean`'s far-beard target.

[beard.png](beard.png): the man and the elder, close front at rest and talking, three-quarter and Middle; before, the port as landed, and an option.
- **The mouth shows** when talking, and the edges are soft.
- **As landed, a full beard's core is drawn at about 60% cover** (`0.90 × (0.30 + 0.70 × hairs)`), so the man's dark beard reads pale tan: the skin shows through. The branch restored a near-opaque core for the short beard only (`537eb0457`).
- **The option** holds the full beard's core like the short's (`0.95 + 0.05 × hairs`; the mask still gives the soft edge and the bare mouth): the man's beard stays dark. It's a one-word change, not in the commit.
- **At Middle** the hair covers the face from the camera's height, and the three look alike.

**For the GC:** the port as landed, or the option.

## 2. `swept_braid`'s mid strip: fixed by remedy (a), t2 0.65

**The GC's choice** (2026-11-21): remedy (a), a wider mid band on the sweep's own surface. The cuts' side volume is accepted as it is (ortho bind: 2.971–3.009 against the band 2.973–3.319).

**What changed:** `hair.MASTERS["swept_braid"]["profile"] = {t2: 0.65}`, the cut's own threshold between the mid and light bands (every other style keeps `hair_page.PROFILE`'s 0.4).
- `person.py` writes it to the cut's `.hairpage.json`.
- `hair_page.py` applies it to that cut's files, in its page and in its `--profile-only` rewrite.
- **Built** (`SLOP_PORT=hair,masters`, the full set): the other 86 hair files equal S6's set as data, their buffers byte-identical and their JSON the same values. As files they differ only in key order, because S6's set had been through a `--profile-only` rewrite. `swept_braid`'s six files differ only in t2.

**Measured consistently** (`calibrate_bins`, idle, the calibration frame, step 3's types; [t2-sweep.png](t2-sweep.png)):

| t2 | Result | dark.mid | brown.mid |
|---|---|---|---|
| 0.40 (S6's) | out | [−6, −5, −12] | [−6, −4, −7] |
| 0.52 | out | [−3, −2, −10] | [−5, −3, −6] |
| 0.60 | pass, at the edge | [−1, 0, −9] | [−3, −1, −5] |
| **0.65** | **pass** | [−1, −1, −8] | **[−3, −1, −4]** |
| 0.70 | pass | [−1, −1, −8] | [−3, −1, −4] |

The light, highlight and shade bands don't move with t2. brown.highlight's −5 is S6's, unchanged.

**On the built set at t2 0.65** (`.local/char-port-2/s7/hair65`, step 3's types):

| Run | Pose | Result |
|---|---|---|
| `swept_braid` alone | idle | **PASS**: brown.mid [−3, −1, −4], dark.mid [−1, −1, −8] |
| six styles (bob, long, braid, swept, short, swept_braid) | idle | **PASS, 6 of 6** |
| `swept_braid` alone | bind | mids in (brown.mid [−5, −2, −5], at the edge); **dark.shade −12.2 against ±12** |

**The bind row is for the record.** The palettes were tuned in the calibration frame (idle at 0 s), and dark.shade reads the same −12.2 in bind at t2 0.52, so it is the pose's light on the shade band, not the remedy. Whether hair calibration moves to bind too would mean re-tuning every palette, so that is the GC's call.

**A measuring artefact, caught.** The first t2 trial (0.50–0.53, "passes from 0.51") set t2 in the installed files only. `calibrate_bins` copies its band-mask file (`zzcal-`) before each round's `hair_page --profile-only` rewrite, and that rewrite reset the drawn files to 0.4. So only the masks moved with t2. The sweep above carries t2 in the files and in their `.hairpage.json`, which the rewrite keeps, so masks and drawing agree. `calibrate_bins` now records its pose (`--pose`).

**Accepted** (2026-11-21):
- t2 0.65, in the generator.
- Hair calibration stays on the calibration frame (idle at 0 s). Bind's dark.shade −12.2 is a known pose effect (PLAN.md §7).

### Before: still out; the remedy was the GC's

**Re-measured** (`calibrate_bins.py`, six styles, measure only, S7's types and S6's hair set installed; [mid/](mid/)):
- bob, long, braid, swept and short pass;
- **swept_braid's dark mid (−6, −5, −12) and brown mid (−6, −4, −7) are out of ±5**, as in S6. S6b and S7 did not move it.

**S6's two remedies** ([s6/step4](../s6/step4/README.md)), for the GC to choose:
- a wider mid band on the sweep's own surface;
- less stand-off at the hem.

The band's tolerance is not widened.

## The Cora arm: her resident line in its own resident hairstyle

**What happened:** built from her resident line (`cora-stannard`: adult-f-c, auburn, seed 37053) in `swept_braid`, the master stops the build. It is out of its tolerances even unvaried: rear depth 0.67 against 0.49–0.57, spread 2.30. The master was fitted on adult-f-b, the shared styles' head, and her resident line's head is deeper. The face is not the cause: the clearance pass resolves every mouth key. It failed the same way in every final run.

**The decision** (the coordinator's, 2026-11-21):
- **(a):** the sheet shows her resident line in its own resident hairstyle, labelled as such.
- **The tolerances are not widened.**

**Candidate (c), recorded:** fit the master to the head's depth (its rear stations scaled by the head's own rear depth), so a deeper head keeps the cut within its tolerances. Whether (c) belongs in S8 depends on how many of the town's heads the master fails on. See the town check below.
