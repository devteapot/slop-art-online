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
//!
//! **Cues and tiers** (frame-views, 2026-11-18; docs/PERCEPTION.md, "Cues and tiers"). In 2.14.1
//! any write to one of a viewer's copies re-runs that viewer's whole view of them, so a frame costs
//! about the scene whatever changed in it, and no ordering of frames makes a near change cheaper
//! (frame-fresh, docs/TICK_RATE.md). So:
//! - **Cues.** What is near a viewer (within [`NEAR_M`] at its last sweep) or engaged with it (a
//!   move or visible act aimed at it, or its own aimed at them) is sent as rows of the event
//!   tables `seen_body_cue`, `seen_fighter_cue` and `seen_doing_cue`, which no view reads and the
//!   database never stores. Each creature that changed since the last tick goes, as the viewer's
//!   copy would hold it now, to the viewers it is near at their next cue tick (every
//!   [`CUE_TICKS`]) and to those engaged with it at once. A cue costs one row whatever the scene.
//! - **Tiers.** Near copies live in their own tables (`motion_near`, `fighter_near`,
//!   `doing_near`), far ones in the old copy tables, and each view has two tiers reading one
//!   table's key (`seen_*_near`, `seen_*_far`): a far frame re-runs only the far views.
//!   Near copies follow at most every [`NEAR_COPY_MS`]; cues carry their changes meanwhile, and
//!   they are the durable state behind the cues. A creature that changes tier at a sweep has its
//!   copies written as it is now, in the new tier.
//!
//! A client shows a creature's cue until its next tier row. A frame that writes no copy of a far
//! creature cued since the last frame (engaged from beyond [`NEAR_M`]) cues it as it is now
//! (reconcile), so a client is never left on a cue its copy will not replace.
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
/// A creature within this distance of a viewer at its last sweep is near it: its changes reach
/// the viewer as cues at the next tick. One already near stays near until [`NEAR_KEEP_M`].
pub const NEAR_M: f32 = 8.0;
pub const NEAR_KEEP_M: f32 = 9.0;
/// A viewer's copies of its near creatures (the near tier, `seen_*_near`) follow them at most
/// this often (ms): cues carry their changes, the copies are the durable state behind them.
pub const NEAR_COPY_MS: u64 = 500;
/// A viewer's near cues go out every this many ticks (its phase by id); cues of those engaged with
/// it go at every tick. 2 was measured (frame-views' selection pair, docs/TICK_RATE.md): about a
/// sixth fewer messages per player, near cues staler by about 15 ms at p90, so 1.
pub const CUE_TICKS: u64 = 1;
/// At most this many creatures are in a viewer's near tier: the nearest within [`NEAR_M`]. A
/// near creature's every change is cued to the viewer, so in a dense crowd (200 fighters within
/// 9 m) an unbounded tier fans each change out to everyone; the rest of the crowd follows at the
/// frames, as on main.
pub const NEAR_MAX: usize = 12;
/// The most cue rows one tick writes while the frames' budget is whole; it shrinks with that
/// budget (missed boundaries), down to [`CUE_ROWS_MIN`]. Cues of engaged pairs go first; near
/// cues beyond it wait for the next tick (kept as the viewer's pending cues), in a turn that
/// rotates by tick.
pub const CUE_ROWS_PER_TICK: usize = 3_000;
pub const CUE_ROWS_MIN: usize = 300;

/// The streams a cue carries, as bits.
const MOTION: u8 = 1;
const FIGHTER: u8 = 2;
const DOING: u8 = 4;
const ALL: u8 = MOTION | FIGHTER | DOING;

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
    /// When its senses were last asked, and the row last written (`None`: read it first).
    senses_ms: u64,
    senses: Option<CharacterSenses>,
    /// When its earshot was last asked, and the row last written (`None`: read it first).
    earshot_ms: u64,
    earshot: Option<CharacterEarshot>,
    /// The creatures near it at its last sweep (a subset of `scene`): its copies of them are the
    /// near tier.
    near: HashSet<u32>,
    /// When, and up to which change, its near copies last followed them.
    near_ms: u64,
    near_seq: u64,
    /// The streams of each creature of the far tier cued since its last frame (engaged with it
    /// from beyond [`NEAR_M`]; reconciled at the next).
    cued: HashMap<u32, u8>,
    /// Near creatures' streams changed since its last cues (sent at its next cue tick), and the
    /// sequence number then.
    pending: HashMap<u32, u8>,
    pending_seq: u64,
    /// Near creatures whose cue the budget deferred, and the cue tick it was first deferred at.
    deferred: HashMap<u32, u64>,
    /// Reconcile every creature in the scene at the next frame (a fresh instance, a step this
    /// instance did not see commit: what it was sent is unknown).
    reconcile: bool,
}

impl Viewer {
    fn new(who: Identity) -> Self {
        Self { who, scene: None, seq: 0, full: true, last_ms: 0, lines_ms: 0, band_ms: 0, band_seq: 0, events: Vec::new(), feed: VecDeque::new(), senses_ms: 0, senses: None, earshot_ms: 0, earshot: None, near: HashSet::new(), near_ms: 0, near_seq: 0, cued: HashMap::new(), pending: HashMap::new(), pending_seq: 0, deferred: HashMap::new(), reconcile: true }
    }
}

