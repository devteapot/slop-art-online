//! Development host and scoped browser enrollment. World execution remains in reducers.
use axum::{
    body::Body,
    extract::{Path, State},
    http::{header, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use bridge::reasoning::{backend::Config, Reasoner};
use bridge::{agent_harness, owner_snapshot::{self, SnapshotApi}, participant::new_session};
use serde_json::{json, Value};
use spacetimedb_sdk::DbContext;
use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};
use tokio::process::Command;
#[path = "sao-dev-client/transport.rs"]
mod transport;
#[path = "sao-dev-client/enrollment.rs"]
mod enrollment;
#[path = "sao-dev-client/export.rs"]
mod export;

#[derive(Clone)]
struct Session {
    identity: Option<String>,
    observer: bool,
    run: String,
}
#[derive(Clone, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ActorConfig {
    actor: u32,
    role: String,
    config: Config,
}
struct App {
    root: PathBuf,
    out: PathBuf,
    db: String,
    server: String,
    owner_snapshot_api: SnapshotApi,
    origin: String,
    local_origin: String,
    browser_server: String,
    run: Mutex<String>,
    sessions: Mutex<HashMap<String, Session>>,
    runs: Mutex<Vec<String>>,
    mutation: tokio::sync::Mutex<()>,
    config: Option<Config>,
    controllers: Vec<ActorConfig>,
    newcomer: Option<enrollment::NewcomerController>,
    enrollments: tokio::sync::Mutex<enrollment::Registry>,
    harness_cancellations: Mutex<Vec<tokio::sync::watch::Sender<Option<String>>>>,
}
type Shared = Arc<App>;
type ApiResult = Result<Response, (StatusCode, String)>;
fn error(s: impl ToString) -> (StatusCode, String) {
    (StatusCode::BAD_REQUEST, s.to_string())
}
fn module_path() -> String {
    std::env::var("BEVY_DEV_MODULE")
        .unwrap_or("target/wasm32-unknown-unknown/debug/server_module.wasm".into())
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
    let mut command = Command::new(binary);
    if let Ok(config_path) = std::env::var("SPACETIME_CONFIG_PATH") {
        command.args(["--config-path", &config_path]);
    }
    let output = tokio::time::timeout(std::time::Duration::from_secs(30),
        command.args(args).kill_on_drop(true).output())
        .await.map_err(|_| "SpacetimeDB CLI exceeded its 30-second deadline")?
        .map_err(|_| "SpacetimeDB CLI unavailable")?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).into());
    }
    Ok(String::from_utf8_lossy(&output.stdout).into())
}
async fn call_text(app: &App, name: &str, args: Vec<Value>) -> Result<String, String> {
    let mut command = vec!["call".into(), app.db.clone(), name.into()];
    command.extend(args.into_iter().map(|v| v.to_string()));
    command.extend([
        "--server".into(),
        app.server.clone(),
        "--no-config".into(),
        "-y".into(),
    ]);
    cli(command).await
}
async fn call(app: &App, name: &str, args: Vec<Value>) -> Result<(), String> {
    call_text(app, name, args).await.map(|_| ())
}
async fn sql_text(app: &App, query: &str) -> Result<String, String> {
    cli(vec![
        "sql".into(), app.db.clone(), query.into(), "--server".into(),
        app.server.clone(), "--format".into(), "json".into(), "--no-config".into(),
    ]).await.map_err(|error| {
        // CLI stderr can contain query/transport details; background diagnostics
        // distinguish deadlines without logging response text or credentials.
        if error == "SpacetimeDB CLI exceeded its 30-second deadline" {
            "database SQL read exceeded its 30-second deadline".into()
        } else { "database SQL read failed".into() }
    })
}
async fn sql(app: &App, query: &str) -> Result<Vec<Vec<Value>>, String> {
    export::rows(&sql_text(app, query).await?)
}
fn parse_world_reply(api: SnapshotApi, reply: &str) -> Result<String, String> {
    match api {
        SnapshotApi::Sql => {
            let rows: Vec<(String,)> = export::rows(reply)?;
            if rows.len() != 1 { return Err("run missing or ambiguous".into()); }
            Ok(rows.into_iter().next().unwrap().0)
        }
        SnapshotApi::Procedure => owner_snapshot::parse_export_json(reply),
    }
}
async fn world_json(app: &App, run: &str) -> Result<String, String> {
    let reply = match app.owner_snapshot_api {
        SnapshotApi::Sql => sql_text(app, &format!("SELECT state FROM sim_run WHERE id = '{run}'")).await?,
        SnapshotApi::Procedure => call_text(app, owner_snapshot::EXPORT_PROCEDURE, vec![json!(run)])
            .await.map_err(|error| {
                if error == "SpacetimeDB CLI exceeded its 30-second deadline" {
                    "owner export exceeded its 30-second deadline"
                } else { "owner export call failed" }
            })?,
    };
    let api = app.owner_snapshot_api;
    tokio::task::spawn_blocking(move || parse_world_reply(api, &reply))
        .await.map_err(|_| "world row worker failed")?
}
async fn state(app: &App, run: &str) -> Result<simulation::World, String> {
    let body = world_json(app, run).await?;
    let expected_run = run.to_owned();
    tokio::task::spawn_blocking(move || {
        let world: simulation::World = serde_json::from_str(&body).map_err(|_| "invalid world")?;
        if world.run != expected_run || world.next_event == 0 {
            return Err("world identity or event cursor invalid".into());
        }
        Ok(world)
    })
        .await.map_err(|_| "world decode worker failed")?
}
fn loopback_url(value: &str) -> bool {
    reqwest::Url::parse(value).is_ok_and(|u| {
        matches!(u.scheme(), "http" | "https")
            && u.username().is_empty()
            && u.password().is_none()
            && u.path() == "/"
            && u.query().is_none()
            && u.fragment().is_none()
            && matches!(u.host_str(), Some("localhost" | "127.0.0.1" | "[::1]"))
    })
}
fn browser_origin_allowed(origin: &str, local_origin: &str, headers: &HeaderMap) -> bool {
    let supplied = headers.get("origin").and_then(|v| v.to_str().ok());
    supplied == Some(origin)
        || supplied == Some(local_origin)
        || supplied.is_some_and(|value| {
            loopback_url(value)
                && headers
                    .get("host")
                    .and_then(|v| v.to_str().ok())
                    .is_some_and(|host| loopback_url(&format!("http://{host}")))
        })
}
fn allowed_origin(origin: &str, local_origin: &str, headers: &HeaderMap) -> bool {
    browser_origin_allowed(origin, local_origin, headers)
        && headers.get("x-sao-client").and_then(|v| v.to_str().ok()) == Some("1")
}
fn browser_addresses(public_url: &str) -> Result<(String, String), String> {
    let url = reqwest::Url::parse(public_url).map_err(|_| "invalid BEVY_DEV_PUBLIC_URL")?;
    if url.scheme() != "http"
        || url.host_str().is_none()
        || matches!(url.host_str(), Some("0.0.0.0" | "[::]"))
        || !url.username().is_empty()
        || url.password().is_some()
        || url.path() != "/"
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("BEVY_DEV_PUBLIC_URL must be an http:// browser address with a reachable hostname or IP and no credentials, path, query or fragment".into());
    }
    let origin = url.origin().ascii_serialization();
    Ok((origin.clone(), origin))
}
fn same_origin(app: &App, headers: &HeaderMap) -> Result<(), (StatusCode, String)> {
    if !allowed_origin(&app.origin, &app.local_origin, headers) {
        return Err((
            StatusCode::FORBIDDEN,
            "local same-origin development request required".into(),
        ));
    }
    Ok(())
}
fn cookie_name(headers: &HeaderMap) -> Result<String, (StatusCode, String)> {
    let view = headers
        .get("x-sao-view")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    if view.len() > 40 || !view.chars().all(|c| c.is_ascii_alphanumeric()) {
        return Err(error("invalid view identifier"));
    }
    Ok(if view.is_empty() {
        "sao_dev".into()
    } else {
        format!("sao_dev_{view}")
    })
}
fn session(app: &App, headers: &HeaderMap) -> Result<(String, Session), (StatusCode, String)> {
    same_origin(app, headers)?;
    let prefix = format!("{}=", cookie_name(headers)?);
    let id = headers
        .get("cookie")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| {
            s.split(';')
                .find_map(|part| part.trim().strip_prefix(&prefix).map(str::to_string))
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
    let browser_server = headers
        .get("origin")
        .and_then(|v| v.to_str().ok())
        .unwrap_or(&app.browser_server);
    if let Ok((_, s)) = session(&app, &headers) {
        return Ok(
            Json(json!({"db":app.db,"server":browser_server,"run":s.run,"actor":0}))
                .into_response(),
        );
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
            run: app.run.lock().unwrap().clone(),
        },
    );
    let mut response=Json(json!({"db":app.db,"server":browser_server,"run":app.run.lock().unwrap().clone(),"mode":"local development","actor":0})).into_response();
    response.headers_mut().insert(
        header::SET_COOKIE,
        format!(
            "{}={id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400",
            cookie_name(&headers)?
        )
        .parse()
        .unwrap(),
    );
    Ok(response)
}
async fn bind(State(app): State<Shared>, headers: HeaderMap, Json(body): Json<Value>) -> ApiResult {
    let _guard = app.mutation.lock().await;
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
    let run = s.run.clone();
    call(
        &app,
        "sim_grant_client",
        vec![
            json!(run),
            json!(identity),
            json!(s.observer),
            json!(if s.observer { 0 } else { 3 }),
        ],
    )
    .await
    .map_err(error)?;
    s.identity = Some(identity.into());
    app.sessions.lock().unwrap().insert(id, s);
    Ok(Json(json!({"ok":true,"run":run})).into_response())
}
async fn mode(State(app): State<Shared>, headers: HeaderMap, Json(body): Json<Value>) -> ApiResult {
    let _guard = app.mutation.lock().await;
    let (id, mut s) = session(&app, &headers)?;
    let observer = body["observer"].as_bool().ok_or(error("mode missing"))?;
    let identity = s.identity.clone().ok_or(error("connect first"))?;
    let run = s.run.clone();
    call(
        &app,
        "sim_grant_client",
        vec![
            json!(run),
            json!(identity),
            json!(observer),
            json!(if observer { 0 } else { 3 }),
        ],
    )
    .await
    .map_err(error)?;
    s.observer = observer;
    app.sessions.lock().unwrap().insert(id, s);
    Ok(Json(json!({"ok":true,"observer":observer})).into_response())
}
async fn create_run(app: &App) -> Result<String, String> {
    let run = format!("sim-bevy-{}", now());
    let mut scenario: Value =
        serde_json::from_slice(
            &std::fs::read(app.root.join(
                std::env::var("BEVY_DEV_SCENARIO").unwrap_or("scenarios/survival.json".into()),
            ))
            .map_err(|_| "scenario missing")?,
        )
        .map_err(|_| "invalid scenario")?;
    scenario["max_ticks"] = json!(std::env::var("BEVY_DEV_MAX_TICKS")
        .ok()
        .and_then(|s| s.parse::<u32>().ok())
        .unwrap_or(300)
        .clamp(1, 10_000));
    let parsed: simulation::Scenario = serde_json::from_value(scenario.clone()).map_err(|e| e.to_string())?;
    simulation::World::new(run.clone(), parsed.clone())?;
    if !app.controllers.is_empty() {
        let mut ids = std::collections::BTreeSet::new();
        for entry in &app.controllers {
            if parsed.arenas.iter().find(|a|a.actors.contains(&entry.actor)).and_then(|a|a.controllers.get(&entry.actor)).is_some_and(|role|*role!=entry.role) {
                return Err("controller manifest disagrees with arena metadata".into());
            }
            if !ids.insert(entry.actor) || !matches!(entry.role.as_str(), "builtin" | "external")
                || !parsed.players.iter().any(|p| p.id == entry.actor && p.controller == simulation::Controller::Ai) {
                return Err("controller manifest requires unique existing AI actors and builtin/external roles".into());
            }
        }
        if ids.len() != parsed.players.len() { return Err("matrix needs one controller per actor".into()); }
    }
    call(
        app,
        "sim_create_participant",
        vec![json!(run), json!(scenario.to_string())],
    )
    .await?;
    call(
        app,
        "sim_setup_client_clock",
        vec![
            json!(run),
            json!(if app.config.is_some() || !app.controllers.is_empty() {
                "live_model"
            } else {
                "live_fixture"
            }),
        ],
    )
    .await?;
    if let Ok(interval) = std::env::var("BEVY_DEV_TICK_MS") {
        let tick_ms: u64 = interval.parse().map_err(|_| "invalid BEVY_DEV_TICK_MS")?;
        call(
            app,
            "sim_operator_clock",
            vec![json!(run), json!(tick_ms), json!(true)],
        )
        .await?;
    }
    let dir = app.out.join(&run);
    std::fs::create_dir(&dir).map_err(|_| "archive creation failed")?;
    std::fs::create_dir(dir.join("reasoning")).map_err(|_| "audit directory failed")?;
    std::fs::write(dir.join("scenario.json"), scenario.to_string())
        .map_err(|_| "scenario archive failed")?;
    let module = module_path();
    for (source, name) in [
        ("Cargo.lock", "Cargo.lock"),
        (module.as_str(), "module.wasm"),
    ] {
        std::fs::copy(app.root.join(source), dir.join(name))
            .map_err(|_| "version archive failed")?;
    }
    if app.config.is_none() && app.controllers.is_empty() {
        std::fs::copy(
            app.root.join("scenarios/reactive-client-fixture.json"),
            dir.join("fixture-policy.json"),
        )
        .map_err(|_| "fixture archive failed")?;
    }

    std::fs::write(dir.join("mode.json"),json!({"run":run,"db":app.db,"server":app.server,"evidence_mode":if app.config.is_some() || !app.controllers.is_empty(){"live_model"}else{"live_fixture"},"note":"actual authoritative run; fixture explicitly test-authored; no model substitution"}).to_string()).map_err(|_|"mode write failed")?;
    let entries: Vec<(u32, &str, Option<&Config>)> = if app.controllers.is_empty() {
        vec![(1, "builtin", app.config.as_ref()), (2, "external", app.config.as_ref())]
    } else {
        app.controllers.iter().map(|c| (c.actor, c.role.as_str(), Some(&c.config))).collect()
    };
    for (actor, role, config) in entries {
        enrollment::enroll_initial(app, &run, actor, role, config).await?;
    }

    app.runs.lock().unwrap().push(run.clone());
    Ok(run)
}
async fn fresh(State(app): State<Shared>, headers: HeaderMap) -> ApiResult {
    if std::env::var_os("BEVY_DEV_ARCHIVE_ONLY").is_some() {
        return Err(error("completed experiment viewer; create new runs through the batch coordinator"));
    }
    let _guard = app.mutation.lock().await;
    let (id, mut s) = session(&app, &headers)?;
    if !s.observer {
        return Err((StatusCode::FORBIDDEN, "observer privilege required".into()));
    }
    let run = create_run(&app).await.map_err(error)?;
    *app.run.lock().unwrap() = run.clone();
    if let Some(identity) = &s.identity {
        call(
            &app,
            "sim_grant_client",
            vec![json!(run), json!(identity), json!(true), json!(0)],
        )
        .await
        .map_err(error)?;
    }
    write_active(&app).map_err(error)?;
    s.run = run.clone();
    app.sessions.lock().unwrap().insert(id, s);
    Ok(Json(json!({"run":run})).into_response())
}
// Focus only rebinds this view. It never changes any run's clock or harness.
async fn focus(
    State(app): State<Shared>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> ApiResult {
    let _guard = app.mutation.lock().await;
    let (id, mut s) = session(&app, &headers)?;
    if !s.observer {
        return Err((StatusCode::FORBIDDEN, "observer privilege required".into()));
    }
    let run = body["run"].as_str().ok_or(error("run missing"))?;
    if !app.runs.lock().unwrap().iter().any(|r| r == run) {
        return Err(error("unknown hosted run"));
    }
    let identity = s.identity.as_ref().ok_or(error("connect first"))?;
    call(
        &app,
        "sim_grant_client",
        vec![json!(run), json!(identity), json!(true), json!(0)],
    )
    .await
    .map_err(error)?;
    s.run = run.into();
    app.sessions.lock().unwrap().insert(id, s);
    Ok(Json(json!({"run":run})).into_response())
}
async fn runs(State(app): State<Shared>, headers: HeaderMap) -> ApiResult {
    let (_, s) = session(&app, &headers)?;
    if !s.observer {
        return Err((StatusCode::FORBIDDEN, "observer privilege required".into()));
    }
    let ids = app.runs.lock().unwrap().clone();
    // Return only session metadata; world detail remains the caller-specific SDK projection.
    let clocks = sql(&app, "SELECT run, paused FROM sim_client_clock")
        .await
        .map_err(error)?;
    let mut entries = vec![];
    for run in ids {
        if let Ok(w) = state(&app, &run).await {
            let paused = clocks
                .iter()
                .find(|r| r.first() == Some(&json!(run)))
                .and_then(|r| r.get(1))
                .cloned()
                .unwrap_or(Value::Null);
            entries.push(json!({"run":run,"tick":w.tick,"stopped":w.stopped,"paused":paused}));
        }
    }
    Ok(Json(json!({"runs":entries})).into_response())
}
fn write_active(app: &App) -> std::io::Result<()> {
    std::fs::write(app.out.join("active.json"), json!({"db":app.db,"server":app.server,"run":app.run.lock().unwrap().clone(),"url":app.origin,
        "owner_snapshot_api":app.owner_snapshot_api,"enrollment_protocol":enrollment::PROTOCOL,"newcomer_enrollment":app.newcomer.is_some()}).to_string())
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
    let file = app.root.join("client/dist-participant").join(path);
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
    let mut exports = HashMap::<String, export::Export>::new();
    loop {
        tokio::time::sleep(std::time::Duration::from_millis(600)).await;
        if let Err(error) = enrollment::acknowledge_stop(&app).await {
            eprintln!("enrollment shutdown: {error}");
        }
        let runs = app.runs.lock().unwrap().clone();
        for run in runs {
            let body = match world_json(&app, &run).await {
                Ok(body) => body,
                Err(error) => { eprintln!("snapshot export {run}: {error}"); continue; }
            };
            let mut saved = exports.remove(&run).unwrap_or_default();
            let expected_run = run.clone();
            let prepared = tokio::task::spawn_blocking(move || {
                let result = saved.prepare(&expected_run, &body);
                (saved, result)
            }).await;
            let (saved, result) = match prepared {
                Ok(value) => value,
                Err(_) => { eprintln!("snapshot export {run}: world decode worker failed"); continue; }
            };
            if let Err(error) = result {
                eprintln!("snapshot export {run}: {error}");
                exports.insert(run, saved);
                continue;
            }
            // Enrollment still retries on an unchanged world, using the cached
            // typed state rather than reparsing its retained observations.
            if let Err(error) = enrollment::discover(&app, &run, saved.world()).await {
                eprintln!("newcomer enrollment: {error}");
                let path = app.out.join("enrollment-errors.json");
                if !path.exists() {
                    let _ = enrollment::atomic_json(&path, &json!({"errors":[{"run":run,"error":error,"at_ms":now()}]}));
                }
            }
            if !saved.pending() { exports.insert(run, saved); continue; }
            let reply = if let Some(query) = saved.audit_query() {
                match sql_text(&app, &query).await {
                    Ok(reply) => Some(reply),
                    Err(error) => {
                        eprintln!("snapshot export {run}: {error}");
                        exports.insert(run, saved);
                        continue;
                    }
                }
            } else { None };
            let path = app.out.join(&run).join("snapshot.json");
            // Large first exports and local disk writes do not occupy a Tokio
            // worker shared with the participant harnesses and transports.
            let written = tokio::task::spawn_blocking(move || {
                let mut saved = saved;
                let result = (|| {
                    if let Some(reply) = reply { saved.append(&reply)?; }
                    saved.write(&path)
                })();
                (saved, result)
            }).await;
            match written {
                Ok((saved, result)) => {
                    if let Err(error) = result { eprintln!("snapshot export {run}: {error}"); }
                    exports.insert(run, saved);
                }
                Err(_) => eprintln!("snapshot export {run}: serialization worker failed"),
            }
        }
    }
}
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let root = std::env::current_dir()?;
    let port = std::env::var("BEVY_DEV_PORT").unwrap_or("18891".into());
    let bind_addr = std::env::var("BEVY_DEV_BIND").unwrap_or("127.0.0.1".into());
    let local_origin = format!("http://127.0.0.1:{port}");
    let public_url = std::env::var("BEVY_DEV_PUBLIC_URL").unwrap_or(local_origin.clone());
    let (origin, browser_server) = browser_addresses(&public_url)?;
    let resume = std::env::var("BEVY_DEV_RESUME_ACTIVE")
        .ok()
        .map(
            |path| -> Result<Value, Box<dyn std::error::Error + Send + Sync>> {
                Ok(serde_json::from_slice(&std::fs::read(path)?)?)
            },
        )
        .transpose()?;
    let db = match &resume {
        Some(active) => active["db"]
            .as_str()
            .ok_or("resume database missing")?
            .to_owned(),
        None => format!("sim-bevy-db-{}-{}", now(), std::process::id()),
    };
    let server = std::env::var("BEVY_DEV_SERVER")
        .unwrap_or_else(|_| "http://127.0.0.1:3101".to_string());
    let out = root
        .join(std::env::var("BEVY_DEV_OUTPUT").unwrap_or("output/participant-agent-dev".into()));
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
    let controllers: Vec<ActorConfig> = std::env::var("BEVY_DEV_CONTROLLERS").ok()
        .map(|path| -> Result<_, Box<dyn std::error::Error + Send + Sync>> {
            Ok(serde_json::from_slice(&std::fs::read(path)?)?)
        }).transpose()?.unwrap_or_default();
    for c in &controllers { Reasoner::new(c.config.clone())?; }
    let newcomer: Option<enrollment::NewcomerController> = std::env::var("BEVY_DEV_NEWCOMER_CONTROLLER").ok()
        .map(|path| -> Result<_, Box<dyn std::error::Error + Send + Sync>> {
            Ok(serde_json::from_slice(&std::fs::read(path)?)?)
        }).transpose()?;
    if let Some(template) = &newcomer { template.validate()?; }
    let app = Arc::new(App {
        root,
        out,
        db,
        server,
        owner_snapshot_api: SnapshotApi::from_env()?,
        origin,
        local_origin,
        browser_server,
        run: Mutex::new(String::new()),
        sessions: Mutex::new(HashMap::new()),
        runs: Mutex::new(vec![]),
        mutation: tokio::sync::Mutex::new(()),
        config,
        controllers,
        newcomer,
        enrollments: tokio::sync::Mutex::new(enrollment::Registry::default()),
        harness_cancellations: Mutex::new(vec![]),
    });
    if let Some(active) = resume {
        let run = active["run"].as_str().ok_or("resume run missing")?;
        state(&app, run).await?;
        *app.run.lock().unwrap() = run.into();
        app.runs.lock().unwrap().push(run.into());
    } else {
        cli(vec![
            "publish".into(),
            app.db.clone(),
            "--server".into(),
            app.server.clone(),
            "--bin-path".into(),
            module_path(),
            "--delete-data=never".into(),
            "--no-config".into(),
            "-y".into(),
        ])
        .await?;
        *app.run.lock().unwrap() = create_run(&app).await?;
    }
    if std::env::var_os("BEVY_DEV_ARCHIVE_ONLY").is_none() {
        write_active(&app)?;
        tokio::spawn(background(app.clone()));
    }
    let router = Router::new()
        .route("/", get(index))
        .route("/api/session", post(bootstrap))
        .route(
            "/v1/database/{database}/subscribe",
            get(transport::subscribe),
        )
        .route("/api/bind", post(bind))
        .route("/api/mode", post(mode))
        .route("/api/new-run", post(fresh))
        .route("/api/archive", post(archive))
        .route("/api/runs", post(runs))
        .route("/api/focus", post(focus))
        .route("/{*path}", get(files))
        .with_state(app.clone());
    let listener = tokio::net::TcpListener::bind(format!("{bind_addr}:{port}")).await?;
    println!(
        "Bevy game client: {} — live authoritative {}, initially paused",
        app.origin,
        if app.config.is_some() || !app.controllers.is_empty() {
            "model mode"
        } else {
            "explicit fixture mode, no inference"
        }
    );
    axum::serve(listener, router).await?;
    Ok(())
}

