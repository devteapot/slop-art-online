//! The throng drawn (docs/ATTENTION_BUDGET.md, "Built: the player side"): whom my character sees
//! but does not keep track of, as the authority counts them in `seen_throng` (one row per 6 m
//! cell, or per 12 m square of four far cells merged; at most 48). Only while the world's laws
//! let players heed (`heed_on` and `heed_players`: the set in place has the table, `net::throng`)
//! and the throng is drawn in Settings (`Prefs::throng`, on by default). Off, nothing here spawns
//! or draws anything.
//!
//! **The figures.** Each row gives `count` simple, unnamed figure cards (flat, unlit, upright,
//! turned to the camera; the look of the E1b mock on `attention-e1`), scattered round the row's
//! centroid (`origin + (centre_x, centre_y) + 0.5 m`) on a sunflower spiral within half its
//! `spread`, never outside the square. A row's shares pick the poses: `fighting` cards hold a
//! spear forward, then `moving` cards walk, mirrored to the side `heading` points and stepping
//! along it, and the rest stand. Per-kind counts (`people`, `wolves`, `deer`, `others`) apportion
//! cards across person cards and animal stand-ins. The fallen are no row: they stay the game's
//! own remains.
//!
//! **Colours.** Each row carries its three most-worn cloth colour indices (`living_rules::look::CLOTH`)
//! and their quantized counts (`colour_a/b/c`). One swatch per word is derived as the mean of the
//! look book's outfit RGBs for that word (`swatches_of`); a word with no outfit in the book uses
//! the neutral placeholder (logged once). Person cards take those swatches in proportion to the
//! row's counts (the rest neutral), with skin and dark trousers; animal cards keep their neutral
//! stand-in tint.
//!
//! **No pops.** Cards are kept per square (`(cell, size)`, as the authority writes a row in place
//! when a field changes): a changed row moves its cards to their new places, a new card fades in
//! and a card no longer counted fades out, over the times people fade in and out of sight
//! (`fade.rs`), so someone moving between my individuals and the throng crossfades.
//!
//! Rings on the ground mark whom I keep track of (`heed.rs`): pins and my focus.

use crate::net::Net;
use bevy::asset::RenderAssetUsages;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
use living_bindings::{SeenThrong, StructureTableAccess};
use spacetimedb_sdk::Table;
use std::collections::BTreeMap;

/// A cell's side (m), as the authority's `throng::CELL_M`.
pub const CELL_M: f32 = 6.0;
/// `heading` when most stand or their ways cancel.
pub const STILL: u8 = 255;
/// `kinds` bits.
pub const PEOPLE: u8 = 1;
pub const WOLVES: u8 = 2;
pub const DEER: u8 = 4;
pub const OTHERS: u8 = 8;
/// A person card's base size (m): slender proportions matching 3D characters (~0.36 m body width),
/// with room for a compact diagonal fighting spear without clipping. Scaled uniformly by
/// [`billboard_scale`] so camera-aligned upright cards match 3D characters' screen height at every
/// camera pitch.
const CARD: (f32, f32) = (0.88, 1.68);
/// Hit-test body width for a person card (m), matching the body rather than the spear reach.
const PICK_W: f32 = 0.62;
/// An animal stand-in's card (m).
const BEAST: (f32, f32) = (1.25, 0.90);
/// Fade in and out (s): as people do (`fade::IN_S`, `fade::OUT_S`), so a person leaving my
/// individuals for the throng crossfades with their card.
const IN_S: f32 = crate::fade::IN_S;
const OUT_S: f32 = crate::fade::OUT_S;
/// How fast a card walks to its new place when its row changes (m/s).
const GLIDE_MPS: f32 = 3.0;
/// Clearance kept between a throng card's place and a remains mound (m): a mound's boulder radius
/// is 0.4 m (`world.rs`), so 0.62 m keeps cards standing round mounds rather than bisecting them.
const MOUND_CLEAR_M: f32 = 0.62;
/// Clearance kept around perceived 3D characters (m) so throng cards do not slice through models.
const PERCEIVED_CLEAR_M: f32 = 0.80;
/// Extra clearance kept around pinned and focused characters (m) so throng cards never stand
/// inside green pin rings (`r = 0.78 m`) or amber focus rings (`r = 0.95 m`).
const RING_CLEAR_M: f32 = 1.10;
/// The tint while rows carry no colour: one neutral slate, clearly a placeholder.
pub const PLACEHOLDER: [u8; 3] = [126, 132, 146];
/// The placeholder's head and legs: a little lighter and darker than the body, for legibility.
const PLACEHOLDER_HEAD: [u8; 3] = [170, 174, 184];
const PLACEHOLDER_LEGS: [u8; 3] = [84, 88, 100];
/// The coloured card's skin, trousers, spear shaft, spearhead and dark ink outline (matching
/// `Style::default().outline_color = [0.17, 0.11, 0.10]`).
const SKIN: [u8; 3] = [214, 170, 138];
const TROUSERS: [u8; 3] = [52, 48, 58];
const SPEAR: [u8; 3] = [148, 108, 66];
const SPEAR_TIP: [u8; 3] = [220, 228, 238];
const INK: [u8; 3] = [43, 28, 26];
/// Subtle painted silhouette outline thickness (m): keeps light garments readable against stone
/// without looking like a heavy cut-out sticker.
const OUTLINE_M: f32 = 0.015;

/// Uniform pitch-aware scale for camera-aligned upright billboards: a standing 3D person viewed at
/// downward pitch `θ` projects onto `cam_up` with foreshortening `cos(θ)` plus top-down body depth
/// (~`0.22 * sin(θ)`). Applying this uniform scale keeps camera-aligned cards strictly vertical on
/// screen across the whole viewport (zero radial flank tilt) while matching 3D characters' exact
/// screen height and slender proportions at both steep top-down (~58°) and shallow orbit pitches.
pub fn billboard_scale(cam_fwd: Vec3) -> f32 {
    let sin_p = (-cam_fwd.y).clamp(0.0, 1.0);
    let cos_p = (1.0 - sin_p * sin_p).sqrt();
    (cos_p + 0.22 * sin_p).clamp(0.68, 1.0)
}
/// The key light's illuminance by day (the island's noon, `assets/envs/island.json`): cards are
/// unlit, so they are shaded by the light's colour and its share of this ([`shade`]).
const DAY_LUX: f32 = 9000.0;
/// The toon shader's noon lit-band linear gain (`toon_light.wesl` `sun_color()`):
/// `DAY_LUX * (1 / (2^9.7 * 1.2)) / PI * Style::default().exposure (0.82)`.
/// Look-book outfit RGBs are pre-lighting albedos meant to be multiplied by this in `toon.wesl`;
/// unlit cards bypass `sun_color()`, so [`swatches_of`] applies this gain when calibrating swatches.
const TOON_SUN_GAIN: f32 = DAY_LUX * (1.0 / (831.746_4 * 1.2)) / std::f32::consts::PI * 0.82;
/// The darkest the shading goes (the island's night is about 0.3 of noon).
const NIGHT_SHADE: f32 = 0.3;
/// A crowd card is under the cursor's ground point within this (m).
const PICK_M: f32 = 0.9;

/// What a card shows.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, PartialOrd, Ord)]
pub enum Pose {
    Stand,
    Walk,
    Fight,
}

/// What kind of creature a card stands for.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, PartialOrd, Ord)]
pub enum Kind {
    Person,
    Wolf,
    Deer,
    Other,
}

/// One `seen_throng` row, decoded.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Row {
    pub id: u64,
    /// The square's top-left cell (map cells of [`CELL_M`]).
    pub cx: u32,
    pub cy: u32,
    /// 1, or 2 for four far cells merged.
    pub size: u8,
    pub count: u16,
    pub spread: u8,
    pub heading: u8,
    pub moving: u16,
    pub fighting: u16,
    pub kinds: u8,
    /// The three cloth colours most worn (most first): `(index into living_rules::look::CLOTH, count)`.
    /// `(NO_CLOTH, 0)` where none.
    pub colours: [(u8, u16); 3],
    /// Quantized counts by kind (people, wolves, deer, others).
    pub people: u16,
    pub wolves: u16,
    pub deer: u16,
    pub others: u16,
    /// Members' mean position: whole metres east and south of the square's corner (`0..side-1`).
    pub centre_x: u8,
    pub centre_y: u8,
}

impl Row {
    pub fn of(r: &SeenThrong) -> Row {
        Row {
            id: r.id,
            cx: r.cell >> 16,
            cy: r.cell & 0xFFFF,
            size: r.size.max(1),
            count: r.count,
            spread: r.spread,
            heading: r.heading,
            moving: r.moving,
            fighting: r.fighting,
            kinds: r.kinds,
            colours: [(r.colour_a, r.colour_a_count), (r.colour_b, r.colour_b_count), (r.colour_c, r.colour_c_count)],
            people: r.people,
            wolves: r.wolves,
            deer: r.deer,
            others: r.others,
            centre_x: r.centre_x,
            centre_y: r.centre_y,
        }
    }

    /// How a client keys a row: by its square, as the authority updates a row in place.
    pub fn key(&self) -> (u32, u8) {
        ((self.cx << 16) | self.cy, self.size)
    }

    /// The square's side (m).
    pub fn side(&self) -> f32 {
        self.size as f32 * CELL_M
    }

    /// Its top-left corner (map m: x east, y south).
    pub fn origin(&self) -> Vec2 {
        Vec2::new(self.cx as f32, self.cy as f32) * CELL_M
    }

    /// Where the members stand (map m): `(cell corner + centre_x/centre_y + 0.5 m)`, clamped to
    /// the square (`0..=side-1` + 0.5 m).
    pub fn centre(&self) -> Vec2 {
        let max = (self.side() - 1.0).max(0.0);
        self.origin() + Vec2::new((self.centre_x as f32).min(max) + 0.5, (self.centre_y as f32).min(max) + 0.5)
    }

    /// Whether a map point lies in the square.
    pub fn holds(&self, p: Vec2) -> bool {
        let (o, s) = (self.origin(), self.side());
        p.x >= o.x && p.y >= o.y && p.x < o.x + s && p.y < o.y + s
    }

    /// Clamp a map point strictly inside the square (for `pin_at` near a card at a square's edge).
    pub fn clamp(&self, p: Vec2) -> Vec2 {
        let o = self.origin();
        let hi = o + Vec2::splat((self.side() - 1e-3).max(0.0));
        p.clamp(o, hi)
    }

    /// The way most move (map axes, unit), or none: still or mixed.
    pub fn heading_dir(&self) -> Option<Vec2> {
        heading_dir(self.heading)
    }

