//! Living core authority: a SpacetimeDB module with typed tables, kinematic motion,
//! analytic needs, Rhai skill rules and in-module behavior graph evaluation.
//! External LLM minds deliver behavior graphs and belief projections through the
//! `mind_*` reducers; they read only their characters' experiences and deliberations.

mod act;
mod brain;
mod mind;
mod motion;
mod perceive;
mod seed;
mod tables;
mod tick;
mod common;

use spacetimedb::{ReducerContext, ScheduleAt, Table, ViewContext};
use std::time::Duration;
use tables::*;

#[spacetimedb::reducer(init)]
pub fn init(ctx: &ReducerContext) -> Result<(), String> {
    let now = common::now_ms(ctx);
    ctx.db.world().insert(World {
        id: 0,
        run: String::new(),
        seed: 0,
        epoch_ms: now,
        day_ms: living_rules::DEFAULT_DAY_MS,
        admin: ctx.sender(),
        paused: false,
        width: living_rules::map::MAP_W,
        height: living_rules::map::MAP_H,
    });
    ctx.db.clock().insert(Clock {
        id: 0,
        tick: 0,
        last_ms: 0,
        last_hour: 7,
        scripts_rev: 1,
        max_gap_ms: 0,
        evals: 0,
        motions: 0,
        completions: 0,
        percepts: 0,
        deliberations: 0,
        profile: false,
        hits: 0,
        dodged: 0,
        blocked: 0,
        missed: 0,
    });
    living_rules::script::Scripts::new(seed::SKILLS)?;
    ctx.db.script().insert(Script { name: "skills".into(), source: seed::SKILLS.into(), revision: 1, updated_ms: now });
    for kind in ["person", "deer", "wolf"] {
        living_rules::graph::parse(&seed::instinct(kind)).map_err(|e| format!("{kind} instinct: {e}"))?;
    }
    seed::seed(ctx, now);
    ctx.db.tick_timer().insert(TickTimer { scheduled_id: 0, scheduled_at: ScheduleAt::Interval(Duration::from_micros(16_667).into()) });
    ctx.db.slow_timer().insert(SlowTimer { scheduled_id: 0, scheduled_at: ScheduleAt::Interval(Duration::from_secs(1).into()) });
    Ok(())
}

fn require_admin(ctx: &ReducerContext) -> Result<World, String> {
    let w = common::world(ctx);
    if ctx.sender() != w.admin {
        return Err("admin only".into());
    }
    Ok(w)
}

#[spacetimedb::reducer]
pub fn set_paused(ctx: &ReducerContext, paused: bool) -> Result<(), String> {
    let mut w = require_admin(ctx)?;
    w.paused = paused;
    ctx.db.world().id().update(w);
    Ok(())
}

/// Replace the skill rules at runtime (next action start/completion uses them).
#[spacetimedb::reducer]
pub fn install_script(ctx: &ReducerContext, source: String) -> Result<(), String> {
    require_admin(ctx)?;
    living_rules::script::Scripts::new(&source)?;
    let now = common::now_ms(ctx);
    let rev = ctx.db.script().name().find("skills".to_string()).map(|s| s.revision + 1).unwrap_or(1);
    ctx.db.script().name().delete("skills".to_string());
    ctx.db.script().insert(Script { name: "skills".into(), source, revision: rev, updated_ms: now });
    let mut k = common::clock(ctx);
    k.scripts_rev = rev;
    ctx.db.clock().id().update(k);
    Ok(())
}

/// Benchmark support: log every tick's duration while enabled.
#[spacetimedb::reducer]
pub fn set_profile(ctx: &ReducerContext, on: bool) -> Result<(), String> {
    require_admin(ctx)?;
    let mut k = common::clock(ctx);
    k.profile = on;
    ctx.db.clock().id().update(k);
    Ok(())
}

