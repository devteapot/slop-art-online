//! Combat on the client (docs/COMBAT.md): presentation and input only. The authority decides
//! every move, hit and death; this module
//!
//! - reads what my character perceived (`my_combat`, transient rows the authority writes only
//!   for what my character could see) and what others look like in a fight (`fighter`, through
//!   the body window), and my own timing (`my_readiness`);
//! - maps the skill bar's keys to `use_skill` / `release_skill`, aiming skillshots at the
//!   cursor's ground point and targeted skills at the creature under or nearest the cursor;
//! - picks the clip each drawn character plays for its move, a hit or its death;
//! - predicts only my own move's clip at the moment I press (the authority's answer arrives a
//!   round trip later): the prediction ends when the authority's `fighter` row confirms it,
//!   when a `REFUSED` arrives, or after [`PREDICT_MS`] without either. Movement is never
//!   predicted: the dodge's dash is the authority's.
//! - draws the aim and range indicators while a skill key is held.

use crate::camera::Cam;
use crate::controls::{Input, Target};
use crate::net::Net;
use crate::world::Scene;
use bevy::prelude::*;
use living_bindings::*;
use living_rules::combat::{self as rules, seen};
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
    predicted: Option<(&'static str, f64)>,
    /// When I last pressed each skill (display ms), for the HUD until readiness arrives.
    pub pressed: HashMap<&'static str, f64>,
    /// The last refusal (why, display ms).
    pub refusal: Option<(String, f64)>,
    /// Which skill key is held (indicators), and since when.
    pub aiming: Option<&'static str>,
    pub guarding: bool,
    /// Count of presses (alternating strike clips).
    strikes: u32,
    /// Where a script aims an indicator (instead of the cursor).
    script_aim: Option<Vec2>,
}

pub struct CombatPlugin;

