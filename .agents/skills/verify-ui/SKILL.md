---
name: verify-ui
description: "Verify Slop Art Online's game interface (interface D in living/game, Bevy) by driving the real client headless through its live script (cursor, clicks, keys, UI dumps) on scratch verify-ui-* worlds. Use when changing UI controls, windows or keys (living/game/src/ui and the input, camera and look code), talking, names on screen, items, the skill bar, the body's tooltip and the clock, offers, my family, courting offers and community, the wheel, the recipe grid, facing sight on screen, how characters are drawn or animated, themes, film or settings, or when the screen shows something other than what the client received."
---

# Verify the game interface

The game client (`living/game`) draws interface D: a small cluster, the compass and two buttons on screen, floating windows on two anchors, a window per person, the pack, and Settings (`docs/GAME_BRIEF.md`, "Interface D"). This skill clicks through it the way a player does, with the game's own cursor, in a headless window of the real client connected to a real scratch world.

Read the [`verify` entry point](../verify/SKILL.md) first: it owns launch, doctor, cleanup, the safety rules and the evidence standard. This skill adds the client driver and the scenarios. For anything a player's commands send (`human_say`, `human_act`, `use_skill`), also run [`verify-player`](../verify-player/SKILL.md): this skill shows that the UI sends them, not that the rules handle them right.

## Launch

```bash
V=.agents/skills/verify/scripts/verify.py; R=ui-$(date +%m%d-%H%M%S)   # run names start with ui-
$V launch --run $R --seed island --target-dir .local/living/verify/$R/target   # verify-ui-<...>, Brackenford with residents
$V doctor --run $R
export CARGO_TARGET_DIR=$PWD/.local/target            # a private target dir (other agents build too)
/Users/carlid/dev/slop-art-online/.local/bin/build-slot --label verify-ui cargo build --release --manifest-path living/Cargo.toml -p living-game
```

- The island seed's newcomer arrives on Brackenford's square among residents. No mind service runs and no model is called: residents never answer, and the free tier is all there is. The one exception is `reply-pace`, which starts `living-mind` for one resident against verify-llm's local fake model (`fake_llm.py`; no paid call): build it first (`cargo build --release -p living-mind` into the same `CARGO_TARGET_DIR`).
- In a fresh worktree, link `living/game/assets/{lookdev,textures,view}` from the main checkout (`for d in lookdev textures view; do ln -s /Users/carlid/dev/slop-art-online/living/game/assets/$d living/game/assets/$d; done`). They are generated and git-ignored; without them the client draws no character models or textures, and `ready` waits for a fitted character until it gives up at 240 s. Link the environment kits and the look book too (`for d in /Users/carlid/dev/slop-art-online/living/game/assets/envs/*/; do ln -s ${d%/} living/game/assets/envs/$(basename $d); done; ln -s /Users/carlid/dev/slop-art-online/living/game/assets/characters/looks.json living/game/assets/characters/looks.json`): without the kits `camera`'s market-stall cutaway never fires, and without the look book people are drawn as VRoid bases ("no look book" in client.log) and `camera`'s short middle hover fails (law-override-client, 2026-11-19).
- On the laptop, heavy builds go through `build-slot` (at most three at once).
- `drive.py` waits for the client's log to say `playing character #N` (the player's id), then reads each complete `live script: waiting for <path>` line in order. It matches the full `<evidence-dir>/NAME.go` path, including `scene.go` for `--place` and `--place-free`, and consumes the wait once before acknowledging it. Use a distinct name for each sync in a plan. The plan's own `ready` step waits in the client: until the island is drawn, the character has a body, the buildings round it are in, one person is fitted (when any is shown) and the loading cover has lifted, at least 2 s, or 240 s at most (`live.rs`).

## Drive

`scripts/drive.py` runs one headless client (`LIVING_GAME_LIVE`, `LIVING_GAME_LIVE_PLAN`) and keeps its evidence; `scripts/check.py` runs the scenarios with their checks.

