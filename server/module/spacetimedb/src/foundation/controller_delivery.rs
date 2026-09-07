//! Sender-scoped controller delivery. Every lookup follows the authenticated grant.
//! Bootstrap, live facts and individual experiences have independent lifetimes.
use super::{client_access::*, native_storage::*, participant_delivery::*};
use spacetimedb::{ReducerContext, SpacetimeType, Table, ViewContext};

/// Published facts change independently of private physical execution counters.
#[spacetimedb::table(accessor = sim_controller_frame_state)]
pub struct SimControllerFrameState {
    #[primary_key]
    pub key: String,
    pub frame: String,
}

/// One durable dispatch result per actor/ownership epoch. General observation
/// receipts may rotate out; this high-water mark must not rotate with them.
#[spacetimedb::table(accessor = sim_controller_dispatch)]
pub struct SimControllerDispatch {
    #[primary_key]
    pub key: String,
    pub run: String,
    pub actor: u32,
    pub control_epoch: u64,
    pub sequence: u64,
    pub request: String,
    pub receipt: String,
}
/// Delivery progress only. The complete retained personal trace stays in its
/// canonical table, and a reconnect may explicitly request that range again.
#[spacetimedb::table(accessor = sim_controller_delivery_cursor)]
pub struct SimControllerDeliveryCursor {
    #[primary_key]
    pub key: String,
    pub control_epoch: u64,
    pub cursor: u64,
}
fn delivery_cursor(ctx: &ReducerContext, cursor: u64, reset: bool) -> Result<(), String> {
    let access=grant(ctx)?;
    if access.observer { return Err("participant ownership required".into()); }
    let key=format!("{}:{}",access.run,access.actor);
    if ctx.db.sim_controller_bootstrap().key().find(&key).is_none() { return Err("client controller mode required".into()); }
    let head=ctx.db.sim_participant_head().key().find(&key).ok_or("participant head missing")?;
    if cursor>head.latest_cursor { return Err("delivery cursor ahead of personal trace".into()); }
    let old=ctx.db.sim_controller_delivery_cursor().key().find(&key);
    let cursor=if reset {cursor} else {old.as_ref().filter(|r|r.control_epoch==head.control_epoch).map_or(cursor,|r|r.cursor.max(cursor))};
    if old.as_ref().is_some_and(|r|r.control_epoch==head.control_epoch && r.cursor==cursor) {return Ok(());}
    let row=SimControllerDeliveryCursor {key,control_epoch:head.control_epoch,cursor};
    if old.is_some() {ctx.db.sim_controller_delivery_cursor().key().update(row);}
    else {ctx.db.sim_controller_delivery_cursor().insert(row);}
    Ok(())
}
#[spacetimedb::reducer]
pub fn sim_set_controller_delivery_cursor(ctx: &ReducerContext, cursor: u64) -> Result<(), String> {
    delivery_cursor(ctx,cursor,true)
}
/// Piggyback a cursor already committed by the persistent controller on its
/// next action. The original dispatch API remains available to older clients.
#[spacetimedb::reducer]
pub fn sim_dispatch_controller_action_after(ctx: &ReducerContext, sequence:u64, request:String, cursor:u64) -> Result<(),String> {
    sim_dispatch_controller_action(ctx,sequence,request)?;
    delivery_cursor(ctx,cursor,false)
}

#[spacetimedb::view(accessor = sim_my_controller_dispatch, public)]
pub fn sim_my_controller_dispatch(ctx: &ViewContext) -> Option<SimControllerDispatch> {
    let access=ctx.db.sim_client_access().identity().find(ctx.sender())?;
    if access.observer {return None;}
    let key=format!("{}:{}",access.run,access.actor);
    let head=ctx.db.sim_participant_head().key().find(&key)?;
    ctx.db.sim_controller_dispatch().key().find(key)
        .filter(|d|d.control_epoch==head.control_epoch)
}

