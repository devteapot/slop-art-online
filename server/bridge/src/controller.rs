//! Relay for a separately deployed canonical controller database.
//! Both connections use participant credentials; neither has operator authority.
use crate::participant::{ParticipantService, Session};
use shared::{controller_bindings as brain, module_bindings as world};
use brain::{brain_ack, brain_command, brain_ingest, brain_register, brain_refresh_context,
    MyBrainHeadTableAccess, MyBrainOutboxTableAccess, MyBrainReadsTableAccess,
    MyBrainReceiptsTableAccess};
use world::{SimMyControllerBootstrapTableAccess, SimMyControllerExperiencesTableAccess,
    SimMyControllerFrameTableAccess, SimMyControllerKnowledgeTableAccess,
    SimMyControllerDispatchTableAccess};
use simulation::{controller::runtime::Frame, participant::{Experience, Receipt, Request}};
use spacetimedb_sdk::{DbContext, Table};
use std::{sync::{Arc, Mutex}, time::Duration};
use serde_json::Value;

pub struct Controller {
    pub connection: Arc<brain::DbConnection>,
    session: Mutex<Session>,
    // Serializes ingestion and model commands, including observation capture.
    serial: tokio::sync::Mutex<()>,
    last_input: Mutex<Option<(String, u64, Option<String>)>>,
}
type Completion = Arc<Mutex<Option<Result<(), String>>>>;
fn completion() -> (Completion, impl FnOnce(&brain::ReducerEventContext,
    Result<Result<(), String>, spacetimedb_sdk::__codegen::InternalError>) + Send + 'static) {
    let result=Arc::new(Mutex::new(None)); let copy=result.clone();
    (result, move |_,r| *copy.lock().unwrap()=Some(r.unwrap_or_else(|_|Err("controller connection lost; outcome unknown".into()))))
}
async fn wait(result:Completion)->Result<(),String> {
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if let Some(r)=result.lock().unwrap().take() {return r;}
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    }).await.map_err(|_|"controller receipt timeout; outcome unknown")?
}
impl Controller {
    pub(crate) async fn resume_delivery(&self, world:&ParticipantService)->Result<(),String> {
        let cursor=self.connection.db.my_brain_head().iter().next().map_or(0,|head|head.cursor);
        world.set_delivery_cursor(cursor).await
    }
    pub async fn open(session:Session)->Result<Arc<Self>,String> {
        Self::connect(session, None).await
    }
    pub async fn provision(server:String,database:String,path:&std::path::Path)->Result<Arc<Self>,String> {
        Self::connect(Session {server,database,token:String::new()},Some(path.to_owned())).await
    }
    async fn connect(session:Session,save:Option<std::path::PathBuf>)->Result<Arc<Self>,String> {
        let ready=Arc::new(Mutex::new(false)); let copy=ready.clone();
        let captured=Arc::new(Mutex::new(None)); let token_copy=captured.clone();
        let connection=brain::DbConnection::builder().with_uri(session.server.clone())
            .with_database_name(session.database.clone()).with_token((!session.token.is_empty()).then_some(session.token.clone()))
            .on_connect(move |c,_,token| { *token_copy.lock().unwrap()=Some(token.to_owned()); let copy=copy.clone(); c.subscription_builder()
                .on_applied(move |_| *copy.lock().unwrap()=true)
                .subscribe(["SELECT * FROM my_brain_head", "SELECT * FROM my_brain_outbox",
                    "SELECT * FROM my_brain_receipts", "SELECT * FROM my_brain_reads"]);})
            .build().map_err(|_|"controller connection failed")?;
        connection.run_threaded();
        let controller=Arc::new(Self {connection:Arc::new(connection), session:Mutex::new(session.clone()),
            serial:tokio::sync::Mutex::new(()), last_input:Mutex::new(None)});
        tokio::time::timeout(Duration::from_secs(10),async {
            while !*ready.lock().unwrap() {tokio::time::sleep(Duration::from_millis(10)).await;}
        }).await.map_err(|_|"controller subscription timeout")?;
        controller.session.lock().unwrap().token=captured.lock().unwrap().clone().ok_or("controller token unavailable")?;
        if let Some(path)=save {
            use std::io::Write;
            let mut options=std::fs::OpenOptions::new(); options.create_new(true).write(true);
            #[cfg(unix)] {use std::os::unix::fs::OpenOptionsExt; options.mode(0o600);}
            let mut file=options.open(path).map_err(|_|"new private controller session path required")?;
            let token=captured.lock().unwrap().clone().ok_or("controller token unavailable")?;
            file.write_all(&serde_json::to_vec(&Session {token,..session}).unwrap()).map_err(|_|"controller session write failed")?;
            file.sync_all().map_err(|_|"controller session sync failed")?;
        }
        Ok(controller)
    }
    pub async fn reconnect(&self)->Result<Arc<Self>,String> {
        let session=self.session.lock().unwrap().clone();
        Self::open(session).await
    }
    pub fn current(&self)->Result<Value,String> {
        if !self.connection.is_active() {return Err("controller database disconnected; reconnect with the same private session".into());}
        let h=self.connection.db.my_brain_head().iter().next().ok_or("controller not registered")?;
        if let Some(fault)=h.fault {return Err(fault);}
        Ok(serde_json::json!({"run":h.run,"actor":h.actor,"control_epoch":h.epoch,
            "latest_cursor":h.cursor,"policy_revision":h.policy_revision,"learning_revision":h.learning_revision,
            "stopped":h.stopped,"context":{"player":{"health":h.health}}}))
    }
    pub async fn command(&self,request:&Request)->Result<Receipt,String> {
        let _lock=self.serial.lock().await;
        let (done,callback)=completion();
        self.connection.reducers.brain_command_then(serde_json::to_string(request).unwrap(),callback)
            .map_err(|_|"controller command not sent")?;
        wait(done).await?;
        let r=self.connection.db.my_brain_receipts().iter().find(|r|r.request_id==request.request_id)
            .ok_or("controller receipt missing")?;
        serde_json::from_str(&r.receipt).map_err(|e|e.to_string())
    }
    pub async fn refresh_context(&self,context:Value)->Result<(),String> {
        let _lock=self.serial.lock().await;
        let(done,callback)=completion();
        self.connection.reducers.brain_refresh_context_then(context.to_string(),callback)
            .map_err(|_|"context refresh not sent")?;
        wait(done).await
    }
    pub fn read(&self,id:&str)->Result<Value,String> {
        let r=self.connection.db.my_brain_reads().iter().find(|r|r.request_id==id).ok_or("controller read missing")?;
        serde_json::from_str(&r.observation).map_err(|e|e.to_string())
    }
    /// Synchronize authorized inputs without dispatching. Useful for controlled
    /// controller handoff and for checking a durable outbox before resuming it.
    pub async fn synchronize_inputs(&self,world:&ParticipantService)->Result<(),String> {
        let _lock=self.serial.lock().await;
        self.ingest_inputs(world).await.map(|_|())
    }
    async fn ingest_inputs(&self,world:&ParticipantService)->Result<Frame,String> {
        let f=world.connection.db.sim_my_controller_frame().iter().next().ok_or("no scoped controller frame")?;
        let frame=Frame {run:f.run,actor:f.actor,tick:f.tick,stopped:f.stopped,paused:f.paused,
            control_epoch:f.control_epoch,revision:f.revision,position:f.position,health:f.health,
            hunger:f.hunger,energy:f.energy,food:f.food,fear:f.fear,failures:f.failures,
            action:serde_json::from_str(&f.action).map_err(|e|e.to_string())?,
            body:f.body.as_deref().map(serde_json::from_str).transpose().map_err(|e|e.to_string())?,
            materials:f.materials.as_deref().map(serde_json::from_str).transpose().map_err(|e|e.to_string())?,action_ready_ms:f.action_ready_ms};
        let encoded=serde_json::to_string(&frame).unwrap();
        if self.connection.db.my_brain_head().iter().next().is_none() {
            let seed=world.connection.db.sim_my_controller_bootstrap().iter().next().ok_or("controller bootstrap unavailable")?;
            let(done,callback)=completion();
            self.connection.reducers.brain_register_then(seed.body,encoded.clone(),callback).map_err(|_|"registration not sent")?;
            wait(done).await?;
        }
        let head=self.connection.db.my_brain_head().iter().next().ok_or("controller head unavailable")?;
        if head.run!=frame.run || head.actor!=frame.actor || head.epoch!=frame.control_epoch {
            return Err("controller identity scope changed; explicit handoff required".into());
        }
        if let Some(fault)=head.fault {return Err(fault);}
        let mut experiences:Vec<_>=world.connection.db.sim_my_controller_experiences().iter()
            .filter(|e|e.cursor>head.cursor).map(|e| Ok(Experience {cursor:e.cursor,source:e.source,
                tick:e.tick,location:e.location,kind:e.kind,parents:e.parents,
                data:serde_json::from_str(&e.data).map_err(|e|e.to_string())?}))
            .collect::<Result<_,String>>()?;
        experiences.sort_by_key(|e|e.cursor);
        let holdings=world.connection.db.sim_my_controller_knowledge().iter().next().map(|k|k.holdings);
        let input=(encoded.clone(),experiences.last().map_or(head.cursor,|e|e.cursor),holdings.clone());
        if self.last_input.lock().unwrap().as_ref()!=Some(&input) {
        let(done,callback)=completion();
        self.connection.reducers.brain_ingest_then(encoded,serde_json::to_string(&experiences).unwrap(),holdings,callback)
            .map_err(|_|"controller input not sent")?;
        wait(done).await?;
        *self.last_input.lock().unwrap()=Some(input);
        }
        Ok(frame)
    }
    pub async fn relay_once(&self,world:&ParticipantService)->Result<(),String> {
        let _lock=self.serial.lock().await;
        let frame=self.ingest_inputs(world).await?;
        if let Some(out)=self.connection.db.my_brain_outbox().iter().next() {
            let prior=world.connection.db.sim_my_controller_dispatch().iter()
                .find(|r|r.sequence==out.sequence && r.control_epoch==frame.control_epoch);
            let result=async {
            let receipt=if let Some(r)=prior {
                let receipt:Receipt=serde_json::from_str(&r.receipt).map_err(|_|"invalid dispatch receipt")?;
                if receipt.request_id!=out.request_id {return Err("dispatch receipt request mismatch".into());}
                receipt
            } else {
                // Claimed means a previous process may have sent this request.
                // Replay the exact sequence; the authority's durable high-water
                // mark returns its original result or rejects a superseded ID.
                let request:Request=serde_json::from_str(&out.request).map_err(|e|e.to_string())?;
                let cursor=self.connection.db.my_brain_head().iter().next().ok_or("controller head unavailable")?.cursor;
                world.dispatch_action_after(out.sequence,request,cursor).await?
            };
            let(done,callback)=completion();
            self.connection.reducers.brain_ack_then(serde_json::to_string(&receipt).unwrap(),callback).map_err(|_|"ack not sent")?;
            wait(done).await?;
            Ok::<(),String>(())
            }.await;
            if let Err(error)=result {
                // Another connection for this same controller may already have
                // acknowledged and advanced the outbox. Never apply an old ack
                // to its successor, or stop a healthy relay over that race.
                let unchanged=self.connection.db.my_brain_outbox().iter().any(|r|r.request_id==out.request_id);
                if unchanged || !self.connection.is_active() {return Err(error);}
            }
        }
        Ok(())
    }
}
impl Drop for Controller {
    fn drop(&mut self) {let _=self.connection.disconnect();}
}
