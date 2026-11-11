//! Interface D's cluster, bottom centre: health and energy over the skill slots, and the
//! weapon slot on X ("sheathed" or "drawn").
//!
//! - **The main row:** LMB and RMB, the three skill keys (Q E R; 1–3 are their twins), the jump
//!   (Space) and the dodge (a double tap of a direction key), then the weapon. Which skill sits
//!   where is `combat::Roles` (by how the rules aim each bar skill); each key's label is its
//!   binding (`keys.rs`), so a rebinding shows at once.
//! - **A smaller row above** holds skills the rules add beyond the main row, on 4–9. It shows
//!   only when there are any, so no key you already know moves.
//! - **Each slot:** its glyph in its school's colours, the energy it costs (teal, top right),
//!   how many of what it spends I carry (arrows, bottom right), the cooldown as a sweep with the
//!   seconds left, a gold ring while held (a raised guard), and greyed when it can't be used now:
//!   missing what it needs, too tired, or an attack skill while the weapon is sheathed.
//! - **Health** reads both figures rounded alike (`ui::hp_text`); a hit flashes the bar.

use super::icons::{Glyph, Icons, Mark};
use super::model::*;
use super::theme::{self, Fonts};
use super::{set_bg, set_text, set_width, show, wood, HudRoot};
use crate::keys::{Act, Binds};
use bevy::color::Mix;
use bevy::prelude::*;
use bevy::ui::{AngularColorStop, BackgroundGradient, ColorStop, ConicGradient, GlobalZIndex, Gradient, LinearGradient, Outline, UiPosition};
use std::f32::consts::TAU;

const SLOT: f32 = 56.0;
const SMALL: f32 = 46.0;
const STATUS: usize = 4;

/// A place on the bar.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Place {
    Bar(Act),
    Weapon,
}

const MAIN: [(Act, f32); 7] = [(Act::Primary, 0.0), (Act::Secondary, 0.0), (Act::Skill1, 12.0), (Act::Skill2, 0.0), (Act::Skill3, 0.0), (Act::Jump, 12.0), (Act::Dodge, 0.0)];

#[derive(Component)]
pub struct Cluster;
#[derive(Component)]
pub struct ExtraRow;
#[derive(Component)]
pub struct Sq(Place);
#[derive(Component)]
pub struct SqIcon(Place);
#[derive(Component)]
pub struct SqSweep(Place);
#[derive(Component)]
pub struct SqTime(Place);
#[derive(Component)]
pub struct SqCost(Place);
#[derive(Component)]
pub struct SqCostText(Place);
#[derive(Component)]
pub struct SqCount(Place);
#[derive(Component)]
pub struct SqKey(Place);
#[derive(Component)]
pub struct SqSlot(Place);
#[derive(Component)]
pub struct WeaponText;
#[derive(Component)]
pub struct HpFill;
#[derive(Component)]
pub struct HpGhost;
#[derive(Component)]
pub struct HpFlash;
#[derive(Component)]
pub struct HpText;
#[derive(Component)]
pub struct EnFill;
#[derive(Component)]
pub struct EnText;
#[derive(Component)]
pub struct StatusPill(usize);
#[derive(Component)]
pub struct StatusIcon(usize);

fn down(stops: &[(Color, f32)]) -> BackgroundGradient {
    BackgroundGradient::from(LinearGradient::to_bottom(stops.iter().map(|(c, p)| ColorStop::percent(*c, *p)).collect()))
}

fn bar(p: &mut ChildSpawnerCommands, f: &Fonts, fill: impl Bundle, text: impl Bundle, ghost: bool) {
    p.spawn((Node { height: Val::Px(16.0), border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(9.0)), overflow: Overflow::clip(), flex_grow: 1.0, ..default() }, BackgroundColor(wood::TRACK), BorderColor::all(wood::INK), Pickable::IGNORE)).with_children(|b| {
        if ghost {
            b.spawn((HpGhost, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), ..default() }, BackgroundColor(Color::srgba(1.0, 0.86, 0.72, 0.55)), Pickable::IGNORE));
        }
        b.spawn(fill);
        if ghost {
            b.spawn((HpFlash, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), ..default() }, BackgroundColor(Color::NONE), Pickable::IGNORE));
        }
        b.spawn((Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(-1.0), bottom: Val::Px(0.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, ..default() }, Pickable::IGNORE))
            .with_child((text, Text::new(""), f.body(11.0, 900), TextColor(Color::srgb_u8(0xff, 0xf8, 0xea)), bevy::ui::widget::TextShadow { offset: Vec2::new(0.0, 1.0), color: Color::BLACK }, Pickable::IGNORE));
    });
}

