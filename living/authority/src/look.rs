//! A person's look on the authority (docs/LOOK.md): the world data a seed carries (`looks`), the
//! private `look` and `look_line` rows, and every write of them.
//!
//! - **World data.** A seed's `looks: { generation, people: { lp: { band: lk } }, words: { lk:
//!   LookWords }, pool: [lp] }`, and `look: "lp_…"` on a seeded resident. [`check`] refuses a
//!   seed whose looks do not resolve, before anything is written. The person entries and the pool
//!   stay on the authority: clients get only `lk_` keys on their `projected` rows.
//! - **Rows written.** `look_line`: one per (person, band) of the world data, at genesis
//!   ([`genesis`]) and at `relook`; static. `look`: one per living person, at creation
//!   ([`assign`], from `seed::spawn_with` for everyone and again from the seed for an authored
//!   resident), when the band changes (housekeeping's [`due`] read over the `look.due` index, and
//!   `grew` in the stage change's transaction), when the script changes ([`retime_all`]: the life
//!   and band laws give new times) and at `relook`; deleted at death (`perception::gone`).
//! - **Re-projection.** A changed line is written to the `projected` rows of everyone who sees
//!   the person, through the `projected.body` index ([`reproject`]), as `health_moved` does.
//!
//! A world from before looks has no `look_line` rows and an empty `world.look_book`: no look is
//! written there (its people project `look` "", drawn as before) until an admin runs `relook`.

use crate::common;
use crate::seed::{self, Seed};
use crate::tables::*;
use living_rules::look::{self as rules, LookBand, LookBands};
use serde::Deserialize;
use spacetimedb::{ReducerContext, Table};
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::rc::Rc;

/// A seed's look data (docs/LOOK.md §5): its generation, each person entry's line by band, each
/// line's words, and the pool unseeded people wear (`living_rules::look::pool_pick`).
#[derive(Deserialize, Default, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct SeedLooks {
    pub generation: String,
    /// Person key → band ("0".."4" or "infant".."elder") → line key.
    #[serde(default)]
    pub people: BTreeMap<String, BTreeMap<String, String>>,
    #[serde(default)]
    pub words: BTreeMap<String, rules::LookWords>,
    #[serde(default)]
    pub pool: Vec<String>,
}

impl SeedLooks {
    /// Each (person, band, line) of the data, bands as codes; unknown band names are skipped
    /// ([`check`] refuses them).
    pub fn lines(&self) -> impl Iterator<Item = (&str, LookBand, &str)> + '_ {
        self.people.iter().flat_map(|(p, bands)| bands.iter().filter_map(move |(b, k)| LookBand::parse(b).map(|b| (p.as_str(), b, k.as_str()))))
    }

    fn has(&self, person: &str, band: LookBand) -> bool {
        self.people.get(person).is_some_and(|m| m.keys().any(|b| LookBand::parse(b) == Some(band)))
    }
}

/// Only the seed's looks, for reading them out of the whole seed text.
#[derive(Deserialize)]
struct Only {
    #[serde(default)]
    looks: Option<SeedLooks>,
}

thread_local! {
    /// The active seed's looks, parsed once per seed text.
    static LOOKS: RefCell<Option<(Rc<str>, Option<Rc<SeedLooks>>)>> = const { RefCell::new(None) };
}

/// The world's look data: its seed's `looks`, when the world wears that generation
/// (`world.look_book`). `None` for a world without looks, a floor without a seed yet, or a world
/// whose seed carries another generation than the one it was made or `relook`ed with.
fn world_looks(ctx: &ReducerContext) -> Option<Rc<SeedLooks>> {
    let w = common::world(ctx);
    if w.look_book.is_empty() || (seed::VALLEY.is_empty() && !seed::is_runtime()) {
        return None;
    }
    let text = seed::active();
    let looks = LOOKS.with(|l| {
        let mut l = l.borrow_mut();
        match l.as_ref() {
            Some((t, v)) if Rc::ptr_eq(t, &text) => v.clone(),
            _ => {
                let v = serde_json::from_str::<Only>(&text).ok().and_then(|o| o.looks).map(Rc::new);
                *l = Some((text.clone(), v.clone()));
                v
            }
        }
    })?;
    (looks.generation == w.look_book).then_some(looks)
}

