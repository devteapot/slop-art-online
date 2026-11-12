//! Combat on the client (docs/COMBAT.md): presentation and input only. The authority decides
//! every move, hit and death; this module
//!
//! - reads what my character perceived (`my_combat`, transient rows the authority writes only
//!   for what my character could see) and what others look like in a fight (`fighter`, through
//!   the body window), and my own timing (`my_readiness`);
//! - maps the skill bar's keys to `use_skill` / `release_skill`, aiming skillshots at the
//!   cursor's ground point and targeted skills at the creature under or nearest the cursor;
//! - picks the clip each drawn character plays for its move, a hit or its death (an animal's
//!   from its own clips by the move's aim, [`animal_clip`]);
//! - predicts only my own move's clip at the moment I press (the authority's answer arrives a
//!   round trip later): the prediction ends when the authority's `fighter` row confirms it,
//!   when a `REFUSED` arrives, or after [`PREDICT_MS`] without either. Movement is never
//!   predicted: the dodge's dash is the authority's, and so is its clip, which carries no
//!   travel and plays as the body dashes.
//! - draws the aim and range indicators while a skill key is held.
//!
//! Which skill is which comes from the authority's `skill_card` rows ([`Cards`]): the bar's
//! order, each skill's presentation code, how it is aimed, its reach, a missile's radius and a
//! guard's arc. How a skill looks (its clip, effect and icon) is this client's own choice
//! ([`look`]), by name for the skills it was drawn for and otherwise from how the rules aim it,
//! so a skill the rules add shows without a client change.

use crate::camera::Cam;
use crate::controls::{Input, Target};
use crate::net::Net;
use crate::ui::model::SkillIcon;
use crate::world::Scene;
use crate::phase::Phase;
use bevy::prelude::*;
use living_bindings::*;
use living_rules::combat::seen;
use spacetimedb_sdk::Table;
use std::collections::{HashMap, HashSet};

/// How long a press waits for the authority's answer before its predicted clip is dropped.
const PREDICT_MS: f64 = 600.0;
/// How long a corpse stays drawn after the authority removes the body (s).
pub const CORPSE_S: f64 = 7.0;
/// How long a hit reaction plays (ms).
const HIT_MS: f64 = 450.0;

/// What a drawn character plays for a move.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Action {
    pub clip: &'static str,
    pub rate: f32,
    /// When it started (display ms); a new start replays the clip.
    pub start_ms: f64,
    /// Hold the pose at this fraction of the clip (a raised guard, the fallen body).
    pub hold: Option<f32>,
    /// Facing during the move (sim direction).
    pub face: Option<Vec2>,
    /// Where in the clip it starts (s), and where it starts fading out (s; the clip's end when
    /// none): a move plays only its motion, timed to the rules' windup ([`timing`]).
    pub from: f32,
    pub cut: Option<f32>,
    /// A whole-body clip that lets the gait go on stepping under it (a moving jump's take, so the
    /// gait is in stride when the take fades at landing; `anim.rs`).
    pub gait: bool,
}

impl Default for Action {
    fn default() -> Self {
        Self { clip: "", rate: 1.0, start_ms: 0.0, hold: None, face: None, from: 0.0, cut: None, gait: false }
    }
}

/// One perceived event, as received.
#[derive(Clone, Debug)]
pub struct Event {
    pub row: CombatSeen,
    /// Display time it arrived (ms).
    pub seen_ms: f64,
}

/// A floating number.
#[derive(Clone, Debug)]
pub struct Number {
    pub at: Vec2,
    pub amount: f32,
    pub kind: NumberKind,
    pub born_ms: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NumberKind {
    Dealt,
    Taken,
    Healed,
    Blocked,
}

#[derive(Resource, Default)]
pub struct Combat {
    seen_ids: HashSet<u64>,
    /// Events that arrived this frame (effects spawn from these).
    pub fresh: Vec<Event>,
    /// The last few seconds of events (hit reactions, death screen).
    pub recent: Vec<Event>,
    pub numbers: Vec<Number>,
    /// Bodies that died in my sight (display ms of the death), drawn as corpses for a while.
    pub deaths: HashMap<u32, f64>,
    /// Who saw my last character die (character ids), and who killed it.
    pub witnesses: Vec<u32>,
    pub killer: Option<u32>,
    /// The creature my targeted skills go to: under or nearest the cursor.
    pub target: Option<u32>,
    /// What each drawn character plays now.
    pub actions: HashMap<u32, Action>,
    /// My pressed move awaiting the authority: (skill, pressed at display ms).
    predicted: Option<(String, f64)>,
    /// When I last pressed each skill (display ms), for the HUD until readiness arrives.
    pub pressed: HashMap<String, f64>,
    /// The last refusal (why, display ms), and of which skill.
    pub refusal: Option<(String, f64)>,
    pub refused_skill: Option<String>,
    /// Which skill key is held (indicators), and since when.
    pub aiming: Option<String>,
    pub guarding: bool,
    /// A move is being aimed at the cursor now: a key held on a skill aimed at a creature or a
    /// point, or a guard up (`controls::Control::Travel` turns my body to the cursor only then).
    pub aims: bool,
    /// The direction a raised guard was sent toward (sim, unit): the authority keeps the aim
    /// of the press, so the arc shows that, not the cursor.
    guard_dir: Option<Vec2>,
    /// Count of presses (alternating strike clips).
    strikes: u32,
    /// Where a script aims an indicator (instead of the cursor).
    script_aim: Option<Vec2>,
    /// Drawn bodies that are animals (not people), remembered past their body row so a
    /// corpse keeps playing its own death.
    animals: HashSet<u32>,
}

/// The rules' combat skills as the authority states them (`skill_card`), read each frame.
#[derive(Resource, Default)]
pub struct Cards {
    pub all: Vec<SkillCard>,
}

/// `skill_card.slot` of a skill that is not on the bar.
const NOT_ON_BAR: u8 = u8::MAX;
/// Bar slots: LMB, RMB, Q, E, R, Shift.
pub const SLOTS: usize = 6;

impl Cards {
    pub fn by_name(&self, skill: &str) -> Option<&SkillCard> {
        self.all.iter().find(|c| c.skill == skill)
    }

