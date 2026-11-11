//! The island's atmosphere, in presentation only (docs/GAME_BRIEF.md, decisions of 2026-11-09):
//! the time of day, regional moods that blend as you walk, and the weather (weather.rs), combined
//! into one [`Atmo`] that lights the scene, colours the sky (sky.rs), the water (water.rs) and the
//! finishing pass (post.rs). Nothing here changes game logic.
//!
//! - **Clock:** connected, the authority's time is the source of truth
//!   (`living_rules::hour_of` on the `world` row's `epoch_ms` and `day_ms`, at the displayed server
//!   time). Offline (look-dev), a local clock: `LIVING_GAME_HOUR` sets the start hour (default the
//!   environment's mood hour) and `LIVING_GAME_DAY_MINUTES` the length of a day in real minutes
//!   (default 24; 0 stops the clock, for photographs at a chosen hour). The F1 sun-hour slider sets
//!   it too.
//! - **Day curve:** the environment's `atmosphere.day` keys (light, sky, fog, shadow hue, fill,
//!   grading, bloom, glow, stars) are interpolated by hour. The key light is the sun by day and the
//!   moon by night; it dips to nothing at the switch so shadows don't jump.
//! - **Regions:** `atmosphere.regions` shifts the mood by region kind (`Land::kind_at`), sampled
//!   in rings round you and eased, so moods change over tens of metres.
//! - **Weather:** `atmosphere.weather` shifts it by weather state, weighted as states change.
//!
//! What changes every frame travels through view-level data only (the light, the scene's ambient
//! light, fog, grading, bloom, the finishing pass), never through the shared toon materials: each
//! material change re-prepares it, and every material is a batch set in every view
//! (docs/GAME_BRIEF.md, performance pass 2). The toon shader reads the ambient light as the sky's
//! fill: its colour lifts shadows and gives their hue, its alpha scales glowing things.

use crate::lookdev::Lookdev;
use crate::net::Net;
use crate::weather::Weather;
use crate::world::Scene;
use bevy::pbr::{DistanceFog, FogFalloff};
use bevy::prelude::*;
use serde::Deserialize;
use living_bindings::*;
use spacetimedb_sdk::Table;
use std::collections::HashMap;
use std::f32::consts::PI;

/// An environment's `atmosphere` section.
#[derive(Deserialize, Clone, Debug)]
pub struct AtmoDef {
    /// Moods by hour, in any order.
    pub day: Vec<Key>,
    /// Shifts by region kind (`RegionKind::id`).
    #[serde(default)]
    pub regions: HashMap<String, Shift>,
    /// Shifts by weather state (`clear`, `rain`, `fog`, `storm`).
    #[serde(default)]
    pub weather: HashMap<String, Shift>,
}

/// The mood at one hour. Colours are sRGB (0..1), like the environments' moods.
#[derive(Deserialize, Clone, Copy, Debug)]
pub struct Key {
    pub hour: f32,
    /// The key light (sun or moon) and its illuminance.
    pub light: [f32; 3],
    pub lux: f32,
    /// The sky dome: straight up and at the horizon; the fog (and the sky below the horizon).
    pub zenith: [f32; 3],
    pub horizon: [f32; 3],
    pub fog: [f32; 3],
    /// Shadows' target hue (0..1), and how much the sky's fill lifts dark surfaces.
    pub shadow_hue: f32,
    pub lift: f32,
    pub saturation: f32,
    pub grade: [f32; 3],
    pub grade_strength: f32,
    pub bloom: f32,
    /// How strongly lit windows, lamps and glowing plants shine (1 = as authored).
    pub glow: f32,
    #[serde(default)]
    pub stars: f32,
    /// Fog distance, times the camera's (night closes in a little).
    #[serde(default = "one")]
    pub fog_far: f32,
    /// How much of the regions' and weather's fog banks lie (mist gathers at dawn and burns off
    /// by midday).
    #[serde(default = "one")]
    pub banks: f32,
}

