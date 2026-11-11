//! How the world's skills are presented to a player (docs/INTERFACE.md): the fixed vocabulary a
//! rules script may name in a `<name>_ui()` declaration, the typed [`UiSpec`] it is read into,
//! the defaults a skill gets when it declares nothing, which skill goes on which place of the
//! skill bar ([`bar_places`]), and the one filter that decides which skills a body is offered,
//! for players and minds alike ([`offered`]).
//!
//! A declaration only shows. Anything that limits what a character may do is a rule (a combat
//! trait, a `_check`) that the authority enforces for players and minds alike: nothing here
//! grants or refuses an act. What a player sends is an act node the minds' grammar also accepts
//! ([`act_node`], [`bar_act`]); the anti-drift tests at the end of this module hold that.
//!
//! The defaults are the game client's guesses before declarations existed, moved here so the
//! client, the authority's install and the mind read one description: `combat::look()`'s
//! fallback by aim for icons, clips and effects, with [`BOLT_RADIUS`] as the line between an
//! arrow and a bolt; the F list's choice of places by spec (`verbs.rs`); and the step-4 WIP's
//! `Roles::of` resolution of the bar. Reading `_ui()` is `living_rules::script`'s
//! (`Scripts::ui`, `Scripts::ui_errors`); this module needs no script runtime.

use crate::catalog::{SkillSpec, Skills};
use crate::combat::{Aim, MissileSpec, Shape, Shapes};
use std::collections::BTreeMap;

// ---- the vocabulary ----------------------------------------------------------------------------

