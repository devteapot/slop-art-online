use spacetimedb::{Identity, ReducerContext, ScheduleAt, SpacetimeType, Table};
use spacetimedb::rand::Rng;
use std::time::Duration;

const WORLD_MIN: f32 = -500.0;
const WORLD_MAX: f32 = 500.0;
const NPC_MOVE_RANGE: f32 = 50.0;
const NPC_CHASE_STEP: f32 = 60.0;
const NPC_TICK_MS: u64 = 500;
const NPC_DETECTION_RANGE: f32 = 350.0;
const MAX_HEALTH: i32 = 100;
const ATTACK_DAMAGE: i32 = 10;
const ATTACK_RANGE: f32 = 100.0;

// --- Types ---

#[derive(SpacetimeType, Clone, Debug)]
pub struct Position {
    pub x: f32,
    pub y: f32,
}

impl Position {
    fn distance_to(&self, other: &Position) -> f32 {
        let dx = self.x - other.x;
        let dy = self.y - other.y;
        (dx * dx + dy * dy).sqrt()
    }
}

// --- Tables ---

#[derive(Clone)]
#[spacetimedb::table(accessor = player, public)]
pub struct Player {
    #[primary_key]
    pub identity: Identity,
    pub position: Position,
    pub health: i32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = npc, public)]
pub struct Npc {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub position: Position,
    pub health: i32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = npc_behaviour_graph, public)]
pub struct NpcBehaviourGraph {
    #[primary_key]
    pub npc_id: u64,
    pub current_node: String,
    pub graph: String,
}

#[spacetimedb::table(accessor = npc_pending_decision, public)]
pub struct NpcPendingDecision {
    #[primary_key]
    pub npc_id: u64,
    pub context: String,
}

#[spacetimedb::table(accessor = npc_tick_schedule, scheduled(tick_npcs))]
pub struct NpcTickSchedule {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}

// --- Behaviour graph evaluation (internal, not SpacetimeDB types) ---

#[derive(serde::Deserialize)]
struct BehaviourGraph {
    initial_node: String,
    nodes: std::collections::HashMap<String, BehaviourNode>,
}

#[derive(serde::Deserialize)]
struct BehaviourNode {
    action: String,
    transitions: Vec<Transition>,
}

#[derive(serde::Deserialize)]
struct Transition {
    condition: String,
    next: String,
}

fn direction_to(from: &Position, to: &Position) -> (f32, f32) {
    let dx = to.x - from.x;
    let dy = to.y - from.y;
    let len = (dx * dx + dy * dy).sqrt();
    if len < 0.001 { (0.0, 0.0) } else { (dx / len, dy / len) }
}

fn find_nearest_player(ctx: &ReducerContext, pos: &Position) -> Option<(Player, f32)> {
    ctx.db.player().iter()
        .map(|p| { let d = pos.distance_to(&p.position); (p, d) })
        .min_by(|a, b| a.1.partial_cmp(&b.1).unwrap())
}

fn check_condition(condition: &str, npc: &Npc, target: Option<&Player>) -> bool {
    match condition {
        "in_range"            => target.map_or(false, |p| npc.position.distance_to(&p.position) <= ATTACK_RANGE),
        "target_out_of_range" => target.map_or(true,  |p| npc.position.distance_to(&p.position) > ATTACK_RANGE),
        "no_target"           => target.is_none(),
        _                     => false,
    }
}

fn execute_action(ctx: &ReducerContext, npc: &Npc, action: &str, target: Option<&Player>) {
    match action {
        "move_toward_target" => {
            if let Some(player) = target {
                let (dx, dy) = direction_to(&npc.position, &player.position);
                let new_x = (npc.position.x + dx * NPC_CHASE_STEP).clamp(WORLD_MIN, WORLD_MAX);
                let new_y = (npc.position.y + dy * NPC_CHASE_STEP).clamp(WORLD_MIN, WORLD_MAX);
                ctx.db.npc().id().update(Npc {
                    position: Position { x: new_x, y: new_y },
                    ..(*npc).clone()
                });
            }
        }
        "attack_target" => {
            if let Some(player) = target {
                if npc.position.distance_to(&player.position) <= ATTACK_RANGE {
                    let new_health = player.health - ATTACK_DAMAGE;
                    if new_health <= 0 {
                        ctx.db.player().identity().update(Player {
                            position: Position { x: 0.0, y: 0.0 },
                            health: MAX_HEALTH,
                            ..(*player).clone()
                        });
                    } else {
                        ctx.db.player().identity().update(Player {
                            health: new_health,
                            ..(*player).clone()
                        });
                    }
                }
            }
        }
        "flee_from_target" => {
            if let Some(player) = target {
                let (dx, dy) = direction_to(&npc.position, &player.position);
                let new_x = (npc.position.x - dx * NPC_CHASE_STEP).clamp(WORLD_MIN, WORLD_MAX);
                let new_y = (npc.position.y - dy * NPC_CHASE_STEP).clamp(WORLD_MIN, WORLD_MAX);
                ctx.db.npc().id().update(Npc {
                    position: Position { x: new_x, y: new_y },
                    ..(*npc).clone()
                });
            }
        }
        "wander" => {
            let dx = (ctx.rng().gen::<f32>() * 2.0 - 1.0) * NPC_MOVE_RANGE;
            let dy = (ctx.rng().gen::<f32>() * 2.0 - 1.0) * NPC_MOVE_RANGE;
            let new_x = (npc.position.x + dx).clamp(WORLD_MIN, WORLD_MAX);
            let new_y = (npc.position.y + dy).clamp(WORLD_MIN, WORLD_MAX);
            ctx.db.npc().id().update(Npc {
                position: Position { x: new_x, y: new_y },
                ..(*npc).clone()
            });
        }
        _ => {} // idle or unknown
    }
}

