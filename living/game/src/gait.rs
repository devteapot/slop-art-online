//! Locomotion by actual speed, blended at one shared phase so feet neither slide nor cross.
//!
//! A character's clip file (its own, or generated people's shared one: `anim::clip_file`) comes
//! with `<file>.clips.json` (`living/tools/blender/animate.py
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
//!   run ↔ run_fast) across the whole gap, and between the walking and running families by
//!   [`Family`]: the authority's own word on whether a body runs when it gives one, else a
//!   split speed from the world's laws (`live.rs`: the geometric mean of a grown person's walking
//!   and running speeds, 3.18 m/s at the rules' 2.6 and 3.9), blending only within
//!   ±[`CROSS_BAND`] of it, else midway between the clips' own walking and running speeds. No
//!   speed of the rules is written here, so a walk set to 3.4 m/s still walks.
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

/// Half the width of the walk ↔ run blend round the split speed ([`Family::Split`], m/s).
pub const CROSS_BAND: f32 = 0.2;

/// Which of a person's gait families plays: walking clips (walk, walk_brisk) or running ones
/// (run, run_fast).
#[derive(Clone, Copy, Debug, PartialEq, Default)]
pub enum Family {
    /// The authority says whether the body runs: that family only, at any speed.
    Running(bool),
    /// The split speed (m/s for a character of the 1.75 m base, off a road): walking clips below
    /// it, running clips above, blending within ±[`CROSS_BAND`].
    Split(f32),
    /// Neither known: the split midway between the walking clips' fastest natural speed and the
    /// running clips' slowest ([`Gaits::clips_split`]).
    #[default]
    Clips,
}
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
    /// A turn on the spot (`turn_deg` in the sidecar, the game's sense: -90 a quarter turn left):
    /// the clip itself doesn't turn (`animate.py` took the turn out), so the body turns along
    /// this curve (normalised clip time, degrees so far).
    pub turn: Option<(f32, Vec<(f32, f32)>)>,
    /// The rules' flight window of a jump take (clip seconds), from its path.
    pub hop: Option<(f32, f32)>,
    /// The body's own track while the clip plays (game metres per frame at 30 fps: to its left,
    /// ahead): a start's, a stop's or a hop's (the asset view draws the body along it).
    pub path: Vec<(f32, f32)>,
    /// Its length (s), from the sidecar.
    pub seconds: f32,
    /// The gait and its phase a one-shot starts from (a stop's: `start_gait` in the sidecar).
    pub start_gait: Option<(String, f32)>,
}

impl ClipInfo {
    /// How far a turn take has turned the body at clip time `u` (0–1, radians, the game's sense).
    pub fn turned(&self, u: f32) -> f32 {
        let Some((_, curve)) = &self.turn else { return 0.0 };
        let u = u.clamp(0.0, 1.0);
        let k = curve.partition_point(|p| p.0 < u);
        let deg = match (k.checked_sub(1).and_then(|i| curve.get(i)), curve.get(k)) {
            (Some(a), Some(b)) if b.0 > a.0 => a.1 + (b.1 - a.1) * (u - a.0) / (b.0 - a.0),
            (_, Some(b)) => b.1,
            (Some(a), None) => a.1,
            _ => 0.0,
        };
        deg.to_radians()
    }

    /// Where the body's own track has it at clip time `t` (s): (left, ahead) in metres.
    pub fn path_at(&self, t: f32) -> Vec2 {
        if self.path.is_empty() {
            return Vec2::ZERO;
        }
        let x = (t * 30.0).clamp(0.0, (self.path.len() - 1) as f32);
        let (a, b) = (x.floor() as usize, (x.ceil() as usize).min(self.path.len() - 1));
        let (pa, pb) = (Vec2::from(self.path[a]), Vec2::from(self.path[b]));
        pa.lerp(pb, x - a as f32)
    }

    /// The longest window (clip time, 0–1) where neither foot is down: a jump's flight.
    pub fn flight(&self) -> Option<(f32, f32)> {
        if self.contacts.feet() != 2 {
            return None;
        }
        const N: usize = 240;
        let up: Vec<bool> = (0..=N).map(|i| self.contacts.count(i as f32 / N as f32) == 0).collect();
        let (mut best, mut k) = (None::<(usize, usize)>, 0);
        while k <= N {
            if !up[k] {
                k += 1;
                continue;
            }
            let b = k + up[k..].iter().position(|&u| !u).unwrap_or(N + 1 - k);
            if best.is_none_or(|(x, y)| b - k > y - x) {
                best = Some((k, b));
            }
            k = b;
        }
        best.map(|(a, b)| (a as f32 / N as f32, b as f32 / N as f32))
    }
}