/// A closed vocabulary of names: an enum, the list of its names (for messages and checks), and
/// conversions both ways.
macro_rules! vocab {
    ($(#[$m:meta])* $name:ident, $list:ident { $($(#[$vm:meta])* $v:ident = $s:literal),+ $(,)? }) => {
        $(#[$m])*
        #[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
        pub enum $name { $($(#[$vm])* $v),+ }
        #[doc = concat!("Every name of [`", stringify!($name), "`], in order.")]
        pub const $list: &[&str] = &[$($s),+];
        impl $name {
            pub const ALL: &'static [$name] = &[$($name::$v),+];
            pub fn parse(s: &str) -> Option<Self> {
                match s { $($s => Some($name::$v),)+ _ => None }
            }
            pub fn as_str(self) -> &'static str {
                match self { $($name::$v => $s),+ }
            }
        }
    };
}

vocab! {
    /// Where a declaration attaches (`on`).
    On, PLACES {
        /// The skill bar: `use_skill` for a combat skill in `skill_bar()`, otherwise the
        /// `human_act` node.
        Bar = "bar",
        /// F toward a creature under the cursor (a person or an animal), and a person's window:
        /// `target: {"id": n}`.
        Person = "person",
        /// F toward a resource or structure: `target: {"nearest": kind}`.
        Thing = "thing",
        /// A point on the ground under the cursor: `target: {"at": [x, y]}`.
        Ground = "ground",
        /// C, the acts on oneself: no target.
        Me = "self",
        /// An item clicked in the pack: the act with that item.
        Item = "item",
        /// The ways chips in the text box (ways of speaking only).
        Box = "box",
    }
}

vocab! {
    /// A place on the skill bar (`place`).
    BarPlace, BAR_PLACES {
        Primary = "primary",
        Secondary = "secondary",
        /// The skill keys (Q E R by default); `order` is the key.
        Skill = "skill",
        Jump = "jump",
        Dodge = "dodge",
        /// The weapon's toggle (sheathe and draw).
        Weapon = "weapon",
        /// The extra row, and beyond it the skills window.
        Extra = "extra",
    }
}

impl BarPlace {
    /// A place only one skill may hold.
    pub fn single(self) -> bool {
        matches!(self, BarPlace::Primary | BarPlace::Secondary | BarPlace::Jump | BarPlace::Dodge | BarPlace::Weapon)
    }
}

vocab! {
    /// The input a declaration asks of the player (`input`).
    Input, INPUTS {
        /// Press once; aimed at a creature, the one under the cursor, else the nearest in reach.
        Tap = "tap",
        /// Hold; release ends it (a guard).
        Hold = "hold",
        /// Press to switch a body state.
        Toggle = "toggle",
        /// Aim at a ground point within reach.
        AimPoint = "aim_point",
        /// Aim a direction.
        AimDir = "aim_dir",
        PickPerson = "pick_person",
        PickItem = "pick_item",
        PickQty = "pick_qty",
        DragOnto = "drag_onto",
        Words = "words",
    }
}

vocab! {
    /// What the player must choose (`picks`), each mapping onto the spec.
    Pick, PICKS {
        /// A creature: the spec takes a target.
        Person = "person",
        /// An item: the spec takes an item.
        Item = "item",
        /// An amount: the spec reads `qty`.
        Qty = "qty",
        /// What is asked in return: the spec reads `want`.
        Want = "want",
        /// Words: the spec reads `text`.
        Words = "words",
    }
}

impl Pick {
    /// Whether a spec takes this choice.
    pub fn fits(self, spec: &SkillSpec) -> bool {
        let arg = |a: &str| spec.args.iter().any(|x| x == a);
        match self {
            Pick::Person => spec.needs_target,
            Pick::Item => spec.needs_item,
            Pick::Qty => arg("qty"),
            Pick::Want => arg("want"),
            Pick::Words => arg("text"),
        }
    }

    /// What the spec must have for this choice, in words.
    pub fn needs(self) -> &'static str {
        match self {
            Pick::Person => "a spec with `target: true`",
            Pick::Item => "a spec with `item`",
            Pick::Qty => "`qty` in the spec's args",
            Pick::Want => "`want` in the spec's args",
            Pick::Words => "`text` in the spec's args",
        }
    }
}

vocab! {
    /// How an item is chosen (`choose`).
    Choose, CHOOSE { List = "list", Grid = "grid" }
}

vocab! {
    /// What a press does while the skill's combat stance is not met (`unready`).
    Unready, UNREADY {
        /// The press switches the state instead.
        Toggle = "toggle",
        /// The slot is greyed.
        Grey = "grey",
    }
}

vocab! {
    /// What shows while it runs (`running.show`).
    RunShow, RUN_SHOWS { Windup = "windup", Progress = "progress", Held = "held", None = "none" }
}

vocab! {
    /// How a refusal the client foresees is shown (`refused`).
    Refused, REFUSALS {
        /// Greyed, with the rules' own `_check` text as the reason.
        Grey = "grey",
        /// A note when the act is tried.
        Note = "note",
    }
}

vocab! {
    /// The ground marker while aiming (`marker`).
    Marker, MARKERS { Circle = "circle", Arc = "arc", Line = "line", None = "none" }
}

vocab! {
    /// How a way of speaking's experience kind is drawn (`rows`).
    Row, ROWS { Line = "line", Dots = "dots", Hidden = "hidden" }
}

vocab! {
    /// A way of speaking's bubble (`bubble`).
    Bubble, BUBBLES { Normal = "normal", Hushed = "hushed", None = "none" }
}

/// Named icons for skills and acts (`look.icon`). The client's theme maps each to an image.
pub const ICONS: &[&str] = &["sword", "bow", "fire", "shield", "dodge", "heal", "sheath", "give", "trade", "talk", "wave", "eye", "book", "hammer", "pot", "hand"];
/// Named icons for items (an item's `icon` trait).
pub const ITEM_ICONS: &[&str] = &["berries", "bread", "meat", "arrow", "spear", "wood", "stone", "herb", "torch", "cloth", "tablet", "tool", "vessel", "bundle"];
/// Clip families (`look.clip`): the client maps a family to its clips, rates and beats. `throw`
/// is the spear throw's take; `turn`, `step` and `play` are the town-life looks of `_shows()`.
pub const CLIPS: &[&str] = &["slash", "overhead", "thrust", "shoot", "throw", "cast", "guard", "dash", "jump", "bite", "leap", "gesture", "turn", "step", "play", "work", "eat", "sleep", "rest", "hand"];
/// Named effects (`look.effect`; `"none"` declares that it has none).
pub const EFFECTS: &[&str] = &["slash", "arrow", "bolt", "burst", "glow", "guard_arc"];
/// Body states a declaration may switch (`toggles`). Each is added only when the authority has
/// it; the drawn state is the Spark's to add, so none is listed yet.
pub const STATES: &[&str] = &[];
/// Item groups that order the pack (an item's `group` trait).
pub const ITEM_GROUPS: &[&str] = &["food", "tool", "material", "garment", "money"];

/// The keys of a `<name>_ui()` map.
pub const UI_TRAITS: &[&str] = &["label", "on", "place", "order", "input", "picks", "choose", "detail", "unready", "toggles", "drag", "pin", "running", "refused", "look", "marker", "key", "tip", "alias", "to_label", "room_label", "rows", "bubble"];
/// The keys only a way of speaking's `_ui()` may have.
pub const WAY_UI_TRAITS: &[&str] = &["alias", "to_label", "room_label", "rows", "bubble"];
/// The keys of `look`.
pub const LOOK_TRAITS: &[&str] = &["icon", "clip", "effect"];
/// The keys of `running`.
pub const RUNNING_TRAITS: &[&str] = &["show", "text"];

/// A missile at least this wide is a bolt (fire icon, cast, bolt effect); a narrower one an arrow.
pub const BOLT_RADIUS: f32 = 0.25;
/// Skill keys the bar has by default (Q E R).
pub const SKILL_KEYS: usize = 3;

/// The vocabulary's own spelling of a name, if the name is in it.
pub fn name_in(list: &'static [&'static str], s: &str) -> Option<&'static str> {
    list.iter().copied().find(|n| *n == s)
}

// ---- the declaration -----------------------------------------------------------------------

/// How a skill looks: a named icon, the clip families its move plays (one per press, in turn)
/// and its effect.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Look {
    pub icon: Option<&'static str>,
    pub clips: Vec<&'static str>,
    pub effect: Option<&'static str>,
}

