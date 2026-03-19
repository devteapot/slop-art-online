pub const HOST: &str = "http://localhost:3000";
pub const DB_NAME: &str = "slop-art-online";
pub const POINTS_PER_LEVEL: i32 = 5;

/// (server_key, display_label) — server_key must match allocate_skill_point reducer
pub const ATTRS: &[(&str, &str)] = &[
    ("damage", "Damage"),
    ("cooldown", "Cooldown"),
    ("aoe", "AOE"),
    ("range", "Range"),
    ("duration", "Duration"),
    ("projectile_count", "Projectiles"),
    ("knockback", "Knockback"),
    ("resource_cost", "Resource Cost"),
    ("cast_speed", "Cast Speed"),
];

pub const MOVE_SPEED: f32 = 20.0;
pub const ATTACK_RANGE: f32 = 3.0;
pub const HEALTH_BAR_WIDTH: f32 = 1.0;
pub const HEALTH_BAR_HEIGHT: f32 = 0.1;
pub const HEALTH_BAR_Y_OFFSET: f32 = 1.8;
pub const MAX_LOOK_AHEAD: f32 = 15.0;

// Physics / movement
/// Multiplier on top of avian3d's default gravity (9.81 m/s²).
/// 3.0 → ~29 m/s² — snappy game-feel fall without floatiness.
pub const PLAYER_GRAVITY_SCALE: f32 = 3.0;
pub const JUMP_IMPULSE: f32 = 12.0;
pub const DASH_SPEED: f32 = 40.0;
pub const DASH_DURATION: f32 = 0.2;
pub const CAPSULE_HALF_LEN: f32 = 0.5;
pub const CAPSULE_RADIUS: f32 = 0.4;
pub const PICKUP_RANGE: f32 = 3.0;
