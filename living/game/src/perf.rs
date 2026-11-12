//! Measurement switches (`LIVING_GAME_PERF=<flag>,…`) that turn one rendering cost off at a time,
//! to find where frame time goes. They are for measurement only:
//! - `noedges`: the finishing pass's edge lines and rim;
//! - `slivers`: crease lines on every step, however small (the old rule, `Style::crease_step` 0);
//! - `nooutlines`: shell outlines (characters);
//! - `noshadows`: the sun's shadow maps;
//! - `noprepass`: depth and normal prepasses (also disables edges, which need them);
//! - `nobloom`: bloom;
//! - `nopeople`: no characters on the island;
//! - `nosmall`: no small things (grass, flowers, props under 1.6 m) on the island;
//! - `nostencil`: environment meshes and ground draw no outline stencil;
//! - `nofar`: no coarse ground and sea past the island's 170 m, and no landmarks past 190 m
//!   (`island::stream`, `live::lots`): the long view's cost;
//! - `nohair`, `charopaque`: characters without hair, or with alpha-masked materials drawn opaque;
//! - `shadowmap=N`, `cascades=N`, `shadowfar=M`: the sun's shadow map size, cascade count and
//!   reach;
//! - `people=K`: K times the island's people per settlement;
//! - `nodetail`: no painted detail on scenery models (style.rs); `detailonly=bark+leaves` keeps
//!   it on only the surfaces named;
//! - `nocutaway`: tall things between the camera and you stay drawn (photographing your
//!   character behind a wall or a tree, as other people are seen);
//! - `nobudget`: the island spawns a chunk's things as soon as their files have loaded, all in
//!   one frame (island.rs `SPAWN_BUDGET`);
//! - `hitch=MS`: every frame slower than MS milliseconds (default 30) is logged with what entered
//!   the world in it and the two frames before: entities, meshes, models and characters spawned
//!   and meshes converted to toon materials; in the render world, every frame that creates
//!   pipelines logs how many, by label and vertex layout, and how long its render set took
//!   (Bevy creates pipelines synchronously on macOS, inside that set: a new material, mesh
//!   layout or pass stalls the frame that first draws it; `prewarm` in `island.rs`);
//! - `diag`: every 2 s, Bevy's render diagnostics (per-pass CPU time; GPU time only where the
//!   backend reports timestamps, so not on Metal) and what each view draws: meshes, distinct
//!   meshes and materials, triangles, and the characters' share, for the camera and each
//!   shadow cascade; every 10 s, what the loaded assets hold (`assets:`);
//! - `rebuild=S`: S seconds after the first load's cover lifts, every character's scene is
//!   spawned again, as a changed scene asset would make Bevy do (`characters::force_rebuild`), to
//!   check that they are fitted, shaped and animated again; `nokeep` skips that (what happened
//!   before rebuild-keep, for comparison);
//! - `genoutlines`: generate every mesh's outline directions, ignoring those a file brings
//!   (`style::outline_normals`); `keeppixels`: character pictures keep their pixels on the CPU
//!   (`characters::thumb_pictures`). Both are the way before types-1, for comparison.
//! - `sharestyles`: composed people's style files share a toon material wherever their
//!   materials are the same, in place of one a file (`characters/compose.rs`), to measure what
//!   the materials cost. Colours are wrong with it (each piece recolours from the first one's
//!   mean).
//!
//! The frame is often limited by neither the GPU nor one system but by the render world's
//! per-batch work: every distinct material and mesh slab is a batch set per view and pass, and
//! each batch set's buffers are written every frame (a staging buffer apiece on Metal). The
//! `diag` material counts show it; a CPU sample (`sample <pid> 4`) attributes it to
//! `write_binned_instance_buffers` and `submit_pending_command_buffers`.
//!
//! `LIVING_GAME_FPS_CAP=<hz>` sets the headless loop's rate (default 60; 0 runs uncapped, so
//! frame times show the real cost).
//!
//! `LIVING_GAME_FRAMES=<file>` appends one line per frame, `unix_us,interval_us,work_us`: the
//! wall clock at the frame's end, the real time since the previous frame (`Time<Real>`, what
//! frame pacing is judged on) and the main schedule's own time from `First` to `Last` (without
//! the runner's sleep up to the cap). For the immediate gate's frame pacing (docs/GATE_216.md).

use bevy::prelude::*;

pub fn has(flag: &str) -> bool {
    std::env::var("LIVING_GAME_PERF").is_ok_and(|v| v.split(',').any(|f| f.trim() == flag))
}

