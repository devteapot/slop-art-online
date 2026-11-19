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
//! - **Ways come from the world** ([`ways`], `speech_card`): its ways of speaking in their order
//!   (say, whisper, call… as the rules name and label them); the box's chip shows the one it
//!   has, and a click on it or the Way key (Up) moves to the next. A line goes in that way
//!   (`human_speak`); its limits are the card's (`max_chars` cuts the box, `gap_ms` greys the
//!   chip), and whatever the rules refuse (a whisper to no one, a call too soon) comes back in
//!   their words as a note. Tab follows the way's reach: the authority's list for it when the
//!   `earshot` law gives one, else its carry by the rules (`WaySpec::carry_for`, a reach such as a
//!   whisper's as the limit).
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

/// The world's ways of speaking (`speech_card`: say, whisper, call… as the rules name them), in
/// the box's order (the card's `order`): the first is the box's own until another is chosen.
/// No way is named here (the rules' ratchet, `living_rules::ui`).
pub fn ways(conn: &DbConnection) -> Vec<SpeechCard> {
    let mut v: Vec<SpeechCard> = conn.db.speech_card().iter().collect();
    v.sort_by(|a, b| a.order.cmp(&b.order).then_with(|| a.name.cmp(&b.name)));
    v
}

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
    /// With the authority's earshot (the `earshot` law: `my_earshot`), its `say` list; else the
    /// client's own reckoning ([`earshot`]).
    pub earshot: Vec<u32>,
    /// The authority's earshot row while it has one: its sentence, in my own labels ("Within
    /// earshot if you say it: ...; a whisper would reach no one; a call would also reach: ..."),
    /// and each way's hearers. None with the law off.
    pub told: Option<Told>,
    /// The way of speaking chosen in the box (a `speech_card` name; None: the world's first), the
    /// card it is now (for the box's chip, its limit and gap), and a request for the next one (the
    /// Way key, a click on the chip).
    pub way: Option<String>,
    pub card: Option<SpeechCard>,
    pub next_way: bool,
    /// When each way was last used here (app s), for its gap (`gap_ms`).
    pub used_at: std::collections::HashMap<String, f64>,
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
    /// When the authority last told me a line of mine to the room reached no one (authority ms).
    room_unheard: Option<u64>,
    /// The last Tab, for the UI dump: whom it came from, the earshot it went by (refreshed every
    /// `ASK_S`, so a later dump's list can differ) and whom it chose before the perceived check.
    pub tabbed: Option<(Option<u32>, Vec<u32>, Option<u32>, bool)>,
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

/// The authority's earshot for me (`my_earshot`, the `earshot` law): who would hear a line said
/// now at each way, people I can see only, and its sentence in my own labels.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Told {
    pub text: String,
    /// (way, hearers): say, call, whisper.
    pub ways: Vec<(String, Vec<u32>)>,
}

impl Told {
    /// Who would hear a line said `way`'s way.
    pub fn hearers(&self, way: &str) -> Option<&[u32]> {
        self.ways.iter().find(|(w, _)| w == way).map(|(_, h)| h.as_slice())
    }
}

/// My row of the authority's earshot, if the world's `earshot` law writes one.
pub fn earshot_row(conn: &DbConnection, me: u32) -> Option<Told> {
    let r = conn.db.my_earshot().id().find(&me)?;
    Some(Told { text: r.text, ways: r.ways.into_iter().map(|w| (w.way, w.hearers)).collect() })
}

