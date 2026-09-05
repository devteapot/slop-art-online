//! Single explicitly authorized Carlid streaming generation from an authoritative Pending.
//! No local world execution and no retries/model substitution.
use bridge::reasoning::{
    backend::{BackendConfig, Config},
    Reasoner,
};
use serde_json::json;
use simulation::World;
use std::{fs, path::PathBuf};
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("usage: hosted_policy_probe STATE_JSON CONFIG_JSON NEW_OUTPUT_DIR".into());
    }
    let world: World = serde_json::from_slice(&fs::read(&args[1])?)?;
    let pending = world
        .pending
        .first()
        .ok_or("no authoritative pending request")?
        .clone();
    let config: Config = serde_json::from_slice(&fs::read(&args[2])?)?;
    if !matches!(&config.backend, BackendConfig::OpenaiCompatible { base_url, stream: true, .. } if base_url == "https://codex.carlid.dev/v1")
        || config.max_attempts != 1
        || config.max_output_tokens.is_some()
        || config.deadline_ms > 300_000
    {
        return Err("probe requires the Carlid streaming endpoint, explicit no cap, one attempt and <=300s deadline".into());
    }
    let out = PathBuf::from(&args[3]);
    fs::create_dir(&out)?;
    fs::create_dir(out.join("reasoning"))?;
    let reasoner = Reasoner::new(config)?;
    reasoner.preflight(&out).await?;
    let (_tx, cancel) = tokio::sync::watch::channel(None);
    let result = reasoner
        .reason(world.run, pending, cancel, out.join("reasoning"))
        .await;
    fs::write(
        out.join("generation.json"),
        serde_json::to_vec_pretty(
            &json!({"request_id":result.request_id,"raw":result.raw,"metadata":result.metadata}),
        )?,
    )?;
    println!(
        "Single hosted generation retained; outcome: {}",
        result.metadata["outcome"]
    );
    Ok(())
}
