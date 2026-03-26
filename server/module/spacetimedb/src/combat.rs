use spacetimedb::rand::Rng;
use spacetimedb::{Identity, ReducerContext, ScheduleAt, Table};
use std::time::Duration;

use crate::constants::*;
use crate::equipment::{degrade_armor, equipment_bonuses};
use crate::loot::{drop_all_inventory, generate_loot};
use crate::npc_ai::{build_default_combat_tree, log_npc_event, role_config, trigger_decision, trigger_emotion, upsert_npc_behavior};
use crate::tables::*;
use crate::skill::*;
use crate::{StatusEffect, status_effect, npc_event_log, npc_memory, GroundItem, ground_item,
    npc_inventory_item, npc_equipped_item, npc_goal, npc_belief, npc_relationship, npc_skill};

pub fn direction_to(from: &Position, to: &Position) -> (f32, f32) {
    let dx = to.x - from.x;
    let dz = to.z - from.z;
    let len = (dx * dx + dz * dz).sqrt();
    if len < 0.001 { (0.0, 0.0) } else { (dx / len, dz / len) }
}

pub fn apply_knockback(pos: &Position, from: &Position, knockback: f32) -> Position {
    if knockback <= 0.0 { return pos.clone(); }
    let (dx, dz) = direction_to(from, pos);
    Position {
        x: (pos.x + dx * knockback).clamp(WORLD_MIN, WORLD_MAX),
        y: pos.y,
        z: (pos.z + dz * knockback).clamp(WORLD_MIN, WORLD_MAX),
    }
}

pub fn apply_status_effect(
    ctx: &ReducerContext,
    effect_type: StatusEffectType,
    target_identity: Identity,
    target_npc_id: u64,
    power: i32,
    duration_ms: u64,
    source: Identity,
) {
    // Remove existing effect of same type on same target (no stacking)
    for existing in ctx.db.status_effect().iter().collect::<Vec<_>>() {
        if existing.effect_type == effect_type
            && existing.target_identity == target_identity
            && existing.target_npc_id == target_npc_id
        {
            ctx.db.status_effect().scheduled_id().delete(&existing.scheduled_id);
        }
    }
    ctx.db.status_effect().insert(StatusEffect {
        scheduled_id: 0,
        scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(duration_ms)),
        effect_type,
        target_identity,
        target_npc_id,
        power,
        source,
    });
}

fn clear_effects_for_player(ctx: &ReducerContext, identity: &Identity) {
    for e in ctx.db.status_effect().iter().collect::<Vec<_>>() {
        if e.target_identity == *identity && e.target_npc_id == 0 {
            ctx.db.status_effect().scheduled_id().delete(&e.scheduled_id);
        }
    }
}

fn clear_effects_for_npc(ctx: &ReducerContext, npc_id: u64) {
    for e in ctx.db.status_effect().iter().collect::<Vec<_>>() {
        if e.target_npc_id == npc_id {
            ctx.db.status_effect().scheduled_id().delete(&e.scheduled_id);
        }
    }
}

pub fn respawn_player(ctx: &ReducerContext, player: &Player) {
    drop_all_inventory(ctx, player);
    clear_effects_for_player(ctx, &player.identity);
    ctx.db.player().identity().update(Player {
        position: Position { x: 0.0, y: 1.0, z: 0.0 },
        health: player.max_health,
        mana: player.max_mana,
        stamina: player.max_stamina,
        ..player.clone()
    });
}

