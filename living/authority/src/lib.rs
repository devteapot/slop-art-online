//! Living core authority: a SpacetimeDB module with typed tables, kinematic motion,
//! analytic needs, Rhai skill rules and in-module behavior graph evaluation.
//! External LLM minds deliver behavior graphs and belief projections through the
//! `mind_*` reducers; they read only their characters' experiences and deliberations.

mod act;
mod seen_structures;
mod acts;
mod attention;
mod brain;
mod breath;
mod codes;
mod combat;
mod floor;
mod geometry;
mod frame;
mod frame_trace;
mod island;
mod look;
mod mind;
mod motion;
mod outcomes;
mod perceive;
mod speech;
mod stock;
mod perception;
mod presence;
mod records;
mod seed;
mod sex;
mod tables;
mod tick;
mod town;
mod common;
mod det;
mod far;
mod earshot;
mod fold;
mod fast;
mod known;
mod latency;

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
        look_book: String::new(),
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
    speech::cards(ctx, &sc);
    ctx.db.script().insert(Script { name: "skills".into(), source: seed::SKILLS.into(), revision: 1, updated_ms: now });
    common::publish_cover_law(ctx, sc.laws());
    for kind in ["person", "deer", "wolf"] {
        living_rules::graph::parse(&seed::instinct(kind)).map_err(|e| format!("{kind} instinct: {e}"))?;
    }
    // A module built with a seed creates its world now (in steps when the land is too big for
    // one call); a floor module waits for `create_floor` (floor.rs).
    if !seed::VALLEY.is_empty() {
        let s: seed::Seed = serde_json::from_str(seed::VALLEY).map_err(|e| format!("seed: {e}"))?;
        let laws = floor::check(&s)?;
        floor::begin(ctx, &s, laws, now)?;
    }
    Ok(())
}

/// The world's clocks: the 60 Hz tick and the 1 s housekeeping, once the world exists.
pub(crate) fn start_ticking(ctx: &ReducerContext) {
    // A measurement build (`LIVING_NO_TICK=1`: genesis compared by table hashes,
    // docs/STAGED_GENESIS.md §5) makes the world and leaves it still.
    if option_env!("LIVING_NO_TICK").is_some() {
        return;
    }
    ctx.db.tick_timer().insert(TickTimer { scheduled_id: 0, scheduled_at: ScheduleAt::Interval(Duration::from_micros(crate::frame::TICK_US as u64).into()) });
    ctx.db.slow_timer().insert(SlowTimer { scheduled_id: 0, scheduled_at: ScheduleAt::Interval(Duration::from_secs(1).into()) });
}

/// Why cover sight cannot go on: only a land has the ground its cover geometry is sampled from
/// (a land without the geometry derives it: `geometry`).
const NO_COVER_LAND: &str = "cover sight requires a land world (a seed whose map kind is \"land\"), once it is made";

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
    install_source(ctx, source)
}

/// Install a skill script: compiled and validated on the world's day, then written with a new
/// revision. `install_script` (the admin) and a seed's laws overlay (`floor::begin`) go through it.
pub(crate) fn install_source(ctx: &ReducerContext, source: String) -> Result<(), String> {
    install(ctx, source, false)
}

/// Install a seed's laws overlay that `floor::check` has just compiled and validated (on this
/// world's day, which `floor::begin` set first): validated again only when the world already has
/// values of its own (`law_override`), which make the installed source differ from the checked
/// one. At genesis it has none, so the overlay is validated once (about 26 × 10⁹ fuel on Cullet;
/// docs/STAGED_GENESIS.md §1).
pub(crate) fn install_checked_source(ctx: &ReducerContext, source: String) -> Result<(), String> {
    install(ctx, source, true)
}

