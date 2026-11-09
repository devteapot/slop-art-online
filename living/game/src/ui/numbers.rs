//! Floating combat numbers: small, short-lived figures rising over whoever was hit or healed
//! (only blows my character dealt, took or saw healed: the authority sends amounts to the two
//! involved). Minimal by design (docs/GAME_BRIEF.md HUD): no labels, colour says what it was.

use super::model::*;
use super::theme::{self, Fonts};
use super::{set_color, set_text, show, HudRoot};
use bevy::prelude::*;
use bevy::ui::GlobalZIndex;

const POOL: usize = 16;
/// How long a number stays (s), and how far it rises (px).
const LIFE: f32 = 1.1;
const RISE: f32 = 46.0;

#[derive(Component)]
pub struct Num(usize);

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = fonts.clone();
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), ..default() }, GlobalZIndex(-4), Pickable::IGNORE))
        .with_children(|layer| {
            for i in 0..POOL {
                layer.spawn((Num(i), Text::new(""), f.body(19.0, 800), TextColor(theme::TEXT), theme::text_shadow(), Node { position_type: PositionType::Absolute, width: Val::Px(80.0), display: Display::None, ..default() }, TextLayout::justify(Justify::Center)));
            }
        });
}

fn colour(kind: NumberKind) -> Color {
    match kind {
        NumberKind::Dealt => theme::GOLD,
        NumberKind::Taken => theme::HP_HI,
        NumberKind::Healed => theme::FRIENDLY,
        NumberKind::Blocked => Color::srgb(0.66, 0.80, 1.0),
    }
}

pub fn update(model: Res<HudModel>, ui_scale: Res<UiScale>, camq: Query<(&Camera, &Transform), With<Camera3d>>, mut q: Query<(&Num, &mut Text, &mut TextColor, &mut Node, &mut TextFont)>) {
    let Ok((camera, tf)) = camq.single() else { return };
    let gtf = GlobalTransform::from(*tf);
    let s = ui_scale.0.max(0.1);
    let shown: Vec<(Vec2, &FloatNumber)> = if model.death.is_some() {
        Vec::new()
    } else {
        model.numbers.iter().filter(|n| n.age < LIFE).filter_map(|n| camera.world_to_viewport(&gtf, n.at).ok().map(|p| (p / s, n))).take(POOL).collect()
    };
    for (num, mut t, mut c, mut node, mut font) in &mut q {
        let Some((p, n)) = shown.get(num.0) else {
            show(&mut node, false);
            continue;
        };
        show(&mut node, true);
        let k = (n.age / LIFE).clamp(0.0, 1.0);
        // A quick pop, then a rise and a fade; numbers on the same spot fan out by slot.
        let pop = if k < 0.12 { 1.0 + (0.12 - k) * 3.0 } else { 1.0 };
        let fan = ((num.0 % 3) as f32 - 1.0) * 14.0;
        let size = if n.kind == NumberKind::Taken { 21.0 } else { 18.0 } * pop;
        let px = FontSize::Px((size * 2.0).round() / 2.0);
        if font.font_size != px {
            font.font_size = px;
        }
        let (l, top) = (Val::Px((p.x - 40.0 + fan).round()), Val::Px((p.y - RISE * k).round()));
        if node.left != l {
            node.left = l;
        }
        if node.top != top {
            node.top = top;
        }
        let label = match n.kind {
            NumberKind::Healed => format!("+{:.0}", n.amount),
            _ => format!("{:.0}", n.amount.max(1.0)),
        };
        set_text(&mut t, &label);
        set_color(&mut c, theme::with_alpha(colour(n.kind), 1.0 - k * k));
    }
}
