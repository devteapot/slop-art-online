//! Cullet's laws against their targets (docs/CULLET_RULES.md): a day of a person's needs run
//! minute by minute through the composed script, exactly as the engine finishes the rates
//! (`Scripts::rates` with the world's day length), and the island's laws through the same
//! simulation for comparison. `cargo test -p living-rules cullet -- --nocapture` prints the table.

use crate::script::{ActorFacts, Scripts, SkillCtx};

const BASE: &str = include_str!("../../scripts/skills.rhai");
const CULLET: &str = include_str!("../../seeds/worlds/cullet/laws.rhai");
/// Cullet's day (its seed's `day_minutes`), in real milliseconds.
pub const CULLET_DAY_MS: u64 = 48 * 60_000;

pub fn cullet() -> Scripts {
    Scripts::with_day(&crate::floors::compose(BASE, CULLET).expect("Cullet's overlay composes"), CULLET_DAY_MS).expect("Cullet's laws compile")
}

pub fn island() -> Scripts {
    Scripts::new(BASE).expect("the shipped script compiles")
}

/// Where a person is and what it does in one game minute.
#[derive(Clone, Copy)]
pub struct Spot {
    pub activity: &'static str,
    pub roof: bool,
    pub fire: bool,
    pub coat: bool,
    pub raining: bool,
    pub winter: bool,
}

pub const AWAKE_INDOORS: Spot = Spot { activity: "", roof: true, fire: false, coat: true, raining: false, winter: false };

/// A body's levels.
#[derive(Clone, Copy, Debug)]
pub struct Levels {
    pub hunger: f32,
    pub energy: f32,
    pub hp: f32,
}

/// Run one game minute at `hour` (hunger and energy clamped 0..100, health to 100).
pub fn minute(s: &Scripts, l: &mut Levels, hour: f32, at: Spot) {
    let mut inv = Vec::new();
    if at.coat {
        inv.push(("cloak".to_string(), 1));
    }
    let actor = ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), hp: l.hp, hunger: l.hunger, energy: l.energy, near_fire: at.fire, near_shelter: at.roof, activity: at.activity.into(), inv, terrain: "grass".into(), ..Default::default() };
    let c = SkillCtx { actor, night: s.is_night(hour), dark: s.dark(hour), hour, season: if at.winter { "winter" } else { "summer" }.into(), raining: at.raining, ..Default::default() };
    let r = s.rates(&c).expect("rates");
    // Real minutes in a game minute.
    let k = (s.hour_ms() / 60_000.0 / 60.0) as f32;
    l.hunger = (l.hunger + r.hunger_per_min * k).clamp(0.0, 100.0);
    l.energy = (l.energy + r.energy_per_min * k).clamp(0.0, 100.0);
    l.hp = (l.hp + r.hp_per_min * k).min(100.0);
}

/// Game hours from `start` at `hour0` until `done`, living by `spot(hour)` (at most `limit` hours).
pub fn hours_until(s: &Scripts, mut l: Levels, hour0: f32, limit: f32, spot: impl Fn(f32) -> Spot, done: impl Fn(&Levels) -> bool) -> Option<f32> {
    for m in 0..(limit * 60.0) as u32 {
        if done(&l) {
            return Some(m as f32 / 60.0);
        }
        let h = (hour0 + m as f32 / 60.0).rem_euclid(24.0);
        minute(s, &mut l, h, spot(h));
    }
    None
}

/// A day of an ordinary life: awake 07:00-23:00 under a roof, asleep in bed 23:00-07:00.
pub fn ordinary(h: f32) -> Spot {
    if (7.0..23.0).contains(&h) { AWAKE_INDOORS } else { Spot { activity: "sleep", ..AWAKE_INDOORS } }
}

/// The outcomes the targets are stated in.
#[derive(Debug, Clone, Copy)]
pub struct Outcomes {
    pub hunger_a_day: f32,
    pub hours_to_hungry: f32,
    pub days_to_starving: f32,
    pub days_starving_to_death: f32,
    pub drain_awake_16h: f32,
    pub bed_hours_to_rest: f32,
    pub rough_hours_to_rest: f32,
    pub sleepless_hours_to_slow: f32,
    pub sleepless_hours_to_harm: f32,
    pub ordinary_night_out_hp: f32,
    pub winter_night_out_hp: f32,
    pub rainy_day_energy: f32,
    pub rainy_day_hp: f32,
    pub healing_a_day: f32,
}

