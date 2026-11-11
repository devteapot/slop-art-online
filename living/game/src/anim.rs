//! Every animated character's pose: locomotion blended at one shared phase, a standing loop,
//! and one-shots over them, on the whole body or the upper body only. One module for connected
//! bodies (`live.rs`), your own character and the look-dev line-up and crowds (`lookdev.rs`), and
//! the wolf. Callers say what the body does ([`Motion`]); this module decides the clips and their
//! weights and drives Bevy's animation player directly (no `AnimationTransitions`).
//!
//! **The graph** (one per file, shared by everyone wearing it):
//!
//! ```text
//! root (blend)
//! ├─ base (blend, weight 1): every clip, whole body
//! └─ every `layer: "upper"` clip again, masked off the hips and legs (mask group 0)
//! ```
//!
//! Group 0 holds every animated bone that is not the spine (`J_Bip_C_Spine`) or below it: hips,
//! legs, the root. A masked clip never touches them, so on those bones the root blend sees only
//! `base`. On the spine, arms and head it blends `base` (weight 1) with the upper clips, so an
//! upper clip at weight `f / (1 − f)` takes the fraction `f`. These are override layers, not
//! Bevy's additive ones: an add node multiplies in a clip's whole local rotation, which for VRoid
//! (identity rest rotations) is the T-pose-relative pose, not a correction, so a sword swing
//! added over a walk would turn the arms twice.
//!
//! **Locomotion.** [`gait::Gaits::blend`] gives up to two gaits and their weights from the drawn
//! speed. All gait clips are paused and set to the same normalised phase every frame, which
//! advances at `speed / (stride × cycle metres)`; their markers start at the same footfall, so
//! no foot mixes with its opposite. A body steps whenever it moves (above [`STEP_ON`], down to
//! [`STEP_OFF`]): at a slow walk's rate its feet still keep still, where standing would glide.
//! Starting from standing, the phase starts at the leading gait's right mid-stance (the planted
//! foot under the hips, the pose nearest standing) while the gait fades in over [`MOVE_IN_REST`]
//! (over [`MOVE_IN`] when a stopping body walks on).
//! Stopping, the phase runs on to the leading gait's next double support
//! (`Contacts::next_settle`) when that is within [`SETTLE_MAX`] of a cycle, no slower than
//! reaching it within [`SETTLE_S`]; further than that it stays put, since running on would slide
//! the planted foot through the rest of its stance. Then standing fades in over [`MOVE_OUT`].
//!
//! **Standing loops** (idle, talk, work, sitting, …) play at their own time and crossfade over
//! [`STAND_FADE`]. A loop starts at an offset of its own for each body, so a herd or a crowd
//! spawned together doesn't graze, look up or breathe in unison. **One-shots** ([`Action`]) are timed on the caller's clock (`now_ms`): they
//! start at `start_ms` (and join part-way when seen late), fade in over [`FADE_IN`] and out over
//! the last [`FADE_OUT`] of the clip, or hold a pose. A clip whose sidecar says `layer: "upper"`
//! plays on the upper body in proportion to how much the body moves, and on the whole body as
//! far as it stands, so a strike while walking keeps the legs in their gait and the same strike
//! standing still uses the whole body. The dodge, death, sitting, getting up and `play` are whole
//! body clips.
//!
//! **For foot IK** (`ik.rs`) this module also gives each foot's contact (0–1) from the markers of
//! the clips the legs show, weighted as they are, and how much of the legs' pose comes from clips
//! where IK applies ([`Anim::ik`]; `ik: false` in the sidecar for sitting and lying).

use crate::combat::Action;
use crate::gait::{self, Gaits};
use crate::lookdev::{Fitted, Model};
use bevy::animation::AnimationTargetId;
use bevy::prelude::*;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

