//! People in interface D: a window per person, keyed by character id, and the log and people.
//!
//! - **A person's window** (left anchor) opens by talking to them (Enter, a tap on them, F),
//!   from the list of acts ("Their window") or from Log › People. It holds how I name them and
//!   how they look (`looks.rs`), how we met, the acts toward them (Give ›, Trade…, Wave, Look
//!   over, Introduce yourself), our conversation, and the words I am typing to them.
//! - **The conversation** comes from my experience rows (`heard.rs`): my `said` lines to them
//!   and every line of theirs I heard (marked "to you" when addressed to me). Under my line: who
//!   heard it among the people I could see, once the authority reports it (`heard_by`, not built
//!   yet: nothing shows), and "they did not hear you" when a `silence` row says so.
//! - **Introduce yourself** puts an ordinary editable line in the box ("I'm Diego."), sent with
//!   `human_say` to them like any other. Whether they learn the name is the rules' affair.
//! - **Log and people** (L): Heard (every line heard and said), People (everyone met; a click
//!   opens their window) and Events (what the authority told me of my acts, introductions, no
//!   answers). Its box speaks to the room (`to = 0`).
//!
//! The store keeps what this session received: `my_experience` holds only the authority's
//! newest rows, so lines older than the session are not in it.

use super::hit::{Block, Hot, Tag, UiPointer};
use super::icons::{Glyph, Icons, Mark};
use super::kit::{self, Lit};
use super::theme::Fonts;
use super::win::{Win, WinBody, WinTitle, Windows};
use super::{set_text, show, wood};
use crate::heard;
use crate::looks::Looks;
use crate::net::Net;
use bevy::prelude::*;
use bevy::ui::{BackgroundGradient, ScrollPosition};
use living_bindings::*;
use spacetimedb_sdk::Table;
use std::collections::{BTreeMap, HashMap, HashSet};

const THREAD: usize = 24;
const HEARD_ROWS: usize = 30;
const PEOPLE_ROWS: usize = 16;
const EVENT_ROWS: usize = 24;
const GIVE_ROWS: usize = 10;

#[derive(Clone, Debug)]
pub struct Line {
    pub at_ms: u64,
    pub speaker: u32,
    pub to: u32,
    pub text: String,
    pub mine: bool,
    pub heard_by: Option<Vec<u32>>,
    /// The one addressed was out of earshot ("No answer from …").
    pub unheard: bool,
}

#[derive(Default, Clone, Debug)]
pub struct Met {
    /// When I first perceived them, or first had a row about them (authority ms).
    pub first_ms: u64,
    /// When they told me their name (`introduced`), once the authority reports it.
    pub introduced_ms: Option<u64>,
    pub last_line: Option<String>,
}

/// What this session has received of talk and people.
#[derive(Resource, Default)]
pub struct Talks {
    /// Lines by experience id, oldest first.
    pub lines: BTreeMap<u64, Line>,
    pub met: HashMap<u32, Met>,
    /// Events: (authority ms, text).
    pub events: Vec<(u64, String)>,
    /// Offers dismissed on this client (row ids, this session only: the world is not told).
    pub dismissed: HashSet<u64>,
    /// Offers already noted.
    noted: HashSet<u64>,
    seen: HashSet<u64>,
    me: Option<u32>,
}

impl Talks {

    /// Our conversation, oldest first.
    pub fn with(&self, id: u32) -> impl Iterator<Item = &Line> {
        self.lines.values().filter(move |l| (l.mine && l.to == id) || (!l.mine && l.speaker == id))
    }
}

/// Take in the experience rows that arrived (Present phase).
pub fn ingest(net: NonSend<Net>, scene: NonSend<crate::world::Scene>, looks: Res<Looks>, mut t: ResMut<Talks>, mut hints: ResMut<Hints>) {
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else { return };
    if t.me != Some(me) {
        *t = Talks { me: Some(me), ..default() };
    }
    let now = scene.now_ms as u64;
    for c in conn.db.seen_characters().iter().filter(|c| c.id != me && c.kind == "person") {
        t.met.entry(c.id).or_insert(Met { first_ms: now, ..default() });
    }
    let mut fresh: Vec<Experience> = conn.db.my_experience().iter().filter(|e| e.observer == me && !t.seen.contains(&e.id)).collect();
    fresh.sort_by_key(|e| e.id);
    for e in fresh {
        t.seen.insert(e.id);
        // Someone I have talked with, or who is in my scene now, counts as met.
        let talkish = matches!(e.kind.as_str(), "said" | "speech" | "introduced" | "silence");
        let other = if e.kind == "said" { e.object } else { e.subject };
        if other != 0 && other != me && (talkish || t.met.contains_key(&other)) {
            let m = t.met.entry(other).or_insert(Met { first_ms: e.at_ms, ..default() });
            m.first_ms = m.first_ms.min(e.at_ms);
        }
        if let Some(to) = heard::said(&e) {
            if e.at_ms as f64 + 10_000.0 >= scene.now_ms {
                hints.said = true;
            }
            t.lines.insert(e.id, Line { at_ms: e.at_ms, speaker: me, to, text: heard::words(&e.text).to_string(), mine: true, heard_by: heard::heard_by(&e), unheard: false });
        } else if let Some((who, to)) = heard::heard(&e) {
            let text = heard::words(&e.text).to_string();
            t.met.entry(who).or_default().last_line = Some(text.clone());
            t.lines.insert(e.id, Line { at_ms: e.at_ms, speaker: who, to, text, mine: false, heard_by: None, unheard: false });
        } else if let Some(to) = heard::unheard(&e) {
            if let Some(l) = t.lines.values_mut().rev().find(|l| l.mine && l.to == to && l.at_ms == e.at_ms) {
                l.unheard = true;
            }
            t.events.push((e.at_ms, wood::readable(&e.text)));
        } else if let Some(who) = heard::introduced(&e) {
            t.met.entry(who).or_default().introduced_ms = Some(e.at_ms);
            t.events.push((e.at_ms, wood::readable(&e.text)));
        } else if matches!(e.kind.as_str(), "act" | "record") {
            t.events.push((e.at_ms, crate::verbs::outcome_text(&e.text).1));
        }
    }
    // A name the rules gave since: an event too.
    let _ = &looks;
    while t.lines.len() > 400 {
        t.lines.pop_first();
    }
    let n = t.events.len();
    if n > 80 {
        t.events.drain(..n - 80);
    }
    if t.seen.len() > 4096 {
        let live: HashSet<u64> = conn.db.my_experience().iter().map(|e| e.id).collect();
        t.seen.retain(|id| live.contains(id));
    }
}

