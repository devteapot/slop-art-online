// Living core skill and needs rules. Functions only; the authority calls them at
// action start (check, duration) and completion (done), and when need rates change.
// `a.actor`, `a.target`, `a.item`, `a.qty`, `a.night`, `a.hour` — see rules/src/script.rs.

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
    let hunger = switch a.actor.kind { "deer" => 6.0, "wolf" => 5.0, _ => 7.0 };
    let energy = -4.0;
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
    // Elders slowly weaken.
    if a.actor.kind == "person" && a.actor.age > 40.0 {
        hp -= (a.actor.age - 40.0) * 1.5;
    }
    // Cold nights hurt people without a fire or shelter nearby.
    if a.night && a.actor.kind == "person" && !a.actor.near_fire && !a.actor.near_shelter {
        hp -= 5.0;
    }
    #{ hunger: hunger, energy: energy, hp: hp }
}

fn move_speed(a) {
    let base = switch a.actor.kind { "deer" => 3.2, "wolf" => 3.4, _ => 2.6 };
    if a.actor.kind == "person" && a.actor.age < 3.0 { base *= 0.75; }
    if a.actor.energy < 10.0 { base * 0.6 } else { base }
}

// ---- gathering and food ------------------------------------------------

fn gather_check(a) {
    if a.target.class != "resource" { return "that is not something to gather"; }
    if a.target.amount < 1.0 { return `the ${a.target.kind} is depleted`; }
    if a.actor.kind != "person" { return "only people gather"; }
    ""
}
fn gather_duration(a) {
    switch a.target.kind {
        "berry_bush" => 2000,
        "reeds" => 2500,
        "tree" => 4000,
        "boulder" => 5000,
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
fn wait_duration(a) { if a.qty > 0 && a.qty <= 60 { a.qty * 1000 } else { 3000 } }

// ---- building and crafting --------------------------------------------

fn cost(kind) {
    switch kind {
        "campfire" => #{ wood: 3 },
        "shelter" => #{ wood: 6, fiber: 3 },
        "storage" => #{ wood: 4 },
        "spear" => #{ wood: 2, stone: 1 },
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
    if a.actor.kind == "person" && a.actor.age < 3.0 { return "too young to build"; }
    if a.item != "campfire" && a.item != "shelter" && a.item != "storage" { return `cannot build ${a.item}`; }
    if a.actor.terrain == "water" || a.actor.terrain == "rock" { return "cannot build here"; }
    if a.item == "campfire" && a.actor.near_fire { return "a campfire already burns right here"; }
    if a.item == "shelter" && a.actor.near_shelter { return "there is already a shelter right here"; }
    afford(a, a.item)
}
fn build_duration(a) { switch a.item { "campfire" => 6000, "shelter" => 20000, _ => 10000 } }
fn build_done(a) {
    let fx = pay(a.item);
    fx.push(#{ op: "build", kind: a.item });
    fx.push(#{ op: "vitals", energy: -4.0 });
    fx
}

fn craft_check(a) {
    if a.actor.age < 3.0 { return "too young to craft"; }
    if a.item != "spear" { return `cannot craft ${a.item}`; }
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
    if a.actor.kind == "person" && a.actor.age < 3.0 { return "too young to fight"; }
    if a.target.class != "creature" || !a.target.alive { return "nothing to attack"; }
    if a.target.id == a.actor.id { return "cannot attack yourself"; }
    ""
}
fn attack_duration(a) { switch a.actor.kind { "wolf" => 900, _ => 1100 } }
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

fn max_hp(kind) { switch kind { "deer" => 40.0, "wolf" => 55.0, _ => 100.0 } }

// Regrowth per minute for resource kinds.
fn regrow(kind) {
    switch kind {
        "berry_bush" => 1.2,
        "reeds" => 1.0,
        "tree" => 0.5,
        "boulder" => 0.2,
        "fishing_spot" => 1.4,
        _ => 0.0,
    }
}

// ---- life course --------------------------------------------------------

fn grown(a) { a.actor.age >= 3.0 }

fn conceive_check(a) {
    if a.actor.kind != "person" || !grown(a) { return "too young to start a family"; }
    if a.target.class != "creature" || a.target.kind != "person" || !a.target.alive { return "no partner"; }
    if a.target.id == a.actor.id { return "cannot do that alone"; }
    if a.actor.hunger > 60.0 { return "too hungry to think of a family"; }
    if !a.actor.near_shelter { return "a family needs a shelter nearby"; }
    ""
}
fn conceive_duration(a) { 3000 }
fn conceive_done(a) { [#{ op: "bond" }] }

// ---- signals (species vocabulary is checked by the engine) --------------

fn signal_duration(a) { 800 }
fn signal_done(a) { [#{ op: "signal" }] }
