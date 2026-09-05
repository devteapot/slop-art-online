//! Development host and scoped browser enrollment. World execution remains in reducers.
use axum::{
    Json, Router,
    body::Body,
    extract::{Path, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use bridge::reasoning::{Reasoner, backend::Config};
use bridge::{participant::new_session,agent_harness};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};
use tokio::process::Command;
use spacetimedb_sdk::DbContext;

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
    local_origin: String,
    browser_server: String,
    run: Mutex<String>,
    sessions: Mutex<HashMap<String, Session>>,
    config: Option<Config>,
    harness_cancellations: Mutex<Vec<tokio::sync::watch::Sender<Option<String>>>>,
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
    let mut command = Command::new(binary);
    if let Ok(config_path) = std::env::var("SPACETIME_CONFIG_PATH") {
        command.args(["--config-path", &config_path]);
    }
    let output = command.args(args)
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
fn allowed_origin(origin: &str, local_origin: &str, headers: &HeaderMap) -> bool {
    let supplied = headers.get("origin").and_then(|v| v.to_str().ok());
    (supplied == Some(origin) || supplied == Some(local_origin))
        && headers.get("x-sao-client").and_then(|v| v.to_str().ok()) == Some("1")
}
fn browser_addresses(public_url: &str) -> Result<(String, String), String> {
    let mut url = reqwest::Url::parse(public_url).map_err(|_| "invalid BEVY_DEV_PUBLIC_URL")?;
    if url.scheme() != "http" || url.host_str().is_none()
        || matches!(url.host_str(), Some("0.0.0.0" | "[::]"))
        || !url.username().is_empty() || url.password().is_some()
        || url.path() != "/" || url.query().is_some() || url.fragment().is_some()
    {
        return Err("BEVY_DEV_PUBLIC_URL must be an http:// browser address with a reachable hostname or IP and no credentials, path, query or fragment".into());
    }
    let origin = url.origin().ascii_serialization();
    url.set_port(Some(3101)).map_err(|_| "invalid database port")?;
    Ok((origin, url.origin().ascii_serialization()))
}
fn same_origin(app: &App, headers: &HeaderMap) -> Result<(), (StatusCode, String)> {
    if !allowed_origin(&app.origin, &app.local_origin, headers)
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
    let browser_server = if headers.get("origin").and_then(|v| v.to_str().ok()) == Some(&app.origin) {
        &app.browser_server
    } else {
        &app.server
    };
    if session(&app, &headers).is_ok() {
        return Ok(Json(json!({"db":app.db,"server":browser_server,"run":app.run.lock().unwrap().clone(),"actor":3})).into_response());
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
    let mut response=Json(json!({"db":app.db,"server":browser_server,"run":app.run.lock().unwrap().clone(),"mode":"local development","actor":3})).into_response();
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
        &std::fs::read(app.root.join(std::env::var("BEVY_DEV_SCENARIO").unwrap_or("scenarios/survival.json".into()))).map_err(|_| "scenario missing")?,
    )
    .map_err(|_| "invalid scenario")?;
    scenario["name"] = json!("Bevy development survival");
    scenario["max_ticks"] = json!(std::env::var("BEVY_DEV_MAX_TICKS").ok().and_then(|s|s.parse::<u32>().ok()).unwrap_or(300).clamp(1,300));
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
    let private=app.root.join(".local/credentials");
    std::fs::create_dir_all(&private).map_err(|_|"private session directory unavailable")?;
    let mut links=vec![];
    for (actor,role) in [(1,"builtin"),(2,"external")] {
        let path=private.join(format!("{run}-{role}.json"));
        let (service,identity)=new_session(app.server.clone(),app.db.clone(),&path).await?;
        call(app,"sim_grant_client",vec![json!(run),json!(identity),json!(false),json!(actor)]).await?;
        let view=service.observe(0,256).await?;
        links.push(json!({"actor":actor,"role":role,"session_file":path}));
        if role=="builtin" {
            if let Some(config)=&app.config {
                if std::env::var("SAO_HARNESS_MANUAL").as_deref()==Ok("1"){let _=service.connection.disconnect();continue;}
                let (tx,rx)=tokio::sync::watch::channel(None);
                app.harness_cancellations.lock().unwrap().push(tx);
                tokio::spawn(agent_harness::run(service,config.clone(),dir.join("reasoning"),rx));
            }else{
                let fixture:simulation::Decision=serde_json::from_slice(&std::fs::read(app.root.join("scenarios/reactive-client-fixture.json")).map_err(|_|"fixture missing")?).map_err(|_|"fixture invalid")?;
                let receipt=service.command(simulation::participant::Request{api_version:simulation::participant::API_VERSION.into(),request_id:format!("fixture-{run}"),control_epoch:view["control_epoch"].as_u64().unwrap(),command:simulation::participant::Command::ReplaceTree{expected_revision:view["policy_revision"].as_u64().unwrap(),reason:"explicit test-authored developer fixture; no model inference".into(),tree:fixture.policy.ok_or("fixture tree missing")?}}).await?;
                if !receipt.ok{return Err(format!("fixture rejected: {:?}",receipt.error));}
                let _=service.connection.disconnect();
            }
        }else{let _=service.connection.disconnect();}
    }
    std::fs::write(dir.join("participants.json"),json!(links).to_string()).map_err(|_|"participant descriptors failed")?;
    call(app,"sim_step",vec![json!(run)]).await?;
    Ok(run)
}
async fn fresh(State(app): State<Shared>, headers: HeaderMap) -> ApiResult {
    let (id, s) = session(&app, &headers)?;
    if !s.observer {
        return Err((StatusCode::FORBIDDEN, "observer privilege required".into()));
    }
    for tx in app.harness_cancellations.lock().unwrap().drain(..) { let _=tx.send(Some("run replaced".into())); }
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
    let db = format!("sim-bevy-db-{}", now());
    let server = "http://127.0.0.1:3101".to_string();
    let out = root.join(std::env::var("BEVY_DEV_OUTPUT").unwrap_or("output/participant-agent-dev".into()));
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
        origin,
        local_origin,
        browser_server,
        run: Mutex::new(String::new()),
        sessions: Mutex::new(HashMap::new()),
        config,
        harness_cancellations:Mutex::new(vec![]),
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
    let listener = tokio::net::TcpListener::bind(format!("{bind_addr}:{port}")).await?;
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

#[cfg(test)]
mod network_tests {
    use super::*;

    #[test]
    fn browser_database_uses_advertised_host_including_ipv6() {
        for (url, origin, database) in [
            ("http://192.168.1.117:18891/", "http://192.168.1.117:18891", "http://192.168.1.117:3101"),
            ("http://game.local:19999", "http://game.local:19999", "http://game.local:3101"),
            ("http://[::1]:18891", "http://[::1]:18891", "http://[::1]:3101"),
        ] {
            assert_eq!(browser_addresses(url).unwrap(), (origin.into(), database.into()));
        }
    }

    #[test]
    fn browser_address_rejects_bind_addresses_and_non_origins() {
        for url in ["http://0.0.0.0:18891", "http://[::]:18891", "https://game.local", "http://user:password@game.local", "http://game.local/path", "http://game.local?x=1", "http://game.local#x", "garbage"] {
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
        for origin in ["null", "https://untrusted.example", "http://192.168.1.117:18892", "http://192.168.1.117.evil.example:18891"] {
            headers.insert("origin", origin.parse().unwrap());
            headers.insert("host", origin.strip_prefix("http://").unwrap_or(origin).parse().unwrap());
            assert!(!allowed_origin(public, local, &headers));
        }
        headers.insert("origin", public.parse().unwrap());
        headers.remove("x-sao-client");
        assert!(!allowed_origin(public, local, &headers));
    }
}
