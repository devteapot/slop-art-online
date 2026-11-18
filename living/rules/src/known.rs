//! Known ground (docs/MOVEMENT_MIND.md, step 3): what a character has seen of the map, kept as a
//! mask over the shared map, and the walking plan over it.
//!
//! - **The mask.** The map is cut into 4 m cells, sixteen to a 16 m chunk; a character marks a
//!   cell when it sees it (the one sight rule, out to the world's `ground_sight_m`). A row per
//!   128 m block (8 × 8 chunks) holds its chunks' masks and, per chunk, the map's edit count when
//!   the chunk was last seen.
//! - **The belief.** A seen tile is what it was when seen: the map now, with the edits made since
//!   undone. A gate is as last seen. Everything else is unknown.
//! - **The plan.** A coarse route over chunks on the belief (unknown ground passable at a cost),
//!   then a tile search over the next `leg_m` of it through those chunks and the ones beside them.
//!   Unseen ground is never read.

use crate::map::{chunk_id, chunk_xy, Map, Terrain, CHUNK};
use std::cell::RefCell;
use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap};

/// Metres a cell's side.
pub const CELL: u32 = 4;
/// Cells along a chunk's side.
const CELLS: u32 = CHUNK / CELL;
/// Chunks along a block's side (the routes' blocks, `nav`).
pub const BLOCK: u32 = 8;
/// Chunks in a block.
pub const SLOTS: usize = (BLOCK * BLOCK) as usize;

/// The block of a chunk and the chunk's slot in it.
pub fn block_of(chunk: u32) -> (u32, usize) {
    let (cx, cy) = chunk_xy(chunk);
    (chunk_id(cx / BLOCK, cy / BLOCK), ((cy % BLOCK) * BLOCK + cx % BLOCK) as usize)
}

/// The chunk of a tile and its cell's bit in the chunk's mask.
pub fn cell_of(x: i32, y: i32) -> (u32, u16) {
    let (x, y) = (x.max(0) as u32, y.max(0) as u32);
    let chunk = chunk_id(x / CHUNK, y / CHUNK);
    let (lx, ly) = (x % CHUNK / CELL, y % CHUNK / CELL);
    (chunk, 1u16 << (ly * CELLS + lx))
}

/// One block of a character's known ground.
#[derive(Clone, Debug, PartialEq)]
pub struct Known {
    /// Per chunk slot, the cells seen.
    pub cells: [u16; SLOTS],
    /// Per chunk slot, the map's edit count when it was last seen.
    pub seen_at: [u32; SLOTS],
}

impl Default for Known {
    fn default() -> Self {
        Self { cells: [0; SLOTS], seen_at: [0; SLOTS] }
    }
}

impl Known {
    pub fn has(&self, slot: usize, bit: u16) -> bool {
        self.cells[slot] & bit != 0
    }

    /// Mark a cell seen at edit count `epoch`.
    pub fn mark(&mut self, slot: usize, bit: u16, epoch: u32) {
        self.cells[slot] |= bit;
        self.seen_at[slot] = epoch;
    }

    pub fn cells_bytes(&self) -> Vec<u8> {
        self.cells.iter().flat_map(|c| c.to_le_bytes()).collect()
    }

    pub fn seen_bytes(&self) -> Vec<u8> {
        self.seen_at.iter().flat_map(|c| c.to_le_bytes()).collect()
    }

    pub fn from_bytes(cells: &[u8], seen: &[u8]) -> Self {
        let mut k = Known::default();
        for (i, c) in cells.chunks_exact(2).take(SLOTS).enumerate() {
            k.cells[i] = u16::from_le_bytes([c[0], c[1]]);
        }
        for (i, c) in seen.chunks_exact(4).take(SLOTS).enumerate() {
            k.seen_at[i] = u32::from_le_bytes([c[0], c[1], c[2], c[3]]);
        }
        k
    }

