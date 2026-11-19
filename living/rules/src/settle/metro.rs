//! The city planner: one city filling most of a land, ringed by its wall (see `docs/FLOORS.md`).
//!
//! The city is laid out from its centre outward:
//! - a central plaza, and arterials running straight from it out through the wall into the
//!   land beyond, ending at the shore where they meet the sea;
//! - ring highways at fixed fractions of the city's radius, split into one road per sector
//!   between neighbouring arterials;
//! - the wall at the edge, with a gate where each arterial crosses it;
//! - wards: the core inside the first ring, and one ward per band between rings and sector
//!   between arterials. Each ward takes the first [`District`] whose band, side toward the sea
//!   and wealth match it, and is one [`Settlement`] of kind town in that district's style;
//! - in each ward, a street grid turned to face the centre, clipped to the ward and to walkable
//!   ground, with a square in the grid cell nearest the ward's middle;
//! - lots along every street and along the ward's side of its highways, chosen by the
//!   district's mix (blended toward its `rich` mix with the ward's wealth), with passages left
//!   through each frontage so courtyards stay reachable, and lamps along the highways.
//!
//! The city's output is the planner's own: settlements, lots, roads and the wall, so hosting,
//! digests and drawing need nothing new. Mechanics only: every size, count and mix is a field of
//! [`MetroParams`]; styles name `buildings.py` kits through [`Style::kit`].

use super::*;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct MetroParams {
    /// Centre (fractions of the side) and mean radius (fraction of half the side).
    pub centre: [f32; 2],
    pub radius: f32,
    /// Irregularity of the edge, as a fraction of the radius.
    pub edge_warp: f32,
    /// How strongly the ground inside is levelled toward the plain (0..1).
    pub flatten: f32,
    /// Ring highways at these fractions of the radius, and their width.
    pub rings: Vec<f32>,
    pub ring_m: f32,
    /// Arterials: how many, their width, and how far past the wall they run (fraction of the
    /// radius).
    pub arterials: u32,
    pub arterial_m: f32,
    pub reach: f32,
    /// Radius of the central plaza.
    pub plaza_m: f32,
    /// The city wall at its edge (None: an open city).
    pub wall: Option<WallSpec>,
    /// The edge keeps this far from the sea.
    pub shore_m: f32,
    /// Lamps along both sides of the highways this far apart (0: none).
    pub lamp_m: f32,
    /// Elevated highway pieces over the arterials and rings inside the wall (props, drawn above
    /// the street; the rules keep the roads at street level).
    pub highways: bool,
    /// Towers on the wall's corners (props).
    pub wall_towers: bool,
    pub districts: Vec<District>,
}

/// What a kind of ward is built like.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct District {
    /// The settlement style ([`Style::buildings`] of a town style).
    pub style: String,
    /// Where it applies: the ward's middle as a fraction of the radius; the cosine of the angle
    /// between the ward's direction and the sea's (1: facing the sea); its wealth (0..1, highest
    /// opposite the sea).
    pub band: [f32; 2],
    pub sea: [f32; 2],
    pub wealth: [f32; 2],
    /// Grid spacing along the ward's radial axis and across it, and how much lines wander off
    /// it (fraction of the spacing).
    pub block_m: [f32; 2],
    pub jitter: f32,
    /// Every n-th grid line is a street; the rest are lanes of `lane_class`.
    pub street_every: u32,
    pub street_m: f32,
    pub lane_m: f32,
    pub lane_class: RoadClass,
    /// Lots: set-back from the street, gaps between neighbours, a passage at least every
    /// `passage_m` along a frontage, and how far their ground may be cut or filled.
    pub setback_m: f32,
    pub gap_m: [f32; 2],
    pub passage_m: f32,
    pub passage_w_m: f32,
    pub level_m: f32,
    /// What stands on the lots, by weight, blended toward `rich` with the ward's wealth.
    pub mix: Vec<(LotKind, f32)>,
    pub rich: Vec<(LotKind, f32)>,
    /// The ward's square, at most this long and wide.
    pub plaza_m: [f32; 2],
    /// Open ground between the buildings is paved (`Road` tiles), else left as it is.
    pub paved: bool,
    /// At most this many wards take the district (0: any number). Wards choose in an order
    /// drawn from the seed, so a district with a quota lands in different sectors per seed.
    pub quota: u32,
    /// Fill the blocks behind the frontages too: interior lots on a grid this many metres apart
    /// (0: frontages only), at least `fill_gap_m` from each other so alleys stay between them.
    pub fill_m: f32,
    pub fill_gap_m: f32,
}

impl Default for District {
    fn default() -> Self {
        Self {
            style: "metro".into(),
            band: [0.0, 1.0],
            sea: [-1.0, 1.0],
            wealth: [0.0, 1.0],
            block_m: [70.0, 55.0],
            jitter: 0.04,
            street_every: 2,
            street_m: 9.0,
            lane_m: 6.0,
            lane_class: RoadClass::Lane,
            setback_m: 0.8,
            gap_m: [0.3, 2.0],
            passage_m: 48.0,
            passage_w_m: 4.0,
            level_m: 3.5,
            mix: vec![(LotKind::Townhouse, 1.0)],
            rich: Vec::new(),
            plaza_m: [40.0, 28.0],
            paved: true,
            quota: 0,
            fill_m: 0.0,
            fill_gap_m: 2.2,
        }
    }
}

