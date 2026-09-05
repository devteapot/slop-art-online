//! Shared application client for built-in harnesses and protocol adapters.
//! Holds only one participant identity. No CLI/operator access, actor arguments or model-provider assumptions.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use shared::module_bindings::{
    sim_participant_command, DbConnection, SimParticipantStateTableAccess,
};
use simulation::participant::{Receipt, Request};
use spacetimedb_sdk::{DbContext, Table};
use std::{
    path::Path,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
#[derive(Clone, Serialize, Deserialize)]
pub struct Session {
    pub server: String,
    pub database: String,
    pub token: String,
}
#[derive(Clone)]
pub struct ParticipantService {
    pub connection: Arc<DbConnection>,
}
impl ParticipantService {
    pub async fn open(session: Session) -> Result<Self, String> {
        tokio::task::spawn_blocking(move || {
            let conn = DbConnection::builder()
                .with_uri(session.server)
                .with_database_name(session.database)
                .with_token(Some(session.token))
                .on_connect(|c, _, _| {
                    c.subscription_builder()
                        .subscribe(["SELECT * FROM sim_participant_state"]);
                })
                .build()
                .map_err(|_| "participant authority unavailable")?;
            conn.run_threaded();
            Ok(Self {
                connection: Arc::new(conn),
            })
        })
        .await
        .map_err(|_| "connection worker failed")?
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
        let body = self
            .connection
            .db
            .sim_participant_state()
            .iter()
            .next()
            .ok_or("no participant grant or subscription not ready")?
            .body;
        serde_json::from_str(&body).map_err(|_| "invalid authority response".into())
    }
    pub async fn observe(&self, after: u64, limit: usize) -> Result<Value, String> {
        let deadline = Instant::now() + Duration::from_secs(5);
        let mut v = loop {
            match self.current() {
                Ok(v) => break v,
                Err(e) if Instant::now() >= deadline => return Err(e),
                _ => tokio::time::sleep(Duration::from_millis(15)).await,
            }
        };
        if after > v["latest_cursor"].as_u64().unwrap_or(0) {
            return Err("cursor ahead of character trace".into());
        }
        let entries: Vec<Value> = v["experiences"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|e| e["cursor"].as_u64().unwrap() > after)
            .take(limit.clamp(1, 256))
            .cloned()
            .collect();
        let next = entries
            .last()
            .and_then(|e| e["cursor"].as_u64())
            .unwrap_or(after);
        v["next_cursor"] = json!(next);
        v["gap"] = json!(after.saturating_add(1) < v["oldest_cursor"].as_u64().unwrap_or(1));
        v["experiences"] = json!(entries);
        Ok(v)
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
                if let Ok(v) = self.current() {
                    if let Some(r) = v["receipts"]
                        .as_array()
                        .and_then(|rs| rs.iter().find(|r| r["request_id"] == id))
                    {
                        return serde_json::from_value(r.clone())
                            .map_err(|_| "invalid command receipt".into());
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
                    .subscribe(["SELECT * FROM sim_participant_state"]);
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
    file.write_all(
        &serde_json::to_vec(&Session {
            server: config_server,
            database: config_db,
            token,
        })
        .unwrap(),
    )
    .map_err(|_| "session write failed")?;
    Ok((
        ParticipantService {
            connection: Arc::new(conn),
        },
        identity,
    ))
}
