// Living core skill and needs rules. Functions only; the authority calls them at
// action start (check, duration) and completion (done), and when need rates change.
// `a.actor`, `a.target`, `a.item`, `a.qty`, `a.night`, `a.hour` — see rules/src/script.rs.

// ---- world laws (read once per script revision; parameters for the engine) ----------

fn laws() {
    #{
        sight_day: 11.0, sight_night: 6.0, sight_torch: 9.0, hearing: 9.0,
        fire_warmth: 3.5, shelter_warmth: 2.5,
        gestation_days: 1.0, bond_window_s: 120.0,
        crowd: 6, danger_near: 8.0, danger_far: 12.0,
        repeat_failure_s: 120.0,
        road_speed: 1.4,
        // Steering: how bodies turn, slow, keep apart and how often they look again.
        turn_rate: 6.0, turn_slow: 0.4, slow_radius: 1.2, corner_radius: 0.9,
        separation: 0.8, separation_weight: 0.9,
        steer_s: 2.0, crowd_hz: 3.0, chase_hz: 4.0, combat_hz: 8.0,
        run_speed: 1.5, input_hz: 30.0, input_burst: 15.0,
        // Grass regrowth per grassy tile per growing minute: about one grazer per 300 grassy
        // tiles (it was one per 70, and the wilds filled with deer).
        pasture_regen: 0.0015,
        // Someone with no other person within this many tiles is alone (predators dare more).
        alone_within: 6.0,
        // A body within this many radians of facing something already faces it.
        face_slack: 0.35,
        // Seconds a played character stands with no connection of its person before the
        // world's minds take it over (it keeps living; the person takes it back on return).
        takeover_s: 30.0,
    }
}

// What an observer perceives of a target it sees (docs/PERCEPTION.md). `p.observer` has
// `kind` and `knows`; `p.target` has `kind`, `known` (its name is known to the observer) and
// `revealed` (what a skill use such as `appraise` shows for a while); `p.self`, `p.night`.
// Returns which fields the observer gets: `name` (else a label such as "a stranger") and
// `health` ("band", "exact" or "none").
fn perceived_of(p) {
    let name = p.self || p.target.known || (p.observer.kind != "person" && p.observer.kind == p.target.kind);
    let health = if p.self || p.target.revealed.contains("health") { "exact" } else { "band" };
    #{ name: name, health: health }
}

fn knows(a, t) { a.actor.knows.contains(t) }

fn inv(a, item) {
    let n = a.actor.inv[item];
    if n == () { 0 } else { n }
}

// ---- carrying and spoiling -------------------------------------------------

// How many things a body can carry (a person's pack; an animal carries a mouthful).
fn carry_limit(kind) { switch kind { "person" => 40.0, _ => 6.0 } }
fn carried(a) {
    let n = 0;
    for k in a.actor.inv.keys() { n += a.actor.inv[k]; }
    n
}
// A basket carries 20 more.
fn pack_full(a) { carried(a) >= carry_limit(a.actor.kind) + if inv(a, "basket") > 0 { 20.0 } else { 0.0 } }
// Share of a food that spoils per real minute (a lab day is 12 minutes): raw meat and fish
// within about a day, berries in a few days, cooked food more slowly. A storage keeps food
// three times longer.
fn spoil_rate(item) {
    switch item {
        "meat" => 0.05,
        "fish" => 0.05,
        "berries" => 0.02,
        "cooked_meat" => 0.012,
        "cooked_fish" => 0.012,
        // Smoked food keeps for weeks: something to carry to another town.
        "smoked_meat" => 0.002,
        "smoked_fish" => 0.002,
        _ => 0.0,
    }
}
// Share of that rate for food an animal carries: a predator gorges at its kill and keeps the
// rest by it, so a deer feeds a wolf for about an hour instead of mostly rotting.
fn carried_spoil(kind) { switch kind { "person" => 1.0, _ => 0.25 } }

fn nutrition(item) {
    switch item {
        "berries" => 12.0,
        "fish" => 16.0,
        "meat" => 20.0,
        "cooked_fish" => 34.0,
        "cooked_meat" => 42.0,
        "smoked_fish" => 24.0,
        "smoked_meat" => 30.0,
        _ => 0.0,
    }
}

// ---- needs -------------------------------------------------------------

fn cold(a) {
    a.night && a.actor.kind == "person" && !a.actor.near_fire && !a.actor.near_shelter && inv(a, "cloak") == 0
}

fn wet(a) { a.raining && a.actor.kind == "person" && !a.actor.near_shelter }

fn body_state(a) {
    let fraction = a.actor.hp / (max_hp(a.actor.kind) * a.actor.vitality);
    #{ cold: cold(a), hungry: a.actor.hunger > 55.0, starving: a.actor.hunger >= 100.0,
       wound: if fraction < 0.15 { "barely alive" } else if fraction < 0.35 { "badly wounded" }
              else if fraction < 0.6 || a.actor.hurt_ago < 5000 { "hurt" } else { "" } }
}

// Need rates per minute for a body's state. The engine asks this when the state changes and
// keeps the answer for every body in the same state; it then finishes the rates for each body's
// own hunger, energy and genes with the numbers given here (rules/src/script.rs `NeedLaw`):
//   hunger, energy            the state's rates (energy before the tiring gene)
//   starving_at, starving_hp  at or above this hunger, health changes by starving_hp
//   fed_below, rested_above   otherwise, below this hunger and above this energy, health
//   healing_hp                changes by healing_hp, times `healing` (age)
//   spent_at, spent_hp        at or below this energy, health changes by spent_hp as well
//   tiring_gene               a falling energy rate is divided by this gene
//   healing_gene              a rising health rate is multiplied by this gene
//   wet_energy, cold_hp       exposure, added last
fn rates(a) {
    // A predator feeds big and rarely: a wolf lasts about an hour on a deer.
    let hunger = switch a.actor.kind { "deer" => 6.0, "wolf" => 1.5, _ => 5.0 };
    let energy = -3.0;
    let act = a.actor.activity;
    if act == "sleep" {
        energy = if a.actor.near_shelter { 26.0 } else { 16.0 };
        hunger *= 0.5;
    } else if act == "rest" {
        energy = 6.0;
    } else if act == "block" {
        energy = -12.0;
    }
    // Elders heal slower and tire sooner; infants get hungry more slowly. (Death of old age
    // comes at each creature's own point late in its lifespan.)
    let healing = 1.0;
    if a.actor.stage == "elder" {
        healing = 0.5;
        energy *= 1.3;
    }
    // A suckling animal lives mostly on its mother's milk (not modelled on the mother).
    if a.actor.stage == "infant" { hunger *= if a.actor.kind == "person" { 0.6 } else { 0.3 }; }
    #{
        hunger: hunger, energy: energy,
        // Starving hurts; fed and rested, a body heals; with no energy left, it suffers.
        starving_at: 100.0, starving_hp: -6.0,
        fed_below: 70.0, rested_above: 15.0, healing_hp: 3.0, healing: healing,
        spent_at: 0.0, spent_hp: -2.0,
        // Inborn endurance slows tiring; vitality speeds healing.
        tiring_gene: "endurance", healing_gene: "vitality",
        // Rain soaks people out from under a roof (a cloak keeps some of it off): it is tiring.
        wet_energy: if wet(a) { if inv(a, "cloak") > 0 { -1.0 } else { -2.5 } } else { 0.0 },
        // Cold nights hurt people without a fire, shelter or warm cloak; winter nights are worse.
        cold_hp: if cold(a) { if a.season == "winter" { -5.0 } else { -2.0 } } else { 0.0 },
    }
}

fn move_speed(a) {
    let base = switch a.actor.kind { "deer" => 3.7, "wolf" => 3.4, _ => 2.6 };
    if a.actor.stage == "infant" { base *= 0.4; } else if a.actor.stage == "child" { base *= 0.8; } else if a.actor.stage == "elder" { base *= 0.85; }
    base *= a.actor.speed;
    if a.actor.energy < 10.0 { base * 0.6 } else { base }
}

// ---- gathering and food ------------------------------------------------

