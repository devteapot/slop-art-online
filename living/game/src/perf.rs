//! Measurement switches (`LIVING_GAME_PERF=<flag>,…`) that turn one rendering cost off at a time,
//! to find where frame time goes. They are for measurement only:
//! - `noedges`: the finishing pass's edge lines and rim;
//! - `nooutlines`: shell outlines (characters);
//! - `noshadows`: the sun's shadow maps;
//! - `noprepass`: depth and normal prepasses (also disables edges, which need them);
//! - `nobloom`: bloom;
//! - `nopeople`: no characters on the island;
//! - `nosmall`: no small things (grass, flowers, props under 1.6 m) on the island;
//! - `nostencil`: environment meshes and ground draw no outline stencil;
//! - `nohair`, `charopaque`: characters without hair, or with alpha-masked materials drawn opaque;
//! - `shadowmap=N`, `cascades=N`, `shadowfar=M`: the sun's shadow map size, cascade count and
//!   reach;
//! - `people=K`: K times the island's people per settlement;
//! - `diag`: every 2 s, Bevy's render diagnostics (per-pass CPU time; GPU time only where the
//!   backend reports timestamps, so not on Metal) and what each view draws: meshes, distinct
//!   meshes and materials, triangles, and the characters' share, for the camera and each
//!   shadow cascade.
//!
//! The frame is often limited by neither the GPU nor one system but by the render world's
//! per-batch work: every distinct material and mesh slab is a batch set per view and pass, and
//! each batch set's buffers are written every frame (a staging buffer apiece on Metal). The
//! `diag` material counts show it; a CPU sample (`sample <pid> 4`) attributes it to
//! `write_binned_instance_buffers` and `submit_pending_command_buffers`.
//!
//! `LIVING_GAME_FPS_CAP=<hz>` sets the headless loop's rate (default 60; 0 runs uncapped, so
//! frame times show the real cost).

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
    if !has("diag") {
        return;
    }
    app.add_plugins(bevy::render::diagnostic::RenderDiagnosticsPlugin).add_systems(Last, (log_diagnostics, log_views));
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
        format!("{n} meshes ({distinct_meshes} distinct, {} materials) {:.0}k tris [people {pn}, {} materials, {:.0}k]", distinct(false), t as f32 / 1000.0, distinct(true), pt as f32 / 1000.0)
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
