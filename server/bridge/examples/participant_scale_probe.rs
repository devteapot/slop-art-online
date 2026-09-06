//! Measure concurrent scoped reads against an existing isolated 36-person run.
//! Uses saved sessions without printing tokens, issuing actions, or invoking models.
use bridge::participant::ParticipantService;
use serde::Deserialize;
use serde_json::{json, Value};
use spacetimedb_sdk::DbContext;
use std::{
    collections::BTreeSet,
    path::PathBuf,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::task::JoinSet;

#[derive(Deserialize)]
struct Descriptor {
    actor: u32,
    session_file: PathBuf,
}

fn wall_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis()
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let descriptors = PathBuf::from(args.next().ok_or("participants.json argument required")?);
    let output = PathBuf::from(args.next().ok_or("output JSON argument required")?);
    let rows: Vec<Descriptor> = serde_json::from_slice(&std::fs::read(descriptors)?)?;
    let ids: BTreeSet<_> = rows.iter().map(|row| row.actor).collect();
    if rows.len() != 36 || ids.len() != 36 {
        return Err("probe requires exactly 36 distinct participant descriptors".into());
    }
    let started_at_ms = wall_ms();
    let opened_at = Instant::now();
    let mut opening = JoinSet::new();
    for row in rows {
        opening.spawn(async move {
            (
                row.actor,
                ParticipantService::from_file(&row.session_file).await,
            )
        });
    }
    let mut services = Vec::new();
    let mut open_errors = Vec::new();
    while let Some(result) = opening.join_next().await {
        match result {
            Ok((actor, Ok(service))) => services.push((actor, service)),
            Ok((actor, Err(error))) => open_errors.push(json!({"actor":actor,"error":error})),
            Err(_) => open_errors.push(json!({"error":"connection task failed"})),
        }
    }
    services.sort_by_key(|(actor, _)| *actor);
    let open_ms = opened_at.elapsed().as_millis();
    let mut rounds = Vec::new();
    for round in 1..=3 {
        let round_started_at_ms = wall_ms();
        let started = Instant::now();
        let mut reads = JoinSet::new();
        for (actor, service) in &services {
            let actor = *actor;
            let service = service.clone();
            reads.spawn(async move {
                let started = Instant::now();
                let observation = service.observe(0, 128).await;
                let elapsed_ms = started.elapsed().as_millis();
                match observation {
                    Ok(observed) => {
                        let current = service.current().ok();
                        let identity_matches = observed["actor"] == json!(actor);
                        let status_fresh = current.as_ref().is_some_and(|status| {
                            status["actor"] == json!(actor)
                                && status["control_epoch"] == observed["control_epoch"]
                                && status["tick"].as_u64().zip(observed["tick"].as_u64())
                                    .is_some_and(|(current, captured)| current >= captured)
                                && observed["control_epoch"].as_u64().is_some()
                                && observed["context"]["player"]["health"].as_u64().is_some_and(|h| h <= 100)
                                && status["context"]["player"]["health"].as_u64().is_some_and(|h| h <= 100)
                        });
                        json!({"actor":actor,"read_ok":true,"ok":identity_matches && status_fresh,
                            "elapsed_ms":elapsed_ms,"observed_actor":observed["actor"],
                            "identity_matches":identity_matches,"status_fresh":status_fresh,
                            "run":observed["run"],"time_ms":observed["time_ms"],
                            "updates":observed["updates"],"health":observed["context"]["player"]["health"],
                            "control_epoch":observed["control_epoch"],"latest_cursor":observed["latest_cursor"],
                            "observed_tick":observed["tick"],"status_tick":current.as_ref().map(|v|&v["tick"]),
                            "status_health":current.as_ref().map(|v|&v["context"]["player"]["health"]),
                            "observation_bytes":observed.to_string().len()})
                    }
                    Err(error) => json!({"actor":actor,"read_ok":false,"ok":false,"elapsed_ms":elapsed_ms,"error":error}),
                }
            });
        }
        let mut results = Vec::new();
        while let Some(result) = reads.join_next().await {
            results.push(match result {
                Ok(value) => value,
                Err(_) => json!({"ok":false,"error":"read task failed"}),
            });
        }
        results.sort_by_key(|v| v["actor"].as_u64().unwrap_or(u64::MAX));
        let mut latencies: Vec<_> = results
            .iter()
            .filter_map(|v| v["elapsed_ms"].as_u64())
            .collect();
        latencies.sort_unstable();
        let successes = results.iter().filter(|v| v["ok"] == true).count();
        let reads_returned = results.iter().filter(|v| v["read_ok"] == true).count();
        let report = json!({"round":round,"started_at_ms":round_started_at_ms,"finished_at_ms":wall_ms(),
            "wall_ms":started.elapsed().as_millis(),"attempts":results.len(),"successes":successes,
            "reads_returned":reads_returned,"read_errors":results.len()-reads_returned,"validation_failures":reads_returned-successes,
            "failures":results.len()-successes,"latency_min_ms":latencies.first(),
            "latency_median_ms":latencies.get(latencies.len()/2),"latency_max_ms":latencies.last(),
            "results":results});
        println!(
            "{}",
            json!({"round":round,"attempts":report["attempts"],"successes":successes,
            "reads_returned":reads_returned,"read_errors":report["read_errors"],"validation_failures":report["validation_failures"],
            "wall_ms":report["wall_ms"],"latency_median_ms":report["latency_median_ms"],
            "latency_max_ms":report["latency_max_ms"]})
        );
        rounds.push(report);
        if round < 3 {
            tokio::time::sleep(Duration::from_secs(15)).await;
        }
    }
    for (_, service) in &services {
        let _ = service.connection.disconnect();
    }
    let all_pass = services.len() == 36 && rounds.iter().all(|r| r["successes"] == 36);
    let report: Value = json!({"started_at_ms":started_at_ms,"finished_at_ms":wall_ms(),
        "opened":services.len(),"open_ms":open_ms,"open_errors":open_errors,"rounds":rounds,
        "all_pass":all_pass,"models_invoked":0,"physical_actions_submitted":0,
        "scope":"Existing personal identities; concurrent atomic observation reads only; every connection disconnected afterward."});
    if let Some(parent) = output.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(output, serde_json::to_vec_pretty(&report)?)?;
    if !all_pass {
        return Err("one or more scoped reads failed; see diagnostic JSON".into());
    }
    Ok(())
}
