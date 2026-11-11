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

mod anim;
mod bodies;
mod camera;
mod capture;
mod characters;
mod combat;
mod controls;
mod daylight;
mod demo;
mod envs;
mod gait;
mod ik;
mod twist;
mod fade;
mod pointer;
mod heard;
mod jump;
mod hud;
mod keys;
mod looks;
mod island;
mod live;
mod loading;
mod lookdev;
mod net;
mod perf;
mod phase;
mod post;
mod probe;
mod route;
mod sight;
mod sightedge;
mod sightfield;
mod sky;
mod talk;
mod style;
mod terrain;
mod town;
mod ui;
mod verbs;
mod vfx;
mod view;
mod water;
mod weather;
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
    perf::diagnostics(&mut app);
    app.add_systems(Update, lookdev::character_shadows);
    app.insert_resource(ClearColor(camera::SKY))
        .add_plugins(style::StylePlugin)
        .add_plugins(post::PostPlugin)
        .add_plugins(characters::CharactersPlugin)
        .add_plugins(gait::GaitPlugin)
        .add_plugins(anim::AnimPlugin)
        .add_plugins(ik::IkPlugin)
        .add_plugins(twist::TwistPlugin)
        .add_plugins(fade::FadePlugin)
        .add_plugins(pointer::PointerPlugin)
        .add_plugins(jump::JumpPlugin)
        .add_plugins(daylight::DaylightPlugin)
        .add_plugins(terrain::TerrainPlugin)
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
    // Key bindings and the Play settings, from the viewer's settings file (`keys.rs`).
    {
        let (binds, prefs) = keys::load();
        app.insert_resource(binds).insert_resource(prefs).init_resource::<keys::DoubleTap>().init_resource::<looks::Looks>();
    }
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
    // The player's UI (Bevy UI); egui stays for the F1 developer panels.
    app.add_plugins(ui::UiPlugin);
    // The first load happens behind a cover (pipelines compile synchronously on macOS).
    app.add_plugins(loading::LoadingPlugin);
    app.add_plugins(route::RoutePlugin);
    if !headless {
        app.add_systems(EguiPrimaryContextPass, hud::draw);
    }
    if lookdev::enabled() {
        // Look-dev: a fixed scene of models from assets/lookdev, no server.
        app.add_plugins(probe::ProbePlugin);
        app.add_systems(Startup, (world::setup, camera::spawn, sight::setup, lookdev::setup, envs::setup).chain())
            .add_systems(
                Update,
                (envs::hdr, envs::keys, envs::switch, island::stream, island::grey_boxes, island::report, lookdev::convert, lookdev::fit, lookdev::rig, envs::walk, lookdev::clips, lookdev::animate, lookdev::sun, lookdev::demo, envs::tour, camera::follow, world::fade_trees, envs::cutaway, envs::reach).chain(),
            );
    } else {
        // A frame's order (phase.rs): net, mirror, input, flush, present, camera.
        phase::configure(&mut app);
        use phase::Phase;
        app.add_systems(Startup, (world::setup, camera::spawn, sight::setup))
            .add_systems(Update, net::pump.in_set(Phase::Net))
            .add_systems(Update, (bodies::update, world::things, controls::target, world::terrain.run_if(live::tiles), looks::update).chain().in_set(Phase::Mirror))
            .add_systems(Update, (demo::run, controls::scheme, keys::double_tap, controls::movement).chain().in_set(Phase::Input))
            .add_systems(Update, net::flush.in_set(Phase::Flush))
            .add_systems(Update, (camera::follow, world::fade_trees, sight::update, controls::gizmos).chain().in_set(Phase::Camera));
        // Land worlds (the island the authority hosts) draw through the island renderer.
        app.add_plugins(live::LivePlugin);
        // Combat: skill input, perceived events, clips and effects (docs/COMBAT.md).
        app.add_plugins((combat::CombatPlugin, vfx::VfxPlugin));
        // Town life: what residents are seen doing, my gestures, the authority's weather
        // (docs/TOWN_LIFE.md).
        app.add_plugins(town::TownPlugin);
        // Verbs: acts on what is in front of me and on myself, offered from the world's rules.
        app.add_plugins(verbs::VerbsPlugin);
        // Whom the text box speaks to: the person pointed at or the nearest within earshot.
        app.add_plugins(talk::TalkPlugin);
        // How the edge of my sight is shown: fade, not seen now, limited view (F2).
        app.add_plugins(sightedge::SightEdgePlugin);
        app.add_plugins(sightfield::SightFieldPlugin);
        if let Some(d) = demo::Demo::from_env() {
            app.insert_resource(d);
        }
    }
    app.run();
}
