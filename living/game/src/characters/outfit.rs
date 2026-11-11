//! Outfit pieces worn over a character's own clothes: coats, hats, boots, visors… made per VRoid
//! base by `living/tools/blender/outfits.py` into `assets/lookdev/outfits/` (git-ignored), with
//! `outfits.json` listing each piece's style, slot, layer, bones and the base clothes it covers.
//!
//! **Attaching.** A piece's GLB holds the base's whole armature and one mesh skinned to its
//! `J_Bip_*` bones, at the base's rest pose (the file's `rest` check). Only the mesh is used: each
//! primitive becomes an entity under the character's root with a [`SkinnedMesh`] whose joints are
//! the character's own bone entities, found by `Name`, or the recipe's helper scale joints where
//! [`super::shape`] put them in a bone's place. The piece's inverse bind matrices are the base's,
//! so it follows the animation, the proportions (bone and helper scales) and the height like the
//! body's own meshes. Joints a piece lists but the character lacks fall back to the hips (they
//! carry no weight: `outfits.py` moves spring-bone weights to their `J_Bip` ancestor). Pieces go
//! on after the character is shaped (so the fitted height ignores hats) and its helpers exist.
//!
//! **Look.** Pieces get the same treatment as the body: the toon material, shell outlines, shadow
//! casting by distance (`lookdev::character_shadows`) and recolouring through the mesh tag
//! (`recolor`). A piece's colour is per vertex on a white `Outfit` material; its toon material is
//! one per piece file, so its mean (vertex) colour is the piece's own and a recipe colour moves
//! exactly that piece to it. Materials stay shared across the crowd: one per piece file in view,
//! whatever the number of wearers. Glowing materials (`Glow…`) keep their colour and are shared
//! by content.
//!
//! **Covered clothes.** A piece in the recipe book's `hides` list hides the base clothes it
//! covers (`covers` in `outfits.json`: `Tops`, `Bottoms`, `Shoes`), so they can't poke through.

use super::{Character, Shaped};
use crate::lookdev::{CastsShadow, Converted};
use crate::style::{outline, Outlined, Style, Toon};
use bevy::camera::visibility::DynamicSkinnedMeshBounds;
use bevy::gltf::{Gltf, GltfMaterial, GltfMaterialName, GltfMesh, GltfNode, GltfSkin};
use bevy::mesh::skinning::SkinnedMesh;
use bevy::prelude::*;
use bevy_mod_outline::OutlineMeshExt;
use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

/// The piece list, under the asset folder.
pub const FILE: &str = "lookdev/outfits/outfits.json";
const FOLDER: &str = "lookdev/outfits";

/// One piece for one base, from `outfits.json`.
#[derive(Deserialize, Clone, Debug)]
pub struct PieceDef {
    pub piece: String,
    /// The base's file stem (`vroid-Vivi`).
    pub base: String,
    /// Under the outfits folder.
    pub file: String,
    pub slot: String,
    /// Base material groups it covers (`Tops`, `Bottoms`, `Shoes`).
    #[serde(default)]
    pub covers: Vec<String>,
}

#[derive(Deserialize, Default)]
struct Catalog {
    pieces: Vec<PieceDef>,
}

fn catalog() -> &'static [PieceDef] {
    static CATALOG: OnceLock<Catalog> = OnceLock::new();
    &CATALOG
        .get_or_init(|| {
            let path = std::path::Path::new(&crate::lookdev::asset_root()).join(FILE);
            match std::fs::read_to_string(&path).map_err(|e| e.to_string()).and_then(|s| serde_json::from_str::<Catalog>(&s).map_err(|e| e.to_string())) {
                Ok(c) => c,
                Err(e) => {
                    warn!("outfits: {}: {e}", path.display());
                    Catalog::default()
                }
            }
        })
        .pieces
}

/// Every piece in the catalogue.
pub fn all() -> &'static [PieceDef] {
    catalog()
}

/// A piece made for a base file (`lookdev/vroid-Vivi.glb`), if there is one.
pub fn piece_for(base: &str, piece: &str) -> Option<&'static PieceDef> {
    let stem = std::path::Path::new(base).file_stem()?.to_str()?;
    catalog().iter().find(|p| p.base == stem && p.piece == piece)
}

