//! Static vocabulary shared by the authority, minds and the observer.
//! Balance numbers live in the Rhai skill scripts, not here.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KindClass {
    Resource,
    Structure,
    Creature,
    /// Ground one can walk to: the nearest tile of it in sight.
    Terrain,
}

/// Terrain kinds usable as targets (`{"nearest": "grass"}`).
pub const TERRAINS: &[&str] = &["grass", "forest"];

/// What a skill is, as the world's rule script declares it (`<skill>_spec()` in
/// `living/scripts/skills.rhai`): read once when the script compiles. The engine, graph
/// normalization, the mind's prompts and the client's verbs all take skills from it; no skill
/// is named here.
#[derive(Clone, Debug, PartialEq)]
pub struct SkillSpec {
    pub name: String,
    pub needs_target: bool,
    pub needs_item: bool,
    /// What the item names, in a prompt's argument list (`item`, `technique`, `signal name`).
    pub item_arg: String,
    /// Further arguments the skill reads (`qty`, `want`, `text`...), for prompts.
    pub args: Vec<String>,
    /// Distance (tiles) within which the skill can be performed; walking closes the gap.
    pub reach: f32,
    /// What it is, for a mind or a player: what it does, when it is useful, what it is not.
    pub about: String,
    /// What it takes and what it gives, from the rules' own numbers.
    pub takes: String,
    pub gives: String,
    /// Listed for bodies whose species names no skills (people); a species that names it still
    /// gets it (grazing is the animals').
    pub listed: bool,
    /// Offered in a conversation turn among the acts one may do right there.
    pub talk: bool,
    /// The item words it is given (`build`: campfire, shelter...): choices for clients and
    /// prompts, and accepted for it even when they are not items, structures or techniques
    /// (e.g. `lodging`).
    pub items: Vec<String>,
    /// A graph keeps doing it until it ends, even when a higher branch would win (eating,
    /// building, sleeping: work that is not dropped half-done).
    pub latch: bool,
    /// Worth recording as an experience when done (a build, a gift, a blow), not routine.
    pub notable: bool,
    /// Done while the body keeps whatever motion it has (waiting, eating, a call); every other
    /// skill stands still to be done.
    pub moving: bool,
    /// Behaviour of the moment (walking about, resting, grazing): it belongs in a graph, not in
    /// a one-off act.
    pub moment: bool,
    /// In a graph it takes the body back from a deliberate act (a flight).
    pub reflex: bool,
}

/// Every skill a world has, in the order the script declares them.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Skills {
    list: Vec<SkillSpec>,
    /// The world's items (`items()`), in the script's order.
    pub items: Vec<ItemSpec>,
    /// Indexes into `list` by name.
    by_name: Vec<(String, usize)>,
    /// The world's skills are not known here (a build without the script runtime, such as the
    /// lab viewer, which only shows graphs the authority accepted): any skill name is taken.
    pub open: bool,
}

impl Skills {
    /// The skills in the order given (the script's).
    pub fn new(list: Vec<SkillSpec>) -> Self {
        let mut by_name: Vec<(String, usize)> = list.iter().enumerate().map(|(i, s)| (s.name.clone(), i)).collect();
        by_name.sort();
        Self { list, by_name, items: Vec::new(), open: false }
    }

    /// Whether a name is a skill here (any name, when the skills are not known).
    pub fn has(&self, name: &str) -> bool {
        self.open || self.get(name).is_some()
    }

    pub fn get(&self, name: &str) -> Option<&SkillSpec> {
        self.by_name.binary_search_by(|(n, _)| n.as_str().cmp(name)).ok().map(|i| &self.list[self.by_name[i].1])
    }

    pub fn iter(&self) -> impl Iterator<Item = &SkillSpec> {
        self.list.iter()
    }

    pub fn names(&self) -> impl Iterator<Item = &str> {
        self.list.iter().map(|s| s.name.as_str())
    }

    pub fn len(&self) -> usize {
        self.list.len()
    }

    pub fn is_empty(&self) -> bool {
        self.list.is_empty()
    }
}

