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
#[allow(clippy::type_complexity)]
pub fn update(
    style: Res<crate::style::Style>,
    film: Res<Film>,
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
    let (w, h) = camera.physical_viewport_size().map_or((1600.0, 900.0), |s| (s.x as f32, s.y as f32));
    let near = if let Projection::Perspective(p) = proj { p.near } else { 0.1 };
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
    *e = Edges {
        line: Vec4::new(lr, lg, lb, if on { s.line_strength } else { 0.0 }),
        params: Vec4::new(s.depth_threshold, s.normal_threshold, s.line_width * scale, near),
        fade: Vec4::new(s.line_fade[0], s.line_fade[1], s.screen_rim_width * scale, if on { s.screen_rim } else { 0.0 }),
        rim: Vec4::new(rr, rg, rb, 0.0),
        // z: the smallest step a crease line marks (`Style::crease_step`).
        sun: screen_sun.extend(s.crease_step).extend(0.0),
        grade: Vec4::new(gr, gg, gb, if on && *film != Film::Off { s.grade } else { 0.0 }),
        film: Vec4::new(if *film == Film::Soft { 1.0 } else { 0.0 }, SOFT_FROM, SOFT_TO, soft_by_light(atmo.as_ref().map(|a| a.lux))),
        screen: Vec4::new(w, h, 1.0 / w, 1.0 / h),
        world_from_clip: gtf.to_matrix() * camera.clip_from_view().inverse(),
        eye: gtf.translation().extend(time.elapsed_secs_wrapped()),
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
        if b.intensity != s.bloom {
            b.intensity = s.bloom;
        }
    }
    let sat = if s.enabled { s.saturation } else { 1.0 };
    if grading.global.post_saturation != sat {
        grading.global.post_saturation = sat;
    }
}

pub struct PostPlugin;

impl Plugin for PostPlugin {
    fn build(&self, app: &mut App) {
        embedded_asset!(app, "edges.wesl");
        let film = Film::from_env().unwrap_or_default();
        info!("film: {}", film.name());
        app.insert_resource(film);
        app.add_plugins((ExtractComponentPlugin::<Edges>::default(), UniformComponentPlugin::<Edges>::default(), ExtractComponentPlugin::<SightTexture>::default()));
        let Some(render_app) = app.get_sub_app_mut(RenderApp) else { return };
        render_app.add_systems(RenderStartup, init_pipeline).add_systems(Core3d, draw.in_set(Core3dSystems::PostProcess));
    }
}

#[derive(Resource)]
struct EdgesPipeline {
    layout: BindGroupLayoutDescriptor,
    sampler: Sampler,
    ldr: CachedRenderPipelineId,
    hdr: CachedRenderPipelineId,
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
    let queue = |format: TextureFormat| {
        pipeline_cache.queue_render_pipeline(RenderPipelineDescriptor {
            label: Some("edges_pipeline".into()),
            layout: vec![layout.clone()],
            vertex: fullscreen_shader.to_vertex_state(),
            fragment: Some(FragmentState {
                shader: shader.clone(),
                targets: vec![Some(ColorTargetState { format, blend: None, write_mask: ColorWrites::ALL })],
                ..default()
            }),
            ..default()
        })
    };
    let (ldr, hdr) = (queue(TextureFormat::Rgba8UnormSrgb), queue(TextureFormat::Rgba16Float));
    commands.insert_resource(EdgesPipeline { layout, sampler, ldr, hdr });
}

#[allow(clippy::too_many_arguments)]
fn draw(
    view: ViewQuery<(&ViewTarget, &ViewPrepassTextures, &DynamicUniformIndex<Edges>, Option<&SightTexture>)>,
    images: Res<RenderAssets<GpuImage>>,
    fallback: Res<FallbackImage>,
    pipeline: Option<Res<EdgesPipeline>>,
    pipeline_cache: Res<PipelineCache>,
    uniforms: Res<ComponentUniforms<Edges>>,
    render_device: Res<RenderDevice>,
    mut ctx: RenderContext,
) {
    let Some(pipeline) = pipeline else { return };
    let (target, prepass, index, field) = view.into_inner();
    // The sight field, or a white texel until it is uploaded (the pass reads it only when
    // `sight_field.w` says it holds one).
    let memory = field.and_then(|f| images.get(&f.1)).unwrap_or(&fallback.d2);
    let field = field.and_then(|f| images.get(&f.0)).unwrap_or(&fallback.d2);
    let id = if target.main_texture_format() == TextureFormat::Rgba16Float { pipeline.hdr } else { pipeline.ldr };
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
