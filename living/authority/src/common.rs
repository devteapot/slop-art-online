//! Shared authority helpers: caches, time, positions, needs, inventory, spatial queries.

use crate::tables::*;
use living_rules::graph::Node;
use living_rules::map::{chunks_around, Map};
use living_rules::script::Scripts;
use spacetimedb::{ReducerContext, Table};
use std::cell::RefCell;
use std::collections::{HashMap, HashSet};
use std::rc::Rc;

thread_local! {
    static MAP: RefCell<Option<Rc<Map>>> = const { RefCell::new(None) };
    static SCRIPTS: RefCell<Option<(u32, Rc<Scripts>)>> = const { RefCell::new(None) };
    static GRAPHS: RefCell<HashMap<u32, (u32, Rc<Compiled>)>> = RefCell::new(HashMap::new());
    /// Genes never change after birth.
    static GENES: RefCell<HashMap<u32, Rc<living_rules::genes::Genes>>> = RefCell::new(HashMap::new());
}

/// Drop a dead character's cached genes and compiled graph.
pub fn forget_cached(id: u32) {
    GENES.with(|c| c.borrow_mut().remove(&id));
    GRAPHS.with(|g| g.borrow_mut().remove(&id));
}

/// A character's genes (cached; empty, i.e. all ordinary, when it has none).
pub fn genes_of(ctx: &ReducerContext, id: u32) -> Rc<living_rules::genes::Genes> {
    if let Some(g) = GENES.with(|c| c.borrow().get(&id).cloned()) {
        return g;
    }
    let Some(row) = ctx.db.genome().id().find(id) else { return Rc::new(Default::default()) };
    let g: Rc<living_rules::genes::Genes> = Rc::new(serde_json::from_str(&row.genes).unwrap_or_default());
    GENES.with(|c| c.borrow_mut().insert(id, g.clone()));
    g
}

/// Uses per skill.
pub fn practice_of(ctx: &ReducerContext, id: u32) -> std::collections::BTreeMap<String, u32> {
    ctx.db.practice().actor().filter(id).map(|p| (p.skill, p.uses)).collect()
}

/// One more successful use of a skill.
pub fn practise(ctx: &ReducerContext, id: u32, skill: &str) {
    if !living_rules::genes::is_skilled(skill) {
        return;
    }
    match ctx.db.practice().by_actor_skill().filter((id, skill)).next() {
        Some(mut p) => {
            p.uses += 1;
            ctx.db.practice().id().update(p);
        }
        None => {
            ctx.db.practice().insert(Practice { id: 0, actor: id, skill: skill.into(), uses: 1 });
        }
    }
}

