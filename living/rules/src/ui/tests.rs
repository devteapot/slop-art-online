//! The interface's defaults against today's game, and the anti-drift tests: what a player is
//! offered and sends is what a mind is offered and writes (docs/INTERFACE.md §5).
//!
//! The oracles below are copies of the game client's decisions before declarations existed
//! (`living/game/src/combat.rs` `look()` on main, `Roles::of` on `ui-1-step4-wip`, `verbs.rs`
//! `plan()` and `Choice::node`). They are frozen here on purpose: when the client moves onto
//! `UiSpec` (INTERFACE.md step 2) these remain the record of what "today's game" was.

use super::*;
use crate::catalog;
use crate::graph::{self, Node, Target};
use crate::script::{ActorFacts, Scripts, SkillCtx, TargetFacts};
use crate::species::Species;
use serde_json::json;

fn island() -> Scripts {
    crate::cullet_check::island()
}

fn worlds() -> Vec<(&'static str, Scripts)> {
    vec![("island", island()), ("cullet", crate::cullet_check::cullet())]
}

fn species() -> BTreeMap<String, Species> {
    crate::species::parse(include_str!("../../../seeds/species.json")).expect("species")
}

// ---- oracles: today's client ---------------------------------------------------------------

/// `combat.rs` `look()` on main (bcd5…, 2026-11-11): clips, slash, bolt and icon.
#[derive(Debug, PartialEq)]
struct TodayLook {
    clips: Vec<&'static str>,
    slash: bool,
    bolt: bool,
    icon: &'static str,
}

fn today_look(skill: &str, aim: &str, radius: f32) -> TodayLook {
    let l = |clips: &[&'static str], icon: &'static str| TodayLook { clips: clips.to_vec(), slash: false, bolt: false, icon };
    match skill {
        "strike" => TodayLook { slash: true, ..l(&["sword_slash", "sword_overhead", "sword_thrust"], "sword") },
        "attack" => TodayLook { slash: true, ..l(&["sword_slash"], "sword") },
        "bowshot" | "shoot" => l(&["bow_shoot"], "bow"),
        "throw" => l(&["attack"], "sword"),
        "firebolt" => TodayLook { bolt: true, ..l(&["cast"], "fire") },
        "heal" => l(&["cast"], "heal"),
        "block" => l(&["block"], "shield"),
        "dodge" => l(&["dodge"], "dodge"),
        "jump" => l(&["jump"], "dodge"),
        _ => match aim {
            "point" if radius >= 0.25 => TodayLook { bolt: true, ..l(&["cast"], "fire") },
            "point" => l(&["bow_shoot"], "bow"),
            "facing" => l(&["block"], "shield"),
            "dash" => l(&["dodge"], "dodge"),
            "self_or_ally" => l(&["cast"], "heal"),
            "creature" => TodayLook { slash: true, ..l(&["sword_slash"], "sword") },
            _ => l(&[], "empty"),
        },
    }
}

/// The client clip a family stands for today (the theme's table in step 2).
fn clip_today(family: &str) -> &'static str {
    match family {
        "slash" => "sword_slash",
        "overhead" => "sword_overhead",
        "thrust" => "sword_thrust",
        "shoot" => "bow_shoot",
        "throw" => "attack",
        "cast" => "cast",
        "guard" => "block",
        "dash" => "dodge",
        "jump" => "jump",
        other => panic!("no clip today for the family `{other}`"),
    }
}

fn as_today(l: &Look) -> TodayLook {
    TodayLook { clips: l.clips.iter().map(|c| clip_today(c)).collect(), slash: l.effect == Some("slash"), bolt: l.effect == Some("bolt"), icon: l.icon.unwrap_or("empty") }
}

/// A `skill_card` row, as far as the oracles read it.
struct Card {
    skill: String,
    aim: &'static str,
    radius: f32,
    slot: usize,
    evades: bool,
}

fn cards(s: &Scripts) -> Vec<Card> {
    s.bar_entries()
        .into_iter()
        .filter(|e| s.shapes().on_bar(&e.name))
        .enumerate()
        .map(|(slot, e)| Card { skill: e.name.clone(), aim: e.aim.as_str(), radius: e.radius, slot, evades: e.evades })
        .collect()
}

/// `Roles::of` on `ui-1-step4-wip` (31b95bc7): main[0..5], jump, dodge, extra.
#[derive(Debug, PartialEq)]
struct Roles {
    main: [Option<String>; 5],
    jump: Option<String>,
    dodge: Option<String>,
    extra: Vec<String>,
}

fn roles_of(cards: &[Card]) -> Roles {
    let mut bar: Vec<&Card> = cards.iter().collect();
    bar.sort_by_key(|c| c.slot);
    let mut used: Vec<String> = Vec::new();
    let mut take = |want: &dyn Fn(&Card) -> bool| -> Option<String> {
        let c = bar.iter().find(|c| !used.contains(&c.skill) && want(c))?;
        used.push(c.skill.clone());
        Some(c.skill.clone())
    };
    let main = [
        take(&|c| c.aim == "creature"),
        take(&|c| c.aim == "point" && c.radius < 0.25),
        take(&|c| c.aim == "facing"),
        take(&|c| c.aim == "self_or_ally"),
        take(&|c| c.aim == "point"),
    ];
    let jump = take(&|c| c.aim == "dash" && !c.evades);
    let dodge = take(&|c| c.aim == "dash");
    let extra = bar.iter().filter(|c| !used.contains(&c.skill)).map(|c| c.skill.clone()).collect();
    Roles { main, jump, dodge, extra }
}

fn as_roles(b: &Bar) -> Roles {
    let k = |i: usize| b.skill.get(i).cloned().flatten();
    Roles { main: [b.primary.clone(), b.secondary.clone(), k(0), k(1), k(2)], jump: b.jump.clone(), dodge: b.dodge.clone(), extra: b.extra.clone() }
}

/// Where `verbs.rs` `plan()` offers a skill, before its checks run: toward myself, a creature
/// of my own kind, a creature of another kind, or a thing.
#[derive(Debug, PartialEq, Clone, Copy)]
enum Aimed {
    Me,
    OwnKind,
    OtherKind,
    Thing,
}

