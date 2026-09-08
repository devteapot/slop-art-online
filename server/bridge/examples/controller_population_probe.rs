//! Actual world + canonical controller workload. All actors retain their seed
//! policies and physical rules. No model inference or synthetic physical effects.
use bridge::{controller::Controller,participant::{new_session,ParticipantService}};
use serde_json::{json,Value};
use shared::module_bindings::SimMyControllerFrameTableAccess;
use spacetimedb_sdk::{DbContext,Table};
use std::{path::PathBuf,time::{Duration,Instant,SystemTime,UNIX_EPOCH},io::Write};
#[path="controller_population_probe/live_clients.rs"]
mod live_clients;
#[path="controller_population_probe/combat_feed.rs"]
mod combat_feed;
#[path="controller_population_probe/render_parts.rs"]
mod render_parts;
fn wall_ms()->u128 {SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis()}

async fn call(c:&Value,name:&str,args:Vec<Value>)->Result<(),String> {
    let mut cmd=tokio::process::Command::new(c["cli"].as_str().unwrap());
    cmd.kill_on_drop(true).arg("--config-path").arg(c["cli_config"].as_str().unwrap())
        .args(["call",c["database"].as_str().unwrap(),name]);
    for arg in args {cmd.arg(arg.to_string());}
    let out=tokio::time::timeout(Duration::from_secs(30),cmd.args(["--server",c["server"].as_str().unwrap(),"--no-config","-y"]).output())
        .await.map_err(|_|format!("{name} timeout; outcome unknown"))?.map_err(|e|e.to_string())?;
    if !out.status.success() {return Err(format!("owner {name} failed: {}",String::from_utf8_lossy(&out.stderr)));}
    Ok(())
}
async fn create(c:&Value,seed:&str)->Result<(),String> {
    let config:toml::Value=std::fs::read_to_string(c["cli_config"].as_str().unwrap()).map_err(|_|"owner config unavailable")?
        .parse().map_err(|_|"owner config invalid")?;
    let token=config["spacetimedb_token"].as_str().ok_or("owner token unavailable")?;
    let response=reqwest::Client::new().post(format!("{}/v1/database/{}/call/sim_create_client_world",
        c["server"].as_str().unwrap(),c["database"].as_str().unwrap())).bearer_auth(token)
        .json(&json!([c["run"],seed])).timeout(Duration::from_secs(60)).send().await.map_err(|_|"world creation transport error")?;
    if !response.status().is_success() {return Err(format!("world creation HTTP {}",response.status()));}
    Ok(())
}
async fn workload(c:&Value,people:&mut Vec<ParticipantService>)->Result<Value,String> {
    let dir=PathBuf::from(c["output_dir"].as_str().unwrap());
    let seed=std::fs::read_to_string(c["scenario"].as_str().unwrap()).map_err(|e|e.to_string())?;
    let scenario:simulation::Scenario=serde_json::from_str(&seed).map_err(|e|e.to_string())?;
    create(c,&seed).await?;
    call(c,"sim_setup_client_clock",vec![c["run"].clone(),json!("live_fixture")]).await?;
    call(c,"sim_operator_clock",vec![c["run"].clone(),json!(c["action_period_ms"].as_u64().unwrap_or(50)),json!(true)]).await?;
    call(c,"sim_configure_deadline_clock",vec![c["run"].clone(),json!(true)]).await?;
    if let Some(hz)=c["action_hz"].as_u64() {
        call(c,"sim_configure_clock_rate",vec![c["run"].clone(),json!(hz)]).await?;
    }
    call(c,"sim_configure_audit_archive",vec![c["run"].clone(),json!(true)]).await?;
    if c["physical_clock"].as_bool().unwrap_or(false) {call(c,"sim_configure_physical_clock",vec![c["run"].clone(),json!(true)]).await?;}
    let enrollment=Instant::now();
    for actor in &scenario.players {
        let path=PathBuf::from(c["credentials"].as_str().unwrap()).join(format!("actor-{}.json",actor.id));
        let endpoint=if c["human_actor"].as_u64()==Some(u64::from(actor.id)) {
            c["human_server"].as_str().unwrap_or(c["server"].as_str().unwrap())
        } else {c["server"].as_str().unwrap()};
        let (mut service,id)=new_session(endpoint.into(),c["database"].as_str().unwrap().into(),&path).await?;
        call(c,"sim_grant_client",vec![c["run"].clone(),json!(id),json!(false),json!(actor.id)]).await?;
        let until=Instant::now()+Duration::from_secs(10);
        while service.connection.db.sim_my_controller_frame().count()==0 {
            if Instant::now()>until {return Err("frame enrollment timeout".into());}
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        if c["human_actor"].as_u64()!=Some(u64::from(actor.id)) {
            let controller=Controller::provision(c["controller_server"].as_str().unwrap().into(),
                c["controller_database"].as_str().unwrap().into(),&path.with_extension("controller.json")).await?;
            service.attach_open_controller(controller).await?;
        }
        people.push(service);
        if people.len()%24==0 {println!("enrolled {} / {}",people.len(),scenario.players.len());}
    }
    let mut live=live_clients::LiveClients::setup(c,&scenario,people).await?;
    let enrollment_ms=enrollment.elapsed().as_millis();
    if let Some(gate)=c["start_gate"].as_str() {
        std::fs::write(dir.join("ready.json"),json!({"ready":true,"population":people.len(),"wall_ms":wall_ms()}).to_string()).map_err(|e|e.to_string())?;
        tokio::time::timeout(Duration::from_secs(180),async {
            let gate=PathBuf::from(gate);
            while !gate.exists() {
                if gate.with_extension("cancel").exists() {return Err("measurement cancelled before start: browser setup failed");}
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            Ok(())
        }).await.map_err(|_|"measurement start gate timeout")??;
    }
    let mut samples=std::fs::File::create(dir.join("controller-samples.jsonl")).map_err(|e|e.to_string())?;
    let start=Instant::now();
    let start_wall_ms=wall_ms();
    std::fs::write(dir.join("workload-window.json"),serde_json::to_vec_pretty(&json!({
        "population":people.len(),"seconds":c["seconds"],"enrollment_ms":enrollment_ms,
        "start_wall_ms":start_wall_ms,"pause_sent_wall_ms":null
    })).unwrap()).map_err(|e|e.to_string())?;
    live.begin();
    call(c,"sim_operator_clock",vec![c["run"].clone(),json!(c["action_period_ms"].as_u64().unwrap_or(50)),json!(false)]).await?;
    println!("measurement started: {} actors, {} human input client(s), {} observer(s)",
        people.len(), usize::from(c["human_actor"].is_u64()), usize::from(c["observer"] == true));
    let seconds=c["seconds"].as_u64().ok_or("seconds missing")?;
    let mut next_sample=Duration::from_secs(1);
    while start.elapsed()<Duration::from_secs(seconds) {
        tokio::time::sleep(Duration::from_millis(20)).await;
        live.poll(people)?;
        if start.elapsed()<next_sample {continue;}
        next_sample+=Duration::from_secs(1);
        let states:Vec<_>=people.iter().map(|p|match p.current(){Ok(v)=>v,Err(e)=>json!({"error":e})}).collect();
        writeln!(samples,"{}",json!({"elapsed_ms":start.elapsed().as_millis(),"states":states,"live_clients":live.sample()})).map_err(|e|e.to_string())?;
        samples.flush().map_err(|e|e.to_string())?;
    }
    let pause_sent_wall_ms=wall_ms();
    // Preserve measurement boundaries even when the pause acknowledgement times
    // out. A failed pause must not erase the active window or become a success.
    std::fs::write(dir.join("workload-window.json"),serde_json::to_vec_pretty(&json!({
        "population":people.len(),"seconds":seconds,"enrollment_ms":enrollment_ms,
        "start_wall_ms":start_wall_ms,"pause_sent_wall_ms":pause_sent_wall_ms
    })).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
    call(c,"sim_operator_clock",vec![c["run"].clone(),json!(c["action_period_ms"].as_u64().unwrap_or(50)),json!(true)]).await?;
    let live=live.finish();
    std::fs::write(dir.join("live-client-result.json"),serde_json::to_vec_pretty(&live).unwrap()).map_err(|e|e.to_string())?;
    if c["verify_combat_feed"]==true || c["verify_render_parts"]==true {
        for person in people.iter() {person.interrupt_controller_relay().await;}
    }
    if c["verify_combat_feed"]==true {
        combat_feed::verify(c,people,&scenario).await?;
    }
    if c["verify_render_parts"]==true {render_parts::verify(c,people,&scenario).await?;}
    let frames:Vec<_>=people.iter().map(|p|p.connection.db.sim_my_controller_frame().iter().next()
        .map(|f|json!({"actor":f.actor,"tick":f.tick,"health":f.health,"revision":f.revision,"action":f.action}))).collect();
    Ok(json!({"population":people.len(),"seconds":seconds,"enrollment_ms":enrollment_ms,"elapsed_ms":start.elapsed().as_millis(),
        "start_wall_ms":start_wall_ms,"pause_sent_wall_ms":pause_sent_wall_ms,"pause_received_wall_ms":wall_ms(),
        "frames":frames,"model_calls":0,"observer_connections":live["observer_connections"],"human_connections":live["human_connections"],
        "policy":"original scenario starting_behaviors, optional declared automated human inputs", "tick_interval_ms":c["action_period_ms"].as_u64().unwrap_or(50),"physical_clock":c["physical_clock"].as_bool().unwrap_or(false)}))
}
#[tokio::main]
async fn main()->Result<(),Box<dyn std::error::Error>> {
    let c:Value=serde_json::from_slice(&std::fs::read(std::env::args().nth(1).ok_or("config required")?)?)?;
    let mut people=vec![];
    let result=workload(&c,&mut people).await;
    if result.is_err() {
        let path=PathBuf::from(c["output_dir"].as_str().unwrap()).join("workload-window.json");
        if let Ok(bytes)=std::fs::read(&path) {
            let mut window:Value=serde_json::from_slice(&bytes)?;
            if window["pause_sent_wall_ms"].is_null() {window["pause_sent_wall_ms"]=json!(wall_ms());}
            window["workload_failed"]=json!(true);
            std::fs::write(path,serde_json::to_vec_pretty(&window)?)?;
        }
    }
    let cleanup=call(&c,"sim_operator_clock",vec![c["run"].clone(),json!(c["action_period_ms"].as_u64().unwrap_or(50)),json!(true)]).await;
    for p in people.drain(..) {let _=p.connection.disconnect();}
    let value=match &result {Ok(v)=>json!({"ok":true,"workload":v,"pause_error":cleanup.err()}),Err(e)=>json!({"ok":false,"error":e,"pause_error":cleanup.err()})};
    std::fs::write(PathBuf::from(c["output_dir"].as_str().unwrap()).join("result.json"),serde_json::to_vec_pretty(&value)?)?;
    result.map(|_|()).map_err(Into::into)
}
