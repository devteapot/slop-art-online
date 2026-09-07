//! Canonical native client, deployed separately from the physical world database.
//! A connection owns one mind. It can submit only its own scoped world inputs.
//! This module has no world credentials, world tables or physical executor.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use simulation::{controller::{Bootstrap, runtime::{Runtime, Frame, Dispatch}},
    participant::{Command, Experience, Receipt, Request, API_VERSION}, scripting::Registry};
use spacetimedb::{Identity, ReducerContext, ScheduleAt, Table, ViewContext};
mod journal_archive;

#[spacetimedb::table(accessor = brain)]
pub struct Brain {
    #[primary_key]
    pub owner: Identity,
    pub run: String,
    pub actor: u32,
    pub epoch: u64,
    pub cursor: u64,
    pub sequence: u64,
    pub runtime: String,
    pub frame: String,
    pub fault: Option<String>,
}
/// Large context changes at model-read frequency, not every policy update.
#[spacetimedb::table(accessor = brain_context)]
pub struct BrainContext {
    #[primary_key]
    pub owner: Identity,
    pub context: String,
}
/// Immutable scoped inputs, bounded to the latest 256 cursors per controller.
/// Older interpreted evidence remains in the durable decision journal/read leases.
#[spacetimedb::table(accessor = brain_experience, index(accessor = personal, btree(columns = [owner, cursor])))]
pub struct BrainExperience {
    #[primary_key]
    pub key: String,
    pub owner: Identity,
    pub cursor: u64,
    pub experience: String,
}
#[spacetimedb::table(accessor = brain_mind_history)]
pub struct BrainMindHistory {
    #[primary_key]
    pub owner: Identity,
    pub memories: String,
    pub site_observations: String,
    pub beliefs: String,
    pub relationships: String,
    pub knowledge: String,
}
#[spacetimedb::table(accessor = brain_head)]
pub struct BrainHead {
    #[primary_key]
    pub owner: Identity,
    pub run: String,
    pub actor: u32,
    pub epoch: u64,
    pub cursor: u64,
    pub policy_revision: u64,
    pub learning_revision: u64,
    pub stopped: bool,
    pub health: i32,
    pub fault: Option<String>,
}
#[spacetimedb::table(accessor = brain_outbox)]
pub struct BrainOutbox {
    #[primary_key]
    pub owner: Identity,
    pub request_id: String,
    pub request: String,
    pub sequence: u64,
    /// Retained for inspection; retry safety is enforced by the world sequence.
    pub claimed: bool,
}
#[spacetimedb::table(accessor = brain_last_ack)]
pub struct BrainLastAck {
    #[primary_key]
    pub owner: Identity,
    pub receipt: String,
}
#[spacetimedb::table(accessor = brain_wake, scheduled(brain_tick))]
pub struct BrainWake {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    #[unique]
    pub owner: Identity,
    pub scheduled_at: ScheduleAt,
}
#[spacetimedb::table(accessor = brain_journal, index(accessor = personal, btree(columns = [owner, sequence])))]
pub struct BrainJournal {
    #[primary_key]
    pub key: String,
    pub owner: Identity,
    pub sequence: u64,
    pub kind: String,
    pub data: String,
}
#[spacetimedb::table(accessor = brain_receipt, index(accessor = personal, btree(columns = [owner, sequence])))]
pub struct BrainReceipt {
    #[primary_key]
    pub key: String,
    pub owner: Identity,
    pub sequence: u64,
    pub request_id: String,
    pub fingerprint: String,
    pub receipt: String,
}
#[spacetimedb::table(accessor = brain_read, index(accessor = personal, btree(columns = [owner, sequence])))]
pub struct BrainRead {
    #[primary_key]
    pub key: String,
    pub owner: Identity,
    pub sequence: u64,
    pub request_id: String,
    pub cursor: u64,
    pub expires_ms: u64,
    pub observation: String,
}
fn encode(v: &impl serde::Serialize) -> String {serde_json::to_string(v).expect("controller serialization")}
fn decode<T:serde::de::DeserializeOwned>(s:&str)->Result<T,String> {serde_json::from_str(s).map_err(|e|e.to_string())}
fn key(owner:Identity, id:impl std::fmt::Display)->String {format!("{owner}:{id}")}
fn load(ctx:&ReducerContext)->Result<Brain,String> {ctx.db.brain().owner().find(ctx.sender()).ok_or("no native controller".into())}
fn runtime(ctx:&ReducerContext,b:&Brain)->Result<Runtime,String> {
    let mut r:Runtime=decode(&b.runtime)?;
    if let Some(m)=ctx.db.brain_mind_history().owner().find(b.owner) {
        macro_rules! field {($field:ident)=>{{
            let value=m.$field;
            simulation::deferred::Deferred::load_with(move ||decode(&value))
        }};}
        r.player.memories=field!(memories);
        r.player.site_observations=field!(site_observations);
        r.player.beliefs=field!(beliefs);
        r.player.relationships=field!(relationships);
        r.player.knowledge=field!(knowledge);
    }
    Ok(r)
}
fn full_runtime(ctx:&ReducerContext,b:&Brain)->Result<Runtime,String> {
    let mut r=runtime(ctx,b)?;
    // Inline fields remain readable when resuming an older controller checkpoint.
    if r.context.is_null() {
        r.context=decode(&ctx.db.brain_context().owner().find(b.owner).ok_or("controller context missing")?.context)?;
    }
    if r.experiences.is_empty() {
        r.experiences=ctx.db.brain_experience().personal().filter((b.owner,))
            .map(|e|decode(&e.experience)).collect::<Result<_,_>>()?;
    }
    Ok(r)
}
fn wake(ctx:&ReducerContext,owner:Identity) {
    if ctx.db.brain_wake().owner().find(owner).is_none() {
        ctx.db.brain_wake().insert(BrainWake {id:0,owner,scheduled_at:(ctx.timestamp+std::time::Duration::from_millis(50)).into()});
    }
}
fn persist(ctx:&ReducerContext, mut b:Brain, mut r:Runtime, f:&Frame) {
    let old=ctx.db.brain_mind_history().owner().find(b.owner);
    macro_rules! history {($field:ident)=>{{
        let value=if !r.player.$field.is_loaded() {
            old.as_ref().expect("deferred mind has stored row").$field.clone()
        } else {encode(&r.player.$field)};
        r.player.$field=Default::default();
        value
    }};}
    let history=BrainMindHistory {owner:b.owner,memories:history!(memories),site_observations:history!(site_observations),
        beliefs:history!(beliefs),relationships:history!(relationships),knowledge:history!(knowledge)};
    match old {
        Some(m) if m.memories==history.memories && m.site_observations==history.site_observations
            && m.beliefs==history.beliefs && m.relationships==history.relationships && m.knowledge==history.knowledge=>{},
        Some(_)=>{ctx.db.brain_mind_history().owner().update(history);},
        None=>{ctx.db.brain_mind_history().insert(history);},
    }
    if !r.context.is_null() {
        let context=encode(&std::mem::take(&mut r.context));
        match ctx.db.brain_context().owner().find(b.owner) {
            Some(old) if old.context==context=>{},
            Some(_)=>{ctx.db.brain_context().owner().update(BrainContext {owner:b.owner,context});},
            None=>{ctx.db.brain_context().insert(BrainContext {owner:b.owner,context});},
        }
    }
    for e in std::mem::take(&mut r.experiences) {
        let key=key(b.owner,e.cursor);
        if ctx.db.brain_experience().key().find(&key).is_none() {
            ctx.db.brain_experience().insert(BrainExperience {key,owner:b.owner,cursor:e.cursor,experience:encode(&e)});
        }
    }
    for old in ctx.db.brain_experience().personal().filter((b.owner,..=r.cursor.saturating_sub(256))) {
        ctx.db.brain_experience().key().delete(&old.key);
    }
    let journal=r.take_journal();
    let first=journal.first().map_or(0,|e|e.sequence);
    let count=journal.len() as u64;
    for entry in journal {
        ctx.db.brain_journal().insert(BrainJournal {key:key(b.owner,entry.sequence),owner:b.owner,
            sequence:entry.sequence,kind:entry.kind,data:encode(&entry.data)});
    }
    journal_archive::appended(ctx,b.owner,first,count);
    let head=BrainHead {owner:b.owner,run:b.run.clone(),actor:b.actor,epoch:b.epoch,cursor:r.cursor,
        policy_revision:r.policy_revision,learning_revision:r.learning_revision,stopped:f.stopped,
        health:f.health,fault:b.fault.clone()};
    if ctx.db.brain_head().owner().find(b.owner).is_some() {ctx.db.brain_head().owner().update(head);} else {ctx.db.brain_head().insert(head);}
    b.cursor=r.cursor; b.runtime=encode(&r); b.frame=encode(f);
    if ctx.db.brain().owner().find(b.owner).is_some() {ctx.db.brain().owner().update(b);} else {ctx.db.brain().insert(b);}
}
#[spacetimedb::reducer]
pub fn brain_register(ctx:&ReducerContext, bootstrap:String, frame:String)->Result<(),String> {
    if bootstrap.len()>2_000_000 || frame.len()>100_000 {return Err("controller input too large".into());}
    if ctx.db.brain().owner().find(ctx.sender()).is_some() {return Err("controller already exists; resume it".into());}
    let seed:Bootstrap=decode(&bootstrap)?;let f:Frame=decode(&frame)?;
    let mut r=Runtime::new(&seed)?;r.apply_frame(&f,None)?;
    let b=Brain {owner:ctx.sender(),run:seed.run,actor:seed.actor,epoch:f.control_epoch,cursor:0,sequence:0,
        runtime:String::new(),frame:String::new(),fault:None};
    persist(ctx,b,r,&f);wake(ctx,ctx.sender());Ok(())
}
#[spacetimedb::reducer]
pub fn brain_ingest(ctx:&ReducerContext, frame:String, experiences:String, holdings:Option<String>)->Result<(),String> {
    if frame.len()>100_000 || experiences.len()>2_000_000 || holdings.as_ref().is_some_and(|s|s.len()>2_000_000) {return Err("controller input too large".into());}
    let b=load(ctx)?;let f:Frame=decode(&frame)?;
    if b.epoch!=f.control_epoch {return Err("controller epoch changed; explicit handoff required".into());}
    let prior:Frame=decode(&b.frame)?;
    if f.tick<prior.tick || f.revision<prior.revision {return Err("stale controller frame".into());}
    let mut r=runtime(ctx,&b)?;
    let events:Vec<Experience>=decode(&experiences)?;
    if events.len()>256 {return Err("experience batch too large".into());}
    let registry=Registry::default();
    for event in events {r.ingest(event,&registry)?;}
    r.apply_frame(&f,holdings.as_deref().map(decode).transpose()?)?;
    persist(ctx,b,r,&f);wake(ctx,ctx.sender());Ok(())
}
#[spacetimedb::reducer]
pub fn brain_tick(ctx:&ReducerContext, scheduled:BrainWake)->Result<(),String> {
    if ctx.sender()!=ctx.identity() {return Err("scheduled controller execution only".into());}
    let Some(mut b)=ctx.db.brain().owner().find(scheduled.owner) else {return Ok(());};
    let f:Frame=decode(&b.frame)?;
    if f.paused || f.stopped || f.health<=0 || b.fault.is_some() || ctx.db.brain_outbox().owner().find(b.owner).is_some() {return Ok(());}
    let mut r=runtime(ctx,&b)?;
    let had_active = r.active.is_some();
    b.sequence+=1;
    let id=format!("brain-{}-{}",b.owner,b.sequence);
    let charge=f.body.as_ref().and_then(|b|b["charge"].as_i64()).unwrap_or(0) as i32;
    match r.tick(&id,f.action.as_ref(),&Registry::default(),charge) {
        Err(error)=>b.fault=Some(error),
        Ok(Some(dispatch))=>{
            let command=match dispatch {Dispatch::Start(action)=>Command::StartAction {expected_revision:f.revision,action},
                Dispatch::Cancel=>Command::CancelAction {expected_revision:f.revision}};
            let request=Request {api_version:API_VERSION.into(),request_id:id.clone(),control_epoch:b.epoch,command};
            ctx.db.brain_outbox().insert(BrainOutbox {owner:b.owner,request_id:id,request:encode(&request),sequence:b.sequence,claimed:false});
        }
        Ok(None)=>{},
    }
    // Input and action receipts wake the loop. A consumed terminal result may
    // advance a sequence without dispatching; schedule its next local step.
    let again=b.fault.is_none() && ctx.db.brain_outbox().owner().find(b.owner).is_none()
        && had_active && r.active.is_none() && r.tree.is_some() && r.state.status != simulation::policy::Status::Failure;
    let owner=b.owner;
    persist(ctx,b,r,&f);
    if again {
        // Current one-shot still exists until this reducer commits.
        ctx.db.brain_wake().id().delete(scheduled.id);
        wake(ctx,owner);
    }
    Ok(())
}
#[spacetimedb::reducer]
pub fn brain_claim(ctx:&ReducerContext, request_id:String)->Result<(),String> {
    let mut out=ctx.db.brain_outbox().owner().find(ctx.sender()).ok_or("no queued action")?;
    if out.request_id!=request_id {return Err("queued action changed".into());}
    if out.claimed {return Ok(());}
    out.claimed=true;ctx.db.brain_outbox().owner().update(out);Ok(())
}
#[spacetimedb::reducer]
pub fn brain_ack(ctx:&ReducerContext, receipt:String)->Result<(),String> {
    let receipt:Receipt=decode(&receipt)?;
    let encoded=encode(&receipt);
    if ctx.db.brain_last_ack().owner().find(ctx.sender()).is_some_and(|a|a.receipt==encoded) {return Ok(());}
    let out=ctx.db.brain_outbox().owner().find(ctx.sender()).ok_or("no queued action")?;
    if receipt.request_id!=out.request_id {return Err("receipt does not match pending action".into());}
    let b=load(ctx)?;let mut r=runtime(ctx,&b)?;let mut f:Frame=decode(&b.frame)?;
    if !receipt.ok {
        f.action=Some(simulation::controller::ActionState {request_id:receipt.request_id.clone(),revision:f.revision,
            accepted_event:receipt.event,status:simulation::policy::Status::Failure,attempt:None});
    }
    // Preserve the independently correlated authority receipt in the client journal.
    r.record_receipt(&receipt);
    persist(ctx,b,r,&f);
    let ack=BrainLastAck {owner:ctx.sender(),receipt:encoded};
    if ctx.db.brain_last_ack().owner().find(ctx.sender()).is_some() {ctx.db.brain_last_ack().owner().update(ack);}
    else {ctx.db.brain_last_ack().insert(ack);}
    ctx.db.brain_outbox().owner().delete(ctx.sender());wake(ctx,ctx.sender());Ok(())
}

