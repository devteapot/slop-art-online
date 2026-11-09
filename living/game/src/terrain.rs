//! The ground's material (`terrain.wesl`): the shared toon lighting over hand-painted detail.
//!
//! The island's chunks (`island.rs`) and the look-dev ground discs (`envs.rs`) keep their vertex
//! colours, which carry every palette and regional colour. This material multiplies a painted
//! detail texture into them:
//! - **Layers** ([`Layer`]): one texture array of stylised, tileable textures, painted by
//!   `living/tools/textures/paint.py` (`ground.png`, git-ignored; `just living-game-textures`).
//!   Each texel is a factor round mid-grey, so a layer adds brush strokes and shapes but no
//!   colour of its own beyond a slight hue.
//! - **Blend weights** per vertex ([`ATTRIBUTE_BLEND`]): three `Unorm8x4` attributes, one weight
//!   per layer, from the terrain class and region under the vertex (blended over about 25 m like
//!   the colours, with crisp roads). The shader samples only the few layers with weight, blends
//!   them by the textures' height channel, and samples cliffs from three sides (triplanar).
//! - **Calm at range:** the detail fades to the plain vertex colour between `FADE` metres, and a
//!   macro layer of slow noise varies value and hue so neither the near nor the far ground tiles.
//!
//! Lighting is the shared toon model (`toon_light.wesl`) for plain surfaces (bands, hue-shifted
//! shadows, sky fill at night, rim, point lights, rain darkening and puddles, which here gather
//! in the detail's hollows). Its parameters are copied from the toon materials whenever the
//! style changes (F2 sliders, the plain-look comparison, weather), so ground and scenery always
//! agree. It is one material for every ground mesh, so the ground stays
//! one batch set per view.
//!
//! The extra vertex attributes exist only in the main pass. Prepass and shadow pipelines keep
//! Bevy's default vertex layout and shaders (the ground doesn't sway), so they are unchanged.
//!
//! `LIVING_GAME_PERF=noterrain` draws the ground with the plain toon material instead (A/B).

use crate::style::{Toon, ToonParams};
use bevy::asset::{embedded_asset, RenderAssetUsages};
use bevy::image::{CompressedImageFormats, ImageAddressMode, ImageFilterMode, ImageSampler, ImageSamplerDescriptor, ImageType};
use bevy::mesh::{MeshVertexAttribute, MeshVertexBufferLayoutRef, VertexAttributeValues, VertexFormat};
use bevy::pbr::{ExtendedMaterial, MaterialExtension, MaterialExtensionKey, MaterialExtensionPipeline};
use bevy::prelude::*;
use bevy::render::render_resource::{AsBindGroup, Extent3d, RenderPipelineDescriptor, ShaderType, SpecializedMeshPipelineError, TextureDataOrder};
use bevy::shader::{ShaderDefVal, ShaderRef};

pub type Ground = ExtendedMaterial<StandardMaterial, GroundExt>;

/// The ground textures, in the order of `paint.py`'s `GROUND` set (layer k of `ground.png`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Layer {
    Grass,
    LushGrass,
    DryGrass,
    ForestFloor,
    Dirt,
    Sand,
    Rock,
    Cobble,
    Flagstone,
    Mud,
    SpiritMoss,
    /// A cyberpunk town's large square panels.
    Pavers,
}

pub const LAYERS: usize = 12;
/// The layers' names in `ground.txt` (paint.py `GROUND`), in [`Layer`] order.
const NAMES: [&str; LAYERS] = ["grass", "lush_grass", "dry_grass", "forest_floor", "dirt", "sand", "rock", "cobble", "flagstone", "mud", "spirit_moss", "pavers"];

/// Per layer: tile size (m) and detail strength (how far its factors depart from 1).
const TILE: [(f32, f32); LAYERS] = [
    (4.0, 1.0),  // grass
    (3.6, 1.0),  // lush grass
    (4.4, 1.0),  // dry grass
    (4.0, 1.0),  // forest floor
    (4.0, 1.0),  // dirt
    (5.0, 0.9),  // sand
    (7.0, 1.0),  // rock
    (3.2, 1.0),  // cobble
    (4.8, 1.0),  // flagstone
    (4.5, 0.9),  // mud
    (4.0, 1.0),  // spirit moss
    (6.0, 1.0),  // pavers
];

