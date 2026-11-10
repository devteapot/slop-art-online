//! Fuel and time of route legs in WASM, under wasmtime configured as SpacetimeDB 2.14.1 runs
//! reducers (as `living/tools/script_bench/host`: Cranelift at OptLevel::Speed, fuel and epoch
//! interruption on). Fuel is WASM instructions: deterministic for the same inputs.
//!
//! usage: pb-host <pb_guest.wasm> <world.json> [leg_m]
//! For each of the world file's targets (the `path-budget` format), walks from `from` leg by
//! leg, re-planning 16 m before each leg's end as `motion` does, and prints per walk: the cold
//! first leg (no regions built), then the warm legs' fuel and time. Then the plain search
//! at 6,000 expansions, the authority's old first step, for the same pairs.
use std::time::Instant;
use wasmtime::{Config, Engine, Linker, Module, OptLevel, Store, TypedFunc, UpdateDeadline, WasmBacktraceDetails};

const BUDGET: u64 = 120_000_000_000;
const AHEAD: f32 = 16.0;

fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}

fn q(v: &mut [f64], p: f64) -> f64 {
    v.sort_by(|a, b| a.total_cmp(b));
    v[((v.len() - 1) as f64 * p).round() as usize]
}

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let leg_m: f32 = args.get(3).map_or(64.0, |v| v.parse().unwrap());
    let mut config = Config::new();
    config.cranelift_opt_level(OptLevel::Speed).consume_fuel(true).epoch_interruption(true).wasm_backtrace_details(WasmBacktraceDetails::Enable);
    let engine = Engine::new(&config)?;
    let module = Module::new(&engine, std::fs::read(&args[1])?)?;
    let linker: Linker<()> = Linker::new(&engine);
    let mut store = Store::new(&engine, ());
    store.epoch_deadline_callback(|_| Ok(UpdateDeadline::Continue(100)));
    store.set_epoch_deadline(100);
    store.set_fuel(BUDGET)?;
    let inst = linker.instantiate(&mut store, &module)?;
    let memory = inst.get_memory(&mut store, "memory").expect("memory");
    macro_rules! f {
        ($n:literal, $a:ty, $r:ty) => {
            inst.get_typed_func::<$a, $r>(&mut store, $n)?
        };
    }
    let tiles: TypedFunc<u32, u32> = f!("pb_tiles", u32, u32);
    let load: TypedFunc<(u32, u32), ()> = f!("pb_load", (u32, u32), ());
    let cold: TypedFunc<(), ()> = f!("pb_cold", (), ());
    let leg: TypedFunc<(f32, f32, f32, f32, f32), i32> = f!("pb_leg", (f32, f32, f32, f32, f32), i32);
    let px: TypedFunc<u32, f32> = f!("pb_x", u32, f32);
    let py: TypedFunc<u32, f32> = f!("pb_y", u32, f32);
    let last: TypedFunc<(), u32> = f!("pb_last", (), u32);
    let areas: TypedFunc<(), u32> = f!("pb_areas", (), u32);
    let regions: TypedFunc<(), u32> = f!("pb_regions", (), u32);
    let tiles_n: TypedFunc<(), u32> = f!("pb_tiles_expanded", (), u32);
    let warm: TypedFunc<u32, u32> = f!("pb_warm", u32, u32);
    let path: TypedFunc<(f32, f32, f32, f32, u32), i32> = f!("pb_path", (f32, f32, f32, f32, u32), i32);

    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(&args[2])?)?;
    let (w, h) = (v["w"].as_u64().unwrap() as u32, v["h"].as_u64().unwrap() as u32);
    let mut grid = vec![0u8; (w * h) as usize];
    for c in v["chunks"].as_array().unwrap() {
        let id = c[0].as_u64().unwrap() as u32;
        let (cx, cy) = (id & 0xFFFF, id >> 16);
        for (k, t) in c[1].as_array().unwrap().iter().enumerate() {
            let (x, y) = (cx * 16 + k as u32 % 16, cy * 16 + k as u32 / 16);
            if x < w && y < h {
                grid[(y * w + x) as usize] = t.as_u64().unwrap() as u8;
            }
        }
    }
    let p = tiles.call(&mut store, grid.len() as u32)? as usize;
    memory.data_mut(&mut store)[p..p + grid.len()].copy_from_slice(&grid);
    load.call(&mut store, (w, h))?;
    println!("wasm memory with the map loaded: {} MiB", memory.data_size(&store) >> 20);
    let from = (v["from"][0].as_f64().unwrap() as f32, v["from"][1].as_f64().unwrap() as f32);
    let targets: Vec<(String, (f32, f32))> = v["to"].as_array().unwrap().iter().map(|t| (t[0].as_str().unwrap().to_string(), (t[1].as_f64().unwrap() as f32, t[2].as_f64().unwrap() as f32))).collect();

    // One metered call: (result, fuel, ms).
    macro_rules! metered {
        ($e:expr) => {{
            store.set_fuel(BUDGET)?;
            let t = Instant::now();
            let r = $e;
            let ms = t.elapsed().as_secs_f64() * 1e3;
            (r, BUDGET - store.get_fuel()?, ms)
        }};
    }
    println!("leg_m {leg_m}");
    println!("target\tlegs\tcold first leg fuel\tms\twarm leg fuel p50\tp99\tmax\twarm leg ms p50\tp99\tmax\tmax areas\tmax regions\tmax tiles\told 6000 fuel\tms\tfound");
    let mut all_fuel = Vec::new();
    let mut all_ms = Vec::new();
    for (name, to) in &targets {
        cold.call(&mut store, ())?;
        let (n, cf, cms) = metered!(leg.call(&mut store, (from.0, from.1, to.0, to.1, leg_m))?);
        if n < 0 {
            println!("{name}\tno route (target tile blocked?)");
            continue;
        }
        // Warm walk.
        let mut at = from;
        let (mut fuels, mut mss) = (Vec::new(), Vec::new());
        let (mut ma, mut mr, mut mt) = (0, 0, 0);
        for _ in 0..2000 {
            let (n, fu, ms) = metered!(leg.call(&mut store, (at.0, at.1, to.0, to.1, leg_m))?);
            assert!(n > 0, "{name}: lost the way at {at:?}");
            fuels.push(fu as f64);
            mss.push(ms);
            ma = ma.max(areas.call(&mut store, ())?);
            mr = mr.max(regions.call(&mut store, ())?);
            mt = mt.max(tiles_n.call(&mut store, ())?);
            if last.call(&mut store, ())? == 1 {
                break;
            }
            let pts: Vec<(f32, f32)> = (0..n as u32).map(|i| Ok::<_, anyhow::Error>((px.call(&mut store, i)?, py.call(&mut store, i)?))).collect::<Result<_, _>>()?;
            let end = *pts.last().unwrap();
            'walk: for qp in &pts {
                let k = (dist(at, *qp) / 0.5).ceil().max(1.0) as usize;
                let a = at;
                for s in 1..=k {
                    let t = s as f32 / k as f32;
                    at = (a.0 + (qp.0 - a.0) * t, a.1 + (qp.1 - a.1) * t);
                    if dist(at, end) < AHEAD {
                        break 'walk;
                    }
                }
            }
        }
        all_fuel.extend(fuels.iter().copied());
        all_ms.extend(mss.iter().copied());
        let legs = fuels.len();
        let (f50, f99, fmax) = (q(&mut fuels, 0.5), q(&mut fuels, 0.99), q(&mut fuels, 1.0));
        let (m50, m99, mmax) = (q(&mut mss, 0.5), q(&mut mss, 0.99), q(&mut mss, 1.0));
        let (found, of, oms) = metered!(path.call(&mut store, (from.0, from.1, to.0, to.1, 6_000))?);
        println!("{name}\t{legs}\t{cf}\t{cms:.2}\t{f50:.0}\t{f99:.0}\t{fmax:.0}\t{m50:.3}\t{m99:.3}\t{mmax:.3}\t{ma}\t{mr}\t{mt}\t{of}\t{oms:.2}\t{}", found >= 0);
    }
    println!("all warm legs ({}): fuel p50 {:.0} p99 {:.0} max {:.0}; ms p50 {:.3} p99 {:.3} max {:.3}", all_fuel.len(), q(&mut all_fuel, 0.5), q(&mut all_fuel, 0.99), q(&mut all_fuel, 1.0), q(&mut all_ms, 0.5), q(&mut all_ms, 0.99), q(&mut all_ms, 1.0));
    println!("wasm memory after the walks: {} MiB", memory.data_size(&store) >> 20);
    // Building every region and area ahead of time, in slices as a tick would.
    cold.call(&mut store, ())?;
    let slice: u32 = std::env::var("PB_WARM_SLICE").ok().map_or(64, |v| v.parse().unwrap());
    let (mut fuels, mut mss) = (Vec::new(), Vec::new());
    loop {
        let (more, fu, ms) = metered!(warm.call(&mut store, slice)?);
        fuels.push(fu as f64);
        mss.push(ms);
        if more == 0 {
            break;
        }
    }
    let (n, total) = (fuels.len(), fuels.iter().sum::<f64>());
    println!("warm-up in slices of {slice} chunks: {n} calls, {total:.0} fuel in all ({:.1} ms); per call fuel p50 {:.0} max {:.0}, ms p50 {:.3} max {:.3}", mss.iter().sum::<f64>(), q(&mut fuels, 0.5), q(&mut fuels, 1.0), q(&mut mss, 0.5), q(&mut mss, 1.0));
    println!("wasm memory with everything built: {} MiB", memory.data_size(&store) >> 20);
    Ok(())
}