fn plan_offers(s: &Scripts, skill: &str, aimed: Aimed) -> bool {
    let spec = s.skills().get(skill).expect("spec");
    if s.shapes().get(skill).is_some_and(|sh| sh.real_time) {
        return false;
    }
    let wants_target = aimed != Aimed::Me;
    if spec.needs_target != wants_target {
        return false;
    }
    let checked = s.has(&format!("{skill}_check"));
    if !checked && (aimed == Aimed::Thing || (wants_target && aimed != Aimed::OwnKind)) {
        return false;
    }
    !spec.args.iter().any(|a| a == "graph")
}

// ---- defaults reproduce today's game --------------------------------------------------------

#[test]
fn defaults_reproduce_todays_looks() {
    for (world, s) in worlds() {
        let mut n = 0;
        for (skill, shape) in s.shapes().iter() {
            let u = s.ui(skill).unwrap_or_else(|| panic!("{world}: no UiSpec for combat skill `{skill}`"));
            let radius = combat_radius(&s, skill);
            match s.shows().get(skill) {
                // A shown skill (tend) is drawn by how others see it (the town look), not as a blow.
                Some(sh) => assert_eq!(u.look.clips, vec![name_in(CLIPS, &sh.look).expect("a family")], "{world}: `{skill}` plays its shown look"),
                None => assert_eq!(as_today(&u.look), today_look(skill, shape.aim.as_str(), radius), "{world}: `{skill}` looks as the client drew it"),
            }
            n += 1;
        }
        assert!(n >= 14, "{world}: {n} combat skills");
        // Every shipped `_shows().look` is a clip family, and a skill that shows plays it.
        for (skill, sh) in s.shows().iter() {
            let c = name_in(CLIPS, &sh.look).unwrap_or_else(|| panic!("{world}: `{skill}_shows()` look `{}` is no clip family", sh.look));
            assert_eq!(s.ui(skill).unwrap().look.clips, vec![c], "{world}: `{skill}`");
        }
    }
}

fn combat_radius(s: &Scripts, skill: &str) -> f32 {
    let shape = s.shapes().get(skill).unwrap();
    if !shape.missile {
        return 0.0;
    }
    let c = SkillCtx { actor: ActorFacts { kind: "person".into(), ..Default::default() }, skill: skill.into(), qty: shape.hold_ms, ..Default::default() };
    s.missile(skill, &c).map_or(0.0, |m| m.radius)
}

#[test]
fn the_three_looks_by_name_are_declared_not_coded() {
    // Today's client drew strike, shoot and throw by name; their looks are the script's now.
    let s = island();
    for skill in ["strike", "shoot", "throw"] {
        let (u, d) = (s.ui(skill).unwrap(), s.ui_default(skill).unwrap());
        assert!(u.declared, "{skill}_ui() is shipped");
        assert_ne!(u.look, d.look, "{skill}: the declaration is what makes it look as it did");
        // Only the look is declared: everything else is its default.
        assert_eq!(UiSpec { look: d.look.clone(), declared: false, ..u.clone() }, d, "{skill}: only `look` is declared");
    }
    let declared: Vec<&str> = s.ui_specs().filter(|u| u.declared).map(|u| u.name.as_str()).collect();
    assert_eq!(declared, ["strike", "throw", "shoot"], "the shipped script declares only these (step 2 adds the bar's)");
}

#[test]
fn defaults_reproduce_todays_bar() {
    for (world, s) in worlds() {
        let bar = bar_places(&s);
        assert_eq!(as_roles(&bar), roles_of(&cards(&s)), "{world}: the bar as Roles::of placed it");
        assert!(bar.weapon.is_none());
    }
    // The shipped bar, spelt out: LMB strike, RMB bowshot, Q block, E heal, R fire bolt, Space
    // jump, Shift dodge. On main the keys went by slot (Q fire bolt, E block, R heal); the WIP
    // and the design settled Q E R as here (INTERFACE.md example 2). LMB, RMB, Shift and Space
    // are the same on both.
    let b = bar_places(&island());
    let some = |s: &str| Some(s.to_string());
    assert_eq!((b.primary.clone(), b.secondary.clone()), (some("strike"), some("bowshot")));
    assert_eq!(b.skill, vec![some("block"), some("heal"), some("firebolt")]);
    assert_eq!((b.jump.clone(), b.dodge.clone(), b.extra.len()), (some("jump"), some("dodge"), 0));
    let main_by_slot = island().shapes().bar().to_vec();
    assert_eq!((main_by_slot[0].as_str(), main_by_slot[1].as_str(), main_by_slot[5].as_str(), main_by_slot[6].as_str()), ("strike", "bowshot", "dodge", "jump"));
    // Every skill of the bar keeps a place.
    for n in island().shapes().bar() {
        assert!(b.place_of(n).is_some(), "`{n}` lost its place");
    }
}

#[test]
fn bar_places_match_roles_of_for_any_bar() {
    // Every order of the shipped bar's skills, and a bar with a second of each aim.
    let s = island();
    let mut base: Vec<BarEntry> = s.bar_entries();
    base.push(BarEntry { name: "lance".into(), aim: Aim::Creature, evades: false, radius: 0.0, place: None, order: None });
    base.push(BarEntry { name: "flare".into(), aim: Aim::Point, evades: false, radius: 0.5, place: None, order: None });
    base.push(BarEntry { name: "dart".into(), aim: Aim::Point, evades: false, radius: 0.1, place: None, order: None });
    base.push(BarEntry { name: "roll".into(), aim: Aim::Dash, evades: true, radius: 0.0, place: None, order: None });
    let mut seen = 0;
    let n = base.len();
    // A deterministic sample of orders (all 11! are too many): rotations and reversals.
    for r in 0..n {
        for rev in [false, true] {
            let mut es = base.clone();
            es.rotate_left(r);
            if rev {
                es.reverse();
            }
            for keep in [n, n - 4, 5, 3] {
                let es = &es[..keep];
                let cs: Vec<Card> = es.iter().enumerate().map(|(slot, e)| Card { skill: e.name.clone(), aim: e.aim.as_str(), radius: e.radius, slot, evades: e.evades }).collect();
                assert_eq!(as_roles(&bar_places_of(es)), roles_of(&cs), "order {:?}", es.iter().map(|e| &e.name).collect::<Vec<_>>());
                seen += 1;
            }
        }
    }
    assert!(seen > 80);
}

