# Game brief: the playable client

Started with the user on 2026-11-08. This is a design target and decision log, not an implementation report. Implementation evidence goes in [current state](CURRENT_STATE.md) and the [stage log](STAGES.md).

Until now every client served the simulation lab: the [living observer](../living/viewer) shows experiment worlds and cannot control anyone. This brief covers a separate product: a game humans actually play, built from scratch.

## Lab and game — decided

| | Simulation lab | Game |
|---|---|---|
| Purpose | experiments on behavior, society and scale | a world people play in |
| Code | shared core: [`living/rules`](../living/rules) and [`living/authority`](../living/authority) | the same core |
| Own parts | seeds, lab tools, the observer, throwaway worlds | its setting and seed, its client (`living/game`), its database and deployment |
| Pace of change | moves fast on `main` | runs a released core version |

Findings move from the lab to the game when a core version is released and the game world is updated to it. A persistent game world is never reset, so every core update the game takes must be a valid in-place update of a live module. Game-specific behavior lives in the seed and config (seeds already carry a `rules` block), never in a fork of the core.

## Player experience — decided

- **A 3D world in Bevy, desktop first.** Other platforms may come later. The simulation stays a flat tile plane; the client renders it in 3D.
- **ARPG-style camera.** Isometric or top-down, as in League of Legends, Supervive and Path of Exile, tweaked for the genre. No first person, and no free 360° orbiting camera.
- **Interactive combat** with both targeted skills and aimed skillshots.
- **Proximity chat.** Players type free text. Only characters within earshot hear it, which the authority already enforces (`perceive::speak`).
- **Many human players.** No fixed number: as many as the core can support. This makes the scale gates of the [performance contract](PERFORMANCE_CONTRACT.md) game requirements.
- **The world continues offline.** When a player leaves, their character keeps living under an AI mind. That mind's behavior should come from how the player actually played, so the character stays recognizably theirs. A custom external mind supplied by the player is a later option.
- **Running cost** of model calls is set aside for now.

## Open questions, with recommended defaults

| Question | Recommended default | Why |
|---|---|---|
| Which setting ships? | A new game seed built with the authored-world tools; Aske Coast as the first test world | The [world vision](WORLD_VISION.md) setting (AI factions, gods, ascension) needs mechanics the core doesn't have yet |
| Core loop | Arrive as a stranger, find food and shelter, earn a place in a community by working, trading and talking; status and conflict follow | Every part already exists in the core: needs, communities, offices, graded force |
| Joining | Arrive at the edge of a settlement and ask to join (`community`, `membership`, `join_request` exist) | Being born is too slow at a playable pace |
| Death | Permanent, as agreed. The player sees how they died and who saw it, then arrives as a new stranger with nothing inherited | Follows [world vision](WORLD_VISION.md) mortality |
| World pace | Slower than labs (labs run about 5 game days per real hour); set per seed with `life_pace` and `year_days` | To decide by play-testing |
| Camera details | **Not fixed yet** (user, 2026-11-08). Leading candidate: zoom-tilt (spike preset 4). The view should show only what the character perceives, and how much a character can see could be a capability (below) | The user liked presets 1–3 and found a purely high view less immersive. Fully zoomed in feels most immersive, but it is unclear how that plays with many players, since much of the area is not visible. The camera research found the zoom-tilt blend in Baldur's Gate 3, Manor Lords and Diablo IV |
| Movement | WASD relative to the camera, plus click-to-move (`goto` to a point) | Matches the chosen genre |

## The view as perception (idea, 2026-11-08)

The user's idea: seeing only what is in front of you makes sense, and skills, passives or kinds of character could change the view. That fits the core's rules:

