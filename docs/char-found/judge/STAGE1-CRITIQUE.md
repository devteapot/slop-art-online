# Character Foundation (`char-found`) · Stage 1 Body Visual Critique

**Date:** 2026-11-27
**Machine:** dev-box
**Target reviewed:** `origin/char-found` at `20d2953958262da17ac8434ec5f083974b2136d5` (`living/tools/blender/found/`, `docs/char-found/`)
**Scope:** Stage 1 **body only** across all five mixes (`base`, `woman`, `man`, `elder`, `child`) at **L1** (`8,864` tris) and **L2** (`35,456` tris), compared against Track **B2** (`origin/bakeoff-B2`), the owner's quality bar (`~/archive/owner-quality-refs-20261126/`, read-only), and our drawings (`docs/cage-taper/cora.webp`, `docs/char-live-2/final/review-sheet.png`, `living/tools/characters/reference/`). The blank head volume, inherited 4-edge B2 fingers, hair, and clothing layers belong to later stages — noted where relevant, not scored against Stage 1.
**Sheets:** [`stage1-body.png`](stage1-body.png) · [`stage1-vs-B2.png`](stage1-vs-B2.png)

---

## 1. Re-Shoot Methodology, Measurements & Problems Encountered

All 10 Stage-1 GLBs (`{base,woman,man,elder,child}-l{1,2}.glb`) were rebuilt cleanly from `origin/char-found` (`20d295395`) using Blender 5.2.2 (`JOBS=3`, `blender -b -t 3`) against the pinned `~/slop-assets/current/assets/lookdev/anim/own-clips.glb`. Every rebuilt GLB matched the SHA-256 of the output in Astra's worktree (`t3-3530bd47-b550ecb8739a9974`) byte-for-byte.

All 10 Stage-1 GLBs and the 4 Track B2 GLBs (`b2-{woman,man,elder,child}.glb` copied read-only from `t3-2be8784d-624c5b6d104a8564/.local/b2/out/`) were staged inside this worktree under `living/game/assets/view/{char-found,b2}/` and photographed through `~/.local/state/bakeoff/shoot.sh` (1600×900, 11:00 daylight, pinned render set `~/slop-assets/current`) using a private `CARGO_TARGET_DIR` (`.local/target-judge`) under the shared build gate (`flock -s ~/.local/state/slop-build/gate.lock`, `CARGO_BUILD_JOBS=8`).

### Re-shoot observations & problems hit

1. **B2 A-pose orbit framing normalization:** As documented in `origin/bakeoff-judge:docs/char-bakeoff/judge/CRITIQUE.md`, `view.rs::framing()` derives perspective orbit distance from the 3D bounding-sphere radius. T-pose `char-found` models (`1.91 × 1.80 m`) frame cleanly under unmodified `shots.env` (`zoom = 0.62 / 0.22 / 0.26`), whereas narrow A-pose B2 models (`0.61 × 1.70 m`) get cropped at head and feet. We preserved the raw `shoot.sh` pass (`.local/judge-shots/`) and ran a second `shoot.sh` pass for B2 (`.local/judge-shots-b2-apose/`) with orbit zooms scaled `1.50×` (`0.93 / 0.33 / 0.39`) for matched vertical framing on `stage1-vs-B2.png`. World-space play cameras (`Near 8m`, `Middle 12m`, `play 22m`) are untouched raw `shoot.sh` outputs shown as identical 1:1 native-pixel `400×225` center crops.
2. **Child asset-view bounding-box offset (`1.281 m` vs `1.200 m`):** `view.rs` computes `Fitted` from unskinned mesh bounds, so `child-l1`/`child-l2` report `bbox 1.28 m` while the morphed/skinned bind surface is `1.200 m`. This shifts `face close-up` (`aim = 0.88`) upward on the child rows in `stage1-body.png` and `stage1-vs-B2.png`, leaving extra sky above the head and placing the chin near the bottom edge.
3. **L1 vs L2 visual parity:** Across all 14 animated shots per mix, the mean absolute RGB difference between L1 (`8,864` tris) and L2 (`35,456` tris) is **`0.046–0.050` out of 255** (maximum single-frame mean `0.228` in `hands close-up` on `child`). Under flat toon shading, L1 is virtually indistinguishable from L2 even at close range — confirming the single-cage Catmull–Clark LOD architecture works.
4. **What was not driven:** `strain.py` and the 87-clip Blender playback probe were read from Astra's committed `docs/char-found/evidence/{exports,strain,clips,child-clips,child-rest-scale-clips}.json` and pose stills (`.local/tmp/char-found/poses/base-l1.png`), not re-executed in Blender; our independent checks were the full 10-GLB rebuild + SHA-256 verification, direct GLB vertex/joint proportion extraction, and full Bevy `shoot.sh` re-shooting of all 14 models.

