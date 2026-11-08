//! Ground height derived from the tile map: a deterministic, seeded function shared by every
//! client that draws the world (and by the authority, should height ever matter to the rules).
//!
//! The simulation stays a flat tile plane; this only says how high the ground at a point is
//! drawn, so characters stand on the rendered surface. Water lies lowest, then sand, grass,
//! dirt and forest, and rock rises into hills; borders between kinds blend over about a tile
//! and a half, and seeded value noise roughens each kind by its own amount.

use crate::map::{Map, Terrain};

/// Surface of still water (tiles of height).
pub const WATER_LEVEL: f32 = -0.15;

/// Blend radius between tile kinds (tiles).
const RADIUS: f32 = 1.6;

/// Base height and noise amplitude of a terrain kind.
fn profile(t: Terrain) -> (f32, f32) {
    match t {
        Terrain::Water => (-1.2, 0.15),
        Terrain::Sand => (0.1, 0.12),
        Terrain::Grass => (0.35, 0.4),
        Terrain::Dirt => (0.3, 0.3),
        Terrain::Road => (0.3, 0.08),
        Terrain::Forest => (0.5, 0.5),
        Terrain::Rock => (2.2, 1.3),
        Terrain::Wall => (0.35, 0.1),
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

/// Three octaves of value noise, roughly in [-1, 1].
fn fbm(seed: u64, x: f32, y: f32) -> f32 {
    let mut sum = 0.0;
    let (mut f, mut a, mut norm) = (0.12, 1.0, 0.0);
    for o in 0..3u64 {
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

/// Height of the drawn ground at a point (tile units, +x east, +y south).
pub fn ground(map: &Map, seed: u64, x: f32, y: f32) -> f32 {
    let (mut base, mut amp) = (0.0, 0.0);
    blend(map, x, y, |t, w| {
        let (b, a) = profile(t);
        base += b * w;
        amp += a * w;
    });
    base + amp * fbm(seed, x, y)
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
        let m = map_of(32, 32, |_, _| Terrain::Grass);
        assert_eq!(ground(&m, 7, 10.3, 11.7), ground(&m, 7, 10.3, 11.7));
        assert_ne!(ground(&m, 7, 10.3, 11.7), ground(&m, 8, 10.3, 11.7));
    }

    #[test]
    fn water_lies_under_the_surface_and_rock_rises() {
        // A lake on the left, grass in the middle, rock on the right.
        let m = map_of(40, 20, |x, _| if x < 12 { Terrain::Water } else if x < 28 { Terrain::Grass } else { Terrain::Rock });
        for y in [5.5, 10.5, 15.5] {
            assert!(ground(&m, 3, 5.5, y) < WATER_LEVEL, "lake bed under water");
            assert!(ground(&m, 3, 20.5, y) > WATER_LEVEL, "grass above water");
            assert!(ground(&m, 3, 34.5, y) > ground(&m, 3, 20.5, y) + 1.0, "rock well above grass");
        }
    }

    #[test]
    fn continuous_across_tile_and_chunk_borders() {
        let m = map_of(48, 48, |x, y| if (x / 3 + y / 5) % 3 == 0 { Terrain::Rock } else if (x + y) % 7 == 0 { Terrain::Water } else { Terrain::Forest });
        // Small steps never jump: the surface has no cracks at tile (or 16-tile chunk) edges.
        let mut prev = ground(&m, 1, 0.0, 16.0);
        let mut x = 0.0;
        while x < 47.0 {
            x += 0.01;
            let h = ground(&m, 1, x, 16.0);
            assert!((h - prev).abs() < 0.1, "jump of {} at x = {x}", h - prev);
            prev = h;
        }
    }
}
