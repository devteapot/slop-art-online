//! The finishing pass (`edges.wesl`): edge lines from the depth and normal prepasses, a
//! screen-space rim light and the film gradient; with the atmosphere (daylight.rs) also drifting
//! fog banks (marched through the depth to each pixel) and rain streaks in layers that stop at
//! nearer things. Structured after Bevy 0.20's
//! `custom_post_processing` example: settings are a camera component extracted to the render
//! world; a render system draws a full-screen triangle in `Core3dSystems::PostProcess`.

use bevy::asset::embedded_asset;
use bevy::core_pipeline::{prepass::ViewPrepassTextures, schedule::Core3d, Core3dSystems, FullscreenShader};
use bevy::prelude::*;
use bevy::render::{
    extract_component::{ComponentUniforms, DynamicUniformIndex, ExtractComponent, ExtractComponentPlugin, UniformComponentPlugin},
    render_resource::{
        binding_types::{sampler, texture_2d, texture_depth_2d, uniform_buffer},
        *,
    },
    render_asset::RenderAssets,
    renderer::{RenderContext, RenderDevice, ViewQuery},
    texture::{FallbackImage, GpuImage},
    view::ViewTarget,
    RenderApp, RenderStartup,
};

/// Finishing settings, on the camera (the render world reads a copy each frame).
#[derive(Component, Default, Clone, Copy, ExtractComponent, ShaderType)]
#[extract_app(RenderApp)]
pub struct Edges {
    pub line: Vec4,
    pub params: Vec4,
    pub fade: Vec4,
    pub rim: Vec4,
    pub sun: Vec4,
    pub grade: Vec4,
    pub screen: Vec4,
    /// World position from clip position (fog banks reconstruct points along each pixel's ray).
    pub world_from_clip: Mat4,
    /// xyz: camera position, w: the shader clock (wrapped seconds).
    pub eye: Vec4,
    /// Fog banks: x density (0 = none), y the ground level they lie on, z their depth (m),
    /// w how far they are marched (m).
    pub bank: Vec4,
    /// rgb: fog bank colour (linear), a: drift along x.
    pub bank_color: Vec4,
    /// Rain: x amount (0 = none), y slant, z brightness, w drift along z (fog banks).
    pub rain: Vec4,
    /// The edge of my sight (`sightedge.rs`): xy where I stand (world x, z), z the radius (m),
    /// w the mode (0 fade only, 1 not seen now, 2 limited view).
    pub sight: Vec4,
    /// Not seen now: x, y the soft band inside and beyond the radius (m), z dimming,
    /// w desaturation.
    pub sight_look: Vec4,
    /// rgb: the fog's colour (linear), a: how far not seen now is flattened toward it.
    pub sight_fog: Vec4,
    /// x: where limited view is fully fogged, times the radius; y: how far limited view fogs
    /// what lies behind something (0–1).
    pub sight_far: Vec4,
    /// Where my sight lines reach (`sightfield.rs`): xy the world x, z of the field texture's
    /// corner, z one over its side (m), w 1 when it holds a field.
    pub sight_field: Vec4,
    /// x: how "not seen now" is drawn (`sightedge::Look`: 0 grey, 1 wash, 2 lantern, 3 shadows,
    /// 4 hatch, 5 memory); y: how light the scene is (0 night, 1 day); z: 1 when the memory
    /// texture is current.
    pub sight_extra: Vec4,
    /// The scene's shadow tone for the shade look: x the target hue (the sky fill's, else the
    /// style's `shadow_hue`), y `hue_shift`, z `shadow_saturation`, w `shadow_depth`.
    pub sight_shade: Vec4,
    /// rgb: the style's `shadow_tint`.
    pub sight_tint: Vec4,
    /// The film ([`Film`]): x 0 screen, 1 soft (weighted by the pixel's light); y, z: the
    /// luminance (linear) over which soft goes from none of the film to all of it; w how much
    /// soft spares dark pixels now (1 by day, 0 by night: [`soft_by_light`]).
    pub film: Vec4,
    /// Look-dev Step 3 (all zero in Classic, which compiles without `LOOKDEV` or `CREVICE_AO`):
    /// Crevice AO: x strength (0 off), y world radius (m), z fade start (m), w fade end (m).
    pub ld_ao: Vec4,
    /// Crevice AO: rgb cool shadow-hue multiply target (linear), a projection scale (px/m at 1 m or ortho).
    pub ld_ao_color: Vec4,
    /// Camera right (xyz) and w: tan(fov_x / 2) (perspective) or half_w (ortho).
    pub ld_view_x: Vec4,
    /// Camera up (xyz) and w: tan(fov_y / 2) (perspective) or half_h (ortho).
    pub ld_view_y: Vec4,
    /// Camera back / -forward (xyz) and w: 1 when Look-dev is active, 0 in Classic.
    pub ld_view_z: Vec4,
    /// Aerial depth haze: rgb cool mist colour (linear), a max opacity.
    pub ld_aerial: Vec4,
    /// Aerial depth & grade split: x haze start (m), y haze end (m), z shadow split strength, w highlight split strength.
    pub ld_aerial_range: Vec4,
    /// Split-tone: rgb cool shadow hue target (linear; luminance restored after), a unused.
    pub ld_split_shadow: Vec4,
    /// Split-tone: rgb clean highlight multiply target (linear), a unused.
    pub ld_split_high: Vec4,
}

