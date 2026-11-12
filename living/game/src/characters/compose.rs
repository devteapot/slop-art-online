//! A person composed from shared files: a type's file (head, neck and hands, the skeleton and the
//! identity bones) and the style files the person wears (hair, outfit pieces), in place of one
//! whole file a person (docs/CHARACTERS.md, "The client format", "Hair styles", "Outfit pieces").
//!
//! **The switch.** `LIVING_GAME_COMPOSE=1` composes every recipe that carries a person line
//! (`person`: the generator's `<name>.params.json` line). Off (the default), a recipe is its whole
//! `base` file as before. A recipe without a person line is its base file either way.
//!
//! **The person line** names the type, the height, the proportions (`build` carries the girth a
//! whole file built into its meshes), the identity values, the colours and the style files. The
//! character is spawned from `lookdev/types/<type>.glb` with the line's numbers ([`prepare`]);
//! identity, proportions, height, recolouring, the far switch, springs and clips then run as for
//! any generated person.
//!
//! **Attaching** ([`attach`], when the type's scene comes in, before it is first fitted), each
//! style file by `compose.py`'s rule, so a type plus a style matches the generator to 0.000 mm:
//! 1. every mesh node of the file comes across (its `Far*` meshes too, for the far switch), each
//!    primitive an entity under the character's root with a `SkinnedMesh`;
//! 2. joints are the person's own bones by name;
//! 3. a joint's inverse bind matrix is the type's own for it (the inverse of its rest in the
//!    type's file) times `hair_fit` (the type's scene extras: the standard skull laid onto the
//!    type's) for hair and head pieces (`cap`, `kerchief`), times nothing for body pieces;
//! 4. bones only the style has (a hair style's spring chains) are added under the person's
//!    `J_Id_Cranium`, each at `hair_fit` × its rest in the style's file, and its spring groups
//!    and colliders join the person's (`rig_springs`).
//!
//! **Shared, not copied.** A style file is loaded once ([`super::kept`]) and its meshes are the
//! file's own mesh assets for everyone wearing it. Bind matrices are one asset a type and file.
//! People differ only in their bones and their mesh tags (colours), so the shared meshes batch.
//!
//! **Materials by what they draw** ([`Plans`]). Every material is a batch set in every view and
//! pass, so style files share toon materials wherever the result is the same. A person's colours
//! are not in a material: each mesh carries its own in its tag, and the shader moves the
//! material's source colour to it (`toon.wesl` `recolor`, mode 3). What a material brings is its
//! content (the glTF material, its picture, its kind of shading, a face's shadow map) and that
//! source colour (`characters::source_mean`): its picture's whole mean, else the mean of its
//! file's vertex colours (near meshes first), set on the toon when it is made and kept by
//! `recolor`. A file's material shares a toon already made with the same content whose source
//! colour is within [`SAME_SOURCE`] of its own, so every tag draws the same on either to below a
//! step of the screen's 8 bits; else it makes its own. The generator builds each class of style
//! files around one shading mean (docs/CHARACTERS.md, "One shading mean a class"): every outfit
//! piece's `Cloth` is then one toon, and every hair cut's hair one (their one picture's mean).
//! `LIVING_GAME_PERF=filestyles` (measurement only) keys one a file and material name, as before,
//! to compare.
//!
//! **Colours** go through the mesh tag as recipes recolour today (`recolor`, mode 3): hair by its
//! `_HAIR` material, skin by `_SKIN`, an outfit piece by its own name in the line's
//! `colors.outfit` (an [`super::outfit::Piece`] whose slot is the piece). A hair style's tie keeps
//! its own colour, as compose.py leaves it.
//!
//! **Overlays** (`styles.overlays`: beards, stubble, lines, freckles, docs/CHARACTERS.md "Overlay
//! styles") are files of the person's own type (`lookdev/styles/overlay/<type>/<name>.glb`), thin
//! blended layers over its face: they attach as body pieces do (the type's own inverse bind
//! matrices, no `hair_fit`), carry the face's blink and open mouth (`lookdev::FaceMorphs`, driven
//! with the face's) and cast no shadow. A beard and stubble (`…Overlay_00_HAIR`, `…FarOverlay_00_HAIR`
//! for the far one) shade as hair and take `colors.beard`. Lines and freckles
//! (`…FaceOverlay_00_FACE`) are a fixed-colour layer, as lips and blush are: drawn as a face
//! part, unshaded, in their picture's own colours, untagged and without a shadow map ([`kind_of`]).
//!
//! **The belly** (`belly`, 0 to about 0.35) moves `J_Fit_Belly` forward by `belly` × 0.108 m (the
//! file's -Z) from its rest when the scene comes in, and `shape` keeps it under the spine's girth.
//!
//! A beard's far mesh (`FarOverlay`) comes with it and shows with the far head, tinted the same.
//!
//! **Not here** (the files' limits): one strength an overlay; the belly a forward bulge only.

use super::{Colors, Proportions, Recipe};
use crate::lookdev::{asset_root, glb_json, Converted};
use crate::style::{outline, Kind, Outlined, Style, Toon};
use bevy::asset::RecursiveDependencyLoadState;
use bevy::camera::visibility::DynamicSkinnedMeshBounds;
use bevy::gltf::{Gltf, GltfMaterial, GltfMaterialName, GltfMesh, GltfNode, GltfSkin};
use bevy::mesh::skinning::{SkinnedMesh, SkinnedMeshInverseBindposes};
use bevy::prelude::*;
use serde::Deserialize;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::{Arc, Mutex, OnceLock};

