//! Public-feed scoping on the client (docs/FEED_SCOPING.md, "Client subscriptions", "Remembered
//! vs current", "The look and act path", "Reconnect").
//!
//! The world's one public `feed_scope` row (`stage`; no row is stage 0) is the only thing this
//! client reads to choose where structures, gates and resources come from:
//!
//! - **legacy** (stage 0, as main): the public `structure`, `gate` and `resource_node` rows, the
//!   near window's `structure` and `resource_node` by chunk and `gate` whole in the base;
//! - **scoped** (stage ≥ 1): what my character sees now (`my_things`), what it remembers of
//!   sight-scoped things (`my_remembered_things`), owner labels (`my_owners`), depletion it saw
//!   (`my_stock`) and fuel it found by looking fires over (`my_fuel_seen`) in the base, and the
//!   public map projections (`map_structure`, `map_resource`) in the near window by chunk.
//!
//! `net.rs` switches between the two make-before-break: the new base and the new near window are
//! subscribed beside the old ones, and only when both are applied are the old ones dropped and
//! the reads moved ([`reads`]). Until then everything is drawn from the old rows. The switch is
//! independent of the perception tiers' switch (`net::perception_law`), which chooses only the
//! creature streams.
//!
//! [`things`] is the one source every reader takes (`world::things`, `verbs.rs`, `sightfield.rs`):
//! under the legacy feed the legacy rows; under the scoped feed a thing in `my_things` is live, a
//! key in `my_remembered_things` and not in `my_things` is last seen (drawn where and as it was
//! last seen), architecture and landmarks from the map projections are drawn at full size, and
//! anything else is unknown (not drawn, not offered).
//!
//! SpacetimeDB documentation (2.0 docs, against the pinned 2.14.1 SDK):
//! [subscriptions](https://spacetimedb.com/docs/clients/subscriptions/) (subscribe the new set
//! before unsubscribing the old; `on_applied` once its rows are in the client cache; overlapping
//! sets keep a row while any set holds it) and
//! [views](https://spacetimedb.com/docs/functions/views/) (sender-scoped views re-evaluated per
//! subscriber; a `primary_key` gives updates, so a fire going out is an update of its key).

use living_bindings::*;
use spacetimedb_sdk::Table;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};

/// Where structures, gates and resources come from.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Feed {
    /// Stage 0: the legacy public tables, as main.
    #[default]
    Legacy,
    /// Stage ≥ 1: the sender-scoped views and the map projections.
    Scoped,
}

impl Feed {
    pub fn of_stage(stage: u8) -> Feed {
        if stage == 0 { Feed::Legacy } else { Feed::Scoped }
    }

    pub fn name(self) -> &'static str {
        match self {
            Feed::Legacy => "legacy",
            Feed::Scoped => "scoped",
        }
    }

    /// The feed's tag in a window's key (`net.rs`).
    pub fn tag(self) -> u32 {
        match self {
            Feed::Legacy => 0,
            Feed::Scoped => 1,
        }
    }

    pub fn of_tag(tag: u32) -> Feed {
        if tag == 0 { Feed::Legacy } else { Feed::Scoped }
    }
}

/// The world's stage as the static `feed_scope` row says (absent: 0).
pub fn stage(db: &RemoteTables) -> u8 {
    db.feed_scope().iter().next().map_or(0, |r| r.stage)
}

/// The scoped base views (in the base subscription beside the perceived set).
pub const SCOPED_BASE: &[&str] = &[
    // What my character sees now: sight-scoped things in sight, and the state of allowlisted
    // things that carry it (gates, fires), keyed `class << 56 | id`.
    "SELECT * FROM my_things",
    // What it last saw of sight-scoped things and gates, with their state then.
    "SELECT * FROM my_remembered_things",
    // Owner labels for architecture, as the `owner_shown` law grants them.
    "SELECT * FROM my_owners",
    // Depletion it saw (`seen_stock`, both controllers).
    "SELECT * FROM my_stock",
    // Fuel it found on fires by looking them over (`inspect`).
    "SELECT * FROM my_fuel_seen",
];

