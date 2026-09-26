//! Static vocabulary shared by the authority, minds and the observer.
//! Balance numbers live in the Rhai skill scripts, not here.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KindClass {
    Resource,
    Structure,
    Creature,
}

pub struct SkillSpec {
    pub name: &'static str,
    pub needs_target: bool,
    pub needs_item: bool,
    /// Distance (tiles) within which the skill can be performed; walking closes the gap.
    pub reach: f32,
    pub help: &'static str,
}

pub const SKILLS: &[SkillSpec] = &[
    SkillSpec { name: "goto", needs_target: true, needs_item: false, reach: 0.8, help: "walk to a target" },
    SkillSpec { name: "wander", needs_target: false, needs_item: false, reach: 0.0, help: "stroll to a random nearby spot (explore)" },
    SkillSpec { name: "gather", needs_target: true, needs_item: false, reach: 1.3, help: "harvest one unit from a resource (berry_bush→berries, tree→wood, boulder→stone, reeds→fiber, fishing_spot→fish)" },
    SkillSpec { name: "eat", needs_target: false, needs_item: true, reach: 0.0, help: "eat a food item from your pack" },
    SkillSpec { name: "sleep", needs_target: false, needs_item: false, reach: 0.0, help: "sleep until rested; faster and safe from cold near a shelter" },
    SkillSpec { name: "rest", needs_target: false, needs_item: false, reach: 0.0, help: "sit and recover a little energy" },
    SkillSpec { name: "build", needs_target: false, needs_item: true, reach: 0.0, help: "build a structure here (item: campfire|shelter|storage)" },
    SkillSpec { name: "craft", needs_target: false, needs_item: true, reach: 0.0, help: "craft a tool (item: spear)" },
    SkillSpec { name: "cook", needs_target: true, needs_item: true, reach: 1.5, help: "cook raw fish or meat at a campfire" },
    SkillSpec { name: "give", needs_target: true, needs_item: true, reach: 1.8, help: "hand items to another creature" },
    SkillSpec { name: "store", needs_target: true, needs_item: true, reach: 1.5, help: "put items into a storage" },
    SkillSpec { name: "take", needs_target: true, needs_item: true, reach: 1.5, help: "take items from a storage or remains" },
    SkillSpec { name: "attack", needs_target: true, needs_item: false, reach: 1.4, help: "strike a creature (spear hits harder); killing game yields meat" },
    SkillSpec { name: "offer", needs_target: true, needs_item: true, reach: 3.0, help: "offer a trade to a person beside you: item + qty you give, want + want_qty you ask in return; they may accept" },
    SkillSpec { name: "accept", needs_target: true, needs_item: false, reach: 3.0, help: "accept the trade a person just offered you (both sides are exchanged at once, if both still have the goods)" },
    SkillSpec { name: "found", needs_target: false, needs_item: false, reach: 0.0, help: "found a community with its home here (text: its name); you become its first member" },
    SkillSpec { name: "join", needs_target: true, needs_item: false, reach: 3.0, help: "ask a member of a community to let you join it (a member must welcome you)" },
    SkillSpec { name: "welcome", needs_target: true, needs_item: false, reach: 3.0, help: "welcome a person who asked to join your community" },
    SkillSpec { name: "leave", needs_target: false, needs_item: false, reach: 0.0, help: "leave your community" },
    SkillSpec { name: "dodge", needs_target: false, needs_item: false, reach: 0.0, help: "dash out of the way; an attack landing while you dodge misses (costs energy)" },
    SkillSpec { name: "block", needs_target: false, needs_item: false, reach: 0.0, help: "raise your guard for a moment; hits taken while blocking do a quarter of the damage" },
    SkillSpec { name: "throw", needs_target: true, needs_item: false, reach: 7.0, help: "throw your spear at a creature up to 7 tiles away (you lose the spear)" },
    SkillSpec { name: "follow", needs_target: true, needs_item: false, reach: 2.0, help: "walk alongside a creature for a while" },
    SkillSpec { name: "flee", needs_target: true, needs_item: false, reach: 0.0, help: "run away from a creature or place" },
    SkillSpec { name: "wait", needs_target: false, needs_item: false, reach: 0.0, help: "pause briefly" },
    SkillSpec { name: "conceive", needs_target: true, needs_item: false, reach: 2.0, help: "start a family with a willing adult partner: both must choose it toward each other within 2 minutes, while fed and near a shelter; a child is born a day later" },
    SkillSpec { name: "teach", needs_target: true, needs_item: true, reach: 2.0, help: "teach a technique you know to a person beside you (item: technique); takes a while, both must stay close" },
    SkillSpec { name: "experiment", needs_target: false, needs_item: true, reach: 0.0, help: "tinker with a material from your pack (item) hoping to work out a new technique; uses up the material, often fails" },
    SkillSpec { name: "write", needs_target: false, needs_item: true, reach: 0.0, help: "write on a tablet you keep or a sign you leave here (item: tablet|sign; text: your words; topic: a technique you know to describe) — needs writing and 1 wood" },
    SkillSpec { name: "tend", needs_target: true, needs_item: false, reach: 1.5, help: "tend someone's wounds (target a person, or \"self\"); slow, and not while they are fighting" },
    SkillSpec { name: "read", needs_target: false, needs_item: false, reach: 1.5, help: "read a tablet you carry, or a sign (target: {\"nearest\": \"sign\"}) — needs writing; a tablet describing a technique can teach it" },
    SkillSpec { name: "plant", needs_target: false, needs_item: false, reach: 0.0, help: "plant 2 berries here to grow a new berry bush (needs planting; open grass or dirt)" },
    SkillSpec { name: "signal", needs_target: false, needs_item: true, reach: 0.0, help: "make one of your species' signals (item: its name); others nearby hear it" },
    SkillSpec { name: "graze", needs_target: false, needs_item: false, reach: 0.0, help: "(animals) eat grass where you stand" },
];