pub fn outcomes(s: &Scripts, slow_below: f32) -> Outcomes {
    let fed = Levels { hunger: 5.0, energy: 100.0, hp: 100.0 };
    let day = |spot: &dyn Fn(f32) -> Spot, from: f32, hours: u32, l0: Levels| {
        let mut l = l0;
        for m in 0..hours * 60 {
            let h = (from + m as f32 / 60.0).rem_euclid(24.0);
            minute(s, &mut l, h, spot(h));
        }
        l
    };
    let after_day = day(&ordinary, 7.0, 24, Levels { hunger: 0.0, ..fed });
    let starving = Levels { hunger: 100.0, energy: 100.0, hp: 100.0 };
    let night_out = |winter: bool| {
        let out = Spot { activity: "sleep", roof: false, fire: false, coat: false, raining: false, winter };
        day(&|_| out, 20.0, 10, Levels { hunger: 20.0, energy: 60.0, hp: 100.0 }).hp - 100.0
    };
    let rain = Spot { activity: "", roof: false, fire: false, coat: false, raining: true, winter: false };
    let rainy = day(&|_| rain, 7.0, 16, Levels { hunger: 5.0, energy: 100.0, hp: 100.0 });
    let dry = day(&|_| Spot { raining: false, ..rain }, 7.0, 16, Levels { hunger: 5.0, energy: 100.0, hp: 100.0 });
    let healed = day(&ordinary, 7.0, 24, Levels { hunger: 5.0, energy: 100.0, hp: 50.0 });
    Outcomes {
        hunger_a_day: after_day.hunger,
        hours_to_hungry: hours_until(s, fed, 7.0, 400.0, ordinary, |l| l.hunger > 50.0).unwrap_or(f32::INFINITY),
        days_to_starving: hours_until(s, fed, 7.0, 2000.0, ordinary, |l| l.hunger >= 100.0).unwrap_or(f32::INFINITY) / 24.0,
        days_starving_to_death: hours_until(s, starving, 7.0, 10_000.0, ordinary, |l| l.hp <= 0.0).unwrap_or(f32::INFINITY) / 24.0,
        drain_awake_16h: 100.0 - day(&|_| AWAKE_INDOORS, 7.0, 16, fed).energy,
        bed_hours_to_rest: hours_until(s, Levels { energy: 100.0 - (100.0 - day(&|_| AWAKE_INDOORS, 7.0, 16, fed).energy), ..fed }, 23.0, 48.0, |_| Spot { activity: "sleep", ..AWAKE_INDOORS }, |l| l.energy >= 99.9).unwrap_or(f32::INFINITY),
        rough_hours_to_rest: hours_until(s, Levels { energy: day(&|_| AWAKE_INDOORS, 7.0, 16, fed).energy, ..fed }, 23.0, 48.0, |_| Spot { activity: "sleep", roof: false, ..AWAKE_INDOORS }, |l| l.energy >= 99.9).unwrap_or(f32::INFINITY),
        sleepless_hours_to_slow: hours_until(s, fed, 7.0, 600.0, |_| AWAKE_INDOORS, |l| l.energy < slow_below).unwrap_or(f32::INFINITY),
        sleepless_hours_to_harm: hours_until(s, fed, 7.0, 600.0, |_| AWAKE_INDOORS, |l| l.energy <= 0.0).unwrap_or(f32::INFINITY),
        ordinary_night_out_hp: night_out(false),
        winter_night_out_hp: night_out(true),
        rainy_day_energy: rainy.energy - dry.energy,
        rainy_day_hp: rainy.hp - dry.hp,
        healing_a_day: healed.hp - 50.0,
    }
}

