//! Shared primitives a declaration can fill (docs/INTERFACE.md §2): the `bar` (a row of slots)
//! and the `slot` (a glyph, its key, its cost, a count, a cooldown sweep, a held ring, greyed
//! with a reason, and a flash when the rules refuse it). Painted from the theme (`wood.rs`).
//!
//! An owner spawns slots with a key of its choosing ([`SlotKey`]), then fills [`Slots`] each
//! frame with one [`SlotView`] per key; [`paint`] draws them all. Hovering a slot shows its
//! words (its label, and why it is greyed, or the rules' description) over the bar ([`tooltip`]).

use super::hit::{Block, Tag, UiPointer};
use super::icons::{Glyph, Icons};
use super::theme::{self, Fonts};
use super::{set_text, show, wood, HudRoot};
use bevy::color::Mix;
use bevy::prelude::*;
use bevy::ui::{AngularColorStop, BackgroundGradient, ConicGradient, GlobalZIndex, Gradient, Outline, UiPosition};
use std::collections::HashMap;
use std::f32::consts::TAU;

/// Which slot: the owner's name for it ("bar:Primary", "bar:Weapon").
#[derive(Component, Clone, PartialEq, Eq, Hash, Debug)]
pub struct SlotKey(pub String);

/// What a slot shows now.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct SlotView {
    pub glyph: Option<Glyph>,
    /// The glyph's colour family (light, dark): a school's colours, or none for the theme's.
    pub family: Option<(Color, Color)>,
    pub key: String,
    pub cost: Option<f32>,
    pub count: Option<u32>,
    pub cooldown: Option<(f32, f32)>,
    pub held: bool,
    /// Greyed, and why (the rules' words where they give them).
    pub off: Option<String>,
    /// A caption under the glyph (the weapon slot's "sheathed").
    pub caption: Option<String>,
    /// Filled with a colour (the drawn weapon).
    pub fill: Option<Color>,
    /// Refused by the authority just now (s ago): a red flash that fades.
    pub refused: Option<f32>,
    /// Hovered: its name, and words under it.
    pub label: String,
    pub about: String,
}

#[derive(Resource, Default)]
pub struct Slots(pub HashMap<SlotKey, SlotView>);

#[derive(Component)]
pub struct SlotRoot;
#[derive(Component)]
pub struct SlotFace;
#[derive(Component)]
pub struct SlotGlyph;
#[derive(Component)]
pub struct SlotSweep;
#[derive(Component)]
pub struct SlotTime;
#[derive(Component)]
pub struct SlotCost;
#[derive(Component)]
pub struct SlotCostText;
#[derive(Component)]
pub struct SlotCount;
#[derive(Component)]
pub struct SlotChip;
#[derive(Component)]
pub struct SlotCaption;
#[derive(Component)]
pub struct Tooltip;
#[derive(Component)]
pub struct TooltipTitle;
#[derive(Component)]
pub struct TooltipText;

/// A bar: a row of slots, `(key, size, width, gap before)`, in `node` (none: a plain row).
/// A row of slots: (key, size, width, gap before it, whether it shows a caption).
pub fn bar(p: &mut ChildSpawnerCommands, f: &Fonts, icons: &Icons, slots: &[(String, f32, f32, f32, bool)], node: Option<Node>, extra: impl Bundle) {
    let node = node.unwrap_or(Node { flex_direction: FlexDirection::Row, column_gap: Val::Px(6.0), align_items: AlignItems::FlexEnd, ..default() });
    p.spawn((node, Pickable::IGNORE, extra)).with_children(|r| {
        for (key, size, width, gap, caption) in slots {
            slot(r, f, icons, key, *size, *width, *gap, *caption);
        }
    });
}