/// The feed's queries in the base subscription for a world kind (`land`: whether a `land` row
/// exists). Legacy land worlds take every gate (a hundred rows on a town, changed rarely: a shut
/// gate blocks sight, `sightfield.rs`); legacy tile worlds nothing; scoped worlds the views.
pub fn base_queries(feed: Feed, land: bool) -> Vec<&'static str> {
    match feed {
        Feed::Legacy if land => vec!["SELECT * FROM gate"],
        Feed::Legacy => Vec::new(),
        Feed::Scoped => SCOPED_BASE.to_vec(),
    }
}

/// The feed's tables in the near window, by chunk: (resources, structures).
pub fn window_tables(feed: Feed) -> (&'static str, &'static str) {
    match feed {
        Feed::Legacy => ("resource_node", "structure"),
        Feed::Scoped => ("map_resource", "map_structure"),
    }
}

// ---- the reads ---------------------------------------------------------------------------------

/// The feed reads take (`net.rs` moves it when a switch completes; one connection per process).
static READS: AtomicU8 = AtomicU8::new(0);
/// The base subscription is applied and no join (or reclaim through join) awaits its result: an
/// empty `my_things` means nothing sight-scoped is in sight. Before that the scoped source gives
/// the map projections alone, never "remembered, so out of sight" for what may be in sight.
static BASE_IN: AtomicBool = AtomicBool::new(false);
static JOINING: AtomicBool = AtomicBool::new(false);
/// A feed switch is under way (`net.rs` has a base for the other feed subscribed, not yet in).
static SWITCHING: AtomicBool = AtomicBool::new(false);

pub fn reads() -> Feed {
    Feed::of_tag(READS.load(Ordering::Acquire) as u32)
}

pub(crate) fn set_reads(f: Feed) {
    READS.store(f.tag() as u8, Ordering::Release);
}

/// A new connection: nothing is in until its base is applied.
pub(crate) fn reset() {
    BASE_IN.store(false, Ordering::Release);
    JOINING.store(false, Ordering::Release);
    SWITCHING.store(false, Ordering::Release);
}

pub(crate) fn set_switching(on: bool) {
    SWITCHING.store(on, Ordering::Release);
}

/// While a feed switch is under way the drawing keeps what it drew (`world::things` defers
/// despawns): the old feed's rows can go before the new set is in. Law off at stage 1 clears the
/// map projections in the same transaction that sets stage 0, so the scoped rows are gone in the
/// frame the client learns it must subscribe the legacy set; and a client still subscribing the
/// scoped set when the cut lands loses the legacy rows. Nothing new is drawn from held state: a
/// held entity is only not taken away until the switch is done, then reconciled.
pub fn switching() -> bool {
    SWITCHING.load(Ordering::Acquire)
}

pub(crate) fn base_applied() {
    BASE_IN.store(true, Ordering::Release);
}

pub(crate) fn joining(on: bool) {
    JOINING.store(on, Ordering::Release);
}

/// Whether the scoped views can be read as "what I see now" (see [`BASE_IN`]).
pub fn settled() -> bool {
    BASE_IN.load(Ordering::Acquire) && !JOINING.load(Ordering::Acquire)
}

// ---- things ------------------------------------------------------------------------------------

/// Where a thing's row came from.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Source {
    /// The legacy public rows (stage 0, or the switch not yet done).
    Legacy,
    /// In sight now (`my_things`).
    Live,
    /// Out of sight, as last seen (`my_remembered_things`), at authority ms.
    Remembered { seen_ms: u64 },
    /// Architecture or a landmark from the public map, with no state.
    Map,
}

/// A resource or structure as this client knows it.
#[derive(Clone, PartialEq, Debug)]
pub struct Thing {
    /// 0 a resource, 1 a structure (`scene.things` keys on (class, id)).
    pub class: u8,
    pub id: u64,
    pub kind: String,
    pub x: f32,
    pub y: f32,
    pub source: Source,
    /// Whether it burns as seen (legacy: worked out from the row; live; last seen), None unknown
    /// (map). Scoped rows say false for a kind that is no fire; [`Thing::glows`] reads it.
    pub lit: Option<bool>,
    /// A gate's state as seen (legacy, live, last seen), None for anything else or unknown.
    pub open: Option<bool>,
    /// A resource's units left and full stock (legacy: the amount now, regrowth interpolated;
    /// live: `left`/`max`), None when only its landmark is known (full, or out of sight).
    pub left: Option<f32>,
    pub max: Option<f32>,
    /// Its owner as my client may know it (legacy: the row; scoped: the copy's grant, else
    /// `my_owners`); 0 none or not granted.
    pub owner: u32,
    /// Legacy only: the row's `lit_until_ms`, for the rules' fire state.
    pub lit_until_ms: Option<u64>,
    /// The drawn size ([`Thing::fill`]).
    pub drawn: f32,
}

