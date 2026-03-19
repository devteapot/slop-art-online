use avian3d::prelude::*;
use bevy::prelude::*;
use bevy::mesh::{Indices, PrimitiveTopology};
use bevy::asset::RenderAssetUsages;
use bevy_voxel_world::prelude::*;
use bevy_voxel_world::rendering::ATTRIBUTE_TEX_INDEX;
use fast_surface_nets::ndshape::{ConstShape, ConstShape3u32};
use fast_surface_nets::{surface_nets, SurfaceNetsBuffer};

#[derive(Component)]
pub struct MainCamera;

#[derive(Resource, Clone, Default)]
pub struct GameWorld;

/// Padded chunk: 32 interior voxels + 1 border on each side = 34.
type SurfaceNetsChunkShape = ConstShape3u32<34, 34, 34>;

/// Continuous terrain height at world coordinates (x, z).
fn terrain_height(x: f32, z: f32) -> f32 {
    let mut h = 0.0;
    if z >= -5.0 && z <= 5.0 {
        if x >= 10.0 && x <= 20.0 {
            let t = (x - 10.0) / 10.0;
            h = 6.0 * t * t;
        } else if x >= 25.0 && x <= 27.0 {
            h = 2.0;
        } else if x >= 32.0 && x < 39.0 {
            h = -8.0;
        } else if x >= 44.0 && x <= 50.0 {
            h = -6.0;
        }
    }
    h
}

fn build_mesh_from_surface_nets(buffer: &SurfaceNetsBuffer, chunk_pos: IVec3) -> Mesh {
    let mut mesh = Mesh::new(
        PrimitiveTopology::TriangleList,
        RenderAssetUsages::default(),
    );

    if buffer.positions.is_empty() {
        return mesh;
    }

    // World-space UVs from XZ projection for texture tiling
    let uvs: Vec<[f32; 2]> = buffer
        .positions
        .iter()
        .map(|pos| {
            let wx = chunk_pos.x as f32 * 32.0 - 1.0 + pos[0];
            let wz = chunk_pos.z as f32 * 32.0 - 1.0 + pos[2];
            [wx * 0.25, wz * 0.25]
        })
        .collect();

    let vertex_count = buffer.positions.len();

    mesh.insert_attribute(Mesh::ATTRIBUTE_POSITION, buffer.positions.clone());
    mesh.insert_attribute(Mesh::ATTRIBUTE_NORMAL, buffer.normals.clone());
    mesh.insert_attribute(Mesh::ATTRIBUTE_UV_0, uvs);
    // bevy_voxel_world's shader expects these additional vertex attributes
    mesh.insert_attribute(
        ATTRIBUTE_TEX_INDEX,
        vec![[0u32, 0, 0]; vertex_count],
    );
    mesh.insert_attribute(
        Mesh::ATTRIBUTE_COLOR,
        vec![[1.0f32, 1.0, 1.0, 1.0]; vertex_count],
    );
    mesh.insert_indices(Indices::U32(buffer.indices.clone()));

    mesh
}

impl VoxelWorldConfig for GameWorld {
    type MaterialIndex = u8;
    type ChunkUserBundle = ();

    fn spawning_distance(&self) -> u32 {
        16
    }

    fn voxel_lookup_delegate(&self) -> VoxelLookupDelegate<Self::MaterialIndex> {
        Box::new(move |_chunk_pos, _lod, _previous| {
            Box::new(move |pos: IVec3, _prev: Option<WorldVoxel>| {
                let ground_height = terrain_height(pos.x as f32, pos.z as f32) as i32;
                if pos.y < ground_height {
                    WorldVoxel::Solid(0)
                } else {
                    WorldVoxel::Air
                }
            })
        })
    }

    fn chunk_meshing_delegate(
        &self,
    ) -> ChunkMeshingDelegate<Self::MaterialIndex, Self::ChunkUserBundle> {
        Some(Box::new(
            move |chunk_pos: IVec3, _lod, _data_shape, _mesh_shape, _previous| {
                Box::new(
                    move |_voxels, _data_shape_inner, _mesh_shape_inner, _tex_mapper| {
                        // Build SDF for the padded 34×34×34 chunk
                        let mut sdf = vec![0.0f32; SurfaceNetsChunkShape::USIZE];

                        for i in 0u32..SurfaceNetsChunkShape::SIZE {
                            let [lx, ly, lz] = SurfaceNetsChunkShape::delinearize(i);
                            // World coords: chunk_pos * 32 + local - 1 (padding offset)
                            let wx = chunk_pos.x * 32 + lx as i32 - 1;
                            let wy = chunk_pos.y * 32 + ly as i32 - 1;
                            let wz = chunk_pos.z * 32 + lz as i32 - 1;

                            // SDF: positive above ground (outside), negative below (inside)
                            sdf[i as usize] = wy as f32 - terrain_height(wx as f32, wz as f32);
                        }

                        let mut buffer = SurfaceNetsBuffer::default();
                        surface_nets(
                            &sdf,
                            &SurfaceNetsChunkShape {},
                            [0; 3],
                            [33; 3],
                            &mut buffer,
                        );

                        let mesh = build_mesh_from_surface_nets(&buffer, chunk_pos);
                        (mesh, None)
                    },
                )
            },
        ))
    }
}

pub fn setup(mut commands: Commands) {
    commands.spawn((
        Camera3d::default(),
        Transform::from_xyz(0.0, 30.0, 40.0).looking_at(Vec3::ZERO, Vec3::Y),
        VoxelWorldCamera::<GameWorld>::default(),
        MainCamera,
    ));

    commands.spawn((
        DirectionalLight {
            illuminance: 10_000.0,
            shadows_enabled: true,
            ..default()
        },
        Transform::from_rotation(Quat::from_euler(EulerRot::XYZ, -1.0, 0.4, 0.0)),
    ));

    commands.spawn(AmbientLight {
        color: Color::WHITE,
        brightness: 200.0,
        ..default()
    });
}

/// Attach a trimesh collider to every newly meshed voxel chunk.
/// `Chunk<GameWorld>` is always present on chunk entities (public bevy_voxel_world component),
/// so we use it as the filter instead of a custom marker.
pub fn add_chunk_colliders(
    mut commands: Commands,
    meshes: Res<Assets<Mesh>>,
    new_chunks: Query<
        (Entity, &Mesh3d),
        (With<Chunk<GameWorld>>, Without<Collider>),
    >,
) {
    for (entity, mesh3d) in new_chunks.iter() {
        let Some(mesh) = meshes.get(&mesh3d.0) else { continue };
        // None = air chunk (no triangles) — skip silently
        let Some(collider) = Collider::trimesh_from_mesh(mesh) else { continue };
        commands.entity(entity).insert((RigidBody::Static, collider));
    }
}
