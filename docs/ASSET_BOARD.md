# Asset board

The asset board records which version of each generated asset the owner accepted, and shows every later pass beside it. It follows AGENTS.md "Build tools we own": the photographs come from the game's own renderer, in shots that are the same every time, so a pass that makes something worse is visible.

- Tool: `living/tools/board/board.py` (`just living-board …`).
- Records, tracked in git: `living/assets/board/`.
- Media and pages, outside git: `~/archive/asset-board/` (`$ASSET_BOARD_HOME`).

Built 2026-11-11 (branch `tool-6`). It replaces the per-pass comparison pages of the character spike (`living/tools/char_spike/`) and the ad-hoc contact sheets of `living/tools/view_assets.sh`; both remain for one-off looks.

## What it shows

A **family** is a set of models a generator makes and the owner judges together. It is named `kind:name`, for example `building:cone`, `building:row-low`, `prop:strand` (eight props) or `character:adult-man`. A family has one or more **members**: `subject` members are judged, and `control` members are references photographed in the same pass, such as the VRoid control beside our characters. The first control is the family's **target**.

For each family, `family/<family>.html` shows:

- **The latest version beside the accepted one,** shot by shot:
  - the accepted photograph, the latest, and a diff picture (the latest dimmed, changed pixels in red);
  - the share of pixels that changed;
  - a **Flicker** button that swaps the two in place;
  - the target's photograph where there is a control.
- **Numbers, accepted beside latest, with the change:**
  - from the model file: triangles, vertices, glowing triangles, materials, textures, morph targets, bones, clips and bytes;
  - from the asset view's report: size, height and footprint;
  - every scalar of the generator's own `report.json` entry.
- **The palette:** vertex colours by surface share as two strips, and the colours whose share moved by 1% or more.
- **Clips,** side by side, with a button to play them together.
- **The decision box:** type the owner's words, press Accept or Reject, and the page writes the `decide` command to copy.
- **History:** every version with its date, maker, track, source commit, generator and its sha256, seed, parameters and renderer. It also shows every decision with its date and the owner's words, and each version's photographs and delivered pages.

`index.html` has one card per family: the accepted version beside the latest, the latest's state (no decision, accepted or rejected), and its most changed shot.

### Fixed shots

The shot presets are in `living/tools/board/capture.py` (`PRESETS`). The preset's hash is stored with each version, so a changed preset shows as "renderer differs".

| Kind | Shots | Light |
|---|---|---|
| `building`, `prop` | `front` 0°/8°, `three-quarter` 40°/18°, `side`, `back`, `close` (30°/10°, zoom 0.45, aimed at 0.3 of the height), all 1280×960. `game` is the game camera (22 m, 28° down) at 1600×900. Glowing models also get `night-three-quarter` and `night-game`. | The `cullet` environment's day curve at 15:00 and 22:00 (`LIVING_GAME_VIEW_ATMO=1`) |
| `character` | The spike's stills (capture.sh) at 1000×1000: `front`, `three-quarter`, `side`, `back`, `face`, `face-three-quarter`, `face-side`, `hands`, `sit-three-quarter`, `sit-side`, `elbow`, `knee`, `shoulder`, `hip`. Then `game` and `game-walk` at 1600×900, each with its middle enlarged four times. Eight clips (idle, walk ×2, run ×2, sword_slash, sit_down, sit_idle) at 720×720 as H.264 mp4. | The look-dev mood, the sun at 15:00, as the spike |

A model glows when the game's rule says so (`lookdev.rs` `has_glow`): an emissive factor, or a material named `*Glow*`.

## Data format

All records are JSON, one file each. Two branches never edit the same file, so a track's pass and a coordinator's decision merge without conflict.

```
living/assets/board/<kind>-<name>/
  family.json                          {family, kind, title, description?, target?}
  versions/<id>.json                   one published version
  decisions/<date>-<id>-<verdict>.json one accept or reject
```

**Version id:** `YYYYMMDD-<source commit, 8>-<hash, 6>`. The hash covers the generator's sha256, the seed, the parameters, and each member's name, role, file sha256 and recipe.
- The same commit and content keeps its first id, even on another day. Publishing it again replaces its photographs, but only once the new set is complete.
- A version that has a decision is not photographed again without `--force`, since that would change what was decided on.
- An id that names different content (a hash collision) is refused.

**Version record:**

