//! Frames: what a player's client is shown of the others in its scene is delivered once per
//! frame, at a cadence per viewer (docs/PERCEPTION.md, "Frames").
//!
//! In SpacetimeDB 2.14.1 a view re-runs in full, inside the writing transaction, whenever a row
//! it read changed, and its whole result is deleted and inserted again
//! (`call_views_with_tx_at`, `materialize_view_arg_hash`). When the `seen_*` views read the
//! perceived creatures' own rows (`body`, `fighter`, a band written at each blow), every move
//! re-ran the view of every player who saw it: players × changes × rows per view, cubic in the
//! size of a crowd.
//!
//! So the views read per-viewer copies instead: `motion_seen` (`seen_bodies`), `fighter_seen`
//! (`seen_fighters`), `doing_seen` (`seen_doing`), the band of `projected` (`seen_characters`),
//! the onlookers' `combat_seen` rows (`my_combat`) and the released `line_seen` rows
//! (`my_experience`). Each view reads a handful of keys, not one per row: when a refreshed view
//! commits, 2.14.1 drops its old read set by scanning every view's read set in the database
//! (`TableReadSet::remove_view_call`), so the total number of keys read is a cost of every
//! refresh. The authority keeps
//! writing the truth where it always did; the tick copies what changed into a viewer's rows at
//! that viewer's frame, in one transaction, so each of its views re-runs at most once per frame
//! however many writes the frame covers. A player's own character is read directly, so its own
//! moves, blows taken and outcomes reach it in their own transaction.
//!
//! Which creatures changed since a viewer's last frame is kept in module memory (2.14.1 runs
//! every reducer and view in one module instance; a panic replaces it). A fresh instance
//! compares a viewer's whole scene at its first frame, so nothing is lost with the memory.
//!
//! The cadence: a frame re-materializes about one row per creature in the scene per view, so
//! a viewer's interval grows with its scene ([`interval`]): every other tick for a small scene,
//! down to [`FRAME_MAX_MS`] in a crowd. A step serves at most [`FRAME_ROWS_PER_TICK`] rows of
//! scene, stalest viewers first, so the work frames add to one step is bounded: when more is
//! due than that, frames come less often (the delivery's back-pressure) instead of the tick
//! running late.

use crate::combat::Seen;
use crate::common;
use crate::perception::Moving;
use crate::tables::*;
use spacetimedb::{Identity, ReducerContext, Table};
use std::cell::{Cell, RefCell};
use std::collections::{HashMap, HashSet, VecDeque};

/// The shortest interval between a viewer's frames: every other tick (30 Hz). Clients
/// extrapolate others' motion segments between rows, as they always did between writes.
pub const FRAME_MIN_MS: u64 = 33;
/// The longest, for a crowded scene before the load stretch.
pub const FRAME_MAX_MS: u64 = 100;
/// Rows of scene a viewer's frames may re-materialize per second and view (the interval is
/// the scene's size over this).
pub const SCENE_ROWS_PER_S: u64 = 2_000;
/// How long an onlooker's feed row stays in `my_combat` once released (ms). The client reads
/// each row once (by id), so a row needs only to reach it; a shorter stay keeps the feed small
/// in a battle, where a player sees a few hundred events a second.
pub const ONLOOKER_MS: u64 = 300;
/// The scene rows (creatures in the scenes of the viewers served) one step's frames may cover.
pub const FRAME_ROWS_PER_TICK: usize = 2_500;
/// How often a viewer's projections follow others' health at most (ms): the band and exact
/// health `seen_characters` shows (the client draws health bars from `seen_fighters`, which
/// carries the band at every frame; the exact health an appraisal reveals follows each second).
pub const BAND_MS: u64 = 1_000;
/// Experience lines kept released per character in `my_experience` (the newest).
pub const LINES_SHOWN: usize = 64;
/// Lines are released at most this often per character (ms).
pub const LINES_MS: u64 = 100;

/// The key of a viewer's `motion_seen` row of a creature.
pub fn key(viewer: u32, body: u32) -> u64 {
    ((viewer as u64) << 32) | body as u64
}

struct Viewer {
    who: Identity,
    /// The creatures it perceives (not itself), as the last sweep left them; `None` until a
    /// sweep has run in this module instance.
    scene: Option<HashSet<u32>>,
    /// Changes marked after this sequence number are news to it.
    seq: u64,
    /// Compare the whole scene at the next frame (a fresh instance, a new scene).
    full: bool,
    last_ms: u64,
    lines_ms: u64,
    /// When, and up to which change, its projections last followed health.
    band_ms: u64,
    band_seq: u64,
    /// Onlookers' feed events waiting for the frame, with their amounts.
    events: Vec<(Seen, f32)>,
    /// This viewer's feed rows by expiry (ms, row id).
    feed: VecDeque<(u64, u64)>,
}

