# The measuring view

The asset view's level orthographic camera (`living/game/src/view.rs` `OrthoFrame`, `ortho`), for 2D measures in metres: a known number of pixels per metre at every depth, recorded beside each photograph. It runs with no world. It is a developer switch of the asset view. Play's camera and the asset view's defaults are unchanged without it. Design, known answer and the S7 gap: [docs/char-port-2/measure-view/README.md](../../../../docs/char-port-2/measure-view/README.md).

## Sub-features

- `ortho`: `LIVING_GAME_VIEW_ORTHO=1` (with `LIVING_GAME_VIEW`):
  - every shot through an orthographic camera at pitch 0, at the shot's yaw;
  - `front`, the default shot in this mode, is dead front: the model's forward, a hand-made file's declared one;
  - the shot's pitch, zoom, aim and camera stop are ignored; its clip and time are kept (`LIVING_GAME_VIEW_CLIP=bind` for a square head).
- `size`: `LIVING_GAME_VIEW_ORTHO_M=<m>`, the frame's height in metres. Pixels per metre is the frame's height in pixels over it (default: the model's height × 1.1).
- `place`: `LIVING_GAME_VIEW_ORTHO_Y=<m>`, the height of the frame's middle (default: the model's middle).
- `record`: each photograph's `NN-<shot>.ortho.json` (`px_per_m`, `frame_px`, `frame_m`, `camera_height_m`, `frame_middle_m`, `ground_row_px`, `yaw_deg`, `pitch_deg`), the model's `report.json` `ortho` list, and a `view: … orthographic, <k> px/m` log line.
- `lines`: the outline and the ink stay on, as in play.
  - `LIVING_GAME_PERF=nooutlines` turns off the shell outline, and `noedges` the finishing pass, to measure what each adds.
  - The finishing pass reads an orthographic depth (`post.rs` sends −far, `edges.wesl` `dist`), and characters keep their near model (`lookdev::far_models` counts pixels per metre).

## Driving it

No world and no `drive.py`. The known-answer selftest draws a head of known size (`living/tools/characters/ortho_shape.py`) through the real client and holds the widths to 1%:

```bash
CARGO_TARGET_DIR=<target the client was built in> python3 living/tools/characters/ortho_selftest.py [--out DIR]
```

- **The runs:** five client runs (as in play; outline off; both off; the old perspective portrait level and at pitch 8). Each photograph has its plate.
- **The output:** `PASS`/`FAIL` and `selftest.json`.
- **Dependencies:** standard library only.
- **Where the subject goes:** `living/game/assets/measure/` (git-ignored). It is never copied into `view/`, which a worktree may link to a shared tree.
- **The binary:** must be built from the checkout the script runs in (the client's asset root is its own checkout's).

For a character: `docs/char-port-2/measure-view/face_rows.py` (numpy and Pillow, an ear-ID type and a no-hair style installed). It compares S6b's 2D face rule in the portrait and in the measuring view with the 3D cut at the same heights.

## Proof that play is unchanged

Without the env, default asset-view shots from main's binary and the branch's must be byte-identical. Use frames at fixed clip times only: a model whose animation runs freely during a still (a VRoid base's procedural sway, a clip playing under a view shot) differs between two runs of main's binary too. Then run `check.py hair camera-lod` on a scratch island world.

## Gotchas

- **The outline is a fixed pixel count:** 2 px a side at the 50% crossing (+4 px across), within 1% at 3000 px/m but not at coarse scales. Subtract it, or measure with `nooutlines`.
- **The ink:** a 1 px line outside the silhouette, about 20% darker than the background. It falls below the 50% crossing.
- **Interactive mode** (no `LIVING_GAME_VIEW_OUT`): dragging turns the level camera round the model, and the wheel scales the frame's height. Pixels per metre is then not the env's.