#[cfg(test)]
mod network_tests {
    use super::*;

    #[test]
    fn owner_snapshot_mode_selects_its_wire_format_without_fallback() {
        let body = "{\"run\":\"r\",\"next_event\":1}";
        let sql = json!([{"rows":[[body]]}]).to_string();
        let procedure = json!([0, body]).to_string();
        assert_eq!(parse_world_reply(SnapshotApi::from_setting(None).unwrap(), &sql).unwrap(), body);
        assert_eq!(parse_world_reply(SnapshotApi::Procedure, &procedure).unwrap(), body);
        assert!(parse_world_reply(SnapshotApi::Sql, &procedure).is_err());
        assert!(parse_world_reply(SnapshotApi::Procedure, &sql).is_err());
        assert_eq!(parse_world_reply(SnapshotApi::Procedure, "[1,\"run unavailable\"]").unwrap_err(), "run unavailable");
    }

    #[test]
    fn forwarded_loopback_browser_uses_one_origin_and_keeps_csrf_check() {
        let mut headers = HeaderMap::new();
        headers.insert("host", "127.0.0.1:18909".parse().unwrap());
        headers.insert("origin", "http://localhost:62271".parse().unwrap());
        assert!(!allowed_origin(
            "http://127.0.0.1:18909",
            "http://127.0.0.1:18909",
            &headers
        ));
        headers.insert("x-sao-client", "1".parse().unwrap());
        assert!(allowed_origin(
            "http://127.0.0.1:18909",
            "http://127.0.0.1:18909",
            &headers
        ));
        for origin in [
            "http://localhost.evil.test:62271",
            "http://user@localhost:62271",
            "null",
            "http://localhost:62271/path",
        ] {
            headers.insert("origin", origin.parse().unwrap());
            assert!(!allowed_origin(
                "http://127.0.0.1:18909",
                "http://127.0.0.1:18909",
                &headers
            ));
        }
        headers.insert("origin", "http://localhost:62271".parse().unwrap());
        headers.insert("host", "untrusted.example".parse().unwrap());
        assert!(!allowed_origin(
            "http://127.0.0.1:18909",
            "http://127.0.0.1:18909",
            &headers
        ));
    }