    /// How many cells are marked.
    pub fn count(&self) -> u32 {
        self.cells.iter().map(|c| c.count_ones()).sum()
    }
}

/// Cell offsets, in cells from the eye's cell, that can lie within `radius` metres, nearest first.
pub fn ring(radius: f32) -> Vec<(i32, i32)> {
    let r = (radius / CELL as f32).ceil() as i32 + 1;
    let mut v: Vec<(i32, i32, i32)> = Vec::new();
    for dy in -r..=r {
        for dx in -r..=r {
            if ((dx * dx + dy * dy) as f32).sqrt() * CELL as f32 <= radius + CELL as f32 * 1.5 {
                v.push((dx * dx + dy * dy, dx, dy));
            }
        }
    }
    v.sort_unstable();
    v.into_iter().map(|(_, dx, dy)| (dx, dy)).collect()
}

/// The cells newly seen from `eye` within `radius`: each that `known` does not hold, whose centre
/// (or, for a cell one cannot see into, such as a wall's, its side toward the eye) `sees`
/// accepts, nearest first. At most `cap` (0: no cap); cells over the cap stay unmarked and are
/// found again by a later pass while they are in view, so nothing is dropped.
#[allow(clippy::too_many_arguments)]
pub fn newly_seen(map: &Map, eye: (f32, f32), offsets: &[(i32, i32)], radius: f32, cap: usize, mut known: impl FnMut(u32, u16) -> bool, mut sees: impl FnMut((f32, f32), f32) -> bool) -> Vec<(u32, u16)> {
    let (ex, ey) = (eye.0.floor() as i32 / CELL as i32, eye.1.floor() as i32 / CELL as i32);
    let mut out = Vec::new();
    for &(dx, dy) in offsets {
        let (cx, cy) = (ex + dx, ey + dy);
        if cx < 0 || cy < 0 || (cx * CELL as i32) >= map.w as i32 || (cy * CELL as i32) >= map.h as i32 {
            continue;
        }
        let half = CELL as f32 / 2.0;
        let centre = ((cx * CELL as i32) as f32 + half, (cy * CELL as i32) as f32 + half);
        let d = ((centre.0 - eye.0).powi(2) + (centre.1 - eye.1).powi(2)).sqrt();
        if d > radius + half {
            continue;
        }
        let (chunk, bit) = cell_of(cx * CELL as i32, cy * CELL as i32);
        if known(chunk, bit) {
            continue;
        }
        // The cell's side toward the eye: a wall's face is seen though its middle is not.
        let near = if d > half + 0.5 { (centre.0 + (eye.0 - centre.0) * (half + 0.25) / d, centre.1 + (eye.1 - centre.1) * (half + 0.25) / d) } else { centre };
        if sees(centre, d) || sees(near, d - half) {
            out.push((chunk, bit));
            if cap > 0 && out.len() >= cap {
                break;
            }
        }
    }
    out
}

/// What a character believes of one tile.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ground {
    Open,
    Road,
    Blocked,
    Unknown,
}

/// A tile edit after genesis: the edit count, the tile's index in its chunk and its byte before.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Edit {
    pub epoch: u32,
    pub tile: u16,
    pub before: u8,
}

/// One character's belief over the shared map. Blocks and edits are loaded when first asked for.
pub struct Belief<'a> {
    map: &'a Map,
    load_block: RefCell<Box<dyn FnMut(u32) -> Option<Known> + 'a>>,
    load_edits: RefCell<Box<dyn FnMut(u32) -> Vec<Edit> + 'a>>,
    blocks: RefCell<HashMap<u32, Option<Known>>>,
    edits: RefCell<HashMap<u32, Vec<Edit>>>,
    /// Gates as last seen, by tile index (`y * w + x`): open or shut.
    gates: HashMap<u32, bool>,
}

