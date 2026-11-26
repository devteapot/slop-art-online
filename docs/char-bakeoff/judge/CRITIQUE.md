# Character Bake-Off · Stage 1 Visual Critique & Foundation Verdict

**Date:** 2026-11-26  
**Machine:** dev-box  
**Scope:** Stage 1 foundation decision (one solid base human) across Tracks **A**, **B1**, **B2**, and **C** (yardstick), with Stage 2 (4-role comparison of B2 vs C) as supporting reference.  
**Sheets:** [`stage1-compare.png`](stage1-compare.png) · [`stage2-compare.png`](stage2-compare.png)

---

## 1. Re-Shoot Methodology & Problems Encountered

All 12 models (Stage 1: A `cullet-base`, B1 `own-b1-base`, B2 `b2-woman` & `b2-base`, C `look:stage1_woman`; Stage 2: B2 `b2-man`, `b2-elder`, `b2-child` and C `look:woman_cora`, `look:man_eamon`, `look:elder_halvard`, `look:child_juno`) were re-photographed in the game's own Bevy renderer (`living/game`, 1600×900, 11:00 daylight) through `~/.local/state/bakeoff/shoot.sh` against the pinned render set `~/slop-assets/current` (`eab260ef1df8`).

Every re-shot face was visually verified against its track's own contact sheet; all face, hair, and eye-ink sidecars loaded cleanly with zero missing layers. `b2-base.glb` (which retains all 8 morph targets) and `b2-woman.glb` (zero mix baked) rendered virtually identically (mean RGB diff `0.0000–0.0014` across all 14 animated shots), so `b2-woman` represents B2 on `stage1-compare.png`.

### Re-shoot problems hit and how they were resolved

1. **`view.rs` drops sidecar textures for GLBs outside `living/game/assets/`:** `living/game/src/view.rs` copies only the `.glb` file into `assets/view/`, omitting sibling `.face.png`, `.hair.png`, and `.eyes.ink.png` sidecars required by B1 (`own-b1-base`). Furthermore, `living/tools/render_set.py link --repo .` symlinks `living/game/assets/view` to a read-only folder inside `~/slop-assets/eab260ef1df8/`.
   - **Resolution:** Kept untouched copies under `.local/judge-inputs/`, replaced the read-only `living/game/assets/view` symlink in this worktree with a local git-ignored folder `living/game/assets/view/judge/{A,B1,B2}/` containing each GLB alongside all its sidecars, and passed asset-relative `view/judge/...` paths to `shoot.sh`.
