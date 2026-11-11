//! Ground per environment (docs/GAME_BRIEF.md, "Ground per environment"): an environment's own
//! surfaces for the island's ground, so a hand-authored town (Cullet) is paved, cindered and
//! sanded as its kit says rather than by the generic island's rules.
//!
//! - **The map:** keys with a colon in the environment's `ground` object (`envs/<env>.json`,
//!   beside `surface`, `color`, `radius` and `relief`). Each value is
//!   `{"layer": <ground layer>, "colour": [r, g, b] (sRGB), "tint": [r, g, b] (optional)}`:
//!   the painted layer (`terrain.rs` `Layer`, by its `ground.txt` name), the vertex colour, and
//!   a colour the slow macro variation leans toward. The keys:
//!   - `street:<surface>`: a laid street of that `surface` (a plan's `streets[].surface`);
//!   - `class:<Terrain>`: the rules' terrain class (`Road` is a road tile with no street
//!     surface, such as a paved square);
//!   - `region:<RegionKind>`, as the seed spells it (`meadow`, `highland`, `beach`, `forest`);
//!   - `stamp:<ground>`: inside a relief stamp of that `ground` (`map.params.relief.stamps`);
//!   - `area:<surface>`: inside an area of `envs/<env>/ground.json` of that surface.
//! - **The areas** (`envs/<env>/ground.json`, written by the kit's generator): a list of
//!   `{"id", "surface", "area": [[x, z], …] (land metres), "cause"}`, later entries on top. A
//!   vertex that is not on a road and lies inside one takes `area:<surface>`; area edges are crisp,
//!   like roads.
//! - **Lookup**, most specific first ([`GroundMap::lookup`]): on a road tile `street:` then
//!   `class:Road`; elsewhere `area:`, `stamp:`, `class:`, then `region:` (not under water: lake and
//!   sea beds keep their mud and sand). Whatever finds no key is drawn by the island's own rules
//!   (`island.rs` `ground_colour`, `ground_layers`, `road_layer`).
//!
//! An environment without a map (the island) is drawn exactly as before: [`Ground::is_empty`]
//! skips every lookup.

use crate::terrain::Layer;
use crate::world::{hash, rgb, scale};
use bevy::prelude::*;
use living_rules::land::{Land, LandParams, RegionKind};
use living_rules::map::Terrain;
use serde::Deserialize;
use std::collections::HashMap;

/// A mapped surface: its painted layer, its vertex colour (linear) and the colour its macro
/// variation leans toward.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Surface {
    pub layer: Layer,
    pub colour: [f32; 4],
    pub tint: Option<[f32; 4]>,
}

impl Surface {
    pub fn new(layer: Layer, colour: [u8; 3], tint: Option<[u8; 3]>) -> Self {
        Self { layer, colour: rgb(colour[0], colour[1], colour[2]), tint: tint.map(|t| rgb(t[0], t[1], t[2])) }
    }

    /// The vertex colour at a point: the per-vertex value `v` (0–1) as the island's own colours
    /// vary, leaning toward the tint over slow patches (tens of metres, as the shader's macro
    /// variation).
    pub fn colour_at(&self, p: Vec2, v: f32) -> [f32; 4] {
        let mut c = scale(self.colour, 0.94 + 0.12 * v);
        if let Some(t) = self.tint {
            let m = 0.6 * noise(p / 37.0, 0x51ab) + 0.4 * noise(p / 13.0 + 17.0, 0x7c3d);
            let k = TINT_LEAN * smooth((m - 0.3) / 0.45);
            for i in 0..3 {
                c[i] += (t[i] * (0.94 + 0.12 * v) - c[i]) * k;
            }
        }
        c
    }
}

/// How far a surface's colour leans toward its tint in the strongest patches.
const TINT_LEAN: f32 = 0.55;

