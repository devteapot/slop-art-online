//! Sheathe and draw (interface D, the owner's choice; it replaces talk-1's stopgap, where a
//! held press struck a peaceful person).
//!
//! - **One state**, [`Weapon`]: sheathed or drawn, since when and why. X (the Weapon binding)
//!   sheathes or draws it.
//! - **Sheathed:** a tap on a person talks to them (or acts); the attack skills (the rules'
//!   `hostile` trait, `combat::Shape`) are greyed on the bar, and the first press of one draws
//!   the weapon instead of firing. Nothing else changes: a block, a heal, the jump and the dodge
//!   work sheathed.
//! - **Drawn:** a tap strikes what is under the cursor, whoever it is.
//! - **It draws itself when I am attacked** (Settings › Play can turn that off): when the
//!   authority tells me of a blow or a shot on me (my `attacked` line, newer than a few seconds),
//!   or someone becomes hostile to me as my client knows it (`combat::hostile_to_me`: their move
//!   is aimed at me, or they hurt me within 15 s, `vitals.hurt_by`). The note is the authority's
//!   own line when there is one ("A stranger shot you with an arrow: hit for 8. Your weapon is
//!   drawn."; "An arrow struck you from somewhere you could not see: …"), never a second sentence
//!   of ours beside it; before any hit, "A wolf is attacking you. Your weapon is drawn." An unseen
//!   shooter (the line's subject 0) is named by nothing, targeted by nothing, pointed at by
//!   nothing.
//! - **Shaped to be sent.** Residents will react to a drawn weapon once the authority has a
//!   per-body `drawn` state, set through an act and carried in the projection (the Spark
//!   coordinator's; docs/INTERFACE.md example 1: `draw_spec`, `draw_ui`, a `stance` trait).
//!   [`Weapon::act`] is that act's node; [`send`] is the one place it would be sent, and sends
//!   nothing until the act exists.
//! - **A restriction only.** Kept on this client until then, it can only stop this player's
//!   own presses (an attack while sheathed draws instead); it grants nothing and changes nothing
//!   the authority decides. The greyed skills are the rules' `hostile` ones until a `stance`
//!   trait names them.

use crate::net::Net;
use bevy::prelude::*;
use living_bindings::*;
use spacetimedb_sdk::Table;
use std::collections::HashSet;

#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Why {
    #[default]
    Start,
    /// The Weapon key.
    Key,
    /// The first press of an attack skill while sheathed.
    Attack,
    /// Someone attacked me (their id; 0 when I could not see them).
    Attacked(u32),
}

#[derive(Resource, Clone, Debug, Default)]
pub struct Weapon {
    pub drawn: bool,
    /// When it last changed (authority ms), and why.
    pub since_ms: f64,
    pub why: Why,
    /// Who was hostile to me last frame (a new one draws it).
    hostile: HashSet<u32>,
    /// A script's X (`weapon:toggle|draw|sheathe` in the live script).
    pub scripted: Option<bool>,
    /// The authority's `attacked` lines already read (experience ids).
    told: HashSet<u64>,
    /// Drawn for a move aimed at me before any hit: whose, and when (authority ms). The note
    /// waits [`HELD_NOTE_MS`] for the authority's line (a drawn bow is told "shot you" once its
    /// arrow lands), and is ours ("is attacking you") only if none comes.
    pending: Option<(u32, f64)>,
}

impl Weapon {
    pub fn set(&mut self, drawn: bool, why: Why, now_ms: f64, net: &Net) {
        if self.drawn == drawn {
            return;
        }
        self.drawn = drawn;
        self.since_ms = now_ms;
        self.why = why;
        info!("weapon: {} ({why:?})", if drawn { "drawn" } else { "sheathed" });
        send(net, self);
    }

    /// The act that will tell the authority, in the shape docs/INTERFACE.md example 1 gives
    /// (`draw` taking the state as its item); not in the rules yet, so never sent.
    pub fn act(&self) -> serde_json::Value {
        serde_json::json!({"do": "draw", "item": if self.drawn { "drawn" } else { "sheathed" }})
    }
}