/// The film finish (`edges.wesl`): a warm gradient from the top of the frame. Settings › Play ›
/// Film; kept in the settings file only once chosen there, so a viewer who never chose one
/// follows this default. `LIVING_GAME_FILM=soft|screen|off` starts in one (headless captures).
#[derive(Resource, Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Film {
    /// The screen blend weighted by the pixel's own light: the sky and lit things take it as
    /// the screen did; dark hair, cloth and shadows keep their colour (film-1, 2026-11-12). By
    /// day only: at night it is the screen, the moonlit haze the night look is built on. A
    /// tint (`color * (1 + g)`) was tried and dropped: it moved the sky and greens and pushed
    /// skin orange.
    #[default]
    Soft,
    /// The screen blend on every pixel, as before film-1: it lifts dark pixels most.
    Screen,
    Off,
}

impl Film {
    pub const ALL: [Film; 3] = [Film::Soft, Film::Screen, Film::Off];

    pub fn parse(s: &str) -> Option<Film> {
        match s {
            "soft" => Some(Film::Soft),
            "screen" | "today" => Some(Film::Screen),
            "off" | "none" => Some(Film::Off),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Film::Soft => "soft",
            Film::Screen => "screen",
            Film::Off => "off",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Film::Soft => "Soft",
            Film::Screen => "Full",
            Film::Off => "None",
        }
    }

    pub fn from_env() -> Option<Film> {
        std::env::var("LIVING_GAME_FILM").ok().and_then(|v| Film::parse(&v))
    }
}

/// Colour grade under the look-dev light (`Settings › Play › Colour grade`, Step 3.2):
/// drives Bevy `ColorGrading`, split-tone warmth/coolness, and calibrated Bloom only when
/// `style::Look::Lookdev` is active; Classic ignores it completely.
/// `LIVING_GAME_GRADE=natural|vivid|soft` starts in one.
#[derive(Resource, Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Grade {
    /// Balanced Blue Protocol / SUPERVIVE anime clarity: clean highlights, anchored blacks,
    /// subtle cool shadows against the warm key, natural skin tones and night legibility.
    #[default]
    Natural,
    /// Punchier anime contrast, richer chroma and stronger warm/cool split-toning.
    Vivid,
    /// Gentler, calmer contrast and subtler split-toning closer to Classic's tonal range.
    Soft,
}

impl Grade {
    pub const ALL: [Grade; 3] = [Grade::Natural, Grade::Vivid, Grade::Soft];

    pub fn parse(s: &str) -> Option<Grade> {
        match s.trim().to_ascii_lowercase().as_str() {
            "natural" => Some(Grade::Natural),
            "vivid" => Some(Grade::Vivid),
            "soft" => Some(Grade::Soft),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Grade::Natural => "natural",
            Grade::Vivid => "vivid",
            Grade::Soft => "soft",
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Grade::Natural => "Natural",
            Grade::Vivid => "Vivid",
            Grade::Soft => "Soft",
        }
    }

    pub fn from_env() -> Option<Grade> {
        std::env::var("LIVING_GAME_GRADE").ok().and_then(|v| Grade::parse(&v))
    }

    fn bloom_scale(self) -> f32 {
        match self {
            Grade::Natural => 1.0,
            Grade::Vivid => 1.15,
            Grade::Soft => 0.85,
        }
    }
}

/// Look-dev Bloom prefilter calibration (Step 3.2), by day and at dusk: catches the sun's core and
/// bright sun rims without blooming grey stone or the bright dusk sky round a low sun, which at
/// 1.05 flooded foreground silhouettes (pass 2).
pub(crate) const LD_BLOOM_THRESHOLD: f32 = 1.60;
/// At full night, a lower threshold for the lanterns' glow (emissive at 6x their glow).
const LD_BLOOM_THRESHOLD_NIGHT: f32 = 1.05;
/// Look-dev bloom intensity relative to the profile's (`Grade::bloom_scale` on top), by day and
/// at full night. Threshold and intensity are uniforms: varying them with the hour never compiles
/// a bloom pipeline (the threshold stays above 0, so the prefilter key holds).
const LD_BLOOM_GAIN: f32 = 0.75;
const LD_BLOOM_GAIN_NIGHT: f32 = 1.30;
pub(crate) const LD_BLOOM_SOFTNESS: f32 = 0.35;