#[test]
fn declared_places_come_first() {
    let mut es = island().bar_entries();
    let set = |es: &mut Vec<BarEntry>, n: &str, p: BarPlace, o: Option<i64>| {
        let e = es.iter_mut().find(|e| e.name == n).unwrap();
        e.place = Some(p);
        e.order = o;
    };
    // Fire bolt on the first skill key: the guard passes to the first free key, the heal keeps E.
    set(&mut es, "firebolt", BarPlace::Skill, Some(0));
    let b = bar_places_of(&es);
    assert_eq!(b.skill, vec![Some("firebolt".into()), Some("heal".into()), Some("block".into())]);
    // The dodge as the primary: strike goes to the extra row.
    set(&mut es, "dodge", BarPlace::Primary, None);
    let b = bar_places_of(&es);
    assert_eq!((b.primary.as_deref(), b.dodge.as_deref(), b.extra.clone()), (Some("dodge"), None, vec!["strike".to_string()]));
    // An extra with an order sorts before the extras that have none.
    set(&mut es, "jump", BarPlace::Extra, Some(0));
    let b = bar_places_of(&es);
    assert_eq!(b.extra, vec!["jump".to_string(), "strike".to_string()]);
    // Two claims of a single place: the first in bar order keeps it (an install refuses the
    // second), the other goes to the extra row.
    set(&mut es, "heal", BarPlace::Primary, None);
    let b = bar_places_of(&es);
    assert_eq!(b.primary.as_deref(), Some("heal"));
    assert!(b.extra.contains(&"dodge".to_string()));
}

#[test]
fn defaults_reproduce_todays_aims_and_lists() {
    for (world, s) in worlds() {
        for spec in s.skills().iter() {
            let name = spec.name.as_str();
            let u = s.ui(name).unwrap();
            // The F and C lists: where `plan()` offered it.
            assert_eq!(u.is_on(On::Me), plan_offers(&s, name, Aimed::Me), "{world}: `{name}` toward myself");
            assert_eq!(u.is_on(On::Person), plan_offers(&s, name, Aimed::OwnKind), "{world}: `{name}` toward a person");
            assert_eq!(u.is_on(On::Thing), plan_offers(&s, name, Aimed::Thing), "{world}: `{name}` toward a thing");
            // Toward an animal the client still asks the rules' check first (a runtime filter).
            assert!(!plan_offers(&s, name, Aimed::OtherKind) || u.is_on(On::Person));
            assert_eq!(u.is_on(On::Bar), s.shapes().on_bar(name), "{world}: `{name}` on the bar");
            assert_eq!(u.is_on(On::Item), spec.needs_item && (u.is_on(On::Me) || u.is_on(On::Person)), "{world}: `{name}` from the pack");
            // The label: the name with spaces (the client's `pretty`), capitalised.
            assert_eq!(u.label.to_lowercase(), name.replace('_', " "));
        }
        // How the bar aims: input, marker and the act a press is.
        for (name, shape) in s.shapes().iter().filter(|(n, _)| s.shapes().on_bar(n)) {
            let u = s.ui(name).unwrap();
            let (input, marker) = match shape.aim {
                Aim::Point => (Input::AimPoint, Marker::Line),
                Aim::Facing => (Input::Hold, Marker::Arc),
                Aim::Creature | Aim::SelfOrAlly => (Input::Tap, Marker::Circle),
                _ => (Input::Tap, Marker::None),
            };
            assert_eq!((u.input, u.marker), (input, marker), "{world}: `{name}`");
            assert_eq!(u.running.show, if shape.aim == Aim::Facing { RunShow::Held } else { RunShow::Windup }, "{world}: `{name}`");
            assert_eq!(u.refused_at(On::Bar), Refused::Grey);
        }
    }
}

// ---- anti-drift (a): what a player sends, a mind's grammar accepts -------------------------------

/// The target an act names, by kind.
#[derive(Debug, PartialEq)]
enum Kind {
    None,
    Id(u32),
    Nearest(String),
    At,
}

fn kind_of(t: &Option<Target>) -> Kind {
    match t {
        None | Some(Target::Me) => Kind::None,
        Some(Target::Id(i)) => Kind::Id(*i),
        Some(Target::Nearest(f)) => Kind::Nearest(f.kind.clone()),
        Some(Target::At(_)) => Kind::At,
        Some(other) => panic!("unexpected target {other:?}"),
    }
}

fn want(t: &ActTarget) -> Kind {
    match t {
        ActTarget::Me => Kind::None,
        ActTarget::Creature(i) => Kind::Id(*i),
        ActTarget::Thing { kind, .. } => Kind::Nearest(kind.clone()),
        ActTarget::At(_) => Kind::At,
    }
}

/// The items a player could pick for a skill: its own words, else the world's items (or its
/// techniques, or the body's signals).
fn item_choices(spec: &crate::catalog::SkillSpec, body: &Species) -> Vec<String> {
    if !spec.items.is_empty() {
        return spec.items.clone();
    }
    if spec.item_arg.contains("technique") {
        return catalog::technique_names();
    }
    if spec.item_arg.contains("signal") {
        return body.signals.keys().cloned().collect();
    }
    let mut v = catalog::item_names();
    if spec.item_arg.contains("food") {
        v.push("food".into());
    }
    v
}

/// The targets a place sends, for a skill.
fn targets(on: On, spec: &crate::catalog::SkillSpec) -> Vec<ActTarget> {
    let things = || catalog::resource_names().into_iter().chain(catalog::structure_names());
    match on {
        On::Person => vec![ActTarget::Creature(7)],
        On::Thing => things().flat_map(|k| [ActTarget::Thing { kind: k.clone(), at: None }, ActTarget::Thing { kind: k, at: Some([3.0, 4.0]) }]).collect(),
        On::Ground => vec![ActTarget::At([3.0, 4.0])],
        On::Me => vec![ActTarget::Me],
        On::Item if spec.needs_target => vec![ActTarget::Creature(7)],
        On::Item => vec![ActTarget::Me],
        On::Bar | On::Box => vec![],
    }
}

