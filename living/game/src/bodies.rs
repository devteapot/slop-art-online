//! Creatures at real size (metres): people about 1.75 m (children and infants smaller), deer
//! about 1.1 m at the shoulder, wolves about 0.75 m. Each is a root entity (position, facing,
//! scale) with a body mesh and limbs on pivots that swing with the creature's actual speed.
//! Models face local +X (the authority's heading 0 is east).
//!
//! Wolves are drawn from the rigged file instead when it is on disk ([`spawn_beast`]): the
//! connected client (`live.rs`) plays its clips by speed (`gait.rs`) and by the rules' aim of
//! a move (`combat.rs`). Deer are still the box creature below.

use crate::net::Net;
use crate::style::{outline, Outlined, Style};
use bevy_mod_outline::{OutlineMeshExt, PropagateOutline};
use crate::world::{hash, rgb, scale, MeshBuf, Scene};
use bevy::prelude::*;
use living_bindings::*;
use spacetimedb_sdk::Table;
use std::collections::HashMap;

/// My character's size (1 = an ordinary adult): try larger and smaller characters.
#[derive(Resource)]
pub struct MySize(pub f32);

impl Default for MySize {
    fn default() -> Self {
        Self(1.0)
    }
}

#[derive(Component)]
pub struct Creature(pub u32);

/// Walking state: last displayed position, gait phase, smoothed speed (m/s), stride (m).
#[derive(Component)]
pub struct Gait {
    last: Vec2,
    phase: f32,
    speed: f32,
    stride: f32,
}

/// A limb on a pivot: swings `amp` radians at `offset` (radians) into the gait cycle.
#[derive(Component)]
pub struct Limb {
    offset: f32,
    amp: f32,
}

pub fn stage_scale(stage: u8) -> f32 {
    match stage {
        0 => 0.42,
        1 => 0.72,
        3 => 0.96,
        _ => 1.0,
    }
}

struct Parts {
    body: Mesh,
    /// (pivot position, limb mesh hanging below it, gait offset, swing amplitude)
    limbs: Vec<(Vec3, Mesh, f32, f32)>,
    stride: f32,
}

fn pick<const N: usize>(id: u32, salt: u32, options: [[u8; 3]; N]) -> [f32; 4] {
    let c = options[((hash(id, salt) * N as f32) as usize).min(N - 1)];
    rgb(c[0], c[1], c[2])
}

fn person(id: u32, mine: bool) -> Parts {
    let skin = pick(id, 1, [[236, 196, 160], [214, 168, 130], [178, 128, 92], [128, 86, 60], [96, 64, 44]]);
    let shirt = if mine { rgb(220, 170, 50) } else { pick(id, 2, [[120, 80, 60], [90, 110, 70], [70, 90, 120], [140, 120, 90], [110, 60, 60], [80, 80, 80]]) };
    let trousers = pick(id, 3, [[70, 60, 50], [60, 70, 80], [90, 80, 60], [50, 50, 55]]);
    let hair = pick(id, 4, [[40, 30, 24], [90, 60, 30], [160, 130, 80], [30, 30, 30], [140, 140, 140]]);
    let mut b = MeshBuf::default();
    b.cube(Vec3::new(0.0, 0.98, 0.0), Vec3::new(0.11, 0.08, 0.17), trousers);
    b.cube(Vec3::new(0.0, 1.24, 0.0), Vec3::new(0.12, 0.2, 0.2), shirt);
    b.cube(Vec3::new(0.0, 1.47, 0.0), Vec3::new(0.06, 0.04, 0.06), skin);
    b.boulder(Vec3::new(0.0, 1.6, 0.0), 0.12, 1.1, id, skin);
    b.boulder(Vec3::new(-0.03, 1.66, 0.0), 0.12, 0.7, id + 1, hair);
    // Eyes face +X.
    b.cube(Vec3::new(0.115, 1.62, 0.045), Vec3::splat(0.015), rgb(30, 30, 30));
    b.cube(Vec3::new(0.115, 1.62, -0.045), Vec3::splat(0.015), rgb(30, 30, 30));
    let leg = |c: [f32; 4]| {
        let mut m = MeshBuf::default();
        m.cube(Vec3::new(0.0, -0.45, 0.0), Vec3::new(0.065, 0.45, 0.065), c);
        m.cube(Vec3::new(0.05, -0.88, 0.0), Vec3::new(0.11, 0.03, 0.06), rgb(60, 44, 32));
        m.build()
    };
    let arm = |c: [f32; 4], hand: [f32; 4]| {
        let mut m = MeshBuf::default();
        m.cube(Vec3::new(0.0, -0.28, 0.0), Vec3::new(0.05, 0.28, 0.05), c);
        m.cube(Vec3::new(0.0, -0.62, 0.0), Vec3::new(0.045, 0.06, 0.045), hand);
        m.build()
    };
    let pi = std::f32::consts::PI;
    Parts {
        body: b.build(),
        limbs: vec![
            (Vec3::new(0.0, 0.9, 0.09), leg(trousers), 0.0, 0.55),
            (Vec3::new(0.0, 0.9, -0.09), leg(trousers), pi, 0.55),
            (Vec3::new(0.0, 1.42, 0.25), arm(shirt, skin), pi, 0.45),
            (Vec3::new(0.0, 1.42, -0.25), arm(shirt, skin), 0.0, 0.45),
        ],
        stride: 1.5,
    }
}