    /// The skill a presentation code names (`fighter.act`, `combat_seen.skill`).
    pub fn by_code(&self, code: u8) -> Option<&SkillCard> {
        (code != 0).then(|| self.all.iter().find(|c| c.code == code)).flatten()
    }

    pub fn code(&self, skill: &str) -> u8 {
        self.by_name(skill).map_or(0, |c| c.code)
    }

    /// The skill on a bar slot.
    pub fn slot(&self, slot: usize) -> Option<&SkillCard> {
        self.all.iter().find(|c| c.slot as usize == slot && c.slot != NOT_ON_BAR)
    }

    /// A skill on the bar, by name.
    pub fn on_bar(&self, skill: &str) -> Option<&SkillCard> {
        self.by_name(skill).filter(|c| c.slot != NOT_ON_BAR)
    }
}

/// The bar's places and the rules' skills on them: `living_rules::ui::bar_places` (declared
/// places first, then by aim), with the bar skills the rules call hostile (greyed while the
/// weapon is sheathed, `weapon.rs`, until the rules' `stance` replaces it).
#[derive(Resource, Default, Clone, Debug, PartialEq)]
pub struct Roles {
    pub bar: living_rules::ui::Bar,
    pub hostile: Vec<String>,
    /// Each bar skill's label (`<name>_ui()`'s, else its name as words).
    pub labels: HashMap<String, String>,
}

impl Roles {
    /// The skill a binding uses, if any.
    pub fn skill(&self, a: crate::keys::Act) -> Option<&str> {
        use crate::keys::Act;
        use living_rules::ui::BarPlace;
        match a {
            Act::Primary => self.bar.at(BarPlace::Primary, 0),
            Act::Secondary => self.bar.at(BarPlace::Secondary, 0),
            Act::Skill1 => self.bar.at(BarPlace::Skill, 0),
            Act::Skill2 => self.bar.at(BarPlace::Skill, 1),
            Act::Skill3 => self.bar.at(BarPlace::Skill, 2),
            Act::Extra(i) => self.bar.at(BarPlace::Extra, i as usize),
            Act::Jump => self.bar.at(BarPlace::Jump, 0),
            Act::Dodge => self.bar.at(BarPlace::Dodge, 0),
            _ => None,
        }
    }

    pub fn is_hostile(&self, skill: &str) -> bool {
        self.hostile.iter().any(|h| h == skill)
    }

    pub fn dodge(&self) -> Option<&str> {
        self.bar.dodge.as_deref()
    }

    pub fn extra(&self) -> &[String] {
        &self.bar.extra
    }
}

/// The bar's acts, in the order presses are sent (as before: the mouse, then the keys).
pub const BAR_ACTS: [crate::keys::Act; 13] = {
    use crate::keys::Act::*;
    [Primary, Secondary, Skill1, Skill3, Skill2, Extra(0), Extra(1), Extra(2), Extra(3), Extra(4), Extra(5), Jump, Dodge]
};

fn read_roles(rules: NonSend<crate::verbs::Rules>, mut roles: ResMut<Roles>, mut names: ResMut<crate::ui::settings::SkillNames>, mut revision: Local<Option<u32>>) {
    // Once per compile of the world's rules.
    let Some(sc) = rules.scripts.as_ref() else { return };
    if *revision == Some(rules.revision) {
        return;
    }
    *revision = Some(rules.revision);
    let bar = living_rules::ui::bar_places(sc);
    let shapes = sc.shapes();
    let hostile = bar.iter().filter(|(_, _, n)| shapes.get(n).is_some_and(|s| s.hostile)).map(|(_, _, n)| n.to_string()).collect();
    let labels: HashMap<String, String> = bar.iter().map(|(_, _, n)| (n.to_string(), sc.ui(n).map_or_else(|| living_rules::ui::label_of(n), |u| u.label.clone()))).collect();
    if let Ok(mut g) = LOOK_NAMES.write() {
        *g = Some(sc.ui_specs().map(|u| (u.name.clone(), u.look.clone())).collect());
    }
    for e in sc.ui_errors() {
        warn!("rules: {e} (shown with its defaults)");
    }
    use living_rules::ui::BarPlace;
    info!("combat: bar places primary {:?}, secondary {:?}, keys {:?}, jump {:?}, dodge {:?}, more {:?}", bar.primary, bar.secondary, bar.skill, bar.jump, bar.dodge, bar.extra);
    *names = crate::ui::settings::SkillNames {
        slots: [bar.at(BarPlace::Primary, 0), bar.at(BarPlace::Secondary, 0), bar.at(BarPlace::Skill, 0), bar.at(BarPlace::Skill, 1), bar.at(BarPlace::Skill, 2)].map(|s| s.map(|n| labels.get(n).cloned().unwrap_or_else(|| n.to_string()))),
        extra: (0..crate::keys::EXTRA as usize).map(|i| bar.at(BarPlace::Extra, i).map(|n| labels.get(n).cloned().unwrap_or_else(|| n.to_string()))).collect(),
        jump: bar.jump.as_ref().map(|n| labels.get(n).cloned().unwrap_or_else(|| n.clone())),
        dodge: bar.dodge.as_ref().map(|n| labels.get(n).cloned().unwrap_or_else(|| n.clone())),
    };
    *roles = Roles { bar, hostile, labels };
}

/// How a skill looks on this client.
#[derive(Clone, Debug, PartialEq)]
pub struct Look {
    /// Clips its move plays (one per press, in turn), their rate, and a pose to hold.
    pub clips: Vec<&'static str>,
    pub rate: f32,
    pub hold: Option<f32>,
    /// Its release draws a slash.
    pub slash: bool,
    /// Its missile is a glowing bolt (else an arrow), with an ember while it winds up.
    pub bolt: bool,
    pub icon: SkillIcon,
}


/// The names each skill's look is made of (its `<name>_ui()` look, or the defaults by aim:
/// `living_rules::ui`), read when the rules compile (`read_roles`). Kept outside the ECS so the
/// draw paths that take a card (`clip_of`, `vfx.rs`, the bar) read it as they read the card.
static LOOK_NAMES: std::sync::RwLock<Option<HashMap<String, living_rules::ui::Look>>> = std::sync::RwLock::new(None);

/// The client's theme table for clip families (docs/INTERFACE.md §4: the client maps a family to
/// its clips, rates and held pose; `BEATS` times them to the windup).
fn clip_family(name: &str) -> (&'static [&'static str], f32, Option<f32>) {
    match name {
        "slash" => (&["sword_slash"], 2.8, None),
        "overhead" => (&["sword_overhead"], 2.8, None),
        "thrust" => (&["sword_thrust"], 2.8, None),
        "shoot" => (&["bow_shoot"], 3.4, None),
        "throw" => (&["attack"], 1.3, None),
        "cast" => (&["cast"], 2.2, None),
        "guard" => (&["block"], 2.2, Some(0.42)),
        // The dash on the rules' track (2.6 m at 5.2 m/s): the clip carries no travel of its own.
        "dash" => (&["dodge"], 1.0, None),
        // Drawn by jump.rs over whatever the body plays (no jump take yet).
        "jump" => (&[crate::jump::CLIP], 1.0, None),
        _ => (&[], 1.0, None),
    }
}