impl Viewer {
    fn new(who: Identity) -> Self {
        Self { who, scene: None, seq: 0, full: true, last_ms: 0, lines_ms: 0, band_ms: 0, band_seq: 0, events: Vec::new(), feed: VecDeque::new() }
    }
}

thread_local! {
    static SEQ: Cell<u64> = const { Cell::new(0) };
    /// The sequence number of each creature's last change of motion, fighter row, and health.
    static MOVED: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    static FOUGHT: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    static HURT: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    static DID: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    /// Players' living characters, by character id.
    static VIEWERS: RefCell<HashMap<u32, Viewer>> = RefCell::new(HashMap::new());
    /// What creatures are like now, read once per `deliver` and shared by every viewer's frame
    /// in it (frames run after the tick's writes). `None` outside `deliver`: reads go to the
    /// tables.
    static NOW: RefCell<Option<Sources>> = const { RefCell::new(None) };
}

#[derive(Default)]
struct Sources {
    motion: HashMap<u32, Option<Moving>>,
    fighter: HashMap<u32, Option<Fighter>>,
    health: HashMap<u32, Option<(f32, f32)>>,
    doing: HashMap<u32, Option<Doing>>,
}

fn cached<V: Clone>(pick: impl FnOnce(&mut Sources) -> &mut HashMap<u32, V>, id: u32, read: impl FnOnce() -> V) -> V {
    NOW.with(|n| match n.borrow_mut().as_mut() {
        Some(s) => pick(s).entry(id).or_insert_with(read).clone(),
        None => read(),
    })
}

fn motion_now(ctx: &ReducerContext, id: u32) -> Option<Moving> {
    cached(|s| &mut s.motion, id, || ctx.db.body().id().find(id).map(|b| Moving::from(&b)))
}

fn fighter_now(ctx: &ReducerContext, id: u32) -> Option<Fighter> {
    cached(|s| &mut s.fighter, id, || ctx.db.fighter().id().find(id))
}

fn health_now(ctx: &ReducerContext, id: u32, now: u64) -> Option<(f32, f32)> {
    cached(|s| &mut s.health, id, || ctx.db.vitals().id().find(id).map(|v| (common::needs(&v, now).hp, v.max_hp)))
}

fn doing_now(ctx: &ReducerContext, id: u32) -> Option<Doing> {
    cached(|s| &mut s.doing, id, || ctx.db.doing().id().find(id))
}

fn mark(map: &'static std::thread::LocalKey<RefCell<HashMap<u32, u64>>>, id: u32) {
    let s = SEQ.with(|s| {
        let v = s.get() + 1;
        s.set(v);
        v
    });
    map.with(|m| m.borrow_mut().insert(id, s));
}

/// A creature's body row was written (its motion may have changed).
pub fn moved(id: u32) {
    mark(&MOVED, id);
}

/// A creature's `fighter` row was written or deleted.
pub fn fought(id: u32) {
    mark(&FOUGHT, id);
}

/// A creature's health moved (its band, or exact health where shown).
pub fn hurt(id: u32) {
    mark(&HURT, id);
}

/// A creature's `doing` row was written or deleted.
pub fn did(id: u32) {
    mark(&DID, id);
}

fn changed(map: &'static std::thread::LocalKey<RefCell<HashMap<u32, u64>>>, id: u32, since: u64) -> bool {
    map.with(|m| m.borrow().get(&id).is_some_and(|s| *s > since))
}

/// The sweep's answer for a viewer: the creatures it perceives now (itself excluded). Rows of
/// newcomers were written by the sweep as they are now.
pub fn scene(id: u32, who: Identity, seen: &HashSet<u32>) {
    VIEWERS.with(|v| {
        let mut v = v.borrow_mut();
        let e = v.entry(id).or_insert_with(|| Viewer::new(who));
        if e.who != who {
            *e = Viewer::new(who);
        }
        e.scene = Some(seen.clone());
    });
}

/// A feed event for an onlooker, delivered at its frame.
pub fn witness(id: u32, who: Identity, ev: &Seen, amount: f32) {
    VIEWERS.with(|v| {
        let mut v = v.borrow_mut();
        let e = v.entry(id).or_insert_with(|| Viewer::new(who));
        e.events.push((ev.clone(), amount));
    });
}

/// A feed row was written for this viewer at once (it expires at `expires_ms`).
pub fn fed(id: u32, who: Identity, expires_ms: u64, row: u64) {
    VIEWERS.with(|v| {
        let mut v = v.borrow_mut();
        let e = v.entry(id).or_insert_with(|| Viewer::new(who));
        e.feed.push_back((expires_ms, row));
    });
}

