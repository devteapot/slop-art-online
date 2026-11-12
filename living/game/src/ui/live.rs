//! The UI's live source: fills the view-model from the authority's rows this client already
//! has (`net.rs` subscriptions) and the displayed scene. Presentation only.
//!
//! Live today:
//! - health and the `energy` need from my `vitals` row, projected along its per-minute rates
//!   (the same formula as the authority's `common::needs`);
//! - status from those needs (hunger, energy, health trend) and `hurt_ms`/`hurt_by`;
//! - names over characters from `character`, positions from the displayed bodies;
//! - speech bubbles and the chat log from my own `experience` rows (`speech`): only what I
//!   heard, since the authority decides earshot (`perceive::speak`); my own lines are echoed;
//! - death from my `character` row (`alive`, `cause`, `born_ms`, `died_ms`);
//! - my known places (`place` rows of my character) on the compass;
//! - on a land world (the island, `live.rs`), nameplates and bubbles over the drawn characters.
//!
//! - combat (docs/COMBAT.md, `combat.rs`): the skill bar from `skill_card` (the rules' bar
//!   order, costs and what each skill needs), `my_readiness` (cooldowns), my inventory and
//!   know-how; others' health band and
//!   move from their `fighter` rows; floating numbers and who saw my death from `my_combat`.
//!
//! - town life (docs/TOWN_LIFE.md, `town.rs`): no nameplate over someone indoors; a brief one
//!   over whoever answered my greeting (my `experience`), and nothing else: what residents do
//!   shows on their bodies, never as labels.
//!
//! - verbs (`verbs.rs`, `ui/verbs.rs`): the F hint, the list of acts, notes of their outcomes,
//!   inventory and know-how, filled by `ui/verbs.rs` after this.

use super::model::*;
use crate::camera::Cam;
use crate::controls::{self, Input, Target};
use crate::net::Net;
use crate::world::Scene;
use bevy::prelude::*;
use living_bindings::*;
use spacetimedb_sdk::Table;
use std::collections::{BTreeMap, HashMap};

/// The character I last played, to notice its death.
#[derive(Default)]
pub struct Last {
    id: Option<u32>,
    dead: Option<u32>,
    /// How I last perceived each creature (its label). A death takes my perceived rows away in
    /// the same update as the death itself, so the death screen names my killer and the
    /// witnesses from this, as my character saw them, not from the authority's cause text.
    labels: HashMap<u32, String>,
    /// When each creature was last among those I perceive (authority ms), and when I noticed my
    /// death: a killer is named only if my character saw them just before ([`KILLER_SEEN_MS`]);
    /// a missile's unseen shooter is not, whatever id the death row carries.
    seen_ms: HashMap<u32, f64>,
    died_ms: f64,
    /// Speech I heard, by experience id: `my_experience` holds only my newest lines (the
    /// authority's window, `frame::LINES_SHOWN`), so the log keeps what it has received.
    heard: BTreeMap<u64, Experience>,
    /// The connection has been live: a later loss is shown.
    was_live: bool,
}

