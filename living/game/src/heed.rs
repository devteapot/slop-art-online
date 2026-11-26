//! Heed for players, the client's side (docs/ATTENTION_BUDGET.md, "Built: the player side" and
//! v2.1 point 6): whom I keep track of. Only while the world's laws let players heed (`heed_on`
//! and `heed_players`: the set in place has `seen_throng`, `net::throng`); off, nothing here reads
//! a key, sends a call or draws anything.
//!
//! - **Pins:** the Pin key (T) on whoever the cursor points at (`pick.rs`, the pick the plates,
//!   Enter and combat use) pins them, or unpins them if pinned; Clear (Y) unpins everyone. At most
//!   [`MAX_PINS`]: a fifth is warned about first, and asked for only on a second press (the
//!   authority then refuses it in its own words).
//! - **A throng figure:** the throng has no ids, so a figure cannot name anyone. Until the
//!   authority takes a position pin (`pin_at`, coming), the Pin key on a figure pins the
//!   individual I perceive nearest it within its square ([`in_throng`]); with none, it says so.
//!   When `pin_at` lands, [`ThrongPick`] is what is sent instead.
//! - **Focus** follows my current target: whom the open text box speaks to, else the creature my
//!   last creature-aimed skill went to (held [`FOCUS_HOLD_MS`]). Hover stays on the client.
//! - **The call:** `human_heed(HeedInput { pins, focus })` carries the whole choice. Changes are
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

/// The calls: what the authority holds as far as I know, the one in flight, and the pace.
#[derive(Default, Debug)]
pub struct Sender {
    /// My last accepted choice (the authority's `heed_choice` row, as far as I know).
    pub acked: Choice,
    pub pending: Option<Choice>,
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
    /// The call to send now, if any: `want` as `seen` allows, when it differs from what the
    /// authority holds (as `seen` allows: a pin gone from sight needs no call), was not refused
    /// as it is, no call is in flight and the pace allows. `force`: a choice asked for as it is
    /// (a fifth pin on a second press), whatever it changes.
    pub fn next(&self, want: &Choice, seen: impl Fn(u32) -> bool + Copy, now: f64, force: Option<&Choice>) -> Option<Choice> {
        if self.pending.is_some() || now < self.retry_at || self.last_sent.is_some_and(|t| now - t < SPACING_S) {
            return None;
        }
        if let Some(f) = force {
            return Some(f.clone());
        }
        let w = want.seen(seen);
        (w != self.acked.seen(seen) && self.refused.as_ref() != Some(&w)).then_some(w)
    }

    pub fn sent(&mut self, c: Choice, now: f64) {
        self.pending = Some(c);
        self.last_sent = Some(now);
    }

    /// The SDK did not queue the call: as a pace refusal, without a word.
    pub fn not_sent(&mut self, now: f64) {
        self.pending = None;
        self.retry_at = now + RETRY_S;
    }

    pub fn reply(&mut self, c: &Choice, r: &Result<(), String>, now: f64) -> Outcome {
        if self.pending.as_ref() != Some(c) {
            return Outcome::Stale;
        }
        self.pending = None;
        match r {
            Ok(()) => {
                self.acked = c.clone();
                self.refused = None;
                Outcome::Accepted
            }
            Err(e) if e == PACE => {
                self.retry_at = now + RETRY_S;
                Outcome::Paced
            }
            Err(e) => {
                self.refused = Some(c.clone());
                Outcome::Refused(e.clone())
            }
        }
    }
}

/// A Pin press on a throng figure: the figure's square and where it stands (map m). Sent as a
/// position pin once the authority takes one (`pin_at`); until then resolved by [`in_throng`].
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ThrongPick {
    pub row: crate::throng::Row,
    pub at: Vec2,
}

/// Until the authority takes a position pin: the individual I perceive nearest a throng figure,
/// within the figure's square (or 1.5 m of the figure), if any. Never a throng member: those have
/// no id here.
pub fn in_throng(pick: &ThrongPick, individuals: &[(u32, Vec2)]) -> Option<u32> {
    individuals
        .iter()
        .filter(|(_, p)| pick.row.holds(*p) || p.distance(pick.at) < 1.5)
        .min_by(|a, b| a.1.distance(pick.at).total_cmp(&b.1.distance(pick.at)).then(a.0.cmp(&b.0)))
        .map(|(id, _)| *id)
}

/// Pins asked for as they are by the live script (`heed:ID`, `live.rs`), not yet sent.
static ASKS: Mutex<Vec<u32>> = Mutex::new(Vec::new());

/// The live script asks the authority to pin `id` as it is: sent with my other pins, past this
/// client's check that I perceive `id`, so the authority's own answer shows (a check of its
/// refusal words; the Pin key never sends someone I do not perceive).
pub fn ask(id: u32) {
    ASKS.lock().unwrap().push(id);
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
    /// A choice to ask for as it is (the fifth).
    force: Option<Choice>,
    /// Pins I do not perceive now, since when (app s).
    gone: Vec<(u32, f64)>,
    /// The character the choice is for.
    owner: Option<u32>,
    replies: Arc<Mutex<Vec<(Choice, Result<(), String>)>>>,
    /// The last calls and replies, for the dump (`ui` dump's `heed`).
    pub log: Vec<String>,
    /// Refusals shown, in the authority's words, for the dump.
    pub refusals: Vec<String>,
}

