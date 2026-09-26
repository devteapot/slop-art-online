//! Tile map: terrain generation, chunk addressing and grid pathfinding.
//! Positions are continuous tile coordinates; tile (i, j) spans [i, i+1) × [j, j+1).

use std::cmp::Ordering;
use std::collections::BinaryHeap;

/// Size of the classic valley map (the realm generator makes maps of any size).
pub const MAP_W: u32 = 96;
pub const MAP_H: u32 = 96;
pub const CHUNK: u32 = 16;
/// Largest supported map side (chunk coordinates are packed in 16 bits each).
pub const MAX_SIDE: u32 = 4096;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
pub enum Terrain {
    Grass = 0,
    Forest = 1,
    Water = 2,
    Sand = 3,
    Rock = 4,
    Dirt = 5,
    /// Laid by people: walkable, faster to walk on.
    Road = 6,
    /// Built by people: blocks movement.
    Wall = 7,
}

impl Terrain {
    pub fn from_u8(v: u8) -> Self {
        match v {
            1 => Self::Forest,
            2 => Self::Water,
            3 => Self::Sand,
            4 => Self::Rock,
            5 => Self::Dirt,
            6 => Self::Road,
            7 => Self::Wall,
            _ => Self::Grass,
        }
    }
    pub fn walkable(self) -> bool {
        !matches!(self, Self::Water | Self::Rock | Self::Wall)
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::Grass => "grass",
            Self::Forest => "forest",
            Self::Water => "water",
            Self::Sand => "sand",
            Self::Rock => "rock",
            Self::Dirt => "dirt",
            Self::Road => "road",
            Self::Wall => "wall",
        }
    }
}

/// Chunk ids pack chunk coordinates, so they do not depend on the map's width.
pub fn chunk_id(cx: u32, cy: u32) -> u32 {
    (cy << 16) | cx
}

pub fn chunk_xy(id: u32) -> (u32, u32) {
    (id & 0xFFFF, id >> 16)
}

pub fn chunk_of(x: f32, y: f32) -> u32 {
    let cx = (x.max(0.0) as u32 / CHUNK).min(MAX_SIDE / CHUNK - 1);
    let cy = (y.max(0.0) as u32 / CHUNK).min(MAX_SIDE / CHUNK - 1);
    chunk_id(cx, cy)
}

/// Chunks overlapping the square of half-size `r` around a point (callers filter to the map).
pub fn chunks_around(x: f32, y: f32, r: f32) -> Vec<u32> {
    let lo_x = ((x - r).max(0.0)) as u32 / CHUNK;
    let hi_x = ((x + r).max(0.0)) as u32 / CHUNK;
    let lo_y = ((y - r).max(0.0)) as u32 / CHUNK;
    let hi_y = ((y + r).max(0.0)) as u32 / CHUNK;
    let mut out = Vec::with_capacity(9);
    for cy in lo_y..=hi_y {
        for cx in lo_x..=hi_x {
            out.push(chunk_id(cx, cy));
        }
    }
    out
}

/// Whole-map terrain, row-major `y * w + x`.
#[derive(Clone, Debug)]
pub struct Map {
    pub w: u32,
    pub h: u32,
    pub tiles: Vec<u8>,
    /// Tiles closed by structures (a shut gate), by tile index; rebuilt when they change.
    pub blocked: std::collections::HashSet<u32>,
}