impl Thing {
    pub fn key(&self) -> (u8, u64) {
        (self.class, self.id)
    }

    pub fn class_name(&self) -> &'static str {
        if self.class == 0 { "resource" } else { "structure" }
    }

    /// Whether it may be acted on (in sight, or the legacy feed's rows): a remembered thing is
    /// only a place to go to.
    pub fn actionable(&self) -> bool {
        !matches!(self.source, Source::Remembered { .. })
    }

    /// The drawn size of a resource: what is left of its full stock, 0.4–1.0 (main's rule: a
    /// legacy row's `amount` as it came, without regrowth since; a live copy's `left / max`);
    /// full when only its landmark is known.
    pub fn fill(&self) -> f32 {
        self.drawn
    }

    /// What an act's check takes as its amount: what is left; a landmark seen at full stock (no
    /// copy) or a remembered one is taken as having what is asked (as a target's pack is,
    /// `verbs::check_unit`): the authority decides.
    pub fn amount(&self) -> f32 {
        self.left.unwrap_or(f32::MAX)
    }

    /// Whether it is drawn burning. `burns`: the kind's `burns` trait as the world's rules say
    /// (`Some(true)` a fire that eats fuel, `Some(false)` anything else, None while the rules have
    /// not compiled here). A fire that eats fuel burns as seen (unknown: drawn out); any other kind
    /// is drawn as main drew it (lit panes, a plain campfire always burning).
    pub fn glows(&self, burns: Option<bool>) -> bool {
        match burns {
            Some(true) => self.lit.unwrap_or(false),
            Some(false) => true,
            None => self.lit.unwrap_or(true),
        }
    }
}

/// Whether a legacy structure burns at `now` (authority ms): one whose kind `burns` fuel while its
/// `lit_until_ms` is ahead, any other always; `burns` None while the world's rules are not
/// compiled here yet, when one never lit (0) or lit till later counts as burning (main's rule).
pub fn burning(burns: Option<bool>, until: u64, now: u64) -> bool {
    match burns {
        Some(true) => living_rules::fire::lit(until, now),
        Some(false) => true,
        None => until == 0 || living_rules::fire::lit(until, now),
    }
}

/// Every resource and structure this client knows, from the feed reads take. `now_ms` is the
/// authority clock (regrowth on legacy rows); `burns(kind)` as in [`Thing::glows`].
pub fn things(db: &RemoteTables, now_ms: f64, burns: &dyn Fn(&str) -> Option<bool>) -> Vec<Thing> {
    match reads() {
        Feed::Legacy => legacy(db, now_ms, burns),
        Feed::Scoped => {
            let owners: HashMap<u64, u32> = db.my_owners().iter().map(|o| (o.structure, o.owner)).collect();
            let settled = settled();
            scoped(
                if settled { db.my_things().iter().collect() } else { Vec::new() },
                if settled { db.my_remembered_things().iter().collect() } else { Vec::new() },
                db.map_structure().iter().collect(),
                db.map_resource().iter().collect(),
                &owners,
            )
        }
    }
}

fn legacy(db: &RemoteTables, now_ms: f64, burns: &dyn Fn(&str) -> Option<bool>) -> Vec<Thing> {
    let gates: HashMap<(i32, i32), bool> = db.gate().iter().map(|g| ((g.x, g.y), g.open)).collect();
    let mut v: Vec<Thing> = db.resource_node().iter().map(|r| of_node(r, now_ms)).collect();
    v.extend(db.structure().iter().map(|s| {
        let open = gates.get(&(s.x.floor() as i32, s.y.floor() as i32)).copied();
        of_structure(s, open, now_ms, burns)
    }));
    v
}

/// A legacy resource row: what is left now, its regrowth since the row interpolated (main's rule).
fn of_node(r: ResourceNode, now_ms: f64) -> Thing {
    let left = (r.amount + r.regen * ((now_ms - r.at_ms as f64).max(0.0) / 60_000.0) as f32).min(r.max);
    let drawn = fill_of(r.amount, r.max);
    Thing { class: 0, id: r.id, kind: r.kind, x: r.x, y: r.y, source: Source::Legacy, lit: None, open: None, left: Some(left), max: Some(r.max), owner: 0, lit_until_ms: None, drawn }
}

