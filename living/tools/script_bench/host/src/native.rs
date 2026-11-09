//! The same engines and laws natively (x86_64), for reference.
//! usage: sb-native <kind,kind,...> [--dumps DIR] [--batches N]

use sb_bench::{Kind, Law};
use std::time::Instant;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let kinds: Vec<Kind> = args[1].split(',').map(|k| Kind::ALL.into_iter().find(|x| x.name() == k).unwrap_or_else(|| panic!("unknown engine {k}"))).collect();
    let opt = |name: &str| args.iter().position(|a| a == name).map(|i| args[i + 1].clone());
    let dumps = opt("--dumps");
    let batches: usize = opt("--batches").map_or(3000, |v| v.parse().unwrap());
    let fx = sb_bench::fixtures::build();
    let mut cursor = 0usize;
    if args.iter().any(|a| a == "--rhai-ops") {
        let [r, c, d, k] = sb_bench::rhai_engine::ops_per_law(&fx);
        println!("{{\"rhai_max_ops\":{{\"rates\":{r},\"strike_check\":{c},\"strike_done\":{d},\"combat_cooldown\":{k},\"limit\":20000}},\"skills_rhai_bytes\":{},\"max_source\":{}}}", sb_bench::rhai_engine::SOURCE.len(), living_rules::script::MAX_SOURCE);
        return;
    }
    for kind in kinds {
        let t = Instant::now();
        let mut e = match sb_bench::make(kind) {
            Ok(e) => e,
            Err(err) => {
                println!("{{\"engine\":\"{}\",\"error\":{:?}}}", kind.name(), err);
                continue;
            },
        };
        let init_ms = t.elapsed().as_secs_f64() * 1e3;
        for law in Law::ALL {
            let text = sb_bench::dump(e.as_mut(), &fx, law);
            if let Some(dir) = &dumps {
                std::fs::write(format!("{dir}/native-{}-{}.txt", kind.name(), law.name()), &text).unwrap();
            }
            let digest = sb_bench::digest(&text);
            sb_bench::run(e.as_mut(), &fx, law, &mut cursor, 2000);
            let t = Instant::now();
            sb_bench::run(e.as_mut(), &fx, law, &mut cursor, 2000);
            let est = t.elapsed().as_nanos() as f64 / 2000.0;
            let n = ((200_000.0 / est) as u32).clamp(1, 100_000);
            let mut per = Vec::with_capacity(batches);
            for _ in 0..batches {
                let t = Instant::now();
                std::hint::black_box(sb_bench::run(e.as_mut(), &fx, law, &mut cursor, n));
                per.push(t.elapsed().as_nanos() as f64 / n as f64);
            }
            per.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let q = |p: f64| per[((per.len() - 1) as f64 * p) as usize];
            let mean = per.iter().sum::<f64>() / per.len() as f64;
            println!(
                "{{\"target\":\"x86_64\",\"engine\":\"{}\",\"law\":\"{}\",\"calls_per_batch\":{n},\"batches\":{batches},\"p50_ns\":{:.1},\"p99_ns\":{:.1},\"mean_ns\":{mean:.1},\"init_ms\":{init_ms:.2},\"digest\":\"{digest:016x}\"}}",
                kind.name(),
                law.name(),
                q(0.5),
                q(0.99)
            );
        }
    }
}
