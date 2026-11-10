//! Long walking routes in three levels, so no single search covers a whole journey.
//!
//! - **Regions.** Each 16-tile chunk splits into regions: its 4-connected pockets of
//!   walkable tiles (shut gates count as blocked). A diagonal step in the tile search needs
//!   both orthogonal neighbours open, so 4-connectivity is exactly the tile search's
//!   connectivity. Two regions in side-by-side chunks are linked when a tile of one touches a
//!   tile of the other across the shared edge.
//! - **Areas.** Each block of 8 × 8 chunks (128 m) splits into areas: groups of its regions
//!   joined by links inside the block. Two areas in different blocks are linked when one of
//!   their regions is.
//! - **A leg.** Every search runs on the current map, so a route follows the terrain as it is:
//!   1. over areas, from the start's to the goal's;
//!   2. over regions, to the end of the area route's first `area_m`, through the blocks of that
//!      stretch and their neighbours;
//!   3. over tiles, to the end of the region route's first `leg_m`, through the chunks of that
//!      stretch and their neighbours.
//!
//!   Each stretch's blocks or chunks contain a connected chain from its start to its end, so
//!   the lower search cannot fail, and its cost is bounded by the stretch, not the journey. A
//!   walker plans its next leg as it nears the end of the current one.
//!
//! A link costs the straight distance between the two ends' representative tiles, divided by
//! the road speed in proportion to the road on them, so routes prefer roads where they save
//! time. Searches are guided by the straight distance at walking speed, which ignores roads'
//! speed-up: a route can be slightly slower than the fastest, in exchange for fewer nodes
//! searched.
//!
//! Regions and areas are worked out when a route first needs them (or ahead of time by
//! [`Map::warm_routes`]) and dropped when a tile or gate in them changes. Everything is
//! deterministic: integer costs, ties broken by cost so far and then by node.

use crate::map::{Map, Reached, Terrain, TileHasher, CHUNK};
use std::cmp::Ordering;
use std::collections::BinaryHeap;
use std::sync::atomic::{AtomicU32, Ordering as AtomicOrdering};
use std::sync::OnceLock;

/// No region: the tile is not walkable.
const NONE: u8 = u8::MAX;
const TILES: usize = (CHUNK * CHUNK) as usize;
/// Chunks per block side.
const BLOCK: u32 = 8;
/// Most areas a block keeps (regions beyond are left out of routes, as are a chunk's regions
/// beyond 254; neither happens on generated land).
const MAX_AREAS: usize = u16::MAX as usize;

/// One chunk's regions.
#[derive(Clone, Debug)]
struct ChunkNav {
    /// Region of each tile (row-major within the chunk), `NONE` where not walkable.
    label: [u8; TILES],
    /// Per region: the representative tile's centre.
    rep: Vec<(f32, f32)>,
    /// Per region: share of road tiles, 0–255.
    road: Vec<u8>,
}

/// One block's areas.
#[derive(Clone, Debug)]
struct BlockNav {
    /// Area of each region, per chunk of the block (`(cy % BLOCK) * BLOCK + cx % BLOCK`).
    area: Vec<Vec<u16>>,
    /// Per area: its regions (keys), representative (its region nearest the regions' mean
    /// representative) and mean road share 0–1.
    members: Vec<Vec<u32>>,
    rep: Vec<(f32, f32)>,
    rep_region: Vec<u32>,
    road: Vec<f32>,
}

/// A link to a node of the same level.
#[derive(Clone, Copy, Debug)]
struct Link {
    to: u32,
    /// The other node's representative tile.
    at: (f32, f32),
    /// Metres between the two representatives.
    d: f32,
    /// Mean road share of the two, 0–1.
    road: f32,
}

/// A chunk's regions and, built separately because they read the neighbours' regions, their
/// links.
#[derive(Clone, Debug, Default)]
struct Slot {
    regions: OnceLock<Box<ChunkNav>>,
    links: OnceLock<Box<[Vec<Link>]>>,
}

/// A block's areas and their links.
#[derive(Clone, Debug, Default)]
struct BlockSlot {
    areas: OnceLock<Box<BlockNav>>,
    links: OnceLock<Box<[Vec<Link>]>>,
}

/// The lazily built regions and areas of a map.
#[derive(Debug, Default)]
pub struct Nav {
    chunks: OnceLock<Vec<Slot>>,
    blocks: OnceLock<Vec<BlockSlot>>,
    /// How far [`Map::warm_routes`] has got: chunks, then blocks.
    warmed: AtomicU32,
    /// Each area's connected component (per block, per area), labelled by
    /// [`Map::warm_routes`] once every block's areas are built; dropped on any change.
    components: OnceLock<Box<[Box<[u32]>]>>,
}

impl Clone for Nav {
    fn clone(&self) -> Self {
        Self { chunks: self.chunks.clone(), blocks: self.blocks.clone(), warmed: AtomicU32::new(self.warmed.load(AtomicOrdering::Relaxed)), components: self.components.clone() }
    }
}

