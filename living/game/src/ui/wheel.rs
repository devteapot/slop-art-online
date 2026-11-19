//! The wheel (docs/INTERFACE.md §8): hold F on a person or a thing whose place the world's
//! `menus()` gives a wheel, move toward a section, let go.
//!
//! What goes where is the rules' (`living_rules::ui::wheel_of` over the F list's own choices,
//! `verbs.rs` builds it); this module draws it and holds the input feel: the dead zone, the
//! sectors (a section owns its direction and half of each empty neighbour), the hysteresis at a
//! border and the clamp. While it is open the cursor is held (`pointer.rs` `hold`): motion moves
//! a selection out from the hub, and when it closes the cursor is where it was on screen.

use super::hit::UiPointer;
use super::icons::{Glyph, Icons, Mark};
use super::model::SkillIcon;
use super::theme::Fonts;
use super::{set_text, show, wood, HudRoot};
use crate::verbs::Verbs;
use bevy::prelude::*;
use bevy::ui::BackgroundGradient;
use living_rules::ui::{Dir, Pin, Section, Wheel};
use std::collections::HashMap;

/// Below this (logical px) from the hub, the hub is selected: letting go there cancels.
pub const DEAD_PX: f32 = 20.0;
/// The selection stops this far out, so reversing is quick.
pub const MAX_PX: f32 = 90.0;
/// A border is crossed only this far past it (degrees), so it does not flicker.
pub const HYST_DEG: f32 = 8.0;
/// F down and the pointer moved this far before the wheel would draw: it opens with that
/// direction chosen (a flick), if the press has lasted at least [`FLICK_MIN_S`].
pub const FLICK_PX: f32 = 30.0;
pub const FLICK_MIN_S: f64 = 0.08;
/// The sections' distance from the hub's centre, and their size (UI px).
const RADIUS: f32 = 118.0;
const SEC_W: f32 = 132.0;
const SEC_H: f32 = 40.0;
const HUB: f32 = 112.0;

/// An open wheel, toward one target (held while open: another body walking under the held
/// cursor does not change it).
#[derive(Clone, Debug)]
pub struct WheelOpen {
    pub aim: crate::verbs::Aim,
    pub title: String,
    pub layout: Wheel,
    /// The F list's choices toward the target (a section's sub-choice is among them).
    pub choices: Vec<crate::verbs::Choice>,
    /// How each section reads: its label, its icon (`look.icon`), its words (`about`), and the
    /// rules' reason when greyed (its `_check` text).
    pub labels: HashMap<Pin, String>,
    pub icons: HashMap<Pin, Option<String>>,
    pub abouts: HashMap<Pin, String>,
    pub reasons: HashMap<Pin, String>,
    /// The item a greyed item-taking section is asked and sent with (its reason is for it).
    pub grey_items: HashMap<Pin, String>,
    /// Opened by holding F (letting go chooses) or sticky (a click, Enter or F chooses).
    pub held: bool,
    /// Where it is drawn (logical px in the window: where the cursor was), the selection vector
    /// and the section selected (None: the hub).
    pub at: Vec2,
    pub vec: Vec2,
    pub sel: Option<Dir>,
}

impl WheelOpen {
    /// What is behind More, by name.
    pub fn more_names(&self) -> String {
        if self.layout.more.is_empty() { "nothing".into() } else { self.layout.more.iter().map(|p| p.name()).collect::<Vec<_>>().join(", ") }
    }

    /// The directions that have a section.
    pub fn dirs(&self) -> Vec<Dir> {
        self.layout.sections.iter().map(|s| s.dir).collect()
    }

    /// Move the selection by pointer motion (logical px), clamped, and re-read the sector.
    pub fn nudge(&mut self, d: Vec2) {
        self.vec = (self.vec + d).clamp_length_max(MAX_PX);
        self.sel = sector(self.vec, &self.dirs(), self.sel);
    }

    /// Point the selection at a direction (the arrow keys, a script), part way out.
    pub fn point(&mut self, d: Dir) {
        let a = d.degrees().to_radians();
        self.vec = Vec2::new(a.sin(), -a.cos()) * (MAX_PX * 0.7);
        self.sel = sector(self.vec, &self.dirs(), self.sel);
    }
}

