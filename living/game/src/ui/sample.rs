//! The UI's look-dev source: representative sample values for judging layout without a server.
//! Presentation data only; nothing here is a rule or a simulation.
//!
//! Off unless `LIVING_GAME_HUD` is set, so look-dev and tour photographs stay clean.
//! `LIVING_GAME_HUD=1` shows a typical moment (hover, bubbles, cooldown); a comma list picks
//! states to demo (`quiet` alone shows only what is always on screen):
//! - `hover`: the nearest character is under the cursor (target frame, nameplate, hint);
//! - `bubbles`: several nearby speakers at once (bubbles stack instead of overlapping);
//! - `chat`: the chat input is open with a line being typed;
//! - `lowhp`: low health, a hostile attacker, losing health and in combat;
//! - `cooldown`: skills on cooldown, one unavailable for lack of energy;
//! - `death`: the death screen;
//! - `crowd`: with `bubbles`, eight speakers at once and up to twelve people with plates (a
//!   market crowd, for judging overlap and legibility; with `LIVING_GAME_CROWD`).
//!
//! Sample characters are the look-dev scene's own (`characters::Character`), with sample names.
//! In a window the sample loops (bubbles come and go, cooldowns run down); in scripted
//! photographs it holds still.

use super::model::*;
use crate::camera::Cam;
use crate::controls::{Input, Target};
use bevy::prelude::*;
use living_rules::land::SiteKind;

#[derive(Default, Clone, Copy)]
pub struct States {
    pub hover: bool,
    pub bubbles: bool,
    pub chat: bool,
    pub lowhp: bool,
    pub cooldown: bool,
    pub death: bool,
    pub crowd: bool,
}

/// The sample states asked for, if the sample HUD is on.
pub fn states() -> Option<States> {
    let v = std::env::var("LIVING_GAME_HUD").ok().filter(|v| !v.is_empty() && v != "0")?;
    let mut s = States::default();
    if v == "1" || v == "default" {
        return Some(States { hover: true, bubbles: true, cooldown: true, ..s });
    }
    for w in v.split(',').map(str::trim) {
        match w {
            "hover" => s.hover = true,
            "bubbles" => s.bubbles = true,
            "crowd" => {
                s.crowd = true;
                s.bubbles = true;
            }
            "chat" => s.chat = true,
            "lowhp" => s.lowhp = true,
            "cooldown" => s.cooldown = true,
            "death" => s.death = true,
            "quiet" => {}
            other => warn!("LIVING_GAME_HUD: unknown state {other} (hover, bubbles, chat, lowhp, cooldown, death, crowd)"),
        }
    }
    Some(s)
}

const NAMES: [&str; 8] = ["Mira Ashdown", "Old Hale", "Wren", "Tomas Reed", "Ysolde", "Bram", "Kesh", "Little Pell"];

const LINES: [&str; 4] = [
    "Did you hear? The ferry hasn't crossed since the storm.",
    "Ask at the inn. Hale keeps the ledger.",
    "Mind the north road after dark.",
    "Bread's fresh, if you've coin.",
];

#[derive(Default)]
pub struct Local {
    started: bool,
    dead_dismissed: bool,
    said: Vec<(f64, String)>,
}

