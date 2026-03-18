use bevy::prelude::*;
use shared::module_bindings::move_player_reducer::move_player;
use shared::module_bindings::use_skill_reducer::use_skill;
use shared::module_bindings::SkillAttributes;
use spacetimedb_sdk::Timestamp;

use crate::constants::{DASH_DISTANCE, JUMP_DURATION, JUMP_HEIGHT, PLAYER_Y};
use crate::network::{
    LocalIdentity, PlayerSkillEvent, PlayerSkillEventQueue, SkillAttributesEvent,
    SkillAttributesEventQueue, SkillCooldownEvent, SkillCooldownEventQueue, SkillDefEvent,
    SkillDefEventQueue, SpacetimeDb,
};
use crate::player::LocalPlayer;

// --- Resources ---

/// Ordered list of skill IDs the local player has (sorted by skill_id -> maps to keys 1–4).
#[derive(Resource, Default)]
pub struct LocalSkills(pub Vec<u64>);

#[derive(Resource, Default)]
pub struct LocalSkillData {
    pub levels: std::collections::HashMap<u64, i32>,
    pub attrs:  std::collections::HashMap<u64, SkillAttributes>,
}

/// skill_id → ready_at (micros since unix epoch)
#[derive(Resource, Default)]
pub struct LocalCooldowns(pub std::collections::HashMap<u64, i64>);

#[derive(Resource, Default)]
pub struct SelectedSkill(pub Option<u64>);

#[derive(Resource, Default)]
pub struct SkillNameMap(pub std::collections::HashMap<u64, String>);

#[derive(Resource, Default)]
pub struct MobilitySkillIds {
    pub jump: Option<u64>,
    pub dash: Option<u64>,
}

#[derive(Resource, Default, Clone)]
pub struct JumpState {
    pub elapsed: f32,
    pub active: bool,
}

// --- Helpers ---

pub fn cooldown_remaining(cooldowns: &LocalCooldowns, skill_id: u64) -> f32 {
    let Some(&ready_at) = cooldowns.0.get(&skill_id) else { return 0.0 };
    let now = Timestamp::now().to_micros_since_unix_epoch();
    ((ready_at - now) as f32 / 1_000_000.0).max(0.0)
}

pub fn get_attr_pts(attrs: &SkillAttributes, idx: usize) -> i32 {
    match idx {
        0 => attrs.damage_points,
        1 => attrs.cooldown_points,
        2 => attrs.aoe_points,
        3 => attrs.range_points,
        4 => attrs.duration_points,
        5 => attrs.projectile_count_points,
        6 => attrs.knockback_points,
        7 => attrs.resource_cost_points,
        8 => attrs.cast_speed_points,
        _ => 0,
    }
}

pub fn points_allocated_client(attrs: &SkillAttributes) -> i32 {
    attrs.damage_points + attrs.cooldown_points + attrs.aoe_points + attrs.range_points
        + attrs.duration_points + attrs.projectile_count_points + attrs.knockback_points
        + attrs.resource_cost_points + attrs.cast_speed_points
}

pub fn attr_display(attr_idx: usize, pts: i32) -> String {
    match attr_idx {
        0 => format!("{} pts -> {} dmg",     pts, 15 + pts * 5),
        1 => format!("{} pts -> {}ms cd",    pts, (3000 - pts * 150).max(500)),
        2 => format!("{} pts -> {:.1} aoe",  pts, pts as f32 * 0.8),
        3 => format!("{} pts -> {:.1} rng",  pts, 5.0 + pts as f32 * 1.5),
        4 => format!("{} pts -> {:.1}s dur", pts, 2.0 + pts as f32 * 0.5),
        5 => format!("{} pts -> {} proj",    pts, 1 + pts),
        6 => format!("{} pts -> {:.1} kb",   pts, pts as f32 * 2.0),
        7 => format!("{} pts -> {} cost",    pts, (20 - pts * 2).max(5)),
        8 => format!("{} pts -> {:.1}x spd", pts, 1.0 + pts as f32 * 0.1),
        _ => String::new(),
    }
}

// --- Systems ---

pub fn sync_player_skills(
    queue: Res<PlayerSkillEventQueue>,
    local_identity: Res<LocalIdentity>,
    mut local_skills: ResMut<LocalSkills>,
    mut local_skill_data: ResMut<LocalSkillData>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let Some(ref id) = local_id else { return };
    let mut events = queue.0.lock().unwrap();
    let mut changed = false;

    for event in events.drain(..) {
        match event {
            PlayerSkillEvent::Inserted(ps) if &ps.player_identity == id => {
                local_skill_data.levels.insert(ps.skill_id, ps.level);
                if !local_skills.0.contains(&ps.skill_id) {
                    local_skills.0.push(ps.skill_id);
                    changed = true;
                }
            }
            PlayerSkillEvent::Updated(ps) if &ps.player_identity == id => {
                local_skill_data.levels.insert(ps.skill_id, ps.level);
            }
            PlayerSkillEvent::Deleted(ps) if &ps.player_identity == id => {
                local_skill_data.levels.remove(&ps.skill_id);
                local_skills.0.retain(|&s| s != ps.skill_id);
                changed = true;
            }
            _ => {}
        }
    }
    if changed {
        local_skills.0.sort();
    }
}