/// A legacy structure row (`open`: the `gate` row on its tile, if any).
fn of_structure(s: Structure, open: Option<bool>, now_ms: f64, burns: &dyn Fn(&str) -> Option<bool>) -> Thing {
    let lit = Some(burning(burns(&s.kind), s.lit_until_ms, now_ms.max(0.0) as u64));
    Thing { class: 1, id: s.id, kind: s.kind, x: s.x, y: s.y, source: Source::Legacy, lit, open, left: None, max: None, owner: s.owner, lit_until_ms: Some(s.lit_until_ms), drawn: 1.0 }
}

fn of_seen(t: SeenThing, owner_of: impl Fn(u64) -> u32) -> Thing {
    let owner = if t.owner != 0 { t.owner } else { owner_of(t.id) };
    let drawn = match (t.left, t.max) {
        (Some(l), Some(m)) => fill_of(l as f32, m as f32),
        _ => 1.0,
    };
    Thing { class: t.class, id: t.id, kind: t.kind, x: t.x, y: t.y, source: Source::Live, lit: Some(t.lit), open: t.open, left: t.left.map(|l| l as f32), max: t.max.map(|m| m as f32), owner, lit_until_ms: None, drawn }
}

fn of_remembered(r: RememberedSeen, owner_of: impl Fn(u64) -> u32) -> Thing {
    Thing { class: r.class, id: r.id, kind: r.kind, x: r.x, y: r.y, source: Source::Remembered { seen_ms: r.seen_ms }, lit: Some(r.lit), open: r.open, left: None, max: None, owner: owner_of(r.id), lit_until_ms: None, drawn: 1.0 }
}

fn of_map(class: u8, id: u64, kind: String, x: f32, y: f32, owner: u32) -> Thing {
    Thing { class, id, kind, x, y, source: Source::Map, lit: None, open: None, left: None, max: None, owner, lit_until_ms: None, drawn: 1.0 }
}

/// What is left of a full stock, as drawn: 0.4–1.0 (main's rule).
fn fill_of(left: f32, max: f32) -> f32 {
    (left / max.max(1.0)).clamp(0.4, 1.0)
}

/// The scoped feed's things: live over remembered over the map, by key (pure, for tests).
pub fn scoped(live: Vec<SeenThing>, remembered: Vec<RememberedSeen>, map_s: Vec<MapStructure>, map_r: Vec<MapResource>, owners: &HashMap<u64, u32>) -> Vec<Thing> {
    let mut by: HashMap<(u8, u64), Thing> = HashMap::new();
    let owner_of = |id: u64| owners.get(&id).copied().unwrap_or(0);
    for r in map_r {
        by.insert((0, r.id), of_map(0, r.id, r.kind, r.x, r.y, 0));
    }
    for s in map_s {
        by.insert((1, s.id), of_map(1, s.id, s.kind, s.x, s.y, owner_of(s.id)));
    }
    for r in remembered {
        by.insert((r.class, r.id), of_remembered(r, owner_of));
    }
    for t in live {
        by.insert((t.class, t.id), of_seen(t, owner_of));
    }
    let mut v: Vec<Thing> = by.into_values().collect();
    v.sort_by_key(|t| t.key());
    v
}

/// One thing by its class and id, by point lookups in the feed reads take (as [`things`]).
pub fn find(db: &RemoteTables, class: u8, id: u64, now_ms: f64, burns: &dyn Fn(&str) -> Option<bool>) -> Option<Thing> {
    match reads() {
        Feed::Legacy if class == 0 => db.resource_node().id().find(&id).map(|r| of_node(r, now_ms)),
        Feed::Legacy => db.structure().id().find(&id).map(|s| {
            let open = (s.kind == "gate").then(|| db.gate().iter().find(|g| (g.x, g.y) == (s.x.floor() as i32, s.y.floor() as i32)).map(|g| g.open)).flatten();
            of_structure(s, open, now_ms, burns)
        }),
        Feed::Scoped => {
            let owner_of = |id: u64| db.my_owners().structure().find(&id).map_or(0, |o| o.owner);
            let key = (class as u64) << 56 | id;
            let live = settled().then(|| db.my_things().key().find(&key)).flatten().map(|t| of_seen(t, owner_of));
            let remembered = || settled().then(|| db.my_remembered_things().key().find(&key)).flatten().map(|r| of_remembered(r, owner_of));
            let map = || match class {
                0 => db.map_resource().id().find(&id).map(|r| of_map(0, r.id, r.kind, r.x, r.y, 0)),
                _ => db.map_structure().id().find(&id).map(|s| of_map(1, s.id, s.kind, s.x, s.y, owner_of(s.id))),
            };
            live.or_else(remembered).or_else(map)
        }
    }
}

