//! The cluster, bottom centre: health and energy over the skill bar, and the weapon slot
//! (docs/GAME_BRIEF.md, "Interface D"; docs/INTERFACE.md step 2). Built from the shared `bar`
//! and `slot` primitives (`prim.rs`), in the theme.
//!
//! - **The main row:** the bar's places in order: primary and secondary (LMB, RMB), the three
//!   skill places (Q E R; 1–3 are their twins), the jump (Space) and the dodge (a double tap),
//!   then the weapon (X). Which skill sits where is the bar's placement (`combat::Roles`, from the
//!   rules' bar); each key's label is its binding (`keys.rs`), so a rebinding shows at once.
//! - **A smaller row above** for skills the rules add beyond the main row (4–9), only when there
//!   are any.
//! - **Each slot:** the skill's glyph in its school's colours, its cost, what it spends that I
//!   carry (arrows), the cooldown, a ring while held (a raised guard), greyed with the reason
//!   (in the tooltip on hover, with the rules' description), and a red flash with a note in the
//!   rules' own words when the authority refuses a press ("no one there to strike").
//! - **Sheathed** (`weapon.rs`), the attack skills are greyed: "Sheathed: X draws".

use super::icons::{Glyph, Icons, Mark};
use super::model::*;
use super::prim::{self, SlotKey, SlotView, Slots};
use super::theme::{self, Fonts};
use super::{set_bg, set_text, set_width, show, wood, HudRoot};
use crate::keys::{Act, Binds};
use bevy::color::Mix;
use bevy::prelude::*;
use bevy::ui::{BackgroundGradient, ColorStop, GlobalZIndex, LinearGradient};

const SLOT: f32 = 54.0;
const SMALL: f32 = 44.0;
const STATUS: usize = 4;

/// The main row: (act, gap before).
const MAIN: [(Act, f32); 7] = [(Act::Primary, 0.0), (Act::Secondary, 0.0), (Act::Skill1, 12.0), (Act::Skill2, 0.0), (Act::Skill3, 0.0), (Act::Jump, 12.0), (Act::Dodge, 0.0)];

fn key_of(a: Act) -> String {
    format!("bar:{}", a.name())
}
const WEAPON: &str = "bar:Weapon";

#[derive(Component)]
pub struct Cluster;
#[derive(Component)]
pub struct ExtraRow;
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

/// A meter: a value over its maximum, with its number on it.
fn meter(p: &mut ChildSpawnerCommands, f: &Fonts, fill: impl Bundle, text: impl Bundle, ghost: bool) {
    let th = wood::t();
    let track = if th.serif_titles { wood::TRACK } else { wood::alpha(th.text, 0.16) };
    p.spawn((Node { height: Val::Px(if th.serif_titles { 16.0 } else { 12.0 }), border: if th.serif_titles { wood::b(2.0) } else { UiRect::ZERO }, border_radius: BorderRadius::all(Val::Px(9.0)), overflow: Overflow::clip(), flex_grow: 1.0, ..default() }, BackgroundColor(track), BorderColor::all(th.edge), Pickable::IGNORE)).with_children(|b| {
        if ghost {
            b.spawn((HpGhost, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), ..default() }, BackgroundColor(Color::srgba(1.0, 0.86, 0.72, 0.55)), Pickable::IGNORE));
        }
        b.spawn(fill);
        if ghost {
            b.spawn((HpFlash, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), ..default() }, BackgroundColor(Color::NONE), Pickable::IGNORE));
        }
        b.spawn((Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(-1.0), bottom: Val::Px(0.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, ..default() }, Pickable::IGNORE))
            .with_child((text, Text::new(""), f.body(if th.serif_titles { 11.0 } else { 9.5 }, 800), TextColor(Color::srgb_u8(0xff, 0xf8, 0xea)), bevy::ui::widget::TextShadow { offset: Vec2::new(0.0, 1.0), color: Color::srgba(0.0, 0.0, 0.0, 0.7) }, Pickable::IGNORE));
    });
}