pub fn cap() -> std::time::Duration {
    let hz: f64 = std::env::var("LIVING_GAME_FPS_CAP").ok().and_then(|v| v.parse().ok()).unwrap_or(60.0);
    if hz <= 0.0 {
        std::time::Duration::ZERO
    } else {
        std::time::Duration::from_secs_f64(1.0 / hz)
    }
}

/// Apply the switches to the camera, the sun and the style each frame (cheap; they only write
/// when something differs).
pub fn apply(
    mut commands: Commands,
    mut style: ResMut<crate::style::Style>,
    mut suns: Query<&mut DirectionalLight>,
    cams: Query<(Entity, Has<bevy::core_pipeline::prepass::DepthPrepass>, Has<bevy::post_process::bloom::Bloom>), With<Camera3d>>,
) {
    if std::env::var("LIVING_GAME_PERF").is_err() {
        return;
    }
    if (has("noedges") || has("noprepass")) && style.edges {
        style.edges = false;
    }
    if has("slivers") && style.crease_step != 0.0 {
        style.crease_step = 0.0;
    }
    if has("nooutlines") && style.outlines {
        style.outlines = false;
    }
    if has("noshadows") {
        for mut s in &mut suns {
            if s.shadow_maps_enabled {
                s.shadow_maps_enabled = false;
            }
        }
    }
    for (e, prepass, bloom) in &cams {
        if has("noprepass") && prepass {
            commands.entity(e).remove::<(bevy::core_pipeline::prepass::DepthPrepass, bevy::core_pipeline::prepass::NormalPrepass)>();
        }
        if has("nobloom") && bloom {
            commands.entity(e).remove::<bevy::post_process::bloom::Bloom>();
        }
    }
}

/// `diag`: Bevy's render diagnostics (per-pass CPU time, and GPU time where the backend reports
/// timestamps), logged every 2 s.
pub fn diagnostics(app: &mut App) {
    if let Some(n) = value("shadowmap") {
        app.insert_resource(bevy::light::DirectionalLightShadowMap { size: n as usize });
    }
    if let Some(file) = std::env::var("LIVING_GAME_FRAMES").ok().filter(|f| !f.is_empty()).and_then(|f| std::fs::File::create(f).ok()) {
        app.insert_resource(Frames { out: std::io::BufWriter::new(file), start: None, flushed: 0 });
        app.add_systems(First, frame_start);
        app.add_systems(Last, frame_end);
    }
    if has("hitch") || value("hitch").is_some() {
        app.add_systems(Last, log_hitches);
        if let Some(render) = app.get_sub_app_mut(bevy::render::RenderApp) {
            use bevy::render::{Render, RenderSystems};
            render.add_systems(Render, (pipelines_start.before(RenderSystems::Render), log_pipelines.after(RenderSystems::Render)));
        }
    }
    if !has("diag") {
        return;
    }
    app.add_plugins(bevy::render::diagnostic::RenderDiagnosticsPlugin).add_systems(Last, (log_diagnostics, log_views, log_assets));
    if let Some(render) = app.get_sub_app_mut(bevy::render::RenderApp) {
        use bevy::render::{Render, RenderSystems};
        render.add_systems(Render, log_batches.after(RenderSystems::PhaseSort).before(RenderSystems::Render));
    }
}

