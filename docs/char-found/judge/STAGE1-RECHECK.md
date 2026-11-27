# Character Foundation (`char-found`) · Stage 1 Body Re-Check

**Date:** 2026-11-27
**Machine:** dev-box
**Target reviewed:** `origin/char-found` at `374f49ac1` (`Differentiate foundation body proportions and smooth the shoulder bend`), compared against prior pass `20d295395`.
**Scope:** Stage 1 **body only** across all five mixes (`base`, `woman`, `man`, `elder`, `child`) at L1 (`8,864` tris) and L2 (`35,456` tris). Head, fingers (`7.29×` man-L2 slash outlier), hair, and clothing remain later stages and are not scored.
**Sheets:** [`stage1-body.png`](stage1-body.png) (updated to `374f49ac1`) · [`stage1-fixes-compare.png`](stage1-fixes-compare.png) (before `20d295395` vs after `374f49ac1`, L2)

---

## 1. Re-Shoot Verification & Independent Measurements

- **Rebuild & hash match:** All 10 GLBs (`{base,woman,man,elder,child}-l{1,2}.glb`) were rebuilt from `origin/char-found` (`374f49ac1`) using Blender 5.2.2 (`JOBS=3`, `blender -b -t 3`) into `living/game/assets/view/char-found-after/`. **10 / 10 SHA-256 hashes matched** Astra's worktree (`t3-3530bd47-b550ecb8739a9974`) and `docs/char-found/evidence/fixes/playback.json` byte-for-byte.
- **Re-shoot:** All 10 rebuilt GLBs were photographed through `~/.local/state/bakeoff/shoot.sh` (1600×900, 11:00 daylight, unmodified `shots.env`, private `CARGO_TARGET_DIR=.local/target-judge`, `CARGO_BUILD_JOBS=8`, shared `gate.lock`) into `.local/judge-shots-after/`.
- **L1 vs L2 visual parity:** Mean absolute RGB difference between L1 and L2 across all 14 animated shots per mix remains **`0.045–0.055` out of 255** (max single-frame mean `0.233` in `hands close-up` on `man`).
- **Asset-view framing note:** `view.rs` continues to compute AABBs on unskinned mesh bounds (`child` reports `bbox 1.27 m` vs `1.20 m` skinned; `elder` reports `1.75 m` vs `1.70 m` settled), slightly shifting `face close-up` upward on `child` and `elder`. Not a model bug.
- **What was not driven:** Did not re-run `strain.py` or the 87-clip Blender probe (read Astra's committed `docs/char-found/evidence/fixes/{strain,playback}.json` directly). Independent checks were the 10-GLB rebuild + SHA-256 verification, direct GLB bind-surface proportion extraction, and full Bevy `shoot.sh` re-shooting + 1600×900 inspection.

### Independent Before vs After L2 Bind Measurements

| Mix | Heads (before → after) | `shJ%` (before → after) | `hipW%` (before → after) | `W/H` (before → after) | Bust ahead of waist | `neckW%` (before → after) | `hand%` (before → after) | `hdFwd` (before → after) | `ubBk` (before → after) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Base** | 7.53 → **6.88** | 22.4 → 22.1% | 17.8 → 17.6% | 0.734 → 0.734 | +2.58 → +2.54 cm | 4.37 → **5.41%** | 12.1 → **13.2%** | +0.02 → −0.35 cm | +3.05 → +3.01 cm |
| **Woman** | 7.54 → **6.89** | 22.4 → **16.3%** | 17.9 → **20.0%** | 0.720 → **0.648** | +2.47 → **+4.70 cm** | 4.31 → **5.29%** | 12.1 → **13.2%** | −0.18 → +0.99 cm | +2.89 → +3.46 cm |
| **Man** | 7.39 → **6.98** | 22.4 → 24.0% | 17.7 → 17.6% | 0.924 → 0.924 | +2.27 → +2.25 cm | 6.30 → **7.01%** | 13.7 → **15.0%** | −0.77 → −0.85 cm | +4.19 → +4.16 cm |
| **Elder** | 7.27 → **6.98** | 22.4 → **20.3%** | 17.7 → 17.8% | 0.930 → **0.822** | +0.91 → +0.21 cm | 5.41 → **5.56%** | 13.2 → **14.0%** | −1.14 → **+4.51 cm** | +3.90 → **+5.37 cm** |
| **Child** | 5.98 → **5.28** | 23.9 → **19.8%** | 20.2 → 19.6% | 0.737 → **0.779**\* | +0.24 → +0.13 cm | 4.27 → **5.20%** | 11.1 → **12.0%** | −1.29 → −1.46 cm | +1.33 → +1.21 cm |

*\*Astra's `proportions.py` measures narrowest transverse waist `W/H = 0.863` on `child-l2`, `hdFwd = +3.83 cm` and peak `ubBk = +5.89 cm` on `elder-l2`; differences reflect slice height/band conventions. All trends agree.*

---

## 2. Status of the 6 Fixes

| Fix | Status | Evidence & visual findings at 1600×900 |
|---|---|---|
| **1. Base proportions (`6.7–7.0` heads), neck & clavicles** | **MET** | Adults measure `6.88–6.98` heads, necks widened to `5.29–5.56%` (`man 7.01%`), and the front collar notch reads gently in close-up without breaking cel shading. |
| **2. Eliminate sleeve-root armpit wedges** | **MET** | The dark triangular armpit wedges are gone across all five mixes in `idle - front`, `3/4`, and `back`. `strain.json` confirms walk and run shoulder `p05–p95` inside `0.7012–1.2464` on all 10 GLBs. |
| **3. Unmistakable `woman` silhouette (`Sex_Female`)** | **PARTLY MET** | Quantitative targets hit (`hipW% 20.0%`, `W/H 0.648`, `bust +4.70 cm`, outer shoulder/hip `1.089`) and `woman` now reads unmistakably female at `Near`. **Visual defect:** `underbust = 0.015` on `k = 5` combined with `bust = 2.05` peaking at `j = 2, 14` (`cage.py:273-282`) creates two sharp underside pinch spots that render as distracting **dark circular dots** under the chest in `idle - front`, `idle - 3/4`, and `walk`. |
| **4. Unmistakable `elder` stoop & silhouette** | **PARTLY MET** | Forward head carriage (`+3.83 / +4.51 cm`), `3.3 cm` settle, `Sex_Male` reduced to `0.22`, thinner limbs, and separation from `man` are all achieved. **Visual defect:** concentrating kyphosis exclusively into `k = 5..10` (`b += 2.08 * stoop` + `0.54 * stoop`, jumping from `0` at `k = 4` and back to `0` at `k = 11`, `cage.py:251-264`) creates a **sharp hunchback fin/shelf** behind the shoulder blades clearly visible in `idle - 3/4` and Astra's profile still — it reads as an artificial fin rather than an anatomical spine curve and will deform Stage-3 coats. |
| **5. Refine `child` shoulders & head ratio** | **PARTLY MET** | `5.28` heads and `19.8%` shoulder span (down from `23.9%`) transform `child` into a genuine anime child silhouette. **Visual defect:** `Age_Child` `waist = 1.33` paired with `chest = 0.95` and `hip = 0.90` (`cage.py:83-86`) makes the waist flare outward wider than the ribcage above the waistband, producing a noticeable **pear/pot-belly bulge** in `idle - front`. |
| **6. Top-down extremity readability (`+10–12%` wrists/hands, `+8–10%` bare feet/ankles)** | **MET** | `+11%` wrist/palm scale and `+9%` horizontal ankle/foot area noticeably improve limb readability at `Near (8m)` and `Middle (12m)` while keeping bare close-ups natural. |

---

## 3. Updated Stage-1 Score Table (Body Only, 1–5)

| Criterion | Prior (`20d295395`) | Revised (`374f49ac1`) | One-line reasoning |
|---|---:|---:|---|
| **Rig, Skeleton & L1/L2 Architecture** | 5 / 5 | **5 / 5** | Bit-exact 82-joint `own-clips.glb` T-pose match (87/87 clips, 0.00° / 0.0 cm drift), 9 morphs, 6 materials, L1/L2 parity (`mean RGB diff ≤ 0.055/255`), and clean reciprocal bind-scale pivots. |
| **Deformation & Joint Mechanics** | 3 / 5 | **4 / 5** | Sleeve-root wedges eliminated cleanly with walk/run shoulder `p05–p95` inside `0.7012–1.2464`; docked 1 point for `child-l2` `2.42×` ground-sit saddle edge and `−1.2 cm` walk sole dip (placeholder hand `7.29×` excluded for Stage 2). |
| **Anatomical Polish (clavicles, shoulders, knees/calves, ankles/feet)** | 2 / 5 | **4 / 5** | Blue Protocol proportions (`6.88–6.98` heads), necks (`5.3–7.0%`), wrists/hands (`+11%`), feet (`+9%`), calves, and subtle collar notch all read well; docked 1 point for the three local morph contour kinks below. |
| **Man Reading as an Adult Man** | 4 / 5 | **5 / 5** | Clean, heroic adult male body (`6.98` heads, `7.01%` neck, broad smooth shoulders `1.797`, straight waist `0.924`, zero armpit wedges) — ready for Stage 2 as is. |
| **Woman Reading as a Woman** | 2 / 5 | **3 / 5** | Huge silhouette leap (`hipW% 20.0%`, `W/H 0.648`, narrow shoulders `1.089`, `bust +4.70 cm`), docked 2 points for the two distracting dark circular underbust shadow dots visible in front, 3/4, and walk. |
| **Elder Silhouette & Posture** | 1 / 5 | **3 / 5** | Real forward head (`+3.83/+4.51 cm`), `3.3 cm` settle, thinner limbs, and clean separation from `man`, docked 2 points for the sharp hunchback fin/shelf behind the shoulder blades in 3/4 and profile. |
| **Child Real Proportions** | 3 / 5 | **4 / 5** | Strong anime child proportions (`5.28` heads, `19.8%` narrow shoulders, `44.9%` leg ratio, `1.20 m`), docked 1 point for the pear-shaped waist bulge (`waist = 1.33` vs `chest = 0.95`) above the waistband in front view. |
| **4-Role Silhouette Distinctiveness at Play Distance** | 2 / 5 | **4 / 5** | All four cast archetypes (`woman`, `man`, `elder`, `child`) separate cleanly at `Near (8m)` and retain clear width/scale hierarchy at `Middle (12m)`. |
| **Total (out of 40)** | **22 / 40** | **32 / 40** | **+10 points** over initial pass. |

---

## 4. Verdict: **PASS WITH 3 SMALL `cage.py` CLEANUPS** (Do Not Redo; Quick Polish Gate Before Stage 2)

### Weighing `elder` vs `base` at `Middle (12m)`
- **Not a Stage-1 blocker.** `base` is the neutral generator midpoint, not an in-game town archetype. Among the four real archetypes (`woman`, `man`, `elder`, `child`), `elder` is already clearly narrower and smaller than `man`, narrower-hipped than `woman`, and much taller than `child` at `Near (8m)`. Once Stage 2 adds aged face geometry + grey/receding hair and Stage 3 adds elder garments/colours, `elder` will separate effortlessly at `Middle (12m)` as well.

### What still blocks a clean Stage-1 sign-off (3 small `cage.py`-only curve smoothings)
Every architectural, rigging, weight, normal-smoothing, and proportion requirement is **done**. Only **three localized surface kinks in `living/tools/blender/found/cage.py`** remain — all three are pure ~15-line curve/parameter adjustments that will save Stage 3 clothing from wrapping around ugly kinks:

1. **Smooth `elder`'s upper-back kyphosis (`cage.py:249-265`):** Replace the abrupt `b += 2.08 * stoop` step isolated to `k = 5..10` with a smooth bell curve spread across `k = 3..12` (peaking gentler around `k = 7..9`, tapering smoothly into lumbar `k = 3, 4` and neck base `k = 11` with `ubBk` around `~4.5–5.2 cm` instead of a sudden `+11.5 cm` fin). Verify in `idle - 3/4` and profile that the sharp shelf behind the shoulder blades is gone while keeping `hdFwd ≥ +3.5 cm`.
2. **Remove `woman`'s underbust shadow dots (`cage.py:273-282`):** Soften `Sex_Female` `underbust` (`0.015 → ~0.004–0.006`) and broaden the bust weighting across `j = 1, 2, 3` (less concentrated spike at `j = 2, 14`) so the bust reads as a smooth cel-shaded curve in `idle - front`, `idle - 3/4`, and `walk` with **zero dark circular spots** on the shirt while retaining `bust +4.0 to +4.7 cm`.
3. **Flatten `child`'s pear waist bulge (`cage.py:83-86`):** Bring `Age_Child` `waist` down from `1.33` to `~1.12–1.18` (and optionally bump `chest` `0.95 → 1.00`, `hip` `0.90 → 0.95`) so the child's ribcage-to-waist-to-hip outline is cleanly straight/softly cylindrical in `idle - front` instead of flaring wider than the chest above the waistband (keeping `W/H ≈ 0.82–0.88`).

Once those three `cage.py` curves are smoothed (a quick check of `woman`, `elder`, and `child` front + 3/4 + profile stills confirms them cleanly), Stage 1 is **PASS** and ready for **Stage 2 (3D anime head, B1 `hands.py` hands, and sculpted hair)**.
