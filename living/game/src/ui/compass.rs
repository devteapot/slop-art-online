//! A compact compass-map at the top right: it turns with the view, shows north and nearby
//! points of interest (settlements, known places), and your facing in the middle. Beyond its
//! range, points sit on the rim. Terrain is not drawn yet (a later minimap texture).

use super::icons::{Glyph, Icons};
use super::model::*;
use super::theme::{self, Fonts};
use super::{show, HudRoot};
use bevy::prelude::*;
use bevy::ui::{BackgroundGradient, ColorStop, Gradient, RadialGradient, RadialGradientShape, UiPosition, UiTransform};

const SIZE: f32 = 112.0;
/// Metres from the centre to the inner ring.
const RANGE: f32 = 320.0;
const INNER: f32 = 36.0;
const RIM: f32 = 47.0;
const POIS: usize = 8;
const TICKS: usize = 8;

#[derive(Component)]
pub struct Cardinal(u8);
#[derive(Component)]
pub struct Tick(usize);
#[derive(Component)]
pub struct PoiIcon(usize);
#[derive(Component)]
pub struct Facing;

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>, icons: Res<Icons>) {
    let f = fonts.clone();
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, right: Val::Px(22.0), top: Val::Px(20.0), ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            root.spawn((
                Node { width: Val::Px(SIZE), height: Val::Px(SIZE), border: UiRect::all(Val::Px(1.5)), border_radius: BorderRadius::all(Val::Percent(50.0)), ..default() },
                BackgroundGradient::from(Gradient::Radial(RadialGradient {
                    position: UiPosition::CENTER,
                    shape: RadialGradientShape::ClosestSide,
                    stops: vec![ColorStop::percent(Color::srgba(0.10, 0.12, 0.18, 0.42), 0.0), ColorStop::percent(Color::srgba(0.07, 0.085, 0.13, 0.55), 80.0), ColorStop::percent(Color::srgba(0.05, 0.06, 0.1, 0.66), 100.0)],
                    color_space: default(),
                })),
                BorderColor::all(theme::EDGE),
            ))
            .with_children(|disc| {
                let c = SIZE / 2.0 - 1.5;
                // Range ring.
                disc.spawn((Node { position_type: PositionType::Absolute, left: Val::Px(c - INNER), top: Val::Px(c - INNER), width: Val::Px(INNER * 2.0), height: Val::Px(INNER * 2.0), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Percent(50.0)), ..default() }, BorderColor::all(theme::EDGE)));
                for i in 0..TICKS {
                    disc.spawn((Tick(i), Node { position_type: PositionType::Absolute, width: Val::Px(3.0), height: Val::Px(3.0), border_radius: BorderRadius::all(Val::Percent(50.0)), ..default() }, BackgroundColor(theme::with_alpha(theme::TEXT, 0.28))));
                }
                for i in 0..POIS {
                    disc.spawn((PoiIcon(i), Node { position_type: PositionType::Absolute, width: Val::Px(14.0), height: Val::Px(14.0), display: Display::None, ..default() }, ImageNode::new(Handle::default())));
                }
                // Only north is marked; the ticks give the other quarters.
                disc.spawn((Cardinal(0), Node { position_type: PositionType::Absolute, width: Val::Px(20.0), height: Val::Px(20.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, ..default() }))
                    .with_child((Text::new("N"), f.body(12.5, 850), TextColor(theme::GOLD), theme::text_shadow()));
                disc.spawn((Facing, Node { position_type: PositionType::Absolute, left: Val::Px(c - 8.0), top: Val::Px(c - 8.0), width: Val::Px(16.0), height: Val::Px(16.0), ..default() }, ImageNode::new(icons.get(Glyph::Arrow)).with_color(theme::GOLD), UiTransform::default()));
            });
        });
}

#[allow(clippy::type_complexity)]
pub fn update(
    model: Res<HudModel>,
    icons: Res<Icons>,
    mut cards: Query<(&Cardinal, &mut Node), (Without<Tick>, Without<PoiIcon>, Without<Facing>)>,
    mut ticks: Query<(&Tick, &mut Node), (Without<Cardinal>, Without<PoiIcon>, Without<Facing>)>,
    mut pois: Query<(&PoiIcon, &mut Node, &mut ImageNode), (Without<Cardinal>, Without<Tick>, Without<Facing>)>,
    mut facing: Query<(&mut UiTransform, &mut ImageNode), (With<Facing>, Without<PoiIcon>)>,
) {
    let m = &model.map;
    let c = SIZE / 2.0 - 1.5;
    let y = m.yaw.to_radians();
    let (up, right) = (Vec2::new(y.sin(), -y.cos()), Vec2::new(y.cos(), y.sin()));
    // A ground direction (game x, z) as a screen direction (x right, y down).
    let to_screen = |d: Vec2| Vec2::new(d.dot(right), -d.dot(up));
    let at = |n: &mut Node, p: Vec2, half: f32| {
        let (l, t) = (Val::Px((c + p.x - half).round()), Val::Px((c + p.y - half).round()));
        if n.left != l {
            n.left = l;
        }
        if n.top != t {
            n.top = t;
        }
    };
    for (k, mut n) in &mut cards {
        let dir = [Vec2::new(0.0, -1.0), Vec2::new(1.0, 0.0), Vec2::new(0.0, 1.0), Vec2::new(-1.0, 0.0)][k.0 as usize];
        at(&mut n, to_screen(dir) * RIM, 10.0);
    }
    for (t, mut n) in &mut ticks {
        let a = (t.0 as f32 + 0.5) * std::f32::consts::TAU / TICKS as f32;
        at(&mut n, to_screen(Vec2::new(a.sin(), -a.cos())) * RIM, 1.5);
    }
    let me = m.me.unwrap_or_default();
    let mut list: Vec<(&Poi, f32)> = m.pois.iter().map(|p| (p, p.at.distance(me))).collect();
    list.sort_by(|a, b| a.1.total_cmp(&b.1));
    for (i, mut n, mut img) in &mut pois {
        let Some((p, d)) = list.get(i.0).filter(|_| m.me.is_some()) else {
            show(&mut n, false);
            continue;
        };
        show(&mut n, true);
        let dir = to_screen((p.at - me).normalize_or_zero());
        let far = *d > RANGE;
        let r = if far { RIM - 1.0 } else { d / RANGE * INNER };
        at(&mut n, dir * r, 7.0);
        let h = icons.get(Glyph::Poi(p.kind));
        if img.image != h {
            img.image = h;
        }
        let col = if far { theme::with_alpha(theme::TEXT, 0.4) } else { theme::with_alpha(Color::srgb(0.98, 0.92, 0.78), 0.9) };
        if img.color != col {
            img.color = col;
        }
    }
    for (mut tf, mut img) in &mut facing {
        let on = m.facing.is_some();
        let col = if on { theme::GOLD } else { Color::NONE };
        if img.color != col {
            img.color = col;
        }
        if let Some(f) = m.facing.filter(|f| f.length_squared() > 1e-6) {
            let s = to_screen(f.normalize());
            let rot = Rot2::radians(s.x.atan2(-s.y));
            if tf.rotation != rot {
                tf.rotation = rot;
            }
        }
    }
}