/// Time-of-day factors `(day, dusk, night)` derived from `Atmo` for Look-dev Step 3 grading,
/// aerial depth and crevice AO.
fn tod_weights(atmo: Option<&crate::daylight::Atmo>) -> (f32, f32, f32, f32) {
    let Some(a) = atmo else {
        return (1.0, 0.0, 0.0, 0.72);
    };
    let day = ((a.lux - 2800.0) / (9000.0 - 2800.0)).clamp(0.0, 1.0);
    let l = Color::srgb(a.light[0], a.light[1], a.light[2]).to_linear();
    let lum = (0.2126 * l.red + 0.7152 * l.green + 0.0722 * l.blue).max(1e-4);
    let warm = (((l.red - l.blue) / lum - 0.14) / 0.32).clamp(0.0, 1.0);
    let dusk = warm * (1.0 - (day - 0.55).abs().min(0.55) / 0.55 * 0.45);
    let night = (1.0 - day).clamp(0.0, 1.0);
    (day, dusk, night, a.shadow_hue)
}

/// How fully it is night with no dusk left (0 by day and at dusk, 1 at full night).
fn full_night(dusk: f32, night: f32) -> f32 {
    (night - dusk).clamp(0.0, 1.0)
}

/// Look-dev Bevy `ColorGrading` driven by `Atmo` and [`Grade`] (Step 3.2).
///
/// Uses `ColorGrading::with_identical_sections` so `shadows == midtones == highlights`: Bevy
/// 0.20.1's `tonemapping.wesl:334` has a typo (`levels.z = 1.0 - levels.y` instead of `levels.x`)
/// in the shadow-to-midtone crossfade band, which would otherwise create a sharp luminance step at
/// `level = midtone_range.x - 0.1` whenever shadows and highlights differ. Keeping all three
/// sections identical eliminates that artefact completely while driving gamma/gain/lift,
/// exposure, white balance and post_saturation inside Bevy's existing tonemapping pass; cool-shadow
/// vs warm-highlight RGB split-toning complements it in `edges.wesl`.
///
/// Pipeline invariance: every hour and every `Grade` keeps `SECTIONAL_COLOR_GRADING` and
/// `WHITE_BALANCE` active, so tonemapping never compiles a new pipeline mid-play as the clock runs.
pub(crate) fn ld_color_grading(atmo: Option<&crate::daylight::Atmo>, grade: Grade, base_sat: f32) -> bevy::render::view::ColorGrading {
    use bevy::render::view::{ColorGrading, ColorGradingGlobal, ColorGradingSection};
    let (day, dusk, night, _) = tod_weights(atmo);
    let (g_off, gain_off, sat_off) = match grade {
        Grade::Natural => (0.0, 0.0, 0.0),
        Grade::Vivid => (-0.018, 0.040, 0.11),
        Grade::Soft => (0.012, -0.030, -0.08),
    };
    // Bevy raises to 1 / gamma: below 1 deepens the darks. Kept close to 1 and with no negative
    // lift, so dark boots, trousers, hair and shadowed cloth keep their cel shading (pass 2: the
    // stacked lift, toe and low gamma clipped them to black by day and at dusk).
    let gamma = (0.992 - 0.006 * day - 0.004 * dusk + g_off).clamp(0.90, 1.04);
    let gain = (1.032 + 0.014 * day + 0.012 * dusk + gain_off).clamp(0.98, 1.12);
    // A small positive lift by day and at dusk anchors the darks above black. Look-dev's bloom is
    // additive with a threshold, so it no longer lays the faint veil over dark pixels that main's
    // energy-conserving, unthresholded bloom does (measured in pass 2: that veil, not the grade,
    // was what kept boots and dark cloth above luma 5). Gone by full night, which never crushed.
    let lift = 0.0022 * (1.0 - full_night(dusk, night));
    // More light by day, for what taming the soft film took from sunlit stone.
    let exposure = 0.02 + 0.18 * day + 0.01 * dusk;
    // Always non-zero so Bevy's WHITE_BALANCE pipeline key stays invariant across the day curve.
    let raw_temp = 0.006 * day + 0.008 * dusk - 0.016 * night;
    let temperature = if raw_temp.abs() < 0.001 { 0.001 } else { raw_temp };
    let tint = -0.004 - 0.003 * dusk;
    let post_saturation = (base_sat + 0.02 + 0.015 * day + 0.025 * dusk + sat_off).clamp(0.85, 1.40);
    let section = ColorGradingSection {
        saturation: 1.0,
        contrast: 1.0,
        gamma,
        gain,
        lift,
    };
    ColorGrading::with_identical_sections(
        ColorGradingGlobal {
            exposure,
            temperature,
            tint,
            hue: 0.0,
            post_saturation,
            midtones_range: 0.2..0.7,
        },
        section,
    )
}

