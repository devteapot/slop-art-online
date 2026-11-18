# Top-down play camera

Settings › Play › Camera starts at Top-down for a fresh profile. Orbit (old) restores the [turning camera](turns.md). Top-down centres on the character, keeps north up, and uses fixed screen directions for WASD. Shift runs. Cursor facing starts enabled on a fresh profile, and the Facing setting retains Travel.

| Stop | Zoom | Eye above chest focus | Pitch down | Vertical FOV |
| --- | ---: | ---: | ---: | ---: |
| Far | 0.00 | 19 m | 65° | 46° |
| Middle (default) | 0.55 | 12 m | 58° | 44° |
| Near | 1.00 | 8 m | 48° | 42° |

The wheel moves by 0.05 per notch, and pinch shares its zoom coordinate. A stationary cursor keeps its facing intent through zoom, while the ground pick updates under the cursor. A scrollable window or the held F wheel consumes the wheel. The HUD keeps talk and fight context while the player's zoom remains under their control.

Shade and scoped character rendering follow the character's sight. The dithered cutaway affects roofs and canopies intersecting the camera-to-character segment. Support surfaces are protected by the existing support probes. Generic forest has no sight blocker until the shared cover policy lands.

## Driving it

Run `check.py --run $R camera` on a fresh island scratch world, or a scratch world compiled from the copied Brackenford play scene. The scenario sets noon and places three residents using admin calls. It runs with the facing law off and on, then checks the starting zoom, all three settled poses, sight source and range, picks on the front resident's ground point and body, the separate short hover and detailed target labels at Middle, and consumption of line-wheel input over a person window. It captures the street, the forest edge, and a market stall eave at every stop with the facing law in both states.

Read `ui/camera-off/` and `ui/camera-on/` for each stop's stills and dumps. `extra.view` reports the displayed zoom, eye height, pitch, FOV and bearing. Compare `perceived` (the replica's sight projection) and `seen` (body pick candidates) against the placements in `scene.json`. Read the driver log for reducer responses and use `support` for the existing cutaway support proof.

`check.py --run $R camera-narrow` drives the far-zoom person window and movement keys at 960×900. Use `camera-lod` for uncapped frame p50/p99 and the on-screen near and far counts with the eight-person LOD cap and with it turned off on the same crowded street. Its frame samples and summaries are preserved under the run's `ui/` directory. On the play-test 8 seed, `camera-faces` captures a full generated head next to the Shino fallback at Middle and Near.