pub fn kill_npc(ctx: &ReducerContext, npc: &Npc, attacker: Identity) {
    let xp = xp_for_npc_kill(npc.level);

    // Drop NPC inventory as ground items (replaces loot table generation)
    let now_us = ctx.timestamp.to_duration_since_unix_epoch().unwrap_or_default().as_micros() as u64;
    let ffa_at = now_us + GROUND_ITEM_FFA_DELAY_MS * 1000;
    let mut dropped_anything = false;

    for inv in ctx.db.npc_inventory_item().iter().collect::<Vec<_>>() {
        if inv.npc_id == npc.id {
            let scatter_x: f32 = (ctx.rng().gen_range(0..100) as f32 / 100.0) - 0.5;
            let scatter_z: f32 = (ctx.rng().gen_range(0..100) as f32 / 100.0) - 0.5;
            ctx.db.ground_item().insert(GroundItem {
                scheduled_id: 0,
                scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(GROUND_ITEM_DESPAWN_MS)),
                item_def_id: inv.item_def_id,
                quantity: inv.quantity,
                position: Position {
                    x: npc.position.x + scatter_x,
                    y: npc.position.y,
                    z: npc.position.z + scatter_z,
                },
                owner: attacker,
                free_for_all_at: ffa_at,
            });
            ctx.db.npc_inventory_item().id().delete(&inv.id);
            dropped_anything = true;
        }
    }
    for eq in ctx.db.npc_equipped_item().iter().collect::<Vec<_>>() {
        if eq.npc_id == npc.id {
            let scatter_x: f32 = (ctx.rng().gen_range(0..100) as f32 / 100.0) - 0.5;
            let scatter_z: f32 = (ctx.rng().gen_range(0..100) as f32 / 100.0) - 0.5;
            ctx.db.ground_item().insert(GroundItem {
                scheduled_id: 0,
                scheduled_at: ScheduleAt::Time(ctx.timestamp + Duration::from_millis(GROUND_ITEM_DESPAWN_MS)),
                item_def_id: eq.item_def_id,
                quantity: 1,
                position: Position {
                    x: npc.position.x + scatter_x,
                    y: npc.position.y,
                    z: npc.position.z + scatter_z,
                },
                owner: attacker,
                free_for_all_at: ffa_at,
            });
            ctx.db.npc_equipped_item().id().delete(&eq.id);
            dropped_anything = true;
        }
    }

    // Fall back to loot table if NPC had no inventory
    if !dropped_anything {
        generate_loot(ctx, npc, attacker);
    }

    clear_effects_for_npc(ctx, npc.id);
    ctx.db.npc().id().delete(&npc.id);
    ctx.db.npc_behavior().npc_id().delete(&npc.id);
    ctx.db.npc_plan().npc_id().delete(&npc.id);
    ctx.db.npc_pending_decision().npc_id().delete(&npc.id);
    ctx.db.npc_destination().npc_id().delete(&npc.id);
    // Clean up NPC event logs and memories
    for evt in ctx.db.npc_event_log().iter().collect::<Vec<_>>() {
        if evt.npc_id == npc.id {
            ctx.db.npc_event_log().scheduled_id().delete(&evt.scheduled_id);
        }
    }
    for mem in ctx.db.npc_memory().iter().collect::<Vec<_>>() {
        if mem.npc_id == npc.id {
            ctx.db.npc_memory().id().delete(&mem.id);
        }
    }
    // Clean up BDI tables
    for goal in ctx.db.npc_goal().iter().collect::<Vec<_>>() {
        if goal.npc_id == npc.id {
            ctx.db.npc_goal().id().delete(&goal.id);
        }
    }
    for belief in ctx.db.npc_belief().iter().collect::<Vec<_>>() {
        if belief.npc_id == npc.id {
            ctx.db.npc_belief().id().delete(&belief.id);
        }
    }
    for rel in ctx.db.npc_relationship().iter().collect::<Vec<_>>() {
        if rel.npc_id == npc.id {
            ctx.db.npc_relationship().id().delete(&rel.id);
        }
    }
    for skill in ctx.db.npc_skill().iter().collect::<Vec<_>>() {
        if skill.npc_id == npc.id {
            ctx.db.npc_skill().id().delete(&skill.id);
        }
    }
    if let Some(player) = ctx.db.player().identity().find(&attacker) {
        award_player_xp(ctx, &player, xp);
    }
}

pub fn award_player_xp(ctx: &ReducerContext, player: &Player, amount: i32) {
    let mut new_xp = player.xp + amount;
    let mut new_level = player.level;
    let old_level = player.level;
    loop {
        let threshold = player_xp_threshold(new_level);
        if new_xp >= threshold { new_xp -= threshold; new_level += 1; } else { break; }
    }
    let leveled_up = new_level > old_level;
    let new_max_health = player_max_health(new_level);
    let new_max_mana = player_max_mana(new_level);
    let new_max_stamina = player_max_stamina(new_level);
    ctx.db.player().identity().update(Player {
        xp: new_xp,
        level: new_level,
        max_health: new_max_health,
        max_mana: new_max_mana,
        max_stamina: new_max_stamina,
        health: if leveled_up { new_max_health } else { player.health },
        mana: if leveled_up { new_max_mana } else { player.mana },
        stamina: if leveled_up { new_max_stamina } else { player.stamina },
        ..player.clone()
    });
}

