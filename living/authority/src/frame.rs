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
use crate::perception::{Moving, Segment};
use crate::tables::*;
use spacetimedb::{Identity, ReducerContext, Table};
use std::cell::{Cell, RefCell};
use std::collections::{BTreeSet, HashMap, HashSet, VecDeque};

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
/// What a frame costs beyond its rows, in rows: its views' fixed cost per refresh (in 2.14.1 about
/// 40 µs a refresh against about 2 µs a row; docs/TICK_RATE.md, "Post-review series").
pub const FRAME_FIXED_ROWS: usize = 16;
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
/// At most this many creatures are in a viewer's near tier (beyond those engaged with it): the
/// nearest within [`NEAR_M`]. A near creature's every change is cued to the viewer, so in a dense
/// crowd (200 fighters within 9 m) an unbounded tier fans each change out to everyone; the rest
/// of the crowd follows at the frames, as on main. 32 holds the measured crowd's whole near
/// neighbourhood (31 within 3 m); 12 left most of it to frames (near p90 160 ms).
pub const NEAR_MAX: usize = 32;
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
    /// Under heed (the `heed_players` law): the rest of its sight, its throng, as its last sweep
    /// left it. Earshot reads sight, the scene and the throng (docs/ATTENTION_BUDGET.md v2.1
    /// point 4); nothing else reads it. Empty while heed does not apply. A `BTreeSet`: a std
    /// set made per viewer would shift the hash keys of every later map (docs/GATE216_GROWTH.md).
    throng: BTreeSet<u32>,
}

