//! Characters from recipes: distinct people of different sizes who share one skeleton (VRoid's
//! `J_Bip_*`) and one animation set, with spring bones for hair, skirts and sleeves.
//!
//! **Recipes** (`assets/characters/recipes.json`): a base VRoid file, a height in metres,
//! proportions, colours and an outfit (one piece per slot, [`outfit`]). [`Recipe::random_in`]
//! draws a recipe for a folk (`adult`, `giant`, `small`) in a style from the file's ranges,
//! palettes and style presets; [`Recipe::for_height_in`] picks the folk by height.
//! [`spawn`] puts one in the world; callers add their own markers (`EnvPart`, `Occluder`).
//!
//! **Styles** are culture presets (`styles` in the file): the pieces each slot may hold and how
//! likely, and palettes that replace the shared ones. `fantasy` is the bases' own clothes;
//! `steampunk` and `cyberpunk` add their pieces. A random recipe's body doesn't depend on its
//! style (the same seed is the same person, dressed differently). Callers choose the style from
//! context: `LIVING_GAME_CROWD=N[:seed][:style]`, an island settlement's `style`, a look-dev
//! environment's id ([`place_style`]).
//!
//! **Proportions** are scales on bones that keep clips working. Clips key rotations and the
//! hips' translation, so:
//! - lengths and girths (legs, arms, torso, neck, shoulders, hips, build) scale a bone's own
//!   vertices through a helper joint that the skins use in its place, without passing the scale
//!   to its children (no shear when they rotate); the children's offsets move with the length;
//! - head, hands and feet scale uniformly with everything below them;
//! - the hips' translation (rest and animated) scales with the leg chain, so feet stay on the
//!   ground;
//! - the whole character is then scaled to its height. `Character::stride` tells playback how
//!   much longer this character's steps are than the 1.75 m default's.
//!
//! **Colours** recolour textured materials per instance in the toon shader (`recolor` in
//! `toon.wesl`): the hue moves and saturation and value are remapped so that the material's
//! mean texture colour becomes the recipe's colour, keeping the texture's detail. Grey textures
//! are tinted instead. Characters share their base's materials, which hold the mean colour; each
//! mesh's `MeshTag` holds its recipe colour, so crowds batch instead of drawing every character
//! with materials of its own. Groups go by VRoid's material names: `_HAIR` (and brows), `_SKIN`,
//! `EyeIris`, and `_CLOTH` as `Tops`, `Bottoms`, `Shoes` and anything else as the accent.
//!
//! **Spring bones** follow VRM 0.x (`extensions.VRM.secondaryAnimation`, UniVRM's
//! `VRMSpringBoneLogic`): every chain below a group's bones is a Verlet tail pulled back to its
//! animated rest direction by stiffness, damped by drag, kept at its length and pushed out of the
//! group's collider spheres. It runs after the animation pose and transform propagation, at a
//! fixed 60 Hz (at most three steps a frame, so it stays stable at low and variable frame rates),
//! and writes the bones' local and global transforms. Distances and forces scale with the
//! character. Level of detail: characters beyond `LIVING_GAME_SPRING_NEAR` metres (default 40,
//! scaled by height) or past the nearest `LIVING_GAME_SPRING_BUDGET` (default 48) rest rigid;
//! `LIVING_GAME_SPRINGS=0` turns the simulation off. Every few seconds it logs its cost.
//!
//! `LIVING_GAME_PERF=frames` logs frame times every 2 s outside the island (whose own
//! `island perf` line does it), with the number of characters and outfit meshes.

pub mod compose;
pub mod identity;
pub mod outfit;

use crate::lookdev::{Converted, Fitted, Model};
use crate::style::Toon;
use bevy::mesh::skinning::SkinnedMesh;
use bevy::prelude::*;
use bevy::world_serialization::WorldAssetRoot;
use serde::Deserialize;
use std::collections::{BTreeMap, HashMap};
use std::f32::consts::PI;
use std::sync::{Arc, Mutex, OnceLock};

/// The recipe file, under the asset folder.
pub const FILE: &str = "characters/recipes.json";

/// Multipliers on the base's own proportions (1 = unchanged).
#[derive(Deserialize, Clone, Debug, PartialEq)]
#[serde(default)]
pub struct Proportions {
    pub legs: f32,
    pub arms: f32,
    pub torso: f32,
    pub neck: f32,
    pub head: f32,
    pub shoulders: f32,
    pub hips: f32,
    /// Girth of limbs and torso.
    pub build: f32,
    pub hands: f32,
    pub feet: f32,
}

impl Default for Proportions {
    fn default() -> Self {
        Self { legs: 1.0, arms: 1.0, torso: 1.0, neck: 1.0, head: 1.0, shoulders: 1.0, hips: 1.0, build: 1.0, hands: 1.0, feet: 1.0 }
    }
}

/// Colours as sRGB hex (`#rrggbb`); a missing colour keeps the base's texture.
#[derive(Deserialize, Clone, Debug, Default, PartialEq)]
#[serde(default)]
pub struct Colors {
    pub hair: Option<String>,
    pub eyes: Option<String>,
    pub skin: Option<String>,
    pub top: Option<String>,
    pub bottom: Option<String>,
    pub shoes: Option<String>,
    pub accent: Option<String>,
    /// A composed person's beard and stubble (an overlay's `…Overlay_00_HAIR`); the hair's
    /// without one.
    pub beard: Option<String>,
    /// A greying person's hair before and after (the line's `grey` mixes them lock by lock by
    /// the hair file's `_GREY`, `compose.rs`); `hair` is the one tint where they are not used.
    pub hair_natural: Option<String>,
    pub hair_silver: Option<String>,
    /// Outfit pieces' colours by slot (a missing one keeps the piece's own).
    pub outfit: BTreeMap<String, String>,
}

#[derive(Deserialize, Clone, Debug, PartialEq)]
pub struct Recipe {
    pub name: String,
    /// A VRoid GLB under the asset folder; its animated copy (`anim/`) is used when there is one.
    pub base: String,
    /// Metres, sole to the top of the head (hair included).
    pub height: f32,
    #[serde(default)]
    pub proportions: Proportions,
    #[serde(default)]
    pub colors: Colors,
    /// Outfit pieces by slot (`outfits.json` names: `"head": "top_hat"`).
    #[serde(default)]
    pub outfit: BTreeMap<String, String>,
    /// Identity values (-1 to 1 by name) for a type's identity bones (`identity.rs`): set once
    /// in `shape`. A file whose bones already carry them (`gen_person.sh`'s people) needs none.
    #[serde(default)]
    pub identity: BTreeMap<String, f32>,
    /// The person as shared files compose it (`compose.rs`): a type, style files, colours and
    /// the line's own numbers. It replaces `base` and the numbers above unless
    /// `LIVING_GAME_COMPOSE=0`, which ignores it.
    #[serde(default)]
    pub person: Option<compose::Person>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct Palettes {
    hair: Vec<String>,
    skin: Vec<String>,
    eyes: Vec<String>,
    outfit: Vec<String>,
}

/// A culture preset for random recipes.
#[derive(Deserialize, Default)]
#[serde(default)]
struct Preset {
    /// Palettes that replace the shared ones (an empty list keeps the shared one).
    palettes: Palettes,
    /// Slot → piece → chance of wearing it (a slot's chances add up to at most 1).
    pieces: BTreeMap<String, BTreeMap<String, f32>>,
    /// Slot → colours for its piece (default: the `outfit` palette).
    slot_palettes: BTreeMap<String, Vec<String>>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct Book {
    bases: Vec<String>,
    recipes: Vec<Recipe>,
    /// Folk → proportion (and `height`) → [min, max].
    folks: HashMap<String, HashMap<String, [f32; 2]>>,
    palettes: Palettes,
    styles: BTreeMap<String, Preset>,
    /// Pieces that hide the base clothes they cover.
    hides: Vec<String>,
    /// Recipes by name that a look-dev crowd (`LIVING_GAME_CROWD`) is made of, in its spawn
    /// order, in place of random ones: a town's people as they are (`crowd.py`).
    crowd: Vec<String>,
}

/// The style random recipes take when none is given or the given one is unknown.
pub const DEFAULT_STYLE: &str = "fantasy";

fn book() -> &'static Book {
    static BOOK: OnceLock<Book> = OnceLock::new();
    BOOK.get_or_init(|| {
        let path = std::path::Path::new(&crate::lookdev::asset_root()).join(FILE);
        match std::fs::read_to_string(&path).map_err(|e| e.to_string()).and_then(|s| serde_json::from_str::<Book>(&s).map_err(|e| e.to_string())) {
            Ok(b) => b,
            Err(e) => {
                warn!("characters: {}: {e}", path.display());
                Book::default()
            }
        }
    })
}

/// Whether any base character file is present (they are git-ignored downloads).
pub fn available() -> bool {
    let root = std::path::Path::new(&crate::lookdev::asset_root()).to_path_buf();
    book().bases.iter().any(|b| root.join(b).exists())
}

/// A small seeded generator (SplitMix64).
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    fn f(&mut self) -> f32 {
        (self.next() >> 40) as f32 / (1u64 << 24) as f32
    }
    fn pick<'a>(&mut self, list: &'a [String]) -> Option<&'a String> {
        (!list.is_empty()).then(|| &list[(self.next() % list.len() as u64) as usize])
    }
}

impl Recipe {
    /// A recipe from the file by name.
    pub fn named(name: &str) -> Option<Recipe> {
        book().recipes.iter().find(|r| r.name == name).cloned()
    }

    /// The base's own look at 1.75 m: the file's recipe for that base with no changes, else a
    /// plain one.
    /// Recipes that between them wear every outfit piece made for every base, once each (the
    /// first load draws them under its cover, so their pipelines exist before anyone is seen in
    /// them: `loading.rs`). Pieces of one slot go to different recipes.
    pub fn every_piece() -> Vec<Recipe> {
        let mut out = Vec::new();
        for base in &book().bases {
            let stem = std::path::Path::new(base).file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
            out.push(Recipe::default_for(base));
            let mut by_slot: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
            for p in outfit::all().iter().filter(|p| p.base == stem) {
                by_slot.entry(p.slot.as_str()).or_default().push(p.piece.as_str());
            }
            let n = by_slot.values().map(|v| v.len()).max().unwrap_or(0);
            for i in 0..n {
                let mut r = Recipe::default_for(base);
                r.outfit = by_slot.iter().filter_map(|(slot, ps)| ps.get(i).map(|p| (slot.to_string(), p.to_string()))).collect();
                out.push(r);
            }
        }
        out
    }

