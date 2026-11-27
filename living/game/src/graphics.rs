//! Graphics quality tier and 3D render scaling (Step 4 of look-dev plan).
//!
//! - **Render scale ([`RenderScale`]):** renders the 3D scene (`Camera3d`, depth/normal prepass,
//!   shell outlines, `Edges`, `Bloom`, tonemapping, `Smaa`) into a scaled offscreen sRGB target and
//!   composites it onto the native output via a `Camera2d` + fullscreen [`UpscaleMaterial`] node
//!   (`upscale.wesl`: Catmull-Rom resampling plus light contrast-adaptive sharpening, so ink lines
//!   and eyes survive the non-integer stretch), keeping Bevy UI and HUD text razor-sharp at native
//!   resolution. At the default `100%` (or
//!   `Auto` at ≤1440 px height), no offscreen image or extra pass is created — `Camera3d` renders
//!   directly to the window or headless capture target, bit-for-bit identical to pre-Step-4 output.
//! - **Quality tier ([`Quality`]):** `Low`, `Medium`, or `High` (default). Controls bloom tier
//!   (`Full` / `Half` / `Off`), shadow-map resolution and cascade count, and carries the
//!   `crevice_ao` hook for Step 3. Every tier filters shadows `Gaussian` (look-dev 4b);
//!   `Hardware2x2` remains as a `LIVING_GAME_PERF=shadowfilter=hw` override.
//!
//! Environment overrides (for headless captures and `lookdev_shoot.py`):
//! - `LIVING_GAME_RENDER_SCALE=67|75|85|100|auto`
//! - `LIVING_GAME_QUALITY=low|medium|high`
//! - `LIVING_GAME_PERF` flags (`nobloom`, `bloom=full|half|quarter|off`,
//!   `shadowfilter=hw|gaussian`, `shadowmap=N`, `cascades=N`, `firstcascade=M`, `shadowfar=M`)
//!   always override [`Quality`] for isolated pass benchmarking; `upscale=bilinear` composites a
//!   scaled picture with plain bilinear filtering and `sharpen=S` sets the CAS sharpness (0–1,
//!   default [`Upscale::SHARPNESS`]), for A/B stills and cost measurement.

use bevy::asset::embedded_asset;
use bevy::camera::{ImageRenderTarget, RenderTarget};
use bevy::image::ImageSampler;
use bevy::light::{CascadeShadowConfig, CascadeShadowConfigBuilder, DirectionalLightShadowMap, ShadowFilteringMethod};
use bevy::post_process::bloom::Bloom;
use bevy::prelude::*;
use bevy::render::render_resource::{AsBindGroup, TextureFormat, TextureUsages};
use bevy::shader::ShaderRef;
use bevy::ui::{GlobalZIndex, IsDefaultUiCamera, UiSystems, UiTargetCamera};
use bevy::window::{PrimaryWindow, WindowRef};

/// 3D render scale (`Settings › Play › 3D render scale`, `LIVING_GAME_RENDER_SCALE`).
#[derive(Resource, Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum RenderScale {
    Pct67,
    Pct75,
    Pct85,
    #[default]
    Native,
    /// Caps 3D height near 1440 px on HiDPI displays (`(1440 / phys_h).clamp(0.67, 1.0)`).
    /// Stays at native 100% (zero extra pass) when output height ≤ 1440 px.
    Auto,
}

impl RenderScale {
    pub const ALL: [RenderScale; 5] = [
        RenderScale::Pct67,
        RenderScale::Pct75,
        RenderScale::Pct85,
        RenderScale::Native,
        RenderScale::Auto,
    ];

    /// Target vertical cap (physical px) for [`RenderScale::Auto`].
    pub const AUTO_CAP_HEIGHT: u32 = 1440;