---

## 2. Measured Body Proportions (Direct GLB Skin/Morph Evaluation)

Measured on the evaluated L2 bind surface (torso-isolated slices excluding arms, plus skeleton rest joints):

| Model | Height (m) | Heads tall | `shJ%` (joint span / H) | `chestW%` | `waistW%` | `hipW%` | `W / H` | `shJ / hipW` | Bust ahead of waist | `neckW%` | `leg%` (hip joint / H) | Head fwd of hips | Upper back behind waist |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Stage 1 · `base-l2`** | 1.800 | **7.53** | **22.4%** | 15.6% | 13.1% | **17.8%** | 0.73 | **1.26** | +2.6 cm | **4.4%** | 52.0% | +0.3 cm | +3.1 cm |
| **Stage 1 · `woman-l2`** | 1.670 | **7.54** | **22.4%** | 15.4% | 12.9% | **17.9%** | 0.72 | **1.25** | **+2.5 cm** | **4.3%** | 52.0% | +0.1 cm | +2.9 cm |
| **Stage 1 · `man-l2`** | 1.860 | **7.39** | 22.4% | 20.5% | 16.4% | 17.7% | 0.92 | 1.26 | +2.3 cm | 6.3% | 52.0% | −0.6 cm | +4.2 cm |
| **Stage 1 · `elder-l2`** | 1.700 | **7.27** | 22.4% | 19.1% | **16.5%** | **17.7%** | **0.93** | 1.26 | +0.9 cm | 5.4% | 52.0% | **−0.9 cm** | **+3.9 cm** |
| **Stage 1 · `child-l2`** | 1.200 | **5.98** | **23.9%** | 16.1% | 14.9% | 20.2% | 0.74 | 1.18 | +0.2 cm | 4.3% | **46.1%** | −1.0 cm | +1.3 cm |
| **B2 · `b2-woman`** | 1.660 | **7.05** | **17.2%** | 15.3% | 14.0% | **19.8%** | 0.71 | **0.87** | +2.5 cm | **6.3%** | 54.4% | +1.2 cm | +3.0 cm |
| **B2 · `b2-man`** | 1.831 | 6.06 | 16.8% | 16.7% | 16.3% | 19.4% | 0.84 | 0.87 | +1.5 cm | 8.7% | 53.3% | +1.6 cm | +3.3 cm |
| **B2 · `b2-elder`** | 1.737 | 6.24 | 16.9% | 16.4% | 16.9% | 19.1% | 0.88 | 0.88 | +0.2 cm | 7.7% | 53.6% | +0.7 cm | +2.6 cm |
| **B2 · `b2-child`** | 1.341 | **5.14** | 16.1% | 13.6% | 14.5% | 18.7% | 0.77 | 0.86 | +0.2 cm | 5.3% | 50.9% | +0.7 cm | +1.6 cm |

---

## 3. Critique Against Quality Bar, Brief Goals & Coordinator's First Look

### What genuinely works (do not throw away)
- **Rig & clip architecture (`own-clips.glb`):** Exact 82-joint T-pose match with 87/87 shared clips verified at 0.00° / 0.0 cm drift, clean L1/L2 parity (`8,864` / `35,456` tris, `6` materials), and smooth walk/run/sit playback.
- **Crotch saddle & lower-leg anatomy:** The 4-corner perineal saddle cleanly eliminates B2's dark vertical diamond crease in idle and keeps `sit_ground` visually intact (`2.24×` max stretch vs `6.23×` earlier). Calves and ankles show clean, natural curve in 3/4 and back views — noticeably better than B1's tubes.
- **Adult man torso:** `man-l2` genuinely reads as an adult male body (`chestW% = 20.5%`, `W/H = 0.92`, thicker neck `6.3%`, thicker arms) — a major improvement over B2's boyish `b2-man`.
- **Child leg/arm shortening:** `child-l2` achieves genuine child limb-to-torso proportions (`leg% = 46.1%` vs adult `52.0%`, arm span `0.98× H`, `1.20 m` height, `2 mm` floor contact in `sit_ground`), cleanly beating B2's uniformly scaled `b2-child` (`50.9%` leg ratio).

