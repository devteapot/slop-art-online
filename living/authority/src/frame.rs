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
//! down to [`FRAME_MAX_MS`] in a crowd. A step serves at most its budget of rows of scene,
//! stalest viewers first, so the work frames add to one step is bounded: when more is due than
//! that, frames come less often (the delivery's back-pressure) instead of the tick running late.
//!
//! Since tick-rate (2026-11-13; docs/TICK_RATE.md) the budget is shared with the step's sweeps
//! and follows the tick's boundaries. Most of a frame's or a sweep's cost is not in the tick's
//! body: the views its writes re-run, their read sets and the subscription evaluation are part
//! of the tick's transaction after the reducer returns, and the scheduler sets the next tick at
//! the first 60 Hz boundary after that transaction ends (2.14.1 `next_interval_tick_after`). On
//! Cullet at 216 players every tick that swept a quarter of the players and then served frames
//! up to the budget ran past the next boundary, and the world stepped at 40 Hz. So:
//! - **A sweep counts against the step's frames:** each player swept takes its scene's rows
//!   from the budget, as a frame of it would (a sweep and its views cost about what a frame of
//!   the same scene costs). A step that sweeps serves fewer frames; the other steps serve more.
//! - **The budget follows the boundaries** ([`budget`]): a tick that starts a slot or more after
//!   the previous one shrinks it by an eighth, and each tick on time grows it by
//!   [`FRAME_ROWS_STEP`] rows, up to [`FRAME_ROWS_PER_TICK`].

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
/// The most scene rows (creatures in the scenes of the viewers served) one step's frames may
/// cover; the budget ([`budget`]) starts here and never grows past it.
pub const FRAME_ROWS_PER_TICK: usize = 2_500;
/// The least the budget shrinks to; a step still serves its stalest due viewer
/// whatever the budget (`deliver`).
pub const FRAME_ROWS_MIN: usize = 250;
/// How many rows each tick on time adds to the budget.
pub const FRAME_ROWS_STEP: usize = 2;
/// The tick's interval (µs), as `init` schedules it (`lib.rs`).
pub const TICK_US: i64 = 16_667;
/// How often a viewer's projections follow others' health at most (ms): the band and exact
/// health `seen_characters` shows (the client draws health bars from `seen_fighters`, which
/// carries the band at every frame; the exact health an appraisal reveals follows each second).
pub const BAND_MS: u64 = 1_000;
/// Experience lines kept released per character in `my_experience` (the newest).
pub const LINES_SHOWN: usize = 64;
/// Lines are released at most this often per character (ms).
pub const LINES_MS: u64 = 100;
/// A player's senses (`my_senses`) are asked again at most this often (ms): a change shows
/// within this of nightfall or of picking up a torch.
pub const SENSES_MS: u64 = 250;
/// A player's earshot (`my_earshot`) is asked again at most this often (ms): someone stepping
/// into or out of a way's reach shows within this.
pub const EARSHOT_MS: u64 = 250;

/// The key of a viewer's `motion_seen` row of a creature.
pub fn key(viewer: u32, body: u32) -> u64 {
    ((viewer as u64) << 32) | body as u64
}

struct Viewer {
    who: Identity,
    /// The creatures it perceives (not itself), as the last sweep left them; `None` until a
    /// sweep has run in this module instance.
    scene: Option<HashMap<u32, SceneRow>>,
    near_ms: u64,
    engaged_ms: u64,
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
    /// When its senses were last asked, and the row last written (`None`: read it first).
    senses_ms: u64,
    senses: Option<CharacterSenses>,
    /// When its earshot was last asked, and the row last written (`None`: read it first).
    earshot_ms: u64,
    earshot: Option<CharacterEarshot>,
}

/// Delivery cursors are scheduling hints. Values sent to players come from the tables.
#[derive(Default)]
struct SceneRow {
    distance: f32,
    seq: u64,
    last_ms: u64,
}

