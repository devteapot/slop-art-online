//! Heed for players, the client's side (docs/ATTENTION_BUDGET.md, "Built: the player side" and
//! v2.1 point 6): whom I keep track of. Only while the world's laws let players heed (`heed_on`
//! and `heed_players`: the set in place has `seen_throng`, `net::throng`); off, nothing here reads
//! a key, sends a call or draws anything.
//!
//! - **Pins:** the Pin key (T) on whoever the cursor points at (`pick.rs`, the pick the plates,
//!   Enter and combat use) pins them, or unpins them if pinned; Clear (Y) unpins everyone. At most
//!   [`MAX_PINS`]: a fifth is warned about first, and asked for only on a second press (the
//!   authority then refuses it in its own words).
//! - **A throng figure:** clicking a throng card (or pressing the Pin key while pointing at one)
//!   sends `human_heed` with `pin_at` = the click's ground point (map metres), keeping the current
//!   pins and focus. The authority picks the nearest throng member in that square through heed's
//!   selection; if taken, it joins `perceived` in the same transaction and becomes one of the pins
//!   (shown as an individual with a pin ring through the normal perceived path).
//! - **Focus** follows my current target: whom the open text box speaks to, else the creature my
//!   last creature-aimed skill went to (held [`FOCUS_HOLD_MS`]). Hover stays on the client.
//! - **The call:** `human_heed(HeedInput { pins, focus, pin_at })` carries the whole choice. Changes are
//!   coalesced: at most one call in flight, at least [`SPACING_S`] apart (the authority takes one
//!   per 250 ms, each spending an input token), never one that changes nothing. Only those I
//!   perceive now go in it (the authority refuses the whole call otherwise), so a pin out of
//!   sight is kept here a while ([`GONE_S`]) but not sent.
//! - **Refusals** show the authority's words in the notes, exactly (`verbs.rs` toasts).
//! - **Death or another character:** everything here is forgotten (the authority drops the row
//!   with the character).

use crate::net::Net;
use bevy::prelude::*;
use living_bindings::*;
use std::sync::{Arc, Mutex};

/// The most pins the authority keeps (`heed::MAX_PINS` there).
pub const MAX_PINS: usize = 4;
/// Calls at least this far apart (s): over the authority's 250 ms floor.
pub const SPACING_S: f64 = 0.3;
/// After a pace refusal ("too many inputs"), try again after this (s).
const RETRY_S: f64 = 0.4;
/// A second Pin press on a fifth within this (s) asks the authority anyway.
const OVER_S: f64 = 3.0;
/// A pin I no longer perceive is let go after this (s).
pub const GONE_S: f64 = 10.0;
/// My combat target stays my focus this long after my last skill aimed at it (display ms).
pub const FOCUS_HOLD_MS: f64 = 10_000.0;
/// The authority's words for a call too soon or with no input left.
pub const PACE: &str = "too many inputs";

/// Whom I keep track of: the pins (in the order pinned) and the focus.
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Choice {
    pub pins: Vec<u32>,
    pub focus: Option<u32>,
}

impl Choice {
    /// Only those `seen` holds: what a call may carry.
    pub fn seen(&self, seen: impl Fn(u32) -> bool) -> Choice {
        Choice { pins: self.pins.iter().copied().filter(|p| seen(*p)).collect(), focus: self.focus.filter(|f| seen(*f)) }
    }
}

/// What a Pin press did to the pins.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Toggle {
    Added,
    Removed,
    /// Already [`MAX_PINS`]: not added.
    Full,
}

/// Pin `id`, or unpin it if pinned; a fifth is not added.
pub fn toggle(pins: &mut Vec<u32>, id: u32) -> Toggle {
    if let Some(i) = pins.iter().position(|p| *p == id) {
        pins.remove(i);
        Toggle::Removed
    } else if pins.len() >= MAX_PINS {
        Toggle::Full
    } else {
        pins.push(id);
        Toggle::Added
    }
}

/// One `human_heed` call: the pins and focus, plus an optional throng ground point (`pin_at`).
#[derive(Clone, Debug, PartialEq)]
pub struct Call {
    pub choice: Choice,
    pub pin_at: Option<Vec2>,
}

impl Call {
    pub fn of_choice(choice: Choice) -> Self {
        Self { choice, pin_at: None }
    }

    pub fn with_pin_at(choice: Choice, at: Vec2) -> Self {
        Self { choice, pin_at: Some(at) }
    }

    pub fn to_input(&self) -> HeedInput {
        HeedInput { pins: self.choice.pins.clone(), focus: self.choice.focus, pin_at: self.pin_at.map(|p| PinAt { x: p.x, y: p.y }) }
    }
}

/// The calls: what the authority holds as far as I know, the one in flight, and the pace.
#[derive(Default, Debug)]
pub struct Sender {
    /// My last accepted choice (the authority's `heed_choice` row, as far as I know).
    pub acked: Choice,
    pub pending: Option<Call>,
    pub last_sent: Option<f64>,
    retry_at: f64,
    /// A choice refused for a reason other than pace: not asked again unchanged.
    pub refused: Option<Choice>,
}