impl Plugin for CombatPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Combat>()
            .init_resource::<Scripted>()
            .add_systems(Update, (ingest, pick, input, actions).chain().after(crate::controls::movement).before(crate::camera::follow))
            .add_systems(Update, indicators.after(crate::camera::follow));
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
        .filter(|(id, _)| **id != me_id && kind.is_none_or(|k| conn.db.body().id().find(id).is_some_and(|b| b.kind == k)))
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
pub fn ingest(net: NonSend<Net>, scene: NonSend<Scene>, mut c: ResMut<Combat>) {
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
                if conn.db.character().id().find(&r.actor).is_some_and(|ch| ch.controller == net.me.unwrap_or_default()) {
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
                if c.predicted.is_some_and(|(s, _)| rules::code(s) == r.skill) {
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
pub fn pick(net: NonSend<Net>, scene: NonSend<Scene>, cam: Res<Cam>, target: Res<Target>, mut c: ResMut<Combat>) {
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
        .filter(|(id, (p, _))| Some(**id) != me && p.distance(me_at) < 30.0 && !c.deaths.contains_key(id))
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
    mut scripted: ResMut<Scripted>,
    mut c: ResMut<Combat>,
) {
    let now = now_ms(&scene);
    if c.predicted.is_some_and(|(_, t)| now - t > PREDICT_MS) {
        c.predicted = None;
    }
    let (Some(conn), Some(me_id), Some(me3)) = (net.conn.as_ref(), net.my_id, target.0) else { return };
    let me = Vec2::new(me3.x, me3.z);
    let typing = input.chat_open || ui.keyboard;
    let free_mouse = !ui.pointer;
    let mut presses: Vec<(&'static str, Option<Vec2>, Option<u32>)> = Vec::new();
    // A script's indicator (headless photographs).
    let mut scripted_aiming = None;
    if let Some((skill, spec)) = scripted.aiming.clone() {
        if let Some(s) = rules::STARTER.iter().find(|s| **s == skill) {
            scripted_aiming = Some((*s, scripted_aim(conn, &scene, me_id, me, &spec, input.look)));
        }
    }
    c.script_aim = scripted_aiming.map(|(_, (p, _))| p);
    let mut releases: Vec<&'static str> = Vec::new();
    if !input.demo && !typing {
        let held = |k| keys.pressed(k);
        c.aiming = if mouse.pressed(MouseButton::Right) && free_mouse {
            Some("bowshot")
        } else if held(KeyCode::KeyQ) {
            Some("firebolt")
        } else if mouse.pressed(MouseButton::Left) && free_mouse {
            Some("strike")
        } else if held(KeyCode::KeyR) {
            Some("heal")
        } else if held(KeyCode::KeyE) {
            Some("block")
        } else {
            None
        };
        if mouse.just_pressed(MouseButton::Left) && free_mouse {
            presses.push(("strike", None, None));
        }
        if mouse.just_pressed(MouseButton::Right) && free_mouse {
            presses.push(("bowshot", None, None));
        }
        if keys.just_pressed(KeyCode::KeyQ) {
            presses.push(("firebolt", None, None));
        }
        if keys.just_pressed(KeyCode::KeyR) {
            presses.push(("heal", None, None));
        }
        if keys.just_pressed(KeyCode::KeyE) {
            presses.push(("block", None, None));
        }
        if keys.just_released(KeyCode::KeyE) {
            releases.push("block");
        }
        if keys.just_pressed(KeyCode::ShiftLeft) || keys.just_pressed(KeyCode::ShiftRight) {
            presses.push(("dodge", None, None));
        }
    }
    if let Some((s, _)) = scripted_aiming {
        c.aiming = Some(s);
    } else if input.demo {
        c.aiming = None;
    }
    for (skill, spec) in std::mem::take(&mut scripted.press) {
        if let Some(s) = rules::STARTER.iter().find(|s| **s == skill) {
            let (aim, tgt) = scripted_aim(conn, &scene, me_id, me, &spec, input.look);
            presses.push((s, Some(aim), tgt));
        }
    }
    for skill in std::mem::take(&mut scripted.release) {
        if let Some(s) = rules::STARTER.iter().find(|s| **s == skill) {
            releases.push(s);
        }
    }
    for (skill, aim, tgt) in presses {
        let aim = aim.unwrap_or_else(|| aim_point(&cam, me, &input));
        let (target_id, point) = match skill {
            "strike" => (tgt.or(c.target).or_else(|| nearest(&scene, me_id, me, aim, 2.6)).unwrap_or(0), aim),
            "heal" => (tgt.or(c.target.filter(|t| !hostile(conn, *t, me_id))).unwrap_or(0), aim),
            // A dodge goes the way I move, else back from where I face.
            "dodge" => {
                let d = if input.dir != Vec2::ZERO { input.dir } else { (me - aim).normalize_or(Vec2::NEG_Y) };
                (0, me + d * 2.0)
            }
            _ => (tgt.unwrap_or(0), aim),
        };
        let r = conn.reducers.use_skill_then(skill.to_string(), target_id, point.x, point.y, net.on_reply("skill"));
        net.report("skill", r);
        c.pressed.insert(skill, now);
        if skill == "strike" {
            c.strikes = c.strikes.wrapping_add(1);
        }
        if skill == "block" {
            c.guarding = true;
        }
        c.predicted = Some((skill, now));
    }
    for skill in releases {
        let r = conn.reducers.release_skill_then(skill.to_string(), net.on_reply("release"));
        net.report("release", r);
        if skill == "block" {
            c.guarding = false;
            if c.predicted.is_some_and(|(s, _)| s == "block") {
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
    conn.db.fighter().id().find(&id).is_some_and(|f| f.target == me && f.act != 0)
}

/// The clip a move plays, at what rate, and whether it holds a pose.
fn clip_of(code: u8, variant: u32) -> Option<(&'static str, f32, Option<f32>)> {
    Some(match rules::name(code) {
        "strike" => (["sword_slash", "sword_overhead", "sword_thrust"][(variant % 3) as usize], 2.8, None),
        "attack" => ("sword_slash", 2.0, None),
        "bowshot" | "shoot" => ("bow_shoot", 3.4, None),
        "throw" => ("attack", 1.3, None),
        "firebolt" => ("cast", 2.2, None),
        "heal" => ("cast", 2.6, None),
        "block" => ("block", 2.2, Some(0.42)),
        "dodge" => ("dodge_roll", 3.3, None),
        _ => return None,
    })
}

/// What each drawn character plays: its death, its move (mine predicted until confirmed),
/// else a hit reaction.
pub fn actions(net: NonSend<Net>, scene: NonSend<Scene>, input: Res<Input>, mut c: ResMut<Combat>) {
    let now = now_ms(&scene);
    let Some(conn) = net.conn.as_ref() else { return };
    let me = net.my_id;
    let mut out: HashMap<u32, Action> = HashMap::new();
    for (&id, &t) in &c.deaths {
        out.insert(id, Action { clip: "death", rate: 1.1, start_ms: t, hold: Some(0.97), face: None });
    }
    let ids: Vec<u32> = scene.shown.keys().copied().collect();
    for id in ids {
        if out.contains_key(&id) {
            continue;
        }
        let f = conn.db.fighter().id().find(&id);
        let live = f.as_ref().filter(|f| f.act != 0 && (now as u64) < f.until_ms.max(f.release_ms) + 120);
        let face = live.and_then(|f| (f.aim_x != 0.0 || f.aim_y != 0.0).then(|| Vec2::new(f.aim_x, f.aim_y)));
        if let Some(f) = live {
            if let Some((clip, rate, hold)) = clip_of(f.act, (f.act_ms / 7) as u32) {
                // A held guard stays up while the authority holds it.
                out.insert(id, Action { clip, rate, start_ms: f.act_ms as f64, hold, face });
                if Some(id) == me && c.predicted.is_some_and(|(s, t)| rules::code(s) == f.act && (f.act_ms as f64) >= t - 400.0) {
                    c.predicted = None;
                }
                continue;
            }
        }
        if Some(id) == me {
            if let Some((skill, t)) = c.predicted {
                if let Some((clip, rate, hold)) = clip_of(rules::code(skill), c.strikes) {
                    out.insert(id, Action { clip, rate, start_ms: t, hold, face: input.look });
                    continue;
                }
            }
        }
        // A hit reaction for a blow that landed on them just now.
        if let Some(e) = c.recent.iter().rev().find(|e| e.row.target == id && e.row.kind == seen::HIT && now - e.seen_ms < HIT_MS) {
            out.insert(id, Action { clip: "hit", rate: 2.0, start_ms: e.seen_ms, hold: None, face: None });
        }
    }
    c.actions = out;
}

/// Aim and range indicators, subtle and only while a skill key is held.
fn indicators(mut g: Gizmos, net: NonSend<Net>, scene: NonSend<Scene>, cam: Res<Cam>, target: Res<Target>, input: Res<Input>, island: Option<Res<crate::island::Island>>, c: Res<Combat>) {
    let (Some(skill), Some(me3)) = (c.aiming.or(c.guarding.then_some("block")), target.0) else { return };
    let me = Vec2::new(me3.x, me3.z);
    let aim = c.script_aim.unwrap_or_else(|| aim_point(&cam, me, &input));
    let dir = (aim - me).normalize_or(Vec2::Y);
    let ground = |p: Vec2| Vec3::new(p.x, island.as_ref().map_or(me3.y, |i| i.height(p.x, p.y)) + 0.06, p.y);
    let flat = Quat::from_rotation_x(std::f32::consts::FRAC_PI_2);
    let soft = Color::srgba(1.0, 0.97, 0.88, 0.32);
    let warm = Color::srgba(1.0, 0.62, 0.32, 0.45);
    let _ = &net;
    match skill {
        "bowshot" | "firebolt" => {
            let (range, width, col) = if skill == "bowshot" { (22.0, 0.15, soft) } else { (16.0, 0.35, warm) };
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
        "strike" => {
            g.circle(Isometry3d::new(ground(me), flat), 1.6 + 0.6, soft);
            if let Some(t) = c.target.and_then(|t| scene.shown.get(&t)) {
                let in_reach = t.0.distance(me) <= 2.2;
                g.circle(Isometry3d::new(ground(t.0), flat), 0.6, if in_reach { soft } else { Color::srgba(1.0, 0.4, 0.4, 0.45) });
            }
        }
        "heal" => {
            g.circle(Isometry3d::new(ground(me), flat), 8.0, Color::srgba(0.6, 1.0, 0.7, 0.28));
            if let Some(t) = c.target.and_then(|t| scene.shown.get(&t)) {
                g.circle(Isometry3d::new(ground(t.0), flat), 0.7, Color::srgba(0.6, 1.0, 0.7, 0.5));
            }
        }
        "block" => {
            // The guard's arc in front (75° either side).
            let a0 = dir.y.atan2(dir.x);
            let n = 16;
            for k in 0..n {
                let (u, v) = (a0 - 1.31 + 2.62 * k as f32 / n as f32, a0 - 1.31 + 2.62 * (k + 1) as f32 / n as f32);
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
