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
use bevy::mesh::MeshVertexBufferLayoutRef;
use bevy::pbr::{ExtendedMaterial, MaterialExtension, MaterialExtensionKey, MaterialExtensionPipeline};
use bevy::prelude::*;
use bevy::render::render_resource::{AsBindGroup, RenderPipelineDescriptor, SpecializedMeshPipelineError};
use bevy::shader::ShaderRef;
use bevy_mod_outline::{OutlineMode, OutlineStencil, OutlineVolume};

pub type Toon = ExtendedMaterial<StandardMaterial, ToonExt>;

#[derive(Asset, AsBindGroup, Reflect, Debug, Clone, Default)]
#[bind_group_data(ToonKey)]
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
    /// The hair's greying palette (`characters/compose.rs` `HairTints`): the one hair material
    /// composed people share has it; none elsewhere.
    #[texture(105)]
    pub tints: Option<Handle<Image>>,
    /// A hand-made material's ink map (contract v1.2, docs/HANDMADE_INK.md; `handmade.rs`
    /// `InkProfile`): G the distance to the nearest stroke, R its width. Texture only: it is
    /// sampled through binding 102's sampler, so the sampler count stays as it was. None (the
    /// shared fallback, never read) on every material without ink.
    #[texture(106)]
    pub ink: Option<Handle<Image>>,
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
    commands.insert_resource(DetailLayers(images.add(crate::terrain::load_array("textures/material", &Surface::ALL.map(Surface::name), |_| None))));
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
    /// A hand-made file's hair with its own profile (`handmade.rs`, docs/HANDMADE_HAIR.md): two
    /// thresholds, three palette colours, one masked highlight; no rims, ring or core band.
    HandHair = 5,
    /// A layer multiplied over the lit skin under it (blush, freckles; a hand-made file's
    /// `"tint"` slot): its colour is a factor, so it carries the skin's light and shadow.
    Tint = 6,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Reflect, bevy::render::render_resource::ShaderType)]
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
    /// Hair's ring, its shape: x edge softness (0 a hard edge, 1 fading from the band's middle),
    /// y comb teeth (0 none, 1 full), z break-up by the strand picture (0 none, 1 full).
    pub hair_sheen: Vec4,
    /// Where on the head the ring may lie: x how far up a surface must face (N·up where it
    /// starts, full 0.25 above), y from how far it faces the character's forward it fades (gone
    /// 0.3 beyond; 2 never).
    pub hair_place: Vec4,
    /// The ring by height and lock: x the share of locks without it, y how far it moves up or
    /// down a lock (in N·up), z 0 placed by the view, 1 at a height (where N·up is w).
    pub hair_lock: Vec4,
    /// Painted detail: x 1 on scenery whose vertex colours name surfaces ([`with_detail`]), z
    /// full detail until (m), w none from (m). The style sets z and w; x is the material's own.
    pub detail: Vec4,
    /// A hand-made hair profile's palette ([`Kind::HandHair`], `handmade.rs`): shade, mid, light
    /// and highlight as linear rgb; `hand[3].w` 1 when the highlight mask is a texture (bound as
    /// [`ToonExt::face`]), else it comes from the second UVs. The material's own.
    pub hand: [Vec4; 4],
    /// The profile's numbers: x `t1`, y `t2` (N·L), z `edge`, w `highlight_feather`.
    pub hand_bands: Vec4,
    /// A hand-made file's forward in this mesh's own frame (xyz), w 1 when set; else the
    /// character files' −Z (`toon.wesl` `facing`). The material's own.
    pub file: Vec4,
    /// A profile's lock ink (v1.1): rgb the line's linear colour, w `ink_px`.
    pub hand_ink: Vec4,
    /// x `ink_range` (UV), y `ink_fade_px`, z 1 when ink is drawn (an ink field set and the mask
    /// texture has G).
    pub hand_ink_range: Vec4,
    /// A material's general ink (contract v1.2, [`ToonExt::ink`]): rgb the line's linear colour,
    /// w `px` (width "px") or `min_px` (width "uv").
    pub ink: Vec4,
    /// x `range` (UV), y `fade_px`, z the mode (0 none, 1 "px", 2 "px" with taper, 3 "uv", 4 "uv"
    /// through the screen derivatives, `LIVING_GAME_PERF=inkfw`),
    /// w the material's texel density (metres per UV unit; 0 unknown).
    pub ink_shape: Vec4,
    /// A palette material (contract v1.3, `characters/palette.rs`): x 1 when the hair profile's
    /// swatches and ink come from the mesh's palette entry ([`ToonExt::tints`], tag bit 27), y 1
    /// when the general ink's colour does (row 4). The material's own.
    pub palette: Vec4,
    /// Per [`Surface`]: x 1 / tile size (1/m), y strength, z mapping (0 triplanar, 1 planar).
    pub layers: [Vec4; SURFACES],
    /// A seated character's skirted piece (hem-ground, `characters::seat_clamp`): xyz the seat
    /// plane's upward normal, w its offset, a margin up; the vertex shaders keep every vertex
    /// where `dot(xyz, p) >= w` (`toon_light.wesl` `seat_clamp`). Zero (every shared toon): none.
    pub seat: Vec4,
    /// The look-dev light ([`Look::Lookdev`], `toon_light.wesl` `ld_*`): x 1 on, y the character
    /// rim's strength ([`CharRim`]), z the specular's strength, w how much of the classic rim
    /// scenery keeps. All zero in the classic look, which then draws exactly as before.
    pub look: Vec4,
    /// The look-dev light's numbers: x the sky's fill (times the sun's brightness), y the ground's
    /// warm bounce (times the sun), z how dark cloth and scenery shadows get (replaces
    /// `shadow.a`), w skin shadows' saturation.
    pub look_light: Vec4,
    /// x 1 on a character's material (lookdev.rs, compose.rs, outfit.rs: the character rim and
    /// skin-aware light); the material's own.
    pub character: Vec4,
    /// The look-dev ramp: x characters' band threshold (N·L), y their brush breakup's share, z
    /// how much of the sun's colour shadows keep.
    pub look_ramp: Vec4,
}

