//! Land worlds (`map.kind = "land"`): the km-scale island of `living_rules::land`, hosted as
//! authority data (see `docs/ISLAND_AUTHORITY.md`).
//!
//! World creation generates the land once, inside `init`, and keeps only what the rules use:
//! - the tiles, with building footprints as `Wall` (`living_rules::host::hosted_map`), as the
//!   usual `terrain_chunk` rows;
//! - a `land` row with the seed, size, parameters and digests, so clients regenerate heights,
//!   water and roads themselves instead of receiving them;
//! - a `settlement` row per settlement and a `lot` row per lot, with a structure at the door
//!   of every building that shelters or stores (house, inn, hall, workshop, storage);
//! - each seeded settlement's layout for `seed::town` (hearth, stores, gates, homes, gardens).
//!
//! The `Land` itself (about 9 MB) is dropped before resources and people are placed.

use crate::common;
use crate::seed::{SeedMap, SeedTown};
use crate::tables::*;
use living_rules::city::Layout;
use living_rules::host;
use living_rules::land::{self as landgen, LandParams, SiteKind};
use living_rules::map::{chunk_of, Map};
use living_rules::settle::LotKind;
use spacetimedb::{ReducerContext, Table};

/// What world creation keeps from a generated land.
pub struct Hosted {
    pub map: Map,
    pub info: LandInfo,
    pub settlements: Vec<Planned>,
    pub lots: Vec<PlannedLot>,
    /// The roads as a graph, for the stages of a known way (`town::seat`); dropped with the rest.
    pub ways: living_rules::ways::Ways,
    /// Planned settlements' authored resources (`PlanSpec::resources`), on the land.
    pub resources: Vec<living_rules::settle::LaidResource>,
    /// Planned settlements' authored structures and lot stores (`PlanSpec::structures`,
    /// `LotSpec::contents`), on the land.
    pub structures: Vec<living_rules::settle::LaidStructure>,
}

pub struct Planned {
    pub kind: SiteKind,
    /// What a seed's `site` names it: `town`, `village`, ..., or `steampunk_town` for a town in
    /// its own style (`living_rules::land::Site::id`).
    pub site_id: String,
    pub style: String,
    /// The region kind it stands in (`meadow`, `forest`, ...), for seeds that choose a site.
    pub region: String,
    pub centre: (f32, f32),
    pub radius_m: f32,
    pub scale: f32,
    /// Gate tiles (the wall's openings), hearth/sign/store spots and garden plantings.
    pub gates: Vec<(i32, i32)>,
    pub market: Vec<(f32, f32)>,
    pub fields: Vec<(f32, f32)>,
    /// Door points of the homes, nearest the plaza first.
    pub homes: Vec<(f32, f32)>,
    /// Where one stands on the square: its middle, or, when that is built on, walkable points
    /// round its edge (each resident takes the nearest it can reach).
    pub square: Vec<(f32, f32)>,
    /// A planned settlement's lots by their plan ids, with their door points (seed `homes`,
    /// `buildings[].lot`).
    pub lots: Vec<(String, (f32, f32))>,
}

pub struct PlannedLot {
    pub settlement: u16,
    pub kind: LotKind,
    pub centre: (f32, f32),
    pub width_m: f32,
    pub depth_m: f32,
    pub yaw: f32,
    pub floor_m: f32,
    pub height_m: f32,
    pub model: String,
    pub door: (f32, f32),
    /// A planned lot's id in its plan (`living_rules::settle::LotSpec::id`), "" for generated
    /// lots: what a seed's `homes` and `buildings[].lot` and a `lot:<id>` place name. In memory
    /// only, like the rest of `Hosted`.
    pub key: String,
    /// Its named spots (seats, a stall's sides), walkable points on the land.
    pub spots: Vec<(String, (f32, f32))>,
    /// The structure kind at its door: a planned lot's own (`LotSpec::structure`), else its lot
    /// kind's ([`structure_kind`]); none: nothing stands there.
    pub structure: Option<String>,
}

/// The structure that stands at a lot's door: what the building does in the rules.
fn structure_kind(k: LotKind) -> Option<&'static str> {
    match k {
        LotKind::House | LotKind::Townhouse => Some("house"),
        LotKind::Inn => Some("inn"),
        // A chapel shelters like a hall; the lot row says what it is.
        LotKind::Hall | LotKind::Chapel => Some("hall"),
        LotKind::Workshop => Some("workshop"),
        LotKind::Barn => Some("storage"),
        _ => None,
    }
}

