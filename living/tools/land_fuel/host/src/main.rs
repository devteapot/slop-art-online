//! Runs lf-guest under wasmtime 39.0.1 configured as SpacetimeDB 2.14.1 configures its reducer
//! engine (crates/core/src/host/wasmtime/mod.rs `wasmtime_config(_, false)`: Cranelift at
//! OptLevel::Speed, fuel metering on, epoch interruption on), refilling the reducer budget
//! (FunctionBudget::DEFAULT_BUDGET, 120 × 10⁹ fuel) before each step, as each step would be its
//! own reducer call. Prints one line per step: fuel, share of the budget, time, linear memory.
//!
//! usage: lf-host <lf_guest.wasm> <seed.json> [size_m]

use std::time::{Duration, Instant};
use wasmtime::{Config, Engine, Linker, Module, OptLevel, Store, TypedFunc, UpdateDeadline};

const BUDGET: u64 = 120_000_000_000;

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    let seed = std::fs::read(&args[2])?;
    let size: u32 = args.get(3).map_or(0, |s| s.parse().unwrap());
    let mut config = Config::new();
    config.cranelift_opt_level(OptLevel::Speed).consume_fuel(true).epoch_interruption(true);
    let engine = Engine::new(&config)?;
    let weak = engine.weak();
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_millis(10));
        match weak.upgrade() {
            Some(e) => e.increment_epoch(),
            None => return,
        }
    });
    let module = Module::new(&engine, std::fs::read(&args[1])?)?;
    let linker: Linker<()> = Linker::new(&engine);
    let mut store = Store::new(&engine, ());
    store.epoch_deadline_callback(|_| Ok(UpdateDeadline::Continue(100)));
    store.set_epoch_deadline(100);
    store.set_fuel(BUDGET)?;
    let inst = linker.instantiate(&mut store, &module)?;
    let memory = inst.get_memory(&mut store, "memory").expect("memory");
    let input: TypedFunc<u32, u32> = inst.get_typed_func(&mut store, "lf_input")?;
    let out: TypedFunc<(), u32> = inst.get_typed_func(&mut store, "lf_out")?;
    let new: TypedFunc<u32, u32> = inst.get_typed_func(&mut store, "lf_new")?;
    let label: TypedFunc<(), u32> = inst.get_typed_func(&mut store, "lf_label")?;
    let step: TypedFunc<(), u32> = inst.get_typed_func(&mut store, "lf_step")?;
    let host: TypedFunc<(), u32> = inst.get_typed_func(&mut store, "lf_host")?;
    let text = |store: &mut Store<()>, len: u32| -> anyhow::Result<String> {
        let p = out.call(&mut *store, ())? as usize;
        Ok(String::from_utf8_lossy(&memory.data(&*store)[p..p + len as usize]).into_owned())
    };
    let p = input.call(&mut store, seed.len() as u32)? as usize;
    memory.data_mut(&mut store)[p..p + seed.len()].copy_from_slice(&seed);
    let steps = new.call(&mut store, size)?;
    println!("{} size {} m: {steps} steps (fuel per step of a {:.0} × 10⁹ budget)", args[2], if size > 0 { size.to_string() } else { "seed".into() }, BUDGET as f64 / 1e9);
    let (mut total_fuel, mut worst, t_all) = (0u64, 0u64, Instant::now());
    let mut k = 0;
    loop {
        let n = label.call(&mut store, ())?;
        let what = text(&mut store, n)?;
        store.set_fuel(BUDGET)?;
        let t = Instant::now();
        let done = step.call(&mut store, ())?;
        let used = BUDGET - store.get_fuel()?;
        k += 1;
        total_fuel += used;
        worst = worst.max(used);
        println!("step {k:>3}/{steps} {what:<30} {:>8.2} × 10⁹  {:>5.1}%  {:>7.3} s  memory {:>6.0} MB", used as f64 / 1e9, used as f64 / BUDGET as f64 * 100.0, t.elapsed().as_secs_f64(), memory.data_size(&store) as f64 / 1048576.0);
        if done == 1 {
            break;
        }
    }
    store.set_fuel(BUDGET)?;
    let t = Instant::now();
    let n = host.call(&mut store, ())?;
    let used = BUDGET - store.get_fuel()?;
    let d = text(&mut store, n)?;
    println!("host+digests {:>23} {:>8.2} × 10⁹  {:>5.1}%  {:>7.3} s  memory {:>6.0} MB", "", used as f64 / 1e9, used as f64 / BUDGET as f64 * 100.0, t.elapsed().as_secs_f64(), memory.data_size(&store) as f64 / 1048576.0);
    println!("total {:.1} × 10⁹ fuel ({:.2} budgets) in {:.1} s; worst step {:.1}% of a budget; digests {d}", total_fuel as f64 / 1e9, total_fuel as f64 / BUDGET as f64, t_all.elapsed().as_secs_f64(), worst as f64 / BUDGET as f64 * 100.0);
    Ok(())
}
