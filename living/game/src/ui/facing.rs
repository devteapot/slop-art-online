//! Settings › Play: the world's laws a play scene may change (`crate::facing`).
//! - **Facing sight:** shown at all times as "Facing sight: on" or "off"; while on, with the
//!   field's five values (focal, side, side share, near, margin).
//! - **Walk speed:** the world's walk law (`facing::WALK_LAW`) as the installed script has it,
//!   with a choice of 2.6, 3.0 or 3.4 m/s.
//!
//! The switch, F5 and the choices work only when the play launcher gave this client the admin
//! link for its scratch world (`facing::set_law`); otherwise the lines are read-only.
//!
//! Its own module, filling the place `settings.rs` keeps for it ([`super::settings::FacingSight`]),
//! so the Settings page itself changes by one node.

use super::hit::{Tag, UiPointer};
use super::kit::{self, Lit};
use super::settings::FacingSight;
use super::theme::Fonts;
use super::{set_text, show, wood};
use crate::facing::FovState;
use bevy::prelude::*;

/// The tag of the switch.
pub const TAG: &str = "settings:facing_sight";
/// The walk speed's choices are tagged `settings:walk:<m/s>`.
pub const WALK_TAG: &str = "settings:walk";

/// The walk-speed row's state line.
#[derive(Component)]
pub struct WalkLine;
/// The walk-speed choices' row (hidden without the admin link).
#[derive(Component)]
pub struct WalkChoices;
/// The extra chip for a walk speed that is none of the choices (set elsewhere), selected.
#[derive(Component)]
pub struct WalkOther;
#[derive(Component)]
pub struct WalkOtherText;

/// The lines: 0 the state, 1 the five values.
#[derive(Component)]
pub struct Line(u8);

/// The note after a change, at the top centre (under the target plate).
#[derive(Component)]
pub struct Pill;
#[derive(Component)]
pub struct PillText;

/// The pill's tree, once (and again after a theme's rebuild sweeps the HUD's roots).
pub fn pill_spawn(mut commands: Commands, have: Query<(), With<Pill>>, fonts: Res<Fonts>) {
    if !have.is_empty() {
        return;
    }
    let f = &*fonts;
    commands
        .spawn((super::HudRoot, Node { position_type: PositionType::Absolute, top: Val::Px(92.0), left: Val::Px(0.0), right: Val::Px(0.0), justify_content: JustifyContent::Center, ..default() }, Pickable::IGNORE, GlobalZIndex(40)))
        .with_children(|r| {
            r.spawn((Pill, Node { padding: UiRect::axes(Val::Px(12.0), Val::Px(5.0)), border: wood::b(1.5), border_radius: wood::r(12.0), display: Display::None, ..default() }, BackgroundColor(wood::alpha(wood::surface(), 0.9)), BorderColor::all(wood::edge()), Pickable::IGNORE))
                .with_child((PillText, Text::new(""), f.body(13.0, 700), TextColor(wood::text()), Pickable::IGNORE));
        });
}

/// Shows the note for `facing::NOTE_S`, fading over its last half second.
pub fn pill(st: Option<Res<FovState>>, time: Res<Time>, mut pills: Query<(&mut Node, &mut BackgroundColor), With<Pill>>, mut texts: Query<(&mut Text, &mut TextColor), With<PillText>>) {
    let now = time.elapsed_secs_f64();
    let shown = st.as_ref().and_then(|s| s.note.clone()).filter(|(_, at)| now - at < crate::facing::NOTE_S);
    let a = shown.as_ref().map_or(0.0, |(_, at)| ((crate::facing::NOTE_S - (now - at)) / 0.5).clamp(0.0, 1.0) as f32);
    for (mut n, mut bg) in &mut pills {
        show(&mut n, shown.is_some());
        super::set_bg(&mut bg, wood::alpha(wood::surface(), 0.9 * a));
    }
    for (mut t, mut c) in &mut texts {
        if let Some((s, _)) = &shown {
            set_text(&mut t, s);
        }
        super::set_color(&mut c, wood::alpha(wood::text(), a));
    }
}

pub fn spawn(mut commands: Commands, places: Query<Entity, Added<FacingSight>>, fonts: Res<Fonts>) {
    let f = &*fonts;
    for e in &places {
        commands.entity(e).insert(Node { display: Display::Flex, flex_direction: FlexDirection::Column, ..default() });
        commands.entity(e).with_children(|pg| {
            super::settings::row(pg, f, "Facing sight", "The world's law: you see less to the sides and behind you (F5)", |c| {
                kit::toggle(c, TAG);
                c.spawn((Line(0), Text::new("Facing sight: off"), wood::ink(f, 13.5, 800), Pickable::IGNORE));
            });
            super::settings::row(pg, f, "Walk speed", "The world's law: how fast everyone walks", |c| {
                c.spawn((WalkChoices, Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(8.0), ..default() }, Pickable::IGNORE)).with_children(|w| {
                    let opts: Vec<(String, String)> = crate::facing::WALK_CHOICES.iter().map(|v| (format!("{v:.1} m/s"), format!("{v:.1}"))).collect();
                    let refs: Vec<(&str, &str)> = opts.iter().map(|(a, b)| (a.as_str(), b.as_str())).collect();
                    kit::seg(w, f, WALK_TAG, &refs);
                    // A value none of the choices is (another client, an admin): one more chip,
                    // selected; shown only then.
                    w.spawn((WalkOther, Node { display: Display::None, ..default() }, Pickable::IGNORE)).with_children(|o| {
                        o.spawn((Node { border: wood::b(2.0), border_radius: wood::r(9.0), overflow: Overflow::clip(), align_self: AlignSelf::FlexStart, ..default() }, BorderColor::all(wood::edge()), wood::hard_shadow(2.0, 0.4), Pickable::IGNORE))
                            .with_children(|s| {
                                s.spawn((Tag(format!("{WALK_TAG}:other")), kit::Paint::Choice, Lit(true), Node { padding: UiRect::axes(Val::Px(12.0), Val::Px(5.0)), ..default() }, kit::flat(wood::plain()), BorderColor::all(wood::edge())))
                                    .with_child((WalkOtherText, Text::new(""), wood::ink(f, 13.0, 800), Pickable::IGNORE));
                            });
                    });
                });
                c.spawn((WalkLine, Text::new(""), wood::ink(f, 13.0, 700), Pickable::IGNORE));
            });
            pg.spawn((Line(1), Text::new(""), f.body(12.5, 700), TextColor(wood::text()), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Node { margin: UiRect::new(Val::Px(232.0), Val::Px(0.0), Val::Px(4.0), Val::Px(0.0)), display: Display::None, ..default() }, Pickable::IGNORE));
        });
    }
}

