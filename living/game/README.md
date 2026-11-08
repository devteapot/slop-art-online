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

## Controls

| Input | Effect |
|---|---|
| WASD, Shift | move relative to the camera, run (`human_move`) |
| Right click | walk to that point (`human_act` with `goto`) |
| Enter | say something; only characters within earshot hear it (`human_say`) |
| 1–5 | camera presets: ARPG, MOBA north-up, top-down action, zoom-tilt, default (mid; the starting one) |
| Q / E | rotate 45° (when the preset allows it) |
| Middle mouse or Alt + mouse | glance around; the view eases back on release |
| Mouse wheel | zoom; in zoom-tilt it also brings the view down toward the ground |
| F1 | camera and sight panels |

The line from your character to the cursor shows where an aimed skill would go. There are no skills yet.

## What it shows

- **Ground:** a heightfield from the shared `living_rules::height::ground` function (water lowest, rock rising into hills, borders blended, seeded noise). Characters stand on it. Each chunk has a ground mesh with blended tile colours and bare rock on steep slopes, boulders inside rock, walls and a water plane. Trees between the camera and your character fade out.
- **Zoom-tilt (preset 4):** one zoom axis eases pitch, distance and field of view together, from 60° far out to 24° close in. Distant ground fades into the sky, and more terrain is drawn as the view lowers.
- **Default (preset 5):** zoom-tilt starting mid-way at about 40°.
  - You face the cursor (mouse look is on by default), and WASD moves you relative to the camera.
  - The view turns while the cursor sits toward a side of the screen ("follow cursor"), but not when the cursor is below your character.
  - In the walking-based turning modes, walking toward the camera turns the view only after 1.2 s. Zooming out is bounded by sight: the camera distance is at most 1.5 × the sight radius, so scout sight allows the full tactical view.
- **Camera options (F1):**
  - conversation framing: comes in on you and whoever you are talking with; a manual zoom overrides it until the conversation ends;
  - turning modes:
    - fixed, north up, with Q/E 45° steps;
    - follow heading;
    - zoom blend: north up when zoomed out, increasingly behind where you face as you zoom in;
    - mouse steer: the view turns while you point well off to the side;
  - mouse look: you move with WASD and face the cursor, shown locally only, because the authority has no look direction yet;
  - in every mode the movement keys keep their direction while held, and a compass at the top shows north;
  - cursor lean, with a deadzone.
- **Sight mock (F1, client-only):**
  - you see within a sight radius, either all around or in a forward cone with a small all-round ring; presets are night 6, torch 9, day 11 and scout 20;
  - ground you have seen stays dimmed, and ground you have never seen stays dark;
  - characters, names and speech bubbles outside sight are hidden; what you hear stays in the feed;
  - resources and structures appear once their tile has been seen, and trees outside sight are dimmed;
  - nothing is enforced: the authority still sends every row.

- **Terrain:** one mesh per 16×16-tile chunk, built near the player.
- **Region subscriptions:** `body`, `resource_node` and `structure` rows are subscribed for the chunks within 40 tiles. The next window is subscribed before the old one is dropped.
- **Motion:** the observer's display sync (`living/viewer/src/sync.rs`, included by path) smooths it.
- **Perception:** the feed and speech bubbles come only from your character's own `experience` rows. Your own lines are echoed locally, because the authority sends a speaker no percept of their own words.

## Known limits

- **No fog of war.** The authority still publishes every table to any client, and the spike subscribes to `character` and `terrain_chunk` whole.
- **No client-side prediction.** Your own movement waits for the authority's rows.
- **Occlusion:** trees fade, but terrain and boulders don't; a hill between the camera and you can still block the view in zoom-tilt.
- **Tile edits:** changed terrain rows (roads, walls) redraw only after a reconnect.
- **Speech bubbles** overlap when speakers stand close together.
- **Death:** when your character dies, the client quietly joins again as a new one. There is no death screen yet.
- **Not checked on its own:** egui `TextEdit` focus combined with Enter. It is verified only through the scripted demo, which calls `say` directly.