impl Heed {
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
            "acked": {"pins": self.sender.acked.pins, "focus": self.sender.acked.focus},
            "pending": self.sender.pending.as_ref().map(|c| serde_json::json!({"pins": c.pins, "focus": c.focus})),
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

/// Keys, focus, replies and the call, each frame.
#[allow(clippy::too_many_arguments)]
fn input(
    net: NonSend<Net>,
    scene: NonSend<crate::world::Scene>,
    (keys, binds, controls, ui): (Res<ButtonInput<KeyCode>>, Res<crate::keys::Binds>, Res<crate::controls::Input>, Res<crate::hud::UiWants>),
    (pick, cam, throng): (Res<crate::pick::Pick>, Res<crate::camera::Cam>, Res<crate::throng::Throng>),
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

    // Replies first, so a refusal shows the frame it comes.
    let replies: Vec<(Choice, Result<(), String>)> = std::mem::take(&mut *h.replies.lock().unwrap());
    for (c, r) in replies {
        match h.sender.reply(&c, &r, now) {
            Outcome::Accepted => h.note(format!("accepted pins {:?} focus {:?}", c.pins, c.focus)),
            Outcome::Paced => {
                h.note(format!("refused (paced): {PACE}; pins {:?} focus {:?}", c.pins, c.focus));
                toast(&mut verbs, PACE, Some(false), now);
                h.refusals.push(PACE.to_string());
            }
            Outcome::Refused(e) => {
                h.note(format!("refused: {e}; pins {:?} focus {:?}", c.pins, c.focus));
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

    // The keys.
    let free = !controls.demo && !controls.chat_open && !ui.keyboard;
    if free && binds.just_pressed(crate::keys::Act::ClearPins, &keys) && !h.pins.is_empty() {
        h.pins.clear();
        h.over = None;
        h.note("cleared every pin".into());
    }
    if free && binds.just_pressed(crate::keys::Act::Pin, &keys) {
        let under = pick.under.filter(|id| seen(*id));
        let who = match under {
            Some(id) => Some(id),
            None => {
                let ground = cam.cursor_ground.map(|g| Vec2::new(g.x, g.z));
                match ground.and_then(|g| throng.card_at(g)) {
                    Some((row, at)) => {
                        let tp = ThrongPick { row, at };
                        let individuals: Vec<(u32, Vec2)> = perceived.iter().filter_map(|id| scene.shown.get(id).map(|(p, _)| (*id, *p))).collect();
                        let got = in_throng(&tp, &individuals);
                        h.note(format!("a throng figure at ({:.1}, {:.1}) in cell ({}, {}) size {}: {}", at.x, at.y, row.cx, row.cy, row.size, got.map_or("no individual near it".to_string(), |id| format!("the nearest individual, #{id}"))));
                        if got.is_none() {
                            toast(&mut verbs, "No one there you can pick out of the throng yet.", None, now);
                        }
                        got
                    }
                    None => None,
                }
            }
        };
        if let Some(id) = who {
            let mut pins = h.pins.clone();
            match toggle(&mut pins, id) {
                Toggle::Added => {
                    h.over = None;
                    h.note(format!("pin #{id} ({})", name(id)));
                }
                Toggle::Removed => {
                    h.over = None;
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
                    h.force = Some(five);
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
    }

    // The live script's asks (`heed:ID`): sent as they are.
    for id in std::mem::take(&mut *ASKS.lock().unwrap()) {
        let mut c = h.sender.acked.seen(seen);
        let extra: Vec<u32> = h.pins.iter().copied().filter(|p| seen(*p) && !c.pins.contains(p)).collect();
        c.pins.extend(extra);
        if !c.pins.contains(&id) {
            c.pins.push(id);
        }
        c.focus = h.focus;
        h.note(format!("asked for #{id} as a pin as it is (live script)"));
        h.force = Some(c);
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

    // The call.
    let want = Choice { pins: h.pins.clone(), focus: h.focus };
    let force = h.force.clone();
    let Some(c) = h.sender.next(&want, seen, now, force.as_ref()) else { return };
    h.force = None;
    let args = { let c = c.clone(); move || serde_json::json!({"input": {"pins": c.pins, "focus": c.focus}}) };
    let report = net.on_reply("heed", "human_heed", args);
    let (replies, cc) = (h.replies.clone(), c.clone());
    let r = conn.reducers.human_heed_then(HeedInput { pins: c.pins.clone(), focus: c.focus }, move |ctx, res| {
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
    } else {
        h.note(format!("sent pins {:?} focus {:?}", c.pins, c.focus));
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
        assert_eq!(s.next(&Choice::default(), all, 0.0, None), None);
        // A change: one call; none while it is in flight, whatever changes meanwhile.
        let a = ch(&[3], None);
        assert_eq!(s.next(&a, all, 0.0, None), Some(a.clone()));
        s.sent(a.clone(), 0.0);
        assert_eq!(s.next(&ch(&[3, 5], Some(7)), all, 1.0, None), None);
        assert_eq!(s.reply(&a, &Ok(()), 0.05), Outcome::Accepted);
        assert_eq!(s.acked, a);
        // The coalesced latest, once the spacing allows (not at 0.2 s, at 0.3 s).
        let b = ch(&[3, 5], Some(7));
        assert_eq!(s.next(&b, all, 0.2, None), None);
        assert_eq!(s.next(&b, all, SPACING_S, None), Some(b.clone()));
        s.sent(b.clone(), SPACING_S);
        // Paced: asked again after a short wait, not before.
        assert_eq!(s.reply(&b, &Err(PACE.into()), 0.35), Outcome::Paced);
        assert_eq!(s.next(&b, all, 0.5, None), None);
        assert_eq!(s.next(&b, all, 0.8, None), Some(b.clone()));
        s.sent(b.clone(), 0.8);
        assert_eq!(s.reply(&b, &Ok(()), 0.85), Outcome::Accepted);
        // Held: no call.
        assert_eq!(s.next(&b, all, 5.0, None), None);
        // A stale reply changes nothing.
        assert_eq!(s.reply(&a, &Ok(()), 5.0), Outcome::Stale);
        assert_eq!(s.acked, b);
        // Clearing everything is a call (empty pins and no focus clear the row).
        assert_eq!(s.next(&Choice::default(), all, 5.0, None), Some(Choice::default()));
    }

    #[test]
    fn only_the_perceived_go_in_a_call_and_a_pin_out_of_sight_needs_none() {
        let mut s = Sender::default();
        let held = ch(&[3, 5], Some(5));
        s.sent(held.clone(), 0.0);
        s.reply(&held, &Ok(()), 0.0);
        // #3 out of sight: nothing to send (the authority's row may keep it).
        let seen = |id: u32| id != 3;
        assert_eq!(s.next(&held, seen, 1.0, None), None);
        // A new pin then: the call carries only those I perceive.
        assert_eq!(s.next(&ch(&[3, 5, 8], Some(5)), seen, 1.0, None), Some(ch(&[5, 8], Some(5))));
        // Focus on someone gone: dropped from the call.
        assert_eq!(s.next(&ch(&[5], Some(3)), seen, 1.0, None), Some(ch(&[5], None)));
    }

    #[test]
    fn a_refusal_is_not_asked_again_unchanged_but_a_forced_fifth_is_sent() {
        let all = |_: u32| true;
        let mut s = Sender::default();
        let a = ch(&[], Some(9));
        s.sent(a.clone(), 0.0);
        let unseen = "You can only keep track of someone you can see now.";
        assert_eq!(s.reply(&a, &Err(unseen.into()), 0.1), Outcome::Refused(unseen.into()));
        assert_eq!(s.next(&a, all, 2.0, None), None);
        assert_eq!(s.next(&ch(&[], Some(10)), all, 2.0, None), Some(ch(&[], Some(10))));
        // The fifth: sent as asked, whatever is held.
        let five = ch(&[1, 2, 3, 4, 5], None);
        assert_eq!(s.next(&Choice::default(), all, 2.0, Some(&five)), Some(five.clone()));
        // Not while a call is in flight, nor inside the spacing.
        s.sent(five.clone(), 2.0);
        assert_eq!(s.next(&Choice::default(), all, 3.0, Some(&five)), None);
        let max = "You can keep at most 4 others pinned at once.";
        assert_eq!(s.reply(&five, &Err(max.into()), 2.1), Outcome::Refused(max.into()));
        assert_eq!(s.acked, Choice::default());
    }

    #[test]
    fn a_throng_figure_pins_only_an_individual_near_it() {
        use crate::throng::{Row, STILL};
        let row = Row::of(&living_bindings::SeenThrong { id: 1, viewer: spacetimedb_sdk::Identity::ZERO, cell: (10 << 16) | 10, size: 1, count: 5, spread: 4, heading: STILL, moving: 0, fighting: 0, kinds: 1 });
        let tp = ThrongPick { row, at: Vec2::new(63.0, 63.0) };
        // In the square, the nearest to the figure; ties by id.
        assert_eq!(in_throng(&tp, &[(7, Vec2::new(61.0, 61.0)), (4, Vec2::new(64.0, 63.5)), (9, Vec2::new(90.0, 90.0))]), Some(4));
        // Outside the square but within 1.5 m of the figure.
        let edge = ThrongPick { row, at: Vec2::new(65.8, 63.0) };
        assert_eq!(in_throng(&edge, &[(5, Vec2::new(66.8, 63.0))]), Some(5));
        // Nobody I perceive near it: nobody (a throng member has no id here).
        assert_eq!(in_throng(&tp, &[(9, Vec2::new(90.0, 90.0))]), None);
        assert_eq!(in_throng(&tp, &[]), None);
    }

    #[test]
    fn marks_ring_each_pin_and_the_focus_once() {
        let h = Heed { pins: vec![3, 5], focus: Some(5), ..Default::default() };
        assert_eq!(h.marks(), vec![(3, false), (5, true)]);
    }
}
