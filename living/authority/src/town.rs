//! Town life without minds (docs/TOWN_LIFE.md): the weather, what others see a character
//! doing (`act_card`, `doing`), gestures made at someone (`hail`), the commotion of a fight or
//! a death, and the places each settled resident knows (home, work, the square, an evening
//! spot). Routines live in the residents' own graphs; nothing here decides for anyone.

use crate::common::{self, dist};
use crate::tables::*;
use spacetimedb::{ReducerContext, Table};
use std::cell::RefCell;

thread_local! {
    /// The weather row, read once per transaction.
    static RAIN: std::cell::Cell<Option<(i64, bool)>> = const { std::cell::Cell::new(None) };
    /// Recent fights and deaths (`chronicle` rows of those kinds within `COMMOTION_MS`), read
    /// once per transaction and shared by every evaluation in it.
    static COMMOTIONS: RefCell<Option<(i64, Vec<(f32, f32)>)>> = const { RefCell::new(None) };
}

// ---- weather ---------------------------------------------------------------------

/// Whether it is raining now (the `weather` row; no row: never).
pub fn raining(ctx: &ReducerContext) -> bool {
    let key = common::stamp(ctx);
    if let Some((k, r)) = RAIN.with(|c| c.get()) {
        if k == key {
            return r;
        }
    }
    let r = ctx.db.weather().id().find(0).is_some_and(|w| w.raining);
    RAIN.with(|c| c.set(Some((key, r))));
    r
}

/// A world's climate, from its seed (`"weather": {"spell_s": 180, "rain_share": 0.2}`): the sky
/// changes every `spell_s` real seconds and each spell rains with probability `rain_share`.
/// A seed without one never rains, so lab worlds keep their weather (none).
#[derive(serde::Deserialize, Default, Clone, Copy)]
pub struct SeedWeather {
    #[serde(default = "spell_s")]
    pub spell_s: f32,
    #[serde(default)]
    pub rain_share: f32,
}

fn spell_s() -> f32 {
    180.0
}

#[derive(serde::Deserialize, Default)]
struct ClimateOf {
    #[serde(default)]
    weather: SeedWeather,
}

thread_local! {
    static CLIMATE: SeedWeather = serde_json::from_str::<ClimateOf>(&crate::seed::active()).map(|c| c.weather).unwrap_or_default();
}

/// The seed's own weather at `now`: whether the current spell rains, and when it ends.
fn natural(w: &World, now: u64) -> (bool, u64) {
    let c = CLIMATE.with(|c| *c);
    let period = (c.spell_s.clamp(10.0, 86_400.0) * 1000.0) as u64;
    let k = now.saturating_sub(w.epoch_ms) / period;
    // splitmix64 of the seed and the spell: the same sky for everyone, different per world.
    let mut z = w.seed ^ k.wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ 0xC0FF_EE00_0000_0001;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^= z >> 31;
    let u = (z >> 11) as f64 / (1u64 << 53) as f64;
    // The first spell of a world is always dry, so a fresh world starts in clear weather.
    (k > 0 && (u as f32) < c.rain_share.clamp(0.0, 1.0), w.epoch_ms + (k + 1) * period)
}

/// Keep the `weather` row current (housekeeping, once a second); writes only on a change.
pub fn refresh_weather(ctx: &ReducerContext, now: u64) {
    let w = common::world(ctx);
    let cur = ctx.db.weather().id().find(0);
    let forced = cur.as_ref().filter(|c| c.forced_until_ms > now);
    let (raining, until) = match forced {
        Some(c) => (c.raining, c.forced_until_ms),
        None => natural(&w, now),
    };
    let row = Weather {
        id: 0,
        raining,
        since_ms: cur.as_ref().filter(|c| c.raining == raining).map_or(now, |c| c.since_ms),
        until_ms: until,
        forced_until_ms: forced.map_or(0, |c| c.forced_until_ms),
    };
    match cur {
        Some(c) if c == row => {}
        Some(_) => {
            ctx.db.weather().id().update(row);
            RAIN.with(|c| c.set(None));
        }
        None => {
            ctx.db.weather().insert(row);
            RAIN.with(|c| c.set(None));
        }
    }
}