fn gather_check(a) {
    if a.target.class != "resource" { return "that is not something to gather"; }
    if a.target.amount < 1.0 { return `the ${a.target.kind} is depleted`; }
    if a.actor.kind != "person" { return "only people gather"; }
    if a.actor.stage == "infant" { return "too small to gather"; }
    if pack_full(a) { return "your pack is full (eat, store, give or drop some first)"; }
    ""
}
fn gather_duration(a) {
    switch a.target.kind {
        "berry_bush" => 2000,
        "reeds" => 2500,
        "tree" => if inv(a, "axe") > 0 { 2000 } else { 4000 },
        "boulder" => if inv(a, "pick") > 0 { 2500 } else { 5000 },
        "clay_bank" => 3000,
        "fishing_spot" => if inv(a, "spear") > 0 { 3000 } else { 6500 },
        _ => 3000,
    }
}
// What one gathering at each resource yields.
fn yield_of(kind) {
    switch kind {
        "berry_bush" => "berries",
        "tree" => "wood",
        "boulder" => "stone",
        "reeds" => "fiber",
        "fishing_spot" => "fish",
        "clay_bank" => "clay",
        _ => "",
    }
}
fn gather_done(a) {
    // A net brings in two fish at a time.
    let n = if a.target.kind == "fishing_spot" && inv(a, "net") > 0 { 2 } else { 1 };
    [#{ op: "harvest", qty: n }, #{ op: "add", item: yield_of(a.target.kind), qty: n }, #{ op: "vitals", energy: -1.0 }]
}

fn eat_check(a) {
    if nutrition(a.item) <= 0.0 { return `${a.item} is not food`; }
    if inv(a, a.item) < 1 { return `no ${a.item} in your pack (${a.item}: ${source_of(a.item)})`; }
    ""
}
fn eat_duration(a) { 1500 }
fn eat_done(a) {
    [#{ op: "remove", item: a.item, qty: 1 }, #{ op: "vitals", hunger: -nutrition(a.item), hp: 1.0 }]
}

fn cook_check(a) {
    if !knows(a, "cooking") { return "you don't know how to cook" + learn_how("cooking"); }
    if a.target.kind != "campfire" { return "cooking needs a campfire"; }
    if a.item != "fish" && a.item != "meat" { return "only raw fish or meat can be cooked"; }
    if inv(a, a.item) < 1 { return `no ${a.item} in your pack (${a.item}: ${source_of(a.item)})`; }
    ""
}
fn cook_duration(a) { 4000 }
fn cook_done(a) {
    [#{ op: "remove", item: a.item, qty: 1 }, #{ op: "add", item: "cooked_" + a.item, qty: 1 }]
}

fn smoke_check(a) {
    if !knows(a, "smoking") { return "you don't know how to smoke food" + learn_how("smoking"); }
    if a.target.kind != "campfire" { return "smoking needs a campfire"; }
    if a.item != "fish" && a.item != "meat" { return "only raw fish or meat can be smoked"; }
    if inv(a, a.item) < 1 { return `no ${a.item} in your pack (${a.item}: ${source_of(a.item)})`; }
    ""
}
fn smoke_duration(a) { 10000 }
fn smoke_done(a) {
    [#{ op: "remove", item: a.item, qty: 1 }, #{ op: "add", item: "smoked_" + a.item, qty: 1 }]
}

// Clearing forest: the tile becomes open ground, and yields wood.
fn clear_check(a) {
    if a.actor.kind != "person" || young(a) { return "you cannot clear land"; }
    if a.actor.terrain != "forest" { return "there is no forest to clear where you stand"; }
    if pack_full(a) { return "your pack is full (eat, store, give or drop some first)"; }
    ""
}
fn clear_duration(a) { if inv(a, "axe") > 0 { 6000 } else { 12000 } }
fn clear_done(a) { [#{ op: "build", kind: "clearing" }, #{ op: "add", item: "wood", qty: 2 }, #{ op: "vitals", energy: -3.0 }] }

fn graze_check(a) {
    if a.actor.kind != "deer" { return "only deer graze"; }
    if a.actor.terrain != "grass" && a.actor.terrain != "forest" { return "no grass here"; }
    if a.actor.pasture < 1.0 { return "the grass here is grazed bare"; }
    ""
}
fn graze_duration(a) { 4000 }
// Each grazing eats a share of the chunk's grass (see pasture); bare ground feeds nothing.
fn graze_done(a) { [#{ op: "vitals", hunger: -14.0 }] }

// ---- rest ---------------------------------------------------------------

fn sleep_duration(a) {
    let rate = if a.actor.near_shelter { 26.0 } else { 16.0 };
    let need = 100.0 - a.actor.energy;
    let ms = need / rate * 60000.0;
    if ms < 5000.0 { 5000 } else if ms > 150000.0 { 150000 } else { ms.to_int() }
}
fn rest_duration(a) { 8000 }
fn wait_duration(a) { if a.qty > 0 { if a.qty > 120 { 120000 } else { a.qty * 1000 } } else { 3000 } }

// ---- building and crafting --------------------------------------------

fn cost(kind) {
    switch kind {
        "campfire" => #{ wood: 3 },
        "shelter" => #{ wood: 6, fiber: 3 },
        "storage" => #{ wood: 4 },
        "spear" => #{ wood: 2, stone: 1 },
        "cloak" => #{ hide: 2, fiber: 1 },
        "torch" => #{ wood: 1, fiber: 1 },
        "house" => #{ wood: 6, clay: 4, stone: 2 },
        "gate" => #{ wood: 4 },
        "wall" => #{ stone: 2 },
        "road" => #{ stone: 1 },
        "axe" => #{ wood: 2, stone: 1 },
        "pick" => #{ wood: 2, stone: 2 },
        "net" => #{ fiber: 3 },
        "basket" => #{ fiber: 2, wood: 1 },
        "bow" => #{ wood: 2, fiber: 1 },
        "arrow" => #{ wood: 1, stone: 1 },
        "salve" => #{ berries: 2, fiber: 1 },
        "leather" => #{ hide: 1 },
        "armor" => #{ leather: 3, fiber: 1 },
        "trap" => #{ wood: 2, fiber: 2 },
        "bridge" => #{ wood: 4, stone: 2 },
        _ => (),
    }
}
fn afford(a, kind) {
    let c = cost(kind);
    if c == () { return `cannot make ${kind}`; }
    for k in c.keys() {
        if inv(a, k) < c[k] { return `need ${c[k]} ${k} for a ${kind} (${k}: ${source_of(k)})`; }
    }
    ""
}
fn pay(kind) {
    let c = cost(kind);
    let out = [];
    for k in c.keys() { out.push(#{ op: "remove", item: k, qty: c[k] }); }
    out
}

fn build_check(a) {
    if a.actor.kind == "person" && young(a) { return "too young to build"; }
    let needed = switch a.item {
        "campfire" => "fire",
        "shelter" => "shelter",
        "storage" => "storage",
        "house" => "carpentry",
        "gate" => "carpentry",
        "wall" => "masonry",
        "trap" => "trapping",
        "bridge" => "bridging",
        _ => (),
    };
    if needed == () { return `cannot build ${a.item}`; }
    if !knows(a, needed) { return `you don't know how to build a ${a.item}` + learn_how(needed); }
    if a.item == "wall" || a.item == "gate" || a.item == "bridge" {
        if a.target.class != "place" { return `point at the tile beside you where the ${a.item} goes`; }
    } else if a.actor.terrain == "water" || a.actor.terrain == "rock" || a.actor.terrain == "wall" { return "cannot build here"; }
    if a.item == "campfire" && a.actor.near_fire { return "a campfire already burns right here"; }
    if a.item == "shelter" && a.actor.near_shelter { return "there is already a shelter right here"; }
    afford(a, a.item)
}
fn build_duration(a) { switch a.item { "campfire" => 6000, "shelter" => 20000, "house" => 40000, "wall" => 6000, "gate" => 15000, "trap" => 8000, "bridge" => 20000, _ => 10000 } }

// A trap catches small game over time: one meat about every 4 minutes, holding at most 3.
fn trap_every_s(x) { 240.0 }
fn trap_holds(x) { 3.0 }
fn build_done(a) {
    // Place first: if the spot turns out unusable, nothing is spent.
    let fx = [#{ op: "build", kind: a.item }];
    fx += pay(a.item);
    fx.push(#{ op: "vitals", energy: -4.0 });
    fx
}

// The technique each crafted thing needs.
fn made_by(item) {
    switch item {
        "spear" => "spear", "cloak" => "cloak", "torch" => "torch",
        "axe" => "toolmaking", "pick" => "toolmaking",
        "net" => "fishing", "basket" => "basketry",
        "bow" => "archery", "arrow" => "archery",
        "salve" => "medicine",
        "leather" => "tanning", "armor" => "tanning",
        _ => (),
    }
}
fn craft_check(a) {
    if young(a) { return "too young to craft"; }
    let needed = made_by(a.item);
    if needed == () { return `cannot craft ${a.item}`; }
    if !knows(a, needed) { return `you don't know how to make a ${a.item}` + learn_how(needed); }
    afford(a, a.item)
}
fn craft_duration(a) { 8000 }
fn craft_done(a) {
    let fx = pay(a.item);
    // Arrows come three at a time.
    fx.push(#{ op: "add", item: a.item, qty: if a.item == "arrow" { 3 } else { 1 } });
    fx
}

// ---- exchange -----------------------------------------------------------

fn amount(a) { if a.qty < 1 { 1 } else { a.qty } }

fn drop_check(a) {
    if inv(a, a.item) < 1 { return `you carry no ${a.item}`; }
    ""
}
fn drop_duration(a) { 500 }
fn drop_done(a) {
    let n = amount(a);
    let have = inv(a, a.item);
    if n > have { n = have; }
    [#{ op: "remove", item: a.item, qty: n }]
}

fn give_check(a) {
    if a.target.class != "creature" || !a.target.alive { return "no one to give to"; }
    if a.target.id == a.actor.id { return "cannot give to yourself"; }
    if inv(a, a.item) < amount(a) { return `not enough ${a.item} (${a.item}: ${source_of(a.item)})`; }
    // What someone is given has to fit in their pack; a baby can hold only a few things.
    let held = 0;
    for k in a.target.inv.keys() { held += a.target.inv[k]; }
    let room = if a.target.stage == "infant" { 4.0 } else { carry_limit(a.target.kind) + if a.target.inv.contains("basket") { 20.0 } else { 0.0 } };
    if held + amount(a) > room { return if a.target.stage == "infant" { `a baby can hold only ${room} things; give food a little at a time` } else { "their pack is full" }; }
    ""
}
fn give_duration(a) { 1000 }
fn give_done(a) { [#{ op: "give", item: a.item, qty: amount(a) }] }

// A storage holds this many things in all; a full one takes no more.
fn storage_holds(x) { 120 }
fn store_check(a) {
    if a.target.kind != "storage" { return "can only store in a storage"; }
    let held = 0;
    for k in a.target.inv.keys() { held += a.target.inv[k]; }
    if held + amount(a) > storage_holds(0) { return `the storage is full (it holds ${held} of ${storage_holds(0)} things)`; }
    if inv(a, a.item) < amount(a) { return `not enough ${a.item} (${a.item}: ${source_of(a.item)})`; }
    ""
}
fn store_duration(a) { 1000 }
fn store_done(a) { [#{ op: "store", item: a.item, qty: amount(a) }] }

fn take_check(a) {
    if a.target.kind != "storage" && a.target.kind != "remains" && a.target.kind != "trap" { return "nothing to take from"; }
    let have = a.target.inv[a.item];
    if have == () || have < 1 { return `no ${a.item} there`; }
    if pack_full(a) { return "your pack is full (eat, store, give or drop some first)"; }
    ""
}
fn take_duration(a) { 1000 }
fn take_done(a) {
    let have = a.target.inv[a.item];
    let n = amount(a);
    if n > have { n = have; }
    [#{ op: "take", item: a.item, qty: n }]
}

// ---- conflict -----------------------------------------------------------
// A blow, missile or effect does its damage; when health reaches 0 the creature dies. There
// is no way to hold a blow back: to frighten someone without harming them, threaten.
// Threatening does no harm; yielding stops resisting.

// How long a yield holds: the one who yielded does not strike back (ms). Striking them
// meanwhile is not prevented, but whoever does is seen striking someone who gave in.
fn yield_ms(kind) { 20000.0 }

fn within(ago, ms) { ago != () && ago < ms }
fn yielding(a) { within(a.actor.yielded_ago, yield_ms(a.actor.kind)) }
fn sensed(a, kind) { let n = a.actor.sensed[kind]; if n == () { 0 } else { n } }
// How the actor refers to its target.
fn who(a) { if a.target.kind == a.actor.kind || a.target.name == "" { a.target.name } else { "the " + a.target.kind } }

// Predators and people. A predator fears people: it attacks a person only when desperate
// (starving with no prey in sight or smell), when the person is easy prey (a child, badly
// hurt, asleep away from a fire, or alone at night away from a fire), or to fight back.
fn prey_of(kind) { switch kind { "wolf" => ["deer"], _ => [] } }
fn desperate_hunger(kind) { 85.0 }
// A person below this share of full health is easy prey.
fn easy_hurt(kind) { 0.35 }
// A predator fights back against whoever hurt it this recently (ms).
fn fight_back_ms(kind) { 10000.0 }
fn dares(a) {
    if a.actor.kind == "person" || a.target.kind != "person" { return ""; }
    // A hostile pack (the seed's `bold` animals) has lost its fear of people.
    if a.actor.bold { return ""; }
    if a.actor.hurt_by == a.target.id && within(a.actor.hurt_ago, fight_back_ms(a.actor.kind)) { return ""; }
    let prey = 0;
    for k in prey_of(a.actor.kind) { prey += sensed(a, k); }
    if a.actor.hunger >= desperate_hunger(a.actor.kind) && prey == 0 { return ""; }
    let t = a.target;
    if t.stage == "infant" || t.stage == "child" { return ""; }
    if t.max_hp > 0.0 && t.hp < easy_hurt(a.actor.kind) * t.max_hp { return ""; }
    if !t.near_fire && (t.activity == "sleep" || (a.night && t.company == 0)) { return ""; }
    "you do not dare: people are dangerous"
}

fn attack_check(a) {
    if a.actor.kind == "person" && young(a) { return "too young to fight"; }
    if a.target.class != "creature" || !a.target.alive { return "nothing to attack"; }
    if a.target.id == a.actor.id { return "cannot attack yourself"; }
    if yielding(a) { return "you have yielded: you do not strike back while it holds"; }
    let wary = dares(a);
    if wary != "" { return wary; }
    ""
}
// The windup: time the target has to see it coming and react.
fn attack_duration(a) { switch a.actor.kind { "wolf" => 550, _ => if inv(a, "spear") > 0 { 750 } else { 650 } } }
// How far a blow still carries at the end of its windup, beyond the attack's reach (tiles):
// a wolf leaps, a person steps into a thrust. Out of reach by more than this, it misses.
fn lunge(kind) { switch kind { "wolf" => 1.8, "deer" => 0.6, _ => 0.6 } }
fn attack_done(a) {
    let dmg = switch a.actor.kind {
        "wolf" => 13.0,
        "deer" => 4.0,
        _ => if inv(a, "spear") > 0 { 18.0 } else { 7.0 },
    };
    // Strength and skill at fighting (knack × practice) make blows count.
    let dmg = dmg * a.actor.strength * a.actor.factor * armor(a);
    [#{ op: "damage", amount: dmg }, #{ op: "vitals", energy: -1.5 }]
}
// Leather armor takes the edge off a blow.
fn armor(a) { let n = a.target.inv["armor"]; if n == () || n < 1 { 1.0 } else { 0.65 } }

// Menacing someone in reach (weapon raised, closing in): no harm done, but they see it.
fn threaten_check(a) {
    if a.actor.kind != "person" { return "only people threaten"; }
    if a.actor.stage == "infant" { return "too small to threaten anyone"; }
    // A child can frighten another child, not a grown-up.
    if a.actor.stage == "child" && a.target.stage != "child" && a.target.stage != "infant" { return "you are too small to frighten a grown-up; ask them instead (say)"; }
    if a.target.class != "creature" || !a.target.alive { return "no one to threaten"; }
    if a.target.id == a.actor.id { return "cannot threaten yourself"; }
    ""
}
fn threaten_duration(a) { 2000 }
fn threaten_done(a) { [#{ op: "vitals", energy: -0.5 }] }

// Taking by force without killing: from someone who has yielded, or who is badly hurt.
fn seize_check(a) {
    if a.actor.kind != "person" { return "only people seize things"; }
    if young(a) { return "too young to take things by force"; }
    if a.target.class != "creature" || !a.target.alive || a.target.kind != "person" { return "no one to take from"; }
    if a.target.id == a.actor.id { return "cannot take from yourself"; }
    let beaten = a.target.max_hp > 0.0 && a.target.hp < easy_hurt(a.actor.kind) * a.target.max_hp;
    if !within(a.target.yielded_ago, yield_ms(a.target.kind)) && !beaten { return `${who(a)} has not given in: they would have to yield first (or be badly hurt)`; }
    let has = 0;
    for k in a.target.inv.keys() { if k == a.item { has = a.target.inv[k]; } }
    if has < amount(a) { return `${who(a)} does not have ${amount(a)} ${a.item}`; }
    ""
}
fn seize_duration(a) { 1500 }
fn seize_done(a) { [#{ op: "seize", item: a.item, qty: amount(a) }] }

// Giving in: guard down, hands up.
fn yield_check(a) {
    if a.actor.kind != "person" { return "only people yield"; }
    if a.actor.stage == "infant" { return "too small to yield"; }
    if a.target.class == "creature" && a.target.id == a.actor.id { return "cannot yield to yourself"; }
    if yielding(a) { return "you have already yielded"; }
    ""
}
fn yield_duration(a) { 1000 }
fn yield_done(a) { [#{ op: "yield" }] }

// Meat left when a creature dies at someone's hand.
fn carcass_meat(kind) { switch kind { "deer" => 5, "wolf" => 2, _ => 0 } }
fn carcass_hide(kind) { switch kind { "deer" => 1, "wolf" => 1, _ => 0 } }

fn max_hp(kind) { switch kind { "deer" => 40.0, "wolf" => 55.0, _ => 100.0 } }

// Regrowth per minute for resource kinds.
fn regrow(kind) {
    switch kind {
        "berry_bush" => 1.2,
        "reeds" => 1.0,
        "tree" => 0.5,
        "boulder" => 0.2,
        "fishing_spot" => 1.4,
        "clay_bank" => 0.6,
        _ => 0.0,
    }
}

// ---- life course --------------------------------------------------------

fn young(a) { a.actor.stage == "infant" || a.actor.stage == "child" }
fn grown(a) { !young(a) }

fn conceive_check(a) {
    if a.actor.stage != "adult" { return "not of an age to start a family"; }
    if a.target.class != "creature" || a.target.kind != a.actor.kind || !a.target.alive { return "no partner"; }
    if a.target.id == a.actor.id { return "cannot do that alone"; }
    if a.target.stage != "adult" { return "they are not of an age for it"; }
    if a.actor.hunger > 60.0 { return "too hungry to think of a family"; }
    ""
}
fn conceive_duration(a) { 3000 }
fn conceive_done(a) { [#{ op: "bond" }] }

// ---- signals (species vocabulary is checked by the engine) --------------

fn signal_duration(a) { 800 }
fn signal_done(a) { [#{ op: "signal" }] }

// ---- know-how -----------------------------------------------------------------

fn requires(t) { switch t { "cooking" => ["fire"], "torch" => ["fire"], "carpentry" => ["shelter"], "smoking" => ["fire"], "bridging" => ["carpentry"], _ => [] } }

// ---- roads and gates ------------------------------------------------------

fn pave_check(a) {
    if a.actor.kind != "person" || young(a) { return "you cannot lay road"; }
    if a.actor.terrain == "road" { return "this is already road"; }
    if a.actor.terrain == "water" || a.actor.terrain == "rock" { return "cannot lay road here"; }
    afford(a, "road")
}
fn pave_duration(a) { 4000 }
fn pave_done(a) { let fx = [#{ op: "build", kind: "road" }]; fx += pay("road"); fx }

fn open_check(a) { if a.target.kind != "gate" { return "that is not a gate"; } "" }
fn open_duration(a) { 1500 }
fn open_done(a) { [#{ op: "gate", open: 1.0 }] }
fn close_check(a) { if a.target.kind != "gate" { return "that is not a gate"; } "" }
fn close_duration(a) { 1500 }
fn close_done(a) { [#{ op: "gate", open: 0.0 }] }

// Every technique there is: whatever experimenting with some material can reveal.
fn techniques() {
    let all = [];
    for m in ["stone", "wood", "clay", "fiber", "hide", "berries", "meat", "fish"] {
        for t in discoveries(m) { if !all.contains(t) { all.push(t); } }
    }
    all
}
fn teach_check(a) {
    let all = techniques();
    if !all.contains(a.item) {
        let by = made_by(a.item);
        if by != () { return `${a.item} is a thing, not a technique: it is made with ${by}`; }
        let names = "";
        for t in all { names += if names == "" { t } else { `, ${t}` }; }
        return `there is no technique called ${a.item} (the techniques are: ${names})`;
    }
    if !knows(a, a.item) { return `you don't know ${a.item} yourself`; }
    if a.target.class != "creature" || a.target.kind != "person" || !a.target.alive { return "no one to teach"; }
    if a.target.knows.contains(a.item) { return `they already know ${a.item}`; }
    for r in requires(a.item) { if !a.target.knows.contains(r) { return `they must first learn ${r}`; } }
    ""
}
fn teach_duration(a) { 15000 }
fn teach_done(a) { [#{ op: "teach", technique: a.item }] }

// How a technique one lacks can be learned, for failure feedback: from someone who knows
// it, from writing, or (when a material can reveal it) by experimenting with that material.
fn learn_how(t) {
    let from = "";
    for m in ["stone", "wood", "clay", "fiber", "hide", "berries", "meat", "fish"] {
        if discoveries(m).contains(t) { from += if from == "" { m } else { ` or ${m}` }; }
    }
    let tail = if from == "" { "" } else { `, or work it out by experimenting with ${from}` };
    ` (${t}: learn it from someone who knows it or from writing${tail})`
}

// What tinkering with a material can reveal.
fn discoveries(m) {
    switch m {
        "stone" => ["spear", "fire", "masonry", "toolmaking"],
        "wood" => ["fire", "storage", "writing", "torch", "carpentry", "toolmaking", "archery", "trapping", "bridging"],
        "clay" => ["carpentry", "masonry"],
        "fiber" => ["shelter", "torch", "cloak", "fishing", "basketry"],
        "hide" => ["cloak", "tanning"],
        "berries" => ["planting", "medicine"],
        "meat" => ["cooking", "smoking"],
        "fish" => ["cooking", "smoking"],
        _ => [],
    }
}
fn experiment_check(a) {
    if a.actor.kind != "person" || young(a) { return "you cannot experiment"; }
    if inv(a, a.item) < 1 { return `no ${a.item} to experiment with`; }
    ""
}
fn experiment_duration(a) { 10000 }
fn experiment_done(a) {
    let fx = [#{ op: "remove", item: a.item, qty: 1 }];
    let open = [];
    for t in discoveries(a.item) {
        if knows(a, t) { continue; }
        let ok = true;
        for r in requires(t) { if !knows(a, r) { ok = false; } }
        if (t == "cooking" || t == "smoking") && !a.actor.near_fire { ok = false; }
        if ok { open.push(t); }
    }
    if open.len() > 0 && a.roll < 0.3 {
        let i = (a.roll / 0.3 * open.len()).to_int();
        if i >= open.len() { i = open.len() - 1; }
        fx.push(#{ op: "learn", technique: open[i] });
    }
    fx
}

fn write_check(a) {
    if !knows(a, "writing") { return "you don't know how to write" + learn_how("writing"); }
    if a.item != "tablet" && a.item != "sign" { return "you can write a tablet or a sign"; }
    if inv(a, "wood") < 1 { return `writing needs 1 wood (wood: ${source_of("wood")})`; }
    if a.text == "" { return "nothing to write"; }
    if a.topic != "" && !knows(a, a.topic) { return `you can't describe ${a.topic}: you don't know it`; }
    ""
}
fn write_duration(a) { 12000 }
fn write_done(a) { [#{ op: "remove", item: "wood", qty: 1 }, #{ op: "write" }] }

// Tending wounds: anyone can do it; it takes a while and needs the patient to hold still.
fn tend_check(a) {
    if a.target.class != "creature" || a.target.kind != "person" || !a.target.alive { return "no one to tend"; }
    if a.target.hp >= a.target.max_hp - 1.0 { return "they are not hurt"; }
    if a.target.hurt_ago < 10000 { return "they won't hold still in a fight"; }
    ""
}
fn tend_duration(a) { 6000 }
fn tend_done(a) {
    // Knowing medicine, a salve heals far more (and is used up).
    if knows(a, "medicine") && inv(a, "salve") > 0 {
        return [#{ op: "remove", item: "salve", qty: 1 }, #{ op: "heal", amount: 25.0 * a.actor.factor }, #{ op: "vitals", energy: -1.0 }];
    }
    [#{ op: "heal", amount: 10.0 * a.actor.factor }, #{ op: "vitals", energy: -1.0 }]
}

fn read_check(a) {
    if !knows(a, "writing") { return "you can't read"; }
    ""
}
fn read_duration(a) { 6000 }
fn read_done(a) { [#{ op: "read" }] }

fn plant_check(a) {
    if !knows(a, "planting") { return "you don't know how to plant" + learn_how("planting"); }
    if inv(a, "berries") < 2 { return `planting needs 2 berries (berries: ${source_of("berries")})`; }
    if a.actor.terrain != "grass" && a.actor.terrain != "dirt" { return "nothing grows here"; }
    if a.season == "winter" { return "the ground is frozen"; }
    ""
}
fn plant_duration(a) { 5000 }
fn plant_done(a) { [#{ op: "remove", item: "berries", qty: 2 }, #{ op: "plant" }] }

// ---- reworking one's ways ------------------------------------------------------
// A way (routine) is changed by sitting down to rework it, and only once it has been lived
// with: tried a few times, failed a couple of times, or kept for a while. A new way can be
// worked out at any time. The top level (what one weighs) changes more slowly still.

fn rework_check(a) {
    if a.actor.kind != "person" { return "only people rework their ways"; }
    if young(a) && a.actor.stage == "infant" { return "too small to change your ways"; }
    if a.text == "" { return "no new way in mind"; }
    let r = a.routine;
    if !r.exists { return if a.text == "retire" { `you have no way called "${a.item}"` } else { "" }; }
    if a.item == "top level" {
        if r.changed_s < 1440.0 { return `you changed how you live only ${(r.changed_s / 60.0).to_int()} minutes ago: live with it for about two days first`; }
        return "";
    }
    let tried = r.ok + r.failed;
    if tried >= 4 || r.failed >= 2 || r.changed_s >= 900.0 { return ""; }
    `you have hardly lived with "${a.item}" since you last changed it (tried ${tried} times, failed ${r.failed}): see how it goes first`
}
fn rework_duration(a) { if a.item == "top level" { 30000 } else if a.routine.exists { 15000 } else { 10000 } }
fn rework_done(a) { [#{ op: "rework" }, #{ op: "vitals", energy: -1.0 }] }

// ---- combat moves ---------------------------------------------------------------

// Every combat move has a windup (its `_duration`: the time others have to see it coming),
// then its release, a recovery in which only a dodge can follow (`combat_recover`), and a
// cooldown counted from its start (`combat_cooldown`), for anyone who uses it: player or
// graph, person or animal. `combat_cost` is the energy it takes, paid at the release.
fn combat_recover(skill) { switch skill { "strike" => 250, "bowshot" => 250, "firebolt" => 350, "heal" => 300, "dodge" => 200, "attack" => 300, "shoot" => 300, "throw" => 400, _ => 0 } }
fn combat_cooldown(skill) { switch skill { "strike" => 650, "bowshot" => 900, "firebolt" => 4000, "heal" => 8000, "dodge" => 900, "block" => 400, _ => 0 } }
fn combat_cost(skill) { switch skill { "strike" => 2.0, "bowshot" => 1.5, "firebolt" => 12.0, "heal" => 15.0, "dodge" => 4.0, "block" => 1.0, _ => 0.0 } }
fn spent(skill) { [#{ op: "vitals", energy: -combat_cost(skill) }] }
fn winded(a) { if a.actor.energy < combat_cost(a.skill) { "too tired" } else { "" } }

// What each combat skill is: `<skill>_combat()`, read once when the script is installed (the
// authority never asks per tick). Every skill that has one is a combat skill, gets a
// `skill_card` and a presentation code (its place in name order). Traits (all optional):
//   aim        how a player aims it: "creature", "self_or_ally", "point" (a skillshot: it needs
//              `<skill>_missile`), "facing" (a held guard), "dash" (a dodge), "none"
//   timed      the combat timing above (one windup at a time, recovery, cooldown)
//   rooted     a player's movement waits while it winds up
//   hostile    aimed at a creature, that creature is its victim and sees it coming
//   reflex     it takes the body back from a deliberate act
//   real_time  behavior of the moment: a graph's, not a one-off act's
//   melee      a blow in reach, with `lunge(kind)`; out of reach by then, it misses
//   closes_in  its rules are weighed before walking into reach
//   menace     made once per target in a while; the target perceives a threat
//   force      whether its actor has yielded is weighed
//   dares      the target is weighed first: whether they yielded, what a predator dares
//   hold_ms    a guard: the longest a player holds it
//   arc        a guard: degrees either side of where it faces that it covers
//   takes      a guard: the share of a covered blow that still lands
//   knack      the skill whose knack gene serves it (itself by default)
//   needs      items the skill bar shows as missing (the check stays the rule)
//   knows      techniques the skill bar shows as unknown
// A dash moves `<skill>_dist(kind)` tiles at `<skill>_speed(kind)` tiles/s.
fn strike_combat() { #{ aim: "creature", timed: true, rooted: true, hostile: true, reflex: true, real_time: true, melee: true, closes_in: true, force: true, dares: true, knack: "attack" } }
fn bowshot_combat() { #{ aim: "point", timed: true, rooted: true, hostile: true, reflex: true, real_time: true, force: true, knack: "shoot", needs: ["bow", "arrow"] } }
fn firebolt_combat() { #{ aim: "point", timed: true, rooted: true, hostile: true, reflex: true, real_time: true, force: true, knack: "throw", knows: ["fire_bolt"] } }
fn block_combat() { #{ aim: "facing", timed: true, reflex: true, real_time: true, hold_ms: 8000, arc: 75.0, takes: 0.25 } }
fn heal_combat() { #{ aim: "self_or_ally", timed: true, rooted: true, reflex: true, knack: "tend", knows: ["wound_tending"] } }
fn dodge_combat() { #{ aim: "dash", timed: true, reflex: true, real_time: true } }
fn attack_combat() { #{ aim: "creature", timed: true, rooted: true, hostile: true, reflex: true, real_time: true, melee: true, closes_in: true, force: true, dares: true } }
fn shoot_combat() { #{ aim: "creature", timed: true, rooted: true, hostile: true, reflex: true, real_time: true, force: true } }
fn throw_combat() { #{ aim: "creature", timed: true, hostile: true, reflex: true, real_time: true, force: true } }
fn threaten_combat() { #{ aim: "creature", hostile: true, closes_in: true, menace: true } }
fn yield_combat() { #{ reflex: true, force: true } }
fn seize_combat() { #{ aim: "creature", dares: true } }
fn tend_combat() { #{ aim: "creature" } }
// The player's skill bar, in order (the game binds LMB, RMB, Q, E, R, Shift).
fn skill_bar() { ["strike", "bowshot", "firebolt", "block", "heal", "dodge"] }
// How far and fast a dodge carries a body (tiles, tiles/s); hits while it lasts miss.
fn dodge_dist(kind) { switch kind { "wolf" => 2.4, "deer" => 2.8, _ => 2.6 } }
fn dodge_speed(kind) { switch kind { "wolf" => 8.0, "deer" => 8.0, _ => 5.2 } }

fn dodge_check(a) { if a.actor.energy < 5.0 { "too exhausted to dodge" } else { "" } }
fn dodge_done(a) { spent("dodge") }

// A guard is held for `qty` ms (a player holds it until they let go, at most its `hold_ms`),
// else a moment. Holding it is tiring (see `rates`).
fn block_check(a) { if a.actor.kind != "person" { return "only people can block"; } winded(a) }
fn block_duration(a) { let most = block_combat().hold_ms; if a.qty > 0 { if a.qty > most { most } else { a.qty } } else { 1200 } }
fn block_done(a) { [#{ op: "vitals", energy: -0.5 }] }

// ---- the starter skills (docs/GAME_BRIEF.md): sword strike, bow shot, fire bolt, heal ------

// A quick, telegraphed blow at a creature in reach; it does its damage like an attack.
fn strike_check(a) {
    let why = attack_check(a);
    if why != "" { return why; }
    winded(a)
}
fn strike_duration(a) { 350 }
fn strike_done(a) {
    let dmg = if inv(a, "spear") > 0 { 15.0 } else { 10.0 };
    let dmg = dmg * a.actor.strength * a.actor.factor * armor(a);
    [#{ op: "damage", amount: dmg }] + spent("strike")
}

fn aim_check(a) {
    if young(a) { return "too young to fight"; }
    if yielding(a) { return "you have yielded: you do not strike back while it holds"; }
    if a.target.class == "creature" && (a.target.id == a.actor.id || !a.target.alive) { return "nothing to aim at"; }
    winded(a)
}
// An arrow flies straight and hits the first creature in its path.
fn bowshot_check(a) {
    if inv(a, "bow") < 1 { return "no bow to shoot with"; }
    if inv(a, "arrow") < 1 { return `no arrows (arrow: ${source_of("arrow")})`; }
    aim_check(a)
}
fn bowshot_duration(a) { 300 }
fn bowshot_done(a) { [#{ op: "remove", item: "arrow", qty: 1 }, #{ op: "launch" }] + spent("bowshot") }
fn bowshot_missile(a) { #{ speed: 30.0, range: 22.0, radius: 0.15 } }
fn bowshot_hit(a) { [#{ op: "damage", amount: 14.0 * a.actor.strength * a.actor.factor * armor(a) }] }

// A bolt of fire: slower, shorter, wider and much harder, at a great cost of energy.
fn firebolt_check(a) {
    if !knows(a, "fire_bolt") { return "you don't know how to hurl fire" + learn_how("fire_bolt"); }
    aim_check(a)
}
fn firebolt_duration(a) { 450 }
fn firebolt_done(a) { [#{ op: "launch" }] + spent("firebolt") }
fn firebolt_missile(a) { #{ speed: 16.0, range: 16.0, radius: 0.35 } }
fn firebolt_hit(a) { [#{ op: "damage", amount: 24.0 * a.actor.factor * armor(a) }] }

// Closing wounds by hand (wound_tending): yourself or an ally in sight, quickly, even mid-fight.
fn heal_check(a) {
    if !knows(a, "wound_tending") { return "you don't know how to close wounds by hand" + learn_how("wound_tending"); }
    if a.target.class != "creature" || a.target.kind != "person" || !a.target.alive { return "no one to heal"; }
    if a.target.hp >= a.target.max_hp - 0.5 { return if a.target.id == a.actor.id { "you are not hurt" } else { "they are not hurt" }; }
    // An ally: not someone fighting you, nor someone you are fighting.
    if a.target.id != a.actor.id && (a.actor.hurt_by == a.target.id && within(a.actor.hurt_ago, 15000.0)) { return "they are fighting you"; }
    winded(a)
}
fn heal_duration(a) { 600 }
fn heal_done(a) { [#{ op: "heal", amount: 22.0 * a.actor.factor }] + spent("heal") }

fn throw_check(a) {
    if inv(a, "spear") < 1 { return "no spear to throw"; }
    if a.target.class != "creature" || !a.target.alive { return "nothing to throw at"; }
    if young(a) { return "too young to fight"; }
    if yielding(a) { return "you have yielded: you do not strike back while it holds"; }
    ""
}
fn throw_duration(a) { 800 }
fn throw_done(a) { [#{ op: "remove", item: "spear", qty: 1 }, #{ op: "damage", amount: 24.0 * armor(a) }, #{ op: "vitals", energy: -2.0 }] }

fn shoot_check(a) {
    if inv(a, "bow") < 1 { return "no bow to shoot with"; }
    if inv(a, "arrow") < 1 { return `no arrows (arrow: ${source_of("arrow")})`; }
    if a.target.class != "creature" || !a.target.alive { return "nothing to shoot at"; }
    if young(a) { return "too young to fight"; }
    if yielding(a) { return "you have yielded: you do not strike back while it holds"; }
    ""
}
fn shoot_duration(a) { 700 }
fn shoot_done(a) { [#{ op: "remove", item: "arrow", qty: 1 }, #{ op: "damage", amount: 16.0 * a.actor.strength * a.actor.factor * armor(a) }, #{ op: "vitals", energy: -1.0 }] }

// ---- trade ------------------------------------------------------------------------

fn offer_check(a) {
    if a.target.class != "creature" || a.target.kind != "person" || !a.target.alive { return "no one to trade with"; }
    if inv(a, a.item) < amount(a) { return `not enough ${a.item} to offer`; }
    ""
}
fn offer_duration(a) { 1500 }
fn offer_done(a) { [#{ op: "offer" }] }

fn accept_check(a) {
    if a.target.class != "creature" || a.target.kind != "person" { return "no one to trade with"; }
    ""
}
fn accept_duration(a) { 1500 }
// Terms the person proposed to you come first; otherwise their standing trade.
fn accept_done(a) {
    let r = proposal_from(a);
    if r == () { return [#{ op: "accept" }]; }
    let t = r.terms;
    [#{ op: "amend", id: r.id, status: "agreed", due_h: due_by_dark(a) },
     #{ op: "tell", to: r.parties.from, salience: 0.8, text: `{actor} accepted your terms: ${terms_line(t, "from")}, ${due_words(a)}.` },
     #{ op: "tell", to: a.actor.id, text: `agreed with {target}: ${terms_line(t, "to")}, ${due_words(a)}` },
     #{ op: "witness", text: "{a} and {b} came to an agreement." }]
}

// ---- agreements, demands and regard (docs/WORLD_RULES.md) ---------------------------------
// Built on the engine's records: a record has a kind, a status, parties by role, terms and a
// time it falls due (world hours). The engine keeps them, indexed by party, hands a law the
// actor's own (`a.records`, through its community too), and tells these rules when something
// happens: `on_<skill>` after a skill is done (`on_give`, `on_store`, `on_host` here),
// `on_expire` when a record falls due (`a.record`), `on_death`. A hook only makes, amends and
// closes records and tells; it moves nothing. People make, keep and break agreements and
// demands with the ordinary skills: nothing here is a role or a schedule.
//   record ops   #{ op: "record", kind, status, parties: #{ role: id }, terms: #{...}, due_h }
//                #{ op: "amend", id, status, terms (merged), due_h }
//                #{ op: "close", id, status, keep_h }
//   telling      #{ op: "tell", to: id, text, salience, ask } ({actor}, {target}, {id:N} become
//                how the one told refers to them; ask: their mind thinks about it; told to the
//                actor, it is the act's outcome)
//                #{ op: "witness", text, salience } (those who see the actor; {a}, {b})
// A record between a `holder` and a `toward` side whose terms have a `label` and a `value`
// (-100..100) is a stance: relation filters and minds read it (a community's regard, seeded).

// How long a proposal stands, a demand waits, and a closed record is remembered (world hours).
fn proposal_h(x) { 4.0 }
fn demand_h(x) { 3.0 }
fn kept_h(x) { 12.0 }
// An agreement falls due at dusk (20:00): the first dusk at least `agreement_min_h` game hours
// after it is agreed, so both sides have time to gather, carry and come back. (Dusk two hours
// off, the old minimum, was about a minute in a 12-minute day: both accepted agreements in the
// social trials lapsed before anyone could deliver, docs/TRIALS.md, "Fast iterations".)
fn agreement_min_h(x) { 12.0 }
fn due_by_dark(a) { let h = 20.0 - a.hour; while h < agreement_min_h(0) { h += 24.0; } h }
// Which dusk, said from the hour it is agreed.
fn due_words(a) { if a.hour + due_by_dark(a) < 24.0 { "by dusk today" } else { "by dusk tomorrow" } }

fn other_role(me) { if me == "from" { "to" } else { "from" } }
fn qty_of(n) { if n < 1 { 1 } else { n } }
fn goods(item, n) { if item == "lodging" { "a night's lodging" } else { `${n} ${item}` } }
fn words(t) { if t == "" { "" } else { ` ("${t}")` } }
// What each side owes, as the side `me` reads it.
fn terms_line(t, me) {
    let other = other_role(me);
    `you give ${goods(t[me + "_gives"], t[me + "_qty"])}, they give ${goods(t[other + "_gives"], t[other + "_qty"])}`
}
// Terms the target proposed to the actor, still standing.
fn proposal_from(a) {
    for r in a.records {
        if r.open && r.kind == "agreement" && r.status == "offered" && r.me == "to" && r.parties.from == a.target.id { return r; }
    }
    ()
}
// How the actor's community regards another (its stance record's terms), or ().
fn regard_toward(a, community) {
    for r in a.records {
        if r.kind == "regard" && r.me == "holder" && r.parties.toward == community { return r.terms; }
    }
    ()
}

fn offer_terms_check(a) {
    if a.target.class != "creature" || a.target.kind != "person" || !a.target.alive { return "no one to make an agreement with"; }
    if a.target.id == a.actor.id { return "not with yourself"; }
    if young(a) { return "too young to make agreements"; }
    if a.item == "" || a.want == "" { return "say what you will give (item, qty) and what they will give (want, want_qty)"; }
    let open = 0;
    for r in a.records { if r.open { open += 1; } }
    if open >= 12 { return "you have too many dealings in hand already"; }
    ""
}
fn offer_terms_duration(a) { 2000 }
fn offer_terms_done(a) {
    let t = #{ from_gives: a.item, from_qty: qty_of(a.qty), to_gives: a.want, to_qty: qty_of(a.want_qty), from_done: 0, to_done: 0, from_home: a.actor.home, to_home: a.target.home, words: a.text };
    if a.item == "lodging" { t.from_qty = 1; }
    if a.want == "lodging" { t.to_qty = 1; }
    [#{ op: "record", kind: "agreement", status: "offered", parties: #{ from: a.actor.id, to: a.target.id }, terms: t, due_h: proposal_h(0) },
     #{ op: "tell", to: a.target.id, ask: true, salience: 0.85, text: `{actor} proposes an agreement: ${terms_line(t, "to")}${words(a.text)}, due at the first dusk at least ${agreement_min_h(0).to_int()} hours after you accept. If you accept (accept, toward them), the world counts what each of you hands over or stores for the other.` },
     #{ op: "tell", to: a.actor.id, text: `proposed to {target}: ${terms_line(t, "from")}${words(a.text)}` }]
}

// What the actor handed over or stored for someone, counted toward its agreements with them
// and the demands they made of it.
fn delivered(a, item, n, to_id, to_home) {
    let fx = [];
    for r in a.records {
        if !r.open { continue; }
        if r.kind == "agreement" && r.status == "agreed" {
            let me = r.me;
            let other = other_role(me);
            let t = r.terms;
            let them = r.parties[other];
            let to_them = to_id == them || (to_home != "" && to_home == t[other + "_home"]);
            if t[me + "_gives"] != item || !to_them { continue; }
            let owed = t[me + "_qty"];
            let done = t[me + "_done"];
            if done >= owed { continue; }
            done += n;
            if done > owed { done = owed; }
            let change = #{};
            change[me + "_done"] = done;
            fx.push(#{ op: "amend", id: r.id, terms: change });
            let left = t[other + "_qty"] - t[other + "_done"];
            if done >= owed && left <= 0 {
                fx.push(#{ op: "close", id: r.id, status: "kept", keep_h: kept_h(0) });
                fx.push(#{ op: "tell", to: them, salience: 0.75, text: `{actor} has delivered ${goods(item, owed)}: your agreement with them is kept on both sides.` });
                fx.push(#{ op: "tell", to: a.actor.id, text: `with that your agreement with {id:${them}} is kept on both sides` });
            } else if done >= owed {
                fx.push(#{ op: "tell", to: them, ask: true, salience: 0.85, text: `{actor} has delivered all ${goods(item, owed)} you agreed on. You owe them ${goods(t[other + "_gives"], left)} by dusk.` });
                fx.push(#{ op: "tell", to: a.actor.id, text: `you have delivered your part (${goods(item, owed)}); {id:${them}} owes you ${goods(t[other + "_gives"], left)}` });
            }
            // A part delivered is not told piece by piece: a give is seen by its receiver anyway,
            // and each side reads how far the other has got in its dealings (`record_text`).
        } else if r.kind == "demand" && r.me == "of" && to_id == r.parties.by && r.terms.item == item {
            let done = r.terms.done + n;
            if done >= r.terms.qty {
                fx.push(#{ op: "amend", id: r.id, terms: #{ done: done } });
                fx.push(#{ op: "close", id: r.id, status: "met", keep_h: kept_h(0) });
                fx.push(#{ op: "tell", to: r.parties.by, salience: 0.7, text: `{actor} paid the ${r.terms.qty} ${item} you demanded.` });
                fx.push(#{ op: "tell", to: a.actor.id, text: `you have paid what {id:${r.parties.by}} demanded` });
            } else {
                fx.push(#{ op: "amend", id: r.id, terms: #{ done: done } });
            }
        }
    }
    fx
}
fn on_give(a) { delivered(a, a.item, qty_of(a.qty), a.target.id, "") }
fn on_store(a) { delivered(a, a.item, qty_of(a.qty), a.target.owner, a.target.home) }
fn on_host(a) { delivered(a, "lodging", 1, a.target.id, "") }

// A record fell due: a proposal not taken, an agreement kept by one side only or by neither,
// a demand not paid. Whoever did not deliver is told so, and so is the other side.
fn on_expire(a) {
    let r = a.record;
    if r.kind == "agreement" { return agreement_due(r); }
    if r.kind == "demand" { return demand_due(r); }
    []
}
fn agreement_due(r) {
    let t = r.terms;
    let f = r.parties.from;
    let to = r.parties.to;
    if r.status == "offered" {
        return [#{ op: "close", id: r.id, status: "not taken", keep_h: 1.0 },
                #{ op: "tell", to: f, salience: 0.5, text: `{id:${to}} did not take up your terms (${terms_line(t, "from")}).` }];
    }
    let f_ok = t.from_done >= t.from_qty;
    let to_ok = t.to_done >= t.to_qty;
    if f_ok && to_ok { return [#{ op: "close", id: r.id, status: "kept", keep_h: kept_h(0) }]; }
    if f_ok || to_ok {
        let kept = if f_ok { "from" } else { "to" };
        let broke = other_role(kept);
        let k = r.parties[kept];
        let b = r.parties[broke];
        let owed = goods(t[broke + "_gives"], t[broke + "_qty"] - t[broke + "_done"]);
        return [#{ op: "amend", id: r.id, terms: #{ broken_by: broke } },
                #{ op: "close", id: r.id, status: "broken", keep_h: kept_h(0) },
                #{ op: "tell", to: k, salience: 0.85, text: `{id:${b}} has not delivered ${owed} by dusk as agreed, though you delivered your part: they broke your agreement.` },
                #{ op: "tell", to: b, salience: 0.8, text: `Dusk has passed and you have not delivered ${owed} to {id:${k}}, who delivered their part: you broke your agreement.` }];
    }
    [#{ op: "close", id: r.id, status: "lapsed", keep_h: kept_h(0) },
     #{ op: "tell", to: f, salience: 0.6, text: `Your agreement with {id:${to}} has lapsed at dusk: neither of you delivered all of your part.` },
     #{ op: "tell", to: to, salience: 0.6, text: `Your agreement with {id:${f}} has lapsed at dusk: neither of you delivered all of your part.` }]
}
fn demand_due(r) {
    let by = r.parties.by;
    let of = r.parties.of;
    let what = `${r.terms.qty} ${r.terms.item}`;
    [#{ op: "close", id: r.id, status: "unpaid", keep_h: kept_h(0) },
     #{ op: "tell", to: by, salience: 0.7, text: `{id:${of}} has not paid the ${what} you demanded.` },
     #{ op: "tell", to: of, salience: 0.5, text: `You did not pay the ${what} {id:${by}} demanded.` }]
}

// How a party reads one of its records, for minds and players ({id:N} becomes how they refer to
// N: a person, or a community). Read by the mind service and the client, never per tick.
fn record_text(r) {
    if r.kind == "agreement" {
        let other = r.parties[other_role(r.me)];
        let t = r.terms;
        if r.status == "offered" {
            return if r.me == "from" { `you proposed to {id:${other}}: ${terms_line(t, "from")}${words(t.words)}; they have not accepted yet` } else { `{id:${other}} proposed to you: ${terms_line(t, "to")}${words(t.words)}; accept (toward them) to agree` };
        }
        let mine = t[r.me + "_done"];
        let theirs = t[other_role(r.me) + "_done"];
        if r.status == "agreed" {
            return `agreement with {id:${other}}, by dusk: ${terms_line(t, r.me)}${words(t.words)}; so far you delivered ${mine} of ${t[r.me + "_qty"]}, they ${theirs} of ${t[other_role(r.me) + "_qty"]}`;
        }
        return `agreement with {id:${other}} (${terms_line(t, r.me)}): ${r.status}`;
    }
    if r.kind == "demand" {
        let what = `${r.terms.qty} ${r.terms.item}${words(r.terms.words)}`;
        if r.me == "by" { return `you demanded ${what} of {id:${r.parties.of}}: ${if r.open { "not paid yet" } else { r.status }}`; }
        return `{id:${r.parties.by}} demanded ${what} of you: ${if r.open { "not paid yet" } else { r.status }}`;
    }
    if r.kind == "regard" {
        if r.me == "holder" { return `your people hold {id:${r.parties.toward}} as ${r.terms.label} (${r.terms.why})`; }
        return `{id:${r.parties.holder}} holds your people as ${r.terms.label} (${r.terms.why})`;
    }
    `${r.kind}: ${r.status}`
}

fn demand_check(a) {
    if a.target.class != "creature" || a.target.kind != "person" || !a.target.alive { return "no one to demand of"; }
    if a.target.id == a.actor.id { return "not of yourself"; }
    if young(a) { return "too young to make demands"; }
    if a.item == "" { return "say what you demand (item, qty)"; }
    for r in a.records {
        if r.open && r.kind == "demand" && r.me == "by" && r.parties.of == a.target.id { return "you already have a demand of them standing"; }
    }
    ""
}
fn demand_duration(a) { 1500 }
fn demand_done(a) {
    let n = qty_of(a.qty);
    [#{ op: "record", kind: "demand", status: "open", parties: #{ by: a.actor.id, of: a.target.id }, terms: #{ item: a.item, qty: n, done: 0, words: a.text }, due_h: demand_h(0) },
     #{ op: "tell", to: a.target.id, ask: true, salience: 0.85, text: `{actor} demands ${n} ${a.item} of you${words(a.text)}. You may give it to them, or not.` },
     #{ op: "witness", text: `{a} demanded ${n} ${a.item} of {b}.` },
     #{ op: "tell", to: a.actor.id, text: `demanded ${n} ${a.item} of {target}; you will know whether they pay` }]
}

// ---- hospitality ----------------------------------------------------------------------
// Taking someone in: a grown person offers another a bed in their household's house (the
// house at their home door; the engine finds it, and refuses without one) until the morning
// hour `host_done` names. The guest learns where it is (a place called "lodging"), may sleep
// there, and taking from the household's store is no longer theft for them.

fn host_check(a) {
    if a.target.class != "creature" || a.target.kind != "person" || !a.target.alive { return "no one to take in"; }
    if a.target.id == a.actor.id { return "you cannot be your own guest"; }
    if young(a) { return "only grown people take in guests"; }
    ""
}
fn host_duration(a) { 2000 }
fn host_done(a) { [#{ op: "host", until_hour: 7.0 }] }

// ---- communities (meaning is up to members; the engine keeps membership) ------------------

fn found_check(a) {
    if a.actor.kind != "person" || young(a) { return "only grown people found communities"; }
    if a.text == "" { return "a community needs a name"; }
    ""
}
fn found_duration(a) { 3000 }
fn found_done(a) { [#{ op: "found" }] }
fn join_duration(a) { 2000 }
fn join_done(a) { [#{ op: "join" }] }
fn welcome_duration(a) { 2000 }
fn welcome_done(a) { [#{ op: "welcome" }] }
fn leave_duration(a) { 1000 }
fn leave_done(a) { [#{ op: "leave" }] }

// ---- residents who get a mind (docs/TOWN_LIFE.md, "Layer 2") -----------------------------
// On a world whose residents live on their behaviour graphs alone, someone engaging a
// resident can wake it into a mind, which it keeps. `e` is "<what>:<by>": what is `speech`
// (spoken to), the name of a skill aimed at the resident as it starts (`wave`, `give`,
// `teach`, `offer`, `attack`…), `hurt` (a blow or missile landed) or `theft` (taking from its
// store as it watched); by is `player`, `mind` (what a mind decided: its acts and words),
// `woken` (what a woken resident's mind decided), `habit` (what a minded character's behaviour
// graph did by itself) or `instinct`. 1 wakes, 0 does not. Habits and instincts stay at the level of detail they happen at: a neighbour's
// evening nod or a wolf's bite wakes nobody, whether or not the neighbour has a mind (the first
// paid run, before `habit`, had woken residents' routine nods wake 11 of 15 in 9 minutes).
// Read once per script revision for each engagement.
fn wakes(e) {
    let p = e.split(":");
    if p.len() < 2 || p[1] == "instinct" || p[1] == "habit" { return 0; }
    let what = p[0];
    // A woken resident's words and gestures do not wake its neighbours; a blow or a theft does.
    // Without this, woken residents talking to each other woke 41 of 48 in three social trials
    // (docs/TRIALS.md, "Fast iterations", 6), the newcomer 7.
    if p[1] == "woken" && !["hurt", "theft"].contains(what) && !["attack", "strike", "shoot", "bowshot", "firebolt", "throw", "threaten", "seize"].contains(what) { return 0; }
    if ["speech", "hurt", "theft"].contains(what) { return 1; }
    // Kindness, dealings, lessons, asking to belong, and anything hostile.
    if ["wave", "nod", "give", "offer", "offer_terms", "demand", "accept", "teach", "tend", "heal", "join", "welcome", "host"].contains(what) { return 1; }
    if ["attack", "strike", "shoot", "bowshot", "firebolt", "throw", "threaten", "seize"].contains(what) { return 1; }
    0
}

// What a resident without a mind keeps of what it perceives, for the mind it may get: a ring
// of `slots` (at most 256; 0 keeps nothing) per resident, of perceptions at least
// `min_salience` (an answered greeting is 0.15, a greeting 0.3, someone coming into view 0.2,
// overheard speech 0.45), the same perception again within `repeat_s` counted in its slot,
// someone who came into view noted again only after `sighted_s`. Measured on the island
// (docs/TOWN_LIFE.md): without the floor a fifth of the slots held answered greetings.
// What a woken resident's mind gets, read by the mind service: at most `cap` woken residents of
// one settlement are on stage (thinking and talking at the full rate) at once; beyond it the
// least recently engaged is off stage (0: no cap). A woken resident's first thought waits at
// most `wait_s` for its mind to be made (its identity from the world's facts, then its ring).
fn woken_stage(k) {
    switch k {
        "cap" => 6,
        "wait_s" => 60,
        _ => 0,
    }
}

fn woken_ring(k) {
    switch k {
        "slots" => 24,
        "min_salience" => 0.2,
        "repeat_s" => 120,
        "sighted_s" => 600,
        _ => 0,
    }
}

// ---- text helpers for the skills' specs (below) -----------------------------------------
// Specs are read by minds to compose routines from skills: build them from the same numbers
// as the rules so they change when the rules do.

fn list(parts) {
    let out = "";
    for p in parts { if out != "" { out += ", "; } out += p; }
    out
}
fn cost_text(kind) {
    let c = cost(kind);
    if c == () { return ""; }
    let parts = [];
    for k in c.keys() { parts.push(`${c[k]} ${k}`); }
    list(parts)
}
fn foods_text() {
    let parts = [];
    for f in ["berries", "fish", "meat", "cooked_fish", "cooked_meat", "smoked_fish", "smoked_meat"] { parts.push(`${f} ${nutrition(f).to_int()}`); }
    list(parts)
}
// Where an item comes from (shown when a skill lacks it).
fn source_of(item) {
    for r in ["berry_bush", "tree", "boulder", "reeds", "fishing_spot", "clay_bank"] {
        if yield_of(r) == item { return `gather it at a ${r}, or take it from a storage`; }
    }
    switch item {
        "food" => "gather berries at a berry_bush or fish at a fishing_spot, take food from a storage, or hunt",
        "hide" => "kill game (attack), then take it from the remains",
        "meat" => "kill game (attack) and take it from the remains, take it from a trap or a storage",
        "cooked_fish" => "cook fish at a campfire",
        "cooked_meat" => "cook meat at a campfire",
        "smoked_fish" => "smoke fish at a campfire (knowing smoking), or trade for it",
        "smoked_meat" => "smoke meat at a campfire (knowing smoking), or trade for it",
        _ => if cost(item) == () { "someone who has it can give or trade it to you" } else { `craft it (${cost_text(item)})` },
    }
}
// ---- what each skill is ----------------------------------------------------------------
// `<skill>_spec()`, read once when the script compiles (the engine never asks per tick). Every
// skill with rules (a duration or effects) declares one; graph normalization, the minds'
// prompts, the client's verbs and the acts path all take skills from here, so a skill added
// here needs no engine change. A floor overrides a skill's description by redefining its spec.
//   target  it is aimed at something (true/false)
//   item    it takes an item (true), or a word for what the item names ("technique")
//   args    further arguments it reads, for prompts ("qty", "want", "text"...)
//   reach   tiles within which it is done; an act walks into reach first
//   about   what it is, for a mind: what it does, when it is useful, what it is not
//   takes   what it uses up or needs, from the rules' own numbers
//   gives   what comes of it
//   listed  shown to people (false: only species that name it, e.g. grazing)
//   talk    offered in a conversation turn among the acts one may do right there
//   items   the item words it is given (choices for clients and prompts); accepted for it even
//           when they are not items, structures or techniques

fn goto_spec() {
    let l = laws();
    #{ target: true, reach: 0.8,
       about: "Walk to something in sight or a place you know and stop beside it. An act aimed at a target walks there by itself, so you need goto only to be somewhere (home before dark, a meeting place). Not following someone who moves (follow), not running away (flee).",
       takes: "a target in sight or a known place",
       gives: `you there; within ${l.fire_warmth} tiles of a campfire or ${l.shelter_warmth} of a shelter or house the night cold can't hurt you` }
}
fn wander_spec() { #{ about: "Stroll to a random spot nearby, to look around when nothing you need is in sight. It searches for nothing in particular.", gives: "you at a nearby spot you may not have seen" } }
fn gather_spec() {
    #{ target: true, reach: 1.3,
       about: "Take one unit from a resource beside you: berries from a berry_bush, wood from a tree, stone from a boulder, fiber from reeds, fish from a fishing_spot, clay from a clay_bank. The way to get food and materials from the land. Taking from a storage, remains or a trap is take.",
       takes: "a resource in reach with some left, room in your pack, a little energy",
       gives: "1 unit into your pack: berry_bush→berries, tree→wood (faster with an axe), boulder→stone (faster with a pick), reeds→fiber, fishing_spot→fish (faster with a spear, two at a time with a net), clay_bank→clay" }
}
fn eat_spec() {
    #{ item: "a food you carry, or \"food\" for your best",
       about: "Eat one food item from your own pack. Only what you carry: food in a storage must be taken out first, food someone else has must be given to you.",
       takes: "1 food item from your own pack",
       gives: `hunger down by its worth (${foods_text()}), a little health` }
}
fn cook_spec() { #{ target: true, item: true, reach: 1.5, about: "Cook raw fish or meat at a campfire beside you: about twice as filling, and it keeps longer. Needs cooking.", takes: "1 raw fish or meat from your pack, a campfire in reach, knowing cooking", gives: "1 cooked_fish or cooked_meat" } }
fn smoke_spec() { #{ target: true, item: true, reach: 1.5, about: "Smoke raw fish or meat at a campfire beside you so it keeps for weeks: food to store, carry far or trade. Needs smoking.", takes: "1 raw fish or meat from your pack, a campfire in reach, knowing smoking, 10 seconds", gives: "1 smoked_fish or smoked_meat: more filling than raw" } }
fn clear_spec() { #{ about: "Turn the forest where you stand into open ground. For making room to build; gathering at a tree is the quicker way to get wood.", takes: "forest where you stand, room in your pack, some energy (faster with an axe)", gives: "open ground where the forest was, and 2 wood" } }
fn graze_spec() { #{ listed: false, about: "Eat grass where you stand (grazing animals).", takes: "grass where you stand, not grazed bare", gives: "hunger down by 14" } }
fn sleep_spec() { #{ about: "Sleep until rested. Night is the time for it; beside a shelter or house it is much faster and the night cold can't hurt you. A short break is rest.", takes: "time, until rested", gives: "energy back quickly (much faster beside a shelter or house); hunger grows slower meanwhile" } }
fn rest_spec() { #{ about: "Sit a few seconds and recover a little energy. Sleep restores far more.", takes: "8 seconds", gives: "a little energy" } }
fn wait_spec() { #{ args: ["qty"], about: "Pause where you are (qty: seconds, at most 120).", takes: "time", gives: "nothing: time passes" } }

fn build_spec() {
    let l = laws();
    #{ item: true, items: ["campfire", "shelter", "storage", "house", "trap", "wall", "gate", "bridge"], reach: 1.5,
       about: "Build a structure where you stand (campfire, shelter, storage, house, trap), or a wall, gate or bridge on the tile beside you that you point at (target {\"at\": [x, y]}; a bridge goes on water). There is no repairing or mending of anything: a structure stands until it is gone.",
       takes: `its materials from your pack (campfire ${cost_text("campfire")}; shelter ${cost_text("shelter")}; storage ${cost_text("storage")}; house ${cost_text("house")}; wall ${cost_text("wall")}; gate ${cost_text("gate")}; trap ${cost_text("trap")}; bridge ${cost_text("bridge")}) and knowing its technique`,
       gives: `the structure here: a campfire warms within ${l.fire_warmth} tiles at night, a shelter or house within ${l.shelter_warmth} and makes sleep restful, a storage keeps items (food spoils slower), a trap catches game over time (take the meat from it), a bridge makes the water tile beside you a way across` }
}
fn pave_spec() { #{ about: "Lay road on the tile you stand on. Walking on road is faster: worth it on ways walked often.", takes: cost_text("road"), gives: "road under you" } }
fn open_spec() { #{ target: true, reach: 1.8, about: "Open a gate. Only members of the gate's community may; anyone else must ask one of them.", takes: "a gate in reach, belonging to your community", gives: "the gate open: anyone may pass" } }
fn close_spec() { #{ target: true, reach: 1.8, about: "Close a gate: closed, it blocks the way like a wall. Only members of its community may.", takes: "a gate in reach, belonging to your community", gives: "the gate shut" } }
fn craft_spec() {
    #{ item: true, items: ["spear", "cloak", "torch", "axe", "pick", "net", "basket", "bow", "arrow", "salve", "leather", "armor"],
       about: "Make a tool, weapon or garment from materials in your pack. Each needs its technique. Structures are built (build); nothing is repaired.",
       takes: `its materials from your pack (spear ${cost_text("spear")}; cloak ${cost_text("cloak")}; torch ${cost_text("torch")}; axe ${cost_text("axe")}; pick ${cost_text("pick")}; net ${cost_text("net")}; basket ${cost_text("basket")}; bow ${cost_text("bow")}; arrow ${cost_text("arrow")} for 3; salve ${cost_text("salve")}; leather ${cost_text("leather")}; armor ${cost_text("armor")}) and knowing how`,
       gives: "the item in your pack: a spear hits harder, a cloak keeps the night cold off, a torch lights the night, an axe or pick gathers faster, a net catches two fish at a time, a basket carries 20 more, a bow shoots arrows, a salve helps tending, armor softens blows" }
}

fn give_spec() {
    #{ target: true, item: true, args: ["qty"], reach: 1.8, talk: true,
       about: "Hand items from your pack to someone beside you. Nothing is asked in return; for an exchange now, offer. It is also how you pay what you agreed to or what is demanded of you: the world counts it.",
       takes: "the items from your pack, room in their pack", gives: "the items in their pack" }
}
fn store_spec() {
    #{ target: true, item: true, args: ["qty"], reach: 1.5,
       about: "Put items from your pack into a storage beside you. Storing into someone's household store is how goods are delivered to them while they are away.",
       takes: `the items from your pack, a storage in reach with room (a storage holds ${storage_holds(0)} things in all)`, gives: "the items in the storage" }
}
fn take_spec() {
    #{ target: true, item: true, args: ["qty"], reach: 1.5,
       about: "Take items from a storage, remains or a trap beside you. From another household's store, unless you are their guest or of their community, it is theft: its owner and anyone watching see it.",
       takes: "items in a storage, remains or a trap in reach, room in your pack", gives: "the items in your pack" }
}
fn drop_spec() { #{ item: true, args: ["qty"], about: "Set items down where you stand and leave them, e.g. to free your pack. What is dropped is kept for no one.", takes: "the items from your pack", gives: "room in your pack; the items are left behind" } }

fn attack_spec() {
    #{ target: true, reach: 1.4,
       about: "Strike a creature beside you. Every blow does its full damage and whoever reaches 0 health dies; there is no holding back. To frighten someone without harm, threaten. Killing game yields meat and hide.",
       takes: "a creature in reach, a little energy",
       gives: "a blow (harder with a spear, strength and practice); a creature killed leaves remains with meat and hide to take" }
}
fn strike_spec() {
    #{ target: true, reach: 1.6,
       about: "A quick blow at a creature in reach, after a short windup they can see. It does its full damage like any blow; 0 health is death.",
       takes: `a creature within reach, ${combat_cost("strike")} energy; ready again ${combat_cooldown("strike")} ms after you start`,
       gives: "a quick blow (harder with a spear, strength and practice); out of reach by then, it misses; a raised guard in front of them takes most of it" }
}
fn bowshot_spec() {
    #{ target: true, reach: 22.0,
       about: "Loose an arrow toward a creature or a point (target {\"at\": [x, y]}): it flies straight and hits the first creature in its path, whoever that is.",
       takes: `a bow and 1 arrow, ${combat_cost("bowshot")} energy, a creature or a point to aim at (up to 22 tiles)`,
       gives: "a hit at range (softened by armor); the arrow is spent" }
}
fn firebolt_spec() {
    #{ target: true, reach: 16.0,
       about: "Hurl a bolt of fire toward a creature or a point: it burns the first creature it meets, hard. Needs the fire_bolt technique.",
       takes: `knowing fire_bolt, ${combat_cost("firebolt")} energy, a creature or a point to aim at (up to 16 tiles); ready again after ${combat_cooldown("firebolt") / 1000} s`,
       gives: "a bolt of fire that burns the first creature it meets" }
}
fn throw_spec() { #{ target: true, reach: 7.0, about: "Throw your spear at a creature up to 7 tiles away. The spear is gone afterwards.", takes: "your spear", gives: "a hard hit at range" } }
fn shoot_spec() { #{ target: true, reach: 9.0, about: "Shoot an arrow from your bow at a creature up to 9 tiles away.", takes: "a bow and 1 arrow, a creature within 9 tiles", gives: "a hit at range (softened by armor); the arrow is spent" } }
fn threaten_spec() {
    #{ target: true, reach: 3.0,
       about: "Menace a creature within a few tiles for 2 s, weapon raised. No harm is done, but they and anyone watching see it: a way to make a warning or a demand felt without a blow.",
       takes: "a creature within a few tiles, 2 seconds", gives: "no harm: they see you menacing them, and so does anyone watching" }
}
fn seize_spec() {
    #{ target: true, item: true, args: ["qty"], reach: 1.8,
       about: "Take items from a person's pack against their will: only from someone who has yielded to you or is badly hurt. Everyone who sees it knows it was taken by force.",
       takes: "a person in reach who has yielded to force or is badly hurt, the items in their pack", gives: "the items in your pack; they and anyone watching see you take them" }
}
fn yield_spec() {
    #{ reach: 12.0,
       about: "Give in: guard down, hands up (target: whom you yield to; without one, whoever last hurt you). It says you surrender; it does not stop blows by itself.",
       takes: "a second",
       gives: `for ${(yield_ms("person") / 1000.0).to_int()} seconds you do not strike back. Blows still land on you, but whoever strikes you meanwhile is seen striking someone who gave in` }
}
fn dodge_spec() { #{ about: "Dash out of the way (away from what is coming, or toward a point you aim at); a blow or missile landing while you dash misses. For fights, not travel.", takes: `${combat_cost("dodge")} energy`, gives: "a quick dash of a few tiles" } }
fn block_spec() { #{ args: ["qty"], about: "Raise your guard toward what threatens you (or a point you aim at) for a moment (qty: ms to hold it). Blows from the front do a quarter of their damage; from behind it does not help.", takes: `${combat_cost("block")} energy, holding still`, gives: "a guard in front of you" } }
fn heal_spec() {
    #{ reach: 8.0,
       about: "Close wounds at once with your hands, your own or an ally's in sight within 8 tiles, even in a fight. Needs the wound_tending technique. It heals bodies only: it does not mend tools, hinges, nets or anything else.",
       takes: `knowing wound_tending, ${combat_cost("heal")} energy, yourself or a hurt ally in sight within 8 tiles; ready again after ${combat_cooldown("heal") / 1000} s`,
       gives: "their wounds closed at once" }
}
fn tend_spec() {
    #{ target: true, reach: 1.5,
       about: "Tend someone's wounds by hand (a person beside you, or \"self\"): slow, and not while they are fighting. Anyone can tend; a salve helps if you know medicine. heal is the quick way, for those who know wound_tending.",
       takes: "a hurt person in reach who is not fighting, a little energy (and a salve, if you know medicine)", gives: "their wounds healed some (far more with a salve)" }
}

fn follow_spec() { #{ target: true, reach: 2.0, about: "Walk alongside a creature for a while, keeping up as it moves: to go somewhere together or keep watch on someone. It does not make them follow you.", takes: "a creature in sight", gives: "you beside them as they go" } }
fn flee_spec() { #{ target: true, about: "Run away from a creature or place until you are clear of it.", takes: "something to run from", gives: "distance between you and it" } }

fn offer_spec() {
    #{ target: true, item: true, args: ["qty", "want", "want_qty"], reach: 3.0, talk: true,
       about: "Propose a swap now to a person beside you: item × qty you give for want × want_qty you ask. If they accept, both sides change hands at once. For goods in hand; for work, or for something delivered later, offer_terms.",
       takes: "the goods in your pack when they accept", gives: "their goods in your pack, if they accept" }
}
fn accept_spec() {
    #{ target: true, reach: 3.0, talk: true,
       about: "Accept what a person beside you just proposed to you: their terms (offer_terms: it becomes an agreement the world keeps count of; you then owe what they asked of you, and they owe what they offered you), or else their swap (both sides change hands at once, if both still have the goods).",
       takes: "a standing proposal from them to you", gives: "the swap done, or the agreement made" }
}
fn offer_terms_spec() {
    #{ target: true, item: true, items: ["lodging"], args: ["qty", "want", "want_qty", "text"], reach: 3.0, talk: true,
       about: `Propose an agreement to a person beside you, kept over time. item × qty is what YOU will deliver to them; want × want_qty is what THEY will deliver to you. To be given a bed for your goods or work, put what you will bring in item and "lodging" in want; put "lodging" in item only if you have a house and will take them in. text: the terms in your words ("stack it at my store"). A delivery is handing it to them or storing it in their household's store; "lodging" is delivered by taking the guest in (host). It falls due at the first dusk at least ${agreement_min_h(0).to_int()} hours after they accept; the world keeps count and tells you both when it is kept, or broken or lapsed then. For a swap of goods in hand now, offer.`,
       takes: "a person beside you who accepts", gives: "an agreement both of you are told the outcome of" }
}
fn demand_spec() {
    #{ target: true, item: true, args: ["qty", "text"], reach: 6.0, talk: true,
       about: "Demand items of a person near you: a toll, a due, rent or a debt (text: why, in your words). They are told and may give them to you; refusing is simply not paying, and the world tells you when they have paid or have not, after a while. What you do then is up to you: a demand takes nothing by itself.",
       takes: "a person near you", gives: "your demand, which they may pay" }
}
fn found_spec() { #{ args: ["text"], about: "Found a community with its home where you stand (text: its name); you become its first member.", takes: "a name, not being in a community", gives: "a new community of one" } }
fn join_spec() { #{ target: true, reach: 3.0, about: "Ask a member of a community to let you join it; a member must welcome you.", takes: "a member beside you", gives: "your request, which they may answer" } }
fn welcome_spec() { #{ target: true, reach: 3.0, talk: true, about: "Welcome into your community a person who asked to join it.", takes: "a person beside you who asked to join", gives: "they are a member" } }
fn leave_spec() { #{ about: "Leave your community.", takes: "", gives: "you belong to no community" } }
fn host_spec() {
    #{ target: true, reach: 3.0, talk: true,
       about: "Take a person in as your household's guest until morning: a bed in your house and food from its store. Needs a house at your home door.",
       takes: "a person beside you, and a house of your household's (at your home door), 2 s",
       gives: "they are your guest until 7 in the morning: they know where your house is (their place \"lodging\"), may sleep there, and may take from your household's store" }
}

fn conceive_spec() { #{ target: true, reach: 2.0, talk: true, about: "Start a family with a willing adult partner: it happens when both of you choose it toward each other within 2 minutes, while fed.", takes: "a willing adult partner choosing it too, both fed", gives: "a child in time" } }
fn teach_spec() { #{ target: true, item: "technique", reach: 2.0, talk: true, about: "Teach a technique you know to a person beside you. It takes a while and both must stay close; afterwards they know it and you still do.", takes: "a technique you know, a person beside you staying close for a while", gives: "they know it too" } }
fn experiment_spec() { #{ item: "material", about: "Tinker with a material from your pack hoping to work out a new technique. It uses up the material and often fails; learning from someone who knows is surer.", takes: "1 of the material", gives: "sometimes a new technique" } }
fn write_spec() { #{ item: true, items: ["tablet", "sign"], args: ["text", "topic"], about: "Write on a tablet you keep or a sign you leave here (text: your words; topic: a technique you know, so that readers can learn it). Needs writing.", takes: "1 wood, knowing writing", gives: "a tablet you keep or a sign left here, with your words" } }
fn read_spec() { #{ reach: 1.5, about: "Read a tablet you carry, or a sign beside you (target {\"nearest\": \"sign\"}). Needs writing.", takes: "a tablet you carry or a sign here, knowing writing", gives: "its words; a tablet describing a technique can teach it" } }
fn plant_spec() { #{ about: "Plant 2 berries where you stand to grow a new berry bush. Needs planting.", takes: "2 berries, open grass or dirt outside winter, knowing planting", gives: "a new berry bush in time" } }
fn signal_spec() { #{ item: "signal name", about: "Make one of your species' signals; others nearby hear it.", takes: "a moment", gives: "your call, heard by those nearby" } }
fn rework_spec() {
    #{ item: "a routine's name, or \"top level\"", args: ["graph", "retire"],
       about: "Sit and rework one of your ways (graph: the new version, or retire: true to drop it). It takes a while, and the old way must have been lived with first.",
       takes: "a while sitting still; an old way must have been tried about 4 times, failed twice or kept 15 minutes (the top level: about two days)",
       gives: "that way replaced by your new version (or dropped); how it goes starts counting afresh" }
}

fn wave_spec() { #{ target: true, reach: 12.0, about: "Wave to someone you can see: a greeting, a farewell or an answer to one. They see it and may answer.", takes: "someone in sight within 12 tiles, 1.2 s", gives: "they see you wave at them" } }
fn nod_spec() { #{ target: true, reach: 6.0, about: "Nod to someone near you: a quiet greeting or a yes. They see it and may answer.", takes: "someone within 6 tiles, 0.7 s", gives: "they see you nod at them" } }
fn appraise_spec() { #{ target: true, reach: 6.0, about: "Look someone (a person or an animal) over closely: for a while you see exactly how hurt they are.", takes: "someone within 6 tiles, 1.5 s", gives: "for 20 s you see exactly how hurt they are" } }
fn face_spec() { #{ target: true, reach: 15.0, about: "Turn where you stand to face someone or something you can see (a person coming up to you or speaking, a fight, a sound).", takes: "something or someone in sight", gives: "you turn to face it" } }
fn step_aside_spec() { #{ target: true, reach: 3.0, about: "Step a pace aside to let someone coming toward you pass, in a narrow street or a doorway.", takes: "someone coming at you where there is little room", gives: "a pace to the side, out of their way" } }
fn keep_spec() { #{ about: "Keep your post a while (a stall, a workshop, a gate, a door): stand at it and attend to whoever comes by.", takes: "10 seconds at your post", gives: "you are seen at work there" } }
fn play_spec() { #{ about: "Play a little while where you are (run about, skip, make up a game).", takes: "4 seconds, not a baby", gives: "a little fun; tires a little" } }

// ---- gestures and town life (docs/TOWN_LIFE.md) ---------------------------------------
// A gesture is seen, not heard: its target must be in sight within the gesture's reach.
// `hail` lets the one it is made at see that it was made at them (they may answer).
fn gesture_check(a, reach) {
    if a.target.class != "creature" || !a.target.alive { return "no one there"; }
    if a.target.id == a.actor.id { return "not to yourself"; }
    if a.actor.stage == "infant" { return "too small"; }
    if a.actor.activity == "sleep" { return "you are asleep"; }
    if a.target.dist > reach { return "too far for them to see it"; }
    ""
}
fn wave_check(a) { gesture_check(a, 12.0) }
fn wave_duration(a) { 1200 }
fn wave_done(a) { [#{ op: "hail" }] }
// Appraising: looking someone over closely shows exactly how hurt they are, for a while.
fn appraise_check(a) {
    if a.target.class != "creature" || !a.target.alive { return "no one there"; }
    if a.target.id == a.actor.id { return "you know how you feel"; }
    if a.actor.activity == "sleep" { return "you are asleep"; }
    if a.target.dist > 6.0 { return "too far to look them over"; }
    ""
}
fn appraise_duration(a) { 1500 }
fn appraise_done(a) { [#{ op: "reveal", what: "health", secs: 20.0 }] }
fn nod_check(a) { gesture_check(a, 6.0) }
fn nod_duration(a) { 700 }
fn nod_done(a) { [#{ op: "hail" }] }
// Turning where one stands to face what one sees (already facing it within the `face_slack`
// law, the engine refuses it before asking: there is nothing to do).
fn face_check(a) {
    if a.target.class == "none" { return "nothing to face"; }
    if a.target.class == "creature" && a.target.id == a.actor.id { return "not yourself"; }
    ""
}
fn face_duration(a) { 600 }
fn face_done(a) { [] }
// Making way: a pace aside for someone coming at you where there is little room to pass.
fn step_aside_check(a) {
    if a.target.class != "creature" || a.target.id == a.actor.id { return "no one to make way for"; }
    if a.target.closing < 0.5 { return "no one is coming your way"; }
    if a.actor.room > 19 { return "there is room enough to pass"; }
    ""
}
fn step_aside_dist(kind) { 1.2 }
// Keeping one's post: standing at a stall, a workshop or a gate, attending to who comes.
fn keep_check(a) { if young(a) { return "too young to keep a post"; } if a.actor.activity == "sleep" { return "you are asleep"; } "" }
fn keep_duration(a) { 10000 }
fn keep_done(a) { [#{ op: "vitals", energy: -0.3 }] }
fn play_check(a) { if a.actor.stage == "infant" { return "too small to play"; } "" }
fn play_duration(a) { 4000 }
fn play_done(a) { [#{ op: "vitals", energy: -0.5 }] }

// What others see of a skill: `<skill>_shows()`, read once when the script is installed.
// Every skill with one gets an `act_card` and a presentation code (its place in name order),
// and while it is performed a `doing` row anyone in view can see. Traits:
//   look    how it looks (clients draw a skill they know by name, any other by its look)
//   faces   the body turns where it stands to face the skill's target when it starts
//   turn    turning is all it does: facing its target already (`face_slack`), it is refused
//           before its rules are asked
//   aside   a short walk to the side of the creature it targets (`<skill>_dist(kind)`), only
//           while that creature is coming toward the actor
//   record  each use is kept in `skill_use`, from intention to outcome, like a combat move
fn wave_shows() { #{ look: "gesture", faces: true, record: true } }
fn nod_shows() { #{ look: "gesture", faces: true, record: true } }
fn appraise_shows() { #{ look: "gesture", faces: true, record: true } }
fn face_shows() { #{ look: "turn", faces: true, turn: true, record: true } }
fn step_aside_shows() { #{ look: "step", aside: true, record: true } }
fn play_shows() { #{ look: "play" } }
fn keep_shows() { #{ look: "work" } }
fn gather_shows() { #{ look: "work" } }
fn plant_shows() { #{ look: "work" } }
fn cook_shows() { #{ look: "work" } }
fn store_shows() { #{ look: "work" } }
fn take_shows() { #{ look: "work" } }
fn craft_shows() { #{ look: "work" } }
fn read_shows() { #{ look: "work" } }
fn tend_shows() { #{ look: "work" } }
fn eat_shows() { #{ look: "eat" } }
fn sleep_shows() { #{ look: "sleep" } }
fn rest_shows() { #{ look: "rest" } }