fn quadruped(wolf: bool, id: u32) -> Parts {
    let (coat, belly) = if wolf { (pick(id, 5, [[110, 108, 104], [90, 86, 80], [130, 120, 104]]), rgb(170, 164, 150)) } else { (pick(id, 6, [[150, 104, 62], [132, 92, 56], [160, 118, 72]]), rgb(210, 190, 160)) };
    // Body length, shoulder height and girth.
    let (half_len, hip, girth, leg_len) = if wolf { (0.48, 0.55, 0.15, 0.52) } else { (0.62, 0.92, 0.2, 0.86) };
    let mut b = MeshBuf::default();
    b.cube(Vec3::new(0.0, hip + girth * 0.2, 0.0), Vec3::new(half_len, girth, girth * 0.85), coat);
    b.cube(Vec3::new(0.0, hip - girth * 0.6, 0.0), Vec3::new(half_len * 0.8, girth * 0.25, girth * 0.7), belly);
    if wolf {
        b.cube(Vec3::new(half_len + 0.12, hip + 0.18, 0.0), Vec3::new(0.14, 0.1, 0.1), coat);
        b.cube(Vec3::new(half_len + 0.3, hip + 0.14, 0.0), Vec3::new(0.08, 0.05, 0.05), belly);
        b.cone(Vec3::new(half_len + 0.1, hip + 0.28, 0.06), 0.03, 0.0, 0.0, 3, coat);
        b.cube(Vec3::new(half_len + 0.08, hip + 0.32, 0.06), Vec3::new(0.02, 0.05, 0.02), coat);
        b.cube(Vec3::new(half_len + 0.08, hip + 0.32, -0.06), Vec3::new(0.02, 0.05, 0.02), coat);
        b.cube(Vec3::new(-half_len - 0.18, hip + 0.05, 0.0), Vec3::new(0.18, 0.04, 0.04), coat);
    } else {
        b.cube(Vec3::new(half_len + 0.05, hip + 0.38, 0.0), Vec3::new(0.08, 0.24, 0.07), coat);
        b.cube(Vec3::new(half_len + 0.18, hip + 0.6, 0.0), Vec3::new(0.14, 0.07, 0.065), coat);
        b.cube(Vec3::new(half_len + 0.33, hip + 0.57, 0.0), Vec3::new(0.04, 0.04, 0.04), rgb(40, 30, 26));
        if hash(id, 7) < 0.5 {
            for s in [-1.0f32, 1.0] {
                b.cube(Vec3::new(half_len + 0.12, hip + 0.8, s * 0.08), Vec3::new(0.015, 0.14, 0.015), rgb(200, 180, 150));
                b.cube(Vec3::new(half_len + 0.17, hip + 0.9, s * 0.13), Vec3::new(0.06, 0.012, 0.012), rgb(200, 180, 150));
            }
        }
        b.cube(Vec3::new(-half_len - 0.04, hip + 0.15, 0.0), Vec3::new(0.05, 0.06, 0.04), belly);
    }
    let leg = || {
        let mut m = MeshBuf::default();
        m.cube(Vec3::new(0.0, -leg_len / 2.0, 0.0), Vec3::new(0.04, leg_len / 2.0, 0.04), scale(coat, 0.85));
        m.cube(Vec3::new(0.0, -leg_len + 0.03, 0.0), Vec3::new(0.045, 0.03, 0.045), rgb(40, 34, 30));
        m.build()
    };
    let pi = std::f32::consts::PI;
    let (fx, z) = (half_len * 0.8, girth * 0.6);
    Parts {
        body: b.build(),
        // Diagonal pairs move together.
        limbs: vec![
            (Vec3::new(fx, leg_len, z), leg(), 0.0, 0.5),
            (Vec3::new(-fx, leg_len, -z), leg(), 0.0, 0.5),
            (Vec3::new(fx, leg_len, -z), leg(), pi, 0.5),
            (Vec3::new(-fx, leg_len, z), leg(), pi, 0.5),
        ],
        stride: if wolf { 1.3 } else { 1.8 },
    }
}