pub fn skill(name: &str) -> Option<&'static SkillSpec> {
    SKILLS.iter().find(|s| s.name == name)
}

pub struct ItemSpec {
    pub name: &'static str,
    pub food: bool,
}

pub const ITEMS: &[ItemSpec] = &[
    ItemSpec { name: "berries", food: true },
    ItemSpec { name: "fish", food: true },
    ItemSpec { name: "meat", food: true },
    ItemSpec { name: "cooked_fish", food: true },
    ItemSpec { name: "cooked_meat", food: true },
    ItemSpec { name: "wood", food: false },
    ItemSpec { name: "stone", food: false },
    ItemSpec { name: "fiber", food: false },
    ItemSpec { name: "spear", food: false },
    ItemSpec { name: "hide", food: false },
    ItemSpec { name: "cloak", food: false },
    ItemSpec { name: "torch", food: false },
    ItemSpec { name: "tablet", food: false },
];

/// Practical techniques: must be known (world state, not belief) before use.
pub struct TechniqueSpec {
    pub name: &'static str,
    pub help: &'static str,
    pub requires: &'static [&'static str],
}

pub const TECHNIQUES: &[TechniqueSpec] = &[
    TechniqueSpec { name: "fire", help: "build a campfire (3 wood)", requires: &[] },
    TechniqueSpec { name: "cooking", help: "cook raw fish or meat at a campfire", requires: &["fire"] },
    TechniqueSpec { name: "spear", help: "craft a spear (2 wood, 1 stone)", requires: &[] },
    TechniqueSpec { name: "shelter", help: "build a shelter (6 wood, 3 fiber)", requires: &[] },
    TechniqueSpec { name: "storage", help: "build a storage (4 wood)", requires: &[] },
    TechniqueSpec { name: "cloak", help: "craft a warm cloak (2 hide, 1 fiber) that keeps the night cold off", requires: &[] },
    TechniqueSpec { name: "torch", help: "craft a torch (1 wood, 1 fiber) that lights the night", requires: &["fire"] },
    TechniqueSpec { name: "planting", help: "plant berries to grow new berry bushes", requires: &[] },
    TechniqueSpec { name: "writing", help: "write and read tablets and signs", requires: &[] },
];

pub fn technique(name: &str) -> Option<&'static TechniqueSpec> {
    TECHNIQUES.iter().find(|t| t.name == name)
}

pub fn item(name: &str) -> Option<&'static ItemSpec> {
    ITEMS.iter().find(|i| i.name == name)
}

pub const RESOURCES: &[(&str, &str)] = &[
    ("berry_bush", "berries"),
    ("tree", "wood"),
    ("boulder", "stone"),
    ("reeds", "fiber"),
    ("fishing_spot", "fish"),
];

pub const STRUCTURES: &[&str] = &["campfire", "shelter", "storage", "remains", "sign", "bush_patch"];
pub const CREATURES: &[&str] = &["person", "deer", "wolf"];

pub fn kind_class(kind: &str) -> Option<KindClass> {
    if RESOURCES.iter().any(|(k, _)| *k == kind) {
        Some(KindClass::Resource)
    } else if STRUCTURES.contains(&kind) {
        Some(KindClass::Structure)
    } else if CREATURES.contains(&kind) || kind == "creature" {
        Some(KindClass::Creature)
    } else {
        None
    }
}

pub fn resource_yield(kind: &str) -> Option<&'static str> {
    RESOURCES.iter().find(|(k, _)| *k == kind).map(|(_, y)| *y)
}

/// Compact skill reference for prompts.
pub fn skills_help() -> String {
    SKILLS
        .iter()
        .filter(|s| s.name != "graze")
        .map(|s| {
            let mut args = Vec::new();
            if s.needs_target {
                args.push("target");
            }
            if s.needs_item {
                args.push("item");
            }
            format!("- {}({}): {}", s.name, args.join(", "), s.help)
        })
        .collect::<Vec<_>>()
        .join("\n")
}