fn slot(p: &mut ChildSpawnerCommands, f: &Fonts, icons: &Icons, place: Place, size: f32, gap: f32) {
    let w = if place == Place::Weapon { 74.0 } else { size };
    p.spawn((SqSlot(place), Node { width: Val::Px(w), margin: UiRect::left(Val::Px(gap)), flex_direction: FlexDirection::Column, align_items: AlignItems::Center, ..default() }, super::hit::Block, super::hit::Tag(format!("bar:{}", match place { Place::Weapon => "weapon".into(), Place::Bar(a) => a.name() })))).with_children(|s| {
        s.spawn((Sq(place), Node { width: Val::Px(w), height: Val::Px(size), border: UiRect::all(Val::Px(3.0)), border_radius: BorderRadius::all(Val::Px(10.0)), justify_content: JustifyContent::Center, align_items: AlignItems::Center, overflow: Overflow::clip(), ..default() }, BackgroundGradient::default(), BorderColor::all(wood::INK), Outline { width: Val::Px(0.0), offset: Val::Px(2.0), color: Color::srgb_u8(0xff, 0xcf, 0x5c) }, Pickable::IGNORE)).with_children(|q| {
            let isz = if place == Place::Weapon { 28.0 } else { size * 0.6 };
            q.spawn((SqIcon(place), Node { width: Val::Px(isz), height: Val::Px(isz), margin: if place == Place::Weapon { UiRect::bottom(Val::Px(10.0)) } else { UiRect::ZERO }, ..default() }, ImageNode::new(icons.get(Glyph::Ui(Mark::Sheathed))), Pickable::IGNORE));
            if place == Place::Weapon {
                q.spawn((WeaponText, Text::new("sheathed"), f.body(11.0, 900), TextColor(wood::INK), Node { position_type: PositionType::Absolute, bottom: Val::Px(3.0), ..default() }, Pickable::IGNORE));
            } else {
                q.spawn((SqSweep(place), Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, ..default() }, BackgroundGradient::default(), Pickable::IGNORE))
                    .with_child((SqTime(place), Text::new(""), f.body(18.0, 900), TextColor(Color::WHITE), theme::text_shadow(), Pickable::IGNORE));
                q.spawn((SqCost(place), Node { position_type: PositionType::Absolute, right: Val::Px(2.0), top: Val::Px(2.0), min_width: Val::Px(16.0), height: Val::Px(16.0), padding: UiRect::axes(Val::Px(3.0), Val::Px(0.0)), border: UiRect::all(Val::Px(1.5)), border_radius: BorderRadius::all(Val::Px(8.0)), justify_content: JustifyContent::Center, align_items: AlignItems::Center, display: Display::None, ..default() }, BackgroundColor(wood::TEAL), BorderColor::all(wood::INK), Pickable::IGNORE))
                    .with_child((SqCostText(place), Text::new(""), f.body(9.5, 900), TextColor(Color::WHITE), Pickable::IGNORE));
                q.spawn((SqCount(place), Text::new(""), f.body(13.0, 900), TextColor(Color::WHITE), theme::text_shadow(), Node { position_type: PositionType::Absolute, right: Val::Px(4.0), bottom: Val::Px(1.0), ..default() }, Pickable::IGNORE));
            }
        });
        // The key, as bound.
        s.spawn((Node { margin: UiRect::top(Val::Px(-9.0)), ..default() }, GlobalZIndex(21), Pickable::IGNORE)).with_children(|k| {
            wood::chip(k, f, "", SqKey(place));
        });
    });
}

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>, icons: Res<Icons>) {
    let f = &*fonts;
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), bottom: Val::Px(14.0), justify_content: JustifyContent::Center, ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            root.spawn((Cluster, super::hit::Block, Node { flex_direction: FlexDirection::Column, align_items: AlignItems::Center, row_gap: Val::Px(8.0), padding: UiRect::new(Val::Px(14.0), Val::Px(14.0), Val::Px(9.0), Val::Px(20.0)), border: UiRect::all(Val::Px(3.0)), border_radius: BorderRadius::all(Val::Px(12.0)), ..default() }, wood::wood(), GlobalZIndex(20)))
                .with_children(|c| {
                    c.spawn(wood::rim(9.0));
                    // Status (hunger, tiredness, a fight), over the bars' left end.
                    c.spawn((Node { position_type: PositionType::Absolute, left: Val::Px(12.0), top: Val::Px(-30.0), flex_direction: FlexDirection::Row, column_gap: Val::Px(5.0), ..default() }, Pickable::IGNORE)).with_children(|row| {
                        for i in 0..STATUS {
                            row.spawn((StatusPill(i), Node { width: Val::Px(26.0), height: Val::Px(26.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Percent(50.0)), display: Display::None, ..default() }, BackgroundColor(wood::PARCH), BorderColor::all(wood::INK), Pickable::IGNORE))
                                .with_child((StatusIcon(i), Node { width: Val::Px(16.0), height: Val::Px(16.0), ..default() }, ImageNode::new(Handle::default()), Pickable::IGNORE));
                        }
                    });
                    c.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(10.0), align_self: AlignSelf::Stretch, ..default() }, Pickable::IGNORE)).with_children(|v| {
                        bar(v, f, (HpFill, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), border_radius: BorderRadius::all(Val::Px(7.0)), ..default() }, down(&[(wood::ROSE2, 0.0), (wood::ROSE, 60.0), (wood::ROSE_LO, 100.0)]), Pickable::IGNORE), HpText, true);
                        bar(v, f, (EnFill, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), border_radius: BorderRadius::all(Val::Px(7.0)), ..default() }, down(&[(wood::TEAL2, 0.0), (wood::TEAL, 100.0)]), Pickable::IGNORE), EnText, false);
                    });
                    c.spawn((ExtraRow, Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(5.0), padding: UiRect::bottom(Val::Px(12.0)), border: UiRect::bottom(Val::Px(2.0)), display: Display::None, ..default() }, BorderColor::all(wood::alpha(wood::BRASS2, 0.35)), Pickable::IGNORE)).with_children(|r| {
                        for i in 0..crate::keys::EXTRA {
                            slot(r, f, &icons, Place::Bar(Act::Extra(i)), SMALL, 0.0);
                        }
                    });
                    c.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(6.0), align_items: AlignItems::FlexEnd, ..default() }, Pickable::IGNORE)).with_children(|r| {
                        for (a, gap) in MAIN {
                            slot(r, f, &icons, Place::Bar(a), SLOT, gap);
                        }
                        slot(r, f, &icons, Place::Weapon, SLOT, 12.0);
                    });
                });
        });
}

