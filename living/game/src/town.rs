//! Town life on the client (docs/TOWN_LIFE.md, "What the client must draw"): presentation and my
//! own gestures only. The authority decides what every resident does; this module
//!
//! - names `doing.code` through `act_card` ([`Acts`]) and picks how each activity looks
//!   ([`look`]): by name for the skills it was drawn for, otherwise from the card's `look`, so a
//!   skill the rules add shows without a client change;
//! - says, for each drawn body ([`Show`]), the loop a standing body plays instead of `idle`
//!   (work, gathering, eating, play, sitting), a gesture played once over it (a wave, a nod,
//!   settling down to sit), where a standing body faces (its activity's spot or the one it is
//!   aimed at), and whether the body is indoors and not drawn (asleep, or resting at its own
//!   door: the house is where it is; an animal has no house and stays drawn, standing);
//! - sends my own gestures through `human_act` ([`WAVE`] waves, [`NOD`] nods, at the person under
//!   or nearest the cursor, else the nearest one ahead), predicting only my clip; [`APPRAISE`]
//!   looks a person or an animal over the same way (the rules' `appraise`: for a while the
//!   authority's projection of them carries their exact health, which the nameplate shows);
//! - notes who answered my greeting (my `experience` rows), so their nameplate shows briefly;
//! - hands the public `weather` row to `weather.rs`, so everyone sees the rain residents
//!   shelter from.
//!
//! Gestures last longer on screen than in the rules (a wave is 1.2 s there, its clip about 2 s
//! here): a gesture plays to its end unless its body moves off or starts something else.

use crate::combat::Action;
use crate::net::Net;
use crate::world::Scene;
use bevy::prelude::*;
use living_bindings::*;
use spacetimedb_sdk::Table;
use std::collections::{HashMap, HashSet};

/// Gesture keys: G waves (greets), B nods, V looks someone over (`appraise`). Clear of WASD, the
/// skill bar (LMB, RMB, Q, E, R, Shift) and F (interact).
pub const WAVE: KeyCode = KeyCode::KeyG;
pub const NOD: KeyCode = KeyCode::KeyB;
pub const APPRAISE: KeyCode = KeyCode::KeyV;
/// How long my predicted gesture waits for the authority's `doing` row (ms).
const PREDICT_MS: f64 = 600.0;
/// How long the nameplate of someone who answered my greeting shows (ms).
pub const ANSWERED_MS: f64 = 3500.0;
/// A standing body turns toward its activity's spot only when it is at least this far (m).
const FACE_MIN_M: f32 = 0.4;
/// Gesture reach for choosing whom I greet (m), as the rules' wave and nod take.
const WAVE_REACH: f32 = 12.0;
const NOD_REACH: f32 = 6.0;
/// Reach for looking someone over (m), as the rules' `appraise_check` takes.
const APPRAISE_REACH: f32 = 6.0;

/// The rules' visible skills (`act_card`), read each frame.
#[derive(Resource, Default)]
pub struct Acts {
    pub all: Vec<ActCard>,
}

impl Acts {
    pub fn by_code(&self, code: u8) -> Option<&ActCard> {
        (code != 0).then(|| self.all.iter().find(|c| c.code == code)).flatten()
    }
}