/// The world's look bands and the person life table under its laws.
fn laws(ctx: &ReducerContext) -> (living_rules::life::Life, LookBands) {
    (common::life_of(ctx, "person"), common::scripts(ctx).look_bands())
}

/// What a seed's looks say, checked before anything is written (`floor::check`): a generation;
/// keys of the right shape; every band a band; every line with its words (girth and height 0 to
/// 2); every pool entry a person with a line for every band; every resident's `look` a person
/// with a line for their band at their seeded age and for every band after it. A resident
/// without `look` wears a pool entry. A resident naming a look in a seed without looks is
/// refused.
pub fn check(s: &Seed, sc: &living_rules::script::Scripts) -> Result<(), String> {
    let residents = s.towns.iter().chain(s.villages.iter()).flat_map(|t| t.residents.iter());
    let Some(l) = &s.looks else {
        if let Some(r) = residents.into_iter().find(|r| !r.look.is_empty()) {
            return Err(format!("seed looks: {} wears `{}` but the seed has no `looks`", r.name, r.look));
        }
        return Ok(());
    };
    if l.generation.trim().is_empty() {
        return Err("seed looks: `generation` names the look generation (the client book's)".into());
    }
    for (k, w) in &l.words {
        if !rules::is_line_key(k) {
            return Err(format!("seed looks: `{k}` is not a line key (lk_ and 16 hex digits)"));
        }
        if let Some(e) = w.problem() {
            return Err(format!("seed looks: the words of {k}: {e}"));
        }
    }
    for (p, bands) in &l.people {
        if !rules::is_person_key(p) {
            return Err(format!("seed looks: `{p}` is not a person key (lp_ and 16 hex digits)"));
        }
        for (b, k) in bands {
            if LookBand::parse(b).is_none() {
                return Err(format!("seed looks: {p} names band `{b}` (the bands are 0..4: infant, child, youth, adult, elder)"));
            }
            if !l.words.contains_key(k) {
                return Err(format!("seed looks: {p}'s {b} line {k} has no words"));
            }
        }
    }
    for p in &l.pool {
        let Some(missing) = LookBand::ALL.iter().find(|b| !l.has(p, **b)) else { continue };
        if !l.people.contains_key(p) {
            return Err(format!("seed looks: the pool names {p}, which is not among `people`"));
        }
        return Err(format!("seed looks: the pool's {p} has no {} line (a pool person is born and grows old)", missing.name()));
    }
    let life = sc.life("person", common::species_life("person"));
    let bands = sc.look_bands();
    for r in residents {
        if r.look.is_empty() {
            continue;
        }
        if !l.people.contains_key(&r.look) {
            return Err(format!("seed looks: {} wears {}, which is not among `people`", r.name, r.look));
        }
        let from = rules::band_at(&life, r.age, &bands);
        if let Some(b) = LookBand::ALL.iter().filter(|b| **b >= from).find(|b| !l.has(&r.look, **b)) {
            return Err(format!("seed looks: {} ({} years, {}) wears {}, which has no {} line", r.name, r.age, from.name(), r.look, b.name()));
        }
    }
    Ok(())
}

/// Write a seed's look data at genesis (before its people are made, so each is given a look as
/// they are) or at `relook`: the `look_line` rows, replacing any, and `world.look_book`.
pub fn genesis(ctx: &ReducerContext, looks: Option<&SeedLooks>) {
    let Some(l) = looks else { return };
    for id in ctx.db.look_line().iter().map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.look_line().id().delete(id);
    }
    for (person, band, key) in l.lines() {
        let Some(w) = l.words.get(key) else { continue };
        ctx.db.look_line().insert(LookLine { id: 0, key: key.to_string(), person: person.to_string(), band: band.code(), words: w.into() });
    }
    if let Some(mut w) = ctx.db.world().id().find(0) {
        w.look_book = l.generation.clone();
        ctx.db.world().id().update(w);
        common::invalidate_world();
    }
    log::info!("looks: generation {}, {} person entries, {} lines, a pool of {}", l.generation, l.people.len(), ctx.db.look_line().count(), l.pool.len());
}

