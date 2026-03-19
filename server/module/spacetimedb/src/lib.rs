mod constants;
mod tables;
mod skill;
mod combat;
mod npc_ai;

use spacetimedb::{Identity, ReducerContext, ScheduleAt, Table};
use std::time::Duration;

use crate::constants::*;
use crate::tables::*;
use crate::skill::*;
use crate::combat::*;
use crate::npc_ai::*;

// --- NPC tick schedule (must live here alongside tick_npcs reducer) ---

#[spacetimedb::table(accessor = npc_tick_schedule, scheduled(tick_npcs))]
pub struct NpcTickSchedule {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = active_skill, public, scheduled(expire_active_skill))]
pub struct ActiveSkill {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub player_identity: Identity,
    pub skill_id: u64,
    pub started_at: u64,
}

// --- Scheduler helper ---

fn schedule_next_npc_tick(ctx: &ReducerContext) {
    let next = ctx.timestamp + Duration::from_millis(NPC_TICK_MS);
    ctx.db.npc_tick_schedule().insert(NpcTickSchedule {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(next),
    });
}

// --- Reducers ---

#[spacetimedb::reducer(init)]
pub fn init(ctx: &ReducerContext) {
    ctx.db.skill_def().insert(SkillDef { id: 0, name: "Strike".to_string(),    behavior_type: BehaviorType::Melee,      resource_type: ResourceType::Stamina });
    ctx.db.skill_def().insert(SkillDef { id: 0, name: "Fireball".to_string(),  behavior_type: BehaviorType::Projectile, resource_type: ResourceType::Mana });
    ctx.db.skill_def().insert(SkillDef { id: 0, name: "Shockwave".to_string(), behavior_type: BehaviorType::GroundAoe,  resource_type: ResourceType::Mana });
    ctx.db.skill_def().insert(SkillDef { id: 0, name: "Heal".to_string(),      behavior_type: BehaviorType::Buff,       resource_type: ResourceType::Mana });
    ctx.db.skill_def().insert(SkillDef { id: 0, name: "Jump".to_string(),      behavior_type: BehaviorType::Mobility,   resource_type: ResourceType::Stamina });
    ctx.db.skill_def().insert(SkillDef { id: 0, name: "Dash".to_string(),      behavior_type: BehaviorType::Mobility,   resource_type: ResourceType::Stamina });
    schedule_next_npc_tick(ctx);
}

#[spacetimedb::reducer]
pub fn start_npc_ticker(ctx: &ReducerContext) {
    for s in ctx.db.npc_tick_schedule().iter() {
        ctx.db.npc_tick_schedule().scheduled_id().delete(&s.scheduled_id);
    }
    schedule_next_npc_tick(ctx);
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
            facing_angle: 0.0,
            last_seq: 0,
        });
        give_all_skills(ctx, ctx.sender());
    }
}

#[spacetimedb::reducer(client_disconnected)]
pub fn identity_disconnected(ctx: &ReducerContext) {
    ctx.db.player().identity().delete(&ctx.sender());
}

#[spacetimedb::reducer]
pub fn move_player(ctx: &ReducerContext, x: f32, y: f32, z: f32, seq: u32) -> Result<(), String> {
    let player = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Player not found")?;

    // Simple anti-teleport: reject moves beyond MAX_MOVE_DIST on the XZ plane.
    let dx = x - player.position.x;
    let dz = z - player.position.z;
    if (dx * dx + dz * dz).sqrt() > MAX_MOVE_DIST {
        return Err("Moved too far".to_string());
    }

    ctx.db.player().identity().update(Player {
        position: Position {
            x: x.clamp(WORLD_MIN, WORLD_MAX),
            y,
            z: z.clamp(WORLD_MIN, WORLD_MAX),
        },
        last_seq: seq,
        ..player
    });
    Ok(())
}

#[spacetimedb::reducer]
pub fn rotate_player(ctx: &ReducerContext, angle: f32) -> Result<(), String> {
    let player = ctx.db.player().identity().find(&ctx.sender())
        .ok_or("Player not found")?;
    ctx.db.player().identity().update(Player {
        facing_angle: angle,
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
            let player = ctx.db.player().identity().find(&ctx.sender()).ok_or("Player not found")?;
            let new_health = (player.health + stats.power).min(MAX_HEALTH);
            ctx.db.player().identity().update(Player { health: new_health, ..player });
        }
        BehaviorType::Mobility => {
            // Cooldown and resource already consumed above.
            // Client handles the visual effect (jump arc, dash movement, etc.).
        }
    }

    award_skill_xp(ctx, ctx.sender(), skill_id, SKILL_XP_PER_USE);

    // Broadcast ability usage to all clients via ActiveSkill table.
    let anim_duration_ms: u64 = match skill_def.behavior_type {
        BehaviorType::Mobility => 800,
        BehaviorType::Melee => 500,
        BehaviorType::Projectile => 600,
        BehaviorType::GroundAoe => 700,
        BehaviorType::Buff => 500,
    };
    ctx.db.active_skill().insert(ActiveSkill {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(anim_duration_ms)),
        player_identity: ctx.sender(),
        skill_id,
        started_at: now_us as u64,
    });

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

#[spacetimedb::reducer]
pub fn expire_active_skill(_ctx: &ReducerContext, _row: ActiveSkill) {
    // Row auto-deletes after this reducer completes.
}
