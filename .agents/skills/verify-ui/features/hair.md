# Hair shine

The highlight on hair (`living/game/src/toon.wesl` `hair_light`), by name from the style profile's table (`style.rs` `HAIR_SHINES`): each shine is the ring's values in `RING_KEYS` order (strength, width, edge softness, comb teeth, strand break-up, tangent shift, how far up a surface must face, from how far it faces the character's forward it fades, the teeth's scale, placed by the view or at a height and where, the share of locks without it, how far it moves per lock, and the width on hair without lock data).

- **Crown** (the default since hair-ring-2; re-tuned in hair-ring-3): on char-4's hair a hard band at one height over the crown (N·up 0.52), about 1.6 cm wide, teeth about 7 mm, broken where locks part (each lock's `_GREY`), never across a fringe; on other hair (VRoid bases) the view-placed ring at hair-ring-2's width. A hair file's `_RING` replaces the client's own placement when present.
- **Soft:** a softer, wider band broken by the strands.
- **Today:** the ring before hair-ring-1, one hard band that crosses a smooth fringe.

## Sub-features

- `default`: a fresh settings file (`hair_shine` null or missing) and no `LIVING_GAME_HAIR_SHINE` start on Crown, and the client saves no choice until one is made.
- `choose`: Settings › Play › Hair shine; the log says `settings: hair shine: <name>`.
- `keep`: the settings file's `hair_shine`, read back at the next start.
- `start`: `LIVING_GAME_HAIR_SHINE=crown|soft|today` starts in one; `LIVING_GAME_HAIR_RING=<values in RING_KEYS order>` sets single values over any (look-dev captures; the log names them).
- `pixels`: switching changes the hair and nothing else.

## How to get to it (user POV)

- Menu › Settings › Play › Hair shine.

## Driving it with drive.py

Preconditions: baseline.

- **Scenario.** `check.py --run $R hair` (run it with `uv run --with pillow --with numpy python`, for the pixel checks):
  - deletes the drive's settings file;
  - `dump:01`: `extra.hair_shine == "crown"`, `extra.hair_shine_saved` null;
  - Settings › Hair shine › Soft, then Today (`dump:02`, `03`); the drive's `settings.json` has `"hair_shine": "today"`;
  - a second drive reads it back (`dump:00`), sets `shine:crown`, places a resident beside the player (`--place`), opens their window (the camera on their face) and photographs `01_crown`, `02_today`, `03_crown`, `04_soft` and `05_crown` from one view;
  - Today and Soft each differ from the preceding Crown near the heads (`seen` in `dump:06`). Away from the heads, the check uses the surrounding Crown shots to account for changes from idle motion and lighting.
- It refuses to run with `LIVING_GAME_HAIR_SHINE` or `LIVING_GAME_HAIR_RING` set.

## Hand-made character files

A GLB opts in through its default scene's `extras.slop` with `contract: 1` and `character: "handmade"`. The load observer turns authored `forward: "+Z"` scenes to the client's −Z convention. Material `extras.slop.slot` identifies hair, skin, face, eyes, tint and cloth. An opt-in hair material uses its own palette and thresholds. Files without the scene declaration use the existing material classification and shine controls. See the [asset contract](../../../../docs/HANDMADE_HAIR.md).

```bash
just living-game-calibrate view/<file>.glb
```

Run on a local hand-made export in `living/game/assets/view/` with its calibration targets and sidecars. The recipe builds the release client (honouring `CARGO_TARGET_DIR`), audits the metadata and renders three fixed daylight asset-view shots without a world. Inspect the portrait for the forward turn and the near and turned stills for the hair. The run writes screenshots, `client.log`, `colours.csv` and `report.json` under `.local/living/calibrate/<stem>/<time>/`. Exit 1 can indicate that measured patches missed their targets. Read the audit and patch results to identify the cause. The live `hair` scenario checks the existing presets on town characters.

**Lock ink (contract v1.1):** a profile that sets any of `ink`, `ink_px`, `ink_range` or `ink_fade_px` draws lock lines from `<stem>.hair.png` G, a distance field made by `living/tools/characters/ink_field.py LINES.png STEM.hair.png --range R` (`--seams-as-lines --glb FILE.glb` for the UV island borders). `ink_range` must equal the field's `--range`. The hair needs a real UV unwrap; the audit warns when its TEXCOORD_0 spans no area, and `ink_field.py` refuses. Measure an ink line in the calibration frame with `"sample": "min5"` on its patch. To photograph the game camera's stops in the asset view, use `near@YAW`, `middle@YAW`, `far@YAW` or `play:HEIGHT:FOV@YAW` in `LIVING_GAME_VIEW_SHOTS`, after `idle@0/` for a paused pose. To measure in metres, use the measuring view (`LIVING_GAME_VIEW_ORTHO=1`, [measure-view.md](measure-view.md)). The shimmer of the lock lines is scored by `living/tools/characters/hair_shimmer.py view/<file>.glb` (pans and zooms at each stop, the second temporal difference of the line's darkening against the profile's own band edges); no live scenario checks ink.

