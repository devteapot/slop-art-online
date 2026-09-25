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
        let x = ctx.rng().gen_range(4.0f32..(living_rules::map::MAP_W as f32 - 4.0));
        let y = ctx.rng().gen_range(4.0f32..(living_rules::map::MAP_H as f32 - 4.0));
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
