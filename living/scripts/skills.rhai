// Living core skill and needs rules. Functions only; the authority calls them at
// action start (check, duration) and completion (done), and when need rates change.
// `a.actor`, `a.target`, `a.item`, `a.qty`, `a.night`, `a.hour` — see rules/src/script.rs.

// ---- world laws (read once per script revision; parameters for the engine) ----------

fn laws() {
    #{
        fire_warmth: 3.5, shelter_warmth: 2.5,
        gestation_days: 1.0, bond_window_s: 120.0,
        crowd: 6, danger_near: 8.0, danger_far: 12.0,
        repeat_failure_s: 120.0,
        road_speed: 1.4,
        // Steering: where bodies slow down and cut corners, and how often they look again
        // (how each creature turns and keeps apart is its `motion` law).
        slow_radius: 1.2, corner_radius: 0.9,
        steer_s: 2.0, crowd_hz: 3.0, chase_hz: 4.0, combat_hz: 8.0,
        // How often a body smells afresh; between reads it keeps what it last smelled.
        scent_hz: 1.0,
        input_hz: 30.0, input_burst: 15.0,
        // Grass regrowth per grassy tile per growing game hour (0.0015 a real minute on the
        // 12-minute day): about one grazer per 300 grassy tiles (it was one per 70, and the
        // wilds filled with deer).
        pasture_regen_per_h: 0.00075,
        // Someone with no other person within this many tiles is alone (predators dare more).
        alone_within: 6.0,
        // A body within this many radians of facing something already faces it.
        face_slack: 0.35,
        // A flight runs until it is this many tiles farther from the threat than it began.
        flee_clear: 9.0,
        // Seconds a played character stands with no connection of its person before the
        // world's minds take it over (it keeps living; the person takes it back on return).
        takeover_s: 30.0,
        // How long one `follow` lasts before the follower looks again (seconds), and how far
        // `read` with nothing named looks for a sign (metres).
        follow_s: 12.0, read_sign_m: 8.0,
        // Others of one's kind within this many metres are kin near (`a.actor.kin_near`).
        kin_near_m: 4.0,
        // How long a trade offer can be accepted and a request to join stands (seconds).
        trade_window_s: 180.0, join_window_s: 300.0,
        // Speech to no one in particular is for the only listener within this many metres.
        address_m: 6.0,
        // A creature in a player's sight stays seen until this far beyond it (metres); a chase
        // is lost beyond this share of the chaser's sight.
        keep_seen_m: 1.0, chase_lost_share: 1.4,
        // A body that comes into the world: its hunger and energy.
        spawn_hunger: 25.0, spawn_energy: 85.0,
        // Grazing each grassy or forest tile holds.
        pasture_per_tile: 0.02,
        // A crying infant makes its carers think about it (false: it is only heard). A world
        // sets this in its seed's `rules`, like any law here. Every person has a mind: no law
        // turns minds off (docs/SEEDED_LIVES.md, "Every person a mind").
        cry_prompts_carers: true,
        // A grown person longs for a child this many real minutes after its own birth or its
        // youngest child's (the most nurturing sooner, down to a sixth of it), and only while
        // carrying at least `longing_food` food (0: whatever it carries).
        longing_after_min: 20.0, longing_food: 0.0,
        // Sight that depends on facing (`senses(a).field`, docs/PERCEPTION.md). Off: one sees
        // the same distance all round, as before. On: full sight within `fov_focal_deg` of
        // where the body faces, `fov_side_share` of it out to `fov_side_deg`, and all round only
        // within `fov_near_m` (`fov_near_dark_m` in the dark); someone already seen stays seen
        // `fov_margin_deg` past an edge. A light on someone (`glow`) shows them only within the
        // field. Hearing stays all round.
        fov_on: false,
        fov_focal_deg: 70.0, fov_side_deg: 110.0, fov_side_share: 0.3333,
        fov_near_m: 3.0, fov_near_dark_m: 2.0, fov_margin_deg: 10.0,
        // What is heard but not seen (only while the field is on) is told by its distance:
        // near within `heard_near_m`, close within `heard_close_m`, far out to hearing; it
        // lingers `heard_linger_s` after it was last heard.
        heard_near_m: 5.0, heard_close_m: 15.0, heard_linger_s: 2.0,
        // A player's look (`human_face`): a change within `look_slack_deg` of the look held (or
        // of where the body stands facing) is nothing new; walking, the body turns toward the
        // look at most `look_walk_deg` off the way it is told to go (the walk bends with it).
        look_slack_deg: 10.0, look_walk_deg: 30.0,
    }
}

// ---- senses (a law per creature, on the hot path) -----------------------------------
// Distances are in tiles, and a tile is one metre. The engine asks `senses(a)` for a creature's
// state and keeps the answer for every creature in the same state: the key is only what the
// law reads (here, whether it is night and whether the creature carries a torch). A passive or
// a skill that changes how far someone sees or hears is a line here, at no cost per look, as
// long as `reach` below still bounds it.

// How far one sees in each light: by day, at night with a lit torch in the pack, at night.
fn sight_in(light) { switch light { "day" => 11.0, "torch" => 9.0, _ => 6.0 } }
// How far speech carries to the ear.
fn hearing_of_people() { 9.0 }
fn light_of(a) { if !a.night { "day" } else if inv(a, "torch") > 0 { "torch" } else { "night" } }

fn senses(a) {
    let s = #{ sight: sight_in(light_of(a)), hearing: hearing_of_people() };
    if law("fov_on") { s.field = sight_field(a); }
    s
}

// How the view narrows away from facing (the `fov_*` laws); all round within the near ring,
// less of it in the dark.
fn sight_field(a) {
    #{
        focal_deg: law("fov_focal_deg"), side_deg: law("fov_side_deg"), side_share: law("fov_side_share"),
        near_m: if light_of(a) == "night" { law("fov_near_dark_m") } else { law("fov_near_m") },
        margin_deg: law("fov_margin_deg"),
    }
}

// What a creature heard but not seen sounds like (the kind told for it; "creature" where one
// cannot tell).
fn heard_as(kind) { if kind == "person" || kind == "deer" || kind == "wolf" { kind } else { "creature" } }

// The field of view in words, when the world's law turns it on.
fn field_about() {
    if !law("fov_on") { return ""; }
    ` One sees that far only within about ${short(law("fov_focal_deg"))} degrees either side of the way one faces, a third as far out to ${short(law("fov_side_deg"))} degrees, and behind only within ${short(law("fov_near_m"))} m (${short(law("fov_near_dark_m"))} m in the dark): one hears what is behind one, and turns to see it. A light on someone shows them only where one is looking.`
}

// A number for descriptions: at most two decimals, a whole number without its ".0".
fn short(x) { let r = (x * 100.0).round() / 100.0; if r == r.floor() { `${r.to_int()}` } else { `${r}` } }

fn senses_law() {
    let night_most = if sight_in("torch") > sight_in("night") { sight_in("torch") } else { sight_in("night") };
    #{
        cadence: "hot",
        topic: "senses",
        // The farthest anyone sees by day and by night, and hears: the engine gathers onlookers
        // within these before testing each one's own senses, and holds every answer to them.
        reach: #{ day: sight_in("day"), night: night_most, hearing: hearing_of_people() },
        about: `How far a creature sees and hears, in metres (one tile is one metre). By day one sees ${short(sight_in("day"))} m; at night ${short(sight_in("night"))} m, or ${short(sight_in("torch"))} m carrying a torch. Rock, walls and shut gates block the line of sight. Speech carries ${short(hearing_of_people())} m.${field_about()}`,
    }
}

// ---- ways of speaking (read once per script revision; the speech primitive applies them) ----
// Each `<way>_speech()` is a way to say a line (docs/COMMUNICATION.md). Speech is not a skill: it
// never interrupts what the body is doing. The engine reads these maps when the script compiles
// and refuses a key it does not know, so a way cannot claim what the engine does not do.
//   about        what the way is, for minds (the world text) and players (the talk box).
//   label, order the word a client shows for it, and where it comes among the ways.
//   to           "optional" (the room, or one person) or "required" (one person).
//   words        who receives the words: `hearing` a share of each listener's own hearing,
//                or `within_m` metres (and never beyond the listener's hearing); `only_to:
//                true` gives them to the addressee alone.
//   noticed      who learns only that it was said, between whom: within `within_m`, those who
//                see the speaker (`seen`), as rows of `kind` reading `text` ({a} the speaker,
//                {b} the addressee as each one knows them).
//   said, said_to, heard, heard_to, heard_to_you   the words of the rows, before the line
//                itself (`: "…"` follows): {a} the speaker, {b} the addressee, {d} how far
//                the speaker is from the one who reads it (metres).
//   kind         the kind of the rows that carry the words ("speech").
//   animals      what an animal in range hears ("" nothing).
//   gap_s        seconds between two lines of this way (never under the 2 s speaking limit).
//   max_chars    longer lines are cut short.
//   needs        a technique of `know_how()` the speaker must know.
//   reach        the addressee must be within this many metres.
//   needs_sight  the addressee must be in sight.
//   introduces   a line with the speaker's own name tells it to those who receive the words.
//   names        a line to someone that holds their name tells it to those who receive the
//                words and see whom it was for (default: unless the words are for one ear).
//   salience     #{ addressed, overheard }.
// A way's refusals are its `<way>_check(a)`: "" accepts the line, anything else refuses it in
// those words. The reducer returns exactly them, and the game client, which compiles this
// script, runs the same check before it sends, so a player sees the same words either way.
// `a.target` is the addressee (class "none" for the room; one who is not there, absent or dead,
// is a creature not alive and very far), `a.text` the line, `a.qty` the milliseconds since the
// speaker's last line in this way (4000000000 if never); nothing else (the install refuses a
// check that reads another field, such as the hour, which a client could not give). Both call
// `living_rules::script::speech::check_way`. A way that requires an addressee, a
// reach, a technique or a gap must refuse a line that breaks it (the install tries). Only the
// engine's own refusals are not here: a way it does not know, and two lines within 2 s.
fn say_speech() {
    #{ label: "Say", order: 0, about: "Speak aloud. Everyone within earshot hears you, also when you speak to one person.",
       words: #{ hearing: 1.0 }, to: "optional", gap_s: 2.0, max_chars: 400 }
}
// How far a whisper goes, and how near one sees that someone whispered.
fn whisper_reach() { 1.5 }
fn whisper_noticed_within() { 6.0 }
fn whisper_check(a) {
    if a.target.class == "none" { return "a whisper needs someone to whisper to"; }
    if !a.target.alive || a.target.dist > whisper_reach() { return "too far to whisper: step closer"; }
    ""
}
fn whisper_speech() {
    #{ label: "Whisper", order: 1,
       about: `Whisper to someone beside you (within ${short(whisper_reach())} m). Only they hear the words; people within ${short(whisper_noticed_within())} m who see you may notice that you whispered to them, but not what.`,
       to: "required", reach: whisper_reach(), words: #{ within_m: whisper_reach(), only_to: true }, kind: "whisper",
       noticed: #{ within_m: whisper_noticed_within(), seen: true, kind: "whispered", text: "{a} whispers something to {b}.", salience: 0.3 },
       said: "You whispered", said_to: "You whispered to {b}", heard_to_you: "{a} whispers to you", gap_s: 2.0, max_chars: 400 }
}
// A call carries this many times a voice, to people and animals alike, and comes at most once
// every few seconds.
fn call_carry() { 2.5 }
fn call_gap_s() { 6.0 }
fn call_check(a) {
    if a.qty < (call_gap_s() * 1000.0).to_int() { return "too soon to call out again: wait a few seconds"; }
    ""
}
fn call_speech() {
    #{ label: "Call out", order: 2,
       about: `Call out over a distance: everyone within ${short(hearing_of_people() * call_carry())} m hears you, and animals too (a shout can startle deer or draw wolves). Short lines (80 characters), at most one every ${short(call_gap_s())} s.`,
       to: "optional", words: #{ hearing: call_carry() }, animals: "a person shouting",
       said: "You called out", said_to: "You called out to {b}", heard: "{a} calls out from about {d} m", heard_to: "{a} calls out to {b} from about {d} m", heard_to_you: "{a} calls out to you from about {d} m",
       gap_s: call_gap_s(), max_chars: 80 }
}

