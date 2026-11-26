# B1 · Stage 1 fitting master

[Judging sheet](contact-sheet.png) · [Editable Blender scene](base.blend) · [Game model](own-b1-base.glb) · [Measured rig and deformation](rig-check.json)

The first-round subject is a 1.65 m young woman in a plain jersey, shorts and socks, with Cora's head, swept fringe and plait. Her body, feet and hands were built for this round. The man, elder, child, identity morphs and detachable wardrobe await the foundation decision.

## Surface and rig

The editable body is one connected cage of 4,459 vertices and 4,440 faces. It has 4,436 quads and four triangles on the soles. Its only open boundary is a 40-edge loop tucked beneath the separate neck. Both shoulders branch out of openings in the chest. Both thighs meet at a curved perineal strip. The finger webs and thumb openings share edges with the palm. Each finger has supporting rings either side of its articulated joints. The toe joints roll the front of each sock. One subdivision level precedes skinning.

The genre reference for the face is the project's own Cora drawing. The calibrated face, neck, eye carriers, shadow and plait come from [the char-live-3 master](../../char-live-3/ink-batch-2/README.md). Hair and face are separate skinned meshes. The underlayer uses material regions on the same body. The shirt, shorts, exposed skin, rib knit and nails each have an editable material. The face has the inherited 15 expression targets.

| Game file | Measured |
|---|---|
| Triangles | 68,654, including 35,512 on the connected body |
| Materials | 15 used |
| Rig | 82 skin joints. All 52 animated target names in the 84-clip library map directly by name and parent. |
| Embedded images | Face atlas 1024², iris 192², tint 512² |
| Sidecar images | Face shadow 512², hair mask 2048², eye ink 2048² |
| Embedded motion | Idle, walk, run, talk, seated idle and ground sit. The game selects the shared library by the shipped file's `own-` prefix when installed. |

## Verification and limitations

The shared photographer captured 13 animated stills and three bind views. The game reported 84 available clips, 15 materials and 68,654 triangles. The sheet includes six phases of the walk. Full resolution stills on the dev-box are under `.local/b1/final-shoot/own-b1-base/` in this worktree.

A numerical skinning check sampled four phases each of shared idle, walk, run and ground sit. The bind-pose known answer reproduced body positions within 0.000001 m. The first crotch saddle produced a 33.8× maximum edge stretch at the first ground-sit sample. A shallower saddle, lower first thigh section and weights shared across both hips reduced it to 3.52×. Early bind shots also exposed squared shoulder caps, gaps at the collar and a transverse crease where Cora's original finger tubes entered the palm. The submitted cage lowers the caps, returns the collar edge inside the neck, and replaces both hands.

Deep flexion still pinches the groin. At the first ground-sit sample the worst individual edge compressed to 0.091 of rest length. The calves and socked feet have little surface definition, and the rear braid reads more clearly at play distance than the body planes. Hand articulation has a connected mesh and finger weights, but individual grips, extreme shoulder reach and ground sitting still need visual review. Only idle, walk and bind were photographed.

For 64 residents the proposed next stage is a family of coordinated body, joint-position and head morphs on this topology, followed by fitted garment layers that use the same deltas. The available variation today is face expression, hair as its own mesh and material colours. The 64-person population, age and sex morphs, and crowd cost have not been demonstrated.

## Rebuild

Use a fresh output folder. From the worktree root on the dev-box:

```bash
export PATH="$HOME/.local/share/slop-tools/build-bin:$PATH" JOBS=3
export OCIO="$PWD/docs/char-live-1/standard.ocio"
export B1_OUT="$PWD/.local/b1-rebuild"
blender -b --factory-startup --python-exit-code 1 -P docs/char-bakeoff/B1/base.py
python3 docs/char-bakeoff/B1/check.py "$B1_OUT/own-b1-base.glb" living/game/assets/lookdev/anim/own-clips.glb
```

For body edits saved in the master, open that scene with Blender and run [the body exporter](export_body.py). It bakes subdivision on the export copy and takes calibrated head and hair data from the prior char-live GLB. Both a fresh construction and export from the saved master reproduced SHA-256 `e62fd8027fae1fdbe1acfbef11f9bdc89ab7344dc921f167cd7450e29706270f`.

```bash
blender -b docs/char-bakeoff/B1/base.blend --python-exit-code 1 -P docs/char-bakeoff/B1/export_body.py
mkdir -p living/game/assets/view/b1
cp "$B1_OUT"/own-b1-base.* living/game/assets/view/b1/
CARGO_BUILD_JOBS=8 CARGO_TARGET_DIR="$PWD/.local/target" \
  "$HOME/.local/state/bakeoff/shoot.sh" .local/b1-photos view/b1/own-b1-base.glb
```

## Asset provenance

All new geometry and material definitions were authored in this repository. The inherited head, neck, hair, rig, six embedded game clips and maps come from the project's char-live-3 hand-built Cora package. No external meshes, textures, store assets or reference images were imported. The owner's images are absent from the deliverables.