/// The client's theme table for skill icons.
fn icon_named(name: Option<&str>) -> SkillIcon {
    match name {
        Some("sword") => SkillIcon::Sword,
        Some("bow") => SkillIcon::Bow,
        Some("fire") => SkillIcon::Fire,
        Some("shield") => SkillIcon::Shield,
        Some("dodge") => SkillIcon::Dodge,
        Some("heal") => SkillIcon::Heal,
        Some("jump") => SkillIcon::Jump,
        _ => SkillIcon::Empty,
    }
}

/// How a skill looks on this client: its look names through the theme tables. No skill name is
/// matched: a skill the rules add, or restyle, shows by its declaration.
pub fn look(card: &SkillCard) -> Look {
    let names = LOOK_NAMES.read().ok().and_then(|g| g.as_ref().and_then(|m| m.get(&card.skill).cloned()));
    let names = names.unwrap_or_else(|| by_card(card));
    let mut clips: Vec<&'static str> = Vec::new();
    let (mut rate, mut hold) = (1.0, None);
    for (i, f) in names.clips.iter().enumerate() {
        let (c, r, h) = clip_family(f);
        clips.extend_from_slice(c);
        if i == 0 {
            (rate, hold) = (r, h);
        }
    }
    Look { clips, rate, hold, slash: names.effect == Some("slash"), bolt: names.effect == Some("bolt"), icon: icon_named(names.icon) }
}

/// Before the rules compile here: the look by the card's aim, as `living_rules::ui::look_by_aim`
/// gives it.
fn by_card(card: &SkillCard) -> living_rules::ui::Look {
    let l = |icon: &'static str, clip: &'static str, effect: Option<&'static str>| living_rules::ui::Look { icon: Some(icon), clips: vec![clip], effect };
    match card.aim.as_str() {
        "point" if card.radius >= living_rules::ui::BOLT_RADIUS => l("fire", "cast", Some("bolt")),
        "point" => l("bow", "shoot", Some("arrow")),
        "facing" => l("shield", "guard", None),
        "dash" => l("dodge", "dash", None),
        "self_or_ally" => l("heal", "cast", None),
        "creature" => l("sword", "slash", Some("slash")),
        _ => living_rules::ui::Look::default(),
    }
}

/// The skill's items the bar shows as missing, and techniques it shows as unknown.
pub fn needs(card: &SkillCard) -> (impl Iterator<Item = &str>, impl Iterator<Item = &str>) {
    (card.needs.split(',').filter(|s| !s.is_empty()), card.knows.split(',').filter(|s| !s.is_empty()))
}

/// Read the rules' combat skills.
fn read_cards(net: NonSend<Net>, mut cards: ResMut<Cards>) {
    let Some(conn) = net.conn.as_ref() else { return };
    if conn.db.skill_card().count() as usize != cards.all.len() || conn.db.skill_card().iter().zip(&cards.all).any(|(a, b)| a != *b) {
        cards.all = conn.db.skill_card().iter().collect();
    }
}

pub struct CombatPlugin;

impl Plugin for CombatPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Combat>()
            .init_resource::<Cards>()
            .init_resource::<Roles>()
            .init_resource::<Scripted>()
            .add_systems(Update, (read_cards, read_roles, ingest).chain().in_set(Phase::Mirror))
            // After movement: a dash goes the way I move, a skill aims where I look.
            .add_systems(Update, (pick, input).chain().in_set(Phase::Input).after(crate::controls::movement))
            .add_systems(Update, actions.in_set(Phase::Present))
            .add_systems(Update, indicators.in_set(Phase::Camera).after(crate::camera::follow));
    }
}

/// Skill input a headless script asks for (`live.rs` `skill:`, `release:` and `aim:` steps).
/// An aim is `nearest` (the nearest creature), a kind (`wolf`, `person`: the nearest one), or
/// `DX,DY` (metres from me, sim axes); empty is straight ahead.
#[derive(Resource, Default)]
pub struct Scripted {
    pub press: Vec<(String, String)>,
    pub release: Vec<String>,
    /// Show a skill's indicator toward an aim (as if its key were held).
    pub aiming: Option<(String, String)>,
}

/// Resolve a scripted aim to a ground point and a creature.
fn scripted_aim(conn: &DbConnection, scene: &Scene, me_id: u32, me: Vec2, spec: &str, look: Option<Vec2>) -> (Vec2, Option<u32>) {
    if let Some((x, y)) = spec.split_once(',').and_then(|(x, y)| Some((x.trim().parse::<f32>().ok()?, y.trim().parse::<f32>().ok()?))) {
        return (me + Vec2::new(x, y), None);
    }
    let kind = if spec.is_empty() || spec == "nearest" { None } else { Some(spec) };
    let pick = scene
        .shown
        .iter()
        .filter(|(id, _)| **id != me_id && kind.is_none_or(|k| conn.db.seen_characters().id().find(id).is_some_and(|c| c.kind == k)))
        .min_by(|a, b| a.1 .0.distance(me).total_cmp(&b.1 .0.distance(me)))
        .map(|(id, (p, _))| (*p, *id));
    match pick {
        Some((p, id)) if !spec.is_empty() => (p, Some(id)),
        _ => (me + look.unwrap_or(Vec2::Y).normalize_or(Vec2::Y) * 4.0, None),
    }
}

