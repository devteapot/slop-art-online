//! Living core authority: a SpacetimeDB module with typed tables, kinematic motion,
//! analytic needs, Rhai skill rules and in-module behavior graph evaluation.
//! External LLM minds deliver behavior graphs and belief projections through the
//! `mind_*` reducers; they read only their characters' experiences and deliberations.

mod act;
mod acts;
mod brain;
mod codes;
mod combat;
mod floor;
mod frame;
mod island;
mod mind;
mod motion;
mod perceive;
mod perception;
mod presence;
mod records;
mod seed;
mod tables;
mod tick;
mod town;
mod woken;
mod common;

use spacetimedb::{ReducerContext, ScheduleAt, Table, ViewContext};
use std::time::Duration;
use tables::*;
use tables::presence as _;

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
        life_pace: 1.0,
        year_days: living_rules::YEAR_DAYS as u32,
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
    let mut sc = living_rules::script::Scripts::new(seed::SKILLS)?;
    let checked = {
        let _t = spacetimedb::log_stopwatch::LogStopwatch::new("install.validate");
        sc.validate()?
    };
    log::info!("skills script: {}", checked.summary());
    codes::install(ctx, &mut sc)?;
    combat::cards(ctx, &sc);
    town::cards(ctx, &sc);
    ctx.db.script().insert(Script { name: "skills".into(), source: seed::SKILLS.into(), revision: 1, updated_ms: now });
    for kind in ["person", "deer", "wolf"] {
        living_rules::graph::parse(&seed::instinct(kind)).map_err(|e| format!("{kind} instinct: {e}"))?;
    }
    // A module built with a seed creates its world now (in steps when the land is too big for
    // one call); a floor module waits for `create_floor` (floor.rs).
    if !seed::VALLEY.is_empty() {
        let s: seed::Seed = serde_json::from_str(seed::VALLEY).map_err(|e| format!("seed: {e}"))?;
        floor::begin(ctx, &s, now);
    }
    Ok(())
}

/// The world's clocks: the 60 Hz tick and the 1 s housekeeping, once the world exists.
pub(crate) fn start_ticking(ctx: &ReducerContext) {
    ctx.db.tick_timer().insert(TickTimer { scheduled_id: 0, scheduled_at: ScheduleAt::Interval(Duration::from_micros(16_667).into()) });
    ctx.db.slow_timer().insert(SlowTimer { scheduled_id: 0, scheduled_at: ScheduleAt::Interval(Duration::from_secs(1).into()) });
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
    common::invalidate_world();
    Ok(())
}

/// Replace the skill rules at runtime (next action start/completion uses them). The script is
/// compiled and every law and skill function is run on sample inputs first
/// (`Scripts::validate`); a script that fails, reads a field the engine does not provide or
/// exceeds the engine's limits is refused, naming the function, before anything is written.
#[spacetimedb::reducer]
pub fn install_script(ctx: &ReducerContext, source: String) -> Result<(), String> {
    require_admin(ctx)?;
    let mut sc = {
        let _t = spacetimedb::log_stopwatch::LogStopwatch::new("install.compile");
        living_rules::script::Scripts::new(&source)?
    };
    // Installs are rare: always timed.
    let checked = {
        let _t = spacetimedb::log_stopwatch::LogStopwatch::new("install.validate");
        sc.validate()?
    };
    log::info!("install_script: {}", checked.summary());
    rename_techniques(ctx);
    codes::install(ctx, &mut sc)?;
    combat::cards(ctx, &sc);
    town::cards(ctx, &sc);
    let now = common::now_ms(ctx);
    let rev = ctx.db.script().name().find("skills".to_string()).map(|s| s.revision + 1).unwrap_or(1);
    ctx.db.script().name().delete("skills".to_string());
    ctx.db.script().insert(Script { name: "skills".into(), source, revision: rev, updated_ms: now });
    let mut k = common::clock(ctx);
    k.scripts_rev = rev;
    ctx.db.clock().id().update(k);
    common::invalidate_scripts_rev();
    // Takeovers already pending follow the new `takeover_s` law.
    presence::reschedule(ctx, sc.laws().takeover_s);
    Ok(())
}