/// Idempotent finite-action transport. Sequence gaps are allowed, but an old
/// sequence can never perform another action, even after its receipt is replaced.
#[spacetimedb::reducer]
pub fn sim_dispatch_controller_action(ctx:&ReducerContext, sequence:u64, request:String)->Result<(),String> {
    let access=grant(ctx)?;
    if access.observer {return Err("participant ownership required".into());}
    if sequence==0 || request.len()>50_000 {return Err("invalid dispatch sequence/request size".into());}
    let parsed:simulation::participant::Request=serde_json::from_str(&request).map_err(|e|e.to_string())?;
    if !matches!(parsed.command,simulation::participant::Command::StartAction {..}|simulation::participant::Command::CancelAction {..}) {
        return Err("sequenced dispatch requires a finite action command".into());
    }
    let key=format!("{}:{}",access.run,access.actor);
    let head=ctx.db.sim_participant_head().key().find(&key).ok_or("participant head missing")?;
    if parsed.control_epoch!=head.control_epoch {return Err("controller epoch changed; explicit handoff required".into());}
    if ctx.db.sim_controller_bootstrap().key().find(&key).is_none() {return Err("action API requires client controller mode".into());}
    let canonical=serde_json::to_string(&parsed).map_err(|e|e.to_string())?;
    if let Some(old)=ctx.db.sim_controller_dispatch().key().find(&key) {
        if old.control_epoch==parsed.control_epoch {
            if sequence<old.sequence {return Err("dispatch sequence already superseded".into());}
            if sequence==old.sequence {
                return if old.request==canonical {Ok(())} else {Err("dispatch sequence reused with different request".into())};
            }
        }
    }
    // Nested reducer function executes in this same transaction: no interval
    // exists in which the physical command commits without its durable result.
    sim_participant_command(ctx,canonical.clone())?;
    let r=ctx.db.sim_participant_receipt().key().find(format!("{}:{}:{}",access.run,access.actor,parsed.request_id))
        .ok_or("dispatch receipt missing")?;
    let receipt=simulation::participant::Receipt {request_id:r.request_id,fingerprint:r.fingerprint,
        ok:r.ok,error:r.error,event:r.event};
    let row=SimControllerDispatch {key:key.clone(),run:access.run,actor:access.actor,
        control_epoch:parsed.control_epoch,sequence,request:canonical,receipt:serde_json::to_string(&receipt).unwrap()};
    if ctx.db.sim_controller_dispatch().key().find(&key).is_some() {ctx.db.sim_controller_dispatch().key().update(row);}
    else {ctx.db.sim_controller_dispatch().insert(row);}
    Ok(())
}

