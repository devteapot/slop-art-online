//! The ground's material (`terrain.wesl`): the shared toon lighting over hand-painted detail.
//!
//! The island's chunks (`island.rs`) and the look-dev ground discs (`envs.rs`) keep their vertex
//! colours, which carry every palette and regional colour. This material multiplies a painted
//! detail texture into them:
//! - **Layers** ([`Layer`]): one texture array of stylised, tileable textures, painted by
//!   `living/tools/textures/paint.py` (`ground.png`, git-ignored; `just living-game-textures`).
//!   Each texel is a factor round mid-grey, so a layer adds brush strokes and shapes but no
//!   colour of its own beyond a slight hue. Layers are matched by name ([`match_layers`]): a
//!   painted strip with fewer, more or reordered layers still draws, the missing ones as their
//!   nearest older layer ([`fallback`]) or flat.
//! - **Blend weights** per vertex ([`ATTRIBUTE_BLEND`]): six `Unorm8x4` attributes, one weight
//!   per weighted layer, from the terrain class and region under the vertex (blended over about
//!   25 m like the colours, with crisp roads), or from the environment's ground map (`ground.rs`). The shader samples only the few layers with weight, blends
//!   them by the textures' height channel, and samples cliffs from three sides (triplanar).
//! - **Blocking rock** (the rules' `Terrain::Rock`, which walkers cannot cross) reads as cliff:
//!   the vertex colour's alpha carries the share of blocking tiles round each vertex
//!   ([`BLOCKED_ALPHA`]), and the shader turns it, sharpened and broken up by noise, into dark
//!   bedded stone ([`Layer::Cliff`]) with strata by height and a dark rim where it meets walkable
//!   ground. Colour, strata and rim show at every distance; only the texture fades. Walkable
//!   steep slopes keep the lighter `rock` layer.
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
    /// Arid lands (`island.rs` `Climate::Arid`): sun-baked bare earth, a dried mud pan's plates,
    /// packed gravel.
    DryEarth,
    CrackedMud,
    Gravel,
    /// A hand-authored town's surfaces (Cullet's, set by its ground map, `ground.rs`): slate
    /// setts, a quay's big flags, cinders, kelp-strewn shingle, wet sand, peat, heather, worked
    /// garden soil and thin turf.
    SlateSetts,
    QuayFlags,
    Cinders,
    KelpShingle,
    WetSand,
    Peat,
    Heather,
    WorkedSoil,
    ThinTurf,
    /// Rock that blocks walking (the rules' `Terrain::Rock`), from the vertex colour's alpha
    /// ([`BLOCKED_ALPHA`]), not from the blend weights.
    Cliff,
}

pub const LAYERS: usize = 25;
/// The layers' names in `ground.txt` (paint.py `GROUND`), in [`Layer`] order.
const NAMES: [&str; LAYERS] = [
    "grass", "lush_grass", "dry_grass", "forest_floor", "dirt", "sand", "rock", "cobble", "flagstone", "mud", "spirit_moss", "pavers", "dry_earth", "cracked_mud", "gravel",
    "slate_setts", "quay_flags", "cinders", "kelp_shingle", "wet_sand", "peat", "heather", "worked_soil", "thin_turf", "cliff",
];
/// Weighted layers: six `Unorm8x4` attributes, one weight each. [`Layer::Cliff`] is the vertex
/// alpha instead.
const WEIGHTED: usize = 24;
const BLENDS: usize = WEIGHTED / 4;
// The cliff is the last layer, after every weighted one (`terrain.wesl` `CLIFF`).
const _: () = assert!(Layer::Cliff as usize == WEIGHTED && WEIGHTED + 1 == LAYERS);

/// A ground vertex's colour alpha where every tile round it blocks walking; 1 where none does.
/// It stays at or above 0.5, which the toon material reads as "no painted surface" (the
/// `noterrain` comparison draws the same meshes with it).
pub const BLOCKED_ALPHA: f32 = 0.5;

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
    (4.5, 1.0),  // dry earth
    (3.4, 1.0),  // cracked mud
    (2.6, 1.0),  // gravel
    (3.2, 1.0),  // slate setts
    (4.8, 1.0),  // quay flags
    (2.6, 1.0),  // cinders
    (3.4, 1.0),  // kelp shingle
    (5.0, 1.0),  // wet sand
    (4.0, 1.0),  // peat
    (3.6, 1.0),  // heather
    (3.2, 1.0),  // worked soil
    (4.0, 1.0),  // thin turf
    (6.5, 1.0),  // cliff
];

