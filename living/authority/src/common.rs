//! Shared authority helpers: caches, time, positions, needs, inventory, spatial queries.

use crate::tables::*;
use living_rules::graph::Node;
use living_rules::map::{chunks_around, Map};
use living_rules::script::Scripts;
use spacetimedb::{ReducerContext, Table};
use std::cell::RefCell;
use std::collections::HashMap;
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

/// A named timing span logged by the host while profiling is on (see `tools/bench.py`).
pub fn span(name: &str) -> Option<spacetimedb::log_stopwatch::LogStopwatch> {
    PROFILE.with(|p| p.get()).then(|| spacetimedb::log_stopwatch::LogStopwatch::new(name))
}

pub fn now_ms(ctx: &ReducerContext) -> u64 {
    (ctx.timestamp.to_micros_since_unix_epoch() / 1000) as u64
}

/// The transaction's timestamp in microseconds: the key of caches that are valid only
/// within one reducer call (a later call, or one rolled back, has another timestamp).
fn stamp(ctx: &ReducerContext) -> i64 {
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

pub fn map(ctx: &ReducerContext) -> Rc<Map> {
    MAP.with(|m| {
        if let Some(map) = m.borrow().as_ref() {
            return map.clone();
        }
        let w = world(ctx);
        let mut map = Map::from_chunks(w.width, w.height, ctx.db.terrain_chunk().iter().map(|c| (c.id, c.tiles)));
        // Shut gates block like walls (few rows; rebuilt only when a gate or tile changes).
        for g in ctx.db.gate().iter().filter(|g| !g.open) {
            if g.x >= 0 && g.y >= 0 && (g.x as u32) < w.width && (g.y as u32) < w.height {
                map.blocked.insert(g.y as u32 * w.width + g.x as u32);
            }
        }
        let map = Rc::new(map);
        *m.borrow_mut() = Some(map.clone());
        map
    })
}

pub fn invalidate_map() {
    MAP.with(|m| *m.borrow_mut() = None);
}

/// Change one terrain tile (a road laid, a wall built) and persist its chunk row.
pub fn set_tile(ctx: &ReducerContext, x: i32, y: i32, t: living_rules::map::Terrain) -> Result<(), String> {
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
    invalidate_map();
    Ok(())
}

/// World laws from the installed scripts (cached with them).
pub fn laws(ctx: &ReducerContext) -> living_rules::script::Laws {
    let rev = scripts_rev(ctx);
    if let Some(l) = LAWS.with(|l| l.get().filter(|(r, _)| *r == rev).map(|(_, l)| l)) {
        return l;
    }
    let l = scripts(ctx).laws();
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
        let sc = Rc::new(Scripts::new(&src).expect("installed skills script compiles"));
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

pub fn night(w: &World, now: u64) -> bool {
    living_rules::is_night(hour(w, now))
}

/// A species' life table (lifespan and stages).
pub fn life_of(kind: &str) -> living_rules::life::Life {
    species(kind).map(|s| s.life).unwrap_or_default()
}

/// The world's time for lives: days per year and pace.
pub fn pace(w: &World) -> living_rules::life::Pace {
    living_rules::life::Pace { year_days: w.year_days.max(1) as f32, pace: w.life_pace }
}

/// Life stage of a character now, at the world's pace.
pub fn stage_of(c: &Character, w: &World, now: u64) -> living_rules::life::Stage {
    life_of(&c.kind).stage(age_days(c, w, now), pace(w))
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

pub fn sight(ctx: &ReducerContext, w: &World, now: u64) -> f32 {
    let l = laws(ctx);
    if night(w, now) {
        l.sight_night
    } else {
        l.sight_day
    }
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

/// Re-anchor needs at `now`.
pub fn settle(v: &mut Vitals, now: u64) {
    let n = needs(v, now);
    v.hp = n.hp;
    v.hunger = n.hunger;
    v.energy = n.energy;
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

/// Best food item held: cooked first, then by nutrition.
pub fn best_food(ctx: &ReducerContext, owner: u64) -> Option<String> {
    let held = inv_list(ctx, owner);
    ["cooked_meat", "cooked_fish", "meat", "fish", "berries"]
        .iter()
        .find(|f| held.iter().any(|(i, q)| i == *f && *q > 0))
        .map(|s| s.to_string())
}

pub fn food_count(ctx: &ReducerContext, owner: u64) -> u32 {
    inv_list(ctx, owner)
        .into_iter()
        .filter(|(i, _)| living_rules::catalog::item(i).map_or(false, |s| s.food))
        .map(|(_, q)| q)
        .sum()
}

// ---- resources ----------------------------------------------------------------

/// Resource amount now: regrowth counts only growing (non-winter) time.
/// Grazing per grassy tile a chunk holds, and its regrowth per minute of growing time.
/// Regrowth is a world law (`pasture_regen` in the rules script).
const PASTURE_PER_TILE: f32 = 0.02;

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
    let max = tiles as f32 * PASTURE_PER_TILE;
    Pasture { chunk, amount: max, max, regen: tiles as f32 * laws(ctx).pasture_regen, at_ms: now }
}

/// Grazing left in a chunk now.
pub fn pasture_now(ctx: &ReducerContext, chunk: u32, now: u64) -> f32 {
    let p = pasture_row(ctx, chunk, now);
    let (epoch, day, year) = calendar(ctx);
    // Regrowth follows the current rules (the row keeps the chunk's grassy tiles as its max).
    let regen = p.max / PASTURE_PER_TILE * laws(ctx).pasture_regen;
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

pub fn amount_now(ctx: &ReducerContext, r: &ResourceNode, now: u64) -> f32 {
    let (epoch, day, year) = calendar(ctx);
    (r.amount + r.regen * living_rules::growing_ms(r.at_ms, now, epoch, day, year) as f32 / 60_000.0).min(r.max)
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

/// Sight for a particular creature: a torch pushes back the night.
pub fn sight_for(ctx: &ReducerContext, id: u32, w: &World, now: u64) -> f32 {
    if night(w, now) && inv_count(ctx, id as u64, "torch") > 0 {
        laws(ctx).sight_torch
    } else {
        sight(ctx, w, now)
    }
}

pub fn knows(ctx: &ReducerContext, id: u32) -> Vec<String> {
    ctx.db.know_how().actor().filter(id).map(|k| k.technique).collect()
}

/// Learn a technique; false if already known.
pub fn learn(ctx: &ReducerContext, id: u32, technique: &str, source: &str, now: u64) -> bool {
    if ctx.db.know_how().by_actor_technique().filter((id, technique)).next().is_some() {
        return false;
    }
    ctx.db.know_how().insert(KnowHow { id: 0, actor: id, technique: technique.into(), source: source.into(), since_ms: now });
    true
}

// ---- spatial queries ------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct NearCreature {
    pub id: u32,
    pub kind: Rc<str>,
    pub pos: (f32, f32),
    pub dist: f32,
}

thread_local! {
    /// Bodies per chunk at one instant, shared by every evaluation in the same tick.
    static CHUNK_BODIES: RefCell<(u64, HashMap<u32, Rc<Vec<(u32, Rc<str>, (f32, f32))>>>)> = RefCell::new((0, HashMap::new()));
}

fn chunk_bodies(ctx: &ReducerContext, chunk: u32, now: u64) -> Rc<Vec<(u32, Rc<str>, (f32, f32))>> {
    CHUNK_BODIES.with(|c| {
        let mut c = c.borrow_mut();
        if c.0 != now {
            c.0 = now;
            c.1.clear();
        }
        if let Some(v) = c.1.get(&chunk) {
            return v.clone();
        }
        let v: Rc<Vec<_>> = Rc::new(ctx.db.body().chunk().filter(chunk).map(|b| (b.id, Rc::from(b.kind.as_str()), pos(&b, now))).collect());
        c.1.insert(chunk, v.clone());
        v
    })
}

/// Forget cached bodies (after a body is removed or moved to another chunk this instant).
pub fn invalidate_bodies() {
    CHUNK_BODIES.with(|c| c.borrow_mut().0 = 0);
}

pub fn creatures_near(ctx: &ReducerContext, at: (f32, f32), r: f32, now: u64) -> Vec<NearCreature> {
    let mut out = Vec::new();
    for c in chunks_around(at.0, at.1, r) {
        for (id, kind, p) in chunk_bodies(ctx, c, now).iter() {
            let d = dist(at, *p);
            if d <= r {
                out.push(NearCreature { id: *id, kind: kind.clone(), pos: *p, dist: d });
            }
        }
    }
    out.sort_by(|a, b| a.dist.total_cmp(&b.dist));
    out
}

/// Creatures a body of species `kind` smells beyond `sight` (within its scent radius, of its
/// scent kinds), nearest first; empty for a body without a scent. Uses the same per-tick chunk
/// cache as sight: a radius of 60 tiles covers at most 9x9 chunks, filtered by kind first.
pub fn smelled_near(ctx: &ReducerContext, kind: &str, at: (f32, f32), sight: f32, now: u64) -> Vec<NearCreature> {
    let Some(scent) = scent_of(kind).filter(|s| s.radius > sight) else { return Vec::new() };
    let mut out = Vec::new();
    for c in chunks_around(at.0, at.1, scent.radius) {
        for (id, k, p) in chunk_bodies(ctx, c, now).iter() {
            if !scent.kinds.iter().any(|x| **x == **k) {
                continue;
            }
            let d = dist(at, *p);
            if d > sight && d <= scent.radius {
                out.push(NearCreature { id: *id, kind: k.clone(), pos: *p, dist: d });
            }
        }
    }
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

/// How `observer` refers to `id`: people by name, their own kind by name, others by kind.
pub fn label_for(ctx: &ReducerContext, observer: &Character, id: u32) -> String {
    match ctx.db.character().id().find(id) {
        // People know each other's names; animals know only their own kind by name.
        Some(c) if c.kind == observer.kind || (c.kind == "person" && observer.kind == "person") => c.name,
        Some(c) => format!("a {}", c.kind),
        None => "someone".into(),
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
        living_rules::species::parse(include_str!(concat!(env!("OUT_DIR"), "/species.json"))).expect("species.json");
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

pub fn wake(ctx: &ReducerContext, id: u32) {
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
    let every = (sc.num_of("trap_every_s", "meat", 240.0) * 1000.0) as u64;
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