/// Detail at full strength up to the first distance (m), gone by the second.
const FADE: [f32; 2] = [30.0, 85.0];

/// Blend weights for layers 0–3, 4–7 and 8–11, at shader locations 8, 9 and 10.
pub const ATTRIBUTE_BLEND: [MeshVertexAttribute; 3] = [
    MeshVertexAttribute::new("Ground_Blend_A", 0x5a0_0001, VertexFormat::Unorm8x4),
    MeshVertexAttribute::new("Ground_Blend_B", 0x5a0_0002, VertexFormat::Unorm8x4),
    MeshVertexAttribute::new("Ground_Blend_C", 0x5a0_0003, VertexFormat::Unorm8x4),
];

/// Per-vertex layer weights, accumulated from samples and quantised for the mesh.
#[derive(Clone, Copy, Default, Debug)]
pub struct Blend(pub [f32; LAYERS]);

impl Blend {
    pub fn one(layer: Layer) -> Self {
        let mut b = Self::default();
        b.0[layer as usize] = 1.0;
        b
    }

    pub fn add(&mut self, layer: Layer, w: f32) {
        self.0[layer as usize] += w;
    }

    /// Normalised and packed into the three attributes' bytes.
    pub fn pack(&self) -> [[u8; 4]; 3] {
        let sum: f32 = self.0.iter().sum::<f32>().max(1e-6);
        let mut out = [[0u8; 4]; 3];
        for (k, w) in self.0.iter().enumerate() {
            out[k / 4][k % 4] = ((w / sum) * 255.0 + 0.5) as u8;
        }
        out
    }
}

/// Add the blend attributes to a ground mesh, one [`Blend`] per vertex.
pub fn insert_blend(mesh: &mut Mesh, blends: &[Blend]) {
    let packed: Vec<[[u8; 4]; 3]> = blends.iter().map(Blend::pack).collect();
    for (i, attr) in ATTRIBUTE_BLEND.iter().enumerate() {
        mesh.insert_attribute(attr.clone(), VertexAttributeValues::Unorm8x4(packed.iter().map(|p| p[i]).collect()));
    }
}

/// The layer of a look-dev environment's ground disc.
pub fn disc_layer(env: &str, surface: &str) -> Layer {
    match (env, surface) {
        ("forest", _) => Layer::ForestFloor,
        ("spirit_forest", _) => Layer::SpiritMoss,
        ("caverns", _) | (_, "cave") => Layer::Rock,
        ("steampunk_city", _) => Layer::Cobble,
        ("cyberpunk_city", _) => Layer::Pavers,
        (_, "paved") => Layer::Flagstone,
        _ => Layer::Grass,
    }
}

#[derive(Clone, Copy, Debug, ShaderType)]
pub struct GroundParams {
    /// Per layer, 1 / tile size (1/m): layers 0–3, 4–7, 8–11.
    pub scale: [Vec4; 3],
    /// Per layer, detail strength.
    pub amount: [Vec4; 3],
    /// x: full detail until (m), y: none from (m), z: macro variation strength, w: on (1) or
    /// the plain look (0, detail off).
    pub fade: Vec4,
    /// x: height-blend depth, y: N.y below which slopes turn to rock, z: N.y where they are all
    /// rock, w: triplanar sharpness.
    pub blend: Vec4,
}

impl Default for GroundParams {
    fn default() -> Self {
        let mut scale = [Vec4::ZERO; 3];
        let mut amount = [Vec4::ZERO; 3];
        for (k, (tile, a)) in TILE.iter().enumerate() {
            scale[k / 4][k % 4] = 1.0 / tile;
            amount[k / 4][k % 4] = *a;
        }
        Self { scale, amount, fade: Vec4::new(FADE[0], FADE[1], 0.07, 1.0), blend: Vec4::new(0.3, 0.72, 0.5, 4.0) }
    }
}

