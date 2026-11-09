//! The bottom-centre cluster (status, health, energy, skill bar, interaction hint), the target
//! frame at the top centre, and the low-health vignette.

use super::icons::{Glyph, Icons};
use super::model::*;
use super::theme::{self, Fonts};
use super::{set_bg, set_color, set_text, set_width, show, HudRoot};
use bevy::prelude::*;
use bevy::color::Mix;
use bevy::ui::{AngularColorStop, BackgroundGradient, BoxShadow, ColorStop, ConicGradient, GlobalZIndex, Gradient, LinearGradient, Outline, UiPosition, UiTransform};
use std::f32::consts::TAU;

/// Width of the cluster: seven 54 px slots with gaps and two group gaps.
const WIDTH: f32 = 54.0 * 7.0 + 6.0 * 4.0 + 16.0 * 2.0;
const SLOT: f32 = 54.0;
const STATUS_SLOTS: usize = 6;

#[derive(Component)]
pub struct HpFill;
#[derive(Component)]
pub struct HpGhost;
#[derive(Component)]
pub struct HpFlash;
#[derive(Component)]
pub struct EnFill;
#[derive(Component)]
pub struct StatusPill(usize);
#[derive(Component)]
pub struct StatusIcon(usize);

#[derive(Component)]
pub struct Slot(usize);
#[derive(Component)]
pub struct SlotIcon(usize);
#[derive(Component)]
pub struct SlotSweep(usize);
#[derive(Component)]
pub struct SlotTime(usize);
#[derive(Component)]
pub struct SlotKey(usize);
#[derive(Component)]
pub struct SlotVeil(usize);

#[derive(Component)]
pub struct HintRoot;
#[derive(Component)]
pub struct HintKey;
#[derive(Component)]
pub struct HintLabel;

#[derive(Component)]
pub struct TargetRoot;
#[derive(Component)]
pub struct TargetAccent;
#[derive(Component)]
pub struct TargetName;
#[derive(Component)]
pub struct TargetDoing;
#[derive(Component)]
pub struct TargetBar;
#[derive(Component)]
pub struct TargetFill;
#[derive(Component)]
pub struct TargetMarker;

#[derive(Component)]
pub struct Vignette;

fn bar_gradient(lo: Color, hi: Color) -> BackgroundGradient {
    // Light top edge over a saturated body: the toon look's banding, in a bar.
    BackgroundGradient::from(LinearGradient::to_bottom(vec![ColorStop::percent(hi, 0.0), ColorStop::percent(hi, 38.0), ColorStop::percent(lo, 40.0), ColorStop::percent(lo, 100.0)]))
}