impl Map {
    pub fn chunks(&self) -> impl Iterator<Item = u32> + '_ {
        let (cw, ch) = (self.w.div_ceil(CHUNK), self.h.div_ceil(CHUNK));
        (0..ch).flat_map(move |cy| (0..cw).map(move |cx| chunk_id(cx, cy)))
    }

    pub fn get(&self, x: i32, y: i32) -> Terrain {
        if x < 0 || y < 0 || x >= self.w as i32 || y >= self.h as i32 {
            return Terrain::Rock;
        }
        Terrain::from_u8(self.tiles[(y as u32 * self.w + x as u32) as usize])
    }
    pub fn at(&self, x: f32, y: f32) -> Terrain {
        self.get(x.floor() as i32, y.floor() as i32)
    }
    pub fn walkable(&self, x: i32, y: i32) -> bool {
        self.get(x, y).walkable() && (self.blocked.is_empty() || !self.blocked.contains(&(y as u32 * self.w + x as u32)))
    }

    /// Whether a body can stand at a continuous position (terrain and closed gates).
    pub fn free(&self, x: f32, y: f32) -> bool {
        self.walkable(x.floor() as i32, y.floor() as i32)
    }

    /// Change one tile (roads, walls); callers persist the chunk.
    pub fn set(&mut self, x: i32, y: i32, t: Terrain) {
        if x >= 0 && y >= 0 && x < self.w as i32 && y < self.h as i32 {
            self.tiles[(y as u32 * self.w + x as u32) as usize] = t as u8;
        }
    }

    /// Terrain bytes for one chunk, row-major within the chunk.
    pub fn chunk_bytes(&self, id: u32) -> Vec<u8> {
        let (cx, cy) = chunk_xy(id);
        let mut out = Vec::with_capacity((CHUNK * CHUNK) as usize);
        for j in 0..CHUNK {
            for i in 0..CHUNK {
                out.push(self.get((cx * CHUNK + i) as i32, (cy * CHUNK + j) as i32) as u8);
            }
        }
        out
    }

    pub fn from_chunks(w: u32, h: u32, chunks: impl IntoIterator<Item = (u32, Vec<u8>)>) -> Self {
        let mut tiles = vec![0u8; (w * h) as usize];
        for (id, bytes) in chunks {
            let (cx, cy) = chunk_xy(id);
            for (k, b) in bytes.iter().enumerate() {
                let i = k as u32 % CHUNK;
                let j = k as u32 / CHUNK;
                let x = cx * CHUNK + i;
                let y = cy * CHUNK + j;
                if x < w && y < h {
                    tiles[(y * w + x) as usize] = *b;
                }
            }
        }
        Self { w, h, tiles, blocked: Default::default() }
    }

    /// Nearest walkable tile center to a point, searching outward.
    pub fn nearest_walkable(&self, x: f32, y: f32) -> Option<(f32, f32)> {
        let (tx, ty) = (x.floor() as i32, y.floor() as i32);
        for r in 0i32..12 {
            for dy in -r..=r {
                for dx in -r..=r {
                    if dx.abs() != r && dy.abs() != r {
                        continue;
                    }
                    if self.walkable(tx + dx, ty + dy) {
                        return Some(((tx + dx) as f32 + 0.5, (ty + dy) as f32 + 0.5));
                    }
                }
            }
        }
        None
    }

    /// True when the straight segment only crosses walkable tiles.
    pub fn line_clear(&self, a: (f32, f32), b: (f32, f32)) -> bool {
        let d = ((b.0 - a.0).powi(2) + (b.1 - a.1).powi(2)).sqrt();
        let steps = (d * 4.0).ceil().max(1.0) as i32;
        for s in 0..=steps {
            let t = s as f32 / steps as f32;
            let x = a.0 + (b.0 - a.0) * t;
            let y = a.1 + (b.1 - a.1) * t;
            // Keep a small clearance so bodies do not clip corners.
            for (ox, oy) in [(0.0, 0.0), (0.2, 0.2), (-0.2, 0.2), (0.2, -0.2), (-0.2, -0.2)] {
                if !self.free(x + ox, y + oy) {
                    return false;
                }
            }
        }
        true
    }

    /// A* over the 8-connected tile grid followed by line-of-sight smoothing.
    /// Returns waypoints excluding the start, ending exactly at `to` when walkable.
    pub fn path(&self, from: (f32, f32), to: (f32, f32), max_expansions: usize) -> Option<Vec<(f32, f32)>> {
        let start = (from.0.floor() as i32, from.1.floor() as i32);
        let goal = (to.0.floor() as i32, to.1.floor() as i32);
        if !self.walkable(goal.0, goal.1) {
            return None;
        }
        if self.line_clear(from, to) {
            return Some(vec![to]);
        }
        let w = self.w as i32;
        let idx = |p: (i32, i32)| (p.1 * w + p.0) as usize;
        let n = (self.w * self.h) as usize;
        let mut g = vec![u32::MAX; n];
        let mut came = vec![u32::MAX; n];
        let h = |p: (i32, i32)| {
            let dx = (p.0 - goal.0).unsigned_abs();
            let dy = (p.1 - goal.1).unsigned_abs();
            10 * dx.max(dy) + 4 * dx.min(dy)
        };
        #[derive(PartialEq, Eq)]
        struct Open(u32, u32, (i32, i32));
        impl Ord for Open {
            fn cmp(&self, o: &Self) -> Ordering {
                o.0.cmp(&self.0).then(o.1.cmp(&self.1))
            }
        }
        impl PartialOrd for Open {
            fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
                Some(self.cmp(o))
            }
        }
        let mut open = BinaryHeap::new();
        g[idx(start)] = 0;
        open.push(Open(h(start), 0, start));
        let mut expansions = 0;
        let mut found = false;
        while let Some(Open(_, cost, p)) = open.pop() {
            if p == goal {
                found = true;
                break;
            }
            if cost > g[idx(p)] {
                continue;
            }
            expansions += 1;
            if expansions > max_expansions {
                return None;
            }
            for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)] {
                let q = (p.0 + dx, p.1 + dy);
                if !self.walkable(q.0, q.1) {
                    continue;
                }
                if dx != 0 && dy != 0 && (!self.walkable(p.0 + dx, p.1) || !self.walkable(p.0, p.1 + dy)) {
                    continue;
                }
                let step = if dx != 0 && dy != 0 { 14 } else { 10 };
                let nc = cost + step;
                if nc < g[idx(q)] {
                    g[idx(q)] = nc;
                    came[idx(q)] = idx(p) as u32;
                    open.push(Open(nc + h(q), nc, q));
                }
            }
        }
        if !found {
            return None;
        }
        let mut cells = vec![goal];
        let mut cur = idx(goal);
        while cur != idx(start) {
            let prev = came[cur];
            if prev == u32::MAX {
                break;
            }
            cur = prev as usize;
            cells.push(((cur as i32) % w, (cur as i32) / w));
        }
        cells.reverse();
        let mut pts: Vec<(f32, f32)> = cells.iter().map(|c| (c.0 as f32 + 0.5, c.1 as f32 + 0.5)).collect();
        if let Some(last) = pts.last_mut() {
            *last = to;
        }
        // String pulling.
        let mut out = Vec::new();
        let mut anchor = from;
        let mut i = 0;
        while i < pts.len() {
            let mut j = pts.len() - 1;
            while j > i && !self.line_clear(anchor, pts[j]) {
                j -= 1;
            }
            out.push(pts[j]);
            anchor = pts[j];
            i = j + 1;
        }
        Some(out)
    }
}