impl Layer {
    pub const ALL: [Layer; LAYERS] = [
        Layer::Grass, Layer::LushGrass, Layer::DryGrass, Layer::ForestFloor, Layer::Dirt, Layer::Sand, Layer::Rock, Layer::Cobble, Layer::Flagstone, Layer::Mud, Layer::SpiritMoss, Layer::Pavers, Layer::DryEarth, Layer::CrackedMud, Layer::Gravel,
        Layer::SlateSetts, Layer::QuayFlags, Layer::Cinders, Layer::KelpShingle, Layer::WetSand, Layer::Peat, Layer::Heather, Layer::WorkedSoil, Layer::ThinTurf, Layer::Cliff,
    ];

    /// Its name in `ground.txt` and in ground maps.
    #[cfg(test)]
    pub fn name(self) -> &'static str {
        NAMES[self as usize]
    }

    pub fn from_name(name: &str) -> Option<Self> {
        NAMES.iter().position(|n| *n == name).map(|k| Self::ALL[k])
    }
}

/// The painted layer a ground layer borrows while `ground.png` lacks it (painted before it
/// existed): the nearest of the first sixteen.
pub fn fallback(name: &str) -> Option<&'static str> {
    Some(match name {
        "slate_setts" => "cobble",
        "quay_flags" => "flagstone",
        "cinders" | "kelp_shingle" => "gravel",
        "wet_sand" => "sand",
        "peat" => "mud",
        "heather" => "dry_grass",
        "worked_soil" => "dirt",
        "thin_turf" => "grass",
        _ => return None,
    })
}

/// Detail at full strength up to the first distance (m), gone by the second.
const FADE: [f32; 2] = [30.0, 85.0];

/// Blend weights for layers 0–3, 4–7, …, 20–23, at shader locations 8 to 13.
pub const ATTRIBUTE_BLEND: [MeshVertexAttribute; BLENDS] = [
    MeshVertexAttribute::new("Ground_Blend_A", 0x5a0_0001, VertexFormat::Unorm8x4),
    MeshVertexAttribute::new("Ground_Blend_B", 0x5a0_0002, VertexFormat::Unorm8x4),
    MeshVertexAttribute::new("Ground_Blend_C", 0x5a0_0003, VertexFormat::Unorm8x4),
    MeshVertexAttribute::new("Ground_Blend_D", 0x5a0_0004, VertexFormat::Unorm8x4),
    MeshVertexAttribute::new("Ground_Blend_E", 0x5a0_0005, VertexFormat::Unorm8x4),
    MeshVertexAttribute::new("Ground_Blend_F", 0x5a0_0006, VertexFormat::Unorm8x4),
];

/// Per-vertex layer weights, accumulated from samples and quantised for the mesh.
#[derive(Clone, Copy, Default, Debug)]
pub struct Blend(pub [f32; WEIGHTED]);

impl Blend {
    pub fn one(layer: Layer) -> Self {
        let mut b = Self::default();
        b.add(layer, 1.0);
        b
    }

    /// Cliff takes no weight: it comes from the blocking tiles (vertex alpha).
    pub fn add(&mut self, layer: Layer, w: f32) {
        if let Some(x) = self.0.get_mut(layer as usize) {
            *x += w;
        }
    }

    /// This blend moved a share `t` (0–1) of the way to one layer alone.
    pub fn toward(mut self, layer: Layer, t: f32) -> Self {
        let sum: f32 = self.0.iter().sum::<f32>().max(1e-6);
        for w in &mut self.0 {
            *w *= 1.0 - t;
        }
        self.add(layer, sum * t);
        self
    }

    /// Normalised and packed into the six attributes' bytes.
    pub fn pack(&self) -> [[u8; 4]; BLENDS] {
        let sum: f32 = self.0.iter().sum::<f32>().max(1e-6);
        let mut out = [[0u8; 4]; BLENDS];
        for (k, w) in self.0.iter().enumerate() {
            out[k / 4][k % 4] = ((w / sum) * 255.0 + 0.5) as u8;
        }
        out
    }
}