fn key_chip(fonts: &Fonts) -> impl Bundle {
    (
        Node { padding: UiRect::axes(Val::Px(5.0), Val::Px(0.0)), min_width: Val::Px(17.0), height: Val::Px(17.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(5.0)), ..default() },
        BackgroundColor(theme::INK_SOLID),
        BorderColor::all(theme::EDGE_STRONG),
        children![(Text::new(""), fonts.body(11.0, 800), TextColor(theme::TEXT))],
    )
}

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>, icons: Res<Icons>) {
    let f = fonts.clone();
    // Bottom centre.
    commands
        .spawn((
            HudRoot,
            Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), bottom: Val::Px(20.0), flex_direction: FlexDirection::Column, align_items: AlignItems::Center, ..default() },
            Pickable::IGNORE,
        ))
        .with_children(|root| {
            // Interaction hint.
            root.spawn((HintRoot, Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(9.0), margin: UiRect::bottom(Val::Px(18.0)), padding: UiRect::new(Val::Px(6.0), Val::Px(14.0), Val::Px(5.0), Val::Px(5.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(999.0)), ..default() }, theme::panel(999.0)))
                .with_children(|h| {
                    h.spawn((Node { width: Val::Px(26.0), height: Val::Px(26.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: UiRect::all(Val::Px(1.5)), border_radius: BorderRadius::all(Val::Px(7.0)), ..default() }, BackgroundColor(theme::INK_SOLID), BorderColor::all(theme::GOLD)))
                        .with_child((HintKey, Text::new("F"), f.body(14.0, 800), TextColor(theme::GOLD)));
                    h.spawn((HintLabel, Text::new(""), f.body(15.0, 650), TextColor(theme::TEXT)));
                });
            // Status pills, left-aligned over the bars.
            root.spawn(Node { width: Val::Px(WIDTH), flex_direction: FlexDirection::Row, column_gap: Val::Px(5.0), margin: UiRect::bottom(Val::Px(6.0)), ..default() }).with_children(|row| {
                for i in 0..STATUS_SLOTS {
                    row.spawn((
                        StatusPill(i),
                        Node { width: Val::Px(26.0), height: Val::Px(26.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: UiRect::all(Val::Px(1.5)), border_radius: BorderRadius::all(Val::Percent(50.0)), ..default() },
                        BackgroundColor(theme::INK),
                        BorderColor::all(theme::EDGE),
                    ))
                    .with_child((StatusIcon(i), Node { width: Val::Px(17.0), height: Val::Px(17.0), ..default() }, ImageNode::new(icons.get(Glyph::Status(StatusKind::Hungry)))));
                }
            });
            // Health.
            root.spawn((
                Node { width: Val::Px(WIDTH), height: Val::Px(14.0), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(6.0)), overflow: Overflow::clip(), ..default() },
                BackgroundColor(theme::TRACK),
                BorderColor::all(theme::EDGE_STRONG),
                BoxShadow::new(theme::SHADOW, Val::ZERO, Val::Px(2.0), Val::ZERO, Val::Px(8.0)),
            ))
            .with_children(|b| {
                b.spawn((HpGhost, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), ..default() }, BackgroundColor(Color::srgba(1.0, 0.86, 0.72, 0.55))));
                b.spawn((HpFill, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), ..default() }, bar_gradient(theme::HP_LO, theme::HP_HI)));
                b.spawn((HpFlash, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), ..default() }, BackgroundColor(Color::NONE)));
            });
            // Energy (the rules' `energy` need).
            root.spawn((
                Node { width: Val::Px(WIDTH), height: Val::Px(7.0), margin: UiRect::top(Val::Px(4.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(5.0)), overflow: Overflow::clip(), ..default() },
                BackgroundColor(theme::TRACK),
                BorderColor::all(theme::EDGE),
            ))
            .with_children(|b| {
                b.spawn((EnFill, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), ..default() }, bar_gradient(theme::EN_LO, theme::EN_HI)));
            });
            // Skill bar: mouse, skills, dodge.
            root.spawn(Node { width: Val::Px(WIDTH), margin: UiRect::top(Val::Px(10.0)), flex_direction: FlexDirection::Row, column_gap: Val::Px(6.0), ..default() }).with_children(|bar| {
                for (i, key) in Key::BAR.iter().enumerate() {
                    let gap = if matches!(key, Key::Q | Key::Shift) { 10.0 } else { 0.0 };
                    bar.spawn((
                        Slot(i),
                        Node { width: Val::Px(SLOT), height: Val::Px(SLOT), margin: UiRect::left(Val::Px(gap)), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: UiRect::all(Val::Px(1.5)), border_radius: BorderRadius::all(Val::Px(11.0)), ..default() },
                        BackgroundColor(theme::INK),
                        BackgroundGradient::default(),
                        BorderColor::all(theme::EDGE_STRONG),
                        BoxShadow::new(theme::SHADOW, Val::ZERO, Val::Px(3.0), Val::ZERO, Val::Px(10.0)),
                        Outline { width: Val::Px(0.0), offset: Val::Px(2.0), color: theme::GOLD },
                    ))
                    .with_children(|s| {
                        s.spawn((SlotIcon(i), Node { width: Val::Px(36.0), height: Val::Px(36.0), ..default() }, ImageNode::new(Handle::default())));
                        s.spawn((SlotVeil(i), Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), border_radius: BorderRadius::all(Val::Px(10.0)), ..default() }, BackgroundColor(Color::NONE)));
                        s.spawn((SlotSweep(i), Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), border_radius: BorderRadius::all(Val::Px(10.0)), justify_content: JustifyContent::Center, align_items: AlignItems::Center, ..default() }, BackgroundGradient::default()))
                            .with_child((SlotTime(i), Text::new(""), f.body(18.0, 850), TextColor(theme::TEXT), theme::text_shadow()));
                        let mut chip = s.spawn((SlotKey(i), Node { position_type: PositionType::Absolute, left: Val::Px(-6.0), top: Val::Px(-7.0), ..default() }));
                        match key {
                            Key::Lmb | Key::Rmb => {
                                let g = if *key == Key::Lmb { Glyph::MouseL } else { Glyph::MouseR };
                                chip.insert((
                                    Node { position_type: PositionType::Absolute, left: Val::Px(-6.0), top: Val::Px(-7.0), width: Val::Px(19.0), height: Val::Px(23.0), padding: UiRect::all(Val::Px(1.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(6.0)), ..default() },
                                    BackgroundColor(theme::INK_SOLID),
                                    BorderColor::all(theme::EDGE_STRONG),
                                ))
                                .with_child((Node { width: Val::Percent(100.0), height: Val::Percent(100.0), ..default() }, ImageNode::new(icons.get(g))));
                            }
                            _ => {
                                chip.with_children(|c| {
                                    c.spawn(key_chip(&f));
                                });
                            }
                        }
                    });
                }
            });
        });

    // Target frame, top centre.
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(18.0), justify_content: JustifyContent::Center, ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            root.spawn((
                TargetRoot,
                Node { min_width: Val::Px(220.0), max_width: Val::Px(320.0), flex_direction: FlexDirection::Column, padding: UiRect::new(Val::Px(13.0), Val::Px(13.0), Val::Px(8.0), Val::Px(9.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(12.0)), overflow: Overflow::clip(), ..default() },
                theme::panel(12.0),
            ))
            .with_children(|t| {
                t.spawn((TargetAccent, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), height: Val::Px(2.0), ..default() }, BackgroundColor(theme::GOLD)));
                t.spawn(Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(8.0), ..default() }).with_children(|r| {
                    r.spawn((TargetMarker, Node { width: Val::Px(9.0), height: Val::Px(9.0), ..default() }, UiTransform::from_rotation(Rot2::degrees(45.0)), BackgroundColor(theme::GOLD)));
                    r.spawn((TargetName, Text::new(""), f.body(17.0, 800), TextColor(theme::TEXT), Node { flex_grow: 1.0, ..default() }));
                    r.spawn((TargetDoing, Node { width: Val::Px(18.0), height: Val::Px(18.0), ..default() }, ImageNode::new(Handle::default())));
                });
                t.spawn((TargetBar, Node { height: Val::Px(7.0), margin: UiRect::top(Val::Px(7.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(4.0)), overflow: Overflow::clip(), ..default() }, BackgroundColor(theme::TRACK), BorderColor::all(theme::EDGE)))
                    .with_child((TargetFill, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), ..default() }, bar_gradient(theme::HP_LO, theme::HP_HI)));
            });
        });

    // Low-health vignette, under everything else.
    commands.spawn((
        HudRoot,
        Vignette,
        Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), ..default() },
        BackgroundGradient::default(),
        GlobalZIndex(-10),
        Pickable::IGNORE,
    ));
}

