//! Scripted demo for evidence (`LIVING_GAME_DEMO=<dir>`): once the player's character is in
//! view, screenshot every camera preset, walk east for three seconds through the same
//! `human_move` path the keys use, say a line, screenshot again, and quit. It logs the
//! character's authoritative position before and after the walk.

use crate::camera::Cam;
use crate::controls::{self, Input};
use crate::net::Net;
use bevy::prelude::*;
use bevy::render::view::screenshot::{save_to_disk, Screenshot};

#[derive(Resource)]
pub struct Demo {
    dir: std::path::PathBuf,
    step: usize,
    at: f32,
    start: Option<(f32, f32)>,
}

impl Demo {
    pub fn from_env() -> Option<Self> {
        let dir = std::env::var("LIVING_GAME_DEMO").ok().filter(|d| !d.is_empty())?;
        std::fs::create_dir_all(&dir).ok()?;
        Some(Self { dir: dir.into(), step: 0, at: 0.0, start: None })
    }
}

fn shot(commands: &mut Commands, dir: &std::path::Path, name: &str) {
    let path = dir.join(format!("{name}.png"));
    info!("demo: screenshot {}", path.display());
    commands.spawn(Screenshot::primary_window()).observe(save_to_disk(path));
}

pub fn run(
    mut commands: Commands,
    demo: Option<ResMut<Demo>>,
    net: NonSend<Net>,
    mut cam: ResMut<Cam>,
    mut input: ResMut<Input>,
    mut sight: ResMut<crate::sight::Sight>,
    target: Res<controls::Target>,
    time: Res<Time>,
    mut exit: MessageWriter<AppExit>,
) {
    let Some(mut demo) = demo else { return };
    let now = time.elapsed_secs();
    if target.0.is_none() {
        demo.at = now;
        return;
    }
    let Some(&(after, ref act)) = STEPS.get(demo.step) else { return };
    if now - demo.at < after {
        return;
    }
    let d = &mut *demo;
    match act {
        Act::Preset(i, zoom) => {
            cam.set_preset(*i);
            cam.zoom = *zoom;
        }
        Act::Zoom(z) => cam.zoom = *z,
        Act::Shot(name) => shot(&mut commands, &d.dir, name),
        Act::Walk(dir) => {
            d.start = net.my_body().map(|b| (b.x, b.y));
            info!("demo: before walking, authority position {:?}", d.start);
            input.scripted = Some((*dir, false));
        }
        Act::Stop => input.scripted = Some((Vec2::ZERO, false)),
        Act::Sight(on, radius, cone) => {
            sight.enabled = *on;
            sight.radius = *radius;
            sight.cone = *cone;
        }
        Act::Look(dir) => input.scripted_look = *dir,
        Act::Glance(g) => cam.scripted_glance = *g,
        Act::Log(what) => info!("demo: {what}: camera yaw {:.0}°, pitch {:.0}°, sight {} r {:.0} cone {:.0}", cam.shown_yaw, cam.shown.pitch, sight.enabled, sight.radius, sight.cone),
        Act::Say(line) => {
            let end = net.my_body().map(|b| (b.x, b.y));
            info!("demo: after walking east 3 s, authority position {end:?} (from {:?})", d.start);
            input.scripted = None;
            if controls::say(&net, line) {
                input.said.push((crate::clock::now_ms(), (*line).into()));
            }
        }
        Act::Exit => {
            for e in net.errors.lock().unwrap().iter() {
                warn!("demo: reported error: {e}");
            }
            info!("demo: done (camera now pitch {:.0}°, framing {:?})", cam.shown.pitch, cam.talk_partner);
            exit.write(AppExit::Success);
        }
    }
    d.step += 1;
    d.at = now;
}