/// Degrees between two directions on the circle (0..180).
fn apart(a: f32, b: f32) -> f32 {
    let d = (a - b).rem_euclid(360.0);
    d.min(360.0 - d)
}

/// The section a selection vector picks (screen px, y down): none inside the dead zone; else
/// the section whose direction is nearest the vector's, so each owns its 45° and half of each
/// empty neighbour's; the one selected before keeps it unless another is nearer by more than
/// [`HYST_DEG`].
pub fn sector(v: Vec2, dirs: &[Dir], prev: Option<Dir>) -> Option<Dir> {
    if v.length() < DEAD_PX || dirs.is_empty() {
        return None;
    }
    // Clockwise from screen up.
    let ang = v.x.atan2(-v.y).to_degrees().rem_euclid(360.0);
    let best = dirs.iter().copied().min_by(|a, b| apart(ang, a.degrees()).total_cmp(&apart(ang, b.degrees())))?;
    match prev.filter(|p| dirs.contains(p)) {
        Some(p) if p != best && apart(ang, p.degrees()) <= apart(ang, best.degrees()) + HYST_DEG => Some(p),
        _ => Some(best),
    }
}

/// A section's image by its look's icon name (`living_rules::ui::ICONS`), or a client
/// section's own; the theme's empty one otherwise.
pub fn glyph(what: &Pin, icon: Option<&str>) -> Glyph {
    match what {
        Pin::Own(Section::Talk) => return Glyph::Ui(Mark::Talk),
        Pin::Own(Section::Window) => return Glyph::Ui(Mark::People),
        Pin::Own(Section::Introduce) => return Glyph::Ui(Mark::Person),
        Pin::Own(Section::More) => return Glyph::Ui(Mark::Dots),
        Pin::Skill(_) => {}
    }
    // By the icon's place in the rules' vocabulary (append-only), so no name is spelt here.
    const BY_ICON: [Glyph; 17] = [
        Glyph::Skill(SkillIcon::Sword),
        Glyph::Skill(SkillIcon::Bow),
        Glyph::Skill(SkillIcon::Fire),
        Glyph::Skill(SkillIcon::Shield),
        Glyph::Skill(SkillIcon::Dodge),
        Glyph::Skill(SkillIcon::Heal),
        Glyph::Ui(Mark::Sheathed),
        Glyph::Ui(Mark::Give),
        Glyph::Ui(Mark::Trade),
        Glyph::Ui(Mark::Talk),
        Glyph::Ui(Mark::Wave),
        Glyph::Ui(Mark::Eye),
        Glyph::Ui(Mark::Book),
        Glyph::Ui(Mark::Gear),
        Glyph::Ui(Mark::Gear),
        Glyph::Ui(Mark::Person),
        Glyph::Skill(SkillIcon::Jump),
    ];
    icon.and_then(|i| living_rules::ui::ICONS.iter().position(|n| *n == i)).and_then(|k| BY_ICON.get(k).copied()).unwrap_or(Glyph::Ui(Mark::Option))
}

#[derive(Component)]
pub struct WheelRoot;
#[derive(Component)]
pub struct WheelSec(usize);
#[derive(Component)]
pub struct WheelIcon(usize);
#[derive(Component)]
pub struct WheelLabel(usize);
#[derive(Component)]
pub struct WheelNum(usize);
#[derive(Component)]
pub struct HubTitle;
#[derive(Component)]
pub struct HubText;
#[derive(Component)]
pub struct WheelDot;