impl Viewer {
    fn new(who: Identity) -> Self {
        Self { who, scene: None, near_ms: 0, engaged_ms: 0, full: true, last_ms: 0, lines_ms: 0, band_ms: 0, band_seq: 0, events: Vec::new(), feed: VecDeque::new(), senses_ms: 0, senses: None, earshot_ms: 0, earshot: None }
    }
}

thread_local! {
    static SEQ: Cell<u64> = const { Cell::new(0) };
    /// The sequence number of each creature's last change of motion, fighter row, and health.
    static MOVED: RefCell<HashMap<u32, MotionChange>> = RefCell::new(HashMap::new());
    static FOUGHT: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    static HURT: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    static DID: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    static TARGET_DIRTY: RefCell<HashSet<u32>> = RefCell::new(HashSet::new());
    static TARGETS: RefCell<HashMap<u32, Targets>> = RefCell::new(HashMap::new());
    /// Players' living characters, by character id.
    static VIEWERS: RefCell<HashMap<u32, Viewer>> = RefCell::new(HashMap::new());
    /// What creatures are like now, read once per `deliver` and shared by every viewer's frame
    /// in it (frames run after the tick's writes). `None` outside `deliver`: reads go to the
    /// tables.
    static NOW: RefCell<Option<Sources>> = const { RefCell::new(None) };
    /// The frames' budget of scene rows per step, and the previous tick's start (µs since the
    /// epoch, 0 before the first). Timing only: a fresh instance starts at the most, and which
    /// viewers a step serves never changes what a frame writes.
    static BUDGET: Cell<(usize, i64)> = const { Cell::new((FRAME_ROWS_PER_TICK, 0)) };
}

