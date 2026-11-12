//! Whom the text box speaks to (play-test 2: every chat line went to no one; the owner's rule,
//! 2026-11-11: "if your cursor is not on someone and you press enter, you go into general chat.
//! If you are hovering someone and press enter, you enter chat with that person specifically.
//! But that conversation should still be kind of public, unless you whisper").
//!
//! - **Enter, nobody under the cursor:** to the room (`to = 0`); the box is in Log and people.
//! - **Enter while hovering someone:** to them (`to = id`); their window opens with the box. The
//!   line is still heard by everyone in earshot (the rules' `perceive::speak`).
//! - **Tab** goes to the next person within earshot (nearest first), then back to the room.
//! - A tap on a peaceful person, F on them, or a click in their window's box addresses them.
//! - **The box says whom:** "To the room", "To a child in red" (labels by looks, `looks.rs`).
//! - **Modes come from a table** ([`MODES`]): today the room and a person. Whispering (close, or
//!   through skills) and skill channels are the Spark coordinator's `docs/COMMUNICATION.md`;
//!   the table keeps a place for whisper, shown greyed, with no rules behind it yet.
//! - **Earshot is the rules'.** The world's `senses(a)` law (`hearing`), asked per person
//!   perceived (their kind and stage; night and dark from the displayed clock).
//! - **When the room does not answer, the client says so.** Minds give no turn to a line to the
//!   room yet (until the Spark's greeting experiments are on). About 10 s after a line to the
//!   room with nobody taking it up, a note says how many heard it and how to speak to someone.
//!   Who heard it: the people perceived within earshot when it was said (until the authority's
//!   `heard_by` lands, `heard.rs`).
//! - **What the authority accepts:** any `to`. An addressee out of earshot hears nothing, and I
//!   get "… could not have heard you." (a `silence` row; "No answer from …" where the world's `speech_truth` law is off). A line within 2 s of the last is refused
//!   ("speaking too fast").

use crate::net::Net;
use crate::world::Scene;
use bevy::prelude::*;
use living_bindings::*;
use living_rules::script::{ActorFacts, SkillCtx};
use spacetimedb_sdk::Table;
use std::collections::HashSet;

/// A way of speaking the box offers: its key, whether it names a person, and whether the
/// world's rules allow it yet (whisper and skill channels come with `docs/COMMUNICATION.md`).
pub struct ModeSpec {
    pub key: &'static str,
    pub person: bool,
    pub available: bool,
}

/// The box's ways of speaking, in Tab's order: a person in earshot, then the room. Whisper is
/// listed, unavailable, so the box shows where it will go.
pub const MODES: [ModeSpec; 3] = [ModeSpec { key: "person", person: true, available: true }, ModeSpec { key: "room", person: false, available: true }, ModeSpec { key: "whisper", person: true, available: false }];

/// How long the room has to take a line up before the note says nobody did (s).
const ROOM_WAIT_S: f64 = 10.0;

/// While the box is open, who is within earshot is asked this often (s).
const ASK_S: f32 = 0.25;
/// A `silence` row is shown if it is at most this old when it arrives (ms).
const FRESH_MS: f64 = 5_000.0;

#[derive(Resource, Default)]
pub struct Talk {
    /// The person the open text box addresses.
    pub to: Option<u32>,
    /// What the box says of them: "Say to a stranger", "Say — nobody in earshot".
    pub label: String,
    /// People within earshot now, nearest first (Tab's order); empty before the rules are known.
    pub earshot: Vec<u32>,
    /// A left tap on a peaceful person (`combat.rs`): open the box to them, or, open, address them.
    pub open_to: Option<u32>,
    /// Tab in the box (`ui/say.rs`).
    pub cycle: bool,
    /// Type to this one (a click in their window's box; `Some(None)`: the room), without
    /// turning to them.
    pub want: Option<Option<u32>>,
    /// The person under the cursor when Enter opened the box (`ui/say.rs`): addressed.
    pub prefer: Option<u32>,
    /// A line to the room awaiting someone to take it up: when it was said (authority ms), and
    /// who heard it as far as I know (perceived in earshot then).
    room: Option<(u64, Vec<u32>)>,
    /// Whom the open box addresses has been worked out this opening (the window can follow).
    pub resolved: bool,
    /// Addressed on purpose from their window (its box, Introduce yourself): kept even when
    /// out of sight, so the line goes to them and the authority says whether they heard.
    pinned: bool,
    was_open: bool,
    next_ask: f32,
    seen: HashSet<u64>,
    /// Someone has spoken to me this session (the talk hint shows again the first time).
    heard_to_me: bool,
}