/// The world's skills in this process: set where a process adopts a world's script
/// ([`set_skills`]: the authority's script cache, the mind's `set_rules`, the client's compile),
/// otherwise the shipped script's. [`scoped`] overrides it on one thread (tests).
static WORLD: std::sync::RwLock<Option<std::sync::Arc<Skills>>> = std::sync::RwLock::new(None);

thread_local! {
    static SCOPED: std::cell::RefCell<Option<std::sync::Arc<Skills>>> = const { std::cell::RefCell::new(None) };
}

/// The skills of the world this process serves.
pub fn skills() -> std::sync::Arc<Skills> {
    if let Some(s) = SCOPED.with(|s| s.borrow().clone()) {
        return s;
    }
    if let Some(s) = WORLD.read().unwrap_or_else(|e| e.into_inner()).as_ref() {
        return s.clone();
    }
    WORLD.write().unwrap_or_else(|e| e.into_inner()).get_or_insert_with(shipped).clone()
}

#[cfg(feature = "scripting")]
fn shipped() -> std::sync::Arc<Skills> {
    crate::script::Scripts::new(include_str!("../../scripts/skills.rhai")).map(|s| s.skills().clone()).unwrap_or_default()
}

#[cfg(not(feature = "scripting"))]
fn shipped() -> std::sync::Arc<Skills> {
    std::sync::Arc::new(Skills { open: true, ..Default::default() })
}

/// Adopt a world's skills (its installed script's).
pub fn set_skills(s: std::sync::Arc<Skills>) {
    *WORLD.write().unwrap_or_else(|e| e.into_inner()) = Some(s);
}

/// Run `f` with `s` as the world's skills on this thread.
pub fn scoped<T>(s: std::sync::Arc<Skills>, f: impl FnOnce() -> T) -> T {
    let before = SCOPED.with(|c| c.replace(Some(s)));
    let out = f();
    SCOPED.with(|c| *c.borrow_mut() = before);
    out
}

/// A skill of the world this process serves.
pub fn skill(name: &str) -> Option<SkillSpec> {
    skills().get(name).cloned()
}

/// Whether the world has this skill.
pub fn is_skill(name: &str) -> bool {
    skills().has(name)
}

/// An item the world knows, as its script declares it (`items()`): its name and its traits
/// (`cooks_to`, ...). What it does (feeds, spoils, cuts) is the rules' to say: `nutrition(item)`,
/// `spoil_rate(item)` and the skills in `living/scripts/skills.rhai`.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ItemSpec {
    pub name: String,
    /// Its traits, as words (`cooks_to: cooked_fish`); a trait that is true reads "true".
    pub traits: std::collections::BTreeMap<String, String>,
}

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
    TechniqueSpec { name: "masonry", help: "build walls (2 stone per tile)", requires: &[] },
    TechniqueSpec { name: "carpentry", help: "build houses (6 wood, 4 clay, 2 stone; warm like a shelter and a fire) and gates (4 wood)", requires: &["shelter"] },
    TechniqueSpec { name: "fishing", help: "craft a net (3 fiber) that brings in two fish at a time", requires: &[] },
    TechniqueSpec { name: "smoking", help: "smoke raw fish or meat at a campfire so it keeps for weeks", requires: &["fire"] },
    TechniqueSpec { name: "basketry", help: "craft a basket (2 fiber, 1 wood) to carry 20 more", requires: &[] },
    TechniqueSpec { name: "archery", help: "craft a bow (2 wood, 1 fiber) and arrows (1 wood, 1 stone for 3) and shoot from afar", requires: &[] },
    TechniqueSpec { name: "tanning", help: "craft leather from hide, and armor (3 leather, 1 fiber) that softens blows", requires: &[] },
    TechniqueSpec { name: "medicine", help: "craft a salve (2 berries, 1 fiber); tending with a salve heals far more", requires: &[] },
    TechniqueSpec { name: "trapping", help: "build a trap (2 wood, 2 fiber) that catches small game over time", requires: &[] },
    TechniqueSpec { name: "bridging", help: "build a bridge (4 wood, 2 stone) over water beside you", requires: &["carpentry"] },
    TechniqueSpec { name: "fire_bolt", help: "hurl a bolt of fire (firebolt) that burns the first creature in its path", requires: &["fire"] },
    TechniqueSpec { name: "wound_tending", help: "close wounds quickly with your hands (the heal skill), your own or an ally's, even in a fight; not mending things", requires: &[] },
    TechniqueSpec { name: "toolmaking", help: "craft an axe (2 wood, 1 stone; cuts wood twice as fast) or a pick (2 wood, 2 stone; breaks stone twice as fast)", requires: &[] },
];

