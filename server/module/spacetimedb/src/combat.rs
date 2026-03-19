use spacetimedb::{Identity, ReducerContext, Table};

use crate::constants::*;
use crate::tables::*;
use crate::skill::*;

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

pub fn respawn_player(ctx: &ReducerContext, player: &Player) {
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

pub fn hit_npc(ctx: &ReducerContext, npc: &Npc, power: i32, knockback: f32, from: &Position, attacker: Identity, skill_id: u64, hit_xp: i32) {
    award_skill_xp(ctx, attacker, skill_id, hit_xp);
    let new_pos = apply_knockback(&npc.position, from, knockback);
    let new_health = npc.health - power;
    if new_health <= 0 {
        kill_npc(ctx, npc, attacker);
        award_skill_xp(ctx, attacker, skill_id, SKILL_XP_PER_KILL);
    } else {
        ctx.db.npc().id().update(Npc { position: new_pos, health: new_health, ..npc.clone() });
    }
}

pub fn hit_player(ctx: &ReducerContext, target: &Player, power: i32, knockback: f32, from: &Position, attacker: Identity, skill_id: u64, hit_xp: i32) {
    award_skill_xp(ctx, attacker, skill_id, hit_xp);
    let new_pos = apply_knockback(&target.position, from, knockback);
    let new_health = target.health - power;
    if new_health <= 0 {
        respawn_player(ctx, target);
        if let Some(attacker_player) = ctx.db.player().identity().find(&attacker) {
            award_player_xp(ctx, &attacker_player, xp_for_player_kill(target.level));
        }
        award_skill_xp(ctx, attacker, skill_id, SKILL_XP_PER_KILL);
    } else {
        ctx.db.player().identity().update(Player { position: new_pos, health: new_health, ..target.clone() });
    }
}

pub fn find_nearest_player(ctx: &ReducerContext, pos: &Position) -> Option<(Player, f32)> {
    ctx.db.player().iter()
        .map(|p| { let d = pos.distance_to(&p.position); (p, d) })
        .min_by(|a, b| a.1.partial_cmp(&b.1).unwrap())
}