#[spacetimedb::reducer]
pub fn brain_refresh_context(ctx:&ReducerContext, context:String)->Result<(),String> {
    if context.len()>2_000_000 {return Err("context too large".into());}
    let b=load(ctx)?;let f:Frame=decode(&b.frame)?;let mut r=runtime(ctx,&b)?;
    let context:Value=decode(&context)?;
    if context["player"]["id"].as_u64()!=Some(u64::from(b.actor)) {return Err("foreign context".into());}
    // The relay supplies an authenticated owner-scoped read only at model-read
    // frequency. Runtime::observation overlays the privately maintained mind.
    r.context=context;
    persist(ctx,b,r,&f);Ok(())
}
#[spacetimedb::reducer]
pub fn brain_command(ctx:&ReducerContext, request:String)->Result<(),String> {
    if request.len()>50_000 {return Err("command too large".into());}
    let request:Request=decode(&request)?;
    if request.request_id.is_empty() || request.request_id.len()>100 {return Err("invalid request ID".into());}
    let fingerprint=format!("client:{:x}",Sha256::digest(encode(&request).as_bytes()));
    let receipt_key=key(ctx.sender(),&request.request_id);
    if let Some(old)=ctx.db.brain_receipt().key().find(&receipt_key) {
        return if old.fingerprint==fingerprint {Ok(())} else {Err("request ID reused with different command".into())};
    }
    let mut b=load(ctx)?;let f:Frame=decode(&b.frame)?;let mut r=full_runtime(ctx,&b)?;
    b.sequence+=1;
    let result=(||->Result<(),String> {
        if request.api_version!=API_VERSION || request.control_epoch!=b.epoch {return Err("API version or control epoch mismatch".into());}
        if f.stopped || f.health<=0 {return Err("character dead or run stopped".into());}
        match &request.command {
            Command::ReadObservation {after,limit}=>{
                if *after>r.cursor {return Err("cursor ahead of retained trace".into());}
                let mut observation=r.observation(&f,*after,*limit);
                observation["next_cursor"]=observation["observed_cursor"].clone();
                let expires=f.tick.saturating_mul(simulation::timing::LEGACY_UNIT_MS).saturating_add(simulation::participant::EVIDENCE_LEASE_MS);
                observation["evidence_lease"]=json!({"expires_ms":expires,"duration_ms":simulation::participant::EVIDENCE_LEASE_MS,"provenance":"client"});
                let cursor=observation["observed_cursor"].as_u64().unwrap();
                let mut previous:Vec<_>=ctx.db.brain_read().personal().filter((ctx.sender(),)).collect();
                previous.sort_by_key(|r|r.sequence);
                for old in previous.iter().take(previous.len().saturating_sub(3)) {ctx.db.brain_read().key().delete(&old.key);}
                ctx.db.brain_read().insert(BrainRead {key:receipt_key.clone(),owner:ctx.sender(),sequence:b.sequence,
                    request_id:request.request_id.clone(),cursor,expires_ms:expires,observation:encode(&observation)});
            }
            Command::ReplaceTree {expected_revision,tree,reason}=>r.replace(*expected_revision,tree.clone(),reason)?,
            Command::PatchSubtree {expected_revision,path,subtree,reason}=>r.patch(*expected_revision,path,subtree.clone(),reason)?,
            Command::Reflect {expected_revision,observed_cursor,reflections,goal}=>{
                let reads:Vec<BrainRead>=ctx.db.brain_read().personal().filter((ctx.sender(),)).filter(|read|read.cursor==*observed_cursor
                    && read.expires_ms>=f.tick*simulation::timing::LEGACY_UNIT_MS).collect();
                let mut retained=vec![];
                for read in reads {let v:Value=decode(&read.observation)?;retained.extend(serde_json::from_value::<Vec<Experience>>(v["experiences"].clone()).map_err(|e|e.to_string())?);}
                r.reflect(*expected_revision,*observed_cursor,reflections,goal.as_deref(),&retained,&Registry::default())?;
            }
            Command::PinObservation {observed_cursor,sources}=>{
                if sources.is_empty() || sources.len()>128 {return Err("invalid pin batch".into());}
                let mut found=false;
                for mut read in ctx.db.brain_read().personal().filter((ctx.sender(),)) {
                    if read.cursor!=*observed_cursor || read.expires_ms<f.tick*simulation::timing::LEGACY_UNIT_MS {continue;}
                    let v:Value=decode(&read.observation)?;
                    if sources.iter().all(|id|v["experiences"].as_array().is_some_and(|es|es.iter().any(|e|e["source"].as_u64()==Some(*id)))) {
                        read.expires_ms=f.tick*simulation::timing::LEGACY_UNIT_MS+simulation::participant::EVIDENCE_LEASE_MS;
                        ctx.db.brain_read().key().update(read);found=true;break;
                    }
                }
                if !found {return Err("supplied observation is no longer retained".into());}
            }
            _=>return Err("physical commands go to the world authority".into()),
        }
        Ok(())
    })();
    let receipt=Receipt {request_id:request.request_id.clone(),fingerprint:fingerprint.clone(),ok:result.is_ok(),
        error:result.err(),event:0};
    ctx.db.brain_receipt().insert(BrainReceipt {key:receipt_key,owner:ctx.sender(),sequence:b.sequence,
        request_id:request.request_id,fingerprint,receipt:encode(&receipt)});
    let mut previous:Vec<_>=ctx.db.brain_receipt().personal().filter((ctx.sender(),)).collect();
    // A transaction's newly inserted row can precede persisted index rows.
    // Retention follows the explicit sequence, never iterator arrival order.
    previous.sort_by_key(|r|r.sequence);
    for old in previous.iter().take(previous.len().saturating_sub(64)) {ctx.db.brain_receipt().key().delete(&old.key);}
    persist(ctx,b,r,&f);wake(ctx,ctx.sender());Ok(())
}
#[spacetimedb::view(accessor = my_brain_head, public)]
pub fn my_brain_head(ctx:&ViewContext)->Option<BrainHead> {ctx.db.brain_head().owner().find(ctx.sender())}
#[spacetimedb::view(accessor = my_brain_outbox, public)]
pub fn my_brain_outbox(ctx:&ViewContext)->Option<BrainOutbox> {ctx.db.brain_outbox().owner().find(ctx.sender())}
#[spacetimedb::view(accessor = my_brain_receipts, public)]
pub fn my_brain_receipts(ctx:&ViewContext)->Vec<BrainReceipt> {ctx.db.brain_receipt().personal().filter((ctx.sender(),)).collect()}
#[spacetimedb::view(accessor = my_brain_reads, public)]
pub fn my_brain_reads(ctx:&ViewContext)->Vec<BrainRead> {ctx.db.brain_read().personal().filter((ctx.sender(),)).collect()}
#[spacetimedb::view(accessor = my_brain_journal, public)]
pub fn my_brain_journal(ctx:&ViewContext)->Vec<BrainJournal> {journal_archive::journal(ctx)}