/// A toon material's pipeline key: whether its shaders are compiled with the look-dev light
/// (`ToonParams::look.x`; the shader def LOOKDEV). The classic look's pipelines compile the shaders
/// exactly as before, so it draws exactly as before.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug, Default)]
pub struct ToonKey {
    pub lookdev: bool,
}

impl From<&ToonExt> for ToonKey {
    fn from(t: &ToonExt) -> Self {
        ToonKey { lookdev: t.params.look.x > 0.5 }
    }
}

/// The look-dev light's shader def on a pipeline's fragment shader (`ToonKey`; terrain.rs too).
pub fn lookdev_def(descriptor: &mut RenderPipelineDescriptor, lookdev: bool) {
    if let (true, Some(f)) = (lookdev, descriptor.fragment.as_mut()) {
        f.shader_defs.push("LOOKDEV".into());
    }
}

impl MaterialExtension for ToonExt {
    fn fragment_shader() -> ShaderRef {
        "embedded://living_game/toon.wesl".into()
    }

    fn specialize(_: &MaterialExtensionPipeline, descriptor: &mut RenderPipelineDescriptor, _: &MeshVertexBufferLayoutRef, key: MaterialExtensionKey<Self>) -> Result<(), SpecializedMeshPipelineError> {
        lookdev_def(descriptor, key.bind_group_data.lookdev);
        Ok(())
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
    /// The smallest step between two parallel faces a crease line marks (m): a slate's lower
    /// edge or a sill is drawn by the model, and its lines beaded and crawled as the view moved,
    /// a pixel or so wide (edges-1, the owner's Cullet walk). 0 marks every crease (the old
    /// rule, `LIVING_GAME_PERF=slivers` for A/B).
    pub crease_step: f32,
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
    /// The ring's shape: its edge's softness (0 hard, 1 fading from the middle), the comb teeth
    /// that break its edge (0 none, 1 full) and how far the strand picture breaks it (0 none, 1
    /// full: light strands carry it, dark ones lose it).
    pub hair_ring_soft: f32,
    pub hair_ring_teeth: f32,
    pub hair_ring_strands: f32,
    /// How far up a surface must face to carry the ring (N·up where it starts, full 0.25
    /// above): 0.2 lets it onto a fringe, which faces forward; about 0.55 keeps it to the crown.
    pub hair_ring_up: f32,
    /// From how far a surface faces the character's forward (N·forward) the ring fades, gone 0.3
    /// beyond: about 0.25 keeps it off a fringe, which faces forward, and on the crown, sides and
    /// back; 2 never fades it.
    pub hair_ring_front: f32,
    /// How fine the comb teeth are across the strands (`uv.x` times this; the strand picture
    /// repeats every 22 cm round a head, so 90 is about 2.4 mm, 30 about 7 mm).
    pub hair_ring_teeth_scale: f32,
    /// Where the ring lies: 0 where the view meets the strands (it slides with the camera), 1 at
    /// a height on the head, where N·up is `hair_ring_at` (char-4's normals lean up with height,
    /// `hair.py` RING_TILT, RING_FROM, so that is one height all round).
    pub hair_ring_level: f32,
    pub hair_ring_at: f32,
    /// Where locks part (each lock's own `_GREY`, a number per lock): the share of locks without
    /// the ring, and how far it moves up or down a lock (in N·up).
    pub hair_lock_drop: f32,
    pub hair_lock_shift: f32,
    /// Placed at a height, the ring needs char-4's hair (its normals lean up with height and its
    /// locks carry `_GREY`); other hair (VRoid bases) keeps the view-placed ring at this width.
    pub hair_ring_width_other: f32,
    /// Painted detail on scenery: strength (0 off), how far its relief (the painted height) moves
    /// the sun's band edge, and the distances (m) from which it fades and by which it is gone.
    pub detail: f32,
    pub detail_relief: f32,
    pub detail_fade: [f32; 2],
    /// The look-dev light ([`Look`], [`CharRim`]; `with_look`). Classic leaves it off.
    pub look: LookParams,
}

/// The look-dev light's values in the style profile (`ToonParams::look`, `look_light`).
#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub struct LookParams {
    pub on: bool,
    /// The character rim (0 off).
    pub char_rim: f32,
    /// Cel-stepped specular, by the material's metallic and roughness (and scenery's painted
    /// metal, copper and glass).
    pub specular: f32,
    /// The share of the classic Fresnel rim scenery and ground keep.
    pub scenery_rim: f32,
    /// The sky's fill from above, as a share of the sun's brightness, in the shadows' hue.
    pub sky: f32,
    /// The ground's warm bounce from below, as a share of the sun.
    pub bounce: f32,
    /// How dark cloth and scenery shadows get (the classic `shadow_depth` is 0.42).
    pub shadow_depth: f32,
    /// Skin shadows' saturation (times the lit skin's).
    pub skin_saturation: f32,
    /// Characters' band threshold (N·L; the classic is -0.2) and their brush breakup's share.
    pub char_threshold: f32,
    pub char_brush: f32,
    /// How much of the sun's colour shadows keep (1 as classic; 0: shadows are lit by the sky
    /// alone, the warm/cool split at dusk).
    pub shadow_sun: f32,
    /// Scenery edge-line multiplier in `post.rs` (0.80 under Look-dev so characters lead; 1.0 in Classic).
    pub scenery_edges: f32,
    /// Character shell-outline weight multiplier (`OutlineWeight::scale`, Look-dev only).
    pub outline_weight: f32,
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
            crease_step: 0.06,
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
            hair_ring: 0.0,
            hair_ring_width: 0.0,
            hair_ring_shift: 0.0,
            hair_rim: 0.2,
            hair_ring_soft: 0.0,
            hair_ring_teeth: 0.0,
            hair_ring_strands: 0.0,
            hair_ring_up: 0.0,
            hair_ring_front: 0.0,
            hair_ring_teeth_scale: 0.0,
            hair_ring_level: 0.0,
            hair_ring_at: 0.0,
            hair_lock_drop: 0.0,
            hair_lock_shift: 0.0,
            hair_ring_width_other: 0.0,
            detail: 1.0,
            detail_relief: 0.0,
            detail_fade: [20.0, 55.0],
            look: LookParams::default(),
        }
        .with_shine(HairShine::default())
    }
}