/// Add the blend attributes to a ground mesh, one [`Blend`] per vertex.
pub fn insert_blend(mesh: &mut Mesh, blends: &[Blend]) {
    let packed: Vec<[[u8; 4]; BLENDS]> = blends.iter().map(Blend::pack).collect();
    for (i, attr) in ATTRIBUTE_BLEND.iter().enumerate() {
        mesh.insert_attribute(attr.clone(), VertexAttributeValues::Unorm8x4(packed.iter().map(|p| p[i]).collect()));
    }
}

/// The layer of a look-dev environment's ground disc.
pub fn disc_layer(env: &str, surface: &str) -> Layer {
    match (env, surface) {
        ("forest", _) => Layer::ForestFloor,
        ("wastes", _) => Layer::DryEarth,
        ("scrubland", _) => Layer::DryGrass,
        ("badlands", _) => Layer::Gravel,
        ("spirit_forest", _) => Layer::SpiritMoss,
        ("caverns", _) | (_, "cave") => Layer::Rock,
        ("steampunk_city", _) => Layer::Cobble,
        ("cyberpunk_city", _) => Layer::Pavers,
        (_, "paved") => Layer::Flagstone,
        _ => Layer::Grass,
    }
}

/// Vectors of four per-layer values (`terrain.wesl` `Ground`).
const VEC4S: usize = LAYERS.div_ceil(4);

#[derive(Clone, Copy, Debug, ShaderType)]
pub struct GroundParams {
    /// Per layer, 1 / tile size (1/m): layers 0–3, 4–7, …, 24 (the cliff).
    pub scale: [Vec4; VEC4S],
    /// Per layer, detail strength.
    pub amount: [Vec4; VEC4S],
    /// x: full detail until (m), y: none from (m), z: macro variation strength, w: on (1) or
    /// the plain look (0, detail off).
    pub fade: Vec4,
    /// x: height-blend depth, y: N.y below which slopes turn to rock, z: N.y where they are all
    /// rock, w: triplanar sharpness.
    pub blend: Vec4,
}

