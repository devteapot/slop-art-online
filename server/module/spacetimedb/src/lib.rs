mod constants;
mod tables;
mod skill;
mod combat;
mod npc_ai;
mod loot;

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
    pub target_x: f32,
    pub target_y: f32,
    pub target_z: f32,
    pub dir_x: f32,
    pub dir_z: f32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = projectile, public, scheduled(expire_projectile))]
pub struct Projectile {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub owner: Identity,
    pub skill_id: u64,
    pub start_x: f32,
    pub start_y: f32,
    pub start_z: f32,
    pub dir_x: f32,
    pub dir_z: f32,
    pub speed: f32,
    pub max_range: f32,
    pub power: i32,
    pub knockback: f32,
    pub hit_radius: f32,
    pub started_at: u64,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = ground_item, public, scheduled(expire_ground_item))]
pub struct GroundItem {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub item_def_id: u64,
    pub quantity: i32,
    pub position: Position,
    pub owner: Identity,
    pub free_for_all_at: u64,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = aoe_zone, public, scheduled(expire_aoe_zone))]
pub struct AoeZone {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
    pub owner: Identity,
    pub skill_id: u64,
    pub center_x: f32,
    pub center_y: f32,
    pub center_z: f32,
    pub radius: f32,
    pub power: i32,
    pub knockback: f32,
    pub tick_interval_ms: u64,
    pub last_tick_at: u64,
    pub started_at: u64,
}

#[spacetimedb::table(accessor = projectile_tick_schedule, scheduled(tick_projectiles))]
pub struct ProjectileTickSchedule {
    #[primary_key]
    #[auto_inc]
    pub scheduled_id: u64,
    pub scheduled_at: ScheduleAt,
}

// --- Scheduler helper ---

fn schedule_next_npc_tick(ctx: &ReducerContext) {
    let next = ctx.timestamp + Duration::from_millis(NPC_TICK_MS);
    ctx.db.npc_tick_schedule().insert(NpcTickSchedule {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(next),
    });
}

