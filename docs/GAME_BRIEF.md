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
- **Decisions of 2026-11-09 (user):**
  - **Controls:** WASD movement, and you face the cursor. Left and right mouse are basic attacks; Q/E/R are skills; Shift is the dodge; F interacts (talk, pick up; Genshin-style). The camera aligns on a middle-button tap only, so R is free for a skill. Skillshots fire toward the cursor; targeted skills hit the enemy under or nearest the cursor.
  - **Starter skills:** the mixed six (sword strike, targeted; bow shot, skillshot; fire bolt, skillshot spell; block, held; dodge roll; heal, targeted on an ally or yourself), and more where possible. These are shared skills any character can learn; classes emerge from combinations.
  - **Death:** permanent, then you rejoin as a new identity. A development-only shortcut makes rejoining quick on scratch databases.
  - **Day length:** tune freely for testing. The server's effective clock stays as it is for now.
  - **HUD:** between minimal anime (Genshin, Blue Protocol) and classic MMO, not fully anime. Clean and readable, with enough information for combat: health and resources, the skill bar with cooldowns, a target frame, nameplates when relevant, and a proximity chat box. **Only relevant information on screen, no text clutter** (user): health, the resource bar and the skill bar are always visible. Everything else (target frame, nameplates, status icons, interaction hints, chat log) appears only when it matters and fades after. Icons, bars and shapes over words, with no labels or persistent instructions.
  - **Gameplay tracks, all wanted:** the island hosted by the server, town life, combat, and the HUD with proximity chat.
    - Per AGENTS.md, rules stay authoritative in the server and the client only presents, so combat and town life are built on the server with no client-side simulation.
    - Town residents are server characters on their behaviour graphs, which need no model calls. No scripted NPCs.
  - **Atmosphere, all wanted:** a day-night cycle, regional moods that blend as you walk, weather (rain, fog banks, wind in trees and grass), and a stylised sky and toon water.
  - **Unattended workers may touch:** the client, the tools, the rules crate, and the authority on scratch databases (never the lab worlds). No paid model calls.

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
  - The default is a mid zoom-tilt that turns with you. It was about 40° down and 16 m away; since 2026-11-09 it is 28° down, 22 m away, with a 50° field of view. The user found 40° showed too little of the world, and the flatter view lets rising ground and far trees show.
  - How far you can zoom out is bounded by sight: the camera distance is at most 2 × the sight radius (1.5 × before the wider default). Day sight barely allows zooming out past the default, while scout sight allows the full tactical view.
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
  | Turn to where you face | A middle tap, on request only (user, 2026-11-08; `R` was dropped on 2026-11-09 to free it for skills). The cursor moves with the ground while the view turns, so the facing doesn't change and the turn ends with it straight ahead |
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
- walking is 2.6 m/s and running 3.9 m/s. The look-dev client walks at the authored clips' 1.4 and 3.6 m/s instead. Settle one pair before the clips play on authority-driven characters: a brisker walk clip, or slower rules.
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

Both are settings for the game's own world (seed and laws), not the lab's. A generic km-scale placeholder world, with travel times, densities, landmark visibility and hosting costs, is drafted in [first world](FIRST_WORLD.md). Body size is so far only a client slider ("my size"). Real sizes of character would need the rules to carry a size: reach, separation, speed and sight.

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