fn one() -> f32 {
    1.0
}

/// A gentle change of mood for a region kind or a weather state. Every field defaults to no
/// change; shifts blend linearly by weight.
#[derive(Deserialize, Clone, Copy, Debug)]
#[serde(default)]
pub struct Shift {
    /// Key light: illuminance factor and colour factor.
    pub lux: f32,
    pub light: [f32; 3],
    /// Sky and fog move toward `sky` (keeping their brightness, times `sky_bright`) by `sky_mix`.
    pub sky: [f32; 3],
    pub sky_mix: f32,
    pub sky_bright: f32,
    pub fog_far: f32,
    pub lift: f32,
    pub hue: f32,
    pub hue_mix: f32,
    pub saturation: f32,
    pub bloom: f32,
    pub glow: f32,
    pub grade: [f32; 3],
    pub grade_mix: f32,
    pub grade_strength: f32,
    pub stars: f32,
    /// Weather fields (added): cloud cover, fog banks, wind, rain.
    pub clouds: f32,
    pub banks: f32,
    pub wind: f32,
    pub rain: f32,
}

impl Default for Shift {
    fn default() -> Self {
        Self {
            lux: 1.0,
            light: [1.0; 3],
            sky: [0.5; 3],
            sky_mix: 0.0,
            sky_bright: 1.0,
            fog_far: 1.0,
            lift: 0.0,
            hue: 0.0,
            hue_mix: 0.0,
            saturation: 0.0,
            bloom: 0.0,
            glow: 0.0,
            grade: [1.0; 3],
            grade_mix: 0.0,
            grade_strength: 0.0,
            stars: 1.0,
            clouds: 0.0,
            banks: 0.0,
            wind: 0.0,
            rain: 0.0,
        }
    }
}

impl Shift {
    /// The weighted mean of shifts (weights need not sum to 1; the rest is no change).
    pub fn blend(parts: &[(f32, &Shift)]) -> Shift {
        let id = Shift::default();
        let total: f32 = parts.iter().map(|(w, _)| *w).sum::<f32>().max(1.0);
        let rest = 1.0 - parts.iter().map(|(w, _)| *w).sum::<f32>() / total;
        let mean = |f: &dyn Fn(&Shift) -> f32| parts.iter().map(|(w, s)| w * f(s)).sum::<f32>() / total + rest * f(&id);
        let mean3 = |f: &dyn Fn(&Shift) -> [f32; 3]| [0, 1, 2].map(|i| mean(&|s| f(s)[i]));
        // Colours that come with a mix are averaged by their mix.
        let mixed = |c: &dyn Fn(&Shift) -> [f32; 3], m: &dyn Fn(&Shift) -> f32| {
            let wm: f32 = parts.iter().map(|(w, s)| w * m(s)).sum();
            if wm <= 1e-5 {
                return c(&id);
            }
            [0, 1, 2].map(|i| parts.iter().map(|(w, s)| w * m(s) * c(s)[i]).sum::<f32>() / wm)
        };
        // Hues average on the circle, by their mix.
        let (hx, hy, hm) = parts.iter().fold((0.0, 0.0, 0.0), |(x, y, m), (w, s)| (x + w * s.hue_mix * (s.hue * 2.0 * PI).cos(), y + w * s.hue_mix * (s.hue * 2.0 * PI).sin(), m + w * s.hue_mix));
        Shift {
            lux: mean(&|s| s.lux),
            light: mean3(&|s| s.light),
            sky: mixed(&|s| s.sky, &|s| s.sky_mix),
            sky_mix: mean(&|s| s.sky_mix),
            sky_bright: mean(&|s| s.sky_bright),
            fog_far: mean(&|s| s.fog_far),
            lift: mean(&|s| s.lift),
            hue: if hm > 1e-5 { (hy.atan2(hx) / (2.0 * PI)).rem_euclid(1.0) } else { 0.0 },
            hue_mix: hm / total,
            saturation: mean(&|s| s.saturation),
            bloom: mean(&|s| s.bloom),
            glow: mean(&|s| s.glow),
            grade: mixed(&|s| s.grade, &|s| s.grade_mix),
            grade_mix: mean(&|s| s.grade_mix),
            grade_strength: mean(&|s| s.grade_strength),
            stars: mean(&|s| s.stars),
            clouds: mean(&|s| s.clouds),
            banks: mean(&|s| s.banks),
            wind: mean(&|s| s.wind),
            rain: mean(&|s| s.rain),
        }
    }
}