impl<'a> Belief<'a> {
    pub fn new(map: &'a Map, load_block: impl FnMut(u32) -> Option<Known> + 'a, load_edits: impl FnMut(u32) -> Vec<Edit> + 'a, gates: HashMap<u32, bool>) -> Self {
        Self { map, load_block: RefCell::new(Box::new(load_block)), load_edits: RefCell::new(Box::new(load_edits)), blocks: RefCell::default(), edits: RefCell::default(), gates }
    }

    fn known(&self, chunk: u32) -> (Option<Known>, usize) {
        let (block, slot) = block_of(chunk);
        let mut blocks = self.blocks.borrow_mut();
        let k = blocks.entry(block).or_insert_with(|| (self.load_block.borrow_mut())(block)).clone();
        (k, slot)
    }

    /// The chunk's seen-cell mask and the edit count it was seen at.
    pub fn chunk_mask(&self, chunk: u32) -> (u16, u32) {
        let (block, slot) = block_of(chunk);
        let mut blocks = self.blocks.borrow_mut();
        let k = blocks.entry(block).or_insert_with(|| (self.load_block.borrow_mut())(block));
        k.as_ref().map_or((0, 0), |k| (k.cells[slot], k.seen_at[slot]))
    }

    pub fn ground(&self, x: i32, y: i32) -> Ground {
        if x < 0 || y < 0 || x >= self.map.w as i32 || y >= self.map.h as i32 {
            return Ground::Blocked;
        }
        let (chunk, bit) = cell_of(x, y);
        let (mask, seen_at) = self.chunk_mask(chunk);
        if mask & bit == 0 {
            return Ground::Unknown;
        }
        let mut byte = self.map.tiles[(y as u32 * self.map.w + x as u32) as usize];
        let tile = ((y as u32 % CHUNK) * CHUNK + x as u32 % CHUNK) as u16;
        {
            let mut edits = self.edits.borrow_mut();
            let list = edits.entry(chunk).or_insert_with(|| (self.load_edits.borrow_mut())(chunk));
            // The tile as it was when seen: the first edit to it made after then holds that byte.
            if let Some(e) = list.iter().filter(|e| e.tile == tile && e.epoch > seen_at).min_by_key(|e| e.epoch) {
                byte = e.before;
            }
        }
        let t = Terrain::from_u8(byte);
        if !t.walkable() || self.gates.get(&(y as u32 * self.map.w + x as u32)) == Some(&false) {
            return Ground::Blocked;
        }
        if t == Terrain::Road {
            Ground::Road
        } else {
            Ground::Open
        }
    }

    /// Whether a body could walk the straight line from `a` to `b` on what it believes (unknown
    /// ground counts as open).
    pub fn line_open(&self, a: (f32, f32), b: (f32, f32)) -> bool {
        let d = ((b.0 - a.0).powi(2) + (b.1 - a.1).powi(2)).sqrt();
        let n = (d * 4.0).ceil().max(1.0) as i32;
        (0..=n).all(|k| {
            let t = k as f32 / n as f32;
            self.ground((a.0 + (b.0 - a.0) * t).floor() as i32, (a.1 + (b.1 - a.1) * t).floor() as i32) != Ground::Blocked
        })
    }
}

/// How a plan over a belief is shaped (the world's laws).
#[derive(Clone, Copy, Debug)]
pub struct Shape {
    /// Cost of a metre of unseen ground against seen open ground.
    pub unknown_cost: f32,
    /// Speed on roads against open ground.
    pub road_speed: f32,
    /// Metres of tiles planned in one leg.
    pub leg_m: f32,
    /// Most nodes either search expands.
    pub max_nodes: usize,
}

impl Default for Shape {
    fn default() -> Self {
        Self { unknown_cost: 1.5, road_speed: 1.4, leg_m: 64.0, max_nodes: 40_000 }
    }
}