thread_local! {
    /// Benchmark profiling (the clock's `profile` flag, read at the start of each scheduled reducer).
    static PROFILE: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

pub fn set_profiling(on: bool) {
    PROFILE.with(|p| p.set(on));
}

thread_local! {
    /// While profiling: graph scenes built since the last report, the creatures they saw in
    /// all, and the most one saw.
    static SCENES: std::cell::Cell<(u64, u64, u64)> = const { std::cell::Cell::new((0, 0, 0)) };
}

/// While profiling: a behaviour graph's scene saw `n` creatures (`tools/bench.py` reports the
/// mean per scene).
pub fn note_scene(n: usize) {
    if PROFILE.with(|p| p.get()) {
        SCENES.with(|s| {
            let (b, t, m) = s.get();
            s.set((b + 1, t + n as u64, m.max(n as u64)));
        });
    }
}

thread_local! {
    /// Diagnostic counts while profiling (docs/BATTLE_SCALE.md): percepts by kind and how many
    /// woke their observer, onlookers per witnessed event, requests to think by reason, graph
    /// evaluations by trigger, wakes. Logged once a second by `report_diag`, then cleared.
    static DIAG: RefCell<std::collections::BTreeMap<String, u64>> = const { RefCell::new(std::collections::BTreeMap::new()) };
}

/// Count `n` under the key `key()` while profiling (no work otherwise).
pub fn diag(key: impl FnOnce() -> String, n: u64) {
    if PROFILE.with(|p| p.get()) {
        DIAG.with(|d| *d.borrow_mut().entry(key()).or_default() += n);
    }
}

/// One line a second while profiling: the counts since the last report.
pub fn report_diag() {
    if PROFILE.with(|p| p.get()) {
        let m = DIAG.with(|d| std::mem::take(&mut *d.borrow_mut()));
        if !m.is_empty() {
            log::info!("diag: {}", serde_json::to_string(&m).unwrap_or_default());
        }
    }
}

/// While profiling, once a second: what graph scenes saw since the last report, one log line.
pub fn report_scenes() {
    if PROFILE.with(|p| p.get()) {
        let (b, t, m) = SCENES.with(|s| s.replace((0, 0, 0)));
        log::info!("scene seen: builds={b} seen={t} max={m}");
    }
}

/// A named timing span logged by the host while profiling is on (see `tools/bench.py`).
/// Whether spans are being logged (a profiling window is open).
pub fn profiling() -> bool {
    PROFILE.with(|p| p.get())
}

pub fn span(name: &str) -> Option<spacetimedb::log_stopwatch::LogStopwatch> {
    PROFILE.with(|p| p.get()).then(|| spacetimedb::log_stopwatch::LogStopwatch::new(name))
}

// ---- a module updated under a running instance (docs/LOOK.md §7, "The update panic") ------

thread_local! {
    /// A fingerprint of the database's list of tables (`st_table`) as this instance first saw it,
    /// at its first scheduled call (0: not yet), and whether it has said it was replaced.
    static SCHEMA: std::cell::Cell<(u64, bool)> = const { std::cell::Cell::new((0, false)) };
}

/// Whether the database's tables have changed under this module instance since its first
/// scheduled call: a module update with a schema change was published while this instance (the
/// old module's) still runs. SpacetimeDB 2.14.1 lets the outgoing module fire one more scheduled
/// reducer after the update has committed, and the bindings keep each table's and index's id in
/// a `static` resolved once per instance, so a table the update rewrote (a column appended: a new
/// table id and new index ids) makes that call's first lookup panic with "No such index". A
/// scheduled reducer that sees this returns at once, touching no table; the new module's own
/// instances (whose first call takes the fingerprint afresh) carry on. One scan of `st_table`
/// (about 150 short rows) through the host's uncached calls.
pub fn schema_moved(reducer: &str) -> bool {
    let Ok(st_table) = spacetimedb::sys::table_id_from_name("st_table") else { return false };
    let Ok(mut rows) = spacetimedb::sys::datastore_table_scan_bsatn(st_table) else { return false };
    let mut buf = Vec::with_capacity(16 * 1024);
    while !rows.is_exhausted() {
        rows.read(&mut buf);
    }
    // FNV-1a over the rows' bytes (never 0, so 0 means "not yet taken").
    let h = buf.iter().fold(0xcbf2_9ce4_8422_2325u64, |h, b| (h ^ *b as u64).wrapping_mul(0x0100_0000_01b3)) | 1;
    SCHEMA.with(|s| {
        let (seen, told) = s.get();
        if seen == 0 {
            s.set((h, false));
            return false;
        }
        if seen == h {
            return false;
        }
        if !told {
            log::warn!("{reducer}: the database's tables changed under this module instance (a module update was published); this call does nothing, and the new module carries on");
            s.set((seen, true));
        }
        true
    })
}

thread_local! {
    /// The transaction whose `now` was last asked for: its stamp, its `now`, a sequence number
    /// unique to it (the key of caches valid within one transaction), and the latest `now` any
    /// transaction has used.
    static TX: std::cell::Cell<(i64, u64, u64, u64)> = const { std::cell::Cell::new((0, 0, 0, 0)) };
}

/// The transaction's time in ms, never earlier than a time an earlier transaction already used.
///
/// A client's reducer is stamped when the host receives it, before the database's queue
/// (2.14.1 `module_host.rs` `call_reducer_params`), so a call that waited behind a tick runs
/// with a time older than the tick's. Its writes would then begin in the past: `motion::anchor`
/// restamps a body's segment earlier than where the tick left it (the body jumps ahead by its
/// speed times the wait), and readiness and the input bucket are judged at a time already
/// passed. The world has moved on to the tick's time, so a late call acts at that time.
pub fn now_ms(ctx: &ReducerContext) -> u64 {
    let received = (ctx.timestamp.to_micros_since_unix_epoch() / 1000) as u64;
    let st = stamp(ctx);
    TX.with(|t| {
        let (s, now, seq, latest) = t.get();
        if s == st {
            return now;
        }
        let now = received.max(latest);
        t.set((st, now, seq + 1, now));
        now
    })
}

/// A number unique to the current transaction (after its first `now_ms`): the key of module
/// caches valid within one transaction, which `now` alone no longer distinguishes.
pub fn tx_seq() -> u64 {
    TX.with(|t| t.get().2)
}

/// The transaction's timestamp in microseconds: the key of caches that are valid only
/// within one reducer call (a later call, or one rolled back, has another timestamp).
pub(crate) fn stamp(ctx: &ReducerContext) -> i64 {
    ctx.timestamp.to_micros_since_unix_epoch()
}

thread_local! {
    /// The world row, read once per transaction (it changes only through admin reducers,
    /// which call `invalidate_world`).
    static WORLD: RefCell<Option<(i64, World)>> = const { RefCell::new(None) };
    /// The installed script revision, read once per transaction.
    static SCRIPTS_REV: std::cell::Cell<Option<(i64, u32)>> = const { std::cell::Cell::new(None) };
    /// Work counters for the `stats` row, added to the clock row once per tick instead of
    /// rewriting it for every evaluation and experience.
    static COUNTS: std::cell::Cell<Counts> = const { std::cell::Cell::new(Counts::ZERO) };
}

pub fn world(ctx: &ReducerContext) -> World {
    let t = stamp(ctx);
    if let Some(w) = WORLD.with(|c| c.borrow().as_ref().filter(|(s, _)| *s == t).map(|(_, w)| w.clone())) {
        return w;
    }
    let w = ctx.db.world().id().find(0).expect("world initialized");
    WORLD.with(|c| *c.borrow_mut() = Some((t, w.clone())));
    // A floor module's seed lives in a row; this instance takes it before anything reads it.
    crate::seed::load(ctx);
    w
}

/// Call after writing the world row.
pub fn invalidate_world() {
    WORLD.with(|c| *c.borrow_mut() = None);
}

pub fn clock(ctx: &ReducerContext) -> Clock {
    ctx.db.clock().id().find(0).expect("clock initialized")
}

/// Revision of the installed skill script (cached for the transaction).
fn scripts_rev(ctx: &ReducerContext) -> u32 {
    let t = stamp(ctx);
    if let Some((_, rev)) = SCRIPTS_REV.with(|c| c.get()).filter(|(s, _)| *s == t) {
        return rev;
    }
    let rev = clock(ctx).scripts_rev;
    SCRIPTS_REV.with(|c| c.set(Some((t, rev))));
    rev
}

/// Call after writing the clock's `scripts_rev`.
pub fn invalidate_scripts_rev() {
    SCRIPTS_REV.with(|c| c.set(None));
}

#[derive(Clone, Copy, Default)]
pub struct Counts {
    pub evals: u64,
    pub motions: u64,
    pub completions: u64,
    pub percepts: u64,
    pub deliberations: u64,
    pub hits: u64,
    pub dodged: u64,
    pub blocked: u64,
    pub missed: u64,
}

impl Counts {
    const ZERO: Counts = Counts { evals: 0, motions: 0, completions: 0, percepts: 0, deliberations: 0, hits: 0, dodged: 0, blocked: 0, missed: 0 };
}

/// Count work for the stats row (flushed into the clock by `flush_counts`).
pub fn count(f: impl FnOnce(&mut Counts)) {
    COUNTS.with(|c| {
        let mut v = c.get();
        f(&mut v);
        c.set(v);
    });
}

/// Add pending counters to a clock row about to be written; false if there were none.
/// (Counts from a reducer call that later failed are kept: they are diagnostics.)
pub fn flush_counts(k: &mut Clock) -> bool {
    let c = COUNTS.with(|c| c.replace(Counts::ZERO));
    let any = c.evals | c.motions | c.completions | c.percepts | c.deliberations | c.hits | c.dodged | c.blocked | c.missed != 0;
    k.evals += c.evals;
    k.motions += c.motions;
    k.completions += c.completions;
    k.percepts += c.percepts;
    k.deliberations += c.deliberations;
    k.hits += c.hits;
    k.dodged += c.dodged;
    k.blocked += c.blocked;
    k.missed += c.missed;
    any
}

/// Who controls a seeded or newborn character that has no player: the admin's minds, which
/// deliberate and receive experiences. Every person has a mind; animals' are cheap (the mind
/// service's species routes) and asked only near people.
pub fn mind_controller(ctx: &ReducerContext) -> (spacetimedb::Identity, bool) {
    (world(ctx).admin, true)
}

/// Lives on its behaviour graph alone, with no mind to read its experiences: only the
/// benchmark crowds the admin spawns for load (`spawn_battle`, `spawn_skirmish`,
/// `spawn_crowd` with `minded` false). Seeded and newborn characters always have a mind.
pub fn instinct_only(ctx: &ReducerContext, c: &Character) -> bool {
    !c.ai && c.controller == ctx.database_identity()
}

thread_local! {
    /// Chunks whose tiles a transaction patched in the cached map, with its timestamp. A later
    /// transaction reloads just those rows (the patching one may have rolled back) instead of
    /// rebuilding the whole map: on a 2048 m world that is 16,384 rows and 4 MiB.
    static MAP_PATCHED: RefCell<(i64, Vec<u32>)> = const { RefCell::new((0, Vec::new())) };
    /// Timestamp of the last transaction that opened or shut a gate (0 = none pending).
    static GATES_CHANGED: std::cell::Cell<i64> = const { std::cell::Cell::new(0) };
}

/// Closed gates block like walls.
fn gate_blocks(ctx: &ReducerContext, w: u32, h: u32) -> std::collections::HashSet<u32> {
    ctx.db
        .gate()
        .iter()
        .filter(|g| !g.open && g.x >= 0 && g.y >= 0 && (g.x as u32) < w && (g.y as u32) < h)
        .map(|g| g.y as u32 * w + g.x as u32)
        .collect()
}

pub fn map(ctx: &ReducerContext) -> Rc<Map> {
    MAP.with(|m| {
        let t = stamp(ctx);
        let mut cached = m.borrow_mut();
        if let Some(map) = cached.as_mut() {
            // Revalidate what earlier transactions changed (committed or rolled back alike).
            let reload = MAP_PATCHED.with(|p| {
                let mut p = p.borrow_mut();
                if p.0 != 0 && p.0 != t {
                    p.0 = 0;
                    std::mem::take(&mut p.1)
                } else {
                    Vec::new()
                }
            });
            if !reload.is_empty() {
                let mm = Rc::make_mut(map);
                for id in reload {
                    if let Some(row) = ctx.db.terrain_chunk().id().find(id) {
                        mm.put_chunk(id, &row.tiles);
                    }
                }
            }
            let g = GATES_CHANGED.with(|g| g.get());
            if g != 0 {
                let mm = Rc::make_mut(map);
                let blocked = gate_blocks(ctx, mm.w, mm.h);
                mm.set_blocked(blocked);
                if g != t {
                    GATES_CHANGED.with(|c| c.set(0));
                }
            }
            return map.clone();
        }
        // The whole map, once per module instance (and after world creation): every chunk row.
        let _t = spacetimedb::log_stopwatch::LogStopwatch::new("map.rebuild");
        let w = world(ctx);
        let mut map = Map::from_chunks(w.width, w.height, ctx.db.terrain_chunk().iter().map(|c| (c.id, c.tiles)));
        map.set_blocked(gate_blocks(ctx, w.width, w.height));
        let map = Rc::new(map);
        *cached = Some(map.clone());
        map
    })
}

/// Drop the whole cached map (world creation; the next read rebuilds it from every chunk).
pub fn invalidate_map() {
    MAP.with(|m| *m.borrow_mut() = None);
    MAP_PATCHED.with(|p| *p.borrow_mut() = (0, Vec::new()));
    GATES_CHANGED.with(|g| g.set(0));
}

/// Call after a gate opens or shuts: the cached map re-reads the gate rows (a handful), not the
/// terrain.
pub fn invalidate_gates(ctx: &ReducerContext) {
    GATES_CHANGED.with(|g| g.set(stamp(ctx)));
}

/// Change one terrain tile (a road laid, a wall built) and persist its chunk row.
pub fn set_tile(ctx: &ReducerContext, x: i32, y: i32, t: living_rules::map::Terrain) -> Result<(), String> {
    // Revalidate earlier transactions' patches first, so only this one's stay pending.
    let _ = map(ctx);
    let w = world(ctx);
    if x < 0 || y < 0 || x as u32 >= w.width || y as u32 >= w.height {
        return Err("outside the world".into());
    }
    let chunk = living_rules::map::chunk_of(x as f32, y as f32);
    let mut row = ctx.db.terrain_chunk().id().find(chunk).ok_or("no terrain there")?;
    let (lx, ly) = (x as u32 % living_rules::map::CHUNK, y as u32 % living_rules::map::CHUNK);
    let i = (ly * living_rules::map::CHUNK + lx) as usize;
    if i >= row.tiles.len() {
        return Err("no terrain there".into());
    }
    row.tiles[i] = t as u8;
    ctx.db.terrain_chunk().id().update(row);
    // Patch the cached map in place and remember the chunk, so a later transaction re-reads
    // that one row if this one rolls back.
    let st = stamp(ctx);
    MAP.with(|m| {
        if let Some(map) = m.borrow_mut().as_mut() {
            Rc::make_mut(map).set(x, y, t);
        }
    });
    MAP_PATCHED.with(|p| {
        let mut p = p.borrow_mut();
        if !p.1.contains(&chunk) {
            p.1.push(chunk);
        }
        p.0 = st;
    });
    Ok(())
}

/// World laws from the installed scripts, with the world's own values over them (its seed's
/// `rules`, `world_law`). Cached with the scripts: writing a world law moves `scripts_rev`.
pub fn laws(ctx: &ReducerContext) -> living_rules::script::Laws {
    let rev = scripts_rev(ctx);
    if let Some(l) = LAWS.with(|l| l.get().filter(|(r, _)| *r == rev).map(|(_, l)| l)) {
        return l;
    }
    let over: Vec<(String, serde_json::Value)> = ctx.db.world_law().iter().filter_map(|w| serde_json::from_str(&w.value).ok().map(|v| (w.name, v))).collect();
    let sc = scripts(ctx);
    let l = sc.laws_with(&over).unwrap_or_else(|e| {
        log::warn!("world laws: {e}; the script's own values hold");
        sc.laws()
    });
    LAWS.with(|c| c.set(Some((rev, l))));
    l
}

thread_local! {
    static LAWS: std::cell::Cell<Option<(u32, living_rules::script::Laws)>> = const { std::cell::Cell::new(None) };
}

pub fn scripts(ctx: &ReducerContext) -> Rc<Scripts> {
    let rev = scripts_rev(ctx);
    SCRIPTS.with(|s| {
        if let Some((r, sc)) = s.borrow().as_ref() {
            if *r == rev {
                return sc.clone();
            }
        }
        let src = ctx.db.script().name().find("skills".to_string()).map(|s| s.source).unwrap_or_default();
        // Laws written per game hour run on this world's day (its seed's `day_minutes`).
        let mut sc = Scripts::with_day(&src, world(ctx).day_ms).expect("installed skills script compiles");
        crate::codes::apply(ctx, &mut sc);
        // Graph normalization and validation take the world's skills from its script.
        living_rules::catalog::set_skills(sc.skills().clone());
        let sc = Rc::new(sc);
        *s.borrow_mut() = Some((rev, sc.clone()));
        sc
    })
}

/// A validated graph with its routines inlined: preorder subtree sizes, and for each node
/// the routine it belongs to (for attributing outcomes).
pub struct Compiled {
    pub root: Node,
    pub sizes: Vec<u16>,
    pub routine_of: Vec<Option<u64>>,
}

fn sizes(root: &Node) -> Vec<u16> {
    fn go(n: &Node, out: &mut Vec<u16>) -> u16 {
        let me = out.len();
        out.push(1);
        let mut total = 1u16;
        match n {
            Node::First(c) | Node::Seq(c) => {
                for ch in &c.children {
                    total += go(ch, out);
                }
            }
            Node::If(i) => {
                total += go(&i.then, out);
                if let Some(e) = &i.otherwise {
                    total += go(e, out);
                }
            }
            Node::Desires(ds) => {
                for d in ds {
                    total += go(&d.body, out);
                }
            }
            _ => {}
        }
        out[me] = total;
        total
    }
    let mut out = Vec::new();
    go(root, &mut out);
    out
}

/// For each node in preorder, the routine whose inlined branch contains it.
fn owners(root: &Node, mine: &[Routine]) -> Vec<Option<u64>> {
    fn go(n: &Node, cur: Option<u64>, mine: &[Routine], out: &mut Vec<Option<u64>>) {
        let here = match n {
            Node::First(c) => c.label.as_deref().and_then(|l| l.strip_prefix("routine:")).and_then(|name| mine.iter().find(|r| same_routine(&r.name, name)).map(|r| r.id)).or(cur),
            _ => cur,
        };
        out.push(here);
        match n {
            Node::First(c) | Node::Seq(c) => c.children.iter().for_each(|ch| go(ch, here, mine, out)),
            Node::If(i) => {
                go(&i.then, here, mine, out);
                if let Some(e) = &i.otherwise {
                    go(e, here, mine, out);
                }
            }
            Node::Desires(ds) => ds.iter().for_each(|d| go(&d.body, here, mine, out)),
            _ => {}
        }
    }
    let mut out = Vec::new();
    go(root, None, mine, &mut out);
    out
}

pub fn compiled(ctx: &ReducerContext, id: u32, revision: u32) -> Option<Rc<Compiled>> {
    if let Some(c) = GRAPHS.with(|g| g.borrow().get(&id).filter(|(r, _)| *r == revision).map(|(_, c)| c.clone())) {
        return Some(c);
    }
    let brain = ctx.db.brain().id().find(id)?;
    let graph = living_rules::graph::parse(&brain.graph).ok()?;
    // Inline the character's routines (only when the graph calls any).
    let (root, routine_of) = if living_rules::graph::preorder(&graph.root).iter().any(|n| matches!(n, Node::Routine(_))) {
        let mine: Vec<Routine> = ctx.db.routine().actor().filter(id).collect();
        let lookup = |name: &str| mine.iter().find(|r| same_routine(&r.name, name)).and_then(|r| living_rules::graph::parse(&r.graph).ok()).map(|g| g.root);
        let expanded = living_rules::graph::expand(&graph.root, &lookup);
        let root = living_rules::graph::validate_compiled(expanded).map(|g| g.root).unwrap_or(graph.root);
        let owners = owners(&root, &mine);
        (root, owners)
    } else {
        let n = living_rules::graph::preorder(&graph.root).len();
        (graph.root, vec![None; n])
    };
    let c = Rc::new(Compiled { sizes: sizes(&root), root, routine_of });
    GRAPHS.with(|g| g.borrow_mut().insert(id, (brain.revision, c.clone())));
    if brain.revision == revision {
        Some(c)
    } else {
        None
    }
}

// ---- time ----------------------------------------------------------------------

pub fn hour(w: &World, now: u64) -> f32 {
    living_rules::hour_of(now, w.epoch_ms, w.day_ms)
}

/// Whether it is night now: the script's `daylight` law below one half (read per game minute
/// and kept for the script revision, so this costs a lookup).
pub fn night(ctx: &ReducerContext, w: &World, now: u64) -> bool {
    scripts(ctx).is_night(hour(w, now))
}

/// How dark it is now, 0 (day) to 1 (night), in the steps laws see (`SkillCtx::dark`).
pub fn dark(ctx: &ReducerContext, w: &World, now: u64) -> f32 {
    scripts(ctx).dark(hour(w, now))
}

/// Draws in [0, 1) that depend only on a character and a purpose (splitmix64), so drawing a
/// person's own differences (rhythm, constitution) leaves the world's random stream alone.
pub fn hashed_draws(id: u32, salt: u64) -> impl FnMut() -> f32 {
    let mut x = (id as u64) ^ salt.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    move || {
        x = x.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = x;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^= z >> 31;
        (z >> 40) as f32 / (1u64 << 24) as f32
    }
}

/// A rhythm row's hours (`living_rules::rhythm`).
pub fn hours_of(r: &Rhythm) -> living_rules::rhythm::Hours {
    living_rules::rhythm::Hours { rise_h: r.rise_h, bed_h: r.bed_h, evening_h: r.evening_h, work_from_h: r.work_from_h, work_to_h: r.work_to_h, nap_from_h: r.nap_from_h, nap_to_h: r.nap_to_h }
}

/// Where a body is in its own day at `hour`: its bedtime, its evening and its working hours. A
/// person's rhythm row says when it rises and goes to bed, how long its evening is, its working
/// hours and any second sleep (`living_rules::rhythm`); without one, bedtime is the world's
/// night, the evening 18:00 to 22:00 and working hours the rest of the day.
pub fn day_phase(ctx: &ReducerContext, id: u32, hour: f32) -> living_rules::rhythm::Phase {
    match ctx.db.rhythm().id().find(id) {
        Some(r) => hours_of(&r).phase(hour),
        None => {
            let (bedtime, evening) = (scripts(ctx).is_night(hour), (18.0..22.0).contains(&hour));
            living_rules::rhythm::Phase { bedtime, evening, work: !bedtime && !evening }
        }
    }
}

/// A species' life table as `species.json` gives it.
pub fn species_life(kind: &str) -> living_rules::life::Life {
    species(kind).map(|s| s.life).unwrap_or_default()
}

/// A species' life table (lifespan and stages) under the world's rules: its species data, as a
/// world's `life_years` law changes it (docs/CULLET_RULES.md); without the law, the data.
pub fn life_of(ctx: &ReducerContext, kind: &str) -> living_rules::life::Life {
    scripts(ctx).life(kind, species_life(kind))
}

/// The world's time for lives: days per year and pace.
pub fn pace(w: &World) -> living_rules::life::Pace {
    living_rules::life::Pace { year_days: w.year_days.max(1) as f32, pace: w.life_pace }
}

/// Life stage of a character now, at the world's pace.
pub fn stage_of(ctx: &ReducerContext, c: &Character, w: &World, now: u64) -> living_rules::life::Stage {
    life_of(ctx, &c.kind).stage(age_days(c, w, now), pace(w))
}

/// A life stage's name from its code (`stage_code`).
pub fn stage_name(code: u8) -> &'static str {
    match code {
        0 => "infant",
        1 => "child",
        3 => "elder",
        _ => "adult",
    }
}

