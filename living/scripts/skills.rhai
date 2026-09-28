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
    }
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

fn rates(a) {
    // A predator feeds big and rarely: a wolf lasts about an hour on a deer.
    let hunger = switch a.actor.kind { "deer" => 6.0, "wolf" => 1.5, _ => 5.0 };
    let energy = -3.0;
    let hp = 0.0;
    let act = a.actor.activity;
    if act == "sleep" {
        energy = if a.actor.near_shelter { 26.0 } else { 16.0 };
        hunger *= 0.5;
    } else if act == "rest" {
        energy = 6.0;
    }
    if a.actor.hunger >= 100.0 {
        hp -= 6.0;
    } else if a.actor.hunger < 70.0 && a.actor.energy > 15.0 {
        hp += 3.0;
    }
    if a.actor.energy <= 0.0 {
        hp -= 2.0;
    }
    // Elders heal slower and tire sooner; infants get hungry more slowly. (Death of old age
    // comes at each creature's own point late in its lifespan.)
    if a.actor.stage == "elder" {
        if hp > 0.0 { hp *= 0.5; }
        energy *= 1.3;
    }
    // A suckling animal lives mostly on its mother's milk (not modelled on the mother).
    if a.actor.stage == "infant" { hunger *= if a.actor.kind == "person" { 0.6 } else { 0.3 }; }
    // Inborn endurance slows tiring; vitality speeds healing.
    if energy < 0.0 { energy /= a.actor.endurance; }
    if hp > 0.0 { hp *= a.actor.vitality; }
    // Cold nights hurt people without a fire, shelter or warm cloak; winter nights are worse.
    if a.night && a.actor.kind == "person" && !a.actor.near_fire && !a.actor.near_shelter && inv(a, "cloak") == 0 {
        hp -= if a.season == "winter" { 5.0 } else { 2.0 };
    }
    #{ hunger: hunger, energy: energy, hp: hp }
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
// Force is graded. An attack is meant to hurt (a beating: it stops once the other is badly
// hurt or gives in, and never takes anyone near death) or to kill. The node's item says
// which ("hurt" or "kill"); without it, people mean to hurt people, and every fight with an
// animal is to kill. Threatening someone does no harm; yielding stops resisting.

// How long a yield holds: the one who yielded does not strike back, and blows meant only to
// hurt are held back from them (ms).
fn yield_ms(kind) { 20000.0 }
// A beating stops once its target is down to this share of full health...
fn hurt_enough(kind) { 0.4 }
// ...and a blow meant only to hurt never takes anyone below this share.
fn hurt_floor(kind) { 0.1 }

fn within(ago, ms) { ago != () && ago < ms }
fn yielding(a) { within(a.actor.yielded_ago, yield_ms(a.actor.kind)) }
fn sensed(a, kind) { let n = a.actor.sensed[kind]; if n == () { 0 } else { n } }
fn attack_mode(a) {
    if a.item == "hurt" || a.item == "kill" { return a.item; }
    if a.actor.kind == "person" && a.target.kind == "person" { "hurt" } else { "kill" }
}
// How the attacker refers to its target, and how the target looks.
fn who(a) { if a.target.kind == a.actor.kind || a.target.name == "" { a.target.name } else { "the " + a.target.kind } }
fn looks(t) {
    let f = if t.max_hp > 0.0 { t.hp / t.max_hp } else { 0.0 };
    if f < 0.2 { "barely standing" } else if f < hurt_enough(t.kind) { "badly hurt" } else { "hurt" }
}

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
    if attack_mode(a) == "hurt" {
        if within(a.target.yielded_ago, yield_ms(a.target.kind)) { return `${who(a)} has yielded`; }
        if a.target.hp < hurt_enough(a.target.kind) * a.target.max_hp { return `you have hurt ${who(a)} enough: they are ${looks(a.target)}`; }
    }
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
    // A blow meant to hurt is held short of taking them near death.
    if attack_mode(a) == "hurt" {
        let room = a.target.hp - hurt_floor(a.target.kind) * a.target.max_hp;
        if room < 0.0 { room = 0.0; }
        if dmg > room { dmg = room; }
    }
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

fn dodge_check(a) { if a.actor.energy < 5.0 { "too exhausted to dodge" } else { "" } }
fn dodge_done(a) { [#{ op: "vitals", energy: -2.0 }] }

fn block_check(a) { if a.actor.kind != "person" { "only people can block" } else { "" } }
fn block_duration(a) { 1200 }
fn block_done(a) { [#{ op: "vitals", energy: -0.5 }] }

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
fn accept_done(a) { [#{ op: "accept" }] }

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

// ---- what each skill takes and gives -------------------------------------------------
// Read by minds to compose routines from skills: keep these beside the rules above, and
// build them from the same numbers so they change when the rules do.

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
fn skill_io(skill) {
    let l = laws();
    switch skill {
        "goto" => #{ takes: "a target in sight or a known place", gives: `you there; within ${l.fire_warmth} tiles of a campfire or ${l.shelter_warmth} of a shelter or house the night cold can't hurt you` },
        "wander" => #{ takes: "", gives: "you at a nearby spot you may not have seen" },
        "gather" => #{ takes: "a resource in reach with some left, room in your pack, a little energy",
            gives: "1 unit into your pack: berry_bush→berries, tree→wood (faster with an axe), boulder→stone (faster with a pick), reeds→fiber, fishing_spot→fish (faster with a spear, two at a time with a net), clay_bank→clay" },
        "eat" => #{ takes: "1 food item from your own pack (item: its name, or \"food\" for your best)", gives: `hunger down by its worth (${foods_text()}), a little health` },
        "cook" => #{ takes: "1 raw fish or meat from your pack, a campfire in reach, knowing cooking", gives: "1 cooked_fish or cooked_meat: about twice as filling, keeps longer" },
        "smoke" => #{ takes: "1 raw fish or meat from your pack, a campfire in reach, knowing smoking, 10 seconds", gives: "1 smoked_fish or smoked_meat: more filling than raw, keeps for weeks (food to carry far or trade)" },
        "clear" => #{ takes: "forest where you stand, room in your pack, some energy (faster with an axe)", gives: "open ground where the forest was, and 2 wood" },
        "graze" => #{ takes: "grass where you stand, not grazed bare", gives: "hunger down by 14" },
        "sleep" => #{ takes: "time, until rested", gives: "energy back quickly (much faster beside a shelter or house); hunger grows slower meanwhile" },
        "rest" => #{ takes: "8 seconds", gives: "a little energy" },
        "wait" => #{ takes: "time", gives: "nothing: time passes" },
        "build" => #{ takes: `its materials from your pack (campfire ${cost_text("campfire")}; shelter ${cost_text("shelter")}; storage ${cost_text("storage")}; house ${cost_text("house")}; wall ${cost_text("wall")}; gate ${cost_text("gate")}; trap ${cost_text("trap")}; bridge ${cost_text("bridge")}) and knowing its technique`,
            gives: `the structure here: a campfire warms within ${l.fire_warmth} tiles at night, a shelter or house within ${l.shelter_warmth} and makes sleep restful, a storage keeps items (food spoils slower), a trap catches game over time (take the meat from it), a bridge makes the water tile beside you a way across` },
        "pave" => #{ takes: cost_text("road"), gives: "road under you (faster walking)" },
        "craft" => #{ takes: `its materials from your pack (spear ${cost_text("spear")}; cloak ${cost_text("cloak")}; torch ${cost_text("torch")}; axe ${cost_text("axe")}; pick ${cost_text("pick")}; net ${cost_text("net")}; basket ${cost_text("basket")}; bow ${cost_text("bow")}; arrow ${cost_text("arrow")} for 3; salve ${cost_text("salve")}; leather ${cost_text("leather")}; armor ${cost_text("armor")}) and knowing how`,
            gives: "the item in your pack: a spear hits harder, a cloak keeps the night cold off, a torch lights the night, an axe or pick gathers faster, a net catches two fish at a time, a basket carries 20 more, a bow shoots arrows, a salve helps tending, armor softens blows" },
        "give" => #{ takes: "the items from your pack", gives: "the items in their pack" },
        "store" => #{ takes: `the items from your pack, a storage in reach with room (a storage holds ${storage_holds(0)} things in all)`, gives: "the items in the storage, for anyone to take" },
        "take" => #{ takes: "items in a storage, remains or a trap in reach, room in your pack", gives: "the items in your pack" },
        "drop" => #{ takes: "the items from your pack", gives: "room in your pack; the items are left behind" },
        "attack" => #{ takes: "a creature in reach, a little energy; item \"hurt\" or \"kill\" says what the blows are meant for (without it: to hurt between people, to kill with animals)",
            gives: `a blow (harder with a spear, strength and practice). Meant to hurt, blows stop once they are down to ${(hurt_enough("person") * 100.0).to_int()}% of their health or have yielded, and never take anyone below ${(hurt_floor("person") * 100.0).to_int()}%; meant to kill, they go on until death. A creature killed leaves remains with meat and hide to take` },
        "threaten" => #{ takes: "a creature within a few tiles, 2 seconds", gives: "no harm: they see you menacing them (weapon raised), and so does anyone watching" },
        "yield" => #{ takes: "a second (target: whom you give in to; without one, whoever last hurt you)",
            gives: `you stop resisting, guard down and hands up: for ${(yield_ms("person") / 1000.0).to_int()} seconds you do not strike back, and blows meant only to hurt are held back from you (blows meant to kill are not)` },
        "throw" => #{ takes: "your spear", gives: "a hard hit at range; the spear is gone" },
        "shoot" => #{ takes: "a bow and 1 arrow, a creature within 9 tiles", gives: "a hit at range (softened by armor); the arrow is spent" },
        "tend" => #{ takes: "a hurt person in reach who is not fighting, a little energy (and a salve, if you know medicine)", gives: "their wounds healed some (far more with a salve)" },
        "plant" => #{ takes: "2 berries, open grass or dirt outside winter, knowing planting", gives: "a new berry bush in time" },
        "experiment" => #{ takes: "1 of the material", gives: "sometimes a new technique" },
        "teach" => #{ takes: "a technique you know, a person beside you staying close for a while", gives: "they know it too" },
        "write" => #{ takes: "1 wood, knowing writing", gives: "a tablet you keep or a sign left here, with your words" },
        "read" => #{ takes: "a tablet you carry or a sign here, knowing writing", gives: "its words; a tablet describing a technique can teach it" },
        "rework" => #{ takes: "a while sitting still; an old way must have been tried about 4 times, failed twice or kept 15 minutes (the top level: about two days)",
            gives: "that way replaced by your new version (or dropped); how it goes starts counting afresh" },
        "conceive" => #{ takes: "a willing adult partner choosing it too, both fed", gives: "a child in time" },
        _ => #{ takes: "", gives: "" },
    }
}