/// The atmosphere as shown this frame (linear colours unless noted).
#[derive(Resource, Clone, Debug, Default)]
pub struct Atmo {
    /// Whether the atmosphere drives the scene (the island offline, or connected).
    pub active: bool,
    /// Directions toward the sun and the moon (true positions, for the sky), and toward the key
    /// light that lights and shadows the scene.
    pub sun: Vec3,
    pub moon: Vec3,
    pub key: Vec3,
    /// Key light colour (sRGB) and illuminance.
    pub light: [f32; 3],
    pub lux: f32,
    pub zenith: Vec3,
    pub horizon: Vec3,
    pub fog: Vec3,
    pub fog_far: f32,
    /// The sky's fill (linear, added to dark surfaces) and the glow factor.
    pub fill: Vec3,
    pub glow: f32,
    pub saturation: f32,
    /// Film gradient (sRGB, as the style profile) and its strength.
    pub grade: [f32; 3],
    pub grade_strength: f32,
    pub bloom: f32,
    pub stars: f32,
    /// Weather, eased: cloud cover, fog banks, wind, rain (0..1+), wetness, lightning flash.
    pub clouds: f32,
    pub banks: f32,
    pub wind: f32,
    pub rain: f32,
    pub wet: f32,
    pub flash: f32,
    /// Where you stand (ground height), for fog banks.
    pub ground: f32,
}

/// The atmosphere's definition (the first environment that has one: the island's).
#[derive(Resource, Default)]
pub struct AtmoDefs(pub Option<AtmoDef>);

/// The displayed clock.
#[derive(Resource)]
pub struct Clock {
    /// Game hours since the start of day 1 (continuous).
    pub hours: f64,
    /// Real minutes per game day offline (0 = stopped).
    pub day_minutes: f32,
    /// Whether the hour came from the authority this frame.
    pub server: bool,
    started: bool,
    /// The hour last written to the look-dev slider, to notice when someone moves it.
    slider: f32,
}

impl Default for Clock {
    fn default() -> Self {
        let day_minutes = std::env::var("LIVING_GAME_DAY_MINUTES").ok().and_then(|v| v.parse().ok()).unwrap_or(24.0f32).max(0.0);
        Self { hours: 15.0, day_minutes, server: false, started: false, slider: f32::NAN }
    }
}

impl Clock {
    pub fn hour(&self) -> f32 {
        self.hours.rem_euclid(24.0) as f32
    }
}

/// Region kinds round you, eased: (kind id, weight).
#[derive(Resource, Default)]
pub struct RegionMix(pub Vec<(String, f32)>);

pub struct DaylightPlugin;

impl Plugin for DaylightPlugin {
    fn build(&self, app: &mut App) {
        // `LIVING_GAME_PERF=noatmo` leaves the atmosphere out (measurement only).
        let def = crate::envs::load_defs().into_iter().find_map(|d| d.atmosphere).filter(|_| !crate::perf::has("noatmo"));
        if def.is_none() {
            warn!("atmosphere: no environment defines one; the scene keeps its fixed mood");
        }
        app.insert_resource(AtmoDefs(def))
            .init_resource::<Clock>()
            .init_resource::<Atmo>()
            .init_resource::<RegionMix>()
            .init_resource::<Weather>()
            .add_plugins((crate::sky::SkyPlugin, crate::water::WaterPlugin))
            .add_systems(
                PostUpdate,
                (clock, regions, crate::weather::update, compose, apply, lamps, crate::weather::push, crate::weather::tag_plants, crate::sky::update, crate::water::update)
                    .chain()
                    .before(bevy::transform::TransformSystems::Propagate)
                    .before(crate::post::update),
            );
    }
}