/// Where type files are, under the asset folder.
pub const TYPES: &str = "lookdev/types";
/// Where style files are (`hair/<style>.glb`, `outfit/<piece>.glb`).
pub const STYLES: &str = "lookdev/styles";
/// A hair vertex's greying (`_GREY` in the hair files: 1 / a, where its lock is wholly grey once a
/// person's `grey` reaches a). The glTF loader reads it (main.rs); composing copies it into the
/// mesh's second UVs, which Bevy's vertex path already brings to the fragment shader, and the
/// hair's shading reads it there (`toon.wesl` `recolor`). The vertex shader turns the second UVs
/// only for a face's skin, so hair's pass as they are.
pub const ATTRIBUTE_GREY: bevy::mesh::MeshVertexAttribute = bevy::mesh::MeshVertexAttribute::new("Grey", 0x5c3e_9a01, bevy::render::render_resource::VertexFormat::Float32);

/// The greying palette the one shared hair material holds (`ToonExt::tints`): row 0 the natural
/// colours and row 1 the silvers that the people drawn with it carry, as sRGB bytes, each once.
/// A greying person's hair meshes carry their two places in it and how grey they are in their
/// tag (`characters::recolor`), so the hair stays one material for everyone. 256 of each; a
/// person whose colour finds no room keeps the one tint (`colors.hair`).
#[derive(Resource)]
pub struct HairTints {
    pub image: Handle<Image>,
    rows: [Vec<[u8; 3]>; 2],
    /// The toons that hold the palette, touched when it grows so their bind groups take it.
    pub users: Vec<AssetId<Toon>>,
    pub grown: bool,
}

impl FromWorld for HairTints {
    fn from_world(world: &mut World) -> Self {
        use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
        let img = Image::new_fill(Extent3d { width: 256, height: 2, depth_or_array_layers: 1 }, TextureDimension::D2, &[0, 0, 0, 255], TextureFormat::Rgba8Unorm, bevy::asset::RenderAssetUsages::all());
        Self { image: world.resource_mut::<Assets<Image>>().add(img), rows: [Vec::new(), Vec::new()], users: Vec::new(), grown: false }
    }
}

impl HairTints {
    /// A colour's place on a row (0 natural, 1 silver), added if new; None when the row is full.
    pub fn place(&mut self, row: usize, rgb: [u8; 3], images: &mut Assets<Image>) -> Option<u8> {
        if let Some(i) = self.rows[row].iter().position(|c| *c == rgb) {
            return Some(i as u8);
        }
        let i = self.rows[row].len();
        if i >= 256 {
            return None;
        }
        self.rows[row].push(rgb);
        if let Some(mut img) = images.get_mut(&self.image) {
            if let Some(data) = img.data.as_mut() {
                let at = (row * 256 + i) * 4;
                data[at..at + 3].copy_from_slice(&rgb);
                data[at + 3] = 255;
            }
        }
        self.grown = true;
        Some(i as u8)
    }
}

/// How close two style files' source colours must be (linear, each channel) to share a toon:
/// under one 8-bit step, so sharing moves no colour the screen shows.
pub const SAME_SOURCE: f32 = 0.004;

/// Outfit pieces worn on the head: attached with the type's `hair_fit`, as hair is.
const HEAD_PIECES: [&str; 2] = ["cap", "kerchief"];

/// `LIVING_GAME_COMPOSE=1`: compose people who have a person line from shared files.
pub fn enabled() -> bool {
    static ON: OnceLock<bool> = OnceLock::new();
    *ON.get_or_init(|| {
        let on = std::env::var("LIVING_GAME_COMPOSE").is_ok_and(|v| v == "1");
        if on {
            info!("compose: people with a person line are composed from {TYPES} and {STYLES}");
        }
        on
    })
}

/// A person as the client composes one: the generator's person line (`person_params.person_line`).
#[derive(Deserialize, Clone, Debug, PartialEq)]
pub struct Person {
    /// A type id: `lookdev/types/<type>.glb`.
    #[serde(rename = "type")]
    pub kind: String,
    pub height: f32,
    #[serde(default)]
    pub proportions: Proportions,
    #[serde(default)]
    pub identity: BTreeMap<String, f32>,
    /// Skin, hair (and eyes, when a line gives them); `outfit` by piece name.
    #[serde(default)]
    pub colors: Colors,
    #[serde(default)]
    pub styles: Styles,
    /// How far the belly stands out (0 to about 0.35): `J_Fit_Belly` moves forward by this ×
    /// [`BELLY_M`].
    #[serde(default)]
    pub belly: f32,
    /// How grey the person is (0 to 0.9; none when left out): hair greys lock by lock from
    /// `colors.hair_natural` to `colors.hair_silver` by the hair file's `_GREY`.
    #[serde(default)]
    pub grey: f32,
}

/// How far `J_Fit_Belly` moves forward for a `belly` of 1 (metres in the file, along -Z).
pub const BELLY_M: f32 = 0.108;

