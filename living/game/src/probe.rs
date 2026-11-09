//! Scripted animation probes for measurement in look-dev (`LIVING_GAME_LOOKDEV=1`): speed ramps,
//! one-shots over locomotion and frame sequences. Each is off unless its variable is set.
//!
//! - `LIVING_GAME_RAMP=<peak m/s>:<seconds>[:<hold s>]`: while you walk
//!   (`LIVING_GAME_AUTOWALK` or a route), your speed ramps from 0 to the peak and back over
//!   `seconds`, then you stand for `hold` (default 1.5 s), and again (`envs::walk`).
//! - `LIVING_GAME_ONESHOT=<clip>[*<rate>][+<clip>[*<rate>]…]:<every s>`: your character plays
//!   these one-shots in turn, one every `every` seconds (the first after one interval), over
//!   whatever it is doing.
//! - `LIVING_GAME_SEQ=<dir>:<start s>:<every s>:<count>`: photographs `<dir>/seq-0000.png` … every
//!   `every` seconds from `start` seconds after the first load's cover lifts, then quits. Run it
//!   headless on the tour's switch (`LIVING_GAME_TOUR=<dir>`, `LIVING_GAME_TOUR_ONLY=<env>`,
//!   `LIVING_GAME_TOUR_SHOTS=default`); it holds the tour's exit until the last photograph.
//!   `LIVING_GAME_SEQ_VIEW=YAW:PITCH:DISTANCE[:FOV]` poses the camera (degrees and metres, yaw 0
//!   looking north, as the tour's shots).
//!
//! Times count from the moment the cover lifts (`loading.rs`), so runs line up.

use bevy::ecs::message::Messages;
use bevy::prelude::*;
use std::path::PathBuf;

pub struct ProbePlugin;

impl Plugin for ProbePlugin {
    fn build(&self, app: &mut App) {
        let probe = Probe::from_env();
        let seq = probe.seq.is_some();
        app.insert_resource(probe).add_systems(First, start);
        if seq {
            app.add_systems(Update, sequence.after(crate::camera::follow)).add_systems(Last, hold_exit);
        }
    }
}

struct Seq {
    dir: PathBuf,
    start: f32,
    every: f32,
    count: usize,
    view: Option<(crate::camera::View, f32)>,
    taken: usize,
}

#[derive(Resource)]
pub struct Probe {
    ramp: Option<(f32, f32, f32)>,
    oneshots: Vec<(String, f32)>,
    every: f32,
    seq: Option<Seq>,
    /// When the cover lifted (elapsed s).
    t0: Option<f32>,
}

impl Probe {
    fn from_env() -> Self {
        let var = |k: &str| std::env::var(k).ok().filter(|v| !v.is_empty());
        let nums = |s: &str| s.split(':').filter_map(|x| x.parse::<f32>().ok()).collect::<Vec<_>>();
        let ramp = var("LIVING_GAME_RAMP").and_then(|s| {
            let n = nums(&s);
            (n.len() >= 2).then(|| (n[0], n[1].max(0.5), n.get(2).copied().unwrap_or(1.5)))
        });
        let (oneshots, every) = var("LIVING_GAME_ONESHOT")
            .and_then(|s| {
                let (clips, every) = s.rsplit_once(':')?;
                let list = clips
                    .split('+')
                    .map(|c| match c.split_once('*') {
                        Some((c, r)) => (c.to_string(), r.parse().unwrap_or(1.0)),
                        None => (c.to_string(), 1.0),
                    })
                    .collect();
                Some((list, every.parse().ok()?))
            })
            .unwrap_or((vec![], 0.0));
        let seq = var("LIVING_GAME_SEQ").and_then(|s| {
            let mut parts = s.split(':');
            let dir = PathBuf::from(parts.next()?);
            let n: Vec<f32> = parts.filter_map(|x| x.parse().ok()).collect();
            let view = var("LIVING_GAME_SEQ_VIEW").and_then(|v| {
                let n = nums(&v);
                let fov = n.get(3).copied().unwrap_or(crate::camera::Rig::default().view.fov);
                (n.len() >= 3).then(|| (crate::camera::View { pitch: n[1], distance: n[2], fov }, n[0]))
            });
            let _ = std::fs::create_dir_all(&dir);
            (n.len() >= 3).then(|| Seq { dir, start: n[0], every: n[1].max(0.0), count: n[2] as usize, view, taken: 0 })
        });
        Self { ramp, oneshots, every, seq, t0: None }
    }

    /// Seconds since the cover lifted.
    fn since(&self, now: f32) -> Option<f32> {
        self.t0.map(|t| now - t)
    }

    /// Your speed under `LIVING_GAME_RAMP` at elapsed time `now` (0 while standing).
    pub fn ramp_speed(&self, now: f32) -> Option<f32> {
        let (peak, secs, hold) = self.ramp?;
        let Some(t) = self.since(now) else { return Some(0.0) };
        let t = t % (secs + hold);
        let half = secs * 0.5;
        Some(if t < half { peak * t / half } else if t < secs { peak * (secs - t) / half } else { 0.0 })
    }

    /// The one-shot `LIVING_GAME_ONESHOT` has playing at elapsed time `now`: its clip, rate and
    /// start (elapsed s).
    pub fn oneshot(&self, now: f32) -> Option<(&str, f32, f32)> {
        let t = self.since(now)?;
        if self.oneshots.is_empty() || self.every <= 0.0 {
            return None;
        }
        let k = (t / self.every).floor() as usize;
        if k == 0 {
            return None;
        }
        let (clip, rate) = &self.oneshots[(k - 1) % self.oneshots.len()];
        Some((clip.as_str(), *rate, self.t0? + k as f32 * self.every))
    }
}

fn start(mut probe: ResMut<Probe>, time: Res<Time>, loading: Option<Res<crate::loading::Loading>>) {
    if probe.t0.is_none() && crate::loading::Loading::clear(loading.as_deref()) {
        probe.t0 = Some(time.elapsed_secs());
    }
}

fn sequence(mut commands: Commands, mut probe: ResMut<Probe>, mut cam: ResMut<crate::camera::Cam>, time: Res<Time>, target: Option<Res<crate::capture::Target>>, mut exit: MessageWriter<AppExit>) {
    let now = time.elapsed_secs();
    let Some(t) = probe.since(now) else { return };
    let Some(seq) = probe.seq.as_mut() else { return };
    if let Some((view, yaw)) = seq.view {
        cam.rig.sight_bound = false;
        cam.rig.view = view;
        cam.set_yaw(yaw);
    }
    if seq.taken >= seq.count {
        if t > seq.start + seq.every * seq.count as f32 + 1.0 {
            seq.view = None;
            probe.seq = None;
            exit.write(AppExit::Success);
        }
        return;
    }
    if t >= seq.start + seq.every * seq.taken as f32 {
        crate::capture::shot(&mut commands, target.as_deref(), seq.dir.join(format!("seq-{:04}.png", seq.taken)));
        seq.taken += 1;
    }
}

/// Hold the tour's exit until the sequence is done.
fn hold_exit(probe: Res<Probe>, mut exits: ResMut<Messages<AppExit>>) {
    if probe.seq.is_some() {
        exits.clear();
    }
}
