pub const WORLD_MIN: f32 = -500.0;
pub const WORLD_MAX: f32 = 500.0;
pub const NPC_MOVE_RANGE: f32 = 3.0;
pub const NPC_CHASE_STEP: f32 = 3.0;
pub const NPC_TICK_MS: u64 = 500;
pub const NPC_DETECTION_RANGE: f32 = 30.0;
pub const NPC_GROUND_Y: f32 = 0.9;
pub const MANA_REGEN_PER_TICK: i32 = 3;
pub const STAMINA_REGEN_PER_TICK: i32 = 3;
pub const PLAYER_BASE_ATTACK: i32 = 10;
pub const ATTACK_RANGE: f32 = 3.0;

// Player stat scaling
pub const BASE_PLAYER_HP: i32 = 100;
pub const HP_PER_LEVEL: i32 = 20;
pub const BASE_PLAYER_MANA: i32 = 100;
pub const MANA_PER_LEVEL: i32 = 10;
pub const BASE_PLAYER_STAMINA: i32 = 100;
pub const STAMINA_PER_LEVEL: i32 = 10;

// NPC stat scaling
pub const BASE_NPC_HP: i32 = 80;
pub const NPC_HP_PER_LEVEL: i32 = 30;
pub const BASE_NPC_DAMAGE: i32 = 8;
pub const NPC_DAMAGE_PER_LEVEL: i32 = 3;

// XP rewards
pub const BASE_XP_PER_NPC_KILL: i32 = 30;
pub const XP_PER_NPC_LEVEL: i32 = 20;
pub const BASE_XP_PER_PLAYER_KILL: i32 = 60;
pub const XP_PER_PLAYER_LEVEL: i32 = 40;
pub const POINTS_PER_LEVEL: i32 = 5;
/// Max XZ distance a player may move between consecutive move_player calls.
/// Generous enough for dashes but blocks teleportation exploits.
pub const MAX_MOVE_DIST: f32 = 15.0;
pub const SKILL_XP_PER_USE: i32 = 10;
pub const SKILL_XP_PER_KILL: i32 = 25;
pub const SKILL_XP_PER_HIT: i32 = 10;
pub const SKILL_XP_PER_AOE_TICK: i32 = 3;

// Projectile simulation
pub const PROJECTILE_TICK_MS: u64 = 100;
pub const PROJECTILE_SPEED: f32 = 20.0;
pub const PROJECTILE_HIT_RADIUS: f32 = 1.0;
pub const PROJECTILE_MAX_LIFETIME_MS: u64 = 5000;

// AoE zones
pub const AOE_TICK_INTERVAL_MS: u64 = 500;
pub const AOE_DEFAULT_DURATION_MS: u64 = 3000;

// Status effects
pub const EFFECT_POISON_POWER: i32 = 3;
pub const EFFECT_REGEN_POWER: i32 = 5;
pub const EFFECT_DEFAULT_DURATION_MS: u64 = 5000;
pub const MAX_MOVE_DIST_SLOW: f32 = 8.0;
pub const MAX_MOVE_DIST_HASTE: f32 = 22.0;

// Chat
pub const CHAT_MESSAGE_EXPIRE_MS: u64 = 30_000;
pub const CHAT_MAX_LENGTH: usize = 200;
pub const CHAT_PROXIMITY_RANGE: f32 = 50.0;

// Inventory & Loot
pub const INVENTORY_SLOTS: i32 = 20;
pub const GROUND_ITEM_DESPAWN_MS: u64 = 300_000;
pub const GROUND_ITEM_FFA_DELAY_MS: u64 = 30_000;
pub const PICKUP_RANGE: f32 = 3.0;
pub const LOOT_ROLLS_PER_KILL: i32 = 2;
pub const LOOT_DROP_CHANCE_PCT: i32 = 60;

// Equipment
pub const EQUIPMENT_SLOTS: i32 = 6;