/// How a reply ended, for the caller.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Outcome {
    Accepted,
    /// Too soon or no input left: asked again shortly.
    Paced,
    Refused(String),
    /// Not the call in flight (a reply after a reset).
    Stale,
}

impl Sender {
    /// The call to send now, if any: `force` as it is (a fifth pin on a second press, or a live
    /// script probe), else a pending throng click `pin_at` carrying `want` as `seen` allows, else
    /// `want` as `seen` allows when it differs from what the authority holds (as `seen` allows: a
    /// pin gone from sight needs no call) and was not refused as it is. Always respects in-flight
    /// and [`SPACING_S`].
    pub fn next(&self, want: &Choice, seen: impl Fn(u32) -> bool + Copy, now: f64, force: Option<&Call>, pin_at: Option<Vec2>) -> Option<Call> {
        if self.pending.is_some() || now < self.retry_at || self.last_sent.is_some_and(|t| now - t < SPACING_S) {
            return None;
        }
        if let Some(f) = force {
            return Some(f.clone());
        }
        let w = want.seen(seen);
        if let Some(at) = pin_at {
            return Some(Call::with_pin_at(w, at));
        }
        (w != self.acked.seen(seen) && self.refused.as_ref() != Some(&w)).then(|| Call::of_choice(w))
    }

    pub fn sent(&mut self, c: Call, now: f64) {
        self.pending = Some(c);
        self.last_sent = Some(now);
    }

    /// Record the id promoted and pinned by an accepted `pin_at` call, so `acked` matches the
    /// authority's `heed_choice` row without sending a redundant call.
    pub fn record_picked(&mut self, id: u32) {
        if !self.acked.pins.contains(&id) {
            self.acked.pins.push(id);
        }
    }

    /// The SDK did not queue the call: as a pace refusal, without a word.
    pub fn not_sent(&mut self, now: f64) {
        self.pending = None;
        self.retry_at = now + RETRY_S;
    }

    pub fn reply(&mut self, c: &Call, r: &Result<(), String>, now: f64) -> Outcome {
        if self.pending.as_ref() != Some(c) {
            return Outcome::Stale;
        }
        self.pending = None;
        match r {
            Ok(()) => {
                self.acked = c.choice.clone();
                self.refused = None;
                Outcome::Accepted
            }
            Err(e) if e == PACE => {
                self.retry_at = now + RETRY_S;
                Outcome::Paced
            }
            Err(e) => {
                if c.pin_at.is_none() {
                    self.refused = Some(c.choice.clone());
                }
                Outcome::Refused(e.clone())
            }
        }
    }
}

/// A click or Pin press on a throng figure: the figure's square and the click's ground point
/// (map m, clamped into the square), sent to the authority as `pin_at`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ThrongPick {
    pub row: crate::throng::Row,
    pub at: Vec2,
}

/// Identify the creature promoted by an accepted `pin_at` call: among those newly perceived (in
/// `now_seen` and not in `before`), prefer those inside `square` (if known), then pick the one
/// nearest `at` (ties by lower id, matching the authority's `heed::pick_at`).
pub fn find_picked(at: Vec2, square: Option<crate::throng::Row>, before: &[u32], now_seen: &[(u32, Vec2)]) -> Option<u32> {
    let fresh: Vec<(u32, Vec2)> = now_seen.iter().copied().filter(|(id, _)| !before.contains(id)).collect();
    if fresh.is_empty() {
        return None;
    }
    let nearest = |list: &[(u32, Vec2)]| {
        list.iter()
            .min_by(|a, b| a.1.distance(at).total_cmp(&b.1.distance(at)).then(a.0.cmp(&b.0)))
            .map(|(id, _)| *id)
    };
    if let Some(row) = square {
        let inside: Vec<(u32, Vec2)> = fresh.iter().copied().filter(|(_, p)| row.holds(*p)).collect();
        if !inside.is_empty() {
            return nearest(&inside);
        }
    }
    nearest(&fresh)
}

/// Pins asked for as they are by the live script (`heed:ID` or `heed:at:X,Y`, `live.rs`), not yet sent.
static ASKS: Mutex<Vec<u32>> = Mutex::new(Vec::new());
static ASKS_AT: Mutex<Vec<Vec2>> = Mutex::new(Vec::new());

/// The live script asks the authority to pin `id` as it is: sent with my other pins, past this
/// client's check that I perceive `id`, so the authority's own answer shows (a check of its
/// refusal words; the Pin key never sends someone I do not perceive).
pub fn ask(id: u32) {
    ASKS.lock().unwrap().push(id);
}

/// The live script asks the authority to pick out a throng member at `at` (map m) as it is, past
/// the client's check that a throng card stands there, so a refused `pin_at` can be tested.
pub fn ask_at(at: Vec2) {
    ASKS_AT.lock().unwrap().push(at);
}