/// What a person sees: (by day, in the dark, carrying a torch at night, seen in lamplight, seen
/// carrying a light, speech).
pub fn sight(s: &Scripts) -> (f32, f32, f32, f32, f32, f32) {
    let person = |torch: bool, lit: bool, night: bool| {
        let inv = if torch { vec![("torch".to_string(), 1)] } else { vec![] };
        SkillCtx { actor: ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), inv, lit, ..Default::default() }, night, dark: if night { 1.0 } else { 0.0 }, hour: if night { 23.0 } else { 12.0 }, ..Default::default() }
    };
    let sense = |c: &SkillCtx| s.senses_unshared(c).unwrap();
    (sense(&person(false, false, false)).sight, sense(&person(false, false, true)).sight, sense(&person(true, false, true)).sight, s.glow_unshared(&person(false, true, true)).unwrap_or(0.0), s.glow_unshared(&person(true, false, true)).unwrap_or(0.0), sense(&person(false, false, false)).hearing)
}

/// Share of a stack of `item` left after `days` game days, spoiling as the authority spoils it:
/// once a real minute, that minute's share in expectation (`tick::spoil`), carried by a person or
/// kept in a storage (`kept_spoil`).
pub fn kept_after(s: &Scripts, item: &str, days: f64, in_store: bool) -> f64 {
    let rate = s.spoil_per_min(item) * if in_store { s.num_of("kept_spoil", "storage", 1.0 / 3.0) } else { s.num_of("carried_spoil", "person", 1.0) };
    (1.0 - rate).powf(days * 24.0 * s.hour_ms() / 60_000.0)
}

/// Game days until half a stack has spoilt (as [`kept_after`]).
pub fn half_gone_days(s: &Scripts, item: &str, in_store: bool) -> f64 {
    let rate = s.spoil_per_min(item) * if in_store { s.num_of("kept_spoil", "storage", 1.0 / 3.0) } else { s.num_of("carried_spoil", "person", 1.0) };
    if rate <= 0.0 {
        return f64::INFINITY;
    }
    0.5f64.ln() / (1.0 - rate).ln() / (24.0 * s.hour_ms() / 60_000.0)
}

/// Units a resource regrowing `per_min` a real minute (the `regen` the authority keeps) gives in
/// a game day of growing time.
pub fn regrown_a_day(s: &Scripts, per_min: f64) -> f64 {
    per_min * 24.0 * s.hour_ms() / 60_000.0
}

/// Cullet's plan, as `living/tools/cullet_plan.py` writes it.
pub fn cullet_plan() -> serde_json::Value {
    serde_json::from_str(include_str!("../../seeds/worlds/cullet/plan.json")).expect("Cullet's plan parses")
}

/// What the plan's resources give in a game day, by kind (a pool counted once): each node's
/// `regrow_per_h` turned into real time for the day as the authority keeps it, then back into a
/// game day.
pub fn plan_daily(s: &Scripts, plan: &serde_json::Value) -> std::collections::BTreeMap<String, f64> {
    let mut out = std::collections::BTreeMap::new();
    let mut pools = std::collections::BTreeSet::new();
    for r in plan["resources"].as_array().unwrap() {
        let kind = r["kind"].as_str().unwrap();
        let pool = r["pool"].as_str().unwrap_or("");
        if !pool.is_empty() && !pools.insert(pool.to_string()) {
            continue;
        }
        let per_min = r["regrow_per_h"].as_f64().map_or_else(|| s.regrow_per_min(kind, 0.5), |v| (v as f32) as f64 * s.per_minute()) as f32;
        *out.entry(kind.to_string()).or_insert(0.0) += regrown_a_day(s, per_min as f64);
    }
    out
}

/// The goods outcomes in a game day (docs/CULLET_RULES.md): spoiling, regrowth, traps, remains.
#[derive(Debug, Clone)]
pub struct Goods {
    pub fish_left_a_day: f64,
    pub fish_half_gone_days: f64,
    pub fish_half_gone_stored_days: f64,
    pub smoked_half_gone_days: f64,
    pub roots_half_gone_days: f64,
    pub greens_half_gone_days: f64,
    pub store_left_after_6_days: (f64, f64),
    pub traps_a_day: f64,
    pub person_remains_days: f64,
    pub fishing_spot_a_day: f64,
}

