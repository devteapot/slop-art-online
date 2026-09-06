//! Grant-only fixture setup. Deliberation/observation uses the actual native MCP worker.
use bridge::participant::new_session;
use serde::Deserialize;
use serde_json::{json, Value};
use spacetimedb_sdk::DbContext;
use std::{path::{Path, PathBuf}, time::{Duration, Instant}};

#[derive(Deserialize)]
struct Config {
    server: String,
    database: String,
    run: String,
    output: PathBuf,
    credentials: PathBuf,
    cli: PathBuf,
    owner_cli_config: PathBuf,
    actors: Vec<u32>,
}
fn write(path: &Path, value: &Value) -> Result<(), String> {
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, serde_json::to_vec(value).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
    std::fs::rename(tmp,path).map_err(|e|e.to_string())
}
async fn setup(c: &Config) -> Result<(), String> {
    let mut ledger = Vec::new();
    for actor in &c.actors {
        let session_path = c.credentials.join(format!("actor-{actor}.json"));
        let (service, identity) = new_session(c.server.clone(), c.database.clone(), &session_path).await?;
        // The new identity has no grant. Close it before granting so the worker's
        // later connection is the first granted subscription; no observe/current.
        service.connection.disconnect().map_err(|_|"setup disconnect failed")?;
        let until = Instant::now() + Duration::from_secs(5);
        while service.connection.is_active() {
            if Instant::now() >= until { return Err("setup disconnect deadline".into()); }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        ledger.push(json!({"actor":actor,"identity":identity,"session_file":session_path,
            "setup_connection_closed":true,"grant_attempted":false,"grant_succeeded":false}));
        write(&c.output.join("identities.json"),&json!(ledger))?;
        let row = ledger.last_mut().unwrap();
        row["grant_attempted"] = json!(true);
        write(&c.output.join("identities.json"),&json!(ledger))?;
        let output = tokio::time::timeout(Duration::from_secs(30),
            tokio::process::Command::new(&c.cli).kill_on_drop(true)
                .arg("--config-path").arg(&c.owner_cli_config)
                .args(["call", &c.database, "sim_grant_client"])
                .args([json!(c.run).to_string(),json!(identity).to_string(),"false".into(),actor.to_string()])
                .args(["-y","--server",&c.server,"--no-config"]).output()).await
            .map_err(|_|"grant deadline; outcome unknown, no retry")?
            .map_err(|_|"grant CLI unavailable")?;
        if !output.status.success() { return Err("grant CLI failed; output suppressed".into()); }
        ledger.last_mut().unwrap()["grant_succeeded"] = json!(true);
        write(&c.output.join("identities.json"),&json!(ledger))?;
    }
    Ok(())
}
#[tokio::main]
async fn main() -> Result<(), String> {
    let arg = std::env::args().nth(1).ok_or("one config path required")?;
    let c: Config = serde_json::from_slice(&std::fs::read(arg).map_err(|_|"config unavailable")?).map_err(|_|"invalid config")?;
    if c.server != "http://127.0.0.1:3102" || !c.database.starts_with("sim-persistent-mcp-")
        || !c.run.starts_with("sim-persistent-mcp-") || c.actors != (1..=36).collect::<Vec<_>>()
        || c.output.join("identities.json").exists() || !c.credentials.is_dir() {
        return Err("unexpected fixture scope or replay".into());
    }
    let started = Instant::now();
    let result = tokio::time::timeout(Duration::from_secs(120),setup(&c)).await
        .unwrap_or_else(|_|Err("120s setup ceiling; no retry".into()));
    write(&c.output.join("setup-result.json"),&json!({"pass":result.is_ok(),"error":result.as_ref().err(),
        "elapsed_ms":started.elapsed().as_millis(),"observe_calls":0,"connections_left_open":if result.is_ok(){Some(0)}else{None}}))?;
    result
}