/// What a place holds now: its skill, as the model has it.
fn skill_at<'a>(model: &'a HudModel, roles: &crate::combat::Roles, p: Place) -> Option<&'a Skill> {
    match p {
        Place::Bar(a) => roles.skill(a).and_then(|s| model.skills.iter().find(|k| k.name == s)),
        Place::Weapon => None,
    }
}

#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn update(
    model: Res<HudModel>,
    roles: Res<crate::combat::Roles>,
    binds: Res<Binds>,
    weapon: Res<crate::weapon::Weapon>,
    icons: Res<Icons>,
    time: Res<Time>,
    mut ghost: Local<f32>,
    mut sqs: Query<(&Sq, &mut BackgroundGradient, &mut Outline), (Without<SqSweep>, Without<HpFill>, Without<EnFill>)>,
    mut imgs: Query<(&SqIcon, &mut ImageNode, &mut Node), (Without<SqSlot>, Without<StatusIcon>)>,
    mut sweeps: Query<(&SqSweep, &mut BackgroundGradient), Without<Sq>>,
    mut texts: ParamSet<(Query<(&SqTime, &mut Text)>, Query<(&SqCostText, &mut Text)>, Query<(&SqCount, &mut Text)>, Query<(&SqKey, &mut Text)>, Query<(&mut Text, &mut TextColor), With<WeaponText>>, Query<&mut Text, With<HpText>>, Query<&mut Text, With<EnText>>)>,
    mut nodes: ParamSet<(Query<(&SqCost, &mut Node)>, Query<(&SqSlot, &mut Node)>, Query<&mut Node, With<ExtraRow>>, Query<&mut Node, With<HpFill>>, Query<&mut Node, With<HpGhost>>, Query<&mut Node, With<EnFill>>, Query<(&StatusPill, &mut Node)>)>,
    mut flash: Query<&mut BackgroundColor, (With<HpFlash>, Without<StatusPill>)>,
    mut status_icons: Query<(&StatusIcon, &mut ImageNode), (Without<SqIcon>, Without<SqSlot>)>,
) {
    let _ = &time;
    let off = |s: &Skill| !weapon.drawn && roles.is_hostile(&s.name) || matches!(s.state, SkillState::Unavailable(_) | SkillState::Empty);
    for (sq, mut g, mut o) in &mut sqs {
        let want = match sq.0 {
            Place::Weapon if weapon.drawn => down(&[(Color::srgb_u8(0xf0, 0x6a, 0x55), 0.0), (wood::DRAWN, 100.0)]),
            Place::Weapon => down(&[(Color::srgb_u8(0xfb, 0xf0, 0xd6), 0.0), (Color::srgb_u8(0xe8, 0xcf, 0x9e), 100.0)]),
            p => match skill_at(&model, &roles, p) {
                Some(s) => {
                    let (light, dark) = theme::school(s.icon);
                    let k = if off(s) { 0.45 } else { 1.0 };
                    down(&[(wood::alpha(light.mix(&Color::WHITE, 0.15), k), 0.0), (wood::alpha(dark.mix(&light, 0.35), k), 100.0)])
                }
                None => down(&[(wood::alpha(wood::WAL2, 0.9), 0.0), (wood::alpha(wood::WAL2, 0.9), 100.0)]),
            },
        };
        if *g != want {
            *g = want;
        }
        let ring = skill_at(&model, &roles, sq.0).is_some_and(|s| s.state == SkillState::Active);
        let w = if ring { Val::Px(3.0) } else { Val::Px(0.0) };
        if o.width != w {
            o.width = w;
        }
    }
    for (i, mut img, mut n) in &mut imgs {
        let (g, col) = match i.0 {
            Place::Weapon => (Glyph::Ui(if weapon.drawn { Mark::Drawn } else { Mark::Sheathed }), if weapon.drawn { Color::WHITE } else { wood::INK }),
            p => match skill_at(&model, &roles, p) {
                Some(s) => {
                    let (light, _) = theme::school(s.icon);
                    (Glyph::Skill(s.icon), if off(s) { Color::srgba(0.75, 0.72, 0.68, 0.6) } else { light.mix(&Color::WHITE, 0.55) })
                }
                None => (Glyph::Skill(SkillIcon::Empty), Color::srgba(1.0, 1.0, 1.0, 0.25)),
            },
        };
        let h = icons.get(g);
        if img.image != h {
            img.image = h;
        }
        if img.color != col {
            img.color = col;
        }
        let _ = &mut n;
    }
    for (s, mut g) in &mut sweeps {
        let want = match skill_at(&model, &roles, s.0).map(|k| &k.state) {
            Some(SkillState::Cooldown { left, total }) => {
                let done = (1.0 - left / total.max(0.01)).clamp(0.0, 1.0) * TAU;
                let shade = Color::srgba(0.1, 0.06, 0.03, 0.7);
                BackgroundGradient::from(Gradient::Conic(ConicGradient { start: 0.0, position: UiPosition::CENTER, stops: vec![AngularColorStop::new(Color::NONE, 0.0), AngularColorStop::new(Color::NONE, done), AngularColorStop::new(shade, done), AngularColorStop::new(shade, TAU)], color_space: default() }))
            }
            _ => BackgroundGradient::default(),
        };
        if *g != want {
            *g = want;
        }
    }
    for (t, mut text) in &mut texts.p0() {
        let s = match skill_at(&model, &roles, t.0).map(|k| &k.state) {
            Some(SkillState::Cooldown { left, .. }) if *left >= 1.0 => format!("{:.0}", left.ceil()),
            Some(SkillState::Cooldown { left, .. }) => format!("{left:.1}"),
            _ => String::new(),
        };
        set_text(&mut text, &s);
    }
    for (t, mut text) in &mut texts.p1() {
        if let Some(s) = skill_at(&model, &roles, t.0) {
            set_text(&mut text, &if s.cost.fract().abs() < 0.05 { format!("{:.0}", s.cost) } else { format!("{:.1}", s.cost) });
        }
    }
    for (t, mut text) in &mut texts.p2() {
        let s = skill_at(&model, &roles, t.0).and_then(|k| k.count).map_or(String::new(), |n| n.to_string());
        set_text(&mut text, &s);
    }
    for (k, mut text) in &mut texts.p3() {
        let s = match k.0 {
            Place::Weapon => binds.first(Act::Weapon),
            Place::Bar(a) => binds.first(a),
        };
        set_text(&mut text, &s);
    }
    for (mut t, mut c) in &mut texts.p4() {
        set_text(&mut t, if weapon.drawn { "drawn" } else { "sheathed" });
        super::set_color(&mut c, if weapon.drawn { Color::WHITE } else { wood::INK });
    }
    for (c, mut n) in &mut nodes.p0() {
        show(&mut n, skill_at(&model, &roles, c.0).is_some_and(|s| s.cost > 0.0));
    }
    // A place with no skill shows only on the main row.
    for (s, mut n) in &mut nodes.p1() {
        let on = match s.0 {
            Place::Bar(Act::Extra(_)) => skill_at(&model, &roles, s.0).is_some(),
            _ => true,
        };
        show(&mut n, on);
    }
    let extras = !roles.extra.is_empty();
    for mut n in &mut nodes.p2() {
        show(&mut n, extras);
    }
    // Health and energy.
    let Some(me) = &model.me else { return };
    let f = (me.hp / me.max_hp.max(1.0)).clamp(0.0, 1.0);
    let dt = time.delta_secs();
    *ghost = if *ghost < f || *ghost == 0.0 { f } else { *ghost + (f - *ghost) * (1.0 - (-dt * 2.2).exp()) };
    for mut n in &mut nodes.p3() {
        set_width(&mut n, Val::Percent(f * 100.0));
    }
    for mut n in &mut nodes.p4() {
        set_width(&mut n, Val::Percent(*ghost * 100.0));
    }
    for mut n in &mut nodes.p5() {
        set_width(&mut n, Val::Percent((me.energy / me.max_energy.max(1.0)).clamp(0.0, 1.0) * 100.0));
    }
    for mut b in &mut flash {
        set_bg(&mut b, Color::srgba(1.0, 0.95, 0.9, me.hurt * 0.35));
    }
    for mut t in &mut texts.p5() {
        set_text(&mut t, &super::hp_text(me.hp, me.max_hp));
    }
    for mut t in &mut texts.p6() {
        set_text(&mut t, &format!("{:.0} / {:.0}", me.energy.max(0.0).round(), me.max_energy.round()));
    }
    for (p, mut n) in &mut nodes.p6() {
        show(&mut n, p.0 < me.statuses.len());
    }
    for (i, mut img) in &mut status_icons {
        if let Some(s) = me.statuses.get(i.0) {
            let h = icons.get(Glyph::Status(s.kind));
            if img.image != h {
                img.image = h;
            }
            let c = theme::tone(s.tone).mix(&wood::INK, 0.25);
            if img.color != c {
                img.color = c;
            }
        }
    }
}