impl Nav {
    /// Drop chunk `(cx, cy)`'s regions and its block's areas (a tile or gate in it changed),
    /// and the neighbours' links into them.
    pub(crate) fn forget(&mut self, w: u32, cx: u32, cy: u32) {
        // A change can join or split ground anywhere: label the components again.
        self.components = OnceLock::new();
        let cw = w.div_ceil(CHUNK);
        let near = |x: u32, y: u32, wide: u32| {
            let (x, y, wide) = (x as i64, y as i64, wide as i64);
            [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)].map(|(dx, dy)| {
                let (a, b) = (x + dx, y + dy);
                (a >= 0 && b >= 0 && a < wide).then(|| (b * wide + a) as usize)
            })
        };
        if let Some(v) = self.chunks.get_mut() {
            for (k, i) in near(cx, cy, cw).into_iter().enumerate() {
                if let Some(slot) = i.and_then(|i| v.get_mut(i)) {
                    if k == 0 {
                        *slot = Slot::default();
                    } else {
                        slot.links = OnceLock::new();
                    }
                }
            }
        }
        if let Some(v) = self.blocks.get_mut() {
            for (k, i) in near(cx / BLOCK, cy / BLOCK, cw.div_ceil(BLOCK)).into_iter().enumerate() {
                if let Some(slot) = i.and_then(|i| v.get_mut(i)) {
                    if k == 0 {
                        *slot = BlockSlot::default();
                    } else {
                        slot.links = OnceLock::new();
                    }
                }
            }
        }
    }
}

/// A region key: chunk index (`cy * chunks_wide + cx`) and region.
fn region_key(chunk: u32, r: u8) -> u32 {
    (chunk << 8) | r as u32
}

/// An area key: block index (`by * blocks_wide + bx`) and area.
fn area_key(block: u32, a: u16) -> u32 {
    (block << 16) | a as u32
}

/// The next stretch of a route.
#[derive(Clone, Debug, PartialEq)]
pub struct Leg {
    /// Waypoints from the start (excluded), smoothed by line of sight.
    pub points: Vec<(f32, f32)>,
    /// The leg ends at the goal (otherwise at a point on the way, to be continued).
    pub last: bool,
    /// Nodes expanded by each search: areas, regions, tiles (cost evidence).
    pub areas: usize,
    pub regions: usize,
    pub tiles: usize,
}

/// How a route is searched (from the world's laws).
#[derive(Clone, Copy, Debug)]
pub struct RouteSpec {
    /// Walking speed multiplier on roads (`road_speed`).
    pub road_speed: f32,
    /// Plan the tile path this far ahead along the region route, metres.
    pub leg_m: f32,
    /// Plan the region route this far ahead along the area route, metres.
    pub area_m: f32,
    /// Most nodes any one of the searches may expand.
    pub max_nodes: usize,
}

impl Default for RouteSpec {
    fn default() -> Self {
        Self { road_speed: 1.4, leg_m: 64.0, area_m: 384.0, max_nodes: 40_000 }
    }
}

/// A* over linked nodes from `start` to `goal`, through nodes `allow` admits. Returns the
/// nodes from start to goal and the number expanded.
fn astar<'a>(start: (u32, (f32, f32)), goal: u32, to: (f32, f32), road_speed: f32, max: usize, links: impl Fn(u32) -> &'a [Link], allow: impl Fn(u32) -> bool) -> Option<(Vec<u32>, usize)> {
    if start.0 == goal {
        return Some((vec![goal], 0));
    }
    let rs = road_speed.max(1.0);
    // Straight distance in tenths of a metre (see the module notes).
    let h = |p: (f32, f32)| (((p.0 - to.0).powi(2) + (p.1 - to.1).powi(2)).sqrt() * 10.0) as u32;
    #[derive(PartialEq, Eq)]
    struct Open(u32, u32, u32);
    impl Ord for Open {
        fn cmp(&self, o: &Self) -> Ordering {
            o.0.cmp(&self.0).then(self.1.cmp(&o.1)).then(o.2.cmp(&self.2))
        }
    }
    impl PartialOrd for Open {
        fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
            Some(self.cmp(o))
        }
    }
    let mut seen: Reached = Reached::with_capacity_and_hasher(256, std::hash::BuildHasherDefault::<TileHasher>::default());
    let mut open = BinaryHeap::new();
    seen.insert(start.0, (0, u32::MAX));
    open.push(Open(h(start.1), 0, start.0));
    let mut expanded = 0;
    while let Some(Open(_, g, k)) = open.pop() {
        if k == goal {
            let mut route = vec![goal];
            let mut cur = k;
            while let Some(&(_, prev)) = seen.get(&cur) {
                if prev == u32::MAX {
                    break;
                }
                route.push(prev);
                cur = prev;
            }
            route.reverse();
            return Some((route, expanded));
        }
        if seen.get(&k).is_some_and(|e| g > e.0) {
            continue;
        }
        expanded += 1;
        if expanded > max {
            return None;
        }
        for l in links(k) {
            if !allow(l.to) {
                continue;
            }
            // Tenths of a metre at walking speed.
            let ng = g + ((l.d * 10.0 / (1.0 + (rs - 1.0) * l.road)).round() as u32).max(1);
            if seen.get(&l.to).map_or(true, |e| ng < e.0) {
                seen.insert(l.to, (ng, k));
                open.push(Open(ng + h(l.at), ng, l.to));
            }
        }
    }
    None
}