/// Give person `id` a look: `person` (a seeded resident's entry), else the pool's
/// (`pool_pick(world seed, id, pool length)`). Nothing is written in a world without looks, for
/// an animal, or when the entry has no line for the person's band now.
pub fn assign(ctx: &ReducerContext, id: u32, person: Option<&str>, now: u64) {
    let Some(c) = ctx.db.character().id().find(id).filter(|c| c.alive && c.kind == "person") else { return };
    let person = match person {
        Some(p) => p.to_string(),
        None => {
            let Some(l) = world_looks(ctx) else { return };
            let w = common::world(ctx);
            let Some(i) = rules::pool_pick(w.seed, id, l.pool.len()) else { return };
            l.pool[i].clone()
        }
    };
    let (life, bands) = laws(ctx);
    write(ctx, &c, &person, &life, &bands, now, "made");
}

/// Write `c`'s look row for entry `person` as it is now: the band, the line and its words, and
/// when the band next changes. A changed line reaches everyone who sees `c`.
fn write(ctx: &ReducerContext, c: &Character, person: &str, life: &living_rules::life::Life, bands: &LookBands, now: u64, why: &str) {
    let w = common::world(ctx);
    let pace = common::pace(&w);
    let age_days = common::age_days(c, &w, now);
    let years = life.years_old(age_days, pace);
    let band = rules::look_band(common::stage_code(life.stage(age_days, pace)), years, bands);
    let next_ms = match rules::next_change(life, years, bands) {
        None => u64::MAX,
        Some(t) => {
            let days = (living_rules::life::days_of_years(t, pace) - c.birth_age_days).max(0.0) as f64;
            // A millisecond past the threshold, so the band has changed when it is read; one read
            // a hair early (rounding) looks again a second later.
            (c.born_ms + (days * w.day_ms.max(1) as f64).ceil() as u64 + 1).max(now + 1_000)
        }
    };
    let old = ctx.db.look().id().find(c.id);
    let Some(line) = ctx.db.look_line().by_person_band().filter((person, band.code())).next() else {
        if old.is_some() {
            ctx.db.look().id().delete(c.id);
            reproject(ctx, c.id, "");
        }
        log::warn!("look: {} (#{}) wears {person}, which has no {} line: no look", c.name, c.id, band.name());
        return;
    };
    let row = Look { id: c.id, person: person.to_string(), line: line.key.clone(), band: band.code(), next_ms, words: line.words };
    match old {
        Some(o) if o.line == row.line && o.person == row.person && o.band == row.band && o.next_ms == row.next_ms => {}
        Some(o) => {
            let moved = o.line != row.line;
            if o.band != row.band {
                log::info!("look: #{} {} -> {} ({why})", c.id, LookBand::from_code(o.band).map_or("?", |b| b.name()), band.name());
            }
            ctx.db.look().id().update(row);
            if moved {
                reproject(ctx, c.id, &line.key);
            }
        }
        None => {
            ctx.db.look().insert(row);
            reproject(ctx, c.id, &line.key);
        }
    }
}

/// Person `id`'s look again, as of now (its band may have moved): `grew`, the due read.
pub fn refresh(ctx: &ReducerContext, id: u32, now: u64, why: &str) {
    let Some(l) = ctx.db.look().id().find(id) else { return };
    let Some(c) = ctx.db.character().id().find(id).filter(|c| c.alive) else {
        ctx.db.look().id().delete(id);
        return;
    };
    let (life, bands) = laws(ctx);
    write(ctx, &c, &l.person, &life, &bands, now, why);
}

