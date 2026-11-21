# Top-down play camera

Settings › Play › Camera starts at Top-down for a fresh profile. Orbit (old) restores the [turning camera](turns.md). Top-down centres on the character and starts north-up. Drag with the middle mouse button or twist two fingers on a macOS trackpad to change the bearing. A short middle tap snaps north when the button is free. N also snaps north and can be changed under Settings › Controls › Snap camera north. Orbit still aligns to facing on middle tap. WASD follows the displayed bearing, and the compass, world rays and cutaway use the same view. Settings › Camera keeps the rotation toggle, speed and invert in the local profile. Shift runs. Cursor is the default Facing preset for Top-down. Orbit defaults to Natural. A choice under Settings › Play › Facing applies to both camera modes.

| Stop | Zoom | Eye above chest focus | Pitch down | Vertical FOV |
| --- | ---: | ---: | ---: | ---: |
| Far | 0.00 | 19 m | 58° | 46° |
| Middle (default) | 0.55 | 12 m | 58° | 44° |
| Near | 1.00 | 8 m | 58° | 42° |

These are the Ours, fixed 58° play defaults. Ours (current) restores the 65° / 58° / 48° tilt curve. The wheel moves by 0.05 per notch, and pinch shares its zoom coordinate. A stationary cursor keeps its facing intent through zoom, while the ground pick updates under the cursor. A scrollable window or the held F wheel consumes the wheel. The HUD keeps talk and fight context while the player's zoom remains under their control.

Shade and scoped character rendering follow the character's sight. The dithered cutaway affects roofs and canopies intersecting the camera-to-character segment. Support surfaces are protected by the existing support probes. Generic forest leaves the sight line clear with cover disabled. With gaze enabled, the zoom target selects the band independently of the preset and Shade waits for the owner field. [Gaze scenario](gaze.md).

## Driving it

Run `check.py --run $R camera` on a fresh island scratch world, or a scratch world compiled from the copied Brackenford play scene. The scenario selects Ours (current), sets noon and places three residents using admin calls. After each field drive it returns the residents to their saved locations and reinstalls their previous behavior graphs. With gaze disabled it runs with the facing law off and on, then checks the starting zoom, all three settled poses, sight source and range, picks on the front resident's ground point and body, the separate short hover and detailed target labels at Middle, and consumption of line-wheel input over a person window. It captures the street, the forest edge, and a market stall eave at every stop with the facing law in both states.

Run `check.py --run $R camera-rotate` to drive a middle drag past its threshold, the native gesture message, N and a middle tap, walking with W at 135°, resident and ground picks, and the awning cutaway. It also checks speed, invert, disabling rotation and the exported bearing. A headless gesture message exercises the client path. Physical trackpad delivery requires a desktop play-test.

Run `VERIFY_UI_BEARING=135 check.py --run $R camera camera-lod pick windows` for the same scenarios turned 135°. Its evidence has the `-bearing-135` suffix. The north-up run uses the same command without the environment setting.

Read `ui/camera-off/` and `ui/camera-on/` for each stop's stills and dumps. `extra.view` reports the displayed zoom, eye height, pitch, FOV and bearing. Compare `perceived` (the replica's sight projection) and `seen` (body pick candidates) against the placements in `scene.json`. Read the driver log for reducer responses and use `support` for the existing cutaway support proof.

`check.py --run $R camera-narrow` drives the far-zoom person window and movement keys at 960×900. Use `camera-lod` for uncapped frame p50/p99 and the on-screen near and far counts with the eight-person LOD cap and with it turned off on the same crowded street. Its frame samples and summaries are preserved under the run's `ui/` directory. On the play-test 8 seed, `camera-faces` captures a full generated head next to the Shino fallback at Middle and Near.


## Live tuning

Start the client with `LIVING_GAME_DEV=1`, select Top-down in Play, then open Settings › Camera tuning. Click or drag a slider to set height, pitch and vertical FOV at each zoom stop, the wheel step or the easing rate. The world camera updates while the panel is open. Fixed pitch holds the selected angle. Ours, fixed 58° keeps the three Ours FOVs to isolate tilt. A manually fixed Ours (current) uses the Middle FOV at every stop. Tilt near holds the base pitch through Tilt start z, then eases to Near pitch by the closest stop. SUPERVIVE and LoL use fixed pitch, and Corepunk uses Tilt curve.

Copy values includes the displayed bearing in degrees and writes the same JSON to the system clipboard and to `camera-tuning.json` beside `game.json` (or beside the file named by `LIVING_GAME_SETTINGS`). The panel's edits are saved in `camera_tuning` in the settings file.

`check.py --run $R camera-tuning` opens the developer page, resets to Ours, changes the Middle height, selects and adjusts Fixed pitch, copies values, then adjusts and exports Tilt near and zooms in. Read `ui/camera-tuning/` for the displayed views, the panel still, the saved settings and the exported JSON. A headless drive checks the file. The system clipboard can be checked in a desktop play-test.


`check.py --run $R camera-lol` selects LoL through Settings, zooms to 4.8 m, points at the resident's ground and body, selects them, then samples eye clearance and continuity walking from the market awning. The cutaway log and screenshots show the roof transition. The awning case exercises ordinary terrain. `check.py --run $R camera-lol-ridge` crosses a hillside where the nominal eye would intersect terrain. Its feet log records actual eye height and ground clearance frame by frame.

`check.py --run $R camera-lod` runs with the eight-model cap and again with the cap off. It samples each zoom stop for Ours, fixed 58°, then places a denser crowd for the 4.8 m LoL stop. Read `camera-lod.json` and `camera-lod-lol.json` for the near/far counts and uncapped wall-frame p50/p99 values.
