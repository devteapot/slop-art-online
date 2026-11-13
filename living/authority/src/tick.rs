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
    // The outgoing module's last call after an update: no table is touched (common::schema_moved).
    if common::schema_moved("tick") {
        return Ok(());
    }
    let w = common::world(ctx);
    if w.paused {
        return Ok(());
    }
    let now = common::now_ms(ctx);
    let mut k = common::clock(ctx);
    let prev_ms = if k.last_ms != 0 { k.last_ms } else { now };
    if k.last_ms != 0 {
        k.max_gap_ms = k.max_gap_ms.max(now.saturating_sub(k.last_ms) as u32);
    }
    k.tick += 1;
    k.last_ms = now;
    let slot = (k.tick % 60) as u8;
    let k_tick = k.tick;
    common::set_profiling(k.profile);
    common::set_profile_detail(k.profile && common::laws(ctx).profile_detail);
    let _timer = common::span("tick");

    // 1. Steering updates that are due (events and cadence of moving bodies).
    let phase = common::span("tick.motion");
    // By id, each read when its turn comes: an earlier body's update this tick (a push, a
    // death) may have changed or removed it, and a stale copy would overwrite that.
    let due: Vec<u32> = ctx.db.body().next_ms().filter(..=now).map(|b| b.id).collect();
    let mut motions = 0u64;
    for id in due {
        let Some(b) = ctx.db.body().id().find(id).filter(|b| b.next_ms <= now) else { continue };
        motions += 1;
        if let Some(ev) = motion::advance(ctx, b, now) {
            act::on_motion(ctx, id, ev, now);
        }
    }
    drop(phase);
    // Walking regions are worked out ahead of the routes that need them, a slice a tick.
    let phase = common::span("tick.routes");
    motion::warm_routes(ctx);
    drop(phase);
    // 2. Activity timers.
    let phase = common::span("tick.activity");
    // By id too: finishing one activity can end, replace or delete another.
    let due: Vec<u32> = ctx.db.activity().ends_ms().filter(..=now).map(|a| a.id).collect();
    for id in due {
        if let Some(a) = ctx.db.activity().id().find(id).filter(|a| a.ends_ms <= now) {
            act::progress(ctx, a, now);
        }
    }
    drop(phase);
    // Missiles in flight are swept along their paths.
    let phase = common::span("tick.missiles");
    crate::combat::missiles(ctx, now);
    crate::fast::tick(ctx, now);
    drop(phase);
    // What onlookers saw of fights since their last line, for those whose window ended
    // (`witness_fold_ms`, docs/BATTLE_SCALE.md fix 4).
    let phase = common::span("tick.fold");
    crate::fold::flush(ctx, prev_ms, now);
    drop(phase);
    // 3. Wakes and this slot's evaluations.
    let phase = common::span("tick.wakes");
    // Bystanders' wakes held back by `witness_wake_ms` whose window has ended.
    let due_wakes = common::detail_span("wake.bystanders_due");
    common::due_bystander_wakes(ctx, now);
    drop(due_wakes);
    let mut done = HashSet::new();
    for _ in 0..3 {
        let wakes: Vec<u32> = ctx.db.wake().iter().map(|w| w.id).collect();
        if wakes.is_empty() {
            break;
        }
        common::diag(|| "wake:round", 1);
        for id in wakes {
            ctx.db.wake().id().delete(id);
            if done.insert(id) {
                common::diag(|| "eval:wake", 1);
                // While profiling with detail: woken evaluations of those in a fight (on the
                // combat cadence) apart from the rest.
                let _detail = if common::profiling() {
                    let fighting = ctx.db.mind_state().id().find(id).is_some_and(|m| m.fast_until >= now);
                    common::diag(move || if fighting { "eval:wake:fight" } else { "eval:wake:calm" }, 1);
                    common::detail_span(if fighting { "wake.eval.fight" } else { "wake.eval.calm" })
                } else {
                    None
                };
                brain::evaluate(ctx, id, now);
            }
        }
    }
    drop(phase);
    // Combat cadence: creatures in a fight are evaluated about 15 times per second,
    // staggered across ticks so a battle does not land in one tick.
    let phase = common::span("tick.combat");
    let fighting: Vec<u32> = ctx.db.mind_state().fast_until().filter(now..).map(|m| m.id).filter(|id| (*id as u64 + k_tick) % 4 == 0).collect();
    for id in fighting {
        if done.insert(id) {
            common::diag(|| "eval:combat", 1);
            brain::evaluate(ctx, id, now);
        }
    }
    drop(phase);
    // What each player's character perceives (docs/PERCEPTION.md), each every 200 ms.
    let phase = common::span("tick.perception");
    crate::perception::sweep(ctx, now);
    drop(phase);
    // What each player is shown of the others in its scene, at its frame (frame.rs).
    let phase = common::span("tick.frames");
    crate::frame::deliver(ctx, now);
    drop(phase);
    let phase = common::span("tick.slots");
    let slot_ids: Vec<u32> = ctx.db.mind_state().slot().filter(slot).map(|m| m.id).collect();
    for id in slot_ids {
        if done.insert(id) {
            common::diag(|| "eval:slot", 1);
            brain::evaluate(ctx, id, now);
        }
    }
    drop(phase);
    common::count(|k| k.motions += motions);
    // One clock write a tick: its stamp and the counts gathered since the last one (nothing
    // else reads the clock row during the tick).
    common::flush_counts(&mut k);
    ctx.db.clock().id().update(k);
    Ok(())
}