/// The index of the first of `route`'s nodes at least `m` metres from `from` (the last when
/// none is).
fn stretch(route: &[u32], from: (f32, f32), m: f32, rep: impl Fn(u32) -> (f32, f32)) -> usize {
    route
        .iter()
        .position(|&n| {
            let p = rep(n);
            (p.0 - from.0).powi(2) + (p.1 - from.1).powi(2) >= m * m
        })
        .unwrap_or(route.len() - 1)
}

/// The cells of a `wide` × `high` grid on or next to any of `cells`, sorted.
fn widen(cells: impl Iterator<Item = u32>, wide: u32, high: u32) -> Vec<u32> {
    let mut out = Vec::new();
    for c in cells {
        let (cx, cy) = ((c % wide) as i64, (c / wide) as i64);
        for dy in -1..=1 {
            for dx in -1..=1 {
                let (x, y) = (cx + dx, cy + dy);
                if x >= 0 && y >= 0 && x < wide as i64 && y < high as i64 {
                    out.push((y * wide as i64 + x) as u32);
                }
            }
        }
    }
    out.sort_unstable();
    out.dedup();
    out
}

fn area_component(c: &[Box<[u32]>], area: u32) -> u32 {
    c[(area >> 16) as usize][(area & 0xFFFF) as usize]
}

fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}

impl Map {
    fn chunks_wide(&self) -> u32 {
        self.w.div_ceil(CHUNK)
    }

    fn chunks_high(&self) -> u32 {
        self.h.div_ceil(CHUNK)
    }

    fn blocks_wide(&self) -> u32 {
        self.chunks_wide().div_ceil(BLOCK)
    }

    fn slot(&self, c: u32) -> &Slot {
        let n = self.chunks_wide() * self.chunks_high();
        &self.nav.chunks.get_or_init(|| (0..n).map(|_| Slot::default()).collect())[c as usize]
    }

    fn block_slot(&self, b: u32) -> &BlockSlot {
        let n = self.blocks_wide() * self.chunks_high().div_ceil(BLOCK);
        &self.nav.blocks.get_or_init(|| (0..n).map(|_| BlockSlot::default()).collect())[b as usize]
    }

    fn chunk_nav(&self, c: u32) -> &ChunkNav {
        let cw = self.chunks_wide();
        self.slot(c).regions.get_or_init(|| Box::new(self.label_chunk(c % cw, c / cw)))
    }

    /// Region `key`'s representative tile.
    fn region_rep(&self, key: u32) -> (f32, f32) {
        self.chunk_nav(key >> 8).rep[(key & 0xFF) as usize]
    }

    /// Each of chunk `c`'s regions' links to regions of the four side-by-side chunks.
    fn region_links(&self, c: u32) -> &[Vec<Link>] {
        self.slot(c).links.get_or_init(|| {
            let me = self.chunk_nav(c);
            let (cw, ch) = (self.chunks_wide(), self.chunks_high());
            let (cx, cy) = (c % cw, c / cw);
            let last = CHUNK - 1;
            let mut out: Vec<Vec<Link>> = vec![Vec::new(); me.rep.len()];
            // (exists, dx, dy, (own border tile, neighbour's tile) for k along the edge)
            let sides: [(bool, i64, i64, fn(u32, u32) -> (u32, u32)); 4] = [
                (cx + 1 < cw, 1, 0, |k, l| (k * CHUNK + l, k * CHUNK)),
                (cx > 0, -1, 0, |k, l| (k * CHUNK, k * CHUNK + l)),
                (cy + 1 < ch, 0, 1, |k, l| (l * CHUNK + k, k)),
                (cy > 0, 0, -1, |k, l| (k, l * CHUNK + k)),
            ];
            for (ok, dx, dy, idx) in sides {
                if !ok {
                    continue;
                }
                let other = ((cy as i64 + dy) * cw as i64 + cx as i64 + dx) as u32;
                let them = self.chunk_nav(other);
                for k in 0..CHUNK {
                    let (mine, theirs) = idx(k, last);
                    let (r, s) = (me.label[mine as usize], them.label[theirs as usize]);
                    if r == NONE || s == NONE || out[r as usize].iter().any(|l| l.to == region_key(other, s)) {
                        continue;
                    }
                    let (a, b) = (me.rep[r as usize], them.rep[s as usize]);
                    let road = (me.road[r as usize] as f32 + them.road[s as usize] as f32) / 510.0;
                    out[r as usize].push(Link { to: region_key(other, s), at: b, d: dist(a, b), road });
                }
            }
            out.into_boxed_slice()
        })
    }

