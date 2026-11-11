# Third-party material and the character generator

What the character generator (`person.py`, `head_form.py`, `head_mesh.py`, `face_paint.py`, `person_params.py`) starts from, and under what licence. Checked 2026-11-11.

## Included in the generator: nothing

Every mesh, weight, colour and texture of a generated person is computed by the scripts in this directory. No third-party mesh, texture, morph target or code is in the repository or in a generated file.

## Studied, not copied: the VRoid samples

The two look-dev controls, `lookdev/vroid-Sendagaya_Shino.glb` and `lookdev/vroid-Vivi.glb`, were inspected to learn how VRoid characters get their look. `living/tools/lookdev_assets.sh` downloads them; they are git-ignored.

- **Licence:** each file's own VRM metadata says `"licenseName": "CC0"`, `"commercialUssageName": "Allow"`, `"allowedUserName": "Everyone"` (read from the files on 2026-11-11).
- **What was taken:** the method only. The face is a mask with real eye openings. The eye is a surface set back behind the lids, with painted layers. Lashes, lid lines and brows are separate pieces standing off the skin. The mouth is a real slit with an inside. Expressions are morph targets named `Fcl_…`. `docs/CHARACTERS.md` records the findings.
- **What was not taken:** no vertex, triangle, UV layout or texel. The generator's topology is its own (a cube-sphere on a parametric form, cut and stitched by script), and its textures are painted by `face_paint.py`.
- The generator writes VRoid's material-name tags, bone names and morph-target names, because the game and `animate.py` recognise characters by them. Names are an interface, not content.

## Checked and not used: MakeHuman and MPFB2

The task suggested starting from an openly licensed base such as MakeHuman's.

- **Licence, verified.** MakeHuman's `LICENSE.md` (github.com/makehumancommunity/makehuman, branch `master`): "The MakeHuman source (as defined per the above) is released under AGPL." and, of the assets ("The base mesh and proxies", "Targets and modifiers", "Textures", "Clothes (any MHCLO-based asset)", "Poses and expressions"): "These assets have been released under CC0 1.0 Universal." MPFB2's `LICENSE.md` (github.com/makehumancommunity/mpfb2): "MPFB uses the same license setup as MakeHuman, but with GPLv3 as source code license rather than AGPL", and its assets are likewise "released under CC0 1.0 Universal". Both add that third-party assets from their asset repositories carry their own licences.
- So the base mesh and its targets could be used here with no obligation, provided we wrote our own loader and took none of their code.
- **Why it was not used in this pass.** Their head is realistic: small eyes in true sockets with eyeball meshes, a modelled nose and lips. The game's look is drawn (`docs/GAME_BRIEF.md`, art direction). Turning that head into this style means replacing its eyes, lids, brows and mouth treatment, which is the work this pass did anyway on a form whose proportions we set directly.
- **Where it may help later:** hands (ours are tubes), ears, and the unclothed body under future outfits. Nothing was downloaded except the two licence files, kept outside the repository in `.local/third-party/makehuman-licence/`.

## Tools the pipeline runs

These are run, not redistributed; their licences put no terms on what they produce.

| Tool | Use | Licence |
|---|---|---|
| Blender 5.2 | Builds and exports the models (`blender -b -P`) | GPL (the program); output is ours |
| numpy | Form, mesh and texture arithmetic | BSD-3-Clause |
| Pillow | Contact sheets in `living/tools/characters/` | MIT-CMU (HPND) |
| ffmpeg | Clips on the check pages | LGPL/GPL (the program) |

The motion clips are the project's existing Kimodo library (`living/tools/kimodo/`, `clips.json`); this pass generated none and changed nothing there.