/// What shows while it runs, and the words with it (`{item}` is the chosen item).
#[derive(Clone, Debug, PartialEq)]
pub struct Running {
    pub show: RunShow,
    pub text: String,
}

/// A way of speaking's presentation (only for a name with `_speech()`).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct WayUi {
    pub alias: Option<String>,
    pub to_label: Option<String>,
    pub room_label: Option<String>,
    /// How each experience kind the way declares is drawn.
    pub rows: BTreeMap<String, Row>,
    pub bubble: Option<Bubble>,
}

/// How one skill (or way of speaking) is presented: its `<name>_ui()` declaration over the
/// defaults ([`defaults`]), as `Scripts::ui` gives it. Presentation only: it grants nothing.
#[derive(Clone, Debug, PartialEq)]
pub struct UiSpec {
    /// The skill (or way) it presents: what acts are written with.
    pub name: String,
    /// Short display name.
    pub label: String,
    /// Where it attaches, in order; empty: nowhere (minds still have it in their graphs).
    pub on: Vec<On>,
    /// Its declared bar place (none: placed by aim, [`bar_places`]).
    pub place: Option<BarPlace>,
    /// Its declared position within its place or list (none: the script's order).
    pub order: Option<i64>,
    pub input: Input,
    pub picks: Vec<Pick>,
    pub choose: Choose,
    /// A script function that takes a choice's name and returns words describing it.
    pub detail: Option<String>,
    pub unready: Unready,
    /// The body state it switches.
    pub toggles: Option<&'static str>,
    /// Dropping an item on this kind of target does this act (`Person` or `Thing`).
    pub drag: Option<On>,
    /// Shown as a button in the person window.
    pub pin: bool,
    pub running: Running,
    /// How a foreseen refusal shows (none: grey on the bar, a note elsewhere: [`UiSpec::refused_at`]).
    pub refused: Option<Refused>,
    pub look: Look,
    pub marker: Marker,
    /// A suggested default key, used only if the player has not bound it.
    pub key: Option<String>,
    /// A first-time hint (`{key}` is the bound key).
    pub tip: Option<String>,
    /// For a way of speaking.
    pub way: Option<WayUi>,
    /// The script declares `<name>_ui()` (some fields may still be defaults).
    pub declared: bool,
}