fn now_ms(scene: &Scene) -> f64 {
    scene.now_ms
}

/// New perceived events, numbers and deaths.
pub fn ingest(net: NonSend<Net>, scene: NonSend<Scene>, cards: Res<Cards>, mut c: ResMut<Combat>) {
    let now = now_ms(&scene);
    c.fresh.clear();
    let Some(conn) = net.conn.as_ref() else { return };
    let me = net.my_id;
    let mut rows: Vec<CombatSeen> = conn.db.my_combat().iter().filter(|r| !c.seen_ids.contains(&r.id)).collect();
    rows.sort_by_key(|r| r.id);
    for r in rows {
        c.seen_ids.insert(r.id);
        let ev = Event { row: r.clone(), seen_ms: now };
        let at = Vec2::new(r.x, r.y);
        match r.kind {
            seen::HIT | seen::BLOCKED if r.amount > 0.0 => {
                let kind = if Some(r.target) == me {
                    NumberKind::Taken
                } else if r.kind == seen::BLOCKED {
                    NumberKind::Blocked
                } else {
                    NumberKind::Dealt
                };
                c.numbers.push(Number { at, amount: r.amount, kind, born_ms: now });
            }
            seen::HEALED if r.amount > 0.0 => c.numbers.push(Number { at, amount: r.amount, kind: NumberKind::Healed, born_ms: now }),
            seen::DEATH => {
                c.deaths.insert(r.actor, now);
                // My own death: who killed me; the witnesses arrive beside it.
                if conn.db.my_characters().id().find(&r.actor).is_some() {
                    c.killer = (r.target != 0).then_some(r.target);
                    c.witnesses.clear();
                }
            }
            seen::WITNESS => {
                if !c.witnesses.contains(&r.actor) {
                    c.witnesses.push(r.actor);
                }
            }
            seen::REFUSED => {
                c.refusal = Some((r.note.clone(), now));
                c.refused_skill = cards.by_code(r.skill).map(|k| k.skill.clone());
                if c.predicted.as_ref().is_some_and(|(s, _)| cards.code(s) == r.skill) {
                    c.predicted = None;
                }
            }
            _ => {}
        }
        c.fresh.push(ev.clone());
        c.recent.push(ev);
    }
    c.recent.retain(|e| now - e.seen_ms < 8_000.0);
    c.numbers.retain(|n| now - n.born_ms < 1_400.0);
    c.deaths.retain(|_, t| now - *t < CORPSE_S * 1000.0);
    // Rows the authority dropped are gone from the cache; keep the id set bounded.
    if c.seen_ids.len() > 4096 {
        let live: HashSet<u64> = conn.db.my_combat().iter().map(|r| r.id).collect();
        c.seen_ids.retain(|id| live.contains(id));
    }
}

/// The creature under the cursor (`pick.rs`, the pick the nameplates and Enter use), else, with
/// nobody under it, the nearest to its ground point (within 3.5 m of it, 30 m of me).
pub fn pick(net: NonSend<Net>, scene: NonSend<Scene>, cam: Res<Cam>, target: Res<Target>, town: Res<crate::town::Town>, under: Res<crate::pick::Pick>, mut c: ResMut<Combat>) {
    let (Some(cursor), Some(me_at)) = (cam.cursor_ground, target.0) else {
        c.target = None;
        return;
    };
    let cursor = Vec2::new(cursor.x, cursor.z);
    let me_at = Vec2::new(me_at.x, me_at.z);
    let me = net.my_id;
    if let Some(id) = under.under.filter(|id| scene.shown.get(id).is_some_and(|(p, _)| p.distance(me_at) < 30.0)) {
        c.target = Some(id);
        return;
    }
    c.target = scene
        .shown
        .iter()
        .filter(|(id, (p, _))| Some(**id) != me && p.distance(me_at) < 30.0 && !c.deaths.contains_key(id) && !town.hidden(**id))
        .map(|(id, (p, _))| (*id, p.distance(cursor)))
        .filter(|(_, d)| *d < 3.5)
        .min_by(|a, b| a.1.total_cmp(&b.1))
        .map(|(id, _)| id);
}

/// Whether a skill aimed this way turns the body toward the cursor while it is aimed: at a
/// creature, a point or a guard's facing; not a dash, a heal on oneself or an ally, or none.
pub fn aims_at_cursor(aim: &str) -> bool {
    matches!(aim, "creature" | "point" | "facing")
}

/// Where I aim: the cursor's ground point (sim), else ahead of me.
fn aim_point(cam: &Cam, me: Vec2, input: &Input) -> Vec2 {
    cam.cursor_ground.map(|c| Vec2::new(c.x, c.z)).unwrap_or_else(|| me + input.look.unwrap_or(Vec2::Y).normalize_or(Vec2::Y) * 4.0)
}

