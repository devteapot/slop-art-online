//! Single local generation against a Pending exported from the real authority.
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
    if !(4..=5).contains(&args.len()) {
        return Err(
            "usage: local_policy_probe STATE_JSON CONFIG_JSON NEW_OUTPUT_DIR [FEEDBACK_JSON]"
                .into(),
        );
    }
    let world: World = serde_json::from_slice(&fs::read(&args[1])?)?;
    let pending = world
        .pending
        .first()
        .ok_or("no authoritative pending request")?
        .clone();
    let config: Config = serde_json::from_slice(&fs::read(&args[2])?)?;
    if !matches!(config.backend, BackendConfig::Ollama { .. }) || config.max_attempts != 1 {
        return Err("probe is limited to single-attempt native local Ollama".into());
    }
    let out = PathBuf::from(&args[3]);
    fs::create_dir(&out)?;
    fs::create_dir(out.join("reasoning"))?;
    let reasoner = Reasoner::new(config)?;
    let feedback = args
        .get(4)
        .map(
            |path| -> Result<serde_json::Value, Box<dyn std::error::Error + Send + Sync>> {
                Ok(serde_json::from_slice(&fs::read(path)?)?)
            },
        )
        .transpose()?;
    reasoner.preflight(&out).await?;
    let (_tx, cancel) = tokio::sync::watch::channel(None);
    let result = reasoner
        .reason_with_feedback(world.run, pending, cancel, out.join("reasoning"), feedback)
        .await;
    fs::write(
        out.join("generation.json"),
        serde_json::to_vec_pretty(
            &json!({"request_id":result.request_id,"raw":result.raw,"metadata":result.metadata}),
        )?,
    )?;
    println!(
        "Single local generation retained; outcome: {}",
        result.metadata["outcome"]
    );
    Ok(())
}
