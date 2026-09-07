//! Actual dual-database controller smoke test. Setup uses explicit owner config;
//! the relay and mental operations use only private participant credentials.
use bridge::{controller::Controller,participant::{new_session,ParticipantService}};
use serde_json::{json,Value};
use spacetimedb_sdk::{DbContext,Table};
use shared::{module_bindings::{sim_select_inspector,sim_set_controller_delivery_cursor,
    SimMySnapshotTableAccess,SimMyRenderSnapshotTableAccess,SimMyRenderEventsTableAccess,
    SimMyParticipantHeadTableAccess,SimMyControllerExperiencesTableAccess,
    SimMyControllerFrameTableAccess,SimMyControllerDispatchTableAccess},
    controller_bindings::{MyBrainHeadTableAccess,MyBrainJournalTableAccess}};
use simulation::{participant::{Command,Request,API_VERSION},policy::Node,Action,Skill};
use std::{path::PathBuf,time::Duration};
async fn cursor(service:&ParticipantService,value:u64)->Result<(),String> {
    let(tx,rx)=tokio::sync::oneshot::channel();
    service.connection.reducers.sim_set_controller_delivery_cursor_then(value,move|_,r|{let _=tx.send(r);}).map_err(|e|e.to_string())?;
    tokio::time::timeout(Duration::from_secs(5),rx).await.map_err(|_|"cursor timeout")?
        .map_err(|_|"cursor callback lost")?.map_err(|_|"cursor transport error")?
}
async fn inspect(service:&ParticipantService,actor:Option<u32>)->Result<(),String> {
    let(tx,rx)=tokio::sync::oneshot::channel();
    service.connection.reducers.sim_select_inspector_then(actor,move|_,r|{let _=tx.send(r);}).map_err(|e|e.to_string())?;
    tokio::time::timeout(Duration::from_secs(5),rx).await.map_err(|_|"inspector timeout")?
        .map_err(|_|"inspector callback lost")?.map_err(|_|"inspector transport error")?
}
async fn wait_until(mut ready:impl FnMut()->bool)->Result<(),String> {
    tokio::time::timeout(Duration::from_secs(5),async {while !ready(){tokio::time::sleep(Duration::from_millis(10)).await;}})
        .await.map_err(|_|"subscription condition timed out".into())
}
async fn call(c:&Value,name:&str,args:Vec<Value>)->Result<(),String> {
    let mut cmd=tokio::process::Command::new(c["cli"].as_str().unwrap());
    cmd.arg("--config-path").arg(c["cli_config"].as_str().unwrap())
        .args(["call",c["database"].as_str().unwrap(),name]);
    for arg in args {cmd.arg(arg.to_string());}
    let out=cmd.args(["--server",c["server"].as_str().unwrap(),"--no-config","-y"]).output().await.map_err(|e|e.to_string())?;
    if !out.status.success() {return Err(format!("owner {name} failed: {}",String::from_utf8_lossy(&out.stderr)));}
    Ok(())
}
#[tokio::main]
async fn main()->Result<(),Box<dyn std::error::Error>> {
    let c:Value=serde_json::from_slice(&std::fs::read(std::env::args().nth(1).ok_or("config required")?)?)?;
    let run=c["run"].as_str().unwrap();
    let seed=std::fs::read_to_string(c["scenario"].as_str().unwrap())?;
    call(&c,"sim_create_client_world",vec![json!(run),json!(seed)]).await?;
    call(&c,"sim_setup_client_clock",vec![json!(run),json!("live_fixture")]).await?;
    call(&c,"sim_operator_clock",vec![json!(run),json!(50),json!(true)]).await?;
    let path=PathBuf::from(c["credentials"].as_str().unwrap()).join("actor.json");
    let outsider_path=path.with_file_name("outsider.json");
    let (outsider,_)=new_session(c["server"].as_str().unwrap().into(),c["database"].as_str().unwrap().into(),&outsider_path).await?;
    assert_eq!(outsider.connection.db.sim_my_controller_frame().count(),0);
    assert_eq!(outsider.connection.db.sim_my_controller_dispatch().count(),0);
    assert!(outsider.observe(0,1).await.is_err());
    assert!(cursor(&outsider,0).await.is_err());
    assert!(inspect(&outsider,Some(1)).await.is_err());
    outsider.connection.disconnect()?;
    let outsider_brain=Controller::provision(c["controller_server"].as_str().unwrap().into(),
        c["controller_database"].as_str().unwrap().into(),&outsider_path.with_extension("controller.json")).await?;
    assert_eq!(outsider_brain.connection.db.my_brain_head().count(),0);
    assert!(outsider_brain.current().is_err());
    for table in ["brain","brain_context","brain_experience","brain_mind_history","brain_journal","brain_last_ack","brain_journal_block","brain_journal_retention"] {
        use std::sync::{Arc,atomic::{AtomicBool,Ordering}};
        let denied=Arc::new(AtomicBool::new(false));let flag=denied.clone();
        let _subscription=outsider_brain.connection.subscription_builder()
            .on_error(move |_,_|{flag.store(true,Ordering::Release);})
            .subscribe([format!("SELECT * FROM {table}")]);
        let until=std::time::Instant::now()+Duration::from_secs(5);
        while !denied.load(Ordering::Acquire) {
            if std::time::Instant::now()>until {return Err(format!("private table {table} was not denied").into());}
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }
    drop(outsider_brain);
    let (mut service,id)=new_session(c["server"].as_str().unwrap().into(),c["database"].as_str().unwrap().into(),&path).await?;
    call(&c,"sim_grant_client",vec![json!(run),json!(id),json!(false),json!(1)]).await?;
    tokio::time::sleep(Duration::from_millis(250)).await;
    let controller=Controller::provision(c["controller_server"].as_str().unwrap().into(),
        c["controller_database"].as_str().unwrap().into(),&path.with_extension("controller.json")).await?;
    service.attach_open_controller(controller.clone()).await?;
    assert!(inspect(&service,Some(1)).await.is_err());
    assert!(cursor(&service,u64::MAX).await.is_err());
    let before=service.observe(0,256).await?;
    let request=Request {api_version:API_VERSION.into(),request_id:"probe-policy".into(),
        control_epoch:before["control_epoch"].as_u64().ok_or("missing epoch")?,
        command:Command::ReplaceTree {expected_revision:before["policy_revision"].as_u64().ok_or("missing revision")?,
            reason:"explicit controller boundary probe".into(),
            tree:Node::Once {child:Box::new(Node::Action {action:Action::new(Skill::Wait)})}}};
    let receipt=service.command(request.clone()).await?;
    if !receipt.ok {return Err(format!("policy rejected: {:?}",receipt.error).into());}
    assert!(receipt.fingerprint.starts_with("client:"));assert_eq!(receipt.event,0);
    assert_eq!(service.command(request).await?.fingerprint,receipt.fingerprint);
    if c["physical_clock"].as_bool().unwrap_or(false) {call(&c,"sim_configure_physical_clock",vec![json!(run),json!(true)]).await?;}
    call(&c,"sim_operator_clock",vec![json!(run),json!(50),json!(false)]).await?;
    tokio::time::sleep(Duration::from_secs(4)).await;
    let after=service.observe(0,256).await?;
    call(&c,"sim_operator_clock",vec![json!(run),json!(50),json!(true)]).await?;
    std::fs::write(c["output"].as_str().unwrap(),serde_json::to_vec_pretty(&json!({"before":before,"after":after,"phase":"before_assertions"}))?)?;
    assert_eq!(after["context"]["player"]["current_approach"]["authority_action"]["status"],"success");
    assert!(after["context"]["player"]["current_approach"]["state"]["once_completed"].as_array()
        .is_some_and(|paths|paths.iter().any(|p|p=="root")));
    let consumed=service.connection.db.sim_my_participant_head().iter().next().unwrap().latest_cursor;
    assert!(consumed>0);
    cursor(&service,consumed).await?;
    wait_until(||service.connection.db.sim_my_controller_experiences().count()==0).await?;
    cursor(&service,0).await?;
    wait_until(||service.connection.db.sim_my_controller_experiences().count()>0).await?;
    service.connection.subscription_builder().subscribe(["SELECT * FROM sim_my_snapshot",
        "SELECT * FROM sim_my_render_snapshot", "SELECT * FROM sim_my_render_events"]);
    wait_until(||service.connection.db.sim_my_render_snapshot().count()==1).await?;
    let personal:Value=serde_json::from_str(&service.connection.db.sim_my_snapshot().iter().next().unwrap().body)?;
    let mut personal_incremental:Value=serde_json::from_str(&service.connection.db.sim_my_render_snapshot().iter().next().unwrap().body)?;
    let mut personal_events:Vec<Value>=service.connection.db.sim_my_render_events().iter().map(|r|serde_json::from_str(&r.body).unwrap()).collect();
    personal_events.sort_by_key(|e|e["id"].as_u64().unwrap());
    personal_incremental["events"]=json!(personal_events);
    assert_eq!(personal_incremental,personal,"incremental personal projection");
    let (observer,observer_id)=new_session(c["server"].as_str().unwrap().into(),c["database"].as_str().unwrap().into(),&path.with_file_name("observer.json")).await?;
    observer.connection.subscription_builder().subscribe(["SELECT * FROM sim_my_snapshot",
        "SELECT * FROM sim_my_render_snapshot", "SELECT * FROM sim_my_render_events"]);
    call(&c,"sim_grant_client",vec![json!(run),json!(observer_id),json!(true),json!(1)]).await?;
    wait_until(||observer.connection.db.sim_my_snapshot().count()==1).await?;
    assert!(cursor(&observer,0).await.is_err());
    inspect(&observer,Some(1)).await?;
    wait_until(||observer.connection.db.sim_my_snapshot().iter().next().is_some_and(|s|serde_json::from_str::<Value>(&s.body).unwrap()["inspected_actor"]==1)).await?;
    let rendered:Value=serde_json::from_str(&observer.connection.db.sim_my_snapshot().iter().next().unwrap().body)?;
    assert!(rendered["players"].as_array().unwrap().iter().filter(|p|p["id"]!=1).all(|p|p.get("beliefs").is_none()));
    wait_until(||observer.connection.db.sim_my_render_snapshot().iter().next().is_some_and(|s|serde_json::from_str::<Value>(&s.body).unwrap()["inspected_actor"]==1)).await?;
    let mut incremental:Value=serde_json::from_str(&observer.connection.db.sim_my_render_snapshot().iter().next().unwrap().body)?;
    let mut events:Vec<Value>=observer.connection.db.sim_my_render_events().iter().map(|r|serde_json::from_str(&r.body).unwrap()).collect();
    events.sort_by_key(|e|e["id"].as_u64().unwrap());
    incremental["events"]=json!(events);
    assert_eq!(incremental,rendered,"incremental observer projection");
    call(&c,"sim_revoke_client",vec![json!(observer_id)]).await?;
    wait_until(||observer.connection.db.sim_my_snapshot().count()==0
        &&observer.connection.db.sim_my_render_snapshot().count()==0
        &&observer.connection.db.sim_my_render_events().count()==0).await?;
    observer.connection.disconnect()?;
    service.connection.disconnect()?;
    tokio::time::timeout(Duration::from_secs(5),async {
        while service.connection.is_active() {tokio::time::sleep(Duration::from_millis(10)).await;}
    }).await?;
    assert!(service.reconnect_if_needed().await?);
    assert_eq!(service.observe(0,256).await?["policy_revision"],after["policy_revision"]);
    controller.connection.disconnect()?;
    tokio::time::timeout(Duration::from_secs(5),async {
        while controller.connection.is_active() {tokio::time::sleep(Duration::from_millis(10)).await;}
    }).await?;
    assert!(service.reconnect_if_needed().await?);
    assert_eq!(service.observe(0,256).await?["policy_revision"],after["policy_revision"]);
    let current=service.current()?;
    let next_policy=current["policy_revision"].as_u64().unwrap()+1;
    assert!(service.command(Request {api_version:API_VERSION.into(),request_id:"probe-inflight-policy".into(),
        control_epoch:current["control_epoch"].as_u64().unwrap(),command:Command::ReplaceTree {
            expected_revision:next_policy-1,reason:"disconnect during an accepted finite action".into(),
            tree:Node::Once {child:Box::new(Node::Action {action:Action::new(Skill::Wait)})}}}).await?.ok);
    call(&c,"sim_operator_clock",vec![json!(run),json!(50),json!(false)]).await?;
    let until=std::time::Instant::now()+Duration::from_secs(5);
    let inflight=loop {
        let f=service.connection.db.sim_my_controller_frame().iter().next().ok_or("frame missing")?;
        let action:Value=serde_json::from_str(&f.action)?;
        if action["status"]=="running" {break json!({"revision":f.revision,"action":action});}
        if std::time::Instant::now()>until {return Err("inflight action did not start".into());}
        tokio::time::sleep(Duration::from_millis(10)).await;
    };
    service.connection.disconnect()?;
    drop(service);
    tokio::time::sleep(Duration::from_secs(3)).await;
    let resumed=ParticipantService::from_file(&path).await?;
    tokio::time::sleep(Duration::from_millis(250)).await;
    let reconnected=resumed.observe(0,256).await?;
    call(&c,"sim_operator_clock",vec![json!(run),json!(50),json!(true)]).await?;
    assert_eq!(reconnected["policy_revision"],next_policy);
    let recovered=&reconnected["context"]["player"]["current_approach"]["authority_action"];
    assert_eq!(recovered["request_id"],inflight["action"]["request_id"]);
    assert_eq!(recovered["revision"],inflight["revision"]);
    assert_eq!(recovered["status"],"success");
    let journal_controller=Controller::open(serde_json::from_slice(&std::fs::read(path.with_extension("controller.json"))?)?).await?;
    wait_until(||resumed.connection.db.sim_my_controller_frame().iter().next().is_some_and(|f|f.paused)).await?;
    journal_controller.synchronize_inputs(&resumed).await?;
    let ready=std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));let flag=ready.clone();
    journal_controller.connection.subscription_builder().on_applied(move |_|{flag.store(true,std::sync::atomic::Ordering::Release);})
        .subscribe(["SELECT * FROM my_brain_journal"]);
    wait_until(||ready.load(std::sync::atomic::Ordering::Acquire)).await?;
    let mut original:Vec<_>=journal_controller.connection.db.my_brain_journal().iter().map(|r|(r.sequence,r.kind,r.data)).collect();original.sort();
    let deletions=std::sync::Arc::new(std::sync::atomic::AtomicU64::new(0));let count=deletions.clone();
    journal_controller.connection.db.my_brain_journal().on_delete(move|_,_|{count.fetch_add(1,std::sync::atomic::Ordering::Relaxed);});
    for n in 0..400 {
        assert!(resumed.command(Request {api_version:API_VERSION.into(),request_id:format!("archive-policy-{n}"),
            control_epoch:reconnected["control_epoch"].as_u64().unwrap(),command:Command::ReplaceTree {
                expected_revision:next_policy+n,reason:"journal retention fixture".into(),
                tree:Node::Once {child:Box::new(Node::Action {action:Action::new(Skill::Wait)})}}}).await?.ok);
    }
    wait_until(||journal_controller.connection.db.my_brain_journal().count()==original.len() as u64+400).await?;
    let mut archived:Vec<_>=journal_controller.connection.db.my_brain_journal().iter().map(|r|(r.sequence,r.kind,r.data)).collect();archived.sort();
    assert_eq!(&archived[..original.len()],original.as_slice());
    assert_eq!(deletions.load(std::sync::atomic::Ordering::Relaxed),0);
    assert!(archived.windows(2).all(|r|r[1].0==r[0].0+1));
    call(&c,"sim_revoke_client",vec![json!(id)]).await?;
    tokio::time::sleep(Duration::from_millis(250)).await;
    assert_eq!(resumed.connection.db.sim_my_controller_frame().count(),0);
    assert_eq!(resumed.connection.db.sim_my_controller_dispatch().count(),0);
    assert!(resumed.observe(0,1).await.is_err());
    std::fs::write(c["output"].as_str().unwrap(),serde_json::to_vec_pretty(&json!({"before":before,"policy_receipt":receipt,"after":after,"inflight":inflight,"reconnected":reconnected,
        "journal_records":archived.len(),"journal_tail_deletions_visible":0,
        "checks":{"ungranted_world_empty":true,"foreign_mind_empty":true,"private_mind_tables_denied":true,"finite_action_success":true,"once_completed":true,"world_transport_reconnected":true,"controller_transport_reconnected":true,"reconnect_retained_policy":true,"inflight_completed_without_duplicate":true,"revocation_removed_world_access":true,
            "delivery_ack_removes_only_delivered_view_rows":true,"delivery_reset_recovers_retained_trace":true,"delivery_cursor_scope_and_bounds":true,
            "observer_inspector_scope_and_revocation":true,"journal_archive_preserves_complete_subscribed_history":true,
            "incremental_render_matches_observer_and_personal_snapshots":true}}))?)?;
    resumed.connection.disconnect()?;
    Ok(())
}