    /// The kinds present, in a fixed order.
    pub fn kinds_list(&self) -> Vec<Kind> {
        kinds_of(self.kinds)
    }

    /// Each card's kind (`count` entries), apportioned by `people`, `wolves`, `deer`, `others`
    /// (falling back to the `kinds` bitmask only when all four counts are zero).
    pub fn card_kinds(&self) -> Vec<Kind> {
        card_kinds(self.count, self.kinds, [self.people, self.wolves, self.deer, self.others])
    }

    /// Each card's pose: the fighting share first, then the moving share (those fighting are
    /// not counted twice), then the rest standing.
    pub fn poses(&self) -> Vec<Pose> {
        poses(self.count, self.moving, self.fighting)
    }
}

/// `heading` as a unit vector in map axes (x east, y south): 0 east, then clockwise in 45° steps
/// (2 south, 4 west, 6 north); 255 (or any value past 7) none.
pub fn heading_dir(h: u8) -> Option<Vec2> {
    (h != STILL && h < 8).then(|| Vec2::from_angle(h as f32 * std::f32::consts::FRAC_PI_4))
}

/// `kinds` bits as kinds, people first; none set reads as people (a row counts someone).
pub fn kinds_of(bits: u8) -> Vec<Kind> {
    let v: Vec<Kind> = [(PEOPLE, Kind::Person), (WOLVES, Kind::Wolf), (DEER, Kind::Deer), (OTHERS, Kind::Other)].into_iter().filter(|(b, _)| bits & b != 0).map(|(_, k)| k).collect();
    if v.is_empty() { vec![Kind::Person] } else { v }
}

/// Apportion `total` seats proportionally to `weights` by largest remainder (exact when
/// `sum(weights) == total`). When `min_one` is true and every positive weight can take at least
/// one seat, no positive weight is rounded down to zero.
fn apportion(total: usize, weights: &[usize], min_one: bool) -> Vec<usize> {
    let n = weights.len();
    if total == 0 || n == 0 {
        return vec![0; n];
    }
    let sum: usize = weights.iter().sum();
    if sum == 0 {
        return vec![0; n];
    }
    if sum == total {
        return weights.to_vec();
    }
    let mut out = vec![0usize; n];
    let mut rems: Vec<(usize, f64)> = Vec::with_capacity(n);
    let mut used = 0usize;
    for (i, &w) in weights.iter().enumerate() {
        let exact = (w as f64) * (total as f64) / (sum as f64);
        let floor = exact.floor() as usize;
        out[i] = floor;
        used += floor;
        rems.push((i, exact - floor as f64));
    }
    rems.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    for &(i, _) in rems.iter().take(total.saturating_sub(used)) {
        out[i] += 1;
    }
    if min_one && weights.iter().filter(|&&w| w > 0).count() <= total {
        for i in 0..n {
            if weights[i] > 0 && out[i] == 0 {
                if let Some((j, _)) = out.iter().enumerate().filter(|&(_, &c)| c > 1).max_by_key(|&(j, &c)| (c, j)) {
                    out[j] -= 1;
                    out[i] = 1;
                }
            }
        }
    }
    out
}

/// Smoothly interleave `items` (`(value, count)`) into an exact-count sequence of length
/// `sum(count)`, deterministically, so a mixed square spreads its kinds or colours evenly across
/// its spiral rather than forming concentric rings.
fn distribute_smooth<T: Copy>(items: &[(T, usize)]) -> Vec<T> {
    let total: usize = items.iter().map(|(_, c)| *c).sum();
    if total == 0 {
        return Vec::new();
    }
    let mut rem: Vec<usize> = items.iter().map(|(_, c)| *c).collect();
    let mut err: Vec<i64> = vec![0; items.len()];
    let mut out = Vec::with_capacity(total);
    let total_i = total as i64;
    for _ in 0..total {
        for (i, &(_, c)) in items.iter().enumerate() {
            err[i] += c as i64;
        }
        let best = (0..items.len()).filter(|&i| rem[i] > 0).max_by(|&a, &b| err[a].cmp(&err[b]).then(b.cmp(&a))).unwrap();
        out.push(items[best].0);
        rem[best] -= 1;
        err[best] -= total_i;
    }
    out
}

/// `count` kinds from the row's per-kind counts (`[people, wolves, deer, others]`), apportioned to
/// `count` (falling back to the `kinds` bitmask only when all four counts are zero).
pub fn card_kinds(count: u16, kinds_bits: u8, by_kind: [u16; 4]) -> Vec<Kind> {
    let n = count as usize;
    if n == 0 {
        return Vec::new();
    }
    let weights = by_kind.map(|c| c as usize);
    if weights.iter().sum::<usize>() == 0 {
        let present = kinds_of(kinds_bits);
        let ones = vec![1usize; present.len()];
        let alloc = apportion(n, &ones, true);
        let items: Vec<(Kind, usize)> = present.into_iter().zip(alloc).collect();
        return distribute_smooth(&items);
    }
    let alloc = apportion(n, &weights, true);
    distribute_smooth(&[(Kind::Person, alloc[0]), (Kind::Wolf, alloc[1]), (Kind::Deer, alloc[2]), (Kind::Other, alloc[3])])
}

/// `count` poses: `fighting` fight, then up to `moving` walk, the rest stand (shares clamped to
/// the count, as all three are rounded to 5 apart).
pub fn poses(count: u16, moving: u16, fighting: u16) -> Vec<Pose> {
    let n = count as usize;
    let f = (fighting as usize).min(n);
    let w = (moving as usize).min(n - f);
    let mut v = vec![Pose::Fight; f];
    v.extend(std::iter::repeat_n(Pose::Walk, w));
    v.extend(std::iter::repeat_n(Pose::Stand, n - f - w));
    v
}

/// Where a row's cards stand (map m): `n` places round the row's centroid
/// (`origin + (centre_x, centre_y) + 0.5 m`) on a sunflower spiral within half the row's `spread`
/// (at least `0.55 m × √n` so dense cells breathe), then relaxed deterministically to keep cards
/// separated without leaving the square or collapsing onto an edge sliver. A lone card stands
/// right on the centroid.
pub fn places(row: &Row, n: usize) -> Vec<Vec2> {
    if n == 0 {
        return Vec::new();
    }
    let c = row.centre();
    if n == 1 {
        return vec![c];
    }
    let half = row.side() * 0.5;
    let r_need = (0.55 * (n as f32).sqrt()).max(0.75).min(half - 0.25);
    let r = (row.spread as f32 * 0.5).max(r_need).min(half - 0.25);
    let lo = row.origin() + Vec2::splat(0.25);
    let hi = row.origin() + Vec2::splat(row.side() - 0.25);
    // Shift the packing centre inward only as far as `n` cards actually need to stay separated,
    // so the cluster stays anchored near the centroid while never crushing onto an edge sliver.
    let pack = c.clamp(lo + Vec2::splat(r_need), hi - Vec2::splat(r_need));
    let (rx_pos, rx_neg) = (r.min((hi.x - pack.x).max(0.0)), r.min((pack.x - lo.x).max(0.0)));
    let (ry_pos, ry_neg) = (r.min((hi.y - pack.y).max(0.0)), r.min((pack.y - lo.y).max(0.0)));
    // A turn of the spiral per square, so neighbouring squares don't line up.
    let turn = ((row.cx.wrapping_mul(7) ^ row.cy.wrapping_mul(13)) % 97) as f32;
    let mut pts: Vec<Vec2> = (0..n)
        .map(|k| {
            let t = ((k as f32 + 0.5) / n.max(1) as f32).sqrt();
            let a = k as f32 * 2.399_963 + turn;
            let (ux, uy) = (a.cos() * t, a.sin() * t);
            let dx = if ux >= 0.0 { ux * rx_pos } else { ux * rx_neg };
            let dy = if uy >= 0.0 { uy * ry_pos } else { uy * ry_neg };
            (pack + Vec2::new(dx, dy)).clamp(lo, hi)
        })
        .collect();
    // Deterministic pairwise repulsion inside `[lo, hi]` so dense cells never stack into smudges.
    // Target separation is 0.85 m (wider than a person's shoulders), gracefully scaling down only
    // when a cell holds more cards than can physically pack at 0.85 m.
    let min_sep = 0.85_f32.min(0.75 * row.side() / (n as f32).sqrt().max(1.0));
    let min_sep2 = min_sep * min_sep;
    for _ in 0..6 {
        let mut moved = false;
        for i in 0..n {
            for j in (i + 1)..n {
                let d = pts[j] - pts[i];
                let d2 = d.length_squared();
                if d2 < min_sep2 {
                    let dist = d2.sqrt();
                    let dir = if dist > 1e-4 {
                        d / dist
                    } else {
                        let ang = (i * 17 + j * 31) as f32;
                        Vec2::new(ang.cos(), ang.sin())
                    };
                    let push = dir * ((min_sep - dist) * 0.52);
                    pts[i] = (pts[i] - push).clamp(lo, hi);
                    pts[j] = (pts[j] + push).clamp(lo, hi);
                    moved = true;
                }
            }
        }
        if !moved {
            break;
        }
    }
    pts
}

/// Nudge card positions clear of ground obstacles (such as remains mounds) while staying inside
/// `[lo, hi]`, so flat billboard cards stand round mounds instead of bisecting them.
pub fn avoid_obstacles(pts: &mut [Vec2], obstacles: &[Vec2], min_clear: f32, lo: Vec2, hi: Vec2) {
    if obstacles.is_empty() || min_clear <= 0.0 {
        return;
    }
    let c2 = min_clear * min_clear;
    for (k, p) in pts.iter_mut().enumerate() {
        for _ in 0..3 {
            let mut push = Vec2::ZERO;
            for &o in obstacles {
                let d = *p - o;
                let d2 = d.length_squared();
                if d2 < c2 {
                    let dist = d2.sqrt();
                    let dir = if dist > 1e-4 {
                        d / dist
                    } else {
                        let a = k as f32 * 2.399_963;
                        Vec2::new(a.cos(), a.sin())
                    };
                    push += dir * (min_clear - dist + 0.02);
                }
            }
            if push.length_squared() < 1e-6 {
                break;
            }
            *p = (*p + push).clamp(lo, hi);
        }
    }
}

/// One RGB swatch per [`living_rules::look::CLOTH`] word, derived from the look book's outfit
/// colours (`None` where the book holds no outfit for that word).
pub type Swatches = [Option<[u8; 3]>; living_rules::look::CLOTH.len()];

/// Parse `#rrggbb` (or `rrggbb`) into sRGB bytes.
pub fn parse_hex(hex: &str) -> Option<[u8; 3]> {
    let h = hex.trim().trim_start_matches('#');
    if h.len() != 6 {
        return None;
    }
    let n = u32::from_str_radix(h, 16).ok()?;
    Some([((n >> 16) & 0xFF) as u8, ((n >> 8) & 0xFF) as u8, (n & 0xFF) as u8])
}