/// The shut gates' tiles (`floor(x)`, `floor(y)`): legacy from the `gate` rows; scoped a gate
/// seen shut now, else one remembered shut. A gate never seen is not among them: it does not
/// block in the Shade, and the authority's collision still decides.
pub fn shut_gates(db: &RemoteTables) -> Vec<(i32, i32)> {
    match reads() {
        Feed::Legacy => db.gate().iter().filter(|g| !g.open).map(|g| (g.x, g.y)).collect(),
        Feed::Scoped if settled() => shut_of(db.my_things().iter().map(|t| (t.key, t.x, t.y, t.open)), db.my_remembered_things().iter().map(|t| (t.key, t.x, t.y, t.open))),
        // Before the views are in: what is remembered (stored rows), never more.
        Feed::Scoped => shut_of(std::iter::empty(), db.my_remembered_things().iter().map(|t| (t.key, t.x, t.y, t.open))),
    }
}

/// Shut gates from live and remembered (key, x, y, open) rows: live wins for a key in both.
pub fn shut_of(live: impl Iterator<Item = (u64, f32, f32, Option<bool>)>, remembered: impl Iterator<Item = (u64, f32, f32, Option<bool>)>) -> Vec<(i32, i32)> {
    let mut by: HashMap<u64, (f32, f32, Option<bool>)> = remembered.map(|(k, x, y, o)| (k, (x, y, o))).collect();
    for (k, x, y, o) in live {
        by.insert(k, (x, y, o));
    }
    let mut v: Vec<(i32, i32)> = by.into_values().filter(|(_, _, o)| *o == Some(false)).map(|(x, y, _)| (x.floor() as i32, y.floor() as i32)).collect();
    v.sort_unstable();
    v.dedup();
    v
}

// ---- fires -------------------------------------------------------------------------------------

/// What my character found on a fire by looking it over: the hours of burning left then and when
/// (authority ms), from `my_fuel_seen` (my living character's rows).
pub fn fuel_seen(db: &RemoteTables, me: u32, id: u64) -> Option<(f32, u64)> {
    db.my_fuel_seen().iter().filter(|r| r.observer == me && r.target == id).max_by_key(|r| r.seen_ms).map(|r| (r.left, r.seen_ms))
}

/// A fire's facts for the rules' checks under the scoped feed: lit as seen; the fuel held now
/// projected from the last look at its burn `rate` (units a world hour) while it is seen lit,
/// 0 when it is out, and unknown (NaN) when it was never looked over: a NaN fuel refuses no
/// fuel comparison in the checks (`make`'s "too little fuel", `feed`'s "holds at most"), as an
/// unknown pack is assumed to hold what is asked; the authority decides.
pub fn fire_check(lit: bool, seen: Option<(f32, u64)>, rate: f32, now: u64, day_ms: u64) -> f32 {
    if !lit {
        return 0.0;
    }
    match seen {
        Some((hours, at)) => {
            let hour_ms = (day_ms.max(1) as f64 / 24.0).max(1.0);
            let since = now.saturating_sub(at) as f64 / hour_ms;
            ((hours as f64 - since).max(0.0) * rate as f64) as f32
        }
        None => f32::NAN,
    }
}

/// How the fuel found on a fire reads in a title: "about N h of fuel left, as of when you looked
/// it over, M ago" (`ago` in real seconds of the authority clock).
pub fn fuel_words(hours: f32, ago_s: f64) -> String {
    let left = if hours <= 0.0 {
        "no fuel left".to_string()
    } else if hours < 1.0 {
        "less than an hour of fuel left".to_string()
    } else {
        format!("about {:.0} h of fuel left", hours.round())
    };
    format!("{left}, as of when you looked it over, {}", ago_words(ago_s))
}