    fn block_of(&self, chunk: u32) -> u32 {
        let cw = self.chunks_wide();
        (chunk / cw / BLOCK) * self.blocks_wide() + (chunk % cw) / BLOCK
    }

    fn block_nav(&self, b: u32) -> &BlockNav {
        self.block_slot(b).areas.get_or_init(|| Box::new(self.group_block(b)))
    }

    /// Group one block's regions into areas, following links inside the block.
    fn group_block(&self, b: u32) -> BlockNav {
        let (cw, ch, bw) = (self.chunks_wide(), self.chunks_high(), self.blocks_wide());
        let (bx, by) = (b % bw, b / bw);
        let local = |c: u32| ((c / cw) % BLOCK * BLOCK + (c % cw) % BLOCK) as usize;
        let mut area: Vec<Vec<u16>> = vec![Vec::new(); (BLOCK * BLOCK) as usize];
        let mut chunks = Vec::new();
        for ly in 0..BLOCK {
            for lx in 0..BLOCK {
                let (cx, cy) = (bx * BLOCK + lx, by * BLOCK + ly);
                if cx < cw && cy < ch {
                    let c = cy * cw + cx;
                    area[local(c)] = vec![u16::MAX; self.chunk_nav(c).rep.len()];
                    chunks.push(c);
                }
            }
        }
        let (mut members, mut rep, mut rep_region, mut road) = (Vec::new(), Vec::new(), Vec::new(), Vec::new());
        let mut stack = Vec::new();
        for &c in &chunks {
            for r in 0..area[local(c)].len() {
                if area[local(c)][r] != u16::MAX || members.len() >= MAX_AREAS {
                    continue;
                }
                let a = members.len() as u16;
                area[local(c)][r] = a;
                stack.push(region_key(c, r as u8));
                let mut m = Vec::new();
                while let Some(k) = stack.pop() {
                    m.push(k);
                    for l in &self.region_links(k >> 8)[(k & 0xFF) as usize] {
                        let (oc, or) = (l.to >> 8, (l.to & 0xFF) as usize);
                        if self.block_of(oc) == b && area[local(oc)][or] == u16::MAX {
                            area[local(oc)][or] = a;
                            stack.push(l.to);
                        }
                    }
                }
                m.sort_unstable();
                let reps: Vec<(f32, f32)> = m.iter().map(|&k| self.region_rep(k)).collect();
                let n = reps.len() as f32;
                let mean = reps.iter().fold((0.0, 0.0), |s, p| (s.0 + p.0 / n, s.1 + p.1 / n));
                let best = (0..m.len()).min_by(|&i, &j| dist(reps[i], mean).total_cmp(&dist(reps[j], mean)).then(i.cmp(&j))).expect("an area has a region");
                rep.push(reps[best]);
                rep_region.push(m[best]);
                road.push(m.iter().map(|&k| self.chunk_nav(k >> 8).road[(k & 0xFF) as usize] as f32 / 255.0).sum::<f32>() / n);
                members.push(m);
            }
        }
        BlockNav { area, members, rep, rep_region, road }
    }

    /// The area of region `key` (`None` for a region left out of its block's areas).
    fn area_of(&self, key: u32) -> Option<u32> {
        let c = key >> 8;
        let b = self.block_of(c);
        let cw = self.chunks_wide();
        let a = self.block_nav(b).area[((c / cw) % BLOCK * BLOCK + (c % cw) % BLOCK) as usize][(key & 0xFF) as usize];
        (a != u16::MAX).then(|| area_key(b, a))
    }

    fn area_rep(&self, key: u32) -> (f32, f32) {
        self.block_nav(key >> 16).rep[(key & 0xFFFF) as usize]
    }

    /// Each of block `b`'s areas' links to areas of other blocks.
    fn area_links(&self, b: u32) -> &[Vec<Link>] {
        self.block_slot(b).links.get_or_init(|| {
            let me = self.block_nav(b);
            let mut out: Vec<Vec<Link>> = vec![Vec::new(); me.members.len()];
            for (a, m) in me.members.iter().enumerate() {
                for &k in m {
                    for l in &self.region_links(k >> 8)[(k & 0xFF) as usize] {
                        let ob = self.block_of(l.to >> 8);
                        if ob == b {
                            continue;
                        }
                        let Some(to) = self.area_of(l.to) else { continue };
                        if out[a].iter().any(|x| x.to == to) {
                            continue;
                        }
                        let at = self.area_rep(to);
                        let road = (me.road[a] + self.block_nav(ob).road[(to & 0xFFFF) as usize]) / 2.0;
                        out[a].push(Link { to, at, d: dist(me.rep[a], at), road });
                    }
                }
            }
            out.into_boxed_slice()
        })
    }