/// The people within earshot of me, nearest first.
#[allow(clippy::too_many_arguments)]
fn earshot(conn: &DbConnection, scene: &Scene, rules: &crate::verbs::Rules, me: u32, at: Vec2, hour: f32, town: &crate::town::Town, combat: &crate::combat::Combat, way: Option<&SpeechCard>) -> Vec<u32> {
    let Some(sc) = rules.scripts.as_ref() else { return Vec::new() };
    // A way's words carry by the rules (`WaySpec::carry_for` the hearer's hearing); one that names
    // someone within a reach (a whisper) reaches no further than that.
    let spec = way.and_then(|w| sc.way(&w.name));
    let reach = way.map_or(0.0, |w| w.reach_m);
    let mut near: Vec<(f32, u32)> = scene
        .shown
        .iter()
        .filter(|(id, _)| **id != me && !town.hidden(**id) && !combat.deaths.contains_key(id))
        .filter_map(|(id, (p, _))| {
            let c = conn.db.seen_characters().id().find(id).filter(|c| c.kind == "person")?;
            let d = p.distance(at);
            let h = hearing(sc, &c, hour)?;
            let carry = spec.map_or(h, |w| w.carry_for(h));
            let within = if reach > 0.0 { carry.min(reach) } else { carry };
            (d <= within).then_some((d, *id))
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
    // The way of speaking: the one chosen if the world still has it, else its first; the Way
    // key or the chip moves to the next.
    let all = ways(conn);
    let mut i = talk.way.as_ref().and_then(|w| all.iter().position(|c| &c.name == w)).unwrap_or(0);
    if std::mem::take(&mut talk.next_way) && !all.is_empty() {
        i = (i + 1) % all.len();
        talk.way = Some(all[i].name.clone());
        talk.next_ask = 0.0;
        info!("talk: way {}", all[i].name);
    }
    let card = all.get(i).cloned();
    // The way's longest line (`max_chars`): the box holds no more, however the words came.
    if let Some(max) = card.as_ref().map(|c| c.max_chars as usize).filter(|m| *m > 0) {
        if input.chat.chars().count() > max {
            input.chat = input.chat.chars().take(max).collect();
        }
    }
    if talk.card != card {
        talk.card = card;
    }
    let fresh = !talk.was_open;
    talk.was_open = true;
    if fresh || now >= talk.next_ask {
        talk.next_ask = now + ASK_S;
        // The authority's own list when it gives one (the box can only say: its `say` way; whisper
        // and call have no place here yet), else the client's reckoning, as before.
        let told = earshot_row(conn, me);
        // That way's own list (the authority's, by its name), else its reach by the rules.
        let way = talk.card.clone();
        talk.earshot = match told.as_ref().zip(way.as_ref()).and_then(|(t, w)| t.hearers(&w.name)) {
            Some(h) => h.to_vec(),
            None => earshot(conn, &scene, &rules, me, at, clock.hour(), &town, &combat, way.as_ref()),
        };
        if talk.told != told {
            talk.told = told;
        }
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
    let tab = std::mem::take(&mut talk.cycle);
    let prev = talk.to;
    if tab && !talk.earshot.is_empty() {
        talk.pinned = false;
        talk.to = match talk.to.and_then(|t| talk.earshot.iter().position(|e| *e == t)) {
            Some(i) if i + 1 < talk.earshot.len() => Some(talk.earshot[i + 1]),
            Some(_) => None,
            None if talk.to.is_some() => talk.earshot.first().copied(),
            None => talk.earshot.first().copied(),
        };
    }
    if tab {
        // Whether the list it went by was the authority's (`my_earshot`) or the client's own.
        let authority = talk.told.as_ref().is_some_and(|t| t.hearers("say").is_some());
        talk.tabbed = Some((prev, talk.earshot.clone(), talk.to, authority));
    }
    // Someone I no longer perceive: back to the room.
    if !talk.pinned && talk.to.is_some_and(|id| !perceived(id)) {
        talk.to = None;
    }
    talk.resolved = true;
    let label = match talk.to {
        Some(id) => {
            // As `Looks` names them (the one way the client names anyone).
            let who = looks.of(id).unwrap_or("someone").to_string();
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
            // Unless the authority already said nobody heard it (`speech_truth`; its row can come
            // first): then its words are the note, not this one.
            if talk.room_unheard != Some(e.at_ms) {
                let heard = crate::heard::heard_by(&e).unwrap_or_else(|| talk.earshot.clone());
                talk.room = Some((e.at_ms, heard));
            }
            continue;
        }
        // Someone who heard it said something since: the room took it up.
        if e.kind == "speech" && talk.room.as_ref().is_some_and(|(at, who)| e.at_ms >= *at && (who.contains(&e.subject) || e.object == me)) {
            talk.room = None;
        }
        if e.kind == "silence" && fresh {
            // The authority's truth about a line not heard (`speech_truth`: "… could not have
            // heard you.", "Nobody was near enough to hear you."): once, as a quiet note (not a
            // refusal). A room line's replaces the client's own "No one in earshot" note.
            if e.subject == 0 {
                talk.room_unheard = Some(e.at_ms);
                talk.room = talk.room.take().filter(|(at, _)| *at != e.at_ms);
            }
            verbs.toasts.push(crate::verbs::Toast { text: e.text.clone(), ok: None, at: now });
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