/// A player's character died: its frames stop, and its last staged lines are released (its
/// window stays readable, the dead included).
pub fn forget(ctx: &ReducerContext, id: u32) {
    VIEWERS.with(|v| v.borrow_mut().remove(&id));
    release_lines(ctx, id);
}

/// How often a viewer with `n` creatures in its scene gets a frame (ms), before the stretch.
pub fn interval(n: usize) -> u64 {
    (n as u64 * 1000 / SCENE_ROWS_PER_S).clamp(FRAME_MIN_MS, FRAME_MAX_MS)
}

/// The players whose frame is due get it (every tick, after the perception sweep), stalest
/// first, within the step's budget of scene rows.
pub fn deliver(ctx: &ReducerContext, now: u64) {
    NOW.with(|n| *n.borrow_mut() = Some(Sources::default()));
    let humans = crate::combat::humans(ctx);
    let due: Vec<(u32, Viewer)> = VIEWERS.with(|v| {
        let mut v = v.borrow_mut();
        let ids: HashSet<u32> = humans.iter().map(|(h, _)| *h).collect();
        v.retain(|id, _| ids.contains(id));
        let mut due = Vec::new();
        for (id, who) in &humans {
            let e = v.entry(*id).or_insert_with(|| Viewer::new(*who));
            if e.who != *who {
                *e = Viewer::new(*who);
            }
            let n = e.scene.as_ref().map_or(0, |s| s.len());
            let every = interval(n);
            if e.last_ms == 0 {
                // A first frame comes within one interval, staggered by character so a crowd's
                // frames spread over the ticks.
                e.last_ms = now.saturating_sub((*id as u64).wrapping_mul(37) % every.max(1));
            }
            if now.saturating_sub(e.last_ms) >= every {
                due.push((e.last_ms, *id, n));
            }
        }
        due.sort_unstable();
        let mut rows = 0;
        let mut served = Vec::new();
        for (_, id, n) in due {
            if rows > 0 && rows + n > FRAME_ROWS_PER_TICK {
                break;
            }
            rows += n;
            served.push(id);
        }
        served.into_iter().filter_map(|id| v.remove(&id).map(|e| (id, e))).collect()
    });
    for (id, mut e) in due {
        frame(ctx, id, &mut e, now);
        VIEWERS.with(|v| v.borrow_mut().insert(id, e));
    }
    // Rows written later (other transactions, the sweep) must be read again.
    NOW.with(|n| *n.borrow_mut() = None);
}

fn frame(ctx: &ReducerContext, id: u32, v: &mut Viewer, now: u64) {
    let upto = SEQ.with(|s| s.get());
    if let Some(scene) = v.scene.as_ref() {
        let since = if v.full { 0 } else { v.seq };
        let full = v.full;
        for &body in scene {
            if full || changed(&MOVED, body, since) {
                show_motion(ctx, id, body);
            }
            let hurt = full || changed(&HURT, body, since);
            if hurt || changed(&FOUGHT, body, since) {
                show_fighter(ctx, id, v.who, body, hurt, now);
            }
            if full || changed(&DID, body, since) {
                show_doing(ctx, id, v.who, body);
            }
        }
        // Projections follow health less often: their band is what `seen_characters` shows.
        if full || now.saturating_sub(v.band_ms) >= BAND_MS {
            let since = if full { 0 } else { v.band_seq };
            for &body in scene {
                if full || changed(&HURT, body, since) {
                    show_band(ctx, v.who, body, now);
                }
            }
            v.band_ms = now;
            v.band_seq = upto;
        }
        v.full = false;
        v.seq = upto;
    }
    // The onlookers' feed: what happened in sight since the last frame, then what expired.
    for (ev, amount) in std::mem::take(&mut v.events) {
        let row = crate::combat::feed_row(ctx, v.who, now, &ev, amount, ONLOOKER_MS);
        v.feed.push_back((now + ONLOOKER_MS, row));
    }
    while v.feed.front().is_some_and(|(at, _)| *at <= now) {
        let (_, row) = v.feed.pop_front().unwrap();
        ctx.db.combat_seen().id().delete(row);
    }
    if now.saturating_sub(v.lines_ms) >= LINES_MS {
        v.lines_ms = now;
        release_lines(ctx, id);
    }
    v.last_ms = now;
}

fn show_motion(ctx: &ReducerContext, viewer: u32, body: u32) {
    let k = key(viewer, body);
    let (Some(mut row), Some(m)) = (ctx.db.motion_seen().id().find(k), motion_now(ctx, body)) else { return };
    if row.moving() != m {
        row.set(&m);
        ctx.db.motion_seen().id().update(row);
    }
}

