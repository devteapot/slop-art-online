//! Known ground (docs/MOVEMENT_MIND.md, step 3): what a character has seen of the map, kept as a
//! mask over the shared map, and the walking plan over it.
//!
//! - **The mask.** The map is cut into 4 m cells, sixteen to a 16 m chunk; a character marks a
//!   cell when it sees it (the one sight rule, out to the world's `ground_sight_m`). A row per
//!   128 m block (8 × 8 chunks) holds its chunks' masks and, per chunk, the map's edit count when
//!   the chunk was last seen.
//! - **The belief.** A seen tile is what it was when seen: the map now, with the edits made since
//!   undone. A gate is as last seen. Everything else is unknown.
//! - **The plan.** A coarse route over connected chunk regions on the belief (unknown ground passable at a cost),
//!   then a tile search over the next `leg_m` of it through those chunks and the ones beside them.
//!   Unseen ground is never read.

use crate::map::{chunk_id, chunk_xy, Map, Terrain, TileHasher, CHUNK};
use std::cell::RefCell;
use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap, HashSet};
use std::hash::BuildHasherDefault;

type TileMap<K, V> = HashMap<K, V, BuildHasherDefault<TileHasher>>;

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
        Self {
            cells: [0; SLOTS],
            seen_at: [0; SLOTS],
        }
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
pub fn newly_seen(
    map: &Map,
    eye: (f32, f32),
    offsets: &[(i32, i32)],
    radius: f32,
    cap: usize,
    mut known: impl FnMut(u32, u16) -> bool,
    mut sees: impl FnMut((f32, f32), f32) -> bool,
) -> Vec<(u32, u16)> {
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
        let near = if d > half + 0.5 {
            (
                centre.0 + (eye.0 - centre.0) * (half + 0.25) / d,
                centre.1 + (eye.1 - centre.1) * (half + 0.25) / d,
            )
        } else {
            centre
        };
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
    blocks: RefCell<TileMap<u32, Option<Known>>>,
    edits: RefCell<TileMap<u32, Vec<Edit>>>,
    /// Gates as last seen, by tile index (`y * w + x`): open or shut.
    gates: HashMap<u32, bool>,
}

impl<'a> Belief<'a> {
    pub fn new(
        map: &'a Map,
        load_block: impl FnMut(u32) -> Option<Known> + 'a,
        load_edits: impl FnMut(u32) -> Vec<Edit> + 'a,
        gates: HashMap<u32, bool>,
    ) -> Self {
        Self {
            map,
            load_block: RefCell::new(Box::new(load_block)),
            load_edits: RefCell::new(Box::new(load_edits)),
            blocks: RefCell::default(),
            edits: RefCell::default(),
            gates,
        }
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
        self.tile_at(
            x,
            y,
            seen_at,
            &self.edits.borrow_mut().entry(chunk).or_insert_with(|| (self.load_edits.borrow_mut())(chunk)),
        )
    }

