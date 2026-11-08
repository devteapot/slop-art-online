//! Scripted demo for evidence (`LIVING_GAME_DEMO=<dir>`): once the player's character is in
//! view, screenshot every camera preset, walk east for three seconds through the same
//! `human_move` path the keys use, say a line, screenshot again, and quit. It logs the
//! character's authoritative position before and after the walk.

use crate::camera::{Cam, PRESETS};
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
    let n = PRESETS.len();
    let d = &mut *demo;
    let since = now - d.at;
    let wait = |s: f32| since >= s;
    match d.step {
        // Let terrain chunks build around the player first.
        0 if wait(4.0) => {
            cam.set_preset(0);
            d.step = 1;
            d.at = now;
        }
        // Odd steps photograph preset k; even steps switch to the next one, a moment later, so
        // a picture never shows the frame in which the camera changed.
        s if (1..2 * n).contains(&s) && s % 2 == 1 && wait(1.5) => {
            shot(&mut commands, &d.dir, &format!("camera-{}", s / 2 + 1));
            d.step += 1;
            d.at = now;
        }
        s if (1..2 * n).contains(&s) && s % 2 == 0 && wait(0.3) => {
            cam.set_preset(s / 2);
            d.step += 1;
            d.at = now;
        }
        s if s == 2 * n - 1 + 1 && wait(0.3) => {
            cam.set_preset(0);
            d.step += 1;
            d.at = now;
        }
        s if s == 2 * n + 1 && wait(1.0) => {
            d.start = net.my_body().map(|b| (b.x, b.y));
            info!("demo: before walking, authority position {:?}", d.start);
            input.scripted = Some((Vec2::X, false));
            d.step += 1;
            d.at = now;
        }
        s if s == 2 * n + 2 && wait(3.0) => {
            input.scripted = Some((Vec2::ZERO, false));
            d.step += 1;
            d.at = now;
        }
        s if s == 2 * n + 3 && wait(1.5) => {
            let end = net.my_body().map(|b| (b.x, b.y));
            info!("demo: after walking east 3 s, authority position {end:?} (from {:?})", d.start);
            input.scripted = None;
            let line = "Hello! Is anyone around here?";
            if controls::say(&net, line) {
                input.said.push((crate::clock::now_ms(), line.into()));
            }
            d.step += 1;
            d.at = now;
        }
        // Long enough for someone nearby to answer (the verification run has a second player
        // speak here).
        s if s == 2 * n + 4 && wait(6.0) => {
            shot(&mut commands, &d.dir, "after-walk-and-talk");
            d.step += 1;
            d.at = now;
        }
        s if s == 2 * n + 5 && wait(1.5) => {
            for e in net.errors.lock().unwrap().iter() {
                warn!("demo: reported error: {e}");
            }
            info!("demo: done");
            exit.write(AppExit::Success);
        }
        _ => {}
    }
}
