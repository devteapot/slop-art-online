// Cullet's laws: an overlay over the shipped script (living/scripts/skills.rhai), composed by
// `floors::compose` when the world is created (the seed's `laws_file`). A function here replaces
// the shipped one of the same name, which stays callable as `base_NAME`. Mechanics stay the
// shipped ones; this chooses Cullet's values (docs/SMALL_CITY.md §4 and §5, docs/CULLET_RULES.md).
//
// The day is 48 real minutes (the seed's `day_minutes`): a game hour is two real minutes. Every
// need rate below is per game hour (`per: "hour"`), so these numbers are the balance per game
// day whatever the day length; the engine turns them into real time.

// ---- the day -----------------------------------------------------------------------------

// Dusk and dawn each take about an hour, eased: half light at 20:00 and at 06:00, so night (less
// than half light: cold, and what the minds are told) is 20:00-06:00 as on the island, while
// sight and sleepiness change over the hour around it instead of in one tick.
fn night_hours() { #{ dusk: 20.0, dawn: 6.0, twilight: 1.0 } }

// ---- needs (per game hour; a game day is 24 of them) ------------------------------------------
// Targets (docs/SMALL_CITY.md §4): two meals a day; missing one changes nothing; a whole day
// without food makes one hungry (no harm); harm only after about two days without food, death
// about eight days after that; about 16 hours awake and 8 asleep; a sleepless night means a slow
// walk the next day and harm only after two; sleeping rough restores half as fast as a bed; an
// ordinary night outside costs nothing but poorer rest; only a winter night outside without a
// coat, fire or roof hurts, about 15 health a night; rain tires and does not harm.

// Hunger a game hour awake: 16 hours awake and 8 asleep (at half) make 48 a day, two meals of 24.
fn hunger_awake() { 2.4 }
// Energy a game hour: awake it falls 40 over 16 hours; a bed gives it back over 8, a rough
// sleep half as fast.
fn energy_awake() { -2.5 }
fn sleep_gain(a) { if a.actor.near_shelter { 5.0 } else { 2.5 } }

fn rates(a) {
    if a.actor.kind != "person" { return base_rates(a); }
    let hunger = hunger_awake();
    let energy = energy_awake();
    let act = a.actor.activity;
    if act == "sleep" {
        energy = sleep_gain(a);
        hunger *= 0.5;
    } else if act == "rest" {
        energy = 2.5;
    } else if act == "block" {
        // Bracing in a fight costs what it costs on the island in real time.
        energy = -7.2;
    }
    let healing = 1.0;
    if a.actor.stage == "elder" {
        healing = 0.5;
        if energy < 0.0 { energy *= 1.3; }
    }
    if a.actor.stage == "infant" { hunger *= 0.6; }
    // A body freezing does not heal (else a fed, rested body's healing would cancel the cold).
    let freezing_now = cold(a) && freezing(a);
    if freezing_now { healing = 0.0; }
    #{
        per: "hour",
        hunger: hunger, energy: energy,
        // Starving (hunger 100, about two days after a meal) takes about 8 days to kill.
        starving_at: 100.0, starving_hp: -0.5,
        // Fed and rested, a body heals about 36 a day.
        fed_below: 70.0, rested_above: 15.0, healing_hp: 1.5, healing: healing,
        spent_at: 0.0, spent_hp: -0.4,
        tiring_gene: "endurance", healing_gene: "vitality", appetite_gene: "appetite", hardiness_gene: "hardiness",
        // Rain tires those out from under a roof, less in a coat; an ordinary cold night costs
        // nothing here but the poorer rest of sleeping rough.
        wet_energy: if wet(a) { if inv(a, "cloak") > 0 { -0.5 } else { -1.2 } } else { 0.0 },
        // A winter night outside with no coat, fire or roof: about 15 over its 10 hours.
        cold_hp: if freezing_now { -1.5 } else { 0.0 },
    }
}

// Only winter nights hurt; rain does not.
fn freezing(a) { a.season == "winter" }

// One sleep lasts until rested at Cullet's own rate (at most 150 real seconds; a sleeper not yet
// rested sleeps again).
fn sleep_duration(a) {
    let need = 100.0 - a.actor.energy;
    let ms = need / sleep_gain(a) * hour_ms();
    if ms < 5000.0 { 5000 } else if ms > 150000.0 { 150000 } else { ms.to_int() }
}

// Tired (under 35 energy, about a day and a night without sleep) one walks slowly; exhausted
// (under 10) slower still, as everywhere.
fn tired_below() { 35.0 }
fn move_speed(a) {
    let s = base_move_speed(a);
    if a.actor.energy < tired_below() && a.actor.energy >= 10.0 { s * 0.8 } else { s }
}

// ---- light and sight (docs/SMALL_CITY.md §5; decision 6) --------------------------------------

// How far one sees by day, in the dark, and carrying a light at night; how far speech carries.
fn sight_in(light) { switch light { "day" => 48.0, "torch" => 20.0, _ => 14.0 } }
fn hearing_of_people() { 12.0 }
// Within this one knows who a figure is (its name, its health as a band); beyond it, "a stranger".
fn known_within() { 24.0 }
// How far someone is seen from at night: standing in lamplight, and carrying a light.
fn lamplight_seen() { 28.0 }
fn carried_light_seen() { 48.0 }

// Sight eases from the dark's to the day's with the light.
fn senses(a) {
    let eye = sight_in("night") + (sight_in("day") - sight_in("night")) * a.daylight;
    let torch = if inv(a, "torch") > 0 { sight_in("torch") } else { 0.0 };
    #{ sight: if torch > eye { torch } else { eye }, hearing: hearing_of_people() }
}

// A light on someone shows them farther than the onlooker's own sight in the dark: a carried
// torch at 48 m, lamplight at 28 m. By day it adds nothing.
fn glow(a) {
    if a.daylight >= 1.0 { return 0.0; }
    if inv(a, "torch") > 0 { return carried_light_seen(); }
    if a.actor.lit { return lamplight_seen(); }
    0.0
}

fn senses_law() {
    #{
        cadence: "hot",
        topic: "senses",
        covers: ["glow"],
        reach: #{ day: sight_in("day"), night: sight_in("torch"), hearing: hearing_of_people(), glow: carried_light_seen() },
        about: `How far a creature sees and hears, in metres (one tile is one metre). By day one sees ${short(sight_in("day"))} m; in the dark ${short(sight_in("night"))} m, or ${short(sight_in("torch"))} m carrying a torch; sight grows and shrinks with the light at dusk and dawn. At night anyone standing in lamplight is seen from ${short(lamplight_seen())} m, and anyone carrying a light from ${short(carried_light_seen())} m. Within ${short(known_within())} m you can tell who someone is; farther off they are a figure. Rock, walls and shut gates block the line of sight. Speech carries ${short(hearing_of_people())} m.`,
    }
}

// Who a figure is, only within `known_within` metres.
fn perceived_of(p) {
    let r = base_perceived_of(p);
    if !p.self && p.dist > known_within() {
        r.name = false;
        r.health = "none";
    }
    r
}

// What gives light: a campfire, a lamp, and the public hearths of a hall or an inn.
fn structure_traits() {
    let t = base_structure_traits();
    t.campfire.lights = 6.0;
    t.hall.lights = 6.0;
    t.inn.lights = 6.0;
    t.lamp = #{ lights: 8.0 };
    t
}
