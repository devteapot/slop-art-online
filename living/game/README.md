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

## Controls

| Input | Effect |
|---|---|
| WASD, Shift | move relative to the camera, run (`human_move`) |
| Right click | walk to that point (`human_act` with `goto`) |
| Enter | say something; only characters within earshot hear it (`human_say`) |
| Q / E | rotate 45° (when the preset allows it) |
| Mouse cursor | where you face and aim (turning the view by pointing at screen sides is an F1 option, off by default) |
| `R`, or a middle mouse tap | turn the view until the direction you face is straight ahead; the cursor moves with the ground meanwhile, so you keep facing the same spot |
| `[` / `]` held, or middle mouse drag | rotate the view (90°/s for the keys); it stays where you leave it |
| Alt + mouse | glance around; the view eases back on release |
| F1 | camera and sight panels |

The line from your character to the cursor shows where an aimed skill would go. There are no skills yet.

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
- **Occlusion:** trees between the camera and you, or close to you on the camera's side, are hidden, with a faded band around them.
- **Region subscriptions:** `body`, `resource_node` and `structure` rows are subscribed for the chunks within 40 m.
- **Motion:** the observer's display sync (`living/viewer/src/sync.rs`, included by path) smooths it.
- **Perception:** the feed and speech bubbles come only from your character's own `experience` rows. Your own lines are echoed locally.
- **Sight mock (F1, client-only):**
  - a sight radius, all round or in a forward cone;
  - seen ground stays dimmed, and never-seen ground stays dark;
  - characters, names and bubbles outside sight are hidden, and trees outside sight are dimmed.

## Known limits

- **No fog of war.** The authority still publishes every table to any client, and the spike subscribes to `character` and `terrain_chunk` whole.
- **No client-side prediction.** Your own movement waits for the authority's rows.
- **Occlusion:** trees fade, but terrain and boulders don't; a hill between the camera and you can still block the view in zoom-tilt.
- **Tile edits:** changed terrain rows (roads, walls) redraw only after a reconnect.
- **Speech bubbles** overlap when speakers stand close together.
- **Death:** when your character dies, the client quietly joins again as a new one. There is no death screen yet.
- **Not checked on its own:** egui `TextEdit` focus combined with Enter. It is verified only through the scripted demo, which calls `say` directly.