impl Default for MetroParams {
    fn default() -> Self {
        let d = District::default;
        Self {
            centre: [0.5, 0.5],
            radius: 0.72,
            edge_warp: 0.06,
            flatten: 0.85,
            rings: vec![0.3, 0.58, 0.82],
            ring_m: 22.0,
            arterials: 8,
            arterial_m: 16.0,
            reach: 0.3,
            plaza_m: 46.0,
            wall: Some(WallSpec { thickness_m: 4.0, height_m: 14.0, tower_m: 120.0, lane_offset_m: 8.0, gate_m: 4.0 }),
            shore_m: 70.0,
            lamp_m: 40.0,
            highways: false,
            wall_towers: false,
            districts: vec![
                // The core: towers round the central plaza, the tallest on the rich side.
                District {
                    band: [0.0, 0.3],
                    block_m: [92.0, 74.0],
                    jitter: 0.02,
                    street_every: 1,
                    street_m: 11.0,
                    gap_m: [0.4, 2.5],
                    passage_m: 60.0,
                    mix: vec![(LotKind::Hall, 0.55), (LotKind::Townhouse, 0.25), (LotKind::Chapel, 0.1), (LotKind::Inn, 0.1)],
                    rich: vec![(LotKind::Hall, 0.5), (LotKind::Chapel, 0.3), (LotKind::Townhouse, 0.1), (LotKind::Inn, 0.1)],
                    plaza_m: [56.0, 40.0],
                    ..d()
                },
                // Works and docks on the sea's side, past the first ring.
                District {
                    style: "works".into(),
                    band: [0.45, 1.0],
                    sea: [0.55, 1.0],
                    block_m: [84.0, 64.0],
                    street_m: 10.0,
                    gap_m: [1.0, 4.0],
                    mix: vec![(LotKind::Workshop, 0.45), (LotKind::Barn, 0.4), (LotKind::House, 0.15)],
                    ..d()
                },
                // Slums at the poor edge: narrow lanes, shacks and stacks.
                District {
                    style: "slum".into(),
                    band: [0.82, 1.0],
                    wealth: [0.0, 0.62],
                    // Narrow stacks are 10-13 m deep: 30 m between lanes fronts them on both sides.
                    block_m: [34.0, 30.0],
                    jitter: 0.3,
                    street_every: 5,
                    street_m: 6.0,
                    lane_m: 3.2,
                    setback_m: 0.3,
                    gap_m: [0.1, 0.9],
                    passage_m: 30.0,
                    passage_w_m: 2.5,
                    level_m: 2.5,
                    mix: vec![(LotKind::House, 0.35), (LotKind::Townhouse, 0.55), (LotKind::MarketStall, 0.06), (LotKind::Workshop, 0.04)],
                    plaza_m: [24.0, 18.0],
                    paved: false,
                    ..d()
                },
                // The inner band: dense blocks and towers.
                District {
                    band: [0.3, 0.58],
                    block_m: [76.0, 58.0],
                    street_every: 2,
                    mix: vec![(LotKind::Townhouse, 0.6), (LotKind::Hall, 0.25), (LotKind::Inn, 0.08), (LotKind::Workshop, 0.07)],
                    rich: vec![(LotKind::Hall, 0.55), (LotKind::Townhouse, 0.35), (LotKind::Chapel, 0.05), (LotKind::Inn, 0.05)],
                    ..d()
                },
                // Everything else: mid-rise blocks.
                District {
                    block_m: [64.0, 48.0],
                    street_every: 3,
                    gap_m: [0.4, 2.5],
                    mix: vec![(LotKind::Townhouse, 0.55), (LotKind::House, 0.25), (LotKind::Workshop, 0.1), (LotKind::Inn, 0.05), (LotKind::Hall, 0.05)],
                    rich: vec![(LotKind::Townhouse, 0.5), (LotKind::Hall, 0.35), (LotKind::Inn, 0.1), (LotKind::House, 0.05)],
                    ..d()
                },
            ],
        }
    }
}

/// A ward: its outline, district and the roads along its sides.
#[derive(Clone, Debug)]
pub(super) struct Ward {
    poly: Vec<V2>,
    district: usize,
    wealth: f32,
    /// Its middle as a fraction of the radius, and the cosine of its bearing to the sea's.
    mid: f32,
    sea_cos: f32,
    /// Highways and arterials along its sides.
    border: Vec<u32>,
    /// Its own streets and lanes.
    streets: Vec<u32>,
}

/// The laid-out city, before its lots.
pub(super) struct City {
    pub centre: V2,
    pub radius: f32,
    pub roads: Vec<Road>,
    pub settlements: Vec<Settlement>,
    pub sites: Vec<Site>,
    pub bounds: Vec<(Vec<f32>, Vec<f32>)>,
    pub walls: Vec<(u16, f32, Vec<V2>)>,
    wards: Vec<Ward>,
}

const EDGE_SAMPLES: usize = 360;

/// The edge's radius by direction: noise, kept off the sea, smoothed.
fn edge(land: &Land, mp: &MetroParams, c: V2, r: f32) -> Vec<f32> {
    let mut rng = Rng(land.seed ^ 0xC17E);
    let (p1, p2) = (rng.f() * std::f32::consts::TAU, rng.f() * std::f32::consts::TAU);
    let raw: Vec<f32> = (0..EDGE_SAMPLES)
        .map(|i| {
            let t = i as f32 / EDGE_SAMPLES as f32 * std::f32::consts::TAU;
            let want = r * (1.0 + mp.edge_warp * (0.6 * (3.0 * t + p1).d_sin() + 0.4 * (5.0 * t + p2).d_sin()));
            let dir = (t.d_cos(), t.d_sin());
            let mut d = 0.0;
            let s = land.size as f32;
            while d < want + mp.shore_m {
                let q = add(c, mul(dir, d));
                if q.0 < 2.0 || q.1 < 2.0 || q.0 > s - 2.0 || q.1 > s - 2.0 || land.water_level(q.0, q.1) <= 0.5 && land.map.at(q.0, q.1) == Terrain::Water {
                    return (d - mp.shore_m).min(want).max(r * 0.35);
                }
                d += 6.0;
            }
            want
        })
        .collect();
    // A moving minimum then a moving average, so the edge bends round a bay without notches.
    let n = EDGE_SAMPLES as isize;
    let at = |v: &[f32], i: isize| v[i.rem_euclid(n) as usize];
    let lo: Vec<f32> = (0..n).map(|i| (-6..=6).map(|d| at(&raw, i + d)).fold(f32::MAX, f32::min)).collect();
    (0..n).map(|i| (-8..=8).map(|d| at(&lo, i + d)).sum::<f32>() / 17.0).collect()
}