pub fn goods(s: &Scripts) -> Goods {
    let day_ms = 24.0 * s.hour_ms();
    Goods {
        fish_left_a_day: kept_after(s, "fish", 1.0, false),
        fish_half_gone_days: half_gone_days(s, "fish", false),
        fish_half_gone_stored_days: half_gone_days(s, "fish", true),
        smoked_half_gone_days: half_gone_days(s, "smoked_fish", false),
        roots_half_gone_days: half_gone_days(s, "roots", false),
        greens_half_gone_days: half_gone_days(s, "greens", false),
        store_left_after_6_days: (kept_after(s, "smoked_fish", 6.0, true), kept_after(s, "roots", 6.0, true)),
        traps_a_day: if s.trap_every_ms() > 0.0 { day_ms / s.trap_every_ms() } else { 0.0 },
        person_remains_days: s.remains_ms("person") / day_ms,
        fishing_spot_a_day: regrown_a_day(s, s.regrow_per_min("fishing_spot", 0.5)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(a: f32, b: f32, tol: f32) -> bool {
        (a - b).abs() <= tol
    }

    /// A seed's own know-how is taught like the base ones (glassmaking was refused as "no
    /// technique": teaching checked what experimenting can reveal).
    #[test]
    fn cullet_s_glassmaking_can_be_taught() {
        use crate::script::{ActorFacts, SkillCtx, TargetFacts};
        let s = cullet();
        let c = SkillCtx {
            actor: ActorFacts { kind: "person".into(), stage: "adult".into(), knows: vec!["fire".into(), "glassmaking".into()], ..Default::default() },
            target: TargetFacts { class: "creature".into(), kind: "person".into(), id: 9, alive: true, stage: "adult".into(), knows: vec!["fire".into()], ..Default::default() },
            item: "glassmaking".into(),
            skill: "teach".into(),
            ..Default::default()
        };
        assert_eq!(s.check("teach", &c), Ok(()));
        let mut c = c;
        c.target.knows.clear();
        assert!(s.check("teach", &c).unwrap_err().contains("must first learn fire"));
    }

    #[test]
    fn cullet_s_laws_pass_their_install_checks() {
        let s = cullet();
        s.validate().expect("Cullet's laws pass the install checks");
        assert_eq!(s.hour_ms(), 120_000.0);
        assert!(s.world_text(&[]).starts_with("One day lasts 48 real minutes; night is 20:00-06:00. Dusk and dawn each take about 1 hour"), "{}", s.world_text(&[]));
    }

    #[test]
    fn cullet_s_needs_meet_the_survival_targets() {
        let o = outcomes(&cullet(), 35.0);
        println!("{o:#?}");
        // Two meals a day: about 48 hunger a game day, two meals of 24.
        assert!(close(o.hunger_a_day, 48.0, 0.5), "{}", o.hunger_a_day);
        // Missing a meal changes nothing; a whole day without food makes one hungry.
        assert!(o.hours_to_hungry > 18.0 && o.hours_to_hungry <= 26.0, "{}", o.hours_to_hungry);
        // Harm only after about two days without food; death about eight days after that.
        assert!(o.days_to_starving > 1.8 && o.days_to_starving < 2.3, "{}", o.days_to_starving);
        assert!(o.days_starving_to_death > 7.5 && o.days_starving_to_death < 9.0, "{}", o.days_starving_to_death);
        // About 16 hours awake and 8 asleep; rough sleep restores at half a bed's rate.
        assert!(close(o.bed_hours_to_rest, 8.0, 0.2) && close(o.rough_hours_to_rest, 16.0, 0.3), "{} {}", o.bed_hours_to_rest, o.rough_hours_to_rest);
        // One night without sleep: a slow walk the next morning; harm only in the second night.
        assert!(o.sleepless_hours_to_slow > 24.0 && o.sleepless_hours_to_slow < 30.0, "{}", o.sleepless_hours_to_slow);
        assert!(o.sleepless_hours_to_harm > 36.0 && o.sleepless_hours_to_harm < 48.0, "{}", o.sleepless_hours_to_harm);
        // An ordinary night outside costs nothing; a winter night outside about 15; rain tires
        // and does not harm.
        assert_eq!(o.ordinary_night_out_hp.min(0.0), 0.0, "{}", o.ordinary_night_out_hp);
        assert!(o.winter_night_out_hp < -13.0 && o.winter_night_out_hp > -17.0, "{}", o.winter_night_out_hp);
        assert!(o.rainy_day_energy < -10.0 && o.rainy_day_hp == 0.0, "{} {}", o.rainy_day_energy, o.rainy_day_hp);
    }

    #[test]
    fn cullet_s_sight_is_its_law_values() {
        assert_eq!(sight(&cullet()), (48.0, 14.0, 20.0, 28.0, 48.0, 12.0));
        // The island keeps its own.
        assert_eq!(sight(&island()), (11.0, 6.0, 9.0, 0.0, 0.0, 9.0));
    }

    #[test]
    fn cullet_s_sight_takes_the_field_when_the_law_is_on() {
        let c = SkillCtx { actor: ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), ..Default::default() }, dark: 0.0, ..Default::default() };
        assert_eq!(cullet().senses(&c).unwrap().field, None, "off as shipped");
        let src = crate::script::with_world_laws(&crate::floors::compose(BASE, CULLET).unwrap(), &[("fov_on".into(), serde_json::json!(true))]);
        let on = Scripts::with_day(&src, CULLET_DAY_MS).unwrap();
        on.validate().unwrap();
        let s = on.senses(&c).unwrap();
        assert_eq!((s.sight, s.field.map(|f| (f.focal_deg, f.side_deg, f.near_m))), (48.0, Some((70.0, 110.0, 3.0))));
    }

    #[test]
    fn dusk_and_dawn_take_an_hour_and_night_is_where_it_was() {
        let s = cullet();
        let at = |h: f32| s.daylight(h);
        assert_eq!((at(12.0), at(1.0)), (1.0, 0.0));
        assert!(at(19.75) > 0.5 && at(19.75) < 1.0 && at(20.25) < 0.5 && at(20.25) > 0.0);
        for (h, night) in [(19.99, false), (20.02, true), (5.98, true), (6.0, false)] {
            assert_eq!(s.is_night(h), night, "at {h}");
            assert_eq!(island().is_night(h), night, "the island at {h}");
        }
        // Sight eases with the light.
        let mut c = SkillCtx { actor: ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), ..Default::default() }, ..Default::default() };
        c.dark = s.dark(20.0);
        let mid = s.senses(&c).unwrap().sight;
        assert!(mid > 14.0 && mid < 48.0, "{mid}");
    }

    #[test]
    fn names_only_within_knowing_distance() {
        let s = cullet();
        assert!(s.regard_reads_dist() && !island().regard_reads_dist());
        let p = |dist: u16| crate::script::RegardIn { observer_kind: "person".into(), target_kind: "person".into(), known: true, dist, ..Default::default() };
        assert!(s.perceived_of(&p(24)).name && !s.perceived_of(&p(25)).name);
        assert_eq!(s.perceived_of(&p(30)).health, crate::script::Precision::None);
        // Past it someone is too far away to make out, known or not; within it, not (far-label).
        assert!(s.perceived_of(&p(25)).far && !s.perceived_of(&p(24)).far);
        let stranger = |dist: u16| crate::script::RegardIn { known: false, ..p(dist) };
        assert!(s.perceived_of(&stranger(40)).far && !s.perceived_of(&stranger(10)).far && !s.perceived_of(&stranger(10)).name);
        assert!(!island().perceived_of(&p(40)).far);
        assert!(s.structure("lamp").lights > 0.0 && s.structure("campfire").lights > 0.0 && island().widest_light() == 0.0);
    }

    /// The island's rates did not change in real time: they are the old per-minute numbers.
    #[test]
    fn the_island_s_real_time_rates_are_unchanged() {
        let o = outcomes(&island(), 10.0);
        println!("{o:#?}");
        // 14.4 hunger a game day; hungry about 33 game hours (16-17 real minutes) after a meal.
        assert!(close(o.hunger_a_day, 0.6 * 16.0 + 0.3 * 8.0, 0.05), "{}", o.hunger_a_day);
    }

    /// Prints docs/CULLET_RULES.md's outcome table from the scripts.
    /// Cullet's goods per game day against SMALL_CITY §2 and §4: raw fish gone in about a day,
    /// stored food that lasts the six days it is meant to, and a land that yields 1.3 times what
    /// 64 residents and 10 players eat, fish 55%, roots 30%, greens 15%, with peat the tight
    /// resource (the cutters bring in about 70% of what the Cone and the homes burn, and the
    /// Cone's stock lasts 12 days of full firing).
    #[test]
    fn cullet_s_goods_meet_their_targets_in_a_game_day() {
        let (c, i) = (goods(&cullet()), goods(&island()));
        println!("cullet {c:#?}\nisland {i:#?}");
        // Raw fish: half gone in about a day, carried; a storage keeps it three times longer.
        assert!(c.fish_half_gone_days > 0.9 && c.fish_half_gone_days < 1.4, "{}", c.fish_half_gone_days);
        assert!(close(c.fish_half_gone_stored_days as f32, 3.0 * c.fish_half_gone_days as f32, 0.05), "{}", c.fish_half_gone_stored_days);
        // The same per game day as on the island, but for the sweep's step: the authority spoils
        // once a real minute, 12 times an island day and 48 times a Cullet day.
        assert!((c.fish_left_a_day - i.fish_left_a_day).abs() < 0.01, "{} {}", c.fish_left_a_day, i.fish_left_a_day);
        // Smoked fish keeps for weeks, roots about a fortnight, greens a day or so.
        assert!(c.smoked_half_gone_days > 25.0 && c.roots_half_gone_days > 12.0 && c.roots_half_gone_days < 18.0, "{c:?}");
        assert!(c.greens_half_gone_days > 0.8 && c.greens_half_gone_days < 1.6, "{}", c.greens_half_gone_days);
        // The Store's food mostly lasts the six days it is meant for: about 5% of the smoked fish
        // and 9% of the roots spoil over them if none were eaten (the plan stocks no margin).
        assert!(c.store_left_after_6_days.0 > 0.95 && c.store_left_after_6_days.1 > 0.90, "{:?}", c.store_left_after_6_days);
        // No small game on the Wrack; the dead lie two days.
        assert_eq!(c.traps_a_day, 0.0);
        assert!(close(c.person_remains_days as f32, 2.0, 1e-6));
        // The island: one meat in 3 game days, remains for 5 game days, as before in real time.
        assert!(close(i.traps_a_day as f32, 3.0, 1e-6) && close(i.person_remains_days as f32, 5.0, 1e-6), "{i:?}");

        let s = cullet();
        let daily = plan_daily(&s, &cullet_plan());
        println!("{daily:#?}");
        let n = |item: &str| s.num_of("nutrition", item, 0.0);
        let eaten = 74.0 * 48.0;
        let fish = (daily["fishing_spot"] + daily["weir"]) * n("smoked_fish");
        let roots = daily["root_plot"] * n("baked_roots");
        let greens = daily["greens_bed"] * n("greens");
        let all = fish + roots + greens;
        assert!(all / eaten > 1.28 && all / eaten < 1.35, "yield {:.2} of what is eaten", all / eaten);
        assert!(close((fish / all) as f32, 0.55, 0.01) && close((roots / all) as f32, 0.30, 0.01) && close((greens / all) as f32, 0.15, 0.01), "{fish} {roots} {greens}");
        // Peat: the Cone at full firing and the homes about as much; the cutters bring 70%.
        let furnace = s.structure("furnace").burns.as_ref().unwrap().rate as f64 * 24.0;
        assert!(close((daily["peat_bank"] / (2.0 * furnace)) as f32, 0.70, 0.01), "{}", daily["peat_bank"]);
    }

    #[test]
    #[ignore]
    fn print_cullet_table() {
        let (c, i) = (outcomes(&cullet(), 35.0), outcomes(&island(), 10.0));
        let rows: [(&str, f32, f32); 14] = [
            ("Hunger gained in a game day (awake 16 h, asleep 8 h)", i.hunger_a_day, c.hunger_a_day),
            ("Game hours from a meal (hunger 5) to hungry (over 50)", i.hours_to_hungry, c.hours_to_hungry),
            ("Game days from a meal to starving (100)", i.days_to_starving, c.days_to_starving),
            ("Game days starving until death, from full health", i.days_starving_to_death, c.days_starving_to_death),
            ("Energy spent in 16 waking hours", i.drain_awake_16h, c.drain_awake_16h),
            ("Game hours in a bed to be rested again", i.bed_hours_to_rest, c.bed_hours_to_rest),
            ("Game hours sleeping rough to be rested again", i.rough_hours_to_rest, c.rough_hours_to_rest),
            ("Game hours awake until a slow walk", i.sleepless_hours_to_slow, c.sleepless_hours_to_slow),
            ("Game hours awake until harm (energy 0)", i.sleepless_hours_to_harm, c.sleepless_hours_to_harm),
            ("Health lost sleeping out an ordinary night, no coat", -i.ordinary_night_out_hp, -c.ordinary_night_out_hp),
            ("Health lost sleeping out a winter night, no coat", -i.winter_night_out_hp, -c.winter_night_out_hp),
            ("Energy a rainy day outside costs, no coat", -i.rainy_day_energy, -c.rainy_day_energy),
            ("Health a rainy day outside costs", -i.rainy_day_hp, -c.rainy_day_hp),
            ("Health healed in a game day, fed and rested", i.healing_a_day, c.healing_a_day),
        ];
        println!("| Outcome | Island (12-minute day) | Cullet (48-minute day) |\n| --- | ---: | ---: |");
        for (what, a, b) in rows {
            println!("| {what} | {:.1} | {:.1} |", a + 0.0, b + 0.0);
        }
        println!("sight island {:?} cullet {:?}", sight(&island()), sight(&cullet()));
        let (c, i) = (goods(&cullet()), goods(&island()));
        let goods_rows: [(&str, f64, f64); 9] = [
            ("Raw fish left after a game day, carried", i.fish_left_a_day, c.fish_left_a_day),
            ("Game days until half of raw fish is gone, carried", i.fish_half_gone_days, c.fish_half_gone_days),
            ("The same in a storage", i.fish_half_gone_stored_days, c.fish_half_gone_stored_days),
            ("Game days until half of smoked fish is gone, carried", i.smoked_half_gone_days, c.smoked_half_gone_days),
            ("Game days until half of roots are gone, carried", i.roots_half_gone_days, c.roots_half_gone_days),
            ("Game days until half of greens are gone, carried", i.greens_half_gone_days, c.greens_half_gone_days),
            ("Smoked fish and roots left in a storage after 6 game days", i.store_left_after_6_days.0, c.store_left_after_6_days.0),
            ("Meat a trap catches in a game day", i.traps_a_day, c.traps_a_day),
            ("Game days a person's remains lie", i.person_remains_days, c.person_remains_days),
        ];
        for (what, a, b) in goods_rows {
            println!("| {what} | {a:.3} | {b:.3} |");
        }
        println!("roots left in a storage after 6 days: island {:.3} cullet {:.3}; a fishing spot (unpooled) regrows island {:.1} cullet {:.1} a game day", i.store_left_after_6_days.1, c.store_left_after_6_days.1, i.fishing_spot_a_day, c.fishing_spot_a_day);
        println!("Cullet's plan, a game day: {:#?}", plan_daily(&cullet(), &cullet_plan()));
    }
}

