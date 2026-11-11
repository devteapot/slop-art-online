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
    /// The last refusal (why, display ms).
    pub refusal: Option<(String, f64)>,
    /// Which skill key is held (indicators), and since when.
    pub aiming: Option<String>,
    pub guarding: bool,
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

/// How a skill looks on this client.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Look {
    /// Clips its move plays (one per press, in turn), their rate, and a pose to hold.
    pub clips: &'static [&'static str],
    pub rate: f32,
    pub hold: Option<f32>,
    /// Its release draws a slash.
    pub slash: bool,
    /// Its missile is a glowing bolt (else an arrow), with an ember while it winds up.
    pub bolt: bool,
    pub icon: SkillIcon,
}

/// A missile at least this wide is drawn as a bolt.
const BOLT_RADIUS: f32 = 0.25;

/// How a skill looks: the skills drawn for by name, any other from how the rules aim it.
pub fn look(card: &SkillCard) -> Look {
    let l = |clips: &'static [&'static str], rate: f32, hold: Option<f32>, icon: SkillIcon| Look { clips, rate, hold, slash: false, bolt: false, icon };
    match card.skill.as_str() {
        "strike" => Look { slash: true, ..l(&["sword_slash", "sword_overhead", "sword_thrust"], 2.8, None, SkillIcon::Sword) },
        "attack" => Look { slash: true, ..l(&["sword_slash"], 2.0, None, SkillIcon::Sword) },
        "bowshot" | "shoot" => l(&["bow_shoot"], 3.4, None, SkillIcon::Bow),
        "throw" => l(&["attack"], 1.3, None, SkillIcon::Sword),
        "firebolt" => Look { bolt: true, ..l(&["cast"], 2.2, None, SkillIcon::Fire) },
        "heal" => l(&["cast"], 2.6, None, SkillIcon::Heal),
        "block" => l(&["block"], 2.2, Some(0.42), SkillIcon::Shield),
        // The dash on the rules' track (2.6 m at 5.2 m/s): the clip carries no travel of its own.
        "dodge" => l(&["dodge"], 1.0, None, SkillIcon::Dodge),
        // Drawn by jump.rs over whatever the body plays (no jump take yet).
        "jump" => l(&[crate::jump::CLIP], 1.0, None, SkillIcon::Dodge),
        _ => match card.aim.as_str() {
            "point" if card.radius >= BOLT_RADIUS => Look { bolt: true, ..l(&["cast"], 2.2, None, SkillIcon::Fire) },
            "point" => l(&["bow_shoot"], 3.4, None, SkillIcon::Bow),
            "facing" => l(&["block"], 2.2, Some(0.42), SkillIcon::Shield),
            "dash" => l(&["dodge"], 1.0, None, SkillIcon::Dodge),
            "self_or_ally" => l(&["cast"], 2.6, None, SkillIcon::Heal),
            "creature" => Look { slash: true, ..l(&["sword_slash"], 2.0, None, SkillIcon::Sword) },
            _ => l(&[], 1.0, None, SkillIcon::Empty),
        },
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
            .init_resource::<Scripted>()
            .add_systems(Update, (read_cards, ingest).chain().in_set(Phase::Mirror))
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

/// The creature under or nearest the cursor (within 3.5 m of it, 30 m of me).
pub fn pick(net: NonSend<Net>, scene: NonSend<Scene>, cam: Res<Cam>, target: Res<Target>, town: Res<crate::town::Town>, mut c: ResMut<Combat>) {
    let (Some(cursor), Some(me_at)) = (cam.cursor_ground, target.0) else {
        c.target = None;
        return;
    };
    let cursor = Vec2::new(cursor.x, cursor.z);
    let me_at = Vec2::new(me_at.x, me_at.z);
    let me = net.my_id;
    c.target = scene
        .shown
        .iter()
        .filter(|(id, (p, _))| Some(**id) != me && p.distance(me_at) < 30.0 && !c.deaths.contains_key(id) && !town.hidden(**id))
        .map(|(id, (p, _))| (*id, p.distance(cursor)))
        .filter(|(_, d)| *d < 3.5)
        .min_by(|a, b| a.1.total_cmp(&b.1))
        .map(|(id, _)| id);
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
    mut c: ResMut<Combat>,
) {
    let now = now_ms(&scene);
    if c.predicted.as_ref().is_some_and(|(_, t)| now - t > PREDICT_MS) {
        c.predicted = None;
    }
    let (Some(conn), Some(me_id), Some(me3)) = (net.conn.as_ref(), net.my_id, target.0) else { return };
    let me = Vec2::new(me3.x, me3.z);
    let typing = input.chat_open || ui.keyboard;
    let free_mouse = !ui.pointer && !ui.menu;
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
    // The bar's skills by slot (the rules' `skill_bar()`).
    let slot = |i: usize| cards.slot(i).map(|card| card.skill.clone());
    let shift = |b: &ButtonInput<KeyCode>, f: fn(&ButtonInput<KeyCode>, KeyCode) -> bool| f(b, KeyCode::ShiftLeft) || f(b, KeyCode::ShiftRight);
    if !input.demo {
        // A held guard is let go with its key, also while typing: the key went up either way,
        // and a release missed would leave the guard raised until pressed again.
        let went_up = [
            mouse.just_released(MouseButton::Left),
            mouse.just_released(MouseButton::Right),
            keys.just_released(KeyCode::KeyQ),
            keys.just_released(KeyCode::KeyE),
            keys.just_released(KeyCode::KeyR),
            shift(&keys, |b, k| b.just_released(k)),
        ];
        for (i, up) in went_up.into_iter().enumerate() {
            if let Some(card) = cards.slot(i).filter(|card| up && card.aim == "facing") {
                releases.push(card.skill.clone());
            }
        }
    }
    if !input.demo && typing {
        c.aiming = None;
    }
    if !input.demo && !typing {
        let held = |k| keys.pressed(k);
        // Held keys show their skill's indicator: RMB, Q, LMB, R, E.
        c.aiming = if mouse.pressed(MouseButton::Right) && free_mouse {
            slot(1)
        } else if held(KeyCode::KeyQ) {
            slot(2)
        } else if mouse.pressed(MouseButton::Left) && free_mouse {
            slot(0)
        } else if held(KeyCode::KeyR) {
            slot(4)
        } else if held(KeyCode::KeyE) {
            slot(3)
        } else {
            None
        };
        let went_down = [
            mouse.just_pressed(MouseButton::Left) && free_mouse,
            mouse.just_pressed(MouseButton::Right) && free_mouse,
            keys.just_pressed(KeyCode::KeyQ),
            keys.just_pressed(KeyCode::KeyE),
            keys.just_pressed(KeyCode::KeyR),
            shift(&keys, |b, k| b.just_pressed(k)),
            keys.just_pressed(KeyCode::Space),
        ];
        // In bar order, as before: LMB, RMB, Q, then R before E, then Shift, then Space (the
        // jump, not drawn on the bar).
        for i in [0, 1, 2, 4, 3, 5, 6] {
            if went_down[i] {
                if let Some(s) = slot(i) {
                    presses.push((s, None, None));
                }
            }
        }
    }
    if let Some((s, _)) = scripted_aiming {
        c.aiming = Some(s);
    } else if input.demo {
        c.aiming = None;
    }
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
    for (skill, aim, tgt) in presses {
        let Some(card) = cards.by_name(&skill) else { continue };
        let aim = aim.unwrap_or_else(|| aim_point(&cam, me, &input));
        // Who or where it goes, by how the rules aim it.
        let (target_id, point) = match card.aim.as_str() {
            "creature" => (tgt.or(c.target).or_else(|| nearest(&scene, me_id, me, aim, card.reach + 0.4)).unwrap_or(0), aim),
            "self_or_ally" => (tgt.or(c.target.filter(|t| !hostile(conn, *t, me_id))).unwrap_or(0), aim),
            // A dash goes the way I move, else back from where I face (a jump: toward it).
            "dash" => {
                let back = (me - aim).normalize_or(Vec2::NEG_Y);
                let d = if input.dir != Vec2::ZERO { input.dir } else if skill == "jump" { -back } else { back };
                (0, me + d * 2.0)
            }
            _ => (tgt.unwrap_or(0), aim),
        };
        let r = conn.reducers.use_skill_then(skill.clone(), target_id, point.x, point.y, net.on_reply("skill"));
        net.report("skill", r);
        c.pressed.insert(skill.clone(), now);
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
        let r = conn.reducers.release_skill_then(skill.clone(), net.on_reply("release"));
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
    conn.db.seen_fighters().id().find(&id).is_some_and(|f| f.target == me && f.act != 0)
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
        Action { clip: "death", rate: 1.0, start_ms: t, hold: Some(0.995), face: None }
    } else {
        Action { clip: "death", rate: 1.1, start_ms: t, hold: Some(0.97), face: None }
    }
}

/// The clip a move plays, at what rate, and whether it holds a pose.
fn clip_of(card: Option<&SkillCard>, variant: u32) -> Option<(&'static str, f32, Option<f32>)> {
    let l = look(card?);
    let clip = l.clips.get(variant as usize % l.clips.len().max(1))?;
    Some((clip, l.rate, l.hold))
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
        let f = conn.db.seen_fighters().id().find(&id);
        let live = f.as_ref().filter(|f| f.act != 0 && (now as u64) < f.until_ms.max(f.release_ms) + 120);
        let face = live.and_then(|f| (f.aim_x != 0.0 || f.aim_y != 0.0).then(|| Vec2::new(f.aim_x, f.aim_y)));
        let animal = c.animals.contains(&id);
        if let Some(f) = live {
            let clip = if animal { cards.by_code(f.act).and_then(animal_clip) } else { clip_of(cards.by_code(f.act), (f.act_ms / 7) as u32) };
            if let Some((clip, rate, hold)) = clip {
                // A held guard stays up while the authority holds it.
                out.insert(id, Action { clip, rate, start_ms: f.act_ms as f64, hold, face });
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
                if let Some((clip, rate, hold)) = clip_of(cards.by_name(&skill), c.strikes) {
                    out.insert(id, Action { clip, rate, start_ms: t, hold, face: input.look });
                    continue;
                }
            }
        }
        // A hit reaction for a blow that landed on them just now.
        if let Some(e) = c.recent.iter().rev().find(|e| e.row.target == id && e.row.kind == seen::HIT && now - e.seen_ms < HIT_MS) {
            // An animal's flinch is HIT_MS long at rate 1 (wolf.py); people's hit clip is twice that.
            out.insert(id, Action { clip: "hit", rate: if animal { 1.0 } else { 2.0 }, start_ms: e.seen_ms, hold: None, face: None });
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
            let held = net.my_id.and_then(|me| net.conn.as_ref()?.db.seen_fighters().id().find(&me)).filter(|f| f.act == card.code && (f.aim_x != 0.0 || f.aim_y != 0.0)).map(|f| Vec2::new(f.aim_x, f.aim_y).normalize_or(dir));
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
