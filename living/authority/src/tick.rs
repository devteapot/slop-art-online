//! Scheduled work. `tick` runs at 60 Hz and touches only due rows (motion events,
//! activity timers, wakes) plus one sixtieth of the population for their 1 Hz behavior
//! evaluation. `housekeeping` runs at 1 Hz for slow world processes.

use crate::tables::*;
use crate::{act, brain, common, motion, seed};
use spacetimedb::rand::Rng;
use spacetimedb::{ReducerContext, Table};
use std::collections::HashSet;

#[spacetimedb::reducer]
pub fn tick(ctx: &ReducerContext, _t: TickTimer) -> Result<(), String> {
    if ctx.sender() != ctx.database_identity() {
        return Err("tick is scheduled only".into());
    }
    let w = common::world(ctx);
    if w.paused {
        return Ok(());
    }
    let now = common::now_ms(ctx);
    let mut k = common::clock(ctx);
    if k.last_ms != 0 {
        k.max_gap_ms = k.max_gap_ms.max(now.saturating_sub(k.last_ms) as u32);
    }
    k.tick += 1;
    k.last_ms = now;
    let slot = (k.tick % 60) as u8;
    let _timer = k.profile.then(|| spacetimedb::log_stopwatch::LogStopwatch::new("tick"));
    ctx.db.clock().id().update(k);

    // 1. Bodies reaching a waypoint or chunk boundary.
    let due: Vec<Body> = ctx.db.body().next_ms().filter(..=now).collect();
    let mut motions = 0u64;
    for b in due {
        let id = b.id;
        motions += 1;
        if motion::advance(ctx, b, now) {
            if let Some(a) = ctx.db.activity().id().find(id) {
                if a.phase == 0 {
                    act::progress(ctx, a, now);
                }
            }
        }
    }
    // 2. Activity timers.
    let due: Vec<Activity> = ctx.db.activity().ends_ms().filter(..=now).collect();
    for a in due {
        act::progress(ctx, a, now);
    }
    // 3. Wakes and this slot's evaluations.
    let mut done = HashSet::new();
    for _ in 0..3 {
        let wakes: Vec<u32> = ctx.db.wake().iter().map(|w| w.id).collect();
        if wakes.is_empty() {
            break;
        }
        for id in wakes {
            ctx.db.wake().id().delete(id);
            if done.insert(id) {
                brain::evaluate(ctx, id, now);
            }
        }
    }
    let slot_ids: Vec<u32> = ctx.db.mind_state().slot().filter(slot).map(|m| m.id).collect();
    for id in slot_ids {
        if done.insert(id) {
            brain::evaluate(ctx, id, now);
        }
    }
    if motions > 0 {
        let mut k = common::clock(ctx);
        k.motions += motions;
        ctx.db.clock().id().update(k);
    }
    Ok(())
}

const NAMES: &[&str] = &[
    "Ada", "Bryn", "Cato", "Dara", "Eli", "Faye", "Gil", "Hana", "Ivo", "Juno", "Kit", "Lark", "Moss", "Nell", "Odo", "Pia",
    "Quill", "Rhea", "Sol", "Tam", "Uma", "Vale", "Wren", "Yara", "Zev", "Ash", "Bee", "Cove", "Dell", "Ember", "Fern", "Gale",
    "Hollis", "Ione", "Jory", "Kestrel", "Linden", "Marlo", "Nia", "Orrin", "Perrin", "Rook", "Sage", "Teal", "Ulla", "Vesper",
];

fn birth(ctx: &ReducerContext, a: u32, b: u32, now: u64) {
    let parents: Vec<Character> = [a, b].iter().filter_map(|id| ctx.db.character().id().find(*id)).filter(|c| c.alive).collect();
    let (Some(first), Some(pa), Some(pb)) = (parents.first(), ctx.db.character().id().find(a), ctx.db.character().id().find(b)) else {
        common::chronicle(ctx, now, "family", a, b, (0.0, 0.0), format!("The child of {} and {} was never born", common::name_of(ctx, a), common::name_of(ctx, b)));
        return;
    };
    let Some(at) = ctx.db.body().id().find(first.id).map(|bd| common::pos(&bd, now)) else { return };
    let used: Vec<String> = ctx.db.character().kind().filter("person").map(|c| c.name).collect();
    let pick = ctx.rng().gen_range(0..NAMES.len());
    let name = (0..NAMES.len()).map(|i| NAMES[(pick + i) % NAMES.len()]).find(|n| !used.iter().any(|u| u == n)).map(String::from).unwrap_or_else(|| format!("Child{}", used.len()));
    let controller = if first.ai { first.controller } else { common::world(ctx).admin };
    let id = seed::spawn_with(ctx, &name, "person", controller, true, at, now, 0.0, (pa.id, pb.id));
    common::chronicle(ctx, now, "birth", id, first.id, at, format!("{name} was born to {} and {}", pa.name, pb.name));
    for p in &parents {
        crate::perceive::percept(ctx, p, now, "birth", id, p.id, at, format!("Your child {name} was born."), 1.0);
    }
    crate::perceive::witnessed(ctx, now, at, "birth", id, first.id, &format!("{name} was born to {} and {}", pa.name, pb.name), 0.5, &[a, b, id]);
    if let Some(mut s) = ctx.db.stats().id().find(0) {
        s.births += 1;
        ctx.db.stats().id().update(s);
    }
    crate::perceive::request_deliberation(ctx, id, "You were just born into the valley. You know only your parents' faces.", now);
}