#[derive(Asset, AsBindGroup, Reflect, Debug, Clone)]
pub struct GroundExt {
    /// The toon parameters, copied from the toon materials (`sync`).
    #[uniform(100)]
    pub toon: ToonParams,
    #[uniform(101)]
    #[reflect(ignore)]
    pub params: GroundParams,
    #[texture(102, dimension = "2d_array")]
    #[sampler(103)]
    pub layers: Handle<Image>,
}

const SHADER: &str = "embedded://living_game/terrain.wesl";

impl MaterialExtension for GroundExt {
    fn vertex_shader() -> ShaderRef {
        SHADER.into()
    }

    fn fragment_shader() -> ShaderRef {
        SHADER.into()
    }

    /// The main pass reads the blend weights; the prepass and shadow pipelines keep Bevy's layout.
    fn specialize(_: &MaterialExtensionPipeline, descriptor: &mut RenderPipelineDescriptor, layout: &MeshVertexBufferLayoutRef, _: MaterialExtensionKey<Self>) -> Result<(), SpecializedMeshPipelineError> {
        if descriptor.vertex.shader_defs.iter().any(|d| matches!(d, ShaderDefVal::Bool(name, true) if name == "PREPASS_PIPELINE")) {
            return Ok(());
        }
        let buffer = layout.0.get_layout(&[
            Mesh::ATTRIBUTE_POSITION.at_shader_location(0),
            Mesh::ATTRIBUTE_NORMAL.at_shader_location(1),
            Mesh::ATTRIBUTE_COLOR.at_shader_location(5),
            ATTRIBUTE_BLEND[0].at_shader_location(8),
            ATTRIBUTE_BLEND[1].at_shader_location(9),
            ATTRIBUTE_BLEND[2].at_shader_location(10),
        ])?;
        descriptor.vertex.buffers = vec![buffer];
        Ok(())
    }
}

/// The one ground material.
#[derive(Resource)]
pub struct GroundMat(pub Handle<Ground>);

pub struct TerrainPlugin;

impl Plugin for TerrainPlugin {
    fn build(&self, app: &mut App) {
        embedded_asset!(app, "terrain.wesl");
        app.add_plugins(MaterialPlugin::<Ground>::default()).add_systems(Startup, setup).add_systems(PostUpdate, sync);
    }
}

fn setup(mut commands: Commands, mut images: ResMut<Assets<Image>>, mut mats: ResMut<Assets<Ground>>) {
    let layers = images.add(load_array("textures/ground", &NAMES));
    let base = StandardMaterial { base_color: Color::WHITE, perceptual_roughness: 0.85, ..default() };
    let toon = crate::style::Style::default().toon(StandardMaterial::default()).extension.params;
    commands.insert_resource(GroundMat(mats.add(Ground { base, extension: GroundExt { toon, params: GroundParams::default(), layers } })));
}