    fn tile_at(&self, x: i32, y: i32, seen_at: u32, edits: &[Edit]) -> Ground {
        let key = y as u32 * self.map.w + x as u32;
        let mut byte = self.map.tiles[key as usize];
        let tile = offset((x, y)) as u16;
        // The first edit to this tile after it was seen holds the remembered byte.
        if let Some(e) = edits.iter().filter(|e| e.tile == tile && e.epoch > seen_at).min_by_key(|e| e.epoch) {
            byte = e.before;
        }
        let t = Terrain::from_u8(byte);
        if !t.walkable() || self.gates.get(&key) == Some(&false) {
            Ground::Blocked
        } else if t == Terrain::Road {
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
        let mut previous = tile(a);
        for k in 0..=n {
            let t = k as f32 / n as f32;
            let p = tile((a.0 + (b.0 - a.0) * t, a.1 + (b.1 - a.1) * t));
            if self.ground(p.0, p.1) == Ground::Blocked
                || (p.0 != previous.0
                    && p.1 != previous.1
                    && (self.ground(p.0, previous.1) == Ground::Blocked || self.ground(previous.0, p.1) == Ground::Blocked))
            {
                return false;
            }
            previous = p;
        }
        true
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
    /// Queue pops per slice for the offline driver.
    pub max_nodes: usize,
}

impl Default for Shape {
    fn default() -> Self {
        Self {
            unknown_cost: 1.5,
            road_speed: 1.4,
            leg_m: 64.0,
            max_nodes: 40_000,
        }
    }
}

/// Why no leg could be planned.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NoLeg {
    NoWay,
    GoalBlocked,
    StartBlocked,
    CorridorDisconnected,
    WorkLimit,
}

type Tile = (i32, i32);
type Region = (Tile, u8);
const SIDE: i32 = CHUNK as i32;
const SIZE: usize = (CHUNK * CHUNK) as usize;
const BLOCKED: u8 = u8::MAX;
/// Heap-pop budget for one authority steering update.
pub const STEERING_POPS: usize = 512;
const SIDES: [Tile; 4] = [(1, 0), (-1, 0), (0, 1), (0, -1)];
const DIAGONALS: [Tile; 4] = [(1, 1), (1, -1), (-1, 1), (-1, -1)];

fn tile(p: (f32, f32)) -> Tile {
    (p.0.floor() as i32, p.1.floor() as i32)
}
fn point(p: Tile) -> (f32, f32) {
    (p.0 as f32 + 0.5, p.1 as f32 + 0.5)
}
fn chunk(p: Tile) -> Tile {
    (p.0.div_euclid(SIDE), p.1.div_euclid(SIDE))
}
fn offset(p: Tile) -> usize {
    (p.1.rem_euclid(SIDE) * SIDE + p.0.rem_euclid(SIDE)) as usize
}
fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}

struct Chunk {
    // Unknown interior chunks are uniform. Store tile arrays only for mixed chunks.
    tiles: Option<Box<ChunkTiles>>,
    regions: Vec<(Tile, u32)>,
}

struct ChunkTiles {
    label: [u8; SIZE],
    cost: [u32; SIZE],
}

impl Chunk {
    fn label(&self, i: usize) -> u8 {
        self.tiles.as_ref().map_or(0, |tiles| tiles.label[i])
    }

    fn cost(&self, i: usize) -> u32 {
        match &self.tiles {
            Some(tiles) => tiles.cost[i],
            None => self.regions[0].1,
        }
    }

    fn new(c: Tile, b: &Belief, s: &Shape) -> Self {
        let at = |i: usize| (c.0 * SIDE + i as i32 % SIDE, c.1 * SIDE + i as i32 / SIDE);
        let unknown = (s.unknown_cost * 100.0).max(1.0) as u32;
        let in_bounds = |x, y| x >= 0 && y >= 0 && (x as u32) < b.map.w && (y as u32) < b.map.h;
        let key = chunk_id(c.0 as u32, c.1 as u32);
        let (mask, seen_at) = if c.0 >= 0 && c.1 >= 0 { b.chunk_mask(key) } else { (0, 0) };
        if mask == 0 && in_bounds(at(0).0, at(0).1) && in_bounds(at(SIZE - 1).0, at(SIZE - 1).1) {
            return Self {
                tiles: None,
                regions: vec![(at(SIZE / 2 + SIDE as usize / 2), unknown)],
            };
        }
        let mut edits = b.edits.borrow_mut();
        let edits = if mask != 0 {
            edits.entry(key).or_insert_with(|| (b.load_edits.borrow_mut())(key)).as_slice()
        } else {
            &[]
        };
        let cost = std::array::from_fn(|i| {
            let (x, y) = at(i);
            if !in_bounds(x, y) {
                return 0;
            }
            let bit = 1 << (i as u32 / CHUNK / CELL * CELLS + i as u32 % CHUNK / CELL);
            if mask & bit == 0 {
                return unknown;
            }
            match b.tile_at(x, y, seen_at, edits) {
                Ground::Blocked => 0,
                Ground::Road => (100.0 / s.road_speed).max(1.0) as u32,
                Ground::Open => 100,
                Ground::Unknown => unknown,
            }
        });
        let mut labels = [BLOCKED; SIZE];
        let mut regions = Vec::new();
        let mut queue = Vec::with_capacity(SIZE);
        let rank = |i: usize| (i as i32 % SIDE - SIDE / 2).pow(2) + (i as i32 / SIDE - SIDE / 2).pow(2);
        for i in 0..SIZE {
            if cost[i] == 0 || labels[i] != BLOCKED {
                continue;
            }
            let label = regions.len() as u8;
            queue.clear();
            queue.push(i);
            labels[i] = label;
            let (mut j, mut total, mut rep) = (0, 0u64, i);
            while j < queue.len() {
                let k = queue[j];
                j += 1;
                total += u64::from(cost[k]);
                if rank(k) < rank(rep) {
                    rep = k;
                }
                for (dx, dy) in SIDES {
                    let p = (k as i32 % SIDE + dx, k as i32 / SIDE + dy);
                    if !(0..SIDE).contains(&p.0) || !(0..SIDE).contains(&p.1) {
                        continue;
                    }
                    let n = offset(p);
                    if cost[n] != 0 && labels[n] == BLOCKED {
                        labels[n] = label;
                        queue.push(n);
                    }
                }
            }
            regions.push((at(rep), (total / j as u64) as u32));
        }
        Self {
            tiles: Some(Box::new(ChunkTiles { label: labels, cost })),
            regions,
        }
    }
}