pub fn award_skill_xp(ctx: &ReducerContext, player_identity: Identity, skill_id: u64, amount: i32) {
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

pub fn give_all_skills(ctx: &ReducerContext, player_identity: Identity) {
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

pub fn hit_npc(
    ctx: &ReducerContext, npc: &Npc, power: i32, knockback: f32, from: &Position,
    attacker: Identity, skill_id: u64, hit_xp: i32,
    effect: Option<(StatusEffectType, i32, u64)>,
) {
    award_skill_xp(ctx, attacker, skill_id, hit_xp);
    let new_pos = apply_knockback(&npc.position, from, knockback);
    let new_health = npc.health - power;
    if new_health <= 0 {
        kill_npc(ctx, npc, attacker);
        award_skill_xp(ctx, attacker, skill_id, SKILL_XP_PER_KILL);
    } else {
        ctx.db.npc().id().update(Npc { position: new_pos, health: new_health, ..npc.clone() });
        if let Some((etype, epower, edur)) = effect {
            apply_status_effect(ctx, etype, attacker, npc.id, epower, edur, attacker);
        }

        // Log damage event
        log_npc_event(ctx, npc.id, "took_damage",
            &format!(r#"{{"player":"{}","damage":{}}}"#, attacker.to_hex().to_string(), power));

        // Emotion: taking damage causes anger + fear
        trigger_emotion(ctx, npc.id, "anger", 0.3);
        trigger_emotion(ctx, npc.id, "fear", 0.2);

        // Non-hostile NPCs enter combat when hit (if aggro_on_hit)
        let config = role_config(&npc.role);
        if config.aggro_on_hit {
            if let Some(beh) = ctx.db.npc_behavior().npc_id().find(&npc.id) {
                if beh.mode != "combat" {
                    let default = build_default_combat_tree(&config.default_tree_style);
                    let tree_json = serde_json::to_string(&default).unwrap();
                    upsert_npc_behavior(ctx, npc.id, "combat", &tree_json);
                    // Look up attacker as target for decision context
                    let attacker_player = ctx.db.player().identity().find(&attacker);
                    trigger_decision(ctx, npc, "combat_start", attacker_player.as_ref());
                }
            }
        }
    }
}

pub fn hit_player(
    ctx: &ReducerContext, target: &Player, power: i32, knockback: f32, from: &Position,
    attacker: Identity, skill_id: u64, hit_xp: i32,
    effect: Option<(StatusEffectType, i32, u64)>,
) {
    award_skill_xp(ctx, attacker, skill_id, hit_xp);
    let new_pos = apply_knockback(&target.position, from, knockback);
    let defense = equipment_bonuses(ctx, &target.identity).defense;
    let effective_power = (power - defense).max(1);
    let new_health = target.health - effective_power;
    if new_health <= 0 {
        respawn_player(ctx, target);
        if let Some(attacker_player) = ctx.db.player().identity().find(&attacker) {
            award_player_xp(ctx, &attacker_player, xp_for_player_kill(target.level));
        }
        award_skill_xp(ctx, attacker, skill_id, SKILL_XP_PER_KILL);
    } else {
        ctx.db.player().identity().update(Player { position: new_pos, health: new_health, ..target.clone() });
        degrade_armor(ctx, &target.identity);
        if let Some((etype, epower, edur)) = effect {
            apply_status_effect(ctx, etype, target.identity, 0, epower, edur, attacker);
        }
    }
}

pub fn find_nearest_player(ctx: &ReducerContext, pos: &Position) -> Option<(Player, f32)> {
    ctx.db.player().iter()
        .map(|p| { let d = pos.distance_to(&p.position); (p, d) })
        .min_by(|a, b| a.1.partial_cmp(&b.1).unwrap())
}
