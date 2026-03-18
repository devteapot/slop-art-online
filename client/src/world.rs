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
                if pos.y < 0 {
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
