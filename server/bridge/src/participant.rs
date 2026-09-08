//! Shared application client for built-in harnesses and protocol adapters.
//! Holds only one participant identity. No CLI/operator access, actor arguments or model-provider assumptions.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use shared::module_bindings::{
    sim_participant_command, sim_dispatch_controller_action, DbConnection, SimMyParticipantHeadTableAccess, SimMyControllerFrameTableAccess,
    SimMyControllerDispatchTableAccess,
    sim_dispatch_controller_action_after, sim_set_controller_delivery_cursor,
    SimMyParticipantReceiptsTableAccess, SimMyParticipantReadsTableAccess,
};
use simulation::participant::{Command, Receipt, Request, API_VERSION};
use spacetimedb_sdk::{DbContext, Table};
use std::{
    path::Path,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
const SUBSCRIPTIONS: [&str; 8] = [
    "SELECT * FROM sim_my_participant_head",
    "SELECT * FROM sim_my_participant_receipts",
    "SELECT * FROM sim_my_participant_reads",
    "SELECT * FROM sim_my_controller_bootstrap",
    "SELECT * FROM sim_my_controller_frame",
    "SELECT * FROM sim_my_controller_experiences",
    "SELECT * FROM sim_my_controller_knowledge",
    "SELECT * FROM sim_my_controller_dispatch",
];
#[derive(Clone, Serialize, Deserialize)]
pub struct Session {
    pub server: String,
    pub database: String,
    pub token: String,
}
#[derive(Clone)]
pub struct ParticipantService {
    pub connection: Arc<DbConnection>,
    session: Arc<Session>,
    controller: Option<Arc<crate::controller::Controller>>,
    relay: Option<Arc<RelayTask>>,
}
struct RelayTask {
    task: tokio::task::JoinHandle<()>,
    error: Arc<Mutex<Option<String>>>,
}
impl Drop for RelayTask {fn drop(&mut self) {self.task.abort();}}
impl ParticipantService {
    /// Optional personal combat notifications. Keep the returned handle while
    /// watching `sim_my_combat_events` in the SDK cache. Cursors may have gaps:
    /// this filtered channel does not replace the ordered controller trace.
    pub async fn subscribe_combat_events(&self) -> Result<shared::module_bindings::SubscriptionHandle, String> {
        let (send, receive)=tokio::sync::oneshot::channel();
        let send=Arc::new(Mutex::new(Some(send)));
        let applied=send.clone();
        let handle=self.connection.subscription_builder()
            .on_applied(move |_| { if let Some(send)=applied.lock().unwrap().take() {let _=send.send(Ok(()));} })
            .on_error(move |_,_| {if let Some(send)=send.lock().unwrap().take() {let _=send.send(Err("combat subscription failed".to_string()));}})
            .subscribe("SELECT * FROM sim_my_combat_events");
        match tokio::time::timeout(Duration::from_secs(10),receive).await {
            Ok(Ok(Ok(()))) => Ok(handle),
            result => {
                use spacetimedb_sdk::SubscriptionHandle as _;
                let _=handle.unsubscribe();
                Err(match result {Ok(Ok(Err(error)))=>error,_=>"combat subscription timeout/disconnected".into()})
            }
        }
    }
    async fn wait_controller_frame(&self)->Result<(),String> {
        use shared::module_bindings::SimMyControllerFrameTableAccess;
        let deadline=Instant::now()+Duration::from_secs(10);
        while self.connection.db.sim_my_controller_frame().iter().next().is_none() {
            if Instant::now()>=deadline {return Err("world controller subscription timeout".into());}
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        Ok(())
    }
    pub async fn open(session: Session) -> Result<Self, String> {
        let reconnect_session = Arc::new(session.clone());
        tokio::task::spawn_blocking(move || {
            let conn = DbConnection::builder()
                .with_uri(session.server)
                .with_database_name(session.database)
                .with_token(Some(session.token))
                .on_connect(|c, _, _| {
                    c.subscription_builder()
                        .subscribe(SUBSCRIPTIONS);
                })
                .build()
                .map_err(|_| "participant authority unavailable")?;
            conn.run_threaded();
            Ok(Self {
                connection: Arc::new(conn),
                session: reconnect_session,
                controller: None,
                relay: None,
            })
        })
        .await
        .map_err(|_| "connection worker failed")?
    }
    /// Attach the separately provisioned native mind using its private session.
    pub async fn attach_controller(&mut self, session: Session) -> Result<(), String> {
        let controller=crate::controller::Controller::open(session).await?;
        self.attach_open_controller(controller).await
    }
    pub async fn attach_open_controller(&mut self,controller:Arc<crate::controller::Controller>)->Result<(),String> {
        controller.resume_delivery(self).await?;
        controller.relay_once(self).await?;
        self.controller=Some(controller.clone());
        let mut world=self.clone(); world.controller=None; world.relay=None;
        let error=Arc::new(Mutex::new(None));let failure=error.clone();
        let task=tokio::spawn(async move {
            let mut delay=Duration::from_millis(50);
            loop {
                tokio::time::sleep(delay).await;
                if let Err(error)=controller.relay_once(&world).await {
                    let retry=world.connection.is_active() && controller.connection.is_active()
                        && retryable_relay_error(&error);
                    if failure.lock().unwrap().as_ref()!=Some(&error) {
                        eprintln!("native controller relay {}: {error}",if retry {"retrying"} else {"stopped"});
                    }
                    *failure.lock().unwrap()=Some(error);
                    if !retry {break;}
                    delay=(delay*2).min(Duration::from_secs(5));
                } else {
                    if failure.lock().unwrap().take().is_some() {eprintln!("native controller relay recovered");}
                    delay=Duration::from_millis(50);
                }
            }
        });
        self.relay=Some(Arc::new(RelayTask {task,error}));
        Ok(())
    }
    pub async fn relay_controller(&self)->Result<(),String> {
        match &self.controller {Some(c)=>c.relay_once(self).await,None=>Ok(())}
    }
    /// Stop this process's relay task without closing its transports. Supervisors
    /// may call reconnect_if_needed to resume the same durable pending command.
    pub async fn interrupt_controller_relay(&self) {
        if let Some(relay)=&self.relay {
            relay.task.abort();
            while !relay.task.is_finished() {tokio::task::yield_now().await;}
        }
    }
    /// Resume the same identity after a transport or relay-task failure. Pending
    /// actions retain their durable dispatch sequence; no grant or handoff occurs.
    pub async fn reconnect_if_needed(&mut self) -> Result<bool, String> {
        let world_active=self.connection.is_active();
        let brain_active=self.controller.as_ref().is_none_or(|c|c.connection.is_active());
        let relay_stopped=self.relay.as_ref().is_some_and(|r|r.task.is_finished());
        if world_active && brain_active && !relay_stopped { return Ok(false); }
        let mut replacement = if world_active {self.clone()} else {Self::open((*self.session).clone()).await?};
        if let Some(c)=&self.controller {
            replacement.wait_controller_frame().await?;
            let controller=if brain_active {c.clone()} else {c.reconnect().await?};
            replacement.attach_open_controller(controller).await?;
        }
        if let Err(error) = replacement.observe(0, 1).await {
            let _ = replacement.connection.disconnect();
            return Err(error);
        }
        *self = replacement;
        Ok(true)
    }
    pub async fn from_file(path: &Path) -> Result<Self, String> {
        let session: Session = serde_json::from_slice(
            &std::fs::read(path).map_err(|_| "participant session file unavailable")?,
        )
        .map_err(|_| "invalid session file")?;
        let mut service=Self::open(session).await?;
        let brain_path=path.with_extension("controller.json");
        if brain_path.exists() {
            let brain=serde_json::from_slice(&std::fs::read(brain_path).map_err(|_|"controller session unavailable")?)
                .map_err(|_|"invalid controller session")?;
            // Wait for world subscriptions before attaching its controller.
            service.wait_controller_frame().await?;
            service.attach_controller(brain).await?;
        }
        Ok(service)
    }
    pub fn current(&self) -> Result<Value, String> {
        if !self.connection.is_active() {
            return Err(
                "participant connection disconnected; reconnect with same session file".into(),
            );
        }
        if let Some(relay)=&self.relay {
            if let Some(error)=relay.error.lock().unwrap().as_ref() {return Err(format!("controller relay stopped: {error}"));}
        }
        if let Some(c)=&self.controller {return c.current();}
        let h = self
            .connection
            .db
            .sim_my_participant_head()
            .iter()
            .next()
            .ok_or("no participant grant or subscription not ready")?;
        let mut receipts: Vec<_> = self.connection.db.sim_my_participant_receipts().iter()
            .map(|r| Receipt { request_id:r.request_id, fingerprint:r.fingerprint,
                ok:r.ok,error:r.error,event:r.event }).collect();
        receipts.sort_by_key(|r| r.event);
        let mut reads: Vec<_> = self.connection.db.sim_my_participant_reads().iter().collect();
        reads.sort_by_key(|r| r.sequence);
        let reads = reads.into_iter().map(|r| {
            let observation: Value = serde_json::from_str(&r.observation).map_err(|_| "invalid authority read")?;
            Ok(json!({"request_id":r.request_id,"observation":observation}))
        }).collect::<Result<Vec<_>, String>>()?;
        // Compatibility assembly for diagnostic callers. Each read response is
        // immutable and atomic; this live header is not a new captured context.
        Ok(json!({"api_version":API_VERSION,"projection":"status; use read_observation for fresh subjective state",
            "run":h.run,"actor":h.actor,"tick":h.tick,"stopped":h.stopped,
            "latest_cursor":h.latest_cursor,"oldest_cursor":h.oldest_cursor,
            "control_epoch":h.control_epoch,"policy_revision":h.policy_revision,"learning_revision":h.learning_revision,
            "context":{"player":{"health":h.health}},"receipts":receipts,"read_observations":reads,
            "capabilities":if self.connection.db.sim_my_controller_frame().iter().next().is_some() {vec!["read_observation","pin_observation","start_action","cancel_action","speak","publish_knowledge"]} else {vec!["read_observation","replace_tree","patch_subtree","speak","reflect","pin_observation"]}}))
    }
    pub async fn observe(&self, after: u64, limit: usize) -> Result<Value, String> {
        let deadline = Instant::now() + Duration::from_secs(5);
        let head = loop {
            if !self.connection.is_active() {
                return Err("participant connection disconnected".into());
            }
            if let Some(head) = self.connection.db.sim_my_participant_head().iter().next() {
                break head;
            }
            if Instant::now() >= deadline {
                return Err("no participant grant or subscription not ready".into());
            }
            tokio::time::sleep(Duration::from_millis(15)).await;
        };
        let nonce = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| "clock unavailable")?.as_nanos();
        let request_id = format!("read-{nonce}");
        if let Some(c)=&self.controller {
            let physical_id=format!("facts-{nonce}");
            let receipt=self.authority_command(Request {api_version:API_VERSION.into(),
                request_id:physical_id.clone(),control_epoch:head.control_epoch,
                command:Command::ReadObservation {after:0,limit:256}}).await?;
            if !receipt.ok {return Err(receipt.error.unwrap_or_else(||"physical context read rejected".into()));}
            let read=self.connection.db.sim_my_participant_reads().iter().find(|r|r.request_id==physical_id)
                .ok_or("physical context read missing")?;
            let observation:Value=serde_json::from_str(&read.observation).map_err(|_|"invalid physical context")?;
            c.refresh_context(observation["context"].clone()).await?;
        }
        let receipt = self.command(Request {
            api_version: API_VERSION.into(), request_id: request_id.clone(),
            control_epoch: head.control_epoch, command: Command::ReadObservation { after, limit },
        }).await?;
        if !receipt.ok { return Err(receipt.error.unwrap_or_else(|| "read rejected".into())); }
        if let Some(c)=&self.controller {return c.read(&request_id);}
        let read = self.connection.db.sim_my_participant_reads().iter()
            .filter(|r| r.request_id == request_id && r.control_epoch == head.control_epoch)
            .max_by_key(|r| r.sequence)
            .ok_or("atomic read no longer retained; refresh")?;
        serde_json::from_str(&read.observation).map_err(|_| "invalid atomic observation".into())
    }
    pub async fn command(&self, request: Request) -> Result<Receipt, String> {
        if let Some(c)=&self.controller {
            if matches!(&request.command,Command::ReadObservation {..}|Command::PinObservation {..}
                |Command::ReplaceTree {..}|Command::PatchSubtree {..}|Command::Reflect {..}) {
                return c.command(&request).await;
            }
        }
        self.authority_command(request).await
    }
    pub(crate) async fn authority_command(&self, request: Request) -> Result<Receipt, String> {
        self.send_authority(request,None,None).await
    }
    /// A persistent sequence makes retransmission safe after both receipt loss
    /// and a crash before sending. The world atomically stores the command result.
    pub async fn dispatch_action(&self, sequence:u64, request:Request)->Result<Receipt,String> {
        self.send_authority(request,Some(sequence),None).await
    }
    pub(crate) async fn dispatch_action_after(&self, sequence:u64, request:Request, cursor:u64)->Result<Receipt,String> {
        self.send_authority(request,Some(sequence),Some(cursor)).await
    }
    pub(crate) async fn set_delivery_cursor(&self, cursor:u64)->Result<(),String> {
        let (sent,received)=tokio::sync::oneshot::channel();
        self.connection.reducers.sim_set_controller_delivery_cursor_then(cursor,move |_,result| {
            let _=sent.send(result.unwrap_or_else(|_|Err("delivery cursor connection lost; outcome unknown".into())));
        }).map_err(|_|"delivery cursor not sent")?;
        tokio::time::timeout(Duration::from_secs(10),received).await
            .map_err(|_|"delivery cursor timeout; outcome unknown")?.map_err(|_|"delivery cursor callback dropped")?
    }
    async fn send_authority(&self, request:Request, sequence:Option<u64>, cursor:Option<u64>)->Result<Receipt,String> {
        let id = request.request_id.clone();
        let response = Arc::new(Mutex::new(None));
        let copy = response.clone();
        let callback=move |_: &shared::module_bindings::ReducerEventContext, r: Result<Result<(),String>,spacetimedb_sdk::__codegen::InternalError>| {
                    *copy.lock().unwrap() = Some(match r {
                        Ok(Ok(())) => Ok(()),
                        Ok(Err(e)) => Err(e),
                        Err(_) => Err(
                            "authority connection lost; outcome unknown, retry same request ID"
                                .into(),
                        ),
                    });
                };
        let encoded=serde_json::to_string(&request).map_err(|e|e.to_string())?;
        match sequence {
            Some(n) if cursor.is_some()=>self.connection.reducers.sim_dispatch_controller_action_after_then(n,encoded,cursor.unwrap(),callback),
            Some(n)=>self.connection.reducers.sim_dispatch_controller_action_then(n,encoded,callback),
            None=>self.connection.reducers.sim_participant_command_then(encoded,callback),
        }.map_err(|_|"command not sent")?;
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            if let Some(result) = response.lock().unwrap().clone() {
                result?;
                if let Some(n)=sequence {
                    if let Some(r)=self.connection.db.sim_my_controller_dispatch().iter()
                        .find(|r|r.sequence==n && r.control_epoch==request.control_epoch) {
                        let receipt:Receipt=serde_json::from_str(&r.receipt).map_err(|_|"invalid dispatch receipt")?;
                        if receipt.request_id!=id {return Err("dispatch receipt request mismatch".into());}
                        return Ok(receipt);
                    }
                } else {
                if let Some(r) = self.connection.db.sim_my_participant_receipts().iter()
                    .find(|r| r.request_id == id) {
                    return Ok(Receipt { request_id:r.request_id, fingerprint:r.fingerprint,
                        ok:r.ok, error:r.error, event:r.event });
                }
                }
            }
            if Instant::now() >= deadline {
                return Err("receipt timeout; outcome unknown, retry same request ID".into());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }
}

fn retryable_relay_error(error:&str)->bool {
    error.contains("timeout") || error.contains("connection lost") || error.ends_with("not sent")
        || matches!(error,"controller receipt missing"|"dispatch receipt missing")
}

/// Operator setup ONLY: create an ungranted anonymous identity and retain its own token privately.
/// This performs no grant or world mutation; callers must provision through the separate owner reducer.
pub async fn new_session(
    server: String,
    database: String,
    path: &Path,
) -> Result<(ParticipantService, String), String> {
    let captured = Arc::new(Mutex::new(None));
    let copy = captured.clone();
    let config_server = server.clone();
    let config_db = database.clone();
    let conn = tokio::task::spawn_blocking(move || {
        DbConnection::builder()
            .with_uri(server)
            .with_database_name(database)
            .on_connect(move |c, id, token| {
                *copy.lock().unwrap() = Some((id.to_hex().to_string(), token.to_string()));
                c.subscription_builder()
                    .subscribe(SUBSCRIPTIONS);
            })
            .build()
            .map_err(|_| "new participant connection failed")
    })
    .await
    .map_err(|_| "connection worker failed")??;
    conn.run_threaded();
    let deadline = Instant::now() + Duration::from_secs(8);
    let (identity, token) = loop {
        if let Some(c) = captured.lock().unwrap().clone() {
            break c;
        }
        if Instant::now() > deadline {
            return Err("identity handshake timeout".into());
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    };
    use std::io::Write;
    let mut options = std::fs::OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options
        .open(path)
        .map_err(|_| "new private session path required")?;
    let session = Arc::new(Session {
            server: config_server,
            database: config_db,
            token,
        });
    file.write_all(&serde_json::to_vec(&*session).unwrap())
    .map_err(|_| "session write failed")?;
    Ok((
        ParticipantService {
            connection: Arc::new(conn),
            session,
            controller: None,
            relay: None,
        },
        identity,
    ))
}
