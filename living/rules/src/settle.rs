//! Settlement planner for the km-scale land ([`crate::land`]; see `docs/FIRST_WORLD.md`).
//!
//! For the island: roads between the settlements, the coast and the cave mouths, routed on a
//! 4 m grid by least cost (gentle grades, around rock and still water, over rivers at fords),
//! joining each other in T-junctions so the network branches like a real one.
//!
//! For each town, village, giants' and small-folk site:
//! - a plaza (a market square or a green) with a landmark (a tower or a well);
//! - main streets, which are the island roads arriving at the plaza, plus radial streets where
//!   the roads leave a large gap;
//! - lanes branching off them that bend with the slope (along contours) and around the centre,
//!   joining other streets or ending in a dead end;
//! - building lots along every street and round the plaza, each facing its street, denser near
//!   the centre and thinning out into gardens and fields beyond the edge; each lot is sized to
//!   a generated model it names (narrow townhouses beside wide ones, cottages, longhouses,
//!   corner buildings at junctions), and the big buildings (an inn, a hall, a chapel) take the
//!   plaza's edge;
//! - for a walled town, a wall following a terrain-aware boundary, with gates where roads cross
//!   it, towers along it and a lane inside it.
//!
//! [`Land::height`] levels the ground under every building lot to its floor (a pad with a smooth
//! skirt), and lays roads along a smoothed profile with a slight cross-fall. Where a site has
//! relief and its style terraces, the ground steps down the hill in level terraces with drops
//! between them; streets ramp across the drops, lanes stop short of them, and stairs join the
//! levels ([`terrace`]).
//!
//! After the lots, [`ornament`] dresses each settlement with props ([`Prop`]): benches, a
//! fountain or market cross, barrels and carts by inns and workshops, fenced gardens with trees
//! and washing lines, flower boxes, signs, banners, kerbs, street trees, the cyberpunk street's
//! neon, and the terraces' stairs and retaining walls.
//!
//! Mechanics only: every size, count and kind is a field of [`SettleParams`]. Building footprints
//! come from `data/buildings.json`, written by `living/tools/blender/buildings.py`: every
//! generated model with its exact footprint, which a lot is sized to.

mod metro;
mod ornament;
mod plan;
mod terrace;

pub use metro::{District, MetroParams};
pub use plan::{placed_structures, stranded_doors, validate as validate_plan, Inside, INSIDE_REACH_M, validate_all as validate_plans, Facing, FixtureSpec, Laid, LaidFixture, LaidLot, LaidResource, LaidStructure, LevelSpec, LotSpec, PlanSpec, ResourceSpec, SpotSpec, StructureSpec, SquareSpec, StairSpec, StreetSpec};
pub(crate) use plan::{covers as plan_covers, resolve as resolve_plan, site as plan_site, stamp_macro as stamp_plans, Resolved as PlanResolved};

pub(crate) use terrace::Terrace;

use crate::det::Det;
use crate::land::{hash, lerp, smoothstep, value, Land, RegionKind, Site, SiteKind};
use crate::map::Terrain;
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use std::collections::BinaryHeap;

pub type V2 = (f32, f32);

// ------------------------------------------------------------------------------------------
// Output

/// What stands on a lot. [`LotKind::model`] names the `buildings.py` kind that fits it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LotKind {
    House,
    Townhouse,
    Inn,
    Hall,
    Chapel,
    Workshop,
    Barn,
    Tower,
    Well,
    MarketStall,
    Lamp,
    /// A kitchen garden behind a house: no building, not levelled.
    Garden,
    /// A field or pasture: no building, not levelled.
    Field,
}

impl LotKind {
    pub fn id(self) -> &'static str {
        match self {
            Self::House => "house",
            Self::Townhouse => "townhouse",
            Self::Inn => "inn",
            Self::Hall => "hall",
            Self::Chapel => "chapel",
            Self::Workshop => "workshop",
            Self::Barn => "barn",
            Self::Tower => "tower",
            Self::Well => "well",
            Self::MarketStall => "market_stall",
            Self::Lamp => "lamp",
            Self::Garden => "garden",
            Self::Field => "field",
        }
    }

    pub const ALL: [LotKind; 13] = [
        Self::House,
        Self::Townhouse,
        Self::Inn,
        Self::Hall,
        Self::Chapel,
        Self::Workshop,
        Self::Barn,
        Self::Tower,
        Self::Well,
        Self::MarketStall,
        Self::Lamp,
        Self::Garden,
        Self::Field,
    ];

    pub fn from_id(id: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|k| k.id() == id)
    }

    /// The `buildings.py` kind (asset folder `envs/<site env>/<kind>/`), if a model stands here.
    pub fn model(self) -> Option<&'static str> {
        match self {
            Self::Garden | Self::Field => None,
            k => Some(k.id()),
        }
    }

    /// Whether the ground is levelled to the lot's floor. Small things on the street or in a
    /// level plaza stand on their own foundations.
    pub fn padded(self) -> bool {
        matches!(self, Self::House | Self::Townhouse | Self::Inn | Self::Hall | Self::Chapel | Self::Workshop | Self::Barn | Self::Tower | Self::Well)
    }

    /// A building that stands on the plaza's edge as one of the settlement's big lots.
    pub fn big(self) -> bool {
        matches!(self, Self::Inn | Self::Hall | Self::Chapel)
    }
}

/// What a lot's front faces.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Frontage {
    Road(u32),
    /// The plaza of a settlement (index into [`Land::settlements`]).
    Plaza(u16),
    /// A garden faces the house it belongs to (index into [`Land::lots`]).
    Lot(u32),
    /// A tower standing on its settlement's wall, door toward the town.
    Wall(u16),
    /// Behind the frontages of a city block ([`MetroParams`] districts with `fill_m`): faces
    /// this road, reached through the alleys left between lots.
    Alley(u32),
}

#[derive(Clone, Debug, Serialize)]
pub struct Lot {
    pub settlement: u16,
    pub kind: LotKind,
    pub centre: V2,
    /// Along the front, and from front to back (metres): the model's footprint plus the style's
    /// margin on every side.
    pub width_m: f32,
    pub depth_m: f32,
    /// Unit vector from the centre toward what the lot faces.
    pub front: V2,
    /// Turn about the vertical that brings a model's front (+Z in glTF) to `front`: in the game's
    /// frame (x = land x, z = land y) that is `Quat::from_rotation_y(yaw)`.
    pub yaw: f32,
    /// Ground level of the lot (metres); a model's origin goes here. For padded kinds the ground
    /// under the whole footprint is exactly this level.
    pub floor_m: f32,
    pub frontage: Frontage,
    pub landmark: bool,
    /// The model that stands here: a `buildings.py` file under the client's `envs/` (for
    /// example `fantasy_city/house/gen-house-fantasy-cottage-03.glb`), chosen from
    /// `data/buildings.json` among the models that fit. None for gardens and fields, or when the
    /// table has no models of the kind.
    pub model_file: Option<String>,
    /// That model's height above the floor (0 without one).
    pub height_m: f32,
}

impl Lot {
    /// The footprint's corners: front left, front right, back right, back left.
    pub fn corners(&self) -> [V2; 4] {
        self.rect().corners()
    }

