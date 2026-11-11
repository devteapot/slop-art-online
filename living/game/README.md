# Camera and controls spike

A throwaway desktop client for choosing the game's camera and controls ([game brief](../../docs/GAME_BRIEF.md)). It joins a living world as a human player with its own identity and draws the authority's tile world in 3D. It is not the start of the client's architecture.

## Run

The spike needs a running world. Use a scratch world from the verify harness, never a paused lab or reference world:

```bash
V=.agents/skills/verify/scripts/verify.py
python3 $V launch --run game-1 --seed stage3-village   # SpacetimeDB container + fresh verify-game-1
cargo run --manifest-path living/Cargo.toml --release -p living-game   # from the repository root, with:
#   LIVING_DB=verify-game-1  LIVING_GAME_NAME=YourName
python3 $V cleanup --run game-1                          # when done
```

| Variable | Default | Meaning |
|---|---|---|
| `LIVING_SERVER` | `http://127.0.0.1:3300` | SpacetimeDB |
| `LIVING_DB` | `living` | database to join |
| `LIVING_GAME_NAME` | `Wanderer` | your character's name on first join |
| `LIVING_GAME_TOKEN` | `.local/living/game/<db>.token` | where your identity token is kept, so you return to the same character |
| `LIVING_GAME_DEMO` | unset | a directory: run the scripted demo, write screenshots there, then quit |

## Look-dev mode

`LIVING_GAME_LOOKDEV=1` runs a small fixed scene without the server, for judging the look on real models:
- every `.glb`/`.gltf` in `living/game/assets/lookdev/` (git-ignored) is laid out in an arc beside a 1.75 m reference figure;
- each model is converted to the shared toon material and outlined;
- the game camera works as in play, and F1 → Look dev sets the sun's hour.