/// One slot. Only the parts it can show are spawned (a caption where asked, cost chips in a
/// theme that shows costs): every node is laid out each frame, shown or not.
#[allow(clippy::too_many_arguments)]
pub fn slot(p: &mut ChildSpawnerCommands, f: &Fonts, icons: &Icons, key: &str, size: f32, width: f32, gap: f32, caption: bool) {
    let k = SlotKey(key.to_string());
    let th = wood::t();
    p.spawn((SlotRoot, k.clone(), Block, Tag(key.to_string()), Node { width: Val::Px(width), margin: UiRect::left(Val::Px(gap)), flex_direction: FlexDirection::Column, align_items: AlignItems::Center, ..default() })).with_children(|s| {
        s.spawn((SlotFace, k.clone(), Node { width: Val::Px(width), height: Val::Px(size), border: wood::b(3.0), border_radius: wood::r(10.0), flex_direction: FlexDirection::Column, row_gap: Val::Px(1.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, overflow: Overflow::clip(), ..default() }, BackgroundGradient::default(), BorderColor::all(th.edge), Outline { width: Val::Px(0.0), offset: Val::Px(2.0), color: Color::srgb_u8(0xff, 0xcf, 0x5c) }, Pickable::IGNORE)).with_children(|q| {
            q.spawn((SlotGlyph, k.clone(), Node { width: Val::Px(size * 0.56), height: Val::Px(size * 0.56), ..default() }, ImageNode::new(icons.get(Glyph::Ui(super::icons::Mark::Dots))), Pickable::IGNORE));
            if caption {
                q.spawn((SlotCaption, k.clone(), Text::new(""), f.body(10.5, 800), TextColor(th.text), Node { display: Display::None, ..default() }, Pickable::IGNORE));
            }
            q.spawn((SlotSweep, k.clone(), Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, ..default() }, BackgroundGradient::default(), Pickable::IGNORE))
                .with_child((SlotTime, k.clone(), Text::new(""), f.body(17.0, 800), TextColor(Color::WHITE), theme::text_shadow(), Pickable::IGNORE));
            if th.chips {
            q.spawn((SlotCost, k.clone(), Node { position_type: PositionType::Absolute, right: Val::Px(2.0), top: Val::Px(2.0), min_width: Val::Px(15.0), height: Val::Px(15.0), padding: UiRect::axes(Val::Px(3.0), Val::Px(0.0)), border_radius: BorderRadius::all(Val::Px(8.0)), justify_content: JustifyContent::Center, align_items: AlignItems::Center, display: Display::None, ..default() }, BackgroundColor(wood::alpha(wood::TEAL, 0.9)), Pickable::IGNORE))
                .with_child((SlotCostText, k.clone(), Text::new(""), f.body(9.5, 800), TextColor(Color::WHITE), Pickable::IGNORE));
            }
            q.spawn((SlotCount, k.clone(), Text::new(""), f.body(12.0, 800), TextColor(th.text), Node { position_type: PositionType::Absolute, right: Val::Px(4.0), bottom: Val::Px(1.0), ..default() }, Pickable::IGNORE));
        });
        // The key, as bound.
        s.spawn((Node { margin: UiRect::top(Val::Px(-8.0)), ..default() }, GlobalZIndex(21), Pickable::IGNORE)).with_children(|c| {
            wood::chip(c, f, "", (SlotChip, k.clone()));
        });
    });
}

/// The tooltip over the bar (one, shared by every slot).
pub fn spawn_tooltip(mut commands: Commands, fonts: Res<Fonts>) {
    // A set width: under a max width the layout sizes the box for the unwrapped line and the
    // wrapped text spills out of it.
    let th = wood::t();
    commands
        .spawn((HudRoot, Tooltip, Node { position_type: PositionType::Absolute, width: Val::Px(300.0), flex_direction: FlexDirection::Column, row_gap: Val::Px(2.0), padding: UiRect::axes(Val::Px(10.0), Val::Px(7.0)), border: wood::b(2.0), border_radius: wood::r(8.0), display: Display::None, ..default() }, BackgroundColor(th.surface_hi), BorderColor::all(th.edge), wood::shadow(3.0, 1.0), GlobalZIndex(80), Pickable::IGNORE))
        .with_children(|t| {
            t.spawn((TooltipTitle, Text::new(""), wood::ink(&fonts, 14.0, 800), Pickable::IGNORE));
            t.spawn((TooltipText, Text::new(""), fonts.body(12.5, 600), TextColor(th.muted), TextLayout::new(Justify::Left, LineBreak::WordBoundary), Pickable::IGNORE));
        });
}