/// Where a composed person's `J_Fit_Belly` stands from its rest (file units): forward by the
/// line's `belly`. Nothing for a whole file, which carries its belly in its meshes.
pub fn belly_offset(recipe: &Recipe, styled: bool) -> Vec3 {
    match recipe.person.as_ref().filter(|_| styled) {
        Some(p) => Vec3::new(0.0, 0.0, -p.belly * BELLY_M),
        None => Vec3::ZERO,
    }
}

/// The style files a person wears.
#[derive(Deserialize, Clone, Debug, PartialEq, Default)]
#[serde(default)]
pub struct Styles {
    /// `lookdev/styles/hair/<hair>.glb`.
    pub hair: Option<String>,
    /// `lookdev/styles/outfit/<piece>.glb`, each.
    pub outfit: Vec<String>,
    /// `lookdev/styles/overlay/<type>/<name>.glb`, each: beards, stubble, lines, freckles.
    pub overlays: Vec<String>,
}

/// One style file a composed character wears.
pub struct Wear {
    /// Under the asset folder.
    pub file: String,
    /// The piece's name, for its colour (`colors.outfit`); none for hair.
    pub slot: Option<String>,
    /// Attached with the type's `hair_fit` (hair and head pieces).
    pub fitted: bool,
    /// A layer over the face (an overlay): no shadow.
    pub overlay: bool,
    handle: Handle<Gltf>,
}

/// On a composed character: the style files it wears.
#[derive(Component)]
pub struct Styled {
    pub worn: Vec<Wear>,
}

impl Styled {
    /// Whether every file worn has loaded (or failed to).
    pub fn loaded(&self, assets: &AssetServer) -> bool {
        self.worn.iter().all(|w| matches!(assets.recursive_dependency_load_state(&w.handle), RecursiveDependencyLoadState::Loaded | RecursiveDependencyLoadState::Failed(_)))
    }
}

/// On each mesh and bone a style file brought to a character: let go of with its old scene
/// (`forget_scene`) and attached again on the new one.
#[derive(Component)]
pub struct Worn;

fn exists(file: &str) -> bool {
    std::path::Path::new(&asset_root()).join(file).exists()
}

fn warn_once(msg: String) {
    static SEEN: OnceLock<Mutex<HashSet<String>>> = OnceLock::new();
    if SEEN.get_or_init(Default::default).lock().unwrap().insert(msg.clone()) {
        warn!("{msg}");
    }
}

/// The recipe a character is spawned from, and the style files it wears: with the switch on and
/// a person line whose type file exists, the line's person on the type's file; else the recipe
/// as it is.
pub fn prepare(recipe: &Recipe, assets: &AssetServer) -> (Recipe, Option<Styled>) {
    let Some(p) = recipe.person.as_ref().filter(|_| enabled()) else { return (recipe.clone(), None) };
    let base = format!("{TYPES}/{}.glb", p.kind);
    if !exists(&base) {
        warn_once(format!("compose: no type file {base}; {} is drawn from {}", recipe.name, recipe.base));
        return (recipe.clone(), None);
    }
    let mut worn = Vec::new();
    let hair = p.styles.hair.iter().map(|h| (format!("{STYLES}/hair/{h}.glb"), None, true, false));
    let outfit = p.styles.outfit.iter().map(|o| (format!("{STYLES}/outfit/{o}.glb"), Some(o.clone()), HEAD_PIECES.contains(&o.as_str()), false));
    // An overlay is drawn on its own type's face: no fit, the type's own bind matrices.
    let overlays = p.styles.overlays.iter().map(|o| (format!("{STYLES}/overlay/{}/{o}.glb", p.kind), None, false, true));
    for (file, slot, fitted, overlay) in hair.chain(outfit).chain(overlays) {
        if !exists(&file) {
            warn_once(format!("compose: no style file {file} ({})", recipe.name));
            continue;
        }
        let handle = super::kept(assets, &file);
        worn.push(Wear { file, slot, fitted, overlay, handle });
    }
    let composed = Recipe {
        name: recipe.name.clone(),
        base,
        height: p.height,
        proportions: p.proportions.clone(),
        colors: p.colors.clone(),
        outfit: BTreeMap::new(),
        identity: p.identity.clone(),
        person: recipe.person.clone(),
    };
    (composed, Some(Styled { worn }))
}

/// A type's `hair_fit` (its scene's extras: column-major, the standard skull onto the type's);
/// identity for a file without one (the standard head itself).
pub fn hair_fit(type_file: &str) -> Mat4 {
    static CACHE: OnceLock<Mutex<HashMap<String, Mat4>>> = OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    if let Some(m) = cache.lock().unwrap().get(type_file) {
        return *m;
    }
    let m = (|| {
        let j = glb_json(type_file)?;
        let scene = j["scene"].as_u64().unwrap_or(0) as usize;
        let cols: Vec<f32> = j["scenes"][scene]["extras"]["hair_fit"]["matrix"].as_array()?.iter().filter_map(|v| v.as_f64().map(|x| x as f32)).collect();
        (cols.len() == 16).then(|| Mat4::from_cols_slice(&cols))
    })();
    if m.is_none() {
        warn_once(format!("compose: {type_file} has no hair_fit; styles sit as on the standard head"));
    }
    let m = m.unwrap_or(Mat4::IDENTITY);
    cache.lock().unwrap().insert(type_file.to_string(), m);
    m
}

