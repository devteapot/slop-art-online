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
| 1–4 | camera presets: ARPG diagonal, MOBA north-up, top-down action, isometric orthographic |
| Q / E | rotate 45° (when the preset allows it) |
| Mouse wheel | zoom within limits |
| F1 | camera tuning panel |

The line from your character to the cursor shows where an aimed skill would go. There are no skills yet.

## What it shows

- **Terrain:** one mesh per 16×16-tile chunk, built near the player.
- **Region subscriptions:** `body`, `resource_node` and `structure` rows are subscribed for the chunks within 40 tiles. The next window is subscribed before the old one is dropped.
- **Motion:** the observer's display sync (`living/viewer/src/sync.rs`, included by path) smooths it.
- **Perception:** the feed and speech bubbles come only from your character's own `experience` rows. Your own lines are echoed locally, because the authority sends a speaker no percept of their own words.

## Known limits

- **No fog of war.** The authority still publishes every table to any client, and the spike subscribes to `character` and `terrain_chunk` whole.
- **No client-side prediction.** Your own movement waits for the authority's rows.
- **Tall forests hide your character** in the steeper presets. A real client needs occlusion fading.
- **Not checked on its own:** egui `TextEdit` focus combined with Enter. It is verified only through the scripted demo, which calls `say` directly.
