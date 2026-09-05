//! Bounded live verification runtime. Internal uses the production harness; external uses only MCP.
use bridge::{
    agent_harness::{deliberate_once, Proposal, Responsibility},
    participant::ParticipantService,
    reasoning::backend::{Backend, Config},
};
use serde_json::{json, Value};
use std::{
    path::PathBuf,
    process::Stdio,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::{ChildStdin, ChildStdout},
    sync::watch,
};
struct Mcp {
    input: ChildStdin,
    output: BufReader<ChildStdout>,
    id: u64,
}
impl Mcp {
    async fn rpc(&mut self, method: &str, mut params: Value) -> Result<Value, String> {
        self.id += 1;
        params["_meta"] = json!({"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"sao-bounded-live-rust-agent","version":"1"},"io.modelcontextprotocol/clientCapabilities":{}});
        self.input
            .write_all(
                format!(
                    "{}\n",
                    json!({"jsonrpc":"2.0","id":self.id,"method":method,"params":params})
                )
                .as_bytes(),
            )
            .await
            .map_err(|e| e.to_string())?;
        self.input.flush().await.map_err(|e| e.to_string())?;
        tokio::time::timeout(Duration::from_secs(15), async {
            loop {
                let mut line = String::new();
                if self
                    .output
                    .read_line(&mut line)
                    .await
                    .map_err(|e| e.to_string())?
                    == 0
                {
                    return Err("MCP EOF".into());
                }
                let v: Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
                if v["id"] == self.id {
                    if !v["error"].is_null() {
                        return Err(v["error"].to_string());
                    }
                    return Ok(v["result"].clone());
                }
            }
        })
        .await
        .map_err(|_| "MCP deadline".to_string())?
    }
    async fn call(&mut self, name: &str, args: Value) -> Result<Value, String> {
        let r = self
            .rpc("tools/call", json!({"name":name,"arguments":args}))
            .await?;
        let value = if let Some(s) = r.get("structuredContent") {
            s.clone()
        } else {
            serde_json::from_str(
                r["content"][0]["text"]
                    .as_str()
                    .ok_or("MCP result missing")?,
            )
            .map_err(|e| e.to_string())?
        };
        if r["isError"] == true {
            return Err(value.to_string());
        }
        Ok(value)
    }
}
#[tokio::main]
async fn main() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 5 {
        return Err("usage: participant_live_agent internal|external SESSION CONFIG behavior|communication|learning OUTDIR".into());
    }
    let role = match args[3].as_str() {
        "behavior" => Responsibility::Behavior,
        "communication" => Responsibility::Communication,
        "learning" => Responsibility::Learning,
        _ => return Err("invalid role".into()),
    };
    let config: Config =
        serde_json::from_slice(&std::fs::read(&args[2]).map_err(|_| "config unavailable")?)
            .map_err(|_| "invalid config")?;
    let out = PathBuf::from(&args[4]);
    std::fs::create_dir_all(&out).map_err(|_| "audit unavailable")?;
    let (keep, mut cancel) = watch::channel(None);
    let started = Instant::now();
    if args[0] == "internal" {
        let service = ParticipantService::from_file(std::path::Path::new(&args[1])).await?;
        let result = deliberate_once(&service, config, role, &out, cancel).await;
        std::fs::write(out.join("result.json"),json!({"runtime":"built-in production harness, scoped ParticipantService","role":args[3],"elapsed_ms":started.elapsed().as_millis(),"result":result.as_ref().ok(),"error":result.as_ref().err()}).to_string()).map_err(|_|"write failed")?;
        println!(
            "internal {} finished; accepted transport result={}",
            args[3],
            result.is_ok()
        );
        return result.map(|_| ());
    }
    if args[0] != "external" {
        return Err("invalid runtime".into());
    }
    let mut child = tokio::process::Command::new("target/debug/sao-agent-mcp")
        .env("SAO_PARTICIPANT_SESSION", &args[1])
        .env_remove("CARLID_NPC_API_KEY")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()
        .map_err(|_| "cannot launch MCP")?;
    let mut mcp = Mcp {
        input: child.stdin.take().unwrap(),
        output: BufReader::new(child.stdout.take().unwrap()),
        id: 0,
    };
    let discovery = mcp.rpc("server/discover", json!({})).await?;
    let tools = mcp.rpc("tools/list", json!({})).await?;
    let mut state = mcp
        .call("observe", json!({"after_cursor":0,"limit":256}))
        .await?;
    let planned_role = role;
    let feedback_dir = out.parent().ok_or("actor audit directory missing")?;
    let role = bridge::agent_harness::add_controller_feedback(&mut state, feedback_dir, role);
    let backend = Backend::new(config.clone())?;
    if config.max_attempts != 1 {
        return Err("single attempt required".into());
    }
    let mut schema = bridge::agent_harness::proposal_schema(role);
    bridge::agent_harness::ground_reflection_schema(&mut schema, &state);
    let payload=backend.payload(json!([{"role":"system","content":format!("You are a separately running external AI player connected to SAO through MCP. Own your choices using ONLY the supplied subjective state. This turn's responsibility: {role:?}. Behavior chooses replace_tree or patch_subtree; Communication chooses speak; Learning chooses reflect. You may choose no operation when appropriate. Return a compact JSON Proposal matching {schema}. The runtime maps each chosen op unchanged into its matching MCP tool and supplies request ID and the observed control_epoch. Use the observed policy_revision or learning_revision, never guess revisions. Learning needs 1..8 reflections citing retained own experience source IDs of kind perception, skill_progress, skill_result, action_interrupted, behavior_interrupted or speech_cancelled; observed_cursor=latest_cursor. Do not cite a skill_attempt or participant_command. Reflect on what you perceived, including speech if relevant; false conclusions are allowed but provenance must be real. Behavior trees must have at most64nodes, depth8, children8; prefer a small intelligible approach rather than elaborate plans. Dialogue is independent of the running tree; expiry follows current rules_description. Learning does not replace behavior. Choose actual useful intentions for your character; do not output examples or authored test fixtures. No observer truth is available. MCP tool contracts: {tools}. Skill semantics: {}",state["context"]["skill_definitions"])},{"role":"user","content":state.to_string()}]),schema);
    let mut record=backend.safe_value(&json!({"runtime":"separate minimal Rust model-driven MCP client","role":role,"planned_responsibility":planned_role,"discovery":discovery,"participant_context":state,"request":payload,"phase":"started"}));
    std::fs::write(out.join("external.json"), record.to_string()).map_err(|_| "write failed")?;
    let reply = backend
        .complete(
            &payload,
            tokio::time::Instant::now() + Duration::from_millis(config.deadline_ms),
            &mut cancel,
        )
        .await;
    record["reply"] = backend.safe_value(&json!(reply));
    let result=async{
        if let Some(e)=reply.error{return Err(e);}
        let proposal:Proposal=serde_json::from_str(&reply.raw_output).map_err(|error|format!("invalid generated proposal: {error}"))?;
        if proposal.operations.len()>4{return Err("too many operations".into());}
        let mut receipts=vec![];
        for (i,op) in proposal.operations.iter().enumerate(){
            let mut value=serde_json::to_value(op).unwrap();let name=value["op"].as_str().unwrap().to_string();
            let allowed=match role{Responsibility::Behavior=>name=="replace_tree"||name=="patch_subtree",Responsibility::Communication=>name=="speak",Responsibility::Learning=>name=="reflect"};
            if !allowed{return Err("wrong responsibility".into());}
            value.as_object_mut().unwrap().remove("op");value["request_id"]=json!(format!("external-live-{}-{i}",rand::random::<u64>()));value["control_epoch"]=state["control_epoch"].clone();
            let receipt=mcp.call(&name,value.clone()).await;
            receipts.push(json!({"tool":name,"arguments":value,"receipt":receipt.as_ref().ok(),"error":receipt.as_ref().err()}));
        }
        Ok::<_,String>(json!({"reported_reason":proposal.reason,"receipts":receipts}))
    }.await;
    record["elapsed_ms"] = json!(started.elapsed().as_millis());
    record["phase"] = json!("completed");
    record["result"] = json!(result.as_ref().ok());
    record["error"] = json!(result.as_ref().err());
    bridge::agent_harness::save_controller_feedback(feedback_dir, role, &backend.safe_value(&record))?;
    std::fs::write(
        out.join("external.json"),
        backend.safe_value(&record).to_string(),
    )
    .map_err(|_| "write failed")?;
    drop(keep);
    drop(mcp);
    let _ = child.kill().await;
    println!(
        "external {} finished; transport result={}",
        args[3],
        result.is_ok()
    );
    result.map(|_| ())
}