/// The figure a composed character stands as, in file units: the vertical span of the type's
/// meshes and every worn file's (accessor bounds through the node transforms, `Far*` left out),
/// fitted files through `hair_fit`. What `lookdev::figure_height` is for a whole file.
pub fn figure_height(type_file: &str, styled: &Styled) -> Option<f32> {
    let fit = hair_fit(type_file);
    let mut range: Option<(f32, f32)> = None;
    let mut add = |file: &str, m: Mat4| {
        for c in crate::lookdev::figure_corners(file).iter() {
            let y = m.transform_point3(*c).y;
            range = Some(range.map_or((y, y), |(lo, hi)| (lo.min(y), hi.max(y))));
        }
    };
    add(type_file, Mat4::IDENTITY);
    for w in &styled.worn {
        add(&w.file, if w.fitted { fit } else { Mat4::IDENTITY });
    }
    range.and_then(|(lo, hi)| (hi > lo).then_some(hi - lo))
}

/// Whether a style material is a face's skin, so lit by the shadow map beside its file when it
/// has one (`…Face…_SKIN`). Lines and freckles were (`…FaceOverlay_00_SKIN`); since char-4's
/// fixed-colour layer they are `…FaceOverlay_00_FACE` and are not.
fn wants_face_map(name: &str) -> bool {
    (name.ends_with("_SKIN") || name.contains("Skin")) && name.contains("Face")
}

/// How a style material is shaded, by its name, as `lookdev::convert` shades a character's own:
/// hair (a beard and stubble too, `…Overlay_00_HAIR`) as hair; a face's skin with its shadow map
/// as a face, else skin as skin; `…_FACE` and `…_EYE` as face parts, unshaded and in the file's
/// own colours (lips and blush, `…FaceTint_00_FACE`; lines and freckles,
/// `…FaceOverlay_00_FACE`); everything else plain. Which are tinted is `recolor`'s, by the same
/// names: no `…_FACE` material takes a tag.
fn kind_of(name: &str, face_map: bool) -> Kind {
    let skin = name.ends_with("_SKIN") || name.contains("Skin");
    match () {
        _ if name.contains("_HAIR") => Kind::Hair,
        _ if face_map && skin => Kind::Face,
        _ if skin => Kind::Skin,
        _ if name.contains("_FACE") || name.contains("_EYE") => Kind::FacePart,
        _ => Kind::Plain,
    }
}

/// What a style file brings to a type's person, worked out once per type and file.
struct Plan {
    /// Bones only the style has: name, parent's name, local transform (parents first).
    bones: Vec<(String, String, Transform)>,
    meshes: Vec<PlanMesh>,
}

struct PlanMesh {
    /// The node's name (`Hair`, `FarHair`, `Cloth`, `FarCloth`): `Far*` is the far model.
    node: String,
    joints: Vec<String>,
    bindposes: Handle<SkinnedMeshInverseBindposes>,
    /// Mesh, material name, toon material.
    prims: Vec<(Handle<Mesh>, String, Handle<Toon>)>,
    /// Its morph targets' count and, when they are the face's, the blink's and the open mouth's
    /// indices (an overlay's).
    morphs: Option<(usize, Option<crate::lookdev::FaceMorphs>)>,
}

/// Plans by (type file, style file, fitted); toon materials by what they draw (`toons`: content
/// and source colour) and the one each style file's material takes (`file_toons`). Both hold
/// their assets for the session: a few dozen files serve any number of people.
#[derive(Resource, Default)]
pub struct Plans {
    plans: HashMap<(String, String, bool), Option<Arc<Plan>>>,
    /// By content: each source colour made, and its toon.
    toons: HashMap<String, Vec<(Vec3, Handle<Toon>)>>,
    file_toons: HashMap<String, Handle<Toon>>,
    /// A type's rest (bind) world matrix by joint name.
    rests: HashMap<String, Arc<HashMap<String, Mat4>>>,
    outlined: HashSet<AssetId<Mesh>>,
}

#[derive(bevy::ecs::system::SystemParam)]
pub struct Composer<'w> {
    assets: Res<'w, AssetServer>,
    gltfs: Res<'w, Assets<Gltf>>,
    nodes: Res<'w, Assets<GltfNode>>,
    skins: Res<'w, Assets<GltfSkin>>,
    gmeshes: Res<'w, Assets<GltfMesh>>,
    gmaterials: Res<'w, Assets<GltfMaterial>>,
    bindposes: ResMut<'w, Assets<SkinnedMeshInverseBindposes>>,
    toons: ResMut<'w, Assets<Toon>>,
    meshes: ResMut<'w, Assets<Mesh>>,
    style: Res<'w, Style>,
    plans: ResMut<'w, Plans>,
    thumbs: Res<'w, super::Thumbs>,
    images: Res<'w, Assets<Image>>,
    tints: ResMut<'w, HairTints>,
}

