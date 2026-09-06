//! Bounded JSONL supervisor for a persistent actor-scoped external MCP child.
#[path = "admission.rs"]
mod admission;
#[path = "rpc.rs"]
mod rpc;
use bridge::{
    agent_harness::{Proposal, Responsibility},
    reasoning::backend::{Backend, Config},
};
use serde_json::{json, Value};
#[cfg(unix)]
use std::os::fd::AsFd;
use std::{
    path::{Component, Path, PathBuf},
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    sync::{mpsc, watch},
};

const PROTOCOL: &str = "sao-external-worker-v1";

fn role(value: &str) -> Result<Responsibility, String> {
    match value {
        "behavior" => Ok(Responsibility::Behavior),
        "communication" => Ok(Responsibility::Communication),
        "learning" => Ok(Responsibility::Learning),
        _ => Err("invalid responsibility".into()),
    }
}
struct Job {
    id: u64,
    config: PathBuf,
    responsibility: Responsibility,
    output: PathBuf,
}
fn parse_job(value: &Value, root: &Path, previous: u64) -> Result<Job, String> {
    if value["protocol"] != PROTOCOL || value["op"] != "job" {
        return Err("invalid worker protocol".into());
    }
    let id = value["id"]
        .as_u64()
        .filter(|id| *id > previous)
        .ok_or("job ID must be positive and increasing")?;
    let config = PathBuf::from(value["config_path"].as_str().ok_or("config_path missing")?);
    if !config.is_absolute() {
        return Err("config_path must be absolute".into());
    }
    let output = PathBuf::from(value["output"].as_str().ok_or("output missing")?);
    if output.components().count() != 1
        || !matches!(output.components().next(), Some(Component::Normal(_)))
    {
        return Err("output must be one safe path component".into());
    }
    Ok(Job {
        id,
        config,
        responsibility: role(
            value["responsibility"]
                .as_str()
                .ok_or("responsibility missing")?,
        )?,
        output: root.join(output),
    })
}
fn write(path: &Path, value: &Value) -> Result<(), String> {
    std::fs::write(path, value.to_string()).map_err(|_| "audit write failed".into())
}
struct Actor {
    session: PathBuf,
    mcp: Option<rpc::Mcp>,
    fatal: Option<String>,
    admission: Option<std::sync::Arc<admission::Admission>>,
}
impl Actor {
    fn reusable(&self) -> bool {
        self.fatal.is_none() && self.mcp.as_ref().is_none_or(|mcp| mcp.transport.reusable())
    }
    async fn close(&mut self) -> Result<(), String> {
        if let Some(mcp) = self.mcp.take() {
            mcp.close().await
        } else {
            Ok(())
        }
    }
    async fn job(&mut self, job: &Job, cancel: &mut watch::Receiver<Option<String>>) -> Value {
        let start = Instant::now();
        let reused = self.mcp.is_some();
        let first_id = self
            .mcp
            .as_ref()
            .map(|mcp| mcp.transport.audit()["issued_rpc_ids"].as_u64().unwrap())
            .unwrap_or(0);
        let mut audit = json!({"protocol":PROTOCOL,"id":job.id,"responsibility":job.responsibility,"phase":"started","setup_phase":"audit","mcp_reused":reused,"rpc_id_before":first_id});
        let mut audit_ready = false;
        let mut model_started = false;
        if let Some(mcp) = &mut self.mcp {
            mcp.transport.begin_job();
        }
        let result = async {
            match std::fs::symlink_metadata(&job.output) {
                Ok(meta) if !meta.is_dir() || meta.file_type().is_symlink() => return Err("unsafe audit directory".into()),
                Ok(_) if job.output.join("worker-job.json").exists() || job.output.join("external.json").exists() => return Err("audit job already exists".into()),
                Ok(_) => (),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => std::fs::create_dir(&job.output).map_err(|_| "audit directory unavailable")?,
                Err(_) => return Err("audit directory unavailable".into()),
            }
            audit_ready = true;
            write(&job.output.join("worker-job.json"), &audit)?;
            audit["setup_phase"] = json!("config");
            let config: Config = serde_json::from_slice(&std::fs::read(&job.config).map_err(|_| "config unavailable")?).map_err(|_| "invalid config")?;
            if config.max_attempts != 1 { return Err("single attempt required".into()); }
            let backend = Backend::new(config.clone())?;
            if let Some(error) = &self.fatal { return Err(error.clone()); }
            if cancel.borrow().is_some() { return Err("job cancelled before MCP setup".into()); }
            audit["setup_phase"] = json!("mcp_spawn");
            if self.mcp.is_none() {
                match rpc::Mcp::spawn(&self.session, self.admission.clone()) {
                    Ok(mcp) => self.mcp = Some(mcp),
                    Err(error) => { self.fatal = Some(error.clone()); return Err(error); }
                }
            }
            let mcp = &mut self.mcp.as_mut().unwrap().transport;
            audit["setup_phase"] = json!("discovery");
            write(&job.output.join("worker-job.json"), &audit)?;
            let discovery = mcp.rpc("server/discover", json!({}), cancel).await?;
            audit["setup_phase"] = json!("tools_list");
            write(&job.output.join("worker-job.json"), &audit)?;
            let tools = mcp.rpc("tools/list", json!({}), cancel).await?;
            audit["setup_phase"] = json!("observe");
            write(&job.output.join("worker-job.json"), &audit)?;
            let mut state = mcp.call("observe", json!({"after_cursor":0,"limit":256}), cancel).await?;
            let feedback_dir = job.output.parent().ok_or("actor audit directory missing")?;
            let responsibility = bridge::agent_harness::add_controller_feedback(&mut state, feedback_dir, job.responsibility);
            let mut schema = bridge::agent_harness::proposal_schema(responsibility);
            bridge::agent_harness::ground_reflection_schema(&mut schema, &state);
            let payload = super::payload::payload(&backend, responsibility, &state, &tools, schema);
            let mut record = backend.safe_value(&json!({"runtime":"separate minimal Rust model-driven MCP client","role":responsibility,"planned_responsibility":job.responsibility,"discovery":discovery,"participant_context":state,"request":payload,"phase":"started"}));
            write(&job.output.join("external.json"), &record)?;
            audit["setup_phase"] = json!("model");
            write(&job.output.join("worker-job.json"), &audit)?;
            let result = async {
                if cancel.borrow().is_some() { return Err("job cancelled before model request".into()); }
                model_started = true;
                let reply = backend.complete(&payload, tokio::time::Instant::now() + Duration::from_millis(config.deadline_ms), cancel).await;
                record["reply"] = backend.safe_value(&json!(reply));
                if let Some(error) = reply.error { return Err(error); }
                let proposal: Proposal = serde_json::from_str(&reply.raw_output).map_err(|error| format!("invalid generated proposal: {error}"))?;
                if proposal.operations.len() > 4 { return Err("too many operations".into()); }
                let mut receipts = vec![];
                for (i, op) in proposal.operations.iter().enumerate() {
                    if cancel.borrow().is_some() { return Err("job cancelled before operation; prior delivery may be unknown".into()); }
                    let mut value = serde_json::to_value(op).unwrap();
                    let name = value["op"].as_str().unwrap().to_string();
                    let allowed = match responsibility { Responsibility::Behavior => name == "replace_tree" || name == "patch_subtree", Responsibility::Communication => name == "speak", Responsibility::Learning => name == "reflect" };
                    if !allowed { return Err("wrong responsibility".into()); }
                    value.as_object_mut().unwrap().remove("op");
                    value["request_id"] = json!(format!("external-live-{}-{i}", rand::random::<u64>()));
                    value["control_epoch"] = state["control_epoch"].clone();
                    audit["setup_phase"] = json!("operation");
                    write(&job.output.join("worker-job.json"), &audit)?;
                    let receipt = mcp.call(&name, value.clone(), cancel).await;
                    receipts.push(json!({"tool":name,"arguments":value,"receipt":receipt.as_ref().ok(),"error":receipt.as_ref().err()}));
                    // Persist each returned receipt before advancing; cancellation never replays it.
                    record["partial_receipts"] = json!(receipts);
                    write(&job.output.join("external.json"), &backend.safe_value(&record))?;
                }
                // Preserve the existing runner's distinction between model result and tool receipt errors.
                Ok::<Value, String>(json!({"reported_reason":proposal.reason,"receipts":receipts}))
            }.await;
            record["elapsed_ms"] = json!(start.elapsed().as_millis());
            record["phase"] = json!(if cancel.borrow().is_some() { "interrupted" } else { "completed" });
            record["result"] = json!(result.as_ref().ok());
            record["error"] = json!(result.as_ref().err());
            let feedback_result = bridge::agent_harness::save_controller_feedback(feedback_dir, responsibility, &backend.safe_value(&record));
            write(&job.output.join("external.json"), &backend.safe_value(&record))?;
            feedback_result?;
            result.map(|_| ()).map_err(|error| backend.safe_value(&json!(error)).as_str().unwrap_or("external job failed").to_owned())
        }.await;
        let interrupted = cancel.borrow().is_some();
        let phase = if interrupted {
            "interrupted"
        } else if result.is_ok() {
            "completed"
        } else {
            "failed"
        };
        if let Some(mcp) = &self.mcp {
            audit["mcp"] = mcp.audit();
        }
        if interrupted || !self.reusable() {
            self.fatal.get_or_insert_with(|| {
                if interrupted {
                    "worker cancelled; MCP closed".into()
                } else {
                    "MCP transport failed; respawn prohibited".into()
                }
            });
            if let Err(error) = self.close().await {
                audit["cleanup_error"] = json!(error);
            }
        }
        audit["phase"] = json!(phase);
        audit["elapsed_ms"] = json!(start.elapsed().as_millis());
        audit["error"] = json!(result.as_ref().err());
        audit["delivery_may_be_unknown"] = json!(
            audit["mcp"]["requests"]
                .as_array()
                .is_some_and(|events| events.iter().any(|event| event["delivery_unknown"] == true))
                || (interrupted && model_started && audit["setup_phase"] == "model")
                || result.as_ref().err().is_some_and(|e| e.contains("unknown"))
        );
        audit["worker_reusable"] = json!(self.reusable());
        let saved = if audit_ready {
            write(&job.output.join("worker-job.json"), &audit)
        } else {
            Ok(())
        };
        let error = result.err().or(saved.err());
        json!({"protocol":PROTOCOL,"id":job.id,"phase":if error.is_some() && phase == "completed" { "failed" } else { phase },"exit_code":if error.is_some() || interrupted {1} else {0},"error":error,"worker_reusable":self.reusable()})
    }
}
async fn acknowledge(value: &Value) -> Result<(), String> {
    #[cfg(unix)]
    let mut stdout = tokio::net::unix::pipe::Sender::from_owned_fd(
        std::io::stdout()
            .as_fd()
            .try_clone_to_owned()
            .map_err(|_| "worker stdout unavailable")?,
    )
    .map_err(|_| "worker stdout must be a pipe")?;
    #[cfg(not(unix))]
    let mut stdout = tokio::io::stdout();
    tokio::time::timeout(Duration::from_secs(3), async {
        stdout.write_all(format!("{value}\n").as_bytes()).await?;
        stdout.flush().await
    })
    .await
    .map_err(|_| "worker acknowledgement deadline")?
    .map_err(|_| "worker acknowledgement failed".into())
}
pub async fn run(session: PathBuf, root: PathBuf) -> Result<(), String> {
    let admission = admission::Admission::from_env()?;
    std::fs::create_dir_all(&root).map_err(|_| "actor audit directory unavailable")?;
    let root = root
        .canonicalize()
        .map_err(|_| "actor audit directory unavailable")?;
    // Tokio stdin uses an uncancellable blocking read. A real async pipe lets shutdown
    // reap the worker even while the supervisor keeps its input pipe open.
    #[cfg(unix)]
    let stdin = tokio::net::unix::pipe::Receiver::from_owned_fd(
        std::io::stdin()
            .as_fd()
            .try_clone_to_owned()
            .map_err(|_| "worker stdin unavailable")?,
    )
    .map_err(|_| "worker stdin must be a pipe")?;
    #[cfg(not(unix))]
    let stdin = tokio::io::stdin();
    let (sender, mut input) = mpsc::channel(1);
    let stdin_sender = sender.clone();
    let reader = tokio::spawn(async move {
        let mut lines = BufReader::new(stdin).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            let value = serde_json::from_str(&line).unwrap_or_else(|_| json!({"op":"invalid"}));
            if stdin_sender.send(value).await.is_err() {
                return;
            }
        }
        let _ = stdin_sender
            .send(json!({"protocol":PROTOCOL,"op":"shutdown"}))
            .await;
    });
    let signal = tokio::spawn(async move {
        #[cfg(unix)]
        {
            let mut terminate =
                tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                    .expect("SIGTERM handler");
            tokio::select! { _ = terminate.recv() => (), _ = tokio::signal::ctrl_c() => () }
        }
        #[cfg(not(unix))]
        let _ = tokio::signal::ctrl_c().await;
        let _ = sender
            .send(json!({"protocol":PROTOCOL,"op":"shutdown"}))
            .await;
    });
    let mut actor = Actor {
        session,
        admission,
        mcp: None,
        fatal: None,
    };
    let mut previous = 0;
    let result = async {
        while let Some(value) = input.recv().await {
            if value["protocol"] == PROTOCOL && value["op"] == "shutdown" { break; }
            let job = match parse_job(&value, &root, previous) {
                Ok(job) => job,
                Err(error) => return Err(error),
            };
            previous = job.id;
            let (cancel, mut cancelled) = watch::channel(None);
            let mut shutdown = false;
            let mut protocol_error = None;
            let response = {
                let future = actor.job(&job, &mut cancelled);
                tokio::pin!(future);
                loop {
                    tokio::select! {
                        biased;
                        value = input.recv(), if !shutdown => {
                            match value {
                                Some(value) if value["protocol"] == PROTOCOL && value["op"] == "cancel" && value["id"] == job.id => {
                                    let _ = cancel.send(Some("supervisor cancelled job; delivery and cost may be unknown".into()));
                                }
                                Some(value) if value["protocol"] == PROTOCOL && value["op"] == "shutdown" => {
                                    shutdown = true;
                                    let _ = cancel.send(Some("supervisor shutdown; delivery and cost may be unknown".into()));
                                }
                                None => { shutdown = true; let _ = cancel.send(Some("supervisor disconnected".into())); }
                                _ => {
                                    shutdown = true;
                                    protocol_error = Some("worker protocol violation: one job in flight; no queue".to_string());
                                    let _ = cancel.send(Some("worker protocol violation".into()));
                                }
                            }
                        }
                        response = &mut future => break response,
                    }
                }
            };
            acknowledge(&response).await?;
            if let Some(error) = protocol_error { return Err(error); }
            if shutdown { break; }
        }
        Ok(())
    }.await;
    reader.abort();
    signal.abort();
    let cleanup = actor.close().await;
    result.and(cleanup)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn protocol_rejects_replay_and_path_escape() {
        let good = json!({"protocol":PROTOCOL,"op":"job","id":1,"config_path":"/config.json","responsibility":"behavior","output":"01-behavior"});
        assert!(parse_job(&good, Path::new("/audit"), 0).is_ok());
        assert!(parse_job(&good, Path::new("/audit"), 1).is_err());
        for output in ["..", ".", "", "/escape", "a/b", "../escape"] {
            let mut bad = good.clone();
            bad["output"] = json!(output);
            assert!(parse_job(&bad, Path::new("/audit"), 0).is_err());
        }
        let mut bad = good;
        bad["config_path"] = json!("relative");
        assert!(parse_job(&bad, Path::new("/audit"), 0).is_err());
    }
    #[tokio::test]
    async fn missing_config_is_audited_without_spawning_or_fabricating_context() {
        let root = std::env::temp_dir().join(format!("sao-worker-test-{}", rand::random::<u64>()));
        std::fs::create_dir(&root).unwrap();
        let mut actor = Actor {
            session: root.join("missing-session"),
            admission: None,
            mcp: None,
            fatal: None,
        };
        let (_keep, mut cancel) = watch::channel(None);
        for id in 1..=2 {
            let output = root.join(format!("{id}-behavior"));
            let ack = actor
                .job(
                    &Job {
                        id,
                        config: root.join("missing-config"),
                        responsibility: Responsibility::Behavior,
                        output: output.clone(),
                    },
                    &mut cancel,
                )
                .await;
            assert_eq!(ack["phase"], "failed");
            assert_eq!(ack["worker_reusable"], true);
            assert!(output.join("worker-job.json").is_file());
            assert!(!output.join("external.json").exists());
            assert!(actor.mcp.is_none());
        }
        std::fs::remove_dir_all(root).unwrap();
    }
}