/// Below this drawn speed (m/s) callers count a body as standing (idle or talk, what it is seen
/// doing). The gait itself starts above [`STEP_ON`] and stops below [`STEP_OFF`]: a body that
/// moves at all steps (a slow walk at its stride keeps the feet still), so it never glides.
pub const MOVING: f32 = 0.3;
pub const STEP_ON: f32 = 0.12;
pub const STEP_OFF: f32 = 0.06;
/// A stopping body runs on to double support only when it is this close (in cycles); otherwise
/// it stands from where it is, rather than slide its planted foot through the rest of a stance.
pub const SETTLE_MAX: f32 = 0.2;
/// Gait fades in over this (s) when a stopping body walks on, and over [`MOVE_IN_REST`] when it
/// sets off from standing (the authority starts a body at full speed, and the gait starts from
/// the pose nearest standing, so a long fade would slide the feet); standing fades in over
/// [`MOVE_OUT`] once settled.
pub const MOVE_IN: f32 = 0.2;
pub const MOVE_IN_REST: f32 = 0.08;
pub const MOVE_OUT: f32 = 0.25;
/// A stopping body reaches its settling phase within this (s).
pub const SETTLE_S: f32 = 0.3;
/// Standing loops crossfade over this (s).
pub const STAND_FADE: f32 = 0.22;
/// One-shots fade in and out over these (s).
pub const FADE_IN: f32 = 0.09;
pub const FADE_OUT: f32 = 0.2;
/// Foot contact eases in and out over this (s) round each marker window.
const CONTACT_RAMP_S: f32 = 0.06;
/// Mask group of the bones upper-body clips leave alone.
const LOWER: u32 = 0;

/// What a drawn body is doing, set by its caller every frame.
#[derive(Component, Clone, Debug)]
pub struct Motion {
    /// The drawn body's speed (m/s).
    pub speed: f32,
    /// Its steps against the base's (`Character::stride`, an animal's stage scale).
    pub stride: f32,
    /// The loop it plays standing (idle, talk, work, sit_ground, …).
    pub stand: &'static str,
    /// A one-shot over it (a move, a hit, a death, a gesture, getting up).
    pub action: Option<Action>,
    /// The clock `action.start_ms` is on (ms).
    pub now_ms: f64,
    /// Walking backwards: the gaits play in reverse (the planted foot then moves forward under
    /// the hips, as the body backs away), so legs facing away from the travel keep still feet.
    pub reverse: bool,
    /// How far the upper body turns from the legs toward where the body looks (radians, sim
    /// sense: counter-clockwise seen from above is positive), spread over the spine (`twist.rs`).
    pub twist: f32,
    /// How much faster than its own pace the ground makes the body go (the rules' road speed on
    /// a road; 1 elsewhere). The gait is chosen at `speed / pace`, so a walk on a road stays a
    /// walk, and steps at the body's real speed, so its feet stay planted.
    pub pace: f32,
}

impl Default for Motion {
    fn default() -> Self {
        Self { speed: 0.0, stride: 1.0, stand: "idle", action: None, now_ms: 0.0, reverse: false, twist: 0.0, pace: 1.0 }
    }
}

/// One file's graph and what each node plays.
struct Set {
    graph: Handle<AnimationGraph>,
    full: HashMap<String, AnimationNodeIndex>,
    upper: HashMap<String, AnimationNodeIndex>,
    lens: HashMap<String, f32>,
    gaits: Arc<Gaits>,
    /// Each gait's node and length (s), by its index in `gaits`.
    gait_nodes: Vec<Option<(AnimationNodeIndex, f32)>>,
}

impl Set {
    fn len(&self, clip: &str) -> f32 {
        self.lens.get(clip).copied().unwrap_or(1.0).max(1e-3)
    }

    fn gait_len(&self, i: usize) -> f32 {
        self.gait_nodes.get(i).copied().flatten().map_or(1.0, |(_, l)| l)
    }
}

#[derive(Resource, Default)]
struct Sets(HashMap<String, Arc<Set>>);

/// A one-shot playing or fading out.
#[derive(Clone, Copy, Debug)]
struct Once {
    clip: &'static str,
    rate: f32,
    /// Where in the clip it starts (s), and where its fade out begins (s).
    from: f32,
    cut: Option<f32>,
    /// When it started (the caller's ms), and the latest start asked for it (a confirmed
    /// prediction carries on under the authority's start).
    start_ms: f64,
    key: f64,
    hold: Option<f32>,
    /// Its weight now (0–1) and its time in the clip (s).
    w: f32,
    t: f32,
    upper: bool,
}