fn edge_at(e: &[f32], t: f32) -> f32 {
    let f = t.rem_euclid(std::f32::consts::TAU) / std::f32::consts::TAU * EDGE_SAMPLES as f32;
    let i = f.floor() as usize % EDGE_SAMPLES;
    lerp(e[i], e[(i + 1) % EDGE_SAMPLES], f - f.floor())
}

/// The sea's direction from the centre: the bearing of the nearest sea along rays, if any.
fn sea_bearing(land: &Land, c: V2, reach: f32) -> Option<f32> {
    let mut best: Option<(f32, f32)> = None;
    for i in 0..72 {
        let t = i as f32 / 72.0 * std::f32::consts::TAU;
        let dir = (t.d_cos(), t.d_sin());
        let mut d = 0.0;
        while d < reach {
            let q = add(c, mul(dir, d));
            if q.0 < 0.0 || q.1 < 0.0 || q.0 >= land.size as f32 || q.1 >= land.size as f32 {
                break;
            }
            if land.map.at(q.0, q.1) == Terrain::Water && land.water_level(q.0, q.1) <= 0.5 {
                if best.is_none_or(|b| d < b.0) {
                    best = Some((d, t));
                }
                break;
            }
            d += 12.0;
        }
    }
    best.map(|b| b.1)
}

/// Parameter intervals of segment ab inside a closed polygon.
fn clip(poly: &[V2], a: V2, b: V2) -> Vec<(f32, f32)> {
    let mut ts = vec![0.0, 1.0];
    let n = poly.len();
    for i in 0..n {
        if let Some((t, _)) = seg_intersect(a, b, poly[i], poly[(i + 1) % n]) {
            ts.push(t);
        }
    }
    ts.sort_by(f32::total_cmp);
    ts.dedup_by(|x, y| (*x - *y).abs() < 1e-5);
    let mut out = Vec::new();
    for w in ts.windows(2) {
        let m = add(a, mul(sub(b, a), (w[0] + w[1]) * 0.5));
        if poly_contains(poly, m) {
            out.push((w[0], w[1]));
        }
    }
    out
}

fn dist_to_poly_edge(poly: &[V2], p: V2) -> f32 {
    let n = poly.len();
    (0..n).map(|i| seg_near(p, poly[i], poly[(i + 1) % n]).0).fold(f32::MAX, f32::min)
}

fn centroid(poly: &[V2]) -> V2 {
    let (mut cx, mut cy, mut a) = (0.0, 0.0, 0.0);
    let n = poly.len();
    for i in 0..n {
        let (p, q) = (poly[i], poly[(i + 1) % n]);
        let c = cross(p, q);
        a += c;
        cx += (p.0 + q.0) * c;
        cy += (p.1 + q.1) * c;
    }
    if a.abs() < 1e-6 {
        return poly[0];
    }
    (cx / (3.0 * a), cy / (3.0 * a))
}

/// Clear the city's ground as settlements clear theirs: rock outcrops become dirt and trees
/// grass, within the edge's largest reach.
pub(super) fn clear(land: &mut Land, mp: &MetroParams) {
    let s = land.size as f32;
    let (c, r) = ((mp.centre[0] * s, mp.centre[1] * s), mp.radius * s * 0.5 * (1.0 + mp.edge_warp) + 30.0);
    let w = land.size as i32;
    let (x0, x1) = (((c.0 - r).floor() as i32).max(0), ((c.0 + r).ceil() as i32).min(w - 1));
    let (y0, y1) = (((c.1 - r).floor() as i32).max(0), ((c.1 + r).ceil() as i32).min(w - 1));
    for y in y0..=y1 {
        for x in x0..=x1 {
            if dist((x as f32 + 0.5, y as f32 + 0.5), c) > r {
                continue;
            }
            let k = (y * w + x) as usize;
            land.map.tiles[k] = match Terrain::from_u8(land.map.tiles[k]) {
                Terrain::Rock => Terrain::Dirt as u8,
                Terrain::Forest => Terrain::Grass as u8,
                t => t as u8,
            };
        }
    }
}

/// Pave the open ground of every paved ward (`Road` tiles), round its lots' footprints, which
/// keep their ground so buildings block there.
pub(super) fn pave(land: &mut Land, city: &City, mp: &MetroParams, lots: &[Lot]) {
    let w = land.size as usize;
    let mut keep = vec![false; w * w];
    for l in lots {
        let r = l.rect();
        let (lo, hi) = r.bbox(0.5);
        for y in (lo.1.floor().max(0.0) as usize)..=(hi.1.ceil() as usize).min(w - 1) {
            for x in (lo.0.floor().max(0.0) as usize)..=(hi.0.ceil() as usize).min(w - 1) {
                if r.outside((x as f32 + 0.5, y as f32 + 0.5)) <= 0.5 {
                    keep[y * w + x] = true;
                }
            }
        }
    }
    for ward in &city.wards {
        if !mp.districts[ward.district].paved {
            continue;
        }
        let poly = &ward.poly;
        let y0 = poly.iter().map(|p| p.1).fold(f32::MAX, f32::min).floor().max(0.0) as usize;
        let y1 = (poly.iter().map(|p| p.1).fold(f32::MIN, f32::max).ceil() as usize).min(w - 1);
        let n = poly.len();
        let mut xs: Vec<f32> = Vec::new();
        for y in y0..=y1 {
            let fy = y as f32 + 0.5;
            xs.clear();
            for i in 0..n {
                let (a, b) = (poly[i], poly[(i + 1) % n]);
                if (a.1 > fy) != (b.1 > fy) {
                    xs.push(a.0 + (fy - a.1) / (b.1 - a.1) * (b.0 - a.0));
                }
            }
            xs.sort_by(f32::total_cmp);
            for pair in xs.chunks(2) {
                if pair.len() < 2 {
                    continue;
                }
                let (xa, xb) = ((pair[0] - 0.5).ceil().max(0.0) as usize, ((pair[1] - 0.5).floor() as usize).min(w - 1));
                for x in xa..=xb {
                    let k = y * w + x;
                    if keep[k] {
                        continue;
                    }
                    if matches!(Terrain::from_u8(land.map.tiles[k]), Terrain::Grass | Terrain::Dirt | Terrain::Sand | Terrain::Forest) {
                        land.map.tiles[k] = Terrain::Road as u8;
                    }
                }
            }
        }
    }
}

