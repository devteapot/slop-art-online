//! The game UI's view-model: everything the widgets draw, and nothing else.
//!
//! One source fills it each frame: the authority's rows when connected (`live.rs`), or
//! representative sample values in look-dev (`sample.rs`). Widgets read only this model, so the
//! layout can be judged without a server, and the live wiring is one module. The model holds
//! presentation data only: no rules run here.

use bevy::prelude::*;

#[derive(Resource, Default)]
pub struct HudModel {
    /// Whether any source is filling the model (look-dev without `LIVING_GAME_HUD` has none).
    pub shown: bool,
    pub me: Option<Me>,
    pub skills: Vec<Skill>,
    pub target: Option<TargetInfo>,
    /// Characters near enough to get a nameplate if relevant (hovered, targeted, talking, hostile).
    pub actors: Vec<Actor>,
    pub bubbles: Vec<Bubble>,
    /// What I heard (and said), oldest first.
    pub log: Vec<LogLine>,
    pub hint: Option<Hint>,
    pub death: Option<Death>,
    /// Floating combat numbers (damage dealt and taken, healing).
    pub numbers: Vec<FloatNumber>,
    pub map: MapInfo,
    /// The verbs' list, notes and panels (`verbs.rs`); all hidden by default.
    pub verbs: VerbsView,
    /// The connection, when it is not live after having been: a notice of being offline and
    /// reconnecting (no one is drawn meanwhile).
    pub link: Option<String>,
    /// Model time (seconds), for fades.
    pub now: f64,
}

#[derive(Default)]
pub struct VerbsView {
    pub menu: Option<MenuView>,
    /// What the authority said of my acts: text, worked (or not, or just started), age (s).
    pub toasts: Vec<(String, Option<bool>, f32)>,
    pub inventory: Option<InventoryView>,
    pub know_how: Option<KnowHowView>,
}

pub struct MenuView {
    pub title: String,
    pub rows: Vec<MenuRowView>,
    /// An open sub-list (a skill with many items: "Give ›"), beside the list.
    pub sub: Option<(String, Vec<MenuRowView>)>,
    /// Toward whom (an icon and the place beside their head), or where the UI put it.
    pub person: Option<u32>,
    pub at: Option<Vec2>,
}

pub struct MenuRowView {
    pub label: String,
    /// The rules' skill (or `talk`, `window`), for its icon and key.
    pub skill: String,
    pub group: bool,
    /// How many of its item I carry, for a sub-list's count.
    pub have: u32,
}

pub struct InventoryView {
    /// Item, how many, and a short note from the rules (food value).
    pub rows: Vec<(String, u32, String)>,
    /// How much is carried against the rules' limit (fractional once goods count by their own
    /// weight); a limit of 0 is none.
    pub carried: f32,
    pub limit: f32,
}

pub struct KnowHowView {
    /// Techniques I know, and how I came by each.
    pub techniques: Vec<(String, String)>,
    /// The skills shown in the list (a window round the selected one), and which is selected.
    pub skills: Vec<String>,
    pub selected: usize,
    /// The first skill shown.
    pub start: usize,
    pub detail: SkillDetail,
}

#[derive(Default)]
pub struct SkillDetail {
    pub name: String,
    pub help: String,
    pub takes: String,
    pub gives: String,
}

