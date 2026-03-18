pub const HOST: &str = "http://localhost:3000";
pub const DB_NAME: &str = "slop-art-online";
pub const POINTS_PER_LEVEL: i32 = 5;

/// (server_key, display_label) — server_key must match allocate_skill_point reducer
pub const ATTRS: &[(&str, &str)] = &[
    ("damage",           "Damage"),
    ("cooldown",         "Cooldown"),
    ("aoe",              "AOE"),
    ("range",            "Range"),
    ("duration",         "Duration"),
    ("projectile_count", "Projectiles"),
    ("knockback",        "Knockback"),
    ("resource_cost",    "Resource Cost"),
    ("cast_speed",       "Cast Speed"),
];

pub const MOVE_SPEED: f32 = 20.0;
pub const ATTACK_RANGE: f32 = 3.0;
pub const PLAYER_Y: f32 = 1.0;
pub const MAX_HEALTH: f32 = 100.0;
pub const HEALTH_BAR_WIDTH: f32 = 1.0;
pub const HEALTH_BAR_HEIGHT: f32 = 0.1;
pub const HEALTH_BAR_Y_OFFSET: f32 = 1.8;
pub const JUMP_HEIGHT: f32 = 3.0;
pub const JUMP_DURATION: f32 = 0.55;
pub const DASH_DISTANCE: f32 = 8.0;