- The authority already gives every character a sight range (`sight_day` 11, `sight_night` 6, `sight_torch` 9 tiles) and `hearing` 9, and minds receive only what falls inside them. Players are the exception today: they receive every table.
- **Principle:** the camera presents the character's perception, not the world. A higher or wider view then reveals nothing the character doesn't perceive, so the camera stops being a fairness question. The authority enforces it (perception-scoped views); the client only draws it.
- **Then the view can be a capability**, granted, learned or bodily like any skill. Possible forms:
  - a wider or farther sight (a scout, an elevated perch);
  - a facing cone with peripheral awareness;
  - night vision;
  - scent shown as traces (animals already smell beyond sight);
  - a skill that briefly lifts the camera.
- **To explore before deciding:**
  - a client-only mock in the spike: hide what lies beyond sight or outside a facing cone, dim terrain not seen recently, and use a slider for the "sight" capability;
  - try it at day and night, alone and in a crowd, high and low camera;
  - only then move the scoping into the authority.

## Core work the game needs (engine-independent)

1. **Perception-scoped data.** Almost every table is public today, including other characters' `experience`, `thought`, `belief` and `persona`. A player must receive only what their character can perceive and remember:
   - shared views by map region for the physical world (`body`, `structure`, `resource_node` and `terrain_chunk` are already indexed by 16×16-tile chunk);
   - per-player views keyed on the caller for private state;
   - mind tables made private, with a separate developer path for the observer.
2. **A typed player API.** `human_act` takes behavior-graph JSON. The game needs typed actions, aim directions and the projectile or area mechanics that skillshots require.
3. **Controller handoff.** Move a character between the player and a mind on disconnect and reconnect. Today `mind_*` reducers authorize by `character.controller`.
4. **A mind learned from play.** The player's own experiences and choices must be consolidated into the persona and routines the offline mind uses.
5. **Joining, death and rejoining** as above.
6. **Measured input latency.** The contract asks for ≤150 ms p95 from input to authoritative outcome at 80 ms round trip. It is unmeasured for human input on the living core. Client-side prediction can reuse the same steering code the authority runs (`living_rules::steer`).

## Engine — decided: Bevy

How easily an agent can build, verify and iterate decided it:

- **Bevy:** everything is Rust code, buildable and testable from the command line. It shares the rules crate with the authority (prediction without a second simulator), and it shares bindings and verification harnesses with the core.
- **Unity:** scenes and prefabs are fragile to edit as text, and headless builds need license activation.
- **Unreal:** Blueprints are binary, and builds are slow and very large.

Bevy's gaps are filled with our own code: game UI widgets (egui only for developer tools), editor-like tooling as in-game debug panels and data files, and art made in Blender and exported as glTF. Unity remains the fallback if art or animation needs outgrow this.

## SpacetimeDB documentation consulted (2026-11-08)

Pinned versions at the time: module, SDK and server `2.10.1` (upgraded to 2.14.1 the same day).

