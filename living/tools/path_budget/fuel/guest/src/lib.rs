//! The walk planner compiled to WASM for `pb-host`: the host loads a map's tiles, then asks for
//! legs (`Map::route_leg`, as the authority's `motion` does) or plain searches (`Map::path`)
//! and meters each call's fuel.
use living_rules::map::Map;
use living_rules::nav::{Leg, RouteSpec};
use std::cell::RefCell;

thread_local! {
    static MAP: RefCell<Option<Map>> = const { RefCell::new(None) };
    static TILES: RefCell<Vec<u8>> = const { RefCell::new(Vec::new()) };
    static LEG: RefCell<Option<Leg>> = const { RefCell::new(None) };
}

/// Room for `len` tile bytes; returns where to write them.
#[no_mangle]
pub extern "C" fn pb_tiles(len: u32) -> u32 {
    TILES.with(|t| {
        let mut t = t.borrow_mut();
        t.resize(len as usize, 0);
        t.as_mut_ptr() as u32
    })
}

/// Build the map from the written tiles (row-major), with no regions yet.
#[no_mangle]
pub extern "C" fn pb_load(w: u32, h: u32) {
    let tiles = TILES.with(|t| t.borrow().clone());
    let map = Map { w, h, tiles, blocked: Default::default(), opaque: Default::default(), nav: Default::default() };
    MAP.with(|m| *m.borrow_mut() = Some(map));
}

/// Drop every built region (a module instance's first route after loading the map).
#[no_mangle]
pub extern "C" fn pb_cold() {
    MAP.with(|m| {
        if let Some(map) = m.borrow_mut().as_mut() {
            map.nav = Default::default();
        }
    });
}

/// Plan the next leg; returns its waypoint count, or -1 when there is no route.
#[no_mangle]
pub extern "C" fn pb_leg(fx: f32, fy: f32, tx: f32, ty: f32, leg_m: f32) -> i32 {
    let leg = MAP.with(|m| m.borrow().as_ref().unwrap().route_leg((fx, fy), (tx, ty), &RouteSpec { leg_m, ..Default::default() }));
    let n = leg.as_ref().map_or(-1, |l| l.points.len() as i32);
    LEG.with(|l| *l.borrow_mut() = leg);
    n
}

fn with_leg<T>(f: impl FnOnce(&Leg) -> T) -> T {
    LEG.with(|l| f(l.borrow().as_ref().unwrap()))
}

#[no_mangle]
pub extern "C" fn pb_x(i: u32) -> f32 {
    with_leg(|l| l.points[i as usize].0)
}
#[no_mangle]
pub extern "C" fn pb_y(i: u32) -> f32 {
    with_leg(|l| l.points[i as usize].1)
}
#[no_mangle]
pub extern "C" fn pb_last() -> u32 {
    with_leg(|l| l.last as u32)
}
#[no_mangle]
pub extern "C" fn pb_areas() -> u32 {
    with_leg(|l| l.areas as u32)
}
#[no_mangle]
pub extern "C" fn pb_regions() -> u32 {
    with_leg(|l| l.regions as u32)
}
#[no_mangle]
pub extern "C" fn pb_tiles_expanded() -> u32 {
    with_leg(|l| l.tiles as u32)
}

/// Build up to `chunks` more chunks' regions ahead of time; 1 while more remain.
#[no_mangle]
pub extern "C" fn pb_warm(chunks: u32) -> u32 {
    MAP.with(|m| m.borrow().as_ref().unwrap().warm_routes(chunks as usize) as u32)
}

/// The plain tile search: waypoint count, or -1.
#[no_mangle]
pub extern "C" fn pb_path(fx: f32, fy: f32, tx: f32, ty: f32, budget: u32) -> i32 {
    MAP.with(|m| m.borrow().as_ref().unwrap().path((fx, fy), (tx, ty), budget as usize).map_or(-1, |p| p.len() as i32))
}

use living_rules::known::{Belief, Edit, Known, Search, Shape, STEERING_POPS};
use std::collections::HashMap;

