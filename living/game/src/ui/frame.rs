//! The target frame at the top centre (until the fight plate of interface D's step 6) and the
//! low-health vignette. The cluster is `cluster.rs`.

use super::icons::{Glyph, Icons};
use super::model::*;
use super::theme::{self, Fonts};
use super::{set_bg, set_color, set_text, set_width, show, HudRoot};
use bevy::prelude::*;
use bevy::ui::{BackgroundGradient, ColorStop, GlobalZIndex, Gradient, LinearGradient, UiPosition, UiTransform};

/// Width of the cluster: seven 54 px slots with gaps and two group gaps.
const WIDTH: f32 = 54.0 * 7.0 + 6.0 * 4.0 + 16.0 * 2.0;
const SLOT: f32 = 54.0;
const STATUS_SLOTS: usize = 6;

#[derive(Component)]
pub struct HpFill;
/// Health as a number on its bar ("87 / 100").
#[derive(Component)]
pub struct HpText;
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

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = fonts.clone();
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