impl Composer<'_> {
    /// A skin's joints by name with their bind world matrices (the inverse of the inverse bind
    /// matrices).
    fn skin_rest(&self, skin: &Handle<GltfSkin>) -> Option<Vec<(String, Mat4)>> {
        let skin = self.skins.get(skin)?;
        let ibm = self.bindposes.get(&skin.inverse_bind_matrices)?;
        Some(skin.joints.iter().zip(ibm.iter()).map(|(j, m)| (self.nodes.get(j).map(|n| n.name.clone()).unwrap_or_default(), m.inverse())).collect())
    }

    /// The type's rest world matrix by joint name, from its first skin.
    fn type_rest(&mut self, type_file: &str, type_gltf: &Handle<Gltf>) -> Option<Arc<HashMap<String, Mat4>>> {
        if let Some(r) = self.plans.rests.get(type_file) {
            return Some(r.clone());
        }
        let skin = self.gltfs.get(type_gltf)?.skins.first()?.clone();
        let rest: HashMap<String, Mat4> = self.skin_rest(&skin)?.into_iter().collect();
        let rest = Arc::new(rest);
        self.plans.rests.insert(type_file.to_string(), rest.clone());
        Some(rest)
    }

    /// The toon a style file's material takes: one already made that draws the same (the same
    /// content and source colour), else a new one. `sources` are the file's meshes in it.
    fn toon(&mut self, file: &str, name: &str, material: Option<&Handle<GltfMaterial>>, sources: &[Handle<Mesh>]) -> Handle<Toon> {
        let own = format!("{file}#{name}");
        if let Some(h) = self.plans.file_toons.get(&own) {
            return h.clone();
        }
        let gm = material.and_then(|m| self.gmaterials.get(m)).cloned().unwrap_or_default();
        let base = bevy::pbr::gltf::standard_material_from_gltf_material(&gm);
        // As `lookdev::convert` gives a character's meshes by material name: hair as hair; a
        // face's skin (an overlay's lines and freckles) as a face, with the shadow map beside its
        // file, else as skin; eyes and lines as face parts; clothes plain.
        let map = format!("{}.face.png", file.trim_end_matches(".glb"));
        let face_map = wants_face_map(name).then_some(map).filter(|m| exists(m));
        let face = face_map.clone().map(|m| self.assets.load_builder().with_settings(|s: &mut bevy::image::ImageLoaderSettings| s.is_srgb = false).load(m));
        let kind = kind_of(name, face.is_some());
        // The source colour the recolour moves to a person's: over the file's meshes in this
        // material. Without it (a picture not yet readable) the material is the file's own and
        // `recolor` finds it from the first mesh, as for any character.
        let meshes: Vec<&Mesh> = sources.iter().filter_map(|m| self.meshes.get(m)).collect();
        let source = super::source_mean(&base, &meshes, &self.thumbs, &self.images);
        let content = format!("{kind:?} {face_map:?} {base:?}");
        let shared = source.filter(|_| !crate::perf::has("filestyles")).and_then(|src| {
            self.plans.toons.get(&content)?.iter().find(|(m, _)| (*m - src).abs().max_element() < SAME_SOURCE).map(|(_, h)| h.clone())
        });
        let h = match shared {
            Some(h) => h,
            None => {
                let mut toon = self.style.kind(base, kind, face);
                if let Some((recolor, from)) = source.map(super::recolor_source) {
                    toon.extension.params.recolor = recolor;
                    toon.extension.params.recolor_from = from;
                }
                // Hair greys lock by lock from the shared palette.
                let hair = matches!(kind, Kind::Hair) && !name.contains("Overlay");
                if hair {
                    toon.extension.tints = Some(self.tints.image.clone());
                }
                let h = self.toons.add(toon);
                if hair {
                    self.tints.users.push(h.id());
                }
                if let Some(src) = source {
                    self.plans.toons.entry(content).or_default().push((src, h.clone()));
                }
                h
            }
        };
        debug!("compose: material {own} takes toon {:?} (source {:?})", h.id(), source.map(|m| m.to_array()));
        self.plans.file_toons.insert(own, h.clone());
        h
    }

    /// Work out what `file` brings to a person of `type_file`.
    fn plan(&mut self, type_file: &str, type_gltf: &Handle<Gltf>, wear: &Wear) -> Option<Arc<Plan>> {
        let key = (type_file.to_string(), wear.file.clone(), wear.fitted);
        if let Some(p) = self.plans.plans.get(&key) {
            return p.clone();
        }
        let plan = self.make_plan(type_file, type_gltf, wear).map(Arc::new);
        if plan.is_none() {
            warn_once(format!("compose: {} could not be put on {type_file}", wear.file));
        }
        self.plans.plans.insert(key, plan.clone());
        plan
    }

    fn make_plan(&mut self, type_file: &str, type_gltf: &Handle<Gltf>, wear: &Wear) -> Option<Plan> {
        let mut world: HashMap<String, Mat4> = (*self.type_rest(type_file, type_gltf)?).clone();
        let fit = if wear.fitted { hair_fit(type_file) } else { Mat4::IDENTITY };
        let (gnodes, materials) = {
            let g = self.gltfs.get(&wear.handle)?;
            (g.nodes.clone(), g.named_materials.clone())
        };
        // Each node's parent, by name, in the style's file.
        let mut parent: HashMap<String, String> = HashMap::new();
        for n in gnodes.iter().filter_map(|h| self.nodes.get(h)) {
            for c in n.children.iter().filter_map(|c| self.nodes.get(c)) {
                parent.insert(c.name.clone(), n.name.clone());
            }
        }
        let mut bones = Vec::new();
        let mut meshes = Vec::new();
        let mesh_nodes: Vec<GltfNode> = gnodes.iter().filter_map(|h| self.nodes.get(h)).filter(|n| n.mesh.is_some() && n.skin.is_some()).cloned().collect();
        // Each material's meshes in the file, near ones first: its source colour is theirs.
        let name_of = |h: &Handle<GltfMaterial>| materials.iter().find(|(_, m)| *m == h).map(|(n, _)| n.to_string()).unwrap_or_default();
        let mut sources: HashMap<String, (Vec<Handle<Mesh>>, Vec<Handle<Mesh>>)> = HashMap::new();
        for node in &mesh_nodes {
            let Some(gmesh) = node.mesh.as_ref().and_then(|m| self.gmeshes.get(m)) else { continue };
            for p in &gmesh.primitives {
                let e = sources.entry(p.material.as_ref().map(name_of).unwrap_or_default()).or_default();
                if node.name.starts_with("Far") { e.1.push(p.mesh.clone()) } else { e.0.push(p.mesh.clone()) }
            }
        }
        for node in mesh_nodes {
            let rest = self.skin_rest(node.skin.as_ref()?)?;
            let style_rest: HashMap<&str, Mat4> = rest.iter().map(|(n, m)| (n.as_str(), *m)).collect();
            // Joints by name; the style's own bones go under the person's, at hair_fit × their
            // rest in the style's file (compose.py `place`).
            fn place(name: &str, world: &mut HashMap<String, Mat4>, bones: &mut Vec<(String, String, Transform)>, parent: &HashMap<String, String>, style_rest: &HashMap<&str, Mat4>, fit: Mat4, depth: u32) -> bool {
                if world.contains_key(name) {
                    return true;
                }
                let (Some(up), Some(r)) = (parent.get(name), style_rest.get(name)) else { return false };
                if depth > 64 || !place(up, world, bones, parent, style_rest, fit, depth + 1) {
                    return false;
                }
                let w = fit * *r;
                let local = world[up].inverse() * w;
                world.insert(name.to_string(), w);
                bones.push((name.to_string(), up.clone(), Transform::from_matrix(local)));
                true
            }
            let mut joints = Vec::new();
            let mut ibm = Vec::new();
            for (name, _) in &rest {
                if !place(name, &mut world, &mut bones, &parent, &style_rest, fit, 0) {
                    warn_once(format!("compose: {}: joint {name} is neither the type's nor below one", wear.file));
                }
                // The joint's inverse bind matrix: the inverse of its rest on the person, times
                // hair_fit, so a vertex stands at hair_fit × its place in the style's file.
                ibm.push(world.get(name).map_or(Mat4::IDENTITY, |w| w.inverse() * fit));
                joints.push(name.clone());
            }
            let bindposes = self.bindposes.add(SkinnedMeshInverseBindposes::from(ibm));
            let gmesh = self.gmeshes.get(node.mesh.as_ref()?)?.clone();
            let mut prims = Vec::new();
            for p in &gmesh.primitives {
                let mname = p.material.as_ref().map(name_of).unwrap_or_default();
                let own = sources.get(&mname).map(|(near, far)| if near.is_empty() { far.clone() } else { near.clone() }).unwrap_or_default();
                let toon = self.toon(&wear.file, &mname, p.material.as_ref(), &own);
                if self.plans.outlined.insert(p.mesh.id()) {
                    if let Some(mut m) = self.meshes.get_mut(&p.mesh) {
                        crate::style::outline_normals(&mut m);
                        // A hair mesh's greying into its second UVs ([`ATTRIBUTE_GREY`]).
                        if let Some(bevy::mesh::VertexAttributeValues::Float32(g)) = m.remove_attribute(ATTRIBUTE_GREY) {
                            let uv: Vec<[f32; 2]> = g.iter().map(|v| [*v, 0.0]).collect();
                            m.insert_attribute(Mesh::ATTRIBUTE_UV_1, uv);
                        }
                    }
                }
                prims.push((p.mesh.clone(), mname, toon));
            }
            let morphs = morph_targets(&wear.file, &node.name).map(|t| {
                let find = |suffix: &str| t.iter().position(|n| n.ends_with(suffix));
                let face = find("Fcl_EYE_Close").zip(find("Fcl_MTH_A")).map(|(blink, mouth)| crate::lookdev::FaceMorphs { blink, mouth });
                (t.len(), face)
            });
            meshes.push(PlanMesh { node: node.name.clone(), joints, bindposes, prims, morphs });
        }
        debug!("compose: {} on {type_file}: {} meshes, {} bones of its own", wear.file, meshes.len(), bones.len());
        Some(Plan { bones, meshes })
    }
}

