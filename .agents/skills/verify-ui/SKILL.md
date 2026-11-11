---
name: verify-ui
description: Verify Slop Art Online's game interface (interface D in living/game, Bevy, in its themes) by driving the real client headless through its live script (cursor, clicks, slides, keys, UI dumps) on scratch verify-ui-* worlds. Covers the windows (opening, moving and snapping between anchors, closing, the Esc order, Menu), the themes (F4, Settings › Play › Look, kept in the settings file), talking to a person (addressing, the person window, Log and people, introduce yourself), items on people (the pack, item acts, dragging onto someone, hold F › Give ›), what you stand on never fading (stairs, terraces, the quay's edge, on a Cullet world), the cursor while the view turns or zooms (a two-finger pan, a pinch, a left drag), facing sight (the field of view drawn from the world's fov_on law, its readout, the F5 and Settings switch through a play scene's admin link, the look sent through human_face, heard marks), looking aside while walking (head, then chest, then the body on a curve; the look-walk presets), and later the skill bar with sheathe and draw, and Settings. Use when changing living/game/src/ui/*, the camera's fade (envs.rs cutaway), camera.rs, keys.rs, looks.rs, heard.rs, sightedge.rs, sightfield.rs, facing.rs, heardmark.rs, controls.rs's look, talk.rs, verbs.rs, pointer.rs, twist.rs, how live.rs turns a walking body's legs and upper body, or the live script, or when the screen shows something other than what the client received.
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

- The island seed's newcomer arrives on Brackenford's square among residents. No mind service runs and no model is called: residents never answer, and the free tier is all there is.
- In a fresh worktree, link `living/game/assets/{lookdev,textures,view}` from the main checkout (`for d in lookdev textures view; do ln -s /Users/carlid/dev/slop-art-online/living/game/assets/$d living/game/assets/$d; done`). They are generated and git-ignored; without them the client draws no character models or textures, and `ready` can wait for a fitted character until `drive.py` times out.
- On the laptop, heavy builds go through `build-slot` (at most three at once).
- The client is ready when its log says `live script: ready after …`; `drive.py` waits for it.

## Drive

`scripts/drive.py` runs one headless client (`LIVING_GAME_LIVE`, `LIVING_GAME_LIVE_PLAN`) and keeps its evidence; `scripts/check.py` runs the scenarios with their checks.

```bash
S=.agents/skills/verify-ui/scripts
$S/check.py --run $R                       # all scenarios: field windows talk items themes pick turns look-walk (PASS/FAIL per check)
LIVING_GAME_THEME=night $S/check.py --run $R windows talk items   # the same in a theme; evidence in <scenario>-night/
$S/check.py --run $R windows               # one
$S/check.py --run $R support               # on a Cullet world (`--seed cullet`): what you stand on never fades
LOOK_WALK_PRESETS=chest LOOK_WALK_RECORD=1 $S/check.py --run $R look-walk   # one look-walk preset, recorded
$S/drive.py --run $R --name try --plan 'ready;wait:2;click:@menu;wait:0.5;shot:menu;dump:menu;quit'
```

The live script's steps for the UI (`living/game/src/live.rs`, its doc comment has them all):

| Step | Does |
| --- | --- |
| `click:@TAG` / `click:X,Y` | The cursor goes to a tagged node (or fractions of the picture), the left button goes down, then up: a click through `ui/hit.rs`, as the drawn cursor makes one |
| `slide:A>B[:SECS]` | Holds the click at A, slides to B, lets go: a title-bar drag, an item carried onto someone (a three-finger drag is the same press and move) |
| `key:NAME:tap\|down\|up` | Any key by its `KeyCode` name (`KeyI`, `Escape`, `Enter`, `Tab`, `Digit1`, `AltLeft`) |
| `type:TEXT`, `enter`, `tab`, `chat:open\|close` | Words in the box, said to whom it addresses; Tab; the box opened or closed (closing keeps its window) |
| `dump:NAME` | Writes `NAME.json`: open windows (top last) with anchors and rectangles, the Menu list, the list of acts, the box and whom it addresses, settings, every tagged node shown with its centre, and the cursor pick: `under` (who is under the cursor, `living/game/src/pick.rs`), `hovered` (id, label: the nameplates shown as hovered), `targeted` (the target plate) and `seen` (each body's feet and head on screen, its depth and its distance from the cursor's ground point) |
| `point:ID[:H]` | Keeps the game's cursor on character ID as drawn, H m above their feet (default 0.3; 1.3 is the chest), frame after frame, until `cursor:` or another `point:` |
| `menu:f@id:N`, `sync:NAME`, `shot:NAME`, `scroll:PX`, `dodge:W` | F's list on someone; wait for a scene; a photograph; two-finger scroll; a double tap |
| `walk:DEG:S`, `hold:DEG`, `stop`, `look:DEG`, `lookwalk:SPEC` | Walk a compass direction for S seconds, or hold it until `stop`; look a compass direction (the cursor scheme's look, until `look:`); set the look-walk preset (`twist::LookWalk::parse`: `chest`, `head,body_s=0.3`) |
| `cursor:X,Y`, `pan:PX`, `drag:PX`, `pinch:F`, `frame:0` | The cursor at fractions of the picture; a two-finger pan, a left drag or a pinch through the pointer's paths; no framing contexts (the dump's `extra.cursor`, `extra.view` and `extra.cursor_ground` show what they did) |

Tags (`ui/hit.rs` `Tag`; a tag that is the start of another finds it, so `@acts:0:give` finds `acts:0:give:3`):
- buttons and Menu: `pack`, `menu`, `menu:Character|Skills|Log|Settings|Leave`;
- windows: `win:<Win>:head`, `win:<Win>:close` with `<Win>` `Pack`, `Log`, `Skills`, `Settings` or `Person<ID>`;
- a person window: `person:give|wave|appraise|more:<ID>` (More… opens every act, Trade… and Introduce yourself among them), its Give rows `person:gift:<ID>:<I>`, and its box `input:Person<ID>` (the log's `input:Log`);
- the log: `log:tab:0|1|2` (Heard, People, Events), `log:person:<I>`;
- the list of acts: `acts:0:<skill>:<I>` (`talk`, `window`, `introduce`, `give`, `more`, …), its sub-list `acts:1:<item>:<I>`;
- the pack: `pack:<item>:<I>`; know-how: `skill:<I>`; the tip: `tip:ok`, `tip:all`;
- Settings: `settings:page:play|controls`, `settings:theme:clear|night|linen|walnut`, `settings:look_walk:head|chest|loose`, `settings:control:travel|cursor`, `settings:sight:unseen|limited|fade`, `settings:look:memory|grey|wash|lantern|shadows|hatch`, `settings:facing_sight` (the switch; shown only with the admin link), `settings:walk:2.6|3.0|3.4` (the walk law's choices; shown only with the admin link and the law in the script), `settings:auto_draw`, `settings:tips`, `settings:tips_again`, `settings:preset:letters|numbers|own`, `bind:<Act>:<slot>`.

Facing sight (`check.py field`, [features/field.md](features/field.md)): drive.py's `--admin-link` gives the client the world admin's token in a mode-600 file it deletes after the drive, as `play.py` does for a scene with `"law_toggle": true`; a `--sync NAME='sql|QUERY;…'` call snapshots the authority (owner SQL, `{me}`, `{ident}`) into `scene.json`'s `snaps`.

Scenes: `--place ID:DX:DY` puts a resident beside the player and holds them still when the plan reaches `sync:scene`; `--sync NAME='reducer|arg;…'` makes other admin calls at `sync:NAME`. Both are scene setup through admin reducers, never player acts; name them in a report.

## Evidence

Each drive writes `.local/living/verify/<run>/ui/<name>/`: the photographs (`shot:`), dumps (`dump:`), `client.log`, the feet log when `LIVING_GAME_FEET` names one (`look-walk` does: every frame's feet, gaits, the legs', hips', chest's and head's yaw, the twist asked, the look, and the authority's heading and segment), `plan.txt`, `scene.json` (the player's id and the admin calls) and `settings.json` (the run's own settings file: `LIVING_GAME_SETTINGS`, so the owner's `~/.config/slop-art-online/game.json` is never touched). `check.py` writes `ui/checks.json`. A proof of a UI change holds:

- **the action:** the plan (`plan.txt`) and the client log's lines for it (`ui: window Pack opened at Right`, `say: "…" to #57`, `verbs: berries let go on #57: give berries`);
- **the state:** the dumps before and after, and for anything sent, the authority's rows (`$V sql`: `experience` `said` rows, `inventory`);
- **the screen:** the photographs, at 1600×900 (the design's size).

Compare a photograph with the design's picture (`/Users/carlid/dev/slop-art-online/.local/living/ui-designs/png/d-*.png`) when the look changed.

## Cleanup

```bash
$V cleanup --run $R
```

It deletes `verify-<run>`; the evidence stays in `.local/living/verify/<run>/`. `drive.py` waits for its own client to quit (a plan ends with `quit`; a stuck client is stopped by its pid after `--timeout`). Never point a run at the paused reference worlds or at `verify-play*` worlds.

## Feature map

[features/README.md](features/README.md) lists the UI features and their recipes. [references/validation.md](references/validation.md) records the last real run.

## What this skill does not prove

- A real window, trackpad or system cursor: runs are headless, so the cursor is the script's. The capture, Esc giving the system cursor back and how winit reports a real two-finger pan or pinch need hardware (a play-test); `turns` drives what the pointer does with them.
- What residents answer: no mind service runs.
- That the rules handle what the UI sends correctly: use `verify-player` and `verify-core`.
- Frame time or scale.
