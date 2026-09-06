//! One MCP transport for one actor. The reader owns framing across caller deadlines.
use super::admission::Admission;
use serde_json::{json, Value};
use std::{
    path::Path,
    process::Stdio,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncRead, AsyncWrite, AsyncWriteExt, BufReader},
    process::Child,
    sync::{oneshot, watch},
    task::JoinHandle,
};

type Reply = Result<Value, String>;
#[derive(Default)]
struct State {
    issued: u64,
    pending: Option<(u64, oneshot::Sender<Reply>)>,
    fatal: Option<String>,
    late_responses: u64,
}
impl State {
    fn fail(&mut self, error: &str) {
        self.fatal.get_or_insert_with(|| error.into());
        if let Some((_, sender)) = self.pending.take() {
            let _ = sender.send(Err(error.into()));
        }
    }
    fn receive(&mut self, value: Value) {
        if value["jsonrpc"] != "2.0" {
            self.fail("invalid MCP protocol frame");
            return;
        }
        if value.get("id").is_none() && value["method"].is_string() {
            return;
        }
        let Some(id) = value["id"]
            .as_u64()
            .filter(|id| *id > 0 && *id <= self.issued)
        else {
            self.fail("invalid or unissued MCP response ID");
            return;
        };
        if value.get("result").is_some() == value.get("error").is_some() {
            self.fail("invalid MCP response envelope");
            return;
        }
        if let Some(error) = value.get("error") {
            if error["code"].as_i64().is_none() || !error["message"].is_string() {
                self.fail("invalid MCP error envelope");
                return;
            }
        }
        if self
            .pending
            .as_ref()
            .is_some_and(|(pending, _)| *pending == id)
        {
            let (_, sender) = self.pending.take().unwrap();
            let reply = if let Some(error) = value.get("error") {
                Err(error.to_string())
            } else {
                Ok(value["result"].clone())
            };
            let _ = sender.send(reply);
        } else {
            // Retired responses are discarded, never added to a subsequent actor context.
            self.late_responses += 1;
        }
    }
}

