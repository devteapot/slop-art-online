//! My character's family, courting offers and community (perception parity, phase 0: the facts
//! its graphs read of itself, `docs/PERCEPTION_PARITY_AUDIT.md`), from the identity-scoped views
//! `my_kin`, `my_bond_offers` and `my_community` (`net::KIN_VIEWS`).
//!
//! - **Where.** Log › People (L) opens with "Family" (a row per parent, partner and child; a
//!   click opens their window) and "Community" (its name, who founded it and when, when I joined,
//!   and where its home is from me). A courting offer is a card in the other one's person window,
//!   beside the trade offers' cards: theirs to me with the rules' act that takes it up, mine to
//!   them without buttons.
//! - **Names only from what I know or see.** A relative is named by the name my character knows
//!   (`my_known_names`, the rules' owner-known names: kin and community are in it), else by the
//!   relation alone ("Your parent", never a stranger's looks for one's own parent). A suitor or a
//!   founder by that name, else by how I see them (`looks.rs`, the perceived projection), else
//!   "A suitor" or no name. Nothing else is read: no `alive`, health or position of a
//!   relative is in the views, and none is shown. "here now" only for someone I perceive and can
//!   make out; anyone else is "not in sight" (one too far to make out is not told apart).
//! - **The rules' words.** A relation's word is the world's own `kin_terms()` (the words a
//!   speaker uses for a relative): the first word for the sex I have seen their body to be
//!   ("mother", "son", "wife"), else the relation's sex-neutral word ("parent"), else the
//!   relation's name as the views and minds' scenes give it ("child", "partner"). The home's
//!   way and distance are `living_rules::bearing::from_here`, the words every scene uses
//!   ("140 m northeast", "here"); days are the clock's (`living_rules::day_of`).
//! - **Answering a courting offer.** The card's buttons are the skills whose `_ui()` puts them
//!   `on` `bond` (`living_rules::ui::On::Bond`), in the script's order, each sent through
//!   `human_act` toward the offer's maker; no skill is named here. As shipped that is `conceive`,
//!   which takes the offer up within the `bond_window_s` law (its `done` gives `op: "bond"`). A
//!   world with no skill on `bond` shows the card without buttons. The shipped rules have no act
//!   to decline or withdraw one: it lapses at the window's end, when the card goes.

use super::hit::{Hot, Tag};
use super::kit::{self, Lit};
use super::theme::Fonts;
use super::win::{Win, Windows};
use super::{set_text, show, wood};
use crate::looks::{Looks, FAR};
use crate::net::Net;
use bevy::prelude::*;
use bevy::ui::BackgroundGradient;
use living_bindings::*;
use living_rules::script::speech::KinTerms;
use living_rules::sex::Sex;
use spacetimedb_sdk::Table;
use std::collections::HashSet;

/// Family rows shown in Log › People (two parents, a partner, children).
const KIN_ROWS: usize = 8;
/// The community's lines under its name: founded and joined, then home.
const COMMUNITY_LINES: usize = 2;
/// The rules' acts on a courting card (skills on `On::Bond`), at most this many.
const BOND_ACTS: usize = 2;

/// The rules' acts on a courting offer, in the script's order: each skill whose `_ui()` puts it
/// `on` `bond`, as (skill, label). What each does is the rules'.
pub fn bond_acts(sc: &living_rules::script::Scripts) -> Vec<(String, String)> {
    let on_bond = sc.ui_specs().filter(|u| u.is_on(living_rules::ui::On::Bond)).take(BOND_ACTS);
    on_bond.map(|u| (u.name.clone(), super::label(if u.label.trim().is_empty() { &u.name } else { &u.label }))).collect()
}

/// How I know someone, for naming them: the name my character knows, else how I see them, and
/// whether I perceive and make them out now.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Who {
    pub name: Option<String>,
    pub label: Option<String>,
    pub here: bool,
}

impl Who {
    /// Their name, else how I see them, as known now.
    pub fn called(&self) -> Option<&str> {
        self.name.as_deref().or(self.label.as_deref())
    }
}

