# Game interface verification map

This directory is the maintained source for verifying interface D in the game client (`living/game/src/ui/`). Read the index, then use the feature's file as the recipe.

| Feature | File | Scenario |
| --- | --- | --- |
| A crowd of generated people: paged faces with their page's shadow map, the far model beyond 10 m, one shared clip file; people composed from type, style and overlay files (the default; `LIVING_GAME_COMPOSE=0` draws whole files), joint by joint and colour by colour against their whole files, style materials shared by what they draw; draw counts, batches, asset memory and foot slide | [crowd.md](crowd.md) | look-dev, no world: `living/tools/characters/crowd.py` (`lod`, `town` and `composed` runs), `compose_check.py`, `colour_check.py` |
| Facing sight (`fov_on`): off draws no field; F5 or Settings › Play switches it through the admin link (`law_change` rows); the readout of the five values; the authority's perceived set against the client's field at four looks (`human_face`); a walking look held at 30° and the releases; heard marks per `heard_sounds` row | [field.md](field.md) | `check.py field` |
| Items on people: the pack, an item's acts, carrying an item onto someone's window or onto them, hold F › Give › | [items.md](items.md) | `check.py items` |
| Looking aside while walking: head, then chest, then the body on an eased curve; legs on the travel's takes; a sidestep only after a sudden turn; the three presets (Settings › Play › Looking aside) | [look-walk.md](look-walk.md) | `check.py look-walk` |
| Names on screen: one way to name a person (`Looks`), places and houses by kind, the death screen by the cause's kind; the guard: no seed name the player was not given | [names.md](names.md) | `check.py names` (Cullet); `check.py death`; `check.py houses`; `check.py shot` |
| Offers to me: a card per swap or proposal in the maker's window, Accept (the rules' skill on `offer`), refusals, Dismiss, a re-offer, terms | [offers.md](offers.md) | `check.py offers` |
| People drawn from their look (look-1): the projected key's line from the look book, composed; the VRoid fallback and its warnings; a new key redrawn in place; chips by piece from the style files' slot and layer; the prewarm; background people from decor | [looks.md](looks.md) | `check.py looks` (Cullet), `check.py looks-old` (island), `check.py looks-band` (a Cullet world at a lab pace, `looks_seed.py`) |
| Pools and the walk law: the bars from `meters()` (health, stamina and mana, always), slots greyed by their pool's cost in the rules' words, Settings › Walk speed reading and writing `walk_base` | [pools.md](pools.md) | `check.py pools`; `check.py walk-law` |
| Talking: whom Enter addresses, the person window, Tab (another person, then everyone near), the log and people, introduce yourself, labels by looks, `heard_by` and `introduced` slots, mouths moving while lines are said (mine and a resident's answer) | [talking.md](talking.md) | `check.py talk`; `check.py room-detail` (how a room line was said); `check.py earshot` (the authority's earshot); `check.py ways` (the world's ways of speaking); `check.py bubble-once` (a line shown once); `check.py unheard` (speech-truth: a line nobody could hear); `check.py far` (someone too far to make out) |
| The cluster and skill bar: the rules' places and looks, sheathe and draw (X), greyed with a reason, the rules' refusals, the held guard, the tooltip | [bar.md](bar.md) | `check.py bar`; `check.py own` (own outcomes); `check.py committed` (committed moves) |
| The cursor pick: who is under the cursor when two overlap on screen (the one drawn in front; stacked exactly, the nearer the camera, every frame), the same for the nameplate, Enter, a tap and combat's target | [talking.md](talking.md) (`pick`) | `check.py pick` |
| The cursor while the view turns or zooms: a two-finger pan, a pinch and a left drag keep the cursor at its screen position, and what it points at follows the view | [turns.md](turns.md) | `check.py turns` |
| The film (`post::Film`): Soft (the default; spares dark pixels by day, the screen at night), Full (the screen, as before film-1) and None; Settings › Play › Film sets it, the settings file keeps a choice once made, `LIVING_GAME_FILM` starts in one | [film.md](film.md) | `check.py film` |
| The hair shine (`style::HAIR_SHINES`): Crown (the default; a hard band over the crown, off a fringe), Soft and Today (the ring before hair-ring-1); Settings › Play › Hair shine sets it, the settings file keeps a choice once made, `LIVING_GAME_HAIR_SHINE` starts in one; the live script's `shine:` switches it in one view | [hair.md](hair.md) | `check.py hair` |
| The recipe grid: a way of making's products as cells, greyed with the rules' reasons, rows from the recipe, a cell sends the act | [grid.md](grid.md) | `check.py grid` on a Cullet world |
| The wheel: hold F on a person or a fuel fire, the held cursor picks a section, let go; pinned sections grey in place with the rules' reason; Esc and the hub send nothing; flick, digits; the cursor back to the pixel | [wheel.md](wheel.md) | `check.py wheel`; `check.py wheel-workplace` on a Cullet world |
| Themes: Glass (default), Clear, Night, Linen, Walnut; F4 cycles, Settings › Play › Look sets, the settings file keeps; windows stay through a change | [themes.md](themes.md) | `check.py themes`; `LIVING_GAME_THEME=<t> check.py …` for each theme's stills |
| What you stand on: a flight, a terrace, the quay's edge and a wall's top never fade under you; landmarks and far things are not faded for being in the way | [support.md](support.md) | `check.py support` on a Cullet world (`--seed cullet`) |
| Windows: the two anchors, opening and replacing, dragging by the title bar and snapping, ✕, the window keys, the Esc order, Menu and its list | [windows.md](windows.md) | `check.py windows` |

## Which feature a source file belongs to

| Source (`living/game/src/`) | Features |
| --- | --- |
| `anim.rs` (`clip_file`), `lookdev.rs` (far models, face maps) | [crowd.md](crowd.md) |
| `camera.rs`, `pointer.rs` | [turns.md](turns.md), [wheel.md](wheel.md) |
| `characters.rs` (`recolor`, `shape`, spring bones), `characters/compose.rs` (people composed from type, style and overlay files), `perf.rs` (`diag`'s `batches:`), `view.rs` (`LIVING_GAME_VIEW_JOINTS`, `LIVING_GAME_VIEW_PLATE`) | [crowd.md](crowd.md) |
| `combat.rs`, `weapon.rs` | [bar.md](bar.md) |
| `controls.rs` (the look), `facing.rs`, `heardmark.rs`, `sightedge.rs`, `sightfield.rs` | [field.md](field.md) |
| `envs.rs` (the cutaway fade) | [support.md](support.md) |
| `heard.rs`, `mouth.rs`, `pick.rs`, `talk.rs` | [talking.md](talking.md) |
| `keys.rs` (Settings › Controls) | [windows.md](windows.md), [bar.md](bar.md) |
| `live.rs`: the live script every drive runs through (SKILL.md), and how a walking body's legs and upper body turn | the harness for every feature; [look-walk.md](look-walk.md); `recipe_for`, `swap_look`: [looks.md](looks.md) |
| `characters/book.rs`, `characters/seen.rs`, `loading.rs` (the prewarm), `island.rs` (`person_recipe`) | [looks.md](looks.md) |
| `looks.rs` | [names.md](names.md), [looks.md](looks.md) (`clothes`, `place`) |
| `post.rs` (`post::Film`) | [film.md](film.md) |
| `style.rs` (`HAIR_SHINES`, `HairShine`), `toon.wesl` (`hair_light`) | [hair.md](hair.md) |
| `twist.rs` | [look-walk.md](look-walk.md) |
| `ui/*` (interface D) | every feature |
| `verbs.rs`, the skills' `_ui()` declarations | [items.md](items.md), [wheel.md](wheel.md), [grid.md](grid.md), [bar.md](bar.md), [offers.md](offers.md) |

## Baseline preconditions

- A scratch world from `$V launch --run ui-<…> --seed island` (Brackenford with residents, no mind service) and `$V doctor` passing.
- The release client built from this checkout into a private `CARGO_TARGET_DIR`.
- Each drive is a fresh client run that joins as `Verifier` with the run's own token (`ui/player.token`) and its own settings file. The character persists across drives of one run: after a drive, the world's minds take it over 30 s later (offline takeover), so it may have moved; scenes are set relative to wherever it stands.

## Driving conventions

- Click tagged nodes (`@win:Pack:close`), not coordinates; a tag is stable across layout changes.
- Check state from `dump:` files, and what was sent from the client log and the authority's rows. A photograph alone is not the proof. For every reducer call and its reply, give the drive `LIVING_GAME_ACTIONS=<file>` and read the JSON lines (docs/PLAY_REPORT.md, "The action log").
- Wait 0.3–0.6 s after a click or key before a dump or a photograph: windows spawn and lay out at the end of a frame.

## Proof and skip reporting

- Report the run name, the scenarios run, `checks.json`, and the photographs that show each feature.
- Say which entry points were not driven (a real trackpad, the system cursor, model answers).
