//! Hand-authored settlement plans (`LandParams::plans`, docs/AUTHORED_PLANS.md): a settlement
//! whose ground levels, streets, stairs, square and lots are written in the seed instead of
//! generated. The generator steps aside for it:
//! - the macro relief is stamped toward the plan's levels, and the sea is forced inside its
//!   `sea` polygon ([`stamp_macro`], in `land::hydro_pass`);
//! - the plan is one fixed site whose seed id is the plan's id ([`site`]);
//! - the planner's `Plan` step lays it out as written ([`build`]): its ground (levels at exact
//!   heights with drops between them, [`Ground`]), streets, stairs, square, lots with their
//!   explicit models and heights, and retaining walls along its drops;
//! - the generated streets, lots, stairs, terraces and ornaments leave it alone, and island
//!   roads join its trunk streets where they leave the town.
//!
//! Plans are written in their own frame (x east, y north, metres from `origin`, turned by
//! `rotation_deg`) and converted to the land's axes (x east, y south) when they are resolved,
//! with [`crate::det`] trigonometry only, so the authority and clients derive the same land.
//! [`validate`] refuses a plan the generator cannot honour before anything is written. Fields
//! the engine does not read (wear, door colours, keepsakes for the asset generator) are ignored
//! by serde and are not digested.

use super::*;

// ------------------------------------------------------------------------------------------
// The seed format (the plan's own frame)

/// One authored settlement.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlanSpec {
    /// The settlement's seed id: a seed's `towns[].site` names it (`living-authority`'s
    /// `match_seed`), like `town` or `steampunk_town` for generated sites.
    pub id: String,
    #[serde(default = "town")]
    pub kind: SiteKind,
    /// The `settlement.style`: the client's environment and asset folder (`env_of`).
    pub style: String,
    /// Where the plan's (0, 0) lies on the land (land metres, x east, y south).
    pub origin: [f32; 2],
    /// The compass bearing the plan's north (+y) points to on the land, clockwise in degrees.
    #[serde(default)]
    pub rotation_deg: f32,
    /// Inhabitants' height relative to a 1.75 m adult.
    #[serde(default = "one")]
    pub scale: f32,
    /// Width of the drop from a level down to a lower one (metres): the ground falls inside the
    /// lower level, along its edge.
    #[serde(default = "drop_m")]
    pub drop_m: f32,
    /// Width over which the plan's outer edge blends into the natural ground.
    #[serde(default = "skirt_m")]
    pub skirt_m: f32,
    /// How far beyond the levels the land's coarse relief is pulled toward them, so the ground
    /// round the town meets it gently.
    #[serde(default = "blend_m")]
    pub blend_m: f32,
    /// Depth of the sea floor stamped inside `sea` (metres below sea level).
    #[serde(default = "sea_depth_m")]
    pub sea_depth_m: f32,
    pub levels: Vec<LevelSpec>,
    #[serde(default)]
    pub streets: Vec<StreetSpec>,
    #[serde(default)]
    pub stairs: Vec<StairSpec>,
    pub square: SquareSpec,
    /// A polygon that is sea (a harbour): it must reach the open sea to be sea.
    #[serde(default)]
    pub sea: Vec<[f32; 2]>,
    #[serde(default)]
    pub lots: Vec<LotSpec>,
    /// Resources at authored points (fishing spots on a quay's edge, trees in a copse), in the
    /// plan's frame; they may lie outside its levels. The authority places those of kinds the
    /// rules know when the world is created ([`Laid::resources`]); the others wait, unplaced,
    /// for their kinds.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub resources: Vec<ResourceSpec>,
    /// Structures the authority places when the world is created (a furnace at a mouth, lamps
    /// along a quay, a store), at a point in the plan's frame or at a lot's door or spot, with
    /// the fuel a fire starts burning and the items it holds ([`StructureSpec`]).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub structures: Vec<StructureSpec>,
}

/// A resource at a point ([`PlanSpec::resources`]), with what it holds and regrows when the
/// author says so (else its kind's `max` and `regrow_per_h` in the script). Resources that name
/// the same `pool` draw on one stock, held by the first of them (a fishing ground's spots).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ResourceSpec {
    pub kind: String,
    pub at: [f32; 2],
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max: Option<f32>,
    /// Units it regrows a game hour of growing time (the world's day turns it into real time).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub regrow_per_h: Option<f32>,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub pool: String,
}

/// A structure the plan places ([`PlanSpec::structures`]): `at` a point in the plan's frame, or
/// at a `lot`'s door, or at one of its named `spot`s. A kind the rules do not know is left out
/// and logged when the world is created.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StructureSpec {
    pub kind: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub at: Option<[f32; 2]>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub lot: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub spot: Option<String>,
    /// For a fire that burns fuel (its kind `burns`): the units it starts burning with (0: out),
    /// as a seed's `structures[].fuel`.
    #[serde(default)]
    pub fuel: f32,
    /// Items it holds at the start.
    #[serde(default, skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub contents: std::collections::BTreeMap<String, u32>,
}

/// A ground level: a polygon at an exact height.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LevelSpec {
    pub id: String,
    pub height_m: f32,
    pub area: Vec<[f32; 2]>,
    /// Retaining walls stand along its edges where the ground falls away below it.
    #[serde(default = "yes")]
    pub retaining: bool,
}

/// A street: a polyline on the plan's ground.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StreetSpec {
    #[serde(default)]
    pub id: String,
    pub points: Vec<[f32; 2]>,
    pub width_m: f32,
    /// `trunk` streets are where island roads join the town; they should leave its levels.
    #[serde(default = "street")]
    pub class: RoadClass,
    /// The paving (`setts`, `flags`, `earth`...), for clients; the rules do not read it.
    #[serde(default)]
    pub surface: Option<String>,
    /// The level it runs on: every point must lie on it.
    #[serde(default)]
    pub level: Option<String>,
}

/// A flight of stairs from a lower level (`from`) up to a higher one (`to`).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StairSpec {
    #[serde(default)]
    pub id: String,
    pub from: String,
    pub to: String,
    /// The middle of its foot (on `from`) and of its head (on `to`).
    pub foot: [f32; 2],
    pub head: [f32; 2],
    #[serde(default = "stair_w")]
    pub width_m: f32,
    /// What the author means it to climb; refused when the levels it joins differ by more than
    /// 5 cm from it.
    #[serde(default)]
    pub rise_m: Option<f32>,
    #[serde(default)]
    pub model: Option<String>,
}

/// The settlement's square: where its people gather and newcomers arrive.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SquareSpec {
    pub level: String,
    pub area: Vec<[f32; 2]>,
    #[serde(default = "yes")]
    pub paved: bool,
}

/// A building lot.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LotSpec {
    /// Unique in the plan: residents' homes and named buildings refer to it.
    pub id: String,
    pub kind: LotKind,
    #[serde(default)]
    pub name: Option<String>,
    /// The footprint's centre, its width along the front and depth from front to back.
    pub at: [f32; 2],
    pub size: [f32; 2],
    /// Where its front faces: a bearing in degrees (0 north, 90 east), or `north`, `east`,
    /// `south`, `west`.
    pub facing: Facing,
    pub level: String,
    /// The model under the client's `envs/` (none: the client draws a plain box).
    #[serde(default)]
    pub model: Option<String>,
    /// Its height above the floor (none: 6 m for a building, 0 for a garden or field).
    #[serde(default)]
    pub height_m: Option<f32>,
    #[serde(default)]
    pub landmark: bool,
    /// Named spots at the lot (seats, sides of a stall), in the lot's own frame: metres to the
    /// right of its front's middle as one faces out, and forward from its centre toward the front.
    #[serde(default)]
    pub spots: Vec<SpotSpec>,
    /// Items the structure at its door holds at the start (a store's stock); a lot of a kind
    /// with no structure has nowhere to keep them, and they are left out and logged.
    #[serde(default, skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub contents: std::collections::BTreeMap<String, u32>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SpotSpec {
    pub name: String,
    pub at: [f32; 2],
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Facing {
    Bearing(f32),
    Named(String),
}

fn town() -> SiteKind {
    SiteKind::Town
}
fn one() -> f32 {
    1.0
}
fn yes() -> bool {
    true
}
fn street() -> RoadClass {
    RoadClass::Street
}
fn drop_m() -> f32 {
    0.6
}
fn skirt_m() -> f32 {
    10.0
}
fn blend_m() -> f32 {
    60.0
}
fn sea_depth_m() -> f32 {
    6.0
}
fn stair_w() -> f32 {
    2.4
}

impl Facing {
    fn bearing(&self) -> Result<f32, String> {
        match self {
            Facing::Bearing(b) if b.is_finite() => Ok(*b),
            Facing::Bearing(b) => Err(format!("facing {b}")),
            Facing::Named(n) => match n.as_str() {
                "north" | "n" => Ok(0.0),
                "east" | "e" => Ok(90.0),
                "south" | "s" => Ok(180.0),
                "west" | "w" => Ok(270.0),
                other => Err(format!("facing {other:?}: a bearing in degrees or north, east, south, west")),
            },
        }
    }
}