    pub fn parse(s: &str) -> Option<RenderScale> {
        match s.trim().to_ascii_lowercase().as_str() {
            "67" | "67%" | "0.67" => Some(RenderScale::Pct67),
            "75" | "75%" | "0.75" => Some(RenderScale::Pct75),
            "85" | "85%" | "0.85" => Some(RenderScale::Pct85),
            "100" | "100%" | "1.0" | "1" | "native" => Some(RenderScale::Native),
            "auto" => Some(RenderScale::Auto),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            RenderScale::Pct67 => "67",
            RenderScale::Pct75 => "75",
            RenderScale::Pct85 => "85",
            RenderScale::Native => "100",
            RenderScale::Auto => "auto",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            RenderScale::Pct67 => "67%",
            RenderScale::Pct75 => "75%",
            RenderScale::Pct85 => "85%",
            RenderScale::Native => "100%",
            RenderScale::Auto => "Auto",
        }
    }

    pub fn from_env() -> Option<RenderScale> {
        std::env::var("LIVING_GAME_RENDER_SCALE").ok().and_then(|v| RenderScale::parse(&v))
    }

    /// Effective linear scale factor for an output target of `output_physical` pixels.
    pub fn effective_factor(self, output_physical: UVec2) -> f32 {
        match self {
            RenderScale::Pct67 => 0.67,
            RenderScale::Pct75 => 0.75,
            RenderScale::Pct85 => 0.85,
            RenderScale::Native => 1.0,
            RenderScale::Auto => {
                if output_physical.y > Self::AUTO_CAP_HEIGHT {
                    (Self::AUTO_CAP_HEIGHT as f32 / output_physical.y as f32).clamp(0.67, 1.0)
                } else {
                    1.0
                }
            }
        }
    }

    /// Scaled 3D render target size in physical pixels, or `None` when native (100%) applies.
    pub fn scaled_size(self, output_physical: UVec2) -> Option<UVec2> {
        if output_physical.x == 0 || output_physical.y == 0 {
            return None;
        }
        let f = self.effective_factor(output_physical);
        if f >= 0.999 {
            return None;
        }
        let w = ((output_physical.x as f32 * f).round() as u32).clamp(1, output_physical.x);
        let h = ((output_physical.y as f32 * f).round() as u32).clamp(1, output_physical.y);
        if w == output_physical.x && h == output_physical.y {
            return None;
        }
        Some(UVec2::new(w, h))
    }
}

/// Bloom resolution tier controlled by [`Quality`] (or `LIVING_GAME_PERF=bloom=...`).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum BloomTier {
    /// Today's full `Bloom::NATURAL` (`max_mip_dimension = 512`).
    Full,
    /// Half-resolution mip chain (`max_mip_dimension = 256`).
    Half,
    /// Quarter-resolution mip chain (`max_mip_dimension = 128`).
    Quarter,
    /// Bloom component removed from `Camera3d`.
    Off,
}

impl BloomTier {
    pub fn parse(s: &str) -> Option<BloomTier> {
        match s.trim().to_ascii_lowercase().as_str() {
            "full" | "high" | "512" => Some(BloomTier::Full),
            "half" | "medium" | "256" => Some(BloomTier::Half),
            "quarter" | "128" => Some(BloomTier::Quarter),
            "off" | "none" | "0" => Some(BloomTier::Off),
            _ => None,
        }
    }

    pub fn max_mip_dimension(self) -> Option<u32> {
        match self {
            BloomTier::Full => Some(512),
            BloomTier::Half => Some(256),
            BloomTier::Quarter => Some(128),
            BloomTier::Off => None,
        }
    }
}

/// Quality tier (`Settings › Play › Quality`, `LIVING_GAME_QUALITY`).
#[derive(Resource, Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Quality {
    Low,
    Medium,
    #[default]
    High,
}

/// Concrete rendering parameters for a [`Quality`] tier.
#[derive(Clone, Copy, PartialEq, Debug)]
pub struct QualityProfile {
    pub bloom: BloomTier,
    pub shadow_filter: ShadowFilteringMethod,
    pub shadow_map_size: usize,
    pub cascades: usize,
    pub first_cascade_far: f32,
    pub shadow_far: f32,
    /// Reserved hook for Step 3's depth-buffer crevice AO in `edges.wesl`.
    pub crevice_ao: bool,
}

