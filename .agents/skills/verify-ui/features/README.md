# Game interface verification map

This directory is the maintained source for verifying interface D in the game client (`living/game/src/ui/`). Read the index, then use the feature's file as the recipe.

| Feature | File | Scenario |
| --- | --- | --- |
| The cluster and skill bar: the rules' places and looks, sheathe and draw (X), greyed with a reason, the rules' refusals, the held guard, the tooltip | [bar.md](bar.md) | `check.py bar`; `check.py own` (own outcomes); `check.py committed` (committed moves); `check.py move-off` (broken off by moving; gestures on the move) |
| The copy tables on a connected client (battle-views): `seen_body_copy` for bodies and `seen_character_copy` for characters while `motion_tables_on` and `characters_table_on` are on, in place of the views; the switch made before broken in every combination with the frame-tier laws; the kill switch by row; a reconnect and a fresh client take the tables first; camera, talk and far with both on; kB/s and near ages on against off | [battle-views.md](battle-views.md) | `check.py battle-views`, `check.py battle-views-ui`, `check.py battle-views-cost` (island, explicit) |
| Camera in play: follow, bearing and north snap, wheel and pinch zoom, stable cursor look while zooming, world picking, personal Shade at each stop, and live developer tuning with JSON export | [camera.md](camera.md) | `check.py camera`; `check.py camera-rotate`; `check.py camera-tuning`; `check.py camera-lol`; `check.py camera-lol-ridge`; `check.py camera-lod` |
| Cover hides residents from the camera and cursor, with matching Shade and canopy cutaway checks | [cover.md](cover.md) | `check.py cover` (Cullet) |
| A crowd of generated people: paged faces with their page's shadow map, the far model beyond 10 m, one shared clip file; people composed from type, style and overlay files (the default; `LIVING_GAME_COMPOSE=0` draws whole files), joint by joint and colour by colour against their whole files, style materials shared by what they draw; draw counts, batches, asset memory and foot slide; the cost of composed files' `slop` (contract v1.3) against main's files and `LIVING_GAME_COMPOSED_SLOP=off` | [crowd.md](crowd.md) | look-dev, no world: `living/tools/characters/crowd.py` (`lod`, `town` and `composed` runs), `compose_check.py`, `colour_check.py`, `check.py skirt-scale` (spring skirts on scaled bodies) |
| Facing sight (`fov_on`): off draws no field; F5 or Settings › Play switches it through the admin link (`law_change` rows); the readout of the five values; the authority's perceived set against the client's field at four looks (`human_face`); a walking look held at 30° and the releases; heard marks per `heard_sounds` row | [field.md](field.md) | `check.py field` |
| The film (`post::Film`): Soft (the default; spares dark pixels by day, the screen at night), Full (the screen, as before film-1) and None; Settings › Play › Film sets it, the settings file keeps a choice once made, `LIVING_GAME_FILM` starts in one | [film.md](film.md) | `check.py film` |
| Gaze from the zoom target: Far, Middle and Near, authority-confirmed Shade, coalescing, reconnect and the Cullet hedge | [gaze.md](gaze.md) | `check.py gaze` (Cullet) |
| The recipe grid: a way of making's products as cells, greyed with the rules' reasons, rows from the recipe, a cell sends the act | [grid.md](grid.md) | `check.py grid` on a Cullet world |
| The hair shine (`style::HAIR_SHINES`): Crown (the default; a hard band over the crown, off a fringe), Soft and Today (the ring before hair-ring-1); Settings › Play › Hair shine sets it, the settings file keeps a choice once made, `LIVING_GAME_HAIR_SHINE` starts in one; the live script's `shine:` switches it in one view. Hand-made character GLBs can opt into explicit material slots, forward-axis handling, a hair palette and ink lines on any slot (`slop.ink`, contract v1.2) through `extras.slop`; composed type and style files opt in too (contract v1.3): a palette relative to each person's hair tag, the shared hair-mask and ink pages, hero files | [hair.md](hair.md) | `check.py hair` for live presets, `just living-game-calibrate view/<file>.glb` for hand-made asset-view shots, colour checks and the ink audit, `calibrate.py <composed file> --no-run` and `calibrate.py --pages lookdev` for composed files, `ink_shimmer.py` (`look:<key>` for a composed person) for ink shimmer |
| Items on people: the pack, an item's acts, carrying an item onto someone's window or onto them, hold F › Give › | [items.md](items.md) | `check.py items` |
| Law overrides on a connected client: `law_override` in the base set, laid over the compiled script in place for a value-only law (delivery, gaze, cover; no compile, the script revision kept), compiled with the rows on an install; the delivery switch made before broken; a reconnect and a fresh client take the rows before a set is chosen | [law-override.md](law-override.md) | `check.py law-override` (island, explicit) |
| Looking aside while walking: Cursor snaps the local body to the look and strafes or backpedals. Natural follows from head to chest to legs, with three Looking aside choices | [look-walk.md](look-walk.md) | `check.py look-walk`; `check.py reversal` (no brief backwards gait at a reversal) |
| Other characters in motion: the player's near and far body, fighter and doing views with transient cues; a tier change replaces a cue for that stream | [look-walk.md](look-walk.md) | `check.py look-walk` (others case); `check.py reversal`; SDK delivery and viewer scope via [verify-client](../../verify-client/SKILL.md) (`cues.py`) |
| People drawn from their look (look-1): the projected key's line from the look book, composed; the VRoid fallback and its warnings; a new key redrawn in place; chips by piece from the style files' slot and layer; the prewarm; background people from decor; a hero line's `hero_file` drawn as its hand-made file (contract v1.3) | [looks.md](looks.md) | `check.py looks` (Cullet), `check.py looks-old` (a world without looks, `looks_seed.py --old`), `check.py looks-band` (a Cullet world at a lab pace, `looks_seed.py`) |
| Names on screen: one way to name a person (`Looks`), places and houses by kind, the death screen by the cause's kind; the guard: no seed name the player was not given | [names.md](names.md) | `check.py names` (Cullet); `check.py death`; `check.py houses`; `check.py shot` |
| Offers to me: a card per swap or proposal in the maker's window, Accept (the rules' skill on `offer`), refusals, Dismiss, a re-offer, terms | [offers.md](offers.md) | `check.py offers` |
| Pools and the walk law: the bars from `meters()` (health, stamina and mana, always), slots greyed by their pool's cost in the rules' words, Settings › Walk speed reading and writing `walk_base` | [pools.md](pools.md) | `check.py pools`; `check.py walk-law` |
| A world still being made (staged genesis): the `genesis` row subscribed on its own, the base set and `join` held until `done`, the cover's "Preparing the world…" with step, steps, label and a bar, `world_preparing` refusals held quietly and `join` sent again on `done` or a backoff, the join timed from `done` | [preparing.md](preparing.md) | `check.py preparing` (explicit: launches its own island world under a new run name) |
| Seated cloth on the ground (seat-2a): a resident resting outdoors sits (`sit_ground_down`, `sit_ground`) and gets up where it sat (`stand_up_ground`); its `Skirt` and `Coat` spring groups keep to a ground plane at the seat, weighted by the clips' time; released once up; it stays seated across the authority's rest renewals and a far/near zoom (no rise, no turn take, no spring pop); no swing when its springs wake seated; the contact on against off with eight near; the asset view seats a model for side stills | [seat.md](seat.md) | `check.py seat` |
| What you stand on: a flight, a terrace, the quay's edge and a wall's top never fade under you; landmarks and far things are not faded for being in the way | [support.md](support.md) | `check.py support` on a Cullet world (`--seed cullet`) |
| Talking: whom Enter addresses, the person window, Tab (another person, then everyone near), the log and people, introduce yourself, labels by looks, `heard_by` and `introduced` slots, mouths moving while lines are said (mine and a resident's answer) | [talking.md](talking.md) | `check.py talk`; `check.py room-detail` (how a room line was said); `check.py earshot` (the authority's earshot); `check.py ways` (the world's ways of speaking); `check.py bubble-once` (a line shown once); `check.py reply-pace` (a reply's bubble at speaking pace, with a mind on the fake model); `check.py unheard` (speech-truth: a line nobody could hear); `check.py far` (someone too far to make out) |
| The cursor pick: who is under the cursor when two overlap on screen (the one drawn in front; stacked exactly, the nearer the camera, every frame), the same for the nameplate, Enter, a tap and combat's target | [talking.md](talking.md) (`pick`) | `check.py pick` |
| Themes: Glass (default), Clear, Night, Linen, Walnut; F4 cycles, Settings › Play › Look sets, the settings file keeps; windows stay through a change | [themes.md](themes.md) | `check.py themes`; `LIVING_GAME_THEME=<t> check.py …` for each theme's stills |
| The cursor while the view turns or zooms: a two-finger pan, a pinch and a left drag keep the cursor at its screen position, and what it points at follows the view | [turns.md](turns.md) | `check.py turns` |
| The wheel: hold F on a person or a fuel fire, the held cursor picks a section, let go; pinned sections grey in place with the rules' reason; Esc and the hub send nothing; flick, digits; the cursor back to the pixel | [wheel.md](wheel.md) | `check.py wheel`; `check.py wheel-workplace` on a Cullet world |
| Windows: the two anchors, opening and replacing, dragging by the title bar and snapping, ✕, the window keys, the Esc order, Menu and its list | [windows.md](windows.md) | `check.py windows` |