fn evaluate_graph(ctx: &ReducerContext, npc: &Npc, entry: &NpcBehaviourGraph) {
    let graph: BehaviourGraph = match serde_json::from_str(&entry.graph) {
        Ok(g) => g,
        Err(e) => { log::error!("Invalid graph for NPC {}: {e}", npc.id); return; }
    };

    let node = match graph.nodes.get(&entry.current_node) {
        Some(n) => n,
        None => match graph.nodes.get(&graph.initial_node) {
            Some(n) => n,
            None => return,
        }
    };

    // Use nearest player within detection range as target
    let target = find_nearest_player(ctx, &npc.position)
        .filter(|(_, d)| *d <= NPC_DETECTION_RANGE)
        .map(|(p, _)| p);

    // Check transitions — take first matching
    let next_node = node.transitions.iter()
        .find(|t| check_condition(&t.condition, npc, target.as_ref()))
        .map(|t| t.next.clone());

    execute_action(ctx, npc, &node.action, target.as_ref());

    if let Some(next) = next_node {
        ctx.db.npc_behaviour_graph().npc_id().update(NpcBehaviourGraph {
            current_node: next,
            ..(*entry).clone()
        });
    }
}

// --- Reducers ---

#[spacetimedb::reducer(init)]
pub fn init(ctx: &ReducerContext) {
    schedule_next_npc_tick(ctx);
}

#[spacetimedb::reducer]
pub fn start_npc_ticker(ctx: &ReducerContext) {
    for s in ctx.db.npc_tick_schedule().iter() {
        ctx.db.npc_tick_schedule().scheduled_id().delete(&s.scheduled_id);
    }
    schedule_next_npc_tick(ctx);
}

fn schedule_next_npc_tick(ctx: &ReducerContext) {
    let next = ctx.timestamp + Duration::from_millis(NPC_TICK_MS);
    ctx.db.npc_tick_schedule().insert(NpcTickSchedule {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(next),
    });
}

#[spacetimedb::reducer]
pub fn tick_npcs(ctx: &ReducerContext, _schedule: NpcTickSchedule) {
    for npc in ctx.db.npc().iter() {
        if let Some(graph_entry) = ctx.db.npc_behaviour_graph().npc_id().find(&npc.id) {
            let has_pending = ctx.db.npc_pending_decision().npc_id().find(&npc.id).is_some();

            // When idle and a player enters detection range, request an LLM strategy upgrade
            if !has_pending && graph_entry.current_node == "idle" {
                if let Some((player, dist)) = find_nearest_player(ctx, &npc.position) {
                    if dist <= NPC_DETECTION_RANGE {
                        let context = format!(
                            r#"{{"npc_id":{},"npc_position":{{"x":{},"y":{}}},"npc_health":{},"nearby_players":[{{"identity":"{}","position":{{"x":{},"y":{}}},"distance":{}}}],"attack_range":{}}}"#,
                            npc.id, npc.position.x, npc.position.y, npc.health,
                            player.identity.to_hex().to_string(),
                            player.position.x, player.position.y, dist,
                            ATTACK_RANGE
                        );
                        ctx.db.npc_pending_decision().insert(NpcPendingDecision { npc_id: npc.id, context });
                    }
                }
            }

            // Always evaluate the graph — NPC keeps moving even while LLM is thinking
            evaluate_graph(ctx, &npc, &graph_entry);
        }
    }
    schedule_next_npc_tick(ctx);
}

