# char-port-2 · hair-mirror: why a mirrored cut drew unmirrored

**The question** (from [S6's mirror check](../s6/mirror/README.md)): `swept_braid` built parted left and parted right is an exact mirror (vertices to 1 mm, weights, the file composed offline), yet main's client drew the two differently at S6's front portrait: 208 px of hair against 192, and on one side the near section stood off the cheek as a flat slab.

**The answer:** the client treats left and right alike. The drawings differ because the head they are drawn on is turned. At S6's moment, 2.0 s into the idle clip, the clip's own keys turn the head 11–12° to one side. A mirrored cut on a turned head is not a mirrored picture: the near section on one side is seen broadside, the other's edge-on. In the bind pose, with the head square, the two partings draw as mirrors: 201 and 201 px, mismatch 0.028.

## The cause, and its proof

| Pose | Head (eyes' joints, as drawn) | Eyes' middle against the forehead's (no hair) | Hair width L / R | image_spread body width L / R | Mismatch, best axis |
|---|---|---|---|---|---|
| idle 2.0 s (S6's moment) | yaw −11.4°, roll +3.7° | +12.8 px | **208 / 192** | 199 / 185 | 0.607 |
| idle 0.0 s (the clip turns the head the other way, +6°) | | −9.1 px | **192 / 207** | 183 / 197 | 0.637 |
| bind (`LIVING_GAME_VIEW_CLIP=bind`) | yaw 0.00°, roll 0.00° | +0.5 px | **201 / 201** | 195 / 195 | **0.028** |

- **It is the clip's data.** Over the spine chain, the idle clip's keys (`lookdev/anim/own-clips.glb`) turn the head −12.3° at 2.0 s and −12.1° to −12.5° from 1 to 3 s, and +6.1° at 0 s. The drawn head follows them (the view's joint dump, `LIVING_GAME_VIEW_JOINTS`), and the measured turn on a face with no hair follows the same course: −9.1 px at 0 s, then +12.4 to +13.2 px from 1.0 to 3.0 s. The hips and legs stay square (−0.1°).
- **The asymmetry follows the head.** When the head turns the other way (0.0 s), the other parting draws wide. In the bind pose neither does.
- **Nothing else moved it.** Springs on or off in the bind pose: the same 201 / 201 px and 0.028 (the cut's one spring chain is the plait). The asset view runs no head twist (`twist.rs` acts on bodies with `anim::Anim`), and no foot IK on the head. Every collider is symmetric about x, and so is the one chain's gravity, (0, −1, 0). The type's skeleton is symmetric, and its node rest equals its bind pose (worst 4·10⁻⁸). Both files' inverse bind matrices mirror to 2·10⁻¹⁶, their windings and weights mirror, and the identity rig's per-side rule mirrors (a new test, below).
- **Without a clip the head still turns.** A rest frame without clips (`LIVING_GAME_SHARED_CLIPS=0`) is not the bind pose either: `lookdev::animate` sways a body that has no clips, the head up to 8.6° (`sin(t·0.5)·0.15` rad). The bind pose keeps the body still.

## What changed

- **The asset view's bind pose** (`view.rs`, `lookdev.rs`): `LIVING_GAME_VIEW_CLIP=bind` plays no clip, and `lookdev::animate` leaves the body alone; the face still blinks. Each model stands in its file's bind pose, square to the camera, with its arms out. It is a dev switch of the asset view and changes nothing else. Main's binary and this branch draw 16 of 16 regression frames byte-identically (below).
- **image_spread.py's pose** (`--pose bind|idle`, default `bind`). Its docstring said idle 2.0 s was square; it is not (above). `--pose idle` gives S6's earlier numbers exactly. The S6 spread band was set on idle frames, so S6's owner should look at a cut's `body_over_eyes` again in the bind pose: `swept_braid` reads 2.661 on both partings there, against 2.848 and 2.648 at idle (band 2.973–3.319).
- **The mirror check** ([mirror_pair.py](mirror_pair.py), [mirror_metric.py](mirror_metric.py), [rope_id.py](rope_id.py)):
  - **What it draws:** both builds of a pair through image_spread.py, plus an ID copy with the plait in magenta. The plait is shared unmirrored by both partings, so the masks leave it out.
  - **What it compares:** the left build's hair mask, mirrored about the body's midline (the eyes sit 4 px off it at rest), against the right build's.
  - **The acceptance:** whole hair width and image_spread's body width each within 2 px between the builds, and the mismatch (pixels in one mask only over pixels in either) at most 0.05 with the axis free within ±3 px.
- **A test** (`characters/identity.rs`, `paired_bones_change_as_mirrors`): every value of the identity rig, one at a time and all together at four amounts, moves, scales and turns each paired bone as its partner's mirror. That is the client's one per-side rule.

## Evidence

- **[pair.png](pair.png):** each row shows parted left, parted right, the left build mirrored, and the masks (grey both, red the left mirrored only, blue the right only). The top row is idle 2.0 s, the bottom the bind pose.
- **[mirror.json](mirror.json):** the measures. `idle` and `bind` are from this branch's binary; `idle_main_binary` is from main's, and its numbers are the same as `idle`.
- **The builds:** dev-box's `mirror-keep` pair (sha256 `a041bb5e…` left, `0ec541e5…` right), on the laptop's pinned render set `79072c65d37f`.
- **Run:**

```bash
python3 docs/char-port-2/hair-mirror/mirror_pair.py OUT --binary living/target/release/living-game \
    --left DIR_L --right DIR_R            # each DIR: swept_braid.glb and hair-masks.png; --pose idle for S6's old moment
```

`mirror_pair.py` overwrites `lookdev/styles/hair/<style>{,_all,_none,_rope}.glb` and the page in the checkout's asset tree. Run it in a worktree whose `lookdev` is a copy, not a link to a shared tree.

## Not covered

- **The dev-box render pass.** Main's client and this branch draw the same everywhere outside the bind pose, but the render group still needs its pass before merge.
- **Other cuts' mirror pairs.** Only `swept_braid` was built both ways.
- **A turned head with a mirrored turn.** The idle has no moment at +12°. Under the bind pose's symmetry, the left build at a head turn of θ should match the right build at −θ, mirrored; this was not drawn.
