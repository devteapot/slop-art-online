//! The session recorder's frames (record.rs): a small copy of the finished frame, read back
//! from the GPU.
//!
//! Bevy's screenshot reads the whole window back. At Retina size that is about 23 MB per frame,
//! copied on the CPU, and the frames after each one were measured slower. Here a render system
//! runs after the UI pass and before upscaling, so the copy holds the HUD as shown. It draws
//! the view's main texture into a small `Rgba8UnormSrgb` image with a box filter of 16 bilinear
//! taps (`record_frames.wesl`), only on frames the recorder asks for. That image is read back with
//! Bevy's pooled `ReadbackOnce`, so the copy that reaches the CPU is the small one
//! (960×540 is 2 MB).

use bevy::asset::embedded_asset;
use bevy::camera::CompositingSpace;
use bevy::core_pipeline::{schedule::Core3d, upscaling::upscaling, FullscreenShader};
use bevy::prelude::*;
use bevy::render::{
    extract_component::{ExtractComponent, ExtractComponentPlugin},
    extract_resource::{ExtractResource, ExtractResourcePlugin},
    render_asset::RenderAssets,
    render_resource::{
        binding_types::{sampler, texture_2d},
        *,
    },
    renderer::{RenderContext, RenderDevice, ViewQuery},
    texture::GpuImage,
    view::{ResolvedCompositingSpace, ViewTarget},
    RenderApp, RenderStartup,
};
use bevy::ui_render::render_pass::ui_pass;

/// The small image the frame is drawn into, and whether this frame is to be drawn into it.
/// Written by record.rs in `Last`, read by the render world the same frame.
#[derive(Resource, Clone, Default)]
pub struct Grab {
    pub image: Option<Handle<Image>>,
    pub size: UVec2,
    pub now: bool,
}

impl ExtractResource<RenderApp> for Grab {
    type Source = Grab;
    fn extract_resource(source: &Self::Source) -> Self {
        source.clone()
    }
}

/// Marks the camera whose frame is recorded (the one the HUD is drawn on).
#[derive(Component, Clone, Copy, ExtractComponent)]
#[extract_app(RenderApp)]
pub struct Recorded;

pub struct FramesPlugin;

impl Plugin for FramesPlugin {
    fn build(&self, app: &mut App) {
        embedded_asset!(app, "record_frames.wesl");
        app.init_resource::<Grab>()
            .add_plugins((ExtractResourcePlugin::<Grab>::default(), ExtractComponentPlugin::<Recorded>::default()));
        let Some(render_app) = app.get_sub_app_mut(RenderApp) else { return };
        render_app.add_systems(RenderStartup, init_pipeline).add_systems(Core3d, draw.after(ui_pass).before(upscaling));
    }
}

/// The size of the recorded frame: `width` wide (a multiple of 64), the view's aspect, an even height (a
/// row of 4-byte texels then needs no padding for the readback: 256-byte rows at 64 px).
pub fn size_for(view: UVec2, width: u32) -> UVec2 {
    let w = (width.min(view.x.max(64)) / 64).max(1) * 64;
    let h = ((w as u64 * view.y as u64 / view.x.max(1) as u64) as u32 / 2).max(1) * 2;
    UVec2::new(w, h)
}

/// A small render target the readback can copy from.
pub fn target(images: &mut Assets<Image>, size: UVec2) -> Handle<Image> {
    let mut image = Image::new_target_texture(size.x, size.y, TextureFormat::Rgba8UnormSrgb, None);
    image.texture_descriptor.usage |= TextureUsages::COPY_SRC | TextureUsages::RENDER_ATTACHMENT;
    images.add(image)
}

#[derive(Resource)]
struct FramesPipeline {
    layout: BindGroupLayoutDescriptor,
    sampler: Sampler,
    /// For a view composited in linear light, and for one composited in sRGB.
    linear: CachedRenderPipelineId,
    srgb: CachedRenderPipelineId,
}

fn init_pipeline(mut commands: Commands, render_device: Res<RenderDevice>, asset_server: Res<AssetServer>, fullscreen_shader: Res<FullscreenShader>, pipeline_cache: Res<PipelineCache>) {
    let layout = BindGroupLayoutDescriptor::new(
        "record_frames_layout",
        &BindGroupLayoutEntries::sequential(ShaderStages::FRAGMENT, (texture_2d(TextureSampleType::Float { filterable: true }), sampler(SamplerBindingType::Filtering))),
    );
    let sampler = render_device.create_sampler(&SamplerDescriptor { mag_filter: FilterMode::Linear, min_filter: FilterMode::Linear, ..default() });
    let shader = asset_server.load("embedded://living_game/record_frames.wesl");
    let queue = |defs: Vec<bevy::shader::ShaderDefVal>| {
        pipeline_cache.queue_render_pipeline(RenderPipelineDescriptor {
            label: Some("record_frames_pipeline".into()),
            layout: vec![layout.clone()],
            vertex: fullscreen_shader.to_vertex_state(),
            fragment: Some(FragmentState {
                shader: shader.clone(),
                shader_defs: defs,
                targets: vec![Some(ColorTargetState { format: TextureFormat::Rgba8UnormSrgb, blend: None, write_mask: ColorWrites::ALL })],
                ..default()
            }),
            ..default()
        })
    };
    let (linear, srgb) = (queue(vec![]), queue(vec!["SRGB_TO_LINEAR".into()]));
    commands.insert_resource(FramesPipeline { layout, sampler, linear, srgb });
}

#[allow(clippy::too_many_arguments)]
fn draw(
    view: ViewQuery<(&ViewTarget, Option<&Recorded>, Option<&ResolvedCompositingSpace>)>,
    grab: Option<Res<Grab>>,
    images: Res<RenderAssets<GpuImage>>,
    pipeline: Option<Res<FramesPipeline>>,
    pipeline_cache: Res<PipelineCache>,
    render_device: Res<RenderDevice>,
    mut ctx: RenderContext,
) {
    let (Some(grab), Some(pipeline)) = (grab, pipeline) else { return };
    let (target, recorded, space) = view.into_inner();
    if !grab.now || recorded.is_none() {
        return;
    }
    let Some(dst) = grab.image.as_ref().and_then(|h| images.get(h)) else { return };
    let id = if ResolvedCompositingSpace::space(space) == Some(CompositingSpace::Srgb) { pipeline.srgb } else { pipeline.linear };
    let Some(render_pipeline) = pipeline_cache.get_render_pipeline(id) else { return };
    let bind_group = render_device.create_bind_group(
        "record_frames_bind_group",
        &pipeline_cache.get_bind_group_layout(&pipeline.layout),
        &BindGroupEntries::sequential((target.main_texture_view(), &pipeline.sampler)),
    );
    let mut pass = ctx.command_encoder().begin_render_pass(&RenderPassDescriptor {
        label: Some("record_frames_pass"),
        color_attachments: &[Some(RenderPassColorAttachment { view: &dst.texture_view, depth_slice: None, resolve_target: None, ops: Operations::default() })],
        depth_stencil_attachment: None,
        timestamp_writes: None,
        occlusion_query_set: None,
        multiview_mask: None,
    });
    pass.set_pipeline(render_pipeline);
    pass.set_bind_group(0, &bind_group, &[]);
    pass.draw(0..3, 0..1);
}
