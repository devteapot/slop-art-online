//! Ground height derived from the tile map: a deterministic, seeded function shared by every
//! client that draws the world (and by the authority, should height ever matter to the rules).
//!
//! Scale: one tile is one metre (walking 2.6 m/s, personal space 0.8 m, campfire warmth 3.5 m).
//! The simulation stays a flat tile plane; this only says how high the ground at a point is
//! drawn, so characters stand on the rendered surface. Three layers add up:
//!
//! - **Local:** each tile kind's own level and roughness, blended over about 1.6 m (water lies
//!   about a metre below its surface, forest slightly raised).
//! - **Hills:** broad seeded undulation up to about 14 m, fading out toward water, so lakes and
//!   rivers lie in valleys and shores stay low.
//! - **Mountains:** where rock is dense (rock fraction within about 10 m), the ground rises up
//!   to about 60 m with ridged noise. Small rock outcrops become knolls, large rock regions
//!   mountains, and the map's rim (outside counts as rock) a mountain wall.

use crate::map::{Map, Terrain};

/// Surface of still water (metres).
pub const WATER_LEVEL: f32 = -0.15;

/// Blend radius between tile kinds (metres).
const RADIUS: f32 = 1.6;
/// Highest hills and mountains (metres).
const HILLS: f32 = 14.0;
const MOUNTAINS: f32 = 48.0;
const RIDGES: f32 = 14.0;
/// Rock density radius (tiles) and how far inland hills and mountains reach full height.
const ROCK_R: i32 = 10;
const INLAND_HILLS: f32 = 40.0;
const INLAND_MOUNTAINS: f32 = 10.0;

/// Base height and noise amplitude of a terrain kind (metres).
fn profile(t: Terrain) -> (f32, f32) {
    match t {
        Terrain::Water => (-1.3, 0.15),
        Terrain::Sand => (0.1, 0.12),
        Terrain::Grass => (0.35, 0.4),
        Terrain::Dirt => (0.3, 0.3),
        Terrain::Road => (0.3, 0.08),
        Terrain::Forest => (0.5, 0.5),
        Terrain::Rock => (1.2, 1.0),
        Terrain::Wall => (0.35, 0.1),
        Terrain::Drop => (0.3, 0.3),
    }
}

