use super::*;
use shared::module_bindings::{
    DbConnection, SimMySnapshotTableAccess, sim_client_control, sim_client_intent,
};
use spacetimedb_sdk::{DbContext, Table};
use std::sync::{Arc, Mutex};

pub enum Signal {
    Http(String, Result<Value, String>),
    Connected(String),
    Connection(Result<DbConnection, String>),
    Status(String),
    Disconnected,
}
#[derive(Clone, Default)]
pub struct Inbox(pub Arc<Mutex<Vec<Signal>>>);
#[derive(Default)]
pub struct Network {
    pub connection: Option<DbConnection>,
    pub inbox: Inbox,
    pub cookie: Arc<Mutex<String>>,
    pub connecting: bool,
    pub retry_at: f64,
    pub latest: String,
}
impl Network {
    pub fn post(&self, tag: &str, path: &str, body: Value) {
        post(
            self.inbox.clone(),
            self.cookie.clone(),
            tag.into(),
            path.into(),
            body,
        );
    }
    pub fn intent(&self, action: Value) {
        let Some(conn) = &self.connection else {
            return;
        };
        let inbox = self.inbox.clone();
        let decision = json!({"reason":"Intent chosen in the Bevy game client","actions":[action],"reflections":[]});
        let r = conn
            .reducers
            .sim_client_intent_then(decision.to_string(), move |_, result| {
                let text = match result {
                    Ok(Ok(())) => {
                        "Intent delivered to authority; effects occur on simulation ticks".into()
                    }
                    Ok(Err(e)) => e,
                    Err(_) => "Intent delivery failed".into(),
                };
                inbox.0.lock().unwrap().push(Signal::Status(text));
            });
        if r.is_err() {
            self.inbox
                .0
                .lock()
                .unwrap()
                .push(Signal::Status("Disconnected: intent not sent".into()));
        }
    }
    pub fn control(&self, command: &str) {
        if let Some(conn) = &self.connection {
            let inbox = self.inbox.clone();
            let _ = conn
                .reducers
                .sim_client_control_then(command.into(), move |_, r| {
                    if let Ok(Err(e)) = r {
                        inbox.0.lock().unwrap().push(Signal::Status(e));
                    }
                });
        }
    }
}
fn connect(inbox: Inbox, server: String, db: String) {
    let connected = inbox.clone();
    let disconnected = inbox.clone();
    let failed = inbox.clone();
    let builder = DbConnection::builder()
        .with_uri(server)
        .with_database_name(db)
        // Never persist or reuse the returned authentication token. Enrollment binds a fresh
        // browser identity through the HttpOnly development session, with no auth in URLs.
        .on_connect(move |ctx, identity, _| {
            ctx.subscription_builder()
                .subscribe(["SELECT * FROM sim_my_snapshot"]);
            connected
                .0
                .lock()
                .unwrap()
                .push(Signal::Connected(identity.to_hex().to_string()));
        })
        .on_disconnect(move |_, _| {
            disconnected.0.lock().unwrap().push(Signal::Disconnected);
        })
        .on_connect_error(move |_, _| {
            failed.0.lock().unwrap().push(Signal::Disconnected);
        });
    #[cfg(target_arch = "wasm32")]
    wasm_bindgen_futures::spawn_local(async move {
        let connection = builder
            .build()
            .await
            .map_err(|_| "Could not connect to authoritative server".into());
        inbox.0.lock().unwrap().push(Signal::Connection(connection));
    });
    #[cfg(not(target_arch = "wasm32"))]
    std::thread::spawn(move || {
        inbox.0.lock().unwrap().push(Signal::Connection(
            builder
                .build()
                .map_err(|_| "Could not connect to authoritative server".into()),
        ));
    });
}
fn post(inbox: Inbox, cookie: Arc<Mutex<String>>, tag: String, path: String, body: Value) {
    #[cfg(target_arch = "wasm32")]
    {
        let _ = cookie;
        wasm_bindgen_futures::spawn_local(async move {
            let result = async {
                let origin = web_sys::window()
                    .ok_or("browser window missing")?
                    .location()
                    .origin()
                    .map_err(|_| "origin unavailable")?;
                let req = gloo_net::http::Request::post(&format!("{origin}{path}"))
                    .header("x-sao-client", "1")
                    .json(&body)
                    .map_err(|_| "request failed")?;
                let response = req
                    .send()
                    .await
                    .map_err(|_| "development host unavailable")?;
                if !response.ok() {
                    return Err(response.text().await.unwrap_or("Request rejected".into()));
                }
                response
                    .json::<Value>()
                    .await
                    .map_err(|_| "invalid host response".into())
            }
            .await;
            inbox.0.lock().unwrap().push(Signal::Http(tag, result));
        });
    }
    #[cfg(not(target_arch = "wasm32"))]
    std::thread::spawn(move || {
        let result = (|| {
            let origin = std::env::var("BEVY_DEV_URL").unwrap_or("http://127.0.0.1:18891".into());
            let response = reqwest::blocking::Client::new()
                .post(format!("{origin}{path}"))
                .header("origin", &origin)
                .header("x-sao-client", "1")
                .header("cookie", cookie.lock().unwrap().clone())
                .json(&body)
                .send()
                .map_err(|_| "development host unavailable")?;
            if let Some(value) = response
                .headers()
                .get("set-cookie")
                .and_then(|v| v.to_str().ok())
            {
                *cookie.lock().unwrap() = value.split(';').next().unwrap_or("").into();
            }
            if !response.status().is_success() {
                return Err(response.text().unwrap_or("Request rejected".into()));
            }
            response
                .json::<Value>()
                .map_err(|_| "invalid host response".into())
        })();
        inbox.0.lock().unwrap().push(Signal::Http(tag, result));
    });
}
pub fn start(mut net: NonSendMut<Network>) {
    net.connecting = true;
    net.post("boot", "/api/session", json!({}));
}
pub fn tick(mut net: NonSendMut<Network>, mut game: ResMut<Game>, time: Res<Time>) {
    if let Some(conn) = &net.connection {
        let _ = conn.frame_tick();
    }
    let signals = std::mem::take(&mut *net.inbox.0.lock().unwrap());
    for signal in signals {
        game.dirty = true;
        match signal {
            Signal::Http(tag, Ok(value)) => match tag.as_str() {
                "boot" => {
                    game.status = "Connecting to authoritative run…".into();
                    connect(
                        net.inbox.clone(),
                        value["server"].as_str().unwrap().into(),
                        value["db"].as_str().unwrap().into(),
                    );
                }
                "archive" => {
                    game.snapshot = value;
                    game.archive = true;
                    game.selected = 1;
                    game.dirty = true;
                    game.status = "Recorded Qwen policy · archive is read-only".into();
                }
                "mode" => {
                    game.status = "Role granted by authority".into();
                    game.scroll = [0.; 2];
                    game.snapshot = Value::Null;
                    net.latest.clear();
                    game.archive = false;
                    game.selected = if value["observer"] == true { 1 } else { 3 };
                    game.dirty = true;
                }
                "new" => {
                    game.archive = false;
                    net.latest.clear();
                    game.selected = 1;
                    game.status = "Fresh bounded run created; paused".into();
                }
                _ => {
                    game.status = "Connected · state and effects come from SpacetimeDB".into();
                }
            },
            Signal::Http(_, Err(error)) | Signal::Status(error) => {
                game.status = error;
                game.dirty = true;
            }
            Signal::Connected(identity) => {
                net.post("bind", "/api/bind", json!({"identity":identity}));
            }
            Signal::Connection(Ok(conn)) => {
                net.connection = Some(conn);
                net.connecting = false;
            }
            Signal::Connection(Err(error)) => {
                game.status = error;
                net.connecting = false;
                net.retry_at = time.elapsed_secs_f64() + 3.;
            }
            Signal::Disconnected => {
                game.status = "Disconnected; reconnecting…".into();
                net.connection = None;
                net.connecting = false;
                net.retry_at = time.elapsed_secs_f64() + 3.;
            }
        }
    }
    if !game.archive {
        if let Some(conn) = &net.connection {
            let body = conn
                .db
                .sim_my_snapshot()
                .iter()
                .next()
                .map(|s| s.body.clone());
            if let Some(body) = body {
                if body != net.latest {
                    if let Ok(snapshot) = serde_json::from_str(&body) {
                        game.snapshot = snapshot;
                        game.dirty = true;
                    }
                    net.latest = body;
                }
            } else if !net.latest.is_empty() {
                net.latest.clear();
                game.snapshot = Value::Null;
                game.status = "No active grant for this connection".into();
                game.dirty = true;
            }
        }
    }
    if net.connection.is_none() && !net.connecting && time.elapsed_secs_f64() >= net.retry_at {
        net.connecting = true;
        net.post("boot", "/api/session", json!({}));
    }
}
