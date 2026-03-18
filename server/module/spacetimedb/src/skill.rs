use crate::constants::POINTS_PER_LEVEL;
use crate::tables::SkillAttributes;

pub struct SkillStats {
    pub power: i32,
    pub cooldown_ms: u64,
    pub aoe_radius: f32,
    pub range: f32,
    pub knockback: f32,
    pub resource_cost: i32,
}

pub fn compute_stats(attrs: &SkillAttributes) -> SkillStats {
    SkillStats {
        power: 15 + attrs.damage_points * 5,
        cooldown_ms: 3000u64.saturating_sub(attrs.cooldown_points as u64 * 150).max(500),
        aoe_radius: attrs.aoe_points as f32 * 0.8,
        range: 5.0 + attrs.range_points as f32 * 1.5,
        knockback: attrs.knockback_points as f32 * 0.5,
        resource_cost: (25 - attrs.resource_cost_points * 2).max(5),
    }
}

pub fn total_skill_points(level: i32) -> i32 { level * POINTS_PER_LEVEL }

pub fn points_allocated(attrs: &SkillAttributes) -> i32 {
    attrs.damage_points + attrs.cooldown_points + attrs.aoe_points
        + attrs.range_points + attrs.duration_points + attrs.projectile_count_points
        + attrs.knockback_points + attrs.resource_cost_points + attrs.cast_speed_points
}

pub fn skill_xp_threshold(level: i32) -> i32 { level * 50 }
pub fn player_xp_threshold(level: i32) -> i32 { level * 100 }
