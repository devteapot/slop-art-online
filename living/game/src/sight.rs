//! Client-only perception mock, for feeling out "the view is what your character perceives"
//! (docs/GAME_BRIEF.md, "The view as perception"). Nothing here is enforced: the authority still
//! sends every row, and its own sight is the script's `senses(a)` law, a circle per creature (11 m by day, 6 at night, 9 with a torch; one tile is one metre).
//!
//! You see within `radius`, either all around or in a forward `cone` with a small all-round
//! `close` ring. Tiles you have seen stay remembered (dimmed); tiles never seen stay dark.
//! Creatures are drawn only while seen; resources and structures once their tile was seen.
//! A shroud mesh per chunk, lying just above the ground, carries the darkness as vertex alpha.

use crate::controls::{Input, Target};
use crate::net::Net;
use crate::bodies::Creature;
use crate::world::{Draw, Scene, Thing};
use bevy::asset::RenderAssetUsages;
use bevy::mesh::{Indices, PrimitiveTopology};
use bevy::prelude::*;
use living_rules::map::{chunk_id, chunk_xy, CHUNK};
use std::collections::HashMap;

#[derive(Resource)]
pub struct Sight {
    pub enabled: bool,
    /// How far you see (tiles): the "sight" capability.
    pub radius: f32,
    /// Half-angle of the forward cone (degrees); 180 = all around.
    pub cone: f32,
    /// All-round awareness radius inside the cone mode (tiles).
    pub close: f32,
    /// Whether seen ground stays remembered (dimmed) instead of going dark again.
    pub remember: bool,
    /// Last facing (radians, +x east, +y south) and when each tile was last seen.
    facing: f32,
    seen: HashMap<(i32, i32), f64>,
    shrouds: HashMap<u32, (Entity, Handle<Mesh>)>,
    material: Handle<StandardMaterial>,
    next_s: f32,
}

impl Default for Sight {
    fn default() -> Self {
        Self { enabled: false, radius: 11.0, cone: 180.0, close: 2.5, remember: true, facing: 0.0, seen: HashMap::new(), shrouds: HashMap::new(), material: Handle::default(), next_s: 0.0 }
    }
}

impl Sight {
    /// Whether something at `p` may be drawn (always, with the mock off).
    pub fn shows(&self, me: Vec2, p: Vec2) -> bool {
        !self.enabled || self.sees(me, p)
    }

    /// Whether a point is in view of an observer at `me` facing `facing`.
    fn sees(&self, me: Vec2, p: Vec2) -> bool {
        let d = p - me;
        let dist = d.length();
        if dist <= self.close.min(self.radius) {
            return true;
        }
        if dist > self.radius {
            return false;
        }
        if self.cone >= 179.0 {
            return true;
        }
        let off = (d.y.atan2(d.x) - self.facing + std::f32::consts::PI).rem_euclid(std::f32::consts::TAU) - std::f32::consts::PI;
        off.abs().to_degrees() <= self.cone
    }

    /// For a point: 0 = in view, 1 = remembered, 2 = never seen (always 0 with the mock off).
    pub fn state_at(&self, me: Vec2, p: Vec2) -> u8 {
        if !self.enabled {
            return 0;
        }
        self.state(me, p.x.floor() as i32, p.y.floor() as i32)
    }

    /// 0 = in view, 1 = remembered, 2 = never seen.
    fn state(&self, me: Vec2, x: i32, y: i32) -> u8 {
        if self.sees(me, Vec2::new(x as f32 + 0.5, y as f32 + 0.5)) {
            0
        } else if self.remember && self.seen.contains_key(&(x, y)) {
            1
        } else {
            2
        }
    }
}

pub fn setup(mut sight: ResMut<Sight>, mut mats: ResMut<Assets<StandardMaterial>>) {
    sight.material = mats.add(StandardMaterial { base_color: Color::WHITE, unlit: true, alpha_mode: AlphaMode::Blend, ..default() });
}