/// Advance the clock: the authority's time when connected, else the local one.
fn clock(mut clock: ResMut<Clock>, time: Res<Time>, net: NonSend<Net>, scene: NonSend<Scene>, look: Option<ResMut<Lookdev>>, island: Option<Res<crate::island::Island>>) {
    if let Some(w) = net.conn.as_ref().and_then(|c| c.db.world().iter().next()) {
        if scene.now_ms > 0.0 {
            let (now, day) = (scene.now_ms as u64, w.day_ms.max(1));
            let hour = living_rules::hour_of(now, w.epoch_ms, day) as f64;
            let days = living_rules::day_of(now, w.epoch_ms, day).saturating_sub(1) as f64;
            clock.hours = days * 24.0 + hour;
            clock.server = true;
            return;
        }
    }
    clock.server = false;
    let Some(mut look) = look else { return };
    if !clock.started && island.is_some() {
        // The start hour: `LIVING_GAME_HOUR`, else the island mood's hour (already in the slider).
        clock.hours = std::env::var("LIVING_GAME_HOUR").ok().and_then(|v| v.parse::<f64>().ok()).unwrap_or(look.hour as f64).rem_euclid(24.0);
        clock.started = true;
    } else if clock.started && (look.hour - clock.slider).abs() > 1e-4 {
        // Someone moved the slider.
        let day = (clock.hours / 24.0).floor();
        clock.hours = day * 24.0 + look.hour as f64;
    } else if clock.day_minutes > 0.0 {
        clock.hours += time.delta_secs_f64() * 24.0 / (clock.day_minutes as f64 * 60.0);
    }
    look.hour = clock.hour();
    clock.slider = look.hour;
}

/// Which region kinds are round you: samples at you and in two rings (20 and 45 m), eased over
/// about a second and a half, so moods cross a border over tens of metres.
fn regions(island: Option<Res<crate::island::Island>>, roam: Option<Res<crate::envs::Roam>>, time: Res<Time>, mut mix: ResMut<RegionMix>) {
    let (Some(island), Some(roam)) = (island, roam) else {
        mix.0.clear();
        return;
    };
    let mut want: HashMap<&'static str, f32> = HashMap::new();
    let p = roam.pos;
    let mut add = |x: f32, z: f32, w: f32| *want.entry(island.land.kind_at(x, z).id()).or_default() += w;
    add(p.x, p.y, 3.0);
    for (r, w) in [(20.0, 1.0), (45.0, 0.55)] {
        for k in 0..8 {
            let a = k as f32 / 8.0 * 2.0 * PI + r * 0.01;
            add(p.x + r * a.cos(), p.y + r * a.sin(), w);
        }
    }
    let total: f32 = want.values().sum();
    let ease = if mix.0.is_empty() { 1.0 } else { 1.0 - (-time.delta_secs() / 1.5).exp() };
    for (_, w) in mix.0.iter_mut() {
        *w *= 1.0 - ease;
    }
    for (k, w) in want {
        match mix.0.iter_mut().find(|(id, _)| id == k) {
            Some((_, v)) => *v += ease * w / total,
            None => mix.0.push((k.to_string(), ease * w / total)),
        }
    }
    mix.0.retain(|(_, w)| *w > 0.002);
}

/// Toward the sun and the moon at an hour. The sun keeps look-dev's arc (east at 6, high at noon,
/// west at 18, a little south, so the default view looks at lit faces); the moon crosses at night
/// on the same side.
pub fn bodies(hour: f32) -> (Vec3, Vec3) {
    let t = (hour - 6.0) / 12.0 * PI;
    let sun = Vec3::new(t.cos(), t.sin() * 1.2, 0.35).normalize();
    let m = (hour - 18.0).rem_euclid(24.0) / 12.0 * PI;
    let moon = Vec3::new(m.cos(), m.sin() * 1.0, 0.5).normalize();
    (sun, moon)
}

