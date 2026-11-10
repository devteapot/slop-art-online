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