**Ink on any slot (contract v1.2, [the ink contract](../../../../docs/HANDMADE_INK.md)):** a material's `extras.slop.ink` (`color`, `width` `"px"`|`"uv"`, `px`, `min_px`, `range`, `fade_px`, `map`, `taper`) draws lines from its ink map, `<stem>.<slot>.ink.png` (G the distance to the nearest stroke, R its width), bound at 106 beside the face map or hair mask and lit by the material's own light. A carrier (BLEND, base alpha 0, no texture) draws only its ink, takes no outline and sorts after the face parts. Make a map with `ink_field.py LINES.png|STROKES.json STEM.SLOT.ink.png --range R [--width W.png]`; `calibrate.py` audits it (errors: no map, `range` ≤ 0, a collapsed UV0, a carrier not BLEND) and takes per-slot ink patches (`"slot"`, `"material"`, floor-relative `"relative"`, `"floor"`; `"swatch": "ink"` suggests the material's `ink.color`); `ink_shimmer.py view/<file>.glb --slot S [--fade A,B] [--stills] [--also portrait]` scores the slot's shimmer at the three stops (`hair_shimmer.py` is its `--slot hair`). The asset view drives no face morphs on a hand-made file: photograph an expression from a copy whose face mesh's default `weights` hold it (Bevy takes them as the initial `MorphWeights`). No live scenario checks ink; the evidence of the v1.2 build is in `.local/living/handmade-ink/` on the laptop's `handmade-ink` worktree.

## Gotchas

- Opening Settings closes the other windows: compare shines in one view with `shine:`, not with Settings.
- Live residents with a person line use composed models by default. The client can fall back to a VRoid base. For the live lookbook and fallback routes, see [looks.md](looks.md).

## Composed characters (contract v1.3)

Composed type and style files opt in to `slop` through their scene: `{"slop": {"contract": 1}}` with no `character` ([the composed contract](../../../../docs/HANDMADE_COMPOSED.md)). The material-name rules still decide kinds; a valid `slop.hair` on name-rule hair makes it a profile (it packs `_HIGHLIGHT`, drops `_RING`), and `slop.ink` draws as on a hand-made file. Code: `handmade.rs` (`composed_of`, `composed_material`), `characters/compose.rs` (`Composer::toon`), `lookdev.rs` `convert` (type files), `characters/palette.rs`, `characters.rs` `recolor` (palette tags, bit 27), `toon.wesl` (`hand_colours`, `palette_row`).

Sub-features:

- `opt-in`: files without the scene key draw exactly as on main (no material `slop` read, today's content keys).
- `palette`: `slop.hair.palette: "tag"` with `ref` (and up to 3 `anchors`) moves the swatches and the ink to each mesh's tag colour in OKLCh (lightness and chroma by ratio, hue by offset, gamut by chroma); entries per material in a 256×5 image at binding 105, the mesh's tag names its columns; greying hair mixes the natural and silver entries by `_GREY`. `slop.ink.ref` moves an ink colour the same way (a carrier named `…FaceBrow…` takes the hair tag).
- `pages`: every cut's mask on `lookdev/styles/hair/hair-masks.png`, every class's carriers on `lookdev/types/types.eyes.ink.png`, their UV0 already in page space, manifests beside them (`hair-masks.json`, `types.ink.json`); `ink.m_uv` and `hair.ink_m_uv` declare the density, so files on one page share one material.
- `noshine`: a profile ignores the hair-shine presets (Crown, Soft, Today) by design: `check.py hair`'s "differs from Crown" checks on people who all wear profile hair pass on their idle motion, not on the shine (run them on files without `slop` for the shine itself).
- `switch`: `LIVING_GAME_COMPOSED_SLOP=on|off|noink|noink:<slot>` (measurement and tools: `off` draws composed files as before v1.3; `noink` drops `slop.ink` and a profile's lock ink).

Driving it, with no world (the asset view and the tools):

- The files: S4 and S5's generator writes them; until then `living/tools/characters/composed_fixture.py SRC/lookdev OUT/lookdev` (`uv run --with numpy --with pillow --with scipy`) makes an opted-in copy of a lookdev tree (carriers on every type's eyeline and brow, every hair cut on the mask page, Cora's palette relative to auburn with a dark anchor). Point the worktree's `living/game/assets/lookdev` link at OUT (never write into the main checkout's).
- `LIVING_GAME_LOOK_BOOK=<book> LIVING_GAME_VIEW=look:<key>,…` with portrait (`idle@0/0:8:0.36:0.88`), Near and close shots: the palette on two or more hair colours, the dark anchor (a black-haired line with and without `anchors`), a greying elder.
- `python3 living/tools/characters/calibrate.py lookdev/types/<type>.glb --no-run` (and a hair style): the composed audit, with the palette's entries for the nine hair colours; `calibrate.py --pages lookdev`: both pages against their manifests (a class's types must share their carriers' UV0: today's types don't, so the fixture fails that check by design).
- `python3 living/tools/characters/palette.py --self-test`: the maths against the contract's worked example; `palette.py PROFILE.json [#rrggbb …]` prints a profile's entries.
- `LIVING_GAME_LOOK_BOOK=<book> python3 living/tools/characters/ink_shimmer.py look:<key> --slot eyes|hair [--also portrait]`: the reference is the same person under `LIVING_GAME_COMPOSED_SLOP=noink:<slot>`.
- Left against right: `LIVING_GAME_VIEW_CLIP=bind` stands a model in its bind pose (no clip, no procedural sway), the head square. The idle clip turns the head 11–12° from 1 s on, so a cut and its mirror differ at any idle moment. `python3 docs/char-port-2/hair-mirror/mirror_pair.py OUT --binary BIN --left DIR --right DIR` draws a mirrored pair and measures it. The acceptance: widths within 2 px, mismatch ≤ 0.05; `swept_braid` reads 201/201 px and 0.028 ([hair-mirror](../../../../docs/char-port-2/hair-mirror/README.md)).
- Pixel identity: build main's client from its own worktree (the asset root is compiled in) and compare stills of unflagged files (a composed person at three-quarter and Near, a VRoid base, scenery, a hand-made file) pixel by pixel.