/// Hold the weather for a while (an admin scene); `secs == 0` hands it back to the seed.
pub fn force_weather(ctx: &ReducerContext, raining: bool, secs: u32, now: u64) {
    let forced_until_ms = if secs == 0 { 0 } else { now + secs as u64 * 1000 };
    let cur = ctx.db.weather().id().find(0);
    let row = Weather { id: 0, raining, since_ms: now, until_ms: forced_until_ms, forced_until_ms };
    match cur {
        Some(_) => ctx.db.weather().id().update(row),
        None => ctx.db.weather().insert(row),
    };
    RAIN.with(|c| c.set(None));
    refresh_weather(ctx, now);
}

// ---- what others see -------------------------------------------------------------

/// One `act_card` per skill the script says others can see; rewritten on each install.
pub fn cards(ctx: &ReducerContext, sc: &living_rules::script::Scripts) {
    let shows = sc.shows();
    for old in ctx.db.act_card().iter().filter(|c| shows.get(&c.skill).is_none()).map(|c| c.skill).collect::<Vec<_>>() {
        ctx.db.act_card().skill().delete(old);
    }
    for (skill, s) in shows.iter() {
        let card = ActCard { skill: skill.to_string(), code: s.code, look: s.look.clone(), faces: s.faces, aside: s.aside };
        match ctx.db.act_card().skill().find(skill.to_string()) {
            Some(c) if c == card => {}
            Some(_) => {
                ctx.db.act_card().skill().update(card);
            }
            None => {
                ctx.db.act_card().insert(card);
            }
        }
    }
}

/// How near its home a resting body is indoors (m).
pub const INDOORS_M: f32 = 3.5;

/// A shown skill starts being performed: anyone in view sees it (`doing`).
pub fn shown(ctx: &ReducerContext, sc: &living_rules::script::Scripts, a: &Activity, at: Option<(f32, f32)>, now: u64) {
    let code = sc.shows().code(&a.skill);
    if code == 0 {
        return;
    }
    let (x, y) = at.unwrap_or((a.target.x, a.target.y));
    // A rest taken at one's own door is taken indoors (what clients drew from the home
    // position, which is no longer sent to them).
    let indoors = sc.shows().get(&a.skill).is_some_and(|s| s.look == "rest")
        && ctx.db.character().id().find(a.id).zip(ctx.db.body().id().find(a.id)).is_some_and(|(c, b)| (c.home_x != 0.0 || c.home_y != 0.0) && common::dist(common::pos(&b, now), (c.home_x, c.home_y)) <= INDOORS_M);
    let row = Doing { id: a.id, code, target: if a.target.class == 3 { a.target.id as u32 } else { 0 }, x, y, since_ms: now, until_ms: a.ends_ms, indoors };
    crate::frame::did(a.id);
    if ctx.db.doing().id().find(a.id).is_some() {
        ctx.db.doing().id().update(row);
    } else {
        ctx.db.doing().insert(row);
    }
}

/// A shown skill ended (finished, broken off, or its doer died).
pub fn unshown(ctx: &ReducerContext, sc: &living_rules::script::Scripts, id: u32, skill: &str) {
    if sc.shows().code(skill) != 0 {
        crate::frame::did(id);
        ctx.db.doing().id().delete(id);
    }
}

// ---- gestures --------------------------------------------------------------------

/// How long a greeting stays unanswered for the one who made it: a gesture back within this
/// time answers it (and does not greet them again).
const ANSWER_MS: u64 = 10_000;

/// `hail`: the target sees the gesture made at them. A gesture back at someone who greeted
/// me within `ANSWER_MS` answers their greeting: they see it, but are not greeted anew (no
/// endless exchange of waves).
pub fn hail(ctx: &ReducerContext, me: u32, a: &Activity, at: (f32, f32), now: u64) -> Result<String, String> {
    if a.target.class != 3 {
        return Err("no one to greet".into());
    }
    let them = a.target.id as u32;
    let answer = ctx.db.mind_state().id().find(me).is_some_and(|st| st.hailer == them && now.saturating_sub(st.hailed_ms) < ANSWER_MS);
    if let Some(mut st) = ctx.db.mind_state().id().find(me).filter(|_| answer) {
        // Answered: their greeting is closed for me too.
        st.hailed_ms = 0;
        st.hailer = 0;
        ctx.db.mind_state().id().update(st);
    }
    if !answer {
        if let Some(mut st) = ctx.db.mind_state().id().find(them) {
            st.hailed_ms = now;
            st.hailer = me;
            ctx.db.mind_state().id().update(st);
        }
        common::wake(ctx, them);
    }
    if let Some(c) = ctx.db.character().id().find(them) {
        let who = common::label_cap(ctx, &c, me);
        let text = if answer { format!("{who} answers your greeting ({}).", a.skill) } else { format!("{who} greets you ({}).", a.skill) };
        crate::perceive::percept(ctx, &c, now, "gesture", me, them, at, text, if answer { 0.15 } else { 0.3 });
    }
    let name = ctx.db.character().id().find(me).map(|c| common::label_for(ctx, &c, them)).unwrap_or_else(|| common::name_of(ctx, them));
    Ok(if answer { format!("answered {name}") } else { format!("greeted {name}") })
}