fn srgb_to_linear(c: f32) -> f32 {
    if c <= 0.04045 { c / 12.92 } else { ((c + 0.055) / 1.055).powf(2.4) }
}

fn linear_to_srgb(c: f32) -> f32 {
    let c = c.clamp(0.0, 1.0);
    if c <= 0.003_130_8 { 12.92 * c } else { 1.055 * c.powf(1.0 / 2.4) - 0.055 }
}

fn rgb_to_hsv(r: f32, g: f32, b: f32) -> (f32, f32, f32) {
    let mx = r.max(g).max(b);
    let mn = r.min(g).min(b);
    let d = mx - mn;
    let h = if d <= 1e-5 {
        0.0
    } else if mx == r {
        ((g - b) / d + if g < b { 6.0 } else { 0.0 }) / 6.0
    } else if mx == g {
        ((b - r) / d + 2.0) / 6.0
    } else {
        ((r - g) / d + 4.0) / 6.0
    };
    let s = if mx > 1e-5 { d / mx } else { 0.0 };
    (h.rem_euclid(1.0), s, mx)
}

fn hsv_to_rgb(h: f32, s: f32, v: f32) -> [u8; 3] {
    let h = h.rem_euclid(1.0) * 6.0;
    let i = h.floor() as i32;
    let f = h - i as f32;
    let p = v * (1.0 - s);
    let q = v * (1.0 - s * f);
    let t = v * (1.0 - s * (1.0 - f));
    let (r, g, b) = match i.rem_euclid(6) {
        0 => (v, t, p),
        1 => (q, v, p),
        2 => (p, v, t),
        3 => (p, q, v),
        4 => (t, p, v),
        _ => (v, p, q),
    };
    [(r.clamp(0.0, 1.0) * 255.0).round() as u8, (g.clamp(0.0, 1.0) * 255.0).round() as u8, (b.clamp(0.0, 1.0) * 255.0).round() as u8]
}

fn smoothstep(e0: f32, e1: f32, x: f32) -> f32 {
    let t = ((x - e0) / (e1 - e0)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

/// Calibrate a look-book HSV mean `(h, s, v)` (from raw pre-lighting outfit albedos) for an unlit
/// flat throng card under the scene's toon lighting:
/// 1. Multiply linear value by [`TOON_SUN_GAIN`] (~2.35×, matching `toon_light.wesl` `sun_color()`
///    at noon), since unlit cards bypass the sun's linear exposure gain.
/// 2. Smoothly lift chroma and dark-chromatic value for chromatic words (`s > 0.14`, leaving
///    neutrals like `black`, `tan` and `cream` faithful) so flat 2D cards stay distinct from grey
///    stone paving even under warm noon light.
pub fn calibrate_swatch(h: f32, s: f32, v: f32) -> [u8; 3] {
    let v_lit = linear_to_srgb((srgb_to_linear(v) * TOON_SUN_GAIN).min(1.0));
    let chroma_w = smoothstep(0.14, 0.22, s);
    let s_cal = (s + chroma_w * (s.sqrt() - s) * 0.95).clamp(0.0, 0.95);
    let v_cal = (v_lit + chroma_w * (v_lit.powf(0.75) - v_lit) * 0.60).clamp(0.0, 1.0);
    hsv_to_rgb(h, s_cal, v_cal)
}

/// Strip gender (`-f`/`-m`) and trailing numeric variant (`_58`) from an outfit piece name.
fn outfit_stem(piece: &str) -> &str {
    let s = piece.trim_end_matches("-f").trim_end_matches("-m");
    s.rsplit_once('_').filter(|(_, n)| !n.is_empty() && n.chars().all(|c| c.is_ascii_digit())).map_or(s, |(stem, _)| stem)
}

/// The RGB of the top garment named by `top_words` ("a green smock with an apron", "a yellow coat",
/// "a cream jersey") from a line's `colors.outfit` map. Matches the named garment piece first so
/// an apron worn over a smock never shifts the smock's colour.
pub fn top_piece_rgb(top_words: &str, outfit: &BTreeMap<String, String>) -> Option<[u8; 3]> {
    let mut words = top_words.split_whitespace();
    let first = words.next().unwrap_or("");
    let colour = if first == "a" || first == "an" { words.next().unwrap_or("") } else { first };
    let garment = words.next().unwrap_or("");
    let _ = colour;
    if !garment.is_empty() {
        if let Some(hex) = outfit.iter().find(|(k, _)| outfit_stem(k) == garment).map(|(_, v)| v) {
            if let Some(rgb) = parse_hex(hex) {
                return Some(rgb);
            }
        }
    }
    // Fallback: main upper garment (coat/smock, then jersey), excluding aprons and trims.
    for want in ["coat", "smock", "jersey"] {
        if let Some(hex) = outfit.iter().find(|(k, _)| outfit_stem(k) == want).map(|(_, v)| v) {
            if let Some(rgb) = parse_hex(hex) {
                return Some(rgb);
            }
        }
    }
    None
}

/// Derive one swatch per [`living_rules::look::CLOTH`] word from the look book's top-garment
/// outfit RGBs: saturation-weighted circular mean hue, mean saturation and mean value in HSV
/// (so multi-shade words such as `green` do not cancel chroma in RGB averaging), calibrated for
/// unlit cards via [`calibrate_swatch`]. Words with no outfit in the book stay `None`.
pub fn swatches_of(book: &crate::characters::book::LookBook) -> Swatches {
    use living_rules::look::{cloth_index, CLOTH, NO_CLOTH};
    let mut hx = [0.0f64; CLOTH.len()];
    let mut hy = [0.0f64; CLOTH.len()];
    let mut sum_s = [0.0f64; CLOTH.len()];
    let mut sum_v = [0.0f64; CLOTH.len()];
    let mut count = [0u64; CLOTH.len()];
    for line in book.lines.values() {
        let Some(top) = line.words.get("top").and_then(|v| v.as_str()) else { continue };
        let idx = cloth_index(top);
        if idx == NO_CLOTH || (idx as usize) >= CLOTH.len() {
            continue;
        }
        let Some(rgb) = top_piece_rgb(top, &line.person.colors.outfit) else { continue };
        let (h, s, v) = rgb_to_hsv(rgb[0] as f32 / 255.0, rgb[1] as f32 / 255.0, rgb[2] as f32 / 255.0);
        let ang = (h as f64) * std::f64::consts::TAU;
        let w = (s as f64).max(1e-3);
        let i = idx as usize;
        hx[i] += ang.cos() * w;
        hy[i] += ang.sin() * w;
        sum_s[i] += s as f64;
        sum_v[i] += v as f64;
        count[i] += 1;
    }
    let mut out = [None; CLOTH.len()];
    for i in 0..CLOTH.len() {
        if count[i] > 0 {
            let n = count[i] as f64;
            let h_mean = (hy[i].atan2(hx[i]) / std::f64::consts::TAU).rem_euclid(1.0) as f32;
            let s_mean = (sum_s[i] / n) as f32;
            let v_mean = (sum_v[i] / n) as f32;
            out[i] = Some(calibrate_swatch(h_mean, s_mean, v_mean));
        }
    }
    out
}

/// Swatches derived once from the client's look book; any word with no outfit in the book is
/// logged once and left `None` (neutral).
pub fn swatches() -> &'static Swatches {
    static CACHE: std::sync::OnceLock<Swatches> = std::sync::OnceLock::new();
    CACHE.get_or_init(|| match crate::characters::book::book() {
        Some(book) => {
            let s = swatches_of(book);
            for (i, word) in living_rules::look::CLOTH.iter().enumerate() {
                if s[i].is_none() {
                    info!("throng: cloth word {word:?} has no outfit in the look book; using neutral tint");
                }
            }
            s
        }
        None => {
            warn!("throng: no look book; throng cards use neutral tint");
            [None; living_rules::look::CLOTH.len()]
        }
    })
}

/// Each card's top colour, from the row's colour summary (`colour_a/b/c`) using `palette`.
/// Person cards take the three top colours in proportion to their counts (the rest neutral `None`,
/// as is any colour word with no swatch in `palette`); animal cards always stay `None`.
pub fn tops_with(row: &Row, kinds: &[Kind], palette: &Swatches) -> Vec<Option<[u8; 3]>> {
    use living_rules::look::NO_CLOTH;
    let n_people = kinds.iter().filter(|k| **k == Kind::Person).count();
    if n_people == 0 {
        return vec![None; kinds.len()];
    }
    let slots: Vec<(Option<[u8; 3]>, usize)> = row
        .colours
        .iter()
        .filter(|&&(idx, cnt)| idx != NO_CLOTH && cnt > 0)
        .map(|&(idx, cnt)| (palette.get(idx as usize).copied().flatten(), cnt as usize))
        .collect();
    let total_c: usize = slots.iter().map(|(_, c)| *c).sum();
    let mut items: Vec<(Option<[u8; 3]>, usize)> = if total_c <= n_people {
        let mut v = slots;
        let rest = n_people - total_c;
        if rest > 0 {
            v.push((None, rest));
        }
        v
    } else {
        let weights: Vec<usize> = slots.iter().map(|(_, c)| *c).collect();
        let alloc = apportion(n_people, &weights, false);
        slots.into_iter().zip(alloc).map(|((rgb, _), c)| (rgb, c)).collect()
    };
    if items.is_empty() {
        items.push((None, n_people));
    }
    let mut person_tops = distribute_smooth(&items).into_iter();
    kinds.iter().map(|k| if *k == Kind::Person { person_tops.next().flatten() } else { None }).collect()
}

/// Each card's top colour, from the row's colour summary and the look book's derived swatches.
pub fn tops(row: &Row, kinds: &[Kind]) -> Vec<Option<[u8; 3]>> {
    tops_with(row, kinds, swatches())
}

/// How an unlit card is shaded under the scene's light: the key light's colour (sRGB) times its
/// share of the day's illuminance, at least [`NIGHT_SHADE`]; full white without an atmosphere.
pub fn shade(atmo: Option<&crate::daylight::Atmo>) -> Vec3 {
    match atmo.filter(|a| a.active) {
        Some(a) => Vec3::from(a.light) * (a.lux / DAY_LUX).clamp(NIGHT_SHADE, 1.0),
        None => Vec3::ONE,
    }
}

/// One card drawn.
struct Card {
    entity: Entity,
    blob: Entity,
    mat: Handle<StandardMaterial>,
    pose: Pose,
    kind: Kind,
    top: Option<[u8; 3]>,
    /// Where it stands now and where it is going (map m).
    at: Vec2,
    to: Vec2,
    /// Drawn (0 gone, 1 full) and toward which.
    alpha: f32,
    target: f32,
    /// Whether the card is currently in opaque `AlphaMode::Mask` (steady state) vs `AlphaMode::Blend`
    /// (during spawn/despawn fade transitions).
    masked: bool,
    /// A number of its own, for its stepping.
    seed: f32,
}

/// A square's cards and the row they show.
struct Square {
    row: Row,
    cards: Vec<Card>,
}

/// The throng as drawn, for the dump, `heed.rs`'s picks and the drawing.
#[derive(Resource, Default)]
pub struct Throng {
    /// The rows taken this frame (none while the throng is not drawn).
    pub rows: Vec<Row>,
    /// Whether the set in place has my throng (heed for players on), and whether it is drawn.
    pub on: bool,
    pub drawn: bool,
    /// The throng card currently under the cursor, if any: `(row, click ground point inside row)`.
    /// Computed once per frame in [`pick`] while heed is on and drawn; always `None` when off.
    pub under: Option<(Row, Vec2)>,
    squares: BTreeMap<(u32, u8), Square>,
    /// Cards fading out after their square went.
    leaving: Vec<Card>,
}

impl Throng {
    /// The square of a card standing within [`PICK_M`] of a ground point (map m), and that card's
    /// place: a click on a crowd figure (`heed.rs`).
    pub fn card_at(&self, ground: Vec2) -> Option<(Row, Vec2)> {
        self.squares
            .values()
            .flat_map(|s| s.cards.iter().filter(|c| c.target > 0.5).map(move |c| (s.row, c.at, c.at.distance(ground))))
            .filter(|(_, _, d)| *d < PICK_M)
            .min_by(|a, b| a.2.total_cmp(&b.2))
            .map(|(r, at, _)| (r, at))
    }

    /// The card under the cursor: front-most card whose screen outline holds `cursor`, else the
    /// nearest card within [`PICK_M`] of `ground`. Returns `(row, click ground point clamped into row)`.
    pub fn card_under(&self, cursor: Option<Vec2>, camera: Option<(&Camera, &GlobalTransform)>, ground: Option<Vec2>, ground_y: impl Fn(Vec2) -> f32) -> Option<(Row, Vec2)> {
        if let (Some(cur), Some((cam, gtf))) = (cursor, camera) {
            let eye = gtf.translation();
            let cam_up = gtf.up().as_vec3();
            let scale = billboard_scale(gtf.forward().as_vec3());
            let mut best: Option<(f32, Row, Vec2)> = None;
            for sq in self.squares.values() {
                for c in sq.cards.iter().filter(|c| c.target > 0.5) {
                    let (w, h) = if c.kind == Kind::Person { (PICK_W, CARD.1) } else { BEAST };
                    let y = ground_y(c.at);
                    let feet = Vec3::new(c.at.x, y, c.at.y);
                    let head = feet + cam_up * (h * scale);
                    let (Ok(f), Ok(t)) = (cam.world_to_viewport(gtf, feet), cam.world_to_viewport(gtf, head)) else { continue };
                    let ppm = (f.y - t.y).abs() / (h * scale).max(0.1);
                    let half = (w * scale * 0.5 * ppm).max(6.0);
                    let (left, right) = (f.x.min(t.x) - half, f.x.max(t.x) + half);
                    let (top, bottom) = (f.y.min(t.y) - 0.1 * ppm, f.y.max(t.y) + 0.1 * ppm);
                    if cur.x >= left && cur.x <= right && cur.y >= top && cur.y <= bottom {
                        let depth = eye.distance((feet + head) * 0.5);
                        if best.is_none_or(|(d, _, _)| depth < d) {
                            let pt = ground.filter(|g| sq.row.holds(*g)).unwrap_or(c.at);
                            best = Some((depth, sq.row, sq.row.clamp(pt)));
                        }
                    }
                }
            }
            if let Some((_, row, at)) = best {
                return Some((row, at));
            }
        }
        ground.and_then(|g| self.card_at(g).map(|(row, _)| (row, row.clamp(g))))
    }

    /// The dump's view: each row with the cards drawn for it.
    pub fn json(&self) -> serde_json::Value {
        let sw = swatches();
        let has_book = sw.iter().any(Option::is_some);
        let rows: Vec<serde_json::Value> = self
            .squares
            .values()
            .map(|s| {
                let live: Vec<&Card> = s.cards.iter().filter(|c| c.target > 0.5).collect();
                let n = |p: Pose| live.iter().filter(|c| c.pose == p).count();
                let k = |x: Kind| live.iter().filter(|c| c.kind == x).count();
                let r = &s.row;
                let centroid = r.centre();
                let mean_card = if live.is_empty() {
                    None
                } else {
                    let sum = live.iter().fold(Vec2::ZERO, |acc, c| acc + c.to);
                    let m = sum / live.len() as f32;
                    Some([m.x, m.y])
                };
                let sample_card = live.first().map(|c| [c.at.x, c.at.y]);
                let mut rgb: BTreeMap<String, usize> = BTreeMap::new();
                for c in &live {
                    if let Some([cr, cg, cb]) = c.top {
                        *rgb.entry(format!("#{cr:02x}{cg:02x}{cb:02x}")).or_insert(0) += 1;
                    }
                }
                serde_json::json!({
                    "id": r.id, "cell": [r.cx, r.cy], "size": r.size, "count": r.count, "spread": r.spread, "heading": r.heading,
                    "moving": r.moving, "fighting": r.fighting, "kinds": r.kinds,
                    "by_kind": [r.people, r.wolves, r.deer, r.others],
                    "colours": [[r.colours[0].0, r.colours[0].1], [r.colours[1].0, r.colours[1].1], [r.colours[2].0, r.colours[2].1]],
                    "centre": [r.centre_x, r.centre_y],
                    "centroid": [centroid.x, centroid.y],
                    "mean_card": mean_card,
                    "sample_card": sample_card,
                    "cards": live.len(), "stand": n(Pose::Stand), "walk": n(Pose::Walk), "fight": n(Pose::Fight),
                    "people": k(Kind::Person), "animals": live.len() - k(Kind::Person),
                    "card_kinds": {"person": k(Kind::Person), "wolf": k(Kind::Wolf), "deer": k(Kind::Deer), "other": k(Kind::Other)},
                    "inside": live.iter().all(|c| r.holds(c.to)),
                    "tinted": live.iter().filter(|c| c.top.is_some()).count(),
                    "rgb": rgb,
                })
            })
            .collect();
        serde_json::json!({
            "on": self.on, "drawn": self.drawn, "rows": self.rows.len(),
            "count": self.rows.iter().map(|r| r.count as u64).sum::<u64>(),
            "cards": self.squares.values().map(|s| s.cards.iter().filter(|c| c.target > 0.5).count()).sum::<usize>(),
            "leaving": self.leaving.len() + self.squares.values().map(|s| s.cards.iter().filter(|c| c.target < 0.5).count()).sum::<usize>(),
            "tint": if has_book { "book" } else { "placeholder" },
            "under": self.under.map(|(r, at)| serde_json::json!({"cell": [r.cx, r.cy], "size": r.size, "at": [at.x, at.y]})),
            "squares": rows,
        })
    }
}

/// The shared meshes and textures.
#[derive(Resource)]
struct Kit {
    card: Handle<Mesh>,
    beast: Handle<Mesh>,
    blob: Handle<Mesh>,
    ring: Handle<Mesh>,
    blob_mat: Handle<StandardMaterial>,
    /// Ring materials: a pin, my focus.
    pin_mat: Handle<StandardMaterial>,
    focus_mat: Handle<StandardMaterial>,
    /// Textures by (kind, pose, top colour; none the placeholder).
    tex: BTreeMap<(Kind, Pose, Option<[u8; 3]>), Handle<Image>>,
}

/// Rings under whom I keep track of.
#[derive(Component)]
struct Ring;

pub struct ThrongPlugin;

impl Plugin for ThrongPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Throng>()
            .add_systems(Update, pick.in_set(crate::phase::Phase::Input).after(crate::ui::UiInput).before(crate::combat::input))
            .add_systems(Update, (take, draw, rings).chain().in_set(crate::phase::Phase::Camera).after(crate::camera::follow));
    }
}