pub fn spawn(mut commands: Commands, fonts: Res<Fonts>, icons: Res<Icons>) {
    let f = &*fonts;
    let th = wood::t();
    let main: Vec<(String, f32, f32, f32)> = MAIN.iter().map(|(a, gap)| (key_of(*a), SLOT, SLOT, *gap)).chain(std::iter::once((WEAPON.to_string(), SLOT, 70.0, 12.0))).collect();
    let extra: Vec<(String, f32, f32, f32)> = (0..crate::keys::EXTRA).map(|i| (key_of(Act::Extra(i)), SMALL, SMALL, 0.0)).collect();
    commands
        .spawn((HudRoot, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), bottom: Val::Px(14.0), justify_content: JustifyContent::Center, ..default() }, Pickable::IGNORE))
        .with_children(|root| {
            root.spawn((Cluster, super::hit::Block, Node { flex_direction: FlexDirection::Column, align_items: AlignItems::Center, row_gap: Val::Px(if th.serif_titles { 8.0 } else { 10.0 }), padding: UiRect::new(Val::Px(14.0), Val::Px(14.0), Val::Px(10.0), Val::Px(18.0)), border: wood::b(3.0), border_radius: wood::r(12.0), ..default() }, wood::wood(), GlobalZIndex(20)))
                .with_children(|c| {
                    c.spawn(wood::rim(9.0));
                    // Status (hunger, tiredness, a fight), over the meters' left end.
                    c.spawn((Node { position_type: PositionType::Absolute, left: Val::Px(12.0), top: Val::Px(-30.0), flex_direction: FlexDirection::Row, column_gap: Val::Px(5.0), ..default() }, Pickable::IGNORE)).with_children(|row| {
                        for i in 0..STATUS {
                            row.spawn((StatusPill(i), Node { width: Val::Px(26.0), height: Val::Px(26.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: wood::b(2.0), border_radius: BorderRadius::all(Val::Percent(50.0)), display: Display::None, ..default() }, BackgroundColor(th.surface), BorderColor::all(th.edge), Pickable::IGNORE))
                                .with_child((StatusIcon(i), Node { width: Val::Px(16.0), height: Val::Px(16.0), ..default() }, ImageNode::new(Handle::default()), Pickable::IGNORE));
                        }
                    });
                    c.spawn((Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(10.0), align_self: AlignSelf::Stretch, ..default() }, Pickable::IGNORE)).with_children(|v| {
                        meter(v, f, (HpFill, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), border_radius: BorderRadius::all(Val::Px(7.0)), ..default() }, down(&[(wood::ROSE2, 0.0), (wood::ROSE, 60.0), (wood::ROSE_LO, 100.0)]), Pickable::IGNORE), HpText, true);
                        meter(v, f, (EnFill, Node { position_type: PositionType::Absolute, left: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), width: Val::Percent(100.0), border_radius: BorderRadius::all(Val::Px(7.0)), ..default() }, down(&[(wood::TEAL2, 0.0), (wood::TEAL, 100.0)]), Pickable::IGNORE), EnText, false);
                    });
                    prim::bar(c, f, &icons, &extra, Some(Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(5.0), padding: UiRect::bottom(Val::Px(10.0)), display: Display::None, ..default() }), ExtraRow);
                    prim::bar(c, f, &icons, &main, None, ());
                });
        });
}

/// The rules' description of a skill, for the tooltip.
fn about(rules: &crate::verbs::Rules, skill: &str) -> String {
    rules.skills.iter().find(|s| s.name == skill).map(|s| s.help.clone()).unwrap_or_default()
}

/// What each slot shows, from the rules' bar skills, the places, the keys, the weapon and what
/// the authority refused.
#[allow(clippy::too_many_arguments)]
pub fn fill(
    model: Res<HudModel>,
    roles: Option<Res<crate::combat::Roles>>,
    binds: Res<Binds>,
    weapon: Res<crate::weapon::Weapon>,
    combat: Option<Res<crate::combat::Combat>>,
    rules: Option<NonSend<crate::verbs::Rules>>,
    scene: NonSend<crate::world::Scene>,
    mut verbs: Option<ResMut<crate::verbs::Verbs>>,
    time: Res<Time>,
    mut slots: ResMut<Slots>,
    mut noted: Local<f64>,
) {
    // Look-dev's sample HUD has no rules or combat: nothing to place.
    let (Some(roles), Some(combat), Some(rules), Some(verbs)) = (roles, combat, rules, verbs.as_mut()) else { return };
    let now_ms = scene.now_ms;
    // The authority's refusal of a press: on its slot, and a note in the rules' words.
    let refused = combat.refusal.as_ref().filter(|(_, at)| now_ms - at < 4_000.0);
    if let Some((why, at)) = combat.refusal.as_ref() {
        if *at > *noted {
            *noted = *at;
            if now_ms - at < 2_000.0 {
                verbs.toasts.push(crate::verbs::Toast { text: super::label(&wood::readable(why)), ok: Some(false), at: time.elapsed_secs_f64() });
            }
        }
    }
    let mut out = std::collections::HashMap::new();
    let mut put = |a: Act| {
        let skill = roles.skill(a).and_then(|s| model.skills.iter().find(|k| k.name == s));
        let v = match skill {
            Some(s) => {
                let sheathed = !weapon.drawn && roles.is_hostile(&s.name);
                let off = if sheathed {
                    Some(format!("Sheathed: {} draws your weapon", binds.first(Act::Weapon)))
                } else {
                    match &s.state {
                        SkillState::Unavailable(why) => Some(why.clone()),
                        SkillState::Empty => Some(String::new()),
                        _ => None,
                    }
                };
                SlotView {
                    glyph: Some(Glyph::Skill(s.icon)),
                    family: Some(theme::school(s.icon)),
                    key: binds.first(a),
                    cost: Some(s.cost),
                    count: s.count,
                    cooldown: match s.state {
                        SkillState::Cooldown { left, total } => Some((left, total)),
                        _ => None,
                    },
                    held: s.state == SkillState::Active,
                    off,
                    caption: None,
                    fill: None,
                    refused: refused.filter(|_| combat.refused_skill.as_deref() == Some(s.name.as_str())).map(|(_, at)| ((now_ms - at) / 1000.0) as f32),
                    label: roles.labels.get(&s.name).cloned().unwrap_or_else(|| super::label(&s.name)),
                    about: about(&rules, &s.name),
                }
            }
            None => SlotView { key: binds.first(a), ..default() },
        };
        out.insert(SlotKey(key_of(a)), v);
    };
    for (a, _) in MAIN {
        put(a);
    }
    for i in 0..crate::keys::EXTRA {
        put(Act::Extra(i));
    }
    let th = wood::t();
    out.insert(
        SlotKey(WEAPON.into()),
        SlotView {
            glyph: Some(Glyph::Ui(if weapon.drawn { Mark::Drawn } else { Mark::Sheathed })),
            key: binds.first(Act::Weapon),
            caption: Some(if weapon.drawn { "drawn" } else { "sheathed" }.into()),
            fill: weapon.drawn.then_some(if th.serif_titles { wood::HOSTILE.mix(&Color::WHITE, 0.15) } else { wood::alpha(wood::HOSTILE, 0.85) }),
            label: if weapon.drawn { "Weapon drawn".into() } else { "Weapon sheathed".into() },
            about: if weapon.drawn { "A tap strikes whoever is under the cursor.".into() } else { "A tap on a person talks; an attack skill's first press draws the weapon.".into() },
            ..default()
        },
    );
    slots.0 = out;
}

