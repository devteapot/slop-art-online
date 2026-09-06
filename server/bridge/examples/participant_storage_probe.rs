//! Companion for run_storage_regression.py. Real subscriptions and ParticipantService;
//! explicit tooling policies only, no model/backend, existing bridge dependencies only.
use bridge::participant::{new_session, ParticipantService, Session};
use serde::Deserialize;
use serde_json::{json, Value};
use shared::module_bindings::*;
use simulation::participant::{Command, Request, API_VERSION};
use spacetimedb_sdk::{DbContext, Table};
use std::{collections::VecDeque, path::{Path, PathBuf}, sync::{Arc, Mutex}, time::{Duration, Instant, SystemTime, UNIX_EPOCH}};
use tokio::task::JoinSet;

#[derive(Clone, Deserialize)]
struct Config {
    server: String, database: String, run: String, output: PathBuf,
    credential_dir: PathBuf, cli: PathBuf, cli_config: PathBuf,
    duration_seconds: u64, read_interval_ms: u64, private_tables: Vec<String>,
}
fn wall_ms() -> u128 { SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() }
fn write(path: &Path, value: &Value) -> Result<(), String> {
    let temporary=path.with_extension("tmp");
    std::fs::write(&temporary, serde_json::to_vec(value).unwrap()).map_err(|e|e.to_string())?;
    std::fs::rename(temporary,path).map_err(|e|e.to_string())
}
fn fingerprint(value: &Value) -> String {
    // Diagnostic checksum only; exact Value equality is used for all privacy/lease assertions.
    let mut h=0xcbf29ce484222325u64;
    for b in serde_json::to_vec(value).unwrap() { h=(h ^ u64::from(b)).wrapping_mul(0x100000001b3); }
    format!("fnv1a64:{h:016x}")
}
async fn cli(config: &Config, name: &str, values: Vec<Value>) -> Result<(), String> {
    let mut command=tokio::process::Command::new(&config.cli);
    command.arg("--config-path").arg(&config.cli_config).args(["call",&config.database,name]);
    for value in values {command.arg(value.to_string());}
    let output=command.args(["--server",&config.server,"--no-config","-y"]).output().await.map_err(|_|"operator CLI unavailable")?;
    if output.status.success() {Ok(())} else {Err(format!("operator {name} failed (output suppressed)"))}
}
async fn nonowner_has_no_full_world(config: &Config, session: &Path) -> Result<bool,String> {
    let session:Session=serde_json::from_slice(&std::fs::read(session).map_err(|_|"private session unavailable")?).map_err(|_|"invalid private session")?;
    let response=reqwest::Client::new().post(format!("{}/v1/database/{}/sql",config.server,config.database))
        .bearer_auth(session.token).header("Content-Type","text/plain").body("SELECT state FROM sim_run")
        .send().await.map_err(|_|"nonowner SQL transport failed")?;
    if !response.status().is_success() {return Err(format!("normalized owner view HTTP {}",response.status().as_u16()));}
    let rows:Value=response.json().await.map_err(|_|"invalid SQL response")?;
    Ok(rows[0]["rows"].as_array().is_some_and(Vec::is_empty))
}
async fn private_tables_denied(config: &Config, session: &Path) -> Result<Value,String> {
    let session:Session=serde_json::from_slice(&std::fs::read(session).map_err(|_|"private session unavailable")?).map_err(|_|"invalid private session")?;
    let mut results=Vec::new();
    for table in &config.private_tables {
        if !table.chars().all(|c|c.is_ascii_alphanumeric() || c=='_') {return Err("invalid private table name".into());}
        // Python first proves each table exists using the owner credential, so an
        // inaccessible-table response cannot accidentally validate a misspelled name.
        let response=reqwest::Client::new().post(format!("{}/v1/database/{}/sql",config.server,config.database))
            .bearer_auth(&session.token).header("Content-Type","text/plain").body(format!("SELECT * FROM {table}"))
            .send().await.map_err(|_|"private-table SQL transport failed")?;
        let denied=matches!(response.status().as_u16(),400|401|403);
        results.push(json!({"table":table,"denied":denied,"http_status":response.status().as_u16()}));
        if !denied {return Err(format!("nonowner query of private table {table} was not denied"));}
    }
    Ok(json!(results))
}
async fn snapshot(service:&ParticipantService) -> Result<Value,String> {
    let deadline=Instant::now()+Duration::from_secs(10);
    loop {
        if let Some(row)=service.connection.db.sim_my_snapshot().iter().next() {
            return serde_json::from_str(&row.body).map_err(|_|"invalid client projection".into());
        }
        if Instant::now()>=deadline {return Err("client subscription not ready".into());}
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
}
fn private_view_ok(view:&Value,actor:u32,run:&str) -> bool {
    view["run"]==run && view["actor"]==actor && view["observer"]==false && view["pending"].is_null()
        && view["players"].as_array().is_some_and(|players|players.iter().all(|p|p["id"]==actor ||
            ["knowledge","memories","beliefs","health","research","laws"].iter().all(|field|p.get(*field).is_none())))
        && view["sites"].as_array().is_some_and(|sites|sites.iter().all(|s|s.get("hazard").is_none()))
        && (1..=4).filter(|other|*other!=actor).all(|other|!view.to_string().contains(&format!("STORAGE_PRIVATE_ACTOR_{other}_")))
}
fn observer_ok(view:&Value,run:&str) -> bool {
    view["run"]==run && view["observer"]==true && view["actor"].is_null()
        && view["players"].as_array().is_some_and(|players|players.len()==4 && players.iter().all(|p|p["health"].is_number()))
        && view["sites"].as_array().is_some_and(|sites|sites.iter().any(|s|s.get("hazard").is_some()))
}
fn harmless_policy() -> Value {
    json!({"kind":"priority","children":[
        {"kind":"guard","condition":{"kind":"resource","resource":"hunger","comparison":"at_least","value":35},"child":{"kind":"action","action":{"skill":"eat","duration":1}}},
        {"kind":"guard","condition":{"kind":"resource","resource":"energy","comparison":"below","value":30},"child":{"kind":"action","action":{"skill":"rest","duration":1}}},
        {"kind":"guard","condition":{"kind":"resource","resource":"food","comparison":"below","value":4},"child":{"kind":"action","action":{"skill":"gather","duration":1}}},
        {"kind":"action","action":{"skill":"observe","duration":1}}
    ]})
}
struct Person {actor:u32,service:ParticipantService,path:PathBuf,private_denials:Value,updates:Arc<Mutex<Vec<(u128,u64,usize)>>>}
async fn capture_read(person:&Person,config:&Config,round:u64,previous_cursor:u64) -> (Value,Option<Value>) {
    let started=Instant::now();
    // Alternate newest and incremental pages. Never reconnect/open per read.
    let after=if round%4==0 {0} else {previous_cursor};
    match person.service.observe(after,128).await {
        Err(error)=>(json!({"actor":person.actor,"round":round,"ok":false,"read_ok":false,"error":error,"elapsed_ms":started.elapsed().as_millis()}),None),
        Ok(observed)=> {
            let status=person.service.current().unwrap_or(Value::Null);
            let retained=status["read_observations"].as_array().into_iter().flatten().find(|r|r["observation"]==observed).cloned();
            let request_id=retained.as_ref().map(|r|r["request_id"].clone()).unwrap_or(Value::Null);
            let receipt_ok=status["receipts"].as_array().into_iter().flatten().any(|r|r["request_id"]==request_id && r["ok"]==true);
            let entries=observed["experiences"].as_array().cloned().unwrap_or_default();
            let latest=observed["latest_cursor"].as_u64().unwrap_or(0);
            let order=entries.windows(2).all(|w|w[0]["cursor"].as_u64()<w[1]["cursor"].as_u64())
                && entries.iter().all(|e|e["cursor"].as_u64().is_some_and(|c|c>after && c<=latest));
            let next=entries.last().map(|e|e["cursor"].clone()).unwrap_or(json!(after));
            let lease_exact=observed["evidence_lease"]["atomic"]==true && observed["evidence_lease"]["observed_cursor"]==observed["latest_cursor"]
                && observed["evidence_lease"]["duration_ms"]==330000 && retained.is_some() && receipt_ok;
            let identity=observed["run"]==config.run && observed["actor"]==person.actor && observed["context"]["player"]["id"]==person.actor
                && status["actor"]==person.actor && status["control_epoch"]==observed["control_epoch"];
            let privacy=(1..=4).filter(|id|*id!=person.actor).all(|id|!observed.to_string().contains(&format!("STORAGE_PRIVATE_ACTOR_{id}_")));
            let status_fresh=status["latest_cursor"].as_u64().is_some_and(|cursor|cursor>=latest)
                && status["tick"].as_u64()>=observed["tick"].as_u64();
            let own_view= snapshot(&person.service).await.ok();
            let client_private=own_view.as_ref().is_some_and(|view|private_view_ok(view,person.actor,&config.run));
            let ok=identity && order && next==observed["next_cursor"] && lease_exact && privacy && status_fresh && client_private;
            let report=json!({"actor":person.actor,"round":round,"ok":ok,"read_ok":true,"request_id":request_id,
                "wall_ms":wall_ms(),"elapsed_ms":started.elapsed().as_millis(),"after":after,"identity_matches":identity,
                "cursor_ordered":order,"next_cursor_exact":next==observed["next_cursor"],"lease_exact":lease_exact,
                "private_context":privacy,"private_client_view":client_private,"status_fresh":status_fresh,
                "control_epoch":observed["control_epoch"],"latest_cursor":latest,"next_cursor":observed["next_cursor"],
                "oldest_cursor":observed["oldest_cursor"],"gap":observed["gap"],"time_ms":observed["time_ms"],"updates":observed["updates"],
                "experience_count":entries.len(),"observation_bytes":observed.to_string().len(),"observation_checksum":fingerprint(&observed)});
            (report,retained)
        }
    }
}
#[tokio::main]
async fn main() -> Result<(),Box<dyn std::error::Error>> {
    let config:Config=serde_json::from_slice(&std::fs::read(std::env::args().nth(1).ok_or("config JSON required")?)?)?;
    if !(60..=90).contains(&config.duration_seconds) || config.read_interval_ms<500 {return Err("bounded 60..90 second probe with >=500ms read interval required".into());}
    let mut identities=Vec::new();let mut people=Vec::new();let mut observer=None;
    let result:Result<Value,String>=async {
        for actor in 1..=4 {
            let path=config.credential_dir.join(format!("{}-actor-{actor}.json",config.run));
            let (service,identity)=new_session(config.server.clone(),config.database.clone(),&path).await?;
            identities.push(identity.clone());
            cli(&config,"sim_grant_client",vec![json!(config.run),json!(identity),json!(false),json!(actor)]).await?;
            service.connection.subscription_builder().subscribe(["SELECT * FROM sim_my_snapshot"]);
            let observations=Arc::new(Mutex::new(Vec::new()));let updates=observations.clone();
            service.connection.db.sim_my_snapshot().on_insert(move |_,row| {
                updates.lock().unwrap().push((wall_ms(),row.tick,row.body.len()));
            });
            let current=service.observe(0,128).await?;
            let receipt=service.command(Request {api_version:API_VERSION.into(),request_id:format!("storage-policy-{actor}"),
                control_epoch:current["control_epoch"].as_u64().ok_or("control epoch missing")?,command:Command::ReplaceTree {
                    expected_revision:current["policy_revision"].as_u64().ok_or("policy revision missing")?,
                    reason:"Explicit no-inference storage regression: observe and maintain ordinary food/energy".into(),tree:serde_json::from_value(harmless_policy()).map_err(|e|e.to_string())?
                }}).await?;
            if !receipt.ok {return Err("harmless policy rejected".into());}
            if !nonowner_has_no_full_world(&config,&path).await? {return Err("participant can read full owner world".into());}
            let private_denials=private_tables_denied(&config,&path).await?;
            people.push(Person {actor,service,path,private_denials,updates:observations});
        }
        let observer_path=config.credential_dir.join(format!("{}-observer.json",config.run));
        let (service,identity)=new_session(config.server.clone(),config.database.clone(),&observer_path).await?;
        identities.push(identity.clone());
        cli(&config,"sim_grant_client",vec![json!(config.run),json!(identity),json!(true),json!(0)]).await?;
        service.connection.subscription_builder().subscribe(["SELECT * FROM sim_my_snapshot"]);
        let observer_updates=Arc::new(Mutex::new(Vec::new()));let updates=observer_updates.clone();
        service.connection.db.sim_my_snapshot().on_insert(move |_,row|updates.lock().unwrap().push((wall_ms(),row.tick,row.body.len())));
        if !observer_ok(&snapshot(&service).await?,&config.run) {return Err("observer projection missing full local fixture".into());}
        if !nonowner_has_no_full_world(&config,&observer_path).await? {return Err("observer can read raw owner world".into());}
        let observer_private_denials=private_tables_denied(&config,&observer_path).await?;
        observer=Some(service);
        write(&config.output.join("ready.json"),&json!({"run":config.run,"participants":4,"observer":true,"model_calls":0,"identities":identities,"subscriptions_active":true}))?;
        let gate_deadline=Instant::now()+Duration::from_secs(120);
        while !config.output.join("go.json").exists() {
            if config.output.join("stop.json").exists() || Instant::now()>gate_deadline {return Err("measurement start cancelled/timed out".into());}
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        let started=Instant::now();let mut round=0;let mut reports=Vec::new();let mut recent:Vec<VecDeque<Value>>=(0..4).map(|_|VecDeque::new()).collect();let mut cursors=[0;4];
        while started.elapsed()<Duration::from_secs(config.duration_seconds) && !config.output.join("stop.json").exists() {
            let round_start=Instant::now();let mut reads=JoinSet::new();
            for (i,p) in people.iter().enumerate() {
                let p=Person {actor:p.actor,service:p.service.clone(),path:p.path.clone(),private_denials:p.private_denials.clone(),updates:p.updates.clone()};let cfg=config.clone();let after=cursors[i];
                reads.spawn(async move {(i,capture_read(&p,&cfg,round,after).await)});
            }
            while let Some(joined)=reads.join_next().await {
                let (i,(report,retained))=joined.map_err(|_|"read task failed")?;
                if let Some(cursor)=report["next_cursor"].as_u64() {cursors[i]=cursor;}
                if let Some(retained)=retained {recent[i].push_back(retained);if recent[i].len()>4 {recent[i].pop_front();}}
                reports.push(report);
            }
            if !observer_ok(&snapshot(observer.as_ref().unwrap()).await?,&config.run) {return Err("observer projection regressed during clock".into());}
            write(&config.output.join("read-progress.json"),&json!({"round":round,"reads":reports.len(),"failures":reports.iter().filter(|r|r["ok"]!=true).count(),"elapsed_ms":started.elapsed().as_millis()}))?;
            round+=1;
            if let Some(delay)=Duration::from_millis(config.read_interval_ms).checked_sub(round_start.elapsed()) {tokio::time::sleep(delay).await;}
        }
        write(&config.output.join("reads-done.json"),&json!({"wall_ms":wall_ms(),"reads":reports.len(),"rounds":round}))?;
        // Keep every view subscribed while Python pauses and captures the full authority.
        let deadline=Instant::now()+Duration::from_secs(90);
        while !config.output.join("paused.json").exists() {
            if Instant::now()>deadline {return Err("paused final-capture handshake timed out".into());}
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        let captured:Value=serde_json::from_slice(&std::fs::read(config.output.join("snapshot.json")).map_err(|_|"final paused snapshot missing")?).map_err(|_|"invalid snapshot")?;
        let kernel:simulation::World=serde_json::from_value(captured["world"].clone()).map_err(|e|format!("kernel World deserialization failed: {e}"))?;
        let kernel_world_roundtrip_exact=serde_json::to_value(&kernel).map_err(|e|e.to_string())?==captured["world"];
        let mut kernel_status_exact=true;
        let mut final_people=Vec::new();
        for (i,p) in people.iter().enumerate() {
            let expected:Value=serde_json::from_str(&kernel.participant_status_json(p.actor)?).map_err(|e|e.to_string())?;
            let deadline=Instant::now()+Duration::from_secs(10);
            let (status,view)=loop {
                let status=p.service.current()?;let view=snapshot(&p.service).await?;
                if status==expected && view["time_ms"]==kernel.timing.time_ms {break (status,view);}
                if Instant::now()>deadline {break (status,view);}
                tokio::time::sleep(Duration::from_millis(20)).await;
            };
            kernel_status_exact &= status==expected;
            let retained_exact=recent[i].iter().all(|read|status["read_observations"].as_array().into_iter().flatten().any(|r|r==read));
            let changes=p.updates.lock().unwrap().clone();
            final_people.push(json!({"actor":p.actor,"status":status,"client_view":view,"last_reads":recent[i],"retained_exact":retained_exact,
                "subscription_updates":changes,"private_table_denials":p.private_denials,"kernel_status_exact":status==expected,"raw_owner_view_empty":nonowner_has_no_full_world(&config,&p.path).await?}));
        }
        let full=snapshot(observer.as_ref().unwrap()).await?;
        let observed_final_time_exact=full["time_ms"]==kernel.timing.time_ms;
        let all_pass=kernel_world_roundtrip_exact && kernel_status_exact && observed_final_time_exact && reports.len()>=4*30 && reports.iter().all(|r|r["ok"]==true)
            && final_people.iter().all(|r|r["retained_exact"]==true && r["raw_owner_view_empty"]==true)
            && observer_ok(&full,&config.run);
        Ok(json!({"all_pass":all_pass,"run":config.run,"started_wall_ms":serde_json::from_slice::<Value>(&std::fs::read(config.output.join("go.json")).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?["wall_ms"],
            "elapsed_ms":started.elapsed().as_millis(),"rounds":round,"reads":reports,"final_participants":final_people,
            "kernel_world_roundtrip_exact":kernel_world_roundtrip_exact,"kernel_status_exact":kernel_status_exact,"observer_final_time_exact":observed_final_time_exact,
            "observer":full,"observer_private_table_denials":observer_private_denials,"observer_subscription_updates":observer_updates.lock().unwrap().clone(),
            "connection_reuse":"one ParticipantService per identity for the whole run; clones share its same Arc<DbConnection>","model_calls":0}))
    }.await;
    let report=match result {Ok(report)=>report,Err(error)=>json!({"all_pass":false,"error":error,"run":config.run})};
    write(&config.output.join("participant-storage-result.json"),&report)?;
    for person in &people {let _=person.service.connection.disconnect();}
    if let Some(observer)=observer {let _=observer.connection.disconnect();}
    // Python owns pausing/capture/revocation, including failure cleanup. Only public identities are emitted.
    write(&config.output.join("identities.json"),&json!(identities))?;
    if report["all_pass"]!=true {return Err("participant storage regression failed; see result".into());}
    Ok(())
}
