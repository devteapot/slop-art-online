//! Local experiment/operator service. All state transitions happen in SpacetimeDB.
use bridge::reasoning::{
    backend::{BackendConfig, Config},
    Reasoner, ReasoningResult,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use simulation::{Event, Scenario, World, VERSION};
use std::{
    collections::{BTreeMap, HashSet},
    fs,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::Command,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;
#[derive(Clone, Serialize, Deserialize)]
struct Manifest {
    run: String,
    db: String,
    server: String,
    scenario: Scenario,
    model: String,
    #[serde(default)]
    ollama: String,
    #[serde(default)]
    reasoning: Option<Config>,
    #[serde(default)]
    reasoning_version: String,
    #[serde(default)]
    decision_format: String,
    tick_ms: u64,
    rules: String,
    wasm_sha256: String,
    #[serde(default)]
    runner_sha256: String,
    git_head: String,
    cli_version: String,
    created_ms: u128,
}
#[derive(Clone, Serialize, Deserialize)]
struct Snapshot {
    world: World,
    events: Vec<Event>,
}
fn command(args: &[String]) -> Result<String> {
    let out = Command::new(std::env::var("SPACETIME_CLI").unwrap_or("spacetime".into()))
        .args(args)
        .output()?;
    if !out.status.success() {
        return Err(format!(
            "spacetime command failed: {}",
            String::from_utf8_lossy(&out.stderr)
        )
        .into());
    }
    Ok(String::from_utf8(out.stdout)?)
}
fn call(m: &Manifest, name: &str, args: Vec<Value>) -> Result<()> {
    let mut cmd = vec!["call".into(), m.db.clone(), name.into()];
    cmd.extend(args.into_iter().map(|v| v.to_string()));
    cmd.extend([
        "--server".into(),
        m.server.clone(),
        "--no-config".into(),
        "-y".into(),
    ]);
    command(&cmd)?;
    Ok(())
}
fn sql(m: &Manifest, query: &str) -> Result<Vec<Value>> {
    let raw = command(&[
        "sql".into(),
        m.db.clone(),
        query.into(),
        "--server".into(),
        m.server.clone(),
        "--format".into(),
        "json".into(),
        "--no-config".into(),
    ])?;
    let results: Value = serde_json::from_str(&raw)?;
    Ok(results[0]["rows"]
        .as_array()
        .ok_or("SQL response has no rows")?
        .clone())
}
fn snapshot(m: &Manifest) -> Result<Snapshot> {
    // Each experiment owns a dedicated DB. Read-only consumers never become model context.
    let rows = sql(m, "SELECT state FROM sim_run")?;
    let world: World = serde_json::from_str(
        rows.first()
            .and_then(|v| v[0].as_str())
            .ok_or("missing run")?,
    )?;
    let mut events: Vec<Event> = sql(m, "SELECT json FROM sim_audit")?
        .iter()
        .map(|r| serde_json::from_str(r[0].as_str().unwrap_or("")))
        .collect::<std::result::Result<_, _>>()?;
    events.retain(|e| e.id < world.next_event);
    events.sort_by_key(|e| e.id);
    Ok(Snapshot { world, events })
}
fn write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    let temp = path.with_extension("tmp");
    fs::write(&temp, serde_json::to_vec(value)?)?;
    fs::rename(temp, path)?;
    Ok(())
}
fn export(m: &Manifest, out: &Path) -> Result<Snapshot> {
    let s = snapshot(m)?;
    write_json(&out.join("snapshot.json"), &s)?;
    let mut f = fs::File::create(out.join("events.jsonl"))?;
    for e in &s.events {
        writeln!(f, "{}", serde_json::to_string(e)?)?;
    }
    Ok(s)
}
fn summarize(s: &Snapshot) -> Value {
    let mut counts = BTreeMap::<String, usize>::new();
    for e in &s.events {
        *counts.entry(e.kind.clone()).or_default() += 1;
    }
    let exchanges: Vec<Value> = s.events.iter().filter(|e|e.kind=="model_result").map(|e| {
        let m=&e.data["metadata"];
        json!({"event_id":e.id,"request_id":e.data["request_id"],"backend":m["backend"],"requested_backend_config":m["config"],"legacy_requested_model":m["model"],"elapsed_ms":m["elapsed_ms"],"outcome":m["outcome"],"error":m["error"],"attempts":m["attempts"].as_array().map(|attempts|attempts.iter().map(|a|json!({"attempt":a["attempt"],"elapsed_ms":a["elapsed_ms"],"served_model":a["reply"]["served_model"],"served_provider":a["reply"]["served_provider"],"usage":a["reply"]["usage"],"error":a["error"]})).collect::<Vec<_>>())})
    }).collect();
    json!({"run":s.world.run,"tick":s.world.tick,"stopped":s.world.stopped,"reasoning_exchanges":exchanges,"event_counts":counts,"players":s.world.players.iter().map(|p|json!({"id":p.id,"name":p.name,"alive":p.health>0,"health":p.health,"hunger":p.hunger,"caution":p.caution,"beliefs":p.beliefs,"relationships":p.relationships,"identity_event_ids":s.events.iter().filter(|e|e.kind=="identity_change"&&e.actor==Some(p.id)).map(|e|e.id).collect::<Vec<_>>()})).collect::<Vec<_>>()})
}
fn serve(out: PathBuf, port: u16, live: bool) -> Result<()> {
    let listener = TcpListener::bind(("127.0.0.1", port))?;
    println!(
        "Inspector: http://127.0.0.1:{port} ({})",
        if live {
            "live operator"
        } else {
            "read-only archive"
        }
    );
    let out = Arc::new(out);
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            if let Ok(stream) = stream {
                let out = out.clone();
                std::thread::spawn(move || {
                    let _ = http(stream, &out, live);
                });
            }
        }
    });
    Ok(())
}
fn http(mut stream: TcpStream, out: &Path, live: bool) -> Result<()> {
    stream.set_read_timeout(Some(Duration::from_secs(3)))?;
    let mut request = Vec::new();
    let mut buf = [0; 4096];
    let end;
    loop {
        let n = stream.read(&mut buf)?;
        if n == 0 {
            return Ok(());
        }
        request.extend_from_slice(&buf[..n]);
        if request.len() > 65536 {
            return Err("request too large".into());
        }
        if let Some(i) = request.windows(4).position(|w| w == b"\r\n\r\n") {
            end = i + 4;
            break;
        }
    }
    let headers = String::from_utf8_lossy(&request[..end]).to_string();
    let line = headers.lines().next().unwrap_or("");
    let fields: Vec<_> = line.split_whitespace().collect();
    let method = fields.first().copied().unwrap_or("");
    let path = fields.get(1).copied().unwrap_or("/");
    let length = headers
        .lines()
        .find_map(|l| {
            l.to_lowercase()
                .strip_prefix("content-length:")
                .and_then(|x| x.trim().parse::<usize>().ok())
        })
        .unwrap_or(0);
    if length > 20000 {
        return Err("body too large".into());
    }
    while request.len() < end + length {
        let n = stream.read(&mut buf)?;
        if n == 0 {
            break;
        }
        request.extend_from_slice(&buf[..n]);
    }
    let response: Result<(String, Vec<u8>)> = (|| {
        if method == "GET" && path == "/" {
            return Ok((
                "text/html; charset=utf-8".into(),
                include_bytes!("../../inspector.html").to_vec(),
            ));
        }
        if method == "GET" && path == "/api/manifest" {
            let mut v: Value = serde_json::from_slice(&fs::read(out.join("manifest.json"))?)?;
            v["live"] = json!(live);
            return Ok(("application/json".into(), serde_json::to_vec(&v)?));
        }
        if method == "GET" && path.starts_with("/api/") {
            let s: Snapshot = serde_json::from_slice(&fs::read(out.join("snapshot.json"))?)?;
            let query: BTreeMap<_, _> = path
                .split_once('?')
                .map(|(_, q)| q.split('&').filter_map(|s| s.split_once('=')).collect())
                .unwrap_or_default();
            if path.starts_with("/api/reasoning?") {
                let id = query
                    .get("request")
                    .ok_or("request ID required")?
                    .parse::<u64>()?;
                return Ok((
                    "application/x-ndjson".into(),
                    fs::read(out.join("reasoning").join(format!("request-{id}.jsonl")))?,
                ));
            }
            let v = if path.starts_with("/api/events") {
                let actor = query.get("actor").and_then(|s| s.parse::<u32>().ok());
                let after = query
                    .get("after")
                    .and_then(|s| s.parse::<u64>().ok())
                    .unwrap_or(0);
                json!(s
                    .events
                    .iter()
                    .filter(|e| e.id > after
                        && actor.is_none_or(|a| e.actor == Some(a))
                        && query.get("kind").is_none_or(|k| *k == e.kind))
                    .collect::<Vec<_>>())
            } else if path.starts_with("/api/context") {
                let id = query.get("actor").ok_or("actor required")?.parse::<u32>()?;
                let i = s
                    .world
                    .players
                    .iter()
                    .position(|p| p.id == id)
                    .ok_or("actor missing")?;
                s.world.context(i)
            } else if path == "/api/snapshot" {
                serde_json::to_value(s)?
            } else {
                return Err("not found".into());
            };
            return Ok(("application/json".into(), serde_json::to_vec(&v)?));
        }
        if method == "POST" && path == "/api/intent" && live {
            if !headers
                .lines()
                .any(|l| l.eq_ignore_ascii_case("x-sao-intent: 1"))
            {
                return Err("local operator header required".into());
            }
            let host = headers
                .lines()
                .find_map(|l| {
                    l.strip_prefix("Host: ")
                        .or_else(|| l.strip_prefix("host: "))
                })
                .ok_or("host missing")?;
            if let Some(origin) = headers.lines().find_map(|l| {
                l.strip_prefix("Origin: ")
                    .or_else(|| l.strip_prefix("origin: "))
            }) {
                if origin != format!("http://{host}") {
                    return Err("cross-origin operator request rejected".into());
                }
            }
            let v: Value =
                serde_json::from_slice(request.get(end..end + length).ok_or("incomplete body")?)?;
            let m: Manifest = serde_json::from_slice(&fs::read(out.join("manifest.json"))?)?;
            let actor = v["actor"].as_u64().ok_or("actor required")?;
            call(
                &m,
                "sim_intent",
                vec![json!(m.run), json!(actor), json!(v["decision"].to_string())],
            )?;
            return Ok(("application/json".into(),b"{\"submitted\":true,\"note\":\"Inspect human_input and decision/intent_rejected records for outcome\"}".to_vec()));
        }
        Err("not found or archive is read-only".into())
    })();
    let (status, mime, body) = match response {
        Ok((m, b)) => ("200 OK", m, b),
        Err(e) => (
            "400 Bad Request",
            "application/json".into(),
            serde_json::to_vec(&json!({"error":e.to_string()}))?,
        ),
    };
    write!(stream,"HTTP/1.1 {status}\r\nContent-Type: {mime}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n",body.len())?;
    stream.write_all(&body)?;
    Ok(())
}
#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    let usage="Usage: sao-sim run SCENARIO OUTPUT [MODEL] [PORT] | inspect OUTPUT [PORT] | compare OUTPUT... | export OUTPUT\nEnvironment: SIM_SERVER (loopback only, default http://127.0.0.1:3100), SIM_TICK_MS (default 1000), SIM_WASM, OLLAMA_URL, SPACETIME_CLI, NPC_REASONING_CONFIG (JSON path)";
    match args.get(1).map(String::as_str) {
        Some("inspect") => {
            let out = PathBuf::from(args.get(2).ok_or(usage)?);
            serve(
                out,
                args.get(3).map(|s| s.parse()).transpose()?.unwrap_or(18877),
                false,
            )?;
            std::future::pending::<()>().await;
        }
        Some("compare") => {
            let mut runs = vec![];
            for out in args.iter().skip(2) {
                let s: Snapshot =
                    serde_json::from_slice(&fs::read(Path::new(out).join("snapshot.json"))?)?;
                runs.push(summarize(&s));
            }
            println!(
                "{}",
                serde_json::to_string_pretty(
                    &json!({"runs":runs,"interpretation":"Descriptive differences, not prescribed narrative or statistical significance; event IDs are local to each run"})
                )?
            );
        }
        Some("export") => {
            let out = PathBuf::from(args.get(2).ok_or(usage)?);
            let m: Manifest = serde_json::from_slice(&fs::read(out.join("manifest.json"))?)?;
            export(&m, &out)?;
            println!("Exported retained database state and audit history");
        }
        Some("run") => {
            let scenario: Scenario = serde_json::from_slice(&fs::read(args.get(2).ok_or(usage)?)?)?;
            let config = if let Ok(path) = std::env::var("NPC_REASONING_CONFIG") {
                if args.get(4).is_some_and(|v| v != "configured") {
                    return Err(
                        "with NPC_REASONING_CONFIG, pass configured instead of a positional model"
                            .into(),
                    );
                }
                serde_json::from_slice::<Config>(&fs::read(path)?)?
            } else {
                Config::ollama(
                    args.get(4).cloned().unwrap_or("qwen2.5:7b".into()),
                    std::env::var("OLLAMA_URL").unwrap_or("http://127.0.0.1:11434".into()),
                    scenario.seed,
                )
            };
            if config.model() == "fixture" {
                return Err("fixtures are test-only; select a real backend/model".into());
            }
            let reasoner = Arc::new(Reasoner::new(config.clone())?);
            let out = PathBuf::from(args.get(3).ok_or(usage)?);
            fs::create_dir_all(out.parent().unwrap_or(Path::new(".")))?;
            fs::create_dir(&out)?;
            let created_ms = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
            let run = format!("sim-{created_ms}-{}", std::process::id());
            let server = std::env::var("SIM_SERVER").unwrap_or("http://127.0.0.1:3100".into());
            let url = reqwest::Url::parse(&server)?;
            if url.scheme() != "http"
                || !matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]"))
            {
                return Err("experiment runner only publishes to a local loopback server".into());
            }
            let wasm = std::env::var("SIM_WASM")
                .unwrap_or("target/wasm32-unknown-unknown/debug/server_module.wasm".into());
            let hash = Command::new("shasum").args(["-a", "256", &wasm]).output()?;
            if !hash.status.success() {
                return Err("build the module WASM first".into());
            }
            let m = Manifest {
                run: run.clone(),
                db: run.clone(),
                server,
                scenario,
                model: config.model().to_string(),
                ollama: match &config.backend {
                    BackendConfig::Ollama { endpoint, .. } => endpoint.clone(),
                    _ => String::new(),
                },
                reasoning: Some(config),
                reasoning_version: bridge::reasoning::REASONING_VERSION.into(),
                decision_format: simulation::DECISION_FORMAT_VERSION.into(),
                tick_ms: std::env::var("SIM_TICK_MS")
                    .ok()
                    .map(|s| s.parse())
                    .transpose()?
                    .unwrap_or(1000),
                rules: VERSION.into(),
                wasm_sha256: String::from_utf8(hash.stdout)?
                    .split_whitespace()
                    .next()
                    .unwrap()
                    .into(),
                runner_sha256: {
                    let result = Command::new("shasum")
                        .args(["-a", "256"])
                        .arg(std::env::current_exe()?)
                        .output()?;
                    if !result.status.success() {
                        return Err("cannot identify runner executable".into());
                    }
                    String::from_utf8(result.stdout)?
                        .split_whitespace()
                        .next()
                        .ok_or("missing runner hash")?
                        .to_string()
                },
                git_head: String::from_utf8(
                    Command::new("git")
                        .args(["rev-parse", "HEAD"])
                        .output()?
                        .stdout,
                )?
                .trim()
                .into(),
                cli_version: command(&["--version".into()])?.trim().into(),
                created_ms,
            };
            // Validate before publish, but never execute the local copy as a simulation runner.
            World::new(run.clone(), m.scenario.clone())?;
            fs::copy(&wasm, out.join("module.wasm"))?;
            write_json(&out.join("manifest.json"), &m)?;
            fs::create_dir(out.join("reasoning"))?;
            reasoner.preflight(&out).await?;
            command(&[
                "publish".into(),
                m.db.clone(),
                "--server".into(),
                m.server.clone(),
                "--bin-path".into(),
                wasm,
                "--delete-data=never".into(),
                "--no-config".into(),
                "--yes".into(),
            ])?;
            call(
                &m,
                "sim_create",
                vec![json!(run), json!(serde_json::to_string(&m.scenario)?)],
            )?;
            let initialized = export(&m, &out)?;
            if initialized.world.version != VERSION {
                return Err("published simulation version differs from runner; rebuild both module and runner".into());
            }
            let port = args.get(5).map(|s| s.parse()).transpose()?.unwrap_or(18877);
            serve(out.clone(), port, true)?;
            println!("Run {} in {}; {} model mode", m.run, out.display(), m.model);
            let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<ReasoningResult>();
            let mut dispatched = HashSet::new();
            let mut active =
                BTreeMap::<u64, (u32, u64, tokio::sync::watch::Sender<Option<String>>)>::new();
            loop {
                while let Ok(result) = rx.try_recv() {
                    call(
                        &m,
                        "sim_model_result",
                        vec![
                            json!(m.run),
                            json!(result.request_id),
                            json!(result.raw),
                            json!(result.metadata.to_string()),
                        ],
                    )?;
                    active.remove(&result.request_id);
                }
                let s = export(&m, &out)?;
                for (id, (actor, generation, cancel)) in &active {
                    let invalid = s.world.stopped
                        || !s.world.pending.iter().any(|p| p.id == *id)
                        || s.world
                            .players
                            .iter()
                            .find(|p| p.id == *actor)
                            .is_none_or(|p| {
                                p.health == 0
                                    || p.controller != simulation::Controller::Ai
                                    || p.generation != *generation
                            });
                    if invalid && cancel.borrow().is_none() {
                        let _ = cancel.send(Some("request no longer current at authority".into()));
                    }
                }
                if s.world.stopped && active.is_empty() {
                    write_json(&out.join("summary.json"), &summarize(&s))?;
                    println!(
                        "Completed at tick {}. Archive remains in {}",
                        s.world.tick,
                        out.display()
                    );
                    break;
                }
                if !s.world.stopped {
                    for p in s.world.pending {
                        if dispatched.insert(p.id) {
                            let tx = tx.clone();
                            let (cancel, cancelled) = tokio::sync::watch::channel(None);
                            active.insert(p.id, (p.actor, p.generation, cancel));
                            let service = reasoner.clone();
                            let run = m.run.clone();
                            let audit_dir = out.join("reasoning");
                            tokio::spawn(async move {
                                let result = service.reason(run, p, cancelled, audit_dir).await;
                                let _ = tx.send(result);
                            });
                        }
                    }
                    call(&m, "sim_step", vec![json!(m.run)])?;
                }
                tokio::time::sleep(Duration::from_millis(m.tick_ms.max(10))).await;
            }
        }
        _ => return Err(usage.into()),
    }
    Ok(())
}

#[cfg(test)]
mod compatibility_tests {
    use super::*;
    #[test]
    fn old_manifest_and_snapshot_load_without_backends_or_credentials() {
        let scenario: Scenario =
            serde_json::from_str(include_str!("../../../../scenarios/survival.json")).unwrap();
        let old = json!({"run":"legacy-run","db":"legacy-run","server":"http://127.0.0.1:3100","scenario":scenario,"model":"qwen2.5:7b","ollama":"http://127.0.0.1:11434","tick_ms":2000,"rules":"m1-2","wasm_sha256":"old-hash","git_head":"old-head","cli_version":"2.7.1","created_ms":1});
        let m: Manifest = serde_json::from_value(old).unwrap();
        assert!(m.reasoning.is_none());
        assert_eq!(m.rules, "m1-2");
        let world = World::new("archive".into(), scenario).unwrap();
        let snapshot = json!({"world":world,"events":world.events});
        let s: Snapshot = serde_json::from_value(snapshot).unwrap();
        assert_eq!(summarize(&s)["run"], "archive");
    }
}
