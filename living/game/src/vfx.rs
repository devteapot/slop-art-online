//! Stylised combat effects (docs/COMBAT.md): slash arcs, arrows, fire bolts with a trail and
//! a burst, heal glows, block flashes, a raised guard's arc and a fire bolt's windup ember.
//! Presentation only: every effect starts from what my character perceived (`combat.rs`
//! events) or from what others look like in a fight (`fighter` rows); missiles fly along the
//! authority's launch (origin, direction, speed) and stop at its impact.
//!
//! All effects share a handful of meshes and unlit additive materials made once; they fade by
//! shrinking, so no effect needs a material of its own.

use crate::combat::{look, Cards, Combat};
use crate::net::Net;
use crate::world::Scene;
use bevy::light::NotShadowCaster;
use bevy::prelude::*;
use living_rules::combat::seen;
use std::collections::HashMap;

pub struct VfxPlugin;

impl Plugin for VfxPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Startup, setup).add_systems(Update, (spawn, persistent, animate).chain().in_set(crate::phase::Phase::Present).after(crate::combat::actions));
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
enum Kind {
    Slash,
    Arrow,
    Bolt,
    Trail,
    Burst,
    Ring,
    Flash,
    Shield,
    Glow,
    Ember,
    Guard,
    Glint,
}

/// How long a windup midpoint glint stays visible (s).
pub const GLINT_LIFE: f32 = 0.12;

#[derive(Resource)]
struct Assets3 {
    arc: Handle<Mesh>,
    arrow: Handle<Mesh>,
    ball: Handle<Mesh>,
    ring: Handle<Mesh>,
    column: Handle<Mesh>,
    disc: Handle<Mesh>,
    guard: Handle<Mesh>,
    glint_mesh: Handle<Mesh>,
    slash: Handle<StandardMaterial>,
    wood: Handle<StandardMaterial>,
    fire: Handle<StandardMaterial>,
    fire_core: Handle<StandardMaterial>,
    spark: Handle<StandardMaterial>,
    heal: Handle<StandardMaterial>,
    shield: Handle<StandardMaterial>,
    claw: Handle<StandardMaterial>,
    glint: Handle<StandardMaterial>,
}

/// One live effect: where it started, how it moves and grows, and when it ends (s).
#[derive(Component)]
struct Fx {
    kind: Kind,
    born: f32,
    life: f32,
    from: Vec3,
    vel: Vec3,
    grow: (f32, f32),
    spin: f32,
    base: Quat,
    trail_at: f32,
}

/// Missiles in flight by who loosed them and what, oldest first (an impact ends the oldest).
#[derive(Resource, Default)]
struct Flights(HashMap<(u32, u8), Vec<Entity>>);

/// Effects that last as long as a fighter's state: a raised guard, a fire bolt's windup.
#[derive(Resource, Default)]
struct Held(HashMap<(u32, Kind), Entity>);

/// One recorded windup telegraph glint firing (for `verify-ui` dumps).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct GlintEvent {
    pub actor: u32,
    pub act_ms: u64,
    pub release_ms: u64,
    pub f: f32,
    pub clock_ms: f64,
}

/// Pure keying state for one-shot windup glints: fires once per `(actor, act_ms)` when a
/// visible hostile windup reaches `LATE_WINDUP`, and clears its active cue on release or cancel.
#[derive(Debug)]
pub struct GlintTracker<T: Copy = Entity> {
    fired: HashMap<u32, u64>,
    active: HashMap<(u32, u64), T>,
}

impl<T: Copy> Default for GlintTracker<T> {
    fn default() -> Self {
        Self { fired: HashMap::new(), active: HashMap::new() }
    }
}

/// Outcome of reconciling `GlintTracker` against this frame's active late windups.
#[derive(Debug, PartialEq)]
pub struct GlintDiff<T: Copy = Entity> {
    /// Active glint handles whose windup released, was cancelled, or turned off: despawn now.
    pub clear: Vec<T>,
    /// Newly triggered `(actor, LateWindup)` cues to spawn this frame.
    pub spawn: Vec<(u32, crate::combat::LateWindup)>,
    /// Still-active cues `(actor, act_ms, handle, LateWindup)` whose position should follow the body.
    pub keep: Vec<(u32, u64, T, crate::combat::LateWindup)>,
}