const NAMES: &[&str] = &[
    "Ada", "Bryn", "Cato", "Dara", "Eli", "Faye", "Gil", "Hana", "Ivo", "Juno", "Kit", "Lark", "Moss", "Nell", "Odo", "Pia",
    "Quill", "Rhea", "Sol", "Tam", "Uma", "Vale", "Wren", "Yara", "Zev", "Ash", "Bee", "Cove", "Dell", "Ember", "Fern", "Gale",
    "Hollis", "Ione", "Jory", "Kestrel", "Linden", "Marlo", "Nia", "Orrin", "Perrin", "Rook", "Sage", "Teal", "Ulla", "Vesper",
];

/// Housekeeping calls (one a second) in which every stack is checked once for spoilage.
const SPOIL_SLICES: u32 = 60;

thread_local! {
    /// Rolling spoilage pass: the owner to resume from, the call within the current minute
    /// and the rows to take per call (fixed at the start of each minute).
    static SPOIL: std::cell::Cell<(u64, u32, u64)> = const { std::cell::Cell::new((0, 0, 0)) };
}

thread_local! {
    /// Species kept from dying out by newcomers from beyond the map (`migrate` in species.json).
    static MIGRANTS: Vec<(String, living_rules::species::Migrate)> =
        living_rules::species::parse(&common::species_json())
            .map(|all| all.into_iter().filter_map(|(k, s)| s.migrate.map(|m| (k, m))).collect())
            .unwrap_or_default();
    /// The minute in which migration was last considered.
    static MIGRATION_MINUTE: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}

/// The wilds beyond the map: once a minute, a species that has lived here and is down to
/// fewer than its floor gets a group of newcomers at an edge, unless newcomers (or the
/// world's first animals) came within its interval. When they last came is read from the
/// characters themselves (animals without parents are founders or newcomers), so it
/// survives module updates without a table. Scans the kind's rows only while below the floor.
fn migration(ctx: &ReducerContext, alive: &[(String, u32)], now: u64) {
    let minute = now / 60_000;
    if MIGRATION_MINUTE.with(|m| m.replace(minute)) == minute {
        return;
    }
    MIGRANTS.with(|all| {
        for (kind, m) in all {
            let n = alive.iter().find(|(k, _)| k == kind).map_or(0, |(_, n)| *n);
            if n >= m.below {
                continue;
            }
            // A kind that never lived in this world does not start arriving.
            let Some(last) = ctx.db.character().kind().filter(kind.as_str()).filter(|c| c.parent_a == 0 && c.parent_b == 0).map(|c| c.born_ms).max() else { continue };
            if m.due(n, last, now) {
                crate::seed::migrate(ctx, kind, m, now);
            }
        }
    });
}