/// A technique by its name (a renamed technique by its old name too, see [`RENAMED`]).
pub fn technique(name: &str) -> Option<&'static TechniqueSpec> {
    let name = technique_name(name);
    TECHNIQUES.iter().find(|t| t.name == name)
}

/// Techniques that were renamed, old name first: seeds, stored know-how and written topics
/// under the old name are read as the new one, and an install renames a world's rows.
/// `mending` was the heal skill's wound-closing, and models read it as mending tools and hinges
/// (docs/TRIALS.md, `i8`).
pub const RENAMED: &[(&str, &str)] = &[("mending", "wound_tending")];

/// A technique's current name.
pub fn technique_name(name: &str) -> &str {
    RENAMED.iter().find(|(old, _)| *old == name).map_or(name, |(_, new)| new)
}

/// An item of the world this process serves (any name, when its items are not known).
pub fn item(name: &str) -> Option<ItemSpec> {
    let w = skills();
    if w.open {
        return Some(ItemSpec { name: name.to_string(), ..Default::default() });
    }
    w.items.iter().find(|i| i.name == name).cloned()
}

/// The names of the world's items, in the script's order.
pub fn item_names() -> Vec<String> {
    skills().items.iter().map(|i| i.name.clone()).collect()
}

pub const RESOURCES: &[(&str, &str)] = &[
    ("berry_bush", "berries"),
    ("tree", "wood"),
    ("boulder", "stone"),
    ("reeds", "fiber"),
    ("fishing_spot", "fish"),
    ("clay_bank", "clay"),
];

pub const STRUCTURES: &[&str] = &["campfire", "shelter", "storage", "remains", "sign", "bush_patch", "house", "gate", "trap", "hall", "workshop", "market", "inn"];
pub const CREATURES: &[&str] = &["person", "deer", "wolf"];
/// Things built into the terrain itself rather than as structures.
pub const TERRAIN_BUILDS: &[&str] = &["wall", "road", "bridge"];

pub fn kind_class(kind: &str) -> Option<KindClass> {
    if RESOURCES.iter().any(|(k, _)| *k == kind) {
        Some(KindClass::Resource)
    } else if STRUCTURES.contains(&kind) {
        Some(KindClass::Structure)
    } else if CREATURES.contains(&kind) || kind == "creature" {
        Some(KindClass::Creature)
    } else if TERRAINS.contains(&kind) {
        Some(KindClass::Terrain)
    } else {
        None
    }
}

pub fn resource_yield(kind: &str) -> Option<&'static str> {
    RESOURCES.iter().find(|(k, _)| *k == kind).map(|(_, y)| *y)
}

/// Compact skill reference for prompts.
pub fn skills_help() -> String {
    skills_help_of(&skills())
}

/// One skill's prompt line: its arguments, what it is, and what it takes and gives.
pub fn skill_line(s: &SkillSpec) -> String {
    let mut args: Vec<String> = Vec::new();
    if s.needs_target {
        args.push("target".into());
    }
    if s.needs_item {
        args.push(if !s.items.is_empty() {
            format!("item: {}", s.items.join("|"))
        } else if s.item_arg.is_empty() || s.item_arg == "item" {
            "item".into()
        } else {
            format!("item: {}", s.item_arg)
        });
    }
    args.extend(s.args.iter().cloned());
    let mut line = format!("- {}({}): {}", s.name, args.join(", "), s.about);
    if !s.takes.is_empty() {
        line.push_str(&format!("\n    takes: {}", s.takes));
    }
    if !s.gives.is_empty() {
        line.push_str(&format!("\n    gives: {}", s.gives));
    }
    line
}

/// Skill reference with each skill's inputs and outputs, for people.
pub fn skills_help_of(skills: &Skills) -> String {
    skills.iter().filter(|s| s.listed).map(skill_line).collect::<Vec<_>>().join("\n")
}
