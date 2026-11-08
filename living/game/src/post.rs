//! The finishing pass (`edges.wesl`): edge lines from the depth and normal prepasses, a
//! screen-space rim light and the film gradient. Structured after Bevy 0.20's
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
    renderer::{RenderContext, RenderDevice, ViewQuery},
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
}

/// Feed the finishing pass from the style profile, the sun and the camera.
pub fn update(
    style: Res<crate::style::Style>,
    mut cams: Query<(&Camera, &GlobalTransform, &Projection, &mut Edges, &mut bevy::render::view::ColorGrading)>,
    lights: Query<&GlobalTransform, With<DirectionalLight>>,
) {
    let Ok((camera, gtf, proj, mut e, mut grading)) = cams.single_mut() else { return };
    let s = &*style;
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
        sun: screen_sun.extend(0.0).extend(0.0),
        grade: Vec4::new(gr, gg, gb, if on { s.grade } else { 0.0 }),
        screen: Vec4::new(w, h, 1.0 / w, 1.0 / h),
    };
    let sat = if s.enabled { s.saturation } else { 1.0 };
    if grading.global.post_saturation != sat {
        grading.global.post_saturation = sat;
    }
}

pub struct PostPlugin;

impl Plugin for PostPlugin {
    fn build(&self, app: &mut App) {
        embedded_asset!(app, "edges.wesl");
        app.add_plugins((ExtractComponentPlugin::<Edges>::default(), UniformComponentPlugin::<Edges>::default()));
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

fn draw(
    view: ViewQuery<(&ViewTarget, &ViewPrepassTextures, &DynamicUniformIndex<Edges>)>,
    pipeline: Option<Res<EdgesPipeline>>,
    pipeline_cache: Res<PipelineCache>,
    uniforms: Res<ComponentUniforms<Edges>>,
    render_device: Res<RenderDevice>,
    mut ctx: RenderContext,
) {
    let Some(pipeline) = pipeline else { return };
    let (target, prepass, index) = view.into_inner();
    let id = if target.main_texture_format() == TextureFormat::Rgba16Float { pipeline.hdr } else { pipeline.ldr };
    let Some(render_pipeline) = pipeline_cache.get_render_pipeline(id) else { return };
    let (Some(depth), Some(normal), Some(binding)) = (prepass.depth_only_view(), prepass.normal_view(), uniforms.uniforms().binding()) else { return };
    let post = target.post_process_write();
    let bind_group = render_device.create_bind_group(
        "edges_bind_group",
        &pipeline_cache.get_bind_group_layout(&pipeline.layout),
        &BindGroupEntries::sequential((post.source, &pipeline.sampler, depth, normal, binding.clone())),
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