    fn rect(&self) -> Rect {
        Rect { c: self.centre, f: self.front, hw: self.width_m * 0.5, hd: self.depth_m * 0.5 }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RoadClass {
    /// Between settlements.
    Trunk,
    /// A settlement's main street.
    Street,
    Lane,
    /// A footpath (to a cave mouth, or the small folk's ways).
    Path,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RoadEnd {
    /// The centre of a site (index into [`Land::sites`]).
    Site(u16),
    /// The edge of a settlement's plaza.
    Plaza(u16),
    /// A junction on another road.
    Road(u32),
    /// A landing on the sea shore.
    Shore,
    /// A dead end.
    Free,
}

#[derive(Clone, Debug, Serialize)]
pub struct Road {
    pub class: RoadClass,
    pub settlement: Option<u16>,
    /// Centre line (metres) and the surface height along it.
    pub points: Vec<V2>,
    pub heights: Vec<f32>,
    pub width_m: f32,
    /// Per segment: rise of the surface per metre to the left of travel (x east, y south).
    pub crossfall: Vec<f32>,
    pub ends: [RoadEnd; 2],
    pub length_m: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CrossingKind {
    Ford,
    Bridge,
}

/// Where a road crosses a river.
#[derive(Clone, Debug, Serialize)]
pub struct Crossing {
    pub road: u32,
    pub kind: CrossingKind,
    pub at: V2,
    /// Unit direction of the road across the water, and the water's width along it.
    pub along: V2,
    pub span_m: f32,
    pub water_m: f32,
}

#[derive(Clone, Debug, Serialize)]
pub struct Plaza {
    pub centre: V2,
    /// Outline (closed, counter-clockwise on the map).
    pub points: Vec<V2>,
    pub floor_m: f32,
    /// A paved market square, or a green.
    pub paved: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct Gate {
    pub at: V2,
    /// Unit vector out of the town.
    pub out: V2,
    pub width_m: f32,
    pub road: u32,
}

#[derive(Clone, Debug, Serialize)]
pub struct Wall {
    /// The wall's centre line, closed: straight curtains between `corners`.
    pub ring: Vec<V2>,
    /// Where the wall turns; towers stand at most of them.
    pub corners: Vec<V2>,
    /// Stretches of standing wall: the ring cut at gates and where it would stand in water.
    pub runs: Vec<Vec<V2>>,
    pub gates: Vec<Gate>,
    pub height_m: f32,
    pub thickness_m: f32,
}

/// One piece of wall: centre, a yaw that turns a wall model's outer face (+Z in glTF) out of
/// the town (as [`Lot::yaw`]), and its length along the wall.
#[derive(Clone, Copy, Debug, Serialize)]
pub struct WallPiece {
    pub centre: V2,
    pub yaw: f32,
    pub length_m: f32,
}

impl Wall {
    /// Pieces about `piece_m` long along every run, for placing wall-segment models.
    pub fn pieces(&self, piece_m: f32, town_centre: V2) -> Vec<WallPiece> {
        let mut out = Vec::new();
        for run in &self.runs {
            let cl = cumlen(run);
            let total = *cl.last().unwrap_or(&0.0);
            let n = (total / piece_m).round().max(1.0) as usize;
            let step = total / n as f32;
            for i in 0..n {
                let (p, t) = at_s(run, &cl, (i as f32 + 0.5) * step);
                let mut out_dir = perp(t);
                if dot(out_dir, sub(p, town_centre)) < 0.0 {
                    out_dir = mul(out_dir, -1.0);
                }
                out.push(WallPiece { centre: p, yaw: yaw_of(out_dir), length_m: step });
            }
        }
        out
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct Settlement {
    /// Index into [`Land::sites`].
    pub site: u16,
    pub kind: SiteKind,
    /// The `buildings.py` style its models come from.
    pub style: String,
    pub centre: V2,
    pub scale: f32,
    /// Mean distance from the centre to the edge of the built-up area.
    pub radius_m: f32,
    pub plaza: Plaza,
    pub wall: Option<Wall>,
    /// Lots of this settlement: `lots.0..lots.1` in [`Land::lots`].
    pub lots: (u32, u32),
    pub landmark: Option<u32>,
    /// Roads that belong to it (streets and lanes; trunk roads have no settlement).
    pub roads: Vec<u32>,
    /// Height of one terrace step when its ground is terraced (0: not terraced).
    pub terrace_m: f32,
    /// Laid out from a hand-authored plan ([`PlanSpec`]): its lots are their models'
    /// footprints exactly (no style margin), and the generated steps leave it alone.
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub planned: bool,
}

impl Settlement {
    /// Whether a point lies in the plaza.
    pub fn in_plaza(&self, p: V2) -> bool {
        poly_contains(&self.plaza.points, p)
    }
}

/// The client's environment folder (`envs/<folder>/<kind>/`) of a `buildings.py` style.
pub fn env_of(style: &str) -> &'static str {
    match style {
        "giant" => "giants_city",
        "small" => "small_city",
        "steampunk" => "steampunk_city",
        "cyberpunk" => "cyberpunk_city",
        // The glassmakers' harbour (docs/SMALL_CITY.md), from its own kit (`cullet.py`).
        "cullet" => "cullet",
        // The megacity's district styles, and the wastes' outposts, camps and ruins, built from
        // the megacity kit (`Style::kit`, living/tools/blender/city.py). Its folder's name starts
        // with `cyberpunk`, so clients dress its people in the cyberpunk look.
        s if is_megacity(s) => "cyberpunk_megacity",
        _ => "fantasy_city",
    }
}

/// The megacity floor's settlement styles ([`MetroParams`] districts and the wastes' sites).
pub fn is_megacity(style: &str) -> bool {
    matches!(style, "metro" | "corporate" | "neon" | "megablock" | "market" | "oldtown" | "slum" | "works" | "outpost" | "salvage" | "ruin")
}

/// The paving of a settlement's roads and squares by its style, for clients: `pavers` (large
/// panels), `setts`, `earth`, `gravel`, or None for the default (flagstone squares, cobbled
/// streets).
pub fn road_surface(style: &str) -> Option<&'static str> {
    match style {
        "cyberpunk" | "metro" | "corporate" | "neon" | "megablock" | "market" | "works" => Some("pavers"),
        "steampunk" | "oldtown" => Some("setts"),
        "slum" => Some("earth"),
        "outpost" | "salvage" | "ruin" => Some("gravel"),
        _ => None,
    }
}

/// The `buildings.py` kind of a model file (`steampunk_city/clocktower/gen-....glb` is a
/// `clocktower`): the folder its kind's assets are in.
pub fn asset_kind(model_file: &str) -> Option<&str> {
    model_file.split('/').nth(1)
}

/// A street ornament, or a piece of terracing. Its `buildings.py` kind has the same id.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PropKind {
    Barrel,
    Crate,
    Cart,
    Bench,
    Fountain,
    MarketCross,
    Fence,
    Gate,
    Planter,
    FlowerBox,
    Sign,
    Banner,
    WashingLine,
    Tree,
    Kerb,
    /// A flight of steps from one terrace down to the next; the ground under it rises with it.
    Stairs,
    /// A wall along a drop, its face toward the lower ground.
    RetainingWall,
    NeonSign,
    Billboard,
    Cable,
    Kiosk,
    FoodStall,
    Pipe,
    /// A piece of elevated highway over a trunk road (presentation: the rules keep the road at
    /// street level, docs/FLOORS.md "Verticality").
    Highway,
    /// A tower on a city wall's corner.
    WallTower,
    Vending,
    /// A steam vent in the street (the client adds the steam).
    Vent,
    Trash,
    Barrier,
    /// A parked vehicle: scenery until vehicles exist in the rules, so it does not block.
    Vehicle,
    Hologram,
    Scaffold,
    Crane,
    Container,
    Salvage,
}

impl PropKind {
    pub const ALL: [PropKind; 35] = [
        Self::Barrel,
        Self::Crate,
        Self::Cart,
        Self::Bench,
        Self::Fountain,
        Self::MarketCross,
        Self::Fence,
        Self::Gate,
        Self::Planter,
        Self::FlowerBox,
        Self::Sign,
        Self::Banner,
        Self::WashingLine,
        Self::Tree,
        Self::Kerb,
        Self::Stairs,
        Self::RetainingWall,
        Self::NeonSign,
        Self::Billboard,
        Self::Cable,
        Self::Kiosk,
        Self::FoodStall,
        Self::Pipe,
        Self::Highway,
        Self::WallTower,
        Self::Vending,
        Self::Vent,
        Self::Trash,
        Self::Barrier,
        Self::Vehicle,
        Self::Hologram,
        Self::Scaffold,
        Self::Crane,
        Self::Container,
        Self::Salvage,
    ];

    pub fn id(self) -> &'static str {
        match self {
            Self::Barrel => "barrel",
            Self::Crate => "crate",
            Self::Cart => "cart",
            Self::Bench => "bench",
            Self::Fountain => "fountain",
            Self::MarketCross => "market_cross",
            Self::Fence => "fence",
            Self::Gate => "gate",
            Self::Planter => "planter",
            Self::FlowerBox => "flower_box",
            Self::Sign => "sign",
            Self::Banner => "banner",
            Self::WashingLine => "washing_line",
            Self::Tree => "tree",
            Self::Kerb => "kerb",
            Self::Stairs => "stairs",
            Self::RetainingWall => "retaining_wall",
            Self::NeonSign => "neon_sign",
            Self::Billboard => "billboard",
            Self::Cable => "cable",
            Self::Kiosk => "kiosk",
            Self::FoodStall => "food_stall",
            Self::Pipe => "pipe",
            Self::Highway => "highway",
            Self::WallTower => "wall_tower",
            Self::Vending => "vending",
            Self::Vent => "vent",
            Self::Trash => "trash",
            Self::Barrier => "barrier",
            Self::Vehicle => "vehicle",
            Self::Hologram => "hologram",
            Self::Scaffold => "scaffold",
            Self::Crane => "crane",
            Self::Container => "container",
            Self::Salvage => "salvage",
        }
    }

    pub fn from_id(id: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|k| k.id() == id)
    }

    /// Whether it stands in the way: its footprint becomes `Wall` tiles where the land is
    /// hosted ([`crate::host::hosted_map`]). Retaining walls block through the drop they stand
    /// on ([`terrace::paint_drops`]); the rest are posts, low things or overhead.
    pub fn blocks(self) -> bool {
        matches!(self, Self::Fountain | Self::MarketCross | Self::Cart | Self::Kiosk | Self::FoodStall | Self::Vending | Self::Container | Self::Salvage)
    }
}

/// A prop the planner placed. Props are derived from the layout on both the authority and
/// clients, not stored per row (see `docs/ISLAND_AUTHORITY.md`).
#[derive(Clone, Debug, Serialize)]
pub struct Prop {
    pub settlement: u16,
    pub kind: PropKind,
    pub centre: V2,
    /// Along the front, and front to back: the model's footprint.
    pub width_m: f32,
    pub depth_m: f32,
    /// Unit vector the model's front (+Z in glTF) faces: toward the street or the square, down
    /// the stairs, out of a retaining wall toward the lower ground.
    pub front: V2,
    /// As [`Lot::yaw`].
    pub yaw: f32,
    /// Where the model's origin goes: the ground under it (stairs and retaining walls: the
    /// lower ground).
    pub floor_m: f32,
    /// The model (a `buildings.py` file under the client's `envs/`), chosen from
    /// `data/buildings.json` among the models of its style and kind.
    pub model_file: Option<String>,
    /// That model's height above the floor.
    pub height_m: f32,
}

impl Prop {
    pub fn corners(&self) -> [V2; 4] {
        self.rect().corners()
    }

    fn rect(&self) -> Rect {
        Rect { c: self.centre, f: self.front, hw: self.width_m * 0.5, hd: self.depth_m * 0.5 }
    }

    /// What takes room on the ground: the footprint, but a tree's trunk and ring, not its crown.
    fn base(&self) -> Rect {
        let r = self.rect();
        match self.kind {
            PropKind::Tree => Rect { hw: r.hw.min(self.width_m * 0.22), hd: r.hd.min(self.width_m * 0.22), ..r },
            _ => r,
        }
    }
}

// ------------------------------------------------------------------------------------------
// Parameters

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct SettleParams {
    pub roads: RoadParams,
    pub styles: Vec<Style>,
    pub buildings: Buildings,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct RoadParams {
    /// Routing grid (metres per cell).
    pub grid_m: f32,
    /// Grade at which a road costs twice as much per metre; above `max_grade` it costs 10×.
    pub grade_ref: f32,
    pub max_grade: f32,
    /// Cost factors per metre: forest, sand, rock (a cutting), the spirit grove.
    pub forest_cost: f32,
    pub sand_cost: f32,
    pub rock_cost: f32,
    pub grove_cost: f32,
    /// Cost factor per metre across a river, and across an existing ford.
    pub river_cost: f32,
    pub ford_cost: f32,
    /// Rivers wider than this at the crossing get a bridge instead of a ford.
    pub bridge_m: f32,
    /// Width of the blended shoulder beside a road, and the steepest cross-fall.
    pub shoulder_m: f32,
    pub crossfall: f32,
    /// Length of the moving average along a road's profile.
    pub smooth_m: f32,
    /// A road from the town to the sea when the shore is within this distance (0: none).
    pub landing_m: f32,
    /// Footpaths to cave mouths up to this long (0: none), and their width.
    pub cave_path_m: f32,
    pub path_width_m: f32,
}

/// How one kind of site is laid out. Lengths are metres in the world (a giants' style has
/// giant numbers).
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Style {
    pub site: SiteKind,
    /// `buildings.py` style of its models.
    pub buildings: String,
    /// The `buildings.py` style its models come from when that is not `buildings`: a style of
    /// its own (its own layout, ornaments and kind names) built from another style's kit.
    #[serde(default)]
    pub kit: Option<String>,
    /// Plaza length (along the main roads) and width; paved square or a green.
    pub plaza_m: [f32; 2],
    pub paved: bool,
    /// Width of the island road to this settlement, its main streets and its lanes.
    pub trunk_m: f32,
    pub street_m: f32,
    pub lane_m: f32,
    pub lane_class: RoadClass,
    /// Main streets out of the plaza, at least.
    pub radials: u32,
    /// Distance between branching lanes along a street, their length limits, and how far a
    /// lane keeps from a parallel street.
    pub lane_spacing_m: f32,
    pub lane_m_max: f32,
    pub lane_m_min: f32,
    pub lane_sep_m: f32,
    /// Chance of a lane at each branch point on each side; branching depth.
    pub branch: f32,
    pub depth: u32,
    /// How lanes steer: along contours (on slopes), round the centre, and how much they wander.
    pub contour: f32,
    pub circle: f32,
    pub wander: f32,
    /// Built-up edge as a fraction of the site radius, shrunk where water, rock or steep relief
    /// (more than `relief_m` from the centre) comes first.
    pub bound: f32,
    pub relief_m: f32,
    /// Inside this fraction of the edge, lots are `core` kind; outside, `outer` kind with
    /// `core_share` of `core`.
    pub core: f32,
    pub core_kind: LotKind,
    pub outer_kind: LotKind,
    pub core_share: f32,
    /// Gaps between neighbouring lots, in the core and outside it; set-back from the street.
    pub core_gap_m: [f32; 2],
    pub gap_m: [f32; 2],
    pub setback_m: f32,
    /// Chance of a garden behind an outer house, and its depth.
    pub garden: f32,
    pub garden_m: [f32; 2],
    /// Skirt of a levelled pad, and the most it may cut into or fill above the ground.
    pub skirt_m: f32,
    pub cut_m: f32,
    pub fill_m: f32,
    /// Floor above the street at the front.
    pub step_m: f32,
    pub landmark: Option<LotKind>,
    /// The landmark stands in the middle of the plaza, else on its edge.
    pub landmark_centre: bool,
    /// Big buildings on the plaza's edge after the landmark (or along a main street near it when
    /// the edge has no room), in order.
    pub plaza_lots: Vec<LotKind>,
    /// Chance that a lot outside the core is a workshop, and that an outskirts lot is a barn.
    pub workshop: f32,
    pub barn: f32,
    /// Space between a model's footprint and its lot's edge, on every side.
    pub margin_m: f32,
    pub well: bool,
    pub stalls: u32,
    /// Street lamps along main streets this far apart (0: none).
    pub lamp_m: f32,
    pub wall: Option<WallSpec>,
    /// Outskirts: houses along the roads up to this far beyond the edge, their gaps, and the
    /// chance and size (width, depth ranges) of fields.
    pub outskirts_m: f32,
    pub outskirt_gap_m: [f32; 2],
    pub fields: f32,
    pub field_w_m: [f32; 2],
    pub field_d_m: [f32; 2],
    /// The `buildings.py` kind on a lot kind where it is not the lot kind's own id (a
    /// steampunk landmark tower is a `clocktower`, a cyberpunk house a `block`).
    pub models: Vec<(LotKind, String)>,
    /// Terraces: height of one step (0: never terraced), and the least relief across the site
    /// that is terraced (flatter sites stay as they are). Stairs between terraces about
    /// `stair_m` apart along each drop.
    pub terrace_m: f32,
    pub terrace_relief_m: f32,
    pub stair_m: f32,
    /// Lamps along lanes this far apart (0: none).
    pub lane_lamp_m: f32,
    /// Wells in the neighbourhoods, where lanes leave the main streets away from the plaza.
    pub wells: u32,
    pub ornaments: Ornaments,
}

/// What a settlement is dressed with, and where ([`ornament`]). Chances are per candidate spot.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Ornaments {
    /// A fountain or a market cross in the plaza (None: none).
    pub centrepiece: Option<PropKind>,
    /// Benches round the plaza's edge facing in, this far apart (0: none); trees on it.
    pub bench_m: f32,
    pub plaza_trees: u32,
    /// Banners on both sides of the streets into the plaza, and inside the town's gates.
    pub banners: bool,
    /// Per house: a flower box beside the door, a planter at a front corner.
    pub flower_box: f32,
    pub planter: f32,
    /// Gardens: fenced with a gate; a tree, a washing line.
    pub fences: bool,
    pub garden_tree: f32,
    pub washing: f32,
    /// A washing line across a 2-6 m gap between neighbouring houses.
    pub washing_gap: f32,
    /// Barrels, crates and carts by inns, workshops, barns and market stalls.
    pub clutter: f32,
    /// Hanging signs at inns and workshops, signposts where streets leave the plaza.
    pub signs: bool,
    /// Kerbs along paved main streets, and paving edges round a paved plaza.
    pub kerbs: bool,
    /// Trees along the main streets this far apart (0: none).
    pub street_tree_m: f32,
    /// A neon street: signs, kiosks and food stalls along the main street with the most
    /// buildings, cables across it this far apart; billboards round the plaza.
    pub neon_street: bool,
    pub cable_m: f32,
    pub billboards: u32,
    /// Pipes along the sides of works and factories.
    pub pipes: bool,
    /// Neon streets: the `neon_street` dressing on this many of the busiest streets (0: one).
    pub neon_streets: u32,
    /// Street dressing along every street and lane edge, one spot each `street_kit_m`: a kind
    /// drawn by weight (vending machines, vents, rubbish, barriers, parked vehicles...), or
    /// nothing for the rest of the weight up to 1.
    pub street_kit: Vec<(PropKind, f32)>,
    pub street_kit_m: f32,
    /// Holograms round the square.
    pub holograms: u32,
    /// Chance of a scaffold against a building of at least 20 m.
    pub scaffold: f32,
    /// Chance of a crane in front of a building whose front looks over water within 30 m (a port).
    pub cranes: f32,
    /// Chance of a salvage pile beside each building.
    pub salvage: f32,
}

impl Default for Ornaments {
    fn default() -> Self {
        Self {
            centrepiece: None,
            bench_m: 12.0,
            plaza_trees: 1,
            banners: false,
            flower_box: 0.3,
            planter: 0.1,
            fences: true,
            garden_tree: 0.5,
            washing: 0.3,
            washing_gap: 0.2,
            clutter: 0.7,
            signs: true,
            kerbs: false,
            street_tree_m: 0.0,
            neon_street: false,
            cable_m: 0.0,
            billboards: 0,
            pipes: false,
            neon_streets: 0,
            street_kit: Vec::new(),
            street_kit_m: 10.0,
            holograms: 0,
            scaffold: 0.0,
            cranes: 0.0,
            salvage: 0.0,
        }
    }
}

impl Style {
    /// The `buildings.py` kind of the models on a lot kind.
    pub fn model_kind(&self, k: LotKind) -> Option<&str> {
        k.model()?;
        Some(self.models.iter().find(|m| m.0 == k).map_or_else(|| k.model().unwrap(), |m| m.1.as_str()))
    }
}

impl SettleParams {
    /// The `buildings.py` style whose models a settlement style uses ([`Style::kit`]).
    pub fn kit<'s>(&'s self, style: &'s str) -> &'s str {
        self.styles.iter().find(|s| s.buildings == style).and_then(|s| s.kit.as_deref()).unwrap_or(style)
    }

    /// The style of a kind of site in a `buildings.py` style, else the kind's first style.
    pub fn style_for(&self, kind: SiteKind, buildings: &str) -> Option<&Style> {
        self.styles.iter().find(|s| s.site == kind && s.buildings == buildings).or_else(|| self.styles.iter().find(|s| s.site == kind))
    }

    /// The style a site is laid out in: its own ([`crate::land::SiteSpec::style`]) or its kind's first.
    pub fn style_for_site(&self, site: &Site) -> Option<&Style> {
        match &site.style {
            Some(b) => self.styles.iter().find(|s| s.site == site.kind && &s.buildings == b),
            None => self.styles.iter().find(|s| s.site == site.kind),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct WallSpec {
    pub thickness_m: f32,
    pub height_m: f32,
    /// Distance between wall towers, and from the wall to the lane inside it.
    pub tower_m: f32,
    pub lane_offset_m: f32,
    pub gate_m: f32,
}

/// Building footprints per `buildings.py` style and kind, and of every generated model.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Buildings {
    pub kinds: Vec<Footprint>,
    #[serde(default)]
    pub models: Vec<ModelFootprint>,
}

/// One generated model: its file under the client's `envs/`, form and exact footprint.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ModelFootprint {
    pub style: String,
    pub kind: String,
    /// Size class and shape within the kind (cottage, longhouse, narrow, wide, corner...).
    pub form: String,
    pub file: String,
    /// Along the front, front to back (roof overhangs, steps and yards included), and above the
    /// floor; the model is centred on its footprint with its origin at the floor.
    pub width_m: f32,
    pub depth_m: f32,
    pub height_m: f32,
    pub foundation_m: f32,
    /// A corner building's second street front, in the model's frame (glTF +X = 1, -X = -1;
    /// 0: not a corner building). Placed with [`Lot::yaw`], the model's +X points along
    /// `(front.1, -front.0)` on the map.
    #[serde(default)]
    pub corner: i8,
    #[serde(default)]
    pub tris: u32,
    /// Share of the footprint's area that is solid at eye height ([`EYE_BAND_M`]), measured
    /// from the mesh by `buildings.py` (`eye_cells`). None: not measured.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub eye_solid: Option<f32>,
    /// What the model hides at eye height, per [`EYE_CELL_M`] square of its footprint: how much
    /// of the view through it is blocked in [`EYE_BAND_M`], looking along either of the model's
    /// axes, measured from its mesh by `buildings.py` (`eye_cells`, `eye_rle`): the number of
    /// columns, a colon, then runs of a count and a level (`a` none ... `k` all, at least that
    /// many tenths), row-major from the front row (the model's front, glTF +Z), column 0 at the
    /// model's -X. Decoded by [`ModelFootprint::eye`]; read by `host::hosted_map`. None: not
    /// measured (the height rule applies).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub eye_cells: Option<String>,
}

/// The band above a model's floor that `eye_cells` measures (metres): where a standing person's
/// eye and head are. A land whose eye height (`land::Sight::eye_m`) lies outside it uses the
/// height rule alone, since the cells say nothing about other heights.
pub const EYE_BAND_M: (f32, f32) = (1.2, 1.8);
/// The side of an `eye_cells` square (metres): finer than a tile, so every square lands on the
/// tile it lies in, whatever a lot's position and facing.
pub const EYE_CELL_M: f32 = 0.5;

/// A model's `eye_cells`, decoded.
#[derive(Clone, Debug, PartialEq)]
pub struct EyeCells {
    pub cols: usize,
    pub rows: usize,
    /// Row-major from the front row; each 0..=10, tenths of the view blocked.
    pub levels: Vec<u8>,
}

impl EyeCells {
    /// The centre of square (`col`, `row`) in the model's own frame (metres; x along glTF +X,
    /// y toward the model's back: glTF -Z, Blender +Y), the model centred on its footprint.
    pub fn centre(&self, col: usize, row: usize) -> V2 {
        ((col as f32 + 0.5 - self.cols as f32 * 0.5) * EYE_CELL_M, (row as f32 + 0.5 - self.rows as f32 * 0.5) * EYE_CELL_M)
    }
}

impl ModelFootprint {
    /// Its `eye_cells`, decoded; None when not measured or malformed.
    pub fn eye(&self) -> Option<EyeCells> {
        let (cols, runs) = self.eye_cells.as_deref()?.split_once(':')?;
        let cols: usize = cols.parse().ok().filter(|&c| c > 0)?;
        let mut levels = Vec::new();
        let mut n = 0usize;
        for ch in runs.chars() {
            match ch {
                '0'..='9' => n = n * 10 + ch as usize - '0' as usize,
                'a'..='k' if n > 0 => {
                    levels.extend(std::iter::repeat(ch as u8 - b'a').take(n));
                    n = 0;
                }
                _ => return None,
            }
        }
        (n == 0 && !levels.is_empty() && levels.len() % cols == 0).then(|| EyeCells { cols, rows: levels.len() / cols, levels })
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Footprint {
    pub style: String,
    pub kind: String,
    /// Envelope of every model of the kind, roof overhangs included: along the front, front to
    /// back, and above the floor.
    pub width_m: f32,
    pub depth_m: f32,
    pub height_m: f32,
    /// Depth of the foundation below the floor.
    pub foundation_m: f32,
}

impl Default for Buildings {
    fn default() -> Self {
        serde_json::from_str(include_str!("../data/buildings.json")).expect("data/buildings.json")
    }
}

impl Buildings {
    pub fn get(&self, style: &str, kind: LotKind) -> Option<&Footprint> {
        let id = kind.model()?;
        self.kinds.iter().find(|f| f.style == style && f.kind == id)
    }

    /// The model a lot names.
    pub fn model(&self, file: &str) -> Option<&ModelFootprint> {
        self.models.iter().find(|m| m.file == file)
    }
}

impl Default for SettleParams {
    fn default() -> Self {
        Self { roads: RoadParams::default(), styles: default_styles(), buildings: Buildings::default() }
    }
}

impl Default for RoadParams {
    fn default() -> Self {
        Self {
            grid_m: 4.0,
            grade_ref: 0.07,
            max_grade: 0.28,
            forest_cost: 1.6,
            sand_cost: 1.25,
            rock_cost: 12.0,
            grove_cost: 3.0,
            river_cost: 30.0,
            ford_cost: 2.0,
            bridge_m: 6.0,
            shoulder_m: 2.5,
            crossfall: 0.03,
            smooth_m: 16.0,
            landing_m: 600.0,
            cave_path_m: 1100.0,
            path_width_m: 1.6,
        }
    }
}

impl Default for WallSpec {
    fn default() -> Self {
        Self { thickness_m: 3.0, height_m: 5.5, tower_m: 70.0, lane_offset_m: 7.5, gate_m: 2.0 }
    }
}

impl Default for Style {
    fn default() -> Self {
        Self {
            site: SiteKind::Village,
            buildings: "fantasy".into(),
            kit: None,
            plaza_m: [24.0, 16.0],
            paved: false,
            trunk_m: 3.0,
            street_m: 3.6,
            lane_m: 2.6,
            lane_class: RoadClass::Lane,
            radials: 2,
            lane_spacing_m: 34.0,
            lane_m_max: 70.0,
            lane_m_min: 14.0,
            lane_sep_m: 18.0,
            branch: 0.5,
            depth: 1,
            contour: 0.7,
            circle: 0.4,
            wander: 0.5,
            bound: 0.95,
            relief_m: 12.0,
            core: 0.4,
            core_kind: LotKind::House,
            outer_kind: LotKind::House,
            core_share: 0.0,
            core_gap_m: [2.0, 5.0],
            gap_m: [3.0, 8.0],
            setback_m: 2.0,
            garden: 0.7,
            garden_m: [5.0, 9.0],
            skirt_m: 3.0,
            cut_m: 2.6,
            fill_m: 2.2,
            step_m: 0.1,
            landmark: Some(LotKind::Well),
            landmark_centre: true,
            plaza_lots: Vec::new(),
            workshop: 0.0,
            barn: 0.0,
            margin_m: 0.15,
            well: false,
            stalls: 0,
            lamp_m: 0.0,
            wall: None,
            outskirts_m: 70.0,
            outskirt_gap_m: [8.0, 22.0],
            fields: 0.6,
            field_w_m: [14.0, 26.0],
            field_d_m: [22.0, 40.0],
            models: Vec::new(),
            terrace_m: 0.0,
            terrace_relief_m: 7.0,
            stair_m: 34.0,
            lane_lamp_m: 0.0,
            wells: 0,
            ornaments: Ornaments::default(),
        }
    }
}

fn default_styles() -> Vec<Style> {
    let town = Style {
        site: SiteKind::Town,
        plaza_m: [62.0, 38.0],
        paved: true,
        trunk_m: 3.6,
        street_m: 5.0,
        lane_m: 3.0,
        radials: 4,
        lane_spacing_m: 36.0,
        lane_m_max: 150.0,
        lane_m_min: 16.0,
        lane_sep_m: 21.0,
        branch: 0.75,
        depth: 2,
        contour: 0.6,
        circle: 0.55,
        wander: 0.35,
        bound: 0.85,
        relief_m: 16.0,
        core: 0.55,
        core_kind: LotKind::Townhouse,
        outer_kind: LotKind::House,
        core_share: 0.3,
        core_gap_m: [0.25, 0.6],
        gap_m: [1.0, 3.5],
        setback_m: 1.0,
        garden: 0.7,
        garden_m: [6.0, 15.0],
        landmark: Some(LotKind::Chapel),
        landmark_centre: false,
        plaza_lots: vec![LotKind::Inn, LotKind::Hall],
        workshop: 0.12,
        barn: 0.3,
        well: true,
        stalls: 10,
        lamp_m: 24.0,
        wall: Some(WallSpec::default()),
        outskirts_m: 110.0,
        terrace_m: 3.0,
        lane_lamp_m: 42.0,
        wells: 2,
        ornaments: Ornaments { centrepiece: Some(PropKind::MarketCross), bench_m: 10.0, banners: true, flower_box: 0.4, planter: 0.15, garden_tree: 0.55, washing_gap: 0.35, clutter: 0.85, kerbs: true, ..Ornaments::default() },
        ..Style::default()
    };
    let village = Style {
        site: SiteKind::Village,
        branch: 0.7,
        plaza_lots: vec![LotKind::Chapel, LotKind::Inn],
        workshop: 0.1,
        barn: 0.35,
        terrace_m: 3.0,
        terrace_relief_m: 6.0,
        ornaments: Ornaments { plaza_trees: 2, garden_tree: 0.6, washing: 0.4, ..Ornaments::default() },
        ..Style::default()
    };
    let giants = Style {
        site: SiteKind::Giants,
        buildings: "giant".into(),
        plaza_m: [70.0, 48.0],
        paved: true,
        trunk_m: 6.0,
        street_m: 12.0,
        lane_m: 9.0,
        radials: 4,
        lane_spacing_m: 48.0,
        lane_m_max: 220.0,
        lane_m_min: 30.0,
        lane_sep_m: 36.0,
        branch: 0.75,
        depth: 2,
        contour: 0.7,
        circle: 0.35,
        wander: 0.12,
        bound: 0.95,
        relief_m: 40.0,
        core: 0.5,
        core_gap_m: [3.0, 6.0],
        gap_m: [5.0, 12.0],
        setback_m: 3.0,
        garden: 0.5,
        garden_m: [12.0, 22.0],
        skirt_m: 7.0,
        cut_m: 9.0,
        fill_m: 6.0,
        step_m: 0.3,
        landmark: Some(LotKind::Tower),
        landmark_centre: false,
        plaza_lots: vec![LotKind::Hall],
        margin_m: 0.4,
        well: true,
        lamp_m: 60.0,
        outskirts_m: 90.0,
        outskirt_gap_m: [20.0, 50.0],
        fields: 0.4,
        field_w_m: [36.0, 60.0],
        field_d_m: [50.0, 80.0],
        ornaments: Ornaments { bench_m: 32.0, flower_box: 0.0, planter: 0.15, washing_gap: 0.0, clutter: 0.5, ..Ornaments::default() },
        ..Style::default()
    };
    let small = Style {
        site: SiteKind::SmallFolk,
        buildings: "small".into(),
        plaza_m: [10.0, 7.0],
        paved: false,
        trunk_m: 1.2,
        street_m: 1.2,
        lane_m: 0.9,
        lane_class: RoadClass::Path,
        radials: 3,
        lane_spacing_m: 9.0,
        lane_m_max: 30.0,
        lane_m_min: 4.0,
        lane_sep_m: 5.5,
        branch: 0.7,
        depth: 2,
        contour: 0.8,
        circle: 0.5,
        wander: 0.9,
        bound: 1.0,
        relief_m: 6.0,
        core: 1.0,
        core_gap_m: [0.4, 1.4],
        gap_m: [0.6, 2.0],
        setback_m: 0.4,
        garden: 0.5,
        garden_m: [1.5, 2.5],
        skirt_m: 1.2,
        cut_m: 1.4,
        fill_m: 0.7,
        step_m: 0.04,
        landmark: Some(LotKind::Tower),
        landmark_centre: true,
        plaza_lots: vec![LotKind::Hall],
        margin_m: 0.05,
        outskirts_m: 22.0,
        outskirt_gap_m: [2.0, 5.0],
        fields: 0.5,
        field_w_m: [3.0, 5.0],
        field_d_m: [4.0, 7.0],
        ornaments: Ornaments { bench_m: 3.5, flower_box: 0.4, planter: 0.2, garden_tree: 0.4, washing: 0.2, washing_gap: 0.0, clutter: 0.3, signs: false, ..Ornaments::default() },
        ..Style::default()
    };
    // A hillside town of brick and iron: a clock tower in the middle of its square, the
    // exchange, a pub and the market arcade round it, works and factories on the outskirts,
    // terraces with stairs where the hill is steep.
    let steampunk = Style {
        site: SiteKind::Town,
        buildings: "steampunk".into(),
        plaza_m: [52.0, 36.0],
        paved: true,
        trunk_m: 3.6,
        street_m: 5.0,
        lane_m: 3.0,
        radials: 4,
        lane_spacing_m: 32.0,
        lane_m_max: 130.0,
        lane_m_min: 14.0,
        lane_sep_m: 19.0,
        branch: 0.8,
        depth: 2,
        contour: 0.9,
        circle: 0.3,
        wander: 0.25,
        bound: 0.9,
        relief_m: 45.0,
        core: 0.6,
        core_kind: LotKind::Townhouse,
        outer_kind: LotKind::House,
        core_share: 0.4,
        core_gap_m: [0.2, 0.5],
        gap_m: [0.8, 3.0],
        setback_m: 1.2,
        garden: 0.45,
        garden_m: [5.0, 11.0],
        skirt_m: 1.2,
        // A house may back into the terrace above (its back wall holds the drop).
        cut_m: 3.5,
        step_m: 0.15,
        landmark: Some(LotKind::Tower),
        landmark_centre: true,
        plaza_lots: vec![LotKind::Inn, LotKind::Hall, LotKind::Chapel],
        models: vec![(LotKind::Tower, "clocktower".into()), (LotKind::Chapel, "arcade".into()), (LotKind::Townhouse, "house".into()), (LotKind::Workshop, "works".into()), (LotKind::Barn, "factory".into())],
        workshop: 0.14,
        barn: 0.3,
        lamp_m: 22.0,
        outskirts_m: 80.0,
        fields: 0.35,
        terrace_m: 3.0,
        terrace_relief_m: 6.0,
        stair_m: 30.0,
        lane_lamp_m: 36.0,
        wells: 0,
        ornaments: Ornaments { centrepiece: Some(PropKind::Fountain), bench_m: 9.0, plaza_trees: 2, banners: true, flower_box: 0.3, planter: 0.2, garden_tree: 0.4, washing_gap: 0.4, clutter: 0.9, kerbs: true, street_tree_m: 18.0, pipes: true, ..Ornaments::default() },
        ..Style::default()
    };
    // A dense harbour town of concrete blocks: a megatower on its square, the food court and a
    // tower round it, a neon street of signs, stalls and cables, garages on the outskirts.
    let cyberpunk = Style {
        site: SiteKind::Town,
        buildings: "cyberpunk".into(),
        plaza_m: [40.0, 26.0],
        paved: true,
        trunk_m: 4.0,
        street_m: 6.0,
        lane_m: 3.4,
        radials: 4,
        lane_spacing_m: 30.0,
        lane_m_max: 120.0,
        lane_m_min: 14.0,
        lane_sep_m: 21.0,
        branch: 0.85,
        depth: 2,
        contour: 0.4,
        circle: 0.2,
        wander: 0.12,
        bound: 0.9,
        relief_m: 26.0,
        core: 0.7,
        core_kind: LotKind::Townhouse,
        outer_kind: LotKind::House,
        core_share: 0.6,
        core_gap_m: [0.1, 0.4],
        gap_m: [0.6, 2.0],
        setback_m: 0.8,
        garden: 0.12,
        garden_m: [4.0, 8.0],
        skirt_m: 1.2,
        landmark: Some(LotKind::Chapel),
        landmark_centre: false,
        plaza_lots: vec![LotKind::Inn, LotKind::Hall],
        models: vec![
            (LotKind::Chapel, "landmark".into()),
            (LotKind::Inn, "market".into()),
            (LotKind::Hall, "tower".into()),
            (LotKind::Townhouse, "block".into()),
            (LotKind::House, "block".into()),
            (LotKind::Barn, "workshop".into()),
            (LotKind::MarketStall, "food_stall".into()),
        ],
        workshop: 0.2,
        barn: 0.3,
        stalls: 6,
        lamp_m: 18.0,
        outskirts_m: 70.0,
        fields: 0.15,
        terrace_m: 3.0,
        terrace_relief_m: 6.0,
        stair_m: 30.0,
        lane_lamp_m: 30.0,
        ornaments: Ornaments { centrepiece: Some(PropKind::MarketCross), bench_m: 12.0, plaza_trees: 2, banners: true, flower_box: 0.1, planter: 0.3, garden_tree: 0.3, washing: 0.2, washing_gap: 0.3, clutter: 0.9, kerbs: true, neon_street: true, cable_m: 12.0, billboards: 3, ..Ornaments::default() },
        ..Style::default()
    };
    // The city's wards ([`MetroParams`]) and the settlements of the land round it, all from
    // the cyberpunk kit. Their layout comes from the city planner; these set their ornaments,
    // pads and the kit's kind names. They follow the styles above, so a land without a city
    // lays out as before.
    let m = |pairs: &[(LotKind, &str)]| pairs.iter().map(|(k, v)| (*k, v.to_string())).collect::<Vec<_>>();
    // Street dressing shared by the city's districts, by weight per spot.
    let busy = vec![(PropKind::Vending, 0.12), (PropKind::Vent, 0.08), (PropKind::Trash, 0.14), (PropKind::Vehicle, 0.2), (PropKind::Barrier, 0.03)];
    let ward = Style {
        site: SiteKind::Town,
        buildings: "metro".into(),
        kit: Some("megacity".into()),
        terrace_m: 0.0,
        wall: None,
        well: false,
        stalls: 0,
        skirt_m: 1.2,
        margin_m: 0.15,
        landmark: None,
        models: m(&[(LotKind::Chapel, "neon_tower"), (LotKind::Inn, "market"), (LotKind::Hall, "block"), (LotKind::Townhouse, "block"), (LotKind::House, "block"), (LotKind::Barn, "workshop"), (LotKind::MarketStall, "food_stall")]),
        ornaments: Ornaments {
            centrepiece: Some(PropKind::Fountain),
            bench_m: 14.0,
            plaza_trees: 2,
            banners: false,
            flower_box: 0.0,
            planter: 0.2,
            fences: false,
            garden_tree: 0.0,
            washing: 0.0,
            washing_gap: 0.0,
            clutter: 0.5,
            signs: true,
            kerbs: false,
            street_tree_m: 0.0,
            neon_street: true,
            cable_m: 14.0,
            billboards: 4,
            pipes: false,
            street_kit: busy.clone(),
            holograms: 1,
            scaffold: 0.06,
            ..Ornaments::default()
        },
        ..cyberpunk.clone()
    };
    // The corporate core: megatowers and their plazas, an arcology in the middle.
    let corporate = Style {
        buildings: "corporate".into(),
        landmark: Some(LotKind::Tower),
        models: m(&[(LotKind::Tower, "arcology"), (LotKind::Hall, "megatower"), (LotKind::Chapel, "megatower"), (LotKind::Townhouse, "block"), (LotKind::House, "block"), (LotKind::Inn, "neon_tower"), (LotKind::MarketStall, "food_stall")]),
        ornaments: Ornaments { neon_street: false, billboards: 6, holograms: 4, cable_m: 0.0, clutter: 0.2, street_kit: vec![(PropKind::Vending, 0.1), (PropKind::Barrier, 0.06), (PropKind::Vehicle, 0.2)], scaffold: 0.0, ..ward.ornaments.clone() },
        ..ward.clone()
    };
    // Entertainment: neon on every street, screens and clubs.
    let neon = Style {
        buildings: "neon".into(),
        models: m(&[(LotKind::Inn, "neon_tower"), (LotKind::Hall, "neon_tower"), (LotKind::Chapel, "neon_tower"), (LotKind::Townhouse, "block"), (LotKind::House, "block"), (LotKind::MarketStall, "food_stall")]),
        ornaments: Ornaments { neon_streets: 6, cable_m: 9.0, billboards: 6, holograms: 3, street_kit: vec![(PropKind::Vending, 0.18), (PropKind::Trash, 0.16), (PropKind::Vent, 0.1), (PropKind::Vehicle, 0.12)], ..ward.ornaments.clone() },
        ..ward.clone()
    };
    // Residential megablocks.
    let megablock = Style {
        buildings: "megablock".into(),
        models: m(&[(LotKind::Townhouse, "megablock"), (LotKind::Hall, "megablock"), (LotKind::House, "block"), (LotKind::Inn, "market"), (LotKind::Workshop, "workshop"), (LotKind::MarketStall, "food_stall")]),
        ornaments: Ornaments { billboards: 2, holograms: 1, washing_gap: 0.4, street_kit: vec![(PropKind::Trash, 0.2), (PropKind::Vending, 0.1), (PropKind::Vehicle, 0.22), (PropKind::Vent, 0.06)], scaffold: 0.1, ..ward.ornaments.clone() },
        ..ward.clone()
    };
    // The market: food courts and stalls on every street.
    let market = Style {
        buildings: "market".into(),
        models: m(&[(LotKind::Inn, "market"), (LotKind::Hall, "market"), (LotKind::Townhouse, "old_block"), (LotKind::House, "block"), (LotKind::Workshop, "workshop"), (LotKind::MarketStall, "food_stall")]),
        ornaments: Ornaments { neon_streets: 4, centrepiece: None, clutter: 1.0, cable_m: 8.0, street_kit: vec![(PropKind::Trash, 0.2), (PropKind::Vending, 0.12), (PropKind::Vehicle, 0.1)], ..ward.ornaments.clone() },
        ..ward.clone()
    };
    // The old town: older brick and plaster blocks on irregular streets.
    let oldtown = Style {
        buildings: "oldtown".into(),
        models: m(&[(LotKind::Townhouse, "old_block"), (LotKind::House, "old_block"), (LotKind::Inn, "old_block"), (LotKind::Hall, "old_block"), (LotKind::Chapel, "old_block"), (LotKind::Workshop, "workshop"), (LotKind::MarketStall, "food_stall")]),
        ornaments: Ornaments { billboards: 1, holograms: 0, washing_gap: 0.5, cable_m: 10.0, street_kit: vec![(PropKind::Trash, 0.16), (PropKind::Vehicle, 0.1), (PropKind::Vending, 0.06)], ..ward.ornaments.clone() },
        ..ward.clone()
    };
    // Vertical slums against the wall: shanties a few metres deep, stacked; containers.
    let slum = Style {
        buildings: "slum".into(),
        models: m(&[(LotKind::House, "shanty"), (LotKind::Townhouse, "shanty"), (LotKind::Workshop, "container"), (LotKind::MarketStall, "food_stall"), (LotKind::Inn, "food_stall"), (LotKind::Lamp, "lamp")]),
        ornaments: Ornaments { centrepiece: None, bench_m: 0.0, plaza_trees: 0, washing: 0.5, washing_gap: 0.6, clutter: 0.9, billboards: 1, cable_m: 6.0, street_kit: vec![(PropKind::Trash, 0.3), (PropKind::Barrier, 0.04), (PropKind::Vehicle, 0.04)], scaffold: 0.0, salvage: 0.08, ..ward.ornaments.clone() },
        ..ward.clone()
    };
    // Industry and the port: warehouses, containers, cranes on the water.
    let works = Style {
        buildings: "works".into(),
        models: m(&[(LotKind::House, "block"), (LotKind::Workshop, "warehouse"), (LotKind::Barn, "container"), (LotKind::Inn, "market"), (LotKind::Hall, "warehouse"), (LotKind::MarketStall, "food_stall")]),
        ornaments: Ornaments { centrepiece: None, neon_street: false, billboards: 2, clutter: 1.0, pipes: true, street_kit: vec![(PropKind::Vehicle, 0.3), (PropKind::Barrier, 0.1), (PropKind::Trash, 0.1)], cranes: 0.5, ..ward.ornaments.clone() },
        ..ward.clone()
    };
    let wastes = |buildings: &str, models: Vec<(LotKind, String)>| Style {
        site: SiteKind::Village,
        buildings: buildings.into(),
        kit: Some("megacity".into()),
        paved: false,
        models,
        garden: 0.0,
        fields: 0.0,
        barn: 0.0,
        terrace_m: 0.0,
        ornaments: Ornaments { fences: true, garden_tree: 0.0, flower_box: 0.0, washing: 0.3, washing_gap: 0.3, clutter: 0.9, signs: true, street_kit: vec![(PropKind::Vehicle, 0.15), (PropKind::Trash, 0.1)], street_kit_m: 14.0, salvage: 0.3, ..Ornaments::default() },
        ..Style::default()
    };
    let outpost = Style { workshop: 0.25, fields: 0.2, landmark: None, ..wastes("outpost", m(&[(LotKind::House, "container"), (LotKind::Townhouse, "block"), (LotKind::Workshop, "workshop"), (LotKind::Inn, "market"), (LotKind::Hall, "block"), (LotKind::MarketStall, "food_stall")])) };
    let salvage = Style {
        plaza_m: [14.0, 10.0],
        landmark: None,
        lane_m: 2.4,
        workshop: 0.4,
        outskirts_m: 20.0,
        ..wastes("salvage", m(&[(LotKind::House, "shanty"), (LotKind::Workshop, "container"), (LotKind::Chapel, "food_stall"), (LotKind::Inn, "food_stall"), (LotKind::MarketStall, "food_stall")]))
    };
    let ruin = Style { landmark: None, workshop: 0.3, ..wastes("ruin", m(&[(LotKind::House, "ruin"), (LotKind::Townhouse, "ruin"), (LotKind::Workshop, "ruin")])) };
    // A hamlet: a few farmhouses round a small green, barns and fields along its track, from
    // the village kit (docs/SEEDED_LIVES.md).
    let hamlet = Style {
        site: SiteKind::Village,
        buildings: "hamlet".into(),
        kit: Some("fantasy".into()),
        plaza_m: [12.0, 9.0],
        trunk_m: 2.6,
        street_m: 2.8,
        lane_m: 2.2,
        radials: 1,
        lane_spacing_m: 30.0,
        lane_m_max: 40.0,
        branch: 0.3,
        depth: 1,
        bound: 0.95,
        relief_m: 8.0,
        gap_m: [5.0, 12.0],
        garden: 0.8,
        barn: 0.6,
        workshop: 0.1,
        outskirts_m: 45.0,
        outskirt_gap_m: [10.0, 26.0],
        fields: 0.8,
        ornaments: Ornaments { garden_tree: 0.6, washing: 0.4, ..Ornaments::default() },
        ..Style::default()
    };
    vec![town, village, giants, small, steampunk, cyberpunk, ward, corporate, neon, megablock, market, oldtown, slum, works, outpost, salvage, ruin, hamlet]
}

// ------------------------------------------------------------------------------------------
// Geometry

#[inline]
fn add(a: V2, b: V2) -> V2 {
    (a.0 + b.0, a.1 + b.1)
}
#[inline]
fn sub(a: V2, b: V2) -> V2 {
    (a.0 - b.0, a.1 - b.1)
}
#[inline]
fn mul(a: V2, k: f32) -> V2 {
    (a.0 * k, a.1 * k)
}
#[inline]
fn dot(a: V2, b: V2) -> f32 {
    a.0 * b.0 + a.1 * b.1
}
#[inline]
fn cross(a: V2, b: V2) -> f32 {
    a.0 * b.1 - a.1 * b.0
}
#[inline]
fn len(a: V2) -> f32 {
    a.0.d_hypot(a.1)
}
#[inline]
fn dist(a: V2, b: V2) -> f32 {
    len(sub(a, b))
}
#[inline]
fn norm(a: V2) -> V2 {
    let l = len(a).max(1e-6);
    (a.0 / l, a.1 / l)
}
/// A quarter turn: to the left of travel on the map (x east, y south) when seen from above.
#[inline]
fn perp(a: V2) -> V2 {
    (-a.1, a.0)
}
fn rot(a: V2, t: f32) -> V2 {
    let (s, c) = t.d_sin_cos();
    (a.0 * c - a.1 * s, a.0 * s + a.1 * c)
}
/// Yaw that turns +Z (glTF front) onto `front` in the game's frame (x, z) = (land x, land y).
fn yaw_of(front: V2) -> f32 {
    front.0.d_atan2(front.1)
}

/// Distance to segment ab, position along it (0..1) and signed offset (positive on perp(b - a)).
#[inline]
fn seg_near(p: V2, a: V2, b: V2) -> (f32, f32, f32) {
    let d = sub(b, a);
    let l2 = dot(d, d).max(1e-9);
    let u = (dot(sub(p, a), d) / l2).clamp(0.0, 1.0);
    let q = add(a, mul(d, u));
    let lat = dot(sub(p, a), perp(d)) / l2.sqrt();
    (dist(p, q), u, lat)
}

fn seg_intersect(a: V2, b: V2, c: V2, d: V2) -> Option<(f32, f32)> {
    let r = sub(b, a);
    let s = sub(d, c);
    let den = cross(r, s);
    if den.abs() < 1e-9 {
        return None;
    }
    let t = cross(sub(c, a), s) / den;
    let u = cross(sub(c, a), r) / den;
    ((0.0..=1.0).contains(&t) && (0.0..=1.0).contains(&u)).then_some((t, u))
}

fn cumlen(p: &[V2]) -> Vec<f32> {
    let mut out = Vec::with_capacity(p.len());
    let mut s = 0.0;
    for i in 0..p.len() {
        if i > 0 {
            s += dist(p[i], p[i - 1]);
        }
        out.push(s);
    }
    out
}

/// Point and unit tangent at arc length `s`.
fn at_s(p: &[V2], cl: &[f32], s: f32) -> (V2, V2) {
    if p.len() < 2 {
        return (p[0], (1.0, 0.0));
    }
    let s = s.clamp(0.0, cl[cl.len() - 1]);
    let i = match cl.binary_search_by(|v| v.total_cmp(&s)) {
        Ok(i) => i.min(p.len() - 2),
        Err(i) => i.saturating_sub(1).min(p.len() - 2),
    };
    let seg = (cl[i + 1] - cl[i]).max(1e-6);
    let t = ((s - cl[i]) / seg).clamp(0.0, 1.0);
    (add(p[i], mul(sub(p[i + 1], p[i]), t)), norm(sub(p[i + 1], p[i])))
}

fn resample(p: &[V2], step: f32) -> Vec<V2> {
    if p.len() < 2 {
        return p.to_vec();
    }
    let cl = cumlen(p);
    let total = cl[cl.len() - 1];
    let n = (total / step).ceil().max(1.0) as usize;
    (0..=n).map(|i| at_s(p, &cl, total * i as f32 / n as f32).0).collect()
}

fn chaikin(p: &[V2]) -> Vec<V2> {
    if p.len() < 3 {
        return p.to_vec();
    }
    let mut out = vec![p[0]];
    for w in p.windows(2) {
        out.push(add(mul(w[0], 0.75), mul(w[1], 0.25)));
        out.push(add(mul(w[0], 0.25), mul(w[1], 0.75)));
    }
    out.push(p[p.len() - 1]);
    out
}

fn rdp(p: &[V2], eps: f32) -> Vec<V2> {
    if p.len() < 3 {
        return p.to_vec();
    }
    let mut keep = vec![false; p.len()];
    keep[0] = true;
    keep[p.len() - 1] = true;
    let mut stack = vec![(0, p.len() - 1)];
    while let Some((a, b)) = stack.pop() {
        let mut best = (0.0, 0);
        for i in a + 1..b {
            let d = seg_near(p[i], p[a], p[b]).0;
            if d > best.0 {
                best = (d, i);
            }
        }
        if best.0 > eps {
            keep[best.1] = true;
            stack.push((a, best.1));
            stack.push((best.1, b));
        }
    }
    p.iter().zip(keep).filter(|(_, k)| *k).map(|(q, _)| *q).collect()
}

/// Nearest point on a polyline: (distance, segment, u, point).
fn nearest_on(p: &[V2], q: V2) -> (f32, usize, f32, V2) {
    let mut best = (f32::MAX, 0, 0.0, q);
    for i in 0..p.len().saturating_sub(1) {
        let (d, u, _) = seg_near(q, p[i], p[i + 1]);
        if d < best.0 {
            best = (d, i, u, add(p[i], mul(sub(p[i + 1], p[i]), u)));
        }
    }
    best
}

pub(crate) fn poly_contains(poly: &[V2], p: V2) -> bool {
    let mut inside = false;
    let n = poly.len();
    let mut j = n - 1;
    for i in 0..n {
        let (a, b) = (poly[i], poly[j]);
        if (a.1 > p.1) != (b.1 > p.1) && p.0 < (b.0 - a.0) * (p.1 - a.1) / (b.1 - a.1) + a.0 {
            inside = !inside;
        }
        j = i;
    }
    inside
}

/// Distance outside a closed polygon (0 inside).
pub(crate) fn poly_outside(poly: &[V2], p: V2) -> f32 {
    if poly_contains(poly, p) {
        return 0.0;
    }
    let n = poly.len();
    (0..n).map(|i| seg_near(p, poly[i], poly[(i + 1) % n]).0).fold(f32::MAX, f32::min)
}

/// An oriented rectangle: centre, unit front, half width (across the front) and half depth.
#[derive(Clone, Copy, Debug)]
pub(crate) struct Rect {
    c: V2,
    f: V2,
    hw: f32,
    hd: f32,
}

impl Rect {
    fn u(&self) -> V2 {
        perp(self.f)
    }
    fn corners(&self) -> [V2; 4] {
        let (u, f) = (mul(self.u(), self.hw), mul(self.f, self.hd));
        [add(self.c, add(f, mul(u, -1.0))), add(self.c, add(f, u)), add(self.c, sub(u, f)), sub(self.c, add(f, u))]
    }
    fn local(&self, p: V2) -> V2 {
        let d = sub(p, self.c);
        (dot(d, self.u()), dot(d, self.f))
    }
    #[inline]
    fn outside(&self, p: V2) -> f32 {
        let (a, b) = self.local(p);
        let (dx, dy) = ((a.abs() - self.hw).max(0.0), (b.abs() - self.hd).max(0.0));
        dx.d_hypot(dy)
    }
    fn overlaps(&self, o: &Rect) -> bool {
        for axis in [self.u(), self.f, o.u(), o.f] {
            let pr = |r: &Rect| {
                let c = dot(r.c, axis);
                let e = r.hw * dot(r.u(), axis).abs() + r.hd * dot(r.f, axis).abs();
                (c - e, c + e)
            };
            let (a, b) = (pr(self), pr(o));
            if a.1 < b.0 || b.1 < a.0 {
                return false;
            }
        }
        true
    }
    /// Separation between two rectangles (0 when they overlap).
    fn gap(&self, o: &Rect) -> f32 {
        if self.overlaps(o) {
            return 0.0;
        }
        let a = self.corners().iter().map(|p| o.outside(*p)).fold(f32::MAX, f32::min);
        let b = o.corners().iter().map(|p| self.outside(*p)).fold(f32::MAX, f32::min);
        a.min(b)
    }
    /// Distance from the rectangle to segment ab (0 when they touch).
    fn seg_dist(&self, a: V2, b: V2) -> f32 {
        let (la, lb) = (self.local(a), self.local(b));
        // Clip the segment to the box (Liang-Barsky): any part inside means they touch.
        let (mut t0, mut t1) = (0.0f32, 1.0f32);
        let d = sub(lb, la);
        let mut hit = true;
        for (p, q) in [(-d.0, la.0 + self.hw), (d.0, self.hw - la.0), (-d.1, la.1 + self.hd), (d.1, self.hd - la.1)] {
            if p.abs() < 1e-9 {
                if q < 0.0 {
                    hit = false;
                    break;
                }
            } else {
                let r = q / p;
                if p < 0.0 {
                    t0 = t0.max(r);
                } else {
                    t1 = t1.min(r);
                }
                if t0 > t1 {
                    hit = false;
                    break;
                }
            }
        }
        if hit {
            return 0.0;
        }
        let mut m = self.outside(a).min(self.outside(b));
        for c in self.corners() {
            m = m.min(seg_near(c, a, b).0);
        }
        m
    }
    fn bbox(&self, pad: f32) -> (V2, V2) {
        let cs = self.corners();
        let lo = cs.iter().fold((f32::MAX, f32::MAX), |m, p| (m.0.min(p.0), m.1.min(p.1)));
        let hi = cs.iter().fold((f32::MIN, f32::MIN), |m, p| (m.0.max(p.0), m.1.max(p.1)));
        ((lo.0 - pad, lo.1 - pad), (hi.0 + pad, hi.1 + pad))
    }
}

struct Rng(u64);

impl Rng {
    fn f(&mut self) -> f32 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut h = self.0;
        h ^= h >> 30;
        h = h.wrapping_mul(0xBF58_476D_1CE4_E5B9);
        h ^= h >> 27;
        h = h.wrapping_mul(0x94D0_49BB_1331_11EB);
        ((h ^ (h >> 31)) >> 40) as f32 / (1u64 << 24) as f32
    }
    fn range(&mut self, r: [f32; 2]) -> f32 {
        lerp(r[0], r[1], self.f())
    }
}

/// A coarse bucket grid over the map, for overlap queries.
struct Buckets {
    cell: f32,
    n: i32,
    v: Vec<Vec<u32>>,
}

impl Buckets {
    fn new(size: f32, cell: f32) -> Self {
        let n = (size / cell).ceil() as i32 + 1;
        Self { cell, n, v: vec![Vec::new(); (n * n) as usize] }
    }
    fn range(&self, lo: V2, hi: V2) -> impl Iterator<Item = usize> + '_ {
        let c = |v: f32| ((v / self.cell).floor() as i32).clamp(0, self.n - 1);
        let (x0, x1, y0, y1) = (c(lo.0), c(hi.0), c(lo.1), c(hi.1));
        (y0..=y1).flat_map(move |y| (x0..=x1).map(move |x| (y * self.n + x) as usize))
    }
    fn insert(&mut self, lo: V2, hi: V2, id: u32) {
        let cells: Vec<usize> = self.range(lo, hi).collect();
        for k in cells {
            self.v[k].push(id);
        }
    }
    fn query(&self, lo: V2, hi: V2, out: &mut Vec<u32>) {
        out.clear();
        for k in self.range(lo, hi) {
            out.extend_from_slice(&self.v[k]);
        }
        out.sort_unstable();
        out.dedup();
    }
}

// ------------------------------------------------------------------------------------------
// Height modifications: graded roads and levelled pads

#[derive(Clone, Debug)]
struct Seg {
    road: u32,
    a: V2,
    b: V2,
    ha: f32,
    hb: f32,
    hw: f32,
    fade: f32,
    cross: f32,
}

#[derive(Clone, Debug)]
pub(crate) enum Shape {
    Rect(Rect),
    Poly(Vec<V2>),
}

#[derive(Clone, Debug)]
pub(crate) struct Pad {
    shape: Shape,
    floor: f32,
    skirt: f32,
    /// Within this distance of the pad, other pads' skirts give way, so every pad stays level.
    gate: f32,
    /// A stair's pad rises: from `floor` at its front edge, by `.1` metres over its depth, in
    /// the direction opposite its front `.0`.
    rise: Option<(V2, f32)>,
}

impl Pad {
    #[inline]
    fn outside(&self, p: V2) -> f32 {
        match &self.shape {
            Shape::Rect(r) => r.outside(p),
            Shape::Poly(q) => poly_outside(q, p),
        }
    }

    #[inline]
    fn floor_at(&self, p: V2) -> f32 {
        match (&self.shape, self.rise) {
            (Shape::Rect(r), Some((front, rise))) => {
                let along = dot(sub(p, r.c), front);
                self.floor + rise * ((r.hd - along) / (2.0 * r.hd)).clamp(0.0, 1.0)
            }
            _ => self.floor,
        }
    }
}

/// Road and pad shaping applied on top of the natural ground, bucketed on a coarse grid.
#[derive(Clone, Debug, Default)]
pub(crate) struct Mods {
    cell: f32,
    n: usize,
    seg_at: Vec<u32>,
    seg_ids: Vec<u32>,
    pad_at: Vec<u32>,
    pad_ids: Vec<u32>,
    segs: Vec<Seg>,
    pads: Vec<Pad>,
    /// Terraced settlements' ground, applied before roads and pads.
    pub(crate) terr: Vec<Terrace>,
    /// Planned settlements' ground ([`plan::Ground`]), applied first.
    ground: Vec<plan::Ground>,
}

const MOD_CELL: f32 = 16.0;
/// Softness (metres) of the soft-minimum that picks a road's nearest segment.
const SOFT: f32 = 0.3;

fn csr(n: usize, cell: f32, boxes: &[(V2, V2)]) -> (Vec<u32>, Vec<u32>) {
    let c = |v: f32| ((v / cell).floor() as isize).clamp(0, n as isize - 1) as usize;
    let mut count = vec![0u32; n * n + 1];
    for (lo, hi) in boxes {
        for j in c(lo.1)..=c(hi.1) {
            for i in c(lo.0)..=c(hi.0) {
                count[j * n + i + 1] += 1;
            }
        }
    }
    for k in 1..count.len() {
        count[k] += count[k - 1];
    }
    let mut fill = count.clone();
    let mut ids = vec![0u32; *count.last().unwrap() as usize];
    for (id, (lo, hi)) in boxes.iter().enumerate() {
        for j in c(lo.1)..=c(hi.1) {
            for i in c(lo.0)..=c(hi.0) {
                let k = j * n + i;
                ids[fill[k] as usize] = id as u32;
                fill[k] += 1;
            }
        }
    }
    (count, ids)
}

impl Mods {
    fn build(size: u32, segs: Vec<Seg>, pads: Vec<Pad>, terr: Vec<Terrace>, ground: Vec<plan::Ground>) -> Self {
        let cell = MOD_CELL;
        let n = (size as f32 / cell).ceil() as usize + 1;
        let sb: Vec<(V2, V2)> = segs
            .iter()
            .map(|s| {
                // Past the shoulder by enough that every segment that matters to a road's
                // soft-minimum is in the cell's list.
                let r = s.hw + s.fade + 12.0 * SOFT;
                ((s.a.0.min(s.b.0) - r, s.a.1.min(s.b.1) - r), (s.a.0.max(s.b.0) + r, s.a.1.max(s.b.1) + r))
            })
            .collect();
        let pb: Vec<(V2, V2)> = pads
            .iter()
            .map(|p| {
                let r = p.skirt.max(p.gate);
                match &p.shape {
                    Shape::Rect(rc) => rc.bbox(r),
                    Shape::Poly(q) => {
                        let lo = q.iter().fold((f32::MAX, f32::MAX), |m, v| (m.0.min(v.0), m.1.min(v.1)));
                        let hi = q.iter().fold((f32::MIN, f32::MIN), |m, v| (m.0.max(v.0), m.1.max(v.1)));
                        ((lo.0 - r, lo.1 - r), (hi.0 + r, hi.1 + r))
                    }
                }
            })
            .collect();
        let (seg_at, seg_ids) = csr(n, cell, &sb);
        let (pad_at, pad_ids) = csr(n, cell, &pb);
        Self { cell, n, seg_at, seg_ids, pad_at, pad_ids, segs, pads, terr, ground }
    }

    /// Shape `h`, the natural ground at (x, y), where `sd` is the signed distance to water.
    #[inline]
    pub(crate) fn apply(&self, x: f32, y: f32, h: f32, sd: f32) -> f32 {
        if self.n == 0 {
            return h;
        }
        let (i, j) = ((x / self.cell).floor() as isize, (y / self.cell).floor() as isize);
        if i < 0 || j < 0 || i >= self.n as isize || j >= self.n as isize {
            return h;
        }
        let k = j as usize * self.n + i as usize;
        // A planned settlement's levels and drops, whatever the water's distance (a quay stands
        // straight out of the sea); roads and pads apply over them.
        let h = if self.ground.is_empty() { h } else { self.ground.iter().fold(h, |t, g| g.apply((x, y), t, sd)) };
        let (s0, s1) = (self.seg_at[k] as usize, self.seg_at[k + 1] as usize);
        let (p0, p1) = (self.pad_at[k] as usize, self.pad_at[k + 1] as usize);
        if s0 == s1 && p0 == p1 && self.terr.is_empty() {
            return h;
        }
        // Shaping fades out at the water's edge, so banks and beds keep following the water.
        let wf = smoothstep(0.5, 2.5, sd);
        if wf <= 0.0 {
            return h;
        }
        let p = (x, y);
        let mut t = h;
        // Terraces keep off banks altogether: `Land::height` lifts any ground lowered below the
        // water within 6.5 m of it, and a terrace must not lean on that.
        let wt = smoothstep(6.5, 14.0, sd);
        for z in &self.terr {
            t = z.apply(p, t, wt);
        }
        if s0 == s1 && p0 == p1 {
            return t;
        }
        // Each road gives one surface: a soft-minimum over its own segments, so on the centre
        // line it is the road's profile and between segments it stays continuous. Roads apply
        // in order, each blended in over its shoulder.
        let ids = &self.seg_ids[s0..s1];
        let mut i = 0;
        while i < ids.len() {
            let road = self.segs[ids[i] as usize].road;
            let mut j = i;
            let mut near = [(0f32, 0f32); 64];
            let mut n = 0;
            let mut dmin = f32::MAX;
            let mut first = &self.segs[ids[i] as usize];
            while j < ids.len() && self.segs[ids[j] as usize].road == road {
                let s = &self.segs[ids[j] as usize];
                let (d, u, lat) = seg_near(p, s.a, s.b);
                if d < s.hw + s.fade + 12.0 * SOFT && n < near.len() {
                    near[n] = (d, lerp(s.ha, s.hb, u) + s.cross * lat.clamp(-s.hw, s.hw));
                    n += 1;
                    if d < dmin {
                        dmin = d;
                        first = s;
                    }
                }
                j += 1;
            }
            i = j;
            let reach = first.hw + first.fade;
            if n == 0 || dmin >= reach {
                continue;
            }
            let (mut num, mut den) = (0.0, 0.0);
            for &(d, surf) in &near[..n] {
                let k = (-(d - dmin) / SOFT).d_exp();
                num += k * surf;
                den += k;
            }
            let w = (1.0 - smoothstep(first.hw, reach, dmin)) * wf;
            t = lerp(t, num / den, w);
        }
        if p0 == p1 {
            return t;
        }
        const MAXP: usize = 48;
        let mut d = [0f32; MAXP];
        let ids = &self.pad_ids[p0..p1.min(p0 + MAXP)];
        for (n, &id) in ids.iter().enumerate() {
            d[n] = self.pads[id as usize].outside(p);
        }
        let (mut num, mut den) = (0.0, 0.0);
        for (a, &ia) in ids.iter().enumerate() {
            let pa = &self.pads[ia as usize];
            if d[a] >= pa.skirt {
                continue;
            }
            let mut w = 1.0 - smoothstep(0.0, pa.skirt, d[a]);
            for (b, &ib) in ids.iter().enumerate() {
                let g = self.pads[ib as usize].gate;
                if b != a && d[b] < g {
                    w *= smoothstep(0.0, g, d[b]);
                }
            }
            w *= wf;
            num += w * (pa.floor_at(p) - t);
            den += w;
        }
        t + num / den.max(1.0)
    }
}

// ------------------------------------------------------------------------------------------
// Planning

const SITE_MARK: u32 = u32::MAX - 1;

/// Mark a cell of the road network and its neighbours (unless already marked).
fn mark_net(net: &mut [u32], n: usize, k: usize, v: u32) {
    let (i, j) = ((k % n) as isize, (k / n) as isize);
    for dy in -1..=1 {
        for dx in -1..=1 {
            let (x, y) = (i + dx, j + dy);
            if x >= 0 && y >= 0 && x < n as isize && y < n as isize {
                let q = y as usize * n + x as usize;
                if net[q] == 0 {
                    net[q] = v;
                }
            }
        }
    }
}

/// Island roads between their parts ([`Plan::roads_begin`]): the routing grid, the network
/// cells, the settlements still to join with their distances to the network, and the routed
/// paths.
pub(crate) struct RoadWork {
    gr: Grid,
    net: Vec<u32>,
    foot: Vec<u32>,
    town: usize,
    tc: V2,
    connected: Vec<usize>,
    todo: Vec<usize>,
    near: Vec<f32>,
    raw: Vec<(Vec<usize>, RoadEnd, RoadEnd, f32, RoadClass)>,
    pre: u32,
}

/// Settlements routed into the island's road network per step of [`Staged`].
const ROUTES_PER_STEP: usize = 8;

/// The routing grid.
struct Grid {
    g: f32,
    n: usize,
    h: Vec<f32>,
    cost: Vec<f32>,
    river: Vec<bool>,
    shore: Vec<bool>,
    /// Lake or wetland water: crossed only when nothing else reaches (a causeway).
    still: Vec<bool>,
}

const MOVES: [(i32, i32); 16] = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1), (1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)];

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

impl Grid {
    fn new(land: &Land, rp: &RoadParams) -> Self {
        let g = rp.grid_m;
        let n = (land.size as f32 / g).floor() as usize;
        let w = land.size as i32;
        let mut river = vec![false; n * n];
        for r in &land.rivers {
            for i in 0..r.points.len().saturating_sub(1) {
                let (a, b) = (r.points[i], r.points[i + 1]);
                let hw = r.width_m[i] * 0.5 + 3.0;
                let lo = ((a.0.min(b.0) - hw) / g).floor().max(0.0) as usize;
                let hi = (((a.0.max(b.0) + hw) / g).ceil() as usize).min(n - 1);
                let lo_y = ((a.1.min(b.1) - hw) / g).floor().max(0.0) as usize;
                let hi_y = (((a.1.max(b.1) + hw) / g).ceil() as usize).min(n - 1);
                for j in lo_y..=hi_y {
                    for i2 in lo..=hi {
                        let c = ((i2 as f32 + 0.5) * g, (j as f32 + 0.5) * g);
                        if seg_near(c, a, b).0 < hw + g * 0.5 {
                            river[j * n + i2] = true;
                        }
                    }
                }
            }
        }
        let mut h = vec![0f32; n * n];
        let mut cost = vec![f32::INFINITY; n * n];
        let mut sea = vec![false; n * n];
        let s = g as i32;
        for j in 0..n {
            for i in 0..n {
                let k = j * n + i;
                let (cx, cy) = ((i as f32 + 0.5) * g, (j as f32 + 0.5) * g);
                h[k] = land.height(cx, cy);
                let (mut water, mut rock, mut forest, mut sand, mut total) = (0, 0, 0, 0, 0);
                for ty in (j as i32 * s)..((j as i32 + 1) * s).min(w) {
                    for tx in (i as i32 * s)..((i as i32 + 1) * s).min(w) {
                        total += 1;
                        match land.map.get(tx, ty) {
                            Terrain::Water => water += 1,
                            Terrain::Rock => rock += 1,
                            Terrain::Forest => forest += 1,
                            Terrain::Sand => sand += 1,
                            _ => {}
                        }
                    }
                }
                let t = total.max(1) as f32;
                if water > 0 {
                    if river[k] {
                        cost[k] = rp.river_cost;
                    } else {
                        sea[k] = land.water_level(cx, cy) < 0.5;
                    }
                    continue;
                }
                let mut c = 1.0 + (rp.forest_cost - 1.0) * forest as f32 / t + (rp.sand_cost - 1.0) * sand as f32 / t + (rp.rock_cost - 1.0) * rock as f32 / t;
                if river[k] && sand > 0 {
                    // An existing ford.
                    c = c.min(rp.ford_cost);
                }
                if land.kind_at(cx, cy) == RegionKind::SpiritGrove {
                    c *= rp.grove_cost;
                }
                cost[k] = c;
            }
        }
        let mut shore = vec![false; n * n];
        for j in 1..n - 1 {
            for i in 1..n - 1 {
                let k = j * n + i;
                if cost[k].is_finite() && !river[k] && [k - 1, k + 1, k - n, k + n].iter().any(|&q| sea[q]) {
                    shore[k] = true;
                }
            }
        }
        let still = (0..n * n).map(|k| !cost[k].is_finite() && !sea[k]).collect();
        Self { g, n, h, cost, river, shore, still }
    }