#[allow(clippy::too_many_arguments)]
pub fn fill(mut model: ResMut<HudModel>, mut out: ResMut<Outbox>, mut net: NonSendMut<Net>, scene: NonSend<Scene>, cam: Res<Cam>, mut input: ResMut<Input>, target: Res<Target>, size: Res<crate::bodies::MySize>, sight: Res<crate::sight::Sight>, island: Option<Res<crate::island::Island>>, live: Res<crate::live::Live>, combat: Res<crate::combat::Combat>, cards: Res<crate::combat::Cards>, town: Res<crate::town::Town>, (talk, looks, pick, rules, clock): (Option<Res<crate::talk::Talk>>, Res<crate::looks::Looks>, Res<crate::pick::Pick>, NonSend<crate::verbs::Rules>, Res<crate::daylight::Clock>), mut last: Local<Last>) {
    let now_ms = scene.now_ms;
    let now = now_ms / 1000.0;
    model.shown = true;
    model.now = now;
    model.hint = None;

    // Requests from the UI.
    // In the way the box has (the world's ways, `speech_card`), else plainly.
    let way = talk.as_ref().and_then(|t| t.card.as_ref()).map(|c| c.name.clone());
    for (line, to) in out.say.drain(..) {
        if controls::say(&net, &line, to, way.as_deref()) {
            input.said.push((now_ms as u64, line.trim().to_string()));
        }
    }
    if std::mem::take(&mut out.rejoin) {
        last.dead = None;
        net.rejoin();
    }

    // Once live, any other state of the connection is a loss: say so while it reconnects.
    if net.status == crate::net::Status::Live {
        last.was_live = true;
    }
    let link = (last.was_live && net.status != crate::net::Status::Live).then(|| match net.status {
        crate::net::Status::Offline => "Connection lost · reconnecting…".to_string(),
        _ => "Reconnecting…".to_string(),
    });
    let Some(conn) = net.conn.as_ref() else {
        *model = HudModel { shown: true, now, link, ..default() };
        return;
    };
    model.link = link;
    // Who I perceive, as I perceive them (name or label, health as I can tell it), and my own
    // characters (the dead one stays for the death screen).
    let chars: HashMap<u32, SeenCharacter> = conn.db.seen_characters().iter().map(|c| (c.id, c)).collect();
    let mine: HashMap<u32, Character> = conn.db.my_characters().iter().map(|c| (c.id, c)).collect();
    if last.labels.len() > 4096 {
        last.labels.clear();
    }
    if last.seen_ms.len() > 4096 {
        last.seen_ms.clear();
    }
    for c in chars.values() {
        if last.labels.get(&c.id) != Some(&c.label) {
            last.labels.insert(c.id, c.label.clone());
        }
        last.seen_ms.insert(c.id, now_ms);
    }

    // Death: the character I played is no longer alive.
    if let Some(prev) = last.id {
        if net.my_id.is_none() && mine.get(&prev).is_some_and(|c| !c.alive) {
            if last.dead != Some(prev) {
                last.died_ms = now_ms;
            }
            last.dead = Some(prev);
        }
    }
    if net.my_id.is_some() {
        last.id = net.my_id;
        last.dead = None;
    }
    // Named as everywhere else (`Looks`: a known name, a stranger by their colours, someone too
    // far away to make out); the authority's last label kept at frame rate covers the moment
    // before `Looks` (4 Hz) has them.
    let perceived = |id: u32| looks.of(id).map(String::from).or_else(|| last.labels.get(&id).cloned());
    // The death row (`my_act_outcomes`, kind `death`): its code and, killed, the killer's id.
    let died = conn.db.my_act_outcomes().iter().filter(|o| o.kind == "death").max_by_key(|o| o.at_ms);
    // The killer only if my character saw them just before it died (id 0 is no one).
    let saw_then = |id: &u32| *id != 0 && last.seen_ms.get(id).is_some_and(|t| *t >= last.died_ms - KILLER_SEEN_MS);
    model.death = last.dead.and_then(|id| mine.get(&id)).map(|c| death(c, died.as_ref().filter(|o| o.other != 0).map(|o| o.other).or(combat.killer).filter(saw_then).and_then(perceived), died.as_ref())).map(|mut d| {
        // Who saw it, as my character perceived (the authority's `WITNESS` rows).
        if !combat.witnesses.is_empty() {
            d.witnesses = Some(combat.witnesses.iter().map(|w| perceived(*w).unwrap_or_else(|| "someone".to_string())).collect());
        } else if combat.killer.is_some() {
            d.witnesses = Some(Vec::new());
        }
        d
    });

    let me = net.my_id;
    let my_pos = target.0;
    let vit = me.and_then(|id| conn.db.my_vitals().id().find(&id));
    model.me = me.zip(vit.as_ref()).map(|(id, v)| {
        let m = (now_ms - v.at_ms as f64).max(0.0) as f32 / 60_000.0;
        let hp = (v.hp + v.hp_rate * m).clamp(0.0, v.max_hp);
        let hunger = (v.hunger + v.hunger_rate * m).clamp(0.0, 100.0);
        let energy = (v.energy + v.energy_rate * m).clamp(0.0, 100.0);
        let since_hurt = (now_ms - v.hurt_ms as f64) as f32 / 1000.0;
        // The bars and pills from the world's `meters()` and `status_of` over my vitals row read
        // generically (no column named here): a new vital is one column and one meters row.
        let (meters, statuses, pools) = match (rules.scripts.as_ref(), mine.get(&id)) {
            (Some(sc), Some(c)) => my_body(sc, v, &c.kind, crate::verbs::stage_name(c.stage), sc.is_night(clock.hour()), now_ms),
            _ => (Vec::new(), Vec::new(), Vec::new()),
        };
        let name = mine.get(&id).map_or(net.name.clone(), |c| c.name.clone());
        let _ = hunger;
        Me { name, hp, max_hp: v.max_hp, energy, max_energy: 100.0, meters, statuses, pools, hurt: if v.hurt_ms > 0 { (1.0 - since_hurt / 0.8).clamp(0.0, 1.0) } else { 0.0 } }
    });
    let hostile = |id: u32| me.is_some_and(|m| crate::combat::hostile_to_me(conn, id, m, now_ms));
    // Others' health as anyone sees it: the band of their `fighter` row, if they have fought.
    // Exact where I perceive it exactly (my look at them, an appraisal), else the band.
    let band = |id: u32| match chars.get(&id).filter(|c| c.hp >= 0.0 && c.max_hp > 0.0) {
        Some(c) => Some((c.hp / c.max_hp).clamp(0.0, 1.0)),
        None => crate::net::find_fighter(conn, id).filter(|f| f.band <= 4).map(|f| living_rules::combat::band_fraction(f.band)),
    };
    let busy = |id: u32| crate::net::find_fighter(conn, id).is_some_and(|f| f.act != 0 && (now_ms as u64) < f.until_ms);

    // What I heard.
    last.heard.retain(|_, e| Some(e.observer) == me);
    if let Some(id) = me {
        last.heard.extend(conn.db.my_experience().iter().filter(|e| e.observer == id && e.kind == "speech").map(|e| (e.id, e)));
    }
    while last.heard.len() > 200 {
        last.heard.pop_first();
    }
    let mut heard: Vec<Experience> = last.heard.values().cloned().collect();
    heard.sort_by_key(|e| e.at_ms);
    let talking: Vec<u32> = heard.iter().filter(|e| now_ms - (e.at_ms as f64) < 8_000.0).map(|e| e.subject).collect();
    // How I name them: the rules' name, else their looks (`looks.rs`).
    let name_of = |id: u32| looks.of(id).map(String::from).or_else(|| chars.get(&id).map(|c| c.label.clone())).unwrap_or_else(|| "Someone".to_string());
    let mut log: Vec<LogLine> = heard
        .iter()
        .map(|e| LogLine { at: e.at_ms as f64 / 1000.0, who: name_of(e.subject), text: quoted(&e.text).to_string(), kind: if e.text.contains(" said to you:") { LogKind::ToMe } else { LogKind::Heard } })
        .collect();
    let my_name = model.me.as_ref().map_or(net.name.clone(), |m| m.name.clone());
    log.extend(input.said.iter().map(|(t, text)| LogLine { at: *t as f64 / 1000.0, who: my_name.clone(), text: text.clone(), kind: LogKind::Mine }));
    log.sort_by(|a, b| a.at.total_cmp(&b.at));
    let skip = log.len().saturating_sub(40);
    model.log = log.into_iter().skip(skip).collect();

    // Characters around me.
    // On the island, over the drawn character (its recipe height) standing on the island's
    // ground; on tile worlds, over the tile ground.
    let head = |id: u32, p: Vec2, kind: &str| match &island {
        Some(i) => Vec3::new(p.x, i.height(p.x, p.y), p.y) + Vec3::Y * (live.heights.get(&id).copied().unwrap_or(1.75) * 1.1),
        None => {
            let lift = if Some(id) == me { 1.95 * size.0 } else if kind == "person" { 1.95 } else { 1.25 };
            scene.at3(p.x, p.y) + Vec3::Y * lift
        }
    };
    let mut actors = Vec::new();
    for (id, (p, _)) in &scene.shown {
        let Some(c) = chars.get(id) else { continue };
        // The client-side sight mock (F1): nothing over those out of sight, or indoors.
        if Some(*id) == me || town.hidden(*id) || my_pos.is_some_and(|m| !sight.shows(Vec2::new(m.x, m.z), *p)) {
            continue;
        }
        let distance = my_pos.map_or(0.0, |m| Vec2::new(m.x, m.z).distance(*p));
        if distance > 40.0 {
            continue;
        }
        let hostile = hostile(*id);
        actors.push(Actor {
            id: *id as u64,
            // Plates and hover: someone too far to make out by the colours drawn (`Looks::plate`).
            name: looks.plate(*id).map(String::from).unwrap_or_else(|| name_of(*id)),
            head: head(*id, *p, &c.kind),
            distance,
            // The one under the cursor (`pick.rs`): the same pick Enter and combat's target use.
            hovered: pick.under == Some(*id),
            targeted: false,
            talking: talking.contains(id),
            greeted: town.answered.contains_key(id),
            stance: if hostile { Stance::Hostile } else { Stance::Neutral },
            hp: band(*id),
            // The projection carries exact health for others only while an appraisal holds.
            exact: (c.hp >= 0.0 && c.max_hp > 0.0).then_some((c.hp, c.max_hp)),
            kind_person: c.kind == "person",
        });
    }
    // Targeted skills go to the creature under the cursor, else nearest it (`combat.rs` picks it);
    // while the text box is open, the target shown is whom it speaks to (`talk.rs`).
    let speaking_to = talk.as_ref().filter(|_| input.chat_open).and_then(|t| t.to);
    let target_id = speaking_to.or(combat.target);
    for a in &mut actors {
        a.targeted = Some(a.id as u32) == target_id;
    }
    model.target = target_id.and_then(|id| {
        let c = chars.get(&id)?;
        let a = actors.iter().find(|a| a.id == id as u64)?;
        let doing = if a.stance == Stance::Hostile || busy(id) {
            Some(StatusKind::InCombat)
        } else if a.talking {
            Some(StatusKind::Talking)
        } else {
            None
        };
        // Capitalised, as everywhere a label starts a line (talk-1 left the target's lower case).
        // The target plate names them as their nameplate does (someone too far: by colours drawn).
        let name = super::label(&if c.kind != "person" && !c.name.is_empty() { format!("{} the {}", c.name, c.kind) } else { a.name.clone() });
        Some(TargetInfo { name, doing, hp: band(id), stance: a.stance, distance: a.distance })
    });

    // Bubbles: lines heard within their lifetime, and my own last line.
    let mut bubbles = Vec::new();
    for e in heard.iter().rev() {
        let text = quoted(&e.text).to_string();
        let age = ((now_ms - e.at_ms as f64) / 1000.0) as f32;
        let life = bubble_life(&text);
        if age > life || bubbles.iter().any(|b: &Bubble| b.speaker == e.subject as u64) {
            continue;
        }
        let Some((p, _)) = scene.shown.get(&e.subject) else { continue };
        let kind = chars.get(&e.subject).map_or("person", |c| c.kind.as_str());
        // Over their head, as their plate names them (someone too far: by the colours drawn).
        let name = looks.plate(e.subject).map(String::from).unwrap_or_else(|| name_of(e.subject));
        bubbles.push(Bubble { speaker: e.subject as u64, name, text, head: head(e.subject, *p, kind), age, life, mine: false });
    }
    if let (Some(id), Some((t, text))) = (me, input.said.last()) {
        let age = ((now_ms - *t as f64) / 1000.0) as f32;
        if let Some((p, _)) = scene.shown.get(&id).filter(|_| age < bubble_life(text)) {
            bubbles.push(Bubble { speaker: id as u64, name: my_name.clone(), text: text.clone(), head: head(id, *p, "person"), age, life: bubble_life(text), mine: true });
        }
    }
    model.bubbles = bubbles;
    model.actors = actors;

    // Skills: every skill on the rules' bar, with live cooldowns, a held guard, what the rules
    // require (costs from `skill_card`) and what it spends that I carry. The cluster puts them
    // on their places (`ui/cluster.rs`, `combat::Roles`).
    model.skills = match (me, model.me.as_ref()) {
        (Some(id), Some(m)) => {
            let inv = |item: &str| conn.db.my_inventory().iter().filter(|r| r.owner == id as u64 && r.item == item).map(|r| r.qty).sum::<u32>();
            let knows = |t: &str| conn.db.my_know_how().iter().any(|k| k.actor == id && k.technique == t);
            let me_f = crate::net::find_fighter(conn, id);
            let energy = m.energy;
            let mut bar: Vec<&SkillCard> = cards.all.iter().filter(|c| c.slot != u8::MAX).collect();
            bar.sort_by_key(|c| c.slot);
            bar.into_iter()
                .map(|card| {
                    let state = (|| {
                        // A held guard: raised now (my fighter row says so) or my key is down.
                        if card.aim == "facing" && (combat.guarding || me_f.as_ref().is_some_and(|f| f.act == card.code && (now_ms as u64) < f.until_ms)) {
                            return SkillState::Active;
                        }
                        if let Some((left, total)) = crate::combat::cooldown(conn, id, &card.skill, now_ms) {
                            return SkillState::Cooldown { left, total };
                        }
                        let (mut items, mut techniques) = crate::combat::needs(card);
                        if let Some(item) = items.find(|i| inv(i) == 0) {
                            return SkillState::Unavailable(missing(item));
                        }
                        if techniques.any(|t| !knows(t)) {
                            return SkillState::Unavailable("Unknown".into());
                        }
                        // Its pool (stamina-1: `skill_card.pool`, a field a meter shows) short of its
                        // cost: greyed in the pool's word ("Not enough mana"). A hint only: a press
                        // still goes, and the authority decides.
                        if let Some(p) = m.pools.iter().find(|p| !card.pool.is_empty() && p.name == card.pool) {
                            if p.value < card.cost {
                                // The rules' own words for a short pool (`short_of`: "out of
                                // breath", "not enough mana"), else the pool's label.
                                let why = rules.scripts.as_ref().and_then(|sc| sc.text_of("short_of", &card.pool)).unwrap_or_else(|| format!("not enough {}", p.label.to_lowercase()));
                                return SkillState::Unavailable(crate::ui::label(&why));
                            }
                        }
                        SkillState::Ready
                    })();
                    // What it spends: the last item it needs (a bow and arrows: the arrows).
                    let count = crate::combat::needs(card).0.last().map(inv).filter(|_| crate::combat::needs(card).0.count() > 1);
                    Skill { key: Key::Lmb, icon: crate::combat::look(card).icon, state, name: card.skill.clone(), cost: card.cost, count }
                })
                .collect()
        }
        _ => Vec::new(),
    };

    // Floating numbers over whoever they happened to.
    model.numbers = combat
        .numbers
        .iter()
        .map(|n| {
            let at = Vec3::new(n.at.x, island.as_ref().map_or(0.0, |i| i.height(n.at.x, n.at.y)), n.at.y) + Vec3::Y * 2.0;
            let kind = match n.kind {
                crate::combat::NumberKind::Dealt => NumberKind::Dealt,
                crate::combat::NumberKind::Taken => NumberKind::Taken,
                crate::combat::NumberKind::Healed => NumberKind::Healed,
                crate::combat::NumberKind::Blocked => NumberKind::Blocked,
            };
            FloatNumber { at, amount: n.amount, kind, age: ((now_ms - n.born_ms) / 1000.0) as f32 }
        })
        .collect();

    // Compass: my known places, and the nearest of them names where I am (`ui/top.rs`).
    let places: Vec<Place> = me.map(|id| conn.db.my_places().iter().filter(|p| p.actor == id).collect()).unwrap_or_default();
    let here = my_pos.map(|p| Vec2::new(p.x, p.z));
    let place = here.and_then(|h| places.iter().map(|p| (p, Vec2::new(p.x, p.y).distance(h))).filter(|(p, d)| *d <= super::top::PLACE_M && !p.name.trim().is_empty()).min_by(|a, b| a.1.total_cmp(&b.1)).map(|(p, _)| super::label(&super::wood::readable(p.name.trim()))));
    model.map = MapInfo { me: here, facing: input.facing(), yaw: cam.shown_yaw, pois: places.iter().map(|p| Poi { kind: PoiKind::Place, at: Vec2::new(p.x, p.y) }).collect(), place };
}