/// Spawned once, hidden: the hub, eight sections and the selection's dot, updated in place.
pub fn spawn(mut commands: Commands, fonts: Res<Fonts>) {
    let f = &*fonts;
    let th = wood::t();
    commands
        .spawn((HudRoot, WheelRoot, Node { position_type: PositionType::Absolute, width: Val::Px(0.0), height: Val::Px(0.0), display: Display::None, ..default() }, GlobalZIndex(60), Pickable::IGNORE))
        .with_children(|w| {
            w.spawn((
                Node { position_type: PositionType::Absolute, left: Val::Px(-HUB / 2.0), top: Val::Px(-HUB / 2.0), width: Val::Px(HUB), height: Val::Px(HUB), flex_direction: FlexDirection::Column, justify_content: JustifyContent::Center, align_items: AlignItems::Center, row_gap: Val::Px(3.0), padding: UiRect::all(Val::Px(10.0)), border: wood::b(2.0), border_radius: BorderRadius::all(Val::Percent(50.0)), ..default() },
                BackgroundColor(th.surface_hi),
                BorderColor::all(th.edge),
                wood::shadow(3.0, 0.8),
                Pickable::IGNORE,
            ))
            .with_children(|h| {
                h.spawn((HubTitle, Text::new(""), wood::ink(f, 13.0, 800), TextLayout::new(Justify::Center, LineBreak::WordBoundary), Pickable::IGNORE));
                h.spawn((HubText, Text::new(""), f.body(10.5, 600), TextColor(th.muted), TextLayout::new(Justify::Center, LineBreak::WordBoundary), Pickable::IGNORE));
            });
            for (i, d) in Dir::ALL.iter().enumerate() {
                let a = d.degrees().to_radians();
                let c = Vec2::new(a.sin(), -a.cos()) * RADIUS;
                w.spawn((
                    WheelSec(i),
                    Node { position_type: PositionType::Absolute, left: Val::Px(c.x - SEC_W / 2.0), top: Val::Px(c.y - SEC_H / 2.0), width: Val::Px(SEC_W), height: Val::Px(SEC_H), flex_direction: FlexDirection::Row, align_items: AlignItems::Center, column_gap: Val::Px(7.0), padding: UiRect::axes(Val::Px(9.0), Val::Px(4.0)), border: wood::b(2.0), border_radius: wood::r(10.0), display: Display::None, ..default() },
                    BackgroundGradient::default(),
                    BorderColor::all(th.edge),
                    wood::shadow(2.0, 0.6),
                    Pickable::IGNORE,
                ))
                .with_children(|s| {
                    s.spawn((WheelIcon(i), Node { width: Val::Px(20.0), height: Val::Px(20.0), flex_shrink: 0.0, ..default() }, ImageNode::default(), Pickable::IGNORE));
                    s.spawn((WheelLabel(i), Text::new(""), wood::ink(f, 13.0, 800), Node { flex_grow: 1.0, ..default() }, Pickable::IGNORE));
                    s.spawn((WheelNum(i), Text::new(format!("{}", i + 1)), f.body(9.5, 700), TextColor(wood::alpha(th.muted, 0.6)), Pickable::IGNORE));
                });
            }
            w.spawn((WheelDot, Node { position_type: PositionType::Absolute, width: Val::Px(8.0), height: Val::Px(8.0), border_radius: BorderRadius::all(Val::Percent(50.0)), display: Display::None, ..default() }, BackgroundColor(th.accent.0), Pickable::IGNORE));
        });
}

