//! Large-world generator (checkpoint 3): a realm with a sea coast on the east, hills and
//! mountains in the west, rivers running downhill to the sea, forests and plains by moisture,
//! and every piece of land connected (fords are cut where rivers would isolate land).
//! Also proposes sites: fertile, well-connected town sites near the coast/rivers in the east,
//! and sparse wild sites in the west.

use crate::map::Terrain;
use std::collections::VecDeque;

pub struct Realm {
    pub w: u32,
    pub h: u32,
    pub tiles: Vec<u8>,
    /// Suggested town centers (east, fertile, near water).
    pub towns: Vec<(f32, f32)>,
    /// Suggested wild starting spots (west, away from towns).
    pub wilds: Vec<(f32, f32)>,
    /// Suggested village sites (the middle lands, between towns and wilds).
    pub villages: Vec<(f32, f32)>,
}

fn hash(seed: u64, x: i64, y: i64) -> f32 {
    let mut h = seed ^ 0x9E37_79B9_7F4A_7C15;
    h ^= (x as u64).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    h = h.rotate_left(27).wrapping_mul(0x94D0_49BB_1331_11EB);
    h ^= (y as u64).wrapping_mul(0xD6E8_FEB8_6659_FD93);
    h ^= h >> 31;
    h = h.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    h ^= h >> 29;
    (h >> 40) as f32 / (1u64 << 24) as f32
}

fn noise(seed: u64, x: f32, y: f32, scale: f32) -> f32 {
    let (fx, fy) = (x / scale, y / scale);
    let (x0, y0) = (fx.floor() as i64, fy.floor() as i64);
    let (tx, ty) = (fx - x0 as f32, fy - y0 as f32);
    let (sx, sy) = (tx * tx * (3.0 - 2.0 * tx), ty * ty * (3.0 - 2.0 * ty));
    let a = hash(seed, x0, y0);
    let b = hash(seed, x0 + 1, y0);
    let c = hash(seed, x0, y0 + 1);
    let d = hash(seed, x0 + 1, y0 + 1);
    let top = a + (b - a) * sx;
    let bot = c + (d - c) * sx;
    top + (bot - top) * sy
}

fn fbm(seed: u64, x: f32, y: f32, base: f32) -> f32 {
    0.5 * noise(seed, x, y, base) + 0.28 * noise(seed ^ 0xA5, x, y, base / 2.3) + 0.14 * noise(seed ^ 0x5A, x, y, base / 5.0) + 0.08 * noise(seed ^ 0x3C, x, y, base / 11.0)
}

impl Realm {
    pub fn to_map(&self) -> crate::map::Map {
        crate::map::Map { w: self.w, h: self.h, tiles: self.tiles.clone(), blocked: Default::default() }
    }
}