impl Quality {
    pub const ALL: [Quality; 3] = [Quality::Low, Quality::Medium, Quality::High];

    pub fn parse(s: &str) -> Option<Quality> {
        match s.trim().to_ascii_lowercase().as_str() {
            "low" => Some(Quality::Low),
            "medium" | "med" => Some(Quality::Medium),
            "high" => Some(Quality::High),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Quality::Low => "low",
            Quality::Medium => "medium",
            Quality::High => "high",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Quality::Low => "Low",
            Quality::Medium => "Medium",
            Quality::High => "High",
        }
    }

    pub fn from_env() -> Option<Quality> {
        std::env::var("LIVING_GAME_QUALITY").ok().and_then(|v| Quality::parse(&v))
    }

    /// Parameters for this quality tier. `High` matches `origin/main` defaults exactly.
    pub fn profile(self) -> QualityProfile {
        let s = crate::world::SHADOWS;
        match self {
            Quality::High => QualityProfile {
                bloom: BloomTier::Full,
                shadow_filter: ShadowFilteringMethod::Gaussian,
                shadow_map_size: 2048,
                cascades: s.cascades,
                first_cascade_far: s.first_far,
                shadow_far: s.far,
                crevice_ao: true,
            },
            // Gaussian on every tier (look-dev 4b): Hardware2x2 stair-stepped limb and building
            // shadows at noon and dusk (and blotched Low's 1024 px self-shadowing) to save 0.16 ms
            // at Medium + Auto and 0.41 ms at Low at 3024x1964; half-res bloom is visually free.
            Quality::Medium => QualityProfile {
                bloom: BloomTier::Half,
                shadow_filter: ShadowFilteringMethod::Gaussian,
                shadow_map_size: 2048,
                cascades: 2,
                first_cascade_far: s.first_far,
                shadow_far: 72.0,
                crevice_ao: false,
            },
            Quality::Low => QualityProfile {
                bloom: BloomTier::Off,
                shadow_filter: ShadowFilteringMethod::Gaussian,
                shadow_map_size: 1024,
                cascades: 2,
                first_cascade_far: 16.0,
                shadow_far: 60.0,
                crevice_ao: false,
            },
        }
    }

    /// Whether Step 3's crevice AO is enabled at this tier.
    #[allow(dead_code)]
    pub fn crevice_ao(self) -> bool {
        self.profile().crevice_ao
    }
}

/// Marker for the native-resolution 2D camera that composites the scaled 3D image and hosts UI.
#[derive(Component)]
pub struct ScaledCompositeCamera;

/// Marker for the fullscreen UI node that displays the scaled 3D render target.
#[derive(Component)]
struct ScaledBackdrop;

/// How a scaled 3D picture is drawn onto the native output (`upscale.wesl`).
#[derive(Resource, Clone, Copy, PartialEq, Debug)]
pub struct Upscale {
    /// Catmull-Rom + CAS (true), or plain bilinear (`LIVING_GAME_PERF=upscale=bilinear`, A/B only).
    pub sharpen: bool,
    /// CAS sharpness, 0 (least) to 1 (most).
    pub sharpness: f32,
    /// Whether a scaled picture is being composited now (false at 100%: no extra pass).
    pub active: bool,
    /// Effective 3D render-scale factor (`1.0` at native 100%; `scaled_h / output_h` when scaled).
    pub factor: f32,
}

impl Upscale {
    /// Default CAS sharpness: AMD's lightest (0 still sharpens, a peak of -1/8). On live 2x
    /// captures (look-dev 4b) Catmull-Rom with it brought Auto's line and eye detail back to 100%
    /// (Laplacian 0.99-1.15x of 100%, bilinear 0.53-0.65x); 0.3 overshot (up to 1.32x, beading).
    pub const SHARPNESS: f32 = 0.0;