// ---- commotion -------------------------------------------------------------------

/// How recent a blow, threat or death must be to draw the eye.
const COMMOTION_MS: u64 = 8_000;
/// The chronicle's event kinds that are a fight or a death.
const COMMOTION_KINDS: &[&str] = &["attack", "threat", "killing", "death"];

/// Where the nearest recent fight or death within `sight` of `at` is (a fight's chronicle
/// row is refreshed at every blow, so it stays recent while the fight lasts).
pub fn commotion(ctx: &ReducerContext, at: (f32, f32), sight: f32, now: u64) -> Option<(f32, f32)> {
    let key = common::stamp(ctx);
    let recent = COMMOTIONS.with(|c| {
        let mut c = c.borrow_mut();
        if c.as_ref().map_or(true, |(k, _)| *k != key) {
            let rows = ctx.db.chronicle().at_ms().filter(now.saturating_sub(COMMOTION_MS)..).filter(|r| COMMOTION_KINDS.contains(&r.kind.as_str())).map(|r| (r.x, r.y)).collect();
            *c = Some((key, rows));
        }
        c.as_ref().map(|(_, v)| v.clone()).unwrap_or_default()
    });
    recent.into_iter().map(|p| (dist(at, p), p)).filter(|(d, _)| *d <= sight).min_by(|a, b| a.0.total_cmp(&b.0)).map(|(_, p)| p)
}

/// Walkable tiles in the 5x5 square around a point (a narrow street has few).
pub fn room(ctx: &ReducerContext, at: (f32, f32)) -> u32 {
    let map = common::map(ctx);
    let (cx, cy) = (at.0.floor() as i32, at.1.floor() as i32);
    let mut n = 0;
    for dy in -2..=2 {
        for dx in -2..=2 {
            if map.walkable(cx + dx, cy + dy) {
                n += 1;
            }
        }
    }
    n
}

/// A body's heading and velocity now.
pub fn motion_of(b: &Body, now: u64) -> (f32, (f32, f32)) {
    let dt = now.min(b.next_ms).saturating_sub(b.t_ms) as f32 / 1000.0;
    let v = (b.vx * b.vx + b.vy * b.vy).sqrt();
    let (_, _, h) = living_rules::steer::pose(b.x, b.y, b.heading, v, b.turn, b.turn_s, dt);
    let moving = now < b.next_ms && v > 0.0;
    (h, if moving { (v * h.cos(), v * h.sin()) } else { (0.0, 0.0) })
}

// ---- places a settled resident knows ---------------------------------------------

/// What a land seed says about town life: which lots or things each place a resident knows
/// is, and where each occupation works (seed data, so the mechanics stay free of culture).
#[derive(serde::Deserialize, Default)]
pub struct SeedTownLife {
    /// Place name -> kinds to look for, in order: a lot kind (`inn`, `field`), a resource kind
    /// (`fishing_spot`), a structure kind (`gate`), or `plaza` (the settlement's square).
    #[serde(default)]
    pub places: std::collections::BTreeMap<String, Vec<String>>,
    /// Occupation -> the kinds its workplace may be (as above); spread over the matching lots.
    #[serde(default)]
    pub work: std::collections::BTreeMap<String, Vec<String>>,
    /// Places some households go in the evening (alternating by household), e.g. inn, square.
    #[serde(default)]
    pub evening: Vec<String>,
    /// Places spread over their spots like workplaces (each resident the nearest of the least
    /// used), so that a whole town does not share one, e.g. the bush someone picks berries at.
    #[serde(default)]
    pub spread: Vec<String>,
}