#[allow(clippy::too_many_arguments)]
pub fn input(
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    cam: Res<Cam>,
    keys: Res<ButtonInput<KeyCode>>,
    mouse: Res<ButtonInput<MouseButton>>,
    input: Res<Input>,
    target: Res<Target>,
    ui: Res<crate::hud::UiWants>,
    cards: Res<Cards>,
    mut scripted: ResMut<Scripted>,
    (pointer, mut talk, rules): (Res<crate::pointer::Pointer>, Option<ResMut<crate::talk::Talk>>, NonSend<crate::verbs::Rules>),
    mut c: ResMut<Combat>,
    (binds, roles, mut weapon, taps): (Res<crate::keys::Binds>, Res<Roles>, ResMut<crate::weapon::Weapon>, Res<crate::keys::DoubleTap>),
) {
    let now = now_ms(&scene);
    if c.predicted.as_ref().is_some_and(|(_, t)| now - t > PREDICT_MS) {
        c.predicted = None;
    }
    let (Some(conn), Some(me_id), Some(me3)) = (net.conn.as_ref(), net.my_id, target.0) else { return };
    let me = Vec2::new(me3.x, me3.z);
    let typing = input.chat_open || ui.keyboard;
    let free_mouse = !ui.over() && !ui.menu;
    let mut presses: Vec<(String, Option<Vec2>, Option<u32>)> = Vec::new();
    // A script's indicator (headless photographs).
    let mut scripted_aiming = None;
    if let Some((skill, spec)) = scripted.aiming.clone() {
        if let Some(card) = cards.on_bar(&skill) {
            scripted_aiming = Some((card.skill.clone(), scripted_aim(conn, &scene, me_id, me, &spec, input.look)));
        }
    }
    c.script_aim = scripted_aiming.as_ref().map(|(_, (p, _))| *p);
    let mut releases: Vec<String> = Vec::new();
    // The bar's places by binding (`keys.rs`), their skills by how the rules aim them (`Roles`).
    use crate::keys::{Act, Bind};
    let mouse_bound = |a: Act| binds.get(a).iter().any(|b| matches!(b, Bind::Mouse(_)));
    let ok = |a: Act| !mouse_bound(a) || free_mouse;
    if !input.demo {
        // A held guard is let go with its key, also while typing: the key went up either way,
        // and a release missed would leave the guard raised until pressed again.
        for a in BAR_ACTS {
            if let Some(card) = roles.skill(a).and_then(|s| cards.by_name(s)).filter(|card| card.aim == "facing" && binds.went_up(a, &keys, &mouse)) {
                releases.push(card.skill.clone());
            }
        }
    }
    if !input.demo && typing {
        c.aiming = None;
    }
    // Sheathed (`weapon.rs`), a tap on a person talks to them (play-test 2: the owner, tapping to
    // interact, struck the first resident who greeted him). Drawn, a tap strikes whoever is
    // under the cursor.
    let person = |id: u32| conn.db.seen_characters().id().find(&id).is_some_and(|k| k.kind == "person");
    let tap_target = |c: &Combat| {
        let reach = roles.skill(Act::Primary).and_then(|s| cards.by_name(s)).map_or(0.0, |k| k.reach);
        c.target.or_else(|| nearest(&scene, me_id, me, aim_point(&cam, me, &input), reach + 0.4))
    };
    let tap_talks = |c: &Combat| (!weapon.drawn).then(|| tap_target(c)).flatten().filter(|id| person(*id));
    if !input.demo && pointer.tapped && free_mouse {
        // Open: a tap on someone addresses them instead; closed: it opens the box to them.
        let whom = if typing { c.target.filter(|id| person(*id)) } else { tap_talks(&c) };
        if let (Some(id), Some(t)) = (whom, talk.as_mut()) {
            t.open_to = Some(id);
        }
    }
    let tapped_talk = !input.demo && !typing && pointer.tapped && talk.is_some() && tap_talks(&c).is_some();
    if !input.demo && !typing && pointer.tapped {
        let whom = tap_target(&c);
        info!("tap: {} (at {:?}, weapon {})", if tapped_talk { "talk" } else if weapon.drawn { "strike" } else { "draw" }, whom, if weapon.drawn { "drawn" } else { "sheathed" });
    }
    if !input.demo && !typing {
        // Held keys show their skill's indicator.
        c.aiming = [Act::Secondary, Act::Skill1, Act::Primary, Act::Skill3, Act::Skill2].into_iter().chain((0..crate::keys::EXTRA).map(Act::Extra)).find(|a| ok(*a) && binds.down(*a, &keys, &mouse)).and_then(|a| roles.skill(a)).map(String::from);
        // Digits belong to an open list, wheel or grid (1–3 are also the skill keys' twins).
        let digits = [KeyCode::Digit1, KeyCode::Digit2, KeyCode::Digit3, KeyCode::Digit4, KeyCode::Digit5, KeyCode::Digit6, KeyCode::Digit7, KeyCode::Digit8, KeyCode::Digit9];
        let numbered = ui.menu && digits.iter().any(|k| keys.just_pressed(*k));
        for a in BAR_ACTS {
            let down = binds.went_down(a, &keys, &mouse) && ok(a) && !(a == Act::Primary && tapped_talk) && !numbered;
            if let Some(s) = roles.skill(a).filter(|_| down) {
                presses.push((s.to_string(), None, None));
            }
        }
        // The dodge's default: a double tap of a direction key, that way.
        if let (Some(v), Some(s)) = (taps.fired, roles.dodge()) {
            let (up, right) = cam.control_axes();
            let d = (up * v.y + right * v.x).normalize_or_zero();
            presses.push((s.to_string(), Some(me + d * 2.0), None));
        }
    }
    // Sheathed, the first press of an attack skill draws the weapon instead.
    if !weapon.drawn && presses.iter().any(|(s, _, _)| roles.is_hostile(s)) {
        weapon.set(true, crate::weapon::Why::Attack, now, &net);
        presses.retain(|(s, _, _)| !roles.is_hostile(s));
    }
    if let Some((s, _)) = scripted_aiming {
        c.aiming = Some(s);
    } else if input.demo {
        c.aiming = None;
    }
    c.aims = c.guarding || c.aiming.as_ref().and_then(|s| cards.by_name(s)).is_some_and(|k| aims_at_cursor(&k.aim));
    for (skill, spec) in std::mem::take(&mut scripted.press) {
        if let Some(card) = cards.on_bar(&skill) {
            let (aim, tgt) = scripted_aim(conn, &scene, me_id, me, &spec, input.look);
            presses.push((card.skill.clone(), Some(aim), tgt));
        }
    }
    for skill in std::mem::take(&mut scripted.release) {
        if let Some(card) = cards.on_bar(&skill) {
            releases.push(card.skill.clone());
        }
    }
    // A committed move of mine running its course: a press over it is still sent (the authority
    // decides and says why), but nothing of it is predicted (no clip, no guard raised).
    let mine = rules.scripts.as_ref().zip(crate::net::find_fighter(conn, me_id)).and_then(|(sc, f)| my_committed(sc, &cards, &f, now));
    for (skill, aim, tgt) in presses {
        let Some(card) = cards.by_name(&skill) else { continue };
        let given = aim.is_some() && card.aim == "dash";
        let aim = aim.unwrap_or_else(|| aim_point(&cam, me, &input));
        // Who or where it goes, by how the rules aim it.
        let (target_id, point) = match card.aim.as_str() {
            "creature" => (tgt.or(c.target).or_else(|| nearest(&scene, me_id, me, aim, card.reach + 0.4)).unwrap_or(0), aim),
            "self_or_ally" => (tgt.or(c.target.filter(|t| !hostile(conn, *t, me_id))).unwrap_or(0), aim),
            // A dash goes the way I move, else back from where I face (a jump: toward it). Facing
            // where I walk and not aiming, that is the facing drawn, not the cursor.
            "dash" if given => (0, aim),
            "dash" => {
                let drawn = input.face.filter(|_| !input.faces_cursor(c.aims));
                let back = drawn.map_or((me - aim).normalize_or(Vec2::NEG_Y), |f| -f.normalize_or(Vec2::Y));
                let d = if input.dir != Vec2::ZERO { input.dir } else if skill == "jump" { -back } else { back };
                (0, me + d * 2.0)
            }
            _ => (tgt.unwrap_or(0), aim),
        };
        let args = || serde_json::json!({"skill": skill, "target": target_id, "x": point.x, "y": point.y});
        let r = conn.reducers.use_skill_then(skill.clone(), target_id, point.x, point.y, net.on_reply("skill", "use_skill", args));
        net.report("skill", r);
        c.pressed.insert(skill.clone(), now);
        if held(mine.as_ref(), card.aim == "dash") {
            info!("combat: {skill} pressed during my {}: sent, not predicted", mine.as_ref().map_or("", |m| m.0.as_str()));
            continue;
        }
        if look(card).clips.len() > 1 {
            c.strikes = c.strikes.wrapping_add(1);
        }
        if card.aim == "facing" {
            c.guarding = true;
            c.guard_dir = Some((point - me).normalize_or(input.look.unwrap_or(Vec2::Y).normalize_or(Vec2::Y)));
        }
        c.predicted = Some((skill, now));
    }
    for skill in releases {
        let r = conn.reducers.release_skill_then(skill.clone(), net.on_reply("release", "release_skill", || serde_json::json!({"skill": skill})));
        net.report("release", r);
        if cards.by_name(&skill).is_some_and(|card| card.aim == "facing") {
            c.guarding = false;
            c.guard_dir = None;
            if c.predicted.as_ref().is_some_and(|(s, _)| *s == skill) {
                c.predicted = None;
            }
        }
    }
}