/// Benchmark support: add `n` people on their instinct graph. With `minded`, they are
/// controlled by the admin identity like LLM characters (experiences and deliberation
/// requests are produced) even if no mind answers.
#[spacetimedb::reducer]
pub fn spawn_crowd(ctx: &ReducerContext, n: u32, minded: bool) -> Result<(), String> {
    use spacetimedb::rand::Rng;
    require_admin(ctx)?;
    let now = common::now_ms(ctx);
    let map = common::map(ctx);
    let mut made = 0;
    for _ in 0..n.min(5_000) * 20 {
        if made >= n {
            break;
        }
        let x = ctx.rng().gen_range(4.0f32..(map.w as f32 - 4.0));
        let y = ctx.rng().gen_range(4.0f32..(map.h as f32 - 4.0));
        if !map.at(x, y).walkable() {
            continue;
        }
        let controller = if minded { common::world(ctx).admin } else { ctx.database_identity() };
        let id = seed::spawn_creature(ctx, &format!("Walker{}", made + 1), "person", controller, minded, (x, y), now);
        common::inv_add(ctx, id as u64, "berries", 3);
        made += 1;
    }
    Ok(())
}

/// Test support: give a character know-how.
#[spacetimedb::reducer]
pub fn grant_know_how(ctx: &ReducerContext, id: u32, technique: String) -> Result<(), String> {
    require_admin(ctx)?;
    common::learn(ctx, id, &technique, "granted", common::now_ms(ctx));
    Ok(())
}

/// Test support: set a character's background (read by its mind when it first forms an identity).
#[spacetimedb::reducer]
pub fn set_background(ctx: &ReducerContext, id: u32, text: String) -> Result<(), String> {
    require_admin(ctx)?;
    serde_json::from_str::<serde_json::Value>(&text).map_err(|e| format!("background must be JSON: {e}"))?;
    if ctx.db.background().id().find(id).is_some() {
        ctx.db.background().id().update(Background { id, text });
    } else {
        ctx.db.background().insert(Background { id, text });
    }
    Ok(())
}

/// Test support: give a character items.
#[spacetimedb::reducer]
pub fn grant_items(ctx: &ReducerContext, id: u32, item: String, qty: u32) -> Result<(), String> {
    require_admin(ctx)?;
    common::inv_add(ctx, id as u64, &item, qty);
    Ok(())
}

/// Test support: place a structure beside a character.
#[spacetimedb::reducer]
pub fn place_structure(ctx: &ReducerContext, near: u32, kind: String) -> Result<(), String> {
    require_admin(ctx)?;
    let now = common::now_ms(ctx);
    let b = ctx.db.body().id().find(near).ok_or("no such body")?;
    let p = common::pos(&b, now);
    ctx.db.structure().insert(Structure { id: 0, kind, x: p.0 + 0.8, y: p.1, chunk: living_rules::map::chunk_of(p.0 + 0.8, p.1), owner: near, built_ms: now });
    Ok(())
}

/// Test support: install a graph on any character.
#[spacetimedb::reducer]
pub fn set_behavior(ctx: &ReducerContext, id: u32, graph: String) -> Result<(), String> {
    require_admin(ctx)?;
    mind::set_graph(ctx, id, &graph, "test", "test", common::now_ms(ctx)).map(|_| ())
}

/// Test support: move a character next to another.
#[spacetimedb::reducer]
pub fn place_near(ctx: &ReducerContext, id: u32, near: u32) -> Result<(), String> {
    require_admin(ctx)?;
    let now = common::now_ms(ctx);
    let t = ctx.db.body().id().find(near).ok_or("no such body")?;
    let p = common::pos(&t, now);
    let mut b = ctx.db.body().id().find(id).ok_or("no such body")?;
    b.x = p.0 + 1.0;
    b.y = p.1;
    b.t_ms = now;
    b.vx = 0.0;
    b.vy = 0.0;
    b.path.clear();
    b.next_ms = u64::MAX;
    b.chunk = living_rules::map::chunk_of(b.x, b.y);
    ctx.db.body().id().update(b);
    common::invalidate_bodies();
    Ok(())
}

