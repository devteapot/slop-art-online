//! Runs a bench module under wasmtime 39.0.1 configured as SpacetimeDB 2.14.1 configures its
//! main-lane (reducer) engine: crates/core/src/host/wasmtime/mod.rs `wasmtime_config(_, false)`
//! — Cranelift at OptLevel::Speed, fuel metering on, epoch interruption on (a 10 ms ticker
//! whose deadline callback only logs and continues), WASM backtrace details on.
//!
//! usage: sb-host <module.wasm> <kind,kind,...> [--no-fuel] [--dumps DIR] [--batches N]
//!                [--laws rates,strike,cooldown,perceived,rates-law] [--calls N]
//! Prints one JSON line per (engine, law). The laws default to the three every engine runs.
//!
//! `--calls N`: every batch makes exactly N calls, after one warm-up batch of N, instead of a
//! count sized to about 200 µs of this machine's time. With N a multiple of every fixture
//! set's length (64: 64 rates and strike contexts, 16 perceptions and gives, 8 skills), each
//! batch covers each fixture exactly once, so `fuel_per_call` is a pure function of the module
//! and the fixtures: the same in every run on every machine (gate.py).
//!
//! `--seeds K`: measure in K fresh instances of the module, instance i with Rhai's hashing keys
//! number i (`sb_seed`, sb_bench::fix_hashing). Where Rhai's tables put an entry depends on its
//! keys, so the fuel of a call does too; each build of the authority draws its keys at random
//! when ahash is compiled. The mean over a fixed set of keys is what a build costs on average,
//! and it moves only when the code or the fixtures do. Each line then gives the mean
//! (`fuel_per_call`) and every key's own (`fuel_seeds`); a law's outputs must not depend on the
//! keys (`digest`, checked).

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
    let calls: Option<u32> = opt("--calls").map(|v| v.parse().unwrap());
    // `--fuel-batches`: also print every batch's fuel (with `--calls 1`, each fixture's).
    let fuel_batches = args.iter().any(|a| a == "--fuel-batches");
    let seeds: u32 = opt("--seeds").map_or(1, |v| v.parse().unwrap());
    let laws: Vec<Law> = opt("--laws").map_or(Law::ALL.to_vec(), |v| v.split(',').map(|n| Law::from_name(n).unwrap_or_else(|| panic!("unknown law {n}"))).collect());

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
    let size = bytes.len();
    let refuel = |store: &mut Store<()>| {
        if fuel {
            store.set_fuel(BUDGET).unwrap();
        }
    };
    let used = |store: &Store<()>| if fuel { BUDGET - store.get_fuel().unwrap() } else { 0 };

    // Per (engine, law), over every instance.
    #[derive(Default)]
    struct Acc {
        per: Vec<f64>,
        fuel_total: u64,
        calls: u64,
        fuel_min: u64,
        fuel_max: u64,
        seed_fuel: Vec<f64>,
        each: Vec<String>,
        n: u32,
        digest: Option<u64>,
        init_ms: f64,
        init_fuel: u64,
        mem: [usize; 4],
        error: Option<String>,
    }
    let mut acc: Vec<Acc> = (0..kinds.len() * laws.len()).map(|_| Acc { fuel_min: u64::MAX, ..Default::default() }).collect();

    for seed in 0..seeds {
        let mut store = Store::new(&engine, ());
        store.epoch_deadline_callback(|_| Ok(UpdateDeadline::Continue(EPOCH_TICKS_PER_SECOND)));
        store.set_epoch_deadline(EPOCH_TICKS_PER_SECOND);
        if fuel {
            store.set_fuel(BUDGET)?;
        }
        let instance = linker.instantiate(&mut store, &module)?;
        let memory = instance.get_memory(&mut store, "memory").expect("memory");
        let f = |store: &mut Store<()>, n: &str| instance.get_func(&mut *store, n).unwrap_or_else(|| panic!("export {n}"));
        // Before anything else in the instance touches Rhai. A module from before the keys were
        // fixed has no sb_seed: one instance only, with the keys its build drew.
        match instance.get_func(&mut store, "sb_seed") {
            Some(set) => set.typed::<u32, ()>(&store)?.call(&mut store, seed)?,
            None if seeds > 1 => anyhow::bail!("{path} has no sb_seed export: it cannot be measured under --seeds"),
            None => eprintln!("{path}: no sb_seed export; Rhai's hashing keys are the ones its build drew"),
        }
        let fixtures: TypedFunc<(), u32> = f(&mut store, "sb_fixtures").typed(&store)?;
        let init: TypedFunc<u32, u32> = f(&mut store, "sb_init").typed(&store)?;
        let run: TypedFunc<(u32, u32, u32), u64> = f(&mut store, "sb_run").typed(&store)?;
        let dump: TypedFunc<(u32, u32), u32> = f(&mut store, "sb_dump").typed(&store)?;
        let buf: TypedFunc<(), u32> = f(&mut store, "sb_buf").typed(&store)?;
        let read_buf = |store: &mut Store<()>, len: u32| -> anyhow::Result<String> {
            let p = buf.call(&mut *store, ())? as usize;
            Ok(String::from_utf8_lossy(&memory.data(&*store)[p..p + len as usize]).into_owned())
        };

        fixtures.call(&mut store, ())?;
        let base_mem = memory.data_size(&store);

        for (ki, kind) in kinds.iter().copied().enumerate() {
            refuel(&mut store);
            let mem0 = memory.data_size(&store);
            let t = Instant::now();
            let status = init.call(&mut store, kind as u32)?;
            let init_ms = t.elapsed().as_secs_f64() * 1e3;
            let init_fuel = used(&store);
            if status != 0 {
                for li in 0..laws.len() {
                    acc[ki * laws.len() + li].error = Some(format!("init failed ({status})"));
                }
                continue;
            }
            let mem_init = memory.data_size(&store);
            for (li, law) in laws.iter().copied().enumerate() {
                let a = &mut acc[ki * laws.len() + li];
                refuel(&mut store);
                let len = dump.call(&mut store, (kind as u32, law as u32))?;
                let text = read_buf(&mut store, len)?;
                if let (Some(dir), 0) = (&dumps, seed) {
                    std::fs::write(format!("{dir}/wasm-{}-{}.txt", kind.name(), law.name()), &text)?;
                }
                let digest = sb_bench::digest(&text);
                match a.digest {
                    Some(d) if d != digest => anyhow::bail!("{} {}: the outputs under hashing keys {seed} differ from key 0's ({digest:016x}, not {d:016x})", kind.name(), law.name()),
                    _ => a.digest = Some(digest),
                }
                let n = match calls {
                    // A fixed count: one warm-up batch, then batches of exactly n calls.
                    Some(n) => {
                        refuel(&mut store);
                        run.call(&mut store, (kind as u32, law as u32, n))?;
                        n
                    },
                    // Warm-up, then size batches to about 200 µs.
                    None => {
                        refuel(&mut store);
                        run.call(&mut store, (kind as u32, law as u32, 2000))?;
                        let t = Instant::now();
                        run.call(&mut store, (kind as u32, law as u32, 2000))?;
                        let est = t.elapsed().as_nanos() as f64 / 2000.0;
                        ((200_000.0 / est) as u32).clamp(1, 100_000)
                    },
                };
                a.n = n;
                let mut seed_total = 0u64;
                for _ in 0..batches {
                    refuel(&mut store);
                    let t = Instant::now();
                    std::hint::black_box(run.call(&mut store, (kind as u32, law as u32, n))?);
                    a.per.push(t.elapsed().as_nanos() as f64 / n as f64);
                    // The fuel of the cheapest and the dearest batch: equal when every batch made
                    // the same calls (`--calls`, a multiple of the fixture sets' lengths).
                    let f = used(&store);
                    seed_total += f;
                    a.fuel_min = a.fuel_min.min(f);
                    a.fuel_max = a.fuel_max.max(f);
                    if fuel_batches {
                        a.each.push(f.to_string());
                    }
                }
                a.fuel_total += seed_total;
                a.calls += batches as u64 * n as u64;
                a.seed_fuel.push(seed_total as f64 / (batches as f64 * n as f64));
                if seed == 0 {
                    (a.init_ms, a.init_fuel) = (init_ms, init_fuel);
                    a.mem = [base_mem, mem0, mem_init, memory.data_size(&store)];
                }
            }
        }
    }

    for (ki, kind) in kinds.iter().enumerate() {
        for (li, law) in laws.iter().enumerate() {
            let a = &mut acc[ki * laws.len() + li];
            if let Some(e) = &a.error {
                println!("{{\"module\":\"{path}\",\"engine\":\"{}\",\"error\":\"{e}\"}}", kind.name());
                break;
            }
            a.per.sort_by(|x, y| x.partial_cmp(y).unwrap());
            let q = |p: f64| a.per[((a.per.len() - 1) as f64 * p) as usize];
            let mean = a.per.iter().sum::<f64>() / a.per.len() as f64;
            let each = if fuel_batches { format!(",\"fuel_batches\":[{}]", a.each.join(",")) } else { String::new() };
            let seed_fuel: Vec<String> = a.seed_fuel.iter().map(|f| format!("{f:.1}")).collect();
            let [base_mem, mem0, mem_init, mem_run] = a.mem;
            println!(
                "{{\"module\":\"{path}\",\"size\":{size},\"compile_ms\":{compile_ms:.1},\"engine\":\"{}\",\"law\":\"{}\",\"fuel\":{fuel},\"calls_per_batch\":{},\"batches\":{batches},\"seeds\":{seeds},\"p50_ns\":{:.1},\"p99_ns\":{:.1},\"mean_ns\":{mean:.1},\"fuel_per_call\":{:.0},\"fuel_seeds\":[{}],\"fuel_total\":{},\"fuel_batch_min\":{},\"fuel_batch_max\":{},\"init_ms\":{:.2},\"init_fuel\":{},\"mem_base\":{base_mem},\"mem_before_init\":{mem0},\"mem_after_init\":{mem_init},\"mem_after_run\":{mem_run},\"digest\":\"{:016x}\"{each}}}",
                kind.name(),
                law.name(),
                a.n,
                q(0.5),
                q(0.99),
                a.fuel_total as f64 / a.calls as f64,
                seed_fuel.join(","),
                a.fuel_total,
                a.fuel_min,
                a.fuel_max,
                a.init_ms,
                a.init_fuel,
                a.digest.unwrap_or(0),
            );
        }
    }
    Ok(())
}