/// A committed move of mine under way (committed-moves: the rules' `committed`, docs/COMBAT.md):
/// its skill and whether it is a dash, while it winds up (before its release) or dashes (before
/// its end), from my fighter row. It runs its whole course: movement keys wait (the authority
/// holds them, `combat::resume_move`), and a press starts nothing over it but a dash over a windup.
pub fn my_committed(sc: &living_rules::script::Scripts, cards: &Cards, f: &Fighter, now: f64) -> Option<(String, bool)> {
    let card = cards.by_code(f.act).filter(|_| f.act != 0)?;
    let shape = sc.shapes().get(&card.skill)?;
    let dash = shape.aim == living_rules::combat::Aim::Dash;
    let under_way = if dash { now < f.until_ms as f64 } else { (f.act_ms as f64) <= now && now < f.release_ms as f64 };
    (shape.committed && under_way).then(|| (card.skill.clone(), dash))
}

/// Whether a press would start over `cur` (a committed move under way: its skill, whether a
/// dash): the authority's `held_by`, so the client predicts nothing it will refuse. Only a dash
/// cuts in on a committed windup.
pub fn held(cur: Option<&(String, bool)>, press_dash: bool) -> bool {
    match cur {
        None => false,
        Some((_, cur_dash)) => !(press_dash && !cur_dash),
    }
}

fn nearest(scene: &Scene, me_id: u32, me: Vec2, toward: Vec2, within: f32) -> Option<u32> {
    let ahead = (toward - me).normalize_or(Vec2::Y);
    scene
        .shown
        .iter()
        .filter(|(id, (p, _))| **id != me_id && p.distance(me) <= within && (*p - me).normalize_or(ahead).dot(ahead) > 0.0)
        .min_by(|a, b| a.1 .0.distance(me).total_cmp(&b.1 .0.distance(me)))
        .map(|(id, _)| *id)
}

/// Whether a creature looks hostile to me: its move under way is aimed at me.
pub fn hostile(conn: &DbConnection, id: u32, me: u32) -> bool {
    crate::net::find_fighter(conn, id).is_some_and(|f| f.target == me && f.act != 0)
}

/// How long after a blow its giver still counts as hostile to me (ms).
pub const HURT_HOSTILE_MS: f64 = 15_000.0;

/// Whether a creature is hostile to me as far as my client knows: its move under way is aimed
/// at me, or it hurt me within [`HURT_HOSTILE_MS`] (my `vitals.hurt_by`). The HUD's hostile
/// stance and the tap rule use it.
pub fn hostile_to_me(conn: &DbConnection, id: u32, me: u32, now_ms: f64) -> bool {
    let hurt = conn.db.my_vitals().id().find(&me).is_some_and(|v| v.hurt_by == id && v.hurt_by != 0 && now_ms - (v.hurt_ms as f64) < HURT_HOSTILE_MS);
    hurt || hostile(conn, id, me)
}

/// An animal's move: its own clip by how the rules aim the skill (`skill_card.aim`), never by
/// the skill's name, so a skill the rules give animals shows without a client change. The
/// wolf's bite (wolf.py) snaps at 0.55 s, the rules' 550 ms `attack_duration` for a wolf, so it
/// plays at rate 1 from the move's start; its leap (0.5 s) plays faster, as a dash is short.
pub fn animal_clip(card: &SkillCard) -> Option<(&'static str, f32, Option<f32>)> {
    match card.aim.as_str() {
        "creature" => Some(("bite", 1.0, None)),
        "dash" => Some(("leap", 1.67, None)),
        _ => None,
    }
}