/// Update [`Throng::under`] once per frame while heed for players is on and drawn.
#[allow(clippy::too_many_arguments)]
fn pick(
    pointer: Res<crate::pointer::Pointer>,
    cam: Res<crate::camera::Cam>,
    scene: NonSend<crate::world::Scene>,
    island: Option<Res<crate::island::Island>>,
    cams: Query<&Camera, With<Camera3d>>,
    mut t: ResMut<Throng>,
) {
    if !t.on || !t.drawn || t.squares.is_empty() {
        t.under = None;
        return;
    }
    let camera = cams.single().ok().map(|c| (c, &cam.pose));
    let ground_pt = cam.cursor_ground.map(|g| Vec2::new(g.x, g.z));
    let isl = island.as_deref();
    t.under = t.card_under(pointer.pos, camera, ground_pt, |p| ground(isl, &scene, p).y);
}

fn soft(w: u32, h: u32, alpha: impl Fn(f32, f32) -> f32) -> Image {
    let mut px = Vec::with_capacity((w * h * 4) as usize);
    for j in 0..h {
        for i in 0..w {
            let a = alpha((i as f32 + 0.5) / w as f32, 1.0 - (j as f32 + 0.5) / h as f32).clamp(0.0, 1.0);
            px.extend_from_slice(&[255, 255, 255, (a * 255.0) as u8]);
        }
    }
    Image::new(Extent3d { width: w, height: h, depth_or_array_layers: 1 }, TextureDimension::D2, px, TextureFormat::Rgba8UnormSrgb, RenderAssetUsages::default())
}

fn edge(d: f32) -> f32 {
    (0.5 - d / 0.03).clamp(0.0, 1.0)
}

/// Distance from a point to a segment, less a radius (m).
fn seg(p: Vec2, a: Vec2, b: Vec2, r: f32) -> f32 {
    let ab = b - a;
    let t = ((p - a).dot(ab) / ab.length_squared()).clamp(0.0, 1.0);
    (p - (a + ab * t)).length() - r
}