/// Per chunk on the belief: passable, and the mean cost of a metre over its passable tiles.
fn chunk_cost(b: &Belief, chunk: u32, s: &Shape) -> Option<f32> {
    let (mask, _) = b.chunk_mask(chunk);
    let (cx, cy) = chunk_xy(chunk);
    let (mut n, mut cost) = (0u32, 0f32);
    for cell in 0..(CELLS * CELLS) {
        if mask & (1 << cell) == 0 {
            n += CELL * CELL;
            cost += (CELL * CELL) as f32 * s.unknown_cost;
            continue;
        }
        let (ox, oy) = (cx * CHUNK + (cell % CELLS) * CELL, cy * CHUNK + (cell / CELLS) * CELL);
        for ty in 0..CELL {
            for tx in 0..CELL {
                match b.ground((ox + tx) as i32, (oy + ty) as i32) {
                    Ground::Blocked => {}
                    Ground::Road => {
                        n += 1;
                        cost += 1.0 / s.road_speed;
                    }
                    Ground::Open => {
                        n += 1;
                        cost += 1.0;
                    }
                    Ground::Unknown => {
                        n += 1;
                        cost += s.unknown_cost;
                    }
                }
            }
        }
    }
    (n >= CHUNK).then(|| cost / n as f32)
}

/// Why no leg could be planned.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NoLeg {
    /// Nothing passable on the belief joins the two (as far as the searches go).
    NoWay,
    /// The goal is on ground believed blocked.
    GoalBlocked,
}

fn centre(chunk: u32) -> (f32, f32) {
    let (cx, cy) = chunk_xy(chunk);
    ((cx * CHUNK) as f32 + CHUNK as f32 / 2.0, (cy * CHUNK) as f32 + CHUNK as f32 / 2.0)
}

fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}

/// A coarse route over chunks from `from` to `to` on the belief, without the `barred` steps.
fn coarse(b: &Belief, from: (f32, f32), to: (f32, f32), s: &Shape, barred: &[(u32, u32)], costs: &mut HashMap<u32, Option<f32>>) -> Option<Vec<u32>> {
    let start = crate::map::chunk_of(from.0, from.1);
    let goal = crate::map::chunk_of(to.0, to.1);
    let (cw, ch) = (b.map.w.div_ceil(CHUNK), b.map.h.div_ceil(CHUNK));
    let mut g: HashMap<u32, u32> = HashMap::new();
    let mut parent: HashMap<u32, u32> = HashMap::new();
    let mut heap = BinaryHeap::new();
    g.insert(start, 0);
    heap.push(Reverse((0u32, 0u32, start)));
    let mut expanded = 0;
    while let Some(Reverse((_, cost, c))) = heap.pop() {
        if c == goal {
            let mut route = vec![c];
            let mut k = c;
            while let Some(&p) = parent.get(&k) {
                route.push(p);
                k = p;
            }
            route.reverse();
            return Some(route);
        }
        if cost > *g.get(&c).unwrap_or(&u32::MAX) {
            continue;
        }
        expanded += 1;
        if expanded > s.max_nodes {
            return None;
        }
        let (x, y) = chunk_xy(c);
        let fc = costs.entry(c).or_insert_with(|| if c == start || c == goal { Some(1.0) } else { chunk_cost(b, c, s) }).unwrap_or(1.0);
        for (dx, dy) in [(1i32, 0i32), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)] {
            let (nx, ny) = (x as i32 + dx, y as i32 + dy);
            if nx < 0 || ny < 0 || nx >= cw as i32 || ny >= ch as i32 {
                continue;
            }
            let n = chunk_id(nx as u32, ny as u32);
            if barred.contains(&(c, n)) {
                continue;
            }
            let Some(fn_) = *costs.entry(n).or_insert_with(|| if n == goal { Some(1.0) } else { chunk_cost(b, n, s) }) else { continue };
            let step = if dx != 0 && dy != 0 { 22.6 } else { 16.0 } * (fc + fn_) / 2.0;
            let nc = cost + (step * 100.0) as u32;
            if nc < *g.get(&n).unwrap_or(&u32::MAX) {
                g.insert(n, nc);
                parent.insert(n, c);
                let h = (dist(centre(n), to) / s.road_speed * 100.0) as u32;
                heap.push(Reverse((nc + h, nc, n)));
            }
        }
    }
    None
}