pub fn stage_code(s: living_rules::life::Stage) -> u8 {
    match s {
        living_rules::life::Stage::Infant => 0,
        living_rules::life::Stage::Child => 1,
        living_rules::life::Stage::Adult => 2,
        living_rules::life::Stage::Elder => 3,
    }
}

pub fn age_days(c: &Character, w: &World, now: u64) -> f32 {
    c.birth_age_days + now.saturating_sub(c.born_ms) as f32 / w.day_ms.max(1) as f32
}

/// The farthest anyone sees now (the `senses` law's reach by day or by night): onlookers are
/// gathered within it before each one's own sight is tested.
pub fn widest_sight(ctx: &ReducerContext, w: &World, now: u64) -> f32 {
    scripts(ctx).reach().seen(dark(ctx, w, now))
}

/// The farthest anyone hears.
pub fn widest_hearing(ctx: &ReducerContext) -> f32 {
    scripts(ctx).reach().hearing
}

// ---- bodies ---------------------------------------------------------------------

/// Where a body is at `now`: along its segment (straight or an arc) until `next_ms`.
pub fn pos(b: &Body, now: u64) -> (f32, f32) {
    if b.vx == 0.0 && b.vy == 0.0 {
        return (b.x, b.y);
    }
    let t = now.min(b.next_ms).saturating_sub(b.t_ms) as f32 / 1000.0;
    if b.turn == 0.0 || b.turn_s <= 0.0 {
        return (b.x + b.vx * t, b.y + b.vy * t);
    }
    let (x, y, _) = living_rules::steer::pose(b.x, b.y, b.heading, (b.vx * b.vx + b.vy * b.vy).sqrt(), b.turn, b.turn_s, t);
    (x, y)
}