fn home(k: LotKind) -> bool {
    matches!(k, LotKind::House | LotKind::Townhouse)
}

/// The land's side and parameters from a seed's `map`.
/// The largest land side generation is tested at (docs/FLOORS.md, megacity-1); `Gen` itself
/// asserts 256..=16384.
pub const LAND_MAX_M: u32 = 8192;

pub fn params_of(m: &SeedMap) -> Result<(u32, LandParams), String> {
    let size = if m.size > 0 { m.size } else { m.w.max(m.h) };
    // Checked here, before a reducer gets as far as generating (where a bad side panics).
    if !(256..=LAND_MAX_M).contains(&size) || size % 16 != 0 {
        return Err(format!("map.size {size}: a land's side is a multiple of 16 from 256 to {LAND_MAX_M} m"));
    }
    let params: LandParams = if m.params.is_null() { LandParams::default() } else { serde_json::from_value(m.params.clone()).map_err(|e| format!("map.params: {e}"))? };
    // Hand-authored plans are refused here, before anything is generated or written.
    living_rules::settle::validate_plans(&params.plans, size).map_err(|e| format!("map.params.plans: {e}"))?;
    living_rules::land::validate_relief(&params.relief).map_err(|e| format!("map.params.relief: {e}"))?;
    Ok((size, params))
}

/// Generate the land in this call and plan what the world keeps of it.
pub fn generate(seed: u64, m: &SeedMap) -> Result<Hosted, String> {
    let (size, params) = params_of(m)?;
    let land = {
        let _t = spacetimedb::log_stopwatch::LogStopwatch::new("init.land.generate");
        landgen::generate(seed, size, &params)
    };
    let _t = spacetimedb::log_stopwatch::LogStopwatch::new("init.land.host");
    host(seed, m, &land, &params)
}

