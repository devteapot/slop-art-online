//! Full participant/MCP/built-in harness parity against an isolated real SpacetimeDB run.
use bridge::{
    agent_harness::{deliberate_once, Responsibility},
    participant::{new_session, ParticipantService},
    reasoning::backend::Config,
};
use serde_json::{json, Value};
use shared::module_bindings::*;
use simulation::{
    participant::{Command, Request, API_VERSION},
    Action, Node, Reflection,
};
use spacetimedb_sdk::{DbContext, Table};
use std::{
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
async fn cli(db: &str, name: &str, args: Vec<Value>) -> bool {
    let mut c = tokio::process::Command::new("spacetime");
    c.args(["call", db, name]);
    for a in args {
        c.arg(a.to_string());
    }
    c.args(["--server", "http://127.0.0.1:3101", "--no-config", "-y"]);
    let out = c.output().await.unwrap();
    if !out.status.success() {
        eprintln!(
            "expected/actual reducer rejection for {name}: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }
    out.status.success()
}
async fn send(
    s: &ParticipantService,
    id: &str,
    command: Command,
) -> simulation::participant::Receipt {
    let v = s.observe(0, 256).await.unwrap();
    s.command(Request {
        api_version: API_VERSION.into(),
        request_id: id.into(),
        control_epoch: v["control_epoch"].as_u64().unwrap(),
        command,
    })
    .await
    .unwrap()
}
async fn wait(check: impl Fn() -> bool) {
    let start = std::time::Instant::now();
    while !check() {
        assert!(
            start.elapsed() < Duration::from_secs(10),
            "authority timeout"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}
async fn mcp(path: &Path, stage: &str, out: &Path) {
    let status = tokio::process::Command::new("python3")
        .args([
            "scripts/verify_participant_mcp.py",
            path.to_str().unwrap(),
            stage,
            out.to_str().unwrap(),
        ])
        .status()
        .await
        .unwrap();
    assert!(status.success());
}
#[tokio::main]
async fn main() {
    let a: Value =
        serde_json::from_slice(&std::fs::read("output/participant-agent-dev/active.json").unwrap())
            .unwrap();
    let db = a["db"].as_str().unwrap();
    let run = format!(
        "sim-participant-proof-{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis()
    );
    let out = PathBuf::from("output/participant-agent-dev").join(&run);
    std::fs::create_dir(&out).unwrap();
    let mut scenario: Value =
        serde_json::from_str(include_str!("../../../scenarios/survival.json")).unwrap();
    for s in scenario["sites"].as_array_mut().unwrap() {
        s["hazard"] = json!(0);
    }
    for p in scenario["players"].as_array_mut().unwrap() {
        p["position"] = json!(0);
        p["caution"] = json!(50);
    }
    scenario["max_ticks"] = json!(30);
    assert!(
        cli(
            db,
            "sim_create_participant",
            vec![json!(run), json!(scenario.to_string())]
        )
        .await
    );
    assert!(
        cli(
            db,
            "sim_setup_client_clock",
            vec![json!(run), json!("live_fixture")]
        )
        .await
    );
    let private = PathBuf::from(".local/credentials");
    let (internal, iid) = new_session(
        "http://127.0.0.1:3101".into(),
        db.into(),
        &private.join(format!("{run}-internal.json")),
    )
    .await
    .unwrap();
    let external_path = private.join(format!("{run}-external.json"));
    let (external, eid) = new_session("http://127.0.0.1:3101".into(), db.into(), &external_path)
        .await
        .unwrap();
    let (stranger, sid) = new_session(
        "http://127.0.0.1:3101".into(),
        db.into(),
        &private.join(format!("{run}-stranger.json")),
    )
    .await
    .unwrap();
    assert!(stranger.current().is_err());
    assert!(
        cli(
            db,
            "sim_grant_client",
            vec![json!(run), json!(iid), json!(false), json!(1)]
        )
        .await
    );
    assert!(
        cli(
            db,
            "sim_grant_client",
            vec![json!(run), json!(eid), json!(false), json!(2)]
        )
        .await
    );
    assert!(
        !cli(
            db,
            "sim_grant_client",
            vec![json!(run), json!(sid), json!(false), json!(1)]
        )
        .await
    );
    let iv = internal.observe(0, 256).await.unwrap();
    let ev = external.observe(0, 256).await.unwrap();
    assert_eq!(iv["actor"], 1);
    assert_eq!(ev["actor"], 2);
    assert!(iv.get("sites").is_none());
    assert!(ev.get("pending").is_none());
    let denied = Arc::new(Mutex::new(false));
    let d = denied.clone();
    internal
        .connection
        .subscription_builder()
        .on_error(move |_, _| *d.lock().unwrap() = true)
        .subscribe(["SELECT * FROM sim_run"]);
    wait(|| *denied.lock().unwrap()).await;
    let denied = Arc::new(Mutex::new(false));
    let d = denied.clone();
    external
        .connection
        .reducers
        .sim_step_then(run.clone(), move |_, r| {
            *d.lock().unwrap() = matches!(r, Ok(Err(_)))
        })
        .unwrap();
    wait(|| *denied.lock().unwrap()).await;
    assert!(
        !cli(
            db,
            "sim_model_result",
            vec![json!(run), json!(0), json!("{}"), json!("{}")]
        )
        .await
    );
    assert!(!cli(db, "sim_intent", vec![json!(run), json!(1), json!("{}")]).await);
    assert!(
        send(
            &internal,
            "internal-tree-fixture",
            Command::ReplaceTree {
                expected_revision: iv["policy_revision"].as_u64().unwrap(),
                reason: "explicit protocol parity fixture".into(),
                tree: Node::Action {
                    action: Action::go(5)
                }
            }
        )
        .await
        .ok
    );
    assert!(
        send(
            &internal,
            "internal-speech-fixture",
            Command::Speak {
                text: "Protocol parity fixture words".into(),
                expires_tick: 10
            }
        )
        .await
        .ok
    );
    mcp(&external_path, "setup", &out.join("mcp-setup.json")).await;
    // A real delayed local mock-provider exchange through the built-in harness, while authority keeps stepping.
    let v = internal.observe(0, 256).await.unwrap();
    let source = v["experiences"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["kind"] == "perception" && e["data"]["kind"] == "site")
        .unwrap()["source"]
        .as_u64()
        .unwrap();
    let proposal = json!({"reason":"explicit delayed local mock-provider fixture, not generated intelligence","operations":[{"op":"reflect","expected_revision":v["learning_revision"],"observed_cursor":v["latest_cursor"],"reflections":[{"source":source,"interpretation":"Explicit fixture interpretation","caution_delta":2,"trust_delta":0,"belief":null}],"goal":"Fixture evidence comparison"}]});
    let entered = Arc::new(tokio::sync::Notify::new());
    let release = Arc::new(tokio::sync::Notify::new());
    let en = entered.clone();
    let rel = release.clone();
    let body = proposal.to_string();
    let app=axum::Router::new().route("/api/chat",axum::routing::post(move|axum::Json(payload):axum::Json<Value>|{let en=en.clone();let rel=rel.clone();let body=body.clone();async move{
    let context:Value=serde_json::from_str(payload["messages"][1]["content"].as_str().unwrap()).unwrap();assert_eq!(context["actor"],1);assert!(context.get("sites").is_none());assert!(context.get("pending").is_none());en.notify_one();rel.notified().await;axum::Json(json!({"model":"local-mock-fixture","message":{"role":"assistant","content":body},"done":true,"done_reason":"stop"}))
 }}));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let mock = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    let service = internal.clone();
    let audit = out.join("reasoning");
    let config = Config::ollama("local-mock-fixture".into(), format!("http://{address}"), 1);
    let (_tx, rx) = tokio::sync::watch::channel(None);
    let task = tokio::spawn(async move {
        deliberate_once(&service, config, Responsibility::Learning, &audit, rx).await
    });
    entered.notified().await;
    for tick in 1..=3 {
        assert!(cli(db, "sim_step", vec![json!(run)]).await);
        wait(|| internal.current().is_ok_and(|v| v["tick"] == tick)).await;
    }
    let before = internal.observe(0, 256).await.unwrap();
    assert_eq!(before["context"]["player"]["position"], 3);
    let attempt = before["context"]["player"]["current_approach"]["active_attempt"].clone();
    release.notify_one();
    let result = task.await.unwrap().unwrap();
    assert_eq!(result["receipts"][0]["ok"], true);
    mock.abort();
    let after = internal.observe(0, 256).await.unwrap();
    assert_eq!(
        after["context"]["player"]["current_approach"]["active_attempt"],
        attempt
    );
    assert_eq!(after["policy_revision"], before["policy_revision"]);
    mcp(&external_path, "inspect", &out.join("mcp-after.json")).await;
    let external_after: Value =
        serde_json::from_slice(&std::fs::read(out.join("mcp-after.json")).unwrap()).unwrap();
    let ev = &external_after["snapshot"];
    for key in ["position", "motive"] {
        assert_eq!(
            after["context"]["player"][key],
            ev["context"]["player"][key]
        );
    }
    assert_eq!(
        after["context"]["player"]["personality"]["caution"],
        ev["context"]["player"]["personality"]["caution"]
    );
    assert!(after["experiences"]
        .as_array()
        .unwrap()
        .iter()
        .any(|e| e["kind"] == "perception" && e["data"]["kind"] == "speech"));
    // Cross-character source IDs cannot be laundered into learning.
    let wrong = ev["experiences"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["kind"] == "perception")
        .unwrap()["source"]
        .as_u64()
        .unwrap();
    assert!(
        !send(
            &internal,
            "foreign-evidence",
            Command::Reflect {
                expected_revision: after["learning_revision"].as_u64().unwrap(),
                observed_cursor: after["latest_cursor"].as_u64().unwrap(),
                reflections: vec![Reflection {
                    source: wrong,
                    interpretation: "must reject".into(),
                    caution_delta: 1,
                    trust_delta: 0,
                    belief: None
                }],
                goal: None
            }
        )
        .await
        .ok
    );
    assert!(cli(db, "sim_revoke_client", vec![json!(iid)]).await);
    wait(|| internal.connection.db.sim_participant_state().count() == 0).await;
    assert!(cli(db, "sim_revoke_client", vec![json!(eid)]).await);
    wait(|| external.connection.db.sim_participant_state().count() == 0).await;
    let report = json!({"run":run,"db":db,"evidence":"fixture/protocol integration, no fresh model intelligence","real_authority":true,"mcp_protocol":"2026-07-28","transport":"stdio","same_permissions_and_effects":true,"ownership_exclusive":true,"private_tables_denied":true,"participant_admin_denied":true,"operator_model_and_intent_backdoors_disabled":true,"cross_actor_evidence_rejected":true,"revocation_removes_view":true,"execution_ticks_during_deliberation":3,"attempt_preserved_across_learning":attempt,"internal_snapshot":after,"harness_result":result});
    std::fs::write(
        out.join("verification.json"),
        serde_json::to_vec_pretty(&report).unwrap(),
    )
    .unwrap();
    println!(
        "Participant authority/MCP/harness parity verified: {}",
        out.display()
    );
    for s in [internal, external, stranger] {
        let _ = s.connection.disconnect();
    }
}
