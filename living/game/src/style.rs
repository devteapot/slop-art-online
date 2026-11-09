//! The shared look: one toon material (`toon.wesl`) used by everything drawn, outlines on
//! characters and objects, and the style profile that tunes both (F2). Zones will differ by
//! their assets and, gently, by light, fog and grading; never by how things are drawn.
//!
//! The lighting lives in `toon_light.wesl`, a shader module that `toon.wesl` (models) and
//! `terrain.wesl` (the ground) both compose, with the toon parameters and the wind sway that
//! the vertex shaders share.
//!
//! **Painted detail on scenery** ([`Surface`]): generated models carry, in their vertex colours'
//! alpha, which painted surface each part is (bark, leaves, plaster, brick, roof tiles…; tagged by
//! `living/tools/blender/nature.py` and `buildings.py` from material names and palette entries).
//! One texture array of those surfaces ([`DetailLayers`], `paint.py --set material`) is bound on
//! every scenery material, and the per-surface tile size, strength and mapping are in the
//! parameters, so scenery keeps sharing its few materials and batches. Detail is grey round 1, so
//! vertex colours keep every palette; it fades out with distance; characters get none.
//! `LIVING_GAME_PERF=nodetail` turns it off for A/B.

use bevy::asset::embedded_asset;
use bevy::pbr::{ExtendedMaterial, MaterialExtension};
use bevy::prelude::*;
use bevy::render::render_resource::AsBindGroup;
use bevy::shader::ShaderRef;
use bevy_mod_outline::{OutlineMode, OutlineStencil, OutlineVolume};

pub type Toon = ExtendedMaterial<StandardMaterial, ToonExt>;

#[derive(Asset, AsBindGroup, Reflect, Debug, Clone, Default)]
pub struct ToonExt {
    #[uniform(100)]
    pub params: ToonParams,
    /// A face's shadow map (`living/tools/face_normals.py`): per texel, the light angle up to
    /// which it stays lit, for light from the face's right (R) and left (G). Only face skin
    /// materials have one; it is one per base file, so characters still share materials.
    #[texture(101)]
    #[sampler(102)]
    pub face: Option<Handle<Image>>,
    /// The painted surfaces ([`DetailLayers`]) on generated scenery; none elsewhere.
    #[texture(103, dimension = "2d_array")]
    #[sampler(104)]
    pub detail: Option<Handle<Image>>,
}

/// The painted surfaces of models, in the order of `living/tools/textures/surfaces.py` (layer k
/// of `material.png`; the generators tag parts with surface k as vertex alpha (k + 0.5) / 32).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Surface {
    Bark,
    Leaves,
    /// Beams and posts.
    Wood,
    Planks,
    Plaster,
    /// Ashlar masonry.
    Stone,
    /// Natural rock (boulders, cave rock).
    Boulder,
    Brick,
    Shingles,
    /// Clay barrel tiles.
    Tiles,
    Thatch,
    Metal,
    /// Copper and brass.
    Copper,
    Concrete,
    /// Awnings.
    Cloth,
    Glass,
    /// Moulded plastic, painted trim, blinds and cables.
    Plastic,
    /// Packed earth (burrows and banks).
    Earth,
}

pub const SURFACES: usize = 18;

/// How a surface's texture is laid on a model.
#[derive(Clone, Copy)]
enum Mapping {
    /// From the three axes, blended by the shading normal: organic, smooth shapes.
    Triplanar,
    /// Flat on each face, level across it and down its slope: built surfaces.
    Planar,
}

impl Surface {
    pub const ALL: [Surface; SURFACES] = [
        Self::Bark,
        Self::Leaves,
        Self::Wood,
        Self::Planks,
        Self::Plaster,
        Self::Stone,
        Self::Boulder,
        Self::Brick,
        Self::Shingles,
        Self::Tiles,
        Self::Thatch,
        Self::Metal,
        Self::Copper,
        Self::Concrete,
        Self::Cloth,
        Self::Glass,
        Self::Plastic,
        Self::Earth,
    ];

