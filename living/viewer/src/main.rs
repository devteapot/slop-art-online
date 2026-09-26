//! Living world observer: a top-down map of the valley with a story feed and an inspector
//! for each character's identity, behavior graph, beliefs and model thoughts. Reads public
//! tables only, anonymously; it never calls reducers (one per-character experience query).

mod art;
mod clock;
mod map;
mod net;
mod panels;
mod state;
mod terrain;

use bevy::prelude::*;
use bevy_egui::{EguiContexts, EguiPlugin, EguiPrimaryContextPass};

fn main() {
    App::new()
        .insert_resource(ClearColor(Color::srgb(0.06, 0.08, 0.10)))
        .add_plugins(DefaultPlugins.set(WindowPlugin {
            primary_window: Some(Window {
                title: "Living world — observer".into(),
                canvas: Some("#living-canvas".into()),
                fit_canvas_to_parent: true,
                ..default()
            }),
            ..default()
        }))
        .add_plugins(EguiPlugin::default())
        .init_non_send_resource::<net::Net>()
        .init_non_send_resource::<state::View>()
        .add_systems(Startup, |mut commands: Commands| {
            commands.spawn(Camera2d);
        })
        .add_systems(Update, net::pump)
        .add_systems(EguiPrimaryContextPass, draw)
        .run();
}

fn draw(mut contexts: EguiContexts, mut net: NonSendMut<net::Net>, mut view: NonSendMut<state::View>, time: Res<Time>) -> Result {
    let started = bevy::platform::time::Instant::now();
    let ctx = contexts.ctx_mut()?;
    view.style(ctx);
    net.watch_experiences(view.selected);
    let net = &*net;
    let mut lap = started;
    let mut split = |i: usize, view: &mut state::View| {
        let t = bevy::platform::time::Instant::now();
        let ms = (t - lap).as_secs_f32() * 1000.0;
        view.splits[i] += ms;
        lap = t;
    };
    let snap = state::Snap::take(net);
    split(0, &mut view);
    view.refresh(ctx, net, &snap, time.delta_secs());
    split(1, &mut view);
    let dt = time.delta_secs().max(1e-4);
    view.fps += (1.0 / dt - view.fps) * 0.05;
    panels::top_bar(ctx, net, &snap, &mut view);
    panels::left(ctx, &mut view, net, &snap);
    split(2, &mut view);
    panels::inspector(ctx, &mut view, net, &snap);
    panels::sign_window(ctx, &mut view, &snap);
    panels::fight_panel(ctx, &mut view, &snap);
    split(3, &mut view);
    map::central(ctx, &mut view, &snap, time.elapsed_secs());
    split(4, &mut view);
    let ms = started.elapsed().as_secs_f32() * 1000.0;
    view.frame_ms += (ms - view.frame_ms) * 0.05;
    view.frames += 1;
    view.worst_ms = view.worst_ms.max(ms);
    let secs = time.elapsed_secs() as u32;
    if secs >= view.logged_at + 10 {
        view.logged_at = secs;
        let n = view.frames.max(1) as f32;
        let s = view.splits.map(|x| x / n);
        info!(
            "viewer: {:.0} fps, {} frames, ui avg {:.1} ms worst {:.1} ms (snapshot {:.1}, refresh {:.1}, left {:.1}, inspector {:.1}, map {:.1}), zoom {:.1}, {} creatures, {} resources, terrain chunks drawn/cached {}/{} (last build {:.1} ms)",
            view.fps, view.frames, s.iter().sum::<f32>(), view.worst_ms, s[0], s[1], s[2], s[3], s[4], view.zoom, snap.bodies.len(), snap.resources.len(), view.terrain_stats.0, view.terrain_stats.1, view.terrain_stats.2
        );
        view.splits = [0.0; 5];
        view.frames = 0;
        view.worst_ms = 0.0;
    }
    Ok(())
}
