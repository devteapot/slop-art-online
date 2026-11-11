//! Dithered fades instead of things popping in and out.
//!
//! An entity with a [`Fade`] eases its `level` (0 drawn, 1 gone) toward its `target`. Every mesh
//! under it gets a `VisibilityRange` that never cuts by distance, only so its pipeline carries
//! Bevy's dither (`VISIBILITY_RANGE_DITHER`; given at spawn, so fading later compiles nothing),
//! and its `MeshTag`'s bits 28–31 carry the level in sixteenths. The toon shaders take that as
//! the dither level (`toon_vertex.wesl`, `toon_prepass.wesl`, `toon.wesl`), so the depth and
//! normal prepasses drop the same pixels as the colour pass and nothing behind shows a hole.
//! At level 1 the entity is hidden outright; outlines go once a thing is mostly faded
//! (`style::fog_outlines`).
//!
//! Users: buildings and tall scenery that come between the camera and you (`envs::cutaway`),
//! trees (`world::fade_trees`), and people coming into and out of sight or going indoors
//! (`live.rs`). A model that hasn't been fitted yet (`lookdev::fit`) holds its fade, so a
//! person fades in once it can be seen.

use bevy::camera::visibility::VisibilityRange;
use bevy::mesh::MeshTag;
use bevy::prelude::*;

/// Fades in and out over these (s).
pub const IN_S: f32 = 0.35;
pub const OUT_S: f32 = 0.25;
/// A visibility range that never cuts by distance. Bevy gives a mesh the dither only for a
/// range with a crossfade (an abrupt one has none), so it ends with a 1 m crossfade at 1000 km.
const NEVER_CUT: VisibilityRange = VisibilityRange { start_margin: 0.0..0.0, end_margin: 1.0e6..1.0e6 + 1.0, use_aabb: false };
/// Bits of `MeshTag` the fade uses.
const SHIFT: u32 = 28;
const MASK: u32 = 0xF << SHIFT;

#[derive(Component, Clone, Copy, Debug)]
pub struct Fade {
    pub level: f32,
    pub target: f32,
    /// Whether this module hid the entity (at level 1), so it shows it again itself.
    hid: bool,
}

impl Fade {
    /// Drawn now.
    pub fn shown() -> Self {
        Self { level: 0.0, target: 0.0, hid: false }
    }

    /// Fading in from nothing.
    pub fn appearing() -> Self {
        Self { level: 1.0, target: 0.0, hid: false }
    }

    /// The sixteenths written to the tag.
    fn step(&self) -> u32 {
        (self.level * 15.0).round().clamp(0.0, 15.0) as u32
    }
}

/// The fade level (0–15) a mesh tag carries.
pub fn tag_level(tag: u32) -> u32 {
    (tag & MASK) >> SHIFT
}

pub struct FadePlugin;

impl Plugin for FadePlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(PostUpdate, (adopt, apply).chain().before(bevy::camera::visibility::VisibilitySystems::CheckVisibility));
    }
}

/// The meshes under a faded entity, found as they arrive (scenes spawn their meshes later).
#[derive(Component, Default)]
pub struct FadeMeshes(Vec<Entity>);

/// Give each new mesh under a faded entity its never-cutting visibility range, and list it.
#[allow(clippy::type_complexity)]
fn adopt(mut commands: Commands, new: Query<Entity, Added<Mesh3d>>, parents: Query<&ChildOf>, mut roots: Query<Option<&mut FadeMeshes>, With<Fade>>, mut fresh: Local<std::collections::HashMap<Entity, Vec<Entity>>>) {
    for m in &new {
        let mut cur = m;
        let root = loop {
            if roots.contains(cur) {
                break Some(cur);
            }
            match parents.get(cur) {
                Ok(p) => cur = p.parent(),
                Err(_) => break None,
            }
        };
        let Some(root) = root else { continue };
        commands.entity(m).insert(NEVER_CUT);
        match roots.get_mut(root) {
            Ok(Some(mut list)) => list.0.push(m),
            // A root's first meshes this frame: gathered, then given their list at once (the
            // insert is deferred, so one per mesh would keep only the last).
            _ => fresh.entry(root).or_default().push(m),
        }
    }
    for (root, ms) in fresh.drain() {
        commands.entity(root).insert(FadeMeshes(ms));
    }
}

#[allow(clippy::type_complexity)]
fn apply(
    time: Res<Time>,
    mut roots: Query<(&mut Fade, Option<&mut FadeMeshes>, Option<&mut Visibility>, Option<&crate::lookdev::Model>, Has<crate::lookdev::Fitted>)>,
    mut tags: Query<Option<&mut MeshTag>>,
    mut commands: Commands,
    mut since: Local<f32>,
) {
    let dt = time.delta_secs().min(0.1);
    // `LIVING_GAME_PERF=fade`: what is fading, every 2 s.
    if crate::perf::has("fade") {
        *since += dt;
        if *since > 2.0 {
            *since = 0.0;
            let (mut n, mut aimed, mut fading, mut lists, mut adopted) = (0, 0, 0, 0, 0);
            for (f, m, ..) in roots.iter() {
                n += 1;
                aimed += (f.target > 0.0) as usize;
                fading += (f.level > 0.0) as usize;
                if let Some(m) = m {
                    lists += 1;
                    adopted += m.0.len();
                }
            }
            let tagged = tags.iter().filter(|t| t.is_some_and(|t| tag_level(t.value) > 0)).count();
            info!("fade: {n} faded things, {aimed} aimed out, {fading} not fully drawn; {lists} with meshes ({adopted} meshes); {tagged} meshes tagged faded");
        }
    }
    for (mut f, meshes, vis, model, fitted) in &mut roots {
        let before = f.step();
        // Unfitted models are still hidden (`lookdev::fit`): hold until they can be seen.
        if model.is_none() || fitted {
            let to = f.target.clamp(0.0, 1.0);
            f.level = if to > f.level { (f.level + dt / OUT_S).min(to) } else { (f.level - dt / IN_S).max(to) };
        }
        let step = f.step();
        let Some(mut meshes) = meshes else { continue };
        if step != 0 || step != before {
            meshes.0.retain(|m| tags.contains(*m));
            for &m in &meshes.0 {
                match tags.get_mut(m) {
                    Ok(Some(mut t)) => {
                        let v = (t.value & !MASK) | (step << SHIFT);
                        if t.value != v {
                            t.value = v;
                        }
                    }
                    Ok(None) if step != 0 => {
                        commands.entity(m).insert(MeshTag::new(step << SHIFT));
                    }
                    _ => {}
                }
            }
        }
        // Gone: hidden outright (nothing to draw); back from gone: shown again.
        if let Some(mut v) = vis {
            let gone = f.level >= 0.999 && f.target >= 0.999;
            if gone && !f.hid && *v != Visibility::Hidden {
                *v = Visibility::Hidden;
                f.hid = true;
            } else if !gone && f.hid {
                *v = Visibility::Inherited;
                f.hid = false;
            }
        }
    }
}