#[cfg(test)]
mod life_tests {
    use super::*;

    fn species() -> Vec<(String, crate::life::Life)> {
        let v: serde_json::Value = serde_json::from_str(include_str!("../../seeds/species.json")).unwrap();
        v.as_object().unwrap().iter().filter_map(|(k, s)| Some((k.clone(), serde_json::from_value(s.get("life")?.clone()).ok()?))).collect()
    }

    fn same(a: crate::life::Life, b: crate::life::Life) -> bool {
        [a.years, a.infant, a.child, a.elder, a.old_age, a.gestation, a.interbirth, a.breeding_radius].map(f32::to_bits) == [b.years, b.infant, b.child, b.elder, b.old_age, b.gestation, b.interbirth, b.breeding_radius].map(f32::to_bits) && a.litter == b.litter
    }

    /// Without a `life_years` law (the shipped script: every world but Cullet) each species'
    /// table is exactly `species.json`'s.
    #[test]
    fn worlds_without_the_law_keep_the_species_tables() {
        let s = island();
        assert!(!s.has("life_years"));
        for (k, l) in species() {
            assert!(same(s.life(&k, l), l), "{k}");
        }
    }

    /// Cullet's people: a child until 15, deaths of old age from 75 to 90; infancy, old age as a
    /// stage (59.5) and pregnancy keep their years; animals keep their tables.
    #[test]
    fn cullet_people_live_longer_and_grow_up_sooner() {
        let s = cullet();
        s.validate().expect("Cullet's laws install");
        for (k, base) in species() {
            let l = s.life(&k, base);
            if k != "person" {
                assert!(same(l, base), "{k}");
                continue;
            }
            let y = |f: f32| f * l.years;
            let close = |a: f32, b: f32| (a - b).abs() < 1e-3;
            assert!(close(l.years, 90.0) && close(y(l.child), 15.0) && close(y(l.old_age), 75.0), "{l:?}");
            assert!(close(y(l.infant), base.infant * base.years) && close(y(l.elder), base.elder * base.years) && close(y(l.gestation), base.gestation * base.years));
            let pace = crate::life::Pace { year_days: 8.0, pace: 1.0 };
            let at = |years: f32| l.stage(years * 8.0, pace);
            assert_eq!(at(14.9), crate::life::Stage::Child);
            assert_eq!(at(15.0), crate::life::Stage::Adult);
            assert_eq!(at(59.0), crate::life::Stage::Adult);
            assert_eq!(at(61.0), crate::life::Stage::Elder);
            // Nobody dies of old age before 75; the cast's eldest (70) lives on.
            for id in 0..5000 {
                assert!(y(l.deathline(id)) >= 75.0 - 1e-3);
            }
        }
    }