/// A hair shine: the hair ring's style values under a name (Settings › Play › Hair shine).
pub struct Shine {
    pub name: &'static str,
    pub label: &'static str,
    /// The ring's values in [`RING_KEYS`] order (`Style::hair_ring*`, `hair_lock*`).
    pub ring: [f32; RING_N],
}

/// A lock is the bin its `_GREY` falls in, this many bins a unit: char-4's numbers run 1.1 to 6.7
/// over a head's 50 to 100 sheet columns and change smoothly round it, so a bin is about two
/// columns (16, one column, broke the ring into streaks on the back's narrow columns).
const LOCK_BINS: f32 = 8.0;

/// The ring's values, in the order of a shine's `ring` and `LIVING_GAME_HAIR_RING`.
pub const RING_KEYS: [&str; RING_N] = ["strength", "width", "soft", "teeth", "strands", "shift", "up", "front", "teeth_scale", "level", "at", "lock_drop", "lock_shift", "width_other"];
pub const RING_N: usize = 14;

/// Crown (hair-ring-3, char-4's intended ring): at one height over the crown (N·up 0.52, about a
/// fifth of the head's height below its top on char-4's normals), hard-edged and about 1.6 cm
/// wide, teeth about 7 mm, one lock in four without it and each a little up or down.
const CROWN: [f32; RING_N] = [0.7, 0.15, 0.0, 1.0, 0.2, 0.35, 0.3, 0.25, 30.0, 1.0, 0.52, 0.25, 0.03, 0.05];

/// The hair shines, the default first (hair-ring-1, approved 2026-11-12).
pub const HAIR_SHINES: [Shine; 3] = [
    // A hard band over the crown, broken where locks part, never across the fringe.
    Shine { name: "crown", label: "Crown", ring: CROWN },
    // A softer, wider band broken by the strands.
    Shine { name: "soft", label: "Soft", ring: [0.45, 0.16, 1.0, 0.0, 1.0, 0.35, 0.2, 2.0, 90.0, 0.0, 0.6, 0.0, 0.0, 0.16] },
    // The ring before hair-ring-1: one hard band, which crosses a smooth fringe.
    Shine { name: "today", label: "Today", ring: [0.7, 0.05, 0.0, 1.0, 0.0, 0.35, 0.2, 2.0, 90.0, 0.0, 0.6, 0.0, 0.0, 0.05] },
];

/// The chosen hair shine: an index into [`HAIR_SHINES`]. Kept in the settings file only once
/// chosen, so a viewer who never chose follows the default. `LIVING_GAME_HAIR_SHINE=<name>` starts
/// in one; `LIVING_GAME_HAIR_RING` overrides single values over any (captures).
#[derive(Resource, Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct HairShine(pub usize);

impl HairShine {
    pub fn parse(s: &str) -> Option<HairShine> {
        HAIR_SHINES.iter().position(|x| x.name == s).map(HairShine)
    }
    pub fn name(self) -> &'static str {
        HAIR_SHINES[self.0.min(HAIR_SHINES.len() - 1)].name
    }
    pub fn from_env() -> Option<HairShine> {
        std::env::var("LIVING_GAME_HAIR_SHINE").ok().and_then(|v| HairShine::parse(v.trim()))
    }
    /// Settings' choices: (label, name).
    pub fn choices() -> [(&'static str, &'static str); 3] {
        HAIR_SHINES.each_ref().map(|s| (s.label, s.name))
    }
}

/// Keep the style profile's hair ring on the chosen shine (an environment's switch rebuilds the
/// profile from its defaults); written only when it differs, so materials are not touched each
/// frame.
fn apply_shine(shine: Res<HairShine>, mut style: ResMut<Style>) {
    let want = style.with_shine(*shine);
    if *style != want {
        *style = want;
    }
}

/// `LIVING_GAME_HAIR_RING=strength,width,…` in [`RING_KEYS`] order (look-dev captures and A/B):
/// the hair ring's style values over the shine's; a value left empty keeps the shine's.
fn hair_ring_env() -> Option<[Option<f32>; RING_N]> {
    static V: std::sync::OnceLock<Option<[Option<f32>; RING_N]>> = std::sync::OnceLock::new();
    *V.get_or_init(|| {
        let v = std::env::var("LIVING_GAME_HAIR_RING").ok().filter(|v| !v.trim().is_empty())?;
        let mut out = [None; RING_N];
        for (i, x) in v.split(',').take(RING_N).enumerate() {
            out[i] = x.trim().parse().ok();
        }
        let set: Vec<String> = RING_KEYS.iter().zip(out).filter_map(|(k, x)| x.map(|x| format!("{k} {x}"))).collect();
        info!("hair ring from LIVING_GAME_HAIR_RING: {}", set.join(", "));
        Some(out)
    })
}