/// A tile search on the belief from `from` to `to` within `allowed` chunks. The path's points are
/// tile centres, after the start, ending at `to`.
fn tiles(b: &Belief, from: (f32, f32), to: (f32, f32), allowed: &std::collections::HashSet<u32>, s: &Shape) -> Option<Vec<(f32, f32)>> {
    let start = (from.0.floor() as i32, from.1.floor() as i32);
    let goal = (to.0.floor() as i32, to.1.floor() as i32);
    let w = b.map.w as i32;
    let key = |p: (i32, i32)| (p.1 * w + p.0) as u32;
    let ok = |p: (i32, i32)| allowed.contains(&crate::map::chunk_of(p.0 as f32, p.1 as f32)) && b.ground(p.0, p.1) != Ground::Blocked;
    let cost_of = |p: (i32, i32)| match b.ground(p.0, p.1) {
        Ground::Road => 1.0 / s.road_speed,
        Ground::Unknown => s.unknown_cost,
        _ => 1.0,
    };
    let mut g: HashMap<u32, u32> = HashMap::new();
    let mut parent: HashMap<u32, (i32, i32)> = HashMap::new();
    let mut heap = BinaryHeap::new();
    g.insert(key(start), 0);
    heap.push(Reverse((0u32, 0u32, start.0, start.1)));
    let mut expanded = 0;
    let mut found = false;
    while let Some(Reverse((_, cost, x, y))) = heap.pop() {
        if (x, y) == goal {
            found = true;
            break;
        }
        if cost > *g.get(&key((x, y))).unwrap_or(&u32::MAX) {
            continue;
        }
        expanded += 1;
        if expanded > s.max_nodes {
            return None;
        }
        for (dx, dy) in [(1i32, 0i32), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)] {
            let n = (x + dx, y + dy);
            if !ok(n) || (dx != 0 && dy != 0 && !(ok((x + dx, y)) && ok((x, y + dy)))) {
                continue;
            }
            let step = if dx != 0 && dy != 0 { 141.0 } else { 100.0 } * cost_of(n);
            let nc = cost + step as u32;
            if nc < *g.get(&key(n)).unwrap_or(&u32::MAX) {
                g.insert(key(n), nc);
                parent.insert(key(n), (x, y));
                let h = (((n.0 - goal.0) as f32).hypot((n.1 - goal.1) as f32) * 100.0 / s.road_speed) as u32;
                heap.push(Reverse((nc + h, nc, n.0, n.1)));
            }
        }
    }
    if !found {
        return None;
    }
    let mut cells = vec![goal];
    let mut k = goal;
    while let Some(&p) = parent.get(&key(k)) {
        if p == start {
            break;
        }
        cells.push(p);
        k = p;
    }
    cells.reverse();
    // String pulling on the belief: from where it stands, the farthest point it can walk straight to.
    let pts: Vec<(f32, f32)> = cells.iter().map(|&(x, y)| (x as f32 + 0.5, y as f32 + 0.5)).collect();
    let mut out = Vec::new();
    let mut at = from;
    let mut i = 0;
    while i < pts.len() {
        let mut j = pts.len() - 1;
        while j > i && !b.line_open(at, pts[j]) {
            j -= 1;
        }
        out.push(pts[j]);
        at = pts[j];
        i = j + 1;
    }
    if let Some(last) = out.last_mut() {
        if (last.0.floor() as i32, last.1.floor() as i32) == goal {
            *last = to;
        }
    }
    Some(out)
}