/// "just now", "5 s ago", "3 min ago", "2 h ago".
pub fn ago_words(s: f64) -> String {
    let s = s.max(0.0);
    if s < 2.0 {
        "just now".to_string()
    } else if s < 90.0 {
        format!("{:.0} s ago", s)
    } else if s < 5400.0 {
        format!("{:.0} min ago", s / 60.0)
    } else {
        format!("{:.0} h ago", s / 3600.0)
    }
}

/// The feed's state for the UI dump (`ui::dump`, verify-ui's `feed-scope`): the stage, the feed
/// reads take, whether the views are settled, and every thing known with its source and state.
pub fn dump(db: &RemoteTables, now_ms: f64, burns: &dyn Fn(&str) -> Option<bool>) -> serde_json::Value {
    let all = things(db, now_ms, burns);
    let mut counts: HashMap<&'static str, usize> = HashMap::new();
    for t in &all {
        *counts.entry(source_name(t.source)).or_default() += 1;
    }
    serde_json::json!({
        "stage": stage(db),
        "reads": reads().name(),
        "settled": settled(),
        "counts": counts,
        "shut_gates": shut_gates(db),
        "things": all.iter().map(|t| serde_json::json!({"class": t.class, "id": t.id, "kind": t.kind, "x": t.x, "y": t.y, "source": source_name(t.source),
            "seen_ms": match t.source { Source::Remembered { seen_ms } => Some(seen_ms), _ => None }, "lit": t.lit, "gate_open": t.open, "left": t.left, "max": t.max, "fill": t.fill(), "owner": t.owner})).collect::<Vec<_>>(),
    })
}