/// Which way a body travels at `now` (`body.heading` along its segment: a turn under way,
/// standing or walking; `steer::pose`): where its legs go. Steering, separation and the pose
/// read it. Where the body looks is [`facing_at`].
pub fn heading_at(b: &Body, now: u64) -> f32 {
    if b.turn == 0.0 || b.turn_s <= 0.0 {
        return b.heading;
    }
    let t = now.min(b.next_ms).saturating_sub(b.t_ms) as f32 / 1000.0;
    living_rules::steer::wrap(b.heading + b.turn * t.min(b.turn_s))
}

/// Which way a body faces at `now`: its travel heading plus its facing offset
/// (`body.face_*`, `steer::facing`), the one facing that facing sight (`fov_on`), what is heard
/// from which side, "you face", a guard's default and an aim at the facing read. A held look
/// (`human_face`) turns it; with none it is the heading. Clients evaluate it the same way.
pub fn facing_at(b: &Body, now: u64) -> f32 {
    let t = now.min(b.next_ms).saturating_sub(b.t_ms) as f32 / 1000.0;
    living_rules::steer::facing(heading_at(b, now), b.face_off, b.face_turn, b.face_turn_s, t)
}

pub fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}

pub fn direction(from: (f32, f32), to: (f32, f32)) -> &'static str {
    let dx = to.0 - from.0;
    let dy = to.1 - from.1;
    if dx.abs() < 0.5 && dy.abs() < 0.5 {
        return "here";
    }
    let a = dy.atan2(dx).to_degrees();
    // Screen coordinates: +y is south.
    match a {
        a if (-22.5..22.5).contains(&a) => "east",
        a if (22.5..67.5).contains(&a) => "southeast",
        a if (67.5..112.5).contains(&a) => "south",
        a if (112.5..157.5).contains(&a) => "southwest",
        a if (-67.5..-22.5).contains(&a) => "northeast",
        a if (-112.5..-67.5).contains(&a) => "north",
        a if (-157.5..-112.5).contains(&a) => "northwest",
        _ => "west",
    }
}

// ---- needs ---------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
pub struct Needs {
    pub hp: f32,
    pub hunger: f32,
    pub energy: f32,
}

pub fn needs(v: &Vitals, now: u64) -> Needs {
    let m = now.saturating_sub(v.at_ms) as f32 / 60_000.0;
    Needs {
        hp: (v.hp + v.hp_rate * m).clamp(0.0, v.max_hp),
        hunger: (v.hunger + v.hunger_rate * m).clamp(0.0, 100.0),
        energy: (v.energy + v.energy_rate * m).clamp(0.0, 100.0),
    }
}

/// Re-anchor needs and the short pools at `now` (breath a drain took since the last anchor
/// tires the body; `crate::breath::settle`).
pub fn settle(ctx: &ReducerContext, v: &mut Vitals, now: u64) {
    let n = needs(v, now);
    let p = pools_of(ctx, v.id, now);
    v.hp = n.hp;
    v.hunger = n.hunger;
    v.energy = crate::breath::settle(v, &p, n.energy, now);
    v.at_ms = now;
}

// ---- inventory ------------------------------------------------------------------

pub fn inv_list(ctx: &ReducerContext, owner: u64) -> Vec<(String, u32)> {
    let mut v: Vec<(String, u32)> = ctx.db.inventory().owner().filter(owner).filter(|r| r.qty > 0).map(|r| (r.item, r.qty)).collect();
    v.sort();
    v
}

