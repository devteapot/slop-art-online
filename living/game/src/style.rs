//! The shared look: one toon material (`toon.wesl`) used by everything drawn, outlines on
//! characters and objects, and the style profile that tunes both (F2). Zones will differ by
//! their assets and, gently, by light, fog and grading; never by how things are drawn.

use bevy::asset::embedded_asset;
use bevy::pbr::{ExtendedMaterial, MaterialExtension};
use bevy::prelude::*;
use bevy::render::render_resource::AsBindGroup;
use bevy::shader::ShaderRef;
use bevy_mod_outline::{OutlineStencil, OutlineVolume};

pub type Toon = ExtendedMaterial<StandardMaterial, ToonExt>;

#[derive(Asset, AsBindGroup, Reflect, Debug, Clone, Default)]
pub struct ToonExt {
    #[uniform(100)]
    pub params: ToonParams,
}

#[derive(Clone, Copy, Debug, Default, Reflect, bevy::render::render_resource::ShaderType)]
pub struct ToonParams {
    pub shadow: Vec4,
    pub rim: Vec4,
    pub band: Vec4,
    pub extra: Vec4,
    pub shade: Vec4,
    /// Recolouring of the texture (characters.rs): x hue, y saturation, z value, w mode (0 none,
    /// 1 shift the hue, 2 tint a grey texture, 3 per instance: the target colour is in each
    /// mesh's `MeshTag` and the shader derives the rest).
    pub recolor: Vec4,
    /// x: the texture's mean hue, y: how much of the texture's hue variation stays (mode 1);
    /// mode 3 also z and w: the texture's mean saturation and value.
    pub recolor_from: Vec4,
}

impl MaterialExtension for ToonExt {
    fn fragment_shader() -> ShaderRef {
        "embedded://living_game/toon.wesl".into()
    }
}

/// The style profile: every parameter of the shared look.
#[derive(Resource, Clone, Copy, Debug, PartialEq)]
pub struct Style {
    pub enabled: bool,
    /// Bloom strength (HDR scenes): how far bright and glowing things halo.
    pub bloom: f32,
    /// Shadows are the lit colour with its hue moved toward `shadow_hue` (0..1) by
    /// `hue_shift`, saturation times `shadow_saturation`, darkened by `shadow_depth`, then
    /// multiplied by `shadow_tint`.
    pub shadow_hue: f32,
    pub hue_shift: f32,
    pub shadow_saturation: f32,
    pub shadow_tint: [f32; 3],
    pub shadow_depth: f32,
    /// N·L where light turns to shadow, and how soft the edge is.
    pub threshold: f32,
    pub softness: f32,
    /// How much the band edge wanders like a brush stroke, and the stroke size (m).
    pub brush: f32,
    pub brush_size: f32,
    /// Extra darkening where surfaces turn fully away from the sun (1 = none).
    pub core: f32,
    pub ambient: f32,
    /// Overall brightness of sunlit surfaces (1 = physical).
    pub exposure: f32,
    pub rim_color: [f32; 3],
    pub rim: f32,
    pub rim_width: f32,
    pub outlines: bool,
    pub outline_color: [f32; 3],
    /// Outline width in pixels for characters and for objects.
    pub outline_people: f32,
    pub outline_things: f32,
    /// Finishing pass (`edges.wesl`): lines from depth and normal edges, drawn outside
    /// silhouettes and fading with distance; a screen-space rim; a film gradient.
    pub edges: bool,
    pub line_color: [f32; 3],
    pub line_strength: f32,
    pub depth_threshold: f32,
    pub normal_threshold: f32,
    pub line_width: f32,
    pub line_fade: [f32; 2],
    pub screen_rim: f32,
    pub screen_rim_width: f32,
    pub grade_color: [f32; 3],
    pub grade: f32,
    pub saturation: f32,
}

impl Default for Style {
    fn default() -> Self {
        Self {
            enabled: true,
            bloom: 0.12,
            // Blue Protocol-like defaults: a hard step with about 70% lit, cool hue-shifted
            // shadows that keep their saturation.
            shadow_hue: 0.72,
            hue_shift: 0.18,
            shadow_saturation: 1.1,
            shadow_tint: [1.0, 1.0, 1.0],
            shadow_depth: 0.42,
            threshold: -0.2,
            softness: 0.02,
            brush: 0.12,
            brush_size: 1.6,
            core: 0.82,
            ambient: 0.0,
            exposure: 0.82,
            rim_color: [1.0, 0.95, 0.85],
            rim: 0.35,
            rim_width: 3.5,
            outlines: true,
            outline_color: [0.12, 0.09, 0.1],
            outline_people: 2.0,
            outline_things: 1.2,
            edges: true,
            line_color: [0.35, 0.28, 0.32],
            line_strength: 0.85,
            depth_threshold: 0.06,
            normal_threshold: 0.55,
            line_width: 1.0,
            line_fade: [25.0, 70.0],
            screen_rim: 0.18,
            screen_rim_width: 3.0,
            grade_color: [1.0, 0.92, 0.8],
            grade: 0.22,
            saturation: 1.08,
        }
    }
}