thread_local! {
    static SEQ: Cell<u64> = const { Cell::new(0) };
    /// The sequence number of each creature's last change of motion, fighter row, and health.
    static MOVED: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    static FOUGHT: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    static HURT: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    static DID: RefCell<HashMap<u32, u64>> = RefCell::new(HashMap::new());
    /// The streams of each creature changed since the last tick's cues.
    static PENDING: RefCell<HashMap<u32, u8>> = RefCell::new(HashMap::new());
    /// The viewers each creature is near (`Viewer::near`, by the viewers' last sweeps).
    static NEAR_OF: RefCell<HashMap<u32, HashSet<u32>>> = RefCell::new(HashMap::new());
    /// What each creature's move and visible act are aimed at, and until when (from frame-fresh):
    /// read again for creatures whose rows were written (`TARGET_DIRTY`).
    static TARGETS: RefCell<HashMap<u32, Targets>> = RefCell::new(HashMap::new());
    static TARGET_DIRTY: RefCell<HashSet<u32>> = RefCell::new(HashSet::new());
    /// Each viewer's creatures engaged with it at the last tick (its near tier holds them first).
    static ENGAGED: RefCell<HashMap<u32, HashSet<u32>>> = RefCell::new(HashMap::new());
    /// Profiling only: when each creature's recent changes were marked (sequence, ms), for the
    /// staleness of deliveries (`frame_trace`).
    static CHANGES: RefCell<HashMap<u32, VecDeque<(u64, u64)>>> = RefCell::new(HashMap::new());
    /// The sequence number at the last tick's cues, and how many ticks have sent cues.
    static CUED_SEQ: Cell<u64> = const { Cell::new(0) };
    static CUE_TICK: Cell<u64> = const { Cell::new(0) };
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

fn mark(map: &'static std::thread::LocalKey<RefCell<HashMap<u32, u64>>>, id: u32, stream: u8) {
    let s = SEQ.with(|s| {
        let v = s.get() + 1;
        s.set(v);
        v
    });
    map.with(|m| m.borrow_mut().insert(id, s));
    PENDING.with(|p| *p.borrow_mut().entry(id).or_default() |= stream);
    if common::profiling() {
        CHANGES.with(|c| {
            let mut c = c.borrow_mut();
            let q = c.entry(id).or_default();
            if q.len() == 16 {
                q.pop_front();
            }
            q.push_back((s, common::tx_now()));
        });
    }
}

/// A creature's body row was written (its motion may have changed).
pub fn moved(id: u32) {
    mark(&MOVED, id, MOTION);
}

/// A creature's `fighter` row was written or deleted.
pub fn fought(id: u32) {
    mark(&FOUGHT, id, FIGHTER);
    TARGET_DIRTY.with(|d| d.borrow_mut().insert(id));
}

/// A creature's health moved (its band, or exact health where shown).
pub fn hurt(id: u32) {
    mark(&HURT, id, FIGHTER);
}

/// A creature's `doing` row was written or deleted.
pub fn did(id: u32) {
    mark(&DID, id, DOING);
    TARGET_DIRTY.with(|d| d.borrow_mut().insert(id));
}

/// Profiling only: the time of a creature's first change after `since`, if still recorded.
fn changed_at(id: u32, since: u64) -> Option<u64> {
    CHANGES.with(|c| c.borrow().get(&id).and_then(|q| q.iter().find(|(s, _)| *s > since).map(|(_, ms)| *ms)))
}

fn changed(map: &'static std::thread::LocalKey<RefCell<HashMap<u32, u64>>>, id: u32, since: u64) -> bool {
    map.with(|m| m.borrow().get(&id).is_some_and(|s| *s > since))
}

/// The sweep's answer for a viewer: the creatures it perceives now (itself excluded), with how
/// far each is (the sweep's reading), which decides the near ones. Rows of newcomers were written
/// by the sweep as they are now. A creature that changes tier has its copies written as it is now,
/// in its new tier (it leaves one tier's view and enters the other's in this transaction).
pub fn scene(ctx: &ReducerContext, id: u32, who: Identity, seen: &HashSet<u32>, dist: &HashMap<u32, f32>, now: u64) {
    let flips: Vec<(u32, bool)> = VIEWERS.with(|v| {
        let mut v = v.borrow_mut();
        let e = v.entry(id).or_insert_with(|| Viewer::new(who));
        if e.who != who {
            unnear(id, &e.near);
            *e = Viewer::new(who);
        }
        e.scene = Some(seen.clone());
        // First, whoever is engaged with it (its move or visible act aimed at the viewer, or the
        // viewer's at it), at any distance in sight and past the cap. Then, in the slots left of
        // NEAR_MAX, the nearest within NEAR_M (NEAR_KEEP_M for one already near); one already near
        // counts half a metre nearer, so a crowd's tier does not flap at the cut.
        let engaged: HashSet<u32> = ENGAGED.with(|g| g.borrow().get(&id).map(|s| s.iter().copied().filter(|b| seen.contains(b)).collect()).unwrap_or_default());
        let slots = NEAR_MAX.saturating_sub(engaged.len());
        let mut cand: Vec<(f32, u32)> = seen
            .iter()
            .filter(|b| !engaged.contains(b))
            .filter_map(|b| {
                let d = *dist.get(b)?;
                let was = e.near.contains(b);
                (d <= NEAR_M || (was && d <= NEAR_KEEP_M)).then_some((if was { d - 0.5 } else { d }, *b))
            })
            .collect();
        if cand.len() > slots {
            cand.sort_unstable_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
            cand.truncate(slots);
            common::diag(|| "cues:near_capped", 1);
        }
        let near: HashSet<u32> = engaged.iter().copied().chain(cand.into_iter().map(|(_, b)| b)).collect();
        let mut flips = Vec::new();
        NEAR_OF.with(|n| {
            let mut n = n.borrow_mut();
            for b in e.near.difference(&near) {
                if let Some(s) = n.get_mut(b) {
                    s.remove(&id);
                    if s.is_empty() {
                        n.remove(b);
                    }
                }
                if seen.contains(b) {
                    flips.push((*b, false));
                }
            }
            for b in near.difference(&e.near) {
                n.entry(*b).or_default().insert(id);
                flips.push((*b, true));
            }
        });
        // Their copies are written as they are now: nothing cued of them is still owed.
        for (b, _) in &flips {
            e.cued.remove(b);
            e.pending.remove(b);
        }
        e.near = near;
        flips
    });
    for (body, near) in flips {
        show_motion(ctx, id, body, near);
        show_fighter(ctx, id, who, body, near, true, now);
        show_doing(ctx, id, who, body, near);
    }
}

/// Whether `body` is in the near tier of viewer `id` (as its last sweep left it).
pub fn is_near(id: u32, body: u32) -> bool {
    VIEWERS.with(|v| v.borrow().get(&id).is_some_and(|e| e.near.contains(&body)))
}

/// A viewer's near creatures no longer have it as a viewer.
fn unnear(id: u32, near: &HashSet<u32>) {
    NEAR_OF.with(|n| {
        let mut n = n.borrow_mut();
        for b in near {
            if let Some(s) = n.get_mut(b) {
                s.remove(&id);
                if s.is_empty() {
                    n.remove(b);
                }
            }
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
    VIEWERS.with(|v| {
        v.borrow_mut().values_mut().for_each(|e| {
            e.full = true;
            e.reconcile = true;
        })
    });
    TARGETS.with(|t| TARGET_DIRTY.with(|d| d.borrow_mut().extend(t.borrow().keys().copied())));
}

pub fn forget(ctx: &ReducerContext, id: u32) {
    if let Some(e) = VIEWERS.with(|v| v.borrow_mut().remove(&id)) {
        unnear(id, &e.near);
    }
    release_lines(ctx, id);
}

/// How often a viewer with `n` creatures in its scene gets a frame (ms), before the stretch.
pub fn interval(n: usize) -> u64 {
    (n as u64 * 1000 / SCENE_ROWS_PER_S).clamp(FRAME_MIN_MS, FRAME_MAX_MS)
}

/// The players whose frame is due get it (every tick, after the perception sweep), stalest
/// first, within the step's budget of scene rows less those of the players `swept` in it.
pub fn deliver(ctx: &ReducerContext, now: u64, swept: &[u32]) {
    let budget = budget(ctx.timestamp.to_micros_since_unix_epoch());
    NOW.with(|n| *n.borrow_mut() = Some(Sources::default()));
    let humans = crate::combat::humans(ctx);
    // The `cue_transport_on` law: off, no cue is written and near copies follow at every frame.
    let on = common::laws(ctx).cue_transport_on;
    let due: Vec<(u32, Viewer)> = VIEWERS.with(|v| {
        let mut v = v.borrow_mut();
        let ids: HashSet<u32> = humans.iter().map(|(h, _)| *h).collect();
        v.retain(|id, e| {
            let keep = ids.contains(id);
            if !keep {
                unnear(*id, &e.near);
            }
            keep
        });
        let mut due = Vec::new();
        for (id, who) in &humans {
            let e = v.entry(*id).or_insert_with(|| Viewer::new(*who));
            if e.who != *who {
                unnear(*id, &e.near);
                *e = Viewer::new(*who);
            }
            // A frame re-materializes the far tier's views, and the near tier's when its copies
            // are due to follow (`NEAR_COPY_MS`); its interval follows the far tier's size.
            let n_all = e.scene.as_ref().map_or(0, |s| s.len());
            let far = n_all.saturating_sub(e.near.len());
            let near_due = e.full || !on || now.saturating_sub(e.near_ms) >= NEAR_COPY_MS;
            let n = far + if near_due { e.near.len() } else { 0 };
            let every = interval(far);
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
        let due_n = due.len();
        // Each player swept in this step counts as a frame of its scene (and itself).
        let mut rows: usize = swept.iter().map(|id| v.get(id).and_then(|e| e.scene.as_ref()).map_or(0, |s| s.len()) + 1).sum();
        common::diag(|| "frames:swept_rows", rows as u64);
        let mut served = Vec::new();
        for (_, id, n) in due {
            if !served.is_empty() && rows + n > budget {
                break;
            }
            rows += n;
            served.push(id);
        }
        common::diag(|| "frames:ticks", 1);
        common::diag(|| "frames:due", due_n as u64);
        common::diag(|| "frames:served", served.len() as u64);
        common::diag(|| "frames:rows", rows as u64);
        served.into_iter().filter_map(|id| v.remove(&id).map(|e| (id, e))).collect()
    });
    if common::profiling() {
        let frames: Vec<_> = due.iter()
            .map(|(id, viewer)| (*id, viewer.scene.as_ref().map_or(0, |scene| scene.len())))
            .collect();
        log::info!("frame cadence: {} {} {:?}", ctx.timestamp.to_micros_since_unix_epoch(), budget, frames);
    }
    let mut trace = common::profiling().then(crate::frame_trace::Trace::default);
    let mut served = HashSet::with_capacity(due.len());
    for (id, mut e) in due {
        served.insert(id);
        frame(ctx, id, &mut e, now, on, trace.as_mut());
        VIEWERS.with(|v| v.borrow_mut().insert(id, e));
    }
    let phase = common::span("tick.cues");
    // Who is engaged with whom this tick; those engaged with a viewer join its near tier at once.
    let ids: HashSet<u32> = humans.iter().map(|(h, _)| *h).collect();
    let engaged = engaged_of(ctx, now, &ids);
    engaged_tiers(ctx, now, &engaged);
    if on {
        let cue_budget = (CUE_ROWS_PER_TICK * budget / FRAME_ROWS_PER_TICK).max(CUE_ROWS_MIN);
        cues(ctx, now, &served, &engaged, cue_budget, trace.as_mut());
    } else {
        // Nothing is owed while cues are off: what changes reaches clients at their frames.
        PENDING.with(|p| p.borrow_mut().clear());
        VIEWERS.with(|v| v.borrow_mut().values_mut().for_each(|e| e.pending.clear()));
    }
    drop(phase);
    if let Some(t) = trace {
        t.log(ctx);
    }
    // Rows written later (other transactions, the sweep) must be read again.
    NOW.with(|n| *n.borrow_mut() = None);
}

/// What each creature's move and visible act are aimed at (a scheduling hint: who is engaged
/// with whom decides only who is sent cues, never what a cue or a copy holds).
#[derive(Default)]
struct Targets {
    fighter: Option<(u32, u64)>,
    doing: Option<(u32, u64)>,
}

/// The players engaged with each creature now: those its unexpired move or visible act is aimed
/// at, and those whose own is aimed at it (from frame-fresh's `engagements`).
fn engaged_of(ctx: &ReducerContext, now: u64, human: &HashSet<u32>) -> HashMap<u32, Vec<u32>> {
    TARGETS.with(|targets| {
        let mut targets = targets.borrow_mut();
        let dirty = TARGET_DIRTY.with(|d| std::mem::take(&mut *d.borrow_mut()));
        for actor in dirty {
            let fighter = fighter_now(ctx, actor).filter(|f| f.act != 0 && f.target != 0 && f.until_ms > now);
            let doing = doing_now(ctx, actor).filter(|d| d.target != 0 && d.until_ms > now);
            targets.insert(actor, Targets { fighter: fighter.map(|f| (f.target, f.until_ms)), doing: doing.map(|d| (d.target, d.until_ms)) });
        }
        let mut of: HashMap<u32, Vec<u32>> = HashMap::new();
        targets.retain(|&actor, t| {
            let mut keep = false;
            for (other, until) in [t.fighter, t.doing].into_iter().flatten() {
                if now >= until {
                    continue;
                }
                keep = true;
                // The target sees the actor's changes, and the actor the target's.
                if human.contains(&other) {
                    of.entry(actor).or_default().push(other);
                }
                if human.contains(&actor) {
                    of.entry(other).or_default().push(actor);
                }
            }
            keep
        });
        of
    })
}

/// The tick's cues: each creature that changed since the last tick, to the viewers it is near or
/// engaged with that had no frame in this tick (a frame wrote their copies already), and each
/// viewer's newly near creatures that changed since its last frame.
/// Those engaged with a viewer (`engaged_of`: creature → viewers) and in its scene join its near
/// tier at once, beyond `NEAR_M` and past `NEAR_MAX` (an archer aiming at it from 20 m outranks
/// the twelfth bystander); its sweeps then rank them first (`scene`). Their copies move as they
/// are now.
fn engaged_tiers(ctx: &ReducerContext, now: u64, engaged: &HashMap<u32, Vec<u32>>) {
    let mut by_viewer: HashMap<u32, HashSet<u32>> = HashMap::new();
    for (&body, viewers) in engaged {
        for &v in viewers {
            by_viewer.entry(v).or_default().insert(body);
        }
    }
    let flips: Vec<(u32, Identity, u32)> = VIEWERS.with(|v| {
        let mut v = v.borrow_mut();
        let mut out = Vec::new();
        for (vid, bodies) in &by_viewer {
            let Some(e) = v.get_mut(vid) else { continue };
            let Some(scene) = e.scene.as_ref() else { continue };
            let new: Vec<u32> = bodies.iter().copied().filter(|b| scene.contains(b) && !e.near.contains(b)).collect();
            for b in new {
                e.near.insert(b);
                e.cued.remove(&b);
                e.pending.remove(&b);
                out.push((*vid, e.who, b));
            }
        }
        out
    });
    NEAR_OF.with(|n| {
        let mut n = n.borrow_mut();
        for (vid, _, b) in &flips {
            n.entry(*b).or_default().insert(*vid);
        }
    });
    if !flips.is_empty() {
        common::diag(|| "cues:engaged_near", flips.len() as u64);
    }
    for (vid, who, b) in flips {
        show_motion(ctx, vid, b, true);
        show_fighter(ctx, vid, who, b, true, true, now);
        show_doing(ctx, vid, who, b, true);
    }
    ENGAGED.with(|e| *e.borrow_mut() = by_viewer);
}

fn cues(ctx: &ReducerContext, now: u64, served: &HashSet<u32>, engaged: &HashMap<u32, Vec<u32>>, cue_budget: usize, mut trace: Option<&mut crate::frame_trace::Trace>) {
    let pending = PENDING.with(|p| std::mem::take(&mut *p.borrow_mut()));
    let since = CUED_SEQ.with(|c| c.replace(SEQ.with(Cell::get)));
    if let Some(t) = trace.as_deref_mut() {
        // Every near pair is looked at in every tick's cues (a change marked since the last).
        let pairs: usize = VIEWERS.with(|v| v.borrow().values().map(|e| e.near.len()).sum());
        t.cue_pass(now, pairs as u32);
    }
    // (viewer, creature, streams, far, since): pairs engaged at once (from the far tier only when
    // the viewer had no frame in this tick: the frame wrote their copies); near pairs are kept for
    // the viewer's next cue tick.
    let mut work: Vec<Cue> = Vec::new();
    let mut held: Vec<(u32, u32, u8)> = Vec::new();
    NEAR_OF.with(|n| {
        let n = n.borrow();
        for (&body, &bits) in &pending {
            let near = n.get(&body);
            let engaged = engaged.get(&body);
            for &viewer in near.into_iter().flatten() {
                if engaged.is_some_and(|e| e.contains(&viewer)) {
                    work.push((viewer, body, bits, false, since, true));
                } else {
                    held.push((viewer, body, bits));
                }
            }
            for &viewer in engaged.into_iter().flatten() {
                if !near.is_some_and(|s| s.contains(&viewer)) && !served.contains(&viewer) {
                    work.push((viewer, body, bits, true, since, true));
                }
            }
        }
    });
    let tick = CUE_TICK.with(|t| {
        let v = t.get() + 1;
        t.set(v);
        v
    });
    VIEWERS.with(|v| {
        let mut v = v.borrow_mut();
        for (viewer, body, bits) in held {
            if let Some(e) = v.get_mut(&viewer) {
                if e.pending.is_empty() {
                    e.pending_seq = since;
                }
                *e.pending.entry(body).or_default() |= bits;
            }
        }
        for (id, e) in v.iter_mut() {
            if !e.pending.is_empty() && (tick + *id as u64) % CUE_TICKS == 0 {
                let since = e.pending_seq;
                work.extend(e.pending.drain().map(|(body, bits)| (*id, body, bits, false, since, false)));
            }
        }
    });
    if work.is_empty() {
        return;
    }
    work.sort_unstable_by_key(|w| (w.0, w.1));
    work.dedup_by(|a, b| {
        let same = a.0 == b.0 && a.1 == b.1;
        if same {
            b.2 |= a.2;
            b.4 = b.4.min(a.4);
            b.5 |= a.5;
        }
        same
    });
    // The tick's budget of cue rows: engaged pairs first, then near ones in a turn that rotates by
    // tick; what is over waits as the viewer's pending cues.
    let late = over_budget(&mut work, cue_budget, tick);
    if !late.is_empty() {
        common::diag(|| "cues:deferred", late.len() as u64);
        VIEWERS.with(|v| {
            let mut v = v.borrow_mut();
            for (viewer, body, bits, _, since, _) in late {
                if let Some(e) = v.get_mut(&viewer) {
                    if e.pending.is_empty() {
                        e.pending_seq = since;
                    }
                    e.pending_seq = e.pending_seq.min(since);
                    *e.pending.entry(body).or_default() |= bits;
                    e.deferred.entry(body).or_insert(tick);
                }
            }
        });
    }
    let mut rows = 0u64;
    let mut i = 0;
    while i < work.len() {
        let viewer = work[i].0;
        let j = work[i..].iter().position(|w| w.0 != viewer).map_or(work.len(), |k| i + k);
        VIEWERS.with(|v| {
            let mut v = v.borrow_mut();
            let Some(e) = v.get_mut(&viewer) else { return };
            let Some(scene) = e.scene.as_ref() else { return };
            for &(_, body, bits, far, since, urgent) in &work[i..j] {
                let waited = e.deferred.remove(&body).map(|t| tick - t);
                if let Some(t) = trace.as_deref_mut() {
                    t.waited(waited.unwrap_or(0), urgent);
                }
                if !scene.contains(&body) {
                    continue;
                }
                let sent = cue(ctx, e.who, body, bits, now);
                if sent == 0 {
                    continue;
                }
                rows += sent.count_ones() as u64;
                if far {
                    *e.cued.entry(body).or_default() |= sent;
                }
                if let Some(t) = trace.as_deref_mut() {
                    if let Some(at) = changed_at(body, since) {
                        t.stale(now.saturating_sub(at), !far, true);
                    }
                }
            }
        });
        i = j;
    }
    common::diag(|| "cues:rows", rows);
}

/// One cue to send: (viewer, creature, streams, from the far tier, changes since, engaged).
type Cue = (u32, u32, u8, bool, u64, bool);

/// Keep within `budget` cue rows: every engaged pair (whatever the budget), then near pairs in a
/// turn that rotates with `tick`. Returns the near pairs over it (they wait for the next tick);
/// `work` stays sorted by viewer and creature.
fn over_budget(work: &mut Vec<Cue>, budget: usize, tick: u64) -> Vec<Cue> {
    let total: usize = work.iter().map(|w| w.2.count_ones() as usize).sum();
    if total <= budget {
        return Vec::new();
    }
    let turn = |viewer: u32| (viewer as u64).wrapping_mul(0x9E37_79B9).wrapping_add(tick.wrapping_mul(0x85EB_CA6B)) as u32;
    work.sort_unstable_by_key(|w| (!w.5, turn(w.0), w.1));
    let mut rows = 0;
    let mut keep = work.len();
    for (k, w) in work.iter().enumerate() {
        rows += w.2.count_ones() as usize;
        if rows > budget && !w.5 {
            keep = k;
            break;
        }
    }
    let late = work.split_off(keep);
    work.sort_unstable_by_key(|w| (w.0, w.1));
    late
}

/// Send `viewer` (`who`) cues of the streams `bits` of `body`, as its copies would hold them now.
/// Returns the streams sent (motion only for a body that is there).
fn cue(ctx: &ReducerContext, who: Identity, body: u32, bits: u8, now: u64) -> u8 {
    let mut sent = 0;
    if bits & MOTION != 0 {
        if let Some(m) = motion_now(ctx, body) {
            ctx.db.seen_body_cue().insert(SeenBodyCue { viewer: who, at_ms: now, motion: m });
            sent |= MOTION;
        }
    }
    if bits & FIGHTER != 0 {
        ctx.db.seen_fighter_cue().insert(SeenFighterCue { viewer: who, at_ms: now, body, fighter: fighter_cue(ctx, who, body, now) });
        sent |= FIGHTER;
    }
    if bits & DOING != 0 {
        ctx.db.seen_doing_cue().insert(SeenDoingCue { viewer: who, at_ms: now, body, doing: doing_now(ctx, body) });
        sent |= DOING;
    }
    sent
}

/// A creature's fighter row as a viewer's frame would show it after a change of its health: the
/// move as it is, the band as this viewer perceives it now.
fn fighter_cue(ctx: &ReducerContext, who: Identity, body: u32, now: u64) -> Option<Fighter> {
    fighter_now(ctx, body).map(|f| Fighter { band: perceived_band(ctx, who, body, now).0, ..f })
}

fn frame(ctx: &ReducerContext, id: u32, v: &mut Viewer, now: u64, on: bool, mut trace: Option<&mut crate::frame_trace::Trace>) {
    let upto = SEQ.with(|s| s.get());
    if let Some(scene) = v.scene.as_ref() {
        let since = if v.full { 0 } else { v.seq };
        let full = v.full;
        // The near tier follows at most every `NEAR_COPY_MS` (cues carry its changes meanwhile).
        let near_due = full || !on || now.saturating_sub(v.near_ms) >= NEAR_COPY_MS;
        let near_since = if full { 0 } else { v.near_seq };
        // The creatures cued since the last frame: a stream whose copy this frame does not write
        // is cued as it is now (`Cues` above).
        let mut cued = std::mem::take(&mut v.cued);
        if std::mem::take(&mut v.reconcile) {
            cued = scene.iter().map(|b| (*b, ALL)).collect();
        }
        for &body in scene {
            let near = v.near.contains(&body);
            if near && !near_due {
                continue;
            }
            let since = if near { near_since } else { since };
            let mut wrote = 0;
            if (full || changed(&MOVED, body, since)) && show_motion(ctx, id, body, near) {
                wrote |= MOTION;
            }
            let hurt = full || changed(&HURT, body, since);
            if (hurt || changed(&FOUGHT, body, since)) && show_fighter(ctx, id, v.who, body, near, hurt, now) {
                wrote |= FIGHTER;
            }
            if (full || changed(&DID, body, since)) && show_doing(ctx, id, v.who, body, near) {
                wrote |= DOING;
            }
            if let Some(t) = trace.as_deref_mut() {
                // Near copies are the durable state behind cues; their freshness is the cues'.
                if !near {
                    if wrote != 0 && !full {
                        if let Some(at) = changed_at(body, since) {
                            t.stale(now.saturating_sub(at), false, false);
                        }
                    }
                    t.served(id, body, now, false);
                }
            }
            if let Some(bits) = cued.get(&body).filter(|_| on) {
                let rest = bits & !wrote;
                if rest != 0 {
                    cue(ctx, v.who, body, rest, now);
                    common::diag(|| "cues:reconciled", rest.count_ones() as u64);
                }
            }
        }
        if near_due {
            v.near_ms = now;
            v.near_seq = upto;
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
    if now.saturating_sub(v.senses_ms) >= SENSES_MS {
        v.senses_ms = now;
        show_senses(ctx, id, v, now);
    }
    if now.saturating_sub(v.earshot_ms) >= EARSHOT_MS {
        v.earshot_ms = now;
        show_earshot(ctx, id, v, now);
    }
    v.last_ms = now;
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
    let ways = crate::earshot::reach(ctx, id, common::pos(&b, now), |x| scene.contains(&x), now);
    let text = crate::earshot::short_words(&ways, |x| common::label_for(ctx, &me, x));
    let row = CharacterEarshot { id, ways, text, at_ms: now };
    match v.earshot.as_ref() {
        Some(old) if old.ways == row.ways && old.text == row.text => {}
        Some(_) => v.earshot = Some(ctx.db.character_earshot().id().update(row)),
        None => v.earshot = Some(ctx.db.character_earshot().insert(row)),
    }
}

/// Bring a viewer's copy of a creature's motion up to date, in its tier: `motion_near` when
/// `near`, else `motion_seen` (moved between them as it is now when the tier changed). Returns
/// whether a copy was written.
fn show_motion(ctx: &ReducerContext, viewer: u32, body: u32, near: bool) -> bool {
    let k = key(viewer, body);
    let in_near = ctx.db.motion_near().id().find(k);
    let was_near = in_near.is_some();
    let Some(mut row) = in_near.map(|r| r.copy).or_else(|| ctx.db.motion_seen().id().find(k)) else { return false };
    let Some(m) = motion_now(ctx, body) else { return false };
    let changed = row.moving() != m;
    if !changed && was_near == near {
        return false;
    }
    row.set(&m);
    put_motion(ctx, row, was_near, near);
    true
}

fn put_motion(ctx: &ReducerContext, row: MotionSeen, was_near: bool, near: bool) {
    match (was_near, near) {
        (true, true) => {
            ctx.db.motion_near().id().update(MotionNear { id: row.id, viewer: row.viewer, copy: row });
        }
        (false, false) => {
            ctx.db.motion_seen().id().update(row);
        }
        (false, true) => {
            ctx.db.motion_seen().id().delete(row.id);
            ctx.db.motion_near().insert(MotionNear { id: row.id, viewer: row.viewer, copy: row });
        }
        (true, false) => {
            ctx.db.motion_near().id().delete(row.id);
            ctx.db.motion_seen().insert(row);
        }
    }
}

/// Bring a viewer's copy of a creature's `fighter` row up to date, in its tier (`fighter_near`
/// when `near`, else `fighter_seen`): its move as it is now; its band as the viewer perceives it
/// (255 while its projection hides health) when `hurt`, else as last shown. A creature with no
/// fighter row has none. Returns whether a copy was written.
pub fn show_fighter(ctx: &ReducerContext, viewer: u32, who: Identity, body: u32, near: bool, hurt: bool, now: u64) -> bool {
    let k = key(viewer, body);
    let in_near = ctx.db.fighter_near().id().find(k);
    let was_near = in_near.is_some();
    let row = in_near.map(|r| r.copy).or_else(|| ctx.db.fighter_seen().id().find(k));
    let Some(f) = fighter_now(ctx, body) else {
        if row.is_some() {
            ctx.db.fighter_seen().id().delete(k);
            ctx.db.fighter_near().id().delete(k);
            return true;
        }
        return false;
    };
    let band = match row.as_ref() {
        Some(r) if !hurt => r.fighter.band,
        _ => perceived_band(ctx, who, body, now).0,
    };
    let new = FighterSeen { id: k, viewer: who, fighter: Fighter { band, ..f } };
    if row.as_ref() == Some(&new) && was_near == near {
        return false;
    }
    match (row.is_some() && was_near, row.is_some() && !was_near, near) {
        (true, _, true) => {
            ctx.db.fighter_near().id().update(FighterNear { id: k, viewer: who, copy: new });
        }
        (_, true, false) => {
            ctx.db.fighter_seen().id().update(new);
        }
        (in_n, in_f, near) => {
            if in_n {
                ctx.db.fighter_near().id().delete(k);
            }
            if in_f {
                ctx.db.fighter_seen().id().delete(k);
            }
            if near {
                ctx.db.fighter_near().insert(FighterNear { id: k, viewer: who, copy: new });
            } else {
                ctx.db.fighter_seen().insert(new);
            }
        }
    }
    true
}

/// Bring a viewer's copy of what a creature is visibly doing up to date, in its tier
/// (`doing_near` when `near`, else `doing_seen`; none while it shows nothing). Returns whether a
/// copy was written.
pub fn show_doing(ctx: &ReducerContext, viewer: u32, who: Identity, body: u32, near: bool) -> bool {
    let k = key(viewer, body);
    let in_near = ctx.db.doing_near().id().find(k);
    let was_near = in_near.is_some();
    let row = in_near.map(|r| r.copy).or_else(|| ctx.db.doing_seen().id().find(k));
    let Some(d) = doing_now(ctx, body) else {
        if row.is_some() {
            ctx.db.doing_seen().id().delete(k);
            ctx.db.doing_near().id().delete(k);
            return true;
        }
        return false;
    };
    let new = DoingSeen { id: k, viewer: who, doing: d };
    if row.as_ref() == Some(&new) && was_near == near {
        return false;
    }
    match (row.is_some() && was_near, row.is_some() && !was_near, near) {
        (true, _, true) => {
            ctx.db.doing_near().id().update(DoingNear { id: k, viewer: who, copy: new });
        }
        (_, true, false) => {
            ctx.db.doing_seen().id().update(new);
        }
        (in_n, in_f, near) => {
            if in_n {
                ctx.db.doing_near().id().delete(k);
            }
            if in_f {
                ctx.db.doing_seen().id().delete(k);
            }
            if near {
                ctx.db.doing_near().insert(DoingNear { id: k, viewer: who, copy: new });
            } else {
                ctx.db.doing_seen().insert(new);
            }
        }
    }
    true
}

/// A creature left a viewer's scene, or died: its copies in both tiers go.
pub fn drop_copies(ctx: &ReducerContext, viewer: u32, body: u32) {
    let k = key(viewer, body);
    ctx.db.motion_seen().id().delete(k);
    ctx.db.fighter_seen().id().delete(k);
    ctx.db.doing_seen().id().delete(k);
    ctx.db.motion_near().id().delete(k);
    ctx.db.fighter_near().id().delete(k);
    ctx.db.doing_near().id().delete(k);
}

/// A creature died: its profiling history goes (`CHANGES`, `frame_trace`). Only that: a death
/// that rolls back must not take marks or tiers that still owe a delivery, and those maps lose a
/// creature's keys by other paths (the sweep's scenes, `engaged_of`'s expiry).
pub fn creature_gone(id: u32) {
    CHANGES.with(|c| c.borrow_mut().remove(&id));
    crate::frame_trace::forget(id);
}

// Row-level security for the cue event tables: a client receives only its own cues.
#[spacetimedb::client_visibility_filter]
const SEEN_BODY_CUE_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM seen_body_cue WHERE viewer = :sender");
#[spacetimedb::client_visibility_filter]
const SEEN_FIGHTER_CUE_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM seen_fighter_cue WHERE viewer = :sender");
#[spacetimedb::client_visibility_filter]
const SEEN_DOING_CUE_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM seen_doing_cue WHERE viewer = :sender");

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

#[cfg(test)]
mod tests {
    use super::*;

    fn cue(viewer: u32, body: u32, engaged: bool) -> Cue {
        (viewer, body, MOTION, false, 0, engaged)
    }

    #[test]
    fn the_cue_budget_keeps_every_engaged_pair_first() {
        // 10 engaged pairs and 100 near ones, budget 20: all 10 engaged and 10 near go.
        let mut work: Vec<Cue> = (0..10).map(|i| cue(i, 1000 + i, true)).chain((0..100).map(|i| cue(i % 7, i, false))).collect();
        let late = over_budget(&mut work, 20, 3);
        assert_eq!(work.len(), 20);
        assert_eq!(work.iter().filter(|w| w.5).count(), 10);
        assert_eq!(late.len(), 90);
        assert!(late.iter().all(|w| !w.5), "an engaged pair was deferred");
        assert!(work.windows(2).all(|p| (p[0].0, p[0].1) <= (p[1].0, p[1].1)), "kept work is sorted by viewer and creature");
        // More engaged pairs than the budget: all of them still go, no near one does.
        let mut work: Vec<Cue> = (0..30).map(|i| cue(i, i, true)).chain((0..5).map(|i| cue(i, 500 + i, false))).collect();
        let late = over_budget(&mut work, 20, 4);
        assert_eq!(work.len(), 30);
        assert!(work.iter().all(|w| w.5));
        assert_eq!(late.len(), 5);
        // Within budget: nothing deferred.
        let mut work: Vec<Cue> = (0..5).map(|i| cue(i, i, false)).collect();
        assert!(over_budget(&mut work, 20, 5).is_empty());
        // The near pairs kept rotate with the tick: different ticks favour different viewers.
        let near = |tick| {
            let mut w: Vec<Cue> = (0..50).map(|i| cue(i, i, false)).collect();
            over_budget(&mut w, 10, tick);
            w.iter().map(|c| c.0).collect::<Vec<_>>()
        };
        assert_ne!(near(1), near(2));
    }
}
