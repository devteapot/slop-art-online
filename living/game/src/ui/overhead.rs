//! Over heads: nameplates for characters that matter now (hovered, targeted, hostile, or
//! looked over: while an appraisal holds, a small `hp / max` under the bar), fading with distance, and speech bubbles that never overlap. A speaker's bubble carries their name,
//! so speaking alone adds no nameplate.
//!
//! Bubbles stack: the nearest speaker's bubble sits on its head, and any bubble that would
//! overlap one already placed is lifted above it, with a thin leader line down to its speaker.
//! Lifts ease, so bubbles slide rather than jump as speakers move.

use super::model::*;
use super::theme::{self, Fonts};
use super::{set_bg, set_color, set_text, set_width, show, HudRoot};
use bevy::prelude::*;
use bevy::ui::{BoxShadow, ComputedNode, GlobalZIndex, UiTransform};
use std::collections::HashMap;

const PLATES: usize = 12;
const BUBBLES: usize = 8;
/// Wrapper width (Val px) that plates and bubbles are centred in.
const WRAP: f32 = 320.0;

#[derive(Component)]
pub struct Plate(usize);
#[derive(Component)]
pub struct PlateName(usize);
#[derive(Component)]
pub struct PlatePill(usize);
#[derive(Component)]
pub struct PlateMarker(usize);
#[derive(Component)]
pub struct PlateBar(usize);
#[derive(Component)]
pub struct PlateFill(usize);
#[derive(Component)]
pub struct PlateExact(usize);

#[derive(Component)]
pub struct BubbleRoot(usize);
#[derive(Component)]
pub struct BubbleBody(usize);
#[derive(Component)]
pub struct BubbleName(usize);
#[derive(Component)]
pub struct BubbleText(usize);
#[derive(Component)]
pub struct BubbleTail(usize);
#[derive(Component)]
pub struct BubbleLeader(usize);

/// Eased lift of each speaker's bubble (Val px), and its last measured size.
#[derive(Resource, Default)]
pub struct Stack {
    lift: HashMap<u64, f32>,
}

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = fonts.clone();
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), ..default() }, GlobalZIndex(-5), Pickable::IGNORE))
        .with_children(|layer| {
            for i in 0..PLATES {
                layer
                    .spawn((Plate(i), Node { position_type: PositionType::Absolute, width: Val::Px(WRAP), flex_direction: FlexDirection::Column, align_items: AlignItems::Center, display: Display::None, ..default() }))
                    .with_children(|p| {
                        // A soft ink pill keeps names readable over any ground.
                        p.spawn((PlatePill(i), Node { flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(5.0), padding: UiRect::axes(Val::Px(8.0), Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(999.0)), ..default() }, BackgroundColor(Color::NONE))).with_children(|r| {
                            r.spawn((PlateMarker(i), Node { width: Val::Px(7.0), height: Val::Px(7.0), ..default() }, UiTransform::from_rotation(Rot2::degrees(45.0)), BackgroundColor(theme::HOSTILE)));
                            r.spawn((PlateName(i), Text::new(""), f.body(15.5, 800), TextColor(theme::TEXT), theme::text_shadow()));
                        });
                        p.spawn((PlateBar(i), Node { width: Val::Px(62.0), height: Val::Px(5.0), margin: UiRect::top(Val::Px(3.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(3.0)), overflow: Overflow::clip(), ..default() }, BackgroundColor(theme::TRACK), BorderColor::all(Color::srgba(0.0, 0.0, 0.0, 0.5))))
                            .with_child((PlateFill(i), Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), ..default() }, BackgroundColor(theme::HP_HI)));
                        p.spawn((PlateExact(i), Node { display: Display::None, margin: UiRect::top(Val::Px(1.0)), ..default() }, Text::new(""), f.body(11.5, 700), TextColor(theme::TEXT), theme::text_shadow()));
                    });
            }
            for i in 0..BUBBLES {
                layer
                    .spawn((BubbleRoot(i), Node { position_type: PositionType::Absolute, width: Val::Px(WRAP), flex_direction: FlexDirection::Column, align_items: AlignItems::Center, display: Display::None, ..default() }))
                    .with_children(|b| {
                        b.spawn((
                            BubbleBody(i),
                            Node { max_width: Val::Px(272.0), flex_direction: FlexDirection::Column, padding: UiRect::new(Val::Px(12.0), Val::Px(12.0), Val::Px(6.0), Val::Px(8.0)), border_radius: BorderRadius::all(Val::Px(13.0)), ..default() },
                            BackgroundColor(theme::BUBBLE),
                            BoxShadow::new(Color::srgba(0.0, 0.0, 0.05, 0.3), Val::ZERO, Val::Px(3.0), Val::ZERO, Val::Px(10.0)),
                        ))
                        .with_children(|body| {
                            body.spawn((BubbleName(i), Text::new(""), f.body(12.0, 800), TextColor(Color::srgb(0.24, 0.43, 0.62))));
                            body.spawn((BubbleText(i), Text::new(""), f.body(14.5, 600), TextColor(theme::BUBBLE_TEXT), TextLayout::new(Justify::Left, LineBreak::WordBoundary)));
                        });
                        b.spawn((BubbleTail(i), Node { width: Val::Px(11.0), height: Val::Px(11.0), margin: UiRect::top(Val::Px(-6.0)), ..default() }, UiTransform::from_rotation(Rot2::degrees(45.0)), BackgroundColor(theme::BUBBLE)));
                        b.spawn((BubbleLeader(i), Node { width: Val::Px(2.0), height: Val::Px(0.0), border_radius: BorderRadius::all(Val::Px(1.0)), ..default() }, BackgroundColor(theme::with_alpha(theme::BUBBLE, 0.7))));
                    });
            }
        });
}