    fn cell(&self, p: V2) -> usize {
        let c = |v: f32| ((v / self.g).floor() as isize).clamp(0, self.n as isize - 1) as usize;
        c(p.1) * self.n + c(p.0)
    }

    fn centre(&self, k: usize) -> V2 {
        (((k % self.n) as f32 + 0.5) * self.g, ((k / self.n) as f32 + 0.5) * self.g)
    }

    /// Least-cost path from `from` to the first cell where `goal` holds.
    fn route(&self, rp: &RoadParams, from: usize, goal: &dyn Fn(usize) -> bool, max_cost: f32) -> Option<Vec<usize>> {
        self.route_with(rp, from, goal, max_cost, false).or_else(|| self.route_with(rp, from, goal, max_cost, true))
    }

    fn route_with(&self, rp: &RoadParams, from: usize, goal: &dyn Fn(usize) -> bool, max_cost: f32, causeway: bool) -> Option<Vec<usize>> {
        let cost = |k: usize| if causeway && self.still[k] { rp.river_cost * 4.0 } else { self.cost[k] };
        let n = self.n as i32;
        let mut best = vec![f32::INFINITY; self.n * self.n];
        let mut prev = vec![u32::MAX; self.n * self.n];
        let mut heap = BinaryHeap::new();
        best[from] = 0.0;
        heap.push(Open(0.0, from as u32));
        while let Some(Open(c, k)) = heap.pop() {
            let k = k as usize;
            if c > best[k] {
                continue;
            }
            if k != from && goal(k) {
                let mut path = vec![k];
                let mut q = k;
                while prev[q] != u32::MAX {
                    q = prev[q] as usize;
                    path.push(q);
                }
                path.reverse();
                return Some(path);
            }
            if c > max_cost {
                break;
            }
            let (i, j) = ((k % self.n) as i32, (k / self.n) as i32);
            for (dx, dy) in MOVES {
                let (x, y) = (i + dx, j + dy);
                if x < 0 || y < 0 || x >= n || y >= n {
                    continue;
                }
                let q = (y * n + x) as usize;
                if !cost(q).is_finite() {
                    continue;
                }
                let mut f = 0.5 * (cost(k) + cost(q));
                if dx.abs() + dy.abs() == 3 {
                    // A knight's move passes over two cells; both must be passable.
                    let (a, b) = if dx.abs() == 2 { ((i + dx.signum(), j), (i + dx.signum(), j + dy)) } else { ((i, j + dy.signum()), (i + dx, j + dy.signum())) };
                    let (ca, cb) = (cost((a.1 * n + a.0) as usize), cost((b.1 * n + b.0) as usize));
                    if !ca.is_finite() || !cb.is_finite() {
                        continue;
                    }
                    f = (f * 2.0 + ca + cb) * 0.25;
                }
                let d = ((dx * dx + dy * dy) as f32).sqrt() * self.g;
                let grade = (self.h[q] - self.h[k]).abs() / d;
                let mut gp = 1.0 + (grade / rp.grade_ref).powi(2);
                if grade > rp.max_grade {
                    gp *= 30.0;
                }
                let nc = c + d * f * gp;
                if nc < best[q] {
                    best[q] = nc;
                    prev[q] = k as u32;
                    heap.push(Open(nc, q as u32));
                }
            }
        }
        None
    }
}

/// Shared state while planning.
struct Plan<'a> {
    land: &'a Land,
    p: &'a SettleParams,
    roads: Vec<Road>,
    lots: Vec<Lot>,
    settlements: Vec<Settlement>,
    crossings: Vec<Crossing>,
    road_b: Buckets,
    lot_b: Buckets,
    /// Wall centre lines as obstacles: (settlement, half thickness, ring).
    walls: Vec<(u16, f32, Vec<V2>)>,
    /// Per settlement: edge radius per direction, and the inner edge (inside its wall lane).
    bounds: Vec<(Vec<f32>, Vec<f32>)>,
    seed: u64,
    /// Models per (style, kind), as indices into `p.buildings.models`.
    catalog: Vec<(String, LotKind, Vec<u32>)>,
    /// Stairs between terraces, placed before the lots so lots keep clear of them.
    stairs: Vec<Prop>,
    /// The city's centre and the radius roads between settlements keep out of.
    city: Option<(V2, f32)>,
}

/// Plan every settlement and the island's roads, paint them into the tiles and shape the ground,
/// in steps, so a caller with a per-call budget (the authority's reducers) can run them
/// one at a time; what one step hands the next is owned here.
#[derive(Default)]
pub(crate) struct Staged {
    next: Step,
    city: Option<metro::City>,
    roads: Vec<Road>,
    crossings: Vec<Crossing>,
    terr: Vec<Terrace>,
    segs: Vec<Seg>,
    settlements: Vec<Settlement>,
    walls: Vec<(u16, f32, Vec<V2>)>,
    bounds: Vec<(Vec<f32>, Vec<f32>)>,
    lots: Vec<Lot>,
    stairs: Vec<Prop>,
    /// The planner between the lot steps.
    parked: Option<Parked>,
    /// Ornaments between their steps, and how many are done.
    dressing: Option<ornament::Dressing>,
    dressed: u32,
    dressing_left: u32,
    /// The city's wards (one lot step each, plus their back-fill steps).
    wards: usize,
    fills: Vec<usize>,
    /// The first lot of the ward being planned.
    ward_start: u32,
    /// Island roads between their steps, and the route steps expected (known once begun).
    road_work: Option<RoadWork>,
    route_steps: u32,
    /// Hand-authored settlements ([`PlanSpec`], from `LandParams::plans`), and what the `Plan`
    /// step laid out of them for the later steps.
    pub(crate) specs: Vec<PlanSpec>,
    plans: Vec<plan::Built>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum Step {
    #[default]
    City,
    /// Planned settlements ([`plan`]): their ground, streets, lots, stairs and retaining walls.
    /// Only when the land has plans.
    Plan,
    /// The routing grid and the network to join.
    Roads,
    /// Settlements routed into it, [`ROUTES_PER_STEP`] per step.
    RoadRoutes(u32),
    /// The landing, cave paths, smoothing, river crossings, painted.
    RoadsEnd,
    Streets,
    Stairs,
    /// The city's wards' lots, one ward per step, then each ward's back-fill in steps.
    Ward(usize),
    WardFill(usize, usize),
    /// The other settlements' lots.
    Towns,
    Paint,
    Connect,
    /// Ornaments, a few settlements per step.
    Ornaments,
    /// The roads as a graph for known ways ([`crate::ways`]), on the finished roads.
    Ways,
    Done,
}

impl Staged {
    /// How many steps [`Staged::step`] takes: known once the city is laid out (its wards).
    pub(crate) fn steps(&self) -> u32 {
        // Ornament steps are counted from the settlements once they are planned (one before).
        let left = if self.next == Step::Done { 0 } else { self.dressing_left.max(1) };
        8 + self.plan_steps() + self.road_steps() + self.wards() as u32 + self.fills.iter().sum::<usize>() as u32 + self.dressed + left
    }

    /// Route steps plus the end step of the island roads.
    fn road_steps(&self) -> u32 {
        self.route_steps.max(1) + 1
    }

    fn wards(&self) -> usize {
        self.wards
    }

    /// The `Plan` step, when the land has plans.
    fn plan_steps(&self) -> u32 {
        (!self.specs.is_empty()) as u32
    }

    fn plan_grounds(&self) -> Vec<plan::Ground> {
        self.plans.iter().map(|b| b.ground.clone()).collect()
    }

    fn plan_pads(&self) -> Vec<Pad> {
        self.plans.iter().flat_map(|b| b.pads.iter().cloned()).collect()
    }

    /// Where planned settlements' drops are walled ([`terrace::paint_drops`]): round each plan.
    fn plan_zones(&self) -> Vec<(V2, f32)> {
        self.plans.iter().map(|b| (b.res.centre, b.res.radius + b.res.skirt + 4.0)).collect()
    }

    /// Steps done so far.
    pub(crate) fn done(&self) -> u32 {
        let w = (self.wards() + self.fills.iter().sum::<usize>()) as u32;
        let ward_step = |i: usize| (i + self.fills[..i].iter().sum::<usize>()) as u32;
        let r = self.road_steps() + self.plan_steps();
        let q = self.plan_steps();
        match self.next {
            Step::City => 0,
            Step::Plan => 1,
            Step::Roads => 1 + q,
            Step::RoadRoutes(k) => 2 + q + k,
            Step::RoadsEnd => 1 + r,
            Step::Streets => 2 + r,
            Step::Stairs => 3 + r,
            Step::Ward(i) => 4 + r + ward_step(i),
            Step::WardFill(i, k) => 5 + r + ward_step(i) + k as u32,
            Step::Towns => 4 + r + w,
            Step::Paint => 5 + r + w,
            Step::Connect => 6 + r + w,
            Step::Ornaments => 7 + r + w + self.dressed,
            Step::Ways => 7 + r + w + self.dressed,
            Step::Done => self.steps(),
        }
    }

    pub(crate) fn label(&self) -> String {
        match self.next {
            Step::City => "city".into(),
            Step::Plan => "planned settlements".into(),
            Step::Roads => "island roads: grid".into(),
            Step::RoadRoutes(k) => format!("island roads: routes {} of {}", k + 1, self.route_steps.max(1)),
            Step::RoadsEnd => "island roads: smoothing and crossings".into(),
            Step::Streets => "streets".into(),
            Step::Stairs => "stairs".into(),
            Step::Ward(i) => format!("ward {} of {} lots", i + 1, self.wards()),
            Step::WardFill(i, k) => format!("ward {} back-fill {} of {}", i + 1, k + 1, self.fills[i]),
            Step::Towns => "lots".into(),
            Step::Paint => "paint".into(),
            Step::Connect => "walled connectivity".into(),
            Step::Ornaments => format!("ornaments ({} of {})", self.dressed + 1, self.dressed + self.dressing_left.max(1)),
            Step::Ways => "the roads as a graph".into(),
            Step::Done => "done".into(),
        }
    }