struct Frontier<N> {
    open: BinaryHeap<Reverse<(u32, Reverse<u32>, N)>>,
    reached: TileMap<N, (u32, N)>,
    start: N,
}

impl<N: Copy + Eq + Ord + std::hash::Hash> Frontier<N> {
    fn new(start: N) -> Self {
        let mut reached = TileMap::default();
        reached.insert(start, (0, start));
        Self {
            open: BinaryHeap::from([Reverse((0, Reverse(0), start))]),
            reached,
            start,
        }
    }

    fn pop(&mut self, budget: &mut usize) -> Option<Option<(u32, N)>> {
        *budget -= 1; // Charge stale entries too.
        let Reverse((_, Reverse(g), n)) = self.open.pop()?;
        Some((g == self.reached[&n].0).then_some((g, n)))
    }

    fn push(&mut self, from: N, to: N, g: u32, h: u32) {
        if self.reached.get(&to).is_none_or(|e| g < e.0) {
            self.reached.insert(to, (g, from));
            self.open.push(Reverse((g.saturating_add(h), Reverse(g), to)));
        }
    }

    fn route(&self, mut n: N) -> Vec<N> {
        let mut path = vec![n];
        while n != self.start {
            n = self.reached[&n].1;
            path.push(n);
        }
        path.reverse();
        path
    }
}

struct Corridor {
    allowed: HashSet<Tile, BuildHasherDefault<TileHasher>>,
    target: (f32, f32),
    frontier: Frontier<Tile>,
}

/// A search over one observation revision, suspended between steering updates.
pub struct Search {
    from: (f32, f32),
    to: (f32, f32),
    shape: Shape,
    chunks: TileMap<Tile, Chunk>,
    coarse: Frontier<Region>,
    goal: Region,
    corridor: Option<Corridor>,
    pops: usize,
}

impl Search {
    pub fn new(b: &Belief, from: (f32, f32), to: (f32, f32), shape: Shape) -> Result<Self, NoLeg> {
        let mut chunks = TileMap::default();
        let mut region = |p: Tile, reason| {
            let c = chunk(p);
            let label = chunks.entry(c).or_insert_with(|| Chunk::new(c, b, &shape)).label(offset(p));
            if label == BLOCKED {
                Err(reason)
            } else {
                Ok((c, label))
            }
        };
        let goal = region(tile(to), NoLeg::GoalBlocked)?;
        let start = region(tile(from), NoLeg::StartBlocked)?;
        Ok(Self {
            from,
            to,
            shape,
            chunks,
            coarse: Frontier::new(start),
            goal,
            corridor: None,
            pops: 0,
        })
    }