    #[test]
    fn view_cookies_are_distinct_and_reject_invalid_names() {
        let mut headers = HeaderMap::new();
        assert_eq!(cookie_name(&headers).unwrap(), "sao_dev");
        headers.insert("x-sao-view", "world123".parse().unwrap());
        assert_eq!(cookie_name(&headers).unwrap(), "sao_dev_world123");
        headers.insert("x-sao-view", "inspector456".parse().unwrap());
        assert_eq!(cookie_name(&headers).unwrap(), "sao_dev_inspector456");
        for invalid in ["bad;cookie", "../world", "two views", &"a".repeat(41)] {
            headers.insert("x-sao-view", invalid.parse().unwrap());
            assert!(cookie_name(&headers).is_err());
        }
    }

    #[test]
    fn browser_database_uses_advertised_host_including_ipv6() {
        for (url, origin, database) in [
            (
                "http://192.168.1.117:18891/",
                "http://192.168.1.117:18891",
                "http://192.168.1.117:18891",
            ),
            (
                "http://game.local:19999",
                "http://game.local:19999",
                "http://game.local:19999",
            ),
            (
                "http://[::1]:18891",
                "http://[::1]:18891",
                "http://[::1]:18891",
            ),
        ] {
            assert_eq!(
                browser_addresses(url).unwrap(),
                (origin.into(), database.into())
            );
        }
    }

