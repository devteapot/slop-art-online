mod llm;

use shared::module_bindings::submit_npc_graph_reducer::submit_npc_graph as SubmitNpcGraph;
use shared::module_bindings::{DbConnection, NpcPendingDecision, NpcPendingDecisionTableAccess};
use spacetimedb_sdk::{DbContext, Table};
use std::sync::{Arc, Mutex};
use std::time::Duration;

const HOST: &str = "http://localhost:3000";
const DB_NAME: &str = "slop-art-online";

fn main() {
    env_logger::init();

    let queue: Arc<Mutex<Vec<NpcPendingDecision>>> = Arc::new(Mutex::new(Vec::new()));
    let queue_cb = queue.clone();

    let conn = DbConnection::builder()
        .with_uri(HOST)
        .with_database_name(DB_NAME)
        .on_connect(|ctx: &DbConnection, _identity, _token| {
            log::info!("Bridge connected to SpacetimeDB");
            ctx.subscription_builder()
                .on_applied(|_| log::info!("Subscribed to npc_pending_decision"))
                .subscribe(["SELECT * FROM npc_pending_decision"]);
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
            log::info!("Pending decision for NPC {}", row.npc_id);
            queue_cb.lock().unwrap().push(row.clone());
        });

    conn.run_threaded();

    log::info!("Bridge running — processing NPC decisions...");
    loop {
        let pending: Vec<NpcPendingDecision> = {
            let mut q = queue.lock().unwrap();
            q.drain(..).collect()
        };

        for decision in pending {
            log::info!(
                "Generating graph for NPC {} (context: {})",
                decision.npc_id,
                decision.context
            );
            let graph_json = llm::generate_behaviour_graph(&decision.context);
            log::info!("Submitting graph for NPC {}: {graph_json}", decision.npc_id);
            if let Err(e) = conn.reducers.submit_npc_graph(decision.npc_id, graph_json) {
                log::error!("submit_npc_graph failed for NPC {}: {e}", decision.npc_id);
            }
        }

        std::thread::sleep(Duration::from_millis(100));
    }
}