    /// At most `budget` heap pops across both stages. None means this search can resume.
    pub fn advance(&mut self, b: &Belief, mut budget: usize) -> Option<Result<Vec<(f32, f32)>, NoLeg>> {
        const MAX_POPS: usize = 40_000;
        const REGION_POPS_PER_SLICE: usize = 32;
        if self.pops == MAX_POPS {
            return Some(Err(NoLeg::WorkLimit));
        }
        budget = budget.min(MAX_POPS - self.pops);
        let mut region_pops = 0;
        while self.corridor.is_none() && budget > 0 {
            if region_pops == REGION_POPS_PER_SLICE {
                return None;
            }
            region_pops += 1;
            self.pops += 1;
            let Some(entry) = self.coarse.pop(&mut budget) else {
                return Some(Err(NoLeg::NoWay));
            };
            let Some((g, node @ (c, label))) = entry else { continue };
            let (rep, cost) = self.chunks[&c].regions[label as usize];
            if node == self.goal {
                let route = self.coarse.route(node);
                let rep = |(c, label): Region| point(self.chunks[&c].regions[label as usize].0);
                let mut walked = 0.0;
                let mut previous = self.from;
                let end = route
                    .iter()
                    .enumerate()
                    .skip(1)
                    .find(|(_, n)| {
                        let at = rep(**n);
                        walked += dist(previous, at);
                        previous = at;
                        walked >= self.shape.leg_m
                    })
                    .map_or(route.len() - 1, |(i, _)| i);
                let allowed = route[..=end]
                    .iter()
                    .flat_map(|&((x, y), _)| (-1..=1).flat_map(move |dy| (-1..=1).map(move |dx| (x + dx, y + dy))))
                    .collect();
                let target = if end + 1 == route.len() { self.to } else { rep(route[end]) };
                self.corridor = Some(Corridor {
                    allowed,
                    target,
                    frontier: Frontier::new(tile(self.from)),
                });
                break;
            }
            for (dx, dy) in SIDES {
                let n = (c.0 + dx, c.1 + dy);
                if n.0 < 0 || n.1 < 0 || n.0 as u32 >= b.map.w.div_ceil(CHUNK) || n.1 as u32 >= b.map.h.div_ceil(CHUNK) {
                    continue;
                }
                let mut linked = [false; SIZE];
                for k in 0..SIDE {
                    let (a, z) = match (dx, dy) {
                        (1, 0) => ((SIDE - 1, k), (0, k)),
                        (-1, 0) => ((0, k), (SIDE - 1, k)),
                        (0, 1) => ((k, SIDE - 1), (k, 0)),
                        _ => ((k, 0), (k, SIDE - 1)),
                    };
                    if self.chunks[&c].label(offset(a)) != label {
                        continue;
                    }
                    let other = self.chunks.entry(n).or_insert_with(|| Chunk::new(n, b, &self.shape));
                    let r = other.label(offset(z));
                    if r == BLOCKED || std::mem::replace(&mut linked[r as usize], true) {
                        continue;
                    }
                    let (at, rate) = other.regions[r as usize];
                    let edge = (dist(point(rep), point(at)) * (cost as f32 + rate as f32) * 0.5) as u32;
                    let h = (dist(point(at), self.to) * 100.0 * self.shape.unknown_cost.max(1.0)) as u32;
                    self.coarse.push(node, (n, r), g.saturating_add(edge.max(1)), h);
                }
            }
        }
        while budget > 0 {
            self.pops += 1;
            let corridor = self.corridor.as_mut().unwrap();
            let goal = tile(corridor.target);
            let Some(entry) = corridor.frontier.pop(&mut budget) else {
                return Some(Err(NoLeg::CorridorDisconnected));
            };
            let Some((g, p)) = entry else { continue };
            if p == goal {
                let cells = corridor.frontier.route(goal);
                let mut result = Vec::new();
                let mut at = self.from;
                let mut i = 1;
                while i < cells.len() {
                    let mut j = (i + 2 * CHUNK as usize).min(cells.len() - 1);
                    while j > i && !b.line_open(at, point(cells[j])) {
                        j -= 1;
                    }
                    at = point(cells[j]);
                    result.push(at);
                    i = j + 1;
                }
                let before_end = result.iter().rev().nth(1).copied().unwrap_or(self.from);
                if !result.is_empty() && b.line_open(before_end, corridor.target) {
                    result.pop();
                }
                result.push(corridor.target);
                return Some(Ok(result));
            }
            let mut cost_at = |p: Tile| {
                let c = chunk(p);
                if !corridor.allowed.contains(&c) {
                    return 0;
                }
                self.chunks.entry(c).or_insert_with(|| Chunk::new(c, b, &self.shape)).cost(offset(p))
            };
            for (dx, dy) in SIDES.into_iter().chain(DIAGONALS) {
                let n = (p.0 + dx, p.1 + dy);
                let cost = cost_at(n);
                if cost == 0 {
                    continue;
                }
                let step = if dx != 0 && dy != 0 {
                    if cost_at((n.0, p.1)) == 0 || cost_at((p.0, n.1)) == 0 {
                        continue;
                    }
                    (cost as f32 * std::f32::consts::SQRT_2) as u32
                } else {
                    cost
                };
                let (dx, dy) = (n.0.abs_diff(goal.0), n.1.abs_diff(goal.1));
                // Match the costs of unknown ground in open space, including diagonals.
                let h = ((dx.max(dy) as f32 + 0.414_213_57 * dx.min(dy) as f32) * 100.0 * self.shape.unknown_cost.max(1.0)) as u32;
                corridor.frontier.push(p, n, g.saturating_add(step), h);
            }
        }
        None
    }
}