/// The word for what a relative is to me, from the world's `kin_terms()`: the first word for the
/// sex I have seen them to be, else the relation's sex-neutral word, else the relation itself.
pub fn relation_word(terms: &KinTerms, relation: &str, sex: Option<Sex>) -> String {
    let Some(w) = terms.words.iter().find(|w| w.relation == relation) else { return relation.to_string() };
    let sexed = match sex {
        Some(Sex::Female) => w.female.first(),
        Some(Sex::Male) => w.male.first(),
        None => None,
    };
    sexed.or(w.any.first()).cloned().unwrap_or_else(|| relation.to_string())
}

/// A relative's row: its title (the name my character knows, else the relation: "Your mother",
/// never "a stranger in green" for one's own parent) and its note (what they are to me unless the
/// title says it, then whether they are here).
pub fn kin_line(word: &str, who: &Who) -> (String, String) {
    let presence = if who.here { "here now" } else { "not in sight" };
    match who.name.as_deref() {
        Some(n) => (super::label(n), format!("your {word} · {presence}")),
        None => (super::label(&format!("your {word}")), presence.to_string()),
    }
}

/// A title as it reads mid-sentence: "Your parent" → "your parent", "A suitor" → "a suitor"; a
/// name is kept as it is.
pub fn lowered(title: &str) -> String {
    match title.split_once(' ') {
        Some((first @ ("Your" | "A" | "An"), rest)) => format!("{} {rest}", first.to_lowercase()),
        _ => title.to_string(),
    }
}

/// "m:ss left" (or "h left") to answer, from authority ms.
pub fn time_left(until_ms: u64, now_ms: u64) -> String {
    let left = until_ms.saturating_sub(now_ms) / 1000;
    if left >= 3600 {
        format!("{} h left", left / 3600)
    } else {
        format!("{}:{:02} left", left / 60, left % 60)
    }
}

/// A courting offer's card: theirs to me ("A suitor wants to start a family with you.") or mine
/// to them, with the time left to answer.
pub fn bond_text(incoming: bool, who: &Who, until_ms: u64, now_ms: u64) -> String {
    let words = if incoming {
        format!("{} wants to start a family with you.", super::label(who.called().unwrap_or("a suitor")))
    } else {
        format!("You asked {} to start a family.", who.called().unwrap_or("them"))
    };
    format!("{words}  ·  {}", time_left(until_ms, now_ms))
}

/// The community's lines under its name: who founded it and on which day, when I joined, and its
/// home's way and distance from me ("Home: 140 m northeast").
pub fn community_lines(c: &MyCommunity, me: u32, founder: &Who, day: impl Fn(u64) -> Option<u64>, me_at: Option<(f32, f32)>) -> Vec<String> {
    let on = |ms: u64| day(ms).map_or_else(String::new, |d| format!(" on day {d}"));
    let mut first = if c.founder == me {
        format!("You founded it{}", on(c.founded_ms))
    } else {
        let by = founder.called().map_or_else(String::new, |n| format!(" by {n}"));
        format!("Founded{by}{}", on(c.founded_ms))
    };
    // When I joined, by the clock's day (none for a membership older than the world's clock).
    if let Some(d) = day(c.since_ms).filter(|d| !(c.founder == me && day(c.founded_ms) == Some(*d))) {
        first.push_str(&format!(" · you joined on day {d}"));
    }
    let mut out = vec![first];
    if let Some(at) = me_at {
        out.push(format!("Home: {}", living_rules::bearing::from_here(at, (c.home_x, c.home_y))));
    }
    out
}

/// A relative as shown.
#[derive(Clone, Debug)]
pub struct KinShown {
    pub id: u32,
    pub relation: String,
    pub word: String,
    pub title: String,
    pub note: String,
    pub here: bool,
    pub named: bool,
}

/// A courting offer as shown: `with` is the other one (whose window has the card).
#[derive(Clone, Debug)]
pub struct BondShown {
    pub id: u64,
    pub with: u32,
    pub incoming: bool,
    pub text: String,
    pub until_ms: u64,
}

/// What the family, community and courting rows show this frame (`fill`).
#[derive(Resource, Default)]
pub struct Kin {
    pub rows: Vec<KinShown>,
    pub community: Option<(String, Vec<String>)>,
    pub bonds: Vec<BondShown>,
    /// The rules' acts on a courting card to me ([`bond_acts`]): (skill, label).
    pub acts: Vec<(String, String)>,
    /// Incoming offers already noted.
    noted: HashSet<u64>,
    me: Option<u32>,
}

