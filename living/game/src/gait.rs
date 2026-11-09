//! Locomotion clips by actual speed, so planted feet don't slide.
//!
//! A character's animated file comes with `<file>.clips.json` (`living/tools/blender/animate.py
//! --library`), which gives every clip's baked speed (m/s at playback rate 1) and its natural
//! speed (the take's own, before `animate.py` time-scaled it). Of the looping gaits there:
//! - the walking clips (`walk`, `walk_brisk`) serve speeds up to [`WALK_MAX`], the running ones
//!   (`run`, `run_fast`) above it, so the rules' 2.6 m/s walk still walks and their 3.9 m/s
//!   run runs;
//! - within that family, the clip whose natural speed is nearest (in ratio) plays, so the
//!   cadence stays close to the take's own;
//! - it plays at `speed / (baked speed × stride)`: the planted foot then moves backward exactly
//!   as fast as the body moves forward. `Character::stride` scales a character's steps by its
//!   legs (`characters.rs`).
//!
//! Current clips are kept a little past the boundaries, so a speed that hovers between two clips
//! doesn't flicker between them. Connected bodies (`live.rs`), your own character and the look-dev
//! line-up and crowds (`lookdev.rs`) all pick through [`Gaits::pick`]. Files without the sidecar
//! use the walk and run at the look-dev's 1.4 and 3.6 m/s.
//!
//! **Animals** (the wolf, `living/tools/blender/wolf.py`) have one family of gaits, `walk`,
//! `trot` and `run` (natural 1.3, 3.4 and 7.0 m/s), listed in their sidecar's `clips` array: the
//! nearest in natural speed plays at `speed / natural speed` (× stride, a pup's smaller steps),
//! with the same hold between two gaits.
//!
//! `LIVING_GAME_FEET=<file>` writes, every frame, where your character's toes are and the ground
//! under them (JSON lines), for measuring foot slide (`living/tools/foot_slide.py`).

use bevy::prelude::*;
use std::collections::HashMap;
use std::io::Write;
use std::sync::{Arc, Mutex, OnceLock};

/// Walking clips serve speeds up to this, for a character of the 1.75 m base (m/s).
pub const WALK_MAX: f32 = 2.8;
/// How far past a boundary the current clip is kept: m/s at the walk/run boundary, and in
/// natural-speed ratio (log) between two clips of a family.
const HOLD_MS: f32 = 0.15;
const HOLD_LOG: f32 = 0.05;

/// One looping locomotion clip.
#[derive(Clone, Copy, Debug)]
pub struct Gait {
    pub clip: &'static str,
    /// m/s at playback rate 1 (after `animate.py`'s time scale).
    pub speed: f32,
    /// m/s of the take at its own cadence.
    pub natural: f32,
    pub run: bool,
}

/// A character file's locomotion clips, and whether they split into walking and running
/// families at [`WALK_MAX`] (people) or are one family (animals).
#[derive(Debug)]
pub struct Gaits {
    clips: Vec<Gait>,
    split: bool,
}

/// The clips this module chooses between, and whether each is a run.
const LOCOMOTION: [(&str, bool); 4] = [("walk", false), ("walk_brisk", false), ("run", true), ("run_fast", true)];
/// An animal's gaits, one family.
const ANIMAL: [&str; 3] = ["walk", "trot", "run"];

impl Gaits {
    fn fallback() -> Self {
        Self {
            clips: vec![
                Gait { clip: "walk", speed: crate::lookdev::WALK_SPEED, natural: crate::lookdev::WALK_SPEED, run: false },
                Gait { clip: "run", speed: crate::lookdev::RUN_SPEED, natural: crate::lookdev::RUN_SPEED, run: true },
            ],
            split: true,
        }
    }

    /// From a `clips.json` sidecar: its looping locomotion clips with a speed. A character's
    /// sidecar maps clip names to clips; an animal's lists them under `clips`.
    fn parse(json: &serde_json::Value) -> Self {
        if let Some(list) = json.get("clips").and_then(|c| c.as_array()) {
            let clips: Vec<Gait> = ANIMAL
                .iter()
                .filter_map(|&clip| {
                    let c = list.iter().find(|c| c["name"].as_str() == Some(clip))?;
                    let speed = c["speed"].as_f64()? as f32;
                    (speed > 0.1 && c["loop"].as_bool() != Some(false)).then_some(Gait { clip, speed, natural: speed, run: false })
                })
                .collect();
            return if clips.is_empty() { Self::fallback() } else { Self { clips, split: false } };
        }
        let clips = LOCOMOTION
            .iter()
            .filter_map(|&(clip, run)| {
                let c = json.get(clip)?;
                let speed = c["speed"].as_f64()? as f32;
                let natural = c["natural_speed"].as_f64().map_or(speed, |n| n as f32);
                (speed > 0.1 && natural > 0.1 && c["loop"].as_bool() != Some(false)).then_some(Gait { clip, speed, natural, run })
            })
            .collect::<Vec<_>>();
        if clips.iter().any(|g| !g.run) && clips.iter().any(|g| g.run) {
            Self { clips, split: true }
        } else {
            Self::fallback()
        }
    }

