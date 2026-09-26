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
    }
}

fn knows(a, t) { a.actor.knows.contains(t) }

fn inv(a, item) {
    let n = a.actor.inv[item];
    if n == () { 0 } else { n }
}

fn nutrition(item) {
    switch item {
        "berries" => 12.0,
        "fish" => 16.0,
        "meat" => 20.0,
        "cooked_fish" => 34.0,
        "cooked_meat" => 42.0,
        _ => 0.0,
    }
}

// ---- needs -------------------------------------------------------------

fn rates(a) {
    let hunger = switch a.actor.kind { "deer" => 6.0, "wolf" => 5.0, _ => 5.0 };
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
    if a.actor.stage == "infant" { hunger *= 0.6; }
    // Cold nights hurt people without a fire, shelter or warm cloak; winter nights are worse.
    if a.night && a.actor.kind == "person" && !a.actor.near_fire && !a.actor.near_shelter && inv(a, "cloak") == 0 {
        hp -= if a.season == "winter" { 5.0 } else { 2.0 };
    }
    #{ hunger: hunger, energy: energy, hp: hp }
}

fn move_speed(a) {
    let base = switch a.actor.kind { "deer" => 3.2, "wolf" => 3.4, _ => 2.6 };
    if a.actor.stage == "infant" { base *= 0.4; } else if a.actor.stage == "child" { base *= 0.8; } else if a.actor.stage == "elder" { base *= 0.85; }
    if a.actor.energy < 10.0 { base * 0.6 } else { base }
}

// ---- gathering and food ------------------------------------------------