The driver renews the scratch world's inactivity lease while the client runs. Scenarios fail early with `scratch world is paused` or `scratch world tick stationary` if the authority fails the health check at scenario start or before perception results are used.

```bash
S=.agents/skills/verify-ui/scripts
$S/drive.py --self-test                      # sync matcher regression, offline
$S/check.py --list                          # every scenario, in the order defined (each registers itself with @scenario); * needs a Cullet world
$S/check.py --run $R                       # ordinary island scenarios (PASS/FAIL per check)
LIVING_GAME_THEME=night $S/check.py --run $R windows talk items   # the same in a theme; evidence in <scenario>-night/
$S/check.py --run $R windows               # one
$S/check.py --run ui-<new> preparing       # launches its own island world and joins while it is made (features/preparing.md)
$S/check.py --run $R names                 # on a Cullet world (`--seed cullet`): no seed name the player was not given
$S/check.py --run $R support               # on a Cullet world (`--seed cullet`): what you stand on never fades
LOOK_WALK_PRESETS=chest LOOK_WALK_RECORD=1 $S/check.py --run $R look-walk   # one look-walk preset, recorded
$S/drive.py --run $R --name try --plan 'ready;wait:2;click:@menu;wait:0.5;shot:menu;dump:menu;quit'
```

The live script's steps for the UI (`living/game/src/live.rs`, its doc comment has them all):

| Step | Does |
| --- | --- |
| `click:@TAG` / `click:X,Y` | The cursor goes to a tagged node (or fractions of the picture), the left button goes down, then up: a click through `ui/hit.rs`, as the drawn cursor makes one |
| `slide:A>B[:SECS]` | Holds the click at A, slides to B, lets go: a title-bar drag, an item carried onto someone (a three-finger drag is the same press and move) |
| `key:NAME:tap\|down\|up` | A key by its `KeyCode` name: any in the bindings' table (`keys.rs` `KEYS`, `key_named`: letters, digits, `Space`, `Enter`, `Tab`, `Escape`, `Backspace`, shift, control, alt, `SuperLeft`, `CapsLock`, the arrows, punctuation, `F1`–`F8`), else `live.rs` `key_code`'s own short list; any other name is not a key |
| `type:TEXT`, `enter`, `tab`, `chat:open\|close` | Words in the box, said to whom it addresses; Tab; the box opened or closed (closing keeps its window) |
| `dump:NAME` | Writes `NAME.json`: open windows (top last) with anchors and rectangles, the Menu list, the list of acts, the box and whom it addresses (with `typing.earshot` and the last Tab, `typing.tab`), the notes shown, `me_at` (my drawn position and the authority's row) (and `naming`: every person- or place-naming text on screen, with `known_names`, `given_places` and `perceived`, the ids I perceive; `rects`: where the notes and the F prompt are drawn, UI px), settings with the weapon (`extra.drawn`), the bar's slots (`extra.slots`) and the tooltip (`extra.tooltip`), the Log's last 12 events (`extra.events`), every tagged node shown with its centre, `me` (the bars, the pills, and `body`: every `meters()` meter with its rules' word, as the body's tooltip gives them, with `body_tip`, the tooltip's text), `clock` (the clock chip: `hour`, `text`, `night`, `season`, `day`, `season_day`, `season_days`, `tip`; [features/body-clock.md](features/body-clock.md)), `kin` (my family's rows, community and courting cards as shown; [features/kin.md](features/kin.md)), and the cursor pick: `under` (who is under the cursor, `living/game/src/pick.rs`), `hovered` (id, label: the nameplates shown as hovered), `targeted` (the target plate) and `seen` (each body's feet and head on screen, its depth and its distance from the cursor's ground point), and `genesis` (staged genesis: the gate, the progress, the first-load cover's title, detail and bar, the link line and the errors the connection holds; [features/preparing.md](features/preparing.md)) |
| `point:ID[:H]` | Keeps the game's cursor on character ID as drawn, H m above their feet (default 0.3; 1.3 is the chest), frame after frame, until `cursor:` or another `point:` |
| `cursor:X,Y` / `cursor:@TAG` | The game's cursor there: fractions of the picture, or a tagged node (a slot, to hover it); `cursor:` takes it away |
| `pointat:X,Y[:H]`, `nudge:DX,DY`, `wheel:DIR` | The cursor kept on a world point (sim m); moved by logical px (an open wheel takes it as motion); an open wheel pointed at a direction |
| `weapon:toggle\|draw\|sheathe`, `tap` | As X; a left tap on the world (a strike, or talk to a peaceful person) |
| `menu:f[@AIM]\|c\|close\|N`, `sync:NAME`, `shot:NAME`, `scroll:PX`, `dodge:W` | F's list (on AIM, e.g. `f@id:57`), my own list (`c`), closing it, or picking row N; wait for a scene; a photograph; two-finger scroll; a double tap |
| `shine:NAME` | The hair shine (`crown`, `soft`, `today`) as Settings sets it, leaving open windows be (Settings would close them): to compare shines from one view |
| `light:NAME`, `rim:NAME` | The light (`classic`, `lookdev`) and the character rim (`off`, `subtle`, `strong`) as Settings sets them, leaving open windows be: before/after stills from one moment |
| `walk:DEG:S[:run]`, `hold:DEG[:run]`, `stop`, `look:DEG`, `lookwalk:SPEC` | Walk (or run) a compass direction for S seconds, or hold it until `stop`; look a compass direction (the cursor scheme's look, until `look:`); set the look-walk preset (`twist::LookWalk::parse`: `chest`, `head,body_s=0.3`) |
| `reconnect` | Closes the player socket so the regular reconnect path runs. |
| `heed:ID` / `heed:at:X,Y` | Asks the authority to pin character ID or pick out a throng member at `(X, Y)` (map m) as it is (heed for players), past the client's own checks, so the authority's refusal words show in the notes ([features/heed.md](features/heed.md)) |
| `preparing[:S]` | Waits until the client shows the world as still being made (staged genesis), at most S s (60): for photographs of the preparing cover ([features/preparing.md](features/preparing.md)) |
| `notches:N` | Sends a line-wheel event through the pointer. Positive zooms in over the world or scrolls the window under the cursor. |
| `pan:PX`, `drag:PX`, `pinch:F`, `frame:0` | A two-finger pan or left drag (Orbit turns), a pinch through either camera's zoom path, or disabling context framing (the dump's `extra.cursor`, `extra.view` and `extra.cursor_ground` show what they did) |
| `mouse:middle:down\|up`, `motion:DX,DY`, `rotate:DEG` | Middle-button input, one frame of mouse motion, and a clockwise native rotation message. Combine middle-button press, motion and release to drive the top-down drag threshold. |