    pub fn default_for(base: &str) -> Recipe {
        let plain = Recipe { name: String::new(), base: base.to_string(), height: 1.75, proportions: Proportions::default(), colors: Colors::default(), outfit: BTreeMap::new(), identity: BTreeMap::new(), person: None };
        book().recipes.iter().find(|r| r.base == base && r.proportions == plain.proportions && r.colors == plain.colors && r.outfit.is_empty()).cloned().unwrap_or_else(|| Recipe {
            name: std::path::Path::new(base).file_stem().unwrap_or_default().to_string_lossy().to_string(),
            ..plain
        })
    }

    /// A seeded random recipe for a folk (`adult`, `giant`, `small`) in the default style.
    pub fn random(seed: u64, folk: &str) -> Recipe {
        Recipe::random_in(seed, folk, DEFAULT_STYLE)
    }

    /// A seeded random recipe for a folk (`adult`, `giant`, `small`) from the file's ranges, dressed
    /// in a style preset (unknown styles fall back to [`DEFAULT_STYLE`]).
    pub fn random_in(seed: u64, folk: &str, style: &str) -> Recipe {
        let b = book();
        let (style, preset) = b.styles.get_key_value(style).or_else(|| b.styles.get_key_value(DEFAULT_STYLE)).map_or((DEFAULT_STYLE, None), |(k, p)| (k.as_str(), Some(p)));
        let mut r = Rng(seed.wrapping_mul(0x2545_F491_4F6C_DD1D) ^ folk.bytes().fold(0u64, |h, c| h.wrapping_mul(131).wrapping_add(c as u64)));
        let ranges = b.folks.get(folk).or_else(|| b.folks.get("adult"));
        // Each value at `t` in 0..1 of its range.
        let at = |k: &str, t: f32| ranges.and_then(|m| m.get(k)).map_or(1.0, |[lo, hi]| lo + (hi - lo) * t.clamp(0.0, 1.0));
        // Correlated draws: heavier builds have broader shoulders and hips; taller ones longer legs.
        let (tall, heavy) = (r.f(), r.f());
        let mix = |r: &mut Rng, base: f32, w: f32| base * w + r.f() * (1.0 - w);
        let proportions = Proportions {
            legs: at("legs", mix(&mut r, tall, 0.5)),
            arms: at("arms", r.f()),
            torso: at("torso", r.f()),
            neck: at("neck", r.f()),
            head: at("head", mix(&mut r, 1.0 - tall, 0.4)),
            shoulders: at("shoulders", mix(&mut r, heavy, 0.6)),
            hips: at("hips", mix(&mut r, heavy, 0.5)),
            build: at("build", heavy),
            hands: at("hands", mix(&mut r, heavy, 0.5)),
            feet: at("feet", r.f()),
        };
        // The preset's palette where it has one, else the shared one.
        let pal = |f: fn(&Palettes) -> &Vec<String>| preset.map(|p| f(&p.palettes)).filter(|l| !l.is_empty()).unwrap_or_else(|| f(&b.palettes));
        let outfit_pal = pal(|p| &p.outfit);
        let outfit = |r: &mut Rng| r.pick(outfit_pal).cloned();
        let mut colors = Colors {
            hair: r.pick(pal(|p| &p.hair)).cloned(),
            skin: r.pick(pal(|p| &p.skin)).cloned(),
            eyes: r.pick(pal(|p| &p.eyes)).cloned(),
            top: outfit(&mut r),
            bottom: outfit(&mut r),
            shoes: outfit(&mut r),
            accent: outfit(&mut r),
            beard: None,
            hair_natural: None,
            hair_silver: None,
            outfit: BTreeMap::new(),
        };
        let base = r.pick(&b.bases).cloned().unwrap_or_else(|| "lookdev/vroid-Vivi.glb".into());
        // Pieces come last, so the body and its own clothes' colours don't depend on the style.
        let mut pieces = BTreeMap::new();
        for (slot, choices) in preset.map(|p| &p.pieces).into_iter().flatten() {
            let u = r.f();
            let mut acc = 0.0;
            if let Some(piece) = choices.iter().find_map(|(piece, chance)| {
                acc += chance;
                (u < acc).then_some(piece)
            }) {
                let colours = preset.and_then(|p| p.slot_palettes.get(slot)).filter(|l| !l.is_empty()).unwrap_or(outfit_pal);
                if let Some(c) = r.pick(colours) {
                    colors.outfit.insert(slot.clone(), c.clone());
                }
                pieces.insert(slot.clone(), piece.clone());
            }
        }
        let name = if style == DEFAULT_STYLE { format!("{folk}-{seed}") } else { format!("{folk}:{seed}:{style}") };
        Recipe { name, base, height: at("height", tall), proportions, colors, outfit: pieces, identity: BTreeMap::new(), person: None }
    }

    /// A random recipe of exactly this height, its folk chosen by it, in a style.
    pub fn for_height_in(seed: u64, height: f32, style: &str) -> Recipe {
        let folk = if height < 1.1 {
            "small"
        } else if height > 3.0 {
            "giant"
        } else {
            "adult"
        };
        Recipe { height, ..Recipe::random_in(seed, folk, style) }
    }

    /// `name` from the file, or `<folk>:<seed>[:<style>]` / `<folk>-<seed>` for a random one.
    pub fn parse(token: &str) -> Option<Recipe> {
        Recipe::named(token).or_else(|| {
            let mut parts = token.split(':');
            let (folk, seed, style) = match (parts.next(), parts.next(), parts.next()) {
                (Some(f), Some(s), style) => (f, s, style.unwrap_or(DEFAULT_STYLE)),
                _ => {
                    let (f, s) = token.rsplit_once('-')?;
                    (f, s, DEFAULT_STYLE)
                }
            };
            Some(Recipe::random_in(seed.parse().ok()?, folk, style))
        })
    }
}

/// The style preset for a place by its id (`steampunk_city` → `steampunk`), else the default.
pub fn place_style(place: &str) -> &'static str {
    book().styles.keys().find(|s| place.starts_with(s.as_str())).map_or(DEFAULT_STYLE, |s| s.as_str())
}

/// `LIVING_GAME_CROWD=N[:seed][:style]`: how many, the seed (default 1) and the style, if given.
pub fn crowd_from_env() -> Option<(usize, u64, Option<String>)> {
    let v = std::env::var("LIVING_GAME_CROWD").ok()?;
    let mut parts = v.split(':');
    let n = parts.next()?.trim().parse::<usize>().ok()?;
    let (mut seed, mut style) = (1, None);
    for p in parts {
        match p.trim().parse::<u64>() {
            Ok(s) => seed = s,
            Err(_) => style = Some(p.trim().to_string()),
        }
    }
    Some((n, seed, style))
}

/// The `LIVING_GAME_CROWD` crowd in a look-dev environment, at `centre` on its ground, in the
/// crowd's style or else the place's. Empty without the variable.
pub fn env_crowd(commands: &mut Commands, assets: &AssetServer, place: &str, centre: Vec3, ground: &dyn Fn(f32, f32) -> f32) -> Vec<Entity> {
    let Some((n, seed, style)) = crowd_from_env() else { return vec![] };
    let style = style.unwrap_or_else(|| place_style(place).to_string());
    spawn_crowd(commands, assets, n, seed, &style, centre, ground)
}

/// A character built from a recipe (on the model root, beside [`Model`]).
#[derive(Component)]
pub struct Character {
    pub recipe: Recipe,
    /// This character's stride against its clip file's figure at 1.75 m (its own base, or the
    /// shared clip file's figure for generated people, `shape`): locomotion clips play at
    /// `speed / (clip speed × stride)` so feet don't slide.
    pub stride: f32,
}

/// Spawn a character at `at` (its sole on `at.y`), facing `yaw` (0 = +Z, the camera's default
/// side; turning counter-clockwise seen from above). Callers add their own markers.
pub fn spawn(commands: &mut Commands, assets: &AssetServer, recipe: &Recipe, at: Vec3, yaw: f32) -> Entity {
    // A person line composes the person from shared files when the switch is on (compose.rs).
    let (recipe, styled) = compose::prepare(recipe, assets);
    let file = crate::lookdev::animated(&recipe.base);
    // VRM 0.x models face −Z.
    let model = Model { vrm: true, file: file.clone(), height: recipe.height, ground_y: at.y, glow: None };
    let root = kept(assets, &file);
    let mut e = commands.spawn((
        model,
        Character { recipe, stride: 1.0 },
        crate::lookdev::CastsShadow::default(),
        SceneOf(root.clone()),
        FileHandle(root),
        Transform::from_translation(at).with_rotation(Quat::from_rotation_y(yaw + PI)),
        Visibility::Hidden,
    ));
    if let Some(s) = styled {
        e.insert(s);
    }
    e.id()
}