impl Style {
    fn params(&self) -> ToonParams {
        let [r, g, b] = self.shadow_tint;
        let [rr, rg, rb] = self.rim_color;
        ToonParams {
            shadow: Vec4::new(r, g, b, self.shadow_depth),
            rim: Vec4::new(rr, rg, rb, self.rim),
            band: Vec4::new(self.threshold, self.softness.max(0.001), self.brush, self.rim_width),
            extra: Vec4::new(1.0 / self.brush_size.max(0.05), self.ambient, self.core, self.exposure),
            shade: Vec4::new(self.shadow_hue, self.hue_shift, self.shadow_saturation, 0.0),
            recolor: Vec4::ZERO,
            recolor_from: Vec4::ZERO,
        }
    }

    pub fn toon(&self, base: StandardMaterial) -> Toon {
        Toon { base, extension: ToonExt { params: self.params() } }
    }

    /// A toon material for skin: lighter, warmer shadows.
    pub fn skin(&self, base: StandardMaterial) -> Toon {
        let mut t = self.toon(base);
        t.extension.params.shade.w = 1.0;
        t
    }
}

/// What kind of outline an entity gets.
#[derive(Component, Clone, Copy)]
pub enum Outlined {
    Person,
    Thing,
}

pub fn outline(kind: Outlined, style: &Style) -> (Outlined, OutlineVolume, OutlineStencil) {
    let [r, g, b] = style.outline_color;
    let width = match kind {
        Outlined::Person => style.outline_people,
        Outlined::Thing => style.outline_things,
    };
    (kind, OutlineVolume { visible: style.outlines, width, colour: Color::srgb(r, g, b) }, OutlineStencil { offset: 0.0, ..default() })
}

pub struct StylePlugin;

impl Plugin for StylePlugin {
    fn build(&self, app: &mut App) {
        embedded_asset!(app, "toon.wesl");
        app.add_plugins(MaterialPlugin::<Toon>::default())
            .add_plugins(bevy_mod_outline::OutlinePlugin::EXTRUDE_VERTEX)
            .init_resource::<Style>()
            .add_systems(Update, (apply, fog_outlines).chain());
    }
}

/// Push a changed style to every toon material and outline.
/// Outlines draw on their own: they ignore fog and a hidden parent (a building the cut-away
/// hides), so they would remain as bare line drawings. Show one only where its object shows and
/// the fog has not mostly swallowed it.
fn fog_outlines(style: Res<Style>, cams: Query<(&GlobalTransform, &DistanceFog), With<Camera3d>>, mut outlines: Query<(&mut OutlineVolume, &GlobalTransform, Option<&InheritedVisibility>), With<Outlined>>) {
    let Ok((cam, fog)) = cams.single() else { return };
    let FogFalloff::Linear { start, end } = fog.falloff else { return };
    let cutoff = start + (end - start) * 0.55;
    let eye = cam.translation();
    let on = style.outlines && style.enabled;
    for (mut o, g, shown) in &mut outlines {
        let want = on && shown.is_none_or(|v| v.get()) && g.translation().distance(eye) < cutoff;
        if o.visible != want {
            o.visible = want;
        }
    }
}

fn apply(style: Res<Style>, mut toons: ResMut<Assets<Toon>>, mut outlines: Query<(&Outlined, &mut OutlineVolume)>) {
    if !style.is_changed() {
        return;
    }
    let p = if style.enabled {
        style.params()
    } else {
        // Plain look: no bands, no tint, no rim (for comparison).
        ToonParams { shadow: Vec4::new(1.0, 1.0, 1.0, 0.45), rim: Vec4::ZERO, band: Vec4::new(-0.2, 0.6, 0.0, 1.0), extra: Vec4::new(1.0, 0.0, 1.0, 1.0), shade: Vec4::new(0.0, 0.0, 1.0, 0.0), recolor: Vec4::ZERO, recolor_from: Vec4::ZERO }
    };
    for (_, m) in toons.iter_mut() {
        // Keep each material's own flags (skin) and recolouring.
        let old = m.extension.params;
        m.extension.params = p;
        m.extension.params.shade.w = old.shade.w;
        m.extension.params.recolor = old.recolor;
        m.extension.params.recolor_from = old.recolor_from;
    }
    let [r, g, b] = style.outline_color;
    for (kind, mut o) in &mut outlines {
        o.visible = style.outlines && style.enabled;
        o.colour = Color::srgb(r, g, b);
        o.width = match kind {
            Outlined::Person => style.outline_people,
            Outlined::Thing => style.outline_things,
        };
    }
}