pub fn vitals(
    model: Res<HudModel>,
    time: Res<Time>,
    mut ghost: Local<f32>,
    mut nodes: ParamSet<(Query<&mut Node, With<HpFill>>, Query<&mut Node, With<HpGhost>>, Query<&mut Node, With<EnFill>>)>,
    mut flash: Query<&mut BackgroundColor, With<HpFlash>>,
) {
    let Some(me) = &model.me else { return };
    let f = (me.hp / me.max_hp.max(1.0)).clamp(0.0, 1.0);
    // The trail eases down after a hit (presentation only).
    let dt = time.delta_secs();
    *ghost = if *ghost < f || *ghost == 0.0 { f } else { *ghost + (f - *ghost) * (1.0 - (-dt * 2.2).exp()) };
    if crate::capture::scripted() && me.hurt > 0.0 {
        *ghost = (f + 0.12).min(1.0);
    }
    for mut n in &mut nodes.p0() {
        set_width(&mut n, Val::Percent(f * 100.0));
    }
    for mut n in &mut nodes.p1() {
        set_width(&mut n, Val::Percent(*ghost * 100.0));
    }
    for mut n in &mut nodes.p2() {
        set_width(&mut n, Val::Percent((me.energy / me.max_energy.max(1.0)).clamp(0.0, 1.0) * 100.0));
    }
    for mut b in &mut flash {
        set_bg(&mut b, Color::srgba(1.0, 0.95, 0.9, me.hurt * 0.35));
    }
}