    /// Its name in `material.txt` (surfaces.py).
    pub fn name(self) -> &'static str {
        match self {
            Self::Bark => "bark",
            Self::Leaves => "leaves",
            Self::Wood => "wood",
            Self::Planks => "planks",
            Self::Plaster => "plaster",
            Self::Stone => "stone",
            Self::Boulder => "boulder",
            Self::Brick => "brick",
            Self::Shingles => "shingles",
            Self::Tiles => "tiles",
            Self::Thatch => "thatch",
            Self::Metal => "metal",
            Self::Copper => "copper",
            Self::Concrete => "concrete",
            Self::Cloth => "cloth",
            Self::Glass => "glass",
            Self::Plastic => "plastic",
            Self::Earth => "earth",
        }
    }

    /// Tile size (m), strength and mapping. Slate and clay roofs are off (strength 0): their
    /// courses are modelled, and every painted version (rows, streaks, mottle) lost the blind A/B
    /// of 2026-11-09 as grain or soot at game distances.
    fn tile(self) -> (f32, f32, Mapping) {
        use Mapping::*;
        match self {
            Self::Bark => (1.6, 1.0, Triplanar),
            Self::Leaves => (4.0, 1.0, Triplanar),
            Self::Wood => (1.2, 1.0, Planar),
            Self::Planks => (1.8, 1.0, Planar),
            Self::Plaster => (2.5, 1.0, Planar),
            Self::Stone => (2.5, 1.0, Planar),
            Self::Boulder => (3.5, 1.0, Planar),
            Self::Brick => (1.6, 1.0, Planar),
            Self::Shingles => (2.0, 0.0, Planar),
            Self::Tiles => (2.4, 0.0, Planar),
            Self::Thatch => (2.0, 1.0, Planar),
            Self::Metal => (2.0, 1.0, Planar),
            Self::Copper => (2.0, 1.0, Planar),
            Self::Concrete => (3.0, 1.0, Planar),
            Self::Cloth => (1.5, 1.0, Planar),
            Self::Glass => (1.5, 1.0, Planar),
            Self::Plastic => (2.0, 1.0, Planar),
            Self::Earth => (2.5, 1.0, Triplanar),
        }
    }
}

/// The per-surface table. `LIVING_GAME_PERF=detailonly=bark+leaves` keeps detail on only the
/// surfaces named (for comparing one family at a time).
fn surface_layers() -> [Vec4; SURFACES] {
    let only: Option<Vec<String>> = std::env::var("LIVING_GAME_PERF").ok().and_then(|v| v.split(',').find_map(|f| f.trim().strip_prefix("detailonly=").map(|l| l.split('+').map(str::to_string).collect())));
    Surface::ALL.map(|s| {
        let (tile, strength, mapping) = s.tile();
        let on = only.as_ref().is_none_or(|o| o.iter().any(|n| n == s.name()));
        Vec4::new(1.0 / tile, if on { strength } else { 0.0 }, matches!(mapping, Mapping::Planar) as u8 as f32, 0.0)
    })
}

/// The painted surfaces' texture array, shared by every scenery material.
#[derive(Resource, Clone)]
pub struct DetailLayers(pub Handle<Image>);

fn load_detail(mut commands: Commands, mut images: ResMut<Assets<Image>>) {
    commands.insert_resource(DetailLayers(images.add(crate::terrain::load_array("textures/material", &Surface::ALL.map(Surface::name)))));
}

/// Give a scenery material the painted surfaces its vertex colours name.
pub fn with_detail(toon: &mut Toon, layers: &DetailLayers) {
    toon.extension.params.detail.x = 1.0;
    toon.extension.detail = Some(layers.0.clone());
}

/// What a toon material shades (`ToonParams::shade.w`; `toon.wesl` branches on it).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Kind {
    Plain = 0,
    /// Lighter, warmer shadows.
    Skin = 1,
    /// A face's skin with a shadow map: its shadow edge comes from the map and the sun's angle
    /// round the head, not from N·L.
    Face = 2,
    /// Eyes, brows, lashes and mouth: hardly shaded, as in anime.
    FacePart = 3,
    /// Hair: an angel-ring highlight, a rim, and shadows toward the hair's own colour.
    Hair = 4,
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
    /// Weather (weather.rs): x wind strength (sways meshes tagged as plants), y wetness; z painted
    /// detail strength (0 off), w how far detail's relief moves the sun's band edge.
    pub atmo: Vec4,
    /// Faces: x shadow-edge softness (fraction of 180°), y how dark face shadows get relative
    /// to other skin, z how far face parts (eyes, mouth) darken in shadow, w face rim strength.
    pub face: Vec4,
    /// Hair: x angel-ring strength, y ring width, z ring position (tangent shift), w rim
    /// strength.
    pub hair: Vec4,
    /// Painted detail: x 1 on scenery whose vertex colours name surfaces ([`with_detail`]), z
    /// full detail until (m), w none from (m). The style sets z and w; x is the material's own.
    pub detail: Vec4,
    /// Per [`Surface`]: x 1 / tile size (1/m), y strength, z mapping (0 triplanar, 1 planar).
    pub layers: [Vec4; SURFACES],
}

