//! Tile map: terrain generation, chunk addressing and grid pathfinding.
//! Positions are continuous tile coordinates; tile (i, j) spans [i, i+1) × [j, j+1).

use std::cmp::Ordering;
use std::collections::BinaryHeap;

/// Size of the classic valley map (the realm generator makes maps of any size).
pub const MAP_W: u32 = 96;
pub const MAP_H: u32 = 96;
pub const CHUNK: u32 = 16;
/// Largest supported map side (chunk coordinates are packed in 16 bits each).
pub const MAX_SIDE: u32 = 16384;

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
    /// Per chunk (`cy * chunks_wide + cx`): whether any of its tiles is opaque (rock or wall),
    /// built on the first sight test and kept by `set` and `put_chunk`, so a sight line over
    /// open chunks needs no tile walk. Code that writes `tiles` directly does so while
    /// generating a world, before any sight test.
    pub opaque: std::sync::OnceLock<Vec<bool>>,
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

    /// Whether a missile flies through a continuous position: walls, rock and shut gates
    /// stop it; water, forest and open ground do not.
    pub fn passable_missile(&self, x: f32, y: f32) -> bool {
        let (tx, ty) = (x.floor() as i32, y.floor() as i32);
        !matches!(self.get(tx, ty), Terrain::Wall | Terrain::Rock) && (self.blocked.is_empty() || !self.blocked.contains(&(ty as u32 * self.w + tx as u32)))
    }

    /// Change one tile (roads, walls); callers persist the chunk.
    pub fn set(&mut self, x: i32, y: i32, t: Terrain) {
        if x >= 0 && y >= 0 && x < self.w as i32 && y < self.h as i32 {
            self.tiles[(y as u32 * self.w + x as u32) as usize] = t as u8;
            self.refresh_opaque(x as u32 / CHUNK, y as u32 / CHUNK);
        }
    }

    fn chunk_opaque(&self, cx: u32, cy: u32) -> bool {
        (cy * CHUNK..((cy + 1) * CHUNK).min(self.h)).any(|y| (cx * CHUNK..((cx + 1) * CHUNK).min(self.w)).any(|x| matches!(Terrain::from_u8(self.tiles[(y * self.w + x) as usize]), Terrain::Wall | Terrain::Rock)))
    }

    fn opaque_chunks(&self) -> &[bool] {
        self.opaque.get_or_init(|| {
            let (cw, ch) = (self.w.div_ceil(CHUNK), self.h.div_ceil(CHUNK));
            (0..ch).flat_map(|cy| (0..cw).map(move |cx| (cx, cy))).map(|(cx, cy)| self.chunk_opaque(cx, cy)).collect()
        })
    }

    fn refresh_opaque(&mut self, cx: u32, cy: u32) {
        let o = self.chunk_opaque(cx, cy);
        let cw = self.w.div_ceil(CHUNK);
        if let Some(f) = self.opaque.get_mut() {
            if let Some(slot) = f.get_mut((cy * cw + cx) as usize) {
                *slot = o;
            }
        }
    }

    /// Whether nothing between `a` and `b` can block sight, by chunk: no opaque tile in any
    /// chunk the segment's box touches, and no shut gate in the box.
    fn open_between(&self, a: (f32, f32), b: (f32, f32)) -> bool {
        let (x0, x1) = (a.0.min(b.0).floor() as i32, a.0.max(b.0).floor() as i32);
        let (y0, y1) = (a.1.min(b.1).floor() as i32, a.1.max(b.1).floor() as i32);
        if x0 < 0 || y0 < 0 || x1 >= self.w as i32 || y1 >= self.h as i32 {
            return false;
        }
        let f = self.opaque_chunks();
        let cw = self.w.div_ceil(CHUNK);
        for cy in y0 as u32 / CHUNK..=y1 as u32 / CHUNK {
            for cx in x0 as u32 / CHUNK..=x1 as u32 / CHUNK {
                if f.get((cy * cw + cx) as usize).copied().unwrap_or(true) {
                    return false;
                }
            }
        }
        self.blocked.iter().all(|&i| {
            let (x, y) = ((i % self.w) as i32, (i / self.w) as i32);
            x < x0 || x > x1 || y < y0 || y > y1
        })
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

    /// Overwrite one chunk's tiles from its row bytes (as stored by `chunk_bytes`).
    pub fn put_chunk(&mut self, id: u32, bytes: &[u8]) {
        let (cx, cy) = chunk_xy(id);
        for (k, b) in bytes.iter().enumerate() {
            let x = cx * CHUNK + k as u32 % CHUNK;
            let y = cy * CHUNK + k as u32 / CHUNK;
            if x < self.w && y < self.h {
                self.tiles[(y * self.w + x) as usize] = *b;
            }
        }
        self.refresh_opaque(cx, cy);
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
        Self { w, h, tiles, blocked: Default::default(), opaque: Default::default() }
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

    /// Whether one can see from `a` to `b`: no tile the segment crosses between the two ends
    /// is opaque (wall, rock or a shut gate, as for missiles; water, forest and open ground
    /// are not). The ends' own tiles never block, so someone standing in a gateway is seen.
    /// Walks the exact tiles the segment crosses (a grid traversal), so its cost grows with
    /// the distance in tiles, not with a sampling rate.
    pub fn sight_clear(&self, a: (f32, f32), b: (f32, f32)) -> bool {
        self.open_between(a, b) || self.sight_walk(a, b)
    }

    /// The tile walk behind [`Map::sight_clear`].
    fn sight_walk(&self, a: (f32, f32), b: (f32, f32)) -> bool {
        let (mut tx, mut ty) = (a.0.floor() as i32, a.1.floor() as i32);
        let end = (b.0.floor() as i32, b.1.floor() as i32);
        let (dx, dy) = (b.0 - a.0, b.1 - a.1);
        let (sx, sy) = (dx.signum() as i32, dy.signum() as i32);
        // Parameter t along the segment at the next vertical and horizontal tile edge.
        let next = |p: f32, d: f32, t: i32| if d > 0.0 { (t as f32 + 1.0 - p) / d } else if d < 0.0 { (t as f32 - p) / d } else { f32::INFINITY };
        let (mut tmx, mut tmy) = (next(a.0, dx, tx), next(a.1, dy, ty));
        let (tdx, tdy) = (if dx != 0.0 { 1.0 / dx.abs() } else { f32::INFINITY }, if dy != 0.0 { 1.0 / dy.abs() } else { f32::INFINITY });
        let mut guard = (end.0 - tx).abs() + (end.1 - ty).abs() + 2;
        while (tx, ty) != end && guard > 0 {
            guard -= 1;
            if tmx < tmy {
                tx += sx;
                tmx += tdx;
            } else {
                ty += sy;
                tmy += tdy;
            }
            if (tx, ty) != end && !self.passable_missile(tx as f32 + 0.5, ty as f32 + 0.5) {
                return false;
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
        // Cost so far and predecessor of each reached tile. A search touches at most
        // `max_expansions` × 8 tiles, so it keeps them in a map sized by that budget instead of
        // two arrays the size of the whole map (32 MiB per call on a 2048 m world, written in
        // full before the search starts). Results are identical: missing entries read as the
        // arrays' initial `u32::MAX`.
        let n = (self.w * self.h) as usize;
        let mut seen: Reached = Reached::with_capacity_and_hasher((max_expansions * 2).min(n).min(1 << 16), Default::default());
        let g_of = |seen: &Reached, i: usize| seen.get(&(i as u32)).map_or(u32::MAX, |e| e.0);
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
        seen.insert(idx(start) as u32, (0, u32::MAX));
        open.push(Open(h(start), 0, start));
        let mut expansions = 0;
        let mut found = false;
        while let Some(Open(_, cost, p)) = open.pop() {
            if p == goal {
                found = true;
                break;
            }
            if cost > g_of(&seen, idx(p)) {
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
                if nc < g_of(&seen, idx(q)) {
                    seen.insert(idx(q) as u32, (nc, idx(p) as u32));
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
            let prev = seen.get(&(cur as u32)).map_or(u32::MAX, |e| e.1);
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

/// Tiles reached by a path search: index → (cost so far, predecessor index).
type Reached = std::collections::HashMap<u32, (u32, u32), std::hash::BuildHasherDefault<TileHasher>>;

/// Multiplicative hash for tile indices (the default SipHash is several times slower here,
/// and the keys are not attacker-chosen).
#[derive(Default)]
struct TileHasher(u64);

impl std::hash::Hasher for TileHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for b in bytes {
            self.0 = (self.0 ^ *b as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
        }
    }
    fn write_u32(&mut self, v: u32) {
        self.0 = (v as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15);
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
    Map { w: MAP_W, h: MAP_H, tiles, blocked: Default::default(), opaque: Default::default() }
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

    #[test]
    fn sight_is_stopped_by_walls_rock_and_shut_gates_only() {
        let mut m = Map { w: 32, h: 32, tiles: vec![Terrain::Grass as u8; 32 * 32], blocked: Default::default(), opaque: Default::default() };
        // A wall across x = 10 from y = 0 to y = 19, water at x = 20.
        for y in 0..20 {
            m.set(10, y, Terrain::Wall);
            m.set(20, y, Terrain::Water);
        }
        assert!(!m.sight_clear((5.5, 5.5), (15.5, 5.5)), "a wall hides");
        assert!(!m.sight_clear((5.2, 5.7), (15.9, 9.1)), "a slanted line through the wall");
        assert!(m.sight_clear((5.5, 25.5), (15.5, 25.5)), "past the wall's end");
        assert!(m.sight_clear((5.5, 21.5), (15.5, 21.5)), "the wall's end is not crossed");
        assert!(m.sight_clear((15.5, 5.5), (25.5, 5.5)), "water does not hide");
        assert!(m.sight_clear((10.5, 5.5), (5.5, 5.5)), "standing in the wall's own tile");
        assert!(m.sight_clear((3.5, 3.5), (3.5, 3.5)), "the same tile");
        m.set(3, 12, Terrain::Rock);
        assert!(!m.sight_clear((3.5, 10.5), (3.5, 14.5)), "rock hides, vertically");
        assert!(m.sight_clear((2.5, 10.5), (2.5, 14.5)), "beside the rock");
        // A shut gate in a gap of the wall.
        m.set(10, 5, Terrain::Grass);
        assert!(m.sight_clear((5.5, 5.5), (15.5, 5.5)), "through an open gateway");
        m.blocked.insert(5 * 32 + 10);
        assert!(!m.sight_clear((5.5, 5.5), (15.5, 5.5)), "a shut gate hides");
        // Exactly along a tile corner: the traversal must not slip diagonally between two
        // walls touching at a corner.
        let mut c = Map { w: 8, h: 8, tiles: vec![Terrain::Grass as u8; 64], blocked: Default::default(), opaque: Default::default() };
        c.set(3, 4, Terrain::Wall);
        c.set(4, 3, Terrain::Wall);
        assert!(!c.sight_clear((2.5, 5.5), (5.5, 2.5)), "two walls meeting at a corner hide");
    }

    #[test]
    fn sight_over_open_chunks_agrees_with_the_tile_walk() {
        let mut m = Map { w: 64, h: 64, tiles: vec![Terrain::Grass as u8; 64 * 64], blocked: Default::default(), opaque: Default::default() };
        // Walls and rock in some chunks, none in others.
        let mut r: u64 = 7;
        let mut next = || {
            r ^= r << 13;
            r ^= r >> 7;
            r ^= r << 17;
            r
        };
        for _ in 0..60 {
            let (x, y) = ((next() % 32) as i32, (next() % 64) as i32);
            m.set(x, y, if next() % 2 == 0 { Terrain::Wall } else { Terrain::Rock });
        }
        for _ in 0..4000 {
            let a = ((next() % 6400) as f32 / 100.0, (next() % 6400) as f32 / 100.0);
            let b = ((a.0 + (next() % 2400) as f32 / 100.0 - 12.0).clamp(0.0, 63.9), (a.1 + (next() % 2400) as f32 / 100.0 - 12.0).clamp(0.0, 63.9));
            assert_eq!(m.sight_clear(a, b), m.sight_walk(a, b), "{a:?} -> {b:?}");
        }
        // A wall built after the first sight test, in a chunk that was open, hides at once;
        // so does a gate shut there.
        assert!(m.sight_clear((40.5, 40.5), (50.5, 40.5)));
        m.set(45, 40, Terrain::Wall);
        assert!(!m.sight_clear((40.5, 40.5), (50.5, 40.5)), "a new wall hides");
        m.set(45, 40, Terrain::Grass);
        assert!(m.sight_clear((40.5, 40.5), (50.5, 40.5)), "and is gone");
        m.blocked.insert(40 * 64 + 45);
        assert!(!m.sight_clear((40.5, 40.5), (50.5, 40.5)), "a shut gate hides");
    }
}