fn install(ctx: &ReducerContext, source: String, checked: bool) -> Result<(), String> {
    // The world's own law values (`law_override`: a seed's `rules`, `set_world_law`) are written
    // at the end of the installed source, so a client that compiles the `script` row alone reads
    // the values of an install (`living_rules::script::with_world_laws`), and laid over the
    // compiled script, as the authority and every client lay the rows over (`with_overrides`).
    let values = world_law_values(ctx);
    let source = installed_source(&source, &values);
    let mut sc = {
        let _t = spacetimedb::log_stopwatch::LogStopwatch::new("install.compile");
        living_rules::script::Scripts::with_overrides(&source, common::world(ctx).day_ms, &values)?
    };
    // A made world without cover geometry derives it once cover is on (`geometry::ensure`,
    // below); only a world that is not a land cannot have it.
    if sc.laws().cover_sight_on && !common::world(ctx).run.is_empty() && ctx.db.land().id().find(0).is_none() {
        return Err(NO_COVER_LAND.into());
    }
    if checked && values.is_empty() {
        log::info!("install_script: validated by the seed check");
    } else {
        // Installs are rare: always timed.
        let checked = {
            let _t = spacetimedb::log_stopwatch::LogStopwatch::new("install.validate");
            sc.validate()?
        };
        log::info!("install_script: {}", checked.summary());
    }
    // A world made before owner-known: its public land row loses its names, once.
    crate::island::scrub_land(ctx);
    // The body's meters name fields of this world's vitals row.
    if let Some(e) = sc.meters_unknown(&Vitals::FIELDS).first() {
        return Err(format!("install refused: {e}"));
    }
    rename_techniques(ctx);
    codes::install(ctx, &mut sc)?;
    combat::cards(ctx, &sc);
    town::cards(ctx, &sc);
    speech::cards(ctx, &sc);
    let now = common::now_ms(ctx);
    // Past the clock's too: writing a world's own laws moves it without a new script.
    let rev = ctx.db.script().name().find("skills".to_string()).map(|s| s.revision).unwrap_or(0).max(common::clock(ctx).scripts_rev) + 1;
    ctx.db.script().name().delete("skills".to_string());
    ctx.db.script().insert(Script { name: "skills".into(), source, revision: rev, updated_ms: now });
    let mut k = common::clock(ctx);
    k.scripts_rev = rev;
    ctx.db.clock().id().update(k);
    common::invalidate_scripts_rev();
    // Cover on in a land without its geometry: derived in steps, in force once complete.
    geometry::ensure(ctx, sc.laws().cover_sight_on);
    common::publish_cover_law(ctx, sc.laws());
    if !sc.gaze_enabled() {
        attention::clear_projection(ctx);
    }
    // Takeovers already pending follow the new `takeover_s` law.
    presence::reschedule(ctx, sc.laws().takeover_s);
    // Looks change band by the life table and the `look_bands` law: their times follow.
    look::retime_all(ctx, now);
    Ok(())
}

/// The text a script is kept as in the `script` row: `source` with the world's own law values
/// written at its end, replacing any it carried. `install_source` and a seed's `rules`
/// (`floor::world_laws`) write the row through it.
pub(crate) fn installed_source(source: &str, values: &[(String, serde_json::Value)]) -> String {
    living_rules::script::with_world_laws(living_rules::script::without_world_laws(source), values)
}

/// The world's own law values (`law_override` rows), by name.
pub(crate) fn world_law_values(ctx: &ReducerContext) -> Vec<(String, serde_json::Value)> {
    // Copied from `world_law` first on a world from before `law_override`.
    common::law_rev(ctx);
    common::overrides(ctx)
}

