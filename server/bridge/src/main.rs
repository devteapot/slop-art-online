mod llm;
mod prompt;
#[allow(unused)]
mod tools;

use shared::module_bindings::{
    DbConnection, NpcPendingDecision, NpcPendingDecisionTableAccess,
    submit_npc_combat_tree_reducer::submit_npc_combat_tree as _,
    submit_npc_plan_reducer::submit_npc_plan as _,
};
use spacetimedb_sdk::{DbContext, Table};
use tokio::sync::mpsc;

const HOST: &str = "http://localhost:3000";
const DB_NAME: &str = "slop-art-online";

#[tokio::main]
async fn main() {
    env_logger::init();
    log::info!("Bridge starting (behavior tree + plan mode)");

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
                    Some(tree_json) => {
                        log::info!("Submitting combat tree for NPC {}", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_combat_tree(decision.npc_id, tree_json) {
                            log::error!("submit_npc_combat_tree failed for NPC {}: {e}", decision.npc_id);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} combat tree, keeping default", decision.npc_id);
                        // Clear the pending decision so it doesn't retry forever
                        // The NPC already has a default combat tree loaded
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
                    Some(steps_json) => {
                        log::info!("Submitting post-combat plan for NPC {}", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_plan(decision.npc_id, steps_json) {
                            log::error!("submit_npc_plan failed for NPC {}: {e}", decision.npc_id);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} post-combat plan", decision.npc_id);
                        // Submit a simple wander plan so the pending decision clears
                        let fallback = r#"["wander"]"#;
                        if let Err(e) = conn.reducers.submit_npc_plan(decision.npc_id, fallback.to_string()) {
                            log::error!("submit_npc_plan (fallback) failed: {e}");
                        }
                    }
                }
            }
            "idle" => {
                match llm::generate_plan(decision.npc_id, &decision.context).await {
                    Some(steps_json) => {
                        log::info!("Submitting idle plan for NPC {}", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_plan(decision.npc_id, steps_json) {
                            log::error!("submit_npc_plan failed for NPC {}: {e}", decision.npc_id);
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
            other => {
                log::warn!("Unknown decision type '{}' for NPC {}", other, decision.npc_id);
            }
        }
    }
}

/// Default aggressive combat tree JSON (matches server's build_default_combat_tree).
fn default_combat_tree_json() -> String {
    r#"{"Select":[{"If":[{"Action":{"health_below":0.25}},{"Sequence":[{"Action":{"say":"I must retreat!"}},{"Action":"flee"}]},{"Select":[{"If":[{"Action":"enemy_in_range"},{"Action":"attack"},{"If":[{"Action":"enemy_detected"},{"Action":"chase"},{"Action":"wander"}]}]}]}]}]}"#.to_string()
}