fn hash2(seed: u64, x: i32, y: i32) -> f32 {
    let mut h = seed ^ 0x9E37_79B9_7F4A_7C15;
    h ^= (x as u64).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    h = h.rotate_left(27).wrapping_mul(0x94D0_49BB_1331_11EB);
    h ^= (y as u64).wrapping_mul(0xD6E8_FEB8_6659_FD93);
    h ^= h >> 31;
    h = h.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    h ^= h >> 29;
    (h >> 40) as f32 / (1u64 << 24) as f32
}

fn value_noise(seed: u64, x: f32, y: f32, scale: f32) -> f32 {
    let fx = x / scale;
    let fy = y / scale;
    let x0 = fx.floor() as i32;
    let y0 = fy.floor() as i32;
    let tx = fx - x0 as f32;
    let ty = fy - y0 as f32;
    let sx = tx * tx * (3.0 - 2.0 * tx);
    let sy = ty * ty * (3.0 - 2.0 * ty);
    let a = hash2(seed, x0, y0);
    let b = hash2(seed, x0 + 1, y0);
    let c = hash2(seed, x0, y0 + 1);
    let d = hash2(seed, x0 + 1, y0 + 1);
    let top = a + (b - a) * sx;
    let bot = c + (d - c) * sx;
    top + (bot - top) * sy
}

fn fbm(seed: u64, x: f32, y: f32) -> f32 {
    0.55 * value_noise(seed, x, y, 22.0) + 0.3 * value_noise(seed ^ 0xA5, x, y, 10.0) + 0.15 * value_noise(seed ^ 0x5A, x, y, 4.0)
}