/// Holds a character file's root glTF from the start. A scene loaded by its label alone lets the
/// root go once loaded; the clips' later load of the root (`lookdev::clips`) then read the whole
/// file again, which replaced its scene asset and rebuilt every instance about 20 frames in, with
/// new bone entities: proportions, outfits and springs set up on the old bones were lost.
/// Loading the label and the root together read it twice as well ([`SceneOf`]).
///
/// The root is also kept for the rest of the session ([`kept`]): when the last character of a
/// base despawned (leaving a town drops its people), the next one to spawn read the whole file
/// again and rebuilt every live instance of that base the same way, in a 100–160 ms frame.
#[derive(Component)]
pub struct FileHandle(#[allow(dead_code)] Handle<bevy::gltf::Gltf>);

impl FileHandle {
    /// A file's root glTF, held for the session ([`kept`]): for any model that plays the
    /// file's clips (characters, the wolf).
    pub fn kept(assets: &AssetServer, file: &str) -> Self {
        Self(kept(assets, file))
    }
}

/// A character file's root glTF, loaded once and held for the session (there are only a few
/// bases).
pub fn kept(assets: &AssetServer, file: &str) -> Handle<bevy::gltf::Gltf> {
    static KEPT: OnceLock<Mutex<HashMap<String, Handle<bevy::gltf::Gltf>>>> = OnceLock::new();
    KEPT.get_or_init(Default::default).lock().unwrap().entry(file.to_string()).or_insert_with(|| assets.load(file.to_string())).clone()
}

/// A model whose scene spawns from its file's root glTF once that is loaded ([`place_scenes`]),
/// in place of a `WorldAssetRoot` of the file's `#Scene0` label from the start.
///
/// Bevy 0.20 loads a label by force-loading its root (`HandleLoadingMode::Force` in
/// `AssetServer::load_internal`) even while a load of the root itself is under way
/// (bevy#10549). A character asked for both in the same frame (its scene's label and the root
/// [`kept`] for its clips), so a file was read twice. The second read replaced the scene asset
/// (`AssetEvent::Modified`), and Bevy respawned every instance already made from the first, on
/// new bone entities: 0 to 6 of 64 people a run lost their proportions (crowd-1). Asking for the
/// root alone reads it once, and the scene is the root's own `scenes[0]`.
#[derive(Component)]
pub struct SceneOf(pub Handle<bevy::gltf::Gltf>);

/// Give each [`SceneOf`] model its scene once its file is in (and, for a composed person, every
/// style file it wears, so its scene and its styles come in together).
pub fn place_scenes(mut commands: Commands, gltfs: Res<Assets<bevy::gltf::Gltf>>, assets: Res<AssetServer>, q: Query<(Entity, &SceneOf, Option<&compose::Styled>), Without<WorldAssetRoot>>) {
    for (e, s, styled) in &q {
        if styled.is_some_and(|st| !st.loaded(&assets)) {
            continue;
        }
        if let Some(g) = gltfs.get(&s.0) {
            match g.scenes.first() {
                Some(scene) => {
                    commands.entity(e).insert(WorldAssetRoot(scene.clone()));
                }
                None => {
                    warn!("characters: {:?} has no scene", assets.get_path(&s.0));
                    commands.entity(e).remove::<SceneOf>();
                }
            }
        } else if let Some(bevy::asset::LoadState::Failed(err)) = assets.get_load_state(&s.0) {
            warn!("characters: {:?} did not load: {err}", assets.get_path(&s.0));
            commands.entity(e).remove::<SceneOf>();
        }
    }
}

/// How many times a character's scene has been spawned.
#[derive(Component)]
pub struct Spawns(pub u32);

/// A character's scene was spawned again (on new bone entities): what was built on the old ones
/// was let go ([`forget_scene`]) and is built again by the usual systems — fitting, proportions
/// (`shape`), the rig, springs, outfit, the far model's lists, the clips and the look's bones.
/// Anything else that sets a character's bones once must listen to this: a type's identity bones
/// (docs/CHARACTERS.md, "The client format") belong in `shape`, which runs again.
#[derive(Message, Clone, Copy, Debug)]
pub struct Rebuilt {
    // Nothing reads it yet: step 3's identity bones will.
    #[allow(dead_code)]
    pub entity: Entity,
}

/// Count each character's scene spawns; on a second one, let go of what was built on the old
/// scene, so it is built again on the new one.
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn on_ready(
    ev: On<bevy::world_serialization::WorldInstanceReady>,
    mut commands: Commands,
    mut chars: Query<(&Character, Option<&Model>, Option<&mut Spawns>)>,
    children: Query<&Children>,
    names: Query<&Name>,
    mut transforms: Query<&mut Transform, Without<Character>>,
    pieces: Query<(), Or<(With<outfit::Piece>, With<compose::Worn>)>>,
    mut rebuilt: MessageWriter<Rebuilt>,
) {
    let e = ev.entity;
    let Ok((ch, model, spawns)) = chars.get_mut(e) else { return };
    // Identity first, on every spawn of the scene: before its bounds are first taken (skinned
    // bounds follow the joints, and `fit` sizes the person by them) and before anything is
    // built on its bones.
    if let Some(model) = model.filter(|_| !ch.recipe.identity.is_empty()) {
        set_identity(e, ch, model, &children, &names, &mut transforms);
    }
    let Some(mut n) = spawns else {
        commands.entity(e).insert(Spawns(1));
        return;
    };
    n.0 += 1;
    if crate::perf::has("nokeep") {
        return;
    }
    info!("characters: {}'s scene was spawned again ({} times); fitting and shaping it again", ch.recipe.name, n.0);
    forget_scene(&mut commands, e, children.get(e).into_iter().flatten().copied().filter(|c| pieces.contains(*c)));
    rebuilt.write(Rebuilt { entity: e });
}

/// Move a character's identity bones by its recipe's values (`identity.rs`), from the rest its
/// file records (compose.py's `rest_translation`, else the node's own). No clip keys them, so
/// this is done once a scene. They sit inside the head, so the recipe's `head` (the head bone's
/// own scale, `shape`) carries them, and they need no helper joints: their children are meant to
/// ride their scale.
fn set_identity(e: Entity, ch: &Character, model: &Model, children: &Query<&Children>, names: &Query<&Name>, transforms: &mut Query<&mut Transform, Without<Character>>) {
    let info = file_info(&model.file);
    let by_name: HashMap<&str, Entity> = children.iter_descendants(e).filter_map(|d| names.get(d).ok().map(|n| (n.as_str(), d))).collect();
    let mut moved = 0;
    for (name, change) in identity::transforms(identity::rig(), &ch.recipe.identity) {
        let Some(&bone) = by_name.get(name.as_str()) else { continue };
        let rest = info.rest_extras.get(&name).or_else(|| info.rest.get(&name)).copied().unwrap_or(Vec3::ZERO);
        if let Ok(mut tf) = transforms.get_mut(bone) {
            *tf = change.transform(rest);
            moved += 1;
            debug!("identity: {} {name} t {:?} r {:?} s {:?}", ch.recipe.name, tf.translation.to_array(), tf.rotation.to_array(), tf.scale.to_array());
        }
    }
    debug!("characters: {}: {} identity values on {moved} bones", ch.recipe.name, ch.recipe.identity.len());
}

/// `LIVING_GAME_PERF=rebuild=S` (perf.rs): S seconds after the first load's cover lifts, spawn
/// every character's scene again, through Bevy's own respawn of a changed `WorldAssetRoot`.
fn force_rebuild(loading: Option<Res<crate::loading::Loading>>, time: Res<Time>, mut roots: Query<(&Character, &mut WorldAssetRoot)>, mut at: Local<Option<f32>>, mut done: Local<bool>) {
    let Some(after) = crate::perf::value("rebuild") else { return };
    if *done || !crate::loading::Loading::clear(loading.as_deref()) {
        return;
    }
    let now = time.elapsed_secs();
    let at = *at.get_or_insert(now + after);
    if now < at {
        return;
    }
    *done = true;
    let mut n = 0;
    for (_, mut root) in &mut roots {
        root.set_changed();
        n += 1;
    }
    info!("characters: spawning {n} characters' scenes again (LIVING_GAME_PERF=rebuild)");
}

/// Let go of what was built on a character's old scene (it is built again on the new one), and
/// hide it until it is fitted again; its outfit pieces and composed styles (skinned to the old
/// bones, [`compose::Worn`]) go, and `compose::on_ready` puts the styles on the new one.
pub fn forget_scene(commands: &mut Commands, e: Entity, pieces: impl IntoIterator<Item = Entity>) {
    commands
        .entity(e)
        .remove::<(Fitted, Shaped, Springs, outfit::Dressed, crate::lookdev::Rig, crate::lookdev::Lod, crate::anim::Anim, crate::anim::Bound, crate::twist::Spine, crate::ik::Legs)>()
        .insert((crate::lookdev::CastsShadow::default(), Visibility::Hidden));
    for p in pieces {
        commands.entity(p).despawn();
    }
}

/// Warn if a shaped character's skeleton is replaced anyway and [`on_ready`] did not let go of
/// it: its proportions, outfit and springs stay on the old bones.
fn rebuilt(chars: Query<(Entity, &Character, &Shaped)>, alive: Query<()>, mut seen: Local<std::collections::HashSet<Entity>>) {
    for (e, c, sh) in &chars {
        if sh.hips.is_some_and(|h| alive.get(h).is_err()) && seen.insert(e) {
            warn!("characters: {}'s scene was rebuilt and not shaped again; its proportions and outfit are lost", c.recipe.name);
        }
    }
}

/// A crowd of `n` seeded random characters in a style, in rows north of `centre`, facing south:
/// small folk in front, then adults, giants behind, standing on `ground(x, z)`. Returns their
/// roots.
pub fn spawn_crowd(commands: &mut Commands, assets: &AssetServer, n: usize, seed: u64, style: &str, centre: Vec3, ground: &dyn Fn(f32, f32) -> f32) -> Vec<Entity> {
    let giants = (n / 7).max(usize::from(n >= 3));
    let small = (n / 5).max(usize::from(n >= 2));
    let adults = n.saturating_sub(giants + small);
    let mut out = Vec::new();
    let mut z = centre.z;
    for (folk, count, gap, depth, per_row) in [("small", small, 1.1, 1.6, 10), ("adult", adults, 1.5, 2.2, 8), ("giant", giants, 4.2, 5.0, 4)] {
        z -= depth;
        for k in 0..count {
            let (row, col) = (k / per_row, k % per_row);
            let in_row = (count - row * per_row).min(per_row);
            let x = centre.x + (col as f32 - (in_row as f32 - 1.0) / 2.0) * gap + if row % 2 == 1 { gap * 0.5 } else { 0.0 };
            let s = seed.wrapping_mul(1000).wrapping_add(out.len() as u64);
            // A crowd the recipe book names (a town's people), else seeded random ones.
            let named = &book().crowd;
            let recipe = (!named.is_empty()).then(|| Recipe::named(&named[out.len() % named.len()])).flatten().unwrap_or_else(|| Recipe::random_in(s, folk, style));
            let yaw = ((s % 7) as f32 - 3.0) * 0.08;
            let z = z - row as f32 * depth;
            out.push(spawn(commands, assets, &recipe, Vec3::new(x, ground(x, z), z), yaw));
        }
        z -= (count.saturating_sub(1) / per_row) as f32 * depth;
    }
    out
}

pub struct CharactersPlugin;

impl Plugin for CharactersPlugin {
    fn build(&self, app: &mut App) {
        app.add_message::<Rebuilt>()
            .add_observer(on_ready)
            .add_observer(compose::on_ready)
            .init_resource::<compose::Plans>()
            .init_resource::<compose::HairTints>()
            .init_resource::<Thumbs>()
            .add_systems(PreUpdate, (place_scenes, force_rebuild, thumb_pictures))
            .insert_resource(SpringSettings::from_env())
            .init_resource::<SpringClock>()
            .init_resource::<SpringStats>()
            .add_systems(Update, (shape, recolor, rig_springs, outfit::dress, rebuilt, frames))
            .add_systems(PostUpdate, (hips.after(bevy::app::AnimationSystems).before(TransformSystems::Propagate), springs.after(TransformSystems::Propagate)));
    }
}

/// What the rest of a file looks like, read once from its glTF JSON: rest translations by node
/// name and its spring bones.
struct FileInfo {
    rest: HashMap<String, Vec3>,
    /// Rest translations a file's nodes record of their own (`extras.rest_translation`, written
    /// by compose.py when it moves an identity bone): where identity values start from.
    rest_extras: HashMap<String, Vec3>,
    springs: Vec<GroupDef>,
    colliders: Vec<ColliderDef>,
}

struct GroupDef {
    stiffness: f32,
    gravity: Vec3,
    drag: f32,
    radius: f32,
    bones: Vec<String>,
    colliders: Vec<usize>,
}

struct ColliderDef {
    node: String,
    spheres: Vec<(Vec3, f32)>,
}

/// A node's rest translation in a character file (its own record of it, else its node's).
pub fn rest_of(file: &str, node: &str) -> Vec3 {
    let info = file_info(file);
    info.rest_extras.get(node).or_else(|| info.rest.get(node)).copied().unwrap_or(Vec3::ZERO)
}

fn file_info(file: &str) -> Arc<FileInfo> {
    static CACHE: OnceLock<Mutex<HashMap<String, Arc<FileInfo>>>> = OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    if let Some(i) = cache.lock().unwrap().get(file) {
        return i.clone();
    }
    let json = crate::lookdev::glb_json(file).unwrap_or_default();
    let nodes = json["nodes"].as_array().cloned().unwrap_or_default();
    let name = |i: &serde_json::Value| i.as_u64().and_then(|i| nodes.get(i as usize)).and_then(|n| n["name"].as_str()).map(String::from);
    let v3 = |v: &serde_json::Value| Vec3::new(v["x"].as_f64().unwrap_or(0.0) as f32, v["y"].as_f64().unwrap_or(0.0) as f32, v["z"].as_f64().unwrap_or(0.0) as f32);
    let rest = nodes
        .iter()
        .filter_map(|n| {
            let t = n["translation"].as_array().map_or(Vec3::ZERO, |t| Vec3::new(t[0].as_f64().unwrap_or(0.0) as f32, t[1].as_f64().unwrap_or(0.0) as f32, t[2].as_f64().unwrap_or(0.0) as f32));
            Some((n["name"].as_str()?.to_string(), t))
        })
        .collect();
    let rest_extras = nodes
        .iter()
        .filter_map(|n| {
            let t = n["extras"]["rest_translation"].as_array()?;
            Some((n["name"].as_str()?.to_string(), Vec3::new(t.first()?.as_f64()? as f32, t.get(1)?.as_f64()? as f32, t.get(2)?.as_f64()? as f32)))
        })
        .collect();
    let sec = &json["extensions"]["VRM"]["secondaryAnimation"];
    let springs = sec["boneGroups"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|g| GroupDef {
            // VRM 0.x spells it "stiffiness".
            stiffness: g["stiffiness"].as_f64().or(g["stiffness"].as_f64()).unwrap_or(1.0) as f32,
            gravity: v3(&g["gravityDir"]) * g["gravityPower"].as_f64().unwrap_or(0.0) as f32,
            drag: g["dragForce"].as_f64().unwrap_or(0.4) as f32,
            radius: g["hitRadius"].as_f64().unwrap_or(0.02) as f32,
            bones: g["bones"].as_array().into_iter().flatten().filter_map(name).collect(),
            colliders: g["colliderGroups"].as_array().into_iter().flatten().filter_map(|c| c.as_u64().map(|c| c as usize)).collect(),
        })
        .collect();
    let colliders = sec["colliderGroups"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|c| ColliderDef {
            node: name(&c["node"]).unwrap_or_default(),
            spheres: c["colliders"].as_array().into_iter().flatten().map(|s| (v3(&s["offset"]), s["radius"].as_f64().unwrap_or(0.0) as f32)).collect(),
        })
        .collect();
    let info = Arc::new(FileInfo { rest, rest_extras, springs, colliders });
    cache.lock().unwrap().insert(file.to_string(), info.clone());
    info
}

/// How a bone is scaled: its own vertices through a helper joint (not inherited), or uniformly
/// with everything below it.
#[derive(Clone, Copy, Debug)]
enum BoneScale {
    Own(Vec3),
    Uniform(f32),
}

/// The scale a recipe gives each `J_Bip_*` bone. VRoid's rest rotations are identity, so the
/// bone's local axes are the model's: legs and spine run along Y, arms along X.
fn bone_scale(name: &str, p: &Proportions) -> Option<BoneScale> {
    use BoneScale::*;
    let g = p.build;
    let lerp = |a: f32, b: f32, t: f32| a + (b - a) * t;
    let side = name.strip_prefix("J_Bip_L_").or_else(|| name.strip_prefix("J_Bip_R_"));
    // Widths across the torso; the arms' roots move out with the upper chest.
    let chest = g * p.shoulders;
    Some(match (name, side) {
        ("J_Bip_C_Hips", _) => Own(Vec3::new(g * p.hips, 1.0, g * p.hips.sqrt())),
        ("J_Bip_C_Spine", _) => Own(Vec3::new(g * lerp(1.0, p.hips, 0.5), p.torso, g)),
        ("J_Bip_C_Chest", _) => Own(Vec3::new(lerp(g, chest, 0.5), p.torso, g)),
        ("J_Bip_C_UpperChest", _) => Own(Vec3::new(chest, p.torso, g)),
        ("J_Bip_C_Neck", _) => Own(Vec3::new(g.powf(0.8), p.neck, g.powf(0.8))),
        ("J_Bip_C_Head", _) => Uniform(p.head),
        (_, Some("Shoulder")) => Own(Vec3::new(chest, g, g)),
        (_, Some("UpperArm")) => Own(Vec3::new(p.arms, g, g)),
        (_, Some("LowerArm")) => Own(Vec3::new(p.arms, g.powf(0.85), g.powf(0.85))),
        (_, Some("Hand")) => Uniform(p.hands),
        (_, Some("UpperLeg")) => Own(Vec3::new(g, p.legs, g)),
        (_, Some("LowerLeg")) => Own(Vec3::new(g.powf(0.85), p.legs, g.powf(0.85))),
        (_, Some("Foot")) => Uniform(p.feet),
        _ => return None,
    })
}

/// A shaped character: the hips bone and how its translation scales, and each bone's own scale
/// (for collider spheres).
#[derive(Component)]
pub struct Shaped {
    hips: Option<Entity>,
    hips_k: f32,
    /// The hips translation last written here (an animation's new value differs from it).
    written: Vec3,
    scales: HashMap<Entity, Vec3>,
    /// Bone → the helper joint skins use in its place (bones scaled in their own frame).
    helpers: HashMap<Entity, Entity>,
}

impl Shaped {
    /// The hips translation was written after `hips` scaled it (foot IK lowering the hips): it is
    /// final, not a fresh animated value to scale.
    pub fn wrote(&mut self, translation: Vec3) {
        self.written = translation;
    }
}

/// Apply a recipe's proportions and height once its model is loaded and measured.
#[allow(clippy::type_complexity)]
pub fn shape(
    mut commands: Commands,
    mut chars: Query<(Entity, &mut Character, &Model, &mut Transform, &mut Fitted, Option<&compose::Styled>), Without<Shaped>>,
    children: Query<&Children>,
    names: Query<&Name>,
    mut bones: Query<&mut Transform, Without<Character>>,
    mut skins: Query<&mut SkinnedMesh>,
) {
    for (e, mut ch, model, mut root, mut fit, styled) in &mut chars {
        let info = file_info(&model.file);
        let mut by_name: HashMap<&str, Entity> = HashMap::new();
        for d in children.iter_descendants(e) {
            if let Ok(n) = names.get(d) {
                by_name.insert(n.as_str(), d);
            }
        }
        let Some(&hips) = by_name.get("J_Bip_C_Hips") else {
            commands.entity(e).insert(Shaped { hips: None, hips_k: 1.0, written: Vec3::NAN, scales: HashMap::new(), helpers: HashMap::new() });
            continue;
        };
        let p = ch.recipe.proportions.clone();
        let rest = |n: &str| info.rest.get(n).copied().unwrap_or(Vec3::ZERO);
        let mut own: HashMap<String, Vec3> = HashMap::new();
        let mut scales = HashMap::new();
        let mut helpers: HashMap<Entity, Entity> = HashMap::new();
        for (name, &bone) in &by_name {
            let Some(s) = bone_scale(name, &p) else { continue };
            // The base's own proportions need nothing.
            if matches!(s, BoneScale::Own(v) if v == Vec3::ONE) || matches!(s, BoneScale::Uniform(k) if k == 1.0) {
                continue;
            }
            match s {
                BoneScale::Uniform(k) => {
                    if let Ok(mut tf) = bones.get_mut(bone) {
                        tf.scale = Vec3::splat(k);
                    }
                }
                BoneScale::Own(v) => {
                    own.insert(name.to_string(), v);
                    scales.insert(bone, v);
                    // The skins use the helper in the bone's place: its vertices scale in the
                    // bone's frame, its children don't.
                    let h = commands.spawn((Name::new("scale"), Transform::from_scale(v), ChildOf(bone))).id();
                    helpers.insert(bone, h);
                    // Children's offsets move with the bone's length and width. A composed person's
                    // belly bone stands forward of its rest (compose.rs) and keeps that, widened.
                    for c in children.get(bone).into_iter().flatten() {
                        if let (Ok(cn), Ok(mut tf)) = (names.get(*c), bones.get_mut(*c)) {
                            if cn.as_str() != "J_Bip_C_Hips" {
                                let belly = if cn.as_str() == "J_Fit_Belly" { compose::belly_offset(&ch.recipe, styled.is_some()) } else { Vec3::ZERO };
                                tf.translation = info.rest.get(cn.as_str()).map_or(tf.translation, |r| *r + belly) * v;
                            }
                        }
                    }
                }
            }
        }
        for d in children.iter_descendants(e) {
            if let Ok(mut skin) = skins.get_mut(d) {
                for j in skin.joints.iter_mut() {
                    if let Some(h) = helpers.get(j) {
                        *j = *h;
                    }
                }
            }
        }
        // Heights in model units along the rest skeleton (rest rotations are identity).
        let s = |n: &str| own.get(n).copied().unwrap_or(Vec3::ONE);
        let k0 = root.scale.x.max(1e-6);
        let lo = -fit.y_off / k0;
        let top0 = lo + fit.size.y / k0;
        let hips0 = rest("J_Bip_C_Hips");
        let leg = |side: &str| {
            let n = |b: &str| format!("J_Bip_{side}_{b}");
            let foot0 = hips0.y + rest(&n("UpperLeg")).y + rest(&n("LowerLeg")).y + rest(&n("Foot")).y;
            let drop = s("J_Bip_C_Hips").y * rest(&n("UpperLeg")).y + s(&n("UpperLeg")).y * rest(&n("LowerLeg")).y + s(&n("LowerLeg")).y * rest(&n("Foot")).y;
            (foot0 - lo, drop)
        };
        let (below, drop) = leg("L");
        let hips_y = lo + below * p.feet - drop;
        let hips_k = if hips0.y.abs() > 1e-4 { hips_y / hips0.y } else { 1.0 };
        let spine = ["J_Bip_C_Spine", "J_Bip_C_Chest", "J_Bip_C_UpperChest", "J_Bip_C_Neck", "J_Bip_C_Head"];
        let mut head = hips_y;
        let mut parent = "J_Bip_C_Hips";
        for b in spine {
            head += s(parent).y * rest(b).y;
            parent = b;
        }
        let head0 = hips0.y + spine.iter().map(|b| rest(b).y).sum::<f32>();
        let top = head + (top0 - head0) * p.head;
        let units = (top - lo).max(0.01);
        let k = ch.recipe.height / units;
        root.scale = Vec3::splat(k);
        root.translation.y = model.ground_y - lo * k;
        let size_units = fit.size / k0;
        // The measured width is the rest pose's arm span.
        fit.size = Vec3::new(size_units.x * p.arms * p.build.sqrt() * k, ch.recipe.height, size_units.z * p.build * k);
        fit.y_off = -lo * k;
        fit.center = Vec3::new(fit.center.x / k0 * k, ch.recipe.height * 0.5, fit.center.z / k0 * k);
        // Stride against the base at 1.75 m. The clips' sidecar gives metres of the figure they
        // were baked on, scaled to 1.75 m (animate.py `--height`). That is this file's figure,
        // or, for clips from a shared clip file, that file's: same skeleton, other meshes (hair
        // and clothes make it a few centimetres taller or shorter), so its height stands in.
        let clips = crate::anim::clip_file(&model.file);
        // A composed person's figure is its type's and its styles' together.
        let own = styled.map_or_else(|| crate::lookdev::figure_height(&model.file), |s| compose::figure_height(&model.file, s));
        let figure = match (clips != model.file).then(|| (crate::lookdev::figure_height(&clips), own)) {
            Some((Some(theirs), Some(ours))) if ours > 0.01 => (top0 - lo) * theirs / ours,
            _ => top0 - lo,
        };
        let base_hip = (hips0.y - lo) * 1.75 / figure.max(0.01);
        ch.stride = ((hips_y - lo) * k / base_hip.max(0.01)).max(0.05);
        debug!("characters: {} {:.2} m (×{k:.3}), hips ×{hips_k:.3}, stride {:.2}", ch.recipe.name, ch.recipe.height, ch.stride);
        commands.entity(e).insert(Shaped { hips: Some(hips), hips_k, written: Vec3::NAN, scales, helpers });
    }
}

/// Scale the hips' translation (rest or freshly animated) with the leg chain.
pub fn hips(mut chars: Query<&mut Shaped>, mut transforms: Query<&mut Transform>) {
    for mut sh in &mut chars {
        let Some(h) = sh.hips else { continue };
        let Ok(mut tf) = transforms.get_mut(h) else { continue };
        if tf.translation != sh.written {
            let t = tf.translation * sh.hips_k;
            tf.translation = t;
            sh.written = t;
        }
    }
}

/// A mesh already checked for recolouring.
#[derive(Component)]
pub struct Recolored;

/// What a VRoid material is, by name.
fn slot<'a>(material: &str, c: &'a Colors) -> Option<&'a String> {
    let m = material;
    if m.contains("Overlay") && m.contains("_HAIR") {
        c.beard.as_ref().or(c.hair.as_ref())
    } else if m.contains("_HAIR") || m.contains("FaceBrow") {
        c.hair.as_ref()
    } else if m.contains("_SKIN") {
        c.skin.as_ref()
    } else if m.contains("EyeIris") {
        c.eyes.as_ref()
    } else if m.contains("_CLOTH") {
        if m.contains("Tops") {
            c.top.as_ref()
        } else if m.contains("Bottoms") {
            c.bottom.as_ref()
        } else if m.contains("Shoes") {
            c.shoes.as_ref()
        } else {
            c.accent.as_ref()
        }
    } else {
        None
    }
}