**One way of rendering, with zones that differ by what is in them (user, 2026-11-08):**
- **Every thing has its own look, and keeps it everywhere.** A character, a creature or an item looks the same in every zone.
- **A zone differs by its contents:** buildings, plants, props, ground and materials. A cyberpunk town is built from cyberpunk assets; nothing gets re-skinned per zone.
- **One shading model for everything:** the same lighting bands, shadow treatment, outlines and post stack across the game. That shared shading is what keeps a character from looking out of place in any environment.
- **Zones may shift mood only gently:** light, sky, fog and colour grading. They never change how things are drawn.
- **A few invariants hold everywhere** so gameplay stays readable: character silhouettes and outlines, threat and faction colours, and the language of effects.
- **Reference:** Arcane-inspired. Try what the engine can do and iterate toward a specific style, keeping both the look and performance in mind. Blue Protocol, Genshin Impact and Zenless Zone Zero are further references (research in progress).
- The user is in the EU, which rules out Hunyuan3D, whose licence excludes the EU.
- **Assets for now: existing models only** (user, 2026-11-08). Build and evolve the world around pre-existing assets. Generate or create game-specific models later, once the world has enough shape and a backstory. It is too early now. Later the same day the user approved piloting our own generators in Blender (below).
- **Test environments to explore** (user, 2026-11-08), to see how the shared look and different scales hold up across contrasting places:
  - a nature world and a normal forest;
  - a spirit forest with glowing plants;
  - caverns;
  - a city of giants and a city of small folk;
  - a cyberpunk city, a fantasy city and a steampunk city.
- **Environment harness (built 2026-11-08):** each environment is a data file in `living/game/assets/envs/`: mood, ground, and slots of kinds with placement rules and heights. Assets plug in by folder (`assets/envs/<id>/<kind>/`), scaled to the slot's height, with placeholders until then. Glowing kinds get point lights, which the toon shader now bands. You walk through each environment with the game camera.
  - First finding: with real-size trees (9–16 m), the camera at 40° and 16 m sees mostly canopy in a dense forest, even with cut-away. Forest density and the camera need judging together.
- **Asset sources** (research of 2026-11-08):
  - **Fetchable without an account:** Kenney, KayKit and OpenGameArt CC0 kits.
  - **Need the user:** Quaternius MegaKits (an itch.io click), Fab (Standard licence: any engine, commercial use, no credit; needs an Epic login) and Sketchfab (mostly CC-BY, credit needed; an API token).
  - **Avoid:** Unity Asset Store (download only through the editor, scripting banned) and CGTrader/TurboSquid free models (they must ship in protected formats).
  - **Steampunk** has no complete free kit.
  - Keep a credits file for CC-BY assets.