    /// Run the next step; true once the plan is complete.
    pub(crate) fn step(&mut self, land: &mut Land, p: &SettleParams, metro: Option<&MetroParams>) -> bool {
        self.next = match self.next {
            // The city, if the land holds one: its highways, wards and streets come first, and
            // the roads between the other settlements join its arterials outside the wall.
            Step::City => {
                self.city = metro.map(|mp| {
                    metro::clear(land, mp);
                    let c = metro::lay_out(land, mp);
                    land.sites.extend(c.sites.iter().cloned());
                    c
                });
                self.wards = self.city.as_ref().map_or(0, |c| c.wards());
                self.fills = match (&self.city, metro) {
                    (Some(c), Some(mp)) => (0..c.wards()).map(|wi| metro::fill_steps(c, mp, wi)).collect(),
                    _ => Vec::new(),
                };
                if self.specs.is_empty() {
                    Step::Roads
                } else {
                    Step::Plan
                }
            }
            // Planned settlements, before anything is routed or traced: their ground is part of
            // the land every later step reads (`Land::height`, the tiles).
            Step::Plan => {
                let res: Vec<plan::Resolved> = self.specs.iter().map(|s| plan::resolve(s).unwrap_or_else(|e| panic!("{e}"))).collect();
                for r in &res {
                    let (lo, hi) = plan::paint(land, r);
                    land.update_sd(lo, hi);
                }
                let grounds: Vec<plan::Ground> = res.iter().map(plan::Ground::of).collect();
                land.mods = Mods::build(land.size, Vec::new(), Vec::new(), Vec::new(), grounds.clone());
                let city_sets = self.city.as_ref().map_or(0, |c| c.settlements.len());
                let mut first_road = self.city.as_ref().map_or(0, |c| c.roads.len()) as u32;
                let mut built = Vec::new();
                for (k, r) in res.into_iter().enumerate() {
                    let site = land.sites.iter().position(|s| s.plan.as_deref() == Some(r.id.as_str())).expect("a plan's site") as u16;
                    let n = r.streets.len() as u32;
                    built.push(plan::build(land, r, (city_sets + k) as u16, site, first_road));
                    first_road += n;
                }
                // The stairs into the ground, then retaining walls along the finished drops.
                let pads: Vec<Pad> = built.iter().flat_map(|b| b.pads.iter().cloned()).collect();
                land.mods = Mods::build(land.size, Vec::new(), pads, Vec::new(), grounds);
                for b in built.iter_mut() {
                    let idx = b.laid.settlement;
                    plan::retaining(land, b, idx);
                }
                self.plans = built;
                Step::Roads
            }
            // Island roads, painted first so river crossings become land before profiles are
            // sampled.
            Step::Roads => {
                let mut pl = Plan::new(land, p);
                if let Some(c) = &self.city {
                    for r in &c.roads {
                        pl.push_road(r.clone());
                    }
                    pl.city = Some((c.centre, c.radius * 1.03));
                }
                for b in &self.plans {
                    for r in &b.roads {
                        pl.push_road(r.clone());
                    }
                }
                let res: Vec<&plan::Resolved> = self.plans.iter().map(|b| &b.res).collect();
                self.road_work = pl.roads_begin(&res);
                self.route_steps = self.road_work.as_ref().map_or(0, |w| w.todo.len().div_ceil(ROUTES_PER_STEP) as u32);
                if self.road_work.is_some() {
                    Step::RoadRoutes(0)
                } else {
                    Step::RoadsEnd
                }
            }
            Step::RoadRoutes(k) => {
                let pl = Plan::new(land, p);
                let w = self.road_work.as_mut().expect("road work");
                if pl.roads_route(w, ROUTES_PER_STEP) {
                    Step::RoadsEnd
                } else {
                    Step::RoadRoutes(k + 1)
                }
            }
            Step::RoadsEnd => {
                let (roads, crossings) = {
                    let mut pl = Plan::new(land, p);
                    if let Some(c) = &self.city {
                        for r in &c.roads {
                            pl.push_road(r.clone());
                        }
                        pl.city = Some((c.centre, c.radius * 1.03));
                    }
                    for b in &self.plans {
                        for r in &b.roads {
                            pl.push_road(r.clone());
                        }
                    }
                    if let Some(w) = self.road_work.take() {
                        pl.roads_end(w);
                    }
                    pl.find_crossings();
                    (pl.roads, pl.crossings)
                };
                let changed = paint_roads(land, &roads, 0);
                for c in changed {
                    land.update_sd(c.0, c.1);
                }
                (self.roads, self.crossings) = (roads, crossings);
                Step::Streets
            }
            // Terraces where a settlement's site has relief: streets are traced over them.
            // Then settlement streets and lanes, and their profiles.
            Step::Streets => {
                self.terr = terrace::terraces(land, p);
                land.mods = Mods::build(land.size, Vec::new(), self.plan_pads(), self.terr.clone(), self.plan_grounds());
                let mut pl = Plan::new(land, p);
                for (i, r) in self.roads.iter().enumerate() {
                    pl.add_road_index(i as u32, r);
                }
                pl.roads = std::mem::take(&mut self.roads);
                pl.crossings = std::mem::take(&mut self.crossings);
                if let Some(c) = &self.city {
                    pl.settlements = c.settlements.clone();
                    pl.bounds = c.bounds.clone();
                    pl.walls = c.walls.clone();
                }
                // Planned settlements after the city's wards, before the generated ones.
                for b in &self.plans {
                    pl.settlements.push(b.settlement.clone());
                    pl.bounds.push((b.bound.clone(), b.bound.clone()));
                }
                pl.lay_out_streets();
                pl.fix_junctions();
                pl.profiles();
                self.segs = pl.road_segs();
                (self.roads, self.crossings, self.settlements) = (std::mem::take(&mut pl.roads), std::mem::take(&mut pl.crossings), std::mem::take(&mut pl.settlements));
                (self.walls, self.bounds) = (std::mem::take(&mut pl.walls), std::mem::take(&mut pl.bounds));
                Step::Stairs
            }
            // Lots against the graded roads: stairs first, which lots keep clear of.
            Step::Stairs => {
                land.mods = Mods::build(land.size, self.segs.clone(), self.plan_pads(), self.terr.clone(), self.plan_grounds());
                let mut pl = Plan::new(land, p);
                for (i, r) in self.roads.iter().enumerate() {
                    pl.add_road_index(i as u32, r);
                }
                pl.roads = std::mem::take(&mut self.roads);
                pl.crossings = std::mem::take(&mut self.crossings);
                pl.settlements = std::mem::take(&mut self.settlements);
                pl.walls = std::mem::take(&mut self.walls);
                pl.bounds = std::mem::take(&mut self.bounds);
                // Planned lots first, as written; generated lots keep clear of them.
                for b in self.plans.iter_mut() {
                    let idx = b.laid.settlement as usize;
                    let start = pl.lots.len() as u32;
                    for (i, lot) in b.lots.iter().enumerate() {
                        let id = pl.lots.len() as u32;
                        let (lo, hi) = lot.rect().bbox(0.0);
                        pl.lot_b.insert(lo, hi, id);
                        pl.lots.push(lot.clone());
                        b.laid.lots[i].lot = id;
                    }
                    pl.settlements[idx].lots = (start, pl.lots.len() as u32);
                }
                pl.place_stairs();
                self.parked = Some(pl.park());
                if self.wards() > 0 {
                    Step::Ward(0)
                } else {
                    Step::Towns
                }
            }
            Step::Ward(i) | Step::WardFill(i, _) => {
                let mut pl = Plan::resume(land, p, self.parked.take().expect("parked plan"));
                let k = match self.next {
                    Step::WardFill(_, k) => Some(k),
                    _ => None,
                };
                if let (Some(c), Some(mp)) = (&self.city, metro) {
                    match k {
                        None => {
                            self.ward_start = pl.lots.len() as u32;
                            metro::ward_lots(&mut pl, c, mp, i);
                        }
                        Some(k) => metro::ward_fill(&mut pl, c, mp, i, k),
                    }
                }
                let fill_next = k.map_or(0, |k| k + 1);
                let next = if fill_next < self.fills.get(i).copied().unwrap_or(0) {
                    Step::WardFill(i, fill_next)
                } else {
                    metro::ward_close(&mut pl, i, self.ward_start);
                    if i + 1 < self.wards() {
                        Step::Ward(i + 1)
                    } else {
                        Step::Towns
                    }
                };
                self.parked = Some(pl.park());
                next
            }
            Step::Towns => {
                let mut pl = Plan::resume(land, p, self.parked.take().expect("parked plan"));
                pl.place_lots();
                let mut pads = pl.pads();
                pads.extend(self.plan_pads());
                let Plan { roads, lots, settlements, crossings, stairs, .. } = pl;
                (self.roads, self.lots, self.settlements, self.crossings, self.stairs) = (roads, lots, settlements, crossings, stairs);
                land.mods = Mods::build(land.size, std::mem::take(&mut self.segs), pads, std::mem::take(&mut self.terr), self.plan_grounds());
                Step::Paint
            }
            // Paint the plan into the tiles.
            Step::Paint => {
                let (roads, lots, settlements) = (&self.roads, &self.lots, &self.settlements);
                paint_roads(land, roads, 1);
                paint_rest(land, settlements, lots);
                if let (Some(c), Some(mp)) = (&self.city, metro) {
                    metro::pave(land, c, mp, lots);
                }
                // Stairs are walkable; then the drops nobody can climb become walls.
                terrace::paint_stairs(land, &self.stairs);
                let planned: Vec<Prop> = self.plans.iter().flat_map(|b| b.props.iter().filter(|pr| pr.kind == PropKind::Stairs).cloned()).collect();
                terrace::paint_stairs(land, &planned);
                terrace::paint_drops(land, lots, settlements, p, &self.plan_zones());
                Step::Connect
            }
            // Walls must not seal anyone in: link any pocket they made through water or rock,
            // never through a wall.
            Step::Connect => {
                let (lots, settlements) = (&self.lots, &self.settlements);
                let water: Vec<u32> = (0..land.map.tiles.len() as u32).filter(|&k| land.map.tiles[k as usize] == Terrain::Water as u8).collect();
                let (opened, _) = crate::land::connect_walled(&mut land.map.tiles, land.size as usize);
                land.opened_tiles += opened;
                // Fords it cut change the distance to water around them.
                let w = land.size as i32;
                let mut boxes: Vec<((i32, i32), (i32, i32))> = Vec::new();
                for k in water {
                    if land.map.tiles[k as usize] != Terrain::Water as u8 {
                        let (x, y) = (k as i32 % w, k as i32 / w);
                        match boxes.iter_mut().find(|b| x >= b.0 .0 - 8 && x <= b.1 .0 + 8 && y >= b.0 .1 - 8 && y <= b.1 .1 + 8) {
                            Some(b) => *b = ((b.0 .0.min(x), b.0 .1.min(y)), (b.1 .0.max(x), b.1 .1.max(y))),
                            None => boxes.push(((x, y), (x, y))),
                        }
                    }
                }
                for b in boxes {
                    land.update_sd(b.0, b.1);
                }
                // Fords change the ground near them: wall any drop that left.
                terrace::paint_drops(land, lots, settlements, p, &self.plan_zones());
                land.plans = self.plans.iter().map(|b| b.laid.clone()).collect();
                land.roads = std::mem::take(&mut self.roads);
                land.lots = std::mem::take(&mut self.lots);
                land.settlements = std::mem::take(&mut self.settlements);
                land.crossings = std::mem::take(&mut self.crossings);
                self.dressing_left = land.settlements.len() as u32;
                Step::Ornaments
            }
            // Ornaments, retaining walls and the stairs, on the finished ground.
            Step::Ornaments => {
                let d = self.dressing.take().unwrap_or_else(|| {
                    // Generated stairs, then the plans' stairs and retaining walls, as props.
                    let mut props = std::mem::take(&mut self.stairs);
                    props.extend(self.plans.drain(..).flat_map(|b| b.props));
                    ornament::Dressing::new(land, p, props, metro)
                });
                self.dressed += 1;
                match d.step(land, p) {
                    Ok(props) => {
                        land.props = props;
                        self.city = None;
                        self.dressing_left = 0;
                        Step::Ways
                    }
                    Err(d) => {
                        self.dressing_left = d.steps_left(land);
                        self.dressing = Some(d);
                        Step::Ornaments
                    }
                }
            }
            Step::Ways => {
                land.ways = Some(crate::ways::Ways::of(land));
                Step::Done
            }
            Step::Done => Step::Done,
        };
        self.next == Step::Done
    }
}

/// A [`Plan`] without its borrows, kept between steps of [`Staged`].
struct Parked {
    roads: Vec<Road>,
    lots: Vec<Lot>,
    settlements: Vec<Settlement>,
    crossings: Vec<Crossing>,
    road_b: Buckets,
    lot_b: Buckets,
    walls: Vec<(u16, f32, Vec<V2>)>,
    bounds: Vec<(Vec<f32>, Vec<f32>)>,
    seed: u64,
    catalog: Vec<(String, LotKind, Vec<u32>)>,
    stairs: Vec<Prop>,
    city: Option<(V2, f32)>,
}

impl<'a> Plan<'a> {
    fn park(self) -> Parked {
        let Plan { land: _, p: _, roads, lots, settlements, crossings, road_b, lot_b, walls, bounds, seed, catalog, stairs, city } = self;
        Parked { roads, lots, settlements, crossings, road_b, lot_b, walls, bounds, seed, catalog, stairs, city }
    }

    fn resume(land: &'a Land, p: &'a SettleParams, k: Parked) -> Self {
        let Parked { roads, lots, settlements, crossings, road_b, lot_b, walls, bounds, seed, catalog, stairs, city } = k;
        Plan { land, p, roads, lots, settlements, crossings, road_b, lot_b, walls, bounds, seed, catalog, stairs, city }
    }
}

impl<'a> Plan<'a> {
    fn new(land: &'a Land, p: &'a SettleParams) -> Self {
        let s = land.size as f32;
        // Each style's models per lot kind, through the style's kind names.
        let mut catalog: Vec<(String, LotKind, Vec<u32>)> = Vec::new();
        for st in &p.styles {
            for kind in LotKind::ALL {
                let Some(id) = st.model_kind(kind) else { continue };
                if catalog.iter().any(|c| c.0 == st.buildings && c.1 == kind) {
                    continue;
                }
                let kit = st.kit.as_deref().unwrap_or(&st.buildings);
                let ms: Vec<u32> = (0..p.buildings.models.len() as u32).filter(|&i| p.buildings.models[i as usize].style == kit && p.buildings.models[i as usize].kind == id).collect();
                if !ms.is_empty() {
                    catalog.push((st.buildings.clone(), kind, ms));
                }
            }
        }
        Self { land, p, roads: Vec::new(), lots: Vec::new(), settlements: Vec::new(), crossings: Vec::new(), road_b: Buckets::new(s, 32.0), lot_b: Buckets::new(s, 32.0), walls: Vec::new(), bounds: Vec::new(), seed: land.seed ^ 0x5E77, catalog, stairs: Vec::new(), city: None }
    }

    fn style(&self, kind: SiteKind) -> Option<&'a Style> {
        self.p.styles.iter().find(|s| s.site == kind)
    }