/// My body as the world's rules read it: the bars (`meters()`, the shown ones in order, each value
/// moved along `<field>_rate` per minute since `<field>_from_ms` or the row's `at_ms`, held
/// within its max) and the pills (`status_of` over the same facts the authority and the minds
/// build). The row is read by field name, generically.
fn my_body(sc: &living_rules::script::Scripts, row: &impl spacetimedb_sdk::__codegen::__sats::ser::Serialize, kind: &str, stage: &str, night: bool, now_ms: f64) -> (Vec<MeterView>, Vec<StatusView>, Vec<MeterView>) {
    let Ok(json) = spacetimedb_sdk::__codegen::__sats::ser::serde::serialize_to(row, serde_json::value::Serializer) else { return (Vec::new(), Vec::new(), Vec::new()) };
    let fields = living_rules::script::body::fields_of_json(&json);
    let get = |k: &str| fields.iter().find(|(n, _)| n == k).map(|(_, v)| *v);
    let mut ms: Vec<&living_rules::script::body::Meter> = sc.meters().iter().collect();
    ms.sort_by_key(|m| m.order);
    // Each meter now: a pool (a field with `<field>_from_ms`, stamina-1) moves along its rate per
    // second from the later of the row's `at_ms` and that time; any other field per minute since
    // `at_ms` (as `BodyFacts::of` reads them, so the bars and the pills agree).
    let now = |m: &living_rules::script::body::Meter| {
        let raw = get(&m.value)?;
        let max = m.max_of(&fields)?;
        let rate = get(&format!("{}_rate", m.value)).unwrap_or(0.0);
        let at = get("at_ms").unwrap_or(now_ms);
        let v = match get(&format!("{}_from_ms", m.value)) {
            Some(from) => raw + rate * ((now_ms - at.max(from)).max(0.0) / 1000.0),
            None => raw + rate * ((now_ms - at).max(0.0) / 60_000.0),
        };
        Some(MeterView { name: m.name.clone(), label: m.label.clone(), value: v.clamp(0.0, max.max(0.0)) as f32, max: max as f32 })
    };
    let all: Vec<(&living_rules::script::body::Meter, MeterView)> = ms.iter().filter_map(|m| now(m).map(|v| (*m, v))).collect();
    // The bars: shown meters, and one `while_short` only while it is not full (mana).
    let meters = all.iter().filter(|(m, v)| m.shown && (!m.while_short || v.value < v.max - 0.01)).map(|(_, v)| v.clone()).collect();
    // Every meter by the field it shows (a skill's pool names one), for greying the bar.
    let pools = all.iter().map(|(m, v)| MeterView { name: m.value.clone(), ..v.clone() }).collect();
    let facts = living_rules::script::BodyFacts::of(kind, stage, night, &fields, sc.meters(), now_ms.max(0.0) as u64);
    // A `plain` status is the body's words when all is well (a mind's "rested"): no pill.
    let statuses = sc.status_of(&facts).map(|v| v.iter().map(|s| StatusView { name: s.name.clone(), tone: Tone::parse(&s.tone), text: s.text.clone() }).filter(|s| s.tone != Tone::Plain).collect()).unwrap_or_default();
    (meters, statuses, pools)
}

