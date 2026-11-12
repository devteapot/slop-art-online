# Game interface verification map

This directory is the maintained source for verifying interface D in the game client (`living/game/src/ui/`). Read the index, then use the feature's file as the recipe.

| Feature | File | Scenario |
| --- | --- | --- |
| Windows: the two anchors, opening and replacing, dragging by the title bar and snapping, ✕, the window keys, the Esc order, Menu and its list | [windows.md](windows.md) | `check.py windows` |
| Talking: whom Enter addresses, the person window, Tab (another person, then everyone near), the log and people, introduce yourself, labels by looks, `heard_by` and `introduced` slots, mouths moving while lines are said (mine and a resident's answer) | [talking.md](talking.md) | `check.py talk` |
| Items on people: the pack, an item's acts, carrying an item onto someone's window or onto them, hold F › Give › | [items.md](items.md) | `check.py items` |
| What you stand on: a flight, a terrace, the quay's edge and a wall's top never fade under you; landmarks and far things are not faded for being in the way | [support.md](support.md) | `check.py support` on a Cullet world (`--seed cullet`) |
| Facing sight (`fov_on`): off draws no field; F5 or Settings › Play switches it through the admin link (`law_change` rows); the readout of the five values; the authority's perceived set against the client's field at four looks (`human_face`); a walking look held at 30° and the releases; heard marks per `heard_sounds` row | [field.md](field.md) | `check.py field` |
| Themes: Clear (default), Night, Linen, Walnut; F4 cycles, Settings › Play › Look sets, the settings file keeps; windows stay through a change | [themes.md](themes.md) | `check.py themes`; `LIVING_GAME_THEME=<t> check.py …` for each theme's stills |

| Themes: Glass (default), Clear, Night, Linen, Walnut; F4 cycles, Settings › Play › Look sets, the settings file keeps; windows stay through a change | [themes.md](themes.md) | `check.py themes`; `LIVING_GAME_THEME=<t> check.py …` for each theme's stills |
| The cluster and skill bar: the rules' places and looks, sheathe and draw (X), greyed with a reason, the rules' refusals, the held guard, the tooltip | [bar.md](bar.md) | `check.py bar`; `check.py own` (own outcomes) |
| Offers to me: a card per swap or proposal in the maker's window, Accept (the rules' skill on `offer`), refusals, Dismiss, a re-offer, terms | [offers.md](offers.md) | `check.py offers` |
| The wheel: hold F on a person or a fuel fire, the held cursor picks a section, let go; pinned sections grey in place with the rules' reason; Esc and the hub send nothing; flick, digits; the cursor back to the pixel | [wheel.md](wheel.md) | `check.py wheel`; `check.py wheel-workplace` on a Cullet world |
| The recipe grid: a way of making's products as cells, greyed with the rules' reasons, rows from the recipe, a cell sends the act | [grid.md](grid.md) | `check.py grid` on a Cullet world |
| Pools and the walk law: the bars from `meters()` (mana only while short), slots greyed by their pool's cost in the rules' words, Settings › Walk speed reading and writing `walk_base` | [pools.md](pools.md) | `check.py pools`; `check.py walk-law` |
| The cursor pick: who is under the cursor when two overlap on screen (the one drawn in front; stacked exactly, the nearer the camera, every frame), the same for the nameplate, Enter, a tap and combat's target | [talking.md](talking.md) (`pick`) | `check.py pick` |
| The cursor while the view turns or zooms: a two-finger pan, a pinch and a left drag keep the cursor at its screen position, and what it points at follows the view | [turns.md](turns.md) | `check.py turns` |
| Looking aside while walking: head, then chest, then the body on an eased curve; legs on the travel's takes; a sidestep only after a sudden turn; the three presets (Settings › Play › Looking aside) | [look-walk.md](look-walk.md) | `check.py look-walk` |
| A crowd of generated people: paged faces with their page's shadow map, the far model beyond 10 m, one shared clip file; people composed from type and style files (`LIVING_GAME_COMPOSE=1`), joint by joint against their whole files; draw counts, batches, asset memory and foot slide | [crowd.md](crowd.md) | look-dev, no world: `living/tools/characters/crowd.py` (`lod`, `town` and `composed` runs), `living/tools/characters/compose_check.py` |

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