pub fn source_name(s: Source) -> &'static str {
    match s {
        Source::Legacy => "legacy",
        Source::Live => "live",
        Source::Remembered { .. } => "remembered",
        Source::Map => "map",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seen(class: u8, id: u64, kind: &str, lit: bool, open: Option<bool>, left: Option<u32>, max: Option<u32>) -> SeenThing {
        SeenThing { key: (class as u64) << 56 | id, class, id, kind: kind.into(), x: id as f32, y: 2.0, open, lit, owner: 0, left, max }
    }

    fn remembered(id: u64, kind: &str, lit: bool, open: Option<bool>, seen_ms: u64) -> RememberedSeen {
        RememberedSeen { key: 1 << 56 | id, class: 1, id, kind: kind.into(), x: id as f32 + 0.5, y: 3.0, open, lit, seen_ms }
    }

    fn map_s(id: u64, kind: &str) -> MapStructure {
        MapStructure { id, kind: kind.into(), x: id as f32, y: 1.0, chunk: 0 }
    }

    fn map_r(id: u64, kind: &str) -> MapResource {
        MapResource { id, kind: kind.into(), x: id as f32, y: 1.0, chunk: 0 }
    }

    #[test]
    fn the_stage_chooses_the_feed_and_its_queries() {
        assert_eq!(Feed::of_stage(0), Feed::Legacy);
        assert_eq!(Feed::of_stage(1), Feed::Scoped);
        assert_eq!(Feed::of_stage(2), Feed::Scoped);
        assert_eq!(base_queries(Feed::Legacy, true), ["SELECT * FROM gate"]);
        assert!(base_queries(Feed::Legacy, false).is_empty());
        assert_eq!(base_queries(Feed::Scoped, true), SCOPED_BASE);
        assert_eq!(base_queries(Feed::Scoped, false), SCOPED_BASE);
        assert_eq!(window_tables(Feed::Legacy), ("resource_node", "structure"));
        assert_eq!(window_tables(Feed::Scoped), ("map_resource", "map_structure"));
        for f in [Feed::Legacy, Feed::Scoped] {
            assert_eq!(Feed::of_tag(f.tag()), f);
        }
    }

    #[test]
    fn live_wins_over_remembered_over_the_map_and_unknown_is_absent() {
        let mut owners = HashMap::new();
        owners.insert(10, 7);
        let v = scoped(
            vec![seen(1, 20, "hearth", true, None, None, None), seen(0, 30, "berry_bush", false, None, Some(2), Some(8)), seen(1, 11, "gate", false, Some(false), None, None)],
            vec![remembered(20, "hearth", false, None, 5), remembered(21, "remains", false, None, 6), remembered(11, "gate", false, Some(true), 4)],
            vec![map_s(10, "house"), map_s(11, "gate")],
            vec![map_r(30, "berry_bush"), map_r(31, "tree")],
            &owners,
        );
        let by: HashMap<(u8, u64), &Thing> = v.iter().map(|t| (t.key(), t)).collect();
        // Live: lit as the copy says, and a depleted bush drawn from left / max.
        assert_eq!(by[&(1, 20)].source, Source::Live);
        assert_eq!(by[&(1, 20)].lit, Some(true));
        assert!((by[&(0, 30)].fill() - 0.4).abs() < 1e-6, "2 of 8 clamps to 0.4");
        assert_eq!(by[&(0, 30)].amount(), 2.0);
        // A gate in sight: shut now, though remembered open.
        assert_eq!(by[&(1, 11)].open, Some(false));
        assert_eq!(by[&(1, 11)].source, Source::Live);
        // Remembered, out of sight: where and as it was last seen, not acted on.
        let rem = by[&(1, 21)];
        assert_eq!(rem.source, Source::Remembered { seen_ms: 6 });
        assert_eq!((rem.x, rem.y), (21.5, 3.0));
        assert!(!rem.actionable());
        // Architecture and landmarks at full size, owners from my_owners.
        assert_eq!(by[&(1, 10)].source, Source::Map);
        assert_eq!(by[&(1, 10)].owner, 7);
        assert_eq!(by[&(0, 31)].fill(), 1.0);
        assert_eq!(by[&(0, 31)].amount(), f32::MAX);
        assert_eq!(v.len(), 6, "{v:?}");
    }

    #[test]
    fn a_fire_glows_as_seen_and_other_kinds_as_main_drew_them() {
        let t = |lit| Thing { class: 1, id: 1, kind: "hearth".into(), x: 0.0, y: 0.0, source: Source::Live, lit, open: None, left: None, max: None, owner: 0, lit_until_ms: None, drawn: 1.0 };
        assert!(t(Some(true)).glows(Some(true)));
        assert!(!t(Some(false)).glows(Some(true)));
        assert!(!t(None).glows(Some(true)), "a fuel fire never seen burning is drawn out");
        // A house's copy says lit false (no fire): drawn with its lit panes, as main.
        assert!(t(Some(false)).glows(Some(false)));
        assert!(t(None).glows(None));
        // Legacy: main's rule.
        assert!(burning(Some(true), 10, 5) && !burning(Some(true), 5, 10));
        assert!(burning(Some(false), 0, 10) && burning(None, 0, 10) && !burning(None, 5, 10));
    }

    #[test]
    fn shut_gates_come_from_live_else_remembered_and_never_seen_ones_are_open() {
        let k = |id: u64| 1u64 << 56 | id;
        let live = vec![(k(1), 4.5, 6.5, Some(true)), (k(2), 8.2, 9.9, Some(false))];
        let rem = vec![(k(1), 4.5, 6.5, Some(false)), (k(3), 12.0, 3.0, Some(false)), (k(4), 1.0, 1.0, Some(true))];
        // 1: open in sight though remembered shut; 2: shut in sight; 3: remembered shut; 4:
        // remembered open; a gate never seen has no row at all.
        assert_eq!(shut_of(live.into_iter(), rem.into_iter()), vec![(8, 9), (12, 3)]);
    }

    #[test]
    fn fuel_is_projected_from_the_last_look_and_unknown_never_refuses() {
        let day = 24 * 60_000; // an hour a minute
        assert_eq!(fire_check(false, Some((4.0, 0)), 3.0, 10, day), 0.0);
        assert!((fire_check(true, Some((4.0, 0)), 3.0, 60_000, day) - 9.0).abs() < 1e-4, "3 h left at 3 a hour");
        assert_eq!(fire_check(true, Some((1.0, 0)), 3.0, 5 * 60_000, day), 0.0);
        assert!(fire_check(true, None, 3.0, 0, day).is_nan());
        assert_eq!(fuel_words(4.2, 125.0), "about 4 h of fuel left, as of when you looked it over, 2 min ago");
        assert_eq!(fuel_words(0.0, 1.0), "no fuel left, as of when you looked it over, just now");
    }
}