/// Change a law on a running world (admin): `name` is any constant of the script's `laws()`
/// (`fov_on`, `fire_warmth`, …), `value` its new value as JSON (`true`, `1.5`), of the law's
/// own kind. The value is kept as the world's own in the public `law_override` row (with a new
/// law revision), which the authority and every client lay over the compiled script
/// (docs/LAW_OVERRIDE.md):
/// - a value-only law (`living_rules::script::VALUE_ONLY`: the delivery, cover and gaze laws)
///   takes effect from the next transaction with the compiled script kept: no compile, no
///   validation, no new script revision; what it reaches is refreshed (the gaze ceilings and
///   senses, the cover policy row and mask, the owner gaze projection when gaze goes off);
/// - any other law installs the script again with the values written at its end
///   (`world_law_values()`), validated in full, with a new script revision, as before.
/// Every change is kept in `law_change` (name, old, new, when, who, the script revision in force
/// after it) and in the chronicle. Refused, with nothing written, for a name that is not a law, a
/// value of another kind, or a value the laws cannot run with (a gaze ceiling out of bounds, a
/// script that fails its install checks).
#[spacetimedb::reducer]
pub fn set_world_law(ctx: &ReducerContext, name: String, value: String) -> Result<(), String> {
    require_admin(ctx)?;
    let _t = spacetimedb::log_stopwatch::LogStopwatch::new("set_world_law");
    let v: serde_json::Value = serde_json::from_str(value.trim()).map_err(|_| format!("`{value}` is not a value: give a number or true or false"))?;
    let sc = common::scripts(ctx);
    sc.laws_with(&[(name.clone(), v.clone())])?;
    if name == "cover_sight_on" && v == true && ctx.db.land().id().find(0).is_none() {
        return Err(NO_COVER_LAND.into());
    }
    let old = sc.law_value(&name).map(|o| o.to_string()).unwrap_or_default();
    let class = sc.value_only(&name);
    // The compiled script is laid over in place below: no reference is held across it.
    drop(sc);
    let new = v.to_string();
    if name == "seen_ranges" && old != new {
        for look in ctx.db.last_look().iter().map(|look| look.id).collect::<Vec<_>>() {
            ctx.db.last_look().id().delete(look);
        }
    }
    let law_rev = common::set_law_override(ctx, &name, &new);
    let how = match class {
        Some(class) => {
            let _v = spacetimedb::log_stopwatch::LogStopwatch::new("set_world_law.value_only");
            // The values laid over the compiled script; a derived check refuses the value here
            // and the reducer's error rolls every row back.
            let sc = common::try_scripts(ctx)?;
            match class {
                living_rules::script::ValueOnly::Delivery => {}
                living_rules::script::ValueOnly::Cover => {
                    // A land without its cover geometry derives it (`geometry`): cover is in
                    // force, for everyone at once, when every band is kept.
                    let laws = common::laws(ctx);
                    geometry::ensure(ctx, laws.cover_sight_on);
                    common::publish_cover_law(ctx, laws);
                }
                living_rules::script::ValueOnly::Gaze => {
                    if !sc.gaze_enabled() {
                        attention::clear_projection(ctx);
                    }
                }
            }
            "value only"
        }
        None => {
            let source = ctx.db.script().name().find("skills".to_string()).map(|s| s.source).ok_or("no script installed")?;
            // Its install refuses a value the laws cannot run with; the reducer's error rolls the row back.
            install_source(ctx, source)?;
            "installed"
        }
    };
    let now = common::now_ms(ctx);
    let revision = ctx.db.script().name().find("skills".to_string()).map(|s| s.revision).unwrap_or(0);
    ctx.db.law_change().insert(LawChange { id: 0, name: name.clone(), old: old.clone(), new: new.clone(), at_ms: now, by: ctx.sender(), revision });
    common::chronicle(ctx, now, "law", 0, 0, (0.0, 0.0), format!("the world's law {name} changed from {old} to {new} (law revision {law_rev}, {how}, script revision {revision})"));
    log::info!("set_world_law: {name} {old} -> {new} (law revision {law_rev}, {how}, script revision {revision})");
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
            crate::perception::answers_changed();
        } else {
            ctx.db.know_how().id().update(KnowHow { technique: new, ..k });
            crate::perception::answers_changed();
        }
        n += 1;
    }
    for a in ctx.db.artifact().iter().filter(|a| renamed(&a.topic).is_some()).collect::<Vec<_>>() {
        let topic = renamed(&a.topic).unwrap_or_default();
        ctx.db.artifact().id().update(Artifact { topic, ..a });
        n += 1;
    }
    if n > 0 {
        // What anyone knows how to do may read otherwise to the `perceived_of` law.
        crate::perception::knowledge_changed(ctx, None);
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
    brain::reset_sight_profile();
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
    act::die(ctx, id, &cause, common::now_ms(ctx), 0, living_rules::outcome::death::OTHER);
    perception::fail_for_test(ctx, 4, "kill")
}