impl Viewer {
    fn new(who: Identity) -> Self {
        Self { who, scene: None, seq: 0, full: true, last_ms: 0, lines_ms: 0, band_ms: 0, band_seq: 0, events: Vec::new(), feed: VecDeque::new(), senses_ms: 0, senses: None, earshot_ms: 0, earshot: None, near: HashSet::new(), near_ms: 0, near_seq: 0, cued: HashMap::new(), pending: HashMap::new(), pending_seq: 0, deferred: HashMap::new(), reconcile: true, throng: BTreeSet::new() }
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
    /// Whether either delivery law (`cue_transport_on`, `near_tier_on`) was on at the last tick.
    /// Both off, the frames take main's path: no cue marks, no targets, no near tier (`deliver`).
    static DELIVERY: Cell<bool> = const { Cell::new(true) };
    /// The sequence number at the last tick's cues, and how many ticks have sent cues.
    static CUED_SEQ: Cell<u64> = const { Cell::new(0) };
    static CUE_TICK: Cell<u64> = const { Cell::new(0) };
    /// The `motion_tables_on` law at the last tick (`None`: not yet in this instance, or after a
    /// step this instance did not see commit).
    static MOTION_TABLES: Cell<Option<bool>> = const { Cell::new(None) };
    /// The `characters_table_on` law at the last tick (as `MOTION_TABLES`).
    static CHAR_TABLES: Cell<Option<bool>> = const { Cell::new(None) };
    /// The `lines_table_on` law at the last tick (as `MOTION_TABLES`).
    static LINES_TABLE: Cell<Option<bool>> = const { Cell::new(None) };
    /// `lines_table_check`'s running total: viewer-ticks compared, differed, ticks since the last log.
    static LINES_CHECKED: Cell<(u64, u64, u64)> = const { Cell::new((0, 0, 0)) };
    /// The `fighter_tables_on` law at the last tick (as `MOTION_TABLES`).
    static FIGHTER_TABLES: Cell<Option<bool>> = const { Cell::new(None) };
    /// Whether `copy_state` may hold a row (`None`: not looked at in this instance). Never set
    /// back to false, so a step that rolls back can only leave it true: a lookup, never a miss.
    static ANY_STATE: Cell<Option<bool>> = const { Cell::new(None) };
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
    /// The ids whose `health` came from the tick's sweeps (`perception::Swept`) and is not yet
    /// used: the first use of each is counted (`frames:health_seeded`).
    seeded: HashSet<u32>,
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
    NOW.with(|n| {
        if n.borrow_mut().as_mut().is_some_and(|s| s.seeded.remove(&id)) {
            common::diag(|| "frames:health_seeded", 1);
        }
    });
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
    if DELIVERY.with(Cell::get) {
        PENDING.with(|p| *p.borrow_mut().entry(id).or_default() |= stream);
    }
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
    if DELIVERY.with(Cell::get) {
        TARGET_DIRTY.with(|d| d.borrow_mut().insert(id));
    }
}

/// A creature's health moved (its band, or exact health where shown).
pub fn hurt(id: u32) {
    mark(&HURT, id, FIGHTER);
}

/// A creature's `doing` row was written or deleted.
pub fn did(id: u32) {
    mark(&DID, id, DOING);
    if DELIVERY.with(Cell::get) {
        TARGET_DIRTY.with(|d| d.borrow_mut().insert(id));
    }
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
    // The `near_tier_on` law: off, no creature is near, so every copy is in the far tier.
    let tiers = common::laws(ctx).near_tier_on;
    let flips: Vec<(u32, bool)> = VIEWERS.with(|v| {
        let mut v = v.borrow_mut();
        let e = v.entry(id).or_insert_with(|| Viewer::new(who));
        if e.who != who {
            unnear(id, &e.near);
            *e = Viewer::new(who);
        }
        e.scene = Some(seen.clone());
        let engaged = ENGAGED.with(|g| g.borrow().get(&id).cloned()).unwrap_or_default();
        let near = near_set(tiers, &engaged, seen, dist, &e.near);
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
    let public = if flips.is_empty() { false } else { public_of(ctx, who) };
    for (body, near) in flips {
        show_motion(ctx, id, who, body, near, public);
        show_fighter(ctx, id, who, body, near, true, now, None);
        show_doing(ctx, id, who, body, near);
    }
}

/// Viewer `id`'s throng at this sweep (after [`scene`]; empty while heed does not apply to it).
pub fn set_throng(id: u32, throng: BTreeSet<u32>) {
    VIEWERS.with(|v| {
        if let Some(e) = v.borrow_mut().get_mut(&id) {
            e.throng = throng;
        }
    });
}

/// Heed does not apply to viewer `id`: its throng is empty (nothing is made while it already is).
pub fn clear_throng(id: u32) {
    VIEWERS.with(|v| {
        if let Some(e) = v.borrow_mut().get_mut(&id).filter(|e| !e.throng.is_empty()) {
            e.throng.clear();
        }
    });
}

/// Contact put `body` in viewer `id`'s `perceived` set between its sweeps (`perception::admit`):
/// its scene holds it from now, so cues and the engaged path follow it at once; its sweep keeps
/// it (forced) or lets it go as any other.
pub fn join_scene(id: u32, body: u32) {
    VIEWERS.with(|v| {
        if let Some(e) = v.borrow_mut().get_mut(&id) {
            if let Some(scene) = e.scene.as_mut() {
                scene.insert(body);
            }
            e.throng.remove(&body);
        }
    });
}

/// The creatures engaged with viewer `id` at the last tick (battle law `far_cap` keeps them).
pub fn engaged_with(id: u32) -> HashSet<u32> {
    ENGAGED.with(|g| g.borrow().get(&id).cloned()).unwrap_or_default()
}

fn ctx_now(ctx: &ReducerContext) -> u64 {
    common::now_ms(ctx)
}

/// Where a motion copy puts its creature at `t` (the client's extrapolation, as `common::pos`).
fn moving_pos(m: &Moving, t: u64) -> (f32, f32) {
    if m.vx == 0.0 && m.vy == 0.0 {
        return (m.x, m.y);
    }
    let dt = t.min(m.next_ms).saturating_sub(m.t_ms) as f32 / 1000.0;
    if m.turn == 0.0 || m.turn_s <= 0.0 {
        return (m.x + m.vx * dt, m.y + m.vy * dt);
    }
    let (x, y, _) = living_rules::steer::pose(m.x, m.y, m.heading, (m.vx * m.vx + m.vy * m.vy).sqrt(), m.turn, m.turn_s, dt);
    (x, y)
}

/// (e) battle law `far_motion_tol_m`: whether the old far copy still puts the creature within `tol`
/// metres of where the new motion does, now, in 250 and 500 ms, and at the end of either segment
/// (at most 2 s on), so the copy is kept and nothing is written.
fn within_tol(old: &Moving, new: &Moving, now: u64, tol: f32) -> bool {
    let end = old.next_ms.min(new.next_ms).min(now + 2_000).max(now);
    [now, now + 250, now + 500, end].into_iter().all(|t| {
        let (a, b) = (moving_pos(old, t), moving_pos(new, t));
        ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt() < tol
    })
}

/// Whether `body` is in the near tier of viewer `id` (as its last sweep left it).
pub fn is_near(id: u32, body: u32) -> bool {
    VIEWERS.with(|v| v.borrow().get(&id).is_some_and(|e| e.near.contains(&body)))
}

/// A viewer's near tier at a sweep. Off (`near_tier_on`): none, and nothing is worked out. On:
/// first whoever is engaged with it (its move or visible act aimed at the viewer, or the viewer's
/// at it), at any distance in sight and past the cap; then, in the slots left of [`NEAR_MAX`], the
/// nearest within [`NEAR_M`] ([`NEAR_KEEP_M`] for one already near); one already near counts half
/// a metre nearer, so a crowd's tier does not flap at the cut.
fn near_set(tiers: bool, engaged: &HashSet<u32>, seen: &HashSet<u32>, dist: &HashMap<u32, f32>, was: &HashSet<u32>) -> HashSet<u32> {
    if !tiers {
        return HashSet::new();
    }
    let engaged: Vec<u32> = engaged.iter().copied().filter(|b| seen.contains(b)).collect();
    let slots = NEAR_MAX.saturating_sub(engaged.len());
    let mut cand: Vec<(f32, u32)> = seen
        .iter()
        .filter(|b| !engaged.contains(b))
        .filter_map(|b| {
            let d = *dist.get(b)?;
            let already = was.contains(b);
            (d <= NEAR_M || (already && d <= NEAR_KEEP_M)).then_some((if already { d - 0.5 } else { d }, *b))
        })
        .collect();
    if cand.len() > slots {
        cand.sort_unstable_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
        cand.truncate(slots);
        common::diag(|| "cues:near_capped", 1);
    }
    engaged.into_iter().chain(cand.into_iter().map(|(_, b)| b)).collect()
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
    MOTION_TABLES.with(|m| m.set(None));
    CHAR_TABLES.with(|m| m.set(None));
    FIGHTER_TABLES.with(|m| m.set(None));
    LINES_TABLE.with(|m| m.set(None));

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
pub fn deliver(ctx: &ReducerContext, now: u64, swept: crate::perception::Swept) {
    let budget = budget(ctx.timestamp.to_micros_since_unix_epoch());
    // The sweeps' health readings seed this step's (exact items, docs/COMBAT_PHASE.md): the same
    // formula (`common::needs(&v, now).hp`, `max_hp`) at the same `now`, and nothing writes
    // `vitals` between them. In `tick::tick` the perception sweep runs right before this, after
    // every phase that damages or heals (activity completions, missiles, the combat cadence's
    // begins); between the two only the `memory_test` diagnostic runs, which writes no `vitals`;
    // the sweeps themselves write `projected`, `perceived`, `heard` and copies, never `vitals`.
    // Another reducer (`admin_set_vitals`, a player's move) is its own transaction, before or
    // after this whole tick. Under `regard_cache_check` each seeded reading is compared with a
    // fresh read (`frames:health_seed_differed`, which must stay 0). Like the rest of `Sources`,
    // the seed lives only in this call (set here, dropped at the end).
    let crate::perception::Swept { ids: swept, health } = swept;
    if common::laws(ctx).regard_cache_check {
        for (id, h) in &health {
            let fresh = ctx.db.vitals().id().find(*id).map(|v| (common::needs(&v, now).hp, v.max_hp));
            if fresh != *h {
                common::diag(|| "frames:health_seed_differed", 1);
                log::error!("exact items: #{id}'s seeded health {h:?} differs from a fresh read {fresh:?}");
            }
        }
    }
    let seeded: HashSet<u32> = health.keys().copied().collect();
    NOW.with(|n| *n.borrow_mut() = Some(Sources { health, seeded, ..Sources::default() }));
    let swept = swept.as_slice();
    let humans = crate::combat::humans(ctx);
    // The `cue_transport_on` law: off, no cue is written and near copies follow at every frame.
    // With `near_tier_on` off too, frames are scheduled as before frame-views.
    let on = common::laws(ctx).cue_transport_on;
    let tiers = common::laws(ctx).near_tier_on;
    // The `motion_tables_on` law (battle-views): on, each viewer's frame moves its motion copies
    // to `seen_body_copy`; off, the first tick to see it so (or a fresh instance's first) moves
    // every public copy back at once.
    let tables = common::laws(ctx).motion_tables_on;
    // The `characters_table_on` law (battle-views addendum 2): on, each viewer's frame fills its
    // mirror of its projections whole; off, the first tick to see it so drops every mirror row.
    let chars = common::laws(ctx).characters_table_on;
    if all_back(CHAR_TABLES.with(|m| m.replace(Some(chars))), chars) {
        let phase = common::span("tick.characters_private");
        let n = crate::perception::drop_mirrors(ctx);
        drop(phase);
        if n > 0 {
            common::diag(|| "characters_table:dropped", n as u64);
            log::info!("characters table off: {n} mirror rows dropped");
        }
    }
    // The `lines_table_on` law (experience-incremental): on, each player's lines are also rows of
    // `experience_copy`; off, the first tick to see it so drops every copy.
    let lines = common::laws(ctx).lines_table_on;
    if all_back(LINES_TABLE.with(|m| m.replace(Some(lines))), lines) {
        let n = drop_line_copies(ctx);
        if n > 0 {
            common::diag(|| "lines_table:dropped", n as u64);
            log::info!("lines table off: {n} line copies dropped");
        }
    }
    if common::laws(ctx).lines_table_check {
        check_line_copies(ctx);
    }
    // The `fighter_tables_on` law (views step 3): as the motion tables, for the fighter copies.
    let fighters = common::laws(ctx).fighter_tables_on;
    if all_back(FIGHTER_TABLES.with(|m| m.replace(Some(fighters))), fighters) {
        let phase = common::span("tick.fighters_private");
        let n = all_private_fighters(ctx);
        drop(phase);
        if n > 0 {
            common::diag(|| "fighter_tables:moved_out", n as u64);
            log::info!("fighter tables off: {n} copies moved back to the private tables");
        }
    }
    if all_back(MOTION_TABLES.with(|m| m.replace(Some(tables))), tables) {
        let phase = common::span("tick.motion_private");
        let n = all_private(ctx);
        drop(phase);
        if n > 0 {
            common::diag(|| "motion_tables:moved_out", n as u64);
            log::info!("motion tables off: {n} copies moved back to the private tables");
        }
    }
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
            // Rows, plus a fixed charge per frame for its views' own cost (a far frame of a few rows
            // costs mostly that): without it a crowd of small frames all fit one step, and after a
            // late tick every viewer comes due in the same step from then on.
            let moving_in = tables && !public_of(ctx, e.who);
            let n = if moving_in { n_all } else { far + if near_due { e.near.len() } else { 0 } } + if tiers { FRAME_FIXED_ROWS } else { 0 };
            // (b) battle law `crowd_frame_max_ms` (docs/BATTLE_LAWS.md): a higher ceiling in a crowd.
            let every = match common::laws(ctx).crowd_frame_max_ms {
                m if m > 0.0 => (far as u64 * 1000 / SCENE_ROWS_PER_S).clamp(FRAME_MIN_MS, m as u64),
                _ => interval(far),
            };
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
    // Both delivery laws off: main's path from here on (no engagements, no cue marks); what was
    // kept for them goes once, at the change. An engagement under way when they are turned on
    // again is known from its next move or act.
    let delivery = on || tiers;
    if DELIVERY.with(|d| d.replace(delivery)) && !delivery {
        PENDING.with(|p| p.borrow_mut().clear());
        TARGETS.with(|t| t.borrow_mut().clear());
        TARGET_DIRTY.with(|d| d.borrow_mut().clear());
        ENGAGED.with(|e| e.borrow_mut().clear());
        VIEWERS.with(|v| v.borrow_mut().values_mut().for_each(|e| e.pending.clear()));
    }
    if delivery {
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
    if !common::laws(ctx).near_tier_on {
        ENGAGED.with(|e| *e.borrow_mut() = by_viewer);
        return;
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
        let public = public_of(ctx, who);
        show_motion(ctx, vid, who, b, true, public);
        show_fighter(ctx, vid, who, b, true, true, now, None);
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
                // A cue goes to a creature near the viewer (its tier as its last sweep left it) or
                // engaged with it; anything else is a delivery fault, logged with how it came.
                if !e.near.contains(&body) && !urgent {
                    common::diag(|| "cues:not_near", 1);
                    log::warn!("cue fault: viewer #{viewer} cued #{body} (bits {bits}) neither near nor engaged (far path {far})");
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
    // Where its motion copies are; with the `motion_tables_on` law on, a viewer whose copies are
    // still private has them moved to `seen_body_copy` here, all at once (`to_public`).
    let mut public = public_of(ctx, v.who);
    if !public && MOTION_TABLES.with(|m| m.get()) == Some(true) {
        let n = to_public(ctx, v.who);
        common::diag(|| "motion_tables:moved_in", n as u64);
        public = true;
    }
    if FIGHTER_TABLES.with(|m| m.get()) == Some(true) && !fighters_public(ctx, v.who) {
        let n = fighters_to_public(ctx, v.who);
        common::diag(|| "fighter_tables:moved_in", n as u64);
    }
    if CHAR_TABLES.with(|m| m.get()) == Some(true) && !crate::perception::mirrored(ctx, v.who) {
        let n = crate::perception::fill_mirror(ctx, v.who);
        common::diag(|| "characters_table:filled", n as u64);
    }
    if LINES_TABLE.with(|m| m.get()) == Some(true) && ctx.db.lines_state().viewer().find(v.who).is_none() {
        let n = lines_resync(ctx, v.who, crate::perception::current_of(ctx, v.who).map(|c| c.id));
        common::diag(|| "lines_table:filled", n as u64);
    }
    if let Some(scene) = v.scene.as_ref() {
        let since = if v.full { 0 } else { v.seq };
        let full = v.full;
        // The near tier follows at most every `NEAR_COPY_MS` (cues carry its changes meanwhile).
        let near_due = full || !on || now.saturating_sub(v.near_ms) >= NEAR_COPY_MS;
        let near_since = if full { 0 } else { v.near_seq };
        // The creatures cued since the last frame: a stream whose copy this frame does not write
        // is cued as it is now (`Cues` above).
        let mut cued = std::mem::take(&mut v.cued);
        if std::mem::take(&mut v.reconcile) && on {
            cued = scene.iter().map(|b| (*b, ALL)).collect();
        }
        for &body in scene {
            let near = v.near.contains(&body);
            if near && !near_due {
                continue;
            }
            let since = if near { near_since } else { since };
            let mut wrote = 0;
            if (full || changed(&MOVED, body, since)) && show_motion(ctx, id, v.who, body, near, public) {
                wrote |= MOTION;
            }
            let hurt = full || changed(&HURT, body, since);
            if (hurt || changed(&FOUGHT, body, since)) && show_fighter(ctx, id, v.who, body, near, hurt, now, None) {
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
    let (ways, text) = if v.throng.is_empty() {
        let ways = crate::earshot::reach(ctx, id, common::pos(&b, now), |x| scene.contains(&x), now);
        let text = crate::earshot::short_words(&ways, |x| common::label_for(ctx, &me, x));
        (ways, text)
    } else {
        // Under heed: reach reads sight (the scene and the throng); the row names individuals only.
        let all = crate::earshot::reach(ctx, id, common::pos(&b, now), |x| scene.contains(&x) || v.throng.contains(&x), now);
        let ways: Vec<EarshotWay> = all.iter().map(|w| EarshotWay { way: w.way.clone(), hearers: w.hearers.iter().copied().filter(|x| scene.contains(x)).collect() }).collect();
        let text = crate::earshot::short_words_throng(&ways, &all, |x| common::label_for(ctx, &me, x));
        (ways, text)
    };
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
fn show_motion(ctx: &ReducerContext, viewer: u32, who: Identity, body: u32, near: bool, public: bool) -> bool {
    let k = key(viewer, body);
    if public {
        let Some(row) = ctx.db.seen_body_copy().viewer_body().filter((who, body)).next() else { return false };
        let Some(m) = motion_now(ctx, body) else { return false };
        let seg = Segment::of(&m);
        if row.seg == seg && row.near == near {
            return false;
        }
        let tol = common::laws(ctx).far_motion_tol_m;
        if tol > 0.0 && !near && !row.near && within_tol(&row.seg.moving(body), &m, ctx_now(ctx), tol) {
            common::diag(|| "frames:far_kept", 1);
            return false;
        }
        ctx.db.seen_body_copy().delete(row);
        ctx.db.seen_body_copy().insert(SeenBodyCopy { viewer: who, body, near, seg });
        return true;
    }
    // The expected tier's table first (the other only when the copy is not there).
    let (was_near, row) = if near {
        match ctx.db.motion_near().id().find(k) {
            Some(r) => (true, Some(r.copy)),
            None => (false, ctx.db.motion_seen().id().find(k)),
        }
    } else {
        match ctx.db.motion_seen().id().find(k) {
            Some(r) => (false, Some(r)),
            None => (true, ctx.db.motion_near().id().find(k).map(|r| r.copy)),
        }
    };
    let Some(mut row) = row else { return false };
    let Some(m) = motion_now(ctx, body) else { return false };
    let changed = row.moving() != m;
    if !changed && was_near == near {
        return false;
    }
    let tol = common::laws(ctx).far_motion_tol_m;
    if tol > 0.0 && !near && !was_near && within_tol(&row.moving(), &m, ctx_now(ctx), tol) {
        common::diag(|| "frames:far_kept", 1);
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
pub fn show_fighter(ctx: &ReducerContext, viewer: u32, who: Identity, body: u32, near: bool, hurt: bool, now: u64, known_band: Option<u8>) -> bool {
    let k = key(viewer, body);
    // Views step 3: a viewer's fighter copies are all public (`seen_fighter_copy`) or all private.
    let public = fighters_public(ctx, who);
    let (was_near, row) = if public {
        match ctx.db.seen_fighter_copy().id().find(k) {
            Some(r) => (r.near, Some(FighterSeen { id: k, viewer: who, fighter: r.fighter })),
            None => (false, None),
        }
    } else if near {
        match ctx.db.fighter_near().id().find(k) {
            Some(r) => (true, Some(r.copy)),
            None => (false, ctx.db.fighter_seen().id().find(k)),
        }
    } else {
        match ctx.db.fighter_seen().id().find(k) {
            Some(r) => (false, Some(r)),
            None => {
                let r = ctx.db.fighter_near().id().find(k).map(|r| r.copy);
                (r.is_some(), r)
            }
        }
    };
    let Some(f) = fighter_now(ctx, body) else {
        if row.is_some() {
            if public {
                ctx.db.seen_fighter_copy().id().delete(k);
            } else {
                ctx.db.fighter_seen().id().delete(k);
                ctx.db.fighter_near().id().delete(k);
            }
            return true;
        }
        return false;
    };
    let band = match row.as_ref() {
        Some(r) if !hurt => r.fighter.band,
        // The sweep passes the band of the projection it has just written for this newcomer, from
        // the same health reading in the same transaction: what `perceived_band` would read back.
        _ => match known_band {
            Some(b) => {
                common::diag(|| "frames:band_passed", 1);
                if common::laws(ctx).regard_cache_check && perceived_band(ctx, who, body, now).0 != b {
                    common::diag(|| "frames:band_passed_differed", 1);
                    log::error!("exact items: #{body}'s passed band {b} for {who} differs from perceived_band");
                }
                b
            }
            None => perceived_band(ctx, who, body, now).0,
        },
    };
    let new = FighterSeen { id: k, viewer: who, fighter: Fighter { band, ..f } };
    if row.as_ref() == Some(&new) && was_near == near {
        return false;
    }
    if public {
        let copy = SeenFighterCopy { id: k, viewer: who, body, near, fighter: new.fighter };
        if row.is_some() {
            ctx.db.seen_fighter_copy().id().update(copy);
        } else {
            ctx.db.seen_fighter_copy().insert(copy);
        }
        return true;
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
    let (was_near, row) = if near {
        match ctx.db.doing_near().id().find(k) {
            Some(r) => (true, Some(r.copy)),
            None => (false, ctx.db.doing_seen().id().find(k)),
        }
    } else {
        match ctx.db.doing_seen().id().find(k) {
            Some(r) => (false, Some(r)),
            None => {
                let r = ctx.db.doing_near().id().find(k).map(|r| r.copy);
                (r.is_some(), r)
            }
        }
    };
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
pub fn drop_copies(ctx: &ReducerContext, viewer: u32, who: Identity, body: u32) {
    let k = key(viewer, body);
    if public_of(ctx, who) {
        drop_public(ctx, who, body);
    } else {
        ctx.db.motion_seen().id().delete(k);
        ctx.db.motion_near().id().delete(k);
    }
    if fighters_public(ctx, who) {
        ctx.db.seen_fighter_copy().id().delete(k);
    } else {
        ctx.db.fighter_seen().id().delete(k);
        ctx.db.fighter_near().id().delete(k);
    }
    ctx.db.doing_seen().id().delete(k);
    ctx.db.doing_near().id().delete(k);
}

/// Whether viewer `who`'s fighter copies are in `seen_fighter_copy` (views step 3).
fn fighters_public(ctx: &ReducerContext, who: Identity) -> bool {
    copy_state(ctx, who).fighters
}

/// Move a viewer's fighter copies from the private tables to `seen_fighter_copy`, tiers kept, in
/// this transaction (as `to_public` for the motion copies).
fn fighters_to_public(ctx: &ReducerContext, who: Identity) -> usize {
    let far: Vec<FighterSeen> = ctx.db.fighter_seen().viewer().filter(who).collect();
    let near: Vec<FighterNear> = ctx.db.fighter_near().viewer().filter(who).collect();
    let n = far.len() + near.len();
    // A row already there (module memory that missed a rollback) is replaced, not a duplicate key.
    for r in far {
        ctx.db.fighter_seen().id().delete(r.id);
        ctx.db.seen_fighter_copy().id().delete(r.id);
        ctx.db.seen_fighter_copy().insert(SeenFighterCopy { id: r.id, viewer: who, body: r.fighter.id, near: false, fighter: r.fighter });
    }
    for r in near {
        ctx.db.fighter_near().id().delete(r.id);
        ctx.db.seen_fighter_copy().id().delete(r.id);
        ctx.db.seen_fighter_copy().insert(SeenFighterCopy { id: r.id, viewer: who, body: r.copy.fighter.id, near: true, fighter: r.copy.fighter });
    }
    set_copy_state(ctx, CopyState { fighters: true, ..copy_state(ctx, who) });
    n
}

/// The kill switch of the `fighter_tables_on` law: every public fighter copy goes back to the
/// private tables of its tier, in this transaction (as `all_private` for the motion copies).
fn all_private_fighters(ctx: &ReducerContext) -> usize {
    let rows: Vec<SeenFighterCopy> = ctx.db.seen_fighter_copy().iter().collect();
    for r in &rows {
        ctx.db.seen_fighter_copy().id().delete(r.id);
        // The public row's key is the private copy's (the viewer's character and the creature).
        let k = r.id;
        ctx.db.fighter_seen().id().delete(k);
        ctx.db.fighter_near().id().delete(k);
        let copy = FighterSeen { id: k, viewer: r.viewer, fighter: r.fighter.clone() };
        if r.near {
            ctx.db.fighter_near().insert(FighterNear { id: k, viewer: r.viewer, copy });
        } else {
            ctx.db.fighter_seen().insert(copy);
        }
    }
    for s in ctx.db.copy_state().iter().filter(|s| s.fighters).collect::<Vec<_>>() {
        set_copy_state(ctx, CopyState { fighters: false, ..s });
    }
    rows.len()
}

/// Delete viewer `who`'s public copy of `body`, if there is one.
fn drop_public(ctx: &ReducerContext, who: Identity, body: u32) {
    for r in ctx.db.seen_body_copy().viewer_body().filter((who, body)).collect::<Vec<_>>() {
        ctx.db.seen_body_copy().delete(r);
    }
}

/// Where viewer `who`'s copies stand (`copy_state`; no row, or a world that never had one in this
/// instance: neither public nor mirrored).
pub fn copy_state(ctx: &ReducerContext, who: Identity) -> CopyState {
    let any = ANY_STATE.with(|a| a.get()).unwrap_or_else(|| {
        let any = ctx.db.copy_state().count() > 0;
        ANY_STATE.with(|a| a.set(Some(any)));
        any
    });
    if !any {
        return CopyState { viewer: who, ..Default::default() };
    }
    ctx.db.copy_state().viewer().find(who).unwrap_or(CopyState { viewer: who, ..Default::default() })
}

/// Write where viewer `who`'s copies stand (a row only while either is set).
pub fn set_copy_state(ctx: &ReducerContext, s: CopyState) {
    ANY_STATE.with(|a| a.set(Some(true)));
    let had = ctx.db.copy_state().viewer().find(s.viewer).is_some();
    match (had, s.public || s.mirrored || s.fighters) {
        (true, true) => {
            ctx.db.copy_state().viewer().update(s);
        }
        (true, false) => {
            ctx.db.copy_state().viewer().delete(s.viewer);
        }
        (false, true) => {
            ctx.db.copy_state().insert(s);
        }
        (false, false) => {}
    }
}

/// Whether viewer `who`'s motion copies are in `seen_body_copy`.
fn public_of(ctx: &ReducerContext, who: Identity) -> bool {
    copy_state(ctx, who).public
}

/// A creature came into viewer `id`'s sight: its motion copy as it is now, in the far tier (the
/// frames' scene moves it to the near tier when it is near), in the table that holds the
/// viewer's copies.
pub fn new_motion(ctx: &ReducerContext, id: u32, who: Identity, b: &Body) {
    let k = key(id, b.id);
    if public_of(ctx, who) {
        drop_public(ctx, who, b.id);
        ctx.db.seen_body_copy().insert(SeenBodyCopy { viewer: who, body: b.id, near: false, seg: Segment::of(&Moving::from(b)) });
        return;
    }
    let row = MotionSeen::of(k, who, b);
    ctx.db.motion_near().id().delete(row.id);
    if ctx.db.motion_seen().id().find(row.id).is_some() {
        ctx.db.motion_seen().id().update(row);
    } else {
        ctx.db.motion_seen().insert(row);
    }
}

/// Whether the tick moves every public motion copy back (the kill switch): the law is off and
/// the last tick did not already see it off in this instance (it was on, or this instance, or a
/// step it did not see commit, does not know where the copies are).
fn all_back(was: Option<bool>, now: bool) -> bool {
    !now && was != Some(false)
}

/// Move a viewer's motion copies from the private tables to `seen_body_copy`, tiers kept, in
/// this transaction (its views read the private tables before it and the public one after).
fn to_public(ctx: &ReducerContext, who: Identity) -> usize {
    let far: Vec<MotionSeen> = ctx.db.motion_seen().viewer().filter(who).collect();
    let near: Vec<MotionNear> = ctx.db.motion_near().viewer().filter(who).collect();
    let n = far.len() + near.len();
    // A row already there (module memory that missed a rollback) is replaced, not a duplicate
    // key that would fail every tick from here on.
    for r in far {
        ctx.db.motion_seen().id().delete(r.id);
        let m = r.moving();
        drop_public(ctx, who, m.id);
        ctx.db.seen_body_copy().insert(SeenBodyCopy { viewer: who, body: m.id, near: false, seg: Segment::of(&m) });
    }
    for r in near {
        ctx.db.motion_near().id().delete(r.id);
        let m = r.copy.moving();
        drop_public(ctx, who, m.id);
        ctx.db.seen_body_copy().insert(SeenBodyCopy { viewer: who, body: m.id, near: true, seg: Segment::of(&m) });
    }
    set_copy_state(ctx, CopyState { public: true, ..copy_state(ctx, who) });
    n
}

/// The kill switch of the `motion_tables_on` law: every public motion copy goes back to the
/// private tables in this one transaction, so nothing reaches a client through the table once
/// the law is off. Returns how many moved.
fn all_private(ctx: &ReducerContext) -> usize {
    let rows: Vec<SeenBodyCopy> = ctx.db.seen_body_copy().iter().collect();
    // The private copies are keyed by the viewer's character (`key`): its `player` row.
    let mut chars: HashMap<Identity, Option<u32>> = HashMap::new();
    for r in &rows {
        ctx.db.seen_body_copy().delete(r.clone());
        let Some(viewer) = *chars.entry(r.viewer).or_insert_with(|| ctx.db.player().identity().find(r.viewer).map(|p| p.character)) else { continue };
        let k = key(viewer, r.body);
        // As in `to_public`: a private row already there is replaced.
        ctx.db.motion_seen().id().delete(k);
        ctx.db.motion_near().id().delete(k);
        let copy = MotionSeen::with(k, r.viewer, &r.seg.moving(r.body));
        if r.near {
            ctx.db.motion_near().insert(MotionNear { id: k, viewer: r.viewer, copy });
        } else {
            ctx.db.motion_seen().insert(copy);
        }
    }
    for s in ctx.db.copy_state().iter().filter(|s| s.public).collect::<Vec<_>>() {
        set_copy_state(ctx, CopyState { public: false, ..s });
    }
    rows.len()
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
// Row-level security for the public motion copies (battle-views): a client reads only its own.
#[spacetimedb::client_visibility_filter]
const SEEN_BODY_COPY_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM seen_body_copy WHERE viewer = :sender");
// Row-level security for the mirror of a player's projections (battle-views addendum 2).
#[spacetimedb::client_visibility_filter]
const SEEN_CHARACTER_COPY_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM seen_character_copy WHERE viewer = :sender");
// Row-level security for the public fighter copies (views step 3, `fighter_tables_on`).
#[spacetimedb::client_visibility_filter]
const SEEN_FIGHTER_COPY_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM seen_fighter_copy WHERE viewer = :sender");
// Row-level security for a player's combat feed as events (views step 2, `combat_feed_on`).
#[spacetimedb::client_visibility_filter]
const COMBAT_FEED_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM combat_feed WHERE viewer = :sender");
// Row-level security for a player's copies of its lines (experience-incremental, `lines_table_on`).
#[spacetimedb::client_visibility_filter]
const EXPERIENCE_COPY_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM experience_copy WHERE viewer = :sender");
// Row-level security for a player's throng cells (heed for players, `heed_players`).
#[spacetimedb::client_visibility_filter]
const SEEN_THRONG_FILTER: spacetimedb::Filter = spacetimedb::Filter::Sql("SELECT * FROM seen_throng WHERE viewer = :sender");

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
        crate::perception::proj_update(ctx, q);
    }
}

/// Release a character's staged experience lines and keep the newest [`LINES_SHOWN`]; with the
/// `lines_table_on` law, the copies of the viewer whose copies hold this character follow.
fn release_lines(ctx: &ReducerContext, id: u32) {
    let staged: Vec<LineSeen> = ctx.db.line_seen().by_observer_shown().filter((id, false)).collect();
    if staged.is_empty() {
        return;
    }
    let copies: Vec<Identity> = ctx.db.lines_state().character().filter(id).map(|s| s.viewer).collect();
    for mut l in staged {
        l.shown = true;
        for who in &copies {
            line_copy_put(ctx, *who, &l.line);
        }
        ctx.db.line_seen().id().update(l);
    }
    let mut shown: Vec<u64> = ctx.db.line_seen().by_observer_shown().filter((id, true)).map(|l| l.id).collect();
    if shown.len() > LINES_SHOWN {
        shown.sort_unstable();
        for old in &shown[..shown.len() - LINES_SHOWN] {
            ctx.db.line_seen().id().delete(*old);
            ctx.db.experience_copy().id().delete(*old);
            crate::outcomes::dropped(ctx, *old);
        }
    }
}

/// The lines staged and shown for character `id`, gone when its person plays another
/// (`perception::set_player`, beside `outcomes::forget`). Its `experience` rows went at its death
/// (`act::forget_dead`), and these copies were kept only for `my_experience` while no other
/// character of that person lives (the death screen). So `line_seen` holds at most
/// [`LINES_SHOWN`] rows per person, not per character ever played (growth-fix, 2026-11-23).
pub fn forget_lines(ctx: &ReducerContext, id: u32) {
    for shown in [false, true] {
        for l in ctx.db.line_seen().by_observer_shown().filter((id, shown)).map(|l| l.id).collect::<Vec<_>>() {
            ctx.db.line_seen().id().delete(l);
        }
    }
}

/// A copy of a shown line for viewer `who` (a row already there, module memory that missed a
/// rollback, is replaced, not a duplicate key).
fn line_copy_put(ctx: &ReducerContext, who: Identity, line: &Experience) {
    ctx.db.experience_copy().id().delete(line.id);
    ctx.db.experience_copy().insert(ExperienceCopy { id: line.id, viewer: who, row: line.clone() });
}

/// Make viewer `who`'s `experience_copy` rows whole for `character` (the one `my_experience` shows
/// it now; `None`: no lines, a character the minds hold), in this transaction, and record it
/// (`lines_state`). Only while the `lines_table_on` law is on; returns the rows written.
pub fn lines_resync(ctx: &ReducerContext, who: Identity, character: Option<u32>) -> usize {
    if !common::laws(ctx).lines_table_on {
        return 0;
    }
    for r in ctx.db.experience_copy().viewer().filter(who).collect::<Vec<_>>() {
        ctx.db.experience_copy().id().delete(r.id);
    }
    let rows: Vec<LineSeen> = character.map(|c| ctx.db.line_seen().by_observer_shown().filter((c, true)).collect()).unwrap_or_default();
    for l in &rows {
        line_copy_put(ctx, who, &l.line);
    }
    let state = LinesState { viewer: who, character: character.unwrap_or(0) };
    if ctx.db.lines_state().viewer().find(who).is_some() {
        ctx.db.lines_state().viewer().update(state);
    } else {
        ctx.db.lines_state().insert(state);
    }
    rows.len()
}

/// The kill switch of the `lines_table_on` law: every line copy and every viewer's record go in
/// this transaction.
fn drop_line_copies(ctx: &ReducerContext) -> usize {
    let ids: Vec<u64> = ctx.db.experience_copy().iter().map(|r| r.id).collect();
    for id in &ids {
        ctx.db.experience_copy().id().delete(*id);
    }
    for s in ctx.db.lines_state().iter().map(|s| s.viewer).collect::<Vec<_>>() {
        ctx.db.lines_state().viewer().delete(s);
    }
    ids.len()
}

/// The `lines_table_check` law (a diagnostic, off in play): every viewer whose copies are whole
/// holds exactly the rows `my_experience` returns it (`perception::current_of`, its shown lines).
/// A difference counts `lines_table:differed` and is logged; the viewers compared count
/// `lines_table:checked`.
fn check_line_copies(ctx: &ReducerContext) {
    let (mut checked, mut differed) = (0u64, 0u64);
    for s in ctx.db.lines_state().iter().collect::<Vec<_>>() {
        let want: Vec<Experience> = crate::perception::current_of(ctx, s.viewer)
            .map(|c| ctx.db.line_seen().by_observer_shown().filter((c.id, true)).map(|l| l.line).collect())
            .unwrap_or_default();
        let mut want: Vec<(u64, Experience)> = want.into_iter().map(|e| (e.id, e)).collect();
        let mut have: Vec<(u64, Experience)> = ctx.db.experience_copy().viewer().filter(s.viewer).map(|r| (r.id, r.row)).collect();
        want.sort_by_key(|x| x.0);
        have.sort_by_key(|x| x.0);
        checked += 1;
        common::diag(|| "lines_table:checked", 1);
        if want != have {
            differed += 1;
            common::diag(|| "lines_table:differed", 1);
            log::error!("lines table: {}'s copies ({} rows) differ from my_experience ({} rows)", s.viewer, have.len(), want.len());
        }
    }
    // A running total, logged every 600 ticks (readable without profiling).
    LINES_CHECKED.with(|c| {
        let (n, d, t) = c.get();
        let (n, d, t) = (n + checked, d + differed, t + 1);
        if t >= 600 {
            log::info!("lines table check: {n} viewer-ticks compared, {d} differed (600 ticks)");
            c.set((0, 0, 0));
        } else {
            c.set((n, d, t));
        }
    });
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
    fn both_delivery_laws_off_take_main_s_path() {
        // Off (DELIVERY false, as `deliver` sets it with both laws off): marks leave no cue owed
        // and no target to read, and no near tier is worked out.
        DELIVERY.with(|d| d.set(false));
        PENDING.with(|p| p.borrow_mut().clear());
        TARGET_DIRTY.with(|t| t.borrow_mut().clear());
        moved(7);
        fought(7);
        hurt(7);
        did(7);
        assert!(PENDING.with(|p| p.borrow().is_empty()), "a cue was owed with both laws off");
        assert!(TARGET_DIRTY.with(|t| t.borrow().is_empty()), "a target was marked with both laws off");
        assert!(MOVED.with(|m| m.borrow().contains_key(&7)), "the frames' own marks are kept, as on main");
        let seen: HashSet<u32> = (1..=40).collect();
        let dist: HashMap<u32, f32> = (1..=40).map(|b| (b, b as f32 * 0.2)).collect();
        let engaged: HashSet<u32> = [3].into_iter().collect();
        assert!(near_set(false, &engaged, &seen, &dist, &HashSet::new()).is_empty());
        // On: the same marks owe cues and mark targets; the near tier is engaged first, then the
        // nearest up to the cap.
        DELIVERY.with(|d| d.set(true));
        moved(8);
        did(8);
        assert_eq!(PENDING.with(|p| p.borrow().get(&8).copied()), Some(MOTION | DOING));
        assert!(TARGET_DIRTY.with(|t| t.borrow().contains(&8)));
        let near = near_set(true, &engaged, &seen, &dist, &HashSet::new());
        assert_eq!(near.len(), NEAR_MAX);
        assert!(near.contains(&3));
    }

    #[test]
    fn motion_tables_off_moves_every_copy_back_once_and_off_stays_main_s_path() {
        // battle-views' kill switch: the first tick to see `motion_tables_on` off moves every
        // public copy back, whether it was on or this instance does not know (fresh, or after a
        // step it did not see commit); ticks after that do nothing more, so a world that never
        // had it on pays one empty table walk per instance.
        assert!(all_back(None, false));
        assert!(all_back(Some(true), false));
        assert!(!all_back(Some(false), false));
        assert!(!all_back(None, true) && !all_back(Some(true), true) && !all_back(Some(false), true));
        // all_full (after a step this instance did not see commit) forgets the laws' last values,
        // so the next tick applies a switch whatever this instance thought. Where each viewer's
        // copies stand is not module memory but `copy_state` rows, rolled back with their moves.
        MOTION_TABLES.with(|m| m.set(Some(false)));
        CHAR_TABLES.with(|m| m.set(Some(false)));
        FIGHTER_TABLES.with(|m| m.set(Some(false)));
        LINES_TABLE.with(|m| m.set(Some(false)));
        all_full();
        assert_eq!(MOTION_TABLES.with(|m| m.get()), None);
        assert_eq!(CHAR_TABLES.with(|m| m.get()), None);
        assert_eq!(FIGHTER_TABLES.with(|m| m.get()), None);
        assert_eq!(LINES_TABLE.with(|m| m.get()), None);
        // A copy moved either way holds the same row the motion views return.
        let m = Moving { id: 5, x: 1.5, y: -2.0, t_ms: 77, vx: 0.5, vy: 0.25, heading: 1.0, turn: 0.1, turn_s: 0.3, next_ms: 99, speed: 1.2, face_off: 0.2, face_turn: -0.1, face_turn_s: 0.4, running: true };
        let private = MotionSeen::with(key(3, 5), Identity::ZERO, &m);
        assert_eq!(private.moving(), m);
        let public = SeenBodyCopy { viewer: private.viewer, body: 5, near: true, seg: Segment::of(&private.moving()) };
        assert_eq!(public.seg.moving(public.body), m);
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