// ------------------------------------------------------------------------------------------
// Resolved: the plan in the land's axes

/// A level on the land.
#[derive(Clone, Debug)]
pub(crate) struct Level {
    pub(crate) id: String,
    pub(crate) floor: f32,
    pub(crate) poly: Vec<V2>,
    pub(crate) lo: V2,
    pub(crate) hi: V2,
    pub(crate) retaining: bool,
}

#[derive(Clone, Debug)]
pub(crate) struct Street {
    pub(crate) points: Vec<V2>,
    pub(crate) width: f32,
    pub(crate) class: RoadClass,
    pub(crate) surface: Option<String>,
}

#[derive(Clone, Debug)]
pub(crate) struct Stair {
    pub(crate) id: String,
    pub(crate) rect: Rect,
    /// Floor of the lower level (at its front, the foot) and the climb to the upper.
    pub(crate) floor: f32,
    pub(crate) rise: f32,
    pub(crate) model: Option<String>,
}

#[derive(Clone, Debug)]
pub(crate) struct PlanLot {
    pub(crate) id: String,
    pub(crate) kind: LotKind,
    pub(crate) name: Option<String>,
    pub(crate) rect: Rect,
    pub(crate) level: usize,
    pub(crate) model: Option<String>,
    pub(crate) height: f32,
    pub(crate) landmark: bool,
    pub(crate) spots: Vec<(String, V2)>,
}

/// A plan converted to the land's axes, its names resolved to indices.
#[derive(Clone, Debug)]
pub(crate) struct Resolved {
    pub(crate) id: String,
    pub(crate) kind: SiteKind,
    pub(crate) style: String,
    pub(crate) scale: f32,
    pub(crate) levels: Vec<Level>,
    pub(crate) streets: Vec<Street>,
    pub(crate) stairs: Vec<Stair>,
    pub(crate) square: Vec<V2>,
    pub(crate) square_level: usize,
    pub(crate) paved: bool,
    pub(crate) sea: Vec<V2>,
    pub(crate) lots: Vec<PlanLot>,
    pub(crate) resources: Vec<LaidResource>,
    pub(crate) structures: Vec<LaidStructure>,
    pub(crate) drop: f32,
    pub(crate) skirt: f32,
    pub(crate) blend: f32,
    pub(crate) sea_depth: f32,
    /// The square's middle, and the radius that holds every level from it.
    pub(crate) centre: V2,
    pub(crate) radius: f32,
    pub(crate) lo: V2,
    pub(crate) hi: V2,
}

/// The plan frame on the land: east and north unit vectors.
struct Frame {
    o: V2,
    e: V2,
    n: V2,
}

impl Frame {
    fn of(s: &PlanSpec) -> Self {
        let r = s.rotation_deg.to_radians();
        let (sn, cs) = r.d_sin_cos();
        // Turning the plan clockwise by r on a map whose y points south.
        Self { o: (s.origin[0], s.origin[1]), e: (cs, sn), n: (sn, -cs) }
    }
    fn pt(&self, p: [f32; 2]) -> V2 {
        add(self.o, add(mul(self.e, p[0]), mul(self.n, p[1])))
    }
    /// A unit direction on the land from a bearing in the plan (0 = plan north, clockwise).
    fn dir(&self, bearing_deg: f32) -> V2 {
        let (sn, cs) = bearing_deg.to_radians().d_sin_cos();
        norm(add(mul(self.e, sn), mul(self.n, cs)))
    }
}

fn bounds(p: &[V2]) -> (V2, V2) {
    let lo = p.iter().fold((f32::MAX, f32::MAX), |m, v| (m.0.min(v.0), m.1.min(v.1)));
    let hi = p.iter().fold((f32::MIN, f32::MIN), |m, v| (m.0.max(v.0), m.1.max(v.1)));
    (lo, hi)
}

fn finite(p: &[[f32; 2]]) -> bool {
    p.iter().all(|q| q[0].is_finite() && q[1].is_finite())
}