    /// Flood-fill one chunk's walkable tiles into 4-connected regions. A region's
    /// representative is its tile nearest its centroid (ties: the lowest tile index).
    fn label_chunk(&self, cx: u32, cy: u32) -> ChunkNav {
        let n = CHUNK as usize;
        let (ox, oy) = (cx * CHUNK, cy * CHUNK);
        // Each tile's walkability and road, read once.
        let mut open = [false; TILES];
        let mut road_tile = [false; TILES];
        let mut count = 0;
        for ly in 0..CHUNK.min(self.h.saturating_sub(oy)) {
            for lx in 0..CHUNK.min(self.w.saturating_sub(ox)) {
                let (x, y) = (ox + lx, oy + ly);
                let t = Terrain::from_u8(self.tiles[(y * self.w + x) as usize]);
                let i = (ly * CHUNK + lx) as usize;
                open[i] = t.walkable() && (self.blocked.is_empty() || !self.blocked.contains(&(y * self.w + x)));
                road_tile[i] = t == Terrain::Road;
                count += open[i] as usize;
            }
        }
        let mut label = [NONE; TILES];
        let mut rep = Vec::new();
        let mut road = Vec::new();
        if count == 0 {
            return ChunkNav { label, rep, road };
        }
        let mut stack: Vec<u16> = Vec::with_capacity(TILES);
        let mut members: Vec<u16> = Vec::with_capacity(TILES);
        for i in 0..TILES {
            if label[i] != NONE || !open[i] || rep.len() >= NONE as usize {
                continue;
            }
            let r = rep.len() as u8;
            members.clear();
            if count == TILES {
                // Open ground throughout: one region, no flood.
                label = [0; TILES];
                members.extend(0..TILES as u16);
            } else {
                label[i] = r;
                stack.push(i as u16);
                while let Some(t) = stack.pop() {
                    members.push(t);
                    let (x, y) = (t as usize % n, t as usize / n);
                    let mut visit = |j: usize| {
                        if label[j] == NONE && open[j] {
                            label[j] = r;
                            stack.push(j as u16);
                        }
                    };
                    if x + 1 < n {
                        visit(t as usize + 1);
                    }
                    if x > 0 {
                        visit(t as usize - 1);
                    }
                    if y + 1 < n {
                        visit(t as usize + n);
                    }
                    if y > 0 {
                        visit(t as usize - n);
                    }
                }
            }
            let k = members.len() as f32;
            let (sx, sy) = members.iter().fold((0u32, 0u32), |a, &t| (a.0 + t as u32 % CHUNK, a.1 + t as u32 / CHUNK));
            let (mx, my) = (sx as f32 / k, sy as f32 / k);
            let d = |t: u16| (((t as u32 % CHUNK) as f32 - mx).powi(2) + ((t as u32 / CHUNK) as f32 - my).powi(2), t);
            let best = members.iter().map(|&t| d(t)).min_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1))).expect("a region has a tile").1 as u32;
            rep.push(((ox + best % CHUNK) as f32 + 0.5, (oy + best / CHUNK) as f32 + 0.5));
            let roads = members.iter().filter(|&&t| road_tile[t as usize]).count();
            road.push((roads * 255 / members.len()) as u8);
        }
        ChunkNav { label, rep, road }
    }

    /// The region of tile `(x, y)`, if it is walkable.
    fn region_of(&self, x: i32, y: i32) -> Option<u32> {
        if x < 0 || y < 0 || x >= self.w as i32 || y >= self.h as i32 {
            return None;
        }
        let c = (y as u32 / CHUNK) * self.chunks_wide() + x as u32 / CHUNK;
        let l = self.chunk_nav(c).label[((y as u32 % CHUNK) * CHUNK + x as u32 % CHUNK) as usize];
        (l != NONE).then_some(region_key(c, l))
    }

    /// The region a body at `p` walks from: its own tile's, or (standing on a blocked tile,
    /// pushed into a wall) the first open neighbour's.
    fn region_near(&self, p: (f32, f32)) -> Option<u32> {
        let (x, y) = (p.0.floor() as i32, p.1.floor() as i32);
        self.region_of(x, y).or_else(|| [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)].into_iter().find_map(|(dx, dy)| self.region_of(x + dx, y + dy)))
    }

    /// The next leg of a walk from `from` to `to`: straight when the way is clear, otherwise
    /// planned through areas, regions and tiles (the module notes). `None` when `to` is not
    /// walkable or cannot be reached from `from`.
    pub fn route_leg(&self, from: (f32, f32), to: (f32, f32), spec: &RouteSpec) -> Option<Leg> {
        if !self.walkable(to.0.floor() as i32, to.1.floor() as i32) {
            return None;
        }
        if self.line_clear(from, to) {
            return Some(Leg { points: vec![to], last: true, areas: 0, regions: 0, tiles: 0 });
        }
        let (start, goal) = (self.region_near(from)?, self.region_of(to.0.floor() as i32, to.1.floor() as i32)?);
        let (start_area, goal_area) = (self.area_of(start)?, self.area_of(goal)?);
        // Ground not connected to the start's is refused at once, not by flooding every area.
        if let Some(c) = self.nav.components.get() {
            if area_component(c, start_area) != area_component(c, goal_area) {
                return None;
            }
        }
        // 1. Areas, the whole way.
        let (areas, n_areas) = astar((start_area, self.area_rep(start_area)), goal_area, to, spec.road_speed, spec.max_nodes, |k| &self.area_links(k >> 16)[(k & 0xFFFF) as usize], |_| true)?;
        let ka = stretch(&areas, from, spec.area_m, |k| self.area_rep(k));
        let areas_end = ka == areas.len() - 1;
        let mid_goal = if areas_end { goal } else { self.block_nav(areas[ka] >> 16).rep_region[(areas[ka] & 0xFFFF) as usize] };
        let bh = self.chunks_high().div_ceil(BLOCK);
        let blocks = widen(areas[..=ka].iter().map(|k| k >> 16), self.blocks_wide(), bh);
        // 2. Regions, through those blocks.
        let mid_to = if areas_end { to } else { self.region_rep(mid_goal) };
        let (regions, n_regions) = astar((start, self.region_rep(start)), mid_goal, mid_to, spec.road_speed, spec.max_nodes, |k| &self.region_links(k >> 8)[(k & 0xFF) as usize], |k| blocks.binary_search(&self.block_of(k >> 8)).is_ok())?;
        let kr = stretch(&regions, from, spec.leg_m, |k| self.region_rep(k));
        let last = areas_end && kr == regions.len() - 1;
        let target = if last { to } else { self.region_rep(regions[kr]) };
        // 3. Tiles, through those chunks.
        let cw = self.chunks_wide();
        let chunks = widen(regions[..=kr].iter().map(|k| k >> 8), cw, self.chunks_high());
        let inside = |x: i32, y: i32| chunks.binary_search(&((y as u32 / CHUNK) * cw + x as u32 / CHUNK)).is_ok();
        let (points, tiles) = self.search(from, target, chunks.len() * TILES, inside)?;
        Some(Leg { points, last, areas: n_areas, regions: n_regions, tiles })
    }

    /// What the cache holds now: chunks with their regions worked out, their regions, and the
    /// areas of the blocks worked out (measurement).
    pub fn route_cache(&self) -> (usize, usize, usize) {
        let chunks: Vec<&ChunkNav> = self.nav.chunks.get().map_or(Vec::new(), |v| v.iter().filter_map(|s| s.regions.get().map(|b| &**b)).collect());
        let areas = self.nav.blocks.get().map_or(0, |v| v.iter().filter_map(|s| s.areas.get()).map(|b| b.members.len()).sum());
        (chunks.len(), chunks.iter().map(|c| c.rep.len()).sum(), areas)
    }

    /// Whether `to` can be walked to from `from` as far as the connected ground says:
    /// `Some(false)` when they are on ground not connected (water or walls between), `Some(true)`
    /// when connected (the way may still be long), `None` before the routes are warmed or when
    /// either end is not walkable ground. O(1) once warmed.
    pub fn reachable(&self, from: (f32, f32), to: (f32, f32)) -> Option<bool> {
        let a = self.component_near(from)?;
        let b = self.component_of(to.0.floor() as i32, to.1.floor() as i32)?;
        Some(a == b)
    }

    /// The connected component of tile `(x, y)`'s ground, once the routes are warmed.
    pub(crate) fn component_of(&self, x: i32, y: i32) -> Option<u32> {
        let c = self.nav.components.get()?;
        Some(area_component(c, self.area_of(self.region_of(x, y)?)?))
    }

    /// The connected component a body at `p` walks on (see `region_near`).
    pub(crate) fn component_near(&self, p: (f32, f32)) -> Option<u32> {
        let c = self.nav.components.get()?;
        Some(area_component(c, self.area_of(self.region_near(p)?)?))
    }

    /// Label every area with its connected component over the area links (built as needed).
    fn label_components(&self) -> Box<[Box<[u32]>]> {
        let nb = self.blocks_wide() * self.chunks_high().div_ceil(BLOCK);
        let mut comp: Vec<Vec<u32>> = (0..nb).map(|b| vec![u32::MAX; self.block_nav(b).members.len()]).collect();
        let (mut next, mut stack) = (0u32, Vec::new());
        for b in 0..nb {
            for a in 0..comp[b as usize].len() {
                if comp[b as usize][a] != u32::MAX {
                    continue;
                }
                comp[b as usize][a] = next;
                stack.push(area_key(b, a as u16));
                while let Some(k) = stack.pop() {
                    for l in &self.area_links(k >> 16)[(k & 0xFFFF) as usize] {
                        let (ob, oa) = ((l.to >> 16) as usize, (l.to & 0xFFFF) as usize);
                        if comp[ob][oa] == u32::MAX {
                            comp[ob][oa] = next;
                            stack.push(l.to);
                        }
                    }
                }
                next += 1;
            }
        }
        comp.into_iter().map(Vec::into_boxed_slice).collect()
    }

    /// Work out up to `chunks` more chunks' regions and links (then blocks' areas, a block
    /// counting as `BLOCK` chunks, then the connected components), so later routes find them
    /// ready. Returns false once everything is built. A tile changed afterwards is worked out
    /// again when needed, and the components are labelled again at the next call.
    pub fn warm_routes(&self, chunks: usize) -> bool {
        let nc = self.chunks_wide() * self.chunks_high();
        let nb = self.blocks_wide() * self.chunks_high().div_ceil(BLOCK);
        let mut budget = chunks;
        while budget > 0 {
            let i = self.nav.warmed.load(AtomicOrdering::Relaxed);
            if i >= nc + nb {
                if self.nav.components.get().is_some() {
                    return false;
                }
                let _ = self.nav.components.set(self.label_components());
                return true;
            }
            if i < nc {
                self.region_links(i);
                budget -= 1;
            } else {
                self.area_links(i - nc);
                budget = budget.saturating_sub(BLOCK as usize);
            }
            self.nav.warmed.store(i + 1, AtomicOrdering::Relaxed);
        }
        true
    }

}