/// State held while a `pin_at` call is in flight or waiting for its admitted row to arrive.
#[derive(Clone, Debug)]
struct PendingPick {
    at: Vec2,
    square: Option<crate::throng::Row>,
    before: Vec<u32>,
    until: f64,
}

/// Heed for players as this client holds it.
#[derive(Resource, Default)]
pub struct Heed {
    /// The world's laws let players heed and the set in place has my throng.
    pub on: bool,
    /// Whom I pin (in the order pinned) and my focus, as wanted here.
    pub pins: Vec<u32>,
    pub focus: Option<u32>,
    pub sender: Sender,
    /// A fifth pin warned about (whom, when, app s): a second press asks anyway.
    over: Option<(u32, f64)>,
    /// A fifth pin via throng click warned about (where, when, app s): a second click asks anyway.
    over_throng: Option<(Vec2, f64)>,
    /// A choice or `pin_at` to ask for as it is (the fifth pin, or a live script probe).
    force: Option<Call>,
    /// A throng card clicked, waiting to be sent as `pin_at`.
    pin_at: Option<ThrongPick>,
    /// Snapshot of perceived ids captured when the in-flight `pin_at` call was sent.
    in_flight_pick: Option<PendingPick>,
    /// An accepted `pin_at` waiting (if needed) for the newly admitted row to appear in `perceived`.
    awaiting_pick: Option<PendingPick>,
    /// The last creature id promoted and pinned via `pin_at`, for dumps.
    pub last_picked: Option<u32>,
    /// Pins I do not perceive now, since when (app s).
    gone: Vec<(u32, f64)>,
    /// The character the choice is for.
    owner: Option<u32>,
    replies: Arc<Mutex<Vec<(Call, Result<(), String>)>>>,
    /// The last calls and replies, for the dump (`ui` dump's `heed`).
    pub log: Vec<String>,
    /// Refusals shown, in the authority's words, for the dump.
    pub refusals: Vec<String>,
    /// Frozen HUD labels for currently pinned creatures: `id -> (look_key, is_known, label)`.
    /// Prevents twin-disambiguation from renaming an already-pinned stranger when other
    /// strangers enter or leave `perceived`, while still updating if their look changes or their
    /// real name is learned.
    pinned_labels: std::collections::BTreeMap<u32, (String, bool, String)>,
}

impl Heed {
    /// Sync frozen labels for `self.pins`: keep an existing frozen label as long as the pinned
    /// creature's look key and known-name flag have not changed, and drop entries for unpinned ids.
    pub fn sync_pin_labels(&mut self, looks: &crate::looks::Looks) {
        self.sync_pin_labels_with(|id| looks.short(id).map(|s| (looks.look_key(id).to_string(), looks.is_known(id), s.to_string())));
    }

    /// Pure core of [`Self::sync_pin_labels`] for unit testing.
    pub fn sync_pin_labels_with(&mut self, lookup: impl Fn(u32) -> Option<(String, bool, String)>) {
        self.pinned_labels.retain(|id, _| self.pins.contains(id));
        for &id in &self.pins {
            let Some((key, known, label)) = lookup(id) else { continue };
            let keep = self.pinned_labels.get(&id).is_some_and(|(k, kn, _)| *k == key && *kn == known);
            if !keep {
                self.pinned_labels.insert(id, (key, known, label));
            }
        }
    }

    /// The stable label to show for a pinned creature (frozen at pin time unless its look changes
    /// or its real name is learned), falling back to `looks.short(id)`.
    pub fn pin_label<'a>(&'a self, id: u32, looks: &'a crate::looks::Looks) -> Option<&'a str> {
        self.pinned_labels.get(&id).map(|(_, _, s)| s.as_str()).or_else(|| looks.short(id))
    }

    /// Ground rings (`throng.rs`): each pin, and my focus (true).
    pub fn marks(&self) -> Vec<(u32, bool)> {
        let mut v: Vec<(u32, bool)> = self.pins.iter().filter(|p| Some(**p) != self.focus).map(|p| (*p, false)).collect();
        v.extend(self.focus.map(|f| (f, true)));
        v
    }

    fn reset(&mut self) {
        let on = self.on;
        *self = Heed { on, replies: Arc::default(), ..Default::default() };
    }

    fn note(&mut self, s: String) {
        info!("heed: {s}");
        self.log.push(s);
        let n = self.log.len();
        if n > 24 {
            self.log.drain(..n - 24);
        }
    }

    pub fn json(&self) -> serde_json::Value {
        serde_json::json!({
            "on": self.on, "pins": self.pins, "focus": self.focus,
            "last_picked": self.last_picked,
            "acked": {"pins": self.sender.acked.pins, "focus": self.sender.acked.focus},
            "pending": self.sender.pending.as_ref().map(|c| serde_json::json!({
                "pins": c.choice.pins, "focus": c.choice.focus,
                "pin_at": c.pin_at.map(|p| [p.x, p.y]),
            })),
            "out_of_sight": self.gone.iter().map(|(id, _)| *id).collect::<Vec<_>>(),
            "refusals": self.refusals, "log": self.log,
        })
    }
}

