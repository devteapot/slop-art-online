//! The UI's look: colours, type and the panel recipe, in one place.
//!
//! Between minimal anime (Genshin, Blue Protocol) and classic MMO (docs/GAME_BRIEF.md,
//! 2026-11-09): soft, rounded ink panels with a thin light edge, saturated bars with a light
//! top, warm gold for the classic accents, and a cream speech bubble that matches the toon look.
//!
//! Type: Nunito (rounded sans, variable weight) for everything you read; Marcellus (a flared
//! roman) for the few titles. Both are SIL Open Font License 1.1, in `assets/ui/fonts/`.

use bevy::prelude::*;
use bevy::text::{FontSize, FontSource, FontVariationTag, FontVariations, FontWeight};

pub const INK: Color = Color::srgba(0.07, 0.085, 0.13, 0.74);
pub const INK_SOLID: Color = Color::srgba(0.055, 0.065, 0.10, 0.92);
pub const EDGE: Color = Color::srgba(1.0, 1.0, 1.0, 0.13);
pub const EDGE_STRONG: Color = Color::srgba(1.0, 1.0, 1.0, 0.24);
pub const TEXT: Color = Color::srgb(0.96, 0.95, 0.92);
pub const MUTED: Color = Color::srgba(0.86, 0.87, 0.92, 0.66);
pub const GOLD: Color = Color::srgb(0.94, 0.80, 0.50);
pub const GOLD_DIM: Color = Color::srgba(0.94, 0.80, 0.50, 0.45);
pub const HOSTILE: Color = Color::srgb(1.0, 0.43, 0.40);
pub const FRIENDLY: Color = Color::srgb(0.55, 0.88, 0.62);
pub const TALK: Color = Color::srgb(0.62, 0.83, 1.0);
pub const TRACK: Color = Color::srgba(0.02, 0.03, 0.06, 0.62);
pub const HP_LO: Color = Color::srgb(0.80, 0.18, 0.24);
pub const HP_HI: Color = Color::srgb(1.0, 0.45, 0.40);
pub const EN_LO: Color = Color::srgb(0.15, 0.62, 0.70);
pub const EN_HI: Color = Color::srgb(0.45, 0.88, 0.86);
pub const BUBBLE: Color = Color::srgba(0.99, 0.97, 0.92, 0.96);
pub const BUBBLE_TEXT: Color = Color::srgb(0.17, 0.15, 0.21);
pub const SHADOW: Color = Color::srgba(0.0, 0.0, 0.03, 0.42);

/// Colour family of a skill: (light, dark) for its slot gradient and glyph tint.
pub fn school(icon: super::model::SkillIcon) -> (Color, Color) {
    use super::model::SkillIcon::*;
    match icon {
        Sword => (Color::srgb(0.62, 0.72, 0.90), Color::srgb(0.16, 0.20, 0.33)),
        Bow => (Color::srgb(0.64, 0.86, 0.52), Color::srgb(0.14, 0.27, 0.17)),
        Fire => (Color::srgb(1.0, 0.66, 0.36), Color::srgb(0.40, 0.13, 0.08)),
        Shield => (Color::srgb(0.96, 0.84, 0.56), Color::srgb(0.32, 0.24, 0.12)),
        Dodge => (Color::srgb(0.56, 0.90, 0.92), Color::srgb(0.10, 0.26, 0.31)),
        Heal => (Color::srgb(0.72, 0.96, 0.70), Color::srgb(0.13, 0.30, 0.20)),
        Empty => (Color::srgba(1.0, 1.0, 1.0, 0.35), Color::srgba(0.06, 0.07, 0.11, 0.6)),
    }
}

pub fn tone(t: super::model::Tone) -> Color {
    use super::model::Tone::*;
    match t {
        Good => FRIENDLY,
        Warn => Color::srgb(1.0, 0.78, 0.38),
        Bad => HOSTILE,
    }
}

pub fn stance(s: super::model::Stance) -> Color {
    use super::model::Stance::*;
    match s {
        Hostile => HOSTILE,
        Neutral => GOLD,
    }
}

pub fn with_alpha(c: Color, a: f32) -> Color {
    let mut c = c;
    c.set_alpha(c.alpha() * a);
    c
}

#[derive(Resource, Clone)]
pub struct Fonts {
    pub body: Handle<Font>,
    pub title: Handle<Font>,
}

pub fn load_fonts(mut commands: Commands, assets: Res<AssetServer>) {
    commands.insert_resource(Fonts { body: assets.load("ui/fonts/Nunito-Variable.ttf"), title: assets.load("ui/fonts/Marcellus-Regular.ttf") });
}

impl Fonts {
    /// Body text at a size (logical px at 1080p) and weight (400 regular … 800 extra bold).
    pub fn body(&self, size: f32, weight: u16) -> TextFont {
        TextFont {
            font: FontSource::Handle(self.body.clone()),
            font_size: FontSize::Px(size),
            weight: FontWeight(weight),
            // Nunito is one variable file; set its weight axis as well as the requested weight.
            font_variations: FontVariations::builder().set(FontVariationTag::WEIGHT, weight as f32).build(),
            ..default()
        }
    }

    pub fn title(&self, size: f32) -> TextFont {
        TextFont { font: FontSource::Handle(self.title.clone()), font_size: FontSize::Px(size), ..default() }
    }
}

/// A soft drop shadow under text over the world.
pub fn text_shadow() -> bevy::ui::widget::TextShadow {
    bevy::ui::widget::TextShadow { offset: Vec2::new(0.0, 1.5), color: Color::srgba(0.0, 0.0, 0.04, 0.85) }
}

/// The panel recipe: rounded ink with a thin light edge and a soft shadow.
pub fn panel(radius: f32) -> (BackgroundColor, BorderColor, BoxShadow) {
    let _ = radius;
    (
        BackgroundColor(INK),
        BorderColor::all(EDGE),
        BoxShadow::new(SHADOW, Val::ZERO, Val::Px(3.0), Val::ZERO, Val::Px(14.0)),
    )
}
