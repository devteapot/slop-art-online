//! The death screen: how you died, who saw it, then "Arrive as a new stranger". Death is
//! permanent; the new character inherits nothing (docs/GAME_BRIEF.md).

use super::model::*;
use super::theme::{self, Fonts};
use super::{set_text, show, HudRoot};
use bevy::prelude::*;
use bevy::ui::{BackgroundGradient, ColorStop, GlobalZIndex, Gradient, LinearGradient, RadialGradient, RadialGradientShape, UiPosition};

#[derive(Component)]
pub struct DeathRoot;
#[derive(Component)]
pub struct DeathCause;
#[derive(Component)]
pub struct DeathLived;
#[derive(Component)]
pub struct DeathSeen;
#[derive(Component)]
pub struct Witness(usize);
#[derive(Component)]
pub struct WitnessName(usize);
#[derive(Component)]
pub struct DeathNoOne;
#[derive(Component)]
pub struct Rejoin;

const WITNESSES: usize = 6;

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = fonts.clone();
    commands
        .spawn((
            HudRoot,
            DeathRoot,
            Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), flex_direction: FlexDirection::Column, align_items: AlignItems::Center, justify_content: JustifyContent::Center, display: Display::None, ..default() },
            BackgroundGradient::from(Gradient::Radial(RadialGradient {
                position: UiPosition::CENTER,
                shape: RadialGradientShape::FarthestCorner,
                stops: vec![ColorStop::percent(Color::srgba(0.03, 0.03, 0.06, 0.62), 0.0), ColorStop::percent(Color::srgba(0.02, 0.02, 0.04, 0.80), 55.0), ColorStop::percent(Color::srgba(0.0, 0.0, 0.02, 0.94), 100.0)],
                color_space: default(),
            })),
            GlobalZIndex(50),
        ))
        .with_children(|root| {
            root.spawn((Text::new("You have died"), f.title(62.0), TextColor(Color::srgb(0.97, 0.93, 0.86)), theme::text_shadow()));
            // An ornament line, gold fading at both ends.
            root.spawn((
                Node { width: Val::Px(360.0), height: Val::Px(2.0), margin: UiRect::new(Val::ZERO, Val::ZERO, Val::Px(16.0), Val::Px(20.0)), ..default() },
                BackgroundGradient::from(LinearGradient::to_right(vec![ColorStop::percent(Color::NONE, 0.0), ColorStop::percent(theme::GOLD, 50.0), ColorStop::percent(Color::NONE, 100.0)])),
            ));
            root.spawn((DeathCause, Text::new(""), f.body(22.0, 700), TextColor(theme::TEXT), theme::text_shadow(), TextLayout::justify(Justify::Center)));
            root.spawn((DeathLived, Text::new(""), f.body(15.0, 600), TextColor(theme::MUTED), Node { margin: UiRect::top(Val::Px(8.0)), ..default() }));
            root.spawn((DeathSeen, Node { flex_direction: FlexDirection::Column, align_items: AlignItems::Center, margin: UiRect::top(Val::Px(30.0)), row_gap: Val::Px(10.0), ..default() })).with_children(|seen| {
                seen.spawn((Text::new("SEEN BY"), f.body(11.5, 800), TextColor(theme::with_alpha(theme::GOLD, 0.75))));
                seen.spawn(Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(8.0), ..default() }).with_children(|row| {
                    for i in 0..WITNESSES {
                        row.spawn((Witness(i), Node { padding: UiRect::axes(Val::Px(12.0), Val::Px(5.0)), border: UiRect::all(Val::Px(1.0)), border_radius: BorderRadius::all(Val::Px(999.0)), ..default() }, BackgroundColor(theme::INK), BorderColor::all(theme::EDGE_STRONG)))
                            .with_child((WitnessName(i), Text::new(""), f.body(14.0, 700), TextColor(theme::TEXT)));
                    }
                });
                seen.spawn((DeathNoOne, Text::new("No one is known to have seen it."), f.body(14.0, 600), TextColor(theme::MUTED)));
            });
            root.spawn((
                Rejoin,
                Node { margin: UiRect::top(Val::Px(44.0)), padding: UiRect::axes(Val::Px(34.0), Val::Px(13.0)), border: UiRect::all(Val::Px(1.5)), border_radius: BorderRadius::all(Val::Px(999.0)), ..default() },
                BackgroundGradient::from(LinearGradient::to_bottom(vec![ColorStop::percent(Color::srgba(0.98, 0.86, 0.58, 0.95), 0.0), ColorStop::percent(Color::srgba(0.80, 0.62, 0.32, 0.95), 100.0)])),
                BorderColor::all(Color::srgb(1.0, 0.93, 0.76)),
                bevy::ui::BoxShadow::new(Color::srgba(0.95, 0.75, 0.35, 0.35), Val::ZERO, Val::ZERO, Val::Px(2.0), Val::Px(22.0)),
            ))
            .with_child((Text::new("Arrive as a new stranger"), f.body(18.0, 800), TextColor(Color::srgb(0.18, 0.12, 0.05)), Pickable::IGNORE))
            .observe(|_: On<bevy::picking::events::PointerClick>, mut out: ResMut<Outbox>| out.rejoin = true);
            root.spawn((Text::new("Nothing you had comes with you."), f.body(13.0, 600), TextColor(theme::MUTED), Node { margin: UiRect::top(Val::Px(14.0)), ..default() }));
        });
}

#[allow(clippy::type_complexity)]
pub fn update(
    model: Res<HudModel>,
    keys: Res<ButtonInput<KeyCode>>,
    mut out: ResMut<Outbox>,
    mut root: Query<&mut Node, (With<DeathRoot>, Without<Witness>, Without<DeathSeen>, Without<DeathNoOne>)>,
    mut texts: ParamSet<(Query<&mut Text, With<DeathCause>>, Query<&mut Text, With<DeathLived>>, Query<(&WitnessName, &mut Text)>)>,
    mut seen: Query<&mut Node, (With<DeathSeen>, Without<DeathRoot>, Without<Witness>, Without<DeathNoOne>)>,
    mut chips: Query<(&Witness, &mut Node), (Without<DeathRoot>, Without<DeathSeen>, Without<DeathNoOne>)>,
    mut no_one: Query<&mut Node, (With<DeathNoOne>, Without<DeathRoot>, Without<Witness>, Without<DeathSeen>)>,
) {
    let d = model.death.as_ref();
    for mut n in &mut root {
        show(&mut n, d.is_some());
    }
    let Some(d) = d else { return };
    let cause = match &d.place {
        Some(p) => format!("{}\n{p}", d.cause),
        None => d.cause.clone(),
    };
    for mut t in &mut texts.p0() {
        set_text(&mut t, &cause);
    }
    for mut t in &mut texts.p1() {
        set_text(&mut t, &d.lived.as_ref().map_or(String::new(), |l| format!("You lived {l}.")));
    }
    let names: &[String] = d.witnesses.as_deref().unwrap_or(&[]);
    for (w, mut t) in &mut texts.p2() {
        if let Some(n) = names.get(w.0) {
            set_text(&mut t, n);
        }
    }
    for (w, mut n) in &mut chips {
        show(&mut n, w.0 < names.len());
    }
    // Who saw it: when the authority doesn't say, say nothing rather than guess.
    for mut n in &mut seen {
        show(&mut n, d.witnesses.is_some());
    }
    for mut n in &mut no_one {
        show(&mut n, d.witnesses.as_ref().is_some_and(|w| w.is_empty()));
    }
    if keys.just_pressed(KeyCode::Enter) {
        out.rejoin = true;
    }
}