fn lerp3(a: [f32; 3], b: [f32; 3], t: f32) -> [f32; 3] {
    [0, 1, 2].map(|i| a[i] + (b[i] - a[i]) * t)
}

fn hue_lerp(a: f32, b: f32, t: f32) -> f32 {
    let mut d = b - a;
    d -= d.round();
    (a + d * t).rem_euclid(1.0)
}

fn lin(c: [f32; 3]) -> Vec3 {
    let l = Color::srgb(c[0], c[1], c[2]).to_linear();
    Vec3::new(l.red, l.green, l.blue)
}

fn luma(c: Vec3) -> f32 {
    c.dot(Vec3::new(0.2126, 0.7152, 0.0722))
}

/// The day curve at an hour (keys sorted by hour, wrapping round midnight).
fn key_at(keys: &[Key], hour: f32) -> Key {
    let mut ks = keys.to_vec();
    ks.sort_by(|a, b| a.hour.total_cmp(&b.hour));
    let n = ks.len();
    if n == 1 {
        return ks[0];
    }
    let i = ks.iter().position(|k| k.hour > hour).unwrap_or(n);
    let (a, b) = (ks[(i + n - 1) % n], ks[i % n]);
    let span = (b.hour - a.hour).rem_euclid(24.0).max(1e-3);
    let t = ((hour - a.hour).rem_euclid(24.0) / span).clamp(0.0, 1.0);
    let t = t * t * (3.0 - 2.0 * t);
    let f = |x: f32, y: f32| x + (y - x) * t;
    Key {
        hour,
        light: lerp3(a.light, b.light, t),
        lux: f(a.lux, b.lux),
        zenith: lerp3(a.zenith, b.zenith, t),
        horizon: lerp3(a.horizon, b.horizon, t),
        fog: lerp3(a.fog, b.fog, t),
        shadow_hue: hue_lerp(a.shadow_hue, b.shadow_hue, t),
        lift: f(a.lift, b.lift),
        saturation: f(a.saturation, b.saturation),
        grade: lerp3(a.grade, b.grade, t),
        grade_strength: f(a.grade_strength, b.grade_strength),
        bloom: f(a.bloom, b.bloom),
        glow: f(a.glow, b.glow),
        stars: f(a.stars, b.stars),
        fog_far: f(a.fog_far, b.fog_far),
        banks: f(a.banks, b.banks),
    }
}

