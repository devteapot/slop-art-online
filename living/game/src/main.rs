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

mod bodies;
mod camera;
mod controls;
mod demo;
mod envs;
mod hud;
mod lookdev;
mod net;
mod post;
mod sight;
mod style;
mod world;

use bevy::prelude::*;
use bevy_egui::{EguiPlugin, EguiPrimaryContextPass};

fn main() {
    let mut app = App::new();
    app.insert_resource(ClearColor(camera::SKY))
        .add_plugins(
            DefaultPlugins
                .set(WindowPlugin {
                    primary_window: Some(Window {
                        title: "Slop Art Online — camera spike".into(),
                        resolution: bevy::window::WindowResolution::new(1600, 900),
                        ..default()
                    }),
                    ..default()
                })
                // Assets live beside the crate, wherever the binary is run from.
                .set(AssetPlugin { file_path: lookdev::asset_root(), ..default() }),
        )
        .add_plugins(EguiPlugin::default())
        .add_plugins(style::StylePlugin)
        .add_plugins(post::PostPlugin)
        .add_systems(PostUpdate, post::update)
        .init_non_send::<net::Net>()
        .init_non_send::<world::Scene>()
        .init_resource::<world::Palette>()
        .init_resource::<world::Draw>()
        .init_resource::<sight::Sight>()
        .init_resource::<bodies::MySize>()
        .init_resource::<camera::Cam>()
        .init_resource::<controls::Target>()
        // You face the cursor by default (mouse look); the demo scripts its own look and cursor.
        .insert_resource(controls::Input::new(std::env::var("LIVING_GAME_DEMO").is_ok()))
        .init_resource::<hud::Hud>()
        .init_resource::<hud::UiWants>()
        .add_systems(EguiPrimaryContextPass, hud::draw);
    if lookdev::enabled() {
        // Look-dev: a fixed scene of models from assets/lookdev, no server.
        app.add_systems(Startup, (world::setup, camera::spawn, sight::setup, lookdev::setup, envs::setup).chain())
            .add_systems(
                Update,
                (envs::hdr, envs::keys, envs::switch, lookdev::convert, lookdev::fit, lookdev::rig, envs::walk, lookdev::animate, lookdev::sun, lookdev::demo, envs::tour, camera::follow, world::fade_trees, envs::cutaway).chain(),
            );
    } else {
        app.add_systems(Startup, (world::setup, camera::spawn, sight::setup))
            .add_systems(
                Update,
                (net::pump, bodies::update, world::things, controls::target, world::terrain, demo::run, controls::movement, camera::follow, world::fade_trees, sight::update, controls::gizmos).chain(),
            );
        if let Some(d) = demo::Demo::from_env() {
            app.insert_resource(d);
        }
    }
    app.run();
}
