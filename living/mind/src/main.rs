//! Living mind service: connects to the living authority as the controller of its AI
//! characters, reads only their percepts and deliberation requests, keeps their personal
//! memory graphs in Neo4j and calls LLMs (outside any reducer) to consolidate experience
//! and revise behavior.

mod llm;
mod memory;
mod mind;
mod prompts;

use anyhow::{anyhow, Context, Result};
use living_bindings::*;
use spacetimedb_sdk::{DbContext, Table};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

pub fn root() -> PathBuf {
    if let Ok(r) = std::env::var("LIVING_ROOT") {
        return PathBuf::from(r);
    }
    let mut p = std::env::current_dir().unwrap();
    loop {
        if p.join("living").join("Cargo.toml").exists() {
            return p;
        }
        if !p.pop() {
            return std::env::current_dir().unwrap();
        }
    }
}

/// Load KEY=VALUE lines without overriding the environment.
fn load_env(path: &Path) {
    let Ok(text) = std::fs::read_to_string(path) else { return };
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            let k = k.trim().trim_start_matches("export ").trim();
            if std::env::var_os(k).is_none() {
                std::env::set_var(k, v.trim().trim_matches('"'));
            }
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info,neo4rs=warn,spacetimedb_sdk=warn")).init();
    let root = root();
    load_env(&root.join(".env"));
    load_env(&root.join(".local/living/neo4j.env"));
    let server = std::env::var("LIVING_SERVER").unwrap_or_else(|_| "http://127.0.0.1:3300".into());
    let db = std::env::var("LIVING_DB").unwrap_or_else(|_| "living".into());
    let token = match std::env::var("LIVING_TOKEN") {
        Ok(t) => t,
        Err(_) if root.join(".local/living/token").exists() => std::fs::read_to_string(root.join(".local/living/token"))?.trim().to_string(),
        Err(_) => {
            let cfg: toml::Value = toml::from_str(&std::fs::read_to_string(root.join(".local/living/cli.toml")).context("read .local/living/cli.toml (publish once first)")?)?;
            cfg.get("spacetimedb_token").and_then(|t| t.as_str()).ok_or_else(|| anyhow!("no spacetimedb_token in cli.toml"))?.to_string()
        }
    };
    let models: llm::ModelsFile = serde_json::from_str(&std::fs::read_to_string(
        std::env::var("LIVING_MODELS").map(PathBuf::from).unwrap_or_else(|_| root.join("living/configs/models.json")),
    )?)?;
    let seed: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(root.join(format!("living/seeds/{}.json", std::env::var("LIVING_SEED").unwrap_or_else(|_| "world".into()))))?)?;
    // LIVING_RUN separates experiments on other databases (journal and Neo4j minds are per run).
    let run = std::env::var("LIVING_RUN").unwrap_or_else(|_| seed["run"].as_str().unwrap_or("valley").to_string());
    let (mw, mh) = (seed["map"]["w"].as_u64().unwrap_or(96) as u32, seed["map"]["h"].as_u64().unwrap_or(96) as u32);
    let year_days = seed["year_days"].as_f64().unwrap_or(living_rules::YEAR_DAYS as f64) as f32;
    let pace = seed["life_pace"].as_f64().unwrap_or(1.0) as f32;
    let species: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(root.join("living/seeds/species.json"))?)?;
    let life: living_rules::life::Life = serde_json::from_value(species["person"]["life"].clone()).unwrap_or_default();
    prompts::set_world(seed["setting"].as_str().unwrap_or_default(), mw, mh, year_days, pace, life);
    let journal = root.join(".local/living/journal").join(&run);
    let llm = llm::Llm::new(models, journal)?;

    let store = match std::env::var("LIVING_NEO4J_PASSWORD") {
        Ok(pw) if std::env::var("LIVING_NEO4J").as_deref() != Ok("off") => {
            let uri = std::env::var("LIVING_NEO4J_URI").unwrap_or_else(|_| "127.0.0.1:7689".into());
            match memory::Store::connect(&uri, "neo4j", &pw, &run).await {
                Ok(s) => {
                    log::info!("personal memory graphs in Neo4j at {uri}");
                    Some(s)
                }
                Err(e) => {
                    log::warn!("Neo4j unavailable ({e:#}); running with in-process memory only");
                    None
                }
            }
        }
        _ => None,
    };

    let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
    let (ready_tx, ready_rx) = tokio::sync::oneshot::channel::<()>();
    let ready = Arc::new(Mutex::new(Some(ready_tx)));
    let conn = DbConnection::builder()
        .with_uri(server.clone())
        .with_database_name(db.clone())
        .with_token(Some(token))
        .on_connect(move |c, identity, _| {
            log::info!("connected as {identity}");
            let ready = ready.clone();
            let experiences = format!("SELECT * FROM experience WHERE controller = 0x{}", identity.to_hex());
            c.subscription_builder()
                .on_applied(move |_| {
                    if let Some(tx) = ready.lock().unwrap().take() {
                        let _ = tx.send(());
                    }
                })
                .on_error(|_, e| log::error!("subscription error: {e:?}"))
                .subscribe([
                    experiences.as_str(),
                    "SELECT * FROM mind_cursor",
                    "SELECT * FROM world",
                    "SELECT * FROM character",
                    "SELECT * FROM brain",
                    "SELECT * FROM persona",
                    "SELECT * FROM relation",
                    "SELECT * FROM judgment",
                    "SELECT * FROM place",
                    "SELECT * FROM know_how",
                    "SELECT * FROM community",
                    "SELECT * FROM membership",
                    "SELECT * FROM background",
                    "SELECT * FROM routine",
                    "SELECT * FROM routine_stat",
                    "SELECT * FROM genome",
                    "SELECT * FROM my_deliberations",
                ]);
        })
        .on_disconnect(|_, e| {
            log::error!("disconnected from the world: {e:?}");
            std::process::exit(2);
        })
        .build()
        .with_context(|| format!("connect to {server}/{db}"))?;
    {
        let tx = tx.clone();
        conn.db.experience().on_insert(move |_, e| {
            if e.kind == "speech" || e.kind == "silence" {
                let _ = tx.send(mind::Event::Speech(e.clone()));
            }
        });
    }
    {
        let tx = tx.clone();
        conn.db.my_deliberations().on_insert(move |_, d| {
            let _ = tx.send(mind::Event::Deliberation(d.actor));
        });
    }
    conn.run_threaded();
    ready_rx.await.map_err(|_| anyhow!("subscription never applied"))?;
    log::info!("world subscribed: {} characters", conn.db.character().count());
    let concurrency = std::env::var("LIVING_CONCURRENCY").ok().and_then(|v| v.parse().ok()).unwrap_or(64);
    let minds = mind::Minds::new(conn, llm, store, seed, concurrency)?;
    minds.bootstrap().await?;
    minds.run(rx).await
}