    fn from_env() -> Upscale {
        let bilinear = crate::perf::string("upscale").is_some_and(|v| v.eq_ignore_ascii_case("bilinear"));
        let sharpness = crate::perf::value("sharpen").map_or(Self::SHARPNESS, |v| v.clamp(0.0, 1.0));
        Upscale { sharpen: !bilinear, sharpness, active: false, factor: 1.0 }
    }

    pub fn method(self) -> &'static str {
        if self.sharpen { "catmull-rom+cas" } else { "bilinear" }
    }

    fn params(self) -> Vec4 {
        Vec4::new(self.sharpness, if self.sharpen { 1.0 } else { 0.0 }, 0.0, 0.0)
    }
}

/// The compositing material: the scaled 3D image, resampled and sharpened (`upscale.wesl`).
#[derive(Asset, TypePath, AsBindGroup, Clone)]
pub struct UpscaleMaterial {
    #[uniform(0)]
    params: Vec4,
    #[texture(1)]
    #[sampler(2)]
    source: Handle<Image>,
}

impl UiMaterial for UpscaleMaterial {
    fn fragment_shader() -> ShaderRef {
        "embedded://living_game/upscale.wesl".into()
    }
}

#[derive(Resource, Default)]
struct ScaleState {
    rig: Option<ScaledRig>,
}

struct ScaledRig {
    image: Handle<Image>,
    material: Handle<UpscaleMaterial>,
    scaled_px: UVec2,
    output_px: UVec2,
    output_scale_bits: u32,
    composite_cam: Entity,
    backdrop: Entity,
}

/// Choose the active UI camera (preferring [`IsDefaultUiCamera`], falling back to `Camera3d`).
pub fn ui_camera<'a>(cams: impl Iterator<Item = (&'a Camera, bool)>) -> Option<&'a Camera> {
    let mut fallback = None;
    for (cam, is_default) in cams {
        if is_default {
            return Some(cam);
        }
        if fallback.is_none() {
            fallback = Some(cam);
        }
    }
    fallback
}

pub struct GraphicsPlugin;

impl Plugin for GraphicsPlugin {
    fn build(&self, app: &mut App) {
        let quality = Quality::from_env().unwrap_or_default();
        let render_scale = RenderScale::from_env().unwrap_or_default();
        let upscale = Upscale::from_env();
        info!("graphics: quality {}, render scale {}, upscale {} {:.2}", quality.name(), render_scale.name(), upscale.method(), upscale.sharpness);
        embedded_asset!(app, "upscale.wesl");
        app.add_plugins(UiMaterialPlugin::<UpscaleMaterial>::default())
            .insert_resource(quality)
            .insert_resource(render_scale)
            .insert_resource(upscale)
            .init_resource::<ScaleState>()
            .add_systems(
                PostUpdate,
                (
                    sync_render_scale
                        .after(crate::capture::attach)
                        .before(crate::post::update)
                        .before(UiSystems::Prepare),
                    apply_quality
                        .after(crate::perf::apply)
                        .before(crate::post::update),
                ),
            );
    }
}