impl<T: Copy> Default for GlintDiff<T> {
    fn default() -> Self {
        Self { clear: Vec::new(), spawn: Vec::new(), keep: Vec::new() }
    }
}

impl<T: Copy> GlintTracker<T> {
    /// Reconcile active glints against `late` (`Combat::late_windups`). When `enabled` is false,
    /// clears every active glint and resets fired keys.
    pub fn reconcile(&mut self, enabled: bool, late: &HashMap<u32, crate::combat::LateWindup>, still_alive: impl Fn(T) -> bool) -> GlintDiff<T> {
        let mut diff = GlintDiff::default();
        if !enabled {
            diff.clear.extend(self.active.drain().map(|(_, e)| e));
            self.fired.clear();
            return diff;
        }
        // Clear any active glint whose windup ended (release or cancel), or drop expired handles.
        self.active.retain(|&(actor, act_ms), &mut handle| {
            if !still_alive(handle) {
                return false;
            }
            match late.get(&actor) {
                Some(w) if w.act_ms == act_ms => {
                    diff.keep.push((actor, act_ms, handle, *w));
                    true
                }
                _ => {
                    diff.clear.push(handle);
                    false
                }
            }
        });
        // Trigger once per `(actor, act_ms)` when a hostile windup reaches `LATE_WINDUP`.
        for (&actor, &w) in late {
            if self.fired.get(&actor) != Some(&w.act_ms) {
                self.fired.insert(actor, w.act_ms);
                diff.spawn.push((actor, w));
            }
        }
        diff.spawn.sort_by_key(|(id, _)| *id);
        diff
    }

    pub fn insert_active(&mut self, actor: u32, act_ms: u64, handle: T) {
        self.active.insert((actor, act_ms), handle);
    }

    /// Drop remembered actor keys that are no longer visible.
    pub fn retain_actors(&mut self, keep: impl Fn(u32) -> bool) {
        self.fired.retain(|id, _| keep(*id));
    }
}

/// Active and recently fired windup telegraph glints (`Kind::Glint`).
#[derive(Resource, Default)]
pub struct Glints {
    tracker: GlintTracker<Entity>,
    /// Recent glint firings (capped at 32) for `verify-ui` dumps.
    pub log: Vec<GlintEvent>,
}

/// A compact 3D 4-point star glint (~0.34 m tip-to-tip), crossed in the horizontal XZ plane and
/// two tilted vertical planes so it reads crisply from the 58° top-down camera at any yaw.
fn glint_mesh() -> Mesh {
    let mut pos: Vec<[f32; 3]> = Vec::new();
    let mut idx: Vec<u32> = Vec::new();
    let mut add_star = |rot: Quat| {
        let base = pos.len() as u32;
        // 4 outer tips (radius 0.17 m -> 0.34 m across) and 4 inner waist vertices (radius 0.036 m).
        let outer = 0.17f32;
        let inner = 0.036f32;
        let pts = [
            Vec3::ZERO,
            Vec3::new(0.0, 0.0, outer),
            Vec3::new(inner, 0.0, inner),
            Vec3::new(outer, 0.0, 0.0),
            Vec3::new(inner, 0.0, -inner),
            Vec3::new(0.0, 0.0, -outer),
            Vec3::new(-inner, 0.0, -inner),
            Vec3::new(-outer, 0.0, 0.0),
            Vec3::new(-inner, 0.0, inner),
        ];
        for p in pts {
            pos.push((rot * p).into());
        }
        for k in 0..8u32 {
            let a = base + 1 + k;
            let b = base + 1 + ((k + 1) % 8);
            idx.extend_from_slice(&[base, a, b]);
        }
    };
    // Horizontal star (strongest from 58° top-down) + two orthogonal vertical stars so it reads
    // at any camera angle without vanishing edge-on.
    add_star(Quat::IDENTITY);
    add_star(Quat::from_rotation_x(std::f32::consts::FRAC_PI_2));
    add_star(Quat::from_rotation_z(std::f32::consts::FRAC_PI_2));
    let normals = vec![[0.0, 1.0, 0.0]; pos.len()];
    let uvs = vec![[0.0, 0.0]; pos.len()];
    Mesh::new(bevy::mesh::PrimitiveTopology::TriangleList, bevy::asset::RenderAssetUsages::default())
        .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, pos)
        .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, normals)
        .with_inserted_attribute(Mesh::ATTRIBUTE_UV_0, uvs)
        .with_inserted_indices(bevy::mesh::Indices::U32(idx))
}