pub struct TalkPlugin;

impl Plugin for TalkPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Talk>()
            .add_systems(Update, address.in_set(crate::phase::Phase::Input).after(crate::combat::input))
            .add_systems(Update, told.in_set(crate::phase::Phase::Present));
    }
}

/// How far a person hears by the world's rules (m).
fn hearing(sc: &living_rules::script::Scripts, c: &SeenCharacter, hour: f32) -> Option<f32> {
    let actor = ActorFacts { id: c.id, kind: c.kind.clone(), stage: crate::verbs::stage_name(c.stage).into(), ..Default::default() };
    // Night and how dark it is are the world's `daylight` law.
    let ctx = SkillCtx { actor, night: sc.is_night(hour), dark: sc.dark(hour), hour, ..Default::default() };
    match sc.senses(&ctx) {
        Ok(s) => Some(s.hearing),
        Err(e) => {
            warn!("talk: the rules' senses law failed: {e}");
            None
        }
    }
}

/// The people within earshot of me, nearest first.
#[allow(clippy::too_many_arguments)]
fn earshot(conn: &DbConnection, scene: &Scene, rules: &crate::verbs::Rules, me: u32, at: Vec2, hour: f32, town: &crate::town::Town, combat: &crate::combat::Combat) -> Vec<u32> {
    let Some(sc) = rules.scripts.as_ref() else { return Vec::new() };
    let mut near: Vec<(f32, u32)> = scene
        .shown
        .iter()
        .filter(|(id, _)| **id != me && !town.hidden(**id) && !combat.deaths.contains_key(id))
        .filter_map(|(id, (p, _))| {
            let c = conn.db.seen_characters().id().find(id).filter(|c| c.kind == "person")?;
            let d = p.distance(at);
            (d <= hearing(sc, &c, hour)?).then_some((d, *id))
        })
        .collect();
    near.sort_by(|a, b| a.0.total_cmp(&b.0));
    near.into_iter().map(|(_, id)| id).collect()
}

/// Whom the open text box addresses, and what it says of them.
#[allow(clippy::too_many_arguments)]
fn address(
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    rules: NonSend<crate::verbs::Rules>,
    clock: Res<crate::daylight::Clock>,
    target: Res<crate::controls::Target>,
    (combat, town): (Res<crate::combat::Combat>, Res<crate::town::Town>),
    mut input: ResMut<crate::controls::Input>,
    mut talk: ResMut<Talk>,
    (time, looks): (Res<Time>, Res<crate::looks::Looks>),
) {
    let (Some(conn), Some(me), Some(me3)) = (net.conn.as_ref(), net.my_id, target.0) else {
        talk.open_to = None;
        return;
    };
    let at = Vec2::new(me3.x, me3.z);
    let now = time.elapsed_secs();
    // A tap on a peaceful person: the box opens to them, and I turn to them where I stand.
    let tapped = talk.open_to.take();
    let wanted = talk.want.take();
    if wanted.is_some() && !input.chat_open {
        input.chat_open = true;
        if !std::mem::take(&mut input.keep_words) {
            input.chat.clear();
        }
        input.compose = None;
        talk.was_open = false;
    }
    if let Some(id) = tapped {
        if !input.chat_open {
            input.chat_open = true;
            input.chat.clear();
            input.compose = None;
            talk.was_open = false;
        }
        if !input.moving {
            let node = serde_json::json!({"do": "face", "target": {"id": id}});
            let node = node.to_string();
            let r = conn.reducers.human_act_then(node.clone(), net.on_reply("face", "human_act", || serde_json::json!({"node": node})));
            net.report("face", r);
        }
    }
    if !input.chat_open || input.compose.is_some() {
        talk.was_open = false;
        talk.to = None;
        talk.cycle = false;
        talk.resolved = false;
        talk.pinned = false;
        talk.prefer = None;
        input.keep_words = false;
        return;
    }
    let fresh = !talk.was_open;
    talk.was_open = true;
    if fresh || now >= talk.next_ask {
        talk.next_ask = now + ASK_S;
        talk.earshot = earshot(conn, &scene, &rules, me, at, clock.hour(), &town, &combat);
    }
    let perceived = |id: u32| conn.db.seen_characters().id().find(&id).is_some_and(|c| c.kind == "person");
    let prefer = talk.prefer.take();
    if let Some(id) = tapped.filter(|id| perceived(*id)) {
        talk.to = Some(id);
    } else if let Some(w) = wanted {
        talk.to = w;
        talk.pinned = w.is_some();
    } else if fresh {
        // Hovering someone: them; else the room (the owner's rule: no nearest-person fallback).
        talk.to = prefer.filter(|id| perceived(*id));
    }
    // Tab: the next one within earshot, nearest first, then the room, then round again.
    if std::mem::take(&mut talk.cycle) && !talk.earshot.is_empty() {
        talk.pinned = false;
        talk.to = match talk.to.and_then(|t| talk.earshot.iter().position(|e| *e == t)) {
            Some(i) if i + 1 < talk.earshot.len() => Some(talk.earshot[i + 1]),
            Some(_) => None,
            None if talk.to.is_some() => talk.earshot.first().copied(),
            None => talk.earshot.first().copied(),
        };
    }
    // Someone I no longer perceive: back to the room.
    if !talk.pinned && talk.to.is_some_and(|id| !perceived(id)) {
        talk.to = None;
    }
    talk.resolved = true;
    let label = match talk.to {
        Some(id) => {
            let who = looks.of(id).map(String::from).unwrap_or_else(|| conn.db.seen_characters().id().find(&id).map_or_else(|| "someone".to_string(), |c| c.label));
            let far = if talk.earshot.contains(&id) { "" } else { " (out of earshot)" };
            format!("To {who}{far}")
        }
        None => "To the room".to_string(),
    };
    if talk.label != label {
        talk.label = label;
    }
}