fn smoothstep(a: f32, b: f32, x: f32) -> f32 {
    let t = ((x - a) / (b - a)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

fn place(n: &mut Node, left: f32, bottom: f32) {
    let (l, b) = (Val::Px(left.round()), Val::Px(bottom.round()));
    if n.left != l {
        n.left = l;
    }
    if n.bottom != b {
        n.bottom = b;
    }
}

/// Which actors get a nameplate now, with their screen point (Val px) and opacity.
fn relevant<'a>(model: &'a HudModel, project: impl Fn(Vec3) -> Option<Vec2>) -> Vec<(Vec2, f32, &'a Actor)> {
    if model.death.is_some() {
        return Vec::new();
    }
    model
        .actors
        .iter()
        .filter(|a| a.hovered || a.targeted || a.greeted || a.exact.is_some() || a.stance == Stance::Hostile)
        .filter_map(|a| {
            let p = project(a.head)?;
            let mut alpha = 1.0 - smoothstep(14.0, 32.0, a.distance);
            if a.hovered || a.targeted || a.greeted || a.exact.is_some() {
                alpha = alpha.max(0.9);
            }
            (alpha >= 0.02).then_some((p, alpha, a))
        })
        .take(PLATES)
        .collect()
}

/// The camera's projection into UI units (Val px): this frame's placement (the camera has no
/// parent; its propagated transform lags a frame) and the UI scale.
fn projector<'a>(camera: &'a Camera, tf: &Transform, scale: f32) -> impl Fn(Vec3) -> Option<Vec2> + 'a {
    let gtf = GlobalTransform::from(*tf);
    let s = scale.max(0.1);
    move |p| camera.world_to_viewport(&gtf, p).ok().map(|v| v / s)
}