/// The next leg of a walk from `from` to `to` on what one believes: the corners of the path over
/// the next `leg_m` of a coarse route (all the way when the goal is that near). A leg whose tiles
/// cannot follow its coarse route bars that stretch's last chunk and routes again (a few times).
pub fn leg(b: &Belief, from: (f32, f32), to: (f32, f32), s: &Shape) -> Result<Vec<(f32, f32)>, NoLeg> {
    if b.ground(to.0.floor() as i32, to.1.floor() as i32) == Ground::Blocked {
        return Err(NoLeg::GoalBlocked);
    }
    let mut costs = HashMap::new();
    let mut barred: Vec<(u32, u32)> = Vec::new();
    for attempt in 0..24 {
        let route = coarse(b, from, to, s, &barred, &mut costs).ok_or(NoLeg::NoWay)?;
        // The stretch for this leg: chunks along the route until `leg_m`, and the ones beside them
        // (two deep after repeated failures).
        let mut walked = 0.0;
        let mut end = route.len() - 1;
        let mut prev = from;
        for (i, &c) in route.iter().enumerate().skip(1) {
            walked += dist(prev, centre(c));
            prev = centre(c);
            if walked >= s.leg_m {
                end = i;
                break;
            }
        }
        let reaches_goal = end == route.len() - 1;
        let target = if reaches_goal { to } else { nearest_passable(b, route[end]).unwrap_or(centre(route[end])) };
        let ring: i32 = if attempt < 12 { 1 } else { 2 };
        let mut allowed = std::collections::HashSet::new();
        for &c in &route[..=end] {
            let (x, y) = chunk_xy(c);
            for dy in -ring..=ring {
                for dx in -ring..=ring {
                    let (nx, ny) = (x as i32 + dx, y as i32 + dy);
                    if nx >= 0 && ny >= 0 {
                        allowed.insert(chunk_id(nx as u32, ny as u32));
                    }
                }
            }
        }
        if let Some(path) = tiles(b, from, target, &allowed, s) {
            if !path.is_empty() {
                return Ok(path);
            }
        }
        // Where the tiles stop: the first step of the route into a chunk the start cannot reach
        // within the stretch. Bar that step (both ways) and route again.
        let reached = reach(b, from, &allowed, s);
        let step = (0..end).find(|&i| !reached.contains(&route[i + 1])).unwrap_or(end.saturating_sub(1));
        if route.len() < 2 {
            return Err(NoLeg::NoWay);
        }
        let (p, q) = (route[step], route[(step + 1).min(route.len() - 1)]);
        barred.push((p, q));
        barred.push((q, p));
    }
    Err(NoLeg::NoWay)
}

/// The chunks holding a tile reachable from `from` on the belief within `allowed` chunks.
fn reach(b: &Belief, from: (f32, f32), allowed: &std::collections::HashSet<u32>, s: &Shape) -> std::collections::HashSet<u32> {
    let w = b.map.w as i32;
    let start = (from.0.floor() as i32, from.1.floor() as i32);
    let ok = |p: (i32, i32)| allowed.contains(&crate::map::chunk_of(p.0 as f32, p.1 as f32)) && b.ground(p.0, p.1) != Ground::Blocked;
    let mut seen = std::collections::HashSet::new();
    let mut chunks = std::collections::HashSet::new();
    let mut stack = vec![start];
    seen.insert(start.1 * w + start.0);
    while let Some((x, y)) = stack.pop() {
        chunks.insert(crate::map::chunk_of(x as f32, y as f32));
        if seen.len() > s.max_nodes {
            break;
        }
        for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
            let n = (x + dx, y + dy);
            if ok(n) && seen.insert(n.1 * w + n.0) {
                stack.push(n);
            }
        }
    }
    chunks
}