**Anime-style references** (Blue Protocol, Genshin Impact, Honkai Star Rail, ZZZ; research of 2026-11-08):
- **Blue Protocol** (CEDEC 2020/2021 reports: [4Gamer](https://www.4gamer.net/games/467/G046741/20210826001/), [CGWORLD](https://cgworld.jp/feature/202011-cedec2020-bluep.html)):
  - one hard light-to-shadow step, with about 70% of a character lit;
  - shadow colour made by shifting hue and lowering brightness, keeping saturation;
  - artist-flattened face normals and no character normal maps;
  - outlines mostly from a post-process (Sobel on depth and normals, drawn outside silhouettes), with inverted hulls only on chin, ears and hair;
  - rim light from a depth post-process;
  - anime "photography" grading, sunshafts, and blue-near, green-far shadows.
- **HoYoverse:**
  - official talks cover grading, not character shading (Genshin rejected ACES for a LUT, [Unite 2020](https://www.docswell.com/s/UnityJapan/KWRPQ5-210617-unity-dojo20211mihoyozhenzhongyi));
  - reverse-engineered: lightmap masks (shadow weight, specular, ramp row), day and night ramp textures, and SDF face shadows ([HoyoToon](https://github.com/Melioli/HoyoToon/wiki/Using-the-Genshin-Shader));
  - nothing published on ZZZ.
- **Characters:** VRM 1.0 as the one humanoid skeleton.
  - Author characters in [VRoid Studio](https://vroid.com/en/studio/guidelines). Output may be used commercially, but an in-game character creator built from VRoid's own parts needs a separate pixiv licence.
  - Load them with `bevy_vrm1` 0.11 (Bevy 0.20): spring bones, look-at, VRMA animation retargeting, and expressions including visemes, which suit characters who talk.
  - MToon serves as a baseline only (no ramps, SDF faces or specular).
  - Keep Quaternius for animals and props.
- **First style test** (`living/game/src/style.rs`, `toon.wesl`):
  - every surface uses one toon material: two bands with a soft, brush-broken edge, hue-tinted shadows, a darker far side, a rim light and emission;
  - characters and buildings get `bevy_mod_outline` outlines, and ground, trees and props act as stencils that hide outlines behind them;
  - every parameter is a slider in F1 → Look, with an on/off comparison.
  - Blue Protocol techniques added the same day:
    - a hard step with about 70% lit;
    - shadows made by hue shift with saturation kept;
    - a finishing pass with depth and normal edge lines drawn outside silhouettes, a screen-space rim from depth, and a film gradient with saturation grading.
  - Skin materials get lighter, warm-hued shadows. That fixed faces turning flushed pink under the cool shadow hue.
  - Look-dev mode has real CC0 models: VRoid Sendagaya Shino and Vivi, and KayKit Adventurers. The VRoid characters move procedurally (idle, walk, talk, blink).
  - `bevy_vrm1` supports only VRM 1.0, and the CC0 VRoid samples are VRM 0.x. Converting to VRM 1.0 (for example with the Blender VRM add-on) would add spring bones and look-at later.
  - **Outlines (2026-11-09):** shell outlines (`bevy_mod_outline`) now go on characters only; environment models are stencils, and their lines come from the finishing pass. Shell outlines ignore fog and hidden parents, and they drew buildings' buried bases through hillsides, so the user saw black outlines with no object. This matches Blue Protocol, which takes most lines from the post-process. Character outlines also hide where their object is hidden or deep in fog.
  - Still to add: SDF face shadows and flattened face normals.
  - Frame rate in look-dev fell from 120 to about 60 fps with the high-poly VRoid models, prepasses and outlines. That needs profiling before scaling up.

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

**Generated assets in Blender (pilot, 2026-11-08):** the user offered local Blender and approved trying our own generators next to existing models.
- `living/tools/blender/nature.py` builds stylized trees, pines, bushes, rocks, flowers, glowing mushrooms and crystals for the meadow, forest and spirit styles. Assets are real-size, coloured by vertex colours on white materials so the toon material shades them, and canopies carry custom normals that point out from each clump so foliage shades as soft masses. Glowing parts use a material named `Glow`.
- `living/tools/blender/gen_nature.sh [count] [seed]` regenerates every set into the environment folders. The output is git-ignored: the script is the asset.
- Look-dev applies an environment slot's glow only to models without their own emissive material.
- **Asset view** (user's suggestion: iterate against the game's renderer, not Blender's): `living/tools/view_assets.sh OUT FILES [ENV] [HEIGHT]` runs the game with `LIVING_GAME_VIEW`. It photographs each model through the game's own toon, outline and finishing pass on a 1 m checker, from five angles and through the default game camera, plus six frames per animation clip. It writes one contact sheet per model and a `report.json` with measured size, triangles, materials, vertex colours, glow and clips. Without `LIVING_GAME_VIEW_OUT` it is interactive: drag orbits, the wheel zooms, `,` `.` change model. With it, no Blender MCP is needed.
  - Scripted runs (the asset view's batches and the environment tour) render headless into an image, with no window. A run can take just the shots it needs: `LIVING_GAME_VIEW_SHOTS` (named views, `game`, `YAW:PITCH[:ZOOM]`, clip frames) and `LIVING_GAME_TOUR_ONLY` / `LIVING_GAME_TOUR_SHOTS` (`default`, `close`, `YAW:PITCH:DISTANCE[:FOV]`). One model from one angle takes a few seconds.
- First tour: colours, glow and scale read correctly. Flowers are too small to read from the game camera, and spirit-forest trees vanish into the night mood. Both are generator tuning.
- **Second pass (2026-11-08):**
  - Two bugs explained the dull first look:
    - Vertex colours were written as sRGB but read as linear, so every colour came out roughly squared. They are now converted.
    - Emission was about 1,000× too weak for the camera's exposure.
  - Flowers are now patches about 1 m across that read from the game camera.
  - Spirit-forest trees: dark curved trunks with glowing bark lines, teal crowns, and vines ending in lanterns.
  - Glowing mushroom clusters and bright-tipped crystals.
  - A grass kind, with 900 tufts in the meadow.
  - Forest crowns sit on the upper half of long trunks, so the game camera sees trunks and floor.
  - New kinds: glow plants, logs and stalagmites.
  - Triangles: trees about 2.1–2.9k, small props mostly under 500.
  - Bloom is now part of each environment's mood (default 0.12; 0.3 in the spirit forest and caverns, 0.25 in the cyberpunk city), so glow haloes there.
  - Open:
    - The camera passes through spirit-tree vines and lanterns, which can fill the view.
    - Glowing parts look faceted up close.
    - The meadow's frame rate with about 1,150 models is unmeasured.

- **Authored animation (2026-11-08):** `living/tools/blender/animate.py` keys looping `idle`, `walk`, `run`, `talk` and `attack` clips (30 fps) onto VRoid characters from short per-clip angle tables. Legs use two-bone IK so planted feet stay on the floor and roll heel to toe. Blender's exporter can't round-trip a VRoid file (it drops the VRM extension, some textures and the morph names), so the script grafts the exported animations into a copy of the original GLB by node name. `gen_anim.sh` writes `assets/lookdev/anim/` (git-ignored); since 2026-11-09 it writes the animation library below, where Kimodo clips replace the keyed idle, walk, run and talk. Look-dev plays a model's clips when its file has them, with 0.22 s crossfades: idle, walk or run for you by how you move; idle, walk or talk for the line-up (`LIVING_GAME_ACT`). Blinking and the talking mouth stay procedural. Walking and running now move at the speeds the clips were made for (1.4 and 3.6 m/s, previously 2.6 and 3.9). Known gaps: skirts and hair don't move (no spring bones), there are no face clips, and the attack has no weapon.
- **Character recipes and spring bones (2026-11-09):** `living/game/src/characters.rs` builds a character from a recipe in `assets/characters/recipes.json`:
  - **Recipe:** a VRoid base, height, per-bone proportions (legs, torso, head, shoulders, build…) and colours (hair, eyes, skin, outfit). Folk ranges are adults 1.5–1.95 m, giants 4.5–5.5 m and small folk 0.55–0.7 m. Seeded random recipes fill crowds and `person` slots.
  - **Proportions:** helper joints scale proportions without shearing children, and the hips' translation follows leg length, so feet stay planted and every clip still plays.
  - **Colours:** the toon shader remaps each material group's mean texture colour to the recipe's colour, keeping the texture detail.
  - **Springs:** hair and skirts simulate VRM 0.x springs and colliders from the file (UniVRM's logic) at a fixed 60 Hz. Only the nearest 48 characters within 40 m are simulated, at about 9–11 µs per character per step.
  - **Controls:** `LIVING_GAME_CROWD`, `LIVING_GAME_PLAYER` and `LIVING_GAME_VIEW=recipe:…`.
  - **Known gaps:**
    - multi-colour garments collapse to shades of one colour;
    - soft hair streams almost horizontally when running;
    - each colour combination is its own material;
    - only two base faces;
    - size-dependent movement speeds are not in the rules yet.
- **Text-to-motion (2026-11-08):** NVIDIA Kimodo SOMA-RP v1.2 runs on the DGX Spark (`~/kimodo-test`, venv, PyTorch 2.11 for CUDA 13 on aarch64; setup notes in `.local/kimodo/README.md`). A 4 s motion takes about 25 s per prompt, mostly loading the Llama 3 8B text encoder (gated: the user's Hugging Face account has access), and peaks at 15 GB of GPU memory. `animate.py --kimodo NAME=motion.npz` retargets a SOMA motion onto VRoid J_Bip: both rest in a T-pose with identity rest rotations, so each bone takes its mapped joint's global rotation turned half round Y, relative to its nearest mapped ancestor; the hips keep sway and bob but not travel. First prompts (walk, idle, talking with gestures, an overhead sword swing) read naturally on Vivi; the walk and the talk look more alive than the hand-keyed ones. Not yet done: looping (the clips are 4 s takes), foot-contact cleanup after removing travel, and prompts that start and end in a matching pose. Licences: Kimodo models under the NVIDIA Open Model License (commercial use; the notice must ship with distributed copies); the text encoder under the Llama 3 licence (attribution "Built with Meta Llama 3").
- **Animation library (2026-11-09):** 27 clips per VRoid character, listed with prompts, seeds and parameters in `living/tools/blender/clips.json`.
  - **Generation:** `living/tools/kimodo/spark.sh` generates the Kimodo takes on the Spark in one process: about 16 s to load, then 3–4 s per motion. `gen_anim.sh` (`animate.py --library`) makes them game-ready for both characters into `assets/lookdev/anim/` and writes `<character>.clips.json` with each clip's length, loop flag, speeds and source.
  - **Loops:** idle, idle_look, walk, walk_brisk, run, run_fast, sneak, talk, talk_explain, listen and sit_idle are cut where pose and foot contacts match, and their seams are spread.
  - **One-shots:** wave, point, sit_down, stand_up, sword_slash, sword_overhead, sword_thrust, block, dodge_roll, hit, death, cast and bow_shoot. Kimodo keyframes them to a shared neutral standing pose at the ends that should blend with idle. sit_idle and stand_up continue from sit_down.
  - **Feet:** planted feet are pinned with the leg IK.
  - **Hand-keyed:** nod and shake_head are keyed on the neutral pose, because every Kimodo seed either bowed or barely moved its head. The keyed `attack` loop is kept for repeated swings. The keyed idle, walk, run and talk are replaced; their names now hold the Kimodo clips.
  - **Natural speeds** (Vivi / Shino): walk 1.44 / 1.48, walk_brisk 2.03 / 2.10, run 3.15 / 3.25, run_fast 3.50 / 3.61, sneak 0.75 / 0.77 m/s. walk and run are time-scaled to the look-dev's 1.4 and 3.6 m/s by default. The rules' 2.6 / 3.9 pair is one flag away (`--speed 2.6 --run-speed 3.9`, or `--target walk_brisk=2.6 --target run_fast=3.9`). It is best served by walk_brisk (×1.30) and run_fast (×1.10), because the casual walk can only be sped up ×1.4, to 2.0 m/s.
  - **Known flaws:**
    - The wide VRoid skirts are rigid, so legs and seated thighs pass through them, and hanging hands sink into Vivi's skirt.
    - The sit poses recline as if against a backrest.
    - The sword and bow clips have no props.
    - dodge_roll travels 1.9 m and death ends about 1 m from where it started. The game has no root motion yet.

- **Tree variety (2026-11-09; the user saw forests of identical trees):**
  - **Species:** nature.py now makes oak, birch, spruce, coppice, young trees, saplings and dead snags. The broadleaf tree picks one of five growth forms, and trees lean and curve by seed.
  - **Spirit trees:** four forms, plus 20–30 m giants with buttress roots, and glowing saplings.
  - **Slots:** the forest, meadow and spirit-forest slots mix species and ages, keeping the large-tree count.
  - **Materials:** bark and leaves share one material per tree, which cut the meshes at the island forest edge from about 3,600 to 2,100.
  - **Open:** the sapling slots cost about 2 ms per frame on the island for an unknown reason (to profile with static-prop merging).

- **Scenery polish 1 (2026-11-09):**
  - **Broadleaf crowns** are built as a few big lobes with hidden faces dropped. Leafy points stick out at the silhouette, and normals point out from the crown's centre, so each crown shades as one mass. Broadleaf triangles roughly halved.
  - **Conifers** have tiered pads with notches and dark undersides; about 45% of pines are flat-topped Scots pines.
  - **Rocks** come in four crisp shapes, and **logs** have root plates.
  - **Buildings:** thick roofs that darken towards the eaves with sagging ridges, windows and doors set into the walls, leaning chimneys, and capped plinths. Footprints are unchanged, so the planner's table still matches.
  - **Blind A/B test** (46 pairs, order randomised, labels hidden): the new trees, rocks and props won; the buildings tied at game distance; the crystal base was reverted.

- **Buildings (2026-11-08):** `living/tools/blender/buildings.py` generates:
  - **fantasy:** timber-frame houses, townhouses, watchtowers, wall segments, market stalls and lamps;
  - **steampunk:** brick townhouses with copper mansards, factories, smokestacks, pipes, crates and lamps;
  - **small folk:** turf burrows, mushroom houses and tree-stump houses;
  - **giants:** the fantasy grammar at giant scale.

  Each kind has one exact height that its slot uses, so the harness doesn't rescale it. Details are built for the inhabitant's height: giants' doors are about 6 m and their steps about 0.5 m high; small folk have 0.7 m doors.

  `gen_buildings.sh` regenerates all 20 sets in about 3.5 s. Triangles: about 3.7k per house, 5.8k per townhouse, 8.2k per factory.

  Fixed in the shader: reds and oranges take a quarter of the shadow hue shift, so red roofs deepen instead of turning magenta under violet shadow hues. Ring slots can face inward (`"face": "in"`).

  **Forms and new kinds (2026-11-09; the user saw towns of same-sized boxes):** `buildings.py` builds houses from storeyed blocks (stone or timber-framed storeys, jetties, gable, hip and half-hip roofs, cross gables, dormers, lean-tos, turrets) in forms per kind, each in its own size:
  - **fantasy houses:** cottage, house, longhouse, L-house and corner house;
  - **townhouses:** narrow (gable to the street, 2–3 storeys, shopfronts and hoist beams), wide (4–5 bays, wall gables or dormers) and corner (a turret on the corner);
  - **new fantasy kinds:** inn (hanging sign, benches, a carriage arch), guildhall (open arcade, bell turret), chapel (buttressed nave, west tower with a spire, apse), workshop (smithy or workshop with a fenced yard) and barn (barn or shed);
  - **giants:** the house forms and a longhall; **small folk:** burrow, big mound, mushroom and stump houses and a mushroom hall; **steampunk houses:** narrow and wide.

  Corner forms come in both hands. Triangles (mean, max): cottage 2.6k/3.2k, house 4.0k/4.5k, longhouse 3.4k/4.0k, L-house 5.4k/6.3k, corner house 6.2k/6.7k, narrow townhouse 4.4k/4.8k, wide 5.4k/6.6k, corner 5.2k/6.6k, inn 8.1k/10.1k, guildhall 4.7k/6.0k, chapel 8.6k/9.7k, workshops 2.8–3.9k, barn 1.8k, steampunk narrow 7.0k/8.1k. Kinds with forms have no fixed height; each run writes every model's footprint, height and form beside the models, and `--table` gathers them into `buildings.json` (`models`, plus each kind's envelope in `kinds`). The planner sizes each lot to one model and records it (`Lot::model_file`). `ENVELOPES` is gone. `gen_buildings.sh` makes 8 models per form (336 models) in about 11 s. The look-dev cities still scale every model of a kind to their slot's single height, so cottages and longhouses there grow to the house slot's 8 m.

  **Foundations and footprints (2026-11-09):** the origin is now the floor, centred on the footprint. Below it every model has a stepped stone foundation under its ground outline: about 1.8 m for a person's buildings, 5.1 m for giants', 0.6 m for small folk's, and 0.4–0.6 m for lamps, stalls, crates and pipes. On a slope it reaches into the ground; on flat ground it is buried. Each model's footprint (roof overhangs and steps included) is measured when it is built (see forms above). `gen_buildings.sh` also writes [`living/rules/data/buildings.json`](../living/rules/data/buildings.json), which the settlement planner reads. A `well` kind joins the fantasy, giants' and small folk's sets. A foundation costs about 120 triangles. **The client must place models by their origin:** look-dev's fit still puts the bounding box's bottom on the ground and scales its whole height to the slot, so until it changes, buildings float by their foundation and shrink by about 18%.

  Open:
  - Windows sit on the walls rather than being cut in, and there are no interiors.
  - In the giants' and steampunk cities the gameplay camera sees mostly plaza.
  - Outlines draw through heavy fog.

**Performance pass 1 (2026-11-09; island, headless 1600×900, uncapped, development Mac):**

`LIVING_GAME_PERF` flags switch one cost off at a time, and `LIVING_GAME_FPS_CAP=0` runs uncapped (`living/game/src/perf.rs`).

Measured costs in the town square (21.8 ms in total):

| Cost | Time |
|---|---|
| Shadows of scenery | about 4.3 ms |
| Shadows of characters | about 5.7 ms |
| Drawing characters | about 2.3 ms |
| Edge lines, outlines, bloom and prepasses | 1–3 ms each, or less |

Fixes:
- the sun's shadows use three cascades to 90 m (was four to 160 m);
- things under 1.6 m cast no shadow;
- characters' face parts never cast one, and characters beyond 26 m cast none;
- `living/tools/merge_primitives.py` merges a GLB's same-material primitives within each mesh. VRoid hair is dozens of primitives: Vivi goes from 95 to 17 draws per pass, Shino from 67 to 18. `gen_anim.sh` runs it on every animated character.

| Spot | Before | After |
|---|---|---|
| Town square | 21.8 ms | about 14 ms |
| Forest edge | 19.3 ms | about 11–13 ms |
| Small-folk hamlet (many props and people) | 29 ms | about 20–25 ms |

Other agents loaded the machine during these runs, so the figures are indicative.

**Performance pass 2 (2026-11-09; same benchmark, both machines):**

**Cause.** The island was limited by neither the GPU nor any one system. The development Mac's GPU ran at about 50% (25–30% of that from other apps), and the main and render threads mostly waited. The wait was in the render world's batching: each distinct material and mesh slab is a batch set in every view (camera and three shadow cascades) and pass. Every frame, each batch set writes its buffers through `queue.write_buffer`, and wgpu allocates and frees a staging buffer for every write. A CPU sample (`sample <pid> 4`) put most of the frame in `write_binned_instance_buffers`, `submit_pending_command_buffers` (the frees) and `prepare_preprocess_bind_groups`. Shadow-map size had no effect (1024 and 4096 alike), and neither did resolution (800×450 alike).

**Fixes:**
- **Toon materials are shared by content** (`lookdev::convert`). Every model file brought its own copies of the same materials: the environment kits hold 1,047 materials but only 14 distinct ones. Scenery in view went from hundreds of materials to 4.
- **Characters share their base's materials** (`characters::recolor`, `toon.wesl`). The material holds its texture's mean colour, and each mesh's `MeshTag` holds its recipe colour; the shader derives the same remapping. Before, every character had about ten recoloured materials of its own, which put 90 materials in view for 12 people. Now there are 15, whatever the crowd's size.
- **People per settlement doubled** (`island.rs`): up to 16 at house fronts and 8 in the square.

Mean of the last three frame reports, two runs each, 1600×900 headless and uncapped. The development Mac is an M4 Pro (load average 9–11 from other agents' work). The dev-box is a Radeon 8060S on Vulkan (load average 5–8).

| Spot | Mac before | Mac after, old cap | Mac after, new cap | Dev-box before | Dev-box after, old cap | Dev-box after, new cap |
|---|---|---|---|---|---|---|
| Small-folk hamlet (1776, 1456) | 17.6 / 18.8 ms | 4.6 / 4.8 ms | 5.1 / 5.1 ms | 13.5 / 15.6 ms | 4.7 / 5.3 ms | 5.8 / 5.7 ms |
| Town square (416, 256) | 12.6 / 12.8 ms | 4.5 / 4.3 ms | 4.9 / 4.9 ms | 10.5 / 9.9 ms | 4.5 / 4.4 ms | 5.3 / 4.9 ms |
| Forest (690, 1600) | 10.4 / 10.3 ms | 4.4 / 3.5 ms | 3.6 / 3.4 ms | 6.0 / 6.0 ms | 3.7 / 2.7 ms | 3.7 / 2.6 ms |

Sharing the scenery materials alone took the Mac to 8.9, 7.05 and 3.7 ms. Crowds now cost little: about 25 people near the hamlet run at 5.1 ms, 49 at 6.1 ms and 73 at 7.2 ms on the Mac. At the same people count, screenshots are pixel-identical to before at the hamlet, the town street and the forest.

What remains at the hamlet on the Mac: characters about 1.0 ms, sun shadows 1.2 ms, prepasses and edge lines 0.5 ms, and small things 0.1 ms.

Open:
- Fixed: `living/tools/merge_primitives.py` used to copy a shared vertex buffer once per merged primitive (Vivi's hair held about 420k vertices for 6.7k triangles). It now copies each distinct vertex set once, and the animated Vivi file shrank from 63 MB to 22 MB.
- `LIVING_GAME_PERF=diag` reports what each view draws (meshes, materials, triangles, characters' share) and Bevy's per-pass CPU times. Metal reports no GPU times; Vulkan should.

**Claude–Blender integration** (research of 2026-11-08):
- **Backbone: headless scripts** (`blender -b -P`), versioned in the repo. No socket or telemetry, reproducible, and N processes can run in parallel. The agent checks its work through rendered contact sheets and numeric checks (dimensions, triangle budget, silhouette against a reference, a re-import round trip), reviewed by a fresh-context subagent ([blender-game-skills](https://github.com/majidmanzarpour/blender-game-skills), [blender-kiln](https://github.com/elithril/blender-kiln)).
- **Live inspection: the official [Blender Lab MCP server](https://www.blender.org/lab/mcp-server/)** (GPL-3.0, Blender 5.1+, the server behind Anthropic's Blender connector). It is optional. It runs model-written code unguarded, so use it on localhost only.
- The community [MCP for Blender](https://github.com/ahujasid/mcp-for-blender) (MIT; `blender-mcp` now installs `mcp-for-blender`) sends anonymous usage telemetry by default (turn it off with `DISABLE_TELEMETRY=true`) and had several 2026 CVEs. Its asset search and paid generation are its only advantage here. Both add-ons default to port 9876.
- Reported limits: blockouts, layout and batch scripts work reliably. Organic shapes, topology, weight painting and IK do not. Procedural materials must be baked before glTF export.

**Characters and animation tooling** (research of 2026-11-08; licences checked, aarch64 untested):
- **Bases:** a person makes two to four base bodies in VRoid Studio (GUI only). The agent derives variants in bpy with the [VRM add-on](https://github.com/saturday06/VRM-Addon-for-Blender) (Blender 4.2–5.3): proportions through bone scaling and shape keys, recoloured materials, outfit swaps, and weights carried over with Data Transfer.
- **Rigging:** every humanoid shares the J_Bip skeleton, so no learned auto-rigger is needed. Fit the template armature, apply automatic (heat) weights, and transfer weights onto outfits.
- **Clips:** the Quaternius Universal Animation Library 1 and 2 (CC0, about 250 clips) retargeted to J_Bip by script. Their bone names are unverified.
- **Text-to-motion:** NVIDIA [Kimodo](https://github.com/nv-tlabs/kimodo) SOMA-RP models (NVIDIA Open Model License: commercial use allowed, no claim on outputs, and a required notice). Its SMPL-X model is non-commercial.
- **Quadrupeds:** Quaternius Ultimate Animated Animals (CC0) or procedural gaits.
- **Excluded:**
  - HY-Motion and Hunyuan3D: their licence excludes the EU, outputs included.
  - Weights trained on AMASS/HumanML3D (MDM, MoMask, MotionGPT, T2M-GPT) and SMPL-based mocap such as GVHMR and WHAM: non-commercial.
  - Mixamo: browser only, and raw files can't be redistributed.

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