#[allow(clippy::type_complexity)]
pub fn plates(
    model: Res<HudModel>,
    ui_scale: Res<UiScale>,
    camq: Query<(&Camera, &Transform), With<Camera3d>>,
    mut plates: Query<(&Plate, &mut Node), (Without<PlateMarker>, Without<PlateBar>, Without<PlateFill>)>,
    mut names: Query<(&PlateName, &mut Text, &mut TextColor)>,
    mut markers: Query<(&PlateMarker, &mut Node, &mut BackgroundColor), (Without<Plate>, Without<PlateBar>, Without<PlateFill>)>,
    mut bars: Query<(&PlateBar, &mut Node), (Without<Plate>, Without<PlateMarker>, Without<PlateFill>)>,
    mut fills: Query<(&PlateFill, &mut Node), (Without<Plate>, Without<PlateMarker>, Without<PlateBar>)>,
    mut pills: Query<(&PlatePill, &mut BackgroundColor), Without<PlateMarker>>,
    mut exacts: Query<(&PlateExact, &mut Node, &mut Text, &mut TextColor), (Without<Plate>, Without<PlateMarker>, Without<PlateBar>, Without<PlateFill>, Without<PlateName>)>,
) {
    let Ok((camera, tf)) = camq.single() else { return };
    let Some(view) = camera.logical_viewport_size() else { return };
    let h = view.y / ui_scale.0.max(0.1);
    let list = relevant(&model, projector(camera, tf, ui_scale.0));
    let shown = |i: usize| list.get(i).copied();
    for (pl, mut n) in &mut plates {
        show(&mut n, shown(pl.0).is_some());
        if let Some((p, _, _)) = shown(pl.0) {
            place(&mut n, p.x - WRAP / 2.0, h - p.y);
        }
    }
    for (pn, mut t, mut c) in &mut names {
        if let Some((_, alpha, a)) = shown(pn.0) {
            set_text(&mut t, &a.name);
            let col = if a.stance == Stance::Hostile {
                theme::HOSTILE
            } else if a.targeted {
                theme::GOLD
            } else if a.talking {
                theme::TALK
            } else {
                theme::TEXT
            };
            set_color(&mut c, theme::with_alpha(col, alpha));
        }
    }
    for (pm, mut n, mut b) in &mut markers {
        show(&mut n, shown(pm.0).is_some_and(|(_, _, a)| a.stance == Stance::Hostile || a.targeted));
        if let Some((_, alpha, a)) = shown(pm.0) {
            set_bg(&mut b, theme::with_alpha(theme::stance(a.stance), alpha));
        }
    }
    for (pp, mut b) in &mut pills {
        if let Some((_, alpha, _)) = shown(pp.0) {
            set_bg(&mut b, Color::srgba(0.05, 0.06, 0.1, 0.5 * alpha));
        }
    }
    for (pb, mut n) in &mut bars {
        show(&mut n, shown(pb.0).is_some_and(|(_, _, a)| a.hp.is_some()));
    }
    for (pf, mut n) in &mut fills {
        if let Some(hp) = shown(pf.0).and_then(|(_, _, a)| a.hp) {
            set_width(&mut n, Val::Percent(hp.clamp(0.0, 1.0) * 100.0));
        }
    }
    for (pe, mut n, mut t, mut c) in &mut exacts {
        let exact = shown(pe.0).and_then(|(_, alpha, a)| a.exact.map(|e| (e, alpha)));
        show(&mut n, exact.is_some());
        if let Some(((hp, max), alpha)) = exact {
            set_text(&mut t, &format!("{:.0} / {:.0}", hp.ceil(), max));
            set_color(&mut c, theme::with_alpha(theme::TEXT, 0.85 * alpha));
        }
    }
}

