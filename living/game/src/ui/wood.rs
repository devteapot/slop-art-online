//! The interface's look, as themes (2026-11-11). Every visual value of the game UI's windows,
//! buttons, lists and prompts comes from the current [`Theme`]: colours, borders, corner radius,
//! ornament, type faces and sizes, shadows, and density (which details show inline).
//!
//! - **Glass** (the default since play-test 5): smoked, translucent panels with a subtle
//!   top-to-bottom gradient and a thin light edge, light text with a dark drop under it (so it
//!   reads over bright sky and white walls as over night ground), and smaller footprints:
//!   narrower windows, tighter paddings and gaps ([`Theme::density`]), so the world shows
//!   around and through them. No blur of what is behind: Bevy 0.20's UI has no backdrop
//!   filter, and the panel's tint carries the contrast instead.
//! - **Clear:** light neutral panels, flat, thin edges, a soft shadow, one face
//!   (Nunito) at two weights, no ornament.
//! - **Night:** the same, dark and translucent.
//! - **Linen:** warm and flat, a hint of the game's palette, no wood, brass or parchment.
//! - **Walnut:** design D as first built: walnut frames with a brass line, parchment bodies,
//!   gold buttons, Marcellus titles, key chips everywhere.
//!
//! Settings › Play chooses it, F4 cycles it, and the settings file keeps it. A change rebuilds
//! the UI's trees (`ui::rebuild`), so what was spawned with the old colours is spawned again.
//!
//! The module keeps its name from design D; the functions name roles (text, edge, surface),
//! not materials. Nunito and Marcellus have no ▾, ✕, ⌥ or →: those are drawn as glyphs
//! (`icons.rs`), and text from the rules goes through [`readable`].

use super::icons::{Glyph, Icons};
use super::theme::Fonts;
use bevy::prelude::*;
use bevy::ui::{BackgroundGradient, BoxShadow, ColorStop, LinearGradient};
use std::sync::RwLock;

const fn hex(v: u32) -> Color {
    Color::srgb(((v >> 16) & 255) as f32 / 255.0, ((v >> 8) & 255) as f32 / 255.0, (v & 255) as f32 / 255.0)
}

const fn hexa(v: u32, a: f32) -> Color {
    Color::srgba(((v >> 16) & 255) as f32 / 255.0, ((v >> 8) & 255) as f32 / 255.0, (v & 255) as f32 / 255.0, a)
}

#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Name {
    #[default]
    Glass,
    Clear,
    Night,
    Linen,
    Walnut,
}

impl Name {
    pub const ALL: [Name; 5] = [Name::Glass, Name::Clear, Name::Night, Name::Linen, Name::Walnut];

    pub fn key(self) -> &'static str {
        match self {
            Name::Glass => "glass",
            Name::Clear => "clear",
            Name::Night => "night",
            Name::Linen => "linen",
            Name::Walnut => "walnut",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Name::Glass => "Glass",
            Name::Clear => "Clear",
            Name::Night => "Night",
            Name::Linen => "Linen",
            Name::Walnut => "Walnut",
        }
    }

    pub fn parse(s: &str) -> Option<Name> {
        Name::ALL.into_iter().find(|n| n.key() == s.trim().to_ascii_lowercase())
    }

    pub fn next(self) -> Name {
        let i = Name::ALL.iter().position(|n| *n == self).unwrap_or(0);
        Name::ALL[(i + 1) % Name::ALL.len()]
    }
}