/// The looks whose band is due to change (once a second, from housekeeping): an index range over
/// `look.next_ms`, only the due rows.
pub fn due(ctx: &ReducerContext, now: u64) {
    let ids: Vec<u32> = ctx.db.look().due().filter(..=now).map(|l| l.id).collect();
    if ids.is_empty() {
        return;
    }
    let (life, bands) = laws(ctx);
    for id in ids {
        let Some(l) = ctx.db.look().id().find(id) else { continue };
        match ctx.db.character().id().find(id).filter(|c| c.alive) {
            Some(c) => write(ctx, &c, &l.person, &life, &bands, now, "due"),
            None => {
                ctx.db.look().id().delete(id);
            }
        }
    }
}

/// Every look's band and next change again, after the script changed (`install_source`): the
/// life table and the band ages are laws. One pass over the `look` rows, one per living person.
pub fn retime_all(ctx: &ReducerContext, now: u64) {
    let rows: Vec<Look> = ctx.db.look().iter().collect();
    if rows.is_empty() {
        return;
    }
    let (life, bands) = laws(ctx);
    for l in rows {
        match ctx.db.character().id().find(l.id).filter(|c| c.alive) {
            Some(c) => write(ctx, &c, &l.person, &life, &bands, now, "laws"),
            None => {
                ctx.db.look().id().delete(l.id);
            }
        }
    }
}

/// Person `id` wears line `line` now: the `projected` rows of everyone who sees them follow
/// (the `projected.body` index; the views re-run for those viewers only).
pub fn reproject(ctx: &ReducerContext, id: u32, line: &str) {
    for mut p in ctx.db.projected().body().filter(id).collect::<Vec<_>>() {
        if p.look != line {
            p.look = line.to_string();
            ctx.db.projected().id().update(p);
        }
    }
}

/// The line key person `id` wears ("" without a look): what the projection sends.
pub fn line_of(ctx: &ReducerContext, id: u32) -> String {
    ctx.db.look().id().find(id).map(|l| l.line).unwrap_or_default()
}