/// Drive the same planner synchronously for offline use.
pub fn leg(b: &Belief, from: (f32, f32), to: (f32, f32), s: &Shape) -> Result<Vec<(f32, f32)>, NoLeg> {
    let mut search = Search::new(b, from, to, *s)?;
    loop {
        if let Some(result) = search.advance(b, s.max_nodes.max(1)) {
            return result;
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;

    fn open(w: u32, h: u32) -> Map {
        Map {
            w,
            h,
            tiles: vec![Terrain::Grass as u8; (w * h) as usize],
            blocked: Default::default(),
            opaque: Default::default(),
            nav: Default::default(),
        }
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
        let second = newly_seen(
            &m,
            eye,
            &offs,
            24.0,
            0,
            |c, b| first.contains(&(c, b)),
            |p, d| d <= 24.0 && m.sight_clear(eye, p),
        );
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
        let edits: Vec<(u32, Edit)> = (0..=50)
            .map(|yy| {
                let (c, _) = cell_of(40, yy);
                (
                    c,
                    Edit {
                        epoch: 1,
                        tile: ((yy as u32 % CHUNK) * CHUNK + 40 % CHUNK) as u16,
                        before: Terrain::Grass as u8,
                    },
                )
            })
            .collect();
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

    #[test]
    fn closed_gate_routes_to_the_alternative() {
        let mut m = open(128, 96);
        wall(&mut m, 40, 0, 95);
        m.set(40, 30, Terrain::Grass);
        m.set(40, 83, Terrain::Grass);
        let seen = all_chunks(&m);
        let b = belief(&m, &seen, &[], HashMap::from([(30 * m.w + 40, false), (83 * m.w + 40, true)]));
        let from = (38.5, 30.5);
        let to = (46.5, 30.5);
        let mut at = from;
        let mut crossing = None;
        for _ in 0..10 {
            let path = leg(&b, at, to, &Shape::default()).unwrap();
            crossing = crossing.or_else(|| crosses(&path, at, 40.5));
            at = *path.last().unwrap();
            if at == to {
                break;
            }
        }
        assert_eq!(at, to);
        assert!((83.0..84.0).contains(&crossing.unwrap()));
    }

    #[test]
    fn hidden_gate_state_does_not_change_the_plan() {
        let mut shut = open(96, 64);
        wall(&mut shut, 40, 0, 63);
        shut.set(40, 30, Terrain::Grass);
        let open = shut.clone();
        let gate = 30 * shut.w + 40;
        shut.set_blocked([gate].into_iter().collect());
        assert!(!shut.free(40.5, 30.5) && open.free(40.5, 30.5));
        let seen = all_chunks(&open);
        let plan = |m| {
            let b = belief(m, &seen, &[], HashMap::from([(gate, true)]));
            leg(&b, (20.5, 30.5), (60.5, 30.5), &Shape::default()).unwrap()
        };
        assert_eq!(plan(&shut), plan(&open));
    }

    #[test]
    fn both_frontiers_resume_with_a_single_pop_per_update() {
        let m = open(128, 64);
        let b = belief(&m, &[], &[], HashMap::new());
        let from = (12.5, 30.5);
        let to = (104.5, 17.5);
        let s = Shape::default();
        let expected = leg(&b, from, to, &s);
        assert!(expected.is_ok());
        let mut search = Search::new(&b, from, to, s).unwrap();
        assert!(search.advance(&b, 1).is_none());
        assert!(search.corridor.is_none());
        for _ in 0..100_000 {
            if let Some(result) = search.advance(&b, 1) {
                assert!(search.corridor.is_some());
                assert_eq!(result, expected);
                return;
            }
        }
        panic!("one-pop updates did not finish the search");
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