pub fn inv_count(ctx: &ReducerContext, owner: u64, item: &str) -> u32 {
    ctx.db.inventory().by_owner_item().filter((owner, item)).map(|r| r.qty).sum()
}

pub fn inv_add(ctx: &ReducerContext, owner: u64, item: &str, qty: u32) {
    if qty == 0 {
        return;
    }
    if let Some(mut r) = ctx.db.inventory().by_owner_item().filter((owner, item)).next() {
        r.qty += qty;
        ctx.db.inventory().id().update(r);
    } else {
        ctx.db.inventory().insert(Inventory { id: 0, owner, item: item.to_string(), qty });
    }
}

pub fn inv_remove(ctx: &ReducerContext, owner: u64, item: &str, qty: u32) -> Result<(), String> {
    let Some(mut r) = ctx.db.inventory().by_owner_item().filter((owner, item)).next() else {
        return Err(format!("no {item}"));
    };
    if r.qty < qty {
        return Err(format!("only {} {item}", r.qty));
    }
    r.qty -= qty;
    if r.qty == 0 {
        ctx.db.inventory().id().delete(r.id);
    } else {
        ctx.db.inventory().id().update(r);
    }
    Ok(())
}

/// What an item feeds, by the rules' `nutrition(item)`: food is whatever has nutrition.
pub fn nutrition(sc: &living_rules::script::Scripts, item: &str) -> f64 {
    sc.num_of("nutrition", item, 0.0)
}

/// The most nourishing food held (cooked food feeds most in the rules), by name on a tie.
pub fn best_food(ctx: &ReducerContext, owner: u64) -> Option<String> {
    let sc = scripts(ctx);
    inv_list(ctx, owner)
        .into_iter()
        .map(|(i, _)| (nutrition(&sc, &i), i))
        .filter(|(n, _)| *n > 0.0)
        .max_by(|a, b| a.0.total_cmp(&b.0).then_with(|| b.1.cmp(&a.1)))
        .map(|(_, i)| i)
}

pub fn food_count(ctx: &ReducerContext, owner: u64) -> u32 {
    let sc = scripts(ctx);
    inv_list(ctx, owner).into_iter().filter(|(i, _)| nutrition(&sc, i) > 0.0).map(|(_, q)| q).sum()
}

// ---- resources ----------------------------------------------------------------

/// A chunk's pasture: grazing per grassy tile it holds (`pasture_per_tile`) and its regrowth per
/// minute of growing time (`pasture_regen`), both world laws.
fn pasture_row(ctx: &ReducerContext, chunk: u32, now: u64) -> Pasture {
    if let Some(p) = ctx.db.pasture().chunk().find(chunk) {
        return p;
    }
    let map = map(ctx);
    let (cx, cy) = living_rules::map::chunk_xy(chunk);
    let n = living_rules::map::CHUNK as i32;
    let mut tiles = 0u32;
    for y in 0..n {
        for x in 0..n {
            if matches!(map.get(cx as i32 * n + x, cy as i32 * n + y), living_rules::map::Terrain::Grass | living_rules::map::Terrain::Forest) {
                tiles += 1;
            }
        }
    }
    let max = tiles as f32 * laws(ctx).pasture_per_tile;
    Pasture { chunk, amount: max, max, regen: tiles as f32 * laws(ctx).pasture_regen, at_ms: now }
}

/// Grazing left in a chunk now.
pub fn pasture_now(ctx: &ReducerContext, chunk: u32, now: u64) -> f32 {
    let p = pasture_row(ctx, chunk, now);
    let (epoch, day, year) = calendar(ctx);
    // Regrowth follows the current rules (the row keeps the chunk's grassy tiles as its max).
    let regen = p.max / laws(ctx).pasture_per_tile.max(1e-6) * laws(ctx).pasture_regen;
    (p.amount + regen * living_rules::growing_ms(p.at_ms, now, epoch, day, year) as f32 / 60_000.0).min(p.max)
}

/// One grazing eaten from a chunk.
pub fn graze_pasture(ctx: &ReducerContext, chunk: u32, now: u64) {
    let amount = (pasture_now(ctx, chunk, now) - 1.0).max(0.0);
    let mut p = pasture_row(ctx, chunk, now);
    p.amount = amount;
    p.at_ms = now;
    if ctx.db.pasture().chunk().find(chunk).is_some() {
        ctx.db.pasture().chunk().update(p);
    } else {
        ctx.db.pasture().insert(p);
    }
}

/// The node whose stock a resource node draws on: its pool's (a fishing ground's spots share
/// one limit), or itself.
pub fn stock_of(ctx: &ReducerContext, r: &ResourceNode) -> ResourceNode {
    if r.pool == 0 || r.pool == r.id {
        return r.clone();
    }
    ctx.db.resource_node().id().find(r.pool).unwrap_or_else(|| r.clone())
}

/// A node's amount now: what it held at `at_ms` and its regrowth since, at its kind's share of
/// the rate in each season (`regrow_by_season`; none: full, and none in winter, as before).
pub fn amount_now(ctx: &ReducerContext, r: &ResourceNode, now: u64) -> f32 {
    let (epoch, day, year) = calendar(ctx);
    let by = scripts(ctx).regrow_seasons(&r.kind);
    (r.amount + r.regen * living_rules::regrowth_ms(r.at_ms, now, epoch, day, year, &by) / 60_000.0).min(r.max)
}

thread_local! {
    static CALENDAR: std::cell::Cell<Option<(u64, u64, u64)>> = const { std::cell::Cell::new(None) };
}

/// The world's epoch, day length and days per year (cached; cleared when the world row changes).
pub fn calendar(ctx: &ReducerContext) -> (u64, u64, u64) {
    CALENDAR.with(|c| {
        if let Some(v) = c.get() {
            return v;
        }
        let w = world(ctx);
        let v = (w.epoch_ms, w.day_ms, w.year_days.max(4) as u64);
        c.set(Some(v));
        v
    })
}

pub fn epoch_day(ctx: &ReducerContext) -> (u64, u64) {
    let (e, d, _) = calendar(ctx);
    (e, d)
}

pub fn invalidate_calendar() {
    CALENDAR.with(|c| c.set(None));
}

pub fn season(ctx: &ReducerContext, now: u64) -> &'static str {
    let (epoch, day, year) = calendar(ctx);
    living_rules::SEASONS[living_rules::season_of(now, epoch, day, year)]
}

/// How far a creature sees now (the `senses` law: day, night, a torch, whatever the world's
/// rules say).
pub fn sight_for(ctx: &ReducerContext, id: u32, w: &World, now: u64) -> f32 {
    senses_of(ctx, id, w, now).sight
}

/// How far a creature hears now.
pub fn hearing_for(ctx: &ReducerContext, id: u32, w: &World, now: u64) -> f32 {
    senses_of(ctx, id, w, now).hearing
}

/// A creature's answers from the laws asked per creature on the hot path, for one moment.
#[derive(Clone, Copy, Default)]
struct Hot {
    senses: Option<living_rules::script::Senses>,
    moves: Option<living_rules::script::Moves>,
    pools: Option<living_rules::pools::Pools>,
    glow: Option<f32>,
}

thread_local! {
    /// The hot laws' answers by creature for one moment (`now`): every look and step in a tick
    /// asks the same few creatures again. Cleared when the moment or the script revision changes.
    static HOT: RefCell<(u64, u32, HashMap<u32, Hot>)> = RefCell::new((0, 0, HashMap::new()));
}