/// A place an author gives one resident (`residents[].places`, docs/SEEDED_LIVES.md). It is found
/// like a `town_life` place, among `kinds` (none: `plaza`) in the settlement named `in` (their
/// own when empty). A `town_life` place of the same name gives way to it, so someone's `work`
/// can be another town's market.
///
/// Knowing the way: with `stages`, they also know that many points evenly spaced along the
/// roads from home to it, `<name> 1` to `<name> <stages>` (the last at the place itself), each a
/// walk an ordinary search finds. With `along_m`, the place is instead the point that far along
/// the roads from home toward it: a spot on the road out. With `between` (two settlements), it
/// is the point of the trunk road between them nearest home: someone who lives by a road knows
/// where it passes.
#[derive(serde::Deserialize, Clone, Default)]
pub struct SeedPlace {
    pub name: String,
    #[serde(default, rename = "in")]
    pub within: String,
    #[serde(default)]
    pub kinds: Vec<String>,
    #[serde(default)]
    pub stages: u32,
    #[serde(default)]
    pub along_m: f32,
    #[serde(default)]
    pub between: Vec<String>,
}

/// Give every resident of a seeded land settlement the places they know as remembered
/// `place` rows: `work` (by occupation), each of the seed's `places`, `evening`, and the places
/// their author gave them. Runs once at world creation over the settlements' own lots (`h.lots`,
/// in memory) and the members of its community (indexed); a character's graph then finds them
/// through its own places.
pub fn seat(ctx: &ReducerContext, h: &crate::island::Hosted, si: usize, community: u32, life: &SeedTownLife, seeded: &[Option<&crate::seed::SeedTown>]) {
    let authored = seeded[si].is_some_and(|t| t.residents.iter().any(|r| !r.places.is_empty()));
    if life.places.is_empty() && life.work.is_empty() && !authored {
        return;
    }
    let map = common::map(ctx);
    let near = |p: (f32, f32)| map.nearest_walkable(p.0, p.1).unwrap_or(p);
    let named = |n: &str| if n.is_empty() { Some(si) } else { seeded.iter().position(|t| t.is_some_and(|t| t.name == n)) };
    // Where a kind stands in settlement `sj` (looked up once per settlement and kind).
    let spots_of = |sj: usize, k: &str| -> Vec<(f32, f32)> {
        let s = &h.settlements[sj];
        let lots = || h.lots.iter().filter(move |l| l.settlement as usize == sj);
        match k {
            "plaza" => s.square.iter().map(|q| near(*q)).collect(),
            // Fields and gardens are worked where they lie; buildings at their door.
            lk if lots().any(|l| l.kind.id() == lk) => lots().filter(|l| l.kind.id() == lk).map(|l| if lk == "field" || lk == "garden" { near(l.centre) } else { l.door }).collect(),
            other if living_rules::catalog::kind_class(other).is_some() => {
                let r = s.radius_m.max(40.0) * 1.5;
                let mut v = Vec::new();
                for c in living_rules::map::chunks_around(s.centre.0, s.centre.1, r) {
                    v.extend(ctx.db.resource_node().chunk().filter(c).filter(|n| n.kind == other && dist((n.x, n.y), s.centre) <= r).map(|n| near((n.x, n.y))));
                    v.extend(ctx.db.structure().chunk().filter(c).filter(|n| n.kind == other && dist((n.x, n.y), s.centre) <= r).map(|n| (n.x, n.y)));
                }
                v
            }
            _ => Vec::new(),
        }
    };
    let mut found: std::collections::HashMap<(usize, String), Vec<(f32, f32)>> = std::collections::HashMap::new();
    let mut spots = |sj: usize, k: &str| -> Vec<(f32, f32)> { found.entry((sj, k.to_string())).or_insert_with(|| spots_of(sj, k)).clone() };
    // How many of the residents already work at a spot.
    let mut used: std::collections::HashMap<(i32, i32), u32> = std::collections::HashMap::new();
    let mut find = |kinds: &[String], sj: usize, from: (f32, f32), spread: bool| -> Option<(f32, f32)> {
        for k in kinds {
            let mut spots = spots(sj, k);
            if spots.is_empty() {
                continue;
            }
            let key = |p: (f32, f32)| (p.0.floor() as i32, p.1.floor() as i32);
            // Work is spread: the nearest of the least used spots. Only a spot one can walk to
            // from home counts (a fishing spot across the water, a walled-in yard do not): by
            // the connected ground once the routes are warmed, else by the walk's first leg,
            // which searches the areas the whole way (a 6,000-tile search refused spots round
            // a building row or a pond). In another settlement the nearest counts.
            spots.sort_by(|a, b| {
                let u = |p: &(f32, f32)| if spread { used.get(&key(*p)).copied().unwrap_or(0) } else { 0 };
                u(a).cmp(&u(b)).then(dist(*a, from).total_cmp(&dist(*b, from)))
            });
            let reach = |p: &(f32, f32)| map.reachable(from, *p).unwrap_or_else(|| map.route_leg(from, *p, &living_rules::nav::RouteSpec::default()).is_some());
            let pick = if sj == si { spots.into_iter().take(4).find(reach) } else { spots.into_iter().next() };
            let Some(pick) = pick else { continue };
            if spread {
                *used.entry(key(pick)).or_default() += 1;
            }
            return Some(pick);
        }
        None
    };
    let members: Vec<u32> = ctx.db.membership().community().filter(community).map(|m| m.member).collect();
    let mut households: Vec<(i32, i32)> = Vec::new();
    for id in members {
        let Some(c) = ctx.db.character().id().find(id) else { continue };
        let home = (c.home_x, c.home_y);
        let occ = ctx.db.background().id().find(id).and_then(|b| serde_json::from_str::<serde_json::Value>(&b.text).ok()).and_then(|v| v["occupation"].as_str().map(String::from)).unwrap_or_default();
        let own: Vec<crate::town::SeedPlace> = seeded[si].and_then(|t| t.residents.iter().find(|r| r.name == c.name)).map(|r| r.places.clone()).unwrap_or_default();
        let mine = |name: &str| own.iter().any(|p| p.name == name);
        let put = |name: &str, at: (f32, f32)| {
            ctx.db.place().insert(Place { id: 0, actor: id, name: name.into(), x: at.0, y: at.1 });
        };
        for p in &own {
            if let [a, b] = p.between.as_slice() {
                let ends = (named(a), named(b));
                let way = match ends {
                    (Some(i), Some(j)) => h.ways.trunk_of_route(near(h.settlements[i].centre), near(h.settlements[j].centre)),
                    _ => None,
                };
                match way.and_then(|w| w.into_iter().min_by(|x, y| dist(*x, home).total_cmp(&dist(*y, home)))) {
                    Some(at) => put(&p.name, near(at)),
                    None => log::warn!("{}: no road between {a:?} and {b:?} for place {:?}", c.name, p.name),
                }
                continue;
            }
            let Some(sj) = named(&p.within) else {
                log::warn!("{}: place {:?} is in {:?}, which is not a settlement of this world", c.name, p.name, p.within);
                continue;
            };
            let kinds = if p.kinds.is_empty() { vec!["plaza".to_string()] } else { p.kinds.clone() };
            let Some(at) = find(&kinds, sj, home, true) else {
                log::warn!("{}: no {:?} for place {:?} in {:?}", c.name, p.kinds, p.name, p.within);
                continue;
            };
            if p.stages == 0 && p.along_m <= 0.0 {
                put(&p.name, at);
                continue;
            }
            let Some(way) = h.ways.route(home, at) else {
                log::warn!("{}: no road from home to {:?} in {:?}", c.name, p.name, p.within);
                put(&p.name, at);
                continue;
            };
            if p.along_m > 0.0 {
                put(&p.name, near(living_rules::ways::along(&way, p.along_m)));
                continue;
            }
            put(&p.name, at);
            let n = p.stages.min(48) as usize;
            for (k, s) in living_rules::ways::stages(&way, n).into_iter().enumerate() {
                put(&format!("{} {}", p.name, k + 1), if k + 1 == n { at } else { near(s) });
            }
        }
        if let Some(kinds) = life.work.get(&occ).filter(|_| !mine("work")) {
            if let Some(at) = find(kinds, si, home, true) {
                put("work", at);
            }
        }
        for (name, kinds) in life.places.iter().filter(|(n, _)| !mine(n)) {
            if let Some(at) = find(kinds, si, home, life.spread.contains(name)) {
                put(name, at);
            }
        }
        if !life.evening.is_empty() && !mine("evening") {
            let hk = (home.0.floor() as i32, home.1.floor() as i32);
            let n = households.iter().position(|k| *k == hk).unwrap_or_else(|| {
                households.push(hk);
                households.len() - 1
            });
            let name = &life.evening[n % life.evening.len()];
            if let Some(p) = ctx.db.place().actor().filter(id).find(|p| p.name == *name) {
                put("evening", (p.x, p.y));
            }
        }
    }
}