/// Lay out the city's highways, wards, streets and squares. Ward sites are numbered from
/// `land.sites.len()`; the caller appends [`City::sites`].
pub(super) fn lay_out(land: &Land, mp: &MetroParams) -> City {
    let s = land.size as f32;
    let c = (mp.centre[0] * s, mp.centre[1] * s);
    let r = mp.radius * s * 0.5;
    let e = edge(land, mp, c, r);
    let base = land.sites.len();
    let mut rng = Rng(land.seed ^ 0x3E7C);
    let tau = std::f32::consts::TAU;
    let na = mp.arterials.max(3) as usize;
    let a0 = rng.f() * tau;
    let ang: Vec<f32> = (0..na).map(|j| a0 + j as f32 * tau / na as f32 + (rng.f() - 0.5) * 0.12).collect();
    let sea = sea_bearing(land, c, r * 1.6);
    let ray = |t: f32, d: f32| add(c, mul((t.d_cos(), t.d_sin()), d));
    let walk = |q: V2| q.0 > 1.0 && q.1 > 1.0 && q.0 < s - 1.0 && q.1 < s - 1.0 && land.map.at(q.0, q.1).walkable();
    let mut roads: Vec<Road> = Vec::new();
    let road = |class, pts: Vec<V2>, w: f32, ends: [RoadEnd; 2], settlement: Option<u16>| {
        let pts = dedup(pts);
        let l = *cumlen(&pts).last().unwrap_or(&0.0);
        Road { class, settlement, points: pts, heights: Vec::new(), width_m: w, crossfall: Vec::new(), ends, length_m: l }
    };
    // Arterials (road ids 0..na): from the central plaza's edge outward, until the ground stops.
    for &t in &ang {
        let out = edge_at(&e, t) * (1.0 + mp.reach);
        let mut pts = Vec::new();
        let mut end = RoadEnd::Free;
        let mut d = mp.plaza_m;
        while d <= out {
            let q = ray(t, d);
            if !walk(q) {
                if land.map.at(q.0, q.1) == Terrain::Water && land.water_level(q.0, q.1) <= 0.5 {
                    end = RoadEnd::Shore;
                }
                break;
            }
            pts.push(q);
            d += 10.0;
        }
        if pts.len() < 2 {
            pts = vec![ray(t, mp.plaza_m), ray(t, mp.plaza_m + 10.0)];
        }
        roads.push(road(RoadClass::Trunk, pts, mp.arterial_m, [RoadEnd::Plaza(0), end], None));
    }
    // Ring highways (one road per ring and sector): ids na + k * na + j.
    for &f in &mp.rings {
        for j in 0..na {
            let (t0, mut t1) = (ang[j], ang[(j + 1) % na]);
            if t1 <= t0 {
                t1 += tau;
            }
            let steps = (((t1 - t0) * f * r) / 12.0).ceil().max(2.0) as usize;
            let pts: Vec<V2> = (0..=steps).map(|i| {
                let t = lerp(t0, t1, i as f32 / steps as f32);
                ray(t, f * edge_at(&e, t))
            }).collect();
            roads.push(road(RoadClass::Trunk, pts, mp.ring_m, [RoadEnd::Road(j as u32), RoadEnd::Road(((j + 1) % na) as u32)], None));
        }
    }
    // The wall, at the edge, with a gate where each arterial crosses it.
    let wall_hw = mp.wall.as_ref().map_or(0.0, |w| w.thickness_m * 0.5);
    let wall = mp.wall.as_ref().map(|ws| {
        let steps = (tau * r / 10.0).ceil() as usize;
        let ring: Vec<V2> = (0..steps).map(|i| {
            let t = a0 + i as f32 / steps as f32 * tau;
            ray(t, edge_at(&e, t))
        }).collect();
        let corners: Vec<V2> = ring.iter().step_by(((ws.tower_m / 10.0).round() as usize).max(1)).copied().collect();
        let gates: Vec<Gate> = ang.iter().enumerate().map(|(j, &t)| Gate { at: ray(t, edge_at(&e, t)), out: (t.d_cos(), t.d_sin()), width_m: mp.arterial_m + 2.0 * ws.gate_m, road: j as u32 }).collect();
        // Runs: the ring cut at gates and where it would stand off dry land.
        let mut runs: Vec<Vec<V2>> = Vec::new();
        let mut cur: Vec<V2> = Vec::new();
        for i in 0..=steps {
            let q = ring[i % steps];
            let gap = gates.iter().any(|g| dist(g.at, q) < g.width_m * 0.5 + 1.0) || !walk(q);
            if gap {
                if cur.len() >= 2 {
                    runs.push(std::mem::take(&mut cur));
                }
                cur.clear();
            } else {
                cur.push(q);
            }
        }
        if cur.len() >= 2 {
            runs.push(cur);
        }
        Wall { ring, corners, runs, gates, height_m: ws.height_m, thickness_m: ws.thickness_m }
    });
    // Wards: the core, then each band and sector.
    let mut bands = vec![0.0];
    bands.extend(mp.rings.iter().copied());
    bands.push(1.0);
    let mut wards: Vec<Ward> = Vec::new();
    let pick_district = |mid: f32, sea_cos: f32, wealth: f32| {
        mp.districts.iter().position(|d| (d.band[0]..=d.band[1]).contains(&mid) && (d.sea[0]..=d.sea[1]).contains(&sea_cos) && (d.wealth[0]..=d.wealth[1]).contains(&wealth)).unwrap_or(mp.districts.len().saturating_sub(1))
    };
    {
        let f = bands[1];
        let steps = (tau * f * r / 12.0).ceil() as usize;
        let poly: Vec<V2> = (0..steps).map(|i| {
            let t = a0 + i as f32 / steps as f32 * tau;
            ray(t, f * edge_at(&e, t))
        }).collect();
        let border: Vec<u32> = (0..na as u32).chain((0..na as u32).map(|j| na as u32 + j)).collect();
        wards.push(Ward { poly, district: 0, wealth: 0.5, mid: f * 0.5, sea_cos: 0.0, border, streets: Vec::new() });
    }
    for b in 1..bands.len() - 1 {
        let (f0, f1) = (bands[b], bands[b + 1]);
        let outer_inset = if b == bands.len() - 2 { wall_hw + 3.0 } else { 0.0 };
        for j in 0..na {
            let (t0, mut t1) = (ang[j], ang[(j + 1) % na]);
            if t1 <= t0 {
                t1 += tau;
            }
            let steps = (((t1 - t0) * f1 * r) / 12.0).ceil().max(2.0) as usize;
            let mut poly: Vec<V2> = (0..=steps).map(|i| {
                let t = lerp(t0, t1, i as f32 / steps as f32);
                ray(t, f0 * edge_at(&e, t))
            }).collect();
            for i in (0..=steps).rev() {
                let t = lerp(t0, t1, i as f32 / steps as f32);
                poly.push(ray(t, f1 * edge_at(&e, t) - outer_inset));
            }
            let tm = (t0 + t1) * 0.5;
            let sea_cos = sea.map_or(0.0, |sb| (tm - sb).d_cos());
            let wealth = (0.5 - 0.5 * sea_cos + 0.15 * (rng.f() - 0.5)).clamp(0.0, 1.0);
            let mut border = vec![j as u32, ((j + 1) % na) as u32];
            // The rings on its inner and outer side (b - 1 and b in `mp.rings`).
            for k in [b as isize - 1, b as isize] {
                if k >= 0 && (k as usize) < mp.rings.len() {
                    border.push((na + k as usize * na + j) as u32);
                }
            }
            wards.push(Ward { poly, district: 0, wealth, mid: (f0 + f1) * 0.5, sea_cos, border, streets: Vec::new() });
        }
    }
    // Districts: the core first, then the other wards in an order drawn from the seed; each
    // takes the first district that fits it and has room in its quota.
    {
        let mut taken = vec![0u32; mp.districts.len()];
        let mut order: Vec<usize> = (1..wards.len()).collect();
        let mut keys: Vec<f32> = (0..wards.len()).map(|_| rng.f()).collect();
        keys[0] = -1.0;
        order.insert(0, 0);
        order.sort_by(|&a, &b| keys[a].total_cmp(&keys[b]));
        for wi in order {
            let (mid, sea_cos, wealth) = (wards[wi].mid, wards[wi].sea_cos, wards[wi].wealth);
            let fits = |d: &District| (d.band[0]..=d.band[1]).contains(&mid) && (d.sea[0]..=d.sea[1]).contains(&sea_cos) && (d.wealth[0]..=d.wealth[1]).contains(&wealth);
            let di = (0..mp.districts.len()).find(|&i| fits(&mp.districts[i]) && (mp.districts[i].quota == 0 || taken[i] < mp.districts[i].quota)).unwrap_or_else(|| pick_district(mid, sea_cos, wealth));
            taken[di] += 1;
            wards[wi].district = di;
        }
    }
    // Streets, squares and settlements, ward by ward.
    let mut settlements: Vec<Settlement> = Vec::new();
    let mut sites: Vec<Site> = Vec::new();
    let mut bounds = Vec::new();
    // Enough sides that the arterials, which start on the circle, meet its outline.
    let sides = ((mp.plaza_m / 3.0).ceil() as usize).max(16);
    let core_plaza: Vec<V2> = (0..sides).map(|i| ray(i as f32 / sides as f32 * tau + a0, mp.plaza_m)).collect();
    for wi in 0..wards.len() {
        let w = wards[wi].clone();
        let d = &mp.districts[w.district];
        let idx = wi as u16;
        let mut wr = Rng(land.seed ^ 0x3A2D ^ (wi as u64) << 12);
        let wc = centroid(&w.poly);
        let up = if wi == 0 { (a0.d_cos(), a0.d_sin()) } else { norm(sub(wc, c)) };
        let axis = rot(up, (wr.f() - 0.5) * 0.25);
        let across = perp(axis);
        let ext = w.poly.iter().map(|q| dist(*q, wc)).fold(0.0, f32::max) + 10.0;
        let mut lines: Vec<(V2, V2, f32, RoadClass)> = Vec::new();
        for (dir, step, normal) in [(axis, d.block_m[1], across), (across, d.block_m[0], axis)] {
            let n = (ext / step).ceil() as i32;
            for i in -n..=n {
                let o = i as f32 * step + (wr.f() - 0.5) * d.jitter * step;
                let street = d.street_every <= 1 || i.rem_euclid(d.street_every as i32) == 0;
                let (wdt, class) = if street { (d.street_m, RoadClass::Street) } else { (d.lane_m, d.lane_class) };
                // Slum lanes bend a little.
                let bend = rot(dir, (wr.f() - 0.5) * d.jitter * 0.3);
                let m = add(wc, mul(normal, o));
                lines.push((sub(m, mul(bend, ext)), add(m, mul(bend, ext)), wdt, class));
            }
        }
        // The square: the grid cell nearest the ward's middle, between its lines.
        let mut plaza: Vec<V2> = Vec::new();
        {
            let (sa, sb) = (d.block_m[1], d.block_m[0]);
            let half = (((sb - d.street_m) * 0.5 - 2.0).min(d.plaza_m[0] * 0.5), ((sa - d.street_m) * 0.5 - 2.0).min(d.plaza_m[1] * 0.5));
            let mut best: Option<(f32, V2)> = None;
            if wi == 0 {
                plaza = core_plaza.clone();
            } else {
                for i in -3..=3 {
                    for k in -3..=3 {
                        let q = add(wc, add(mul(across, (i as f32 + 0.5) * sa), mul(axis, (k as f32 + 0.5) * sb)));
                        if !poly_contains(&w.poly, q) || dist_to_poly_edge(&w.poly, q) < half.0.max(half.1) + 12.0 || !walk(q) {
                            continue;
                        }
                        let dd = dist(q, wc);
                        if best.is_none_or(|b| dd < b.0) {
                            best = Some((dd, q));
                        }
                    }
                }
                if let Some((_, q)) = best {
                    let (u, v) = (mul(axis, half.0), mul(across, half.1));
                    plaza = vec![sub(sub(q, u), v), add(sub(q, v), u), add(add(q, u), v), sub(add(q, v), u)];
                    if poly_area(&plaza) < 0.0 {
                        plaza.reverse();
                    }
                }
            }
        }
        if plaza.is_empty() {
            // No room for a square: a small one at the middle.
            let (u, v) = (mul(axis, 6.0), mul(across, 6.0));
            plaza = vec![sub(sub(wc, u), v), add(sub(wc, v), u), add(add(wc, u), v), sub(add(wc, v), u)];
            if poly_area(&plaza) < 0.0 {
                plaza.reverse();
            }
        }
        let pc = centroid(&plaza);
        // Clip each line to the ward, to dry walkable ground and round the core's plaza.
        let mut streets = Vec::new();
        for (a, b, wdt, class) in lines {
            for (t0, t1) in clip(&w.poly, a, b) {
                let (pa, pb) = (add(a, mul(sub(b, a), t0)), add(a, mul(sub(b, a), t1)));
                let l = dist(pa, pb);
                let mid = mul(add(pa, pb), 0.5);
                if l < 20.0 || dist_to_poly_edge(&w.poly, mid) < wdt * 0.5 + 9.0 {
                    continue;
                }
                // Pieces on walkable ground, outside the square.
                let n = (l / 2.0).ceil() as usize;
                let mut piece: Vec<V2> = Vec::new();
                let mut pieces: Vec<(Vec<V2>, bool, bool)> = Vec::new();
                let mut start_edge = true;
                for i in 0..=n {
                    let q = add(pa, mul(sub(pb, pa), i as f32 / n as f32));
                    let ok = walk(q) && !poly_contains(&plaza, q);
                    if ok {
                        piece.push(q);
                    } else {
                        if piece.len() >= 2 {
                            pieces.push((std::mem::take(&mut piece), start_edge, false));
                        }
                        piece.clear();
                        start_edge = false;
                    }
                }
                if piece.len() >= 2 {
                    pieces.push((piece, start_edge, true));
                }
                for (pts, s_edge, e_edge) in pieces {
                    let pts = vec![pts[0], *pts.last().unwrap()];
                    if dist(pts[0], pts[1]) < 16.0 {
                        continue;
                    }
                    let end_of = |q: V2, on_edge: bool| -> (RoadEnd, V2) {
                        if poly_outside(&plaza, q) < 3.0 {
                            // On the square's edge exactly.
                            let mut ring = plaza.clone();
                            ring.push(plaza[0]);
                            return (RoadEnd::Plaza(idx), nearest_on(&ring, q).3);
                        }
                        if on_edge {
                            let best = w.border.iter().map(|&rid| (rid, nearest_on(&roads[rid as usize].points, q))).min_by(|x, y| x.1 .0.total_cmp(&y.1 .0));
                            if let Some((rid, (dd, _, _, np))) = best {
                                if dd < 4.0 {
                                    return (RoadEnd::Road(rid), np);
                                }
                            }
                        }
                        (RoadEnd::Free, q)
                    };
                    let (ea, qa) = end_of(pts[0], s_edge);
                    let (eb, qb) = end_of(pts[1], e_edge);
                    let pts = resample(&[qa, qb], 12.0);
                    let id = roads.len() as u32;
                    roads.push(road(class, pts, wdt, [ea, eb], Some(idx)));
                    streets.push(id);
                }
            }
        }
        // A short street from the square to the nearest street, so the square is on the
        // network (the core's arterials already start at its plaza).
        if wi > 0 {
            let near = streets.iter().map(|&rid| (rid, nearest_on(&roads[rid as usize].points, pc))).min_by(|x, y| x.1 .0.total_cmp(&y.1 .0));
            if let Some((rid, (_, _, _, np))) = near {
                let dir = norm(sub(np, pc));
                let mut t = 0.0;
                while t < 200.0 && poly_contains(&plaza, add(pc, mul(dir, t))) {
                    t += 0.25;
                }
                let edge = add(pc, mul(dir, (t - 1.0).max(0.0)));
                if dist(edge, np) > 1.0 {
                    let wdt = d.lane_m;
                    let id = roads.len() as u32;
                    roads.push(road(d.lane_class, vec![edge, np], wdt, [RoadEnd::Plaza(idx), RoadEnd::Road(rid)], Some(idx)));
                    streets.push(id);
                }
            }
        }
        wards[wi].streets = streets.clone();
        let area = poly_area(&w.poly).abs();
        let radius_m = (area / std::f32::consts::PI).sqrt();
        let floor = land.height(pc.0, pc.1);
        let si = (base + wi) as u16;
        sites.push(Site { kind: SiteKind::Town, x: pc.0, y: pc.1, radius_m, ground_m: floor, scale: 1.0, facing: 0.0, region: land.kind_at(pc.0, pc.1), flatten: 0.0, style: Some(d.style.clone()), ward: true, plan: None });
        let mut set_roads = streets;
        if wi == 0 {
            set_roads.extend(0..na as u32);
        }
        settlements.push(Settlement {
            site: si,
            kind: SiteKind::Town,
            style: d.style.clone(),
            centre: pc,
            scale: 1.0,
            radius_m,
            plaza: Plaza { centre: pc, points: plaza, floor_m: floor, paved: true },
            wall: if wi == 0 { wall.clone() } else { None },
            lots: (0, 0),
            landmark: None,
            roads: set_roads,
            terrace_m: 0.0,
            planned: false,
        });
        bounds.push((vec![radius_m; 64], vec![radius_m; 64]));
    }
    let walls = wall.map(|w| vec![(0u16, w.thickness_m * 0.5, w.ring)]).unwrap_or_default();
    City { centre: c, radius: e.iter().sum::<f32>() / e.len() as f32, roads, settlements, sites, bounds, walls, wards }
}