// ---- the person window ------------------------------------------------------------------------

#[derive(Component)]
pub struct Portrait(u32);
#[derive(Component)]
pub struct PortraitRing(u32);
#[derive(Component)]
pub struct WhoText(u32);
#[derive(Component)]
pub struct MetText(u32);
#[derive(Component)]
pub struct GiveList(u32);
#[derive(Component)]
pub struct OfferCard(u32);
#[derive(Component)]
pub struct OfferText(u32);
#[derive(Component)]
pub struct GiveRow(u32, usize);
#[derive(Component)]
pub struct GiveText(u32, usize);
#[derive(Component)]
pub struct Thread(Win);
#[derive(Component)]
pub struct Msg(Win, usize);
#[derive(Component)]
pub struct MsgName(Win, usize);
#[derive(Component)]
pub struct MsgText(Win, usize);
#[derive(Component)]
pub struct MsgHeard(Win, usize);
/// The words-being-typed row of a window, its "to" chip and its text.
#[derive(Component)]
pub struct InputRow(Win);
#[derive(Component)]
pub struct ToChip(Win);
#[derive(Component)]
pub struct InputText(Win);
#[derive(Component)]
pub struct Empty(Win);
/// A help line shown until it has been used (`Hints`).
#[derive(Component)]
pub struct Hint;

/// One-time help: the box's line goes once a line has been said.
#[derive(Resource, Default)]
pub struct Hints {
    pub said: bool,
}
/// The log's tabs' bodies.
#[derive(Component)]
pub struct LogTab(u8);
#[derive(Component)]
pub struct PersonRow(usize);
#[derive(Component)]
pub struct PersonRowText(usize);
#[derive(Component)]
pub struct PersonRowNote(usize);
#[derive(Component)]
pub struct EventRow(usize);

/// The log's open tab (0 heard, 1 people, 2 events).
#[derive(Resource, Default)]
pub struct LogPage(pub u8);