/// A hot law's answer for creature `id` now: kept for this moment here, else the law over the
/// few facts it reads (gathered by its plan), kept per state by the scripts.
fn hot<T: Copy>(ctx: &ReducerContext, id: u32, w: &World, now: u64, law: &str, slot: fn(&mut Hot) -> &mut Option<T>, ask: impl FnOnce(&Scripts, &living_rules::script::SkillCtx) -> T) -> T {
    let rev = scripts_rev(ctx);
    if let Some(v) = HOT.with(|c| {
        let mut c = c.borrow_mut();
        if c.0 != now || c.1 != rev {
            return None;
        }
        c.2.get_mut(&id).and_then(|h| *slot(h))
    }) {
        return v;
    }
    let sc = scripts(ctx);
    let c = crate::act::law_ctx(ctx, id, w, now, &sc.law_plan(law));
    let v = ask(&sc, &c);
    HOT.with(|c| {
        let mut c = c.borrow_mut();
        if c.0 != now || c.1 != rev {
            *c = (now, rev, HashMap::new());
        }
        *slot(c.2.entry(id).or_default()) = Some(v);
    });
    v
}

/// A creature's senses now (the `senses` law).
pub fn senses_of(ctx: &ReducerContext, id: u32, w: &World, now: u64) -> living_rules::script::Senses {
    hot(ctx, id, w, now, "senses", |h| &mut h.senses, |sc, c| {
        sc.senses(c).unwrap_or_else(|e| {
            log::warn!("senses for {id}: {e}");
            let r = sc.reach();
            living_rules::script::Senses { sight: r.sight(c.dark), hearing: r.hearing, field: None }
        })
    })
}

/// How far a creature is seen from now by a light on it (the `glow` law: a carried light, standing
/// in lamplight; 0 when the script has none, which costs nothing).
pub fn glow_of(ctx: &ReducerContext, id: u32, w: &World, now: u64) -> f32 {
    if scripts(ctx).reach().glow <= 0.0 {
        return 0.0;
    }
    hot(ctx, id, w, now, "glow", |h| &mut h.glow, |sc, c| {
        sc.glow(c).unwrap_or_else(|e| {
            log::warn!("glow for {id}: {e}");
            0.0
        })
    })
}

/// The radius to gather creatures an observer with sight `sight` may see: its sight, widened to
/// the farthest glow when the script has one.
pub fn gather_radius(ctx: &ReducerContext, sight: f32) -> f32 {
    sight.max(scripts(ctx).reach().glow)
}

/// Whether a spot is in lamplight: within the light of a structure that gives it (its kind's
/// `lights`, or a fire's `burns.light`). A kind that `burns` gives light only while it is lit
/// (`lit_until_ms` ahead of now): a lamp out of oil is dark. False at once when no kind gives
/// light.
pub fn lit_at(ctx: &ReducerContext, at: (f32, f32)) -> bool {
    let sc = scripts(ctx);
    let widest = sc.widest_light();
    if widest <= 0.0 {
        return false;
    }
    let now = now_ms(ctx);
    structures_near(ctx, at, widest).into_iter().any(|(s, d)| {
        let t = sc.structure(&s.kind);
        let l = t.light();
        l > 0.0 && d <= l && (t.burns.is_none() || living_rules::fire::lit(s.lit_until_ms, now))
    })
}

/// How a creature moves now (the `motion` law): its run, flight and step aside as shares of its
/// walk, its turning and how far it keeps from others.
pub fn moves_of(ctx: &ReducerContext, id: u32, now: u64) -> living_rules::script::Moves {
    let w = world(ctx);
    hot(ctx, id, &w, now, "motion", |h| &mut h.moves, |sc, c| {
        sc.moves(c).unwrap_or_else(|e| {
            log::warn!("motion for {id}: {e}");
            living_rules::script::Moves { run: 1.0, flee: 1.0, aside: 1.0, turn_rate: 6.0, turn_slow: 1.0, separation: 0.0, separation_weight: 0.0, wander_turn: 1.2, wander_keep_s: 0.0, top: f32::INFINITY, charge: false }
        })
    })
}

/// A creature's short pools (the `pools` law: breath and focus), kept per state.
pub fn pools_of(ctx: &ReducerContext, id: u32, now: u64) -> living_rules::pools::Pools {
    let w = world(ctx);
    hot(ctx, id, &w, now, "pools", |h| &mut h.pools, |sc, c| {
        sc.pools(c).unwrap_or_else(|e| {
            log::warn!("pools for {id}: {e}");
            living_rules::pools::Pools::default()
        })
    })
}

/// Techniques a character knows, by their current names (a row a world kept from before a
/// rename reads as the new name until an install renames it, `rename_techniques`).
pub fn knows(ctx: &ReducerContext, id: u32) -> Vec<String> {
    ctx.db.know_how().actor().filter(id).map(|k| living_rules::catalog::technique_name(&k.technique).to_string()).collect()
}

/// Learn a technique (by its current name); false if already known.
pub fn learn(ctx: &ReducerContext, id: u32, technique: &str, source: &str, now: u64) -> bool {
    let technique = living_rules::catalog::technique_name(technique);
    if ctx.db.know_how().by_actor_technique().filter((id, technique)).next().is_some() {
        return false;
    }
    ctx.db.know_how().insert(KnowHow { id: 0, actor: id, technique: technique.into(), source: source.into(), since_ms: now });
    crate::perception::answers_changed();
    true
}

// ---- spatial queries ------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct NearCreature {
    pub id: u32,
    pub kind: Rc<str>,
    pub pos: (f32, f32),
    pub dist: f32,
    /// Which way it faces at the instant (`facing_at`: where it looks, not where it goes).
    pub facing: f32,
}

/// A body in the per-tick chunk cache: id, kind, where it is and which way it faces then.
type CachedBody = (u32, Rc<str>, (f32, f32), f32);

thread_local! {
    /// Bodies per chunk at one instant, shared by every evaluation in the same tick.
    static CHUNK_BODIES: RefCell<((u64, u64), HashMap<u32, Rc<Vec<CachedBody>>>)> = RefCell::new(((0, 0), HashMap::new()));
}

thread_local! {
    /// Bodies written (`body_written`) since the chunk cache's instant began: their cached
    /// position may be older than their row, so [`cached_body_current`] says no for them.
    static WRITTEN: RefCell<HashSet<u32>> = RefCell::new(HashSet::new());
}

fn chunk_bodies(ctx: &ReducerContext, chunk: u32, now: u64) -> Rc<Vec<CachedBody>> {
    CHUNK_BODIES.with(|c| {
        let mut c = c.borrow_mut();
        let key = (tx_seq(), now);
        if c.0 != key {
            c.0 = key;
            c.1.clear();
            WRITTEN.with(|w| w.borrow_mut().clear());
        }
        if let Some(v) = c.1.get(&chunk) {
            return v.clone();
        }
        let v: Rc<Vec<_>> = Rc::new(ctx.db.body().chunk().filter(chunk).map(|b| (b.id, Rc::from(b.kind.as_str()), pos(&b, now), facing_at(&b, now))).collect());
        c.1.insert(chunk, v.clone());
        v
    })
}

/// Forget cached bodies (after a body is removed or moved to another chunk this instant).
pub fn invalidate_bodies() {
    CHUNK_BODIES.with(|c| c.borrow_mut().0 = (0, 0));
}

/// A body row was written: a position the chunk cache already holds for it may be older.
pub fn body_written(id: u32) {
    WRITTEN.with(|w| w.borrow_mut().insert(id));
}

/// Whether the position [`creatures_near`] gave for body `id` at `now` in this transaction is
/// exactly `pos(row, now)` of its row as it is now: true unless the row was written since the
/// cache's instant began (it then holds the same row it read).
pub fn cached_body_current(id: u32, now: u64) -> bool {
    CHUNK_BODIES.with(|c| c.borrow().0 == (tx_seq(), now)) && !WRITTEN.with(|w| w.borrow().contains(&id))
}

pub fn creatures_near(ctx: &ReducerContext, at: (f32, f32), r: f32, now: u64) -> Vec<NearCreature> {
    let mut out = Vec::new();
    for c in chunks_around(at.0, at.1, r) {
        for (id, kind, p, h) in chunk_bodies(ctx, c, now).iter() {
            let d = dist(at, *p);
            if d <= r {
                out.push(NearCreature { id: *id, kind: kind.clone(), pos: *p, dist: d, facing: *h });
            }
        }
    }
    out.sort_by(|a, b| a.dist.total_cmp(&b.dist));
    out
}