impl Kin {
    /// Whether Log › People has family or community to show above the people met.
    pub fn any(&self) -> bool {
        !self.rows.is_empty() || self.community.is_some()
    }

    /// How a person window titles a relative or a suitor I have no label for.
    pub fn title_of(&self, id: u32) -> Option<String> {
        if let Some(r) = self.rows.iter().find(|r| r.id == id) {
            return Some(r.title.clone());
        }
        self.bonds.iter().find(|b| b.with == id && b.incoming).map(|_| "A suitor".to_string())
    }

    /// The courting card in their window, if any (at most one stands between two people).
    pub fn bond_with(&self, id: u32) -> Option<&BondShown> {
        self.bonds.iter().find(|b| b.with == id)
    }

    /// Every text this shows that names someone or a place, for the UI dump's guard.
    pub fn naming(&self) -> Vec<(&'static str, String)> {
        let mut out: Vec<(&'static str, String)> = Vec::new();
        for r in &self.rows {
            out.push(("kin", r.title.clone()));
            out.push(("kin", r.note.clone()));
        }
        if let Some((name, lines)) = &self.community {
            out.push(("community", name.clone()));
            out.extend(lines.iter().map(|l| ("community", l.clone())));
        }
        out.extend(self.bonds.iter().map(|b| ("bond", b.text.clone())));
        out
    }

    pub fn json(&self) -> serde_json::Value {
        serde_json::json!({
            "rows": self.rows.iter().map(|r| serde_json::json!({"id": r.id, "relation": r.relation, "word": r.word, "title": r.title, "note": r.note, "here": r.here, "named": r.named})).collect::<Vec<_>>(),
            "community": self.community.as_ref().map(|(name, lines)| serde_json::json!({"name": name, "lines": lines})),
            "bonds": self.bonds.iter().map(|b| serde_json::json!({"id": b.id, "with": b.with, "incoming": b.incoming, "text": b.text, "until_ms": b.until_ms})).collect::<Vec<_>>(),
            "acts": self.acts.iter().map(|(skill, label)| serde_json::json!({"skill": skill, "label": label})).collect::<Vec<_>>(),
        })
    }
}

/// Fill [`Kin`] from the three views, what my character knows by name and what I see; note a
/// courting offer to me once (their window opens when the left anchor is free, as a trade
/// offer's does).
#[allow(clippy::too_many_arguments)]
pub fn fill(mut kin: ResMut<Kin>, net: NonSend<Net>, looks: Res<Looks>, (rules, scene): (NonSend<crate::verbs::Rules>, NonSend<crate::world::Scene>), mut ws: ResMut<Windows>, mut verbs: ResMut<crate::verbs::Verbs>, time: Res<Time>, mut window: Local<(u64, u64)>) {
    let (Some(conn), Some(me)) = (net.conn.as_ref(), net.my_id) else {
        kin.rows.clear();
        kin.community = None;
        kin.bonds.clear();
        return;
    };
    let fresh = kin.me != Some(me);
    if fresh {
        *kin = Kin { me: Some(me), ..default() };
    }
    let now = scene.now_ms.max(0.0) as u64;
    let who = |id: u32| {
        let name = conn.db.my_known_names().id().find(&id).map(|k| k.name).filter(|n| !n.trim().is_empty()).or_else(|| looks.is_known(id).then(|| looks.of(id).map(String::from)).flatten());
        let seen = crate::net::find_character(conn, id);
        let made_out = seen.as_ref().is_some_and(|c| c.label != FAR);
        let label = if name.is_some() { None } else { looks.of(id).map(String::from) };
        Who { name, label, here: made_out }
    };
    let Some(sc) = rules.scripts.as_ref() else { return };
    let terms = sc.kin();
    let order = |r: &str| match r {
        "parent" => 0,
        "partner" => 1,
        "child" => 2,
        _ => 3,
    };
    let mut rows: Vec<MyKin> = conn.db.my_kin().iter().collect();
    rows.sort_by_key(|k| (order(&k.relation), k.id));
    kin.rows = rows
        .into_iter()
        .map(|k| {
            let w = who(k.id);
            let word = relation_word(terms, &k.relation, looks.sex_seen(k.id));
            let (title, note) = kin_line(&word, &w);
            KinShown { id: k.id, relation: k.relation, word, title, note, here: w.here, named: w.name.is_some() }
        })
        .collect();
    let world = conn.db.world().iter().next();
    let day = |ms: u64| world.as_ref().filter(|w| w.day_ms > 0 && ms > 0).map(|w| living_rules::day_of(ms, w.epoch_ms, w.day_ms));
    let me_at = scene.shown.get(&me).map(|(p, _)| (p.x, p.y)).or_else(|| net.my_body().map(|b| (b.x, b.y)));
    kin.community = conn.db.my_community().iter().next().map(|c| {
        let lines = community_lines(&c, me, &who(c.founder), day, me_at);
        (c.name.clone(), lines)
    });
    // The window the rules give to answer an offer, and their acts on one, read again only when
    // the laws change.
    if fresh || window.0 != rules.laws_key || window.1 == 0 {
        *window = (rules.laws_key, (sc.laws().bond_window_s.max(0.0) * 1000.0) as u64);
        kin.acts = bond_acts(sc);
    }
    let bond_ms = window.1;
    let mut bonds: Vec<MyBondOffer> = conn.db.my_bond_offers().iter().filter(|o| now <= o.at_ms + bond_ms).collect();
    bonds.sort_by_key(|o| (!o.incoming, o.at_ms, o.id));
    kin.bonds = bonds
        .into_iter()
        .map(|o| {
            let with = if o.incoming { o.from } else { o.to };
            let until = o.at_ms + bond_ms;
            BondShown { id: o.id, with, incoming: o.incoming, text: wood::readable(&bond_text(o.incoming, &who(with), until, now)), until_ms: until }
        })
        .collect();
    let fresh: Vec<(u64, u32, String)> = kin.bonds.iter().filter(|b| b.incoming).map(|b| (b.id, b.with, b.text.clone())).collect();
    for (id, with, text) in fresh {
        if kin.noted.insert(id) {
            let free = matches!(ws.at(super::win::Anchor::Left), None | Some(Win::Log));
            if free {
                ws.open(Win::Person(with));
            }
            info!("ui: courting offer {id} from #{with}: {text}");
            let words = text.split("  ·  ").next().unwrap_or_default().to_string();
            let more = if free { "" } else { " Their window has it." };
            verbs.toasts.push(crate::verbs::Toast { text: format!("{words}{more}"), ok: None, at: time.elapsed_secs_f64() });
        }
    }
    if kin.noted.len() > 64 {
        let live: HashSet<u64> = conn.db.my_bond_offers().iter().map(|o| o.id).collect();
        kin.noted.retain(|id| live.contains(id));
    }
}

// ---- Log › People: family and community -------------------------------------------------------

#[derive(Component)]
pub struct KinHead;
#[derive(Component)]
pub struct KinRow(usize);
#[derive(Component)]
pub struct KinRowText(usize);
#[derive(Component)]
pub struct KinRowNote(usize);
#[derive(Component)]
pub struct CommunityBox;
#[derive(Component)]
pub struct CommunityName;
#[derive(Component)]
pub struct CommunityLine(usize);
/// The "People met" heading, shown only when family or community come first (`people::update`).
#[derive(Component)]
pub struct MetHead;

/// The family and community at the top of Log › People (`people::spawn`).
pub fn spawn_section(t: &mut ChildSpawnerCommands, f: &Fonts) {
    t.spawn((KinHead, Text::new("Family"), f.body(12.0, 800), TextColor(wood::muted()), Node { display: Display::None, margin: UiRect::top(Val::Px(2.0)), flex_shrink: 0.0, ..default() }, Pickable::IGNORE));
    for i in 0..KIN_ROWS {
        t.spawn((KinRow(i), Hot, Tag(format!("log:kin:{i}")), kit::Paint::Row, Lit(false), Node { flex_direction: FlexDirection::Column, padding: UiRect::axes(Val::Px(8.0), Val::Px(4.0)), border_radius: wood::r(6.0), display: Display::None, flex_shrink: 0.0, ..default() }, BackgroundGradient::default())).with_children(|r| {
            r.spawn((KinRowText(i), Text::new(""), wood::ink(f, 14.0, 800), Pickable::IGNORE));
            r.spawn((KinRowNote(i), Text::new(""), f.body(12.0, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
        });
    }
    t.spawn((CommunityBox, Tag("log:community".into()), Node { flex_direction: FlexDirection::Column, row_gap: Val::Px(1.0), padding: UiRect::axes(Val::Px(8.0), Val::Px(4.0)), margin: UiRect::top(Val::Px(4.0)), display: Display::None, flex_shrink: 0.0, ..default() }, Pickable::IGNORE)).with_children(|c| {
        c.spawn((Text::new("Community"), f.body(12.0, 800), TextColor(wood::muted()), Node { margin: UiRect::left(Val::Px(-8.0)), ..default() }, Pickable::IGNORE));
        c.spawn((CommunityName, Text::new(""), wood::ink(f, 14.0, 800), Pickable::IGNORE));
        for i in 0..COMMUNITY_LINES {
            c.spawn((CommunityLine(i), Text::new(""), f.body(12.0, 600), TextColor(wood::muted()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { display: Display::None, ..default() }, Pickable::IGNORE));
        }
    });
    t.spawn((MetHead, Text::new("People met"), f.body(12.0, 800), TextColor(wood::muted()), Node { display: Display::None, margin: UiRect::top(Val::Px(6.0)), flex_shrink: 0.0, ..default() }, Pickable::IGNORE));
}

// ---- a person window's courting card ----------------------------------------------------------

#[derive(Component)]
pub struct BondCard(u32);
#[derive(Component)]
pub struct BondText(u32);
#[derive(Component)]
pub struct BondAct(u32, usize);
#[derive(Component)]
pub struct BondActText(usize);

/// The courting card of a person window (`people::spawn`), under the trade offers' cards.
pub fn spawn_card(body: &mut ChildSpawnerCommands, f: &Fonts, id: u32) {
    body.spawn((BondCard(id), Node { flex_direction: FlexDirection::Column, row_gap: Val::Px(6.0), padding: UiRect::all(Val::Px(10.0)), border: wood::b(2.0), border_radius: wood::r(8.0), display: Display::None, flex_shrink: 0.0, ..default() }, BackgroundColor(wood::t().hot.0), BorderColor::all(wood::edge()), Pickable::IGNORE)).with_children(|o| {
        o.spawn((BondText(id), Text::new(""), wood::ink(f, 14.0, 700), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
        o.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(6.0), ..default() }, Pickable::IGNORE)).with_children(|b| {
            for j in 0..BOND_ACTS {
                kit::button_with(b, f, "", &format!("person:bond:{id}:{j}"), j > 0, BondAct(id, j), BondActText(j));
            }
        });
    });
}

/// Show the family, the community and the courting cards.
#[allow(clippy::type_complexity)]
pub fn update(
    kin: Res<Kin>,
    mut nodes: ParamSet<(Query<(&KinRow, &mut Node)>, Query<&mut Node, With<KinHead>>, Query<&mut Node, With<CommunityBox>>, Query<(&CommunityLine, &mut Node)>, Query<(&BondCard, &mut Node)>, Query<(&BondAct, &mut Node)>, Query<&mut Node, With<MetHead>>)>,
    mut texts: ParamSet<(Query<(&KinRowText, &mut Text)>, Query<(&KinRowNote, &mut Text)>, Query<&mut Text, With<CommunityName>>, Query<(&CommunityLine, &mut Text)>, Query<(&BondText, &mut Text)>, Query<(&BondActText, &mut Text)>)>,
    (talks, looks, net): (Res<super::people::Talks>, Res<Looks>, NonSend<Net>),
) {
    let met = !super::people::people_list(&talks, net.my_id, &looks).is_empty();
    for mut n in &mut nodes.p6() {
        show(&mut n, kin.any() && met);
    }
    for (r, mut n) in &mut nodes.p0() {
        show(&mut n, r.0 < kin.rows.len());
    }
    for mut n in &mut nodes.p1() {
        show(&mut n, !kin.rows.is_empty());
    }
    for mut n in &mut nodes.p2() {
        show(&mut n, kin.community.is_some());
    }
    let lines = kin.community.as_ref().map_or(&[][..], |(_, l)| l.as_slice());
    for (l, mut n) in &mut nodes.p3() {
        show(&mut n, l.0 < lines.len());
    }
    for (c, mut n) in &mut nodes.p4() {
        show(&mut n, kin.bond_with(c.0).is_some());
    }
    for (a, mut n) in &mut nodes.p5() {
        show(&mut n, a.1 < kin.acts.len() && kin.bond_with(a.0).is_some_and(|b| b.incoming));
    }
    for (r, mut t) in &mut texts.p0() {
        if let Some(k) = kin.rows.get(r.0) {
            set_text(&mut t, &k.title);
        }
    }
    for (r, mut t) in &mut texts.p1() {
        if let Some(k) = kin.rows.get(r.0) {
            set_text(&mut t, &k.note);
        }
    }
    if let Some((name, _)) = &kin.community {
        for mut t in &mut texts.p2() {
            set_text(&mut t, name);
        }
    }
    for (l, mut t) in &mut texts.p3() {
        if let Some(s) = lines.get(l.0) {
            set_text(&mut t, s);
        }
    }
    for (c, mut t) in &mut texts.p4() {
        if let Some(b) = kin.bond_with(c.0) {
            set_text(&mut t, &b.text);
        }
    }
    for (a, mut t) in &mut texts.p5() {
        if let Some((_, label)) = kin.acts.get(a.0) {
            set_text(&mut t, label);
        }
    }
}

/// Clicks: a relative's row opens their window; a courting card's button sends its act toward
/// the offer's maker (the rules say what it does).
pub fn clicks(ui: Res<super::hit::UiPointer>, tags: Query<&Tag>, kin: Res<Kin>, mut ws: ResMut<Windows>, mut verbs: ResMut<crate::verbs::Verbs>) {
    let Some(t) = kit::clicked(&ui, &tags) else { return };
    let parts: Vec<&str> = t.split(':').collect();
    match parts.as_slice() {
        ["log", "kin", i] => {
            if let Some(r) = i.parse::<usize>().ok().and_then(|i| kin.rows.get(i)) {
                ws.open(Win::Person(r.id));
            }
        }
        ["person", "bond", id, j] => {
            let (Ok(id), Some((skill, label))) = (id.parse::<u32>(), j.parse::<usize>().ok().and_then(|j| kin.acts.get(j)).cloned()) else { return };
            if kin.bond_with(id).is_none_or(|b| !b.incoming) {
                return;
            }
            info!("ui: {skill} toward #{id} (a courting offer)");
            verbs.send.push((crate::verbs::Aim::Creature { id }, crate::verbs::Choice { skill, item: None, want: None, words: false, say: None, label, have: 0 }));
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn who(name: Option<&str>, label: Option<&str>, here: bool) -> Who {
        Who { name: name.map(String::from), label: label.map(String::from), here }
    }

    #[test]
    fn relation_words_are_the_rules_own() {
        let t = KinTerms::default();
        assert_eq!(relation_word(&t, "parent", Some(Sex::Female)), "mother");
        assert_eq!(relation_word(&t, "parent", Some(Sex::Male)), "father");
        // Unseen (no sex seen): the relation's sex-neutral word.
        assert_eq!(relation_word(&t, "parent", None), "parent");
        assert_eq!(relation_word(&t, "child", Some(Sex::Male)), "son");
        assert_eq!(relation_word(&t, "child", Some(Sex::Female)), "daughter");
        // No neutral word in the rules: the relation as the views and minds' scenes name it.
        assert_eq!(relation_word(&t, "child", None), "child");
        assert_eq!(relation_word(&t, "partner", Some(Sex::Female)), "wife");
        assert_eq!(relation_word(&t, "partner", None), "partner");
        assert_eq!(relation_word(&t, "cousin", None), "cousin");
    }

    #[test]
    fn the_shipped_script_has_the_words_and_the_act() {
        let sc = living_rules::script::Scripts::new(include_str!("../../../scripts/skills.rhai")).unwrap();
        assert_eq!(relation_word(sc.kin(), "parent", Some(Sex::Female)), "mother");
        // The act that takes up a courting offer is on the card by its declaration.
        let acts = bond_acts(&sc);
        assert_eq!(acts.iter().map(|(s, _)| s.as_str()).collect::<Vec<_>>(), ["conceive"], "{acts:?}");
        assert!(sc.laws().bond_window_s > 0.0);
    }

    #[test]
    fn a_relative_is_named_only_from_what_i_know_or_see() {
        // Known by name (`my_known_names`), in sight.
        assert_eq!(kin_line("mother", &who(Some("Ada Fenner"), None, true)), ("Ada Fenner".into(), "your mother · here now".into()));
        // Known by name, unseen: no alive, health or place, only that they are not in sight.
        assert_eq!(kin_line("parent", &who(Some("Ada Fenner"), None, false)), ("Ada Fenner".into(), "your parent · not in sight".into()));
        // Seen, not known by name: the relation, not a stranger's looks.
        assert_eq!(kin_line("son", &who(None, Some("a boy in red"), true)), ("Your son".into(), "here now".into()));
        // Neither: the relation alone.
        assert_eq!(kin_line("parent", &who(None, None, false)), ("Your parent".into(), "not in sight".into()));
        for (t, n) in [kin_line("parent", &who(None, None, false)), kin_line("child", &who(Some("Wren"), None, false))] {
            for s in [t, n] {
                for leak in ["alive", "dead", "died", "hp", "health", " m ", "north", "south", "east", "west"] {
                    assert!(!s.to_lowercase().contains(leak), "{s:?} says {leak:?}");
                }
            }
        }
    }

    #[test]
    fn a_courting_card_names_the_suitor_or_says_a_suitor() {
        assert_eq!(bond_text(true, &who(None, None, false), 130_000, 10_000), "A suitor wants to start a family with you.  ·  2:00 left");
        assert_eq!(bond_text(true, &who(Some("Moss"), None, true), 70_500, 10_000), "Moss wants to start a family with you.  ·  1:00 left");
        assert_eq!(bond_text(true, &who(None, Some("a woman in green"), true), 15_000, 10_000), "A woman in green wants to start a family with you.  ·  0:05 left");
        assert_eq!(bond_text(false, &who(Some("Wren"), None, false), 100_000, 10_000), "You asked Wren to start a family.  ·  1:30 left");
        assert_eq!(bond_text(false, &who(None, None, false), 9_000, 10_000), "You asked them to start a family.  ·  0:00 left");
        assert_eq!(time_left(7_300_000, 0), "2 h left");
        assert_eq!((lowered("Your parent"), lowered("A suitor"), lowered("Ada Fenner"), lowered("Ann")), ("your parent".into(), "a suitor".into(), "Ada Fenner".into(), "Ann".into()));
    }

    fn community(founder: u32, founded_ms: u64, since_ms: u64) -> MyCommunity {
        MyCommunity { id: 3, name: "Riverfolk".into(), founder, founded_ms, home_x: 100.0, home_y: 0.0, since_ms }
    }

    #[test]
    fn the_community_says_who_founded_it_when_i_joined_and_where_home_is() {
        let day = |ms: u64| (ms > 0).then(|| ms / 1000);
        let at = Some((0.0, 100.0));
        // Home 100 m east and 100 m north of me: the rules' bearing words.
        assert_eq!(community_lines(&community(7, 2_000, 5_000), 1, &who(Some("Ada Fenner"), None, false), day, at), vec!["Founded by Ada Fenner on day 2 · you joined on day 5".to_string(), "Home: 140 m northeast".to_string()]);
        // A founder I neither know nor see: no name.
        assert_eq!(community_lines(&community(7, 2_000, 5_000), 1, &who(None, None, false), day, None), vec!["Founded on day 2 · you joined on day 5".to_string()]);
        // I founded it the day I joined.
        assert_eq!(community_lines(&community(1, 2_000, 2_000), 1, &who(None, None, false), day, Some((100.0, 1.0))), vec!["You founded it on day 2".to_string(), "Home: here".to_string()]);
        // A community older than the world's clock: no day.
        assert_eq!(community_lines(&community(7, 0, 0), 1, &who(None, Some("a man in blue"), true), day, None), vec!["Founded by a man in blue".to_string()]);
    }
}
