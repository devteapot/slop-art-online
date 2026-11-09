//! Runs a bench module under wasmtime 39.0.1 configured as SpacetimeDB 2.14.1 configures its
//! main-lane (reducer) engine: crates/core/src/host/wasmtime/mod.rs `wasmtime_config(_, false)`
//! — Cranelift at OptLevel::Speed, fuel metering on, epoch interruption on (a 10 ms ticker
//! whose deadline callback only logs and continues), WASM backtrace details on.
//!
//! usage: sb-host <module.wasm> <kind,kind,...> [--no-fuel] [--dumps DIR] [--batches N]
//! Prints one JSON line per (engine, law).

use sb_bench::{Kind, Law};
use std::time::{Duration, Instant};
use wasmtime::{Config, Engine, Linker, Module, OptLevel, Store, TypedFunc, UpdateDeadline, WasmBacktraceDetails};

const EPOCH_TICK: Duration = Duration::from_millis(10);
const EPOCH_TICKS_PER_SECOND: u64 = 100;
/// SpacetimeDB's FunctionBudget::DEFAULT_BUDGET (120 × 10⁹ fuel); refilled before each batch.
const BUDGET: u64 = 120_000_000_000;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let path = &args[1];
    let kinds: Vec<Kind> = args[2].split(',').map(|k| Kind::ALL.into_iter().find(|x| x.name() == k).unwrap_or_else(|| panic!("unknown engine {k}"))).collect();
    let fuel = !args.iter().any(|a| a == "--no-fuel");
    let opt = |name: &str| args.iter().position(|a| a == name).map(|i| args[i + 1].clone());
    let dumps = opt("--dumps");
    let batches: usize = opt("--batches").map_or(3000, |v| v.parse().unwrap());

    let mut config = Config::new();
    config.cranelift_opt_level(OptLevel::Speed).consume_fuel(fuel).epoch_interruption(true).wasm_backtrace_details(WasmBacktraceDetails::Enable);
    let engine = Engine::new(&config)?;
    let weak = engine.weak();
    std::thread::spawn(move || loop {
        std::thread::sleep(EPOCH_TICK);
        match weak.upgrade() {
            Some(e) => e.increment_epoch(),
            None => return,
        }
    });

    let bytes = std::fs::read(path)?;
    let t = Instant::now();
    let module = Module::new(&engine, &bytes)?;
    let compile_ms = t.elapsed().as_secs_f64() * 1e3;
    let mut linker: Linker<()> = Linker::new(&engine);
    // `--stub-imports`: trap stubs for imports a module should not have (Koto's wasm-bindgen
    // ones). SpacetimeDB would refuse such a module; this only lets the harness time it.
    if args.iter().any(|a| a == "--stub-imports") {
        linker.define_unknown_imports_as_traps(&module)?;
    }
    let imports: Vec<String> = module.imports().map(|i| format!("{}::{}", i.module(), i.name())).collect();
    eprintln!("{path}: {} imports {:?}", imports.len(), imports);
    let mut store = Store::new(&engine, ());
    store.epoch_deadline_callback(|_| Ok(UpdateDeadline::Continue(EPOCH_TICKS_PER_SECOND)));
    store.set_epoch_deadline(EPOCH_TICKS_PER_SECOND);
    if fuel {
        store.set_fuel(BUDGET)?;
    }
    let instance = linker.instantiate(&mut store, &module)?;
    let memory = instance.get_memory(&mut store, "memory").expect("memory");
    let f = |store: &mut Store<()>, n: &str| instance.get_func(&mut *store, n).unwrap_or_else(|| panic!("export {n}"));
    let fixtures: TypedFunc<(), u32> = f(&mut store, "sb_fixtures").typed(&store)?;
    let init: TypedFunc<u32, u32> = f(&mut store, "sb_init").typed(&store)?;
    let run: TypedFunc<(u32, u32, u32), u64> = f(&mut store, "sb_run").typed(&store)?;
    let dump: TypedFunc<(u32, u32), u32> = f(&mut store, "sb_dump").typed(&store)?;
    let buf: TypedFunc<(), u32> = f(&mut store, "sb_buf").typed(&store)?;

    let refuel = |store: &mut Store<()>| {
        if fuel {
            store.set_fuel(BUDGET).unwrap();
        }
    };
    let used = |store: &Store<()>| if fuel { BUDGET - store.get_fuel().unwrap() } else { 0 };
    let read_buf = |store: &mut Store<()>, len: u32| -> anyhow::Result<String> {
        let p = buf.call(&mut *store, ())? as usize;
        Ok(String::from_utf8_lossy(&memory.data(&*store)[p..p + len as usize]).into_owned())
    };

    fixtures.call(&mut store, ())?;
    let base_mem = memory.data_size(&store);
    let size = bytes.len();

    for kind in kinds {
        refuel(&mut store);
        let mem0 = memory.data_size(&store);
        let t = Instant::now();
        let status = init.call(&mut store, kind as u32)?;
        let init_ms = t.elapsed().as_secs_f64() * 1e3;
        let init_fuel = used(&store);
        if status != 0 {
            let len = memory.data(&store).len();
            let _ = len;
            println!("{{\"module\":\"{path}\",\"engine\":\"{}\",\"error\":\"init failed ({status})\"}}", kind.name());
            continue;
        }
        let mem_init = memory.data_size(&store);
        for law in Law::ALL {
            refuel(&mut store);
            let len = dump.call(&mut store, (kind as u32, law as u32))?;
            let text = read_buf(&mut store, len)?;
            if let Some(dir) = &dumps {
                std::fs::write(format!("{dir}/wasm-{}-{}.txt", kind.name(), law.name()), &text)?;
            }
            let digest = sb_bench::digest(&text);
            // Warm-up, then size batches to about 200 µs.
            refuel(&mut store);
            run.call(&mut store, (kind as u32, law as u32, 2000))?;
            let t = Instant::now();
            run.call(&mut store, (kind as u32, law as u32, 2000))?;
            let est = t.elapsed().as_nanos() as f64 / 2000.0;
            let n = ((200_000.0 / est) as u32).clamp(1, 100_000);
            let mut per = Vec::with_capacity(batches);
            let mut fuel_total = 0u64;
            for _ in 0..batches {
                refuel(&mut store);
                let t = Instant::now();
                std::hint::black_box(run.call(&mut store, (kind as u32, law as u32, n))?);
                per.push(t.elapsed().as_nanos() as f64 / n as f64);
                fuel_total += used(&store);
            }
            per.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let q = |p: f64| per[((per.len() - 1) as f64 * p) as usize];
            let mean = per.iter().sum::<f64>() / per.len() as f64;
            println!(
                "{{\"module\":\"{path}\",\"size\":{size},\"compile_ms\":{compile_ms:.1},\"engine\":\"{}\",\"law\":\"{}\",\"fuel\":{fuel},\"calls_per_batch\":{n},\"batches\":{batches},\"p50_ns\":{:.1},\"p99_ns\":{:.1},\"mean_ns\":{mean:.1},\"fuel_per_call\":{:.0},\"init_ms\":{init_ms:.2},\"init_fuel\":{init_fuel},\"mem_base\":{base_mem},\"mem_before_init\":{mem0},\"mem_after_init\":{mem_init},\"mem_after_run\":{},\"digest\":\"{digest:016x}\"}}",
                kind.name(),
                law.name(),
                q(0.5),
                q(0.99),
                fuel_total as f64 / (batches as f64 * n as f64),
                memory.data_size(&store)
            );
        }
    }
    Ok(())
}
