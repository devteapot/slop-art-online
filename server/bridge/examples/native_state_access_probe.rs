//! No-model authorization, reconnect, retention and expiry check on a fresh run.
use bridge::participant::{new_session, ParticipantService};
use serde::Deserialize;
use serde_json::{json, Value};
use shared::module_bindings::*;
use simulation::{
    participant::{Command, Request, API_VERSION},
    Action, Node, Skill,
};
use spacetimedb_sdk::{DbContext, Table};
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

macro_rules! verify {
    ($condition:expr) => {
        if !$condition {
            return Err(format!("access check failed at line {}", line!()));
        }
    };
}
macro_rules! verify_eq {
    ($left:expr,$right:expr) => {{
        let left = &$left;
        let right = &$right;
        verify!(left == right);
    }};
}
macro_rules! verify_ne {
    ($left:expr,$right:expr) => {{
        let left = &$left;
        let right = &$right;
        verify!(left != right);
    }};
}

#[derive(Deserialize)]
struct Config {
    server: String,
    database: String,
    run: String,
    output: PathBuf,
    credentials: PathBuf,
    cli: PathBuf,
    cli_config: PathBuf,
}
async fn cli(c: &Config, name: &str, args: Vec<Value>) -> Result<(), String> {
    let mut command = tokio::process::Command::new(&c.cli);
    command
        .kill_on_drop(true)
        .arg("--config-path")
        .arg(&c.cli_config)
        .args(["call", &c.database, name]);
    for arg in args {
        command.arg(arg.to_string());
    }
    let result = tokio::time::timeout(
        Duration::from_secs(20),
        command
            .args(["--server", &c.server, "--no-config", "-y"])
            .output(),
    )
    .await
    .map_err(|_| format!("{name}: timeout, outcome unknown"))?
    .map_err(|_| format!("{name}: CLI unavailable"))?;
    if result.status.success() {
        Ok(())
    } else {
        Err(format!("{name}: rejected; CLI output suppressed"))
    }
}
async fn wait(check: impl Fn() -> bool) -> Result<(), String> {
    let until = Instant::now() + Duration::from_secs(10);
    while !check() {
        if Instant::now() >= until {
            return Err("access-check subscription deadline".into());
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    Ok(())
}
fn empty(s: &ParticipantService) -> bool {
    s.connection
        .db
        .sim_my_participant_head()
        .iter()
        .next()
        .is_none()
        && s.connection
            .db
            .sim_my_participant_reads()
            .iter()
            .next()
            .is_none()
        && s.connection
            .db
            .sim_my_participant_receipts()
            .iter()
            .next()
            .is_none()
}
fn request(s: &ParticipantService, id: &str, command: Command) -> Request {
    Request {
        api_version: API_VERSION.into(),
        request_id: id.into(),
        control_epoch: s.current().unwrap()["control_epoch"].as_u64().unwrap(),
        command,
    }
}
async fn grant(
    c: &Config,
    identity: &str,
    run: &str,
    actor: u32,
    observer: bool,
) -> Result<(), String> {
    cli(
        c,
        "sim_grant_client",
        vec![json!(run), json!(identity), json!(observer), json!(actor)],
    )
    .await
}
async fn check(
    c: &Config,
    people: &mut Vec<ParticipantService>,
    identities: &mut Vec<String>,
    passed: &mut Vec<&str>,
) -> Result<(), String> {
    let mut scenario: Value =
        serde_json::from_str(include_str!("../../../scenarios/survival.json")).unwrap();
    scenario["max_ticks"] = json!(1000);
    for site in scenario["sites"].as_array_mut().unwrap() {
        site["hazard"] = json!(0);
    }
    for actor in scenario["players"].as_array_mut().unwrap() {
        actor["food"] = json!(100);
        actor["hunger"] = json!(0);
    }
    for run in [&c.run, &format!("{}-other", c.run)] {
        cli(
            c,
            "sim_create_participant",
            vec![json!(run), json!(scenario.to_string())],
        )
        .await?;
    }
    for name in ["first", "second", "observer"] {
        let (service, identity) = new_session(
            c.server.clone(),
            c.database.clone(),
            &c.credentials.join(format!("{name}.json")),
        )
        .await?;
        people.push(service);
        identities.push(identity);
    }
    let first = &people[0];
    let second = &people[1];
    let observer = &people[2];
    let applied = Arc::new(AtomicBool::new(false));
    let flag = applied.clone();
    let _legacy = first
        .connection
        .subscription_builder()
        .on_applied(move |_| {
            flag.store(true, Ordering::Release);
        })
        .subscribe([
            "SELECT * FROM sim_participant_state",
            "SELECT * FROM sim_run",
            "SELECT * FROM sim_my_snapshot",
        ]);
    wait(|| applied.load(Ordering::Acquire)).await?;
    verify!(empty(first));
    verify!(first.connection.db.sim_run().iter().next().is_none());
    verify!(first
        .connection
        .db
        .sim_my_snapshot()
        .iter()
        .next()
        .is_none());
    passed.push("ungranted views and owner export view are empty");
    for table in [
        "sim_native_actor",
        "sim_native_mind",
        "sim_native_mind_history",
        "sim_native_participant",
        "sim_native_experience",
        "sim_native_lease",
        "sim_native_capture",
        "sim_participant_receipt",
    ] {
        let denied = Arc::new(AtomicBool::new(false));
        let flag = denied.clone();
        let _denied = first
            .connection
            .subscription_builder()
            .on_error(move |_, _| {
                flag.store(true, Ordering::Release);
            })
            .subscribe([format!("SELECT * FROM {table}")]);
        wait(|| denied.load(Ordering::Acquire)).await?;
    }
    passed.push("private native tables reject participant subscriptions");
    grant(c, &identities[0], &c.run, 1, false).await?;
    grant(c, &identities[1], &c.run, 2, false).await?;
    grant(c, &identities[2], &c.run, 0, true).await?;
    wait(|| first.current().is_ok() && second.current().is_ok()).await?;
    let denied = Arc::new(AtomicBool::new(false));
    let flag = denied.clone();
    first
        .connection
        .reducers
        .sim_migrate_native_state_then(c.run.clone(), move |_, result| {
            flag.store(matches!(result, Ok(Err(_))), Ordering::Release);
        })
        .map_err(|_| "migration denial check not sent")?;
    wait(|| denied.load(Ordering::Acquire)).await?;
    let denied = Arc::new(AtomicBool::new(false));
    let flag = denied.clone();
    first
        .connection
        .reducers
        .sim_step_then(c.run.clone(), move |_, result| {
            flag.store(matches!(result, Ok(Err(_))), Ordering::Release);
        })
        .map_err(|_| "operator step denial check not sent")?;
    wait(|| denied.load(Ordering::Acquire)).await?;
    passed.push("participant identities cannot migrate storage or advance the operator clock");
    let observer_applied = Arc::new(AtomicBool::new(false));
    let flag = observer_applied.clone();
    let _observer = observer
        .connection
        .subscription_builder()
        .on_applied(move |_| {
            flag.store(true, Ordering::Release);
        })
        .subscribe([
            "SELECT * FROM sim_my_participant_head",
            "SELECT * FROM sim_my_participant_reads",
            "SELECT * FROM sim_my_participant_receipts",
        ]);
    wait(|| observer_applied.load(Ordering::Acquire)).await?;
    verify!(empty(observer));
    wait(|| {
        first
            .connection
            .db
            .sim_my_snapshot()
            .iter()
            .next()
            .is_some()
    })
    .await?;
    let snapshot: Value = serde_json::from_str(
        &first
            .connection
            .db
            .sim_my_snapshot()
            .iter()
            .next()
            .unwrap()
            .body,
    )
    .unwrap();
    verify_eq!(snapshot["actor"], 1);
    verify_eq!(snapshot["observer"], false);
    verify!(snapshot["pending"].is_null());
    for player in snapshot["players"].as_array().unwrap() {
        if player["id"] != 1 {
            verify!(player.get("knowledge").is_none() && player.get("health").is_none());
        }
    }
    for decision in [
        simulation::Decision {
            reason: "manual wait via client".into(),
            actions: vec![Action::new(Skill::Wait)],
            policy: None,
            reflections: vec![],
        },
        simulation::Decision {
            reason: "policy via client".into(),
            actions: vec![],
            policy: Some(Node::Action {
                action: Action::new(Skill::Wait),
            }),
            reflections: vec![],
        },
    ] {
        let done = Arc::new(AtomicBool::new(false));
        let flag = done.clone();
        first
            .connection
            .reducers
            .sim_client_intent_then(
                serde_json::to_string(&decision).unwrap(),
                move |_, result| {
                    flag.store(matches!(result, Ok(Ok(()))), Ordering::Release);
                },
            )
            .map_err(|_| "client intent check not sent")?;
        wait(|| done.load(Ordering::Acquire)).await?;
    }
    passed.push("Bevy snapshot preserves actor privacy and client manual/policy intents commit");
    let read = request(
        first,
        "retained-read",
        Command::ReadObservation {
            after: 0,
            limit: 16,
        },
    );
    let receipt = first.command(read.clone()).await?;
    verify!(receipt.ok);
    let original = first
        .connection
        .db
        .sim_my_participant_reads()
        .iter()
        .find(|r| r.request_id == read.request_id)
        .unwrap();
    verify_eq!(first.command(read.clone()).await?.event, receipt.event);
    verify_eq!(
        first
            .connection
            .db
            .sim_my_participant_reads()
            .iter()
            .count(),
        1
    );
    let second_read = second.observe(0, 16).await?;
    verify_eq!(second_read["actor"], 2);
    verify!(first
        .connection
        .db
        .sim_my_participant_reads()
        .iter()
        .all(|r| r.actor == 1 && r.run == c.run));
    verify!(second
        .connection
        .db
        .sim_my_participant_reads()
        .iter()
        .all(|r| r.actor == 2 && r.run == c.run));
    let legacy = first
        .connection
        .db
        .sim_participant_state()
        .iter()
        .next()
        .unwrap();
    verify_eq!(
        serde_json::from_str::<Value>(&legacy.body).unwrap(),
        first.current()?
    );
    passed.push("native and legacy status agree; actor and observer isolation; idempotent read");
    let before = first.current()?;
    first
        .connection
        .disconnect()
        .map_err(|_| "disconnect failed")?;
    wait(|| !first.connection.is_active()).await?;
    let replacement = ParticipantService::from_file(&c.credentials.join("first.json")).await?;
    wait(|| replacement.current().is_ok()).await?;
    verify_eq!(replacement.current()?, before);
    people[0] = replacement;
    passed.push("same identity reconnect recovers immutable reads and correlated receipts");
    let first = &people[0];
    for n in 0..65 {
        let rejected = request(
            first,
            &format!("rejected-{n}"),
            Command::ReadObservation {
                after: u64::MAX,
                limit: 1,
            },
        );
        verify!(!first.command(rejected).await?.ok);
    }
    let mut reused = read.clone();
    reused.command = Command::ReadObservation { after: 0, limit: 1 };
    verify!(first.command(reused).await?.ok);
    let repeated: Vec<_> = first
        .connection
        .db
        .sim_my_participant_reads()
        .iter()
        .filter(|r| r.request_id == read.request_id)
        .collect();
    verify_eq!(repeated.len(), 2);
    verify_ne!(repeated[0].lease_id, repeated[1].lease_id);
    verify_eq!(
        repeated
            .iter()
            .find(|r| r.lease_id == original.lease_id)
            .unwrap()
            .observation,
        original.observation
    );
    passed.push("request ID reuse creates a distinct lease without rewriting old evidence");
    // Eat on each coarse step so this finite expiry check is not cut short by
    // starvation. This is an explicit fixture policy, not model behavior.
    let revision = first.current()?["policy_revision"].as_u64().unwrap();
    let eat = request(
        first,
        "expiry-fixture-policy",
        Command::ReplaceTree {
            expected_revision: revision,
            reason: "Keep the explicit expiry fixture alive".into(),
            tree: Node::Action {
                action: Action::new(Skill::Eat),
            },
        },
    );
    verify!(first.command(eat).await?.ok);
    for _ in 0..132 {
        cli(c, "sim_step", vec![json!(c.run)]).await?;
    }
    verify_eq!(
        first
            .connection
            .db
            .sim_my_participant_reads()
            .iter()
            .count(),
        2
    );
    cli(c, "sim_step", vec![json!(c.run)]).await?;
    wait(|| {
        first
            .connection
            .db
            .sim_my_participant_reads()
            .iter()
            .next()
            .is_none()
    })
    .await?;
    passed.push("expired reads leave subscriptions at the existing simulation-time boundary");
    cli(c, "sim_revoke_client", vec![json!(identities[0])]).await?;
    wait(|| empty(first)).await?;
    grant(c, &identities[0], &c.run, 1, false).await?;
    wait(|| first.current().is_ok()).await?;
    verify!(first.current()?["control_epoch"].as_u64().unwrap() > read.control_epoch);
    let mut stale = read.clone();
    stale.request_id = "old-controller".into();
    let stale = first.command(stale).await?;
    verify!(!stale.ok);
    verify!(stale.error.unwrap().contains("stale control epoch"));
    verify!(first
        .connection
        .db
        .sim_my_participant_reads()
        .iter()
        .next()
        .is_none());
    passed
        .push("revocation removes all participant rows and stale controller commands are rejected");
    let other = format!("{}-other", c.run);
    grant(c, &identities[0], &other, 1, false).await?;
    wait(|| first.current().is_ok_and(|v| v["run"] == other)).await?;
    verify!(first
        .connection
        .db
        .sim_my_participant_reads()
        .iter()
        .all(|r| r.run == other));
    verify!(first
        .connection
        .db
        .sim_my_participant_receipts()
        .iter()
        .all(|r| r.run == other));
    verify_eq!(first.observe(0, 16).await?["run"], other);
    passed.push("cross-run reassignment replaces scope without leaking previous rows");
    Ok(())
}
#[tokio::main]
async fn main() -> Result<(), String> {
    let path = std::env::args().nth(1).ok_or("config path required")?;
    let c: Config = serde_json::from_slice(&std::fs::read(path).map_err(|_| "config missing")?)
        .map_err(|_| "invalid config")?;
    if c.server != "http://127.0.0.1:3103"
        || !c.database.starts_with("sim-authority36-")
        || !c.run.starts_with("sim-native-access-")
    {
        return Err("isolated native access fixture destination required".into());
    }
    std::fs::create_dir_all(&c.output).map_err(|_| "output directory unavailable")?;
    std::fs::create_dir_all(&c.credentials).map_err(|_| "credential directory unavailable")?;
    let mut people = vec![];
    let mut identities = vec![];
    let mut passed = vec![];
    let result = check(&c, &mut people, &mut identities, &mut passed).await;
    let mut cleanup_errors = vec![];
    for identity in &identities {
        if let Err(error) = cli(&c, "sim_revoke_client", vec![json!(identity)]).await {
            cleanup_errors.push(error);
        }
    }
    for service in &people {
        let _ = service.connection.disconnect();
    }
    if let Err(error) = wait(|| people.iter().all(|p| !p.connection.is_active())).await {
        cleanup_errors.push(error);
    }
    let report = json!({"passed":result.is_ok() && cleanup_errors.is_empty(),"checks":passed,
        "error":result.err(),"cleanup_errors":cleanup_errors,"model_calls":0,"clock_started":false});
    std::fs::write(
        c.output.join("result.json"),
        serde_json::to_vec_pretty(&report).unwrap(),
    )
    .map_err(|_| "report write failed")?;
    if report["passed"] == true {
        Ok(())
    } else {
        Err("access verification failed; see retained report".into())
    }
}