/// Create the seed's communities (if missing) and their members, on a running world.
#[spacetimedb::reducer]
pub fn seed_communities(ctx: &ReducerContext) -> Result<(), String> {
    require_admin(ctx)?;
    seed::communities(ctx, common::now_ms(ctx));
    Ok(())
}

/// Benchmark support: `n` spear-armed people packed into one small area, fighting the
/// nearest person. Even ids dodge incoming windups, odd ids block.
#[spacetimedb::reducer]
pub fn spawn_battle(ctx: &ReducerContext, n: u32) -> Result<(), String> {
    use spacetimedb::rand::Rng;
    require_admin(ctx)?;
    let now = common::now_ms(ctx);
    let map = common::map(ctx);
    let center = map.nearest_walkable(55.0, 60.0).ok_or("no room")?;
    let mut made = 0;
    for _ in 0..n * 30 {
        if made >= n {
            break;
        }
        let p = (center.0 + ctx.rng().gen_range(-7.0f32..7.0), center.1 + ctx.rng().gen_range(-7.0f32..7.0));
        if !map.at(p.0, p.1).walkable() {
            continue;
        }
        let id = seed::spawn_creature(ctx, &format!("Fighter{}", made + 1), "person", ctx.database_identity(), false, p, now);
        common::inv_add(ctx, id as u64, "spear", 1);
        let defend = if id % 2 == 0 { "dodge" } else { "block" };
        let graph = format!(
            r#"{{"first":{{"label":"combat","children":[{{"if":{{"cond":{{"threatened":true}},"then":{{"do":{{"skill":"{defend}"}}}}}}}},{{"do":{{"skill":"attack","target":{{"nearest":"person"}}}}}}]}}}}"#
        );
        mind::set_graph(ctx, id, &graph, "fight", "battle", now)?;
        made += 1;
    }
    Ok(())
}

// ---- views for controllers ------------------------------------------------------

#[spacetimedb::view(accessor = my_deliberations, public)]
pub fn my_deliberations(ctx: &ViewContext) -> Vec<Deliberation> {
    ctx.db.deliberation().controller().filter(ctx.sender()).collect()
}

// ---- human players ----------------------------------------------------------------

#[spacetimedb::reducer]
pub fn join(ctx: &ReducerContext, name: String) -> Result<(), String> {
    let name = name.trim().to_string();
    if name.is_empty() || name.len() > 24 {
        return Err("name must be 1..=24 bytes".into());
    }
    if ctx.db.character().controller().filter(ctx.sender()).any(|c| c.alive && !c.ai) {
        return Err("you already have a living character".into());
    }
    let now = common::now_ms(ctx);
    let map = common::map(ctx);
    let at = map.nearest_walkable(40.0, 60.0).ok_or("no room")?;
    let id = seed::spawn_creature(ctx, &name, "person", ctx.sender(), false, at, now);
    mind::set_graph(ctx, id, r#"{"wait":30}"#, "waiting for you", "human", now)?;
    Ok(())
}

fn my_character(ctx: &ReducerContext) -> Result<Character, String> {
    ctx.db.character().controller().filter(ctx.sender()).find(|c| c.alive && !c.ai).ok_or_else(|| "you have no living character".into())
}

/// Perform one action (behavior graph node JSON, e.g. `{"do":{"skill":"gather","target":{"nearest":"tree"}}}`).
#[spacetimedb::reducer]
pub fn human_act(ctx: &ReducerContext, node: String) -> Result<(), String> {
    let me = my_character(ctx)?;
    let g = living_rules::graph::parse(&node)?;
    let json = format!(r#"{{"seq":[{},{{"wait":60}}]}}"#, g.to_json());
    mind::set_graph(ctx, me.id, &json, "your command", "human", common::now_ms(ctx)).map(|_| ())
}

#[spacetimedb::reducer]
pub fn human_say(ctx: &ReducerContext, text: String, to: u32) -> Result<(), String> {
    let me = my_character(ctx)?;
    perceive::speak(ctx, me.id, &text, to, common::now_ms(ctx))
}
