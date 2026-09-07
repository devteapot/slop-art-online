//! Kill real relay processes at durable boundaries, then resume their identities.
//! All effects come from the two actual database modules, never a local simulator.
use bridge::{controller::Controller,participant::{new_session,ParticipantService,Session}};
use serde_json::{json,Value};
use shared::{controller_bindings::{brain_ack,brain_claim,MyBrainOutboxTableAccess},
    module_bindings::{SimMyControllerFrameTableAccess,SimMyControllerDispatchTableAccess,SimMyParticipantReceiptsTableAccess}};
use simulation::{participant::{Command,Request,API_VERSION},policy::Node,Action,Skill};
use spacetimedb_sdk::{DbContext,Table};
use std::{path::{Path,PathBuf},time::Duration};

async fn control(c:&Value,verb:&str,args:Vec<String>)->Result<String,String> {
    let out=tokio::time::timeout(Duration::from_secs(30),tokio::process::Command::new(c["cli"].as_str().unwrap())
        .args(["--config-path",c["cli_config"].as_str().unwrap(),verb,c["database"].as_str().unwrap()])
        .args(args).args(["--server",c.get("owner_server").unwrap_or(&c["server"]).as_str().unwrap(),"--no-config"])
        .output()).await.map_err(|_|"owner command timed out")?.map_err(|e|e.to_string())?;
    if !out.status.success() {return Err(format!("owner command failed: {}",String::from_utf8_lossy(&out.stderr)));}
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}
async fn call(c:&Value,name:&str,args:Vec<Value>)->Result<(),String> {
    let mut values=vec![name.into()];values.extend(args.into_iter().map(|v|v.to_string()));values.push("-y".into());
    control(c,"call",values).await.map(|_|())
}
fn write(path:&Path,v:&Value)->Result<(),String> {
    let tmp=path.with_extension("tmp");std::fs::write(&tmp,serde_json::to_vec_pretty(v).unwrap()).map_err(|e|e.to_string())?;
    std::fs::rename(tmp,path).map_err(|e|e.to_string())
}
async fn wait_for(mut condition:impl FnMut()->bool)->Result<(),String> {
    tokio::time::timeout(Duration::from_secs(10),async {while !condition() {tokio::time::sleep(Duration::from_millis(10)).await;}})
        .await.map_err(|_|"probe condition timed out".into())
}
fn check(condition:bool,message:&str)->Result<(),String> {if condition {Ok(())} else {Err(message.into())}}

async fn child(c:&Value,phase:&str,dir:&Path)->Result<(),String> {
    let path=dir.join("actor.json");
    let (service,id)=new_session(c["server"].as_str().unwrap().into(),c["database"].as_str().unwrap().into(),&path).await?;
    call(c,"sim_grant_client",vec![c["run"].clone(),json!(id),json!(false),json!(1)]).await?;
    wait_for(||service.connection.db.sim_my_controller_frame().count()==1).await?;
    let brain=Controller::provision(c["controller_server"].as_str().unwrap().into(),
        c["controller_database"].as_str().unwrap().into(),&path.with_extension("controller.json")).await?;
    brain.synchronize_inputs(&service).await?;
    let h=brain.current()?;
    check(brain.command(&Request {api_version:API_VERSION.into(),request_id:"recovery-policy".into(),
        control_epoch:h["control_epoch"].as_u64().unwrap(),command:Command::ReplaceTree {
            expected_revision:h["policy_revision"].as_u64().unwrap(),reason:"real process-kill recovery test".into(),
            tree:Node::Once {child:Box::new(Node::Action {action:Action::new(Skill::Wait)})}}}).await?.ok,"policy rejected")?;
    call(c,"sim_operator_clock",vec![c["run"].clone(),json!(50),json!(false)]).await?;
    // Synchronize actual unpaused authority inputs, but deliberately do not run
    // the relay dispatch loop: the child will be killed at the selected boundary.
    let until=std::time::Instant::now()+Duration::from_secs(10);
    let out=loop {
        brain.synchronize_inputs(&service).await?;
        if let Some(out)=brain.connection.db.my_brain_outbox().iter().next() {break out;}
        if std::time::Instant::now()>until {return Err("outbox did not appear".into());}
        tokio::time::sleep(Duration::from_millis(25)).await;
    };
    let request:Request=serde_json::from_str(&out.request).map_err(|e|e.to_string())?;
    let mut receipt=None;
    if phase=="claimed" {
        brain.connection.reducers.brain_claim(out.request_id.clone()).map_err(|e|e.to_string())?;
        wait_for(||brain.connection.db.my_brain_outbox().iter().next().is_some_and(|o|o.claimed)).await?;
    }
    if matches!(phase,"committed"|"acked") {
        let r=service.dispatch_action(out.sequence,request.clone()).await?;check(r.ok,"action not accepted")?;
        if phase=="acked" {
            brain.connection.reducers.brain_ack(serde_json::to_string(&r).unwrap()).map_err(|e|e.to_string())?;
            wait_for(||brain.connection.db.my_brain_outbox().count()==0).await?;
        }
        receipt=Some(r);
    }
    let mut timeout_observed=false;
    if phase=="timeout" {
        std::fs::write(c["proxy_hold"].as_str().ok_or("proxy_hold required")?, b"hold").map_err(|e|e.to_string())?;
        let error=service.dispatch_action(out.sequence,request.clone()).await.expect_err("held response unexpectedly arrived");
        check(error.contains("timeout"),&format!("expected timeout, got {error}"))?;
        check(service.connection.is_active(),"timeout closed the transport")?;
        timeout_observed=true;
    }
    write(&dir.join("ready.json"),&json!({"phase":phase,"sequence":out.sequence,"request":request,"receipt":receipt,"identity":id,"timeout_observed":timeout_observed}))?;
    std::future::pending::<()>().await;
    Ok(())
}