fn smooth(t: f32) -> f32 {
    let t = t.clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

/// Smooth value noise in 0..1, one cell per unit of `q`.
fn noise(q: Vec2, seed: u32) -> f32 {
    let (i, f) = (q.floor(), q - q.floor());
    let s = f * f * (Vec2::splat(3.0) - 2.0 * f);
    let h = |x: f32, y: f32| hash((x as i32 as u32).wrapping_add(seed), (y as i32 as u32).wrapping_mul(7919) ^ seed);
    let a = h(i.x, i.y) + (h(i.x + 1.0, i.y) - h(i.x, i.y)) * s.x;
    let b = h(i.x, i.y + 1.0) + (h(i.x + 1.0, i.y + 1.0) - h(i.x, i.y + 1.0)) * s.x;
    a + (b - a) * s.y
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawSurface {
    layer: String,
    colour: [u8; 3],
    #[serde(default)]
    tint: Option<[u8; 3]>,
}

/// The rules' terrain class as a map key spells it (its variant name).
pub fn class_name(t: Terrain) -> &'static str {
    match t {
        Terrain::Grass => "Grass",
        Terrain::Forest => "Forest",
        Terrain::Water => "Water",
        Terrain::Sand => "Sand",
        Terrain::Rock => "Rock",
        Terrain::Dirt => "Dirt",
        Terrain::Road => "Road",
        Terrain::Wall => "Wall",
        Terrain::Drop => "Drop",
        Terrain::Low => "Low",
    }
}

/// An environment's ground map, by key kind.
#[derive(Clone, Debug, Default)]
pub struct GroundMap {
    street: HashMap<String, Surface>,
    class: HashMap<&'static str, Surface>,
    region: HashMap<&'static str, Surface>,
    stamp: HashMap<String, Surface>,
    area: HashMap<String, Surface>,
}

/// What one ground sample is: its tile's class and region, and the street, area and stamp it
/// lies in.
#[derive(Clone, Copy, Debug)]
pub struct Sample<'a> {
    pub class: Terrain,
    pub region: RegionKind,
    pub street: Option<&'a str>,
    pub area: Option<&'a str>,
    pub stamp: Option<&'a str>,
}

impl GroundMap {
    /// The map from a `ground` object's keys with a colon. Keys without one are the old fields
    /// (or unknown, ignored as before); a bad key or value is skipped with a warning.
    pub fn parse(env: &str, keys: &HashMap<String, serde_json::Value>) -> Self {
        let mut map = Self::default();
        let mut keys: Vec<_> = keys.iter().filter(|(k, _)| k.contains(':')).collect();
        keys.sort_by(|a, b| a.0.cmp(b.0));
        for (key, value) in keys {
            let surface = match serde_json::from_value::<RawSurface>(value.clone()) {
                Ok(raw) => match Layer::from_name(&raw.layer) {
                    Some(layer) => Surface::new(layer, raw.colour, raw.tint),
                    None => {
                        warn!("ground map of {env}: {key}: no ground layer {:?}; skipped", raw.layer);
                        continue;
                    }
                },
                Err(e) => {
                    warn!("ground map of {env}: {key}: {e}; skipped");
                    continue;
                }
            };
            if let Err(e) = map.insert(key, surface) {
                warn!("ground map of {env}: {e}; skipped");
            }
        }
        map
    }

    /// Add one key (`street:setts`, `class:Road`, `region:meadow`, …).
    pub fn insert(&mut self, key: &str, s: Surface) -> Result<(), String> {
        let (kind, name) = key.split_once(':').ok_or_else(|| format!("{key}: no colon"))?;
        match kind {
            "street" => drop(self.street.insert(name.to_string(), s)),
            "stamp" => drop(self.stamp.insert(name.to_string(), s)),
            "area" => drop(self.area.insert(name.to_string(), s)),
            "class" => {
                let t = (0..=9u8).map(Terrain::from_u8).find(|t| class_name(*t) == name).ok_or_else(|| format!("{key}: no terrain class {name:?}"))?;
                self.class.insert(class_name(t), s);
            }
            "region" => {
                let k = RegionKind::ALL.iter().find(|k| k.id() == name).ok_or_else(|| format!("{key}: no region kind {name:?}"))?;
                self.region.insert(k.id(), s);
            }
            _ => return Err(format!("{key}: unknown key kind {kind:?} (street, class, region, stamp, area)")),
        }
        Ok(())
    }

    pub fn is_empty(&self) -> bool {
        self.street.is_empty() && self.class.is_empty() && self.region.is_empty() && self.stamp.is_empty() && self.area.is_empty()
    }

