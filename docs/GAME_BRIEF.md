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
  - **Controls:** WASD movement, and you face the cursor. Left and right mouse are basic attacks; Q/E/R are skills; Shift is the dodge; F interacts (talk, pick up; Genshin-style). The camera aligns on a middle-button tap only, so R is free for a skill. Skillshots fire toward the cursor; targeted skills hit the enemy under or nearest the cursor. F, and C, I and K beside it, are built as [verbs](#verbs-acting-on-the-world-2026-11-10) (2026-11-10).
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

- The authority already gives every character a sight range (11 tiles by day, 6 at night, 9 with a torch) and hearing 9 (since 2026-11-11 the script's per-creature `senses` law, docs/WORLD_RULES.md), and minds receive only what falls inside them. Players are the exception today: they receive every table.
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
   - *Built 2026-11-09* ([perception](PERCEPTION.md)): the authority works out each player's perceived set (sight by day and night, a torch, a sight line through walls and rock), per-sender `seen_*` and `my_*` views deliver it with a narrow motion row, and minds' and audit tables are private, read by the mind service and the observer as the database owner. Region views were not needed: a per-sender view moves with the character on the authority. The game client reads only those views, and `scoped` is the default build since the client landed the same day ([what the client shows of others](#what-the-client-shows-of-others-2026-11-09)).
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
  - **Faces and hair (2026-11-09):** `living/tools/face_normals.py` (run by `gen_anim.sh`) flattens the VRoid face's normals toward an ellipsoid round the head, stores the head's rest forward in the face skin's second UVs, writes `<character>.face.png` (a per-face shadow-threshold map for light from the right and from the left), and blends hair normals 35% toward a capsule round the head. `toon.wesl` shades by material kind (`style::Kind`, in `shade.w`; no per-instance materials): the face's shadow edge comes from its map and the sun's angle round the head (skinning turns the forward), and its shadow-map lookup sits 12 cm in front so bangs cast no blotches; eyes, brows, lashes and mouth take only cast shadows; hair gets a view-led Kajiya-Kay "angel ring" with comb-tooth edges, a rim kept off its undersides, and shadows in its own hue when it is coloured. VRoid characters now take the person outline (1.8 px, thinning to 60% from 8 to 30 m) in a warmer line colour. Cost on the Mac: none measurable (town 5.0 ms before and after; a crowd of 40, 5.7–5.8 ms both). Blind A/B against the previous look: the new faces won or tied every pair; hair won 4 of 5 in the last round, losing on white hair, where the old noisy normals gave more pink-tinted strand shadow. Open: white hair reads flatter; the ring's edges are streaky on some cards; characters' outlines still draw over things in front of them (seen at the town well).
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
  - **One-shots:** wave, point, sit_down, stand_up, stand_up_ground, sword_slash, sword_overhead, sword_thrust, block, dodge, hit, death, cast and bow_shoot. Kimodo keyframes them to a shared neutral standing pose at the ends that should blend with idle. sit_idle and stand_up continue from sit_down.
  - **Feet:** planted feet are pinned with the leg IK.
  - **Hand-keyed:** nod and shake_head are keyed on the neutral pose, because every Kimodo seed either bowed or barely moved its head. The keyed `attack` loop is kept for repeated swings. The keyed idle, walk, run and talk are replaced; their names now hold the Kimodo clips.
  - **Natural speeds** (Vivi / Shino): walk 1.44 / 1.48, walk_brisk 2.03 / 2.10, run 3.15 / 3.25, run_fast 3.50 / 3.61, sneak 0.75 / 0.77 m/s. walk and run are time-scaled to the look-dev's 1.4 and 3.6 m/s by default. The rules' 2.6 / 3.9 pair is one flag away (`--speed 2.6 --run-speed 3.9`, or `--target walk_brisk=2.6 --target run_fast=3.9`). It is best served by walk_brisk (×1.30) and run_fast (×1.10), because the casual walk can only be sped up ×1.4, to 2.0 m/s.
  - **Known flaws:**
    - The wide VRoid skirts are rigid, so legs and seated thighs pass through them, and hanging hands sink into Vivi's skirt.
    - The sit poses recline as if against a backrest.
    - The sword and bow clips have no props.
    - Fixed in the client polish pass below: dodge_roll travelled 1.9 m and death ended about 1 m from where it started.

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

- **City styles and outfits (2026-11-09):**
  - **Cyberpunk** (`buildings.py`):
    - narrow, wide and corner blocks; slender towers; a landmark megatower (about 110 m);
    - a food court, garages and fabs;
    - neon signs in Glow colour materials, holo-billboards, cables, kiosks, food stalls, walkways and lamps.
  - **Steampunk:** narrow, wide and corner houses, a pub, an exchange hall, a clock tower, a mooring mast with an airship, a foundry and gearworks, an iron-and-glass arcade, and gas lamps.
  - **Table:** `buildings.json` lists 46 kinds and 528 models, all within budget. The look-dev cyberpunk and steampunk cities use them.
  - **Outfits:** `outfits.py` and `gen_outfits.sh` make 12 pieces per VRoid base, fitted from a body hull and skinned to J_Bip with the body's weights:
    - cyberpunk: cropped jacket, high collar, visor, glow trim, cargo straps;
    - steampunk: long coat, waistcoat, top hat, bowler, brass goggles, gloves, boots.

    The pieces are git-ignored under `assets/lookdev/outfits/`.
  - **Not done yet:**
    - **Outfit wiring:** done on 2026-11-09 in `characters/outfit.rs`. Pieces bind to the character's own bones, or to the recipe's helper scale joints, and hide the base parts they cover (boots hide shoes). Recipes gain `outfit` and per-slot outfit colours. The `fantasy`, `steampunk` and `cyberpunk` style presets dress random people by place: look-dev cities by their id, island settlements by their style, crowds through `LIVING_GAME_CROWD=N[:seed][:style]`. Fixed along the way: characters' scenes were reloaded about 20 frames after spawning, which silently dropped their proportions, springs and shadow rules; `spawn` now holds the file's root handle.
    - **Cyberpunk at night** reads too dark and hazy.
    - **The long coat** bulges at the shoulders.

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

**Atmosphere (2026-11-09; client presentation only):**
- **Day-night:** `daylight.rs` follows a mood curve stored as data in `island.json`: sun and moon arcs, light, sky, fog, shadow hue, grading, bloom and glow. Windows and lamps glow at night; lamp lights are capped to the nearest 14. Connected, the hour comes from the authority's `world` clock. Offline: `LIVING_GAME_HOUR`, and `LIVING_GAME_DAY_MINUTES` (24 by default).
- **Regional moods** blend from the region kinds round you: spirit grove dusky and glowing, wetlands misty, highlands crisp, beach bright.
- **Weather** (`weather.rs`): clear, rain, fog and storm in spells taken from the world clock, so every client sees the same weather. Rain streaks, wet surfaces and puddles; drifting fog banks; lightning; wind sway for plants in every pass through mesh tags, with no per-instance materials. `LIVING_GAME_WEATHER` forces a state.
- **Sky** (`sky.rs`): a gradient dome with toon clouds, sun, moon and stars. **Water** (`water.rs`): a shared toon material with banded depth, shore foam, animated bands, a sky reflection and rain rings.
- **Cost:** none in clear weather (town 5.0, forest 3.5, hamlet 5.3 ms); fog at dawn adds about 0.5 ms in the forest. `LIVING_GAME_PERF=noatmo` turns it off.
- **Open:**
  - dawn in the town is heavily orange-brown;
  - storms read flat;
  - fog washes out vistas beyond about 40 m;
  - the spirit grove is low in contrast;
  - no cloud shadows yet;
  - the connected clock path is untested live.

**Textures, phase 1: the ground (2026-11-09; client presentation only).** The user found everything flat.
- **Textures** (`living/tools/textures/paint.py`, `just living-game-textures`; git-ignored output in `assets/textures/`):
  - painted procedurally with numpy and Pillow from brush dabs, shape clusters and posterised value patches, all periodic, so the tiles are seamless and regenerate identically;
  - 512 px each, as factors round mid-grey with a height channel in alpha; the vertex colours still carry every palette and regional colour;
  - ground kinds: grass, lush grass, dry grass, forest floor, dirt, sand, rock, cobble, flagstone, mud, spirit moss, and pavers for the cyberpunk town;
  - `--set material` already paints bark, planks, plaster, stone, brick, shingles, metal and leaves for phase 2.
- **Material** (`terrain.rs`, `terrain.wesl`): one extension material for every island chunk and look-dev ground disc, so the ground stays a single batch set.
  - Its lighting copies `toon.wesl`'s plain-surface path: bands, hue-shifted shadows, night fill, rim, point lights, rain darkening and puddles, which now gather in the joints between stones. Toon parameters are copied from the toon materials whenever they differ.
  - Chunks carry one blend weight per layer: three `Unorm8x4` vertex attributes, main pass only. The weights come from terrain class and region, blended over about 25 m like the colours.
  - Roads stay crisp, and their surface follows the settlement's style: flagstone squares and cobbled streets, all setts in Kettlebridge, panels in Lanternquay, earth tracks between settlements.
  - The shader samples the strongest four layers here, blends them by height and projects triplanar on slopes, which turn to rock. Patches about three tiles wide switch between two scales and angles of each layer, and a slow macro layer varies value and hue. Detail fades to plain colour between 30 and 85 m.
- **Cost:** within noise at the town, forest and hamlet (5.1, 4.2 and 5.2 ms, before and after alike), and +0.14 ms on the town vista. The scenery here is limited by per-batch CPU work, not by the GPU, so fragment cost hardly shows on this Mac. `LIVING_GAME_PERF=noterrain` draws the ground with the plain toon material for A/B.
- **Blind A/B:** textured beat plain in 23 of 24 pairs (6 spots, noon and dusk, default and vista shots), with 1 tie under the grove's canopy. A softening of grass and moss was indistinguishable and was dropped. Removing the forest floor's posterised patches, whose lattice repeated, won 7 of 8 pairs with sides swapped.
- **Open:**
  - The pavers' grid reads a little mechanical.
  - Roads and paths keep their stair-stepped 1 m edges.
  - The ground's GPU cost should be checked on a GPU-bound machine.
  - Model textures (phase 2) belong in the toon shader (done below).

**Textures, phase 2: scenery models (2026-11-09; client presentation only).**
- **Shared lighting:** `toon_light.wesl` holds the toon parameters, sway, colour helpers and the lighting pieces; `toon.wesl` and `terrain.wesl` compose it, and the vertex and prepass shaders import from it, so the copies are gone. With detail off, the image matches the old shader within run-to-run noise.
- **Surface tags, not materials:** the generators write each triangle's surface into the vertex colour's alpha (until now always 1). Nature maps it from material names, buildings from palette entries. Choosing the texture by material would have split the shared scenery material into about five, each a batch set in the camera and every cascade. The material carries one flag and a 16-entry table (tile size, strength, mapping), so material and batch counts are unchanged (41 toon materials).
- **Set:** `paint.py --set material` paints 16 layers (bark, leaves, wood, planks, plaster, stone, boulder, brick, shingles, tiles, thatch, metal, copper, concrete, cloth, glass). Their order lives in `living/tools/textures/surfaces.py`, shared by `paint.py` and both generators. The game checks `material.txt` against it and draws no detail on a mismatch.
- **Mapping:** in each model's own frame, so rotated and scaled models keep level courses and metre-sized tiles. Built surfaces and boulders are mapped flat from each face's normal; bark and leaves are triplanar. Detail fades from 20 to 55 m; characters get none. `LIVING_GAME_PERF=nodetail` or `detailonly=a+b` for A/B.
- **Cost:** within 0.1 ms at the town, forest and hamlet on the Mac and the dev-box; main-pass GPU time on the Radeon 0.536 → 0.558 ms.
- **Blind A/B:** detail won 28, lost 4, tied 12 in the final round. Trees, rocks, walls and props kept. Slate and clay roofs lost every round (grain at distance, then soot-like blotches) and are set to strength 0. Cyberpunk blinds read as pinstripes in vistas and are untagged.
- **Open:** roofs; untagged parts (38% of cyberpunk triangles, 42% in the spirit forest, mostly glow plants); grass, flowers and petals; everything beyond 55 m. The relief option (painted height moving the shadow edge) is built but off and untested.

**Client batch after the expedition (2026-11-09; client presentation only).**
- **Gaits** (`gait.rs`): the clip is chosen from each body's actual speed for connected bodies, your character and look-dev crowds. Walking clips serve up to 2.8 m/s, running clips above; within a family the clip nearest in natural speed plays, scaled by stride, with hysteresis. Speeds come from each character's `.clips.json` sidecar. At 2.6 m/s the step rate fell from 3.48 to 2.47 a second (walk_brisk, not walk ×1.86) and drift per contact from 2.3 to 0.5 cm; at 3.9 m/s run_fast cut drift from 3.1 to 0.9 cm. `LIVING_GAME_FEET=<file>` records toe positions; `living/tools/foot_slide.py` reports slide and cadence.
- **Arrival hitches** (`island.rs`): a chunk's things spawn nearest first within 12 cost units a frame (a model 1, a person 6), only once their files have loaded; files are fetched when the chunk's ground builds, about 110 m ahead. Character base files stay loaded for the session (the queue had exposed scene rebuilds that dropped outfits). On `road:town>village3@run`, the worst frame fell from 95.6 to 34.5 ms and the village3 arrival from 57 to under 12.5 ms; mean and p99 unchanged. `LIVING_GAME_PERF=hitch=MS` logs slow frames and what arrived in them; `nobudget` turns the budget off.
- **Outlines through scenery:** scenery stencils use per-pixel depth (`style::stencil()`), so a canopy in front hides a character's outline; the ground keeps the flat stencil (`ground_stencil()`) so soles keep theirs. A character behind a hill still shows its outline.
- **Rock that blocks walking** reads as dark bedded stone with strata on steep faces and a dark rim at the walkable edge. `Terrain::Rock` rides crisp per tile in the ground vertex colour's alpha; the ground gains a 13th texture layer, `cliff` (regenerate with `just living-game-textures --set ground` on each machine). Walkability is unchanged. Blind A/B: readability won all 5 rock pairs in both rounds; look 3–2–1, then 2–2–2. Judges disliked small boxy rock tiles on gentle ground, a shape the rules decide.
- **Cost:** town, forest and hamlet within noise (5.2, 4.4, 5.4 ms); material and mesh counts identical.

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

## Town life in the client (2026-11-09)

Presentation only: the authority decides what every resident does ([town life](TOWN_LIFE.md)); the client draws it from public rows and sends my gestures through `human_act`. Code: `living/game/src/town.rs`, with `live.rs` (clips, facing, indoors), `net.rs` (subscriptions), `weather.rs`, `camera.rs` and the HUD.

- **Data** (as first built; since the perception views the client reads `seen_doing` instead of the join, [below](#what-the-client-shows-of-others-2026-11-09)). `act_card` (17 rows) and `weather` (one row) are subscribed once per connection; `doing` is joined to the near body window like `fighter` (`SELECT doing.* FROM doing JOIN body ON doing.id = body.id WHERE <chunk ranges>`). No whole-world query. A connected client holds 21 live queries instead of 18.
- **What residents are seen doing** comes from `doing.code` through `act_card`: by skill name for the skills drawn for, else by the card's `look`, else nothing over locomotion, so a skill the rules add shows without a client change.

  | Skill (look) | Drawn as |
  |---|---|
  | `keep`, `cook`, `craft`, `store` (work) | `work`: busy hands at a stall or a door |
  | `gather`, `plant`, `take`, `tend` (work) | `gather`: bending to a bush and back |
  | `read` (work) | `idle_look` |
  | `eat`, `play` | `eat`, `play` |
  | `rest` | settling down (`sit_ground_down`), then sitting cross-legged (`sit_ground`); about 3 in 10 stand at ease (`listen`); in rain everyone stands (`idle_look`), under the eaves |
  | `wave`, `nod` (gesture) | the clip once, toward the one greeted: a wave 2.1 s (×1.4), a nod 1.4 s; it plays to its end unless the body moves off |
  | `face`, `step_aside` (turn, step) | only the body's own motion |
  | `sleep` | not drawn (indoors) |

  A working body faces its spot (`doing.x/y`) or the one it is aimed at. Unknown codes and looks fall back to idle and locomotion, as combat's do.
- **Indoors: hidden, not a lit window.** A sleeper, or someone resting within 3.5 m of their own door (sheltering at home, keeping warm; the authority now says so on the `doing` row, `indoors`), is not drawn, gets no nameplate and is not targeted; they reappear at the door when they come out. A lit window would need per-house window geometry that buildings don't expose, and the island's windows already glow at night.
- **Turning on the spot.** A standing body takes its facing from its own segment, `heading` + `turn` × elapsed (up to `turn_s`), so the turn before a gesture and `face` turn the body in place instead of sliding. Drawn yaw eases toward the wanted facing (1/16 s), so stops and new aims never snap.
- **Rain** follows the `weather` row in connected mode (rain or clear), eased over 6 s; joining mid-spell shows the sky as it is. Look-dev keeps its schedule and `LIVING_GAME_WEATHER`.
- **My gestures: G waves, B nods** (clear of WASD, the skill bar and F). They go to the person under or nearest the cursor, else the nearest in reach ahead (12 m for a wave, 6 m for a nod). My clip is predicted at the press, and my character turns to whom I greet. The answer is the resident's own `doing` row (the nod) and my `experience` ("… answers your greeting (nod)."). It shows plainly: their nameplate for 3.5 s, and the camera's conversation framing takes in both of us. No text.
- **HUD.** No labels for activities. The only additions are that answerer's nameplate and no plate over someone indoors.
- **New clips** (Kimodo on the Spark, `living/tools/blender/clips.json`; `gen_anim.sh` regenerates): `gather`, `work`, `eat`, `play`, `sit_ground_down`, `sit_ground`. 24 takes in 105 s; seeds picked by hip and head drop, hand travel and root drift.
- **Cost on the Mac** (M4 Pro, uncapped, `LIVING_GAME_PERF=diag`, 30 s windows on the scratch island, one client at a time, base `f2a19f2`): calm village at 10:00, base 5.11 / this 5.04 ms mean (worst 8.1 / 8.3); busy inn crowd at 20:30 (30–40 residents within 30 m), 6.17 / 5.96 ms (worst 11.6 / 11.2). Toon materials (42), materials per view (36 calm, 35 busy) and the people's share (33) are identical across arms and do not grow with residents. Frame hitches (30–170 ms with nothing arriving in the frame) showed in both arms on other windows while the Mac was loaded by other work (load average 4–5); none is from this change. That is one window per arm, not a repeatability study.
- **Bytes.** Whole-client bytes differ between world days more than between arms: the base client sent 3.8 kB/s at the inn at 20:18–21:39 one day and 8.3 kB/s in the same window the next, against this client's 5.6 kB/s. So the new queries were measured alone through verify-client's probe (`drive.py`, nothing else connected). The `doing` join sends 0.56 kB/s on the market street at 11:00 (44 rows initially, 1.5 kB) and 1.16 kB/s at the inn at 21:00 (65 rows, 2.1 kB), against 1.94 kB/s for `body` in the same day window. `act_card` costs 339 B once and `weather` 26 B. Rows arrive only for bodies in the window, at most one each.
- **Proof** (2026-11-09, scratch `verify-townclient`, module from `b7cf7fb`): headless connected photographs at fixed spots. The town market at 10:12, the inn at 20:12 and close at 21:45, the market at 00:42, rain on the market and at the inn after 45 s of `set_weather`, my wave at a stall keeper answered by a nod (`skill_use`: `greeted Roli` → `answered Photographer` 1.27 s later), and a wolf placed in the market (10 residents fled, 13 attacked, 64 turned to face it in 12 s). Scenes were set with admin `place_at`, `set_weather` and `kill`; my gestures went through the game's own G/B path. verify-client's suite passed (17, the 2 known XFAILs, permission matrix 184 calls, 0 mismatches); verify-player's gestures passed 9 of 9.
- **Still off:**
  - At the fixed 22 m view a fight or a nod is small; only a greeting brings the camera in.
  - The evening crowd stands and sits on one spot per place, overlapping: the authority sends everyone to the same point.
  - Standing up from the ground was a 220 ms blend into the walk (fixed below: `stand_up_ground`).
  - Gestures while walking slide (rare: the rules turn a standing body first).
  - A hidden sleeper still animates.
  - Clips are judged from stills, not in motion: `play` had one 41° jerk inside its loop (fixed below).

### Residents who answer (town life layer 2, notes for the client)

Not built in the client; what it would need ([layer 2](TOWN_LIFE.md#layer-2-residents-who-answer)). Residents someone engages get minds and answer through speech rows like anyone. One new act for players: **`host`**, taking someone in as one's household's guest until morning, sent as `human_act` `{"do": "host", "target": {"id": N}}` (refused without a house at the player's home door). A player who is taken in perceives it as an experience ("… takes you in as their guest until 07:00 …") and gains a `lodging` place in `my_places`; the `guest` table is private. No new public table or view.

## Client polish: first load, getting up, root motion, dawn and storm (2026-11-09)

Client presentation and the clip tools only (`living/game`, `living/tools`).

**First load.**
- **Cause.** Bevy 0.20 creates render pipelines synchronously on macOS (`bevy_render`'s `create_pipeline_task` blocks there). The frame that first draws a new material, mesh layout or pass composes its WESL, writes MSL and has Metal compile it: tens of ms when Metal's shader cache is warm, up to seconds when it is cold. That cache is per binary, so a new build starts cold. The first view needs about 90 pipelines. `LIVING_GAME_PERF=hitch` now also logs, per frame, the pipelines created (label and vertex layout) and the render set's time.
- **The 800 ms frame** in look-dev was the land generating inside a frame (0.81–0.88 s). It now generates on a worker thread, as connected mode already did (`envs::switch`, `Island::generate`). `assets_for` lists each folder once per session.
- **The cover** (`loading.rs`): the first load happens behind a plain cover in the sky's colour reading "Arriving…". It lifts once the island and your character are in, nothing waits to spawn, and no pipeline has been created for 0.75 s (30 s at most), then fades over 0.35 s. The tour, routes and the headless script's `ready` wait for it.
- **Prewarm**: under the cover, throwaway characters at the arrival point wear every outfit piece between them (`Recipe::every_piece`, 6 characters). A piece with its own vertex layout used to compile 4 pipelines 2 km into `road:town>village3` (301 ms at (397, 1505) cold). Material caches now hold ids, not handles (`lookdev::convert`, the outfit `Wardrobe`), so a material lives while some mesh wears it. The prewarm leaves none behind: 41 toon materials at the town before and after.
- **Numbers** (M4 Pro, uncapped, base `972aefd` against it plus this change, other agents' work loading the Mac): `road:town>village3@run`, route time:
  - mean 4.58 / 4.55 ms;
  - p99 13.4 / 6.9 ms;
  - frames over 33 ms 753 / 295, over 50 ms 216 / 98;
  - worst 155 / 151 ms;
  - 1-minute load 5.7–19.8 / 5.2–13.1.

  Neither arm creates pipelines at (397, 1505) any more; frames of 30–53 ms still come at the vista stop there, with nothing arriving. Before the route, look-dev's first frames: base 805–847 ms (the land), then up to 1142 ms of pipelines on a cold cache; this change's worst is 166–215 ms, behind the cover, which lifts after 2.1–2.2 s (91 pipelines). Connected: base 212 ms, this change 323 ms behind the cover, which lifts after 2.8 s. After it lifts, the worst frames are 83 ms while lots arrive.
- **Counts:** materials per view and toon materials at the town, forest and hamlet are identical before and after: main 35/23/36, cascades 17/9–15/17, toon materials 41/68/42. 10:00, clear and storm. Frame means are within run-to-run noise: clear 5.29/4.39/5.69 against 5.25/4.70/5.35 ms; storm at the town 5.2–7.2 against 5.3–8.0 ms over 3–4 windows each.

**Getting up and root motion** (Kimodo on the Spark; `clips.json`, `animate.py`, `batch.py`).
- `batch.py` takes `"path": [[s, x, z], …]`: Kimodo's `Root2DConstraintSet` pins the hips' ground track on every frame. `animate.py` gets `travel: path`, which takes exactly that track out, and plants feet along it.
- **`dodge`** (replaces `dodge_roll`): a low forward dash whose hips follow the rules' dodge, 2.6 m at 5.2 m/s, then a recovery; 0.97 s, played at rate 1. Travel 2.60 m for Vivi and 2.69 m for Shino; the hips stray at most 0.04 m from the body's track. One-shots are now timed on the display clock (they wait for `start_ms` and join part-way when seen late), and a dash's clip is not predicted, because the authority moves the body about a round trip after the press. On my character, 5 dodges each way, `LIVING_GAME_FEET` and `foot_slide.py` on the dodge frames: slide median 3.52 → 0.98 m/s (0.54 → 0.21 of the body's speed); drift per contact median 13.9 → 4.5 cm.
- **`death`**: new takes with the hips pinned over the origin. The body falls where it stands: it ends 0.04 m away (was 1.04 m).
- **`stand_up_ground`**: continues from `sit_ground_down`'s end and stands up over the origin (2.47 s, played ×1.6). When a sitter's rest ends, the drawn body holds its seat while the clip plays, then catches up with the authority's position at up to 1.2 m/s faster than the body (`live.rs`). The gait follows the drawn motion.
- **`play`**: 8 seeds; seed 2 replaces seed 0, whose loop had a 41° hand snap. Its worst change in step is now 21° on a lower leg landing from a hop. `loop_jerk` reports the bone.

**Dawn and storm** (`island.json` keys, `sky.wesl`, `edges.wesl`, `toon_light.wesl`, `post.rs`).
- **Dawn (06:24 key):** a gold key light ([1, 0.88, 0.77]), a cooler zenith, a warm-neutral haze ([0.86, 0.80, 0.78]) instead of peach, a lighter grade (0.12) and thinner banks (0.6).
- **Storm:** a cooler, darker key light that still casts, a darker sky (0.28) with less fog fill. Clouds have pale lit tops, dark cool undersides and darker dense cores. Wet surfaces catch the sky at grazing angles (`wet_sheen`); puddles are softer and darker and mirror more of the sky the flatter they are seen. Rain falls in four layers, finer and fainter with distance, the far ones stronger in a storm, and stays visible under a dark sky.
- **Blind A/B** (a fresh judge each round, 12 pairs, sides randomised): storm 6/6 and 6/6. Dawn 3 wins and 3 losses in round 1 (cold lavender haze), then 3 wins, 1 loss and 2 ties in round 2.
- **Still off:** the dawn haze still washes out the middle distance, and the town's terracotta paving reads orange at dawn in both versions. Storm shadows stay sharp under trees. Puddles on grass still read as patches.

**Clippy:** the two `approx_constant` errors (TAU in `bodies.rs` and `world.rs`) are fixed. The remaining warnings are the same as at `da219a7`.

## What the client shows of others (2026-11-09)

The client receives only what its character perceives ([perception](PERCEPTION.md); `scoped` is the default build) and draws only that. Code: `living/game/src/net.rs` (the views), `live.rs`, `town.rs`, `ui/live.rs`, `ui/overhead.rs`.

- **Who is drawn:** every body in `seen_bodies`, which holds the creatures within sight (11 tiles by day, 6 at night, more with a torch) with a clear sight line. Someone behind a wall, a fence, a stall or rock is not drawn, and nobody gets a nameplate there. Creatures appear within about 200 ms of coming into sight.
- **Names:** a name only when my character knows it, otherwise the label the authority gives (`a stranger`, `a child`, `a wolf`). It shows on nameplates, speech bubbles, the log, the target panel and the death screen. Someone who says their own name is known from then on. The death screen names my killer and the witnesses as I last perceived them.
- **Health:** others' health is a band on the nameplate's bar. While an appraisal holds (**V**, below), the bar is exact and a small `hp / max` figure sits under it; the plate stays up for those 20 s and the figure goes when the reveal ends. It has no label and no other new HUD element.
- **Dress:** build and dress come from the projection's `folk` and `style`: the settlement the character lives in, since the home position is no longer sent.
- **Indoors:** a resting resident is hidden when its `doing` row says `indoors` (the authority decides it from the home). A sleeper is hidden as before.
- **V looks someone over** (`appraise`, through `human_act` like G and B). It goes to the creature under or nearest the cursor, else the nearest one within 6 m ahead, people or animals. My character glances (`idle_look`, 1.5 s). The answer is the projection's exact health for 20 s and my experience "You look a stranger over: 94 of 94 health." No text is shown on screen.
- **Cost**, measured on the Mac (M4 Pro), headless and uncapped (`LIVING_GAME_PERF=diag`). Each arm is the real game client on a fresh scratch island, two runs per arm, 40 s windows at the same world hours: a village at 10:45–12:00 (calm, about 10 bodies within 40 m) and the walled town's square at 12:20–13:40 (busy, about 40). Bytes were counted by the perception bench's TCP proxy. Another session's database had a client connected throughout.

  | | `acbbda7` client, `open` build | this client, `scoped` build |
  |---|---|---|
  | calm: bytes to the client | 2.37 / 1.73 kB/s | 0.23 / 0.48 kB/s |
  | busy: bytes to the client | 2.78 / 3.48 kB/s | 1.22 / 0.66 kB/s |
  | calm: frame mean (worst) | 5.18 (14.6) / 5.16 (8.4) ms | 4.79 (8.0) / 4.40 (9.5) ms |
  | busy: frame mean (worst) | 6.29 (8.8) / 6.58 (10.6) ms | 5.14 (9.3) / 4.96 (8.4) ms |
  | characters drawn, calm / busy | 17–20 / 55–58 | 3–6 / 10–13 |
  | live queries | 21 | 20 |

  The frame time drops because the client draws only those in sight, not every body within the ±5-chunk window. Bytes vary with what the people in sight do: one run per world, not a repeatability study.
- **Still off:**
  - My own `my_characters` row carries `cause` as the authority writes it ("killed by Rook the wolf"). The death screen no longer shows it, but the name reaches the client: the authority should project its own death cause too.
  - A greeting from a resident frozen by a test graph gets no answer, so its nameplate does not show; ordinary residents answer.
  - Rock tiles are drawn as flat stone ground, so a person hidden by rock is hidden by something the eye reads as ground.
  - Labels don't tell strangers apart ("a stranger" twice in the log).

## Wolves and arid lands (2026-11-09)

Client presentation (`acbbda7`), recorded here after the fact.

- **Wolves** are the rigged `wolf.glb` (`living/tools/blender/wolf.py`, run by `gen_anim.sh`; git-ignored), in the shared vertex-colour toon, so a pack adds no material. Gaits come from one family, walk, trot and run (1.3, 3.4 and 7.0 m/s natural), through `gait.rs`. A move plays the bite or the leap, chosen by the skill card's aim (`creature` or `dash`), never by the skill's name (`combat::animal_clip`). They also have a flinch and a death held on its last pose. A wolf is scaled by life stage. Deer are rigged too since the pass below.
- **Two `live.rs` fixes:** a corpse no longer vanishes when the death's row arrives in the same update as the body leaves, and a body more than 6 m from where it is drawn (a teleport) snaps there.
- **Arid lands:** a land whose rivers run dry (`water.dry_rivers`, the megacity floor's wastes) gets dry earth, cracked mud and gravel ground layers (16 in all) and its own dressing, `wastes`, `scrubland` and `badlands`. The megacity's wall line draws a 14 m cyberpunk wall. Look-dev draws any land seed with `LIVING_GAME_SEED=<seed.json>` ([floors](FLOORS.md)).
- **Assets:** `just living-game-assets` now paints every texture set (`living-game-textures --set all`): the ground and the model surfaces that `style.rs` binds on scenery. Before, a fresh checkout got the ground only and no model detail.


## Animation: gaits in step, upper-body layers, feet on the ground (2026-11-09)

From Casey Muratori's animation-blending stream, checked against the client. Client presentation only.

- **Foot-down markers.** Every clip's sidecar lists each foot's contact windows as phase 0–1, detected from the baked take (`animate.py`, `wolf.py`). People's gaits start on the right foot coming down; the wolf's on the left hind paw (`sync: "hl"`). Markers agree with recorded feet in 83–93% of foot-frames.
- **Phase-synced gaits** (`anim.rs`). One graph per file; at most two gaits play, paused and set to one shared phase that advances at `speed / (stride × weighted metres per cycle)`. Walk ↔ brisk and run ↔ fast blend across their gap; brisk ↔ run only at 2.6–3.0 m/s; the wolf's gaits within ±10% of each boundary. Speed ramps 0 → 4 → 0 m/s: mean slide of the supporting foot 0.51 → 0.085 m/s (walk ↔ brisk), 0.96 → 0.17 (run ↔ fast); drift per contact 24 → 3.5 cm.
- **Masked upper-body layers.** Clips marked `layer: "upper"` in `clips.json` (13: strikes, bow, cast, block, heal, wave, nod, appraise…) play on the spine, arms and head while the body moves, and whole-body when standing; override with a mask, not additive (VRoid clips are T-pose-relative, so an additive strike turns the arms twice). Dodge, death, sitting, standing up and `play` stay whole-body.
- **Foot IK** (`ik.rs`, people only). During contact windows planted feet go to the ground (and stair treads: `Island::foot_height`), held at the heel or ball where they came down; the hips lower to reach, rise up to 0.18 m; feet tilt to the slope within 26°. Full within 25 m of the camera, gone by 30 m. Supporting-foot gap on stairs: median 3.5 → 1.7 cm, inside the surface 41% → 11%. Corrections blend rest-relative (`rest_relative`).
- **Cost.** Frame times unchanged at the town, forest and hamlet; material counts identical. Per character: Bevy's animation step 16.5 → 13.9 µs (one graph per file), plus 0.5 µs for `anim.rs` and 4.6 µs per IK-solved character: about +2.5 µs a character overall.
- **Open.** Stairs p90 still 15 cm (toes over step edges); stopping far from double support still drags. The wolf's blends were measured in the pass below. `probe.rs` is the look-dev harness (speed ramps, one-shots while walking, frame sequences); `foot_slide.py` gains `--bins`, `--floors`/`--gap` and `--stairs`.

## The megacity kit (2026-11-09)

Built on `megacity-1` for the megacity floor's second pass ([floors](FLOORS.md#the-megacity-second-pass)). `living/tools/blender/city.py` builds on `buildings.py`'s helpers and conventions. `buildings.py` now runs its `main()` only as a script, so `city.py` can import it. `gen_city.sh` (in `just living-game-assets`) writes `envs/cyberpunk_megacity/<kind>/` and refreshes `living/rules/data/buildings.json`: 327 models in about 10 s.

- **Buildings:**

  | Kind | Forms | Height | Triangles, mean and max |
  |---|---|---|---|
  | megatower | blade, stepped, twin, needle | 170-326 m | 6.5k / 10.2k |
  | arcology | arcology | 187-225 m | 13.9k / 14.5k |
  | megablock | slab, court, stack | 61-111 m | 22.2k / 33.5k |
  | neon_tower | neon | 51-57 m | 3.5k |
  | old_block | narrow, wide | 19-31 m | 3.7k / 5.0k |
  | block, market, workshop | as the cyberpunk kit, in the city's palette | | |
  | shanty | shack, stack, lean | 3-13 m | 0.3k / 0.9k |
  | container | stack2, stack3, home2, home3 | 5-9 m | 0.7k / 1.1k |
  | warehouse | shed, sawtooth | 18-22 m | 0.8k / 1.0k |
  | ruin | shell, stump | 4-14 m | 0.5k / 0.7k |
  | wall_tower | tower | 33-38 m | 0.4k |

- **Transport:** highway (ring: a 22 m deck at 9 m; arterial: 16 m at 17 m; 24 m long on a hammerhead pier, with barriers, a lit strip, lane marks, lamp masts and sometimes a sign gantry), about 0.5k triangles.
- **Street dressing:** vending (banks of 2 or 3), vent (stack, grate), trash (bags, bins, heap), barrier (jersey, bollards, checkpoint), vehicle (car, van, bike, truck), hologram (pole, disc), scaffold, crane (port gantry, tower crane), salvage (heap, wreck), all under 1.1k triangles. The cyberpunk lamps, kiosks, food stalls, neon signs, billboards, cables, crates, walkway, wall and street props are made again in the same folder, so a ward finds every model in one environment.
- **Our own text and marks.**
  - A 14-segment neon font writes real words on signs: brands (KAIROS, HALCYON, VANTA, ORRERY, MERIDIAN, NOVA, TESSER, OKAPI) with their marks (ring, sun, chevron, orbit, bar, star, cube); trades (NOODLE, RAMEN, 24H, HOTEL, KARAOKE, REPAIR…); road signs (RING 1, PORT, CORE…).
  - All names are invented here, and nothing comes from an existing game or franchise.
  - The kit's other pseudo-glyph boards are `buildings.py`'s.
- **Lit windows.** Megatowers and arcologies use curtain walls with lit runs per storey, so a few quads per storey stand for a whole floor of offices. Megablocks use punched windows lit per household. A share of floors stays dark.
- **Materials and surfaces.** These are the shared ones: `Body`, `Glow`, and the neon colours `GlowPink`, `GlowCyan`, `GlowAmber`, `GlowRed` and `GlowWhite`. No building has materials of its own. Parts carry the existing surface tags in their vertex alpha: concrete, metal, glass, plastic, cloth, brick, plaster, planks, leaves and earth. Grime is a vertex-colour gradient and streaks; neon is the glow materials. No new texture layers were added. A metal-panel or grime layer would change `surfaces.py`, `paint.py` and the game's table (`style.rs`) together, and the game draws no detail when `material.txt` does not match its table, so that is a client change for later.
- **Measured in the captures.** Near the core: 180-210 models and about 900 meshes in view. At the market and the overpass: 580-660 models and 2,100-2,600 meshes. Frame times are in [floors](FLOORS.md#staged-generation-and-the-largest-floor).

### Client notes for the megacity floor

Nothing in `living/game` was changed on `megacity-1`; its client patch landed on 2026-11-10.
- **Drawn already.** The client draws the new lots and props through their model files and kind folders, and the folder's `cyberpunk` prefix dresses its people in the cyberpunk look (`characters::place_style`).
- **The patch** (applied on 2026-11-10 with the verbs work, and deleted; it was `docs/patches/megacity-client.patch`) did two things; the captures used a private build with it applied:
  - `island.rs` `road_layer` asks `living_rules::settle::road_surface(style)` for the paving, so the new district styles get pavers, setts, earth or gravel, and future styles need no client change. Without it, the corporate, neon, megablock and market wards draw cobbles.
  - `assets/envs/cyberpunk_megacity.json` is a showcase environment whose `lamp` and `neon_sign` slots carry the glow that lights the floor's lamps at night. Without it, megacity lamps get no point lights, because the island takes a lamp's light from its environment's slot.

**Further work, by priority:**
1. **The world being made.** Subscribe to the public `genesis` row and show progress (`step`, `steps`, `label`) while a floor is created: 20 s at 4096 m and 90 s at 8192 m on the dev-box. Wait for `done` before drawing the land.
2. **A land cache by digest.** At 8192 m the client regenerates the land for 37-39 s with about 0.8 GB, and look-dev's tour photographs before it is ready (its first shot waits a fixed 6 s). Cache the generated land under the `land` row's digests, and gate tours and arrival on the land being in.
3. **The floor's own night.** The judge of the blind A/B found the haze beyond about 50 m and the flat blue-violet palette the main weaknesses. `island.json`'s mood curve applies to every land; a floor needs its own curve (longer fog distances at night, a warmer key, stronger bloom on neon), read from the seed or the environment.
4. **Light from props.** Props get no point lights (`Item::glow` is unset for props). Holograms, neon signs and wall towers' floodlights could take the environment slot's glow as lots do, capped like lamps.
5. **Windows through the evening.** Every glowing part scales together with the hour. A per-window hash against the hour, in `toon.wesl`'s glow path, would switch offices off one by one through the night without new materials.
6. **Steam.** `vent` props are the places for rising steam: a small flipbook or particle effect at their position, more in rain.
7. **Large models and the cutaway.** The arcology is about 100 m across. The cutaway's reach comes from a model's fitted size, so it works, but standing beside such a building hides it in vistas taken from the far side. Judge the cutaway by the camera's line, not only by nearness.
8. **Two-sided signs.** Text on container homes reads mirrored from behind. The kit can make those signs two-sided; the client needs no change.

## Deer, fight and greeting framing, wolf gaits, marker checks (2026-11-09)

Client presentation and the clip pipeline only.

- **One quadruped builder.** `living/tools/blender/quadruped.py` holds the rig, leg IK, gaits, keying, paw markers and export; `wolf.py` and the new `deer.py` give proportions, clips and bodies, with the same 21 bones. Refactored, the wolf came out byte-identical, before the fix below.
- **The wolf's clips were 1.25 × too long.** Blender exported its 30 fps keys at its default 24 fps, so `walk` was 1.0 s in the file and 0.8 s in the sidecar. The game seeks gaits by the sidecar, so the wolf played 80% of each cycle and jumped back, and its bite snapped at 0.69 s instead of 0.55. The builder now sets the scene to 30 fps.
- **Deer** (`deer.glb`, 910 triangles, 1.0 m at the shoulder): idle (grazing, then head up chewing and looking round; the rules show no `graze` act yet, so a standing deer grazes as its idle), graze, walk 1.3, trot 3.7 (the rules' deer speed), run (a bound, 4.6; the rules' flee is 4.26), startle, hit and death. The sidecar's `band: 1.04` narrows the animal blend (`gait.rs`), so trot and flee each play one gait. Long legs use cannons that turn with the leg, front hooves that fold back, and a fit that keeps each leg within its length (worst overreach 2.6–5.1 cm, against the wolf's 10–14 cm). Same shared vertex-colour material, no new one.
- **Connected deer** (`live.rs`, `bodies.rs`): drawn from the file through `anim.rs`, like the wolf; scaled by life stage. A deer that sets off at 4 m/s or more after standing a second (fleeing; a wander tops out at 3.9) plays `startle` where it stood, held for 0.42 s, then catches up. Standing loops start at an offset per body, so a herd doesn't graze in unison. Animals asleep or resting are no longer hidden as if indoors.
- **Body on the ground** (`bodies::lie_on`): wolves and deer tilt to the plane through the ground under their fore paws, hind paws and sides, and stand at its height. That is one rotation per animal and no bone IK. On the hilly meadow, planted paws' |gap| p90 went 7.0 → 1.4 cm, and the share more than 3 cm into or above the ground 35% → 1% (flat ground: 1.1 cm, 0%).
- **Wolf paw slide** (look-dev wolf, `LIVING_GAME_PLAYER=beast:wolf`, flat ground, 0 → 8 → 0 m/s, 3 runs each; the slowest planted paw's median slide). f44b66a^: 0.29 m/s at 1–2 m/s, rising to 1.75 at 7–8, with 12–19 cm drift per contact. f44b66a with the phase sync: the same, because the clips' timing was off. Now: 0.002–0.36 m/s, 0.7–4.2 cm. `gait.rs` records paw tips; `foot_slide.py --paws`.
- **Camera framing** (`camera.rs`, `Context`): the view frames you with your opponents in a fight you are in (any move or blow between you in the last 4 s; 10–18 m by their spread), with whoever you talk with (8 m), and with whoever you trade a wave or nod with (9–15 m), for the exchange plus 3.5 s. It never turns; it eases in over about 1.5 s and out over about 2.5 s, and a context outlasts its evidence by 1.2 s, so a wave and its answer are one framing. Turning the view yourself dismisses it until that context ends. Someone greeting you now counts too (`town.rs`, `greeted_by`).
- **Marker check** (`living/tools/marker_check.py`, at the end of `gen_anim.sh`): per character and looping gait, it fails on missing markers and warns on split contacts, a contact share far from the gait's range, unpaired feet, a phase 0 that isn't the synced foot's touchdown, a baked clip whose length differs from its sidecar, and planted feet that slide more than 4 cm in the baked take (pure Python, read from the GLB). Today: the wolf and the deer are clean; the people's Kimodo takes slide 3–10 cm per contact (sneak the most).
- **Open.** The rules show `graze` since 2026-11-10 (`graze_shows`, look `eat`), and the client already names it (`town.rs`); not yet checked on screen. A flee ran toward its threat in scripted scenes: the goal ran from an escape point beyond the fleer (`act.rs`); fixed 2026-11-10, the goal now runs from the threat itself. Deer have no antlers: the projection carries no sex. No paw IK beyond the body tilt, so steps and banks narrower than the body still gap.

## Verbs: acting on the world (2026-11-10)

A player could move, fight and greet, but not gather, eat, craft, build, give, trade, teach, sleep, read or write, or see their pack. Residents do all of it through the rules. The client now offers every one of those acts, and it does so **from the rules' own data, with nothing written per skill** ([`verbs.rs`](../living/game/src/verbs.rs), [`ui/verbs.rs`](../living/game/src/ui/verbs.rs)). A skill the rules add appears for players with no client change.

**Where the acts come from:**
- **Which skills exist:** the world's installed skill script (the public `script` row, one subscription of about 70 kB, sent again only on an install), compiled with the same `living_rules::script` the authority runs. Since `rules-2` each skill's `<skill>_spec()` says whether it takes a target or an item, the items it is given, and its description ([world rules](WORLD_RULES.md)); there is no Rust catalog list.
- **What applies to what:** the rules' own `<skill>_check`, run on what my character knows: my pack (`my_inventory`), my know-how (`my_know_how`), my needs (`my_vitals`), and the target as I perceive it (`seen_characters`, the resource or structure row). What a target holds is not perceived, so a check is run as if it holds what is asked of it. A gather is offered on a bush, not on a person; "eat wood" is never offered; "craft bow" is offered only once I know archery and carry the wood, fibre and stone.
- **What each takes and gives:** the spec's `takes` and `gives`.
- **The authority decides.** An option is a guess from my side of the world. Every act goes through `human_act`, the act path minds use (`acts::submit`); an ongoing skill such as sleep becomes my behaviour as before. The outcome comes back as my `act` experience rows ("You did what you had decided: …", "What you had decided did not work out: …: why") or as the reducer's error.

**Generic rules, not per skill:**
- Real-time skills (a combat shape with `real_time`) belong to the skill bar and are not listed.
- A skill whose script has no check says nothing about what it applies to. It is offered only toward people of my kind (join, welcome, walk to, follow), never toward things, and listed after the checked ones.
- Item choices come from my pack, my know-how and the item names the skill's help lists (`(item: spear|cloak|…)`), plus every item there is toward something that may hold things (taking from a store). A skill whose check refuses an empty text but takes some text needs words: the text box opens with the act's name (write, found).
- A skill with more than two options becomes one row that opens its own list (`give ›`, `offer ›` and what to ask in return).
- A skill whose arguments include a behaviour graph (`rework`) is left out: the client cannot write one.
- A tap does the most likely act: the one I last chose for that kind of target, else on a thing the first the rules allow that needs no further choice and is no use of force (the combat shape's `hostile`, `force`, `menace`). A person has no default: a tap opens the list.
- Things are named to the authority as acts name them, by kind (`{"nearest": "berry_bush"}`). When the one under the cursor is not the nearest of its kind, the act becomes a walk to it and then the act on the nearest (`{"seq": [goto, act]}`), which runs as my behaviour.

**Controls and HUD** (only relevant information on screen; everything below is hidden until it matters):
- **F** acts on what is under the cursor, else the nearest thing or creature within 3 m: a tap does the likely act, holding it (0.28 s) or a tap with no likely act opens the list. With nothing to aim at, F opens my own list. When something is in reach, a small hint over the bar names the likely act (`F gather`) or the target (`F a stranger ›`).
- **C** opens the list of acts on myself (eat, sleep, rest, craft, build, write, drop, experiment, …), with what I carry ("eat berries ×4").
- **The list** sits over the bar: 1–9 and 0 or a click picks, Esc goes back or closes, F or C closes it. The mouse picks from it rather than firing the bar while it is open.
- **Notes** of what the authority said rise just over the hint for about 4.5 s: edged green when done, red when refused with the authority's reason ("You don't know how to make a bow (archery: learn it from someone who knows it or from writing, …)"), grey when an ongoing act began.
- **I** toggles the pack: each item and how many, its worth as food (the rules' `nutrition`), and how much I carry against the rules' `carry_limit`. Clicking an item lists what I can do with it myself.
- **K** toggles know-how: the techniques I know and how I came by each, then every skill in the rules (the catalog's and the script's own), with the selected one's help and what it takes and gives. Up/Down or a click selects.
- **Requests to people:** give, offer a trade, accept one, teach what I know, join, welcome, host (the townlife-2 act appeared here when it merged, with no client change), tend, appraise, wave, nod, and asking to be taught a technique I lack (a line through `human_say` to them: "Would you teach me archery?").
- Gestures stay on G, B and V (`town.rs`).

**On a land world the client now draws resources and small structures** (`world::things`, which was tile worlds only): berry bushes, boulders, reeds, clay banks, fishing spots, stores, hearths, signs, traps and remains, from the `resource_node` and `structure` rows of the near window (±3 chunks, re-centred with the terrain edits). Buildings stay the island's lots, gates its walls, and trees its forest (35,699 tree rows on the island seed; an act names a tree by kind).

**Evidence** (2026-11-10, scratch island world `verify-client-verbs-1110-003532`, the real game client headless, `.local/living/verify/<run>/game2` and `game3`): gather twice at a berry bush, eat berries, craft a spear, write a tablet ("Berries by the arrival road, east side."), give berries to a resident, sleep, and craft a bow refused with the rules' reason; each outcome is an `act` row in the character's experience, and the pack and know-how before and after match. Admin scene setup, named: the spear and writing techniques, 4 wood and 1 stone granted; one resident held still beside the player. Genericity: a scratch authority with a throwaway `polish` skill (a catalog line and three script functions, never committed) on `verify-client-verbs-gen-1110-004303`; the unchanged client binary (same SHA-1) listed `polish` in F's list on a boulder and in know-how with its takes and gives, and the authority performed it (+1 stone).

**Cost** (Mac M4 Pro, 1600×900 headless, uncapped, load average 6–17 from other agents; arm A is `6de2bad`, arm B the same plus this change, both built from one commit's sources with the same assets):
- **Look-dev at the usual spots, two runs per arm:** models, meshes, distinct meshes, materials and triangles identical; frame means within the runs' spread. Hamlet 5.87 / 5.67 against 5.73 / 5.93 ms, town 7.23 / 5.70 against 5.73 / 7.90 ms, forest 4.57 / 4.67 against 4.63 / 4.67 ms.
- **Connected, at the island's arrival:**
  - the drawn resources and stores add 100–150 meshes in view, 3 distinct meshes and 1 material; toon materials stay at 42;
  - frame means 5.53 / 5.53 ms against 5.22 / 6.90 ms;
  - the client checks the rules for what F aims at 4 times a second, and for a whole list only when one opens; since 2026-11-10 the hint's checks are spread over frames (see "How the client feels", item 6).

**What is still off:**
- **A skill in `skills.rhai` alone is not a skill yet for anyone.** The authority's graph parser accepts only catalog skills (`graph::check`, "unknown skill"), so a new skill needs a catalog line in `living_rules` too (as `host` had). The client already lists a script-only skill; the core would need to read a skill's spec from the script (`<name>_spec()`) for the script to be the only place.
- What is offered is checked on what my character knows. The client fills what it does not know: the ground under me is grass, the season summer, the hour noon; a target holds what is asked of it. The authority's refusal covers the rest.
- Quantities are one at a time (give, store, drop, trade 1 for 1).
- Reading a sign: `read` takes no target in the catalog, so F does not offer it on a sign; from C it reads a tablet I carry.
- Storage contents are not perceived, so "take ›" lists every item there is.
- A list shows 16 rows; the first 10 have number keys, the rest are picked with the mouse.

## How the client feels: renewals, frame order, stale input, starts, hills (2026-11-10)

A review of the client at `6c8d1002` found six causes of poor feel. Five are fixed on branch `fix-client-feel`; the sixth was measured and left as a plan. Presentation and input only: no table, reducer or rule changed, and the client still sends no positions. The keys and acts are unchanged.

1. **My body no longer stops at every segment renewal.** The authority renews a moving body's segment at the first tick after its end (`next_ms`), anchored at that end (`motion.rs`, `resume_at`), so the renewal reached my body (drawn on the clock's lead) after it had reached the end. While a direction is held, my segment is now carried on for up to 150 ms past its end, and the renewal's small difference is blended as a late row's is (`sync.rs`, `Tracks::update_ahead`). Others are drawn as before.
2. **A pressed skill's clip starts in the frame of the press.** A connected frame now runs in named phases: Net, Mirror, Input, Flush, Present, Camera (`phase.rs`). Bodies are drawn (Present) after this frame's presses (Input), so a skill's clip no longer waits a frame. Gestures from the keys were already on time.
3. **Input state that went stale:**
   - a guard key let go while the text box is open lowers the guard;
   - the guard's arc shows the direction it was raised toward, not the cursor (the authority keeps the aim of the press; how the authority should take a look direction is still open);
   - a refused movement intent ("too many movement inputs") is sent again after 40 ms, and a new connection or character sends what the keys hold;
   - offline, no body is drawn, and a notice at the top says the connection was lost and is coming back (`ui/link.rs`).
4. **Starts slide less.** A drawn gait takes up its segment's speed at once when it rises (the authority starts a body at full speed), and fades in over 0.08 s from standing instead of 0.2 s. It still eases down at a stop: freezing the gait mid-stride and blending it to standing slid both feet more than finishing the step does.
5. **The camera no longer pops over hills.** `camera::follow` lifts the eye over the island's ground itself, eased (10/s up, 2.5/s down, at least 0.3 m clear), and aims after the lift; the lift that ran after the camera had aimed is gone.
6. **Per-frame copies of the SDK cache: measured, not changed.** `iter()` and `find()` clone rows under a lock every frame (`my_experience` six times, `seen_characters` twice, the 70 kB script row once). At about 180 bodies in sight they cost at most 1.3% of the main thread's samples, about 0.2 ms a frame. The frame's hitches come from elsewhere: the F hint's rule checks (`verbs::options`, Rhai `Scripts::check`) every 0.25 s take about 8 ms each, 9–13% of the main thread, so about one frame in fourteen runs over 8 ms with 50 or 200 people in sight. Plans:
   - **The hint: done on branch `fix-verb-hint` (2026-11-10).** Checking only when the hint's inputs change would not help in a crowd, where the nearest person changes all the time, so the checks are spread instead. The catalog is worked through one skill and item at a time (`verbs::plan`, `check_unit`), at most 1 ms a frame (`HINT_BUDGET`); a job toward a person takes about 8.5 ms in 5–6 frames, and what the hint shows changes when it is done. A skill was too coarse a unit: `teach` alone tries every item there is and takes 4–5 ms. With the crowd held still (`set_behavior` wait, two runs per arm, the Mac's load average 9–11 from other agents):

     | Bodies in sight | Frame work p50 | p99 | Frames over 8 ms |
     |---|---|---|---|
     | 53–60, before | 2.9 / 3.1 ms | 11.3 / 11.5 ms | 90 / 92 of about 1,260 |
     | 55–61, after | 3.4 / 3.2 ms | 4.8 / 4.4 ms | 3 / 0 |
     | 204–212, before | 5.5 / 5.7 ms | 15.3 / 13.7 ms | 113 / 106 of about 1,300 |
     | 196–213, after | 5.4 / 5.8 ms | 7.3 / 7.8 ms | 5 / 8 |

     The same total work, spread: the median rises by up to 0.5 ms with 50 in sight. The frames still over 8 ms with 200 in sight (up to 14 ms) come from something else.
   - **The copies, when a crowd makes them matter:** one typed resource per table, kept from the SDK's `on_insert`/`on_update`/`on_delete` callbacks (they also fire for a subscription's initial rows) and drained in the Mirror phase; systems borrow it. Speech, act outcomes and combat events become queues of new rows. The script row is recompiled on its update callback, not looked up every frame.

**Evidence** (Mac M4 Pro, headless at 60 Hz, scratch island world `verify-feel-1`, the real client through the same script steps the keys use; `.local/living/fix-client-feel/`):

| | Before | After |
|---|---|---|
| Renewals at an unchanged speed with a frame under 90% of the segment's speed (straight walks, `living/tools/root_steps.py`) | 6 of 22, lowest 38% | 2 of 15, lowest 51%, both at real direction changes |
| Frames from a scripted skill press to its clip asked of my body | 1 (4 of 4 presses) | 0 (4 of 4) |
| Guard after its key goes up while typing | stays up until its 8 s limit | lowered at the release (+9 ms) |
| Stop refused after a burst of 40 direction changes | still walking 2 s later | stopped |
| Drift of the supporting foot over 0.5 s, 16 starts | median 32.8 cm, p90 89 cm | median 28.6 cm, p90 50 cm |
| The same over 16 stops | median 10.9 cm, p90 30 cm | median 2.9 cm, p90 30 cm |
| Frames with my chest more than 2° off the view's centre, walking down a steep slope | 360 | 0 |

New measurement aids: the feet log (`LIVING_GAME_FEET`) also records the authority time my body is drawn at, its segment, the one-shot asked of it and the camera's eye and pitch; the live script has `key:`, `mouse:` and `chat:` steps that drive the input systems as the window does.

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