    /// The style a site is laid out in.
    fn site_style(&self, si: usize) -> Option<&'a Style> {
        self.p.style_for_site(&self.land.sites[si])
    }

    /// The style of a laid-out settlement.
    fn set_style(&self, idx: u16) -> &'a Style {
        self.site_style(self.settlements[idx as usize].site as usize).expect("a settlement has a style")
    }

    /// The terraces of a site, if its ground is terraced.
    fn zone(&self, si: usize) -> Option<&'a Terrace> {
        self.land.mods.terr.iter().find(|z| z.site as usize == si)
    }

    fn add_road_index(&mut self, id: u32, r: &Road) {
        for i in 0..r.points.len().saturating_sub(1) {
            let (a, b) = (r.points[i], r.points[i + 1]);
            let pad = r.width_m * 0.5 + 1.0;
            self.road_b.insert((a.0.min(b.0) - pad, a.1.min(b.1) - pad), (a.0.max(b.0) + pad, a.1.max(b.1) + pad), id);
        }
    }

    fn push_road(&mut self, r: Road) -> u32 {
        let id = self.roads.len() as u32;
        self.add_road_index(id, &r);
        self.roads.push(r);
        id
    }

    // -------------------------------------------------------------------------------------
    // Island roads

    /// Island roads, in three parts so a caller with a per-call budget can spread them
    /// ([`Staged`]): the routing grid and the network to join ([`Plan::roads_begin`]), the
    /// settlements routed a few at a time, nearest to the network first
    /// ([`Plan::roads_route`]), and the landing, the cave paths and the smoothing
    /// ([`Plan::roads_end`]). In one go here.
    #[allow(dead_code)]
    fn island_roads(&mut self) {
        if let Some(mut w) = self.roads_begin(&[]) {
            while !self.roads_route(&mut w, usize::MAX) {}
            self.roads_end(w);
        }
    }

    fn roads_begin(&mut self, plans: &[&plan::Resolved]) -> Option<RoadWork> {
        let land = self.land;
        let rp = &self.p.roads;
        let mut gr = Grid::new(land, rp);
        let n = gr.n;
        // Network cells: 0 none, else road id + 1, or SITE_MARK at the town's centre.
        let mut net = vec![0u32; n * n];
        let foot = vec![0u32; n * n];
        // Planned settlements are joined through their trunk streets, not routed to.
        let settled: Vec<usize> = (0..land.sites.len()).filter(|&i| land.sites[i].kind != SiteKind::Cave && !land.sites[i].ward && land.sites[i].plan.is_none() && self.site_style(i).is_some()).collect();
        // Roads laid out already (the city's highways and arterials) are the network's start;
        // roads between settlements keep out of the city and join them outside its wall.
        let pre = self.roads.len() as u32;
        if let Some((cc, cr)) = self.city {
            for k in 0..n * n {
                if dist(gr.centre(k), cc) < cr {
                    gr.cost[k] = f32::INFINITY;
                }
            }
        }
        // Nor through a planned settlement: its levels and harbour are as written.
        for r in plans {
            for k in 0..n * n {
                if plan::covers(r, gr.centre(k), 2.0) {
                    gr.cost[k] = f32::INFINITY;
                }
            }
        }
        for ri in 0..pre {
            let r = &self.roads[ri as usize];
            if r.class != RoadClass::Trunk {
                continue;
            }
            for q in resample(&r.points, gr.g * 0.5) {
                let k = gr.cell(q);
                if net[k] == 0 {
                    net[k] = ri + 1;
                }
            }
        }
        // Trunk roads laid out already are the network; without any, the first town is its hub.
        let town = if pre > 0 && self.roads.iter().any(|r| r.class == RoadClass::Trunk) { None } else { settled.iter().find(|&&i| land.sites[i].kind == SiteKind::Town).or(settled.first()).copied() };
        if pre == 0 && town.is_none() {
            return None;
        }
        let tc = town.map_or((0.0, 0.0), |t| (land.sites[t].x, land.sites[t].y));
        let town = town.unwrap_or(usize::MAX);
        if town != usize::MAX {
            mark_net(&mut net, n, gr.cell(tc), SITE_MARK);
        }
        let connected: Vec<usize> = if town != usize::MAX { vec![town] } else { Vec::new() };
        let todo: Vec<usize> = settled.iter().cloned().filter(|&i| i != town).collect();
        let raw: Vec<(Vec<usize>, RoadEnd, RoadEnd, f32, RoadClass)> = Vec::new();
        let pre_roads = &self.roads;
        let dist_to_net = |raw: &[(Vec<usize>, RoadEnd, RoadEnd, f32, RoadClass)], connected: &[usize], q: V2| {
            let mut m = connected.iter().map(|&i| dist(q, (land.sites[i].x, land.sites[i].y))).fold(f32::MAX, f32::min);
            for r in pre_roads.iter().filter(|r| r.class == RoadClass::Trunk) {
                for p in r.points.iter().step_by(8) {
                    m = m.min(dist(q, *p));
                }
            }
            for r in raw {
                for &k in r.0.iter().step_by(4) {
                    m = m.min(dist(q, gr.centre(k)));
                }
            }
            m
        };
        // Settlements, nearest to the network first: each road ends where it meets the network,
        // so later roads branch off earlier ones. Each one's distance to the network is kept up
        // to date as the network grows (the newly connected site and the new road's cells), the
        // same minimum as measuring it afresh each round, without the rounds × settlements ×
        // network work a land of many hamlets would cost.
        let near: Vec<f32> = todo.iter().map(|&i| dist_to_net(&raw, &connected, (land.sites[i].x, land.sites[i].y))).collect();
        Some(RoadWork { gr, net, foot, town, tc, connected, todo, near, raw, pre })
    }

    /// Route up to `budget` settlements into the network; true once every one is routed.
    fn roads_route(&self, w: &mut RoadWork, budget: usize) -> bool {
        let land = self.land;
        let rp = &self.p.roads;
        let RoadWork { gr, net, foot, town, connected, todo, near, raw, pre, .. } = w;
        let (n, town, pre) = (gr.n, *town, *pre);
        let mut left = budget;
        while !todo.is_empty() {
            if left == 0 {
                return false;
            }
            left -= 1;
            let (ti, _) = near.iter().copied().enumerate().min_by(|a, b| a.1.total_cmp(&b.1)).unwrap();
            let si = todo.swap_remove(ti);
            near.swap_remove(ti);
            let s = &land.sites[si];
            let Some(style) = self.site_style(si) else { continue };
            for (t, &i) in todo.iter().enumerate() {
                near[t] = near[t].min(dist((land.sites[i].x, land.sites[i].y), (s.x, s.y)));
            }
            let from = gr.cell((s.x, s.y));
            let class = if s.kind == SiteKind::SmallFolk { RoadClass::Path } else { RoadClass::Trunk };
            // A road never joins a footpath; a footpath may join anything.
            let path = gr.route(rp, from, &|k| net[k] != 0 || (class == RoadClass::Path && foot[k] != 0), f32::INFINITY);
            connected.push(si);
            let Some(mut path) = path else { continue };
            let last = *path.last().unwrap();
            let hit = if net[last] != 0 { net[last] } else { foot[last] };
            path.reverse();
            let start = if hit == SITE_MARK { RoadEnd::Site(town as u16) } else { RoadEnd::Road(hit - 1) };
            let id = pre + raw.len() as u32;
            for &k in &path {
                mark_net(if class == RoadClass::Path { &mut *foot } else { &mut *net }, n, k, id + 1);
            }
            for (t, &i) in todo.iter().enumerate() {
                let q = (land.sites[i].x, land.sites[i].y);
                for &k in path.iter().step_by(4) {
                    near[t] = near[t].min(dist(q, gr.centre(k)));
                }
            }
            raw.push((path, start, RoadEnd::Site(si as u16), style.trunk_m, class));
        }
        true
    }

    /// The landing, the cave paths, and every routed road smoothed and laid out.
    fn roads_end(&mut self, w: RoadWork) {
        let land = self.land;
        let rp = &self.p.roads;
        let RoadWork { gr, mut net, mut foot, town, tc, mut raw, pre, .. } = w;
        let n = gr.n;
        // A road from the town down to the sea, ending at a landing.
        if rp.landing_m > 0.0 && town != usize::MAX {
            let best = (0..n * n).filter(|&k| gr.shore[k] && dist(gr.centre(k), tc) < rp.landing_m).min_by(|&a, &b| {
                let score = |k: usize| dist(gr.centre(k), tc) - if land.map.at(gr.centre(k).0, gr.centre(k).1) == Terrain::Sand { 60.0 } else { 0.0 };
                score(a).total_cmp(&score(b))
            });
            if let Some(shore) = best {
                let tr = land.sites[town].radius_m * 1.2;
                if let Some(path) = gr.route(rp, shore, &|k| net[k] != 0 && dist(gr.centre(k), tc) < tr, f32::INFINITY) {
                    let hit = net[*path.last().unwrap()];
                    let mut path = path;
                    path.reverse();
                    let start = if hit == SITE_MARK { RoadEnd::Site(town as u16) } else { RoadEnd::Road(hit - 1) };
                    let id = pre + raw.len() as u32;
                    for &k in &path {
                        mark_net(&mut net, n, k, id + 1);
                    }
                    let w = self.style(SiteKind::Town).map_or(3.0, |s| s.trunk_m);
                    raw.push((path, start, RoadEnd::Shore, w, RoadClass::Trunk));
                }
            }
        }
        // Footpaths up to the cave mouths.
        if rp.cave_path_m > 0.0 {
            for (si, s) in land.sites.iter().enumerate() {
                if s.kind != SiteKind::Cave {
                    continue;
                }
                let from = gr.cell((s.x, s.y));
                if !gr.cost[from].is_finite() {
                    continue;
                }
                if let Some(mut path) = gr.route(rp, from, &|k| net[k] != 0 || foot[k] != 0, rp.cave_path_m * 6.0) {
                    if path.len() as f32 * gr.g > rp.cave_path_m {
                        continue;
                    }
                    let last = *path.last().unwrap();
                    let hit = if net[last] != 0 { net[last] } else { foot[last] };
                    path.reverse();
                    let start = if hit == SITE_MARK { RoadEnd::Site(town as u16) } else { RoadEnd::Road(hit - 1) };
                    let id = pre + raw.len() as u32;
                    for &k in &path {
                        mark_net(&mut foot, n, k, id + 1);
                    }
                    raw.push((path, start, RoadEnd::Site(si as u16), rp.path_width_m, RoadClass::Path));
                }
            }
        }
        // Smooth each path; snap its junction onto the road it joins.
        for (cells, start, end, width, class) in raw {
            let mut pts: Vec<V2> = cells.iter().map(|&k| gr.centre(k)).collect();
            if let RoadEnd::Site(i) = end {
                *pts.last_mut().unwrap() = (land.sites[i as usize].x, land.sites[i as usize].y);
            }
            if let RoadEnd::Site(i) = start {
                pts[0] = (land.sites[i as usize].x, land.sites[i as usize].y);
            }
            // Smooth away the grid's small zigzags, but never into still water or a cliff the
            // raw path went round: such points go back onto the raw path.
            let bad = |p: V2| {
                let t = land.map.at(p.0, p.1);
                (t == Terrain::Water && !gr.river[gr.cell(p)]) || (t == Terrain::Rock && !gr.cost[gr.cell(p)].is_finite())
            };
            let pin = |q: Vec<V2>| -> Vec<V2> { q.into_iter().map(|p| if bad(p) { nearest_on(&pts, p).3 } else { p }).collect() };
            let mut q = rdp(&pts, gr.g * 1.1);
            q = resample(&q, gr.g * 2.0);
            for _ in 0..3 {
                q = pin(chaikin(&q));
            }
            // A moving average over a few road widths irons out switchbacks shorter than the
            // road is wide.
            let fine = resample(&q, 1.0);
            let win = (width * 3.0).clamp(6.0, 20.0) as isize;
            let avg: Vec<V2> = (0..fine.len() as isize)
                .map(|i| {
                    let r = win.min(i).min(fine.len() as isize - 1 - i);
                    let (mut sx, mut sy) = (0.0, 0.0);
                    for j in i - r..=i + r {
                        sx += fine[j as usize].0;
                        sy += fine[j as usize].1;
                    }
                    let k = (2 * r + 1) as f32;
                    (sx / k, sy / k)
                })
                .collect();
            let mut pts = rdp(&pin(avg), 0.25);
            if let RoadEnd::Road(parent) = start {
                let (_, _, _, q) = nearest_on(&self.roads[parent as usize].points, pts[0]);
                pts[0] = q;
            }
            let pts = dedup(pts);
            if pts.len() < 2 {
                continue;
            }
            let l = *cumlen(&pts).last().unwrap();
            self.push_road(Road { class, settlement: None, points: pts, heights: Vec::new(), width_m: width, crossfall: Vec::new(), ends: [start, end], length_m: l });
        }
    }

    fn find_crossings(&mut self) {
        let land = self.land;
        let rp = &self.p.roads;
        for (ri, r) in self.roads.iter().enumerate() {
            let cl = cumlen(&r.points);
            let total = *cl.last().unwrap();
            let river_ish = |p: V2| match land.map.at(p.0, p.1) {
                Terrain::Water => true,
                Terrain::Sand => land.rivers.iter().any(|rv| {
                    let (d, i, _, _) = nearest_on(&rv.points, p);
                    d < rv.width_m[i] * 0.5 + 0.5
                }),
                _ => false,
            };
            let mut s = 0.0;
            let mut open: Option<(f32, bool)> = None;
            while s <= total + 0.25 {
                let p = at_s(&r.points, &cl, s).0;
                let wet = s <= total && river_ish(p);
                let water = land.map.at(p.0, p.1) == Terrain::Water;
                match (&mut open, wet) {
                    (None, true) => open = Some((s, !water)),
                    (Some((_, ford)), true) => *ford |= !water,
                    (Some((s0, ford)), false) => {
                        let (s0, ford) = (*s0, *ford);
                        let span = s - s0;
                        let (at, along) = at_s(&r.points, &cl, (s0 + s) * 0.5);
                        let kind = if ford || span <= rp.bridge_m { CrossingKind::Ford } else { CrossingKind::Bridge };
                        self.crossings.push(Crossing { road: ri as u32, kind, at, along, span_m: span, water_m: land.water_level(at.0, at.1) });
                        open = None;
                    }
                    _ => {}
                }
                s += 0.5;
            }
        }
    }

    // -------------------------------------------------------------------------------------
    // Streets

    fn lay_out_streets(&mut self) {
        let land = self.land;
        for (si, site) in land.sites.iter().enumerate() {
            if site.kind == SiteKind::Cave {
                continue;
            }
            if site.ward || site.plan.is_some() {
                continue;
            }
            let Some(style) = self.site_style(si) else { continue };
            self.lay_out_settlement(si, style);
        }
    }

    fn lay_out_settlement(&mut self, si: usize, st: &'a Style) {
        let land = self.land;
        let site = &land.sites[si];
        let idx = self.settlements.len() as u16;
        let mut rng = Rng(self.seed ^ (si as u64).wrapping_mul(0x9E37));
        let c0 = (site.x, site.y);
        // Where roads arrive: the plaza stretches along them.
        let arriving: Vec<u32> = (0..self.roads.len() as u32).filter(|&r| self.roads[r as usize].ends.contains(&RoadEnd::Site(si as u16))).collect();
        let mut s2 = (0.0, 0.0);
        for &r in &arriving {
            let pts = &self.roads[r as usize].points;
            let far = pts.iter().rev().find(|q| dist(**q, c0) > st.plaza_m[0]).or(pts.first()).copied().unwrap();
            let a = (far.1 - c0.1).d_atan2(far.0 - c0.0);
            s2 = add(s2, ((2.0 * a).d_cos(), (2.0 * a).d_sin()));
        }
        let axis = if len(s2) > 0.1 {
            s2.1.d_atan2(s2.0) * 0.5
        } else {
            // Along the contour when nothing arrives.
            let g = self.grad(c0, 4.0);
            g.1.d_atan2(g.0) + std::f32::consts::FRAC_PI_2
        };
        // The plaza: an irregular oval on clean ground near the centre.
        let mut plaza = Vec::new();
        let mut centre = c0;
        'find: for ring in 0..6 {
            for a in 0..(if ring == 0 { 1 } else { 8 }) {
                let off = ring as f32 * st.plaza_m[1] * 0.35;
                let ang = a as f32 * std::f32::consts::TAU / 8.0;
                let c = add(c0, (ang.d_cos() * off, ang.d_sin() * off));
                let poly = self.oval(c, axis, st.plaza_m[0] * 0.5, st.plaza_m[1] * 0.5, &mut rng);
                if self.clean_poly(&poly, 3.0) {
                    centre = c;
                    plaza = poly;
                    break 'find;
                }
            }
        }
        if plaza.is_empty() {
            plaza = self.oval(c0, axis, st.plaza_m[0] * 0.4, st.plaza_m[1] * 0.4, &mut rng);
        }
        let plaza_floor = {
            let mut s = 0.0;
            let mut n = 0.0;
            for q in plaza.iter().chain(std::iter::once(&centre)) {
                s += land.height(q.0, q.1);
                n += 1.0;
            }
            // On terraces the square is one of them, above any water beside it.
            match self.zone(si) {
                Some(z) => {
                    let wet = plaza.iter().chain(std::iter::once(&centre)).filter(|q| land.sd_at(q.0, q.1) < 8.0).map(|q| land.water_level(q.0, q.1) + 0.3).fold(f32::MIN, f32::max);
                    let mut lvl = z.snap(s / n);
                    while lvl < wet {
                        lvl += z.step;
                    }
                    lvl
                }
                None => s / n,
            }
        };
        // Lanes on terraces stop short of a drop (stairs continue them); main streets ramp.
        let drop = self.zone(si).map_or(0.0, |z| z.step * 0.5);
        // Edge of the built-up area, per direction.
        let r_max = site.radius_m * st.bound;
        let bound = self.boundary(centre, len(sub(plaza[0], centre)).max(st.plaza_m[0] * 0.5) + 10.0 * site.scale, r_max, st.relief_m, &mut rng);
        let mut wall_ring = None;
        let mut wall_corners: Vec<V2> = Vec::new();
        let mut inner = bound.clone();
        let mut bound = bound;
        if let Some(ws) = &st.wall {
            // Straight curtains between corners about `tower_m` / 1.7 apart, round a lobed edge.
            let ph = rng.f() * 10.0;
            let lobed: Vec<f32> = (0..bound.len()).map(|i| bound[i] * (1.0 - 0.09 * (0.5 + 0.5 * value(self.seed ^ 0xC3, ph + i as f32 / bound.len() as f32 * 3.0, 0.2)))).collect();
            let mean = lobed.iter().sum::<f32>() / lobed.len() as f32;
            let nv = ((std::f32::consts::TAU * mean) / (ws.tower_m / 1.7)).round().max(6.0) as usize;
            let a0 = rng.f() * std::f32::consts::TAU;
            let corners: Vec<V2> = (0..nv)
                .map(|i| {
                    let a = a0 + (i as f32 + (rng.f() - 0.5) * 0.4) / nv as f32 * std::f32::consts::TAU;
                    let d = (a.d_cos(), a.d_sin());
                    add(centre, mul(d, radial_at(&lobed, centre, add(centre, d))))
                })
                .collect();
            let ring: Vec<V2> = (0..nv)
                .flat_map(|k| {
                    let (a, b) = (corners[k], corners[(k + 1) % nv]);
                    let m = (dist(a, b) / 6.0).ceil().max(1.0) as usize;
                    (0..m).map(move |j| add(a, mul(sub(b, a), j as f32 / m as f32)))
                })
                .collect();
            // The edge is now the wall itself.
            bound = (0..bound.len())
                .map(|i| {
                    let a = i as f32 / bound.len() as f32 * std::f32::consts::TAU;
                    let far = add(centre, (a.d_cos() * 1e4, a.d_sin() * 1e4));
                    (0..nv).find_map(|k| seg_intersect(centre, far, corners[k], corners[(k + 1) % nv]).map(|(t, _)| t * 1e4)).unwrap_or(bound[i])
                })
                .collect();
            inner = bound.iter().map(|r| r - ws.lane_offset_m + st.lane_m * 0.5).collect();
            wall_corners = corners;
            self.walls.push((idx, ws.thickness_m * 0.5, ring.clone()));
            wall_ring = Some(ring);
        }
        // Clip arriving roads at the plaza edge.
        for &r in &arriving {
            let road = &mut self.roads[r as usize];
            let at_end = road.ends[1] == RoadEnd::Site(si as u16);
            if !at_end {
                road.points.reverse();
                road.ends.swap(0, 1);
            }
            let pts = &mut road.points;
            // The plaza may sit a little off the site's centre: aim the road at the plaza.
            if !poly_contains(&plaza, *pts.last().unwrap()) {
                pts.push(centre);
            }
            while pts.len() > 2 && poly_contains(&plaza, pts[pts.len() - 2]) {
                pts.pop();
            }
            let n = pts.len();
            let (a, b) = (pts[n - 2], pts[n - 1]);
            if poly_contains(&plaza, b) {
                let m = plaza.len();
                for i in 0..m {
                    if let Some((t, _)) = seg_intersect(a, b, plaza[i], plaza[(i + 1) % m]) {
                        pts[n - 1] = add(a, mul(sub(b, a), t));
                        break;
                    }
                }
            }
            road.ends[1] = RoadEnd::Plaza(idx);
            road.length_m = *cumlen(&road.points).last().unwrap();
        }
        // Inside a wall, the arriving roads become main streets from the gate to the plaza.
        let mut streets: Vec<u32> = Vec::new();
        for &r in &arriving {
            let mut inner_id = r;
            if let Some(ring) = &wall_ring {
                if let Some((ip, seg)) = last_crossing(&self.roads[r as usize].points, ring) {
                    let road = &self.roads[r as usize];
                    let mut inside: Vec<V2> = vec![ip];
                    inside.extend_from_slice(&road.points[seg + 1..]);
                    let mut outside: Vec<V2> = road.points[..=seg].to_vec();
                    outside.push(ip);
                    let (inside, outside) = (dedup(inside), dedup(outside));
                    if inside.len() >= 2 && outside.len() >= 2 {
                        let new_id = self.roads.len() as u32;
                        let lin = *cumlen(&inside).last().unwrap();
                        let lout = *cumlen(&outside).last().unwrap();
                        let start = self.roads[r as usize].ends[0];
                        self.roads[r as usize].points = outside;
                        self.roads[r as usize].ends = [start, RoadEnd::Road(new_id)];
                        self.roads[r as usize].length_m = lout;
                        self.push_road(Road { class: RoadClass::Street, settlement: Some(idx), points: inside, heights: Vec::new(), width_m: st.street_m, crossfall: Vec::new(), ends: [RoadEnd::Road(r), RoadEnd::Plaza(idx)], length_m: lin });
                        inner_id = new_id;
                    }
                }
            }
            if inner_id != r || st.wall.is_none() {
                streets.push(inner_id);
            }
        }
        // Main streets bend gently between the edge and the plaza instead of running dead
        // straight; the bend fades out at both ends.
        for &r in &streets {
            let walled = st.wall.is_some();
            let pts = self.roads[r as usize].points.clone();
            let cl = cumlen(&pts);
            let total = *cl.last().unwrap();
            // Bend only the stretch inside the edge.
            let s0 = if walled { 0.0 } else { (0..pts.len()).find(|&i| dist(pts[i], centre) < radial_at(&bound, centre, pts[i])).map_or(total, |i| cl[i]) };
            let l = total - s0;
            if l < st.street_m * 6.0 {
                continue;
            }
            let (a1, a2) = ((rng.f() - 0.5) * 0.2 * l, (rng.f() - 0.5) * 0.08 * l);
            let fine = resample(&pts, (st.street_m * 0.8).max(0.5));
            let fcl = cumlen(&fine);
            let bent: Vec<V2> = (0..fine.len())
                .map(|i| {
                    if fcl[i] <= s0 {
                        return fine[i];
                    }
                    let t = (fcl[i] - s0) / l;
                    let tan = norm(sub(fine[(i + 1).min(fine.len() - 1)], fine[i.saturating_sub(1)]));
                    let off = a1 * (std::f32::consts::PI * t).d_sin() + a2 * (std::f32::consts::TAU * t).d_sin();
                    add(fine[i], mul(perp(tan), off))
                })
                .collect();
            let ok = bent.iter().all(|q| land.map.at(q.0, q.1).walkable() && land.sd_at(q.0, q.1) >= 2.0 && dist(*q, centre) < r_max + st.outskirts_m);
            if ok {
                let bent = rdp(&bent, 0.15);
                self.roads[r as usize].length_m = *cumlen(&bent).last().unwrap();
                self.roads[r as usize].points = bent;
                self.add_road_index(r, &self.roads[r as usize].clone());
            }
        }
        // More main streets where the arriving roads leave a wide gap.
        let mut exits: Vec<f32> = streets.iter().map(|&r| {
            let pts = &self.roads[r as usize].points;
            let q = pts.iter().rev().find(|q| dist(**q, centre) > st.plaza_m[0] * 0.8).or(pts.first()).copied().unwrap();
            (q.1 - centre.1).d_atan2(q.0 - centre.0)
        }).collect();
        let mut tries = 0;
        while (exits.len() as u32) < st.radials && tries < 6 {
            tries += 1;
            let dir_a = if exits.is_empty() {
                axis + if rng.f() < 0.5 { 0.0 } else { std::f32::consts::PI }
            } else {
                let mut s = exits.clone();
                s.sort_by(f32::total_cmp);
                let mut best = (0.0, 0.0);
                for i in 0..s.len() {
                    let (a, b) = (s[i], if i + 1 < s.len() { s[i + 1] } else { s[0] + std::f32::consts::TAU });
                    if b - a > best.0 {
                        best = (b - a, (a + b) * 0.5);
                    }
                }
                if best.0 < 1.2 {
                    break;
                }
                best.1 + (rng.f() - 0.5) * 0.3
            };
            let dir = (dir_a.d_cos(), dir_a.d_sin());
            let start = self.plaza_exit(&plaza, centre, dir);
            let reach = r_max + st.outskirts_m * 0.5;
            let opts = Trace { step: st.street_m.max(st.lane_spacing_m / 9.0), max_len: reach, contour: 0.3, circle: 0.0, radial: 1.0, wander: st.wander * 1.3, hw: st.street_m * 0.5, sep: st.lane_sep_m * 0.6, centre, limit: None, parent: None, seed: rng.f().to_bits() as u64, settlement: idx, plaza: &plaza, drop: 0.0, zone: None };
            exits.push(dir_a);
            if let Some((pts, end)) = self.trace(start, dir, &opts) {
                if cumlen(&pts).last().copied().unwrap_or(0.0) > st.lane_m_min * 2.0 {
                    let l = *cumlen(&pts).last().unwrap();
                    let cls = if st.lane_class == RoadClass::Path { RoadClass::Path } else { RoadClass::Street };
                    let id = self.push_road(Road { class: cls, settlement: Some(idx), points: pts, heights: Vec::new(), width_m: st.street_m, crossfall: Vec::new(), ends: [RoadEnd::Plaza(idx), end], length_m: l });
                    streets.push(id);
                }
            }
        }
        // The lane inside the wall.
        let mut parents: Vec<(u32, u32, bool)> = streets.iter().map(|&r| (r, 0, false)).collect();
        if let (Some(ws), Some(_)) = (&st.wall, &wall_ring) {
            let ring = ring_points(centre, &bound.iter().map(|r| r - ws.lane_offset_m).collect::<Vec<_>>(), 1.0);
            let mut closed = ring.clone();
            closed.push(ring[0]);
            let ring = chaikin(&closed);
            let ring = &ring[..ring.len() - 1];
            let good: Vec<bool> = ring.iter().map(|q| land.map.at(q.0, q.1).walkable() && self.clear_of_water(*q, 2.0) && poly_outside(&plaza, *q) > 4.0).collect();
            let m = ring.len();
            let mut pieces: Vec<Vec<V2>> = Vec::new();
            match good.iter().position(|g| !g) {
                None => pieces.push(ring.iter().chain(std::iter::once(&ring[0])).cloned().collect()),
                Some(bad) => {
                    let mut cur = Vec::new();
                    for o in 1..=m {
                        let i = (bad + o) % m;
                        if good[i] {
                            cur.push(ring[i]);
                        } else if !cur.is_empty() {
                            pieces.push(std::mem::take(&mut cur));
                        }
                    }
                    if !cur.is_empty() {
                        pieces.push(cur);
                    }
                }
            }
            for pts in pieces {
                let pts = dedup(pts);
                if pts.len() >= 2 && cumlen(&pts).last().copied().unwrap_or(0.0) > st.lane_m_min {
                    let l = *cumlen(&pts).last().unwrap();
                    let id = self.push_road(Road { class: RoadClass::Lane, settlement: Some(idx), points: pts, heights: Vec::new(), width_m: st.lane_m, crossfall: Vec::new(), ends: [RoadEnd::Free, RoadEnd::Free], length_m: l });
                    parents.push((id, 1, true));
                }
            }
        }
        // Lanes branching off the streets, bending with the ground.
        let limit = inner.clone();
        let mut qi = 0;
        while qi < parents.len() {
            let (pid, depth, inward) = parents[qi];
            qi += 1;
            if depth >= st.depth {
                continue;
            }
            let (ppts, phw) = (self.roads[pid as usize].points.clone(), self.roads[pid as usize].width_m * 0.5);
            let cl = cumlen(&ppts);
            let total = *cl.last().unwrap();
            let mut s = st.lane_spacing_m * rng.range([0.3, 0.8]);
            while s < total - st.lane_spacing_m * 0.2 {
                let (p, t) = at_s(&ppts, &cl, s);
                let zone = dist(p, centre) / radial_at(&limit, centre, p);
                if poly_outside(&plaza, p) > st.plaza_m[1] * 0.3 && (zone < 0.97 || inward) {
                    for side in [1.0f32, -1.0] {
                        let n = mul(perp(t), side);
                        if inward && dot(n, sub(centre, p)) < 0.0 {
                            continue;
                        }
                        if rng.f() > st.branch {
                            continue;
                        }
                        let start = add(p, mul(n, phw + 0.3));
                        let opts = Trace { step: (st.lane_spacing_m / 10.0).max(0.6), max_len: st.lane_m_max, contour: st.contour, circle: st.circle, radial: 0.0, wander: st.wander, hw: st.lane_m * 0.5, sep: st.lane_sep_m, centre, limit: Some(&limit), parent: Some(pid), seed: rng.f().to_bits() as u64, settlement: idx, plaza: &plaza, drop, zone: self.zone(si) };
                        if let Some((mut pts, end)) = self.trace(start, n, &opts) {
                            let l = cumlen(&pts).last().copied().unwrap_or(0.0);
                            let joins = matches!(end, RoadEnd::Road(_) | RoadEnd::Plaza(_));
                            if l >= st.lane_m_min || (joins && l > st.lane_m * 3.0) {
                                pts[0] = p;
                                let l = *cumlen(&pts).last().unwrap();
                                let id = self.push_road(Road { class: st.lane_class, settlement: Some(idx), points: pts, heights: Vec::new(), width_m: st.lane_m, crossfall: Vec::new(), ends: [RoadEnd::Road(pid), end], length_m: l });
                                parents.push((id, depth + 1, false));
                            }
                        }
                    }
                }
                s += st.lane_spacing_m * rng.range([0.75, 1.3]);
            }
        }
        // Settlement streets for its record.
        let mine: Vec<u32> = (0..self.roads.len() as u32).filter(|&r| self.roads[r as usize].settlement == Some(idx) || self.roads[r as usize].ends.contains(&RoadEnd::Plaza(idx))).collect();
        let radius = bound.iter().sum::<f32>() / bound.len() as f32;
        let wall = match (&st.wall, wall_ring) {
            (Some(ws), Some(ring)) => Some(Wall { ring, corners: wall_corners, runs: Vec::new(), gates: Vec::new(), height_m: ws.height_m, thickness_m: ws.thickness_m }),
            _ => None,
        };
        self.settlements.push(Settlement {
            site: si as u16,
            kind: site.kind,
            style: st.buildings.clone(),
            centre,
            scale: site.scale,
            radius_m: radius,
            plaza: Plaza { centre, points: plaza, floor_m: plaza_floor, paved: st.paved },
            wall,
            lots: (0, 0),
            landmark: None,
            roads: mine,
            terrace_m: self.zone(si).map_or(0.0, |z| z.step),
            planned: false,
        });
        self.bounds.push((bound, inner));
    }

    fn oval(&self, c: V2, axis: f32, a: f32, b: f32, rng: &mut Rng) -> Vec<V2> {
        let n = 10;
        let ph = rng.f() * 10.0;
        (0..n)
            .map(|i| {
                let t = i as f32 / n as f32 * std::f32::consts::TAU + (rng.f() - 0.5) * 0.25;
                let (ct, stt) = ((t).d_cos(), (t).d_sin());
                let r = 1.0 / ((ct / a).powi(2) + (stt / b).powi(2)).sqrt() * (1.0 + 0.14 * value(self.seed ^ 0x9A, ph + t * 1.3, 0.5));
                add(c, rot((ct * r, stt * r), axis))
            })
            .collect()
    }

    fn clean_poly(&self, poly: &[V2], water_m: f32) -> bool {
        let lo = poly.iter().fold((f32::MAX, f32::MAX), |m, v| (m.0.min(v.0), m.1.min(v.1)));
        let hi = poly.iter().fold((f32::MIN, f32::MIN), |m, v| (m.0.max(v.0), m.1.max(v.1)));
        let mut y = lo.1;
        while y <= hi.1 {
            let mut x = lo.0;
            while x <= hi.0 {
                if poly_contains(poly, (x, y)) {
                    let t = self.land.map.at(x, y);
                    if !t.walkable() || !self.clear_of_water((x, y), water_m) {
                        return false;
                    }
                }
                x += 1.0;
            }
            y += 1.0;
        }
        true
    }

    fn clear_of_water(&self, p: V2, m: f32) -> bool {
        self.land.sd_at(p.0, p.1) >= m
    }

    /// Edge radius per direction (72 directions): out to `r_max`, stopping short of water, rock
    /// and ground more than `relief` from the centre's.
    fn boundary(&self, c: V2, r_min: f32, r_max: f32, relief: f32, rng: &mut Rng) -> Vec<f32> {
        let land = self.land;
        let h0 = land.height(c.0, c.1);
        let n = 72;
        let raw: Vec<f32> = (0..n)
            .map(|i| {
                let a = i as f32 / n as f32 * std::f32::consts::TAU;
                let d = (a.d_cos(), a.d_sin());
                let mut r = r_min;
                while r < r_max {
                    let p = add(c, mul(d, r + 3.0));
                    let t = land.map.at(p.0, p.1);
                    if !t.walkable() || land.sd_at(p.0, p.1) < 3.0 || (land.height(p.0, p.1) - h0).abs() > relief {
                        break;
                    }
                    r += 2.0;
                }
                r.min(r_max)
            })
            .collect();
        let ph = rng.f() * 20.0;
        (0..n)
            .map(|i| {
                let avg: f32 = (-3i32..=3).map(|d| raw[((i as i32 + d).rem_euclid(n as i32)) as usize]).sum::<f32>() / 7.0;
                let wob = 1.0 + 0.05 * value(self.seed ^ 0xB0, ph + i as f32 * 0.25, 1.5);
                (avg.min(raw[i] + 6.0) * wob).clamp(r_min, r_max)
            })
            .collect()
    }

    fn plaza_exit(&self, plaza: &[V2], c: V2, dir: V2) -> V2 {
        let far = add(c, mul(dir, 1e4));
        let m = plaza.len();
        for i in 0..m {
            if let Some((t, _)) = seg_intersect(c, far, plaza[i], plaza[(i + 1) % m]) {
                return add(c, mul(sub(far, c), t));
            }
        }
        c
    }

    fn grad(&self, p: V2, e: f32) -> V2 {
        let h = |x: f32, y: f32| self.land.height(x, y);
        ((h(p.0 + e, p.1) - h(p.0 - e, p.1)) / (2.0 * e), (h(p.0, p.1 + e) - h(p.0, p.1 - e)) / (2.0 * e))
    }

    /// Walk a new street from `start`, steering by the ground, until it meets another street,
    /// the plaza, the edge, water or rock.
    fn trace(&self, start: V2, dir: V2, o: &Trace) -> Option<(Vec<V2>, RoadEnd)> {
        let land = self.land;
        let mut pts = vec![start];
        let mut p = start;
        let mut d = norm(dir);
        let mut s = 0.0;
        let mut near = Vec::new();
        let mut end = RoadEnd::Free;
        while s < o.max_len {
            // On terraces the ground is flat: steer by the hill they step down.
            let g = match o.zone {
                Some(z) => z.smooth(p).1,
                None => self.grad(p, o.step.max(1.5)),
            };
            let slope = len(g);
            let mut want = mul(d, 1.6);
            if slope > 1e-3 {
                let mut tc = norm(perp(g));
                if dot(tc, d) < 0.0 {
                    tc = mul(tc, -1.0);
                }
                want = add(want, mul(tc, o.contour * smoothstep(0.015, 0.12, slope) * 2.0));
            }
            let rc = sub(p, o.centre);
            if len(rc) > 1.0 {
                let mut tc = norm(perp(rc));
                if dot(tc, d) < 0.0 {
                    tc = mul(tc, -1.0);
                }
                want = add(want, mul(tc, o.circle));
                want = add(want, mul(norm(rc), o.radial));
            }
            let turn = o.wander * value(o.seed, s / (o.step * 7.0), 0.37) * 0.35;
            d = norm(rot(norm(want), turn));
            // Steer off ground too steep to climb.
            let grade = |dd: V2| (land.height(p.0 + dd.0 * o.step, p.1 + dd.1 * o.step) - land.height(p.0, p.1)).abs() / o.step;
            if grade(d) > 0.18 {
                let mut best = (grade(d), d);
                for a in [0.25f32, -0.25, 0.5, -0.5, 0.8, -0.8] {
                    let dd = rot(d, a);
                    let gg = grade(dd) + a.abs() * 0.05;
                    if gg < best.0 {
                        best = (gg, dd);
                    }
                }
                d = best.1;
            }
            if o.radial > 0.0 && s > o.step * 3.0 && dot(d, norm(sub(p, o.centre))) < -0.1 {
                // A main street that turns back toward the centre has run out of room.
                break;
            }
            let q = add(p, mul(d, o.step));
            let t = land.map.at(q.0, q.1);
            if !t.walkable() || land.sd_at(q.0, q.1) < 2.0 + o.hw {
                break;
            }
            if o.drop > 0.0 && (land.height(q.0, q.1) - land.height(p.0, p.1)).abs() > o.drop {
                break;
            }
            if let Some(lim) = o.limit {
                if dist(q, o.centre) > radial_at(lim, o.centre, q) {
                    break;
                }
            }
            if poly_contains(o.plaza, q) && s > o.step * 2.0 {
                let m = o.plaza.len();
                let mut hitp = q;
                for i in 0..m {
                    if let Some((tt, _)) = seg_intersect(p, q, o.plaza[i], o.plaza[(i + 1) % m]) {
                        hitp = add(p, mul(sub(q, p), tt));
                    }
                }
                pts.push(hitp);
                end = RoadEnd::Plaza(o.settlement);
                break;
            }
            // Meeting another street: join it; running alongside one: stop short.
            let reach = o.sep.max(o.hw * 4.0);
            self.road_b.query((q.0 - reach, q.1 - reach), (q.0 + reach, q.1 + reach), &mut near);
            let mut joined = false;
            let mut close = false;
            for &rid in &near {
                let r = &self.roads[rid as usize];
                let (dd, si, _, np) = nearest_on(&r.points, q);
                let own_start = Some(rid) == o.parent && s < o.sep * 1.5;
                if own_start {
                    continue;
                }
                if dd < r.width_m * 0.5 + o.hw + o.step * 0.6 {
                    pts.push(np);
                    end = RoadEnd::Road(rid);
                    joined = true;
                    break;
                }
                let tan = norm(sub(r.points[si + 1], r.points[si]));
                if dd < o.sep && dot(tan, d).abs() > 0.8 {
                    close = true;
                }
            }
            if joined {
                break;
            }
            if close {
                // Trim back out of the parallel street's way.
                break;
            }
            pts.push(q);
            p = q;
            s += o.step;
        }
        if pts.len() < 2 {
            return None;
        }
        let pts = dedup(chaikin(&pts));
        (pts.len() >= 2).then_some((pts, end))
    }

    /// Re-point junction ends at the road they now lie on (splits move them).
    fn fix_junctions(&mut self) {
        for ri in 0..self.roads.len() {
            for e in 0..2 {
                let RoadEnd::Road(o) = self.roads[ri].ends[e] else { continue };
                let q = if e == 0 { self.roads[ri].points[0] } else { *self.roads[ri].points.last().unwrap() };
                let on = |r: &Road| nearest_on(&r.points, q).0 <= r.width_m * 0.5 + 1.0;
                if on(&self.roads[o as usize]) {
                    continue;
                }
                let (d, _, _, np) = nearest_on(&self.roads[o as usize].points, q);
                if d < 25.0 {
                    // The road it joins was bent: move the junction onto it.
                    if e == 0 {
                        self.roads[ri].points[0] = np;
                    } else {
                        *self.roads[ri].points.last_mut().unwrap() = np;
                    }
                    continue;
                }
                // The road it joined was clipped at a plaza: end at that plaza instead.
                if let Some(si) = self.settlements.iter().position(|s| poly_outside(&s.plaza.points, q) < 2.0) {
                    let plaza = self.settlements[si].plaza.points.clone();
                    let pts = &mut self.roads[ri].points;
                    if e == 0 {
                        pts.reverse();
                    }
                    while pts.len() > 2 && poly_contains(&plaza, pts[pts.len() - 2]) {
                        pts.pop();
                    }
                    let n = pts.len();
                    let (a, b) = (pts[n - 2], pts[n - 1]);
                    let m = plaza.len();
                    for i in 0..m {
                        if let Some((t, _)) = seg_intersect(a, b, plaza[i], plaza[(i + 1) % m]) {
                            pts[n - 1] = add(a, mul(sub(b, a), t));
                            break;
                        }
                    }
                    if e == 0 {
                        pts.reverse();
                    }
                    self.roads[ri].ends[e] = RoadEnd::Plaza(si as u16);
                    continue;
                }
                // Else join the nearest road and move the end onto it.
                let mut near = Vec::new();
                self.road_b.query((q.0 - 25.0, q.1 - 25.0), (q.0 + 25.0, q.1 + 25.0), &mut near);
                let best = near.iter().filter(|&&r| r as usize != ri).map(|&r| (r, nearest_on(&self.roads[r as usize].points, q))).min_by(|a, b| a.1 .0.total_cmp(&b.1 .0));
                if let Some((b, (_, _, _, np))) = best {
                    self.roads[ri].ends[e] = RoadEnd::Road(b);
                    if e == 0 {
                        self.roads[ri].points[0] = np;
                    } else {
                        *self.roads[ri].points.last_mut().unwrap() = np;
                    }
                }
            }
        }
    }

    // -------------------------------------------------------------------------------------
    // Profiles

    fn centre_h(&self, rid: u32, p: V2) -> f32 {
        let r = &self.roads[rid as usize];
        let (_, i, u, _) = nearest_on(&r.points, p);
        lerp(r.heights[i], r.heights[i + 1], u)
    }

    fn profiles(&mut self) {
        let land = self.land;
        let rp = &self.p.roads;
        for ri in 0..self.roads.len() {
            // A planned settlement's streets lie on its ground as written.
            if self.roads[ri].settlement.is_some_and(|s| self.settlements.get(s as usize).is_some_and(|x| x.planned)) {
                continue;
            }
            // Resample to ~3 m, keeping the ends.
            let pts = {
                let r = &self.roads[ri];
                let step = (r.width_m * 0.8).clamp(1.0, 3.0);
                dedup(resample(&r.points, step))
            };
            let natural: Vec<f32> = pts.iter().map(|q| land.height(q.0, q.1)).collect();
            let cl = cumlen(&pts);
            // Moving average along the road.
            let win = rp.smooth_m * self.roads[ri].width_m.max(2.0) / 4.0;
            let mut h: Vec<f32> = (0..pts.len())
                .map(|i| {
                    let (mut s, mut w) = (natural[i], 1.0);
                    for dir in [-1isize, 1] {
                        let mut j = i as isize + dir;
                        while j >= 0 && (j as usize) < pts.len() {
                            let d = (cl[j as usize] - cl[i]).abs();
                            if d >= win {
                                break;
                            }
                            let k = 1.0 - d / win;
                            s += natural[j as usize] * k;
                            w += k;
                            j += dir;
                        }
                    }
                    s / w
                })
                .collect();
            // Pins: ends at plazas and junctions, and crossings of earlier roads.
            let mut pins: Vec<(f32, f32)> = Vec::new();
            let ends = self.roads[ri].ends;
            for (e, end) in ends.iter().enumerate() {
                let s_at = if e == 0 { 0.0 } else { cl[cl.len() - 1] };
                let q = if e == 0 { pts[0] } else { pts[pts.len() - 1] };
                match *end {
                    RoadEnd::Plaza(si) => pins.push((s_at, self.settlements_floor(si))),
                    RoadEnd::Road(o) if (o as usize) < ri => pins.push((s_at, self.centre_h(o, q))),
                    _ => {}
                }
            }
            let mut near = Vec::new();
            for i in 0..pts.len() - 1 {
                let (a, b) = (pts[i], pts[i + 1]);
                self.road_b.query((a.0.min(b.0), a.1.min(b.1)), (a.0.max(b.0), a.1.max(b.1)), &mut near);
                for &o in &near {
                    if o as usize >= ri {
                        continue;
                    }
                    let or = &self.roads[o as usize];
                    for j in 0..or.points.len() - 1 {
                        if let Some((t, u)) = seg_intersect(a, b, or.points[j], or.points[j + 1]) {
                            let s = cl[i] + t * (cl[i + 1] - cl[i]);
                            if s > 1.0 && s < cl[cl.len() - 1] - 1.0 {
                                pins.push((s, lerp(or.heights[j], or.heights[j + 1], u)));
                            }
                        }
                    }
                }
            }
            pins.sort_by(|a, b| a.0.total_cmp(&b.0));
            pins.dedup_by(|a, b| (a.0 - b.0).abs() < 2.0);
            if !pins.is_empty() {
                let fall = 30.0f32;
                let delta: Vec<(f32, f32)> = pins.iter().map(|&(s, ph)| (s, ph - sample_profile(&cl, &h, s))).collect();
                for i in 0..h.len() {
                    let s = cl[i];
                    let corr = if s <= delta[0].0 {
                        delta[0].1 * (1.0 - smoothstep(0.0, fall, delta[0].0 - s))
                    } else if s >= delta[delta.len() - 1].0 {
                        let l = delta[delta.len() - 1];
                        l.1 * (1.0 - smoothstep(0.0, fall, s - l.0))
                    } else {
                        let k = delta.iter().position(|d| d.0 > s).unwrap();
                        let (a, b) = (delta[k - 1], delta[k]);
                        lerp(a.1, b.1, (s - a.0) / (b.0 - a.0).max(1e-3))
                    };
                    h[i] += corr;
                }
            }
            // Cross-fall: the slope of the ground across the road, limited.
            let hw = self.roads[ri].width_m * 0.5 + 1.0;
            let cross: Vec<f32> = (0..pts.len() - 1)
                .map(|i| {
                    let m = mul(add(pts[i], pts[i + 1]), 0.5);
                    let n = norm(perp(sub(pts[i + 1], pts[i])));
                    let (l, r) = (add(m, mul(n, hw)), sub(m, mul(n, hw)));
                    ((land.height(l.0, l.1) - land.height(r.0, r.1)) / (2.0 * hw)).clamp(-rp.crossfall, rp.crossfall)
                })
                .collect();
            let r = &mut self.roads[ri];
            r.length_m = cl[cl.len() - 1];
            r.points = pts;
            r.heights = h;
            r.crossfall = cross;
        }
    }

    fn settlements_floor(&self, si: u16) -> f32 {
        self.settlements[si as usize].plaza.floor_m
    }

    fn road_segs(&self) -> Vec<Seg> {
        let rp = &self.p.roads;
        let mut out = Vec::new();
        for (ri, r) in self.roads.iter().enumerate() {
            // A planned settlement's streets do not reshape its ground.
            if r.settlement.is_some_and(|s| self.settlements.get(s as usize).is_some_and(|x| x.planned)) {
                continue;
            }
            let hw = r.width_m * 0.5;
            for i in 0..r.points.len() - 1 {
                out.push(Seg { road: ri as u32, a: r.points[i], b: r.points[i + 1], ha: r.heights[i], hb: r.heights[i + 1], hw, fade: rp.shoulder_m + hw * 0.5, cross: r.crossfall[i] });
            }
        }
        out
    }

    // -------------------------------------------------------------------------------------
    // Lots

    fn place_lots(&mut self) {
        for si in 0..self.settlements.len() {
            if self.land.sites[self.settlements[si].site as usize].ward || self.settlements[si].planned {
                continue;
            }
            let (bound, inner) = self.bounds[si].clone();
            let Some(st) = self.site_style(self.settlements[si].site as usize) else { continue };
            let start = self.lots.len() as u32;
            self.settlement_lots(si as u16, st, &bound, &inner);
            self.settlements[si].lots = (start, self.lots.len() as u32);
        }
    }

    // -------------------------------------------------------------------------------------
    // Stairs between terraces

    /// Stairs down the terraces' drops: first where a lane stops short of one, then along each
    /// drop about `stair_m` apart. Placed before the lots, which keep clear of them.
    fn place_stairs(&mut self) {
        let land = self.land;
        for idx in 0..self.settlements.len() as u16 {
            let si = self.settlements[idx as usize].site as usize;
            let Some(z) = self.zone(si) else { continue };
            let st = self.set_style(idx);
            let style = self.p.kit(&self.settlements[idx as usize].style).to_string();
            let k = self.settlements[idx as usize].scale.max(0.3);
            let mut rng = Rng(self.seed ^ 0x57A1 ^ (idx as u64) << 8);
            let models: Vec<u32> = (0..self.p.buildings.models.len() as u32).filter(|&i| self.p.buildings.models[i as usize].style == style && self.p.buildings.models[i as usize].kind == "stairs").collect();
            // Lane ends that stopped short of a drop.
            let mut wishes: Vec<(V2, V2, u32)> = Vec::new();
            for (rid, rd) in self.roads.iter().enumerate() {
                if rd.settlement != Some(idx) || !matches!(rd.class, RoadClass::Lane | RoadClass::Path) {
                    continue;
                }
                for e in 0..2 {
                    if rd.ends[e] != RoadEnd::Free {
                        continue;
                    }
                    let n = rd.points.len();
                    let (a, b) = if e == 1 { (rd.points[n - 2], rd.points[n - 1]) } else { (rd.points[1], rd.points[0]) };
                    let dir = norm(sub(b, a));
                    let i0 = z.index(b);
                    let mut t = 0.5;
                    while t < 7.0 * k {
                        let q = add(b, mul(dir, t));
                        if z.index(q) != i0 {
                            wishes.push((q, dir, rid as u32));
                            break;
                        }
                        t += 0.5;
                    }
                }
            }
            for (q, _, rid) in wishes {
                self.try_stair(idx, z, q, &models, &mut rng, Some(rid), 10.0 * k);
            }
            if st.stair_m <= 0.0 {
                continue;
            }
            for (_, line) in z.risers(land) {
                let cl = cumlen(&line);
                let total = *cl.last().unwrap();
                let mut s = st.stair_m * rng.range([0.3, 0.7]);
                while s < total {
                    let q = at_s(&line, &cl, s).0;
                    let placed = self.try_stair(idx, z, q, &models, &mut rng, None, st.stair_m * 0.6);
                    s += if placed { st.stair_m } else { 3.0 * k };
                }
            }
        }
    }

    /// A flight of stairs across the drop nearest `q`, square to it, from the lower terrace
    /// up to the next; `lane` is the lane it continues (it may end at the stair's foot or head).
    #[allow(clippy::too_many_arguments)]
    fn try_stair(&mut self, idx: u16, z: &Terrace, q: V2, models: &[u32], rng: &mut Rng, lane: Option<u32>, spacing: f32) -> bool {
        let land = self.land;
        let set = &self.settlements[idx as usize];
        let k = set.scale.max(0.3);
        let (_, g) = z.smooth(q);
        if len(g) < 0.03 {
            return false;
        }
        let down = mul(norm(g), -1.0);
        // The drop's middle along the slope: where `level` is halfway between its plateaus.
        let i_up = z.index(sub(q, mul(down, 3.0 * k)));
        let i_lo = i_up - 1;
        let mid = z.plateau(i_lo) + z.step * 0.5;
        let mut c = None;
        let mut t = -5.0 * k;
        let mut prev = (t, z.level(add(q, mul(down, t))) - mid);
        while t < 5.0 * k {
            t += 0.25;
            let f = z.level(add(q, mul(down, t))) - mid;
            if prev.1 > 0.0 && f <= 0.0 {
                let tt = lerp(prev.0, t, prev.1 / (prev.1 - f));
                c = Some(add(q, mul(down, tt)));
                break;
            }
            prev = (t, f);
        }
        let Some(c) = c else { return false };
        let m = if models.is_empty() { None } else { Some(models[((rng.f() * models.len() as f32) as usize).min(models.len() - 1)]) };
        let (w, d, h, file) = match m {
            Some(m) => {
                let mf = &self.p.buildings.models[m as usize];
                (mf.width_m, mf.depth_m, mf.height_m, Some(mf.file.clone()))
            }
            None => (2.4 * k, z.step / 0.6, z.step + 1.0 * k, None),
        };
        let stair = Prop { settlement: idx, kind: PropKind::Stairs, centre: c, width_m: w, depth_m: d, front: down, yaw: yaw_of(down), floor_m: z.plateau(i_lo), model_file: file, height_m: h };
        let r = stair.rect();
        let foot = add(c, mul(down, d * 0.5 + 1.0 * k));
        let head = sub(c, mul(down, d * 0.5 + 1.0 * k));
        // A whole step between full terraces, on dry walkable ground inside the settlement.
        if z.index(foot) != i_lo || z.index(head) != i_up || z.weight(foot) < 0.98 || z.weight(head) < 0.98 || land.sd_at(foot.0, foot.1) < 14.0 || land.sd_at(head.0, head.1) < 14.0 {
            return false;
        }
        // Level landings: flat terrace for 2 m beyond each end, not the next drop.
        for t in [0.3f32, 1.0, 2.0] {
            let f = add(c, mul(down, d * 0.5 + t * k));
            let h = sub(c, mul(down, d * 0.5 + t * k));
            if (z.level(f) - z.plateau(i_lo)).abs() > 0.05 || (z.level(h) - z.plateau(i_up)).abs() > 0.05 {
                return false;
            }
        }
        let (bound, _) = &self.bounds[idx as usize];
        if dist(c, set.centre) > radial_at(bound, set.centre, c) + 12.0 * k {
            return false;
        }
        for p in r.corners().iter().chain([foot, head].iter()) {
            if !land.map.at(p.0, p.1).walkable() || land.sd_at(p.0, p.1) < 3.0 || poly_outside(&set.plaza.points, *p) < 1.5 * k {
                return false;
            }
        }
        if self.stairs.iter().any(|o| dist(o.centre, c) < spacing) {
            return false;
        }
        for (_, hw, ring) in &self.walls {
            let mm = ring.len();
            if (0..mm).any(|i| r.seg_dist(ring[i], ring[(i + 1) % mm]) < hw + 2.0) {
                return false;
            }
        }
        // Along a drop, a stair joins two streets on different levels: a road near its foot and
        // another near its head.
        if lane.is_none() {
            let nearest = |q: V2| {
                let mut near = Vec::new();
                let r = 16.0 * k;
                self.road_b.query((q.0 - r, q.1 - r), (q.0 + r, q.1 + r), &mut near);
                near.iter().map(|&rid| (nearest_on(&self.roads[rid as usize].points, q).0 - self.roads[rid as usize].width_m * 0.5, rid)).filter(|x| x.0 < r).min_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1))).map(|x| x.1)
            };
            match (nearest(foot), nearest(head)) {
                (Some(a), Some(b)) if a != b => {}
                _ => return false,
            }
        }
        // Clear of roads along the flight (its ends may meet a street); away from ramps, which
        // join the terraces already.
        let mid_r = Rect { hd: (d * 0.5 - 1.2 * k).max(0.3), ..r };
        let mut near = Vec::new();
        self.road_b.query((c.0 - 12.0 * k, c.1 - 12.0 * k), (c.0 + 12.0 * k, c.1 + 12.0 * k), &mut near);
        for &rid in &near {
            let rd = &self.roads[rid as usize];
            let hw = rd.width_m * 0.5;
            for i in 0..rd.points.len() - 1 {
                let (a, b) = (rd.points[i], rd.points[i + 1]);
                if mid_r.seg_dist(a, b) < hw + 0.3 * k {
                    return false;
                }
                if Some(rid) != lane && seg_near(c, a, b).0 < hw + 4.0 * k {
                    return false;
                }
            }
        }
        self.stairs.push(stair);
        true
    }

    fn fp(&self, style: &str, kind: LotKind) -> (f32, f32) {
        let id = self.p.styles.iter().find(|s| s.buildings == style).and_then(|s| s.model_kind(kind)).or(kind.model());
        let kit = self.p.kit(style);
        match id.and_then(|id| self.p.buildings.kinds.iter().find(|f| f.style == kit && f.kind == id)) {
            Some(f) => (f.width_m, f.depth_m),
            None => (4.0, 4.0),
        }
    }

    fn models(&self, style: &str, kind: LotKind) -> &[u32] {
        self.catalog.iter().find(|c| c.0 == style && c.1 == kind).map_or(&[], |c| &c.2)
    }

    /// A model of the kind, at random among those no wider than `max_w`: corner buildings with
    /// that `corner` side only, or no corner buildings for 0. With `deep`, the deeper of two
    /// picks (main streets get the deeper houses).
    fn pick(&self, style: &str, kind: LotKind, rng: &mut Rng, corner: i8, deep: bool, max_w: f32) -> Option<u32> {
        let ms = &self.p.buildings.models;
        let cands: Vec<u32> = self.models(style, kind).iter().copied().filter(|&m| ms[m as usize].corner == corner && ms[m as usize].width_m <= max_w).collect();
        if cands.is_empty() {
            return None;
        }
        let mut one = || cands[((rng.f() * cands.len() as f32) as usize).min(cands.len() - 1)];
        let a = one();
        if deep {
            let b = one();
            if ms[b as usize].depth_m > ms[a as usize].depth_m {
                return Some(b);
            }
        }
        Some(a)
    }

    /// A lot's width and depth for a model (its footprint plus the margin all round), or the
    /// kind's envelope when the table has no models of it.
    fn dims(&self, style: &str, kind: LotKind, m: Option<u32>, margin: f32) -> (f32, f32) {
        let (w, d) = match m {
            Some(m) => (self.p.buildings.models[m as usize].width_m, self.p.buildings.models[m as usize].depth_m),
            None => self.fp(style, kind),
        };
        (w + 2.0 * margin, d + 2.0 * margin)
    }

    /// A lot that names its model.
    fn dressed(&self, mut lot: Lot, m: Option<u32>) -> Lot {
        if let Some(m) = m {
            let mf = &self.p.buildings.models[m as usize];
            lot.model_file = Some(mf.file.clone());
            lot.height_m = mf.height_m;
        }
        lot
    }

    /// A model and its lot size for a small thing (a lamp, a stall, a well, a tower).
    fn thing(&self, style: &str, kind: LotKind, rng: &mut Rng, margin: f32) -> (Option<u32>, f32, f32) {
        let m = self.pick(style, kind, rng, 0, false, f32::MAX);
        let (w, d) = self.dims(style, kind, m, margin);
        (m, w, d)
    }

    /// Which side of a lot (+1 along `perp(front)`, -1 against it) has another road running past
    /// it within `reach`: a corner lot at a junction.
    fn side_road(&self, c: V2, front: V2, w: f32, fr: Frontage, reach: f32) -> Option<f32> {
        let u = perp(front);
        let mut near = Vec::new();
        for sigma in [1.0f32, -1.0] {
            let q = add(c, mul(u, sigma * w * 0.5));
            self.road_b.query((q.0 - reach - 8.0, q.1 - reach - 8.0), (q.0 + reach + 8.0, q.1 + reach + 8.0), &mut near);
            for &rid in &near {
                if fr == Frontage::Road(rid) {
                    continue;
                }
                let rd = &self.roads[rid as usize];
                let (d, _, _, np) = nearest_on(&rd.points, q);
                if d - rd.width_m * 0.5 < reach && dot(norm(sub(np, c)), mul(u, sigma)) > 0.5 {
                    return Some(sigma);
                }
            }
        }
        None
    }

    /// Try a lot; returns its index when it fits.
    fn try_lot(&mut self, mut lot: Lot, gap: f32, cl: &Check) -> Option<u32> {
        let land = self.land;
        let r = lot.rect();
        let (lo, hi) = r.bbox(gap.max(1.0) + 2.0);
        if lo.0 < 1.0 || lo.1 < 1.0 || hi.0 > land.size as f32 - 1.0 || hi.1 > land.size as f32 - 1.0 {
            return None;
        }
        // Clear of roads (their full width plus a little) and walls.
        let mut near = Vec::new();
        self.road_b.query(lo, hi, &mut near);
        for &rid in &near {
            let rd = &self.roads[rid as usize];
            let clear = rd.width_m * 0.5 + cl.road_clear;
            for i in 0..rd.points.len() - 1 {
                let (a, b) = (rd.points[i], rd.points[i + 1]);
                if seg_near(r.c, a, b).0 > r.hw + r.hd + clear + 1.0 {
                    continue;
                }
                if r.seg_dist(a, b) < clear {
                    return None;
                }
            }
        }
        if !cl.on_wall {
            for (_, hw, ring) in &self.walls {
                let m = ring.len();
                for i in 0..m {
                    let (a, b) = (ring[i], ring[(i + 1) % m]);
                    if seg_near(r.c, a, b).0 < r.hw + r.hd + hw + 3.0 && r.seg_dist(a, b) < hw + 1.5 {
                        return None;
                    }
                }
            }
        }
        // Clear of plazas, unless it stands in one.
        for s in &self.settlements {
            if dist(s.plaza.centre, r.c) > 300.0 {
                continue;
            }
            let inside_ok = cl.in_plaza == Some(s.plaza.centre);
            if !inside_ok {
                // Both ways: the plaza's outline can bulge into a long side between its corners.
                let d = r.corners().iter().chain(std::iter::once(&r.c)).map(|q| poly_outside(&s.plaza.points, *q)).chain(s.plaza.points.iter().map(|q| r.outside(*q))).fold(f32::MAX, f32::min);
                let crossing = s.plaza.points.iter().any(|q| r.outside(*q) == 0.0);
                if d < cl.plaza_clear || crossing {
                    return None;
                }
            }
        }
        // Clear of stairs and their 2 m landings, by more than a pad's skirt, so no pad dips the
        // ground beside them.
        if !self.stairs.is_empty() {
            let k = self.settlements[lot.settlement as usize].scale.max(0.3);
            let clear = if lot.kind.padded() { self.set_style(lot.settlement).skirt_m + 0.3 * k } else { 0.5 * k };
            for s in &self.stairs {
                if dist(s.centre, r.c) < r.hw + r.hd + s.width_m + s.depth_m + 8.0 * k {
                    let sr = Rect { hd: s.depth_m * 0.5 + 2.0 * k, ..s.rect() };
                    if r.gap(&sr) < clear {
                        return None;
                    }
                }
            }
        }
        // Clear of other lots, by more where floors differ.
        self.lot_b.query(lo, hi, &mut near);
        for &li in &near {
            let o = &self.lots[li as usize];
            let need = if o.kind == LotKind::Lamp || lot.kind == LotKind::Lamp { 0.3 } else { gap.min(cl.min_gap).max(0.25).max(if o.kind.padded() && lot.kind.padded() { (o.floor_m - lot.floor_m).abs() * 0.8 } else { 0.0 }) };
            if r.gap(&o.rect()) < need {
                return None;
            }
        }
        // Walkable, dry ground, and not too steep to level.
        let step = if cl.step > 0.0 { cl.step.min(r.hw.min(r.hd)) } else { (r.hw.min(r.hd) * 0.5).clamp(0.25, 0.6) };
        let (mut hmin, mut hmax) = (f32::MAX, f32::MIN);
        let u = r.u();
        let mut a = -r.hw;
        while a <= r.hw + 1e-3 {
            let mut b = -r.hd;
            while b <= r.hd + 1e-3 {
                let q = add(r.c, add(mul(u, a), mul(r.f, b)));
                let t = land.map.at(q.0, q.1);
                if !t.walkable() || (t == Terrain::Road && cl.in_plaza.is_none()) || land.sd_at(q.0, q.1) < cl.water {
                    return None;
                }
                let h = land.height(q.0, q.1);
                hmin = hmin.min(h);
                hmax = hmax.max(h);
                // A floor near water stays above it.
                if cl.level && land.sd_at(q.0, q.1) < 7.0 && lot.floor_m < land.water_level(q.0, q.1) + 0.3 {
                    return None;
                }
                b += step;
            }
            a += step;
        }
        if cl.level {
            let cut = hmax - lot.floor_m;
            let fill = lot.floor_m - hmin;
            if cut > cl.cut || fill > cl.fill {
                return None;
            }
        } else {
            // A lamp stands on even ground, not on a terrace's edge or a cutting beside a ramp.
            if lot.kind == LotKind::Lamp && hmax - hmin > 0.4 {
                return None;
            }
            // Nor is a garden or field laid across a terrace's step: the step's edge becomes a
            // drop (`terrace::paint_drops`), which would cut through it.
            let terraced = land.mods.terr.iter().any(|z| dist(z.c, lot.centre) < z.r_out + 4.0);
            if terraced && matches!(lot.kind, LotKind::Garden | LotKind::Field) && hmax - hmin > terrace::CLIMB_M {
                return None;
            }
            lot.floor_m = (hmin + hmax) * 0.5;
        }
        lot.yaw = yaw_of(lot.front);
        let id = self.lots.len() as u32;
        let (lo, hi) = r.bbox(0.0);
        self.lot_b.insert(lo, hi, id);
        self.lots.push(lot);
        Some(id)
    }

    fn settlement_lots(&mut self, idx: u16, st: &'a Style, bound: &[f32], inner: &[f32]) {
        let land = self.land;
        let set = &self.settlements[idx as usize];
        let (centre, style, plaza, floor) = (set.centre, set.style.clone(), set.plaza.points.clone(), set.plaza.floor_m);
        let k = set.scale;
        let mut rng = Rng(self.seed ^ 0x107 ^ (idx as u64) << 8);
        let base = Check { road_clear: 0.25 * k.max(0.4), plaza_clear: 0.4, min_gap: 99.0, water: 2.5 + st.skirt_m, cut: st.cut_m, fill: st.fill_m, level: true, on_wall: false, in_plaza: None, step: 0.0 };
        let in_plaza = Check { in_plaza: Some(centre), level: false, water: 2.0, ..base };
        let make = |kind: LotKind, c: V2, front: V2, w: f32, d: f32, floor: f32, fr: Frontage| Lot { settlement: idx, kind, centre: c, width_m: w, depth_m: d, front: norm(front), yaw: 0.0, floor_m: floor, frontage: fr, landmark: false, model_file: None, height_m: 0.0 };
        // 1. The landmark, then the big buildings round the plaza.
        if let Some(lk) = st.landmark {
            let placed = if st.landmark_centre {
                let (m, w, d) = self.thing(&style, lk, &mut rng, st.margin_m);
                // The middle of the square, else along its long axis.
                let axis = norm(sub(plaza[0], centre));
                let mid = [0.0f32, 0.15, -0.15, 0.28, -0.28].iter().find_map(|&off| {
                    let c = add(centre, mul(axis, off * st.plaza_m[0]));
                    let lot = self.dressed(make(lk, c, (0.0, 1.0), w, d, floor, Frontage::Plaza(idx)), m);
                    self.try_lot(lot, 0.5, &Check { level: true, cut: 99.0, fill: 99.0, ..in_plaza })
                });
                // A square too small for it: its edge.
                mid.or_else(|| self.big_lot(idx, st, &style, lk, false, bound, &mut rng))
            } else {
                // On the plaza's edge, facing in, as far from the roads in as it can be.
                self.big_lot(idx, st, &style, lk, false, bound, &mut rng)
            };
            if let Some(id) = placed {
                self.lots[id as usize].landmark = true;
                self.settlements[idx as usize].landmark = Some(id);
            }
        }
        for &bk in &st.plaza_lots {
            // The inn by a road into the square; the others away from the roads and each other.
            let _ = self.big_lot(idx, st, &style, bk, bk == LotKind::Inn, bound, &mut rng);
        }
        // No room anywhere for the landmark: the biggest building on the square stands for it.
        if st.landmark.is_some() && self.settlements[idx as usize].landmark.is_none() {
            let first = self.lots.iter().rposition(|l| l.settlement != idx).map_or(0, |i| i + 1);
            let best = (first..self.lots.len()).filter(|&i| self.lots[i].kind.big()).max_by(|&a, &b| (self.lots[a].width_m * self.lots[a].depth_m).total_cmp(&(self.lots[b].width_m * self.lots[b].depth_m)));
            if let Some(i) = best {
                self.lots[i].landmark = true;
                self.settlements[idx as usize].landmark = Some(i as u32);
            }
        }
        // 2. A well and market stalls in the plaza.
        let axis = norm(sub(plaza[0], centre));
        if st.well && st.landmark != Some(LotKind::Well) {
            let (m, w, d) = self.thing(&style, LotKind::Well, &mut rng, st.margin_m);
            for off in [0.0f32, 0.2, -0.2, 0.35, -0.35] {
                let c = add(centre, mul(axis, off * st.plaza_m[0]));
                let lot = self.dressed(make(LotKind::Well, c, perp(axis), w, d, floor, Frontage::Plaza(idx)), m);
                if self.try_lot(lot, 0.5, &Check { level: true, cut: 99.0, fill: 99.0, ..in_plaza }).is_some() {
                    break;
                }
            }
        }
        if st.stalls > 0 {
            let aisle = 4.0 * k;
            let mut placed = 0;
            let half = st.plaza_m[0] * 0.5;
            let mut a = -half;
            while a < half && placed < st.stalls {
                let (m, w, d) = self.thing(&style, LotKind::MarketStall, &mut rng, st.margin_m * 0.5);
                for side in [1.0f32, -1.0] {
                    let n = mul(perp(axis), side);
                    let c = add(add(centre, mul(axis, a)), mul(n, aisle * 0.5 + d * 0.5));
                    let corners = Rect { c, f: mul(n, -1.0), hw: w * 0.5, hd: d * 0.5 }.corners();
                    if corners.iter().all(|q| poly_outside(&plaza, *q) == 0.0 && poly_contains(&plaza, *q)) && dist(c, centre) > 4.0 * k {
                        let lot = self.dressed(make(LotKind::MarketStall, c, mul(n, -1.0), w, d, floor, Frontage::Plaza(idx)), m);
                        if self.try_lot(lot, 0.6, &in_plaza).is_some() {
                            placed += 1;
                        }
                    }
                }
                a += w + 0.8 * k;
            }
        }
        // 3. Wall towers and gates.
        if let Some(ws) = &st.wall {
            self.wall_works(idx, st, ws);
        }
        // 4. Lamps along the main streets.
        let my_roads: Vec<u32> = self.settlement_roads(idx, centre, bound, st);
        if st.lamp_m > 0.0 || st.lane_lamp_m > 0.0 {
            for &rid in &my_roads {
                let rd = &self.roads[rid as usize];
                // Main streets at `lamp_m`, lanes at `lane_lamp_m`.
                let spacing = match rd.class {
                    RoadClass::Street | RoadClass::Trunk => st.lamp_m,
                    RoadClass::Lane if rd.settlement == Some(idx) => st.lane_lamp_m,
                    _ => 0.0,
                };
                if spacing <= 0.0 {
                    continue;
                }
                let (pts, hw) = (rd.points.clone(), rd.width_m * 0.5);
                let cl = cumlen(&pts);
                let total = *cl.last().unwrap();
                let mut s = spacing * 0.5;
                let mut side = 1.0f32;
                while s < total {
                    let (p, t) = at_s(&pts, &cl, s);
                    if dist(p, centre) < radial_at(bound, centre, p) {
                        let (m, w, d) = self.thing(&style, LotKind::Lamp, &mut rng, 0.05);
                        let n = mul(perp(t), side);
                        let c = add(p, mul(n, hw + d * 0.5 + 0.1));
                        let h = land.height(p.0, p.1);
                        let lot = self.dressed(Lot { settlement: idx, kind: LotKind::Lamp, centre: c, width_m: w, depth_m: d, front: mul(n, -1.0), yaw: 0.0, floor_m: h, frontage: Frontage::Road(rid), landmark: false, model_file: None, height_m: 0.0 }, m);
                        // At the road's level: not up a cutting or down an embankment beside it.
                        if (land.height(c.0, c.1) - h).abs() < 0.5 * k.max(0.4) {
                            let _ = self.try_lot(lot, 0.3, &Check { level: false, road_clear: 0.05, water: 1.0, ..base });
                        }
                    }
                    side = -side;
                    s += spacing;
                }
            }
        }
        // 4b. Wells in the neighbourhoods: beside lanes where they leave a main street, spread
        // round the town, away from the plaza.
        if st.wells > 0 {
            let mut cands: Vec<(f32, u32)> = my_roads
                .iter()
                .copied()
                .filter(|&r| {
                    let rd = &self.roads[r as usize];
                    rd.class == RoadClass::Lane && rd.settlement == Some(idx) && matches!(rd.ends[0], RoadEnd::Road(p) if matches!(self.roads[p as usize].class, RoadClass::Street | RoadClass::Trunk))
                })
                .map(|r| (dist(self.roads[r as usize].points[0], centre) / radial_at(bound, centre, self.roads[r as usize].points[0]), r))
                .filter(|&(z, _)| (0.35..0.85).contains(&z))
                .collect();
            cands.sort_by(|a, b| b.0.total_cmp(&a.0).then(a.1.cmp(&b.1)));
            let mut done: Vec<V2> = Vec::new();
            for (_, rid) in cands {
                if done.len() as u32 >= st.wells {
                    break;
                }
                let rd = &self.roads[rid as usize];
                let RoadEnd::Road(parent) = rd.ends[0] else { continue };
                let (p0, p1, lhw, phw) = (rd.points[0], rd.points[1.min(rd.points.len() - 1)], rd.width_m * 0.5, self.roads[parent as usize].width_m * 0.5);
                if done.iter().any(|q| dist(*q, p0) < radial_at(bound, centre, p0) * 0.8) {
                    continue;
                }
                let dir = norm(sub(p1, p0));
                let (m, w, d) = self.thing(&style, LotKind::Well, &mut rng, st.margin_m);
                for side in [1.0f32, -1.0] {
                    let n = mul(perp(dir), side);
                    let c = add(add(p0, mul(dir, phw + w * 0.5 + 1.2 * k)), mul(n, lhw + d * 0.5 + 0.6 * k));
                    let fp = add(c, mul(n, -(d * 0.5 + 0.6 * k)));
                    let lot = self.dressed(make(LotKind::Well, c, mul(n, -1.0), w, d, land.height(fp.0, fp.1) + st.step_m, Frontage::Road(rid)), m);
                    if self.try_lot(lot, 0.8, &base).is_some() {
                        done.push(p0);
                        break;
                    }
                }
            }
        }
        // 5. Round the plaza, facing in.
        {
            let m = plaza.len();
            let mut ring: Vec<V2> = plaza.clone();
            ring.push(plaza[0]);
            let _ = m;
            self.frontage(idx, st, &style, &ring, 0.0, if poly_area(&plaza) > 0.0 { -1.0 } else { 1.0 }, Frontage::Plaza(idx), Some(floor), bound, inner, centre, &mut rng, Zone::Plaza);
        }
        // 6. Along every street: main streets first, then lanes; inside the edge.
        let mut order = my_roads.clone();
        order.sort_by_key(|&r| match self.roads[r as usize].class {
            RoadClass::Street => 0,
            RoadClass::Trunk => 1,
            RoadClass::Lane => 2,
            RoadClass::Path => 3,
        });
        for &rid in &order {
            let (pts, hw) = (self.roads[rid as usize].points.clone(), self.roads[rid as usize].width_m * 0.5);
            for side in [1.0f32, -1.0] {
                self.frontage(idx, st, &style, &pts, hw, side, Frontage::Road(rid), None, bound, inner, centre, &mut rng, Zone::Inside);
            }
        }
        // 7. Outskirts along the roads leaving it, thinning out, then fields.
        for &rid in &order {
            let (pts, hw) = (self.roads[rid as usize].points.clone(), self.roads[rid as usize].width_m * 0.5);
            for side in [1.0f32, -1.0] {
                self.frontage(idx, st, &style, &pts, hw, side, Frontage::Road(rid), None, bound, inner, centre, &mut rng, Zone::Outskirts);
            }
        }
        if st.fields > 0.0 {
            for &rid in &order {
                let (pts, hw) = (self.roads[rid as usize].points.clone(), self.roads[rid as usize].width_m * 0.5);
                for side in [1.0f32, -1.0] {
                    self.frontage(idx, st, &style, &pts, hw, side, Frontage::Road(rid), None, bound, inner, centre, &mut rng, Zone::Fields);
                }
            }
        }
    }

    /// A big building (an inn, a hall, a chapel, a landmark) on the plaza's edge facing in: near
    /// a road into the plaza (`near_exits`, for an inn) or far from them, and away from the other
    /// big buildings; failing that, along a main street as near the plaza as it fits.
    #[allow(clippy::too_many_arguments)]
    fn big_lot(&mut self, idx: u16, st: &Style, style: &str, kind: LotKind, near_exits: bool, bound: &[f32], rng: &mut Rng) -> Option<u32> {
        let land = self.land;
        let set = &self.settlements[idx as usize];
        let (centre, plaza, floor) = (set.centre, set.plaza.points.clone(), set.plaza.floor_m);
        let k = land.sites[set.site as usize].scale;
        // Every model of the kind, in a random order (the envelope when there are none).
        let mut models: Vec<Option<u32>> = self.models(style, kind).iter().map(|&m| Some(m)).collect();
        if models.is_empty() {
            models.push(None);
        }
        for i in (1..models.len()).rev() {
            let j = ((rng.f() * (i + 1) as f32) as usize).min(i);
            models.swap(i, j);
        }
        let exits: Vec<V2> = self.roads.iter().filter(|r| r.ends[1] == RoadEnd::Plaza(idx) || r.ends[0] == RoadEnd::Plaza(idx)).map(|r| if r.ends[1] == RoadEnd::Plaza(idx) { r.points[r.points.len() - 1] } else { r.points[0] }).collect();
        let others: Vec<V2> = self.lots.iter().rev().take_while(|l| l.settlement == idx).filter(|l| l.kind.big() || l.landmark).map(|l| l.centre).collect();
        let base = Check { road_clear: 0.25 * k.max(0.4), plaza_clear: 0.4, min_gap: 99.0, water: 2.5 + st.skirt_m, cut: st.cut_m * 1.5, fill: st.fill_m * 1.5, level: true, on_wall: false, in_plaza: None, step: 0.0 };
        let m = plaza.len();
        let spread = 60.0 * k.max(0.3);
        let mut cands: Vec<(f32, V2, V2)> = (0..2 * m)
            .map(|i| {
                let (a, b) = (plaza[i / 2], plaza[(i / 2 + 1) % m]);
                let mid = if i % 2 == 0 { mul(add(a, b), 0.5) } else { b };
                let de = exits.iter().map(|e| dist(*e, mid)).fold(f32::MAX, f32::min).min(spread * 2.0);
                let dother = others.iter().map(|o| dist(*o, mid)).fold(spread, f32::min);
                let score = if near_exits { -(de - 14.0 * k.max(0.3)).abs() } else { de } + 0.7 * dother;
                (score, mid, norm(sub(centre, mid)))
            })
            .collect();
        cands.sort_by(|a, b| b.0.total_cmp(&a.0));
        for (_, mid, inward) in cands.iter().take(24) {
            for &mo in &models {
                let (w, d) = self.dims(style, kind, mo, st.margin_m);
                for off in [1.5f32, 2.5, 3.5] {
                    let c = sub(*mid, mul(*inward, d * 0.5 + off * k.max(0.5)));
                    let lot = self.dressed(Lot { settlement: idx, kind, centre: c, width_m: w, depth_m: d, front: *inward, yaw: 0.0, floor_m: floor + st.step_m, frontage: Frontage::Plaza(idx), landmark: false, model_file: None, height_m: 0.0 }, mo);
                    if let Some(id) = self.try_lot(lot, 0.5, &base) {
                        return Some(id);
                    }
                }
            }
        }
        // Along a main street, nearest the plaza first.
        let mut spots: Vec<(f32, u32, f32)> = Vec::new();
        for rid in self.settlement_roads(idx, centre, bound, st) {
            let rd = &self.roads[rid as usize];
            if !matches!(rd.class, RoadClass::Street | RoadClass::Trunk) {
                continue;
            }
            let cl = cumlen(&rd.points);
            let mut s = 0.0;
            while s < *cl.last().unwrap() {
                let p = at_s(&rd.points, &cl, s).0;
                let dc = dist(p, centre);
                if dc < radial_at(bound, centre, p) * 0.75 {
                    spots.push((dc, rid, s));
                }
                s += 3.0 * k.max(0.3);
            }
        }
        spots.sort_by(|a, b| a.0.total_cmp(&b.0));
        let check = Check { cut: st.cut_m * 1.2, fill: st.fill_m * 1.2, ..base };
        for &(_, rid, s) in spots.iter().take(80) {
            let (pts, hw) = (self.roads[rid as usize].points.clone(), self.roads[rid as usize].width_m * 0.5);
            let cl = cumlen(&pts);
            for side in [1.0f32, -1.0] {
                for &mo in &models {
                    let (w, d) = self.dims(style, kind, mo, st.margin_m);
                    let (pm, t) = at_s(&pts, &cl, s + w * 0.5);
                    let n = mul(perp(t), side);
                    let c = add(pm, mul(n, hw + st.setback_m + d * 0.5));
                    let fp = add(pm, mul(n, hw));
                    let lot = self.dressed(Lot { settlement: idx, kind, centre: c, width_m: w, depth_m: d, front: mul(n, -1.0), yaw: 0.0, floor_m: land.height(fp.0, fp.1) + st.step_m, frontage: Frontage::Road(rid), landmark: false, model_file: None, height_m: 0.0 }, mo);
                    if let Some(id) = self.try_lot(lot, 0.5, &check) {
                        return Some(id);
                    }
                }
            }
        }
        None
    }

    /// Roads that run through a settlement's built-up area or outskirts.
    fn settlement_roads(&self, idx: u16, centre: V2, bound: &[f32], st: &Style) -> Vec<u32> {
        let reach = bound.iter().cloned().fold(0.0, f32::max) + st.outskirts_m + 20.0;
        let mut near = Vec::new();
        self.road_b.query((centre.0 - reach, centre.1 - reach), (centre.0 + reach, centre.1 + reach), &mut near);
        near.into_iter()
            .filter(|&r| {
                let rd = &self.roads[r as usize];
                rd.settlement.is_none_or(|s| s == idx) && rd.points.iter().any(|q| dist(*q, centre) < reach)
            })
            .collect()
    }

    #[allow(clippy::too_many_arguments)]
    fn frontage(&mut self, idx: u16, st: &Style, style: &str, line: &[V2], hw: f32, side: f32, fr: Frontage, fixed_floor: Option<f32>, bound: &[f32], inner: &[f32], centre: V2, rng: &mut Rng, zone: Zone) {
        let land = self.land;
        let k = land.sites[self.settlements[idx as usize].site as usize].scale;
        let cl = cumlen(line);
        let total = *cl.last().unwrap();
        let base = Check { road_clear: 0.25 * k.max(0.4), plaza_clear: 0.4 * k.max(0.5), min_gap: 99.0, water: 2.5 + st.skirt_m, cut: st.cut_m, fill: st.fill_m, level: true, on_wall: false, in_plaza: None, step: 0.0 };
        let walled = st.wall.is_some();
        let mut s = rng.f() * 2.0;
        let fail_step = (1.5 * k).max(0.4);
        let edge = |p: V2| radial_at(if walled { inner } else { bound }, centre, p);
        let outer_edge = |p: V2| radial_at(bound, centre, p) + if walled { st.wall.as_ref().unwrap().thickness_m + 3.0 } else { 0.0 };
        let main = matches!(fr, Frontage::Plaza(_)) || matches!(fr, Frontage::Road(r) if self.roads[r as usize].class == RoadClass::Street);
        // How far beside a lot another road makes it a corner lot.
        let reach = st.setback_m + 3.0 * k.max(0.4);
        // A lot `w` wide and `d` deep from `start` along the line, and its direction away from it.
        let place = |start: f32, w: f32, d: f32, kind: LotKind| {
            let (pm, t) = at_s(line, &cl, start + w * 0.5);
            let n = mul(perp(t), side);
            let setback = if kind == LotKind::Field { st.setback_m + 1.0 * k } else { st.setback_m };
            let c = add(pm, mul(n, hw + setback + d * 0.5));
            let front_pt = add(pm, mul(n, hw));
            let floor = match fixed_floor {
                Some(f) => f + st.step_m,
                None => land.height(front_pt.0, front_pt.1) + st.step_m,
            };
            (Lot { settlement: idx, kind, centre: c, width_m: w, depth_m: d, front: mul(n, -1.0), yaw: 0.0, floor_m: floor, frontage: fr, landmark: false, model_file: None, height_m: 0.0 }, n)
        };
        // Lots inside a wall stay inside it; outskirts stay outside.
        let inside = |q: V2, d: f32| dist(q, centre) <= edge(q) + if walled { 0.0 } else { d * 0.3 };
        let in_zone = |lot: &Lot| match zone {
            Zone::Plaza | Zone::Inside => lot.rect().corners().iter().all(|q| inside(*q, lot.depth_m)),
            _ => lot.rect().corners().iter().all(|q| dist(*q, centre) > outer_edge(*q)),
        };
        while s < total {
            let (p, _) = at_s(line, &cl, s);
            let r = dist(p, centre);
            let z = r / edge(p);
            // What goes here, and with what gap after it.
            let (kind, gap) = match zone {
                Zone::Plaza | Zone::Inside => {
                    if z > 1.0 {
                        s += fail_step * 2.0;
                        continue;
                    }
                    let zz = if main { z * 0.75 } else { z };
                    if zz < st.core || rng.f() < st.core_share {
                        (st.core_kind, rng.range(st.core_gap_m))
                    } else if zone == Zone::Inside && rng.f() < st.workshop {
                        (LotKind::Workshop, rng.range(st.gap_m))
                    } else {
                        (st.outer_kind, rng.range(st.gap_m))
                    }
                }
                Zone::Outskirts => {
                    let oe = outer_edge(p);
                    let out = (r - oe) / st.outskirts_m.max(1.0);
                    if !(0.0..1.0).contains(&out) {
                        s += fail_step * 3.0;
                        continue;
                    }
                    if rng.f() > (1.0 - out).d_powf(1.5) {
                        s += rng.range(st.outskirt_gap_m);
                        continue;
                    }
                    let kind = if rng.f() < st.barn { LotKind::Barn } else { st.outer_kind };
                    (kind, rng.range(st.outskirt_gap_m) * (0.6 + out))
                }
                Zone::Fields => {
                    let oe = outer_edge(p);
                    let out = (r - oe) / st.outskirts_m.max(1.0);
                    if !(0.15..1.6).contains(&out) || rng.f() > st.fields {
                        s += fail_step * 4.0;
                        continue;
                    }
                    (LotKind::Field, rng.range([1.0, 3.0]) * k.max(0.3))
                }
            };
            // The lot that fits: (id, where it ends along the line, its direction from the line).
            let mut placed: Option<(u32, f32, V2)> = None;
            if kind == LotKind::Field {
                let (w, d) = (rng.range(st.field_w_m), rng.range(st.field_d_m));
                let (lot, n) = place(s, w, d, kind);
                if in_zone(&lot) {
                    placed = self.try_lot(lot, gap, &Check { level: false, water: 1.5, ..base }).map(|id| (id, s + w, n));
                }
            } else {
                // A model for the lot (the deeper of two on main streets); a corner building where
                // another road passes its side; narrower models when it does not fit.
                let mut max_w = f32::MAX;
                'models: for attempt in 0..3 {
                    let m = self.pick(style, kind, rng, 0, main && zone != Zone::Outskirts && attempt == 0, max_w);
                    if m.is_none() && attempt > 0 {
                        break;
                    }
                    let (w, d) = self.dims(style, kind, m, st.margin_m);
                    let mut options: Vec<(Option<u32>, f32, f32, f32, Option<f32>)> = Vec::new();
                    let (probe, _) = place(s, w, d, kind);
                    if let Some(sigma) = self.side_road(probe.centre, probe.front, w, fr, reach) {
                        // The model's +X is -perp(front): a front on the sigma side is corner -sigma.
                        if let Some(cm) = self.pick(style, kind, rng, -sigma as i8, false, f32::MAX) {
                            let (cw, cd) = self.dims(style, kind, Some(cm), st.margin_m);
                            // Keep the edge beside the other road where it was.
                            let start = if sigma * side > 0.0 { s + w - cw } else { s };
                            options.push((Some(cm), start, cw, cd, Some(sigma)));
                        }
                    }
                    options.push((m, s, w, d, None));
                    for (mo, start, w, d, corner) in options {
                        let (lot, n) = place(start, w, d, kind);
                        // A corner building must still have the other road on its corner side.
                        if !in_zone(&lot) || corner.is_some_and(|sg| self.side_road(lot.centre, lot.front, w, fr, reach) != Some(sg)) {
                            continue;
                        }
                        let lot = self.dressed(lot, mo);
                        if let Some(id) = self.try_lot(lot, gap, &base) {
                            placed = Some((id, start + w, n));
                            break 'models;
                        }
                    }
                    if m.is_none() {
                        break;
                    }
                    max_w = w - 2.0 * st.margin_m - 0.5 * k.max(0.3);
                }
            }
            match placed {
                Some((id, end, n)) => {
                    s = end + gap;
                    let (c, w, d) = (self.lots[id as usize].centre, self.lots[id as usize].width_m, self.lots[id as usize].depth_m);
                    let chance = if kind == st.core_kind && zone != Zone::Outskirts { st.garden * 0.8 } else { st.garden };
                    if matches!(kind, LotKind::House | LotKind::Townhouse) && rng.f() < chance {
                        // Burgage plots: deeper behind the main streets.
                        let gd = rng.range(st.garden_m) * if main { 1.35 } else { 1.0 };
                        let gc = add(c, mul(n, d * 0.5 + 0.4 * k.max(0.5) + gd * 0.5));
                        let g = Lot { settlement: idx, kind: LotKind::Garden, centre: gc, width_m: w, depth_m: gd, front: mul(n, -1.0), yaw: 0.0, floor_m: 0.0, frontage: Frontage::Lot(id), landmark: false, model_file: None, height_m: 0.0 };
                        let okz = match zone {
                            Zone::Inside | Zone::Plaza => g.rect().corners().iter().all(|q| inside(*q, gd)),
                            _ => true,
                        };
                        if okz {
                            let _ = self.try_lot(g, 0.3, &Check { level: false, water: 1.5, ..base });
                        }
                    }
                }
                None => s += fail_step,
            }
        }
    }

    /// Gates where roads cross the wall, towers beside them and along it, and the standing runs.
    fn wall_works(&mut self, idx: u16, st: &Style, ws: &WallSpec) {
        let land = self.land;
        let Some(wall) = self.settlements[idx as usize].wall.clone() else { return };
        let centre = self.settlements[idx as usize].centre;
        let ring = &wall.ring;
        let m = ring.len();
        let mut gates: Vec<(Gate, usize, f32)> = Vec::new();
        for (rid, r) in self.roads.iter().enumerate() {
            for j in 0..r.points.len() - 1 {
                for i in 0..m {
                    if let Some((t, u)) = seg_intersect(r.points[j], r.points[j + 1], ring[i], ring[(i + 1) % m]) {
                        let at = add(r.points[j], mul(sub(r.points[j + 1], r.points[j]), t));
                        let mut out = norm(perp(sub(ring[(i + 1) % m], ring[i])));
                        if dot(out, sub(at, centre)) < 0.0 {
                            out = mul(out, -1.0);
                        }
                        gates.push((Gate { at, out, width_m: r.width_m + ws.gate_m, road: rid as u32 }, i, u));
                    }
                }
            }
        }
        // Runs: the ring without gate gaps and water.
        let cl_ring = {
            let mut q = ring.clone();
            q.push(ring[0]);
            q
        };
        let cl = cumlen(&cl_ring);
        let total = *cl.last().unwrap();
        let gate_s: Vec<(f32, f32)> = gates.iter().map(|(g, i, u)| (cl[*i] + u * (cl[i + 1] - cl[*i]), g.width_m * 0.5 + 0.5)).collect();
        let mut runs: Vec<Vec<V2>> = Vec::new();
        let mut cur: Vec<V2> = Vec::new();
        let step = 1.0;
        let mut s = 0.0;
        while s <= total {
            let p = at_s(&cl_ring, &cl, s).0;
            let in_gate = gate_s.iter().any(|&(gs, hw)| {
                let d = (s - gs).abs();
                d.min(total - d) < hw
            });
            let wet = land.map.at(p.0, p.1) == Terrain::Water || land.sd_at(p.0, p.1) < 0.5;
            if in_gate || wet {
                if cur.len() >= 2 {
                    runs.push(std::mem::take(&mut cur));
                }
                cur.clear();
            } else {
                cur.push(p);
            }
            s += step;
        }
        if cur.len() >= 2 {
            // Join the last run to the first when the ring closes without a break.
            if let Some(first) = runs.first_mut() {
                if dist(first[0], cl_ring[0]) < 1.5 && dist(*cur.last().unwrap(), cl_ring[0]) < 1.5 {
                    cur.extend(first.iter().skip(1));
                    *first = cur;
                } else {
                    runs.push(cur);
                }
            } else {
                runs.push(cur);
            }
        }
        let runs: Vec<Vec<V2>> = runs.into_iter().map(|r| rdp(&r, 0.3)).filter(|r| r.len() >= 2).collect();
        // Towers: one beside each gate, then along the runs.
        let style = self.settlements[idx as usize].style.clone();
        let mut rng = Rng(self.seed ^ 0x70E5 ^ (idx as u64) << 8);
        let tower = Check { road_clear: 0.6, plaza_clear: 2.0, min_gap: 99.0, water: 2.0, cut: st.cut_m * 2.0, fill: st.fill_m * 2.0, level: true, on_wall: true, in_plaza: None, step: 0.0 };
        let mut towers: Vec<V2> = Vec::new();
        for (g, i, _) in &gates {
            let along = norm(sub(ring[(i + 1) % m], ring[*i]));
            let (tm, w, d) = self.thing(&style, LotKind::Tower, &mut rng, st.margin_m);
            for side in [1.0f32, -1.0] {
                let c = add(add(g.at, mul(along, side * (g.width_m * 0.5 + w * 0.5 + 0.8))), mul(g.out, d * 0.5 - ws.thickness_m * 0.5 - 0.3));
                let floor = land.height(c.0, c.1);
                let lot = self.dressed(Lot { settlement: idx, kind: LotKind::Tower, centre: c, width_m: w, depth_m: d, front: mul(g.out, -1.0), yaw: 0.0, floor_m: floor, frontage: Frontage::Wall(idx), landmark: false, model_file: None, height_m: 0.0 }, tm);
                if self.try_lot(lot, 1.0, &tower).is_some() {
                    towers.push(c);
                    break;
                }
            }
        }
        // Corner towers, every other corner at least, never crowding a gate tower.
        let nc = wall.corners.len();
        for (ci, &p) in wall.corners.iter().enumerate() {
            let (a, b) = (wall.corners[(ci + nc - 1) % nc], wall.corners[(ci + 1) % nc]);
            let turn = cross(norm(sub(p, a)), norm(sub(b, p))).abs();
            if towers.iter().any(|q| dist(*q, p) < ws.tower_m * 0.55) || (turn < 0.12 && ci % 2 == 1) {
                continue;
            }
            let on_wall = runs.iter().any(|r| nearest_on(r, p).0 < 1.0);
            if !on_wall {
                continue;
            }
            let out = norm(sub(p, centre));
            let (tm, w, d) = self.thing(&style, LotKind::Tower, &mut rng, st.margin_m);
            let c = add(p, mul(out, d * 0.5 - ws.thickness_m * 0.5 - 0.3));
            let floor = land.height(c.0, c.1);
            let lot = self.dressed(Lot { settlement: idx, kind: LotKind::Tower, centre: c, width_m: w, depth_m: d, front: mul(out, -1.0), yaw: 0.0, floor_m: floor, frontage: Frontage::Wall(idx), landmark: false, model_file: None, height_m: 0.0 }, tm);
            if self.try_lot(lot, 1.0, &tower).is_some() {
                towers.push(c);
            }
        }
        let wall = self.settlements[idx as usize].wall.as_mut().unwrap();
        wall.gates = gates.into_iter().map(|g| g.0).collect();
        wall.runs = runs;
    }

    fn pads(&self) -> Vec<Pad> {
        let mut pads: Vec<Pad> = Vec::new();
        let mut owner: Vec<Option<u32>> = Vec::new();
        for (i, s) in self.settlements.iter().enumerate() {
            // A planned settlement's square and lots stand on its levels.
            if s.planned {
                continue;
            }
            let st = self.set_style(i as u16);
            pads.push(Pad { shape: Shape::Poly(s.plaza.points.clone()), floor: s.plaza.floor_m, skirt: (st.skirt_m * 2.0).max(1.0), gate: 0.0, rise: None });
            owner.push(None);
        }
        for (i, l) in self.lots.iter().enumerate() {
            // Lots inside a plaza stand on its level ground.
            if !l.kind.padded() || self.settlements[l.settlement as usize].planned || poly_contains(&self.settlements[l.settlement as usize].plaza.points, l.centre) {
                continue;
            }
            let st = self.set_style(l.settlement);
            pads.push(Pad { shape: Shape::Rect(l.rect()), floor: l.floor_m, skirt: st.skirt_m, gate: 0.0, rise: None });
            owner.push(Some(i as u32));
        }
        // Stairs: a ramp from their foot to their head, with a short skirt.
        for st in &self.stairs {
            let k = self.settlements[st.settlement as usize].scale.max(0.3);
            pads.push(Pad { shape: Shape::Rect(st.rect()), floor: st.floor_m, skirt: 0.3 * k, gate: 0.0, rise: Some((st.front, self.settlements[st.settlement as usize].terrace_m)) });
            owner.push(None);
        }
        // Gates: a fraction of the clearance to the nearest other pad, so pads stay level.
        let mut b = Buckets::new(self.land.size as f32, 32.0);
        let boxes: Vec<(V2, V2)> = pads
            .iter()
            .map(|p| match &p.shape {
                Shape::Rect(r) => r.bbox(4.0),
                Shape::Poly(q) => {
                    let lo = q.iter().fold((f32::MAX, f32::MAX), |m, v| (m.0.min(v.0), m.1.min(v.1)));
                    let hi = q.iter().fold((f32::MIN, f32::MIN), |m, v| (m.0.max(v.0), m.1.max(v.1)));
                    ((lo.0 - 4.0, lo.1 - 4.0), (hi.0 + 4.0, hi.1 + 4.0))
                }
            })
            .collect();
        for (i, bx) in boxes.iter().enumerate() {
            b.insert(bx.0, bx.1, i as u32);
        }
        let mut near = Vec::new();
        let gates: Vec<f32> = (0..pads.len())
            .map(|i| {
                b.query(boxes[i].0, boxes[i].1, &mut near);
                let mut g = 2.0f32;
                for &j in &near {
                    if j as usize == i {
                        continue;
                    }
                    g = g.min(pad_gap(&pads[i], &pads[j as usize]));
                }
                let k = owner[i].map_or(1.0, |l| self.settlements[self.lots[l as usize].settlement as usize].scale);
                (g * 0.45).clamp(0.05, 1.0 * k.max(0.3))
            })
            .collect();
        for (p, g) in pads.iter_mut().zip(gates) {
            p.gate = g;
        }
        pads
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Zone {
    Plaza,
    Inside,
    Outskirts,
    Fields,
}

#[derive(Clone, Copy)]
struct Check {
    road_clear: f32,
    plaza_clear: f32,
    min_gap: f32,
    water: f32,
    cut: f32,
    fill: f32,
    /// The ground is levelled to the floor: limit the cut and fill.
    level: bool,
    on_wall: bool,
    in_plaza: Option<V2>,
    /// Spacing of the ground samples under the lot (0: a fine step from its size).
    step: f32,
}

struct Trace<'b> {
    step: f32,
    max_len: f32,
    contour: f32,
    circle: f32,
    radial: f32,
    wander: f32,
    hw: f32,
    sep: f32,
    centre: V2,
    limit: Option<&'b [f32]>,
    parent: Option<u32>,
    seed: u64,
    settlement: u16,
    plaza: &'b [V2],
    /// Stop before a step that rises or falls more than this (0: never).
    drop: f32,
    /// The settlement's terraces, if any.
    zone: Option<&'b Terrace>,
}