2. **Shared `shots.env` (`zoom=0.62`) crops the head and feet of narrow A-pose models (B1 and B2):** `view.rs::framing()` derives perspective orbit distance from the 3D bounding-sphere radius `half.length()`. T-pose models (Track A: `1.90 × 1.83 m`, `radius/height = 0.886`; Track C: `1.59 × 1.66 m`, `radius/height = 0.841`) inflate `half.x` with outstretched arms, whereas narrow A-pose models (B1: `0.61 × 1.65 m`, `radius/height = 0.564`; B2: `0.61 × 1.70 m`, `radius/height = 0.561`) have a ~35% smaller bounding-sphere radius. Under unmodified `shots.env`, `0:8:0.62:0.50` puts the camera too close and decapitates B1 and all five B2 models (the same issue that forced B2's `shoot_all.sh` to run a separate `zoom=1.0` pass).
   - **Resolution:** Preserved the unmodified `shoot.sh` outputs in `.local/judge-shots/`, and ran a second `shoot.sh` pass (`.local/judge-shots-apose-norm/`, `SHOTS_ENV=.local/apose-norm.env`) scaling only the orbit zooms by `1.50×` (`0.93`, `0.33`, `0.39` vs T-pose `0.62`, `0.22`, `0.26`) for B1 and B2 so every row has identical vertical framing (~89% frame height) per metre of body height. World-space play cameras (`Near 8m`, `Middle 12m`, `play 22m`) are unaffected by `framing()` and come untouched from the raw `shoot.sh` pass, displayed as identical 1:1 native-pixel center crops (`400×225`) so silhouettes can be compared directly without downsampling blur.
3. **Track C's `stage1_woman` is not in the pinned render set's look book:** It lives in Track C's `.local/bakeoff-book.json` alongside the four Cullet cast aliases (`woman_cora`, `man_eamon`, `elder_halvard`, `child_juno`).
   - **Resolution:** Copied Track C's `.local/bakeoff-book.json` to `.local/judge-inputs/C/bakeoff-book.json` and passed it via `LIVING_GAME_LOOK_BOOK`.
4. **Missing hands close-up on B1's original sheet:** Track B1's committed `contact-sheet.png` predated the `hands close-up` addition to `shots.env` (16 shots vs 17). Our re-shoot captured B1's hands close-up cleanly under identical framing.

---

## 2. Measured Inventory (From Bevy `report.json` & GLB Inspection)

| Track / Model | Triangles | Vertices | Meshes | Materials | Joints | Morph Targets | Clips (embedded / Bevy available) | Bind Size W×H×D (m) | Textures |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| **A** · `cullet-base.glb` | 34,120 | 20,700 | 12 | 6 | 82 (T-pose) | 0 | 2 (`idle`, `walk`) / 2 | 1.90 × 1.83 × 0.30 | 3 packed (`2048×1024`, `192²`, `256×512`) |
| **B1** · `own-b1-base.glb` | 68,654 | 41,128 | 4 | 15 | 82 (A-pose) | 15 (`Fcl_*`) | 6 / 87 (shared via `own-` prefix) | 0.61 × 1.65 × 0.30 | 3 packed (`1024²`, `192²`, `512²`) + 3 sidecars (`512²`, `2048²`, `2048²`) |
| **B2** · `b2-woman.glb` (`b2-base.glb`) | 42,772 (L1: 15,168) | 21,923 | 3 | 6 | 82 (A-pose) | 2 (`b2-base`: 8 body + 2 `Fcl`) | 6 / 6 | 0.61 × 1.70 × 0.33 | 1 packed (`1024²` RGBA face decal) |
| **C** · `look:stage1_woman` (`adult-f-b`) | 31,486 | 20,487 | 17 | 10 | 82 (T-pose) | 15 (`Fcl_*`) + 25 id bones | shared / 87 | 1.59 × 1.66 × 0.33 | Shared KTX2 render-set pages |

*Stage 2 reference:* B2's four models range `39,944–42,772` tris (`12,392–15,168` at L1), `6` mats, heights `1.34–1.83 m`; C's four clothed Cullet models range `34,494–40,222` tris, `11–13` mats, heights `1.27–1.78 m`.

---

## 3. Score Table (1–5)

Scale calibrated against the owner's quality bar (Corepunk, League of Legends, **Blue Protocol** as closest style bar, SUPERVIVE) and our own Cora references (`docs/cage-taper/cora.webp`, `docs/char-live-2/final/review-sheet.png`, `docs/char-live-3/ink-batch-2/review-sheet.jpg`):  
`5` = matches the production bar · `4` = strong foundation close to the bar · `3` = serviceable with notable structural gaps · `2` = visibly weak / clashing · `1` = fails the brief or style bar outright.

| Criterion | Track A (MPFB2) | Track B1 (Cage + Cora head) | Track B2 (Parametric cage) | Track C (S7 yardstick) |
|---|---:|---:|---:|---:|
| **Detail** | **2** | **3** | **2** | **2** |
| **Silhouette at play distance** | **2** | **3** | **3** | **2** |
| **Face appeal & style fit** | **1** | **4** | **2** | **2** |
| **Hands** | **2** | **4** | **3** | **2** |
| **Materials** | **2** | **3** | **3** | **3** |
| **Clipping & deformation** | **3** | **3** | **3** | **2** |
| **Topology & Stage 2/3 readiness** | **3** | **3** | **4** | **1** |
| **Town of 64 variation** | **2** | **2** | **4** | **3** |
| **Total (out of 40)** | **17** | **25** | **24** | **17** |

### One-line reasoning per score

#### Track A · MPFB2 / MakeHuman (`cullet-base.glb`) — **17 / 40**
- **Detail (2/5):** Genuine realistic anatomy (clavicles, toes, ribs, navel), but HM08's high-frequency normals shatter our cel shader into blotchy olive shadows across the torso and collarbone, with teal UV-seam bleed on the neck.
- **Silhouette at play distance (2/5):** Stretched to `1.83 m` (male clip-rig height despite female macro), with a flat close-cropped scalp that dissolves into skin tone at 12 m and 22 m.
- **Face appeal & style fit (1/5):** Uncanny semi-realistic MakeHuman jaw/double-chin, bulging spherical eyes, flat painted mouth, and glued-on patchy hair — completely incompatible with our Blue Protocol / Cora anime-leaning toon style.
- **Hands (2/5):** Thin, pinched, claw-like fingers with an awkward wrist/forearm kink introduced by Mixamo-to-`own-clips` retargeting.
- **Materials (2/5):** Lean count (6 mats, 3 packed textures), but painting skin + cloth onto one planar front/back 2048×1024 map creates seam artifacts, zero skin-vs-cloth material separation, and muddy cel-shadow pooling.
- **Clipping & deformation (3/5):** Tightest measured walk/idle edge-ratio distribution (`p01–p99 = 0.77–1.17`, max walk `2.23×`) and bit-exact 82-joint T-pose match to `own-clips.glb`, though deep flexion (`sit_ground`) and facial animation are unverified/absent.
- **Topology & Stage 2/3 readiness (3/5):** Real CC0 HM08 quad loops with upstream sex/age/build targets exist in Blender, but the exported base has zero morph targets, zero facial expressions, rigid detached eye/brow parts, and dense realistic loops that fight toon shading.
- **Town of 64 variation (2/5):** Requires bespoke per-person baked GLBs and 2048×1024 textures today with no shared runtime morphing or LOD, and the underlying realistic aesthetic scales poorly into appealing anime townsfolk.

#### Track B1 · Hand-made cage + Cora head (`own-b1-base.glb`) — **25 / 40**
- **Detail (3/5):** By far the best head, hair, and hands (sculpted swept locks, rear plait, ink lids, nostrils, nail beds), but the body itself is plain and tubular (weak clavicles, flat calves, featureless socked feet, squared shoulder caps).
- **Silhouette at play distance (3/5):** Warm copper fringe and braided plait anchor the character immediately at Near, Middle, and play, though the desaturated grey-green top and grey shorts blend into the green checker and the shared wide-stance idle softens posture.
- **Face appeal & style fit (4/5):** The only face in the bake-off that genuinely hits our Blue Protocol / Cora style target (calibrated `char-live-3` head with ink upper lid + lash fringe, freckles, warm blush, and 15 expressions); docked 1 point for the slight lower-cheek/jaw dent and being a single unmorphed female head.
- **Hands (4/5):** Easily the best hands in the bake-off — clean palm-to-finger web topology (`hands.py`), knuckle support rings on both sides of each joint, natural finger taper/curl, nail-bed regions, and clean wrist cuffs.
- **Materials (3/5):** Face, hair, and eye-ink shaders are calibrated to our renderer, but 15 materials and 6 textures (up to `2048²`) are far too heavy for a Stage-1 bare base, and the flat grey body materials show bright crease triangles under the armpits.
- **Clipping & deformation (3/5):** Clean 6-frame walk cycle with 87 shared clips available via `own-` prefix and clean elbow/knee bends, but deep flexion pinches the groin (`0.091–3.52×` in `sit_ground`, visible V-pinch shadow in idle), and the neck is still a separate mesh tucked into the torso opening.
- **Topology & Stage 2/3 readiness (3/5):** Clean all-quad body cage (`4,459` verts -> `35,512` tris at subdiv 1) with good shoulder openings and finger webs, but zero body/face identity morphs (hardcoded for Cora), binary GLB grafting onto a separate head file, heavy hair (`24,276` tris; `68,654` total), and narrow A-pose skeleton.
- **Town of 64 variation (2/5):** Proves only one character at nearly 69k tris and 15 materials; neither sex/age/build morphing nor generalizing Cora's bespoke ink-map head across men, elders, and children has been demonstrated.

#### Track B2 · One-cage parametric base (`b2-woman.glb` + Stage 2) — **24 / 40**
- **Detail (2/5):** Clean, smooth forms with subtle vertex-colour joint warmth (knees, elbows, knuckles), but Playmobil-plain overall: no collarbones, no modelled eye sockets/lids/lips, near-absent ears (tiny nubs on man/elder), faceted spiky hair shells, and slightly scalloped sleeve edges.
- **Silhouette at play distance (3/5):** Clear colour-blocking (copper hair, lavender top, dark shorts, brown shoes) reads cleanly against the ground at Near, Middle, and play, though the stiff conical helmet-bob reads boxy from above.
- **Face appeal & style fit (2/5):** Clean and cute on the woman and child at a glance, but reads like a Mii / 2D-decal doll rather than Blue Protocol; Stage 2 exposes the ceiling sharply — `b2-man` reads like a 12-year-old boy with spiked bangs, and `b2-elder` looks like a smooth egg with a painted sticker moustache.
- **Hands (3/5):** Smooth, clean anime silhouette with warm knuckle/tip tinting, though 4-edge finger tubes and a stubbier thumb have noticeably less anatomical structure and articulation than B1.
- **Materials (3/5):** Cleanest material discipline in the bake-off (6 materials, 1×`1024²` texture, vertex-colour AO/blush/waistband/sole keeping base colours free), shading smoothly under our toon shader — docked because the unshaded floating `FaceLayer` decal bypasses 3D face shading and surfaces lack fabric/hair detail.
- **Clipping & deformation (3/5):** Smooth walk cycle across all 4 people (plus verified `run`/`sit_ground` in B2's sheet) from subdividing cage-level bone-heat weights, but the single crotch vertex creates a dark diamond crease, the narrow A-pose skeleton is untested against the 87 shared `own-clips.glb` clips, and expressions are binary Z-swap patches (`Fcl_EYE_Close`, `Fcl_MTH_A`) not yet driven by the client.
- **Topology & Stage 2/3 readiness (4/5):** Best Stage 2/3 body architecture by a clear margin — one unified parametric quad cage (`1,094` verts -> `8,856` body tris at L1 / `35,424` at L2), 8 topology-preserving body/face morphs already proven across 4 roles + 16 people, and clean surface basis for Stage-3 clothing layers. Its head topology (featureless lathe + floating decal) is its major dead end.
- **Town of 64 variation (4/5):** Best runtime-scaling model: one shared body mesh + 8 morph weights + scale + 4 material colours + swappable hair + parameterized face texture (or shared atlas tile) at `6` materials and `12k–15k` tris at L1 — bottlenecked visually by the simplistic decal-face and spike-hair art style.

#### Track C · Yardstick S7 (`look:stage1_woman` + 4 Cullet roles) — **17 / 40**
- **Detail (2/5):** Knit stripes and boot cuffs add surface break-up, but there is no bare body mesh (garments *are* the body), trouser/waist rings facet visibly, and chest/pelvis planes look stiff and flat.
- **Silhouette at play distance (2/5):** `stage1_woman`'s low-contrast beige/grey values fade into the checker at 12 m / 22 m; clothed Stage-2 coats add mass, but blocky shoulders and stiff coat cones lack the crisp shape language of Blue Protocol or SUPERVIVE.
- **Face appeal & style fit (2/5):** Recognizably anime-leaning, but hampered by S7's pinched flat chin/jaw, wide glassy eyes with bright orange lower glow, thin high brows, paper-thin bob cap, and dated look across all four Stage-2 roles.
- **Hands (2/5):** Rigid paddle-like hands with stiffly splayed thumbs and awkward floating cuff seams where the separate hand primitive meets sleeves.
- **Materials (3/5):** Proven KTX2 shared-page pipeline (`10–13` mats, tiny shared texture footprint) with real cloth striping, though vertical facet banding shows through on the trousers and skin-to-collar joins read pasted-on.
- **Clipping & deformation (2/5):** Runs all 87 shared clips, but `stage1_woman`'s front close-up exposes a hollow gap around the collar rim, boxy shoulder deformation, and faceted crotch shading.
- **Topology & Stage 2/3 readiness (1/5):** Fundamentally fails the Stage 1–3 brief — has no underlying human body mesh at all (only neck and hands), making swappable layered clothing over a morphed base impossible without starting over.
- **Town of 64 variation (3/5):** Proven runtime composition across 64 residents (21 types, 50+ hair files, 26+ outfit pieces, 72 overlays, far LODs), so the *packaging* works, even though the underlying meshes fail the quality bar.

---

## 4. Overall Ranking & Foundation Recommendation

### Ranking
1. **Track B1** — `25 / 40` *(strongest craft: face, hair, hands, style fidelity)*
2. **Track B2** — `24 / 40` *(strongest architecture: single parametric quad cage, Stage-2 morphs, L1/L2 LOD, 6-material discipline)*
3. **Track A** — `17 / 40` *(tie — useful rig-verification tooling, wrong aesthetic/normal base for cel shading)*
4. **Track C** — `17 / 40` *(tie — yardstick; proves runtime packaging works, confirms base meshes must be replaced)*

### Verdict: Build a **Hybrid Foundation (B2 Body Cage + Morphs × B1 Head/Hair & Hands, on `own-clips.glb`'s T-Pose Rig)**

**Do not advance any single track unmodified to Stage 2:**
- Picking **B1 alone** locks us into a single unmorphed 68.7k-tri / 15-material Cora file with a separate tucked neck seam and narrow A-pose rig — we would have to rebuild B2's parametric morph cage from scratch anyway.
- Picking **B2 alone** locks us into a smooth lathe head + 2D floating decal + spiky Playmobil hair that already breaks down badly on `b2-man` and `b2-elder` in Stage 2 (`stage2-compare.png`), far below the Blue Protocol / Cora bar.
- Picking **Track A** fights MakeHuman's realistic anatomy and normals at every step; keep only Track A's `verify.py` habit of asserting exact joint hierarchy/transforms against `own-clips.glb`.
- **Track C** stays strictly as the runtime composition/KTX2-page/LOD reference once the new foundation replaces its base meshes.

### Concrete Hybrid Plan (Finish Stage 1 -> Unlock Stage 2)
1. **Unified Body Cage (B2's architecture + B1's hands + anatomical polish):**
   - Start from B2's low-vertex parametric quad cage (`~1.1k–2k` verts) so **L1 (`~9k–12k` tris)** serves play/crowd and **L2 (`~30k–35k` tris)** serves close-ups from the exact same topology, UVs, weights, and morph targets.
   - Replace B2's 4-edge finger tubes with **B1's `hands.py` connected finger-web, knuckle support-ring, and tapered thumb topology**.
   - Re-author the cage rest pose directly on **`own-clips.glb`'s 82-joint T-pose skeleton** (verified with Track A's `verify.py` check) instead of Cora's narrow A-pose armature, so all 87 shared clips drive it natively without rest-pose mismatch or camera-framing quirks.
   - Upgrade Stage-1 body anatomy where both B1 and B2 are currently too soft: add subtle **clavicle/neck-base planes, clean shoulder-cap transitions, defined knee/calf curves, and properly shaped ankles/feet**, and fix the crotch pole/saddle pinch in deep flexion (`sit_ground`).
2. **Head, Face & Hair (B1's 3D craft, made parametric & budget-disciplined):**
   - Reject B2's smooth lathe + 2D floating `FaceLayer` sticker. Build a **real 3D anime head** with proper eye sockets, eyelid loops, mouth interior, sculpted ears, and 15 `Fcl_*` expression targets matching B1 / `char-live-3`'s Cora ink-lid and face-shadow quality — welded continuously onto the body cage's neck ring (no separate tucked-neck seam) and fixing Cora's minor lower-cheek/jaw dent.
   - Keep B1's sculpted lock-flow hair aesthetic, but cut its polygon budget from B1's `24,276` tris down to **`~4k–7k` tris near / `~1.5k` tris far** so a full character lands around `~15k–20k` tris at play LOD (and `~35k–45k` tris close-up) within `6–8` materials.
3. **First Stage-2 Gate before Stage-3 clothing:**
   - Before touching garments, prove that the hybrid head + body morphs produce an appealing **young woman, adult man, elder, and child** (not just Cora) — with proper child limb-to-torso proportions rather than uniformly scaling the adult skeleton.

---

## 5. What Even the Hybrid Winner Still Lacks Against the Owner's Quality Bar

Compared against the owner's six reference images (Corepunk, League of Legends, **Blue Protocol**, SUPERVIVE):
- **Stylized anatomical poise & silhouette rhythm:** Blue Protocol (`ref4`), League (`ref3`), and SUPERVIVE (`ref5`) bodies have crisp shoulder-to-waist taper, legible clavicles, clean shin/calf curves, and confident neutral posture. Both B1 and B2 currently look slightly straight-sided and mannequin-soft, and our shared `idle` clip puts every character into an awkward wide-legged half-squat that hurts silhouette at every distance.
- **Male, elder, and diverse cast appeal:** Blue Protocol's cast (`ref4`) shows strong, appealing stylized men, varied skin tones, and crisp angular/soft jaw variety all sharing one cohesive cel-shaded language. We have only proved one young woman (`Cora`) at that face bar; proving an equally strong adult man and elder on the new 3D head topology is still ahead.
- **Material richness & crisp shape break-up:** Flat untextured base-colour fills (B1's grey onesie, B2's smooth pastel blocks) read flat up close compared to Blue Protocol and Corepunk (`ref2`). Stage 3's layered garments (collars, hems, seams, belts, coats, boots with real thickness and clean cel-shadow breaks) are needed to reach the locker/portrait bar.
- **Play-camera readability (`Middle` / `play`):** At 12 m and 22 m (compared with Corepunk `ref1` and SUPERVIVE `ref6`), muted grey/olive underlayers dissolve into the ground checker. Bold value contrast between hair, torso, waist/trousers, and boots — plus a cleaner upright idle stance — will make characters pop cleanly at gameplay distance.