/// Which part of a person card a point is (0 none, 1 head, 2 top and arms, 3 legs, 4 spear shaft,
/// 5 spearhead) and its distance outside it (m); u across, v up. Slender upright silhouettes
/// matching 3D characters: standing, walking (legs in stride, arms swinging; facing +u), and
/// fighting (compact athletic stance, tucked arms, spear angled diagonally forward-and-up with a
/// steel tip).
fn person_part(u: f32, v: f32, pose: Pose) -> (u8, f32) {
    let p = Vec2::new((u - 0.5) * CARD.0, v * CARD.1);
    let (head, top, legs, spear, tip) = match pose {
        Pose::Fight => (
            (p - Vec2::new(0.03, 1.48)).length() - 0.115,
            seg(p, Vec2::new(-0.01, 0.87), Vec2::new(0.02, 1.28), 0.140)
                .min(seg(p, Vec2::new(0.13, 1.24), Vec2::new(0.24, 1.15), 0.044))
                .min(seg(p, Vec2::new(-0.13, 1.24), Vec2::new(-0.15, 0.96), 0.044)),
            seg(p, Vec2::new(-0.06, 0.86), Vec2::new(-0.18, 0.04), 0.056)
                .min(seg(p, Vec2::new(0.06, 0.86), Vec2::new(0.16, 0.04), 0.056)),
            seg(p, Vec2::new(-0.20, 0.72), Vec2::new(0.32, 1.54), 0.026),
            seg(p, Vec2::new(0.31, 1.52), Vec2::new(0.38, 1.65), 0.036),
        ),
        Pose::Walk => (
            (p - Vec2::new(0.03, 1.49)).length() - 0.115,
            seg(p, Vec2::new(0.0, 0.88), Vec2::new(0.02, 1.29), 0.140)
                .min(seg(p, Vec2::new(-0.14, 1.26), Vec2::new(-0.24, 0.92), 0.044))
                .min(seg(p, Vec2::new(0.14, 1.26), Vec2::new(0.23, 0.94), 0.044)),
            seg(p, Vec2::new(-0.055, 0.86), Vec2::new(-0.18, 0.04), 0.055)
                .min(seg(p, Vec2::new(0.055, 0.86), Vec2::new(0.17, 0.05), 0.055)),
            f32::MAX,
            f32::MAX,
        ),
        Pose::Stand => (
            (p - Vec2::new(0.0, 1.50)).length() - 0.115,
            seg(p, Vec2::new(0.0, 0.88), Vec2::new(0.0, 1.30), 0.140)
                .min(seg(p, Vec2::new(-0.16, 1.28), Vec2::new(-0.19, 0.86), 0.044))
                .min(seg(p, Vec2::new(0.16, 1.28), Vec2::new(0.19, 0.86), 0.044)),
            seg(p, Vec2::new(-0.065, 0.86), Vec2::new(-0.08, 0.04), 0.055)
                .min(seg(p, Vec2::new(0.065, 0.86), Vec2::new(0.08, 0.04), 0.055)),
            f32::MAX,
            f32::MAX,
        ),
    };
    [(1u8, head), (2, top), (3, legs), (4, spear), (5, tip)].into_iter().fold((0u8, f32::MAX), |a, b| if b.1 < a.1 { b } else { a })
}

/// An animal stand-in (u across, v up; facing +u): a body, a head, four legs; the pose moves the
/// legs (a stride walking or fighting).
fn beast_part(u: f32, v: f32, pose: Pose, kind: Kind) -> f32 {
    let p = Vec2::new((u - 0.5) * BEAST.0, v * BEAST.1);
    let tall = if kind == Kind::Deer { 0.12 } else { 0.0 };
    let body = seg(p, Vec2::new(-0.36, 0.5 + tall), Vec2::new(0.3, 0.52 + tall), 0.15);
    let head = (p - Vec2::new(0.46, 0.66 + tall * 1.8)).length() - 0.1;
    let neck = seg(p, Vec2::new(0.3, 0.55 + tall), Vec2::new(0.44, 0.64 + tall * 1.8), 0.05);
    let s = if pose == Pose::Stand { 0.0 } else { 0.1 };
    let legs = [(-0.3, -s), (-0.22, s), (0.2, -s), (0.28, s)].into_iter().map(|(x, d)| seg(p, Vec2::new(x, 0.45 + tall), Vec2::new(x + d, 0.03), 0.04)).fold(f32::MAX, f32::min);
    let tail = seg(p, Vec2::new(-0.48, 0.56 + tall), Vec2::new(-0.6, 0.4 + tall), 0.03);
    body.min(head).min(neck).min(legs).min(tail)
}

/// A card's texture: a person in the placeholder tint or calibrated top colour (skin, top, dark
/// trousers, spear + bright spearhead when fighting), or an animal stand-in, with a subtle dark
/// ink silhouette outline (`OUTLINE_M` wide, [`INK`]) so light garments stay readable against stone
/// paving and cards stay cleanly separated under `AlphaMode::Mask(0.5)`.
fn card_image(kind: Kind, pose: Pose, top: Option<[u8; 3]>) -> Image {
    let (w, h) = if kind == Kind::Person { (64u32, 128u32) } else { (96u32, 70u32) };
    let mut px = Vec::with_capacity((w * h * 4) as usize);
    for j in 0..h {
        for i in 0..w {
            let (u, v) = ((i as f32 + 0.5) / w as f32, 1.0 - (j as f32 + 0.5) / h as f32);
            let (c, d) = if kind == Kind::Person {
                let (part, d) = person_part(u, v, pose);
                let c = match (top, part) {
                    (Some(_), 1) => SKIN,
                    (Some(t), 2) => t,
                    (Some(_), 3) => TROUSERS,
                    (_, 4) => SPEAR,
                    (_, 5) => SPEAR_TIP,
                    (None, 1) => PLACEHOLDER_HEAD,
                    (None, 3) => PLACEHOLDER_LEGS,
                    _ => top.unwrap_or(PLACEHOLDER),
                };
                (c, d)
            } else {
                (top.unwrap_or(PLACEHOLDER_LEGS), beast_part(u, v, pose, kind))
            };
            // Silhouette extends by `OUTLINE_M`; outer edge blends softly toward `INK` (78% max)
            // so cards separate cleanly from grey stone without heavy sticker-thick borders.
            let a = edge(d - OUTLINE_M);
            let ink_t = ((d + 0.004) / 0.014).clamp(0.0, 1.0) * 0.78;
            let r = (c[0] as f32 * (1.0 - ink_t) + INK[0] as f32 * ink_t).round() as u8;
            let g = (c[1] as f32 * (1.0 - ink_t) + INK[1] as f32 * ink_t).round() as u8;
            let b = (c[2] as f32 * (1.0 - ink_t) + INK[2] as f32 * ink_t).round() as u8;
            px.extend_from_slice(&[r, g, b, (a * 255.0) as u8]);
        }
    }
    Image::new(Extent3d { width: w, height: h, depth_or_array_layers: 1 }, TextureDimension::D2, px, TextureFormat::Rgba8UnormSrgb, RenderAssetUsages::default())
}

/// A ground ring texture: a bold band (`0.72..=0.96`) framed by a thin dark ink border
/// (`0.68..0.72` and `0.96..=1.0`) so green pin and amber focus rings read clearly at Far zoom.
fn ring_image(size: u32) -> Image {
    let mut px = Vec::with_capacity((size * size * 4) as usize);
    for j in 0..size {
        for i in 0..size {
            let u = (i as f32 + 0.5) / size as f32;
            let v = 1.0 - (j as f32 + 0.5) / size as f32;
            let r = Vec2::new(u - 0.5, v - 0.5).length() * 2.0;
            let (rgb, a) = if (0.72..=0.95).contains(&r) {
                (255u8, 255u8)
            } else if (0.67..=1.0).contains(&r) {
                (48u8, 235u8)
            } else {
                (0u8, 0u8)
            };
            px.extend_from_slice(&[rgb, rgb, rgb, a]);
        }
    }
    Image::new(Extent3d { width: size, height: size, depth_or_array_layers: 1 }, TextureDimension::D2, px, TextureFormat::Rgba8UnormSrgb, RenderAssetUsages::default())
}

/// The kit, made the first time a throng is drawn.
fn kit(meshes: &mut Assets<Mesh>, images: &mut Assets<Image>, mats: &mut Assets<StandardMaterial>) -> Kit {
    let blob_tex = images.add(soft(48, 48, |u, v| {
        let a = (1.0 - Vec2::new(u - 0.5, v - 0.5).length() * 2.0).clamp(0.0, 1.0);
        a * a * (3.0 - 2.0 * a)
    }));
    let ring_tex = images.add(ring_image(64));
    let ring = |c: [f32; 3], mats: &mut Assets<StandardMaterial>| mats.add(StandardMaterial { base_color: Color::srgba(c[0], c[1], c[2], 0.98), base_color_texture: Some(ring_tex.clone()), unlit: true, alpha_mode: AlphaMode::Blend, depth_bias: 80.0, ..default() });
    Kit {
        card: meshes.add(Rectangle::new(CARD.0, CARD.1)),
        beast: meshes.add(Rectangle::new(BEAST.0, BEAST.1)),
        blob: meshes.add(Circle::new(0.5)),
        ring: meshes.add(Circle::new(1.0)),
        blob_mat: mats.add(StandardMaterial { base_color: Color::srgba(0.05, 0.05, 0.08, 0.56), base_color_texture: Some(blob_tex), unlit: true, alpha_mode: AlphaMode::Blend, depth_bias: 35.0, ..default() }),
        pin_mat: ring([0.15, 0.95, 0.35], mats),
        focus_mat: ring([1.0, 0.72, 0.10], mats),
        tex: BTreeMap::new(),
    }
}

/// This frame's rows, from the set in place (`net::throng`); none while not drawn.
fn take(net: NonSend<Net>, prefs: Res<crate::keys::Prefs>, mut t: ResMut<Throng>) {
    let on = net.conn.as_ref().is_some_and(|c| c.throng_table());
    t.on = on;
    t.drawn = on && prefs.throng;
    t.rows = match net.conn.as_ref().filter(|_| t.drawn) {
        Some(c) => {
            let mut v: Vec<Row> = crate::net::throng(c).iter().map(Row::of).collect();
            v.sort_by_key(|r| r.key());
            v
        }
        None => Vec::new(),
    };
}

fn ground(island: Option<&crate::island::Island>, scene: &crate::world::Scene, p: Vec2) -> Vec3 {
    match island {
        Some(i) => Vec3::new(p.x, i.foot_height(p.x, p.y), p.y),
        None => scene.at3(p.x, p.y),
    }
}