/// What the bar says when an item a skill needs is not carried.
fn missing(item: &str) -> String {
    // Ammunition is counted, so it reads in the plural.
    match item {
        "arrow" => "No arrows".into(),
        i => format!("No {}", i.replace('_', " ")),
    }
}

/// Slots for the UI sample with no world connected: icons and states on keys, no skills (with
/// no rules there is no bar to name; the cluster is drawn from the rules' bar, `combat::Roles`).
pub fn default_bar(state: impl Fn(Key) -> SkillState) -> Vec<Skill> {
    let slot = |key: Key, icon: SkillIcon, cost: f32, count: Option<u32>| Skill { key, icon, state: if icon == SkillIcon::Empty { SkillState::Empty } else { state(key) }, name: String::new(), cost, count };
    vec![
        slot(Key::Lmb, SkillIcon::Sword, 2.0, None),
        slot(Key::Rmb, SkillIcon::Bow, 1.5, Some(28)),
        slot(Key::Q, SkillIcon::Fire, 6.0, None),
        slot(Key::E, SkillIcon::Shield, 1.0, None),
        slot(Key::R, SkillIcon::Heal, 8.0, None),
        slot(Key::Shift, SkillIcon::Dodge, 4.0, None),
    ]
}

/// The death screen's words, from the cause's kind only (`living_rules::outcome::death`): the
/// death row's code, else the kind of the authority's own fixed cause words ([`cause_kind`]). A
/// killer is named as I perceived them (`killer`: `Looks`). Free text never shows: `cause` (and a
/// cause given by an admin, code `other`) can carry real names; then "You died".
fn death(c: &Character, killer: Option<String>, row: Option<&ActOutcome>) -> Death {
    let lived_ms = c.died_ms.saturating_sub(c.born_ms);
    let code = row.map(|o| o.code.as_str()).or_else(|| cause_kind(&c.cause));
    Death { cause: death_words(code, killer.as_deref()), place: None, lived: (lived_ms > 0).then(|| lived(lived_ms)), witnesses: None }
}