fn hash(seed: u64, x: i32, y: i32) -> f32 {
    let mut h = seed ^ (x as u32 as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ (y as u32 as u64).wrapping_mul(0xC2B2_AE3D_27D4_EB4F);
    h ^= h >> 33;
    h = h.wrapping_mul(0xFF51_AFD7_ED55_8CCD);
    h ^= h >> 33;
    (h & 0xFF_FFFF) as f32 / 0xFF_FFFF as f32
}

fn smooth(t: f32) -> f32 {
    t * t * (3.0 - 2.0 * t)
}

fn smoothstep(a: f32, b: f32, x: f32) -> f32 {
    smooth(((x - a) / (b - a)).clamp(0.0, 1.0))
}

/// Value noise in [-1, 1].
fn value(seed: u64, x: f32, y: f32) -> f32 {
    let (x0, y0) = (x.floor(), y.floor());
    let (fx, fy) = (smooth(x - x0), smooth(y - y0));
    let (i, j) = (x0 as i32, y0 as i32);
    let a = hash(seed, i, j);
    let b = hash(seed, i + 1, j);
    let c = hash(seed, i, j + 1);
    let d = hash(seed, i + 1, j + 1);
    let top = a + (b - a) * fx;
    let bottom = c + (d - c) * fx;
    (top + (bottom - top) * fy) * 2.0 - 1.0
}

/// Octaves of value noise at base frequency `f`, roughly in [-1, 1].
fn fbm(seed: u64, x: f32, y: f32, f: f32, octaves: u64) -> f32 {
    let (mut sum, mut f, mut a, mut norm) = (0.0, f, 1.0, 0.0);
    for o in 0..octaves {
        sum += value(seed.wrapping_add(o * 7919), x * f, y * f) * a;
        norm += a;
        f *= 2.1;
        a *= 0.45;
    }
    sum / norm
}

/// Weights of the tile kinds around a point (sum 1), for height and for shading.
pub fn blend(map: &Map, x: f32, y: f32, mut each: impl FnMut(Terrain, f32)) {
    let r = RADIUS.ceil() as i32;
    let (cx, cy) = (x.floor() as i32, y.floor() as i32);
    let mut total = 0.0;
    let mut acc: [(Terrain, f32); 25] = [(Terrain::Grass, 0.0); 25];
    let mut n = 0;
    for j in cy - r..=cy + r {
        for i in cx - r..=cx + r {
            let d2 = (i as f32 + 0.5 - x).powi(2) + (j as f32 + 0.5 - y).powi(2);
            let q = 1.0 - d2 / (RADIUS * RADIUS);
            if q <= 0.0 {
                continue;
            }
            let w = q * q;
            total += w;
            if n < acc.len() {
                acc[n] = (map.get(i, j), w);
                n += 1;
            }
        }
    }
    for (t, w) in &acc[..n] {
        each(*t, *w / total.max(1e-6));
    }
}

/// The ground of one map: the map plus the fields the relief needs, computed once.
#[derive(Clone, Debug)]
pub struct Ground {
    map: Map,
    seed: u64,
    /// Per tile: distance to the nearest water tile (metres, capped), and rock fraction nearby.
    water_dist: Vec<f32>,
    rock: Vec<f32>,
}

impl Ground {
    pub fn new(map: &Map, seed: u64) -> Self {
        let (w, h) = (map.w as usize, map.h as usize);
        // Distance to water: two-pass chamfer (1, √2) over the tile grid.
        let mut d = vec![f32::MAX; w * h];
        for y in 0..h {
            for x in 0..w {
                if map.get(x as i32, y as i32) == Terrain::Water {
                    d[y * w + x] = 0.0;
                }
            }
        }
        let s2 = std::f32::consts::SQRT_2;
        let pass = |d: &mut Vec<f32>, order: &mut dyn Iterator<Item = (usize, usize)>, nb: &[(i32, i32, f32)]| {
            for (x, y) in order {
                let mut best = d[y * w + x];
                for (dx, dy, c) in nb {
                    let (nx, ny) = (x as i32 + dx, y as i32 + dy);
                    if nx >= 0 && ny >= 0 && (nx as usize) < w && (ny as usize) < h {
                        best = best.min(d[ny as usize * w + nx as usize] + c);
                    }
                }
                d[y * w + x] = best;
            }
        };
        pass(&mut d, &mut (0..h).flat_map(|y| (0..w).map(move |x| (x, y))), &[(-1, 0, 1.0), (0, -1, 1.0), (-1, -1, s2), (1, -1, s2)]);
        pass(&mut d, &mut (0..h).rev().flat_map(|y| (0..w).rev().map(move |x| (x, y))), &[(1, 0, 1.0), (0, 1, 1.0), (1, 1, s2), (-1, 1, s2)]);
        let water_dist = d.into_iter().map(|v| v.min(200.0)).collect();
        // Rock fraction within ROCK_R (outside the map counts as rock): a box blur, run twice.
        let mut rock: Vec<f32> = (0..w * h).map(|i| (map.get((i % w) as i32, (i / w) as i32) == Terrain::Rock) as u8 as f32).collect();
        for _ in 0..2 {
            rock = box_blur(&rock, w, h, ROCK_R);
        }
        Self { map: map.clone(), seed, water_dist, rock }
    }

    pub fn map(&self) -> &Map {
        &self.map
    }

    /// A per-tile field sampled bilinearly between tile centres, clamped at the map's edges (the
    /// rock field already counts the outside as rock through its blur).
    fn field(&self, f: &[f32], x: f32, y: f32) -> f32 {
        let (w, h) = (self.map.w as i32, self.map.h as i32);
        let (gx, gy) = (x - 0.5, y - 0.5);
        let (x0, y0) = (gx.floor() as i32, gy.floor() as i32);
        let (tx, ty) = (gx - x0 as f32, gy - y0 as f32);
        let at = |i: i32, j: i32| f[(j.clamp(0, h - 1) * w + i.clamp(0, w - 1)) as usize];
        let top = at(x0, y0) + (at(x0 + 1, y0) - at(x0, y0)) * tx;
        let bottom = at(x0, y0 + 1) + (at(x0 + 1, y0 + 1) - at(x0, y0 + 1)) * tx;
        top + (bottom - top) * ty
    }

    /// Height of the drawn ground at a point (metres; x east, y south in tiles = metres).
    pub fn height(&self, x: f32, y: f32) -> f32 {
        let (mut base, mut amp) = (0.0, 0.0);
        blend(&self.map, x, y, |t, w| {
            let (b, a) = profile(t);
            base += b * w;
            amp += a * w;
        });
        let local = base + amp * fbm(self.seed, x, y, 0.12, 3);
        let wd = self.field(&self.water_dist, x, y).max(0.0);
        // The blur's running sums can drift a hair outside 0..1; powf of a negative is NaN.
        let rock = self.field(&self.rock, x, y).clamp(0.0, 1.0);
        let hills = (fbm(self.seed ^ 0xA5A5, x, y, 1.0 / 90.0, 2) * 0.5 + 0.5) * HILLS * smoothstep(2.0, INLAND_HILLS, wd);
        let ridge = 1.0 - fbm(self.seed ^ 0x5A5A, x, y, 1.0 / 28.0, 3).abs();
        let mountains = (rock.powf(1.5) * MOUNTAINS + ridge * ridge * RIDGES * rock) * smoothstep(1.0, INLAND_MOUNTAINS, wd);
        local + hills + mountains
    }
}

fn box_blur(src: &[f32], w: usize, h: usize, r: i32) -> Vec<f32> {
    let n = (2 * r + 1) as f32;
    let get = |v: &[f32], x: i32, y: i32| if x < 0 || y < 0 || x >= w as i32 || y >= h as i32 { 1.0 } else { v[y as usize * w + x as usize] };
    let mut tmp = vec![0.0; w * h];
    for y in 0..h as i32 {
        let mut sum: f32 = (-r..=r).map(|i| get(src, i, y)).sum();
        for x in 0..w as i32 {
            tmp[y as usize * w + x as usize] = sum / n;
            sum += get(src, x + r + 1, y) - get(src, x - r, y);
        }
    }
    let mut out = vec![0.0; w * h];
    for x in 0..w as i32 {
        let mut sum: f32 = (-r..=r).map(|j| get(&tmp, x, j)).sum();
        for y in 0..h as i32 {
            out[y as usize * w + x as usize] = sum / n;
            sum += get(&tmp, x, y + r + 1) - get(&tmp, x, y - r);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn map_of(w: u32, h: u32, f: impl Fn(u32, u32) -> Terrain) -> Map {
        let mut m = Map::from_chunks(w, h, std::iter::empty());
        for y in 0..h {
            for x in 0..w {
                m.set(x as i32, y as i32, f(x, y));
            }
        }
        m
    }

    #[test]
    fn deterministic_and_seeded() {
        let m = map_of(64, 64, |_, _| Terrain::Grass);
        let (a, b) = (Ground::new(&m, 7), Ground::new(&m, 8));
        assert_eq!(a.height(30.3, 31.7), a.height(30.3, 31.7));
        assert_ne!(a.height(30.3, 31.7), b.height(30.3, 31.7));
    }

    #[test]
    fn water_lies_under_its_surface_and_rock_rises_into_mountains() {
        // A lake on the left, grass in the middle, a broad rock region on the right.
        let m = map_of(160, 60, |x, _| if x < 30 { Terrain::Water } else if x < 100 { Terrain::Grass } else { Terrain::Rock });
        let g = Ground::new(&m, 3);
        for y in [20.5, 30.5, 40.5] {
            assert!(g.height(10.5, y) < WATER_LEVEL, "lake bed under water");
            assert!(g.height(31.5, y) > WATER_LEVEL && g.height(31.5, y) < 2.0, "the shore is low");
            assert!(g.height(140.5, y) > 30.0, "deep in rock is a mountain: {}", g.height(140.5, y));
            assert!(g.height(140.5, y) > g.height(65.5, y) + 20.0, "mountains stand well above the plain");
        }
    }

    #[test]
    fn finite_everywhere_on_a_generated_world() {
        // The running-sum blur can leave rock fractions a hair below zero; heights must stay finite.
        let m = crate::map::generate(7);
        let g = Ground::new(&m, 7);
        for j in 0..(m.h * 2) {
            for i in 0..(m.w * 2) {
                let h = g.height(i as f32 * 0.5, j as f32 * 0.5);
                assert!(h.is_finite(), "height {h} at {}, {}", i as f32 * 0.5, j as f32 * 0.5);
            }
        }
    }

    #[test]
    fn continuous_across_tile_and_chunk_borders() {
        let m = map_of(96, 96, |x, y| if (x / 9 + y / 13) % 3 == 0 { Terrain::Rock } else if (x + y) % 11 == 0 { Terrain::Water } else { Terrain::Forest });
        let g = Ground::new(&m, 1);
        // Small steps never jump: no cracks at tile (or 16-tile chunk) edges.
        let mut prev = g.height(0.0, 40.0);
        let mut x = 0.0;
        while x < 95.0 {
            x += 0.01;
            let h = g.height(x, 40.0);
            assert!((h - prev).abs() < 0.2, "jump of {} at x = {x}", h - prev);
            prev = h;
        }
    }
}
