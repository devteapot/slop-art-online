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
    let s = #{ sight: if torch > eye { torch } else { eye }, hearing: hearing_of_people() };
    // Sight that depends on facing, when the world's `fov_on` law turns it on (the shipped
    // field and its laws).
    if law("fov_on") { s.field = sight_field(a); }
    s
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
        about: `How far a creature sees and hears, in metres (one tile is one metre). By day one sees ${short(sight_in("day"))} m; in the dark ${short(sight_in("night"))} m, or ${short(sight_in("torch"))} m carrying a torch; sight grows and shrinks with the light at dusk and dawn. At night anyone standing in lamplight is seen from ${short(lamplight_seen())} m, and anyone carrying a light from ${short(carried_light_seen())} m. Within ${short(known_within())} m you can tell who someone is; farther off they are a figure. Rock, walls and shut gates block the line of sight. Speech carries ${short(hearing_of_people())} m.${field_about()}`,
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

// What gives light: a campfire and the public hearths of a hall or an inn, always; a lamp, and
// every fire that burns fuel, only while it burns (its `burns`, with the goods below).
fn structures() {
    let out = [];
    for k in base_structures() {
        if k.name == "campfire" || k.name == "hall" || k.name == "inn" { k.lights = 6.0; }
        if k.name != "lamp" { out.push(k); }
    }
    out + goods_structures()
}

// ---- goods, fires and recipes (docs/WORLD_RULES.md, "Goods, recipes and fuel") ------------
// Data only (each item's icon, label and group are what a client shows; a recipe looks like its
// product): the rules that read these traits are the shipped script's. The chain: kelp is
// gathered on the Wrack Strand and burnt to ash at any fire; ash and sand are melted into glass
// at the Cone, a furnace that burns peat; fish are smoked over peat at a smokehouse; roots are
// baked at an oven; lamp oil is rendered from fish at a fire and burnt in lamps. The numbers are
// first guesses, to be tuned in the soak (docs/SMALL_CITY.md, phase 4). Rates and durations are in
// game time (`_per_h`, `_h`), turned into real time for the 48-minute day by the engine.

fn items() {
    base_items() + [
        // Gathered on the shore; burnt to ash (4 to 1).
        #{ name: "kelp", icon: "kelp", label: "kelp", group: "material" },
        // Ash is an alkali: glass takes any alkali.
        #{ name: "ash", alkali: true, icon: "ash", label: "ash", group: "material" },
        #{ name: "sand", icon: "sand", label: "sand", group: "material" },
        #{ name: "glass", icon: "glass", label: "glass", group: "glass" },
        // The staple, eaten raw or baked.
        #{ name: "roots", bakes_to: "baked_roots", icon: "roots", label: "roots", group: "food" },
        #{ name: "baked_roots", icon: "baked_roots", label: "baked roots", group: "food" },
        #{ name: "greens", icon: "greens", label: "greens", group: "food" },
        // Cut on the Moss; what hearths, ovens, smokehouses and the Cone burn.
        #{ name: "peat", fuel: 1.0, icon: "peat", label: "peat", group: "fuel" },
        // Rendered from fish; what lamps burn.
        #{ name: "lamp_oil", oil: 1.0, icon: "lamp_oil", label: "lamp oil", group: "fuel" },
    ]
}

fn nutrition(item) {
    switch item {
        "roots" => 14.0,
        "baked_roots" => 30.0,
        "greens" => 10.0,
        _ => base_nutrition(item),
    }
}

// Share of a food that spoils in a game hour (docs/SMALL_CITY.md §4; carried in a pack, a
// storage keeps it three times longer). Raw fish: half gone in a game day, nine tenths in four
// (§4's 1.25% a real minute on the 48-minute day). Smoked fish keeps for weeks; roots keep for
// about a fortnight before half are gone; greens wilt within a day or two.
fn spoil_per_h(item) {
    switch item {
        "fish" => 0.025,
        "cooked_fish" => 0.006,
        "smoked_fish" => 0.001,
        "roots" => 0.002,
        "baked_roots" => 0.01,
        "greens" => 0.03,
        _ => base_spoil_per_h(item),
    }
}

// A storage holds up to 1,000 things: the town's stores are barns (the Store's six days of food,
// the Cone's peat; living/tools/cullet_plan.py). Every storage here, a person's crate as well.
fn storage_holds(x) { 1000 }

// There is no small game on the Wrack: a trap catches nothing (the world does not restock).
fn trap_every_h(x) { 0.0 }

// A person's remains, with what they carried, lie two game days before they are gone.
fn remains_h(kind) { if kind == "person" { 48.0 } else { base_remains_h(kind) } }

