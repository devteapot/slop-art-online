//! Shared application client for built-in harnesses and protocol adapters.
//! Holds only one participant identity. No CLI/operator access, actor arguments or model-provider assumptions.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use shared::module_bindings::{
    sim_participant_command, DbConnection, SimMyParticipantHeadTableAccess,
    SimMyParticipantReceiptsTableAccess, SimMyParticipantReadsTableAccess,
};
use simulation::participant::{Command, Receipt, Request, API_VERSION};
use spacetimedb_sdk::{DbContext, Table};
use std::{
    path::Path,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
const SUBSCRIPTIONS: [&str; 3] = [
    "SELECT * FROM sim_my_participant_head",
    "SELECT * FROM sim_my_participant_receipts",
    "SELECT * FROM sim_my_participant_reads",
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
}
impl ParticipantService {
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
            })
        })
        .await
        .map_err(|_| "connection worker failed")?
    }
    /// Resume the same identity after a transport failure. Never create a grant,
    /// change controllers or replay a possibly completed command.
    pub async fn reconnect_if_needed(&mut self) -> Result<bool, String> {
        if self.connection.is_active() { return Ok(false); }
        let replacement = Self::open((*self.session).clone()).await?;
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
        Self::open(session).await
    }
    pub fn current(&self) -> Result<Value, String> {
        if !self.connection.is_active() {
            return Err(
                "participant connection disconnected; reconnect with same session file".into(),
            );
        }
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
            "capabilities":["read_observation","replace_tree","patch_subtree","speak","reflect","pin_observation"]}))
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
        let receipt = self.command(Request {
            api_version: API_VERSION.into(), request_id: request_id.clone(),
            control_epoch: head.control_epoch, command: Command::ReadObservation { after, limit },
        }).await?;
        if !receipt.ok { return Err(receipt.error.unwrap_or_else(|| "read rejected".into())); }
        let read = self.connection.db.sim_my_participant_reads().iter()
            .filter(|r| r.request_id == request_id && r.control_epoch == head.control_epoch)
            .max_by_key(|r| r.sequence)
            .ok_or("atomic read no longer retained; refresh")?;
        serde_json::from_str(&read.observation).map_err(|_| "invalid atomic observation".into())
    }
    pub async fn command(&self, request: Request) -> Result<Receipt, String> {
        let id = request.request_id.clone();
        let response = Arc::new(Mutex::new(None));
        let copy = response.clone();
        self.connection
            .reducers
            .sim_participant_command_then(
                serde_json::to_string(&request).map_err(|e| e.to_string())?,
                move |_, r| {
                    *copy.lock().unwrap() = Some(match r {
                        Ok(Ok(())) => Ok(()),
                        Ok(Err(e)) => Err(e),
                        Err(_) => Err(
                            "authority connection lost; outcome unknown, retry same request ID"
                                .into(),
                        ),
                    });
                },
            )
            .map_err(|_| "command not sent")?;
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            if let Some(result) = response.lock().unwrap().clone() {
                result?;
                if let Some(r) = self.connection.db.sim_my_participant_receipts().iter()
                    .find(|r| r.request_id == id) {
                    return Ok(Receipt { request_id:r.request_id, fingerprint:r.fingerprint,
                        ok:r.ok, error:r.error, event:r.event });
                }
            }
            if Instant::now() >= deadline {
                return Err("receipt timeout; outcome unknown, retry same request ID".into());
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    }
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
        },
        identity,
    ))
}