#[derive(SpacetimeType, serde::Serialize, serde::Deserialize)]
pub struct SimControllerFrame {
    pub run: String,
    pub actor: u32,
    pub tick: u64,
    pub stopped: bool,
    pub paused: bool,
    pub control_epoch: u64,
    pub revision: u64,
    pub position: i32,
    pub health: i32,
    pub hunger: i32,
    pub energy: i32,
    pub food: i32,
    pub fear: i32,
    pub failures: u32,
    pub action: String,
    pub body: Option<String>,
    pub materials: Option<String>,
    pub action_ready_ms: u64,
}
#[spacetimedb::view(accessor = sim_my_controller_bootstrap, public)]
pub fn sim_my_controller_bootstrap(ctx: &ViewContext) -> Option<SimControllerBootstrap> {
    let a = ctx.db.sim_client_access().identity().find(ctx.sender())?;
    if a.observer { return None; }
    ctx.db.sim_controller_bootstrap().key().find(format!("{}:{}",a.run,a.actor))
}
#[spacetimedb::view(accessor = sim_my_controller_frame, public)]
pub fn sim_my_controller_frame(ctx: &ViewContext) -> Option<SimControllerFrame> {
    let a = ctx.db.sim_client_access().identity().find(ctx.sender())?;
    if a.observer { return None; }
    let key = format!("{}:{}",a.run,a.actor);
    if let Some(row)=ctx.db.sim_controller_frame_state().key().find(&key) {
        let mut frame:SimControllerFrame=serde_json::from_str(&row.frame).ok()?;
        frame.paused=ctx.db.sim_client_clock().run().find(&a.run).is_none_or(|c|c.paused);
        return Some(frame);
    }
    let c = ctx.db.sim_native_controller().key().find(&key)?;
    let p = ctx.db.sim_native_actor().key().find(&key)?;
    let m = ctx.db.sim_native_mind().key().find(&key)?;
    let h = ctx.db.sim_participant_head().key().find(&key)?;
    let aux = ctx.db.sim_native_actor_aux().key().find(&key)?;
    let paused = ctx.db.sim_client_clock().run().find(&a.run).is_none_or(|c|c.paused);
    Some(SimControllerFrame { run:a.run, actor:a.actor, tick:h.tick, stopped:h.stopped,
        paused, control_epoch:h.control_epoch, revision:m.generation,
        position:p.position, health:p.health, hunger:p.hunger, energy:p.energy, food:p.food,
        fear:m.fear, failures:m.failures, action:c.action, body:aux.body,
        materials:aux.materials, action_ready_ms:aux.action_ready_ms.unwrap_or(0) })
}
pub(super) fn publish_frame(ctx:&ReducerContext,run:&str,tick:u64,stopped:bool,
    player:&simulation::Player,state:&simulation::participant::ParticipantState) {
    let Some(controller)=&state.client_controller else {return;};
    let key=format!("{run}:{}",player.id);
    let aux=ctx.db.sim_native_actor_aux().key().find(&key).expect("controller actor auxiliary state");
    let frame=SimControllerFrame {run:run.into(),actor:player.id,tick,stopped,paused:false,
        control_epoch:state.control_epoch,revision:player.generation,position:player.position,
        health:player.health,hunger:player.hunger,energy:player.energy,food:player.food,fear:player.fear,
        failures:player.failures,action:serde_json::to_string(&controller.action).unwrap(),
        body:aux.body,materials:aux.materials,action_ready_ms:aux.action_ready_ms.unwrap_or(0)};
    let row=SimControllerFrameState {key:key.clone(),frame:serde_json::to_string(&frame).unwrap()};
    match ctx.db.sim_controller_frame_state().key().find(&key) {
        Some(old) if old.frame==row.frame=>{},
        Some(_)=>{ctx.db.sim_controller_frame_state().key().update(row);},
        None=>{ctx.db.sim_controller_frame_state().insert(row);},
    }
}
#[spacetimedb::view(accessor = sim_my_controller_experiences, public)]
pub fn sim_my_controller_experiences(ctx: &ViewContext) -> Vec<SimNativeExperience> {
    let scope=ctx.db.sim_client_access().identity().find(ctx.sender()).filter(|a| !a.observer)
        .filter(|a|ctx.db.sim_controller_bootstrap().key().find(format!("{}:{}",a.run,a.actor)).is_some());
    let Some(scope) = scope else { return vec![]; };
    // On the pinned 2.10 host, RawQuery views record whole-table read sets.
    // A procedural indexed range instead tracks only this participant's rows.
    let key=format!("{}:{}",scope.run,scope.actor);
    let head=ctx.db.sim_participant_head().key().find(&key);
    let cursor=ctx.db.sim_controller_delivery_cursor().key().find(&key)
        .filter(|r|head.as_ref().is_some_and(|h|h.control_epoch==r.control_epoch)).map_or(0,|r|r.cursor);
    if cursor==u64::MAX {return vec![];}
    // Keep the exact actor-prefix read set on the pinned host. The mixed
    // three-column prefix/range invalidates much more broadly in the measured
    // 2.10 runtime. The retained actor range is bounded to 256 rows.
    ctx.db.sim_native_experience().controller_scope().filter((scope.run.as_str(), scope.actor))
        .filter(|row|row.cursor>cursor).collect()
}
#[derive(SpacetimeType)]
pub struct SimControllerKnowledge {
    pub run: String,
    pub actor: u32,
    pub holdings: String,
}
#[spacetimedb::view(accessor = sim_my_controller_knowledge, public)]
pub fn sim_my_controller_knowledge(ctx: &ViewContext) -> Option<SimControllerKnowledge> {
    let a = ctx.db.sim_client_access().identity().find(ctx.sender())?;
    if a.observer { return None; }
    let key = format!("{}:{}",a.run,a.actor);
    ctx.db.sim_native_controller().key().find(&key)?;
    let m = ctx.db.sim_native_mind_history().key().find(key)?;
    Some(SimControllerKnowledge { run:a.run,actor:a.actor,holdings:m.knowledge })
}