fn parts(kind: &str, id: u32, mine: bool) -> Parts {
    match kind {
        "person" => person(id, mine),
        "wolf" => quadruped(true, id),
        _ => quadruped(false, id),
    }
}

/// The rigged wolf (`living/tools/blender/wolf.py`, run by `gen_anim.sh`; git-ignored), with
/// `wolf.clips.json` beside it: idle, walk, trot, run, bite, leap, hit and death. It faces +Z
/// and stands with its origin on the ground, at real size (0.86 m at the shoulder).
pub const WOLF: &str = "lookdev/anim/wolf.glb";

/// A creature drawn from a rigged file ([`spawn_beast`]). Its meshes wear the shared
/// vertex-colour material, as the box creatures do (`lookdev::convert`), so a pack adds no
/// material; it plays its file's clips (`live.rs`).
#[derive(Component)]
pub struct Beast;

/// A creature of `kind` from its rigged file, if there is one on disk: at `at`, facing `yaw`
/// (0 = +Z), `size` times its real size. None: draw the box creature ([`spawn`]).
pub fn spawn_beast(commands: &mut Commands, assets: &AssetServer, kind: &str, at: Vec3, yaw: f32, size: f32) -> Option<Entity> {
    let file = match kind {
        "wolf" => WOLF,
        _ => return None,
    };
    if !std::path::Path::new(&crate::lookdev::asset_root()).join(file).exists() {
        return None;
    }
    let scene = assets.load(bevy::gltf::GltfAssetLabel::Scene(0).from_asset(file));
    let model = crate::lookdev::Model { vrm: false, file: file.to_string(), height: 0.0, ground_y: at.y, glow: None };
    Some(
        commands
            .spawn((
                model,
                Beast,
                bevy::world_serialization::WorldAssetRoot(scene),
                crate::characters::FileHandle::kept(assets, file),
                Transform::from_translation(at).with_rotation(Quat::from_rotation_y(yaw)).with_scale(Vec3::splat(size)),
                Visibility::Hidden,
            ))
            .id(),
    )
}