/// Plan what the world keeps of a generated land: the hosted tiles, digests, settlements and
/// lots. Refused when a planned settlement has a building whose door no one can reach.
pub fn host(seed: u64, m: &SeedMap, land: &landgen::Land, params: &LandParams) -> Result<Hosted, String> {
    let size = land.size;
    let (map, hosted) = host::hosted_map(land, params);
    let stranded = living_rules::settle::stranded_doors(land, &map, &hosted.reachable);
    if !stranded.is_empty() {
        return Err(format!("map.params.plans: no one can reach the doors of {}", stranded.join(", ")));
    }
    let d = host::digests(land, &map);
    log::info!(
        "land {seed} at {size} m: {} settlements, {} lots, {} roads, {} props (derived, not stored); buildings block {} tiles and cut off {}; digests tiles {:016x} heights {:016x} layout {:016x}",
        land.settlements.len(),
        land.lots.len(),
        land.roads.len(),
        land.props.len(),
        hosted.blocked_tiles,
        hosted.cut_off_tiles,
        d.tiles,
        d.heights,
        d.layout
    );
    let near = |p: (f32, f32)| map.nearest_walkable(p.0, p.1).unwrap_or(p);
    let mut settlements = Vec::new();
    for (si, s) in land.settlements.iter().enumerate() {
        let mut gates = Vec::new();
        if let Some(w) = &s.wall {
            for g in &w.gates {
                let (ox, oy) = g.out;
                let (ux, uy) = (-oy, ox);
                let r = (g.width_m + w.thickness_m).ceil() as i32 + 2;
                let (cx, cy) = (g.at.0.floor() as i32, g.at.1.floor() as i32);
                for j in cy - r..=cy + r {
                    for i in cx - r..=cx + r {
                        let (dx, dy) = (i as f32 + 0.5 - g.at.0, j as f32 + 0.5 - g.at.1);
                        let (along, across) = (dx * ux + dy * uy, dx * ox + dy * oy);
                        if along.abs() <= g.width_m * 0.5 + 1.0 && across.abs() <= w.thickness_m * 0.5 + 0.5 && map.walkable(i, j) && !gates.contains(&(i, j)) {
                            gates.push((i, j));
                        }
                    }
                }
            }
        }
        // Hearth, sign and two stores on the plaza, clear of its well and stalls. A square whose
        // middle is built on (the megacity core's arcology) has its heart on its walkable edge.
        let square: Vec<(f32, f32)> = if map.walkable(s.plaza.centre.0 as i32, s.plaza.centre.1 as i32) {
            vec![s.plaza.centre]
        } else {
            s.plaza.points.iter().step_by(2).map(|q| (q.0 * 0.9 + s.plaza.centre.0 * 0.1, q.1 * 0.9 + s.plaza.centre.1 * 0.1)).filter(|q| map.walkable(q.0 as i32, q.1 as i32)).collect()
        };
        let c = square.first().copied().unwrap_or(s.plaza.centre);
        let mut market: Vec<(f32, f32)> = Vec::new();
        for off in [(3.0, 2.0), (-3.0, 2.5), (4.0, -3.0), (-4.0, -3.0)] {
            let p = near((c.0 + off.0 * s.scale.max(0.5), c.1 + off.1 * s.scale.max(0.5)));
            market.push(p);
        }
        let mut fields = Vec::new();
        let mut homes: Vec<(f32, (f32, f32))> = Vec::new();
        for l in land.lots.iter().filter(|l| l.settlement as usize == si) {
            match l.kind {
                LotKind::Garden => fields.push(near(l.centre)),
                LotKind::Field => {
                    // A few plantings along a field's middle line.
                    let (ux, uy) = (-l.front.1, l.front.0);
                    for k in [-0.3f32, 0.0, 0.3] {
                        fields.push(near((l.centre.0 + ux * k * l.width_m, l.centre.1 + uy * k * l.width_m)));
                    }
                }
                k if home(k) => homes.push(((l.centre.0 - c.0).hypot(l.centre.1 - c.1), near(host::door(l)))),
                _ => {}
            }
        }
        homes.sort_by(|a, b| a.0.total_cmp(&b.0));
        let keyed_lots: Vec<(String, (f32, f32))> = land.plans.iter().filter(|p| p.settlement as usize == si).flat_map(|p| p.lots.iter().map(|l| (l.key.clone(), near(host::door(&land.lots[l.lot as usize]))))).collect();
        settlements.push(Planned {
            kind: s.kind,
            site_id: land.sites[s.site as usize].id(),
            style: s.style.clone(),
            region: serde_json::to_value(land.sites[s.site as usize].region).ok().and_then(|v| v.as_str().map(String::from)).unwrap_or_default(),
            centre: c,
            radius_m: s.radius_m,
            scale: s.scale,
            gates,
            market,
            fields,
            homes: homes.into_iter().map(|h| h.1).collect(),
            square,
            lots: keyed_lots,
        });
    }
    // Planned lots' ids and spots, by lot index.
    let mut keyed: std::collections::HashMap<u32, (&str, &[(String, (f32, f32))], Option<&str>)> = std::collections::HashMap::new();
    for p in &land.plans {
        for l in &p.lots {
            keyed.insert(l.lot, (l.key.as_str(), l.spots.as_slice(), l.structure.as_deref()));
        }
    }
    let lots = land
        .lots
        .iter()
        .enumerate()
        .map(|(i, l)| PlannedLot {
            settlement: l.settlement,
            kind: l.kind,
            centre: l.centre,
            width_m: l.width_m,
            depth_m: l.depth_m,
            yaw: l.yaw,
            floor_m: l.floor_m,
            height_m: l.height_m,
            model: l.model_file.clone().unwrap_or_default(),
            door: near(host::door(l)),
            key: keyed.get(&(i as u32)).map_or(String::new(), |k| k.0.to_string()),
            spots: keyed.get(&(i as u32)).map_or(Vec::new(), |k| k.1.iter().map(|(n, q)| (n.clone(), near(*q))).collect()),
            structure: keyed.get(&(i as u32)).and_then(|k| k.2).or_else(|| structure_kind(l.kind)).map(String::from),
        })
        .collect();
    // Newcomers arrive on the first town's square, where its people are (`host::arrival`).
    let arrive = host::arrival(land, &map);
    let info = LandInfo {
        id: 0,
        seed,
        size,
        params: if m.params.is_null() { "{}".into() } else { m.params.to_string() },
        tiles_digest: d.tiles,
        heights_digest: d.heights,
        layout_digest: d.layout,
        arrive_x: arrive.0,
        arrive_y: arrive.1,
    };
    // Built by the planner's last step; a land made otherwise (none today) builds it here.
    let ways = land.ways.clone().unwrap_or_else(|| living_rules::ways::Ways::of(land));
    let resources = land.plans.iter().flat_map(|p| p.resources.iter().cloned()).collect();
    // A household's own structures stand inside its lot, within reach of where one can stand.
    let structures = living_rules::settle::placed_structures(land, &map, &hosted.reachable).map_err(|e| format!("map.params.plans: {e}"))?;
    Ok(Hosted { map, info, settlements, lots, ways, resources, structures })
}