/// Admin support: set a living body's health to `hp` (above 0; more than its maximum is its
/// maximum). Nothing perceives it as care: the body just has that health. Every use is a
/// chronicle line of kind `admin` ("admin set <name>'s health 41 -> 100"). Trial timelines are its
/// only user (an arena's meetings start at full health: docs/COMBAT_MIND.md §5.4); refused for
/// players and minds like every admin reducer.
#[spacetimedb::reducer]
pub fn admin_set_vitals(ctx: &ReducerContext, id: u32, hp: f32) -> Result<(), String> {
    require_admin(ctx)?;
    if !hp.is_finite() || hp <= 0.0 {
        return Err("health must be above 0 (a death is `kill`)".into());
    }
    let now = common::now_ms(ctx);
    let c = ctx.db.character().id().find(id).filter(|c| c.alive).ok_or("no living character with that id")?;
    let mut v = ctx.db.vitals().id().find(id).ok_or("no vitals for that character")?;
    common::settle(ctx, &mut v, now);
    let before = v.hp;
    v.hp = hp.min(v.max_hp);
    v.rate_key = 0;
    let after = v.hp;
    ctx.db.vitals().id().update(v);
    combat::refresh_band(ctx, id, now);
    perception::health_moved(ctx, id, now);
    let at = ctx.db.body().id().find(id).map(|b| common::pos(&b, now)).unwrap_or((0.0, 0.0));
    common::chronicle(ctx, now, "admin", id, 0, at, format!("admin set {}'s health {before:.0} -> {after:.0}", c.name));
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
    ctx.db.structure().insert(Structure { id: 0, kind, x: p.0 + 0.8, y: p.1, chunk: living_rules::map::chunk_of(p.0 + 0.8, p.1), owner: near, built_ms: now, lit_until_ms: 0 });
    Ok(())
}

/// Test support: place a resource node of a kind the world's script has (`resources()`) beside
/// a character, `dx` tiles east and `dy` south of it, holding `max` (0: the kind's own `max`).
/// `pool` names the node whose stock it shares (0: its own).
#[spacetimedb::reducer]
pub fn place_resource(ctx: &ReducerContext, near: u32, kind: String, dx: f32, dy: f32, max: f32, pool: u64) -> Result<(), String> {
    require_admin(ctx)?;
    if !living_rules::catalog::is_resource(&kind) {
        return Err(format!("no resource kind {kind}"));
    }
    if pool != 0 && ctx.db.resource_node().id().find(pool).is_none() {
        return Err(format!("no resource node {pool}"));
    }
    let now = common::now_ms(ctx);
    let b = ctx.db.body().id().find(near).ok_or("no such body")?;
    let p = common::pos(&b, now);
    let (x, y) = (p.0 + dx, p.1 + dy);
    let sc = common::scripts(ctx);
    let max = if max > 0.0 { max } else { sc.tables().number("resources", &kind, "max").unwrap_or(5.0) as f32 };
    let regen = sc.regrow_per_min(&kind, 0.5) as f32;
    common::invalidate_resources(ctx, None);
    ctx.db.resource_node().insert(ResourceNode { id: 0, kind, x, y, chunk: living_rules::map::chunk_of(x, y), amount: max, max, regen, at_ms: now, pool });
    Ok(())
}

/// Test support: install a graph on any character.
#[spacetimedb::reducer]
pub fn set_behavior(ctx: &ReducerContext, id: u32, graph: String) -> Result<(), String> {
    require_admin(ctx)?;
    mind::set_graph(ctx, id, &graph, "test", "test", common::now_ms(ctx)).map(|_| ())
}

/// How far (tiles) `place_near` and `place_at` look for a free walkable tile.
const PLACE_RADIUS: f32 = 6.0;

/// The nearest walkable tile within [`PLACE_RADIUS`] of `want` that no other body stands on
/// (bodies of the chunks around it, through the `body.chunk` index), or a refusal.
fn free_spot(ctx: &ReducerContext, id: u32, want: (f32, f32), exact: bool, from: Option<(f32, f32)>, now: u64) -> Result<(f32, f32), String> {
    let taken: std::collections::HashSet<(i32, i32)> = common::creatures_near(ctx, want, PLACE_RADIUS + 1.5, now)
        .into_iter()
        .filter(|c| c.id != id)
        .map(|c| (c.pos.0.floor() as i32, c.pos.1.floor() as i32))
        .collect();
    common::map(ctx)
        .nearest_free(want.0, want.1, PLACE_RADIUS, exact, from, |x, y| taken.contains(&(x, y)))
        .ok_or_else(|| format!("no free walkable tile within {PLACE_RADIUS} m of ({:.1}, {:.1})", want.0, want.1))
}