/// The pose state of one animated character.
#[derive(Component)]
pub struct Anim {
    player: Entity,
    set: Arc<Set>,
    /// The shared gait phase (0–1). Walking backwards the clips are sampled at `1 − phase`
    /// ([`Anim::clip_phase`]).
    pub phase: f32,
    /// The gaits play in reverse now (see [`Motion::reverse`]).
    pub reverse: bool,
    /// Phase per second while moving.
    rate: f32,
    /// How much the body is in its gait rather than standing (0–1).
    pub moving: f32,
    /// It set off from standing and its gait is still fading in ([`MOVE_IN_REST`]).
    starting: bool,
    /// The phase a stopping body settles at (unwrapped: at or after `phase`), and the least rate
    /// that gets it there within [`SETTLE_S`].
    settle: Option<(f32, f32)>,
    blend: gait::Blend,
    stands: Vec<(&'static str, f32)>,
    onces: Vec<Once>,
    /// The last one-shot that ended (clip, start asked): an action still listed after its clip
    /// ended doesn't play again.
    spent: Option<(&'static str, f64)>,
    /// Nodes this module has playing.
    active: Vec<AnimationNodeIndex>,
    /// The clip that shows most.
    showing: &'static str,
    /// Each foot's contact (people: left, right) from the markers, and how much of the legs'
    /// pose comes from clips where foot IK applies.
    pub feet: [f32; 2],
    pub ik: f32,
}

impl Anim {
    /// Stopping: the gait runs on to its next double support before standing.
    pub fn settling(&self) -> bool {
        self.settle.is_some()
    }

    /// Where in their cycle the gaits are sampled (0–1).
    pub fn clip_phase(&self) -> f32 {
        if self.reverse {
            (1.0 - self.phase).rem_euclid(1.0)
        } else {
            self.phase
        }
    }

    /// The clip that shows most (for recordings).
    pub fn showing(&self) -> &'static str {
        self.showing
    }

    /// The gaits playing now and their weights (for recordings).
    pub fn gaits(&self) -> Vec<(&'static str, f32)> {
        let g = self.set.gaits.gaits();
        self.blend.parts().iter().map(|&(i, w)| (g[i].clip, w * self.moving)).collect()
    }
}

/// The glTF file a body's clips come from, held so the load isn't dropped.
#[derive(Component)]
struct ClipFile(Handle<Gltf>);

pub struct AnimPlugin;

impl Plugin for AnimPlugin {
    fn build(&self, app: &mut App) {
        app.init_resource::<Sets>()
            .init_resource::<Cost>()
            .add_systems(PostUpdate, (build, play, sampling).chain().before(bevy::app::AnimationSystems))
            .add_systems(PostUpdate, sampled.after(bevy::app::AnimationSystems))
            .add_systems(Last, report);
    }
}

/// What animating costs (`LIVING_GAME_PERF=diag` logs it every 2 s): bodies animated, this
/// module's time, and Bevy's animation set's (advancing and sampling every clip that plays).
#[derive(Resource, Default)]
struct Cost {
    bodies: usize,
    frames: u32,
    play_us: f32,
    set_us: f32,
    ik_us: f32,
    ik_solved: usize,
    since: f32,
    start: Option<std::time::Instant>,
}

fn sampling(mut cost: ResMut<Cost>) {
    cost.start = Some(std::time::Instant::now());
}

fn sampled(mut cost: ResMut<Cost>) {
    if let Some(t) = cost.start.take() {
        cost.set_us += t.elapsed().as_secs_f32() * 1e6;
    }
}

fn report(mut cost: ResMut<Cost>, time: Res<Time>, ik: Option<Res<crate::ik::IkStats>>, bodies: Query<(), With<Anim>>) {
    if !crate::perf::has("diag") {
        return;
    }
    cost.frames += 1;
    cost.bodies = bodies.iter().count();
    if let Some(ik) = ik {
        cost.ik_us += ik.micros;
        cost.ik_solved = ik.solved;
    }
    cost.since += time.delta_secs();
    if cost.since >= 2.0 {
        let n = cost.frames.max(1) as f32;
        let per = |us: f32| us / n / cost.bodies.max(1) as f32;
        info!(
            "anim cost: {} bodies; per frame play {:.0} µs, animation set {:.0} µs, ik {:.0} µs ({} solved); per body {:.1} / {:.1} / {:.1} µs",
            cost.bodies,
            cost.play_us / n,
            cost.set_us / n,
            cost.ik_us / n,
            cost.ik_solved,
            per(cost.play_us),
            per(cost.set_us),
            cost.ik_us / n / cost.ik_solved.max(1) as f32
        );
        *cost = Cost::default();
    }
}

/// Give each new animated body its file's graph (built once per file) and its state.
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn build(
    mut commands: Commands,
    assets: Res<AssetServer>,
    gltfs: Res<Assets<Gltf>>,
    clips: Res<Assets<AnimationClip>>,
    mut graphs: ResMut<Assets<AnimationGraph>>,
    mut sets: ResMut<Sets>,
    new: Query<(Entity, &Model, &Motion, Option<&ClipFile>), (With<Fitted>, Without<Anim>)>,
    children: Query<&Children>,
    players: Query<(), With<AnimationPlayer>>,
    targets: Query<(&AnimationTargetId, Option<&Name>)>,
    names: Query<&Name>,
    mut has: Local<HashMap<String, bool>>,
) {
    for (e, model, motion, file) in &new {
        let any = *has.entry(model.file.clone()).or_insert_with(|| crate::lookdev::glb_json(&model.file).is_some_and(|j| j["animations"].as_array().is_some_and(|a| !a.is_empty())));
        if !any {
            continue;
        }
        let Some(file) = file else {
            commands.entity(e).insert(ClipFile(assets.load::<Gltf>(model.file.clone())));
            continue;
        };
        let Some(gltf) = gltfs.get(&file.0) else { continue };
        let Some(p) = children.iter_descendants(e).find(|d| players.contains(*d)) else { continue };
        let set = match sets.0.get(&model.file) {
            Some(s) => s.clone(),
            None => {
                // Every clip's length; wait until all are loaded.
                let lens: Option<HashMap<String, f32>> = gltf.named_animations.iter().map(|(n, h)| clips.get(h).map(|a| (n.to_string(), a.duration()))).collect();
                let Some(lens) = lens else { continue };
                let gaits = gait::of(&model.file);
                // The upper body: the spine and everything below it.
                let spine = children.iter_descendants(p).find(|d| names.get(*d).is_ok_and(|n| n.as_str() == "J_Bip_C_Spine"));
                let upper_bones: HashSet<Entity> = spine.map(|s| std::iter::once(s).chain(children.iter_descendants(s)).collect()).unwrap_or_default();
                let mut graph = AnimationGraph::new();
                if spine.is_some() {
                    for d in children.iter_descendants(p) {
                        if let Ok((id, _)) = targets.get(d) {
                            if !upper_bones.contains(&d) {
                                graph.add_target_to_mask_group(*id, LOWER);
                            }
                        }
                    }
                }
                let base = graph.add_blend(1.0, graph.root);
                let mut full = HashMap::new();
                let mut upper = HashMap::new();
                for (n, h) in &gltf.named_animations {
                    full.insert(n.to_string(), graph.add_clip(h.clone(), 1.0, base));
                    if spine.is_some() && gaits.info(n).is_some_and(|i| i.upper) {
                        upper.insert(n.to_string(), graph.add_clip_with_mask(h.clone(), 1 << LOWER, 1.0, graph.root));
                    }
                }
                let gait_nodes = gaits.gaits().iter().map(|g| full.get(g.clip).map(|&n| (n, g.seconds.unwrap_or_else(|| lens.get(g.clip).copied().unwrap_or(1.0))))).collect();
                debug!("anim: {}: {} clips, {} upper, {} lower bones masked", model.file, full.len(), upper.len(), graph.mask_groups.len());
                let set = Arc::new(Set { graph: graphs.add(graph), full, upper, lens, gaits, gait_nodes });
                sets.0.insert(model.file.clone(), set.clone());
                set
            }
        };
        commands.entity(p).insert(AnimationGraphHandle(set.graph.clone()));
        let stand = if set.full.contains_key(motion.stand) { motion.stand } else { "idle" };
        commands.entity(e).insert(Anim {
            player: p,
            set,
            phase: 0.0,
            reverse: false,
            rate: 0.0,
            moving: 0.0,
            starting: false,
            settle: None,
            blend: gait::Blend { parts: [(0, 1.0), (0, 0.0)], n: 1, cycle_m: 1.0 },
            stands: vec![(stand, 1.0)],
            onces: vec![],
            spent: None,
            active: vec![],
            showing: stand,
            feet: [1.0, 1.0],
            ik: 0.0,
        });
    }
}

/// A clip name as `&'static str` (names from the environment or files; each is kept once).
pub fn intern(name: &str) -> &'static str {
    use std::sync::{Mutex, OnceLock};
    static NAMES: OnceLock<Mutex<HashSet<&'static str>>> = OnceLock::new();
    let mut names = NAMES.get_or_init(Default::default).lock().unwrap();
    if let Some(n) = names.get(name) {
        return n;
    }
    let n: &'static str = Box::leak(name.to_string().into_boxed_str());
    names.insert(n);
    n
}