/// A character file's locomotion clips (the forward ones sorted by natural speed, then the
/// directional ones), whether they split into walking and running families ([`Family`]; people)
/// or are one family (animals), every clip's [`ClipInfo`], and the directions people
/// have takes for (scheme "cursor": [`Gaits::blend_toward`]).
#[derive(Debug, Default)]
pub struct Gaits {
    clips: Vec<Gait>,
    /// How many of `clips` are the forward gaits ([`Gaits::blend`] chooses among those).
    forward: usize,
    split: bool,
    info: HashMap<String, ClipInfo>,
    /// An animal's blend band (ratio either side of the geometric mean).
    band: f32,
    /// Travel directions with their own takes: degrees from the facing (the game's sense: -90
    /// left, 90 right, 180 back) and the walking and running clip (index into `clips`).
    dirs: Vec<Dir>,
}

#[derive(Clone, Copy, Debug)]
struct Dir {
    deg: f32,
    walk: Option<usize>,
    run: Option<usize>,
}

/// The gaits playing at a speed: up to four (index into [`Gaits::gaits`], weight; two forward
/// gaits, or two directions' walk and run), weights summing to 1, and the metres one cycle covers
/// at stride 1 (the weighted mean).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Blend {
    pub parts: [(usize, f32); 4],
    pub n: usize,
    pub cycle_m: f32,
}

impl Blend {
    pub fn parts(&self) -> &[(usize, f32)] {
        &self.parts[..self.n]
    }

    /// One gait alone.
    pub fn one(i: usize, cycle_m: f32) -> Self {
        Self { parts: [(i, 1.0), (i, 0.0), (i, 0.0), (i, 0.0)], n: 1, cycle_m }
    }
}

/// The directional takes the game plays while a person faces one way and moves another (scheme
/// "cursor", `live.rs`), by travel direction from the facing (degrees, the game's sense): a
/// walking and a running take, the first in each list that the file has. These are the takes the
/// clip lab's verdicts accepted (clips 2, 2026-11-11; `docs/GAME_BRIEF.md`, "Locomotion clips").
/// Clips 3 (r2 takes, 2026-11-11) added the back diagonals' walks (`walk_diag_bl` s17 with
/// `walk_diag_br`). Left out: `run_back` s3 (played at twice its own 1.9 m/s, its supporting foot
/// slid 11% of the body's speed against 2% for the forward run reversed), `strafe_run_left` s17
/// and `_right` s15 (their planted feet slide, the right one's seam closes 17°), and the
/// step-touch `strafe_walk_left`/`_right` (0.6 m a cycle). A direction without a take falls back
/// to the forward gaits along the travel with the upper body turned (`twist.rs`).
pub const DIRECTIONS: [(f32, &[&str], &[&str]); 7] = [
    (180.0, &["walk_back"], &[]),
    (-90.0, &["strafe_walk_cross_left"], &[]),
    (90.0, &["strafe_walk_cross_right"], &[]),
    (-45.0, &["walk_diag_fl"], &["run_diag_fl"]),
    (45.0, &["walk_diag_fr"], &["run_diag_fr"]),
    (-135.0, &["walk_diag_bl"], &["run_diag_bl"]),
    (135.0, &["walk_diag_br"], &["run_diag_br"]),
];
/// Neighbouring directions further apart than this (degrees) don't blend: the gap falls back.
const DIR_GAP_MAX: f32 = 91.0;
/// The directional takes step at most this many times as often as the forward gaits would at the
/// same speed (their metres a cycle against the forward's); beyond, the gap falls back. The clip
/// lab's sideways and backward takes cover 0.4–0.8 of the forward's metres a cycle, so at the
/// rules' 2.6 m/s walk and 3.9 m/s run, and 1.4 times that on a road, most of them would step
/// two or three times as often as the forward gait: a scurry.
pub const CADENCE_MAX: f32 = 1.6;

