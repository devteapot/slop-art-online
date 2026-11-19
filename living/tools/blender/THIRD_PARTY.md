# Third-party material and the character generator

What the character generator (`person.py`, `head_form.py`, `head_mesh.py`, `face_paint.py`, `hair.py`, `person_params.py`) starts from, and under what licence. Checked 2026-11-11, again for pass 2 (`char-3`) the same day, and for the reference study (`ref-1`, below).

## Included in the generator: nothing

Every mesh, weight, colour and texture of a generated person is computed by the scripts in this directory. No third-party mesh, texture, morph target or code is in the repository or in a generated file. That holds for pass 2: the hair's locks are walked and built by `hair.py`, its strand texture is painted by `hair.paint_strands`, and the iris by `face_paint.paint_iris`.

## Studied, not copied: the VRoid samples

The two look-dev controls, `lookdev/vroid-Sendagaya_Shino.glb` and `lookdev/vroid-Vivi.glb`, were inspected to learn how VRoid characters get their look. `living/tools/lookdev_assets.sh` downloads them; they are git-ignored.

- **Licence:** each file's own VRM metadata says `"licenseName": "CC0"`, `"commercialUssageName": "Allow"`, `"allowedUserName": "Everyone"` (read from the files on 2026-11-11).
- **What was taken:** the method only. The face is a mask with real eye openings. The eye is a surface set back behind the lids, with painted layers. Lashes, lid lines and brows are separate pieces standing off the skin. The mouth is a real slit with an inside. Expressions are morph targets named `Fcl_…`. `docs/CHARACTERS.md` records the findings.
- **What was taken in pass 2:** again the method only, read from the file's structure (primitive counts, vertex counts per lock, UV ranges, material settings, image sizes and their mean values by row) and from looking at its hair and eye pictures:
  - hair as about fifty broad locks, each a front and a back surface a few vertices across, mapped root to tip onto one tall grey strand texture that is darker at the root and the tip, over a scalp painted with the same strands;
  - the highlight as a band across the locks broken into teeth;
  - long locks hung from chains of spring bones with colliders on the head and body;
  - the eye as a white set back behind the lids, an iris layer and a highlight layer over it, turned by one bone an eye (`J_Adj_L_FaceEye`, `J_Adj_R_FaceEye`);
  - the iris drawn with a dark rim, a shaded top, a warm lit crescent below and a cool arc above;
  - the face's proportions, measured on the mesh (where the eyes sit on the head, the eye opening's height over its width, the head's width over its height), which set `person_params.STYLE`.
- **What was not taken:** no vertex, triangle, UV layout or texel, in either pass. The generator's topology is its own (a cube-sphere on a parametric form, cut and stitched by script; locks walked over that form), and its textures are painted by `face_paint.py` and `hair.py`. The reference's textures were opened only to look at and to take row averages from; none was saved into the repository or used as a source for ours.
- The generator writes VRoid's material-name tags, bone names (the `J_Bip_*` skeleton, the two eye bones, `J_Sec_Hair*` for spring chains) and morph-target names, and a VRM 0.x block (humanoid, look-at, spring bones), because the game and `animate.py` recognise characters by them. Names and a file format are an interface, not content.

## Taken apart for the reference study (`ref-1`), and not used as a base

On 2026-11-11 both VRoid files were taken apart in full: mesh, topology, UVs, every morph target, weights, materials and textures. The tools are in `living/tools/characters/reference/`, and the findings are in `docs/CHARACTER_REFERENCE.md`. The tools read the files from `living/game/assets/lookdev/` into `.local/ref/src/` (git-ignored) with `python3 -I`. They write measurements and figures to `.local/ref/` and copy nothing of the files into the repository.

- **Each file's own VRM `meta`** (Shino; Vivi's is identical apart from the title):
  - `"title": "Sendagaya Shino"`
  - `"author": ""`, `"contactInformation": ""`, `"reference": ""`, `"version": ""`
  - `"licenseName": "CC0"`
  - `"allowedUserName": "Everyone"`
  - `"commercialUssageName": "Allow"`, `"violentUssageName": "Allow"`, `"sexualUssageName": "Allow"`
  - `"otherPermissionUrl": ""`, `"otherLicenseUrl": ""`
  - exporter `"VRoidStudio-0.8.1"`
  - VRM 0.x has no separate modification or redistribution fields; they follow from `licenseName`.
- **The publisher's terms.** pixiv's help, guidelines and hub pages and OpenGameArt refused automated reads (HTTP 403), so this is from search extracts and from mirrors that reproduce the text.
  - pixiv's help article on sample models has a section "CC0 license models": "The CC license* for these models is CC0. This model can be edited and used freely. Copyright is waived, and there is no particular limit when using them."
  - A Booth redistributor ("全モデルはCC0です。") and an OpenGameArt re-upload list Shino among those models, citing pixiv's per-model page `vroid.pixiv.help/hc/ja/articles/360013482714`, which could not be opened.
  - No source names **Vivi** as a CC0 sample. It appears only in the `madjin/vrm-samples` mirror, which has no licence of its own.
  - pixiv's VRoid Studio guidelines: "all content provided by pixiv, including the base models when creating a new avatar, is not CC0", and "even when using a sample model or included textures, please refer to the sample model's conditions of use".
  - CC0 does not cover trademarks (legal code 4(a)): the names VRoid, pixiv and Sendagaya Shino are not to be used in the game.
- **What the study found that bears on this.** Shino and Vivi share one face template: identical triangles and UVs over 2,339 vertices, differing only in positions. So the face mesh is VRoid's own base template, set by sliders. Its CC0 status rests on the sample's own release.
- **Verdict:**
  - Shino is very probably CC0, but the official page that would settle it was not read.
  - Vivi is unverified.
  - In doubt, so **no VRoid file, mesh, connectivity, UV layout, morph target or texture is committed or used as a source for the generator.** Both files stay git-ignored, as look-dev controls and as a measured target in `.local/`.
- **Decision:** the generator's next head (`docs/CHARACTER_REFERENCE.md` §6) is to be built by our own script: a cage of planes with landmarks, subdivided by script. Our form is fitted until its measured sections match the reference's. The loop pattern round the eyes and mouth (rings of about 24 and 32 vertices) is a modelling technique and is reused as such, not copied from the file.
- **To reopen it:** someone opens pixiv's page for Shino in a browser and records what it says here. Starting from Shino's face as a base mesh would then be allowed, and §5 of the reference document weighs it.
- Renders of the models, sheets of their textures and the measurement dumps are kept with the study's figures in `.local/ref-1.tar.gz`, outside the repository.

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

The motion clips are the project's existing Kimodo library (`living/tools/kimodo/`, `clips.json`); neither pass generated any or changed anything there. No online or paid generation service was used in either pass.