/// Move `x` toward `to`, up by at most `up` and down by at most `down`.
fn approach(x: f32, to: f32, up: f32, down: f32) -> f32 {
    if to > x {
        (x + up).min(to)
    } else {
        (x - down).max(to)
    }
}

/// How a node plays this frame.
#[derive(Clone, Copy)]
enum Play {
    /// Paused at this time (s): gaits at the shared phase, one-shots on the caller's clock.
    At(f32),
    /// Looping at its own time; it starts at this time (s).
    Loop(f32),
}

fn play(mut commands: Commands, time: Res<Time>, mut q: Query<(Entity, &Motion, &mut Anim)>, mut players: Query<&mut AnimationPlayer>, mut cost: ResMut<Cost>) {
    let t0 = std::time::Instant::now();
    let dt = time.delta_secs().min(0.1);
    for (e, m, mut a) in &mut q {
        let Ok(mut player) = players.get_mut(a.player) else {
            // The scene was rebuilt: find its player again.
            commands.entity(e).remove::<Anim>();
            continue;
        };
        let set = a.set.clone();
        let a = &mut *a;
        step(a, &set, m, dt);
        // What plays, at what weight, and how.
        let mut want: Vec<(AnimationNodeIndex, f32, Play)> = Vec::with_capacity(8);
        let full_once: f32 = a.onces.iter().map(|o| o.w * if o.upper { 1.0 - a.moving } else { 1.0 }).sum();
        let base = (1.0 - full_once).max(0.0);
        let mut legs: Vec<(&'static str, f32, f32, bool)> = Vec::with_capacity(6);
        let clip_phase = a.clip_phase();
        for &(i, w) in a.blend.parts() {
            let w = base * a.moving * w;
            if let (Some((node, len)), true) = (set.gait_nodes.get(i).copied().flatten(), w > 0.0) {
                want.push((node, w, Play::At(clip_phase * len)));
                legs.push((set.gaits.gaits()[i].clip, w, clip_phase, true));
            }
        }
        let stand_sum: f32 = a.stands.iter().map(|s| s.1).sum::<f32>().max(1e-6);
        for &(clip, sw) in &a.stands {
            let w = base * (1.0 - a.moving) * sw / stand_sum;
            if let (Some(&node), true) = (set.full.get(clip), w > 0.0) {
                // Each body's own offset into the loop (the golden ratio spreads entity indices).
                let offset = (e.index_u32() as f32 * 0.618_034).fract() * set.len(clip);
                want.push((node, w, Play::Loop(offset)));
                let t = player.animation(node).map_or(0.0, |x| x.seek_time()) / set.len(clip);
                legs.push((clip, w, t, true));
            }
        }
        let ups: f32 = a.onces.iter().filter(|o| o.upper).map(|o| o.w * a.moving).sum::<f32>().min(0.999);
        for o in &a.onces {
            let full = o.w * if o.upper { 1.0 - a.moving } else { 1.0 };
            if let (Some(&node), true) = (set.full.get(o.clip), full > 0.0) {
                want.push((node, full, Play::At(o.t)));
                legs.push((o.clip, full, o.t / set.len(o.clip), false));
            }
            let up = if o.upper { o.w * a.moving } else { 0.0 };
            if let (Some(&node), true) = (set.upper.get(o.clip), up > 0.0) {
                want.push((node, up / (1.0 - ups), Play::At(o.t)));
            }
        }
        // Stop what no longer plays, then set the rest.
        for n in a.active.drain(..) {
            if !want.iter().any(|w| w.0 == n) {
                player.stop(n);
            }
        }
        for &(node, w, how) in &want {
            let fresh = !player.is_playing_animation(node);
            let x = player.play(node);
            x.set_weight(w);
            match how {
                Play::At(t) => {
                    x.pause().set_seek_time(t);
                }
                Play::Loop(offset) => {
                    if fresh {
                        x.set_seek_time(offset);
                    }
                    x.resume().set_speed(1.0).repeat();
                }
            }
            a.active.push(node);
        }
        // What shows most, and the feet's contacts for IK.
        a.showing = legs.iter().max_by(|x, y| x.1.total_cmp(&y.1)).map_or(a.showing, |l| l.0);
        if let Some(o) = a.onces.iter().rev().find(|o| o.upper && o.w * a.moving > 0.5) {
            a.showing = o.clip;
        }
        let (mut feet, mut ik, mut all) = ([0.0f32; 2], 0.0f32, 0.0f32);
        for &(clip, w, t, cyclic) in &legs {
            all += w;
            let Some(info) = set.gaits.info(clip) else { continue };
            if !info.ik || info.contacts.feet() != 2 {
                continue;
            }
            let ramp = CONTACT_RAMP_S / set.len(clip);
            for (f, c) in feet.iter_mut().enumerate() {
                *c += w * info.contacts.weight(f, t, ramp, cyclic);
            }
            ik += w;
        }
        if ik > 0.0 {
            a.feet = feet.map(|c| c / ik);
        }
        a.ik = if all > 0.0 { ik / all } else { 0.0 };
    }
    cost.play_us += t0.elapsed().as_secs_f32() * 1e6;
}

/// Advance one body's state by `dt`: its one-shots, gait phase and standing loops.
fn step(a: &mut Anim, set: &Set, m: &Motion, dt: f32) {
    // One-shots. A requested move already showing in the same clip (my predicted one, now
    // confirmed) carries on; a new start replays it.
    let want = m.action.filter(|x| set.full.contains_key(x.clip));
    if let Some(x) = want {
        let carry = a.onces.last().is_some_and(|o| o.clip == x.clip && (o.key == x.start_ms || (o.w > 0.0 && (o.hold.is_some() || o.t < set.len(o.clip)))));
        if carry {
            let o = a.onces.last_mut().unwrap();
            o.rate = x.rate;
            o.hold = x.hold;
            o.key = x.start_ms;
        } else if x.start_ms <= m.now_ms && a.spent != Some((x.clip, x.start_ms)) {
            let upper = set.upper.contains_key(x.clip);
            a.onces.push(Once { clip: x.clip, rate: x.rate, from: x.from, cut: x.cut, start_ms: x.start_ms, key: x.start_ms, hold: x.hold, w: 0.0, t: x.from, upper });
            if a.onces.len() > 2 {
                a.onces.remove(0);
            }
        }
    }
    let last = a.onces.len().saturating_sub(1);
    for (i, o) in a.onces.iter_mut().enumerate() {
        let len = set.len(o.clip);
        let end = o.cut.map_or(len, |c| c.min(len) + FADE_OUT * o.rate).min(len);
        let requested = i == last && want.is_some_and(|x| x.clip == o.clip && x.start_ms == o.key);
        o.t = o.from + (((m.now_ms - o.start_ms) / 1000.0) as f32 * o.rate).max(0.0);
        if let Some(h) = o.hold {
            o.t = o.t.min(h * len);
        }
        o.t = o.t.min(end);
        let ending = o.hold.is_none() && (end - o.t) / o.rate.max(0.01) < FADE_OUT;
        let target = if requested && !ending { 1.0 } else { 0.0 };
        o.w = approach(o.w, target, dt / FADE_IN, dt / FADE_OUT);
    }
    let mut spent = a.spent;
    a.onces.retain(|o| {
        let end = o.cut.map_or(set.len(o.clip), |c| (c + FADE_OUT * o.rate).min(set.len(o.clip)));
        let keep = o.w > 0.0 || want.is_some_and(|x| x.clip == o.clip && x.start_ms == o.key && o.t < end);
        if !keep {
            spent = Some((o.clip, o.key));
        }
        keep
    });
    a.spent = spent;
    // Locomotion at one shared phase. Turning from forward to backward walking keeps the clip
    // time where it is (the pose doesn't jump): the phase becomes its mirror.
    if m.reverse != a.reverse {
        if a.moving > 0.0 {
            a.phase = (1.0 - a.phase).rem_euclid(1.0);
            a.settle = None;
        }
        a.reverse = m.reverse;
    }
    // A whole-body one-shot asked for (a dodge's dash, a death) covers the legs: no gait starts
    // under it, so its first frames don't show a sprint while it fades in.
    // My own body is drawn ahead of the display clock that times one-shots, so its dash can
    // move before its clip starts: asked for is enough.
    let covered = want.is_some_and(|x| !set.upper.contains_key(x.clip));
    let stepping = !covered && if a.moving > 0.0 && a.settle.is_none() { m.speed > STEP_OFF } else { m.speed > STEP_ON };
    let moving = if stepping {
        let b = set.gaits.blend(m.speed / m.pace.max(0.5), m.stride, |i| set.gait_len(i));
        if a.moving <= 0.0 {
            // From standing: the leading gait's right mid-stance (its pose nearest standing: the
            // planted foot under the hips, the other one stepping off).
            let lead = b.parts().iter().max_by(|x, y| x.1.total_cmp(&y.1)).map(|&(i, _)| i);
            let mid = lead.and_then(|i| set.gaits.info(set.gaits.gaits()[i].clip)).map_or(0.0, |i| i.contacts.mid_stance(1));
            a.phase = if a.reverse { (1.0 - mid).rem_euclid(1.0) } else { mid };
            a.starting = true;
        }
        a.settle = None;
        a.blend = b;
        a.rate = m.speed / (m.stride.max(0.05) * b.cycle_m.max(0.05));
        a.phase += a.rate * dt;
        1.0
    } else if a.moving > 0.0 {
        // Stopping: run on to the leading gait's next double support, then stand.
        let lead = a.blend.parts().iter().max_by(|x, y| x.1.total_cmp(&y.1)).map(|&(i, _)| i);
        let contacts = lead.and_then(|i| set.gaits.info(set.gaits.gaits()[i].clip)).map(|i| &i.contacts);
        let phase = a.phase;
        let reverse = a.reverse;
        let (goal, least) = *a.settle.get_or_insert_with(|| {
            // Walking backwards it stands from where it is (the next double support lies behind
            // the clip time, and a short stop from a back step slides little).
            let goal = contacts.filter(|c| !c.is_empty() && !reverse).map_or(phase, |c| c.next_settle(phase));
            let goal = if goal - phase <= SETTLE_MAX { goal } else { phase };
            (goal, (goal - phase) / SETTLE_S)
        });
        if goal - a.phase > 1e-5 {
            a.phase = (a.phase + a.rate.max(least) * dt).min(goal);
            1.0
        } else {
            0.0
        }
    } else {
        a.settle = None;
        0.0
    };
    if a.phase >= 1.0 {
        let k = a.phase.floor();
        a.phase -= k;
        if let Some((g, _)) = a.settle.as_mut() {
            *g -= k;
        }
    }
    a.starting &= moving > 0.0 && a.moving < 1.0;
    a.moving = approach(a.moving, moving, dt / if a.starting { MOVE_IN_REST } else { MOVE_IN }, dt / MOVE_OUT);
    // Standing loops crossfade.
    let stand = if set.full.contains_key(m.stand) { m.stand } else { "idle" };
    if !a.stands.iter().any(|s| s.0 == stand) {
        a.stands.push((stand, 0.0));
    }
    for s in &mut a.stands {
        let to = if s.0 == stand { 1.0 } else { 0.0 };
        s.1 = approach(s.1, to, dt / STAND_FADE, dt / STAND_FADE);
    }
    a.stands.retain(|s| s.1 > 0.0 || s.0 == stand);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn set() -> Set {
        let gaits = Arc::new(crate::gait::tests::vivi());
        let names = ["idle", "talk", "walk", "walk_brisk", "run", "run_fast", "wave", "dodge"];
        let full: HashMap<String, AnimationNodeIndex> = names.iter().enumerate().map(|(i, n)| (n.to_string(), AnimationNodeIndex::new(i + 1))).collect();
        let upper = [("wave".to_string(), AnimationNodeIndex::new(20))].into_iter().collect();
        let lens: HashMap<String, f32> = names.iter().map(|n| (n.to_string(), 1.0)).collect();
        let gait_nodes = gaits.gaits().iter().map(|g| full.get(g.clip).map(|&n| (n, g.seconds.unwrap_or(1.0)))).collect();
        Set { graph: Handle::default(), full, upper, lens, gaits, gait_nodes }
    }

    fn anim(set: &Arc<Set>) -> Anim {
        Anim {
            player: Entity::PLACEHOLDER,
            set: set.clone(),
            phase: 0.0,
            reverse: false,
            rate: 0.0,
            moving: 0.0,
            starting: false,
            settle: None,
            blend: gait::Blend { parts: [(0, 1.0), (0, 0.0)], n: 1, cycle_m: 1.0 },
            stands: vec![("idle", 1.0)],
            onces: vec![],
            spent: None,
            active: vec![],
            showing: "idle",
            feet: [1.0; 2],
            ik: 0.0,
        }
    }

    #[test]
    fn walking_off_starts_at_the_right_foot_and_the_phase_keeps_the_feet_still() {
        let s = Arc::new(set());
        let mut a = anim(&s);
        let m = Motion { speed: 1.4, ..default() };
        step(&mut a, &s, &m, 0.0);
        let mid = (0.0 + 0.5806) / 2.0;
        assert!((a.phase - mid).abs() < 0.02, "starts at the right mid-stance, not {}", a.phase);
        // One cycle covers the blend's metres: at 1.4 m/s the phase advances 1.4 / cycle a second.
        let p = a.phase;
        step(&mut a, &s, &m, 0.05);
        assert!((a.phase - p - 0.05 * 1.4 / a.blend.cycle_m).abs() < 1e-5);
        assert!(a.moving > 0.0 && a.moving < 1.0, "the gait fades in");
        // From standing it is in within MOVE_IN_REST: the authority starts a body at full speed.
        step(&mut a, &s, &m, MOVE_IN_REST - 0.05 + 1e-4);
        assert_eq!(a.moving, 1.0, "in after {MOVE_IN_REST} s from standing");
    }

    #[test]
    fn walking_backwards_reverses_the_phase_without_a_jump() {
        let s = Arc::new(set());
        let mut a = anim(&s);
        let fwd = Motion { speed: 1.4, ..default() };
        for _ in 0..30 {
            step(&mut a, &s, &fwd, 1.0 / 60.0);
        }
        let before = a.clip_phase();
        let back = Motion { speed: 1.4, reverse: true, ..default() };
        step(&mut a, &s, &back, 0.0);
        assert!((a.clip_phase() - before).abs() < 1e-5, "the pose holds at the turn: {before} -> {}", a.clip_phase());
        // Walking on backwards, the clip time runs down at the same rate.
        step(&mut a, &s, &back, 0.05);
        let d = (before - a.clip_phase()).rem_euclid(1.0);
        assert!((d - 0.05 * 1.4 / a.blend.cycle_m).abs() < 1e-4, "clip time runs backwards: {d}");
    }

    #[test]
    fn stopping_settles_at_double_support_before_standing() {
        let s = Arc::new(set());
        let mut a = anim(&s);
        let walk = Motion { speed: 1.4, ..default() };
        // Walk until just before the double support (Vivi's walk: 0.516–0.58).
        while !(a.moving >= 1.0 && a.phase > 0.4 && a.phase < 0.45) {
            step(&mut a, &s, &walk, 1.0 / 240.0);
        }
        let stop = Motion { speed: 0.0, ..default() };
        let c = &s.gaits.info("walk").unwrap().contacts;
        let mut t = 0.0;
        while a.moving > 0.0 && t < 2.0 {
            step(&mut a, &s, &stop, 1.0 / 60.0);
            t += 1.0 / 60.0;
            if a.moving < 1.0 {
                assert_eq!(c.count(a.phase), 2, "standing fades in only in double support (phase {})", a.phase);
            }
        }
        assert!(t <= SETTLE_S + MOVE_OUT + 0.05, "settled and stood within {t} s");
    }

    #[test]
    fn a_new_move_replays_and_a_confirmed_one_carries_on() {
        let s = Arc::new(set());
        let mut a = anim(&s);
        let act = |start: f64| Action { clip: "wave", rate: 1.0, start_ms: start, hold: None, face: None, ..Default::default() };
        step(&mut a, &s, &Motion { action: Some(act(0.0)), now_ms: 100.0, ..default() }, 0.1);
        assert_eq!(a.onces.len(), 1);
        assert!((a.onces[0].t - 0.1).abs() < 1e-4, "joins part-way when seen late");
        // The authority's start (my prediction confirmed) a little later: carries on.
        step(&mut a, &s, &Motion { action: Some(act(60.0)), now_ms: 200.0, ..default() }, 0.1);
        assert_eq!(a.onces.len(), 1);
        assert_eq!(a.onces[0].start_ms, 0.0);
        // After it ends, a new start replays it.
        for k in 3..14 {
            step(&mut a, &s, &Motion { action: Some(act(60.0)), now_ms: 100.0 * k as f64, ..default() }, 0.1);
        }
        assert!(a.onces.is_empty(), "it ended and does not play again while still listed");
        step(&mut a, &s, &Motion { action: Some(act(1500.0)), now_ms: 1500.0, ..default() }, 0.1);
        assert_eq!(a.onces.last().unwrap().start_ms, 1500.0);
    }
}