/// The light and shading (Settings › Play › Light): Classic, the look until look-dev step 1, or
/// Look-dev (docs: `.local/living/lookdev/survey/PLAN.md` step 1): a sky/ground hemisphere fill
/// with warm sun against cool shadow, deeper cloth and scenery shadows with warm skin shadows, a
/// cel-stepped specular, a character rim and less rim on scenery. Classic is the default until
/// the owner has seen it; it draws exactly as before (every look-dev term is behind `look.x`).
/// Kept in the settings file only once chosen. `LIVING_GAME_LOOK=classic|lookdev` starts in one.
#[derive(Resource, Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Look {
    #[default]
    Classic,
    Lookdev,
}

impl Look {
    pub const ALL: [Look; 2] = [Look::Classic, Look::Lookdev];
    pub fn name(self) -> &'static str {
        match self {
            Look::Classic => "classic",
            Look::Lookdev => "lookdev",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Look::Classic => "Classic",
            Look::Lookdev => "Look-dev",
        }
    }
    pub fn parse(s: &str) -> Option<Look> {
        Look::ALL.into_iter().find(|l| l.name() == s)
    }
    pub fn from_env() -> Option<Look> {
        std::env::var("LIVING_GAME_LOOK").ok().and_then(|v| Look::parse(v.trim()))
    }
}

/// The character rim with the look-dev light (Settings › Play › Character rim, a taste): a
/// cel-stepped Fresnel rim on characters' sun side (hair too), with a faint cool rim from the sky
/// on the other. Without the look-dev light it does nothing. `LIVING_GAME_CHAR_RIM=off|subtle|
/// strong` starts in one.
#[derive(Resource, Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum CharRim {
    Off,
    #[default]
    Subtle,
    Strong,
}

impl CharRim {
    pub const ALL: [CharRim; 3] = [CharRim::Off, CharRim::Subtle, CharRim::Strong];
    pub fn name(self) -> &'static str {
        match self {
            CharRim::Off => "off",
            CharRim::Subtle => "subtle",
            CharRim::Strong => "strong",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            CharRim::Off => "Off",
            CharRim::Subtle => "Subtle",
            CharRim::Strong => "Strong",
        }
    }
    pub fn parse(s: &str) -> Option<CharRim> {
        CharRim::ALL.into_iter().find(|l| l.name() == s)
    }
    pub fn from_env() -> Option<CharRim> {
        std::env::var("LIVING_GAME_CHAR_RIM").ok().and_then(|v| CharRim::parse(v.trim()))
    }
    fn strength(self) -> f32 {
        match self {
            CharRim::Off => 0.0,
            CharRim::Subtle => 0.62,
            CharRim::Strong => 1.05,
        }
    }
}

/// Character outline weight with the look-dev light (Settings › Play › Outline weight, step 2.3):
/// scales character shell outlines only when [`Look::Lookdev`] is active; Classic ignores it.
/// `LIVING_GAME_OUTLINE_WEIGHT=fine|standard|bold` starts in one.
#[derive(Resource, Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum OutlineWeight {
    Fine,
    #[default]
    Standard,
    Bold,
}

impl OutlineWeight {
    pub const ALL: [OutlineWeight; 3] = [OutlineWeight::Fine, OutlineWeight::Standard, OutlineWeight::Bold];
    pub fn name(self) -> &'static str {
        match self {
            OutlineWeight::Fine => "fine",
            OutlineWeight::Standard => "standard",
            OutlineWeight::Bold => "bold",
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            OutlineWeight::Fine => "Fine",
            OutlineWeight::Standard => "Standard",
            OutlineWeight::Bold => "Bold",
        }
    }
    pub fn parse(s: &str) -> Option<OutlineWeight> {
        OutlineWeight::ALL.into_iter().find(|w| w.name() == s)
    }
    pub fn from_env() -> Option<OutlineWeight> {
        std::env::var("LIVING_GAME_OUTLINE_WEIGHT").ok().and_then(|v| OutlineWeight::parse(v.trim()))
    }
    pub fn scale(self) -> f32 {
        match self {
            OutlineWeight::Fine => 0.72,
            OutlineWeight::Standard => 1.0,
            OutlineWeight::Bold => 1.32,
        }
    }
}

/// Optional per-submesh shell outline width multiplier (e.g. mean of `_OUTLINE_WIDTH` when
/// authored on a mesh). Applied only under [`Look::Lookdev`].
#[derive(Component, Clone, Copy, Debug)]
pub struct OutlineScale(pub f32);

/// Extract a per-mesh outline width multiplier from `_OUTLINE_WIDTH` if authored on the mesh.
pub fn mesh_outline_scale(mesh: &Mesh) -> Option<f32> {
    let bevy::mesh::VertexAttributeValues::Float32(vals) = mesh.attribute(crate::characters::compose::ATTRIBUTE_OUTLINE_WIDTH)? else {
        return None;
    };
    if vals.is_empty() {
        return None;
    }
    let mean = vals.iter().copied().filter(|v| v.is_finite()).sum::<f32>() / vals.len() as f32;
    Some(mean.clamp(0.25, 1.25))
}

