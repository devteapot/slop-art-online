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
use living_bindings::*;
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
}

#[derive(Resource)]
struct Assets3 {
    arc: Handle<Mesh>,
    arrow: Handle<Mesh>,
    ball: Handle<Mesh>,
    ring: Handle<Mesh>,
    column: Handle<Mesh>,
    disc: Handle<Mesh>,
    guard: Handle<Mesh>,
    slash: Handle<StandardMaterial>,
    wood: Handle<StandardMaterial>,
    fire: Handle<StandardMaterial>,
    fire_core: Handle<StandardMaterial>,
    spark: Handle<StandardMaterial>,
    heal: Handle<StandardMaterial>,
    shield: Handle<StandardMaterial>,
    claw: Handle<StandardMaterial>,
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
        slash: unlit(&mut mats, LinearRgba::new(1.0, 0.93, 0.75, 0.55), true),
        wood: unlit(&mut mats, LinearRgba::new(0.55, 0.42, 0.28, 1.0), false),
        fire: unlit(&mut mats, LinearRgba::new(1.0, 0.38, 0.08, 0.7), true),
        fire_core: unlit(&mut mats, LinearRgba::new(1.0, 0.85, 0.45, 1.0), true),
        spark: unlit(&mut mats, LinearRgba::new(1.0, 1.0, 0.95, 0.85), true),
        heal: unlit(&mut mats, LinearRgba::new(0.35, 1.0, 0.55, 0.45), true),
        shield: unlit(&mut mats, LinearRgba::new(0.55, 0.78, 1.0, 0.5), true),
        claw: unlit(&mut mats, LinearRgba::new(1.0, 0.45, 0.4, 0.5), true),
    });
    commands.init_resource::<Flights>();
    commands.init_resource::<Held>();
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
    let kinds: HashMap<u32, String> = net.conn.as_ref().map(|conn| c.fresh.iter().flat_map(|e| [e.row.actor, e.row.target]).filter_map(|id| conn.db.seen_characters().id().find(&id).map(|c| (id, c.kind))).collect()).unwrap_or_default();
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
        let bolt = lk.is_some_and(|l| l.bolt);
        match r.kind {
            seen::RELEASE if lk.is_some_and(|l| l.slash) => {
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

/// A raised guard's arc and a fire bolt's ember, for as long as the fighter row says.
#[allow(clippy::too_many_arguments)]
fn persistent(mut commands: Commands, a: Res<Assets3>, cards: Res<Cards>, net: NonSend<Net>, scene: NonSend<Scene>, island: Option<Res<crate::island::Island>>, mut held: ResMut<Held>, mut q: Query<&mut Transform, With<Fx>>, time: Res<Time>) {
    let now = time.elapsed_secs();
    let Some(conn) = net.conn.as_ref() else { return };
    let t = scene.now_ms as u64;
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
                if let Ok(mut tf) = q.get_mut(*e) {
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
            _ => tf.scale = Vec3::splat(s),
        }
    }
    for p in trails {
        put(&mut commands, &a.ball, &a.fire, Kind::Trail, now, 0.3, p, Vec3::Y * 0.5, (0.24, 0.06), Quat::IDENTITY, 0.0);
    }
}