/// Food spoils: each minute a share of every perishable stack is lost (rates from the skill
/// script; a storage keeps food three times longer). Owners notice what they lose.
/// The pass rolls through the inventory by owner over the minute's 60 housekeeping calls
/// (an owner's stacks together), so each stack is still checked once a minute but no call
/// walks the whole table; the minute's last call takes whatever is left.
/// Remains whose time is up (`rot` rows due by now) are gone, with what is left in them. Remains
/// holding an artifact stay, as before remains expired. Reads only the due rows.
fn expire_remains(ctx: &ReducerContext, now: u64) {
    let _timer = common::span("housekeeping.remains");
    let due: Vec<Rot> = ctx.db.rot().due_ms().filter(..=now).collect();
    if due.is_empty() {
        return;
    }
    for r in due {
        ctx.db.rot().structure().delete(r.structure);
        let owner = STRUCTURE_BIT | r.structure;
        if ctx.db.artifact().holder().filter(owner).next().is_some() {
            continue;
        }
        for i in ctx.db.inventory().owner().filter(owner).map(|i| i.id).collect::<Vec<_>>() {
            ctx.db.inventory().id().delete(i);
        }
        ctx.db.structure().id().delete(r.structure);
    }
    common::invalidate_structures(ctx);
}

fn spoil(ctx: &ReducerContext, now: u64) {
    let _timer = common::span("housekeeping.spoil");
    let (cursor, call, mut quota) = SPOIL.with(|c| c.get());
    if call == 0 || quota == 0 {
        quota = ctx.db.inventory().count().div_ceil(SPOIL_SLICES as u64).max(1);
    }
    let last = call + 1 >= SPOIL_SLICES;
    let mut rows: Vec<Inventory> = Vec::new();
    let mut resume = u64::MAX;
    for r in ctx.db.inventory().owner().filter(cursor..) {
        if !last && rows.len() as u64 >= quota && rows.last().map_or(true, |p| p.owner != r.owner) {
            resume = r.owner;
            break;
        }
        rows.push(r);
    }
    SPOIL.with(|c| c.set(if last { (0, 0, quota) } else { (resume, call + 1, quota) }));
    let sc = common::scripts(ctx);
    let mut rates: std::collections::HashMap<String, f32> = std::collections::HashMap::new();
    // A carrier's share of the rate by kind (an animal keeps its kill by it), looked up once
    // per owner with something perishable (an owner's stacks come together).
    let mut shares: std::collections::HashMap<String, f32> = std::collections::HashMap::new();
    let mut kept: std::collections::HashMap<String, f32> = std::collections::HashMap::new();
    let mut carrier: (u64, f32) = (u64::MAX, 1.0);
    for mut r in rows.into_iter().filter(|r| r.qty > 0) {
        let rate = *rates.entry(r.item.clone()).or_insert_with(|| sc.spoil_per_min(&r.item) as f32);
        if rate <= 0.0 {
            continue;
        }
        let rate = if r.owner & STRUCTURE_BIT != 0 {
            // Kept in a structure: the `kept_spoil` law's share for its kind.
            let kind = ctx.db.structure().id().find(r.owner & !STRUCTURE_BIT).map(|s| s.kind).unwrap_or_default();
            rate * *kept.entry(kind.clone()).or_insert_with(|| sc.num_of("kept_spoil", &kind, 1.0 / 3.0) as f32)
        } else {
            if carrier.0 != r.owner {
                let share = ctx.db.character().id().find(r.owner as u32).map_or(1.0, |c| *shares.entry(c.kind.clone()).or_insert_with(|| sc.num_of("carried_spoil", &c.kind, 1.0) as f32));
                carrier = (r.owner, share);
            }
            rate * carrier.1
        };
        let expect = r.qty as f32 * rate;
        let mut lost = expect.floor() as u32;
        if ctx.rng().gen::<f32>() < expect.fract() {
            lost += 1;
        }
        let lost = lost.min(r.qty);
        if lost == 0 {
            continue;
        }
        let (owner, item) = (r.owner, r.item.clone());
        r.qty -= lost;
        if r.qty == 0 {
            ctx.db.inventory().id().delete(r.id);
        } else {
            ctx.db.inventory().id().update(r);
        }
        if owner & STRUCTURE_BIT == 0 {
            if let (Some(c), Some(b)) = (ctx.db.character().id().find(owner as u32), ctx.db.body().id().find(owner as u32)) {
                let at = common::pos(&b, now);
                crate::perceive::percept(ctx, &c, now, "body", c.id, 0, at, format!("Some of your {item} spoiled ({lost} lost)."), 0.25);
            }
        }
    }
}

