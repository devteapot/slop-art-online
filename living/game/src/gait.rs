//! Locomotion by actual speed, blended at one shared phase so feet neither slide nor cross.
//!
//! A character's animated file comes with `<file>.clips.json` (`living/tools/blender/animate.py
//! --library`; the wolf's from `wolf.py`), which gives every clip's length and, for the looping
//! gaits, the baked speed (m/s at playback rate 1) and natural speed (the take's own, before
//! `animate.py` time-scaled it). It also gives each clip's **foot-down markers**: every foot's
//! contact windows in normalised clip time ([`Contacts`]), detected from the baked take. Every
//! gait of a family starts at the same event (a person's right foot coming down, the wolf's left
//! hind paw), so one phase means the same footfall in all of them.
//!
//! [`Gaits::blend`] turns a speed into at most two gait weights and the distance one cycle
//! covers; `anim.rs` plays the weighted gaits at one shared phase:
//! - **People** blend between neighbours in natural speed within a family (walk ↔ walk_brisk,
//!   run ↔ run_fast) across the whole gap, and across families (walk_brisk ↔ run) only in a
//!   band of ±[`CROSS_BAND`] round [`WALK_MAX`], so the rules' 2.6 m/s walk still walks and
//!   their 3.9 m/s run runs.
//! - **Animals** (the wolf: walk, trot, run at natural 1.3, 3.4 and 7.0 m/s; the deer: walk,
//!   trot, bound at 1.3, 3.7 and 4.6) change footfall pattern between gaits (lateral walk,
//!   diagonal trot, gallop or bound): halfway blends of two patterns shuffle, so they blend only
//!   within ±10% round the geometric mean of two neighbours, or the sidecar's `band` (the deer's
//!   ±4%, so the rules' deer trot at 3.7 m/s and flee at 4.26 each play one gait).
//! - The phase advances at `speed / (stride × cycle)`, where `cycle` is the weighted mean of the
//!   gaits' metres per cycle (baked speed × length). Each gait then moves its planted foot back at
//!   its own share of the body's speed, and their blend at the body's speed: the stride rule of
//!   the single-clip version (`speed / (baked speed × stride)`) is the one-gait case.
//!   `Character::stride` scales a character's steps by its legs (`characters.rs`); a pup's
//!   stage scale does the same.
//!
//! Weights are continuous in speed, so no hysteresis is needed between gaits; the drawn speed is
//! eased before it gets here (`live.rs`). Files without the sidecar use the walk and run at the
//! look-dev's 1.4 and 3.6 m/s with their clips' own lengths.
//!
//! `LIVING_GAME_FEET=<file>` writes, every frame, where your character's toes and ankles (an
//! animal's paw tips: `LIVING_GAME_PLAYER=beast:wolf` in look-dev) are and the ground under them, the clip that shows most and, through `anim.rs`, the shared phase and
//! each foot's marker contact (JSON lines), for measuring foot slide
//! (`living/tools/foot_slide.py`) and checking markers.

use bevy::prelude::*;
use std::collections::HashMap;
use std::io::Write;
use std::sync::{Arc, Mutex, OnceLock};

/// Walking clips serve speeds up to this, for a character of the 1.75 m base (m/s).
pub const WALK_MAX: f32 = 2.8;
/// Half the width of the walk ↔ run blend round [`WALK_MAX`] (m/s).
pub const CROSS_BAND: f32 = 0.2;
/// Animals blend two gaits within this ratio either side of their geometric mean, unless their
/// sidecar gives its own `band`.
const ANIMAL_BAND: f32 = 1.1;

/// Each foot's contact windows over a clip, in normalised clip time (0–1). People's feet are
/// `[L, R]`; an animal's are its sidecar's paws in [`ANIMAL_FEET`] order.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Contacts(Vec<Vec<(f32, f32)>>);

/// People's feet in sidecar order.
pub const PEOPLE_FEET: [&str; 2] = ["L", "R"];
/// An animal's paws in sidecar order: fore left, fore right, hind left, hind right.
pub const ANIMAL_FEET: [&str; 4] = ["fl", "fr", "hl", "hr"];