/// A death seen at `t` (display ms), held on its last pose: an animal's (wolf.py) ends lying on
/// its side, a person's on the ground.
pub fn death(animal: bool, t: f64) -> Action {
    if animal {
        Action { clip: "death", rate: 1.0, start_ms: t, hold: Some(0.995), face: None, ..Default::default() }
    } else {
        Action { clip: "death", rate: 1.1, start_ms: t, hold: Some(0.97), face: None, ..Default::default() }
    }
}

/// The clip a move plays, at what rate, and whether it holds a pose.
fn clip_of(card: Option<&SkillCard>, variant: u32, windup_s: Option<f32>) -> Option<Action> {
    let card = card?;
    let l = look(card);
    let clip = *l.clips.get(variant as usize % l.clips.len().max(1))?;
    let windup = windup_s.unwrap_or(card.windup_ms as f32 / 1000.0);
    Some(match timing(clip, windup) {
        Some((rate, from, cut)) if l.hold.is_none() => Action { clip, rate, from, cut: Some(cut), ..Default::default() },
        _ => Action { clip, rate: l.rate, hold: l.hold, ..Default::default() },
    })
}

/// When a one-shot's motion starts, peaks (the blow, the release) and settles, in its clip's
/// seconds: measured on the baked takes with `living/tools/oneshot_beats.py` (both VRoid files
/// alike, 2026-11-11). A clip without beats plays whole at its look's rate.
const BEATS: &[(&str, f32, f32, f32)] = &[
    ("cast", 0.9, 1.483, 1.617),
    ("bow_shoot", 1.267, 1.383, 1.75),
    ("sword_slash", 0.767, 1.15, 1.317),
    ("sword_overhead", 0.267, 0.55, 2.05),
    ("sword_thrust", 0.467, 1.2, 1.55),
];
/// Anticipation before the motion starts, the most and least a clip is sped or slowed, and how
/// long it plays on after it settles (s).
const LEAD_S: f32 = 0.15;
const RATE: (f32, f32) = (0.8, 2.2);
const TAIL_S: f32 = 0.35;

/// How a move's clip is played so that its peak lands at the rules' windup: (rate, where it
/// starts, where it starts fading out), in clip seconds. Play-test 1 found the cast at 2.2× and
/// the bow at 3.4×, peaking up to 0.2 s after the release, and ending mid-motion.
pub fn timing(clip: &str, windup_s: f32) -> Option<(f32, f32, f32)> {
    let &(_, start, peak, settle) = BEATS.iter().find(|b| b.0 == clip)?;
    if windup_s <= 0.05 {
        return None;
    }
    let from = (start - LEAD_S).max(0.0);
    let rate = ((peak - from) / windup_s).clamp(RATE.0, RATE.1);
    let from = (peak - windup_s * rate).max(0.0);
    let cut = settle.min(peak + 0.6) + TAIL_S * rate;
    Some((rate, from, cut))
}

/// What each drawn character plays: its death, its move (mine predicted until confirmed),
/// else a hit reaction.
pub fn actions(net: NonSend<Net>, scene: NonSend<Scene>, input: Res<Input>, cards: Res<Cards>, mut c: ResMut<Combat>) {
    let now = now_ms(&scene);
    let Some(conn) = net.conn.as_ref() else { return };
    let me = net.my_id;
    let mut out: HashMap<u32, Action> = HashMap::new();
    let ids: Vec<u32> = scene.shown.keys().copied().collect();
    for &id in &ids {
        if !c.animals.contains(&id) && conn.db.seen_characters().id().find(&id).is_some_and(|c| c.kind != "person") {
            c.animals.insert(id);
        }
    }
    let Combat { animals, deaths, .. } = &mut *c;
    animals.retain(|id| scene.shown.contains_key(id) || deaths.contains_key(id));
    for (&id, &t) in &c.deaths {
        out.insert(id, death(c.animals.contains(&id), t));
    }
    for id in ids {
        if out.contains_key(&id) {
            continue;
        }
        let f = crate::net::find_fighter(conn, id);
        // Live until its recovery ends, or, cut short (a guard let go, a move broken off: its end
        // comes before its release), until it ended (play-test 1: a guard let go after 1 s stayed
        // drawn for its whole 8 s hold).
        let live = f.as_ref().filter(|f| f.act != 0 && (now as u64) < if f.until_ms < f.release_ms { f.until_ms } else { f.release_ms.max(f.until_ms) } + 120);
        let face = live.and_then(|f| (f.aim_x != 0.0 || f.aim_y != 0.0).then(|| Vec2::new(f.aim_x, f.aim_y)));
        let animal = c.animals.contains(&id);
        if let Some(f) = live {
            let clip = if animal { cards.by_code(f.act).and_then(animal_clip).map(|(c, r, h)| Action { clip: c, rate: r, hold: h, ..Default::default() }) } else { clip_of(cards.by_code(f.act), (f.act_ms / 7) as u32, Some(f.release_ms.saturating_sub(f.act_ms) as f32 / 1000.0)) };
            if let Some(a) = clip {
                // A held guard stays up while the authority holds it.
                out.insert(id, Action { start_ms: f.act_ms as f64, face, ..a });
                if Some(id) == me && c.predicted.as_ref().is_some_and(|(s, t)| cards.code(s) == f.act && (f.act_ms as f64) >= t - 400.0) {
                    c.predicted = None;
                }
                continue;
            }
        }
        if Some(id) == me {
            // A dash's clip is not predicted: the authority moves the body about a round trip
            // after the press, and the clip carries no travel of its own, so it plays with the
            // confirmed move (`live.rs` times one-shots on the display clock).
            if let Some((skill, t)) = c.predicted.clone().filter(|(s, _)| cards.by_name(s).is_none_or(|k| k.aim != "dash")) {
                if let Some(a) = clip_of(cards.by_name(&skill), c.strikes, None) {
                    // Faces the cursor while it waits for the authority, if it is aimed there.
                    let face = input.look.filter(|_| cards.by_name(&skill).is_some_and(|k| aims_at_cursor(&k.aim)));
                    out.insert(id, Action { start_ms: t, face, ..a });
                    continue;
                }
            }
        }
        // A hit reaction for a blow that landed on them just now.
        if let Some(e) = c.recent.iter().rev().find(|e| e.row.target == id && e.row.kind == seen::HIT && now - e.seen_ms < HIT_MS) {
            // An animal's flinch is HIT_MS long at rate 1 (wolf.py); people's hit clip is twice that.
            out.insert(id, Action { clip: "hit", rate: if animal { 1.0 } else { 2.0 }, start_ms: e.seen_ms, hold: None, face: None, ..Default::default() });
        }
    }
    c.actions = out;
}