/// Combine the hour, the regions round you and the weather into this frame's atmosphere.
#[allow(clippy::too_many_arguments)]
fn compose(
    defs: Res<AtmoDefs>,
    clock: Res<Clock>,
    mix: Res<RegionMix>,
    weather: Res<Weather>,
    net: NonSend<Net>,
    island: Option<Res<crate::island::Island>>,
    target: Res<crate::controls::Target>,
    mut atmo: ResMut<Atmo>,
) {
    let active = defs.0.is_some() && (island.is_some() || net.conn.is_some() || crate::view::day_curve());
    atmo.active = active;
    let Some(def) = defs.0.as_ref().filter(|_| active) else { return };
    let hour = clock.hour();
    let mut k = key_at(&def.day, hour);
    let regions: Vec<(f32, &Shift)> = mix.0.iter().filter_map(|(id, w)| def.regions.get(id).map(|s| (*w, s))).collect();
    let skies: Vec<(f32, &Shift)> = weather.weights().into_iter().filter_map(|(id, w)| def.weather.get(id).map(|s| (w, s))).collect();
    let (mut clouds, mut banks, mut wind, mut rain) = (0.0, 0.0, 0.0, 0.0);
    for shift in [Shift::blend(&regions), Shift::blend(&skies)] {
        k.lux *= shift.lux;
        k.light = [0, 1, 2].map(|i| k.light[i] * shift.light[i]);
        let toward = |c: [f32; 3]| -> [f32; 3] {
            // Toward the shift's colour at this colour's brightness, so night stays night.
            let (lc, ls) = (luma(lin(c)), luma(lin(shift.sky)).max(1e-4));
            let t = lin(shift.sky) * (lc / ls * shift.sky_bright);
            let t = Color::linear_rgb(t.x, t.y, t.z).to_srgba();
            lerp3(c, [t.red, t.green, t.blue], shift.sky_mix.clamp(0.0, 1.0))
        };
        k.zenith = toward(k.zenith);
        k.horizon = toward(k.horizon);
        k.fog = toward(k.fog);
        k.fog_far *= shift.fog_far;
        k.lift += shift.lift;
        k.shadow_hue = hue_lerp(k.shadow_hue, shift.hue, shift.hue_mix.clamp(0.0, 1.0));
        k.saturation += shift.saturation;
        k.bloom += shift.bloom;
        k.glow += shift.glow;
        k.grade = lerp3(k.grade, shift.grade, shift.grade_mix.clamp(0.0, 1.0));
        k.grade_strength += shift.grade_strength;
        k.stars *= shift.stars;
        clouds += shift.clouds;
        banks += shift.banks;
        wind += shift.wind;
        rain += shift.rain;
    }
    let (sun, moon) = bodies(hour);
    // The key light: the sun until it is just below the horizon, then the moon. It fades out
    // round the switch so its shadows never jump, and never comes from lower than about 17°
    // (a low sun lays 90 m shadows across a town and browns it over), the moon from about 25°
    // (readable nights). The sky still shows both where they really are.
    let switch = -0.03;
    let day = sun.y > switch;
    let raise = |d: Vec3, min_y: f32| if d.y >= min_y { d } else { Vec3::new(d.x, 0.0, d.z).normalize_or_zero() * (1.0 - min_y * min_y).sqrt() + Vec3::Y * min_y };
    // Nor from higher than about 58°: an overhead sun hides every shadow under its caster.
    let lower = |d: Vec3, max_y: f32| if d.y <= max_y { d } else { Vec3::new(d.x, 0.0, d.z).normalize_or(Vec3::Z) * (1.0 - max_y * max_y).sqrt() + Vec3::Y * max_y };
    let key = if day { lower(raise(sun, 0.3), 0.85) } else { lower(raise(moon, 0.42), 0.8) };
    let dip = ((sun.y - switch).abs() / 0.07).clamp(0.0, 1.0);
    let dip = dip * dip * (3.0 - 2.0 * dip);
    let flash = weather.flash;
    *atmo = Atmo {
        active: true,
        sun,
        moon,
        key,
        light: k.light,
        lux: k.lux * (0.08 + 0.92 * dip),
        zenith: lin(k.zenith) * (1.0 + flash * 2.0),
        horizon: lin(k.horizon) * (1.0 + flash * 1.5),
        fog: lin(k.fog) * (1.0 + flash * 0.8),
        fog_far: k.fog_far.max(0.2),
        fill: {
            // The fill's hue is the shadows' target hue (toon.wesl reads it back).
            let c = Color::hsv(k.shadow_hue * 360.0, 0.45, 1.0).to_linear();
            Vec3::new(c.red, c.green, c.blue) * (k.lift.max(0.002) + flash * 0.5)
        },
        glow: k.glow.max(0.05),
        saturation: k.saturation,
        grade: k.grade,
        grade_strength: k.grade_strength.max(0.0),
        bloom: k.bloom.max(0.0),
        stars: k.stars.clamp(0.0, 1.0) * (1.0 - clouds.clamp(0.0, 1.0)),
        clouds: clouds.clamp(0.0, 1.0),
        banks: (banks * k.banks).max(0.0),
        wind: wind.max(0.0),
        rain: rain.max(0.0),
        wet: weather.wet,
        flash,
        ground: target.0.map_or(0.0, |t| t.y),
    };
}

