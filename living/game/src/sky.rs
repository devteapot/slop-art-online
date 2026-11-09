//! The stylised sky (`sky.wesl`): a dome round the camera with the day's gradient, toon clouds
//! that drift with the wind, sun and moon discs, and stars at night. It draws only where nothing
//! else does (no prepass, no shadows), and below the horizon it is the fog's colour, so fogged
//! land meets it without a seam. The default camera looks below the horizon (28° down with a
//! 50° field of view), so the dome mostly shows in vistas and in water's reflections
//! (water.rs reflects the same gradient).

use crate::daylight::Atmo;
use bevy::asset::embedded_asset;
use bevy::camera::visibility::NoFrustumCulling;
use bevy::light::NotShadowCaster;
use bevy::mesh::MeshVertexBufferLayoutRef;
use bevy::pbr::{MaterialPipeline, MaterialPipelineKey};
use bevy::prelude::*;
use bevy::render::render_resource::{AsBindGroup, RenderPipelineDescriptor, ShaderType, SpecializedMeshPipelineError};
use bevy::shader::ShaderRef;

/// The dome's radius (m): beyond everything drawn (terrain streams to 170 m), inside the
/// camera's culling distance.
const RADIUS: f32 = 900.0;

#[derive(Clone, Copy, Debug, Default, ShaderType)]
pub struct SkyParams {
    /// rgb: colour straight up, a: stars (0..1).
    pub zenith: Vec4,
    /// rgb: colour at the horizon, a: cloud cover (0..1).
    pub horizon: Vec4,
    /// rgb: fog colour (the sky below the horizon), a: lightning flash.
    pub fog: Vec4,
    /// xyz: toward the sun, w: rain (darker clouds).
    pub sun: Vec4,
    /// xyz: toward the moon.
    pub moon: Vec4,
    /// rgb: key light colour (linear, relative), a: night (0..1).
    pub light: Vec4,
    /// xy: cloud offset at `time.x`, zw: drift per second.
    pub cloud: Vec4,
    /// x: the shader clock (wrapped seconds) at the offset.
    pub time: Vec4,
}

#[derive(Asset, TypePath, AsBindGroup, Clone, Default)]
pub struct Sky {
    #[uniform(0)]
    pub params: SkyParams,
}

impl Material for Sky {
    fn fragment_shader() -> ShaderRef {
        "embedded://living_game/sky.wesl".into()
    }

    fn enable_prepass() -> bool {
        false
    }

    fn enable_shadows() -> bool {
        false
    }

    // Seen from inside.
    fn specialize(_: &MaterialPipeline, descriptor: &mut RenderPipelineDescriptor, _: &MeshVertexBufferLayoutRef, _: MaterialPipelineKey<Self>) -> Result<(), SpecializedMeshPipelineError> {
        descriptor.primitive.cull_mode = None;
        Ok(())
    }
}

#[derive(Component)]
pub struct Dome;

#[derive(Resource)]
pub struct SkyHandle(Handle<Sky>);

pub struct SkyPlugin;

impl Plugin for SkyPlugin {
    fn build(&self, app: &mut App) {
        embedded_asset!(app, "sky.wesl");
        app.add_plugins(MaterialPlugin::<Sky>::default()).add_systems(Startup, spawn);
    }
}

fn spawn(mut commands: Commands, mut meshes: ResMut<Assets<Mesh>>, mut skies: ResMut<Assets<Sky>>) {
    let mat = skies.add(Sky::default());
    commands.insert_resource(SkyHandle(mat.clone()));
    commands.spawn((Dome, Mesh3d(meshes.add(Sphere::new(1.0).mesh().uv(48, 24))), MeshMaterial3d(mat), Transform::from_scale(Vec3::splat(RADIUS)), NotShadowCaster, NoFrustumCulling, Visibility::Hidden));
}

/// Keep the dome round the camera and its colours in step with the atmosphere. The material is
/// rewritten a few times a second; clouds move smoothly between from the shader's clock.
#[allow(clippy::type_complexity)]
pub fn update(
    atmo: Res<Atmo>,
    handle: Option<Res<SkyHandle>>,
    mut skies: ResMut<Assets<Sky>>,
    time: Res<Time>,
    cams: Query<&Transform, (With<Camera3d>, Without<Dome>)>,
    mut domes: Query<(&mut Transform, &mut Visibility), With<Dome>>,
    mut drift: Local<(Vec2, f32)>,
) {
    let (Some(handle), Ok(cam)) = (handle, cams.single()) else { return };
    for (mut tf, mut vis) in &mut domes {
        tf.translation = cam.translation;
        let want = if atmo.active { Visibility::Inherited } else { Visibility::Hidden };
        if *vis != want {
            *vis = want;
        }
    }
    if !atmo.active {
        return;
    }
    // Clouds drift with the wind (in cloud-plane units per second).
    let speed = Vec2::new(0.94, 0.34) * (0.004 + 0.012 * atmo.wind);
    drift.0 += speed * time.delta_secs();
    drift.1 += time.delta_secs();
    if drift.1 < 0.2 && skies.get(&handle.0).is_some_and(|s| s.params.zenith != Vec4::ZERO) {
        return;
    }
    drift.1 = 0.0;
    let night = ((atmo.glow - 1.0) / 1.0).clamp(0.0, 1.0);
    let light = Color::srgb(atmo.light[0], atmo.light[1], atmo.light[2]).to_linear();
    let level = (atmo.lux / 9000.0).clamp(0.05, 1.2);
    let params = SkyParams {
        zenith: atmo.zenith.extend(atmo.stars),
        horizon: atmo.horizon.extend(atmo.clouds),
        fog: atmo.fog.extend(atmo.flash),
        sun: atmo.sun.extend(atmo.rain.min(1.0)),
        moon: atmo.moon.extend(0.0),
        light: Vec4::new(light.red * level, light.green * level, light.blue * level, night),
        cloud: Vec4::new(drift.0.x, drift.0.y, speed.x, speed.y),
        time: Vec4::new(time.elapsed_secs_wrapped(), 0.0, 0.0, 0.0),
    };
    if let Some(mut s) = skies.get_mut(&handle.0) {
        s.params = params;
    }
}