fn hsv(c: Vec3) -> Vec3 {
    let mx = c.max_element();
    let mn = c.min_element();
    let d = mx - mn;
    let h = if d < 1e-5 {
        0.0
    } else if mx == c.x {
        ((c.y - c.z) / d).rem_euclid(6.0) / 6.0
    } else if mx == c.y {
        ((c.z - c.x) / d + 2.0) / 6.0
    } else {
        ((c.x - c.y) / d + 4.0) / 6.0
    };
    Vec3::new(h, if mx > 1e-5 { d / mx } else { 0.0 }, mx)
}

/// How much of a texture's own hue variation a recoloured material keeps.
///
/// The generator mirrors this rule: `living/tools/blender/person_params.py` `HUE_SPREAD` (this value) and
/// `SHARED_IRIS_SOURCE` (the shared iris picture's mean as [`mean_color`] takes it, over the
/// texels its mesh uses) set each person's `colors.eyes` so that the moved iris lands on their eye
/// colour. Change either here, or how a material's source colour is taken, and those must follow;
/// `living/tools/characters/eye_colours.py --check` catches a changed source.
const HUE_SPREAD: f32 = 0.4;

/// A greying person's hair tag (`toon.wesl` `recolor`): their natural colour's and their
/// silver's places on the palette, how grey they are (0 to 1 in 8 bits), bit 24 set, bit 26 the
/// palette's (bit 25 clear: never wind sway). None without the colours, their `grey`, room on
/// the palette, or a mesh and material that grey (a hair file's `_GREY`, the shared hair toon).
fn grey_tag(c: &Character, mesh: &Mesh, toon: &Toon, tints: &mut compose::HairTints, images: &mut Assets<Image>) -> Option<u32> {
    let p = c.recipe.person.as_ref().filter(|p| p.grey > 0.0)?;
    toon.extension.tints.as_ref()?;
    mesh.attribute(Mesh::ATTRIBUTE_UV_1)?;
    let byte = |hex: &Option<String>| -> Option<[u8; 3]> {
        let c = Srgba::hex(hex.as_ref()?).ok()?;
        let b = |v: f32| (v.clamp(0.0, 1.0) * 255.0).round() as u8;
        Some([b(c.red), b(c.green), b(c.blue)])
    };
    let (natural, silver) = (byte(&p.colors.hair_natural)?, byte(&p.colors.hair_silver)?);
    let n = tints.place(0, natural, images)? as u32;
    let s = tints.place(1, silver, images)? as u32;
    let g = (p.grey.clamp(0.0, 1.0) * 255.0).round() as u32;
    Some(n | s << 8 | g << 16 | 1 << 24 | 1 << 26)
}

