//! Camera and controls spike for the playable client (docs/GAME_BRIEF.md): a desktop 3D view
//! of a living world, joined as a player with its own identity. Throwaway: it exists to pick
//! the camera and controls, not as the client's architecture.

// Display sync is shared with the observer rather than copied (smooth motion of the
// authority's analytic body segments). Extract to a shared client crate if the game stays.
#[path = "../../viewer/src/clock.rs"]
#[allow(dead_code)]
mod clock;
#[path = "../../viewer/src/sync.rs"]
#[allow(dead_code)]
mod sync;

mod camera;
mod controls;
mod demo;
mod hud;
mod net;
mod sight;
mod world;

use bevy::prelude::*;
use bevy_egui::{EguiPlugin, EguiPrimaryContextPass};

fn main() {
    let mut app = App::new();
    app.insert_resource(ClearColor(camera::SKY))
        .add_plugins(DefaultPlugins.set(WindowPlugin {
            primary_window: Some(Window {
                title: "Slop Art Online — camera spike".into(),
                resolution: bevy::window::WindowResolution::new(1600, 900),
                ..default()
            }),
            ..default()
        }))
        .add_plugins(EguiPlugin::default())
        .init_non_send::<net::Net>()
        .init_non_send::<world::Scene>()
        .init_resource::<world::Palette>()
        .init_resource::<world::Draw>()
        .init_resource::<sight::Sight>()
        .init_resource::<camera::Cam>()
        .init_resource::<controls::Target>()
        .init_resource::<controls::Input>()
        .init_resource::<hud::Hud>()
        .init_resource::<hud::UiWants>()
        .add_systems(Startup, (world::setup, camera::spawn, sight::setup))
        .add_systems(
            Update,
            (net::pump, world::entities, controls::target, world::terrain, demo::run, controls::movement, camera::follow, world::fade_trees, sight::update, controls::gizmos).chain(),
        )
        .add_systems(EguiPrimaryContextPass, hud::draw);
    if let Some(d) = demo::Demo::from_env() {
        app.insert_resource(d);
    }
    app.run();
}