/// When a composed character's scene comes in (first or again), put its style files on the new
/// scene's bones, before it is first fitted: its height is measured over them. A scene spawned
/// again lets go of the old ones in `characters::on_ready` ([`Worn`]).
#[allow(clippy::type_complexity)]
pub fn on_ready(
    ev: On<bevy::world_serialization::WorldInstanceReady>,
    mut commands: Commands,
    chars: Query<(&super::Character, &crate::lookdev::Model, &Styled, &super::SceneOf)>,
    children: Query<&Children>,
    names: Query<&Name>,
    worn: Query<(), Or<(With<Worn>, With<super::outfit::Piece>)>>,
    mut composer: Composer,
) {
    let e = ev.entity;
    let Ok((ch, model, styled, scene)) = chars.get(e) else { return };
    let bones: HashMap<String, Entity> = children.iter_descendants(e).filter(|d| !worn.contains(*d)).filter_map(|d| names.get(d).ok().map(|n| (n.as_str().to_string(), d))).collect();
    attach(&mut composer, &mut commands, e, &model.file, &scene.0, styled, &bones, &ch.recipe.name);
    // The belly: J_Fit_Belly forward from its rest (`shape` keeps it under the spine's girth).
    let belly = belly_offset(&ch.recipe, true);
    if belly != Vec3::ZERO {
        if let Some(&b) = bones.get("J_Fit_Belly") {
            let rest = super::rest_of(&model.file, "J_Fit_Belly");
            commands.entity(b).insert(Transform::from_translation(rest + belly));
        }
    }
}

