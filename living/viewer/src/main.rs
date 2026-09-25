//! Living world observer: a top-down map of the valley with a story feed and an inspector
//! for each character's identity, behavior graph, beliefs and model thoughts. Reads public
//! tables only, anonymously; it never calls reducers.

mod clock;
mod map;
mod net;
mod panels;
mod state;

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
    let snap = state::Snap::take(net);
    view.refresh(ctx, net, &snap, time.delta_secs());
    let dt = time.delta_secs().max(1e-4);
    view.fps += (1.0 / dt - view.fps) * 0.05;
    panels::top_bar(ctx, net, &snap, view.fps, view.frame_ms);
    panels::left(ctx, &mut view, &snap);
    panels::inspector(ctx, &mut view, net, &snap);
    map::central(ctx, &mut view, &snap, time.elapsed_secs());
    let ms = started.elapsed().as_secs_f32() * 1000.0;
    view.frame_ms += (ms - view.frame_ms) * 0.05;
    Ok(())
}