/// Keep the 3D render target and native-resolution compositing camera in step with [`RenderScale`]
/// and window/headless target size.
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn sync_render_scale(
    mut commands: Commands,
    render_scale: Res<RenderScale>,
    mut state: ResMut<ScaleState>,
    mut images: ResMut<Assets<Image>>,
    mut materials: ResMut<Assets<UpscaleMaterial>>,
    mut upscale: ResMut<Upscale>,
    capture: Option<Res<crate::capture::Target>>,
    windows: Query<&Window, With<PrimaryWindow>>,
    mut cam3d: Query<(Entity, &mut Camera, &mut RenderTarget), (With<Camera3d>, Without<ScaledCompositeCamera>)>,
) {
    let Ok((cam_e, mut cam, mut cam_target)) = cam3d.single_mut() else { return };

    let (output_target, output_px, output_scale) = if let Some(cap) = capture.as_ref() {
        (RenderTarget::Image(cap.0.clone().into()), crate::capture::size(), 1.0f32)
    } else if let Ok(win) = windows.single() {
        let px = UVec2::new(win.physical_width(), win.physical_height());
        (RenderTarget::Window(WindowRef::Primary), px, win.scale_factor())
    } else {
        return;
    };

    if output_px.x == 0 || output_px.y == 0 {
        return;
    }

    let want = render_scale.scaled_size(output_px);
    let Some(scaled_px) = want else {
        // Native 100%: tear down scaled rig if one was active; otherwise zero overhead.
        if let Some(rig) = state.rig.take() {
            commands.entity(rig.backdrop).despawn();
            commands.entity(rig.composite_cam).despawn();
            images.remove(&rig.image);
            materials.remove(&rig.material);
            upscale.active = false;
            upscale.factor = 1.0;
            *cam_target = output_target;
            cam.order = 0;
            if !crate::view::enabled() {
                commands.entity(cam_e).insert(IsDefaultUiCamera);
            }
            info!("graphics: render scale native ({}x{})", output_px.x, output_px.y);
        }
        return;
    };

    let output_scale_bits = output_scale.to_bits();
    if let Some(rig) = state.rig.as_ref() {
        if rig.scaled_px == scaled_px && rig.output_px == output_px && rig.output_scale_bits == output_scale_bits {
            return;
        }
    }

    let mut image = Image::new_target_texture(scaled_px.x, scaled_px.y, TextureFormat::Rgba8UnormSrgb, None);
    image.texture_descriptor.usage |= TextureUsages::TEXTURE_BINDING | TextureUsages::COPY_SRC;
    image.sampler = ImageSampler::linear();
    let handle = images.add(image);

    // Match the output target's logical viewport height so world_to_viewport, viewport_to_world,
    // edge widths and shell outline widths stay in the exact same logical coordinate space.
    let actual_scale = scaled_px.y as f32 / output_px.y as f32;
    let target_scale_factor = (output_scale * actual_scale).max(0.01);

    *cam_target = RenderTarget::Image(ImageRenderTarget {
        handle: handle.clone(),
        scale_factor: target_scale_factor,
    });
    cam.order = 0;
    commands.entity(cam_e).remove::<IsDefaultUiCamera>();

    upscale.active = true;
    upscale.factor = actual_scale;
    if let Some(rig) = state.rig.as_mut() {
        let old = std::mem::replace(&mut rig.image, handle.clone());
        images.remove(&old);
        rig.scaled_px = scaled_px;
        rig.output_px = output_px;
        rig.output_scale_bits = output_scale_bits;
        if let Some(mut m) = materials.get_mut(&rig.material) {
            m.source = handle;
        }
    } else {
        let material = materials.add(UpscaleMaterial { params: upscale.params(), source: handle.clone() });
        let composite_cam = commands
            .spawn((
                ScaledCompositeCamera,
                Camera2d,
                Camera {
                    order: 1,
                    clear_color: ClearColorConfig::Custom(Color::BLACK),
                    ..default()
                },
                Msaa::Off,
                IsDefaultUiCamera,
                output_target,
            ))
            .id();
        let backdrop = commands
            .spawn((
                ScaledBackdrop,
                UiTargetCamera(composite_cam),
                Node {
                    position_type: PositionType::Absolute,
                    left: Val::Px(0.0),
                    top: Val::Px(0.0),
                    width: Val::Percent(100.0),
                    height: Val::Percent(100.0),
                    ..default()
                },
                MaterialNode(material.clone()),
                GlobalZIndex(-10_000),
                Pickable::IGNORE,
            ))
            .id();
        state.rig = Some(ScaledRig {
            image: handle,
            material,
            scaled_px,
            output_px,
            output_scale_bits,
            composite_cam,
            backdrop,
        });
    }
    info!(
        "graphics: render scale {} ({}x{} -> {}x{}, factor {:.3}, upscale {} {:.2})",
        render_scale.name(),
        scaled_px.x,
        scaled_px.y,
        output_px.x,
        output_px.y,
        actual_scale,
        upscale.method(),
        upscale.sharpness,
    );
}

