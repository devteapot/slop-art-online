//! Composed people's meshes without their CPU copies (looks-mesh-1). A type's or a style's mesh
//! is read on the CPU a few times after it loads, and then only for the same few facts: so each
//! one's facts are recorded once, when the client has finished changing it, and its data then goes
//! to the GPU alone (`RenderAssetUsages::RENDER_WORLD`): Bevy takes the vertices, indices and morph
//! targets out of the main world at the next extraction (`Mesh::take_gpu_data`) and keeps the
//! bounds (`final_aabb`).
//!
//! The readers, and what they read here instead of the mesh:
//!
//! - `characters::recolor` (`mean_color`): the thumb cells its first UVs sample, in order, and its
//!   vertex colours by area; `grey_tag`: whether it has second UVs (a hair mesh's greying). Read
//!   again whenever a material is made again (a type's toons go with their last wearer).
//! - `compose`'s style toons (`source_mean`): vertex colours by area.
//! - `lookdev::fit`: its morph target names (a face's blink and mouth).
//! - the `views:` diag: its triangles.
//! - Bevy's `calculate_bounds`: needs nothing (`Mesh::get_aabb` gives `final_aabb` once the data
//!   is taken); skinned bounds come from `skinned_mesh_bounds`, made at load.
//!
//! When: a type mesh after `lookdev::convert` gives it its outline directions; a style mesh after
//! `compose`'s first plan with it gives it outline directions and moves its greying into its
//! second UVs. A mesh changed later would panic (Bevy's accessors `expect` the data), so nothing
//! changes them after. `LIVING_GAME_PERF=keepmeshes` keeps every copy (to measure), and the asset
//! view keeps them for its report.

use bevy::asset::RenderAssetUsages;
use bevy::mesh::VertexAttributeValues as V;
use bevy::prelude::*;
use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

/// What the client reads of a composed mesh after it is made.
#[derive(Debug, Clone, PartialEq)]
pub struct Facts {
    pub tris: usize,
    /// Second UVs (a hair mesh's greying and ring, `compose`).
    pub uv1: bool,
    /// The summary cell (`Thumb`) under each sampled first-UV vertex, in `mean_color`'s order.
    pub uv_cells: Option<Vec<u16>>,
    /// Vertex colours summed by triangle area, and the area (`vertex_sum`).
    pub vertex_sum: Option<(Vec3, f32)>,
    pub morph_names: Option<Vec<String>>,
}

#[derive(Default)]
struct Store {
    facts: HashMap<AssetId<Mesh>, Arc<Facts>>,
    queue: Vec<AssetId<Mesh>>,
    dropped: usize,
}

fn store() -> std::sync::MutexGuard<'static, Store> {
    static S: OnceLock<Mutex<Store>> = OnceLock::new();
    S.get_or_init(Default::default).lock().unwrap()
}

/// Whether composed meshes give up their CPU copies (not in the asset view, nor with
/// `LIVING_GAME_PERF=keepmeshes`).
pub fn enabled() -> bool {
    static ON: OnceLock<bool> = OnceLock::new();
    *ON.get_or_init(|| !crate::view::enabled() && !crate::perf::has("keepmeshes"))
}

/// A composed person's file: a type's or a style's.
pub fn composed(file: &str) -> bool {
    file.starts_with("lookdev/types/") || file.starts_with("lookdev/styles/")
}

/// Whether a mesh's data is still in the main world.
fn readable(m: &Mesh) -> bool {
    m.try_indices_option().is_ok()
}

/// The facts of a mesh whose data is here; None once it has gone.
pub fn compute(m: &Mesh) -> Option<Facts> {
    if !readable(m) {
        return None;
    }
    let tris = m.indices().map_or_else(|| m.count_vertices(), |i| i.len()) / 3;
    let uv_cells = match m.attribute(Mesh::ATTRIBUTE_UV_0) {
        Some(V::Float32x2(uvs)) => {
            let step = (uvs.len() / 4000).max(1);
            Some(uvs.iter().step_by(step).map(|uv| super::Thumb::cell(uv[0], uv[1]) as u16).collect())
        }
        _ => None,
    };
    Some(Facts {
        tris,
        uv1: m.contains_attribute(Mesh::ATTRIBUTE_UV_1),
        uv_cells,
        vertex_sum: super::vertex_sum(m),
        morph_names: m.morph_target_names().map(|t| t.to_vec()),
    })
}