#[cfg(test)]
mod tests {
    use super::*;

    fn open(w: u32, h: u32) -> Map {
        Map { w, h, tiles: vec![Terrain::Grass as u8; (w * h) as usize], blocked: Default::default(), opaque: Default::default(), nav: Default::default() }
    }

    fn walk(m: &Map, from: (f32, f32), to: (f32, f32), spec: &RouteSpec) -> (Vec<(f32, f32)>, usize) {
        // Follow legs as a walker does: plan, walk to near the leg's end, plan again.
        let mut at = from;
        let mut track = vec![from];
        for legs in 1..200 {
            let leg = m.route_leg(at, to, spec).expect("a leg");
            for w in &leg.points {
                for k in 1..=20 {
                    let t = k as f32 / 20.0;
                    let q = (at.0 + (w.0 - at.0) * t, at.1 + (w.1 - at.1) * t);
                    assert!(m.free(q.0, q.1), "walks only on open ground: {q:?}");
                }
                track.push(*w);
                at = *w;
            }
            if leg.last {
                return (track, legs);
            }
        }
        panic!("did not arrive");
    }

    fn length(t: &[(f32, f32)]) -> f32 {
        t.windows(2).map(|w| ((w[1].0 - w[0].0).powi(2) + (w[1].1 - w[0].1).powi(2)).sqrt()).sum()
    }