impl UiSpec {
    pub fn is_on(&self, place: On) -> bool {
        self.on.contains(&place)
    }

    /// How a foreseen refusal shows at a place.
    pub fn refused_at(&self, place: On) -> Refused {
        self.refused.unwrap_or(if place == On::Bar { Refused::Grey } else { Refused::Note })
    }
}

/// A name as a label: `_` as a space, the first letter capitalised (`fire_bolt` → "Fire bolt").
pub fn label_of(name: &str) -> String {
    let s = name.replace('_', " ");
    let mut c = s.chars();
    c.next().map(|f| f.to_uppercase().chain(c).collect()).unwrap_or_default()
}

// ---- the defaults ----------------------------------------------------------------------------

/// What a skill's defaults are derived from: its spec, its combat shape and missile (as a
/// newcomer person's, like `skill_card`), whether it is on `skill_bar()`, whether the rules
/// check it (`<name>_check`), and its `_shows().look`.
#[derive(Clone, Copy, Debug)]
pub struct Source<'a> {
    pub name: &'a str,
    pub spec: Option<&'a SkillSpec>,
    pub shape: Option<&'a Shape>,
    pub missile: Option<MissileSpec>,
    pub on_bar: bool,
    pub checked: bool,
    pub shows: Option<&'a str>,
}

// The vocabulary's words the defaults use, named once (no word in the code below is a skill's
// name, even where a word is spelt like one: the `jump` clip, the `heal` icon).
const ICON_SWORD: &str = "sword";
const ICON_BOW: &str = "bow";
const ICON_FIRE: &str = "fire";
const ICON_SHIELD: &str = "shield";
const ICON_DODGE: &str = "dodge";
const ICON_HEAL: &str = "heal";
const CLIP_SLASH: &str = "slash";
const CLIP_SHOOT: &str = "shoot";
const CLIP_CAST: &str = "cast";
const CLIP_GUARD: &str = "guard";
const CLIP_DASH: &str = "dash";
const CLIP_JUMP: &str = "jump";
const EFFECT_SLASH: &str = "slash";
const EFFECT_ARROW: &str = "arrow";
const EFFECT_BOLT: &str = "bolt";

/// How a skill is aimed and looks by its combat shape, as the client drew any skill it did not
/// know by name (`combat.rs` `look()`): icon, clips and effect.
pub fn look_by_aim(shape: &Shape, missile: Option<MissileSpec>) -> Look {
    let l = |icon: &'static str, clip: &'static str, effect: Option<&'static str>| Look { icon: Some(icon), clips: vec![clip], effect };
    match shape.aim {
        Aim::Point if missile.is_some_and(|m| m.radius >= BOLT_RADIUS) => l(ICON_FIRE, CLIP_CAST, Some(EFFECT_BOLT)),
        Aim::Point => l(ICON_BOW, CLIP_SHOOT, Some(EFFECT_ARROW)),
        Aim::Facing => l(ICON_SHIELD, CLIP_GUARD, None),
        // A dash that does not evade is a jump (the WIP's `Roles::of` reads it the same way).
        Aim::Dash if !shape.evades => l(ICON_DODGE, CLIP_JUMP, None),
        Aim::Dash => l(ICON_DODGE, CLIP_DASH, None),
        Aim::SelfOrAlly => l(ICON_HEAL, CLIP_CAST, None),
        Aim::Creature => l(ICON_SWORD, CLIP_SLASH, Some(EFFECT_SLASH)),
        Aim::None => Look::default(),
    }
}