Tags (`ui/hit.rs` `Tag`; a tag that is the start of another finds it, so `@acts:0:give` finds `acts:0:give:3`):
- buttons and Menu: `pack`, `menu`, `menu:Character|Skills|Log|Settings|Leave`;
- windows: `win:<Win>:head`, `win:<Win>:close` with `<Win>` `Pack`, `Log`, `Skills`, `Settings` or `Person<ID>`;
- a person window: `person:give|wave|appraise|more:<ID>` (More… opens every act, Trade… and Introduce yourself among them), its Give rows `person:gift:<ID>:<I>`, its offer cards' acts `person:offer:<ID>:<CARD>:<ACT>` (ACT 0 is the first skill on `offer`, Accept) and `person:dismiss:<ID>:<CARD>`, a courting card's acts `person:bond:<ID>:<ACT>` (ACT 0 is the first skill on `bond`, shipped `conceive`), and its box `input:Person<ID>` (the log's `input:Log`);
- the cluster: `bar:Primary|Secondary|Skill1|Skill2|Skill3|Jump|Dodge|Weapon|Extra4…Extra9`, and `body` (the meters' row: hovered, the body's tooltip);
- the clock: `clock` (left of the compass: hovered, the day's tooltip);
- the log: `log:tab:0|1|2` (Heard, People, Events), `log:person:<I>`, and on People my family's rows `log:kin:<I>` and my community `log:community` ([features/kin.md](features/kin.md));
- the list of acts: `acts:0:<skill>:<I>` (`talk`, `window`, `introduce`, `give`, `more`, …), its sub-list `acts:1:<item>:<I>`;
- the pack: `pack:<item>:<I>`; know-how: `skill:<I>`; the tip: `tip:ok`, `tip:all`;
- Settings: `settings:page:play|controls|rotation|camera`, `settings:facing:cursor|natural`, `settings:camera:top-down|orbit`, `settings:theme:glass|clear|night|linen|walnut`, `settings:look_walk:head|chest|loose`, `settings:control:travel|cursor`, `settings:sight:unseen|limited|fade`, `settings:look:shade|memory|grey|wash|lantern|shadows|hatch`, `settings:film:soft|screen|off`, `settings:hair:crown|soft|today`, `settings:light:classic|lookdev`, `settings:char_rim:off|subtle|strong`, `settings:facing_sight` (the switch; shown only with the admin link), `settings:walk:2.6|3.0|3.4` (the walk law's choices; shown only with the admin link and the law in the script), `settings:auto_draw`, `settings:combat_timing:live|old`, `settings:windup_glint`, `settings:throng` (shown only while heed for players is on), `settings:tips`, `settings:tips_again`, `settings:quality:low|medium|high`, `settings:render_scale:67|75|85|100|auto`, `settings:preset:letters|numbers|own`, `bind:<Act>:<slot>`.

Facing sight (`check.py field`, [features/field.md](features/field.md)): drive.py's `--admin-link` gives the client the world admin's token in a mode-600 file it deletes after the drive, as `play.py` does for a scene with `"law_toggle": true`; a `--sync NAME='sql|QUERY;…'` call snapshots the authority (owner SQL, `{me}`, `{ident}`) into `scene.json`'s `snaps`. Use `client_sql|QUERY` in a sync to snapshot a view as the game client identity.


Scenes: `--sync NAME='player|REDUCER|ARG|…'` acts as verify.py's player identity (`$V player join`), a second player beside mine (look-walk's others case). `--place ID:DX:DY` puts a resident beside the player and holds them still when the plan reaches `sync:scene`; `--place-free ID:DX:DY` puts one near that offset on a free walkable tile 1.5–3 m from the player with nothing opaque between (`scene.json` `free_spots`), and `--sync NAME=refree` puts them back there; `--sync NAME='reducer|arg;…'` makes other admin calls at `sync:NAME` (`{me}` the player's id, `(expr)` a Python expression of `mx`, `my` and `me`; in `sql|` snapshots also `{ident}`, `{epoch_at:HOUR}`, the world epoch that makes the hour HOUR now, `{epoch_at:HOUR:DAY}`, HOUR of the world's day DAY (a season), and `{now_ms}`, the authority's time (a vitals row's `at_ms`)). All are scene setup through admin reducers, never player acts; name them in a report.

drive.py's other options (its docstring): `--expect REGEX` (repeatable) must match client.log, else exit 1; `--size WxH` (default `1600x900`); `--token FILE` plays another character (default the run's `ui/player.token`); `--player NAME` (default "Verifier"); `--client PATH` (default `$CARGO_TARGET_DIR/release/living-game`, else `.local/target/release/living-game`); `--admin-link` (above); `--timeout S` (default 600; check.py passes 420); `--preparing` skips the start's tick check, for a client started while the world is still being made (`check.py preparing`). `LIVING_GAME_CLIENT_SERVER` (environment) points the client alone at another server URL, such as a byte-counting relay in front of the world's server (`check.py battle-views-cost`); the harness's own calls still go direct. `LIVING_STDB_URL` points it at a worker's own server (default `http://127.0.0.1:3300`).

