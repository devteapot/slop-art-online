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

#[cfg(test)]
mod tests {
    use super::*;

    fn close(a: f32, b: f32, tol: f32) -> bool {
        (a - b).abs() <= tol
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
    }
}