/// The input a combat aim takes on the bar.
pub fn input_by_aim(aim: Aim) -> Input {
    match aim {
        Aim::Point => Input::AimPoint,
        Aim::Facing => Input::Hold,
        Aim::Creature | Aim::SelfOrAlly | Aim::Dash | Aim::None => Input::Tap,
    }
}

/// The ground marker a combat aim shows while its key is held (`combat.rs` `indicators`).
pub fn marker_by_aim(aim: Aim) -> Marker {
    match aim {
        Aim::Creature | Aim::SelfOrAlly => Marker::Circle,
        Aim::Point => Marker::Line,
        Aim::Facing => Marker::Arc,
        Aim::Dash | Aim::None => Marker::None,
    }
}

/// Where a skill attaches by default: the bar for a skill in `skill_bar()`; and, unless it is
/// real-time combat (the bar's) or takes an argument a player cannot give (a behaviour graph),
/// the F list toward a creature and (when the rules check it) a thing if it takes a target,
/// oneself otherwise, and the pack if it takes an item. This is the game client's F and C list
/// today (`verbs.rs` `plan`).
pub fn on_by_spec(src: &Source) -> Vec<On> {
    let mut on = Vec::new();
    if src.on_bar {
        on.push(On::Bar);
    }
    let Some(spec) = src.spec else { return on };
    if src.shape.is_some_and(|s| s.real_time) || spec.args.iter().any(|a| a == "graph") {
        return on;
    }
    if spec.needs_target {
        on.push(On::Person);
        if src.checked {
            on.push(On::Thing);
        }
    } else {
        on.push(On::Me);
    }
    if spec.needs_item {
        on.push(On::Item);
    }
    on
}

/// What must be chosen, from the spec.
pub fn picks_by_spec(spec: &SkillSpec) -> Vec<Pick> {
    Pick::ALL.iter().copied().filter(|p| p.fits(spec)).collect()
}

/// A skill's presentation when it declares nothing. A world that declares nothing plays as the
/// game client did before declarations.
pub fn defaults(src: &Source) -> UiSpec {
    let aim = src.shape.map_or(Aim::None, |s| s.aim);
    let mut look = src.shape.map(|s| look_by_aim(s, src.missile)).unwrap_or_default();
    // A shown skill plays its `_shows().look` (a gesture, work, sleep), when that is a family.
    if let Some(c) = src.shows.and_then(|l| name_in(CLIPS, l)) {
        look.clips = vec![c];
    }
    let show = match src.shape {
        Some(s) if s.aim == Aim::Facing => RunShow::Held,
        Some(s) if s.timed => RunShow::Windup,
        // Work that is not dropped half-done (eating, building, sleeping) lasts a while.
        _ if src.spec.is_some_and(|k| k.latch) => RunShow::Progress,
        _ => RunShow::None,
    };
    UiSpec {
        name: src.name.to_string(),
        label: label_of(src.name),
        on: on_by_spec(src),
        place: None,
        order: None,
        input: input_by_aim(aim),
        picks: src.spec.map(picks_by_spec).unwrap_or_default(),
        choose: Choose::List,
        detail: None,
        unready: Unready::Grey,
        toggles: None,
        drag: None,
        pin: false,
        running: Running { show, text: String::new() },
        refused: None,
        look,
        marker: marker_by_aim(aim),
        key: None,
        tip: None,
        way: None,
        declared: false,
    }
}

// ---- the bar ---------------------------------------------------------------------------------