/// `diag`, in the render world, every 2 s: how the binned phases batch (`batches:`), and the
/// textures on the GPU. For each phase, summed over its views: multi-draw batch sets (one draw
/// call each where the backend draws indirect lists natively; each of their meshes is one
/// indirect draw within it), batchable bins (one instanced draw each) and unbatchable entities
/// (one draw each: meshes with morph targets). The GPU preprocessing mode decides which a mesh
/// is. Textures: every `GpuImage`'s bytes (mips included).
#[allow(clippy::too_many_arguments)]
fn log_batches(
    support: Option<Res<bevy::render::batching::gpu_preprocessing::GpuPreprocessingSupport>>,
    opaque: Res<bevy::render::render_phase::ViewBinnedRenderPhases<bevy::core_pipeline::core_3d::Opaque3d>>,
    mask: Res<bevy::render::render_phase::ViewBinnedRenderPhases<bevy::core_pipeline::core_3d::AlphaMask3d>>,
    prepass: Res<bevy::render::render_phase::ViewBinnedRenderPhases<bevy::core_pipeline::prepass::Opaque3dPrepass>>,
    mask_prepass: Res<bevy::render::render_phase::ViewBinnedRenderPhases<bevy::core_pipeline::prepass::AlphaMask3dPrepass>>,
    shadow: Res<bevy::render::render_phase::ViewBinnedRenderPhases<bevy::pbr::Shadow>>,
    images: Res<bevy::render::render_asset::RenderAssets<bevy::render::texture::GpuImage>>,
    mut last: Local<Option<std::time::Instant>>,
) {
    use bevy::render::render_phase::{BinnedPhaseItem, ViewBinnedRenderPhases};
    if last.is_some_and(|t| t.elapsed().as_secs_f32() < 2.0) {
        return;
    }
    *last = Some(std::time::Instant::now());
    fn count<P: BinnedPhaseItem>(name: &str, phases: &ViewBinnedRenderPhases<P>) -> String {
        let (mut sets, mut bins, mut lone) = (0, 0, 0);
        for phase in phases.0.values() {
            sets += phase.multidrawable_meshes.len();
            bins += phase.batchable_meshes.len();
            lone += phase.unbatchable_meshes.values().map(|u| u.entities.len()).sum::<usize>();
        }
        format!("{name} {sets} sets, {bins} bins, {lone} lone ({} views)", phases.0.len())
    }
    use bevy::render::batching::gpu_preprocessing::GpuPreprocessingMode as Mode;
    let mode = match support.map(|s| s.max_supported_mode) {
        Some(Mode::None) => "none",
        Some(Mode::PreprocessingOnly) => "preprocessing only",
        Some(Mode::Culling) => "culling (multi-draw)",
        None => "?",
    };
    let bytes: u64 = images
        .iter()
        .map(|(_, g)| {
            let d = &g.texture_descriptor;
            let (bw, bh) = d.format.block_dimensions();
            let block = d.format.block_copy_size(None).unwrap_or(4) as u64;
            (0..d.mip_level_count.max(1))
                .map(|m| {
                    let (w, h) = ((d.size.width >> m).max(1), (d.size.height >> m).max(1));
                    w.div_ceil(bw) as u64 * h.div_ceil(bh) as u64 * block * d.size.depth_or_array_layers as u64
                })
                .sum::<u64>()
        })
        .sum();
    info!(
        "batches: preprocessing {mode}; {}; {}; {}; {}; {}; textures {} on the GPU {:.1} MiB",
        count("opaque", &opaque),
        count("mask", &mask),
        count("prepass", &prepass),
        count("mask-prepass", &mask_prepass),
        count("shadow", &shadow),
        images.iter().count(),
        bytes as f64 / (1024.0 * 1024.0)
    );
}

/// `diag`: what the loaded assets hold, every 10 s: meshes (their vertex, index and morph-target
/// data in the main world), images (their pixels), animation clips (and their curves), graphs and
/// glTF files. Counts and sizes, not the process's memory: they don't move with the machine's
/// load, so two builds or two sets of files compare exactly (crowd-1: clips stored once).
fn log_assets(
    time: Res<Time>,
    mut since: Local<f32>,
    meshes: Res<Assets<Mesh>>,
    images: Res<Assets<Image>>,
    clips: Res<Assets<AnimationClip>>,
    graphs: Res<Assets<AnimationGraph>>,
    gltfs: Res<Assets<bevy::gltf::Gltf>>,
) {
    *since += time.delta_secs();
    if *since < 10.0 {
        return;
    }
    *since = 0.0;
    let mib = |b: usize| b as f32 / (1024.0 * 1024.0);
    let (mut vb, mut ib, mut mb) = (0usize, 0usize, 0usize);
    for (_, m) in meshes.iter() {
        // Meshes whose data went to the render world alone hold none here.
        if m.try_indices_option().is_err() {
            continue;
        }
        vb += m.get_vertex_buffer_size();
        ib += m.get_index_buffer_bytes().map_or(0, |b| b.len());
        mb += m.morph_targets().map_or(0, |t| t.len() * std::mem::size_of::<bevy::mesh::morph::MorphAttributes>());
    }
    let px: usize = images.iter().map(|(_, i)| i.data.as_ref().map_or(0, |d| d.len())).sum();
    let curves: usize = clips.iter().map(|(_, c)| c.curves().values().map(|v| v.len()).sum::<usize>()).sum();
    info!(
        "assets: {} meshes {:.1} MiB (vertices {:.1}, indices {:.1}, morph targets {:.1}); {} images {:.1} MiB; {} clips ({curves} curves); {} graphs; {} glTF files; outline directions generated for {} meshes, brought by {}",
        meshes.len(),
        mib(vb + ib + mb),
        mib(vb),
        mib(ib),
        mib(mb),
        images.len(),
        mib(px),
        clips.len(),
        graphs.len(),
        gltfs.len(),
        crate::style::OUTLINE_NORMALS.0.load(std::sync::atomic::Ordering::Relaxed),
        crate::style::OUTLINE_NORMALS.1.load(std::sync::atomic::Ordering::Relaxed)
    );
}