/// Test support: move a character next to another: 1 tile east of it when that tile is
/// walkable and no one stands there, else the nearest free tile of the ground walkable from
/// the target within [`PLACE_RADIUS`].
#[spacetimedb::reducer]
pub fn place_near(ctx: &ReducerContext, id: u32, near: u32) -> Result<(), String> {
    require_admin(ctx)?;
    let now = common::now_ms(ctx);
    let t = ctx.db.body().id().find(near).ok_or("no such body")?;
    let p = common::pos(&t, now);
    let at = free_spot(ctx, id, (p.0 + 1.0, p.1), true, Some(p), now)?;
    motion::place(ctx, id, at, now)
}

/// Test support: put a character at rest on the centre of the nearest walkable tile to a
/// point (tiles) that no other body stands on, within [`PLACE_RADIUS`].
#[spacetimedb::reducer]
pub fn place_at(ctx: &ReducerContext, id: u32, x: f32, y: f32) -> Result<(), String> {
    require_admin(ctx)?;
    let now = common::now_ms(ctx);
    let at = free_spot(ctx, id, (x, y), false, None, now)?;
    motion::place(ctx, id, at, now)?;
    perception::fail_for_test(ctx, 3, "place_at")
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

/// Benchmark support (a fixture, no game rule; docs/BATTLE_LAWS.md): `spawn_battle`'s packed
/// battle, its `n` fighters in `sides` sides (2-4) that fight each other and leave bystanders be.
/// Each side is a community (`Side A`, `Side B`, …); an open stance record each way between every
/// two sides says `enemy`, so a fighter's target, the nearest person of `relation: enemy`, is
/// someone of another side (residents of no side are not enemies). The side is the fighter's
/// membership, and its name's prefix (`A12`), for a client that tints by side.
#[spacetimedb::reducer]
pub fn spawn_battle_sides(ctx: &ReducerContext, n: u32, sides: u32) -> Result<(), String> {
    use spacetimedb::rand::Rng;
    require_admin(ctx)?;
    let sides = sides.clamp(2, 4) as usize;
    let now = common::now_ms(ctx);
    let map = common::map(ctx);
    let spot = if ctx.db.land().id().find(0).is_some() { let a = island::arrival(ctx); (a.0, a.1 - 20.0) } else { (55.0, 60.0) };
    let center = map.nearest_walkable(spot.0, spot.1).ok_or("no room")?;
    let letters = ["A", "B", "C", "D"];
    let ids: Vec<u32> = (0..sides)
        .map(|i| {
            let name = format!("Side {}", letters[i]);
            match ctx.db.community().iter().find(|c| c.name == name) {
                Some(c) => c.id,
                None => ctx.db.community().insert(Community { id: 0, name, founder: 0, founded_ms: now, home_x: center.0, home_y: center.1 }).id,
            }
        })
        .collect();
    for (i, a) in ids.iter().enumerate() {
        for (j, b) in ids.iter().enumerate() {
            if i != j {
                let parties = [(living_rules::records::HOLDER.to_string(), living_rules::records::COMMUNITY | *a as u64), (living_rules::records::TOWARD.to_string(), living_rules::records::COMMUNITY | *b as u64)];
                let mut terms = serde_json::Map::new();
                terms.insert("label".into(), serde_json::json!("enemy"));
                terms.insert("value".into(), serde_json::json!(-50.0));
                // Due never (`u64::MAX`): record housekeeping drops every record with `due_ms <= now`.
                crate::records::make(ctx, "stance", "open", 0, &parties, &terms, u64::MAX, now);
            }
        }
    }
    let mut made = 0;
    for _ in 0..n * 30 {
        if made >= n {
            break;
        }
        let p = (center.0 + ctx.rng().gen_range(-7.0f32..7.0), center.1 + ctx.rng().gen_range(-7.0f32..7.0));
        if !map.free(p.0, p.1) {
            continue;
        }
        let side = made as usize % sides;
        let id = seed::spawn_creature(ctx, &format!("{}{}", letters[side], made / sides as u32 + 1), "person", ctx.database_identity(), false, p, now);
        common::inv_add(ctx, id as u64, "spear", 1);
        ctx.db.membership().insert(Membership { id: 0, community: ids[side], member: id, since_ms: now });
        let defend = if id % 2 == 0 { "dodge" } else { "block" };
        let graph = format!(
            r#"{{"first":{{"label":"combat","children":[{{"if":{{"cond":{{"threatened":true}},"then":{{"do":{{"skill":"{defend}"}}}}}}}},{{"do":{{"skill":"attack","target":{{"nearest":{{"kind":"person","relation":"enemy"}}}}}}}}]}}}}"#
        );
        mind::set_graph(ctx, id, &graph, "fight", "battle", now)?;
        made += 1;
    }
    crate::perception::knowledge_changed(ctx, None);
    Ok(())
}

/// Diagnostic fixture (a test, no game rule; docs/BLOW_ORDER.md): two identical spear duellists
/// `gap` tiles apart on an east–west line at (`dx`, `dy`) from `spawn_battle`'s spot, each
/// attacking the other by id. The second is the first's clone: the same sex, age, genes and ways,
/// vitals, breath and items. `between` people are made (and killed 60 tiles north) between the
/// two, so their ids differ by `between + 1` (their combat-cadence class). `low_west`: the lower id
/// stands west. The west one's graph is installed first, whatever its id (a graph's install wakes
/// its character), or the east one's with `east_first`. `hp` above 0 sets both healths (5: one
/// spear blow kills, so the first blow resolved decides). `hold_east`: the east one only waits (`{"wait":120}`) until its attack graph is
/// installed with `set_behavior` (an offset start). `defend`: "" none, else the skill each uses
/// when threatened. Refused where either spot is not free.
#[spacetimedb::reducer]
#[allow(clippy::too_many_arguments)]
pub fn spawn_duel(ctx: &ReducerContext, gap: f32, dx: f32, dy: f32, between: u32, low_west: bool, hold_east: bool, defend: String, hp: f32, east_first: bool) -> Result<(), String> {
    require_admin(ctx)?;
    let now = common::now_ms(ctx);
    let map = common::map(ctx);
    let spot = if ctx.db.land().id().find(0).is_some() { let a = island::arrival(ctx); (a.0, a.1 - 20.0) } else { (55.0, 60.0) };
    let c = map.nearest_walkable(spot.0, spot.1).ok_or("no room")?;
    let (cx, cy) = (c.0 + dx, c.1 + dy);
    let west = (cx - gap / 2.0, cy);
    let east = (cx + gap / 2.0, cy);
    for p in [west, east, ((west.0 + east.0) / 2.0, cy)] {
        if !map.free(p.0, p.1) {
            return Err(format!("({:.1}, {:.1}) is not free", p.0, p.1));
        }
    }
    let (lo_at, hi_at) = if low_west { (west, east) } else { (east, west) };
    let age = common::life_of(ctx, "person").age_at(0.25, common::pace(&common::world(ctx)));
    let sex = Some(living_rules::sex::Sex::Male);
    let me = ctx.database_identity();
    let lo = seed::spawn_sexed(ctx, "DuelLow", "person", me, false, lo_at, now, age, (0, 0), sex);
    let far = map.nearest_walkable(cx, cy + 60.0).ok_or("no room for the fillers")?;
    for i in 0..between {
        let f = seed::spawn_sexed(ctx, &format!("Filler{}", i + 1), "person", me, false, far, now, age, (0, 0), sex);
        act::die(ctx, f, "a duel fixture's filler", now, 0, living_rules::outcome::death::OTHER);
    }
    let hi = seed::spawn_sexed(ctx, "DuelHigh", "person", me, false, hi_at, now, age, (0, 0), sex);
    let g = ctx.db.genome().id().find(lo).ok_or("no genome")?;
    ctx.db.genome().id().update(Genome { id: hi, ..g });
    let v = ctx.db.vitals().id().find(lo).ok_or("no vitals")?;
    let v = if hp > 0.0 { Vitals { hp: hp.min(v.max_hp), ..v } } else { v };
    ctx.db.vitals().id().update(Vitals { id: lo, ..v.clone() });
    ctx.db.vitals().id().update(Vitals { id: hi, ..v });
    let (w, e) = if low_west { (lo, hi) } else { (hi, lo) };
    let order = if east_first { [(e, w), (w, e)] } else { [(w, e), (e, w)] };
    for (me_id, other) in order {
        common::inv_add(ctx, me_id as u64, "spear", 1);
        let guard = if defend.is_empty() { String::new() } else { format!(r#"{{"if":{{"cond":{{"threatened":true}},"then":{{"do":{{"skill":"{defend}"}}}}}}}},"#) };
        let graph = format!(r#"{{"first":{{"label":"combat","children":[{guard}{{"do":{{"skill":"attack","target":{{"id":{other}}}}}}}]}}}}"#);
        let graph = if hold_east && me_id == e { r#"{"wait":120}"#.to_string() } else { graph };
        mind::set_graph(ctx, me_id, &graph, "fight", "duel", now)?;
    }
    log::info!("spawn_duel: low {lo} high {hi} west {w} east {e} gap {gap} at ({cx:.2}, {cy:.2}) between {between} hold_east {hold_east} defend '{defend}' hp {hp} east_first {east_first}");
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
        crate::perception::knowledge_changed(ctx, None);
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
    crate::floor::ready(ctx)?;
    join_with(ctx, name, None)
}

/// `join` with the body's sex chosen (docs/LIVING_CORE.md, "Body sex"): `sex` is "f" or "m"
/// (also "female", "male", any case); anything else is refused and nothing is made. A reducer
/// beside `join`, not a new argument to it, so existing clients and bindings keep working
/// (changing an existing reducer's arguments is not a safe module update).
#[spacetimedb::reducer]
pub fn join_as(ctx: &ReducerContext, name: String, sex: String) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    let Some(s) = living_rules::sex::Sex::parse(&sex) else {
        return Err(format!("sex must be \"f\" or \"m\", not {sex:?}"));
    };
    join_with(ctx, name, Some(s))
}

fn join_with(ctx: &ReducerContext, name: String, sex: Option<living_rules::sex::Sex>) -> Result<(), String> {
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
    let age = common::life_of(ctx, "person").age_at(0.25, common::pace(&common::world(ctx)));
    let id = seed::spawn_sexed(ctx, &name, "person", ctx.sender(), false, at, now, age, (0, 0), sex);
    perception::set_player(ctx, ctx.sender(), id);
    mind::set_graph(ctx, id, WAITING_GRAPH, WAITING, "human", now)?;
    // What the world gives every newcomer (the seed's `newcomer`): nothing of anyone before.
    seed::newcomer_kit(ctx, id, now);
    presence::start(ctx, id, ctx.sender(), now);
    combat::invalidate_humans(ctx);
    // What the newcomer perceives is there from the first frame, not after a sweep.
    perception::sweep_now(ctx, id, ctx.sender(), now);
    perception::fail_for_test(ctx, 5, "join")
}

/// Test support (trials, docs/TRIALS.md): a newcomer as `join` makes one — the same arrival
/// point and the seed's newcomer kit, the species' instinct graph — but thought for by the
/// admin's minds (`ai`), as every resident is; a trial's mind service thinks only for the
/// characters `LIVING_ONLY` names. It has no background; a caller that wants the mind to write
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
/// a mind's decisions (see `acts.rs`), replacing whatever the player commanded before once it
/// passes its checks (`act_replace_checks`); any other node becomes the character's behavior.
/// Each call spends an input as moving does (`act_input_cost`; "too many inputs" when spent).
#[spacetimedb::reducer]
pub fn human_act(ctx: &ReducerContext, node: String) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    let me = my_character(ctx)?;
    latency::nav(ctx, me.id, "human_act", 0, format_args!(""));
    let g = living_rules::graph::parse(&node)?;
    let now = common::now_ms(ctx);
    // Every command is an input, as a movement or a skill use is (`act_input_cost`).
    acts::spend_input(ctx, me.id, now)?;
    if let living_rules::graph::Node::Do(a) = &g.root {
        if living_rules::acts::not_an_act(&a.skill, common::scripts(ctx).shapes()).is_none() {
            acts::submit_player(ctx, me.id, &[g.to_json()], "human", now);
            return Ok(());
        }
    }
    // It runs once: when it ends, done or failed, the character waits for its person again
    // (`command_done`).
    mind::set_graph(ctx, me.id, &g.to_json(), COMMAND, "human", now).map(|_| ())
}

/// A played character's plan while it waits for its person, and the graph it waits with.
pub(crate) const WAITING: &str = "waiting for you";
pub(crate) const WAITING_GRAPH: &str = r#"{"wait":30}"#;
/// The plan of a command its person gave with `human_act`.
const COMMAND: &str = "your command";

/// A played character's graph has run to its end (done or failed). A command from its person
/// is over: the character waits for them again, instead of starting the command over.
pub(crate) fn command_done(ctx: &ReducerContext, id: u32, now: u64) {
    use crate::tables::brain as _;
    if ctx.db.brain().id().find(id).is_some_and(|b| b.plan == COMMAND && b.source == "human") {
        if let Err(e) = mind::set_graph(ctx, id, WAITING_GRAPH, WAITING, "human", now) {
            log::warn!("character {id}: could not go back to waiting: {e}");
        }
    }
}

/// Face a direction (screen axes: +x east, +y south; any length), or release the look (`0, 0`):
/// the player's look. It turns the body's facing (`body.face_*` over `body.heading`,
/// `common::facing_at`): what facing sight, hearing's sides and a guard read. Standing, the body
/// turns where it stands at its turn rate. Walking (`human_move`), the travel is untouched (the
/// keys' way at full speed) and the facing turns toward the look at most the `look_walk_deg` law
/// off the way; when the body stops it finishes the turn. Released, facing returns to the way
/// it walks. A look within the
/// `look_slack_deg` law of the one held is free; any other change spends a token of the movement
/// input bucket (the `input_hz`/`input_burst` laws, shared with `human_move`), so a client
/// that follows the cursor sends looks freely and only changes write rows.
#[spacetimedb::reducer]
pub fn human_face(ctx: &ReducerContext, dx: f32, dy: f32) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    let me = my_character(ctx)?;
    if !dx.is_finite() || !dy.is_finite() {
        return Err("direction must be finite".into());
    }
    let dir = (dx != 0.0 || dy != 0.0).then_some((dx, dy));
    motion::look(ctx, me.id, dir, common::now_ms(ctx))
}

/// Select Middle (0), Far (1) or Near (2). The scheduled sight sweep applies the new band.
#[spacetimedb::reducer]
pub fn human_gaze(ctx: &ReducerContext, band: u8) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    let me = my_character(ctx)?;
    attention::set(ctx, me.id, living_rules::sight::GazeBand::try_from(band)?, common::now_ms(ctx))
}

/// Move in a direction (screen axes: +x east, +y south; any length) or stop (`0, 0`), at a
/// walk or a run. Steering carries it out with the same physics as everyone's movement;
/// it replaces whatever the character was doing. Send it when the intent changes (a key
/// pressed or released, the stick turned); repeats of the current intent are free, and
/// changes are rate-limited by the `input_hz`/`input_burst` laws.
#[spacetimedb::reducer]
pub fn human_move(ctx: &ReducerContext, dx: f32, dy: f32, run: bool) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    let me = my_character(ctx)?;
    latency::nav(ctx, me.id, "human_move", 0, format_args!(""));
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
        // A skill done on the move (`on_the_move`: a wave, a nod) carries on as one walks.
        let on_the_move = |a: &Activity| living_rules::catalog::skill(&a.skill).is_some_and(|k| k.on_the_move);
        if let Some(a) = ctx.db.activity().id().find(me.id).filter(|a| a.skill != "wait" && !(guard(a) && a.node == act::PLAYER) && !on_the_move(a)) {
            act::cancel_moved(ctx, a, now);
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

/// Say a line aloud (the `say` way): to `to`, or to the room with 0. Kept for clients from
/// before `human_speak`.
#[spacetimedb::reducer]
pub fn human_say(ctx: &ReducerContext, text: String, to: u32) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    let me = my_character(ctx)?;
    speech::speak(ctx, me.id, &text, to, "say", common::now_ms(ctx))
}

/// Say a line in a way of speaking (`speech_card.name`; "" is `say`): to `to`, or to the room
/// with 0. A line the way refuses comes back as the reducer's error, in the world's words.
#[spacetimedb::reducer]
pub fn human_speak(ctx: &ReducerContext, text: String, to: u32, way: String) -> Result<(), String> {
    crate::floor::ready(ctx)?;
    let me = my_character(ctx)?;
    speech::speak(ctx, me.id, &text, to, &way, common::now_ms(ctx))
}