    pub fn len(&self) -> usize {
        self.street.len() + self.class.len() + self.region.len() + self.stamp.len() + self.area.len()
    }

    /// Whether an area surface is mapped (an unmapped area leaves the ground to the rest).
    #[cfg(test)]
    pub fn has_area(&self, surface: &str) -> bool {
        self.area.contains_key(surface)
    }

    /// The surface for a sample, most specific first: on a road tile `street:` then `class:Road`;
    /// elsewhere `area:`, `stamp:`, `class:`, then `region:` (not under water). None: the
    /// island's own rules.
    pub fn lookup(&self, s: &Sample) -> Option<&Surface> {
        if s.class == Terrain::Road {
            return s.street.and_then(|k| self.street.get(k)).or_else(|| self.class.get("Road"));
        }
        s.area
            .and_then(|k| self.area.get(k))
            .or_else(|| s.stamp.and_then(|k| self.stamp.get(k)))
            .or_else(|| self.class.get(class_name(s.class)))
            .or_else(|| (s.class != Terrain::Water).then(|| self.region.get(s.region.id())).flatten())
    }
}

/// Whether a point is inside a polygon (even-odd rule; the edge counts on one side only).
pub fn inside(poly: &[Vec2], p: Vec2) -> bool {
    let mut odd = false;
    let n = poly.len();
    for i in 0..n {
        let (a, b) = (poly[i], poly[(i + n - 1) % n]);
        if (a.y > p.y) != (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x {
            odd = !odd;
        }
    }
    odd
}

/// A polygon and its bounds.
#[derive(Clone, Debug)]
struct Poly {
    pts: Vec<Vec2>,
    lo: Vec2,
    hi: Vec2,
}

impl Poly {
    fn new(pts: Vec<Vec2>) -> Option<Self> {
        if pts.len() < 3 || pts.iter().any(|p| !p.is_finite()) {
            return None;
        }
        let lo = pts.iter().copied().fold(Vec2::splat(f32::MAX), Vec2::min);
        let hi = pts.iter().copied().fold(Vec2::splat(f32::MIN), Vec2::max);
        Some(Self { pts, lo, hi })
    }

    fn contains(&self, p: Vec2) -> bool {
        p.x >= self.lo.x && p.y >= self.lo.y && p.x <= self.hi.x && p.y <= self.hi.y && inside(&self.pts, p)
    }
}

#[derive(Deserialize)]
struct RawArea {
    #[serde(default)]
    id: String,
    surface: String,
    area: Vec<[f32; 2]>,
    #[serde(default)]
    #[allow(dead_code)]
    cause: String,
}

/// The areas of an environment's `ground.json`, later ones on top.
#[derive(Clone, Debug, Default)]
pub struct Areas(Vec<(String, Poly)>);

impl Areas {
    /// `envs/<env>/ground.json`; none when the kit has not written one.
    pub fn load(env: &str) -> Self {
        let path = std::path::Path::new(&crate::lookdev::asset_root()).join(format!("envs/{env}/ground.json"));
        match std::fs::read_to_string(&path) {
            Err(_) => Self::default(),
            Ok(text) => match Self::parse(&text) {
                Ok((a, skipped)) => {
                    info!("ground: {} areas from {}{}", a.0.len(), path.display(), if skipped > 0 { format!(" ({skipped} without three finite points skipped)") } else { String::new() });
                    a
                }
                Err(e) => {
                    error!("ground: {}: {e}; no areas", path.display());
                    Self::default()
                }
            },
        }
    }

    /// The areas and how many were skipped (fewer than three finite points).
    pub fn parse(text: &str) -> Result<(Self, usize), String> {
        let raw: Vec<RawArea> = serde_json::from_str(text).map_err(|e| e.to_string())?;
        let n = raw.len();
        let out: Vec<(String, Poly)> = raw
            .into_iter()
            .filter_map(|a| {
                let poly = Poly::new(a.area.iter().map(|p| Vec2::new(p[0], p[1])).collect());
                if poly.is_none() {
                    warn!("ground: area {:?} has fewer than three finite points; skipped", a.id);
                }
                Some((a.surface, poly?))
            })
            .collect();
        let skipped = n - out.len();
        Ok((Self(out), skipped))
    }

    /// The surface of the topmost area at a point.
    pub fn at(&self, p: Vec2) -> Option<&str> {
        self.0.iter().rev().find(|(_, poly)| poly.contains(p)).map(|(s, _)| s.as_str())
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }
}

/// The relief stamps that set a ground (`stamps[].ground`), later ones on top.
#[derive(Clone, Debug, Default)]
struct Stamps(Vec<(String, Terrain, Poly)>);

/// A stamp's `ground` as the rules read it (`land::stamp_ground`).
fn stamp_terrain(g: &str) -> Option<Terrain> {
    match g {
        "grass" => Some(Terrain::Grass),
        "sand" => Some(Terrain::Sand),
        "dirt" => Some(Terrain::Dirt),
        "rock" => Some(Terrain::Rock),
        "forest" => Some(Terrain::Forest),
        _ => None,
    }
}

impl Stamps {
    fn of(params: &LandParams) -> Self {
        Self(params.relief.stamps.iter().filter_map(|s| {
            let g = s.ground.as_deref()?;
            Some((g.to_string(), stamp_terrain(g)?, Poly::new(s.area.iter().map(|p| Vec2::new(p[0], p[1])).collect())?))
        }).collect())
    }

    /// The ground of the topmost stamp at a point whose tile it made (a stamp's ground stands
    /// only where the tile is still of it: water, roads and plans come after).
    fn at(&self, p: Vec2, class: Terrain) -> Option<&str> {
        self.0.iter().rev().find(|(_, t, poly)| *t == class && poly.contains(p)).map(|(g, _, _)| g.as_str())
    }
}

/// Planned streets with a surface, by 16 m cell, for which street a road tile is on.
#[derive(Clone, Debug, Default)]
pub struct Streets {
    segs: Vec<(Vec2, Vec2, f32, u16)>,
    cells: HashMap<(i32, i32), Vec<u32>>,
    surfaces: Vec<String>,
}

const STREET_CELL: f32 = 16.0;
/// How far past a street's half width a road tile still belongs to it (tiles are 1 m).
const STREET_SLACK: f32 = 1.0;

impl Streets {
    pub fn of_land(land: &Land) -> Self {
        let mut s = Self::default();
        for laid in &land.plans {
            for (road, surface) in &laid.streets {
                let (Some(surface), Some(r)) = (surface, land.roads.get(*road as usize)) else { continue };
                let k = match s.surfaces.iter().position(|x| x == surface) {
                    Some(k) => k,
                    None => {
                        s.surfaces.push(surface.clone());
                        s.surfaces.len() - 1
                    }
                } as u16;
                for w in r.points.windows(2) {
                    s.add(Vec2::new(w[0].0, w[0].1), Vec2::new(w[1].0, w[1].1), r.width_m * 0.5, k);
                }
                if r.points.len() == 1 {
                    let p = Vec2::new(r.points[0].0, r.points[0].1);
                    s.add(p, p, r.width_m * 0.5, k);
                }
            }
        }
        s
    }

    /// One centre-line segment of half width `half` and surface index `k`.
    pub fn add(&mut self, a: Vec2, b: Vec2, half: f32, k: u16) {
        let i = self.segs.len() as u32;
        self.segs.push((a, b, half, k));
        let r = half + STREET_SLACK;
        let (lo, hi) = ((a.min(b) - r) / STREET_CELL, (a.max(b) + r) / STREET_CELL);
        for cx in lo.x.floor() as i32..=hi.x.floor() as i32 {
            for cz in lo.y.floor() as i32..=hi.y.floor() as i32 {
                self.cells.entry((cx, cz)).or_default().push(i);
            }
        }
    }

    /// The surface of the street whose centre line is nearest, if the point is on it.
    pub fn at(&self, p: Vec2) -> Option<&str> {
        let cell = ((p.x / STREET_CELL).floor() as i32, (p.y / STREET_CELL).floor() as i32);
        let mut best: Option<(f32, u16)> = None;
        for &i in self.cells.get(&cell)? {
            let (a, b, half, k) = self.segs[i as usize];
            let d = segment_distance(p, a, b);
            if d <= half + STREET_SLACK && best.is_none_or(|(bd, _)| d < bd) {
                best = Some((d, k));
            }
        }
        best.map(|(_, k)| self.surfaces[k as usize].as_str())
    }

    pub fn len(&self) -> usize {
        self.segs.len()
    }
}

fn segment_distance(p: Vec2, a: Vec2, b: Vec2) -> f32 {
    let d = b - a;
    let t = if d.length_squared() > 1e-9 { ((p - a).dot(d) / d.length_squared()).clamp(0.0, 1.0) } else { 0.0 };
    p.distance(a + d * t)
}

/// The current environment's ground: its map and what the lookups need from the land.
#[derive(Clone, Debug, Default)]
pub struct Ground {
    pub map: GroundMap,
    areas: Areas,
    streets: Streets,
    stamps: Stamps,
}

impl Ground {
    /// For an environment (its id and map) on a land; nothing is gathered when the map is empty.
    pub fn new(env: &str, map: GroundMap, land: &Land, params: &LandParams) -> Self {
        if map.is_empty() {
            return Self::default();
        }
        let g = Self::of(map, Areas::load(env), land, params);
        info!("ground: {env}'s map ({} keys) over {} areas, {} street segments, {} ground stamps", g.map.len(), g.areas.len(), g.streets.len(), g.stamps.0.len());
        g
    }

    /// A map and areas on a land.
    pub fn of(map: GroundMap, areas: Areas, land: &Land, params: &LandParams) -> Self {
        Self { areas, streets: Streets::of_land(land), stamps: Stamps::of(params), map }
    }

    /// Without the land (tests): a map, areas and streets as given.
    #[cfg(test)]
    pub fn with(map: GroundMap, areas: Areas, streets: Streets) -> Self {
        Self { map, areas, streets, stamps: Stamps::default() }
    }

    pub fn is_empty(&self) -> bool {
        self.map.is_empty()
    }

    /// On a road tile: its street's surface, else `class:Road`.
    pub fn road(&self, p: Vec2, region: RegionKind) -> Option<&Surface> {
        self.map.lookup(&Sample { class: Terrain::Road, region, street: self.streets.at(p), area: None, stamp: None })
    }

    /// Off the roads, inside a mapped area: its surface (crisp, as roads are).
    pub fn area(&self, p: Vec2) -> Option<&Surface> {
        let s = self.areas.at(p)?;
        self.map.area.get(s)
    }

    /// Off the roads and areas: a stamp's ground, the class, then the region.
    pub fn open(&self, p: Vec2, class: Terrain, region: RegionKind) -> Option<&Surface> {
        self.map.lookup(&Sample { class, region, street: None, area: None, stamp: self.stamps.at(p, class) })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(layer: Layer) -> Surface {
        Surface::new(layer, [100, 100, 100], None)
    }

    fn map(keys: &[(&str, Layer)]) -> GroundMap {
        let mut m = GroundMap::default();
        for (k, l) in keys {
            m.insert(k, s(*l)).unwrap();
        }
        m
    }

    fn sample<'a>(class: Terrain, region: RegionKind, street: Option<&'a str>, area: Option<&'a str>, stamp: Option<&'a str>) -> Sample<'a> {
        Sample { class, region, street, area, stamp }
    }

    #[test]
    fn keys_parse_and_bad_ones_are_skipped() {
        let v: HashMap<String, serde_json::Value> = serde_json::from_str(
            r#"{
                "surface": "open", "color": [1, 2, 3], "radius": 0, "relief": 0,
                "street:setts": {"layer": "slate_setts", "colour": [90, 92, 96]},
                "street:quay_flags": {"layer": "quay_flags", "colour": [150, 146, 136], "tint": [120, 130, 140]},
                "class:Road": {"layer": "flagstone", "colour": [170, 160, 130]},
                "class:Sand": {"layer": "wet_sand", "colour": [200, 190, 160]},
                "region:highland": {"layer": "heather", "colour": [110, 96, 100]},
                "stamp:sand": {"layer": "sand", "colour": [210, 200, 160]},
                "area:cinders": {"layer": "cinders", "colour": [60, 58, 56]},
                "class:Lava": {"layer": "rock", "colour": [1, 1, 1]},
                "region:moon": {"layer": "rock", "colour": [1, 1, 1]},
                "street:mud": {"layer": "no_such_layer", "colour": [1, 1, 1]},
                "street:odd": {"layer": "rock", "colour": [1, 1]},
                "zone:x": {"layer": "rock", "colour": [1, 1, 1]}
            }"#,
        )
        .unwrap();
        let m = GroundMap::parse("test", &v);
        assert_eq!(m.len(), 7, "{m:?}");
        assert_eq!(m.street["setts"].layer, Layer::SlateSetts);
        assert_eq!(m.street["quay_flags"].tint, Some(rgb(120, 130, 140)));
        assert_eq!(m.class["Road"].layer, Layer::Flagstone);
        assert_eq!(m.region["highland"].layer, Layer::Heather);
        assert!(m.has_area("cinders") && !m.has_area("setts"));
        assert!(GroundMap::parse("test", &HashMap::new()).is_empty());
    }

    #[test]
    fn the_most_specific_key_wins() {
        use RegionKind::*;
        use Terrain::*;
        let full = map(&[
            ("street:setts", Layer::SlateSetts),
            ("class:Road", Layer::Flagstone),
            ("area:cinders", Layer::Cinders),
            ("stamp:sand", Layer::WetSand),
            ("class:Sand", Layer::KelpShingle),
            ("class:Dirt", Layer::WorkedSoil),
            ("region:beach", Layer::Sand),
            ("region:meadow", Layer::ThinTurf),
        ]);
        let l = |s: Sample| full.lookup(&s).map(|x| x.layer);
        // A road: its street, else class:Road; areas, stamps and regions never pave a road.
        assert_eq!(l(sample(Road, Meadow, Some("setts"), Some("cinders"), Some("sand"))), Some(Layer::SlateSetts));
        assert_eq!(l(sample(Road, Meadow, Some("earth"), None, None)), Some(Layer::Flagstone));
        assert_eq!(l(sample(Road, Meadow, None, Some("cinders"), None)), Some(Layer::Flagstone));
        // Off the road: area, stamp, class, region.
        assert_eq!(l(sample(Sand, Beach, None, Some("cinders"), Some("sand"))), Some(Layer::Cinders));
        assert_eq!(l(sample(Sand, Beach, None, Some("unmapped"), Some("sand"))), Some(Layer::WetSand));
        assert_eq!(l(sample(Sand, Beach, None, None, None)), Some(Layer::KelpShingle));
        assert_eq!(l(sample(Grass, Beach, None, None, None)), Some(Layer::Sand));
        assert_eq!(l(sample(Grass, Meadow, None, None, None)), Some(Layer::ThinTurf));
        // Under water the region doesn't reach; unmapped classes in unmapped regions fall through.
        assert_eq!(l(sample(Water, Beach, None, None, None)), None);
        assert_eq!(l(sample(Grass, Highland, None, None, None)), None);
        // Without class:Road a street-less road is the island's own.
        let bare = map(&[("street:setts", Layer::SlateSetts)]);
        assert_eq!(bare.lookup(&sample(Road, Meadow, Some("flags"), None, None)), None);
    }

    #[test]
    fn points_in_polygons() {
        let sq = [Vec2::new(0.0, 0.0), Vec2::new(10.0, 0.0), Vec2::new(10.0, 10.0), Vec2::new(0.0, 10.0)];
        assert!(inside(&sq, Vec2::new(5.0, 5.0)));
        assert!(inside(&sq, Vec2::new(0.01, 9.99)));
        assert!(!inside(&sq, Vec2::new(-0.01, 5.0)));
        assert!(!inside(&sq, Vec2::new(5.0, 10.5)));
        // A concave L: the notch is outside.
        let l = [Vec2::new(0.0, 0.0), Vec2::new(10.0, 0.0), Vec2::new(10.0, 4.0), Vec2::new(4.0, 4.0), Vec2::new(4.0, 10.0), Vec2::new(0.0, 10.0)];
        assert!(inside(&l, Vec2::new(2.0, 8.0)));
        assert!(inside(&l, Vec2::new(8.0, 2.0)));
        assert!(!inside(&l, Vec2::new(8.0, 8.0)));
        // Either winding.
        let rev: Vec<Vec2> = l.iter().rev().copied().collect();
        assert!(inside(&rev, Vec2::new(2.0, 8.0)) && !inside(&rev, Vec2::new(8.0, 8.0)));
    }

    #[test]
    fn later_areas_lie_on_top_and_bad_ones_are_skipped() {
        let (a, skipped) = Areas::parse(
            r#"[
                {"id": "yard", "surface": "earth", "area": [[0, 0], [20, 0], [20, 20], [0, 20]], "cause": "x"},
                {"id": "heap", "surface": "cinders", "area": [[5, 5], [10, 5], [10, 10], [5, 10]]},
                {"id": "line", "surface": "setts", "area": [[0, 0], [1, 1]]}
            ]"#,
        )
        .unwrap();
        assert_eq!((a.len(), skipped), (2, 1));
        assert_eq!(a.at(Vec2::new(2.0, 2.0)), Some("earth"));
        assert_eq!(a.at(Vec2::new(7.0, 7.0)), Some("cinders"));
        assert_eq!(a.at(Vec2::new(30.0, 7.0)), None);
        assert!(Areas::parse("{").is_err());
        // An area is crisp and only mapped surfaces count.
        let g = Ground::with(map(&[("area:cinders", Layer::Cinders)]), a, Streets::default());
        assert_eq!(g.area(Vec2::new(7.0, 7.0)).map(|s| s.layer), Some(Layer::Cinders));
        assert_eq!(g.area(Vec2::new(2.0, 2.0)), None);
    }

    #[test]
    fn a_road_tile_takes_its_nearest_streets_surface() {
        let mut st = Streets::default();
        st.surfaces = vec!["setts".into(), "quay_flags".into()];
        st.add(Vec2::new(0.0, 0.0), Vec2::new(40.0, 0.0), 2.0, 0);
        st.add(Vec2::new(20.0, -30.0), Vec2::new(20.0, 30.0), 3.0, 1);
        assert_eq!(st.at(Vec2::new(5.0, 1.5)), Some("setts"));
        assert_eq!(st.at(Vec2::new(5.0, 2.9)), Some("setts"));
        assert_eq!(st.at(Vec2::new(5.0, 3.2)), None);
        // At the crossing the nearer centre line wins.
        assert_eq!(st.at(Vec2::new(20.3, 0.6)), Some("quay_flags"));
        assert_eq!(st.at(Vec2::new(23.0, 0.4)), Some("setts"));
        assert_eq!(st.at(Vec2::new(21.0, 25.0)), Some("quay_flags"));
        let g = Ground::with(map(&[("street:quay_flags", Layer::QuayFlags), ("class:Road", Layer::Flagstone)]), Areas::default(), st);
        assert_eq!(g.road(Vec2::new(21.0, 25.0), RegionKind::Meadow).map(|s| s.layer), Some(Layer::QuayFlags));
        assert_eq!(g.road(Vec2::new(5.0, 1.0), RegionKind::Meadow).map(|s| s.layer), Some(Layer::Flagstone));
    }

    #[test]
    fn a_tint_leans_the_colour_in_patches() {
        let plain = Surface::new(Layer::Peat, [80, 60, 50], None);
        let tinted = Surface::new(Layer::Peat, [80, 60, 50], Some([140, 60, 120]));
        let p = Vec2::new(3.0, 4.0);
        assert_eq!(plain.colour_at(p, 0.5), scale(plain.colour, 1.0));
        // Somewhere it leans, nowhere past the tint.
        let leans = (0..400).map(|i| Vec2::new(i as f32 * 7.3, i as f32 * 3.1)).map(|q| tinted.colour_at(q, 0.5)[0] - plain.colour_at(q, 0.5)[0]).fold(0.0f32, f32::max);
        assert!(leans > 0.0);
        assert!(leans <= tinted.tint.unwrap()[0] - plain.colour[0] + 1e-6);
    }
}