/// Everything the interface's look is made of.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Theme {
    pub name: Name,
    /// Window frames and the corner's buttons: a top and bottom colour (equal: flat).
    pub panel: (Color, Color),
    /// Their edge, its width, and an inner ornament line (none: no ornament).
    pub edge: Color,
    pub edge_px: f32,
    pub rim: Option<Color>,
    /// A window's body inside its frame (none: the body is the frame, no second edge).
    pub body: Option<(Color, Color)>,
    pub body_edge: Color,
    /// Rows, chips, notes, prompts: a light surface; and a lighter one; and a darker one.
    pub surface: Color,
    pub surface_hi: Color,
    pub surface_lo: Color,
    /// Text on surfaces and bodies, quieter text, and section headings.
    pub text: Color,
    pub muted: Color,
    pub heading: Color,
    /// Text on the frame: the title, and anything else there.
    pub title: Color,
    pub on_panel: Color,
    /// Buttons: chosen or live (and its edge), and plain; a highlighted row.
    pub accent: (Color, Color),
    pub accent_text: Color,
    pub plain: Color,
    pub hot: (Color, Color),
    /// A text field and the others' bubbles in a conversation; mine.
    pub field: Color,
    pub mine: Color,
    pub name_mine: Color,
    pub talk: Color,
    pub talk_ink: Color,
    pub close: Color,
    pub close_glyph: Color,
    /// Separators.
    pub line: Color,
    /// Corner radius and edge scale on every node (1: as designed).
    pub radius: f32,
    /// Shadows: offset, blur and strength (a toon hard drop, or a soft one).
    pub shadow_y: f32,
    pub shadow_blur: f32,
    pub shadow_a: f32,
    pub shadow: Color,
    /// Titles in the title face (Marcellus) or the body face, and their size factor.
    pub serif_titles: bool,
    pub title_scale: f32,
    /// Density: key chips beside titles and buttons, the title bar's grip, help lines.
    pub chips: bool,
    pub grip: bool,
    pub help: bool,
    /// The compass face and ring.
    pub compass: (Color, Color),
    /// A drop under light text everywhere in the interface (none: only where a widget sets one),
    /// so it keeps its contrast over whatever shows through a translucent panel ([`shade_text`]).
    pub text_shadow: Option<Color>,
    /// Footprint: windows' widths, paddings and gaps as a fraction of design D's (1: as drawn).
    pub density: f32,
    /// The ground of what floats over the world on its own (tip pills, notes, a slot's tooltip),
    /// where a theme's surface is only a band meant to lie on a panel (none: the surface).
    pub float: Option<Color>,
}

