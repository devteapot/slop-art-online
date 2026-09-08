//! Measured clients use scoped rendering and either Bevy convenience intents or
//! explicit participant actions. Automated inputs are not human playtests.
use super::*;
use shared::module_bindings::{sim_client_intent,sim_participant_command,sim_select_inspector,
    SimMyRenderSnapshotTableAccess,SimMyRenderEventsTableAccess,SimMyParticipantReceiptsTableAccess,
    SimMyRenderHeaderTableAccess,SimMyRenderActorsTableAccess,SimMyRenderBodiesTableAccess,
    SimMyRenderSitesTableAccess,SimMyRenderSceneTableAccess};
use std::sync::{Arc,Mutex,atomic::{AtomicBool,AtomicU64,Ordering}};

#[derive(Default)]
struct RenderStats {
    components: bool,
    active: AtomicBool,
    count: AtomicU64,
    bytes: AtomicU64,
    max_bytes: AtomicU64,
    updates: AtomicU64,
    time_ms: AtomicU64,
    event_rows: AtomicU64,
    event_bytes: AtomicU64,
    event_deletions: AtomicU64,
    component_inserts: AtomicU64,
    component_deletions: AtomicU64,
    frames: Mutex<Vec<Value>>,
}
fn record_header(stats:&RenderStats, body:&str) {
    if !stats.active.load(Ordering::Relaxed) { return; }
    stats.count.fetch_add(1,Ordering::Relaxed);
    stats.bytes.fetch_add(body.len() as u64,Ordering::Relaxed);
    stats.max_bytes.fetch_max(body.len() as u64,Ordering::Relaxed);
    if let Ok(value)=serde_json::from_str::<Value>(body) {
        stats.updates.store(value["updates"].as_u64().unwrap_or(0),Ordering::Relaxed);
        stats.time_ms.store(value["time_ms"].as_u64().unwrap_or(0),Ordering::Relaxed);
        stats.frames.lock().unwrap().push(json!({"wall_ms":wall_ms(),"time_ms":value["time_ms"],"updates":value["updates"]}));
    }
}
async fn render(service:&ParticipantService, components:bool)->Result<Arc<RenderStats>,String> {
    let stats=Arc::new(RenderStats { components, ..Default::default() });let copy=stats.clone();
    if components {
        service.connection.db.sim_my_render_header().on_insert(move|_,row|record_header(&copy,&row.body));
        macro_rules! changed {
            ($table:ident) => {{
                let copy=stats.clone();
                service.connection.db.$table().on_insert(move|_,_| {
                    if copy.active.load(Ordering::Relaxed) { copy.component_inserts.fetch_add(1,Ordering::Relaxed); }
                });
                let copy=stats.clone();
                service.connection.db.$table().on_delete(move|_,_| {
                    if copy.active.load(Ordering::Relaxed) { copy.component_deletions.fetch_add(1,Ordering::Relaxed); }
                });
            }};
        }
        changed!(sim_my_render_actors);
        changed!(sim_my_render_bodies);
        changed!(sim_my_render_sites);
        changed!(sim_my_render_scene);
    } else {
        service.connection.db.sim_my_render_snapshot().on_insert(move|_,row|record_header(&copy,&row.body));
    }
    let copy=stats.clone();
    service.connection.db.sim_my_render_events().on_insert(move|_,row| {
        if !copy.active.load(Ordering::Relaxed) { return; }
        copy.event_rows.fetch_add(1,Ordering::Relaxed);
        copy.event_bytes.fetch_add(row.body.len() as u64,Ordering::Relaxed);
    });
    let copy=stats.clone();
    service.connection.db.sim_my_render_events().on_delete(move|_,_| {
        if copy.active.load(Ordering::Relaxed) { copy.event_deletions.fetch_add(1,Ordering::Relaxed); }
    });
    let queries=if components { shared::render_projection::SUBSCRIPTIONS.to_vec() }
        else {vec!["SELECT * FROM sim_my_render_snapshot", "SELECT * FROM sim_my_render_events"]};
    let(tx,rx)=tokio::sync::oneshot::channel();
    service.connection.subscription_builder().on_applied(move |_| {let _=tx.send(());}).subscribe(queries);
    tokio::time::timeout(Duration::from_secs(10),rx).await.map_err(|_|"render subscription timeout")?
        .map_err(|_|"render subscription disconnected")?;
    let present=if components {service.connection.db.sim_my_render_header().count()>0}
        else {service.connection.db.sim_my_render_snapshot().count()>0};
    if !present {return Err("applied render subscription has no scoped header".into());}
    Ok(stats)
}
pub struct LiveClients {
    output:PathBuf,
    observer:Option<ParticipantService>,
    human:Option<usize>,
    route:Option<(i32,i32)>,
    renders:Vec<(&'static str,Arc<RenderStats>)>,
    inputs:Arc<Mutex<Vec<Value>>>,
    receipts:Arc<Mutex<Vec<Value>>>,
    action_frames:Arc<Mutex<Vec<Value>>>,
    active:Arc<AtomicBool>,
    direct_input:bool,
    next_input:Instant,
    sent:u64,
}
impl LiveClients {
    pub async fn setup(c:&Value,scenario:&simulation::Scenario,people:&[ParticipantService])->Result<Self,String> {
        let components=match c["render_mode"].as_str().unwrap_or("compatibility") {
            "compatibility"=>false,"components"=>true,_=>return Err("unknown render subscription mode".into()),
        };
        let human=c["human_actor"].as_u64().map(|id|scenario.players.iter().position(|p|u64::from(p.id)==id)
            .ok_or("human actor missing from scenario")).transpose()?;
        let mut result=Self {output:PathBuf::from(c["output_dir"].as_str().unwrap()).join("live-client-result.json"),
            observer:None,human,route:None,renders:vec![],inputs:Arc::default(),receipts:Arc::default(),
            action_frames:Arc::default(),active:Arc::default(),direct_input:c["direct_input"].as_bool().unwrap_or(false)||c["no_render"].as_bool().unwrap_or(false),next_input:Instant::now(),sent:0};
        if let Some(i)=human {
            let service=&people[i];
            let active=result.active.clone();let receipts=result.receipts.clone();
            service.connection.db.sim_my_participant_receipts().on_insert(move|_,r| {
                if active.load(Ordering::Relaxed) {
                    receipts.lock().unwrap().push(json!({"wall_ms":wall_ms(),"request_id":r.request_id,"ok":r.ok,"error":r.error,"event":r.event}));
                }
            });
            let active=result.active.clone();let frames=result.action_frames.clone();
            service.connection.db.sim_my_controller_frame().on_insert(move|_,frame| {
                if active.load(Ordering::Relaxed) {
                    if let Ok(action)=serde_json::from_str::<Value>(&frame.action) {
                        frames.lock().unwrap().push(json!({"wall_ms":wall_ms(),"action":action,"position":frame.position,"health":frame.health,
                            "energy":frame.energy,"food":frame.food,"hunger":frame.hunger,"action_ready_ms":frame.action_ready_ms}));
                    }
                }
            });
            let map=if c["no_render"].as_bool().unwrap_or(false) {scenario.map.clone()} else {
                let stats=render(service,components).await?;
                result.renders.push(("human",stats));
                let value:Value=if components {
                    shared::render_projection::from_tables(&service.connection.db)?.ok_or("component snapshot missing")?
                } else {serde_json::from_str(&service.connection.db.sim_my_render_snapshot().iter().next().unwrap().body).map_err(|e|e.to_string())?};
                serde_json::from_value(value["map"].clone()).map_err(|e|e.to_string())?
            };
            let origin=scenario.players[i].position;
            let offsets=map.as_ref().map_or(vec![1,-1],|m|vec![1,-1,m.width,-m.width]);
            let destination=offsets.into_iter().map(|n|origin+n).find(|p|map.as_ref()
                .map_or((-10..=10).contains(p),|m|m.walkable(*p)&&m.distance(origin,*p)==1)).ok_or("human needs a surveyed adjacent walkable cell")?;
            result.route=Some((origin,destination));
        }
        if c["observer"].as_bool().unwrap_or(false) {
            let path=PathBuf::from(c["credentials"].as_str().unwrap()).join("observer.json");
            let (observer,id)=new_session(c["server"].as_str().unwrap().into(),c["database"].as_str().unwrap().into(),&path).await?;
            call(c,"sim_grant_client",vec![c["run"].clone(),json!(id),json!(true),json!(0)]).await?;
            let stats=render(&observer,components).await?;
            let inspected=scenario.players[human.unwrap_or(0)].id;
            let(tx,rx)=tokio::sync::oneshot::channel();
            observer.connection.reducers.sim_select_inspector_then(Some(inspected),move|_,r|{let _=tx.send(r);}).map_err(|e|e.to_string())?;
            tokio::time::timeout(Duration::from_secs(10),rx).await.map_err(|_|"inspector timeout")?
                .map_err(|_|"inspector callback lost")?.map_err(|_|"inspector transport failed")??;
            result.renders.push(("observer",stats));result.observer=Some(observer);
        }
        Ok(result)
    }
    pub fn begin(&mut self) {
        self.active.store(true,Ordering::Relaxed);
        for (_,r) in &self.renders {r.active.store(true,Ordering::Relaxed);}
        self.next_input=Instant::now()+Duration::from_millis(500);
    }
    pub fn poll(&mut self,people:&[ParticipantService])->Result<(),String> {
        let Some(i)=self.human else {return Ok(());};
        if Instant::now()<self.next_input {return Ok(());}
        let service=&people[i];
        let frame=service.connection.db.sim_my_controller_frame().iter().next().ok_or("human frame missing")?;
        if frame.health<=0 {return Err("human character died during measured workload".into());}
        let (a,b)=self.route.unwrap();
        let (action,hold_ms)=if frame.hunger>=25 && frame.food>0 {(json!({"skill":"eat","duration":1}),1000)}
            else if frame.energy<35 {(json!({"skill":"rest","duration":1}),3000)}
            else {(json!({"skill":"move","duration":1,"destination":if frame.position==a {b} else {a}}),500)};
        self.next_input=Instant::now()+Duration::from_millis(hold_ms);
        self.sent+=1;
        let sequence=self.sent;let begin=Instant::now();let sent_wall_ms=wall_ms();let inputs=self.inputs.clone();
        let sent_action=action.clone();
        let request_id=self.direct_input.then(||format!("raw-input-{sequence}"));
        let logged_id=request_id.clone();
        let on_done=move|ctx: &shared::module_bindings::ReducerEventContext,result| {
            let (ok,error)=match result {Ok(Ok(()))=>(true,None),Ok(Err(e))=>(false,Some(e)),Err(_)=>(false,Some("connection lost; outcome unknown".into()))};
            inputs.lock().unwrap().push(json!({"sequence":sequence,"sent_wall_ms":sent_wall_ms,"received_wall_ms":wall_ms(),
                "latency_us":begin.elapsed().as_micros(),"reducer_commit_ok":ok,"error":error,"action":sent_action,"request_id":logged_id,
                "server_reducer_invoked_us":ctx.event.timestamp.to_micros_since_unix_epoch()}));
        };
        if let Some(request_id)=request_id {
            let request=simulation::participant::Request {api_version:simulation::participant::API_VERSION.into(),request_id,
                control_epoch:frame.control_epoch,command:simulation::participant::Command::StartAction {
                    expected_revision:frame.revision,action:serde_json::from_value(action).map_err(|e|e.to_string())?}};
            service.connection.reducers.sim_participant_command_then(serde_json::to_string(&request).unwrap(),on_done).map_err(|_|"human input not sent")?;
        } else {
            service.connection.reducers.sim_client_intent_then(json!({"reason":"Automated Bevy input workload","actions":[action],"reflections":[]}).to_string(),on_done).map_err(|_|"human input not sent")?;
        }
        Ok(())
    }
    pub fn sample(&self)->Value {
        json!(self.renders.iter().map(|(kind,r)|json!({"kind":kind,"snapshots":r.count.load(Ordering::Relaxed),
            "render_mode":if r.components {"components"} else {"compatibility"},
            "byte_scope":if r.components {"header and event JSON only; component row bytes excluded; use server wire counters for total delivery"} else {"snapshot and event JSON bodies; not compressed wire bytes"},
            "component_inserts":r.component_inserts.load(Ordering::Relaxed),"component_deletions":r.component_deletions.load(Ordering::Relaxed),
            "body_bytes":r.bytes.load(Ordering::Relaxed)+r.event_bytes.load(Ordering::Relaxed),
            "frame_bytes":r.bytes.load(Ordering::Relaxed),"event_bytes":r.event_bytes.load(Ordering::Relaxed),
            "event_rows":r.event_rows.load(Ordering::Relaxed),"event_deletions":r.event_deletions.load(Ordering::Relaxed),
            "max_body_bytes":r.max_bytes.load(Ordering::Relaxed),
            "updates":r.updates.load(Ordering::Relaxed),"time_ms":r.time_ms.load(Ordering::Relaxed)})).collect::<Vec<_>>())
    }
    pub fn finish(&self)->Value {
        self.active.store(false,Ordering::Relaxed);
        for (_,r) in &self.renders {r.active.store(false,Ordering::Relaxed);}
        let inputs=self.inputs.lock().unwrap();
        json!({"human_connections":usize::from(self.human.is_some()),"observer_connections":usize::from(self.observer.is_some()),
            "human_inputs_sent":self.sent,"pending_human_callbacks":self.sent.saturating_sub(inputs.len() as u64),
            "human_inputs":*inputs,"human_receipts":*self.receipts.lock().unwrap(),"action_frames":*self.action_frames.lock().unwrap(),"renderers":self.sample(),"route":self.route,
            "render_frames":self.renders.iter().map(|(kind,r)|json!({"kind":kind,"frames":*r.frames.lock().unwrap()})).collect::<Vec<_>>(),
            "input_path":if self.direct_input {"explicit participant StartAction"} else {"Bevy convenience intent"},
            "input_policy":"automated surveyed adjacent moves at 2 Hz, eat at hunger >=25, rest below energy 35; ordinary costs/cooldowns",
            "latency_definition":"SDK intent send to reducer completion; separate receipt outcomes, not animation completion or browser frame pacing"})
    }
}
impl Drop for LiveClients {
    fn drop(&mut self) {
        if !self.output.exists() {
            let mut value=self.finish();value["completed"]=json!(false);
            if let Err(error)=std::fs::write(&self.output,serde_json::to_vec_pretty(&value).unwrap()) {
                eprintln!("failed to retain live client outcomes: {error}");
            }
        }
        if let Some(observer)=&self.observer {let _=observer.connection.disconnect();}
    }
}
