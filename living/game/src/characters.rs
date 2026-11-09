//! Characters from recipes: distinct people of different sizes who share one skeleton (VRoid's
//! `J_Bip_*`) and one animation set, with spring bones for hair, skirts and sleeves.
//!
//! **Recipes** (`assets/characters/recipes.json`): a base VRoid file, a height in metres,
//! proportions and colours. [`Recipe::random`] draws a recipe for a folk (`adult`, `giant`,
//! `small`) from the file's ranges and palettes; [`Recipe::for_height`] picks the folk by height.
//! [`spawn`] puts one in the world; callers add their own markers (`EnvPart`, `Occluder`).
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
//! `ToonParams`): the hue moves and saturation and value are remapped so that the material's
//! mean texture colour becomes the recipe's colour, keeping the texture's detail. Grey textures
//! are tinted instead. Groups go by VRoid's material names: `_HAIR` (and brows), `_SKIN`,
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

use crate::lookdev::{Converted, Fitted, Model};
use crate::style::Toon;
use bevy::mesh::skinning::SkinnedMesh;
use bevy::prelude::*;
use bevy::world_serialization::WorldAssetRoot;
use serde::Deserialize;
use std::collections::HashMap;
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
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct Palettes {
    hair: Vec<String>,
    skin: Vec<String>,
    eyes: Vec<String>,
    outfit: Vec<String>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct Book {
    bases: Vec<String>,
    recipes: Vec<Recipe>,
    /// Folk → proportion (and `height`) → [min, max].
    folks: HashMap<String, HashMap<String, [f32; 2]>>,
    palettes: Palettes,
}

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
    pub fn default_for(base: &str) -> Recipe {
        let plain = Recipe { name: String::new(), base: base.to_string(), height: 1.75, proportions: Proportions::default(), colors: Colors::default() };
        book().recipes.iter().find(|r| r.base == base && r.proportions == plain.proportions && r.colors == plain.colors).cloned().unwrap_or_else(|| Recipe {
            name: std::path::Path::new(base).file_stem().unwrap_or_default().to_string_lossy().to_string(),
            ..plain
        })
    }

    /// A seeded random recipe for a folk (`adult`, `giant`, `small`) from the file's ranges.
    pub fn random(seed: u64, folk: &str) -> Recipe {
        let b = book();
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
        let p = &b.palettes;
        let outfit = |r: &mut Rng| r.pick(&p.outfit).cloned();
        let colors = Colors {
            hair: r.pick(&p.hair).cloned(),
            skin: r.pick(&p.skin).cloned(),
            eyes: r.pick(&p.eyes).cloned(),
            top: outfit(&mut r),
            bottom: outfit(&mut r),
            shoes: outfit(&mut r),
            accent: outfit(&mut r),
        };
        let base = r.pick(&b.bases).cloned().unwrap_or_else(|| "lookdev/vroid-Vivi.glb".into());
        Recipe { name: format!("{folk}-{seed}"), base, height: at("height", tall), proportions, colors }
    }

    /// A random recipe of exactly this height, its folk chosen by it.
    pub fn for_height(seed: u64, height: f32) -> Recipe {
        let folk = if height < 1.1 {
            "small"
        } else if height > 3.0 {
            "giant"
        } else {
            "adult"
        };
        Recipe { height, ..Recipe::random(seed, folk) }
    }

    /// `name` from the file, or `<folk>:<seed>` / `<folk>-<seed>` for a random one.
    pub fn parse(token: &str) -> Option<Recipe> {
        Recipe::named(token).or_else(|| {
            let (folk, seed) = token.split_once(':').or_else(|| token.rsplit_once('-'))?;
            Some(Recipe::random(seed.parse().ok()?, folk))
        })
    }
}

/// A character built from a recipe (on the model root, beside [`Model`]).
#[derive(Component)]
pub struct Character {
    pub recipe: Recipe,
    /// This character's stride against its base at 1.75 m: locomotion clips play at
    /// `speed / (clip speed × stride)` so feet don't slide.
    pub stride: f32,
}

/// Spawn a character at `at` (its sole on `at.y`), facing `yaw` (0 = +Z, the camera's default
/// side; turning counter-clockwise seen from above). Callers add their own markers.
pub fn spawn(commands: &mut Commands, assets: &AssetServer, recipe: &Recipe, at: Vec3, yaw: f32) -> Entity {
    let file = crate::lookdev::animated(&recipe.base);
    let handle = assets.load(GltfAssetLabel::Scene(0).from_asset(file.clone()));
    // VRM 0.x models face −Z.
    let model = Model { vrm: true, file, height: recipe.height, ground_y: at.y, glow: None };
    commands
        .spawn((model, Character { recipe: recipe.clone(), stride: 1.0 }, WorldAssetRoot(handle), Transform::from_translation(at).with_rotation(Quat::from_rotation_y(yaw + PI)), Visibility::Hidden))
        .id()
}