/// A recipe colour packed for a mesh's tag: sRGB bytes, bit 24 marks it set (`toon.wesl`
/// `recolor`).
fn tag_color(c: Srgba) -> u32 {
    let b = |v: f32| (v.clamp(0.0, 1.0) * 255.0).round() as u32;
    b(c.red) | b(c.green) << 8 | b(c.blue) << 16 | 1 << 24
}

/// A material's mean colour (linear) over the texels its mesh's vertices use, read from its
/// texture's summary ([`Thumbs`]).
fn mean_color(toon: &Toon, mesh: &Mesh, thumbs: &Thumbs) -> Option<Vec3> {
    let base = toon.base.base_color.to_linear();
    let base = Vec3::new(base.red, base.green, base.blue);
    let Some(tex) = toon.base.base_color_texture.as_ref() else { return Some(vertex_mean(mesh).map_or(base, |v| v * base)) };
    let thumb = thumbs.0.get(&tex.id())?;
    let Some(bevy::mesh::VertexAttributeValues::Float32x2(uvs)) = mesh.attribute(Mesh::ATTRIBUTE_UV_0) else { return Some(base) };
    let (mut sum, mut wsum) = (Vec3::ZERO, 0.0);
    let step = (uvs.len() / 4000).max(1);
    for uv in uvs.iter().step_by(step) {
        let c = thumb.at(uv[0], uv[1]);
        sum += c.truncate();
        wsum += c.w;
    }
    (wsum > 0.0).then(|| sum / wsum * base)
}