impl Default for GroundParams {
    fn default() -> Self {
        let mut scale = [Vec4::ZERO; VEC4S];
        let mut amount = [Vec4::ZERO; VEC4S];
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
            ATTRIBUTE_BLEND[3].at_shader_location(11),
            ATTRIBUTE_BLEND[4].at_shader_location(12),
            ATTRIBUTE_BLEND[5].at_shader_location(13),
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
    let layers = images.add(load_array("textures/ground", &NAMES, fallback));
    let base = StandardMaterial { base_color: Color::WHITE, perceptual_roughness: 0.85, ..default() };
    let toon = crate::style::Style::default().toon(StandardMaterial::default()).extension.params;
    commands.insert_resource(GroundMat(mats.add(Ground { base, extension: GroundExt { toon, params: GroundParams::default(), layers } })));
}

/// Where each layer the client knows comes from in a painted strip: its own painted layer (by
/// name in `<name>.txt`), else its [`fallback`]'s, else none (drawn flat). Also the listed names
/// the client doesn't know (skipped). The strip's order doesn't matter.
pub fn match_layers(listed: &[String], names: &[&str], fallback: fn(&str) -> Option<&'static str>) -> (Vec<Option<usize>>, Vec<String>) {
    let find = |n: &str| listed.iter().position(|l| l == n);
    let slots = names.iter().map(|n| find(n).or_else(|| fallback(n).and_then(find))).collect();
    let unknown = listed.iter().filter(|l| !names.contains(&l.as_str())).cloned().collect();
    (slots, unknown)
}

/// A painted strip (`<name>.png`, paint.py) as a texture array with mipmaps, one layer per name
/// in `names`, matched by name against its layer list (`<name>.txt`, [`match_layers`]): layers
/// it lacks borrow their `fallback`'s or are flat mid-grey (no detail); layers the client doesn't
/// know are skipped. All flat if the strip is missing. The ground's layers, and the models'
/// surfaces (`style::DetailLayers`, no fallbacks).
pub fn load_array(name: &str, names: &[&str], fallback: fn(&str) -> Option<&'static str>) -> Image {
    let layers = names.len();
    let root = std::path::Path::new(&crate::lookdev::asset_root()).join(name);
    let (path, txt) = (root.with_extension("png"), root.with_extension("txt"));
    let sampler = ImageSampler::Descriptor(ImageSamplerDescriptor {
        address_mode_u: ImageAddressMode::Repeat,
        address_mode_v: ImageAddressMode::Repeat,
        mag_filter: ImageFilterMode::Linear,
        min_filter: ImageFilterMode::Linear,
        mipmap_filter: ImageFilterMode::Linear,
        anisotropy_clamp: 4,
        ..default()
    });
    let flat = || {
        let mut flat = Image::new_fill(Extent3d { width: 4, height: 4 * layers as u32, depth_or_array_layers: 1 }, bevy::render::render_resource::TextureDimension::D2, &[128, 128, 128, 128], bevy::render::render_resource::TextureFormat::Rgba8Unorm, RenderAssetUsages::RENDER_WORLD);
        flat.sampler = sampler.clone();
        let _ = flat.reinterpret_stacked_2d_as_array(layers as u32);
        flat
    };
    let listed: Vec<String> = std::fs::read_to_string(&txt).unwrap_or_default().lines().map(str::trim).filter(|l| !l.is_empty()).map(str::to_string).collect();
    let (slots, unknown) = match_layers(&listed, names, fallback);
    if slots.iter().all(Option::is_none) {
        warn!("textures: {} lists none of the layers {names:?} (run `just living-game-textures --set all`); drawn without detail", txt.display());
        return flat();
    }
    let image = std::fs::read(&path).ok().and_then(|bytes| match Image::from_buffer(&bytes, ImageType::Extension("png"), CompressedImageFormats::NONE, false, sampler.clone(), RenderAssetUsages::RENDER_WORLD) {
        Ok(i) => Some(i),
        Err(e) => {
            warn!("textures: {} unreadable ({e}); drawn without detail", path.display());
            None
        }
    });
    let Some(mut image) = image.filter(|i| i.height() == i.width() * listed.len() as u32 && i.data.as_ref().is_some_and(|d| d.len() == (i.width() * i.height() * 4) as usize)) else {
        warn!("textures: no {} with the {} layers {} lists (run `just living-game-textures --set all`); drawn without detail", path.display(), listed.len(), txt.display());
        return flat();
    };
    if !unknown.is_empty() {
        warn!("textures: {} has layers this client doesn't know, skipped: {unknown:?}", txt.display());
    }
    let missing: Vec<String> = names.iter().zip(&slots).filter(|(n, _)| !listed.iter().any(|l| l == *n)).map(|(n, s)| match s {
        Some(k) => format!("{n} (as {})", listed[*k]),
        None => format!("{n} (flat)"),
    }).collect();
    if !missing.is_empty() {
        info!("textures: {} lacks {} of the client's layers, drawn as others until it is painted again: {}", path.display(), missing.len(), missing.join(", "));
    }
    let size = image.width();
    let painted = image.data.take().unwrap_or_default();
    let layer_bytes = (size * size * 4) as usize;
    // Into the client's order; unchanged bytes when the strip lists exactly `names`.
    let mut base = Vec::with_capacity(layer_bytes * layers);
    for slot in &slots {
        match slot {
            Some(k) => base.extend_from_slice(&painted[k * layer_bytes..(k + 1) * layer_bytes]),
            None => base.extend(std::iter::repeat_n(128u8, layer_bytes)),
        }
    }
    image.texture_descriptor.size.height = size * layers as u32;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_layer_has_a_name_a_tile_and_the_cliff_comes_last() {
        for (k, l) in Layer::ALL.iter().enumerate() {
            assert_eq!(*l as usize, k);
            assert_eq!(Layer::from_name(l.name()), Some(*l));
        }
        assert_eq!(Layer::ALL[LAYERS - 1], Layer::Cliff);
        assert_eq!(Layer::from_name("no_such_layer"), None);
        // The new layers borrow one of the first sixteen until ground.png is painted again.
        for l in &Layer::ALL[15..24] {
            let f = fallback(l.name()).expect("a fallback");
            assert!((Layer::from_name(f).unwrap() as usize) < 15, "{l:?} falls back to {f}");
        }
        assert_eq!(fallback("grass"), None);
        assert_eq!(TILE[Layer::QuayFlags as usize], (4.8, 1.0));
        assert_eq!(TILE[Layer::Cliff as usize], (6.5, 1.0));
    }

    #[test]
    fn blends_pack_into_six_attributes() {
        let mut b = Blend::default();
        b.add(Layer::Grass, 1.0);
        b.add(Layer::Gravel, 1.0);
        b.add(Layer::SlateSetts, 1.0);
        b.add(Layer::ThinTurf, 1.0);
        // The cliff has no weight of its own (the vertex alpha).
        b.add(Layer::Cliff, 5.0);
        let p = b.pack();
        assert_eq!(p.len(), 6);
        assert_eq!(p[0], [64, 0, 0, 0]);
        assert_eq!(p[3], [0, 0, 64, 64], "gravel (14) and slate setts (15)");
        assert_eq!(p[5], [0, 0, 0, 64], "thin turf (23), the last weight");
        assert_eq!(Blend::one(Layer::Peat).pack()[5], [255, 0, 0, 0]);
        // Old layers pack into the first four attributes exactly as before.
        let old = Blend::one(Layer::DryGrass).toward(Layer::Rock, 0.25).pack();
        assert_eq!(old[0], [0, 0, 191, 0]);
        assert_eq!(old[1], [0, 0, 64, 0]);
        assert_eq!((old[4], old[5]), ([0; 4], [0; 4]));
        // The mesh gets six attributes of one entry per vertex.
        let mut mesh = Mesh::new(bevy::mesh::PrimitiveTopology::TriangleList, RenderAssetUsages::default()).with_inserted_attribute(Mesh::ATTRIBUTE_POSITION, vec![[0.0f32; 3]; 2]);
        insert_blend(&mut mesh, &[b, Blend::one(Layer::Cinders)]);
        for a in &ATTRIBUTE_BLEND {
            assert_eq!(mesh.attribute(a.id).map(|v| v.len()), Some(2));
        }
        let Some(VertexAttributeValues::Unorm8x4(e)) = mesh.attribute(ATTRIBUTE_BLEND[4].id) else { panic!("no fifth attribute") };
        assert_eq!(e[1], [0, 255, 0, 0], "cinders (17)");
    }

    #[test]
    fn painted_layers_are_matched_by_name() {
        let old: Vec<String> = NAMES.iter().filter(|n| fallback(n).is_none()).map(|s| s.to_string()).collect();
        assert_eq!(old.len(), 16);
        // Today's 16-layer strip: the old layers are their own, the new ones borrow, cliff is 15.
        let (slots, unknown) = match_layers(&old, &NAMES, fallback);
        assert!(unknown.is_empty());
        for k in 0..15 {
            assert_eq!(slots[k], Some(k));
        }
        assert_eq!(slots[Layer::SlateSetts as usize], Some(Layer::Cobble as usize));
        assert_eq!(slots[Layer::Peat as usize], Some(Layer::Mud as usize));
        assert_eq!(slots[Layer::Cliff as usize], Some(15));
        // kit-2's 25-layer strip: every layer its own.
        let all: Vec<String> = NAMES.iter().map(|s| s.to_string()).collect();
        assert_eq!(match_layers(&all, &NAMES, fallback).0, (0..LAYERS).map(Some).collect::<Vec<_>>());
        // Reordered, with a layer the client doesn't know and one missing with no fallback.
        let odd: Vec<String> = ["cliff", "moon_dust", "grass", "heather", "dry_grass"].iter().map(|s| s.to_string()).collect();
        let (slots, unknown) = match_layers(&odd, &NAMES, fallback);
        assert_eq!(unknown, vec!["moon_dust".to_string()]);
        assert_eq!(slots[Layer::Grass as usize], Some(2));
        assert_eq!(slots[Layer::Heather as usize], Some(3), "its own beats its fallback");
        assert_eq!(slots[Layer::Cliff as usize], Some(0));
        assert_eq!(slots[Layer::Rock as usize], None, "flat");
        assert_eq!(slots[Layer::ThinTurf as usize], Some(2), "as grass");
        // Materials have no fallbacks.
        assert_eq!(match_layers(&odd, &["plaster", "grass"], |_| None).0, vec![None, Some(2)]);
    }
}