fn unlit(mats: &mut Assets<StandardMaterial>, c: LinearRgba, add: bool) -> Handle<StandardMaterial> {
    mats.add(StandardMaterial { base_color: Color::LinearRgba(c), emissive: c * 2.0, unlit: true, alpha_mode: if add { AlphaMode::Add } else { AlphaMode::Blend }, cull_mode: None, ..default() })
}

/// A flat crescent in the XZ plane, centred on +Z (a sword's sweep), 140° wide.
fn arc_mesh() -> Mesh {
    let (n, inner, outer, half) = (20u32, 0.45f32, 1.45f32, 70f32.to_radians());
    let mut pos = Vec::new();
    let mut idx = Vec::new();
    for k in 0..=n {
        let t = k as f32 / n as f32;
        let a = -half + 2.0 * half * t;
        // Thicker in the middle, a blade's trail.
        let w = (std::f32::consts::PI * t).sin();
        let ri = outer - (outer - inner) * w;
        pos.push([a.sin() * ri, 0.0, a.cos() * ri]);
        pos.push([a.sin() * outer, 0.0, a.cos() * outer]);
        if k < n {
            let i = 2 * k;
            idx.extend_from_slice(&[i, i + 1, i + 2, i + 1, i + 3, i + 2]);
        }
    }
    let normals = vec![[0.0, 1.0, 0.0]; pos.len()];
    let uvs = vec![[0.0, 0.0]; pos.len()];
    Mesh::new(bevy::mesh::PrimitiveTopology::TriangleList, bevy::asset::RenderAssetUsages::default())
        .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, pos)
        .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, normals)
        .with_inserted_attribute(Mesh::ATTRIBUTE_UV_0, uvs)
        .with_inserted_indices(bevy::mesh::Indices::U32(idx))
}

fn setup(mut commands: Commands, mut meshes: ResMut<Assets<Mesh>>, mut mats: ResMut<Assets<StandardMaterial>>) {
    commands.insert_resource(Assets3 {
        arc: meshes.add(arc_mesh()),
        arrow: meshes.add(Cuboid::new(0.035, 0.035, 0.75)),
        ball: meshes.add(Sphere::new(0.5).mesh().ico(2).unwrap()),
        ring: meshes.add(Torus::new(0.46, 0.5)),
        column: meshes.add(Cylinder::new(0.5, 1.0)),
        disc: meshes.add(Cylinder::new(0.5, 0.04)),
        guard: meshes.add({
            let mut m = arc_mesh();
            m.scale_by(Vec3::new(0.8, 1.0, 0.8));
            m
        }),
        glint_mesh: meshes.add(glint_mesh()),
        slash: unlit(&mut mats, LinearRgba::new(1.0, 0.93, 0.75, 0.55), true),
        wood: unlit(&mut mats, LinearRgba::new(0.55, 0.42, 0.28, 1.0), false),
        fire: unlit(&mut mats, LinearRgba::new(1.0, 0.38, 0.08, 0.7), true),
        fire_core: unlit(&mut mats, LinearRgba::new(1.0, 0.85, 0.45, 1.0), true),
        spark: unlit(&mut mats, LinearRgba::new(1.0, 1.0, 0.95, 0.85), true),
        heal: unlit(&mut mats, LinearRgba::new(0.35, 1.0, 0.55, 0.45), true),
        shield: unlit(&mut mats, LinearRgba::new(0.55, 0.78, 1.0, 0.5), true),
        claw: unlit(&mut mats, LinearRgba::new(1.0, 0.45, 0.4, 0.5), true),
        glint: mats.add(StandardMaterial {
            base_color: Color::LinearRgba(LinearRgba::new(1.0, 0.90, 0.54, 0.95)),
            emissive: LinearRgba::new(1.0, 0.88, 0.48, 1.0) * 3.0,
            unlit: true,
            alpha_mode: AlphaMode::Add,
            cull_mode: None,
            ..default()
        }),
    });
    commands.init_resource::<Flights>();
    commands.init_resource::<Held>();
    commands.init_resource::<Glints>();
}

