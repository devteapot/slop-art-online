//! Whom the text box speaks to (play-test 2: every chat line went to no one, and in a crowd an
//! unaddressed line from a stranger draws no conversation turn from the minds).
//!
//! - **Earshot is the rules'.** The world's installed script answers `senses(a)`, the law the
//!   authority's `perceive::speak` asks for each listener; its `hearing` is how far speech
//!   carries. The client asks it for each person it perceives (their kind and stage, night from
//!   the displayed clock), four times a second while the box is open.
//! - **Whom.** When the box opens it addresses the person under the cursor (combat's pick) if
//!   they are within earshot, else the nearest person within earshot. Tab goes to the next one
//!   within earshot, nearest first. A left tap on a peaceful person opens the box to them
//!   (`combat.rs`), and a tap on someone else while it is open addresses them instead.
//! - **Shown as I know them.** The box reads "Say to <label>", the projection's `label` from
//!   `seen_characters`: a name only where the rules give it, else "a stranger", "a child". The
//!   one addressed is the HUD's target while the box is open, so their plate shows which
//!   stranger it is.
//! - **Sent with `to`.** `human_say(text, to)`. With nobody in earshot the box says so and the
//!   line goes to no one (`to = 0`), as before.
//! - **What the authority accepts.** Any `to`. The line is heard by everyone within their own
//!   hearing; the one addressed hears it as said to them (a conversation turn for their mind),
//!   whatever the 6 m rule for unaddressed speech (`address_m`). An addressee out of earshot
//!   hears nothing, and I get "No answer from …" (a `silence` experience row), shown as a
//!   refused note. A line within 2 s of the last is refused ("speaking too fast").

use crate::net::Net;
use crate::world::Scene;
use bevy::prelude::*;
use living_bindings::*;
use living_rules::script::{ActorFacts, SkillCtx};
use spacetimedb_sdk::Table;
use std::collections::HashSet;

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
    /// Tab in the box (`ui/chat.rs`).
    pub cycle: bool,
    was_open: bool,
    next_ask: f32,
    seen: HashSet<u64>,
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
    let ctx = SkillCtx { actor, night: living_rules::is_night(hour), hour, ..Default::default() };
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
    time: Res<Time>,
) {
    let (Some(conn), Some(me), Some(me3)) = (net.conn.as_ref(), net.my_id, target.0) else {
        talk.open_to = None;
        return;
    };
    let at = Vec2::new(me3.x, me3.z);
    let now = time.elapsed_secs();
    // A tap on a peaceful person: the box opens to them, and I turn to them where I stand.
    let tapped = talk.open_to.take();
    if let Some(id) = tapped {
        if !input.chat_open {
            input.chat_open = true;
            input.chat.clear();
            input.compose = None;
            talk.was_open = false;
        }
        if !input.moving {
            let node = serde_json::json!({"do": "face", "target": {"id": id}});
            let r = conn.reducers.human_act_then(node.to_string(), net.on_reply("face"));
            net.report("face", r);
        }
    }
    if !input.chat_open || input.compose.is_some() {
        talk.was_open = false;
        talk.to = None;
        talk.cycle = false;
        return;
    }
    let fresh = !talk.was_open;
    talk.was_open = true;
    if fresh || now >= talk.next_ask {
        talk.next_ask = now + ASK_S;
        talk.earshot = earshot(conn, &scene, &rules, me, at, clock.hour(), &town, &combat);
    }
    let perceived = |id: u32| conn.db.seen_characters().id().find(&id).is_some_and(|c| c.kind == "person");
    if let Some(id) = tapped.filter(|id| perceived(*id)) {
        talk.to = Some(id);
    } else if fresh {
        talk.to = combat.target.filter(|id| talk.earshot.contains(id)).or(talk.earshot.first().copied());
    }
    if std::mem::take(&mut talk.cycle) && !talk.earshot.is_empty() {
        let next = talk.to.and_then(|t| talk.earshot.iter().position(|e| *e == t)).map_or(0, |i| (i + 1) % talk.earshot.len());
        talk.to = Some(talk.earshot[next]);
    }
    // Someone I no longer perceive: the nearest within earshot instead.
    if talk.to.is_some_and(|id| !perceived(id)) {
        talk.to = talk.earshot.first().copied();
    }
    let label = match talk.to {
        Some(id) => {
            let who = conn.db.seen_characters().id().find(&id).map_or_else(|| "someone".to_string(), |c| c.label);
            let far = if talk.earshot.contains(&id) { "" } else { " (out of earshot)" };
            let more = if talk.earshot.len() > 1 { "  ·  Tab: someone else" } else { "" };
            format!("Say to {who}{far}{more}")
        }
        None if rules.scripts.is_some() => "Say — nobody in earshot".to_string(),
        None => "Say".to_string(),
    };
    if talk.label != label {
        talk.label = label;
    }
}

/// What the authority told me of my speech: no answer from someone out of earshot.
fn told(net: NonSend<Net>, scene: NonSend<Scene>, time: Res<Time>, mut talk: ResMut<Talk>, mut verbs: ResMut<crate::verbs::Verbs>) {
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else { return };
    let now = time.elapsed_secs_f64();
    for e in conn.db.my_experience().iter().filter(|e| e.observer == me && e.kind == "silence") {
        if !talk.seen.insert(e.id) {
            continue;
        }
        let fresh = e.at_ms as f64 + FRESH_MS >= scene.now_ms;
        if fresh {
            verbs.toasts.push(crate::verbs::Toast { text: e.text.clone(), ok: Some(false), at: now });
        }
    }
    if talk.seen.len() > 1024 {
        let live: HashSet<u64> = conn.db.my_experience().iter().map(|e| e.id).collect();
        talk.seen.retain(|id| live.contains(id));
    }
}