/// A shared style material's recolour source colour (linear), for `compose.rs`: its whole
/// picture's mean (from its summary, or from its pixels while they are still on the CPU), else
/// its meshes' vertex colours by area, times its base colour. A picture is shared by files
/// whose meshes use different parts of it (every hair cut has the one strand picture, whose
/// texels a short cut uses differ from a long one's), so its whole mean is the one value they
/// agree on (docs/CHARACTERS.md, "One shading mean a class"). None while the picture is neither
/// summarised nor readable.
pub(crate) fn source_mean(base: &StandardMaterial, meshes: &[&Mesh], thumbs: &Thumbs, images: &Assets<Image>) -> Option<Vec3> {
    let b = base.base_color.to_linear();
    let b = Vec3::new(b.red, b.green, b.blue);
    let Some(tex) = base.base_color_texture.as_ref() else {
        let (mut sum, mut w) = (Vec3::ZERO, 0.0);
        for m in meshes {
            if let Some((s, a)) = vertex_sum(m) {
                sum += s;
                w += a;
            }
        }
        return Some(if w > 0.0 { sum / w * b } else { b });
    };
    let own;
    let thumb = match thumbs.0.get(&tex.id()) {
        Some(t) => t,
        None => {
            own = Thumb::of(images.get(tex)?)?;
            &own
        }
    };
    let (sum, wsum) = thumb.cells.iter().fold((Vec3::ZERO, 0.0), |(s, w), c| (s + c.truncate(), w + c.w));
    Some(if wsum > 0.0 { sum / wsum * b } else { b })
}

/// The recolour's material values for a source colour: mode 3 and `recolor_from`, as `recolor`
/// sets them from a mesh.
pub(crate) fn recolor_source(mean: Vec3) -> (Vec4, Vec4) {
    let m = hsv(mean);
    (Vec4::new(0.0, 0.0, 0.0, 3.0), Vec4::new(m.x, HUE_SPREAD, m.y, m.z))
}

/// Cells a side of a texture's summary.
const THUMB: u32 = 64;
/// Samples a side within each cell.
const THUMB_SAMPLES: u32 = 4;

/// A texture's colours in a [`THUMB`]² grid: each cell's mean linear colour times alpha, and its
/// mean alpha. Enough for a mean over the texels a mesh uses (`mean_color`), which is all the
/// client reads of a character's pictures on the CPU.
pub struct Thumb {
    cells: Vec<Vec4>,
}

impl Thumb {
    fn of(img: &Image) -> Option<Self> {
        let (w, h) = (img.width().max(1), img.height().max(1));
        img.data.as_ref()?;
        let n = THUMB * THUMB_SAMPLES;
        let mut cells = vec![Vec4::ZERO; (THUMB * THUMB) as usize];
        for sy in 0..n {
            for sx in 0..n {
                let (x, y) = (((sx as f32 + 0.5) / n as f32 * w as f32) as u32, ((sy as f32 + 0.5) / n as f32 * h as f32) as u32);
                let Ok(c) = img.get_color_at(x.min(w - 1), y.min(h - 1)) else { continue };
                let l = c.to_linear();
                cells[((sy / THUMB_SAMPLES) * THUMB + sx / THUMB_SAMPLES) as usize] += Vec4::new(l.red * l.alpha, l.green * l.alpha, l.blue * l.alpha, l.alpha);
            }
        }
        let k = 1.0 / (THUMB_SAMPLES * THUMB_SAMPLES) as f32;
        Some(Self { cells: cells.into_iter().map(|c| c * k).collect() })
    }

    /// The cell under a texture coordinate (wrapped).
    fn at(&self, u: f32, v: f32) -> Vec4 {
        let x = ((u.rem_euclid(1.0) * THUMB as f32) as u32).min(THUMB - 1);
        let y = ((v.rem_euclid(1.0) * THUMB as f32) as u32).min(THUMB - 1);
        self.cells[(y * THUMB + x) as usize]
    }
}

/// Character pictures' summaries, by image.
#[derive(Resource, Default)]
pub struct Thumbs(HashMap<AssetId<Image>, Thumb>);

/// The pictures of character files (`lookdev/`) keep a summary of their colours ([`Thumb`]) and
/// leave their pixels to the GPU: their usage becomes the render world's alone, so Bevy drops
/// the main world's copy once it has uploaded them. A town's face pages were about 500 MiB kept
/// on the CPU for nothing but the recolouring's mean colour, which the shader already applies
/// per fragment (`toon.wesl` `recolor`, mode 3). `LIVING_GAME_PERF=keeppixels` keeps them.
fn thumb_pictures(mut events: MessageReader<AssetEvent<Image>>, mut images: ResMut<Assets<Image>>, assets: Res<AssetServer>, mut thumbs: ResMut<Thumbs>) {
    let keep = crate::perf::has("keeppixels");
    for ev in events.read() {
        let AssetEvent::Added { id } = ev else { continue };
        let Some(path) = assets.get_path(*id) else { continue };
        if !path.path().starts_with("lookdev") {
            continue;
        }
        let Some(img) = images.get(*id) else { continue };
        if let Some(t) = Thumb::of(img) {
            thumbs.0.insert(*id, t);
        }
        if !keep {
            if let Some(mut img) = images.get_mut(*id) {
                img.asset_usage = bevy::asset::RenderAssetUsages::RENDER_WORLD;
            }
        }
    }
}

/// A mesh's vertex colours summed by area, and the area: [`vertex_mean`]'s parts, to pool
/// several meshes.
fn vertex_sum(mesh: &Mesh) -> Option<(Vec3, f32)> {
    use bevy::mesh::VertexAttributeValues as V;
    let colours: Vec<Vec3> = match mesh.attribute(Mesh::ATTRIBUTE_COLOR)? {
        V::Float32x4(c) => c.iter().map(|c| Vec3::new(c[0], c[1], c[2])).collect(),
        V::Float32x3(c) => c.iter().map(|c| Vec3::from(*c)).collect(),
        _ => return None,
    };
    let Some(V::Float32x3(pos)) = mesh.attribute(Mesh::ATTRIBUTE_POSITION) else { return None };
    let idx: Vec<usize> = mesh.indices().map_or_else(|| (0..pos.len()).collect(), |i| i.iter().collect());
    let (mut sum, mut wsum) = (Vec3::ZERO, 0.0);
    for t in idx.chunks_exact(3) {
        let p = |k: usize| Vec3::from(pos[t[k]]);
        let area = (p(1) - p(0)).cross(p(2) - p(0)).length();
        sum += (colours[t[0]] + colours[t[1]] + colours[t[2]]) / 3.0 * area;
        wsum += area;
    }
    Some((sum, wsum))
}

/// A mesh's mean vertex colour (linear), weighted by area: the outfit pieces' colours are per
/// vertex, and a brass button's many small triangles shouldn't outweigh a coat's panels.
fn vertex_mean(mesh: &Mesh) -> Option<Vec3> {
    let (sum, w) = vertex_sum(mesh)?;
    (w > 0.0).then(|| sum / w)
}

/// Give each character's meshes their recipe's colours. Characters share their base file's toon
/// materials, so their meshes batch: the material learns its texture's mean colour once
/// (recolouring mode 3), and each mesh carries its recipe colour in its tag, which the shader
/// turns into the remapping. A material per recipe colour split every character into about ten
/// draws of its own in every view and pass.
#[allow(clippy::type_complexity)]
pub fn recolor(
    mut commands: Commands,
    q: Query<(Entity, &MeshMaterial3d<Toon>, &Mesh3d, Option<&bevy::gltf::GltfMaterialName>, Option<&outfit::Piece>), (With<Converted>, Without<Recolored>)>,
    parents: Query<&ChildOf>,
    chars: Query<&Character>,
    mut toons: ResMut<Assets<Toon>>,
    thumbs: Res<Thumbs>,
    meshes: Res<Assets<Mesh>>,
    mut tints: ResMut<compose::HairTints>,
    mut images: ResMut<Assets<Image>>,
    mut ready: Local<std::collections::HashSet<AssetId<Toon>>>,
) {
    for (e, mat, mesh, name, piece) in &q {
        let mut cur = e;
        let mut owner = None;
        while let Ok(p) = parents.get(cur) {
            cur = p.parent();
            if let Ok(c) = chars.get(cur) {
                owner = Some(c);
                break;
            }
        }
        // Outfit pieces take their slot's colour; the body's meshes go by material name.
        let target = owner.and_then(|c| match piece {
            Some(p) => p.recolors().then(|| c.recipe.colors.outfit.get(&p.slot)).flatten(),
            None => name.and_then(|n| slot(&n.0, &c.recipe.colors)),
        });
        let Some(target) = target else {
            commands.entity(e).insert(Recolored);
            continue;
        };
        let Ok(srgb) = Srgba::hex(target) else {
            warn!("characters: bad colour {target}");
            commands.entity(e).insert(Recolored);
            continue;
        };
        if !ready.contains(&mat.0.id()) {
            let Some(toon) = toons.get(&mat.0) else { continue };
            // A material given its source colour when it was made (a composed person's style
            // materials, `compose.rs`) keeps it: it may be shared by meshes of several files.
            if toon.extension.params.recolor.w > 2.5 {
                ready.insert(mat.0.id());
            }
        }
        // A greying person's hair, lock by lock from the palette; else the one tint.
        if piece.is_none() && name.is_some_and(|n| n.0.contains("_HAIR") && !n.0.contains("Overlay")) {
            if let (Some(c), Some(m), Some(t)) = (owner, meshes.get(&mesh.0), toons.get(&mat.0)) {
                if let Some(tag) = grey_tag(c, m, t, &mut tints, &mut images) {
                    commands.entity(e).insert((bevy::mesh::MeshTag::new(tag), Recolored));
                    continue;
                }
            }
        }
        if !ready.contains(&mat.0.id()) {
            let Some(toon) = toons.get(&mat.0) else { continue };
            let Some(mean) = meshes.get(&mesh.0).and_then(|m| mean_color(toon, m, &thumbs)) else { continue };
            let m = hsv(mean);
            if let Some(mut t) = toons.get_mut(&mat.0) {
                t.extension.params.recolor = Vec4::new(0.0, 0.0, 0.0, 3.0);
                t.extension.params.recolor_from = Vec4::new(m.x, HUE_SPREAD, m.y, m.z);
            }
            ready.insert(mat.0.id());
        }
        commands.entity(e).insert((bevy::mesh::MeshTag::new(tag_color(srgb)), Recolored));
    }
    // A grown palette: its toons are touched so their bind groups take the new texels.
    if std::mem::take(&mut tints.grown) {
        for id in tints.users.clone() {
            let _ = toons.get_mut(id);
        }
    }
}