impl LookParams {
    /// The look-dev light's values (look-dev steps 1–2's tuning), or off. `LIVING_GAME_PERF=ldsteps=N`
    /// keeps its first N parts (1 the hemisphere and warm/cool split, 2 the ramp, 3 the specular,
    /// 4 the rims), the rest as classic, to time each part.
    pub fn of(look: Look, rim: CharRim, weight: OutlineWeight) -> LookParams {
        let full = LookParams {
            on: true,
            char_rim: rim.strength(),
            specular: 1.0,
            scenery_rim: 0.25,
            sky: 0.075,
            bounce: 0.06,
            shadow_depth: 0.56,
            skin_saturation: 1.14,
            char_threshold: -0.08,
            char_brush: 0.35,
            shadow_sun: 0.35,
            scenery_edges: 0.80,
            outline_weight: weight.scale(),
        };
        match look {
            Look::Classic => LookParams::default(),
            Look::Lookdev => match crate::perf::value("ldsteps") {
                None => full,
                Some(n) => {
                    let classic = Style::default();
                    let mut p = full;
                    if n < 2.0 {
                        (p.shadow_depth, p.skin_saturation, p.char_threshold, p.char_brush) = (classic.shadow_depth, classic.shadow_saturation, classic.threshold, 1.0);
                    }
                    if n < 3.0 {
                        p.specular = 0.0;
                    }
                    if n < 4.0 {
                        (p.char_rim, p.scenery_rim) = (0.0, 1.0);
                    }
                    p
                }
            },
        }
    }
}

/// Keep the style profile on the chosen light (an environment's switch rebuilds the profile from
/// its defaults); written only when it differs.
fn apply_look(look: Res<Look>, rim: Res<CharRim>, weight: Res<OutlineWeight>, mut style: ResMut<Style>) {
    let want = LookParams::of(*look, *rim, *weight);
    if style.look != want {
        style.look = want;
    }
}