pub struct Transport<W> {
    input: W,
    state: Arc<Mutex<State>>,
    reader: JoinHandle<()>,
    deadline: Duration,
    events: Vec<Value>,
    admission: Option<Arc<Admission>>,
    last_flushed_unix_ms: Option<u128>,
}
impl<W: AsyncWrite + Unpin> Transport<W> {
    fn new<R: AsyncRead + Unpin + Send + 'static>(input: W, output: R, deadline: Duration) -> Self {
        let state = Arc::new(Mutex::new(State::default()));
        let reader_state = state.clone();
        let reader = tokio::spawn(async move {
            let mut lines = BufReader::new(output).lines();
            loop {
                let result = lines.next_line().await;
                let mut state = reader_state.lock().unwrap();
                match result {
                    Ok(Some(line)) => match serde_json::from_str(&line) {
                        Ok(value) => state.receive(value),
                        Err(_) => state.fail("invalid MCP JSON frame"),
                    },
                    Ok(None) => state.fail("MCP EOF"),
                    Err(_) => state.fail("MCP read failed"),
                }
                if state.fatal.is_some() {
                    break;
                }
            }
        });
        Self {
            input,
            state,
            reader,
            deadline,
            events: Vec::new(),
            admission: None,
            last_flushed_unix_ms: None,
        }
    }
    pub fn reusable(&self) -> bool {
        self.state.lock().unwrap().fatal.is_none()
    }
    pub fn audit(&self) -> Value {
        let state = self.state.lock().unwrap();
        json!({"issued_rpc_ids":state.issued,"discarded_late_responses":state.late_responses,"fatal":state.fatal,"requests":self.events})
    }
    pub fn begin_job(&mut self) {
        self.events.clear();
    }
    pub async fn rpc(
        &mut self,
        method: &str,
        params: Value,
        cancel: &mut watch::Receiver<Option<String>>,
    ) -> Reply {
        let deadline = tokio::time::Instant::now() + self.deadline;
        let started = std::time::Instant::now();
        let at = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        let before = self.state.lock().unwrap().issued;
        let tool = params
            .get("name")
            .and_then(Value::as_str)
            .map(str::to_owned);
        self.last_flushed_unix_ms = None;
        let mut admission_audit = json!({"admission_wait_ms":0,"admission_slot":null,"admission_count":self.admission.as_ref().map(|a| a.count()),"admission_outcome":if self.admission.is_none() {"disabled"} else {"not_required"}});
        let result = self
            .rpc_inner(method, params, cancel, deadline, &mut admission_audit)
            .await;
        let after = self.state.lock().unwrap().issued;
        self.events.push(json!({"id":if after > before { Some(after) } else { None },"method":method,"tool":tool,"started_unix_ms":at,"flushed_unix_ms":self.last_flushed_unix_ms,"elapsed_ms":started.elapsed().as_millis(),"deadline_ms":self.deadline.as_millis(),"ok":result.is_ok(),"outcome":if result.is_ok() { "returned" } else if cancel.borrow().is_some() { "cancelled" } else if result.as_ref().err().is_some_and(|error| error.contains("deadline")) { "deadline" } else if !self.reusable() { "transport_failed" } else { "request_failed" }}));
        let event = self.events.last_mut().unwrap().as_object_mut().unwrap();
        event.extend(admission_audit.as_object().unwrap().clone());
        event.insert(
            "delivery_unknown".into(),
            json!(after > before && result.is_err()),
        );
        if after == before && method == "tools/call" && self.admission.is_some() {
            match event["admission_outcome"].as_str() {
                Some("deadline") => {
                    event.insert("outcome".into(), json!("admission_deadline"));
                }
                Some("cancelled") => {
                    event.insert("outcome".into(), json!("admission_cancelled"));
                }
                _ => (),
            }
        }
        result
    }
    async fn rpc_inner(
        &mut self,
        method: &str,
        mut params: Value,
        cancel: &mut watch::Receiver<Option<String>>,
        deadline: tokio::time::Instant,
        admission_audit: &mut Value,
    ) -> Reply {
        if cancel.borrow().is_some() {
            return Err("cancelled before MCP request".into());
        }
        {
            let state = self.state.lock().unwrap();
            if let Some(error) = &state.fatal {
                return Err(error.clone());
            }
            if state.pending.is_some() {
                return Err("concurrent MCP request prohibited".into());
            }
        }
        let _permit = if method == "tools/call" {
            if let Some(admission) = &self.admission {
                let start = std::time::Instant::now();
                let result = admission.acquire(deadline, cancel).await;
                admission_audit["admission_wait_ms"] = json!(start.elapsed().as_millis());
                match result {
                    Ok(permit) => {
                        admission_audit["admission_slot"] = json!(permit.slot);
                        admission_audit["admission_outcome"] = json!("acquired");
                        Some(permit)
                    }
                    Err(error) => {
                        admission_audit["admission_outcome"] =
                            json!(if error.contains("cancelled") {
                                "cancelled"
                            } else if error.contains("deadline") {
                                "deadline"
                            } else {
                                "failed"
                            });
                        return Err(error.into());
                    }
                }
            } else {
                None
            }
        } else {
            None
        };
        if cancel.borrow().is_some() {
            return Err("cancelled before MCP request".into());
        }
        if tokio::time::Instant::now() >= deadline {
            return Err("MCP deadline before request; request not sent".into());
        }
        let (sender, receiver) = oneshot::channel();
        let id = {
            let mut state = self.state.lock().unwrap();
            if let Some(error) = &state.fatal {
                return Err(error.clone());
            }
            if state.pending.is_some() {
                return Err("concurrent MCP request prohibited".into());
            }
            let id = state.issued.checked_add(1).ok_or("MCP ID exhausted")?;
            state.issued = id;
            state.pending = Some((id, sender));
            id
        };
        params["_meta"] = json!({"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"sao-bounded-live-rust-agent","version":"1"},"io.modelcontextprotocol/clientCapabilities":{}});
        let frame = format!(
            "{}\n",
            json!({"jsonrpc":"2.0","id":id,"method":method,"params":params})
        );
        let write = async {
            self.input.write_all(frame.as_bytes()).await?;
            self.input.flush().await
        };
        let written = tokio::select! {
            biased;
            _ = cancel.changed() => Err("MCP write cancelled; delivery unknown"),
            _ = tokio::time::sleep_until(deadline) => Err("MCP write deadline; delivery unknown"),
            result = write => result.map_err(|_| "MCP write failed; delivery unknown"),
        };
        if let Err(error) = written {
            self.state.lock().unwrap().fail(error);
            return Err(error.into());
        }
        self.last_flushed_unix_ms = Some(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis(),
        );
        let result = tokio::select! {
            biased;
            _ = cancel.changed() => Err("MCP request cancelled; delivery unknown".into()),
            _ = tokio::time::sleep_until(deadline) => Err("MCP response deadline; delivery unknown".into()),
            result = receiver => result.unwrap_or_else(|_| Err("MCP response channel closed".into())),
        };
        // The frame is fully written, so the long-lived reader can safely drain a late reply.
        let mut state = self.state.lock().unwrap();
        if state
            .pending
            .as_ref()
            .is_some_and(|(pending, _)| *pending == id)
        {
            state.pending.take();
        }
        result
    }
    pub async fn call(
        &mut self,
        name: &str,
        args: Value,
        cancel: &mut watch::Receiver<Option<String>>,
    ) -> Reply {
        let r = self
            .rpc("tools/call", json!({"name":name,"arguments":args}), cancel)
            .await?;
        let value = if let Some(s) = r.get("structuredContent") {
            s.clone()
        } else {
            serde_json::from_str(
                r["content"][0]["text"]
                    .as_str()
                    .ok_or("MCP result missing")?,
            )
            .map_err(|_| "invalid MCP tool result")?
        };
        if let Some(event) = self.events.last_mut() {
            event["tool_is_error"] = json!(r["isError"] == true);
            if r["isError"] == true {
                event["delivery_unknown"] = json!(true);
            }
        }
        if r["isError"] == true {
            return Err(value.to_string());
        }
        Ok(value)
    }
}
impl<W> Drop for Transport<W> {
    fn drop(&mut self) {
        self.reader.abort();
    }
}

pub struct Mcp {
    pub transport: Transport<tokio::process::ChildStdin>,
    child: Child,
    instance: String,
    started_unix_ms: u128,
    pid: Option<u32>,
}
impl Mcp {
    pub fn spawn(session: &Path, admission: Option<Arc<Admission>>) -> Result<Self, String> {
        let mut child = tokio::process::Command::new("target/debug/sao-agent-mcp")
            .env("SAO_PARTICIPANT_SESSION", session)
            .env_remove("CARLID_NPC_API_KEY")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .spawn()
            .map_err(|_| "cannot launch MCP")?;
        let input = child.stdin.take().ok_or("MCP input missing")?;
        let output = child.stdout.take().ok_or("MCP output missing")?;
        let mut transport = Transport::new(input, output, Duration::from_secs(15));
        transport.admission = admission;
        Ok(Self {
            transport,
            pid: child.id(),
            child,
            instance: format!("{:032x}", rand::random::<u128>()),
            started_unix_ms: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis(),
        })
    }
    pub fn audit(&self) -> Value {
        let mut audit = self.transport.audit();
        audit["pid"] = json!(self.pid);
        audit["instance"] = json!(self.instance);
        audit["started_unix_ms"] = json!(self.started_unix_ms);
        audit
    }
    pub async fn close(mut self) -> Result<(), String> {
        self.transport.state.lock().unwrap().fail("MCP closed");
        self.child.start_kill().map_err(|_| "MCP kill failed")?;
        tokio::time::timeout(Duration::from_secs(3), self.child.wait())
            .await
            .map_err(|_| "MCP reap deadline")?
            .map_err(|_| "MCP reap failed")?;
        self.transport.reader.abort();
        let _ = (&mut self.transport.reader).await;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn partial_late_frame_is_drained_without_cross_job_response() {
        let (client, server) = tokio::io::duplex(4096);
        let (read, write) = tokio::io::split(client);
        let mut rpc = Transport::new(write, read, Duration::from_millis(40));
        let (_keep, mut cancel) = watch::channel(None);
        let server = tokio::spawn(async move {
            let (read, mut write) = tokio::io::split(server);
            let mut lines = BufReader::new(read).lines();
            let first: Value =
                serde_json::from_str(&lines.next_line().await.unwrap().unwrap()).unwrap();
            assert_eq!(first["id"], 1);
            write
                .write_all(b"{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":")
                .await
                .unwrap();
            tokio::time::sleep(Duration::from_millis(60)).await;
            write
                .write_all(b"{\"private_old_context\":true}}\n")
                .await
                .unwrap();
            let second: Value =
                serde_json::from_str(&lines.next_line().await.unwrap().unwrap()).unwrap();
            assert_eq!(second["id"], 2);
            write
                .write_all(b"{\"jsonrpc\":\"2.0\",\"id\":2,\"result\":\"fresh\"}\n")
                .await
                .unwrap();
            tokio::time::sleep(Duration::from_millis(50)).await;
        });
        assert!(rpc
            .rpc("observe", json!({}), &mut cancel)
            .await
            .unwrap_err()
            .contains("deadline"));
        assert!(rpc.reusable());
        assert_eq!(
            rpc.rpc("observe", json!({}), &mut cancel).await.unwrap(),
            "fresh"
        );
        assert_eq!(rpc.audit()["discarded_late_responses"], 1);
        server.await.unwrap();
    }
    #[tokio::test]
    async fn partial_write_cancellation_poisons_transport() {
        let (client, _server) = tokio::io::duplex(1);
        let (read, write) = tokio::io::split(client);
        let mut rpc = Transport::new(write, read, Duration::from_secs(1));
        let (sender, mut cancel) = watch::channel(None);
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(10)).await;
            sender.send(Some("stop".into())).unwrap();
        });
        assert!(rpc
            .rpc("observe", json!({}), &mut cancel)
            .await
            .unwrap_err()
            .contains("write cancelled"));
        assert!(!rpc.reusable());
    }
    #[tokio::test]
    async fn admission_deadline_and_cancel_issue_no_request() {
        for cancelled in [false, true] {
            let (root, admission) = super::super::admission::tests::fixture(1);
            let (_keep, mut holder_cancel) = watch::channel(None);
            let permit = admission
                .acquire(
                    tokio::time::Instant::now() + Duration::from_secs(1),
                    &mut holder_cancel,
                )
                .await
                .unwrap();
            let (client, _server) = tokio::io::duplex(4096);
            let (read, write) = tokio::io::split(client);
            let mut rpc = Transport::new(write, read, Duration::from_millis(80));
            rpc.admission = Some(admission);
            let (sender, mut cancel) = watch::channel(None);
            let task = if cancelled {
                Some(tokio::spawn(async move {
                    tokio::time::sleep(Duration::from_millis(20)).await;
                    sender.send(Some("stop".into())).unwrap();
                    tokio::time::sleep(Duration::from_millis(100)).await;
                }))
            } else {
                None
            };
            let error = rpc
                .rpc("tools/call", json!({"name":"observe"}), &mut cancel)
                .await
                .unwrap_err();
            assert!(
                error.contains(if cancelled { "cancelled" } else { "deadline" }),
                "{error}"
            );
            let audit = rpc.audit();
            assert_eq!(audit["issued_rpc_ids"], 0);
            assert_eq!(audit["requests"][0]["id"], Value::Null);
            assert_eq!(audit["requests"][0]["flushed_unix_ms"], Value::Null);
            assert_eq!(audit["requests"][0]["delivery_unknown"], false);
            assert!(rpc.reusable());
            drop(permit);
            if let Some(task) = task {
                task.await.unwrap();
            }
            std::fs::remove_dir_all(root).unwrap();
        }
    }
    #[tokio::test]
    async fn admission_wait_and_response_share_one_deadline() {
        let (root, admission) = super::super::admission::tests::fixture(1);
        let (_keep, mut holder_cancel) = watch::channel(None);
        let permit = admission
            .acquire(
                tokio::time::Instant::now() + Duration::from_secs(1),
                &mut holder_cancel,
            )
            .await
            .unwrap();
        let release = tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(80)).await;
            drop(permit);
        });
        let (client, server) = tokio::io::duplex(4096);
        let (read, write) = tokio::io::split(client);
        let mut rpc = Transport::new(write, read, Duration::from_millis(130));
        rpc.admission = Some(admission);
        let server = tokio::spawn(async move {
            let (read, mut write) = tokio::io::split(server);
            let mut lines = BufReader::new(read).lines();
            let request: Value =
                serde_json::from_str(&lines.next_line().await.unwrap().unwrap()).unwrap();
            tokio::time::sleep(Duration::from_millis(90)).await;
            write
                .write_all(
                    format!(
                        "{}\n",
                        json!({"jsonrpc":"2.0","id":request["id"],"result":{}})
                    )
                    .as_bytes(),
                )
                .await
                .unwrap();
        });
        let (_keep, mut cancel) = watch::channel(None);
        assert!(rpc
            .rpc("tools/call", json!({"name":"observe"}), &mut cancel)
            .await
            .unwrap_err()
            .contains("response deadline"));
        let audit = rpc.audit();
        assert_eq!(audit["requests"][0]["admission_outcome"], "acquired");
        assert!(audit["requests"][0]["admission_wait_ms"].as_u64().unwrap() >= 70);
        assert_eq!(audit["requests"][0]["delivery_unknown"], true);
        assert_eq!(audit["requests"][0]["id"], 1);
        assert!(audit["requests"][0]["flushed_unix_ms"].is_number());
        release.await.unwrap();
        server.await.unwrap();
        std::fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn invalid_frames_are_fatal_but_application_errors_are_not() {
        for value in [
            json!({"jsonrpc":"2.0","id":2,"result":{}}),
            json!({"jsonrpc":"2.0","id":0,"result":{}}),
            json!({"jsonrpc":"2.0","id":1}),
            json!({"id":1,"result":{}}),
        ] {
            let mut state = State {
                issued: 1,
                ..Default::default()
            };
            state.receive(value);
            assert!(state.fatal.is_some());
        }
        let (sender, _) = oneshot::channel();
        let mut state = State {
            issued: 1,
            pending: Some((1, sender)),
            ..Default::default()
        };
        state.receive(
            json!({"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"application failure"}}),
        );
        assert!(state.fatal.is_none());
        assert!(state.pending.is_none());
    }
}