/// `LIVING_GAME_PERF=frames`: frame times every 2 s outside the island, with the number of
/// characters, outfit meshes and the characters' mesh entities (those drawn now and all); and
/// once, how long after the start every character was first shaped and dressed (`people ready`).
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn frames(
    time: Res<Time>,
    real: Res<Time<Real>>,
    island: Option<Res<crate::island::Island>>,
    chars: Query<(Entity, Option<&crate::lookdev::Lod>, Has<Shaped>, Has<outfit::Dressed>, Has<compose::Styled>), With<Character>>,
    pieces: Query<(), With<outfit::Piece>>,
    children: Query<&Children>,
    meshes: Query<&Visibility, With<Mesh3d>>,
    mut acc: Local<(f32, f32, u32)>,
    mut ready: Local<bool>,
) {
    if island.is_some() || !crate::perf::has("frames") {
        return;
    }
    if !*ready && !chars.is_empty() && chars.iter().all(|(_, _, shaped, dressed, _)| shaped && dressed) {
        *ready = true;
        let composed = chars.iter().filter(|c| c.4).count();
        info!("people ready: {} characters ({composed} composed) shaped and dressed {:.2} s after the start", chars.iter().count(), real.elapsed_secs());
    }
    let dt = time.delta_secs();
    acc.0 += dt;
    acc.1 = acc.1.max(dt);
    acc.2 += 1;
    if acc.0 < 2.0 {
        return;
    }
    // People with a far model (`lookdev::far_models`): how many show it now.
    let (lods, far) = chars.iter().filter_map(|c| c.1).filter(|l| l.has_far()).fold((0, 0), |(n, f), l| (n + 1, f + usize::from(l.far_now == Some(true))));
    // Mesh entities under characters: all of them, and those not hidden (the far switch hides
    // one model's set).
    let (mut all, mut shown) = (0, 0);
    for (e, ..) in &chars {
        for d in children.iter_descendants(e) {
            if let Ok(v) = meshes.get(d) {
                all += 1;
                shown += usize::from(*v != Visibility::Hidden);
            }
        }
    }
    info!(
        "people perf: mean {:.2} ms ({:.0} fps), worst {:.1} ms; {} characters, {} outfit meshes, {far} of {lods} with a far model show it; {shown} mesh entities shown of {all}",
        acc.0 / acc.2 as f32 * 1000.0,
        acc.2 as f32 / acc.0,
        acc.1 * 1000.0,
        chars.iter().count(),
        pieces.iter().count()
    );
    *acc = (0.0, 0.0, 0);
}

// --- Spring bones -----------------------------------------------------------------------------

#[derive(Resource, Clone, Copy)]
pub struct SpringSettings {
    pub enabled: bool,
    /// Most characters simulated in a frame (the nearest).
    pub budget: usize,
    /// Distance (m) within which a 1.75 m character is simulated; scales with height.
    pub near: f32,
}

impl SpringSettings {
    fn from_env() -> Self {
        let num = |k: &str, d: f32| std::env::var(k).ok().and_then(|v| v.parse::<f32>().ok()).unwrap_or(d);
        Self { enabled: std::env::var("LIVING_GAME_SPRINGS").map_or(true, |v| v != "0"), budget: num("LIVING_GAME_SPRING_BUDGET", 48.0) as usize, near: num("LIVING_GAME_SPRING_NEAR", 40.0) }
    }
}

/// The fixed-step clock: time not yet simulated.
#[derive(Resource, Default)]
pub struct SpringClock(f32);

/// Cost of the simulation since the last report.
#[derive(Resource, Default)]
pub struct SpringStats {
    frames: u32,
    characters: u32,
    joints: u32,
    nanos: u128,
    /// Time inside the simulation summed over threads, and fixed steps taken.
    cpu_nanos: u64,
    steps: u32,
    since: f32,
}

const STEP: f32 = 1.0 / 60.0;
const MAX_STEPS: u32 = 3;
/// Simulate characters in parallel from this many.
const PARALLEL_FROM: usize = 24;

#[derive(Clone, Copy)]
enum Up {
    /// A bone outside the chains (head, hips, a skirt's root).
    Bone(Entity),
    /// An earlier joint in the list.
    Joint(usize),
}

struct Joint {
    e: Entity,
    parent: Up,
    /// Local offset from the parent, initial local rotation and scale (a composed hair style's
    /// chain root carries the type's `hair_fit`), tail direction and length (local).
    t: Vec3,
    r0: Quat,
    s0: Vec3,
    axis: Vec3,
    len: f32,
    group: usize,
    /// World tail now and a step ago.
    tail: Vec3,
    prev: Vec3,
}

struct Group {
    stiffness: f32,
    gravity: Vec3,
    drag: f32,
    radius: f32,
    spheres: Vec<usize>,
}

struct Sphere {
    bone: Entity,
    offset: Vec3,
    radius: f32,
}

/// A character's spring chains, in hierarchy order, and the latest results.
#[derive(Component)]
pub struct Springs {
    joints: Vec<Joint>,
    groups: Vec<Group>,
    spheres: Vec<Sphere>,
    /// Simulated this frame; and whether the tails need placing at rest (newly active).
    active: bool,
    fresh: bool,
    /// Simulated this frame (its results are new).
    ran: bool,
    /// Each joint's new local rotation and global transform.
    out: Vec<(Quat, GlobalTransform)>,
    centres: Vec<(Vec3, f32)>,
}

/// Find each shaped character's spring chains and colliders.
#[allow(clippy::type_complexity)]
pub fn rig_springs(
    mut commands: Commands,
    chars: Query<(Entity, &Model, &Shaped, Option<&compose::Styled>), (With<Character>, Without<Springs>)>,
    children: Query<&Children>,
    parents: Query<&ChildOf>,
    names: Query<&Name>,
    transforms: Query<&Transform>,
) {
    for (e, model, shaped, styled) in &chars {
        // A composed person's spring chains and colliders come with its styles (a hair style's
        // VRM block), after its type's own.
        let infos: Vec<Arc<FileInfo>> = std::iter::once(file_info(&model.file)).chain(styled.into_iter().flat_map(|s| s.worn.iter().map(|w| file_info(&w.file)))).collect();
        let mut by_name: HashMap<&str, Entity> = HashMap::new();
        for d in children.iter_descendants(e) {
            if let Ok(n) = names.get(d) {
                by_name.insert(n.as_str(), d);
            }
        }
        let mut spheres = Vec::new();
        let mut joints: Vec<Joint> = Vec::new();
        let mut index: HashMap<Entity, usize> = HashMap::new();
        let mut groups = Vec::new();
        for info in &infos {
            let mut collider_spheres: Vec<Vec<usize>> = Vec::new();
            for c in &info.colliders {
                let mut ids = Vec::new();
                if let Some(&bone) = by_name.get(c.node.as_str()) {
                    // A bone scaled in its own frame widens its spheres too.
                    let s = shaped.scales.get(&bone).copied().unwrap_or(Vec3::ONE);
                    let along_x = c.node.contains("Arm") || c.node.contains("Shoulder") || c.node.contains("Hand");
                    let girth = if along_x { (s.y + s.z) * 0.5 } else { (s.x + s.z) * 0.5 };
                    for (off, r) in &c.spheres {
                        ids.push(spheres.len());
                        spheres.push(Sphere { bone, offset: *off * s, radius: r * girth });
                    }
                }
                collider_spheres.push(ids);
            }
            for g in info.springs.iter() {
                let gi = groups.len();
                groups.push(Group { stiffness: g.stiffness, gravity: g.gravity, drag: g.drag.clamp(0.0, 1.0), radius: g.radius, spheres: g.colliders.iter().filter_map(|c| collider_spheres.get(*c)).flatten().copied().collect() });
                for root in &g.bones {
                    let Some(&r) = by_name.get(root.as_str()) else { continue };
                    // Depth first: parents before children.
                    let mut stack = vec![r];
                    while let Some(j) = stack.pop() {
                        if index.contains_key(&j) {
                            continue;
                        }
                        let Ok(tf) = transforms.get(j) else { continue };
                        let kids: Vec<Entity> = children.get(j).map(|c| c.iter().filter(|k| transforms.contains(*k)).collect()).unwrap_or_default();
                        let child = kids.first().and_then(|k| transforms.get(*k).ok()).map(|t| t.translation).filter(|t| t.length() > 1e-5);
                        // A leaf's tail lies 7 cm on along its own offset (UniVRM).
                        let local_tail = child.unwrap_or_else(|| tf.translation.try_normalize().unwrap_or(Vec3::NEG_Y) * 0.07);
                        let Ok(p) = parents.get(j).map(|p| p.parent()) else { continue };
                        let parent = index.get(&p).map_or(Up::Bone(p), |i| Up::Joint(*i));
                        index.insert(j, joints.len());
                        joints.push(Joint { e: j, parent, t: tf.translation, r0: tf.rotation, s0: tf.scale, axis: local_tail.normalize(), len: local_tail.length(), group: gi, tail: Vec3::ZERO, prev: Vec3::ZERO });
                        stack.extend(kids.iter().rev());
                    }
                }
            }
        }
        let n = joints.len();
        debug!("characters: {} has {n} spring joints, {} collider spheres", model.file, spheres.len());
        commands.entity(e).insert(Springs { joints, groups, spheres, active: false, fresh: true, ran: false, out: vec![(Quat::IDENTITY, GlobalTransform::IDENTITY); n], centres: vec![] });
    }
}

