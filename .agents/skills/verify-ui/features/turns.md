# The cursor while the view turns or zooms

A two-finger pan, a left drag (press and move), the middle drag and `[` `]` turn the view; a pinch or a notched wheel zooms it within 0.6–1.4 of its distance. While the view turns or zooms, the game's cursor keeps its screen position, and what it points at (the ground point you face, aim at and act on) changes under it with the view. Only an align (a two-finger double tap or a middle tap) keeps the cursor on its ground point, so the align ends with that point straight ahead. Owner, Cullet walk 1 (2026-11-11): before `cursor-pan` the cursor stayed on its ground point and rode off with the view.

## Sub-features

- `pan`: a two-finger pan (`MouseWheel` in pixels with touch phases, `pointer.rs`) turns the view; over a window it scrolls the window instead.
- `drag`: a left press that moves more than 6 px turns the view; the cursor does not follow the finger meanwhile.
- `pinch`: a pinch zooms; a notched wheel zooms by steps.
- `fixed-cursor`: through all three, the cursor stays where it is on the screen (`camera.rs` places it only during an align).

## How to get to it (user POV)

- On a trackpad: two fingers sliding sideways (pan), a pinch, a click held and moved (drag), a two-finger double tap (align).
- With a mouse: the middle button held and moved, or tapped (align); the wheel zooms. `[` and `]` turn the view.

## Driving it with drive.py

Preconditions: baseline; nothing open; the cursor off-centre (`cursor:0.72,0.62`) so a turn would carry it somewhere else; `frame:0` so a framing context does not move the view by itself.

- **Pan.** `pan:300` (a rightward pan through the pointer's own path, ×0.6 as a trackpad's pixels), then `pan:-500`. Dumps mid-pan and after: `extra.cursor` within 1 px of where it was, `extra.view.yaw` turned, `extra.cursor_ground` moved.
- **Pinch.** `pinch:0.3` (in), then `pinch:-0.4` (out): `extra.view.zoom` down then up, the cursor within 1 px, the ground under it moved.
- **Drag.** `drag:250`: the view turned, the cursor within 1 px.
- Scenario: `check.py --run $R turns` (14 checks).

## Gotchas

- The dump's `extra.cursor` is in the picture's pixels (1600×900 headless), `fx`/`fy` fractions; `extra.view.zoom` is the target zoom, which the view eases to.
- `pan:`, `drag:` and `pinch:` feed the pointer's scripted turn and zoom, the same values a real pan, drag or pinch produces after `pointer.rs` reads the events. Whether winit reports a real trackpad's gestures that way is a play-test's question.
- Facing follows the cursor's ground point, so a turn now turns the character too.
