//! Static cover shared by the authority's map and the client's Shade.
use crate::{
    land::{Land, LandParams},
    map::{Map, Terrain, CHUNK},
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(default)]
pub struct Spec {
    brush: Vec<Brush>,
    cliffs: Vec<Face>,
    // Reserved in the recipe. Height-aware sight handles ordinary overlooks.
    overlooks: Vec<Face>,
}

impl Spec {
    pub fn is_empty(&self) -> bool {
        self.brush.is_empty() && self.cliffs.is_empty() && self.overlooks.is_empty()
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct Brush {
    id: String,
    area: Vec<[f32; 2]>,
    height_m: f32,
    fill: f32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct Face {
    id: String,
    points: Vec<[f32; 2]>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    height_m: Option<f32>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Policy {
    pub eye_height_m: f32,
    pub brush_on: bool,
    pub brush_min_fill: f32,
    pub cliff_step_m: f32,
}

pub fn placement_sample(x: u32, y: u32) -> f32 {
    let mut h = x.wrapping_mul(0x9E37_79B1) ^ y.wrapping_mul(0x85EB_CA77);
    h ^= h >> 15;
    h = h.wrapping_mul(0x2C1B_3C6D);
    h ^= h >> 12;
    (h & 0xFFFF) as f32 / 65535.0
}

pub fn forest_tree(x: u32, y: u32) -> bool {
    placement_sample(x, y) < 0.1
}

const SIGHT: u8 = 1;
const MISSILE: u8 = 2;
const BRUSH: u8 = 4;

#[derive(Clone, Copy, Debug, Default, PartialEq)]
struct Cell {
    solid_top: i16,
    brush_top: i16,
    brush_id: u16,
    bits: u8,
}

#[derive(Debug, PartialEq)]
struct CoverChunk {
    cells: [Cell; (CHUNK * CHUNK) as usize],
    occupied: [u16; CHUNK as usize],
}

#[derive(Debug, PartialEq)]
pub struct Mask {
    w: u32,
    ground: Arc<[i16]>,
    eye_dm: f32,
    chunks_wide: u32,
    chunks: Vec<Option<Box<CoverChunk>>>,
}

fn dm(metres: f32) -> i16 {
    (metres * 10.0).round() as i16
}

/// Sample the already generated land at tile centres. The authority persists this, in bands of
/// [`ground_range`], when the world's cover law is on (docs/COVER_SIGHT.md, "Cover geometry").
pub fn ground(land: &Land) -> Arc<[i16]> {
    ground_range(land, 0..(land.size as usize).pow(2)).into()
}

/// [`ground`]'s samples for row-major tile indices `range` (clipped to the land): the same
/// values, so a land sampled band by band keeps exactly the rows it would keep sampled whole.
/// The sampling is the cost of cover geometry: about 4 × 10³ (the island) to 10⁴ (a dense city)
/// WASM instructions a tile.
pub fn ground_range(land: &Land, range: std::ops::Range<usize>) -> Vec<i16> {
    let n = land.size as usize;
    (range.start.min(n * n)..range.end.min(n * n)).map(|i| {
        let (x, y) = (i % n, i / n);
        dm(land.height(x as f32 + 0.5, y as f32 + 0.5))
    }).collect()
}

impl Mask {
    fn z(&self, x: u32, y: u32) -> i16 {
        if x < self.w {
            self.ground.get((y as usize) * self.w as usize + x as usize).copied().unwrap_or(0)
        } else { 0 }
    }

    pub(crate) fn eye(&self, x: i32, y: i32) -> f32 {
        self.z(x as u32, y as u32) as f32 + self.eye_dm
    }

    fn chunk(&self, cx: u32, cy: u32) -> Option<&CoverChunk> {
        if cx >= self.chunks_wide { return None; }
        self.chunks.get((cy * self.chunks_wide + cx) as usize)?.as_deref()
    }

    /// Skip elevation and per-tile cover reads when the segment's box contains no cover.
    pub(crate) fn might_cross(&self, a: (f32, f32), b: (f32, f32)) -> bool {
        if a.0.min(b.0) < 0.0 || a.1.min(b.1) < 0.0 { return true; }
        let (x0, x1) = (a.0.min(b.0) as u32, a.0.max(b.0) as u32);
        let (y0, y1) = (a.1.min(b.1) as u32, a.1.max(b.1) as u32);
        if x1 >= self.w || y1 / CHUNK >= self.chunks.len() as u32 / self.chunks_wide {
            return true;
        }
        for cy in y0 / CHUNK..=y1 / CHUNK {
            for cx in x0 / CHUNK..=x1 / CHUNK {
                let Some(chunk) = self.chunk(cx, cy) else { continue };
                let lx = x0.saturating_sub(cx * CHUNK);
                let rx = (x1 - cx * CHUNK).min(CHUNK - 1);
                let ly = y0.saturating_sub(cy * CHUNK);
                let ry = (y1 - cy * CHUNK).min(CHUNK - 1);
                let columns = (u16::MAX << lx) & (u16::MAX >> (CHUNK - 1 - rx));
                if chunk.occupied[ly as usize..=ry as usize].iter().any(|row| row & columns != 0) {
                    return true;
                }
            }
        }
        false
    }

    fn cell(&self, x: i32, y: i32) -> Option<&Cell> {
        let (x, y) = (u32::try_from(x).ok()?, u32::try_from(y).ok()?);
        self.chunk(x / CHUNK, y / CHUNK)
            .map(|c| &c.cells[((y % CHUNK) * CHUNK + x % CHUNK) as usize])
    }

    pub(crate) fn missile(&self, x: i32, y: i32) -> bool {
        self.cell(x, y).is_some_and(|c| c.bits & MISSILE != 0)
    }

    pub(crate) fn brush(&self, x: i32, y: i32, z: f32) -> Option<u16> {
        self.cell(x, y).filter(|c| c.bits & BRUSH != 0 && z < c.brush_top as f32).map(|c| c.brush_id)
    }

    pub(crate) fn hides(&self, x: i32, y: i32, z: f32, same_brush: Option<u16>) -> bool {
        self.cell(x, y).is_some_and(|c| (c.bits & SIGHT != 0 && z < c.solid_top as f32)
            || (c.bits & BRUSH != 0 && z < c.brush_top as f32 && Some(c.brush_id) != same_brush))
    }

    fn add(&mut self, x: u32, y: u32, top: i16, brush_id: Option<u16>) {
        let index = ((y / CHUNK) * self.chunks_wide + x / CHUNK) as usize;
        let chunk = self.chunks[index].get_or_insert_with(|| Box::new(CoverChunk {
            cells: [Cell::default(); (CHUNK * CHUNK) as usize],
            occupied: [0; CHUNK as usize],
        }));
        chunk.occupied[(y % CHUNK) as usize] |= 1 << (x % CHUNK);
        let c = &mut chunk.cells[((y % CHUNK) * CHUNK + x % CHUNK) as usize];
        if let Some(id) = brush_id {
            if c.bits & BRUSH == 0 || top >= c.brush_top {
                c.brush_top = top;
                c.brush_id = id;
            }
            c.bits |= BRUSH;
        } else {
            c.solid_top = if c.bits & SIGHT == 0 { top } else { c.solid_top.max(top) };
            c.bits |= SIGHT | MISSILE;
        }
    }

    fn relief(&self, x: u32, y: u32, h: u32) -> (i16, i16) {
        let mut lo = self.z(x, y);
        let mut hi = lo;
        for yy in y.saturating_sub(2)..=(y + 2).min(h - 1) {
            for xx in x.saturating_sub(2)..=(x + 2).min(self.w - 1) {
                let z = self.z(xx, yy);
                lo = lo.min(z);
                hi = hi.max(z);
            }
        }
        (lo, hi)
    }

    pub fn geometry_bytes(&self) -> (usize, usize) {
        let chunks = self.chunks.iter().flatten().count();
        let bytes = self.chunks.len() * std::mem::size_of::<Option<Box<CoverChunk>>>()
            + chunks * std::mem::size_of::<CoverChunk>();
        (bytes, self.ground.len() * 2)
    }
}

fn contains(area: &[[f32; 2]], x: f32, y: f32) -> bool {
    let mut inside = false;
    for (a, b) in area.iter().zip(area.iter().cycle().skip(1)) {
        if (a[1] > y) != (b[1] > y) && x < a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) {
            inside = !inside;
        }
    }
    inside
}

fn bounds(points: &[[f32; 2]], axis: usize, limit: u32) -> std::ops::Range<u32> {
    let lo = points.iter().map(|p| p[axis]).fold(f32::INFINITY, f32::min);
    let hi = points.iter().map(|p| p[axis]).fold(f32::NEG_INFINITY, f32::max);
    (lo.floor() as u32).min(limit)..(hi.floor() as u32).saturating_add(1).min(limit)
}

fn trunk(mask: &mut Mask, h: u32, center: [f32; 2], radius: f32, height: f32) {
    let [x, y] = center;
    let corners = [[x - radius, y - radius], [x + radius, y + radius]];
    let top = mask.z(x as u32, y as u32).saturating_add(dm(height));
    for ty in bounds(&corners, 1, h) {
        for tx in bounds(&corners, 0, mask.w) {
            let dx = x - x.clamp(tx as f32, tx as f32 + 1.0);
            let dy = y - y.clamp(ty as f32, ty as f32 + 1.0);
            if dx * dx + dy * dy <= radius * radius {
                mask.add(tx, ty, top, None);
            }
        }
    }
}

fn authored(mask: &mut Mask, h: u32, spec: &Spec, transform: impl Fn([f32; 2]) -> [f32; 2], policy: Policy, next_brush: &mut u16) {
    if policy.brush_on {
        for brush in spec.brush.iter().filter(|b| b.height_m >= policy.eye_height_m && b.fill >= policy.brush_min_fill) {
            *next_brush = next_brush.saturating_add(1);
            let polygon: Vec<_> = brush.area.iter().copied().map(&transform).collect();
            for y in bounds(&polygon, 1, h) {
                for x in bounds(&polygon, 0, mask.w) {
                    let hits = (0..100).filter(|&i| contains(&polygon,
                        x as f32 + (i % 10) as f32 * 0.1 + 0.05,
                        y as f32 + (i / 10) as f32 * 0.1 + 0.05)).count();
                    if hits as f32 * 0.01 * brush.fill >= policy.brush_min_fill {
                        mask.add(x, y, mask.z(x, y).saturating_add(dm(brush.height_m)), Some(*next_brush));
                    }
                }
            }
        }
    }
    for cliff in &spec.cliffs {
        for edge in cliff.points.windows(2) {
            let [a, b] = [transform(edge[0]), transform(edge[1])];
            let steps = ((a[0] - b[0]).abs().max((a[1] - b[1]).abs()) * 4.0).ceil().max(1.0) as u32;
            for i in 0..=steps {
                let t = i as f32 / steps as f32;
                let (x, y) = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t);
                if x < 0.0 || y < 0.0 || x >= mask.w as f32 || y >= h as f32 { continue; }
                let (x, y) = (x as u32, y as u32);
                let (lo, hi) = mask.relief(x, y, h);
                let top = cliff.height_m.map_or(hi, |height| lo.saturating_add(dm(height)));
                mask.add(x, y, top, None);
            }
        }
    }
}

const DROP_MARK: u32 = 1 << 31;

/// Keep only procedural tree anchors and potential cliff cells from genesis terrain.
pub fn candidates(map: &Map) -> Vec<u32> {
    map.tiles.iter().enumerate().filter_map(|(i, tile)| {
        let i = i as u32;
        match Terrain::from_u8(*tile) {
            Terrain::Forest if forest_tree(i % map.w, i / map.w) => Some(i),
            Terrain::Drop => Some(i | DROP_MARK),
            _ => None,
        }
    }).collect()
}

pub fn compile(map: &Map, ground: Arc<[i16]>, recipe: &LandParams, policy: Policy) -> Mask {
    compile_candidates(map.w, map.h, candidates(map), ground, recipe, policy)
}

pub fn compile_candidates(w: u32, h: u32, candidates: impl IntoIterator<Item = u32>,
    ground: Arc<[i16]>, recipe: &LandParams, policy: Policy) -> Mask {
    let chunks_wide = w.div_ceil(CHUNK);
    let chunks = (0..chunks_wide * h.div_ceil(CHUNK)).map(|_| None).collect();
    let mut mask = Mask { w, ground, eye_dm: policy.eye_height_m * 10.0, chunks_wide, chunks };
    for candidate in candidates {
        let i = candidate & !DROP_MARK;
        let (x, y) = (i % w, i / w);
        if candidate & DROP_MARK == 0 {
            let center = [x as f32 + 0.25 + 0.5 * placement_sample(x, y),
                          y as f32 + 0.25 + 0.5 * placement_sample(y, x)];
            trunk(&mut mask, h, center, 0.20, 3.2);
        } else {
            let (lo, hi) = mask.relief(x, y, h);
            if hi.saturating_sub(lo) >= dm(policy.cliff_step_m) {
                mask.add(x, y, hi, None);
            }
        }
    }
    let mut next_brush = 0;
    authored(&mut mask, h, &recipe.cover, |p| p, policy, &mut next_brush);
    for plan in &recipe.plans {
        let (sn, cs) = crate::det::Det::d_sin_cos(plan.rotation_deg.to_radians());
        let xy = |p: [f32; 2]| [plan.origin[0] + (cs * p[0] + sn * p[1]), plan.origin[1] + (sn * p[0] - cs * p[1])];
        authored(&mut mask, h, &plan.cover, xy, policy, &mut next_brush);
        for tree in plan.resources.iter().filter(|r| r.kind == "tree") {
            trunk(&mut mask, h, xy(tree.at), tree.trunk_r_m.unwrap_or(0.20), tree.trunk_h_m.unwrap_or(3.2));
        }
    }
    mask
}

#[cfg(test)]
mod tests {
    use super::*;

    fn policy() -> Policy {
        Policy { eye_height_m: 1.6, brush_on: true, brush_min_fill: 0.6, cliff_step_m: 2.0 }
    }

    fn blank() -> Map {
        Map::from_chunks(16, 16, std::iter::empty())
    }

    /// Bands sampled one by one (staged genesis, a derivation after a switch-on) are exactly
    /// the whole land's samples, so their `cover_ground` rows are the same.
    #[test]
    fn ground_in_bands_is_ground() {
        let land = crate::land::generate_default(7, 256);
        let whole = ground(&land);
        let band = 5_000;
        let mut parts = Vec::new();
        for i in 0..(256usize * 256).div_ceil(band) {
            parts.extend(ground_range(&land, i * band..(i + 1) * band));
        }
        assert_eq!(&parts[..], &whole[..]);
        assert!(ground_range(&land, 70_000..80_000).is_empty());
    }

    #[test]
    fn trunk_stops_missiles_and_sight_but_brush_only_hides() {
        let mut map = blank();
        let mut cover = compile(&map, Arc::from([0; 256]), &LandParams::default(), policy());
        cover.add(3, 2, 32, None);
        for x in 3..=5 {
            cover.add(x, 5, 20, Some(1));
        }
        map.cover = Some(Arc::new(cover));
        assert!(!map.sight_clear((1.5, 2.5), (6.5, 2.5)));
        assert!(!map.passable_missile(3.5, 2.5));
        assert!(!map.sight_clear((1.5, 5.5), (4.5, 5.5)));
        assert!(map.sight_clear((3.5, 5.5), (5.5, 5.5)));
        assert!(map.passable_missile(3.5, 5.5));
        map.cover = None;
        assert!(map.sight_clear((1.5, 2.5), (6.5, 2.5)));
        assert!(map.sight_clear((1.5, 5.5), (4.5, 5.5)));
    }

    #[test]
    fn cliff_can_hide_level_ray_and_clear_an_overlook() {
        let mut map = blank();
        let mut z = [0; 256];
        z[4] = 30;
        let mut planar = compile(&map, Arc::from([0; 256]), &LandParams::default(), policy());
        planar.add(3, 0, 25, None);
        map.cover = Some(Arc::new(planar));
        assert!(!map.sight_clear((4.5, 0.5), (1.5, 0.5)), "the same path with flat eyes is blocked");
        let mut cover = compile(&map, Arc::from(z), &LandParams::default(), policy());
        cover.add(3, 0, 25, None);
        map.cover = Some(Arc::new(cover));
        assert!(!map.sight_clear((1.5, 0.5), (6.5, 0.5)));
        assert!(!map.passable_missile(3.5, 0.5));
        assert!(map.sight_clear((4.5, 0.5), (1.5, 0.5)));
        assert!(map.sight_clear((1.5, 0.5), (4.5, 0.5)));
    }

    #[test]
    fn published_recipe_and_private_candidates_compile_identically() {
        let raw = serde_json::json!({"cover":{
            "brush":[{"id":"brush","area":[[2,2],[5,2],[5,5],[2,5],[2,2]],"height_m":2.0,"fill":0.8}],
            "cliffs":[{"id":"cut","points":[[6,2],[6,5]],"height_m":3.0}],
            "overlooks":[{"id":"reserved","points":[[7,2],[7,5]]}]
        }});
        let private: LandParams = serde_json::from_value(raw.clone()).unwrap();
        let public: LandParams = serde_json::from_value(crate::land::public_params(&raw).unwrap()).unwrap();
        let mut map = blank();
        map.set(8, 8, Terrain::Forest);
        let ground = Arc::from([0; 256]);
        let shade = compile(&map, Arc::clone(&ground), &public, policy());
        let mut authority = map.clone();
        authority.set(8, 8, Terrain::Grass);
        let cached = compile_candidates(authority.w, authority.h, candidates(&map), ground, &private, policy());
        assert_eq!(cached, shade);
        assert!(shade.brush(3, 3, 16.0).is_some());
        assert!(shade.missile(6, 3));
    }

    #[test]
    fn old_empty_recipe_has_no_authored_cover() {
        let params: LandParams = serde_json::from_str("{}").unwrap();
        assert!(params.cover.is_empty());
        assert!(compile(&blank(), Arc::from([0; 256]), &params, policy()).chunks.iter().all(Option::is_none));
    }
}