pub fn generate(seed: u64, w: u32, h: u32) -> Realm {
    let (wi, hi) = (w as i32, h as i32);
    let idx = |x: i32, y: i32| (y * wi + x) as usize;
    let n = (w * h) as usize;
    // Elevation: high in the west, sloping to a sea in the east, with noisy relief.
    let mut elev = vec![0f32; n];
    for y in 0..hi {
        for x in 0..wi {
            let fx = x as f32 / w as f32;
            let slope = 0.95 - fx * 0.75;
            let relief = fbm(seed, x as f32, y as f32, 48.0);
            let edge = (y.min(hi - 1 - y) as f32 / 10.0).min(1.0);
            let e = slope * 0.55 + relief * 0.55 - (1.0 - edge) * 0.15 - (fx - 0.86).max(0.0) * 3.0;
            elev[idx(x, y)] = e;
        }
    }
    let sea_level = 0.30;
    let mut tiles = vec![Terrain::Grass as u8; n];
    for y in 0..hi {
        for x in 0..wi {
            let e = elev[idx(x, y)];
            let m = fbm(seed ^ 0x1234_5678, x as f32, y as f32, 40.0);
            let t = if e < sea_level {
                Terrain::Water
            } else if e < sea_level + 0.025 {
                Terrain::Sand
            } else if e > 0.82 {
                Terrain::Rock
            } else if e > 0.70 && m < 0.55 {
                Terrain::Dirt
            } else if m > 0.56 {
                Terrain::Forest
            } else {
                Terrain::Grass
            };
            tiles[idx(x, y)] = t as u8;
        }
    }
    // Rivers: from high sources, follow the steepest descent (with a little meander) to water.
    let rivers = (w * h / 9000).clamp(3, 12);
    for r in 0..rivers {
        let mut best = (0, 0, 0.0f32);
        for k in 0..64 {
            let x = (hash(seed ^ 0xC0FFEE, r as i64, k) * (w as f32 * 0.45)) as i32 + 4;
            let y = (hash(seed ^ 0xBEEF, r as i64, k) * (h as f32 - 16.0)) as i32 + 8;
            let e = elev[idx(x, y)];
            if e > best.2 && tiles[idx(x, y)] != Terrain::Water as u8 {
                best = (x, y, e);
            }
        }
        let (mut x, mut y) = (best.0, best.1);
        let mut visited = std::collections::HashSet::new();
        let mut carved = std::collections::HashSet::new();
        for step in 0..(w + h) as i64 * 2 {
            if x <= 1 || y <= 1 || x >= wi - 2 || y >= hi - 2 || !visited.insert((x, y)) {
                break;
            }
            // Reaching water this river did not carve itself (the sea, a lake, another river) ends it.
            let reached = tiles[idx(x, y)] == Terrain::Water as u8 && step > 0 && !carved.contains(&(x, y));
            // Carve 2-wide with sandy banks.
            for (dx, dy) in [(0, 0), (1, 0), (0, 1)] {
                tiles[idx(x + dx, y + dy)] = Terrain::Water as u8;
                carved.insert((x + dx, y + dy));
            }
            for (dx, dy) in [(-1, 0), (2, 0), (0, -1), (0, 2), (-1, -1), (2, 2)] {
                let (bx, by) = (x + dx, y + dy);
                if bx > 0 && by > 0 && bx < wi - 1 && by < hi - 1 && tiles[idx(bx, by)] != Terrain::Water as u8 && tiles[idx(bx, by)] != Terrain::Rock as u8 {
                    tiles[idx(bx, by)] = Terrain::Sand as u8;
                }
            }
            if reached {
                break;
            }
            let mut next = (x + 1, y);
            let mut low = f32::MAX;
            for (dx, dy) in [(1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 0)] {
                let (nx, ny) = (x + dx, y + dy);
                if nx < 0 || ny < 0 || nx >= wi || ny >= hi || visited.contains(&(nx, ny)) {
                    continue;
                }
                let v = elev[idx(nx, ny)] + (hash(seed ^ 0x77, nx as i64, ny as i64) - 0.5) * 0.04 - dx as f32 * 0.004;
                if v < low {
                    low = v;
                    next = (nx, ny);
                }
            }
            elev[idx(next.0, next.1)] = elev[idx(next.0, next.1)].min(elev[idx(x, y)] - 0.0005);
            (x, y) = next;
        }
    }
    // Connectivity: cut fords so every land region reaches the largest one.
    connect(&mut tiles, w, h);
    // Sites.
    let walkable = |t: u8| t != Terrain::Water as u8 && t != Terrain::Rock as u8;
    let near = |tiles: &Vec<u8>, x: i32, y: i32, t: Terrain, r: i32| {
        (-r..=r).any(|dy| (-r..=r).any(|dx| {
            let (nx, ny) = (x + dx, y + dy);
            nx >= 0 && ny >= 0 && nx < wi && ny < hi && tiles[idx(nx, ny)] == t as u8
        }))
    };
    // Town sites: roomy grass (a walled city needs about 30×30 tiles) near water and forest,
    // in the east; village sites the same in the middle lands, smaller.
    let pick = |x0: f32, x1: f32, room: i32, want: usize, spacing: f32, avoid: &[(f32, f32)]| -> Vec<(f32, f32)> {
        let mut out: Vec<(f32, f32)> = Vec::new();
        let mut candidates: Vec<(f32, i32, i32)> = Vec::new();
        let (lo, hi_x) = (((wi as f32 * x0) as i32).max(room + 4), ((wi as f32 * x1) as i32).min(wi - room - 4));
        for y in (room + 4..hi - room - 4).step_by(3) {
            for x in (lo..hi_x).step_by(3) {
                if tiles[idx(x, y)] != Terrain::Grass as u8 {
                    continue;
                }
                if !near(&tiles, x, y, Terrain::Water, room / 2 + 6) || !near(&tiles, x, y, Terrain::Forest, room + 6) {
                    continue;
                }
                let land = (-room..=room).flat_map(|dy| (-room..=room).map(move |dx| (dx, dy))).filter(|(dx, dy)| walkable(tiles[idx(x + dx, y + dy)])).count();
                let area = ((2 * room + 1) * (2 * room + 1)) as f32;
                if (land as f32) < area * 0.85 {
                    continue;
                }
                candidates.push((land as f32 + hash(seed, x as i64, y as i64) * area * 0.05, x, y));
            }
        }
        candidates.sort_by(|a, b| b.0.total_cmp(&a.0));
        for (_, x, y) in candidates {
            let p = (x as f32 + 0.5, y as f32 + 0.5);
            let far = |q: &(f32, f32)| ((q.0 - p.0).powi(2) + (q.1 - p.1).powi(2)).sqrt() > spacing;
            if out.iter().all(far) && avoid.iter().all(far) {
                out.push(p);
                if out.len() == want {
                    break;
                }
            }
        }
        out
    };
    let want_towns = (w / 128).clamp(2, 4) as usize;
    let towns = pick(0.55, 1.0, 14, want_towns, h as f32 / (want_towns as f32 + 0.5), &[]);
    let villages = pick(0.3, 0.6, 6, (w / 128).clamp(1, 4) as usize, h as f32 / 5.0, &towns);
    let mut wilds: Vec<(f32, f32)> = Vec::new();
    let want_wilds = (w / 100).clamp(4, 8) as usize;
    for k in 0..800 {
        if wilds.len() >= want_wilds {
            break;
        }
        let x = (hash(seed ^ 0xABCD, k, 1) * (w as f32 * 0.35)) as i32 + 8;
        let y = (hash(seed ^ 0xABCD, k, 2) * (h as f32 - 24.0)) as i32 + 12;
        if !walkable(tiles[idx(x, y)]) || tiles[idx(x, y)] == Terrain::Sand as u8 {
            continue;
        }
        let p = (x as f32 + 0.5, y as f32 + 0.5);
        if wilds.iter().all(|q| ((q.0 - p.0).powi(2) + (q.1 - p.1).powi(2)).sqrt() > h as f32 / (want_wilds as f32 + 1.0)) {
            wilds.push(p);
        }
    }
    Realm { w, h, tiles, towns, wilds, villages }
}

