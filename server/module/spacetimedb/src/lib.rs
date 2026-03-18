use spacetimedb::{Identity, ReducerContext, ScheduleAt, SpacetimeType, Table, Timestamp};
use spacetimedb::rand::Rng;
use std::time::Duration;

// --- Constants ---

const WORLD_MIN: f32 = -500.0;
const WORLD_MAX: f32 = 500.0;
const NPC_MOVE_RANGE: f32 = 3.0;
const NPC_CHASE_STEP: f32 = 3.0;
const NPC_TICK_MS: u64 = 500;
const NPC_DETECTION_RANGE: f32 = 30.0;
const NPC_GROUND_Y: f32 = 0.9;
const MAX_HEALTH: i32 = 100;
const MAX_MANA: i32 = 100;
const MAX_STAMINA: i32 = 100;
const MANA_REGEN_PER_TICK: i32 = 3;
const STAMINA_REGEN_PER_TICK: i32 = 3;
const ATTACK_DAMAGE: i32 = 10;
const ATTACK_RANGE: f32 = 3.0;
const POINTS_PER_LEVEL: i32 = 5;
const SKILL_XP_PER_USE: i32 = 10;
const SKILL_XP_PER_KILL: i32 = 25;
const PLAYER_XP_PER_NPC_KILL: i32 = 50;
const PLAYER_XP_PER_PLAYER_KILL: i32 = 100;

// --- Types ---