/// Mirror subscribed bodies as creatures: smoothed motion, facing, size, life stage and gait.
#[allow(clippy::too_many_arguments)]
pub fn update(
    mut commands: Commands,
    net: NonSend<Net>,
    mut scene: NonSendMut<Scene>,
    mut meshes: ResMut<Assets<Mesh>>,
    palette: Res<crate::world::Palette>,
    style: Res<Style>,
    my_size: Res<MySize>,
    input: Res<crate::controls::Input>,
    mut roots: Query<(&mut Transform, &mut Gait, &Children), (With<Creature>, Without<Limb>)>,
    mut limbs: Query<(&Limb, &mut Transform), Without<Creature>>,
    time: Res<Time>,
) {
    let Some(conn) = &net.conn else { return };
    let now = scene.clock.frame(net.body_t.swap(0, std::sync::atomic::Ordering::Relaxed));
    scene.now_ms = now;
    let bodies: HashMap<u32, Body> = conn.db.body().iter().map(|b| (b.id, b)).collect();
    let chars: HashMap<u32, Character> = conn.db.character().iter().filter(|c| bodies.contains_key(&c.id)).map(|c| (c.id, c)).collect();
    let scene = &mut *scene;
    let dt = time.delta_secs().max(1e-4);
    scene.tracks.retain(|id| bodies.contains_key(&id));
    scene.shown.retain(|id, _| bodies.contains_key(id));
    let shown = &mut scene.shown;
    scene.tracks.update(bodies.values(), now, dt, |id, p, heading| {
        let prev = shown.get(&id).and_then(|(_, h)| *h);
        shown.insert(id, (Vec2::new(p.x, p.y), heading.or(prev)));
    });
    scene.creatures.retain(|id, e| {
        let keep = bodies.contains_key(id);
        if !keep {
            commands.entity(*e).despawn();
        }
        keep
    });
    if !scene.ready() {
        return;
    }
    for (id, b) in &bodies {
        let Some((p, heading)) = scene.shown.get(id).copied() else { continue };
        let c = chars.get(id);
        let alive = c.is_none_or(|c| c.alive);
        let mine = Some(*id) == net.my_id;
        // My own character turns toward where I look (shown locally only: the authority has
        // no look direction yet).
        let look = input.look.filter(|_| mine).filter(|l| l.length_squared() > 1e-4).map(|l| l.y.atan2(l.x));
        let mut rot = Quat::from_rotation_y(-look.or(heading).unwrap_or(b.heading));
        if !alive {
            rot *= Quat::from_rotation_x(std::f32::consts::FRAC_PI_2);
        }
        let size = c.map_or(1.0, |c| stage_scale(c.stage)) * if mine { my_size.0 } else { 1.0 };
        let at = scene.at3(p.x, p.y);
        if let Some(e) = scene.creatures.get(id) {
            if let Ok((mut t, mut gait, children)) = roots.get_mut(*e) {
                t.translation = at;
                t.rotation = rot;
                t.scale = Vec3::splat(size);
                let v = (p - gait.last).length() / dt;
                gait.last = p;
                let v = if v.is_finite() && v < 20.0 { v } else { 0.0 };
                gait.speed += (v - gait.speed) * (1.0 - (-dt * 10.0).exp());
                let moving = (gait.speed / 2.6).min(1.5);
                gait.phase = (gait.phase + gait.speed * dt / (gait.stride * size) * std::f32::consts::TAU) % std::f32::consts::TAU;
                for child in children.iter() {
                    if let Ok((limb, mut lt)) = limbs.get_mut(child) {
                        let a = (gait.phase + limb.offset).sin() * limb.amp * moving * alive as u8 as f32;
                        lt.rotation = Quat::from_rotation_z(a);
                    }
                }
            }
            continue;
        }
        let e = spawn(&mut commands, &mut meshes, &palette, &style, &b.kind, *id, mine, Transform::from_translation(at).with_rotation(rot).with_scale(Vec3::splat(size)), p);
        scene.creatures.insert(*id, e);
    }
}

/// Spawn a creature model (root, body and limbs) at `tf`; `p` seeds its gait position.
#[allow(clippy::too_many_arguments)]
pub fn spawn(commands: &mut Commands, meshes: &mut Assets<Mesh>, palette: &crate::world::Palette, style: &Style, kind: &str, id: u32, mine: bool, tf: Transform, p: Vec2) -> Entity {
    let parts = parts(kind, id, mine);
    let smooth = |mut m: Mesh| {
        let _ = m.generate_outline_normals(&Default::default());
        m
    };
    let body = meshes.add(smooth(parts.body));
    commands
        .spawn((
            Creature(id),
            Gait { last: p, phase: hash(id, 9) * std::f32::consts::TAU, speed: 0.0, stride: parts.stride },
            tf,
            Visibility::default(),
            outline(Outlined::Person, style),
            PropagateOutline,
        ))
        .with_children(|root| {
            root.spawn((Mesh3d(body), MeshMaterial3d(palette.vertex.clone()), Transform::default()));
            for (pivot, mesh, offset, amp) in parts.limbs {
                let m = meshes.add(smooth(mesh));
                root.spawn((Limb { offset, amp }, Transform::from_translation(pivot), Visibility::default())).with_children(|l| {
                    l.spawn((Mesh3d(m), MeshMaterial3d(palette.vertex.clone()), Transform::default()));
                });
            }
        })
        .id()
}