/// Every act a default interface would send for a skill: its place, the target and what was
/// picked, and the node.
fn player_acts(s: &Scripts, u: &UiSpec, body: &Species) -> Vec<(On, ActTarget, Picked, serde_json::Value)> {
    let Some(spec) = s.skills().get(&u.name) else { return Vec::new() };
    let items: Vec<Option<String>> = if u.picks.contains(&Pick::Item) { item_choices(spec, body).into_iter().map(Some).collect() } else { vec![None] };
    let mut out = Vec::new();
    for &on in &u.on {
        if on == On::Bar {
            let shape = s.shapes().get(&u.name).expect("a bar skill is a combat skill");
            for t in [Some(7), None] {
                let node = bar_act(&u.name, shape.aim, t, [3.0, 4.0]);
                let at = match (shape.aim, t) {
                    (Aim::Creature, Some(i)) | (Aim::SelfOrAlly, Some(i)) => ActTarget::Creature(i),
                    (Aim::SelfOrAlly, None) => ActTarget::Me,
                    _ => ActTarget::At([3.0, 4.0]),
                };
                out.push((on, at, Picked::default(), node));
            }
            continue;
        }
        for t in targets(on, spec) {
            for item in &items {
                let p = Picked {
                    item: item.clone(),
                    qty: u.picks.contains(&Pick::Qty).then_some(2),
                    want: u.picks.contains(&Pick::Want).then(|| catalog::item_names().into_iter().find(|w| Some(w) != item.as_ref()).unwrap()),
                    want_qty: None,
                    text: u.picks.contains(&Pick::Words).then(|| "a few words".to_string()),
                };
                let node = act_node(&u.name, &t, &p);
                out.push((on, t.clone(), p, node));
            }
        }
    }
    out
}

/// The act a mind's grammar makes of a node (the one-off act path, or a graph leaf for
/// real-time behaviour, or the leaf after a walk), and the player's path through `human_act`.
fn mind_reads(s: &Scripts, node: &serde_json::Value, body: &Species) -> Result<graph::Action, String> {
    let real_time = |a: &graph::Action| real_time(s.skills(), s.shapes(), &a.skill);
    // The authority's `human_act` parses the same node with the same grammar.
    let player = graph::parse(&node.to_string()).map_err(|e| format!("human_act refuses it: {e}"))?;
    let (g, warnings) = graph::from_value_for(node.clone(), body).map_err(|e| format!("a mind's graph refuses it: {e}"))?;
    if !warnings.is_empty() {
        return Err(format!("a mind's grammar pruned it: {warnings:?}"));
    }
    assert_eq!(g.root, player.root, "human_act and a mind read {node} alike");
    let leaf = match &g.root {
        Node::Do(a) => a.clone(),
        Node::Seq(c) => match c.children.as_slice() {
            [Node::Do(walk), Node::Do(a)] if walk.skill == "goto" => a.clone(),
            other => return Err(format!("not a walk then an act: {other:?}")),
        },
        other => return Err(format!("not an act: {other:?}")),
    };
    if !real_time(&leaf) && matches!(g.root, Node::Do(_)) {
        // A one-off act: the path minds' decisions take (`mind_act` → `acts::parse`).
        let a = crate::acts::parse(node.clone(), Some(body), s.shapes()).map_err(|e| format!("a mind's act refuses it: {e}"))?;
        assert_eq!(a, leaf);
    } else if real_time(&leaf) {
        assert!(crate::acts::not_an_act(&leaf.skill, s.shapes()).is_some(), "`{}` is real-time for both", leaf.skill);
    }
    Ok(leaf)
}

#[test]
fn every_default_act_is_one_a_mind_could_write() {
    let sp = species();
    let person = &sp["person"];
    for (world, s) in worlds() {
        catalog::scoped(s.skills().clone(), || {
            let mut checked = 0;
            for spec in offered(s.skills(), Some(person)) {
                let u = s.ui_default(&spec.name).expect("a default for every offered skill");
                for (on, t, p, node) in player_acts(&s, &u, person) {
                    let a = mind_reads(&s, &node, person).unwrap_or_else(|e| panic!("DRIFT ({world}): the default interface of `{}` on `{}` sends {node}, which {e}", spec.name, on.as_str()));
                    let at = format!("DRIFT ({world}): `{}` on `{}` sent {node}, a mind's grammar read {a:?}", spec.name, on.as_str());
                    assert_eq!(a.skill, spec.name, "{at}: another skill");
                    assert_eq!(kind_of(&a.target), want(&t), "{at}: another target");
                    let item = p.item.as_deref().map(|i| if spec.item_arg.contains("technique") { catalog::technique_name(i) } else { i });
                    assert_eq!(a.item.as_deref(), item, "{at}: another item");
                    assert_eq!(a.qty, p.item.as_ref().map(|_| p.qty.unwrap_or(1)), "{at}: another amount");
                    assert_eq!(a.want, p.want, "{at}: another thing asked in return");
                    assert_eq!(a.text, p.text, "{at}: other words");
                    checked += 1;
                }
                // Every choice a picks list names is one the spec takes.
                for pk in &u.picks {
                    assert!(pk.fits(spec), "DRIFT ({world}): `{}` picks {pk:?}, which its spec does not take", spec.name);
                }
            }
            assert!(checked > 500, "{world}: {checked} acts");
        });
    }
}

#[test]
fn a_drifted_interface_is_caught() {
    // The test above fails loudly when a player's act would differ from a mind's: an item sent
    // to a skill that takes none is dropped by the grammar, and a skill without a target sent
    // one keeps it only as an aim.
    let sp = species();
    let person = &sp["person"];
    let s = island();
    catalog::scoped(s.skills().clone(), || {
        let node = act_node("rest", &ActTarget::Me, &Picked { item: Some("wood".into()), ..Default::default() });
        let a = mind_reads(&s, &node, person).unwrap();
        assert_ne!(a.item.as_deref(), Some("wood"), "the grammar drops what the spec does not take");
        assert!(mind_reads(&s, &act_node("give", &ActTarget::Me, &Picked { item: Some("wood".into()), ..Default::default() }), person).is_err(), "a target the spec needs");
        assert!(mind_reads(&s, &act_node("no_such_skill", &ActTarget::Me, &Picked::default()), person).is_err());
    });
}

// ---- anti-drift (b): one filter for players and minds ------------------------------------------

/// The skills a mind's reference lists (`- name(args): ...`).
fn listed_names(help: &str) -> Vec<String> {
    help.lines().filter_map(|l| l.strip_prefix("- ")).map(|l| l.split('(').next().unwrap().to_string()).collect()
}