/// A crowd of `n` seeded random characters in rows north of `centre`, facing south: small folk
/// in front, then adults, giants behind. Returns their roots.
pub fn spawn_crowd(commands: &mut Commands, assets: &AssetServer, n: usize, seed: u64, centre: Vec3) -> Vec<Entity> {
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
            let recipe = Recipe::random(s, folk);
            let yaw = ((s % 7) as f32 - 3.0) * 0.08;
            out.push(spawn(commands, assets, &recipe, Vec3::new(x, centre.y, z - row as f32 * depth), yaw));
        }
        z -= (count.saturating_sub(1) / per_row) as f32 * depth;
    }
    out
}

pub struct CharactersPlugin;

impl Plugin for CharactersPlugin {
    fn build(&self, app: &mut App) {
        app.insert_resource(SpringSettings::from_env())
            .init_resource::<SpringClock>()
            .init_resource::<SpringStats>()
            .add_systems(Update, (shape, recolor, rig_springs))
            .add_systems(PostUpdate, (hips.after(bevy::app::AnimationSystems).before(TransformSystems::Propagate), springs.after(TransformSystems::Propagate)));
    }
}

/// What the rest of a file looks like, read once from its glTF JSON: rest translations by node
/// name and its spring bones.
struct FileInfo {
    rest: HashMap<String, Vec3>,
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
    let info = Arc::new(FileInfo { rest, springs, colliders });
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
}