/// The kind of a cause without a death row: the authority's own fixed words for a death that
/// names no one (`brain.rs` needs, `tick.rs` age), compared whole. Anything else has no kind.
fn cause_kind(cause: &str) -> Option<&'static str> {
    use living_rules::outcome::death;
    match cause.trim() {
        "starvation" => Some(death::STARVED),
        "cold and exposure" => Some(death::COLD),
        "exhaustion" => Some(death::EXHAUSTED),
        "old age" => Some(death::OLD_AGE),
        _ => None,
    }
}

/// What the death screen says for a cause's kind; a killing names the killer as perceived.
fn death_words(code: Option<&str>, killer: Option<&str>) -> String {
    use living_rules::outcome::death;
    match code {
        Some(death::STARVED) => "You starved".to_string(),
        Some(death::COLD) => "You died of cold".to_string(),
        Some(death::EXHAUSTED) => "You died of exhaustion".to_string(),
        Some(death::OLD_AGE) => "You died of old age".to_string(),
        Some(death::KILLED) | Some(death::KILLED_YIELDING) => format!("Killed by {}", killer.unwrap_or("someone")),
        _ => "You died".to_string(),
    }
}

/// How recently my character must have seen its killer to name them on the death screen (ms):
/// the death takes my perceived rows away in the same update.
const KILLER_SEEN_MS: f64 = 2_000.0;