/// Convert a plan to the land's axes. Errors name what is wrong (unknown levels, malformed
/// geometry); [`validate`] adds the checks against the land and between the plan's parts.
pub(crate) fn resolve(s: &PlanSpec) -> Result<Resolved, String> {
    let f = Frame::of(s);
    let id = &s.id;
    if id.is_empty() {
        return Err("a plan needs an id".into());
    }
    if s.kind == SiteKind::Cave {
        return Err(format!("plan {id}: kind cave is not a settlement"));
    }
    if s.style.is_empty() {
        return Err(format!("plan {id}: style is empty"));
    }
    for (what, v) in [("origin", s.origin[0]), ("origin", s.origin[1]), ("rotation_deg", s.rotation_deg)] {
        if !v.is_finite() {
            return Err(format!("plan {id}: {what} is not a number"));
        }
    }
    for (what, v) in [("scale", s.scale), ("drop_m", s.drop_m), ("skirt_m", s.skirt_m), ("blend_m", s.blend_m)] {
        if !(v.is_finite() && v > 0.0) {
            return Err(format!("plan {id}: {what} must be above 0"));
        }
    }
    if !(s.sea_depth_m.is_finite() && s.sea_depth_m >= 0.5) {
        return Err(format!("plan {id}: sea_depth_m must be at least 0.5"));
    }
    if s.levels.is_empty() || s.levels.len() > 64 {
        return Err(format!("plan {id}: 1 to 64 levels, not {}", s.levels.len()));
    }
    let mut levels: Vec<Level> = Vec::new();
    for l in &s.levels {
        if l.id.is_empty() || levels.iter().any(|o| o.id == l.id) {
            return Err(format!("plan {id}: level ids must be unique and not empty ({:?})", l.id));
        }
        if l.area.len() < 3 || !finite(&l.area) || !l.height_m.is_finite() {
            return Err(format!("plan {id}: level {} needs a polygon of at least 3 points and a height", l.id));
        }
        let poly: Vec<V2> = l.area.iter().map(|q| f.pt(*q)).collect();
        if poly_area(&poly).abs() < 1.0 {
            return Err(format!("plan {id}: level {} has no area", l.id));
        }
        let (lo, hi) = bounds(&poly);
        levels.push(Level { id: l.id.clone(), floor: l.height_m, poly, lo, hi, retaining: l.retaining });
    }
    let level_of = |name: &str, what: &str| levels.iter().position(|l| l.id == name).ok_or_else(|| format!("plan {id}: {what} names level {name:?}, which the plan does not have"));
    let mut streets = Vec::new();
    for (i, st) in s.streets.iter().enumerate() {
        let name = if st.id.is_empty() { format!("streets[{i}]") } else { format!("street {}", st.id) };
        if st.points.len() < 2 || !finite(&st.points) || !(st.width_m.is_finite() && st.width_m > 0.0) {
            return Err(format!("plan {id}: {name} needs at least 2 points and a width"));
        }
        if !st.id.is_empty() && s.streets.iter().filter(|o| o.id == st.id).count() > 1 {
            return Err(format!("plan {id}: two streets are called {}", st.id));
        }
        let points = dedup(st.points.iter().map(|q| f.pt(*q)).collect());
        if points.len() < 2 {
            return Err(format!("plan {id}: {name} has no length"));
        }
        if let Some(lv) = &st.level {
            let li = level_of(lv, &name)?;
            let lvl = &levels[li];
            if let Some(q) = resample(&points, 1.0).into_iter().find(|q| poly_outside(&lvl.poly, *q) > 0.05) {
                return Err(format!("plan {id}: {name} leaves level {lv} at ({:.1}, {:.1})", q.0, q.1));
            }
        }
        streets.push(Street { points, width: st.width_m, class: st.class, surface: st.surface.clone() });
    }
    let mut stairs = Vec::new();
    for (i, st) in s.stairs.iter().enumerate() {
        let name = if st.id.is_empty() { format!("stairs[{i}]") } else { format!("stair {}", st.id) };
        if !st.id.is_empty() && s.stairs.iter().filter(|o| o.id == st.id).count() > 1 {
            return Err(format!("plan {id}: two stairs are called {}", st.id));
        }
        let (a, b) = (level_of(&st.from, &name)?, level_of(&st.to, &name)?);
        if !finite(&[st.foot, st.head]) || !(st.width_m.is_finite() && st.width_m > 0.0) {
            return Err(format!("plan {id}: {name} needs a foot, a head and a width"));
        }
        let rise = levels[b].floor - levels[a].floor;
        if rise <= 0.05 {
            return Err(format!("plan {id}: {name} climbs from {} ({} m) to {} ({} m): `to` must be the higher level", st.from, levels[a].floor, st.to, levels[b].floor));
        }
        if let Some(r) = st.rise_m {
            if (r - rise).abs() > 0.05 {
                return Err(format!("plan {id}: {name} rises {r} m, but {} and {} are {rise} m apart", st.from, st.to));
            }
        }
        let (foot, head) = (f.pt(st.foot), f.pt(st.head));
        let run = dist(foot, head);
        if run < 0.5 || rise / run > 1.0 {
            return Err(format!("plan {id}: {name} climbs {rise:.2} m over {run:.2} m; a flight may rise at most 1 m per metre"));
        }
        if poly_outside(&levels[a].poly, foot) > 0.05 {
            return Err(format!("plan {id}: the foot of {name} is not on level {}", st.from));
        }
        if poly_outside(&levels[b].poly, head) > 0.05 {
            return Err(format!("plan {id}: the head of {name} is not on level {}", st.to));
        }
        let down = norm(sub(foot, head));
        let rect = Rect { c: mul(add(foot, head), 0.5), f: down, hw: st.width_m * 0.5, hd: run * 0.5 };
        stairs.push(Stair { id: if st.id.is_empty() { name } else { st.id.clone() }, rect, floor: levels[a].floor, rise, model: st.model.clone() });
    }
    if s.square.area.len() < 3 || !finite(&s.square.area) {
        return Err(format!("plan {id}: the square needs a polygon of at least 3 points"));
    }
    let square_level = level_of(&s.square.level, "the square")?;
    let mut square: Vec<V2> = s.square.area.iter().map(|q| f.pt(*q)).collect();
    if poly_area(&square) < 0.0 {
        square.reverse();
    }
    if poly_area(&square) < 4.0 {
        return Err(format!("plan {id}: the square has no area"));
    }
    if let Some(q) = square.iter().find(|q| poly_outside(&levels[square_level].poly, **q) > 0.05) {
        return Err(format!("plan {id}: the square's corner ({:.1}, {:.1}) is not on level {}", q.0, q.1, s.square.level));
    }
    if !s.sea.is_empty() && (s.sea.len() < 3 || !finite(&s.sea)) {
        return Err(format!("plan {id}: the sea needs a polygon of at least 3 points"));
    }
    let sea: Vec<V2> = s.sea.iter().map(|q| f.pt(*q)).collect();
    let mut lots = Vec::new();
    for l in &s.lots {
        if l.id.is_empty() || s.lots.iter().filter(|o| o.id == l.id).count() > 1 {
            return Err(format!("plan {id}: lot ids must be unique and not empty ({:?})", l.id));
        }
        let li = level_of(&l.level, &format!("lot {}", l.id))?;
        if !finite(&[l.at, l.size]) || l.size[0] <= 0.0 || l.size[1] <= 0.0 {
            return Err(format!("plan {id}: lot {} needs a position and a size", l.id));
        }
        let front = f.dir(l.facing.bearing().map_err(|e| format!("plan {id}: lot {}: {e}", l.id))?);
        let rect = Rect { c: f.pt(l.at), f: front, hw: l.size[0] * 0.5, hd: l.size[1] * 0.5 };
        let height = match l.height_m {
            Some(h) if h.is_finite() && h >= 0.0 => h,
            Some(h) => return Err(format!("plan {id}: lot {} height_m {h}", l.id)),
            None if l.kind.model().is_some() => 6.0,
            None => 0.0,
        };
        let right = mul(perp(front), -1.0);
        let mut spots = Vec::new();
        for sp in &l.spots {
            if !finite(&[sp.at]) || sp.name.is_empty() {
                return Err(format!("plan {id}: lot {} has a spot without a name or a place", l.id));
            }
            spots.push((sp.name.clone(), add(rect.c, add(mul(right, sp.at[0]), mul(front, sp.at[1])))));
        }
        lots.push(PlanLot { id: l.id.clone(), kind: l.kind, name: l.name.clone(), rect, level: li, model: l.model.clone().filter(|m| !m.is_empty()), height, landmark: l.landmark, spots });
    }
    let mut resources = Vec::new();
    for (i, rs) in s.resources.iter().enumerate() {
        if rs.kind.is_empty() || !finite(&[rs.at]) {
            return Err(format!("plan {id}: resources[{i}] needs a kind and a place"));
        }
        let ok = |v: Option<f32>| v.map_or(true, |v| v.is_finite() && v >= 0.0);
        if !ok(rs.max) || !ok(rs.regrow_per_h) {
            return Err(format!("plan {id}: resources[{i}] ({}) has a max or regrow_per_h that is not a number of at least 0", rs.kind));
        }
        resources.push(LaidResource { kind: rs.kind.clone(), at: f.pt(rs.at), max: rs.max, regrow_per_h: rs.regrow_per_h, pool: rs.pool.clone() });
    }
    // Structures at a point, a lot's door or a lot's spot; then each lot's own store.
    let door = |l: &PlanLot| add(l.rect.c, mul(l.rect.f, l.rect.hd + 0.5));
    let mut structures = Vec::new();
    for (i, st) in s.structures.iter().enumerate() {
        let name = format!("structures[{i}] ({})", st.kind);
        if st.kind.is_empty() || !(st.fuel.is_finite() && st.fuel >= 0.0) {
            return Err(format!("plan {id}: structures[{i}] needs a kind, and fuel of at least 0"));
        }
        let at = match (&st.at, &st.lot) {
            (Some(q), None) if st.spot.is_none() && finite(&[*q]) => f.pt(*q),
            (None, Some(lid)) => {
                let l = lots.iter().find(|l: &&PlanLot| l.id == *lid).ok_or_else(|| format!("plan {id}: {name} is at lot {lid}, which the plan does not have"))?;
                match &st.spot {
                    None => door(l),
                    Some(sp) => l.spots.iter().find(|(n, _)| n == sp).map(|(_, q)| *q).ok_or_else(|| format!("plan {id}: {name}: lot {lid} has no spot {sp:?}"))?,
                }
            }
            _ => return Err(format!("plan {id}: {name} needs either `at` or a `lot` (with an optional `spot`)")),
        };
        structures.push(LaidStructure { kind: st.kind.clone(), lot: String::new(), at, fuel: st.fuel, contents: st.contents.iter().map(|(k, v)| (k.clone(), *v)).collect() });
    }
    for (l, spec) in lots.iter().zip(&s.lots) {
        if !spec.contents.is_empty() {
            structures.push(LaidStructure { kind: String::new(), lot: l.id.clone(), at: door(l), fuel: 0.0, contents: spec.contents.iter().map(|(k, v)| (k.clone(), *v)).collect() });
        }
    }
    let n = square.len() as f32;
    let centre = square.iter().fold((0.0, 0.0), |a, q| add(a, mul(*q, 1.0 / n)));
    let all: Vec<V2> = levels.iter().flat_map(|l| l.poly.iter().copied()).collect();
    let radius = all.iter().map(|q| dist(*q, centre)).fold(0.0, f32::max);
    let (mut lo, mut hi) = bounds(&all);
    if !sea.is_empty() {
        let (a, b) = bounds(&sea);
        (lo, hi) = ((lo.0.min(a.0), lo.1.min(a.1)), (hi.0.max(b.0), hi.1.max(b.1)));
    }
    Ok(Resolved {
        id: id.clone(),
        kind: s.kind,
        style: s.style.clone(),
        scale: s.scale,
        levels,
        streets,
        stairs,
        square,
        square_level,
        paved: s.square.paved,
        sea,
        lots,
        resources,
        structures,
        drop: s.drop_m,
        skirt: s.skirt_m,
        blend: s.blend_m,
        sea_depth: s.sea_depth_m,
        centre,
        radius,
        lo,
        hi,
    })
}

/// Whether two polygons share area (more than touching along an edge or at a corner).
fn polys_overlap(a: &[V2], b: &[V2]) -> bool {
    let strictly_in = |p: V2, q: &[V2]| {
        poly_contains(q, p) && {
            let n = q.len();
            (0..n).map(|i| seg_near(p, q[i], q[(i + 1) % n]).0).fold(f32::MAX, f32::min) > 0.05
        }
    };
    let centroid = |p: &[V2]| {
        let n = p.len() as f32;
        p.iter().fold((0.0, 0.0), |a, q| add(a, mul(*q, 1.0 / n)))
    };
    if a.iter().any(|p| strictly_in(*p, b)) || b.iter().any(|p| strictly_in(*p, a)) || strictly_in(centroid(a), b) || strictly_in(centroid(b), a) {
        return true;
    }
    // Points just inside each edge (a sliver between two edges that meet at a corner).
    let inner = |p: &[V2]| -> Vec<V2> {
        let ccw = poly_area(p) > 0.0;
        let n = p.len();
        (0..n)
            .flat_map(|i| {
                let (a, b) = (p[i], p[(i + 1) % n]);
                let t = norm(sub(b, a));
                let inward = if ccw { perp(t) } else { mul(perp(t), -1.0) };
                [0.25f32, 0.5, 0.75].map(|u| add(add(a, mul(sub(b, a), u)), mul(inward, 0.2)))
            })
            .collect()
    };
    if inner(a).into_iter().any(|p| strictly_in(p, b)) || inner(b).into_iter().any(|p| strictly_in(p, a)) {
        return true;
    }
    // Edges crossing each other: each one's ends on opposite sides of the other's line, by
    // more than a few centimetres (collinear or touching edges do not cross).
    let side = |a: V2, b: V2, p: V2| cross(sub(b, a), sub(p, a)) / dist(a, b).max(1e-6);
    let (na, nb) = (a.len(), b.len());
    for i in 0..na {
        let (p, q) = (a[i], a[(i + 1) % na]);
        for j in 0..nb {
            let (r, s) = (b[j], b[(j + 1) % nb]);
            let (dr, ds) = (side(p, q, r), side(p, q, s));
            let (dp, dq) = (side(r, s, p), side(r, s, q));
            if dr * ds < 0.0 && dp * dq < 0.0 && dr.abs().min(ds.abs()) > 0.05 && dp.abs().min(dq.abs()) > 0.05 {
                return true;
            }
        }
    }
    false
}