impl Theme {
    pub fn of(n: Name) -> Theme {
        match n {
            Name::Walnut => Theme {
                name: n,
                panel: (hex(0x6b4529), hex(0x3a2414)),
                edge: hex(0x2a1d14),
                edge_px: 1.0,
                rim: Some(hexa(0xf6d78a, 0.55)),
                body: Some((hex(0xfbf0d6), hex(0xe4cb9c))),
                body_edge: hex(0x2a1d14),
                surface: hex(0xf4e4c1),
                surface_hi: hex(0xfbf0d6),
                surface_lo: hex(0xe4cb9c),
                text: hex(0x2a1d14),
                muted: hex(0x7b6449),
                heading: hex(0x7a4a1e),
                title: hex(0xf6d78a),
                on_panel: hex(0xf3e3c0),
                accent: (hex(0xffe7a6), hex(0xf0bf5a)),
                accent_text: hex(0x2a1d14),
                plain: hex(0xfbf1da),
                hot: (hex(0xffe7a6), hex(0xf6cd73)),
                field: hex(0xfffaf0),
                mine: hex(0xf6e0b0),
                name_mine: hex(0x8a4f12),
                talk: hex(0x4f9fd6),
                talk_ink: hex(0x2a6f9e),
                close: hex(0xc0503c),
                close_glyph: Color::WHITE,
                line: hex(0xc9ad7d),
                radius: 1.0,
                shadow_y: 4.0,
                shadow_blur: 0.0,
                shadow_a: 0.45,
                shadow: hex(0x2a1d14),
                serif_titles: true,
                title_scale: 1.0,
                chips: true,
                grip: true,
                help: true,
                compass: (hex(0xfbefcf), hex(0x5a3a22)),
                text_shadow: None,
                density: 1.0,
                float: None,
            },
            Name::Glass => Theme {
                name: n,
                // Smoked glass: a cool slate top over a deeper bottom, both translucent. The tint
                // is what keeps light text legible over a bright world (no backdrop blur in
                // Bevy 0.20's UI): about a fifth of the world shows through, and
                // `glass_keeps_contrast_over_a_bright_world` holds text to WCAG AA over the
                // brightest ground measured by day (glass-1 stills).
                panel: (hexa(0x222a37, 0.76), hexa(0x0b0e14, 0.84)),
                edge: hexa(0xffffff, 0.16),
                edge_px: 0.5,
                rim: None,
                body: None,
                body_edge: hexa(0xffffff, 0.08),
                // Rows, chips, cells and fields are darker bands under their text.
                surface: hexa(0x05070b, 0.26),
                // A raised cell (a full pack cell, the Give list): lighter than the panel.
                surface_hi: hexa(0x3a4456, 0.62),
                surface_lo: hexa(0x05070b, 0.34),
                text: hex(0xf6f7fa),
                muted: hex(0xd0d5dd),
                heading: hex(0xdfe3ea),
                title: hex(0xffffff),
                on_panel: hex(0xdfe3ea),
                accent: (hexa(0x6b97ff, 0.92), hexa(0x3f6fe0, 0.92)),
                accent_text: Color::WHITE,
                plain: hexa(0xffffff, 0.09),
                hot: (hexa(0x86aaff, 0.30), hexa(0x86aaff, 0.20)),
                field: hexa(0x05070b, 0.34),
                mine: hexa(0x6f9cff, 0.26),
                name_mine: hex(0xb2caff),
                talk: hex(0x5b8cff),
                talk_ink: hex(0xb2caff),
                close: hexa(0xffffff, 0.08),
                close_glyph: hex(0xdfe3ea),
                line: hexa(0xffffff, 0.10),
                radius: 0.85,
                shadow_y: 4.0,
                shadow_blur: 14.0,
                shadow_a: 0.18,
                shadow: hex(0x000000),
                serif_titles: false,
                title_scale: 0.72,
                chips: false,
                grip: false,
                help: false,
                compass: (hexa(0x141a24, 0.55), hexa(0xffffff, 0.22)),
                text_shadow: Some(hexa(0x000000, 0.80)),
                density: 0.72,
                float: Some(hexa(0x141a24, 0.86)),
            },
            Name::Clear => Theme {
                name: n,
                panel: (hexa(0xfafaf8, 0.96), hexa(0xf3f3f0, 0.96)),
                edge: hexa(0x1c2024, 0.12),
                edge_px: 0.5,
                rim: None,
                body: None,
                body_edge: hexa(0x1c2024, 0.10),
                surface: hex(0xf4f4f1),
                surface_hi: hex(0xffffff),
                surface_lo: hex(0xe9e9e5),
                text: hex(0x1f2328),
                muted: hex(0x6a7079),
                heading: hex(0x3a4048),
                title: hex(0x1f2328),
                on_panel: hex(0x3a4048),
                accent: (hex(0x2f6fd1), hex(0x2f6fd1)),
                accent_text: Color::WHITE,
                plain: hex(0xececea),
                hot: (hex(0xe4ecf8), hex(0xe4ecf8)),
                field: hex(0xffffff),
                mine: hex(0xe4ecf8),
                name_mine: hex(0x2f5fa8),
                talk: hex(0x2f6fd1),
                talk_ink: hex(0x2f5fa8),
                close: hexa(0x1f2328, 0.06),
                close_glyph: hex(0x5a6069),
                line: hexa(0x1c2024, 0.10),
                radius: 0.85,
                shadow_y: 6.0,
                shadow_blur: 18.0,
                shadow_a: 0.16,
                shadow: hex(0x10141a),
                serif_titles: false,
                title_scale: 0.78,
                chips: false,
                grip: false,
                help: false,
                compass: (hexa(0xfafaf8, 0.92), hexa(0x1c2024, 0.18)),
                text_shadow: None,
                density: 1.0,
                float: None,
            },
            Name::Night => Theme {
                name: n,
                panel: (hexa(0x14171d, 0.84), hexa(0x14171d, 0.84)),
                edge: hexa(0xffffff, 0.10),
                edge_px: 0.5,
                rim: None,
                body: None,
                body_edge: hexa(0xffffff, 0.08),
                surface: hexa(0xffffff, 0.06),
                surface_hi: hexa(0xffffff, 0.10),
                surface_lo: hexa(0xffffff, 0.03),
                text: hex(0xeceef2),
                muted: hex(0x9aa1ab),
                heading: hex(0xc9ced6),
                title: hex(0xf2f3f5),
                on_panel: hex(0xc9ced6),
                accent: (hex(0x4a7fe0), hex(0x4a7fe0)),
                accent_text: Color::WHITE,
                plain: hexa(0xffffff, 0.08),
                hot: (hexa(0x6f9cff, 0.20), hexa(0x6f9cff, 0.20)),
                field: hexa(0xffffff, 0.07),
                mine: hexa(0x6f9cff, 0.18),
                name_mine: hex(0x9fbcff),
                talk: hex(0x4a7fe0),
                talk_ink: hex(0x9fbcff),
                close: hexa(0xffffff, 0.07),
                close_glyph: hex(0xc9ced6),
                line: hexa(0xffffff, 0.08),
                radius: 0.85,
                shadow_y: 6.0,
                shadow_blur: 20.0,
                shadow_a: 0.30,
                shadow: hex(0x000000),
                serif_titles: false,
                title_scale: 0.78,
                chips: false,
                grip: false,
                help: false,
                compass: (hexa(0x14171d, 0.70), hexa(0xffffff, 0.18)),
                text_shadow: None,
                density: 1.0,
                float: None,
            },
            Name::Linen => Theme {
                name: n,
                panel: (hexa(0xf5eee2, 0.97), hexa(0xf5eee2, 0.97)),
                edge: hexa(0x5a3a22, 0.18),
                edge_px: 0.5,
                rim: None,
                body: None,
                body_edge: hexa(0x5a3a22, 0.12),
                surface: hex(0xefe5d4),
                surface_hi: hex(0xfbf7f0),
                surface_lo: hex(0xe6d9c3),
                text: hex(0x33281f),
                muted: hex(0x7d6c5b),
                heading: hex(0x6b4a2c),
                title: hex(0x33281f),
                on_panel: hex(0x5b4a3a),
                accent: (hex(0xc9873b), hex(0xc9873b)),
                accent_text: Color::WHITE,
                plain: hex(0xe9dfcd),
                hot: (hex(0xf1dfbf), hex(0xf1dfbf)),
                field: hex(0xfffcf6),
                mine: hex(0xf1dfbf),
                name_mine: hex(0x8a5a26),
                talk: hex(0x3f86b8),
                talk_ink: hex(0x2f6a94),
                close: hexa(0x5a3a22, 0.07),
                close_glyph: hex(0x7d6c5b),
                line: hexa(0x5a3a22, 0.12),
                radius: 0.85,
                shadow_y: 5.0,
                shadow_blur: 16.0,
                shadow_a: 0.16,
                shadow: hex(0x3a2414),
                serif_titles: false,
                title_scale: 0.78,
                chips: false,
                grip: false,
                help: false,
                compass: (hexa(0xf5eee2, 0.92), hexa(0x5a3a22, 0.25)),
                text_shadow: None,
                density: 1.0,
                float: None,
            },
        }
    }
}