/// Update facing, what is seen, the shrouds near the player and creature/thing visibility.
#[allow(clippy::too_many_arguments)]
pub fn update(
    mut commands: Commands,
    mut sight: ResMut<Sight>,
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    input: Res<Input>,
    target: Res<Target>,
    draw: Res<Draw>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut creatures: Query<(&Creature, &mut Visibility), Without<Thing>>,
    mut things: Query<(&Thing, &mut Visibility), Without<Creature>>,
    time: Res<Time>,
) {
    let me_id = net.my_id;
    let Some(me3) = target.0 else { return };
    let me = Vec2::new(me3.x, me3.z);
    // Facing: where you look with the mouse, else the way you last walked.
    if let Some(l) = input.look.filter(|l| l.length_squared() > 1e-4) {
        sight.facing = l.y.atan2(l.x);
    } else if let Some(h) = me_id.and_then(|id| scene.shown.get(&id)).and_then(|(_, h)| *h) {
        sight.facing = h;
    }
    if !sight.enabled {
        for (_, mut v) in &mut creatures {
            *v = Visibility::Inherited;
        }
        for (_, mut v) in &mut things {
            *v = Visibility::Inherited;
        }
        for (e, _) in sight.shrouds.values() {
            commands.entity(*e).insert(Visibility::Hidden);
        }
        return;
    }
    let now = scene.now_ms;
    let r = sight.radius.ceil() as i32 + 1;
    let (cx, cy) = (me.x.floor() as i32, me.y.floor() as i32);
    for y in cy - r..=cy + r {
        for x in cx - r..=cx + r {
            if sight.sees(me, Vec2::new(x as f32 + 0.5, y as f32 + 0.5)) {
                sight.seen.insert((x, y), now);
            }
        }
    }
    for (c, mut v) in &mut creatures {
        let show = Some(c.0) == me_id || scene.shown.get(&c.0).is_some_and(|(p, _)| sight.sees(me, *p));
        *v = if show { Visibility::Inherited } else { Visibility::Hidden };
    }
    for (t, mut v) in &mut things {
        let (x, y) = (t.0.x.floor() as i32, t.0.y.floor() as i32);
        let known = sight.state(me, x, y) < 2;
        *v = if known { Visibility::Inherited } else { Visibility::Hidden };
    }

    // Shrouds: one per chunk within the drawn radius; rebuilt near the player a few times a second.
    sight.next_s -= time.delta_secs();
    let refresh_near = sight.next_s <= 0.0;
    if refresh_near {
        sight.next_s = 0.12;
    }
    let (w, h) = net.map_size();
    let (cw, ch) = (w.div_ceil(CHUNK) as i32, h.div_ceil(CHUNK) as i32);
    let reach = (draw.radius / CHUNK as f32).ceil() as i32 + 1;
    let (mcx, mcy) = (me.x as i32 / CHUNK as i32, me.y as i32 / CHUNK as i32);
    let near_r = sight.radius + CHUNK as f32;
    let mut keep = Vec::new();
    for j in (mcy - reach).max(0)..=(mcy + reach).min(ch - 1) {
        for i in (mcx - reach).max(0)..=(mcx + reach).min(cw - 1) {
            let id = chunk_id(i as u32, j as u32);
            keep.push(id);
            let centre = Vec2::new((i * CHUNK as i32) as f32 + 8.0, (j * CHUNK as i32) as f32 + 8.0);
            let exists = sight.shrouds.contains_key(&id);
            let near = centre.distance(me) < near_r + 12.0;
            if exists && !(near && refresh_near) {
                if let Some((e, _)) = sight.shrouds.get(&id) {
                    commands.entity(*e).insert(Visibility::Inherited);
                }
                continue;
            }
            let mesh = shroud_mesh(&sight, &scene, me, id, w, h);
            if let Some((e, handle)) = sight.shrouds.get(&id) {
                if let Some(mut m) = meshes.get_mut(handle) {
                    *m = mesh;
                }
                commands.entity(*e).insert(Visibility::Inherited);
            } else {
                let handle = meshes.add(mesh);
                let e = commands.spawn((Mesh3d(handle.clone()), MeshMaterial3d(sight.material.clone()), Transform::default())).id();
                sight.shrouds.insert(id, (e, handle));
            }
        }
    }
    sight.shrouds.retain(|id, (e, _)| {
        let k = keep.contains(id);
        if !k {
            commands.entity(*e).despawn();
        }
        k
    });
}

fn shroud_mesh(sight: &Sight, scene: &Scene, me: Vec2, id: u32, w: u32, h: u32) -> Mesh {
    let (cx, cy) = chunk_xy(id);
    let (x0, y0) = ((cx * CHUNK) as i32, (cy * CHUNK) as i32);
    let tw = (CHUNK as i32).min(w as i32 - x0);
    let th = (CHUNK as i32).min(h as i32 - y0);
    // Two samples per tile, like the ground mesh, so the shroud follows slopes and hills.
    let (nx, ny) = (tw * 2 + 1, th * 2 + 1);
    let mut pos = Vec::with_capacity((nx * ny) as usize);
    let mut col = Vec::with_capacity((nx * ny) as usize);
    for j in 0..ny {
        for i in 0..nx {
            let (fx, fy) = (x0 as f32 + i as f32 * 0.5, y0 as f32 + j as f32 * 0.5);
            // A sample is as dark as the lightest tile touching it, so edges soften.
            let (xa, xb) = ((fx - 0.25).floor() as i32, (fx + 0.25).floor() as i32);
            let (ya, yb) = ((fy - 0.25).floor() as i32, (fy + 0.25).floor() as i32);
            let s = [(xa, ya), (xb, ya), (xa, yb), (xb, yb)].iter().map(|(a, b)| sight.state(me, *a, *b)).min().unwrap_or(2);
            let a = [0.0, 0.6, 0.88][s as usize];
            pos.push([fx, scene.ground(fx, fy) + 0.1, fy]);
            col.push([0.02, 0.03, 0.05, a]);
        }
    }
    let mut idx = Vec::new();
    for j in 0..ny - 1 {
        for i in 0..nx - 1 {
            let a = (j * nx + i) as u32;
            let (b, c, d) = (a + 1, a + nx as u32, a + nx as u32 + 1);
            idx.extend_from_slice(&[a, c, b, b, c, d]);
        }
    }
    let n = vec![[0.0, 1.0, 0.0]; pos.len()];
    Mesh::new(PrimitiveTopology::TriangleList, RenderAssetUsages::default())
        .with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, pos)
        .with_inserted_attribute(Mesh::ATTRIBUTE_NORMAL, n)
        .with_inserted_attribute(Mesh::ATTRIBUTE_COLOR, col)
        .with_inserted_indices(Indices::U32(idx))
}
