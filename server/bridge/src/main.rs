mod llm;
mod prompt;
#[allow(unused)]
mod tools;

use shared::module_bindings::{
    DbConnection, NpcPendingDecision, NpcPendingDecisionTableAccess,
    submit_npc_tree_reducer::submit_npc_tree as _,
    submit_npc_identity_update_reducer::submit_npc_identity_update as _,
    submit_npc_speech_reducer::submit_npc_speech as _,
    submit_npc_memory_reducer::submit_npc_memory as _,
    submit_npc_goals_reducer::submit_npc_goals as _,
    submit_npc_beliefs_reducer::submit_npc_beliefs as _,
    submit_npc_knowledge_reducer::submit_npc_knowledge as _,
};
use spacetimedb_sdk::{DbContext, Table};
use tokio::sync::mpsc;

const HOST: &str = "http://localhost:3000";
const DB_NAME: &str = "slop-art-online";

#[tokio::main]
async fn main() {
    env_logger::init();
    log::info!("Bridge v2 starting (unified tree + experience + conversation)");

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
        log::info!(
            "════ NPC {} | type={} | context={}",
            decision.npc_id,
            decision.decision_type,
            &decision.context[..decision.context.len().min(200)]
        );

        match decision.decision_type.as_str() {
            // ── Tree generation: dawn, exhaustion, goal change ──
            "tree_generation" => {
                match llm::generate_tree(decision.npc_id, &decision.context).await {
                    Some(tree_json) => {
                        log::info!("Submitting unified tree for NPC {}", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_tree(decision.npc_id, tree_json) {
                            log::error!("submit_npc_tree failed for NPC {}: {e}", decision.npc_id);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} tree generation, keeping default", decision.npc_id);
                        // Submit empty to clear pending decision
                        let _ = conn.reducers.submit_npc_tree(decision.npc_id, String::new());
                    }
                }
            }

            // ── Experience evaluation: significant events, near-death ──
            "experience" => {
                match llm::generate_experience_eval(decision.npc_id, &decision.context).await {
                    Some(json) => {
                        log::info!("Submitting identity update for NPC {}", decision.npc_id);
                        if let Err(e) = conn.reducers.submit_npc_identity_update(decision.npc_id, json) {
                            log::error!("submit_npc_identity_update failed for NPC {}: {e}", decision.npc_id);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} experience eval", decision.npc_id);
                        let _ = conn.reducers.submit_npc_identity_update(
                            decision.npc_id, "{}".to_string(),
                        );
                    }
                }
            }

            // ── Conversation: novel social interaction ──
            "conversation" => {
                match llm::generate_conversation(decision.npc_id, &decision.context).await {
                    Some(raw) => {
                        let message = llm::parse_conversation_response(&raw)
                            .unwrap_or_else(|| raw.clone());
                        log::info!("Submitting speech for NPC {}: {}", decision.npc_id,
                            &message[..message.len().min(100)]);
                        if let Err(e) = conn.reducers.submit_npc_speech(decision.npc_id, message) {
                            log::error!("submit_npc_speech failed for NPC {}: {e}", decision.npc_id);
                        }
                    }
                    None => {
                        log::warn!("LLM failed for NPC {} conversation", decision.npc_id);
                        let _ = conn.reducers.submit_npc_speech(
                            decision.npc_id, "Hmm...".to_string(),
                        );
                    }
                }
            }

            other => {
                log::warn!("Unknown decision type '{}' for NPC {}", other, decision.npc_id);
            }
        }
    }
}