/// A mesh's facts: those recorded when its copy was given up, else from its data while it is here.
pub fn of(id: AssetId<Mesh>, mesh: Option<&Mesh>) -> Option<Arc<Facts>> {
    if let Some(f) = store().facts.get(&id) {
        return Some(f.clone());
    }
    mesh.and_then(compute).map(Arc::new)
}

/// A mesh's triangles, cheaply (the `views:` diag, every 2 s, for every mesh drawn).
pub fn tris(id: AssetId<Mesh>, mesh: Option<&Mesh>) -> usize {
    if let Some(f) = store().facts.get(&id) {
        return f.tris;
    }
    mesh.filter(|m| readable(m)).map_or(0, |m| m.indices().map_or_else(|| m.count_vertices(), |i| i.len()) / 3)
}

/// The client is done changing this composed mesh: record its facts, and give up its CPU copy at
/// the end of the frame ([`drop_copies`]).
pub fn done(id: AssetId<Mesh>, mesh: &Mesh) {
    if !enabled() {
        return;
    }
    let Some(f) = compute(mesh) else { return };
    let mut s = store();
    s.facts.insert(id, Arc::new(f));
    s.queue.push(id);
}

/// Composed meshes handed to the render world alone, this session.
pub fn dropped() -> usize {
    store().dropped
}

/// Give up the CPU copies of the meshes [`done`] this frame; forget the facts of meshes freed.
pub fn drop_copies(mut meshes: ResMut<Assets<Mesh>>, mut events: MessageReader<AssetEvent<Mesh>>) {
    let queue = std::mem::take(&mut store().queue);
    let mut n = 0;
    for id in queue {
        if let Some(mut m) = meshes.get_mut(id) {
            if m.asset_usage != RenderAssetUsages::RENDER_WORLD {
                m.asset_usage = RenderAssetUsages::RENDER_WORLD;
                n += 1;
            }
        }
    }
    let removed: Vec<AssetId<Mesh>> = events.read().filter_map(|e| if let AssetEvent::Removed { id } = e { Some(*id) } else { None }).collect();
    let mut s = store();
    s.dropped += n;
    for id in removed {
        s.facts.remove(&id);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use bevy::mesh::{Indices, PrimitiveTopology};

    fn quad() -> Mesh {
        Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::default())
            .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
            .with_inserted_attribute(Mesh::ATTRIBUTE_UV_0, vec![[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]])
            .with_inserted_attribute(Mesh::ATTRIBUTE_COLOR, vec![[1.0, 0.0, 0.0, 1.0], [0.0, 1.0, 0.0, 1.0], [0.0, 0.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]])
            .with_inserted_indices(Indices::U32(vec![0, 1, 2, 0, 2, 3]))
    }

    /// The facts recorded before the data goes are what the readers would have read from it, and
    /// the mesh, once its data is taken (as the render world takes it), still has its bounds and
    /// gives its facts from the record alone.
    #[test]
    fn a_meshs_facts_outlive_its_data() {
        use bevy::camera::primitives::MeshAabb;
        let mut m = quad();
        let f = compute(&m).unwrap();
        assert_eq!(f.tris, 2);
        assert!(!f.uv1);
        assert_eq!(f.uv_cells.as_ref().unwrap().len(), 4);
        assert_eq!(f.vertex_sum, super::super::vertex_sum(&m));
        let aabb = m.get_aabb().unwrap();
        let id = AssetId::<Mesh>::from(bevy::asset::uuid::Uuid::from_u128(0x6c6f6f6b736d657368));
        store().facts.insert(id, Arc::new(f.clone()));
        let _gpu = m.take_gpu_data().unwrap();
        assert!(compute(&m).is_none());
        assert_eq!(m.get_aabb().map(|a| (a.center, a.half_extents)), Some((aabb.center, aabb.half_extents)));
        assert_eq!(of(id, Some(&m)).as_deref(), Some(&f));
        assert_eq!(tris(id, Some(&m)), 2);
        let other = AssetId::<Mesh>::from(bevy::asset::uuid::Uuid::from_u128(1));
        assert_eq!(tris(other, Some(&m)), 0);
        assert!(of(other, Some(&m)).is_none());
    }
}