/// What entered the world in one frame: entities (net), meshes, models, characters, conversions.
#[derive(Default, Clone, Copy)]
struct Arrivals {
    entities: i64,
    meshes: usize,
    models: usize,
    characters: usize,
    converted: usize,
}

/// `hitch`: frames slower than the threshold, with the arrivals of that frame and the two before.
/// A frame's own cost shows in the next frame's delta, so the delta logged belongs to the frame
/// before the one it is read in.
#[allow(clippy::too_many_arguments)]
fn log_hitches(
    time: Res<bevy::time::Time<bevy::time::Real>>,
    all: Query<()>,
    meshes: Query<(), Added<Mesh3d>>,
    models: Query<(), Added<crate::lookdev::Model>>,
    characters: Query<(), Added<crate::characters::Character>>,
    converted: Query<(), Added<crate::lookdev::Converted>>,
    roam: Res<crate::envs::Roam>,
    mut last: Local<(i64, [Arrivals; 3])>,
) {
    let n = all.iter().count() as i64;
    let now = Arrivals { entities: n - last.0, meshes: meshes.iter().count(), models: models.iter().count(), characters: characters.iter().count(), converted: converted.iter().count() };
    last.0 = n;
    let ms = time.delta_secs() * 1000.0;
    if ms > value("hitch").unwrap_or(30.0) {
        let [a, b, _] = last.1;
        info!("hitch: {ms:.1} ms at ({:.0}, {:.0}); this frame {now:?}; before {a:?}; two before {b:?}", roam.pos.x, roam.pos.y);
    }
    last.1 = [now, last.1[0], last.1[1]];
}

/// `LIVING_GAME_FRAMES`: the per-frame record.
#[derive(Resource)]
struct Frames {
    out: std::io::BufWriter<std::fs::File>,
    start: Option<std::time::Instant>,
    flushed: u64,
}

fn frame_start(mut frames: ResMut<Frames>) {
    frames.start = Some(std::time::Instant::now());
}

fn frame_end(mut frames: ResMut<Frames>, time: Res<bevy::time::Time<bevy::time::Real>>) {
    use std::io::Write;
    let work = frames.start.take().map_or(0, |s| s.elapsed().as_micros() as u64);
    let unix = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_micros() as u64);
    let _ = writeln!(frames.out, "{unix},{},{work}", time.delta().as_micros());
    // At most one flush a second, so a killed run loses at most a second of frames.
    if unix.saturating_sub(frames.flushed) > 1_000_000 {
        let _ = frames.out.flush();
        frames.flushed = unix;
    }
}

#[derive(Resource)]
struct RenderSetStart(std::time::Instant);

fn pipelines_start(mut commands: Commands) {
    commands.insert_resource(RenderSetStart(std::time::Instant::now()));
}

/// `hitch`: pipelines created this frame (label, vertex buffers' attribute count), and the
/// render set's time.
fn log_pipelines(cache: Res<bevy::render::render_resource::PipelineCache>, start: Option<Res<RenderSetStart>>, mut seen: Local<usize>) {
    use bevy::material::descriptor::PipelineDescriptor;
    let n = cache.pipelines().count();
    if n <= *seen {
        return;
    }
    let mut by: std::collections::BTreeMap<String, usize> = Default::default();
    for p in cache.pipelines().skip(*seen) {
        let k = match &p.descriptor {
            PipelineDescriptor::RenderPipelineDescriptor(d) => format!("{}/{}", d.label.as_deref().unwrap_or("?"), d.vertex.buffers.iter().map(|b| b.attributes.len()).sum::<usize>()),
            PipelineDescriptor::ComputePipelineDescriptor(d) => d.label.as_deref().unwrap_or("compute").to_string(),
            PipelineDescriptor::MeshPipelineDescriptor(_) => "mesh".into(),
        };
        *by.entry(k).or_default() += 1;
    }
    *seen = n;
    let ms = start.map_or(0.0, |s| s.0.elapsed().as_secs_f64() * 1000.0);
    info!("pipelines: +{} (now {n}) in a {ms:.0} ms render set: {}", by.values().sum::<usize>(), by.iter().map(|(k, v)| format!("{k} ×{v}")).collect::<Vec<_>>().join(", "));
}