/// Deterministic valley: a meandering river, a lake, forests, rocky outcrops.
pub fn generate(seed: u64) -> Map {
    let w = MAP_W as i32;
    let h = MAP_H as i32;
    let mut tiles = vec![Terrain::Grass as u8; (MAP_W * MAP_H) as usize];
    let set = |tiles: &mut Vec<u8>, x: i32, y: i32, t: Terrain| {
        if x >= 0 && y >= 0 && x < w && y < h {
            tiles[(y * w + x) as usize] = t as u8;
        }
    };
    for y in 0..h {
        for x in 0..w {
            let e = fbm(seed, x as f32, y as f32);
            let m = fbm(seed ^ 0x1234_5678, x as f32, y as f32);
            // Edges rise into rock so the valley is enclosed.
            let edge = (x.min(w - 1 - x).min(y).min(h - 1 - y)) as f32;
            let rim = if edge < 3.0 { 0.4 } else { 0.0 };
            let t = if e + rim > 0.74 {
                Terrain::Rock
            } else if m > 0.58 {
                Terrain::Forest
            } else if m < 0.3 && e > 0.55 {
                Terrain::Dirt
            } else {
                Terrain::Grass
            };
            set(&mut tiles, x, y, t);
        }
    }
    // River: meanders from north to south, west of center.
    let mut rx = w as f32 * 0.38 + (hash2(seed, 1, 1) - 0.5) * 10.0;
    for y in 0..h {
        rx += (value_noise(seed ^ 0xBEEF, 0.0, y as f32, 9.0) - 0.5) * 1.6;
        rx = rx.clamp(10.0, w as f32 - 10.0);
        let width = 1.5 + value_noise(seed ^ 0xCAFE, y as f32, 0.0, 12.0) * 1.5;
        for dx in -4..=4 {
            let x = (rx + dx as f32) as i32;
            let d = (x as f32 + 0.5 - rx).abs();
            if d <= width {
                set(&mut tiles, x, y, Terrain::Water);
            } else if d <= width + 1.2 && tiles[(y * w + x.clamp(0, w - 1)) as usize] != Terrain::Water as u8 {
                set(&mut tiles, x, y, Terrain::Sand);
            }
        }
    }
    // Two fords so both banks connect.
    for fy in [h / 3, (h * 2) / 3] {
        for x in 0..w {
            for dy in 0..2 {
                if tiles[((fy + dy) * w + x) as usize] == Terrain::Water as u8 {
                    set(&mut tiles, x, fy + dy, Terrain::Sand);
                }
            }
        }
    }
    // Lake east of center.
    let (lx, ly) = (w as f32 * 0.7, h as f32 * 0.35);
    for y in 0..h {
        for x in 0..w {
            let d = ((x as f32 - lx).powi(2) + (y as f32 - ly).powi(2) * 1.4).sqrt()
                + (value_noise(seed ^ 0x77, x as f32, y as f32, 5.0) - 0.5) * 3.0;
            if d < 5.5 {
                set(&mut tiles, x, y, Terrain::Water);
            } else if d < 7.0 && tiles[(y * w + x) as usize] != Terrain::Water as u8 {
                set(&mut tiles, x, y, Terrain::Sand);
            }
        }
    }
    Map { w: MAP_W, h: MAP_H, tiles, blocked: Default::default() }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn map_is_deterministic_and_connected_across_river() {
        let a = generate(7);
        let b = generate(7);
        assert_eq!(a.tiles, b.tiles);
        let west = a.nearest_walkable(20.0, 48.0).unwrap();
        let east = a.nearest_walkable(70.0, 60.0).unwrap();
        let path = a.path(west, east, 20_000).expect("path across river");
        assert!(!path.is_empty());
        let water = a.tiles.iter().filter(|t| **t == Terrain::Water as u8).count();
        assert!(water > 200, "river and lake exist: {water}");
    }

    #[test]
    fn chunk_roundtrip() {
        let m = generate(3);
        let chunks: Vec<_> = m.chunks().map(|id| (id, m.chunk_bytes(id))).collect();
        assert_eq!(Map::from_chunks(m.w, m.h, chunks).tiles, m.tiles);
        assert_eq!(chunk_of(17.0, 1.0), 1);
        assert_eq!(chunk_of(1.0, 17.0), 1 << 16);
        assert_eq!(chunks_around(1.0, 1.0, 8.0), vec![0]);
    }
}