/// The seed's settlement entry for each planned settlement. An entry of a site kind (`site`, or
/// `town` for `towns` and `village` for `villages`; a town in its own style is its own kind,
/// `steampunk_town`) takes the next settlement of that kind, in order. An entry that chooses
/// (`near`, `region`) goes after those and takes the unused one of its kind in one of its
/// region kinds if any, nearest the settlement it names. Settlements without an entry stand
/// empty.
pub fn match_seed<'a>(h: &Hosted, towns: &'a [SeedTown], villages: &'a [SeedTown]) -> Vec<Option<&'a SeedTown>> {
    let entries: Vec<(&str, &SeedTown)> = towns
        .iter()
        .map(|t| (if t.site.is_empty() { "town" } else { t.site.as_str() }, t))
        .chain(villages.iter().map(|t| (if t.site.is_empty() { "village" } else { t.site.as_str() }, t)))
        .collect();
    let chooses = |t: &SeedTown| !t.near.is_empty() || !t.region.is_empty();
    let mut out: Vec<Option<&SeedTown>> = vec![None; h.settlements.len()];
    for (k, t) in entries.iter().filter(|(_, t)| !chooses(t)) {
        if let Some(i) = (0..out.len()).find(|&i| out[i].is_none() && h.settlements[i].site_id == *k) {
            out[i] = Some(*t);
        }
    }
    for (k, t) in entries.iter().filter(|(_, t)| chooses(t)) {
        let anchor = (0..out.len()).find(|&j| out[j].is_some_and(|o| o.name == t.near)).map(|j| h.settlements[j].centre);
        if anchor.is_none() && !t.near.is_empty() {
            log::warn!("{}: near {:?}, which is not a settlement placed before it; nearness ignored", t.name, t.near);
        }
        let key = |i: usize| {
            let s = &h.settlements[i];
            let off_region = !t.region.is_empty() && !t.region.contains(&s.region);
            (off_region, anchor.map_or(0.0, |a| (s.centre.0 - a.0).hypot(s.centre.1 - a.1)))
        };
        let best = (0..out.len()).filter(|&i| out[i].is_none() && h.settlements[i].site_id == *k).min_by(|&a, &b| {
            let (ka, kb) = (key(a), key(b));
            ka.0.cmp(&kb.0).then(ka.1.total_cmp(&kb.1))
        });
        if let Some(i) = best {
            out[i] = Some(*t);
        }
    }
    out
}

/// The layout `seed::town` builds a seeded settlement from.
pub fn layout(p: &Planned) -> Layout {
    Layout { center: p.centre, gates: p.gates.clone(), houses: p.homes.clone(), market: p.market.clone(), fields: p.fields.clone(), lots: p.lots.clone() }
}

/// Write the `land` row with its public parameters (`living_rules::land::public_params`: no
/// names) and keep the full ones in the private `land_plan` (owner-known).
pub fn keep_land(ctx: &ReducerContext, mut info: LandInfo) {
    let full = std::mem::take(&mut info.params);
    info.params = public_of(&full);
    ctx.db.land().insert(info);
    ctx.db.land_plan().id().delete(0);
    ctx.db.land_plan().insert(LandPlan { id: 0, params: full });
}

/// The public form of a land's parameters as JSON text. Parameters the world was made from parse;
/// should they not, the public row gets the defaults' `{}` rather than anyone's names.
fn public_of(full: &str) -> String {
    serde_json::from_str::<serde_json::Value>(full)
        .ok()
        .and_then(|v| living_rules::land::public_params(&v).ok())
        .map_or_else(|| "{}".to_string(), |v| v.to_string())
}