    /// The clip and playback rate for moving at `speed` (m/s) with steps `stride` times the
    /// base's, given the clip playing now (kept near boundaries).
    pub fn pick(&self, speed: f32, stride: f32, current: Option<&str>) -> (&'static str, f32) {
        let stride = stride.max(0.05);
        let s = speed / stride;
        let now = self.clips.iter().find(|g| Some(g.clip) == current);
        let walk_max = match now {
            Some(g) if g.run => WALK_MAX - HOLD_MS,
            Some(_) => WALK_MAX + HOLD_MS,
            None => WALK_MAX,
        };
        let run = self.split && s > walk_max;
        let cost = |g: &Gait| (s / g.natural).ln().abs() - if Some(g.clip) == current { HOLD_LOG } else { 0.0 };
        let best = self.clips.iter().filter(|g| g.run == run).min_by(|a, b| cost(a).total_cmp(&cost(b))).or_else(|| self.clips.first());
        match best {
            Some(g) => (g.clip, speed / (g.speed * stride)),
            None => ("walk", 1.0),
        }
    }
}

/// The locomotion clips of a character file (cached; `<file stem>.clips.json`).
pub fn of(file: &str) -> Arc<Gaits> {
    static CACHE: OnceLock<Mutex<HashMap<String, Arc<Gaits>>>> = OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    if let Some(g) = cache.lock().unwrap().get(file) {
        return g.clone();
    }
    let path = std::path::Path::new(&crate::lookdev::asset_root()).join(file).with_extension("clips.json");
    let gaits = Arc::new(match std::fs::read(&path).ok().and_then(|b| serde_json::from_slice::<serde_json::Value>(&b).ok()) {
        Some(json) => Gaits::parse(&json),
        None => Gaits::fallback(),
    });
    debug!("gait: {file}: {:?}", gaits.clips);
    cache.lock().unwrap().insert(file.to_string(), gaits.clone());
    gaits
}

/// Marks your character in connected play, whose feet `LIVING_GAME_FEET` records (look-dev's is
/// `envs::Player`).
#[derive(Component)]
pub struct Feet;

pub struct GaitPlugin;

impl Plugin for GaitPlugin {
    fn build(&self, app: &mut App) {
        let Some(path) = std::env::var("LIVING_GAME_FEET").ok().filter(|p| !p.is_empty()) else { return };
        match std::fs::File::create(&path) {
            Ok(f) => {
                app.insert_resource(FeetLog(std::io::BufWriter::new(f))).add_systems(Last, record);
            }
            Err(e) => warn!("gait: can't write {path}: {e}"),
        }
    }
}

#[derive(Resource)]
struct FeetLog(std::io::BufWriter<std::fs::File>);