/// Soft film: below `SOFT_FROM` (linear luminance, as the pass sees it) a pixel takes none of the
/// film, above `SOFT_TO` all of it.
const SOFT_FROM: f32 = 0.02;
const SOFT_TO: f32 = 0.25;

/// How much the soft film spares dark pixels at the atmosphere's light (lux): fully by day, not at
/// night, where the day curve's film is the moonlit blue haze the night look is built on (and
/// unseen ground's shade was tuned with). Without an atmosphere, day.
fn soft_by_light(lux: Option<f32>) -> f32 {
    const NIGHT: f32 = 2800.0;
    const DAY: f32 = 7000.0;
    lux.map_or(1.0, |l| ((l - NIGHT) / (DAY - NIGHT)).clamp(0.0, 1.0))
}

/// The sight field's texture and the memory of it (`sightfield.rs`), on the camera beside its
/// [`Edges`].
#[derive(Component, Clone, ExtractComponent)]
#[extract_app(RenderApp)]
pub struct SightTexture(pub Handle<Image>, pub Handle<Image>);

/// Feed the finishing pass from the style profile, the sun and the camera.
#[allow(clippy::type_complexity, clippy::too_many_arguments)]
pub fn update(
    style: Res<crate::style::Style>,
    film: Res<Film>,
    grade: Res<Grade>,
    quality: Res<crate::graphics::Quality>,
    target: Option<Res<crate::controls::Target>>,
    atmo: Option<Res<crate::daylight::Atmo>>,
    time: Res<Time>,
    mut drift: Local<Vec2>,
    mut cams: Query<(&Camera, &GlobalTransform, &Projection, &mut Edges, &mut bevy::render::view::ColorGrading, Option<&mut bevy::post_process::bloom::Bloom>, Option<&DistanceFog>)>,
    lights: Query<&GlobalTransform, With<DirectionalLight>>,
) {
    let Ok((camera, gtf, proj, mut e, mut grading, bloom, fog)) = cams.single_mut() else { return };
    // With the atmosphere, grading, bloom and line fade follow it (they change through the day
    // and with the fog), without touching the style profile, which the materials hang on.
    let mut s = *style;
    let atmo = atmo.filter(|a| a.active);
    if let Some(a) = &atmo {
        s.saturation = a.saturation;
        s.grade_color = a.grade;
        s.grade = a.grade_strength;
        s.bloom = a.bloom;
        if let Some(FogFalloff::Linear { start, end }) = fog.map(|f| f.falloff.clone()) {
            s.line_fade = [s.line_fade[0].min(start * 0.6), s.line_fade[1].min(start + (end - start) * 0.45)];
        }
    }
    let s = &s;
    let on = s.enabled && s.edges;
    let lookdev = s.enabled && s.look.on;
    let (w, h) = camera.physical_viewport_size().map_or((1600.0, 900.0), |s| (s.x as f32, s.y as f32));
    // The pass reads a pixel's distance from its depth (`edges.wesl` `dist`): a perspective
    // camera sends its near plane (depth = near / distance), an orthographic one (the asset
    // view's measuring view, near 0) minus its far plane (depth = 1 − distance / far).
    let (near, proj_scale, tan_x, tan_y) = match proj {
        Projection::Perspective(p) => {
            let ty = (p.fov * 0.5).tan().max(1e-4);
            let tx = ty * (w / h.max(1.0));
            (p.near, 0.5 * h / ty, tx, ty)
        }
        Projection::Orthographic(o) => {
            let oh = o.area.height().abs().max(1e-3);
            let ow = o.area.width().abs().max(1e-3);
            (-(o.far - o.near), h / oh, 0.5 * ow, 0.5 * oh)
        }
        _ => (0.1, h, 0.5, 0.5),
    };
    // The sun's direction across the screen: project a step toward it from in front of the camera.
    let sun_dir = lights.iter().next().map(|l| -l.forward().as_vec3()).unwrap_or(Vec3::Y);
    let at = gtf.translation() + gtf.forward().as_vec3() * 10.0;
    let screen_sun = match (camera.world_to_viewport(gtf, at), camera.world_to_viewport(gtf, at + sun_dir)) {
        (Ok(a), Ok(b)) => (b - a).normalize_or_zero(),
        _ => Vec2::new(0.0, -1.0),
    };
    let scale = w / camera.logical_viewport_size().map_or(w, |v| v.x).max(1.0);
    let [lr, lg, lb] = s.line_color;
    let [rr, rg, rb] = s.rim_color;
    let [gr, gg, gb] = s.grade_color;
    let line_strength = if s.look.on { s.line_strength * s.look.scenery_edges } else { s.line_strength };
    let (day, dusk, night, shadow_hue) = tod_weights(atmo.as_deref());
    // Step 3.2: tone down Film::Soft's flat salmon/warm overlay under Look-dev (keeps night's gentle
    // cool moonlight haze while clearing the flat dusk salmon wash).
    let film_strength = if on && *film != Film::Off {
        if lookdev && *film == Film::Soft {
            let day_scale = 0.60 - 0.30 * day;
            let dusk_tame = 1.0 - 0.45 * dusk;
            s.grade * day_scale * dusk_tame
        } else {
            s.grade
        }
    } else {
        0.0
    };
    // Step 3.1/3.2/3.3 Look-dev uniforms (all zero in Classic).
    let (ld_ao, ld_ao_color, ld_view_x, ld_view_y, ld_view_z, ld_aerial, ld_aerial_range, ld_split_shadow, ld_split_high) = if lookdev {
        let ao_on = on && quality.crevice_ao();
        let ao_strength = if ao_on { 0.72 + 0.16 * day } else { 0.0 };
        let sh_lin = Color::hsv(shadow_hue * 360.0, 0.55, 1.0).to_linear();
        let sh_dir = Vec3::new(sh_lin.red, sh_lin.green, sh_lin.blue).normalize_or(Vec3::new(0.35, 0.42, 0.84));
        // Cool shadow-hue crevice multiply target (never black).
        let ao_tint = (Vec3::new(0.20, 0.24, 0.40) + sh_dir * 0.14).clamp(Vec3::splat(0.16), Vec3::splat(0.62));
        // Aerial depth haze: cool-tinted mist from a little behind the camera's focus (at least
        // 15.5 m) over the next 12 m, so the far part of the Middle and Far frames recedes while
        // the characters round the focus stay clean (the Near frame ends before it starts).
        let focus_dist = target.as_deref().and_then(|t| t.0).map_or(14.0, |p| gtf.translation().distance(p));
        let aerial_start = (focus_dist + 2.6).max(15.5);
        let aerial_end = aerial_start + 12.0;
        let base_fog = atmo.as_deref().map_or(Vec3::new(0.30, 0.50, 0.78), |a| a.ld_fog);
        let cool_target = Vec3::new(0.24, 0.46, 0.84).lerp(Vec3::new(0.13, 0.16, 0.44), dusk.max(night * 0.75))
            .lerp(Vec3::new(0.035, 0.068, 0.18), night);
        let aerial_col = base_fog.lerp(cool_target, (0.50 + 0.25 * dusk).min(0.85));
        let aerial_alpha = 0.21 + 0.09 * dusk.max(night);
        let split_mul = match *grade {
            Grade::Natural => 1.0,
            Grade::Vivid => 1.35,
            Grade::Soft => 0.48,
        };
        // The shadow split moves hue only: `edges.wesl` restores each pixel's luminance after it.
        let sh_split = (0.22 + 0.10 * dusk) * split_mul;
        let hi_split = (0.28 + 0.12 * dusk - 0.12 * night) * split_mul;
        let split_shadow = Vec3::new(0.93, 0.97, 1.09).lerp(Vec3::new(0.91, 0.95, 1.12), dusk).lerp(Vec3::new(0.92, 0.97, 1.08), night);
        let split_high = Vec3::new(1.035, 1.008, 0.962).lerp(Vec3::new(1.055, 1.005, 0.940), dusk).lerp(Vec3::new(0.96, 0.99, 1.04), night);
        (
            Vec4::new(ao_strength, 0.52, 20.0, 32.0),
            ao_tint.extend(proj_scale),
            gtf.right().as_vec3().extend(tan_x),
            gtf.up().as_vec3().extend(tan_y),
            gtf.back().as_vec3().extend(1.0),
            aerial_col.extend(if on { aerial_alpha } else { 0.0 }),
            Vec4::new(aerial_start, aerial_end, sh_split, hi_split),
            split_shadow.extend(0.0),
            split_high.extend(0.0),
        )
    } else {
        (Vec4::ZERO, Vec4::ZERO, Vec4::ZERO, Vec4::ZERO, Vec4::ZERO, Vec4::ZERO, Vec4::ZERO, Vec4::ZERO, Vec4::ZERO)
    };
    *e = Edges {
        line: Vec4::new(lr, lg, lb, if on { line_strength } else { 0.0 }),
        params: Vec4::new(s.depth_threshold, s.normal_threshold, s.line_width * scale, near),
        fade: Vec4::new(s.line_fade[0], s.line_fade[1], s.screen_rim_width * scale, if on { s.screen_rim } else { 0.0 }),
        rim: Vec4::new(rr, rg, rb, 0.0),
        // z: the smallest step a crease line marks (`Style::crease_step`).
        sun: screen_sun.extend(s.crease_step).extend(0.0),
        grade: Vec4::new(gr, gg, gb, film_strength),
        film: Vec4::new(if *film == Film::Soft { 1.0 } else { 0.0 }, SOFT_FROM, SOFT_TO, soft_by_light(atmo.as_ref().map(|a| a.lux))),
        screen: Vec4::new(w, h, 1.0 / w, 1.0 / h),
        world_from_clip: gtf.to_matrix() * camera.clip_from_view().inverse(),
        eye: gtf.translation().extend(time.elapsed_secs_wrapped()),
        ld_ao,
        ld_ao_color,
        ld_view_x,
        ld_view_y,
        ld_view_z,
        ld_aerial,
        ld_aerial_range,
        ld_split_shadow,
        ld_split_high,
        ..default()
    };
    if let Some(a) = &atmo {
        // Banks drift with the wind.
        *drift += Vec2::new(0.94, 0.34) * (0.6 + 2.5 * a.wind) * time.delta_secs();
        let fog_c = a.fog * 1.06 + a.fill * 0.5;
        e.bank = Vec4::new(a.banks, a.ground, 5.0, 150.0);
        e.bank_color = fog_c.extend(drift.x);
        // Rain catches the light: brighter by day, and still seen under a storm's dark sky.
        let level = (a.lux / 9000.0).clamp(0.08, 1.0);
        e.rain = Vec4::new(a.rain, 0.12 + 0.18 * a.wind, 0.16 * level + 0.1 + a.flash * 0.35, drift.y);
    }
    if let Some(mut b) = bloom {
        if lookdev {
            let nb = full_night(dusk, night);
            let want_intensity = s.bloom * grade.bloom_scale() * (LD_BLOOM_GAIN + (LD_BLOOM_GAIN_NIGHT - LD_BLOOM_GAIN) * nb);
            if b.intensity != want_intensity {
                b.intensity = want_intensity;
            }
            let want_threshold = LD_BLOOM_THRESHOLD + (LD_BLOOM_THRESHOLD_NIGHT - LD_BLOOM_THRESHOLD) * nb;
            if b.prefilter.threshold != want_threshold {
                b.prefilter.threshold = want_threshold;
            }
            if b.prefilter.threshold_softness != LD_BLOOM_SOFTNESS {
                b.prefilter.threshold_softness = LD_BLOOM_SOFTNESS;
            }
            if b.composite_mode != bevy::post_process::bloom::BloomCompositeMode::Additive {
                b.composite_mode = bevy::post_process::bloom::BloomCompositeMode::Additive;
            }
        } else {
            if b.intensity != s.bloom {
                b.intensity = s.bloom;
            }
            if b.prefilter.threshold != 0.0 {
                b.prefilter.threshold = 0.0;
            }
            if b.prefilter.threshold_softness != 0.0 {
                b.prefilter.threshold_softness = 0.0;
            }
            if b.composite_mode != bevy::post_process::bloom::BloomCompositeMode::EnergyConserving {
                b.composite_mode = bevy::post_process::bloom::BloomCompositeMode::EnergyConserving;
            }
        }
    }
    let sat = if s.enabled { s.saturation } else { 1.0 };
    let want_grading = if lookdev {
        ld_color_grading(atmo.as_deref(), *grade, sat)
    } else {
        let mut g = bevy::render::view::ColorGrading::default();
        g.global.post_saturation = sat;
        g
    };
    if *grading != want_grading {
        *grading = want_grading;
    }
}