static CURRENT: RwLock<Option<Theme>> = RwLock::new(None);

/// The theme in force.
pub fn t() -> Theme {
    CURRENT.read().ok().and_then(|g| *g).unwrap_or_else(|| Theme::of(Name::default()))
}

/// Put a theme in force (the widgets are rebuilt by `ui::rebuild`).
pub fn set(n: Name) {
    if let Ok(mut g) = CURRENT.write() {
        *g = Some(Theme::of(n));
    }
}

// Colours that are the game's, whatever the theme (health, hostility, the anchors' outline).
pub const ROSE: Color = hex(0xd9475b);
pub const ROSE2: Color = hex(0xf58a86);
pub const ROSE_LO: Color = hex(0xa72f43);
pub const TEAL: Color = hex(0x2f9c90);
pub const TEAL2: Color = hex(0x86e0d2);
pub const HOSTILE: Color = hex(0xc9362f);
pub const ANCHOR: Color = hex(0xfff3c4);
pub const TRACK: Color = hex(0x23150c);

// Roles, from the theme.
pub fn text() -> Color {
    t().text
}
pub fn muted() -> Color {
    t().muted
}
pub fn heading() -> Color {
    t().heading
}
pub fn edge() -> Color {
    t().edge
}
pub fn surface() -> Color {
    t().surface
}
pub fn surface_hi() -> Color {
    t().surface_hi
}
pub fn surface_lo() -> Color {
    t().surface_lo
}
/// The ground of a note, pill or tooltip over the world: the theme's [`Theme::float`], or the
/// surface the widget would use (`or`) in a theme whose surfaces stand on their own.
pub fn float_or(or: Color) -> Color {
    t().float.unwrap_or(or)
}
pub fn on_panel() -> Color {
    t().on_panel
}
pub fn plain() -> Color {
    t().plain
}
pub fn field() -> Color {
    t().field
}
pub fn mine() -> Color {
    t().mine
}
pub fn name_mine() -> Color {
    t().name_mine
}
pub fn talk() -> Color {
    t().talk
}
pub fn talk_ink() -> Color {
    t().talk_ink
}
pub fn line() -> Color {
    t().line
}
pub fn accent_text() -> Color {
    t().accent_text
}