/// One skill that may go on the bar, for [`bar_places_of`]: how the rules aim it, whether a dash
/// evades, its missile's radius (0: none), and its declared place and order.
#[derive(Clone, Debug, PartialEq)]
pub struct BarEntry {
    pub name: String,
    pub aim: Aim,
    pub evades: bool,
    pub radius: f32,
    pub place: Option<BarPlace>,
    pub order: Option<i64>,
}

/// Which skill is on which place of the bar.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Bar {
    pub primary: Option<String>,
    pub secondary: Option<String>,
    /// The skill keys in order (Q E R by default; at least [`SKILL_KEYS`]); a key may be empty.
    pub skill: Vec<Option<String>>,
    pub jump: Option<String>,
    pub dodge: Option<String>,
    pub weapon: Option<String>,
    /// Every other bar skill, in order (the extra row, then the skills window).
    pub extra: Vec<String>,
}

impl Bar {
    /// The skill at a place (`index`: the key, for `Skill` and `Extra`).
    pub fn at(&self, place: BarPlace, index: usize) -> Option<&str> {
        match place {
            BarPlace::Primary => self.primary.as_deref(),
            BarPlace::Secondary => self.secondary.as_deref(),
            BarPlace::Skill => self.skill.get(index).and_then(|s| s.as_deref()),
            BarPlace::Jump => self.jump.as_deref(),
            BarPlace::Dodge => self.dodge.as_deref(),
            BarPlace::Weapon => self.weapon.as_deref(),
            BarPlace::Extra => self.extra.get(index).map(|s| s.as_str()),
        }
    }

    /// Every placed skill: its place, its index there and its name, in the places' order.
    pub fn iter(&self) -> impl Iterator<Item = (BarPlace, usize, &str)> {
        fn one(p: BarPlace, s: &Option<String>) -> Option<(BarPlace, usize, &str)> {
            s.as_deref().map(|n| (p, 0, n))
        }
        one(BarPlace::Primary, &self.primary)
            .into_iter()
            .chain(one(BarPlace::Secondary, &self.secondary))
            .chain(self.skill.iter().enumerate().filter_map(|(i, s)| s.as_deref().map(|n| (BarPlace::Skill, i, n))))
            .chain(one(BarPlace::Jump, &self.jump))
            .chain(one(BarPlace::Dodge, &self.dodge))
            .chain(one(BarPlace::Weapon, &self.weapon))
            .chain(self.extra.iter().enumerate().map(|(i, n)| (BarPlace::Extra, i, n.as_str())))
    }

    /// Where a skill is on the bar.
    pub fn place_of(&self, skill: &str) -> Option<(BarPlace, usize)> {
        self.iter().find(|(_, _, n)| *n == skill).map(|(p, i, _)| (p, i))
    }

    fn slot(&mut self, place: BarPlace, index: usize) -> Option<&mut Option<String>> {
        Some(match place {
            BarPlace::Primary => &mut self.primary,
            BarPlace::Secondary => &mut self.secondary,
            BarPlace::Skill => {
                if self.skill.len() <= index {
                    self.skill.resize(index + 1, None);
                }
                &mut self.skill[index]
            }
            BarPlace::Jump => &mut self.jump,
            BarPlace::Dodge => &mut self.dodge,
            BarPlace::Weapon => &mut self.weapon,
            BarPlace::Extra => return None,
        })
    }
}

/// The most skill keys a declared `order` may name.
const MOST_SKILL_KEYS: usize = 12;

