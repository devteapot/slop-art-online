pub const WORLD_MIN: f32 = -500.0;
pub const WORLD_MAX: f32 = 500.0;
pub const NPC_MOVE_RANGE: f32 = 3.0;
pub const NPC_CHASE_STEP: f32 = 3.0;
pub const NPC_TICK_MS: u64 = 500;
pub const NPC_DETECTION_RANGE: f32 = 30.0;
pub const NPC_GROUND_Y: f32 = 0.9;
pub const MAX_HEALTH: i32 = 100;
pub const MAX_MANA: i32 = 100;
pub const MAX_STAMINA: i32 = 100;
pub const MANA_REGEN_PER_TICK: i32 = 3;
pub const STAMINA_REGEN_PER_TICK: i32 = 3;
pub const ATTACK_DAMAGE: i32 = 10;
pub const ATTACK_RANGE: f32 = 3.0;
pub const POINTS_PER_LEVEL: i32 = 5;
/// Max XZ distance a player may move between consecutive move_player calls.
/// Generous enough for dashes but blocks teleportation exploits.
pub const MAX_MOVE_DIST: f32 = 15.0;
pub const SKILL_XP_PER_USE: i32 = 10;
pub const SKILL_XP_PER_KILL: i32 = 25;

// Projectile simulation
pub const PROJECTILE_TICK_MS: u64 = 100;
pub const PROJECTILE_SPEED: f32 = 20.0;
pub const PROJECTILE_HIT_RADIUS: f32 = 1.0;
pub const PROJECTILE_MAX_LIFETIME_MS: u64 = 5000;

// AoE zones
pub const AOE_TICK_INTERVAL_MS: u64 = 500;
pub const AOE_DEFAULT_DURATION_MS: u64 = 3000;
pub const PLAYER_XP_PER_NPC_KILL: i32 = 50;
pub const PLAYER_XP_PER_PLAYER_KILL: i32 = 100;