    /// A law that gets the table wrong is refused at install.
    #[test]
    fn a_wrong_life_table_is_refused() {
        let src = crate::floors::compose(BASE, "fn life_years(t) { t.child = 80.0; t }\nfn life_years_law() { #{ cadence: \"compile\", topic: \"\", about: \"x\" } }").unwrap();
        let e = Scripts::new(&src).unwrap().validate().unwrap_err();
        assert!(e.contains("life_years") && e.contains("child"), "{e}");
    }
}

#[cfg(test)]
mod ways_tests {
    use super::*;

    /// Cullet's starting ways (`worlds/cullet/ways.json`, merged into the seed by
    /// cullet_plan.py) are graphs its rules accept: every routine, the top level, and nothing
    /// a person may not do; each trade has a workplace.
    #[test]
    fn cullet_ways_are_valid_graphs() {
        let s = cullet();
        let w: serde_json::Value = serde_json::from_str(include_str!("../../seeds/worlds/cullet/ways.json")).unwrap();
        crate::catalog::scoped(s.skills().clone(), || {
            let parse = |what: &str, g: &serde_json::Value| {
                let g = crate::graph::parse(&g.to_string()).unwrap_or_else(|e| panic!("{what}: {e}"));
                assert!(crate::graph::skills_used(&g.root).iter().all(|k| s.skills().get(k).is_some()), "{what}");
            };
            for (k, g) in w["common"].as_object().unwrap() {
                parse(k, g);
            }
            for (k, o) in w["occupations"].as_object().unwrap() {
                parse(k, &o["graph"]);
                assert!(k == "child" || w["town_life"]["work"].get(k).is_some(), "{k} has no workplace");
            }
            let top = w["top"].to_string().replace("\"WORK\"", "\"fishing\"");
            parse("top", &serde_json::from_str(&top).unwrap());
            let work = w["top"]["desires"].as_array().unwrap().iter().find(|d| d["want"] == "work").unwrap();
            assert!(work["weight"]["work_hours"].as_f64().unwrap() > 0.0);
        });
    }
}
