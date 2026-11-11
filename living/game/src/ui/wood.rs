//! Interface D's look (2026-11-11, `.local/living/ui-designs/`, design D): walnut frames with a
//! brass edge, parchment bodies, ink outlines and gold buttons, toon-warm like the world they sit
//! in rather than a dark web overlay. Every D widget takes its colours, type and recipes from
//! here.
//!
//! Sizes are the mock-up's own pixels: the design was drawn at 1600×900, and the UI scale is
//! the window's height over 900 (`ui::scale`).
//!
//! Type: Nunito for everything read, Marcellus for titles (both SIL OFL 1.1, in
//! `assets/ui/fonts/`). Neither has ▾, ✕, ⌥ or →: those are drawn as glyphs (`icons.rs`), and
//! text from the rules goes through [`readable`].

use super::icons::{Glyph, Icons};
use super::theme::Fonts;
use bevy::prelude::*;
use bevy::ui::{BackgroundGradient, BoxShadow, ColorStop, LinearGradient};

const fn hex(v: u32) -> Color {
    Color::srgb(((v >> 16) & 255) as f32 / 255.0, ((v >> 8) & 255) as f32 / 255.0, (v & 255) as f32 / 255.0)
}

const fn hexa(v: u32, a: f32) -> Color {
    Color::srgba(((v >> 16) & 255) as f32 / 255.0, ((v >> 8) & 255) as f32 / 255.0, (v & 255) as f32 / 255.0, a)
}

pub const WAL_TOP: Color = hex(0x6b4529);
pub const WAL: Color = hex(0x5a3a22);
pub const WAL2: Color = hex(0x3a2414);
pub const BRASS: Color = hex(0xd9a441);
pub const BRASS2: Color = hex(0xf6d78a);
pub const PARCH_HI: Color = hex(0xfbf0d6);
pub const PARCH: Color = hex(0xf4e4c1);
pub const PARCH2: Color = hex(0xe4cb9c);
pub const INK: Color = hex(0x2a1d14);
pub const INK_SOFT: Color = hexa(0x2a1d14, 0.45);
pub const MUTED: Color = hex(0x7b6449);
pub const SUB: Color = hex(0x7a4a1e);
pub const DASH: Color = hex(0xc9ad7d);
pub const ROSE: Color = hex(0xd9475b);
pub const ROSE2: Color = hex(0xf58a86);
pub const ROSE_LO: Color = hex(0xa72f43);
pub const TEAL: Color = hex(0x2f9c90);
pub const TEAL2: Color = hex(0x86e0d2);
pub const TALK: Color = hex(0x4f9fd6);
pub const TALK_INK: Color = hex(0x2a6f9e);
pub const HOSTILE: Color = hex(0xc9362f);
pub const X_RED: Color = hex(0xc0503c);
pub const BTN_HI: Color = hex(0xffe7a6);
pub const BTN_LO: Color = hex(0xf0bf5a);
pub const GHOST: Color = hex(0xfbf1da);
pub const CREAM: Color = hex(0xfffaf0);
pub const ME_TINT: Color = hex(0xf6e0b0);
pub const NAME_ME: Color = hex(0x8a4f12);
pub const HOT_HI: Color = hex(0xffe7a6);
pub const HOT_LO: Color = hex(0xf6cd73);
pub const ON_WOOD: Color = hex(0xf3e3c0);
pub const ANCHOR: Color = hex(0xfff3c4);
pub const DRAWN: Color = hex(0xe0503c);
pub const TRACK: Color = hex(0x23150c);

pub fn alpha(c: Color, a: f32) -> Color {
    let mut c = c;
    c.set_alpha(c.alpha() * a);
    c
}

fn down(stops: &[(Color, f32)]) -> BackgroundGradient {
    BackgroundGradient::from(LinearGradient::to_bottom(stops.iter().map(|(c, p)| ColorStop::percent(*c, *p)).collect()))
}

/// The walnut panel: a vertical grain gradient, an ink edge and a hard drop shadow (the toon
/// look's offset shadow, not a blur). The caller's `Node` sets the 3 px border and the radius.
pub fn wood() -> impl Bundle {
    (down(&[(WAL_TOP, 0.0), (WAL, 45.0), (WAL2, 100.0)]), BorderColor::all(INK), BoxShadow::new(alpha(INK, 0.45), Val::ZERO, Val::Px(5.0), Val::ZERO, Val::ZERO))
}

/// The brass line just inside a walnut panel's edge (the mock-up's inset shadow), as a child.
pub fn rim(radius: f32) -> impl Bundle {
    (
        Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(radius)), ..default() },
        BorderColor::all(alpha(BRASS2, 0.55)),
        Pickable::IGNORE,
    )
}

/// Parchment, for a window's body and the rows of lists.
pub fn parch() -> impl Bundle {
    (down(&[(PARCH_HI, 0.0), (PARCH, 55.0), (PARCH2, 100.0)]), BorderColor::all(INK))
}