#[test]
fn players_and_minds_are_offered_the_same_skills() {
    let sp = species();
    for (world, s) in worlds() {
        let names = |v: Vec<&crate::catalog::SkillSpec>| v.into_iter().map(|k| k.name.clone()).collect::<Vec<_>>();
        // A person as the catalog lists one, and each species.
        assert_eq!(listed_names(&catalog::skills_help_of(s.skills())), names(offered(s.skills(), None)), "DRIFT ({world}): the mind's reference for people is not `offered`");
        for (kind, body) in &sp {
            let o = names(offered(s.skills(), Some(body)));
            assert_eq!(listed_names(&crate::species::skills_help_of(body, s.skills())), o, "DRIFT ({world}): the mind's reference for a {kind} is not `offered`");
            // The player's interface has a presentation for every skill offered, and real-time
            // is one definition: what the bar or a graph runs is what an act may not be.
            for k in &o {
                assert!(s.ui(k).is_some(), "{world}: `{k}` offered with no presentation");
                catalog::scoped(s.skills().clone(), || {
                    assert_eq!(real_time(s.skills(), s.shapes(), k), crate::acts::not_an_act(k, s.shapes()).is_some(), "DRIFT ({world}): real-time `{k}`");
                    assert_eq!(real_time(s.skills(), s.shapes(), k), s.shapes().real_time(k));
                });
            }
        }
        // `listed: false` hides from both: graze is the animals'.
        assert!(!names(offered(s.skills(), Some(&sp["person"]))).contains(&"graze".to_string()));
        assert!(!names(offered(s.skills(), None)).contains(&"graze".to_string()));
        assert!(names(offered(s.skills(), Some(&sp["deer"]))).contains(&"graze".to_string()));
    }
    // A world's own unlisted skill is hidden from both too.
    let src = format!("{}\nfn hum_spec() {{ #{{ listed: false, about: \"Hum a tune.\" }} }}\nfn hum_ui() {{ #{{ label: \"Hum\" }} }}\n", include_str!("../../../scripts/skills.rhai"));
    let s = Scripts::new(&src).unwrap();
    assert!(s.ui("hum").is_some_and(|u| u.declared));
    assert!(!listed_names(&catalog::skills_help_of(s.skills())).contains(&"hum".to_string()));
    assert!(!offered(s.skills(), Some(&sp["person"])).iter().any(|k| k.name == "hum"));
}

/// A body that has some of everything, beside a campfire, by day.
fn facts(s: &Scripts) -> SkillCtx {
    let inv: Vec<(String, u32)> = catalog::item_names().into_iter().map(|i| (i, 3)).collect();
    let actor = ActorFacts { id: 1, kind: "person".into(), stage: "adult".into(), age: 30.0, hp: 80.0, hunger: 60.0, energy: 70.0, near_fire: true, terrain: "grass".into(), inv, knows: catalog::technique_names(), ..Default::default() };
    let _ = s;
    SkillCtx { actor, hour: 12.0, season: "summer".into(), roll: 0.5, ..Default::default() }
}

fn target_facts(t: &Kind) -> TargetFacts {
    match t {
        Kind::Id(i) => TargetFacts { class: "creature".into(), id: *i as u64, kind: "person".into(), stage: "adult".into(), hp: 60.0, max_hp: 100.0, alive: true, dist: 1.0, ..Default::default() },
        Kind::Nearest(k) => TargetFacts { class: if catalog::is_resource(k) { "resource" } else { "structure" }.into(), kind: k.clone(), amount: 5.0, dist: 1.0, ..Default::default() },
        Kind::At | Kind::None => TargetFacts { class: "none".into(), ..Default::default() },
    }
}

#[test]
fn the_same_facts_allow_the_same_acts_to_both() {
    // For one body and the same facts, the rules' check gives a player's act (as the interface
    // built it) and the act a mind's grammar reads from it the same answer.
    let sp = species();
    let person = &sp["person"];
    for (world, s) in worlds() {
        catalog::scoped(s.skills().clone(), || {
            let base = facts(&s);
            let (mut allowed, mut refused) = (0, 0);
            for spec in offered(s.skills(), Some(person)) {
                let u = s.ui_default(&spec.name).unwrap();
                for (_, t, p, node) in player_acts(&s, &u, person) {
                    let player = SkillCtx {
                        skill: spec.name.clone(),
                        target: target_facts(&want(&t)),
                        item: p.item.clone().unwrap_or_default(),
                        qty: p.item.as_ref().map_or(0, |_| p.qty.unwrap_or(1)),
                        want: p.want.clone().unwrap_or_default(),
                        want_qty: p.want.as_ref().map_or(0, |_| 1),
                        text: p.text.clone().unwrap_or_default(),
                        ..base.clone()
                    };
                    let a = mind_reads(&s, &node, person).unwrap();
                    let mind = SkillCtx {
                        skill: a.skill.clone(),
                        target: target_facts(&kind_of(&a.target)),
                        item: a.item.clone().unwrap_or_default(),
                        qty: a.qty.unwrap_or(0),
                        want: a.want.clone().unwrap_or_default(),
                        want_qty: a.want_qty.unwrap_or(0),
                        text: a.text.clone().unwrap_or_default(),
                        ..base.clone()
                    };
                    let (x, y) = (s.check(&spec.name, &player), s.check(&a.skill, &mind));
                    assert_eq!(x, y, "DRIFT ({world}): `{}` {node}: the player's act and the mind's are checked differently", spec.name);
                    if x.is_ok() {
                        allowed += 1;
                    } else {
                        refused += 1;
                    }
                }
            }
            assert!(allowed > 50 && refused > 50, "{world}: allowed {allowed}, refused {refused}: the facts exercise both answers");
        });
    }
}

// ---- reading and install -----------------------------------------------------------------------

fn with(extra: &str) -> Scripts {
    Scripts::new(&format!("{}\n{extra}\n", include_str!("../../../scripts/skills.rhai"))).expect("compiles: declarations never fail the compile")
}

#[test]
fn the_shipped_worlds_install_with_their_declarations() {
    for (world, s) in worlds() {
        assert!(s.ui_errors().is_empty(), "{world}: {:?}", s.ui_errors());
        s.validate().unwrap_or_else(|e| panic!("{world}: {e}"));
    }
}