enum Act {
    Preset(usize, f32),
    Zoom(f32),
    Shot(&'static str),
    Walk(Vec2),
    Stop,
    Say(&'static str),
    Sight(bool, f32, f32),
    Look(Option<Vec2>),
    Glance(Option<f32>),
    Log(&'static str),
    Exit,
}

/// (seconds after the previous step, action). Pictures are taken a moment after each change
/// so they never show the frame in which the camera moved.
const STEPS: &[(f32, Act)] = &[
    (4.0, Act::Preset(0, 0.5)),
    (2.0, Act::Shot("camera-1")),
    (0.3, Act::Preset(1, 0.5)),
    (2.0, Act::Shot("camera-2")),
    (0.3, Act::Preset(2, 0.5)),
    (2.0, Act::Shot("camera-3")),
    // The common default: mid zoom, then zoomed out as far as day sight allows, then with
    // scout sight (more sight, more room to zoom out).
    (0.3, Act::Preset(4, 0.55)),
    (2.5, Act::Shot("default-mid")),
    (0.1, Act::Log("default mid")),
    (0.2, Act::Zoom(0.0)),
    (2.5, Act::Shot("default-out-day-sight")),
    (0.1, Act::Log("default out, day sight")),
    (0.2, Act::Sight(false, 20.0, 180.0)),
    (0.1, Act::Zoom(0.0)),
    (2.5, Act::Shot("default-out-scout-sight")),
    (0.1, Act::Log("default out, scout sight")),
    (0.2, Act::Sight(false, 11.0, 180.0)),
    // Default camera: a short step back toward the camera keeps the view; a sustained walk turns it.
    (0.3, Act::Preset(4, 0.55)),
    (1.5, Act::Walk(Vec2::Y)),
    (0.8, Act::Log("default, 0.8 s walking toward the camera")),
    (0.1, Act::Stop),
    (1.0, Act::Walk(Vec2::Y)),
    (3.5, Act::Log("default, 3.5 s walking toward the camera")),
    (0.1, Act::Shot("default-after-turning-around")),
    (0.2, Act::Stop),
    // Glance 90° to the right, then let go.
    (0.5, Act::Glance(Some(90.0))),
    (1.5, Act::Shot("default-glance")),
    (0.1, Act::Log("glancing")),
    (0.1, Act::Glance(None)),
    (1.5, Act::Log("after the glance")),
    (0.3, Act::Preset(3, 0.0)),
    (2.5, Act::Shot("tilt-far")),
    (0.3, Act::Zoom(0.55)),
    (2.5, Act::Shot("tilt-mid")),
    (0.3, Act::Zoom(1.0)),
    (2.5, Act::Shot("tilt-near")),
    (0.3, Act::Preset(3, 0.35)),
    (1.0, Act::Walk(Vec2::X)),
    (3.0, Act::Stop),
    (1.5, Act::Say("Hello! Is anyone around here?")),
    // Long enough for someone nearby to answer (the verification run has a second player
    // speak here) and for the camera to frame the conversation.
    (6.0, Act::Shot("talk-framing")),
    // Zoomed all the way in with zoom blend, walking south: the view should come round behind.
    (0.5, Act::Preset(3, 1.0)),
    (8.5, Act::Walk(Vec2::Y)),
    (3.5, Act::Shot("blend-walking-south")),
    (0.1, Act::Log("walking south, zoom blend")),
    (0.2, Act::Stop),
    // Perception mock: day sight in a forward cone, looking east.
    (0.5, Act::Look(Some(Vec2::X))),
    (0.1, Act::Sight(true, 11.0, 60.0)),
    (3.0, Act::Shot("sight-cone-day")),
    (0.1, Act::Log("cone")),
    (0.2, Act::Sight(true, 6.0, 180.0)),
    (2.0, Act::Shot("sight-night")),
    // The high view with sight limited reveals nothing more than the character perceives.
    (0.2, Act::Look(None)),
    (0.1, Act::Preset(1, 0.5)),
    (0.1, Act::Sight(true, 11.0, 180.0)),
    (2.5, Act::Shot("sight-high-view")),
    (0.5, Act::Exit),
];