/// Spawn, update in place and fade the cards, and orient them upright to the camera.
#[allow(clippy::too_many_arguments)]
fn draw(
    mut commands: Commands,
    mut t: ResMut<Throng>,
    kit_res: Option<ResMut<Kit>>,
    net: NonSend<Net>,
    scene: NonSend<crate::world::Scene>,
    island: Option<Res<crate::island::Island>>,
    cam: Res<crate::camera::Cam>,
    heed: Option<Res<crate::heed::Heed>>,
    time: Res<Time>,
    (mut meshes, mut images, mut mats): (ResMut<Assets<Mesh>>, ResMut<Assets<Image>>, ResMut<Assets<StandardMaterial>>),
    mut tfs: Query<&mut Transform>,
    atmo: Option<Res<crate::daylight::Atmo>>,
) {
    if t.rows.is_empty() && t.squares.is_empty() && t.leaving.is_empty() {
        return;
    }
    let mut kit = match kit_res {
        Some(k) => k,
        None => {
            commands.insert_resource(kit(&mut meshes, &mut images, &mut mats));
            return;
        }
    };
    let dt = time.delta_secs();
    let now = time.elapsed_secs();
    let remains: Vec<Vec2> = net
        .conn
        .as_ref()
        .map(|c| c.db.structure().iter().filter(|s| s.kind == "remains").map(|s| Vec2::new(s.x, s.y)).collect())
        .unwrap_or_default();
    let marked_ids: Vec<u32> = heed.as_ref().filter(|h| h.on).map(|h| h.marks().into_iter().map(|(id, _)| id).collect()).unwrap_or_default();
    let mut perceived_pts: Vec<Vec2> = Vec::with_capacity(scene.shown.len());
    let mut marked_pts: Vec<Vec2> = Vec::with_capacity(marked_ids.len());
    for (&id, &(pos, _)) in &scene.shown {
        if marked_ids.contains(&id) {
            marked_pts.push(pos);
        } else {
            perceived_pts.push(pos);
        }
    }
    let t = &mut *t;
    // Rows to squares: a row's square keeps its cards; its count, poses and kinds are dealt
    // to them in a fixed order, so an unchanged row moves nothing.
    let mut seen: Vec<(u32, u8)> = Vec::with_capacity(t.rows.len());
    for row in t.rows.clone() {
        let key = row.key();
        seen.push(key);
        let sq = t.squares.entry(key).or_insert_with(|| Square { row, cards: Vec::new() });
        sq.row = row;
        let n = row.count as usize;
        let mut to = places(&row, n);
        if n > 0 {
            let lo = row.origin() + Vec2::splat(0.25);
            let hi = row.origin() + Vec2::splat(row.side() - 0.25);
            let near = |src: &[Vec2], clear: f32| -> Vec<Vec2> {
                src.iter()
                    .copied()
                    .filter(|r| r.x >= lo.x - clear && r.x <= hi.x + clear && r.y >= lo.y - clear && r.y <= hi.y + clear)
                    .collect()
            };
            if !remains.is_empty() {
                avoid_obstacles(&mut to, &near(&remains, MOUND_CLEAR_M), MOUND_CLEAR_M, lo, hi);
            }
            if !perceived_pts.is_empty() {
                avoid_obstacles(&mut to, &near(&perceived_pts, PERCEIVED_CLEAR_M), PERCEIVED_CLEAR_M, lo, hi);
            }
            if !marked_pts.is_empty() {
                avoid_obstacles(&mut to, &near(&marked_pts, RING_CLEAR_M), RING_CLEAR_M, lo, hi);
            }
        }
        let poses = row.poses();
        let kinds = row.card_kinds();
        let top = tops(&row, &kinds);
        // Cards past the count fade out (in place); the rest are dealt their place and pose.
        for (k, c) in sq.cards.iter_mut().enumerate() {
            if k >= n {
                c.target = 0.0;
            }
        }
        for k in 0..n {
            let (pose, kind) = (poses[k], kinds[k]);
            if k < sq.cards.len() {
                let c = &mut sq.cards[k];
                c.to = to[k];
                c.target = 1.0;
                if (c.pose, c.kind, c.top) != (pose, kind, top[k]) {
                    let mesh_changed = (c.kind == Kind::Person) != (kind == Kind::Person);
                    c.pose = pose;
                    c.kind = kind;
                    c.top = top[k];
                    let tex = kit.tex.entry((kind, pose, top[k])).or_insert_with(|| images.add(card_image(kind, pose, top[k]))).clone();
                    if let Some(mut m) = mats.get_mut(&c.mat) {
                        m.base_color_texture = Some(tex);
                    }
                    if mesh_changed {
                        let mesh = if kind == Kind::Person { kit.card.clone() } else { kit.beast.clone() };
                        commands.entity(c.entity).insert(Mesh3d(mesh));
                    }
                }
                continue;
            }
            let tex = kit.tex.entry((kind, pose, top[k])).or_insert_with(|| images.add(card_image(kind, pose, top[k]))).clone();
            let mat = mats.add(StandardMaterial { base_color: Color::srgba(1.0, 1.0, 1.0, 0.0), base_color_texture: Some(tex), unlit: true, alpha_mode: AlphaMode::Blend, cull_mode: None, ..default() });
            let mesh = if kind == Kind::Person { kit.card.clone() } else { kit.beast.clone() };
            let base = ground(island.as_deref(), &scene, to[k]);
            let entity = commands.spawn((Mesh3d(mesh), MeshMaterial3d(mat.clone()), Transform::from_translation(base), Visibility::Visible, bevy::light::NotShadowCaster, Name::new("throng card"))).id();
            let blob = commands
                .spawn((Mesh3d(kit.blob.clone()), MeshMaterial3d(kit.blob_mat.clone()), Transform::from_translation(base + Vec3::Y * 0.05).with_rotation(Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2)).with_scale(Vec3::ZERO), Visibility::Visible, bevy::light::NotShadowCaster))
                .id();
            let seed = (row.cx.wrapping_mul(31) ^ row.cy.wrapping_mul(17)).wrapping_add(k as u32 * 7) as f32 * 0.618;
            sq.cards.push(Card { entity, blob, mat, pose, kind, top: top[k], at: to[k], to: to[k], alpha: 0.0, target: 1.0, masked: false, seed });
        }
    }
    // Squares no longer in the rows: their cards fade out.
    let gone: Vec<(u32, u8)> = t.squares.keys().filter(|k| !seen.contains(k)).copied().collect();
    for k in gone {
        if let Some(sq) = t.squares.remove(&k) {
            t.leaving.extend(sq.cards.into_iter().map(|mut c| {
                c.target = 0.0;
                c.to = c.at;
                c
            }));
        }
    }
    let lit = shade(atmo.as_deref());
    let cam_rot = cam.pose.rotation();
    let cam_up = cam.pose.up().as_vec3();
    let right = cam.pose.right().as_vec3();
    let scale = billboard_scale(cam.pose.forward().as_vec3());
    let mut step = |c: &mut Card, heading: Option<Vec2>| -> bool {
        // Fade toward its target.
        let rate = if c.target > c.alpha { dt / IN_S } else { dt / OUT_S };
        c.alpha = if c.target > c.alpha { (c.alpha + rate).min(c.target) } else { (c.alpha - rate).max(c.target) };
        c.at = c.at.move_towards(c.to, GLIDE_MPS * dt);
        // Walking steps along the way; fighting lunges a little; standing keeps still.
        let (sway, lift) = match (c.pose, heading) {
            (Pose::Walk, Some(h)) => (h * 0.25 * (now * 1.7 + c.seed).sin(), 0.04 * (now * 7.0 + c.seed).sin().abs()),
            (Pose::Fight, _) => (heading.unwrap_or(Vec2::X) * 0.08 * (now * 3.1 + c.seed).sin(), 0.0),
            _ => (Vec2::ZERO, 0.0),
        };
        let p = c.at + sway;
        let base = ground(island.as_deref(), &scene, p);
        let half = if c.kind == Kind::Person { CARD.1 * 0.5 } else { BEAST.1 * 0.5 };
        // Mirrored to face the way it walks, as the camera sees it.
        let face = heading.map(|h| Vec3::new(h.x, 0.0, h.y)).filter(|_| c.pose != Pose::Stand);
        let flip = if face.is_some_and(|f| f.dot(right) < 0.0) { -1.0 } else { 1.0 };
        if let Ok(mut tf) = tfs.get_mut(c.entity) {
            *tf = Transform::from_translation(base + cam_up * (half * scale + lift))
                .with_rotation(cam_rot)
                .with_scale(Vec3::new(flip * scale, scale, 1.0));
        }
        if let Ok(mut tf) = tfs.get_mut(c.blob) {
            tf.translation = base + Vec3::Y * 0.03;
            let (rx, ry) = if c.kind == Kind::Person { (0.76, 0.52) } else { (1.15, 0.75) };
            tf.scale = Vec3::new(c.alpha * rx, c.alpha * ry, 1.0);
        }
        // Steady-state cards use opaque `AlphaMode::Mask(0.5)` so they write depth cleanly (no
        // translucent ghosting, no remains-mound outlines drawing over cards); `AlphaMode::Blend`
        // is used only during spawn/despawn crossfades.
        let want_masked = c.alpha >= 0.99 && c.target >= 0.99;
        if let Some(mut m) = mats.get_mut(&c.mat) {
            if want_masked != c.masked {
                c.masked = want_masked;
                m.alpha_mode = if want_masked { AlphaMode::Mask(0.5) } else { AlphaMode::Blend };
            }
            let alpha = if want_masked { 1.0 } else { c.alpha };
            let want = Color::srgba(lit.x, lit.y, lit.z, alpha);
            let (h, w) = (m.base_color.to_srgba(), want.to_srgba());
            if (h.alpha - w.alpha).abs() > 0.004 || (h.red - w.red).abs() > 0.01 || (h.green - w.green).abs() > 0.01 || (h.blue - w.blue).abs() > 0.01 {
                m.base_color = want;
            }
        }
        // Gone: fully faded out.
        c.target <= 0.0 && c.alpha <= 0.0
    };
    let mut dead: Vec<Card> = Vec::new();
    for sq in t.squares.values_mut() {
        let h = sq.row.heading_dir();
        let mut k = 0;
        while k < sq.cards.len() {
            if step(&mut sq.cards[k], h) && k >= sq.row.count as usize {
                dead.push(sq.cards.remove(k));
            } else {
                k += 1;
            }
        }
    }
    let mut k = 0;
    while k < t.leaving.len() {
        if step(&mut t.leaving[k], None) {
            dead.push(t.leaving.swap_remove(k));
        } else {
            k += 1;
        }
    }
    for c in dead {
        commands.entity(c.entity).despawn();
        commands.entity(c.blob).despawn();
        mats.remove(&c.mat);
    }
}