fn bubble(p: &mut ChildSpawnerCommands, f: &Fonts, w: Win, i: usize) {
    p.spawn((Msg(w, i), Node { flex_direction: FlexDirection::Column, padding: UiRect::new(Val::Px(9.0), Val::Px(9.0), Val::Px(5.0), Val::Px(6.0)), border: wood::b(2.0), border_radius: wood::r(10.0), max_width: Val::Px(330.0), display: Display::None, flex_shrink: 0.0, ..default() }, BackgroundColor(wood::field()), BorderColor::all(wood::edge()), Pickable::IGNORE)).with_children(|m| {
        m.spawn((MsgName(w, i), Text::new(""), f.body(12.0, 900), TextColor(wood::talk_ink()), Pickable::IGNORE));
        m.spawn((MsgText(w, i), Text::new(""), f.body(14.0, 600), TextColor(wood::text()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
        m.spawn((MsgHeard(w, i), Text::new(""), f.body(11.5, 700), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { display: Display::None, margin: UiRect::top(Val::Px(2.0)), ..default() }, Pickable::IGNORE));
    });
}

fn input_row(p: &mut ChildSpawnerCommands, f: &Fonts, icons: &Icons, w: Win, hint: &str) {
    p.spawn((InputRow(w), Hot, Tag(format!("input:{}", w.name())), Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(8.0), padding: UiRect::axes(Val::Px(8.0), Val::Px(6.0)), border: wood::b(2.0), border_radius: wood::r(8.0), flex_shrink: 0.0, ..default() }, BackgroundColor(wood::field()), BorderColor::all(wood::edge()), bevy::ui::Outline { width: Val::Px(0.0), offset: Val::Px(0.0), color: wood::alpha(wood::talk(), 0.5) }))
        .with_children(|r| {
            r.spawn((Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(3.0), padding: UiRect::axes(Val::Px(7.0), Val::Px(2.0)), border_radius: wood::r(6.0), flex_shrink: 0.0, ..default() }, BackgroundColor(wood::talk()), Pickable::IGNORE)).with_children(|c| {
                c.spawn((ToChip(w), Text::new(""), f.body(12.0, 900), TextColor(Color::WHITE), Pickable::IGNORE));
                c.spawn(wood::icon(icons, Glyph::Ui(Mark::Caret), 9.0, Color::WHITE));
            });
            r.spawn((InputText(w), Text::new(""), f.body(14.0, 650), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { flex_grow: 1.0, flex_shrink: 1.0, min_width: Val::Px(90.0), ..default() }, Pickable::IGNORE));
            // The box's other ways of speaking (`talk::MODES`): whisper keeps its place, greyed,
            // until the rules have it (docs/COMMUNICATION.md, the Spark coordinator's).
            for m in crate::talk::MODES.iter().filter(|m| !m.available) {
                r.spawn((Node { padding: UiRect::axes(Val::Px(6.0), Val::Px(1.0)), border: wood::b(1.5), border_radius: wood::r(6.0), flex_shrink: 0.0, ..default() }, BorderColor::all(wood::alpha(wood::muted(), 0.6)), Pickable::IGNORE))
                    .with_child((Text::new(m.key), f.body(11.0, 800), TextColor(wood::alpha(wood::muted(), 0.8)), Pickable::IGNORE));
            }
            if wood::t().chips {
                wood::chip(r, f, "Enter", ());
            }
        });
    // How the box works: shown until the first line is said (always in a dense theme).
    p.spawn((Hint, Text::new(hint), f.body(12.0, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
}

fn thread(p: &mut ChildSpawnerCommands, f: &Fonts, w: Win, n: usize, empty: &str) {
    p.spawn((Thread(w), Node { flex_direction: FlexDirection::Column, row_gap: Val::Px(7.0), padding: UiRect::top(Val::Px(8.0)), border: UiRect::top(Val::Px(1.5)), overflow: Overflow::scroll_y(), flex_grow: 1.0, flex_shrink: 1.0, min_height: Val::Px(0.0), ..default() }, BorderColor::all(wood::line()), ScrollPosition::default(), Block)).with_children(|t| {
        t.spawn((Empty(w), Text::new(empty), f.body(13.0, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
        for i in 0..n {
            bubble(t, f, w, i);
        }
    });
}

pub fn spawn(mut commands: Commands, bodies: Query<(Entity, &WinBody), Added<WinBody>>, fonts: Res<Fonts>, icons: Res<Icons>, binds: Res<crate::keys::Binds>) {
    let f = &*fonts;
    for (e, b) in &bodies {
        match b.0 {
            Win::Person(id) => {
                let w = b.0;
                commands.entity(e).with_children(|body| {
                    body.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(12.0), align_items: AlignItems::Center, flex_shrink: 0.0, ..default() }, Pickable::IGNORE)).with_children(|h| {
                        h.spawn((PortraitRing(id), Node { width: Val::Px(58.0), height: Val::Px(58.0), border: wood::b(3.0), border_radius: BorderRadius::all(Val::Percent(50.0)), justify_content: JustifyContent::Center, align_items: AlignItems::Center, flex_shrink: 0.0, ..default() }, BackgroundColor(wood::surface_lo()), BorderColor::all(wood::edge()), Pickable::IGNORE))
                            .with_child((Portrait(id), Node { width: Val::Px(40.0), height: Val::Px(40.0), ..default() }, ImageNode::new(icons.get(Glyph::Ui(Mark::Person))).with_color(wood::heading()), Pickable::IGNORE));
                        h.spawn((Node { flex_direction: FlexDirection::Column, flex_shrink: 1.0, ..default() }, Pickable::IGNORE)).with_children(|c| {
                            c.spawn((WhoText(id), Text::new(""), wood::ink(f, 15.0, 900), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                            c.spawn((MetText(id), Text::new(""), f.body(12.5, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                        });
                    });
                    // The acts wanted in the moment; the rest (Trade…, Introduce yourself, every act
                    // the rules allow) behind More….
                    body.spawn((Node { flex_direction: FlexDirection::Row, flex_wrap: FlexWrap::Wrap, column_gap: Val::Px(6.0), row_gap: Val::Px(6.0), flex_shrink: 0.0, ..default() }, Pickable::IGNORE)).with_children(|a| {
                        kit::button(a, f, "Give ›", &format!("person:give:{id}"), false);
                        let wave = kit::button(a, f, "Wave", &format!("person:wave:{id}"), true);
                        let look = kit::button(a, f, "Look over", &format!("person:appraise:{id}"), true);
                        if wood::t().chips {
                            a.commands().entity(wave).with_children(|b| {
                                wood::chip(b, f, &binds.first(crate::keys::Act::Wave), ());
                            });
                            a.commands().entity(look).with_children(|b| {
                                wood::chip(b, f, &binds.first(crate::keys::Act::LookOver), ());
                            });
                        }
                        kit::button(a, f, "More…", &format!("person:more:{id}"), true);
                    });
                    // An offer they made me: their words, Accept (the rules' `accept`) and Decline.
                    body.spawn((OfferCard(id), Node { flex_direction: FlexDirection::Column, row_gap: Val::Px(6.0), padding: UiRect::all(Val::Px(10.0)), border: wood::b(2.0), border_radius: wood::r(8.0), display: Display::None, flex_shrink: 0.0, ..default() }, BackgroundColor(wood::t().hot.0), BorderColor::all(wood::edge()), Pickable::IGNORE)).with_children(|o| {
                        o.spawn((OfferText(id), Text::new(""), wood::ink(f, 14.0, 700), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                        o.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(6.0), ..default() }, Pickable::IGNORE)).with_children(|b| {
                            kit::button(b, f, "Accept", &format!("person:accept:{id}"), false);
                            // No act declines yet: this hides it here and tells them nothing.
                            kit::button(b, f, "Dismiss", &format!("person:dismiss:{id}"), true);
                        });
                    });
                    // What I can give them, from my pack and the rules (opened by Give ›).
                    body.spawn((GiveList(id), Node { flex_direction: FlexDirection::Column, border: wood::b(2.0), border_radius: wood::r(8.0), overflow: Overflow::clip(), display: Display::None, flex_shrink: 0.0, ..default() }, BackgroundColor(wood::surface_hi()), BorderColor::all(wood::edge()), Pickable::IGNORE)).with_children(|g| {
                        for i in 0..GIVE_ROWS {
                            g.spawn((GiveRow(id, i), Hot, Tag(format!("person:gift:{id}:{i}")), kit::Paint::Row, Lit(false), Node { padding: UiRect::axes(Val::Px(10.0), Val::Px(5.0)), display: Display::None, ..default() }, BackgroundGradient::default()))
                                .with_child((GiveText(id, i), Text::new(""), wood::ink(f, 14.0, 800), Pickable::IGNORE));
                        }
                    });
                    thread(body, f, w, THREAD, "Nothing said between you yet.");
                    input_row(body, f, &icons, w, "Everyone in earshot hears it. Tab: someone else, or the room.");
                });
            }
            Win::Log => {
                let w = b.0;
                commands.entity(e).with_children(|body| {
                    body.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(6.0), flex_shrink: 0.0, ..default() }, Pickable::IGNORE)).with_children(|tabs| {
                        for (label, i) in [("Heard", 0), ("People", 1), ("Events", 2)] {
                            tabs.spawn((Hot, Tag(format!("log:tab:{i}")), kit::Paint::Choice, Lit(false), Node { padding: UiRect::axes(Val::Px(12.0), Val::Px(4.0)), border: wood::b(2.0), border_radius: wood::r(8.0), ..default() }, BackgroundGradient::default(), BorderColor::all(wood::edge()), wood::hard_shadow(2.0, 0.4)))
                                .with_child((Text::new(label), wood::ink(f, 13.5, 800), Pickable::IGNORE));
                        }
                    });
                    body.spawn((LogTab(0), Node { flex_direction: FlexDirection::Column, flex_grow: 1.0, flex_shrink: 1.0, min_height: Val::Px(0.0), ..default() }, Pickable::IGNORE)).with_children(|t| thread(t, f, w, HEARD_ROWS, "Nothing heard yet. Lines you hear and say gather here."));
                    body.spawn((LogTab(1), Node { flex_direction: FlexDirection::Column, row_gap: Val::Px(2.0), flex_grow: 1.0, flex_shrink: 1.0, min_height: Val::Px(0.0), overflow: Overflow::scroll_y(), display: Display::None, ..default() }, ScrollPosition::default(), Block)).with_children(|t| {
                        t.spawn((Empty(Win::Settings), Text::new("No one met yet."), f.body(13.0, 600), TextColor(wood::muted()), Pickable::IGNORE));
                        for i in 0..PEOPLE_ROWS {
                            t.spawn((PersonRow(i), Hot, Tag(format!("log:person:{i}")), kit::Paint::Row, Lit(false), Node { flex_direction: FlexDirection::Column, padding: UiRect::axes(Val::Px(8.0), Val::Px(4.0)), border_radius: wood::r(6.0), display: Display::None, flex_shrink: 0.0, ..default() }, BackgroundGradient::default())).with_children(|r| {
                                r.spawn((PersonRowText(i), Text::new(""), wood::ink(f, 14.0, 800), Pickable::IGNORE));
                                r.spawn((PersonRowNote(i), Text::new(""), f.body(12.0, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
                            });
                        }
                    });
                    body.spawn((LogTab(2), Node { flex_direction: FlexDirection::Column, row_gap: Val::Px(3.0), flex_grow: 1.0, flex_shrink: 1.0, min_height: Val::Px(0.0), overflow: Overflow::scroll_y(), display: Display::None, ..default() }, ScrollPosition::default(), Block)).with_children(|t| {
                        for i in 0..EVENT_ROWS {
                            t.spawn((EventRow(i), Text::new(""), f.body(13.0, 600), TextColor(wood::text()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { display: Display::None, flex_shrink: 0.0, ..default() }, Pickable::IGNORE));
                        }
                    });
                    input_row(body, f, &icons, w, "Everyone in earshot hears it. Point at someone first to speak to them.");
                });
            }
            _ => {}
        }
    }
}

/// The people listed under Log › People, most recent first.
fn people_list(t: &Talks, me: Option<u32>, looks: &Looks) -> Vec<u32> {
    let mut v: Vec<(u64, u32)> = t.met.iter().filter(|(id, _)| Some(**id) != me && looks.of(**id).is_some()).map(|(id, m)| (t.with(*id).last().map_or(m.first_ms, |l| l.at_ms.max(m.first_ms)), *id)).collect();
    v.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
    v.into_iter().map(|(_, id)| id).collect()
}

fn ago(now_ms: f64, at_ms: u64) -> String {
    let s = ((now_ms - at_ms as f64) / 1000.0).max(0.0);
    if s < 60.0 {
        "just now".into()
    } else if s < 3600.0 {
        format!("{} min ago", (s / 60.0).round() as u32)
    } else {
        format!("{} h ago", (s / 3600.0).round() as u32)
    }
}

/// Clicks in the people windows: acts toward a person, Give rows, the log's tabs and people.
#[allow(clippy::too_many_arguments)]
pub fn clicks(ui: Res<UiPointer>, tags: Query<&Tag>, mut ws: ResMut<Windows>, mut page: ResMut<LogPage>, (looks, time, mut offers): (Res<Looks>, Res<Time>, ResMut<Talks>), net: NonSend<Net>, mut verbs: ResMut<crate::verbs::Verbs>, mut gestures: ResMut<crate::town::Scripted>, mut talk: ResMut<crate::talk::Talk>, mut input: ResMut<crate::controls::Input>, mut open_give: Local<Option<u32>>, mut give: Query<(&GiveList, &mut Node)>) {
    if let Some(t) = kit::clicked(&ui, &tags) {
        let parts: Vec<&str> = t.split(':').collect();
        match parts.as_slice() {
            ["log", "tab", i] => page.0 = i.parse().unwrap_or(0),
            ["log", "person", i] => {
                if let Some(id) = i.parse::<usize>().ok().and_then(|i| people_list(&offers, net.my_id, &looks).get(i).copied()) {
                    ws.open(Win::Person(id));
                }
            }
            ["input", w] => {
                // A click in a window's box: type to whom it names.
                match w.strip_prefix("Person").and_then(|n| n.parse::<u32>().ok()) {
                    Some(id) => talk.want = Some(Some(id)),
                    None => talk.want = Some(None),
                }
            }
            // `person:ACT:ID` (ACT first, so a script finds `@person:intro`).
            ["person", act, id] => {
                let Ok(id) = id.parse::<u32>() else { return };
                match *act {
                    "give" => {
                        *open_give = if *open_give == Some(id) { None } else { Some(id) };
                        verbs.want_toward = Some(id);
                    }
                    "trade" => verbs.open_group = Some((id, "offer".into())),
                    "accept" | "dismiss" => answer_offer(act, id, net.conn.as_ref(), &mut verbs, &mut offers),
                    "more" if net.conn.as_ref().is_some_and(|c| c.db.seen_characters().id().find(&id).is_none()) => {
                        verbs.toasts.push(crate::verbs::Toast { text: format!("{} is not in sight", looks.cap(id)), ok: None, at: time.elapsed_secs_f64() });
                    }
                    "more" => {
                        // Beside the window.
                        let at = ws.anchor_of(Win::Person(id)).map(|a| if a == super::win::Anchor::Left { Vec2::new(462.0, 60.0) } else { Vec2::new(880.0, 280.0) });
                        verbs.open_list = Some((id, at));
                    }
                    "wave" => gestures.press.push(("wave".into(), id.to_string())),
                    "appraise" => gestures.press.push(("appraise".into(), id.to_string())),
                    "intro" => {
                        let name = net.conn.as_ref().zip(net.my_id).and_then(|(c, me)| c.db.my_characters().id().find(&me)).map(|c| c.name).unwrap_or_else(|| net.name.clone());
                        talk.want = Some(Some(id));
                        input.chat = format!("I'm {name}.");
                        input.keep_words = true;
                    }
                    _ => {}
                }
            }
            ["person", "gift", id, i] => {
                if let (Ok(id), Ok(i)) = (id.parse::<u32>(), i.parse::<usize>()) {
                    if let Some(c) = verbs.toward.as_ref().filter(|t| t.0 == id).and_then(|t| super::people::gifts(&t.1).get(i).cloned().cloned()) {
                        verbs.send.push((crate::verbs::Aim::Creature { id }, c));
                    }
                    *open_give = None;
                }
            }
            _ => {}
        }
    }
    // Introduce yourself from the list of acts (`verbs.rs`).
    if let Some(id) = verbs.want_intro.take() {
        let name = net.conn.as_ref().zip(net.my_id).and_then(|(c, me)| c.db.my_characters().id().find(&me)).map(|c| c.name).unwrap_or_else(|| net.name.clone());
        talk.want = Some(Some(id));
        input.chat = format!("I'm {name}.");
        input.keep_words = true;
    }
    for (g, mut n) in &mut give {
        show(&mut n, *open_give == Some(g.0) && ws.is_open(Win::Person(g.0)));
    }
}

/// The rules' choices toward a person that hand over something I carry (no return asked).
pub fn gifts(choices: &[crate::verbs::Choice]) -> Vec<&crate::verbs::Choice> {
    choices.iter().filter(|c| c.item.is_some() && c.have > 0 && c.want.is_none() && c.say.is_none() && !c.words).collect()
}

/// Fill the people windows from the store, the projection and the words being typed.
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn update(
    (talks, looks, ws, input, talk, typing, page, verbs, time, pointer, ui): (Res<Talks>, Res<Looks>, Res<Windows>, Res<crate::controls::Input>, Res<crate::talk::Talk>, Res<super::say::Typing>, Res<LogPage>, Res<crate::verbs::Verbs>, Res<Time>, Res<crate::pointer::Pointer>, Res<UiPointer>),
    net: NonSend<Net>,
    scene: NonSend<crate::world::Scene>,
    mut texts: ParamSet<(
        Query<(&WhoText, &mut Text)>,
        Query<(&MetText, &mut Text)>,
        Query<(&MsgName, &mut Text, &mut TextColor)>,
        Query<(&MsgText, &mut Text)>,
        Query<(&MsgHeard, &mut Text, &mut Node)>,
        Query<(&ToChip, &mut Text)>,
        Query<(&InputText, &mut Text, &mut TextColor)>,
        ParamSet<(Query<(&WinTitle, &mut Text)>, Query<(&PersonRowText, &mut Text)>, Query<(&PersonRowNote, &mut Text)>, Query<(&EventRow, &mut Text, &mut Node)>, Query<(&GiveText, &mut Text)>)>,
    )>,
    (mut msgs, mut tabs, mut rows, mut gives, mut empties): (
        Query<(&Msg, &mut Node, &mut BackgroundColor), (Without<MsgHeard>, Without<EventRow>, Without<LogTab>, Without<PersonRow>, Without<GiveRow>, Without<Empty>)>,
        Query<(&LogTab, &mut Node), (Without<Msg>, Without<MsgHeard>, Without<EventRow>, Without<PersonRow>, Without<GiveRow>, Without<Empty>)>,
        Query<(&PersonRow, &mut Node), (Without<Msg>, Without<MsgHeard>, Without<EventRow>, Without<LogTab>, Without<GiveRow>, Without<Empty>)>,
        Query<(&GiveRow, &mut Node), (Without<Msg>, Without<MsgHeard>, Without<EventRow>, Without<LogTab>, Without<PersonRow>, Without<Empty>)>,
        Query<(&Empty, &mut Node), (Without<Msg>, Without<MsgHeard>, Without<EventRow>, Without<LogTab>, Without<PersonRow>, Without<GiveRow>)>,
    ),
    (mut lit, mut inputs, mut portraits, mut threads): (Query<(&Tag, &mut Lit)>, Query<(&InputRow, &mut bevy::ui::Outline)>, Query<(&Portrait, &mut ImageNode)>, Query<(&Thread, &mut ScrollPosition, &bevy::ui::ComputedNode, &bevy::ui::UiGlobalTransform)>),
    mut counts: Local<HashMap<Win, usize>>,
) {
    let me = net.my_id;
    let now = scene.now_ms;
    let name = |id: u32| if Some(id) == me { "You".to_string() } else { looks.cap(id) };
    let lower = |id: u32| if Some(id) == me { "you".to_string() } else { looks.of(id).unwrap_or("someone").to_string() };
    let perceived = |id: u32| net.conn.as_ref().is_some_and(|c| c.db.seen_characters().id().find(&id).is_some());
    // Each open window's lines (the log: everything heard and said).
    let mut shown: HashMap<Win, Vec<&Line>> = HashMap::new();
    for o in &ws.open {
        match o.win {
            Win::Person(id) => {
                let v: Vec<&Line> = talks.with(id).collect();
                shown.insert(o.win, v[v.len().saturating_sub(THREAD)..].to_vec());
            }
            Win::Log => {
                let v: Vec<&Line> = talks.lines.values().collect();
                shown.insert(o.win, v[v.len().saturating_sub(HEARD_ROWS)..].to_vec());
            }
            _ => {}
        }
    }
    let line_of = |w: &Win, i: usize| shown.get(w).and_then(|v| v.get(i)).copied();
    for (m, mut n, mut bg) in &mut msgs {
        let l = line_of(&m.0, m.1);
        show(&mut n, l.is_some());
        if let Some(l) = l {
            let (col, align) = if l.mine { (wood::mine(), AlignSelf::FlexEnd) } else { (wood::field(), AlignSelf::FlexStart) };
            if bg.0 != col {
                bg.0 = col;
            }
            if n.align_self != align {
                n.align_self = align;
            }
        }
    }
    for (e, mut n) in &mut empties {
        show(&mut n, match e.0 {
            Win::Settings => people_list(&talks, me, &looks).is_empty(),
            w => shown.get(&w).is_none_or(|v| v.is_empty()),
        });
    }
    {
        let mut q = texts.p2();
        for (m, mut t, mut c) in &mut q {
            if let Some(l) = line_of(&m.0, m.1) {
                let s = match (m.0, l.mine) {
                    (Win::Person(_), true) => "You, to them".to_string(),
                    (Win::Person(_), false) => {
                        let to = if Some(l.to) == me { ", to you".to_string() } else if l.to != 0 { format!(", to {}", lower(l.to)) } else { String::new() };
                        format!("{}{to}", name(l.speaker))
                    }
                    (_, _) => format!("{} › {}", name(l.speaker), if l.to == 0 { "the room".to_string() } else { lower(l.to) }),
                };
                set_text(&mut t, &s);
                super::set_color(&mut c, if l.mine { wood::name_mine() } else { wood::talk_ink() });
            }
        }
    }
    for (m, mut t) in &mut texts.p3() {
        if let Some(l) = line_of(&m.0, m.1) {
            set_text(&mut t, &wood::readable(&l.text));
        }
    }
    for (m, mut t, mut n) in &mut texts.p4() {
        // Under my line: who heard it, once the authority reports it; a known "not heard".
        let note = line_of(&m.0, m.1).filter(|l| l.mine).and_then(|l| {
            if l.unheard {
                return Some(format!("{} did not hear you: out of earshot", looks.cap(l.to)));
            }
            let by = l.heard_by.as_ref()?;
            let seen: Vec<String> = by.iter().filter(|id| looks.of(**id).is_some()).map(|id| lower(*id)).collect();
            let missed = l.to != 0 && !by.contains(&l.to);
            Some(match (seen.is_empty(), missed) {
                (_, true) => format!("addressed {}, not heard by them", lower(l.to)),
                (true, false) => "heard by no one you could see".into(),
                (false, false) => format!("heard by {}: the people you could see", seen.join(", ")),
            })
        });
        show(&mut n, note.is_some());
        if let Some(s) = note {
            set_text(&mut t, &s);
        }
    }
    for (w, mut t) in &mut texts.p0() {
        let named = net.conn.as_ref().and_then(|c| c.db.seen_characters().id().find(&w.0)).is_some_and(|c| !c.name.is_empty());
        let colour = looks.colours.get(&w.0).and_then(|(t, _)| t.as_deref()).and_then(crate::looks::colour_name);
        // The title names them; this line adds only what the title lacks (a named person's
        // clothes), and is empty otherwise.
        let s = match (named, colour) {
            (true, Some(c)) => format!("{} · in {c}", looks.cap(w.0)),
            _ => String::new(),
        };
        set_text(&mut t, &s);
    }
    for (w, mut t) in &mut texts.p1() {
        let m = talks.met.get(&w.0);
        // Kept short: when we met, and whether they are in sight.
        let mut s = m.map_or_else(String::new, |m| format!("First seen {}", ago(now, m.first_ms)));
        if m.and_then(|m| m.introduced_ms).is_some() {
            s.push_str(" · told you their name");
        }
        if !perceived(w.0) {
            s.push_str(" · not in sight");
        }
        set_text(&mut t, &s);
    }
    for (w, mut t) in &mut texts.p7().p0() {
        if let Win::Person(id) = w.0 {
            set_text(&mut t, &wood::fit(&looks.cap(id), 34));
        }
    }
    // The box: whom it speaks to, the words, a caret.
    let typing_in = typing.window.filter(|_| input.chat_open && input.compose.is_none());
    let to_label = |w: Win| match w {
        Win::Person(id) => format!("to {}", lower(id)),
        _ => "to the room".into(),
    };
    for (c, mut t) in &mut texts.p5() {
        // Short, so the box keeps its room: "to a stranger in gr…".
        let s = wood::fit(&if typing_in == Some(c.0) { talk.to.map_or_else(|| "to the room".into(), |id| format!("to {}", lower(id))) } else { to_label(c.0) }, 22);
        set_text(&mut t, &s);
    }
    let caret = if crate::capture::scripted() || (time.elapsed_secs() * 1.8).fract() < 0.6 { "|" } else { " " };
    for (c, mut t, mut col) in &mut texts.p6() {
        if typing_in == Some(c.0) {
            set_text(&mut t, &format!("{}{caret}", input.chat));
            super::set_color(&mut col, wood::text());
        } else {
            set_text(&mut t, "Enter to talk");
            super::set_color(&mut col, wood::muted());
        }
    }
    for (r, mut o) in &mut inputs {
        let w = if typing_in == Some(r.0) { Val::Px(3.0) } else { Val::Px(0.0) };
        if o.width != w {
            o.width = w;
        }
    }
    for (p, mut img) in &mut portraits {
        let col = looks.colours.get(&p.0).and_then(|(t, _)| t.as_deref()).and_then(|h| Srgba::hex(h).ok()).map_or(wood::heading(), Color::from);
        if img.color != col {
            img.color = col;
        }
    }
    // The log's tabs.
    for (t, mut n) in &mut tabs {
        show(&mut n, t.0 == page.0);
    }
    let pg = page.0;
    kit::light(&mut lit, |t| t.strip_prefix("log:tab:").map(|i| i.parse::<u8>().ok() == Some(pg)));
    let list = people_list(&talks, me, &looks);
    for (r, mut n) in &mut rows {
        show(&mut n, r.0 < list.len());
    }
    for (r, mut t) in &mut texts.p7().p1() {
        if let Some(id) = list.get(r.0) {
            let here = if perceived(*id) { "  · here now" } else { "" };
            set_text(&mut t, &format!("{}{here}", looks.cap(*id)));
        }
    }
    for (r, mut t) in &mut texts.p7().p2() {
        if let Some(id) = list.get(r.0) {
            let m = talks.met.get(id);
            let s = m.and_then(|m| m.last_line.clone()).map_or_else(|| format!("First seen {}", m.map_or_else(String::new, |m| ago(now, m.first_ms))), |l| format!("“{}”", wood::readable(&l)));
            set_text(&mut t, &s);
        }
    }
    let ev = &talks.events[talks.events.len().saturating_sub(EVENT_ROWS)..];
    for (r, mut t, mut n) in &mut texts.p7().p3() {
        show(&mut n, r.0 < ev.len());
        if let Some((at, text)) = ev.get(r.0) {
            set_text(&mut t, &format!("{}  ·  {}", text, ago(now, *at)));
        }
    }
    let gifts_now: Vec<String> = verbs.toward.as_ref().map(|(_, c)| gifts(c).iter().map(|c| super::label(&c.label)).collect()).unwrap_or_default();
    for (g, mut n) in &mut gives {
        let ok = verbs.toward.as_ref().is_some_and(|t| t.0 == g.0) && g.1 < gifts_now.len();
        show(&mut n, ok || (g.1 == 0 && verbs.toward.as_ref().is_none_or(|t| t.0 != g.0)));
    }
    for (g, mut t) in &mut texts.p7().p4() {
        let s = if verbs.toward.as_ref().is_some_and(|t| t.0 == g.0) { gifts_now.get(g.1).cloned().unwrap_or_else(|| if g.1 == 0 { "Nothing in your pack to give".into() } else { String::new() }) } else { "…".into() };
        set_text(&mut t, &s);
    }
    // New lines scroll a thread to its end; two fingers over it scroll it.
    for (th, mut sp, node, tf) in &mut threads {
        let n = shown.get(&th.0).map_or(0, |v| v.len()) + talks.lines.len();
        if counts.get(&th.0) != Some(&n) {
            counts.insert(th.0, n);
            sp.0.y = 1.0e6;
        }
        let over = ui.pos.is_some_and(|p| node.contains_point(*tf, p * ui.scale));
        if over && pointer.scroll_px != 0.0 {
            sp.0.y = (sp.0.y.min(node.content_size().y) - pointer.scroll_px).max(0.0);
        }
    }
}

/// One-time help lines, and the person window's second line only when it says something.
pub fn hints(hints: Res<Hints>, mut lines: Query<&mut Node, (With<Hint>, Without<WhoText>)>, mut who: Query<(&Text, &mut Node), (With<WhoText>, Without<Hint>)>) {
    let on = wood::t().help || !hints.said;
    for mut n in &mut lines {
        show(&mut n, on);
    }
    for (t, mut n) in &mut who {
        show(&mut n, !t.0.is_empty());
    }
}


/// Answering an offer, the one place its acts live (rules-offers-2 will name the offer or record
/// and add a real `decline`). Today Accept is the rules' `accept` toward its maker, as a mind
/// accepts: what it takes is the rules' (their proposed terms first, else their swap), and a
/// refusal comes back as a note in the rules' words while the card stays. Dismiss has no act yet:
/// it hides their offers on this client for this session and tells them nothing.
fn answer_offer(how: &str, from: u32, conn: Option<&DbConnection>, verbs: &mut crate::verbs::Verbs, talks: &mut Talks) {
    match how {
        "accept" => verbs.send.push((crate::verbs::Aim::Creature { id: from }, crate::verbs::Choice { skill: "accept".into(), item: None, want: None, words: false, say: None, label: "accept".into(), have: 0 })),
        _ => {
            for o in conn.into_iter().flat_map(|c| c.db.my_offers().iter()).filter(|o| o.incoming && o.from == from) {
                talks.dismissed.insert(o.id);
            }
        }
    }
}

/// What Accept toward someone will do, in words: their open proposal of terms if they have one
/// (the rules' `accept` takes those first), else their standing offer.
fn offer_words(conn: &DbConnection, o: &MyOffer, me: u32, who: &str) -> String {
    let terms = conn.db.my_records().iter().find(|r| r.actor == me && r.open && r.kind == "agreement" && r.status == "offered" && r.role == "to" && r.others.split(',').any(|p| p == format!("from={}", o.from)));
    if let Some(r) = terms {
        let t: serde_json::Value = serde_json::from_str(&r.terms).unwrap_or_default();
        let n = |k: &str| t[k].as_u64().unwrap_or(1);
        let item = |k: &str| t[k].as_str().unwrap_or("?").replace('_', " ");
        return format!("{who} proposes terms: they give {} {}, you give {} {}. Accept agrees to these (the world keeps count), not to their swap.", n("from_qty"), item("from_gives"), n("to_qty"), item("to_gives"));
    }
    format!("{who} offers you {} {} for {} {}.", o.give_qty, o.give_item.replace('_', " "), o.want_qty, o.want_item.replace('_', " "))
}

/// Offers made to me (`my_offers`): a note when one arrives, and the card in that person's
/// window while the row stands (it goes when taken, withdrawn, offered again or out of time).
#[allow(clippy::type_complexity)]
pub fn offers(mut talks: ResMut<Talks>, looks: Res<Looks>, mut ws: ResMut<Windows>, net: NonSend<Net>, mut verbs: ResMut<crate::verbs::Verbs>, time: Res<Time>, mut cards: Query<(&OfferCard, &mut Node)>, mut texts: Query<(&OfferText, &mut Text)>) {
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else { return };
    let rows: Vec<MyOffer> = conn.db.my_offers().iter().filter(|o| o.incoming && o.to == me && !talks.dismissed.contains(&o.id)).collect();
    for o in &rows {
        if talks.noted.insert(o.id) {
            let words = offer_words(conn, o, me, &looks.cap(o.from));
            // Their window, with Accept in it, if the left anchor is free (or only the log is).
            let free = matches!(ws.at(super::win::Anchor::Left), None | Some(Win::Log));
            if free {
                ws.open(Win::Person(o.from));
            }
            let more = if free { "" } else { " Their window has Accept." };
            info!("ui: offer #{} from #{}: {words}", o.id, o.from);
            verbs.toasts.push(crate::verbs::Toast { text: format!("{words}{more}"), ok: None, at: time.elapsed_secs_f64() });
        }
    }
    if talks.noted.len() > 256 {
        let live: HashSet<u64> = conn.db.my_offers().iter().map(|o| o.id).collect();
        talks.noted.retain(|id| live.contains(id));
    }
    for (c, mut n) in &mut cards {
        show(&mut n, rows.iter().any(|o| o.from == c.0));
    }
    for (c, mut t) in &mut texts {
        if let Some(o) = rows.iter().filter(|o| o.from == c.0).max_by_key(|o| o.at_ms) {
            set_text(&mut t, &wood::readable(&offer_words(conn, o, me, &looks.cap(c.0))));
        }
    }
}
