//! Additive no-model load diagnostic; never part of an autonomous controller.
use bridge::participant::{new_session, ParticipantService};
use serde::Deserialize;
use serde_json::{json, Value};
use shared::module_bindings::{Reducer, SimMyParticipantHeadTableAccess, SimMyParticipantReceiptsTableAccess, SimMyParticipantReadsTableAccess};
use simulation::participant::{Command, Request, API_VERSION};
use spacetimedb_sdk::{DbContext, Event, Table};
use std::{
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

const PREFIX: &str = "sim-authority36-";
const SAMPLE_CAP: usize = 100_000;
#[derive(Deserialize)]
struct Config {
    server: String,
    database: String,
    run: String,
    case: String,
    output: PathBuf,
    credential_dir: PathBuf,
    cli: PathBuf,
    cli_config: PathBuf,
    actors: Vec<u32>,
    #[serde(default = "default_window")]
    window_seconds: u64,
    #[serde(default = "default_rounds")]
    read_round_seconds: Vec<u64>,
    #[serde(default = "default_setup")]
    setup_seconds: u64,
}
fn default_window() -> u64 {60}
fn default_rounds() -> Vec<u64> {vec![5,20,35,50]}
fn default_setup() -> u64 {120}
struct Person {
    actor: u32,
    epoch: u64,
    service: ParticipantService,
}
fn wall_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis()
}
fn write(path: &Path, value: &Value) -> Result<(), String> {
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, serde_json::to_vec(value).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    std::fs::rename(tmp, path).map_err(|e| e.to_string())
}
async fn cli(c: &Config, name: &str, values: Vec<Value>) -> Result<(), String> {
    let mut command = tokio::process::Command::new(&c.cli);
    command
        .kill_on_drop(true)
        .arg("--config-path")
        .arg(&c.cli_config)
        .args(["call", &c.database, name]);
    for value in values {
        command.arg(value.to_string());
    }
    let output = tokio::time::timeout(
        Duration::from_secs(30),
        command
            .args(["--server", &c.server, "--no-config", "-y"])
            .output(),
    )
    .await
    .map_err(|_| format!("{name}: owner CLI 30s timeout; outcome unknown"))?
    .map_err(|_| format!("{name}: owner CLI unavailable"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!("{name}: owner CLI failed; output suppressed"))
    }
}
async fn disconnect(people: &[Person]) -> Result<(), String> {
    for p in people {
        let _ = p.service.connection.disconnect();
    }
    let deadline = Instant::now() + Duration::from_secs(5);
    while people.iter().any(|p| p.service.connection.is_active()) {
        if Instant::now() >= deadline {
            return Err("participant disconnect 5s deadline".into());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    Ok(())
}
async fn read(
    service: ParticipantService,
    actor: u32,
    epoch: u64,
    request_id: String,
    round: usize,
    start: Instant,
) -> Value {
    let sent = Instant::now();
    let sent_wall = wall_ms();
    let result = tokio::time::timeout(
        Duration::from_secs(10),
        service.command(Request {
            api_version: API_VERSION.into(),
            request_id: request_id.clone(),
            control_epoch: epoch,
            command: Command::ReadObservation {
                after: 0,
                limit: 128,
            },
        }),
    )
    .await;
    let mut report = json!({"actor":actor,"round":round,"request_id":request_id,"sent_wall_ms":sent_wall,
        "sent_elapsed_ms":sent.duration_since(start).as_millis(),"finished_elapsed_ms":start.elapsed().as_millis(),
        "elapsed_ms":sent.elapsed().as_millis(),"client_outcome":"unknown"});
    match result {
        Ok(Ok(receipt)) => {
            report["client_outcome"] = json!(if receipt.ok {
                "receipt_ok"
            } else {
                "receipt_rejected"
            });
            report["receipt"] = json!(receipt);
            if let Ok(status) = service.current() {
                report["status_json_bytes"] = json!(serde_json::to_vec(&status).unwrap().len());
                if let Some(read) = status["read_observations"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .find(|r| r["request_id"] == request_id)
                {
                    let observation = &read["observation"];
                    report["observation_json_bytes"] =
                        json!(serde_json::to_vec(observation).unwrap().len());
                    report["observation_actor"] = observation["actor"].clone();
                    report["observation_time_ms"] = observation["time_ms"].clone();
                    report["own_observation_verified"] = json!(observation["actor"] == actor);
                }
            }
        }
        Ok(Err(error)) => {
            report["error"] = json!(error);
        }
        Err(_) => {
            report["error"] = json!("10s local read deadline; authority outcome unknown; no retry");
        }
    }
    report
}
async fn run(c: Config) -> Result<(), String> {
    if !["http://127.0.0.1:3102", "http://127.0.0.1:3103"].contains(&c.server.as_str())
        || !c.database.starts_with(PREFIX)
        || !c.run.starts_with(PREFIX)
        || !["clock", "status", "reads"].contains(&c.case.as_str())
        || ![36,72,144].contains(&c.actors.len())
        || (c.actors.len()!=36 && c.server!="http://127.0.0.1:3103")
        || !(60..=300).contains(&c.window_seconds)
        || !(120..=240).contains(&c.setup_seconds)
        || c.read_round_seconds.is_empty()
        || c.read_round_seconds.len()>20
        || c.read_round_seconds.windows(2).any(|w|w[0]>=w[1])
        || c.read_round_seconds.iter().any(|s|*s==0 || *s+10>c.window_seconds)
        || c.actors
            .iter()
            .copied()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != c.actors.len()
    {
        return Err(
            "isolated localhost service / fresh authority probe / bounded actors and duration required".into(),
        );
    }
    let origin = Instant::now();
    let samples = Arc::new(Mutex::new(Vec::<Value>::new()));
    let dropped = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut people = Vec::new();
    let mut identities = Vec::new();
    let mut initial = Vec::new();
    let setup:Result<(),String>=tokio::time::timeout(Duration::from_secs(c.setup_seconds),async {
        for &actor in &c.actors {
            let (service,identity)=new_session(c.server.clone(),c.database.clone(),&c.credential_dir.join(format!("actor-{actor}.json"))).await?;
            identities.push(identity.clone()); write(&c.output.join("identities.json"),&json!(identities))?;
            macro_rules! track {
                ($table:ident, $kind:literal, $row:ident, $tick:expr) => {{
                    let copy=samples.clone(); let overflow=dropped.clone(); let expected_run=c.run.clone();
                    service.connection.db.$table().on_insert(move |ctx,$row| {
                        let mut sample=json!({"actor":actor,"elapsed_from_process_ms":origin.elapsed().as_millis(),
                            "wall_ms":wall_ms(),"tick":$tick,
                            "body_bytes":spacetimedb_sdk::__codegen::__sats::bsatn::to_vec($row).unwrap().len(),
                            "row_encoding":"bsatn","table":$kind,"own_run":$row.run==expected_run});
                        match &ctx.event {
                            Event::Reducer(e) => {
                                sample["event_kind"]=json!("own_reducer");
                                sample["reducer_timestamp_us"]=json!(e.timestamp.to_micros_since_unix_epoch());
                                sample["reducer_status"]=json!(format!("{:?}",e.status));
                                if let Reducer::SimParticipantCommand{request}=&e.reducer {
                                    if let Ok(request)=serde_json::from_str::<Value>(request) { sample["request_id"]=request["request_id"].clone(); }
                                }
                            }
                            Event::Transaction => {sample["event_kind"]=json!("transaction");}
                            Event::SubscribeApplied => {sample["event_kind"]=json!("subscribe_applied");}
                            _ => {sample["event_kind"]=json!("other");}
                        }
                        let mut entries=copy.lock().unwrap();
                        if entries.len()<SAMPLE_CAP {entries.push(sample);} else {overflow.fetch_add(1,std::sync::atomic::Ordering::Relaxed);}
                    });
                }};
            }
            track!(sim_my_participant_head, "head", row, Some(row.tick));
            track!(sim_my_participant_receipts, "receipt", row, None::<u64>);
            track!(sim_my_participant_reads, "read", row, None::<u64>);
            people.push(Person{actor,epoch:0,service});
            cli(&c,"sim_grant_client",vec![json!(c.run),json!(identity),json!(false),json!(actor)]).await?;
            let p=people.last_mut().unwrap(); let deadline=Instant::now()+Duration::from_secs(5);
            let status=loop {
                if let Ok(status)=p.service.current() { break status; }
                if Instant::now()>=deadline {return Err("5s initial own status deadline".into());}
                tokio::time::sleep(Duration::from_millis(20)).await;
            };
            if status["actor"]!=actor || status["run"]!=c.run || status["context"]["player"]["health"].as_i64().unwrap_or(0)<=0
                || status["read_observations"].as_array().map_or(true,|r|!r.is_empty()) {
                return Err("initial own status validation failed".into());
            }
            p.epoch=status["control_epoch"].as_u64().ok_or("missing epoch")?;
            initial.push(json!({"actor":actor,"epoch":p.epoch,"tick":status["tick"],"status_json_bytes":serde_json::to_vec(&status).unwrap().len()}));
        }
        Ok(())
    }).await.unwrap_or_else(|_|Err(format!("{}s setup ceiling reached",c.setup_seconds)));
    write(&c.output.join("initial-status.json"), &json!(initial))?;
    let mut report = json!({"case":c.case,"run":c.run,"setup_ok":setup.is_ok(),"setup_elapsed_ms":origin.elapsed().as_millis(),
        "fixed_window_seconds":c.window_seconds,"round_seconds":if c.case=="reads" {c.read_round_seconds.clone()} else {vec![]},
        "host_execution_duration_available":false,"energy_available":false,"pause_acknowledged":false});
    let operation:Result<(),String>=async {
        setup?;
        if c.case=="clock" {disconnect(&people).await?;}
        report["connections_at_resume"]=json!(people.iter().filter(|p|p.service.connection.is_active()).count());
        report["resume_sent_wall_ms"]=json!(wall_ms()); let resume=Instant::now();
        cli(&c,"sim_operator_clock",vec![json!(c.run),json!(50),json!(false)]).await?;
        let start=Instant::now(); let deadline=start+Duration::from_secs(c.window_seconds);
        report["resume_latency_ms"]=json!(resume.elapsed().as_millis());
        report["window_start_wall_ms"]=json!(wall_ms());
        report["window_start_process_ms"]=json!(start.duration_since(origin).as_millis());
        write(&c.output.join("runtime-progress.json"),&report)?;
        let mut tasks=tokio::task::JoinSet::new(); let mut reads=Vec::new(); let mut dispatched=Vec::new();
        let rounds=&c.read_round_seconds; let mut next=if c.case=="reads" {0} else {rounds.len()};
        loop {
            let round_at=if next<rounds.len() {start+Duration::from_secs(rounds[next])} else {deadline+Duration::from_secs(1)};
            tokio::select! { biased;
                _=tokio::time::sleep_until(deadline.into()) => {break;}
                _=tokio::time::sleep_until(round_at.into()), if next<rounds.len() => {
                    for p in &people {
                        let id=format!("{}-r{}-a{}",c.run,next+1,p.actor);
                        dispatched.push(json!({"actor":p.actor,"round":next+1,"request_id":id,"scheduled_seconds":rounds[next]}));
                        tasks.spawn(read(p.service.clone(),p.actor,p.epoch,id,next+1,start));
                    }
                    next+=1;
                }
                result=tasks.join_next(), if !tasks.is_empty() => {
                    match result {Some(Ok(value))=>reads.push(value),Some(Err(e))=>reads.push(json!({"task_error":e.to_string()})),None=>{}}
                }
            }
        }
        // Pause is issued at the independent wall deadline, before waiting on reads.
        let pause_sent=Instant::now(); report["pause_sent_wall_ms"]=json!(wall_ms());
        report["pause_sent_elapsed_ms"]=json!(pause_sent.duration_since(start).as_millis());
        report["reads_inflight_at_deadline"]=json!(tasks.len());
        let pause=cli(&c,"sim_operator_pause",vec![json!(c.run)]).await;
        report["pause_latency_ms"]=json!(pause_sent.elapsed().as_millis());
        report["pause_acknowledged"]=json!(pause.is_ok());
        report["pause_finished_wall_ms"]=json!(wall_ms());
        while let Some(result)=tasks.try_join_next() {match result {Ok(v)=>reads.push(v),Err(e)=>reads.push(json!({"task_error":e.to_string()}))}}
        let unknown:Vec<Value>=dispatched.iter().filter(|d|!reads.iter().any(|r|r["request_id"]==d["request_id"])).cloned().collect();
        tasks.abort_all();
        report["connections_after_pause"]=json!(people.iter().filter(|p|p.service.connection.is_active()).count());
        write(&c.output.join("read-results.json"),&json!({"dispatched":dispatched,"results":reads,"unresolved_client_results":unknown}))?;
        pause
    }.await;
    if let Err(error) = operation {
        report["error"] = json!(error);
    }
    let disconnected = disconnect(&people).await;
    report["disconnect_ok"] = json!(disconnected.is_ok());
    report["samples_dropped"] = json!(dropped.load(std::sync::atomic::Ordering::Relaxed));
    report["process_elapsed_ms"] = json!(origin.elapsed().as_millis());
    write(
        &c.output.join("status-samples.json"),
        &json!(*samples.lock().unwrap()),
    )?;
    write(&c.output.join("helper-result.json"), &report)?;
    if report.get("error").is_some() || disconnected.is_err() {
        Err("case recorded failure; consult local artifacts".into())
    } else {
        Ok(())
    }
}
#[tokio::main]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) == Some("--check-fixture") {
        let scenario: simulation::Scenario =
            serde_json::from_slice(&std::fs::read(&args[2]).unwrap()).unwrap();
        let mut world = simulation::World::new("offline-authority36".into(), scenario).unwrap();
        world.enable_participants();
        assert!([36,72,144].contains(&world.players.len()));
        println!(
            "{}",
            json!({"offline_fixture_valid":true,"actors":world.players.len(),"authority_connections":0})
        );
        return;
    }
    let config: Config = serde_json::from_slice(
        &std::fs::read(args.get(1).expect("config path")).expect("read config"),
    )
    .expect("config JSON");
    if let Err(error) = run(config).await {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