impl Style {
    /// The profile with a shine's ring values, then `LIVING_GAME_HAIR_RING`'s over them.
    pub fn with_shine(mut self, shine: HairShine) -> Self {
        let mut r = HAIR_SHINES[shine.0.min(HAIR_SHINES.len() - 1)].ring;
        if let Some(env) = hair_ring_env() {
            for (v, e) in r.iter_mut().zip(env) {
                *v = e.unwrap_or(*v);
            }
        }
        let [x, w, soft, teeth, strands, shift, up, front, teeth_scale, level, at, drop, lock_shift, width_other] = r;
        self.hair_ring_width_other = width_other;
        (self.hair_ring, self.hair_ring_width, self.hair_ring_soft, self.hair_ring_teeth) = (x, w, soft, teeth);
        (self.hair_ring_strands, self.hair_ring_shift, self.hair_ring_up, self.hair_ring_front) = (strands, shift, up, front);
        (self.hair_ring_teeth_scale, self.hair_ring_level, self.hair_ring_at) = (teeth_scale, level, at);
        (self.hair_lock_drop, self.hair_lock_shift) = (drop, lock_shift);
        self
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
            hair_sheen: Vec4::new(self.hair_ring_soft.clamp(0.0, 1.0), self.hair_ring_teeth.clamp(0.0, 1.0), self.hair_ring_strands.clamp(0.0, 1.0), self.hair_ring_teeth_scale.max(1.0)),
            hair_place: Vec4::new(self.hair_ring_up, self.hair_ring_front, LOCK_BINS, self.hair_ring_width_other.max(0.01)),
            hair_lock: Vec4::new(self.hair_lock_drop.clamp(0.0, 1.0), self.hair_lock_shift, self.hair_ring_level.clamp(0.0, 1.0), self.hair_ring_at),
            detail: Vec4::new(0.0, 0.0, self.detail_fade[0], self.detail_fade[1].max(self.detail_fade[0] + 1.0)),
            hand: [Vec4::ZERO; 4],
            hand_bands: Vec4::ZERO,
            file: Vec4::ZERO,
            hand_ink: Vec4::ZERO,
            hand_ink_range: Vec4::ZERO,
            ink: Vec4::ZERO,
            ink_shape: Vec4::ZERO,
            palette: Vec4::ZERO,
            layers: surface_layers(),
            seat: Vec4::ZERO,
            look: if self.look.on { Vec4::new(1.0, self.look.char_rim, self.look.specular, self.look.scenery_rim) } else { Vec4::ZERO },
            look_light: if self.look.on { Vec4::new(self.look.sky, self.look.bounce, self.look.shadow_depth, self.look.skin_saturation) } else { Vec4::ZERO },
            character: Vec4::ZERO,
            look_ramp: if self.look.on { Vec4::new(self.look.char_threshold, self.look.char_brush, self.look.shadow_sun, 0.0) } else { Vec4::ZERO },
        }
    }

    pub fn toon(&self, base: StandardMaterial) -> Toon {
        self.kind(base, Kind::Plain, None)
    }

    /// A toon material for one kind of surface; a `Face` takes its shadow map.
    pub fn kind(&self, base: StandardMaterial, kind: Kind, face: Option<Handle<Image>>) -> Toon {
        let mut params = self.params();
        params.shade.w = kind as u8 as f32;
        Toon { base, extension: ToonExt { params, face, detail: None, tints: None, ink: None } }
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
            .insert_resource(HairShine::from_env().unwrap_or_default())
            .insert_resource(Look::from_env().unwrap_or_default())
            .insert_resource(CharRim::from_env().unwrap_or_default())
            .insert_resource(OutlineWeight::from_env().unwrap_or_default())
            .add_systems(Startup, load_detail)
            .add_systems(Update, (apply_shine, apply_look, apply, fog_outlines).chain());
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
/// Face submesh outline width multiplier under Look-dev (`FacePart` meshes without `_OUTLINE_WIDTH`).
const FACE_OUTLINE_SCALE: f32 = 0.42;
/// The thinnest a Look-dev character shell may be, in pixels of the 3D render target. A shell
/// extruded less than one pixel covers no pixel centre along stretches of its silhouette, so the
/// line breaks into dashes (dev-box's 1x 75% check: Portrait 0.61 px and Near 0.94 px before the
/// floor); from one pixel on, every row or column the edge crosses keeps an ink pixel.
const LD_MIN_RENDER_PX: f32 = 1.0;

fn person_width(style: &Style, distance: f32) -> f32 {
    let t = ((distance - PERSON_NEAR) / (PERSON_FAR - PERSON_NEAR)).clamp(0.0, 1.0);
    let w = style.outline_people * (1.0 - (1.0 - PERSON_THIN) * t);
    (w * 8.0).round() / 8.0
}

/// Look-dev character outline distance curve (step 2.3):
/// - Portrait / close-up (<= 2.0 m): thinner (`0.62x`, face `0.42x` -> ~0.47 px) so close-up faces
///   read delicately like Blue Protocol (`ref4`).
/// - Play Near (~8–10 m) and Middle (~14 m): crisp (`0.92x` -> `0.86x`, ~1.55–1.65 px at Standard).
/// - Play Far (~22 m) to 32 m: tapers smoothly down to `0.42x` so distant figures don't turn chunky.
/// - Widths are logical pixels, as `bevy_mod_outline` takes them: it extrudes `width` times the
///   3D target's pixels per logical pixel (`Camera::target_scaling_factor`). A scaled 3D target
///   (`graphics.rs`) already has that factor times the render scale, so a line keeps its display
///   thickness at every render scale with no compensation here (step 2 pass 2 multiplied by the
///   render scale once more, which thinned lines to 0.56x in render pixels at 75%).
/// - Never below [`LD_MIN_RENDER_PX`] render pixels: `px_per_logical` is the 3D target's pixels
///   per logical pixel (1 at a 1x native output, 2 on a 2x display, 0.75 at 1x 75%, 1.5 at 2x
///   75%). At 2x and 100% it changes only Standard's face lines (0.875 px to 1).
pub(crate) fn ld_person_width(style: &Style, distance: f32, submesh_scale: f32, px_per_logical: f32) -> f32 {
    let s = |a: f32, b: f32, x: f32| {
        let t = ((x - a) / (b - a)).clamp(0.0, 1.0);
        t * t * (3.0 - 2.0 * t)
    };
    let close_to_near = 0.62 + (0.92 - 0.62) * s(1.8, 7.5, distance);
    let near_to_far = 0.92 + (0.42 - 0.92) * s(13.0, 32.0, distance);
    let curve = if distance < 10.0 { close_to_near } else { near_to_far };
    let w = style.outline_people * curve * style.look.outline_weight * submesh_scale;
    // Quantize in 1/16 px steps so close-up face outlines stay smooth while crowds rarely rewrite;
    // the floor rounds up, so it is never under one render pixel.
    let floor = ((LD_MIN_RENDER_PX / px_per_logical.max(0.01)) * 16.0).ceil() / 16.0;
    ((w * 16.0).round() / 16.0).max(floor).max(0.25)
}

/// Look-dev outline colour harmonized with the ambient fill and time of day (step 2.3):
/// replaces fixed warm espresso (`[0.17, 0.11, 0.10]`) with a subtle warm-neutral charcoal at
/// noon (~sRGB (35, 29, 35)), deep twilight plum at dusk (~sRGB (37, 29, 40)), and soft deep
/// midnight indigo at night (~sRGB (29, 34, 57), luma ~34) so night silhouettes harmonize without
/// turning into harsh near-black rings.
pub(crate) fn ld_outline_color(atmo: Option<&crate::daylight::Atmo>, style: &Style) -> Color {
    let (ambient_dir, day, warm) = match atmo.filter(|a| a.active) {
        Some(a) => {
            let dir = a.fill.normalize_or(Vec3::new(0.45, 0.50, 0.75));
            let day = (a.lux / 9000.0).clamp(0.0, 1.0);
            let l = Color::srgb(a.light[0], a.light[1], a.light[2]).to_linear();
            let lum = (0.2126 * l.red + 0.7152 * l.green + 0.0722 * l.blue).max(1e-4);
            let warm = (((l.red - l.blue) / lum - 0.02) / 0.25).clamp(0.0, 1.0);
            (dir, day, warm)
        }
        None => {
            let c = Color::hsv(style.shadow_hue * 360.0, 0.45, 1.0).to_linear();
            (Vec3::new(c.red, c.green, c.blue).normalize_or(Vec3::new(0.45, 0.50, 0.75)), 1.0, 0.5)
        }
    };
    // Warm umber anchor by day, cool sky/ambient-hue deep indigo ink at dusk and night.
    let night = 1.0 - day;
    let warm_ink = Vec3::new(0.020, 0.014, 0.013);
    let cool_dir = (ambient_dir + Vec3::new(0.0, 0.13, 0.08) * night).normalize();
    let cool_lum = 0.021 + 0.027 * night;
    let cool_ink = cool_dir * cool_lum + Vec3::splat(0.003 + 0.0005 * night);
    let mix_warm = 0.60 * warm * day;
    let lin = cool_ink.lerp(warm_ink, mix_warm);
    // Quantize to 1/255 sRGB steps so OutlineVolume isn't dirtied by sub-LSB drift.
    let srgb = Color::linear_rgb(lin.x, lin.y, lin.z).to_srgba();
    let q = |x: f32| (x.clamp(0.0, 1.0) * 255.0).round() / 255.0;
    Color::srgb(q(srgb.red), q(srgb.green), q(srgb.blue))
}

#[allow(clippy::type_complexity)]
fn fog_outlines(
    style: Res<Style>,
    atmo: Option<Res<crate::daylight::Atmo>>,
    cams: Query<(&GlobalTransform, &DistanceFog, &Camera), With<Camera3d>>,
    mut outlines: Query<(&Outlined, &mut OutlineVolume, &GlobalTransform, Option<&InheritedVisibility>, Option<&bevy::mesh::MeshTag>, Has<crate::lookdev::FacePart>, Option<&OutlineScale>)>,
    (edge, target): (Option<Res<crate::sightedge::SightEdge>>, Option<Res<crate::controls::Target>>),
) {
    let Ok((cam, fog, camera)) = cams.single() else { return };
    let FogFalloff::Linear { start, end } = fog.falloff else { return };
    let cutoff = start + (end - start) * 0.55;
    let eye = cam.translation();
    let on = style.outlines && style.enabled;
    let [cr, cg, cb] = style.outline_color;
    let want_col = if style.look.on { ld_outline_color(atmo.as_deref(), &style) } else { Color::srgb(cr, cg, cb) };
    // The 3D target's pixels per logical pixel: the display's scale times the render scale.
    let px_per_logical = camera.target_scaling_factor().unwrap_or(1.0);
    // Limited view fogs round my character, not by the camera's distance (sightedge.rs).
    let limit = edge.and_then(|e| e.outline_limit(target.and_then(|t| t.0)));
    for (kind, mut o, g, shown, tag, face_part, scale) in &mut outlines {
        let d = g.translation().distance(eye);
        // A thing mostly faded out (fade.rs) loses its lines with it.
        let faded = tag.is_some_and(|t| crate::fade::tag_level(t.value) > 6);
        let within = limit.is_none_or(|(c, r)| Vec2::new(g.translation().x, g.translation().z).distance(c) < r);
        let want = on && shown.is_none_or(|v| v.get()) && d < cutoff && !faded && within;
        if o.visible != want {
            o.visible = want;
        }
        if want {
            if o.colour != want_col {
                o.colour = want_col;
            }
            if matches!(kind, Outlined::Person) {
                let w = if style.look.on {
                    let submesh = scale.map_or(if face_part { FACE_OUTLINE_SCALE } else { 1.0 }, |s| if face_part { s.0.min(FACE_OUTLINE_SCALE) } else { s.0 });
                    ld_person_width(&style, d, submesh, px_per_logical)
                } else {
                    person_width(&style, d)
                };
                if o.width != w {
                    o.width = w;
                }
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
        ToonParams { shadow: Vec4::new(1.0, 1.0, 1.0, 0.45), rim: Vec4::ZERO, band: Vec4::new(-0.2, 0.6, 0.0, 1.0), extra: Vec4::new(1.0, 0.0, 1.0, 1.0), shade: Vec4::new(0.0, 0.0, 1.0, 0.0), recolor: Vec4::ZERO, recolor_from: Vec4::ZERO, atmo: Vec4::new(style.wind, style.wet, 0.0, 0.0), face: Vec4::new(0.3, 1.0, 1.0, 0.0), hair: Vec4::new(0.0, 0.1, 0.0, 0.0), look: Vec4::ZERO, look_light: Vec4::ZERO, look_ramp: Vec4::ZERO, ..style.params() }
    };
    for (_, m) in toons.iter_mut() {
        // Keep each material's own kind (skin, face, hair), recolouring, detail and hand-made
        // profile.
        let old = m.extension.params;
        m.extension.params = p;
        m.extension.params.shade.w = old.shade.w;
        m.extension.params.hand = old.hand;
        m.extension.params.hand_bands = old.hand_bands;
        m.extension.params.file = old.file;
        m.extension.params.hand_ink = old.hand_ink;
        m.extension.params.hand_ink_range = old.hand_ink_range;
        m.extension.params.ink = old.ink;
        m.extension.params.ink_shape = old.ink_shape;
        m.extension.params.palette = old.palette;
        m.extension.params.recolor = old.recolor;
        m.extension.params.recolor_from = old.recolor_from;
        m.extension.params.detail.x = old.detail.x;
        m.extension.params.seat = old.seat;
        m.extension.params.character = old.character;
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

/// Give a mesh its outline's directions unless its file brought them (`_OUTLINE_NORMAL`, which
/// the generator writes smoothed across a person's meshes, so the outline closes between them).
/// Returns whether they were generated here.
pub fn outline_normals(mesh: &mut Mesh) -> bool {
    use bevy_mod_outline::OutlineMeshExt;
    use std::sync::atomic::Ordering::Relaxed;
    // `LIVING_GAME_PERF=genoutlines`: generate them anyway (to compare with the file's).
    if mesh.contains_attribute(bevy_mod_outline::ATTRIBUTE_OUTLINE_NORMAL) && !crate::perf::has("genoutlines") {
        OUTLINE_NORMALS.1.fetch_add(1, Relaxed);
        return false;
    }
    let _ = mesh.generate_outline_normals(&Default::default());
    OUTLINE_NORMALS.0.fetch_add(1, Relaxed);
    true
}

/// Meshes whose outline directions were generated, and meshes that brought their own (the
/// `assets:` diag line, perf.rs).
pub static OUTLINE_NORMALS: (std::sync::atomic::AtomicUsize, std::sync::atomic::AtomicUsize) = (std::sync::atomic::AtomicUsize::new(0), std::sync::atomic::AtomicUsize::new(0));

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outline_weight_scales_and_parses() {
        assert_eq!(OutlineWeight::default(), OutlineWeight::Standard);
        assert_eq!(OutlineWeight::parse("fine"), Some(OutlineWeight::Fine));
        assert_eq!(OutlineWeight::parse("standard"), Some(OutlineWeight::Standard));
        assert_eq!(OutlineWeight::parse("bold"), Some(OutlineWeight::Bold));
        assert_eq!(OutlineWeight::parse("other"), None);
        assert!(OutlineWeight::Fine.scale() < OutlineWeight::Standard.scale());
        assert!(OutlineWeight::Standard.scale() < OutlineWeight::Bold.scale());
    }

    #[test]
    fn ld_outline_distance_curve_thins_at_portrait_and_far_and_on_faces() {
        let mut s = Style::default();
        s.look = LookParams::of(Look::Lookdev, CharRim::Subtle, OutlineWeight::Standard);
        // On a 2x display at 100% (2 render px per logical px), where only the face line meets the floor.
        let portrait = ld_person_width(&s, 1.4, 1.0, 2.0);
        let portrait_face = ld_person_width(&s, 1.4, FACE_OUTLINE_SCALE, 2.0);
        let near = ld_person_width(&s, 9.4, 1.0, 2.0);
        let middle = ld_person_width(&s, 14.1, 1.0, 2.0);
        let far = ld_person_width(&s, 28.0, 1.0, 2.0);
        assert!(portrait < near, "portrait ({portrait}) is thinner than Near ({near})");
        assert!(portrait_face < portrait * 0.55, "face ({portrait_face}) is thinner than body ({portrait})");
        assert!(near >= middle && middle > far, "Near ({near}) >= Middle ({middle}) > Far ({far})");
        // The width is logical: a scaled target's own scale factor keeps its display thickness.
        assert_eq!(ld_person_width(&s, 9.4, 1.0, 1.5), near, "2x at 75%: Near as at 100%");

        let mut fine = s;
        fine.look = LookParams::of(Look::Lookdev, CharRim::Subtle, OutlineWeight::Fine);
        let mut bold = s;
        bold.look = LookParams::of(Look::Lookdev, CharRim::Subtle, OutlineWeight::Bold);
        assert!(ld_person_width(&fine, 14.1, 1.0, 2.0) < middle);
        assert!(ld_person_width(&bold, 14.1, 1.0, 2.0) > middle);
    }

    #[test]
    fn ld_outline_never_under_one_render_pixel() {
        let mut s = Style::default();
        for weight in [OutlineWeight::Fine, OutlineWeight::Standard, OutlineWeight::Bold] {
            s.look = LookParams::of(Look::Lookdev, CharRim::Subtle, weight);
            // 1x and 2x outputs at 100%, Auto's 2x factor (1440 / 1898), 85%, 75% and 67%.
            for px in [1.0, 2.0, 2.0 * 1440.0 / 1898.0, 0.85, 0.75, 0.67, 1.5, 1.34] {
                for d in [0.8, 1.4, 4.0, 9.4, 14.1, 22.0, 28.0, 40.0] {
                    for sub in [1.0, FACE_OUTLINE_SCALE, 0.2] {
                        let w = ld_person_width(&s, d, sub, px);
                        assert!(w * px >= LD_MIN_RENDER_PX - 1e-4, "{weight:?} d {d} sub {sub} at {px} px/logical: {w} logical = {} render px", w * px);
                    }
                }
            }
        }
        // dev-box's case: a 1x output at 75%. Portrait was 0.8125 logical (0.61 render px).
        s.look = LookParams::of(Look::Lookdev, CharRim::Subtle, OutlineWeight::Standard);
        assert_eq!(ld_person_width(&s, 1.4, 1.0, 0.75), 1.375);
        // Widths over the floor are left as they are.
        assert_eq!(ld_person_width(&s, 9.4, 1.0, 0.75), ld_person_width(&s, 9.4, 1.0, 2.0));
    }

    #[test]
    fn ld_outline_color_shifts_cool_at_night_and_dusk() {
        let style = Style::default();
        let noon = crate::daylight::Atmo {
            active: true,
            lux: 9000.0,
            light: [1.0, 0.96, 0.88],
            fill: Vec3::new(0.010, 0.008, 0.022),
            ..default()
        };
        let night = crate::daylight::Atmo {
            active: true,
            lux: 2800.0,
            light: [0.46, 0.60, 1.0],
            fill: Vec3::new(0.008, 0.012, 0.028),
            ..default()
        };
        let c_noon = ld_outline_color(Some(&noon), &style).to_srgba();
        let c_night = ld_outline_color(Some(&night), &style).to_srgba();
        let night_luma = (0.2126 * c_night.red + 0.7152 * c_night.green + 0.0722 * c_night.blue) * 255.0;
        assert!(c_night.blue > c_night.red, "night outline harmonizes cool blue ({c_night:?})");
        assert!(c_noon.red > c_night.red, "noon outline is warmer/lighter than night ({c_noon:?} vs {c_night:?})");
        assert!(night_luma >= 30.0 && night_luma <= 42.0, "night outline stays soft deep indigo, not near-black (luma {night_luma:.1}, {c_night:?})");
    }
}