/// Move a live world to its seed's looks (docs/LOOK.md §4), admin only: `generation` must be the
/// generation the seed's `looks` carry (the module's seed, or a floor's). The `look_line` rows
/// are written again, `world.look_book` set, and every living person given a look: a resident
/// the seed names (a minded person of that name) its entry, anyone else a pool entry. Recorded
/// in the chronicle. One pass over the living people; rare and explicit.
#[spacetimedb::reducer]
pub fn relook(ctx: &ReducerContext, generation: String) -> Result<(), String> {
    let w = common::world(ctx);
    if ctx.sender() != w.admin {
        return Err("admin only".into());
    }
    let s: Seed = serde_json::from_str(&seed::active()).map_err(|e| format!("seed: {e}"))?;
    let Some(looks) = s.looks.clone() else { return Err("this world's seed has no `looks`".into()) };
    if looks.generation != generation {
        return Err(format!("this world's seed carries looks of generation `{}`, not `{generation}`", looks.generation));
    }
    check(&s, &common::scripts(ctx))?;
    let now = common::now_ms(ctx);
    let before = w.look_book.clone();
    genesis(ctx, Some(&looks));
    let named: BTreeMap<&str, &str> = s.towns.iter().chain(s.villages.iter()).flat_map(|t| t.residents.iter()).filter(|r| !r.look.is_empty()).map(|r| (r.name.as_str(), r.look.as_str())).collect();
    let people: Vec<Character> = ctx.db.character().kind().filter("person").filter(|c| c.alive).collect();
    let (mut seeded, mut pooled) = (0u32, 0u32);
    for c in &people {
        let person = named.get(c.name.as_str()).filter(|_| c.ai).copied();
        if person.is_some() {
            seeded += 1;
        } else {
            pooled += 1;
        }
        assign(ctx, c.id, person, now);
    }
    // A look whose person entry the new data lacks is gone with it.
    for l in ctx.db.look().iter().collect::<Vec<_>>() {
        if ctx.db.look_line().by_person_band().filter((l.person.as_str(), l.band)).next().is_none() {
            ctx.db.look().id().delete(l.id);
            reproject(ctx, l.id, "");
        }
    }
    let was = if before.is_empty() { String::new() } else { format!(" (was {before})") };
    common::chronicle(ctx, now, "look", 0, 0, (0.0, 0.0), format!("The world's people take looks of generation {generation}{was}: {seeded} from the seed, {pooled} from the pool"));
    log::info!("relook {generation}{was}: {seeded} seeded, {pooled} from the pool, {} look rows", ctx.db.look().count());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const PLAN_TEST: &str = include_str!("../../seeds/plan-test.json");

    fn checked(edit: impl FnOnce(&mut serde_json::Value)) -> Result<(), String> {
        let mut v: serde_json::Value = serde_json::from_str(PLAN_TEST).unwrap();
        edit(&mut v);
        let s: Seed = serde_json::from_value(v).map_err(|e| e.to_string())?;
        let sc = living_rules::script::Scripts::new(seed::SKILLS).unwrap();
        check(&s, &sc)
    }

    /// The fixture's looks (plan-test, generation `fixture-1`) resolve; a seed whose looks do
    /// not is refused, saying why.
    #[test]
    fn a_seeds_looks_are_checked() {
        assert_eq!(checked(|_| {}), Ok(()));
        let s: Seed = serde_json::from_str(PLAN_TEST).unwrap();
        let l = s.looks.as_ref().unwrap();
        assert_eq!((l.generation.as_str(), l.people.len(), l.pool.len()), ("fixture-1", 8, 3));
        assert!(s.towns[0].residents.iter().all(|r| rules::is_person_key(&r.look)));
        let nell = || s.towns[0].residents.iter().find(|r| r.name == "Nell Hollis").unwrap().look.clone();
        let ada = s.towns[0].residents[0].look.clone();
        let pool0 = l.pool[0].clone();
        let cases: Vec<(Box<dyn FnOnce(&mut serde_json::Value)>, &str)> = vec![
            (Box::new(|v| v["looks"]["generation"] = "".into()), "`generation`"),
            (Box::new(move |v| v["looks"]["people"][&ada]["adult"] = "lk_ffffffffffffffff".into()), "has no words"),
            (Box::new(|v| v["towns"][0]["residents"][0]["look"] = "lp_0000000000000000".into()), "not among `people`"),
            (Box::new(move |v| { v["looks"]["people"][&nell()].as_object_mut().unwrap().remove("youth"); }), "has no youth line"),
            (Box::new(move |v| { v["looks"]["people"][&pool0].as_object_mut().unwrap().remove("infant"); }), "has no infant line"),
            (Box::new(|v| v["looks"]["pool"].as_array_mut().unwrap().push("lp_1111111111111111".into())), "the pool names"),
            (Box::new(|v| { v.as_object_mut().unwrap().remove("looks"); }), "the seed has no `looks`"),
            (Box::new(|v| v["looks"]["people"]["lp_short"] = serde_json::json!({})), "not a person key"),
        ];
        for (edit, says) in cases {
            let e = checked(edit).unwrap_err();
            assert!(e.contains(says), "{e} (wanted {says})");
        }
        // A line's words are the generator's: no colour, girth and height 0 to 2.
        let k = l.words.keys().next().unwrap().clone();
        let k2 = k.clone();
        assert!(checked(move |v| v["looks"]["words"][&k]["colour"] = "green".into()).unwrap_err().contains("colour"));
        assert!(checked(move |v| v["looks"]["words"][&k2]["girth"] = 3.into()).unwrap_err().contains("girth and height"));
        // A resident's band at their seeded age decides what must be there: Ada at 41 needs only
        // adult and elder; at 15 she would need a youth line.
        assert!(checked(|v| v["towns"][0]["residents"][0]["age"] = 15.into()).unwrap_err().contains("youth"));
    }

    /// Seeds without looks are unchanged: Cullet (until char-4's data) and the island pass.
    #[test]
    fn seeds_without_looks_pass() {
        for text in [include_str!("../../seeds/cullet.json"), include_str!("../../seeds/island.json")] {
            let s: Seed = serde_json::from_str(text).unwrap();
            let sc = living_rules::script::Scripts::new(seed::SKILLS).unwrap();
            assert!(s.looks.is_none());
            assert_eq!(check(&s, &sc), Ok(()));
        }
    }
}