/// Speech bubbles: nearest first, each lifted clear of those already placed.
#[allow(clippy::type_complexity, clippy::too_many_arguments)]
pub fn bubbles(
    model: Res<HudModel>,
    ui_scale: Res<UiScale>,
    time: Res<Time>,
    mut stack: ResMut<Stack>,
    camq: Query<(&Camera, &Transform), With<Camera3d>>,
    mut roots: Query<(&BubbleRoot, &mut Node), Without<BubbleLeader>>,
    bodies: Query<(&BubbleBody, &ComputedNode)>,
    mut body_bg: Query<(&BubbleBody, &mut BackgroundColor), (Without<BubbleTail>, Without<BubbleLeader>)>,
    mut tails: Query<(&BubbleTail, &mut BackgroundColor), (Without<BubbleBody>, Without<BubbleLeader>)>,
    mut leaders: Query<(&BubbleLeader, &mut Node, &mut BackgroundColor), (Without<BubbleBody>, Without<BubbleTail>, Without<BubbleRoot>)>,
    mut names: Query<(&BubbleName, &mut Text, &mut TextColor), Without<BubbleText>>,
    mut texts: Query<(&BubbleText, &mut Text, &mut TextColor), Without<BubbleName>>,
) {
    let Ok((camera, tf)) = camq.single() else { return };
    let Some(view) = camera.logical_viewport_size() else { return };
    let s = ui_scale.0.max(0.1);
    let (w, h) = (view.x / s, view.y / s);
    let project = projector(camera, tf, ui_scale.0);
    let plates = relevant(&model, &project);
    let plated: Vec<u64> = plates.iter().map(|(_, _, a)| a.id).collect();
    let cam_at = tf.translation;
    let mut order: Vec<(usize, &Bubble)> = if model.death.is_some() { Vec::new() } else { model.bubbles.iter().take(BUBBLES).enumerate().collect() };
    order.sort_by(|a, b| a.1.head.distance(cam_at).total_cmp(&b.1.head.distance(cam_at)));
    let sizes: HashMap<usize, Vec2> = bodies.iter().map(|(b, c)| (b.0, c.size() * c.inverse_scale_factor())).collect();
    // Nameplates are obstacles too, so a bubble never hides a target's name (width estimated
    // from the name; plates are one line).
    let mut placed: Vec<(Option<u64>, Rect)> = plates
        .iter()
        .map(|(p, _, a)| {
            let half = (a.name.chars().count() as f32 * 8.6 + 34.0) / 2.0;
            (Some(a.id), Rect::new(p.x - half, p.y - 22.0, p.x + half, p.y))
        })
        .collect();
    let mut slot_of: [Option<(f32, f32, f32, f32, &Bubble)>; BUBBLES] = [None; BUBBLES];
    let dt = time.delta_secs();
    let still = crate::capture::scripted();
    for (slot, b) in order {
        let Some(p) = project(b.head) else { continue };
        let size = sizes.get(&slot).copied().filter(|s| s.x > 1.0).unwrap_or(Vec2::new(180.0, 46.0)) + Vec2::new(0.0, 6.0);
        let base = p.y - if plated.contains(&b.speaker) { 24.0 } else { 6.0 };
        let x = p.x.clamp(size.x / 2.0 + 8.0, w - size.x / 2.0 - 8.0);
        // Rise past whatever it overlaps (its own speaker's plate sits below it already).
        let mut lift: f32 = 0.0;
        for _ in 0..placed.len() + 1 {
            let r = Rect::new(x - size.x / 2.0 - 3.0, base - lift - size.y - 3.0, x + size.x / 2.0 + 3.0, base - lift + 3.0);
            match placed.iter().find(|(id, o)| *id != Some(b.speaker) && !o.intersect(r).is_empty()) {
                Some((_, o)) => lift = lift.max(base - o.min.y + 1.0),
                None => break,
            }
        }
        placed.push((None, Rect::new(x - size.x / 2.0, base - lift - size.y, x + size.x / 2.0, base - lift)));
        let eased = stack.lift.entry(b.speaker).or_insert(lift);
        *eased = if still { lift } else { *eased + (lift - *eased) * (1.0 - (-dt * 10.0).exp()) };
        let fade_in = (b.age / 0.18).clamp(0.0, 1.0);
        let fade_out = ((b.life - b.age) / 0.6).clamp(0.0, 1.0);
        let alpha = fade_in.min(fade_out) * (1.0 - smoothstep(16.0, 34.0, b.head.distance(cam_at) - 10.0));
        slot_of[slot] = Some((x, base, *eased, alpha, b));
    }
    let live: Vec<u64> = model.bubbles.iter().map(|b| b.speaker).collect();
    stack.lift.retain(|k, _| live.contains(k));

    for (br, mut n) in &mut roots {
        show(&mut n, slot_of[br.0].is_some());
        if let Some((x, base, _, _, _)) = slot_of[br.0] {
            place(&mut n, x - WRAP / 2.0, h - base);
        }
    }
    for (bl, mut n, mut c) in &mut leaders {
        if let Some((_, _, lift, alpha, _)) = slot_of[bl.0] {
            let hgt = Val::Px((lift - 2.0).max(0.0).round());
            if n.height != hgt {
                n.height = hgt;
            }
            set_bg(&mut c, theme::with_alpha(theme::BUBBLE, 0.75 * alpha));
        }
    }
    for (bb, mut c) in &mut body_bg {
        if let Some((_, _, _, alpha, _)) = slot_of[bb.0] {
            set_bg(&mut c, theme::with_alpha(theme::BUBBLE, alpha));
        }
    }
    for (bt, mut c) in &mut tails {
        if let Some((_, _, _, alpha, _)) = slot_of[bt.0] {
            set_bg(&mut c, theme::with_alpha(theme::BUBBLE, alpha));
        }
    }
    for (bn, mut t, mut c) in &mut names {
        if let Some((_, _, _, alpha, b)) = slot_of[bn.0] {
            set_text(&mut t, &b.name);
            let col = if b.mine { Color::srgb(0.62, 0.43, 0.12) } else { Color::srgb(0.24, 0.43, 0.62) };
            set_color(&mut c, theme::with_alpha(col, alpha));
        }
    }
    for (bt, mut t, mut c) in &mut texts {
        if let Some((_, _, _, alpha, b)) = slot_of[bt.0] {
            set_text(&mut t, &b.text);
            set_color(&mut c, theme::with_alpha(theme::BUBBLE_TEXT, alpha));
        }
    }
}