- [Client SDKs](https://spacetimedb.com/docs/clients): official SDKs exist for Rust, C# (also used for Unity), TypeScript and Unreal (C++ and Blueprint). The pages read give no maturity labels.
- [Views](https://spacetimedb.com/docs/functions/views/):
  - Views can filter per caller (`ctx.sender`), and clients subscribe to them like tables. Each per-user view is computed separately for every subscriber, while anonymous views are shared.
  - Views may only use indexed lookups.
  - The page recommends region-based design: clients subscribe to shared regions instead of per-user "what's near me" queries.
  - **Implication:** the physical world goes through shared, chunk-keyed data, and only private state goes through per-player views. Fog of war still has to be enforced by what the authority puts in those views.
- [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/):
  - Keep subscriptions small and precise, grouped by lifetime.
  - When moving, subscribe to the new set before dropping the old one.
  - **Implication:** the client subscribes to a moving window of chunks around the player.

## World look and camera research (2026-11-08)

**Terrain: heightfield plus meshes, not voxels.**
- No Man's Sky does use a density field ("voxels") meshed smoothly, with dual contouring, and with dual marching cubes since its 5.0 update ([GDC 2017](https://www.gdcvault.com/play/1024265/Continuous-World-Generation-in-No), [5.0 notes](https://www.nomanssky.com/worlds-part-i-update/)). Its terrain edits are buffers with known size limits.
- For a world whose rules are a flat tile grid, that brings level-of-detail seams, 3D memory and harder edit syncing, with no gameplay that needs caves or overhangs.
- Shipped stylized worlds mostly use heightfields: The Witcher 3 ([GDC](https://www.gdcvault.com/play/1020394/Landscape-Creation-and-Rendering-in)), Valheim (height edits). BitCraft, the closest match to our model, uses discrete height steps on a grid ([blog](https://bitcraftonline.com/blog/shaping-the-world)).
- **Decision:** a seeded height function in the shared rules crate (`living_rules::height`), so characters stand on the drawn ground, plus separate meshes for rocks and cliffs. The authority stays 2D. If height ever matters to gameplay, the authority calls the same function or stores per-chunk heights.
- A surface-nets cliff on one chunk is the test for whether real overhangs are worth it later.

**Camera: zoom-tilt with context framing.**
- Diablo IV brings the camera closer in towns and frames conversations while keeping its isometric feel, and pulls back for big fights ([GameBanshee](https://www.gamebanshee.com/3dhhd)).
- Baldur's Gate 3 and Manor Lords scroll from a bird's-eye view down to near ground level ([PCGamesN](https://www.pcgamesn.com/baldurs-gate-3/camera-controls), [TechRadar](https://www.techradar.com/gaming/manor-lords-preview-camera-feature-brings-you-down-to-earth)).
- Guild Wars 2 and Throne and Liberty make a follow-heading camera opt-in ([GW2 wiki](https://wiki.guildwars2.com/wiki/Camera)).
- Design rules applied:
  - pitch, distance and field of view come from one zoom value (Nesky, [50 Camera Mistakes](https://gdcvault.com/play/1020460/50-Camera));
  - the movement keys never change direction instantly (Haigh-Hutchinson);
  - the player's zoom overrides the automatic framing.
- **Open tension:** cursor aiming loses precision at low angles. Skillshots will need a pitch floor while aiming, an automatic raise in combat, or a reticle (as in GW2's action camera).

## Dependency upgrades (checked 2026-11-08)

| Component | Pinned | Latest | What matters |
|---|---|---|---|
| SpacetimeDB (server image, module crate, SDK, CLI) | 2.10.1 | 2.14.1 | Views with arguments from 2.13, the building block for area-of-interest views. Lower per-transaction subscription memory, also from 2.13. Module unit tests from 2.12. Rust API churn is near zero. Upgrade the server before the module (2.14 modules export an HTTP-handler entry that older hosts reject). Back up the data volume first and treat the upgrade as one-way. |
| Bevy | 0.18.1 (observer) | 0.20.1 (spike) | 0.19 and 0.20 add text input with IME, Feathers widgets (dropdown, list, number input), BSN scenes and contact shadows, and catch panics in systems. The editor is still future work. |
| bevy_egui / egui | 0.39.1 / 0.33 | 0.43.1 / 0.36 | The egui 0.35–0.36 panel API rewrite is most of the observer's upgrade effort. |
| rhai, reqwest, toml | 1.26, 0.12, 0.8 | 1.27, 0.13, 1.x | Small. reqwest renames the `rustls-tls` feature to `rustls`; rhai counts callback operations toward the operations limit. |

Order: the small crates first, then SpacetimeDB 2.14.1 across server, module, SDK and bindings, then the observer to Bevy 0.20. Afterwards the workspace builds one Bevy version again. Re-baseline the 216-character gate after the SpacetimeDB upgrade.

## Camera spike

[`living/game`](../living/game) is a throwaway prototype for choosing the camera and controls, not the start of the client's architecture. It runs as a desktop Bevy app and joins a world as a player with its own identity.

What it does:

- shows the real map in 3D;
- loads only the chunks around the player;
- offers several camera presets with live tuning;
- sends WASD movement through `human_move`, click-to-move through `goto`, and chat through `human_say`;
- shows only speech the character hears, from its own `experience` rows.

How to run it is in its [README](../living/game/README.md).