/// Renamed techniques (`catalog::RENAMED`) take their new names in the world's know-how and in
/// what tablets and signs describe. An install is rare and admin-only: this reads every
/// know-how row and artifact once (there is no index by technique), and writes only renamed rows.
fn rename_techniques(ctx: &ReducerContext) {
    let renamed = |t: &str| living_rules::catalog::RENAMED.iter().find(|(old, _)| *old == t).map(|(_, new)| new.to_string());
    let mut n = 0;
    for k in ctx.db.know_how().iter().filter(|k| renamed(&k.technique).is_some()).collect::<Vec<_>>() {
        let new = renamed(&k.technique).unwrap_or_default();
        if ctx.db.know_how().by_actor_technique().filter((k.actor, new.as_str())).next().is_some() {
            ctx.db.know_how().id().delete(k.id);
        } else {
            ctx.db.know_how().id().update(KnowHow { technique: new, ..k });
        }
        n += 1;
    }
    for a in ctx.db.artifact().iter().filter(|a| renamed(&a.topic).is_some()).collect::<Vec<_>>() {
        let topic = renamed(&a.topic).unwrap_or_default();
        ctx.db.artifact().id().update(Artifact { topic, ..a });
        n += 1;
    }
    if n > 0 {
        log::info!("install_script: {n} know-how rows and writings took a renamed technique's new name");
    }
}