// ---- hospitality ------------------------------------------------------------------------

/// The house at a character's home door (its household's), if it has one.
fn house_of(ctx: &ReducerContext, c: &Character) -> Option<Structure> {
    if c.home_x == 0.0 && c.home_y == 0.0 {
        return None;
    }
    let home = (c.home_x, c.home_y);
    living_rules::map::chunks_around(home.0, home.1, 2.0)
        .into_iter()
        .flat_map(|k| ctx.db.structure().chunk().filter(k).collect::<Vec<_>>())
        .filter(|s| s.kind == "house" && dist((s.x, s.y), home) <= 1.5)
        .min_by(|a, b| dist((a.x, a.y), home).total_cmp(&dist((b.x, b.y), home)))
}

/// The `host` effect: the target person is the actor's household's guest until the next
/// `until_hour` of the world's day. One stay per guest at a time (a new one replaces it).
pub fn host(ctx: &ReducerContext, me: u32, a: &Activity, at: (f32, f32), until_hour: f32, now: u64) -> Result<String, String> {
    if a.target.class != 3 {
        return Err("no one to take in".into());
    }
    let guest = a.target.id as u32;
    let host_c = ctx.db.character().id().find(me).ok_or("no host")?;
    let house = house_of(ctx, &host_c).ok_or("you have no house to offer (none stands at your home door)")?;
    let w = common::world(ctx);
    let hour_ms = w.day_ms as f64 / 24.0;
    let ahead = ((until_hour - common::hour(&w, now)).rem_euclid(24.0)) as f64;
    let until_ms = now + (ahead * hour_ms) as u64;
    for g in ctx.db.guest().guest().filter(guest).map(|g| g.id).collect::<Vec<_>>() {
        ctx.db.guest().id().delete(g);
    }
    ctx.db.guest().insert(Guest { id: 0, guest, host: me, house: house.id, x: house.x, y: house.y, since_ms: now, until_ms });
    // The guest knows where its bed is: a remembered place its graph can go to.
    match ctx.db.place().actor().filter(guest).find(|p| p.name == "lodging") {
        Some(mut p) => {
            p.x = house.x;
            p.y = house.y;
            ctx.db.place().id().update(p);
        }
        None => {
            ctx.db.place().insert(Place { id: 0, actor: guest, name: "lodging".into(), x: house.x, y: house.y });
        }
    }
    let when = format!("{:02}:00", until_hour.floor() as u32);
    if let Some(c) = ctx.db.character().id().find(guest) {
        let dir = common::direction(at, (house.x, house.y));
        let text = format!("{} takes you in as their guest until {when}: a bed in their house ({dir}, at [{:.0}, {:.0}]) and food from their household's store.", common::label_cap(ctx, &c, me), house.x, house.y);
        crate::perceive::percept(ctx, &c, now, "host", me, guest, at, text, 0.85);
    }
    crate::perceive::witnessed(ctx, now, at, "host", me, guest, "{a} took {b} in as a guest", 0.4, &[me, guest]);
    common::chronicle(ctx, now, "host", me, guest, at, format!("{} took {} in as a guest until {when}", common::display(ctx, me), common::display(ctx, guest)));
    Ok(format!("took {} in as your guest until {when}", common::label_for(ctx, &host_c, guest)))
}

/// `who` is a guest now of `owner`'s household (its host, or someone sharing the host's home).
pub fn guest_of(ctx: &ReducerContext, who: u32, owner: u32, now: u64) -> bool {
    let home = |id: u32| ctx.db.character().id().find(id).map(|c| (c.home_x, c.home_y));
    ctx.db.guest().guest().filter(who).any(|g| g.until_ms > now && (g.host == owner || (home(g.host).is_some() && home(g.host) == home(owner))))
}

/// Housekeeping: stays that ended (an index range of the due rows) go, with the guest's
/// `lodging` place at that house.
pub fn guests_leave(ctx: &ReducerContext, now: u64) {
    for g in ctx.db.guest().until_ms().filter(..=now).collect::<Vec<_>>() {
        ctx.db.guest().id().delete(g.id);
        if let Some(p) = ctx.db.place().actor().filter(g.guest).find(|p| p.name == "lodging" && dist((p.x, p.y), (g.x, g.y)) < 0.5) {
            ctx.db.place().id().delete(p.id);
        }
    }
}

/// A guest died: its stays go.
pub fn forget_guest(ctx: &ReducerContext, id: u32) {
    ctx.db.guest().guest().delete(id);
}