/// The passable tile of a chunk nearest its centre, on the belief.
fn nearest_passable(b: &Belief, chunk: u32) -> Option<(f32, f32)> {
    let c = centre(chunk);
    let (cx, cy) = chunk_xy(chunk);
    let mut best: Option<((f32, f32), f32)> = None;
    for ty in 0..CHUNK {
        for tx in 0..CHUNK {
            let (x, y) = ((cx * CHUNK + tx) as i32, (cy * CHUNK + ty) as i32);
            if b.ground(x, y) == Ground::Blocked {
                continue;
            }
            let p = (x as f32 + 0.5, y as f32 + 0.5);
            let d = dist(p, c);
            if best.map_or(true, |(_, bd)| d < bd) {
                best = Some((p, d));
            }
        }
    }
    best.map(|(p, _)| p)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn open(w: u32, h: u32) -> Map {
        Map { w, h, tiles: vec![Terrain::Grass as u8; (w * h) as usize], blocked: Default::default(), opaque: Default::default(), nav: Default::default() }
    }

    /// A belief from a list of blocks fully seen at edit count 0, with edits by chunk.
    fn belief<'a>(m: &'a Map, seen: &'a [u32], edits: &'a [(u32, Edit)], gates: HashMap<u32, bool>) -> Belief<'a> {
        Belief::new(
            m,
            move |block| {
                let mut k = Known::default();
                let mut any = false;
                for slot in 0..SLOTS {
                    let (bx, by) = chunk_xy(block);
                    let chunk = chunk_id(bx * BLOCK + slot as u32 % BLOCK, by * BLOCK + slot as u32 / BLOCK);
                    if seen.contains(&chunk) {
                        k.cells[slot] = u16::MAX;
                        any = true;
                    }
                }
                any.then_some(k)
            },
            move |chunk| edits.iter().filter(|(c, _)| *c == chunk).map(|(_, e)| *e).collect(),
            gates,
        )
    }

    fn wall(m: &mut Map, x: i32, y0: i32, y1: i32) {
        for y in y0..=y1 {
            m.set(x, y, Terrain::Wall);
        }
    }

    fn all_chunks(m: &Map) -> Vec<u32> {
        m.chunks().collect()
    }

    fn crosses(path: &[(f32, f32)], from: (f32, f32), x: f32) -> Option<f32> {
        let mut a = from;
        for &b in path {
            if (a.0 - x) * (b.0 - x) <= 0.0 && a.0 != b.0 {
                let t = (x - a.0) / (b.0 - a.0);
                return Some(a.1 + (b.1 - a.1) * t);
            }
            a = b;
        }
        None
    }

    #[test]
    fn cells_bytes_round_trip() {
        let mut k = Known::default();
        k.mark(3, 1 << 5, 7);
        k.mark(63, 1 << 15, 9);
        let back = Known::from_bytes(&k.cells_bytes(), &k.seen_bytes());
        assert_eq!(back, k);
        assert_eq!(back.count(), 2);
        assert_eq!(cell_of(16 * 9 + 5, 16 * 2 + 13), (chunk_id(9, 2), 1 << (3 * CELLS + 1)));
        assert_eq!(block_of(chunk_id(9, 2)), (chunk_id(1, 0), (2 * BLOCK + 1) as usize));
    }

    /// Seen through open ground, not behind a wall; a wall's face is seen; the cap leaves the rest
    /// for a later pass and drops nothing.
    #[test]
    fn what_a_pass_sees() {
        let mut m = open(64, 64);
        wall(&mut m, 40, 0, 63);
        let eye = (30.0, 30.0);
        let offs = ring(24.0);
        let all = newly_seen(&m, eye, &offs, 24.0, 0, |_, _| false, |p, d| d <= 24.0 && m.sight_clear(eye, p));
        let has = |x: i32, y: i32| {
            let (c, b) = cell_of(x, y);
            all.contains(&(c, b))
        };
        assert!(has(30, 30) && has(37, 30), "open ground in view");
        assert!(has(40, 30), "the wall's face");
        assert!(!has(46, 30), "behind the wall");
        assert!(!has(30, 2), "beyond the distance");
        // Capped: nearest first, and the next pass takes the rest.
        let first = newly_seen(&m, eye, &offs, 24.0, 10, |_, _| false, |p, d| d <= 24.0 && m.sight_clear(eye, p));
        assert_eq!(first.len(), 10);
        assert!(first.iter().all(|c| all.contains(c)));
        let second = newly_seen(&m, eye, &offs, 24.0, 0, |c, b| first.contains(&(c, b)), |p, d| d <= 24.0 && m.sight_clear(eye, p));
        assert_eq!(first.len() + second.len(), all.len());
    }

    /// The plan never reads unseen ground: an unknown wall is planned through (and found by
    /// looking), a seen one is gone round; a wall built after the ground was seen is believed
    /// absent; a gate seen shut blocks, one believed open does not.
    #[test]
    fn a_plan_reads_only_belief() {
        let mut m = open(128, 64);
        wall(&mut m, 40, 0, 50);
        let from = (20.5, 30.5);
        let to = (60.5, 30.5);
        let s = Shape::default();
        // Nothing seen: straight through where the (unseen) wall is.
        let b = belief(&m, &[], &[], HashMap::new());
        let p = leg(&b, from, to, &s).unwrap();
        let y = crosses(&p, from, 40.5).unwrap();
        assert!((y - 30.5).abs() < 1.0, "straight: crosses at {y}");
        // All seen: round the wall's end (y > 50).
        let seen = all_chunks(&m);
        let b = belief(&m, &seen, &[], HashMap::new());
        let p = leg(&b, from, to, &s).unwrap();
        let y = crosses(&p, from, 40.5).unwrap();
        assert!(y > 50.0, "round the wall: crosses at {y}: {p:?}");
        // The wall built after it was seen (edit count 1 > seen at 0): believed absent.
        let edits: Vec<(u32, Edit)> = (0..=50).map(|yy| {
            let (c, _) = cell_of(40, yy);
            (c, Edit { epoch: 1, tile: ((yy as u32 % CHUNK) * CHUNK + 40 % CHUNK) as u16, before: Terrain::Grass as u8 })
        }).collect();
        let b = belief(&m, &seen, &edits, HashMap::new());
        let p = leg(&b, from, to, &s).unwrap();
        let y = crosses(&p, from, 40.5).unwrap();
        assert!((y - 30.5).abs() < 1.0, "the new wall is not known: crosses at {y}");
        // A gate in a gap: seen shut blocks, believed open passes.
        let mut m2 = open(128, 64);
        wall(&mut m2, 40, 0, 63);
        m2.set(40, 30, Terrain::Grass);
        let seen2 = all_chunks(&m2);
        let gate = 30 * 128 + 40;
        let shut = belief(&m2, &seen2, &[], HashMap::from([(gate, false)]));
        assert_eq!(leg(&shut, from, to, &s), Err(NoLeg::NoWay));
        let open_gate = belief(&m2, &seen2, &[], HashMap::from([(gate, true)]));
        assert!(leg(&open_gate, from, to, &s).is_ok());
    }

    /// A long walk goes a leg at a time: the first ends about `leg_m` along, and from there the
    /// next reaches the goal.
    #[test]
    fn legs_follow_a_coarse_route() {
        let m = open(512, 64);
        let b = belief(&m, &[], &[], HashMap::new());
        let s = Shape::default();
        let from = (10.5, 30.5);
        let to = (300.5, 30.5);
        let p1 = leg(&b, from, to, &s).unwrap();
        let end = *p1.last().unwrap();
        assert!(end.0 > 50.0 && end.0 < 120.0, "{end:?}");
        let mut at = end;
        for _ in 0..10 {
            let p = leg(&b, at, to, &s).unwrap();
            at = *p.last().unwrap();
            if at == to {
                break;
            }
        }
        assert_eq!(at, to);
    }
}