/// Scene support (admin): hold the weather for `secs` seconds (0 hands it back to the seed's
/// own weather). Verification scenes use it to bring rain; it never changes the day length.
#[spacetimedb::reducer]
pub fn set_weather(ctx: &ReducerContext, raining: bool, secs: u32) -> Result<(), String> {
    require_admin(ctx)?;
    town::force_weather(ctx, raining, secs.min(86_400), common::now_ms(ctx));
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
        if !map.free(x, y) {
            continue;
        }
        let controller = if minded { common::world(ctx).admin } else { ctx.database_identity() };
        let id = seed::spawn_creature(ctx, &format!("Walker{}", made + 1), "person", controller, minded, (x, y), now);
        common::inv_add(ctx, id as u64, "berries", 3);
        // Crowds live by a forager's repertoire, like real people (for representative load).
        seed::give_repertoire(ctx, id, "forager", now);
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

/// Migration: the body-habit layer that used to be injected ahead of mind-written graphs
/// becomes an ordinary branch the character owns ("habits"), to keep, change or drop.
#[spacetimedb::reducer]
pub fn own_habits(ctx: &ReducerContext) -> Result<(), String> {
    use crate::tables::brain as _;
    require_admin(ctx)?;
    let now = common::now_ms(ctx);
    let brains: Vec<Brain> = ctx.db.brain().iter().filter(|b| b.graph.contains("\"label\":\"reflexes\"")).collect();
    let mut n = 0;
    for b in brains {
        if !ctx.db.character().id().find(b.id).map_or(false, |c| c.alive) {
            continue;
        }
        let graph = b.graph.replace("\"label\":\"reflexes\"", "\"label\":\"habits\"");
        if mind::set_graph(ctx, b.id, &graph, &b.plan, &b.source, now).is_ok() {
            n += 1;
        }
    }
    log::info!("habit layers now owned by {n} characters");
    Ok(())
}

/// Give each living person without routines the starting repertoire for their background
/// (occupation, band member or child); used when a running world gains repertoires.
#[spacetimedb::reducer]
pub fn grant_repertoires(ctx: &ReducerContext) -> Result<(), String> {
    use crate::tables::routine as _;
    require_admin(ctx)?;
    let now = common::now_ms(ctx);
    let people: Vec<Character> = ctx.db.character().kind().filter("person").filter(|c| c.alive && c.stage >= 1).collect();
    let mut n = 0;
    for c in people {
        if ctx.db.routine().actor().filter(c.id).next().is_some() {
            continue;
        }
        let bg: serde_json::Value = ctx.db.background().id().find(c.id).and_then(|b| serde_json::from_str(&b.text).ok()).unwrap_or_default();
        let occ = if c.stage == 1 {
            "child".to_string()
        } else {
            bg["occupation"].as_str().filter(|o| *o != "child").unwrap_or("forager").to_string()
        };
        seed::give_repertoire(ctx, c.id, &occ, now);
        n += 1;
    }
    log::info!("gave starting repertoires to {n} people");
    Ok(())
}

/// Apply the death cleanup to characters who died before it existed.
#[spacetimedb::reducer]
pub fn purge_dead(ctx: &ReducerContext) -> Result<(), String> {
    require_admin(ctx)?;
    let dead: Vec<u32> = ctx.db.character().iter().filter(|c| !c.alive).map(|c| c.id).collect();
    for id in &dead {
        act::forget_dead(ctx, *id);
        act::retire(ctx, *id);
    }
    log::info!("purged mind-serving rows of {} dead characters", dead.len());
    Ok(())
}

/// Test support: a character dies on the spot.
#[spacetimedb::reducer]
pub fn kill(ctx: &ReducerContext, id: u32, cause: String) -> Result<(), String> {
    require_admin(ctx)?;
    act::die(ctx, id, &cause, common::now_ms(ctx), 0);
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
    common::invalidate_structures(ctx);
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
    motion::place(ctx, id, (p.0 + 1.0, p.1), now)
}

/// Test support: put a character at rest at a point (tiles).
#[spacetimedb::reducer]
pub fn place_at(ctx: &ReducerContext, id: u32, x: f32, y: f32) -> Result<(), String> {
    require_admin(ctx)?;
    let map = common::map(ctx);
    let at = map.nearest_walkable(x, y).ok_or("no room there")?;
    motion::place(ctx, id, at, common::now_ms(ctx))
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
    let spot = if ctx.db.land().id().find(0).is_some() { let a = island::arrival(ctx); (a.0, a.1 - 20.0) } else { (55.0, 60.0) };
    let center = map.nearest_walkable(spot.0, spot.1).ok_or("no room")?;
    let mut made = 0;
    for _ in 0..n * 30 {
        if made >= n {
            break;
        }
        let p = (center.0 + ctx.rng().gen_range(-7.0f32..7.0), center.1 + ctx.rng().gen_range(-7.0f32..7.0));
        if !map.free(p.0, p.1) {
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

/// Benchmark and test support: `n` people in two sides `spacing` tiles apart near the
/// arrival point (or the map centre), fighting the other side with the starter skills on a
/// behavior graph (strike in reach, bow shots at range, block or dodge when threatened, a
/// heal when hurt). Each side is a community; the other side's people are `outsider`s.
#[spacetimedb::reducer]
pub fn spawn_skirmish(ctx: &ReducerContext, n: u32, spacing: f32) -> Result<(), String> {
    use spacetimedb::rand::Rng;
    require_admin(ctx)?;
    let now = common::now_ms(ctx);
    let map = common::map(ctx);
    let spot = if ctx.db.land().id().find(0).is_some() { let a = island::arrival(ctx); (a.0, a.1 - 30.0) } else { (map.w as f32 / 2.0, map.h as f32 / 2.0) };
    let center = map.nearest_walkable(spot.0, spot.1).ok_or("no room")?;
    let community = |name: &str| -> u32 {
        match ctx.db.community().iter().find(|c| c.name == name) {
            Some(c) => c.id,
            None => ctx.db.community().insert(Community { id: 0, name: name.into(), founder: 0, founded_ms: now, home_x: center.0, home_y: center.1 }).id,
        }
    };
    let sides = [community("Skirmish East"), community("Skirmish West")];
    let mut made = 0;
    for _ in 0..n * 40 {
        if made >= n {
            break;
        }
        let side = (made % 2) as usize;
        let dx = if side == 0 { spacing * 0.5 } else { -spacing * 0.5 };
        let p = (center.0 + dx + ctx.rng().gen_range(-3.0f32..3.0), center.1 + ctx.rng().gen_range(-6.0f32..6.0));
        if !map.free(p.0, p.1) {
            continue;
        }
        let name = format!("{}{}", if side == 0 { "East" } else { "West" }, made / 2 + 1);
        let id = seed::spawn_creature(ctx, &name, "person", ctx.database_identity(), false, p, now);
        common::inv_add(ctx, id as u64, "bow", 1);
        common::inv_add(ctx, id as u64, "arrow", 40);
        common::learn(ctx, id, "wound_tending", "skirmish", now);
        ctx.db.membership().insert(Membership { id: 0, community: sides[side], member: id, since_ms: now });
        let graph = format!(
            r#"{{"first":{{"label":"combat","children":[
              {{"if":{{"cond":{{"threatened":true}},"then":{{"do":{{"skill":"{defend}"}}}}}}}},
              {{"if":{{"cond":{{"health":{{"below":45}}}},"then":{{"do":{{"skill":"heal","target":"self"}}}}}}}},
              {{"if":{{"cond":{{"near":{{"target":{{"nearest":{{"kind":"person","relation":"outsider"}}}},"within":2}}}},"then":{{"do":{{"skill":"strike","target":{{"nearest":{{"kind":"person","relation":"outsider"}}}}}}}}}}}},
              {{"if":{{"cond":{{"near":{{"target":{{"nearest":{{"kind":"person","relation":"outsider"}}}},"within":14}}}},"then":{{"do":{{"skill":"bowshot","target":{{"nearest":{{"kind":"person","relation":"outsider"}}}}}}}}}}}},
              {{"if":{{"cond":{{"sees":{{"nearest":{{"kind":"person","relation":"outsider"}}}}}},"then":{{"do":{{"skill":"goto","target":{{"nearest":{{"kind":"person","relation":"outsider"}}}}}}}}}}}},
              {{"do":{{"skill":"goto","target":{{"at":[{fx},{fy}]}}}}}}]}}}}"#,
            defend = if id % 2 == 0 { "dodge" } else { "block" },
            // With no one of the other side in sight, toward where they started.
            fx = center.0 - dx,
            fy = center.1,
        );
        mind::set_graph(ctx, id, &graph.replace(['\n', ' '], ""), "skirmish", "battle", now)?;
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
    if perception::player_character(ctx).is_some() || ctx.db.presence().player().filter(ctx.sender()).next().is_some() {
        return Err("you already have a living character".into());
    }
    let now = common::now_ms(ctx);
    let map = common::map(ctx);
    let arrive = island::arrival(ctx);
    let at = map.nearest_walkable(arrive.0, arrive.1).ok_or("no room")?;
    let id = seed::spawn_creature(ctx, &name, "person", ctx.sender(), false, at, now);
    perception::set_player(ctx, ctx.sender(), id);
    mind::set_graph(ctx, id, r#"{"wait":30}"#, "waiting for you", "human", now)?;
    // What the world gives every newcomer (the seed's `newcomer`): nothing of anyone before.
    seed::newcomer_kit(ctx, id, now);
    presence::start(ctx, id, ctx.sender(), now);
    combat::invalidate_humans();
    // What the newcomer perceives is there from the first frame, not after a sweep.
    perception::sweep_now(ctx, id, ctx.sender(), now);
    Ok(())
}

/// Test support (trials, docs/TRIALS.md): a newcomer as `join` makes one — the same arrival
/// point and the seed's newcomer kit, the species' instinct graph — but thought for by the
/// admin's minds (`ai`), so one mind-backed character can live among residents that have no
/// minds (`rules.minds = false`). It has no background; a caller that wants the mind to write
/// it an identity sets one (`set_background`), as the trial runner does.
#[spacetimedb::reducer]
pub fn spawn_newcomer(ctx: &ReducerContext, name: String) -> Result<(), String> {
    let w = require_admin(ctx)?;
    let name = name.trim().to_string();
    if name.is_empty() || name.len() > 24 {
        return Err("name must be 1..=24 bytes".into());
    }
    let now = common::now_ms(ctx);
    let map = common::map(ctx);
    let arrive = island::arrival(ctx);
    let at = map.nearest_walkable(arrive.0, arrive.1).ok_or("no room")?;
    let id = seed::spawn_creature(ctx, &name, "person", w.admin, true, at, now);
    seed::newcomer_kit(ctx, id, now);
    log::info!("newcomer {name} (#{id}) arrives, thought for by the admin's minds");
    Ok(())
}

fn my_character(ctx: &ReducerContext) -> Result<Character, String> {
    perception::player_character(ctx).ok_or_else(|| "you have no living character".into())
}

/// Perform one action (behavior graph node JSON, e.g. `{"do":{"skill":"gather","target":{"nearest":"tree"}}}`).
/// A single deliberate act (give, offer, conceive, teach...) runs through the same act path as
/// a mind's decisions (see `acts.rs`), replacing whatever the player commanded before; any
/// other node becomes the character's behavior.
#[spacetimedb::reducer]
pub fn human_act(ctx: &ReducerContext, node: String) -> Result<(), String> {
    let me = my_character(ctx)?;
    let g = living_rules::graph::parse(&node)?;
    if let living_rules::graph::Node::Do(a) = &g.root {
        if living_rules::acts::not_an_act(&a.skill, common::scripts(ctx).shapes()).is_none() {
            acts::submit(ctx, me.id, &[g.to_json()], "human", true, common::now_ms(ctx));
            return Ok(());
        }
    }
    let json = format!(r#"{{"seq":[{},{{"wait":60}}]}}"#, g.to_json());
    mind::set_graph(ctx, me.id, &json, "your command", "human", common::now_ms(ctx)).map(|_| ())
}

/// Move in a direction (screen axes: +x east, +y south; any length) or stop (`0, 0`), at a
/// walk or a run. Steering carries it out with the same physics as everyone's movement;
/// it replaces whatever the character was doing. Send it when the intent changes (a key
/// pressed or released, the stick turned); repeats of the current intent are free, and
/// changes are rate-limited by the `input_hz`/`input_burst` laws.
#[spacetimedb::reducer]
pub fn human_move(ctx: &ReducerContext, dx: f32, dy: f32, run: bool) -> Result<(), String> {
    let me = my_character(ctx)?;
    if !dx.is_finite() || !dy.is_finite() {
        return Err("direction must be finite".into());
    }
    let now = common::now_ms(ctx);
    // A blow, a shot or a dash under way holds the body: the movement follows when it ends.
    if combat::rooted_now(ctx, me.id) {
        combat::defer_move(ctx, me.id, dx, dy, run);
        return Ok(());
    }
    let dir = (dx != 0.0 || dy != 0.0).then_some((dx, dy));
    // A raised guard (a skill the rules aim `facing`).
    let sc = common::scripts(ctx);
    let guard = |a: &Activity| sc.combat(&a.skill).is_some_and(|s| s.aim == living_rules::combat::Aim::Facing);
    if dir.is_some() {
        // Taking the controls: what was going on stops (a raised guard walks along), and the
        // plan becomes "wait".
        if let Some(a) = ctx.db.activity().id().find(me.id).filter(|a| a.skill != "wait" && !(guard(a) && a.node == act::PLAYER)) {
            act::cancel(ctx, a, now, Some("you moved"));
        }
        player_controls(ctx, me.id, now)?;
    }
    // A guard is held at a walk.
    let guarding = ctx.db.activity().id().find(me.id).is_some_and(|a| guard(&a));
    motion::intent(ctx, me.id, dir, run && !guarding, || act::walk_speed(ctx, me.id, now), now)
}

const MOVING: &str = "moving yourself";

/// A player takes the controls: the character's plan becomes waiting for them.
pub(crate) fn player_controls(ctx: &ReducerContext, id: u32, now: u64) -> Result<(), String> {
    use crate::tables::brain as _;
    if ctx.db.brain().id().find(id).map_or(true, |b| b.plan != MOVING) {
        mind::set_graph(ctx, id, r#"{"wait":60}"#, MOVING, "human", now)?;
    }
    Ok(())
}

#[spacetimedb::reducer]
pub fn human_say(ctx: &ReducerContext, text: String, to: u32) -> Result<(), String> {
    let me = my_character(ctx)?;
    perceive::speak(ctx, me.id, &text, to, true, common::now_ms(ctx))
}