/// A school's glyph colour on this theme: its light colour on a dark ground, its dark one on a
/// light ground.
fn tint(family: (Color, Color), off: bool) -> Color {
    let light_theme = wood::t().text.to_srgba().red < 0.5;
    let c = if light_theme && !wood::t().serif_titles { family.1.mix(&family.0, 0.25) } else { family.0.mix(&Color::WHITE, 0.45) };
    if off {
        wood::alpha(c.mix(&Color::srgb(0.6, 0.6, 0.6), 0.6), 0.55)
    } else {
        c
    }
}

fn face(v: &SlotView) -> BackgroundGradient {
    let th = wood::t();
    let k = if v.off.is_some() { 0.5 } else { 1.0 };
    if let Some(c) = v.fill {
        return wood::flat(c);
    }
    match (th.serif_titles, v.family) {
        // Walnut: the school's gradient, as design D drew it.
        (true, Some((light, dark))) => BackgroundGradient::from(bevy::ui::LinearGradient::to_bottom(vec![bevy::ui::ColorStop::percent(wood::alpha(light.mix(&Color::WHITE, 0.15), k), 0.0), bevy::ui::ColorStop::percent(wood::alpha(dark.mix(&light, 0.35), k), 100.0)])),
        // Flat themes: the surface, the glyph carries the colour.
        _ => wood::flat(wood::alpha(th.surface_lo, if v.glyph.is_some() { 1.0 } else { 0.6 })),
    }
}

/// Draw every slot from [`Slots`].
#[allow(clippy::type_complexity)]
pub fn paint(
    slots: Res<Slots>,
    icons: Res<Icons>,
    mut faces: Query<(&SlotKey, &mut BackgroundGradient, &mut Outline, &mut BorderColor), (With<SlotFace>, Without<SlotSweep>)>,
    mut glyphs: Query<(&SlotKey, &mut ImageNode), With<SlotGlyph>>,
    mut sweeps: Query<(&SlotKey, &mut BackgroundGradient), (With<SlotSweep>, Without<SlotFace>)>,
    mut texts: ParamSet<(Query<(&SlotKey, &mut Text), With<SlotTime>>, Query<(&SlotKey, &mut Text), With<SlotCostText>>, Query<(&SlotKey, &mut Text), With<SlotCount>>, Query<(&SlotKey, &mut Text), With<SlotChip>>, Query<(&SlotKey, &mut Text, &mut TextColor, &mut Node), With<SlotCaption>>)>,
    mut costs: Query<(&SlotKey, &mut Node), (With<SlotCost>, Without<SlotCaption>)>,
) {
    let none = SlotView::default();
    let view = |k: &SlotKey| slots.0.get(k).unwrap_or(&none);
    let th = wood::t();
    for (k, mut g, mut o, mut b) in &mut faces {
        let v = view(k);
        let want = face(v);
        if *g != want {
            *g = want;
        }
        let ring = if v.held { Val::Px(3.0) } else { Val::Px(0.0) };
        if o.width != ring {
            o.width = ring;
        }
        // A refusal flashes the edge red for a moment.
        let edge = match v.refused {
            Some(age) if age < 0.9 => wood::HOSTILE.mix(&th.edge, (age / 0.9).clamp(0.0, 1.0)),
            _ => th.edge,
        };
        if b.top != edge {
            *b = BorderColor::all(edge);
        }
    }
    for (k, mut img) in &mut glyphs {
        let v = view(k);
        let h = icons.get(v.glyph.unwrap_or(Glyph::Skill(super::model::SkillIcon::Empty)));
        if img.image != h {
            img.image = h;
        }
        let c = match (v.fill, v.family) {
            (Some(_), _) => Color::WHITE,
            (None, Some(fam)) => tint(fam, v.off.is_some()),
            (None, None) => wood::alpha(th.text, if v.glyph.is_some() { 0.9 } else { 0.25 }),
        };
        if img.color != c {
            img.color = c;
        }
    }
    for (k, mut g) in &mut sweeps {
        let want = match view(k).cooldown {
            Some((left, total)) => {
                let done = (1.0 - left / total.max(0.01)).clamp(0.0, 1.0) * TAU;
                let shade = Color::srgba(0.05, 0.05, 0.07, 0.62);
                BackgroundGradient::from(Gradient::Conic(ConicGradient { start: 0.0, position: UiPosition::CENTER, stops: vec![AngularColorStop::new(Color::NONE, 0.0), AngularColorStop::new(Color::NONE, done), AngularColorStop::new(shade, done), AngularColorStop::new(shade, TAU)], color_space: default() }))
            }
            None => BackgroundGradient::default(),
        };
        if *g != want {
            *g = want;
        }
    }
    for (k, mut t) in &mut texts.p0() {
        let s = match view(k).cooldown {
            Some((left, _)) if left >= 1.0 => format!("{:.0}", left.ceil()),
            Some((left, _)) => format!("{left:.1}"),
            None => String::new(),
        };
        set_text(&mut t, &s);
    }
    for (k, mut t) in &mut texts.p1() {
        if let Some(c) = view(k).cost {
            set_text(&mut t, &if c.fract().abs() < 0.05 { format!("{c:.0}") } else { format!("{c:.1}") });
        }
    }
    for (k, mut n) in &mut costs {
        show(&mut n, view(k).cost.is_some_and(|c| c > 0.0) && wood::t().chips);
    }
    for (k, mut t) in &mut texts.p2() {
        set_text(&mut t, &view(k).count.map_or(String::new(), |n| n.to_string()));
    }
    for (k, mut t) in &mut texts.p3() {
        set_text(&mut t, &view(k).key);
    }
    for (k, mut t, mut c, mut n) in &mut texts.p4() {
        let v = view(k);
        show(&mut n, v.caption.is_some());
        if let Some(s) = &v.caption {
            set_text(&mut t, s);
            super::set_color(&mut c, if v.fill.is_some() { Color::WHITE } else { th.text });
        }
    }
}

