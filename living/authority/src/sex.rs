//! Body sex on the authority (docs/LIVING_CORE.md, "Body sex"): the private `sex` row of each
//! person, where it comes from, and what reads it.
//!
//! - **Written once**, when a person comes into the world (`seed::spawn_sexed`, before their look
//!   and their first mind call in the same transaction): a seeded resident's `sex`, a band
//!   member's when the seed gives one, a player's choice (`join_as`), else the world's pick
//!   ([`pick`]: `living_rules::sex::pick` over the world seed and the `female_share()` law).
//!   Kept after death. Never changed.
//! - **Read by primary key only**: the look's pool pick (`look::assign`), a person's scene entry
//!   and first sight (`perceive`), kin words (`speech::named_at`), the conception check
//!   (`act::facts`, only when a law reads `sex`), the self line (`my_sex`, the mind service as the
//!   owner). No per-tick scan.
//! - **Existing worlds**: `backfill_sex` (admin, idempotent) gives a row to every person without
//!   one; `relook` then gives seeded residents a look of their sex.

use crate::common;
use crate::tables::*;
use living_rules::sex::{self as rules, Sex};
use spacetimedb::{ReducerContext, Table, ViewContext};

/// Person `id`'s sex, if the world holds it.
pub fn of(ctx: &ReducerContext, id: u32) -> Option<Sex> {
    ctx.db.sex().id().find(id).and_then(|r| Sex::from_code(r.sex))
}

/// The world's pick for person `id` (no seed or player decided): `living_rules::sex::pick` over
/// the world seed and the `female_share()` law.
pub fn pick(ctx: &ReducerContext, id: u32) -> Sex {
    rules::pick(common::world(ctx).seed, id, common::scripts(ctx).female_share())
}

/// Give person `id` its sex once: `given`, else the world's pick. A row already there is kept
/// (and returned): a body's sex never changes.
pub fn give(ctx: &ReducerContext, id: u32, given: Option<Sex>) -> Sex {
    if let Some(s) = of(ctx, id) {
        return s;
    }
    let s = given.unwrap_or_else(|| pick(ctx, id));
    ctx.db.sex().insert(SexRow { id, sex: s.code() });
    s
}

/// The rules' word for `c`'s body by its sex and life stage ("woman", "old man"; `sex_words()`),
/// or `None` when the world holds no sex for them (an animal, an old world's person).
pub fn word(ctx: &ReducerContext, c: &Character) -> Option<String> {
    if c.kind != "person" {
        return None;
    }
    of(ctx, c.id).map(|s| common::scripts(ctx).sex_words().word(s, c.stage).to_string())
}

/// `observer` made out `target` at full sight now: a minded observer remembers the target's sex
/// with them, once (`sex_seen`; one pair-index lookup, an insert the first time). Nothing for a
/// played observer, an animal on either side, or a target with no sex row.
pub fn remember(ctx: &ReducerContext, observer: &Character, target: &Character, now: u64) {
    if !observer.ai || observer.kind != "person" || target.kind != "person" || observer.id == target.id {
        return;
    }
    if ctx.db.sex_seen().by_pair().filter((observer.id, target.id)).next().is_some() {
        return;
    }
    let Some(s) = of(ctx, target.id) else { return };
    ctx.db.sex_seen().insert(SexSeen { id: 0, observer: observer.id, known: target.id, sex: s.code(), at_ms: now });
}

/// What `id` remembered goes with it at death (`perception::gone`).
pub fn forget(ctx: &ReducerContext, id: u32) {
    for r in ctx.db.sex_seen().observer().filter(id).map(|r| r.id).collect::<Vec<_>>() {
        ctx.db.sex_seen().id().delete(r);
    }
}

/// The sex a person's look shows: the `form` of the lines of their look's person entry
/// (`look_line`, point lookups by band). `None` without a look or when its lines show none.
fn of_look(ctx: &ReducerContext, id: u32) -> Option<Sex> {
    let l = ctx.db.look().id().find(id)?;
    (0u8..=4).filter_map(|b| ctx.db.look_line().by_person_band().filter((l.person.as_str(), b)).next()).find_map(|line| rules::of_form(&line.words.form))
}

/// My living character's body sex, in the rules' name ("female" or "male"); nothing while none
/// lives or the world holds none. One point lookup; the row never changes, so this re-runs only
/// when my character does.
#[spacetimedb::view(accessor = my_sex, public, primary_key = id)]
pub fn my_sex(ctx: &ViewContext) -> Vec<MySex> {
    crate::perception::living(ctx)
        .and_then(|c| ctx.db.sex().id().find(c.id).and_then(|r| Sex::from_code(r.sex)).map(|s| MySex { id: c.id, sex: s.name().into() }))
        .into_iter()
        .collect()
}