// ---- moving (a law per creature, on the hot path) -----------------------------------
// How a creature moves besides its walking pace (`move_speed`): its run, its flight and the
// pace it steps aside at, as shares of its walk; how fast it turns (radians a second) and how
// much of its speed it keeps in the sharpest turns; how far it keeps from other bodies
// (metres) and how strongly that bends its way; how far a wander may turn from the way it was
// heading (radians) and for how long after stopping it still keeps that way (seconds). Asked per creature at every steering step and
// kept per state, like senses: the shipped law reads nothing, so every creature shares it.
fn motion(a) {
    #{ run: 1.5, flee: 1.15, aside: 0.8, turn_rate: 6.0, turn_slow: 0.4, separation: 0.8, separation_weight: 0.9, wander_turn: 1.2, wander_keep_s: 60.0 }
}

// A grown, rested body of a kind at its normal pace (for descriptions).
fn walk_of(kind) { try { return move_speed(#{ actor: #{ kind: kind, stage: "adult", speed: 1.0, energy: 100.0 } }); } catch { } 0.0 }

fn motion_law() {
    let m = motion(#{ actor: #{ kind: "person", stage: "adult" }, night: false });
    #{
        cadence: "hot",
        topic: "moving",
        covers: ["move_speed"],
        about: `How creatures move, in metres a second. Grown people walk ${short(walk_of("person"))}, wolves ${short(walk_of("wolf"))}, deer ${short(walk_of("deer"))}; the young, the old and the exhausted are slower. Running is ${short(m.run)} times one's walk and a flight ${short(m.flee)} times; stepping aside is ${short(m.aside)} times. Bodies turn at about ${short(m.turn_rate)} radians a second, slowing in sharp turns, and keep about ${short(m.separation)} m from others when they can. A stroll (wander) keeps roughly the way it was going, turning at most about ${short(m.wander_turn)} radians, even after a stop of up to ${short(m.wander_keep_s)} s.`,
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

// Every kind of structure, in order, with what it does for those near it (read once when the
// script compiles; docs/WORLD_RULES.md, "Goods, recipes and fuel"):
//   warms   a fire that needs no feeding: near it counts as near a fire (within fire_warmth; a
//           building that warms, a house with its hearth, within shelter_warmth)
//   roof    a roof: near it counts as sheltered (within shelter_warmth)
//   lights  how far it lights the dark (metres: lamplight, `a.actor.lit`); a kind that burns
//           lights only while lit, within the larger of this and its `burns.light`
//   burns   a fire that eats fuel: #{ fuel: the item trait it burns (its number is the units one
//           item gives), rate: units a game hour while lit, warmth and light: metres while lit,
//           holds: the most units it takes }. It is lit only while it holds fuel, warms and
//           lights only while lit, goes out when its fuel is spent and is lit again by feeding
//           it (feed). Its fuel is not an item to take back.
// Other traits are the rules' own data.
fn structures() {
    [
        #{ name: "campfire", warms: true },
        #{ name: "shelter", roof: true },
        #{ name: "storage" }, #{ name: "remains" }, #{ name: "sign" }, #{ name: "bush_patch" },
        #{ name: "house", warms: true, roof: true }, #{ name: "gate" }, #{ name: "trap" },
        #{ name: "hall", warms: true, roof: true }, #{ name: "workshop", roof: true }, #{ name: "market" },
        #{ name: "inn", warms: true, roof: true },
        // Gives no light in the shipped world; a world's laws say what it burns and lights.
        #{ name: "lamp" },
    ]
}
fn structure_trait(kind, t) { let k = entry_of("structures", kind); if k == () { () } else { k[t] } }
// A fire: one that needs no feeding (a campfire), or one that burns fuel (a hearth).
fn fire_kind(kind) { let k = entry_of("structures", kind); k != () && (k.burns != () || (k.warms == true && k.roof != true)) }
// The fire in reach burns now (a campfire always does; a hearth while it holds fuel).
fn burning(a) { a.target.class == "structure" && fire_kind(a.target.kind) && (burns_of(a.target.kind) == () || a.target.lit) }

// Share of the spoiling rate for food kept in a structure of a kind (a storage, remains): kept
// food lasts three times longer.
fn kept_spoil(kind) { 1.0 / 3.0 }
// How many berries a bush planted by someone grows to.
fn planted_max(kind) { 5.0 }
// What someone of an occupation knows from the start (seeded people; their seed may add more).
fn occupation_knows(occ) {
    switch occ {
        "fisher" => ["spear", "cooking", "fishing"],
        "farmer" => ["planting", "storage"],
        "builder" => ["shelter", "storage", "carpentry", "masonry"],
        "mason" => ["masonry", "toolmaking"],
        "carpenter" => ["shelter", "carpentry", "toolmaking"],
        "guard" => ["spear", "torch"],
        "hunter" => ["spear", "cloak", "torch", "trapping"],
        "cook" => ["cooking", "storage"],
        "scribe" => ["writing"],
        "healer" => ["cooking", "planting", "medicine"],
        "trader" => ["writing", "storage", "basketry"],
        _ => [],
    }
}

// Taking from a store is theft when it is someone else's, they are not of your people and you
// are not their guest: the owner, if it sees, is roused, and onlookers see you take it.
fn theft(a) {
    let o = a.target.owner;
    o != 0 && o != a.actor.id && !(a.actor.community != 0 && a.actor.community == a.target.community) && !a.target.hosts
}

// ---- what things and creatures are (read once when the script compiles) -------------------
// Every item of the world, in order, with its traits. Rules read traits instead of naming items:
//   cooks_to, smokes_to   what cooking or smoking it at a fire makes (`cook`, `smoke`)
//   fuel                  units of fuel one gives a fire that burns `fuel` (`feed`)
// What a client shows of it (data only: no rule reads them; docs/WORLD_RULES.md lists the ids):
//   icon                  a short stable id the client draws it by
//   label                 its name for players, lower case as in a sentence
//   group                 where a pack or a recipe grid sorts it: food, fuel, material, tool,
//                         weapon, garment, glass, money (`living_rules::ui` ITEM_ICONS and
//                         ITEM_GROUPS hold the names)
// A recipe (`recipes()`) may ask for an item by name or for anything with a trait; a world adds
// traits of its own (`bakes_to`, `alkali`, `oil`) and the recipes and fires that read them.
fn items() {
    [
        #{ name: "berries", icon: "berries", label: "berries", group: "food" },
        #{ name: "fish", cooks_to: "cooked_fish", smokes_to: "smoked_fish", icon: "fish", label: "fish", group: "food" },
        #{ name: "meat", cooks_to: "cooked_meat", smokes_to: "smoked_meat", icon: "meat", label: "meat", group: "food" },
        #{ name: "cooked_fish", icon: "cooked_fish", label: "cooked fish", group: "food" },
        #{ name: "cooked_meat", icon: "cooked_meat", label: "cooked meat", group: "food" },
        #{ name: "wood", fuel: 1.0, icon: "wood", label: "wood", group: "material" },
        #{ name: "stone", icon: "stone", label: "stone", group: "material" },
        #{ name: "fiber", icon: "fiber", label: "fiber", group: "material" },
        #{ name: "spear", icon: "spear", label: "spear", group: "weapon" },
        #{ name: "hide", icon: "hide", label: "hide", group: "material" },
        #{ name: "cloak", icon: "cloak", label: "cloak", group: "garment" },
        #{ name: "torch", icon: "torch", label: "torch", group: "tool" },
        #{ name: "tablet", icon: "tablet", label: "tablet", group: "tool" },
        #{ name: "clay", icon: "clay", label: "clay", group: "material" },
        #{ name: "axe", icon: "axe", label: "axe", group: "tool" },
        #{ name: "pick", icon: "pick", label: "pick", group: "tool" },
        #{ name: "smoked_fish", icon: "smoked_fish", label: "smoked fish", group: "food" },
        #{ name: "smoked_meat", icon: "smoked_meat", label: "smoked meat", group: "food" },
        #{ name: "net", icon: "net", label: "net", group: "tool" },
        #{ name: "basket", icon: "basket", label: "basket", group: "tool" },
        #{ name: "bow", icon: "bow", label: "bow", group: "weapon" },
        #{ name: "arrow", icon: "arrow", label: "arrow", group: "weapon" },
        #{ name: "salve", icon: "salve", label: "salve", group: "tool" },
        #{ name: "leather", icon: "leather", label: "leather", group: "material" },
        #{ name: "armor", icon: "armor", label: "armor", group: "garment" },
        // Money where a settlement uses it: stamped clay tallies, worth what people agree.
        #{ name: "mark", icon: "mark", label: "mark", group: "money" },
    ]
}
fn item_trait(item, t) { let i = entry_of("items", item); if i == () { () } else { i[t] } }
fn items_with(t) { having("items", t) }

// Every kind of creature, with what the rules ask of a kind (a kind the table does not name is
// taken as the first):
//   grazes                      eats grass where it stands (`graze`)
//   max_hp                      health when grown and whole
//   lunge                       how far a blow still carries past the attack's reach (metres)
//   blow                        the damage of its bare attack, before strength and skill
//   dodge_dist, dodge_speed     its dodge: a dash of so many metres at so many metres a second
//   carcass                     what its body leaves in its remains (items and amounts)
//   remains_h                   game hours its remains lie before they are gone
fn kinds() {
    [
        #{ name: "person", max_hp: 100.0, lunge: 0.6, blow: 7.0, dodge_dist: 2.6, dodge_speed: 5.2, carcass: #{}, remains_h: 120.0 },
        #{ name: "deer", grazes: true, max_hp: 40.0, lunge: 0.6, blow: 4.0, dodge_dist: 2.8, dodge_speed: 8.0, carcass: #{ meat: 5, hide: 1 }, remains_h: 60.0 },
        #{ name: "wolf", max_hp: 55.0, lunge: 1.8, blow: 13.0, dodge_dist: 2.4, dodge_speed: 8.0, carcass: #{ meat: 2, hide: 1 }, remains_h: 60.0 },
    ]
}
fn kind_of(kind) { let all = kinds(); for k in all { if k.name == kind { return k; } } all[0] }
// "a, b or c"
fn or_list(parts) {
    let out = "";
    for i in 0..parts.len() { if i > 0 { out += if i == parts.len() - 1 { " or " } else { ", " }; } out += parts[i]; }
    out
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
// Share of a food that spoils in a game hour (the engine turns it into real time for the
// world's day; on the 12-minute day a game hour is half a real minute): raw meat and fish within
// about a day, berries in a few days, cooked food more slowly. A storage keeps food three times
// longer.
fn spoil_per_h(item) {
    switch item {
        "meat" => 0.025,
        "fish" => 0.025,
        "berries" => 0.01,
        "cooked_meat" => 0.006,
        "cooked_fish" => 0.006,
        // Smoked food keeps for weeks: something to carry to another town.
        "smoked_meat" => 0.001,
        "smoked_fish" => 0.001,
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

// A cold that hurts (a floor may make every cold one): a winter night, or a night in the rain.
fn freezing(a) { a.season == "winter" || wet(a) }

// Survival is secondary (docs/SEEDED_LIVES.md, "Survival made secondary"): a person feels
// hungry from 50, about 42 real minutes (3.5 game days on the 12-minute day) before starving at 100.
fn body_state(a) {
    let fraction = a.actor.hp / (max_hp(a.actor.kind) * a.actor.vitality);
    #{ cold: cold(a), hungry: a.actor.hunger > 50.0, starving: a.actor.hunger >= 100.0,
       wound: if fraction < 0.15 { "barely alive" } else if fraction < 0.35 { "badly wounded" }
              else if fraction < 0.6 || a.actor.hurt_ago < 5000 { "hurt" } else { "" } }
}

// Need rates per game hour for a body's state (`per: "hour"`): the engine turns them into real
// time for the world's day length (rules/src/script.rs `NeedLaw`), so a world with a longer day
// keeps the same balance per game day. The engine asks this when the state changes and keeps the
// answer for every body in the same state; it then finishes the rates for each body's own
// hunger, energy and genes with the numbers given here:
//   hunger, energy            the state's rates (energy before the tiring gene)
//   starving_at, starving_hp  at or above this hunger, health changes by starving_hp
//   fed_below, rested_above   otherwise, below this hunger and above this energy, health
//   healing_hp                changes by healing_hp, times `healing` (age)
//   spent_at, spent_hp        at or below this energy, health changes by spent_hp as well
//   tiring_gene               a falling energy rate is divided by this gene
//   healing_gene              a rising health rate is multiplied by this gene
//   wet_energy, cold_hp       exposure, added last
//
// Targets for people on the 12-minute day (the island and the labs; docs/TRIALS.md "Fast
// iterations" 11): every person rate below is scaled by `person_pace`, so a person's hunger rises
// 0.6 a game hour awake (14.4 a game day; 1.2 a real minute there): a meal brought down to about
// 5 is wanted again at about 25 every 33 game hours (16–17 real minutes); it feels hungry at 50
// and starves at 100 about 83 game hours (42 minutes) later; starving takes about 167 game hours
// (seven game days) to kill a healthy body. Energy, rest, sleep, healing and exposure are scaled
// alike, so a person spends the same share of its time sleeping. An ordinary night outside is
// uncomfortable (tiring), not harmful; only winter nights and nights in the rain hurt without a
// fire, shelter or a warm cloak. Animals keep their own rates (the ecology is tuned on them).
// These numbers are the per-real-minute ones the 12-minute day had, halved (its game hour is half
// a real minute), so the island's rates in real time are what they were. `person_pace` was set
// to pace people's needs to real time on that day; it is now a share of the game-time rates, so
// a world with another day length sets its people's rates for its own day (a floor overlay).
fn person_pace(x) { 0.3 }
fn rates(a) {
    // A predator feeds big and rarely: a wolf lasts about two game hours on a deer.
    let hunger = switch a.actor.kind { "deer" => 3.0, "wolf" => 0.75, _ => 2.0 };
    let energy = -1.5;
    let act = a.actor.activity;
    if act == "sleep" {
        energy = if a.actor.near_shelter { 13.0 } else { 8.0 };
        hunger *= 0.5;
    } else if act == "rest" {
        energy = 3.0;
    } else if act == "block" {
        energy = -6.0;
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
    // Asked once each: a law called with `a` gets its own copy of the whole context, so asking
    // `cold(a)` three times cost three copies (the fuel budget, docs/LIVING_CORE.md).
    let is_cold = cold(a);
    let is_wet = wet(a);
    let r = #{
        per: "hour",
        hunger: hunger, energy: energy,
        // Starving hurts; fed and rested, a body heals; with no energy left, it suffers.
        starving_at: 100.0, starving_hp: -2.0,
        fed_below: 70.0, rested_above: 15.0, healing_hp: 1.5, healing: healing,
        spent_at: 0.0, spent_hp: -1.0,
        // Inborn endurance slows tiring; vitality speeds healing; a big appetite makes one
        // hungry sooner; hardiness divides what cold and wet weather take.
        tiring_gene: "endurance", healing_gene: "vitality", appetite_gene: "appetite", hardiness_gene: "hardiness",
        // Exposure tires: rain soaks people out from under a roof (a cloak keeps some of it
        // off), and a cold night without a fire, shelter or warm cloak is uncomfortable.
        wet_energy: (if is_wet { if inv(a, "cloak") > 0 { -0.5 } else { -1.25 } } else { 0.0 })
            + (if is_cold { -0.75 } else { 0.0 }),
        // A cold night hurts only in winter or in the rain (a storm night).
        cold_hp: if is_cold && freezing(a) { if a.season == "winter" { -1.5 } else { -0.75 } } else { 0.0 },
    };
    if a.actor.kind == "person" {
        let k = person_pace(0);
        for f in ["hunger", "energy", "starving_hp", "healing_hp", "spent_hp", "wet_energy", "cold_hp"] { r[f] = r[f] * k; }
    }
    r
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
        _ => { let r = entry_of("resources", a.target.kind); if r == () || r.gather_ms == () { 3000 } else { r.gather_ms } },
    }
}
// Every kind of resource, in order (read once when the script compiles):
//   yields      what one gathering gives
//   regrow_per_h  units it regrows a game hour of growing time, up to its max
//   max         units a node of it holds when full
//   ground      the ground a settlement's promised nodes of it are placed on (`resources` in a
//               town of the seed), and by_water: only beside water
//   gather_ms   how long one gathering takes without a tool (`gather_duration`)
fn resources() {
    [
        #{ name: "berry_bush", yields: "berries", regrow_per_h: 0.6, max: 5.0, ground: ["grass"], gather_ms: 2000 },
        #{ name: "tree", yields: "wood", regrow_per_h: 0.25, max: 8.0, ground: ["forest", "grass"], gather_ms: 4000 },
        #{ name: "boulder", yields: "stone", regrow_per_h: 0.1, max: 6.0, ground: ["grass", "dirt"], gather_ms: 5000 },
        #{ name: "reeds", yields: "fiber", regrow_per_h: 0.5, max: 4.0, ground: ["sand", "grass"], by_water: true, gather_ms: 2500 },
        #{ name: "fishing_spot", yields: "fish", regrow_per_h: 0.7, max: 5.0, ground: ["sand", "grass"], by_water: true, gather_ms: 6500 },
        #{ name: "clay_bank", yields: "clay", regrow_per_h: 0.3, max: 6.0, ground: ["grass"], by_water: true, gather_ms: 3000 },
    ]
}
// What one gathering at each resource yields.
fn yield_of(kind) { let r = entry_of("resources", kind); if r == () || r.yields == () { "" } else { r.yields } }
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
// A meal: up to `qty` (default 1) of the item, as many as bring hunger down to about 5.
fn meal(a) {
    let n = amount(a);
    let have = inv(a, a.item);
    if n > have { n = have; }
    let want = ((a.actor.hunger - 5.0) / nutrition(a.item)).ceiling().to_int();
    if want < 1 { want = 1; }
    if n > want { n = want; }
    n
}
fn eat_duration(a) { 1500 * meal(a) }
fn eat_done(a) {
    let n = meal(a);
    [#{ op: "remove", item: a.item, qty: n }, #{ op: "vitals", hunger: -nutrition(a.item) * n, hp: 1.0 * n }]
}

fn cook_check(a) {
    if !knows(a, "cooking") { return "you don't know how to cook" + learn_how("cooking"); }
    if a.target.kind != "campfire" && !(a.target.class == "structure" && structure_trait(a.target.kind, "burns") != ()) { return "cooking needs a campfire"; }
    if !burning(a) { return `the ${a.target.kind} is out: feed it first`; }
    if item_trait(a.item, "cooks_to") == () { return `only raw ${or_list(items_with("cooks_to"))} can be cooked`; }
    if inv(a, a.item) < 1 { return `no ${a.item} in your pack (${a.item}: ${source_of(a.item)})`; }
    ""
}
fn cook_duration(a) { 4000 }
fn cook_done(a) {
    [#{ op: "remove", item: a.item, qty: 1 }, #{ op: "add", item: item_trait(a.item, "cooks_to"), qty: 1 }]
}

fn smoke_check(a) {
    if !knows(a, "smoking") { return "you don't know how to smoke food" + learn_how("smoking"); }
    if a.target.kind != "campfire" && !(a.target.class == "structure" && structure_trait(a.target.kind, "burns") != ()) { return "smoking needs a campfire"; }
    if !burning(a) { return `the ${a.target.kind} is out: feed it first`; }
    if item_trait(a.item, "smokes_to") == () { return `only raw ${or_list(items_with("smokes_to"))} can be smoked`; }
    if inv(a, a.item) < 1 { return `no ${a.item} in your pack (${a.item}: ${source_of(a.item)})`; }
    ""
}
fn smoke_duration(a) { 10000 }
fn smoke_done(a) {
    [#{ op: "remove", item: a.item, qty: 1 }, #{ op: "add", item: item_trait(a.item, "smokes_to"), qty: 1 }]
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
    if kind_of(a.actor.kind).grazes != true { return "only grazing animals graze"; }
    if a.actor.terrain != "grass" && a.actor.terrain != "forest" { return "no grass here"; }
    if a.actor.pasture < 1.0 { return "the grass here is grazed bare"; }
    ""
}
fn graze_duration(a) { 4000 }
// Each grazing eats a share of the chunk's grass (see pasture); bare ground feeds nothing.
fn graze_done(a) { [#{ op: "vitals", hunger: -14.0 }, #{ op: "graze" }] }

// ---- rest ---------------------------------------------------------------

// How long one sleep lasts: until rested at a sleeper's unpaced rate a game hour (13 beside a
// shelter, 8 without), at least 5 s and at most 150 s of real time; a sleeper not yet rested
// sleeps again.
fn sleep_duration(a) {
    let rate = if a.actor.near_shelter { 13.0 } else { 8.0 };
    let need = 100.0 - a.actor.energy;
    let ms = need / rate * hour_ms();
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

// A trap catches small game over time: one meat about every 8 game hours (4 real minutes on the
// 12-minute day), holding at most 3.
fn trap_every_h(x) { 8.0 }
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

// ---- fires and recipes (docs/WORLD_RULES.md, "Goods, recipes and fuel") -----------------
// A fire that burns fuel (a structure whose kind `burns`) is fed from the pack: each item worth
// its fuel trait in units. It burns them at its rate while lit and goes out when they are
// spent; feeding an out fire lights it again, which takes knowing fire. What a fire burns is
// whatever has its fuel trait, not a list.

fn burns_of(kind) { structure_trait(kind, "burns") }
// The item fed: the one named, or for "fuel" the first in the pack that burns here.
fn fuel_item(a, b) {
    if a.item != "fuel" { return a.item; }
    for k in having("items", b.fuel) { if inv(a, k) > 0 { return k; } }
    ""
}
fn feed_check(a) {
    if a.target.class != "structure" { return "feed a fire beside you that burns fuel"; }
    let b = burns_of(a.target.kind);
    if b == () { return `the ${a.target.kind} burns no fuel`; }
    let item = fuel_item(a, b);
    if item == "" { return `no fuel for the ${a.target.kind} in your pack (it burns ${or_list(having("items", b.fuel))})`; }
    let worth = item_trait(item, b.fuel);
    if worth == () { return `${item} is not fuel for the ${a.target.kind} (it burns ${or_list(having("items", b.fuel))})`; }
    if inv(a, item) < amount(a) { return `not enough ${item} (${item}: ${source_of(item)})`; }
    if b.holds != () && a.target.fuel + worth * amount(a) > b.holds + 0.001 { return `the ${a.target.kind} holds at most ${short(b.holds)} units of fuel; it has ${short(a.target.fuel)}`; }
    if !a.target.lit && !knows(a, "fire") { return `the ${a.target.kind} is out, and you don't know how to light a fire` + learn_how("fire"); }
    ""
}
fn feed_duration(a) { 1500 }
fn feed_done(a) { [#{ op: "fuel", item: fuel_item(a, burns_of(a.target.kind)), qty: amount(a) }] }

// What a world can make at its workplaces (read once when the script compiles). Each recipe:
//   gives, makes   the item made (the recipe's name by default) and how many (1)
//   takes          what it uses from the pack: #{ name or trait: qty }; a name is that item,
//                  a trait is anything carrying it (`alkali: 1` takes ash, or any other alkali)
//   turns          instead of gives and takes: an item trait naming what an item becomes
//                  (`smokes_to`): the item made is that trait's value, and one of the item is used
//   at             the structure kind it is made at, or "fire" for any fire (none: anywhere)
//   lit            the fire must be burning
//   fuel           units of fuel the heat takes from the fire it is made at (a fire that needs no
//                  feeding gives its heat for nothing)
//   knows          the technique it needs;  ms  how long it takes (8000)
//   icon, label    how it looks in a client, over its product item's (`recipe_look`; data only)
// The shipped world has none: a world adds them with the goods they read.
fn recipes() { [] }

fn gives_of(r) { if r.gives == () { r.name } else { r.gives } }
// How an item looks in a client: its `icon`, `label` and `group` (an item without them: its name
// as the icon and, with spaces, as the label; no group).
fn item_look(item) {
    let i = entry_of("items", item);
    if i == () { i = #{}; }
    let label = item;
    label.replace("_", " ");
    #{ icon: if i.icon == () { item } else { i.icon }, label: if i.label == () { label } else { i.label }, group: if i.group == () { "" } else { i.group } }
}
// How what a recipe makes looks in a recipe grid: its product item's look, with the recipe's own
// `icon` and `label` over it where the recipe sets them (data only; `make` does not read them).
fn recipe_look(product) {
    let look = item_look(product);
    let m = recipe_for(product);
    if m != () {
        if m.r.icon != () { look.icon = m.r.icon; }
        if m.r.label != () { look.label = m.r.label; }
    }
    look
}
// The recipe that makes an item, and the item it turns (for a recipe that `turns`).
fn recipe_for(product) {
    for n in names_of("recipes") {
        let r = entry_of("recipes", n);
        if r.turns == () {
            if gives_of(r) == product { return #{ r: r, input: () }; }
        } else {
            for i in having("items", r.turns) { if item_trait(i, r.turns) == product { return #{ r: r, input: i }; } }
        }
    }
    ()
}
fn products() {
    let out = [];
    for n in names_of("recipes") {
        let r = entry_of("recipes", n);
        if r.turns == () { out.push(gives_of(r)); } else { for i in having("items", r.turns) { out.push(item_trait(i, r.turns)); } }
    }
    out
}
// What the pack holds of a recipe's input: the item of that name, or everything with that trait.
fn holding(a, k) {
    if entry_of("items", k) != () { return inv(a, k); }
    let n = 0;
    for i in having("items", k) { n += inv(a, i); }
    n
}
fn takes_of(m) { let t = m.r.takes; if m.input != () { t = #{}; t[m.input] = 1; } else if t == () { t = #{}; } t }
fn make_check(a) {
    if a.actor.kind != "person" || young(a) { return "you cannot make things"; }
    let m = recipe_for(a.item);
    if m == () { return if products().len() == 0 { "nothing is made here" } else { `no one makes ${a.item} here (what is made: ${or_list(products())})` }; }
    let r = m.r;
    if r.knows != () && !knows(a, r.knows) { return `you don't know how to make ${a.item}` + learn_how(r.knows); }
    if r.at != () {
        let here = a.target.class == "structure" && (a.target.kind == r.at || (r.at == "fire" && fire_kind(a.target.kind)));
        if !here { return if r.at == "fire" { `${a.item} is made at a fire` } else { `${a.item} is made at a ${r.at}` }; }
        if (r.lit == true || r.fuel != ()) && !burning(a) { return `the ${a.target.kind} is out: feed it first`; }
        if r.fuel != () && burns_of(a.target.kind) != () && a.target.fuel + 0.001 < r.fuel { return `the ${a.target.kind} has too little fuel left for it (it takes ${short(r.fuel)}, it has ${short(a.target.fuel)}): feed it first`; }
    }
    let t = takes_of(m);
    for k in t.keys() {
        if holding(a, k) < t[k] { return `${a.item} takes ${t[k]} ${k} (${k}: ${source_of(k)})`; }
    }
    ""
}
fn make_duration(a) { let m = recipe_for(a.item); if m == () || m.r.ms == () { 8000 } else { m.r.ms } }
fn make_done(a) {
    let m = recipe_for(a.item);
    let fx = [];
    let t = takes_of(m);
    for k in t.keys() {
        let left = t[k];
        if entry_of("items", k) != () { fx.push(#{ op: "remove", item: k, qty: left }); continue; }
        for i in having("items", k) {
            if left <= 0 { break; }
            let n = inv(a, i);
            if n > left { n = left; }
            if n > 0 { fx.push(#{ op: "remove", item: i, qty: n }); left -= n; }
        }
    }
    if m.r.fuel != () && a.target.class == "structure" && burns_of(a.target.kind) != () { fx.push(#{ op: "burn", units: m.r.fuel }); }
    fx.push(#{ op: "add", item: a.item, qty: if m.r.makes == () { 1 } else { m.r.makes } });
    fx.push(#{ op: "vitals", energy: -1.0 });
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
fn lunge(kind) { kind_of(kind).lunge }
fn attack_done(a) {
    let dmg = if a.actor.kind == "person" && inv(a, "spear") > 0 { 18.0 } else { kind_of(a.actor.kind).blow };
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

// What a creature's body leaves in its remains when it dies, however it died, beside what it
// carried (its kind's `carcass`), and how long the remains lie in game hours (its kind's
// `remains_h`).
fn carcass(kind) { let c = kind_of(kind).carcass; if c == () { #{} } else { c } }
fn remains_h(kind) { kind_of(kind).remains_h }

fn max_hp(kind) { kind_of(kind).max_hp }

// Regrowth a game hour of growing time for resource kinds (their `regrow_per_h`).
fn regrow_per_h(kind) { let r = entry_of("resources", kind); if r == () || r.regrow_per_h == () { 0.0 } else { r.regrow_per_h } }

// ---- life course --------------------------------------------------------

fn young(a) { a.actor.stage == "infant" || a.actor.stage == "child" }
fn grown(a) { !young(a) }

// Laws of starting a family. The shipped values ask nothing beyond adulthood, a willing
// partner and not being hungry; a world may ask more of a body (docs/TRIALS.md, "Births that
// keep a settlement's numbers"):
//   conceive_food  food the two partners carry between them, at least (0: none asked)
//   conceive_roof  whether one must stand under a roof (a shelter or a house) to start a family
fn conceive_food() { 0 }
fn conceive_roof() { false }
fn food_carried(inv) {
    let n = 0;
    for k in inv.keys() { if nutrition(k) > 0.0 { n += inv[k]; } }
    n
}
fn conceive_more() {
    let more = "";
    if conceive_roof() { more += ", under a roof"; }
    if conceive_food() > 0 { more += `, with at least ${conceive_food()} food carried between you`; }
    more
}

fn conceive_check(a) {
    if a.actor.stage != "adult" { return "not of an age to start a family"; }
    if a.target.class != "creature" || a.target.kind != a.actor.kind || !a.target.alive { return "no partner"; }
    if a.target.id == a.actor.id { return "cannot do that alone"; }
    if a.target.stage != "adult" { return "they are not of an age for it"; }
    if a.actor.hunger > 60.0 { return "too hungry to think of a family"; }
    if conceive_roof() && !a.actor.near_shelter { return "not under a roof: a family is started under a shelter or in a house"; }
    if conceive_food() > 0 {
        let food = food_carried(a.actor.inv) + food_carried(a.target.inv);
        if food < conceive_food() { return `not enough food put by for a child: the two of you carry ${food}, a family needs ${conceive_food()}`; }
    }
    ""
}
fn conceive_duration(a) { 3000 }
fn conceive_done(a) { [#{ op: "bond" }] }

// ---- signals (species vocabulary is checked by the engine) --------------

fn signal_duration(a) { 800 }
fn signal_done(a) { [#{ op: "signal" }] }

// ---- know-how -----------------------------------------------------------------

// Every technique there is, in order (read once when the script compiles): what one is told it
// is (`help`), what must be known first (`requires`), and the few words the minds' world text
// gives it (`brief`; none: its name alone, `know_how_law`). What it lets one do is the skills'.
fn know_how() {
    [
        #{ name: "fire", help: "build a campfire (3 wood)", brief: "campfire" },
        #{ name: "cooking", help: "cook raw fish or meat at a campfire", requires: ["fire"] },
        #{ name: "spear", help: "craft a spear (2 wood, 1 stone)" },
        #{ name: "shelter", help: "build a shelter (6 wood, 3 fiber)" },
        #{ name: "storage", help: "build a storage (4 wood)" },
        #{ name: "cloak", help: "craft a warm cloak (2 hide, 1 fiber) that keeps the night cold off", brief: "2 hides from hunted deer + 1 fiber; keeps you warm at night" },
        #{ name: "torch", help: "craft a torch (1 wood, 1 fiber) that lights the night", brief: "lights the night, you see farther", requires: ["fire"] },
        #{ name: "planting", help: "plant berries to grow new berry bushes", brief: "grow new berry bushes" },
        #{ name: "writing", help: "write and read tablets and signs", brief: "write and read tablets and signs" },
        #{ name: "masonry", help: "build walls (2 stone per tile)", brief: "walls" },
        #{ name: "carpentry", help: "build houses (6 wood, 4 clay, 2 stone; warm like a shelter and a fire) and gates (4 wood)", brief: "houses and gates; needs shelter", requires: ["shelter"] },
        #{ name: "fishing", help: "craft a net (3 fiber) that brings in two fish at a time" },
        #{ name: "smoking", help: "smoke raw fish or meat at a campfire so it keeps for weeks", requires: ["fire"] },
        #{ name: "basketry", help: "craft a basket (2 fiber, 1 wood) to carry 20 more" },
        #{ name: "archery", help: "craft a bow (2 wood, 1 fiber) and arrows (1 wood, 1 stone for 3) and shoot from afar" },
        #{ name: "tanning", help: "craft leather from hide, and armor (3 leather, 1 fiber) that softens blows" },
        #{ name: "medicine", help: "craft a salve (2 berries, 1 fiber); tending with a salve heals far more" },
        #{ name: "trapping", help: "build a trap (2 wood, 2 fiber) that catches small game over time" },
        #{ name: "bridging", help: "build a bridge (4 wood, 2 stone) over water beside you", requires: ["carpentry"] },
        #{ name: "fire_bolt", help: "hurl a bolt of fire (firebolt) that burns the first creature in its path" },
        #{ name: "wound_tending", help: "close wounds quickly with your hands (the heal skill), your own or an ally's, even in a fight; not mending things" },
        #{ name: "toolmaking", help: "craft an axe (2 wood, 1 stone; cuts wood twice as fast) or a pick (2 wood, 2 stone; breaks stone twice as fast)", brief: "axe, pick" },
    ]
}
fn requires(t) { let k = entry_of("know_how", t); if k == () || k.requires == () { [] } else { k.requires } }

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

// Every technique there is: the world's know-how table (its own entries included, such as a
// seed's glassmaking), not only what experimenting with a material can reveal (`discoveries`):
// fire_bolt and wound_tending are learned only from someone or from writing.
fn techniques() { names_of("know_how") }
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
fn combat_recover(skill) { switch skill { "strike" => 250, "bowshot" => 250, "firebolt" => 350, "heal" => 300, "dodge" => 200, "jump" => 150, "attack" => 300, "shoot" => 300, "throw" => 400, _ => 0 } }
fn combat_cooldown(skill) { switch skill { "strike" => 650, "bowshot" => 900, "firebolt" => 4000, "heal" => 8000, "dodge" => 900, "block" => 400, "jump" => 600, _ => 0 } }
fn combat_cost(skill) { switch skill { "strike" => 2.0, "bowshot" => 1.5, "firebolt" => 12.0, "heal" => 15.0, "dodge" => 4.0, "block" => 1.0, "jump" => 2.0, _ => 0.0 } }
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
// A jump is a dash that does not evade: blows and missiles still land while you are in the air.
fn jump_combat() { #{ aim: "dash", timed: true, reflex: true, real_time: true, evades: false } }
fn attack_combat() { #{ aim: "creature", timed: true, rooted: true, hostile: true, reflex: true, real_time: true, melee: true, closes_in: true, force: true, dares: true } }
fn shoot_combat() { #{ aim: "creature", timed: true, rooted: true, hostile: true, reflex: true, real_time: true, force: true } }
fn throw_combat() { #{ aim: "creature", timed: true, hostile: true, reflex: true, real_time: true, force: true } }
fn threaten_combat() { #{ aim: "creature", hostile: true, closes_in: true, menace: true } }
fn yield_combat() { #{ reflex: true, force: true } }
fn seize_combat() { #{ aim: "creature", dares: true } }
fn tend_combat() { #{ aim: "creature" } }
// The player's skill bar, in order (the game binds LMB, RMB, Q, E, R, Shift, Space).
fn skill_bar() { ["strike", "bowshot", "firebolt", "block", "heal", "dodge", "jump"] }
// How a skill is presented to a player: `<skill>_ui()`, read once when the script is installed
// (docs/INTERFACE.md). It only shows: what a skill may do is its spec, shape and check. A skill
// that declares nothing is presented by how the rules aim it; these three look otherwise.
fn strike_ui() { #{ look: #{ icon: "sword", clip: ["slash", "overhead", "thrust"], effect: "slash" } } }
fn shoot_ui() { #{ look: #{ icon: "bow", clip: "shoot", effect: "none" } } }
fn throw_ui() { #{ look: #{ icon: "sword", clip: "throw", effect: "none" } } }
// How far and fast a dodge carries a body (tiles, tiles/s); hits while it lasts miss.
fn dodge_dist(kind) { kind_of(kind).dodge_dist }
fn dodge_speed(kind) { kind_of(kind).dodge_speed }

fn dodge_check(a) { if a.actor.energy < 5.0 { "too exhausted to dodge" } else { "" } }
fn dodge_done(a) { spent("dodge") }

// A jump (proposal for the owner, 2026-11-11): a hop of `jump_dist` tiles the way you move or
// face, at `jump_speed` (a person: 1.6 tiles in about 0.45 s). The world is flat, so its height
// is only shown (about half a metre). It stops short of walls, fences and water as a dodge
// does, and does not evade: blows and missiles land while you are in the air.
fn jump_dist(kind) { switch kind { "wolf" => 2.0, "deer" => 2.4, _ => 1.6 } }
fn jump_speed(kind) { switch kind { "wolf" => 6.0, "deer" => 6.0, _ => 3.6 } }
fn jump_check(a) { if a.actor.energy < combat_cost("jump") { "too tired to jump" } else { "" } }
fn jump_done(a) { spent("jump") }

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
    for i in items() { if nutrition(i.name) > 0.0 { parts.push(`${i.name} ${nutrition(i.name).to_int()}`); } }
    list(parts)
}
// Where an item comes from (shown when a skill lacks it).
fn gathered() { names_of("resources") }
fn source_of(item) {
    for r in names_of("resources") {
        if entry_of("resources", r).yields == item { return `gather it at a ${r}, or take it from a storage`; }
    }
    if item == "food" {
        // What can be gathered and eaten, from the items' nutrition and the resources' yields.
        let ways = [];
        for r in gathered() { let y = yield_of(r); if y != "" && nutrition(y) > 0.0 { ways.push(`${y} at a ${r}`); } }
        return `gather ${or_list(ways)}, take food from a storage, or hunt`;
    }
    switch item {
        "hide" => "kill game (attack), then take it from the remains",
        "meat" => "kill game (attack) and take it from the remains, take it from a trap or a storage",
        "cooked_fish" => "cook fish at a campfire",
        "cooked_meat" => "cook meat at a campfire",
        "smoked_fish" => "smoke fish at a campfire (knowing smoking), or trade for it",
        "smoked_meat" => "smoke meat at a campfire (knowing smoking), or trade for it",
        _ => {
            if cost(item) != () { return `craft it (${cost_text(item)})`; }
            let m = recipe_for(item);
            if m != () { recipe_words(m) } else { "someone who has it can give or trade it to you" }
        },
    }
}
// How a made item is made, from its recipe.
fn made_how(item) { recipe_words(recipe_for(item)) }
// A recipe's words: `m` is #{ r: the recipe, input: the item it turns (or ()) }.
fn recipe_words(m) {
    let r = m.r;
    let parts = [];
    let t = if r.turns != () && m.input == () { #{} } else { takes_of(m) };
    for k in t.keys() { parts.push(`${t[k]} ${k}`); }
    if r.turns != () && m.input == () { parts.push(`anything with ${r.turns}`); }
    let at = if r.at == () { "" } else if r.at == "fire" { " at a fire" } else { ` at a ${r.at}` };
    let heat = if r.fuel == () { "" } else { ` and ${short(r.fuel)} fuel from it` };
    let how = if r.knows == () { "" } else { ` (knowing ${r.knows})` };
    `make it${at} from ${list(parts)}${heat}${how}`
}
// The items fires burn: whatever has one of their fuel traits.
fn fuels() {
    let out = [];
    for k in having("structures", "burns") {
        for i in having("items", burns_of(k).fuel) { if !out.contains(i) { out.push(i); } }
    }
    out
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
fn wander_spec() { #{ moment: true, about: "Stroll to a random spot nearby, to look around when nothing you need is in sight. It searches for nothing in particular.", gives: "you at a nearby spot you may not have seen" } }
fn gather_spec() {
    #{ latch: true, target: true, reach: 1.3,
       about: "Take one unit from a resource beside you: berries from a berry_bush, wood from a tree, stone from a boulder, fiber from reeds, fish from a fishing_spot, clay from a clay_bank. The way to get food and materials from the land. Taking from a storage, remains or a trap is take.",
       takes: "a resource in reach with some left, room in your pack, a little energy",
       gives: "1 unit into your pack: berry_bush→berries, tree→wood (faster with an axe), boulder→stone (faster with a pick), reeds→fiber, fishing_spot→fish (faster with a spear, two at a time with a net), clay_bank→clay" }
}
fn eat_spec() {
    #{ latch: true, moving: true, item: "a food you carry, or \"food\" for your best",
       about: "Eat one food item from your own pack. Only what you carry: food in a storage must be taken out first, food someone else has must be given to you.",
       takes: "1 food item from your own pack",
       gives: `hunger down by its worth (${foods_text()}), a little health` }
}
fn cook_spec() { #{ latch: true, notable: true, target: true, item: true, reach: 1.5, about: "Cook raw fish or meat at a campfire beside you: about twice as filling, and it keeps longer. Needs cooking.", takes: "1 raw fish or meat from your pack, a campfire in reach, knowing cooking", gives: "1 cooked_fish or cooked_meat" } }
fn smoke_spec() { #{ target: true, item: true, reach: 1.5, about: "Smoke raw fish or meat at a campfire beside you so it keeps for weeks: food to store, carry far or trade. Needs smoking.", takes: "1 raw fish or meat from your pack, a campfire in reach, knowing smoking, 10 seconds", gives: "1 smoked_fish or smoked_meat: more filling than raw" } }
fn clear_spec() { #{ about: "Turn the forest where you stand into open ground. For making room to build; gathering at a tree is the quicker way to get wood.", takes: "forest where you stand, room in your pack, some energy (faster with an axe)", gives: "open ground where the forest was, and 2 wood" } }
fn graze_spec() { #{ moment: true, listed: false, about: "Eat grass where you stand (grazing animals).", takes: "grass where you stand, not grazed bare", gives: "hunger down by 14" } }
fn sleep_spec() { #{ latch: true, moment: true, about: "Sleep until rested. Night is the time for it; beside a shelter or house it is much faster and the night cold can't hurt you. A short break is rest.", takes: "time, until rested", gives: "energy back quickly (much faster beside a shelter or house); hunger grows slower meanwhile" } }
fn rest_spec() { #{ latch: true, moment: true, about: "Sit a few seconds and recover a little energy. Sleep restores far more.", takes: "8 seconds", gives: "a little energy" } }
fn wait_spec() { #{ moving: true, moment: true, args: ["qty"], about: "Pause where you are (qty: seconds, at most 120).", takes: "time", gives: "nothing: time passes" } }

fn build_spec() {
    let l = laws();
    #{ latch: true, notable: true, item: true, items: ["campfire", "shelter", "storage", "house", "trap", "wall", "gate", "bridge"], reach: 1.5,
       about: "Build a structure where you stand (campfire, shelter, storage, house, trap), or a wall, gate or bridge on the tile beside you that you point at (target {\"at\": [x, y]}; a bridge goes on water). There is no repairing or mending of anything: a structure stands until it is gone.",
       takes: `its materials from your pack (campfire ${cost_text("campfire")}; shelter ${cost_text("shelter")}; storage ${cost_text("storage")}; house ${cost_text("house")}; wall ${cost_text("wall")}; gate ${cost_text("gate")}; trap ${cost_text("trap")}; bridge ${cost_text("bridge")}) and knowing its technique`,
       gives: `the structure here: a campfire warms within ${l.fire_warmth} tiles at night, a shelter or house within ${l.shelter_warmth} and makes sleep restful, a storage keeps items (food spoils slower), a trap catches game over time (take the meat from it), a bridge makes the water tile beside you a way across` }
}
fn pave_spec() { #{ about: "Lay road on the tile you stand on. Walking on road is faster: worth it on ways walked often.", takes: cost_text("road"), gives: "road under you" } }
fn open_spec() { #{ target: true, reach: 1.8, about: "Open a gate. Only members of the gate's community may; anyone else must ask one of them.", takes: "a gate in reach, belonging to your community", gives: "the gate open: anyone may pass" } }
fn close_spec() { #{ target: true, reach: 1.8, about: "Close a gate: closed, it blocks the way like a wall. Only members of its community may.", takes: "a gate in reach, belonging to your community", gives: "the gate shut" } }
fn craft_spec() {
    #{ latch: true, notable: true, item: true, items: ["spear", "cloak", "torch", "axe", "pick", "net", "basket", "bow", "arrow", "salve", "leather", "armor"],
       about: "Make a tool, weapon or garment from materials in your pack. Each needs its technique. Structures are built (build); nothing is repaired.",
       takes: `its materials from your pack (spear ${cost_text("spear")}; cloak ${cost_text("cloak")}; torch ${cost_text("torch")}; axe ${cost_text("axe")}; pick ${cost_text("pick")}; net ${cost_text("net")}; basket ${cost_text("basket")}; bow ${cost_text("bow")}; arrow ${cost_text("arrow")} for 3; salve ${cost_text("salve")}; leather ${cost_text("leather")}; armor ${cost_text("armor")}) and knowing how`,
       gives: "the item in your pack: a spear hits harder, a cloak keeps the night cold off, a torch lights the night, an axe or pick gathers faster, a net catches two fish at a time, a basket carries 20 more, a bow shoots arrows, a salve helps tending, armor softens blows" }
}

fn give_spec() {
    #{ latch: true, notable: true, target: true, item: true, args: ["qty"], reach: 1.8, talk: true,
       about: "Hand items from your pack to someone beside you. Nothing is asked in return; for an exchange now, offer. It is also how you pay what you agreed to or what is demanded of you: the world counts it.",
       takes: "the items from your pack, room in their pack", gives: "the items in their pack" }
}
fn store_spec() {
    #{ latch: true, notable: true, target: true, item: true, args: ["qty"], reach: 1.5,
       about: "Put items from your pack into a storage beside you. Storing into someone's household store is how goods are delivered to them while they are away.",
       takes: `the items from your pack, a storage in reach with room (a storage holds ${storage_holds(0)} things in all)`, gives: "the items in the storage" }
}
fn take_spec() {
    #{ latch: true, notable: true, target: true, item: true, args: ["qty"], reach: 1.5,
       about: "Take items from a storage, remains or a trap beside you. From another household's store, unless you are their guest or of their community, it is theft: its owner and anyone watching see it.",
       takes: "items in a storage, remains or a trap in reach, room in your pack", gives: "the items in your pack" }
}
fn feed_spec() {
    #{ latch: true, notable: true, target: true, item: true, items: ["fuel"] + fuels(), args: ["qty"], reach: 1.5, listed: having("structures", "burns").len() > 0,
       about: "Put fuel from your pack on a fire beside you that burns it (a hearth, an oven, a furnace): it burns only while it has fuel, and goes out when the fuel is spent. Feeding an out fire lights it again, which takes knowing fire. A campfire needs no feeding. Item \"fuel\" puts on the first fuel you carry.",
       takes: "fuel from your pack (anything that fire burns), a fire in reach with room for it", gives: "the fire burning longer, or lit again" }
}
fn make_spec() {
    #{ latch: true, notable: true, target: true, item: true, items: products(), reach: 1.5, listed: names_of("recipes").len() > 0,
       about: "Make goods from what you carry at the place they are made (target it: a furnace, an oven, a fire...), by the world's recipes: some need the fire there burning and use some of its fuel, some a technique. Tools and garments are crafted (craft); structures are built (build).",
       takes: "the recipe's goods from your pack, its workplace in reach (lit, with fuel, when it needs heat)", gives: "the goods made, in your pack" }
}
fn drop_spec() { #{ item: true, args: ["qty"], about: "Set items down where you stand and leave them, e.g. to free your pack. What is dropped is kept for no one.", takes: "the items from your pack", gives: "room in your pack; the items are left behind" } }

fn attack_spec() {
    #{ notable: true, target: true, reach: 1.4,
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
    #{ notable: true, target: true, reach: 3.0,
       about: "Menace a creature within a few tiles for 2 s, weapon raised. No harm is done, but they and anyone watching see it: a way to make a warning or a demand felt without a blow.",
       takes: "a creature within a few tiles, 2 seconds", gives: "no harm: they see you menacing them, and so does anyone watching" }
}
fn seize_spec() {
    #{ target: true, item: true, args: ["qty"], reach: 1.8,
       about: "Take items from a person's pack against their will: only from someone who has yielded to you or is badly hurt. Everyone who sees it knows it was taken by force.",
       takes: "a person in reach who has yielded to force or is badly hurt, the items in their pack", gives: "the items in your pack; they and anyone watching see you take them" }
}
fn yield_spec() {
    #{ notable: true, reach: 12.0,
       about: "Give in: guard down, hands up (target: whom you yield to; without one, whoever last hurt you). It says you surrender; it does not stop blows by itself.",
       takes: "a second",
       gives: `for ${(yield_ms("person") / 1000.0).to_int()} seconds you do not strike back. Blows still land on you, but whoever strikes you meanwhile is seen striking someone who gave in` }
}
fn dodge_spec() { #{ about: "Dash out of the way (away from what is coming, or toward a point you aim at); a blow or missile landing while you dash misses. For fights, not travel.", takes: `${combat_cost("dodge")} energy`, gives: "a quick dash of a few tiles" } }
fn jump_spec() { #{ about: "Jump: a short hop the way you move or face. It does not clear walls, fences or water, and blows still land while you are in the air (it is not a dodge).", takes: `${combat_cost("jump")} energy; ready again after ${combat_cooldown("jump") / 1000.0} s`, gives: "you a hop of a tile or two along" } }
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

fn follow_spec() { #{ moment: true, target: true, reach: 2.0, about: "Walk alongside a creature for a while, keeping up as it moves: to go somewhere together or keep watch on someone. It does not make them follow you.", takes: "a creature in sight", gives: "you beside them as they go" } }
fn flee_spec() { #{ reflex: true, moment: true, target: true, about: "Run away from a creature or place until you are clear of it.", takes: "something to run from", gives: "distance between you and it" } }

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

fn conceive_spec() { #{ notable: true, target: true, reach: 2.0, talk: true, about: `Start a family with a willing adult partner: it happens when both of you choose it toward each other within 2 minutes, while fed${conceive_more()}.`, takes: `a willing adult partner choosing it too, both fed${conceive_more()}`, gives: "a child in time" } }
fn teach_spec() { #{ latch: true, target: true, item: "technique", reach: 2.0, talk: true, about: "Teach a technique you know to a person beside you. It takes a while and both must stay close; afterwards they know it and you still do.", takes: "a technique you know, a person beside you staying close for a while", gives: "they know it too" } }
fn experiment_spec() { #{ latch: true, item: "material", about: "Tinker with a material from your pack hoping to work out a new technique. It uses up the material and often fails; learning from someone who knows is surer.", takes: "1 of the material", gives: "sometimes a new technique" } }
fn write_spec() { #{ latch: true, item: true, items: ["tablet", "sign"], args: ["text", "topic"], about: "Write on a tablet you keep or a sign you leave here (text: your words; topic: a technique you know, so that readers can learn it). Needs writing.", takes: "1 wood, knowing writing", gives: "a tablet you keep or a sign left here, with your words" } }
fn read_spec() { #{ latch: true, reach: 1.5, about: "Read a tablet you carry, or a sign beside you (target {\"nearest\": \"sign\"}). Needs writing.", takes: "a tablet you carry or a sign here, knowing writing", gives: "its words; a tablet describing a technique can teach it" } }
fn plant_spec() { #{ latch: true, about: "Plant 2 berries where you stand to grow a new berry bush. Needs planting.", takes: "2 berries, open grass or dirt outside winter, knowing planting", gives: "a new berry bush in time" } }
fn signal_spec() { #{ moving: true, item: "signal name", about: "Make one of your species' signals; others nearby hear it.", takes: "a moment", gives: "your call, heard by those nearby" } }
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
// Working at a workplace and feeding a fire: `doing.x/y` is the fire or workplace.
fn make_shows() { #{ look: "work" } }
fn feed_shows() { #{ look: "work" } }
fn read_shows() { #{ look: "work" } }
fn tend_shows() { #{ look: "work" } }
fn eat_shows() { #{ look: "eat" } }
// Grazing looks like eating to a client that does not know it by name.
fn graze_shows() { #{ look: "eat" } }
fn sleep_shows() { #{ look: "sleep" } }
fn rest_shows() { #{ look: "rest" } }

// ---- laws: what each is, for minds (read once when the script compiles) --------------------
// Every law the engine asks is declared by a `<name>_law()`: `about` says what it is for a mind
// (the minds' world text is built from these, so it follows the rules), `cadence` how often
// the engine runs it, `topic` the section of the world text it belongs to, and `covers` the
// functions it declares besides its own name. A law with no function of its own states a rule
// the engine keeps (the calendar, death). Numbers in the texts come from the laws themselves.

// The sections of the minds' world text, in order: [topic, heading]. `seasons` and `life` are
// the world's own (its calendar and its people's life table) and come from the seed.
fn world_topics() {
    [["time", ""], ["senses", "SENSES"], ["speech", "SPEAKING"], ["moving", "MOVING"], ["seasons", "SEASONS"], ["body", "BODY"], ["know_how", "KNOW-HOW"],
     ["food", "FOOD"], ["making", "MAKING"], ["settlements", "SETTLEMENTS"], ["life", "LIFE"], ["combat", "COMBAT"], ["force", "FORCE"],
     ["communities", "COMMUNITIES"], ["purpose", "TIME"], ["others", "OTHERS"]]
}

// A person in a state, as the needs law reads one (for descriptions).
fn person_now(act, night) { #{ actor: #{ kind: "person", stage: "adult", activity: act, near_fire: false, near_shelter: false, inv: #{} }, night: night, season: "summer", raining: false } }

// When night falls and ends (hours of the day) and how long dusk and dawn take (game hours;
// 0: the light turns at once). The shipped day turns at once at 06:00 and 20:00.
fn night_hours() { #{ dusk: 20.0, dawn: 6.0, twilight: 0.0 } }
// 0 to 1 along a smooth step.
fn ease(x) { let t = if x < 0.0 { 0.0 } else if x > 1.0 { 1.0 } else { x }; t * t * (3.0 - 2.0 * t) }
// How light it is at an hour of the day (0..24): 0 is night, 1 full day; night is less than half
// light. With a twilight the light eases over it, half at dusk and at dawn. The engine reads it
// once per game minute of the day and keeps it (rules/src/script.rs `Scripts::daylight`), so it
// costs nothing per tick. Cold (`a.night`), sight (`light_of`; a floor may read `a.daylight`) and
// sleepiness (the graphs' `night` weight, the darkness) follow it.
fn daylight(hour) {
    let n = night_hours();
    if n.twilight <= 0.0 { return if hour >= n.dawn && hour < n.dusk { 1.0 } else { 0.0 }; }
    let half = n.twilight / 2.0;
    if hour < (n.dawn + n.dusk) / 2.0 { ease((hour - n.dawn + half) / n.twilight) } else { 1.0 - ease((hour - n.dusk + half) / n.twilight) }
}

// An hour of the day as "06:00".
fn clock_text(h) { let m = (h * 60.0).round().to_int(); let hh = m / 60; let mm = m % 60; (if hh < 10 { "0" } else { "" }) + `${hh}:` + (if mm < 10 { "0" } else { "" }) + `${mm}` }
fn calendar_law() {
    let n = night_hours();
    let dusk = if n.twilight > 0.0 { ` Dusk and dawn each take about ${short(n.twilight)} hour${if n.twilight == 1.0 { "" } else { "s" }}: the light goes and comes slowly.` } else { "" };
    #{ cadence: "hot", topic: "time", covers: ["daylight", "night_hours"], about: `One day lasts ${short(day_minutes())} real minutes; night is ${clock_text(n.dusk)}-${clock_text(n.dawn)}.${dusk}` }
}

// The need rates of a grown person awake by day (for descriptions); () when the rates law
// cannot say (a world's own rates, or rates given finished).
fn rates_awake() {
    try { let r = rates(person_now("", false)); if r.starving_at != () { return r; } } catch { }
    ()
}

// A rate of the rates law in real minutes, as the engine turns it (`per`: a game hour or a minute).
fn per_real_minute(r, x) { if r.per == "hour" { x * 60000.0 / hour_ms() } else { x } }

fn needs_law() {
    let awake = rates_awake();
    let l = laws();
    let rise = if awake == () { "hunger rises over time (100 = starving, which drains health); energy falls" } else { `hunger rises ~${short(per_real_minute(awake, awake.hunger))}/min (${short(awake.starving_at)} = starving, which drains health); energy falls ~${short(-per_real_minute(awake, awake.energy))}/min` };
    #{ cadence: "event", topic: "body", covers: ["rates", "body_state", "freezing"],
       about: `${rise} awake and recovers while sleeping (faster within ${short(l.shelter_warmth)} m of a shelter or house). At night, people farther than ${short(l.fire_warmth)} m from a campfire and ${short(l.shelter_warmth)} m from a shelter or house, and without a warm cloak, are cold: it tires them, and on winter nights or in the rain it also costs health. Health recovers slowly when fed and rested. Death is permanent.` }
}

// Every technique of the world's know-how table, with its `brief` where it has one.
fn know_how_text() {
    let parts = [];
    for n in names_of("know_how") {
        let b = entry_of("know_how", n).brief;
        parts.push(if b == () || b == "" { n } else { `${n} (${b})` });
    }
    let out = "";
    for p in parts { out += if out == "" { p } else { `, ${p}` }; }
    out
}
fn know_how_law() {
    #{ cadence: "event", topic: "know_how",
       about: `you can only do techniques you know: ${know_how_text()}. Others may know what you don't: ask them to teach you (teach takes time beside each other), read what someone wrote, or experiment with materials to work something out yourself. What only one person knows dies with them unless they teach it or write it down.` }
}

fn food_law() {
    #{ cadence: "compile", topic: "food", covers: ["nutrition", "spoil_per_h", "carried_spoil", "kept_spoil", "carry_limit", "source_of", "items"],
       about: `${foods_text()} (hunger points). Cook raw ${or_list(items_with("cooks_to"))} at a campfire (needs cooking). Food spoils: raw meat and fish within about a day, berries in a few days, cooked food more slowly; a storage keeps it ${short(1.0 / kept_spoil("storage"))} times longer. A pack holds about ${short(carry_limit("person"))} things. Berry bushes, reeds, fishing spots, trees, boulders and clay banks (along rivers) regrow slowly after harvesting; stone is plentiful in the western hills and scarce in the east. Deer can be hunted (${carcass("deer").meat} meat); wolves roam forests and hunt deer; they fear people, and attack a person only when starving with no prey near, or when the person is easy prey (a child, badly hurt, asleep away from a fire, or alone at night away from a fire).` }
}

// The world's recipes and fires in words, for the making law (empty when it has none).
fn recipes_text() {
    let parts = [];
    for n in names_of("recipes") {
        let r = entry_of("recipes", n);
        let what = if r.turns == () { gives_of(r) } else { `${n} (what has ${r.turns})` };
        parts.push(`${what}: ${recipe_words(#{ r: r, input: () })}`);
    }
    if parts.len() == 0 { "" } else { ` Made at workplaces (make): ${list(parts)}.` }
}
fn fires_text() {
    let parts = [];
    for k in having("structures", "burns") {
        let b = burns_of(k);
        let warms = if b.warmth == () || b.warmth <= 0.0 { "" } else { ` and warms within ${short(b.warmth)} m while lit` };
        parts.push(`a ${k} burns ${short(b.rate)} ${b.fuel} a game hour (${or_list(having("items", b.fuel))})${warms}`);
    }
    if parts.len() == 0 { "" } else { ` Fires that burn fuel (feed them): ${list(parts)}; one goes out when its fuel is spent and is lit again by feeding it.` }
}

fn making_law() {
    let parts = [];
    for k in ["campfire", "shelter", "storage", "spear", "cloak", "torch", "house", "gate", "wall", "road", "axe", "pick"] {
        let c = cost(k);
        let need = "";
        for m in c.keys() { if need != "" { need += " + "; } need += `${c[m]} ${m}`; }
        parts.push(`${k} = ${need}`);
    }
    #{ cadence: "event", topic: "making", covers: ["structures", "resources", "regrow_per_h", "planted_max", "trap_every_h", "trap_holds"],
       about: `${list(parts)} (a wall and a road per tile; a tablet or sign is 1 wood, to write on). A spear hits much harder and fishes faster; an axe cuts wood and a pick breaks stone twice as fast; a cloak keeps the night cold off; a house is a home, warm like a shelter and a fire; walking on road is faster; anyone can take from a storage.` }
}

// The world's fires that burn fuel and its recipes, for minds; a world with neither says
// nothing of them.
fn workplaces_law() {
    let t = fires_text() + recipes_text();
    t.trim();
    #{ cadence: "event", topic: if t == "" { "" } else { "making" }, covers: ["recipes"],
       about: if t == "" { "Fires that burn fuel, and recipes made at workplaces: this world has none." } else { t } }
}

fn settlements_law() {
    #{ cadence: "event", topic: "settlements",
       about: "walls block the way; a gate lets people through while open, and only the members of the community that keeps it may open or shut it. Who is let in, when gates are shut and who keeps watch is for each community to decide." }
}

fn theft_law() {
    #{ cadence: "event", topic: "settlements",
       about: "Taking from someone else's store when you are not of their people and not their guest is theft: if the owner sees it, they are roused, and anyone watching sees you take it." }
}

fn remains_law() {
    #{ cadence: "event", topic: "food", covers: ["carcass", "remains_h"],
       about: `Whatever dies leaves remains where it fell: what it carried, and what its body gives (a deer ${carcass("deer").meat} meat and ${carcass("deer").hide} hide, a wolf ${carcass("wolf").meat} meat and ${carcass("wolf").hide} hide). A kill does not fill the killer's pack: whoever is beside the remains, the hunter, its pack or anyone else, takes from them (take). Remains are gone after about ${short(remains_h("deer") * hour_ms() / 60000.0)} minutes (a person's after ${short(remains_h("person") * hour_ms() / 60000.0)}), with whatever is left in them, unless they hold a tablet or sign.` }
}

fn combat_law() {
    #{ cadence: "event", topic: "combat", covers: ["combat_cooldown", "combat_recover", "combat_cost", "lunge", "max_hp", "dodge_dist", "dodge_speed", "step_aside_dist", "kinds"],
       about: `fights are fast. An attack winds up for about 0.6-0.75 s before it lands; the target can see it coming ({"threatened": true}). dodge = a quick dash (an attack landing during it misses; costs energy); block = raise your guard (hits do a quarter of the damage, but you cannot act meanwhile); throw = hurl your spear (you lose it). A blow lands only if you are still within reach (about ${short(attack_spec().reach + lunge("person"))} m; a wolf's leap about ${short(attack_spec().reach + lunge("wolf"))}) when its windup ends: stepping back or running as it winds up makes it miss, but whoever swings stands still meanwhile. You can outrun a person who keeps stopping to swing, not a wolf (a wolf catches the young, old, tired or surprised). While fighting, your graph is checked about 15 times a second; you can patch a single labeled branch mid-fight.` }
}

fn force_law() {
    #{ cadence: "event", topic: "force", covers: ["yield_ms"],
       about: `every blow, shot or bolt does its full damage, and whoever reaches 0 health dies; a blow cannot be held back. threaten = menace someone within a few tiles with harm for 2 s (no harm yet; they see it coming, as {"threatened": true}, and so does anyone watching). It is a threat of violence: to ask, wake, urge or call someone, speak (say) instead. seize = take items from a person's pack against their will, only from someone who has yielded to force or is badly hurt (to get goods by force you need not kill). yield = give in, guard down and hands up: for ${short(yield_ms("person") / 1000.0)} s you do not strike back. Blows still land on you, but whoever strikes you meanwhile is seen striking someone who gave in. Everyone nearby sees which force was used.` }
}

fn communities_law() {
    #{ cadence: "event", topic: "communities", about: `people can found a community (the act {"do": "found", "text": "its name"}), ask a member to join it (join), welcome someone who asked (welcome), or leave. What a community means, who does what and how it treats others is up to its members.` }
}

fn purpose_law() { #{ cadence: "event", topic: "purpose", about: "beyond staying alive, how you spend your days is yours to decide, from who you are and what you want." } }

fn perceived_of_law() {
    #{ cadence: "event", topic: "others",
       about: "You cannot read minds; what others say may be false. You only know what you perceived or were told. You know someone's name once they say it, or you are family, of one community, or close; until then they are a stranger to you." }
}

fn dealings_law() {
    #{ cadence: "event", covers: ["record_text", "on_give", "on_store", "on_host", "on_expire", "due_by_dark"],
       about: "Agreements and demands are kept by the world: it counts what each side hands over, stores or hosts for the other, and tells both sides when an agreement is kept, broken or lapses at its dusk, and when a demand is met or goes unpaid." }
}

fn occupations_law() {
    #{ cadence: "compile", covers: ["occupation_knows"], about: "What someone of an occupation knows from the start of the world: a fisher spears and cooks, a builder builds shelters and houses, and so on." }
}

// What each world constant (`laws()`) is, given the values: every key needs a text.
fn laws_about(l) {
    #{
        fire_warmth: `a campfire warms those within ${short(l.fire_warmth)} m`,
        shelter_warmth: `a shelter or a house shelters (and a house warms) those within ${short(l.shelter_warmth)} m`,
        gestation_days: `a child is carried about ${short(l.gestation_days)} days (the species' life table may say otherwise)`,
        bond_window_s: `two adults who both choose to start a family do so within ${short(l.bond_window_s)} s of each other`,
        crowd: `more than ${short(l.crowd)} people in sight is a crowd`,
        danger_near: `a predator within ${short(l.danger_near)} m is a danger near`,
        danger_far: `a predator within ${short(l.danger_far)} m is noticed as a danger`,
        repeat_failure_s: `the same failure within ${short(l.repeat_failure_s)} s is not news again`,
        road_speed: `walking on road is ${short(l.road_speed)} times as fast`,
        slow_radius: `walkers slow down within ${short(l.slow_radius)} m of where they are going`,
        corner_radius: `walkers cut a corner from ${short(l.corner_radius)} m before it`,
        steer_s: `a walker alone looks again at least every ${short(l.steer_s)} s`,
        crowd_hz: `among others a walker looks again ${short(l.crowd_hz)} times a second`,
        chase_hz: `a chaser or follower looks again ${short(l.chase_hz)} times a second`,
        combat_hz: `in a fight a body looks again ${short(l.combat_hz)} times a second`,
        input_hz: `a player may send ${short(l.input_hz)} movement inputs a second`,
        input_burst: `and ${short(l.input_burst)} in a burst`,
        pasture_regen_per_h: `grass regrows ${l.pasture_regen_per_h} grazing units per grassy tile per growing game hour`,
        alone_within: `someone with no other person within ${short(l.alone_within)} m is alone`,
        face_slack: `a body within ${short(l.face_slack)} radians of facing something already faces it`,
        flee_clear: `a flight ends ${short(l.flee_clear)} m farther from the threat than it began`,
        scent_hz: `a creature smells afresh ${short(l.scent_hz)} times a second at most (or when it has moved a few metres); in between it keeps what it last smelled`,
        takeover_s: `a played character with no connection of its person for ${short(l.takeover_s)} s lives on under the world's minds`,
        follow_s: `one follow lasts ${short(l.follow_s)} s before the follower looks again`,
        read_sign_m: `reading with nothing named reads the nearest sign within ${short(l.read_sign_m)} m`,
        kin_near_m: `others of one's kind within ${short(l.kin_near_m)} m are kin near`,
        trade_window_s: `a trade offer can be accepted for ${short(l.trade_window_s)} s`,
        join_window_s: `a request to join a community stands ${short(l.join_window_s)} s`,
        address_m: `speech to no one in particular is for the only listener within ${short(l.address_m)} m`,
        keep_seen_m: `a creature in a player's sight stays seen until ${short(l.keep_seen_m)} m beyond it`,
        chase_lost_share: `a chase is lost beyond ${short(l.chase_lost_share)} times the chaser's sight`,
        spawn_hunger: `a body comes into the world with hunger ${short(l.spawn_hunger)}`,
        spawn_energy: `and energy ${short(l.spawn_energy)}`,
        pasture_per_tile: `each grassy tile holds ${l.pasture_per_tile} grazing units`,
        cry_prompts_carers: if l.cry_prompts_carers { "a crying infant makes its carers think about it" } else { "a crying infant is only heard" },
        longing_after_min: `a grown person longs for a child ${short(l.longing_after_min)} minutes after its own birth or its youngest child's (the most nurturing sooner)`,
        longing_food: if l.longing_food > 0.0 { `and only while carrying at least ${short(l.longing_food)} food` } else { "whatever food it carries" },
        fov_on: if l.fov_on { "one sees fully only the way one faces" } else { "one sees as far in every direction" },
        fov_focal_deg: `full sight within ${short(l.fov_focal_deg)} degrees of facing (when sight depends on facing)`,
        fov_side_deg: `side vision out to ${short(l.fov_side_deg)} degrees`,
        fov_side_share: `side vision reaches ${short(l.fov_side_share)} of one's sight`,
        fov_near_m: `one sees all round within ${short(l.fov_near_m)} m`,
        fov_near_dark_m: `and within ${short(l.fov_near_dark_m)} m in the dark`,
        fov_margin_deg: `someone already seen stays seen ${short(l.fov_margin_deg)} degrees past the edge of the view`,
        heard_near_m: `a sound within ${short(l.heard_near_m)} m is near`,
        heard_close_m: `within ${short(l.heard_close_m)} m it is close, farther it is far`,
        heard_linger_s: `a sound is kept in mind ${short(l.heard_linger_s)} s after it was last heard`,
        look_slack_deg: `a player's look within ${short(l.look_slack_deg)} degrees of the last is the same look`,
        look_walk_deg: `walking, one turns toward where one looks at most ${short(l.look_walk_deg)} degrees off one's way`,
    }
}