fn effective_bloom(quality: Quality) -> BloomTier {
    if crate::perf::has("nobloom") {
        return BloomTier::Off;
    }
    if let Some(v) = crate::perf::string("bloom").and_then(|s| BloomTier::parse(&s)) {
        return v;
    }
    quality.profile().bloom
}

fn effective_shadow_filter(quality: Quality) -> ShadowFilteringMethod {
    if let Some(v) = crate::perf::string("shadowfilter") {
        match v.to_ascii_lowercase().as_str() {
            "hw" | "hw2x2" | "hardware2x2" => return ShadowFilteringMethod::Hardware2x2,
            "gaussian" => return ShadowFilteringMethod::Gaussian,
            "temporal" => return ShadowFilteringMethod::Temporal,
            _ => {}
        }
    }
    quality.profile().shadow_filter
}

fn effective_shadow_map_size(quality: Quality) -> usize {
    if let Some(n) = crate::perf::value("shadowmap") {
        return (n as usize).max(256);
    }
    quality.profile().shadow_map_size
}

fn effective_cascades(quality: Quality) -> (usize, f32, f32) {
    let p = quality.profile();
    let cascades = crate::perf::value("cascades").map_or(p.cascades, |n| (n as usize).max(1));
    let first_far = crate::perf::value("firstcascade").unwrap_or(p.first_cascade_far);
    let far = crate::perf::value("shadowfar").unwrap_or(p.shadow_far);
    (cascades, first_far, far)
}

