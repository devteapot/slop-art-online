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
    mut my_size: ResMut<crate::bodies::MySize>,
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
        Act::Size(k) => my_size.0 = *k,
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
        Act::Turn(rate) => input.scripted_turn = *rate,
        Act::Align => cam.align_request = true,
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
    Size(f32),
    Shot(&'static str),
    Walk(Vec2),
    Stop,
    Say(&'static str),
    Sight(bool, f32, f32),
    Look(Option<Vec2>),
    Turn(Option<f32>),
    Align,
    Log(&'static str),
    Exit,
}

/// (seconds after the previous step, action). Pictures are taken a moment after each change
/// so they never show the frame in which the camera moved.
const STEPS: &[(f32, Act)] = &[
    // Let terrain and people build around the player first.
    (5.0, Act::Shot("view")),
    (0.1, Act::Log("the view")),
    // Rotate 90° with [ ] (it stays), and back.
    (0.1, Act::Turn(Some(90.0))),
    (1.0, Act::Turn(None)),
    (1.5, Act::Shot("rotated-90")),
    (0.1, Act::Log("rotated 90°")),
    (0.1, Act::Turn(Some(-90.0))),
    (1.0, Act::Turn(None)),
    // Align on request: facing south-east, press R; the view turns until south-east is ahead.
    (0.5, Act::Look(Some(Vec2::new(1.0, 1.0)))),
    (0.3, Act::Log("before align, facing south-east")),
    (0.1, Act::Align),
    (1.5, Act::Log("after align")),
    (0.1, Act::Shot("aligned-south-east")),
    (0.3, Act::Look(Some(Vec2::new(0.0, -1.0)))),
    (0.1, Act::Align),
    (1.5, Act::Log("after align, facing north")),
    // Walk east for 3 s, looking ahead, then say something.
    (0.5, Act::Look(Some(Vec2::new(1.0, -0.3)))),
    (0.2, Act::Walk(Vec2::X)),
    (1.2, Act::Shot("walking")),
    (1.8, Act::Stop),
    (1.5, Act::Say("Hello! Is anyone around here?")),
    // Long enough for someone nearby to answer (the verification run has a second player
    // speak here) and for the camera to frame the conversation.
    (6.0, Act::Shot("talk-framing")),
    (9.0, Act::Look(None)),
    // Other sizes of character: the camera scales with them.
    (0.1, Act::Size(2.5)),
    (2.5, Act::Shot("size-giant")),
    (0.1, Act::Size(0.55)),
    (2.5, Act::Shot("size-small")),
    (0.1, Act::Size(1.0)),
    // Night sight brings the view in.
    (0.1, Act::Sight(true, 6.0, 180.0)),
    (2.5, Act::Shot("night-sight")),
    (0.1, Act::Sight(false, 11.0, 180.0)),
    (0.5, Act::Exit),
];