/// Give every person without a sex row one (docs/LIVING_CORE.md, "Body sex": an existing
/// world's update), admin only and idempotent: a row already there is never changed. In order:
///
/// 1. a seeded resident (a minded person named in the world's seed): the seed's `sex`;
/// 2. anyone with a look: the sex its line shows, so nobody changes appearance;
/// 3. anyone else: what others' words about them say (the `relation` notes and labels minds
///    hold about them), where at least two words do and twice as many one way as the other;
/// 4. the rest: the world's pick.
///
/// Recorded in the chronicle with the counts. One pass over the people and one over `relation`;
/// rare and explicit. Run `relook(<generation>)` after it in a world with looks, so seeded
/// residents whose pool look shows the other sex get one of theirs.
#[spacetimedb::reducer]
pub fn backfill_sex(ctx: &ReducerContext) -> Result<(), String> {
    let w = common::world(ctx);
    if ctx.sender() != w.admin {
        return Err("admin only".into());
    }
    let people: Vec<Character> = ctx.db.character().kind().filter("person").filter(|c| ctx.db.sex().id().find(c.id).is_none()).collect();
    let seeded: std::collections::BTreeMap<String, Sex> = match crate::seed::active_seed() {
        Some(s) => s.towns.iter().chain(s.villages.iter()).flat_map(|t| t.residents.iter()).filter_map(|r| Sex::parse(&r.sex).map(|x| (r.name.clone(), x))).collect(),
        None => Default::default(),
    };
    // What others' minds hold about each one still without a row (one pass over `relation`).
    let mut told: std::collections::BTreeMap<u32, (u32, u32)> = std::collections::BTreeMap::new();
    if people.iter().any(|c| !(c.ai && seeded.contains_key(&c.name)) && ctx.db.look().id().find(c.id).is_none()) {
        let wanted: std::collections::BTreeSet<u32> = people.iter().map(|c| c.id).collect();
        for r in ctx.db.relation().iter().filter(|r| wanted.contains(&r.other)) {
            let (f, m) = rules::told(&format!("{} {}", r.label, r.note));
            let e = told.entry(r.other).or_default();
            e.0 += f;
            e.1 += m;
        }
    }
    let (mut from_seed, mut from_look, mut from_words, mut picked) = (0u32, 0u32, 0u32, 0u32);
    for c in &people {
        let s = if let Some(s) = seeded.get(&c.name).filter(|_| c.ai) {
            from_seed += 1;
            *s
        } else if let Some(s) = of_look(ctx, c.id) {
            from_look += 1;
            s
        } else if let Some(s) = told.get(&c.id).and_then(|t| rules::clear_majority(*t, 2)) {
            from_words += 1;
            s
        } else {
            picked += 1;
            pick(ctx, c.id)
        };
        give(ctx, c.id, Some(s));
    }
    let now = common::now_ms(ctx);
    let line = format!("{} people given a body sex: {from_seed} from the seed, {from_look} from their look, {from_words} from what others say of them, {picked} by the world's pick", people.len());
    common::chronicle(ctx, now, "sex", 0, 0, (0.0, 0.0), line.clone());
    log::info!("backfill_sex: {line}");
    Ok(())
}