/// How an activity looks on this client.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Pose {
    /// Nothing over locomotion: a turn or a step aside shows as the body's own motion.
    Motion,
    /// A loop played while standing.
    Loop(&'static str),
    /// A gesture played once: clip, rate, and how long it plays (s).
    Once(&'static str, f32, f32),
    /// Rest: settle down, then sit (raining, or for some, standing at ease).
    Rest,
    /// Not drawn: inside the house.
    Indoors,
}

/// A gesture's clip, rate and seconds on screen (the clips: wave 2.97 s, nod 1.4 s).
const WAVE_LOOK: Pose = Pose::Once("wave", 1.4, 2.1);
const NOD_LOOK: Pose = Pose::Once("nod", 1.0, 1.4);
/// Looking someone over: a glance held for the rules' 1.5 s.
const APPRAISE_LOOK: Pose = Pose::Once("idle_look", 1.0, 1.5);

/// One of my own acts sent through `human_act` from a key: whom it may be aimed at, how far, and
/// the clip predicted at the press.
struct MyAct {
    skill: &'static str,
    key: KeyCode,
    reach: f32,
    /// People only (a greeting), or any creature (looking an animal over too).
    people: bool,
    look: Pose,
}

const MY_ACTS: [MyAct; 3] = [
    MyAct { skill: "wave", key: WAVE, reach: WAVE_REACH, people: true, look: WAVE_LOOK },
    MyAct { skill: "nod", key: NOD, reach: NOD_REACH, people: true, look: NOD_LOOK },
    MyAct { skill: "appraise", key: APPRAISE, reach: APPRAISE_REACH, people: false, look: APPRAISE_LOOK },
];
/// Settling down to sit plays this long (s; `sit_ground_down` is 2.97 s).
const SIT_DOWN_S: f64 = 2.9;

/// How a visible skill looks: the skills drawn for by name, any other by its card's `look`.
pub fn look(card: &ActCard) -> Pose {
    match card.skill.as_str() {
        "wave" => WAVE_LOOK,
        "nod" => NOD_LOOK,
        "appraise" => APPRAISE_LOOK,
        "gather" | "plant" | "take" | "tend" => Pose::Loop("gather"),
        "keep" | "cook" | "craft" | "store" => Pose::Loop("work"),
        "read" => Pose::Loop("idle_look"),
        "eat" => Pose::Loop("eat"),
        // An animal's own (the deer's file has the loop; anything else stands idle).
        "graze" => Pose::Loop("graze"),
        "play" => Pose::Loop("play"),
        "rest" => Pose::Rest,
        "sleep" => Pose::Indoors,
        "face" | "step_aside" => Pose::Motion,
        _ => match card.look.as_str() {
            "gesture" => WAVE_LOOK,
            "work" => Pose::Loop("work"),
            "eat" => Pose::Loop("eat"),
            "play" => Pose::Loop("play"),
            "rest" => Pose::Rest,
            "sleep" => Pose::Indoors,
            // turn, step, and looks this client does not know
            _ => Pose::Motion,
        },
    }
}

/// What a drawn body shows of its activity now.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Show {
    /// The loop a standing body plays instead of idle.
    pub idle: Option<&'static str>,
    /// A one-shot over it: a gesture, settling down to sit.
    pub once: Option<Action>,
    /// Where a standing body faces (sim direction from it).
    pub face: Option<Vec2>,
    /// Inside a house: not drawn.
    pub hidden: bool,
}

/// A gesture on screen, which outlasts its row.
#[derive(Clone, Copy, Debug)]
struct Playing {
    action: Action,
    until_ms: f64,
    /// Where its body stood when it began; moving off ends it.
    at: Vec2,
    /// The authority's row has confirmed it (mine is predicted until then).
    confirmed: bool,
}

#[derive(Resource, Default)]
pub struct Town {
    pub shows: HashMap<u32, Show>,
    gestures: HashMap<u32, Playing>,
    /// The `doing.since_ms` of the last gesture row each body started, so a row plays once.
    started: HashMap<u32, u64>,
    /// My gesture awaiting the authority: (clip look, pressed at display ms, facing).
    predicted: Option<(Pose, f64, Option<Vec2>)>,
    /// Whom I last greeted, at display ms (the camera frames us both for a moment).
    pub greeting: Option<(u32, f64)>,
    /// Who answered my greeting, at display ms.
    pub answered: HashMap<u32, f64>,
    /// Who made a gesture at me (a wave, a nod), at display ms (the camera frames us).
    pub greeted_by: HashMap<u32, f64>,
    seen: HashSet<u64>,
}

impl Town {
    pub fn hidden(&self, id: u32) -> bool {
        self.shows.get(&id).is_some_and(|s| s.hidden)
    }
}

/// Gestures a headless script asks for (`live.rs` `gesture:` steps): the skill and whom
/// (`nearest`, empty, or a character id).
#[derive(Resource, Default)]
pub struct Scripted {
    pub press: Vec<(String, String)>,
}

pub struct TownPlugin;

impl Plugin for TownPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Acts>()
            .init_resource::<Town>()
            .init_resource::<Scripted>()
            // After the bodies are placed and before they are drawn (`live.rs`); combat's pick (who
            // is under the cursor) is from the frame before.
            .add_systems(Update, (read, input, shows).chain().after(crate::controls::target).before(crate::demo::run));
    }
}