/// Light the scene from the atmosphere: the key light, the sky's fill (the scene's ambient
/// light), fog and the clear colour.
#[allow(clippy::type_complexity)]
fn apply(
    atmo: Res<Atmo>,
    mut ambient: ResMut<GlobalAmbientLight>,
    mut clear: ResMut<ClearColor>,
    mut lights: Query<(&mut DirectionalLight, &mut Transform)>,
    mut fogs: Query<&mut DistanceFog, With<Camera3d>>,
) {
    if !atmo.active {
        // Fixed moods: the toon shader ignores the ambient light (alpha 0).
        if ambient.color.alpha() != 0.0 {
            ambient.color = ambient.color.with_alpha(0.0);
        }
        return;
    }
    for (mut l, mut tf) in &mut lights {
        l.color = Color::srgb(atmo.light[0], atmo.light[1], atmo.light[2]);
        l.illuminance = atmo.lux;
        *tf = Transform::from_translation(atmo.key * 60.0).looking_at(Vec3::ZERO, Vec3::Y);
    }
    ambient.color = Color::LinearRgba(LinearRgba::new(atmo.fill.x, atmo.fill.y, atmo.fill.z, atmo.glow));
    ambient.brightness = 1.0;
    let fog = Color::linear_rgb(atmo.fog.x, atmo.fog.y, atmo.fog.z);
    clear.0 = fog;
    for mut f in &mut fogs {
        f.color = fog;
        // camera::follow sets the distance each frame; the atmosphere scales it.
        if let FogFalloff::Linear { start, end } = f.falloff {
            f.falloff = FogFalloff::Linear { start: start * atmo.fog_far, end: end * atmo.fog_far };
        }
    }
}

/// A lamp's point light (envs::local_light): its full intensity, and whether it is a lamp people
/// light at night (else a glowing plant or crystal, which glows by day too).
#[derive(Component, Clone, Copy)]
pub struct Lamp {
    pub lumens: f32,
    pub lit_at_night: bool,
}

/// Most lamps lit at once, and how far from you.
const LAMPS: usize = 14;
const LAMP_REACH: f32 = 48.0;

/// Point lights only near you, nearest first and capped, brighter at night; lamps people light
/// are out by day. Without the atmosphere every lamp stays as authored.
fn lamps(atmo: Res<Atmo>, target: Res<crate::controls::Target>, mut q: Query<(Entity, &Lamp, &mut PointLight, &GlobalTransform, &mut Visibility)>, mut order: Local<Vec<(f32, Entity)>>) {
    let night = ((atmo.glow - 1.0) / 1.0).clamp(0.0, 1.0);
    let me = target.0.unwrap_or(Vec3::ZERO);
    order.clear();
    if atmo.active {
        for (e, lamp, _, g, _) in &q {
            let d = g.translation().distance(me);
            if d < LAMP_REACH && (!lamp.lit_at_night || night > 0.02) {
                order.push((d, e));
            }
        }
        order.sort_by(|a, b| a.0.total_cmp(&b.0));
        order.truncate(LAMPS);
    }
    for (e, lamp, mut light, _, mut vis) in &mut q {
        let (on, want) = if !atmo.active {
            (true, lamp.lumens)
        } else {
            let Some(&(d, _)) = order.iter().find(|(_, x)| *x == e) else {
                if *vis != Visibility::Hidden {
                    *vis = Visibility::Hidden;
                }
                continue;
            };
            // Fade out toward the edge of the reach, so the cap never pops a light.
            let edge = 1.0 - ((d - LAMP_REACH * 0.7) / (LAMP_REACH * 0.3)).clamp(0.0, 1.0);
            let level = if lamp.lit_at_night { night } else { 0.55 + 0.45 * night };
            (true, lamp.lumens * level * edge)
        };
        let want_vis = if on { Visibility::Inherited } else { Visibility::Hidden };
        if *vis != want_vis {
            *vis = want_vis;
        }
        if (light.intensity - want).abs() > 1.0 {
            light.intensity = want;
        }
    }
}