impl Contacts {
    fn parse(v: &serde_json::Value, feet: &[&str]) -> Self {
        let Some(m) = v.as_object() else { return Self::default() };
        let wins = |f: &str| -> Option<Vec<(f32, f32)>> {
            m.get(f)?.as_array()?.iter().map(|w| Some((w.get(0)?.as_f64()? as f32, w.get(1)?.as_f64()? as f32))).collect()
        };
        let all: Option<Vec<_>> = feet.iter().map(|f| wins(f)).collect();
        all.map_or_else(Self::default, Self)
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn feet(&self) -> usize {
        self.0.len()
    }

    /// Whether `foot` is down at clip time `t` (wrapped into 0–1).
    pub fn down(&self, foot: usize, t: f32) -> bool {
        let t = t.rem_euclid(1.0);
        self.0.get(foot).is_some_and(|w| w.iter().any(|&(a, b)| t >= a && t < b.max(a + 1e-4) || (b >= 1.0 && t >= a)))
    }

    /// How planted `foot` is at clip time `t`: 1 inside a window, easing to 0 over `ramp` (clip
    /// time) past each end, so IK fades in at touchdown and out at lift-off. In a loop, distances
    /// wrap round the seam (windows split there join up).
    pub fn weight(&self, foot: usize, t: f32, ramp: f32, cyclic: bool) -> f32 {
        let Some(wins) = self.0.get(foot) else { return 0.0 };
        let t = if cyclic { t.rem_euclid(1.0) } else { t.clamp(0.0, 1.0) };
        let mut best: f32 = 0.0;
        for &(a, b) in wins {
            // Distance outside the window (0 inside), across the seam for a loop.
            let outside = |x: f32| {
                if x >= a && x <= b {
                    0.0
                } else if x < a {
                    a - x
                } else {
                    x - b
                }
            };
            let d = if cyclic { outside(t).min(outside(t + 1.0)).min(outside(t - 1.0)) } else { outside(t) };
            let w = if ramp > 0.0 { 1.0 - smoothstep(0.0, ramp, d) } else if d == 0.0 { 1.0 } else { 0.0 };
            best = best.max(w);
        }
        best
    }

    /// The middle of `foot`'s contact that holds clip time 0 (or of its first): mid-stance, the
    /// foot under the hips.
    pub fn mid_stance(&self, foot: usize) -> f32 {
        let Some(w) = self.0.get(foot).filter(|w| !w.is_empty()) else { return 0.0 };
        let &(a, b) = w.iter().find(|&&(a, _)| a <= 0.0).unwrap_or(&w[0]);
        // A window from 0 may continue from one that ends at 1 (split at the seam).
        let before = w.iter().find(|&&(_, e)| e >= 1.0 && a <= 0.0).map_or(0.0, |&(s, _)| 1.0 - s);
        ((a - before + b) * 0.5).rem_euclid(1.0)
    }

    /// How many feet are down at clip time `t`.
    pub fn count(&self, t: f32) -> usize {
        (0..self.0.len()).filter(|&f| self.down(f, t)).count()
    }

    /// The first clip time at or after `t` (looping) where as many feet are down as anywhere in
    /// the cycle: a person's double support, a walk's three paws. Where to settle into standing.
    pub fn next_settle(&self, t: f32) -> f32 {
        const N: usize = 96;
        let most = (0..N).map(|i| self.count(i as f32 / N as f32)).max().unwrap_or(0);
        for i in 0..=N {
            let x = t + i as f32 / N as f32;
            if self.count(x) >= most {
                return x;
            }
        }
        t
    }
}

fn smoothstep(a: f32, b: f32, x: f32) -> f32 {
    let t = ((x - a) / (b - a)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

/// One looping locomotion clip.
#[derive(Clone, Debug)]
pub struct Gait {
    pub clip: &'static str,
    /// m/s at playback rate 1 (after `animate.py`'s time scale).
    pub speed: f32,
    /// m/s of the take at its own cadence.
    pub natural: f32,
    pub run: bool,
    /// Length (s), when the sidecar gives it; else the clip's own (`anim.rs`).
    pub seconds: Option<f32>,
}

/// What `anim.rs` needs of any clip: whether it plays on the upper body over a moving
/// body's gait (`layer: "upper"`), whether foot IK applies (`ik: false` for sitting, lying, …)
/// and its foot-down markers.
#[derive(Clone, Debug, Default)]
pub struct ClipInfo {
    pub upper: bool,
    pub ik: bool,
    pub contacts: Contacts,
}

/// A character file's locomotion clips (sorted by natural speed), whether they split into walking
/// and running families at [`WALK_MAX`] (people) or are one family (animals), and every clip's
/// [`ClipInfo`].
#[derive(Debug, Default)]
pub struct Gaits {
    clips: Vec<Gait>,
    split: bool,
    info: HashMap<String, ClipInfo>,
    /// An animal's blend band (ratio either side of the geometric mean).
    band: f32,
}

/// The gaits playing at a speed: up to two (index into [`Gaits::gaits`], weight), weights
/// summing to 1, and the metres one cycle covers at stride 1 (the weighted mean).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Blend {
    pub parts: [(usize, f32); 2],
    pub n: usize,
    pub cycle_m: f32,
}

impl Blend {
    pub fn parts(&self) -> &[(usize, f32)] {
        &self.parts[..self.n]
    }
}

/// The clips this module chooses between, and whether each is a run.
const LOCOMOTION: [(&str, bool); 4] = [("walk", false), ("walk_brisk", false), ("run", true), ("run_fast", true)];
/// An animal's gaits, one family.
const ANIMAL: [&str; 3] = ["walk", "trot", "run"];

impl Gaits {
    fn fallback() -> Self {
        Self {
            clips: vec![
                Gait { clip: "walk", speed: crate::lookdev::WALK_SPEED, natural: crate::lookdev::WALK_SPEED, run: false, seconds: None },
                Gait { clip: "run", speed: crate::lookdev::RUN_SPEED, natural: crate::lookdev::RUN_SPEED, run: true, seconds: None },
            ],
            split: true,
            info: HashMap::new(),
            band: ANIMAL_BAND,
        }
    }

    /// From a `clips.json` sidecar: its looping locomotion clips with a speed, and every clip's
    /// info. A character's sidecar maps clip names to clips; an animal's lists them under `clips`.
    fn parse(json: &serde_json::Value) -> Self {
        let info_of = |c: &serde_json::Value, feet: &[&str]| ClipInfo {
            upper: c["layer"].as_str() == Some("upper"),
            ik: c["ik"].as_bool() != Some(false),
            contacts: Contacts::parse(&c["contacts"], feet),
        };
        if let Some(list) = json.get("clips").and_then(|c| c.as_array()) {
            let info = list.iter().filter_map(|c| Some((c["name"].as_str()?.to_string(), info_of(c, &ANIMAL_FEET)))).collect();
            let clips: Vec<Gait> = ANIMAL
                .iter()
                .filter_map(|&clip| {
                    let c = list.iter().find(|c| c["name"].as_str() == Some(clip))?;
                    let speed = c["speed"].as_f64()? as f32;
                    (speed > 0.1 && c["loop"].as_bool() != Some(false)).then_some(Gait { clip, speed, natural: speed, run: false, seconds: c["seconds"].as_f64().map(|s| s as f32) })
                })
                .collect();
            let band = json["band"].as_f64().map_or(ANIMAL_BAND, |b| (b as f32).clamp(1.001, 1.5));
            return if clips.is_empty() { Self { info, ..Self::fallback() } } else { Self { clips, split: false, info, band } };
        }
        let info = json.as_object().map(|m| m.iter().filter(|(_, c)| c.is_object()).map(|(k, c)| (k.clone(), info_of(c, &PEOPLE_FEET))).collect()).unwrap_or_default();
        let mut clips = LOCOMOTION
            .iter()
            .filter_map(|&(clip, run)| {
                let c = json.get(clip)?;
                let speed = c["speed"].as_f64()? as f32;
                let natural = c["natural_speed"].as_f64().map_or(speed, |n| n as f32);
                (speed > 0.1 && natural > 0.1 && c["loop"].as_bool() != Some(false)).then_some(Gait { clip, speed, natural, run, seconds: c["seconds"].as_f64().map(|s| s as f32) })
            })
            .collect::<Vec<_>>();
        if clips.iter().any(|g| !g.run) && clips.iter().any(|g| g.run) {
            // Walks first, then runs, each by natural speed.
            clips.sort_by(|a, b| a.run.cmp(&b.run).then(a.natural.total_cmp(&b.natural)));
            Self { clips, split: true, info, band: ANIMAL_BAND }
        } else {
            Self { info, ..Self::fallback() }
        }
    }

    pub fn gaits(&self) -> &[Gait] {
        &self.clips
    }

    pub fn info(&self, clip: &str) -> Option<&ClipInfo> {
        self.info.get(clip)
    }

    /// The speed band (m/s at stride 1) over which gaits `i` and `i + 1` blend.
    fn band(&self, i: usize) -> (f32, f32) {
        let (a, b) = (&self.clips[i], &self.clips[i + 1]);
        if !self.split {
            let m = (a.natural * b.natural).sqrt();
            (m / self.band, m * self.band)
        } else if a.run != b.run {
            (WALK_MAX - CROSS_BAND, WALK_MAX + CROSS_BAND)
        } else {
            (a.natural, b.natural)
        }
    }

    /// The gaits and their weights for moving at `speed` (m/s) with steps `stride` times the
    /// base's, and the metres a cycle covers at stride 1. `len(i)` gives a gait's length (s) when
    /// the sidecar has none.
    pub fn blend(&self, speed: f32, stride: f32, len: impl Fn(usize) -> f32) -> Blend {
        let s = speed / stride.max(0.05);
        let cycle = |i: usize| {
            let g = &self.clips[i];
            g.speed * g.seconds.unwrap_or_else(|| len(i)).max(0.05)
        };
        let one = |i: usize| Blend { parts: [(i, 1.0), (i, 0.0)], n: 1, cycle_m: cycle(i) };
        if self.clips.is_empty() {
            return Blend { parts: [(0, 0.0); 2], n: 0, cycle_m: 1.0 };
        }
        let mut prev_hi = 0.0f32;
        for i in 0..self.clips.len() - 1 {
            let (lo, hi) = self.band(i);
            let lo = lo.max(prev_hi);
            let hi = hi.max(lo + 0.01);
            prev_hi = hi;
            if s <= lo {
                return one(i);
            }
            if s < hi {
                let t = smoothstep(0.0, 1.0, (s / lo).ln() / (hi / lo).ln());
                if t <= 0.0 {
                    return one(i);
                }
                if t >= 1.0 {
                    return one(i + 1);
                }
                return Blend { parts: [(i, 1.0 - t), (i + 1, t)], n: 2, cycle_m: (1.0 - t) * cycle(i) + t * cycle(i + 1) };
            }
        }
        one(self.clips.len() - 1)
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

/// What the recorder follows on a body: a person's toes and ankles, or an animal's paw tips
/// (each paw bone's head moved its length along the bone: the bone ends at the paw).
enum Tracked {
    Person([Entity; 4]),
    Paws([(Entity, f32); 4]),
}

/// An animal file's paw bones' lengths (`paw_len` in its sidecar, from `quadruped.py`; the wolf's
/// own when an older sidecar lacks them), in [`ANIMAL_FEET`] order.
fn paw_lengths(file: &str) -> [f32; 4] {
    let path = std::path::Path::new(&crate::lookdev::asset_root()).join(file).with_extension("clips.json");
    let json = std::fs::read(&path).ok().and_then(|b| serde_json::from_slice::<serde_json::Value>(&b).ok());
    let wolf = [0.1163, 0.1163, 0.1504, 0.1504];
    ANIMAL_FEET.map(|f| json.as_ref().and_then(|j| j["paw_len"][f].as_f64()).map(|v| v as f32)).iter().zip(wolf).map(|(v, w)| v.unwrap_or(w)).collect::<Vec<_>>().try_into().unwrap_or(wolf)
}

/// One line a frame: time, the body's root, each toe and ankle (or each paw tip) with the ground
/// under it, the clip that shows most, the phase, the gaits and the markers' foot contacts.
#[allow(clippy::type_complexity, clippy::too_many_arguments)]
fn record(
    mut log: ResMut<FeetLog>,
    time: Res<Time>,
    island: Option<Res<crate::island::Island>>,
    envs: Option<Res<crate::envs::Envs>>,
    who: Query<(Entity, &GlobalTransform, Option<&crate::lookdev::Model>), Or<(With<Feet>, With<crate::envs::Player>)>>,
    children: Query<&Children>,
    bones: Query<(&Name, &GlobalTransform)>,
    anims: Query<&crate::anim::Anim>,
    roam: Res<crate::envs::Roam>,
    scene: Option<NonSend<crate::world::Scene>>,
    mut feet: Local<HashMap<Entity, Tracked>>,
) {
    // The island's ground, else the look-dev environment's.
    let ground = |x: f32, z: f32| match (&island, &envs) {
        (Some(i), _) => i.height(x, z),
        (None, Some(e)) => e.ground.height(x, z),
        _ => 0.0,
    };
    for (e, root, model) in &who {
        if !feet.contains_key(&e) {
            let find = |name: &str| children.iter_descendants(e).find(|d| bones.get(*d).is_ok_and(|(n, _)| n.as_str() == name));
            if let (Some(l), Some(r), Some(la), Some(ra)) = (find("J_Bip_L_ToeBase"), find("J_Bip_R_ToeBase"), find("J_Bip_L_Foot"), find("J_Bip_R_Foot")) {
                feet.insert(e, Tracked::Person([l, r, la, ra]));
            } else if let (Some(fl), Some(fr), Some(hl), Some(hr)) = (find("paw.fl"), find("paw.fr"), find("paw.hl"), find("paw.hr")) {
                let len = paw_lengths(model.map_or("", |m| m.file.as_str()));
                feet.insert(e, Tracked::Paws([(fl, len[0]), (fr, len[1]), (hl, len[2]), (hr, len[3])]));
            } else {
                continue;
            }
        }
        let pt = |v: Vec3| [v.x, v.y, v.z, ground(v.x, v.z)];
        let mut line = match &feet[&e] {
            Tracked::Person(b) => {
                let [Ok(l), Ok(r), Ok(la), Ok(ra)] = b.map(|b| bones.get(b).map(|(_, g)| g.translation())) else {
                    feet.remove(&e);
                    continue;
                };
                serde_json::json!({"l": pt(l), "r": pt(r), "la": pt(la), "ra": pt(ra)})
            }
            Tracked::Paws(b) => {
                let [Ok(fl), Ok(fr), Ok(hl), Ok(hr)] = b.map(|(b, len)| bones.get(b).map(|(_, g)| g.transform_point(Vec3::Y * len))) else {
                    feet.remove(&e);
                    continue;
                };
                serde_json::json!({"paws": {"fl": pt(fl), "fr": pt(fr), "hl": pt(hl), "hr": pt(hr)}})
            }
        };
        let p = root.translation();
        let anim = anims.get(e).ok();
        let rest = serde_json::json!({
            "t": time.elapsed_secs_f64(),
            "root": [p.x, p.y, p.z],
            "speed": roam.speed,
            // Connected play: the authority time my body is drawn at, and its segment then.
            "mine_ms": scene.as_ref().map(|s| s.mine_ms),
            "seg": scene.as_ref().map(|s| [s.mine_seg.0, s.mine_seg.1]),
            "clip": anim.map_or("", |a| a.showing()),
            // The shared phase, the gaits and their weights, and each foot's marker contact.
            "phase": anim.map(|a| a.phase),
            "gaits": anim.map(|a| a.gaits()),
            "feet": anim.map(|a| a.feet),
            "ik": anim.map(|a| a.ik),
        });
        if let (Some(m), Some(r)) = (line.as_object_mut(), rest.as_object()) {
            m.extend(r.clone());
        }
        let _ = writeln!(log.0, "{line}");
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;

    /// Vivi's sidecar (`assets/lookdev/anim/vroid-Vivi.clips.json`): speeds, lengths and markers.
    pub(crate) fn vivi() -> Gaits {
        Gaits::parse(&serde_json::json!({
            "walk": {"speed": 1.389, "natural_speed": 1.435, "seconds": 1.033, "loop": true, "contacts": {"L": [[0.5161, 1.0]], "R": [[0.0, 0.5806]]}},
            "walk_brisk": {"speed": 2.028, "natural_speed": 2.028, "seconds": 1.0, "loop": true, "contacts": {"L": [[0.5, 1.0]], "R": [[0.0, 0.4667]]}},
            "run": {"speed": 3.67, "natural_speed": 3.146, "seconds": 0.6, "loop": true, "contacts": {"L": [[0.4444, 0.7778]], "R": [[0.0, 0.2778]]}},
            "run_fast": {"speed": 3.497, "natural_speed": 3.497, "seconds": 0.767, "loop": true, "contacts": {"L": [[0.4783, 0.7826]], "R": [[0.0, 0.1739]]}},
            "sneak": {"speed": 0.747, "natural_speed": 0.747, "loop": true},
            "idle": {"speed": 0.0, "seconds": 5.967, "loop": true, "contacts": {"L": [[0.0, 1.0]], "R": [[0.0, 1.0]]}},
            "wave": {"seconds": 2.97, "loop": false, "layer": "upper", "contacts": {"L": [[0.0, 1.0]], "R": [[0.0, 1.0]]}},
            "sit_ground": {"seconds": 6.0, "loop": true, "ik": false},
        }))
    }

    fn only(b: &Blend) -> Option<&'static str> {
        (b.n == 1).then(|| vivi().clips[b.parts[0].0].clip)
    }

    #[test]
    fn speeds_blend_neighbouring_gaits_and_the_feet_keep_the_bodys_speed() {
        let g = vivi();
        let len = |_| 1.0;
        // Pure where one gait serves: the rules' walk and run, the look-dev walk.
        for (speed, clip) in [(1.4, "walk"), (2.5, "walk_brisk"), (3.05, "run"), (3.9, "run_fast")] {
            assert_eq!(only(&g.blend(speed, 1.0, len)), Some(clip), "at {speed} m/s");
        }
        // Between walk and walk_brisk both play, and the phase rate keeps the stride rule: one
        // gait at its baked cycle reproduces `speed / (baked speed × stride)`.
        let b = g.blend(1.7, 1.0, len);
        assert_eq!(b.n, 2);
        assert!((b.parts[0].1 + b.parts[1].1 - 1.0).abs() < 1e-5);
        let walk = g.blend(1.4, 1.0, len);
        let rate = 1.4 / walk.cycle_m;
        assert!((rate * 1.033 - 1.4 / 1.389).abs() < 1e-3, "one cycle per {} s", 1.0 / rate);
        // Walk ↔ run only round WALK_MAX.
        assert_eq!(g.blend(WALK_MAX, 1.0, len).n, 2);
        assert_eq!(only(&g.blend(WALK_MAX - CROSS_BAND - 0.01, 1.0, len)), Some("walk_brisk"));
    }

    #[test]
    fn weights_are_continuous_in_speed() {
        let g = vivi();
        let w = |s: f32| {
            let b = g.blend(s, 1.0, |_| 1.0);
            let mut v = [0.0f32; 4];
            for &(i, x) in b.parts() {
                v[i] += x;
            }
            v
        };
        let mut prev = w(0.5);
        let mut s = 0.5;
        while s < 4.5 {
            s += 0.005;
            let now = w(s);
            let jump = prev.iter().zip(&now).map(|(a, b)| (a - b).abs()).fold(0.0, f32::max);
            assert!(jump < 0.06, "weights jump by {jump} at {s} m/s");
            prev = now;
        }
    }

    #[test]
    fn longer_legs_step_slower_and_walk_further() {
        let g = vivi();
        // A giant twice the base's stride walks at 2.6 m/s with the casual walk, at half its rate.
        let b = g.blend(2.6, 2.0, |_| 1.0);
        assert_eq!(only(&b), Some("walk"));
        let rate = 2.6 / (2.0 * b.cycle_m);
        assert!((rate * 1.033 - 2.6 / (1.389 * 2.0)).abs() < 1e-3);
    }

    #[test]
    fn markers_say_which_feet_are_down_and_where_to_settle() {
        let g = vivi();
        let c = &g.info("walk").unwrap().contacts;
        assert!(c.down(1, 0.0) && !c.down(0, 0.2) && c.down(0, 0.7));
        assert_eq!(c.count(0.55), 2, "double support");
        let at = c.next_settle(0.1);
        assert!((0.5161..0.5806).contains(&(at % 1.0)), "settles in the next double support, not at {at}");
        // Weights ease in round a touchdown.
        assert_eq!(c.weight(0, 0.75, 0.05, true), 1.0);
        assert_eq!(c.weight(0, 0.2, 0.05, true), 0.0);
        let near = c.weight(0, 0.5, 0.05, true);
        assert!(near > 0.5 && near < 1.0);
        // Clip info: layer and IK.
        assert!(g.info("wave").unwrap().upper && !g.info("walk").unwrap().upper);
        assert!(!g.info("sit_ground").unwrap().ik && g.info("idle").unwrap().ik);
    }

    /// The wolf's sidecar (`assets/lookdev/anim/wolf.clips.json`, from wolf.py).
    fn wolf() -> Gaits {
        Gaits::parse(&serde_json::json!({"model": "wolf", "clips": [
            {"name": "idle", "seconds": 3.0, "loop": true},
            {"name": "walk", "seconds": 0.8, "loop": true, "speed": 1.3, "sync": "hl", "contacts": {"fl": [[0.25, 0.875]], "fr": [[0.0, 0.375], [0.75, 1.0]], "hl": [[0.0, 0.625]], "hr": [[0.0, 0.125], [0.5, 1.0]]}},
            {"name": "trot", "seconds": 0.44, "loop": true, "speed": 3.4},
            {"name": "run", "seconds": 0.32, "loop": true, "speed": 7.0},
            {"name": "bite", "seconds": 0.85, "loop": false},
        ]}))
    }

    #[test]
    fn an_animal_changes_footfall_pattern_only_round_the_boundaries() {
        let g = wolf();
        let name = |b: &Blend| b.parts().iter().map(|&(i, w)| (g.clips[i].clip, (w * 100.0).round() / 100.0)).collect::<Vec<_>>();
        for (speed, clip) in [(1.3, "walk"), (1.0, "walk"), (3.4, "trot"), (4.1, "trot"), (7.0, "run"), (5.5, "run")] {
            assert_eq!(name(&g.blend(speed, 1.0, |_| 1.0)), vec![(clip, 1.0)], "at {speed} m/s");
        }
        // walk/trot meet at sqrt(1.3 × 3.4) = 2.10 m/s, trot/run at sqrt(3.4 × 7) = 4.88.
        assert_eq!(g.blend(2.10, 1.0, |_| 1.0).n, 2);
        assert_eq!(g.blend(4.88, 1.0, |_| 1.0).n, 2);
        // A pup (stage scale 0.42) takes smaller steps: at 1.3 m/s it trots.
        assert_eq!(name(&g.blend(1.3, 0.42, |_| 1.0)), vec![("trot", 1.0)]);
        // The walk's settle point has three paws down.
        let c = &g.info("walk").unwrap().contacts;
        assert_eq!(c.count(c.next_settle(0.3)), 3);
    }

    #[test]
    fn the_deers_narrow_band_keeps_the_rules_trot_and_flee_pure() {
        let g = Gaits::parse(&serde_json::json!({"model": "deer", "band": 1.04, "clips": [
            {"name": "walk", "seconds": 1.0, "loop": true, "speed": 1.3},
            {"name": "trot", "seconds": 0.5, "loop": true, "speed": 3.7},
            {"name": "run", "seconds": 0.48, "loop": true, "speed": 4.6},
        ]}));
        let top = |s: f32| {
            let b = g.blend(s, 1.0, |_| 1.0);
            let &(i, w) = b.parts().iter().max_by(|a, b| a.1.total_cmp(&b.1)).unwrap();
            (g.clips[i].clip, w)
        };
        // The rules' deer move at 3.7 m/s and flee at 1.15 × that.
        assert_eq!(top(3.7), ("trot", 1.0));
        let (clip, w) = top(3.7 * 1.15);
        assert!(clip == "run" && w > 0.9, "flee plays the bound, not {clip} at {w}");
        assert_eq!(g.blend(4.125, 1.0, |_| 1.0).n, 2, "they still blend round the boundary");
    }

    #[test]
    fn a_file_without_both_gaits_uses_the_lookdev_speeds() {
        let g = Gaits::parse(&serde_json::json!({"walk": {"speed": 1.4}}));
        assert_eq!(g.clips.len(), 2);
        let b = g.blend(3.6, 1.0, |_| 1.0);
        assert_eq!((b.n, g.clips[b.parts[0].0].clip), (1, "run"));
    }
}