/// Where a seed's sheets speak of a resident as the other sex (body-sex): for each resident with
/// a `sex`, what the other residents' sheets say of them (each relation's `label` and `note`,
/// `living_rules::sex::told`), when at least two words clearly say the other sex. Warnings, not
/// refusals: the resident's `sex` is the fact, and a sheet is what someone believes or wrote.
/// Logged at genesis (`seed::populate`); verify-generation reads them.
pub fn sheet_warnings(s: &crate::seed::Seed) -> Vec<String> {
    let residents: Vec<&crate::seed::SeedResident> = s.towns.iter().chain(s.villages.iter()).flat_map(|t| t.residents.iter()).collect();
    let mut said: std::collections::BTreeMap<&str, ((u32, u32), Vec<&str>)> = std::collections::BTreeMap::new();
    for r in &residents {
        for rel in r.sheet.get("relations").and_then(|v| v.as_array()).into_iter().flatten() {
            let Some(name) = rel.get("name").and_then(|v| v.as_str()) else { continue };
            let text = format!("{} {}", rel.get("label").and_then(|v| v.as_str()).unwrap_or(""), rel.get("note").and_then(|v| v.as_str()).unwrap_or(""));
            let (f, m) = rules::told(&text);
            if f + m == 0 {
                continue;
            }
            let e = said.entry(name).or_default();
            e.0 .0 += f;
            e.0 .1 += m;
            e.1.push(r.name.as_str());
        }
    }
    let mut out = Vec::new();
    for r in &residents {
        let (Some(sex), Some((counts, by))) = (Sex::parse(&r.sex), said.get(r.name.as_str())) else { continue };
        if let Some(other) = rules::clear_majority(*counts, 2).filter(|s| *s != sex) {
            out.push(format!("{} is {} in the seed, but the sheets of {} speak of them as {} ({} female, {} male words)", r.name, sex.name(), by.join(", "), other.name(), counts.0, counts.1));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn island() -> crate::seed::Seed {
        serde_json::from_str(include_str!("../../seeds/island.json")).unwrap()
    }

    /// Every authored cast gives every resident a sex, and their own looks agree with it.
    #[test]
    fn authored_casts_give_every_resident_a_sex() {
        for (name, text) in [("island", include_str!("../../seeds/island.json")), ("cullet", include_str!("../../seeds/cullet.json")), ("aske-coast", include_str!("../../seeds/aske-coast.json")), ("plan-test", include_str!("../../seeds/plan-test.json")), ("hamlet", include_str!("../../seeds/hamlet.json")), ("hamlet-6", include_str!("../../seeds/hamlet-6.json")), ("authored-test", include_str!("../../seeds/authored-test.json"))] {
            let s: crate::seed::Seed = serde_json::from_str(text).unwrap();
            let rs: Vec<&crate::seed::SeedResident> = s.towns.iter().chain(s.villages.iter()).flat_map(|t| t.residents.iter()).collect();
            assert!(!rs.is_empty(), "{name}");
            assert!(rs.iter().all(|r| Sex::parse(&r.sex).is_some()), "{name}: a resident without a sex");
            assert_eq!(crate::look::check_sex(&s), Ok(()), "{name}");
        }
    }

    /// The seed check refuses a bad or missing sex in an authored cast, and warns where sheets
    /// speak of a resident as the other sex.
    #[test]
    fn seed_sex_is_checked_and_sheets_warned() {
        let mut v: serde_json::Value = serde_json::from_str(include_str!("../../seeds/island.json")).unwrap();
        v["towns"][0]["residents"][0]["sex"] = "x".into();
        let e = crate::look::check_sex(&serde_json::from_value(v.clone()).unwrap()).unwrap_err();
        assert!(e.contains("\"f\" or \"m\""), "{e}");
        v["towns"][0]["residents"][0].as_object_mut().unwrap().remove("sex");
        let e = crate::look::check_sex(&serde_json::from_value(v.clone()).unwrap()).unwrap_err();
        assert!(e.contains("has no `sex`"), "{e}");
        // A seed without looks whose residents give no sex is not an authored cast: its people
        // take the world's pick.
        let mut h: serde_json::Value = serde_json::from_str(include_str!("../../seeds/hamlet.json")).unwrap();
        for key in ["towns", "villages"] {
            for t in h[key].as_array_mut().unwrap() {
                for r in t["residents"].as_array_mut().unwrap() {
                    r.as_object_mut().unwrap().remove("sex");
                }
            }
        }
        assert_eq!(crate::look::check_sex(&serde_json::from_value(h).unwrap()), Ok(()));
        // Every hand-written cast's sheets agree with its sexes (no warning).
        for text in [include_str!("../../seeds/hamlet.json"), include_str!("../../seeds/hamlet-6.json"), include_str!("../../seeds/authored-test.json"), include_str!("../../seeds/island.json"), include_str!("../../seeds/cullet.json"), include_str!("../../seeds/aske-coast.json")] {
            let s: crate::seed::Seed = serde_json::from_str(text).unwrap();
            assert!(sheet_warnings(&s).is_empty(), "{:?}", sheet_warnings(&s));
        }
        // Aldric's sheet calls Cuth Marrow "wife" and "she": made a man, Cuth is warned of.
        let s = island();
        assert!(sheet_warnings(&s).iter().all(|w| !w.starts_with("Cuth Marrow")), "{:?}", sheet_warnings(&s));
        let mut v: serde_json::Value = serde_json::from_str(include_str!("../../seeds/island.json")).unwrap();
        for t in v["towns"].as_array_mut().unwrap() {
            for r in t["residents"].as_array_mut().unwrap() {
                if r["name"] == "Cuth Marrow" {
                    r["sex"] = "m".into();
                }
            }
        }
        let w = sheet_warnings(&serde_json::from_value(v).unwrap());
        assert!(w.iter().any(|w| w.starts_with("Cuth Marrow is male in the seed") && w.contains("Aldric Marrow")), "{w:?}");
    }
}