/// The forward gaits of a sidecar from before `locomotion` was written for every loop, and whether
/// each is a run.
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
            forward: 2,
            split: true,
            info: HashMap::new(),
            band: ANIMAL_BAND,
            dirs: vec![],
        }
    }

    /// From a `clips.json` sidecar: its looping locomotion clips with a speed, and every clip's
    /// info. A character's sidecar maps clip names to clips; an animal's lists them under `clips`.
    pub(crate) fn parse(json: &serde_json::Value) -> Self {
        let info_of = |c: &serde_json::Value, feet: &[&str]| {
            let pair = |v: &serde_json::Value| Some((v.get(0)?.as_f64()? as f32, v.get(1)?.as_f64()? as f32));
            ClipInfo {
                upper: c["layer"].as_str() == Some("upper"),
                ik: c["ik"].as_bool() != Some(false),
                contacts: Contacts::parse(&c["contacts"], feet),
                turn: c["turn_deg"].as_f64().map(|d| (d as f32, c["turn_curve"].as_array().map(|a| a.iter().filter_map(pair).collect()).unwrap_or_default())),
                hop: pair(&c["hop"]),
                path: c["path_m"].as_array().map(|a| a.iter().filter_map(pair).collect()).unwrap_or_default(),
                seconds: c["seconds"].as_f64().unwrap_or(0.0) as f32,
                start_gait: c["start_gait"]["clip"].as_str().zip(c["start_gait"]["phase"].as_f64()).map(|(g, p)| (g.to_string(), p as f32)),
            }
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
            let forward = clips.len();
            return if clips.is_empty() { Self { info, ..Self::fallback() } } else { Self { clips, forward, split: false, info, band, dirs: vec![] } };
        }
        let info = json.as_object().map(|m| m.iter().filter(|(_, c)| c.is_object()).map(|(k, c)| (k.clone(), info_of(c, &PEOPLE_FEET))).collect()).unwrap_or_default();
        let gait = |clip: &'static str, run: bool| {
            let c = json.get(clip)?;
            let speed = c["speed"].as_f64()? as f32;
            let natural = c["natural_speed"].as_f64().map_or(speed, |n| n as f32);
            (speed > 0.1 && natural > 0.1 && c["loop"].as_bool() != Some(false)).then_some(Gait { clip, speed, natural, run, seconds: c["seconds"].as_f64().map(|s| s as f32) })
        };
        // The forward gaits: every loop the sidecar marks a walk or a run (`locomotion`) with no
        // travel of its own, so a new take joins its family by its natural speed (a 3.0 m/s walk
        // between walk_brisk and running); a sidecar from before the field, the named four.
        let tagged: Vec<Gait> = json
            .as_object()
            .map(|m| {
                m.iter()
                    .filter(|(_, c)| c["travel_deg"].is_null() && c["loop"].as_bool() == Some(true))
                    .filter_map(|(k, c)| match c["locomotion"].as_str() {
                        Some("walk") => gait(crate::anim::intern(k), false),
                        Some("run") => gait(crate::anim::intern(k), true),
                        _ => None,
                    })
                    .collect()
            })
            .unwrap_or_default();
        let mut clips = if tagged.is_empty() { LOCOMOTION.iter().filter_map(|&(clip, run)| gait(clip, run)).collect::<Vec<_>>() } else { tagged };
        if clips.iter().any(|g| !g.run) && clips.iter().any(|g| g.run) {
            // Walks first, then runs, each by natural speed.
            clips.sort_by(|a, b| a.run.cmp(&b.run).then(a.natural.total_cmp(&b.natural)));
            let forward = clips.len();
            // Then the directional takes the file has (a loop with a speed and `travel_deg`).
            let mut dirs = vec![];
            for &(deg, walks, runs) in &DIRECTIONS {
                let mut add = |names: &[&'static str], run: bool| {
                    let &clip = names.iter().find(|n| json.get(**n).is_some_and(|c| c["travel_deg"].is_number() && c["loop"].as_bool() == Some(true) && c["speed"].as_f64().is_some_and(|v| v > 0.1)))?;
                    let c = &json[clip];
                    let speed = c["speed"].as_f64()? as f32;
                    clips.push(Gait { clip, speed, natural: c["natural_speed"].as_f64().map_or(speed, |n| n as f32), run, seconds: c["seconds"].as_f64().map(|s| s as f32) });
                    Some(clips.len() - 1)
                };
                let (walk, run) = (add(walks, false), add(runs, true));
                if walk.is_some() || run.is_some() {
                    dirs.push(Dir { deg, walk, run });
                }
            }
            Self { clips, forward, split: true, info, band: ANIMAL_BAND, dirs }
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

    /// The gaits for moving at `speed` (m/s, the pace's: the gait is chosen at it) toward
    /// `travel` radians from where the legs face (the game's sense: positive to the right, ±π
    /// behind), from the directional takes either side of it: each direction blends its walk and
    /// run take by speed between their own natural speeds (a backward jog serves a fast backward
    /// walk), and the two directions blend by angle (no warp: they are at most [`DIR_GAP_MAX`]
    /// apart). None when there is no take on a side, when the blend would step more than
    /// [`CADENCE_MAX`] times as often as the forward gaits, or when the mirrored travel (left for
    /// right) would fall back: the caller falls back to the forward gaits along the travel, so
    /// both sides always look alike.
    pub fn blend_toward(&self, speed: f32, stride: f32, family: Family, travel: f32, len: impl Fn(usize) -> f32 + Copy) -> Option<Blend> {
        let b = self.blend_side(speed, stride, family, travel, len)?;
        self.blend_side(speed, stride, family, -travel, len)?;
        Some(b)
    }

    fn blend_side(&self, speed: f32, stride: f32, family: Family, travel: f32, len: impl Fn(usize) -> f32 + Copy) -> Option<Blend> {
        let fwd = self.blend(speed, stride, family, len);
        let deg = {
            let d = travel.to_degrees().rem_euclid(360.0);
            if d > 180.0 { d - 360.0 } else { d }
        };
        if deg.abs() < 0.5 {
            return Some(fwd);
        }
        let s = speed / stride.max(0.05);
        let mut angles: Vec<(f32, Option<Dir>)> = vec![(0.0, None)];
        angles.extend(self.dirs.iter().map(|d| (d.deg, Some(*d))));
        // Behind can be reached from either side.
        if let Some(b) = angles.iter().find(|(a, _)| (a.abs() - 180.0).abs() < 0.5).and_then(|x| x.1) {
            angles.push((-180.0, Some(b)));
        }
        angles.sort_by(|a, b| a.0.total_cmp(&b.0));
        let lo = angles.iter().rev().find(|(a, _)| *a <= deg)?;
        let hi = angles.iter().find(|(a, _)| *a >= deg)?;
        let gap = hi.0 - lo.0;
        if gap > DIR_GAP_MAX {
            return None;
        }
        let t = if gap > 0.0 { (deg - lo.0) / gap } else { 0.0 };
        let mut parts: Vec<(usize, f32)> = Vec::with_capacity(4);
        for (w, dir) in [(1.0 - t, lo.1), (t, hi.1)] {
            if w <= 0.0 {
                continue;
            }
            match dir {
                None => parts.extend(fwd.parts().iter().map(|&(i, x)| (i, x * w))),
                Some(d) => match (d.walk, d.run) {
                    // The authority's word picks the take where the direction has both.
                    (Some(a), Some(_)) if family == Family::Running(false) => parts.push((a, w)),
                    (Some(_), Some(b)) if family == Family::Running(true) => parts.push((b, w)),
                    (Some(a), Some(b)) => {
                        // Between the two takes' natural speeds, as neighbouring forward gaits.
                        let (lo, hi) = (self.clips[a].natural, self.clips[b].natural.max(self.clips[a].natural + 0.01));
                        let t = if s <= lo { 0.0 } else if s >= hi { 1.0 } else { smoothstep(0.0, 1.0, (s / lo).ln() / (hi / lo).ln()) };
                        parts.push((a, w * (1.0 - t)));
                        parts.push((b, w * t));
                    }
                    (Some(i), None) | (None, Some(i)) => parts.push((i, w)),
                    (None, None) => {}
                },
            }
        }
        parts.retain(|p| p.1 > 1e-4);
        let sum: f32 = parts.iter().map(|p| p.1).sum();
        if parts.is_empty() || sum <= 0.0 {
            return Some(fwd);
        }
        let cycle = |i: usize| {
            let g = &self.clips[i];
            g.speed * g.seconds.unwrap_or_else(|| len(i)).max(0.05)
        };
        let mut b = Blend { parts: [(parts[0].0, 0.0); 4], n: parts.len().min(4), cycle_m: 0.0 };
        for (k, &(i, w)) in parts.iter().take(4).enumerate() {
            b.parts[k] = (i, w / sum);
            b.cycle_m += w / sum * cycle(i);
        }
        (fwd.cycle_m <= CADENCE_MAX * b.cycle_m).then_some(b)
    }

    /// Midway between the walking clips' fastest natural speed and the running clips' slowest
    /// (m/s at stride 1): the walk ↔ run split when neither the authority nor the laws give one.
    pub fn clips_split(&self) -> f32 {
        let fwd = &self.clips[..self.forward];
        let walk = fwd.iter().filter(|g| !g.run).map(|g| g.natural).fold(f32::NAN, f32::max);
        let run = fwd.iter().filter(|g| g.run).map(|g| g.natural).fold(f32::NAN, f32::min);
        match (walk.is_nan(), run.is_nan()) {
            (false, false) => 0.5 * (walk + run),
            (false, true) => walk,
            (true, false) => run,
            (true, true) => 0.0,
        }
    }

    /// The walk ↔ run split for `family` (m/s at stride 1), or None when the authority picks.
    fn split_speed(&self, family: Family) -> Option<f32> {
        match family {
            Family::Running(_) => None,
            Family::Split(v) => Some(v),
            Family::Clips => Some(self.clips_split()),
        }
    }

    /// Whether a person moving at `speed` (m/s) with steps `stride` times the base's walks, not
    /// runs, clear of the blend into running.
    pub fn walks(&self, speed: f32, stride: f32, family: Family) -> bool {
        match self.split_speed(family) {
            None => family == Family::Running(false),
            Some(v) => speed / stride.max(0.05) <= v - CROSS_BAND,
        }
    }

    /// The speed band (m/s at stride 1) over which gaits `i` and `i + 1` blend.
    fn band(&self, i: usize, family: Family) -> (f32, f32) {
        let (a, b) = (&self.clips[i], &self.clips[i + 1]);
        if !self.split {
            let m = (a.natural * b.natural).sqrt();
            (m / self.band, m * self.band)
        } else if a.run != b.run {
            let v = self.split_speed(family).unwrap_or_else(|| self.clips_split());
            (v - CROSS_BAND, v + CROSS_BAND)
        } else {
            (a.natural, b.natural)
        }
    }

    /// The gaits and their weights for moving at `speed` (m/s) with steps `stride` times the
    /// base's, in `family`, and the metres a cycle covers at stride 1. `len(i)` gives a gait's
    /// length (s) when the sidecar has none.
    pub fn blend(&self, speed: f32, stride: f32, family: Family, len: impl Fn(usize) -> f32) -> Blend {
        let s = speed / stride.max(0.05);
        let cycle = |i: usize| {
            let g = &self.clips[i];
            g.speed * g.seconds.unwrap_or_else(|| len(i)).max(0.05)
        };
        let one = |i: usize| Blend::one(i, cycle(i));
        if self.forward == 0 {
            return Blend { parts: [(0, 0.0); 4], n: 0, cycle_m: 1.0 };
        }
        // The authority's word picks the family: only its clips (sorted, so a run of them).
        let (first, end) = match family {
            Family::Running(r) if self.split && self.clips[..self.forward].iter().any(|g| g.run == r) => {
                let first = self.clips[..self.forward].iter().position(|g| g.run == r).unwrap_or(0);
                let end = first + self.clips[first..self.forward].iter().take_while(|g| g.run == r).count();
                (first, end)
            }
            _ => (0, self.forward),
        };
        let mut prev_hi = 0.0f32;
        for i in first..end - 1 {
            let (lo, hi) = self.band(i, family);
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
                return Blend { parts: [(i, 1.0 - t), (i + 1, t), (i, 0.0), (i, 0.0)], n: 2, cycle_m: (1.0 - t) * cycle(i) + t * cycle(i + 1) };
            }
        }
        one(end - 1)
    }
}