/// Rings on the ground under whom I keep track of: green under a pin, amber under my focus.
/// Only while heed for players is on.
#[allow(clippy::too_many_arguments)]
fn rings(
    mut commands: Commands,
    heed: Option<Res<crate::heed::Heed>>,
    kit: Option<Res<Kit>>,
    scene: NonSend<crate::world::Scene>,
    island: Option<Res<crate::island::Island>>,
    (mut meshes, mut images, mut mats): (ResMut<Assets<Mesh>>, ResMut<Assets<Image>>, ResMut<Assets<StandardMaterial>>),
    q: Query<Entity, With<Ring>>,
) {
    let marks: Vec<(u32, bool)> = heed.as_ref().filter(|h| h.on).map(|h| h.marks()).unwrap_or_default();
    let had = !q.is_empty();
    if marks.is_empty() && !had {
        return;
    }
    for e in &q {
        commands.entity(e).despawn();
    }
    if marks.is_empty() {
        return;
    }
    let Some(kit) = kit else {
        commands.insert_resource(self::kit(&mut meshes, &mut images, &mut mats));
        return;
    };
    for (id, focus) in marks {
        let Some((p, _)) = scene.shown.get(&id) else { continue };
        let at = ground(island.as_deref(), &scene, *p) + Vec3::Y * 0.08;
        let mat = if focus { kit.focus_mat.clone() } else { kit.pin_mat.clone() };
        let r = if focus { 0.95 } else { 0.78 };
        commands.spawn((Ring, Mesh3d(kit.ring.clone()), MeshMaterial3d(mat), Transform::from_translation(at).with_rotation(Quat::from_rotation_x(-std::f32::consts::FRAC_PI_2)).with_scale(Vec3::splat(r)), Visibility::Visible, bevy::light::NotShadowCaster));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use spacetimedb_sdk::Identity;

    fn row(cell: u32, size: u8, count: u16, spread: u8, heading: u8, moving: u16, fighting: u16, kinds: u8) -> SeenThrong {
        SeenThrong { id: 9, viewer: Identity::ZERO, cell, size, count, spread, heading, moving, fighting, kinds, colour_a: 255, colour_a_count: 0, colour_b: 255, colour_b_count: 0, colour_c: 255, colour_c_count: 0, people: 0, wolves: 0, deer: 0, others: 0, centre_x: 2, centre_y: 2 }
    }

    #[test]
    fn a_row_decodes_its_cell_heading_kinds_and_centroid() {
        // x 401.5 m, y 255 m: cell (66, 42), the authority's (x / 6) << 16 | (y / 6).
        let mut st = row((66 << 16) | 42, 1, 7, 4, 2, 3, 2, PEOPLE | WOLVES);
        st.centre_x = 4;
        st.centre_y = 1;
        let r = Row::of(&st);
        assert_eq!((r.cx, r.cy, r.size), (66, 42, 1));
        assert_eq!(r.origin(), Vec2::new(396.0, 252.0));
        assert_eq!(r.centre(), Vec2::new(396.0 + 4.5, 252.0 + 1.5));
        assert!(r.holds(Vec2::new(401.5, 255.0)) && !r.holds(Vec2::new(402.0, 255.0)));
        assert_eq!(r.key(), ((66 << 16) | 42, 1));
        // A merged square: 12 m from its top-left cell; centre_x/y up to 11.
        let mut mst = row((10 << 16) | 20, 2, 30, 10, STILL, 0, 0, PEOPLE);
        mst.centre_x = 9;
        mst.centre_y = 11;
        let m = Row::of(&mst);
        assert_eq!((m.side(), m.centre()), (12.0, Vec2::new(60.0 + 9.5, 120.0 + 11.5)));
        // Out-of-range centre_x/y clamps to side - 1 (+0.5 m).
        let mut clamped = row((10 << 16) | 20, 1, 1, 0, STILL, 0, 0, PEOPLE);
        clamped.centre_x = 99;
        clamped.centre_y = 99;
        let cr = Row::of(&clamped);
        assert_eq!(cr.centre(), Vec2::new(65.5, 125.5));
        assert!(cr.holds(cr.centre()));
        assert_ne!(m.key(), Row::of(&row((10 << 16) | 20, 1, 30, 10, STILL, 0, 0, PEOPLE)).key());
        // Headings: 0 east, clockwise (map y grows south): 2 south, 4 west, 6 north; 255 none.
        let near = |a: Vec2, b: Vec2| a.distance(b) < 1e-5;
        assert!(near(heading_dir(0).unwrap(), Vec2::X));
        assert!(near(heading_dir(2).unwrap(), Vec2::Y));
        assert!(near(heading_dir(4).unwrap(), -Vec2::X));
        assert!(near(heading_dir(6).unwrap(), -Vec2::Y));
        assert!(near(heading_dir(1).unwrap(), Vec2::new(1.0, 1.0).normalize()));
        assert_eq!(heading_dir(STILL), None);
        assert_eq!(heading_dir(8), None);
        // Kinds by bit, people first; none set reads as people.
        assert_eq!(r.kinds_list(), vec![Kind::Person, Kind::Wolf]);
        assert_eq!(kinds_of(DEER | OTHERS), vec![Kind::Deer, Kind::Other]);
        assert_eq!(kinds_of(0), vec![Kind::Person]);
    }

    #[test]
    fn poses_follow_the_row_s_shares() {
        let count = |v: &[Pose], p: Pose| v.iter().filter(|x| **x == p).count();
        let v = poses(10, 5, 3);
        assert_eq!((v.len(), count(&v, Pose::Fight), count(&v, Pose::Walk), count(&v, Pose::Stand)), (10, 3, 5, 2));
        // Quantized shares past the count are clamped (count 5, moving 5, fighting 5).
        let v = poses(5, 5, 5);
        assert_eq!((count(&v, Pose::Fight), count(&v, Pose::Walk)), (5, 0));
        let v = poses(4, 10, 0);
        assert_eq!(count(&v, Pose::Walk), 4);
        assert!(poses(0, 3, 3).is_empty());
    }

    #[test]
    fn cards_stand_around_the_centroid_within_spread_and_square() {
        for (size, count, spread, cx, cy) in [
            (1u8, 1u16, 0u8, 0u8, 0u8),
            (1, 1, 0, 5, 5),
            (1, 5, 2, 1, 4),
            (1, 20, 4, 0, 0),
            (1, 30, 8, 5, 2),
            (2, 60, 16, 10, 11),
            (2, 3, 2, 0, 11),
            (1, 100, 12, 3, 3),
        ] {
            let mut st = row((50 << 16) | 70, size, count, spread, STILL, 0, 0, PEOPLE);
            st.centre_x = cx;
            st.centre_y = cy;
            let r = Row::of(&st);
            let ps = places(&r, count as usize);
            assert_eq!(ps.len(), count as usize);
            if count == 1 {
                assert_eq!(ps[0], r.centre(), "a lone card stands right on the centroid");
            }
            for p in &ps {
                assert!(r.holds(*p), "{p} outside {r:?}");
            }
            // The same row, the same places.
            assert_eq!(ps, places(&r, count as usize));
            // Centroid pulls small clusters to its side of the square.
            if count > 1 && count <= 5 && cx == 0 && cy == 0 && spread <= 4 {
                let mean = ps.iter().copied().fold(Vec2::ZERO, |a, b| a + b) / ps.len() as f32;
                assert!(mean.x < r.origin().x + r.side() * 0.5 && mean.y < r.origin().y + r.side() * 0.5, "mean {mean} not on centroid side");
            }
            // Minimum pairwise separation: dense cells spread out cleanly instead of stacking
            // onto a corner or vertical sliver.
            if count > 1 && count <= 20 {
                let min = ps.iter().enumerate().flat_map(|(i, a)| ps[i + 1..].iter().map(move |b| a.distance(*b))).fold(f32::MAX, f32::min);
                assert!(min >= 0.65, "{count} cards in {size} at ({cx},{cy}): min separation {min:.3} m < 0.65 m");
            } else if count > 20 && count <= 30 {
                let min = ps.iter().enumerate().flat_map(|(i, a)| ps[i + 1..].iter().map(move |b| a.distance(*b))).fold(f32::MAX, f32::min);
                assert!(min >= 0.55, "{count} cards in {size} at ({cx},{cy}): min separation {min:.3} m < 0.55 m");
            }
        }
        // A wide spread on a small square stays in the square.
        let r = Row::of(&row((1 << 16) | 1, 1, 6, 30, STILL, 0, 0, PEOPLE));
        assert!(places(&r, 6).iter().all(|p| r.holds(*p)));
    }

    #[test]
    fn avoid_obstacles_keeps_cards_clear_of_mounds_perceived_and_rings_inside_square() {
        let lo = Vec2::new(60.0, 60.0);
        let hi = Vec2::new(65.5, 65.5);
        let mound = Vec2::new(63.0, 63.0);
        let pinned = Vec2::new(61.8, 63.0);
        let mut pts = vec![mound, mound + Vec2::new(0.2, 0.1), pinned + Vec2::new(0.3, 0.0), Vec2::new(61.0, 61.0)];
        avoid_obstacles(&mut pts, &[mound], MOUND_CLEAR_M, lo, hi);
        avoid_obstacles(&mut pts, &[pinned], RING_CLEAR_M, lo, hi);
        for p in &pts {
            assert!(p.x >= lo.x && p.x <= hi.x && p.y >= lo.y && p.y <= hi.y, "{p} outside square");
            assert!(p.distance(pinned) >= RING_CLEAR_M - 0.02, "{p} still inside pin ring (d={})", p.distance(pinned));
        }
        assert!(pts[0].distance(mound) >= MOUND_CLEAR_M - 0.02);
        // Unobstructed point stays put.
        assert_eq!(pts[3], Vec2::new(61.0, 61.0));
    }

    #[test]
    fn billboard_scale_matches_3d_foreshortening_at_top_down_and_orbit_pitches() {
        // 58° downward play camera: foreshortened to ~0.72 so upright cards match 3D character height.
        let top_down = Vec3::new(0.0, -(58.0_f32.to_radians().sin()), -(58.0_f32.to_radians().cos())).normalize();
        let s_td = billboard_scale(top_down);
        assert!((0.68..=0.76).contains(&s_td), "top-down scale {s_td}");
        // 28° orbit camera: nearly full height (~0.98).
        let orbit = Vec3::new(0.0, -(28.0_f32.to_radians().sin()), -(28.0_f32.to_radians().cos())).normalize();
        let s_orb = billboard_scale(orbit);
        assert!(s_orb > 0.92 && s_orb <= 1.0, "orbit scale {s_orb}");
        // Horizon camera: full 1.0.
        assert!((billboard_scale(Vec3::NEG_Z) - 1.0).abs() < 1e-4);
    }

    #[test]
    fn fighting_card_has_subtle_outline_and_compact_diagonal_spear() {
        let img = card_image(Kind::Person, Pose::Fight, Some([242, 238, 219]));
        let data = img.data.as_ref().unwrap();
        let (mut opaque, mut outline_dark, mut spear_px) = (0usize, 0usize, 0usize);
        for px in data.chunks_exact(4) {
            if px[3] >= 128 {
                opaque += 1;
                if px[0] <= 115 && px[1] <= 100 && px[2] <= 95 {
                    outline_dark += 1;
                }
                // Bright steel spearhead or warm spear shaft pixels.
                if (px[0] > 180 && px[2] > 195) || (px[0] > 115 && px[1] > 80 && px[2] < 80) {
                    spear_px += 1;
                }
            }
        }
        assert!(opaque > 1000, "opaque pixels {opaque}");
        assert!(outline_dark > 120, "outline pixels {outline_dark}");
        assert!(spear_px > 40, "spear + spearhead pixels {spear_px}");
    }

    #[test]
    fn card_kinds_follow_per_kind_counts_instead_of_equal_turns() {
        let cnt = |v: &[Kind], k: Kind| v.iter().filter(|x| **x == k).count();
        // Exact sum: 7 people, 2 wolves -> 7 people, 2 wolves (not 5 and 4).
        let v = card_kinds(9, PEOPLE | WOLVES, [7, 2, 0, 0]);
        assert_eq!((v.len(), cnt(&v, Kind::Person), cnt(&v, Kind::Wolf)), (9, 7, 2));
        // Quantized counts summing under count: 5 people, 2 wolves, count 10 -> proportional 7 and 3.
        let v = card_kinds(10, PEOPLE | WOLVES, [5, 2, 0, 0]);
        assert_eq!((v.len(), cnt(&v, Kind::Person), cnt(&v, Kind::Wolf)), (10, 7, 3));
        // Quantized counts summing over count: 10 people, 5 wolves, 5 deer, count 15 -> 7/8, 4, 4.
        let v = card_kinds(15, PEOPLE | WOLVES | DEER, [10, 5, 5, 0]);
        assert_eq!(v.len(), 15);
        assert_eq!(cnt(&v, Kind::Person) + cnt(&v, Kind::Wolf) + cnt(&v, Kind::Deer), 15);
        assert!(cnt(&v, Kind::Person) >= 7 && cnt(&v, Kind::Wolf) >= 3 && cnt(&v, Kind::Deer) >= 3);
        // A lone wolf among many people still gets at least 1 card.
        let v = card_kinds(20, PEOPLE | WOLVES, [20, 1, 0, 0]);
        assert_eq!((cnt(&v, Kind::Person), cnt(&v, Kind::Wolf)), (19, 1));
        // Fallback when all four counts are zero: uses the bitmask.
        let v = card_kinds(6, PEOPLE | DEER, [0, 0, 0, 0]);
        assert_eq!((cnt(&v, Kind::Person), cnt(&v, Kind::Deer)), (3, 3));
        assert!(card_kinds(0, PEOPLE, [5, 0, 0, 0]).is_empty());
    }

    #[test]
    fn swatches_are_derived_and_calibrated_from_book_outfit_rgbs_and_missing_words_stay_neutral() {
        let text = serde_json::json!({
            "generation": "test",
            "lines": {
                "lk_0000000000000001": {
                    "person": {
                        "type": "adult-f-a", "height": 1.65,
                        "colors": { "outfit": { "smock_58-f": "#406080", "apron_58-f": "#f0f0f0", "trousers-f": "#202020" } },
                        "styles": { "outfit": ["smock_58-f", "apron_58-f", "trousers-f"] }
                    },
                    "words": { "top": "a blue smock with an apron" }
                },
                "lk_0000000000000002": {
                    "person": {
                        "type": "adult-m-a", "height": 1.75,
                        "colors": { "outfit": { "coat-m": "#6080a0", "jersey_coat-m": "#101010", "trousers-m": "#202020" } },
                        "styles": { "outfit": ["coat-m", "jersey_coat-m", "trousers-m"] }
                    },
                    "words": { "top": "a blue coat" }
                },
                "lk_0000000000000003": {
                    "person": {
                        "type": "adult-m-a", "height": 1.75,
                        "colors": { "outfit": { "jersey-m": "#562722", "trousers-m": "#202020" } },
                        "styles": { "outfit": ["jersey-m", "trousers-m"] }
                    },
                    "words": { "top": "a red jersey" }
                },
                "lk_0000000000000004": {
                    "person": {
                        "type": "adult-f-a", "height": 1.65,
                        "colors": { "outfit": { "smock-f": "#416565", "trousers-f": "#202020" } },
                        "styles": { "outfit": ["smock-f", "trousers-f"] }
                    },
                    "words": { "top": "a green smock" }
                },
                "lk_0000000000000005": {
                    "person": {
                        "type": "adult-m-a", "height": 1.75,
                        "colors": { "outfit": { "coat-m": "#615c3f", "trousers-m": "#202020" } },
                        "styles": { "outfit": ["coat-m", "trousers-m"] }
                    },
                    "words": { "top": "a green coat" }
                }
            }
        });
        let book = crate::characters::book::LookBook::parse(&text.to_string()).unwrap();
        let sw = swatches_of(&book);
        // Blue (index 4): brighter than raw mean (80,112,144) under toon lit-band gain, and
        // clearly blue (b > g > r); cream apron (#f0f0f0) did not contaminate it.
        let blue = sw[4].expect("blue swatch");
        assert!(blue[2] > blue[1] && blue[1] > blue[0] && blue[2] > 160, "blue {blue:?}");
        // Red (index 5): calibrated from dark crimson #562722 to a clearly red, brighter swatch.
        let red = sw[5].expect("red swatch");
        assert!(red[0] > 130 && red[0] > red[1] * 2 && red[0] > red[2] * 2, "red {red:?}");
        // Green (index 2): teal-green (#416565) + olive-green (#615c3f) keep clear green chroma
        // in HSV aggregation instead of collapsing to grey in RGB averaging.
        let green = sw[2].expect("green swatch");
        assert!(green[1] > green[0] + 40 && green[1] > green[2] + 40, "green {green:?}");
        // Grey (index 9) and every other absent word: None (neutral, never invented).
        assert_eq!(sw[9], None);
        assert_eq!(sw[0], None);
    }

    #[test]
    fn tops_proportion_colours_leave_the_rest_neutral_and_never_tint_animals() {
        let mut pal: Swatches = [None; living_rules::look::CLOTH.len()];
        let yellow = [172, 141, 76];
        let red = [86, 39, 34];
        let blue = [90, 106, 122];
        pal[0] = Some(yellow);
        pal[5] = Some(red);
        pal[4] = Some(blue);
        // pal[9] (grey) stays None.

        // Exact fit with remainder neutral: 10 people, 4 yellow, 3 red, 1 blue -> 2 neutral.
        let mut st = row(0, 1, 10, 4, STILL, 0, 0, PEOPLE);
        st.people = 10;
        st.colour_a = 0; st.colour_a_count = 4;
        st.colour_b = 5; st.colour_b_count = 3;
        st.colour_c = 4; st.colour_c_count = 1;
        let r = Row::of(&st);
        let kinds = r.card_kinds();
        let ts = tops_with(&r, &kinds, &pal);
        assert_eq!(ts.len(), 10);
        assert_eq!(ts.iter().filter(|t| **t == Some(yellow)).count(), 4);
        assert_eq!(ts.iter().filter(|t| **t == Some(red)).count(), 3);
        assert_eq!(ts.iter().filter(|t| **t == Some(blue)).count(), 1);
        assert_eq!(ts.iter().filter(|t| t.is_none()).count(), 2);

        // Quantized colour counts past n_people scale proportionally (e.g. 5 + 5 + 5 for 10 people).
        st.colour_a_count = 5; st.colour_b_count = 5; st.colour_c_count = 5;
        let r2 = Row::of(&st);
        let ts2 = tops_with(&r2, &kinds, &pal);
        assert_eq!(ts2.len(), 10);
        assert_eq!(ts2.iter().filter(|t| t.is_none()).count(), 0);
        assert_eq!(ts2.iter().filter(|t| **t == Some(yellow)).count(), 4);
        assert_eq!(ts2.iter().filter(|t| **t == Some(red)).count(), 3);
        assert_eq!(ts2.iter().filter(|t| **t == Some(blue)).count(), 3);

        // A word with no swatch in the book (grey, index 9) produces neutral cards, never steals into B.
        st.colour_a = 9; st.colour_a_count = 5; st.colour_b = 5; st.colour_b_count = 3; st.colour_c = 255; st.colour_c_count = 0;
        let r3 = Row::of(&st);
        let ts3 = tops_with(&r3, &kinds, &pal);
        assert_eq!(ts3.iter().filter(|t| **t == Some(red)).count(), 3);
        assert_eq!(ts3.iter().filter(|t| t.is_none()).count(), 7);

        // Mixed people and wolves: only people get cloth colours; every wolf stays None.
        let mut mix = row(0, 1, 7, 4, STILL, 0, 0, PEOPLE | WOLVES);
        mix.people = 5; mix.wolves = 2;
        mix.colour_a = 0; mix.colour_a_count = 3;
        mix.colour_b = 5; mix.colour_b_count = 2;
        let rm = Row::of(&mix);
        let km = rm.card_kinds();
        let tm = tops_with(&rm, &km, &pal);
        assert_eq!(tm.len(), 7);
        for (k, t) in km.iter().zip(&tm) {
            if *k != Kind::Person {
                assert_eq!(*t, None, "animals never take cloth colours");
            }
        }
        assert_eq!(tm.iter().filter(|t| **t == Some(yellow)).count(), 3);
        assert_eq!(tm.iter().filter(|t| **t == Some(red)).count(), 2);

        // No colours at all: every card is neutral.
        let none = Row::of(&row(0, 1, 5, 4, STILL, 0, 0, PEOPLE));
        assert!(tops_with(&none, &none.card_kinds(), &pal).iter().all(Option::is_none));
    }

    #[test]
    fn cards_darken_with_the_light_but_not_to_nothing() {
        assert_eq!(shade(None), Vec3::ONE);
        let mut a = crate::daylight::Atmo { active: true, light: [1.0, 0.96, 0.88], lux: 9000.0, ..Default::default() };
        assert!((shade(Some(&a)) - Vec3::new(1.0, 0.96, 0.88)).length() < 1e-5);
        a.lux = 2800.0;
        a.light = [0.46, 0.6, 1.0];
        assert!((shade(Some(&a)) - Vec3::new(0.46, 0.6, 1.0) * (2800.0 / 9000.0)).length() < 1e-5);
        a.lux = 100.0;
        assert!((shade(Some(&a)) - Vec3::new(0.46, 0.6, 1.0) * NIGHT_SHADE).length() < 1e-5);
        a.active = false;
        assert_eq!(shade(Some(&a)), Vec3::ONE);
    }
}