#[test]
fn a_bad_declaration_is_logged_by_a_client_and_refused_at_install() {
    let cases: &[(&str, &str)] = &[
        ("fn block_ui() { #{ slot: 1 } }", "block_ui: unknown trait `slot` (traits are label, on, place, order"),
        ("fn bowshot_ui() { #{ look: #{ icon: \"axe\" } } }", "`look.icon` is one of sword, bow"),
        ("fn rest_ui() { #{ on: \"person\" } }", "`person` needs a spec with `target: true`"),
        ("fn rest_ui() { #{ picks: [\"qty\"] } }", "`picks: qty` needs `qty` in the spec's args"),
        ("fn juggle_ui() { #{ label: \"Juggle\" } }", "`juggle` is not a skill"),
        ("fn attack_ui() { #{ on: \"bar\" } }", "must be in `skill_bar()`"),
        ("fn heal_ui() { #{ place: \"primary\" } }\nfn block_ui() { #{ place: \"primary\" } }", "heal_ui: the bar place `primary` is already `block`'s"),
        ("fn build_ui() { #{ detail: \"no_such_fn\" } }", "`detail` names a function of one name"),
        ("fn build_ui() { #{ detail: \"num\" } }\nfn num(x) { 3 }", "must return words"),
        ("fn wave_ui() { #{ look: #{ clip: \"work\" } } }", "contradicts `wave_shows()`, whose look is `gesture`"),
        ("fn draw_spec() { #{ about: \"Draw.\" } }\nfn draw_ui() { #{ on: \"bar\", place: \"weapon\", toggles: \"drawn\" } }", "`toggles` names nothing yet"),
        ("fn rest_ui() { #{ input: \"aim_point\" } }", "needs a combat aim of `point`"),
        ("fn rest_ui() { #{ pin: true } }", "`pin` shows a button in the person window"),
        ("fn give_ui() { #{ drag: \"ground\" } }", "`drag` is `person` or `thing`"),
        ("fn rest_ui() { #{ alias: \"/r\" } }", "`alias` is for a way of speaking"),
        ("fn rest_ui() { #{ running: #{ show: \"spin\" } } }", "`running.show` is one of windup"),
    ];
    for (src, want) in cases {
        let s = with(src);
        assert!(s.ui_errors().iter().any(|e| e.contains(want)), "{src}: {:?} lacks {want:?}", s.ui_errors());
        let e = s.validate().expect_err(src);
        assert!(e.starts_with("install refused: ") && e.contains(want.split(':').next().unwrap()), "{src}: {e}");
    }
    // A field that is wrong keeps its default, and the rest of the declaration holds; a declared
    // primary comes before the one placed by aim.
    let s = with("fn heal_ui() { #{ place: \"primary\", label: \"Mend\", look: #{ icon: \"axe\" } } }");
    let u = s.ui("heal").unwrap();
    assert_eq!((u.label.as_str(), u.look.icon, u.place), ("Mend", Some("heal"), Some(BarPlace::Primary)));
    let b = bar_places(&s);
    assert_eq!((b.primary.as_deref(), b.extra.clone()), (Some("heal"), vec!["strike".to_string()]));
}

#[test]
fn an_item_names_its_icon_and_group_from_the_vocabulary() {
    let shipped = include_str!("../../../scripts/skills.rhai");
    let s = Scripts::new(&crate::floors::compose(shipped, "fn items() { base_items() + [#{ name: \"glass\", icon: \"vessel\", group: \"material\" }, #{ name: \"slag\", icon: \"lump\" }] }").unwrap()).unwrap();
    assert_eq!(s.ui_errors().len(), 1, "{:?}", s.ui_errors());
    assert!(s.ui_errors()[0].contains("the `icon` of `slag` is one of berries"));
}

#[test]
fn declarations_place_and_present() {
    let s = with(
        "fn firebolt_ui() { #{ label: \"Fire bolt\", place: \"skill\", order: 2, marker: \"circle\", unready: \"toggle\", look: #{ icon: \"fire\", clip: \"cast\", effect: \"bolt\" }, running: #{ show: \"windup\" }, refused: \"grey\" } }\n\
         fn block_ui() { #{ place: \"skill\", order: 0 } }\n\
         fn heal_ui() { #{ place: \"skill\", order: 1 } }\n\
         fn give_ui() { #{ label: \"Give\", on: [\"person\", \"item\"], picks: [\"person\", \"item\", \"qty\"], drag: \"person\", pin: true, order: 0, look: #{ icon: \"give\", clip: \"hand\" }, refused: \"note\" } }\n\
         fn make_ui() { #{ on: \"thing\", picks: [\"item\"], choose: \"grid\", detail: \"made_how\", running: #{ show: \"progress\", text: \"Making {item}\" }, look: #{ icon: \"hammer\", clip: \"work\" } } }",
    );
    assert!(s.ui_errors().is_empty(), "{:?}", s.ui_errors());
    s.validate().unwrap();
    let b = bar_places(&s);
    assert_eq!(b.skill, vec![Some("block".into()), Some("heal".into()), Some("firebolt".into())]);
    let f = s.ui("firebolt").unwrap();
    assert_eq!((f.label.as_str(), f.marker, f.unready, f.refused_at(On::Bar)), ("Fire bolt", Marker::Circle, Unready::Toggle, Refused::Grey));
    let g = s.ui("give").unwrap();
    assert_eq!((g.on.clone(), g.drag, g.pin, g.picks.clone()), (vec![On::Person, On::Item], Some(On::Person), true, vec![Pick::Person, Pick::Item, Pick::Qty]));
    let m = s.ui("make").unwrap();
    assert_eq!((m.choose, m.detail.as_deref(), m.running.show, m.running.text.as_str()), (Choose::Grid, Some("made_how"), RunShow::Progress, "Making {item}"));
}

#[test]
fn a_way_of_speaking_is_presented_in_the_box() {
    let s = with("fn whisper_speech() { #{ label: \"Whisper\" } }\nfn whisper_ui() { #{ on: \"box\", alias: \"/w\", to_label: \"Whisper to {b}\", bubble: \"hushed\", rows: #{ whisper: \"line\", whispered: \"dots\" } } }");
    assert!(s.ui_errors().is_empty(), "{:?}", s.ui_errors());
    let w = s.ui("whisper").unwrap();
    let way = w.way.as_ref().unwrap();
    assert_eq!((w.on.clone(), way.alias.as_deref(), way.bubble, way.rows.get("whispered").copied()), (vec![On::Box], Some("/w"), Some(Bubble::Hushed), Some(Row::Dots)));
    let s = with("fn whisper_speech() { #{} }\nfn whisper_ui() { #{ label: \"W\", on: \"bar\" } }");
    assert!(s.ui_errors().iter().any(|e| e.contains("a way's `label` is set by `whisper_speech()`")));
    assert!(s.ui_errors().iter().any(|e| e.contains("text box")));
}