Each model is scaled to a 1.75 m character from its bounds and faces the camera (VRM models are turned, since they face −Z).
- **Skin:** materials named …_SKIN (VRoid's convention) get lighter, warmer skin shadows.
- **VRoid characters:** they are animated procedurally from their standard `J_Bip_*` bones and `Fcl_*` face blend shapes:
  - arms lowered out of the T-pose;
  - breathing and head movement;
  - a walk cycle in place;
  - blinking;
  - the mouth moving while talking.

  F1 → Look dev switches between idle, walk and talk. Bevy reads morph target names from mesh extras, while VRoid stores them on the primitive, so the names are read from the file's JSON. `living/tools/lookdev_assets.sh` downloads the CC0 set used so far: two VRoid anime characters (Sendagaya Shino, Vivi) and four KayKit Adventurers.

With `LIVING_GAME_DEMO=<dir>` it photographs the scene:
- from the north, east and south;
- close up at 8 m and 4.5 m;
- at sunset;
- without the toon look;

then quits.

```bash
LIVING_GAME_LOOKDEV=1 cargo run --manifest-path living/Cargo.toml --release -p living-game
```

## Test environments

In look-dev mode, F1 → Look dev (or `,` and `.`) switches between the character line-up and the test environments in `living/game/assets/envs/*.json`:
- meadow, forest and spirit forest;
- caverns;
- the cities of giants and of small folk;
- cyberpunk, fantasy and steampunk cities.

Each file gives:
- **mood:** sun, sky, fog, and gentle shifts in shadow hue, saturation, gradient, brightness and ambient;
- **ground:** `open`, `paved` or `cave`, with colour and relief;
- **slots:** a kind, a rule (`scatter`, `grid` or `ring`), a height range in metres and an optional glow.

**Assets plug in by folder:**
- every GLB/glTF in `assets/envs/<id>/<kind>/` (or `assets/envs/shared/<kind>/`) is used for that kind, scaled to the slot's height, so a pack's units don't matter;
- empty folders fall back to placeholder shapes;
- glowing kinds (lamps, signs, crystals, some mushrooms) get point lights, which the toon shader bands like the sun;
- tall things are cut away when they stand between the camera and you.

You walk around with WASD (Shift to run), as a VRoid character from the look-dev folder if there is one.

`LIVING_GAME_TOUR=<dir>` photographs every environment, from the default view and close up:

```bash
LIVING_GAME_LOOKDEV=1 LIVING_GAME_TOUR=/tmp/tour cargo run --manifest-path living/Cargo.toml --release -p living-game
```

## Characters

VRoid characters are built from recipes (`src/characters.rs`, `assets/characters/recipes.json`). They share one skeleton and one set of clips.

A recipe gives:
- a base VRoid file;
- a height in metres;
- proportions as multipliers: legs, arms, torso, neck, head, shoulders, hips, build, hands and feet;
- colours for hair, skin, eyes, top, bottom, shoes and accent, as sRGB hex.

The file also holds folk ranges (`adult`, `giant`, `small`) and palettes for seeded random recipes.
- Lengths and girths scale each bone's own vertices through a helper skin joint, so rotating children aren't sheared. Head, hands and feet scale uniformly.
- The hips' animated translation scales with the legs, so feet stay on the ground.
- Colours are per-instance toon parameters: the hue and value are remapped from each material's mean texture colour, and grey textures are tinted.
- Spring bones come from the file's VRM 0.x `secondaryAnimation`. They cover hair, skirts, sleeves and bust, and collide with the file's collider spheres. They run after the pose at a fixed 60 Hz, with at most three steps a frame.

| Variable | Meaning |
|---|---|
| `LIVING_GAME_CROWD=N[:seed]` | the line-up gets N random characters in rows to its south: small folk in front, then adults, then giants. Photograph them with `LIVING_GAME_TOUR_SHOTS=0:10:36:40` |
| `LIVING_GAME_PLAYER=<recipe>` | your character: a recipe name or `<folk>:<seed>` |
| `LIVING_GAME_VIEW=recipe:<name>` or `recipe:<folk>:<seed>` | the asset view shows a recipe |
| `LIVING_GAME_SPRINGS=0` | springs off |
| `LIVING_GAME_SPRING_BUDGET` / `LIVING_GAME_SPRING_NEAR` | the most characters simulated in a frame (nearest first; default 48), and the distance limit in metres for a 1.75 m character (default 40, scaled by height) |

Environment slots of kind `person` with no asset folder are filled with random recipes of the slot's height.

The simulation logs its cost every 3 s. A 78-joint character costs about 9 µs of CPU per step on an M4 Pro.

## Controls

| Input | Effect |
|---|---|
| A click in the window | captures the cursor: the system cursor is locked and hidden and the game draws its own (`pointer.rs`); the click does nothing else |
| Esc | closes the text box, a list (a sub-list first) or the panels; with nothing open, gives the cursor back. Losing focus gives it back too |
| WASD, Shift | move relative to the camera, run (`human_move`). Shift is also the dodge (an open question) |
| Mouse or one finger on a trackpad | the cursor: where you face and aim. Moving, your legs keep to your travel (backwards beyond 110°) and your upper body turns toward it (`twist.rs`) |
| Left click (tap) / left held | the strike (on release for a tap, after 0.22 s held for aiming) |
| Left drag (mouse or trackpad press-and-move), two-finger pan, middle drag, `[` / `]` | turn the view; the cursor stays on its ground point, so where you face doesn't change |
| Pinch, mouse wheel | zoom, within 0.6–1.4 of the view's distance |
| Two-finger double tap, middle tap | turn the view until the direction you face is straight ahead |
| Right click (two-finger click), Q, E, R, Shift | the bow shot, fire bolt, block, heal, dodge |
| Space | jump (a 1.6 m hop; `jump.rs`, the rules' `jump`) |
| Enter | say something; only characters within earshot hear it (`human_say`). Enter says it, Esc cancels |
| Alt + mouse | glance around; the view eases back on release |
| F | act on what is under the cursor or within 3 m: a tap does the likely act (never a gesture), holding opens the list of what the rules allow (`verbs.rs`) |
| C | the list of acts on yourself (eat, sleep, craft, build, write, …) |
| I / K | toggle the pack and the know-how panels |
| 1–9, 0, click | pick from an open list |
| G / B / V | wave, nod, look someone over (`town.rs`) |
| F1 | developer panels in egui (status, camera, look, sight, look-dev); hidden by default (the cursor is given back while they show) |

The line from your character to the cursor shows where an aimed skill would go. `F` acts on things and people from the rules' own data (docs/GAME_BRIEF.md, "Verbs").

Buildings, trees and props that come between the camera and you fade to a dithered 20% (fully, around the eye) and return 0.35 s after; people and animals fade in and out of sight and into their houses (`fade.rs`). Headless scripts can drive the pointer (`cursor:X,Y`, `pan:PX`, `drag:PX`, `pinch:F`), face a direction (`look:DEG`), press Space (`key:Space:tap`) and turn the view's framing off (`frame:0`) (`live.rs`).

## Game UI

The player's UI is Bevy UI (`src/ui/`); egui stays for the F1 panels. It is minimal: only health, energy and the skill bar are always on screen. Everything else appears when it matters:
- the target frame (top centre) with a target under or near the cursor;
- nameplates over hovered, targeted or hostile characters, fading with distance (a speaker's bubble carries their name);
- speech bubbles that stack instead of overlapping, with leader lines, and that fade out;
- status icons while an effect is active (hungry, tired, losing health, recovering, in combat);
- an interaction hint near something usable (`F gather`), the list of acts, and short notes of what the authority said of them;
- the pack (I) and know-how (K) panels, hidden by default;
- the chat log when there is new speech or the input is open (only what you heard);
- the death screen: the cause, who saw it, then "Arrive as a new stranger" (click or Enter);
- a notice at the top while a lost connection is restored; no one is drawn meanwhile;
- a small compass at the top right, with north and nearby places.

Widgets draw a view-model (`ui/model.rs`) filled by one source:
- **Live** (`ui/live.rs`): health and energy from your `vitals` row, projected along its rates; status from needs and `hurt_ms`/`hurt_by`; names from `character`; bubbles and the log from your own `experience` speech rows; death from your `character` row; compass points from your `place` rows (subscribed with your character).
- **Sample** (`ui/sample.rs`, look-dev only): representative values on the scene's own characters, for layout.

Layout is designed at 1080p and scales with the window's height. Fonts are Nunito and Marcellus under the SIL Open Font License 1.1 (`assets/ui/fonts/`). Icons are procedural placeholders (`ui/icons.rs`) until real icon art exists.

`LIVING_GAME_HUD` turns the sample UI on in look-dev (it is off by default, so look-dev photographs and frame-time runs stay clean): `1` for a typical moment, or a comma list of `hover`, `bubbles`, `chat`, `lowhp`, `cooldown`, `death` (`quiet` shows only what is always on screen):

```bash
LIVING_GAME_LOOKDEV=1 LIVING_GAME_TOUR=/tmp/hud LIVING_GAME_TOUR_ONLY=island LIVING_GAME_START=416,256 \
  LIVING_GAME_TOUR_SHOTS=default LIVING_GAME_HUD=lowhp,cooldown \
  cargo run --manifest-path living/Cargo.toml --release -p living-game
```

## What it shows

- **Scale:** one tile is one metre.
  - The ground comes from the shared `living_rules::height::Ground`: hills up to about 14 m that flatten toward water, mountains of 40–60 m where rock is dense, and snow on the highest ground.
  - People are 1.75 m, deer and wolves are real size, and legs and arms swing with actual speed.
  - Trees are 8–15 m, with bushes and berry bushes between; huts have roofs, and town walls are 2.6 m.
- **One camera:**
  - about 40° down and 16 m away for an adult, scaled to your size ("my size" in F1 tries a giant or a small character);
  - you face the cursor; the view turns only when you turn it, with `[` `]` or middle-drag, and Alt glances (turning by pointing is an option, off by default);
  - conversations are framed;
  - the view never pulls back further than about 1.5 × your sight, so night sight brings it down and in.
- **Look (F1 → Look):**
  - one toon material on every surface, after Blue Protocol: a hard step with about 70% lit, shadows whose hue is shifted toward a target with saturation kept, slightly brushy band edges, rim light;
  - a finishing pass (`edges.wesl`): edge lines from the depth and normal prepasses, drawn outside silhouettes and fading with distance; a screen-space rim on silhouettes facing the sun; a warm film gradient; saturation grading. SMAA replaces MSAA so the prepasses stay single-sample;
  - outlines on characters and buildings, which the ground, trees and props hide;
  - every parameter is tunable, with a toggle to compare against the plain look.
- **Occlusion:** tall things whose box cuts the sight lines from the eye to your head, chest or feet fade to a dithered 20% (`envs::cutaway`, `fade.rs`).
- **Region subscriptions:** `body`, `resource_node` and `structure` rows are subscribed for the chunks within 40 m.
- **Motion:** the observer's display sync (`living/viewer/src/sync.rs`, included by path) smooths it.
- **Perception:** the chat log and speech bubbles come only from your character's own `experience` rows. Your own lines are echoed locally.
- **Sight mock (F1, client-only):**
  - a sight radius, all round or in a forward cone;
  - seen ground stays dimmed, and never-seen ground stays dark;
  - characters, nameplates and bubbles outside sight are hidden, and trees outside sight are dimmed.

## Known limits

- **No fog of war.** The authority still publishes every table to any client, and the spike subscribes to `character` and `terrain_chunk` whole.
- **No client-side prediction.** Your own movement waits for the authority's rows.
- **Occlusion:** trees fade, but terrain and boulders don't; a hill between the camera and you can still block the view in zoom-tilt.
- **Tile edits:** changed terrain rows (roads, walls) redraw only after a reconnect.
- **Death:** the authority doesn't say who saw a death, so the live death screen omits witnesses.
- **The game UI's live source is not driven against a server yet;** its layout is checked through look-dev photographs (`LIVING_GAME_HUD`). Typing into the chat and the death screen's click are not driven by a script.
