//! Procedural icons: small signed-distance shapes rasterized once at startup into white glyphs
//! with a dark rim, so a tint colours the glyph and the rim keeps it readable over the world.
//!
//! Placeholders by design: the skill, status and map glyphs should become real icon art (one
//! painted set in the game's style) once skills are on the server.

use super::model::{PoiKind, SkillIcon, StatusKind};
use bevy::asset::RenderAssetUsages;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
use std::collections::HashMap;

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Glyph {
    Skill(SkillIcon),
    Status(StatusKind),
    Poi(PoiKind),
    MouseL,
    MouseR,
    Arrow,
}

#[derive(Resource, Default)]
pub struct Icons(HashMap<Glyph, Handle<Image>>);

impl Icons {
    pub fn get(&self, g: Glyph) -> Handle<Image> {
        self.0.get(&g).cloned().unwrap_or_default()
    }
}

pub fn build(mut commands: Commands, mut images: ResMut<Assets<Image>>) {
    let mut icons = Icons::default();
    let mut all: Vec<(Glyph, u32)> = vec![(Glyph::MouseL, 48), (Glyph::MouseR, 48), (Glyph::Arrow, 64)];
    for s in [SkillIcon::Sword, SkillIcon::Bow, SkillIcon::Fire, SkillIcon::Shield, SkillIcon::Dodge, SkillIcon::Heal, SkillIcon::Empty] {
        all.push((Glyph::Skill(s), 128));
    }
    for s in [StatusKind::Hungry, StatusKind::Starving, StatusKind::Tired, StatusKind::Exhausted, StatusKind::Wasting, StatusKind::Recovering, StatusKind::InCombat, StatusKind::Talking] {
        all.push((Glyph::Status(s), 64));
    }
    for p in [PoiKind::Town, PoiKind::Village, PoiKind::Giants, PoiKind::SmallFolk, PoiKind::Cave, PoiKind::Place] {
        all.push((Glyph::Poi(p), 64));
    }
    for (g, n) in all {
        let rim = match g {
            Glyph::Skill(_) => 0.09,
            Glyph::MouseL | Glyph::MouseR => 0.0,
            _ => 0.12,
        };
        icons.0.insert(g, images.add(raster(n, rim, |p| sdf(g, p))));
    }
    commands.insert_resource(icons);
}

/// Rasterize a distance field over [-1, 1]² (y up) into a white glyph with a dark rim `rim`
/// units wide.
fn raster(n: u32, rim: f32, f: impl Fn(Vec2) -> f32) -> Image {
    let pad = 1.12;
    let px = 2.0 * pad / n as f32;
    let mut data = Vec::with_capacity((n * n * 4) as usize);
    for y in 0..n {
        for x in 0..n {
            // Four samples a pixel for clean edges at small sizes.
            let (mut fill, mut edge) = (0.0, 0.0);
            for (ox, oy) in [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)] {
                let p = Vec2::new(((x as f32 + ox) / n as f32 * 2.0 - 1.0) * pad, -((y as f32 + oy) / n as f32 * 2.0 - 1.0) * pad);
                let d = f(p);
                fill += (0.5 - d / px).clamp(0.0, 1.0) * 0.25;
                if rim > 0.0 {
                    edge += (0.5 - (d - rim) / (px * 2.0)).clamp(0.0, 1.0) * 0.25;
                }
            }
            let a = fill + (1.0 - fill) * edge * 0.7;
            let v = if a > 0.0 { fill / a } else { 0.0 };
            // White glyph over a dark ink rim (straight alpha, sRGB).
            let c = |w: f32, dark: f32| ((w * v + dark * (1.0 - v)).clamp(0.0, 1.0).powf(1.0 / 2.2) * 255.0) as u8;
            data.extend_from_slice(&[c(1.0, 0.03), c(1.0, 0.035), c(1.0, 0.06), (a.clamp(0.0, 1.0) * 255.0) as u8]);
        }
    }
    Image::new(Extent3d { width: n, height: n, depth_or_array_layers: 1 }, TextureDimension::D2, data, TextureFormat::Rgba8UnormSrgb, RenderAssetUsages::default())
}