/// Check a plan against a land of side `size` before anything is generated: unknown levels,
/// duplicate ids, anything outside the land, levels or lots that overlap, a lot off its level
/// or on a street, a stair whose rise disagrees with the levels it joins, a square off its
/// level, a sea over a level. Shared by the authority (`create_floor`, `init`) and clients.
pub fn validate(s: &PlanSpec, size: u32) -> Result<(), String> {
    let r = resolve(s)?;
    let id = &r.id;
    let side = size as f32;
    let inside = |p: V2| p.0 >= 1.0 && p.1 >= 1.0 && p.0 <= side - 1.0 && p.1 <= side - 1.0;
    let off = |what: String, pts: &[V2]| -> Result<(), String> {
        match pts.iter().copied().find(|p| !inside(*p)) {
            Some(p) => Err(format!("plan {id}: {what} at ({:.1}, {:.1}) is outside the {size} m land", p.0, p.1)),
            None => Ok(()),
        }
    };
    for l in &r.levels {
        off(format!("level {}", l.id), &l.poly)?;
    }
    for (i, st) in r.streets.iter().enumerate() {
        off(format!("streets[{i}]"), &st.points)?;
    }
    for st in &r.stairs {
        off(format!("stair {}", st.id), &st.rect.corners())?;
    }
    off("the square".into(), &r.square)?;
    for (i, q) in r.resources.iter().enumerate() {
        off(format!("resources[{i}] ({})", q.kind), &[q.at])?;
    }
    for (i, q) in r.structures.iter().enumerate() {
        off(format!("structures[{i}] ({})", if q.kind.is_empty() { &q.lot } else { &q.kind }), &[q.at])?;
    }
    off("the sea".into(), &r.sea)?;
    for l in &r.lots {
        off(format!("lot {}", l.id), &l.rect.corners())?;
    }
    for i in 0..r.levels.len() {
        for j in i + 1..r.levels.len() {
            let (a, b) = (&r.levels[i], &r.levels[j]);
            if a.lo.0 < b.hi.0 && b.lo.0 < a.hi.0 && a.lo.1 < b.hi.1 && b.lo.1 < a.hi.1 && polys_overlap(&a.poly, &b.poly) {
                return Err(format!("plan {id}: levels {} and {} overlap", a.id, b.id));
            }
        }
        if !r.sea.is_empty() && polys_overlap(&r.levels[i].poly, &r.sea) {
            return Err(format!("plan {id}: the sea overlaps level {}", r.levels[i].id));
        }
    }
    for (i, l) in r.lots.iter().enumerate() {
        let lvl = &r.levels[l.level];
        if let Some(c) = l.rect.corners().into_iter().find(|c| poly_outside(&lvl.poly, *c) > 0.05) {
            return Err(format!("plan {id}: lot {}'s corner ({:.1}, {:.1}) is not on level {}", l.id, c.0, c.1, lvl.id));
        }
        // Lots may share a wall; they may not share floor.
        let shrunk = |q: &Rect| Rect { hw: (q.hw - 0.05).max(0.01), hd: (q.hd - 0.05).max(0.01), ..*q };
        for o in &r.lots[i + 1..] {
            if shrunk(&l.rect).overlaps(&shrunk(&o.rect)) {
                return Err(format!("plan {id}: lots {} and {} overlap", l.id, o.id));
            }
        }
        if l.kind.model().is_some() {
            for (k, st) in r.streets.iter().enumerate() {
                let hw = st.width * 0.5;
                if (0..st.points.len() - 1).any(|j| shrunk(&l.rect).seg_dist(st.points[j], st.points[j + 1]) < hw - 0.1) {
                    return Err(format!("plan {id}: lot {} stands on streets[{k}]", l.id));
                }
            }
            for st in &r.stairs {
                if shrunk(&l.rect).overlaps(&st.rect) {
                    return Err(format!("plan {id}: lot {} stands on stair {}", l.id, st.id));
                }
            }
        }
    }
    Ok(())
}

/// Every plan of a land's parameters, with ids unique across plans.
pub fn validate_all(plans: &[PlanSpec], size: u32) -> Result<(), String> {
    for (i, p) in plans.iter().enumerate() {
        if plans[..i].iter().any(|o| o.id == p.id) {
            return Err(format!("two plans are called {}", p.id));
        }
        validate(p, size)?;
    }
    Ok(())
}

// ------------------------------------------------------------------------------------------
// The ground

/// A plan's ground: its levels at their exact heights, a drop of `drop` metres inside a lower
/// level wherever a higher one meets it, and a skirt of `skirt` metres blending its outer edge
/// into the natural ground (never over water). Continuous everywhere:
/// `G(p) = max_i [f_i − (f_i − f_min) · s((d_i − d_u) / drop)]`, with `d_i` the distance
/// outside level `i`, `d_u` the least of them and `s` a smoothstep; then
/// `h = lerp(natural, G, 1 − s(d_u / skirt))`.
#[derive(Clone, Debug)]
pub(crate) struct Ground {
    lo: V2,
    hi: V2,
    levels: Vec<(Vec<V2>, f32, V2, V2)>,
    fmin: f32,
    drop: f32,
    skirt: f32,
}

impl Ground {
    pub(crate) fn of(r: &Resolved) -> Self {
        let pad = r.skirt + r.drop + 1.0;
        let all: Vec<V2> = r.levels.iter().flat_map(|l| l.poly.iter().copied()).collect();
        let (lo, hi) = bounds(&all);
        Self {
            lo: (lo.0 - pad, lo.1 - pad),
            hi: (hi.0 + pad, hi.1 + pad),
            levels: r.levels.iter().map(|l| (l.poly.clone(), l.floor, l.lo, l.hi)).collect(),
            fmin: r.levels.iter().map(|l| l.floor).fold(f32::MAX, f32::min),
            drop: r.drop,
            skirt: r.skirt,
        }
    }

    /// The plan's surface at `p` and its weight there (0 beyond the skirt), and the distance
    /// outside the nearest level.
    #[inline]
    pub(crate) fn eval(&self, p: V2) -> Option<(f32, f32, f32)> {
        if p.0 < self.lo.0 || p.1 < self.lo.1 || p.0 > self.hi.0 || p.1 > self.hi.1 {
            return None;
        }
        let reach = self.skirt + self.drop;
        let mut d = [f32::INFINITY; 64];
        let mut du = f32::INFINITY;
        for (i, (poly, _, lo, hi)) in self.levels.iter().enumerate().take(64) {
            // A level whose box is farther than the skirt and the drop cannot shape this point
            // (its candidate below is the floor's least, or the skirt's weight is 0).
            if p.0 < lo.0 - reach || p.1 < lo.1 - reach || p.0 > hi.0 + reach || p.1 > hi.1 + reach {
                continue;
            }
            d[i] = poly_outside(poly, p);
            du = du.min(d[i]);
        }
        if du >= self.skirt {
            return None;
        }
        let mut g = self.fmin;
        for (i, (_, f, _, _)) in self.levels.iter().enumerate().take(64) {
            if d[i].is_finite() {
                g = g.max(f - (f - self.fmin) * smoothstep(0.0, self.drop, d[i] - du));
            }
        }
        Some((g, 1.0 - smoothstep(0.0, self.skirt, du), du))
    }

    /// Natural ground `h` at `p` shaped by the plan; `sd` is the signed distance to water. The
    /// skirt keeps off the water, so a quay stands straight out of it.
    #[inline]
    pub(crate) fn apply(&self, p: V2, h: f32, sd: f32) -> f32 {
        match self.eval(p) {
            None => h,
            Some((g, w, du)) => {
                // Off a level, over water, the plan falls to the bed within 0.5 m: a quay's face.
                let w = if du > 0.0 { w * smoothstep(0.0, 1.0, sd).max(1.0 - smoothstep(0.0, 0.5, du)) } else { w };
                lerp(h, g, w)
            }
        }
    }