/// Ground height under a sim point (the island's, else the tile ground).
fn ground(island: &Option<Res<crate::island::Island>>, scene: &Scene, p: Vec2) -> f32 {
    island.as_ref().map_or_else(|| scene.ground(p.x, p.y), |i| i.height(p.x, p.y))
}

fn face(dir: Vec2) -> Quat {
    Quat::from_rotation_y(dir.x.atan2(dir.y))
}

#[allow(clippy::too_many_arguments)]
fn put(commands: &mut Commands, mesh: &Handle<Mesh>, mat: &Handle<StandardMaterial>, kind: Kind, now: f32, life: f32, from: Vec3, vel: Vec3, grow: (f32, f32), base: Quat, spin: f32) -> Entity {
    commands
        .spawn((
            Mesh3d(mesh.clone()),
            MeshMaterial3d(mat.clone()),
            Transform::from_translation(from).with_rotation(base).with_scale(Vec3::splat(grow.0)),
            NotShadowCaster,
            Fx { kind, born: now, life, from, vel, grow, spin, base, trail_at: now },
        ))
        .id()
}

#[allow(clippy::too_many_arguments)]
fn spawn(mut commands: Commands, a: Res<Assets3>, c: Res<Combat>, cards: Res<Cards>, net: NonSend<Net>, scene: NonSend<Scene>, island: Option<Res<crate::island::Island>>, mut flights: ResMut<Flights>, time: Res<Time>) {
    let now = time.elapsed_secs();
    let kinds: HashMap<u32, String> = net.conn.as_ref().map(|conn| c.fresh.iter().flat_map(|e| [e.row.actor, e.row.target]).filter_map(|id| crate::net::find_character(conn, id).map(|c| (id, c.kind))).collect()).unwrap_or_default();
    for e in &c.fresh {
        let r = &e.row;
        let at2 = Vec2::new(r.x, r.y);
        let dir = Vec2::new(r.dx, r.dy).normalize_or(Vec2::Y);
        let chest = |id: u32, p: Vec2| {
            let lift = match kinds.get(&id).map(String::as_str) {
                Some("wolf") => 0.55,
                Some("deer") => 0.9,
                _ => 1.15,
            };
            Vec3::new(p.x, ground(&island, &scene, p) + lift, p.y)
        };
        // How the skill looks here (`skill_card` names its code).
        let lk = cards.by_code(r.skill).map(look);
        let bolt = lk.as_ref().is_some_and(|l| l.bolt);
        match r.kind {
            seen::RELEASE if lk.as_ref().is_some_and(|l| l.slash) => {
                let p = scene.shown.get(&r.actor).map_or(at2, |s| s.0);
                let beast = kinds.get(&r.actor).is_some_and(|k| k != "person");
                let from = chest(r.actor, p) + Vec3::new(dir.x, 0.0, dir.y) * 0.25;
                let tilt = Quat::from_rotation_z(if (r.id % 2) == 0 { 0.6 } else { -0.6 });
                put(&mut commands, &a.arc, if beast { &a.claw } else { &a.slash }, Kind::Slash, now, 0.2, from, Vec3::ZERO, (0.8, 1.1), face(dir) * tilt, 2.2);
            }
            seen::LAUNCH => {
                let from = Vec3::new(r.x, ground(&island, &scene, at2) + 1.25, r.y);
                let vel = Vec3::new(dir.x, 0.0, dir.y) * r.amount.max(1.0);
                let life = (r.ms as f32 / 1000.0).max(0.05);
                let ent = if bolt {
                    put(&mut commands, &a.ball, &a.fire_core, Kind::Bolt, now, life, from, vel, (0.32, 0.32), Quat::IDENTITY, 0.0)
                } else {
                    put(&mut commands, &a.arrow, &a.wood, Kind::Arrow, now, life, from, vel, (1.0, 1.0), face(dir), 0.0)
                };
                flights.0.entry((r.actor, r.skill)).or_default().push(ent);
            }
            seen::IMPACT => {
                if let Some(list) = flights.0.get_mut(&(r.actor, r.skill)) {
                    if !list.is_empty() {
                        let e = list.remove(0);
                        commands.entity(e).try_despawn();
                    }
                }
                let at = Vec3::new(r.x, ground(&island, &scene, at2) + 1.2, r.y);
                if bolt {
                    put(&mut commands, &a.ball, &a.fire, Kind::Burst, now, 0.35, at, Vec3::ZERO, (0.3, 2.2), Quat::IDENTITY, 0.0);
                    put(&mut commands, &a.ball, &a.fire_core, Kind::Burst, now, 0.2, at, Vec3::ZERO, (0.2, 1.0), Quat::IDENTITY, 0.0);
                    let g = Vec3::new(r.x, ground(&island, &scene, at2) + 0.08, r.y);
                    put(&mut commands, &a.ring, &a.fire, Kind::Ring, now, 0.45, g, Vec3::ZERO, (0.4, 3.0), Quat::IDENTITY, 0.0);
                } else {
                    put(&mut commands, &a.ball, &a.spark, Kind::Burst, now, 0.12, at, Vec3::ZERO, (0.06, 0.3), Quat::IDENTITY, 0.0);
                }
            }
            seen::HIT => {
                let p = scene.shown.get(&r.target).map_or(at2, |s| s.0);
                let at = chest(r.target, p) - Vec3::new(dir.x, 0.0, dir.y) * 0.25;
                put(&mut commands, &a.ball, &a.spark, Kind::Flash, now, 0.14, at, Vec3::ZERO, (0.1, 0.55), Quat::IDENTITY, 0.0);
            }
            seen::BLOCKED => {
                let p = scene.shown.get(&r.target).map_or(at2, |s| s.0);
                let back = -dir;
                let at = chest(r.target, p) + Vec3::new(back.x, 0.0, back.y) * 0.45;
                let tilt = face(back) * Quat::from_rotation_x(std::f32::consts::FRAC_PI_2);
                put(&mut commands, &a.disc, &a.shield, Kind::Shield, now, 0.28, at, Vec3::ZERO, (1.4, 0.7), tilt, 0.0);
                put(&mut commands, &a.ball, &a.spark, Kind::Flash, now, 0.1, at, Vec3::ZERO, (0.08, 0.35), Quat::IDENTITY, 0.0);
            }
            seen::DODGED | seen::MISS => {
                let p = scene.shown.get(&r.target).map_or(at2, |s| s.0);
                let g = Vec3::new(p.x, ground(&island, &scene, p) + 0.06, p.y);
                put(&mut commands, &a.ring, &a.shield, Kind::Ring, now, 0.3, g, Vec3::ZERO, (0.6, 1.6), Quat::IDENTITY, 0.0);
            }
            seen::HEALED => {
                let p = scene.shown.get(&r.target).map_or(at2, |s| s.0);
                let g = Vec3::new(p.x, ground(&island, &scene, p), p.y);
                put(&mut commands, &a.ring, &a.heal, Kind::Ring, now, 0.9, g + Vec3::Y * 0.1, Vec3::Y * 1.8, (0.9, 1.3), Quat::IDENTITY, 0.0);
                put(&mut commands, &a.column, &a.heal, Kind::Glow, now, 0.7, g + Vec3::Y * 1.0, Vec3::ZERO, (0.9, 0.2), Quat::IDENTITY, 0.0);
            }
            _ => {}
        }
    }
}