thread_local! {
    /// What each body last smelled: when, from where, at what sight, and every creature of its
    /// scent kinds within the radius then (with its position then).
    static SMELLED: RefCell<HashMap<u32, (u64, (f32, f32), f32, Rc<Vec<NearCreature>>)>> = RefCell::new(HashMap::new());
}

/// A body that has moved this far since its last read smells afresh.
const SCENT_MOVE: f32 = 4.0;

/// Creatures body `who` of species `kind` smells beyond `sight` (within its scent radius, of
/// its scent kinds), nearest first; empty for a body without a scent. A fresh read sweeps the
/// per-tick chunk cache over every chunk within the radius (19x19 chunks at 150 tiles), so a
/// body reads afresh at most `scent_hz` times a second, or when it has moved `SCENT_MOVE`
/// tiles; in between, distances are taken from where it is now to where the creatures were.
pub fn smelled_near(ctx: &ReducerContext, who: u32, kind: &str, at: (f32, f32), sight: f32, now: u64) -> Vec<NearCreature> {
    let Some(scent) = scent_of(kind).filter(|s| s.radius > sight) else { return Vec::new() };
    let _t = span("scent.query");
    let every_ms = (1000.0 / laws(ctx).scent_hz) as u64;
    let kept = SMELLED.with(|m| {
        m.borrow().get(&who).filter(|(t, from, s, _)| now >= *t && now - *t < every_ms && dist(*from, at) < SCENT_MOVE && *s == sight).map(|e| e.3.clone())
    });
    let all = kept.unwrap_or_else(|| {
        let _t = span("scent.read");
        let mut all = Vec::new();
        for c in chunks_around(at.0, at.1, scent.radius) {
            for (id, k, p, h) in chunk_bodies(ctx, c, now).iter() {
                if *id != who && scent.kinds.iter().any(|x| **x == **k) && dist(at, *p) <= scent.radius + SCENT_MOVE {
                    all.push(NearCreature { id: *id, kind: k.clone(), pos: *p, dist: 0.0, facing: *h });
                }
            }
        }
        let all = Rc::new(all);
        SMELLED.with(|m| {
            let mut m = m.borrow_mut();
            if m.len() > 4096 {
                m.retain(|_, e| now.saturating_sub(e.0) < 10_000);
            }
            m.insert(who, (now, at, sight, all.clone()));
        });
        all
    });
    let mut out: Vec<NearCreature> = all
        .iter()
        .filter_map(|c| {
            let d = dist(at, c.pos);
            (d > sight && d <= scent.radius).then(|| NearCreature { dist: d, ..c.clone() })
        })
        .collect();
    out.sort_by(|a, b| a.dist.total_cmp(&b.dist));
    out
}

/// Values derived from rows that change rarely (resource nodes change on a gather, structures
/// on a build, a persona when the mind revises it), kept across transactions and dropped for a
/// key when its rows are written.
///
/// Every write goes through `invalidate` first (in the same transaction). Values loaded after
/// a write in the same transaction may include uncommitted changes, so they are tagged with
/// that transaction's timestamp and not trusted by any other transaction (a failed reducer
/// rolls its writes back; the next one reloads). Values loaded in a transaction that has
/// written nothing are committed state and stay valid until a later write to their key. Like
/// the map cache, this assumes the database runs its reducers one at a time in this module
/// instance.
struct WriteCache<V> {
    rows: HashMap<u32, (V, i64)>,
    /// Timestamp of the last transaction that wrote.
    wrote: i64,
}

impl<V: Clone> WriteCache<V> {
    fn new() -> Self {
        Self { rows: HashMap::new(), wrote: 0 }
    }

    fn get(&mut self, t: i64, key: u32, load: impl FnOnce() -> V) -> V {
        if let Some((v, tag)) = self.rows.get(&key) {
            if *tag == 0 || *tag == t {
                return v.clone();
            }
        }
        let v = load();
        let tag = if self.wrote == t { t } else { 0 };
        self.rows.insert(key, (v.clone(), tag));
        v
    }

    fn invalidate(&mut self, t: i64, key: Option<u32>) {
        self.wrote = t;
        match key {
            Some(k) => {
                self.rows.remove(&k);
            }
            None => self.rows.clear(),
        }
    }
}

thread_local! {
    static CHUNK_RESOURCES: RefCell<WriteCache<Rc<Vec<ResourceNode>>>> = RefCell::new(WriteCache::new());
    static CHUNK_STRUCTURES: RefCell<WriteCache<Rc<Vec<Structure>>>> = RefCell::new(WriteCache::new());
    /// Temperament a persona states (curiosity, sociability, nurture; 50 when not stated).
    static TRAITS: RefCell<WriteCache<[f32; 3]>> = RefCell::new(WriteCache::new());
}

/// The temperament traits the evaluator reads from a character's persona (cached).
pub fn traits_of(ctx: &ReducerContext, id: u32) -> [f32; 3] {
    let t = stamp(ctx);
    TRAITS.with(|c| {
        c.borrow_mut().get(t, id, || {
            let traits: serde_json::Value = ctx.db.persona().id().find(id).and_then(|p| serde_json::from_str(&p.traits).ok()).unwrap_or_default();
            let of = |k: &str| traits[k].as_f64().unwrap_or(50.0) as f32;
            [of("curiosity"), of("sociability"), of("nurture")]
        })
    })
}

/// Call before writing a persona.
pub fn invalidate_traits(ctx: &ReducerContext, id: u32) {
    let t = stamp(ctx);
    TRAITS.with(|c| c.borrow_mut().invalidate(t, Some(id)));
}

fn chunk_resources(ctx: &ReducerContext, chunk: u32) -> Rc<Vec<ResourceNode>> {
    let t = stamp(ctx);
    CHUNK_RESOURCES.with(|c| c.borrow_mut().get(t, chunk, || Rc::new(ctx.db.resource_node().chunk().filter(chunk).collect())))
}

fn chunk_structures(ctx: &ReducerContext, chunk: u32) -> Rc<Vec<Structure>> {
    let t = stamp(ctx);
    CHUNK_STRUCTURES.with(|c| c.borrow_mut().get(t, chunk, || Rc::new(ctx.db.structure().chunk().filter(chunk).collect())))
}

/// Call before inserting (`None`: any chunk) or updating (`Some(chunk)`) a resource node.
pub fn invalidate_resources(ctx: &ReducerContext, chunk: Option<u32>) {
    let t = stamp(ctx);
    CHUNK_RESOURCES.with(|c| c.borrow_mut().invalidate(t, chunk));
}

/// Call before inserting a structure.
pub fn invalidate_structures(ctx: &ReducerContext) {
    let t = stamp(ctx);
    CHUNK_STRUCTURES.with(|c| c.borrow_mut().invalidate(t, None));
}

pub fn resources_near(ctx: &ReducerContext, at: (f32, f32), r: f32) -> Vec<(ResourceNode, f32)> {
    let mut out = Vec::new();
    for c in chunks_around(at.0, at.1, r) {
        for n in chunk_resources(ctx, c).iter() {
            let d = dist(at, (n.x, n.y));
            if d <= r {
                out.push((n.clone(), d));
            }
        }
    }
    out.sort_by(|a, b| a.1.total_cmp(&b.1));
    out
}

pub fn structures_near(ctx: &ReducerContext, at: (f32, f32), r: f32) -> Vec<(Structure, f32)> {
    let mut out = Vec::new();
    for c in chunks_around(at.0, at.1, r) {
        for s in chunk_structures(ctx, c).iter() {
            let d = dist(at, (s.x, s.y));
            if d <= r {
                out.push((s.clone(), d));
            }
        }
    }
    out.sort_by(|a, b| a.1.total_cmp(&b.1));
    out
}

pub fn name_of(ctx: &ReducerContext, id: u32) -> String {
    ctx.db.character().id().find(id).map(|c| c.name).unwrap_or_else(|| format!("#{id}"))
}

