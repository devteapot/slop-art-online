use spacetimedb::ReducerContext;

use crate::constants::*;
use crate::tables::*;
use crate::combat::direction_to;

#[derive(serde::Deserialize)]
pub struct BehaviourGraph {
    pub initial_node: String,
    pub nodes: std::collections::HashMap<String, BehaviourNode>,
}

#[derive(serde::Deserialize)]
pub struct BehaviourNode {
    pub action: String,
    pub transitions: Vec<Transition>,
}

#[derive(serde::Deserialize)]
pub struct Transition {
    pub condition: String,
    pub next: String,
}

pub const DEFAULT_GRAPH: &str = r#"{
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

pub fn check_condition(condition: &str, npc: &Npc, target: Option<&Player>) -> bool {
    match condition {
        "in_range"            => target.map_or(false, |p| npc.position.distance_to(&p.position) <= ATTACK_RANGE),
        "target_out_of_range" => target.map_or(true,  |p| npc.position.distance_to(&p.position) > ATTACK_RANGE),
        "no_target"           => target.is_none(),
        _                     => false,
    }
}

pub fn execute_action(ctx: &ReducerContext, npc: &Npc, action: &str, target: Option<&Player>) {
    match action {
        "move_toward_target" => {
            if let Some(player) = target {
                let (dx, dz) = direction_to(&npc.position, &player.position);
                let new_x = (npc.position.x + dx * NPC_CHASE_STEP).clamp(WORLD_MIN, WORLD_MAX);
                let new_z = (npc.position.z + dz * NPC_CHASE_STEP).clamp(WORLD_MIN, WORLD_MAX);
                ctx.db.npc().id().update(Npc {
                    position: Position { x: new_x, y: NPC_GROUND_Y, z: new_z },
                    ..(*npc).clone()
                });
            }
        }
        "attack_target" => {
            if let Some(player) = target {
                if npc.position.distance_to(&player.position) <= ATTACK_RANGE {
                    let new_health = player.health - ATTACK_DAMAGE;
                    if new_health <= 0 {
                        use crate::combat::respawn_player;
                        respawn_player(ctx, player);
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
                let (dx, dz) = direction_to(&npc.position, &player.position);
                let new_x = (npc.position.x - dx * NPC_CHASE_STEP).clamp(WORLD_MIN, WORLD_MAX);
                let new_z = (npc.position.z - dz * NPC_CHASE_STEP).clamp(WORLD_MIN, WORLD_MAX);
                ctx.db.npc().id().update(Npc {
                    position: Position { x: new_x, y: NPC_GROUND_Y, z: new_z },
                    ..(*npc).clone()
                });
            }
        }
        "wander" => {
            use spacetimedb::rand::Rng;
            let dx = (ctx.rng().gen::<f32>() * 2.0 - 1.0) * NPC_MOVE_RANGE;
            let dz = (ctx.rng().gen::<f32>() * 2.0 - 1.0) * NPC_MOVE_RANGE;
            let new_x = (npc.position.x + dx).clamp(WORLD_MIN, WORLD_MAX);
            let new_z = (npc.position.z + dz).clamp(WORLD_MIN, WORLD_MAX);
            ctx.db.npc().id().update(Npc {
                position: Position { x: new_x, y: NPC_GROUND_Y, z: new_z },
                ..(*npc).clone()
            });
        }
        _ => {}
    }
}

pub fn evaluate_graph(ctx: &ReducerContext, npc: &Npc, entry: &NpcBehaviourGraph) {
    use crate::combat::find_nearest_player;

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
    let target = find_nearest_player(ctx, &npc.position)
        .filter(|(_, d)| *d <= NPC_DETECTION_RANGE)
        .map(|(p, _)| p);
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
