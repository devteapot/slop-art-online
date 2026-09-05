//! Real SDK/reducer permission and shared-skill check on a separate test run, no model calls.
use serde_json::{Value, json};
use shared::module_bindings::*;
use spacetimedb_sdk::{DbContext, Identity, Table};
use std::{
    process::Command,
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
fn cli(db: &str, name: &str, args: Vec<Value>) -> bool {
    let mut c = Command::new("spacetime");
    c.args(["call", db, name]);
    for a in args {
        c.arg(a.to_string());
    }
    c.args(["--server", "http://127.0.0.1:3101", "--no-config", "-y"]);
    c.output().unwrap().status.success()
}
fn wait(conns: &[&DbConnection], check: impl Fn() -> bool) {
    let start = Instant::now();
    loop {
        for c in conns {
            c.frame_tick().unwrap();
        }
        if check() {
            return;
        }
        assert!(
            start.elapsed() < Duration::from_secs(8),
            "timed out waiting for authority"
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}
fn connect(db: &str) -> (DbConnection, Arc<Mutex<Option<Identity>>>) {
    let id = Arc::new(Mutex::new(None));
    let copy = id.clone();
    let conn = DbConnection::builder()
        .with_uri("http://127.0.0.1:3101")
        .with_database_name(db)
        .on_connect(move |c, identity, _| {
            *copy.lock().unwrap() = Some(identity);
            c.subscription_builder()
                .subscribe(["SELECT * FROM sim_my_snapshot"]);
        })
        .build()
        .unwrap();
    (conn, id)
}
fn view(c: &DbConnection) -> Option<Value> {
    c.db.sim_my_snapshot()
        .iter()
        .next()
        .map(|r| serde_json::from_str(&r.body).unwrap())
}
fn main() {
    let active: Value =
        serde_json::from_slice(&std::fs::read("output/bevy-browser-dev/active.json").unwrap())
            .unwrap();
    let db = active["db"].as_str().unwrap();
    let run = format!(
        "sim-bevy-access-{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis()
    );
    let scenario = std::fs::read_to_string("scenarios/survival.json").unwrap();
    assert!(cli(db, "sim_create", vec![json!(run), json!(scenario)]));
    assert!(cli(db, "sim_step", vec![json!(run)]));
    assert!(cli(
        db,
        "sim_setup_client_clock",
        vec![json!(run), json!("live_bootstrap")]
    ));
    let (a, ai) = connect(db);
    let (b, bi) = connect(db);
    let (c, ci) = connect(db);
    let conns = [&a, &b, &c];
    wait(&conns, || {
        ai.lock().unwrap().is_some() && bi.lock().unwrap().is_some() && ci.lock().unwrap().is_some()
    });
    let aid = ai.lock().unwrap().unwrap();
    let bid = bi.lock().unwrap().unwrap();
    let cid = ci.lock().unwrap().unwrap();
    assert!(view(&a).is_none() && view(&b).is_none());
    let private_denied = Arc::new(Mutex::new(false));
    let flag = private_denied.clone();
    c.subscription_builder()
        .on_error(move |_, _| *flag.lock().unwrap() = true)
        .subscribe(["SELECT * FROM sim_run"]);
    wait(&conns, || *private_denied.lock().unwrap());
    let denied = Arc::new(Mutex::new(None));
    let flag = denied.clone();
    c.reducers
        .sim_grant_client_then(run.clone(), cid, true, 3, move |_, r| {
            *flag.lock().unwrap() = Some(matches!(r, Ok(Err(_))))
        })
        .unwrap();
    wait(&conns, || denied.lock().unwrap().is_some());
    assert_eq!(*denied.lock().unwrap(), Some(true));
    assert!(cli(
        db,
        "sim_grant_client",
        vec![
            json!(run),
            json!(aid.to_hex().to_string()),
            json!(true),
            json!(3)
        ]
    ));
    assert!(cli(
        db,
        "sim_grant_client",
        vec![
            json!(run),
            json!(bid.to_hex().to_string()),
            json!(false),
            json!(3)
        ]
    ));
    wait(&conns, || view(&a).is_some() && view(&b).is_some());
    let observer = view(&a).unwrap();
    let participant = view(&b).unwrap();
    assert!(
        observer["sites"]
            .as_array()
            .unwrap()
            .iter()
            .any(|s| s.get("hazard").is_some())
    );
    assert!(
        participant["sites"]
            .as_array()
            .unwrap()
            .iter()
            .all(|s| s.get("hazard").is_none())
    );
    assert!(participant["pending"].is_null());
    for p in participant["players"].as_array().unwrap() {
        if p["id"] != 3 {
            assert!(p.get("beliefs").is_none());
            assert!(p.get("health").is_none());
        }
    }
    assert!(!cli(
        db,
        "sim_grant_client",
        vec![
            json!(run),
            json!(cid.to_hex().to_string()),
            json!(false),
            json!(3)
        ]
    ));
    let denied = Arc::new(Mutex::new(None));
    let flag = denied.clone();
    b.reducers
        .sim_client_control_then("step".into(), move |_, r| {
            *flag.lock().unwrap() = Some(matches!(r, Ok(Err(_))))
        })
        .unwrap();
    wait(&conns, || denied.lock().unwrap().is_some());
    assert_eq!(*denied.lock().unwrap(), Some(true));
    let denied = Arc::new(Mutex::new(None));
    let flag = denied.clone();
    b.reducers
        .sim_intent_then(run.clone(), 1, "{}".into(), move |_, r| {
            *flag.lock().unwrap() = Some(matches!(r, Ok(Err(_))))
        })
        .unwrap();
    wait(&conns, || denied.lock().unwrap().is_some());
    assert_eq!(*denied.lock().unwrap(), Some(true));
    let position = participant["players"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["id"] == 3)
        .unwrap()["position"]
        .as_i64()
        .unwrap();
    let destination = position + 1;
    let accepted = Arc::new(Mutex::new(false));
    let flag = accepted.clone();
    b.reducers.sim_client_intent_then(json!({"reason":"real client ownership check","actions":[{"skill":"move","destination":destination,"duration":1}],"reflections":[]}).to_string(),move|_,r|*flag.lock().unwrap()=matches!(r,Ok(Ok(())))).unwrap();
    wait(&conns, || *accepted.lock().unwrap());
    a.reducers.sim_client_control("step".into()).unwrap();
    wait(&conns, || view(&b).is_some_and(|v| v["tick"] == 2));
    let after = view(&b).unwrap();
    assert_eq!(
        after["players"]
            .as_array()
            .unwrap()
            .iter()
            .find(|p| p["id"] == 3)
            .unwrap()["position"],
        destination
    );
    let speech = "A client chooses these exact words; shared rules carry the sound.";
    let accepted = Arc::new(Mutex::new(false));
    let flag = accepted.clone();
    b.reducers.sim_client_intent_then(json!({"reason":"free-form speech check","actions":[{"skill":"speak","text":speech,"duration":1}],"reflections":[]}).to_string(),move|_,r|*flag.lock().unwrap()=matches!(r,Ok(Ok(())))).unwrap();
    wait(&conns, || *accepted.lock().unwrap());
    a.reducers.sim_client_control("step".into()).unwrap();
    wait(&conns, || view(&a).is_some_and(|v| v["tick"] == 3));
    let full = view(&a).unwrap();
    assert!(
        full["players"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|p| p["id"] != 3)
            .any(|p| p["memories"].to_string().contains(speech))
    );
    assert!(cli(
        db,
        "sim_revoke_client",
        vec![json!(aid.to_hex().to_string())]
    ));
    wait(&conns, || view(&a).is_none());
    assert!(cli(
        db,
        "sim_revoke_client",
        vec![json!(bid.to_hex().to_string())]
    ));
    wait(&conns, || view(&b).is_none());
    let result = json!({"run":run,"db":db,"private_tables_denied":true,"ungranted_view_empty":true,"non_operator_grant_denied":true,"participant_hidden_truth_excluded":true,"human_ownership_exclusive":true,"participant_time_control_denied":true,"other_actor_input_denied":true,"same_authority_movement":true,"free_form_speech_heard":true,"revocation_removes_view":true,"observer_snapshot":full});
    std::fs::write(
        "output/bevy-browser-dev/access-verification.json",
        serde_json::to_vec_pretty(&result).unwrap(),
    )
    .unwrap();
    println!("Real browser-access protocol checks passed; report saved. No model calls.");
}