fn pad_gap(a: &Pad, b: &Pad) -> f32 {
    match (&a.shape, &b.shape) {
        (Shape::Rect(x), Shape::Rect(y)) => x.gap(y),
        (Shape::Rect(x), Shape::Poly(q)) | (Shape::Poly(q), Shape::Rect(x)) => {
            let a = x.corners().iter().map(|c| poly_outside(q, *c)).fold(f32::MAX, f32::min);
            let b = q.iter().map(|c| x.outside(*c)).fold(f32::MAX, f32::min);
            a.min(b)
        }
        (Shape::Poly(p), Shape::Poly(q)) => p.iter().map(|c| poly_outside(q, *c)).fold(f32::MAX, f32::min),
    }
}

fn poly_area(p: &[V2]) -> f32 {
    let n = p.len();
    (0..n).map(|i| cross(p[i], p[(i + 1) % n])).sum::<f32>() * 0.5
}

fn dedup(p: Vec<V2>) -> Vec<V2> {
    let mut out: Vec<V2> = Vec::with_capacity(p.len());
    for q in p {
        if out.last().is_none_or(|l| dist(*l, q) > 0.05) {
            out.push(q);
        }
    }
    out
}

fn sample_profile(cl: &[f32], h: &[f32], s: f32) -> f32 {
    let i = cl.iter().position(|v| *v >= s).unwrap_or(cl.len() - 1);
    if i == 0 {
        return h[0];
    }
    let t = (s - cl[i - 1]) / (cl[i] - cl[i - 1]).max(1e-6);
    lerp(h[i - 1], h[i], t.clamp(0.0, 1.0))
}