    #[test]
    fn a_long_wall_is_walked_round_leg_by_leg_without_a_whole_map_search() {
        // 512 m with a wall across it, open only at its far end: the 6,000-tile search fails,
        // the route goes round in legs, each search bounded by its corridor.
        let mut m = open(512, 512);
        for x in 0..500 {
            m.set(x, 256, Terrain::Wall);
        }
        let (a, b) = ((100.5, 200.5), (100.5, 300.5));
        assert!(m.path(a, b, 6_000).is_none(), "beyond the plain search");
        let spec = RouteSpec::default();
        let (track, legs) = walk(&m, a, b, &spec);
        let best = m.path(a, b, 2_000_000).unwrap();
        let (got, opt) = (length(&track), length(&[vec![a], best].concat()));
        assert!(legs > 5 && got < opt * 1.08, "{legs} legs, {got:.0} m against {opt:.0} m");
        assert!(*track.last().unwrap() == b);
        let first = m.route_leg(a, b, &spec).unwrap();
        assert!(!first.last && first.tiles < 9 * 9 * 256, "{first:?}");
    }

    #[test]
    fn unreachable_and_unwalkable_goals_are_refused() {
        let mut m = open(128, 128);
        for x in 0..128 {
            m.set(x, 64, Terrain::Water);
        }
        let spec = RouteSpec::default();
        assert!(m.route_leg((10.5, 10.5), (10.5, 100.5), &spec).is_none(), "across water");
        assert!(m.route_leg((10.5, 10.5), (10.5, 64.5), &spec).is_none(), "into water");
        // A shut gate in a gap closes the way; opening it opens it again.
        m.set(40, 64, Terrain::Grass);
        assert!(m.route_leg((10.5, 10.5), (10.5, 100.5), &spec).is_some(), "through the gap");
        m.set_blocked([64 * 128 + 40].into_iter().collect());
        assert!(m.route_leg((10.5, 10.5), (10.5, 100.5), &spec).is_none(), "gate shut");
        m.set_blocked(Default::default());
        assert!(m.route_leg((10.5, 10.5), (10.5, 100.5), &spec).is_some(), "gate open");
    }