/// Which skill goes on which place, from the bar's skills in bar order. Declared places come
/// first: a `skill` place with an `order` takes that key, one without the first free key; an
/// `extra` joins the extra row by its order. Then each place takes the first skill not yet
/// placed whose aim fits it, as the step-4 WIP's `Roles::of` did: the primary a skill aimed at a
/// creature; the secondary a skillshot with an arrow (radius under [`BOLT_RADIUS`]); the skill
/// keys a guard, a heal (oneself or an ally) and any skillshot (a key a declaration took passes
/// to the first free key); the jump a dash that does not evade; the dodge any dash. Every skill
/// left goes to the extra row, in bar order. A single
/// place claimed twice keeps the first claim (an install refuses the second).
pub fn bar_places_of(entries: &[BarEntry]) -> Bar {
    let mut bar = Bar { skill: vec![None; SKILL_KEYS], ..Default::default() };
    let mut placed: Vec<&str> = Vec::new();
    let mut extra: Vec<(i64, usize, &str)> = Vec::new();
    // Declared places: with an order first, then without.
    for with_order in [true, false] {
        for (i, e) in entries.iter().enumerate() {
            let Some(place) = e.place else { continue };
            if e.order.is_some() != with_order || placed.contains(&e.name.as_str()) {
                continue;
            }
            if place == BarPlace::Extra {
                extra.push((e.order.unwrap_or(i64::MAX), i, &e.name));
                placed.push(&e.name);
                continue;
            }
            let index = match (place, e.order) {
                (BarPlace::Skill, Some(o)) => (o.max(0) as usize).min(MOST_SKILL_KEYS - 1),
                (BarPlace::Skill, None) => bar.skill.iter().position(|s| s.is_none()).unwrap_or(bar.skill.len()),
                _ => 0,
            };
            if let Some(slot) = bar.slot(place, index).filter(|s| s.is_none()) {
                *slot = Some(e.name.clone());
                placed.push(&e.name);
            }
        }
    }
    // Places by aim, for the skills not declared.
    type Fits = fn(&BarEntry) -> bool;
    let by_aim: [(BarPlace, usize, Fits); 7] = [
        (BarPlace::Primary, 0, |e| e.aim == Aim::Creature),
        (BarPlace::Secondary, 0, |e| e.aim == Aim::Point && e.radius < BOLT_RADIUS),
        (BarPlace::Skill, 0, |e| e.aim == Aim::Facing),
        (BarPlace::Skill, 1, |e| e.aim == Aim::SelfOrAlly),
        (BarPlace::Skill, 2, |e| e.aim == Aim::Point),
        (BarPlace::Jump, 0, |e| e.aim == Aim::Dash && !e.evades),
        (BarPlace::Dodge, 0, |e| e.aim == Aim::Dash),
    ];
    // A skill key a declaration took passes its skill to the first key free after the others.
    let mut displaced: Vec<Fits> = Vec::new();
    for (place, index, fits) in by_aim {
        if bar.at(place, index).is_some() {
            if place == BarPlace::Skill {
                displaced.push(fits);
            }
            continue;
        }
        if let Some(e) = entries.iter().find(|e| e.place.is_none() && !placed.contains(&e.name.as_str()) && fits(e)) {
            if let Some(slot) = bar.slot(place, index) {
                *slot = Some(e.name.clone());
                placed.push(&e.name);
            }
        }
    }
    for fits in displaced {
        let Some(free) = bar.skill.iter().position(|s| s.is_none()) else { break };
        if let Some(e) = entries.iter().find(|e| e.place.is_none() && !placed.contains(&e.name.as_str()) && fits(e)) {
            bar.skill[free] = Some(e.name.clone());
            placed.push(&e.name);
        }
    }
    for (i, e) in entries.iter().enumerate() {
        if !placed.contains(&e.name.as_str()) {
            extra.push((i64::MAX, i, &e.name));
            placed.push(&e.name);
        }
    }
    extra.sort();
    bar.extra = extra.into_iter().map(|(_, _, n)| n.to_string()).collect();
    bar
}

/// Which skill goes on which place of the world's bar ([`bar_places_of`]): the skills of
/// `skill_bar()` in its order, then any other skill declared `on: "bar"` (a weapon's toggle), in
/// the script's order.
#[cfg(feature = "scripting")]
pub fn bar_places(s: &crate::script::Scripts) -> Bar {
    bar_places_of(&s.bar_entries())
}

