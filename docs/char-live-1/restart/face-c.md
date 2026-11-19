# Cora face fit, final attempt

**The face fit failed the profile check.** In the drawing the jaw rises from the chin toward the ear, leaving a visible angle above the throat. On the model the underside slopes into the neck at that point. The darker lining closes the background gap and exposes the ear, but hangs in a rounded lobe in front of the braid. Both differences are visible at the same scale in the [profile comparison and half-opacity overlay](face-c-profile-review.png). Work stopped after two high attempts and this xhigh attempt. The accepted clothing and hair checkpoints remain available.

In the [three-quarter portrait](face-c-portrait-review.png) the cheek shading is continuous, the front of the chin is rounded and the mouth has a short closed line. The ear shows a rim and recessed bowl. The eye shape, green iris, catchlight and freckles come from the generator. The [orbit and play-camera sheet](face-c-review.png) covers front, three-quarter, profile, back and the 58° camera at Near and Middle. Those distant Blender views preserve the outfit and braid silhouette. Bevy evaluation belongs to the later game stage.

## Changes to the checkpoint

The [pre-fit inspection](face-c-before.json) found a 588-vertex expression cage subdivided to 2,330 vertices. All 3,492 mesh polygons used smooth shading. The saved mesh lacked custom normals. At the upper lip the last mouth control sat at 0.0991 head heights from the midline and the neighbouring cheek column at 0.0862, folding that strip inward.

The journal fits an ascending mandibular arc, eases the cheek and jaw creases and allows the lower cage to round under subdivision. The cheek columns now lie in order beyond the mouth. The fit retains the generator's working eye and mouth topology. The head uses its subdivided skin normals blended with the ellipsoid used by the project's face-normal tool. Under-jaw and tint vertices inherit their source normals. The lip shell was removed, the slit shortened, and the inner mouth moved back. Both ears use the generator's own helix, rim and bowl, with 24 segments, a smaller outline and the generator's vertex-colour multiplier on the skin swatch. A radial strip joins the existing hair material at the temple and nape. The [fitted parameters and map hashes](face-c-design.json) accompany the [saved Blender checkpoint](cora-face-c.blend).

## Verification and usage

- The head has 6,496 triangles, 3,354 smooth polygons and 15 expression keys with measured displacement. The hair including the lining has 12,978 triangles on one material.
- Both eyes close on blink, talk opens to show the teeth, and the closed smile lifts the mouth corners. Returning all keys to zero reproduced the neutral portrait pixel for pixel. [Expression row](face-c-expression-review.png)
- The saved material audit checked all 25 material datablocks and all three image datablocks. The packed atlas, iris and tint matched the procedural generator output hashes. The audit recorded zero violations. [Audit log](audit.jsonl)
- A separate factory-startup [replay](replay.py) of the [journal](session.jsonl) reproduced all 12 RGBA renders pixel for pixel, the design metrics and the three map hashes. [Verification counts](face-c-verification.json)
- Xhigh inspection, fitting, renders, replay and evidence took about nine minutes. The two high attempts took about six minutes and forty seconds together. External image generations and game builds during this attempt were zero. Token usage and cost were unavailable. The live Blender bridge closed after the checkpoint was saved.
