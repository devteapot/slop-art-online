# Character Bake-Off · Track C (Yardstick: S7 / Render Set `eab260ef1df8`)

Track C is the yardstick: today's composed character generator as S7 left it, rendered through the game's own Bevy renderer (`living/tools/view_assets.sh`) using the shared bake-off shot list ([shots.env](shots.env) and [shoot.sh](shoot.sh)).

## Shared shot list

- **[shots.env](shots.env)** (also published to `~/.local/state/bakeoff/shots.env`):
  - `LIVING_GAME_SIZE="1600x900"`, `LIVING_GAME_HOUR="11"`, `LIVING_GAME_DAY_MINUTES="0"`
  - `LIVING_GAME_VIEW_SHOTS="idle@1.0/front,idle@1.0/three-quarter,idle@1.0/back,idle@1.0/0:8:0.22:0.88,idle@1.0/near@0,idle@1.0/middle@0,idle@1.0/game,walk/three-quarter"`
  - `LIVING_GAME_VIEW_SHOTS_BIND="front,three-quarter,back"` (second pass with `LIVING_GAME_VIEW_CLIP=bind`, since `living/game/src/view.rs` activates bind pose per-process via `LIVING_GAME_VIEW_CLIP=bind`)
- **[shoot.sh](shoot.sh)** (also published to `~/.local/state/bakeoff/shoot.sh`): sources `shots.env`, runs both passes through `living/tools/view_assets.sh` under `flock -s ~/.local/state/slop-build/gate.lock` with `CARGO_BUILD_JOBS=8` and a private `CARGO_TARGET_DIR`, merges the per-character stills and `report.json`, and builds one labelled 4×4 contact sheet per character.

## Contact sheets

- **[contact-sheet.png](contact-sheet.png)** — all four Cullet characters side-by-side across `idle · front`, `idle · 3/4`, `idle · back`, `face close-up`, `Near (8m)`, `Middle (12m)`, `play (game)`, `walk f0 · 3/4`, and `bind · front`.
- **[stage1-woman.png](stage1-woman.png)** — full 16-shot Stage-1 comparison of today's base young woman (`adult-f-b`) in the least-dressed plain underlayer the current generator allows.

## Source assets

All five renders come from the pinned render set `~/slop-assets/current` (`eab260ef1df8`, built from `31c22edf`, KTX2-BC7 textures), linked into the worktree via `python3 living/tools/render_set.py link --repo .`. Shared animation clips come from `lookdev/anim/own-clips.glb` (87 clips).

Shared texture footprint in the pinned render set:
- `lookdev/pages/types-far.ktx2` (258 KB), `types-iris.ktx2` (27 KB), `types-tint.ktx2` (251 KB)
- `lookdev/strands.ktx2` (115 KB)
- Per-type face/atlas textures: `lookdev/types/<type>.atlas.ktx2` (~130 KB) and `lookdev/types/<type>.face.ktx2` (~94 KB)

## Per-character summary

Metrics are from `view_assets.sh`'s `report.json` (triangles, vertices, meshes, materials, height) and GLB skin inspection (joint counts; the type skeleton has 82 joints, with up to 5 extra hair spring joints on hanging hair styles).

| Role | Resident / Look key | Type | Height (m) | Triangles | Vertices | Meshes | Materials | Joints (type / max) | Hair & outfit pieces |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| **Young woman** | Cora Stannard (`lk_d423463d51caeaad`) | `adult-f-c` | 1.65 | 40,222 | 25,113 | 20 | 11 | 82 / 87 | `braid.collar`; `coat-f`, `jersey_coat-f`, `trousers-f`, `boots-f`; overlay: `lines` |
| **Man (adult)** | Eamon Tarn (`lk_fad54e60db874d56`) | `adult-m-b` | 1.78 | 37,562 | 23,711 | 24 | 13 | 82 / 85 | `tail.2.collar.m`; `coat_1-m`, `jersey_coat-m`, `trousers-m`, `boots-m`; overlays: `beard_goatee`, `freckles` |
| **Elder** | Halvard Dunmore (`lk_7ef777ee17cad6e3`) | `elder-m-c` | 1.76 | 37,994 | 24,110 | 25 | 13 | 82 / 82 | `sides.cap`; `coat_2-m`, `jersey_coat-m`, `trousers-m`, `boots-m`, `cap`; overlays: `beard_full`, `stubble`, `lines` |
| **Child** | Juno Brandt (`lk_8bd684a147bb4068`) | `child-u-b` | 1.27 | 34,494 | 21,180 | 24 | 11 | 82 / 82 | `bob`; `smock_58-m`, `smock_bands-m`, `jersey_smock-m`, `apron_58-m`, `trousers-m`, `boots-m`; overlay: `freckles` |
| **Stage-1 base (young woman)** | `stage1_woman` (zeroed identity) | `adult-f-b` | 1.66 | 31,486 | 20,487 | 17 | 10 | 82 / 82 | `bob`; `jersey-f`, `trousers-f`, `boots-f`; no overlays |

### Materials per character (`report.json`)

- **Base 10 materials** (all five characters): `M00_000_Hair_00_HAIR`, `M00_001_01_Cloth_01_CLOTH`, `M00_000_00_Face_00_SKIN`, `M00_000_00_Eye_00_EYE`, `M00_000_00_EyeIris_00_EYE`, `M00_000_00_FaceEyeline_00_FACE`, `M00_000_00_FaceBrow_00_FACE`, `M00_000_00_Body_00_SKIN`, `M00_000_00_FaceTint_00_FACE`, `M00_000_00_Body_01_SKIN`.
- **+1 face overlay** (`M00_000_00_FaceOverlay_00_FACE`): Cora, Eamon, Halvard, Juno.
- **+2 beard/hair overlays** (`M00_000_00_Overlay_00_HAIR`, `M00_000_00_FarOverlay_00_HAIR`): Eamon, Halvard.

## Stage-1 note: no bare body mesh in today's generator

Today's generator **cannot produce a bare or underwear base body**: in every type GLB (`lookdev/types/<type>.glb`), the `Skin` mesh covers only the neck and hands (`y = 1.381..1.522 m` in bind pose). The torso, arms, legs, and feet exist only as garment pieces (`jersey-*`, `trousers-*`, `boots-*`, coats, smocks). Therefore `stage1_woman` ([stage1-woman.png](stage1-woman.png)) shows the **least-dressed** configuration the current generator supports: `adult-f-b` with zero identity offsets in plain `jersey-f` + `trousers-f` + `boots-f` and `bob` hair, with no coat, smock, apron, headwear, or face overlays.

## How today's generator varies into a town of 64

- 21 designed face/head types (`adult/youth/elder` × `m/f` × `a/b/c`, plus `child-u-{a,b,c}`) with 25 identity bones (38 face parameters) and body proportion multipliers (`height`, `legs`, `arms`, `torso`, `shoulders`, `hips`, `build`, `hands`, `feet`, `head`, `belly`).
- Composed at runtime from shared GLB files: 50+ hair style/cut variants, 26+ outfit piece files (coats, smocks, jerseys, trousers, boots, aprons, caps, kerchiefs), and 72 face/beard overlay files, recoloured per-person via look-book palette entries (`characters/looks.json`).
