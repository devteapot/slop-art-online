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
//! file's own mesh assets for everyone wearing it; each file's materials become one toon
//! material a file and material name ([`Plans`]), shared the same way. Bind matrices are one
//! asset a type and file. People differ only in their bones and their mesh tags (colours), so
//! the shared meshes can batch.
//!
//! **Colours** go through the mesh tag as recipes recolour today (`recolor`, mode 3): hair by its
//! `_HAIR` material, skin by `_SKIN`, an outfit piece by its own name in the line's
//! `colors.outfit` (an [`super::outfit::Piece`] whose slot is the piece). A hair style's tie keeps
//! its own colour, as compose.py leaves it.
//!
//! **Not here yet** (char-4's next step): beards, stubble and lines (a line's `beard` is read and
//! not drawn), a separate apron (part of its smock, so one colour moves both), the eyes' colour
//! by tag (the type's iris shows), bellies and strong chests (shapes the bones cannot give).

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
}

/// The style files a person wears.
#[derive(Deserialize, Clone, Debug, PartialEq, Default)]
#[serde(default)]
pub struct Styles {
    /// `lookdev/styles/hair/<hair>.glb`.
    pub hair: Option<String>,
    /// `lookdev/styles/outfit/<piece>.glb`, each.
    pub outfit: Vec<String>,
    /// Read, not drawn: beard styles are not files yet.
    pub beard: Option<String>,
}

/// One style file a composed character wears.
pub struct Wear {
    /// Under the asset folder.
    pub file: String,
    /// The piece's name, for its colour (`colors.outfit`); none for hair.
    pub slot: Option<String>,
    /// Attached with the type's `hair_fit` (hair and head pieces).
    pub fitted: bool,
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
    if p.styles.beard.as_deref().is_some_and(|b| b != "none") {
        warn_once(format!("compose: beards are not style files yet; {}'s {} is not drawn", recipe.name, p.styles.beard.as_deref().unwrap_or_default()));
    }
    let mut worn = Vec::new();
    let hair = p.styles.hair.iter().map(|h| (format!("{STYLES}/hair/{h}.glb"), None, true));
    let outfit = p.styles.outfit.iter().map(|o| (format!("{STYLES}/outfit/{o}.glb"), Some(o.clone()), HEAD_PIECES.contains(&o.as_str())));
    for (file, slot, fitted) in hair.chain(outfit) {
        if !exists(&file) {
            warn_once(format!("compose: no style file {file} ({})", recipe.name));
            continue;
        }
        let handle = super::kept(assets, &file);
        worn.push(Wear { file, slot, fitted, handle });
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
}

/// Plans by (type file, style file, fitted); toon materials by style file and material name.
/// Both hold their assets for the session: a few dozen files serve any number of people.
#[derive(Resource, Default)]
pub struct Plans {
    plans: HashMap<(String, String, bool), Option<Arc<Plan>>>,
    toons: HashMap<String, Handle<Toon>>,
    /// A type's rest (bind) world matrix by joint name.
    rests: HashMap<String, Arc<HashMap<String, Mat4>>>,
    outlined: HashSet<AssetId<Mesh>>,
}

#[derive(bevy::ecs::system::SystemParam)]
pub struct Composer<'w> {
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

    fn toon(&mut self, file: &str, name: &str, material: Option<&Handle<GltfMaterial>>) -> Handle<Toon> {
        let gm = material.and_then(|m| self.gmaterials.get(m)).cloned().unwrap_or_default();
        let base = bevy::pbr::gltf::standard_material_from_gltf_material(&gm);
        // As `lookdev::convert` gives a character's meshes: hair shades as hair; clothes plain.
        let kind = if name.contains("_HAIR") { Kind::Hair } else { Kind::Plain };
        // One material a file and material name: recolouring keeps each material's mean colour,
        // and every piece's differs. `LIVING_GAME_PERF=sharestyles` shares one material between
        // files whose materials are the same (measurement only: every piece then recolours
        // from the first piece's mean, so colours are wrong).
        let key = if crate::perf::has("sharestyles") { format!("{kind:?} {base:?}") } else { format!("{file}#{name}") };
        if let Some(h) = self.plans.toons.get(&key) {
            return h.clone();
        }
        let h = self.toons.add(self.style.kind(base, kind, None));
        self.plans.toons.insert(key, h.clone());
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
            let name_of = |h: &Handle<GltfMaterial>| materials.iter().find(|(_, m)| *m == h).map(|(n, _)| n.to_string()).unwrap_or_default();
            let mut prims = Vec::new();
            for p in &gmesh.primitives {
                let mname = p.material.as_ref().map(name_of).unwrap_or_default();
                let toon = self.toon(&wear.file, &mname, p.material.as_ref());
                if self.plans.outlined.insert(p.mesh.id()) {
                    if let Some(mut m) = self.meshes.get_mut(&p.mesh) {
                        crate::style::outline_normals(&mut m);
                    }
                }
                prims.push((p.mesh.clone(), mname, toon));
            }
            meshes.push(PlanMesh { node: node.name.clone(), joints, bindposes, prims });
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
            "styles": {"hair": "bob", "outfit": ["smock_58-f", "jersey_smock-f", "trousers-f", "boots-f"], "beard": "none"}}"##;
        let p: Person = serde_json::from_str(line).unwrap();
        assert_eq!(p.kind, "adult-f-a");
        assert_eq!(p.proportions.build, 0.973);
        assert_eq!(p.proportions.legs, 1.0);
        assert_eq!(p.colors.outfit.get("smock_58-f").map(String::as_str), Some("#5d7f9a"));
        assert_eq!(p.styles.outfit.len(), 4);
        assert_eq!(p.styles.hair.as_deref(), Some("bob"));
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
