//! Same-identity transport recovery against a separate paused authority run.
use bridge::participant::new_session;
use serde_json::{json, Value};
use simulation::participant::{Command, Request, API_VERSION};
use spacetimedb_sdk::DbContext;
use std::{path::PathBuf, time::{Duration, SystemTime, UNIX_EPOCH}};

async fn call(db: &str, server: &str, name: &str, args: Vec<Value>) {
    let mut command = tokio::process::Command::new(std::env::var("SPACETIME_CONTROL_CLI").unwrap_or("spacetime".into()));
    if let Ok(config) = std::env::var("SPACETIME_CONFIG_PATH") { command.args(["--config-path", &config]); }
    command.args(["call", db, name]);
    for arg in args {command.arg(arg.to_string());}
    let result=command.args(["--server", server, "--no-config", "-y"]).output().await.unwrap();
    assert!(result.status.success(), "reducer {name}: {}", String::from_utf8_lossy(&result.stderr));
}

#[tokio::main]
async fn main() {
    let active: Value=serde_json::from_slice(&std::fs::read(std::env::args().nth(1).expect("active.json path")).unwrap()).unwrap();
    let (db,server)=(active["db"].as_str().unwrap(),active["server"].as_str().unwrap());
    let run=format!("sim-reconnect-proof-{}",SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis());
    call(db,server,"sim_create_participant",vec![json!(run),json!(include_str!("../../../scenarios/survival.json"))]).await;
    call(db,server,"sim_setup_client_clock",vec![json!(run),json!("live_fixture")]).await;
    let path=PathBuf::from(".local/credentials").join(format!("{run}.json"));
    let (mut service, identity)=new_session(server.into(),db.into(),&path).await.unwrap();
    call(db,server,"sim_grant_client",vec![json!(run),json!(identity),json!(false),json!(1)]).await;
    let before=service.observe(0,16).await.unwrap();
    let request=Request {api_version:API_VERSION.into(),request_id:"reconnect-goal".into(),control_epoch:before["control_epoch"].as_u64().unwrap(),
        command:Command::ReadObservation{after:0,limit:16}};
    assert!(service.command(request.clone()).await.unwrap().ok);
    assert!(!service.reconnect_if_needed().await.unwrap());
    service.connection.disconnect().unwrap();
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert!(service.current().is_err());
    assert!(service.reconnect_if_needed().await.unwrap());
    let after=service.observe(0,16).await.unwrap();
    for key in ["actor","control_epoch","policy_revision","learning_revision"] {assert_eq!(before[key],after[key],"{key}");}
    assert_eq!(before["context"]["player"],after["context"]["player"]);
    // A previous request remains idempotent across the transport boundary.
    assert!(service.command(request).await.unwrap().ok);
    call(db,server,"sim_revoke_client",vec![json!(identity)]).await;
    service.connection.disconnect().unwrap();
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert!(service.reconnect_if_needed().await.is_err(),"revocation must survive reconnect");
    let report=json!({"run":run,"same_identity":true,"unchanged_control_and_revisions":true,"unchanged_personal_state":true,"idempotent_receipt":true,"revoked_grant_not_recreated":true});
    let output=PathBuf::from("output/society-lab").join(format!("{run}.json"));
    std::fs::write(&output,serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    println!("Transport recovery verified: {}",output.display());
}