fn gather_check(a) {
    if a.target.class != "resource" { return "that is not something to gather"; }
    if a.target.amount < 1.0 { return `the ${a.target.kind} is depleted`; }
    if a.actor.kind != "person" { return "only people gather"; }
    if a.actor.stage == "infant" { return "too small to gather"; }
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
fn gather_done(a) {
    let item = switch a.target.kind {
        "berry_bush" => "berries",
        "tree" => "wood",
        "boulder" => "stone",
        "reeds" => "fiber",
        "fishing_spot" => "fish",
        "clay_bank" => "clay",
        _ => "",
    };
    [#{ op: "harvest", qty: 1 }, #{ op: "add", item: item, qty: 1 }, #{ op: "vitals", energy: -1.0 }]
}

fn eat_check(a) {
    if nutrition(a.item) <= 0.0 { return `${a.item} is not food`; }
    if inv(a, a.item) < 1 { return `no ${a.item} in pack`; }
    ""
}
fn eat_duration(a) { 1500 }
fn eat_done(a) {
    [#{ op: "remove", item: a.item, qty: 1 }, #{ op: "vitals", hunger: -nutrition(a.item), hp: 1.0 }]
}

fn cook_check(a) {
    if !knows(a, "cooking") { return "you don't know how to cook"; }
    if a.target.kind != "campfire" { return "cooking needs a campfire"; }
    if a.item != "fish" && a.item != "meat" { return "only raw fish or meat can be cooked"; }
    if inv(a, a.item) < 1 { return `no ${a.item} in pack`; }
    ""
}
fn cook_duration(a) { 4000 }
fn cook_done(a) {
    [#{ op: "remove", item: a.item, qty: 1 }, #{ op: "add", item: "cooked_" + a.item, qty: 1 }]
}

fn graze_check(a) {
    if a.actor.kind != "deer" { return "only deer graze"; }
    if a.actor.terrain != "grass" && a.actor.terrain != "forest" { return "no grass here"; }
    ""
}
fn graze_duration(a) { 4000 }
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
        _ => (),
    }
}
fn afford(a, kind) {
    let c = cost(kind);
    if c == () { return `cannot make ${kind}`; }
    for k in c.keys() {
        if inv(a, k) < c[k] { return `need ${c[k]} ${k} for a ${kind}`; }
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
        _ => (),
    };
    if needed == () { return `cannot build ${a.item}`; }
    if !knows(a, needed) { return `you don't know how to build a ${a.item}`; }
    if a.item == "wall" || a.item == "gate" {
        if a.target.class != "place" { return `point at the tile beside you where the ${a.item} goes`; }
    } else if a.actor.terrain == "water" || a.actor.terrain == "rock" || a.actor.terrain == "wall" { return "cannot build here"; }
    if a.item == "campfire" && a.actor.near_fire { return "a campfire already burns right here"; }
    if a.item == "shelter" && a.actor.near_shelter { return "there is already a shelter right here"; }
    afford(a, a.item)
}
fn build_duration(a) { switch a.item { "campfire" => 6000, "shelter" => 20000, "house" => 40000, "wall" => 6000, "gate" => 15000, _ => 10000 } }
fn build_done(a) {
    // Place first: if the spot turns out unusable, nothing is spent.
    let fx = [#{ op: "build", kind: a.item }];
    fx += pay(a.item);
    fx.push(#{ op: "vitals", energy: -4.0 });
    fx
}

fn craft_check(a) {
    if young(a) { return "too young to craft"; }
    if a.item != "spear" && a.item != "cloak" && a.item != "torch" && a.item != "axe" && a.item != "pick" { return `cannot craft ${a.item}`; }
    let needed = if a.item == "axe" || a.item == "pick" { "toolmaking" } else { a.item };
    if !knows(a, needed) { return `you don't know how to make a ${a.item}`; }
    afford(a, a.item)
}
fn craft_duration(a) { 8000 }
fn craft_done(a) {
    let fx = pay(a.item);
    fx.push(#{ op: "add", item: a.item, qty: 1 });
    fx
}

// ---- exchange -----------------------------------------------------------

fn amount(a) { if a.qty < 1 { 1 } else { a.qty } }

fn give_check(a) {
    if a.target.class != "creature" || !a.target.alive { return "no one to give to"; }
    if a.target.id == a.actor.id { return "cannot give to yourself"; }
    if inv(a, a.item) < amount(a) { return `not enough ${a.item}`; }
    ""
}
fn give_duration(a) { 1000 }
fn give_done(a) { [#{ op: "give", item: a.item, qty: amount(a) }] }

fn store_check(a) {
    if a.target.kind != "storage" { return "can only store in a storage"; }
    if inv(a, a.item) < amount(a) { return `not enough ${a.item}`; }
    ""
}
fn store_duration(a) { 1000 }
fn store_done(a) { [#{ op: "store", item: a.item, qty: amount(a) }] }

fn take_check(a) {
    if a.target.kind != "storage" && a.target.kind != "remains" { return "nothing to take from"; }
    let have = a.target.inv[a.item];
    if have == () || have < 1 { return `no ${a.item} there`; }
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

fn attack_check(a) {
    if a.actor.kind == "person" && young(a) { return "too young to fight"; }
    if a.target.class != "creature" || !a.target.alive { return "nothing to attack"; }
    if a.target.id == a.actor.id { return "cannot attack yourself"; }
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
    [#{ op: "damage", amount: dmg }, #{ op: "vitals", energy: -1.5 }]
}

// Meat left when a creature dies at someone's hand.
fn carcass_meat(kind) { switch kind { "deer" => 3, "wolf" => 2, _ => 0 } }
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
    if a.actor.kind == "person" {
        if !a.actor.near_shelter { return "a family needs a shelter nearby"; }
    } else if a.season != "spring" { return "it is not the season"; }
    ""
}
fn conceive_duration(a) { 3000 }
fn conceive_done(a) { [#{ op: "bond" }] }

// ---- signals (species vocabulary is checked by the engine) --------------

fn signal_duration(a) { 800 }
fn signal_done(a) { [#{ op: "signal" }] }

// ---- know-how -----------------------------------------------------------------

fn requires(t) { switch t { "cooking" => ["fire"], "torch" => ["fire"], "carpentry" => ["shelter"], _ => [] } }

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

fn teach_check(a) {
    if !knows(a, a.item) { return `you don't know ${a.item} yourself`; }
    if a.target.class != "creature" || a.target.kind != "person" || !a.target.alive { return "no one to teach"; }
    if a.target.knows.contains(a.item) { return `they already know ${a.item}`; }
    for r in requires(a.item) { if !a.target.knows.contains(r) { return `they must first learn ${r}`; } }
    ""
}
fn teach_duration(a) { 15000 }
fn teach_done(a) { [#{ op: "teach", technique: a.item }] }

// What tinkering with a material can reveal.
fn discoveries(m) {
    switch m {
        "stone" => ["spear", "fire", "masonry", "toolmaking"],
        "wood" => ["fire", "storage", "writing", "torch", "carpentry", "toolmaking"],
        "clay" => ["carpentry", "masonry"],
        "fiber" => ["shelter", "torch", "cloak"],
        "hide" => ["cloak"],
        "berries" => ["planting"],
        "meat" => ["cooking"],
        "fish" => ["cooking"],
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
        if t == "cooking" && !a.actor.near_fire { ok = false; }
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
    if !knows(a, "writing") { return "you don't know how to write"; }
    if a.item != "tablet" && a.item != "sign" { return "you can write a tablet or a sign"; }
    if inv(a, "wood") < 1 { return "writing needs 1 wood"; }
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
fn tend_done(a) { [#{ op: "heal", amount: 10.0 }, #{ op: "vitals", energy: -1.0 }] }

fn read_check(a) {
    if !knows(a, "writing") { return "you can't read"; }
    ""
}
fn read_duration(a) { 6000 }
fn read_done(a) { [#{ op: "read" }] }

fn plant_check(a) {
    if !knows(a, "planting") { return "you don't know how to plant"; }
    if inv(a, "berries") < 2 { return "planting needs 2 berries"; }
    if a.actor.terrain != "grass" && a.actor.terrain != "dirt" { return "nothing grows here"; }
    if a.season == "winter" { return "the ground is frozen"; }
    ""
}
fn plant_duration(a) { 5000 }
fn plant_done(a) { [#{ op: "remove", item: "berries", qty: 2 }, #{ op: "plant" }] }

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
    ""
}
fn throw_duration(a) { 800 }
fn throw_done(a) { [#{ op: "remove", item: "spear", qty: 1 }, #{ op: "damage", amount: 24.0 }, #{ op: "vitals", energy: -2.0 }] }

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