/// A corner radius as designed, scaled by the theme.
pub fn r(px: f32) -> BorderRadius {
    BorderRadius::all(Val::Px(px * t().radius))
}

/// An edge as designed (3 px on frames, 2 px on rows and chips), as thick as the theme draws.
pub fn b(px: f32) -> UiRect {
    UiRect::all(Val::Px(if t().edge_px < 1.0 { 1.0 } else { px }))
}

pub fn alpha(c: Color, a: f32) -> Color {
    let mut c = c;
    c.set_alpha(c.alpha() * a);
    c
}

/// A padding, gap or margin as designed, scaled by the theme's density (never under 2 px).
pub fn d(px: f32) -> f32 {
    (px * t().density).round().max(px.min(2.0))
}

/// Light text spawned anywhere in the interface gets the theme's drop under it, if it has one
/// (Glass): one rule for every widget's text, instead of a shadow written into each. Dark text
/// (a cream bubble's, a light button's) is left as it is, and so is text that has its own.
pub fn shade_text(mut commands: Commands, q: Query<(Entity, &TextColor), (Added<Text>, Without<bevy::ui::widget::TextShadow>)>) {
    let Some(c) = t().text_shadow else { return };
    for (e, tc) in &q {
        if light(tc.0) {
            commands.entity(e).try_insert(bevy::ui::widget::TextShadow { offset: Vec2::new(0.0, 1.0), color: c });
        }
    }
}

/// Relative luminance (WCAG, linear sRGB).
pub fn luminance(c: Color) -> f32 {
    let l = c.to_linear();
    0.2126 * l.red + 0.7152 * l.green + 0.0722 * l.blue
}

fn light(c: Color) -> bool {
    luminance(c) > 0.3
}

fn down(stops: &[(Color, f32)]) -> BackgroundGradient {
    BackgroundGradient::from(LinearGradient::to_bottom(stops.iter().map(|(c, p)| ColorStop::percent(*c, *p)).collect()))
}

pub fn flat(c: Color) -> BackgroundGradient {
    down(&[(c, 0.0), (c, 100.0)])
}

/// A window frame or a corner button: the theme's panel, edge and shadow. The caller's `Node`
/// sets `b(3.0)` and `r(12.0)`.
pub fn wood() -> impl Bundle {
    let th = t();
    (down(&[(th.panel.0, 0.0), (th.panel.1, 100.0)]), BorderColor::all(th.edge), shadow(5.0, 1.0))
}

/// The ornament line inside a frame (nothing, in a theme without ornament).
pub fn rim(radius: f32) -> impl Bundle {
    let th = t();
    (
        Node { position_type: PositionType::Absolute, left: Val::Px(0.0), right: Val::Px(0.0), top: Val::Px(0.0), bottom: Val::Px(0.0), border: UiRect::all(Val::Px(if th.rim.is_some() { 2.0 } else { 0.0 })), border_radius: BorderRadius::all(Val::Px(radius * th.radius)), ..default() },
        BorderColor::all(th.rim.unwrap_or(Color::NONE)),
        Pickable::IGNORE,
    )
}

/// A window's body: its own surface and edge, or the frame itself in a flat theme.
pub fn parch() -> impl Bundle {
    let th = t();
    match th.body {
        Some((a, b)) => (down(&[(a, 0.0), (b, 100.0)]), BorderColor::all(th.body_edge)),
        None => (BackgroundGradient::default(), BorderColor::all(Color::NONE)),
    }
}

