//! Bounded live trial: unchanged primary proposals execute; Jev only observes copies.
use bridge::{
    agent_harness::{deliberate_once_with_shadow, Responsibility},
    participant::ParticipantService,
    reasoning::backend::{Backend, Config},
    typesafe_shadow,
};
use serde_json::{json, Value};
use std::{path::PathBuf, time::Duration};
use tokio::sync::{mpsc, watch};

#[tokio::main]
async fn main() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 4 {
        return Err("usage: participant_shadow_trial SESSION PRIMARY_CONFIG NEW_OUTDIR CALLS (1..24); TYPESAFE_API_KEY and primary credentials in environment".into());
    }
    let count: usize = args[3].parse().map_err(|_| "invalid call count")?;
    if !(1..=24).contains(&count) {
        return Err("calls must be 1..24".into());
    }
    let config: Config =
        serde_json::from_slice(&std::fs::read(&args[1]).map_err(|_| "primary config unavailable")?)
            .map_err(|_| "invalid primary config")?;
    let backend = Backend::new(config.clone())?;
    if config.max_attempts != 1 {
        return Err("primary requires max_attempts=1".into());
    }
    let key = std::env::var("TYPESAFE_API_KEY").map_err(|_| "TYPESAFE_API_KEY unavailable")?;
    let out = PathBuf::from(&args[2]);
    std::fs::create_dir(&out)
        .map_err(|_| "trial output must be a new directory with existing parent")?;
    let mut manifest = json!({"version":"sao-shadow-trial-v1","calls_requested":count,
        "primary_config":config,"shadow_model":"jev-1.13.0","shadow_max_in_flight":1,
        "shadow_queue_capacity":1,"shadow_deadline_ms":10000,"retries":0,
        "interval_after_primary_ms":1000,"shadow_applies_commands":false,"calls":[],
        "comparison":"same personal context; independent questions; coarse operate/no-operation alignment is not correctness or physical outcome equality"});
    let save = |v: &Value| {
        std::fs::write(out.join("trial.json"), backend.safe_value(v).to_string())
            .map_err(|_| "trial journal failed".to_string())
    };
    save(&manifest)?;
    let service = ParticipantService::from_file(std::path::Path::new(&args[0])).await?;
    let initial = service.current()?;
    manifest["initial_context"] = backend.safe_value(&initial);
    save(&manifest)?;
    let (keep, cancel) = watch::channel(None);
    let signal = keep.clone();
    let signal_task = tokio::spawn(async move {
        let _ = tokio::signal::ctrl_c().await;
        let _ = signal.send(Some("trial interrupted".into()));
    });
    let (tx, rx) = mpsc::channel(1);
    let shadow_out = out.join("shadow");
    let shadow_cancel = cancel.clone();
    let worker = tokio::spawn(async move {
        typesafe_shadow::run(rx, shadow_cancel, &shadow_out, key, "jev-1.13.0", count).await
    });
    let mut failed = false;
    for n in 0..count {
        if cancel.borrow().is_some() {
            failed = true;
            break;
        }
        let role = [
            Responsibility::Behavior,
            Responsibility::Communication,
            Responsibility::Learning,
        ][n % 3];
        let started = std::time::Instant::now();
        let result = deliberate_once_with_shadow(
            &service,
            config.clone(),
            role,
            &out,
            cancel.clone(),
            Some(&tx),
        )
        .await;
        manifest["calls"].as_array_mut().unwrap().push(json!({"index":n,"role":role,
            "elapsed_ms":started.elapsed().as_secs_f64()*1000.0,"result":result.as_ref().ok(),"error":result.as_ref().err()}));
        save(&manifest)?;
        println!(
            "Primary call {}/{} {:?}: {}",
            n + 1,
            count,
            role,
            if result.is_ok() {
                "completed"
            } else {
                "failed"
            }
        );
        if result.is_err() {
            failed = true;
            break;
        }
        if n + 1 < count {
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
    }
    // Close admission and explicitly drain the owned worker; never wait before a primary submission.
    drop(tx);
    manifest["shadow_worker"] = match worker.await {
        Ok(Ok(outcome)) => {
            failed |= outcome.succeeded != count;
            json!(outcome)
        }
        Ok(Err(e)) => {
            failed = true;
            json!({"error":e})
        }
        Err(_) => {
            failed = true;
            json!({"error":"shadow worker task failed"})
        }
    };
    manifest["final_context"] = backend.safe_value(&service.current().unwrap_or(Value::Null));
    manifest["status"] = json!(if failed { "incomplete" } else { "completed" });
    save(&manifest)?;
    signal_task.abort();
    drop(keep);
    if failed {
        Err("trial incomplete; retained primary and shadow journals contain evidence".into())
    } else {
        Ok(())
    }
}