/// A painted strip (`<name>.png`, paint.py) as a texture array with mipmaps, if its layer list
/// (`<name>.txt`) is `names`; flat mid-grey (no detail) if it is missing or painted for another
/// order. The ground's layers, and the models' surfaces (`style::DetailLayers`).
pub fn load_array(name: &str, names: &[&str]) -> Image {
    let layers = names.len();
    let root = std::path::Path::new(&crate::lookdev::asset_root()).join(name);
    let path = root.with_extension("png");
    let sampler = ImageSampler::Descriptor(ImageSamplerDescriptor {
        address_mode_u: ImageAddressMode::Repeat,
        address_mode_v: ImageAddressMode::Repeat,
        mag_filter: ImageFilterMode::Linear,
        min_filter: ImageFilterMode::Linear,
        mipmap_filter: ImageFilterMode::Linear,
        anisotropy_clamp: 4,
        ..default()
    });
    let listed: Vec<String> = std::fs::read_to_string(root.with_extension("txt")).unwrap_or_default().lines().map(str::to_string).collect();
    let image = if listed != names {
        warn!("textures: {} does not list the layers {names:?} (run `just living-game-textures --set all`); drawn without detail", root.with_extension("txt").display());
        None
    } else {
        std::fs::read(&path).ok().and_then(|bytes| match Image::from_buffer(&bytes, ImageType::Extension("png"), CompressedImageFormats::NONE, false, sampler.clone(), RenderAssetUsages::RENDER_WORLD) {
            Ok(i) => Some(i),
            Err(e) => {
                warn!("textures: {} unreadable ({e}); drawn without detail", path.display());
                None
            }
        })
    };
    let Some(mut image) = image.filter(|i| i.height() == i.width() * layers as u32) else {
        if listed == names {
            warn!("textures: no {} with {layers} layers (run `just living-game-textures --set all`); drawn without detail", path.display());
        }
        let mut flat = Image::new_fill(Extent3d { width: 4, height: 4 * layers as u32, depth_or_array_layers: 1 }, bevy::render::render_resource::TextureDimension::D2, &[128, 128, 128, 128], bevy::render::render_resource::TextureFormat::Rgba8Unorm, RenderAssetUsages::RENDER_WORLD);
        flat.sampler = sampler;
        let _ = flat.reinterpret_stacked_2d_as_array(layers as u32);
        return flat;
    };
    let size = image.width();
    let base = image.data.take().unwrap_or_default();
    image.data = Some(with_mips(&base, size, layers));
    let _ = image.reinterpret_stacked_2d_as_array(layers as u32);
    image.texture_descriptor.mip_level_count = size.ilog2() + 1;
    image.data_order = TextureDataOrder::LayerMajor;
    image
}

/// Box-filtered mipmaps for each square RGBA8 layer, laid out layer by layer (each layer's mips
/// in a row). The data is linear, so averaging is exact; small mips tend to mid-grey (no detail).
fn with_mips(base: &[u8], size: u32, layers: usize) -> Vec<u8> {
    let layer_bytes = (size * size * 4) as usize;
    let mut out = Vec::with_capacity(layer_bytes * layers * 4 / 3 + 64);
    for l in 0..layers {
        let mut level: Vec<u8> = base[l * layer_bytes..(l + 1) * layer_bytes].to_vec();
        let mut s = size as usize;
        out.extend_from_slice(&level);
        while s > 1 {
            let h = s / 2;
            let mut next = vec![0u8; h * h * 4];
            for y in 0..h {
                for x in 0..h {
                    for c in 0..4 {
                        let at = |xx: usize, yy: usize| level[(yy * s + xx) * 4 + c] as u32;
                        let sum = at(2 * x, 2 * y) + at(2 * x + 1, 2 * y) + at(2 * x, 2 * y + 1) + at(2 * x + 1, 2 * y + 1);
                        next[(y * h + x) * 4 + c] = ((sum + 2) / 4) as u8;
                    }
                }
            }
            out.extend_from_slice(&next);
            level = next;
            s = h;
        }
    }
    out
}

/// Keep the ground's toon parameters equal to the plain toon materials' (style sliders, the
/// plain-look comparison, wind and wetness). `world::Palette::vertex` is a plain toon material
/// that `style::apply` keeps current. The style can change after `apply` has run in a frame
/// (weather writes it), so this compares the parameters themselves every frame (ten vectors)
/// and writes the material only when they differ.
fn sync(style: Res<crate::style::Style>, palette: Res<crate::world::Palette>, toons: Res<Assets<Toon>>, ground: Option<Res<GroundMat>>, mut mats: ResMut<Assets<Ground>>) {
    let Some(ground) = ground else { return };
    let Some(src) = toons.get(&palette.vertex) else { return };
    let key = |t: &ToonParams| [t.shadow, t.rim, t.band, t.extra, t.shade, t.recolor, t.recolor_from, t.atmo, t.face, t.hair, t.detail];
    let on = if style.enabled { 1.0 } else { 0.0 };
    let Some(m) = mats.get(&ground.0) else { return };
    if key(&m.extension.toon) == key(&src.extension.params) && m.extension.params.fade.w == on {
        return;
    }
    let toon = src.extension.params;
    if let Some(mut m) = mats.get_mut(&ground.0) {
        m.extension.toon = toon;
        m.extension.params.fade.w = on;
    }
}