// ---- distance primitives (negative inside) ------------------------------------------------

fn circle(p: Vec2, c: Vec2, r: f32) -> f32 {
    (p - c).length() - r
}

fn seg(p: Vec2, a: Vec2, b: Vec2, r: f32) -> f32 {
    let (pa, ba) = (p - a, b - a);
    let h = (pa.dot(ba) / ba.dot(ba)).clamp(0.0, 1.0);
    (pa - ba * h).length() - r
}

fn rbox(p: Vec2, c: Vec2, half: Vec2, round: f32) -> f32 {
    let q = (p - c).abs() - half + Vec2::splat(round);
    q.max(Vec2::ZERO).length() + q.x.max(q.y).min(0.0) - round
}

fn tri(p: Vec2, a: Vec2, b: Vec2, c: Vec2) -> f32 {
    let (e0, e1, e2) = (b - a, c - b, a - c);
    let (v0, v1, v2) = (p - a, p - b, p - c);
    let pq = |v: Vec2, e: Vec2| v - e * (v.dot(e) / e.dot(e)).clamp(0.0, 1.0);
    let (pq0, pq1, pq2) = (pq(v0, e0), pq(v1, e1), pq(v2, e2));
    let s = (e0.x * e2.y - e0.y * e2.x).signum();
    let d0 = Vec2::new(pq0.dot(pq0), s * (v0.x * e0.y - v0.y * e0.x));
    let d1 = Vec2::new(pq1.dot(pq1), s * (v1.x * e1.y - v1.y * e1.x));
    let d2 = Vec2::new(pq2.dot(pq2), s * (v2.x * e2.y - v2.y * e2.x));
    let d = d0.min(d1).min(d2);
    -d.x.sqrt() * d.y.signum()
}

/// An arc of radius `r` and half-thickness `t` from angle `a0` to `a1` (radians, CCW).
fn arc(p: Vec2, c: Vec2, r: f32, t: f32, a0: f32, a1: f32) -> f32 {
    let q = p - c;
    let a = q.y.atan2(q.x).rem_euclid(std::f32::consts::TAU);
    let (s, e) = (a0.rem_euclid(std::f32::consts::TAU), a1.rem_euclid(std::f32::consts::TAU));
    let inside = if s <= e { a >= s && a <= e } else { a >= s || a <= e };
    if inside {
        (q.length() - r).abs() - t
    } else {
        let pa = c + Vec2::from_angle(a0) * r;
        let pb = c + Vec2::from_angle(a1) * r;
        ((p - pa).length() - t).min((p - pb).length() - t)
    }
}

fn smin(a: f32, b: f32, k: f32) -> f32 {
    let h = (0.5 + 0.5 * (b - a) / k).clamp(0.0, 1.0);
    b + (a - b) * h - k * h * (1.0 - h)
}

fn sub(a: f32, b: f32) -> f32 {
    a.max(-b)
}

fn v(x: f32, y: f32) -> Vec2 {
    Vec2::new(x, y)
}

fn sword(p: Vec2) -> f32 {
    // Diagonal, tip to the upper right.
    let blade = seg(p, v(-0.28, -0.28), v(0.52, 0.52), 0.1);
    let tip = tri(p, v(0.43, 0.61), v(0.61, 0.43), v(0.8, 0.8));
    let guard = seg(p, v(-0.52, -0.06), v(-0.06, -0.52), 0.075);
    let grip = seg(p, v(-0.3, -0.3), v(-0.58, -0.58), 0.06);
    let pommel = circle(p, v(-0.66, -0.66), 0.1);
    blade.min(tip).min(guard).min(grip).min(pommel)
}

fn shield(p: Vec2) -> f32 {
    let top = rbox(p, v(0.0, 0.28), v(0.62, 0.42), 0.14);
    let point = tri(p, v(-0.62, 0.05), v(0.62, 0.05), v(0.0, -0.86));
    smin(top, point, 0.12)
}

fn house(p: Vec2, c: Vec2, s: f32) -> f32 {
    let q = (p - c) / s;
    let walls = rbox(q, v(0.0, -0.32), v(0.52, 0.38), 0.04);
    let roof = tri(q, v(-0.74, 0.0), v(0.74, 0.0), v(0.0, 0.72));
    sub(walls.min(roof), rbox(q, v(0.0, -0.5), v(0.13, 0.22), 0.04)) * s
}