// Fires that eat fuel. Rates are units a game hour while lit; warmth and light are metres. A
// lamp is one: it lights only while it has oil.
fn goods_structures() {
    [
        #{ name: "hearth", burns: #{ fuel: "fuel", rate: 0.5, warmth: 4.0, light: 8.0, holds: 12.0 } },
        #{ name: "oven", burns: #{ fuel: "fuel", rate: 1.0, warmth: 2.5, light: 3.0, holds: 8.0 } },
        // The Cone: the town's glass furnace, burning about as much as all the homes together.
        #{ name: "furnace", burns: #{ fuel: "fuel", rate: 3.0, warmth: 6.0, light: 10.0, holds: 40.0 } },
        #{ name: "smokehouse", roof: true, burns: #{ fuel: "fuel", rate: 0.5, warmth: 2.0, light: 2.0, holds: 8.0 } },
        #{ name: "lamp", lights: 8.0, burns: #{ fuel: "oil", rate: 0.25, light: 8.0, holds: 8.0 } },
    ]
}

// What the land gives, a game hour of growing time (no winter) per node, up to its max. A
// fishing ground's spots share one stock when the plan or seed says so (a resource node's
// `pool`); the plan gives each ground its own stock and regrowth. Starting values for the soak
// against docs/SMALL_CITY.md §2 (about 1.3 times what 64 residents and 10 players eat; fish 55%,
// roots 30%, greens 15%; peat the tight resource), computed in living/tools/cullet_plan.py, which
// writes each node's own values into the plan; these are a node's of each kind when nothing says
// otherwise, and hold about two days of regrowth (docs/CULLET_RULES.md, "Cullet's goods, placed").
fn resources() {
    base_resources() + [
        // 12 beds on the Wrack Strand: 60 kelp a day, ash for about 12 glass and kelp for the plots.
        #{ name: "kelp_bed", yields: "kelp", regrow_per_h: 0.208, max: 10.0, ground: ["sand"], by_water: true, gather_ms: 2500 },
        // 6 banks on the Sand Spit: 24 sand a day, two to a glass.
        #{ name: "sand_bank", yields: "sand", regrow_per_h: 0.167, max: 8.0, ground: ["sand"], gather_ms: 2000 },
        // 18 cuttings on the Moss: about 100 peat a day, 70% of what the Cone and the homes burn.
        #{ name: "peat_bank", yields: "peat", regrow_per_h: 0.233, max: 11.2, ground: ["grass", "dirt"], gather_ms: 5000 },
        // 18 plots: about 46 roots a day, 30% of the food baked (30 each).
        #{ name: "root_plot", yields: "roots", regrow_per_h: 0.107, max: 6.0, ground: ["dirt", "grass"], gather_ms: 3000 },
        // 11 working glasshouses: about 69 greens a day, 15% of the food.
        #{ name: "greens_bed", yields: "greens", regrow_per_h: 0.262, max: 12.6, ground: ["grass"], gather_ms: 2000 },
        // A fish trap in the shallows (the Weirs share one stock: the plan's pool).
        #{ name: "weir", yields: "fish", regrow_per_h: 0.176, max: 8.5, ground: ["sand"], by_water: true, gather_ms: 4000 },
    ]
}

fn know_how() {
    base_know_how() + [
        #{ name: "glassmaking", help: "melt ash and sand into glass at a burning furnace", brief: "glass from ash and sand at the furnace", requires: ["fire"] },
    ]
}

fn recipes() {
    [
        #{ name: "ash", at: "fire", lit: true, takes: #{ kelp: 4 }, ms: 6000 },
        #{ name: "glass", at: "furnace", lit: true, takes: #{ alkali: 1, sand: 2 }, fuel: 1.0, knows: "glassmaking", ms: 15000 },
        #{ name: "smoking", turns: "smokes_to", at: "smokehouse", lit: true, fuel: 0.5, knows: "smoking", ms: 10000 },
        #{ name: "baking", turns: "bakes_to", at: "oven", lit: true, fuel: 0.25, ms: 6000 },
        #{ name: "lamp_oil", at: "fire", lit: true, takes: #{ fish: 2 }, ms: 8000 },
    ]
}


// ---- life (docs/CULLET_RULES.md, "People's lives") ----------------------------------------
// The engine gives this law each species' life table in years (`species.json`: a person lives
// 70 years, a child until 16.1, old from 59.5, deaths of old age from 60.9) and uses what it
// returns. On the Wrack people live longer and grow up sooner: childhood ends at 15, deaths of old
// age begin at 75 (each person's own point between 75 and the lifespan, 90). Infancy (2.1 years),
// being old from 59.5, pregnancy and the years between births keep their ages. Animals keep
// theirs.
fn person_years() { #{ lifespan: 90.0, child: 15.0, old_age: 75.0 } }

fn life_years(t) {
    if t.kind != "person" { return t; }
    let y = person_years();
    for k in y.keys() { t[k] = y[k]; }
    t
}

fn life_years_law() {
    let y = person_years();
    #{ cadence: "compile", topic: "",
       about: `People live up to about ${short(y.lifespan)} years: a child until ${short(y.child)}, and deaths of old age come from about ${short(y.old_age)}.` }
}
