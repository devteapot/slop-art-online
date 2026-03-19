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
}

#[derive(Clone)]
#[spacetimedb::table(accessor = npc_behaviour_graph, public)]
pub struct NpcBehaviourGraph {
    #[primary_key]
    pub npc_id: u64,
    pub current_node: String,
    pub graph: String,
}

#[spacetimedb::table(accessor = npc_pending_decision, public)]
pub struct NpcPendingDecision {
    #[primary_key]
    pub npc_id: u64,
    pub context: String,
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