/// Over the bar, the hovered slot's words: its label, then why it is greyed, or its description.
#[allow(clippy::type_complexity)]
pub fn tooltip(slots: Res<Slots>, ui: Res<UiPointer>, cams: Query<&Camera, With<Camera3d>>, roots: Query<(&SlotKey, &bevy::ui::ComputedNode, &bevy::ui::UiGlobalTransform), With<SlotRoot>>, mut tip: Query<&mut Node, With<Tooltip>>, mut title: Query<&mut Text, (With<TooltipTitle>, Without<TooltipText>)>, mut text: Query<&mut Text, (With<TooltipText>, Without<TooltipTitle>)>) {
    let screen = cams.iter().find_map(|c| c.logical_viewport_size()).unwrap_or(Vec2::new(1600.0, 900.0)) / ui.ui_scale.max(0.01);
    let hovered = ui.pos.and_then(|p| roots.iter().find(|(_, n, t)| n.contains_point(**t, p * ui.scale)).map(|(k, n, t)| (k.clone(), (t.affine().translation - n.size() / 2.0) * n.inverse_scale_factor())));
    let v = hovered.as_ref().and_then(|(k, _)| slots.0.get(k)).filter(|v| !v.label.is_empty());
    for mut n in &mut tip {
        show(&mut n, v.is_some());
        // Over the cluster: its bottom above the meters over the hovered slot, whatever its height.
        if let (Some((_, at)), Some(_)) = (&hovered, v) {
            let l = Val::Px((at.x - 40.0).max(8.0));
            let b = Val::Px((screen.y - at.y + 62.0).max(8.0));
            if n.left != l {
                n.left = l;
            }
            n.top = Val::Auto;
            if n.bottom != b {
                n.bottom = b;
            }
        }
    }
    if let Some(v) = v {
        for mut t in &mut title {
            set_text(&mut t, &v.label);
        }
        let words = match &v.off {
            Some(why) if !v.about.is_empty() => format!("{why}\n{}", v.about),
            Some(why) => why.clone(),
            None => v.about.clone(),
        };
        for mut t in &mut text {
            set_text(&mut t, &words);
        }
    }
}