/// How `observer` refers to `id`: by name when it knows it, otherwise as a stranger or by
/// kind (`crate::perception::label`: the `perceived_of` law's projection).
pub fn label_for(ctx: &ReducerContext, observer: &Character, id: u32) -> String {
    crate::perception::label(ctx, observer, id, now_ms(ctx))
}

/// Whose a structure is, as `observer` is told it (owner-known): the owner's name when the
/// world's `owner_shown` law says so (it knows the owner's name, `perception::knows_name`, the
/// shared answer; or the structure shows its owner, its kind's `shows_owner`), else `None`, and
/// the structure is just its kind.
///
/// Where the owner stands now never matters (house-owner-label, 2026-11-12): whether one can make
/// someone out (`perceived_of`'s `far`, Cullet's `known_within`) is about the person in sight,
/// never about their house. Before, a known neighbour's house read as "someone too far away to
/// make out"'s (or "a stranger"'s) whenever its owner was away from it (docs/IDEAS_AUDITS.md §2).
/// The client names owners the same way, from `my_known_names` (`living/game/src/looks.rs`).
pub fn owner_label(ctx: &ReducerContext, observer: &Character, owner: u32, kind: &str) -> Option<String> {
    if owner == 0 {
        return None;
    }
    let t = ctx.db.character().id().find(owner)?;
    let knows = owner == observer.id || crate::perception::knows_name(ctx, observer, &t);
    let sc = scripts(ctx);
    let shows = sc.structure(kind).shows_owner;
    if !sc.owner_shown(knows, shows, kind) {
        return None;
    }
    Some(t.name)
}

/// The same, to begin a sentence with.
pub fn label_cap(ctx: &ReducerContext, observer: &Character, id: u32) -> String {
    capitalized(&label_for(ctx, observer, id))
}

/// A label to begin a sentence with.
pub fn capitalized(l: &str) -> String {
    let mut c = l.chars();
    match c.next() {
        Some(f) => f.to_uppercase().chain(c).collect(),
        None => String::new(),
    }
}

/// Name for the story feed: animals carry their species.
pub fn display(ctx: &ReducerContext, id: u32) -> String {
    match ctx.db.character().id().find(id) {
        Some(c) if c.kind != "person" => format!("{} the {}", c.name, c.kind),
        Some(c) => c.name,
        None => format!("#{id}"),
    }
}

thread_local! {
    static SPECIES: std::collections::BTreeMap<String, living_rules::species::Species> =
        living_rules::species::parse(&species_json()).expect("species.json");
}

/// The species profiles: `seeds/species.json` with the seed's `species` entries merged over
/// it. build.rs merges a compiled seed's; a runtime seed's are merged here, the same way.
pub fn species_json() -> String {
    if !crate::seed::is_runtime() {
        return include_str!(concat!(env!("OUT_DIR"), "/species.json")).to_string();
    }
    fn merge(base: &mut serde_json::Value, over: &serde_json::Value) {
        match (base, over) {
            (serde_json::Value::Object(b), serde_json::Value::Object(o)) => {
                for (k, v) in o {
                    merge(b.entry(k.clone()).or_insert(serde_json::Value::Null), v);
                }
            }
            (b, o) => *b = o.clone(),
        }
    }
    let mut species: serde_json::Value = serde_json::from_str(include_str!("../../seeds/species.json")).expect("species.json");
    let seed: serde_json::Value = serde_json::from_str(&crate::seed::active()).expect("seed json");
    if let Some(over) = seed.get("species") {
        merge(&mut species, over);
    }
    species.to_string()
}

pub fn species(kind: &str) -> Option<living_rules::species::Species> {
    SPECIES.with(|s| s.get(kind).cloned())
}

/// A species' scent, if it has one (without cloning the whole profile).
pub fn scent_of(kind: &str) -> Option<living_rules::species::Scent> {
    SPECIES.with(|s| s.get(kind).and_then(|sp| sp.scent.clone()))
}

pub fn chronicle(ctx: &ReducerContext, now: u64, kind: &str, a: u32, b: u32, at: (f32, f32), text: String) {
    // The same event repeated within two minutes becomes one entry with a count.
    let recent: Vec<Chronicle> = ctx.db.chronicle().at_ms().filter(now.saturating_sub(120_000)..).collect();
    for mut c in recent.into_iter().rev().take(40) {
        let base = c.text.rsplit_once(" (×").map(|(b, _)| b.to_string()).unwrap_or_else(|| c.text.clone());
        if c.kind == kind && c.a == a && c.b == b && base == text {
            let n = c.text.rsplit_once(" (×").and_then(|(_, r)| r.trim_end_matches(')').parse::<u32>().ok()).unwrap_or(1) + 1;
            c.text = format!("{base} (×{n})");
            c.at_ms = now;
            ctx.db.chronicle().id().update(c);
            return;
        }
    }
    ctx.db.chronicle().insert(Chronicle { id: 0, at_ms: now, kind: kind.into(), a, b, x: at.0, y: at.1, text });
}

thread_local! {
    /// Bystanders' wakes (docs/BATTLE_SCALE.md, fix 3): when each was last woken by what it saw,
    /// and when a wake held back since is due.
    static BYSTANDER: RefCell<std::collections::HashMap<u32, (u64, Option<u64>)>> = RefCell::new(std::collections::HashMap::new());
}

/// Wake `id`, a bystander of what it just saw (not party to it): at once unless it was woken by
/// what it saw within `witness_wake_ms`, else when that window ends (`due_bystander_wakes`). A
/// party to the event is woken by `wake`, at once.
pub fn wake_bystander(ctx: &ReducerContext, id: u32, now: u64) {
    let ms = laws(ctx).witness_wake_ms as u64;
    if ms == 0 {
        wake(ctx, id);
        return;
    }
    let now_wake = BYSTANDER.with(|b| {
        let mut b = b.borrow_mut();
        let e = b.entry(id).or_insert((0, None));
        if e.0 == 0 || now.saturating_sub(e.0) >= ms {
            *e = (now, None);
            true
        } else {
            e.1.get_or_insert(e.0 + ms);
            false
        }
    });
    if now_wake {
        wake(ctx, id);
    } else {
        diag(|| "wake:deferred".into(), 1);
    }
}

/// The bystanders whose held-back wake is due: woken now (each tick, before the wakes).
pub fn due_bystander_wakes(ctx: &ReducerContext, now: u64) {
    let due: Vec<u32> = BYSTANDER.with(|b| {
        let mut b = b.borrow_mut();
        let mut out = Vec::new();
        b.retain(|id, (last, pending)| {
            if pending.is_some_and(|t| t <= now) {
                out.push(*id);
                *last = now;
                *pending = None;
            }
            pending.is_some() || now.saturating_sub(*last) < 60_000
        });
        out
    });
    for id in due {
        diag(|| "wake:due".into(), 1);
        wake(ctx, id);
    }
}

pub fn wake(ctx: &ReducerContext, id: u32) {
    diag(|| "wake".into(), 1);
    if ctx.db.wake().id().find(id).is_none() {
        ctx.db.wake().insert(Wake { id });
    }
}

/// Whether two routine names mean the same routine ("stay_safe" is "Stay safe").
pub fn same_routine(a: &str, b: &str) -> bool {
    living_rules::normalize::routine_name(a) == living_rules::normalize::routine_name(b)
}

/// A trap's catch: meat gathers in it over time (the rules say how often and how much it
/// holds). `built_ms` marks the last catch counted.
pub fn trap_catch(ctx: &ReducerContext, s: &Structure, now: u64) {
    let sc = scripts(ctx);
    let every = sc.trap_every_ms() as u64;
    if every == 0 {
        return;
    }
    let n = now.saturating_sub(s.built_ms) / every;
    if n == 0 {
        return;
    }
    let holds = sc.num_of("trap_holds", "meat", 3.0) as u32;
    let owner = crate::tables::STRUCTURE_BIT | s.id;
    let add = (n as u32).min(holds.saturating_sub(inv_count(ctx, owner, "meat")));
    if add > 0 {
        inv_add(ctx, owner, "meat", add);
    }
    let mut t = s.clone();
    t.built_ms += n * every;
    ctx.db.structure().id().update(t);
}