impl Springs {
    /// Simulate `steps` fixed steps against the current pose (read-only transforms).
    fn simulate(&mut self, steps: u32, globals: &Query<&GlobalTransform>) {
        self.centres.clear();
        for s in &self.spheres {
            match globals.get(s.bone) {
                Ok(g) => {
                    let (sc, _, _) = g.to_scale_rotation_translation();
                    self.centres.push((g.transform_point(s.offset), s.radius * sc.x.abs()));
                }
                Err(_) => self.centres.push((Vec3::splat(f32::MAX), 0.0)),
            }
        }
        let fresh = std::mem::replace(&mut self.fresh, false);
        self.ran = true;
        for step in 0..steps.max(1) {
            for i in 0..self.joints.len() {
                let parent = match self.joints[i].parent {
                    Up::Bone(b) => match globals.get(b) {
                        Ok(g) => *g,
                        Err(_) => continue,
                    },
                    Up::Joint(k) => self.out[k].1,
                };
                let (ps, pr, _) = parent.to_scale_rotation_translation();
                let sc = ps.x.abs().max(1e-6);
                let j = &mut self.joints[i];
                let g = &self.groups[j.group];
                let pos = parent.transform_point(j.t);
                let rest = pr * j.r0;
                let rest_dir = rest * j.axis;
                let len = j.len * sc;
                if fresh && step == 0 {
                    j.tail = pos + rest_dir * len;
                    j.prev = j.tail;
                }
                if steps > 0 {
                    // Verlet: inertia less drag, a pull back to the rest direction, gravity. Forces
                    // are in the model's units, so they scale with the character.
                    let mut next = j.tail + (j.tail - j.prev) * (1.0 - g.drag) + rest_dir * (g.stiffness * STEP * sc) + g.gravity * (STEP * sc);
                    next = pos + (next - pos).try_normalize().unwrap_or(rest_dir) * len;
                    for &si in &g.spheres {
                        let (c, r) = self.centres[si];
                        let r = r + g.radius * sc;
                        let d = next - c;
                        if d.length_squared() < r * r {
                            let pushed = c + d.try_normalize().unwrap_or(rest_dir) * r;
                            next = pos + (pushed - pos).try_normalize().unwrap_or(rest_dir) * len;
                        }
                    }
                    j.prev = j.tail;
                    j.tail = next;
                }
                let to = (j.tail - pos).try_normalize().unwrap_or(rest_dir);
                let world = Quat::from_rotation_arc(rest_dir.normalize(), to) * rest;
                let local = (pr.inverse() * world).normalize();
                self.out[i] = (local, parent.mul_transform(Transform { translation: j.t, rotation: local, scale: j.s0 }));
            }
        }
    }
}

/// Run the spring chains after the pose is final, nearest characters first, within budget.
#[allow(clippy::type_complexity)]
pub fn springs(
    settings: Res<SpringSettings>,
    mut clock: ResMut<SpringClock>,
    mut stats: ResMut<SpringStats>,
    time: Res<Time>,
    mut chars: Query<(Entity, &mut Springs, &Character, Option<&InheritedVisibility>)>,
    cams: Query<Entity, With<Camera3d>>,
    mut set: ParamSet<(Query<&GlobalTransform>, Query<(&mut Transform, &mut GlobalTransform)>)>,
) {
    clock.0 += time.delta_secs().min(0.25);
    let steps = ((clock.0 / STEP) as u32).min(MAX_STEPS);
    clock.0 = (clock.0 - steps as f32 * STEP).min(STEP);
    let start = std::time::Instant::now();
    // Who is simulated: visible, near enough for their size, and the nearest within budget.
    let mut want: Vec<(f32, Entity)> = Vec::new();
    {
        let globals = set.p0();
        let eye = cams.iter().next().and_then(|c| globals.get(c).ok()).map(|g| g.translation());
        for (e, _, ch, vis) in &chars {
            if !settings.enabled || vis.is_some_and(|v| !v.get()) {
                continue;
            }
            let Ok(g) = globals.get(e) else { continue };
            let d = eye.map_or(0.0, |eye| g.translation().distance(eye));
            if d < settings.near * (ch.recipe.height / 1.75).max(0.5).sqrt() {
                want.push((d, e));
            }
        }
    }
    want.sort_by(|a, b| a.0.total_cmp(&b.0));
    want.truncate(settings.budget);
    let chosen: std::collections::HashSet<Entity> = want.iter().map(|w| w.1).collect();
    // Characters going to rest: back to their rigid pose, placed afresh when they wake.
    let mut resting: Vec<(Entity, Quat)> = Vec::new();
    for (e, mut sp, _, _) in &mut chars {
        let now = chosen.contains(&e);
        if sp.active && !now {
            resting.extend(sp.joints.iter().map(|j| (j.e, j.r0)));
        }
        if !sp.active && now {
            sp.fresh = true;
        }
        sp.active = now;
    }
    let cpu = std::sync::atomic::AtomicU64::new(0);
    {
        let globals = set.p0();
        let run = |(_, mut sp, _, _): (Entity, Mut<Springs>, &Character, Option<&InheritedVisibility>)| {
            if sp.active && (steps > 0 || sp.fresh) {
                let t = std::time::Instant::now();
                sp.simulate(steps, &globals);
                cpu.fetch_add(t.elapsed().as_nanos() as u64, std::sync::atomic::Ordering::Relaxed);
            }
        };
        // A few characters cost less than waking the task pool (which may be busy loading).
        if want.len() > PARALLEL_FROM {
            chars.par_iter_mut().for_each(run);
        } else {
            chars.iter_mut().for_each(run);
        }
    }
    let mut writes = set.p1();
    let (mut n_chars, mut n_joints) = (0u32, 0u32);
    for (_, mut sp, _, _) in &mut chars {
        if !sp.active || !std::mem::replace(&mut sp.ran, false) {
            continue;
        }
        n_chars += 1;
        n_joints += sp.joints.len() as u32;
        for (j, (local, global)) in sp.joints.iter().zip(&sp.out) {
            if let Ok((mut tf, mut g)) = writes.get_mut(j.e) {
                tf.rotation = *local;
                *g = *global;
            }
        }
    }
    for (e, r) in resting {
        if let Ok((mut tf, _)) = writes.get_mut(e) {
            tf.rotation = r;
        }
    }
    stats.frames += 1;
    stats.characters += n_chars;
    stats.joints += n_joints;
    stats.nanos += start.elapsed().as_nanos();
    stats.cpu_nanos += cpu.into_inner();
    stats.steps += steps * n_chars;
    stats.since += time.delta_secs();
    if stats.since >= 3.0 {
        if stats.characters > 0 {
            let f = stats.frames.max(1) as f64;
            let us = stats.nanos as f64 / 1000.0 / f;
            let chars_per = stats.characters as f64 / f;
            // Wall time of the whole system per frame; simulation time summed over threads per
            // character and fixed step.
            let per_step = stats.cpu_nanos as f64 / 1000.0 / stats.steps.max(1) as f64;
            info!(
                "springs: {chars_per:.1} characters ({:.0} joints) a frame, {us:.0} µs a frame (wall), {:.1} µs a character; {per_step:.1} µs CPU a character-step, {:.2} steps a frame",
                stats.joints as f64 / f,
                us / chars_per.max(1e-9),
                stats.steps as f64 / stats.characters.max(1) as f64
            );
        }
        *stats = SpringStats::default();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use bevy::world_serialization::{WorldInstanceReady, WorldInstanceSpawner};

    #[test]
    fn a_second_spawn_of_a_characters_scene_lets_go_of_what_was_built_on_the_old_one() {
        let mut app = App::new();
        app.add_message::<Rebuilt>().add_observer(on_ready);
        let recipe = Recipe { name: "test".into(), base: "lookdev/own-test.glb".into(), height: 1.2, proportions: Proportions::default(), colors: Colors::default(), outfit: BTreeMap::new(), identity: BTreeMap::new(), person: None };
        let shaped = Shaped { hips: None, hips_k: 1.0, written: Vec3::NAN, scales: HashMap::new(), helpers: HashMap::new() };
        let fitted = Fitted { y_off: 0.0, size: Vec3::ONE, center: Vec3::ZERO };
        let e = app.world_mut().spawn((Character { recipe, stride: 0.6 }, fitted, shaped, outfit::Dressed, crate::anim::Bound, Visibility::Inherited)).id();
        let piece = app.world_mut().spawn((outfit::Piece { slot: "head".into(), material: "Hat".into() }, ChildOf(e))).id();
        let other = app.world_mut().spawn(ChildOf(e)).id();
        let instance = WorldInstanceSpawner::default().spawn_as_child(Handle::default(), e);
        // The first spawn: counted, nothing let go.
        app.world_mut().trigger(WorldInstanceReady { entity: e, instance_id: instance });
        app.world_mut().flush();
        assert_eq!(app.world().get::<Spawns>(e).map(|s| s.0), Some(1));
        assert!(app.world().get::<Shaped>(e).is_some() && app.world().get::<Fitted>(e).is_some());
        // Spawned again (a changed scene asset): fitted, shaped, dressed and bound again from scratch.
        app.world_mut().trigger(WorldInstanceReady { entity: e, instance_id: instance });
        app.world_mut().flush();
        let w = app.world();
        assert_eq!(w.get::<Spawns>(e).map(|s| s.0), Some(2));
        assert!(w.get::<Shaped>(e).is_none() && w.get::<Fitted>(e).is_none() && w.get::<outfit::Dressed>(e).is_none() && w.get::<crate::anim::Bound>(e).is_none());
        assert_eq!(w.get::<Visibility>(e), Some(&Visibility::Hidden), "hidden until fitted again");
        assert!(w.get_entity(piece).is_err(), "the outfit pieces on the old bones go");
        assert!(w.get_entity(other).is_ok(), "only outfit pieces go");
        assert_eq!(w.resource::<Messages<Rebuilt>>().iter_current_update_messages().count(), 1);
    }
}