/// Where the weapon's state goes to the authority: nowhere until the rules have a `drawn`
/// state and an act to set it.
pub fn send(net: &Net, w: &Weapon) {
    let _ = (net, w.act());
}

/// How new an `attacked` line must be to draw the weapon and be the note (authority ms).
const TOLD_FRESH_MS: f64 = 3_000.0;
/// How long the note for a move aimed at me waits for the authority's line (ms): an arrow's
/// flight and the line's arrival.
const HELD_NOTE_MS: f64 = 1_500.0;

/// The Weapon key, and drawing itself when someone attacks me.
#[allow(clippy::too_many_arguments)]
pub fn update(
    net: NonSend<Net>,
    scene: NonSend<crate::world::Scene>,
    keys: Res<ButtonInput<KeyCode>>,
    binds: Res<crate::keys::Binds>,
    prefs: Res<crate::keys::Prefs>,
    input: Res<crate::controls::Input>,
    wants: Res<crate::hud::UiWants>,
    looks: Res<crate::looks::Looks>,
    mut verbs: ResMut<crate::verbs::Verbs>,
    mut w: ResMut<Weapon>,
    time: Res<Time>,
) {
    let now_ms = scene.now_ms;
    let typing = input.chat_open || wants.keyboard;
    if !typing && binds.just_pressed(crate::keys::Act::Weapon, &keys) {
        let d = !w.drawn;
        w.set(d, Why::Key, now_ms, &net);
    }
    if let Some(d) = w.scripted.take() {
        w.set(d, Why::Key, now_ms, &net);
    }
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else { return };
    // What the authority told me of a blow or a shot on me, newest of those just arrived.
    let mut hit: Option<Experience> = None;
    for e in conn.db.my_experience().iter().filter(|e| e.observer == me && e.kind == "attacked") {
        if w.told.insert(e.id) && now_ms - (e.at_ms as f64) < TOLD_FRESH_MS && hit.as_ref().is_none_or(|h| e.at_ms >= h.at_ms) {
            hit = Some(e);
        }
    }
    if w.told.len() > 1024 {
        let live: HashSet<u64> = conn.db.my_experience().iter().map(|e| e.id).collect();
        w.told.retain(|id| live.contains(id));
    }
    let now: HashSet<u32> = conn.db.seen_characters().iter().filter(|c| c.id != me && crate::combat::hostile_to_me(conn, c.id, me, now_ms)).map(|c| c.id).collect();
    let fresh = now.iter().copied().find(|id| !w.hostile.contains(id));
    w.hostile = now;
    let said = |e: &Experience| format!("{}. Your weapon is drawn.", crate::ui::label(e.text.trim().trim_end_matches('.')));
    let mut text = None;
    // Drawn for an aimed move a moment ago: the authority's line when it comes, else ours.
    if let Some((id, since)) = w.pending {
        if let Some(e) = &hit {
            text = Some(said(e));
            w.pending = None;
        } else if now_ms - since >= HELD_NOTE_MS {
            text = Some(format!("{} is attacking you. Your weapon is drawn.", looks.cap(id)));
            w.pending = None;
        }
    } else if !w.drawn && prefs.auto_draw {
        match (&hit, fresh) {
            // The authority's line names the shooter as I perceive them, or no one when unseen.
            (Some(e), _) => {
                w.set(true, Why::Attacked(e.subject), now_ms, &net);
                text = Some(said(e));
            }
            (None, Some(id)) => {
                w.set(true, Why::Attacked(id), now_ms, &net);
                w.pending = Some((id, now_ms));
            }
            (None, None) => {}
        }
    }
    if let Some(text) = text {
        verbs.toasts.push(crate::verbs::Toast { text, ok: None, at: time.elapsed_secs_f64() });
    }
}