/// Apply a recipe's proportions and height once its model is loaded and measured.
#[allow(clippy::type_complexity)]
pub fn shape(
    mut commands: Commands,
    mut chars: Query<(Entity, &mut Character, &Model, &mut Transform, &mut Fitted), Without<Shaped>>,
    children: Query<&Children>,
    names: Query<&Name>,
    mut bones: Query<&mut Transform, Without<Character>>,
    mut skins: Query<&mut SkinnedMesh>,
) {
    for (e, mut ch, model, mut root, mut fit) in &mut chars {
        let info = file_info(&model.file);
        let mut by_name: HashMap<&str, Entity> = HashMap::new();
        for d in children.iter_descendants(e) {
            if let Ok(n) = names.get(d) {
                by_name.insert(n.as_str(), d);
            }
        }
        let Some(&hips) = by_name.get("J_Bip_C_Hips") else {
            commands.entity(e).insert(Shaped { hips: None, hips_k: 1.0, written: Vec3::NAN, scales: HashMap::new() });
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
                    // Children's offsets move with the bone's length and width.
                    for c in children.get(bone).into_iter().flatten() {
                        if let (Ok(cn), Ok(mut tf)) = (names.get(*c), bones.get_mut(*c)) {
                            if cn.as_str() != "J_Bip_C_Hips" {
                                tf.translation = info.rest.get(cn.as_str()).copied().unwrap_or(tf.translation) * v;
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
        // Stride against the base at 1.75 m.
        let base_hip = (hips0.y - lo) * 1.75 / (top0 - lo).max(0.01);
        ch.stride = ((hips_y - lo) * k / base_hip.max(0.01)).max(0.05);
        debug!("characters: {} {:.2} m (×{k:.3}), hips ×{hips_k:.3}, stride {:.2}", ch.recipe.name, ch.recipe.height, ch.stride);
        commands.entity(e).insert(Shaped { hips: Some(hips), hips_k, written: Vec3::NAN, scales });
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
    if m.contains("_HAIR") || m.contains("FaceBrow") {
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
const HUE_SPREAD: f32 = 0.4;

/// Shader recolour parameters (`recolor`, `recolor_from`) that map a material's mean colour
/// `mean` onto `target` (both linear): x the target hue, y saturation and z value as factors
/// (≥ 0 scales toward 0, < 0 is `-f` scaling the distance to 1), w the mode (1 move the hues,
/// 2 tint a grey texture); then the mean hue and the hue spread.
fn recolor_params(mean: Vec3, target: Vec3) -> (Vec4, Vec4) {
    let (m, t) = (hsv(mean), hsv(target));
    let f = |m: f32, t: f32| if t <= m { if m > 1e-4 { t / m } else { 1.0 } } else { -((1.0 - t) / (1.0 - m).max(1e-4)).max(1e-4) };
    if m.y < 0.12 {
        (Vec4::new(t.x, t.y, f(m.z, t.z), 2.0), Vec4::ZERO)
    } else {
        (Vec4::new(t.x, f(m.y, t.y), f(m.z, t.z), 1.0), Vec4::new(m.x, HUE_SPREAD, 0.0, 0.0))
    }
}

/// A material's mean colour (linear) over the texels its mesh's vertices use.
fn mean_color(toon: &Toon, mesh: &Mesh, images: &Assets<Image>) -> Option<Vec3> {
    let base = toon.base.base_color.to_linear();
    let base = Vec3::new(base.red, base.green, base.blue);
    let Some(tex) = toon.base.base_color_texture.as_ref() else { return Some(base) };
    let img = images.get(tex)?;
    let (w, h) = (img.width().max(1), img.height().max(1));
    let Some(bevy::mesh::VertexAttributeValues::Float32x2(uvs)) = mesh.attribute(Mesh::ATTRIBUTE_UV_0) else { return Some(base) };
    let (mut sum, mut wsum) = (Vec3::ZERO, 0.0);
    let step = (uvs.len() / 4000).max(1);
    for uv in uvs.iter().step_by(step) {
        let x = ((uv[0].rem_euclid(1.0) * w as f32) as u32).min(w - 1);
        let y = ((uv[1].rem_euclid(1.0) * h as f32) as u32).min(h - 1);
        let Ok(c) = img.get_color_at(x, y) else { continue };
        let l = c.to_linear();
        sum += Vec3::new(l.red, l.green, l.blue) * l.alpha;
        wsum += l.alpha;
    }
    (wsum > 0.0).then(|| sum / wsum * base)
}

/// Give each character's meshes their recipe's colours (per-instance toon materials).
#[allow(clippy::type_complexity, clippy::too_many_arguments)]
pub fn recolor(
    mut commands: Commands,
    q: Query<(Entity, &MeshMaterial3d<Toon>, &Mesh3d, Option<&bevy::gltf::GltfMaterialName>), (With<Converted>, Without<Recolored>)>,
    parents: Query<&ChildOf>,
    chars: Query<&Character>,
    mut toons: ResMut<Assets<Toon>>,
    images: Res<Assets<Image>>,
    meshes: Res<Assets<Mesh>>,
    mut cache: Local<(HashMap<(AssetId<Toon>, String), Handle<Toon>>, HashMap<AssetId<Toon>, Vec3>)>,
) {
    for (e, mat, mesh, name) in &q {
        let mut cur = e;
        let mut owner = None;
        while let Ok(p) = parents.get(cur) {
            cur = p.parent();
            if let Ok(c) = chars.get(cur) {
                owner = Some(c);
                break;
            }
        }
        let target = owner.zip(name).and_then(|(c, n)| slot(&n.0, &c.recipe.colors));
        let Some(target) = target else {
            commands.entity(e).insert(Recolored);
            continue;
        };
        let Ok(srgb) = Srgba::hex(target) else {
            warn!("characters: bad colour {target}");
            commands.entity(e).insert(Recolored);
            continue;
        };
        let key = (mat.0.id(), target.clone());
        if let Some(h) = cache.0.get(&key) {
            commands.entity(e).insert((MeshMaterial3d(h.clone()), Recolored));
            continue;
        }
        let Some(toon) = toons.get(&mat.0) else { continue };
        let mean = match cache.1.get(&mat.0.id()) {
            Some(m) => *m,
            None => {
                let Some(m) = meshes.get(&mesh.0).and_then(|m| mean_color(toon, m, &images)) else { continue };
                cache.1.insert(mat.0.id(), m);
                m
            }
        };
        let l = LinearRgba::from(srgb);
        let mut t = toon.clone();
        (t.extension.params.recolor, t.extension.params.recolor_from) = recolor_params(mean, Vec3::new(l.red, l.green, l.blue));
        let h = toons.add(t);
        cache.0.insert(key, h.clone());
        commands.entity(e).insert((MeshMaterial3d(h), Recolored));
    }
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
    /// Local offset from the parent, initial local rotation, tail direction and length (local).
    t: Vec3,
    r0: Quat,
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
    chars: Query<(Entity, &Model, &Shaped), (With<Character>, Without<Springs>)>,
    children: Query<&Children>,
    parents: Query<&ChildOf>,
    names: Query<&Name>,
    transforms: Query<&Transform>,
) {
    for (e, model, shaped) in &chars {
        let info = file_info(&model.file);
        let mut by_name: HashMap<&str, Entity> = HashMap::new();
        for d in children.iter_descendants(e) {
            if let Ok(n) = names.get(d) {
                by_name.insert(n.as_str(), d);
            }
        }
        let mut spheres = Vec::new();
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
        let mut joints: Vec<Joint> = Vec::new();
        let mut index: HashMap<Entity, usize> = HashMap::new();
        let mut groups = Vec::new();
        for (gi, g) in info.springs.iter().enumerate() {
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
                    joints.push(Joint { e: j, parent, t: tf.translation, r0: tf.rotation, axis: local_tail.normalize(), len: local_tail.length(), group: gi, tail: Vec3::ZERO, prev: Vec3::ZERO });
                    stack.extend(kids.iter().rev());
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
                self.out[i] = (local, parent.mul_transform(Transform { translation: j.t, rotation: local, scale: Vec3::ONE }));
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
