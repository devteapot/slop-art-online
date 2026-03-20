use spacetimedb::{Identity, SpacetimeType, Timestamp};

#[derive(SpacetimeType, Clone, Debug)]
pub struct Position {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Position {
    pub fn distance_to(&self, other: &Position) -> f32 {
        let dx = self.x - other.x;
        let dy = self.y - other.y;
        let dz = self.z - other.z;
        (dx * dx + dy * dy + dz * dz).sqrt()
    }
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub enum BehaviorType {
    Melee,
    Projectile,
    GroundAoe,
    Buff,
    /// Mobility skills (Jump, Dash, etc.). Server only tracks cooldown/resource;
    /// the client handles the visual effect entirely.
    Mobility,
    /// Point-and-click targeting (select entity, apply effect).
    Targeted,
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub enum ResourceType {
    Mana,
    Stamina,
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub enum StatusEffectType {
    Poison,  // DoT
    Regen,   // HoT
    Slow,    // 50% move speed
    Haste,   // 150% move speed
}

#[derive(Clone)]
#[spacetimedb::table(accessor = player, public)]
pub struct Player {
    #[primary_key]
    pub identity: Identity,
    pub position: Position,
    pub health: i32,
    pub max_health: i32,
    pub level: i32,
    pub xp: i32,
    pub mana: i32,
    pub max_mana: i32,
    pub stamina: i32,
    pub max_stamina: i32,
    pub facing_angle: f32,
    pub last_seq: u32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = npc, public)]
pub struct Npc {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub position: Position,
    pub health: i32,
    pub max_health: i32,
    pub level: i32,
    pub role: String,
    pub name: String,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = npc_behavior, public)]
pub struct NpcBehavior {
    #[primary_key]
    pub npc_id: u64,
    pub mode: String,        // "idle" | "combat" | "plan"
    pub combat_tree: String, // Behavior<NpcBtAction> JSON, empty when not in combat
}

#[derive(Clone)]
#[spacetimedb::table(accessor = npc_plan, public)]
pub struct NpcPlan {
    #[primary_key]
    pub npc_id: u64,
    pub steps: String,       // JSON array of plan steps
    pub current_step: i32,   // 0-indexed into steps array
}

#[spacetimedb::table(accessor = npc_pending_decision, public)]
pub struct NpcPendingDecision {
    #[primary_key]
    pub npc_id: u64,
    pub decision_type: String, // "combat_start" | "combat_update" | "post_combat" | "idle"
    pub context: String,
}

#[spacetimedb::table(accessor = npc_destination, public)]
pub struct NpcDestination {
    #[primary_key]
    pub npc_id: u64,
    pub target_x: f32,
    pub target_z: f32,
}


#[derive(Clone)]
#[spacetimedb::table(accessor = skill_def, public)]
pub struct SkillDef {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub name: String,
    pub behavior_type: BehaviorType,
    pub resource_type: ResourceType,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = player_skill, public)]
pub struct PlayerSkill {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub player_identity: Identity,
    pub skill_id: u64,
    pub level: i32,
    pub xp: i32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = skill_attributes, public)]
pub struct SkillAttributes {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub player_identity: Identity,
    pub skill_id: u64,
    pub damage_points: i32,
    pub cooldown_points: i32,
    pub aoe_points: i32,
    pub range_points: i32,
    pub duration_points: i32,
    pub projectile_count_points: i32,
    pub knockback_points: i32,
    pub resource_cost_points: i32,
    pub cast_speed_points: i32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = skill_cooldown, public)]
pub struct SkillCooldown {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub player_identity: Identity,
    pub skill_id: u64,
    pub ready_at: Timestamp,
}

// --- Item & Inventory ---

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub enum ItemRarity {
    Common,
    Uncommon,
    Rare,
    Epic,
}

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub enum ItemType {
    Material,
    Consumable,
    Equipment,
    Quest,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = item_def, public)]
pub struct ItemDef {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub name: String,
    pub item_type: ItemType,
    pub rarity: ItemRarity,
    pub max_stack: i32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = loot_table_entry, public)]
pub struct LootTableEntry {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub item_def_id: u64,
    pub min_npc_level: i32,
    pub max_npc_level: i32,
    pub weight: i32,
    pub min_quantity: i32,
    pub max_quantity: i32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = inventory_item, public)]
pub struct InventoryItem {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub player_identity: Identity,
    pub slot: i32,
    pub item_def_id: u64,
    pub quantity: i32,
}

// --- Consumables ---

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub enum ConsumableEffect {
    RestoreHealth,
    RestoreMana,
    RestoreStamina,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = consumable_def, public)]
pub struct ConsumableDef {
    #[primary_key]
    pub item_def_id: u64,
    pub effect: ConsumableEffect,
    pub power: i32,
}

// --- Equipment ---

#[derive(SpacetimeType, Clone, Debug, PartialEq)]
pub enum EquipSlot {
    Weapon,
    Helmet,
    Chest,
    Legs,
    Boots,
    Accessory,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = equipment_def, public)]
pub struct EquipmentDef {
    #[primary_key]
    pub item_def_id: u64,
    pub equip_slot: EquipSlot,
    pub required_level: i32,
    pub max_durability: i32,
    pub bonus_health: i32,
    pub bonus_mana: i32,
    pub bonus_stamina: i32,
    pub bonus_attack: i32,
    pub bonus_defense: i32,
}

#[derive(Clone)]
#[spacetimedb::table(accessor = equipped_item, public)]
pub struct EquippedItem {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub player_identity: Identity,
    pub equip_slot: EquipSlot,
    pub item_def_id: u64,
    pub durability: i32,
}

// --- NPC Memory ---

#[derive(Clone)]
#[spacetimedb::table(accessor = npc_memory, public)]
pub struct NpcMemory {
    #[primary_key]
    #[auto_inc]
    pub id: u64,
    pub npc_id: u64,
    pub text: String,
    pub created_at: u64,
}