/// What the authority told me of my speech: no answer from someone out of earshot. And the
/// talk hint: on arrival, once the first load's cover lifts, and again the first time someone
/// speaks to me.
#[allow(clippy::too_many_arguments)]
fn told(
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    time: Res<Time>,
    target: Res<crate::controls::Target>,
    loading: Option<Res<crate::loading::Loading>>,
    mut talk: ResMut<Talk>,
    mut verbs: ResMut<crate::verbs::Verbs>,
    mut tips: Option<ResMut<crate::ui::tips::Tips>>,
) {
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else { return };
    let now = time.elapsed_secs_f64();
    if target.0.is_some() && crate::loading::Loading::clear(loading.as_deref()) {
        if let Some(t) = tips.as_mut() {
            t.once(crate::ui::tips::TALK, now);
        }
    }
    let mut rows: Vec<Experience> = conn.db.my_experience().iter().filter(|e| e.observer == me && matches!(e.kind.as_str(), "silence" | "speech" | "said")).collect();
    rows.sort_by_key(|e| e.id);
    for e in rows {
        if !talk.seen.insert(e.id) {
            continue;
        }
        let fresh = e.at_ms as f64 + FRESH_MS >= scene.now_ms;
        // A line of mine to the room: who heard it, as far as I know (perceived in earshot as I
        // spoke; the authority's `heard_by` will replace this, `heard.rs`).
        if e.kind == "said" && e.object == 0 && fresh {
            let heard = crate::heard::heard_by(&e).unwrap_or_else(|| talk.earshot.clone());
            talk.room = Some((e.at_ms, heard));
            continue;
        }
        // Someone who heard it said something since: the room took it up.
        if e.kind == "speech" && talk.room.as_ref().is_some_and(|(at, who)| e.at_ms >= *at && (who.contains(&e.subject) || e.object == me)) {
            talk.room = None;
        }
        if e.kind == "silence" && fresh {
            verbs.toasts.push(crate::verbs::Toast { text: e.text.clone(), ok: Some(false), at: now });
        } else if e.kind == "speech" && fresh && !talk.heard_to_me && e.text.contains(" said to you:") {
            talk.heard_to_me = true;
            if let Some(t) = tips.as_mut() {
                t.show(crate::ui::tips::TALK, now);
            }
        }
    }
    // Nobody took it up: say so, plainly (minds give a line to the room no turn yet).
    if let Some((at, who)) = talk.room.clone() {
        if scene.now_ms - at as f64 > ROOM_WAIT_S * 1000.0 {
            talk.room = None;
            let text = if who.is_empty() { "No one in earshot heard you. Point at someone and press Enter to speak to them.".to_string() } else { format!("Heard by {} — no one took it up. Point at someone and press Enter to speak to them.", who.len()) };
            info!("talk: room note \"{text}\"");
            verbs.toasts.push(crate::verbs::Toast { text, ok: None, at: now });
        }
    }
    if talk.seen.len() > 1024 {
        let live: HashSet<u64> = conn.db.my_experience().iter().map(|e| e.id).collect();
        talk.seen.retain(|id| live.contains(id));
    }
}