### Root-causing the visual failures (testing the coordinator's first look)

The coordinator's first look is **confirmed across both the sheets and the direct mesh measurements**, and every failure traces to four specific defects in `cage.py` and `body.py`:

1. **B2's 1.66 m female cage was transplanted onto `own-clips.glb`'s 1.80 m wide-shoulder rig without rescaling (`7.54` heads, pencil neck, narrow hips, sleeve-root wedges):**
   - B2's `TORSO` (`hip rx = 0.163`, `sh rx = 0.149`), `HEAD` (`HS = 1.06`), and `neck` (`rx = 0.0295`) were authored for Cora's `1.66 m` A-pose rig (`J_Bip_L_UpperArm.x = 0.143 m`, `shJ% = 17.2%`).
   - On `own-clips.glb` (`1.80 m` tall, `J_Bip_L_UpperArm.x = 0.199 m`, `shJ% = 22.4%`), keeping those exact radii shrank every cross-section ~8% relative to height: adult heads dropped to **`7.27–7.54` heads** (too small/realistic for Blue Protocol's `6.5–7.0` bar), neck width shrank to a pencil-thin **`4.3%`** (vs B2's `6.3%`), hips narrowed from B2's `19.8%` to **`17.8%`**, and the armhole-to-`UpperArm` jump grew to a **`7.8 cm` unsupported horizontal bridge** (`torso rx = 0.149` -> `SJ = 0.199` -> `arm ring 1 = 0.227`). When the arm rotates down ~75° from T-pose into idle/walk/run, that bridge collapses into the glaring dark triangular **sleeve-root wedges** visible across every mix in front, 3/4, and back.