/// A window body's margin and edge (none in a flat theme).
pub fn body_frame() -> (UiRect, UiRect) {
    match t().body {
        Some(_) => (UiRect::new(Val::Px(9.0), Val::Px(9.0), Val::Px(0.0), Val::Px(9.0)), b(2.0)),
        None => (UiRect::new(Val::Px(4.0), Val::Px(4.0), Val::Px(0.0), Val::Px(4.0)), UiRect::ZERO),
    }
}

/// A chosen or live button's face.
pub fn gold() -> BackgroundGradient {
    let th = t();
    down(&[(th.accent.0, 0.0), (th.accent.1, 100.0)])
}

/// A highlighted list row.
pub fn hot_row() -> BackgroundGradient {
    let th = t();
    down(&[(th.hot.0, 0.0), (th.hot.1, 100.0)])
}

/// The icon tile of the corner's buttons: plain, or the accent while its window is open.
pub fn tile(on: bool) -> BackgroundGradient {
    if on {
        gold()
    } else {
        flat(t().plain)
    }
}

/// The theme's shadow, `y` as designed (a toon theme's hard drop; a soft one in a flat theme).
pub fn shadow(y: f32, a: f32) -> BoxShadow {
    let th = t();
    BoxShadow::new(alpha(th.shadow, th.shadow_a * a), Val::ZERO, Val::Px(if th.shadow_blur > 0.0 { th.shadow_y } else { y }), Val::ZERO, Val::Px(th.shadow_blur))
}

/// A small drop under rows and chips (none in a flat theme: it would be noise).
pub fn hard_shadow(y: f32, a: f32) -> BoxShadow {
    let th = t();
    if th.shadow_blur > 0.0 {
        BoxShadow::new(Color::NONE, Val::ZERO, Val::ZERO, Val::ZERO, Val::ZERO)
    } else {
        BoxShadow::new(alpha(th.shadow, a), Val::ZERO, Val::Px(y), Val::ZERO, Val::ZERO)
    }
}

/// A title's face at a designed size: Marcellus in an ornamented theme, else the body face.
pub fn tface(f: &Fonts, size: f32) -> TextFont {
    let th = t();
    if th.serif_titles {
        f.title(size)
    } else {
        f.body((size * th.title_scale).round(), 700)
    }
}

/// A title on the frame.
pub fn title(f: &Fonts, size: f32) -> impl Bundle {
    let th = t();
    let shadow = if th.serif_titles { bevy::ui::widget::TextShadow { offset: Vec2::new(0.0, 2.0), color: th.edge } } else { bevy::ui::widget::TextShadow { offset: Vec2::ZERO, color: Color::NONE } };
    (tface(f, size), TextColor(th.title), shadow)
}

/// Text on the frame that is not a title.
pub fn on_wood(f: &Fonts, size: f32, weight: u16) -> impl Bundle {
    (f.body(size, weight.min(800)), TextColor(t().on_panel))
}

/// Text on surfaces: one face, two weights (600 for reading, 800 for what you act on).
pub fn ink(f: &Fonts, size: f32, weight: u16) -> impl Bundle {
    let w = if t().serif_titles { weight } else if weight >= 700 { 700 } else { 500 };
    (f.body(size, w), TextColor(t().text))
}