/// A node's morph target names in a style file (its mesh's extras, else its first primitive's).
fn morph_targets(file: &str, node: &str) -> Option<Vec<String>> {
    let j = glb_json(file)?;
    let mesh = j["nodes"].as_array()?.iter().find(|n| n["name"] == node)?["mesh"].as_u64()? as usize;
    let m = &j["meshes"][mesh];
    let names = if m["extras"]["targetNames"].is_array() { &m["extras"]["targetNames"] } else { &m["primitives"][0]["extras"]["targetNames"] };
    let names: Vec<String> = names.as_array()?.iter().filter_map(|v| v.as_str().map(String::from)).collect();
    (!names.is_empty()).then_some(names)
}

/// Put a composed character's style files on its scene's bones ([`on_ready`]). `bones` are the
/// scene's nodes by name. Returns how many meshes were attached.
#[allow(clippy::too_many_arguments)]
pub fn attach(c: &mut Composer, commands: &mut Commands, e: Entity, type_file: &str, type_gltf: &Handle<Gltf>, styled: &Styled, bones: &HashMap<String, Entity>, name: &str) -> usize {
    let mut bones = bones.clone();
    let Some(&hips) = bones.get("J_Bip_C_Hips") else {
        warn_once(format!("compose: {type_file} has no J_Bip_C_Hips; {name} wears nothing"));
        return 0;
    };
    let mut n = 0;
    for wear in &styled.worn {
        if c.gltfs.get(&wear.handle).is_none() {
            warn_once(format!("compose: {} did not load", wear.file));
            continue;
        }
        let Some(plan) = c.plan(type_file, type_gltf, wear) else { continue };
        for (bone, up, tf) in &plan.bones {
            if bones.contains_key(bone) {
                continue;
            }
            let Some(&p) = bones.get(up) else { continue };
            let b = commands.spawn((Name::new(bone.clone()), *tf, Worn, ChildOf(p))).id();
            bones.insert(bone.clone(), b);
        }
        for m in &plan.meshes {
            let joints: Vec<Entity> = m.joints.iter().map(|j| bones.get(j).copied().unwrap_or(hips)).collect();
            // A mesh with morph targets: the first primitive holds the weights, every one reads
            // them (as Bevy's loader does with the node).
            let mut weights: Option<Entity> = None;
            for (mesh, material, toon) in &m.prims {
                let mut ec = commands.spawn((
                    Name::new(m.node.clone()),
                    Mesh3d(mesh.clone()),
                    MeshMaterial3d(toon.clone()),
                    SkinnedMesh { inverse_bindposes: m.bindposes.clone(), joints: joints.clone() },
                    DynamicSkinnedMeshBounds,
                    GltfMaterialName(material.clone()),
                    Transform::IDENTITY,
                    Visibility::default(),
                    Converted,
                    outline(Outlined::Person, &c.style),
                    Worn,
                    ChildOf(e),
                ));
                if let Some(slot) = &wear.slot {
                    ec.insert(super::outfit::Piece { slot: slot.clone(), material: material.clone() });
                }
                if wear.overlay {
                    ec.insert((bevy::light::NotShadowCaster, crate::lookdev::FacePart));
                }
                if let Some((count, face)) = m.morphs {
                    let id = ec.id();
                    let owner = *weights.get_or_insert(id);
                    if owner == id {
                        if let Ok(w) = bevy::mesh::morph::MorphWeights::new(vec![0.0; count], Some(mesh.clone())) {
                            ec.insert(w);
                        }
                        if let Some(f) = face {
                            ec.insert(f);
                        }
                    }
                    ec.insert(bevy::mesh::morph::MeshMorphWeights::Reference(owner));
                }
                n += 1;
            }
        }
    }
    debug!("compose: {name} wears {} on {type_file}: {n} meshes", styled.worn.iter().map(|w| w.file.rsplit('/').next().unwrap_or_default()).collect::<Vec<_>>().join(", "));
    n
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_person_line_reads_as_the_generator_writes_it() {
        let line = r##"{"type": "adult-f-a", "height": 1.62, "proportions": {"head": 1.0, "shoulders": 0.895, "build": 0.973},
            "identity": {"jaw_width": -0.292}, "colors": {"skin": "#e6b89c", "hair": "#4a2a1a", "outfit": {"smock_58-f": "#5d7f9a"}},
            "styles": {"hair": "bob", "outfit": ["smock_58-f", "apron_58-f", "jersey_smock-f", "trousers-f", "boots-f"], "overlays": ["lines", "freckles"]}, "belly": 0.12}"##;
        let p: Person = serde_json::from_str(line).unwrap();
        assert_eq!(p.kind, "adult-f-a");
        assert_eq!(p.proportions.build, 0.973);
        assert_eq!(p.proportions.legs, 1.0);
        assert_eq!(p.colors.outfit.get("smock_58-f").map(String::as_str), Some("#5d7f9a"));
        assert_eq!(p.styles.outfit.len(), 5);
        assert_eq!(p.styles.overlays, ["lines", "freckles"]);
        assert_eq!(p.belly, 0.12);
        assert_eq!(p.styles.hair.as_deref(), Some("bob"));
    }

    /// The greying palette keeps each colour once a row, writes its texel, and refuses a
    /// 257th colour (that person keeps the one tint).
    #[test]
    fn the_greying_palette_holds_each_colour_once() {
        let mut world = World::new();
        world.init_resource::<Assets<Image>>();
        let mut tints = HairTints::from_world(&mut world);
        let mut images = world.resource_mut::<Assets<Image>>();
        assert_eq!(tints.place(0, [74, 42, 26], &mut images), Some(0));
        assert_eq!(tints.place(1, [199, 199, 194], &mut images), Some(0));
        assert_eq!(tints.place(0, [51, 34, 23], &mut images), Some(1));
        assert_eq!(tints.place(0, [74, 42, 26], &mut images), Some(0));
        let data = images.get(&tints.image).unwrap().data.clone().unwrap();
        assert_eq!(&data[4..8], &[51, 34, 23, 255]);
        assert_eq!(&data[256 * 4..256 * 4 + 4], &[199, 199, 194, 255]);
        for i in 2..256u32 {
            assert!(tints.place(0, [i as u8, (i >> 8) as u8, 1], &mut images).is_some());
        }
        assert_eq!(tints.place(0, [9, 9, 9], &mut images), None);
    }

    /// Lines and freckles are a fixed-colour face part, untagged, without a shadow map; a beard is
    /// hair and takes the beard's colour (docs/CHARACTERS.md, "Overlay styles", and char-4's
    /// fixed-colour lines and freckles).
    #[test]
    fn lines_and_freckles_are_drawn_in_their_own_colours() {
        let lines = "M00_000_00_FaceOverlay_00_FACE";
        assert!(!wants_face_map(lines));
        assert!(matches!(kind_of(lines, false), Kind::FacePart));
        assert!(matches!(kind_of("M00_000_00_FaceTint_00_FACE", false), Kind::FacePart));
        assert!(matches!(kind_of("M00_000_00_Overlay_00_HAIR", false), Kind::Hair));
        assert!(matches!(kind_of("M00_000_00_FarOverlay_00_HAIR", false), Kind::Hair));
        // The old skin-tinted layer, for files before the change.
        assert!(wants_face_map("M00_000_00_FaceOverlay_00_SKIN"));
        assert!(matches!(kind_of("M00_000_00_FaceOverlay_00_SKIN", true), Kind::Face));
        let colors = Colors { skin: Some("#e8bca3".into()), hair: Some("#332217".into()), beard: Some("#c7c7c2".into()), ..Default::default() };
        assert_eq!(super::super::slot(lines, &colors), None);
        assert_eq!(super::super::slot("M00_000_00_FaceTint_00_FACE", &colors), None);
        assert_eq!(super::super::slot("M00_000_00_Overlay_00_HAIR", &colors).map(String::as_str), Some("#c7c7c2"));
        assert_eq!(super::super::slot("M00_000_00_FarOverlay_00_HAIR", &colors).map(String::as_str), Some("#c7c7c2"));
    }

    /// compose.py `attach_hair`: a spring bone's inverse bind matrix is its own in the style's
    /// file (the fit cancels), and a vertex on any joint lands at hair_fit × where it was.
    #[test]
    fn hair_fit_lays_a_vertex_where_the_rule_puts_it() {
        let fit = Mat4::from_scale_rotation_translation(Vec3::new(0.959, 0.985, 0.962), Quat::IDENTITY, Vec3::new(0.0, 0.0242, 0.0008));
        let cranium = Mat4::from_translation(Vec3::new(0.0, 1.62, 0.01));
        let spring_rest = Mat4::from_translation(Vec3::new(-0.1, 1.64, -0.05));
        let v = Vec3::new(-0.09, 1.6, -0.06);
        // On a type joint, at rest: joint world × (rest⁻¹ × fit) = fit.
        let ibm = cranium.inverse() * fit;
        assert!((cranium * ibm).transform_point3(v).distance(fit.transform_point3(v)) < 1e-6);
        // A spring bone placed at fit × its rest under the cranium.
        let local = cranium.inverse() * (fit * spring_rest);
        let world = cranium * Transform::from_matrix(local).to_matrix();
        let ibm = (fit * spring_rest).inverse() * fit;
        assert!((world * ibm).transform_point3(v).distance(fit.transform_point3(v)) < 1e-6);
    }
}