#[spacetimedb::reducer]
pub fn submit_npc_graph(ctx: &ReducerContext, npc_id: u64, graph_json: String) -> Result<(), String> {
    ctx.db.npc().id().find(&npc_id).ok_or("NPC not found")?;

    let graph: BehaviourGraph = serde_json::from_str(&graph_json)
        .map_err(|e| format!("Invalid graph JSON: {e}"))?;

    // Start in the most appropriate node given current world state so we
    // don't immediately re-trigger a pending decision from the idle node.
    let npc = ctx.db.npc().id().find(&npc_id).ok_or("NPC not found")?;
    let start_node = find_nearest_player(ctx, &npc.position)
        .filter(|(_, d)| *d <= NPC_DETECTION_RANGE)
        .map(|(_, d)| if d <= ATTACK_RANGE { "attacking" } else { "chasing" })
        .unwrap_or(&graph.initial_node)
        .to_string();

    if ctx.db.npc_behaviour_graph().npc_id().find(&npc_id).is_some() {
        ctx.db.npc_behaviour_graph().npc_id().update(NpcBehaviourGraph {
            npc_id,
            current_node: start_node,
            graph: graph_json,
        });
    } else {
        ctx.db.npc_behaviour_graph().insert(NpcBehaviourGraph {
            npc_id,
            current_node: start_node,
            graph: graph_json,
        });
    }

    // Clear the pending decision
    ctx.db.npc_pending_decision().npc_id().delete(&npc_id);
    Ok(())
}

const DEFAULT_GRAPH: &str = r#"{
    "initial_node": "idle",
    "nodes": {
        "idle": {
            "action": "wander",
            "transitions": [
                { "condition": "in_range",            "next": "attacking" },
                { "condition": "target_out_of_range", "next": "chasing"  }
            ]
        },
        "chasing": {
            "action": "move_toward_target",
            "transitions": [
                { "condition": "in_range",  "next": "attacking" },
                { "condition": "no_target", "next": "idle"      }
            ]
        },
        "attacking": {
            "action": "attack_target",
            "transitions": [
                { "condition": "target_out_of_range", "next": "chasing" },
                { "condition": "no_target",           "next": "idle"    }
            ]
        }
    }
}"#;

#[spacetimedb::reducer]
pub fn spawn_npc(ctx: &ReducerContext, x: f32, y: f32) {
    let npc = ctx.db.npc().insert(Npc {
        id: 0,
        position: Position { x: x.clamp(WORLD_MIN, WORLD_MAX), y: y.clamp(WORLD_MIN, WORLD_MAX) },
        health: MAX_HEALTH,
    });
    ctx.db.npc_behaviour_graph().insert(NpcBehaviourGraph {
        npc_id: npc.id,
        current_node: "idle".to_string(),
        graph: DEFAULT_GRAPH.to_string(),
    });
}

#[spacetimedb::reducer]
pub fn join_game(ctx: &ReducerContext) {
    if ctx.db.player().identity().find(&ctx.sender()).is_some() {
        ctx.db.player().identity().update(Player {
            identity: ctx.sender(),
            position: Position { x: 0.0, y: 0.0 },
            health: MAX_HEALTH,
        });
    } else {
        ctx.db.player().insert(Player {
            identity: ctx.sender(),
            position: Position { x: 0.0, y: 0.0 },
            health: MAX_HEALTH,
        });
    }
}

#[spacetimedb::reducer(client_disconnected)]
pub fn identity_disconnected(ctx: &ReducerContext) {
    ctx.db.player().identity().delete(&ctx.sender());
}

#[spacetimedb::reducer]
pub fn move_player(ctx: &ReducerContext, x: f32, y: f32) -> Result<(), String> {
    let player = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Player not found")?;
    ctx.db.player().identity().update(Player {
        position: Position {
            x: x.clamp(WORLD_MIN, WORLD_MAX),
            y: y.clamp(WORLD_MIN, WORLD_MAX),
        },
        ..player
    });
    Ok(())
}

#[spacetimedb::reducer]
pub fn attack_player(ctx: &ReducerContext, target: Identity) -> Result<(), String> {
    let attacker = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Attacker not found")?;
    let target_player = ctx.db.player().identity().find(&target)
        .ok_or("Target not found")?;

    if attacker.position.distance_to(&target_player.position) > ATTACK_RANGE {
        return Err("Target out of range".to_string());
    }

    let new_health = target_player.health - ATTACK_DAMAGE;
    if new_health <= 0 {
        ctx.db.player().identity().update(Player {
            position: Position { x: 0.0, y: 0.0 },
            health: MAX_HEALTH,
            ..target_player
        });
    } else {
        ctx.db.player().identity().update(Player { health: new_health, ..target_player });
    }
    Ok(())
}

#[spacetimedb::reducer]
pub fn attack_npc(ctx: &ReducerContext, target_id: u64) -> Result<(), String> {
    let attacker = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Attacker not found")?;
    let target_npc = ctx.db.npc().id().find(&target_id)
        .ok_or("NPC not found")?;

    if attacker.position.distance_to(&target_npc.position) > ATTACK_RANGE {
        return Err("Target out of range".to_string());
    }

    let new_health = target_npc.health - ATTACK_DAMAGE;
    if new_health <= 0 {
        ctx.db.npc().id().delete(&target_id);
        ctx.db.npc_behaviour_graph().npc_id().delete(&target_id);
        ctx.db.npc_pending_decision().npc_id().delete(&target_id);
    } else {
        ctx.db.npc().id().update(Npc { health: new_health, ..target_npc });
    }
    Ok(())
}