struct Observation {
    blocks: HashMap<u32, Known>,
    edits: HashMap<u32, Vec<Edit>>,
    gates: HashMap<u32, bool>,
    shape: Shape,
}

thread_local! {
    static OBSERVATION: RefCell<Option<Observation>> = const { RefCell::new(None) };
    static SEARCH: RefCell<Option<Search>> = const { RefCell::new(None) };
}

/// Load the arena's JSON observation via the byte buffer. Input preparation is outside metering.
#[no_mangle]
pub extern "C" fn pb_observation() {
    let v: serde_json::Value = TILES.with(|t| serde_json::from_slice(&t.borrow()).unwrap());
    let number = |v: &serde_json::Value| v.as_u64().unwrap() as u32;
    let bytes = |v: &serde_json::Value| v.as_array().unwrap().iter().map(|v| number(v) as u8).collect::<Vec<_>>();
    MAP.with(|m| {
        let mut m = m.borrow_mut();
        let m = m.as_mut().unwrap();
        m.set_blocked(v["shut"].as_array().unwrap().iter().map(|p| number(&p[1]) * m.w + number(&p[0])).collect());
        let blocks = v["known"].as_array().unwrap().iter().map(|b| {
            (number(&b["block"]), Known::from_bytes(&bytes(&b["cells"]), &bytes(&b["seen_at"])))
        }).collect();
        let mut edits: HashMap<u32, Vec<Edit>> = HashMap::new();
        for e in v["edits"].as_array().unwrap() {
            edits.entry(number(&e["chunk"])).or_default().push(Edit {
                epoch: number(&e["epoch"]), tile: number(&e["tile"]) as u16, before: number(&e["before"]) as u8,
            });
        }
        let gates = v["gates_seen"].as_array().unwrap().iter()
            .map(|p| (number(&p[1]) * m.w + number(&p[0]), p[2].as_bool().unwrap())).collect();
        let shape = Shape {
            road_speed: v["road_speed"].as_f64().unwrap() as f32,
            unknown_cost: v["unknown_cost"].as_f64().unwrap() as f32,
            ..Default::default()
        };
        OBSERVATION.with(|o| *o.borrow_mut() = Some(Observation { blocks, edits, gates, shape }));
    });
    SEARCH.with(|s| *s.borrow_mut() = None);
}

/// One metered slice of the belief planner. -2 means resume; -1 means refused.
#[no_mangle]
pub extern "C" fn pb_belief_slice(fx: f32, fy: f32, tx: f32, ty: f32) -> i32 {
    MAP.with(|m| OBSERVATION.with(|o| SEARCH.with(|s| {
        let m = m.borrow();
        let o = o.borrow();
        let o = o.as_ref().unwrap();
        let mut search = s.borrow_mut();
        let b = Belief::new(m.as_ref().unwrap(), |key| o.blocks.get(&key).cloned(), |key| o.edits.get(&key).cloned().unwrap_or_default(), o.gates.clone());
        if search.is_none() {
            *search = Search::new(&b, (fx, fy), (tx, ty), o.shape).ok();
        }
        let Some(active) = search.as_mut() else { return -1 };
        match active.advance(&b, STEERING_POPS) {
            Some(result) => {
                *search = None;
                result.map_or(-1, |points| points.len() as i32)
            }
            None => -2,
        }
    })))
}

/// Meter the same warm true-map entry point as authority steering.
#[no_mangle]
pub extern "C" fn pb_true_first_leg(fx: f32, fy: f32, tx: f32, ty: f32) -> i32 {
    MAP.with(|m| OBSERVATION.with(|o| {
        let m = m.borrow();
        let o = o.borrow();
        let spec = RouteSpec { road_speed: o.as_ref().unwrap().shape.road_speed, ..Default::default() };
        let result = m.as_ref().unwrap().route_leg_along((fx, fy), (tx, ty), &spec, &mut Default::default());
        result.map_or(-1, |leg| leg.points.len() as i32)
    }))
}