## Which feature a source file belongs to

| Source (`living/game/src/`) | Features |
| --- | --- |
| `anim.rs` (`clip_file`), `lookdev.rs` (far models, face maps) | [crowd.md](crowd.md) |
| `camera.rs`, `pointer.rs` | [camera.md](camera.md), [gaze.md](gaze.md), [turns.md](turns.md), [wheel.md](wheel.md) |
| `characters.rs` (`SeatAnchor`, `CLOTH_GROUPS`, the springs' seat contact), `anim.rs` (`ground_seat`, `seat_of`), `live.rs` (`seat_anchor`), `view.rs` (a ground clip's shot seated) | [seat.md](seat.md) |
| `characters.rs` (`recolor`, `shape`, spring bones), `characters/compose.rs` (people composed from type, style and overlay files), `perf.rs` (`diag`'s `batches:`), `view.rs` (`LIVING_GAME_VIEW_JOINTS`, `LIVING_GAME_VIEW_PLATE`) | [crowd.md](crowd.md) |
| `combat.rs`, `weapon.rs`, `town.rs` (my gestures, theirs drawn) | [bar.md](bar.md) |
| `controls.rs` (the look), `facing.rs`, `heardmark.rs`, `sightedge.rs`, `sightfield.rs` | [field.md](field.md), [gaze.md](gaze.md) |
| `genesis.rs`, `loading.rs` (the preparing cover), `net.rs` (`watch_genesis`, the `genesis` subscription, `world_preparing` in `on_reply`) | [preparing.md](preparing.md) |
| `envs.rs` (the cutaway fade) | [support.md](support.md) |
| `heard.rs`, `mouth.rs`, `pick.rs`, `talk.rs` | [talking.md](talking.md) |
| `keys.rs` (Settings › Controls) | [camera.md](camera.md), [windows.md](windows.md), [bar.md](bar.md) |
| `live.rs`: the live script every drive runs through (SKILL.md), and how a walking body's legs and upper body turn | the harness for every feature; [look-walk.md](look-walk.md); `recipe_for`, `swap_look`: [looks.md](looks.md) |
| `characters/book.rs`, `characters/seen.rs`, `loading.rs` (the prewarm), `island.rs` (`person_recipe`), `characters/compose.rs` (`hero_file`, `prepare`) | [looks.md](looks.md) |
| `looks.rs` | [names.md](names.md), [looks.md](looks.md) (`clothes`, `place`) |
| `net.rs` (perception tiers and cue overlays; owner subscription, gaze replies and reconnect; `law_override` and `law_rows`; `Feed`, `Copies` and the readers `characters`, `find_character`, `find_motion`, `bodies`) | [look-walk.md](look-walk.md), [talking.md](talking.md), [bar.md](bar.md), [gaze.md](gaze.md), [law-override.md](law-override.md), [battle-views.md](battle-views.md) |
| `post.rs` (`post::Film`) | [film.md](film.md) |
| `characters/palette.rs` (the relative palette, palette tags), `characters/compose.rs` (`Composer::toon`: composed files' `slop`), `handmade.rs` (`composed_of`, `composed_material`, `ComposedSlop`), `handmade.rs` (scene metadata, material slots, forward turn, `InkProfile`, `ink_map`), `lookdev.rs` (material assignment, ink carriers), `view.rs` (asset-view turn), `style.rs` (`HAIR_SHINES`, `Kind::HandHair`, `ToonExt::ink`), `toon.wesl` (`hand_hair`, `ink_cover`), `toon_light.wesl`, `living/tools/characters/calibrate.py`, `composed_audit.py`, `palette.py`, `composed_fixture.py`, `ink_field.py`, `ink_shimmer.py`, `hair_shimmer.py`, `pictures.py` (`ink`, `hairmask`) | [hair.md](hair.md) |
| `twist.rs` | [look-walk.md](look-walk.md) |
| `ui/*` (interface D) | every feature |
| `verbs.rs` (`Rules`: the compiled script, `laws_key`, `refresh_rules`) | [law-override.md](law-override.md) |
| `verbs.rs`, the skills' `_ui()` declarations | [items.md](items.md), [wheel.md](wheel.md), [grid.md](grid.md), [bar.md](bar.md), [offers.md](offers.md) |

## Baseline preconditions

- A scratch world from `$V launch --run ui-<…> --seed island` (Brackenford with residents, no mind service) and `$V doctor` passing.
- The release client built from this checkout into a private `CARGO_TARGET_DIR`.
- Each drive is a fresh client run that joins as `Verifier` with the run's own token (`ui/player.token`) and its own settings file. The character persists across drives of one run: after a drive, the world's minds take it over 30 s later (offline takeover), so it may have moved; scenes are set relative to wherever it stands.

## Driving conventions

- Gaze, cover, looks, looks-band and camera return fixture residents to their saved locations using `place_at` and reinstall their previous behavior graphs, including after a failed drive. `place_at` uses the nearest free walkable tile. The authority resumes normal simulation from there.

- Click tagged nodes (`@win:Pack:close`), not coordinates; a tag is stable across layout changes.
- Check state from `dump:` files, and what was sent from the client log and the authority's rows. A photograph alone is not the proof. For every reducer call and its reply, give the drive `LIVING_GAME_ACTIONS=<file>` and read the JSON lines (docs/PLAY_REPORT.md, "The action log").
- Wait 0.3–0.6 s after a click or key before a dump or a photograph: windows spawn and lay out at the end of a frame.

## Proof and skip reporting

- Report the run name, the scenarios run, `checks.json`, and the photographs that show each feature.
- Say which entry points were not driven (a real trackpad, the system cursor, model answers).
