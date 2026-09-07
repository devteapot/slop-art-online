//! Automated human-interface input and a separate developer observer during a
//! live model pilot. Observer truth never enters participant/model requests.
use bridge::participant::{new_session, ParticipantService};
use serde::Deserialize;
use serde_json::{json, Value};
use shared::module_bindings::{sim_client_intent, SimMySnapshotTableAccess};
use simulation::{
    participant::{Command, Request, API_VERSION},
    Action, Decision, Skill,
};
use spacetimedb_sdk::{DbContext, Table};
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

#[derive(Deserialize)]
struct Config {
    server: String,
    database: String,
    run: String,
    actor: u32,
    cli: PathBuf,
    cli_config: PathBuf,
    output: PathBuf,
    credentials: PathBuf,
}
async fn call(c: &Config, name: &str, values: Vec<Value>) -> Result<(), String> {
    let mut cmd = tokio::process::Command::new(&c.cli);
    cmd.kill_on_drop(true)
        .arg("--config-path")
        .arg(&c.cli_config)
        .args(["call", &c.database, name]);
    for value in values {
        cmd.arg(value.to_string());
    }
    let result = tokio::time::timeout(
        Duration::from_secs(30),
        cmd.args(["--server", &c.server, "--no-config", "-y"])
            .output(),
    )
    .await
    .map_err(|_| "owner call timeout; reconcile outcome")?
    .map_err(|_| "owner CLI unavailable")?;
    if result.status.success() {
        Ok(())
    } else {
        Err(format!("{name} failed; output suppressed"))
    }
}
async fn status(service: &ParticipantService) -> Result<Value, String> {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Ok(value) = service.current() {
            return Ok(value);
        }
        if Instant::now() >= deadline {
            return Err("participant status timeout".into());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}
async fn exercise(
    c: &Config,
    human: &mut ParticipantService,
    observer: &ParticipantService,
    result: &mut Value,
) -> Result<(), String> {
    let updates = Arc::new(AtomicU64::new(0));
    let bytes = Arc::new(AtomicU64::new(0));
    let count = updates.clone();
    let total = bytes.clone();
    observer
        .connection
        .db
        .sim_my_snapshot()
        .on_insert(move |_, row| {
            count.fetch_add(1, Ordering::Relaxed);
            total.fetch_add(row.body.len() as u64, Ordering::Relaxed);
        });
    let applied = Arc::new(std::sync::atomic::AtomicBool::new(false));
    let ready = applied.clone();
    let _subscription = observer
        .connection
        .subscription_builder()
        .on_applied(move |_| {
            ready.store(true, Ordering::Release);
        })
        .subscribe("SELECT * FROM sim_my_snapshot");
    let initial = status(human).await?;
    if initial["actor"] != c.actor || initial["run"] != c.run {
        return Err("human scope mismatch".into());
    }
    let epoch = initial["control_epoch"].as_u64().ok_or("missing epoch")?;
    let request = Request {
        api_version: API_VERSION.into(),
        request_id: "mixed-client-retained-read".into(),
        control_epoch: epoch,
        command: Command::ReadObservation {
            after: 0,
            limit: 16,
        },
    };
    let receipt = human.command(request.clone()).await?;
    if !receipt.ok {
        return Err("read rejected".into());
    }
    let before = status(human).await?;
    let captured = before["read_observations"]
        .as_array()
        .ok_or("no reads")?
        .iter()
        .find(|r| r["request_id"] == request.request_id)
        .ok_or("read missing")?
        .clone();
    let mut inputs = vec![];
    let start = Instant::now();
    for n in 0..4 {
        let sent = Instant::now();
        let decision = Decision {
            reason: format!("Automated human-interface workload {n}"),
            actions: vec![Action::new(Skill::Wait)],
            policy: None,
            reflections: vec![],
        };
        let (tx, rx) = tokio::sync::oneshot::channel();
        human
            .connection
            .reducers
            .sim_client_intent_then(serde_json::to_string(&decision).unwrap(), move |_, v| {
                let _ = tx.send(matches!(v, Ok(Ok(()))));
            })
            .map_err(|_| "human input send failed")?;
        let accepted = tokio::time::timeout(Duration::from_secs(10), rx)
            .await
            .map_err(|_| "human input receipt timeout")?
            .map_err(|_| "human input callback lost")?;
        inputs
            .push(json!({"number":n,"accepted":accepted,"elapsed_ms":sent.elapsed().as_millis()}));
        result["inputs"] = json!(inputs);
        if !accepted {
            return Err("human input rejected".into());
        }
        if n == 1 {
            human
                .connection
                .disconnect()
                .map_err(|_| "human disconnect failed")?;
            let end = Instant::now() + Duration::from_secs(5);
            while human.connection.is_active() {
                if Instant::now() >= end {
                    return Err("disconnect timeout".into());
                }
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
            *human = ParticipantService::from_file(&c.credentials.join("human.json")).await?;
            let after = status(human).await?;
            if after["control_epoch"] != epoch
                || !after["read_observations"]
                    .as_array()
                    .is_some_and(|rows| rows.contains(&captured))
            {
                return Err("reconnect changed captured read or epoch".into());
            }
            let replay = human.command(request.clone()).await?;
            if replay.event != receipt.event || !replay.ok {
                return Err("idempotent reconnect replay changed receipt".into());
            }
            result["same_identity_reconnect"] = json!(true);
            result["exact_read_recovered"] = json!(true);
        }
        tokio::time::sleep(Duration::from_secs(10)).await;
    }
    result["observer_updates"] = json!(updates.load(Ordering::Relaxed));
    result["observer_json_body_bytes"] = json!(bytes.load(Ordering::Relaxed));
    result["active_ms"] = json!(start.elapsed().as_millis());
    if !applied.load(Ordering::Acquire) || updates.load(Ordering::Relaxed) < 2 {
        return Err("observer did not receive live updates".into());
    }
    Ok(())
}
#[tokio::main]
async fn main() {
    let c: Config =
        serde_json::from_slice(&std::fs::read(std::env::args().nth(1).expect("config")).unwrap())
            .unwrap();
    assert_eq!(c.server, "http://127.0.0.1:3103");
    assert!(c.database.starts_with("sim-bevy-db-"));
    assert_eq!(c.actor, 72);
    c.output.parent().unwrap().canonicalize().unwrap();
    let mut result = json!({"passed":false,"actor":c.actor,"human_input":"automated client path; no person at keyboard",
        "observer":"one separate developer audit subscription","model_calls":0});
    let mut peers = vec![];
    let work: Result<(), String> = async {
        let (human, id) = new_session(
            c.server.clone(),
            c.database.clone(),
            &c.credentials.join("human.json"),
        )
        .await?;
        peers.push((human, id));
        call(
            &c,
            "sim_grant_client",
            vec![
                json!(c.run),
                json!(peers[0].1),
                json!(false),
                json!(c.actor),
            ],
        )
        .await?;
        let (observer, id) = new_session(
            c.server.clone(),
            c.database.clone(),
            &c.credentials.join("observer.json"),
        )
        .await?;
        peers.push((observer, id));
        call(
            &c,
            "sim_grant_client",
            vec![json!(c.run), json!(peers[1].1), json!(true), json!(0)],
        )
        .await?;
        let (left, right) = peers.split_at_mut(1);
        exercise(&c, &mut left[0].0, &right[0].0, &mut result).await
    }
    .await;
    if let Err(error) = work {
        result["error"] = json!(error);
    } else {
        result["passed"] = json!(true);
    }
    let mut cleanup = vec![];
    for (peer, id) in peers {
        let _ = peer.connection.disconnect();
        if let Err(error) = call(&c, "sim_revoke_client", vec![json!(id)]).await {
            cleanup.push(error);
        }
    }
    if !cleanup.is_empty() {
        result["passed"] = json!(false);
    }
    result["cleanup_errors"] = json!(cleanup);
    std::fs::write(&c.output, serde_json::to_vec_pretty(&result).unwrap()).unwrap();
    if result["passed"] != true {
        std::process::exit(1);
    }
}