/// Bring a viewer's `fighter_seen` row of a creature up to date: its move as it is now; its
/// band as the viewer perceives it (255 while its projection hides health) when `hurt`, else
/// as last shown. A creature with no fighter row has none.
pub fn show_fighter(ctx: &ReducerContext, viewer: u32, who: Identity, body: u32, hurt: bool, now: u64) {
    let k = key(viewer, body);
    let row = ctx.db.fighter_seen().id().find(k);
    let Some(f) = fighter_now(ctx, body) else {
        if row.is_some() {
            ctx.db.fighter_seen().id().delete(k);
        }
        return;
    };
    let band = match row.as_ref() {
        Some(r) if !hurt => r.fighter.band,
        _ => perceived_band(ctx, who, body, now).0,
    };
    let new = FighterSeen { id: k, viewer: who, fighter: Fighter { band, ..f } };
    match row {
        Some(r) if r == new => {}
        Some(_) => {
            ctx.db.fighter_seen().id().update(new);
        }
        None => {
            ctx.db.fighter_seen().insert(new);
        }
    }
}

/// Bring a viewer's `doing_seen` row of a creature up to date (none while it shows nothing).
pub fn show_doing(ctx: &ReducerContext, viewer: u32, who: Identity, body: u32) {
    let k = key(viewer, body);
    let row = ctx.db.doing_seen().id().find(k);
    match (doing_now(ctx, body), row) {
        (None, Some(_)) => {
            ctx.db.doing_seen().id().delete(k);
        }
        (None, None) => {}
        (Some(d), Some(r)) if r.doing == d => {}
        (Some(d), Some(_)) => {
            ctx.db.doing_seen().id().update(DoingSeen { id: k, viewer: who, doing: d });
        }
        (Some(d), None) => {
            ctx.db.doing_seen().insert(DoingSeen { id: k, viewer: who, doing: d });
        }
    }
}

/// A creature's band as this viewer perceives it now (255 while its projection hides health),
/// with its projection row.
fn perceived_band(ctx: &ReducerContext, who: Identity, body: u32, now: u64) -> (u8, Option<(Projected, f32)>) {
    let p = ctx.db.projected().by_viewer_body().filter((who, body)).next();
    let hp = health_now(ctx, body, now);
    let band = match (&p, hp) {
        (Some(p), _) if p.band == 255 => 255,
        (_, Some((hp, max))) => living_rules::combat::band(hp, max),
        _ => 255,
    };
    (band, p.map(|p| (p, hp.map_or(0.0, |h| h.0))))
}

/// The viewer's projection of a creature follows its health: the band, and exact health where
/// the law grants it.
fn show_band(ctx: &ReducerContext, who: Identity, body: u32, now: u64) {
    let (band, Some((p, hp))) = perceived_band(ctx, who, body, now) else { return };
    let mut q = p.clone();
    q.band = band;
    if q.hp >= 0.0 {
        q.hp = hp.max(0.0).round();
    }
    if q != p {
        ctx.db.projected().id().update(q);
    }
}

/// Release a character's staged experience lines and keep the newest [`LINES_SHOWN`].
fn release_lines(ctx: &ReducerContext, id: u32) {
    let staged: Vec<LineSeen> = ctx.db.line_seen().by_observer_shown().filter((id, false)).collect();
    if staged.is_empty() {
        return;
    }
    for mut l in staged {
        l.shown = true;
        ctx.db.line_seen().id().update(l);
    }
    let mut shown: Vec<u64> = ctx.db.line_seen().by_observer_shown().filter((id, true)).map(|l| l.id).collect();
    if shown.len() > LINES_SHOWN {
        shown.sort_unstable();
        for old in &shown[..shown.len() - LINES_SHOWN] {
            ctx.db.line_seen().id().delete(*old);
        }
    }
}

/// An experience line was written for a player's character: staged for its next frame.
pub fn line(ctx: &ReducerContext, line: &Experience) {
    ctx.db.line_seen().insert(LineSeen { id: line.id, observer: line.observer, shown: false, line: line.clone() });
}

/// A character's person (re)takes it (a join, a return after the minds had it): its newest
/// lines, those the minds' time included, are staged for its client.
pub fn catch_up_lines(ctx: &ReducerContext, id: u32) {
    let mut rows: Vec<Experience> = ctx.db.experience().observer().filter(id).collect();
    rows.sort_unstable_by(|a, b| b.id.cmp(&a.id));
    for e in rows.iter().take(LINES_SHOWN) {
        if ctx.db.line_seen().id().find(e.id).is_none() {
            line(ctx, e);
        }
    }
}