/// On each mesh of a worn piece: the slot whose recipe colour it takes, and its material.
#[derive(Component)]
pub struct Piece {
    pub slot: String,
    pub material: String,
}

impl Piece {
    /// Glowing materials keep their colour.
    pub fn recolors(&self) -> bool {
        !self.material.starts_with("Glow")
    }
}

/// On a character whose outfit is on (or who wears none).
#[derive(Component)]
pub struct Dressed;

/// A loaded piece file, ready to put on: its mesh primitives (mesh, material name, toon
/// material's key and source), its skin and the skin's joint names.
struct Ready {
    prims: Vec<(Handle<Mesh>, String, String, StandardMaterial)>,
    bindposes: Handle<bevy::mesh::skinning::SkinnedMeshInverseBindposes>,
    joints: Vec<String>,
}

#[derive(Default)]
pub struct Wardrobe {
    loading: HashMap<String, Handle<Gltf>>,
    ready: HashMap<String, Option<std::sync::Arc<Ready>>>,
    /// Toon materials: per piece file for recoloured ones, by content for glowing ones. Ids, not
    /// handles: a material lives while someone wears it, and is made again for the next wearer
    /// (the first load's prewarm leaves none behind, `loading.rs`).
    toons: HashMap<String, AssetId<Toon>>,
}

#[derive(bevy::ecs::system::SystemParam)]
pub struct GltfAssets<'w> {
    gltfs: Res<'w, Assets<Gltf>>,
    meshes: Res<'w, Assets<GltfMesh>>,
    nodes: Res<'w, Assets<GltfNode>>,
    skins: Res<'w, Assets<GltfSkin>>,
    materials: Res<'w, Assets<GltfMaterial>>,
}

impl Wardrobe {
    /// The piece file once it and everything in it has loaded; `Some(None)` if it can't be used.
    /// A piece's toon material, shared by everyone wearing it.
    fn toon(&mut self, key: &str, base: &StandardMaterial, toons: &mut Assets<Toon>, style: &Style) -> Handle<Toon> {
        if let Some(h) = self.toons.get(key).and_then(|id| toons.get_strong_handle(*id)) {
            return h;
        }
        let h = toons.add(style.toon(base.clone()));
        self.toons.insert(key.to_string(), h.id());
        h
    }

    fn get(&mut self, file: &str, assets: &AssetServer, g: &GltfAssets, meshes: &mut Assets<Mesh>) -> Option<Option<std::sync::Arc<Ready>>> {
        if let Some(r) = self.ready.get(file) {
            return Some(r.clone());
        }
        let handle = self.loading.entry(file.to_string()).or_insert_with(|| assets.load(format!("{FOLDER}/{file}"))).clone();
        match assets.recursive_dependency_load_state(&handle) {
            bevy::asset::RecursiveDependencyLoadState::Loaded => {}
            bevy::asset::RecursiveDependencyLoadState::Failed(e) => {
                warn!("outfits: {file}: {e}");
                self.ready.insert(file.to_string(), None);
                return Some(None);
            }
            _ => return None,
        }
        let ready = (|| {
            let gltf = g.gltfs.get(&handle)?;
            let node = gltf.nodes.iter().filter_map(|n| g.nodes.get(n)).find(|n| n.mesh.is_some() && n.skin.is_some())?;
            let skin = g.skins.get(node.skin.as_ref()?)?;
            let mesh = g.meshes.get(node.mesh.as_ref()?)?;
            let joints = skin.joints.iter().map(|j| g.nodes.get(j).map(|n| n.name.clone()).unwrap_or_default()).collect();
            let name_of = |h: &Handle<GltfMaterial>| gltf.named_materials.iter().find(|(_, m)| *m == h).map(|(n, _)| n.to_string()).unwrap_or_default();
            let mut prims = Vec::new();
            for p in &mesh.primitives {
                let gm = p.material.as_ref().and_then(|m| g.materials.get(m)).cloned().unwrap_or_default();
                let name = p.material.as_ref().map(name_of).unwrap_or_default();
                let base = bevy::pbr::gltf::standard_material_from_gltf_material(&gm);
                let key = if name.starts_with("Glow") { format!("{base:?}") } else { format!("{file}#{name}") };
                if let Some(mut m) = meshes.get_mut(&p.mesh) {
                    crate::style::outline_normals(&mut m);
                }
                prims.push((p.mesh.clone(), name, key, base));
            }
            Some(std::sync::Arc::new(Ready { prims, bindposes: skin.inverse_bind_matrices.clone(), joints }))
        })();
        if ready.is_none() {
            warn!("outfits: {file} has no skinned mesh");
        }
        self.ready.insert(file.to_string(), ready.clone());
        Some(ready)
    }
}

