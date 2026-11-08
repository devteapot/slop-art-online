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
| Death | Permanent, as agreed. The player sees how they died and who saw it, then arrives as a new stranger with nothing inherited | Follows [world vision](WORLD_VISION.md) mortality. In the spike (2026-11-08) a test character starved, and the client quietly joined again as a new character: the death and rejoin screen is missing |
| World pace | Slower than labs (labs run about 5 game days per real hour); set per seed with `life_pace` and `year_days` | To decide by play-testing |
| Camera details | **Default chosen** (user, 2026-11-08): spike preset 5, "Default (mid)". Skills, passives or other capabilities may change how it behaves. Rotation: see "Turning the view" below. Earlier status: not fixed yet (user, 2026-11-08). Leading candidate: zoom-tilt (spike preset 4). The view should show only what the character perceives, and how much a character can see could be a capability (below) | The user liked presets 1–3 and found a purely high view less immersive. Fully zoomed in feels most immersive, but it is unclear how that plays with many players, since much of the area is not visible. The camera research found the zoom-tilt blend in Baldur's Gate 3, Manor Lords and Diablo IV |
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
- **The view must turn with the character when it is low.** The user, 2026-11-08: a north-locked view means you only ever look one way. Fully zoomed in, what you see then depends on which way you walk. The spike compares four turning modes: fixed, follow heading, zoom blend and mouse steer. With mouse look, where you face can differ from where you walk; the authority would need a look direction, which aimed skills and a facing cone need anyway.
- **One camera for every kind of character (proposal, 2026-11-08).** The user wants a common default that suits a summoner mage, who benefits from a wide view, as well as a melee fighter, who wants to be close. The proposal:
  - Characters differ in what they perceive, not in camera rules.
  - The default is a mid zoom-tilt (about 40° down) that turns with you.
  - How far you can zoom out is bounded by sight: the camera distance is at most 1.5 × the sight radius. Day sight barely allows zooming out past the default, while scout sight allows the full tactical view.
  - A summoner who perceives through their summons (as vision from minions or wards does in MOBAs) therefore has a reason to zoom out; a melee fighter doesn't, and sees nothing more by doing so.
  - Context framing extends the same idea: conversations (built), fights (you and your opponents) and your summons or companions, always overridable by the player.
  - Spike preset 5, "Default (mid)", implements the default and the sight bound.
- **Controls (user, 2026-11-08), each separate from the others:**

  | Control | Input |
  |---|---|
  | Move | WASD, relative to the camera |
  | Face and aim | the cursor |
  | Turn by pointing | the cursor toward a side of the screen (**dropped as the default**: the user disliked it, 2026-11-08; an F1 option) |
  | Rotate the view | `[` / `]` or middle-drag; stays where you leave it |
  | Turn to where you face | `R` or a middle tap, on request only (user, 2026-11-08). The cursor moves with the ground while the view turns, so the facing doesn't change and the turn ends with it straight ahead |
  | Glance | Alt + mouse; springs back |

  The zoom stays fixed at the default mid-way view for now, with the wheel off, "to see how it works".
- **Facing follows the cursor (agreed to try, 2026-11-08).** You face the cursor on the ground, and WASD moves you relative to the camera, so you can walk backwards or sideways while facing forward. The spike's default (preset 5) now does this.
  - The view turns while the cursor sits toward a side of the screen (outside the middle 45%, up to 90°/s). It doesn't turn when the cursor is below your character, as when aiming behind you while kiting. A cursor held still can't make it spin, and walking never turns it.
  - Hiding by hills and objects: the user wants to see whether this way of turning already makes it a non-issue before building more (only trees fade today).
  - Facing is shown only on your own screen. The authority still has no look direction, so others see you facing the way you walk.
- **Turning the view (proposal, 2026-11-08):** link the camera to where you face, not to raw movement.
  - **By default** the view eases in behind your facing. Short movements toward the camera (backing off, dodging) don't turn it; only a sustained walk that way does, after 1.2 s. A retreat keeps what you retreat from in front of you. (Built.)
  - **While aiming, fighting or talking**, the yaw holds still and the camera frames the situation. You face the cursor or your target. (Needs combat.)
  - **Glance:** hold the middle button or Alt and move the mouse to look around; release and the view eases back. You can look around without a free orbit. (Built.)
  - **Settings, off by default:** sticky free rotation, Q/E nudges and a reset key, for players who want them.
  - **On the authority:** a look direction for each character, so the facing cone, aiming and what others see of you agree. Today facing is just the direction of travel.
- **To explore before deciding:**
  - a client-only mock in the spike: hide what lies beyond sight or outside a facing cone, dim terrain not seen recently, and use a slider for the "sight" capability (built 2026-11-08, F1 → Sight);
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

## Scale (decided 2026-11-08)

**One tile is one metre.** The rules already read that way:
- walking is 2.6 m/s and running 3.9 m/s;
- personal space is 0.8 m;
- a campfire warms within 3.5 m and a shelter within 2.5 m;
- speech carries 9 m.

