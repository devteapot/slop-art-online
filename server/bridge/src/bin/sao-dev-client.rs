//! Loopback development host and scoped browser enrollment. World execution remains in reducers.
use axum::{
    Json, Router,
    body::Body,
    extract::{Path, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use bridge::reasoning::{Reasoner, backend::Config};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};
use tokio::process::Command;

#[derive(Clone)]
struct Session {
    identity: Option<String>,
    observer: bool,
}
struct App {
    root: PathBuf,
    out: PathBuf,
    db: String,
    server: String,
    origin: String,
    run: Mutex<String>,
    sessions: Mutex<HashMap<String, Session>>,
    config: Option<Config>,
}
type Shared = Arc<App>;
type ApiResult = Result<Response, (StatusCode, String)>;
fn error(s: impl ToString) -> (StatusCode, String) {
    (StatusCode::BAD_REQUEST, s.to_string())
}
fn now() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis()
}
async fn cli(args: Vec<String>) -> Result<String, String> {
    let binary = if args.first().is_some_and(|arg| arg != "publish") {
        std::env::var("SPACETIME_CONTROL_CLI").unwrap_or("spacetime".into())
    } else {
        std::env::var("SPACETIME_CLI").unwrap_or_else(|_| {
            format!(
                "{}/.local/share/spacetime/bin/2.1.0/spacetimedb-cli",
                std::env::var("HOME").unwrap()
            )
        })
    };
    let output = Command::new(binary)
        .args(args)
        .output()
        .await
        .map_err(|_| "SpacetimeDB CLI unavailable")?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).into());
    }
    Ok(String::from_utf8_lossy(&output.stdout).into())
}
async fn call(app: &App, name: &str, args: Vec<Value>) -> Result<(), String> {
    let mut command = vec!["call".into(), app.db.clone(), name.into()];
    command.extend(args.into_iter().map(|v| v.to_string()));
    command.extend([
        "--server".into(),
        app.server.clone(),
        "--no-config".into(),
        "-y".into(),
    ]);
    cli(command).await.map(|_| ())
}
async fn sql(app: &App, query: &str) -> Result<Vec<Vec<Value>>, String> {
    let text = cli(vec![
        "sql".into(),
        app.db.clone(),
        query.into(),
        "--server".into(),
        app.server.clone(),
        "--format".into(),
        "json".into(),
        "--no-config".into(),
    ])
    .await?;
    let value: Value = serde_json::from_str(&text).map_err(|_| "invalid database reply")?;
    serde_json::from_value(value[0]["rows"].clone()).map_err(|_| "invalid rows".into())
}
async fn state(app: &App, run: &str) -> Result<simulation::World, String> {
    let rows = sql(
        app,
        &format!("SELECT state FROM sim_run WHERE id = '{run}'"),
    )
    .await?;
    serde_json::from_str(
        rows.first()
            .and_then(|r| r[0].as_str())
            .ok_or("run missing")?,
    )
    .map_err(|_| "invalid world".into())
}
async fn audit(app: &App, run: &str) -> Result<Vec<simulation::Event>, String> {
    let mut events: Vec<simulation::Event> = sql(
        app,
        &format!("SELECT json FROM sim_audit WHERE run = '{run}'"),
    )
    .await?
    .into_iter()
    .filter_map(|r| serde_json::from_str(r[0].as_str()?).ok())
    .collect();
    events.sort_by_key(|e| e.id);
    Ok(events)
}
fn same_origin(app: &App, headers: &HeaderMap) -> Result<(), (StatusCode, String)> {
    if headers.get("origin").and_then(|v| v.to_str().ok()) != Some(&app.origin)
        || headers.get("x-sao-client").and_then(|v| v.to_str().ok()) != Some("1")
    {
        return Err((
            StatusCode::FORBIDDEN,
            "local same-origin development request required".into(),
        ));
    }
    Ok(())
}
fn session(app: &App, headers: &HeaderMap) -> Result<(String, Session), (StatusCode, String)> {
    same_origin(app, headers)?;
    let id = headers
        .get("cookie")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| {
            s.split(';')
                .find_map(|part| part.trim().strip_prefix("sao_dev=").map(str::to_string))
        })
        .ok_or((StatusCode::UNAUTHORIZED, "local session required".into()))?;
    let s = app.sessions.lock().unwrap().get(&id).cloned().ok_or((
        StatusCode::UNAUTHORIZED,
        "session expired; reconnect".into(),
    ))?;
    Ok((id, s))
}
async fn bootstrap(State(app): State<Shared>, headers: HeaderMap) -> ApiResult {
    same_origin(&app, &headers)?;
    if session(&app, &headers).is_ok() {
        return Ok(Json(json!({"db":app.db,"server":app.server,"run":app.run.lock().unwrap().clone(),"actor":3})).into_response());
    }
    let id = format!(
        "{:032x}{:032x}",
        rand::random::<u128>(),
        rand::random::<u128>()
    );
    app.sessions.lock().unwrap().insert(
        id.clone(),
        Session {
            identity: None,
            observer: true,
        },
    );
    let mut response=Json(json!({"db":app.db,"server":app.server,"run":app.run.lock().unwrap().clone(),"mode":"local development","actor":3})).into_response();
    response.headers_mut().insert(
        header::SET_COOKIE,
        format!("sao_dev={id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400")
            .parse()
            .unwrap(),
    );
    Ok(response)
}
async fn bind(State(app): State<Shared>, headers: HeaderMap, Json(body): Json<Value>) -> ApiResult {
    let (id, mut s) = session(&app, &headers)?;
    let identity = body["identity"].as_str().ok_or(error("identity missing"))?;
    if identity.len() != 64 || !identity.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(error("invalid identity"));
    }
    if let Some(old) = &s.identity {
        if old != identity {
            call(&app, "sim_revoke_client", vec![json!(old)])
                .await
                .map_err(error)?;
        }
    }
    let run = app.run.lock().unwrap().clone();
    call(
        &app,
        "sim_grant_client",
        vec![json!(run), json!(identity), json!(s.observer), json!(3)],
    )
    .await
    .map_err(error)?;
    s.identity = Some(identity.into());
    app.sessions.lock().unwrap().insert(id, s);
    Ok(Json(json!({"ok":true,"run":run})).into_response())
}
async fn mode(State(app): State<Shared>, headers: HeaderMap, Json(body): Json<Value>) -> ApiResult {
    let (id, mut s) = session(&app, &headers)?;
    let observer = body["observer"].as_bool().ok_or(error("mode missing"))?;
    let identity = s.identity.clone().ok_or(error("connect first"))?;
    let run = app.run.lock().unwrap().clone();
    call(
        &app,
        "sim_grant_client",
        vec![json!(run), json!(identity), json!(observer), json!(3)],
    )
    .await
    .map_err(error)?;
    s.observer = observer;
    app.sessions.lock().unwrap().insert(id, s);
    Ok(Json(json!({"ok":true,"observer":observer})).into_response())
}
async fn create_run(app: &App) -> Result<String, String> {
    let run = format!("sim-bevy-{}", now());
    let mut scenario: Value = serde_json::from_slice(
        &std::fs::read(app.root.join("scenarios/survival.json")).map_err(|_| "scenario missing")?,
    )
    .map_err(|_| "invalid scenario")?;
    scenario["name"] = json!("Bevy development survival");
    scenario["max_ticks"] = json!(300);
    call(
        app,
        "sim_create",
        vec![json!(run), json!(scenario.to_string())],
    )
    .await?;
    call(app, "sim_step", vec![json!(run)]).await?;
    if app.config.is_none() {
        let w = state(app, &run).await?;
        let raw = std::fs::read_to_string(app.root.join("scenarios/reactive-client-fixture.json"))
            .map_err(|_| "fixture missing")?;
        for pending in w.pending {
            call(
                app,
                "sim_model_result",
                vec![
                    json!(run),
                    json!(pending.id),
                    json!(raw),
                    json!(
                        json!({"source":"explicit developer fixture","not_model_generated":true})
                            .to_string()
                    ),
                ],
            )
            .await?;
        }
    }
    call(
        app,
        "sim_setup_client_clock",
        vec![
            json!(run),
            json!(if app.config.is_some() {
                "live_model"
            } else {
                "live_fixture"
            }),
        ],
    )
    .await?;
    let dir = app.out.join(&run);
    std::fs::create_dir(&dir).map_err(|_| "archive creation failed")?;
    std::fs::create_dir(dir.join("reasoning")).map_err(|_| "audit directory failed")?;
    std::fs::write(dir.join("scenario.json"), scenario.to_string())
        .map_err(|_| "scenario archive failed")?;
    for (source, name) in [
        ("Cargo.lock", "Cargo.lock"),
        (
            "target/wasm32-unknown-unknown/debug/server_module.wasm",
            "module.wasm",
        ),
    ] {
        std::fs::copy(app.root.join(source), dir.join(name))
            .map_err(|_| "version archive failed")?;
    }
    if app.config.is_none() {
        std::fs::copy(
            app.root.join("scenarios/reactive-client-fixture.json"),
            dir.join("fixture-policy.json"),
        )
        .map_err(|_| "fixture archive failed")?;
    }

    std::fs::write(dir.join("mode.json"),json!({"run":run,"db":app.db,"server":app.server,"evidence_mode":if app.config.is_some(){"live_model"}else{"live_fixture"},"note":"actual authoritative run; fixture explicitly test-authored; no model substitution"}).to_string()).map_err(|_|"mode write failed")?;
    Ok(run)
}
async fn fresh(State(app): State<Shared>, headers: HeaderMap) -> ApiResult {
    let (id, s) = session(&app, &headers)?;
    if !s.observer {
        return Err((StatusCode::FORBIDDEN, "observer privilege required".into()));
    }
    let old = app.run.lock().unwrap().clone();
    call(&app, "sim_operator_pause", vec![json!(old)])
        .await
        .map_err(error)?;
    let run = create_run(&app).await.map_err(error)?;
    *app.run.lock().unwrap() = run.clone();
    if let Some(identity) = s.identity {
        call(
            &app,
            "sim_grant_client",
            vec![json!(run), json!(identity), json!(true), json!(3)],
        )
        .await
        .map_err(error)?;
    }
    write_active(&app).map_err(error)?;
    let _ = id;
    Ok(Json(json!({"run":run})).into_response())
}
fn write_active(app: &App) -> std::io::Result<()> {
    std::fs::write(app.out.join("active.json"), json!({"db":app.db,"server":app.server,"run":app.run.lock().unwrap().clone(),"url":app.origin}).to_string())
}
async fn archive(State(app): State<Shared>, headers: HeaderMap) -> ApiResult {
    let (_, s) = session(&app, &headers)?;
    if !s.observer {
        return Err((
            StatusCode::FORBIDDEN,
            "observer privilege required for archive truth".into(),
        ));
    }
    let file = app
        .root
        .join("output/local-reactive-feedback-proof/snapshot.json");
    let value: Value =
        serde_json::from_slice(&std::fs::read(file).map_err(error)?).map_err(error)?;
    let world: simulation::World = serde_json::from_value(value["world"].clone()).map_err(error)?;
    let events: Vec<simulation::Event> =
        serde_json::from_value(value["events"].clone()).map_err(error)?;
    let mut snapshot = simulation::client_view::snapshot(&world, true, 3, &events);
    snapshot["paused"] = json!(true);
    snapshot["evidence_mode"] = json!("archive_read_only_actual_qwen_generated_policy");
    Ok(Json(snapshot).into_response())
}
async fn files(State(app): State<Shared>, Path(path): Path<String>) -> Response {
    if path.split('/').any(|p| p == ".." || p.starts_with('.')) {
        return StatusCode::NOT_FOUND.into_response();
    }
    let path = if path.is_empty() { "index.html" } else { &path };
    let file = app.root.join("client/dist").join(path);
    match tokio::fs::read(file).await {
        Ok(bytes) => {
            let mime = if path.ends_with(".wasm") {
                "application/wasm"
            } else if path.ends_with(".js") {
                "text/javascript"
            } else if path.ends_with(".html") {
                "text/html"
            } else {
                "application/octet-stream"
            };
            (
                [
                    (header::CONTENT_TYPE, mime),
                    (header::CACHE_CONTROL, "no-store"),
                ],
                Body::from(bytes),
            )
                .into_response()
        }
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}
async fn index(State(app): State<Shared>) -> Response {
    files(State(app), Path("index.html".into())).await
}
async fn background(app: Shared) {
    let mut jobs = HashMap::new();
    loop {
        tokio::time::sleep(std::time::Duration::from_millis(600)).await;
        let run = app.run.lock().unwrap().clone();
        let Ok(w) = state(&app, &run).await else {
            continue;
        };
        if let Ok(events) = audit(&app, &run).await {
            let dir = app.out.join(&run);
            let _ = std::fs::write(
                dir.join("snapshot.json"),
                json!({"world":w,"events":events}).to_string(),
            );
        }
        // The scheduler ticks in the authority independently of any pending external reasoning.
        if let Some(config) = &app.config {
            for p in &w.pending {
                let key = (run.clone(), p.id);
                if jobs.contains_key(&key)
                    || app
                        .out
                        .join(&run)
                        .join(format!("reasoning/request-{}.jsonl", p.id))
                        .exists()
                {
                    continue;
                }
                let Ok(reasoner) = Reasoner::new(config.clone()) else {
                    continue;
                };
                let (tx, rx) = tokio::sync::watch::channel(None);
                jobs.insert(key, tx);
                let task_app = app.clone();
                let pending = p.clone();
                let task_run = run.clone();
                tokio::spawn(async move {
                    let result = reasoner
                        .reason(
                            task_run.clone(),
                            pending,
                            rx,
                            task_app.out.join(&task_run).join("reasoning"),
                        )
                        .await;
                    let _ = call(
                        &task_app,
                        "sim_model_result",
                        vec![
                            json!(task_run),
                            json!(result.request_id),
                            json!(result.raw),
                            json!(result.metadata.to_string()),
                        ],
                    )
                    .await;
                });
            }
            for ((job_run, id), tx) in &jobs {
                if job_run != &run
                    || w.stopped
                    || !w.pending.iter().any(|p| {
                        p.id == *id
                            && w.tick.saturating_sub(p.tick) <= simulation::REQUEST_EXPIRY_TICKS
                    })
                {
                    let _ = tx.send(Some("run stopped, replaced or request expired".into()));
                }
            }
        }
    }
}
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let root = std::env::current_dir()?;
    let port = std::env::var("BEVY_DEV_PORT").unwrap_or("18890".into());
    let db = format!("sim-bevy-db-{}", now());
    let server = "http://127.0.0.1:3101".to_string();
    let out = root.join("output/bevy-browser-dev");
    std::fs::create_dir_all(&out)?;
    let config = std::env::var("NPC_REASONING_CONFIG")
        .ok()
        .map(
            |p| -> Result<Config, Box<dyn std::error::Error + Send + Sync>> {
                let c: Config = serde_json::from_slice(&std::fs::read(p)?)?;
                Reasoner::new(c.clone())?;
                Ok(c)
            },
        )
        .transpose()?;
    let app = Arc::new(App {
        root,
        out,
        db,
        server,
        origin: format!("http://127.0.0.1:{port}"),
        run: Mutex::new(String::new()),
        sessions: Mutex::new(HashMap::new()),
        config,
    });
    cli(vec![
        "publish".into(),
        app.db.clone(),
        "--server".into(),
        app.server.clone(),
        "--bin-path".into(),
        "target/wasm32-unknown-unknown/debug/server_module.wasm".into(),
        "--delete-data=never".into(),
        "--no-config".into(),
        "-y".into(),
    ])
    .await?;
    *app.run.lock().unwrap() = create_run(&app).await?;
    write_active(&app)?;
    tokio::spawn(background(app.clone()));
    let router = Router::new()
        .route("/", get(index))
        .route("/api/session", post(bootstrap))
        .route("/api/bind", post(bind))
        .route("/api/mode", post(mode))
        .route("/api/new-run", post(fresh))
        .route("/api/archive", post(archive))
        .route("/{*path}", get(files))
        .with_state(app.clone());
    let listener = tokio::net::TcpListener::bind(format!("127.0.0.1:{port}")).await?;
    println!(
        "Bevy game client: {} — live authoritative {}, initially paused",
        app.origin,
        if app.config.is_some() {
            "model mode"
        } else {
            "explicit fixture mode, no inference"
        }
    );
    axum::serve(listener, router).await?;
    Ok(())
}
