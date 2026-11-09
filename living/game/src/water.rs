//! Toon water (`water.wesl`) for the sea, lakes and rivers, replacing the flat translucent
//! sheets: colour by depth in bands, a foam line at shores, gentle animated bands, a stylised
//! reflection of the sky's gradient and the key light's glint, and rings in the rain.
//!
//! Depth comes from the difference between the water's surface and the depth prepass behind it
//! (water itself is transparent and stays out of the prepass), so shores need no extra mesh data.
//! One material serves all water; its colours follow the atmosphere a few times a second, and its
//! motion runs on the shader's clock.

use crate::daylight::Atmo;
use bevy::asset::embedded_asset;
use bevy::prelude::*;
use bevy::render::render_resource::{AsBindGroup, ShaderType};
use bevy::shader::ShaderRef;

#[derive(Clone, Copy, Debug, ShaderType)]
pub struct WaterParams {
    /// rgb: shallow water, a: how opaque deep water gets.
    pub shallow: Vec4,
    /// rgb: deep water, a: depth (m) at which it is deep.
    pub deep: Vec4,
    /// rgb: foam, a: foam width (m of depth).
    pub foam: Vec4,
    /// rgb: the sky straight up (reflections), a: rain (0..1).
    pub zenith: Vec4,
    /// rgb: the sky at the horizon, a: wind (0..1+).
    pub horizon: Vec4,
    /// x: the sky fill's strength at night (lifts dark water), y: on (1) or the plain look (0).
    pub extra: Vec4,
}

impl Default for WaterParams {
    fn default() -> Self {
        Self {
            shallow: Vec4::new(0.16, 0.48, 0.52, 0.9),
            deep: Vec4::new(0.03, 0.12, 0.24, 2.8),
            foam: Vec4::new(0.95, 0.98, 1.0, 0.35),
            zenith: Vec4::new(0.12, 0.25, 0.6, 0.0),
            horizon: Vec4::new(0.4, 0.5, 0.65, 0.2),
            extra: Vec4::new(0.0, 1.0, 0.0, 0.0),
        }
    }
}

#[derive(Asset, TypePath, AsBindGroup, Clone, Default)]
pub struct Water {
    #[uniform(0)]
    pub params: WaterParams,
}

impl Material for Water {
    fn fragment_shader() -> ShaderRef {
        "embedded://living_game/water.wesl".into()
    }

    fn alpha_mode(&self) -> AlphaMode {
        AlphaMode::Blend
    }

    fn enable_prepass() -> bool {
        false
    }

    fn enable_shadows() -> bool {
        false
    }
}

pub struct WaterPlugin;

impl Plugin for WaterPlugin {
    fn build(&self, app: &mut App) {
        embedded_asset!(app, "water.wesl");
        app.add_plugins(MaterialPlugin::<Water>::default());
    }
}

/// Follow the atmosphere's sky, rain and wind (a few times a second).
pub fn update(atmo: Res<Atmo>, palette: Res<crate::world::Palette>, mut waters: ResMut<Assets<Water>>, time: Res<Time>, mut since: Local<f32>) {
    *since += time.delta_secs();
    if *since < 0.25 {
        return;
    }
    *since = 0.0;
    let Some(w) = waters.get(&palette.water) else { return };
    let mut p = w.params;
    if atmo.active {
        p.zenith = atmo.zenith.extend(atmo.rain.min(1.0));
        p.horizon = atmo.horizon.extend(atmo.wind);
        p.extra.x = atmo.fill.length();
    } else {
        p = WaterParams::default();
    }
    if p.zenith != w.params.zenith || p.horizon != w.params.horizon || p.extra != w.params.extra {
        if let Some(mut w) = waters.get_mut(&palette.water) {
            w.params = p;
        }
    }
}