async fn resumed(c:&Value,phase:&str,dir:&Path)->Result<Value,String> {
    let ready:Value=serde_json::from_slice(&std::fs::read(dir.join("ready.json")).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
    call(c,"sim_operator_clock",vec![c["run"].clone(),json!(50),json!(true)]).await?;
    let session:Session=serde_json::from_slice(&std::fs::read(dir.join("actor.json")).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
    let raw=ParticipantService::open(session).await?;
    wait_for(||raw.connection.db.sim_my_controller_frame().count()==1).await?;
    let request:Request=serde_json::from_value(ready["request"].clone()).map_err(|e|e.to_string())?;
    let sequence=ready["sequence"].as_u64().unwrap();
    if phase=="timeout" {
        check(ready["timeout_observed"]==true,"child did not observe timeout")?;
        let committed=raw.connection.db.sim_my_controller_dispatch().iter().next().ok_or("timed out dispatch did not commit")?;
        check(committed.sequence==sequence,"timed out dispatch sequence mismatch")?;
    }
    if phase=="committed" {
        // Exercise loss of the ordinary receipt before controller acknowledgement.
        for _ in 0..70 {raw.observe(0,1).await?;}
        check(!raw.connection.db.sim_my_participant_receipts().iter().any(|r|r.request_id==request.request_id),"ordinary receipt was not evicted")?;
        check(raw.connection.db.sim_my_controller_dispatch().count()==1,"durable dispatch result disappeared")?;
        let replay=raw.dispatch_action(sequence,request.clone()).await?;
        check(serde_json::to_value(&replay).unwrap()==ready["receipt"],"replay did not return exact original result")?;
    }
    raw.connection.disconnect().map_err(|e|e.to_string())?;
    let mut service=ParticipantService::from_file(&dir.join("actor.json")).await?;
    call(c,"sim_operator_clock",vec![c["run"].clone(),json!(50),json!(false)]).await?;
    wait_for(||service.connection.db.sim_my_controller_frame().iter().next().is_some_and(|f|
        serde_json::from_str::<Value>(&f.action).is_ok_and(|a|a["request_id"]==request.request_id && a["status"]=="success"))).await?;
    tokio::time::sleep(Duration::from_millis(250)).await;
    call(c,"sim_operator_clock",vec![c["run"].clone(),json!(50),json!(true)]).await?;
    let f=service.connection.db.sim_my_controller_frame().iter().next().ok_or("missing final frame")?;
    check(f.revision==1,"action dispatched more than once")?;
    let a:Value=serde_json::from_str(&f.action).map_err(|e|e.to_string())?;
    if !ready["receipt"].is_null() {check(a["accepted_event"]==ready["receipt"]["event"],"accepted event changed across recovery")?;}
    // A stopped task must be repairable even while both transports remain open.
    service.interrupt_controller_relay().await;
    check(service.connection.is_active(),"task interruption closed transport")?;
    check(service.reconnect_if_needed().await?,"healthy-transport relay was not restarted")?;
    check(service.current().is_ok(),"restarted relay still reports failure")?;
    let duplicate=service.dispatch_action(sequence,request.clone()).await?;
    check(duplicate.ok && duplicate.event==a["accepted_event"].as_u64().unwrap(),"duplicate changed result")?;
    let mut changed=request.clone();changed.request_id.push_str("-different");
    check(service.dispatch_action(sequence,changed).await.is_err(),"sequence reuse with changed content accepted")?;
    let cancel=Request {api_version:API_VERSION.into(),request_id:"newer-cancel".into(),control_epoch:request.control_epoch,
        command:Command::CancelAction {expected_revision:1}};
    check(service.dispatch_action(sequence+1,cancel).await?.ok,"newer dispatch rejected")?;
    check(service.dispatch_action(sequence,request).await.is_err(),"superseded sequence accepted")?;
    let result=json!({"phase":phase,"process_killed":true,"resumed":true,"action":a,"revision_before_new_command":f.revision,
        "ordinary_receipt_eviction_tested":phase=="committed","healthy_transport_task_restarted":true,
        "timeout_after_commit_tested":phase=="timeout","exact_duplicate_result":true,"changed_content_rejected":true,"superseded_sequence_rejected":true});
    service.connection.disconnect().map_err(|e|e.to_string())?;
    Ok(result)
}

#[tokio::main]
async fn main()->Result<(),Box<dyn std::error::Error>> {
    let args:Vec<_>=std::env::args().collect();let config:Value=serde_json::from_slice(&std::fs::read(args.get(1).ok_or("config required")?)?)?;
    if args.get(2).map(String::as_str)==Some("child") {
        return child(&config,&args[3],Path::new(&args[4])).await.map_err(Into::into);
    }
    let root=PathBuf::from(config["output_dir"].as_str().ok_or("output_dir missing")?);
    std::fs::create_dir_all(&root)?;let mut results=vec![];
    let phases:Vec<&str>=config.get("phases").and_then(Value::as_array)
        .map(|p|p.iter().map(|p|p.as_str().unwrap()).collect()).unwrap_or(vec!["queued","claimed","committed","acked"]);
    for phase in phases {
        let mut c=config.clone();c["run"]=json!(format!("{}-{phase}",config["run"].as_str().unwrap()));
        let dir=PathBuf::from(config["credentials"].as_str().unwrap()).join(phase);std::fs::create_dir_all(&dir)?;
        let path=root.join(format!("{phase}-config.json"));write(&path,&c)?;
        let seed=std::fs::read_to_string(c["scenario"].as_str().unwrap())?;
        call(&c,"sim_create_client_world",vec![c["run"].clone(),json!(seed)]).await?;
        call(&c,"sim_setup_client_clock",vec![c["run"].clone(),json!("live_fixture")]).await?;
        call(&c,"sim_operator_clock",vec![c["run"].clone(),json!(50),json!(true)]).await?;
        let log=std::fs::File::create(root.join(format!("{phase}-child.log")))?;
        let mut job=tokio::process::Command::new(std::env::current_exe()?).arg(&path).args(["child",phase]).arg(&dir)
            .stdout(log.try_clone()?).stderr(log).kill_on_drop(true).spawn()?;
        let start=std::time::Instant::now();
        while !dir.join("ready.json").exists() && job.try_wait()?.is_none() && start.elapsed()<Duration::from_secs(30) {
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        let reached=dir.join("ready.json").exists();
        if job.try_wait()?.is_none() {job.kill().await?;}
        let exit=job.wait().await?;
        if phase=="timeout" {let _=std::fs::remove_file(c["proxy_hold"].as_str().ok_or("proxy_hold required")?);}
        let outcome=if reached {resumed(&c,phase,&dir).await} else {Err("child did not reach crash boundary".into())};
        // Owner-only cleanup runs even after a failed assertion; preserve failure.
        let pause=call(&c,"sim_operator_clock",vec![c["run"].clone(),json!(50),json!(true)]).await;
        let rows:Value=serde_json::from_str(&control(&c,"sql",vec![format!("SELECT identity FROM sim_client_access WHERE run = '{}'",c["run"].as_str().unwrap()),"--format".into(),"json".into()]).await?)?;
        for row in rows[0]["rows"].as_array().unwrap() {
            let identity=row[0].as_str().or_else(||row[0][0].as_str()).ok_or("identity shape")?;
            call(&c,"sim_revoke_client",vec![json!(identity.trim_start_matches("0x"))]).await?;
        }
        let result=json!({"phase":phase,"child_exit":exit.to_string(),"result":outcome.as_ref().ok(),"error":outcome.as_ref().err(),"pause_error":pause.err()});
        println!("{phase}: {}",if outcome.is_ok() {"PASS"} else {"FAIL"});results.push(result);
        write(&root.join("result.json"),&json!({"cases":results}))?;
    }
    check(results.iter().all(|r|r["error"].is_null() && r["pause_error"].is_null()),"recovery cases failed")?;
    Ok(())
}