/// Radius of a per-direction profile toward `p`.
fn radial_at(bound: &[f32], c: V2, p: V2) -> f32 {
    let n = bound.len();
    let a = (p.1 - c.1).d_atan2(p.0 - c.0).rem_euclid(std::f32::consts::TAU) / std::f32::consts::TAU * n as f32;
    let i = a.floor() as usize % n;
    lerp(bound[i], bound[(i + 1) % n], a.fract())
}

fn ring_points(c: V2, bound: &[f32], k: f32) -> Vec<V2> {
    let n = bound.len();
    (0..n)
        .map(|i| {
            let a = i as f32 / n as f32 * std::f32::consts::TAU;
            add(c, (a.d_cos() * bound[i] * k, a.d_sin() * bound[i] * k))
        })
        .collect()
}

/// The last crossing of a polyline with a closed ring: (point, segment index).
fn last_crossing(p: &[V2], ring: &[V2]) -> Option<(V2, usize)> {
    let m = ring.len();
    for j in (0..p.len() - 1).rev() {
        for i in 0..m {
            if let Some((t, _)) = seg_intersect(p[j], p[j + 1], ring[i], ring[(i + 1) % m]) {
                return Some((add(p[j], mul(sub(p[j + 1], p[j]), t)), j));
            }
        }
    }
    None
}

/// Paint roads into the tiles (`pass` 0: island roads before profiles; 1: all). Returns the
/// bounding boxes of water tiles that became road (river crossings).
fn paint_roads(land: &mut Land, roads: &[Road], pass: u8) -> Vec<((i32, i32), (i32, i32))> {
    let w = land.size as i32;
    let mut changed = Vec::new();
    for r in roads {
        let hw = r.width_m * 0.5;
        let mut bbox: Option<((i32, i32), (i32, i32))> = None;
        for i in 0..r.points.len().saturating_sub(1) {
            let (a, b) = (r.points[i], r.points[i + 1]);
            let x0 = ((a.0.min(b.0) - hw - 1.0).floor() as i32).max(0);
            let x1 = ((a.0.max(b.0) + hw + 1.0).ceil() as i32).min(w - 1);
            let y0 = ((a.1.min(b.1) - hw - 1.0).floor() as i32).max(0);
            let y1 = ((a.1.max(b.1) + hw + 1.0).ceil() as i32).min(w - 1);
            for y in y0..=y1 {
                for x in x0..=x1 {
                    let q = (x as f32 + 0.5, y as f32 + 0.5);
                    if seg_near(q, a, b).0 > hw.max(0.5) {
                        continue;
                    }
                    let t = land.map.get(x, y);
                    let k = (y * w + x) as usize;
                    match t {
                        Terrain::Water => {
                            // Rivers, or lake water a causeway crosses; never the sea.
                            let river = || {
                                land.rivers.iter().any(|rv| {
                                    let (d, i, _, _) = nearest_on(&rv.points, q);
                                    d < rv.width_m[i] * 0.5 + 1.5
                                })
                            };
                            if pass == 0 && (land.water_level(q.0, q.1) > 0.5 || river()) {
                                land.map.tiles[k] = Terrain::Road as u8;
                                let bb = bbox.get_or_insert(((x, y), (x, y)));
                                bb.0 = (bb.0 .0.min(x), bb.0 .1.min(y));
                                bb.1 = (bb.1 .0.max(x), bb.1 .1.max(y));
                            }
                        }
                        Terrain::Wall | Terrain::Drop => {}
                        // Before streets are laid out only river crossings are painted, since
                        // main streets may still bend away from the routed line.
                        _ if pass == 0 => {}
                        _ => land.map.tiles[k] = Terrain::Road as u8,
                    }
                }
            }
        }
        if let Some(b) = bbox {
            changed.push(b);
        }
    }
    changed
}