/// Put each shaped character's outfit on, once its piece files have loaded.
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn dress(
    mut commands: Commands,
    assets: Res<AssetServer>,
    g: GltfAssets,
    mut toons: ResMut<Assets<Toon>>,
    mut meshes: ResMut<Assets<Mesh>>,
    style: Res<Style>,
    chars: Query<(Entity, &Character, &Shaped), Without<Dressed>>,
    children: Query<&Children>,
    names: Query<&Name>,
    materials: Query<&GltfMaterialName>,
    mut wardrobe: Local<Wardrobe>,
) {
    for (e, ch, shaped) in &chars {
        let r = &ch.recipe;
        let pieces: Vec<&PieceDef> = r
            .outfit
            .iter()
            .filter_map(|(slot, piece)| {
                let def = piece_for(&r.base, piece);
                if def.is_none() {
                    warn_once(&format!("outfits: no {piece} for {} ({slot})", r.base));
                }
                def
            })
            .collect();
        if pieces.is_empty() || shaped.hips.is_none() {
            commands.entity(e).insert(Dressed);
            continue;
        }
        // Wait until every piece is loaded, so a character dresses at once.
        let mut files = Vec::new();
        let mut waiting = false;
        for p in &pieces {
            match wardrobe.get(&p.file, &assets, &g, &mut meshes) {
                None => waiting = true,
                Some(Some(ready)) => files.push((*p, ready)),
                Some(None) => {}
            }
        }
        if waiting {
            continue;
        }
        let mut bones: HashMap<&str, Entity> = HashMap::new();
        for d in children.iter_descendants(e) {
            if let Ok(n) = names.get(d) {
                bones.entry(n.as_str()).or_insert(d);
            }
        }
        let Some(&hips) = bones.get("J_Bip_C_Hips") else {
            commands.entity(e).insert(Dressed);
            continue;
        };
        let joint = |name: &str| bones.get(name).map_or(hips, |b| shaped.helpers.get(b).copied().unwrap_or(*b));
        let hides = &super::book().hides;
        let mut covered: HashSet<&str> = HashSet::new();
        for (def, ready) in &files {
            if hides.iter().any(|h| *h == def.piece) {
                covered.extend(def.covers.iter().map(String::as_str));
            }
            let joints: Vec<Entity> = ready.joints.iter().map(|n| joint(n)).collect();
            for (mesh, material, key, base) in &ready.prims {
                let toon = wardrobe.toon(key, base, &mut toons, &style);
                commands.spawn((
                    Name::new(format!("outfit {}", def.piece)),
                    Mesh3d(mesh.clone()),
                    MeshMaterial3d(toon),
                    SkinnedMesh { inverse_bindposes: ready.bindposes.clone(), joints: joints.clone() },
                    DynamicSkinnedMeshBounds,
                    Transform::IDENTITY,
                    Piece { slot: def.slot.clone(), material: material.clone() },
                    Converted,
                    outline(Outlined::Thing, &style),
                    ChildOf(e),
                ));
            }
        }
        // VRoid names clothes `…_Tops_01_CLOTH`, `…_Shoes_01_CLOTH`.
        if !covered.is_empty() {
            for d in children.iter_descendants(e) {
                if materials.get(d).is_ok_and(|m| m.0.contains("_CLOTH") && covered.iter().any(|c| m.0.contains(&format!("_{c}_")))) {
                    commands.entity(d).insert(Visibility::Hidden);
                }
            }
        }
        debug!("outfits: {} wears {}", r.name, files.iter().map(|(d, _)| d.piece.as_str()).collect::<Vec<_>>().join(", "));
        // Shadows are decided again over the new meshes.
        commands.entity(e).insert((Dressed, CastsShadow::default()));
    }
}

fn warn_once(msg: &str) {
    static SEEN: OnceLock<std::sync::Mutex<HashSet<String>>> = OnceLock::new();
    if SEEN.get_or_init(Default::default).lock().unwrap().insert(msg.to_string()) {
        warn!("{msg}");
    }
}
