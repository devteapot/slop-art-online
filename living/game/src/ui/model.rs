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
    /// Model time (seconds), for fades.
    pub now: f64,
}

pub struct Me {
    pub name: String,
    pub hp: f32,
    pub max_hp: f32,
    /// The rules' `energy` need, 0..100: the resource bar.
    pub energy: f32,
    pub max_energy: f32,
    pub statuses: Vec<Status>,
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
}

/// What the player asked of the UI this frame; the active source carries it out.
#[derive(Resource, Default)]
pub struct Outbox {
    pub say: Vec<String>,
    pub rejoin: bool,
}