impl std::fmt::Debug for Arrivals {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{:+} entities, {} meshes, {} models, {} characters, {} converted", self.entities, self.meshes, self.models, self.characters, self.converted)
    }
}

fn log_diagnostics(store: Res<bevy::diagnostic::DiagnosticsStore>, time: Res<Time>, mut since: Local<f32>) {
    *since += time.delta_secs();
    if *since < 2.0 {
        return;
    }
    *since = 0.0;
    let mut lines: Vec<String> = store
        .iter()
        .filter(|d| d.path().as_str().starts_with("render/"))
        .filter_map(|d| Some(format!("{} {:.3}", d.path().as_str(), d.smoothed()?)))
        .collect();
    lines.sort();
    info!("diag: {}", lines.join("; "));
}

/// `diag`: what each view draws (meshes and triangles; characters' share in brackets), every 2 s.
#[allow(clippy::type_complexity)]
pub fn log_views(
    time: Res<Time>,
    mut since: Local<f32>,
    cams: Query<(Entity, &bevy::camera::visibility::VisibleEntities), With<Camera3d>>,
    lights: Query<&bevy::camera::visibility::CascadesVisibleEntities>,
    mesh3d: Query<&Mesh3d>,
    meshes: Res<Assets<Mesh>>,
    chars: Query<Entity, With<crate::characters::Character>>,
    children: Query<&Children>,
    mats: Query<&MeshMaterial3d<crate::style::Toon>>,
    toons: Res<Assets<crate::style::Toon>>,
) {
    if !has("diag") {
        return;
    }
    *since += time.delta_secs();
    if *since < 2.0 {
        return;
    }
    *since = 0.0;
    let people: std::collections::HashSet<Entity> = chars.iter().flat_map(|c| children.iter_descendants(c)).collect();
    let tris = |e: &Entity| mesh3d.get(*e).ok().and_then(|m| meshes.get(&m.0)).map_or(0, |m| m.indices().map_or(m.count_vertices(), |i| i.len()) / 3);
    let sum = |list: &[Entity]| {
        let (mut n, mut t, mut pn, mut pt) = (0, 0, 0, 0);
        for e in list {
            let k = tris(e);
            n += 1;
            t += k;
            if people.contains(e) {
                pn += 1;
                pt += k;
            }
        }
        let distinct = |people_only: bool| list.iter().filter(|e| !people_only || people.contains(*e)).filter_map(|e| mats.get(*e).ok().map(|m| m.0.id())).collect::<std::collections::HashSet<_>>().len();
        let distinct_meshes = list.iter().filter_map(|e| mesh3d.get(*e).ok().map(|m| m.0.id())).collect::<std::collections::HashSet<_>>().len();
        // People's meshes that could share an instanced draw: the same mesh in the same material.
        let pairs = list.iter().filter(|e| people.contains(*e)).filter_map(|e| Some((mesh3d.get(*e).ok()?.0.id(), mats.get(*e).ok()?.0.id()))).collect::<std::collections::HashSet<_>>().len();
        format!("{n} meshes ({distinct_meshes} distinct, {} materials) {:.0}k tris [people {pn}, {} materials, {:.0}k, {pairs} mesh-material pairs]", distinct(false), t as f32 / 1000.0, distinct(true), pt as f32 / 1000.0)
    };
    let id = std::any::TypeId::of::<Mesh3d>();
    for (cam, vis) in &cams {
        let mut out = vec![format!("main {}", sum(vis.get(id)))];
        for l in &lights {
            if let Some(cs) = l.entities.get(&cam) {
                for (i, c) in cs.iter().enumerate() {
                    out.push(format!("cascade{i} {}", sum(&c.entities)));
                }
            }
        }
        info!("views: {} toon materials; {}", toons.len(), out.join("; "));
    }
}

/// A numeric flag's value (`name=value`).
pub fn value(name: &str) -> Option<f32> {
    std::env::var("LIVING_GAME_PERF").ok()?.split(',').find_map(|f| f.trim().strip_prefix(name)?.strip_prefix('=')?.parse().ok())
}