    #[test]
    fn browser_address_rejects_bind_addresses_and_non_origins() {
        for url in [
            "http://0.0.0.0:18891",
            "http://[::]:18891",
            "https://game.local",
            "http://user:password@game.local",
            "http://game.local/path",
            "http://game.local?x=1",
            "http://game.local#x",
            "garbage",
        ] {
            assert!(browser_addresses(url).is_err(), "{url}");
        }
    }

    #[test]
    fn lan_enrollment_requires_exact_configured_origin_and_client_header() {
        let public = "http://192.168.1.117:18891";
        let local = "http://127.0.0.1:18891";
        let mut headers = HeaderMap::new();
        headers.insert("x-sao-client", "1".parse().unwrap());
        assert!(!allowed_origin(public, local, &headers));
        for origin in [public, local] {
            headers.insert("origin", origin.parse().unwrap());
            assert!(allowed_origin(public, local, &headers));
        }
        for origin in [
            "null",
            "https://untrusted.example",
            "http://192.168.1.117:18892",
            "http://192.168.1.117.evil.example:18891",
        ] {
            headers.insert("origin", origin.parse().unwrap());
            headers.insert(
                "host",
                origin
                    .strip_prefix("http://")
                    .unwrap_or(origin)
                    .parse()
                    .unwrap(),
            );
            assert!(!allowed_origin(public, local, &headers));
        }
        headers.insert("origin", public.parse().unwrap());
        headers.remove("x-sao-client");
        assert!(!allowed_origin(public, local, &headers));
    }
}
