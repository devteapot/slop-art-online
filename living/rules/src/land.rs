//! Km-scale land for the game's first world, a generic placeholder (see `docs/FIRST_WORLD.md`).
//!
//! [`crate::realm`] sizes its features in tiles, so a larger realm repeats the same half-km
//! patterns. Here every feature is sized in metres: a 3 km world gets more regions of the same
//! size, longer rivers and a second range, not bigger blobs. One tile is one metre.
//!
//! Two layers:
//! - **Macro**, a coarse grid of `cell_m` (8 m by default): an island, one or two mountain
//!   ranges with foothills and valleys, lake basins, rivers routed by flow accumulation to the
//!   sea, moisture, regions (biome areas a few hundred metres across) and sites.
//! - **Tiles**, 1 m: the existing [`Terrain`] classes, with fords and passes cut so every
//!   walkable tile is reachable on foot.
//!
//! [`Land::height`] combines both into a continuous ground height in metres. This module holds
//! mechanics only; every size, count and threshold is a field of [`LandParams`].

use crate::det::Det;
use crate::map::{Map, Terrain, MAX_SIDE};
use crate::settle::{self, Crossing, Lot, MetroParams, Prop, Road, SettleParams, Settlement};
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::{BinaryHeap, VecDeque};

const NONE: u32 = u32::MAX;

// ------------------------------------------------------------------------------------------
// Kinds

/// What a region is. [`RegionKind::env`] names the game environment whose assets suit it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RegionKind {
    Sea,
    Beach,
    Meadow,
    Forest,
    OldForest,
    SpiritGrove,
    Wetland,
    Highland,
    Peaks,
}

impl RegionKind {
    pub const ALL: [RegionKind; 9] = [
        Self::Sea,
        Self::Beach,
        Self::Meadow,
        Self::Forest,
        Self::OldForest,
        Self::SpiritGrove,
        Self::Wetland,
        Self::Highland,
        Self::Peaks,
    ];

    pub fn id(self) -> &'static str {
        match self {
            Self::Sea => "sea",
            Self::Beach => "beach",
            Self::Meadow => "meadow",
            Self::Forest => "forest",
            Self::OldForest => "old_forest",
            Self::SpiritGrove => "spirit_grove",
            Self::Wetland => "wetland",
            Self::Highland => "highland",
            Self::Peaks => "peaks",
        }
    }

    /// The game environment (`living/game/assets/envs/<id>.json`) to draw this region with.
    /// Kinds without an environment of their own yet borrow the closest one.
    pub fn env(self) -> Option<&'static str> {
        match self {
            Self::Sea => None,
            Self::Meadow | Self::Beach | Self::Wetland | Self::Highland | Self::Peaks => Some("meadow"),
            Self::Forest | Self::OldForest => Some("forest"),
            Self::SpiritGrove => Some("spirit_forest"),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SiteKind {
    Town,
    Village,
    /// A settlement sized for inhabitants several times taller than adults.
    Giants,
    /// A settlement sized for inhabitants about a third of an adult's height.
    SmallFolk,
    /// A cave mouth on a mountain flank. The caverns behind it are a separate space, not part
    /// of this height map.
    Cave,
}

impl SiteKind {
    pub fn id(self) -> &'static str {
        match self {
            Self::Town => "town",
            Self::Village => "village",
            Self::Giants => "giants",
            Self::SmallFolk => "small_folk",
            Self::Cave => "cave",
        }
    }

    pub fn env(self) -> &'static str {
        match self {
            Self::Town | Self::Village => "fantasy_city",
            Self::Giants => "giants_city",
            Self::SmallFolk => "small_city",
            Self::Cave => "caverns",
        }
    }
}

// ------------------------------------------------------------------------------------------
// Parameters

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct LandParams {
    /// Metres per macro cell (relief, water routing, regions and sites).
    pub cell_m: f32,
    pub relief: Relief,
    pub water: Water,
    pub regions: Regions,
    pub sites: Vec<SiteSpec>,
    /// Walkable pockets smaller than this many tiles are closed instead of linked.
    pub min_pocket_tiles: u32,
    /// Roads, settlement layouts and building lots ([`crate::settle`]).
    pub settlements: SettleParams,
    /// One city filling most of the land, laid out in wards between ring highways and
    /// arterials ([`crate::settle::MetroParams`]); the sites above stand outside it. None: no city.
    #[serde(default)]
    pub metro: Option<MetroParams>,
    /// Hand-authored settlements ([`crate::settle::PlanSpec`], docs/AUTHORED_PLANS.md): laid out
    /// as written; the generator steps aside for them. Empty: the land is as before.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub plans: Vec<settle::PlanSpec>,
    /// What hides what is behind it where the land is hosted ([`Sight`]): the eye height, and
    /// per kind of lot or prop how high it hides. Default: 1.6 m, and each model's own height.
    #[serde(default, skip_serializing_if = "Sight::is_default")]
    pub sight: Sight,
}

/// Which built things hide what is behind them, for sight lines on the hosted tiles
/// (`host::hosted_map`, docs/ISLAND_AUTHORITY.md "Sight over low things" and "Sight through
/// what is open at eye height"). A lot or prop that blocks walking hides only where it is solid
/// at the eye: its footprint is `Low` (blocks the foot, not the eye) where it is not. A thing
/// no higher than `eye_m` is `Low` throughout. Above it, where its model's footprint is measured
/// at eye height (`eye_cells` in `data/buildings.json`, from the mesh), a tile is `Wall` when a
/// square of the model in it blocks at least `solid` of the view, else `Low`; a model without
/// the measure (or an eye outside the band it was measured in) is `Wall` throughout. A kind
/// named in `hides_m` is all one or the other by that height instead.
/// Why land data, not a Rhai law: which tiles block is decided when the land is hosted, in this
/// crate, without the world's script; and the game client rebuilds the same hosted land for its
/// own sight test (sight-2). The authority and the client must compute blocking from the same
/// input, and the only input both have is the seed's land data. Defaults come from each kind's
/// own definition (its model's height); `hides_m` only overrides them.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Sight {
    /// Eye height (metres above the ground): what rises above it hides what is behind.
    pub eye_m: f32,
    /// Per kind (a lot kind's or a prop kind's id: `market_stall`, `well`, `cart`, `fountain`…),
    /// how high it hides (metres), in place of its model's height: `{"market_stall": 0}` makes an
    /// open-sided stall see-through, `{"well": 0.95}` sees over a well's rim under its roof.
    /// Empty: every model hides up to its own height.
    pub hides_m: std::collections::BTreeMap<String, f32>,
    /// How much of the view through a square of a model's footprint at eye height must be
    /// blocked for its tile to hide (0..1, against the model's measured `eye_cells`): 0.8,
    /// nearly all of it, so a wall or a room hides, and a post, a beam, goods on a counter, or a
    /// well's posts with its windlass across them (about 70%) do not: on the 1 m tiles a post's
    /// square hides the whole tile it lands on, which can close the view across a turned well.
    pub solid: f32,
}

impl Default for Sight {
    fn default() -> Self {
        Self { eye_m: 1.6, hides_m: Default::default(), solid: 0.8 }
    }
}

impl Sight {
    fn is_default(&self) -> bool {
        *self == Self::default()
    }

    /// Whether a thing of `kind` whose model is `height_m` tall rises above the eye (so it may
    /// hide what is behind it, where it is solid). A kind named in `hides_m` does by that value;
    /// otherwise by its model's height, and a thing with no height known (0: no model) does, as
    /// walls did before.
    pub fn hides(&self, kind: &str, height_m: f32) -> bool {
        match self.hides_m.get(kind) {
            Some(&h) => h > self.eye_m,
            None => height_m <= 0.0 || height_m > self.eye_m,
        }
    }

