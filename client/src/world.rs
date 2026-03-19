use avian3d::prelude::*;
use bevy::prelude::*;
use bevy_voxel_world::prelude::*;

#[derive(Component)]
pub struct MainCamera;

#[derive(Resource, Clone, Default)]
pub struct GameWorld;

impl VoxelWorldConfig for GameWorld {
    type MaterialIndex = u8;
    type ChunkUserBundle = ();

    fn spawning_distance(&self) -> u32 { 16 }

    fn voxel_lookup_delegate(&self) -> VoxelLookupDelegate<Self::MaterialIndex> {
        Box::new(move |_chunk_pos, _lod, _previous| {
            Box::new(move |pos: IVec3, _prev: Option<WorldVoxel>| {
                let x = pos.x;
                let y = pos.y;
                let z = pos.z;

                // Default ground: solid below Y=0
                let mut ground_height = 0;

                // Only apply features in a Z corridor (z = -5..5)
                if z >= -5 && z <= 5 {
                    if x >= 10 && x <= 20 {
                        // SLOPE: rises from 0 to 6, steepening (quadratic)
                        let t = (x - 10) as f32 / 10.0;
                        ground_height = (6.0 * t * t) as i32;
                    } else if x >= 25 && x <= 27 {
                        // STEP: 2-unit tall ledge
                        ground_height = 2;
                    } else if x >= 32 && x < 39 {
                        // GAP: chasm 8 units deep
                        ground_height = -8;
                    } else if x >= 44 && x <= 50 {
                        // DROP: ground drops to Y=-6
                        ground_height = -6;
                    }
                }

                if y < ground_height {
                    WorldVoxel::Solid(0)
                } else {
                    WorldVoxel::Air
                }
            })
        })
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