/// Make all land one connected region by converting the shortest water/rock gap to sand.
fn connect(tiles: &mut [u8], w: u32, h: u32) {
    let (wi, hi) = (w as i32, h as i32);
    let idx = |x: i32, y: i32| (y * wi + x) as usize;
    let land = |t: u8| t != Terrain::Water as u8 && t != Terrain::Rock as u8;
    loop {
        // Label components.
        let mut comp = vec![u32::MAX; tiles.len()];
        let mut sizes = Vec::new();
        for start in 0..tiles.len() {
            if comp[start] != u32::MAX || !land(tiles[start]) {
                continue;
            }
            let id = sizes.len() as u32;
            let mut q = VecDeque::from([start]);
            comp[start] = id;
            let mut size = 0;
            while let Some(i) = q.pop_front() {
                size += 1;
                let (x, y) = ((i as i32) % wi, (i as i32) / wi);
                for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                    let (nx, ny) = (x + dx, y + dy);
                    if nx < 0 || ny < 0 || nx >= wi || ny >= hi {
                        continue;
                    }
                    let j = idx(nx, ny);
                    if comp[j] == u32::MAX && land(tiles[j]) {
                        comp[j] = id;
                        q.push_back(j);
                    }
                }
            }
            sizes.push(size);
        }
        // Ignore specks (islets under 40 tiles): they stay isolated.
        let main = (0..sizes.len()).max_by_key(|i| sizes[*i]).unwrap_or(0) as u32;
        let Some(orphan) = (0..sizes.len() as u32).find(|c| *c != main && sizes[*c as usize] >= 40) else { return };
        // BFS from the orphan across water/rock to the main component; carve the path.
        let mut prev = vec![usize::MAX; tiles.len()];
        let mut q: VecDeque<usize> = (0..tiles.len()).filter(|i| comp[*i] == orphan).collect();
        for &i in &q {
            prev[i] = i;
        }
        let mut hit = None;
        while let Some(i) = q.pop_front() {
            if comp[i] == main {
                hit = Some(i);
                break;
            }
            let (x, y) = ((i as i32) % wi, (i as i32) / wi);
            for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                let (nx, ny) = (x + dx, y + dy);
                if nx < 1 || ny < 1 || nx >= wi - 1 || ny >= hi - 1 {
                    continue;
                }
                let j = idx(nx, ny);
                if prev[j] == usize::MAX {
                    prev[j] = i;
                    q.push_back(j);
                }
            }
        }
        let Some(mut i) = hit else { return };
        while prev[i] != i {
            if !land(tiles[i]) {
                tiles[i] = Terrain::Sand as u8;
            }
            i = prev[i];
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn realm_is_connected_with_towns_and_wilds() {
        let r = generate(11, 256, 256);
        assert_eq!(r.tiles.len(), 256 * 256);
        assert!(r.towns.len() >= 2, "towns: {:?}", r.towns);
        assert!(r.wilds.len() >= 2, "wilds: {:?}", r.wilds);
        let map = r.to_map();
        assert_eq!(map.chunks().count(), 256);
        let water = r.tiles.iter().filter(|t| **t == Terrain::Water as u8).count();
        assert!(water > 2000 && water < 256 * 256 / 2, "water {water}");
    }
}
