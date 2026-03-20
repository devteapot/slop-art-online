mod llm;
mod prompt;
#[allow(unused)]
mod tools;

use shared::module_bindings::{
    DbConnection, NpcPendingDecision, NpcPendingDecisionTableAccess,
    submit_npc_combat_tree_reducer::submit_npc_combat_tree as _,
    submit_npc_plan_reducer::submit_npc_plan as _,
    submit_npc_memory_reducer::submit_npc_memory as _,
    submit_npc_reflection_reducer::submit_npc_reflection as _,
    submit_npc_life_tree_reducer::submit_npc_life_tree as _,
    submit_npc_goals_reducer::submit_npc_goals as _,
    submit_npc_beliefs_reducer::submit_npc_beliefs as _,
};
use spacetimedb_sdk::{DbContext, Table};
use tokio::sync::mpsc;

const HOST: &str = "http://localhost:3000";
const DB_NAME: &str = "slop-art-online";

#[tokio::main]
async fn main() {
    env_logger::init();
    log::info!("Bridge starting (behavior tree + plan + social mode)");

    let (tx, mut rx) = mpsc::unbounded_channel::<NpcPendingDecision>();

    let subscribe_queries = vec![
        "SELECT * FROM npc_pending_decision".to_string(),
    ];

    let conn = DbConnection::builder()
        .with_uri(HOST)
        .with_database_name(DB_NAME)
        .on_connect(move |ctx: &DbConnection, _identity, _token| {
            log::info!("Bridge connected to SpacetimeDB");
            ctx.subscription_builder()
                .on_applied(|_| log::info!("Subscriptions applied"))
                .subscribe(subscribe_queries.clone());
        })
        .on_connect_error(|_, err| log::error!("Connect error: {err}"))
        .on_disconnect(|_, err| {
            if let Some(e) = err {
                log::error!("Disconnected: {e}")
            }
        })
        .build()
        .expect("Failed to connect to SpacetimeDB");

    conn.db
        .npc_pending_decision()
        .on_insert(move |_, row: &NpcPendingDecision| {
            log::info!("Pending decision for NPC {} (type={})", row.npc_id, row.decision_type);
            let _ = tx.send(row.clone());
        });

    conn.run_threaded();

    log::info!("Bridge running — waiting for NPC decisions...");

    while let Some(decision) = rx.recv().await {
        log::info!("════════════════════════════════════════════════════");
        log::info!(
            "Decision for NPC {} | type={} | context={}",
            decision.npc_id,
            decision.decision_type,
            &decision.context[..decision.context.len().min(200)]
        );

        match decision.decision_type.as_str() {
            "combat_start" | "combat_update" => {
                match llm::generate_combat_tree(decision.npc_id, &decision.context).await {
                    Some(raw) => {
                        let parsed = llm::parse_response_with_memories(&raw);
                        let tree_json = parsed.as_ref().map(|p| p.steps_json.clone()).unwrap_or(raw);
                        log::info!("Submitting combat tree for NPC {}", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_combat_tree(decision.npc_id, tree_json) {
                            log::error!("submit_npc_combat_tree failed for NPC {}: {e}", decision.npc_id);
                        }
                        if let Some(p) = parsed {
                            submit_memories(&conn, decision.npc_id, &p.memories);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} combat tree, keeping default", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_combat_tree(
                            decision.npc_id,
                            default_combat_tree_json(),
                        ) {
                            log::error!("submit_npc_combat_tree (default) failed: {e}");
                        }
                    }
                }
            }
            "post_combat" => {
                match llm::generate_post_combat(decision.npc_id, &decision.context).await {
                    Some(raw) => {
                        let parsed = llm::parse_response_with_memories(&raw);
                        let steps = parsed.as_ref().map(|p| p.steps_json.clone()).unwrap_or(raw);
                        log::info!("Submitting post-combat plan for NPC {}", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_plan(decision.npc_id, steps) {
                            log::error!("submit_npc_plan failed for NPC {}: {e}", decision.npc_id);
                        }
                        if let Some(p) = parsed {
                            submit_memories(&conn, decision.npc_id, &p.memories);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} post-combat plan", decision.npc_id);
                        let fallback = r#"["wander"]"#;
                        if let Err(e) = conn.reducers.submit_npc_plan(decision.npc_id, fallback.to_string()) {
                            log::error!("submit_npc_plan (fallback) failed: {e}");
                        }
                    }
                }
            }
            "idle" => {
                match llm::generate_plan(decision.npc_id, &decision.context).await {
                    Some(raw) => {
                        let parsed = llm::parse_response_with_memories(&raw);
                        let steps = parsed.as_ref().map(|p| p.steps_json.clone()).unwrap_or(raw);
                        log::info!("Submitting idle plan for NPC {}", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_plan(decision.npc_id, steps) {
                            log::error!("submit_npc_plan failed for NPC {}: {e}", decision.npc_id);
                        }
                        if let Some(p) = parsed {
                            submit_memories(&conn, decision.npc_id, &p.memories);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} idle plan", decision.npc_id);
                        let fallback = r#"["wander"]"#;
                        if let Err(e) = conn.reducers.submit_npc_plan(decision.npc_id, fallback.to_string()) {
                            log::error!("submit_npc_plan (fallback) failed: {e}");
                        }
                    }
                }
            }
            "social" => {
                match llm::generate_social(decision.npc_id, &decision.context).await {
                    Some(raw) => {
                        log::info!("Raw LLM response for NPC {}: {}", decision.npc_id, &raw[..raw.len().min(500)]);
                        let parsed = llm::parse_response_with_memories(&raw);
                        let steps = parsed.as_ref().map(|p| p.steps_json.clone()).unwrap_or(raw);
                        log::info!("Submitting social plan for NPC {} with steps: {}", decision.npc_id, &steps[..steps.len().min(500)]);
                        if let Err(e) = conn.reducers.submit_npc_plan(decision.npc_id, steps) {
                            log::error!("submit_npc_plan failed for NPC {}: {e}", decision.npc_id);
                        }
                        if let Some(p) = parsed {
                            submit_memories(&conn, decision.npc_id, &p.memories);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} social plan", decision.npc_id);
                        let fallback = r#"[{"say": "Greetings, traveler."}]"#;
                        if let Err(e) = conn.reducers.submit_npc_plan(decision.npc_id, fallback.to_string()) {
                            log::error!("submit_npc_plan (fallback) failed: {e}");
                        }
                    }
                }
            }
            "reflection" => {
                match llm::generate_reflection(decision.npc_id, &decision.context).await {
                    Some(raw) => {
                        log::info!("Submitting reflection for NPC {}", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_reflection(decision.npc_id, raw) {
                            log::error!("submit_npc_reflection failed for NPC {}: {e}", decision.npc_id);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} reflection, clearing pending", decision.npc_id);
                        // Submit empty reflection to clear pending decision
                        let _ = conn.reducers.submit_npc_reflection(decision.npc_id, "{}".to_string());
                    }
                }
            }
            "dawn" => {
                match llm::generate_dawn(decision.npc_id, &decision.context).await {
                    Some(raw) => {
                        // Parse response: expect {"life_tree": {...}, "memories": [...]}
                        let parsed = llm::parse_response_with_memories(&raw);
                        if let Some(ref p) = parsed {
                            // Try to extract life_tree from the response
                            if let Ok(v) = serde_json::from_str::<serde_json::Value>(&p.steps_json) {
                                if let Some(tree) = v.get("life_tree") {
                                    let tree_json = serde_json::to_string(tree).unwrap_or_default();
                                    log::info!("Submitting life tree for NPC {}", decision.npc_id);
                                    if let Err(e) = conn.reducers.submit_npc_life_tree(decision.npc_id, tree_json) {
                                        log::error!("submit_npc_life_tree failed for NPC {}: {e}", decision.npc_id);
                                    }
                                } else {
                                    // Maybe the whole response IS the tree
                                    log::info!("Submitting life tree (raw) for NPC {}", decision.npc_id);
                                    if let Err(e) = conn.reducers.submit_npc_life_tree(decision.npc_id, p.steps_json.clone()) {
                                        log::error!("submit_npc_life_tree (raw) failed for NPC {}: {e}", decision.npc_id);
                                    }
                                }
                            }
                            submit_memories(&conn, decision.npc_id, &p.memories);
                        } else {
                            // Try raw as tree
                            log::info!("Submitting life tree (unparsed) for NPC {}", decision.npc_id);
                            if let Err(e) = conn.reducers.submit_npc_life_tree(decision.npc_id, raw) {
                                log::error!("submit_npc_life_tree (unparsed) failed for NPC {}: {e}", decision.npc_id);
                            }
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} dawn life tree, using default", decision.npc_id);
                        // Clear pending decision by submitting a simple wander tree
                        let fallback = r#"{"Action":"wander"}"#;
                        let _ = conn.reducers.submit_npc_life_tree(decision.npc_id, fallback.to_string());
                    }
                }
            }
            "significant" => {
                match llm::generate_significant(decision.npc_id, &decision.context).await {
                    Some(raw) => {
                        let parsed = llm::parse_response_with_memories(&raw);
                        let steps = parsed.as_ref().map(|p| p.steps_json.clone()).unwrap_or(raw.clone());
                        log::info!("Submitting significant plan for NPC {}", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_plan(decision.npc_id, steps) {
                            log::error!("submit_npc_plan failed for NPC {}: {e}", decision.npc_id);
                        }
                        if let Some(p) = parsed {
                            submit_memories(&conn, decision.npc_id, &p.memories);
                            // Also submit goals/beliefs/relationships if present
                            submit_reflection_extras(&conn, decision.npc_id, &raw);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} significant event", decision.npc_id);
                        let fallback = r#"[{"say": "Hmm..."}, {"wait": 2.0}]"#;
                        let _ = conn.reducers.submit_npc_plan(decision.npc_id, fallback.to_string());
                    }
                }
            }
            other => {
                log::warn!("Unknown decision type '{}' for NPC {}", other, decision.npc_id);
            }
        }
    }
}

/// Submit memories extracted from LLM responses.
fn submit_memories(conn: &DbConnection, npc_id: u64, memories: &[String]) {
    for memory in memories {
        if !memory.is_empty() {
            log::info!("[NPC {}] saving memory: {}", npc_id, &memory[..memory.len().min(100)]);
            if let Err(e) = conn.reducers.submit_npc_memory(npc_id, memory.clone()) {
                log::error!("submit_npc_memory failed for NPC {}: {e}", npc_id);
            }
        }
    }
}

/// Submit goals/beliefs/relationships extracted from significant event responses.
fn submit_reflection_extras(conn: &DbConnection, npc_id: u64, raw: &str) {
    let v: serde_json::Value = match serde_json::from_str(raw) {
        Ok(v) => v,
        Err(_) => return,
    };
    if let Some(goals) = v.get("goals") {
        if goals.is_array() {
            let goals_json = serde_json::to_string(goals).unwrap_or_default();
            if let Err(e) = conn.reducers.submit_npc_goals(npc_id, goals_json) {
                log::error!("submit_npc_goals failed for NPC {}: {e}", npc_id);
            }
        }
    }
    if let Some(beliefs) = v.get("beliefs") {
        if beliefs.is_array() {
            let beliefs_json = serde_json::to_string(beliefs).unwrap_or_default();
            if let Err(e) = conn.reducers.submit_npc_beliefs(npc_id, beliefs_json) {
                log::error!("submit_npc_beliefs failed for NPC {}: {e}", npc_id);
            }
        }
    }
    // relationship_updates are handled by submit_npc_reflection, not here
    // (significant events go through submit_npc_plan, not submit_npc_reflection)
}

/// Default aggressive combat tree JSON (matches server's build_default_combat_tree).
fn default_combat_tree_json() -> String {
    r#"{"Select":[{"If":[{"Action":{"health_below":0.25}},{"Sequence":[{"Action":{"say":"I must retreat!"}},{"Action":"flee"}]},{"Select":[{"If":[{"Action":"enemy_in_range"},{"Action":"attack"},{"If":[{"Action":"enemy_detected"},{"Action":"chase"},{"Action":"wander"}]}]}]}]}]}"#.to_string()
}