pub fn status(
    model: Res<HudModel>,
    icons: Res<Icons>,
    mut pills: Query<(&StatusPill, &mut Node, &mut BorderColor)>,
    mut imgs: Query<(&StatusIcon, &mut ImageNode)>,
) {
    let list: &[Status] = model.me.as_ref().map_or(&[], |m| &m.statuses);
    for (p, mut n, mut b) in &mut pills {
        show(&mut n, p.0 < list.len());
        if let Some(s) = list.get(p.0) {
            let c = theme::with_alpha(theme::tone(s.tone), 0.55);
            if b.top != c {
                *b = BorderColor::all(c);
            }
        }
    }
    for (i, mut img) in &mut imgs {
        if let Some(s) = list.get(i.0) {
            let h = icons.get(Glyph::Status(s.kind));
            if img.image != h {
                img.image = h;
            }
            if img.color != theme::tone(s.tone) {
                img.color = theme::tone(s.tone);
            }
        }
    }
}

#[allow(clippy::type_complexity)]
pub fn skills(
    model: Res<HudModel>,
    icons: Res<Icons>,
    mut slots: Query<(&Slot, &mut BackgroundGradient, &mut BorderColor, &mut Outline), (Without<SlotSweep>, Without<SlotVeil>)>,
    mut imgs: Query<(&SlotIcon, &mut ImageNode)>,
    mut sweeps: Query<(&SlotSweep, &mut BackgroundGradient), Without<Slot>>,
    mut veils: Query<(&SlotVeil, &mut BackgroundColor)>,
    mut times: Query<(&SlotTime, &mut Text)>,
    keys: Query<(&SlotKey, &Children)>,
    mut key_texts: Query<(&mut Text, &mut TextColor), Without<SlotTime>>,
    chips: Query<&Children>,
) {
    for (slot, mut bg, mut border, mut outline) in &mut slots {
        let Some(s) = model.skills.get(slot.0) else { continue };
        let (light, dark) = theme::school(s.icon);
        let dim = matches!(s.state, SkillState::Unavailable(_) | SkillState::Empty);
        let top = if dim { theme::with_alpha(dark, 0.55) } else { theme::with_alpha(light, 0.32) };
        let want = BackgroundGradient::from(LinearGradient::to_bottom(vec![ColorStop::percent(top, 0.0), ColorStop::percent(theme::with_alpha(dark, 0.92), 70.0), ColorStop::percent(theme::INK_SOLID, 100.0)]));
        if *bg != want {
            *bg = want;
        }
        let edge = match s.state {
            SkillState::Active => theme::GOLD,
            SkillState::Empty => theme::EDGE,
            SkillState::Unavailable(_) => theme::EDGE,
            _ => theme::with_alpha(light, 0.55),
        };
        if border.top != edge {
            *border = BorderColor::all(edge);
        }
        let w = if s.state == SkillState::Active { Val::Px(2.0) } else { Val::Px(0.0) };
        if outline.width != w {
            outline.width = w;
        }
    }
    for (i, mut img) in &mut imgs {
        let Some(s) = model.skills.get(i.0) else { continue };
        let h = icons.get(Glyph::Skill(s.icon));
        if img.image != h {
            img.image = h;
        }
        let (light, _) = theme::school(s.icon);
        let c = match s.state {
            SkillState::Unavailable(_) => Color::srgba(0.62, 0.62, 0.68, 0.55),
            SkillState::Empty => Color::srgba(1.0, 1.0, 1.0, 0.28),
            SkillState::Cooldown { .. } => theme::with_alpha(light.mix(&Color::WHITE, 0.4), 0.85),
            _ => light.mix(&Color::WHITE, 0.35),
        };
        if img.color != c {
            img.color = c;
        }
    }
    for (i, mut g) in &mut sweeps {
        let Some(s) = model.skills.get(i.0) else { continue };
        let want = match s.state {
            SkillState::Cooldown { left, total } => {
                let done = (1.0 - left / total.max(0.01)).clamp(0.0, 1.0) * TAU;
                let shade = Color::srgba(0.02, 0.03, 0.07, 0.74);
                BackgroundGradient::from(Gradient::Conic(ConicGradient {
                    start: 0.0,
                    position: UiPosition::CENTER,
                    stops: vec![
                        AngularColorStop::new(Color::NONE, 0.0),
                        AngularColorStop::new(Color::NONE, done),
                        AngularColorStop::new(shade, done),
                        AngularColorStop::new(shade, TAU),
                    ],
                    color_space: default(),
                }))
            }
            _ => BackgroundGradient::default(),
        };
        if *g != want {
            *g = want;
        }
    }
    for (i, mut b) in &mut veils {
        let Some(s) = model.skills.get(i.0) else { continue };
        let c = match s.state {
            SkillState::Unavailable(_) => Color::srgba(0.30, 0.10, 0.18, 0.42),
            _ => Color::NONE,
        };
        set_bg(&mut b, c);
    }
    for (i, mut t) in &mut times {
        let Some(s) = model.skills.get(i.0) else { continue };
        let label = match s.state {
            SkillState::Cooldown { left, .. } if left >= 1.0 => format!("{:.0}", left.ceil()),
            SkillState::Cooldown { left, .. } => format!("{left:.1}"),
            _ => String::new(),
        };
        set_text(&mut t, &label);
    }
    // Key labels: the chip's text, dimmed when the slot can't be used.
    for (k, children) in &keys {
        let Some(s) = model.skills.get(k.0) else { continue };
        for chip in children.iter() {
            let Ok(inner) = chips.get(chip) else { continue };
            for e in inner.iter() {
                if let Ok((mut t, mut c)) = key_texts.get_mut(e) {
                    set_text(&mut t, s.key.label());
                    set_color(&mut c, if matches!(s.state, SkillState::Unavailable(_) | SkillState::Empty) { theme::MUTED } else { theme::TEXT });
                }
            }
        }
    }
}