// ---- one filter for players and minds ---------------------------------------------------------

/// The skills a body is offered, in the script's order: for players (the F and C lists, the K
/// window) and minds (their skill reference) alike. A body whose species names its skills gets
/// those; any other (people) every skill not `listed: false`. `signal` only to a body with
/// signals. `None` is a body the species list does not describe (a person, as the shipped
/// catalog lists skills).
pub fn offered<'a>(skills: &'a Skills, body: Option<&crate::species::Species>) -> Vec<&'a SkillSpec> {
    skills
        .iter()
        .filter(|s| match body {
            None => s.listed,
            Some(sp) => sp.allows(&s.name) && (sp.skills.is_some() || s.listed) && (s.name != "signal" || !sp.signals.is_empty()),
        })
        .collect()
}

/// Whether a skill is ongoing or real-time behaviour (it belongs in a graph or on the bar, not
/// in a one-off act), for players and minds alike: [`Shapes::real_time_in`].
pub fn real_time(skills: &Skills, shapes: &Shapes, skill: &str) -> bool {
    shapes.real_time_in(skills, skill)
}

// ---- what a player sends ---------------------------------------------------------------------

/// What an act from the interface is aimed at.
#[derive(Clone, Debug, PartialEq)]
pub enum ActTarget {
    /// Oneself: no target.
    Me,
    /// A creature the player perceives.
    Creature(u32),
    /// A thing by its kind; `at`, when it is not the nearest of its kind: walk there first.
    Thing { kind: String, at: Option<[f32; 2]> },
    /// A point on the ground.
    At([f32; 2]),
}

/// What the player chose for an act (an item's amount is 1 unless chosen, as today).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Picked {
    pub item: Option<String>,
    pub qty: Option<u32>,
    pub want: Option<String>,
    pub want_qty: Option<u32>,
    pub text: Option<String>,
}

/// The `human_act` node for an act: the leaf `{"do": skill, ...}` a mind writes, or toward a
/// thing that is not the nearest of its kind `seq[goto, leaf]` (acts name things by kind, nearest
/// first). The game client's `Choice::node`, moved here.
pub fn act_node(skill: &str, target: &ActTarget, picked: &Picked) -> serde_json::Value {
    use serde_json::json;
    let mut leaf = json!({"do": skill});
    match target {
        ActTarget::Me => {}
        ActTarget::Creature(id) => leaf["target"] = json!({"id": id}),
        ActTarget::Thing { kind, .. } => leaf["target"] = json!({"nearest": kind}),
        ActTarget::At(p) => leaf["target"] = json!({"at": p}),
    }
    if let Some(i) = &picked.item {
        leaf["item"] = i.clone().into();
        leaf["qty"] = picked.qty.unwrap_or(1).into();
    }
    if let Some(w) = &picked.want {
        leaf["want"] = w.clone().into();
        leaf["want_qty"] = picked.want_qty.unwrap_or(1).into();
    }
    if let Some(t) = &picked.text {
        leaf["text"] = t.clone().into();
    }
    match target {
        ActTarget::Thing { at: Some(p), .. } => json!({"seq": [{"do": "goto", "target": {"at": p}}, leaf]}),
        _ => leaf,
    }
}

/// The graph leaf a bar press is the same as (`use_skill(skill, target, x, y)` on the authority;
/// the leaf a mind writes in its graph): a creature for a skill aimed at one, oneself or an ally,
/// else the aimed point.
pub fn bar_act(skill: &str, aim: Aim, target: Option<u32>, at: [f32; 2]) -> serde_json::Value {
    let t = match (aim, target) {
        (Aim::Creature, Some(id)) | (Aim::SelfOrAlly, Some(id)) => ActTarget::Creature(id),
        (Aim::SelfOrAlly, None) => ActTarget::Me,
        _ => ActTarget::At(at),
    };
    act_node(skill, &t, &Picked::default())
}

#[cfg(test)]
mod tests;