/// Lots of every ward, in ward order (each ward's lots are one range), with lamps along its
/// highways. Runs on a planner whose roads have their profiles.
impl City {
    /// How many wards the city has.
    pub(super) fn wards(&self) -> usize {
        self.wards.len()
    }
}

/// Lots of ward `wi`. Wards are planned one at a time, in order, each from its own random
/// stream, so a staged plan gives the same city as one pass.
pub(super) fn ward_lots(pl: &mut Plan, city: &City, mp: &MetroParams, wi: usize) {
    let land = pl.land;
    {
        let w = &city.wards[wi];
        let d = &mp.districts[w.district];
        let idx = wi as u16;
        let style = pl.settlements[wi].style.clone();
        let mut rng = Rng(land.seed ^ 0x107E ^ (wi as u64) << 10);
        let check = Check { road_clear: 0.3, plaza_clear: 1.0, min_gap: 99.0, water: 2.0, cut: d.level_m, fill: d.level_m, level: true, on_wall: false, in_plaza: None, step: 1.5 };
        // Weights: the district's mix, blended toward its rich mix by the ward's wealth.
        let mut weights: Vec<(LotKind, f32)> = d.mix.iter().map(|&(k, v)| (k, v * if d.rich.is_empty() { 1.0 } else { 1.0 - w.wealth })).collect();
        for &(k, v) in &d.rich {
            match weights.iter_mut().find(|x| x.0 == k) {
                Some(x) => x.1 += v * w.wealth,
                None => weights.push((k, v * w.wealth)),
            }
        }
        let total: f32 = weights.iter().map(|x| x.1).sum::<f32>().max(1e-6);
        let draw = |rng: &mut Rng| {
            let mut t = rng.f() * total;
            for &(k, v) in &weights {
                if t < v {
                    return k;
                }
                t -= v;
            }
            weights.last().map_or(LotKind::Townhouse, |x| x.0)
        };
        // Lamps on the ward's side of its highways.
        if mp.lamp_m > 0.0 {
            let lamp = Check { level: false, road_clear: 0.05, water: 1.0, step: 0.5, ..check };
            for &rid in &w.border {
                let (pts, hw) = (pl.roads[rid as usize].points.clone(), pl.roads[rid as usize].width_m * 0.5);
                let cl = cumlen(&pts);
                let total = *cl.last().unwrap();
                let mut s = mp.lamp_m * 0.5;
                while s < total {
                    let (q, t) = at_s(&pts, &cl, s);
                    s += mp.lamp_m;
                    for side in [1.0f32, -1.0] {
                        let n = mul(perp(t), side);
                        let (m, lw, ld) = pl.thing(&style, LotKind::Lamp, &mut rng, 0.05);
                        let cpos = add(q, mul(n, hw + ld * 0.5 + 0.4));
                        if !poly_contains(&w.poly, cpos) {
                            continue;
                        }
                        let lot = Lot { settlement: idx, kind: LotKind::Lamp, centre: cpos, width_m: lw, depth_m: ld, front: mul(n, -1.0), yaw: 0.0, floor_m: 0.0, frontage: Frontage::Road(rid), landmark: false, model_file: None, height_m: 0.0 };
                        let lot = pl.dressed(lot, m);
                        let _ = pl.try_lot(lot, 0.3, &lamp);
                    }
                }
            }
        }
        // The core's landmark (its style's: an arcology) in the middle of the central square.
        if wi == 0 {
            if let Some(lk) = pl.p.styles.iter().find(|st| st.buildings == style).and_then(|st| st.landmark) {
                let pc = pl.settlements[wi].plaza.centre;
                let front = city.roads.first().and_then(|r| r.points.first()).map_or((0.0, 1.0), |q| norm(sub(*q, pc)));
                if let Some(mi) = pl.pick(&style, lk, &mut rng, 0, false, f32::MAX) {
                    let (lw, ld) = pl.dims(&style, lk, Some(mi), 0.15);
                    // It stands on the square's level ground (pads skip lots inside a plaza).
                    let lot = Lot { settlement: idx, kind: lk, centre: pc, width_m: lw, depth_m: ld, front, yaw: 0.0, floor_m: pl.settlements[wi].plaza.floor_m, frontage: Frontage::Plaza(idx), landmark: true, model_file: None, height_m: 0.0 };
                    let lot = pl.dressed(lot, Some(mi));
                    if let Some(li) = pl.try_lot(lot, 0.5, &Check { in_plaza: Some(pc), level: true, cut: 40.0, fill: 40.0, water: 2.0, ..check }) {
                        pl.settlements[wi].landmark = Some(li);
                    }
                }
            }
        }
        // Lots along the ward's highways (its side only), then along its own streets.
        let lines: Vec<(u32, bool)> = w.border.iter().map(|&r| (r, true)).chain(w.streets.iter().map(|&r| (r, false))).collect();
        for (rid, border) in lines {
            let (pts, hw) = (pl.roads[rid as usize].points.clone(), pl.roads[rid as usize].width_m * 0.5);
            let cl = cumlen(&pts);
            let total = *cl.last().unwrap();
            for side in [1.0f32, -1.0] {
                let mut s = 2.0 + rng.f() * 4.0;
                let mut since = rng.f() * d.passage_m;
                while s < total - 2.0 {
                    if since >= d.passage_m {
                        s += d.passage_w_m;
                        since = 0.0;
                        continue;
                    }
                    let kind = draw(&mut rng);
                    let m = pl.pick(&style, kind, &mut rng, 0, false, f32::MAX);
                    let (lw, ld) = pl.dims(&style, kind, m, 0.15);
                    let (q, t) = at_s(&pts, &cl, (s + lw * 0.5).min(total));
                    let n = mul(perp(t), side);
                    let centre = add(q, mul(n, hw + d.setback_m + ld * 0.5));
                    let gap = rng.range(d.gap_m);
                    let rect = Rect { c: centre, f: mul(n, -1.0), hw: lw * 0.5, hd: ld * 0.5 };
                    let inside = poly_contains(&w.poly, centre) && rect.corners().iter().all(|k| poly_contains(&w.poly, *k));
                    if border && !inside {
                        // A highway's far side belongs to the next ward.
                        break;
                    }
                    if inside {
                        let lot = Lot { settlement: idx, kind, centre, width_m: lw, depth_m: ld, front: mul(n, -1.0), yaw: 0.0, floor_m: land.height(centre.0, centre.1), frontage: Frontage::Road(rid), landmark: false, model_file: None, height_m: 0.0 };
                        let lot = pl.dressed(lot, m);
                        if pl.try_lot(lot, gap, &check).is_some() {
                            s += lw + gap;
                            since += lw + gap;
                            continue;
                        }
                    }
                    s += 1.5;
                    since += 1.5;
                }
            }
        }
    }
}