#[derive(SpacetimeType, Clone, Debug)]
pub struct Position {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Position {
    fn distance_to(&self, other: &Position) -> f32 {
        let dx = self.x - other.x;
        let dy = self.y - other.y;
        let dz = self.z - other.z;
        (dx * dx + dy * dy + dz * dz).sqrt()
    }
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub enum BehaviorType {
    Melee,
    Projectile,
    GroundAoe,
    Buff,
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub enum ResourceType {
    Mana,
    Stamina,
}

// --- Tables ---

#[derive(Clone)]
#[spacetimedb::table(accessor = player, public)]
pub struct Player {
    #[primary_key]
    pub identity: Identity,
    pub position: Position,
    pub health: i32,
    pub level: i32,
    pub xp: i32,
    pub mana: i32,
    pub max_mana: i32,
    pub stamina: i32,
    pub max_stamina: i32,
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

#[derive(Clone)]
#[spacetimedb::table(accessor = skill_def, public)]
pub struct SkillDef {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub name: String,
    pub behavior_type: BehaviorType,
    pub resource_type: ResourceType,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = player_skill, public)]
pub struct PlayerSkill {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub player_identity: Identity,
    pub skill_id: u64,
    pub level: i32,
    pub xp: i32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = skill_attributes, public)]
pub struct SkillAttributes {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub player_identity: Identity,
    pub skill_id: u64,
    pub damage_points: i32,
    pub cooldown_points: i32,
    pub aoe_points: i32,
    pub range_points: i32,
    pub duration_points: i32,
    pub projectile_count_points: i32,
    pub knockback_points: i32,
    pub resource_cost_points: i32,
    pub cast_speed_points: i32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = skill_cooldown, public)]
pub struct SkillCooldown {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub player_identity: Identity,
    pub skill_id: u64,
    pub ready_at: Timestamp,
}

// --- Behaviour graph (internal) ---

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

// --- Skill stats ---

struct SkillStats {
    power: i32,
    cooldown_ms: u64,
    aoe_radius: f32,
    range: f32,
    knockback: f32,
    resource_cost: i32,
}

fn compute_stats(attrs: &SkillAttributes) -> SkillStats {
    SkillStats {
        power: 15 + attrs.damage_points * 5,
        cooldown_ms: 3000u64.saturating_sub(attrs.cooldown_points as u64 * 150).max(500),
        aoe_radius: attrs.aoe_points as f32 * 0.8,
        range: 5.0 + attrs.range_points as f32 * 1.5,
        knockback: attrs.knockback_points as f32 * 0.5,
        resource_cost: (25 - attrs.resource_cost_points * 2).max(5),
    }
}

fn total_skill_points(level: i32) -> i32 { level * POINTS_PER_LEVEL }

fn points_allocated(attrs: &SkillAttributes) -> i32 {
    attrs.damage_points + attrs.cooldown_points + attrs.aoe_points +
    attrs.range_points + attrs.duration_points + attrs.projectile_count_points +
    attrs.knockback_points + attrs.resource_cost_points + attrs.cast_speed_points
}

fn skill_xp_threshold(level: i32) -> i32 { level * 50 }
fn player_xp_threshold(level: i32) -> i32 { level * 100 }

// --- Helpers ---

fn direction_to(from: &Position, to: &Position) -> (f32, f32) {
    let dx = to.x - from.x;
    let dz = to.z - from.z;
    let len = (dx * dx + dz * dz).sqrt();
    if len < 0.001 { (0.0, 0.0) } else { (dx / len, dz / len) }
}

fn apply_knockback(pos: &Position, from: &Position, knockback: f32) -> Position {
    if knockback <= 0.0 { return pos.clone(); }
    let (dx, dz) = direction_to(from, pos);
    Position {
        x: (pos.x + dx * knockback).clamp(WORLD_MIN, WORLD_MAX),
        y: pos.y,
        z: (pos.z + dz * knockback).clamp(WORLD_MIN, WORLD_MAX),
    }
}

fn respawn_player(ctx: &ReducerContext, player: &Player) {
    ctx.db.player().identity().update(Player {
        position: Position { x: 0.0, y: 1.0, z: 0.0 },
        health: MAX_HEALTH,
        mana: player.max_mana,
        stamina: player.max_stamina,
        ..player.clone()
    });
}

fn kill_npc(ctx: &ReducerContext, npc: &Npc, attacker: Identity) {
    ctx.db.npc().id().delete(&npc.id);
    ctx.db.npc_behaviour_graph().npc_id().delete(&npc.id);
    ctx.db.npc_pending_decision().npc_id().delete(&npc.id);
    if let Some(player) = ctx.db.player().identity().find(&attacker) {
        award_player_xp(ctx, &player, PLAYER_XP_PER_NPC_KILL);
    }
}

fn award_player_xp(ctx: &ReducerContext, player: &Player, amount: i32) {
    let mut new_xp = player.xp + amount;
    let mut new_level = player.level;
    loop {
        let threshold = player_xp_threshold(new_level);
        if new_xp >= threshold { new_xp -= threshold; new_level += 1; } else { break; }
    }
    ctx.db.player().identity().update(Player { xp: new_xp, level: new_level, ..player.clone() });
}

fn award_skill_xp(ctx: &ReducerContext, player_identity: Identity, skill_id: u64, amount: i32) {
    let Some(ps) = ctx.db.player_skill().iter()
        .find(|ps| ps.player_identity == player_identity && ps.skill_id == skill_id)
    else { return };
    let mut new_xp = ps.xp + amount;
    let mut new_level = ps.level;
    loop {
        let threshold = skill_xp_threshold(new_level);
        if new_xp >= threshold { new_xp -= threshold; new_level += 1; } else { break; }
    }
    ctx.db.player_skill().id().update(PlayerSkill { xp: new_xp, level: new_level, ..ps });
}

fn give_all_skills(ctx: &ReducerContext, player_identity: Identity) {
    for skill in ctx.db.skill_def().iter() {
        ctx.db.player_skill().insert(PlayerSkill {
            id: 0, player_identity, skill_id: skill.id, level: 1, xp: 0,
        });
        ctx.db.skill_attributes().insert(SkillAttributes {
            id: 0, player_identity, skill_id: skill.id,
            damage_points: 0, cooldown_points: 0, aoe_points: 0,
            range_points: 0, duration_points: 0, projectile_count_points: 0,
            knockback_points: 0, resource_cost_points: 0, cast_speed_points: 0,
        });
    }
}

fn hit_npc(ctx: &ReducerContext, npc: &Npc, power: i32, knockback: f32, from: &Position, attacker: Identity, skill_id: u64) {
    let new_pos = apply_knockback(&npc.position, from, knockback);
    let new_health = npc.health - power;
    if new_health <= 0 {
        kill_npc(ctx, npc, attacker);
        award_skill_xp(ctx, attacker, skill_id, SKILL_XP_PER_KILL);
    } else {
        ctx.db.npc().id().update(Npc { position: new_pos, health: new_health, ..npc.clone() });
    }
}

fn hit_player(ctx: &ReducerContext, target: &Player, power: i32, knockback: f32, from: &Position, attacker: Identity, skill_id: u64) {
    let new_pos = apply_knockback(&target.position, from, knockback);
    let new_health = target.health - power;
    if new_health <= 0 {
        respawn_player(ctx, target);
        if let Some(attacker_player) = ctx.db.player().identity().find(&attacker) {
            award_player_xp(ctx, &attacker_player, PLAYER_XP_PER_PLAYER_KILL);
        }
        award_skill_xp(ctx, attacker, skill_id, SKILL_XP_PER_KILL);
    } else {
        ctx.db.player().identity().update(Player { position: new_pos, health: new_health, ..target.clone() });
    }
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

// --- Reducers ---

#[spacetimedb::reducer(init)]
pub fn init(ctx: &ReducerContext) {
    ctx.db.skill_def().insert(SkillDef { id: 0, name: "Strike".to_string(),    behavior_type: BehaviorType::Melee,      resource_type: ResourceType::Stamina });
    ctx.db.skill_def().insert(SkillDef { id: 0, name: "Fireball".to_string(),  behavior_type: BehaviorType::Projectile, resource_type: ResourceType::Mana });
    ctx.db.skill_def().insert(SkillDef { id: 0, name: "Shockwave".to_string(), behavior_type: BehaviorType::GroundAoe,  resource_type: ResourceType::Mana });
    ctx.db.skill_def().insert(SkillDef { id: 0, name: "Heal".to_string(),      behavior_type: BehaviorType::Buff,       resource_type: ResourceType::Mana });
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
    // Regen player resources
    for player in ctx.db.player().iter().collect::<Vec<_>>() {
        let new_mana = (player.mana + MANA_REGEN_PER_TICK).min(player.max_mana);
        let new_stamina = (player.stamina + STAMINA_REGEN_PER_TICK).min(player.max_stamina);
        if new_mana != player.mana || new_stamina != player.stamina {
            ctx.db.player().identity().update(Player { mana: new_mana, stamina: new_stamina, ..player });
        }
    }

    for npc in ctx.db.npc().iter() {
        if let Some(graph_entry) = ctx.db.npc_behaviour_graph().npc_id().find(&npc.id) {
            let has_pending = ctx.db.npc_pending_decision().npc_id().find(&npc.id).is_some();
            if !has_pending && graph_entry.current_node == "idle" {
                if let Some((player, dist)) = find_nearest_player(ctx, &npc.position) {
                    if dist <= NPC_DETECTION_RANGE {
                        let context = format!(
                            r#"{{"npc_id":{},"npc_position":{{"x":{},"y":{},"z":{}}},"npc_health":{},"nearby_players":[{{"identity":"{}","position":{{"x":{},"y":{},"z":{}}},"distance":{}}}],"attack_range":{}}}"#,
                            npc.id, npc.position.x, npc.position.y, npc.position.z, npc.health,
                            player.identity.to_hex().to_string(),
                            player.position.x, player.position.y, player.position.z, dist,
                            ATTACK_RANGE
                        );
                        ctx.db.npc_pending_decision().insert(NpcPendingDecision { npc_id: npc.id, context });
                    }
                }
            }
            evaluate_graph(ctx, &npc, &graph_entry);
        }
    }
    schedule_next_npc_tick(ctx);
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
pub fn submit_npc_graph(ctx: &ReducerContext, npc_id: u64, graph_json: String) -> Result<(), String> {
    ctx.db.npc().id().find(&npc_id).ok_or("NPC not found")?;
    let graph: BehaviourGraph = serde_json::from_str(&graph_json)
        .map_err(|e| format!("Invalid graph JSON: {e}"))?;
    let npc = ctx.db.npc().id().find(&npc_id).ok_or("NPC not found")?;
    let start_node = find_nearest_player(ctx, &npc.position)
        .filter(|(_, d)| *d <= NPC_DETECTION_RANGE)
        .map(|(_, d)| if d <= ATTACK_RANGE { "attacking" } else { "chasing" })
        .unwrap_or(&graph.initial_node)
        .to_string();
    if ctx.db.npc_behaviour_graph().npc_id().find(&npc_id).is_some() {
        ctx.db.npc_behaviour_graph().npc_id().update(NpcBehaviourGraph {
            npc_id, current_node: start_node, graph: graph_json,
        });
    } else {
        ctx.db.npc_behaviour_graph().insert(NpcBehaviourGraph {
            npc_id, current_node: start_node, graph: graph_json,
        });
    }
    ctx.db.npc_pending_decision().npc_id().delete(&npc_id);
    Ok(())
}

#[spacetimedb::reducer]
pub fn spawn_npc(ctx: &ReducerContext, x: f32, z: f32) {
    let npc = ctx.db.npc().insert(Npc {
        id: 0,
        position: Position { x: x.clamp(WORLD_MIN, WORLD_MAX), y: NPC_GROUND_Y, z: z.clamp(WORLD_MIN, WORLD_MAX) },
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
    if let Some(existing) = ctx.db.player().identity().find(&ctx.sender()) {
        ctx.db.player().identity().update(Player {
            position: Position { x: 0.0, y: 1.0, z: 0.0 },
            health: MAX_HEALTH,
            mana: existing.max_mana,
            stamina: existing.max_stamina,
            ..existing
        });
    } else {
        ctx.db.player().insert(Player {
            identity: ctx.sender(),
            position: Position { x: 0.0, y: 1.0, z: 0.0 },
            health: MAX_HEALTH,
            level: 1,
            xp: 0,
            mana: MAX_MANA,
            max_mana: MAX_MANA,
            stamina: MAX_STAMINA,
            max_stamina: MAX_STAMINA,
        });
        give_all_skills(ctx, ctx.sender());
    }
}

#[spacetimedb::reducer(client_disconnected)]
pub fn identity_disconnected(ctx: &ReducerContext) {
    ctx.db.player().identity().delete(&ctx.sender());
}

#[spacetimedb::reducer]
pub fn move_player(ctx: &ReducerContext, x: f32, y: f32, z: f32) -> Result<(), String> {
    let player = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Player not found")?;
    ctx.db.player().identity().update(Player {
        position: Position {
            x: x.clamp(WORLD_MIN, WORLD_MAX),
            y,
            z: z.clamp(WORLD_MIN, WORLD_MAX),
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
        respawn_player(ctx, &target_player);
        award_player_xp(ctx, &attacker, PLAYER_XP_PER_PLAYER_KILL);
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
        kill_npc(ctx, &target_npc, ctx.sender());
    } else {
        ctx.db.npc().id().update(Npc { health: new_health, ..target_npc });
    }
    Ok(())
}

#[spacetimedb::reducer]
pub fn use_skill(ctx: &ReducerContext, skill_id: u64, target_x: f32, target_y: f32, target_z: f32) -> Result<(), String> {
    let player = ctx.db.player().identity().find(&ctx.sender()).ok_or("Player not found")?;
    let skill_def = ctx.db.skill_def().id().find(&skill_id).ok_or("Skill not found")?;

    let _ = ctx.db.player_skill().iter()
        .find(|ps| ps.player_identity == ctx.sender() && ps.skill_id == skill_id)
        .ok_or("Skill not available")?;

    let attrs = ctx.db.skill_attributes().iter()
        .find(|a| a.player_identity == ctx.sender() && a.skill_id == skill_id)
        .ok_or("Skill attributes not found")?;

    let stats = compute_stats(&attrs);

    // Check cooldown
    let now_us = ctx.timestamp.to_duration_since_unix_epoch().unwrap_or_default().as_micros();
    if let Some(cd) = ctx.db.skill_cooldown().iter()
        .find(|cd| cd.player_identity == ctx.sender() && cd.skill_id == skill_id)
    {
        let ready_us = cd.ready_at.to_duration_since_unix_epoch().unwrap_or_default().as_micros();
        if now_us < ready_us {
            return Err("Skill on cooldown".to_string());
        }
    }

    // Check and deduct resource
    match skill_def.resource_type {
        ResourceType::Mana => {
            if player.mana < stats.resource_cost { return Err("Not enough mana".to_string()); }
            ctx.db.player().identity().update(Player { mana: player.mana - stats.resource_cost, ..player.clone() });
        }
        ResourceType::Stamina => {
            if player.stamina < stats.resource_cost { return Err("Not enough stamina".to_string()); }
            ctx.db.player().identity().update(Player { stamina: player.stamina - stats.resource_cost, ..player.clone() });
        }
    }

    // Set cooldown
    let ready_at = ctx.timestamp + Duration::from_millis(stats.cooldown_ms);
    if let Some(cd) = ctx.db.skill_cooldown().iter()
        .find(|cd| cd.player_identity == ctx.sender() && cd.skill_id == skill_id)
    {
        ctx.db.skill_cooldown().id().update(SkillCooldown { ready_at, ..cd });
    } else {
        ctx.db.skill_cooldown().insert(SkillCooldown { id: 0, player_identity: ctx.sender(), skill_id, ready_at });
    }

    let target_pos = Position { x: target_x, y: target_y, z: target_z };

    match skill_def.behavior_type {
        BehaviorType::Melee => {
            // Nearest entity to the player within range
            let nearest_npc = ctx.db.npc().iter()
                .filter(|n| n.position.distance_to(&player.position) <= stats.range)
                .min_by(|a, b| a.position.distance_to(&player.position)
                    .partial_cmp(&b.position.distance_to(&player.position)).unwrap());
            let nearest_player = ctx.db.player().iter()
                .filter(|p| p.identity != ctx.sender())
                .filter(|p| p.position.distance_to(&player.position) <= stats.range)
                .min_by(|a, b| a.position.distance_to(&player.position)
                    .partial_cmp(&b.position.distance_to(&player.position)).unwrap());
            match (nearest_npc, nearest_player) {
                (Some(n), Some(p)) => {
                    if n.position.distance_to(&player.position) <= p.position.distance_to(&player.position) {
                        hit_npc(ctx, &n, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id);
                    } else {
                        hit_player(ctx, &p, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id);
                    }
                }
                (Some(n), None) => hit_npc(ctx, &n, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id),
                (None, Some(p)) => hit_player(ctx, &p, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id),
                (None, None) => {}
            }
        }
        BehaviorType::Projectile => {
            // Nearest entity to target_pos within range of player
            let nearest_npc = ctx.db.npc().iter()
                .filter(|n| n.position.distance_to(&player.position) <= stats.range)
                .min_by(|a, b| a.position.distance_to(&target_pos)
                    .partial_cmp(&b.position.distance_to(&target_pos)).unwrap());
            let nearest_player = ctx.db.player().iter()
                .filter(|p| p.identity != ctx.sender())
                .filter(|p| p.position.distance_to(&player.position) <= stats.range)
                .min_by(|a, b| a.position.distance_to(&target_pos)
                    .partial_cmp(&b.position.distance_to(&target_pos)).unwrap());
            match (nearest_npc, nearest_player) {
                (Some(n), Some(p)) => {
                    if n.position.distance_to(&target_pos) <= p.position.distance_to(&target_pos) {
                        hit_npc(ctx, &n, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id);
                    } else {
                        hit_player(ctx, &p, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id);
                    }
                }
                (Some(n), None) => hit_npc(ctx, &n, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id),
                (None, Some(p)) => hit_player(ctx, &p, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id),
                (None, None) => {}
            }
        }
        BehaviorType::GroundAoe => {
            if player.position.distance_to(&target_pos) > stats.range {
                return Err("Target out of range".to_string());
            }
            let radius = if stats.aoe_radius > 0.0 { stats.aoe_radius } else { stats.range };
            for npc in ctx.db.npc().iter().collect::<Vec<_>>() {
                if npc.position.distance_to(&target_pos) <= radius {
                    hit_npc(ctx, &npc, stats.power, stats.knockback, &target_pos, ctx.sender(), skill_id);
                }
            }
            for p in ctx.db.player().iter().collect::<Vec<_>>() {
                if p.identity != ctx.sender() && p.position.distance_to(&target_pos) <= radius {
                    hit_player(ctx, &p, stats.power, stats.knockback, &target_pos, ctx.sender(), skill_id);
                }
            }
        }
        BehaviorType::Buff => {
            // Re-fetch player for fresh health after resource deduction
            let player = ctx.db.player().identity().find(&ctx.sender()).ok_or("Player not found")?;
            let new_health = (player.health + stats.power).min(MAX_HEALTH);
            ctx.db.player().identity().update(Player { health: new_health, ..player });
        }
    }

    award_skill_xp(ctx, ctx.sender(), skill_id, SKILL_XP_PER_USE);
    Ok(())
}

#[spacetimedb::reducer]
pub fn allocate_skill_point(ctx: &ReducerContext, skill_id: u64, attribute: String) -> Result<(), String> {
    let ps = ctx.db.player_skill().iter()
        .find(|ps| ps.player_identity == ctx.sender() && ps.skill_id == skill_id)
        .ok_or("Skill not found")?;

    let attrs = ctx.db.skill_attributes().iter()
        .find(|a| a.player_identity == ctx.sender() && a.skill_id == skill_id)
        .ok_or("Skill attributes not found")?;

    if points_allocated(&attrs) >= total_skill_points(ps.level) {
        return Err("No unspent points".to_string());
    }

    let mut new_attrs = attrs.clone();
    match attribute.as_str() {
        "damage"           => new_attrs.damage_points += 1,
        "cooldown"         => new_attrs.cooldown_points += 1,
        "aoe"              => new_attrs.aoe_points += 1,
        "range"            => new_attrs.range_points += 1,
        "duration"         => new_attrs.duration_points += 1,
        "projectile_count" => new_attrs.projectile_count_points += 1,
        "knockback"        => new_attrs.knockback_points += 1,
        "resource_cost"    => new_attrs.resource_cost_points += 1,
        "cast_speed"       => new_attrs.cast_speed_points += 1,
        _ => return Err(format!("Unknown attribute: {attribute}")),
    }
    ctx.db.skill_attributes().id().update(new_attrs);
    Ok(())
}