#[spacetimedb::reducer]
pub fn housekeeping(ctx: &ReducerContext, _t: SlowTimer) -> Result<(), String> {
    if ctx.sender() != ctx.database_identity() {
        return Err("housekeeping is scheduled only".into());
    }
    let w = common::world(ctx);
    if w.paused {
        return Ok(());
    }
    let now = common::now_ms(ctx);
    let mut k = common::clock(ctx);
    let hour = common::hour(&w, now) as u8;
    if hour != k.last_hour {
        let day = living_rules::day_of(now, w.epoch_ms, w.day_ms);
        if hour == 20 {
            common::chronicle(ctx, now, "time", 0, 0, (0.0, 0.0), format!("Night falls on day {day}."));
        } else if hour == 6 {
            common::chronicle(ctx, now, "time", 0, 0, (0.0, 0.0), format!("Dawn of day {day}."));
        }
        k.last_hour = hour;
    }

    // Wildlife renewal: animals breed slowly while below their seed population.
    let mut alive_people = 0u32;
    let mut deer = Vec::new();
    let mut wolves = 0u32;
    for c in ctx.db.character().iter().filter(|c| c.alive) {
        match c.kind.as_str() {
            "person" => alive_people += 1,
            "deer" => deer.push(c.id),
            "wolf" => wolves += 1,
            _ => {}
        }
    }
    let seed: seed::Seed = serde_json::from_str(seed::VALLEY).map_err(|e| e.to_string())?;
    let map = common::map(ctx);
    if (deer.len() as u32) < seed.animals.deer && ctx.rng().gen_range(0..40) == 0 {
        let at = if let Some(parent) = deer.get(ctx.rng().gen_range(0..deer.len().max(1))).and_then(|id| ctx.db.body().id().find(*id)) {
            map.nearest_walkable(parent.x + 1.0, parent.y + 1.0)
        } else {
            seed::animal_spot(ctx, &map, "deer")
        };
        if let Some(at) = at {
            seed::spawn_animal(ctx, "deer", at, now);
        }
    }
    if wolves < seed.animals.wolf && ctx.rng().gen_range(0..240) == 0 {
        if let Some(at) = seed::animal_spot(ctx, &map, "wolf") {
            seed::spawn_animal(ctx, "wolf", at, now);
        }
    }

    // Births.
    let due: Vec<Expecting> = ctx.db.expecting().due_ms().filter(..=now).collect();
    for e in due {
        ctx.db.expecting().id().delete(e.id);
        birth(ctx, e.a, e.b, now);
    }
    for o in ctx.db.bond_offer().iter().filter(|o| now.saturating_sub(o.at_ms) > 180_000).map(|o| o.id).collect::<Vec<_>>() {
        ctx.db.bond_offer().id().delete(o);
    }

    // Bound the story feed.
    let n = ctx.db.chronicle().count();
    if n > 4_000 {
        let old: Vec<u64> = ctx.db.chronicle().at_ms().filter(0u64..).take((n - 3_500) as usize).map(|c| c.id).collect();
        for id in old {
            ctx.db.chronicle().id().delete(id);
        }
    }

    let prev = ctx.db.stats().id().find(0);
    let deaths = ctx.db.character().iter().filter(|c| !c.alive && c.kind == "person").count() as u32;
    let row = Stats {
        id: 0,
        at_ms: now,
        ticks: k.tick,
        evals: k.evals,
        motions: k.motions,
        completions: k.completions,
        percepts: k.percepts,
        deliberations: k.deliberations,
        alive_people,
        alive_animals: deer.len() as u32 + wolves,
        births: prev.as_ref().map(|p| p.births).unwrap_or(0),
        deaths,
        max_tick_gap_ms: k.max_gap_ms,
    };
    k.max_gap_ms = 0;
    ctx.db.clock().id().update(k);
    if prev.is_some() {
        ctx.db.stats().id().update(row);
    } else {
        ctx.db.stats().insert(row);
    }
    Ok(())
}