pub struct HeedPlugin;

impl Plugin for HeedPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Heed>().add_systems(Update, input.in_set(crate::phase::Phase::Input).after(crate::combat::input).after(crate::combat::pick));
    }
}

fn toast(verbs: &mut crate::verbs::Verbs, text: &str, ok: Option<bool>, now: f64) {
    verbs.toasts.push(crate::verbs::Toast { text: text.to_string(), ok, at: now });
}

/// Keys, throng clicks, focus, replies and the call, each frame.
#[allow(clippy::too_many_arguments)]
fn input(
    net: NonSend<Net>,
    scene: NonSend<crate::world::Scene>,
    (keys, binds, controls, ui, pointer): (Res<ButtonInput<KeyCode>>, Res<crate::keys::Binds>, Res<crate::controls::Input>, Res<crate::hud::UiWants>, Res<crate::pointer::Pointer>),
    (pick, throng): (Res<crate::pick::Pick>, Res<crate::throng::Throng>),
    (talk, combat, looks): (Option<Res<crate::talk::Talk>>, Res<crate::combat::Combat>, Res<crate::looks::Looks>),
    mut verbs: ResMut<crate::verbs::Verbs>,
    time: Res<Time>,
    mut h: ResMut<Heed>,
) {
    let now = time.elapsed_secs_f64();
    let on = net.conn.as_ref().is_some_and(|c| c.throng_table());
    if on != h.on {
        info!("heed: players heed {on}");
        h.on = on;
        h.reset();
    }
    if !on {
        return;
    }
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else {
        if h.owner.is_some() {
            h.reset();
        }
        return;
    };
    if h.owner != Some(me) {
        h.reset();
        h.owner = Some(me);
    }
    let perceived: Vec<u32> = crate::net::characters(conn).into_iter().map(|c| c.id).filter(|id| *id != me).collect();
    let seen = |id: u32| perceived.contains(&id);
    let name = |id: u32| looks.of(id).map(String::from).or_else(|| crate::net::find_character(conn, id).map(|c| c.label)).unwrap_or_else(|| format!("#{id}"));
    let positions = || -> Vec<(u32, Vec2)> {
        perceived
            .iter()
            .filter_map(|&id| {
                crate::net::find_motion(conn, id)
                    .map(|m| (id, Vec2::new(m.x, m.y)))
                    .or_else(|| scene.shown.get(&id).map(|(p, _)| (id, *p)))
            })
            .collect()
    };

    // Replies first, so a refusal shows the frame it comes.
    let replies: Vec<(Call, Result<(), String>)> = std::mem::take(&mut *h.replies.lock().unwrap());
    for (c, r) in replies {
        let flight = h.in_flight_pick.take();
        match h.sender.reply(&c, &r, now) {
            Outcome::Accepted => {
                if let Some(at) = c.pin_at {
                    h.note(format!("accepted pins {:?} focus {:?} pin_at ({:.1}, {:.1})", c.choice.pins, c.choice.focus, at.x, at.y));
                    if let Some(mut pp) = flight {
                        pp.until = now + 1.5;
                        h.awaiting_pick = Some(pp);
                    }
                } else {
                    h.note(format!("accepted pins {:?} focus {:?}", c.choice.pins, c.choice.focus));
                }
            }
            Outcome::Paced => {
                h.note(format!("refused (paced): {PACE}; pins {:?} focus {:?} pin_at {:?}", c.choice.pins, c.choice.focus, c.pin_at));
                toast(&mut verbs, PACE, Some(false), now);
                h.refusals.push(PACE.to_string());
                if let (Some(at), Some(pp)) = (c.pin_at, flight) {
                    if let Some(row) = pp.square {
                        h.pin_at.get_or_insert(ThrongPick { row, at });
                    }
                }
            }
            Outcome::Refused(e) => {
                h.note(format!("refused: {e}; pins {:?} focus {:?} pin_at {:?}", c.choice.pins, c.choice.focus, c.pin_at));
                toast(&mut verbs, &e, Some(false), now);
                h.refusals.push(e);
                // The pins as the authority holds them: what it refused is not kept here.
                h.pins = h.sender.acked.pins.clone();
            }
            Outcome::Stale => {}
        }
    }
    if h.refusals.len() > 12 {
        let n = h.refusals.len();
        h.refusals.drain(..n - 12);
    }

    // Resolve a recently accepted `pin_at` into its admitted creature id.
    if let Some(pp) = h.awaiting_pick.clone() {
        let now_seen = positions();
        if let Some(picked) = find_picked(pp.at, pp.square, &pp.before, &now_seen) {
            h.awaiting_pick = None;
            if !h.pins.contains(&picked) && h.pins.len() < MAX_PINS {
                h.pins.push(picked);
            }
            h.sender.record_picked(picked);
            h.last_picked = Some(picked);
            h.note(format!("picked #{picked} ({}) from throng at ({:.1}, {:.1})", name(picked), pp.at.x, pp.at.y));
        } else if now >= pp.until {
            h.awaiting_pick = None;
            h.note(format!("pin_at ({:.1}, {:.1}) accepted, no newly perceived id arrived", pp.at.x, pp.at.y));
        }
    }

    // Pins I no longer perceive: kept a while (not sent), then let go.
    let pins = h.pins.clone();
    h.gone.retain(|(id, _)| pins.contains(id) && !seen(*id));
    for p in &pins {
        if !seen(*p) && !h.gone.iter().any(|(id, _)| id == p) {
            h.gone.push((*p, now));
        }
    }
    let lost: Vec<u32> = h.gone.iter().filter(|(_, t)| now - t > GONE_S).map(|(id, _)| *id).collect();
    if !lost.is_empty() {
        h.pins.retain(|p| !lost.contains(p));
        h.gone.retain(|(id, _)| !lost.contains(id));
        h.note(format!("let go of {lost:?}: out of sight {GONE_S} s"));
    }

    // Helper: queue a throng click (`pin_at`), respecting the 4-pin warning.
    let mut queue_throng = |h: &mut Heed, row: crate::throng::Row, at: Vec2, via: &str| {
        if h.pins.len() >= MAX_PINS {
            if h.over_throng.is_some_and(|(_, t)| now - t < OVER_S) {
                h.over_throng = None;
                let mut four = h.sender.acked.seen(seen);
                let extra: Vec<u32> = h.pins.iter().copied().filter(|p| seen(*p) && !four.pins.contains(p)).collect();
                four.pins.extend(extra);
                four.focus = h.focus.filter(|f| seen(*f));
                h.note(format!("a fifth pin via throng ({via}) at ({:.1}, {:.1})", at.x, at.y));
                h.force = Some(Call::with_pin_at(four, at));
            } else {
                h.over_throng = Some((at, now));
                h.note(format!("a fifth pin warned (throng {via}) at ({:.1}, {:.1})", at.x, at.y));
                toast(&mut verbs, &format!("You keep track of {MAX_PINS} already. Click again to ask for a fifth."), None, now);
            }
        } else {
            h.over = None;
            h.over_throng = None;
            h.pin_at = Some(ThrongPick { row, at });
            h.note(format!("throng {via} at ({:.1}, {:.1}) in cell ({}, {}) size {}", at.x, at.y, row.cx, row.cy, row.size));
        }
    };

    // The keys and throng clicks.
    let free = !controls.demo && !controls.chat_open && !ui.keyboard;
    let free_mouse = free && !ui.over() && !ui.menu;
    let under_individual = pick.under.filter(|id| seen(*id));

    if free && binds.just_pressed(crate::keys::Act::ClearPins, &keys) && !h.pins.is_empty() {
        h.pins.clear();
        h.over = None;
        h.over_throng = None;
        h.pin_at = None;
        h.note("cleared every pin".into());
    }

    // Left-click (tap) on a throng card sends `pin_at`.
    if free_mouse && pointer.tapped && under_individual.is_none() {
        if let Some((row, at)) = throng.under {
            queue_throng(&mut h, row, at, "click");
        }
    }

    if free && binds.just_pressed(crate::keys::Act::Pin, &keys) {
        match under_individual {
            Some(id) => {
                let mut pins = h.pins.clone();
                match toggle(&mut pins, id) {
                    Toggle::Added => {
                        h.over = None;
                        h.over_throng = None;
                        h.note(format!("pin #{id} ({})", name(id)));
                    }
                    Toggle::Removed => {
                        h.over = None;
                        h.over_throng = None;
                        h.note(format!("unpin #{id} ({})", name(id)));
                    }
                    Toggle::Full if h.over.is_some_and(|(o, t)| o == id && now - t < OVER_S) => {
                        // Asked twice: the authority answers.
                        h.over = None;
                        let mut five = h.sender.acked.seen(seen);
                        let extra: Vec<u32> = h.pins.iter().copied().filter(|p| seen(*p) && !five.pins.contains(p)).collect();
                        five.pins.extend(extra);
                        five.pins.push(id);
                        h.note(format!("a fifth pin asked for: #{id}"));
                        h.force = Some(Call::of_choice(five));
                    }
                    Toggle::Full => {
                        h.over = Some((id, now));
                        let key = binds.first(crate::keys::Act::Pin);
                        h.note(format!("a fifth pin warned: #{id}"));
                        toast(&mut verbs, &format!("You keep track of {MAX_PINS} already. {key} again to ask for a fifth."), None, now);
                    }
                }
                h.pins = pins;
            }
            None => {
                if let Some((row, at)) = throng.under {
                    queue_throng(&mut h, row, at, "pin");
                }
            }
        }
    }

    // The live script's asks (`heed:ID` and `heed:at:X,Y`): sent as they are.
    for id in std::mem::take(&mut *ASKS.lock().unwrap()) {
        let mut c = h.sender.acked.seen(seen);
        let extra: Vec<u32> = h.pins.iter().copied().filter(|p| seen(*p) && !c.pins.contains(p)).collect();
        c.pins.extend(extra);
        if !c.pins.contains(&id) {
            c.pins.push(id);
        }
        c.focus = h.focus;
        h.note(format!("asked for #{id} as a pin as it is (live script)"));
        h.force = Some(Call::of_choice(c));
    }
    for at in std::mem::take(&mut *ASKS_AT.lock().unwrap()) {
        let mut c = h.sender.acked.seen(seen);
        let extra: Vec<u32> = h.pins.iter().copied().filter(|p| seen(*p) && !c.pins.contains(p)).collect();
        c.pins.extend(extra);
        c.focus = h.focus.filter(|f| seen(*f));
        h.note(format!("asked for pin_at ({:.1}, {:.1}) as it is (live script)", at.x, at.y));
        h.force = Some(Call::with_pin_at(c, at));
    }

    // Focus: whom the open box speaks to, else my last aimed skill's creature.
    let talk_to = talk.as_ref().filter(|_| controls.chat_open).and_then(|t| t.to);
    let aimed = combat.aimed.filter(|(_, at)| scene.now_ms - at < FOCUS_HOLD_MS).map(|(id, _)| id);
    let focus = talk_to.or(aimed).filter(|id| seen(*id));
    if focus != h.focus {
        let was = h.focus;
        h.note(format!("focus {was:?} → {focus:?}"));
        h.focus = focus;
    }

    // Wait for a recently accepted `pin_at` to resolve before sending another call that would
    // overwrite the newly pinned creature on the authority.
    if h.awaiting_pick.is_some() {
        return;
    }

    // The call.
    let want = Choice { pins: h.pins.clone(), focus: h.focus };
    let force = h.force.clone();
    let pending_pick = h.pin_at;
    let Some(c) = h.sender.next(&want, seen, now, force.as_ref(), pending_pick.map(|p| p.at)) else { return };
    if force.is_some() {
        h.force = None;
    } else if pending_pick.is_some() && c.pin_at.is_some() {
        h.pin_at = None;
    }
    let square = pending_pick.filter(|p| c.pin_at == Some(p.at)).map(|p| p.row);
    let args = {
        let c = c.clone();
        move || serde_json::json!({"input": {"pins": c.choice.pins, "focus": c.choice.focus, "pin_at": c.pin_at.map(|p| serde_json::json!({"x": p.x, "y": p.y}))}})
    };
    let report = net.on_reply("heed", "human_heed", args);
    let (replies, cc) = (h.replies.clone(), c.clone());
    let r = conn.reducers.human_heed_then(c.to_input(), move |ctx, res| {
        let mine = match &res {
            Ok(Ok(())) => Ok(()),
            Ok(Err(e)) => Err(e.clone()),
            // The host failed it: tried again, as a pace refusal.
            Err(_) => Err(PACE.to_string()),
        };
        replies.lock().unwrap().push((cc, mine));
        report(ctx, res);
    });
    if r.is_err() {
        h.sender.not_sent(now);
        if let (Some(at), Some(row)) = (c.pin_at, square) {
            h.pin_at.get_or_insert(ThrongPick { row, at });
        }
    } else {
        if let Some(at) = c.pin_at {
            h.note(format!("sent pins {:?} focus {:?} pin_at ({:.1}, {:.1})", c.choice.pins, c.choice.focus, at.x, at.y));
            h.in_flight_pick = Some(PendingPick { at, square, before: perceived, until: now + 1.5 });
        } else {
            h.note(format!("sent pins {:?} focus {:?}", c.choice.pins, c.choice.focus));
        }
        h.sender.sent(c, now);
    }
    net.report("heed", r);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ch(pins: &[u32], focus: Option<u32>) -> Choice {
        Choice { pins: pins.to_vec(), focus }
    }

    fn call(pins: &[u32], focus: Option<u32>) -> Call {
        Call::of_choice(ch(pins, focus))
    }

    #[test]
    fn pins_toggle_and_stop_at_four() {
        let mut p = Vec::new();
        for id in [3, 5, 7, 9] {
            assert_eq!(toggle(&mut p, id), Toggle::Added);
        }
        assert_eq!(toggle(&mut p, 11), Toggle::Full);
        assert_eq!(p, vec![3, 5, 7, 9]);
        assert_eq!(toggle(&mut p, 5), Toggle::Removed);
        assert_eq!(p, vec![3, 7, 9]);
        assert_eq!(toggle(&mut p, 11), Toggle::Added);
        assert_eq!(p, vec![3, 7, 9, 11]);
    }

    #[test]
    fn calls_are_coalesced_paced_and_never_change_nothing() {
        let all = |_: u32| true;
        let mut s = Sender::default();
        // Nothing wanted, nothing held: no call.
        assert_eq!(s.next(&Choice::default(), all, 0.0, None, None), None);
        // A change: one call; none while it is in flight, whatever changes meanwhile.
        let a = call(&[3], None);
        assert_eq!(s.next(&a.choice, all, 0.0, None, None), Some(a.clone()));
        s.sent(a.clone(), 0.0);
        assert_eq!(s.next(&ch(&[3, 5], Some(7)), all, 1.0, None, None), None);
        assert_eq!(s.reply(&a, &Ok(()), 0.05), Outcome::Accepted);
        assert_eq!(s.acked, a.choice);
        // The coalesced latest, once the spacing allows (not at 0.2 s, at 0.3 s).
        let b = call(&[3, 5], Some(7));
        assert_eq!(s.next(&b.choice, all, 0.2, None, None), None);
        assert_eq!(s.next(&b.choice, all, SPACING_S, None, None), Some(b.clone()));
        s.sent(b.clone(), SPACING_S);
        // Paced: asked again after a short wait, not before.
        assert_eq!(s.reply(&b, &Err(PACE.into()), 0.35), Outcome::Paced);
        assert_eq!(s.next(&b.choice, all, 0.5, None, None), None);
        assert_eq!(s.next(&b.choice, all, 0.8, None, None), Some(b.clone()));
        s.sent(b.clone(), 0.8);
        assert_eq!(s.reply(&b, &Ok(()), 0.85), Outcome::Accepted);
        // Held: no call.
        assert_eq!(s.next(&b.choice, all, 5.0, None, None), None);
        // A stale reply changes nothing.
        assert_eq!(s.reply(&a, &Ok(()), 5.0), Outcome::Stale);
        assert_eq!(s.acked, b.choice);
        // Clearing everything is a call (empty pins and no focus clear the row).
        assert_eq!(s.next(&Choice::default(), all, 5.0, None, None), Some(Call::of_choice(Choice::default())));
    }

    #[test]
    fn only_the_perceived_go_in_a_call_and_a_pin_out_of_sight_needs_none() {
        let mut s = Sender::default();
        let held = call(&[3, 5], Some(5));
        s.sent(held.clone(), 0.0);
        s.reply(&held, &Ok(()), 0.0);
        // #3 out of sight: nothing to send (the authority's row may keep it).
        let seen = |id: u32| id != 3;
        assert_eq!(s.next(&held.choice, seen, 1.0, None, None), None);
        // A new pin then: the call carries only those I perceive.
        assert_eq!(s.next(&ch(&[3, 5, 8], Some(5)), seen, 1.0, None, None), Some(call(&[5, 8], Some(5))));
        // Focus on someone gone: dropped from the call.
        assert_eq!(s.next(&ch(&[5], Some(3)), seen, 1.0, None, None), Some(call(&[5], None)));
    }

    #[test]
    fn a_refusal_is_not_asked_again_unchanged_but_a_forced_fifth_is_sent() {
        let all = |_: u32| true;
        let mut s = Sender::default();
        let a = call(&[], Some(9));
        s.sent(a.clone(), 0.0);
        let unseen = "You can only keep track of someone you can see now.";
        assert_eq!(s.reply(&a, &Err(unseen.into()), 0.1), Outcome::Refused(unseen.into()));
        assert_eq!(s.next(&a.choice, all, 2.0, None, None), None);
        assert_eq!(s.next(&ch(&[], Some(10)), all, 2.0, None, None), Some(call(&[], Some(10))));
        // The fifth: sent as asked, whatever is held.
        let five = call(&[1, 2, 3, 4, 5], None);
        assert_eq!(s.next(&Choice::default(), all, 2.0, Some(&five), None), Some(five.clone()));
        // Not while a call is in flight, nor inside the spacing.
        s.sent(five.clone(), 2.0);
        assert_eq!(s.next(&Choice::default(), all, 3.0, Some(&five), None), None);
        let max = "You can keep at most 4 others pinned at once.";
        assert_eq!(s.reply(&five, &Err(max.into()), 2.1), Outcome::Refused(max.into()));
        assert_eq!(s.acked, Choice::default());
    }

    #[test]
    fn pin_at_carries_current_pins_focus_and_ground_point_and_records_pick() {
        let all = |_: u32| true;
        let mut s = Sender::default();
        let base = ch(&[3, 5], Some(5));
        let c0 = Call::of_choice(base.clone());
        s.sent(c0.clone(), 0.0);
        assert_eq!(s.reply(&c0, &Ok(()), 0.05), Outcome::Accepted);
        // Clicking a throng card sends `pin_at` keeping current pins and focus (after spacing).
        let pt = Vec2::new(63.2, 64.8);
        assert_eq!(s.next(&base, all, 0.2, None, Some(pt)), None);
        let c1 = s.next(&base, all, SPACING_S, None, Some(pt)).unwrap();
        assert_eq!(c1, Call::with_pin_at(base.clone(), pt));
        let input = c1.to_input();
        assert_eq!(input.pins, vec![3, 5]);
        assert_eq!(input.focus, Some(5));
        let pa = input.pin_at.unwrap();
        assert!((pa.x - 63.2).abs() < 1e-5 && (pa.y - 64.8).abs() < 1e-5);
        s.sent(c1.clone(), SPACING_S);
        assert_eq!(s.reply(&c1, &Ok(()), 0.35), Outcome::Accepted);
        // Recording the promoted id updates acked so no redundant call is sent.
        s.record_picked(42);
        assert_eq!(s.acked.pins, vec![3, 5, 42]);
        assert_eq!(s.next(&ch(&[3, 5, 42], Some(5)), all, 1.0, None, None), None);
        // A refused `pin_at` does not poison later calls or choices.
        let c2 = s.next(&ch(&[3, 5, 42], Some(5)), all, 1.0, None, Some(Vec2::new(1.0, 2.0))).unwrap();
        s.sent(c2.clone(), 1.0);
        let empty = "There is no one in the throng there to pick out.";
        assert_eq!(s.reply(&c2, &Err(empty.into()), 1.05), Outcome::Refused(empty.into()));
        assert_eq!(s.refused, None);
        assert_eq!(s.acked.pins, vec![3, 5, 42]);
    }

    #[test]
    fn find_picked_chooses_the_newly_perceived_member_nearest_the_click_in_square() {
        use crate::throng::{Row, STILL};
        let row = Row::of(&living_bindings::SeenThrong {
            id: 1, viewer: spacetimedb_sdk::Identity::ZERO, cell: (10 << 16) | 10, size: 1,
            count: 5, spread: 4, heading: STILL, moving: 0, fighting: 0, kinds: 1,
            colour_a: 255, colour_a_count: 0, colour_b: 255, colour_b_count: 0, colour_c: 255, colour_c_count: 0,
            people: 5, wolves: 0, deer: 0, others: 0, centre_x: 3, centre_y: 3,
            cloth_yellow: 0, cloth_black: 0, cloth_green: 0, cloth_tan: 0, cloth_blue: 0, cloth_red: 0, cloth_cream: 0, cloth_navy: 0, cloth_purple: 0, cloth_grey: 0,
        });
        let click = Vec2::new(63.0, 63.0);
        let before = [7u32, 4u32];
        // #7 and #4 were already perceived; #19 is inside the square and nearest; #22 is closer
        // to the corner outside; #25 is inside but farther.
        let seen = [
            (7, Vec2::new(63.0, 63.0)),
            (4, Vec2::new(62.5, 62.5)),
            (19, Vec2::new(63.4, 63.2)),
            (25, Vec2::new(61.0, 61.0)),
            (22, Vec2::new(66.1, 63.0)),
        ];
        assert_eq!(find_picked(click, Some(row), &before, &seen), Some(19));
        // Tie in distance breaks by lower id.
        assert_eq!(find_picked(click, Some(row), &before, &[(30, Vec2::new(64.0, 63.0)), (12, Vec2::new(62.0, 63.0))]), Some(12));
        // None newly perceived: None.
        assert_eq!(find_picked(click, Some(row), &before, &[(7, click), (4, click)]), None);
        // Moved just outside the square by the time it arrived: falls back to nearest fresh.
        assert_eq!(find_picked(click, Some(row), &before, &[(22, Vec2::new(66.1, 63.0)), (99, Vec2::new(90.0, 90.0))]), Some(22));
    }

    #[test]
    fn marks_ring_each_pin_and_the_focus_once() {
        let h = Heed { pins: vec![3, 5], focus: Some(5), ..Default::default() };
        assert_eq!(h.marks(), vec![(3, false), (5, true)]);
    }

    #[test]
    fn pinned_labels_stay_stable_across_twin_disambiguation_until_look_or_name_changes() {
        let mut h = Heed { pins: vec![183], ..Default::default() };
        let empty = crate::looks::Looks::default();
        // Initial pin freezes "a stranger in dark grey" for look key "".
        h.sync_pin_labels_with(|id| (id == 183).then(|| ("".into(), false, "a stranger in dark grey".into())));
        assert_eq!(h.pin_label(183, &empty), Some("a stranger in dark grey"));
        // Twin-disambiguation changes looks.short to "a stranger in dark grey and orange", same look key -> frozen label stays!
        h.sync_pin_labels_with(|id| (id == 183).then(|| ("".into(), false, "a stranger in dark grey and orange".into())));
        assert_eq!(h.pin_label(183, &empty), Some("a stranger in dark grey"));
        // Look key actually changes -> label updates.
        h.sync_pin_labels_with(|id| (id == 183).then(|| ("lk_new".into(), false, "a man in a red coat".into())));
        assert_eq!(h.pin_label(183, &empty), Some("a man in a red coat"));
        // Real name learned -> label updates.
        h.sync_pin_labels_with(|id| (id == 183).then(|| ("lk_new".into(), true, "Bram".into())));
        assert_eq!(h.pin_label(183, &empty), Some("Bram"));
        // Unpin drops frozen entry.
        h.pins.clear();
        h.sync_pin_labels_with(|_| None);
        assert_eq!(h.pin_label(183, &empty), None);
    }
}