fn schedule_next_projectile_tick(ctx: &ReducerContext) {
    let next = ctx.timestamp + Duration::from_millis(PROJECTILE_TICK_MS);
    ctx.db.projectile_tick_schedule().insert(ProjectileTickSchedule {
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

    // Item definitions
    ctx.db.item_def().insert(ItemDef { id: 0, name: "Bone Fragment".into(),  item_type: ItemType::Material,   rarity: ItemRarity::Common,   max_stack: 20 });
    ctx.db.item_def().insert(ItemDef { id: 0, name: "Iron Ore".into(),      item_type: ItemType::Material,   rarity: ItemRarity::Common,   max_stack: 20 });
    ctx.db.item_def().insert(ItemDef { id: 0, name: "Health Potion".into(), item_type: ItemType::Consumable, rarity: ItemRarity::Common,   max_stack: 10 });
    ctx.db.item_def().insert(ItemDef { id: 0, name: "Enchanted Dust".into(),item_type: ItemType::Material,   rarity: ItemRarity::Uncommon, max_stack: 10 });
    ctx.db.item_def().insert(ItemDef { id: 0, name: "Dragon Scale".into(),  item_type: ItemType::Material,   rarity: ItemRarity::Rare,     max_stack: 5 });
    ctx.db.item_def().insert(ItemDef { id: 0, name: "Crystal Core".into(),  item_type: ItemType::Material,   rarity: ItemRarity::Epic,     max_stack: 1 });

    // Loot table entries (item_def_ids 1-6 from auto_inc order)
    ctx.db.loot_table_entry().insert(LootTableEntry { id: 0, item_def_id: 1, min_npc_level: 1, max_npc_level: 99, weight: 40, min_quantity: 1, max_quantity: 3 });
    ctx.db.loot_table_entry().insert(LootTableEntry { id: 0, item_def_id: 2, min_npc_level: 1, max_npc_level: 99, weight: 30, min_quantity: 1, max_quantity: 2 });
    ctx.db.loot_table_entry().insert(LootTableEntry { id: 0, item_def_id: 3, min_npc_level: 1, max_npc_level: 99, weight: 25, min_quantity: 1, max_quantity: 2 });
    ctx.db.loot_table_entry().insert(LootTableEntry { id: 0, item_def_id: 4, min_npc_level: 3, max_npc_level: 99, weight: 15, min_quantity: 1, max_quantity: 1 });
    ctx.db.loot_table_entry().insert(LootTableEntry { id: 0, item_def_id: 5, min_npc_level: 5, max_npc_level: 99, weight: 5,  min_quantity: 1, max_quantity: 1 });
    ctx.db.loot_table_entry().insert(LootTableEntry { id: 0, item_def_id: 6, min_npc_level: 8, max_npc_level: 99, weight: 1,  min_quantity: 1, max_quantity: 1 });

    schedule_next_npc_tick(ctx);
    schedule_next_projectile_tick(ctx);
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
                            r#"{{"npc_id":{},"npc_level":{},"npc_position":{{"x":{},"y":{},"z":{}}},"npc_health":{},"nearby_players":[{{"identity":"{}","position":{{"x":{},"y":{},"z":{}}},"distance":{}}}],"attack_range":{}}}"#,
                            npc.id, npc.level, npc.position.x, npc.position.y, npc.position.z, npc.health,
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
pub fn spawn_npc(ctx: &ReducerContext, x: f32, z: f32, level: i32) {
    let hp = npc_max_health(level);
    let npc = ctx.db.npc().insert(Npc {
        id: 0,
        position: Position { x: x.clamp(WORLD_MIN, WORLD_MAX), y: NPC_GROUND_Y, z: z.clamp(WORLD_MIN, WORLD_MAX) },
        health: hp,
        max_health: hp,
        level,
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
        let mh = player_max_health(existing.level);
        let mm = player_max_mana(existing.level);
        let ms = player_max_stamina(existing.level);
        ctx.db.player().identity().update(Player {
            position: Position { x: 0.0, y: 1.0, z: 0.0 },
            health: mh,
            max_health: mh,
            mana: mm,
            max_mana: mm,
            stamina: ms,
            max_stamina: ms,
            ..existing
        });
    } else {
        let mh = player_max_health(1);
        let mm = player_max_mana(1);
        let ms = player_max_stamina(1);
        ctx.db.player().insert(Player {
            identity: ctx.sender(),
            position: Position { x: 0.0, y: 1.0, z: 0.0 },
            health: mh,
            max_health: mh,
            level: 1,
            xp: 0,
            mana: mm,
            max_mana: mm,
            stamina: ms,
            max_stamina: ms,
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
    let new_health = target_player.health - PLAYER_BASE_ATTACK;
    if new_health <= 0 {
        respawn_player(ctx, &target_player);
        award_player_xp(ctx, &attacker, xp_for_player_kill(target_player.level));
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
    let new_health = target_npc.health - PLAYER_BASE_ATTACK;
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
                        hit_npc(ctx, &n, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id, SKILL_XP_PER_HIT);
                    } else {
                        hit_player(ctx, &p, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id, SKILL_XP_PER_HIT);
                    }
                }
                (Some(n), None) => hit_npc(ctx, &n, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id, SKILL_XP_PER_HIT),
                (None, Some(p)) => hit_player(ctx, &p, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id, SKILL_XP_PER_HIT),
                (None, None) => {}
            }
        }
        BehaviorType::Projectile => {
            // Compute direction from player toward cursor target on XZ plane
            let dx = target_pos.x - player.position.x;
            let dz = target_pos.z - player.position.z;
            let len = (dx * dx + dz * dz).sqrt();
            let (dir_x, dir_z) = if len > 0.001 { (dx / len, dz / len) } else { (0.0, -1.0) };

            let now_ms = (now_us / 1000) as u64;
            ctx.db.projectile().insert(Projectile {
                scheduled_id: 0,
                scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(PROJECTILE_MAX_LIFETIME_MS)),
                owner: ctx.sender(),
                skill_id,
                start_x: player.position.x,
                start_y: player.position.y,
                start_z: player.position.z,
                dir_x,
                dir_z,
                speed: PROJECTILE_SPEED,
                max_range: stats.range,
                power: stats.power,
                knockback: stats.knockback,
                hit_radius: PROJECTILE_HIT_RADIUS,
                started_at: now_ms,
            });
        }
        BehaviorType::GroundAoe => {
            if player.position.distance_to(&target_pos) > stats.range {
                return Err("Target out of range".to_string());
            }
            let radius = if stats.aoe_radius > 0.0 { stats.aoe_radius } else { 5.0 };
            let now_ms = (now_us / 1000) as u64;

            // Apply first tick immediately so the skill doesn't feel delayed
            for npc in ctx.db.npc().iter().collect::<Vec<_>>() {
                if npc.position.distance_to(&target_pos) <= radius {
                    hit_npc(ctx, &npc, stats.power, stats.knockback, &target_pos, ctx.sender(), skill_id, SKILL_XP_PER_HIT);
                }
            }
            for p in ctx.db.player().iter().collect::<Vec<_>>() {
                if p.identity != ctx.sender() && p.position.distance_to(&target_pos) <= radius {
                    hit_player(ctx, &p, stats.power, stats.knockback, &target_pos, ctx.sender(), skill_id, SKILL_XP_PER_HIT);
                }
            }

            // Insert lingering zone for periodic damage
            ctx.db.aoe_zone().insert(AoeZone {
                scheduled_id: 0,
                scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(AOE_DEFAULT_DURATION_MS)),
                owner: ctx.sender(),
                skill_id,
                center_x: target_pos.x,
                center_y: target_pos.y,
                center_z: target_pos.z,
                radius,
                power: stats.power,
                knockback: stats.knockback,
                tick_interval_ms: AOE_TICK_INTERVAL_MS,
                last_tick_at: now_ms,
                started_at: now_ms,
            });
        }
        BehaviorType::Buff => {
            let player = ctx.db.player().identity().find(&ctx.sender()).ok_or("Player not found")?;
            let new_health = (player.health + stats.power).min(player.max_health);
            let healed = new_health - player.health;
            ctx.db.player().identity().update(Player { health: new_health, ..player });
            if healed > 0 {
                award_skill_xp(ctx, ctx.sender(), skill_id, healed);
            }
        }
        BehaviorType::Mobility => {
            // Cooldown and resource already consumed above.
            // Client handles the visual effect (jump arc, dash movement, etc.).
        }
        BehaviorType::Targeted => {
            // Targeted skills use use_targeted_skill reducer instead.
            return Err("Targeted skills must use use_targeted_skill".to_string());
        }
    }

    // Mobility skills get XP on cast; damage skills get XP from hit_npc/hit_player; buff XP handled inline
    if skill_def.behavior_type == BehaviorType::Mobility {
        award_skill_xp(ctx, ctx.sender(), skill_id, SKILL_XP_PER_USE);
    }

    // Compute direction from player toward target for animations
    let dx = target_pos.x - player.position.x;
    let dz = target_pos.z - player.position.z;
    let len = (dx * dx + dz * dz).sqrt();
    let (anim_dir_x, anim_dir_z) = if len > 0.001 { (dx / len, dz / len) } else { (0.0, -1.0) };

    // Broadcast ability usage to all clients via ActiveSkill table.
    let anim_duration_ms: u64 = match skill_def.behavior_type {
        BehaviorType::Mobility => 800,
        BehaviorType::Melee => 500,
        BehaviorType::Projectile => 600,
        BehaviorType::GroundAoe => 700,
        BehaviorType::Buff => 500,
        BehaviorType::Targeted => 500,
    };
    ctx.db.active_skill().insert(ActiveSkill {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(anim_duration_ms)),
        player_identity: ctx.sender(),
        skill_id,
        started_at: now_us as u64,
        target_x: target_pos.x,
        target_y: target_pos.y,
        target_z: target_pos.z,
        dir_x: anim_dir_x,
        dir_z: anim_dir_z,
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

#[spacetimedb::reducer]
pub fn expire_projectile(_ctx: &ReducerContext, _row: Projectile) {
    // Row auto-deletes after this reducer completes.
}

#[spacetimedb::reducer]
pub fn expire_aoe_zone(_ctx: &ReducerContext, _row: AoeZone) {
    // Row auto-deletes after this reducer completes.
}

#[spacetimedb::reducer]
pub fn expire_ground_item(_ctx: &ReducerContext, _row: GroundItem) {
    // Row auto-deletes after this reducer completes.
}

#[spacetimedb::reducer]
pub fn tick_projectiles(ctx: &ReducerContext, _schedule: ProjectileTickSchedule) {
    let now_us = ctx.timestamp.to_duration_since_unix_epoch().unwrap_or_default().as_micros();
    let now_ms = (now_us / 1000) as u64;

    // Tick projectiles
    for proj in ctx.db.projectile().iter().collect::<Vec<_>>() {
        let elapsed_s = (now_ms.saturating_sub(proj.started_at)) as f32 / 1000.0;
        let dist = proj.speed * elapsed_s;

        // Current position
        let px = proj.start_x + proj.dir_x * dist;
        let pz = proj.start_z + proj.dir_z * dist;
        let proj_pos = Position { x: px, y: proj.start_y, z: pz };

        // Check if exceeded max range
        if dist > proj.max_range {
            ctx.db.projectile().scheduled_id().delete(&proj.scheduled_id);
            continue;
        }

        // Check collision against NPCs
        let mut hit = false;
        for npc in ctx.db.npc().iter().collect::<Vec<_>>() {
            if proj_pos.distance_to(&npc.position) <= proj.hit_radius {
                hit_npc(ctx, &npc, proj.power, proj.knockback, &proj_pos, proj.owner, proj.skill_id, SKILL_XP_PER_HIT);
                hit = true;
                break;
            }
        }
        if hit {
            ctx.db.projectile().scheduled_id().delete(&proj.scheduled_id);
            continue;
        }

        // Check collision against players (excluding owner)
        for p in ctx.db.player().iter().collect::<Vec<_>>() {
            if p.identity != proj.owner && proj_pos.distance_to(&p.position) <= proj.hit_radius {
                hit_player(ctx, &p, proj.power, proj.knockback, &proj_pos, proj.owner, proj.skill_id, SKILL_XP_PER_HIT);
                hit = true;
                break;
            }
        }
        if hit {
            ctx.db.projectile().scheduled_id().delete(&proj.scheduled_id);
        }
    }

    // Tick AoE zones
    for zone in ctx.db.aoe_zone().iter().collect::<Vec<_>>() {
        if now_ms.saturating_sub(zone.last_tick_at) >= zone.tick_interval_ms {
            let center = Position { x: zone.center_x, y: zone.center_y, z: zone.center_z };
            for npc in ctx.db.npc().iter().collect::<Vec<_>>() {
                if npc.position.distance_to(&center) <= zone.radius {
                    hit_npc(ctx, &npc, zone.power, zone.knockback, &center, zone.owner, zone.skill_id, SKILL_XP_PER_AOE_TICK);
                }
            }
            for p in ctx.db.player().iter().collect::<Vec<_>>() {
                if p.identity != zone.owner && p.position.distance_to(&center) <= zone.radius {
                    hit_player(ctx, &p, zone.power, zone.knockback, &center, zone.owner, zone.skill_id, SKILL_XP_PER_AOE_TICK);
                }
            }
            ctx.db.aoe_zone().scheduled_id().update(AoeZone { last_tick_at: now_ms, ..zone });
        }
    }

    schedule_next_projectile_tick(ctx);
}

#[spacetimedb::reducer]
pub fn start_projectile_ticker(ctx: &ReducerContext) {
    for s in ctx.db.projectile_tick_schedule().iter() {
        ctx.db.projectile_tick_schedule().scheduled_id().delete(&s.scheduled_id);
    }
    schedule_next_projectile_tick(ctx);
}

#[spacetimedb::reducer]
pub fn use_targeted_skill(ctx: &ReducerContext, skill_id: u64, target_kind: String, target_npc_id: u64, target_player_hex: String) -> Result<(), String> {
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

    let (target_x, target_y, target_z) = match target_kind.as_str() {
        "self" => {
            let current = ctx.db.player().identity().find(&ctx.sender()).ok_or("Player not found")?;
            let new_health = (player.health + stats.power).min(current.max_health);
            let healed = new_health - current.health;
            ctx.db.player().identity().update(Player { health: new_health, ..current });
            if healed > 0 {
                award_skill_xp(ctx, ctx.sender(), skill_id, healed);
            }
            (player.position.x, player.position.y, player.position.z)
        }
        "npc" => {
            let npc = ctx.db.npc().id().find(&target_npc_id).ok_or("NPC not found")?;
            if player.position.distance_to(&npc.position) > stats.range {
                return Err("Target out of range".to_string());
            }
            let pos = (npc.position.x, npc.position.y, npc.position.z);
            hit_npc(ctx, &npc, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id, SKILL_XP_PER_HIT);
            pos
        }
        "player" => {
            let target_identity = Identity::from_hex(&target_player_hex)
                .map_err(|_| "Invalid player identity".to_string())?;
            let target_player = ctx.db.player().identity().find(&target_identity)
                .ok_or("Target player not found")?;
            if player.position.distance_to(&target_player.position) > stats.range {
                return Err("Target out of range".to_string());
            }
            let pos = (target_player.position.x, target_player.position.y, target_player.position.z);
            hit_player(ctx, &target_player, stats.power, stats.knockback, &player.position, ctx.sender(), skill_id, SKILL_XP_PER_HIT);
            pos
        }
        _ => return Err(format!("Unknown target_kind: {target_kind}")),
    };

    let dx = target_x - player.position.x;
    let dz = target_z - player.position.z;
    let len = (dx * dx + dz * dz).sqrt();
    let (dir_x, dir_z) = if len > 0.001 { (dx / len, dz / len) } else { (0.0, -1.0) };

    ctx.db.active_skill().insert(ActiveSkill {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(500)),
        player_identity: ctx.sender(),
        skill_id,
        started_at: now_us as u64,
        target_x,
        target_y,
        target_z,
        dir_x,
        dir_z,
    });

    Ok(())
}