/// Read the visible skills, the weather, and answers to my greetings.
fn read(net: NonSend<Net>, scene: NonSend<Scene>, mut acts: ResMut<Acts>, mut weather: ResMut<crate::weather::Weather>, mut town: ResMut<Town>) {
    let Some(conn) = net.conn.as_ref() else {
        weather.authority = None;
        return;
    };
    let cards = conn.db.act_card();
    if cards.count() as usize != acts.all.len() || cards.iter().zip(&acts.all).any(|(a, b)| a != *b) {
        acts.all = cards.iter().collect();
    }
    let w = conn.db.weather().iter().next();
    let now = scene.now_ms;
    weather.authority = w.map(|w| (w.raining, ((now - w.since_ms as f64) / 1000.0).max(0.0) as f32));
    if let Some(me) = net.my_id {
        // "X answers your greeting (nod)." arrives with the resident's `doing` row; the subject is
        // the one who answered.
        // "X greets you (wave)." when someone greets me first.
        let fresh: Vec<Experience> = conn.db.my_experience().iter().filter(|e| e.observer == me && !town.seen.contains(&e.id) && (e.text.contains("answers your greeting") || e.text.contains("greets you"))).collect();
        for e in fresh {
            town.seen.insert(e.id);
            if now - (e.at_ms as f64) < ANSWERED_MS {
                let to = if e.text.contains("greets you") { &mut town.greeted_by } else { &mut town.answered };
                to.insert(e.subject, now);
            }
        }
    }
    town.answered.retain(|_, t| now - *t < ANSWERED_MS);
    town.greeted_by.retain(|_, t| now - *t < ANSWERED_MS);
    town.greeting = town.greeting.filter(|(_, t)| now - *t < ANSWERED_MS);
    if town.seen.len() > 512 {
        let live: HashSet<u64> = conn.db.my_experience().iter().map(|e| e.id).collect();
        town.seen.retain(|id| live.contains(id));
    }
}

/// Whom my act goes to: under or nearest the cursor (combat's pick), else the nearest within
/// reach, ahead of me first; a person, or any creature I perceive when `people` is false.
#[allow(clippy::too_many_arguments)]
fn whom(conn: &DbConnection, scene: &Scene, me_id: u32, me: Vec2, ahead: Vec2, picked: Option<u32>, reach: f32, people: bool, town: &Town) -> Option<u32> {
    let person = |id: &u32| *id != me_id && !town.hidden(*id) && conn.db.seen_characters().id().find(id).is_some_and(|c| !people || c.kind == "person");
    if let Some(id) = picked.filter(person).filter(|id| scene.shown.get(id).is_some_and(|(p, _)| p.distance(me) <= reach)) {
        return Some(id);
    }
    let ahead = ahead.normalize_or(Vec2::Y);
    scene
        .shown
        .iter()
        .filter(|(id, (p, _))| person(id) && p.distance(me) <= reach)
        .map(|(id, (p, _))| (*id, p.distance(me) * if (*p - me).normalize_or(ahead).dot(ahead) > 0.0 { 1.0 } else { 2.0 }))
        .min_by(|a, b| a.1.total_cmp(&b.1))
        .map(|(id, _)| id)
}