/// A key chip ("I", "Esc", "LMB"). `extra` goes on its text.
pub fn chip(p: &mut ChildSpawnerCommands, f: &Fonts, text: &str, extra: impl Bundle) -> Entity {
    let th = t();
    let mut e = Entity::PLACEHOLDER;
    p.spawn((
        Node { padding: UiRect::axes(Val::Px(5.0), Val::Px(0.0)), min_width: Val::Px(22.0), height: Val::Px(20.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: b(2.0), border_radius: r(6.0), flex_shrink: 0.0, ..default() },
        BackgroundColor(if th.serif_titles { th.surface } else { th.surface_lo }),
        BorderColor::all(if th.serif_titles { th.edge } else { Color::NONE }),
        hard_shadow(2.0, 0.5),
        Pickable::IGNORE,
    ))
    .with_children(|c| {
        e = c.spawn((Text::new(text), f.body(11.0, if th.serif_titles { 900 } else { 700 }), TextColor(if th.serif_titles { th.text } else { th.muted }), Pickable::IGNORE, extra)).id();
    });
    e
}

/// A chip holding a glyph instead of a letter (⌥, a mouse button).
pub fn glyph_chip(p: &mut ChildSpawnerCommands, icons: &Icons, g: Glyph, extra: impl Bundle) -> Entity {
    let th = t();
    let mut e = Entity::PLACEHOLDER;
    p.spawn((
        Node { width: Val::Px(26.0), height: Val::Px(20.0), justify_content: JustifyContent::Center, align_items: AlignItems::Center, border: b(2.0), border_radius: r(6.0), flex_shrink: 0.0, ..default() },
        BackgroundColor(th.surface),
        BorderColor::all(th.edge),
        hard_shadow(2.0, 0.5),
        Pickable::IGNORE,
    ))
    .with_children(|c| {
        e = c.spawn((Node { width: Val::Px(13.0), height: Val::Px(13.0), ..default() }, ImageNode::new(icons.get(g)).with_color(th.text), Pickable::IGNORE, extra)).id();
    });
    e
}

/// A glyph at a size and tint.
pub fn icon(icons: &Icons, g: Glyph, size: f32, color: Color) -> impl Bundle {
    (Node { width: Val::Px(size), height: Val::Px(size), flex_shrink: 0.0, ..default() }, ImageNode::new(icons.get(g)).with_color(color), Pickable::IGNORE)
}

/// The colour of a glyph on surfaces (warm brass in Walnut, the muted text colour elsewhere).
pub fn glyph_tint() -> Color {
    if t().serif_titles {
        hex(0xb97b35)
    } else {
        t().muted
    }
}

/// A long label shortened to fit a title (no wrapping in title bars).
pub fn fit(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        return s.to_string();
    }
    let cut: String = s.chars().take(max.saturating_sub(1)).collect();
    format!("{}…", cut.trim_end())
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

    /// Glass over the brightest world measured behind a window by day (glass-1's day stills on
    /// Brackenford's square: pale paving, 95th percentile linear luminance 0.68–0.74), blended
    /// in linear light as Bevy's UI is (the same stills' strips match that model): text keeps
    /// WCAG AA (4.5) on the panel's mean, muted text 3.0, and a row's band only adds to it.
    #[test]
    fn glass_keeps_contrast_over_a_bright_world() {
        use super::*;
        let th = Theme::of(Name::Glass);
        let world = 0.70;
        let over = |c: Color, below: f32| luminance(c.with_alpha(1.0)) * c.alpha() + below * (1.0 - c.alpha());
        let ratio = |a: f32, b: f32| (a.max(b) + 0.05) / (a.min(b) + 0.05);
        let mid = th.panel.0.mix(&th.panel.1, 0.5);
        let panel = over(mid, world);
        let band = over(th.surface, panel);
        assert!(ratio(luminance(th.text), panel) >= 4.5, "text on glass {:.2}", ratio(luminance(th.text), panel));
        assert!(ratio(luminance(th.muted), panel) >= 3.0, "muted on glass {:.2}", ratio(luminance(th.muted), panel));
        assert!(ratio(luminance(th.text), band) >= ratio(luminance(th.text), panel));
        // And it is glass: some of the world shows through every part of a panel.
        assert!(th.panel.0.alpha() < 0.9 && th.panel.1.alpha() < 0.9);
    }

    #[test]
    fn themes_cycle_and_parse_and_long_titles_fit() {
        use super::Name;
        assert_eq!(Name::default(), Name::Glass);
        assert_eq!(Name::Glass.next(), Name::Clear);
        assert_eq!(Name::Walnut.next(), Name::Glass);
        assert_eq!(Name::parse("glass"), Some(Name::Glass));
        assert_eq!(Name::parse("Night"), Some(Name::Night));
        assert_eq!(super::fit("A stranger in green and dark grey", 24), "A stranger in green and…");
        assert_eq!(super::fit("Mercy", 24), "Mercy");
    }
}
