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
    let k_tick = k.tick;
    let _timer = k.profile.then(|| spacetimedb::log_stopwatch::LogStopwatch::new("tick"));
    ctx.db.clock().id().update(k);

    // 1. Steering updates that are due (events and cadence of moving bodies).
    let due: Vec<Body> = ctx.db.body().next_ms().filter(..=now).collect();
    let mut motions = 0u64;
    for b in due {
        let id = b.id;
        motions += 1;
        if let Some(ev) = motion::advance(ctx, b, now) {
            act::on_motion(ctx, id, ev, now);
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
    // Combat cadence: creatures in a fight are evaluated about 15 times per second,
    // staggered across ticks so a battle does not land in one tick.
    let fighting: Vec<u32> = ctx.db.mind_state().fast_until().filter(now..).map(|m| m.id).filter(|id| (*id as u64 + k_tick) % 4 == 0).collect();
    for id in fighting {
        if done.insert(id) {
            brain::evaluate(ctx, id, now);
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

/// A character enters a new stage of life.
fn grew(ctx: &ReducerContext, c: &Character, stage: u8, now: u64) {
    let Some(mut row) = ctx.db.character().id().find(c.id) else { return };
    row.stage = stage;
    ctx.db.character().id().update(row);
    // A person who outgrows infancy starts from a child's way of life (theirs to change).
    if c.kind == "person" && c.stage == 0 && stage == 1 {
        seed::give_repertoire(ctx, c.id, "child", now);
    }
    let at = ctx.db.body().id().find(c.id).map(|b| common::pos(&b, now)).unwrap_or((0.0, 0.0));
    let (story, feel) = match (c.kind.as_str(), stage) {
        ("person", 1) => (format!("{} is no longer a baby", c.name), "You can walk, talk and do things on your own now, though you are still small."),
        ("person", 2) => (format!("{} has grown up", c.name), "You have grown up: you are an adult now."),
        ("person", 3) => (format!("{} has grown old", c.name), "You are growing old: your body tires sooner and heals slower."),
        (_, 2) => (String::new(), "You are grown."),
        _ => (String::new(), ""),
    };
    if !story.is_empty() {
        common::chronicle(ctx, now, "life", c.id, 0, at, story);
    }
    if !feel.is_empty() {
        if let Some(fresh) = ctx.db.character().id().find(c.id) {
            crate::perceive::percept(ctx, &fresh, now, "life", c.id, 0, at, feel.to_string(), 0.8);
            crate::perceive::request_deliberation(ctx, c.id, feel, now);
        }
    }
}

fn birth(ctx: &ReducerContext, a: u32, b: u32, now: u64) {
    let parents: Vec<Character> = [a, b].iter().filter_map(|id| ctx.db.character().id().find(*id)).filter(|c| c.alive).collect();
    let (Some(first), Some(pa), Some(pb)) = (parents.first(), ctx.db.character().id().find(a), ctx.db.character().id().find(b)) else {
        common::chronicle(ctx, now, "family", a, b, (0.0, 0.0), format!("The child of {} and {} was never born", common::name_of(ctx, a), common::name_of(ctx, b)));
        return;
    };
    let Some(at) = ctx.db.body().id().find(first.id).map(|bd| common::pos(&bd, now)) else { return };
    let kind = first.kind.clone();
    let litter = ctx.rng().gen_range(1..=common::life_of(&kind).litter.max(1));
    let controller = if first.ai { first.controller } else { common::world(ctx).admin };
    let mut names = Vec::new();
    for _ in 0..litter {
        let id = if kind == "person" {
            let used: Vec<String> = ctx.db.character().kind().filter("person").map(|c| c.name).collect();
            let pick = ctx.rng().gen_range(0..NAMES.len());
            let name = (0..NAMES.len()).map(|i| NAMES[(pick + i) % NAMES.len()]).find(|n| !used.iter().any(|u| u == n)).map(String::from).unwrap_or_else(|| format!("Child{}", used.len()));
            seed::spawn_with(ctx, &name, "person", controller, true, at, now, 0.0, (pa.id, pb.id))
        } else {
            seed::spawn_young(ctx, &kind, at, now, (pa.id, pb.id))
        };
        names.push((id, common::name_of(ctx, id)));
    }
    let list = names.iter().map(|(_, n)| n.clone()).collect::<Vec<_>>().join(" and ");
    if kind == "person" {
        common::chronicle(ctx, now, "birth", names[0].0, first.id, at, format!("{list} was born to {} and {}", pa.name, pb.name));
        for p in &parents {
            crate::perceive::percept(ctx, p, now, "birth", names[0].0, p.id, at, format!("Your child {list} was born."), 1.0);
        }
        crate::perceive::witnessed(ctx, now, at, "birth", names[0].0, first.id, &format!("{list} was born to {} and {}", pa.name, pb.name), 0.5, &[a, b, names[0].0]);
    } else {
        for p in &parents {
            crate::perceive::percept(ctx, p, now, "birth", names[0].0, p.id, at, format!("Your young were born: {list}."), 1.0);
        }
    }
    if let Some(mut s) = ctx.db.stats().id().find(0) {
        s.births += names.len() as u32;
        ctx.db.stats().id().update(s);
    }
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
            // Each person plans the day ahead (work, meals, learning, time with others).
            let season = common::season(ctx, now);
            let planners: Vec<u32> = ctx.db.character().kind().filter("person").filter(|c| c.alive && c.ai).map(|c| c.id).collect();
            for id in planners {
                crate::perceive::request_deliberation(ctx, id, &format!("Dawn of day {day} ({season}). A new day."), now);
            }
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
    // No re-spawning: animals breed, age and die like everyone else (a species hunted out
    // stays gone). Life stages and deaths of old age, at the world's pace.
    let alive: Vec<Character> = ctx.db.character().iter().filter(|c| c.alive).collect();
    for c in alive {
        let life = common::life_of(&c.kind);
        let age = common::age_days(&c, &w, now);
        if life.fraction(age, common::pace(&w)) >= life.deathline(c.id) {
            crate::act::die(ctx, c.id, "old age", now, 0);
            continue;
        }
        let stage = common::stage_code(life.stage(age, common::pace(&w)));
        if stage != c.stage {
            grew(ctx, &c, stage, now);
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
    for o in ctx.db.trade_offer().iter().filter(|o| now.saturating_sub(o.at_ms) > 240_000).map(|o| o.id).collect::<Vec<_>>() {
        ctx.db.trade_offer().id().delete(o);
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
        hits: k.hits,
        dodged: k.dodged,
        blocked: k.blocked,
        missed: k.missed,
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