fn sdf(g: Glyph, p: Vec2) -> f32 {
    use std::f32::consts::PI;
    match g {
        Glyph::Skill(SkillIcon::Sword) => sword(p),
        Glyph::Skill(SkillIcon::Bow) => {
            let limb = arc(p, v(0.42, 0.0), 0.8, 0.075, PI * 0.62, PI * 1.38);
            let (a, b) = (v(0.42, 0.0) + Vec2::from_angle(PI * 0.62) * 0.8, v(0.42, 0.0) + Vec2::from_angle(PI * 1.38) * 0.8);
            let string = seg(p, a, b, 0.025);
            let shaft = seg(p, v(-0.62, 0.0), v(0.62, 0.0), 0.04);
            let head = tri(p, v(0.58, 0.14), v(0.58, -0.14), v(0.86, 0.0));
            let fletch = tri(p, v(-0.7, 0.13), v(-0.48, 0.0), v(-0.7, -0.13));
            limb.min(string).min(shaft).min(head).min(fletch)
        }
        Glyph::Skill(SkillIcon::Fire) => {
            let outer = smin(circle(p, v(0.0, -0.3), 0.5), tri(p, v(-0.47, -0.18), v(0.42, -0.1), v(0.12, 0.88)), 0.22);
            let tongue = tri(p, v(-0.6, -0.1), v(-0.3, -0.2), v(-0.52, 0.4));
            let inner = smin(circle(p, v(0.0, -0.42), 0.22), tri(p, v(-0.2, -0.38), v(0.18, -0.34), v(0.04, 0.18)), 0.1);
            sub(smin(outer, tongue, 0.1), inner + 0.09).min(inner)
        }
        Glyph::Skill(SkillIcon::Shield) => {
            let s = shield(p);
            sub(s, s + 0.15).min(circle(p, v(0.0, 0.08), 0.17))
        }
        Glyph::Skill(SkillIcon::Dodge) => {
            let ring = arc(p, v(0.12, 0.0), 0.56, 0.085, PI * 0.3, PI * 1.75);
            let tip_at = v(0.12, 0.0) + Vec2::from_angle(PI * 0.3) * 0.56;
            let head = tri(p, tip_at + v(0.24, -0.08), tip_at + v(-0.18, -0.12), tip_at + v(0.02, 0.3));
            let lines = seg(p, v(-0.9, 0.34), v(-0.62, 0.34), 0.055).min(seg(p, v(-0.98, 0.0), v(-0.62, 0.0), 0.055)).min(seg(p, v(-0.9, -0.34), v(-0.62, -0.34), 0.055));
            ring.min(head).min(lines)
        }
        Glyph::Skill(SkillIcon::Heal) | Glyph::Status(StatusKind::Recovering) => {
            let plus = rbox(p, v(0.0, 0.0), v(0.2, 0.62), 0.12).min(rbox(p, v(0.0, 0.0), v(0.62, 0.2), 0.12));
            plus.min(circle(p, v(0.68, 0.68), 0.11)).min(circle(p, v(-0.66, -0.7), 0.08))
        }
        Glyph::Skill(SkillIcon::Empty) => seg(p, v(-0.3, 0.0), v(0.3, 0.0), 0.055).min(seg(p, v(0.0, -0.3), v(0.0, 0.3), 0.055)),
        Glyph::Status(StatusKind::Hungry) | Glyph::Status(StatusKind::Starving) => {
            let bowl = circle(p, v(0.0, 0.0), 0.66).max(p.y - 0.0);
            let rim = seg(p, v(-0.74, 0.02), v(0.74, 0.02), 0.07);
            let steam = seg(p, v(-0.22, 0.24), v(-0.12, 0.7), 0.07).min(seg(p, v(0.18, 0.24), v(0.28, 0.7), 0.07));
            bowl.min(rim).min(steam)
        }
        Glyph::Status(StatusKind::Tired) | Glyph::Status(StatusKind::Exhausted) => sub(circle(p, v(0.0, 0.0), 0.7), circle(p, v(0.36, 0.28), 0.56)),
        Glyph::Status(StatusKind::Wasting) => smin(circle(p, v(0.0, -0.28), 0.48), tri(p, v(-0.4, -0.08), v(0.4, -0.08), v(0.0, 0.86)), 0.08),
        Glyph::Status(StatusKind::InCombat) => {
            let a = seg(p, v(-0.62, -0.62), v(0.66, 0.66), 0.085).min(seg(p, v(-0.72, -0.34), v(-0.34, -0.72), 0.075));
            let b = seg(p, v(0.62, -0.62), v(-0.66, 0.66), 0.085).min(seg(p, v(0.72, -0.34), v(0.34, -0.72), 0.075));
            a.min(b)
        }
        Glyph::Status(StatusKind::Talking) => {
            let body = rbox(p, v(0.0, 0.14), v(0.74, 0.5), 0.34).min(tri(p, v(-0.42, -0.2), v(-0.02, -0.2), v(-0.56, -0.76)));
            let dots = circle(p, v(-0.34, 0.14), 0.1).min(circle(p, v(0.0, 0.14), 0.1)).min(circle(p, v(0.34, 0.14), 0.1));
            sub(body, dots)
        }
        Glyph::Poi(PoiKind::Village) => house(p, v(0.0, 0.0), 1.0),
        Glyph::Poi(PoiKind::Town) => {
            let keep = rbox(p, v(0.0, -0.22), v(0.66, 0.5), 0.04);
            let merlons = rbox(p, v(-0.5, 0.38), v(0.14, 0.14), 0.02).min(rbox(p, v(0.0, 0.38), v(0.14, 0.14), 0.02)).min(rbox(p, v(0.5, 0.38), v(0.14, 0.14), 0.02));
            sub(keep.min(merlons), rbox(p, v(0.0, -0.46), v(0.16, 0.28), 0.12))
        }
        Glyph::Poi(PoiKind::Giants) => {
            let tower = rbox(p, v(0.0, -0.2), v(0.3, 0.62), 0.04);
            let spire = tri(p, v(-0.42, 0.36), v(0.42, 0.36), v(0.0, 0.95));
            sub(tower.min(spire), rbox(p, v(0.0, -0.6), v(0.11, 0.2), 0.08))
        }
        Glyph::Poi(PoiKind::SmallFolk) => {
            let cap = circle(p, v(0.0, -0.05), 0.72).max(-0.05 - p.y);
            let stem = rbox(p, v(0.0, -0.45), v(0.24, 0.4), 0.1);
            sub(cap, circle(p, v(-0.3, 0.3), 0.1)).min(stem)
        }
        Glyph::Poi(PoiKind::Cave) => {
            let hill = circle(p, v(0.0, -0.7), 1.25).max(-0.7 - p.y);
            let mouth = circle(p, v(0.0, -0.45), 0.38).min(rbox(p, v(0.0, -0.75), v(0.38, 0.3), 0.0));
            sub(hill, mouth)
        }
        Glyph::Poi(PoiKind::Place) => {
            let pin = smin(circle(p, v(0.0, 0.25), 0.46), tri(p, v(-0.34, 0.0), v(0.34, 0.0), v(0.0, -0.86)), 0.12);
            sub(pin, circle(p, v(0.0, 0.25), 0.17))
        }
        Glyph::MouseL | Glyph::MouseR => {
            let body = rbox(p, v(0.0, 0.0), v(0.52, 0.78), 0.5);
            let shell = sub(body, body + 0.11);
            let split = seg(p, v(0.0, 0.78), v(0.0, 0.1), 0.05).min(seg(p, v(-0.52, 0.1), v(0.52, 0.1), 0.05));
            let left = g == Glyph::MouseL;
            let button = body.max(0.1 - p.y).max(if left { p.x } else { -p.x });
            shell.min(split).min(button)
        }
        Glyph::Arrow => tri(p, v(0.0, 0.86), v(0.62, -0.7), v(0.0, -0.36)).min(tri(p, v(0.0, 0.86), v(0.0, -0.36), v(-0.62, -0.7))),
    }
}
