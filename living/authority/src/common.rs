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
}

pub fn now_ms(ctx: &ReducerContext) -> u64 {
    (ctx.timestamp.to_micros_since_unix_epoch() / 1000) as u64
}

pub fn world(ctx: &ReducerContext) -> World {
    ctx.db.world().id().find(0).expect("world initialized")
}

pub fn clock(ctx: &ReducerContext) -> Clock {
    ctx.db.clock().id().find(0).expect("clock initialized")
}

pub fn map(ctx: &ReducerContext) -> Rc<Map> {
    MAP.with(|m| {
        if let Some(map) = m.borrow().as_ref() {
            return map.clone();
        }
        let map = Rc::new(Map::from_chunks(ctx.db.terrain_chunk().iter().map(|c| (c.id, c.tiles))));
        *m.borrow_mut() = Some(map.clone());
        map
    })
}

pub fn invalidate_map() {
    MAP.with(|m| *m.borrow_mut() = None);
}

pub fn scripts(ctx: &ReducerContext) -> Rc<Scripts> {
    let rev = clock(ctx).scripts_rev;
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

/// A validated graph with preorder subtree sizes.
pub struct Compiled {
    pub root: Node,
    pub sizes: Vec<u16>,
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
            _ => {}
        }
        out[me] = total;
        total
    }
    let mut out = Vec::new();
    go(root, &mut out);
    out
}

pub fn compiled(ctx: &ReducerContext, id: u32, revision: u32) -> Option<Rc<Compiled>> {
    if let Some(c) = GRAPHS.with(|g| g.borrow().get(&id).filter(|(r, _)| *r == revision).map(|(_, c)| c.clone())) {
        return Some(c);
    }
    let brain = ctx.db.brain().id().find(id)?;
    let graph = living_rules::graph::parse(&brain.graph).ok()?;
    let c = Rc::new(Compiled { sizes: sizes(&graph.root), root: graph.root });
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

pub fn age_days(c: &Character, w: &World, now: u64) -> f32 {
    c.birth_age_days + now.saturating_sub(c.born_ms) as f32 / w.day_ms.max(1) as f32
}

pub fn sight(w: &World, now: u64) -> f32 {
    if night(w, now) {
        living_rules::NIGHT_SIGHT
    } else {
        living_rules::SIGHT
    }
}

// ---- bodies ---------------------------------------------------------------------

pub fn pos(b: &Body, now: u64) -> (f32, f32) {
    if b.vx == 0.0 && b.vy == 0.0 {
        return (b.x, b.y);
    }
    let t = now.min(b.next_ms).saturating_sub(b.t_ms) as f32 / 1000.0;
    (b.x + b.vx * t, b.y + b.vy * t)
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

pub fn amount_now(r: &ResourceNode, now: u64) -> f32 {
    (r.amount + r.regen * now.saturating_sub(r.at_ms) as f32 / 60_000.0).min(r.max)
}

// ---- spatial queries ------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct NearCreature {
    pub id: u32,
    pub kind: String,
    pub pos: (f32, f32),
    pub dist: f32,
}

pub fn creatures_near(ctx: &ReducerContext, at: (f32, f32), r: f32, now: u64) -> Vec<NearCreature> {
    let mut out = Vec::new();
    for c in chunks_around(at.0, at.1, r) {
        for b in ctx.db.body().chunk().filter(c) {
            let p = pos(&b, now);
            let d = dist(at, p);
            if d <= r {
                out.push(NearCreature { id: b.id, kind: b.kind, pos: p, dist: d });
            }
        }
    }
    out.sort_by(|a, b| a.dist.total_cmp(&b.dist));
    out
}

pub fn resources_near(ctx: &ReducerContext, at: (f32, f32), r: f32) -> Vec<(ResourceNode, f32)> {
    let mut out = Vec::new();
    for c in chunks_around(at.0, at.1, r) {
        for n in ctx.db.resource_node().chunk().filter(c) {
            let d = dist(at, (n.x, n.y));
            if d <= r {
                out.push((n, d));
            }
        }
    }
    out.sort_by(|a, b| a.1.total_cmp(&b.1));
    out
}

pub fn structures_near(ctx: &ReducerContext, at: (f32, f32), r: f32) -> Vec<(Structure, f32)> {
    let mut out = Vec::new();
    for c in chunks_around(at.0, at.1, r) {
        for s in ctx.db.structure().chunk().filter(c) {
            let d = dist(at, (s.x, s.y));
            if d <= r {
                out.push((s, d));
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
        Some(c) if c.kind == "person" || c.kind == observer.kind => c.name,
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
        living_rules::species::parse(include_str!("../../seeds/species.json")).expect("species.json");
}

pub fn species(kind: &str) -> Option<living_rules::species::Species> {
    SPECIES.with(|s| s.get(kind).cloned())
}

pub fn chronicle(ctx: &ReducerContext, now: u64, kind: &str, a: u32, b: u32, at: (f32, f32), text: String) {
    ctx.db.chronicle().insert(Chronicle { id: 0, at_ms: now, kind: kind.into(), a, b, x: at.0, y: at.1, text });
}

pub fn wake(ctx: &ReducerContext, id: u32) {
    if ctx.db.wake().id().find(id).is_none() {
        ctx.db.wake().insert(Wake { id });
    }
}