/// The switch's clicks, and the lines from the field.
#[allow(clippy::too_many_arguments)]
pub fn update(
    ui: Res<UiPointer>,
    tags: Query<&Tag>,
    mut lit: Query<(&Tag, &mut Lit)>,
    st: Option<ResMut<FovState>>,
    mut lines: Query<(&Line, &mut Text, &mut Node), (Without<Tag>, Without<WalkLine>, Without<WalkChoices>)>,
    mut switches: Query<(&Tag, &mut Node), (With<kit::Paint>, Without<Line>, Without<WalkChoices>)>,
    mut walk_line: Query<(&mut Text, &mut Node), (With<WalkLine>, Without<Line>, Without<Tag>, Without<WalkChoices>, Without<WalkOther>)>,
    mut walk_choices: Query<&mut Node, (With<WalkChoices>, Without<Tag>, Without<Line>, Without<WalkOther>)>,
    (mut walk_other, mut walk_other_text): (Query<&mut Node, (With<WalkOther>, Without<Tag>, Without<Line>, Without<WalkChoices>)>, Query<&mut Text, (With<WalkOtherText>, Without<WalkLine>, Without<Line>)>),
) {
    let Some(mut st) = st else { return };
    match kit::clicked(&ui, &tags) {
        Some(TAG) => {
            let want = !st.on();
            crate::facing::ask(&mut st, want);
        }
        Some(t) if t.starts_with(WALK_TAG) => {
            // A choice's value (the extra chip is the current value: nothing to send).
            if let Some(v) = t.rsplit_once(':').map(|x| x.1.to_string()).filter(|v| v.parse::<f32>().is_ok()) {
                crate::facing::set_law(&mut st, crate::facing::WALK_LAW, &v);
            }
        }
        _ => {}
    }
    let on = st.on();
    let walk = st.walk;
    kit::light(&mut lit, |t| {
        if t == TAG {
            return Some(on);
        }
        let v = t.strip_prefix(WALK_TAG)?.strip_prefix(':')?;
        if v == "other" {
            return Some(true);
        }
        let v = v.parse::<f32>().ok()?;
        Some(walk.and_then(crate::facing::walk_choice).is_some_and(|c| (c - v).abs() < 1e-3))
    });
    let chips = st.can_switch && walk.is_some();
    for mut n in &mut walk_choices {
        show(&mut n, chips);
    }
    // The three choices, the current one selected; a value none of them is as one more chip.
    let other = walk.filter(|w| chips && crate::facing::walk_choice(*w).is_none());
    for mut n in &mut walk_other {
        show(&mut n, other.is_some());
    }
    if let Some(w) = other {
        for mut t in &mut walk_other_text {
            set_text(&mut t, &format!("{w:.1} m/s"));
        }
    }
    let shown: Vec<(String, bool)> = if chips {
        let sel = walk.and_then(crate::facing::walk_choice);
        let mut v: Vec<(String, bool)> = crate::facing::WALK_CHOICES.iter().map(|c| (format!("{c:.1} m/s"), sel.is_some_and(|s| (s - c).abs() < 1e-3))).collect();
        v.extend(other.map(|w| (format!("{w:.1} m/s"), true)));
        v
    } else {
        Vec::new()
    };
    if st.walk_chips != shown {
        st.walk_chips = shown;
    }
    // The line beside them only when there are no chips: read-only, or not in the laws.
    for (mut text, mut n) in &mut walk_line {
        let law = crate::facing::WALK_LAW;
        let s = match (walk, st.can_switch) {
            (Some(_), true) => String::new(),
            (Some(w), false) => format!("{w:.1} m/s (read-only)"),
            (None, _) => format!("not in this world's laws ({law})"),
        };
        show(&mut n, !s.is_empty());
        set_text(&mut text, &s);
    }
    for (t, mut n) in &mut switches {
        if t.0 == TAG {
            show(&mut n, st.can_switch);
        }
    }
    for (l, mut text, mut n) in &mut lines {
        match l.0 {
            0 => {
                let state = if !st.known { "Facing sight: not known yet" } else if on { "Facing sight: on" } else { "Facing sight: off" };
                let s = if st.can_switch { state.to_string() } else { format!("{state} (read-only)") };
                set_text(&mut text, &s);
            }
            _ => {
                show(&mut n, on);
                if let Some(f) = st.field {
                    set_text(&mut text, &crate::facing::values(&f));
                }
            }
        }
    }
}
