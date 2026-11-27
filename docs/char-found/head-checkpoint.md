# Stage 2 head fitting checkpoint

The face works in the game, but the male and elder heads still read too much like the same young face. The angular change where the back of the skull meets the neck is visible in the level profile, and the child has a hard corner below the ear. These are visible with the facial surface isolated from the body. At Near and Middle, the child’s height and the man’s shoulder span still do most of the recognition work. The checkpoint stops at the head gate, before replacement hands and hair.

[Shared-scale front and profile lineup](lineup.png) · [Five heads in six expressions](head-expressions.png) · [Live blink and speech](live-face.png)

## Geometry and fitting

The head fitter takes a generated Stage 1 GLB. It removes the placeholder skull and fits the project-owned Cora master’s socket, lids, eyes, ink, brows, mouth interior and face-tint surface to the shared rig. Seven of the existing nine identity targets change the facial landmarks. Their defaults follow the body. The expression displacements follow the fitted landmarks too. The master’s 56-station throat opening joins the foundation neck through a strip with matching positions, skin weights and shape displacements at both ends. The earlier overlapping neck sleeve left a visible gap on the child. The fitted strip closes the opening but the contour still needs sculpting.

The fitter reuses the outputs of the Cora head, face paint and designed-normal pipeline from `docs/char-live-2/final`, including the 1024² colour atlas, 192² iris, 512² tint and 512² drawn face-shadow sidecar. It applies a 0.4 outline weight to the face. All five mixes still use Cora’s pigment and shadow design. The hand mesh and weights are the Stage 1 placeholders. The sculpted hair, final texture treatment, hand-grip work and final near/far head topology are outstanding.

## Reproduction

From the repository root, after generating Stage 1 with the body generator:

```bash
python3 living/tools/blender/found/head.py \
  living/game/assets/view/char-found/elder-l2.glb \
  living/game/assets/view/stage2-verify/elder-l2.glb
```

`--expression Fcl_EYE_Close` sets a default expression for a calibration copy. The export includes all 15 expression targets under their original names and the VRM 0.x expression bindings. The six-column sheet uses otherwise identical exports at neutral, blink, A, eye joy, angry brow and surprised brow.

For the separate runtime proof, the game opened the neutral woman GLB, registered its face with the live VRoid rig, and ran `LIVING_GAME_ACT=talk` in the asset view’s bind mode. The face continued to animate while the body held its pose. The live strip shows rest, blink and open mouth from captures 06, 05 and 12 of that run. The standard animated file-view path plays embedded clips and skips the procedural face driver. The live proof covers the bind/talk path. The expression sheet covers embedded skin and morph rendering during a fixed idle frame.

The lineup uses the game’s orthographic mode, pitch 0°, yaw 0° and 90°, a 1.96 m vertical frame and a camera 0.94 m above ground, for all ten stills. Each camera reported 459.184 px/m. Matched background plates isolate the flat silhouettes. All columns and both rows use the same crop dimensions.

## Mesh counts

All five mixes share the following counts. Hands are counted distal to wrist ring 9, including both palms, thumbs and fingers. The head count includes its neck join.

| Level | Body | Placeholder hands | Head | Hair | Used materials | Embedded images + sidecar |
|---|---:|---:|---:|---:|---:|---:|
| L1 | 5,440 | 1,824 | 7,028 | 0 | 11 | 3 + 1 |
| L2 | 21,760 | 7,296 | 7,060 | 0 | 11 | 3 + 1 |

Each export passed the shared skeleton rest-translation check. All ten preserve the source animation table and key buffers byte for byte. The facial deformation evidence records the minimum, p05, p95 and maximum posed-to-rest edge-length ratio for each expression. Edges shorter than 0.1 mm at rest are excluded. Closing lids and opening lips can change individual edges sharply. [Per-export counts and expression strain](evidence/head-fit.json)

All ten checkpoint exports played all 87 takes in Blender with the authored bind transforms restored. `clips_compare.py` found 0.00° rotation and 0.0 cm translation drift on every take. For shoulders, the walk p05–p95 envelope was 0.7115–1.2453 and the run envelope was 0.7123–1.2248. The placeholder man L2 hand still has a 7.2881× edge in sword slash. The face and eyes follow the shared head bone; independent eye tracking was outside this fitting probe.

The shared photographer captured the five mixes at L1 and L2. [Inspection, walk, Near and Middle](head-body-cameras.png)