impl MaterialExtension for ToonExt {
    fn fragment_shader() -> ShaderRef {
        "embedded://living_game/toon.wesl".into()
    }

    // Wind sways plants in every pass alike (main, depth/normal prepass and shadows), so their
    // lines, depth test and shadows stay with them.
    fn vertex_shader() -> ShaderRef {
        "embedded://living_game/toon_vertex.wesl".into()
    }

    fn prepass_vertex_shader() -> ShaderRef {
        "embedded://living_game/toon_prepass.wesl".into()
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
    /// Weather, written by weather.rs in coarse steps (each change re-prepares every toon
    /// material): wind strength for swaying plants, and how wet surfaces are.
    pub wind: f32,
    pub wet: f32,
    /// Characters (`Kind`): the face's shadow-edge softness (fraction of 180°), face shadow
    /// depth relative to skin, how far eyes and mouth darken in shadow, and face rim strength.
    pub face_softness: f32,
    pub face_shadow: f32,
    pub face_parts: f32,
    pub face_rim: f32,
    /// Hair's angel ring: strength, width and position (tangent shift, + moves it up the head),
    /// and the hair's rim strength.
    pub hair_ring: f32,
    pub hair_ring_width: f32,
    pub hair_ring_shift: f32,
    pub hair_rim: f32,
    /// Painted detail on scenery: strength (0 off), how far its relief (the painted height) moves
    /// the sun's band edge, and the distances (m) from which it fades and by which it is gone.
    pub detail: f32,
    pub detail_relief: f32,
    pub detail_fade: [f32; 2],
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
            outline_color: [0.17, 0.11, 0.1],
            outline_people: 1.8,
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
            wind: 0.0,
            wet: 0.0,
            face_softness: 0.012,
            face_shadow: 1.25,
            face_parts: 0.25,
            face_rim: 0.15,
            hair_ring: 0.7,
            hair_ring_width: 0.05,
            hair_ring_shift: 0.35,
            hair_rim: 0.2,
            detail: 1.0,
            detail_relief: 0.0,
            detail_fade: [20.0, 55.0],
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
            atmo: Vec4::new(self.wind, self.wet, if crate::perf::has("nodetail") { 0.0 } else { self.detail }, self.detail_relief),
            face: Vec4::new(self.face_softness.max(0.001), self.face_shadow, self.face_parts, self.face_rim),
            hair: Vec4::new(self.hair_ring, self.hair_ring_width.max(0.01), self.hair_ring_shift, self.hair_rim),
            detail: Vec4::new(0.0, 0.0, self.detail_fade[0], self.detail_fade[1].max(self.detail_fade[0] + 1.0)),
            layers: surface_layers(),
        }
    }

    pub fn toon(&self, base: StandardMaterial) -> Toon {
        self.kind(base, Kind::Plain, None)
    }

    /// A toon material for one kind of surface; a `Face` takes its shadow map.
    pub fn kind(&self, base: StandardMaterial, kind: Kind, face: Option<Handle<Image>>) -> Toon {
        let mut params = self.params();
        params.shade.w = kind as u8 as f32;
        Toon { base, extension: ToonExt { params, face, detail: None } }
    }
}

/// What kind of outline an entity gets.
#[derive(Component, Clone, Copy)]
pub enum Outlined {
    Person,
    Thing,
}

/// The stencil of a scenery model (buildings, walls, trees, fences, props): written at its real
/// depth, so it hides exactly the parts of character outlines behind it. bevy_mod_outline's
/// default (flat) mode writes a stencil at its model's origin instead, so a wall, a canopy or a
/// house corner hid an outline only where the model's origin was nearer than the character's.
/// Ground keeps the flat stencil ([`ground_stencil`]).
pub fn stencil() -> (OutlineStencil, OutlineMode) {
    (OutlineStencil::default(), OutlineMode::ExtrudeReal)
}