pub struct Me {
    pub name: String,
    pub hp: f32,
    pub max_hp: f32,
    /// The rules' `energy` need, 0..100 (what a skill's cost is checked against today).
    pub energy: f32,
    pub max_energy: f32,
    /// The bars, as the world's `meters()` lists them (shown ones, in order): each value moved
    /// along its rate since its row was written, so a bar refills between updates.
    pub meters: Vec<MeterView>,
    /// How the body is, as the world's `status_of` says (the pills).
    pub statuses: Vec<StatusView>,
    /// Every meter now, named by the field it shows (a skill card's `pool`): what a bar slot's
    /// cost is checked against.
    pub pools: Vec<MeterView>,
    /// 1 just after being hurt, fading to 0 (a flash on the health bar).
    pub hurt: f32,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum StatusKind {
    Hungry,
    Starving,
    Tired,
    Exhausted,
    Wasting,
    Recovering,
    InCombat,
    Talking,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Tone {
    Good,
    Warn,
    Bad,
    Plain,
}

impl Tone {
    /// A status's tone as the rules name it (`TONES`: good, warn, bad, plain).
    pub fn parse(s: &str) -> Tone {
        match s {
            "good" => Tone::Good,
            "warn" => Tone::Warn,
            "bad" => Tone::Bad,
            _ => Tone::Plain,
        }
    }
}

/// One bar of my body (`meters()`): its words and where it stands now.
#[derive(Clone, Debug, PartialEq)]
pub struct MeterView {
    pub name: String,
    pub label: String,
    pub value: f32,
    pub max: f32,
}

/// One status pill (`status_of`): its name, how it reads and its words.
#[derive(Clone, Debug, PartialEq)]
pub struct StatusView {
    pub name: String,
    pub tone: Tone,
    pub text: String,
}

pub struct Status {
    pub kind: StatusKind,
    pub tone: Tone,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Key {
    Lmb,
    Rmb,
    Q,
    E,
    R,
    Shift,
}

impl Key {
    /// F is the interaction key, not a skill (user, 2026-11-09).
    pub const BAR: [Key; 6] = [Key::Lmb, Key::Rmb, Key::Q, Key::E, Key::R, Key::Shift];

    pub fn label(self) -> &'static str {
        match self {
            Self::Lmb => "LMB",
            Self::Rmb => "RMB",
            Self::Q => "Q",
            Self::E => "E",
            Self::R => "R",
            Self::Shift => "Shift",
        }
    }
}

/// A skill's glyph and colour family.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum SkillIcon {
    Sword,
    Bow,
    Fire,
    Shield,
    Dodge,
    Heal,
    Jump,
    Empty,
}

#[derive(Clone, PartialEq, Debug)]
pub enum SkillState {
    Ready,
    /// Held or running (block raised).
    Active,
    Cooldown { left: f32, total: f32 },
    /// Can't be used now, and why.
    Unavailable(String),
    /// Nothing in this slot.
    Empty,
}

pub struct Skill {
    pub key: Key,
    pub icon: SkillIcon,
    pub state: SkillState,
    /// The rules' skill on this place of the bar, its energy cost, and how many of what it
    /// spends I carry (arrows), if it spends something.
    pub name: String,
    pub cost: f32,
    pub count: Option<u32>,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Stance {
    Hostile,
    Neutral,
}

pub struct Actor {
    pub id: u64,
    pub name: String,
    /// Just above the head, in world space.
    pub head: Vec3,
    pub distance: f32,
    pub hovered: bool,
    pub targeted: bool,
    pub talking: bool,
    /// Just answered my greeting (a nod or a wave back): their name shows for a moment.
    pub greeted: bool,
    pub stance: Stance,
    /// Health fraction, only when perceived.
    pub hp: Option<f32>,
    /// Exact health and its maximum, only while I perceive it exactly (an appraisal holds).
    pub exact: Option<(f32, f32)>,
    /// A person (not an animal).
    pub kind_person: bool,
}

pub struct TargetInfo {
    pub name: String,
    /// What it is doing, when that matters (talking, fighting), as an icon.
    pub doing: Option<StatusKind>,
    pub hp: Option<f32>,
    pub stance: Stance,
    pub distance: f32,
}

pub struct FloatNumber {
    /// Where it rises from (world space, above the head).
    pub at: Vec3,
    pub amount: f32,
    pub kind: NumberKind,
    /// Seconds since it appeared.
    pub age: f32,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum NumberKind {
    Dealt,
    Taken,
    Healed,
    Blocked,
}

pub struct Bubble {
    pub speaker: u64,
    pub name: String,
    pub text: String,
    pub head: Vec3,
    /// Seconds since it was said, and how long it stays.
    pub age: f32,
    pub life: f32,
    pub mine: bool,
}

/// How long a heard line stays over the speaker: longer lines stay longer.
pub fn bubble_life(text: &str) -> f32 {
    (3.5 + text.chars().count() as f32 * 0.06).min(10.0)
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum LogKind {
    Heard,
    Mine,
    /// Said to me directly.
    ToMe,
}

pub struct LogLine {
    /// Model time it arrived (seconds).
    pub at: f64,
    pub who: String,
    pub text: String,
    pub kind: LogKind,
}

pub struct Hint {
    pub key: String,
    pub label: String,
}

pub struct Death {
    /// "Killed by Varek", "Starved".
    pub cause: String,
    /// Where, if known.
    pub place: Option<String>,
    /// "2 days, 7 hours".
    pub lived: Option<String>,
    /// Who saw it; `None` when the authority doesn't say.
    pub witnesses: Option<Vec<String>>,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum PoiKind {
    Town,
    Village,
    Giants,
    SmallFolk,
    Cave,
    Place,
}

pub struct Poi {
    pub kind: PoiKind,
    /// Ground position (game x, z).
    pub at: Vec2,
}

#[derive(Default)]
pub struct MapInfo {
    /// My ground position (game x, z).
    pub me: Option<Vec2>,
    /// Where I face (game x, z).
    pub facing: Option<Vec2>,
    /// View yaw, degrees (0 = north up, clockwise).
    pub yaw: f32,
    pub pois: Vec<Poi>,
    /// The name of where I am: the nearest place my character knows, if near enough.
    pub place: Option<String>,
}

/// What the player asked of the UI this frame; the active source carries it out.
#[derive(Resource, Default)]
pub struct Outbox {
    /// Lines to say, and to whom (a character id; 0 for no one in particular).
    pub say: Vec<(String, u32)>,
    pub rejoin: bool,
}