pub struct PostPlugin;

impl Plugin for PostPlugin {
    fn build(&self, app: &mut App) {
        embedded_asset!(app, "edges.wesl");
        let film = Film::from_env().unwrap_or_default();
        let grade = Grade::from_env().unwrap_or_default();
        info!("film: {}, grade: {}", film.name(), grade.name());
        app.insert_resource(film).insert_resource(grade);
        app.add_plugins((ExtractComponentPlugin::<Edges>::default(), UniformComponentPlugin::<Edges>::default(), ExtractComponentPlugin::<SightTexture>::default()));
        let Some(render_app) = app.get_sub_app_mut(RenderApp) else { return };
        // Before bloom (and so before tonemapping): unordered within the set, the render schedule
        // ran this pass sometimes before bloom and sometimes after, and the whole picture flipped
        // between the two results from frame to frame (flicker-2: about a level of 8-bit luma on
        // every lit surface with the camera still).
        render_app
            .add_systems(RenderStartup, init_pipeline)
            .add_systems(Core3d, draw.in_set(Core3dSystems::PostProcess).before(bevy::post_process::bloom::bloom));
    }
}

#[derive(Resource)]
struct EdgesPipeline {
    layout: BindGroupLayoutDescriptor,
    sampler: Sampler,
    ldr: CachedRenderPipelineId,
    hdr: CachedRenderPipelineId,
    ldr_ld: CachedRenderPipelineId,
    hdr_ld: CachedRenderPipelineId,
    ldr_ld_ao: CachedRenderPipelineId,
    hdr_ld_ao: CachedRenderPipelineId,
}

