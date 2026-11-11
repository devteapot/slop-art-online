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
    /// Speech I heard, by experience id: `my_experience` holds only my newest lines (the
    /// authority's window, `frame::LINES_SHOWN`), so the log keeps what it has received.
    heard: BTreeMap<u64, Experience>,
    /// The connection has been live: a later loss is shown.
    was_live: bool,
}

#[allow(clippy::too_many_arguments)]
pub fn fill(mut model: ResMut<HudModel>, mut out: ResMut<Outbox>, mut net: NonSendMut<Net>, scene: NonSend<Scene>, cam: Res<Cam>, mut input: ResMut<Input>, target: Res<Target>, size: Res<crate::bodies::MySize>, sight: Res<crate::sight::Sight>, island: Option<Res<crate::island::Island>>, live: Res<crate::live::Live>, combat: Res<crate::combat::Combat>, cards: Res<crate::combat::Cards>, town: Res<crate::town::Town>, (talk, looks): (Option<Res<crate::talk::Talk>>, Res<crate::looks::Looks>), mut last: Local<Last>) {
    let now_ms = scene.now_ms;
    let now = now_ms / 1000.0;
    model.shown = true;
    model.now = now;
    model.hint = None;

    // Requests from the UI.
    for (line, to) in out.say.drain(..) {
        if controls::say(&net, &line, to) {
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
    for c in chars.values() {
        if last.labels.get(&c.id) != Some(&c.label) {
            last.labels.insert(c.id, c.label.clone());
        }
    }

    // Death: the character I played is no longer alive.
    if let Some(prev) = last.id {
        if net.my_id.is_none() && mine.get(&prev).is_some_and(|c| !c.alive) {
            last.dead = Some(prev);
        }
    }
    if net.my_id.is_some() {
        last.id = net.my_id;
        last.dead = None;
    }
    let perceived = |id: u32| chars.get(&id).map(|c| c.label.clone()).or_else(|| last.labels.get(&id).cloned());
    model.death = last.dead.and_then(|id| mine.get(&id)).map(|c| death(c, combat.killer.and_then(perceived))).map(|mut d| {
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
        let mut statuses = Vec::new();
        // Thresholds where the authority starts telling the character (brain.rs percepts).
        if hunger >= 97.0 {
            statuses.push(Status { kind: StatusKind::Starving, tone: Tone::Bad });
        } else if hunger >= 80.0 {
            statuses.push(Status { kind: StatusKind::Hungry, tone: Tone::Warn });
        }
        if energy < 12.0 {
            statuses.push(Status { kind: StatusKind::Exhausted, tone: Tone::Bad });
        } else if energy < 35.0 {
            statuses.push(Status { kind: StatusKind::Tired, tone: Tone::Warn });
        }
        if v.hurt_ms > 0 && since_hurt < 15.0 {
            statuses.push(Status { kind: StatusKind::InCombat, tone: Tone::Bad });
        }
        if v.hp_rate < 0.0 {
            statuses.push(Status { kind: StatusKind::Wasting, tone: Tone::Bad });
        } else if v.hp_rate > 0.0 && hp < v.max_hp {
            statuses.push(Status { kind: StatusKind::Recovering, tone: Tone::Good });
        }
        let name = mine.get(&id).map_or(net.name.clone(), |c| c.name.clone());
        Me { name, hp, max_hp: v.max_hp, energy, max_energy: 100.0, statuses, hurt: if v.hurt_ms > 0 { (1.0 - since_hurt / 0.8).clamp(0.0, 1.0) } else { 0.0 } }
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
    let cursor = cam.cursor_ground.map(|c| Vec2::new(c.x, c.z));
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
        let near_cursor = cursor.map_or(f32::MAX, |c| c.distance(*p));
        let hostile = hostile(*id);
        actors.push(Actor {
            id: *id as u64,
            name: name_of(*id),
            head: head(*id, *p, &c.kind),
            distance,
            hovered: near_cursor < 1.2,
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
    // Targeted skills go to the creature under or nearest the cursor (`combat.rs` picks it);
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
        let name = super::label(&if c.kind != "person" && !c.name.is_empty() { format!("{} the {}", c.name, c.kind) } else { name_of(id) });
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
        bubbles.push(Bubble { speaker: e.subject as u64, name: name_of(e.subject), text, head: head(e.subject, *p, kind), age, life, mine: false });
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
                        if energy < card.cost {
                            return SkillState::Unavailable("Too tired".into());
                        }
                        SkillState::Ready
                    })();
                    // What it spends: the last item it needs (a bow and arrows: the arrows).
                    let count = crate::combat::needs(card).0.last().map(inv).filter(|_| crate::combat::needs(card).0.count() > 1);
                    Skill { key: Key::Lmb, icon: crate::combat::look(card).icon, state, name: card.skill.clone(), cost: card.cost, count }
                })
                .collect()
        }
        _ => default_bar(|_| SkillState::Ready),
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

/// What the bar says when an item a skill needs is not carried.
fn missing(item: &str) -> String {
    // Ammunition is counted, so it reads in the plural.
    match item {
        "arrow" => "No arrows".into(),
        i => format!("No {}", i.replace('_', " ")),
    }
}

/// The starter skills on their keys (docs/GAME_BRIEF.md, 2026-11-09), for the UI sample with
/// no world connected; F interacts.
pub fn default_bar(state: impl Fn(Key) -> SkillState) -> Vec<Skill> {
    let slot = |key: Key, icon: SkillIcon, name: &str, cost: f32, count: Option<u32>| Skill { key, icon, state: if icon == SkillIcon::Empty { SkillState::Empty } else { state(key) }, name: name.into(), cost, count };
    vec![
        slot(Key::Lmb, SkillIcon::Sword, "strike", 2.0, None),
        slot(Key::Rmb, SkillIcon::Bow, "bowshot", 1.5, Some(28)),
        slot(Key::Q, SkillIcon::Fire, "firebolt", 6.0, None),
        slot(Key::E, SkillIcon::Shield, "block", 1.0, None),
        slot(Key::R, SkillIcon::Heal, "heal", 8.0, None),
        slot(Key::Shift, SkillIcon::Dodge, "dodge", 4.0, None),
    ]
}

/// The death screen's words. A killer is named as I perceived them (`killer`: the label of
/// the one my `DEATH` row names), never from `cause`, whose text carries the real name.
fn death(c: &Character, killer: Option<String>) -> Death {
    let cause = c.cause.trim();
    let cause = if cause.is_empty() {
        "You died".to_string()
    } else if cause == "starvation" {
        "You starved".to_string()
    } else if cause == "old age" {
        "You died of old age".to_string()
    } else if cause.starts_with("killed by ") {
        format!("Killed by {}", killer.unwrap_or_else(|| "someone".to_string()))
    } else {
        format!("You died of {cause}")
    };
    let lived_ms = c.died_ms.saturating_sub(c.born_ms);
    Death { cause, place: None, lived: (lived_ms > 0).then(|| lived(lived_ms)), witnesses: None }
}

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