#[allow(clippy::too_many_arguments)]
pub fn fill(
    mut model: ResMut<HudModel>,
    mut out: ResMut<Outbox>,
    mut input: ResMut<Input>,
    cam: Res<Cam>,
    target: Res<Target>,
    roam: Option<Res<crate::envs::Roam>>,
    island: Option<Res<crate::island::Island>>,
    chars: Query<(Entity, &GlobalTransform, &crate::characters::Character), Without<crate::envs::Player>>,
    camq: Query<(&Camera, &GlobalTransform), With<Camera3d>>,
    time: Res<Time>,
    mut st: bevy::prelude::Local<Local>,
) {
    let Some(s) = states() else {
        model.shown = false;
        return;
    };
    let t = time.elapsed_secs_f64();
    let still = crate::capture::scripted();
    model.shown = true;
    model.now = t;
    if !st.started {
        st.started = true;
        if s.chat {
            input.chat_open = true;
            input.chat = "Has anyone seen the ferryman".into();
        }
    }
    for (line, _) in out.say.drain(..) {
        st.said.push((t, line));
    }
    if std::mem::take(&mut out.rejoin) {
        st.dead_dismissed = true;
    }

    let my_name = std::env::var("LIVING_GAME_NAME").unwrap_or_else(|_| "Wanderer".into());
    let me3 = target.0;
    let my_head = me3.map(|m| m + Vec3::Y * 1.95);

    // Sample characters: the scene's nearest people on screen.
    let mut near: Vec<(Entity, Vec3, f32, f32)> = Vec::new();
    if let (Some(me), Ok((camera, ctf))) = (me3, camq.single()) {
        for (e, gtf, c) in &chars {
            let at = gtf.translation();
            let d = at.distance(me);
            if d > 26.0 || d < 0.5 {
                continue;
            }
            let head = at + Vec3::Y * (c.recipe.height * 1.1);
            let on_screen = camera.world_to_viewport(ctf, head).ok().zip(camera.logical_viewport_size()).is_some_and(|(p, size)| p.x > 40.0 && p.y > 60.0 && p.x < size.x - 40.0 && p.y < size.y - 60.0);
            if on_screen {
                near.push((e, head, d, c.recipe.height));
            }
        }
    }
    near.sort_by(|a, b| a.2.total_cmp(&b.2));
    let name = |e: Entity| NAMES[(e.index().index() as usize) % NAMES.len()].to_string();
    let hostile = if s.lowhp { near.get(1).or(near.first()).map(|n| n.0) } else { None };
    let hovered = if s.hover || s.lowhp { hostile.or(near.first().map(|n| n.0)) } else { None };

    // Speakers: the nearest few, when bubbles are asked for.
    let speakers: Vec<Entity> = if s.bubbles { near.iter().map(|n| n.0).filter(|e| Some(*e) != hostile).take(if s.crowd { 8 } else { 3 }).collect() } else { Vec::new() };
    model.actors = near
        .iter()
        .take(if s.crowd { 12 } else { 8 })
        .map(|&(e, head, distance, _)| {
            let is_hostile = Some(e) == hostile;
            Actor {
                id: e.to_bits(),
                name: if is_hostile { "Varek the Brigand".into() } else { name(e) },
                head,
                distance,
                hovered: Some(e) == hovered || (s.crowd && distance < 9.0),
                targeted: Some(e) == hovered,
                talking: speakers.contains(&e),
                greeted: false,
                stance: if is_hostile { Stance::Hostile } else { Stance::Neutral },
                hp: if is_hostile { Some(0.62) } else { None },
                exact: if is_hostile && s.lowhp { Some((31.0, 50.0)) } else { None },
            }
        })
        .collect();
    model.target = model.actors.iter().find(|a| a.targeted).map(|a| TargetInfo {
        name: a.name.clone(),
        doing: if a.stance == Stance::Hostile { Some(StatusKind::InCombat) } else if a.talking { Some(StatusKind::Talking) } else { None },
        hp: a.hp,
        stance: a.stance,
        distance: a.distance,
    });
    // Only near something you can use.
    model.hint = model.target.as_ref().filter(|t| t.stance != Stance::Hostile && t.distance < 6.0).map(|_| Hint { key: "F".into(), label: "Talk".into() });

    // Several speakers at once.
    model.bubbles.clear();
    if s.bubbles {
        let speakers: Vec<_> = model.actors.iter().filter(|a| a.talking).map(|a| (a.id, a.name.clone(), a.head)).collect();
        for (k, (id, who, head)) in speakers.into_iter().enumerate() {
            let text = LINES[k % LINES.len()].to_string();
            let life = bubble_life(&text);
            let age = if still { 0.8 + k as f32 * 0.4 } else { ((t + k as f64 * 2.7) % (life as f64 + 2.5)) as f32 };
            if age < life {
                model.bubbles.push(Bubble { speaker: id, name: who, text, head, age, life, mine: false });
            }
        }
        if let Some(h) = my_head {
            let text = "Where would I find work around here?".to_string();
            let life = bubble_life(&text);
            let age = if still { 1.0 } else { ((t + 1.3) % (life as f64 + 4.0)) as f32 };
            if age < life {
                model.bubbles.push(Bubble { speaker: u64::MAX, name: my_name.clone(), text, head: h, age, life, mine: true });
            }
        }
    }
    if let (Some(h), Some((at, text))) = (my_head, st.said.last()) {
        let age = (t - at) as f32;
        if age < bubble_life(text) {
            model.bubbles.retain(|b| !b.mine);
            model.bubbles.push(Bubble { speaker: u64::MAX, name: my_name.clone(), text: text.clone(), head: h, age, life: bubble_life(text), mine: true });
        }
    }

    // The log: only lines heard.
    let mut log = vec![
        LogLine { at: t - 74.0, who: "Old Hale".into(), text: "Rain by evening, I'd wager.".into(), kind: LogKind::Heard },
        LogLine { at: t - 52.0, who: "Wren".into(), text: "You're new here. Welcome to Ashford.".into(), kind: LogKind::ToMe },
        LogLine { at: t - 40.0, who: my_name.clone(), text: "Thank you. Where's the inn?".into(), kind: LogKind::Mine },
        LogLine { at: t - 31.0, who: "Wren".into(), text: "Past the well, the house with the green sign.".into(), kind: LogKind::ToMe },
    ];
    for b in &model.bubbles {
        log.push(LogLine { at: t - b.age as f64, who: b.name.clone(), text: b.text.clone(), kind: if b.mine { LogKind::Mine } else { LogKind::Heard } });
    }
    log.extend(st.said.iter().map(|(at, text)| LogLine { at: *at, who: my_name.clone(), text: text.clone(), kind: LogKind::Mine }));
    log.sort_by(|a, b| a.at.total_cmp(&b.at));
    model.log = log;

    // Me.
    let mut statuses = vec![Status { kind: StatusKind::Hungry, tone: Tone::Warn }];
    let (hp, energy) = match (s.lowhp, s.cooldown) {
        (true, _) => (34.0, 41.0),
        (_, true) => (168.0, 22.0),
        _ => (168.0, 64.0),
    };
    if energy < 35.0 {
        statuses.push(Status { kind: StatusKind::Tired, tone: Tone::Warn });
    }
    if s.lowhp {
        statuses.push(Status { kind: StatusKind::InCombat, tone: Tone::Bad });
        statuses.push(Status { kind: StatusKind::Wasting, tone: Tone::Bad });
    } else {
        statuses.push(Status { kind: StatusKind::Recovering, tone: Tone::Good });
    }
    let hurt = if s.lowhp { if still { 0.6 } else { (1.0 - ((t % 2.4) / 0.8) as f32).clamp(0.0, 1.0) } } else { 0.0 };
    model.me = Some(Me { name: my_name, hp, max_hp: 200.0, energy, max_energy: 100.0, statuses, hurt });

    // Skills.
    let cd = |total: f32, phase: f32| {
        let left = if still { total * phase } else { total - ((t as f32 + total * (1.0 - phase)) % (total + 1.5)) };
        if left > 0.0 {
            SkillState::Cooldown { left, total }
        } else {
            SkillState::Ready
        }
    };
    model.skills = crate::ui::live::default_bar(|key| match key {
        Key::Q if s.cooldown => cd(8.0, 0.42),
        Key::Shift if s.cooldown => cd(2.5, 0.7),
        Key::Rmb if s.cooldown => cd(1.2, 0.5),
        Key::R if s.cooldown => SkillState::Unavailable("Not enough energy".into()),
        Key::E if s.lowhp => SkillState::Active,
        _ => SkillState::Ready,
    });

    // Death.
    model.death = (s.death && !st.dead_dismissed).then(|| Death {
        cause: "Killed by Varek the Brigand".into(),
        place: Some("on the north road out of Ashford".into()),
        lived: Some("2 days, 7 hours".into()),
        witnesses: Some(vec!["Mira Ashdown".into(), "Old Hale".into()]),
    });

    // Compass: the island's settlements, or sample places off the line-up.
    let pois: Vec<Poi> = match &island {
        Some(i) => {
            let land = &i.land;
            let mut pois: Vec<Poi> = land
                .settlements
                .iter()
                .map(|st| {
                    let kind = match st.kind {
                        SiteKind::Town => PoiKind::Town,
                        SiteKind::Village => PoiKind::Village,
                        SiteKind::Giants => PoiKind::Giants,
                        SiteKind::SmallFolk => PoiKind::SmallFolk,
                        SiteKind::Cave => PoiKind::Cave,
                    };
                    Poi { kind, at: Vec2::new(st.centre.0, st.centre.1) }
                })
                .collect();
            pois.extend(land.sites.iter().filter(|s| s.kind == SiteKind::Cave).map(|s| Poi { kind: PoiKind::Cave, at: Vec2::new(s.x, s.y) }));
            pois
        }
        None => vec![
            Poi { kind: PoiKind::Village, at: Vec2::new(70.0, -120.0) },
            Poi { kind: PoiKind::Cave, at: Vec2::new(-160.0, 40.0) },
            Poi { kind: PoiKind::Place, at: Vec2::new(36.0, 64.0) },
        ],
    };
    model.map = MapInfo { me: me3.map(|m| Vec2::new(m.x, m.z)), facing: input.look.or(roam.map(|r| r.facing)), yaw: cam.shown_yaw, pois };
}