/// Plazas, walls and lot ground.
fn paint_rest(land: &mut Land, settlements: &[Settlement], lots: &[Lot]) {
    let w = land.size as i32;
    let set = |land: &mut Land, x: i32, y: i32, f: &dyn Fn(Terrain) -> Option<Terrain>| {
        if x < 0 || y < 0 || x >= w || y >= w {
            return;
        }
        let k = (y * w + x) as usize;
        if let Some(t) = f(Terrain::from_u8(land.map.tiles[k])) {
            land.map.tiles[k] = t as u8;
        }
    };
    for s in settlements {
        let p = &s.plaza.points;
        let lo = p.iter().fold((f32::MAX, f32::MAX), |m, v| (m.0.min(v.0), m.1.min(v.1)));
        let hi = p.iter().fold((f32::MIN, f32::MIN), |m, v| (m.0.max(v.0), m.1.max(v.1)));
        for y in lo.1.floor() as i32..=hi.1.ceil() as i32 {
            for x in lo.0.floor() as i32..=hi.0.ceil() as i32 {
                if poly_contains(p, (x as f32 + 0.5, y as f32 + 0.5)) {
                    let paved = s.plaza.paved;
                    set(land, x, y, &|t| match t {
                        Terrain::Water | Terrain::Wall | Terrain::Drop => None,
                        _ if paved => Some(Terrain::Road),
                        Terrain::Forest | Terrain::Dirt | Terrain::Rock | Terrain::Road => Some(Terrain::Grass),
                        _ => None,
                    });
                }
            }
        }
        if let Some(wall) = &s.wall {
            let hw = wall.thickness_m * 0.5;
            for run in &wall.runs {
                for i in 0..run.len() - 1 {
                    let (a, b) = (run[i], run[i + 1]);
                    for y in (a.1.min(b.1) - hw - 1.0) as i32..=(a.1.max(b.1) + hw + 1.0) as i32 {
                        for x in (a.0.min(b.0) - hw - 1.0) as i32..=(a.0.max(b.0) + hw + 1.0) as i32 {
                            if seg_near((x as f32 + 0.5, y as f32 + 0.5), a, b).0 <= hw {
                                set(land, x, y, &|t| match t {
                                    Terrain::Water | Terrain::Road => None,
                                    _ => Some(Terrain::Wall),
                                });
                            }
                        }
                    }
                }
            }
        }
    }
    for l in lots {
        let r = l.rect();
        let (lo, hi) = r.bbox(0.0);
        for y in lo.1.floor() as i32..=hi.1.ceil() as i32 {
            for x in lo.0.floor() as i32..=hi.0.ceil() as i32 {
                if r.outside((x as f32 + 0.5, y as f32 + 0.5)) > 0.0 {
                    continue;
                }
                let field = l.kind == LotKind::Field;
                let ploughed = field && hash(0xF1E1D, l.centre.0 as i32, l.centre.1 as i32) < 0.6;
                set(land, x, y, &|t| match t {
                    Terrain::Forest if !field => Some(Terrain::Grass),
                    Terrain::Forest | Terrain::Grass if ploughed => Some(Terrain::Dirt),
                    Terrain::Forest => Some(Terrain::Grass),
                    _ => None,
                });
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::land::{generate_default, LandParams};
    use std::sync::OnceLock;

    fn world() -> &'static Land {
        static L: OnceLock<Land> = OnceLock::new();
        L.get_or_init(|| generate_default(7, 2048))
    }

    fn small() -> &'static Land {
        static L: OnceLock<Land> = OnceLock::new();
        L.get_or_init(|| generate_default(5, 1024))
    }

    fn worlds() -> [&'static Land; 2] {
        [world(), small()]
    }

    /// The megacity floor (`seeds/floor-megacity.json`) at 2048 m: its city is a quarter the
    /// area of the 4096 m floor, with the same planner and districts.
    pub(crate) fn megacity_params() -> (u64, LandParams) {
        let v: serde_json::Value = serde_json::from_str(include_str!("../../seeds/floor-megacity.json")).expect("seed json");
        (v["seed"].as_u64().unwrap(), serde_json::from_value(v["map"]["params"].clone()).expect("map.params"))
    }

    fn megacity() -> &'static Land {
        static L: OnceLock<Land> = OnceLock::new();
        L.get_or_init(|| {
            let (seed, p) = megacity_params();
            crate::land::generate(seed, 2048, &p)
        })
    }

    #[test]
    fn megacity_lots_do_not_overlap_and_stand_on_dry_walkable_ground() {
        let l = megacity();
        lots_do_not_overlap_each_other_or_roads_on(l);
        lots_sit_on_walkable_dry_land_on(l);
        pads_are_level_on(l);
    }

    #[test]
    fn megacity_lots_front_streets_and_name_their_models() {
        let l = megacity();
        every_lot_fronts_a_street_on(l);
        lots_match_their_models_on(l);
        ornaments_keep_doors_and_streets_clear_on(l);
    }

    #[test]
    fn megacity_roads_connect_every_ward_and_settlement() {
        roads_connect_every_settlement_on(megacity());
    }

    /// The city has its parts: a ward for the core and for every band and sector, towers in the
    /// core, slums and works, a wall with a gate on every arterial, and the land's other
    /// settlements outside it.
    #[test]
    fn megacity_has_core_rings_districts_and_wall() {
        let l = megacity();
        let (_, p) = megacity_params();
        let mp = p.metro.clone().unwrap();
        let wards: Vec<&Settlement> = l.settlements.iter().filter(|s| l.sites[s.site as usize].ward).collect();
        assert_eq!(wards.len(), 1 + mp.rings.len() * mp.arterials as usize, "wards");
        let core = wards[0];
        let core_lots = &l.lots[core.lots.0 as usize..core.lots.1 as usize];
        // The core: its arcology in the middle of the square, megatowers round it.
        let arcology = core_lots.iter().find(|x| x.landmark && x.model_file.as_deref().is_some_and(|f| f.contains("/arcology/"))).expect("the core's arcology");
        assert!(poly_contains(&core.plaza.points, arcology.centre) && arcology.height_m >= 100.0, "arcology at {:?}, {} m", arcology.centre, arcology.height_m);
        let towers = wards.iter().filter(|w| w.style == "corporate").flat_map(|w| &l.lots[w.lots.0 as usize..w.lots.1 as usize]).filter(|x| x.height_m >= 100.0).count();
        assert!(towers >= 6, "corporate towers of 100 m: {towers}");
        // Every district of the seed has a ward; districts with a quota keep to it.
        for d in &mp.districts {
            let n = wards.iter().filter(|w| w.style == d.style).count();
            assert!(n >= 1, "no {} ward", d.style);
        }
        for style in ["market", "oldtown"] {
            assert_eq!(wards.iter().filter(|w| w.style == style).count(), 1, "{style} wards");
        }
        let wall = core.wall.as_ref().expect("the city is walled");
        assert_eq!(wall.gates.len(), mp.arterials as usize, "gates");
        let c = (mp.centre[0] * 2048.0, mp.centre[1] * 2048.0);
        let reach = wall.ring.iter().map(|q| dist(*q, c)).fold(0.0, f32::max);
        for s in l.settlements.iter().filter(|s| !l.sites[s.site as usize].ward) {
            assert!(dist(s.centre, c) > reach, "{} settlement at {:?} inside the wall", s.style, s.centre);
        }
        // Each ward has its square and is peopled with homes.
        for w in &wards {
            let homes = l.lots[w.lots.0 as usize..w.lots.1 as usize].iter().filter(|x| matches!(x.kind, LotKind::House | LotKind::Townhouse)).count();
            assert!(homes >= 3 || matches!(w.style.as_str(), "works" | "corporate" | "market"), "{} ward has {homes} homes", w.style);
            assert!(poly_area(&w.plaza.points).abs() > 100.0, "{} ward's square", w.style);
        }
        // Highways: every arterial runs out past the wall, and the rings are whole.
        for r in l.roads.iter().take(mp.arterials as usize) {
            let far = r.points.iter().map(|q| dist(*q, c)).fold(0.0, f32::max);
            assert!(far > reach * 0.98 || r.ends[1] == RoadEnd::Shore, "arterial stops at {far} m");
        }
    }

    #[test]
    fn megacity_is_repeatable() {
        let (seed, p) = megacity_params();
        let a = crate::land::generate(seed, 1024, &p);
        let b = crate::land::generate(seed, 1024, &p);
        let (ma, _) = crate::host::hosted_map(&a, &p);
        let (mb, _) = crate::host::hosted_map(&b, &p);
        assert_eq!(crate::host::digests(&a, &ma), crate::host::digests(&b, &mb));
        assert!(a.settlements.len() > 10 && a.lots.len() > 300, "{} settlements, {} lots at 1024 m", a.settlements.len(), a.lots.len());
    }

    fn in_plaza(l: &Land, lot: &Lot) -> bool {
        poly_contains(&l.settlements[lot.settlement as usize].plaza.points, lot.centre)
    }

    /// Points spread over a lot's footprint, `inset` metres in from its edge.
    fn samples(lot: &Lot, step: f32, inset: f32) -> Vec<V2> {
        let r = lot.rect();
        let (hw, hd) = ((r.hw - inset).max(0.0), (r.hd - inset).max(0.0));
        let mut out = Vec::new();
        let (na, nb) = ((2.0 * hw / step).ceil().max(1.0) as usize, (2.0 * hd / step).ceil().max(1.0) as usize);
        for i in 0..=na {
            for j in 0..=nb {
                let (a, b) = (-hw + 2.0 * hw * i as f32 / na as f32, -hd + 2.0 * hd * j as f32 / nb as f32);
                out.push(add(r.c, add(mul(r.u(), a), mul(r.f, b))));
            }
        }
        out
    }

    #[test]
    fn every_settlement_is_laid_out() {
        for l in worlds() {
            every_settlement_is_laid_out_on(l);
        }
    }

    fn every_settlement_is_laid_out_on(l: &Land) {
        let settled = l.sites.iter().filter(|s| s.kind != SiteKind::Cave).count();
        assert_eq!(l.settlements.len(), settled, "{} m", l.size);
        for s in &l.settlements {
            let lots = &l.lots[s.lots.0 as usize..s.lots.1 as usize];
            let houses = lots.iter().filter(|x| matches!(x.kind, LotKind::House | LotKind::Townhouse)).count();
            // A hamlet may be a farmstead or two; everywhere else a settlement is a few households.
            let least = if s.style == "hamlet" { 1 } else { 3 };
            assert!(houses >= least, "{:?} {} at {} m has {houses} houses", s.kind, s.style, l.size);
            assert!(s.landmark.is_some() || s.kind == SiteKind::Village, "{:?} has no landmark", s.kind);
        }
        let town = l.settlements.iter().find(|s| s.kind == SiteKind::Town).unwrap();
        let wall = town.wall.as_ref().expect("the town is walled");
        assert!(wall.gates.len() >= 2, "town gates: {}", wall.gates.len());
        assert!(!wall.pieces(4.7, town.centre).is_empty());
    }

    #[test]
    fn lots_do_not_overlap_each_other_or_roads() {
        for l in worlds() {
            lots_do_not_overlap_each_other_or_roads_on(l);
        }
    }

    fn lots_do_not_overlap_each_other_or_roads_on(l: &Land) {
        let mut b = Buckets::new(l.size as f32, 32.0);
        for (i, lot) in l.lots.iter().enumerate() {
            let (lo, hi) = lot.rect().bbox(0.0);
            b.insert(lo, hi, i as u32);
        }
        let mut near = Vec::new();
        for (i, lot) in l.lots.iter().enumerate() {
            let r = lot.rect();
            let (lo, hi) = r.bbox(0.0);
            b.query(lo, hi, &mut near);
            for &j in &near {
                if j as usize != i {
                    assert!(r.gap(&l.lots[j as usize].rect()) > 0.1, "lots {i} {:?} and {j} {:?} overlap", lot.kind, l.lots[j as usize].kind);
                }
            }
            for (ri, rd) in l.roads.iter().enumerate() {
                for k in 0..rd.points.len() - 1 {
                    let (a, bb) = (rd.points[k], rd.points[k + 1]);
                    if seg_near(r.c, a, bb).0 > r.hw + r.hd + rd.width_m {
                        continue;
                    }
                    assert!(r.seg_dist(a, bb) >= rd.width_m * 0.5, "lot {i} {:?} at {:?} is on road {ri}", lot.kind, lot.centre);
                }
            }
        }
    }

    #[test]
    fn lots_sit_on_walkable_dry_land() {
        for l in worlds() {
            lots_sit_on_walkable_dry_land_on(l);
        }
    }

    fn lots_sit_on_walkable_dry_land_on(l: &Land) {
        for (i, lot) in l.lots.iter().enumerate() {
            // Tiles are 1 m: a lot's edge may share a tile with the road beside it.
            for q in samples(lot, 0.5, 0.75) {
                let t = l.map.at(q.0, q.1);
                let ok = match t {
                    Terrain::Water | Terrain::Rock => false,
                    // Towers stand on their wall; lamps at a road's edge; plaza lots on paving.
                    // On terraces, gardens and fields step over a drop's wall, and a building's
                    // edge (which blocks where the land is hosted) or a lamp post may stand by one.
                    Terrain::Wall | Terrain::Drop => lot.frontage == Frontage::Wall(lot.settlement) || (l.settlements[lot.settlement as usize].terrace_m > 0.0 && (matches!(lot.kind, LotKind::Garden | LotKind::Field | LotKind::Lamp) || crate::host::blocks(lot.kind))),
                    Terrain::Road => lot.kind == LotKind::Lamp || in_plaza(l, lot),
                    _ => true,
                };
                assert!(ok, "lot {i} {:?} at {:?} stands on {t:?}", lot.kind, q);
                assert!(l.sd_at(q.0, q.1) > 0.0, "lot {i} in water");
            }
        }
    }

    #[test]
    fn every_lot_fronts_a_street() {
        for l in worlds() {
            every_lot_fronts_a_street_on(l);
        }
    }

    fn every_lot_fronts_a_street_on(l: &Land) {
        for (i, lot) in l.lots.iter().enumerate() {
            let front_mid = add(lot.centre, mul(lot.front, lot.depth_m * 0.5));
            assert!((yaw_of(lot.front) - lot.yaw).abs() < 1e-4);
            match lot.frontage {
                Frontage::Road(r) => {
                    let rd = &l.roads[r as usize];
                    let (d, _, _, np) = nearest_on(&rd.points, front_mid);
                    assert!(d <= rd.width_m * 0.5 + 5.0 * l.settlements[lot.settlement as usize].scale.max(1.0), "lot {i} {:?} is {d} m from its road", lot.kind);
                    assert!(dot(lot.front, sub(np, lot.centre)) > 0.0, "lot {i} {:?} turns its back on its road", lot.kind);
                }
                Frontage::Alley(r) => {
                    let rd = &l.roads[r as usize];
                    let (_, _, _, np) = nearest_on(&rd.points, front_mid);
                    assert!(dot(lot.front, sub(np, lot.centre)) > 0.0, "lot {i} {:?} behind the frontage turns its back on its road", lot.kind);
                }
                Frontage::Plaza(s) => {
                    let p = &l.settlements[s as usize].plaza;
                    if !poly_contains(&p.points, lot.centre) {
                        let k = l.settlements[s as usize].scale.max(1.0);
                        assert!(poly_outside(&p.points, front_mid) < 4.0 * k, "lot {i} {:?} is {} m off its plaza", lot.kind, poly_outside(&p.points, front_mid));
                        assert!(dot(lot.front, sub(p.centre, lot.centre)) > 0.0, "lot {i} faces away from its plaza");
                    }
                }
                Frontage::Lot(h) => {
                    let house = &l.lots[h as usize];
                    assert!(matches!(house.kind, LotKind::House | LotKind::Townhouse));
                    assert!(lot.rect().gap(&house.rect()) < 2.0, "garden {i} is away from its house");
                }
                Frontage::Wall(s) => {
                    let w = l.settlements[s as usize].wall.as_ref().unwrap();
                    let mut ring = w.ring.clone();
                    ring.push(w.ring[0]);
                    assert!(nearest_on(&ring, lot.centre).0 < lot.depth_m, "tower {i} is off the wall");
                }
            }
        }
    }

    #[test]
    fn roads_connect_every_settlement() {
        for l in worlds() {
            roads_connect_every_settlement_on(l);
        }
    }

    fn roads_connect_every_settlement_on(l: &Land) {
        // Union-find over roads and settlements, joined by road ends.
        let n = l.roads.len() + l.settlements.len();
        let mut up: Vec<usize> = (0..n).collect();
        fn find(up: &mut [usize], mut a: usize) -> usize {
            while up[a] != a {
                up[a] = up[up[a]];
                a = up[a];
            }
            a
        }
        for (ri, r) in l.roads.iter().enumerate() {
            for (e, end) in r.ends.iter().enumerate() {
                let q = if e == 0 { r.points[0] } else { *r.points.last().unwrap() };
                let other = match *end {
                    RoadEnd::Road(o) => {
                        let o = &l.roads[o as usize];
                        let d = nearest_on(&o.points, q).0;
                        assert!(d <= o.width_m * 0.5 + 1.0, "{} m: road {ri} {:?} {:?} ends {d} m from the road it joins ({:?} {:?})", l.size, r.class, r.ends, o.class, o.ends);
                        Some(l.roads.iter().position(|x| std::ptr::eq(x, o)).unwrap())
                    }
                    RoadEnd::Plaza(s) => {
                        assert!(poly_outside(&l.settlements[s as usize].plaza.points, q) < 1.5, "road {ri} stops short of its plaza");
                        Some(l.roads.len() + s as usize)
                    }
                    _ => None,
                };
                if let Some(o) = other {
                    let (a, b) = (find(&mut up, ri), find(&mut up, o));
                    up[a] = b;
                }
            }
            assert!(r.points.len() == r.heights.len() && r.crossfall.len() + 1 == r.points.len());
            assert!(r.crossfall.iter().all(|c| c.abs() <= 0.0301));
        }
        let root = find(&mut up, l.roads.len());
        for s in 0..l.settlements.len() {
            assert_eq!(find(&mut up, l.roads.len() + s), root, "settlement {s} is not on the road network at {} m", l.size);
        }
        // Every river crossing is walkable.
        for c in &l.crossings {
            assert!(l.map.at(c.at.0, c.at.1).walkable(), "crossing at {:?} is not walkable", c.at);
        }
    }

    #[test]
    fn pads_are_level() {
        for l in worlds() {
            pads_are_level_on(l);
        }
    }

    fn pads_are_level_on(l: &Land) {
        for (i, lot) in l.lots.iter().enumerate() {
            if !lot.kind.padded() {
                continue;
            }
            for q in samples(lot, 0.7, 0.0) {
                let h = l.height(q.0, q.1);
                assert!((h - lot.floor_m).abs() < 2e-3, "lot {i} {:?}: ground {h} at {q:?}, floor {}", lot.kind, lot.floor_m);
            }
        }
        for s in &l.settlements {
            for q in &s.plaza.points {
                let p = add(mul(*q, 0.9), mul(s.plaza.centre, 0.1));
                assert!((l.height(p.0, p.1) - s.plaza.floor_m).abs() < 2e-3, "plaza not level");
            }
        }
    }

    #[test]
    fn roads_follow_their_profile() {
        let l = world();
        // Away from junctions, lots and water, the centre line is at the graded height.
        let mut checked = 0;
        for r in l.roads.iter().filter(|r| r.class == RoadClass::Trunk) {
            for i in (5..r.points.len().saturating_sub(5)).step_by(7) {
                let p = r.points[i];
                let quiet = l.sd_at(p.0, p.1) > 7.0
                    && l.lots.iter().all(|x| dist(x.centre, p) > x.width_m + x.depth_m + 12.0)
                    && l.roads.iter().filter(|o| !std::ptr::eq(*o, r)).all(|o| nearest_on(&o.points, p).0 > o.width_m + 8.0)
                    && l.settlements.iter().all(|s| poly_outside(&s.plaza.points, p) > 20.0);
                if quiet {
                    assert!((l.height(p.0, p.1) - r.heights[i]).abs() < 0.02, "road off its profile at {p:?} by {}", l.height(p.0, p.1) - r.heights[i]);
                    checked += 1;
                }
            }
        }
        assert!(checked > 50, "only {checked} points checked");
    }

    #[test]
    fn height_stays_continuous_through_the_town() {
        let l = world();
        let t = l.settlements.iter().find(|s| s.kind == SiteKind::Town).unwrap();
        for dy in [-31.3f32, 0.4, 17.7] {
            let y = t.centre.1 + dy;
            let mut x = t.centre.0 - t.radius_m - 30.0;
            let mut prev = l.height(x, y);
            while x < t.centre.0 + t.radius_m + 30.0 {
                x += 0.02;
                let h = l.height(x, y);
                assert!(h.is_finite() && (h - prev).abs() < 0.25, "jump of {} at ({x}, {y})", h - prev);
                prev = h;
            }
        }
    }

    #[test]
    fn lots_match_their_models() {
        for l in worlds() {
            lots_match_their_models_on(l);
        }
    }

    /// Every lot with a model kind names a model of its settlement's style and kind (when the
    /// table has some), and is that model's footprint plus the style's margin all round.
    fn lots_match_their_models_on(l: &Land) {
        let p = SettleParams::default();
        for (i, lot) in l.lots.iter().enumerate() {
            let set = &l.settlements[lot.settlement as usize];
            let st = p.style_for(set.kind, &set.style).unwrap();
            let Some(kind) = st.model_kind(lot.kind) else {
                assert!(lot.model_file.is_none(), "lot {i} {:?} names a model", lot.kind);
                continue;
            };
            let kit = p.kit(&set.style);
            let any = p.buildings.models.iter().any(|m| m.style == kit && m.kind == kind);
            let Some(file) = lot.model_file.as_deref() else {
                assert!(!any, "lot {i} {:?} names no model", lot.kind);
                continue;
            };
            let m = p.buildings.model(file).unwrap_or_else(|| panic!("lot {i} names {file}, not in the table"));
            assert_eq!((m.style.as_str(), m.kind.as_str()), (kit, kind), "lot {i}");
            assert_eq!(lot.height_m, m.height_m);
            // Lamps and stalls take a smaller margin than buildings.
            let margin = st.margin_m * 2.0 + 1e-3;
            for (lot_m, model_m, what) in [(lot.width_m, m.width_m, "width"), (lot.depth_m, m.depth_m, "depth")] {
                assert!(lot_m >= model_m - 1e-3 && lot_m <= model_m + margin, "lot {i} {:?} {what} {lot_m} for a model {model_m} wide ({file})", lot.kind);
            }
        }
    }

    #[test]
    fn a_town_has_an_inn_a_hall_and_a_chapel() {
        for l in worlds() {
            a_town_has_an_inn_a_hall_and_a_chapel_on(l);
        }
    }

    fn a_town_has_an_inn_a_hall_and_a_chapel_on(l: &Land) {
        let town = l.settlements.iter().find(|s| s.kind == SiteKind::Town).unwrap();
        let lots = &l.lots[town.lots.0 as usize..town.lots.1 as usize];
        for kind in [LotKind::Inn, LotKind::Hall, LotKind::Chapel] {
            assert_eq!(lots.iter().filter(|x| x.kind == kind).count(), 1, "{} m: the town has no single {kind:?}", l.size);
        }
        let landmark = &l.lots[town.landmark.expect("the town has a landmark") as usize];
        assert_eq!(landmark.kind, LotKind::Chapel, "the town's landmark");
        // Big buildings stand on the square (or a main street) and are bigger than any house.
        let biggest_home = lots.iter().filter(|x| matches!(x.kind, LotKind::House | LotKind::Townhouse)).map(|x| x.width_m * x.depth_m).fold(0.0, f32::max);
        for x in lots.iter().filter(|x| x.kind.big()) {
            assert!(x.width_m * x.depth_m > biggest_home, "{:?} is {} m² against a {biggest_home} m² house", x.kind, x.width_m * x.depth_m);
            assert!(matches!(x.frontage, Frontage::Plaza(_)) || matches!(x.frontage, Frontage::Road(r) if l.roads[r as usize].class != RoadClass::Lane));
        }
    }

    #[test]
    fn towns_vary() {
        for l in worlds() {
            towns_vary_on(l);
        }
    }

    /// The town's homes come in many footprints and forms, with corner buildings at junctions.
    fn towns_vary_on(l: &Land) {
        let p = SettleParams::default();
        let town = l.settlements.iter().find(|s| s.kind == SiteKind::Town).unwrap();
        let homes: Vec<&Lot> = l.lots[town.lots.0 as usize..town.lots.1 as usize].iter().filter(|x| matches!(x.kind, LotKind::House | LotKind::Townhouse)).collect();
        let mut feet: Vec<(i32, i32)> = homes.iter().map(|x| ((x.width_m * 2.0).round() as i32, (x.depth_m * 2.0).round() as i32)).collect();
        feet.sort();
        feet.dedup();
        assert!(feet.len() >= 20, "{} m: only {} distinct footprints among {} homes", l.size, feet.len(), homes.len());
        let mut forms: Vec<(&str, &str)> = homes.iter().map(|x| p.buildings.model(x.model_file.as_deref().unwrap()).unwrap()).map(|m| (m.kind.as_str(), m.form.as_str())).collect();
        forms.sort();
        forms.dedup();
        assert!(forms.len() >= 6, "{} m: only the forms {forms:?}", l.size);
        let widths: Vec<f32> = homes.iter().map(|x| x.width_m).collect();
        let (lo, hi) = (widths.iter().cloned().fold(f32::MAX, f32::min), widths.iter().cloned().fold(0.0, f32::max));
        assert!(hi > lo * 1.8, "{} m: frontages only run {lo}-{hi} m", l.size);
    }

    #[test]
    fn corner_buildings_turn_to_both_streets() {
        for l in worlds() {
            corner_buildings_turn_to_both_streets_on(l);
        }
    }

    /// A corner building's second street front faces a road other than its own.
    fn corner_buildings_turn_to_both_streets_on(l: &Land) {
        let p = SettleParams::default();
        let mut n = 0;
        for (i, lot) in l.lots.iter().enumerate() {
            let Some(m) = lot.model_file.as_deref().and_then(|f| p.buildings.model(f)) else { continue };
            if m.corner == 0 {
                continue;
            }
            n += 1;
            let set = &l.settlements[lot.settlement as usize];
            let st = p.style_for(set.kind, &set.style).unwrap();
            let k = set.scale;
            // The model's +X is (front.1, -front.0) on the map.
            let side = mul((lot.front.1, -lot.front.0), m.corner as f32);
            let q = add(lot.centre, mul(side, lot.width_m * 0.5));
            let near = l.roads.iter().enumerate().any(|(ri, rd)| lot.frontage != Frontage::Road(ri as u32) && nearest_on(&rd.points, q).0 - rd.width_m * 0.5 < st.setback_m + 3.0 * k.max(0.4) + 0.5);
            assert!(near, "corner lot {i} at {:?} has no road on its corner side", lot.centre);
        }
        assert!(n >= 4, "{} m: only {n} corner buildings", l.size);
    }

    #[test]
    fn params_and_footprints_are_data() {
        let p = SettleParams::default();
        for kind in [LotKind::House, LotKind::Townhouse, LotKind::Inn, LotKind::Hall, LotKind::Chapel, LotKind::Workshop, LotKind::Barn, LotKind::Tower, LotKind::Well, LotKind::MarketStall, LotKind::Lamp] {
            assert!(p.buildings.get("fantasy", kind).is_some(), "no fantasy {kind:?} footprint");
            assert!(p.buildings.models.iter().any(|m| m.style == "fantasy" && m.kind == kind.id()), "no fantasy {kind:?} models");
        }
        for k in LotKind::ALL {
            assert_eq!(LotKind::from_id(k.id()), Some(k));
        }
        let json = serde_json::to_string(&p).unwrap();
        let back: SettleParams = serde_json::from_str(&json).unwrap();
        assert_eq!(back.styles.len(), p.styles.len());
        let partial: LandParams = serde_json::from_str(r#"{"settlements": {"roads": {"grid_m": 6.0}}}"#).unwrap();
        assert_eq!(partial.settlements.roads.grid_m, 6.0);
        assert_eq!(partial.settlements.styles.len(), p.styles.len());
    }

    /// Slow: `cargo test --release -p living-rules settle::tests::settle_sweep -- --ignored`.
    #[test]
    #[ignore]
    fn settle_sweep() {
        for size in [1024, 2048, 3072] {
            for seed in [5, 7, 9, 11, 23] {
                let l = generate_default(seed, size);
                println!("seed {seed} size {size}: {} settlements, {} lots, {} roads", l.settlements.len(), l.lots.len(), l.roads.len());
                every_settlement_is_laid_out_on(&l);
                lots_do_not_overlap_each_other_or_roads_on(&l);
                lots_sit_on_walkable_dry_land_on(&l);
                every_lot_fronts_a_street_on(&l);
                roads_connect_every_settlement_on(&l);
                pads_are_level_on(&l);
                lots_match_their_models_on(&l);
                a_town_has_an_inn_a_hall_and_a_chapel_on(&l);
                towns_vary_on(&l);
                corner_buildings_turn_to_both_streets_on(&l);
                ornaments_keep_doors_and_streets_clear_on(&l);
                stairs_connect_levels_on(&l);
                terraces_are_level_on(&l);
                walkable_ground_has_no_cliffs_on(&l);
            }
        }
    }

    /// Ornaments stand off every carriageway, out of buildings and away from doors and the way
    /// out of them; the ones that block stand in a plaza or beside a building, never in a lane.
    #[test]
    fn ornaments_keep_doors_and_streets_clear() {
        for l in worlds() {
            ornaments_keep_doors_and_streets_clear_on(l);
        }
        // The island's settlements are dressed with what their styles ask for.
        let l = world();
        let count = |k: PropKind| l.props.iter().filter(|p| p.kind == k).count();
        for k in [PropKind::Bench, PropKind::Fence, PropKind::Gate, PropKind::Tree, PropKind::Barrel, PropKind::Kerb, PropKind::Banner, PropKind::Sign, PropKind::FlowerBox, PropKind::MarketCross, PropKind::Fountain] {
            assert!(count(k) > 0, "no {k:?} on the island");
        }
        eprintln!("props on the island: {}", l.props.len());
        for s in l.settlements.iter().filter(|s| s.kind != SiteKind::SmallFolk && s.style != "hamlet") {
            let i = l.settlements.iter().position(|x| std::ptr::eq(x, s)).unwrap() as u16;
            assert!(l.props.iter().any(|p| p.settlement == i && p.kind == PropKind::Bench), "{:?} {} has no bench", s.kind, s.style);
        }
    }

    fn ornaments_keep_doors_and_streets_clear_on(l: &Land) {
        let p = SettleParams::default();
        for (i, pr) in l.props.iter().enumerate() {
            assert!((yaw_of(pr.front) - pr.yaw).abs() < 1e-4);
            let file = pr.model_file.as_deref().expect("a prop names its model");
            let m = p.buildings.model(file).unwrap_or_else(|| panic!("prop {i} names {file}, not in the table"));
            assert_eq!((m.style.as_str(), m.kind.as_str()), (p.kit(&l.settlements[pr.settlement as usize].style), pr.kind.id()), "prop {i}");
            // Overhead by design: cables, spans, and the city's highways and wall towers.
            if matches!(pr.kind, PropKind::Cable | PropKind::Kerb | PropKind::Highway | PropKind::WallTower | PropKind::Crane) || (pr.kind == PropKind::WashingLine && m.form.starts_with("span")) {
                continue;
            }
            let r = pr.base();
            for rd in &l.roads {
                for k in 0..rd.points.len() - 1 {
                    let (a, b) = (rd.points[k], rd.points[k + 1]);
                    if seg_near(r.c, a, b).0 < r.hw + r.hd + rd.width_m {
                        // Stairs may meet a street at their foot or head.
                        let need = if pr.kind == PropKind::Stairs { 0.0 } else { rd.width_m * 0.5 };
                        let rr = if pr.kind == PropKind::Stairs { Rect { hd: (r.hd - 1.2).max(0.3), ..r } } else { r };
                        assert!(rr.seg_dist(a, b) >= need - 1e-3, "prop {i} {:?} at {:?} is on a road", pr.kind, pr.centre);
                    }
                }
            }
            for (j, lot) in l.lots.iter().enumerate() {
                if dist(lot.centre, r.c) > lot.width_m + lot.depth_m + r.hw + r.hd {
                    continue;
                }
                if lot.kind.padded() || matches!(lot.kind, LotKind::MarketStall) {
                    // Signs and flower boxes stand against the wall, in the lot's margin.
                    let attached = matches!(pr.kind, PropKind::Sign | PropKind::NeonSign | PropKind::FlowerBox);
                    let shrunk = Rect { hw: lot.width_m * 0.5 - p.style_for(l.settlements[lot.settlement as usize].kind, &l.settlements[lot.settlement as usize].style).unwrap().margin_m, hd: lot.depth_m * 0.5 - p.style_for(l.settlements[lot.settlement as usize].kind, &l.settlements[lot.settlement as usize].style).unwrap().margin_m, ..lot.rect() };
                    let gap = if attached { r.gap(&shrunk) } else { r.gap(&lot.rect()) };
                    assert!(gap > 0.0, "prop {i} {:?} at {:?} stands in lot {j} {:?}", pr.kind, pr.centre, lot.kind);
                }
                if lot.kind.padded() && !matches!(lot.kind, LotKind::Well | LotKind::Tower) && pr.kind != PropKind::RetainingWall {
                    let door = add(lot.centre, mul(lot.front, lot.depth_m * 0.5 + 0.5));
                    let k = l.settlements[lot.settlement as usize].scale.max(0.3);
                    assert!(r.outside(door) > 0.5 * k, "prop {i} {:?} at {:?} blocks the door of lot {j}", pr.kind, pr.centre);
                }
            }
            if pr.kind.blocks() {
                let set = &l.settlements[pr.settlement as usize];
                let in_plaza = poly_contains(&set.plaza.points, pr.centre);
                let by_building = l.lots.iter().any(|lot| lot.kind.padded() && r.gap(&lot.rect()) < 3.0);
                assert!(in_plaza || by_building || matches!(pr.kind, PropKind::Kiosk | PropKind::FoodStall | PropKind::Vending), "blocking prop {i} {:?} stands in the open at {:?}", pr.kind, pr.centre);
            }
        }
    }

    /// Every stair climbs one terrace step, its ground rising evenly from foot to head, and
    /// every tile along it is walkable with no step a person cannot climb.
    #[test]
    fn stairs_connect_levels() {
        for l in worlds() {
            stairs_connect_levels_on(l);
        }
    }

    fn stairs_connect_levels_on(l: &Land) {
        for (i, st) in l.props.iter().enumerate().filter(|(_, p)| p.kind == PropKind::Stairs) {
            let set = &l.settlements[st.settlement as usize];
            let rise = set.terrace_m;
            assert!(rise > 0.0, "stairs {i} in a settlement without terraces");
            let k = set.scale.max(0.3);
            let n = 12;
            let mut prev = f32::MIN;
            for j in 0..=n {
                // From the foot (front) to the head.
                let t = st.depth_m * (0.5 - j as f32 / n as f32);
                let q = add(st.centre, mul(st.front, t));
                let h = l.height(q.0, q.1);
                let want = st.floor_m + rise * j as f32 / n as f32;
                assert!((h - want).abs() < 0.05 * k + rise * 0.02, "stairs {i}: ground {h} at {j}/{n}, wanted {want}");
                assert!(h >= prev - 1e-3, "stairs {i} do not climb");
                prev = h;
                // The flight's own tiles (not the edge tiles its ends share with the landings).
                let tile = (q.0.floor() as i32, q.1.floor() as i32);
                if j > 0 && j < n {
                    assert!(l.map.walkable(tile.0, tile.1), "stairs {i}: tile {tile:?} ({j}/{n}) is not walkable");
                }
            }
            // Walking tile by tile (4-connected, no step over CLIMB_M) from just beyond its foot
            // reaches just beyond its head, through the stair's own tiles.
            let climb = terrace::CLIMB_M * k + 1e-3;
            let tile = |p: V2| (p.0.floor() as i32, p.1.floor() as i32);
            let foot = tile(add(st.centre, mul(st.front, st.depth_m * 0.5 + 0.7 * k)));
            let head = tile(sub(st.centre, mul(st.front, st.depth_m * 0.5 + 0.7 * k)));
            let around = Rect { hw: st.width_m * 0.5 + 1.0, hd: st.depth_m * 0.5 + 2.0 * k, ..st.rect() };
            let h = |t: (i32, i32)| l.height(t.0 as f32 + 0.5, t.1 as f32 + 0.5);
            let mut seen = vec![foot];
            let mut stack = vec![foot];
            while let Some(t) = stack.pop() {
                for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                    let q = (t.0 + dx, t.1 + dy);
                    if seen.contains(&q) || !l.map.walkable(q.0, q.1) || around.outside((q.0 as f32 + 0.5, q.1 as f32 + 0.5)) > 0.0 || (h(q) - h(t)).abs() > climb {
                        continue;
                    }
                    seen.push(q);
                    stack.push(q);
                }
            }
            assert!(l.map.walkable(foot.0, foot.1) && l.map.walkable(head.0, head.1), "stairs {i}: an end is blocked");
            assert!(seen.contains(&head), "stairs {i} at {:?}: no walk from foot to head", st.centre);
        }
    }

    /// A terraced settlement's ground is level on each terrace (away from roads, pads, stairs
    /// and drops), and its plaza is one of the terraces.
    #[test]
    fn terraces_are_level() {
        for l in worlds() {
            terraces_are_level_on(l);
        }
    }

    fn terraces_are_level_on(l: &Land) {
        for z in &l.mods.terr {
            let set = l.settlements.iter().find(|s| s.site == z.site).unwrap();
            assert!((z.snap(set.plaza.floor_m) - set.plaza.floor_m).abs() < 1e-3, "plaza off its terrace");
            let mut checked = 0;
            let r = z.r_in * 0.9;
            let mut y = z.c.1 - r;
            while y < z.c.1 + r {
                let mut x = z.c.0 - r;
                while x < z.c.0 + r {
                    let q = (x, y);
                    x += 3.1;
                    if dist(q, z.c) > r || l.sd_at(q.0, q.1) < 14.0 || z.weight(q) < 1.0 {
                        continue;
                    }
                    let i = z.index(q);
                    let lvl = z.plateau(i);
                    if (z.level(q) - lvl).abs() > 1e-4 {
                        continue; // on a drop
                    }
                    let skirt = SettleParams::default().style_for(set.kind, &set.style).unwrap().skirt_m;
                    let quiet = l.roads.iter().all(|rd| nearest_on(&rd.points, q).0 > rd.width_m * 1.5 + 3.5)
                        && l.lots.iter().all(|lot| lot.rect().outside(q) > skirt + 1.5)
                        && l.props.iter().filter(|p| p.kind == PropKind::Stairs).all(|p| p.rect().outside(q) > 1.0)
                        && l.settlements.iter().all(|s| poly_outside(&s.plaza.points, q) > skirt * 2.0 + 1.5);
                    if quiet {
                        let h = l.height(q.0, q.1);
                        assert!((h - lvl).abs() < 2e-3, "terrace at {q:?} is {h}, its level {lvl}");
                        checked += 1;
                    }
                }
                y += 3.1;
            }
            eprintln!("terraces of site {}: {checked} points level", z.site);
        }
    }

    /// Inside terraced settlements, no two neighbouring walkable tiles differ by more than a
    /// person can step: drops are walled except where roads, ramps and stairs cross them.
    #[test]
    fn walkable_ground_has_no_cliffs() {
        for l in worlds() {
            walkable_ground_has_no_cliffs_on(l);
        }
    }

    fn walkable_ground_has_no_cliffs_on(l: &Land) {
        // What the authority hosts: buildings block.
        let (hosted, _) = crate::host::hosted_map(l, &LandParams::default());
        let l_map = &hosted;
        for z in &l.mods.terr {
            let climb = terrace::CLIMB_M * (z.drop_m / 0.8);
            let r = z.r_out as i32;
            let mut worst = 0.0f32;
            for y in z.c.1 as i32 - r..z.c.1 as i32 + r {
                for x in z.c.0 as i32 - r..z.c.0 as i32 + r {
                    if !l_map.walkable(x, y) {
                        continue;
                    }
                    let h = l.height(x as f32 + 0.5, y as f32 + 0.5);
                    for (dx, dy) in [(1, 0), (0, 1)] {
                        if l_map.walkable(x + dx, y + dy) {
                            let d = (h - l.height((x + dx) as f32 + 0.5, (y + dy) as f32 + 0.5)).abs();
                            // Road against road is the roads' own grading (a road's edge by a
                            // river, where shaping fades out, can step); reported, not walled.
                            let both_road = l_map.get(x, y) == Terrain::Road && l_map.get(x + dx, y + dy) == Terrain::Road;
                            if both_road {
                                worst = worst.max(d);
                            } else {
                                assert!(d <= climb + 1e-3, "a {d} m step between walkable tiles at ({x}, {y})");
                            }
                        }
                    }
                }
            }
            eprintln!("terraces of site {}: no step over {climb} m off the roads; steepest road-to-road step {worst:.2} m", z.site);
        }
    }

    /// The island has a steampunk and a cyberpunk town of their own: laid out in their styles,
    /// with their landmarks, and reachable by road (`roads_connect_every_settlement`).
    #[test]
    fn styled_towns_stand_on_the_island() {
        let l = world();
        let p = SettleParams::default();
        for (style, landmark) in [("steampunk", "clocktower"), ("cyberpunk", "landmark")] {
            let (i, s) = l.settlements.iter().enumerate().find(|(_, s)| s.style == style).unwrap_or_else(|| panic!("no {style} town"));
            assert_eq!(s.kind, SiteKind::Town);
            assert_eq!(l.sites[s.site as usize].id(), format!("{style}_town"));
            let lm = &l.lots[s.landmark.expect("a landmark") as usize];
            assert_eq!(p.buildings.model(lm.model_file.as_deref().unwrap()).unwrap().kind, landmark, "{style} landmark");
            let lots = &l.lots[s.lots.0 as usize..s.lots.1 as usize];
            assert!(lots.iter().filter(|x| matches!(x.kind, LotKind::House | LotKind::Townhouse)).count() >= 20, "{style}: few homes");
            assert!(lots.iter().all(|x| x.model_file.as_deref().is_none_or(|f| f.starts_with(env_of(style)))), "{style}: a lot of another style");
            eprintln!("{style} town {i} at {:?}: {} lots, terraces {} m", s.centre, lots.len(), s.terrace_m);
        }
        // The hill town is terraced: its buildings stand on at least three levels, and stairs join them.
        let hill = l.settlements.iter().position(|s| s.style == "steampunk").unwrap();
        let z = l.mods.terr.iter().find(|z| z.site == l.settlements[hill].site).expect("the steampunk town is terraced");
        let mut levels: Vec<i32> = l.lots[l.settlements[hill].lots.0 as usize..l.settlements[hill].lots.1 as usize].iter().filter(|x| x.kind.padded()).map(|x| z.index(x.centre)).collect();
        levels.sort();
        levels.dedup();
        assert!(levels.len() >= 3, "the hill town's buildings stand on levels {levels:?}");
        let stairs = l.props.iter().filter(|p| p.kind == PropKind::Stairs && p.settlement == hill as u16).count();
        let walls = l.props.iter().filter(|p| p.kind == PropKind::RetainingWall && p.settlement == hill as u16).count();
        assert!(stairs >= 3 && walls >= 10, "the hill town has {stairs} stairs and {walls} retaining walls");
        // Flat towns stay flat: the walled town is not terraced.
        let town = l.settlements.iter().find(|s| s.kind == SiteKind::Town && s.style == "fantasy").unwrap();
        eprintln!("walled town terraces: {} m", town.terrace_m);
    }
}