    /// Whether a point lies on one of the levels.
    pub(crate) fn on_level(&self, p: V2) -> bool {
        self.levels.iter().any(|(poly, _, lo, hi)| p.0 >= lo.0 && p.1 >= lo.1 && p.0 <= hi.0 && p.1 <= hi.1 && poly_contains(poly, p))
    }
}

/// Pull the coarse relief (`elev`, `n` × `n` nodes `cell` metres apart) toward every plan's
/// ground within `blend` metres of its levels, and sink its sea polygon below sea level. Run in
/// `land::hydro_pass` before the sea and the rivers are found, so water follows the plan.
pub(crate) fn stamp_macro(elev: &mut [f32], n: usize, cell: f32, plans: &[Resolved]) {
    for r in plans {
        let g = Ground::of(r);
        let wide = Ground { skirt: r.blend.max(r.skirt), lo: (r.lo.0 - r.blend - 2.0 * cell, r.lo.1 - r.blend - 2.0 * cell), hi: (r.hi.0 + r.blend + 2.0 * cell, r.hi.1 + r.blend + 2.0 * cell), ..g.clone() };
        let (i0, j0) = (((wide.lo.0 / cell).floor().max(0.0)) as usize, ((wide.lo.1 / cell).floor().max(0.0)) as usize);
        let (i1, j1) = (((wide.hi.0 / cell).ceil() as usize).min(n - 1), ((wide.hi.1 / cell).ceil() as usize).min(n - 1));
        for j in j0..=j1 {
            for i in i0..=i1 {
                let k = j * n + i;
                let p = (i as f32 * cell, j as f32 * cell);
                if !r.sea.is_empty() && (poly_contains(&r.sea, p) || poly_outside(&r.sea, p) < cell * 0.5) && !g.on_level(p) {
                    elev[k] = elev[k].min(-r.sea_depth);
                    continue;
                }
                if let Some((h, _, du)) = wide.eval(p) {
                    // Full strength on and just round the levels, fading out over `blend`.
                    let w = 1.0 - smoothstep(cell, wide.skirt, du);
                    elev[k] = lerp(elev[k], h, w);
                }
            }
        }
    }
}

/// Whether a point is inside a plan's footprint for other planning (its levels and sea).
pub(crate) fn covers(r: &Resolved, p: V2, margin: f32) -> bool {
    if p.0 < r.lo.0 - margin || p.1 < r.lo.1 - margin || p.0 > r.hi.0 + margin || p.1 > r.hi.1 + margin {
        return false;
    }
    r.levels.iter().any(|l| poly_outside(&l.poly, p) <= margin) || (!r.sea.is_empty() && poly_outside(&r.sea, p) <= margin)
}

/// The fixed site a plan stands on: its kind and style, at its square, with the radius that
/// holds its levels, levelling nothing (the plan's ground does that).
pub(crate) fn site(r: &Resolved, region: RegionKind) -> Site {
    Site { kind: r.kind, x: r.centre.0, y: r.centre.1, radius_m: r.radius.max(20.0), ground_m: r.levels[r.square_level].floor, scale: r.scale, facing: 0.0, region, flatten: 0.0, style: Some(r.style.clone()), ward: false, plan: Some(r.id.clone()) }
}

// ------------------------------------------------------------------------------------------
// What the planner keeps of a plan

/// What a planned settlement's lots, streets and spots are called, kept on the land for the
/// authority (homes and named buildings by lot, places by lot and spot). Not digested.
#[derive(Clone, Debug, Default, Serialize)]
pub struct Laid {
    pub id: String,
    /// Index into [`Land::settlements`].
    pub settlement: u16,
    pub lots: Vec<LaidLot>,
    /// Road ids of its streets and their paving.
    pub streets: Vec<(u32, Option<String>)>,
    /// Its authored resources on the land ([`PlanSpec::resources`]).
    pub resources: Vec<LaidResource>,
    /// Its authored structures and its lots' stores, on the land ([`PlanSpec::structures`],
    /// [`LotSpec::contents`]).
    pub structures: Vec<LaidStructure>,
}

/// An authored resource on the land.
#[derive(Clone, Debug, Default, Serialize)]
pub struct LaidResource {
    pub kind: String,
    pub at: V2,
    pub max: Option<f32>,
    pub regrow_per_h: Option<f32>,
    pub pool: String,
}