/// A looping clip's belt in a character file's sidecar: its speed (m/s) and where it travels from
/// its facing (degrees, the game's sense: `travel_deg`, 0 without it). None for a clip that
/// doesn't travel.
pub fn belt(file: &str, clip: &str) -> Option<(f32, f32)> {
    let path = std::path::Path::new(&crate::lookdev::asset_root()).join(file).with_extension("clips.json");
    let j = serde_json::from_slice::<serde_json::Value>(&std::fs::read(&path).ok()?).ok()?;
    let c = &j[clip];
    let speed = c["speed"].as_f64()? as f32;
    (c["loop"].as_bool() == Some(true) && speed > 0.1).then(|| (speed, c["travel_deg"].as_f64().unwrap_or(0.0) as f32))
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
    motions: Query<&crate::anim::Motion>,
    roam: Res<crate::envs::Roam>,
    scene: Option<NonSend<crate::world::Scene>>,
    camera: Query<&GlobalTransform, With<Camera3d>>,
    (input, net): (Option<Res<crate::controls::Input>>, Option<NonSend<crate::net::Net>>),
    mut feet: Local<HashMap<Entity, Tracked>>,
    mut spine: Local<HashMap<Entity, [Option<Entity>; 3]>>,
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
        let fwd = root.rotation() * Vec3::Z;
        let yaw = fwd.z.atan2(fwd.x).to_degrees();
        // The hips', chest's and head's facing as drawn, in the same sense as `yaw` (VRoid bones'
        // rest rotations are identity, so each bone's +Z is where it faces).
        let at = *spine.entry(e).or_insert_with(|| ["J_Bip_C_Hips", "J_Bip_C_UpperChest", "J_Bip_C_Head"].map(|n| children.iter_descendants(e).find(|d| bones.get(*d).is_ok_and(|(x, _)| x.as_str() == n))));
        let bone_yaw = |b: Option<Entity>| {
            b.and_then(|b| bones.get(b).ok()).map(|(_, g)| {
                let f = g.rotation() * Vec3::Z;
                f.z.atan2(f.x).to_degrees()
            })
        };
        // Where I look and travel (sim radians as degrees, counter-clockwise from east), and the
        // authority's segment speed: connected play only.
        let mine = net.as_ref().and_then(|n| n.my_id).and_then(|id| scene.as_ref().and_then(|s| s.shown.get(&id).copied()));
        let look = input.as_ref().and_then(|i| i.scripted_look.or(i.look)).filter(|l| l.length_squared() > 1e-4).map(|l| l.y.atan2(l.x).to_degrees());
        let rest = serde_json::json!({
            "t": time.elapsed_secs_f64(),
            "root": [p.x, p.y, p.z],
            "speed": roam.speed,
            // The one-shot asked of the body this frame (a skill's clip, a gesture), and when.
            "action": motions.get(e).ok().and_then(|m| m.action.map(|a| (a.clip, a.start_ms))),
            // The body's facing (the model's +Z on the ground, degrees from +X toward +Z), how far
            // its upper body turns from it and whether it walks backwards (`twist.rs`, `anim.rs`).
            "yaw": yaw,
            "twist": motions.get(e).ok().map(|m| m.twist.to_degrees()),
            "neck": motions.get(e).ok().map(|m| m.neck.to_degrees()),
            "eyes": motions.get(e).ok().map(|m| m.eyes.to_degrees()),
            "travel_rel": motions.get(e).ok().map(|m| m.travel.to_degrees()),
            "hips_yaw": bone_yaw(at[0]),
            "chest_yaw": bone_yaw(at[1]),
            "head_yaw": bone_yaw(at[2]),
            "look": look,
            "heading": mine.and_then(|(_, h)| h).map(|h| h.to_degrees()),
            "sim": mine.map(|(p, _)| [p.x, p.y]),
            "reverse": motions.get(e).ok().map(|m| m.reverse),
            "pace": motions.get(e).ok().map(|m| m.pace),
            // Connected play: the authority time my body is drawn at, and its segment then.
            "mine_ms": scene.as_ref().map(|s| s.mine_ms),
            // The game camera's eye and its pitch below the horizon (degrees).
            "eye": camera.single().ok().map(|c| {
                let (p, f) = (c.translation(), c.forward());
                [p.x, p.y, p.z, (-f.y).asin().to_degrees()]
            }),
            "seg": scene.as_ref().map(|s| [s.mine_seg.0 as f64, s.mine_seg.1 as f64, s.mine_seg.2 as f64]),
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

    /// The split these tests were written at (the client's fixed 2.8 m/s before gait-split-1).
    const OLD: Family = Family::Split(2.8);
    use std::f32::consts::PI;

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

    /// Vivi's sidecar with the clip lab's takes (2026-11-11): directional loops, turns and jumps
    /// (numbers rounded from the bake).
    pub(crate) fn takes_json() -> serde_json::Value {
        let mut j = serde_json::json!({
            "walk": {"speed": 1.389, "natural_speed": 1.435, "seconds": 1.033, "loop": true, "contacts": {"L": [[0.5161, 1.0]], "R": [[0.0, 0.5806]]}},
            "walk_brisk": {"speed": 2.028, "natural_speed": 2.028, "seconds": 1.0, "loop": true, "contacts": {"L": [[0.5, 1.0]], "R": [[0.0, 0.4667]]}},
            "run": {"speed": 3.67, "natural_speed": 3.146, "seconds": 0.6, "loop": true, "contacts": {"L": [[0.4444, 0.7778]], "R": [[0.0, 0.2778]]}},
            "run_fast": {"speed": 3.497, "natural_speed": 3.497, "seconds": 0.767, "loop": true, "contacts": {"L": [[0.4783, 0.7826]], "R": [[0.0, 0.1739]]}},
            "turn_right_90": {"seconds": 1.467, "loop": false, "turn_deg": 90.0, "turn_curve": [[0.0, 0.0], [0.3, 20.0], [0.7, 80.0], [1.0, 90.0]], "contacts": {"L": [[0.0, 1.0]], "R": [[0.0, 0.3], [0.6, 1.0]]}},
            "turn_left_90": {"seconds": 1.467, "loop": false, "turn_deg": -90.0, "turn_curve": [[0.0, 0.0], [1.0, -90.0]]},
            "turn_left_180": {"seconds": 2.0, "loop": false, "turn_deg": -180.0, "turn_curve": [[0.0, 0.0], [1.0, -180.0]]},
            "jump_forward": {"seconds": 2.167, "loop": false, "hop": [0.95, 1.394], "contacts": {"L": [[0.17, 0.25], [0.68, 0.75]], "R": [[0.0, 0.14], [0.35, 0.43], [0.83, 0.97]]}},
            "jump_stand": {"seconds": 1.7, "loop": false, "contacts": {"L": [[0.0, 0.37], [0.65, 1.0]], "R": [[0.0, 0.37], [0.65, 1.0]]}},
            "jump_right": {"seconds": 1.7, "loop": false, "hop": [0.6, 1.044], "travel_deg": 90},
        });
        for (name, deg, loco, speed, secs) in [
            ("walk_back", 180, "walk", 1.05, 1.1),
            ("strafe_walk_cross_right", 90, "walk", 1.3, 1.0), ("strafe_walk_cross_left", -90, "walk", 1.3, 1.0),
            ("walk_diag_fr", 45, "walk", 1.4, 1.0), ("run_diag_fr", 45, "run", 2.6, 0.7),
            ("walk_diag_fl", -45, "walk", 1.4, 1.0), ("run_diag_fl", -45, "run", 2.6, 0.7),
        ] {
            j[name] = serde_json::json!({"speed": speed, "natural_speed": speed, "seconds": secs, "loop": true, "travel_deg": deg, "locomotion": loco, "sync": "R", "contacts": {"L": [[0.5, 1.0]], "R": [[0.0, 0.5]]}});
        }
        j
    }

    pub(crate) fn with_takes() -> Gaits {
        Gaits::parse(&takes_json())
    }

    #[test]
    fn directional_takes_blend_by_angle_and_fall_back_where_a_side_has_none() {
        let g = with_takes();
        let name = |b: &Blend| b.parts().iter().map(|&(i, w)| (g.clips[i].clip, (w * 100.0).round() / 100.0)).collect::<Vec<_>>();
        let len = |_| 1.0;
        // Straight ahead: the forward gaits, exactly as `blend`.
        assert_eq!(g.blend_toward(1.4, 1.0, OLD, 0.0, len), Some(g.blend(1.4, 1.0, OLD, len)));
        // Right and behind, at a walk: that side's take.
        assert_eq!(name(&g.blend_toward(1.2, 1.0, OLD, PI / 2.0, len).unwrap()), vec![("strafe_walk_cross_right", 1.0)]);
        assert_eq!(name(&g.blend_toward(1.2, 1.0, OLD, PI, len).unwrap()), vec![("walk_back", 1.0)]);
        // Behind at the rules' 2.6 m/s walk: 1.16 m a cycle against walk_brisk's 2.03 would step
        // 1.76 times as often, so it falls back.
        assert_eq!(g.blend_toward(2.6, 1.0, OLD, PI, len), None);
        // Between forward and the forward-right diagonal: both, by angle.
        let b = g.blend_toward(1.2, 1.0, OLD, 22.5f32.to_radians(), len).unwrap();
        assert_eq!(name(&b), vec![("walk", 0.5), ("walk_diag_fr", 0.5)]);
        // Right to behind (no back-right diagonal): the 90° gap blends side and back.
        assert_eq!(name(&g.blend_toward(1.0, 1.0, OLD, 135f32.to_radians(), len).unwrap()), vec![("strafe_walk_cross_right", 0.5), ("walk_back", 0.5)]);
        // Each cycle covers the weighted metres, so the feet keep the body's speed.
        let side = g.blend_toward(1.2, 1.0, OLD, PI / 2.0, len).unwrap();
        assert!((side.cycle_m - 1.3).abs() < 1e-4);
        // Between a direction's walk and run takes, by speed.
        assert_eq!(g.blend_toward(1.9, 1.0, OLD, PI / 4.0, len).unwrap().n, 2);
        // A side whose mirror falls back (no left take, and back to forward-left is too far to
        // blend) falls back too.
        let mut j = takes_json();
        j.as_object_mut().unwrap().remove("strafe_walk_cross_left");
        let lopsided = Gaits::parse(&j);
        assert!(lopsided.blend_side(1.2, 1.0, OLD, PI / 2.0, len).is_some());
        assert_eq!(lopsided.blend_toward(1.2, 1.0, OLD, PI / 2.0, len), None);
        // A file with no directional takes falls back.
        assert_eq!(vivi().blend_toward(1.4, 1.0, OLD, PI / 2.0, len), None);
    }

    #[test]
    fn take_info_reads_turns_paths_hops_and_flight() {
        let g = with_takes();
        let t = g.info("turn_right_90").unwrap();
        assert_eq!(t.turn.as_ref().map(|t| t.0), Some(90.0));
        assert!((t.turned(0.5) - 50f32.to_radians()).abs() < 1e-4);
        assert_eq!(g.info("jump_forward").unwrap().hop, Some((0.95, 1.394)));
        let (a, b) = g.info("jump_stand").unwrap().flight().unwrap();
        assert!((a - 0.37).abs() < 0.01 && (b - 0.65).abs() < 0.01, "the longest time both feet are up: {a}..{b}");
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
            assert_eq!(only(&g.blend(speed, 1.0, OLD, len)), Some(clip), "at {speed} m/s");
        }
        // Between walk and walk_brisk both play, and the phase rate keeps the stride rule: one
        // gait at its baked cycle reproduces `speed / (baked speed × stride)`.
        let b = g.blend(1.7, 1.0, OLD, len);
        assert_eq!(b.n, 2);
        assert!((b.parts[0].1 + b.parts[1].1 - 1.0).abs() < 1e-5);
        let walk = g.blend(1.4, 1.0, OLD, len);
        let rate = 1.4 / walk.cycle_m;
        assert!((rate * 1.033 - 1.4 / 1.389).abs() < 1e-3, "one cycle per {} s", 1.0 / rate);
        // Walk ↔ run only round the split.
        assert_eq!(g.blend(2.8, 1.0, OLD, len).n, 2);
        assert_eq!(only(&g.blend(2.8 - CROSS_BAND - 0.01, 1.0, OLD, len)), Some("walk_brisk"));
    }

    #[test]
    fn a_new_walk_joins_its_family_by_natural_speed() {
        // A sidecar that marks its gaits' families: walk_v30 (a 3.0 m/s walk) goes between
        // walk_brisk and the runs, by its natural speed, not its name.
        let g = Gaits::parse(&serde_json::json!({
            "walk": {"speed": 1.389, "natural_speed": 1.435, "seconds": 1.033, "loop": true, "locomotion": "walk"},
            "walk_brisk": {"speed": 2.028, "natural_speed": 2.028, "seconds": 1.0, "loop": true, "locomotion": "walk"},
            "walk_v30": {"speed": 3.0, "natural_speed": 3.0, "seconds": 0.7, "loop": true, "locomotion": "walk"},
            "run": {"speed": 3.67, "natural_speed": 3.146, "seconds": 0.6, "loop": true, "locomotion": "run"},
            "run_fast": {"speed": 3.497, "natural_speed": 3.497, "seconds": 0.767, "loop": true, "locomotion": "run"},
            "sneak": {"speed": 0.747, "natural_speed": 0.747, "seconds": 1.6, "loop": true, "locomotion": "sneak"},
            "walk_back": {"speed": 1.05, "natural_speed": 1.05, "seconds": 1.1, "loop": true, "locomotion": "walk", "travel_deg": 180},
        }));
        let names = |b: &Blend| b.parts().iter().map(|&(i, w)| (g.gaits()[i].clip, (w * 100.0).round() / 100.0)).collect::<Vec<_>>();
        let walk34 = Family::Split((3.4f32 * 4.3).sqrt());
        assert_eq!(names(&g.blend(3.0, 1.0, walk34, |_| 1.0)), vec![("walk_v30", 1.0)]);
        assert_eq!(names(&g.blend(3.4, 1.0, walk34, |_| 1.0)), vec![("walk_v30", 1.0)]);
        assert_eq!(g.blend(2.5, 1.0, walk34, |_| 1.0).n, 2, "between walk_brisk and walk_v30");
        assert_eq!(names(&g.blend(4.3, 1.0, walk34, |_| 1.0)), vec![("run_fast", 1.0)]);
        assert!(g.gaits()[..5].iter().all(|x| x.clip != "sneak" && x.clip != "walk_back"));
    }

    #[test]
    fn the_walk_run_split_follows_the_authority_or_the_laws_not_a_number() {
        let g = vivi();
        let len = |_| 1.0;
        // The laws' split (the geometric mean of a 3.4 m/s walk and a 4.3 m/s run, 3.82): a walk
        // at 3.4 m/s still walks, a run at 4.3 runs.
        let laws = Family::Split((3.4f32 * 4.3).sqrt());
        assert_eq!(only(&g.blend(3.4, 1.0, laws, len)), Some("walk_brisk"));
        assert_eq!(only(&g.blend(4.3, 1.0, laws, len)), Some("run_fast"));
        assert!(g.walks(3.4, 1.0, laws) && !g.walks(4.3, 1.0, laws));
        // The authority's word wins at any speed: a walk at 3.6 walks, a run at 2.9 runs.
        assert_eq!(only(&g.blend(3.6, 1.0, Family::Running(false), len)), Some("walk_brisk"));
        assert_eq!(only(&g.blend(2.9, 1.0, Family::Running(true), len)), Some("run"));
        assert!(g.walks(3.6, 1.0, Family::Running(false)) && !g.walks(2.0, 1.0, Family::Running(true)));
        // Neither: midway between walk_brisk's natural 2.03 and run's 3.15 (2.59).
        assert!((g.clips_split() - 0.5 * (2.028 + 3.15)).abs() < 0.05, "{}", g.clips_split());
        assert_eq!(only(&g.blend(2.3, 1.0, Family::Clips, len)), Some("walk_brisk"));
        assert_eq!(only(&g.blend(2.9, 1.0, Family::Clips, len)), Some("run"));
    }

    #[test]
    fn weights_are_continuous_in_speed() {
        let g = vivi();
        let w = |s: f32| {
            let b = g.blend(s, 1.0, OLD, |_| 1.0);
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
        let b = g.blend(2.6, 2.0, OLD, |_| 1.0);
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
            assert_eq!(name(&g.blend(speed, 1.0, OLD, |_| 1.0)), vec![(clip, 1.0)], "at {speed} m/s");
        }
        // walk/trot meet at sqrt(1.3 × 3.4) = 2.10 m/s, trot/run at sqrt(3.4 × 7) = 4.88.
        assert_eq!(g.blend(2.10, 1.0, OLD, |_| 1.0).n, 2);
        assert_eq!(g.blend(4.88, 1.0, OLD, |_| 1.0).n, 2);
        // A pup (stage scale 0.42) takes smaller steps: at 1.3 m/s it trots.
        assert_eq!(name(&g.blend(1.3, 0.42, OLD, |_| 1.0)), vec![("trot", 1.0)]);
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
            let b = g.blend(s, 1.0, OLD, |_| 1.0);
            let &(i, w) = b.parts().iter().max_by(|a, b| a.1.total_cmp(&b.1)).unwrap();
            (g.clips[i].clip, w)
        };
        // The rules' deer move at 3.7 m/s and flee at 1.15 × that.
        assert_eq!(top(3.7), ("trot", 1.0));
        let (clip, w) = top(3.7 * 1.15);
        assert!(clip == "run" && w > 0.9, "flee plays the bound, not {clip} at {w}");
        assert_eq!(g.blend(4.125, 1.0, OLD, |_| 1.0).n, 2, "they still blend round the boundary");
    }

    #[test]
    fn a_file_without_both_gaits_uses_the_lookdev_speeds() {
        let g = Gaits::parse(&serde_json::json!({"walk": {"speed": 1.4}}));
        assert_eq!(g.clips.len(), 2);
        let b = g.blend(3.6, 1.0, OLD, |_| 1.0);
        assert_eq!((b.n, g.clips[b.parts[0].0].clip), (1, "run"));
    }
}
