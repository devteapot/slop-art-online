//! Built-in slow loop: provider, schedule and private reasoning belong here, never in World.step.
//! Only ParticipantService may read/control the character; no World, SQL, owner token or operator reducer.
use crate::{
    participant::ParticipantService,
    reasoning::backend::{Backend, Config},
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use simulation::participant::{Command, Request, API_VERSION};
use std::{path::Path, time::Duration};
use tokio::sync::watch;
#[derive(Clone, Copy, Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Responsibility {
    Behavior,
    Communication,
    Learning,
}
#[derive(Deserialize, Serialize, schemars::JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Proposal {
    pub reason: String,
    pub operations: Vec<Command>,
}
impl Responsibility {
    pub fn accepts(self, c: &Command) -> bool {
        matches!(
            (self, c),
            (
                Self::Behavior,
                Command::ReplaceTree { .. } | Command::PatchSubtree { .. }
            ) | (Self::Communication, Command::Speak { .. })
                | (Self::Learning, Command::Reflect { .. })
        )
    }
}
/// Constrain each responsibility's generated format before inference, as well as validating it after.
pub fn proposal_schema(role: Responsibility) -> Value {
    let mut schema = serde_json::to_value(schemars::schema_for!(Proposal)).unwrap();
    simulation::contract::strict_schema(&mut schema);
    schema["$defs"]["Command"]["anyOf"]
        .as_array_mut()
        .unwrap()
        .retain(|variant| {
            let op = variant["properties"]["op"]["const"].as_str().unwrap();
            match role {
                Responsibility::Behavior => op == "replace_tree" || op == "patch_subtree",
                Responsibility::Communication => op == "speak",
                Responsibility::Learning => op == "reflect",
            }
        });
    schema
}
/// Ground reflection IDs in this scoped observation; the authority still validates at submission.
pub fn ground_reflection_schema(schema: &mut Value, context: &Value) {
    let ids: Vec<_> = context["experiences"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|e| {
            matches!(
                e["kind"].as_str(),
                Some(
                    "perception"
                        | "skill_progress"
                        | "skill_result"
                        | "action_interrupted"
                        | "behavior_interrupted"
                        | "speech_cancelled"
                )
            )
        })
        .filter_map(|e| e["source"].as_u64())
        .collect();
    schema["$defs"]["Reflection"]["properties"]["source"]["enum"] = json!(ids);
    schema["$defs"]["Reflection"]["properties"]["source"]["description"] = json!("Exact source event ID from this enum, NEVER the separate cursor number. Cursors only belong in observed_cursor.");
    schema["$defs"]["Reflection"]["properties"]["trust_delta"]["description"] = json!("Use zero unless the chosen source identifies a perceived counterpart (data.from is non-null); generic task success has no person to change trust in.");
}
pub async fn deliberate_once(
    service: &ParticipantService,
    config: Config,
    role: Responsibility,
    audit: &Path,
    mut cancel: watch::Receiver<Option<String>>,
) -> Result<Value, String> {
    let context = service.observe(0, 256).await?;
    if context["stopped"] == true || context["context"]["player"]["health"] == 0 {
        return Err("character dead or stopped".into());
    }
    let backend = Backend::new(config.clone())?;
    if config.max_attempts != 1 {
        return Err("participant harness currently requires explicit max_attempts=1; it never retries deliberation automatically".into());
    }
    let id = format!("harness-{:032x}", rand::random::<u128>());
    let mut schema = proposal_schema(role);
    ground_reflection_schema(&mut schema, &context);
    let messages = json!([{"role":"system","content":format!("You are the built-in agent runtime for ONE SAO character. Responsibility this turn: {role:?}. Choose zero operations when nothing useful is needed. Behavior may replace_tree or patch_subtree; Communication may speak independently; Learning may reflect independently. Never manufacture fixed survival plans/dialogue in place of model decisions. Your supplied state is subjective; different/false beliefs are allowed, provenance must cite retained own experience source IDs at/before observed_cursor. Use current control epoch, policy_revision and learning_revision. Learning needs 1..8 reflections citing retained own sources of kind perception, skill_progress, skill_result, action_interrupted, behavior_interrupted or speech_cancelled; do not cite a skill_attempt or participant_command. Prefer compact trees of at most12 nodes for this bounded world. Action duration is an unsigned integer; use the current context rules_description for gameplay limits. Trees use priority/sequence/guard/action/reconsider, bounded 64 nodes, depth8, children8; sequence progress persists, priority rechecks. Policy root repeats. Use patch to retain unaffected progress. Do not automatically replace a tree to speak or learn. Speech queue is separate and delivered at actual future position. Send JSON matching schema: {schema}. Skills: {}",context["context"]["skill_definitions"])},{"role":"user","content":context.to_string()}]);
    let payload = backend.payload(messages, schema);
    std::fs::create_dir_all(audit).map_err(|_| "harness audit directory unavailable")?;
    let path = audit.join(format!("{id}.json"));
    let mut record=backend.safe_value(&json!({"id":id,"responsibility":role,"participant_context":context,"request":payload,"config":config,"phase":"started","not_private_chain_of_thought":true}));
    std::fs::write(&path, record.to_string()).map_err(|_| "harness audit unavailable")?;
    let (local_cancel, mut local_rx) = watch::channel(cancel.borrow().clone());
    let exchange = backend.complete(
        &payload,
        tokio::time::Instant::now() + Duration::from_millis(config.deadline_ms),
        &mut local_rx,
    );
    tokio::pin!(exchange);
    let mut upstream_open = true;
    let reply = loop {
        tokio::select! {
            reply=&mut exchange=>break reply,
            changed=cancel.changed(), if upstream_open=>{ if changed.is_err(){upstream_open=false;} let reason=if changed.is_err(){Some("harness owner stopped".into())}else{cancel.borrow().clone()}; if reason.is_some(){let _=local_cancel.send(reason);} },
            _=tokio::time::sleep(Duration::from_millis(100))=>{
                let invalid=match service.current(){Ok(v)=>v["stopped"]==true||v["context"]["player"]["health"]==0||v["control_epoch"]!=context["control_epoch"],Err(_)=>true};
                if invalid{let _=local_cancel.send(Some("character stopped, disconnected or control changed".into()));}
            }
        }
    };
    record["reply"] = backend.safe_value(&json!(reply));
    let result = async {
        if let Some(error) = reply.error {
            return Err(error);
        }
        if let Some(reason) = cancel.borrow().clone() {
            return Err(format!("cancelled: {reason}"));
        }
        let proposal: Proposal = serde_json::from_str(&backend.redact(&reply.raw_output))
            .map_err(|_| "invalid participant harness proposal")?;
        if proposal.reason.trim().is_empty()
            || proposal.reason.len() > 1000
            || proposal.operations.len() > 4
            || proposal.operations.iter().any(|c| !role.accepts(c))
        {
            return Err("proposal exceeds responsibility/batch limits".into());
        }
        let mut results = vec![];
        for (n, command) in proposal.operations.into_iter().enumerate() {
            if cancel.borrow().is_some() {
                return Err("harness cancelled before submission".into());
            }
            // Use the original read epoch and model-chosen revisions, never silently refresh stale proposals.
            results.push(
                service
                    .command(Request {
                        api_version: API_VERSION.into(),
                        request_id: format!("{id}-{n}"),
                        control_epoch: context["control_epoch"].as_u64().unwrap(),
                        command,
                    })
                    .await?,
            );
        }
        Ok(json!({"reason":proposal.reason,"receipts":results}))
    }
    .await;
    record["phase"] = json!("completed");
    record["result"] = json!(result.as_ref().ok());
    record["error"] = json!(result.as_ref().err());
    std::fs::write(path, backend.safe_value(&record).to_string())
        .map_err(|_| "harness completion audit failed")?;
    result
}
/// Three independently scheduled loops, each free to return no operation. Timing belongs to this harness.
pub async fn run(
    service: ParticipantService,
    config: Config,
    audit: std::path::PathBuf,
    cancel: watch::Receiver<Option<String>>,
) {
    if let Ok(path) = std::env::var("SAO_HARNESS_START_FILE") {
        let mut gate_cancel = cancel.clone();
        while !std::path::Path::new(&path).exists() {
            if gate_cancel.borrow().is_some() { return; }
            tokio::select! { _=tokio::time::sleep(Duration::from_millis(100))=>(), _=gate_cancel.changed()=>return }
        }
    }
    if let Ok(interval) = std::env::var("SAO_HARNESS_SERIAL_MS") {
        let interval = interval.parse::<u64>().unwrap_or(15000).max(1000);
        let calls = std::env::var("SAO_HARNESS_MAX_CALLS").ok().and_then(|n| n.parse::<usize>().ok()).unwrap_or(6);
        let mut cancel = cancel;
        for n in 0..calls {
            if cancel.borrow().is_some() || service.current().is_ok_and(|v|v["stopped"]==true||v["context"]["player"]["health"]==0) {break;}
            let role = [Responsibility::Behavior, Responsibility::Communication, Responsibility::Learning][n%3];
            if let Err(e) = deliberate_once(&service, config.clone(), role, &audit, cancel.clone()).await {eprintln!("participant harness {role:?}: {e}");}
            tokio::select! { _=tokio::time::sleep(Duration::from_millis(interval))=>(), _=cancel.changed()=>break }
        }
        return;
    }
    let remaining = std::sync::Arc::new(std::sync::atomic::AtomicU64::new(
        std::env::var("SAO_HARNESS_MAX_CALLS")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(u64::MAX),
    ));
    let mut tasks = vec![];
    for (role, default_ms, env) in [
        (Responsibility::Behavior, 15000, "SAO_BEHAVIOR_MS"),
        (Responsibility::Communication, 21000, "SAO_COMMUNICATION_MS"),
        (Responsibility::Learning, 27000, "SAO_LEARNING_MS"),
    ] {
        let service = service.clone();
        let config = config.clone();
        let audit = audit.clone();
        let mut cancel = cancel.clone();
        let interval = std::env::var(env)
            .ok()
            .and_then(|s| s.parse::<u64>().ok())
            .unwrap_or(default_ms)
            .max(1000);
        let remaining = remaining.clone();
        tasks.push(tokio::spawn(async move{loop{
            if cancel.borrow().is_some(){break;}
            if service.current().is_ok_and(|v|v["stopped"]==true||v["context"]["player"]["health"]==0){break;}
            if remaining.fetch_update(std::sync::atomic::Ordering::SeqCst, std::sync::atomic::Ordering::SeqCst, |n| n.checked_sub(1)).is_err(){break;}
            if let Err(e)=deliberate_once(&service,config.clone(),role,&audit,cancel.clone()).await{eprintln!("participant harness {role:?}: {e}");}
            tokio::select!{_=tokio::time::sleep(Duration::from_millis(interval))=>(),_=cancel.changed()=>break}
        }}));
    }
    for task in tasks {
        let _ = task.await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn role_schema_exposes_allowed_commands_without_freezing_gameplay_limits() {
        for (role, expected) in [
            (
                Responsibility::Behavior,
                vec!["replace_tree", "patch_subtree"],
            ),
            (Responsibility::Communication, vec!["speak"]),
            (Responsibility::Learning, vec!["reflect"]),
        ] {
            let schema = proposal_schema(role);
            let names: Vec<_> = schema["$defs"]["Command"]["anyOf"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v["properties"]["op"]["const"].as_str().unwrap())
                .collect();
            assert_eq!(names, expected);
            assert_eq!(
                schema["$defs"]["Action"]["properties"]["duration"]["minimum"],
                0
            );
            assert!(schema["$defs"]["Action"]["properties"]["duration"]["maximum"].is_null());
        }
    }
}

#[cfg(test)]
#[test]
fn reflection_grounding_uses_source_ids_not_cursors_or_ineligible_speech() {
    let context = json!({"experiences":[{"cursor":1,"source":31,"kind":"perception"},{"cursor":2,"source":42,"kind":"speech"},{"cursor":3,"source":57,"kind":"skill_result"}]});
    let mut schema = proposal_schema(Responsibility::Learning);
    ground_reflection_schema(&mut schema, &context);
    assert_eq!(
        schema["$defs"]["Reflection"]["properties"]["source"]["enum"],
        json!([31, 57])
    );
}
