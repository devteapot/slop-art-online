# Character research: shape spaces, anime construction and crowd cost

A survey for the character generator ([CHARACTERS.md](CHARACTERS.md); `living/tools/blender/person.py` and its modules). It asks what the best existing head and body models, character creators and anime productions do that we do not, and what we would change. Research of 2026-11-11, branch `res-1`. Documentation only: nothing was downloaded into the repository and no third-party code was run.

**Why now.** The owner's verdict on pass 2:

> "This is definitely progress. But yeah, we are still lacking, I think, depth and probably in the shape, how it is structured internally. What are the points that you can tweak to get different shapes that still make sense, right?"

Two separate problems follow from it, plus a third from the crowd measurements:

1. **Structure.** Our head is one smooth form with features placed on it. `head_form.py` lofts superellipse sections through four curves and adds the nose, brow ridge, eye hollows, cheeks and lips as bumps on the front. Nothing underneath decides where a feature may go. A skull, the eye sockets, the cheekbones and the jaw are not part of the model.
2. **Parameter space.** Our 34 face values (`face.*`, CHARACTERS.md) each move one feature about one average for the person's sex and age. They are drawn independently. Nothing ties a wide jaw to a heavier brow or a long face to a longer nose, so the space holds many faces no head-builder would make.
3. **Crowd cost.** 64 different generated people cost 27 ms a frame and 5.4 GB of process memory against 18.9 ms and 2.3 GB for 64 copies of one person. Materials, not triangles, make the difference: 212 materials on people in view against 23 ([crowd cost](CHARACTERS.md#crowd-cost)).

"Depth" can mean two things here, and this note treats both. One is form: how far a face really goes back from the nose to the ear, and where its planes turn. The other is how depth is drawn in toon shading: shadow shapes, lines at overhangs, and eyes and hair that read as layered. The second does not follow from the first. A toon face shows depth only through the shadow shapes and lines it is given, and anime productions design both by hand (§3).

Another worker (`ref-1`) is taking the VRoid reference files apart in `docs/CHARACTER_REFERENCE.md`. This note does not repeat that. Where it needs a fact about the reference it uses CHARACTERS.md's [what was learnt from VRoid](CHARACTERS.md#what-was-learnt-from-vroid) and points to that file.

**How to read the marks.** Claims are cited. **[unverified]** marks a claim taken from a secondary source or from memory that this note did not confirm against a primary source. **[source]** marks a claim read in the pinned crate source on this machine (`~/.cargo/registry/src/*/bevy_*-0.20.1`). Licence notes are summaries of each licence's own page, not legal advice.

## Contents

1. [Parametric head and body models](#1-parametric-head-and-body-models)
2. [Open character generators and how their sliders stay valid](#2-open-character-generators-and-how-their-sliders-stay-valid)
3. [How anime-style characters are built in production](#3-how-anime-style-characters-are-built-in-production)
4. [How pipelines keep crowds cheap, and what Bevy 0.20.1 gives us](#4-how-pipelines-keep-crowds-cheap-and-what-bevy-0201-gives-us)
5. [Findings into changes, ranked](#5-findings-into-changes-ranked)
6. [Licences](#6-licences)
7. [What could not be verified](#7-what-could-not-be-verified)
8. [Sources](#8-sources)

## 1. Parametric head and body models

There are two families. **Statistical** models learn a mean shape and its main directions of variation (principal components) from many registered scans, so each parameter moves the whole shape the way real heads co-vary. **Morph-target** systems sum offsets that artists sculpted by hand, one target per control, and use rules to keep combinations sound. Both are a template mesh plus a weighted sum of offsets. They differ in where the offsets come from and in what keeps a combination valid.

### SMPL and SMPL-X (Max Planck Institute for Intelligent Systems)

- **What the parameters mean.** A body is a template mesh plus identity blend shapes, which are principal components learned from thousands of scans. The site offers "up to 300 shape components" ([SMPL](https://smpl.is.tue.mpg.de/)). Pose is joint rotations. Pose-dependent corrective blend shapes are "a linear function of the elements of the pose rotation matrices". The joints come from a regressor applied to the shaped mesh, so the skeleton follows the body's shape. SMPL-X adds hands and a face.
- **How it keeps shapes valid.** Shape is a low-dimensional linear space fitted to real bodies. Each component is ordered by how much variance it explains, and values are kept within a few standard deviations. Correctives fix how joints deform, so a bent elbow keeps its volume.
- **Licence.** Non-commercial scientific research only. "Any other use, in particular any use for commercial purposes, is prohibited" ([SMPL model licence](https://smpl.is.tue.mpg.de/modellicense.html); [SMPL-X model licence](https://smpl-x.is.tue.mpg.de/modellicense.html)). Commercial licences have been sold through Meshcapade, but Meshcapade's own page now says its online platforms shut down and that it "is now part of Epic Games" ([Meshcapade](https://meshcapade.com/)). The current commercial route is unclear **[unverified]**.
- **Verdict: learn from it, do not use it.** Two lessons carry over. Joint positions should be computed from the shaped body, not set beside it. Joints that bend far, such as shoulders, elbows, hips and knees, want correctives. Our body is lofted cages with written weights (CHARACTERS.md, how a person is built), so both apply when bodies and clothes get their pass.

### FLAME (Max Planck Institute for Intelligent Systems)

- **What the parameters mean.** A head model with "a linear shape space trained from 3800 scans of human heads": 300 shape components and 100 expression components, "an articulated jaw, neck, and eyeballs", pose-dependent correctives and global expression blend shapes ([FLAME](https://flame.is.tue.mpg.de/)). The mesh has about 5,000 vertices **[unverified: from the paper, not on the page]**.
- **How it keeps shapes valid.** As SMPL: a learned linear shape space. Expression is separate from identity, so one smile works on every head.
- **Licence.** FLAME 2017, 2019, 2020 and 2023 are under an academic, non-commercial licence ([FLAME model licence](https://flame.is.tue.mpg.de/modellicense.html)). **FLAME 2023 Open** is under Creative Commons Attribution 4.0, which grants "the right to share and adapt the model for any purpose, including commercial use" with attribution (same page). The site's news dates the release "11/25", which reads as November 2025, and says its expression parameters differ from FLAME 2023's (conversion code is provided).
- **Verdict: learn from it, and possibly use FLAME 2023 Open as data.** It is the one permissively licensed statistical head model found. It is realistic, so its mean head is not our drawn head. What it could give us is **covariance**: how jaw width, cheekbone width, brow height, nose length and face length vary *together* in real heads. Measured at our landmarks, that would turn our 34 independent values into a few correlated directions (§5, change 3). Downloading it may need a registration on the FLAME site **[unverified]**, and it would bring a CC BY credit obligation.

### Basel Face Model (University of Basel)

- **What the parameters mean.** A PCA face model, with shape, expression and colour each a mean plus basis vectors. A secondary source gives 199 shape and 100 expression vectors ([Photo-realistic facial details, arXiv 1903.10873](https://arxiv.org/pdf/1903.10873)), and another describes its shape space as built from 200 scanned faces ([Jozwik et al., PNAS 2022](https://kriegeskortelab.zuckermaninstitute.columbia.edu/sites/default/files/content/JozwikOKeeffeStorrs_etal_2022_PNAS.pdf)) **[unverified against the model's own paper]**.
- **How it keeps shapes valid.** The coefficients are modelled as a standard normal distribution. The PNAS study found that this Gaussian does not match which faces people judge natural, and built a separate model of perceived naturalness (same source). The lesson for us: a statistical prior bounds a space, but whether a face looks right still has to be judged by eye. Our board and check pages are that judge.
- **Licence.** Non-commercial research only: "The license granted is for internal, non-commercial research, evaluation or testing purposes only", and "You are not allowed to sublicense or distribute the DATA in whole or in part to any third party" ([BFM 2019](https://faces.dmi.unibas.ch/bfm/bfm2019.html); [BFM 2017](https://faces.dmi.unibas.ch/bfm/bfm2017.html)). Commercial questions go to Unitectra.
- **Verdict: neither use nor copy. The one lesson** (a Gaussian prior is not a plausibility test) costs nothing to take.

### MakeHuman and MPFB2 (morph targets)

- **What the parameters mean.** A target is "conceptually a blend shape (a.k.a 'shape key')": per-vertex offsets ([MPFB targets](https://static.makehumancommunity.org/mpfb/docs/assets/targets.html)). There are two layers:
  - **macro modifiers:** gender, age, muscle, weight, height, proportions and a three-way ethnicity blend;
  - **detail modifiers:** per-region targets such as `nose-scale-depth-incr|decr`.
  MakeHuman 1 has "about 100 modifiers" ([technical notes](https://static.makehumancommunity.org/oldsite/uncategorized/technical_notes_on_makehuman.html)).
- **How it keeps shapes valid.** Section 2 covers this: designed targets for each direction, macro targets blended as products, detail targets conditioned on the macro variables, and symmetric pairs.
- **Licence.** Code is AGPL (MakeHuman) or GPLv3 (MPFB2). The base mesh, targets, textures, clothes, poses and expressions are CC0 1.0 ([MakeHuman LICENSE.md](https://github.com/makehumancommunity/makehuman/blob/master/LICENSE.md); [MPFB2 LICENSE.md](https://github.com/makehumancommunity/mpfb2/blob/master/LICENSE.md); [MPFB2 LICENSE.ASSETS.md](https://github.com/makehumancommunity/mpfb2/blob/master/LICENSE.ASSETS.md)). MPFB's FAQ says models may be used in a closed-source game ([FAQ](https://static.makehumancommunity.org/mpfb/faq/use_in_closed_source.html)) and that building another character generator from the base mesh, targets and system assets is "perfectly fine" ([FAQ](https://static.makehumancommunity.org/mpfb/faq/build_other_chargen.html)). The community site lists "Community services shut down" (2026-10-21) and a move to Discord (2026-11-08) **[unverified: titles only]**. The GitHub repositories are the stable copy.
- **Verdict: learn from it now; use its CC0 assets for hands, ears and the unclothed body later.** [THIRD_PARTY.md](../living/tools/blender/THIRD_PARTY.md) already records why its realistic head was not used, and that stays true. Its *rules* (§2) are what our face values lack.

### Mixamo Fuse (Adobe)

- **What it was.** A parts-and-sliders body builder from Mixamo. Adobe ended development in 2019 and support on 13 September 2020 ([Adobe Fuse FAQ](https://helpx.adobe.com/fuse/faq.html), via search; the page returned 403 to fetching). Adobe's Mixamo FAQ also returned 403.
- **Licence.** Not determined. The commercial terms for Fuse output are not settled in the sources found ([Adobe community thread](https://community.adobe.com/t5/mixamo-discussions/fuse-cc-beta-what-is-the-license-and-can-i-use-still-model-with-commercial-use/m-p/14945490)). [GAME_BRIEF.md](GAME_BRIEF.md) already avoids Mixamo.
- **Verdict: neither.** It is discontinued and its terms are unclear. How it worked (picking a head, torso, arms and legs from scanned parts, then morphing) is from memory **[unverified]**.

### Character Creator (Reallusion) and Daz Genesis (Daz 3D)

- **What the parameters mean.**
  - *Character Creator* organises head morphs in six levels: Contour, Face, Eyes, Nose, Mouth and Ears. Each level has sub-nodes, and "The Headshot Morph 1000+ contains sliders from full head and face sculpting to individual features" ([Six Levels of Morph Detail](https://manual.reallusion.com/Headshot_for_CC/ENU/1.0/ID_Six_Levels_of_Morph_Detail.htm)). Its expression profiles run from 75 to 262 sliders by region, paired `_L`/`_R` ([facial profile sliders](https://manual.reallusion.com/Character-Creator-5/Content/ENU/5.0/05-HD-Character/Slider-Table-for-Facial-Profiles.htm)). Bone adjustments sit beside mesh morphs and can be saved into custom sliders ([creating head and body sliders](https://manual.reallusion.com/Character-Creator-4/Content/ENU/4.0/06_Customizing_Morphing_Sliders/Creating-Head-and-Body-Morphing-Sliders.htm)).
  - *Daz Genesis* sums shape morphs, and joint-corrective morphs are triggered by joint rotation through ERC links. Genesis 9 calls them CBS. These details come from forum answers, not official documentation **[unverified]** ([Daz forum](https://www.daz3d.com/forums/discussion/comment/8361691)).
- **How they keep shapes valid.** Hierarchy (whole head, then region, then feature), left/right pairing, correctives driven by pose, and large libraries of sculpted targets.
- **Licence.**
  - *Character Creator:* Reallusion's licence pages returned 404 to fetching. Its content policy page says the Standard License allows export "to any external software or game engine" ([content policy](https://www.reallusion.com/license/content.html), via search). Reallusion forum staff say an in-game character creator using Reallusion content needs an Enterprise licence issued case by case ([forum](https://forum.reallusion.com/PrintTopic550716.aspx)) **[unverified: forum, not the licence text]**.
  - *Daz:* games need an Interactive License, available only on products that offer one ([Interactive License](https://www.daz3d.com/interactive-license-info)). The EULA's Interactive addendum bars selling the content in-game "as a separately-purchased commodity or upgrade", limits app distribution to companies with "annual revenues less than $1,000,000 USD" without written consent, and requires that derived 3D works be "designed to require or encourage" the Daz store ([Daz EULA](https://www.daz3d.com/eula)).
- **Verdict: learn from them only.** Their libraries are licensed per product and both restrict exactly our case: a generator inside the game. The hierarchy of six levels, from contour down to the ears, is the right shape for our parameter table.

### What this section adds up to

| Model | Parameters | Validity from | Licence (own page) | Use / learn / neither |
|---|---|---|---|---|
| SMPL / SMPL-X | PCA shape (up to 300), joint rotations, pose correctives, joints regressed from shape | learned space; correctives | non-commercial research; commercial via Max Planck (Meshcapade route now unclear) | learn: joints from shape, correctives |
| FLAME | 300 shape, 100 expression; jaw, neck, eyeballs | learned space; identity apart from expression | 2017–2023: non-commercial. **2023 Open: CC BY 4.0** | learn, and possibly use 2023 Open's covariance |
| Basel Face Model | PCA shape, expression, colour | Gaussian prior (not a naturalness test) | non-commercial, no distribution | neither (one lesson) |
| MakeHuman / MPFB2 | ~100 modifiers over designed targets; macro and detail layers | designed targets; product blends; detail conditioned on macro; symmetry | code AGPL / GPLv3; **assets CC0** | learn now; use assets later (hands, ears, body) |
| Mixamo Fuse | parts and sliders **[unverified]** | not established | not determined; discontinued 2020 | neither |
| Character Creator | 6-level head hierarchy, 1000+ morphs, bones | hierarchy, `_L`/`_R`, sculpted libraries | export allowed; in-game creator needs Enterprise **[unverified]** | learn the hierarchy |
| Daz Genesis | summed morphs, corrective morphs on joints | correctives | Interactive License for games; restrictions | learn only |

## 2. Open character generators and how their sliders stay valid

What makes a slider produce a valid person, gathered from MakeHuman, MPFB2, Character Creator, Blue Protocol and VRoid, and set against what ours do.

**1. Each direction is its own designed shape.** A MakeHuman dual slider runs -1 to 1 over two targets, `incr` and `decr`, not one offset and its negative ([MakeHuman 2 modelling.json](https://makehuman-2.github.io/custom-toc/nerds/conf_modelling)). A small nose is sculpted as a small nose, not as a large nose run backwards.
*Ours:* most face values are one linear coefficient each way (`head_form.py`: for example `0.075 * g("face_width")`). *Change:* allow an asymmetric response per value. Cheap.

**2. Macro variables blend as products.** MakeHuman 2's `macro.json` gives each macro variable breakpoints on its slider. Age's are 0, 0.1875, 0.5 and 1.0 for baby, child, young and old, so they are not evenly spaced. The weight of each combined target (for example "female-young-averagemuscle-averageweight") is the *product* of its components' weights: gender × age × muscle × weight is 72 targets ([conf_macro](https://makehuman-2.github.io/custom-toc/nerds/conf_macro)). The page's gender pseudocode contradicts its own worked example, so the exact curves are uncertain **[unverified]**. The point is that the body for "old, heavy, male" is a *designed* body, not the sum of separate "old", "heavy" and "male" offsets.
*Ours:* sex, age, child and elder already shift the averages inside `head_form.Head` as sums of terms. *Change:* design key heads at the corners (child, young adult and elder, by sex) and blend between them.

**3. Detail targets depend on the macro state.** A MakeHuman detail target can declare `macro_influence` (ethnicity, age, proportion, height, gender), so the same slider applies a different target on a child than on an adult (conf_modelling).
*Ours:* partly done (each coefficient carries `c`, `e` and `s` terms). This is the right idea, done by hand.

**4. Symmetry is a pairing, not a constraint.** Left and right targets are paired (`rsym`/`lsym`), and symmetry mode moves both together (conf_modelling; [MPFB modeling](https://static.makehumancommunity.org/mpfb/docs/characters/modeling.html)). Character Creator pairs `_L`/`_R`.
*Ours:* the head is exactly symmetric in X (`head_form.py`'s docstring). Real faces and many drawn faces carry a slight asymmetry. *Change:* a small, bounded asymmetry value per person, mostly for elders and weathered faces. Cheap.

**5. A hierarchy of regions with falloff.** Character Creator works from contour to face, eyes, nose, mouth and ears. Blue Protocol's face rig has five parts (brows, eyes, nose, mouth and outline), "each driven by bones" ([Game*Spark on CEDEC 2021](https://www.gamespark.jp/article/2021/08/27/111420.html)).
*Ours:* the features are bumps with Gaussian falloff on one front surface, but no level above them. The jaw outline and the eye placement are separate curves with no shared frame.

**6. Pick a type first, then vary within it.** This is the most important rule for an anime-style creator. Blue Protocol's creator picks sex, then **one of three face types**, then a body type tied to that face type. Height and build are sliders (Game*Spark). CGWORLD reports three base types by sex and build, with height changing the head's proportion and not only scale ([CGWORLD on CEDEC 2020](https://cgworld.jp/feature/202011-cedec2020-bluep.html)). A face type is a designed whole, and sliders move parts within it.
*Ours:* every person is one average plus 34 independent offsets, and `STYLE["toward"]` moves everyone toward one reference.

**7. Bones for identity in a crowd.** Blue Protocol rejected blend shapes for its face parts because "the cost grows with vertex count" (translation), and bones are easier to copy to NPCs. Its face LOD swaps to a shared static face at a distance (Game*Spark).
*Ours:* identity is baked into each file's geometry, which costs nothing per frame but makes every person a distinct mesh and material set (§4).

**VRoid's sliders.** VRoid Studio's help pages and guidelines could not be fetched (403), so its slider list is not documented here **[unverified]**. The exported file carries only the sliders' result, and `ref-1`'s `docs/CHARACTER_REFERENCE.md` takes that file apart. The guidelines' rule on in-game creators is in §6.

**Ready Player Me** shut down its public services on 31 January 2026 after Netflix acquired it in December 2025 ([avatarsdk.com, August 2026](https://avatarsdk.com/blog/2026/08/31/avatar-platforms-2026-whos-alive-whos-gone/); [genies.com](https://genies.com/blog/ready-player-me-shutdown)) **[unverified: secondary sources; readyplayer.me no longer resolves]**. It is not a candidate. Its approach of one base body with fitted modular outfits is from memory **[unverified]**.

## 3. How anime-style characters are built in production

The common thread: anime productions do not let a lit form decide where shadow falls. They author the shadow shapes and the lines, through edited normals, threshold maps, vertex-colour channels and per-vertex line widths, on a mesh built to carry that data. The "depth" the owner misses on our faces is mostly this authored layer.

### Face topology and form

- **Anime faces are few planes, not a sculpted surface.** VRoid's face is a mask of 1,342 triangles with nearly flat colour (CHARACTERS.md). Guilty Gear Xrd's GDC talk stores shading data in vertex normals, vertex colours and UVs instead of textures, because vertex attributes "are linearly interpolated between vertices", which is resolution independent ([GDC Vault](https://gdcvault.com/play/1022031/GuiltyGearXrd-s-Art-Style-The); [handout](https://www.ggxrd.com/Motomura_Junya_GuiltyGearXrd.pdf), which refused the connection; content via search summaries **[unverified in the handout itself]**). Topology there serves the shading data: edges sit where a shadow edge or a line should fall.
- **Edge loops** follow the orbit round each eye, the mouth, the jawline and the brow ridge ([topology notes](https://michael-vl.github.io/learning-wiki/blender/topology/)). An artist on Blender Artists notes that anime topology differs from realistic topology ([thread](https://blenderartists.org/t/possible-anime-face-topology-reference/554520)). No authoritative anime topology reference was found **[unverified]**.
- **Planes of the head.** The Asaro head simplifies a head into flat planes, to show how light falls on them ([James Gurney](https://jamesgurney.substack.com/p/plane-heads)). Its two sides show a rounder or younger face and a thinner or older one. Anime shading is close to this: a front plane, a side plane where the cheek turns, a plane under the nose and under the lower lip, the underside of the jaw. *Ours:* `face_normals.py` flattens the face's normals toward an **ellipsoid**, and its threshold map comes from the ellipsoid's facing. So the light sweeps across a ball. That is exactly the "smooth form with features on it".

### Edited normals and normal transfer

- **Blue Protocol** tunes artist-set normals "so lighting produces anime-like shadows, such as the triangular cheek shadow" (translation; [GameBusiness.jp on CEDEC 2021](https://www.gamebusiness.jp/article/2021/09/13/19051.html)). It uses no character normal maps, because compression noise shows at the shadow edges (CGWORLD). Points and sky light ignore normals so they add no relief (GameBusiness.jp).
- **Guilty Gear Xrd** hand-edits face normals and uses a vertex-colour channel as an offset on the shading threshold, so artists can darken areas to suggest occlusion (GDC 2015; via search summaries **[unverified in the handout]**).
- **Normal transfer** in Blender: shape a simple proxy, then copy its normals onto the face with the Data Transfer modifier ([Unreal forum thread](https://forums.unrealengine.com/t/normal-editing-and-3d-modeling-discussion/150158); [Polycount](https://polycount.com/discussion/comment/2666647)). We already do the computed version of this from an ellipsoid. The change is to make the proxy a *designed planar head* built from the same landmarks as the face (§5, change 2).

### Face shadow maps (SDF or threshold maps)

- **Status of the evidence.** HoYoverse has not published its character shading. Official talks cover colour grading ([Unity Dojo 2021](https://www.docswell.com/s/UnityJapan/KWRPQ5-210617-unity-dojo20211mihoyozhenzhongyi)). What is known is reverse-engineered **[unverified as HoYoverse's method]**. The face map stores, per texel, the light angle up to which it stays lit, for light from 0 to 180° on one side ([NoiRC256 URP shaders](https://github.com/NoiRC256/URPSimpleGenshinShaders); [HoyoToon wiki](https://github.com/Melioli/HoyoToon/wiki/Using-the-Genshin-Shader)).
- **How such maps are authored** (community guides): draw N binary shadow masks, one per light angle (one guide paints nine), convert each to a signed distance field, and interpolate between them into one threshold map ([SDF shadow map guide](https://destiny-fine-0ac.notion.site/SDF-Shadowmap-9527f23116aa42dc89e3c9e17a54ddf3); [Sydian Chen](https://sydianandrewchen.github.io/projects/3-stylized-facial-shadow-workflow); [Eric Hu](https://erichu33.notion.site/Face-Shadow-Map-Creation-Baking-Workflow-d3b8769021e04683a2f2ae4cf16ac810)). The masks are *drawn*: each is the shape an anime artist would give the shadow at that angle, such as the cheek triangle, the shadow beside the nose and the jaw's underside.
- **Hi-Fi Rush's** GDC 2024 talk lists "toon face shadow" among its topics ([GDC Vault](https://gdcvault.com/play/1034330/3D-Toon-Rendering-in-Hi); [80.lv](https://80.lv/articles/the-making-of-hi-fi-rush-s-3d-toon-rendering-style)). Its method was not read **[unverified]**.
- *Ours:* `face_normals.py` already writes an RG threshold map (right and left light) and `toon.wesl` already uses it. Only the *source* of the thresholds is wrong for depth: an ellipsoid's horizontal facing. CHARACTERS.md records that a nose shadow was tried and "read as a blot". A ray-cast nose shadow is a blot. A drawn shadow shape is a designed polygon with a clean edge that grows with the angle. **We can draw these masks by script from the head's landmarks**, at N light angles, and build the threshold map from them as the guides do. That is the anime method, made ours.

### Eyes with depth

- **Parallax iris.** The iris texture is shifted along the view direction in tangent space, as if it sat behind the cornea, without a height map ([Cocos tutorial](https://discuss.cocos2d-x.org/t/tutorial-cocos-creator-practical-and-cost-effective-rendering-character-eyes/54929); [Anime Shading Plus](https://erichu33.github.io/ASPDocs/en/articles/eyes-anime-like-setup-guide.html)). CryEngine and Unity HDRP expose an iris depth ([CryEngine](https://www.cryengine.com/docs/static/engines/cryengine-3/categories/1114113/pages/1048594); [HDRP Eye](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@12.1/manual/master-stack-eye.html)). One commercial anime eye shader notes that parallax must be off for a curved eye shape **[unverified]**.
- **A highlight that follows the view,** separate from the iris texture (Anime Shading Plus: an eye highlight map that rotates with the viewing angle).
- **Layered geometry**, as VRoid has it: a white set back behind the lids, an iris layer and a highlight layer (CHARACTERS.md). We have this since pass 2.
- *Ours:* the geometry layers are there. What is missing is the *drawn* depth: the upper lid's shadow over the top of the iris and white, a second iris colour, and a highlight that stays toward the camera. CHARACTERS.md's gap 4 lists "Close up the reference's iris has two colours, a sparkle and blended lash clumps." A parallax offset and a lid-shadow band are small additions to the eye's kind in `toon.wesl`.

### Hair: cards or locks, and highlights

- **Shifted-tangent highlights.** Scheuermann's model lights hair from the strand tangent (Kajiya-Kay), shifts the tangent along the normal for two highlights (one toward the tip, one toward the root) and breaks the second with a noise texture for sparkle ([SIGGRAPH 2004 sketch](https://history.siggraph.org/wp-content/uploads/2022/12/2004-Talks-Scheuermann_Practical-Real-Time-Hair-Rendering-and-Shading.pdf); [GDC 2004 slides](https://web.engr.oregonstate.edu/~mjb/cs557/Projects/Papers/HairRendering.pdf)).
- **The angel ring.** Unity Toon Shader's Angel Ring "always appears in a fixed position as seen from the camera" and needs a second UV set ([UTS Angel Ring](https://docs.unity3d.com/Packages/com.unity.toonshader@0.13/manual/AngelRing.html)). UTS also has a Shading Grade Map, a greyscale map of how readily each texel goes into shadow, in linear space ([UTS](https://docs.unity3d.com/Packages/com.unity.toonshader@0.15/manual/index.html)).
- **Blue Protocol** sets hair colours by parameter, builds highlights in hand-made node graphs, and draws eyebrow lines in a separate hair pass (GameBusiness.jp).
- *Ours:* the game's ring comes from the normals, with teeth from the hair's UVs (GAME_BRIEF.md, faces and hair). On our hair, smoothed toward a capsule, it reads as "a thin even stripe" (CHARACTERS.md). `hair.py` knows each lock's direction at every step. It can write that as the vertex tangent, and write a per-lock band position and tooth pattern into the strand texture's column or a second UV. The shader then shifts the tangent per lock, Scheuermann's way. A band broken by locks, as the reference has it, then comes from the locks themselves.

### Outlines: inverted hull or post-process

- **Blue Protocol** draws most lines as a post-process from depth, an inner-line ID, normals and painted data. It uses shell geometry only at the jaw, mouth and ears, where the shape overhangs, and on hair (CGWORLD; GameBusiness.jp). Line thickness is a G-buffer channel taken from a second UV channel.
- **Arc System Works** keeps inverted hulls for per-vertex control. Vertex-colour alpha sets the width: 0 none, 0.5 standard, 1 double. Lids and lashes are 0 and valleys about 0.1, so lines do not float. Outline normals are stored separately from lighting normals. Width scales with distance × tan(FOV/2) so it holds when zooming ([ASW toon line control, 2025](https://docswell.com/s/ASW_Academy/5LVY67-GG-Toonline-Eng)). The deck says SEGA introduced the method with *Jet Set Radio* in 2000.
- *Ours:* characters take a shell outline from `bevy_mod_outline` 0.14, and scenery takes post-process edges (GAME_BRIEF.md). `bevy_mod_outline` extrudes along its own `ATTRIBUTE_OUTLINE_NORMAL` when a mesh has one, and has one width for each `OutlineVolume` **[source: `bevy_mod_outline-0.14.0/src/lib.rs`]**. It has no per-vertex width in the version we pin **[source; no such attribute found]**. So:
  - **Outline normals** are possible now: the generator writes smoothed normals into that attribute. They are separate from the lighting normals we flatten, as ASW keeps them.
  - **Per-vertex width** (none on lids, thin on hair, thick under the jaw) needs our own outline shader or a patch.
  - **Lines at overhangs** (chin, jaw, ears, nose tip) are where depth reads in anime. They come from either.

## 4. How pipelines keep crowds cheap, and what Bevy 0.20.1 gives us

### What studios do

| Technique | Source | Point |
|---|---|---|
| Instanced skinning with animation in a texture | [GPU Gems 3, ch. 2](https://developer.nvidia.com/gpugems/GPUGems3/gpugems3_ch02.html) | "we encode all frames of all animations into a texture"; 9,547 characters at about 34 fps in 160 instanced draws (DX10, 8800 GTX); LOD at 20, 60 and 100 radii. Fill-limited at high counts. |
| AI and model level of detail with pooling | [GDC 2015, AC Unity](https://www.gdcvault.com/play/1022141/Massive-Crowd-on-Assassin-s) | "With the limit of 40 real AIs and 120 high resolution models", 10,000 crowd NPCs on screen, swapped invisibly from a pool. |
| Merge a character's parts into one mesh | [Blue Protocol, CEDEC 2021](https://www.gamespark.jp/article/2021/08/27/111420.html); [UE modular characters](https://dev.epicgames.com/documentation/unreal-engine/working-with-modular-characters-in-unreal-engine) | Asynchronous merging when creation finishes took 100 avatars from 30 to 50 fps. Epic rates mesh merge as high setup cost and low render-thread cost. |
| A shared face far away | Blue Protocol (Game*Spark) | Face LOD swaps to a shared static face at higher LOD levels. |
| Share poses across a crowd | [UE Animation Sharing](https://dev.epicgames.com/documentation/unreal-engine/animation-sharing-plugin-in-unreal-engine) | Poses are computed once a state and copied to every member of the bucket, with offsets for variety (via search). |
| Vertex animation textures for far crowds | [UE AnimToTexture (forum)](https://forums.unrealengine.com/t/community-tutorial-animtotexture-plugin-how-to-use-it-to-make-vertex-animation-textures-for-crowds/746648) | City Sample's medium and far pedestrians are static meshes animated in the material **[unverified: no official page]**. |
| Impostors | [shaderbits, octahedral impostors](https://shaderbits.com/blog/octahedral-impostors) | Views baked onto an octahedron. Made for static objects (Fortnite's). The article body could not be read **[unverified]**. Animated people would need a sheet per pose, which costs memory. |

### What Bevy 0.20.1 supports (`living/game/Cargo.toml` pins `bevy = "=0.20.1"`)

Checked in the crate source unless marked.

- **Automatic instancing and batching.** Entities that share a mesh and a material draw instanced. Since 0.16, GPU-driven rendering (multi-draw indirect, a mesh allocator, bindless materials and GPU culling) covers "most 'standard' 3D mesh rendering, including skinned meshes" ([Bevy 0.16](https://bevy.org/news/bevy-0-16/)). The 0.16 platform table lists multi-draw, GPU culling and bindless as unsupported on Direct3D 12, OpenGL, WebGPU and WebGL 2.
- **Skinned and morphed meshes batch where storage buffers exist.** `no_automatic_skin_batching` and `no_automatic_morph_batching` turn batching off only when skins use uniform buffers, which is the WebGL 2 case **[source: `bevy_pbr-0.20.1/src/render/skin.rs:500`, `render/morph.rs:431`]**. 0.19 added "Batched morph targets" ("an almost 2x speedup" in `many_morph_targets`) ([Bevy 0.19](https://bevy.org/news/bevy-0-19/)). Limits are 256 joints a skin (`MAX_JOINTS`) and 256 morph weights a mesh (`MAX_MORPH_WEIGHTS`) **[source]**.
- **Bindless materials.** `#[bindless]` on `AsBindGroup` groups materials into shared bind groups, so materials that differ only by texture can share a batch ([bindless example](https://bevy.org/examples/shaders/shader-material-bindless/)). `StandardMaterial` is bindless **[source: `pbr_material.rs:25`]**. An `ExtendedMaterial` is bindless only when both its base and its extension are **[source: `extended_material.rs:181`]**. Our `ToonExt` has no `#[bindless]` (`living/game/src/style.rs:27`), so **our toon materials are not bindless**, and each person's face, eye and hair textures make a separate bind group and batch. This is inferred from the source and should be confirmed with `LIVING_GAME_PERF=diag`. In 0.20.1 a texture-only bindless material needs `TEXTURE_BINDING_ARRAY`, and one with buffer arrays also needs `BUFFER_BINDING_ARRAY` **[source: `bevy_render_macros-0.20.1/src/as_bind_group.rs:975`]**. Whether the laptop's Metal adapter and the dev-box's Vulkan adapter report it was not checked **[unverified]**.
- **Texture arrays.** `ToonExt` already binds a `2d_array` (`detail`, `style.rs:38`), and `Image::reinterpret_stacked_2d_as_array` exists **[source]**. A shared array of face pages, indexed by layer, fits the material we have. `MeshTag` (a `u32` per entity, already used for recolouring) could carry the layer.
- **Levels of detail.** `VisibilityRange` gives distance bands with a dithered crossfade (HLOD) **[source: `bevy_camera-0.20.1/src/visibility/range.rs`]**. 0.19 moved the checks to the GPU. Our toon shaders already honour `VISIBILITY_RANGE_DITHER` (`toon.wesl:208`, `toon_prepass.wesl:109`), and `fade.rs` uses it. A far model is therefore a second scene under the same entity with its own range.
- **Virtual geometry and mesh shaders.** Meshlets have no skinning path **[source: no skinning in `bevy_pbr-0.20.1/src/meshlet`]**. 0.20's mesh shaders leave higher-level APIs "to future work" ([Bevy 0.20](https://bevy.org/news/bevy-0-20/)). Neither helps people yet.
- **Animation sharing.** Clips bind to bones by `AnimationTargetId`, a hash of the bone's name path. Files with VRoid's bone names could in principle share one clip asset **[inferred from the API, not tested]**. Our `anim.rs` builds "one [graph] per file, shared by everyone wearing it", and each generated file carries its own copy of the clips (CHARACTERS.md, crowd cost, item 4). Sixty-four files are 64 copies.
- **Compressed textures.** The `3d` feature set includes `ktx2` and `zstd_rust` but not `basis-universal` **[source: `bevy-0.20.1/Cargo.toml`]**. Pre-compressed KTX2 images (BC7 or ASTC) load. Whether our glTF path can reference them was not checked **[unverified]**. Our face atlas is uncompressed RGBA8 on the GPU: a 1024² atlas with mips is about 5.6 MB. That is a part of the 19 MiB of graphics memory each different person adds, but not all of it.

### What that means for our crowd

Our 64 different people differ in geometry *and* in textures. By the 0.16 notes, geometry differences need not stop batching: the mesh allocator and multi-draw indirect put distinct meshes in one batch when they share a material bind group and a mesh slab **[not measured on our crowd]**. Texture differences do stop it while `ToonExt` is not bindless. So the 212 materials are the lever, as CHARACTERS.md concluded. There are two ways to pull it:

1. **Fewer distinct textures:** one strand texture for everyone (already the same image, but loaded per file), faces on shared atlas pages or a texture array, and the face shadow maps the same way. Materials then drop to a handful of kinds.
2. **Bindless toon materials:** add `#[bindless]` to `ToonExt`, so materials that differ only by texture share bind groups. This needs the shader to index the bindless arrays.

Memory needs the 49 MiB split first, as CHARACTERS.md says. The likely items are each file's own clips, its morph targets for 15 expressions, and its uncompressed atlas.

## 5. Findings into changes, ranked

Costs are rough working days for one worker on our tools, plus the runtime cost. "Generator" means `living/tools/blender/*`, "client" means `living/game/src/*`.

### Ranked for the owner's gap: depth, internal structure, a parameter space that follows how a head is built

**1. A head built from structure: skull, landmarks, then soft tissue.**
Replace the loft-plus-bumps in `head_form.py` with three layers:
- **a skull:** a cranium (width, length, height, how round), and a face block hung from it at the brow and ear;
- **bony landmarks on the skull:** the orbit rims, the brow ridge, the zygomatic arch and the cheekbone's point, the nasal bridge and the base of the nose, the upper jaw, the jaw's angle and ramus, the chin;
- **soft tissue:** a thickness over each landmark (full for children, thin for elders, more with `build.weight`).

The features hang from the landmarks: the eye sits in its orbit, the nose's root at the bridge, the mouth on the upper jaw, the ear behind the jaw's ramus. A parameter then moves a *bone*, and the features attached to it follow. A wider zygoma widens the face, pushes the cheeks out and shifts the eyes' outer corners. A longer ramus lowers the jaw's angle. The 34 values are re-expressed on these layers and keep their names where they still mean the same thing. Moving the eyes lower on a rounder cranium is pass 3's open item (CHARACTERS.md, "Style"), and it falls out of this rather than needing a further style number.
*What it closes:* "how it is structured internally" and "points you can tweak … that still make sense". Each point is a bone with a range, and features cannot leave their sockets.
*Cost:* the largest item, about 8 to 12 days: the skull and landmark model, re-deriving the mesh's projection, re-tuning `STYLE` against the reference, and a new pass of the town's check pages. No runtime cost. Risk: the expressions are rebuilt by building the face again, so each morph must be re-checked.

**2. Designed shading planes: face normals and a drawn face shadow map from the same landmarks.**
Replace `face_normals.py`'s ellipsoid with a **shading proxy** computed from change 1's landmarks. The proxy is a planar head after Asaro, softened for our style: a front plane, a side plane breaking at the cheekbone, a wedge for the nose, a plane under the nose and under the lip, the jaw's underside, eye sockets. Two outputs follow:
- normals transferred from the proxy;
- a threshold map built as the anime guides do: script-drawn shadow shapes (the cheek triangle, the nose's side, the eye socket, the jaw) at N light angles, made into distance fields and interpolated.

For generated people the generator writes these itself instead of `face_normals.py` guessing them afterwards. The same landmarks can mark where lines belong (change 4).
*What it closes:* depth as the toon look shows it. A shadow shape that follows the face's planes is what makes a drawn face read as having depth.
*Cost:* about 4 to 6 days, and the shapes need judging on the board in blind pairs, as the 2026-11-09 face work was. No runtime cost: the shader, the map's format and the material are unchanged. Risk: CHARACTERS.md records a nose shadow that "read as a blot". The shapes must be designed polygons with clean edges, not cast shadows.

**3. A correlated parameter space: face types, then bounded offsets, then fine values.**
- **Face types.** About three designed face types for each sex and age band (Blue Protocol's three), each a complete set of change 1's skull and landmark values. Set them by measuring the reference, as `STYLE` was, and by drawing.
- **Shape directions.** A person is drawn as a blend of types plus a few correlated directions. The directions come from either:
  - (a) the covariance of heads we judged good on the board, or
  - (b) FLAME 2023 Open's shape space (CC BY 4.0) measured at our landmarks, for how real jaws, brows, cheekbones and nose lengths vary together.
  Bound the draws by distance from the type, not per value.
- **Fine values.** The 34 values stay as small offsets within that.
- **Families** share their type and part of their directions, which is clearer than today's half of each value.
- **Asymmetric responses.** Each value may have its own designed response in each direction (MakeHuman's `incr`/`decr`).
*What it closes:* "different shapes that still make sense": variety comes from moving along directions in which heads really vary, and from a few drawn types, not from 34 independent nudges round one average.
*Cost:* about 3 to 5 days on top of change 1. Option (b) adds about 2 days: download, measure at our landmarks and keep only the covariance, plus a CC BY credit in THIRD_PARTY.md and the game's credits. No runtime cost.

**4. Lines where depth turns: outline normals, overhang lines and per-vertex width.**
- **Outline normals.** The generator writes smoothed outline normals into `bevy_mod_outline`'s `ATTRIBUTE_OUTLINE_NORMAL`, so the shell no longer follows the flattened lighting normals.
- **Overhang lines.** Lines at the chin, jaw, ears and nose tip come from that shell, or from an inner-line ID in the post-process edges as Blue Protocol does.
- **Per-vertex width.** Width set per vertex, ASW's way: 0 on lids and lashes, thin on hair, a little heavier under the jaw. It needs our own outline shader or a patch, because the crate's width is one value per entity.
*What it closes:* depth at the silhouette and under the jaw, and the "line under the jaw" where neck and face shade differently (CHARACTERS.md).
*Cost:* outline normals about 1 day; per-vertex width about 3 to 4 days (client shader and generator). Runtime: an extra vertex attribute; the outline pass is unchanged.

**5. Eyes drawn with depth.**
- In the eye's kind in `toon.wesl`: a parallax offset of the iris along the view, a lid-shadow band over the top of the iris and white, and a highlight kept toward the camera.
- In `face_paint.paint_iris`: a second iris colour.
*What it closes:* gap 4 in CHARACTERS.md.
*Cost:* about 2 days. Runtime: a few instructions on eye pixels only.

**6. Hair highlights from the locks.**
- `hair.py` writes each lock's direction as the vertex tangent, and a band position and tooth pattern per lock into the strand column or a second UV.
- `toon.wesl` shifts the tangent per lock (Scheuermann) and draws the ring from it, broken where locks break.
*What it closes:* the "thin even stripe" (CHARACTERS.md gap 1, "the highlight band as the reference has it").
*Cost:* about 2 to 3 days. Runtime: negligible.

### Ranked for crowd cost (separate: it does not close the owner's look gap, but blocks Cullet)

| # | Change | Expected effect | Cost |
|---|---|---|---|
| C1 | Shared textures: the strand texture once; faces and face shadow maps on shared pages or a `2d_array` with the layer in `MeshTag`; `town.py` builds the pages and rewrites UVs | materials on 64 people from 212 toward the low twenties (the one-file run had 23), and the frame time toward the one-file run's 18.9 ms median (measured on a loaded dev-box) | 3 to 5 days, generator and client |
| C2 | Or: `#[bindless]` on `ToonExt` and a shader that indexes the arrays | the same batching without atlasing, where the adapter supports texture binding arrays | 2 to 4 days, client; adapter support to check first |
| C3 | Clips once: a shared clip library bound by bone name, not copied into each file | a large part of the 49 MiB a person **[to measure]** | 2 to 3 days, client and `animate.py` |
| C4 | A far model under `VisibilityRange` (about 6,000 triangles, CHARACTERS.md item 2), with a **shared far face** carrying the person's proportions as bone scales, after Blue Protocol | triangles and vertex work beyond about 10 m; the far face is shared and instanced | 4 to 6 days, generator and client |
| C5 | Meshes joined by shading kind (12.6 a person to 6) | fewer batches a person | 1 to 2 days, generator |
| C6 | Compressed textures (KTX2 BC7/ASTC) and the full 1024² atlas only near the camera | about a quarter of the texture memory | 2 to 3 days; glTF path to check |
| C7 | Pose sharing (one pose per state for far people) and vertex-animation textures past the far model | CPU animation cost at hundreds of people; needed for 2,000, not 64 | later; 5+ days |

Do C1 or C2 with C3 first, and measure again with `crowd.py` on a quiet machine before choosing more. [PERFORMANCE_CONTRACT.md](PERFORMANCE_CONTRACT.md) rules apply to any claim that follows.

## 6. Licences

Each row comes from the licence's own page unless marked. "Fetched" means the page was read on 2026-11-11. "Via search" means the page refused fetching and its text came from a search result.

| Item | Licence | Commercial use | Inside our in-game generator | Page |
|---|---|---|---|---|
| SMPL | SMPL-Model License, non-commercial scientific research | No ("any use for commercial purposes, is prohibited"); commercial licence by request | No | [fetched](https://smpl.is.tue.mpg.de/modellicense.html) |
| SMPL-X | SMPL-X Model License, non-commercial scientific research | No; commercial "through Meshcapade.com", now part of Epic, with its platforms shut down | No | [fetched](https://smpl-x.is.tue.mpg.de/modellicense.html); [Meshcapade](https://meshcapade.com/) |
| FLAME 2017–2023 | Academic Model License, non-commercial | No | No | [fetched](https://flame.is.tue.mpg.de/modellicense.html) |
| **FLAME 2023 Open** | **CC BY 4.0** | **Yes, with attribution** | Yes, with credit | [fetched](https://flame.is.tue.mpg.de/modellicense.html) |
| Basel Face Model 2017 / 2019 | non-commercial research licence | No ("internal, non-commercial research, evaluation or testing purposes only"); no distribution | No | [fetched](https://faces.dmi.unibas.ch/bfm/bfm2019.html) |
| MakeHuman | code AGPL; assets CC0 1.0 | assets yes; output is the user's | assets yes; code no (copyleft) | [fetched](https://github.com/makehumancommunity/makehuman/blob/master/LICENSE.md) |
| MPFB2 | code GPLv3; assets CC0 1.0 | yes ("Yes." for closed-source games) | assets yes ("perfectly fine" to build another generator) | [fetched](https://github.com/makehumancommunity/mpfb2/blob/master/LICENSE.md); [FAQ](https://static.makehumancommunity.org/mpfb/faq/build_other_chargen.html) |
| Character Creator content | Standard / Extended / Enterprise | export to game engines allowed (Standard) | Enterprise only, case by case **[unverified: forum]** | [via search](https://www.reallusion.com/license/content.html); licence pages 404 |
| Daz 3D content | EULA + Interactive License Addendum 3.0 | games need an Interactive License | restricted (no in-game sale; revenue cap without consent) | [fetched](https://www.daz3d.com/eula) |
| VRoid Studio output | VRoid Studio Guidelines | output and unrestricted preset items may be used commercially | some items need an "application creation license" from pixiv, which may be refused; [GAME_BRIEF.md](GAME_BRIEF.md) records that a creator built from VRoid's parts needs a separate pixiv licence | [via search](https://vroid.com/en/studio/guidelines); 403 to fetching |
| VRoid samples (Shino, Vivi) | CC0 in each file's VRM metadata | yes | studied only | [THIRD_PARTY.md](../living/tools/blender/THIRD_PARTY.md) |
| Mixamo Fuse | not determined; discontinued, support ended 2020-09-13 | not determined | no | [via search](https://helpx.adobe.com/fuse/faq.html) |
| Ready Player Me | not determined; services shut down 2026-01-31 **[secondary]** | n/a | no | [secondary](https://avatarsdk.com/blog/2026/08/31/avatar-platforms-2026-whos-alive-whos-gone/) |
| Talks and articles cited in §3–4 | read for method only; no code or assets taken | n/a | n/a | — |

## 7. What could not be verified

- **Guilty Gear Xrd's GDC 2015 handout** refused the connection. Its points here (vertex attributes as data, a vertex-colour threshold offset, hand-edited face normals) come from search summaries of the talk. ASW's 2025 toon-line deck was read in full.
- **HoYoverse's face shading** is reverse-engineered by the community, not published by the studio.
- **Hi-Fi Rush's toon face shadow** method: only the session summary was read.
- **VRoid Studio's guidelines and help pages** returned 403. The guideline text came from search results, and the slider list is not documented.
- **Reallusion's licence pages** returned 404. The in-game creator rule is from a forum statement by staff.
- **Adobe's Mixamo and Fuse FAQs** returned 403. The Fuse dates are from search results of Adobe's page and Wikipedia.
- **Ready Player Me's shutdown** is from secondary sources. Its domain no longer resolves.
- **The octahedral impostors article** (shaderbits) returned no body text.
- **Unreal's AnimToTexture** has no official page found. The City Sample use is from forum posts.
- **FLAME:** the vertex count, and whether downloading FLAME 2023 Open needs a registration.
- **The Basel Face Model's** basis sizes and scan count are from secondary papers.
- **MakeHuman 2's macro curves:** its own page's pseudocode contradicts its worked example.
- **MakeHuman community status:** the news titles ("Community services shut down", 2026-10-21) were seen, not read.
- **Bevy on our machines:** whether our adapters report `TEXTURE_BINDING_ARRAY` (bindless), whether our toon materials really fall back to one bind group each (to confirm with `LIVING_GAME_PERF=diag`), whether one clip asset can drive many files, and whether our glTF loading can use KTX2 images. These are read from the 0.20.1 source or inferred from the API, not run.
- No anime face topology reference of a studio's own was found. The topology notes are general.
- **Link check (2026-11-11):** 67 of the 70 external links answered 200. The Guilty Gear handout (connection refused), Adobe's Fuse FAQ (403) and the Polycount thread (403 to automated requests) did not; the last two were seen through search results.

## 8. Sources

Grouped by section. Read on 2026-11-11 unless marked.

**Body and head models:** [SMPL](https://smpl.is.tue.mpg.de/) · [SMPL licence](https://smpl.is.tue.mpg.de/modellicense.html) · [SMPL-X licence](https://smpl-x.is.tue.mpg.de/modellicense.html) · [Meshcapade](https://meshcapade.com/) · [FLAME](https://flame.is.tue.mpg.de/) · [FLAME licences](https://flame.is.tue.mpg.de/modellicense.html) · [BFM 2019](https://faces.dmi.unibas.ch/bfm/bfm2019.html) · [BFM 2017](https://faces.dmi.unibas.ch/bfm/bfm2017.html) · [Jozwik et al., PNAS 2022](https://kriegeskortelab.zuckermaninstitute.columbia.edu/sites/default/files/content/JozwikOKeeffeStorrs_etal_2022_PNAS.pdf) · [arXiv 1903.10873](https://arxiv.org/pdf/1903.10873)

**Generators:** [MakeHuman technical notes](https://static.makehumancommunity.org/oldsite/uncategorized/technical_notes_on_makehuman.html) · [MPFB targets](https://static.makehumancommunity.org/mpfb/docs/assets/targets.html) · [MPFB modeling](https://static.makehumancommunity.org/mpfb/docs/characters/modeling.html) · [MakeHuman 2 macro.json](https://makehuman-2.github.io/custom-toc/nerds/conf_macro) · [MakeHuman 2 modelling.json](https://makehuman-2.github.io/custom-toc/nerds/conf_modelling) · [MakeHuman LICENSE.md](https://github.com/makehumancommunity/makehuman/blob/master/LICENSE.md) · [MPFB2 LICENSE.md](https://github.com/makehumancommunity/mpfb2/blob/master/LICENSE.md) · [MPFB2 LICENSE.ASSETS.md](https://github.com/makehumancommunity/mpfb2/blob/master/LICENSE.ASSETS.md) · [MPFB FAQ, closed source](https://static.makehumancommunity.org/mpfb/faq/use_in_closed_source.html) · [MPFB FAQ, other generators](https://static.makehumancommunity.org/mpfb/faq/build_other_chargen.html) · [Reallusion six levels](https://manual.reallusion.com/Headshot_for_CC/ENU/1.0/ID_Six_Levels_of_Morph_Detail.htm) · [Reallusion facial profile sliders](https://manual.reallusion.com/Character-Creator-5/Content/ENU/5.0/05-HD-Character/Slider-Table-for-Facial-Profiles.htm) · [Reallusion custom sliders](https://manual.reallusion.com/Character-Creator-4/Content/ENU/4.0/06_Customizing_Morphing_Sliders/Creating-Head-and-Body-Morphing-Sliders.htm) · [Reallusion content policy](https://www.reallusion.com/license/content.html) · [Reallusion forum, games](https://forum.reallusion.com/PrintTopic550716.aspx) · [Daz EULA](https://www.daz3d.com/eula) · [Daz Interactive License](https://www.daz3d.com/interactive-license-info) · [Daz forum, correctives](https://www.daz3d.com/forums/discussion/comment/8361691) · [VRoid Studio guidelines](https://vroid.com/en/studio/guidelines) · [Adobe Fuse FAQ](https://helpx.adobe.com/fuse/faq.html) · [Adobe community, Fuse licence](https://community.adobe.com/t5/mixamo-discussions/fuse-cc-beta-what-is-the-license-and-can-i-use-still-model-with-commercial-use/m-p/14945490) · [avatarsdk.com, platforms 2026](https://avatarsdk.com/blog/2026/08/31/avatar-platforms-2026-whos-alive-whos-gone/) · [genies.com, RPM shutdown](https://genies.com/blog/ready-player-me-shutdown)

**Anime production:** [Guilty Gear Xrd, GDC 2015](https://gdcvault.com/play/1022031/GuiltyGearXrd-s-Art-Style-The) · [handout](https://www.ggxrd.com/Motomura_Junya_GuiltyGearXrd.pdf) (not reached) · [ASW toon line control](https://docswell.com/s/ASW_Academy/5LVY67-GG-Toonline-Eng) · [Blue Protocol creator, CEDEC 2021 (Game*Spark)](https://www.gamespark.jp/article/2021/08/27/111420.html) · [Blue Protocol rendering, CEDEC 2021 (GameBusiness.jp)](https://www.gamebusiness.jp/article/2021/09/13/19051.html) · [Blue Protocol, CEDEC 2020 (CGWORLD)](https://cgworld.jp/feature/202011-cedec2020-bluep.html) · [Hi-Fi Rush, GDC 2024](https://gdcvault.com/play/1034330/3D-Toon-Rendering-in-Hi) · [80.lv on Hi-Fi Rush](https://80.lv/articles/the-making-of-hi-fi-rush-s-3d-toon-rendering-style) · [Unity Dojo 2021 (miHoYo)](https://www.docswell.com/s/UnityJapan/KWRPQ5-210617-unity-dojo20211mihoyozhenzhongyi) · [HoyoToon wiki](https://github.com/Melioli/HoyoToon/wiki/Using-the-Genshin-Shader) · [NoiRC256 URP shaders](https://github.com/NoiRC256/URPSimpleGenshinShaders) · [SDF shadow map guide](https://destiny-fine-0ac.notion.site/SDF-Shadowmap-9527f23116aa42dc89e3c9e17a54ddf3) · [Sydian Chen, stylized shadow](https://sydianandrewchen.github.io/projects/3-stylized-facial-shadow-workflow) · [Eric Hu, face shadow maps](https://erichu33.notion.site/Face-Shadow-Map-Creation-Baking-Workflow-d3b8769021e04683a2f2ae4cf16ac810) · [Unity Toon Shader](https://docs.unity3d.com/Packages/com.unity.toonshader@0.15/manual/index.html) · [UTS Angel Ring](https://docs.unity3d.com/Packages/com.unity.toonshader@0.13/manual/AngelRing.html) · [Scheuermann, SIGGRAPH 2004](https://history.siggraph.org/wp-content/uploads/2022/12/2004-Talks-Scheuermann_Practical-Real-Time-Hair-Rendering-and-Shading.pdf) · [Scheuermann, GDC 2004 slides](https://web.engr.oregonstate.edu/~mjb/cs557/Projects/Papers/HairRendering.pdf) · [Cocos, character eyes](https://discuss.cocos2d-x.org/t/tutorial-cocos-creator-practical-and-cost-effective-rendering-character-eyes/54929) · [Anime Shading Plus, eyes](https://erichu33.github.io/ASPDocs/en/articles/eyes-anime-like-setup-guide.html) · [CryEngine eye shader](https://www.cryengine.com/docs/static/engines/cryengine-3/categories/1114113/pages/1048594) · [HDRP Eye](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@12.1/manual/master-stack-eye.html) · [James Gurney, plane heads](https://jamesgurney.substack.com/p/plane-heads) · [topology notes](https://michael-vl.github.io/learning-wiki/blender/topology/) · [Blender Artists, anime topology](https://blenderartists.org/t/possible-anime-face-topology-reference/554520) · [Unreal forum, normal editing](https://forums.unrealengine.com/t/normal-editing-and-3d-modeling-discussion/150158) · [Polycount, normals](https://polycount.com/discussion/comment/2666647)

**Crowds and Bevy:** [GPU Gems 3, ch. 2](https://developer.nvidia.com/gpugems/GPUGems3/gpugems3_ch02.html) · [AC Unity, GDC 2015](https://www.gdcvault.com/play/1022141/Massive-Crowd-on-Assassin-s) · [UE modular characters](https://dev.epicgames.com/documentation/unreal-engine/working-with-modular-characters-in-unreal-engine) · [UE Animation Sharing](https://dev.epicgames.com/documentation/unreal-engine/animation-sharing-plugin-in-unreal-engine) · [UE AnimToTexture tutorial](https://forums.unrealengine.com/t/community-tutorial-animtotexture-plugin-how-to-use-it-to-make-vertex-animation-textures-for-crowds/746648) · [octahedral impostors](https://shaderbits.com/blog/octahedral-impostors) · [Bevy 0.16](https://bevy.org/news/bevy-0-16/) · [Bevy 0.19](https://bevy.org/news/bevy-0-19/) · [Bevy 0.20](https://bevy.org/news/bevy-0-20/) · [Bevy bindless example](https://bevy.org/examples/shaders/shader-material-bindless/) · crate source: `bevy_pbr`, `bevy_render`, `bevy_render_macros`, `bevy_camera`, `bevy_mesh`, `bevy_image` and `bevy` 0.20.1, `bevy_mod_outline` 0.14.0