/// Aim and range indicators, subtle and only while a skill key is held.
#[allow(clippy::too_many_arguments)]
fn indicators(mut g: Gizmos, net: NonSend<Net>, scene: NonSend<Scene>, cam: Res<Cam>, target: Res<Target>, input: Res<Input>, island: Option<Res<crate::island::Island>>, cards: Res<Cards>, c: Res<Combat>) {
    // The held key's skill, else a raised guard's.
    let guard = || c.guarding.then(|| cards.all.iter().find(|card| card.aim == "facing" && card.slot != NOT_ON_BAR)).flatten();
    let (Some(card), Some(me3)) = (c.aiming.as_deref().and_then(|s| cards.by_name(s)).or_else(guard), target.0) else { return };
    let me = Vec2::new(me3.x, me3.z);
    let aim = c.script_aim.unwrap_or_else(|| aim_point(&cam, me, &input));
    let dir = (aim - me).normalize_or(Vec2::Y);
    let ground = |p: Vec2| Vec3::new(p.x, island.as_ref().map_or(me3.y, |i| i.height(p.x, p.y)) + 0.06, p.y);
    let flat = Quat::from_rotation_x(std::f32::consts::FRAC_PI_2);
    let soft = Color::srgba(1.0, 0.97, 0.88, 0.32);
    let warm = Color::srgba(1.0, 0.62, 0.32, 0.45);
    match card.aim.as_str() {
        "point" => {
            let (range, width, col) = (card.reach, card.radius, if look(card).bolt { warm } else { soft });
            let side = Vec2::new(-dir.y, dir.x) * width;
            let steps = 24;
            for k in 0..steps {
                let (a, b) = (k as f32 / steps as f32 * range, (k as f32 + 0.6) / steps as f32 * range);
                for s in [side, -side] {
                    g.line(ground(me + dir * a + s), ground(me + dir * b + s), col);
                }
            }
            g.circle(Isometry3d::new(ground(me + dir * range), flat), width + 0.2, col);
        }
        "creature" => {
            g.circle(Isometry3d::new(ground(me), flat), card.reach, soft);
            if let Some(t) = c.target.and_then(|t| scene.shown.get(&t)) {
                let in_reach = t.0.distance(me) <= card.reach;
                g.circle(Isometry3d::new(ground(t.0), flat), 0.6, if in_reach { soft } else { Color::srgba(1.0, 0.4, 0.4, 0.45) });
            }
        }
        "self_or_ally" => {
            g.circle(Isometry3d::new(ground(me), flat), card.reach, Color::srgba(0.6, 1.0, 0.7, 0.28));
            if let Some(t) = c.target.and_then(|t| scene.shown.get(&t)) {
                g.circle(Isometry3d::new(ground(t.0), flat), 0.7, Color::srgba(0.6, 1.0, 0.7, 0.5));
            }
        }
        "facing" => {
            // The guard's arc in front (the rules' degrees either side), toward where it was
            // raised: the authority's aim on my fighter row once it holds it, else the direction
            // sent. Only an indicator before the press follows the cursor.
            let held = net.my_id.and_then(|me| net.conn.as_ref()?.db.my_fighter().id().find(&me)).filter(|f| f.act == card.code && (f.aim_x != 0.0 || f.aim_y != 0.0)).map(|f| Vec2::new(f.aim_x, f.aim_y).normalize_or(dir));
            let dir = if c.guarding { held.or(c.guard_dir).unwrap_or(dir) } else { dir };
            let a0 = dir.y.atan2(dir.x);
            let half = card.arc.to_radians();
            let n = 16;
            for k in 0..n {
                let (u, v) = (a0 - half + 2.0 * half * k as f32 / n as f32, a0 - half + 2.0 * half * (k + 1) as f32 / n as f32);
                g.line(ground(me + Vec2::new(u.cos(), u.sin()) * 1.2), ground(me + Vec2::new(v.cos(), v.sin()) * 1.2), Color::srgba(0.7, 0.85, 1.0, 0.45));
            }
        }
        _ => {}
    }
}

/// For the HUD: cooldown left and total (s) for a skill, from my readiness row; my press
/// covers the moment before the row arrives.
pub fn cooldown(conn: &DbConnection, me: u32, skill: &str, now_ms: f64) -> Option<(f32, f32)> {
    let r = conn.db.my_readiness().iter().find(|r| r.id == me)?;
    let t = r.ready.iter().find(|t| t.skill == skill)?;
    let left = (t.at_ms as f64 - now_ms) / 1000.0;
    (left > 0.0).then(|| (left as f32, (t.at_ms - t.from_ms) as f32 / 1000.0))
}

#[cfg(test)]
mod committed_tests {
    use super::held;

    #[test]
    fn a_press_over_a_committed_move_is_held_but_a_dash_over_a_windup() {
        let windup = ("strike".to_string(), false);
        let dodge = ("dodge".to_string(), true);
        assert!(!held(None, false) && !held(None, true));
        // Over a committed windup: anything but a dash waits; a dash cuts in.
        assert!(held(Some(&windup), false) && !held(Some(&windup), true));
        // Over a dash: nothing starts, a guard or another dash alike.
        assert!(held(Some(&dodge), false) && held(Some(&dodge), true));
    }
}