/// A character enters a new stage of life.
fn grew(ctx: &ReducerContext, c: &Character, stage: u8, now: u64) {
    let Some(mut row) = ctx.db.character().id().find(c.id) else { return };
    row.stage = stage;
    ctx.db.character().id().update(row);
    // The look follows in the same transaction (a new band at a stage change: docs/LOOK.md §4).
    crate::look::refresh(ctx, c.id, now, "grew");
    if stage != 0 {
        ctx.db.infant_cry().infant().delete(c.id);
    }
    // A person who outgrows infancy starts from a child's way of life (theirs to change).
    if c.kind == "person" && c.stage == 0 && stage == 1 {
        if !seed::grow_into_ways(ctx, c.id, now) {
            seed::give_repertoire(ctx, c.id, "child", now);
        }
    }
    // A weaned animal leaves its young instinct (follow a parent, eat what it holds) for its
    // species' ways, so a young wolf hunts before it can breed; grown, it takes them afresh.
    if c.kind != "person" && stage >= 1 && stage <= 2 && c.stage < stage {
        if !seed::grow_into_ways(ctx, c.id, now) {
            seed::give_ways(ctx, c.id, &c.kind, now);
        }
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
        for id in [a, b] {
            crate::act::retire(ctx, id);
        }
        return;
    };
    let Some(at) = ctx.db.body().id().find(first.id).map(|bd| common::pos(&bd, now)) else { return };
    let kind = first.kind.clone();
    let litter = ctx.rng().gen_range(1..=common::life_of(ctx, &kind).litter.max(1));
    let (controller, minded) = if first.ai { (first.controller, true) } else { common::mind_controller(ctx) };
    let mut names = Vec::new();
    for _ in 0..litter {
        let id = if kind == "person" {
            let used: Vec<String> = ctx.db.character().kind().filter("person").map(|c| c.name).collect();
            let pick = ctx.rng().gen_range(0..NAMES.len());
            let name = (0..NAMES.len()).map(|i| NAMES[(pick + i) % NAMES.len()]).find(|n| !used.iter().any(|u| u == n)).map(String::from).unwrap_or_else(|| format!("Child{}", used.len()));
            seed::spawn_with(ctx, &name, "person", controller, minded, at, now, 0.0, (pa.id, pb.id))
        } else {
            seed::spawn_young(ctx, &kind, at, now, (pa.id, pb.id))
        };
        seed::inherit_ways(ctx, id, pa.id, pb.id, now);
        names.push((id, common::name_of(ctx, id)));
    }
    // The parents know their children (and each other, through them).
    crate::perception::knowledge_changed(Some(pa.id));
    crate::perception::knowledge_changed(Some(pb.id));
    // A parent who died before the birth kept what the child inherits until now.
    for p in [&pa, &pb].into_iter().filter(|p| !p.alive) {
        crate::act::retire(ctx, p.id);
    }
    let list = names.iter().map(|(_, n)| n.clone()).collect::<Vec<_>>().join(" and ");
    if kind == "person" {
        common::chronicle(ctx, now, "birth", names[0].0, first.id, at, format!("{list} was born to {} and {}", pa.name, pb.name));
        for p in &parents {
            crate::perceive::percept(ctx, p, now, "birth", names[0].0, p.id, at, format!("Your child {list} was born."), 1.0);
        }
        crate::perceive::witnessed(ctx, now, at, "birth", names[0].0, first.id, "A child was born to {b}", 0.5, &[a, b, names[0].0]);
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
    if common::schema_moved("housekeeping") {
        return Ok(());
    }
    let w = common::world(ctx);
    if w.paused {
        return Ok(());
    }
    let now = common::now_ms(ctx);
    let mut k = common::clock(ctx);
    common::set_profiling(k.profile);
    let _timer = common::span("housekeeping");
    common::report_scenes();
    crate::perception::report_answers(ctx);
    common::report_diag();
    crate::town::refresh_weather(ctx, now);
    crate::presence::housekeeping(ctx, now);
    crate::town::guests_leave(ctx, now);
    crate::perception::expire(ctx, now);
    crate::combat::expire(ctx, now);
    crate::records::housekeeping(ctx, now);
    let hour = common::hour(&w, now) as u8;
    if hour != k.last_hour {
        let day = living_rules::day_of(now, w.epoch_ms, w.day_ms);
        if hour == 20 {
            common::chronicle(ctx, now, "time", 0, 0, (0.0, 0.0), format!("Night falls on day {day}."));
        } else if hour == 6 {
            common::chronicle(ctx, now, "time", 0, 0, (0.0, 0.0), format!("Dawn of day {day}."));
            // No one is asked to think at dawn: each person's new day begins at its own rising
            // (brain.rs, `rhythm.last_day`).
        }
        k.last_hour = hour;
    }

    spoil(ctx, now);
    expire_remains(ctx, now);
    crate::combat::housekeeping(ctx, now);
    crate::fast::pump(ctx, now);

    // One pass over the characters: population counts for the stats row, and the living.
    let mut alive_people = 0u32;
    let mut deer = 0u32;
    let mut wolves = 0u32;
    let mut dead_people = 0u32;
    let mut alive: Vec<Character> = Vec::new();
    let mut kinds: Vec<(String, u32)> = Vec::new();
    for c in ctx.db.character().iter() {
        if !c.alive {
            dead_people += (c.kind == "person") as u32;
            continue;
        }
        match c.kind.as_str() {
            "person" => alive_people += 1,
            "deer" => deer += 1,
            "wolf" => wolves += 1,
            _ => {}
        }
        match kinds.iter_mut().find(|(k, _)| *k == c.kind) {
            Some((_, n)) => *n += 1,
            None => kinds.push((c.kind.clone(), 1)),
        }
        alive.push(c);
    }
    // Animals breed, age and die like everyone else; only a species down to its floor gets
    // newcomers from beyond the map (the living are counted before this second's deaths).
    migration(ctx, &kinds, now);
    // Life stages and deaths of old age, at the world's pace.
    for c in alive {
        let life = common::life_of(ctx, &c.kind);
        let age = common::age_days(&c, &w, now);
        if life.fraction(age, common::pace(&w)) >= life.deathline(c.id) {
            crate::act::die(ctx, c.id, "old age", now, 0, living_rules::outcome::death::OLD_AGE);
            dead_people += (c.kind == "person") as u32;
            continue;
        }
        let stage = common::stage_code(life.stage(age, common::pace(&w)));
        if stage != c.stage {
            grew(ctx, &c, stage, now);
        }
    }
    // Looks whose band changes now by age alone (12 and 18 years): an index range of the due
    // rows only, after the stage changes above have rewritten theirs.
    crate::look::due(ctx, now);

    // Births.
    let due: Vec<Expecting> = ctx.db.expecting().due_ms().filter(..=now).collect();
    for e in due {
        ctx.db.expecting().id().delete(e.id);
        birth(ctx, e.a, e.b, now);
        let w = common::world(ctx);
        let kind = ctx.db.character().id().find(e.a).map(|c| c.kind).unwrap_or_default();
        let until = now + (common::life_of(ctx, &kind).interbirth_days(common::pace(&w)) * w.day_ms as f32) as u64;
        for id in [e.a, e.b] {
            ctx.db.rearing().id().delete(id);
            if ctx.db.character().id().find(id).is_some_and(|c| c.alive) {
                ctx.db.rearing().insert(Rearing { id, until_ms: until });
            }
        }
    }
    // Bond offers are dropped a minute after they can no longer be taken up (the laws'
    // window). Trade offers go as soon as they end, so `my_offers` stops showing them
    // within this second.
    let laws = common::laws(ctx);
    let bond_ms = (laws.bond_window_s * 1000.0) as u64 + 60_000;
    for o in ctx.db.bond_offer().iter().filter(|o| now.saturating_sub(o.at_ms) > bond_ms).map(|o| o.id).collect::<Vec<_>>() {
        ctx.db.bond_offer().id().delete(o);
    }
    for o in ctx.db.trade_offer().iter().filter(|o| now > o.ends_ms(laws.trade_window_s)).map(|o| o.id).collect::<Vec<_>>() {
        ctx.db.trade_offer().id().delete(o);
    }
    // An offer made before `until_ms` existed gets its end from the law's window.
    for mut o in ctx.db.trade_offer().iter().filter(|o| o.until_ms == 0).collect::<Vec<_>>() {
        o.until_ms = o.ends_ms(laws.trade_window_s);
        ctx.db.trade_offer().id().update(o);
    }

    // Bound the story feed.
    let n = ctx.db.chronicle().count();
    if n > 4_000 {
        let old: Vec<u64> = ctx.db.chronicle().at_ms().filter(0u64..).take((n - 3_500) as usize).map(|c| c.id).collect();
        for id in old {
            ctx.db.chronicle().id().delete(id);
        }
    }

    common::flush_counts(&mut k);
    let prev = ctx.db.stats().id().find(0);
    let deaths = dead_people;
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
        alive_animals: deer + wolves,
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