    #[test]
    fn ground_across_water_is_refused_at_once_once_warmed() {
        // Two shores 3 tiles of water apart.
        let mut m = open(256, 256);
        for x in 0..256 {
            for y in 127..130 {
                m.set(x, y, Terrain::Water);
            }
        }
        let (north, north2, south) = ((50.5, 40.5), (200.5, 100.5), (50.5, 200.5));
        assert_eq!(m.reachable(north, south), None, "not known before the warm-up");
        while m.warm_routes(64) {}
        assert_eq!(m.reachable(north, south), Some(false));
        assert_eq!(m.reachable(north, north2), Some(true));
        assert!(m.route_leg(north, south, &RouteSpec::default()).is_none(), "far shore");
        assert!(m.route_leg(north, north2, &RouteSpec::default()).is_some(), "same shore");
        // A click in the water nearer the far shore lands on the walker's own shore.
        assert_eq!(m.nearest_walkable(50.5, 129.4).map(|p| p.1), Some(130.5), "the far shore is nearer");
        assert_eq!(m.nearest_reachable(north, 50.5, 129.4).map(|p| p.1), Some(126.5));
        // A bridge joins the shores; the components are labelled again at the next warm-up.
        for y in 127..130 {
            m.set(60, y, Terrain::Grass);
        }
        assert_eq!(m.reachable(north, south), None, "dropped with the change");
        while m.warm_routes(64) {}
        assert_eq!(m.reachable(north, south), Some(true));
        assert!(m.route_leg(north, south, &RouteSpec::default()).is_some(), "over the bridge");
    }

    #[test]
    fn area_keys_spread_over_hash_buckets() {
        // Area keys keep the block in the high bits and the area (mostly 0) in the low ones; the
        // table picks buckets by the hash's low bits, so the hash must depend on the high ones.
        use std::hash::BuildHasher;
        let b = std::hash::BuildHasherDefault::<TileHasher>::default();
        let buckets: std::collections::HashSet<u64> = (0..4096u32).map(|k| b.hash_one(area_key(k, 0)) & 4095).collect();
        assert!(buckets.len() > 2000, "{} of 4096 buckets", buckets.len());
    }

    #[test]
    fn roads_are_preferred_where_they_save_time() {
        // A rock band with two gaps: open ground on the left, a road on the right that is
        // longer but, at a high road speed, faster.
        let mut m = open(256, 256);
        for x in 0..256 {
            for y in 96..144 {
                m.set(x, y, Terrain::Rock);
            }
        }
        for y in 96..144 {
            for x in 96..112 {
                m.set(x, y, Terrain::Grass);
            }
        }
        for y in 48..192 {
            for x in 160..176 {
                m.set(x, y, Terrain::Road);
            }
        }
        let crossing = |track: &[(f32, f32)]| {
            let w = track.windows(2).find(|w| (w[0].1 - 120.0) * (w[1].1 - 120.0) <= 0.0).unwrap();
            w[0].0 + (w[1].0 - w[0].0) * (120.0 - w[0].1) / (w[1].1 - w[0].1)
        };
        let (a, b) = ((130.5, 60.5), (130.5, 180.5));
        let (track, _) = walk(&m, a, b, &RouteSpec { road_speed: 3.0, ..Default::default() });
        assert!(crossing(&track) > 160.0, "the road: {track:?}");
        let (track, _) = walk(&m, a, b, &RouteSpec { road_speed: 1.0, ..Default::default() });
        assert!(crossing(&track) < 112.0, "the shorter way when roads are no faster: {track:?}");
    }

    #[test]
    fn routes_are_deterministic_and_follow_terrain_changes() {
        let mut m = crate::map::generate(7);
        let (a, b) = (m.nearest_walkable(20.0, 48.0).unwrap(), m.nearest_walkable(70.0, 60.0).unwrap());
        let spec = RouteSpec { leg_m: 24.0, ..Default::default() };
        let one = m.route_leg(a, b, &spec).unwrap();
        // The regions are only a cache: a fresh map, and one with everything built ahead of
        // time, plan the same leg.
        let fresh = || Map::from_chunks(m.w, m.h, m.chunks().map(|id| (id, m.chunk_bytes(id))).collect::<Vec<_>>());
        assert_eq!(one, fresh().route_leg(a, b, &spec).unwrap());
        let warm = fresh();
        while warm.warm_routes(7) {}
        assert_eq!(one, warm.route_leg(a, b, &spec).unwrap());
        // Wall off the start's surroundings: the cached regions follow.
        let (x, y) = (a.0 as i32, a.1 as i32);
        for d in -3..=3 {
            for (px, py) in [(x + d, y - 3), (x + d, y + 3), (x - 3, y + d), (x + 3, y + d)] {
                m.set(px, py, Terrain::Wall);
            }
        }
        assert!(m.route_leg(a, b, &spec).is_none(), "walled in");
    }
}