/// My gesture and appraise keys (and a script's), through `human_act`.
#[allow(clippy::too_many_arguments)]
fn input(
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    keys: Res<ButtonInput<KeyCode>>,
    controls: Res<crate::controls::Input>,
    ui: Res<crate::hud::UiWants>,
    target: Res<crate::controls::Target>,
    roam: Res<crate::envs::Roam>,
    combat: Res<crate::combat::Combat>,
    mut scripted: ResMut<Scripted>,
    mut town: ResMut<Town>,
) {
    let now = scene.now_ms;
    let (Some(conn), Some(me_id), Some(me3)) = (net.conn.as_ref(), net.my_id, target.0) else { return };
    // Unconfirmed (refused, or lost): my predicted clip stops.
    if town.predicted.is_some_and(|(_, t, _)| now - t > PREDICT_MS) {
        town.predicted = None;
        if town.gestures.get(&me_id).is_some_and(|g| !g.confirmed) {
            town.gestures.remove(&me_id);
        }
    }
    let me = Vec2::new(me3.x, me3.z);
    let mut presses: Vec<(&MyAct, Option<u32>)> = Vec::new();
    if !controls.demo && !controls.chat_open && !ui.keyboard {
        if let Some(a) = MY_ACTS.iter().find(|a| keys.just_pressed(a.key)) {
            presses.push((a, None));
        }
    }
    for (skill, spec) in std::mem::take(&mut scripted.press) {
        match MY_ACTS.iter().find(|a| a.skill == skill) {
            Some(a) => presses.push((a, spec.parse().ok())),
            None => warn!("live script: gesture wants wave, nod or appraise, got {skill}"),
        }
    }
    let ahead = controls.look.unwrap_or(roam.facing);
    for (act, id) in presses {
        let to = id.or_else(|| whom(conn, &scene, me_id, me, ahead, combat.target, act.reach, act.people, &town));
        // With nobody there the rules refuse it; the refusal is logged, nothing plays.
        let node = match to {
            Some(t) => serde_json::json!({"do": act.skill, "target": {"id": t}}),
            None => serde_json::json!({"do": act.skill}),
        };
        let r = conn.reducers.human_act_then(node.to_string(), net.on_reply(act.skill));
        net.report(act.skill, r);
        if let Some(t) = to {
            // I turn to whom I greet or look over (the authority turns my body too; my look
            // would not).
            let face = scene.shown.get(&t).map(|(p, _)| *p - me).filter(|d| d.length_squared() > 1e-4);
            town.predicted = Some((act.look, now, face));
            if act.people {
                town.greeting = Some((t, now));
            }
        }
    }
}

fn once(pose: Pose, start_ms: f64, face: Option<Vec2>) -> Option<(Action, f64)> {
    match pose {
        Pose::Once(clip, rate, secs) => Some((Action { clip, rate, start_ms, hold: None, face }, start_ms + secs as f64 * 1000.0)),
        _ => None,
    }
}

