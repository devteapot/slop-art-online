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
mod capture;
mod characters;
mod controls;
mod demo;
mod envs;
mod hud;
mod island;
mod lookdev;
mod net;
mod perf;
mod post;
mod sight;
mod style;
mod view;
mod world;

use bevy::prelude::*;
use bevy_egui::{EguiPlugin, EguiPrimaryContextPass};

fn main() {
    let mut app = App::new();
    let size = capture::size();
    // Assets live beside the crate, wherever the binary is run from.
    let plugins = DefaultPlugins.set(AssetPlugin { file_path: lookdev::asset_root(), ..default() });
    let headless = capture::headless();
    if headless {
        // Scripted photographs: no window; the camera renders into an image (capture.rs).
        app.add_plugins(
            plugins
                .set(WindowPlugin { primary_window: None, exit_condition: bevy::window::ExitCondition::DontExit, ..default() })
                .disable::<bevy::winit::WinitPlugin>(),
        )
        .add_plugins(bevy::app::ScheduleRunnerPlugin::run_loop(perf::cap()))
        .add_systems(PreStartup, capture::setup)
        .add_systems(PostUpdate, capture::attach.before(post::update));
    } else {
        app.add_plugins(plugins.set(WindowPlugin {
            primary_window: Some(Window {
                title: "Slop Art Online — camera spike".into(),
                resolution: bevy::window::WindowResolution::new(size.x, size.y),
                ..default()
            }),
            ..default()
        }))
        .add_plugins(EguiPlugin::default());
    }
    app.add_systems(PostUpdate, perf::apply.before(post::update));
    app.add_systems(Update, lookdev::character_shadows);
    app.insert_resource(ClearColor(camera::SKY))
        .add_plugins(style::StylePlugin)
        .add_plugins(post::PostPlugin)
        .add_plugins(characters::CharactersPlugin)
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
        .init_resource::<hud::UiWants>();
    if view::enabled() {
        // Asset view: models through the game's renderer, no server and no panels.
        if !headless {
            app.add_systems(EguiPrimaryContextPass, || {});
        }
        app.insert_resource(envs::Roam::default())
            .add_systems(Startup, (world::setup, camera::spawn, lookdev::setup, view::setup).chain())
            .add_systems(Update, (envs::hdr, lookdev::convert, lookdev::fit, view::clips, lookdev::rig, lookdev::animate, lookdev::sun, view::layout, view::interact, view::batch).chain());
        app.run();
        return;
    }
    if !headless {
        app.add_systems(EguiPrimaryContextPass, hud::draw);
    }
    if lookdev::enabled() {
        // Look-dev: a fixed scene of models from assets/lookdev, no server.
        app.add_systems(Startup, (world::setup, camera::spawn, sight::setup, lookdev::setup, envs::setup).chain())
            .add_systems(
                Update,
                (envs::hdr, envs::keys, envs::switch, island::stream, island::report, lookdev::convert, lookdev::fit, lookdev::rig, envs::walk, lookdev::clips, lookdev::animate, lookdev::sun, lookdev::demo, envs::tour, camera::follow, world::fade_trees, envs::cutaway).chain(),
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