/// A world made before owner-known keeps its names in the public row: the next script install
/// (every `living-publish`) moves them to `land_plan` and leaves the public row without them. Once.
pub fn scrub_land(ctx: &ReducerContext) {
    if ctx.db.land_plan().id().find(0).is_some() {
        return;
    }
    if let Some(mut row) = ctx.db.land().id().find(0) {
        let full = row.params.clone();
        row.params = public_of(&full);
        ctx.db.land().id().update(row);
        ctx.db.land_plan().insert(LandPlan { id: 0, params: full });
        log::info!("scrub_land: the public land row no longer carries names (kept in land_plan)");
    }
}

/// The `land` row, lot rows and the structures at their doors (owners are set as households
/// move in).
pub fn build(ctx: &ReducerContext, h: &Hosted, now: u64) {
    keep_land(ctx, h.info.clone());
    build_lots(ctx, h, 0..h.lots.len(), now);
}

/// Lot rows `range` and the structures at their doors, in order (a staged world inserts them in
/// batches; ids follow the order either way).
pub fn build_lots(ctx: &ReducerContext, h: &Hosted, range: std::ops::Range<usize>, now: u64) {
    for (i, l) in h.lots.iter().enumerate().skip(range.start).take(range.len()) {
        let structure = l.structure.as_deref().map_or(0, |k| {
            common::invalidate_structures(ctx);
            ctx.db.structure().insert(Structure { id: 0, kind: k.into(), x: l.door.0, y: l.door.1, chunk: chunk_of(l.door.0, l.door.1), owner: 0, built_ms: now, lit_until_ms: 0 }).id
        });
        ctx.db.lot().insert(Lot {
            id: i as u32,
            settlement: l.settlement,
            kind: l.kind.id().into(),
            x: l.centre.0,
            y: l.centre.1,
            width_m: l.width_m,
            depth_m: l.depth_m,
            yaw: l.yaw,
            floor_m: l.floor_m,
            height_m: l.height_m,
            model: l.model.clone(),
            door_x: l.door.0,
            door_y: l.door.1,
            structure,
            chunk: chunk_of(l.centre.0, l.centre.1),
        });
    }
}

/// Settlement rows, once their communities exist; residents' backgrounds name their folk.
pub fn settle(ctx: &ReducerContext, h: &Hosted, seeded: &[Option<&SeedTown>], life: &crate::town::SeedTownLife) {
    for (i, p) in h.settlements.iter().enumerate() {
        let community = seeded[i].and_then(|t| ctx.db.community().iter().find(|c| c.name == t.name)).map_or(0, |c| c.id);
        ctx.db.settlement().insert(Settlement {
            id: i as u16,
            kind: p.kind.id().into(),
            style: p.style.clone(),
            x: p.centre.0,
            y: p.centre.1,
            radius_m: p.radius_m,
            scale: p.scale,
            community,
        });
        if community == 0 {
            continue;
        }
        for m in ctx.db.membership().community().filter(community).collect::<Vec<_>>() {
            let Some(mut bg) = ctx.db.background().id().find(m.member) else { continue };
            let Ok(mut v) = serde_json::from_str::<serde_json::Value>(&bg.text) else { continue };
            v["folk"] = p.kind.id().into();
            // Rounded in f64, so the JSON reads 0.35 rather than the f32's 0.3499999940395355.
            v["body_scale"] = serde_json::json!((p.scale as f64 * 1000.0).round() / 1000.0);
            v["settlement"] = serde_json::json!(i);
            bg.text = v.to_string();
            ctx.db.background().id().update(bg);
        }
        // The places its residents know: home, work, the square, where they spend evenings, and
        // what their authors gave them.
        let _t = spacetimedb::log_stopwatch::LogStopwatch::new("init.town.seat");
        crate::town::seat(ctx, h, i, community, life, seeded);
    }
}

/// Where a newcomer arrives: a land world's arrival point (its first town's square), else the
/// classic spot.
pub fn arrival(ctx: &ReducerContext) -> (f32, f32) {
    ctx.db.land().id().find(0).map_or((40.0, 60.0), |l| (l.arrive_x, l.arrive_y))
}