/// Draw the open wheel: where it is, each section's icon, label and grey, the one selected, and
/// in the hub the target's name, or the section's label and words (its reason when greyed).
#[allow(clippy::type_complexity)]
pub fn update(
    v: Res<Verbs>,
    ui: Res<UiPointer>,
    icons: Res<Icons>,
    mut root: Query<&mut Node, (With<WheelRoot>, Without<WheelSec>, Without<WheelDot>)>,
    mut secs: Query<(&WheelSec, &mut Node, &mut BackgroundGradient, &mut BorderColor), (Without<WheelRoot>, Without<WheelDot>)>,
    mut imgs: Query<(&WheelIcon, &mut ImageNode)>,
    mut texts: ParamSet<(Query<(&WheelLabel, &mut Text, &mut TextColor)>, Query<&mut Text, With<HubTitle>>, Query<&mut Text, With<HubText>>)>,
    mut dot: Query<&mut Node, (With<WheelDot>, Without<WheelRoot>, Without<WheelSec>)>,
    windows: Query<&Window, With<bevy::window::PrimaryWindow>>,
) {
    let open = v.wheel.as_ref();
    for mut n in &mut root {
        show(&mut n, open.is_some());
        if let Some(w) = open {
            // Kept on screen: moved inward to fit.
            let logical = windows.single().map_or_else(|_| crate::capture::size().as_vec2(), |w| Vec2::new(w.width(), w.height()));
            let size = ui.val(logical);
            let c = ui.val(w.at).clamp(Vec2::splat(RADIUS + SEC_W / 2.0), (size - Vec2::splat(RADIUS + SEC_W / 2.0)).max(Vec2::splat(RADIUS + SEC_W / 2.0)));
            n.left = Val::Px(c.x.round());
            n.top = Val::Px(c.y.round());
        }
    }
    let Some(w) = open else { return };
    let th = wood::t();
    let flat = |c: Color| BackgroundGradient::from(bevy::ui::LinearGradient::to_bottom(vec![bevy::ui::ColorStop::percent(c, 0.0), bevy::ui::ColorStop::percent(c, 100.0)]));
    for (s, mut n, mut bg, mut border) in &mut secs {
        let sec = w.layout.at(Dir::at(s.0));
        show(&mut n, sec.is_some());
        let Some(sec) = sec else { continue };
        let on = w.sel == Some(sec.dir);
        let c = if on { th.accent.0 } else { th.surface_hi };
        *bg = flat(c);
        *border = BorderColor::all(if on { th.accent.1 } else { th.edge });
    }
    for (i, mut img) in &mut imgs {
        if let Some(sec) = w.layout.at(Dir::at(i.0)) {
            let h = icons.get(glyph(&sec.what, w.icons.get(&sec.what).and_then(|o| o.as_deref())));
            if img.image != h {
                img.image = h;
            }
            // The theme's ink on a section, the accent's text when selected; faint when greyed.
            let on = w.sel == Some(sec.dir);
            let ink = if on { th.accent_text } else { th.text };
            img.color = if sec.allowed { ink } else { wood::alpha(ink, 0.35) };
        }
    }
    for (l, mut t, mut col) in &mut texts.p0() {
        if let Some(sec) = w.layout.at(Dir::at(l.0)) {
            let mark = if sec.words { " …" } else if sec.sub { " ›" } else { "" };
            set_text(&mut t, &format!("{}{mark}", w.labels.get(&sec.what).cloned().unwrap_or_else(|| super::label(sec.what.name()))));
            let on = w.sel == Some(sec.dir);
            let c = if on { th.accent_text } else if sec.allowed { th.text } else { wood::alpha(th.muted, 0.7) };
            if col.0 != c {
                col.0 = c;
            }
        }
    }
    let selected = w.sel.and_then(|d| w.layout.at(d));
    for mut t in &mut texts.p1() {
        set_text(&mut t, &selected.map_or_else(|| w.title.clone(), |s| w.labels.get(&s.what).cloned().unwrap_or_else(|| super::label(s.what.name()))));
    }
    for mut t in &mut texts.p2() {
        let words = selected.map_or(String::new(), |s| if s.allowed { w.abouts.get(&s.what).cloned().unwrap_or_default() } else { w.reasons.get(&s.what).cloned().unwrap_or_default() });
        set_text(&mut t, &wood::readable(&words));
    }
    for mut n in &mut dot {
        let on = w.vec.length() >= DEAD_PX;
        show(&mut n, on);
        let p = w.vec / ui.ui_scale.max(0.01) * 0.9;
        n.left = Val::Px((p.x - 4.0).round());
        n.top = Val::Px((p.y - 4.0).round());
    }
}

/// The hub's words for a section: the first sentence of its description, up to its first
/// clause when long (the hub is small), and never past [`HUB_WORDS`] characters.
pub fn first_sentence(s: &str) -> String {
    let s = s.trim();
    let mut out = match s.find(". ") {
        Some(i) => s[..=i].to_string(),
        None => s.to_string(),
    };
    if out.chars().count() > HUB_WORDS {
        if let Some(i) = out.find([':', ';', ',']).filter(|i| *i > 12) {
            out = format!("{}.", &out[..i]);
        }
    }
    if out.chars().count() > HUB_WORDS {
        let cut: String = out.chars().take(HUB_WORDS - 1).collect();
        out = format!("{}…", cut.trim_end());
    }
    out
}