pub fn hint(model: Res<HudModel>, mut root: Query<&mut Node, With<HintRoot>>, mut key: Query<&mut Text, (With<HintKey>, Without<HintLabel>)>, mut label: Query<&mut Text, (With<HintLabel>, Without<HintKey>)>) {
    let on = model.hint.is_some() && model.death.is_none();
    for mut n in &mut root {
        show(&mut n, on);
    }
    if let Some(h) = &model.hint {
        for mut t in &mut key {
            set_text(&mut t, &h.key);
        }
        for mut t in &mut label {
            set_text(&mut t, &h.label);
        }
    }
}

#[allow(clippy::type_complexity)]
pub fn target(
    model: Res<HudModel>,
    icons: Res<Icons>,
    mut root: Query<(&mut Node, &mut BorderColor), (With<TargetRoot>, Without<TargetBar>, Without<TargetFill>, Without<TargetDoing>)>,
    mut accent: Query<&mut BackgroundColor, (With<TargetAccent>, Without<TargetMarker>)>,
    mut marker: Query<&mut BackgroundColor, (With<TargetMarker>, Without<TargetAccent>)>,
    mut name: Query<(&mut Text, &mut TextColor), With<TargetName>>,
    mut doing: Query<(&mut Node, &mut ImageNode), (With<TargetDoing>, Without<TargetRoot>, Without<TargetBar>, Without<TargetFill>)>,
    mut bar: Query<&mut Node, (With<TargetBar>, Without<TargetRoot>, Without<TargetFill>, Without<TargetDoing>)>,
    mut fill: Query<&mut Node, (With<TargetFill>, Without<TargetRoot>, Without<TargetBar>, Without<TargetDoing>)>,
) {
    let t = model.target.as_ref().filter(|_| model.death.is_none());
    for (mut n, mut b) in &mut root {
        show(&mut n, t.is_some());
        if let Some(t) = t {
            let c = theme::with_alpha(theme::stance(t.stance), 0.45);
            if b.top != c {
                *b = BorderColor::all(c);
            }
        }
    }
    let Some(t) = t else { return };
    let c = theme::stance(t.stance);
    for mut a in &mut accent {
        set_bg(&mut a, c);
    }
    for mut a in &mut marker {
        set_bg(&mut a, c);
    }
    for (mut x, mut col) in &mut name {
        set_text(&mut x, &t.name);
        set_color(&mut col, if t.stance == Stance::Hostile { Color::srgb(1.0, 0.78, 0.76) } else { theme::TEXT });
    }
    for (mut n, mut img) in &mut doing {
        show(&mut n, t.doing.is_some());
        if let Some(k) = t.doing {
            let h = icons.get(Glyph::Status(k));
            if img.image != h {
                img.image = h;
            }
            let col = if k == StatusKind::InCombat { theme::HOSTILE } else { theme::TALK };
            if img.color != col {
                img.color = col;
            }
        }
    }
    for mut n in &mut bar {
        show(&mut n, t.hp.is_some());
    }
    if let Some(hp) = t.hp {
        for mut n in &mut fill {
            set_width(&mut n, Val::Percent(hp.clamp(0.0, 1.0) * 100.0));
        }
    }
}