/// What each drawn body shows of its activity.
pub fn shows(net: NonSend<Net>, scene: NonSend<Scene>, acts: Res<Acts>, weather: Res<crate::weather::Weather>, mut town: ResMut<Town>) {
    let now = scene.now_ms;
    let Some(conn) = net.conn.as_ref() else {
        town.shows.clear();
        return;
    };
    let raining = weather.authority.is_some_and(|(r, _)| r);
    let me = net.my_id;
    let mut out: HashMap<u32, Show> = HashMap::with_capacity(scene.shown.len());
    let ids: Vec<(u32, Vec2)> = scene.shown.iter().map(|(id, (p, _))| (*id, *p)).collect();
    for (id, p) in ids {
        let mut show = Show::default();
        let row = conn.db.seen_doing().id().find(&id);
        let card = row.as_ref().and_then(|d| acts.by_code(d.code));
        // Animals have no house: asleep or resting they stay where they are, drawn.
        let animal = conn.db.seen_characters().id().find(&id).is_some_and(|c| c.kind != "person");
        let card = card.filter(|c| !(animal && matches!(look(c), Pose::Rest | Pose::Indoors)));
        // Where its target is now: the one it is aimed at (as drawn), else the row's spot.
        let spot = row.as_ref().map(|d| scene.shown.get(&d.target).filter(|_| d.target != 0).map_or(Vec2::new(d.x, d.y), |s| s.0));
        let toward = spot.map(|s| s - p).filter(|d| d.length() >= FACE_MIN_M);
        match (row.as_ref(), card.map(look)) {
            (Some(d), Some(pose @ Pose::Once(..))) if town.started.get(&id) != Some(&d.since_ms) => {
                town.started.insert(id, d.since_ms);
                let predicted = Some(id) == me && town.predicted.is_some_and(|(_, t, _)| (d.since_ms as f64) >= t - 400.0);
                match town.gestures.get_mut(&id).filter(|_| predicted) {
                    // Mine was predicted at the press: the authority confirms it; no replay.
                    Some(g) => {
                        g.confirmed = true;
                        g.until_ms = g.until_ms.max(d.until_ms as f64);
                        town.predicted = None;
                    }
                    None => {
                        // A gesture that faces its target has had the authority turn the body already
                        // (its segment's turn); the rest face their spot here.
                        let face = toward.filter(|_| !card.is_some_and(|c| c.faces));
                        if let Some((action, until)) = once(pose, d.since_ms as f64, face) {
                            town.gestures.insert(id, Playing { action, until_ms: until.max(d.until_ms as f64), at: p, confirmed: true });
                        }
                    }
                }
            }
            (Some(_), Some(Pose::Loop(clip))) => {
                show.idle = Some(clip);
                show.face = toward.filter(|_| clip != "play");
            }
            (Some(d), Some(Pose::Rest)) => {
                // A rest taken at home is indoors (the authority says so on the `doing` row).
                if d.indoors {
                    show.hidden = true;
                } else if raining || crate::world::hash(id, 0x5e47) < 0.3 {
                    // Under the eaves, or standing at ease with the others.
                    show.idle = Some(if raining { "idle_look" } else { "listen" });
                } else if now - (d.since_ms as f64) < SIT_DOWN_S * 1000.0 {
                    show.once = Some(Action { clip: "sit_ground_down", rate: 1.0, start_ms: d.since_ms as f64, hold: Some(0.99), face: None });
                    show.idle = Some("sit_ground");
                } else {
                    show.idle = Some("sit_ground");
                }
            }
            (Some(_), Some(Pose::Indoors)) => show.hidden = true,
            _ => {}
        }
        if Some(id) == me {
            if let Some((pose, t, face)) = town.predicted {
                if town.gestures.get(&id).is_none_or(|g| g.action.start_ms < t) {
                    if let Some((action, until)) = once(pose, t, face) {
                        town.gestures.insert(id, Playing { action, until_ms: until, at: p, confirmed: false });
                    }
                }
            }
        }
        // A gesture plays to its end, unless its body moves off or starts another activity.
        if let Some(g) = town.gestures.get(&id).copied() {
            let other = show.idle.is_some() || show.hidden;
            if now > g.until_ms || g.at.distance(p) > 0.5 || other {
                town.gestures.remove(&id);
            } else {
                show.once = Some(g.action);
                show.face = g.action.face.or(show.face);
            }
        }
        if show != Show::default() {
            out.insert(id, show);
        }
    }
    town.gestures.retain(|id, _| scene.shown.contains_key(id));
    town.started.retain(|id, _| scene.shown.contains_key(id));
    town.shows = out;
}

#[cfg(test)]
mod tests {
    use super::*;

    fn card(skill: &str, look: &str) -> ActCard {
        ActCard { skill: skill.into(), code: 1, look: look.into(), faces: false, aside: false }
    }

    #[test]
    fn skills_drawn_for_look_as_drawn() {
        assert_eq!(look(&card("keep", "work")), Pose::Loop("work"));
        assert_eq!(look(&card("gather", "work")), Pose::Loop("gather"));
        assert_eq!(look(&card("wave", "gesture")), WAVE_LOOK);
        assert_eq!(look(&card("nod", "gesture")), NOD_LOOK);
        assert_eq!(look(&card("sleep", "sleep")), Pose::Indoors);
        assert_eq!(look(&card("face", "turn")), Pose::Motion);
    }

    #[test]
    fn a_skill_the_client_never_saw_looks_like_its_card() {
        assert_eq!(look(&card("mend_nets", "work")), Pose::Loop("work"));
        assert_eq!(look(&card("bow", "gesture")), WAVE_LOOK);
        assert_eq!(look(&card("nap", "sleep")), Pose::Indoors);
        assert_eq!(look(&card("lounge", "rest")), Pose::Rest);
        assert_eq!(look(&card("sidestep", "step")), Pose::Motion);
        assert_eq!(look(&card("dance", "a look from a later script")), Pose::Motion);
    }

    #[test]
    fn unknown_codes_name_nothing() {
        let acts = Acts { all: vec![ActCard { code: 3, ..card("eat", "eat") }] };
        assert!(acts.by_code(0).is_none());
        assert!(acts.by_code(9).is_none());
        assert_eq!(acts.by_code(3).map(|c| c.skill.as_str()), Some("eat"));
    }
}