| Field | What |
|---|---|
| `family`, `id`, `published` | |
| `maker`, `track`, `note` | Who made it, for example `Claude Fable 5.2` and `kit-1`, and what the pass changed |
| `source` | `commit`, `branch`, `dirty`, `generator`, `generator_sha256`, `generator_state` (`committed`, `modified` or `untracked`), `seed`, `params`. This is the version's identity. |
| `renderer` | `method` (`asset-view` is the game). For the game: `commit`, `dirty`, `key` (commit, plus a hash of uncommitted game changes), `env`, `hours`, `preset` (the preset's hash) and `repo` |
| `members[]` | `name`, `role` (`subject` or `control`), `token_kind` (`file`, `recipe` or `import`), `sha256`, `recipe` (the recipe's entry), `file` (the GLB kept in the media, for re-rendering), `stats` (glb.py: triangles by part, palette and more), `view` (the asset view's measured size and triangles), `report` (the generator's own entry), `shots[]`, `clips[]` |
| `media` | `media/<family>/<id>`, under the board's home |
| `baseline_render` | Where the publish photographed the accepted version again with its own renderer |
| `delivered[]` | Pages, notes or renders the track made itself, kept beside the media |

**Decision record:** `family`, `version`, `verdict` (`accept` or `reject`), `date`, `by`, `words` (the owner's own words), `note`, `scope` (what an accept means, for example `base`: start from it, not the bar), `recorded`, `recorded_by`.

The accepted version is the most recent accept that has not been followed by a reject of the same version. Decisions are ordered by date, then by the UTC time they were recorded. Two decisions never share a file.

The latest version is shown beside:
- the accepted version;
- when the latest is itself accepted, the version accepted before it;
- with nothing accepted, the version published before it, labelled "previous".

**Media:** `~/archive/asset-board/media/<family>/<id>/` holds:

- `<member>/<shot>.jpg`;
- `<member>/clips/*.mp4`;
- `files/<member>.glb` (the model files, up to 64 MiB each);
- `delivered/`;
- `vs/<accepted id>/` (its diffs, and the accepted models photographed again).

`records/` in the home mirrors every record. The pages read the union of the repository's records and the mirror, so the board shows every track's passes, even ones not yet merged.

## Running it

```bash
just living-board status                      # each family: accepted, latest, its state
just living-board families                    # each family's kind and member names
just living-board build                       # write the pages again
just living-board check                       # every link and image on the pages resolves
just living-board pack                        # ~/archive/deliverables/asset-board-YYYYMMDD.tar.gz
```

Open `~/archive/asset-board/index.html`. To view it on the laptop, copy the tarball over, unpack it, and open `asset-board/index.html`. `board.py check asset-board` checks an unpacked copy. The tarball leaves out the kept GLB files unless you pass `--with-files`.

### Publishing a pass (tracks)

From the track's own worktree, after the generator has written its files:

```bash
# One family, files:
python3 living/tools/board/board.py publish --family building:cone \
  --model cone=OUT/landmarks/cone.glb --report OUT/report.json \
  --generator living/tools/blender/cullet.py --seed 83 --maker "Claude Fable 5.2" --track kit-1 \
  --note "pass 1: the Cone from the plan's lot"

# One family, characters (recipes in the game's recipes.json), with the VRoid control:
python3 living/tools/board/board.py publish --family character:adult-man --kind character \
  --model man=recipe:cullet-man --control vroid=recipe:shino \
  --generator living/tools/blender/person.py --param variant=man --maker "Claude Fable 5.2" --track char-2 \
  --note "pass 1 on faces"

# Several families in one pass:
python3 living/tools/board/board.py publish --manifest pass.json
```

A manifest:

```json
{"generator": "living/tools/blender/cullet.py", "seed": 83, "params": {"plan": "living/seeds/worlds/cullet/plan.json"},
 "maker": "Claude Fable 5.2", "track": "kit-1", "note": "pass 1", "report": "OUT/report.json",
 "families": [
  {"family": "building:cone", "members": [{"name": "cone", "path": "OUT/landmarks/cone.glb"}]},
  {"family": "prop:strand", "members": [{"name": "bollard", "path": "OUT/strand/bollard.glb"}],
   "report_keys": {"bollard": "bollard_01"}, "delivered": [{"title": "kit-1 notes", "path": "OUT/notes.md"}]}]}
```

Paths are relative to the current directory. A family entry can override `generator`, `seed`, `params` or `note`. The generator's report entry for a member is found under `models[<key>]` or `[<key>]`. The key is the file's stem unless `report_keys` (or `--report-key MEMBER=KEY`) names it.

How publishing works:

- **Member names carry the comparison.** Keep the accepted version's names (`board.py families`, or the table below), so `row` is compared with `row`. A member that is new or missing is labelled as such, and a pass that shares no name with the previous version gets a warning.
- **Families must exist.** A family not yet on the board needs `--new-family` (or `"new": true` in the manifest entry), so a typo does not quietly start a new one.
- **Every shot must be taken.** A model that fails to load, or a shot the view did not take, stops the publish and records nothing, unless `--allow-missing` is given.
- **Commit the generator first.** The version records the commit and the generator's sha256. A generator that is modified or untracked is still recorded, with a warning and its state.
- **The report must match the files.** A report entry whose `sha256` is not the file's is left out, with a warning.
- **Then commit the new files in `living/assets/board/`** with the pass. Media goes to the shared home on its own.
- **The renderer.** Files are photographed by the game of the repository that holds `board.py`. This matters while the tool is reached by absolute path from an older worktree, because that worktree's game lacks the night lighting. Recipes are photographed by the publishing repository's game, since only it has the characters and the recipe book.
  - The renderer repository's game is built with at most 12 jobs. `CARGO_TARGET_DIR` is used only when the renderer is the publishing repository itself, so a track's own binary is never overwritten by another tree's game. Otherwise the build uses the renderer repository's `.local/target` if it exists, else `.local/board-target`. For characters, set `CARGO_TARGET_DIR` to the worktree's existing release target to avoid a second ~4-minute build.
  - `--game BIN` uses a binary you already have. It is identified by the binary's hash.
  - The photographs ignore the caller's `LIVING_GAME_*` settings. The preset sets the environment, hour, day curve and weather (always clear).
- **The accepted version is photographed again.** If it has kept files and was photographed by another renderer build, the publish photographs it again with this one, so the diff shows the models' change and not the renderer's. Imported versions and recipe characters cannot be photographed again: their page says the renderers differ.
- **Quick looks.** `--shots three-quarter,game` takes only those shots; `--no-clips` or `--clips walk-tq` limits character clips. A full character pass takes about four minutes a character, mostly clips.
- **Trial runs.** `ASSET_BOARD_HOME=… ASSET_BOARD_RECORDS=…` send the media and records elsewhere, to test without touching git or the real board.
- **Media made elsewhere** is recorded with `board.py import --family F --member NAME[:control]=PATTERN-with-{shot}` (with `--clip`, `--stats`, `--delivered`, and `--same-shots` when it uses the board's preset). The starting character versions were imported this way.

### Recording a decision (coordinators)

The owner looks at a family page and tells a coordinator "accept" or "reject", with their words. The page's decision box writes the command:

```bash
python3 living/tools/board/board.py decide building:cone latest accept \
  --words "the owner's words" --note "what was compared" --scope base --recorded-by "dev-box coordinator"
git add living/assets/board && git commit -m "board: building:cone accepted"
```

The version is a full id or a unique part of one. Use the id on the page the owner looked at. `latest` takes the newest version, which may have arrived since. `--date` (YYYY-MM-DD) defaults to today. The page's command quotes the words for the shell.

## Families and their starting versions (2026-11-11)

| Family | Members | Starting version | Accepted |
|---|---|---|---|
| `building:cone` | `cone` | Fable arm (`ab-arm1` @ `80b4ec94`, `living/tools/blender/ab/cullet_fable.py`, seed 1) | 2026-11-11, as the base: "they like Fable's results more in general" |
| `building:row-low` | `row` | same | same |
| `building:glasshouse` | `glasshouse` | same | same |
| `prop:strand` | `net_rack`, `barrels`, `creels`, `bollard`, `quay_lamp`, `boat`, `peat_stack`, `floats` | same | same |
| `character:adult-man` | `man`; controls `vroid`, `vroid-smith` | The character spike (`char-spike` @ `c3bc7e79`, `living/tools/blender/person.py`), imported from its page | 2026-11-11, as the base, not the bar: "It's a solid start, but we can and should do much better. …" |
| `character:adult-woman`, `character:elder-man`, `character:youth`, `character:boy`, `character:heavy-man` | `woman`, `elder`, `youth`, `boy`, `heavy`; control `vroid` | same | same |
| `character:cast-64` | `cast` (`lineup`, `faces`) | same, `cast.py` seed 64 | same |

- **The building kit:** the Fable arm's GLBs were photographed by the board in the game. Fable's own Blender renders and notes are kept with each version as delivered media.
- **The character families:** their target is the VRoid control's quality close up (docs/SMALL_CITY.md decision 2).
- **The building kit's acceptance** is a general preference after the Fable/Opus A/B (decision 12), not a sheet-by-sheet judgement.