Pass `camera`, `camera-rotate`, `camera-lod`, `camera-faces`, `camera-tuning`, `camera-lol` or `camera-lol-ridge` explicitly for the dedicated Brackenford fixtures in [camera.md](features/camera.md).

`seat` sits skirted and coated residents on the ground in the crowded street for about 18 s, across two of the authority's rest renewals and a Far → Near → Far → Near zoom. It checks that nobody seated rises or has a spring wake pop before `sync:up` sends them home (the feet log, `seat: #ID gets up` lines, `springwake`), then their unassisted rise. It runs with cloth ground contact on and off (`LIVING_GAME_SEAT_CONTACT=0`; the hem against the ground, `LIVING_GAME_SEAT_HEM`, is on in both and has no effect without the contact) and logs the lowest seated cloth tails and spring wakes (`LIVING_GAME_PERF=seat,springwake`). It also checks that each sitter plays the ground clips its look line selects (the female ground sit's `_f` variants for adults in `trousers-f` and `boots-f`; `LIVING_GAME_CLIP_VARIANTS=0` turns the selection off) and records one variant sitter's frames: [seat.md](features/seat.md).

Pass `law-override` on a fresh island world (made at or after cover-stall, `c83ee5d1`) to set each value-only law (`cue_transport_on`, `near_tier_on`, `gaze_on`, the `cover_*` laws) while a client plays, with the client's reaction, the time until `cover_law` reads each cover change in force, the unchanged script revision, the make-before-break delivery switch and the world's tick gap per call, an ordinary law's full install, and a reconnect and a fresh client with the rows present. [Law overrides](features/law-override.md).

