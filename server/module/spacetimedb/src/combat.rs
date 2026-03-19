use spacetimedb::{Identity, ReducerContext, ScheduleAt, Table};
use std::time::Duration;

use crate::constants::*;
use crate::equipment::{degrade_armor, equipment_bonuses};
use crate::loot::{drop_all_inventory, generate_loot};
use crate::tables::*;
use crate::skill::*;
use crate::{StatusEffect, status_effect};

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
    generate_loot(ctx, npc, attacker);
    clear_effects_for_npc(ctx, npc.id);
    ctx.db.npc().id().delete(&npc.id);
    ctx.db.npc_behaviour_graph().npc_id().delete(&npc.id);
    ctx.db.npc_pending_decision().npc_id().delete(&npc.id);
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