#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn update(
    model: Res<HudModel>,
    roles: Option<Res<crate::combat::Roles>>,
    icons: Res<Icons>,
    time: Res<Time>,
    mut ghost: Local<f32>,
    mut texts: ParamSet<(Query<&mut Text, With<HpText>>, Query<&mut Text, With<EnText>>)>,
    mut nodes: ParamSet<(Query<(&SlotKey, &mut Node), With<prim::SlotRoot>>, Query<&mut Node, With<ExtraRow>>, Query<&mut Node, With<HpFill>>, Query<&mut Node, With<HpGhost>>, Query<&mut Node, With<EnFill>>, Query<(&StatusPill, &mut Node)>)>,
    mut flash: Query<&mut BackgroundColor, (With<HpFlash>, Without<StatusPill>)>,
    mut status_icons: Query<(&StatusIcon, &mut ImageNode)>,
) {
    let none = crate::combat::Roles::default();
    let roles = roles.as_deref().unwrap_or(&none);
    // A place with no skill shows only on the main row; the extra row only with extras.
    for (k, mut n) in &mut nodes.p0() {
        if let Some(i) = k.0.strip_prefix("bar:Extra").and_then(|n| n.parse::<usize>().ok()) {
            show(&mut n, i >= 4 && roles.extra().len() > i - 4);
        }
    }
    let extras = !roles.extra().is_empty();
    for mut n in &mut nodes.p1() {
        show(&mut n, extras);
    }
    let Some(me) = &model.me else { return };
    let f = (me.hp / me.max_hp.max(1.0)).clamp(0.0, 1.0);
    let dt = time.delta_secs();
    *ghost = if *ghost < f || *ghost == 0.0 { f } else { *ghost + (f - *ghost) * (1.0 - (-dt * 2.2).exp()) };
    for mut n in &mut nodes.p2() {
        set_width(&mut n, Val::Percent(f * 100.0));
    }
    for mut n in &mut nodes.p3() {
        set_width(&mut n, Val::Percent(*ghost * 100.0));
    }
    for mut n in &mut nodes.p4() {
        set_width(&mut n, Val::Percent((me.energy / me.max_energy.max(1.0)).clamp(0.0, 1.0) * 100.0));
    }
    for mut b in &mut flash {
        set_bg(&mut b, Color::srgba(1.0, 0.95, 0.9, me.hurt * 0.35));
    }
    for mut t in &mut texts.p0() {
        set_text(&mut t, &super::hp_text(me.hp, me.max_hp));
    }
    for mut t in &mut texts.p1() {
        set_text(&mut t, &format!("{:.0} / {:.0}", me.energy.max(0.0).round(), me.max_energy.round()));
    }
    for (p, mut n) in &mut nodes.p5() {
        show(&mut n, p.0 < me.statuses.len());
    }
    for (i, mut img) in &mut status_icons {
        if let Some(s) = me.statuses.get(i.0) {
            let h = icons.get(Glyph::Status(s.kind));
            if img.image != h {
                img.image = h;
            }
            let c = theme::tone(s.tone).mix(&wood::t().text, 0.25);
            if img.color != c {
                img.color = c;
            }
        }
    }
}