/// Rows of the fill grid per step: each step stays well inside a reducer's budget.
const FILL_ROWS: usize = 12;

/// The steps ward `wi`'s back-fill takes (0 without one).
pub(super) fn fill_steps(city: &City, mp: &MetroParams, wi: usize) -> usize {
    let w = &city.wards[wi];
    let d = &mp.districts[w.district];
    if d.fill_m <= 0.0 {
        return 0;
    }
    let (lo, hi) = (w.poly.iter().map(|q| q.1).fold(f32::MAX, f32::min), w.poly.iter().map(|q| q.1).fold(f32::MIN, f32::max));
    (((hi - lo) / d.fill_m).ceil() as usize).div_ceil(FILL_ROWS).max(1)
}

/// One step of ward `wi`'s back-fill: the blocks behind the frontages, small lots on a
/// jittered grid (rows `step × FILL_ROWS` onward), each facing its nearest street and kept
/// apart so alleys run between them. Each step draws from its own random stream, so the city
/// is the same however its steps fall.
pub(super) fn ward_fill(pl: &mut Plan, city: &City, mp: &MetroParams, wi: usize, step: usize) {
    let land = pl.land;
    let w = &city.wards[wi];
    let d = &mp.districts[w.district];
    let idx = wi as u16;
    let style = pl.settlements[wi].style.clone();
    let mut rng = Rng(land.seed ^ 0xF111 ^ (wi as u64) << 10 ^ (step as u64) << 32);
    let check = Check { road_clear: 0.3, plaza_clear: 1.0, min_gap: d.fill_gap_m, water: 2.0, cut: d.level_m, fill: d.level_m, level: true, on_wall: false, in_plaza: None, step: 1.5 };
    let total: f32 = d.mix.iter().map(|x| x.1).sum::<f32>().max(1e-6);
    let (lo, hi) = (
        (w.poly.iter().map(|q| q.0).fold(f32::MAX, f32::min), w.poly.iter().map(|q| q.1).fold(f32::MAX, f32::min)),
        (w.poly.iter().map(|q| q.0).fold(f32::MIN, f32::max), w.poly.iter().map(|q| q.1).fold(f32::MIN, f32::max)),
    );
    let mut near = Vec::new();
    for row in step * FILL_ROWS..(step + 1) * FILL_ROWS {
        let y = lo.1 + d.fill_m * (row as f32 + 0.5);
        if y >= hi.1 {
            break;
        }
        let mut x = lo.0 + d.fill_m * 0.5;
        while x < hi.0 {
            let q = (x + (rng.f() - 0.5) * d.fill_m * 0.5, y + (rng.f() - 0.5) * d.fill_m * 0.5);
            x += d.fill_m;
            if !poly_contains(&w.poly, q) || dist_to_poly_edge(&w.poly, q) < 8.0 {
                continue;
            }
            // The nearest of the ward's own streets, from the road buckets near the point.
            let r = d.fill_m * 3.0;
            pl.road_b.query((q.0 - r, q.1 - r), (q.0 + r, q.1 + r), &mut near);
            let Some((rid, (dd, _, _, np))) = near.iter().copied().filter(|&rid| pl.roads[rid as usize].settlement == Some(idx)).map(|rid| (rid, nearest_on(&pl.roads[rid as usize].points, q))).min_by(|a, b| a.1 .0.total_cmp(&b.1 .0)) else { continue };
            if dd < 6.0 {
                continue;
            }
            let mut t = rng.f() * total;
            let kind = d.mix.iter().find(|&&(_, v)| {
                let hit = t < v;
                t -= v;
                hit
            }).map_or(LotKind::House, |x| x.0);
            let m = pl.pick(&style, kind, &mut rng, 0, false, d.fill_m);
            let (lw, ld) = pl.dims(&style, kind, m, 0.15);
            let lot = Lot { settlement: idx, kind, centre: q, width_m: lw, depth_m: ld, front: norm(sub(np, q)), yaw: 0.0, floor_m: land.height(q.0, q.1), frontage: Frontage::Alley(rid), landmark: false, model_file: None, height_m: 0.0 };
            let lot = pl.dressed(lot, m);
            let _ = pl.try_lot(lot, d.fill_gap_m, &check);
        }
    }
}

/// Close ward `wi`'s lots (`start..`): its lot range, and its landmark, the tallest building
/// nearest the square (unless it has one).
pub(super) fn ward_close(pl: &mut Plan, wi: usize, start: u32) {
    pl.settlements[wi].lots = (start, pl.lots.len() as u32);
    if pl.settlements[wi].landmark.is_some() {
        return;
    }
    let pc = pl.settlements[wi].plaza.centre;
    let best = (start..pl.lots.len() as u32).filter(|&i| pl.lots[i as usize].kind.padded()).max_by(|&a, &b| {
        let score = |i: u32| pl.lots[i as usize].height_m - 0.05 * dist(pl.lots[i as usize].centre, pc);
        score(a).total_cmp(&score(b))
    });
    if let Some(b) = best {
        pl.lots[b as usize].landmark = true;
        pl.settlements[wi].landmark = Some(b);
    }
}
