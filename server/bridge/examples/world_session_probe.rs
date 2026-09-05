//! Real broker/SDK regression: detached views, independent clocks, focus and role boundaries.
//! Run against an isolated fixture host using BEVY_DEV_URL; creates one additional paused run.
use serde_json::{json, Value};
use shared::module_bindings::*;
use spacetimedb_sdk::{DbContext, Table};
use std::{
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

struct View {
    http: reqwest::Client,
    origin: String,
    name: String,
    cookie: String,
    conn: DbConnection,
}
impl View {
    async fn new(origin: &str, name: &str) -> Self {
        let http = reqwest::Client::new();
        let response = http
            .post(format!("{origin}/api/session"))
            .header("origin", origin)
            .header("x-sao-client", "1")
            .header("x-sao-view", name)
            .json(&json!({}))
            .send()
            .await
            .unwrap()
            .error_for_status()
            .unwrap();
        let cookie = response.headers()["set-cookie"]
            .to_str()
            .unwrap()
            .split(';')
            .next()
            .unwrap()
            .to_string();
        let descriptor: Value = response.json().await.unwrap();
        let identity = Arc::new(Mutex::new(None));
        let copy = identity.clone();
        let conn = tokio::task::block_in_place(|| {
            DbConnection::builder()
                .with_uri(descriptor["server"].as_str().unwrap())
                .with_database_name(descriptor["db"].as_str().unwrap())
                .on_connect(move |c, id, _| {
                    *copy.lock().unwrap() = Some(id);
                    c.subscription_builder()
                        .subscribe(["SELECT * FROM sim_my_snapshot"]);
                })
                .build()
                .unwrap()
        });
        let deadline = Instant::now() + Duration::from_secs(10);
        while identity.lock().unwrap().is_none() {
            tokio::task::block_in_place(|| conn.frame_tick()).unwrap();
            assert!(Instant::now() < deadline);
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        let id = identity.lock().unwrap().unwrap().to_hex().to_string();
        let view = Self {
            http,
            origin: origin.into(),
            name: name.into(),
            cookie,
            conn,
        };
        view.post("bind", json!({"identity":id})).await;
        view.wait(|v| v["observer"] == true).await;
        view
    }
    async fn response(&self, path: &str, body: Value) -> reqwest::Response {
        self.http
            .post(format!("{}/api/{path}", self.origin))
            .header("origin", &self.origin)
            .header("x-sao-client", "1")
            .header("x-sao-view", &self.name)
            .header("cookie", &self.cookie)
            .json(&body)
            .send()
            .await
            .unwrap()
    }
    async fn post(&self, path: &str, body: Value) -> Value {
        self.response(path, body)
            .await
            .error_for_status()
            .unwrap()
            .json()
            .await
            .unwrap()
    }
    fn snapshot(&self) -> Option<Value> {
        tokio::task::block_in_place(|| self.conn.frame_tick()).unwrap();
        self.conn
            .db
            .sim_my_snapshot()
            .iter()
            .next()
            .map(|r| serde_json::from_str(&r.body).unwrap())
    }
    async fn wait(&self, condition: impl Fn(&Value) -> bool) -> Value {
        let deadline = Instant::now() + Duration::from_secs(12);
        loop {
            if let Some(v) = self.snapshot() {
                if condition(&v) {
                    return v;
                }
            }
            assert!(Instant::now() < deadline, "authority update timed out");
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }
    async fn control(&self, command: &str) {
        self.conn
            .reducers
            .sim_client_control(command.into())
            .unwrap();
    }
}
#[tokio::main]
async fn main() {
    let origin = std::env::var("BEVY_DEV_URL").unwrap_or("http://127.0.0.1:18892".into());
    let a = View::new(&origin, "probeWorld").await;
    let b = View::new(&origin, "probeInspector").await;
    let initial = a.wait(|v| v["paused"] == true).await;
    let old = initial["run"].as_str().unwrap().to_string();
    a.control("resume").await;
    a.wait(|v| v["paused"] == false).await;
    let fresh = a.post("new-run", json!({})).await["run"]
        .as_str()
        .unwrap()
        .to_string();
    assert_ne!(old, fresh);
    a.wait(|v| v["run"] == fresh && v["paused"] == true).await;
    let before = b.wait(|v| v["run"] == old && v["paused"] == false).await["tick"]
        .as_u64()
        .unwrap();
    b.wait(|v| v["run"] == old && v["tick"].as_u64().unwrap() > before)
        .await;
    // Both sessions run concurrently, and each view can control only its focus.
    a.control("resume").await;
    a.wait(|v| v["run"] == fresh && v["tick"].as_u64().unwrap() > 1)
        .await;
    b.control("pause").await;
    b.wait(|v| v["paused"] == true).await;
    assert_eq!(a.snapshot().unwrap()["paused"], false);
    a.control("pause").await;
    a.wait(|v| v["paused"] == true).await;
    let roster = a.post("runs", json!({})).await;
    assert!(roster["runs"]
        .as_array()
        .unwrap()
        .iter()
        .any(|r| r["run"] == old));
    assert!(roster["runs"]
        .as_array()
        .unwrap()
        .iter()
        .any(|r| r["run"] == fresh));
    a.post("focus", json!({"run":old})).await;
    a.wait(|v| v["run"] == old).await;
    b.post("focus", json!({"run":fresh})).await;
    b.wait(|v| v["run"] == fresh).await;
    assert_eq!(a.post("session", json!({})).await["run"], old);
    assert_eq!(b.post("session", json!({})).await["run"], fresh);
    assert_eq!(
        a.response("focus", json!({"run":"unregistered-run"}))
            .await
            .status(),
        400
    );
    b.post("mode", json!({"observer":false})).await;
    let participant = b.wait(|v| v["observer"] == false).await;
    assert!(participant["sites"]
        .as_array()
        .unwrap()
        .iter()
        .all(|s| s.get("hazard").is_none()));
    for route in ["focus", "runs", "new-run"] {
        assert_eq!(b.response(route, json!({"run":old})).await.status(), 403);
    }
    b.post("mode", json!({"observer":true})).await;
    b.wait(|v| v["observer"] == true).await;
    a.conn.disconnect().unwrap();
    b.conn.disconnect().unwrap();
    println!("PASS: independent views, concurrent clocks, retained sessions, focus/reload persistence, unknown-run rejection, participant isolation. Runs {old} and {fresh} left paused.");
}