/// A gold button's face.
pub fn gold() -> BackgroundGradient {
    down(&[(BTN_HI, 0.0), (BTN_LO, 100.0)])
}

/// A highlighted list row.
pub fn hot_row() -> BackgroundGradient {
    down(&[(HOT_HI, 0.0), (HOT_LO, 100.0)])
}

/// The icon tile of the two buttons (Pack, Menu): cream, or gold while its window is open.
pub fn tile(on: bool) -> BackgroundGradient {
    if on {
        down(&[(hex(0xffe28a), 0.0), (hex(0xf0b443), 100.0)])
    } else {
        down(&[(hex(0xfbe9c3), 0.0), (hex(0xe2c18b), 100.0)])
    }
}

pub fn hard_shadow(y: f32, a: f32) -> BoxShadow {
    BoxShadow::new(alpha(INK, a), Val::ZERO, Val::Px(y), Val::ZERO, Val::ZERO)
}

/// A title in Marcellus, brass over an ink drop.
pub fn title(f: &Fonts, size: f32) -> impl Bundle {
    (f.title(size), TextColor(BRASS2), bevy::ui::widget::TextShadow { offset: Vec2::new(0.0, 2.0), color: INK })
}

/// Text on walnut that is not a title.
pub fn on_wood(f: &Fonts, size: f32, weight: u16) -> impl Bundle {
    (f.body(size, weight), TextColor(ON_WOOD))
}

/// Ink text on parchment.
pub fn ink(f: &Fonts, size: f32, weight: u16) -> impl Bundle {
    (f.body(size, weight), TextColor(INK))
}

/// A key chip ("I", "Esc", "LMB"): parchment, ink edge. `extra` goes on its text.
pub fn chip(p: &mut ChildSpawnerCommands, f: &Fonts, text: &str, extra: impl Bundle) -> Entity {
    let mut t = Entity::PLACEHOLDER;
    p.spawn((
        Node { padding: UiRect::axes(Val::Px(5.0), Val::Px(0.0)), min_width: Val::Px(22.0), height: Val::Px(20.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(6.0)), flex_shrink: 0.0, ..default() },
        BackgroundColor(PARCH),
        BorderColor::all(INK),
        hard_shadow(2.0, 0.5),
        Pickable::IGNORE,
    ))
    .with_children(|c| {
        t = c.spawn((Text::new(text), f.body(11.0, 900), TextColor(INK), Pickable::IGNORE, extra)).id();
    });
    t
}

/// A small chip holding a glyph instead of a letter (⌥, a mouse button).
pub fn glyph_chip(p: &mut ChildSpawnerCommands, icons: &Icons, g: Glyph, extra: impl Bundle) -> Entity {
    let mut t = Entity::PLACEHOLDER;
    p.spawn((
        Node { width: Val::Px(26.0), height: Val::Px(20.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: UiRect::all(Val::Px(2.0)), border_radius: BorderRadius::all(Val::Px(6.0)), flex_shrink: 0.0, ..default() },
        BackgroundColor(PARCH),
        BorderColor::all(INK),
        hard_shadow(2.0, 0.5),
        Pickable::IGNORE,
    ))
    .with_children(|c| {
        t = c.spawn((Node { width: Val::Px(13.0), height: Val::Px(13.0), ..default() }, ImageNode::new(icons.get(g)).with_color(INK), Pickable::IGNORE, extra)).id();
    });
    t
}

/// Glyph sizes and their tint for an icon on a light ground.
pub fn icon(icons: &Icons, g: Glyph, size: f32, color: Color) -> impl Bundle {
    (Node { width: Val::Px(size), height: Val::Px(size), flex_shrink: 0.0, ..default() }, ImageNode::new(icons.get(g)).with_color(color), Pickable::IGNORE)
}

/// Text from the rules or the authority, with characters the game's fonts lack replaced by ones
/// they have (Nunito and Marcellus have no → or ▸; the act feedback writes "teach medicine →
/// person", and the old F hint's "▸" drew as a missing glyph).
pub fn readable(s: &str) -> String {
    if !s.chars().any(|c| matches!(c, '→' | '←' | '⇒' | '▸' | '▶' | '✓' | '✗' | '✕' | '▾')) {
        return s.to_string();
    }
    s.replace(['→', '⇒', '▸', '▶'], "›").replace('←', "‹").replace('✓', "").replace(['✗', '✕'], "×").replace('▾', "")
}

#[cfg(test)]
mod tests {
    #[test]
    fn arrows_the_fonts_lack_become_ones_they_have() {
        assert_eq!(super::readable("teach medicine → person"), "teach medicine › person");
        assert_eq!(super::readable("Give ›"), "Give ›");
        assert_eq!(super::readable("Mercy ▸"), "Mercy ›");
    }
}