/// The ground's stencil: flat, as before. Character outlines are flat planes through their feet,
/// so a ground stencil at its real depth would cut the line under every sole (the ground just in
/// front of the feet is nearer than that plane), and the library's plane offset can't lead them
/// toward the camera for a turned model. So the ground hides no outline; a hill between you and
/// a character is rare at the game camera's distances.
pub fn ground_stencil() -> OutlineStencil {
    OutlineStencil::default()
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
        bevy::shader::load_shader_library!(app, "toon_light.wesl");
        embedded_asset!(app, "toon.wesl");
        embedded_asset!(app, "toon_vertex.wesl");
        embedded_asset!(app, "toon_prepass.wesl");
        app.add_plugins(MaterialPlugin::<Toon>::default())
            .add_plugins(bevy_mod_outline::OutlinePlugin::EXTRUDE_VERTEX)
            .init_resource::<Style>()
            .add_systems(Startup, load_detail)
            .add_systems(Update, (apply, fog_outlines).chain());
    }
}

/// Push a changed style to every toon material and outline.
/// Outlines draw on their own: they ignore fog and a hidden parent (a building the cut-away
/// hides), so they would remain as bare line drawings. Show one only where its object shows and
/// the fog has not mostly swallowed it.
/// Characters' lines also thin with distance, as drawn anime lines do: full width within
/// `PERSON_NEAR` metres, `PERSON_THIN` of it from `PERSON_FAR` on (a fixed pixel width made
/// distant people look inked heavier than near ones). Widths change in steps, so a crowd
/// rewrites its outlines only when someone crosses one.
const PERSON_NEAR: f32 = 8.0;
const PERSON_FAR: f32 = 30.0;
const PERSON_THIN: f32 = 0.6;

fn person_width(style: &Style, distance: f32) -> f32 {
    let t = ((distance - PERSON_NEAR) / (PERSON_FAR - PERSON_NEAR)).clamp(0.0, 1.0);
    let w = style.outline_people * (1.0 - (1.0 - PERSON_THIN) * t);
    (w * 8.0).round() / 8.0
}

fn fog_outlines(style: Res<Style>, cams: Query<(&GlobalTransform, &DistanceFog), With<Camera3d>>, mut outlines: Query<(&Outlined, &mut OutlineVolume, &GlobalTransform, Option<&InheritedVisibility>)>) {
    let Ok((cam, fog)) = cams.single() else { return };
    let FogFalloff::Linear { start, end } = fog.falloff else { return };
    let cutoff = start + (end - start) * 0.55;
    let eye = cam.translation();
    let on = style.outlines && style.enabled;
    for (kind, mut o, g, shown) in &mut outlines {
        let d = g.translation().distance(eye);
        let want = on && shown.is_none_or(|v| v.get()) && d < cutoff;
        if o.visible != want {
            o.visible = want;
        }
        if want && matches!(kind, Outlined::Person) {
            let w = person_width(&style, d);
            if o.width != w {
                o.width = w;
            }
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
        // Plain look: no bands, no tint, no rim, no painted detail (for comparison).
        ToonParams { shadow: Vec4::new(1.0, 1.0, 1.0, 0.45), rim: Vec4::ZERO, band: Vec4::new(-0.2, 0.6, 0.0, 1.0), extra: Vec4::new(1.0, 0.0, 1.0, 1.0), shade: Vec4::new(0.0, 0.0, 1.0, 0.0), recolor: Vec4::ZERO, recolor_from: Vec4::ZERO, atmo: Vec4::new(style.wind, style.wet, 0.0, 0.0), face: Vec4::new(0.3, 1.0, 1.0, 0.0), hair: Vec4::new(0.0, 0.1, 0.0, 0.0), ..style.params() }
    };
    for (_, m) in toons.iter_mut() {
        // Keep each material's own kind (skin, face, hair), recolouring and detail.
        let old = m.extension.params;
        m.extension.params = p;
        m.extension.params.shade.w = old.shade.w;
        m.extension.params.recolor = old.recolor;
        m.extension.params.recolor_from = old.recolor_from;
        m.extension.params.detail.x = old.detail.x;
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