/// A raised guard's arc, a fire bolt's ember, and (when enabled) the hostile windup midpoint glint.
#[allow(clippy::too_many_arguments)]
fn persistent(
    mut commands: Commands,
    a: Res<Assets3>,
    cards: Res<Cards>,
    c: Res<Combat>,
    prefs: Res<crate::keys::Prefs>,
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    island: Option<Res<crate::island::Island>>,
    mut held: ResMut<Held>,
    mut glints: ResMut<Glints>,
    mut q: Query<(&mut Transform, &mut Fx)>,
    time: Res<Time>,
) {
    let now = time.elapsed_secs();
    let Some(conn) = net.conn.as_ref() else { return };
    let clock_ms = crate::combat::combat_now_ms(&scene, prefs.combat_timing);
    let t = clock_ms as u64;
    let mut want: Vec<((u32, Kind), Vec3, Quat)> = Vec::new();
    for (id, (p, _)) in &scene.shown {
        let Some(f) = crate::net::find_fighter(conn, *id) else { continue };
        let aim = Vec2::new(f.aim_x, f.aim_y).normalize_or(Vec2::Y);
        let g = ground(&island, &scene, *p);
        let Some(card) = cards.by_code(f.act) else { continue };
        match card.aim.as_str() {
            "facing" if t < f.until_ms => want.push(((*id, Kind::Guard), Vec3::new(p.x, g + 1.0, p.y), face(aim))),
            _ if look(card).bolt && t < f.release_ms => {
                let side = Vec2::new(aim.y, -aim.x) * 0.25;
                let hand = *p + aim * 0.45 + side;
                want.push(((*id, Kind::Ember), Vec3::new(hand.x, g + 1.25, hand.y), Quat::IDENTITY));
            }
            _ => {}
        }
    }
    let keys: Vec<(u32, Kind)> = want.iter().map(|w| w.0).collect();
    held.0.retain(|k, e| {
        let keep = keys.contains(k);
        if !keep {
            commands.entity(*e).try_despawn();
        }
        keep
    });
    for (key, at, rot) in want {
        match held.0.get(&key) {
            Some(e) => {
                if let Ok((mut tf, _)) = q.get_mut(*e) {
                    tf.translation = at;
                    tf.rotation = rot;
                    if key.1 == Kind::Ember {
                        tf.scale = Vec3::splat(0.18 + 0.05 * (now * 18.0).sin());
                    }
                }
            }
            None => {
                let e = match key.1 {
                    Kind::Guard => put(&mut commands, &a.guard, &a.shield, Kind::Guard, now, f32::MAX, at, Vec3::ZERO, (1.0, 1.0), rot, 0.0),
                    _ => put(&mut commands, &a.ball, &a.fire_core, Kind::Ember, now, f32::MAX, at, Vec3::ZERO, (0.18, 0.18), rot, 0.0),
                };
                held.0.insert(key, e);
            }
        }
    }
    // Hostile windup midpoint glint (`Kind::Glint`, once per `(actor, act_ms)`, cleared on release/cancel).
    let glint_pos = |id: u32, w: &crate::combat::LateWindup| -> Option<Vec3> {
        let &(p, _) = scene.shown.get(&id)?;
        let g = ground(&island, &scene, p);
        let aim = w.aim.normalize_or(Vec2::Y);
        if w.animal {
            let xy = p + aim * 0.85;
            Some(Vec3::new(xy.x, g + 0.65, xy.y))
        } else {
            let side = Vec2::new(aim.y, -aim.x) * 0.14;
            let xy = p + aim * 0.45 + side;
            Some(Vec3::new(xy.x, g + 1.25, xy.y))
        }
    };
    let diff = glints.tracker.reconcile(prefs.windup_glint, &c.late_windups, |e| q.contains(e));
    for e in diff.clear {
        commands.entity(e).try_despawn();
    }
    for (actor, _, e, w) in diff.keep {
        if let (Some(at), Ok((mut tf, mut fx))) = (glint_pos(actor, &w), q.get_mut(e)) {
            tf.translation = at;
            fx.from = at;
        }
    }
    for (actor, w) in diff.spawn {
        let Some(at) = glint_pos(actor, &w) else { continue };
        let e = put(&mut commands, &a.glint_mesh, &a.glint, Kind::Glint, now, GLINT_LIFE, at, Vec3::ZERO, (0.4, 1.0), face(w.aim), 0.7);
        glints.tracker.insert_active(actor, w.act_ms, e);
        info!("combat: windup glint #{actor} act_ms={} release_ms={} f={:.3}", w.act_ms, w.release_ms, w.f);
        glints.log.push(GlintEvent { actor, act_ms: w.act_ms, release_ms: w.release_ms, f: w.f, clock_ms });
        if glints.log.len() > 32 {
            let drop = glints.log.len() - 32;
            glints.log.drain(..drop);
        }
    }
    glints.tracker.retain_actors(|id| scene.shown.contains_key(&id));
}