The client draws everything to that scale:
- an adult is 1.75 m (children and infants smaller by life stage);
- deer are about 1.1 m at the shoulder and wolves about 0.75 m;
- trees are 8–15 m, spaced 3–4 m apart in forests;
- huts are about 3.7 m to the ridge, and town walls 2.6 m;
- the ground has hills up to about 14 m and mountains of 40–60 m where rock is dense, while water lies in valleys.

What doesn't fit yet is the world, not the drawing:
- day sight of 11 m is short;
- the default world (four walled cities between mountains and a sea) is only 512 × 512 m.

Both are settings for the game's own world (seed and laws), not the lab's. Body size is so far only a client slider ("my size"). Real sizes of character would need the rules to carry a size: reach, separation, speed and sight.

## Art direction (proposal, 2026-11-08)

The user wants:
- a real art style, with models better than the spike's placeholders;
- the look of Fortiche's Arcane (2D and 3D mixed, painterly, clean);
- different styles per zone (a cyberpunk town, an anime-like fantasy region) over the same systems.

**How Arcane is made, and what carries over** ([80.lv](https://80.lv/articles/arcane-artists-show-how-they-combine-traditional-art-3d-for-backgrounds), [VFX Voice](https://vfxvoice.com/riot-games-and-fortiche-get-revolutionary-with-arcane-season-2/)):
- 3D sets with matte painting projected onto them.
- 3D character rigs with 2D animation layered on top for texture, smoke, fire and dust. Effects are reportedly at 12 fps, which is unverified for the characters.
- Light and shadow largely painted into textures.

In real time we can reach:
- banded "cel" lighting through a painted ramp, with shadows tinted toward a hue;
- outlines, and a moderate brush or Kuwahara filter;
- per-zone colour grading;
- 2D flipbook effects at 12 fps, and stepped character poses.

We can't reach Fortiche's per-shot painting and compositing, or painted light that stays right under a moving camera. The closest games, and their methods:
- Guilty Gear Xrd: hand-edited normals, inverted-hull outlines and limited animation ([GDC](https://gdcvault.com/play/1022031/GuiltyGearXrd-s-Art-Style-The)).
- Hi-Fi Rush: a toon renderer ([GDC](https://gdcvault.com/play/1034330/3D-Toon-Rendering-in-Hi)).
- Genshin: face-shadow SDFs.

**Style as data over the same world (architecture):**
- Gameplay objects stay abstract: `person`, `house`, `deer`, `campfire`.
- A zone's **style profile** chooses:
  - the models and materials for each kind;
  - a toon ramp, shadow tint and rim light;
  - outline width, colour and edge thresholds;
  - the painterly-filter strength;
  - colour grading and fog;
  - the light rig;
  - the effects palette.
- One "uber" material takes style parameters as uniforms rather than shader variants, so a new style adds no pipelines.
- Profiles blend at zone borders, the way Unreal blends post-process volumes.
- A few invariants hold across every style so gameplay stays readable: character silhouettes and outlines, threat and faction colours, and the language of effects.

**Bevy 0.20.1 support** (checked in source and crates.io):
- built in: extended materials (WGSL/WESL), fullscreen post-processing materials, depth and normal prepasses, colour grading, bloom, fog, decals, and stepped glTF interpolation;
- crates: `bevy_mod_outline` 0.14 (Bevy 0.20.1), `bevy_hanabi` (particles) and `bevy_sprite3d` (2D sprites in 3D);
- custom code needed: the toon ramp, edge detection, Kuwahara, face SDFs and a stepped-animation sampler.

**Assets** (licences checked where official pages allowed):
- **Humanoids:** Quaternius Universal Base Characters with the Universal Animation Library 1 and 2 (CC0). Six body types share one rig, with about 250 clips (locomotion, combat, emotes, farming, fishing). Bevy plays clips on any character whose bone names match, but has no runtime retargeting. So every humanoid is fitted to one canonical skeleton offline in Blender.
- **Avoid:** Mixamo (unclear long-term terms, and raw files can't be redistributed), Sketchfab models under NC or ND licences, and Hunyuan3D weights, whose licence excludes the EU, the UK and South Korea.
- **Props and buildings** can come from AI generation (Meshy, Tripo or Rodin on a paid plan so the output is owned), conditioned on style reference images. AI-rigged characters each bring their own vendor's skeleton and break shared animation.
- **Animals** need their own four-legged skeleton and clips (not yet researched).
- Blender 5.2.2 runs headless here (`blender -b -P`). A pipeline script and a manifest (kind + traits × zone style → model, materials, animation set, height, triangle budget) can be built and checked automatically, with screenshots next to a 1.75 m reference figure.

**Animation gaps in Bevy 0.20** that need custom code: root motion, IK (feet), animation level of detail. Every bone is an entity, so CPU cost grows with bones × characters. Measure with Bevy's `many_foxes` example before scaling up.

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