/// Authority time lived, in words.
pub fn lived(ms: u64) -> String {
    let m = ms / 60_000;
    let (d, h, min) = (m / 1440, (m / 60) % 24, m % 60);
    let unit = |n: u64, w: &str| format!("{n} {w}{}", if n == 1 { "" } else { "s" });
    match (d, h) {
        (0, 0) => unit(min.max(1), "minute"),
        (0, _) => format!("{}, {}", unit(h, "hour"), unit(min, "minute")),
        _ => format!("{}, {}", unit(d, "day"), unit(h, "hour")),
    }
}

/// The spoken words of a percept such as `Helper said: “Welcome!”` (the whole text otherwise).
fn quoted(text: &str) -> &str {
    match (text.find('“'), text.rfind('”')) {
        (Some(a), Some(b)) if b > a => &text[a + '“'.len_utf8()..b],
        _ => text,
    }
}

#[cfg(test)]
mod tests {
    use super::{cause_kind, death_words};
    use living_rules::outcome::death;

    #[test]
    fn a_death_says_its_kind_and_never_a_free_cause() {
        // The authority's own words for deaths that name no one have a kind.
        assert_eq!(death_words(cause_kind("starvation"), None), "You starved");
        assert_eq!(death_words(cause_kind("old age"), None), "You died of old age");
        assert_eq!(death_words(cause_kind("cold and exposure"), None), "You died of cold");
        assert_eq!(death_words(cause_kind("exhaustion"), None), "You died of exhaustion");
        // Free text (an admin's cause, the authority's "killed by" with a real name) has none.
        assert_eq!(cause_kind("killed by Vessa Pontil"), None);
        assert_eq!(death_words(cause_kind("killed by Vessa Pontil"), None), "You died");
        assert_eq!(death_words(Some(death::OTHER), None), "You died");
        // A killing names the killer only as perceived.
        assert_eq!(death_words(Some(death::KILLED), Some("a stranger in green")), "Killed by a stranger in green");
        assert_eq!(death_words(Some(death::KILLED_YIELDING), None), "Killed by someone");
    }
}