#[test]
fn the_vocabulary_round_trips() {
    for &p in On::ALL {
        assert_eq!(On::parse(p.as_str()), Some(p));
    }
    assert_eq!(PLACES.len(), On::ALL.len());
    for &p in BarPlace::ALL {
        assert_eq!(BarPlace::parse(p.as_str()), Some(p));
    }
    assert_eq!(Input::parse("aim_point"), Some(Input::AimPoint));
    assert_eq!(label_of("fire_bolt"), "Fire bolt");
    assert_eq!(label_of(""), "");
    // A player's acts are written as a mind writes them.
    assert_eq!(act_node("give", &ActTarget::Creature(4), &Picked { item: Some("fish".into()), ..Default::default() }), json!({"do": "give", "target": {"id": 4}, "item": "fish", "qty": 1}));
    assert_eq!(act_node("gather", &ActTarget::Thing { kind: "tree".into(), at: Some([1.0, 2.0]) }, &Picked::default()), json!({"seq": [{"do": "goto", "target": {"at": [1.0, 2.0]}}, {"do": "gather", "target": {"nearest": "tree"}}]}));
    assert_eq!(bar_act("heal", Aim::SelfOrAlly, None, [0.0, 0.0]), json!({"do": "heal"}));
}

// ---- no skill names in Rust interface code ---------------------------------------------------

/// Every skill name of the shipped and Cullet scripts.
fn skill_names() -> std::collections::BTreeSet<String> {
    worlds().iter().flat_map(|(_, s)| s.skills().names().map(String::from).chain(s.shapes().names().map(String::from)).collect::<Vec<_>>()).collect()
}

/// The string literals of Rust source, outside comments.
fn literals(src: &str) -> Vec<String> {
    let mut out = Vec::new();
    for line in src.lines() {
        let code = line.split("//").next().unwrap_or("");
        let mut parts = code.split('"');
        parts.next();
        while let Some(lit) = parts.next() {
            out.push(lit.to_string());
            parts.next();
        }
    }
    out
}

/// A source with its vocabulary declarations (the `vocab!` blocks and the name lists) taken
/// out: a vocabulary word may be spelt like a skill (the `throw` clip family, the `rest` look).
fn without_vocabulary(src: &str) -> String {
    let mut out = String::new();
    let mut depth = 0i32;
    for line in src.lines() {
        let t = line.trim_start();
        // A named word of the vocabulary (`const ICON_FIRE: &str = "fire";`).
        if depth == 0 && (t.starts_with("const ") || t.starts_with("pub const ")) && t.contains(": &str = \"") {
            continue;
        }
        if depth == 0 && (t.starts_with("vocab! {") || t.starts_with("pub const") && t.contains("&[&str]")) {
            depth = 1;
            if t.starts_with("pub const") {
                depth = 0;
                continue;
            }
            continue;
        }
        if depth > 0 {
            depth += line.matches('{').count() as i32 - line.matches('}').count() as i32;
            continue;
        }
        out.push_str(line);
        out.push('\n');
    }
    out
}

/// The grammar's own words that are spelt like a skill: the walk a mind writes before an act
/// toward a thing that is not the nearest of its kind (`{"seq": [{"do": "goto", ...}, act]}`).
/// And the species' signals: a body offered `signal` must have signals to make
/// (`Species::signals`), a rule moved unchanged from `species::skills_help_of` so minds' references
/// stay byte for byte.
const GRAMMAR: &[&str] = &["goto", "signal"];

#[test]
fn no_skill_is_named_in_the_rules_interface_code() {
    let names = skill_names();
    assert!(names.contains("strike") && names.contains("give"));
    for (file, src) in [("rules/src/ui.rs", include_str!("../ui.rs")), ("rules/src/script/ui.rs", include_str!("../script/ui.rs"))] {
        let named: Vec<String> = literals(&without_vocabulary(src)).into_iter().filter(|l| names.contains(l) && !GRAMMAR.contains(&l.as_str())).collect();
        assert!(named.is_empty(), "DRIFT: {file} names the skills {named:?}: presentation comes from a skill's spec, shape and `_ui()`, never its name");
    }
}

/// Skill names the game client's code spells today, by file: what INTERFACE.md steps 2–4 move
/// into declarations. The list may only shrink: a file that names a skill it did not name
/// before fails, and a name a file stopped spelling must be struck from here.
/// Some are ordinary words, not skills (`clear` weather, a gate's `close`); they stay listed.
const CLIENT_NAMES_TODAY: &[(&str, &[&str])] = &[
    ("characters.rs", &["build"]),
    ("combat.rs", &["attack", "block", "bowshot", "dodge", "firebolt", "heal", "jump", "shoot", "strike", "throw"]),
    ("envs.rs", &["close"]),
    ("jump.rs", &["jump"]),
    ("live.rs", &["dodge", "goto", "open", "wait"]),
    ("lookdev.rs", &["found"]),
    ("net.rs", &["join"]),
    ("route.rs", &["host"]),
    ("talk.rs", &["face"]),
    ("town.rs", &["appraise", "cook", "craft", "eat", "face", "gather", "graze", "keep", "nod", "plant", "play", "read", "rest", "sleep", "step_aside", "store", "take", "tend", "wave"]),
    ("ui/icons.rs", &["plant"]),
    ("ui/people.rs", &["appraise", "give", "offer", "wave"]),
    ("ui/settings.rs", &["play"]),
    ("ui/verbs.rs", &["accept", "appraise", "give", "nod", "offer", "offer_terms", "read", "teach", "wave", "write"]),
    ("ui/wood.rs", &["clear"]),
    ("verbs.rs", &["appraise", "close", "give", "goto", "offer", "wave"]),
    ("weather.rs", &["clear"]),
    ("world.rs", &["store"]),
];