/// The step's budget for the tick that started at `start_us`: an eighth less when it started a
/// slot or more after the previous tick (a boundary was missed: the previous one's transaction
/// ran past it, or something queued ahead of this one), [`FRAME_ROWS_STEP`] more otherwise. A
/// gap of a second or more is a pause or a new instance, not a missed boundary.
fn budget(start_us: i64) -> usize {
    BUDGET.with(|b| {
        let (rows, last) = b.get();
        let gap = start_us - last;
        let late = last != 0 && (TICK_US * 3 / 2..1_000_000).contains(&gap);
        let rows = if late { (rows - rows / 8).max(FRAME_ROWS_MIN) } else { (rows + FRAME_ROWS_STEP).min(FRAME_ROWS_PER_TICK) };
        b.set((rows, start_us));
        if late {
            common::diag(|| "frames:late", 1);
        }
        common::diag(|| "frames:budget", rows as u64);
        rows
    })
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

fn next_seq() -> u64 {
    SEQ.with(|s| {
        let v = s.get() + 1;
        s.set(v);
        v
    })
}

fn mark(map: &'static std::thread::LocalKey<RefCell<HashMap<u32, u64>>>, id: u32) {
    let seq = next_seq();
    map.with(|m| m.borrow_mut().insert(id, seq));
}

struct MotionChange {
    seq: u64,
    direction_seq: u64,
    heading: f32,
    facing: f32,
}

/// A change to the end of either turn segment is distinguished from a continuation.
pub fn moved(body: &Body) {
    let seq = next_seq();
    let heading = body.heading + body.turn * body.turn_s;
    let facing = heading + body.face_off + body.face_turn * body.face_turn_s;
    MOVED.with(|changes| {
        let mut changes = changes.borrow_mut();
        let direction_seq = changes.get(&body.id).map_or(seq, |old| {
            if living_rules::steer::wrap(heading - old.heading).abs() > 0.03
                || living_rules::steer::wrap(facing - old.facing).abs() > 0.03 {
                seq
            } else {
                old.direction_seq
            }
        });
        changes.insert(body.id, MotionChange { seq, direction_seq, heading, facing });
    });
}

fn motion_changed(body: u32, since: u64) -> (bool, bool) {
    MOVED.with(|changes| changes.borrow().get(&body)
        .map_or((false, false), |change| (change.seq > since, change.direction_seq > since)))
}

/// A creature's `fighter` row was written or deleted.
pub fn fought(id: u32) {
    mark(&FOUGHT, id);
    TARGET_DIRTY.with(|dirty| dirty.borrow_mut().insert(id));
}

/// A creature's health moved (its band, or exact health where shown).
pub fn hurt(id: u32) {
    mark(&HURT, id);
}

/// A creature's `doing` row was written or deleted.
pub fn did(id: u32) {
    mark(&DID, id);
    TARGET_DIRTY.with(|dirty| dirty.borrow_mut().insert(id));
}

fn changed(map: &'static std::thread::LocalKey<RefCell<HashMap<u32, u64>>>, id: u32, since: u64) -> bool {
    map.with(|m| m.borrow().get(&id).is_some_and(|s| *s > since))
}

/// The sweep's answer for a viewer: the creatures it perceives now (itself excluded). Rows of
/// newcomers were written by the sweep as they are now.
pub fn scene(id: u32, who: Identity, distances: &HashMap<u32, f32>) {
    VIEWERS.with(|v| {
        let mut v = v.borrow_mut();
        let e = v.entry(id).or_insert_with(|| Viewer::new(who));
        if e.who != who {
            *e = Viewer::new(who);
        }
        let scene = e.scene.get_or_insert_with(HashMap::new);
        scene.retain(|body, _| distances.contains_key(body));
        let upto = SEQ.with(Cell::get);
        for (&body, &distance) in distances {
            scene.entry(body).or_insert(SceneRow { seq: upto, ..SceneRow::default() }).distance = distance;
        }
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
/// Every viewer's next frame compares its whole scene (after a tick this instance did not see
/// commit: what earlier frames wrote may have been rolled back).
pub fn all_full() {
    VIEWERS.with(|v| v.borrow_mut().values_mut().for_each(|e| {
        e.full = true;
        e.scene = None;
        e.senses = None;
        e.earshot = None;
    }));
    TARGETS.with(|targets| {
        TARGET_DIRTY.with(|dirty| dirty.borrow_mut().extend(targets.borrow().keys().copied()));
    });
}

/// An unscheduled sweep may still roll back. Reload its membership from the database.
pub fn invalidate_scene(id: u32) {
    VIEWERS.with(|viewers| {
        if let Some(viewer) = viewers.borrow_mut().get_mut(&id) {
            viewer.scene = None;
            viewer.full = true;
        }
    });
}

pub fn forget(ctx: &ReducerContext, id: u32) {
    VIEWERS.with(|v| v.borrow_mut().remove(&id));
    release_lines(ctx, id);
}

/// How often a viewer with `n` creatures in its scene gets a frame (ms), before the stretch.
pub fn interval(n: usize) -> u64 {
    (n as u64 * 1000 / SCENE_ROWS_PER_S).clamp(FRAME_MIN_MS, FRAME_MAX_MS)
}

const NEAR_M: f32 = 8.0;
const NEAR_MS: u64 = 50;
const FAR_INTERVAL_MS: u64 = 100;
const FAR_MAX_WAIT_MS: u64 = 200;

#[derive(Clone, Copy, PartialEq, Eq)]
enum FrameScope {
    Engaged,
    Relevant,
    Whole,
}

impl FrameScope {
    fn includes(self, distance: f32, engaged: bool) -> bool {
        match self {
            Self::Engaged => engaged,
            Self::Relevant => engaged || distance <= NEAR_M,
            Self::Whole => true,
        }
    }
}

#[derive(Default)]
struct Targets {
    fighter: Option<(u32, u64)>,
    doing: Option<(u32, u64)>,
}

fn engagements(ctx: &ReducerContext, now: u64, human: &HashSet<u32>) -> HashMap<u32, HashSet<u32>> {
    TARGETS.with(|targets| {
        let mut targets = targets.borrow_mut();
        let dirty = TARGET_DIRTY.with(|dirty| std::mem::take(&mut *dirty.borrow_mut()));
        for actor in dirty {
            let fighter = fighter_now(ctx, actor).filter(|f| f.act != 0 && f.target != 0 && f.until_ms > now);
            let doing = doing_now(ctx, actor).filter(|d| d.target != 0 && d.until_ms > now);
            targets.insert(actor, Targets {
                fighter: fighter.map(|f| (f.target, f.until_ms)),
                doing: doing.map(|d| (d.target, d.until_ms)),
            });
        }
        let mut active: HashMap<u32, HashSet<u32>> = HashMap::new();
        targets.retain(|&actor, target| {
            let mut keep = false;
            for (other, until) in [target.fighter, target.doing].into_iter().flatten() {
                if now >= until {
                    continue;
                }
                keep = true;
                if human.contains(&actor) {
                    active.entry(actor).or_default().insert(other);
                }
                if human.contains(&other) {
                    active.entry(other).or_default().insert(actor);
                }
            }
            keep
        });
        active
    })
}

/// The old interval still governs whole scenes. Give nearby rows their own deadline, with
/// a whole-scene deadline to keep the rest of the scene moving under sustained demand.
pub fn deliver(ctx: &ReducerContext, now: u64, swept: &[u32]) {
    let budget = budget(ctx.timestamp.to_micros_since_unix_epoch());
    NOW.with(|n| *n.borrow_mut() = Some(Sources::default()));
    let humans = crate::combat::humans(ctx);
    let (due, engaged, mut rows) = VIEWERS.with(|viewers| {
        let mut viewers = viewers.borrow_mut();
        let ids: HashSet<u32> = humans.iter().map(|(id, _)| *id).collect();
        viewers.retain(|id, _| ids.contains(id));
        let engaged = engagements(ctx, now, &ids);
        let no_targets = HashSet::new();
        let mut due = Vec::new();
        for (id, who) in humans {
            let viewer = viewers.entry(id).or_insert_with(|| Viewer::new(who));
            if viewer.who != who {
                *viewer = Viewer::new(who);
            }
            let scene = viewer.scene.get_or_insert_with(|| {
                ctx.db.perceived().viewer().filter(who)
                    .map(|row| (row.body, SceneRow { distance: f32::INFINITY, ..SceneRow::default() }))
                    .collect()
            });
            let n = scene.len();
            let targets = engaged.get(&id).unwrap_or(&no_targets);
            let has_engaged = targets.iter().any(|id| scene.contains_key(id));
            let has_near = has_engaged || scene.values().any(|row| row.distance <= NEAR_M);
            let every = if has_near && n > 1 { FAR_INTERVAL_MS } else { interval(n) };
            if viewer.last_ms == 0 {
                viewer.last_ms = now.saturating_sub((u64::from(id) * 37) % every);
                viewer.near_ms = viewer.last_ms;
                viewer.engaged_ms = viewer.last_ms;
            }
            let age = now.saturating_sub(viewer.last_ms);
            let near_age = now.saturating_sub(viewer.near_ms);
            if age >= FAR_MAX_WAIT_MS || (viewer.full && age >= every) {
                due.push((0, viewer.last_ms, id, FrameScope::Whole));
            } else if now.saturating_sub(viewer.engaged_ms) >= FRAME_MIN_MS && has_engaged {
                due.push((1, viewer.engaged_ms, id, FrameScope::Engaged));
            } else if near_age >= NEAR_MS && has_near {
                let urgent = scene.iter().any(|(&body, row)| row.distance <= NEAR_M
                    && (motion_changed(body, row.seq).1 || changed(&DID, body, row.seq)));
                let scope = if age >= every { FrameScope::Whole } else { FrameScope::Relevant };
                due.push((if urgent { 2 } else { 3 }, viewer.near_ms, id, scope));
            } else if age >= every {
                due.push((4, viewer.last_ms, id, FrameScope::Whole));
            }
        }
        due.sort_unstable_by_key(|&(priority, last, id, _)| (priority, last, id));
        let rows: usize = swept.iter().map(|id| viewers.get(id).and_then(|v| v.scene.as_ref()).map_or(0, HashMap::len) + 1).sum();
        (due, engaged, rows)
    });
    let no_targets = HashSet::new();
    let due_n = due.len();
    common::diag(|| "frames:swept_rows", rows as u64);
    let profiling = common::profiling();
    let mut frames = Vec::new();
    let mut cadence = crate::frame_trace::Cadence::default();
    let mut served = 0;
    for (_, _, id, scope) in due {
        let targets = engaged.get(&id).unwrap_or(&no_targets);
        let viewer = VIEWERS.with(|viewers| {
            let mut viewers = viewers.borrow_mut();
            let cost = frame_cost(ctx, &viewers[&id], scope, targets);
            if served != 0 && rows + cost > budget {
                return None;
            }
            rows += cost;
            viewers.remove(&id)
        });
        let Some(mut viewer) = viewer else { continue };
        served += 1;
        let count = frame(ctx, id, &mut viewer, now, scope, targets, profiling.then_some(&mut cadence));
        VIEWERS.with(|viewers| viewers.borrow_mut().insert(id, viewer));
        if profiling {
            frames.push((id, count));
        }
    }
    common::diag(|| "frames:ticks", 1);
    common::diag(|| "frames:due", due_n as u64);
    common::diag(|| "frames:served", served);
    common::diag(|| "frames:rows", rows as u64);
    if profiling {
        cadence.log(ctx);
        log::info!("frame cadence: {} {} {:?}", ctx.timestamp.to_micros_since_unix_epoch(), budget, frames);
    }
    NOW.with(|n| *n.borrow_mut() = None);
}

/// Motion and fighters each retain an entire scene in their view. A doing-only frame
/// touches the much smaller activity stream. Empty passes still pay for processing.
fn frame_cost(ctx: &ReducerContext, viewer: &Viewer, scope: FrameScope, targets: &HashSet<u32>) -> usize {
    let Some(scene) = viewer.scene.as_ref() else { return 1 };
    if viewer.full {
        return scene.len() + 1;
    }
    let mut doing = 0;
    for (&body, row) in scene {
        if !scope.includes(row.distance, targets.contains(&body)) {
            continue;
        }
        if motion_changed(body, row.seq).0 || changed(&FOUGHT, body, row.seq) || changed(&HURT, body, row.seq) {
            return scene.len() + 1;
        }
        doing += usize::from(changed(&DID, body, row.seq));
    }
    if doing == 0 {
        1
    } else {
        let shown = ctx.db.doing_seen().viewer().filter(viewer.who).count();
        shown.saturating_add(doing).min(scene.len()) + 1
    }
}

fn frame(ctx: &ReducerContext, id: u32, v: &mut Viewer, now: u64, scope: FrameScope, targets: &HashSet<u32>, mut cadence: Option<&mut crate::frame_trace::Cadence>) -> usize {
    let upto = SEQ.with(Cell::get);
    let mut count = 0;
    if let Some(scene) = v.scene.as_mut() {
        let full = v.full;
        let mut work = Vec::with_capacity(scene.len());
        for (&body, row) in scene.iter_mut() {
            let (moving, turning) = motion_changed(body, row.seq);
            let moving = full || moving;
            let hurt = full || changed(&HURT, body, row.seq);
            let fighting = full || changed(&FOUGHT, body, row.seq);
            let doing = full || changed(&DID, body, row.seq);
            let engaged = targets.contains(&body);
            let relevant = engaged || row.distance <= NEAR_M;
            if !scope.includes(row.distance, engaged) {
                continue;
            }
            if let Some(cadence) = cadence.as_deref_mut() {
                cadence.served(now, &mut row.last_ms, relevant);
            }
            count += 1;
            if moving || hurt || fighting || doing {
                work.push(((!engaged, !relevant, !turning && !doing && !fighting),
                           row.distance, body, moving, hurt, fighting, doing));
            }
        }
        work.sort_unstable_by(|a, b| a.0.cmp(&b.0)
            .then_with(|| a.1.total_cmp(&b.1))
            .then_with(|| a.2.cmp(&b.2)));
        for (_, _, body, moving, hurt, fighting, doing) in work {
            if moving {
                show_motion(ctx, id, body);
            }
            if hurt || fighting {
                show_fighter(ctx, id, v.who, body, hurt, now);
            }
            if doing {
                show_doing(ctx, id, v.who, body);
            }
            scene.get_mut(&body).unwrap().seq = upto;
        }
        if scope == FrameScope::Whole {
            // Projections follow health at their own slower cadence.
            if full || now.saturating_sub(v.band_ms) >= BAND_MS {
                let since = if full { 0 } else { v.band_seq };
                for &body in scene.keys() {
                    if full || changed(&HURT, body, since) {
                        show_band(ctx, v.who, body, now);
                    }
                }
                v.band_ms = now;
                v.band_seq = upto;
            }
            v.full = false;
        }
    }
    v.engaged_ms = now;
    if scope != FrameScope::Engaged {
        v.near_ms = now;
    }
    if scope != FrameScope::Whole {
        return count;
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
    if now.saturating_sub(v.senses_ms) >= SENSES_MS {
        v.senses_ms = now;
        show_senses(ctx, id, v, now);
    }
    if now.saturating_sub(v.earshot_ms) >= EARSHOT_MS {
        v.earshot_ms = now;
        show_earshot(ctx, id, v, now);
    }
    v.last_ms = now;
    count
}

/// Bring a player's `character_senses` row up to date with the `senses` law (kept per moment
/// and per state by `common::senses_of`): written only when a value changed.
fn show_senses(ctx: &ReducerContext, id: u32, v: &mut Viewer, now: u64) {
    let w = common::world(ctx);
    let new = CharacterSenses::of(id, &common::senses_of(ctx, id, &w, now));
    if v.senses.is_none() {
        v.senses = ctx.db.character_senses().id().find(id);
    }
    match v.senses.as_ref() {
        Some(old) if old.same(&new) => {}
        Some(_) => {
            let row = CharacterSenses { at_ms: now, ..new };
            v.senses = Some(ctx.db.character_senses().id().update(row));
        }
        None => {
            let row = CharacterSenses { at_ms: now, ..new };
            v.senses = Some(ctx.db.character_senses().insert(row));
        }
    }
}

/// Bring a player's `character_earshot` row up to date: whom a line said now would reach, at
/// each way, among the creatures of its scene (`earshot::reach`), in its own labels. Written
/// only when the people or the words changed.
fn show_earshot(ctx: &ReducerContext, id: u32, v: &mut Viewer, now: u64) {
    let (Some(scene), Some(me), Some(b)) = (v.scene.as_ref(), ctx.db.character().id().find(id), ctx.db.body().id().find(id)) else { return };
    if &*me.kind != "person" {
        return;
    }
    if v.earshot.is_none() {
        v.earshot = ctx.db.character_earshot().id().find(id);
    }
    // Off (the `earshot` law): no row; one written while it was on goes.
    if !common::laws(ctx).earshot {
        if v.earshot.take().is_some() {
            ctx.db.character_earshot().id().delete(id);
        }
        return;
    }
    let ways = crate::earshot::reach(ctx, id, common::pos(&b, now), |x| scene.contains_key(&x), now);
    let text = crate::earshot::short_words(&ways, |x| common::label_for(ctx, &me, x));
    let row = CharacterEarshot { id, ways, text, at_ms: now };
    match v.earshot.as_ref() {
        Some(old) if old.ways == row.ways && old.text == row.text => {}
        Some(_) => v.earshot = Some(ctx.db.character_earshot().id().update(row)),
        None => v.earshot = Some(ctx.db.character_earshot().insert(row)),
    }
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
        crate::perception::row_written(who, body);
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
            crate::outcomes::dropped(ctx, *old);
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