fn animate(mut commands: Commands, a: Res<Assets3>, mut q: Query<(Entity, &mut Fx, &mut Transform)>, time: Res<Time>) {
    let now = time.elapsed_secs();
    let mut trails = Vec::new();
    for (e, mut fx, mut tf) in &mut q {
        if fx.life == f32::MAX {
            continue;
        }
        let age = now - fx.born;
        let t = (age / fx.life).clamp(0.0, 1.0);
        if t >= 1.0 {
            commands.entity(e).try_despawn();
            continue;
        }
        tf.translation = fx.from + fx.vel * age;
        let s = fx.grow.0 + (fx.grow.1 - fx.grow.0) * t;
        match fx.kind {
            Kind::Slash => {
                tf.rotation = fx.base * Quat::from_rotation_y((t - 0.5) * fx.spin);
                // Thins as it fades.
                tf.scale = Vec3::new(s, 1.0, s * (1.0 - t * 0.6));
            }
            Kind::Shield => tf.scale = Vec3::new(s, 1.0, s) * (1.0 - t * 0.5),
            Kind::Glow => tf.scale = Vec3::new(s, 2.0 * (1.0 - t), s),
            Kind::Ring => tf.scale = Vec3::new(s, 1.0 - t * 0.8, s),
            Kind::Burst | Kind::Flash | Kind::Trail => tf.scale = Vec3::splat(s * (1.0 - t * t)),
            Kind::Bolt => {
                tf.scale = Vec3::splat(s);
                if now - fx.trail_at > 0.025 {
                    fx.trail_at = now;
                    trails.push(tf.translation);
                }
            }
            Kind::Glint => {
                // Crisp flash: rapid snap to peak in the first quarter, smooth taper out.
                let pulse = if t < 0.25 {
                    fx.grow.0 + (fx.grow.1 - fx.grow.0) * (t / 0.25)
                } else {
                    let u = (t - 0.25) / 0.75;
                    fx.grow.1 * (1.0 - u) * (1.0 - u)
                };
                tf.rotation = fx.base * Quat::from_rotation_y(t * fx.spin);
                tf.scale = Vec3::splat(pulse.max(0.01));
            }
            _ => tf.scale = Vec3::splat(s),
        }
    }
    for p in trails {
        put(&mut commands, &a.ball, &a.fire, Kind::Trail, now, 0.3, p, Vec3::Y * 0.5, (0.24, 0.06), Quat::IDENTITY, 0.0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::combat::LateWindup;

    fn lw(act_ms: u64, release_ms: u64, f: f32) -> LateWindup {
        LateWindup { act_ms, release_ms, f, aim: Vec2::X, animal: false }
    }

    #[test]
    fn glint_fires_once_per_windup_and_retriggers_on_next_blow() {
        let mut tr = GlintTracker::<u32>::default();
        let mut late = HashMap::new();
        late.insert(5, lw(1000, 1350, 0.52));

        let d1 = tr.reconcile(true, &late, |_| true);
        assert_eq!(d1.spawn.len(), 1);
        assert_eq!(d1.spawn[0].0, 5);
        assert!(d1.clear.is_empty());
        tr.insert_active(5, 1000, 101);

        // Subsequent frames of the same windup keep tracking without spawning a second glint.
        late.insert(5, lw(1000, 1350, 0.75));
        let d2 = tr.reconcile(true, &late, |_| true);
        assert!(d2.spawn.is_empty(), "same (actor, act_ms) never glints twice");
        assert!(d2.clear.is_empty());
        assert_eq!(d2.keep.len(), 1);
        assert_eq!(d2.keep[0].2, 101);

        // Next blow (new act_ms) clears any lingering old glint and triggers once.
        late.insert(5, lw(2000, 2350, 0.51));
        let d3 = tr.reconcile(true, &late, |_| true);
        assert_eq!(d3.clear, vec![101]);
        assert_eq!(d3.spawn.len(), 1);
        assert_eq!(d3.spawn[0].1.act_ms, 2000);
    }

    #[test]
    fn glint_clears_immediately_on_release_cancel_or_setting_off() {
        let mut tr = GlintTracker::<u32>::default();
        let mut late = HashMap::new();
        late.insert(6, lw(1000, 1750, 0.50));
        let d1 = tr.reconcile(true, &late, |_| true);
        assert_eq!(d1.spawn.len(), 1);
        tr.insert_active(6, 1000, 202);

        // Cancel or release removes the actor from `late_windups` -> glint is cleared at once.
        late.clear();
        let d2 = tr.reconcile(true, &late, |_| true);
        assert_eq!(d2.clear, vec![202]);
        assert!(d2.spawn.is_empty());

        // Setting off suppresses all glints and clears any active ones.
        late.insert(6, lw(3000, 3750, 0.55));
        let d3 = tr.reconcile(false, &late, |_| true);
        assert!(d3.spawn.is_empty());
        assert!(d3.clear.is_empty());
    }
}
