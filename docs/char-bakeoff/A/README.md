# Track A · MPFB foundation

**Stage 1, ready for the foundation decision.** One young adult in a T-pose, with a cropped haircut, sleeveless training top and shorts. The native source retains the MakeHuman body, its modeling targets and its fitted A-pose rig. The game source keeps the body topology and separates the hair and eye drawing so the skull and joints can be inspected in Blender.

[Shared Bevy contact sheet](contact-sheet.png) · [Game GLB](cullet-base.glb) · [Editable MPFB source](mpfb-source.blend) · [Game-rig Blender source](cullet-base.blend)

| In the GLB | Measured |
|---|---:|
| Triangles | 34,120 |
| Exported vertices | 20,700 |
| Meshes / materials | 12 / 6 |
| Skin joints / weighted joints | 82 / 52 |
| Maximum joint influences per vertex | 4 |
| Bind dimensions including hair, width × height × depth | 1.897 × 1.833 × 0.295 m |
| Packed foundation, iris and strand textures | 2048 × 1024, 192 × 192, 256 × 512 |

The six materials cover the painted skin and underlayer, warm eye whites, teal irises, eye glints, dark brows and upper lids, and chestnut hair. The foundation paint follows the body. The top and shorts mark the proposed underlayer. They share the body's surface, so there is no loose cloth or independently swappable garment in this stage.

## Construction and sources

MPFB2 **v2.0.18**, commit `d0a32e57a7f915cb2f2b95410e2117648c7bbb7e`, ran in Blender **5.2.2 LTS**. The extension code is GPL-3.0-or-later. Its bundled HM08 mesh, modeling targets, Mixamo-named rig definition and weights are CC0 1.0. “Mixamo” here names MPFB's rig convention. The character uses the assets bundled with this release. Additional community packs contributed no assets. MakeHuman claims no rights over the generated output. [Official release source](https://github.com/makehumancommunity/mpfb2/tree/v2.0.18) · [Upstream license and output terms](https://github.com/makehumancommunity/mpfb2/blob/v2.0.18/LICENSE.md)

The base uses MPFB age, gender, muscle, weight and proportions macros. Local targets shorten the chin, narrow and flatten the mouth and nose, and open the eyes. A smooth socket adjustment moves the lid loops and eye helper landmarks together. The original body UV is retained. A second UV set carries the jersey binding, seams, shorts, blush and lip tint. The old head atlas assumes a different skin layout. The iris painter can be reused directly, as can the game's swept hair geometry and strand painter. The outfit generator assumes the former body and was unnecessary for the fitted underlayer. The shared rig, style and animation inputs are project assets from render set `61421f56f964`.

The game rig uses **all 82 joint names, parents and rest-local transforms** of the shared clip file. The conversion maps the 52 weighted MPFB joints to the corresponding spine, neck, head, limbs, toes and all three segments of each finger. It fits the native limb lengths to the shared T-pose and sets hand roll from the index-to-little-finger direction. Topology-aware weight averaging at the larger joints reduces abrupt changes across short crease edges. Eye geometry and the cropped hair follow the head. The GLB carries the original shared idle (5.967 s) and walk (1.000 s) samples. The game faces the viewer through the armature object's placement.

## Rebuild and verify

Run from the repository root. The first argument is the shared clip file from the extracted render set. Its sibling style tree must contain `styles/hair/swept.glb` one directory above `anim`. The script installs the pinned extension inside the worktree's private Blender profile. The second argument must be a fresh output directory.

```bash
docs/char-bakeoff/A/build.sh "$lookdev/anim/own-clips.glb" "$PWD/.local/track-A-rebuild"
export PATH="$HOME/.local/share/slop-tools/build-bin:$PATH" JOBS=3
export BLENDER_USER_RESOURCES="$PWD/.local/mpfb-profile"
blender -b -t 3 --python-exit-code 2 -P docs/char-bakeoff/A/verify.py -- \
    "$PWD/.local/track-A-rebuild/cullet-base.glb" "$lookdev/anim/own-clips.glb"
CARGO_BUILD_JOBS=8 CARGO_TARGET_DIR="$PWD/.local/target-A" \
    ~/.local/state/bakeoff/shoot.sh "$PWD/.local/track-A-photos" "$PWD/.local/track-A-rebuild/cullet-base.glb"
```

The shared photographer runs the game build under the dev-box's shared gate lock. The judging sheet has 17 Bevy stills: three idle views, face and hands, Near, Middle, the game camera, six walking frames and three bind views. Full-size stills and renderer reports from the final shoot are in `.local/photos-A6/`. The numeric verification log is `.local/final-verified.log`. The verifier checks all joint parents and local transforms and compares the time and value arrays of all 53 channels in each clip with the original.

## Deformation and remaining work

The exported body was reimported and sampled at frames 1, 6, 12, 18 and 24 for each clip. The measurement divides posed edge length by bind edge length for edges longer than 0.1 mm. After weight adjustment the central 98% of ratios span **0.77–1.17** for walk and **0.77–1.16** for idle. A 1.6 mm toe edge previously stretched 5.73× in walk. The final largest walk ratio is 2.23× at the hip crease. Idle reaches 2.26× at the thumb base. Some edges still compress sharply. Deep squats, overhead reach, gripping and facial animation remain unverified. The hands look narrow from the front, and the face and haircut read much more clearly in close-up than from the play camera.

The first clip import produced empties because the shared library stores its hierarchy without a skin. The build supplies inverse bind matrices for import. A Blender scene-library write crashed during the first attempt to save the native source. Saving the full editable project succeeded. The first shoot exposed a stair-stepped neckline and oversized lip color. The second used continuous painted boundaries. A later Blender animation export rounded sample times to the scene frame rate. The shipped GLB copies the original samples directly. Blender also logged a system OpenColorIO version mismatch and an unavailable optional MeshOptimizer library. The judged images are from Bevy loading the uncompressed GLB.

**Stage 2 awaits the foundation decision.** The native mesh and its age, sex, build, height and face targets provide an editable starting point for the four profiles. The game export currently bakes one body shape. A town of 64 would need a tested range for the fitted shapes, shared material and texture pages, and a choice of hair, palette and fitted garments per resident. No four-profile or 64-person result has been verified. Stage 3 garment layer fitting remains open.