pub fn sync_skill_defs(
    queue: Res<SkillDefEventQueue>,
    mut skill_name_map: ResMut<SkillNameMap>,
    mut mobility_ids: ResMut<MobilitySkillIds>,
) {
    let mut events = queue.0.lock().unwrap();
    for event in events.drain(..) {
        match event {
            SkillDefEvent::Inserted(def) => {
                match def.name.as_str() {
                    "Jump" => mobility_ids.jump = Some(def.id),
                    "Dash" => mobility_ids.dash = Some(def.id),
                    _ => {}
                }
                skill_name_map.0.insert(def.id, def.name);
            }
        }
    }
}

pub fn sync_skill_attrs(
    queue: Res<SkillAttributesEventQueue>,
    local_identity: Res<LocalIdentity>,
    mut local_skill_data: ResMut<LocalSkillData>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let Some(ref id) = local_id else { return };
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            SkillAttributesEvent::Inserted(attrs) if &attrs.player_identity == id => {
                local_skill_data.attrs.insert(attrs.skill_id, attrs);
            }
            SkillAttributesEvent::Updated(attrs) if &attrs.player_identity == id => {
                local_skill_data.attrs.insert(attrs.skill_id, attrs);
            }
            _ => {}
        }
    }
}

pub fn sync_skill_cooldowns(
    queue: Res<SkillCooldownEventQueue>,
    local_identity: Res<LocalIdentity>,
    mobility_ids: Res<MobilitySkillIds>,
    mut local_cooldowns: ResMut<LocalCooldowns>,
    mut jump_state: ResMut<JumpState>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let Some(ref id) = local_id else { return };
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            SkillCooldownEvent::Inserted(cd) if &cd.player_identity == id => {
                if mobility_ids.jump == Some(cd.skill_id) && !jump_state.active {
                    jump_state.active = true;
                    jump_state.elapsed = 0.0;
                }
                local_cooldowns.0.insert(cd.skill_id, cd.ready_at.to_micros_since_unix_epoch());
            }
            SkillCooldownEvent::Deleted(cd) if &cd.player_identity == id => {
                local_cooldowns.0.remove(&cd.skill_id);
            }
            _ => {}
        }
    }
}

pub fn use_skill_input(
    conn: Option<Res<SpacetimeDb>>,
    keys: Res<ButtonInput<KeyCode>>,
    local_player: Query<&Transform, With<LocalPlayer>>,
    local_skills: Res<LocalSkills>,
) {
    let Some(conn) = conn else { return };
    let Ok(transform) = local_player.single() else { return };

    let slot = if keys.just_pressed(KeyCode::Digit1) { Some(0) }
        else if keys.just_pressed(KeyCode::Digit2) { Some(1) }
        else if keys.just_pressed(KeyCode::Digit3) { Some(2) }
        else if keys.just_pressed(KeyCode::Digit4) { Some(3) }
        else { None };

    if let Some(idx) = slot {
        if let Some(&skill_id) = local_skills.0.get(idx) {
            let pos = transform.translation;
            let _ = conn.0.reducers.use_skill(skill_id, pos.x, pos.y, pos.z);
        }
    }
}

pub fn mobility_input(
    conn: Option<Res<SpacetimeDb>>,
    keys: Res<ButtonInput<KeyCode>>,
    local_player: Query<&Transform, With<LocalPlayer>>,
    mobility_ids: Res<MobilitySkillIds>,
    local_cooldowns: Res<LocalCooldowns>,
    facing: Res<crate::player::PlayerFacing>,
    jump_state: Res<JumpState>,
) {
    let Some(conn) = conn else { return };
    let Ok(transform) = local_player.single() else { return };
    let pos = transform.translation;

    // Jump — Space (animation starts in sync_skill_cooldowns when server confirms)
    if keys.just_pressed(KeyCode::Space) {
        if let Some(jump_id) = mobility_ids.jump {
            if cooldown_remaining(&local_cooldowns, jump_id) <= 0.0 && !jump_state.active {
                let _ = conn.0.reducers.use_skill(jump_id, pos.x, pos.y, pos.z);
            }
        }
    }

    // Dash — Shift
    let shift = keys.just_pressed(KeyCode::ShiftLeft) || keys.just_pressed(KeyCode::ShiftRight);
    if shift {
        if let Some(dash_id) = mobility_ids.dash {
            if cooldown_remaining(&local_cooldowns, dash_id) <= 0.0 {
                let dir = if facing.0 != Vec2::ZERO { facing.0 } else { Vec2::new(0.0, -1.0) };
                let new_x = pos.x + dir.x * DASH_DISTANCE;
                let new_z = pos.z + dir.y * DASH_DISTANCE;
                let _ = conn.0.reducers.use_skill(dash_id, pos.x, pos.y, pos.z);
                let _ = conn.0.reducers.move_player(new_x, PLAYER_Y, new_z);
            }
        }
    }
}

pub fn apply_jump_anim(
    time: Res<Time>,
    mut jump_state: ResMut<JumpState>,
    mut players: Query<&mut Transform, With<LocalPlayer>>,
) {
    if !jump_state.active { return }
    let Ok(mut transform) = players.single_mut() else { return };

    jump_state.elapsed += time.delta_secs();
    if jump_state.elapsed >= JUMP_DURATION {
        jump_state.active = false;
        transform.translation.y = PLAYER_Y;
    } else {
        let t = jump_state.elapsed / JUMP_DURATION;
        transform.translation.y = PLAYER_Y + JUMP_HEIGHT * (t * std::f32::consts::PI).sin();
    }
}
