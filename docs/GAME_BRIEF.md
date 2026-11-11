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
| Movement | WASD relative to the camera, plus click-to-move (`goto` to a point). Since 2026-11-09 right click is the bow shot and there is no click-to-move; scripts still walk to a point with `goto` | Matches the chosen genre |

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
  - **Clip lab (2026-11-11):** `living/tools/kimodo/cliplab.py`, run on the Spark with the Kimodo venv's python, regenerates and judges one library entry at a time.
    - **What it does:** it generates takes for one or more prompt variants under new seed numbers, through `batch.py` into `~/cliplab/<clip>/takes`. Before the GPU it waits for a machine lock, for no other `batch.py` to be running, and for 40 GB of RAM to stay free. It then scores the new takes and the entry's current library takes on the raw SOMA-77 motion.
    - **Scores:** floor penetration of hands, feet and the rest of the body; slide and drift of planted feet; active share and frozen stretches; loop closure; keyframe match; path, travel and travel direction; turn, facing drift and cadence against the forward walk or run; air time and hop window; steps and first foot.
    - **Pick rule:** a take that fails no check is eligible, and the lowest penalty wins. The penalty is the sum over checks of measured/limit, capped at 3 per check. When nothing passes, the take with the fewest failures wins and is reported as failing.
    - **Output:** `checks.json` (every take's scores and why the winner won), a contact sheet with a motion-energy strip, and a markdown line.
    - **Modes:** `--score-only` scores existing takes. `--expect METRIC>=X` adds a clip-specific check, such as `both_hands_active_share>=0.5` for work or `steps<=2` for a quarter turn. `--write` adopts the last run's winner: it copies its takes into the raw library without overwriting and sets its entry in `clips.json`, refusing when other entries are keyed to a take it would drop, unless they are re-keyed and `--rekey` is given. `--handoff GROUP` packs the chosen raw takes, entries and checks into `~/clip-handoff/GROUP-<date>.tar.gz` with a sha256.
    - **Calibration:** the limits were set on the 2026-11-11 library, where 14 of the 32 Kimodo picks fail a check (listed in the script's header).
    - **First use (2026-11-11):** work, play, sit_ground_down, sit_ground and stand_up_ground were redone, then redone again after dev-box's in-game review asked for an upright, live seat. The seat is now its own pose entry, `sit_ground_pose`, keyed by all three, as `stand` is for standing. The entries' notes give the scores. The locomotion entries (assets-locomotion) were scored against the laptop's request and in-game verdicts (metres a cycle against the forward gait, seam angle), and the failing ones were retaken or re-picked.
    - **Posture and work metrics** (for `--expect`): `torso_pitch_deg` and `head_pitch_deg` (+ leans forward; standing −2 and 8), `shoulder_range_cm`, `seated_feet_min_cm` (the ankles' lowest height while seated; standing 7), `bench_busy_share` (both hands at bench height in front, one moving), `hops`, `cycle_ratio` (metres a cycle against walk_brisk or run_fast) and `loop_seam_deg`. Raw numbers differ from the baked ones: the bake picks its own loop cut and scales each rig, so the raw cycle ratio and seam angle read better than the laptop's bake.
    - **Not covered:** it judges the raw take, not the retargeted VRoid clip. Skirts, grips, the game's foot IK and how a clip looks in the renderer are judged in the game.
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
- **F** acts on what is under the cursor, else the nearest thing or creature within 3 m: a tap does the likely act, holding it (0.28 s) or a tap with no likely act opens the list. With nothing to aim at, F says so in a short note (since 2026-11-11; C opens my own list). When something is in reach, a small hint over the bar names the likely act (`F gather`) or the target (`F a stranger ›`).
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

## Play-test 1 and feel pass 2 (2026-11-11)

The owner played the island and found it hard to play. They reported:
- walking like "an ice cube shifting on a table";
- animations that glitch;
- no jump;
- things popping in and out of view;
- a camera they could not turn;
- a poor interface.

A diagnosis came first. Its stills, logs and measurements are in `.local/living/playtest-1/` (git-ignored). Branch `feel-2` then fixed the client-side causes, one commit per fix. Before and after clips and measurements are in `.local/living/feel-2/`. Captures were headless runs of the real client on `verify-play-1`, plus scratch worlds for the jump. Presentation and input only, except the jump.

- **Facing the cursor while walking** (`live.rs`, `twist.rs`, `anim.rs`):
  - The clips have only forward gaits, so a body facing the cursor while it strafed or backed up slid its planted foot at 1.4–2 times its speed. Foot IK then let go every step.
  - Now the legs keep to the travel: forward, or backward with the gaits reversed beyond 110° (forward again under 80°). The spine, chest, neck and head turn the rest of the way.
  - Foot slid per metre walked: sideways 1.08 → 0.05 m, backwards 1.27 → 0.08 m, diagonally back 1.56 → 0.07 m. IK jumps per segment: 65/29/41 → 0/1/1.
- **Stops** (`live.rs`, `ik.rs`, `anim.rs`):
  - The legs walked on the spot for 0.5–0.8 s after the body stood. A held foot snapped up to 22 cm in one frame as the stop blended into the idle (the lock let go at its limit), then glided into place.
  - Now the gait takes up a standing segment at once. A held foot more than 6 cm from the clip's place steps there (0.22 s, a 5 cm lift).
  - Skating after a stop: median 72 → 20 cm. The standing clip shows 484 → 207 ms after the body stands. Stops with a snap over 10 cm: 19 → 6 of 19 (the rest are swing feet in the brake's glide).
- **Dodge:** no fast-run frame before the dash, and no 0.6 s walk after a standing dodge.
- **A walk on a road** (`anim.rs` `Motion::pace`):
  - The rules speed bodies up on roads (`road_speed` 1.4), so a road walk played the run clip.
  - The gait is now chosen at the body's own pace and steps at its real speed. Road walks at about 4 m/s: fast run 799 frames → brisk walk 838 frames, with the same slide (3–4% of the body's speed).
- **Pop-in of buildings and scenery** (`fade.rs`, `envs::cutaway`, the toon shaders):
  - The old cut-away hid outright anything tall within 5 m of you on the camera's side. The camera also sat inside walls it missed.
  - Now a dithered fade follows a sight-line test against each thing's turned box. Things in the way fade to 20% drawn, and fully when the camera is inside them.
  - It works through Bevy's visibility-range dither, so the prepasses drop the same pixels. An abrupt range gets no dither variant, so the never-cutting range ends in a crossfade.
- **People** fade in and out of sight and into their houses. The sight rule itself (11 tiles by day) is untouched: laws-2 and lives-2 own it.
- **Turning the view without turning you** (`pointer.rs`):
  - A left drag, a two-finger pan or a middle drag turns the view, and the cursor stays on its ground point. In a headless run, facing held at 128° while the view turned +76° and then −109°.
  - **Changed by `cursor-pan` (2026-11-11, the owner after Cullet walk 1):** a pan carried the cursor off with the view. Now a turn or a zoom by hand (pan, drag, `[` `]`, pinch, wheel) leaves the cursor at its screen position, and what it points at, and so where you face, follows the view. Only an align keeps the cursor on its ground point. verify-ui's `turns` scenario checks it to 1 px.
  - A pinch or the wheel zooms within 0.6–1.4 of the distance. A two-finger double tap aligns.
  - A click captures the cursor: it is locked and hidden, and the game draws its own and feeds the UI's picking. Esc gives it back once panels are closed.
  - A tap strikes on release; a press held 0.22 s strikes and aims.
  - Facts checked in Bevy 0.20.1 and winit 0.30.13: macOS supports `Locked` only; a locked cursor reports a frozen position; a pan arrives as `MouseWheel` in pixels with touch phases; its coast is not marked.
  - **Not driven on hardware:** capture, Esc release and the drawn cursor need a window and real input.
- **Jump on Space** (`skills.rhai` `jump_*`, the rules' new `evades` trait, `jump.rs`):
  - The rules, as proposals for the owner: a 1.6-tile hop the way you move or face, at 3.6 tiles/s; 2 energy; 0.6 s cooldown. It stops short of walls as a dodge does, and it doesn't evade.
  - The height (0.45 m) is drawn only: a crouch, an arc with the legs drawn up, a landing dip, and no foot IK in the air.
  - verify-player has a `jump` scene: the body moved 1.6 m and the blow landed.
- **HUD:**
  - Type is 10% larger than its 1080p design and never under 0.9 of it (it was 0.67 at 720p).
  - F's tap never offers a gesture (`_shows().faces`), so it gathers from a berry bush instead of "face".

**Open for the owner:**
- the jump's rules above;
- Shift is both run and the dodge (each run start also dodges);
- the authority's 0.3 s brake glide after a player lets go;
- whether a tap's strike on release (a click's length later) is acceptable, or the strike should leave the left button;
- people appearing at 10–16 m while the view shows about 100 m (sight is a rule);
- the zoom band, and whether a flick should coast;
- jump and strafe takes in the clip pipeline would replace the procedural jump and the upper-body twist.

## Feel pass 3 (2026-11-11)

Branch `feel-3`. Evidence and before/after stills are in `.local/living/feel-3/` (git-ignored). Client only; the authority and the rules are unchanged.

- **Moves:**
  - `living/tools/oneshot_beats.py` finds when a one-shot clip's hands start, peak and settle in the baked take.
  - The move clips (cast, bow, the three sword takes) now play only their motion. Each starts 0.15 s before its motion, at the rate (0.8–2.2×) that lands the peak on the rules' windup, and fades 0.35 s after it settles. Before, they played whole at 2.2–3.4×.
- **Guard:** a guard let go comes down at once.
  - The fighter row keeps its 8 s `release_ms` after a let-go; only `until_ms` is shortened.
  - The client now treats a row whose end comes before its release as cut short. Before, a guard released after 1 s stayed drawn for 8 s.
  - The heal "never played" because the rules refused it: "you are not hurt".
- **Dodge through a bench:** this is the rules' design, not a dash bug. Benches are props that `PropKind::blocks()` leaves passable ("low things"), so walking passes through them too. Making them block would change every world's hosted tiles: a rules decision.
- **Camera:**
  - Buildings (lots) are `Solid`. Where the eye would fall inside one, it comes in along its line to the focus until it is clear, at once, and eases back out. A building merely in the way still fades.
  - Opening the text box no longer frames the nearest person at 8 m; an answer does.
- **Connection:** until the first connection gets through, the first-load cover says "Can't reach the world", with the server, why, and when it is tried again. It no longer lifts after 30 s onto an empty sky.
- **Interface:**
  - Rules names read as words, with a capital.
  - A list's title is in the title face, over a rule.
  - Know-how reads "You know  …".
  - A plate sits behind the bars and the skill bar, and the health bar shows its value.
  - The pack lists each item's name, its worth as food (muted) and its count (gold), with a carry bar.

## Feel pass 4: the first minutes (2026-11-11)

Branch `feel-4`. Evidence is in `.local/living/feel-4/` (git-ignored). Client only.

- **Arrival:**
  - The first load names its stage under "Arriving…": reaching the world, shaping the land, finding your way in.
  - Low buildings (market stalls) fade when they hide you; a newcomer arrives among the stalls.
  - F with nothing in reach says so, instead of opening the list of acts on oneself.
- **Crowds:**
  - Speech bubbles stack without landing on one another. A lifted bubble rose 1 px past an obstacle, inside the overlap test's 3 px margin, so the stacking passes ran out.
  - A speaker under the cursor no longer gets a nameplate repeating the name in their bubble.
  - The authority's labels ("a stranger") are capitalised on plates, bubbles and in the log.
  - Look-dev's sample HUD has a `crowd` state.
- **Jump:** the legs hold their stride in the air instead of cycling, and foot IK eases out and in over the first and last fifth of the flight.
  - Air, median foot motion: 8.8 → 1.0 cm a frame.
  - Landing peak: 46 → 24 cm.
  - Take-off peak: 48 → 32 cm.

## Edge of sight (2026-11-11)

Branches `sight-edge` and `sight-2`. Evidence, with contact sheets, is in `.local/living/sight-edge/` and `.local/living/sight-2/` (git-ignored). Client only: no authority, rules or bindings changes. The client now also subscribes to the public `gate` table.

The screen drew ground and buildings to about 180 m, while people came and went at the rules' sight. **F2** cycles three ways of showing where your character's sight ends. A note names the new mode and the key ("Edge of sight: not seen now · F2 changes how it is shown"). The same note shows for about 6 s on arrival, so the key can be found: since talk-1 it is on the line of first-time hints under the target frame, with the talk hint (`ui/tips.rs`). After that it shows only when the mode changes, over the skill bar. `LIVING_SIGHT_EDGE=fade|unseen|limited` sets the starting mode, for headless captures.

- **Not seen now** (the default since `sight-2`): what your character doesn't see now is drawn greyer, flatter (toward the fog's colour, so night stays dark), dimmer and a little cooler. That covers:
  - ground, buildings and scenery beyond your sight, over a soft band from 1.5 m inside the radius to 3 m beyond it;
  - what lies behind something that blocks your sight lines (a building, a market stall, a well, rock, a shut gate), with a soft edge about half a tile wide.

  The things that block are drawn normally when any face of them is in sight: you see the stall, not what stands behind it. Everything stays drawn, because it is public; the sky is left alone. People whose sight line breaks fade out as it breaks.
- **Fade:** people fade in and out at the edge of sight (`fade.rs`). Nothing else changes.
- **Limited view:** as "not seen now" for people. The view also fogs from your sight radius to 1.3 × of it, in the fog's colour, and the camera's far plane stops just past that. What lies behind something within your sight fogs 80% of the way. The camera's angle, distance and controls are unchanged.

**Why "not seen now" is the default.** It shows the sight lines and leaves the town readable. Limited view hides most of the town by day behind stalls and houses, which makes it hard to find your way. Fade shows nothing of why people vanish. The owner had not found F2 in play-test 2, so the modes were never compared; the arrival note is there for the next play-test.

**What the rules do** (`sight-2`, read from the authority and rules source; details in the evidence README):
- **No facing.** Sight is a radius and a clear line, the same all round. No path has a cone or a facing term: not players' perceived sets, minds' scenes, behaviour graphs, witnessed events or the combat feed (`perception::in_sight`, `perception::visible`). Facing matters only to a raised guard (`Aim::Facing`) and to the social `turn`. The only cone in the code is `living/game/src/sight.rs`, a client-only mock for tile worlds that is off by default and not the rules.
- **What blocks a line:** `Map::sight_clear` walks every tile the segment crosses between the two exact positions, each end's own tile excepted. A tile blocks if it is `Wall` or `Rock`, or is a shut gate (`Map::blocked`). The hosted map turns into `Wall` the footprints of buildings, towers, **wells** and **market stalls**, and of fountains, market crosses, carts, kiosks, food stalls, vending machines, containers and salvage (`host::hosted_map`). Water, forest, trees, benches, lamps, crops, fences, barrels and crates do not block.
- **No hysteresis on the line.** The sweep runs every 200 ms. Its one-tile hold (`keep_seen_m`) widens only the distance for someone already seen. A broken line drops them at the next sweep.
- **So people vanish behind stalls and wells.** By the rules these are as opaque as a house, though the camera sees over them. In the captures, 36 of the 64 people within reach were inside 48 m by day but behind something. One stood 3.5 m away, behind the stall next to the player.

How it works (`sightfield.rs`, `sightedge.rs`, `edges.wesl`, `post.rs`):
- **The radius is the rules'.** The client asks the world's installed script (`senses(a)`, the law the authority's perception sweep uses) for your character, in one place (`sightedge::my_sight`). Night and how dark it is come from the world's `daylight` law at the displayed hour (since `rules-1`), and a torch from your inventory. The radius eases to a new answer over about a second.
- **The sight field is the authority's test on the same tiles.** The client keeps the tiles as the authority hosts them:
  - the land regenerated through `host::hosted_map`, with its digests checked;
  - the window's `terrain_chunk` rows where they differ from it;
  - the shut gates from `gate`.

  It runs `Map::sight_clear` from your drawn position to the centre of every half-metre texel within your sight plus 4 m, in a 256 × 256 texture (±64 m). Blocking tiles joined to a seen one are marked seen too. The field is worked out again on the async compute pool when you move 0.25 m, your sight changes or the tiles do. The finishing pass samples it, filtered, at each pixel's ground position.
- **People leaving sight.** In "not seen now" and limited view, someone drawn whose exact line from you breaks (`Map::sight_clear`, from your drawn position to theirs) fades out at once. The authority's next sweep and its delivery then stop sending them; in the captures that came 17–181 ms later. Nobody is drawn who isn't sent.
- **The fog** is round you rather than Bevy's distance fog from the camera: the eye is about 22 m from you, so a camera fog at a 14 m night sight would hide your own character. Shell outlines are drawn outside the finishing pass, so in limited view they stop halfway into the fog band.

**Checked against the authority.** The checks used `verify-sight2-1`, a scratch world from the play-test 2 module: Brackenford, no mind service. It had the scene's sight (48 m by day, 20 m with a torch, 14 m at night). Each check compared the client's dumped field with the authority's `perceived` rows and every body's position (owner SQL), at three spots by day and three at night.
- 63 of 64 bodies within reach agreed. The one miss stood on the shadow's edge (field 0.51).
- After merging `rules-1`, the check was repeated on a world built from it (`verify-sight2-2`, same scene; the new script with the scene's distances): 47 of 49 agreed. Both misses were at the half-metre resolution of the ground mark: one person walking on a shadow's edge, and one seen through a gap between stalls narrower than a texel. The one in the gap was drawn, since people follow the exact test, but the ground under them was drawn dimmed.
- Over 270 client-side checks of people drawn, 2 had a broken line: people mid-departure, within the sweep's 200 ms.

**Cost** (laptop, with other agents' builds running):
- One field recompute at 48 m tests about 34,000 texels: mean 1.3 ms, max 2.7 ms on a quieter machine (1.2–1.9 ms under load). At 14 m it tests about 4,000: 0.3 ms. It runs on the async compute pool, off the frame. Walking, it runs about 7 times a second (every 0.25 m).
- Each recompute uploads a 64 kB texture.
- The pass adds one filtered texture sample per pixel.
- Frame time showed no cost. Each build ran one uncapped headless window at 1280×720, among the stalls by day, 20 s per mode, under a load average of 13–17 from other work. The previous build's medians were 5.9–6.6 ms; this one's were 5.8–6.4 ms in every mode.

**Not done:**
- **Lit people are not marked.** Since `rules-1`, a world's `glow` law can show someone beyond your sight: Cullet's laws do this for a carried torch at 48 m and lamplight at 28 m, at night. The authority still needs a clear line to them. The client draws whoever it is sent. Such a person stands in the band dimmed by distance, and the field doesn't reach that far, so the screen doesn't mark them as lit. The fade on a broken line uses the exact test, so it holds for them.
- The two-distance rule (see at 48 m, know at 24 m).
- Weather shortening sight. That waits on rules that do it.
- Terrain edits are known only within the client's `terrain_chunk` window: 7 × 7 chunks, re-centred as you walk, so at least about 24 m round you. Edits made since world creation farther out, within a 48 m sight, are not in the field.
- No settings menu; that comes with the interface redesign.

**Looks (branch `sight-look`, 2026-11-11; merged with `fov-client`).** After play-test 3 the owner liked the idea but not the grey. There are five other ways to draw "not seen now". Since `fov-client`, `memory` is the default; the owner hadn't picked one, and it was the comparison's recommendation. The others, grey included, are chosen in Settings › Play › Unseen ground, which the settings file keeps, or with `LIVING_SIGHT_LOOK`. They are not in F2's cycle. The five are:
- `wash`: a faded watercolour with a dry-brush edge;
- `lantern`: sight as light, with darkness beyond;
- `shadows`: sight shadows cast from the eye in the toon shadow's hue;
- `hatch`: pencil hatching on toned paper;
- `memory`: seen ground drains to a pencil sketch over 10 s, and someone who leaves sight stays 3 s as a faint figure where they were last seen.

All five are in the same finishing pass, from the same sight field. `memory` adds a texture of when each texel was last seen within the radius, and `live.rs` holds the departed body for its figure. No frame cost was measurable against grey (paired switches, shared GPU). The comparison page is `.local/living/sight-look/index.html` in the main checkout.

**Facing sight (`fov-client`, 2026-11-11).** While the world's `fov_on` law is on ([perception](PERCEPTION.md#the-field-of-view-seventh-change)), what I see depends on where my body faces, and the screen shows the same rule.
- **The field:** `senses(a)` gives a `field`. The sight field (`sightfield.rs`) tests each texel with the rules' `sight::reach` at its angle off `body.heading`, as well as the clear line. The heading is read with `steer::pose` from my own motion row, so the field follows the authority's facing, never a local guess. It is worked out again on a 2° turn.
  - The three zones show in whichever look is chosen: full sight within ±70°, a third of it out to ±110°, and 3 m all round (2 m in the dark).
  - Off (as shipped), the field is exactly what it was.
  - People who leave the field fade as they leave it, by the same angle test with its margins.
- **The readout:** each change shows two notes for a few seconds: "Facing sight on" (or off) and the five values (focal, side, side share, near, margin). Settings › Play › Facing sight shows them for as long as it is on, as "Facing sight: on/off".
- **The switch:** F5, or the switch in Settings › Play. `set_world_law` is admin only, and the player's identity gets no admin rights. A play scene that opts in (`"law_toggle": true`) has its launcher give the client the world admin's token in a private file. The client opens a second connection with it, for that one call and only to a `verify-*` world. Elsewhere the line is read-only.
- **The look:** `human_face(dx, dy)` (`controls::look`).
  - Facing the cursor, the cursor's direction is sent while standing. While a direction is held the look is released (`FACE_WHILE_MOVING`, off until look-2 makes a look turn only the facing): on main a look bends the walk itself, which play-test 5 felt as drift.
  - Facing where you walk, a look is sent only while a move is aimed, then released.
- **Heard, not seen:** each `heard_sounds` row is a soft, fading mark on the ground that compass way, at its band's rough distance (near, close, far), keyed by its per-viewer key (`heardmark.rs`). Visual only.
- **Verified:** `verify-ui` `field` ([its recipe](../.agents/skills/verify-ui/features/field.md)).

## Talking and tapping (2026-11-11)

Branch `talk-1`, after play-test 2. In that session the residents answered every line within 3–28 s, yet the owner found them "not interactive". Evidence is in `.local/living/talk-1/` (git-ignored). Client only: no table, reducer, view, subscription, rule or mind change. The client calls the existing `human_say(text, to)` with `to` set, and reads `silence` rows from the existing `my_experience` view. No SpacetimeDB feature is used in a new way, so no new documentation was consulted.

- **Addressed speech** (`talk.rs`, `ui/chat.rs`):
  - Enter opens the text box addressed to the person under the cursor, if they are within earshot, else to the nearest person within earshot.
  - Earshot is the rules': the world's `senses` law, asked per person perceived. The play-test scene gives 12 m.
  - The box reads "Say to a stranger" (or a name the rules give: the projection's `label` from `seen_characters`), and the one addressed is the HUD's target while it is open. Tab goes to the next person within earshot, nearest first.
  - With nobody in earshot it reads "Say — nobody in earshot" and the line goes to no one (`to = 0`), as before. If the addressee is no longer perceived, the box falls back to the nearest person in earshot.
  - **What the authority accepts:** any `to`. Everyone within their own hearing hears the line. The one addressed hears it as said to them (salience 0.9, a conversation turn for their mind), whatever the 6 m `address_m` rule for unaddressed speech. If the addressee is out of earshot, they hear nothing and the speaker gets "No answer from …" (a `silence` row). The client shows that as a red note, and shows "speaking too fast" (a line within 2 s of the last) the same way.
  - Before, every line was `to = 0`: with two or more people within 6 m, nobody was addressed, and a stranger's unaddressed line draws no turn from minds that do not care about them.
- **The tap rule** (provisional; the owner is being asked what they expected): *a left tap on a person who is not hostile to you (has not hurt you in the last 15 s and has no move aimed at you) turns you to them and opens the text box to them; striking them takes a held press (0.22 s).*
  - Animals, and people hostile to you, are struck by a tap as before.
  - With the box open, a tap on a peaceful person addresses them instead.
  - `combat::hostile_to_me` is the HUD's hostile stance, now shared.
- **First-time hint** (`ui/tips.rs`): "Enter — talk to the person you point at", under the target frame, for 6 s once the first load lifts, and again the first time someone speaks to you. `Tips::once` is a shared line: sight-2's F2 arrival note moved onto it at the merge, and others (F3) can stack there.
- **F1 controls line:** it said "right click: walk to" and "R: turn to where you face". It now lists the skill bar's keys.
- **F at remains offered "take wound tending"** and the authority refused it three times. The client checks `take` as if the remains held whatever is asked, because their contents are not perceived, and its candidates included the techniques the player knows.
  - Techniques are now candidates only toward a person (teach) or oneself.
  - A refused act is no longer the one a tap repeats.
  - Still open, for the interface redesign: what remains or a store hold is not perceived, so `take ›` can still offer an item that is not there.

Measured on scratch worlds from the play-test 2 scene's module and script (`verify-talk1-*`; no mind service, no model calls):
- In the crowd case (three people within 6 m), the line went out with `to = 7`. Osric's row reads "A stranger said to you" (0.9); the two others' read "A stranger said to Osric Abbot" (0.45).
- A tap on a peaceful resident sent `face` and no strike. A held press struck them (hit for 10). A tap on a resident who had just struck the player struck back (hit for 7).
- At the remains, `take wound_tending` is not offered; `take berries` is.

Not covered: the "No answer" note and the "(out of earshot)" label on screen. The authority's `silence` row was shown by verify-player. Also not covered: a real trackpad (captures are headless), and whether minds answer an addressed line (no mind service ran).

## Feel pass 5 (2026-11-11)

Branch `feel-5`, after play-test 2 (`.local/living/playtest-2/FEEDBACK.md`). Evidence is in `.local/living/feel-5/` (git-ignored): a README, the inventory (`INVENTORY.md`), the clips wanted (`CLIPS_WANTED.md`) and a contact sheet (`index.html`). Captures were headless runs of the real client on the scratch island world `verify-feel5-a`. Client only: no authority, rules, bindings or seed changes.

**The jump's facing flip** (`live.rs`):
- The owner: "When you jump while moving in one direction, the animation flips and plays in the default way, and then you flip back."
- **Cause:** a jump's `fighter` aim is the authority's dash direction, which is the travel. `live.rs` took any move's aim as the body's facing, so a body walking sideways or backward while facing the cursor turned to its travel for the hop: forward gaits, no twist. It turned back after.
- **Fix:** the jump's aim no longer sets the facing; the jump is drawn over whatever the body plays (`jump.rs`). A dodge's roll is a forward take, so it still faces its dash.
- **Measured** over eight moving jumps (walk and run; sideways, backward and diagonally) while looking north:
  - the upper body's facing moved by 45–180° during the jump before, and by 0° after;
  - backward legs flipped by 180° and back before; after, the reversed gait holds through take-off, air and landing.

**Two control schemes** (`controls.rs`, `live.rs`, `combat.rs`):
- **F3** switches between them.
- `LIVING_GAME_CONTROL=cursor|travel` sets the one to start in.
- A note in the HUD's existing styles names the key and the scheme: "F3: controls (facing where you walk)" or "F3: controls (facing the cursor)".
  - It shows on arrival, once the first-load cover lifts, on the line of first-time hints (`ui/tips.rs`, `talk-1`), with the edge of sight's F2 note and the talk hint, for about 6 s.
  - After that it shows for 4.5 s among the verbs' notes, only when the scheme changes, as F2's note does.
- **"Travel"** (facing where you walk): the body faces its travel, and standing, its last heading.
  - It turns to the cursor only while a move is aimed there, and back to its travel after. That means a skill key held on a skill aimed at a creature or a point, a guard up, or a move under way that faces its aim (`combat::aims_at_cursor`).
  - A dodge or jump with no direction held goes from the facing drawn: a dodge back from it, a jump toward it. In the cursor scheme it goes from the cursor, as before.
  - The compass and the view's align use the facing drawn too (`Input::facing`).
- **"Cursor"** (facing the cursor): the body faces the cursor while you move with WASD, as on main, with two changes:
  - **Standing,** the upper body turns first. The legs turn only once the look is 55° from them, and then all the way (to within 6°). On main every cursor move turned the whole body. In a sway of ±25°, the toes travelled 279 cm over seven swings on main and 5 cm now.
  - **The twist** over the spine gives more to the neck and head: at a 90° strafe, 52° in the spine and 38° in the neck and head, against 65° and 25° before.
  - A share on the pelvis (with the thighs turned back) was tried and dropped: under foot IK it moved the planted feet ±7 cm as the cursor swayed.
- **The default is "travel".** Reasons:
  - **What the screen shows is what the rules see.** The client sends no facing to the authority: only `human_move(dx, dy, run)`, each skill's aim point and target, and the `face` gesture through `human_act`. The authority, and the residents who perceive you, take your facing from your movement heading (the body's `heading`; `bearing` and `face_slack` in the act rules). In "travel" the screen and the rules agree, except while aiming, which reaches the authority through the skill's aim. In "cursor" they disagree whenever you look away from where you walk.
  - **It plays the real clips.** Every direction of travel plays the forward clip. In "cursor", every direction but forward is the forward clip turned or played backward (inventory below).
  - **It answers the owner's main complaint:** "the player faces the cursor but moves in the other direction".
  - Facing the cursor stays one key away. A look-direction input to the authority may come later (the Spark's coordinator); the cursor scheme would then send it.

**Locomotion inventory** (`INVENTORY.md`):
- **Clips:** five forward loops (`sneak`, `walk`, `walk_brisk`, `run`, `run_fast`). There is no backward, sideways, diagonal, turning, starting, stopping or jumping take.
- **In scheme "cursor":**
  - forward: the real clip;
  - diagonal forward (±45°) and sideways (±90°): the forward clip along the travel, with the upper body twisted 45° or 90°;
  - diagonal back (±135°) and backward: the forward clip reversed, twisted 45° or not at all;
  - between 80° and 110°: either, with hysteresis;
  - turning, starting, stopping and the jump: procedural.
- **Foot slide** stays at 2–5% of the body's speed walking and 4–9% running in every direction and both schemes (feel pass 2's legs-to-travel rule), on a paved square at 2.3 and 3.5 m/s.
- **How it looks:**
  - sideways reads as walking sideways from the chest;
  - backward reads as a walk played in reverse, and at a run as a moonwalk;
  - the legs spin round when they swap between forward and backward.

**Clips wanted** (`CLIPS_WANTED.md`, for the Spark's text-to-motion; none generated here):
- **For "cursor", in priority order:** `walk_back` and `run_back` (backward, loops); `strafe_walk_left`, `strafe_walk_right`, `strafe_run_left` and `strafe_run_right` (90° to the side, facing ahead, loops). Diagonal takes (45° and 135°, walk and run, loops) are optional: blends of the cardinal takes with a 45° warp usually suffice.
- **For both schemes:** `turn_left_90`, `turn_right_90`, `turn_left_180` and `turn_right_180` (standing, one-shots); `walk_start`, `walk_stop`, `run_start` and `run_stop` (forward, one-shots); `jump_stand` and `jump_forward`, plus for "cursor" `jump_back`, `jump_left` and `jump_right` (one-shots at the rules' 1.6 tiles at 3.6 tiles/s).
- **Pipeline:** `animate.py --library` measures travel forward only. Sideways and backward takes need a travel direction per entry, with Kimodo's `path` constraint pinning the hips' line.

**Not done:**
- No strafe or backward clips: the cursor scheme still shows the procedural blend above.
- Turning on the spot beyond 55° still swivels the legs in about 0.13 s and steps both feet.
- The settings menu belongs to the interface redesign.
- The strike was not captured turning to its aim: the scratch square had no one in reach, so the rules refused it ("no one there to strike").

## Locomotion clips (2026-11-11)

Branch `clips-2`: the laptop half of the clip lab for the Spark's 29 new takes (`assets-locomotion` at `4a1713b`, merged here; tarballs `locomotion-A`, `-B`, `-C` and `-B-diagonals`). Evidence is in `.local/living/clips-2/` (git-ignored): the contact sheet (`index.html`), `verdicts.json`, the bake's tables, the captures and the tools. Captures were headless runs of the real client on the scratch island world `verify-clips2-a`. Client and `animate.py` only: no authority, rules, bindings or seed changes.

**`animate.py`:**
- `travel_deg` (optional, locomotion loops): the take is faced ahead with its travel turned that far (the game's sense: -90 left, 90 right, 180 back), so its cycle and speed are measured along its own direction. The sidecar gets `travel_deg`, `locomotion`, `facing_deg` and `cycle_m`.
- `turn_deg` (a turn on the spot): after the feet are planted, the turn is taken out of the clip (`unturn`: the hips turned back about the vertical by the hips' heading so far), so it ends facing ahead in the neutral pose. The sidecar gets `turn_deg` (measured), `turn_planned_deg` and `turn_curve`; the game turns the body along the curve.
- A `travel: path` one-shot that hops, has `travel_deg` or starts or ends in a gait's frame gets `path_m` (the body's own track) and `hop`; a start or end in a gait baked in the same run gets `start_gait`/`end_gait` ({clip, phase}).
- **Existing entries bake byte-identically** (dev-box's condition): the 34 existing entries on Vivi, before (`origin/main`'s `animate.py`) and after, give the same GLB (sha256 `3f3fab94…`) and sidecar (`a8cd88ce…`); gen_person's 13 entries on `own-man.glb` likewise (`4e76d9d4…`, `ebf46cb8…`). The turn handling touches the hips, so every new take was also baked onto `own-man.glb` (`gen_person.sh man`) and photographed in the asset view.

**Verdicts** (sent to the Spark as `clips-2-verdicts-2026-11-11.tar.gz`; per clip in `verdicts.json` and on the contact sheet): 17 accepted, 8 retakes, 4 a fix on our side.
- **Accepted:** the four turns; `jump_stand`, `jump_left`, `jump_right`; `walk_back`, `strafe_walk_cross_left` and `_right`; `walk_diag_fl`, `_fr`, `_br`; `run_diag_fl`, `_fr`, `_bl`, `_br`.
- **Retakes:** `run_back` (a planted foot slides 16–19 cm in the baked take on all three rigs); `strafe_run_left` (a 15.5° seam that pops); `strafe_run_right` (1.18 m a cycle); the step-touch `strafe_walk_left` and `_right` (0.6 m a cycle); `walk_diag_bl` (a toe 6–8 cm low at its seam); `jump_back` (through the floor, as the lab found); `jump_forward` (it lands into a 1.9 m/s walk: in the game the landing slid 0.5–3 m/s, against 0.03–0.9 for the arc).
- **Our side:** `walk_start`, `run_start`, `walk_stop`, `run_stop`. The takes are clean, but the authority starts a body at full speed and stops it where it is. Drawn along the start's own track, the body fell 0.6–0.9 m behind the authority's, and its catch-up slid the feet 24% of the body's speed (6% with the fade-in). A stop would carry the body 0.8–1.6 m past where it stopped.
- **Stride against the rules' speeds.** People walk at 2.6 m/s and run at 3.9 (times the speed gene; 1.4 times that on a road). The sideways and backward takes cover 0.4–0.8 of the forward gaits' metres a cycle, so with planted feet they step 1.5–2.3 times as often, up to 9 steps a second. The verdicts ask for takes at the rules' speeds.

**Wired** (`takes.rs`, `gait.rs`, `live.rs`, `anim.rs`, `combat::Action::gait`; `LIVING_GAME_TAKES=off` turns it all off, for comparisons):
- **Both schemes, turns on the spot:** standing, when the legs would swivel more than 55° (to the cursor, a standing body's own heading or its activity), the 90° take plays (up to 135°, else the 180°) at 1.3×. The body turns along its curve, and the upper body still leads toward the cursor. In the capture, 90° and 180° looks turned the legs exactly 90° and 180°, stepping 63 and 121 cm of toe path (the swivel before: 66–69 and 118 cm).
- **Both schemes, jumps:** standing, `jump_stand`; sideways (scheme cursor, with the legs facing the cursor), `jump_left` or `jump_right`. Each starts just before take-off, timed so that its flight, when both feet are up, takes the rules' 0.44 s. The gait steps on under a moving jump (`Action::gait`) and takes over as the take fades, just before touchdown. A standing jump's landing slid 0.05 m/s, against 0.24 for the arc. Jumps forward while moving, backward hops and files without takes keep `jump.rs`'s arc.
- **Scheme cursor, directional loops:** the legs face the cursor, and the takes either side of the travel blend by angle, each its walk and run by speed (`Gaits::blend_toward`, up to four gaits at the shared phase). A direction plays only while it steps at most 1.6 times as often as the forward gait would (`CADENCE_MAX`), and only while its mirror does too. A swap to or from the forward gaits waits 0.3 s, since the travel's heading swings round as a walk starts. Elsewhere today's blend stays: the forward gaits along the travel, reversed backward, with the upper body turned.
  - At the rules' 2.6 m/s walk on plain ground, this plays the forward diagonals and, through the backward jogs, the back diagonals. Sideways and straight back fall back, except for slower bodies (children, elders, the tired). Running, only the forward diagonals play.
  - Capture (the same character before and after, on a paved square at 3.6 m/s walking and 5.4 running): the diagonals played their takes, and the supporting foot slid 4–8% of the body's speed on them, against 1–6% before with the forward gaits turned. Every other direction fell back and matched before (1–7%). Their metres a cycle set their cadence at 1.1–1.5 times the forward gait's.
- **Not wired:** the starts and stops (above), and the retakes. The asset view now turns and moves a model by its take (`view.rs`: the turn curve, the path, a loop's belt), so a contact sheet shows planted feet as the game will.

## View distance and the grey city (2026-11-11)

Branch `view-1`, for the owner's walk through Cullet's grey city ([small city](SMALL_CITY.md) §5 and §6, [authored plans](AUTHORED_PLANS.md#the-game-client)). Evidence is in `.local/living/view-1/` and the walk's stills in `.local/walk/runs/` (both git-ignored, in the main checkout). Captures were headless runs of the real client on scratch Cullet worlds (`verify-view1-*`, no residents, no mind service), and offline look-dev. Client only: no authority, rules, bindings or seed changes, and no SpacetimeDB feature used in a new way.

- **The fog follows the mood** (`camera.rs`, `world::Draw`):
  - The camera fogged from its own draw radius on every world: 50 to 105 m for an adult. Since `plan-1` the land picks its mood (`envs/<id>.json` whose `world` names the land's seed and size), and the camera now fogs by that mood's `fog_start` and `fog_end`, scaled by the character's size. The atmosphere still scales it after (night and fog close it in, `daylight::apply`).
  - The island's mood is 70 to 160 m; the town square looks as before, a little clearer at the far end. Cullet's is 180 to 600 m. Tile worlds and the character line-up keep the old fog.
  - The sight edge's limited view still wins: it fogs from your sight and brings the far plane in (`sightedge::far`).
- **Landmarks drawn far** (`live.rs` `lots`, `island.rs` `stream`):
  - Lots with `landmark: true` in the regenerated land (Cullet's Cone, Counting House, Heron, Watchglass and Lintel) are drawn out to the mood's `fog_end` (600 m on Cullet). The `lot` window reaches only ±184 m, so a landmark beyond it is drawn from the regenerated land (the land's lot indices are the rows' ids). Ordinary lots stay at 190 m.
  - Past the detailed ground (170 m) and out to `fog_end`, the ground and the sea are drawn coarse: a vertex every 4 m, no scatter or props. Four sea quads round the map end a long view over the water in fog, not at the map's edge.
  - Ordinary things (lots, chunk props, scatter) fade out, dithered, over the last 25 m of their draw distance (`envs::Reach`), because Cullet's fog no longer hides that edge.
  - The far plane stays past the landmark reach (1000 m by default; at least 1.1 × the reach + 50 m). Bevy 0.20's perspective is infinite reverse-Z on a 32-bit float depth buffer, so the far plane only culls: at 600 m one depth step is about 0.04 mm.
- **Lots without a model** (`island.rs` `lot_item`):
  - **Cause of the bare ground:** building lots were already grey boxes. The bare lots were Cullet's 23 open lots of no height: the Fish Steps, the slip, the Cone yard, the Marver's terrace and the graveyard are `lamp` lots of height 0, which `spawn_lot` skipped, and the 18 root plots are `garden` lots, which have no model kind. So the Fish Steps' notch was a grass tongue. (The other open lots have a height and were boxes: the dry dock 8 m, the cistern 2.6 m, the thorn 4.5 m, the Crown bench 0.5 m.) `envs::assets_for` returned nothing from another environment (`shared/` has no building kinds), and no connected path was skipped.
  - A planned settlement's lot now draws its own model when it is on disk, else a grey box of its footprint and height, else, for an open lot of no height (the 23 above), a slab 2.5 cm high of its footprint in a darker, muted stone (sRGB 132, 128, 120 against the boxes' 168, 168, 172), casting no shadow. It never borrows another model of its kind, so an empty or missing `envs/cullet/` gives the grey city cleanly. Generated towns still sample their kind's models.
  - Connected and look-dev use the same rule. Grey boxes now carry their box as `lookdev::Fitted`: the camera's keep-out query needs it, so connected boxes, though `Solid`, could hold the eye inside them. Look-dev's lot boxes and models are `Solid` too.
- **The quay face** (`island.rs` `face_share`):
  - **Cause:** no relief stamp covers the quay, so its tiles are the level's grass. A quay stands out of the sea within half a metre (`settle::plan::Ground`), from +2 m to the 6 m deep bed. The 1 m ground mesh's smoothed normals round that step into a slope that the shader's slope test (rock below N.y 0.72) left as grass.
  - The ground mesh now moves a vertex's layers to rock, and its colour to stone, by its steepest step to a neighbour (from 0.9 to 1.6 m per metre). Stairs climb 0.55 m per metre and are untouched. Steep generated slopes on the island get the same stone, as the shader already intended.
  - **Not in the rules' data:** the quay's top surface. Levels carry no surface for clients (streets have `surface`, the square `paved`), and a stamp's `ground` of `rock` would make the tiles block walking. The Strand street covers the quay to its edge, so only the face showed; a paved quay beyond its streets would need a client field such as `levels[].surface`.

**Frame cost** on Cullet by day (`verify-view1-c`, built from `f2d803fa` with this branch; no residents). One binary, with and without the long view (`LIVING_GAME_PERF=nofar`: no coarse ring, no landmarks past 190 m), two interleaved runs each, 24 s at each spot, one headless 1600×900 window, under a load average of 15 to 20 from other agents' builds. Median of 2 s windows:

| Spot | Without | With | Drawn with |
|---|---:|---:|---|
| The Ladder's west end, looking east over the town | 18.3, 18.3 ms | 20.1, 22.6 ms | 38 detailed and 176 coarse chunks, 969 meshes (651 without) |
| The Crown, looking south over the town | 18.3, 18.9 ms | 19.1, 18.7 ms | 39 + 201, 1,073 meshes (695) |
| The arrival point, looking east along the quay | 18.4, 18.6 ms | 18.2, 18.3 ms | 40 + 173, 1,039 meshes (729) |

The long view costs about 2 to 4 ms where most of the screen is far ground (the Ladder's view east covers about 600 m of land), and nothing measurable elsewhere. Headless frames here do not go below about 18 ms, so a real window may show the difference differently. If it costs too much in play, the first thing to try is a cheaper material for the coarse chunks (they are drawn with the painted ground shader).

**Not done:**
- The coarse ring meets the detailed ground with T-junctions (a crack of a few centimetres at 170 m is possible, not seen in the captures).
- People beyond sight are still not drawn (that is the rules' sight, 48 m by day on Cullet).
- Coarse chunks draw no props, so the Lintel stands alone on its headland.

## Ground per environment (2026-11-11)

Branch `ground-1`, the client half of kit-2 (dev-box paints the layers and writes Cullet's map and areas). Client only: no authority, rules, bindings or seed changes. An environment can now say what its own ground is, so Cullet's quay is flagged, its Cinder Row cindered and its root plots dug, instead of wearing the generic island's grass and cobbles.

- **Layers** (`terrain.rs`, `terrain.wesl`): nine more after `gravel` (`slate_setts` 3.2 m, `quay_flags` 4.8, `cinders` 2.6, `kelp_shingle` 3.4, `wet_sand` 5.0, `peat` 4.0, `heather` 3.6, `worked_soil` 3.2, `thin_turf` 4.0, all strength 1), `cliff` still last: 24 weighted layers in six `Unorm8x4` blend attributes (shader locations 8 to 13), 25 in the array.
- **Matching by name** (`terrain::match_layers`, `load_array`): `ground.txt` no longer has to equal the client's list. Each client layer takes the painted layer of its name, else its nearest old layer (`terrain::fallback`: setts as cobble, quay flags as flagstone, cinders and kelp shingle as gravel, wet sand as sand, peat as mud, heather as dry grass, worked soil as dirt, thin turf as grass), else is flat; names the client doesn't know are skipped with a warning. Today's 16-layer `ground.png` and kit-2's 25-layer one both draw; the log names what is borrowed. Material layers (`style::DetailLayers`) match by name too, with no fallbacks.
- **The map** (`ground.rs`): keys with a colon inside an environment's `ground` object (`envs/<env>.json`, beside the old four keys, which still work). Each value is `{"layer", "colour" (sRGB), "tint" (optional)}`; the tint is where the colour leans in slow patches of tens of metres. Keys: `street:<surface>` (a plan street's `surface`), `class:<Terrain>` (`Road` is a road tile without a street surface, such as the paved square), `region:<RegionKind>` as the seed spells it, `stamp:<ground>` (a relief stamp's `ground`, where its tiles still are that ground), `area:<surface>`.
- **Areas**: `envs/<env>/ground.json`, beside `fixtures.json`, written by the kit's generator: `{"id", "surface", "area" (polygon, land metres), "cause"}`, later entries on top. A vertex off the roads inside one takes `area:<surface>` if the map has it. Area edges are crisp, like roads, and don't bleed into the blend round them.
- **Lookup**, most specific first: a road tile takes `street:` then `class:Road`; any other vertex `area:`, then for each blend sample `stamp:`, `class:`, `region:` (not under water: lake and sea beds keep their mud and sand). What finds no key is drawn by the island's own rules. Roads never take areas, stamps or regions, so a stamp of sand never sands a square.
- **Which map:** the current environment's: in look-dev the environment shown, connected the one whose `world` names the land's seed and size. The first-world fallback (the island's mood on a land without its own environment) brings no map.
- **No map, as before:** with no map nothing is looked up. `island::tests::without_a_map_the_ground_is_drawn_as_before` checks `blended_ground` bit for bit against the old function over Cullet's whole land (every 3 m, both climates), and the old layers keep the first four attributes' bytes. Island stills from origin/main and from this branch differ only within the run-to-run noise of one binary (about 200 of 1.44 million pixels, on outlines and people; evidence below).

**Cost.** A ground vertex is 64 bytes, 56 before. Ground mesh data (vertices and indices, as the perf report now prints it): the island's town at 34 detailed chunks 12.5 MB (11.4 before); Cullet at the Ladder with 33 detailed and 172 coarse chunks 16.4 MB (14.9). Meshes keep a main-world copy too, so RAM grows by the same again. The texture array holds 25 layers of 512² with mipmaps: 33 MB, 12 MB more than 16 layers (until kit-2's strip lands the nine new slots hold copies of their fallbacks). **Frame time** (headless 1600×900 look-dev, three interleaved runs each of origin/main's binary and this one, 14 windows of 2 s after the first, under other agents' builds): the island's town 18.3 against 18.9 ms median, Cullet at the Ladder 18.7 against 19.0 ms; one binary's runs alone spread from 18.0 to 19.8 ms, so the cost is below what these runs resolve.

Evidence: `.local/ground1/` in the `slop-ground1` worktree (stills, logs, the scratch map and areas used for Cullet, contact sheets). The Cullet stills use a scratch map, not dev-box's.

**Verification:** `cargo test --release -p living-game` (57 passed after merging main; each commit built and tested), headless look-dev stills (island A/B, Cullet with the scratch map, the follow-ups before and after) and verify-ui `support` on a scratch Cullet world (`verify-ui-g1-1111-1908`, 7 of 7; the pre-fix client's still of the same flight shows it dithered). `just living-check` was not run on the laptop.

**Untested until kit-2 lands:** the 25-layer `ground.png` itself (its new layers are drawn here as their fallbacks), dev-box's real map and `ground.json`, and how its colours sit with the kit's models.

**Structures from the kit** (`island::structure_model`, `world::things`): a structure (`sign`, `storage`, `campfire`…) standing in a planned settlement is drawn with its kit's model, `envs/<env>/<kind>/*.glb` with the environment `settle::env_of` names for the settlement's style (its own folder, not `shared/`), at real size, origin on the ground. Its front (+Z) faces the nearest street within 40 m; a sign's faces away from the lot at whose door it stands. A fire keeps its drawn flame unless the model glows itself. Elsewhere, and without a model, structures keep their drawn shapes: generated towns' environments have `sign` folders (fantasy, giants, steampunk) sized for look-dev slots, so they are not used, and the island is unchanged. A kit's fire glows by its own `Glow` materials, as lots do: damped by daylight (`lookdev::NightGlow`) while it burns, and not at all once it is out (`lookdev::Unlit`): a kind that `burns` fuel burns while its `lit_until_ms` is ahead of the authority's clock, any other kind (a plain campfire) always; it is drawn again when that changes (`world::things`, `burning`). A model without glow keeps the drawn flame while it burns. Checked on a scratch Cullet world (`verify-ui-s2-1111-1954`, with Cullet's composed laws installed by hand: `verify.py launch` currently installs the plain script over a seed's laws): a placed hearth, never fed, drew out; the seeded hearths and a placed campfire lit. Checked on a scratch Cullet world (`verify-ui-st1-1111-1927`) with a scratch `sign/test.glb`: the two signs the player was sent (2 and 39 m away; the other three were beyond what the player perceives) drew it, and without it nothing changed.

### Kit-1 follow-ups

- **Fixtures stop the camera** (`envs::SolidIfLarge`, `island.rs`): a kit's fixtures, except flights, become `Solid` once fitted if they stand at least 2 m from foot (or foundation) to top and 4 m along their longer side: quay walls, retaining walls, the mole, the Fish Steps, the Marver's terrace. Bollards, lamps, racks and creels stay out, so the camera doesn't jump in front of every post. A fitted box is now centred where its geometry is (`lookdev::fit`): a model with a foundation had its box centred half its height above its floor, so a quay wall's box stood above the wall.
- **What you stand on never fades** (`envs::supports`, `envs::cutaway`; the owner's Cullet walk): the line from the eye to the feet ended inside a flight's box, so the whole flight dithered away while it was climbed (and faded fully when the eye sat inside its box). Anything whose box holds probes at, under or half a metre round the feet now never fades, whatever the eye does: stairs, terraces, a wall's top. A retaining wall at the edge of a drop is 1–1.5 m off (the drop's tiles), so it still fades when it hides you.
- **Landmarks don't fade** (`envs::Landmark`): landmark lots, and anything whose box is more than 30 m from the eye, are never faded for standing between the camera and you. The eye inside a thing still fades it.
- `RUST_LOG=living_game::envs=debug` logs what fades and why, and what holds you up; verify-ui's `support` scenario reads it.
- **Glow by daylight** (`lookdev::NightGlow`, `lookdev::night_glow`): the glow of lots and fixtures (lit panes, the Cone's mouth, quay lamps' glass) is multiplied by how dark it is by the world's `daylight` law (`Scripts::dark`, the sight display's law; the shipped script's in look-dev), so it is out by day, half at mid-dusk and whole at night. Those models get their own glowing materials; written only when the darkness steps (0.05). Glowing plants, crystals and look-dev slots keep their glow by day.

## Edge lines on small steps (2026-11-11)

Branch `edges-1`, after the owner's Cullet walk ("a bunch of textures flickering in buildings"; a sawtooth where a gable meets a roof). Client only.

- **Cause on the client side:** the finishing pass (`edges.wesl`) draws a crease line wherever neighbouring normals differ by more than about 63°. A slate's lower edge (and a sill, a step's nose) is such a face, a few centimetres tall: from tens of metres it is a pixel or less, so it came and went between pixels and its lines beaded and crawled along every row of a roof. Shadows were not the cause (`noshadows` looked the same), and neither was depth precision (Bevy's default reverse-Z perspective, near 0.1 m: depth steps of micrometres at 30 m). The model cause, dev-box found: a party-wall chimney half in a gable's plane on Mid Row 4, fixed in kit-2's generator, whose checker now counts coplanar faces.
- **Change:** a crease is not marked where it is a step smaller than `Style::crease_step` (6 cm) between two parallel faces: the face past the neighbour is parallel to this one and within that distance of its plane, or this pixel is the step and the face behind it is parallel to the neighbour's (walking up to six samples). The test is in metres, so it holds at every distance. Silhouettes (the depth test), outlines and real creases (a gable against its roof, a wall against the ground) are unchanged. The F2 look panel has a slider; `LIVING_GAME_PERF=slivers` (step 0) brings the old rule back for comparison.
- **Evidence** (`.local/ground1/orbit/` and `chars/` in the `slop-ground1` worktree): session-recorder orbits of Mid Row's gables on a scratch Cullet world (`verify-ui-e1-1111-1933`), close (18 m) and far (34 m), old rule and new, side by side in `before-after.mp4` and `far-before-after.mp4`: the beaded rows are gone, gables and barges keep their lines. The character line-up differs only by idle animation. verify-ui `themes` 6 of 6. Frame time at the orbit's spot (look-dev, two interleaved runs each): 18.2 ms old, 18.1 ms new.
- **Not done:** the exact framing of the owner's screenshot (the orbit passes Mid Row's gables, not that one); a real window over a play session.

## Interface D (2026-11-11)

Branch `ui-1`: the owner's choice of interface (design D: B's amount on screen in A's walnut, brass and parchment, A's floating windows; `.local/living/ui-designs/DECISION.md`, pictures `png/d-*.png`). It replaces the old HUD and menus rather than patching them. Client only: no table, reducer, view, subscription, rule or binding changed. Evidence, with a contact sheet of each built state beside its mock-up, is in `.local/living/ui-1/` (git-ignored). Verified by the new `verify-ui` skill (the real client headless on `verify-ui-*` worlds) and `verify-player`.

Built in steps; steps 1–3 are on main, 4–5 follow, and step 6 (the character window, the skills and know-how window, the fight target plate, a look pass) waits for the owner's go-ahead.

**The look is a theme** (`ui/wood.rs`; play-test 4, 2026-11-11: the owner liked the windows' behaviour but not their look or density, "I'd prefer a much cleaner interface"). Every visual value of the D widgets comes from one `Theme`: colours by role (text, edge, surface, accent, field, line), edge width, corner radius, ornament (a frame's inner line, a second body edge), title face and size, shadows, and density (key chips beside titles and buttons, the title bar's grip, help lines shown always or once). Four themes:
- **Clear** (the default): light neutral, flat panels with a 1 px edge and a soft shadow, Nunito only at two weights, no ornament.
- **Night:** the same, dark and translucent.
- **Linen:** warm and flat, a hint of the game's palette.
- **Walnut:** design D as first built (walnut, brass, parchment, Marcellus titles, key chips).

Settings › Play › Look chooses it, F4 cycles it (a note names it: "Theme: Night · F4 changes it"), the settings file keeps it, and `LIVING_GAME_THEME` sets it for captures. A change rebuilds the UI's trees and reopens the open windows where they were. The sizes are the mock-up's pixels: the UI scale is the window's height over 900 (1600×900 is 1:1; never under 0.9). The drawn cursor is the ring and dot of 90f6fac1 again (the owner preferred it to D's arrow).

**Density** (what a player does not need in the moment went, or went behind a click):
- **Windows:** no grip, no key chips beside ✕ (the keys are in the Menu list and Settings), a smaller ✕; titles on one line (a long label is shortened with "…").
- **A person's window:** no second line repeating the title (it shows only a named person's clothes); "First seen 3 min ago · not in sight" on one line; the acts are Give ›, Wave, Look over and More… (Trade…, Introduce yourself and every act the rules allow are behind More…); the box reads "Enter to talk", its "to" chip is shortened, no Enter chip; the line explaining Tab shows until the first line is said.
- **Log and people:** the box's help line shows until the first line is said.
- **The list of acts:** toward a person Talk, Their window, Give ›, Offer ›, Wave and Appraise, then More… (Introduce yourself, Threaten, Tend, Accept, Demand, Host, Conceive, Teach, Nod, Face, Goto, Follow, Flee, Join and the rest); toward a thing, the first four and More…; the title on one line; no "hold F" note.
- **The pack:** no single "Items" tab; only as many rows of cells as it needs (one free row); "Click an item to use it; drag it onto someone to give it." on one line, until an item is clicked or carried.
- **The F prompt:** "F Talk", with "hold F · more" only the first two times a list is opened that way.
- **Hints at the top** (F2, F3, Enter) are drawn in the theme, and still show once a session.

**On screen while playing:** the compass (top right; the needle follows the view; the place's name under it is the nearest place my character knows within 90 m, from `my_places`, and none shows otherwise) and two labelled buttons, Pack (I) and Menu (Esc). The cluster at the bottom (step 4) is still the old bars and skill bar until then. Only while they matter: nameplates, the F prompt beside the person or thing F acts on ("F Talk · hold F · more"), bubbles, notes over the cluster (parchment, marked green when done and red when refused, in the authority's words), and the first-time tip ("New here", bottom left; "Got it" or "All tips"; once a session, and off in Settings).

**Who is under the cursor is one pick** (`pick.rs`, 2026-11-11, branch `talk-pick`). The play-test 5 build check found that with two people overlapping on screen, the nameplate named the one in front while Enter spoke to the one behind. Each asked its own way: the hover took everyone within 1.2 m of the cursor's ground point, Enter the hovered one nearest it, and combat's target the nearest within 3.5 m. Now one pick, made once a frame after the camera moves, serves the nameplate (only that person is hovered), Enter, a tap on a peaceful person, F, the gestures and combat's target. The pick is the body whose outline on screen holds the cursor (feet to head as drawn, about a shoulder either side), and the one drawn in front where two overlap. With no outline under the cursor, it is the body within 1.2 m of the cursor's ground point. Combat keeps its 3.5 m aim assist only when nobody is under the cursor. verify-ui `pick`: 1 of 7 checks before, 7 of 7 after.

**Windows** (`ui/win.rs`; behaviour as play-tested and accepted):
- Two anchors at 1600×900: the left (26, 26) holds a person, the log and people (and later the character); the right (under the buttons, 26 from the edge, top 252) holds the pack. One window per anchor, so at most two narrow windows (426 wide) are open and the middle stays clear. Opening a window takes its home anchor and replaces what holds it. Skills and know-how, and Settings, are wide (1076), in the centre left of the compass column, and close the others. Heights stop short of the screen's edge (the wide ones above the cluster).
- Hold the click on a title bar and slide (a three-finger drag is the same press and move): the window follows, both anchors are outlined, and letting go snaps it to the nearer one. If another window holds it, the two change places; a wide window goes back to the centre.
- Close with ✕, the window's own key (I, L, K) or Esc. A click in a window raises it.
- **Esc, in order:** the list of acts (its sub-list first), the Menu list, the words being typed (with their window), the top window. With nothing open it opens Menu and gives the system cursor back; a click on the world captures it again. `pointer.rs` no longer frees the cursor on its own.
- **Menu:** Character (until step 6, the list of acts on oneself, as C), Skills and know-how (K), Log and people (L), Settings, and Leave the world (asked twice; the character stays in the world and its mind takes it over after the takeover delay).
- **The pointer for the UI** (`ui/hit.rs`): every window, button and row takes clicks from the game's own cursor through the nodes' layout rectangles (topmost by the UI stack), so the system cursor, the drawn one while captured (macOS reports a frozen position then, which Bevy's picking cannot use) and headless scripts take one path. Over a window, or while a press or drag that began on one is under way, the world does not take the pointer: no strike, no view turn. Over a window, two-finger swipes scroll it.

**Talking** (`ui/say.rs`, `ui/people.rs`, `talk.rs`, `looks.rs`, `heard.rs`):
- **The owner's rule (2026-11-11):** "if your cursor is not on someone and you press enter, you go into general chat. If you are hovering someone and press enter, you enter chat with that person specifically. But that conversation should still be kind of public, unless you whisper." So Enter with nobody under the cursor speaks to the room (`to = 0`; talk-1's "else the nearest in earshot" is gone), and the box is in Log and people, reading "To the room". Enter while hovering someone speaks to them (`to = id`) and opens their window with the box in it ("To a stranger in orange"); everyone in earshot still hears it (the rules' `perceive::speak`). Tab goes to the next person within earshot, nearest first, then back to the room. Enter says it and the window stays with the conversation; Esc closes the box and its window. A click in a window's box types to whom it names, even someone out of sight (the authority then answers "No answer from …").
- **When the room does not answer, the client says so.** Minds give a line to the room no turn yet (until the Spark's greeting experiments are on). About 10 s after a line to the room that nobody took up, a note says "Heard by 4 — no one took it up. Point at someone and press Enter to speak to them." (or "No one in earshot heard you."). Who heard it is the people perceived within the hearing law's earshot as I spoke, until `heard_by` lands; someone among them speaking since counts as taking it up.
- **The box's ways of speaking come from a table** (`talk::MODES`): today a person and the room. Whisper (close, or through skills such as telepathy) and skill channels belong to the Spark coordinator's `docs/COMMUNICATION.md`; the box keeps a greyed "whisper" chip as their place, with nothing behind it.
- F tapped on a peaceful person talks to them (the box in their window); held, it lists every act toward them, starting with Talk and Their window. A tap on them does the same as before (talk-1's rule, until sheathe and draw in step 4).
- **A window per person,** keyed by character id: how I name them and how they look, when I first saw them, the acts toward them (Give ›, Trade…, Wave G, Look over V, Introduce yourself), our conversation (my `said` lines to them and their `speech` lines I heard, marked "to you"), and the box. It opens by talking to them, from the list of acts, or from Log › People. "Introduce yourself" puts "I'm <name>." in the box, editable; whether they learn it is the rules' affair (`perception::introduce`).
- **Log and people** (L): Heard (every line heard and said this session), People (everyone met, most recent first, "here now" when perceived; a click opens their window) and Events (act outcomes, records, no answers, introductions). Its box speaks to everyone near (`to = 0`).
- **Names only from the rules.** A name shows only where the projection's `name` is set (`seen_characters`). A stranger is named by looks: the projection's label ("a stranger", "a child", "an old stranger") with the colour of their clothes as this client draws them (`live::recipe_for`: seeded by the land and their id, in the projection's folk and dress), "a child in red"; a second colour when two read alike ("a stranger in green and dark grey"). No role and no place. Nameplates, bubbles, the log, the box, the target frame and the lists all use it (`Looks::of`).
- **Waiting on the authority, isolated in `heard.rs`:** `heard_by` on the speaker's `said` row (who heard my line, among the people I could see) and an `introduced` row ("They told you their name"). Until they exist, nothing shows under my line and no window says how a name was learned. `introduced` is read by its kind, so it shows as soon as the authority writes it; `heard_by` needs the regenerated binding and one function. A `silence` row already shows under my line: "… did not hear you: out of earshot".

**Items on people** (`ui/pack.rs`, `ui/verbs.rs`, `verbs.rs`):
- The pack window: one cell per item with its count, and carried over the rules' `carry_limit`. A click on an item lists what I can do with it myself, beside the cell (the rules' acts with that item).
- Hold the click on an item and slide it onto a person in the world (the one hovered, else the nearest head within 70 px) or onto their window: a ghost of the item says "Give berries to a stranger in orange", and letting go sends the rules' choice toward them with that item and nothing asked back (today `give`), checked by the rules' own `_check` as the list does.
- **The list of acts** (hold F, C, an item): beside its target's head or its pack cell, in the D frame; a skill with many items (Give ›, Offer ›) opens its items beside it ("from your pack", with counts). Their window's Give › lists the same.

**Settings** (wide, from Menu): Play holds the control scheme (facing where you walk, or the cursor; F3 too), the edge of sight (not seen now, limited view, fade; F2 too), the weapon drawing itself (used from step 4), and key hints and first-time tips with "Show tips again". Controls (step 5) holds the bindings. Everything is saved at once to a small local file, a per-viewer convenience: `LIVING_GAME_SETTINGS`, else `~/.config/slop-art-online/game.json`; F2 and F3 save there too, and `LIVING_GAME_CONTROL` and `LIVING_SIGHT_EDGE` still override at start.

**Keys as built at the first merge** (all through `keys.rs`, rebindable in step 5): WASD move, Shift held runs (and still dodges until step 4), Space jumps; F acts (held: more acts), Enter talks, Tab changes whom; G wave, B nod, V look over; I pack, L log and people, K skills and know-how, C acts on yourself; Esc as above; ⌥ held glances with the camera; F1 developer panels, F2 edge of sight, F3 control scheme. The skill bar keys are talk-1's until step 4 (LMB strike, RMB bow shot, Q fire bolt, E block, R heal).

**Fixed from talk-1:**
- Health read "111 / 110" (here "110 / 109"). The authority's row was hp = max_hp = 109.48 (owner SQL on `verify-ui-a`; no row of the 311 in that world exceeds its max): the client rounded hp up and max to nearest. Both now round alike (`ui::hp_text`).
- The missing glyph was "▸" (U+25B8) in the old F hint ("Mercy ▸"); neither Nunito nor Marcellus has it, nor "→" (the act feedback's "teach medicine → person"). "›" was fine in both. Text from the rules goes through `wood::readable`, which maps them to "›". ✕, ▾ and ⌥ are drawn as glyphs.
- The target frame's label is capitalised.

**Frame cost** (`LIVING_GAME_PERF=ui` times the UI's own work: its input, the live source and widgets, and Bevy's UI layout of every node; 10-s windows). The 90f6fac1 client got the same timing (a worktree with only that patch). Both ran headless and uncapped on `verify-ui-b`, interleaved, on a laptop where other agents' builds kept the load average at 12–21. Whole-frame comparisons on that machine were swamped by the load: repeats of one binary differed sevenfold. Taking each run's best 10-s window, in µs per frame:

| State | 90f6fac1 | ui-1 |
| --- | --- | --- |
| Nothing open | 984–1,981 (514 UI nodes) | 1,084–1,777 (639 nodes) |
| Two panels or windows open | 1,123–2,070 | 1,421–2,018; one run 4,198 (992 nodes) |
| Settings › Controls open | – | 2,935 (930 nodes) |

After the themes and density pass (Clear against the play-tested `92e667c5`, interleaved, load average 26–29): nothing open 1.69–2.75 ms against 1.85–2.30; a person window and the pack open 2.3–2.4 ms against 3.4–3.6. Unchanged or lower, within the noise. No regression shows with nothing open. With two windows open it may cost about 0.3 ms more, within the noise; Settings is the heaviest, and only while it is open. Hit-testing on the game's cursor adds about 60–100 µs to input (10–30 before). Per-frame work was trimmed on the way: controls repaint only when lit or hovered changes, labels by looks refresh four times a second, and the scripts' tag map is built only in scripted runs. Evidence: `.local/living/verify/ui-b/ui/ab*`, `uiperf-*` and `baseperf-*` (client logs, `ui perf:` lines).

**Look direction** (`controls::look`): the client's look goes through one function, toward the authority's `human_face(dx, dy)` (being built on dev-box, fov-1: rate-limited, changes under about 10° write nothing, and `human_face(0, 0)` releases the look). It is a no-op until the reducer is on main and the bindings are regenerated. Facing the cursor it is given the cursor's direction; facing where you walk, none. Settings › Play keeps a place for a read-only "facing sight" line (on or off, with the field's focal, side, side share, near and margin), not built yet.

**The live script** gained the steps `verify-ui` drives: `click:@TAG` (tagged nodes, `ui/hit.rs` `Tag`), `slide:A>B[:SECS]`, `scroll:PX`, `dodge:W|A|S|D`, `dump:NAME` (the UI's state as JSON), and `key:` takes any key by its `KeyCode` name.

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