/// The most characters the hub shows of a description.
pub const HUB_WORDS: usize = 64;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_icon_of_the_vocabulary_has_an_image() {
        // A new icon at the end of `ICONS` needs its image here.
        for i in living_rules::ui::ICONS {
            assert_ne!(glyph(&Pin::parse("x"), Some(i)), Glyph::Ui(Mark::Option), "{i}");
        }
    }

    fn v(deg: f32, len: f32) -> Vec2 {
        let a = deg.to_radians();
        Vec2::new(a.sin(), -a.cos()) * len
    }

    #[test]
    fn the_hub_inside_the_dead_zone_and_the_nearest_section_beyond() {
        let all = Dir::ALL.to_vec();
        assert_eq!(sector(v(90.0, DEAD_PX - 1.0), &all, None), None);
        assert_eq!(sector(v(90.0, 60.0), &all, None), Some(Dir::E));
        assert_eq!(sector(v(0.0, 60.0), &all, None), Some(Dir::N));
        assert_eq!(sector(v(350.0, 60.0), &all, None), Some(Dir::N));
        assert_eq!(sector(v(200.0, 60.0), &all, None), Some(Dir::S));
        assert_eq!(sector(v(30.0, 60.0), &all, None), Some(Dir::Ne));
    }

    #[test]
    fn a_section_widens_into_its_empty_neighbours() {
        // Only n and s: each owns half the circle.
        let two = [Dir::N, Dir::S];
        assert_eq!(sector(v(80.0, 60.0), &two, None), Some(Dir::N));
        assert_eq!(sector(v(100.0, 60.0), &two, None), Some(Dir::S));
        // n, e, s, w: e owns 45..135.
        let four = [Dir::N, Dir::E, Dir::S, Dir::W];
        assert_eq!(sector(v(50.0, 60.0), &four, None), Some(Dir::E));
        assert_eq!(sector(v(130.0, 60.0), &four, None), Some(Dir::E));
    }

    #[test]
    fn a_border_holds_the_selection_by_the_hysteresis() {
        let all = Dir::ALL.to_vec();
        // The n/ne border is at 22.5°: from n, 26° stays n; 31° goes ne.
        assert_eq!(sector(v(26.0, 60.0), &all, Some(Dir::N)), Some(Dir::N));
        assert_eq!(sector(v(31.0, 60.0), &all, Some(Dir::N)), Some(Dir::Ne));
        // From ne, 19° stays ne; 14° goes n.
        assert_eq!(sector(v(19.0, 60.0), &all, Some(Dir::Ne)), Some(Dir::Ne));
        assert_eq!(sector(v(14.0, 60.0), &all, Some(Dir::Ne)), Some(Dir::N));
    }

    #[test]
    fn the_selection_is_clamped_so_reversing_is_quick() {
        let mut w = WheelOpen { aim: crate::verbs::Aim::Me, title: String::new(), layout: Wheel::default(), choices: Vec::new(), labels: HashMap::new(), icons: HashMap::new(), abouts: HashMap::new(), reasons: HashMap::new(), grey_items: HashMap::new(), held: true, at: Vec2::ZERO, vec: Vec2::ZERO, sel: None };
        w.layout.sections = Dir::ALL.iter().map(|d| living_rules::ui::WheelSection { dir: *d, what: Pin::parse("x"), allowed: true, pinned: false, sub: false, words: false }).collect();
        w.nudge(Vec2::new(500.0, 0.0));
        assert_eq!((w.vec.length().round(), w.sel), (MAX_PX, Some(Dir::E)));
        // Straight back across: west within one move of the clamp's length.
        w.nudge(Vec2::new(-2.0 * MAX_PX, 0.0));
        assert_eq!(w.sel, Some(Dir::W));
        // Digits are clockwise from north.
        assert_eq!((Dir::at(0), Dir::at(2), Dir::at(7)), (Dir::N, Dir::E, Dir::Nw));
    }
}