/// An authored structure on the land: a structure of `kind` to place at `at`, or (an empty
/// kind) what the structure at lot `lot`'s door holds.
#[derive(Clone, Debug, Default, Serialize)]
pub struct LaidStructure {
    pub kind: String,
    pub lot: String,
    pub at: V2,
    pub fuel: f32,
    pub contents: Vec<(String, u32)>,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct LaidLot {
    /// Index into [`Land::lots`].
    pub lot: u32,
    pub key: String,
    pub name: Option<String>,
    pub spots: Vec<(String, V2)>,
}

/// A plan laid out by the planner's `Plan` step, handed through the later steps.
pub(crate) struct Built {
    pub(crate) res: Resolved,
    pub(crate) ground: Ground,
    pub(crate) settlement: Settlement,
    pub(crate) bound: Vec<f32>,
    pub(crate) roads: Vec<Road>,
    pub(crate) lots: Vec<Lot>,
    /// Stairs, then retaining walls.
    pub(crate) props: Vec<Prop>,
    pub(crate) pads: Vec<Pad>,
    pub(crate) laid: Laid,
}

/// Paint a plan's ground into the tiles before anything else is planned: its levels are open
/// land (water, rock and trees give way), its sea is water. Returns the box that changed.
pub(crate) fn paint(land: &mut Land, r: &Resolved) -> ((i32, i32), (i32, i32)) {
    let w = land.size as i32;
    let (x0, y0) = ((r.lo.0.floor() as i32 - 1).max(0), (r.lo.1.floor() as i32 - 1).max(0));
    let (x1, y1) = ((r.hi.0.ceil() as i32 + 1).min(w - 1), (r.hi.1.ceil() as i32 + 1).min(w - 1));
    for y in y0..=y1 {
        for x in x0..=x1 {
            let q = (x as f32 + 0.5, y as f32 + 0.5);
            let k = (y * w + x) as usize;
            let t = Terrain::from_u8(land.map.tiles[k]);
            if r.levels.iter().any(|l| poly_contains(&l.poly, q)) {
                if matches!(t, Terrain::Water | Terrain::Rock | Terrain::Forest | Terrain::Wall | Terrain::Drop) {
                    land.map.tiles[k] = Terrain::Grass as u8;
                }
            } else if !r.sea.is_empty() && poly_contains(&r.sea, q) {
                land.map.tiles[k] = Terrain::Water as u8;
            }
        }
    }
    ((x0, y0), (x1, y1))
}

/// Lay out one resolved plan on a land whose `mods` already hold every plan's ground: its
/// streets (heights on the plan's ground), settlement record (`idx` in the settlement list,
/// `site` in the site list, its streets numbered from `first_road`), lots, and its stairs as
/// sloped pads. Retaining walls follow once the stairs are in the ground ([`retaining`]).
pub(crate) fn build(land: &Land, r: Resolved, idx: u16, site: u16, first_road: u32) -> Built {
    let ground = Ground::of(&r);
    let sq = &r.square;
    let near_square = |q: V2| poly_outside(sq, q) < 1.0;
    let mut roads = Vec::new();
    let mut laid = Laid { id: r.id.clone(), settlement: idx, resources: r.resources.clone(), structures: r.structures.clone(), ..Laid::default() };
    for (i, st) in r.streets.iter().enumerate() {
        // Points at most 2 m apart, each at the ground's height: the street lies on the plan.
        let pts = dedup(resample(&st.points, 2.0));
        let heights: Vec<f32> = pts.iter().map(|q| land.height(q.0, q.1)).collect();
        let ends = [if near_square(pts[0]) { RoadEnd::Plaza(idx) } else { RoadEnd::Free }, if near_square(*pts.last().unwrap()) { RoadEnd::Plaza(idx) } else { RoadEnd::Free }];
        let length_m = *cumlen(&pts).last().unwrap();
        let crossfall = vec![0.0; pts.len() - 1];
        roads.push(Road { class: st.class, settlement: Some(idx), points: pts, heights, width_m: st.width, crossfall, ends, length_m });
        laid.streets.push((first_road + i as u32, st.surface.clone()));
    }
    let square_floor = r.levels[r.square_level].floor;
    let mut lots = Vec::new();
    for l in &r.lots {
        // What it faces: the nearest street in front of it, else the square.
        let front_mid = add(l.rect.c, mul(l.rect.f, l.rect.hd));
        let probe = add(front_mid, mul(l.rect.f, 1.0));
        let best = roads.iter().enumerate().map(|(ri, rd)| (nearest_on(&rd.points, probe).0 - rd.width_m * 0.5, ri)).min_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
        let frontage = match best {
            Some((d, ri)) if d < 4.0 || !near_square(probe) => Frontage::Road(first_road + ri as u32),
            _ => Frontage::Plaza(idx),
        };
        lots.push(Lot {
            settlement: idx,
            kind: l.kind,
            centre: l.rect.c,
            width_m: l.rect.hw * 2.0,
            depth_m: l.rect.hd * 2.0,
            front: l.rect.f,
            yaw: yaw_of(l.rect.f),
            floor_m: r.levels[l.level].floor,
            frontage,
            landmark: l.landmark,
            model_file: l.model.clone(),
            height_m: l.height,
        });
        laid.lots.push(LaidLot { lot: 0, key: l.id.clone(), name: l.name.clone(), spots: l.spots.clone() });
    }
    let k = r.scale.max(0.3);
    let mut props = Vec::new();
    let mut pads = Vec::new();
    for st in &r.stairs {
        props.push(Prop { settlement: idx, kind: PropKind::Stairs, centre: st.rect.c, width_m: st.rect.hw * 2.0, depth_m: st.rect.hd * 2.0, front: st.rect.f, yaw: yaw_of(st.rect.f), floor_m: st.floor, model_file: st.model.clone(), height_m: st.rise + 1.0 * k });
        pads.push(Pad { shape: Shape::Rect(st.rect), floor: st.floor, skirt: 0.3 * k, gate: 0.0, rise: Some((st.rect.f, st.rise)) });
    }
    // Gates between the plan's own pads, so each flight stays exact beside another.
    let gates: Vec<f32> = (0..pads.len()).map(|i| (0..pads.len()).filter(|&j| j != i).map(|j| pad_gap(&pads[i], &pads[j])).fold(2.0f32, f32::min) * 0.45).map(|g| g.clamp(0.05, 1.0 * k)).collect();
    for (p, g) in pads.iter_mut().zip(gates) {
        p.gate = g;
    }
    let landmark = r.lots.iter().position(|l| l.landmark).map(|i| i as u32);
    let settlement = Settlement {
        site,
        kind: r.kind,
        style: r.style.clone(),
        centre: r.centre,
        scale: r.scale,
        radius_m: r.radius,
        plaza: Plaza { centre: r.centre, points: sq.clone(), floor_m: square_floor, paved: r.paved },
        wall: None,
        lots: (0, 0),
        landmark,
        roads: (0..roads.len() as u32).map(|i| first_road + i).collect(),
        terrace_m: 0.0,
        planned: true,
    };
    // The edge per direction: as far as its levels reach.
    let bound: Vec<f32> = (0..72)
        .map(|i| {
            let a = i as f32 / 72.0 * std::f32::consts::TAU;
            let (s, c) = a.d_sin_cos();
            let far = add(r.centre, (c * 1e4, s * 1e4));
            let mut reach: f32 = 8.0;
            for l in &r.levels {
                let n = l.poly.len();
                for j in 0..n {
                    if let Some((t, _)) = seg_intersect(r.centre, far, l.poly[j], l.poly[(j + 1) % n]) {
                        reach = reach.max(t * 1e4);
                    }
                }
            }
            reach
        })
        .collect();
    Built { res: r, ground, settlement, bound, roads, lots, props, pads, laid }
}

/// Retaining walls along a plan's levels: in pieces about 4 m long wherever the finished
/// ground falls more than a step below a retaining level's edge, faced toward the lower ground,
/// standing on it, clear of the stairs. Run once the ground has the plan's stairs.
pub(crate) fn retaining(land: &Land, b: &mut Built, idx: u16) {
    let r = &b.res;
    let stairs: Vec<Rect> = r.stairs.iter().map(|s| Rect { hw: s.rect.hw + 0.4, hd: s.rect.hd + 0.4, ..s.rect }).collect();
    let mut walls = Vec::new();
    for l in r.levels.iter().filter(|l| l.retaining) {
        let n = l.poly.len();
        // Outward is away from the polygon's inside, whichever way it winds.
        let ccw = poly_area(&l.poly) > 0.0;
        for i in 0..n {
            let (a, b2) = (l.poly[i], l.poly[(i + 1) % n]);
            let el = dist(a, b2);
            if el < 1.0 {
                continue;
            }
            let t = norm(sub(b2, a));
            let out = if ccw { mul(perp(t), -1.0) } else { perp(t) };
            let pieces = (el / 4.0).round().max(1.0) as usize;
            let pl = el / pieces as f32;
            for k in 0..pieces {
                let m = add(a, mul(t, (k as f32 + 0.5) * pl));
                let below = add(m, mul(out, r.drop + 0.6));
                if below.0 < 1.0 || below.1 < 1.0 || below.0 > land.size as f32 - 1.0 || below.1 > land.size as f32 - 1.0 {
                    continue;
                }
                let lower = land.height(below.0, below.1);
                let fall = l.floor - lower;
                if fall <= terrace::CLIMB_M || land.map.at(below.0, below.1) == Terrain::Water {
                    continue;
                }
                let depth = r.drop.max(0.4);
                let rect = Rect { c: add(m, mul(out, depth * 0.5)), f: out, hw: pl * 0.5, hd: depth * 0.5 };
                if stairs.iter().any(|s| s.overlaps(&rect)) {
                    continue;
                }
                walls.push(Prop { settlement: idx, kind: PropKind::RetainingWall, centre: rect.c, width_m: pl, depth_m: depth, front: out, yaw: yaw_of(out), floor_m: lower, model_file: None, height_m: fall + 0.3 });
            }
        }
    }
    b.props.extend(walls);
}

/// The buildings of planned settlements whose doors no one can reach on the hosted tiles
/// (`reachable` from [`crate::host::hosted_map`]): lot keys, empty when every door is in the
/// main walkable area.
pub fn stranded_doors(land: &Land, map: &crate::map::Map, reachable: &[bool]) -> Vec<String> {
    let mut out = Vec::new();
    for p in &land.plans {
        for l in &p.lots {
            let lot = &land.lots[l.lot as usize];
            if !crate::host::blocks(lot.kind) || matches!(lot.kind, LotKind::Well | LotKind::MarketStall) {
                continue;
            }
            let d = crate::host::door(lot);
            let ok = map.nearest_walkable(d.0, d.1).is_some_and(|q| reachable.get((q.1 as u32 * map.w + q.0 as u32) as usize).copied().unwrap_or(false) && dist(q, d) < 2.0);
            if !ok {
                out.push(format!("{}:{}", p.id, l.key));
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::land::{self, LandParams};
    use crate::map::Map;
    use std::sync::OnceLock;

    fn seed() -> serde_json::Value {
        serde_json::from_str(include_str!("../../../seeds/plan-test.json")).expect("plan-test.json")
    }

    fn params() -> LandParams {
        serde_json::from_value(seed()["map"]["params"].clone()).expect("map.params")
    }

    fn spec() -> PlanSpec {
        params().plans[0].clone()
    }

    /// `seeds/plan-test.json`: seed 3 at 1024 m with one planned town and two villages.
    fn plan_land() -> &'static (Land, Map, Vec<bool>) {
        static L: OnceLock<(Land, Map, Vec<bool>)> = OnceLock::new();
        L.get_or_init(|| {
            let p = params();
            let l = land::generate(3, 1024, &p);
            let (m, h) = crate::host::hosted_map(&l, &p);
            (l, m, h.reachable)
        })
    }

    #[test]
    fn the_plan_frame_turns_with_rotation() {
        let mut s = spec();
        s.origin = [500.0, 500.0];
        s.rotation_deg = 0.0;
        let f = Frame::of(&s);
        let q = f.pt([10.0, 20.0]);
        assert!((q.0 - 510.0).abs() < 1e-4 && (q.1 - 480.0).abs() < 1e-4, "north is up the map: {q:?}");
        let d = f.dir(90.0);
        assert!((d.0 - 1.0).abs() < 1e-4 && d.1.abs() < 1e-4, "a bearing of 90 faces east: {d:?}");
        s.rotation_deg = 90.0;
        let f = Frame::of(&s);
        let q = f.pt([0.0, 10.0]);
        assert!((q.0 - 510.0).abs() < 1e-3 && (q.1 - 500.0).abs() < 1e-3, "the plan's north turned to the east: {q:?}");
        let q = f.pt([10.0, 0.0]);
        assert!((q.0 - 500.0).abs() < 1e-3 && (q.1 - 510.0).abs() < 1e-3, "and its east to the south: {q:?}");
    }

    #[test]
    fn the_test_plan_is_valid() {
        validate_all(&params().plans, 1024).expect("plan-test.json validates");
    }

    #[test]
    fn validation_refuses_what_the_generator_cannot_honour() {
        let cases: Vec<(&str, Box<dyn Fn(&mut PlanSpec)>)> = vec![
            ("level ids must be unique", Box::new(|s| s.levels[1].id = "quay".into())),
            ("which the plan does not have", Box::new(|s| s.lots[0].level = "attic".into())),
            ("which the plan does not have", Box::new(|s| s.stairs[0].to = "roof".into())),
            ("outside the 1024 m land", Box::new(|s| s.origin = [1020.0, 888.0])),
            ("outside the 1024 m land", Box::new(|s| s.lots[0].at = [-30.0, 2000.0])),
            ("overlap", Box::new(|s| s.lots[1].at = [-25.0, 14.0])),
            ("levels quay and row overlap", Box::new(|s| s.levels[1].area[0] = [-40.0, 20.0])),
            ("rises 3 m", Box::new(|s| s.stairs[0].rise_m = Some(3.0))),
            ("the head of stair the steps is not on level row", Box::new(|s| s.stairs[0].head = [32.0, 70.0])),
            ("the higher level", Box::new(|s| {
                    let st = &mut s.stairs[0];
                    std::mem::swap(&mut st.from, &mut st.to)
                })),
            ("is not on level quay", Box::new(|s| s.lots[0].at = [-30.0, 21.0])),
            ("stands on streets", Box::new(|s| s.lots[0].at = [-30.0, 8.0])),
            ("the sea overlaps level quay", Box::new(|s| s.sea[2] = [60.0, 5.0])),
            ("lot ids must be unique", Box::new(|s| s.lots[1].id = "store".into())),
            ("facing", Box::new(|s| s.lots[0].facing = Facing::Named("up".into()))),
        ];
        for (want, f) in cases {
            let mut s = spec();
            f(&mut s);
            let e = validate(&s, 1024).expect_err(want);
            assert!(e.contains(want), "{want:?} not in {e:?}");
        }
        let two = vec![spec(), spec()];
        assert!(validate_all(&two, 1024).unwrap_err().contains("two plans are called plan_test"));
        // What the engine does not read is ignored, not refused.
        let mut v = seed()["map"]["params"]["plans"][0].clone();
        v["wear"] = serde_json::json!({"salt": 0.4});
        v["lots"][0]["keepsake"] = "a caged gull".into();
        let s: PlanSpec = serde_json::from_value(v).expect("unknown fields ignored");
        validate(&s, 1024).expect("still valid");
    }

    /// `seeds/cullet.json` (docs/SMALL_CITY.md, written by `living/tools/cullet_plan.py`): the plan
    /// and the authored land are valid, every building door is reachable, its five landmarks are
    /// the Cone, the Counting House, the Heron, the Watchglass and the Lintel, and the sea, the
    /// Hanger's forest and the Wrack Strand's sand are where the plan puts them.
    #[test]
    fn the_cullet_seed_is_valid_and_reachable() {
        let v: serde_json::Value = serde_json::from_str(include_str!("../../../seeds/cullet.json")).expect("cullet.json");
        let p: LandParams = serde_json::from_value(v["map"]["params"].clone()).expect("map.params");
        let size = v["map"]["size"].as_u64().unwrap() as u32;
        validate_all(&p.plans, size).unwrap();
        crate::land::validate_relief(&p.relief).unwrap();
        let l = land::generate(v["seed"].as_u64().unwrap(), size, &p);
        let (m, h) = crate::host::hosted_map(&l, &p);
        assert_eq!(stranded_doors(&l, &m, &h.reachable), Vec::<String>::new());
        let laid = &l.plans[0];
        let mut marks: Vec<&str> = laid.lots.iter().filter(|q| l.lots[q.lot as usize].landmark).map(|q| q.key.as_str()).collect();
        marks.sort();
        assert_eq!(marks, ["cone", "counting_house", "heron", "lintel", "watchglass"]);
        let f = Frame::of(&p.plans[0]);
        let at = |x: f32, y: f32| m.get(f.pt([x, y]).0 as i32, f.pt([x, y]).1 as i32);
        assert_eq!(at(0.0, -40.0), Terrain::Water, "the harbour");
        assert_eq!(at(0.0, -200.0), Terrain::Water, "the sea beyond the Combs");
        assert_eq!(at(-220.0, 30.0), Terrain::Sand, "the Wrack Strand");
        assert!(l.lakes.is_empty() && l.rivers.is_empty(), "no lake or river on a rock that drinks rain");
        let forest = m.tiles.iter().filter(|t| **t == Terrain::Forest as u8).count();
        assert!(forest > 500 && l.regions.len() > 0, "the Hanger: {forest} forest tiles");
    }

    /// Authored resources are kept on the land at their points, for the authority to place; one
    /// off the land or without a kind is refused.
    #[test]
    fn the_test_plans_resources_are_kept_on_the_land() {
        let (l, _, _) = plan_land();
        let s = spec();
        assert!(!s.resources.is_empty());
        let f = Frame::of(&s);
        let laid = &l.plans[0];
        assert_eq!(laid.resources.len(), s.resources.len());
        for (rs, q) in s.resources.iter().zip(&laid.resources) {
            assert_eq!(rs.kind, q.kind);
            assert!(dist(f.pt(rs.at), q.at) < 1e-4, "{} at {:?}", q.kind, q.at);
        }
        let mut bad = s.clone();
        bad.resources[0].at = [0.0, 2000.0];
        assert!(validate(&bad, 1024).unwrap_err().contains("resources[0]"));
        bad.resources[0].kind.clear();
        assert!(validate(&bad, 1024).unwrap_err().contains("needs a kind"));
    }

    /// Authored structures stand at their point, at a lot's door or at a lot's spot, with their
    /// fuel and contents; a lot's own `contents` go to the structure at its door; one at a lot or
    /// spot the plan does not have, or with both a point and a lot, is refused.
    #[test]
    fn a_plans_structures_and_stores_are_kept_on_the_land() {
        let mut s = spec();
        let f = Frame::of(&s);
        let spot = |id: &str, n: usize| s.lots.iter().find(|l| l.id == id).unwrap().spots[n].name.clone();
        let st = |kind: &str| StructureSpec { kind: kind.into(), at: None, lot: None, spot: None, fuel: 0.0, contents: Default::default() };
        let (inn_seat, hall_door) = (spot("inn", 0), "hall".to_string());
        s.structures = vec![
            StructureSpec { at: Some([1.0, 2.0]), fuel: 4.0, ..st("lamp") },
            StructureSpec { lot: Some(hall_door.clone()), fuel: 6.0, ..st("hearth") },
            StructureSpec { lot: Some("inn".into()), spot: Some(inn_seat.clone()), contents: [("peat".to_string(), 9)].into(), ..st("storage") },
        ];
        for l in &mut s.lots {
            l.contents.clear();
        }
        s.lots.iter_mut().find(|l| l.id == "store").unwrap().contents = [("fish".to_string(), 3)].into();
        let r = resolve(&s).unwrap();
        let lot = |id: &str| r.lots.iter().find(|l| l.id == id).unwrap().clone();
        let door = |l: &PlanLot| add(l.rect.c, mul(l.rect.f, l.rect.hd + 0.5));
        assert_eq!(r.structures.len(), 4);
        assert!(dist(r.structures[0].at, f.pt([1.0, 2.0])) < 1e-4 && r.structures[0].fuel == 4.0);
        assert!(dist(r.structures[1].at, door(&lot("hall"))) < 1e-4 && r.structures[1].kind == "hearth");
        let seat = lot("inn").spots.iter().find(|(n, _)| *n == inn_seat).unwrap().1;
        assert!(dist(r.structures[2].at, seat) < 1e-4 && r.structures[2].contents == vec![("peat".to_string(), 9)]);
        assert!(r.structures[3].kind.is_empty() && r.structures[3].lot == "store" && dist(r.structures[3].at, door(&lot("store"))) < 1e-4);
        assert!(validate(&s, 1024).is_ok());
        let refused = |change: &dyn Fn(&mut PlanSpec), words: &str| {
            let mut b = s.clone();
            change(&mut b);
            let e = validate(&b, 1024).unwrap_err();
            assert!(e.contains(words), "{e}");
        };
        refused(&|b| b.structures[1].lot = Some("nowhere".into()), "which the plan does not have");
        refused(&|b| b.structures[2].spot = Some("nowhere".into()), "has no spot");
        refused(&|b| b.structures[0].lot = Some("hall".into()), "needs either `at` or a `lot`");
        refused(&|b| b.structures[0].fuel = -1.0, "fuel of at least 0");
        refused(&|b| b.structures[0].at = Some([0.0, 5000.0]), "structures[0]");
        refused(&|b| b.resources[0].regrow_per_h = Some(f32::NAN), "regrow_per_h");
    }

    /// The test plan stands as written: its site and id, lots on their levels at exact
    /// heights with their models, the square, streets, the stair between the levels, retaining
    /// walls along the drop, the harbour, island roads joining its trunk street, and every door
    /// reachable on the hosted tiles.
    #[test]
    fn the_test_plan_is_laid_out_as_written() {
        let (l, map, reach) = plan_land();
        let s = spec();
        let r = resolve(&s).unwrap();
        let site = l.sites.iter().find(|x| x.plan.as_deref() == Some("plan_test")).expect("its site");
        assert_eq!(site.id(), "plan_test");
        let laid = &l.plans[0];
        let set = &l.settlements[laid.settlement as usize];
        assert!(set.planned && set.style == "cullet" && set.kind == SiteKind::Town);
        assert_eq!((set.lots.1 - set.lots.0) as usize, s.lots.len());
        assert!((set.plaza.floor_m - 2.5).abs() < 1e-6);
        for (k, (ll, spec_lot)) in laid.lots.iter().zip(&s.lots).enumerate() {
            let lot = &l.lots[ll.lot as usize];
            assert_eq!(ll.key, spec_lot.id);
            assert_eq!(lot.kind, spec_lot.kind);
            assert_eq!(lot.model_file, spec_lot.model, "lot {}", ll.key);
            assert_eq!(lot.height_m, spec_lot.height_m.unwrap_or(6.0));
            let floor = r.levels[r.lots[k].level].floor;
            assert_eq!(lot.floor_m, floor);
            // The ground is level under it (an inset keeps off a drop behind its back wall).
            let rect = Rect { hw: lot.width_m * 0.5 - 0.3, hd: lot.depth_m * 0.5 - 0.3, ..lot.rect() };
            for c in rect.corners().into_iter().chain([lot.centre]) {
                let h = l.height(c.0, c.1);
                assert!((h - floor).abs() < 1e-3, "lot {} at {c:?}: ground {h}, floor {floor}", ll.key);
            }
        }
        assert_eq!(laid.lots.iter().find(|x| x.key == "hall").unwrap().spots.len(), 2);
        assert_eq!(laid.lots.iter().find(|x| x.key == "inn").unwrap().spots.len(), 3);
        // Streets: on their levels, painted, at their level's height.
        let row = &l.roads[laid.streets[2].0 as usize];
        assert_eq!(laid.streets[2].1.as_deref(), Some("setts"));
        for (q, h) in row.points.iter().zip(&row.heights) {
            assert!((h - 6.5).abs() < 1e-3, "the row at {q:?} is at {h}");
            assert_eq!(l.map.at(q.0, q.1), Terrain::Road);
        }
        // The stair: walkable, from the quay's floor up to the row's.
        let stair = l.props.iter().find(|p| p.kind == PropKind::Stairs && p.settlement == laid.settlement).expect("the stair");
        let foot = add(stair.centre, mul(stair.front, stair.depth_m * 0.5 - 0.2));
        let head = sub(stair.centre, mul(stair.front, stair.depth_m * 0.5 - 0.2));
        assert!((l.height(foot.0, foot.1) - 2.5).abs() < 0.2 && (l.height(head.0, head.1) - 6.5).abs() < 0.2, "the stair climbs from {} to {}", l.height(foot.0, foot.1), l.height(head.0, head.1));
        for t in 0..=10 {
            let q = add(foot, mul(sub(head, foot), t as f32 / 10.0));
            assert!(map.walkable(q.0 as i32, q.1 as i32), "the stair is walkable at {q:?}");
        }
        assert!(l.props.iter().filter(|p| p.kind == PropKind::RetainingWall && p.settlement == laid.settlement).count() >= 10, "retaining walls along the drop");
        // The harbour is sea.
        let inner = r.sea.iter().fold((0.0, 0.0), |a, q| add(a, mul(*q, 0.25)));
        assert_eq!(l.map.at(inner.0, inner.1), Terrain::Water);
        // Island roads join the town's trunk street where it leaves the levels.
        let trunk = laid.streets[3].0;
        assert!(l.roads.iter().any(|rd| rd.ends.contains(&RoadEnd::Road(trunk))), "an island road joins the road out");
        assert!(stranded_doors(l, map, reach).is_empty(), "doors stranded: {:?}", stranded_doors(l, map, reach));
        // Newcomers arrive on its square.
        let a = crate::host::arrival(l, map);
        assert!(poly_outside(&set.plaza.points, a) < 2.0, "arrival {a:?}");
    }

    /// The plan's ground is continuous (drops are steep, never a step) and walkable ground
    /// round it has no cliff: only roads (the stair, streets) climb more than a step per tile.
    #[test]
    fn the_test_plans_ground_is_continuous_and_walls_its_drops() {
        let (l, map, _) = plan_land();
        let r = resolve(&spec()).unwrap();
        let (lo, hi) = (r.lo, r.hi);
        let step = 0.05;
        let mut y = lo.1;
        while y < hi.1 {
            let mut x = lo.0;
            let mut prev = l.height(x, y);
            while x < hi.0 {
                x += step;
                let h = l.height(x, y);
                assert!((h - prev).abs() <= 12.0 * step + 0.02, "a step of {} m at ({x:.2}, {y:.2})", h - prev);
                prev = h;
            }
            y += 0.73;
        }
        let (x0, y0, x1, y1) = (lo.0 as i32, lo.1 as i32, hi.0 as i32, hi.1 as i32);
        for y in y0..y1 {
            for x in x0..x1 {
                if !map.walkable(x, y) {
                    continue;
                }
                let h = l.height(x as f32 + 0.5, y as f32 + 0.5);
                for (dx, dy) in [(1, 0), (0, 1)] {
                    if map.walkable(x + dx, y + dy) && !(map.get(x, y) == Terrain::Road && map.get(x + dx, y + dy) == Terrain::Road) {
                        let d = (h - l.height((x + dx) as f32 + 0.5, (y + dy) as f32 + 0.5)).abs();
                        assert!(d <= terrace::CLIMB_M + 1e-3, "a {d} m step between walkable tiles at ({x}, {y})");
                    }
                }
            }
        }
    }

    /// Across the drop between the quay and the row, two people 2 m either side see each other
    /// and neither can step across: the drop's tiles are `Drop` on the hosted map (not `Wall`),
    /// walking stops at them, and any route between goes round the drop, never over it.
    #[test]
    fn people_see_across_the_plans_drop_but_cannot_walk_across() {
        let (l, map, _) = plan_land();
        let r = resolve(&spec()).unwrap();
        let (x0, y0, x1, y1) = (r.lo.0 as i32, r.lo.1 as i32, r.hi.0 as i32, r.hi.1 as i32);
        let drops = (y0..y1).flat_map(|y| (x0..x1).map(move |x| (x, y))).filter(|&(x, y)| map.get(x, y) == Terrain::Drop).count();
        assert!(drops >= 50, "{drops} drop tiles in the plan");
        let mut pairs = 0;
        for y in y0..y1 {
            for x in x0..x1 {
                if map.get(x, y) != Terrain::Drop {
                    continue;
                }
                for (dx, dy) in [(1, 0), (0, 1)] {
                    let (a, b) = ((x - 2 * dx, y - 2 * dy), (x + 2 * dx, y + 2 * dy));
                    let (pa, pb) = ((a.0 as f32 + 0.5, a.1 as f32 + 0.5), (b.0 as f32 + 0.5, b.1 as f32 + 0.5));
                    // Standing ground on two levels, nothing built between.
                    let between_open = (-1..=1).all(|k| !map.get(x + k * dx, y + k * dy).opaque());
                    if !map.walkable(a.0, a.1) || !map.walkable(b.0, b.1) || !between_open || (l.height(pa.0, pa.1) - l.height(pb.0, pb.1)).abs() < 2.0 {
                        continue;
                    }
                    pairs += 1;
                    assert!(map.sight_clear(pa, pb) && map.sight_clear(pb, pa), "the two levels see each other at ({x}, {y})");
                    assert!(!map.free(x as f32 + 0.5, y as f32 + 0.5) && !map.line_clear(pa, pb), "a step across the drop at ({x}, {y})");
                    // A route between them goes round the drop (by a stair, or past its end).
                    if let Some(p) = map.path(pa, pb, 50_000) {
                        for w in std::iter::once(pa).chain(p.iter().copied()).collect::<Vec<_>>().windows(2) {
                            let n = (dist(w[0], w[1]) / 0.1).ceil().max(1.0) as i32;
                            assert!((0..=n).all(|i| map.free(w[0].0 + (w[1].0 - w[0].0) * i as f32 / n as f32, w[0].1 + (w[1].1 - w[0].1) * i as f32 / n as f32)), "a route over the drop at ({x}, {y})");
                        }
                    }
                }
            }
        }
        assert!(pairs >= 20, "{pairs} places where people stand either side of the drop");
    }

    #[test]
    fn the_test_plan_is_repeatable() {
        let p = params();
        let a = land::generate(3, 1024, &p);
        let (ma, _) = crate::host::hosted_map(&a, &p);
        let (l, m, _) = plan_land();
        assert_eq!(crate::host::digests(&a, &ma), crate::host::digests(l, m));
        let g = land::Gen::new(3, 1024, p);
        assert!(g.label().contains("relief"));
    }
}