#[test]
fn the_game_client_names_no_new_skills() {
    let names = skill_names();
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../game/src");
    let Ok(_) = std::fs::metadata(&root) else { return };
    let mut files = Vec::new();
    let mut dirs = vec![root.clone()];
    while let Some(d) = dirs.pop() {
        for e in std::fs::read_dir(&d).unwrap().flatten() {
            let p = e.path();
            if p.is_dir() {
                dirs.push(p);
            } else if p.extension().is_some_and(|x| x == "rs") {
                files.push(p);
            }
        }
    }
    files.sort();
    let mut now: Vec<(String, Vec<String>)> = Vec::new();
    for f in files {
        let src = std::fs::read_to_string(&f).unwrap();
        // Only the code a client ships: its tests may name skills.
        let src = src.split("#[cfg(test)]").next().unwrap_or("");
        let mut named: Vec<String> = literals(src).into_iter().filter(|l| names.contains(l)).collect();
        named.sort();
        named.dedup();
        if !named.is_empty() {
            now.push((f.strip_prefix(&root).unwrap().to_string_lossy().into_owned(), named));
        }
    }
    let frozen: Vec<(String, Vec<String>)> = CLIENT_NAMES_TODAY.iter().map(|(f, n)| (f.to_string(), n.iter().map(|x| x.to_string()).collect())).collect();
    let listing = now.iter().map(|(f, n)| format!("    (\"{f}\", &[{}]),", n.iter().map(|x| format!("\"{x}\"")).collect::<Vec<_>>().join(", "))).collect::<Vec<_>>().join("\n");
    for (f, n) in &now {
        let before = frozen.iter().find(|(g, _)| g == f).map(|(_, m)| m.clone()).unwrap_or_default();
        let new: Vec<&String> = n.iter().filter(|x| !before.contains(x)).collect();
        assert!(new.is_empty(), "DRIFT: game/src/{f} now names the skills {new:?}: present a skill from its `_ui()` and defaults (living_rules::ui), not by name. Today's list:\n{listing}");
    }
    for (f, n) in &frozen {
        let still = now.iter().find(|(g, _)| g == f).map(|(_, m)| m.clone()).unwrap_or_default();
        let gone: Vec<&String> = n.iter().filter(|x| !still.contains(x)).collect();
        assert!(gone.is_empty(), "game/src/{f} no longer names {gone:?}: strike them from CLIENT_NAMES_TODAY. Today's list:\n{listing}");
    }
}

// ---- rules never read the interface -----------------------------------------------------------

/// A script with every `<name>_ui()` taken out.
fn without_ui(src: &str) -> String {
    let mut out = String::new();
    let mut depth = 0i32;
    for line in src.lines() {
        let t = line.trim_start();
        let opens = depth == 0 && t.starts_with("fn ") && t.split('(').next().is_some_and(|h| h.ends_with("_ui"));
        if opens || depth > 0 {
            depth += line.matches('{').count() as i32 - line.matches('}').count() as i32;
            continue;
        }
        out.push_str(line);
        out.push('\n');
    }
    out
}

/// Everything the rules decide that a presentation might be suspected of reaching: the skills and
/// their specs, combat shapes and the bar's skills, what others see, the laws, what each body is
/// offered, what real-time means, how an act parses, and every skill's check on sample facts.
fn rules_of(s: &Scripts) -> String {
    let sp = species();
    let mut out = format!("{:?}\n{:?}\n{:?}\n", s.skills(), s.shapes(), s.shows().iter().collect::<Vec<_>>());
    out += &format!("{:?}\n{:?}\n", s.laws(), s.law_specs());
    out += &format!("{:?}\n", s.validate().map(|_| ()));
    catalog::scoped(s.skills().clone(), || {
        for body in std::iter::once(None).chain(sp.values().map(Some)) {
            out += &format!("{:?}\n", offered(s.skills(), body).iter().map(|k| &k.name).collect::<Vec<_>>());
        }
        out += &crate::catalog::skills_help_of(s.skills());
        let base = facts(s);
        for spec in s.skills().iter() {
            out += &format!("{} {} ", spec.name, real_time(s.skills(), s.shapes(), &spec.name));
            for t in [Kind::None, Kind::Id(7), Kind::Nearest(catalog::resource_names()[0].clone()), Kind::Nearest(catalog::structure_names()[0].clone())] {
                for item in std::iter::once(String::new()).chain(item_choices(spec, &sp["person"]).into_iter().take(4)) {
                    let c = SkillCtx { skill: spec.name.clone(), target: target_facts(&t), item: item.clone(), qty: 1, text: "a few words".into(), ..base.clone() };
                    out += &format!("{:?}{:?}", s.check(&spec.name, &c), s.duration_ms(&spec.name, &c));
                    let node = act_node(&spec.name, &ActTarget::Me, &Picked { item: (!item.is_empty()).then_some(item), ..Default::default() });
                    out += &format!("{:?}", crate::acts::parse(node, Some(&sp["person"]), s.shapes()));
                }
            }
            out.push('\n');
        }
    });
    out
}

#[test]
fn the_rules_are_the_same_without_any_declaration() {
    let shipped = include_str!("../../../scripts/skills.rhai");
    let stripped = without_ui(shipped);
    assert!(stripped.len() < shipped.len() && !stripped.contains("_ui()"), "every declaration is taken out");
    let heavy = format!(
        "{shipped}\n\
         fn firebolt_ui() {{ #{{ label: \"Fire bolt\", place: \"skill\", order: 0, input: \"aim_point\", unready: \"toggle\", refused: \"note\", look: #{{ icon: \"fire\", clip: \"cast\", effect: \"bolt\" }} }} }}\n\
         fn block_ui() {{ #{{ place: \"primary\" }} }}\n\
         fn give_ui() {{ #{{ on: [\"person\", \"item\"], picks: [\"person\", \"item\", \"qty\"], drag: \"person\", pin: true }} }}\n\
         fn make_ui() {{ #{{ on: \"thing\", choose: \"grid\", detail: \"made_how\" }} }}\n\
         fn graze_ui() {{ #{{ on: \"self\", label: \"Graze\" }} }}\n\
         fn rest_ui() {{ #{{ on: [] }} }}\n"
    );
    let pairs = [
        ("island", Scripts::new(shipped).unwrap(), Scripts::new(&stripped).unwrap()),
        ("island, declared heavily", Scripts::new(&heavy).unwrap(), Scripts::new(&without_ui(&heavy)).unwrap()),
        ("cullet", crate::cullet_check::cullet(), Scripts::with_day(&without_ui(&crate::floors::compose(shipped, include_str!("../../../seeds/worlds/cullet/laws.rhai")).unwrap()), crate::cullet_check::CULLET_DAY_MS).unwrap()),
    ];
    for (world, with_ui, without) in pairs {
        assert!(with_ui.ui_specs().any(|u| u.declared) && !without.ui_specs().any(|u| u.declared), "{world}");
        let (a, b) = (rules_of(&with_ui), rules_of(&without));
        if a != b {
            let at = a.lines().zip(b.lines()).position(|(x, y)| x != y).unwrap_or(0);
            panic!("DRIFT ({world}): a `_ui()` declaration changed the rules at line {at}:\n with: {}\n without: {}", a.lines().nth(at).unwrap_or(""), b.lines().nth(at).unwrap_or(""));
        }
    }
}