2. **`woman` has almost no female form and reads identically to `base`:**
   - `PRESETS["woman"]` is just `base` scaled to `1.67 m` plus `Build_Slim: 0.23` (which *shrinks* hips `0.95` and chest `0.96`). Measured `woman-l2` vs `base-l2` differ by ≤ 0.2% everywhere (`W/H 0.72` vs `0.73`, `hipW% 17.9%` vs `17.8%`, `bust+cm 2.5 cm` vs `2.6 cm` — only **2 mm** ahead of `man-l2`'s `2.3 cm`!).
   - With `shJ/hipW = 1.25` (male inverted triangle, vs B2 woman's `0.87`) and a flat 1-ring bust bump invisible from the front, `woman-l2` reads like a slender teenage boy rather than a Blue Protocol / Cora young woman.
3. **`elder` has zero visible stoop and reads nearly identical to `man` and `base`:**
   - **Code bug in `cage.py:257`:** `st = 0.0` is hardcoded before the head loop (and `g == "neck"` also gets `st = 0.0`), so `Age_Elder`'s `stoop = 0.030` nudges the chest forward `1.8 cm` and then snaps the neck and head straight back. Measured `hdFwd` on `elder-l2` is **`−0.9 cm`** (tilted slightly *back* relative to hips, worse than `base`'s `+0.3 cm`!), and upper-back depth (`+3.9 cm`) is actually *less* than `man-l2` (`+4.2 cm`).
   - **Preset cancellation:** `PRESETS["elder"]` stacks `Sex_Male: 0.7` on `Age_Elder: 1.0`, cancelling `Age_Elder`'s shoulder narrowing (`net sh_w = +0.021 m`) and arm slimming (`net arm = 1.12`), yielding identical `waistW%` (`16.5%` vs `16.4%`) and `hipW%` (`17.7%` vs `17.7%`) to `man-l2`. Even in full-resolution 3/4, `elder` and `man` are nearly interchangeable.
4. **`child` still has boxy wide shoulders and a slightly small head:**
   - Shortening legs/arms without narrowing the shoulder span leaves `child-l2` with **`shJ% = 23.9%`** — wider relative to height than the adult man (`22.4%`) — giving a stocky, square-shouldered look in front view. At **`5.98` heads** (`head = 1.21` vs B2's `1.30`), the child reads slightly lanky/pre-teen compared to B2's `5.14` heads and anime child proportions (`5.2–5.5` heads).
5. **Clavicles & top-down readability:**
   - Front daylight gives no clavicle/suprasternal definition at all (completely smooth collar cone).
   - At `Near (8m)` and `Middle (12m)`, the desaturated cool-grey underlayer is uniform across all five mixes (fine for Stage 1 body judgement), but thin wrists and hands thin out toward hairlines from 58° overhead, and four of the five mixes (`base`, `woman`, `man`, `elder`) collapse into near-identical silhouettes at play distance.

### Do the morphs need a wider range or more targets before Stage 2?

**Yes — both.** The current 8-morph set inherits B2's assumption that `base = woman` and relies on `Sex_Male` alone to move away from it, which breaks down once `base` sits on a wide-shouldered male T-pose rig and `elder` mixes `Sex_Male` on top of `Age_Elder`. Before Stage 2 (and before Stage-3 garments bind to the morph set):
- **Fix base proportions first** (6.8–7.0 heads, proper neck, clean armhole/deltoid without wedges).
- **Split/widen the body morphs** so sex, build, and posture do not fight each other: keep `base` neutral and add explicit **`Sex_Female`** (or separate **`Bust_Full`**, **`Hip_Curve`**, **`Waist_Taper`**, **`Shoulder_Narrow`**) alongside widened **`Age_Elder`** / **`Posture_Stoop`** (propagating into neck + head + thoracic kyphosis + shoulder droop). That directly gives Stage 2 and a 64-person town clean orthogonal axes (including female elders and varied female/male builds).

---

## 4. Weighing the Laptop's Advice (`LAPTOP-ADVICE-20261127.md`)

| Laptop point | Verdict & Stage assignment | Reasoning |
|---|---|---|
| **Proportions (`6.5–7` heads, Blue Protocol range; fuller hair volume rather than chibi heads)** | **Stage 1 (body/head ratio) + Stage 2 (hair volume)** | **Adopt in Stage 1 now:** `char-found` is currently `7.27–7.54` heads because B2's `HS = 1.06` wasn't scaled up for `own-clips.glb`'s `1.80 m` height. Locking adults to **6.7–7.0 heads** (and child to **5.2–5.5**) in Stage 1 avoids re-proportioning the body after Stage 2 sculpts the 3D head. Fuller sculpted hair volume belongs in **Stage 2**. |
| **Top-down readability (+12–15% hands, wrists, and boots at 58°)** | **Split: Stage 1 (partial) → Stage 2 (hands) → Stage 3 (boots)** | Good diagnosis — wrists and hands genuinely thin out in `Near (8m)` and `Middle (12m)`. **Stage 1:** raise wrist girth and palm/hand base scale by **+10–12%** and bare foot/ankle volume by **+8–10%** (avoid over-bloating bare Stage-1 feet in close-ups). **Stage 2:** hit the full **+12–15%** readable hand/wrist silhouette when replacing placeholder fingers with B1's `hands.py` topology. **Stage 3:** add the remaining **+12–15%** boot footprint through layered soles, cuffs, and toe caps. |
| **Textures (10–15% top-down value gradient, baked crevice AO, real `metallic` & `perceptual_roughness` maps)** | **Stage 2 (skin/face/hair) & Stage 3 (garments/gear)** | **Not Stage 1.** Stage 1 intentionally uses 6 flat material fills with no UV/texture pipeline yet so pure form/morphs/rigging are judged cleanly. Keep clean material-region boundaries now; author the gradient, crevice AO, and cel-specular `metallic`/`roughness` maps once Stage 2 finalizes head/hand UVs and Stage 3 adds wool/leather/metal layers. |
| **Outlines (`_OUTLINE_WIDTH`: face `0.4×`, outer hair/body `1.0×`)** | **Stage 2 (face/hair/body) & Stage 3 (garments)** | **Not Stage 1.** The face is a blank placeholder and hair does not exist yet. Stage 1 already isolates the `face` material region cleanly; emit `_OUTLINE_WIDTH` attributes in Stage 2 once the real 3D face and hair meshes are welded/attached. |
| **Look-dev scene (`living/tools/lookdev_shoot.py` in Cullet plaza, noon/dusk/night)** | **Stage 3** | **Not Stage 1 or 2.** Keep `~/.local/state/bakeoff/shoot.sh` on the neutral checker for Stage 1 re-check and Stage 2 head/hands gates (apples-to-apples comparisons), then adopt `lookdev_shoot.py` in Stage 3 when materials, cel specular, outlines, and Cullet outfits are judged in-world. |

---

## 5. Stage-1 Score Table (Body Only, 1–5)

Scale: `5` = matches production bar · `4` = strong foundation close to bar · `3` = serviceable with clear gaps · `2` = visibly weak / misses brief · `1` = fails criterion outright.
*(Blank head volume, placeholder 4-edge fingers / `2.99×` slash hand edge, hair, and clothing are excluded from scoring.)*

| Criterion | Score | One-line reasoning |
|---|---:|---|
| **Rig, Skeleton & L1/L2 Architecture** | **5 / 5** | Bit-exact 82-joint `own-clips.glb` T-pose match (87/87 clips, 0.00° / 0.0 cm drift), 6 clean materials, and visually identical L1 (`8,864` tris) / L2 (`35,456` tris) (`mean RGB diff ≤ 0.05/255`). |
| **Deformation & Joint Mechanics** | **3 / 5** | Clean walk/run/knee motion and much-improved 4-corner crotch saddle (`2.24×` max vs `6.23×` prior), docked for glaring dark sleeve-root wedges pinching both armpits whenever arms drop from T-pose. |
| **Anatomical Polish (clavicles, shoulders, knees/calves, ankles/feet)** | **2 / 5** | Calves and ankles curve cleanly in 3/4 and back, but clavicles are invisible, the adult neck is pencil-thin (`4.3%`), shoulders fold into abrupt wedges, and adult height sits too small-headed (`7.3–7.5` heads). |
| **Man Reading as an Adult Man** | **4 / 5** | Clearly beats B2's boyish `b2-man` with broader chest (`20.5%`), thicker neck (`6.3%`) and arms, and straight athletic waist (`W/H 0.92`); docked for small head ratio (`7.39`) and armpit wedges. |
| **Woman Reading as a Woman** | **2 / 5** | Virtually identical to `base` (`hipW% 17.9%` vs B2's `19.8%`, `bust+cm 2.5 cm` vs man's `2.3 cm`) on a wide male shoulder span (`shJ/hipW = 1.25`), reading as a slender teen boy rather than a woman. |
| **Elder Silhouette & Posture** | **1 / 5** | Indistinguishable from `man` and `base` from front, back, Near, and even 3/4 because `Sex_Male: 0.7` cancels `Age_Elder` slimming and `cage.py:257` resets `st = 0.0` before the neck and head (`hdFwd = −0.9 cm`). |
| **Child Real Proportions** | **3 / 5** | Real proportional breakthrough over B2 (`46.1%` leg ratio, `0.98×` arm span, `1.20 m` height, `2 mm` ground-sit contact), docked for boxy wide shoulders (`shJ% = 23.9%`) and tall `5.98`-head ratio. |
| **4-Role Silhouette Distinctiveness at Play Distance** | **2 / 5** | Only `child` separates cleanly at `Near (8m)` and `Middle (12m)`; `base`, `woman`, `man`, and `elder` merge into nearly identical silhouettes from front and 58° overhead. |
| **Total (out of 40)** | **22 / 40** | |

---

## 6. Verdict: **PASS WITH FIXES**

The underlying Stage-1 engineering (unified B2 quad cage on `own-clips.glb`'s 82-joint T-pose rig, 87/87 shared clips, L1/L2 visual parity, 4-corner crotch saddle, child hips-travel scaling, and adult-male torso mass) is **sound and worth building Stage 2 on** — do **not** redo from scratch.

However, **do not start Stage 2 until the following six measurable body/morph fixes land in `living/tools/blender/found/{cage,body}.py`** and pass a quick re-shoot gate:

### Exact fix list for Astra before Stage 2

1. **Rescale base proportions to the Blue Protocol range (`6.7–7.0` heads) & fix neck/clavicles:**
   - Raise head scale (`HS` from `1.06` to `~1.15–1.18`) so adults measure **`6.7–6.9` heads** (`base`/`woman`) and **`6.9–7.0` heads** (`man`/`elder`), down from `7.27–7.54`.
   - Widen base neck (`TORSO` `nb`/`neck` radii) from `4.3%` to **`5.2–5.6%`** of height on `base`/`woman` (keeping `man` around `6.5–7.2%`).
   - Add crisp, subtle **clavicle ridges and suprasternal notch** on rings `k = 10, 11` (`~4–6 mm` front normal relief) so the collarbone reads gently under front 11:00 daylight.
2. **Eliminate the dark sleeve-root armpit wedges:**
   - Close the `7.8 cm` unsupported torso-to-armhole gap (`TORSO` `k = 7..10` lateral wall brought out toward the deltoid/axilla, `arm` ring 1 moved inward from `SJ + au * 0.028` to `SJ + au * 0.005..0.012` with lower axillary underside).
   - Smooth the `UpperChest` → `Shoulder` → `UpperArm` weight gradient across `k = 7..10` and `A1..A3` so lowering arms 75° from T-pose removes the dark pinched crease in `idle - front`, `idle - 3/4`, and `idle - back` while keeping `strain.py` shoulder `p05–p95` within `0.70–1.25` in `walk`/`run`.
3. **Make `woman` unmistakably feminine (separate female shaping targets):**
   - Replace `woman = base + Build_Slim: 0.23` with explicit female shaping (either a dedicated `Sex_Female` target or orthogonal `Bust_Full`, `Hip_Curve`, `Waist_Taper`, `Shoulder_Narrow` targets).
   - Measurable `woman` (`1.67 m`) targets: **`hipW% = 19.5–20.5%`** (matching/beating B2's `19.8%`), **`waistW% = 12.5–13.2%`** (**`W/H = 0.64–0.68`**), fuller multi-ring **`bust+cm = 4.2–5.0 cm`** ahead of waist front with a legible underbust plane on `k = 5`, fuller posterior glute curve, and tucked/sloped deltoid contour so outer shoulder-to-hip ratio reads clearly narrower than `base`/`man` (`≤ 1.05–1.10` vs `man ≥ 1.25`).
4. **Make `elder` unmistakably stooped and distinct from `man` & `base`:**
   - Fix `cage.py:257` (`st = 0.0` bug) and `neck` ring so `stoop` propagates smoothly up the spine through chest (`0.35×`), upper chest/shoulders (`0.75×`), neck base (`0.95×`), neck (`1.10×`), and **head + ears (`1.25×`)**, paired with upper-back kyphosis (`ubBk = +5.5 to +6.5 cm`) and slight vertical upper-body settle (`−2.5 to −3.5 cm`), achieving **`hdFwd = +3.5 to +5.0 cm`** ahead of hip center (up from `−0.9 cm`).
   - Stop `PRESETS["elder"]`'s `Sex_Male: 0.7` from cancelling `Age_Elder`: reduce `Sex_Male` in the elder mix (≤ `0.3`) and strengthen `Age_Elder` (or separate `Posture_Stoop`) with narrower drooping shoulders (`sh_w ≈ −0.025`), thinner limbs (`arm ≈ 0.80`, `leg ≈ 0.84`), narrower sunken chest (`chest ≈ 0.90`), and softer lower belly (`belly ≈ +0.024`) so `elder` separates clearly from `man`, `base`, and `woman` in front, 3/4, back, and `Near (8m)`.
5. **Refine `child` shoulders and head proportion:**
   - Narrow `child`'s shoulders (`sh_w` negative / tucked upper-arm root, or verified bone-scale/rest adjustment preserving 0° clip drift) to eliminate the boxy `shJ% = 23.9%` linebacker silhouette and match B2's soft sloped child shoulders.
   - Increase `Age_Child` `head` from `1.21` to **`~1.32–1.36`** so `child` (`1.20 m`) measures **`5.2–5.5` heads** (down from `5.98`) with a softer juvenile waist (`W/H ≈ 0.84–0.88`).
6. **Stage-1 top-down extremity readability (per laptop advice):**
   - Increase wrist radii (`arm_spec` ring 8) and base hand/palm scale by **+10–12%** and bare ankle/foot volume by **+8–10%** so hands and feet hold up at 58° `Near`/`Middle` without exaggerating bare close-up feet; reserve full `+12–15%` hand craft for Stage 2 (`hands.py`) and boot bulk for Stage 3.
7. **Re-check gate:** Re-run `skeleton_check.py`, `clips_compare.py`, `strain.py`, and `~/.local/state/bakeoff/shoot.sh` on the 5 mixes after fixes 1–6 to confirm all four archetypes (`woman`, `man`, `elder`, `child`) separate cleanly at play distance before Stage 2 begins.