pub fn vignette(model: Res<HudModel>, time: Res<Time>, mut q: Query<&mut BackgroundGradient, With<Vignette>>) {
    let low = model.me.as_ref().map_or(0.0, |m| 1.0 - (m.hp / m.max_hp.max(1.0) / 0.35).clamp(0.0, 1.0)).sqrt();
    let pulse = if crate::capture::scripted() { 1.0 } else { 0.8 + 0.2 * (time.elapsed_secs() * 3.2).sin() };
    let a = if model.death.is_some() { 0.0 } else { low * 0.7 * pulse };
    for mut g in &mut q {
        let want = if a <= 0.001 {
            BackgroundGradient::default()
        } else {
            BackgroundGradient::from(Gradient::Radial(bevy::ui::RadialGradient {
                position: UiPosition::CENTER,
                shape: bevy::ui::RadialGradientShape::FarthestCorner,
                stops: vec![ColorStop::percent(Color::srgba(0.6, 0.02, 0.05, 0.0), 0.0), ColorStop::percent(Color::srgba(0.6, 0.02, 0.05, 0.0), 55.0), ColorStop::percent(Color::srgba(0.6, 0.02, 0.05, a * 0.45), 82.0), ColorStop::percent(Color::srgba(0.6, 0.02, 0.05, a), 100.0)],
                color_space: bevy::ui::InterpolationColorSpace::Srgba,
            }))
        };
        if *g != want {
            *g = want;
        }
    }
}
