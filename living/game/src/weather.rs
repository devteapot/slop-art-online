//! Weather, in presentation only: clear, rain, fog or storm, changing slowly over the game's
//! hours, with wind, wetness and lightning. The state's mood shifts (light, sky, fog, banks,
//! clouds, wind, rain) are data: the environment's `atmosphere.weather` (daylight.rs).
//!
//! - **Schedule:** the game's hours are split into spells of 5 hours; each spell's state comes from
//!   a hash of its index, so every client of one world sees the same weather from the
//!   authority's clock without any server state (the first spell is always clear). States ease
//!   into each other over about a minute; wetness follows the rain more slowly.
//! - `LIVING_GAME_WEATHER=clear|rain|fog|storm` holds one state from the start (no easing in).
//! - **Wind** sways plants in the toon shader by their mesh tag (bit 25; bits 26-27 grass,
//!   bush or tree), set here from the kind folder of each model (`envs/<env>/<kind>/`). The shared
//!   materials carry only the wind strength and wetness, changed in coarse steps, so there are no
//!   per-instance materials.

use crate::daylight::{Atmo, Clock};
use crate::style::Style;
use bevy::prelude::*;

/// The weather states, in the order of [`Weather::weights`].
pub const STATES: [&str; 4] = ["clear", "rain", "fog", "storm"];

/// Game hours per weather spell.
const SPELL_HOURS: f64 = 5.0;

#[derive(Resource)]
pub struct Weather {
    /// A state held from the start (`LIVING_GAME_WEATHER`).
    pub forced: Option<usize>,
    /// How much of each state shows (eased; sums to 1).
    pub mix: [f32; 4],
    /// How wet surfaces are (0..1), and the lightning flash (0..1).
    pub wet: f32,
    pub flash: f32,
    /// Seconds until the next flash, and the flash's own clock.
    next_flash: f32,
    flash_t: f32,
    started: bool,
}

impl Default for Weather {
    fn default() -> Self {
        let forced = std::env::var("LIVING_GAME_WEATHER").ok().and_then(|w| {
            let i = STATES.iter().position(|s| *s == w.trim());
            if i.is_none() {
                warn!("weather: unknown state {w} (want clear, rain, fog or storm)");
            }
            i
        });
        Self { forced, mix: [1.0, 0.0, 0.0, 0.0], wet: 0.0, flash: 0.0, next_flash: 4.0, flash_t: 1.0, started: false }
    }
}

impl Weather {
    pub fn weights(&self) -> Vec<(&'static str, f32)> {
        STATES.iter().zip(self.mix).filter(|(_, w)| *w > 0.001).map(|(s, w)| (*s, w)).collect()
    }

    /// The scheduled state for a spell: mostly clear, sometimes rain, fog (likelier in spells that
    /// start before dawn) or a storm.
    fn scheduled(spell: i64) -> usize {
        if spell <= 3 {
            return 0;
        }
        let r = crate::world::hash(spell as u32, 0x5eed);
        let dawn = ((spell as f64 * SPELL_HOURS).rem_euclid(24.0) - 3.0).abs() < 3.0;
        let fog = if dawn { 0.25 } else { 0.1 };
        if r < 0.55 {
            0
        } else if r < 0.75 {
            1
        } else if r < 0.75 + fog {
            2
        } else {
            3
        }
    }
}

/// Move the weather toward its state: the schedule by the game's clock, or the forced state.
pub fn update(mut w: ResMut<Weather>, clock: Res<Clock>, atmo: Res<Atmo>, time: Res<Time>) {
    let dt = time.delta_secs();
    let state = w.forced.unwrap_or_else(|| Weather::scheduled((clock.hours / SPELL_HOURS).floor() as i64));
    let mut target = [0.0; 4];
    target[state] = 1.0;
    if !w.started {
        w.started = true;
        if w.forced.is_some() {
            // A forced state shows at once (photographs), wet included.
            w.mix = target;
            w.wet = if state == 1 || state == 3 { 1.0 } else { 0.0 };
        }
    }
    let ease = 1.0 - (-dt / 45.0).exp();
    for i in 0..4 {
        w.mix[i] += (target[i] - w.mix[i]) * ease;
    }
    let sum: f32 = w.mix.iter().sum();
    for m in w.mix.iter_mut() {
        *m /= sum.max(1e-4);
    }
    // Wetness: soaks in under a minute of rain, dries over a few minutes.
    let raining = atmo.rain.clamp(0.0, 1.0);
    let rate = if raining > w.wet { 1.0 / 40.0 } else { 1.0 / 200.0 };
    w.wet += (raining - w.wet) * (1.0 - (-dt * rate).exp());
    // Lightning in storms: a double flicker every 6-20 s.
    let storm = w.mix[3];
    w.flash_t += dt;
    if storm > 0.5 {
        w.next_flash -= dt;
        if w.next_flash <= 0.0 {
            let r = crate::world::hash((time.elapsed_secs() * 10.0) as u32, 77);
            w.next_flash = 6.0 + 14.0 * r;
            w.flash_t = 0.0;
        }
    }
    let t = w.flash_t;
    let second = if t > 0.22 { 0.8 * (-(t - 0.22) * 9.0).exp() } else { 0.0 };
    w.flash = ((-t * 16.0).exp() + second).min(1.0) * storm;
}

/// Push wind and wetness to the shared toon materials in coarse steps (each push re-prepares
/// every toon material, so it happens a few times per weather change, not per frame).
pub fn push(atmo: Res<Atmo>, mut style: ResMut<Style>) {
    let step = |v: f32| (v / 0.05).round() * 0.05;
    let (wind, wet) = if atmo.active { (step(atmo.wind), step(atmo.wet)) } else { (0.0, 0.0) };
    if style.wind != wind || style.wet != wet {
        style.wind = wind;
        style.wet = wet;
    }
}

/// How a plant kind sways (mesh tag bits 26-27), if it does.
fn sway_class(kind: &str) -> Option<u32> {
    match kind {
        "grass" | "flower" | "glow_plant" => Some(0),
        "bush" | "sapling" | "young" | "coppice" => Some(1),
        "tree" | "oak" | "birch" | "pine" | "spruce" | "giant" | "snag" => Some(2),
        _ => None,
    }
}

/// Tag the meshes of plant models (from their kind folder) and the connected world's trees, so
/// the toon shader sways them.
#[allow(clippy::type_complexity)]
pub fn tag_plants(
    mut commands: Commands,
    new: Query<Entity, (Added<crate::lookdev::Converted>, Without<bevy::mesh::MeshTag>)>,
    trees: Query<Entity, (Added<crate::world::Tree>, Without<bevy::mesh::MeshTag>)>,
    parents: Query<&ChildOf>,
    models: Query<&crate::lookdev::Model>,
) {
    let tag = |class: u32| bevy::mesh::MeshTag::new((1 << 25) | (class << 26));
    for e in &new {
        let mut cur = e;
        while let Ok(p) = parents.get(cur) {
            cur = p.parent();
            if let Ok(m) = models.get(cur) {
                // envs/<env>/<kind>/<file>
                let kind = m.file.rsplit('/').nth(1).unwrap_or("");
                if let Some(class) = sway_class(kind).filter(|_| m.file.starts_with("envs/")) {
                    commands.entity(e).insert(tag(class));
                }
                break;
            }
        }
    }
    for e in &trees {
        commands.entity(e).insert(tag(2));
    }
}