    /// Whether a model's `eye_cells` decide where it hides: its kind is not named in `hides_m`,
    /// and the eye lies in the band they were measured in.
    pub fn by_cells(&self, kind: &str) -> bool {
        !self.hides_m.contains_key(kind) && (settle::EYE_BAND_M.0..=settle::EYE_BAND_M.1).contains(&self.eye_m)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Relief {
    /// Where the coast lies, as a fraction of half the map side from the centre.
    pub island_radius: f32,
    /// Coast irregularity (fraction of the radius) and its feature size (fraction of the side).
    pub coast_warp: f32,
    pub coast_feature: f32,
    /// The island is stretched along the main range by this factor.
    pub elongation: f32,
    /// Height of the inland plain and depth of the open sea floor.
    pub lowland_m: f32,
    pub sea_floor_m: f32,
    pub hills_m: f32,
    pub hills_feature_m: f32,
    /// Crest height of the main range at the default size, chosen in this interval. Smaller
    /// worlds scale it down (to 60% at 1 km).
    pub peak_m: [f32; 2],
    pub range_half_width_m: f32,
    /// Range length as a fraction of the side, capped in metres.
    pub range_length: f32,
    pub range_max_length_m: f32,
    /// Offset of the main range from the centre (fraction of the side): one side of the island
    /// is steep, the other long and gentle, where the long rivers run.
    pub range_offset: f32,
    /// Sides at least this long always get a second range; from `maybe_two_ranges_m` on, half
    /// the seeds do.
    pub two_ranges_m: f32,
    pub maybe_two_ranges_m: f32,
    pub foothills_m: f32,
    pub ridge_feature_m: f32,
    pub islets: u32,
    pub islet_radius_m: [f32; 2],
    /// Moves the coast's centre off the map's centre (fractions of the side), so the sea lies
    /// along one side only.
    #[serde(default)]
    pub land_shift: [f32; 2],
    /// An authored coastline (land metres, x east, y south; docs/AUTHORED_PLANS.md): the land is
    /// this polygon instead of the warped ellipse above, its edge still roughened by `coast_warp`
    /// (here a fraction of half the side) at `coast_feature`. Inland the plain rises over
    /// `outline_rise_m` from the coast. Empty: the generated shape.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub outline: Vec<[f32; 2]>,
    pub outline_rise_m: f32,
    /// Authored stamps on the relief and the regions, applied in order after the generated
    /// relief, islets and lake basins and before the plans: a plateau, a gully, a beach, a reef.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub stamps: Vec<Stamp>,
}

/// An authored stamp ([`Relief::stamps`]): inside `area` (land metres) the coarse ground is
/// `height_m`, fading into the ground round it over `blend_m`; and/or the ground inside is of
/// region kind `region` (its trees, beach, rocks and dirt follow that kind's look). Lake basins
/// keep off stamps.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Stamp {
    /// For the author; the engine does not read it.
    #[serde(default)]
    pub id: String,
    pub area: Vec<[f32; 2]>,
    #[serde(default)]
    pub height_m: Option<f32>,
    #[serde(default = "stamp_blend")]
    pub blend_m: f32,
    #[serde(default)]
    pub region: Option<RegionKind>,
    /// The tiles inside are this ground (`grass`, `sand`, `dirt`, `rock`, `forest`), wherever
    /// they are not water: a strand wider than the shore's own sand, a scree.
    #[serde(default)]
    pub ground: Option<String>,
}

fn stamp_blend() -> f32 {
    40.0
}

impl Stamp {
    fn poly(&self) -> Vec<(f32, f32)> {
        self.area.iter().map(|q| (q[0], q[1])).collect()
    }
}

fn stamp_ground(g: &str) -> Option<Terrain> {
    match g {
        "grass" => Some(Terrain::Grass),
        "sand" => Some(Terrain::Sand),
        "dirt" => Some(Terrain::Dirt),
        "rock" => Some(Terrain::Rock),
        "forest" => Some(Terrain::Forest),
        _ => None,
    }
}

/// Signed distance to a polygon's edge: positive inside, negative outside.
fn poly_signed(poly: &[(f32, f32)], p: (f32, f32)) -> f32 {
    let out = settle::poly_outside(poly, p);
    if out > 0.0 {
        return -out;
    }
    let n = poly.len();
    (0..n)
        .map(|i| {
            let (a, b) = (poly[i], poly[(i + 1) % n]);
            let (dx, dy) = (b.0 - a.0, b.1 - a.1);
            let u = (((p.0 - a.0) * dx + (p.1 - a.1) * dy) / (dx * dx + dy * dy).max(1e-9)).clamp(0.0, 1.0);
            (p.0 - a.0 - u * dx).d_hypot(p.1 - a.1 - u * dy)
        })
        .fold(f32::MAX, f32::min)
}

/// Check authored relief: polygons of at least three finite points, finite heights and blends,
/// and something for each stamp to do. The authority calls it with the plans' checks, before
/// anything is generated.
pub fn validate_relief(r: &Relief) -> Result<(), String> {
    let ok = |p: &[[f32; 2]]| p.len() >= 3 && p.iter().all(|q| q[0].is_finite() && q[1].is_finite());
    if !r.outline.is_empty() && !ok(&r.outline) {
        return Err("relief.outline needs a polygon of at least 3 points".into());
    }
    if !(r.outline_rise_m.is_finite() && r.outline_rise_m > 0.0) {
        return Err("relief.outline_rise_m must be above 0".into());
    }
    for (i, st) in r.stamps.iter().enumerate() {
        let name = if st.id.is_empty() { format!("relief.stamps[{i}]") } else { format!("relief stamp {}", st.id) };
        if !ok(&st.area) {
            return Err(format!("{name} needs a polygon of at least 3 points"));
        }
        if st.height_m.is_some_and(|h| !h.is_finite()) || !(st.blend_m.is_finite() && st.blend_m >= 0.0) {
            return Err(format!("{name}: height_m and blend_m must be numbers (blend_m at least 0)"));
        }
        if st.height_m.is_none() && st.region.is_none() && st.ground.is_none() {
            return Err(format!("{name} sets neither a height, a region nor a ground"));
        }
        if let Some(g) = &st.ground {
            if stamp_ground(g).is_none() {
                return Err(format!("{name}: ground {g:?} is not grass, sand, dirt, rock or forest"));
            }
        }
    }
    Ok(())
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Water {
    /// Catchment area at which a stream becomes a drawn river.
    pub river_catchment_m2: f32,
    /// Tributaries shorter than this are dropped.
    pub river_min_length_m: f32,
    /// River width = `river_width_k` × √catchment (m²), clamped to `river_width_m`.
    pub river_width_k: f32,
    pub river_width_m: [f32; 2],
    /// Valley walls rise from a river at `valley_slope` + `valley_curve` × distance.
    pub valley_slope: f32,
    pub valley_curve: f32,
    pub ford_spacing_m: f32,
    pub lakes_per_km2: f32,
    pub lake_radius_m: [f32; 2],
    pub lake_depth_m: f32,
    /// Height of a basin's rim above its centre: the lake's depth at the rim.
    pub lake_rim_m: f32,
    /// Natural depressions become lakes when their area lies in this interval (at most
    /// `natural_lakes`); other depressions are filled.
    pub lake_area_m2: [f32; 2],
    pub natural_lakes: u32,
    /// Rivers run dry: their beds are cut and sanded but hold no water ([`Land::dry_beds`]).
    #[serde(default)]
    pub dry_rivers: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Regions {
    /// Spacing of region centres (regions are warped Voronoi cells).
    pub cell_m: f32,
    pub warp_m: f32,
    /// Mean heights above which a region is highland, or peaks (fraction of the highest point).
    pub highland_m: f32,
    pub peaks_fraction: f32,
    pub treeline_m: f32,
    pub wetlands_per_km2: f32,
    /// Shares of the remaining lowland regions, wettest first.
    pub old_forest_share: f32,
    pub forest_share: f32,
    pub looks: Vec<KindLook>,
}

/// How a region kind's ground is laid out in tiles.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct KindLook {
    pub kind: RegionKind,
    /// Fraction of ground covered by forest tiles.
    pub trees: f32,
    /// Amplitude of local relief (metres).
    pub detail_m: f32,
    /// Width of sand along a sea coast (metres).
    pub beach_m: f32,
    /// Fraction of ground that is rock outcrops, and that is bare dirt or scree.
    pub outcrops: f32,
    pub dirt: f32,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SiteSpec {
    pub kind: SiteKind,
    /// Count = land area (km²) × `per_km2`, clamped to `min..=max`.
    pub min: u32,
    pub max: u32,
    pub per_km2: f32,
    pub radius_m: f32,
    /// Least distance to another site of the same kind.
    pub spacing_m: f32,
    /// Inhabitants' height relative to a 1.75 m adult.
    pub scale: f32,
    /// How strongly the ground is levelled inside the site (0..1).
    pub flatten: f32,
    /// The `buildings.py` style of a settlement that differs from its kind's first style in
    /// [`crate::settle::SettleParams::styles`] (a steampunk or cyberpunk town, say).
    #[serde(default)]
    pub style: Option<String>,
    /// Relief (highest less lowest ground across the site, metres) the site wants; empty for
    /// its kind's own rule. A town that wants relief is terraced.
    #[serde(default)]
    pub relief_m: Option<[f32; 2]>,
    /// Prefer a site near the sea.
    #[serde(default)]
    pub coast: bool,
    /// A dispersed settlement (a hamlet, a farmstead, a hollow in the woods): placed after every
    /// other site, on any ground of `regions` that is not too rough, spread over the island and
    /// over its region kinds rather than drawn to water.
    #[serde(default)]
    pub dispersed: bool,
    /// Region kinds a dispersed site may stand in (empty: meadow, forest, old forest, highland,
    /// beach).
    #[serde(default)]
    pub regions: Vec<RegionKind>,
}

impl Default for LandParams {
    fn default() -> Self {
        Self { cell_m: 8.0, relief: Relief::default(), water: Water::default(), regions: Regions::default(), sites: default_sites(), min_pocket_tiles: 60, settlements: SettleParams::default(), metro: None, plans: Vec::new(), sight: Sight::default() }
    }
}

impl Default for Relief {
    fn default() -> Self {
        Self {
            island_radius: 0.9,
            coast_warp: 0.4,
            coast_feature: 0.3,
            elongation: 1.2,
            lowland_m: 26.0,
            sea_floor_m: 30.0,
            hills_m: 18.0,
            hills_feature_m: 360.0,
            peak_m: [300.0, 480.0],
            range_half_width_m: 250.0,
            range_length: 0.62,
            range_max_length_m: 1900.0,
            range_offset: 0.16,
            two_ranges_m: 2600.0,
            maybe_two_ranges_m: 1600.0,
            foothills_m: 60.0,
            ridge_feature_m: 170.0,
            islets: 2,
            islet_radius_m: [25.0, 60.0],
            land_shift: [0.0, 0.0],
            outline: Vec::new(),
            outline_rise_m: 150.0,
            stamps: Vec::new(),
        }
    }
}

impl Default for Water {
    fn default() -> Self {
        Self {
            river_catchment_m2: 30_000.0,
            river_min_length_m: 350.0,
            river_width_k: 0.009,
            river_width_m: [2.5, 14.0],
            valley_slope: 0.08,
            valley_curve: 0.0016,
            ford_spacing_m: 400.0,
            lakes_per_km2: 0.9,
            lake_radius_m: [70.0, 170.0],
            lake_depth_m: 10.0,
            lake_rim_m: 3.0,
            lake_area_m2: [6_000.0, 120_000.0],
            natural_lakes: 1,
            dry_rivers: false,
        }
    }
}

impl Default for Regions {
    fn default() -> Self {
        let look = |kind, trees, detail_m, beach_m, outcrops, dirt| KindLook { kind, trees, detail_m, beach_m, outcrops, dirt };
        Self {
            cell_m: 320.0,
            warp_m: 150.0,
            highland_m: 150.0,
            peaks_fraction: 0.5,
            treeline_m: 340.0,
            wetlands_per_km2: 0.5,
            old_forest_share: 0.3,
            forest_share: 0.35,
            looks: vec![
                look(RegionKind::Sea, 0.0, 0.5, 30.0, 0.0, 0.0),
                look(RegionKind::Beach, 0.05, 0.7, 30.0, 0.01, 0.02),
                look(RegionKind::Meadow, 0.08, 0.8, 8.0, 0.005, 0.05),
                look(RegionKind::Forest, 0.68, 1.0, 6.0, 0.01, 0.04),
                look(RegionKind::OldForest, 0.92, 1.3, 5.0, 0.015, 0.03),
                look(RegionKind::SpiritGrove, 0.85, 1.2, 5.0, 0.03, 0.02),
                look(RegionKind::Wetland, 0.18, 0.4, 6.0, 0.0, 0.18),
                look(RegionKind::Highland, 0.12, 2.5, 4.0, 0.08, 0.35),
                look(RegionKind::Peaks, 0.02, 4.0, 2.0, 0.22, 0.6),
            ],
        }
    }
}

fn default_sites() -> Vec<SiteSpec> {
    let spec = |kind, min, max, per_km2, radius_m, spacing_m, scale, flatten| SiteSpec { kind, min, max, per_km2, radius_m, spacing_m, scale, flatten, style: None, relief_m: None, coast: false, dispersed: false, regions: Vec::new() };
    vec![
        spec(SiteKind::Town, 1, 1, 0.0, 150.0, 0.0, 1.0, 0.8),
        spec(SiteKind::Giants, 1, 1, 0.0, 130.0, 0.0, 3.0, 0.85),
        spec(SiteKind::SmallFolk, 1, 1, 0.0, 28.0, 0.0, 0.35, 0.6),
        spec(SiteKind::Village, 2, 3, 1.2, 50.0, 450.0, 1.0, 0.75),
        // Two more towns in their own building styles, from about 1.6 km² of land: one on a
        // hillside (terraced), one by the sea.
        SiteSpec { style: Some("steampunk".into()), relief_m: Some([12.0, 44.0]), ..spec(SiteKind::Town, 0, 1, 0.6, 105.0, 500.0, 1.0, 0.4) },
        SiteSpec { style: Some("cyberpunk".into()), relief_m: Some([0.0, 24.0]), coast: true, ..spec(SiteKind::Town, 0, 1, 0.6, 100.0, 500.0, 1.0, 0.65) },
        spec(SiteKind::Cave, 2, 4, 1.2, 5.0, 300.0, 1.0, 0.0),
        // Hamlets: a few houses, barns and fields away from the towns, in meadows, woods and
        // hills (docs/SEEDED_LIVES.md). Placed last, so the sites above stay where they were.
        SiteSpec { style: Some("hamlet".into()), dispersed: true, ..spec(SiteKind::Village, 2, 400, 3.0, 26.0, 230.0, 1.0, 0.6) },
    ]
}

impl Regions {
    fn look(&self, kind: RegionKind) -> KindLook {
        self.looks.iter().find(|l| l.kind == kind).cloned().unwrap_or(KindLook { kind, trees: 0.1, detail_m: 0.8, beach_m: 6.0, outcrops: 0.0, dirt: 0.05 })
    }
}

// ------------------------------------------------------------------------------------------
// Output

#[derive(Clone, Debug, Serialize)]
pub struct Region {
    pub id: u16,
    pub kind: RegionKind,
    pub centre: (f32, f32),
    /// Area of the region, and of its land, in m².
    pub area_m2: f32,
    pub land_m2: f32,
    pub mean_height_m: f32,
}

#[derive(Clone, Debug, Serialize)]
pub struct Site {
    pub kind: SiteKind,
    pub x: f32,
    pub y: f32,
    pub radius_m: f32,
    /// Level the ground is flattened toward.
    pub ground_m: f32,
    /// Inhabitants' height relative to a 1.75 m adult.
    pub scale: f32,
    /// Direction the site faces (radians, x east, y south): downhill for a cave mouth.
    pub facing: f32,
    pub region: RegionKind,
    pub(crate) flatten: f32,
    /// A settlement's building style when it is not its kind's first ([`SiteSpec::style`]).
    pub style: Option<String>,
    /// A ward of the city ([`crate::settle::MetroParams`]): laid out by the city planner, not as a
    /// town of its own.
    #[serde(skip)]
    pub(crate) ward: bool,
    /// The id of the hand-authored plan laid out here ([`crate::settle::PlanSpec`]).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub plan: Option<String>,
}

impl Site {
    /// What a seed calls this kind of site: a plan's id; else the kind (`town`, `village`,
    /// ...), or `<style>_<kind>` for a site with its own style (`steampunk_town`).
    pub fn id(&self) -> String {
        if let Some(p) = &self.plan {
            return p.clone();
        }
        match &self.style {
            Some(st) => format!("{st}_{}", self.kind.id()),
            None => self.kind.id().to_string(),
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct River {
    /// Centre line from source to mouth (metres), with the width at each point.
    pub points: Vec<(f32, f32)>,
    pub width_m: Vec<f32>,
    pub length_m: f32,
    pub source_m: f32,
    pub fords: Vec<(f32, f32)>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Lake {
    pub centre: (f32, f32),
    pub level_m: f32,
    pub area_m2: f32,
    /// Diameter of a circle of the same area.
    pub across_m: f32,
}

#[derive(Clone, Debug, Serialize)]
pub struct Range {
    pub spine: Vec<(f32, f32)>,
    pub half_width_m: f32,
    /// Highest ground near the spine: (x, y, height).
    pub summit: (f32, f32, f32),
    crest_m: f32,
    main_t: f32,
    length_m: f32,
    seed: u64,
}

impl Range {
    /// Distance to the spine and position along it (0..1).
    fn locate(&self, x: f32, y: f32) -> (f32, f32) {
        let segs = self.spine.len() - 1;
        let (mut best, mut bt) = (f32::MAX, 0.0);
        for s in 0..segs {
            let (a, b) = (self.spine[s], self.spine[s + 1]);
            let (dx, dy) = (b.0 - a.0, b.1 - a.1);
            let u = (((x - a.0) * dx + (y - a.1) * dy) / (dx * dx + dy * dy)).clamp(0.0, 1.0);
            let d = (x - a.0 - u * dx).d_hypot(y - a.1 - u * dy);
            if d < best {
                best = d;
                bt = (s as f32 + u) / segs as f32;
            }
        }
        (best, bt)
    }

    fn crest(&self, t: f32) -> f32 {
        let taper = smoothstep(0.0, 0.2, t) * smoothstep(1.0, 0.8, t);
        let v = 0.5 + 0.5 * value(self.seed, t * self.length_m / 280.0, 3.7);
        let bump = (-((t - self.main_t) * self.length_m / 240.0).powi(2)).d_exp();
        self.crest_m * taper * (0.45 + 0.3 * v + 0.55 * bump).min(1.0)
    }
}

/// A generated world: tiles, regions, sites and the fields behind its height.
#[derive(Clone, Debug)]
pub struct Land {
    /// The roads as a graph for known ways ([`crate::ways`]), built by the planner's last step.
    pub ways: Option<crate::ways::Ways>,
    pub seed: u64,
    pub size: u32,
    pub map: Map,
    pub regions: Vec<Region>,
    pub sites: Vec<Site>,
    pub rivers: Vec<River>,
    /// Dry river beds ([`Water::dry_rivers`]): cut and sanded, no water.
    pub dry_beds: Vec<River>,
    pub lakes: Vec<Lake>,
    pub ranges: Vec<Range>,
    /// Blocked tiles opened by the connectivity pass, and small pockets it closed.
    pub opened_tiles: u32,
    pub closed_pockets: u32,
    /// Laid-out towns, villages and the giants' and small folk's settlements.
    pub settlements: Vec<Settlement>,
    /// Building lots, gardens and fields of every settlement.
    pub lots: Vec<Lot>,
    /// Roads between settlements, and every settlement's streets and lanes.
    pub roads: Vec<Road>,
    /// Fords and bridges where roads cross rivers.
    pub crossings: Vec<Crossing>,
    /// Street ornaments, stairs and retaining walls of every settlement, derived from the
    /// layout (not stored by the authority; see `docs/ISLAND_AUTHORITY.md`).
    pub props: Vec<Prop>,
    /// Hand-authored settlements as laid out: their lots' and streets' names, for the authority.
    pub plans: Vec<settle::Laid>,
    pub(crate) mods: settle::Mods,
    n: usize,
    cell: f32,
    elev: Grid,
    detail: Grid,
    surf: Grid,
    maxd: Grid,
    region_of: Vec<u16>,
    node_kind: Vec<RegionKind>,
    /// Signed distance to the water's edge at tile centres (eighths of a metre, negative in water).
    sd: Vec<i8>,
}

impl Land {
    /// Height of the ground at a point (metres; x east, y south). Continuous and finite.
    /// Building lots are level at their floor, and roads follow their graded profiles.
    pub fn height(&self, x: f32, y: f32) -> f32 {
        let sd = self.sd_at(x, y);
        let h = self.natural(x, y, sd);
        let m = self.mods.apply(x, y, h, sd);
        if m < h && sd < 6.5 {
            // A graded road or a pad never lowers a bank below its water; the bound fades out
            // where banks stop following the water.
            let lb = self.surf.bilinear(x, y) - 50.0 * smoothstep(6.0, 6.5, sd);
            return m.max(lb.min(h));
        }
        m
    }

    /// Ground before roads and lots: relief, levelled sites and water shaping.
    fn natural(&self, x: f32, y: f32, sd: f32) -> f32 {
        const R: f32 = 6.0;
        let t = self.terrain(x, y);
        if sd >= 2.0 * R {
            return t;
        }
        let surf = self.surf.bilinear(x, y);
        if sd >= 0.0 {
            // Banks meet the water surface and rise from it at least gently.
            let k = smoothstep(0.0, R, sd);
            let floor = 0.12 * sd.min(R);
            let near = surf + lerp(0.12 * sd, (t - surf).max(floor), k);
            lerp(near, t, smoothstep(R, 2.0 * R, sd))
        } else {
            let d = -sd;
            let bed = surf - (0.6 * d).min(self.maxd.bilinear(x, y));
            lerp(bed, bed.min(t), smoothstep(2.0, 10.0, d))
        }
    }

    /// Surface of the nearest water (metres): the sea at 0, lakes level, rivers sloping.
    pub fn water_level(&self, x: f32, y: f32) -> f32 {
        self.surf.bilinear(x, y)
    }

    /// The region a point belongs to.
    pub fn region_at(&self, x: f32, y: f32) -> &Region {
        &self.regions[self.region_of[self.node_at(x, y)] as usize]
    }

    /// The kind of ground at a point. Differs from its region's kind on coastal land inside a
    /// mostly-sea region (beach).
    pub fn kind_at(&self, x: f32, y: f32) -> RegionKind {
        self.node_kind[self.node_at(x, y)]
    }

    fn node_at(&self, x: f32, y: f32) -> usize {
        // Jitter the lookup so region borders are not drawn along the macro grid.
        let jx = hash(self.seed ^ 0x51, x.floor() as i32, y.floor() as i32) - 0.5;
        let jy = hash(self.seed ^ 0x52, x.floor() as i32, y.floor() as i32) - 0.5;
        let m = self.n as i32 - 1;
        let i = ((x / self.cell + jx).round() as i32).clamp(0, m) as usize;
        let j = ((y / self.cell + jy).round() as i32).clamp(0, m) as usize;
        j * self.n + i
    }

    /// Ground before water shaping: macro relief, local detail and levelled sites.
    fn terrain(&self, x: f32, y: f32) -> f32 {
        let detail = self.detail.bilinear(x, y) * fbm(self.seed ^ 0xD1, x, y, 38.0, 4);
        let mut t = self.elev.cubic(x, y) + detail;
        for s in &self.sites {
            if s.flatten <= 0.0 {
                continue;
            }
            // Only sites within 1.5 radii level this point: a box test first spares the
            // distance for the rest (a land of many hamlets asks this for every tile).
            let r = s.radius_m;
            let (dx, dy) = (x - s.x, y - s.y);
            if dx.abs() >= r * 1.5 || dy.abs() >= r * 1.5 {
                continue;
            }
            let d = dx.d_hypot(dy);
            if d < r * 1.5 {
                let w = (1.0 - smoothstep(r * 0.8, r * 1.5, d)) * s.flatten;
                t = lerp(t, s.ground_m + 0.3 * detail, w);
            }
        }
        t
    }

    /// Signed distance to the water's edge (metres, negative in water, within about 16 m).
    pub(crate) fn sd_at(&self, x: f32, y: f32) -> f32 {
        let w = self.size as i32;
        let (gx, gy) = (x - 0.5, y - 0.5);
        let (x0, y0) = (gx.floor(), gy.floor());
        let (tx, ty) = (gx - x0, gy - y0);
        let (x0, y0) = (x0 as i32, y0 as i32);
        let at = |i: i32, j: i32| self.sd[(j.clamp(0, w - 1) * w + i.clamp(0, w - 1)) as usize] as f32 / 8.0;
        lerp(lerp(at(x0, y0), at(x0 + 1, y0), tx), lerp(at(x0, y0 + 1), at(x0 + 1, y0 + 1), tx), ty)
    }

    /// Recompute the signed water distance around tiles `lo..=hi` after they changed.
    pub(crate) fn update_sd(&mut self, lo: (i32, i32), hi: (i32, i32)) {
        let w = self.size as i32;
        // Distances are clamped at 15.8 m, so a 17 m window decides every tile within 16 m.
        let (x0, y0, x1, y1) = ((lo.0 - 33).max(0), (lo.1 - 33).max(0), (hi.0 + 33).min(w - 1), (hi.1 + 33).min(w - 1));
        let (ww, wh) = ((x1 - x0 + 1) as usize, (y1 - y0 + 1) as usize);
        let water = |i: usize, j: usize| self.map.tiles[(j + y0 as usize) * w as usize + i + x0 as usize] == Terrain::Water as u8;
        let mut d = vec![0f32; ww * wh];
        let mut out = vec![0i8; ww * wh];
        for (pass, inside) in [(0, false), (1, true)] {
            for j in 0..wh {
                for i in 0..ww {
                    d[j * ww + i] = if water(i, j) != inside { 0.0 } else { f32::INFINITY };
                }
            }
            chamfer(ww, wh, 1.0, &mut d, None);
            for j in 0..wh {
                for i in 0..ww {
                    if water(i, j) == inside {
                        let v = (d[j * ww + i] - 0.5).min(15.8);
                        out[j * ww + i] = ((if pass == 1 { -v } else { v }) * 8.0).round().clamp(-127.0, 127.0) as i8;
                    }
                }
            }
        }
        for y in (lo.1 - 16).max(0)..=(hi.1 + 16).min(w - 1) {
            for x in (lo.0 - 16).max(0)..=(hi.0 + 16).min(w - 1) {
                self.sd[(y * w + x) as usize] = out[((y - y0) as usize) * ww + (x - x0) as usize];
            }
        }
    }
}

// ------------------------------------------------------------------------------------------
// Noise and helpers

fn mix(mut h: u64) -> u64 {
    h ^= h >> 30;
    h = h.wrapping_mul(0xBF58_476D_1CE4_E5B9);
    h ^= h >> 27;
    h = h.wrapping_mul(0x94D0_49BB_1331_11EB);
    h ^ (h >> 31)
}

pub(crate) fn hash(seed: u64, x: i32, y: i32) -> f32 {
    let h = mix(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ mix(((x as u32 as u64) << 32) | y as u32 as u64));
    (h >> 40) as f32 / (1u64 << 24) as f32
}

fn fade(t: f32) -> f32 {
    t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
}

/// Value noise in [-1, 1] with unit feature size.
pub(crate) fn value(seed: u64, x: f32, y: f32) -> f32 {
    let (x0, y0) = (x.floor(), y.floor());
    let (fx, fy) = (fade(x - x0), fade(y - y0));
    let (i, j) = (x0 as i32, y0 as i32);
    let top = lerp(hash(seed, i, j), hash(seed, i + 1, j), fx);
    let bottom = lerp(hash(seed, i, j + 1), hash(seed, i + 1, j + 1), fx);
    lerp(top, bottom, fy) * 2.0 - 1.0
}

/// Each octave turns by this angle, so value noise's grid does not show as axis-aligned blocks.
const TURN: (f32, f32) = (0.8253356, 0.5646425); // cos, sin of 0.6 rad

fn turn(x: f32, y: f32) -> (f32, f32) {
    (x * TURN.0 - y * TURN.1, x * TURN.1 + y * TURN.0)
}

fn fbm(seed: u64, x: f32, y: f32, feature: f32, octaves: u32) -> f32 {
    let (mut sum, mut norm, mut a, mut f) = (0.0, 0.0, 1.0, 1.0 / feature);
    let (mut x, mut y) = turn(x, y);
    for o in 0..octaves {
        sum += a * value(seed.wrapping_add(o as u64 * 7919), x * f, y * f);
        (x, y) = turn(x, y);
        norm += a;
        a *= 0.5;
        f *= 2.03;
    }
    sum / norm
}

/// Ridged noise in [0, 1]: 1 along ridge lines.
fn ridged(seed: u64, x: f32, y: f32, feature: f32, octaves: u32) -> f32 {
    let (mut sum, mut norm, mut a, mut f) = (0.0, 0.0, 1.0, 1.0 / feature);
    let (mut x, mut y) = turn(x, y);
    for o in 0..octaves {
        sum += a * (1.0 - value(seed.wrapping_add(o as u64 * 104_729), x * f, y * f).abs()).powi(2);
        (x, y) = turn(x, y);
        norm += a;
        a *= 0.5;
        f *= 2.03;
    }
    sum / norm
}

pub(crate) fn lerp(a: f32, b: f32, t: f32) -> f32 {
    a + (b - a) * t
}

pub(crate) fn smoothstep(a: f32, b: f32, x: f32) -> f32 {
    let t = ((x - a) / (b - a)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

struct Rng(u64);

impl Rng {
    fn f(&mut self) -> f32 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        (mix(self.0) >> 40) as f32 / (1u64 << 24) as f32
    }
    fn range(&mut self, r: [f32; 2]) -> f32 {
        lerp(r[0], r[1], self.f())
    }
}

/// Values at macro nodes; node (i, j) sits at (i × cell, j × cell).
#[derive(Clone, Debug)]
struct Grid {
    n: usize,
    cell: f32,
    v: Vec<f32>,
}

impl Grid {
    fn new(n: usize, cell: f32, v: Vec<f32>) -> Self {
        debug_assert_eq!(v.len(), n * n);
        Self { n, cell, v }
    }

    fn get(&self, i: isize, j: isize) -> f32 {
        let m = self.n as isize - 1;
        self.v[(j.clamp(0, m) * self.n as isize + i.clamp(0, m)) as usize]
    }

    fn bilinear(&self, x: f32, y: f32) -> f32 {
        let (gx, gy) = (x / self.cell, y / self.cell);
        let (i, j) = (gx.floor(), gy.floor());
        let (tx, ty) = (gx - i, gy - j);
        let (i, j) = (i as isize, j as isize);
        lerp(lerp(self.get(i, j), self.get(i + 1, j), tx), lerp(self.get(i, j + 1), self.get(i + 1, j + 1), tx), ty)
    }

    /// Catmull-Rom: smooth (C1) between nodes, so hill shading shows no grid facets.
    fn cubic(&self, x: f32, y: f32) -> f32 {
        fn cr(p0: f32, p1: f32, p2: f32, p3: f32, t: f32) -> f32 {
            p1 + 0.5 * t * (p2 - p0 + t * (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3 + t * (3.0 * (p1 - p2) + p3 - p0)))
        }
        let (gx, gy) = (x / self.cell, y / self.cell);
        let (i, j) = (gx.floor(), gy.floor());
        let (tx, ty) = (gx - i, gy - j);
        let (i, j) = (i as isize, j as isize);
        let row = |jj: isize| cr(self.get(i - 1, jj), self.get(i, jj), self.get(i + 1, jj), self.get(i + 2, jj), tx);
        cr(row(j - 1), row(j), row(j + 1), row(j + 2), ty)
    }

    fn blur(&mut self, r: isize, passes: usize) {
        let n = self.n as isize;
        let k = (2 * r + 1) as f32;
        for _ in 0..passes {
            let mut tmp = vec![0.0; self.v.len()];
            for j in 0..n {
                for i in 0..n {
                    tmp[(j * n + i) as usize] = (-r..=r).map(|d| self.get(i + d, j)).sum::<f32>() / k;
                }
            }
            let src = Grid::new(self.n, self.cell, tmp);
            for j in 0..n {
                for i in 0..n {
                    self.v[(j * n + i) as usize] = (-r..=r).map(|d| src.get(i, j + d)).sum::<f32>() / k;
                }
            }
        }
    }
}

#[derive(PartialEq)]
struct Open(f32, u32);
impl Eq for Open {}
impl Ord for Open {
    fn cmp(&self, o: &Self) -> Ordering {
        o.0.total_cmp(&self.0).then(o.1.cmp(&self.1))
    }
}
impl PartialOrd for Open {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}

/// 8-neighbour offsets with their distance in cells.
const D8: [(isize, isize, f32); 8] = [
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, std::f32::consts::SQRT_2),
    (1, -1, std::f32::consts::SQRT_2),
    (-1, 1, std::f32::consts::SQRT_2),
    (-1, -1, std::f32::consts::SQRT_2),
];

/// Two-pass chamfer distance (in place: 0 at sources, infinity elsewhere), also tracking the
/// nearest source when `src` is given.
fn chamfer(w: usize, h: usize, step: f32, d: &mut [f32], mut src: Option<&mut [u32]>) {
    let diag = step * std::f32::consts::SQRT_2;
    let fwd = [(-1isize, 0isize, step), (0, -1, step), (-1, -1, diag), (1, -1, diag)];
    let bwd = [(1isize, 0isize, step), (0, 1, step), (1, 1, diag), (-1, 1, diag)];
    for (pass, nb) in [(0, fwd), (1, bwd)] {
        for jj in 0..h {
            for ii in 0..w {
                let (i, j) = if pass == 0 { (ii, jj) } else { (w - 1 - ii, h - 1 - jj) };
                let k = j * w + i;
                for (dx, dy, c) in nb {
                    let (x, y) = (i as isize + dx, j as isize + dy);
                    if x < 0 || y < 0 || x >= w as isize || y >= h as isize {
                        continue;
                    }
                    let q = y as usize * w + x as usize;
                    if d[q] + c < d[k] {
                        d[k] = d[q] + c;
                        if let Some(s) = src.as_deref_mut() {
                            s[k] = s[q];
                        }
                    }
                }
            }
        }
    }
}

// ------------------------------------------------------------------------------------------
// Generation

pub fn generate_default(seed: u64, size_m: u32) -> Land {
    generate(seed, size_m, &LandParams::default())
}

/// Generate a square world `size_m` metres on a side: every step of [`Gen`] in one call.
pub fn generate(seed: u64, size_m: u32, p: &LandParams) -> Land {
    let mut g = Gen::new(seed, size_m, p.clone());
    while !g.step() {}
    g.into_land()
}

/// Tiles classified per step of [`Gen`]: rows are banded so each step stays well inside a
/// SpacetimeDB reducer's fuel budget (`docs/FLOORS.md`, staged generation).
const BAND_TILES: usize = 4 << 20;

/// Generation in steps, each bounded in work, so a caller with a per-call budget (a SpacetimeDB
/// reducer: 120 × 10⁹ instructions) can generate a land of any supported size across calls. The
/// steps are the macro pass in two halves (relief and rivers; regions, sites, river beds), bands of tile rows, the
/// connectivity pass, the shore distances, then [`settle::Staged`]'s planner steps. Running them
/// all in order is [`generate`], so staged and one-shot generation give identical lands.
pub struct Gen {
    seed: u64,
    size: u32,
    p: LandParams,
    next: Next,
    hydro: Option<Box<Hydro>>,
    work: Option<Box<Work>>,
    land: Option<Land>,
    plan: settle::Staged,
    /// Dispersed-site steps run.
    dispersed_done: u32,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Next {
    Hydro,
    Macro,
    /// Dispersed sites (hamlets), a bounded number per step, after the other sites and before
    /// the tiles (their ground is levelled like any site's).
    Dispersed,
    Rows(usize),
    Connect,
    Shore(usize),
    Plan,
    Done,
}

/// What the dispersed-site steps need from the macro pass, and how far they are.
struct SiteWork {
    wd: Vec<f32>,
    still_d: Vec<f32>,
    sea_d: Vec<f32>,
    max_e: f32,
    land_km2: f32,
    avoid: Option<((f32, f32), f32)>,
    /// The dispersed spec being placed (index among the dispersed ones) and its state.
    spec: usize,
    state: SpecState,
    steps: u32,
}

/// Dispersed sites (hamlets) placed per step of [`Gen`]: each pick scans the candidates once
/// against the placed sites near them, so a step's work is bounded by this many scans.
const DISPERSED_PER_STEP: usize = 24;

/// What the tile steps need from the macro pass.
struct Work {
    /// Dispersed sites still to place (none: done, or the land has no dispersed specs).
    sites: Option<Box<SiteWork>>,
    land: Land,
    rmask: Vec<u8>,
    fords: Vec<((f32, f32), (f32, f32), f32)>,
    still: Grid,
    wet: Grid,
    beach: Grid,
    outcrops: Grid,
    trees: Grid,
    dirt: Grid,
    tiles: Vec<u8>,
    sd: Vec<i8>,
}

impl Gen {
    pub fn new(seed: u64, size_m: u32, p: LandParams) -> Self {
        assert!((256..=MAX_SIDE).contains(&size_m), "land side {size_m} m outside 256..={MAX_SIDE}");
        let mut plan = settle::Staged::default();
        plan.specs = p.plans.clone();
        Self { seed, size: size_m, p, next: Next::Hydro, hydro: None, work: None, land: None, plan, dispersed_done: 0 }
    }

    fn band_rows(&self) -> usize {
        (BAND_TILES / self.size as usize).max(1)
    }

    /// Steps in all, for progress: the macro pass, the dispersed sites, the bands, connect,
    /// shore and the planner.
    pub fn steps(&self) -> u32 {
        let bands = (self.size as usize).div_ceil(self.band_rows()) as u32;
        2 + self.dispersed_steps() + bands + 3 + self.plan.steps()
    }

    /// Dispersed-site steps: done ones, plus the batches still wanted once the macro pass says
    /// how many (before it, one per dispersed spec).
    fn dispersed_steps(&self) -> u32 {
        let specs = self.p.sites.iter().filter(|sp| sp.dispersed).count() as u32;
        match self.work.as_ref().and_then(|w| w.sites.as_ref()) {
            Some(sw) => {
                let land = &self.work.as_ref().expect("work").land;
                let left: usize = self.p.sites.iter().filter(|sp| sp.dispersed).skip(sw.spec).map(|sp| ((sw.land_km2 * sp.per_km2).round() as u32).clamp(sp.min, sp.max) as usize).sum::<usize>().saturating_sub(land.sites.iter().filter(|q| self.p.sites.iter().filter(|sp| sp.dispersed).skip(sw.spec).any(|sp| sp.kind == q.kind && sp.style == q.style)).count());
                sw.steps + (left.div_ceil(DISPERSED_PER_STEP) as u32).max(1)
            }
            None if matches!(self.next, Next::Hydro | Next::Macro) => specs,
            None => self.dispersed_done,
        }
    }

    /// Steps done so far.
    pub fn done(&self) -> u32 {
        let bands = (self.size as usize).div_ceil(self.band_rows()) as u32;
        match self.next {
            Next::Hydro => 0,
            Next::Macro => 1,
            Next::Dispersed => 2 + self.dispersed_done,
            Next::Rows(j) => 2 + self.dispersed_done + (j / self.band_rows()) as u32,
            Next::Connect => 2 + self.dispersed_done + bands,
            Next::Shore(k) => 3 + self.dispersed_done + bands + k as u32,
            Next::Plan => 5 + self.dispersed_done + bands + self.plan.done(),
            Next::Done => self.steps(),
        }
    }

    /// What the next step does.
    pub fn label(&self) -> String {
        match self.next {
            Next::Hydro => "relief, lakes and rivers".into(),
            Next::Macro => "water, regions and sites".into(),
            Next::Dispersed => format!("dispersed sites (step {})", self.dispersed_done + 1),
            Next::Rows(j) => format!("tiles, rows {j}..{}", (j + self.band_rows()).min(self.size as usize)),
            Next::Connect => "connectivity".into(),
            Next::Shore(0) => "shore distances on land".into(),
            Next::Shore(_) => "shore distances in water".into(),
            Next::Plan => format!("plan: {}", self.plan.label()),
            Next::Done => "done".into(),
        }
    }

    /// Run the next step; true once the land is complete ([`Gen::into_land`]).
    pub fn step(&mut self) -> bool {
        let w = self.size as usize;
        match self.next {
            Next::Hydro => {
                self.hydro = Some(Box::new(hydro_pass(self.seed, self.size, &self.p)));
                self.next = Next::Macro;
            }
            Next::Macro => {
                self.work = Some(Box::new(macro_pass(*self.hydro.take().expect("hydro pass"), &self.p)));
                self.next = if self.work.as_ref().is_some_and(|w| w.sites.is_some()) { Next::Dispersed } else { Next::Rows(0) };
            }
            Next::Dispersed => {
                let wk = self.work.as_mut().expect("macro pass");
                self.dispersed_done += 1;
                if dispersed_step(wk, &self.p) {
                    wk.sites = None;
                    self.next = Next::Rows(0);
                }
            }
            Next::Rows(j0) => {
                let j1 = (j0 + self.band_rows()).min(w);
                tile_rows(self.work.as_mut().expect("macro pass"), &self.p, j0, j1);
                self.next = if j1 >= w { Next::Connect } else { Next::Rows(j1) };
            }
            Next::Connect => {
                connect_pass(self.work.as_mut().expect("tiles"), &self.p);
                self.next = Next::Shore(0);
            }
            Next::Shore(k) => {
                shore_pass(self.work.as_mut().expect("tiles"), k);
                if k == 0 {
                    self.next = Next::Shore(1);
                } else {
                    self.land = Some(finish_tiles(*self.work.take().expect("tiles")));
                    self.next = Next::Plan;
                }
            }
            Next::Plan => {
                let land = self.land.as_mut().expect("land");
                if self.plan.step(land, &self.p.settlements, self.p.metro.as_ref()) {
                    self.next = Next::Done;
                }
            }
            Next::Done => {}
        }
        self.next == Next::Done
    }

    pub fn is_done(&self) -> bool {
        self.next == Next::Done
    }

    /// The finished land (panics before the last step).
    pub fn into_land(self) -> Land {
        assert!(self.next == Next::Done, "land generation is not finished");
        self.land.expect("land")
    }
}

/// Place up to [`DISPERSED_PER_STEP`] dispersed sites, in the dispersed specs' order; true once
/// every one is placed. The same picks as placing them all at once.
fn dispersed_step(wk: &mut Work, p: &LandParams) -> bool {
    let Some(sw) = wk.sites.as_mut() else { return true };
    let land = &mut wk.land;
    let mut placed = std::mem::take(&mut land.sites);
    let SiteWork { wd, still_d, sea_d, max_e, land_km2, avoid, spec, state, steps } = &mut **sw;
    *steps += 1;
    let elev = &land.elev.v;
    let c = SiteCtx { p, n: land.n, cell: land.cell, s: land.size as f32, elev, wd, still_d, sea_d, node_kind: &land.node_kind, max_e: *max_e, land_km2: *land_km2, seed: land.seed, avoid: *avoid };
    let specs: Vec<&SiteSpec> = p.sites.iter().filter(|sp| sp.dispersed).collect();
    let mut budget = DISPERSED_PER_STEP;
    while *spec < specs.len() {
        if !place_spec(&c, &|k| node_slope(elev, c.n, c.cell, k), specs[*spec], &mut placed, state, &mut budget) {
            break;
        }
        *spec += 1;
        *state = SpecState::default();
    }
    land.sites = placed;
    *spec >= specs.len()
}

/// The ground's slope at a macro node (as the macro pass computes it).
fn node_slope(elev: &[f32], n: usize, cell: f32, k: usize) -> f32 {
    let (i, j) = ((k % n) as isize, (k / n) as isize);
    let g = |a: isize, b: isize| elev[(b.clamp(0, n as isize - 1) as usize) * n + a.clamp(0, n as isize - 1) as usize];
    ((g(i + 1, j) - g(i - 1, j)) / (2.0 * cell)).d_hypot((g(i, j + 1) - g(i, j - 1)) / (2.0 * cell))
}

/// The first half of the macro pass, on the `cell_m` grid: relief, lakes, rivers and valleys.
fn hydro_pass(seed: u64, size_m: u32, p: &LandParams) -> Hydro {
    let s = size_m as f32;
    let cell = p.cell_m;
    let n = (s / cell).ceil() as usize + 1;
    let nn = n * n;
    let pos = |k: usize| ((k % n) as f32 * cell, (k / n) as f32 * cell);
    let mut rng = Rng(seed ^ 0x1A2D);
    let scale = (s / 2048.0).clamp(0.6, 1.0);
    let r = &p.relief;
    // The city's centre and radius, if the land holds one: no ranges or lakes inside it, and its
    // ground is levelled.
    let city: Option<((f32, f32), f32, f32)> = p.metro.as_ref().map(|m| ((m.centre[0] * s, m.centre[1] * s), m.radius * s * 0.5, m.flatten));
    // Hand-authored settlements: no islets or lakes on them, and the relief follows their levels.
    let plans: Vec<settle::PlanResolved> = p.plans.iter().map(|sp| settle::resolve_plan(sp).unwrap_or_else(|e| panic!("{e}"))).collect();
    let near_plan = |x: f32, y: f32, m: f32| plans.iter().any(|q| settle::plan_covers(q, (x, y), m));

    // Island shape and ranges.
    let centre = (s * 0.5 + (rng.f() - 0.5) * s * 0.04, s * 0.5 + (rng.f() - 0.5) * s * 0.04);
    let mut ranges = plan_ranges(&mut rng, seed, s, centre, scale, r);
    let axis = {
        let sp = &ranges[0].spine;
        let (dx, dy) = (sp[sp.len() - 1].0 - sp[0].0, sp[sp.len() - 1].1 - sp[0].1);
        let l = dx.d_hypot(dy).max(1e-3);
        (dx / l, dy / l)
    };
    let lc = (centre.0 + r.land_shift[0] * s, centre.1 + r.land_shift[1] * s);
    let outline: Vec<(f32, f32)> = r.outline.iter().map(|q| (q[0], q[1])).collect();
    let landness = |x: f32, y: f32| {
        if !outline.is_empty() {
            // An authored coast: the distance inside it, roughened like the generated one.
            let k = r.coast_warp * s * 0.5;
            let wx = x + k * fbm(seed ^ 0x11, x, y, r.coast_feature * s, 4);
            let wy = y + k * fbm(seed ^ 0x12, x, y, r.coast_feature * s, 4);
            return poly_signed(&outline, (wx, wy)) / r.outline_rise_m;
        }
        let u = (x - lc.0) / (s * 0.5) + r.coast_warp * fbm(seed ^ 0x11, x, y, r.coast_feature * s, 4);
        let v = (y - lc.1) / (s * 0.5) + r.coast_warp * fbm(seed ^ 0x12, x, y, r.coast_feature * s, 4);
        let (a, b) = ((u * axis.0 + v * axis.1) / r.elongation, (-u * axis.1 + v * axis.0) * r.elongation.sqrt());
        1.0 - a.d_hypot(b) / r.island_radius
    };

    // Raw elevation.
    let mut elev = vec![0f32; nn];
    for (k, e) in elev.iter_mut().enumerate() {
        let (x, y) = pos(k);
        let land = landness(x, y);
        let shape = (land * 3.0).d_tanh();
        let low = if shape >= 0.0 { r.lowland_m * shape } else { r.sea_floor_m * shape };
        let hills = r.hills_m * fbm(seed ^ 0x13, x, y, r.hills_feature_m, 4) * smoothstep(-0.05, 0.3, land);
        let (mut mount, mut foot) = (0f32, 0f32);
        for g in &ranges {
            let (d, t) = g.locate(x, y);
            let w = g.half_width_m;
            let prof = (-(d / w).powi(2)).d_exp();
            if prof > 1e-4 {
                let rn = ridged(seed ^ 0x14, x, y, r.ridge_feature_m, 4);
                mount = mount.max(g.crest(t) * prof * (0.45 + 0.55 * rn));
            }
            let taper = smoothstep(-0.15, 0.25, t) * smoothstep(1.15, 0.75, t);
            foot += r.foothills_m * (g.crest_m / r.peak_m[1]) * (-(d / (2.2 * w)).powi(2)).d_exp() * taper * (0.6 + 0.4 * fbm(seed ^ 0x15, x, y, 300.0, 3));
        }
        *e = match city {
            None => low + hills + (mount + foot) * smoothstep(-0.12, 0.1, land),
            Some((cc, cr, flat)) => {
                // Ranges rise only beyond the city's edge; inside it the ground is levelled
                // toward the plain, keeping a little of its relief.
                let d = (x - cc.0).d_hypot(y - cc.1);
                let inside = 1.0 - smoothstep(cr * 0.95, cr * 1.3, d);
                let raw = low + hills + (mount + foot) * smoothstep(-0.12, 0.1, land) * smoothstep(cr * 1.05, cr * 1.7, d);
                if land > 0.0 {
                    lerp(raw, r.lowland_m * 0.7 + 0.25 * hills, inside * flat)
                } else {
                    raw
                }
            }
        };
    }
    let slope_of = |elev: &[f32], k: usize| {
        let (i, j) = ((k % n) as isize, (k / n) as isize);
        let g = |a: isize, b: isize| elev[(b.clamp(0, n as isize - 1) as usize) * n + a.clamp(0, n as isize - 1) as usize];
        ((g(i + 1, j) - g(i - 1, j)) / (2.0 * cell)).d_hypot((g(i, j + 1) - g(i, j - 1)) / (2.0 * cell))
    };

    // Islets just offshore.
    for _ in 0..r.islets {
        for _try in 0..400 {
            let k = (rng.f() * nn as f32) as usize % nn;
            let (x, y) = pos(k);
            let e = elev[k];
            if !(-14.0..=-3.0).contains(&e) || x.min(y).min(s - x).min(s - y) < 150.0 || near_plan(x, y, 150.0) {
                continue;
            }
            let rad = rng.range(r.islet_radius_m);
            let top = 3.0 + rng.f() * 12.0;
            stamp(&mut elev, n, cell, (x, y), rad, |e0, q, _, _| e0 + (top - e0) * (1.0 - q * q).powi(2));
            break;
        }
    }

    // Authored stamps (applied below, after the lake basins, which keep off them).
    let stamps: Vec<(Vec<(f32, f32)>, &Stamp)> = r.stamps.iter().map(|st| (st.poly(), st)).collect();

    // Lake basins: a bowl with a rim, on flat-ish ground away from coast and spine.
    let land_nodes = elev.iter().filter(|e| **e > 0.0).count();
    let land_km2 = land_nodes as f32 * cell * cell / 1e6;
    let want_lakes = ((land_km2 * p.water.lakes_per_km2).round() as usize).clamp(1, 6);
    let mut basins: Vec<(f32, f32, f32)> = Vec::new();
    for _try in 0..3000 {
        if basins.len() >= want_lakes {
            break;
        }
        let k = (rng.f() * nn as f32) as usize % nn;
        let (x, y) = pos(k);
        let e = elev[k];
        let rad = rng.range(p.water.lake_radius_m) * scale.max(0.8);
        let spine = ranges.iter().map(|g| g.locate(x, y).0 / g.half_width_m).fold(f32::MAX, f32::min);
        if e < 6.0 || landness(x, y) < 0.22 || slope_of(&elev, k) > 0.07 || spine < 0.9 || spine > 4.0 {
            continue;
        }
        if city.is_some_and(|(cc, cr, _)| (x - cc.0).d_hypot(y - cc.1) < cr * 1.15 + rad * 1.9) {
            continue;
        }
        if near_plan(x, y, rad * 1.9 + 120.0) {
            continue;
        }
        if stamps.iter().any(|(q, st)| poly_signed(q, (x, y)) > -(rad * 1.9 + st.blend_m)) {
            continue;
        }
        if basins.iter().any(|b| (b.0 - x).d_hypot(b.1 - y) < 450.0) {
            continue;
        }
        let (rim, depth) = (p.water.lake_rim_m, p.water.lake_depth_m);
        stamp(&mut elev, n, cell, (x, y), rad * 1.9, |e0, q, px, py| {
            // Irregular shores: the bowl's radius varies around it.
            let d = q * 1.9 / (1.0 + 0.35 * fbm(seed ^ 0x18, px, py, rad * 0.7, 2));
            let bowl = if d < 1.0 { lerp(e0, e - depth, (1.0 - d * d).powi(2)) } else { e0 };
            // The rim: level with the lake at 0.75..1 radius, falling away outside and inside.
            let dam = e + rim - 0.3 * (d - 1.0).max(0.0) * rad - 0.8 * (0.75 - d).max(0.0) * rad;
            bowl.max(dam)
        });
        basins.push((x, y, rad));
    }

    for (q, st) in &stamps {
        let Some(h) = st.height_m else { continue };
        let lo = q.iter().fold((f32::MAX, f32::MAX), |m, v| (m.0.min(v.0), m.1.min(v.1)));
        let hi = q.iter().fold((f32::MIN, f32::MIN), |m, v| (m.0.max(v.0), m.1.max(v.1)));
        let pad = st.blend_m + cell;
        let (i0, j0) = ((((lo.0 - pad) / cell).floor().max(0.0)) as usize, (((lo.1 - pad) / cell).floor().max(0.0)) as usize);
        let (i1, j1) = ((((hi.0 + pad) / cell).ceil().max(0.0)) as usize, (((hi.1 + pad) / cell).ceil().max(0.0)) as usize);
        for j in j0..=j1.min(n - 1) {
            for i in i0..=i1.min(n - 1) {
                let k = j * n + i;
                let d = -poly_signed(q, pos(k));
                let w = if d <= 0.0 { 1.0 } else if st.blend_m <= 0.0 { 0.0 } else { 1.0 - smoothstep(0.0, st.blend_m, d) };
                if w > 0.0 {
                    elev[k] = lerp(elev[k], h, w);
                }
            }
        }
    }

    settle::stamp_plans(&mut elev, n, cell, &plans);

    // Sea: below zero and connected to the border.
    let mut sea = vec![false; nn];
    {
        let mut q = VecDeque::new();
        for k in 0..nn {
            let (i, j) = (k % n, k / n);
            if (i == 0 || j == 0 || i == n - 1 || j == n - 1) && elev[k] < 0.0 {
                sea[k] = true;
                q.push_back(k);
            }
        }
        while let Some(k) = q.pop_front() {
            for (dx, dy, _) in D8 {
                if let Some(nb) = step(n, k, dx, dy) {
                    if !sea[nb] && elev[nb] < 0.0 {
                        sea[nb] = true;
                        q.push_back(nb);
                    }
                }
            }
        }
    }

    // Priority flood from the sea: filled levels and a drainage tree. Routing runs on slightly
    // noisy ground so rivers wander instead of following straight grid lines.
    let route: Vec<f32> = (0..nn).map(|k| elev[k] + 3.0 * fbm(seed ^ 0x17, pos(k).0, pos(k).1, 90.0, 3)).collect();
    let mut fill = route.clone();
    let mut recv = vec![NONE; nn];
    let mut closed = sea.clone();
    let mut order: Vec<u32> = Vec::with_capacity(nn);
    let mut heap = BinaryHeap::new();
    for k in 0..nn {
        let (i, j) = (k % n, k / n);
        if sea[k] {
            heap.push(Open(0.0, k as u32));
        } else if i == 0 || j == 0 || i == n - 1 || j == n - 1 {
            closed[k] = true;
            order.push(k as u32);
            heap.push(Open(route[k], k as u32));
        }
    }
    while let Some(Open(level, k)) = heap.pop() {
        for (dx, dy, c) in D8 {
            if let Some(nb) = step(n, k as usize, dx, dy) {
                if closed[nb] {
                    continue;
                }
                closed[nb] = true;
                fill[nb] = route[nb].max(level.max(0.0) + 1e-3 * c);
                recv[nb] = k;
                order.push(nb as u32);
                heap.push(Open(fill[nb], nb as u32));
            }
        }
    }

    // Depressions: designated basins and a few natural ones become lakes; the rest are filled.
    let mut lake_of = vec![NONE; nn];
    let mut lakes: Vec<Lake> = Vec::new();
    {
        let mut seen = vec![false; nn];
        let mut natural: Vec<(usize, Vec<usize>)> = Vec::new();
        let mut kept: Vec<Vec<usize>> = Vec::new();
        for start in 0..nn {
            if seen[start] || sea[start] || fill[start] - route[start] < 0.25 {
                continue;
            }
            let mut comp = vec![start];
            seen[start] = true;
            let mut h = 0;
            while h < comp.len() {
                let k = comp[h];
                h += 1;
                for (dx, dy, _) in D8 {
                    if let Some(nb) = step(n, k, dx, dy) {
                        if !seen[nb] && !sea[nb] && fill[nb] - route[nb] >= 0.25 {
                            seen[nb] = true;
                            comp.push(nb);
                        }
                    }
                }
            }
            let area = comp.len() as f32 * cell * cell;
            let depth = comp.iter().map(|&k| fill[k] - route[k]).fold(0.0, f32::max);
            let designated = basins.iter().any(|b| comp.iter().any(|&k| (pos(k).0 - b.0).d_hypot(pos(k).1 - b.1) < cell * 2.0));
            if designated && area <= p.water.lake_area_m2[1] * 2.5 {
                kept.push(comp);
            } else if !designated && depth >= 1.5 && area >= p.water.lake_area_m2[0] && area <= p.water.lake_area_m2[1] {
                natural.push((comp.len(), comp));
            }
            // Other depressions keep their shape: rivers breach their rims below.
        }
        natural.sort_by(|a, b| b.0.cmp(&a.0));
        for (i, (_, comp)) in natural.into_iter().enumerate() {
            if i < p.water.natural_lakes as usize {
                kept.push(comp);
            }
        }
        for comp in kept {
            let id = lakes.len() as u32;
            let level = comp.iter().map(|&k| fill[k]).fold(f32::MIN, f32::max);
            let (mut cx, mut cy) = (0.0, 0.0);
            for &k in &comp {
                lake_of[k] = id;
                cx += pos(k).0;
                cy += pos(k).1;
            }
            let area = comp.len() as f32 * cell * cell;
            lakes.push(Lake { centre: (cx / comp.len() as f32, cy / comp.len() as f32), level_m: level, area_m2: area, across_m: 2.0 * (area / std::f32::consts::PI).sqrt() });
        }
    }

    // Flow accumulation and rivers.
    let mut acc = vec![0f32; nn];
    for &k in order.iter().rev() {
        let k = k as usize;
        acc[k] += cell * cell;
        if recv[k] != NONE {
            acc[recv[k] as usize] += acc[k];
        }
    }
    let is_river = |k: usize| !sea[k] && lake_of[k] == NONE && acc[k] >= p.water.river_catchment_m2;
    let mut child = vec![false; nn];
    for k in 0..nn {
        if is_river(k) && recv[k] != NONE {
            child[recv[k] as usize] = true;
        }
    }
    let mut paths: Vec<Vec<usize>> = (0..nn)
        .filter(|&k| is_river(k) && !child[k])
        .map(|src| {
            let mut path = vec![src];
            let mut k = src;
            while recv[k] != NONE && !sea[k] {
                k = recv[k] as usize;
                path.push(k);
            }
            path
        })
        .collect();
    paths.sort_by_key(|p| std::cmp::Reverse(p.len()));
    let mut drawn = vec![false; nn];
    let mut river_nodes: Vec<Vec<usize>> = Vec::new();
    for path in paths {
        let mut part = Vec::new();
        for &k in &path {
            part.push(k);
            if drawn[k] {
                break;
            }
        }
        let len = part.len() as f32 * cell * 1.15;
        if len < p.water.river_min_length_m && !river_nodes.is_empty() {
            continue;
        }
        for &k in &part {
            drawn[k] = true;
        }
        river_nodes.push(part);
    }

    // River levels fall monotonically from source to mouth: where a river meets a rim, it cuts
    // through it (breaching) instead of filling the hollow behind.
    let mut rlevel = vec![f32::NAN; nn];
    for part in &river_nodes {
        let mut lvl = f32::INFINITY;
        for &k in part {
            if !rlevel[k].is_nan() {
                break;
            }
            lvl = if sea[k] {
                0.0
            } else if lake_of[k] != NONE {
                lakes[lake_of[k] as usize].level_m
            } else {
                (lvl - 1e-3).min(elev[k])
            };
            rlevel[k] = lvl;
            if !sea[k] && lake_of[k] == NONE {
                elev[k] = lvl;
            }
        }
    }
    // Valleys: walls rise from the nearest river along a widening cone.
    {
        let is_src = |k: usize| !rlevel[k].is_nan() && !sea[k] && lake_of[k] == NONE;
        let mut vd: Vec<f32> = (0..nn).map(|k| if is_src(k) { 0.0 } else { f32::INFINITY }).collect();
        let mut vs: Vec<u32> = (0..nn).map(|k| if is_src(k) { k as u32 } else { NONE }).collect();
        chamfer(n, n, cell, &mut vd, Some(&mut vs));
        // The nearest river's level, smoothed, so valley walls do not step where a steep river does.
        let mut lv = Grid::new(n, cell, vs.iter().map(|&q| if q == NONE { 0.0 } else { rlevel[q as usize] }).collect());
        lv.blur(3, 2);
        for k in 0..nn {
            if vs[k] == NONE || sea[k] || lake_of[k] != NONE || !rlevel[k].is_nan() {
                continue;
            }
            let q = vs[k] as usize;
            let d = (pos(k).0 - pos(q).0).d_hypot(pos(k).1 - pos(q).1);
            if d < 700.0 {
                elev[k] = elev[k].min(lv.v[k].max(rlevel[q]) + p.water.valley_slope * d + p.water.valley_curve * d * d);
            }
        }
        // Keep lake rims above their lakes.
        for k in 0..nn {
            if lake_of[k] != NONE || sea[k] {
                continue;
            }
            for (dx, dy, _) in D8 {
                if let Some(nb) = step(n, k, dx, dy) {
                    if lake_of[nb] != NONE {
                        elev[k] = elev[k].max(lakes[lake_of[nb] as usize].level_m + 0.3);
                    }
                }
            }
        }
    }
    let max_e = elev.iter().cloned().fold(f32::MIN, f32::max);
    for g in ranges.iter_mut() {
        let mut best = (0.0, 0.0, f32::MIN);
        for k in 0..nn {
            let (x, y) = pos(k);
            if elev[k] > best.2 && g.locate(x, y).0 < g.half_width_m * 1.2 {
                best = (x, y, elev[k]);
            }
        }
        g.summit = best;
    }

    Hydro { seed, size_m, rng, scale, city, elev, sea, lake_of, lakes, rlevel, acc, river_nodes, ranges, land_km2, max_e }
}

/// What the macro pass's second half needs from its first.
struct Hydro {
    seed: u64,
    size_m: u32,
    rng: Rng,
    scale: f32,
    city: Option<((f32, f32), f32, f32)>,
    elev: Vec<f32>,
    sea: Vec<bool>,
    lake_of: Vec<u32>,
    lakes: Vec<Lake>,
    rlevel: Vec<f32>,
    acc: Vec<f32>,
    river_nodes: Vec<Vec<usize>>,
    ranges: Vec<Range>,
    land_km2: f32,
    max_e: f32,
}

/// The second half of the macro pass: water distances, moisture, regions and sites on the
/// `cell_m` grid, and the river beds rasterised into a tile mask.
fn macro_pass(h: Hydro, p: &LandParams) -> Work {
    let Hydro { seed, size_m, mut rng, scale, city, elev, sea, lake_of, lakes, rlevel, acc, river_nodes, ranges, land_km2, max_e } = h;
    let s = size_m as f32;
    let cell = p.cell_m;
    let n = (s / cell).ceil() as usize + 1;
    let nn = n * n;
    let pos = |k: usize| ((k % n) as f32 * cell, (k / n) as f32 * cell);
    let elev_at = |elev: &[f32], x: f32, y: f32| {
        let i = ((x / cell).round() as isize).clamp(0, n as isize - 1) as usize;
        let j = ((y / cell).round() as isize).clamp(0, n as isize - 1) as usize;
        elev[j * n + i]
    };
    let slope_of = |elev: &[f32], k: usize| {
        let (i, j) = ((k % n) as isize, (k / n) as isize);
        let g = |a: isize, b: isize| elev[(b.clamp(0, n as isize - 1) as usize) * n + a.clamp(0, n as isize - 1) as usize];
        ((g(i + 1, j) - g(i - 1, j)) / (2.0 * cell)).d_hypot((g(i, j + 1) - g(i, j - 1)) / (2.0 * cell))
    };
    // Water sources: level and depth of the nearest water body.
    let mut level = vec![0f32; nn];
    let mut depth = vec![1f32; nn];
    let mut water = vec![false; nn];
    for k in 0..nn {
        if sea[k] {
            (water[k], level[k], depth[k]) = (true, 0.0, 12.0);
        } else if lake_of[k] != NONE {
            (water[k], level[k], depth[k]) = (true, lakes[lake_of[k] as usize].level_m, p.water.lake_depth_m * 0.6);
        } else if !rlevel[k].is_nan() {
            let w = (p.water.river_width_k * acc[k].sqrt()).clamp(p.water.river_width_m[0], p.water.river_width_m[1]);
            (water[k], level[k], depth[k]) = (true, rlevel[k], 0.4 + 0.12 * w);
        }
    }
    let mut wd: Vec<f32> = water.iter().map(|w| if *w { 0.0 } else { f32::INFINITY }).collect();
    chamfer(n, n, cell, &mut wd, None);
    let mut sea_d: Vec<f32> = sea.iter().map(|w| if *w { 0.0 } else { f32::INFINITY }).collect();
    chamfer(n, n, cell, &mut sea_d, None);
    // Dry beds still draw settlements and moisture (`wd` above) but hold no water surface.
    if p.water.dry_rivers {
        for k in 0..nn {
            if !sea[k] && lake_of[k] == NONE && !rlevel[k].is_nan() {
                water[k] = false;
            }
        }
    }

    // Moisture: noise, nearby water, and a rain shadow behind high ground upwind.
    let wind = rng.f() * std::f32::consts::TAU;
    let moist: Vec<f32> = (0..nn)
        .map(|k| {
            let (x, y) = pos(k);
            let mut up = 0f32;
            for i in 1..=8 {
                let d = i as f32 * 80.0;
                up = up.max(elev_at(&elev, x - wind.d_cos() * d, y - wind.d_sin() * d));
            }
            let shadow = smoothstep(0.0, 220.0, up - elev[k]);
            0.5 + 0.35 * fbm(seed ^ 0x16, x, y, 520.0, 3) + 0.35 * (-wd[k] / 170.0).d_exp() - 0.35 * shadow
        })
        .collect();

    // Regions: warped Voronoi cells, classified by their mean height, slope and moisture.
    let rp = &p.regions;
    // Smaller worlds get smaller regions, so a 1 km island still holds every kind.
    let (rcell, rwarp) = (rp.cell_m * scale, rp.warp_m * scale);
    let rg = (s / rcell).ceil() as usize;
    let seeds: Vec<(f32, f32)> = (0..rg * rg)
        .map(|g| {
            let (gx, gy) = ((g % rg) as f32, (g / rg) as f32);
            ((gx + 0.15 + 0.7 * hash(seed ^ 0x21, gx as i32, gy as i32)) * rcell, (gy + 0.15 + 0.7 * hash(seed ^ 0x22, gx as i32, gy as i32)) * rcell)
        })
        .collect();
    let region_of: Vec<u16> = (0..nn)
        .map(|k| {
            let (x, y) = pos(k);
            // Several octaves, so borders wander at every scale instead of running straight.
            let wx = x + rwarp * fbm(seed ^ 0x23, x, y, 260.0 * scale, 4);
            let wy = y + rwarp * fbm(seed ^ 0x24, x, y, 260.0 * scale, 4);
            let (cx, cy) = ((wx / rcell).floor() as isize, (wy / rcell).floor() as isize);
            let mut best = (f32::MAX, 0usize);
            for gy in cy - 1..=cy + 1 {
                for gx in cx - 1..=cx + 1 {
                    if gx < 0 || gy < 0 || gx >= rg as isize || gy >= rg as isize {
                        continue;
                    }
                    let g = gy as usize * rg + gx as usize;
                    let d = (seeds[g].0 - wx).d_hypot(seeds[g].1 - wy);
                    if d < best.0 {
                        best = (d, g);
                    }
                }
            }
            best.1 as u16
        })
        .collect();
    #[derive(Default, Clone)]
    struct Stat {
        nodes: f32,
        land: f32,
        coastal: f32,
        wet: f32,
        e: f32,
        m: f32,
        sl: f32,
        sea_d: f32,
    }
    let mut stats = vec![Stat::default(); rg * rg];
    for k in 0..nn {
        let st = &mut stats[region_of[k] as usize];
        st.nodes += 1.0;
        if sea[k] {
            continue;
        }
        st.land += 1.0;
        st.e += elev[k];
        st.m += moist[k];
        st.sl += slope_of(&elev, k);
        st.sea_d += sea_d[k].min(2000.0);
        if sea_d[k] < 70.0 && elev[k] < 12.0 {
            st.coastal += 1.0;
        }
        if wd[k] < 60.0 {
            st.wet += 1.0;
        }
    }
    let mean = |st: &Stat, v: f32| v / st.land.max(1.0);
    let mut kinds = vec![RegionKind::Sea; rg * rg];
    let mut lowland: Vec<usize> = Vec::new();
    for (g, st) in stats.iter().enumerate() {
        if st.land < st.nodes * 0.5 || st.land == 0.0 {
            continue;
        }
        let (e, sl) = (mean(st, st.e), mean(st, st.sl));
        // Peaks are high ground relative to the highest point, and highland in their own right:
        // on a low land (a levelled city's plain) the highest regions are not peaks.
        kinds[g] = if e >= rp.peaks_fraction * max_e && e >= rp.highland_m {
            RegionKind::Peaks
        } else if e >= rp.highland_m || sl > 0.4 {
            RegionKind::Highland
        } else if st.coastal / st.land > 0.3 {
            RegionKind::Beach
        } else {
            lowland.push(g);
            RegionKind::Meadow
        };
    }
    // At least one beach: the lowland region with the most coast, when none passes the share.
    if !kinds.contains(&RegionKind::Beach) {
        let coastal = |g: usize| stats[g].coastal / stats[g].land;
        if let Some(i) = (0..lowland.len()).filter(|&i| coastal(lowland[i]) > 0.05).max_by(|&a, &b| coastal(lowland[a]).total_cmp(&coastal(lowland[b]))) {
            kinds[lowland.swap_remove(i)] = RegionKind::Beach;
        }
    }
    // A land that asks for no wetlands gets none; otherwise at least one.
    let want_wet = if rp.wetlands_per_km2 <= 0.0 { 0 } else { ((land_km2 * rp.wetlands_per_km2).round() as usize).clamp(1, 3) };
    let mut wet_c: Vec<usize> = lowland.iter().cloned().filter(|&g| mean(&stats[g], stats[g].sl) < 0.06 && stats[g].wet / stats[g].land > 0.2).collect();
    wet_c.sort_by(|a, b| mean(&stats[*b], stats[*b].m).total_cmp(&mean(&stats[*a], stats[*a].m)));
    if wet_c.is_empty() {
        wet_c = lowland.clone();
        wet_c.sort_by(|a, b| (stats[*b].wet / stats[*b].land).total_cmp(&(stats[*a].wet / stats[*a].land)));
    }
    for &g in wet_c.iter().take(want_wet.min(lowland.len().saturating_sub(3))) {
        kinds[g] = RegionKind::Wetland;
    }
    let mut rest: Vec<usize> = lowland.iter().cloned().filter(|&g| kinds[g] == RegionKind::Meadow).collect();
    rest.sort_by(|a, b| mean(&stats[*b], stats[*b].m).total_cmp(&mean(&stats[*a], stats[*a].m)));
    let (n_old, n_forest) = ((rest.len() as f32 * rp.old_forest_share).round().max(1.0) as usize, (rest.len() as f32 * rp.forest_share).round().max(1.0) as usize);
    for (i, &g) in rest.iter().enumerate() {
        kinds[g] = if i < n_old { RegionKind::OldForest } else if i < n_old + n_forest { RegionKind::Forest } else { RegionKind::Meadow };
    }
    // One spirit grove: the most remote old forest (else forest, else meadow).
    for want in [RegionKind::OldForest, RegionKind::Forest, RegionKind::Meadow, RegionKind::Highland] {
        if (0..rg * rg).filter(|&g| kinds[g] == want).count() < 2 && want != RegionKind::Highland {
            continue;
        }
        let pick = (0..rg * rg).filter(|&g| kinds[g] == want).max_by(|a, b| mean(&stats[*a], stats[*a].sea_d).total_cmp(&mean(&stats[*b], stats[*b].sea_d)));
        if let Some(g) = pick {
            kinds[g] = RegionKind::SpiritGrove;
            break;
        }
    }
    let regions: Vec<Region> = (0..rg * rg)
        .map(|g| {
            let st = &stats[g];
            Region { id: g as u16, kind: kinds[g], centre: seeds[g], area_m2: st.nodes * cell * cell, land_m2: st.land * cell * cell, mean_height_m: mean(st, st.e) }
        })
        .collect();
    let mut node_kind: Vec<RegionKind> = (0..nn)
        .map(|k| match kinds[region_of[k] as usize] {
            RegionKind::Sea if !sea[k] => RegionKind::Beach,
            kind => kind,
        })
        .collect();
    // Authored region stamps, in order: the land inside each is of its kind.
    for st in p.relief.stamps.iter().filter(|st| st.region.is_some()) {
        let q = st.poly();
        let lo = q.iter().fold((f32::MAX, f32::MAX), |m, v| (m.0.min(v.0), m.1.min(v.1)));
        let hi = q.iter().fold((f32::MIN, f32::MIN), |m, v| (m.0.max(v.0), m.1.max(v.1)));
        for k in 0..nn {
            let c = pos(k);
            if c.0 >= lo.0 && c.1 >= lo.1 && c.0 <= hi.0 && c.1 <= hi.1 && !sea[k] && settle::poly_contains(&q, c) {
                node_kind[k] = st.region.unwrap();
            }
        }
    }

    // Wetland pools are water sources at their own ground level.
    for k in 0..nn {
        if node_kind[k] == RegionKind::Wetland && !water[k] {
            (water[k], level[k], depth[k]) = (true, elev[k] - 0.35, 0.7);
        }
    }
    let mut nd: Vec<f32> = water.iter().map(|w| if *w { 0.0 } else { f32::INFINITY }).collect();
    let mut src: Vec<u32> = (0..nn as u32).map(|k| if water[k as usize] { k } else { NONE }).collect();
    chamfer(n, n, cell, &mut nd, Some(&mut src));
    let surf = Grid::new(n, cell, src.iter().map(|&q| if q == NONE { 0.0 } else { level[q as usize] }).collect());
    let maxd = Grid::new(n, cell, src.iter().map(|&q| if q == NONE { 1.0 } else { depth[q as usize] }).collect());
    let still = Grid::new(n, cell, (0..nn).map(|k| (sea[k] || lake_of[k] != NONE) as u8 as f32).collect());
    let wet = {
        let mut g = Grid::new(n, cell, node_kind.iter().map(|k| (*k == RegionKind::Wetland) as u8 as f32).collect());
        g.blur(2, 2);
        g
    };
    let look_grid = |f: &dyn Fn(&KindLook) -> f32| {
        let looks: Vec<f32> = RegionKind::ALL.iter().map(|k| f(&rp.look(*k))).collect();
        let mut g = Grid::new(n, cell, node_kind.iter().map(|k| looks[*k as usize]).collect());
        g.blur(3, 2);
        g
    };
    let detail = look_grid(&|l| l.detail_m);
    let trees = look_grid(&|l| l.trees);
    let beach = look_grid(&|l| l.beach_m);
    let outcrops = look_grid(&|l| l.outcrops);
    let dirt = look_grid(&|l| l.dirt);

    // Sites.
    let mut still_d: Vec<f32> = (0..nn).map(|k| if sea[k] || lake_of[k] != NONE { 0.0 } else { f32::INFINITY }).collect();
    chamfer(n, n, cell, &mut still_d, None);
    let avoid = city.map(|(cc, cr, _)| (cc, cr));
    // Planned settlements' fixed sites come first; generated sites keep their distance.
    let fixed: Vec<Site> = p
        .plans
        .iter()
        .map(|sp| {
            let r = settle::resolve_plan(sp).unwrap_or_else(|e| panic!("{e}"));
            let k = {
                let i = ((r.centre.0 / cell).round() as isize).clamp(0, n as isize - 1) as usize;
                let j = ((r.centre.1 / cell).round() as isize).clamp(0, n as isize - 1) as usize;
                j * n + i
            };
            settle::plan_site(&r, node_kind[k])
        })
        .collect();
    let sites = place_sites(&SiteCtx { p, n, cell, s, elev: &elev, wd: &wd, still_d: &still_d, sea_d: &sea_d, node_kind: &node_kind, max_e, land_km2, seed, avoid }, &|k| slope_of(&elev, k), fixed);

    let mut land = Land {
        ways: None,
        seed,
        size: size_m,
        map: Map::from_chunks(0, 0, std::iter::empty()),
        regions,
        sites,
        rivers: Vec::new(),
        dry_beds: Vec::new(),
        lakes,
        ranges,
        opened_tiles: 0,
        closed_pockets: 0,
        settlements: Vec::new(),
        lots: Vec::new(),
        roads: Vec::new(),
        crossings: Vec::new(),
        props: Vec::new(),
        plans: Vec::new(),
        mods: settle::Mods::default(),
        n,
        cell,
        elev: Grid::new(n, cell, elev),
        detail,
        surf,
        maxd,
        region_of,
        node_kind,
        sd: Vec::new(),
    };

    // ---- Tiles.
    let w = size_m as usize;
    let tn = w * w;

    // Rivers: smoothed centre lines rasterised with banks; fords at intervals.
    let mut rmask = vec![0u8; tn];
    let mut fords: Vec<((f32, f32), (f32, f32), f32)> = Vec::new();
    for (ri, nodes) in river_nodes.iter().enumerate() {
        let mut pts: Vec<[f32; 3]> = nodes
            .iter()
            .map(|&k| {
                let wv = (p.water.river_width_k * acc[k].sqrt()).clamp(p.water.river_width_m[0], p.water.river_width_m[1]);
                [pos(k).0, pos(k).1, wv]
            })
            .collect();
        // Meander a little where the ground is gentle.
        let mut along = 0.0;
        for i in 1..pts.len().saturating_sub(1) {
            along += (pts[i][0] - pts[i - 1][0]).d_hypot(pts[i][1] - pts[i - 1][1]);
            let (tx, ty) = (pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]);
            let l = tx.d_hypot(ty).max(1e-3);
            let gentle = 1.0 - smoothstep(0.05, 0.25, slope_of(&land.elev.v, nodes[i]));
            let off = value(seed ^ 0x31, along / 110.0, ri as f32 * 7.3) * cell * 1.6 * gentle;
            pts[i][0] += -ty / l * off;
            pts[i][1] += tx / l * off;
        }
        for _ in 0..3 {
            pts = chaikin(&pts);
        }
        let mut length = 0.0;
        let mut next_ford = p.water.ford_spacing_m * 0.5;
        let mut river_fords = Vec::new();
        for i in 0..pts.len().saturating_sub(1) {
            let (a, b) = (pts[i], pts[i + 1]);
            let seg = (b[0] - a[0]).d_hypot(b[1] - a[1]);
            raster_segment(&mut rmask, w, a, b);
            length += seg;
            if length >= next_ford && seg > 0.0 {
                next_ford += p.water.ford_spacing_m;
                let node = land.node_at(a[0], a[1]);
                if !p.water.dry_rivers && still.bilinear(a[0], a[1]) < 0.01 && lake_of[node] == NONE {
                    fords.push(((a[0], a[1]), ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg), a[2] * 0.5));
                    river_fords.push((a[0], a[1]));
                }
            }
        }
        let source_m = nodes.first().map(|&k| rlevel[k]).unwrap_or(0.0);
        let beds = if p.water.dry_rivers { &mut land.dry_beds } else { &mut land.rivers };
        beds.push(River { points: pts.iter().map(|q| (q[0], q[1])).collect(), width_m: pts.iter().map(|q| q[2]).collect(), length_m: length, source_m, fords: river_fords });
    }

    let sites_work = p.sites.iter().any(|sp| sp.dispersed).then(|| Box::new(SiteWork { wd, still_d, sea_d, max_e, land_km2, avoid, spec: 0, state: SpecState::default(), steps: 0 }));
    Work { land, rmask, fords, still, wet, beach, outcrops, trees, dirt, tiles: vec![Terrain::Grass as u8; tn], sd: Vec::new(), sites: sites_work }
}

/// Classify the tiles of rows `j0..j1`. Each tile's slope reads its neighbours' ground, so the
/// band's ground is computed with a row of margin on each side.
fn tile_rows(wk: &mut Work, p: &LandParams, j0: usize, j1: usize) {
    let Work { land, rmask, still, wet, beach, outcrops, trees, dirt, tiles, .. } = wk;
    let (seed, w) = (land.seed, land.size as usize);
    let rp = &p.regions;
    let lo = j0.saturating_sub(1);
    let hi = j1.min(w - 1);
    let t: Vec<f32> = (lo * w..(hi + 1) * w).map(|k| land.terrain((k % w) as f32 + 0.5, (k / w) as f32 + 0.5)).collect();
    let rock_slope = 0.85;
    let treeline = rp.treeline_m;
    // Authored ground stamps, with their boxes, for the rows of this band.
    let grounds: Vec<(Vec<(f32, f32)>, (f32, f32), (f32, f32), Terrain)> = p
        .relief
        .stamps
        .iter()
        .filter_map(|st| {
            let g = stamp_ground(st.ground.as_deref()?)?;
            let q = st.poly();
            let lo = q.iter().fold((f32::MAX, f32::MAX), |m, v| (m.0.min(v.0), m.1.min(v.1)));
            let hi = q.iter().fold((f32::MIN, f32::MIN), |m, v| (m.0.max(v.0), m.1.max(v.1)));
            (hi.1 >= j0 as f32 && lo.1 <= j1 as f32).then_some((q, lo, hi, g))
        })
        .collect();
    for j in j0..j1 {
        for i in 0..w {
            let k = j * w + i;
            let (x, y) = (i as f32 + 0.5, j as f32 + 0.5);
            let h = t[k - lo * w];
            let st = still.bilinear(x, y);
            let sf = land.surf.bilinear(x, y);
            let c = if rmask[k] == 2 && p.water.dry_rivers {
                // A dry bed: sand and gravel where the water would run.
                Terrain::Sand
            } else if st > 0.02 && h < sf || rmask[k] == 2 {
                Terrain::Water
            } else {
                let tl = |a: usize, b: usize| t[(b.min(w - 1) - lo) * w + a.min(w - 1)];
                let sx = (tl(i + 1, j) - tl(i.saturating_sub(1), j)) / 2.0;
                let sy = (tl(i, j + 1) - tl(i, j.saturating_sub(1))) / 2.0;
                let slope = sx.d_hypot(sy);
                let wt = wet.bilinear(x, y);
                if wt > 0.4 && fbm(seed ^ 0x41, x, y, 13.0, 2) > 0.72 - 0.4 * wt {
                    Terrain::Water
                } else if slope > rock_slope {
                    Terrain::Rock
                } else if rmask[k] == 1 && h < 150.0 && slope < 0.45 {
                    Terrain::Sand
                } else if st > 0.02 && sf < 0.5 && h < beach.bilinear(x, y) * 0.06 && slope < 0.3 {
                    Terrain::Sand
                } else if st > 0.02 && sf >= 0.5 && h < sf + 0.3 && slope < 0.3 {
                    Terrain::Sand
                } else if 0.5 + 0.8 * fbm(seed ^ 0x42, x, y, 16.0, 3) > 1.0 - outcrops.bilinear(x, y) {
                    Terrain::Rock
                } else if 0.5 + 0.8 * fbm(seed ^ 0x43, x, y, 26.0, 3) < trees.bilinear(x, y) * (1.0 - smoothstep(treeline - 60.0, treeline, h)) * (1.0 - smoothstep(0.5, 0.8, slope)) {
                    Terrain::Forest
                } else if 0.5 + 0.9 * (0.75 * fbm(seed ^ 0x45, x, y, 110.0, 3) + 0.35 * fbm(seed ^ 0x44, x, y, 14.0, 2)) < dirt.bilinear(x, y) {
                    // Coarse noise dominates, so bare ground gathers in ragged patches instead of
                    // speckling evenly.
                    Terrain::Dirt
                } else {
                    Terrain::Grass
                }
            };
            let c = if c == Terrain::Water { c } else { grounds.iter().rev().find(|(q, lo, hi, _)| x >= lo.0 && y >= lo.1 && x <= hi.0 && y <= hi.1 && settle::poly_contains(q, (x, y))).map_or(c, |g| g.3) };
            tiles[k] = c as u8;
        }
    }
}

/// Fords, cleared settlement sites and cave mouths, then the connectivity pass: every walkable
/// pocket is linked to the main one or closed.
fn connect_pass(wk: &mut Work, p: &LandParams) {
    let Work { land, rmask, fords, tiles, .. } = wk;
    let w = land.size as usize;
    // Fords: a 3 m sand bar across the river.
    for ((px, py), (dx, dy), half) in fords.iter() {
        let r = half + 3.0;
        for j in (py - r).floor() as i32..=(py + r).ceil() as i32 {
            for i in (px - r).floor() as i32..=(px + r).ceil() as i32 {
                if i < 0 || j < 0 || i >= w as i32 || j >= w as i32 {
                    continue;
                }
                let (qx, qy) = (i as f32 + 0.5 - px, j as f32 + 0.5 - py);
                let along = qx * dx + qy * dy;
                let across = -qx * dy + qy * dx;
                let k = j as usize * w + i as usize;
                if along.abs() <= 1.5 && across.abs() <= half + 2.0 && rmask[k] == 2 && tiles[k] == Terrain::Water as u8 {
                    tiles[k] = Terrain::Sand as u8;
                }
            }
        }
    }

    // Settlements clear their ground; cave mouths sit at the foot of rock.
    let mut sites = std::mem::take(&mut land.sites);
    for site in sites.iter_mut() {
        let r = site.radius_m;
        if site.kind == SiteKind::Cave {
            let (gx, gy) = grad(&land.elev, site.x, site.y);
            let gl = gx.d_hypot(gy).max(1e-4);
            let (ux, uy) = (gx / gl, gy / gl);
            let mut best: Option<(f32, f32, f32)> = None;
            for j in (site.y - 40.0) as i32..=(site.y + 40.0) as i32 {
                for i in (site.x - 40.0) as i32..=(site.x + 40.0) as i32 {
                    if i < 2 || j < 2 || i >= w as i32 - 2 || j >= w as i32 - 2 || !Terrain::from_u8(tiles[j as usize * w + i as usize]).walkable() {
                        continue;
                    }
                    let rock_up = (1..=6).filter(|d| {
                        let (xx, yy) = (i as f32 + 0.5 + ux * *d as f32, j as f32 + 0.5 + uy * *d as f32);
                        xx >= 0.0 && yy >= 0.0 && (xx as usize) < w && (yy as usize) < w && tiles[yy as usize * w + xx as usize] == Terrain::Rock as u8
                    });
                    let score = rock_up.count() as f32 - (i as f32 - site.x).d_hypot(j as f32 - site.y) * 0.03;
                    if best.is_none_or(|b| score > b.2) {
                        best = Some((i as f32 + 0.5, j as f32 + 0.5, score));
                    }
                }
            }
            if let Some((bx, by, _)) = best {
                (site.x, site.y) = (bx, by);
            }
            site.facing = (-uy).d_atan2(-ux);
        }
        // A planned settlement opens its own levels (`settle::plan::paint`); a disc of its
        // radius would also clear whatever lies between it and its outlying lots.
        let clear = if site.kind == SiteKind::Cave { 3.0 } else if site.plan.is_some() { 0.0 } else { r * 0.95 };
        for j in (site.y - clear) as i32..=(site.y + clear) as i32 {
            for i in (site.x - clear) as i32..=(site.x + clear) as i32 {
                if i < 0 || j < 0 || i >= w as i32 || j >= w as i32 || (i as f32 + 0.5 - site.x).d_hypot(j as f32 + 0.5 - site.y) > clear {
                    continue;
                }
                let k = j as usize * w + i as usize;
                tiles[k] = match Terrain::from_u8(tiles[k]) {
                    Terrain::Forest => Terrain::Grass as u8,
                    Terrain::Rock => Terrain::Dirt as u8,
                    other => other as u8,
                };
            }
        }
    }

    // Pockets holding a site are linked, never closed.
    let keep: Vec<usize> = sites.iter().map(|s| (s.y.max(0.0) as usize).min(w - 1) * w + (s.x.max(0.0) as usize).min(w - 1)).collect();
    land.sites = sites;

    let (opened, closed_pockets) = connect(tiles, w, p.min_pocket_tiles, &keep, false);
    land.opened_tiles = opened;
    land.closed_pockets = closed_pockets;
    *rmask = Vec::new();
}

/// Signed distance to the water's edge: on land (`pass` 0), then in the water (1).
fn shore_pass(wk: &mut Work, pass: usize) {
    let Work { land, tiles, sd, .. } = wk;
    let w = land.size as usize;
    let tn = w * w;
    if sd.is_empty() {
        *sd = vec![0i8; tn];
    }
    let mut d = vec![0f32; tn];
    {
        let inside = pass == 1;
        for k in 0..tn {
            let is_water = tiles[k] == Terrain::Water as u8;
            d[k] = if is_water != inside { 0.0 } else { f32::INFINITY };
        }
        chamfer(w, w, 1.0, &mut d, None);
        for k in 0..tn {
            let is_water = tiles[k] == Terrain::Water as u8;
            if is_water == inside {
                let v = (d[k] - 0.5).min(15.8);
                let v = if pass == 1 { -v } else { v };
                sd[k] = (v * 8.0).round().clamp(-127.0, 127.0) as i8;
            }
        }
    }
}

/// The finished tile map and shore distances in the land.
fn finish_tiles(wk: Work) -> Land {
    let Work { mut land, tiles, sd, .. } = wk;
    let size_m = land.size;
    land.sd = sd;
    land.map = Map { w: size_m, h: size_m, tiles, blocked: Default::default(), opaque: Default::default(), nav: Default::default() };
    land
}

fn step(n: usize, k: usize, dx: isize, dy: isize) -> Option<usize> {
    let (x, y) = ((k % n) as isize + dx, (k / n) as isize + dy);
    (x >= 0 && y >= 0 && x < n as isize && y < n as isize).then(|| y as usize * n + x as usize)
}

/// Apply `f(old, d / radius)` to nodes within `radius` of a point.
fn stamp(elev: &mut [f32], n: usize, cell: f32, c: (f32, f32), radius: f32, f: impl Fn(f32, f32, f32, f32) -> f32) {
    let r = (radius / cell).ceil() as isize + 1;
    let (ci, cj) = ((c.0 / cell).round() as isize, (c.1 / cell).round() as isize);
    for j in cj - r..=cj + r {
        for i in ci - r..=ci + r {
            if i < 0 || j < 0 || i >= n as isize || j >= n as isize {
                continue;
            }
            let (x, y) = (i as f32 * cell, j as f32 * cell);
            let q = (x - c.0).d_hypot(y - c.1) / radius;
            if q < 1.0 {
                let k = j as usize * n + i as usize;
                elev[k] = f(elev[k], q, x, y);
            }
        }
    }
}

fn grad(g: &Grid, x: f32, y: f32) -> (f32, f32) {
    let e = g.cell;
    ((g.bilinear(x + e, y) - g.bilinear(x - e, y)) / (2.0 * e), (g.bilinear(x, y + e) - g.bilinear(x, y - e)) / (2.0 * e))
}

fn chaikin(p: &[[f32; 3]]) -> Vec<[f32; 3]> {
    if p.len() < 3 {
        return p.to_vec();
    }
    let mut out = vec![p[0]];
    for w in p.windows(2) {
        let (a, b) = (w[0], w[1]);
        out.push([0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1], 0.75 * a[2] + 0.25 * b[2]]);
        out.push([0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1], 0.25 * a[2] + 0.75 * b[2]]);
    }
    out.push(p[p.len() - 1]);
    out
}

/// Mark water (2) within half the width of a segment and bank (1) just beyond.
fn raster_segment(mask: &mut [u8], w: usize, a: [f32; 3], b: [f32; 3]) {
    const BANK: f32 = 1.6;
    let r = a[2].max(b[2]) * 0.5 + BANK + 1.0;
    let (x0, x1) = ((a[0].min(b[0]) - r).floor().max(0.0) as usize, ((a[0].max(b[0]) + r).ceil() as usize).min(w - 1));
    let (y0, y1) = ((a[1].min(b[1]) - r).floor().max(0.0) as usize, ((a[1].max(b[1]) + r).ceil() as usize).min(w - 1));
    let (dx, dy) = (b[0] - a[0], b[1] - a[1]);
    let l2 = (dx * dx + dy * dy).max(1e-6);
    for j in y0..=y1 {
        for i in x0..=x1 {
            let (qx, qy) = (i as f32 + 0.5, j as f32 + 0.5);
            let u = (((qx - a[0]) * dx + (qy - a[1]) * dy) / l2).clamp(0.0, 1.0);
            let d = (qx - a[0] - u * dx).d_hypot(qy - a[1] - u * dy);
            let half = lerp(a[2], b[2], u) * 0.5;
            let k = j * w + i;
            if d < half {
                mask[k] = 2;
            } else if d < half + BANK && mask[k] == 0 {
                mask[k] = 1;
            }
        }
    }
}

fn plan_ranges(rng: &mut Rng, seed: u64, s: f32, centre: (f32, f32), scale: f32, r: &Relief) -> Vec<Range> {
    let two = s >= r.two_ranges_m || (s >= r.maybe_two_ranges_m && rng.f() < 0.5);
    let theta = rng.f() * std::f32::consts::TAU;
    let side = if rng.f() < 0.5 { 1.0 } else { -1.0 };
    let len = (s * r.range_length).min(r.range_max_length_m);
    let make = |rng: &mut Rng, c: (f32, f32), theta: f32, len: f32, crest: f32, width: f32, k: u64| {
        let (dir, nrm) = ((theta.d_cos(), theta.d_sin()), (-theta.d_sin(), theta.d_cos()));
        let bend = (rng.f() - 0.5) * 0.5 * len;
        let p0 = (c.0 - dir.0 * len * 0.5, c.1 - dir.1 * len * 0.5);
        let p2 = (c.0 + dir.0 * len * 0.5, c.1 + dir.1 * len * 0.5);
        let p1 = (c.0 + nrm.0 * bend, c.1 + nrm.1 * bend);
        let spine = (0..=40)
            .map(|i| {
                let u = i as f32 / 40.0;
                let (a, b, cc) = ((1.0 - u) * (1.0 - u), 2.0 * (1.0 - u) * u, u * u);
                (a * p0.0 + b * p1.0 + cc * p2.0, a * p0.1 + b * p1.1 + cc * p2.1)
            })
            .collect();
        Range { spine, half_width_m: width, summit: (0.0, 0.0, 0.0), crest_m: crest, main_t: 0.3 + 0.4 * rng.f(), length_m: len, seed: seed ^ k }
    };
    let off = s * r.range_offset * side;
    let nrm = (-theta.d_sin(), theta.d_cos());
    let c1 = (centre.0 + nrm.0 * off, centre.1 + nrm.1 * off);
    let crest = rng.range(r.peak_m) * scale;
    let mut out = vec![make(rng, c1, theta, len, crest, r.range_half_width_m * scale, 0x61)];
    if two {
        let c2 = (centre.0 - nrm.0 * off * 1.4 + (rng.f() - 0.5) * len * 0.3 * theta.d_cos(), centre.1 - nrm.1 * off * 1.4 + (rng.f() - 0.5) * len * 0.3 * theta.d_sin());
        let theta2 = theta + (rng.f() - 0.5) * 0.9;
        out.push(make(rng, c2, theta2, len * 0.55, crest * 0.62, r.range_half_width_m * scale * 0.8, 0x62));
    }
    out
}

struct SiteCtx<'a> {
    p: &'a LandParams,
    n: usize,
    cell: f32,
    s: f32,
    elev: &'a [f32],
    wd: &'a [f32],
    /// Distance to the sea or a lake.
    still_d: &'a [f32],
    sea_d: &'a [f32],
    node_kind: &'a [RegionKind],
    max_e: f32,
    land_km2: f32,
    seed: u64,
    /// The city (centre, radius): sites stand outside it.
    avoid: Option<((f32, f32), f32)>,
}

struct Survey {
    lo: f32,
    hi: f32,
    mean: f32,
    water: f32,
    still: f32,
    wetland: f32,
    grove: f32,
    sea: f32,
}

/// A site candidate: score, position, mean ground, region kind.
type Cand = (f32, f32, f32, f32, RegionKind);

/// How far one site spec's placement has got: its relaxation level and that level's candidates.
#[derive(Default)]
pub(crate) struct SpecState {
    relax: usize,
    cands: Option<Box<Level>>,
}

/// One relaxation level's candidates and what the placed sites leave of each: whether one is
/// too near (`blocked`, for good: sites are only added) and the distance to the nearest (up to
/// 1,200 m). Kept up to date site by site, through buckets of candidates, so a pick is one pass
/// over the candidates and a placement touches only those near it.
pub(crate) struct Level {
    cands: Vec<Cand>,
    blocked: Vec<bool>,
    nearest: Vec<f32>,
    buckets: Vec<Vec<u32>>,
    cols: i32,
    /// Placed sites already taken into account.
    seen: usize,
}

/// Side of a candidate bucket (metres).
const BUCKET_M: f32 = 128.0;

impl Level {
    fn new(cands: Vec<Cand>, side: f32) -> Self {
        let cols = (side / BUCKET_M).ceil().max(1.0) as i32;
        let mut buckets = vec![Vec::new(); (cols * cols) as usize];
        for (ci, c) in cands.iter().enumerate() {
            let (bx, by) = (((c.1 / BUCKET_M) as i32).clamp(0, cols - 1), ((c.2 / BUCKET_M) as i32).clamp(0, cols - 1));
            buckets[(by * cols + bx) as usize].push(ci as u32);
        }
        let n = cands.len();
        Self { cands, blocked: vec![false; n], nearest: vec![1200.0; n], buckets, cols, seen: 0 }
    }

    /// Take a placed site into account for every candidate within its reach.
    fn apply(&mut self, q: &Site, sp: &SiteSpec, relax: f32) {
        let r = sp.radius_m;
        let mine = q.kind == sp.kind && q.style == sp.style;
        let need = if mine { (sp.spacing_m / relax.sqrt()).max(r + q.radius_m + 60.0) } else if q.kind == sp.kind && q.kind != SiteKind::Cave { (sp.spacing_m.max(q.radius_m * 3.0) / relax.sqrt()).max(r + q.radius_m + 120.0) } else { r + q.radius_m + 120.0 };
        let counts = q.kind != SiteKind::Cave && sp.kind != SiteKind::Cave;
        let reach = if counts { need.max(1200.0) } else { need };
        let (b0x, b0y) = (((q.x - reach) / BUCKET_M).floor() as i32, ((q.y - reach) / BUCKET_M).floor() as i32);
        let (b1x, b1y) = (((q.x + reach) / BUCKET_M).floor() as i32, ((q.y + reach) / BUCKET_M).floor() as i32);
        for by in b0y.max(0)..=b1y.min(self.cols - 1) {
            for bx in b0x.max(0)..=b1x.min(self.cols - 1) {
                for &ci in &self.buckets[(by * self.cols + bx) as usize] {
                    let ci = ci as usize;
                    let (_, x, y, _, _) = self.cands[ci];
                    let d = (q.x - x).d_hypot(q.y - y);
                    if d < need {
                        self.blocked[ci] = true;
                    }
                    if counts && d < self.nearest[ci] {
                        self.nearest[ci] = d;
                    }
                }
            }
        }
    }
}

/// Placement relaxes its limits in these steps when a site does not fit.
const RELAX: [f32; 4] = [1.0, 1.6, 2.5, 4.0];

fn place_sites(c: &SiteCtx, slope: &dyn Fn(usize) -> f32, fixed: Vec<Site>) -> Vec<Site> {
    let mut placed: Vec<Site> = fixed;
    // Dispersed sites (hamlets) are placed in their own steps afterwards ([`Gen`]).
    let mut order: Vec<&SiteSpec> = c.p.sites.iter().filter(|sp| !sp.dispersed).collect();
    // Towns in their own style come after the villages, so the first sites stay where they were.
    order.sort_by_key(|sp| match sp.kind {
        SiteKind::Town if sp.style.is_none() => 0,
        SiteKind::Giants => 1,
        SiteKind::SmallFolk => 2,
        SiteKind::Village => 3,
        SiteKind::Town => 4,
        SiteKind::Cave => 5,
    });
    for sp in order {
        let mut unlimited = usize::MAX;
        place_spec(c, slope, sp, &mut placed, &mut SpecState::default(), &mut unlimited);
    }
    placed
}

/// Place one spec's sites among those already `placed`, at most `budget` of them; true once the
/// spec is done (it has its count, or nowhere is left at any relaxation). Resumable: `st` keeps
/// the relaxation and its candidates, so a caller with a bounded budget per call (a step of
/// [`Gen`]) places the rest in later calls with the same result.
fn place_spec(c: &SiteCtx, slope: &dyn Fn(usize) -> f32, sp: &SiteSpec, placed: &mut Vec<Site>, st: &mut SpecState, budget: &mut usize) -> bool {
    let n = c.n;
    let node = |x: f32, y: f32| {
        let i = ((x / c.cell).round() as isize).clamp(0, n as isize - 1) as usize;
        let j = ((y / c.cell).round() as isize).clamp(0, n as isize - 1) as usize;
        j * n + i
    };
    let survey = |x: f32, y: f32, r: f32| -> Option<Survey> {
        let mut sv = Survey { lo: f32::MAX, hi: f32::MIN, mean: 0.0, water: 0.0, still: 0.0, wetland: 0.0, grove: 0.0, sea: 0.0 };
        let mut count = 0.0;
        for ring in 0..=3 {
            let rr = r * ring as f32 / 3.0;
            let dirs = if ring == 0 { 1 } else { 8 };
            for d in 0..dirs {
                let a = d as f32 * std::f32::consts::TAU / 8.0 + ring as f32 * 0.4;
                let (px, py) = (x + a.d_cos() * rr, y + a.d_sin() * rr);
                if px < 0.0 || py < 0.0 || px >= c.s || py >= c.s {
                    return None;
                }
                let k = node(px, py);
                if c.sea_d[k] < c.cell * 0.5 {
                    sv.sea += 1.0;
                    continue;
                }
                let e = c.elev[k];
                sv.lo = sv.lo.min(e);
                sv.hi = sv.hi.max(e);
                sv.mean += e;
                count += 1.0;
                if c.wd[k] < c.cell * 0.75 {
                    sv.water += 1.0;
                }
                sv.still += (c.still_d[k] < c.cell * 0.5) as u8 as f32;
                sv.grove += (c.node_kind[k] == RegionKind::SpiritGrove) as u8 as f32;
                sv.wetland += (c.node_kind[k] == RegionKind::Wetland) as u8 as f32;
            }
        }
        if count == 0.0 {
            return None;
        }
        sv.sea /= count + sv.sea;
        sv.mean /= count;
        sv.water /= count;
        sv.still /= count;
        sv.wetland /= count;
        Some(sv)
    };
    use RegionKind as K;
    let want = ((c.land_km2 * sp.per_km2).round() as u32).clamp(sp.min, sp.max) as usize;
    let r = sp.radius_m;
    let mine = |q: &Site| q.kind == sp.kind && q.style == sp.style;
    while st.relax < RELAX.len() {
        let relax = RELAX[st.relax];
        let have = placed.iter().filter(|q| mine(q)).count();
        if have >= want {
            return true;
        }
        if st.cands.is_none() {
            let mut cands: Vec<Cand> = Vec::new();
                for k in (0..n * n).step_by(2).filter(|k| (k / n) % 2 == 0) {
                    let (x, y) = ((k % n) as f32 * c.cell, (k / n) as f32 * c.cell);
                    let kind = c.node_kind[k];
                    let sr = if sp.kind == SiteKind::Cave { 12.0 } else { r };
                    if c.avoid.is_some_and(|(cc, cr)| (x - cc.0).d_hypot(y - cc.1) < cr * 1.12 + sr + 40.0) {
                        continue;
                    }
                    let Some(sv) = survey(x, y, sr) else { continue };
                    // Wholly inland, unless the island leaves no room.
                    if sv.sea > if relax < 2.5 { 0.0 } else { 0.12 } {
                        continue;
                    }
                    let rough = sv.hi - sv.lo;
                    // Settlements stay out of the spirit grove and keep lakes and sea outside their edge.
                    // On a cramped island the margin shrinks as placement relaxes.
                    let margin = if relax < 2.5 { r + 15.0 } else { r * 0.6 };
                    if sp.kind != SiteKind::Cave && (sv.grove > 0.0 || c.still_d[k] < margin) {
                        continue;
                    }
                    let jitter = hash(c.seed ^ 0x71 ^ sp.kind as u64, x as i32, y as i32);
                    let score = match sp.kind {
                        _ if sp.dispersed => {
                            // Any not-too-rough ground of its region kinds, not in wetland pools or on
                            // the peaks; water is welcome but not needed (a well, a stream).
                            let ok_kind = if sp.regions.is_empty() { matches!(kind, K::Meadow | K::Forest | K::OldForest | K::Highland | K::Beach) } else { sp.regions.contains(&kind) };
                            if !ok_kind || sv.still > 0.0 || sv.wetland > 0.1 * relax || sv.water > 0.15 * relax || rough > 9.0 * relax || sv.mean < 2.0 || sv.mean > 200.0 * relax {
                                continue;
                            }
                            -rough * 0.5 + jitter * 6.0
                        }
                        SiteKind::Town if sp.relief_m.is_some() => {
                            // A town in its own style: the relief it wants (a hillside to terrace, or
                            // flat ground), near the sea if it likes the coast.
                            let [lo, hi] = sp.relief_m.unwrap();
                            let ok_kind = matches!(kind, K::Meadow | K::Forest | K::Beach | K::Highland) || relax > 1.0 && matches!(kind, K::OldForest);
                            if !ok_kind || sv.still > 0.04 * (relax - 1.0) || sv.wetland > 0.1 * relax || sv.water > 0.1 * relax || rough < lo / relax || rough > hi * relax || sv.mean < 2.0 || sv.mean > 140.0 * relax {
                                continue;
                            }
                            let coast = if sp.coast && c.sea_d[k] < r * 2.5 { 14.0 } else { 0.0 };
                            -(rough - (lo + hi) * 0.5).abs() * 0.3 - 0.02 * c.wd[k].min(400.0) + coast + jitter * 4.0
                        }
                        SiteKind::Town => {
                            let ok_kind = matches!(kind, K::Meadow | K::Forest | K::Beach) || relax > 1.0 && matches!(kind, K::OldForest | K::Wetland);
                            if !ok_kind || sv.still > 0.04 * (relax - 1.0) || sv.wetland > 0.1 * relax || sv.water > 0.08 * relax || rough > 20.0 * relax || sv.mean < 2.0 || sv.mean > 80.0 * relax {
                                continue;
                            }
                            -rough - 0.03 * c.wd[k].min(600.0) + if c.wd[k] < r * 1.2 { 8.0 } else { 0.0 } + if c.sea_d[k] < r * 2.5 { 4.0 } else { 0.0 } + jitter * 3.0
                        }
                        SiteKind::Village => {
                            // Wetland pools leave no room for houses until placement has to relax.
                            let ok_kind = matches!(kind, K::Meadow | K::Forest | K::Beach) || relax > 1.6;
                            if !ok_kind || sv.still > 0.0 || sv.wetland > 0.2 * (relax - 1.0) || sv.water > 0.1 * relax || rough > 10.0 * relax || sv.mean < 2.0 || sv.mean > 120.0 * relax || c.wd[k] > 160.0 * relax {
                                continue;
                            }
                            -rough - 0.02 * c.wd[k] + jitter * 3.0
                        }
                        SiteKind::Giants => {
                            let ok_kind = kind == K::Highland || relax > 1.0 && kind == K::Peaks;
                            // Never below the foothills: the giants live up high.
                            if !ok_kind || sv.water > 0.08 * relax || rough > 70.0 * relax || sv.mean < c.p.regions.highland_m * 0.6 {
                                continue;
                            }
                            -rough + 0.12 * sv.mean + jitter * 5.0
                        }
                        SiteKind::SmallFolk => {
                            let ok_kind = matches!(kind, K::Forest | K::OldForest | K::Highland) || relax > 1.6 && kind != K::Peaks;
                            if !ok_kind || sv.water > 0.05 * relax || rough > 8.0 * relax || sv.mean < 20.0 / relax || sv.mean > 220.0 * relax {
                                continue;
                            }
                            -rough + if matches!(kind, K::Forest | K::OldForest) { 6.0 } else { 0.0 } + 0.02 * sv.mean + jitter * 4.0
                        }
                        SiteKind::Cave => {
                            let sl = slope(k);
                            let ok_kind = matches!(kind, K::Highland | K::Peaks);
                            if !ok_kind || sv.water > 0.0 || sl < 0.45 / relax || sl > 1.6 * relax || sv.mean < 50.0 / relax || sv.mean > c.max_e * 0.8 {
                                continue;
                            }
                            sl * 10.0 + jitter * 5.0
                        }
                    };
                    cands.push((score, x, y, sv.mean, kind));
                }
            st.cands = Some(Box::new(Level::new(cands, c.s)));
        }
        let level = st.cands.as_mut().expect("candidates");
        // Sites placed since this level last looked (all of them, the first time).
        for q in &placed[level.seen..] {
            level.apply(q, sp, relax);
        }
        level.seen = placed.len();
        while placed.iter().filter(|q| mine(q)).count() < want {
            if *budget == 0 {
                return false;
            }
            // Dispersed sites spread over region kinds too: each one already in this kind of
            // region counts against the next.
            let mut same_in = [0usize; 16];
            if sp.dispersed {
                for q in placed.iter().filter(|q| mine(q)) {
                    same_in[(q.region as usize).min(15)] += 1;
                }
            }
            let mut best: Option<(f32, usize)> = None;
            for (ci, &(score, _, _, _, kind)) in level.cands.iter().enumerate() {
                if level.blocked[ci] {
                    continue;
                }
                let eff = score + level.nearest[ci] / 100.0 - 4.0 * same_in[(kind as usize).min(15)] as f32;
                if best.is_none_or(|b| eff > b.0) {
                    best = Some((eff, ci));
                }
            }
            let Some((_, ci)) = best else { break };
            let (_, x, y, mean, kind) = level.cands[ci];
            placed.push(Site { kind: sp.kind, x, y, radius_m: r, ground_m: mean, scale: sp.scale, facing: 0.0, region: kind, flatten: sp.flatten, style: sp.style.clone(), ward: false, plan: None });
            level.apply(placed.last().expect("placed"), sp, relax);
            level.seen = placed.len();
            *budget -= 1;
        }
        st.cands = None;
        st.relax += 1;
    }
    true
}

/// Make every walkable tile reachable on foot: close pockets under `min_pocket` tiles, then cut
/// the cheapest crossing (fewest blocked tiles, 3 m wide) from every other pocket to the
/// largest. Water becomes sand (a ford), rock becomes dirt (a pass). Returns (opened, closed).
fn connect(tiles: &mut [u8], w: usize, min_pocket: u32, keep: &[usize], walls_hold: bool) -> (u32, u32) {
    let n = tiles.len();
    let walk = |t: u8| Terrain::from_u8(t).walkable();
    // Walls and drops (`walls_hold`) are never cut through: they are built, or the ground's own.
    let holds = |t: u8| walls_hold && (t == Terrain::Wall as u8 || t == Terrain::Drop as u8);
    let nb4 = |k: usize| {
        let (x, y) = (k % w, k / w);
        [(x > 0).then(|| k - 1), (x + 1 < w).then(|| k + 1), (y > 0).then(|| k - w), (y + 1 < w).then(|| k + w)]
    };
    let mut comp = vec![NONE; n];
    let mut sizes: Vec<u32> = Vec::new();
    let mut water_rim: Vec<u32> = Vec::new();
    let mut stack = Vec::new();
    for start in 0..n {
        if comp[start] != NONE || !walk(tiles[start]) {
            continue;
        }
        let id = sizes.len() as u32;
        let (mut size, mut wr, mut rr) = (0u32, 0u32, 0u32);
        comp[start] = id;
        stack.push(start);
        while let Some(k) = stack.pop() {
            size += 1;
            for q in nb4(k).into_iter().flatten() {
                if walk(tiles[q]) {
                    if comp[q] == NONE {
                        comp[q] = id;
                        stack.push(q);
                    }
                } else if tiles[q] == Terrain::Water as u8 {
                    wr += 1;
                } else {
                    rr += 1;
                }
            }
        }
        sizes.push(size);
        water_rim.push((wr >= rr) as u32);
    }
    for &k in keep {
        if comp[k] != NONE {
            sizes[comp[k] as usize] = sizes[comp[k] as usize].max(min_pocket);
        }
    }
    let Some(main) = (0..sizes.len()).max_by_key(|&c| sizes[c]) else { return (0, 0) };
    let mut closed = 0;
    for c in 0..sizes.len() {
        if c != main && sizes[c] < min_pocket {
            closed += 1;
        }
    }
    for k in 0..n {
        let c = comp[k];
        if c != NONE && c as usize != main && sizes[c as usize] < min_pocket {
            tiles[k] = if water_rim[c as usize] == 1 { Terrain::Water as u8 } else { Terrain::Rock as u8 };
            comp[k] = NONE;
        }
    }
    // 0-1 BFS from the main pocket: cost = blocked tiles crossed.
    let start = comp.iter().position(|&c| c as usize == main).unwrap();
    let mut dist = vec![u16::MAX; n];
    let mut prev = vec![u8::MAX; n];
    let mut dq = VecDeque::new();
    dist[start] = 0;
    dq.push_back(start);
    while let Some(k) = dq.pop_front() {
        let d = dist[k];
        for (dir, q) in nb4(k).into_iter().enumerate() {
            let Some(q) = q else { continue };
            if holds(tiles[q]) {
                continue;
            }
            let cost = (!walk(tiles[q])) as u16;
            let nd = d.saturating_add(cost);
            if nd < dist[q] {
                dist[q] = nd;
                prev[q] = dir as u8;
                if cost == 0 {
                    dq.push_front(q);
                } else {
                    dq.push_back(q);
                }
            }
        }
    }
    let mut best = vec![(u16::MAX, NONE); sizes.len()];
    for k in 0..n {
        let c = comp[k];
        if c != NONE && c as usize != main && dist[k] < best[c as usize].0 {
            best[c as usize] = (dist[k], k as u32);
        }
    }
    let mut opened = 0;
    let back = |k: usize, dir: u8| match dir {
        0 => k + 1,
        1 => k - 1,
        2 => k + w,
        _ => k - w,
    };
    for (c, &(d, k)) in best.iter().enumerate() {
        if c == main || k == NONE || d == u16::MAX {
            continue;
        }
        let mut cur = k as usize;
        while dist[cur] > 0 {
            cur = back(cur, prev[cur]);
            if dist[cur] > 0 || !walk(tiles[cur]) {
                let (x, y) = ((cur % w) as isize, (cur / w) as isize);
                for dy in -1..=1 {
                    for dx in -1..=1 {
                        let (bx, by) = (x + dx, y + dy);
                        if bx < 0 || by < 0 || bx >= w as isize || by >= w as isize {
                            continue;
                        }
                        let b = by as usize * w + bx as usize;
                        if !walk(tiles[b]) && !holds(tiles[b]) {
                            tiles[b] = if tiles[b] == Terrain::Water as u8 { Terrain::Sand as u8 } else { Terrain::Dirt as u8 };
                            opened += 1;
                        }
                    }
                }
            }
        }
    }
    (opened, closed)
}

/// Link pockets that walls cut off, through water or rock but never through a wall or a drop.
pub(crate) fn connect_walled(tiles: &mut [u8], w: usize) -> (u32, u32) {
    connect(tiles, w, 0, &[], true)
}

/// The land's parameters as any client may read them (the public `land` row's `params`): the
/// same land, with none of what its people call things (owner-known, 2026-11-12). The full
/// parameters stay with the authority (`land_plan`, private), for minds and records.
///
/// - Only what generation reads is kept: the params as given, less every key [`LandParams`]
///   does not parse (a lot's address, household, keepsake, notes and causes). Values keep their
///   given text, and defaults the params left out stay out (the typed form would write them
///   all, the ~575 KB building catalogue among them), so the row is no bigger than given.
/// - Lots lose their `name`; the keys that tie a plan together are renamed in step, so every
///   reference still holds: levels `v0…`, lots `l0…`, a lot's spots `s0…`, streets `r0…`,
///   stairs `w0…`, fixtures `f0…`, owners' household keys `household:o0…`, resource pools
///   `p0…`, relief stamps `t0…`. A plan's own `id` (the seed's site name, which `match_seed`
///   reads) and every kind, style, model and number stay.
///
/// The land a client builds from it is the one the authority built: the same digests (test
/// `public_params_build_the_same_land`).
pub fn public_params(full: &serde_json::Value) -> Result<serde_json::Value, String> {
    use serde_json::{json, Value};
    use std::collections::HashMap;
    if full.is_null() || full.as_object().is_some_and(|o| o.is_empty()) {
        return Ok(full.clone());
    }
    let typed: LandParams =
        serde_json::from_value(full.clone()).map_err(|e| format!("map.params: {e}"))?;
    // The params as given, less what the land does not read (notes, addresses, households,
    // keepsakes): every key the typed form does not carry. The typed form itself is not used:
    // it writes every default out (the building catalogue alone is ~575 KB) and f32s long.
    let mut v = full.clone();
    keep_given(
        &mut v,
        &serde_json::to_value(&typed).map_err(|e| format!("map.params: {e}"))?,
    );
    let rename = |map: &mut HashMap<String, String>, prefix: &str, old: &str| -> String {
        let n = map.len();
        map.entry(old.to_string())
            .or_insert_with(|| format!("{prefix}{n}"))
            .clone()
    };
    let mut owners: HashMap<String, String> = HashMap::new();
    for plan in v
        .get_mut("plans")
        .and_then(Value::as_array_mut)
        .into_iter()
        .flatten()
    {
        let mut levels: HashMap<String, String> = HashMap::new();
        let mut lots: HashMap<String, String> = HashMap::new();
        let mut spots: HashMap<(String, String), String> = HashMap::new();
        for l in plan
            .get_mut("levels")
            .and_then(Value::as_array_mut)
            .into_iter()
            .flatten()
        {
            if let Some(id) = l["id"].as_str().map(String::from) {
                l["id"] = json!(rename(&mut levels, "v", &id));
            }
        }
        // Only keys the params have are touched (indexing a missing key would add a null).
        let level = |levels: &HashMap<String, String>, x: Option<&mut Value>| {
            if let Some(x) = x {
                if let Some(id) = x.as_str() {
                    if let Some(n) = levels.get(id) {
                        *x = json!(n);
                    }
                }
            }
        };
        for l in plan
            .get_mut("lots")
            .and_then(Value::as_array_mut)
            .into_iter()
            .flatten()
        {
            let old = l["id"].as_str().unwrap_or_default().to_string();
            if l.get("id").is_some() {
                l["id"] = json!(rename(&mut lots, "l", &old));
            }
            if let Some(o) = l.as_object_mut() {
                o.remove("name");
            }
            level(&levels, l.get_mut("level"));
            for (k, sp) in l
                .get_mut("spots")
                .and_then(Value::as_array_mut)
                .into_iter()
                .flatten()
                .enumerate()
            {
                if let Some(name) = sp["name"].as_str().map(String::from) {
                    spots.insert((old.clone(), name), format!("s{k}"));
                    sp["name"] = json!(format!("s{k}"));
                }
            }
        }
        for (k, st) in plan
            .get_mut("streets")
            .and_then(Value::as_array_mut)
            .into_iter()
            .flatten()
            .enumerate()
        {
            if st["id"].as_str().is_some_and(|s| !s.is_empty()) {
                st["id"] = json!(format!("r{k}"));
            }
            level(&levels, st.get_mut("level"));
        }
        for (k, st) in plan
            .get_mut("stairs")
            .and_then(Value::as_array_mut)
            .into_iter()
            .flatten()
            .enumerate()
        {
            if st.get("id").is_some() {
                st["id"] = json!(format!("w{k}"));
            }
            level(&levels, st.get_mut("from"));
            level(&levels, st.get_mut("to"));
        }
        if let Some(sq) = plan.get_mut("square").filter(|q| q.is_object()) {
            level(&levels, sq.get_mut("level"));
        }
        for (k, f) in plan
            .get_mut("fixtures")
            .and_then(Value::as_array_mut)
            .into_iter()
            .flatten()
            .enumerate()
        {
            if f["id"].as_str().is_some_and(|s| !s.is_empty()) {
                f["id"] = json!(format!("f{k}"));
            }
        }
        // A resource's `pool` (the node whose stock several share) is a key too.
        let mut pools: HashMap<String, String> = HashMap::new();
        for r in plan
            .get_mut("resources")
            .and_then(Value::as_array_mut)
            .into_iter()
            .flatten()
        {
            if let Some(p) = r["pool"]
                .as_str()
                .filter(|p| !p.is_empty())
                .map(String::from)
            {
                r["pool"] = json!(rename(&mut pools, "p", &p));
            }
        }
        for st in plan
            .get_mut("structures")
            .and_then(Value::as_array_mut)
            .into_iter()
            .flatten()
        {
            let lot = st["lot"].as_str().map(String::from);
            if let (Some(lot), Some(spot)) = (lot.clone(), st["spot"].as_str().map(String::from)) {
                if let Some(n) = spots.get(&(lot, spot)) {
                    st["spot"] = json!(n);
                }
            }
            if let Some(n) = lot.and_then(|l| lots.get(&l).cloned()) {
                st["lot"] = json!(n);
            }
            // An owner is `household:<key>` (the key is a family's name): only the key is renamed.
            if let Some(o) = st["owner"].as_str().map(String::from) {
                let (head, key) = o.split_once(':').map_or(("", o.as_str()), |(h, k)| (h, k));
                let n = rename(&mut owners, "o", key);
                st["owner"] = json!(if head.is_empty() {
                    n
                } else {
                    format!("{head}:{n}")
                });
            }
        }
    }
    for (k, st) in v
        .pointer_mut("/relief/stamps")
        .and_then(Value::as_array_mut)
        .into_iter()
        .flatten()
        .enumerate()
    {
        if st["id"].as_str().is_some_and(|s| !s.is_empty()) {
            st["id"] = json!(format!("t{k}"));
        }
    }
    Ok(v)
}

/// Drop from `out` every object key that `known` does not have, element by element through
/// arrays.
fn keep_given(out: &mut serde_json::Value, known: &serde_json::Value) {
    use serde_json::Value;
    match (out, known) {
        (Value::Object(o), Value::Object(g)) => {
            o.retain(|k, _| g.contains_key(k));
            for (k, x) in o.iter_mut() {
                keep_given(x, &g[k]);
            }
        }
        (Value::Array(o), Value::Array(g)) => {
            for (x, y) in o.iter_mut().zip(g) {
                keep_given(x, y);
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn public_params_build_the_same_land() {
        for (name, src) in [
            ("cullet", include_str!("../../seeds/cullet.json")),
            ("plan-test", include_str!("../../seeds/plan-test.json")),
        ] {
            let seed: serde_json::Value = serde_json::from_str(src).unwrap();
            let full = &seed["map"]["params"];
            let size = seed["map"]["size"].as_u64().unwrap() as u32;
            let public = public_params(full).unwrap();
            let text = public.to_string();
            // What the people call things is not in it: lot names, spot names, street names,
            // notes, households.
            for lot in full["plans"][0]["lots"].as_array().unwrap() {
                if let Some(n) = lot["name"].as_str() {
                    assert!(
                        !text.contains(&format!("\"{n}\"")),
                        "{name}: lot name {n:?} in the public params"
                    );
                }
                for sp in lot["spots"].as_array().into_iter().flatten() {
                    let n = sp["name"].as_str().unwrap();
                    assert!(
                        !text.contains(&format!("\"{n}\"")),
                        "{name}: spot name {n:?} in the public params"
                    );
                }
            }
            for word in [
                "note",
                "household_name",
                "address",
                "keepsake",
                "district",
                "Cinder Row",
                "the Heron",
                "arcade bay 1",
            ] {
                assert!(
                    !text.contains(word),
                    "{name}: {word:?} in the public params"
                );
            }
            // Households are named by their families: no original key is left.
            for st in full["plans"][0]["structures"]
                .as_array()
                .into_iter()
                .flatten()
            {
                if let Some(o) = st["owner"].as_str() {
                    assert!(
                        !text.contains(&format!("\"{o}\"")),
                        "{name}: owner {o:?} in the public params"
                    );
                }
            }
            // No bigger than what was given (no defaults written out).
            assert!(
                text.len() <= full.to_string().len(),
                "{name}: public params {} bytes, given {}",
                text.len(),
                full.to_string().len()
            );
            // And the land built from it is the same land.
            let a: LandParams = serde_json::from_value(full.clone()).unwrap();
            let b: LandParams = serde_json::from_value(public.clone()).unwrap();
            crate::settle::validate_plans(&b.plans, size).unwrap();
            let (la, lb) = (generate(7, size, &a), generate(7, size, &b));
            let (ma, _) = crate::host::hosted_map(&la, &a);
            let (mb, _) = crate::host::hosted_map(&lb, &b);
            let (da, db) = (
                crate::host::digests(&la, &ma),
                crate::host::digests(&lb, &mb),
            );
            assert!(
                da.tiles == db.tiles && da.heights == db.heights && da.layout == db.layout,
                "{name}: the public params build another land"
            );
            // What a client derives besides the digests: lots (models, frontage, landmarks) and
            // props, drawn from the regenerated land and never sent as rows.
            assert_eq!(serde_json::to_string(&la.lots).unwrap(), serde_json::to_string(&lb.lots).unwrap(), "{name}: other lots");
            assert_eq!(serde_json::to_string(&la.props).unwrap(), serde_json::to_string(&lb.props).unwrap(), "{name}: other props");
        }
        assert_eq!(
            public_params(&serde_json::json!({})).unwrap(),
            serde_json::json!({})
        );
        // The megacity floor's params (too big a land to build here): public, parsed, its plans
        // valid, and no bigger than given.
        let seed: serde_json::Value =
            serde_json::from_str(include_str!("../../seeds/floor-megacity.json")).unwrap();
        let full = &seed["map"]["params"];
        let public = public_params(full).unwrap();
        let b: LandParams = serde_json::from_value(public.clone()).unwrap();
        crate::settle::validate_plans(&b.plans, seed["map"]["size"].as_u64().unwrap() as u32)
            .unwrap();
        assert!(public.to_string().len() <= full.to_string().len());
    }

    /// An authored coastline replaces the generated island, and stamps set the ground's height,
    /// region and tiles where they say; lake basins keep off them. Lands without either are
    /// unchanged (`host::tests::pinned_digests_hold`).
    #[test]
    fn an_authored_outline_and_stamps_shape_the_land() {
        let sq = |x0: f32, y0: f32, x1: f32, y1: f32| vec![[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
        let mut p = LandParams { sites: Vec::new(), ..LandParams::default() };
        p.relief = Relief { outline: sq(250.0, 300.0, 774.0, 700.0), coast_warp: 0.02, hills_m: 2.0, peak_m: [1.0, 1.0], foothills_m: 0.0, islets: 0, ..Relief::default() };
        p.relief.stamps = vec![
            Stamp { id: "a hill".into(), area: sq(440.0, 420.0, 520.0, 480.0), height_m: Some(40.0), blend_m: 40.0, region: Some(RegionKind::Highland), ground: None },
            Stamp { id: "a strand".into(), area: sq(300.0, 640.0, 420.0, 712.0), height_m: Some(0.8), blend_m: 10.0, region: Some(RegionKind::Beach), ground: Some("sand".into()) },
        ];
        validate_relief(&p.relief).unwrap();
        let l = generate(9, 1024, &p);
        for (x, y) in [(120.0, 512.0), (900.0, 512.0), (512.0, 160.0), (512.0, 860.0)] {
            assert_eq!(l.map.at(x, y), Terrain::Water, "sea at ({x}, {y})");
        }
        assert!(l.height(600.0, 600.0) > 2.0 && l.map.at(600.0, 600.0) != Terrain::Water, "land inside the outline");
        let h = l.height(480.0, 450.0);
        assert!((h - 40.0).abs() < 5.0, "the hill at {h} m");
        assert_eq!(l.kind_at(480.0, 450.0), RegionKind::Highland);
        let (mut sand, mut other) = (0, 0);
        for y in 645..705 {
            for x in 305..415 {
                match l.map.at(x as f32 + 0.5, y as f32 + 0.5) {
                    Terrain::Water => {}
                    Terrain::Sand => sand += 1,
                    _ => other += 1,
                }
            }
        }
        assert!(sand > 3000 && other == 0, "the strand: {sand} sand, {other} other");
        for lake in &l.lakes {
            for st in &p.relief.stamps {
                assert!(poly_signed(&st.poly(), lake.centre) < -st.blend_m, "a lake at {:?} on {}", lake.centre, st.id);
            }
        }
        let refused = |f: &dyn Fn(&mut Relief), want: &str| {
            let mut r = p.relief.clone();
            f(&mut r);
            let e = validate_relief(&r).expect_err(want);
            assert!(e.contains(want), "{want:?} not in {e:?}");
        };
        refused(&|r| r.outline = vec![[0.0, 0.0], [1.0, 1.0]], "outline needs a polygon");
        refused(&|r| (r.stamps[0].height_m, r.stamps[0].region) = (None, None), "sets neither");
        refused(&|r| r.stamps[1].ground = Some("lava".into()), "is not grass");
        refused(&|r| r.stamps[0].height_m = Some(f32::NAN), "must be numbers");
    }

    /// Dispersed sites (hamlets) are placed a bounded number per step of [`Gen`]: a land asking
    /// for many takes several steps, none places more than its budget, and they keep their
    /// spacing (relaxed at most to the last relaxation).
    #[test]
    fn dispersed_sites_place_in_bounded_steps() {
        let mut p = LandParams::default();
        for sp in p.sites.iter_mut().filter(|sp| sp.dispersed) {
            sp.per_km2 = 30.0;
        }
        let mut g = Gen::new(7, 2048, p.clone());
        let (mut steps, mut most) = (0, 0);
        while !g.is_done() {
            let dispersed = g.next == Next::Dispersed;
            let before = g.work.as_ref().map_or(0, |w| w.land.sites.len());
            g.step();
            if dispersed {
                steps += 1;
                most = most.max(g.work.as_ref().map_or(0, |w| w.land.sites.len()) - before);
            }
        }
        let land = g.into_land();
        let hamlets: Vec<&Site> = land.sites.iter().filter(|s| s.style.as_deref() == Some("hamlet")).collect();
        assert!(steps >= 2, "{} hamlets in {steps} step(s)", hamlets.len());
        assert!(most <= DISPERSED_PER_STEP, "a step placed {most}");
        let spacing = p.sites.iter().find(|sp| sp.dispersed).unwrap().spacing_m / RELAX[RELAX.len() - 1].sqrt();
        for (i, a) in hamlets.iter().enumerate() {
            for b in &hamlets[i + 1..] {
                assert!((a.x - b.x).hypot(a.y - b.y) >= spacing - 1e-3, "hamlets at {:?} and {:?}", (a.x, a.y), (b.x, b.y));
            }
        }
        eprintln!("{} hamlets in {steps} dispersed steps, at most {most} a step", hamlets.len());
    }
    use std::sync::OnceLock;

    fn default_size() -> &'static Land {
        static L: OnceLock<Land> = OnceLock::new();
        L.get_or_init(|| generate_default(7, 2048))
    }

    fn small() -> &'static Land {
        static L: OnceLock<Land> = OnceLock::new();
        L.get_or_init(|| generate_default(5, 1024))
    }

    fn components(map: &Map) -> usize {
        let w = map.w as usize;
        let mut seen = vec![false; map.tiles.len()];
        let mut count = 0;
        for s in 0..map.tiles.len() {
            if seen[s] || !Terrain::from_u8(map.tiles[s]).walkable() {
                continue;
            }
            count += 1;
            let mut stack = vec![s];
            seen[s] = true;
            while let Some(k) = stack.pop() {
                let (x, y) = (k % w, k / w);
                for q in [(x > 0).then(|| k - 1), (x + 1 < w).then(|| k + 1), (y > 0).then(|| k - w), (y + 1 < w).then(|| k + w)].into_iter().flatten() {
                    if !seen[q] && Terrain::from_u8(map.tiles[q]).walkable() {
                        seen[q] = true;
                        stack.push(q);
                    }
                }
            }
        }
        count
    }

    #[test]
    fn deterministic() {
        let a = small();
        let b = generate_default(5, 1024);
        assert_eq!(a.map.tiles, b.map.tiles);
        assert_eq!(a.height(400.3, 512.7), b.height(400.3, 512.7));
        assert_eq!(a.sites.len(), b.sites.len());
    }

    #[test]
    fn every_walkable_tile_is_reachable() {
        assert_eq!(components(&small().map), 1);
        assert_eq!(components(&generate_default(9, 1024).map), 1);
    }

    #[test]
    fn has_the_required_features() {
        features(small());
        features(default_size());
        let l = default_size();
        assert_eq!(components(&l.map), 1);
        let peak = l.ranges[0].summit.2;
        assert!((250.0..=520.0).contains(&peak), "main summit {peak} m");
        assert!(l.rivers.iter().any(|r| r.length_m > 800.0), "a long river");
        assert!(l.lakes.iter().any(|k| (100.0..=450.0).contains(&k.across_m)), "a lake 100-400 m across");
        // Regions clipped by the map's edge are smaller; check the interior ones.
        let inside = |c: (f32, f32)| c.0.min(c.1) > 320.0 && c.0.max(c.1) < l.size as f32 - 320.0;
        for r in l.regions.iter().filter(|r| r.kind != RegionKind::Sea && r.land_m2 > 0.5 * r.area_m2 && inside(r.centre)) {
            let across = 2.0 * (r.area_m2 / std::f32::consts::PI).sqrt();
            assert!((150.0..=650.0).contains(&across), "region {} is {across} m across", r.id);
        }
        let town = l.sites.iter().find(|s| s.kind == SiteKind::Town).unwrap();
        let giants = l.sites.iter().find(|s| s.kind == SiteKind::Giants).unwrap();
        assert!(giants.ground_m > town.ground_m + 60.0, "giants live in the highlands");
    }

    fn features(l: &Land) {
        for kind in [RegionKind::Meadow, RegionKind::Forest, RegionKind::OldForest, RegionKind::Wetland, RegionKind::Highland, RegionKind::Beach] {
            assert!(l.regions.iter().any(|r| r.kind == kind), "no {kind:?} region at {} m", l.size);
        }
        assert_eq!(l.regions.iter().filter(|r| r.kind == RegionKind::SpiritGrove).count(), 1);
        let count = |k: SiteKind| l.sites.iter().filter(|s| s.kind == k && s.style.is_none()).count();
        assert_eq!(count(SiteKind::Town), 1);
        assert!(count(SiteKind::Village) >= 2);
        assert_eq!(count(SiteKind::Giants), 1);
        assert_eq!(count(SiteKind::SmallFolk), 1);
        assert!(count(SiteKind::Cave) >= 2);
        assert!(!l.rivers.is_empty() && !l.lakes.is_empty());
        let water = l.map.tiles.iter().filter(|t| **t == Terrain::Water as u8).count();
        assert!(water > l.map.tiles.len() / 10, "a sea surrounds the island: {water}");
        // Sites stand on land.
        for s in &l.sites {
            assert!(l.map.at(s.x, s.y).walkable() || s.kind != SiteKind::Cave, "cave mouth on blocked ground");
        }
    }

    #[test]
    fn height_is_finite_and_follows_the_water() {
        follows_the_water(small(), 3);
    }

    /// Slow: `cargo test --release -p living-rules land::tests::seed_sweep -- --ignored`.
    #[test]
    #[ignore]
    fn seed_sweep() {
        for size in [1024, 2048, 3072] {
            for seed in [5, 7, 9, 11, 23] {
                let l = generate_default(seed, size);
                println!("seed {seed} size {size}");
                features(&l);
                assert_eq!(components(&l.map), 1, "seed {seed} size {size}");
                follows_the_water(&l, 5);
            }
        }
    }

    fn follows_the_water(l: &Land, every: usize) {
        let w = l.map.w;
        for j in (0..w).step_by(every) {
            for i in (0..w).step_by(every) {
                let (x, y) = (i as f32 + 0.5, j as f32 + 0.5);
                let h = l.height(x, y);
                assert!(h.is_finite(), "height {h} at {x}, {y}");
                if l.map.get(i as i32, j as i32) == Terrain::Water {
                    assert!(h < l.water_level(x, y), "water tile above its surface at {x}, {y}");
                } else {
                    assert!(h >= l.water_level(x, y) - 1e-3 || l.sd_at(x, y) >= 6.0, "bank below the water at {x}, {y}: h {h} level {} sd {} t {} tile {:?}", l.water_level(x, y), l.sd_at(x, y), l.terrain(x, y), l.map.get(i as i32, j as i32));
                }
            }
        }
    }

    #[test]
    fn height_is_continuous() {
        let l = small();
        // Lines across the whole map cross coasts, rivers, slopes and sites.
        for y in [300.2f32, 512.6, 731.1] {
            let mut prev = l.height(0.0, y);
            let mut x = 0.0;
            while x < 1023.0 {
                x += 0.02;
                let h = l.height(x, y);
                assert!((h - prev).abs() < 0.25, "jump of {} at ({x}, {y})", h - prev);
                prev = h;
            }
        }
    }

    #[test]
    fn params_are_data() {
        let p = LandParams::default();
        let json = serde_json::to_string(&p).unwrap();
        let back: LandParams = serde_json::from_str(&json).unwrap();
        assert_eq!(back.sites.len(), p.sites.len());
        let partial: LandParams = serde_json::from_str(r#"{"cell_m": 8.0, "relief": {"islets": 0}}"#).unwrap();
        assert_eq!(partial.relief.islets, 0);
        assert_eq!(partial.relief.peak_m, p.relief.peak_m);
    }
}