Pass `battle-views`, `battle-views-ui` and `battle-views-cost` on an island world for the copy tables (`motion_tables_on`, `characters_table_on`): the live switch through every combination with the frame-tier laws, the kill switch by row, a reconnect and a fresh client; camera, talk and far with both on; kB/s and near ages on against off through a byte-counting relay. [The copy tables](features/battle-views.md).

Pass `combat-switches`, `combat-switches-death`, `combat-switches-ui` and `combat-switches-cost` on an island world for the fighter table and the combat feed (`fighter_tables_on`, `combat_feed_on`): the live switch beside a fight through the combinations with the frame tiers and the copy tables, the kill switch by row, no fighter or event missing, a reconnect and a fresh client; the death screen the same from `my_combat` and `combat_feed`; camera, talk, far and the combat scenarios with both on; kB/s and near ages on against off. [Combat switches](features/combat-switches.md).

Pass `heed-throng`, `heed-pins` and `heed-refusal` on an island world, after the ordinary scenarios (`heed-throng` leaves a 200-fighter battle's remains by the arrival), for heed for players: `seen_throng` subscribed only while `heed_on` and `heed_players` are both on, the throng drawn as figures per row, pins (T), clear (Y), focus and the authority's refusal words. [Heed for players](features/heed.md).

Pass `windup` on an island world for combat clip timing (`settings:combat_timing:live|old`, default `live`) and the hostile windup midpoint glint (`settings:windup_glint`, default off): with defaults, hostile windup clips start during the windup before release and no glint shows; with `old`, clips wait for `scene.now_ms` as on main; with `windup_glint` on, one glint fires per hostile windup at `f >= 0.5` (`extra.glints` and `client.log`), never for my own character. [The cluster and skill bar](features/bar.md).

Pass `gaze` on a Cullet scratch world to exercise the zoom bands, reconnect and the authored hedge. [Gaze evidence and setup](features/gaze.md).

Developer camera controls (`LIVING_GAME_DEV=1`): `settings:camera_preset:ours-fixed|ours|supervive|lol|corepunk`, `settings:camera_pitch:curve|fixed|late`, `settings:camera_slider:height|pitch|fov:far|middle|near`, `settings:camera_slider:pitch:fixed`, `settings:camera_slider:tilt_start|near_pitch|wheel|easing` and `settings:camera_copy`. The tuning drive exports `camera-tuning.json` beside its `settings.json`, including the current bearing. Settings › Camera (`settings:page:rotation`) uses `settings:camera_rotate`, `settings:camera_rotate_speed:0.5|1|2`, and `settings:camera_rotate_invert`. The north snap binding is `bind:NorthUp:0`.

## Evidence

Each drive writes `.local/living/verify/<run>/ui/<name>/`: the photographs (`shot:`), dumps (`dump:`), `client.log`, the feet log when `LIVING_GAME_FEET` names one (also the body `LIVING_GAME_FEET_ID` names, each line with its `id`; `look-walk` does: every frame's feet, the hips' place (`hips_at`), gaits, the legs', hips', chest's and head's yaw, the twist asked, the look, and the authority's heading and segment), `plan.txt`, `scene.json` (the player's id and the admin calls) and `settings.json` (the run's own settings file: `LIVING_GAME_SETTINGS`, so the owner's `~/.config/slop-art-online/game.json` is never touched). `check.py` writes `ui/checks.json`. A proof of a UI change holds:

- **the action:** the plan (`plan.txt`) and the client log's lines for it (`ui: window Pack opened at Right`, `say: "…" to #57`, `verbs: berries let go on #57: give berries`);
- **the state:** the dumps before and after, and for anything sent, the authority's rows (`$V sql`: `experience` `said` rows, `inventory`);
- **the screen:** the photographs, at 1600×900 (the design's size).

Compare a photograph with the design's picture (`/Users/carlid/dev/slop-art-online/.local/living/ui-designs/png/d-*.png`) when the look changed.

## Cleanup

```bash
$V cleanup --run $R
```

It deletes `verify-<run>`; the evidence stays in `.local/living/verify/<run>/`. `drive.py` waits for its own client to quit (a plan ends with `quit`; a stuck client is stopped by its pid after `--timeout`). Whatever ends a drive (a scene's error, SIGTERM, SIGHUP) stops its client by its pid; a drive killed outright leaves a client that quits by itself within a second once its parent is gone (`live.rs`, "my launcher … is gone" in client.log). Never point a run at the paused reference worlds or at `verify-play*` worlds.

## Feature map

[features/README.md](features/README.md) lists the UI features and their recipes. [references/validation/](references/validation/README.md) holds one record per real run; the newest files are the last validated runs.

## The client's unit tests

`just living-check` runs `cargo test --release -p living-game` (its `game-tests` step), headless: no display, GPU or generated assets. A test it cannot run, or a known red one, goes in `GAME_TEST_SKIPS` in `living/tools/check.py` with its reason, and in this list, so it is run here by hand (`cargo test --release -p living-game -- --exact NAME`). No test needs a display: all ran headless on the Spark without assets (2026-11-12). Skipped: none.

`ik::spots::uneven_ground_spots` is `#[ignore]`d in the source: a tool that lists photo spots (`-- --ignored uneven_ground_spots --nocapture`), not a check.

## In the scene gate

The merge's scene gate runs `looks`, `hair` and `seat` when a merge changes how characters are drawn, `camera-faces`, `camera-lod` and `far` when it changes the camera, LOD or sight, `body-clock` when it changes the HUD (`living/game/src/ui/**` or `features/body-clock.md`), and all seven for a shader, the client's manifest or these drivers, on dev-box's pinned render asset set (`living/tools/render_set.py`), and `render-smoke` on a host without one ([verify's "Scene gate"](../verify/SKILL.md#scene-gate), docs/TOOLING.md "The render group"). Its runs are `gate-*` on `verify-gate-*` worlds, which `check.py` and `drive.py` accept beside `ui-*`. A change to these scenarios' names, worlds or what they need changes the gate: keep `CASES` in `scene_gate.py` in step. A case's client logs fail it on shader, pipeline, `bevy_asset` or panic ERROR lines, so a scenario that provokes one on purpose must say so there.

## What this skill does not prove

- A real window, trackpad or system cursor: runs are headless, so the cursor is the script's. The capture, Esc giving the system cursor back and how winit reports a real two-finger pan or pinch need hardware (a play-test); `turns` drives what the pointer does with them.
- What residents answer: no mind service runs (`reply-pace` runs one on a fake model, for when a reply's bubble shows, not for what a model would say).
- That the rules handle what the UI sends correctly: use `verify-player` and `verify-core`.
- Frame time or scale.