/// One line a frame: time, the body's root, each toe and the ground under it, and the clip.
#[allow(clippy::type_complexity)]
fn record(
    mut log: ResMut<FeetLog>,
    time: Res<Time>,
    island: Option<Res<crate::island::Island>>,
    who: Query<(Entity, &GlobalTransform), Or<(With<Feet>, With<crate::envs::Player>)>>,
    children: Query<&Children>,
    bones: Query<(&Name, &GlobalTransform)>,
    live: Query<&crate::live::LiveBody>,
    lookdev: Query<&crate::lookdev::Clips>,
    roam: Res<crate::envs::Roam>,
    mut toes: Local<HashMap<Entity, [Entity; 2]>>,
) {
    let ground = |x: f32, z: f32| island.as_ref().map_or(0.0, |i| i.height(x, z));
    for (e, root) in &who {
        if !toes.contains_key(&e) {
            let find = |name: &str| children.iter_descendants(e).find(|d| bones.get(*d).is_ok_and(|(n, _)| n.as_str() == name));
            if let (Some(l), Some(r)) = (find("J_Bip_L_ToeBase"), find("J_Bip_R_ToeBase")) {
                toes.insert(e, [l, r]);
            } else {
                continue;
            }
        }
        let [l, r] = toes[&e];
        let (Ok((_, l)), Ok((_, r))) = (bones.get(l), bones.get(r)) else {
            toes.remove(&e);
            continue;
        };
        let (l, r, p) = (l.translation(), r.translation(), root.translation());
        let clip = live.get(e).map(|b| b.showing()).ok().or_else(|| lookdev.get(e).ok().and_then(|c| c.playing())).unwrap_or("");
        let line = serde_json::json!({
            "t": time.elapsed_secs_f64(),
            "root": [p.x, p.y, p.z],
            "l": [l.x, l.y, l.z, ground(l.x, l.z)],
            "r": [r.x, r.y, r.z, ground(r.x, r.z)],
            "speed": roam.speed,
            "clip": clip,
        });
        let _ = writeln!(log.0, "{line}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Vivi's sidecar speeds (`assets/lookdev/anim/vroid-Vivi.clips.json`).
    fn vivi() -> Gaits {
        Gaits::parse(&serde_json::json!({
            "walk": {"speed": 1.389, "natural_speed": 1.435, "loop": true},
            "walk_brisk": {"speed": 2.028, "natural_speed": 2.028, "loop": true},
            "run": {"speed": 3.67, "natural_speed": 3.146, "loop": true},
            "run_fast": {"speed": 3.497, "natural_speed": 3.497, "loop": true},
            "sneak": {"speed": 0.747, "natural_speed": 0.747, "loop": true},
        }))
    }

    #[test]
    fn speeds_pick_the_nearest_gait_and_match_its_feet() {
        let g = vivi();
        for (speed, clip) in [(1.4, "walk"), (2.6, "walk_brisk"), (3.0, "run"), (3.6, "run_fast"), (3.9, "run_fast")] {
            let (c, rate) = g.pick(speed, 1.0, None);
            assert_eq!(c, clip, "at {speed} m/s");
            let baked = g.clips.iter().find(|x| x.clip == c).unwrap().speed;
            assert!((rate * baked - speed).abs() < 1e-4, "feet move at the body's speed");
        }
    }

    #[test]
    fn longer_legs_step_slower_and_walk_further() {
        let g = vivi();
        // A giant twice the base's stride walks at 2.6 m/s with the casual walk, at half its rate.
        let (c, rate) = g.pick(2.6, 2.0, None);
        assert_eq!(c, "walk");
        assert!((rate - 2.6 / (1.389 * 2.0)).abs() < 1e-4);
    }

    #[test]
    fn the_current_gait_holds_near_a_boundary() {
        let g = vivi();
        assert_eq!(g.pick(WALK_MAX + 0.05, 1.0, Some("walk_brisk")).0, "walk_brisk");
        assert_eq!(g.pick(WALK_MAX - 0.05, 1.0, Some("run")).0, "run");
        assert_eq!(g.pick(WALK_MAX + 0.05, 1.0, None).0, "run");
    }

    /// The wolf's sidecar (`assets/lookdev/anim/wolf.clips.json`, from wolf.py).
    fn wolf() -> Gaits {
        Gaits::parse(&serde_json::json!({"model": "wolf", "clips": [
            {"name": "idle", "seconds": 3.0, "loop": true},
            {"name": "walk", "seconds": 0.8, "loop": true, "speed": 1.3},
            {"name": "trot", "seconds": 0.44, "loop": true, "speed": 3.4},
            {"name": "run", "seconds": 0.32, "loop": true, "speed": 7.0},
            {"name": "bite", "seconds": 0.85, "loop": false},
        ]}))
    }

    #[test]
    fn an_animal_walks_trots_and_runs_by_speed_at_its_natural_cadence() {
        let g = wolf();
        for (speed, clip, rate) in [(1.3, "walk", 1.0), (1.0, "walk", 1.0 / 1.3), (3.4, "trot", 1.0), (4.1, "trot", 4.1 / 3.4), (7.0, "run", 1.0), (5.5, "run", 5.5 / 7.0)] {
            let (c, r) = g.pick(speed, 1.0, None);
            assert_eq!(c, clip, "at {speed} m/s");
            assert!((r - rate).abs() < 1e-4, "{clip} at {speed} m/s plays at {r}, not {rate}");
        }
        // No walk/run split for animals: 2.9 m/s (past people's WALK_MAX) is a trot.
        assert_eq!(g.pick(2.9, 1.0, None).0, "trot");
        // A pup (stage scale 0.42) takes smaller steps: faster cadence at the same speed.
        let (c, r) = g.pick(1.3, 0.42, None);
        assert_eq!(c, "trot");
        assert!((r - 1.3 / (3.4 * 0.42)).abs() < 1e-4);
    }

    #[test]
    fn an_animal_holds_its_gait_near_a_boundary() {
        let g = wolf();
        // walk/trot meet at sqrt(1.3 × 3.4) = 2.10 m/s, trot/run at sqrt(3.4 × 7) = 4.88.
        assert_eq!(g.pick(2.13, 1.0, Some("walk")).0, "walk");
        assert_eq!(g.pick(2.13, 1.0, None).0, "trot");
        assert_eq!(g.pick(2.075, 1.0, Some("trot")).0, "trot");
        assert_eq!(g.pick(2.075, 1.0, None).0, "walk");
        assert_eq!(g.pick(4.8, 1.0, Some("run")).0, "run");
        assert_eq!(g.pick(4.8, 1.0, None).0, "trot");
    }

    #[test]
    fn a_file_without_both_gaits_uses_the_lookdev_speeds() {
        let g = Gaits::parse(&serde_json::json!({"walk": {"speed": 1.4}}));
        assert_eq!(g.pick(3.6, 1.0, None), ("run", 1.0));
    }
}