/// Apply [`Quality`] (and any `LIVING_GAME_PERF` overrides) to bloom, shadow filtering, shadow-map
/// resolution and shadow cascades. Only writes components/resources when values actually differ so
/// the default `Quality::High` performs zero mutations against `origin/main`.
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn apply_quality(
    mut commands: Commands,
    quality: Res<Quality>,
    mut shadow_map: ResMut<DirectionalLightShadowMap>,
    mut suns: Query<&mut CascadeShadowConfig, With<DirectionalLight>>,
    mut cams: Query<(Entity, Has<bevy::camera::Hdr>, Option<&mut Bloom>, Option<&ShadowFilteringMethod>), With<Camera3d>>,
    mut last_cascades: Local<Option<(usize, u32, u32)>>,
) {
    let want_map = effective_shadow_map_size(*quality);
    if shadow_map.size != want_map {
        shadow_map.size = want_map;
    }

    let (cascades, first_far, far) = effective_cascades(*quality);
    let cascade_key = (cascades, first_far.to_bits(), far.to_bits());
    let default_s = crate::world::SHADOWS;
    let is_default_cascades = cascades == default_s.cascades
        && first_far.to_bits() == default_s.first_far.to_bits()
        && far.to_bits() == default_s.far.to_bits();
    let need_cascade_write = match *last_cascades {
        None => !is_default_cascades,
        Some(prev) => prev != cascade_key,
    };
    if need_cascade_write && !suns.is_empty() {
        let cfg = CascadeShadowConfigBuilder {
            num_cascades: cascades,
            first_cascade_far_bound: first_far,
            maximum_distance: far,
            ..default()
        }
        .build();
        for mut sun in &mut suns {
            *sun = cfg.clone();
        }
        *last_cascades = Some(cascade_key);
    }

    let want_filter = effective_shadow_filter(*quality);
    let want_bloom = effective_bloom(*quality);

    for (e, has_hdr, bloom, filter) in &mut cams {
        let current_filter = filter.copied().unwrap_or_default();
        if current_filter != want_filter {
            commands.entity(e).insert(want_filter);
        }
        match (want_bloom.max_mip_dimension(), bloom) {
            (None, Some(_)) => {
                commands.entity(e).remove::<Bloom>();
            }
            (Some(dim), Some(mut b)) => {
                if b.max_mip_dimension != dim {
                    b.max_mip_dimension = dim;
                }
            }
            (Some(dim), None) if has_hdr => {
                commands.entity(e).insert(Bloom {
                    intensity: 0.12,
                    max_mip_dimension: dim,
                    ..Bloom::NATURAL
                });
            }
            _ => {}
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_match_pre_step4_main() {
        assert_eq!(RenderScale::default(), RenderScale::Native);
        assert_eq!(Quality::default(), Quality::High);

        let high = Quality::High.profile();
        assert_eq!(high.bloom, BloomTier::Full);
        assert_eq!(high.bloom.max_mip_dimension(), Some(512));
        assert_eq!(high.shadow_filter, ShadowFilteringMethod::Gaussian);
        assert_eq!(high.shadow_map_size, 2048);
        assert_eq!(high.cascades, crate::world::SHADOWS.cascades);
        assert_eq!(high.first_cascade_far, crate::world::SHADOWS.first_far);
        assert_eq!(high.shadow_far, crate::world::SHADOWS.far);
        assert!(high.crevice_ao);

        assert_eq!(RenderScale::Native.scaled_size(UVec2::new(3024, 1964)), None);
        assert_eq!(RenderScale::Native.scaled_size(UVec2::new(1920, 1080)), None);
    }

    #[test]
    fn render_scale_sizes_and_auto_cap() {
        let native = UVec2::new(3024, 1964);
        assert_eq!(RenderScale::Pct85.scaled_size(native), Some(UVec2::new(2570, 1669)));
        assert_eq!(RenderScale::Pct75.scaled_size(native), Some(UVec2::new(2268, 1473)));
        assert_eq!(RenderScale::Pct67.scaled_size(native), Some(UVec2::new(2026, 1316)));

        // Auto caps near 1440p on Retina, stays native at 1080p and 1440p.
        let auto_retina = RenderScale::Auto.scaled_size(native).unwrap();
        assert_eq!(auto_retina.y, 1440);
        assert!((auto_retina.x as f32 / auto_retina.y as f32 - 3024.0 / 1964.0).abs() < 0.002);
        assert_eq!(RenderScale::Auto.scaled_size(UVec2::new(1920, 1080)), None);
        assert_eq!(RenderScale::Auto.scaled_size(UVec2::new(2560, 1440)), None);
    }

    #[test]
    fn quality_tiers_step_down_cleanly() {
        let med = Quality::Medium.profile();
        assert_eq!(med.bloom, BloomTier::Half);
        assert_eq!(med.bloom.max_mip_dimension(), Some(256));
        assert_eq!(med.shadow_filter, ShadowFilteringMethod::Gaussian);
        assert_eq!(med.cascades, 2);
        assert!(!med.crevice_ao);

        let low = Quality::Low.profile();
        assert_eq!(low.bloom, BloomTier::Off);
        assert_eq!(low.bloom.max_mip_dimension(), None);
        assert_eq!(low.shadow_filter, ShadowFilteringMethod::Gaussian);
        assert_eq!(low.shadow_map_size, 1024);
        assert_eq!(low.cascades, 2);
        assert!(!low.crevice_ao);
    }

    #[test]
    fn parse_round_trips() {
        for q in Quality::ALL {
            assert_eq!(Quality::parse(q.name()), Some(q));
        }
        assert_eq!(Quality::parse("MED"), Some(Quality::Medium));
        assert_eq!(Quality::parse("ultra"), None);

        for s in RenderScale::ALL {
            assert_eq!(RenderScale::parse(s.name()), Some(s));
        }
        assert_eq!(RenderScale::parse("75%"), Some(RenderScale::Pct75));
        assert_eq!(RenderScale::parse("0.85"), Some(RenderScale::Pct85));
        assert_eq!(RenderScale::parse("native"), Some(RenderScale::Native));
        assert_eq!(RenderScale::parse("50"), None);
    }
}