fn init_pipeline(mut commands: Commands, render_device: Res<RenderDevice>, asset_server: Res<AssetServer>, fullscreen_shader: Res<FullscreenShader>, pipeline_cache: Res<PipelineCache>) {
    let layout = BindGroupLayoutDescriptor::new(
        "edges_bind_group_layout",
        &BindGroupLayoutEntries::sequential(
            ShaderStages::FRAGMENT,
            (
                texture_2d(TextureSampleType::Float { filterable: true }),
                sampler(SamplerBindingType::Filtering),
                texture_depth_2d(),
                texture_2d(TextureSampleType::Float { filterable: false }),
                uniform_buffer::<Edges>(true),
                texture_2d(TextureSampleType::Float { filterable: true }),
                sampler(SamplerBindingType::Filtering),
                texture_2d(TextureSampleType::Float { filterable: true }),
            ),
        ),
    );
    let sampler = render_device.create_sampler(&SamplerDescriptor::default());
    let shader = asset_server.load("embedded://living_game/edges.wesl");
    let queue = |format: TextureFormat, defs: &[&'static str], label: &'static str| {
        pipeline_cache.queue_render_pipeline(RenderPipelineDescriptor {
            label: Some(label.into()),
            layout: vec![layout.clone()],
            vertex: fullscreen_shader.to_vertex_state(),
            fragment: Some(FragmentState {
                shader: shader.clone(),
                shader_defs: defs.iter().map(|d| (*d).into()).collect(),
                targets: vec![Some(ColorTargetState { format, blend: None, write_mask: ColorWrites::ALL })],
                ..default()
            }),
            ..default()
        })
    };
    let (ldr, hdr) = (
        queue(TextureFormat::Rgba8UnormSrgb, &[], "edges_pipeline"),
        queue(TextureFormat::Rgba16Float, &[], "edges_pipeline"),
    );
    let (ldr_ld, hdr_ld) = (
        queue(TextureFormat::Rgba8UnormSrgb, &["LOOKDEV"], "edges_pipeline_lookdev"),
        queue(TextureFormat::Rgba16Float, &["LOOKDEV"], "edges_pipeline_lookdev"),
    );
    let (ldr_ld_ao, hdr_ld_ao) = (
        queue(TextureFormat::Rgba8UnormSrgb, &["LOOKDEV", "CREVICE_AO"], "edges_pipeline_lookdev_ao"),
        queue(TextureFormat::Rgba16Float, &["LOOKDEV", "CREVICE_AO"], "edges_pipeline_lookdev_ao"),
    );
    commands.insert_resource(EdgesPipeline { layout, sampler, ldr, hdr, ldr_ld, hdr_ld, ldr_ld_ao, hdr_ld_ao });
}

#[allow(clippy::too_many_arguments)]
fn draw(
    view: ViewQuery<(&ViewTarget, &ViewPrepassTextures, &Edges, &DynamicUniformIndex<Edges>, Option<&SightTexture>)>,
    images: Res<RenderAssets<GpuImage>>,
    fallback: Res<FallbackImage>,
    pipeline: Option<Res<EdgesPipeline>>,
    pipeline_cache: Res<PipelineCache>,
    uniforms: Res<ComponentUniforms<Edges>>,
    render_device: Res<RenderDevice>,
    mut ctx: RenderContext,
) {
    let Some(pipeline) = pipeline else { return };
    let (target, prepass, edges, index, field) = view.into_inner();
    // The sight field, or a white texel until it is uploaded (the pass reads it only when
    // `sight_field.w` says it holds one).
    let memory = field.and_then(|f| images.get(&f.1)).unwrap_or(&fallback.d2);
    let field = field.and_then(|f| images.get(&f.0)).unwrap_or(&fallback.d2);
    let hdr = target.main_texture_format() == TextureFormat::Rgba16Float;
    let lookdev = edges.ld_view_z.w > 0.5;
    let ao = lookdev && edges.ld_ao.x > 0.001;
    let id = match (hdr, lookdev, ao) {
        (true, false, _) => pipeline.hdr,
        (false, false, _) => pipeline.ldr,
        (true, true, false) => pipeline.hdr_ld,
        (false, true, false) => pipeline.ldr_ld,
        (true, true, true) => pipeline.hdr_ld_ao,
        (false, true, true) => pipeline.ldr_ld_ao,
    };
    let Some(render_pipeline) = pipeline_cache.get_render_pipeline(id) else { return };
    let (Some(depth), Some(normal), Some(binding)) = (prepass.depth_only_view(), prepass.normal_view(), uniforms.uniforms().binding()) else { return };
    let post = target.post_process_write();
    let bind_group = render_device.create_bind_group(
        "edges_bind_group",
        &pipeline_cache.get_bind_group_layout(&pipeline.layout),
        &BindGroupEntries::sequential((post.source, &pipeline.sampler, depth, normal, binding.clone(), &field.texture_view, &field.sampler, &memory.texture_view)),
    );
    let mut pass = ctx.command_encoder().begin_render_pass(&RenderPassDescriptor {
        label: Some("edges_pass"),
        color_attachments: &[Some(RenderPassColorAttachment { view: post.destination, depth_slice: None, resolve_target: None, ops: Operations::default() })],
        depth_stencil_attachment: None,
        timestamp_writes: None,
        occlusion_query_set: None,
        multiview_mask: None,
    });
    pass.set_pipeline(render_pipeline);
    pass.set_bind_group(0, &bind_group, &[index.index()]);
    pass.draw(0..3, 0..1);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn grade_parses_and_defaults_to_natural() {
        assert_eq!(Grade::default(), Grade::Natural);
        for g in Grade::ALL {
            assert_eq!(Grade::parse(g.name()), Some(g));
        }
        assert_eq!(Grade::parse("VIVID"), Some(Grade::Vivid));
        assert_eq!(Grade::parse("cinematic"), None);
        assert!(Grade::Soft.bloom_scale() < Grade::Natural.bloom_scale());
        assert!(Grade::Natural.bloom_scale() < Grade::Vivid.bloom_scale());
    }

    #[test]
    fn ld_color_grading_keeps_sections_identical_and_pipeline_flags_invariant() {
        let noon = crate::daylight::Atmo { active: true, lux: 9000.0, light: [1.0, 0.96, 0.88], shadow_hue: 0.72, ..default() };
        let dusk = crate::daylight::Atmo { active: true, lux: 6600.0, light: [1.0, 0.78, 0.60], shadow_hue: 0.76, ..default() };
        let night = crate::daylight::Atmo { active: true, lux: 2800.0, light: [0.46, 0.60, 1.0], shadow_hue: 0.66, ..default() };
        for grade in Grade::ALL {
            for atmo in [None, Some(&noon), Some(&dusk), Some(&night)] {
                let cg = ld_color_grading(atmo, grade, 1.08);
                // Identical sections avoid Bevy 0.20.1's tonemapping.wesl:334 levels.z typo.
                assert_eq!(cg.shadows, cg.midtones);
                assert_eq!(cg.midtones, cg.highlights);
                // Both WHITE_BALANCE and SECTIONAL_COLOR_GRADING stay active at every hour/grade.
                assert_ne!(cg.global.temperature, 0.0, "{grade:?} must keep WHITE_BALANCE invariant");
                assert_ne!(cg.midtones, bevy::render::view::ColorGradingSection::default(), "{grade:?} must keep SECTIONAL_COLOR_GRADING invariant");
            }
        }
        let nat_noon = ld_color_grading(Some(&noon), Grade::Natural, 1.08);
        let viv_noon = ld_color_grading(Some(&noon), Grade::Vivid, 1.08);
        let soft_noon = ld_color_grading(Some(&noon), Grade::Soft, 1.08);
        assert!(viv_noon.global.post_saturation > nat_noon.global.post_saturation);
        assert!(nat_noon.global.post_saturation > soft_noon.global.post_saturation);
        let nat_night = ld_color_grading(Some(&night), Grade::Natural, 1.18);
        assert!(nat_night.global.temperature < nat_noon.global.temperature, "night grades cooler than noon");
    }
}
