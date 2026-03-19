use avian3d::prelude::*;
use bevy::prelude::*;
use shared::module_bindings::use_skill_reducer::use_skill;
use shared::module_bindings::use_targeted_skill_reducer::use_targeted_skill;
use shared::module_bindings::SkillAttributes;
use spacetimedb_sdk::Timestamp;

use crate::constants::{DASH_DURATION, DASH_SPEED, JUMP_IMPULSE};
use crate::network::{
    LocalIdentity, PlayerSkillEvent, PlayerSkillEventQueue, SkillAttributesEvent,
    SkillAttributesEventQueue, SkillCooldownEvent, SkillCooldownEventQueue, SkillDefEvent,
    SkillDefEventQueue, SpacetimeDb,
};
use crate::npc::NpcId;
use crate::player::{AbilityAnimTrigger, AbilityAnimTriggerQueue, CursorGroundPos, Grounded, LocalPlayer, PlayerId, PlayerFacing};
use crate::world::MainCamera;

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

/// Tracks an active dash so the velocity burst persists for DASH_DURATION.
#[derive(Resource, Default)]
pub struct DashState {
    pub active: bool,
    pub elapsed: f32,
    pub dir: Vec2,
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
    mut local_cooldowns: ResMut<LocalCooldowns>,
) {
    let local_id = local_identity.0.lock().unwrap().clone();
    let Some(ref id) = local_id else { return };
    let mut events = queue.0.lock().unwrap();

    for event in events.drain(..) {
        match event {
            SkillCooldownEvent::Inserted(cd) if &cd.player_identity == id => {
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
    local_cooldowns: Res<LocalCooldowns>,
    local_identity: Res<LocalIdentity>,
    ability_queue: Res<AbilityAnimTriggerQueue>,
    cursor_ground: Res<CursorGroundPos>,
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
            if cooldown_remaining(&local_cooldowns, skill_id) <= 0.0 {
                let pos = transform.translation;
                let target = cursor_ground.0.unwrap_or(pos);
                let _ = conn.0.reducers.use_skill(skill_id, target.x, target.y, target.z);
                if let Some(id) = local_identity.0.lock().unwrap().clone() {
                    ability_queue.0.lock().unwrap().push(AbilityAnimTrigger { identity: id, skill_id });
                }
            }
        }
    }
}

pub fn mobility_input(
    conn: Option<Res<SpacetimeDb>>,
    keys: Res<ButtonInput<KeyCode>>,
    mut player: Query<(&Transform, &mut LinearVelocity, &Grounded), With<LocalPlayer>>,
    mobility_ids: Res<MobilitySkillIds>,
    local_cooldowns: Res<LocalCooldowns>,
    local_identity: Res<LocalIdentity>,
    facing: Res<PlayerFacing>,
    mut dash_state: ResMut<DashState>,
    ability_queue: Res<AbilityAnimTriggerQueue>,
) {
    let Some(conn) = conn else { return };
    let Ok((transform, mut velocity, grounded)) = player.single_mut() else { return };
    let pos = transform.translation;

    // Jump — Space: apply upward impulse when grounded
    if keys.just_pressed(KeyCode::Space) {
        if let Some(jump_id) = mobility_ids.jump {
            if cooldown_remaining(&local_cooldowns, jump_id) <= 0.0 && grounded.0 {
                velocity.y += JUMP_IMPULSE;
                let _ = conn.0.reducers.use_skill(jump_id, pos.x, pos.y, pos.z);
                if let Some(id) = local_identity.0.lock().unwrap().clone() {
                    ability_queue.0.lock().unwrap().push(AbilityAnimTrigger { identity: id, skill_id: jump_id });
                }
            }
        }
    }

    // Dash — Shift: start a velocity burst in the facing direction
    let shift = keys.just_pressed(KeyCode::ShiftLeft) || keys.just_pressed(KeyCode::ShiftRight);
    if shift {
        if let Some(dash_id) = mobility_ids.dash {
            if cooldown_remaining(&local_cooldowns, dash_id) <= 0.0 && !dash_state.active {
                let dir = if facing.0 != Vec2::ZERO { facing.0 } else { Vec2::new(0.0, -1.0) };
                dash_state.active = true;
                dash_state.elapsed = 0.0;
                dash_state.dir = dir;
                let _ = conn.0.reducers.use_skill(dash_id, pos.x, pos.y, pos.z);
                if let Some(id) = local_identity.0.lock().unwrap().clone() {
                    ability_queue.0.lock().unwrap().push(AbilityAnimTrigger { identity: id, skill_id: dash_id });
                }
            }
        }
    }
}

/// Right-click an entity to use a targeted skill on it.
pub fn use_targeted_skill_input(
    conn: Option<Res<SpacetimeDb>>,
    buttons: Res<ButtonInput<MouseButton>>,
    windows: Query<&Window>,
    camera: Query<(&Camera, &GlobalTransform), With<MainCamera>>,
    spatial_query: SpatialQuery,
    local_player: Query<Entity, With<LocalPlayer>>,
    npc_query: Query<&NpcId>,
    player_query: Query<&PlayerId>,
    local_skills: Res<LocalSkills>,
    local_cooldowns: Res<LocalCooldowns>,
    local_identity: Res<LocalIdentity>,
    ability_queue: Res<AbilityAnimTriggerQueue>,
    selected_skill: Res<SelectedSkill>,
) {
    if !buttons.just_pressed(MouseButton::Right) { return }
    let Some(conn) = conn else { return };
    let Ok(local_entity) = local_player.single() else { return };
    let Ok(window) = windows.single() else { return };
    let Some(cursor) = window.cursor_position() else { return };
    let Ok((cam, cam_gt)) = camera.single() else { return };
    let Ok(ray) = cam.viewport_to_world(cam_gt, cursor) else { return };

    // Pick the first skill that is targeted (or fall back to selected skill)
    let skill_id = selected_skill.0.or_else(|| local_skills.0.first().copied());
    let Some(skill_id) = skill_id else { return };
    if cooldown_remaining(&local_cooldowns, skill_id) > 0.0 { return }

    // Raycast against physics colliders
    let hits = spatial_query.ray_hits(
        ray.origin,
        Dir3::new(ray.direction.as_vec3()).unwrap_or(Dir3::NEG_Z),
        200.0,
        10,
        false,
        &SpatialQueryFilter::default(),
    );

    for hit in hits {
        if hit.entity == local_entity { continue }

        if let Ok(npc_id) = npc_query.get(hit.entity) {
            let _ = conn.0.reducers.use_targeted_skill(
                skill_id,
                "npc".to_string(),
                npc_id.0,
                String::new(),
            );
            if let Some(id) = local_identity.0.lock().unwrap().clone() {
                ability_queue.0.lock().unwrap().push(AbilityAnimTrigger { identity: id, skill_id });
            }
            return;
        }
        if let Ok(pid) = player_query.get(hit.entity) {
            let hex = pid.0.to_hex().to_string();
            let _ = conn.0.reducers.use_targeted_skill(
                skill_id,
                "player".to_string(),
                0,
                hex,
            );
            if let Some(id) = local_identity.0.lock().unwrap().clone() {
                ability_queue.0.lock().unwrap().push(AbilityAnimTrigger { identity: id, skill_id });
            }
            return;
        }
    }
}

/// Drive the dash velocity burst for DASH_DURATION seconds.
pub fn apply_dash(
    time: Res<Time>,
    mut dash_state: ResMut<DashState>,
    mut player: Query<&mut LinearVelocity, With<LocalPlayer>>,
) {
    if !dash_state.active { return }
    let Ok(mut velocity) = player.single_mut() else { return };

    dash_state.elapsed += time.delta_secs();
    if dash_state.elapsed >= DASH_DURATION {
        dash_state.active = false;
    } else {
        velocity.x = dash_state.dir.x * DASH_SPEED;
        velocity.z = dash_state.dir.y * DASH_SPEED;
    }
}
