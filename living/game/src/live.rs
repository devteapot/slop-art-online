//! Connected play on a land world (the island the authority hosts; docs/ISLAND_AUTHORITY.md).
//! Presentation only: the rules move every character, the player included, and decide what
//! stands where. This module draws what the client receives (`net.rs`, [`net::Mode::Land`])
//! through the island renderer (`island.rs`):
//!
//! - **Land.** The `land` row's seed, size and parameters regenerate the same `Land` here
//!   (`living_rules::land` is deterministic across targets), on a worker thread. Its three
//!   digests (hosted tiles, heights, layout) are compared with the row's before the island is
//!   drawn; a mismatch is logged and the island is still drawn, while movement stays the
//!   authority's tiles either way (the client predicts nothing).
//! - **Buildings** from the `lot` rows in the window, by their model file
//!   ([`Island::spawn_lot`]); none from the client's own planner.
//! - **Characters** from the bodies in the window: people as recipe characters (seeded by
//!   character id; folk and dress from the settlement round their home, `settlement.kind`,
//!   `settlement.style`; children smaller by life stage), wolves and deer as their rigged files
//!   ([`crate::bodies::spawn_beast`]: walk, trot or run by speed, a wolf's bite and leap, a
//!   flinch and death; scaled by life stage; a deer startles before it flees, [`STARTLE`]),
//!   other animals as the procedural creatures of `bodies.rs`.
//!   Clips follow the displayed motion: idle, walk or run by speed (the authority's
//!   walk is about 2.6 m/s and its run about 4.1), talk while speaking, and over a standing body
//!   what it is seen doing (`town.rs`: work, gathering, eating, play, sitting, a wave or a nod).
//!   Positions come from the shared body tracks (`sync.rs`, filled by `bodies::update`).
//! - **Facing.** A moving body faces its travel; a standing one its own segment's heading,
//!   turning on the spot at the rate the authority's turn carries (`turn` × `turn_s` at zero
//!   speed: `face`, and the turn before a gesture), or toward what its activity is aimed at.
//!   Drawn yaw eases toward that, so a stop or a new aim never snaps.
//! - **Indoors.** A sleeper, or someone resting at their own door, is in the house: not drawn
//!   (`town.rs`); they reappear at the door when they come out.
//! - **You** join at the `land` row's arrival point (`join`); the camera, the island's
//!   streaming and the atmosphere follow your displayed body. The cursor meets the island's
//!   ground for facing and click-to-move.
//!
//! `LIVING_GAME_LIVE=<dir>` runs a script headless and writes photographs there
//! (`LIVING_GAME_LIVE_PLAN`, [`Script`]).

use crate::bodies::stage_scale;
use crate::camera::Cam;
use crate::controls::{Input, Target};
use crate::envs::Roam;
use crate::island::{Island, LotRow};
use crate::lookdev::{Fitted, Model};
use crate::net::{Mode, Net};
use crate::phase::Phase;
use crate::anim::Motion;
use crate::world::Scene;
use bevy::prelude::*;
use living_bindings::*;
use living_rules::land::{Land, LandParams};
use living_rules::map::{chunk_xy, Map, CHUNK};
use spacetimedb_sdk::Table;
use std::collections::{HashMap, HashSet};
use std::f32::consts::PI;
use std::sync::{Arc, Mutex};

/// Lots are drawn within this distance (m) and dropped beyond `LOT_DROP`.
const LOT_FAR: f32 = 190.0;
const LOT_DROP: f32 = 220.0;
/// Building spawns per frame, so a window move doesn't hitch.
const LOTS_PER_FRAME: usize = 6;
/// Speeds (m/s): below `MOVING` a body stands (idle or talk; above it `anim.rs` blends its
/// gaits; whether it walks or runs is [`family`]'s).
const MOVING: f32 = crate::anim::MOVING;

/// Walking or running clips for every person ([`crate::gait::Family`]): the one place it is
/// decided. The authority's word first: a body's row says whether it runs (`Moving::running`,
/// stamina-1: a run under way with breath, whoever controls it). `run_w` is that body's running
/// weight, eased toward the word over [`RUN_EASE_S`] so a switch crossfades the two families
/// instead of popping. Without a row, the laws' split ([`law_split`]), else the clips' own.
fn family(running: Option<bool>, run_w: &mut f32, dt: f32, split: Option<f32>) -> crate::gait::Family {
    match running {
        Some(r) => {
            let step = dt / RUN_EASE_S;
            *run_w = (*run_w + if r { step } else { -step }).clamp(0.0, 1.0);
            crate::gait::Family::Mix(*run_w).settled()
        }
        None => split.map_or(crate::gait::Family::Clips, crate::gait::Family::Split),
    }
}

/// A body's switch between walking and running clips crossfades over this (s).
const RUN_EASE_S: f32 = 0.25;

/// The speed between walking and running by the world's laws (m/s, a grown person off a road):
/// the geometric mean of a rested grown person's walking speed (`move_speed`) and running speed
/// (`motion`'s `run` times it). None without the laws or with speeds that don't make sense.
fn law_split(sc: &living_rules::script::Scripts) -> Option<f32> {
    let ctx = living_rules::script::SkillCtx {
        actor: living_rules::script::ActorFacts { kind: "person".into(), stage: "adult".into(), hp: 100.0, energy: 100.0, ..Default::default() },
        ..Default::default()
    };
    let walk = sc.move_speed(&ctx).ok()?;
    let run = walk * sc.moves(&ctx).ok()?.run;
    (walk > 0.1 && run > walk * 1.01).then(|| (walk * run).sqrt())
}
/// A line counts as being spoken for this long (s).
const TALKING_S: f64 = 4.0;

pub struct LivePlugin;

impl Plugin for LivePlugin {
    fn build(&self, app: &mut App) {
        let island = resource_exists::<Island>;
        app.init_resource::<Live>()
            .init_resource::<LandWorld>()
            .add_systems(Update, mirror.in_set(Phase::Mirror).before(crate::bodies::update))
            .insert_resource(Roam { facing: Vec2::new(0.0, 1.0), ..default() })
            .add_systems(Startup, crate::lookdev::setup)
            // What each body plays is decided this frame (combat's actions, town's shows) before
            // it is drawn.
            .add_systems(Update, (land, lots, bodies, me).chain().in_set(Phase::Present).after(crate::combat::actions).after(crate::town::shows))
            .add_systems(
                Update,
                (crate::envs::hdr, crate::island::stream, crate::island::grey_boxes, crate::island::report, crate::lookdev::convert, crate::lookdev::night_glow, crate::lookdev::fit, crate::envs::solid_if_large, crate::lookdev::rig, crate::lookdev::animate, crate::lookdev::sun, crate::envs::cutaway, crate::envs::reach, report)
                    .chain()
                    .in_set(Phase::Present)
                    .after(me)
                    .run_if(island),
            )
            .add_systems(Update, ground_cursor.in_set(Phase::Camera).after(crate::camera::follow).run_if(island))
            // After sight, which sets every thing's visibility each frame: what stands inside a
            // closed building is hidden over it.
            .add_systems(Update, indoors.in_set(Phase::Camera).after(crate::sight::update).run_if(island));
        if let Some(s) = Script::from_env() {
            app.insert_resource(s).add_systems(Update, script.in_set(Phase::Input).before(crate::controls::movement).before(crate::ui::UiInput));
        }
    }
}

/// What stands inside a planned lot's building ([`crate::world::Indoors`]: a household's hearth
/// and store on its house's floor) is hidden while that building is drawn closed, or not drawn at
/// all; while the cutaway has it open, it is drawn as sight says (`sight::update`, which runs
/// first and sets every thing's visibility each frame), and a kit model once it is fitted.
fn indoors(live: Res<Live>, lots: Query<&crate::envs::Occluder>, mut q: Query<(&crate::world::Indoors, &mut Visibility)>, mut was: Local<HashMap<u32, bool>>) {
    for (inside, mut vis) in &mut q {
        let open = live.lots.get(&inside.0).and_then(|es| es.first()).and_then(|e| lots.get(*e).ok()).is_some_and(|o| o.open);
        if was.insert(inside.0, open) != Some(open) {
            // For checks (`RUST_LOG=living_game::live=debug`): once each time a building opens or closes.
            debug!("indoors: lot {} {}", inside.0, if open { "open: what stands inside it is drawn" } else { "closed: what stands inside it is hidden" });
        }
        if !open && *vis != Visibility::Hidden {
            *vis = Visibility::Hidden;
        }
    }
}

/// Whether the server hosts a land world, mirrored from `Net` (run conditions may run off the
/// main thread, where `Net` cannot be read).
#[derive(Resource, Default)]
pub struct LandWorld(bool);

fn mirror(net: NonSend<Net>, mut land: ResMut<LandWorld>) {
    let on = net.mode == Mode::Land;
    if land.0 != on {
        land.0 = on;
    }
}

/// Tile worlds draw with `world.rs`; land worlds with this module.
pub fn tiles(land: Res<LandWorld>) -> bool {
    !land.0
}

/// Whether a headless script runs (`LIVING_GAME_LIVE`).
pub fn scripted() -> bool {
    std::env::var("LIVING_GAME_LIVE").is_ok_and(|v| !v.is_empty())
}

/// The land regenerated from the `land` row, and how it compares.
struct Built {
    land: Arc<Land>,
    hosted: Arc<Map>,
    /// (digest, ours, the authority's)
    digests: [(&'static str, u64, u64); 3],
    params: LandParams,
    secs: f32,
}

/// One drawn body.
struct Shown {
    entity: Entity,
    last: Vec2,
    speed: f32,
    person: bool,
    /// A rigged creature ([`crate::bodies::Beast`]): faces +Z, sized by life stage here.
    beast: bool,
    /// Drawn facing (sim angle), eased toward the wanted one.
    yaw: f32,
    /// Where the body is drawn (sim metres): the authority's position, except while a sitter
    /// gets up and then catches up ([`STAND_UP`]).
    drawn: Vec2,
    /// Sitting on the ground last frame (`sit_ground`).
    sitting: bool,
    /// Getting up: since when (display ms) and where it sat.
    rising: Option<(f64, Vec2)>,
    /// Its file has a startle ([`STARTLE`]); how long it has stood (s); a startle playing: since
    /// when (display ms) and where it stood.
    startles: bool,
    still: f32,
    startle: Option<(f64, Vec2)>,
    /// A rigged animal's tilt with the ground under its paws (`bodies::lie_on`), eased.
    tilt: Quat,
    kind: String,
    /// A person's upper-body facing (sim angle), eased like `yaw`; it differs from the legs'
    /// while walking one way and looking another (`twist::LookWalk`).
    face: f32,
    /// Walking backwards while looking back (`twist::LookWalk::back_deg`): the legs face away
    /// from the travel.
    back: bool,
    /// Standing and looking somewhere: the legs are turning to the look ([`STAND_TURN_ON`]).
    turning: bool,
    /// A turn take playing (standing) and a jump take (`takes.rs`), the jump the last was chosen
    /// for (its start, display ms) and whether it had a take.
    turn: Option<crate::takes::Playing>,
    jump: Option<crate::takes::Playing>,
    jump_key: f64,
    jump_took: bool,
    /// Walking last frame, and walking forward with the legs within [`ALONG`] of the travel (a
    /// stop take plays only then).
    walked: bool,
    along: bool,
    /// A stop take playing (`takes::stop_for`), where the body was drawn when it began, and where
    /// a stopped body stays drawn after it, until it moves again (its track runs up to 0.26 m past
    /// the authority's stop; catching up would slide the standing feet back).
    stop: Option<crate::takes::Playing>,
    stop_at: Vec2,
    rest_at: Option<Vec2>,
    /// The drawn speed before any move under way (a jump's dash speeds the body up).
    calm_speed: f32,
    /// How far the body's gaits are the running family's (0–1), eased toward its row's
    /// `running` ([`family`]).
    run_w: f32,
    /// The look key it was drawn from (`characters::seen`; empty for none). A new key (a band
    /// change, a `relook`) redraws the person in place ([`swap_look`]).
    look: String,
    /// Drawn from the look's line (else a VRoid recipe).
    composed: bool,
}

/// A person drawn, as the UI dump reports them (`ui::DumpExtra::looks_json`).
pub struct DrawnLook<'a> {
    pub id: u32,
    pub look: &'a str,
    pub composed: bool,
    pub swapping: bool,
}

/// A sitter whose rest ends gets up where it sat before walking off (`stand_up_ground`, 2.47 s,
/// played at this rate). The authority moves the body at once, so the drawn body waits at its
/// seat while the clip plays, then catches up at up to [`CATCH_UP`] m/s faster than the body.
const STAND_UP: (&str, f32, f64) = ("stand_up_ground", 1.6, 2467.0 / 1.6);
const CATCH_UP: f32 = 1.2;
/// A turn take turns the legs at most this fast (radians a second): its own curve stays under it.
const TURN_MAX: f32 = 720.0 * PI / 180.0;
/// Legs within this of the travel (radians) walk along it: a stop take may play.
const ALONG: f32 = 15.0 * PI / 180.0;
/// A body this far (m) from where it is drawn is drawn there at once: a teleport (an admin
/// `place_at`) used to crawl in at [`CATCH_UP`], tens of seconds for a few tens of metres.
const SNAP_M: f32 = 6.0;

/// A creature whose file has a `startle` clip (the deer) and that sets off at least this fast
/// (m/s, the authority's velocity) after standing [`STILL_S`] is fleeing: the rules' flee is
/// 1.15 × the deer's 3.7 m/s walk, and its speed gene varies by a few per cent, so a wander
/// (3.5–3.9 m/s) never reaches it. It plays the startle where it stood, held there for the
/// clip's gathering and spring (s), then catches up as a sitter getting up does ([`CATCH_UP`]).
const STARTLE: (&str, f64) = ("startle", 420.0);
const STARTLE_V: f32 = 4.0;
const STILL_S: f32 = 1.0;

/// How fast a drawn gait takes up a slower segment's speed (1/s): about 95% in 0.15 s.
const SLOWING: f32 = 20.0;
/// How fast drawn yaw takes up a new facing (1/s): about 90% in 0.15 s.
const YAW_RATE: f32 = 16.0;
/// Standing while looking somewhere (my cursor, a move's aim), the upper body turns first; the
/// legs turn after it only once the look is more than this far from them (radians, or the
/// look-walk's head and chest limit when that is less), and then all the way, until within
/// [`STAND_TURN_OFF`]. Before, the whole body followed every move of
/// the cursor, so the feet stepped or slid whenever it moved.
const STAND_TURN_ON: f32 = 55.0 * PI / 180.0;
const STAND_TURN_OFF: f32 = 6.0 * PI / 180.0;

/// Where a body faces on the authority (look-2), when that is not its travel: the row's travel
/// segment turned by its facing offset at `now_ms` (authority ms), as `steer::facing` evaluates
/// it with `dt = (min(now, next_ms) − t_ms) / 1000`. None when the row holds no offset (the body
/// faces its travel).
fn authority_facing(m: &living_bindings::Moving, now_ms: f64) -> Option<f32> {
    if m.face_off == 0.0 && (m.face_turn == 0.0 || m.face_turn_s <= 0.0) {
        return None;
    }
    let dt = ((now_ms.min(m.next_ms as f64) - m.t_ms as f64) / 1000.0).max(0.0) as f32;
    let travel = m.heading + if m.turn_s > 0.0 { m.turn * dt.min(m.turn_s) } else { 0.0 };
    let off = living_rules::steer::face_off(m.face_off, m.face_turn, m.face_turn_s, dt);
    (off.abs() > 1e-3).then(|| living_rules::steer::facing(travel, m.face_off, m.face_turn, m.face_turn_s, dt))
}

#[derive(Resource, Default)]
pub struct Live {
    building: Option<Arc<Mutex<Option<Result<Built, String>>>>>,
    /// The laws' walk/run split ([`law_split`]) and the script revision it was read under.
    walk_run: Option<(u32, Option<f32>)>,
    /// Whether all three digests matched (None until compared).
    pub digests_ok: Option<bool>,
    /// The tiles as the authority hosted them at world creation, to find later edits.
    hosted: Option<Arc<Map>>,
    lots: HashMap<u32, Vec<Entity>>,
    shown: HashMap<u32, Shown>,
    /// Height (m) of each drawn character, for nameplates and bubbles.
    pub heights: HashMap<u32, f32>,
    /// Bodies gone from sight, fading out where they were last drawn (`fade.rs`), how long
    /// they have been fading (s), whose they were, and whether they stay a moment as a faint
    /// figure first (the memory look under trial, `sightedge::Look`).
    leaving: Vec<(Entity, f32, u32, bool)>,
    /// People redrawn in place for a new look ([`swap_look`]): the old body, kept drawn and
    /// moving with the new until the new is fitted, then faded out as the new fades in.
    swaps: Vec<(Entity, Entity, u32)>,
    /// The world's look generation has been checked against the book (one warning at connect).
    looks_checked: bool,
}

impl Live {
    /// The tiles as the authority hosted them at world creation (`host::hosted_map`), once the
    /// land is regenerated.
    pub fn hosted_map(&self) -> Option<Arc<Map>> {
        self.hosted.clone()
    }

    /// Each person drawn and the look they were drawn from.
    pub fn looks(&self) -> impl Iterator<Item = DrawnLook<'_>> + '_ {
        self.shown.iter().filter(|(_, s)| s.person).map(|(id, s)| DrawnLook { id: *id, look: &s.look, composed: s.composed, swapping: self.swaps.iter().any(|w| w.2 == *id) })
    }

    /// The bodies drawn now and their entities (those leaving sight are not among them). While a
    /// person is redrawn for a new look, the body still on screen (the old one) until the new
    /// one is fitted.
    pub fn drawn(&self) -> impl Iterator<Item = (u32, Entity)> + '_ {
        self.shown.iter().map(|(id, s)| (*id, self.swaps.iter().find(|w| w.2 == *id && w.1 == s.entity).map_or(s.entity, |w| w.0)))
    }
}

/// Regenerate the land from the `land` row once, then put the island in place.
#[allow(clippy::too_many_arguments)]
fn land(
    mut commands: Commands,
    net: NonSend<Net>,
    mut live: ResMut<Live>,
    island: Option<Res<Island>>,
    mut style: ResMut<crate::style::Style>,
    mut look: ResMut<crate::lookdev::Lookdev>,
    mut lights: Query<&mut DirectionalLight>,
    mut cams: Query<&mut DistanceFog, With<Camera3d>>,
    mut clear: ResMut<ClearColor>,
    mut roam: ResMut<Roam>,
    mut draw: ResMut<crate::world::Draw>,
) {
    if island.is_some() || net.mode != Mode::Land {
        return;
    }
    let Some(row) = net.land() else { return };
    let Some(slot) = live.building.clone() else {
        let slot: Arc<Mutex<Option<Result<Built, String>>>> = Arc::default();
        live.building = Some(slot.clone());
        info!("land: seed {} {} m, params {}; regenerating", row.seed, row.size, row.params);
        std::thread::spawn(move || {
            let r = regenerate(&row);
            *slot.lock().unwrap() = Some(r);
        });
        return;
    };
    let Some(result) = slot.lock().unwrap().take() else { return };
    live.building = None;
    let built = match result {
        Ok(b) => b,
        Err(e) => {
            error!("land: cannot regenerate the authority's land: {e}");
            net.errors.lock().unwrap().push(format!("land: {e}"));
            return;
        }
    };
    let ok = built.digests.iter().all(|(_, a, b)| a == b);
    live.digests_ok = Some(ok);
    let list = built.digests.iter().map(|(n, a, b)| format!("{n} {a:016x}{}", if a == b { String::new() } else { format!(" (authority {b:016x})") })).collect::<Vec<_>>().join(", ");
    if ok {
        info!("land: regenerated in {:.2} s; digests match: {list}", built.secs);
    } else {
        warn!("land: regenerated in {:.2} s; DIGESTS DIFFER, heights and layout may not match the authority (movement still follows its tiles): {list}", built.secs);
        net.errors.lock().unwrap().push("land digests differ from the authority's".into());
    }
    let defs = crate::envs::load_defs();
    // The mood of the environment made for this land (its `world` names the row's seed and
    // size), else the first world environment's.
    let mine = defs.iter().find(|d| d.world.as_ref().is_some_and(|w| w.seed == row.seed && w.size == row.size));
    let env = mine.or_else(|| defs.iter().find(|d| d.world.is_some()));
    if let Some(def) = env {
        crate::envs::apply_mood(&def.mood, &mut style, &mut look, &mut lights, &mut cams, &mut clear);
        // The camera's fog, and how far landmarks are drawn, follow this mood (`world::Draw`).
        draw.mood(&def.mood);
        info!("land: mood {} (fog {:.0}–{:.0} m)", def.id, def.mood.fog_start, def.mood.fog_end);
    }
    live.hosted = Some(built.hosted);
    let arrive = Vec2::new(row.arrive_x, row.arrive_y);
    roam.pos = arrive;
    // Its ground map is the environment made for this land's; the first world environment's
    // (the island's, which has none) never paints another land.
    let island = Island::hosted(built.land, &defs, mine, arrive, &built.params);
    commands.insert_resource(island);
}

fn regenerate(row: &LandInfo) -> Result<Built, String> {
    let t0 = std::time::Instant::now();
    let params: LandParams = serde_json::from_str(if row.params.trim().is_empty() { "{}" } else { &row.params }).map_err(|e| format!("land.params: {e}"))?;
    if !(256..=8192).contains(&row.size) {
        return Err(format!("land size {} m", row.size));
    }
    let land = living_rules::land::generate(row.seed, row.size, &params);
    let (hosted, _) = living_rules::host::hosted_map(&land, &params);
    let d = living_rules::host::digests(&land, &hosted);
    Ok(Built {
        land: Arc::new(land),
        hosted: Arc::new(hosted),
        digests: [("tiles", d.tiles, row.tiles_digest), ("heights", d.heights, row.heights_digest), ("layout", d.layout, row.layout_digest)],
        params,
        secs: t0.elapsed().as_secs_f32(),
    })
}

/// Buildings from the `lot` rows in the window, near enough to see, and the landmarks.
///
/// - **Ordinary lots** are drawn within [`LOT_FAR`] of me, fading out over the last few metres
///   (`envs::Reach`), and dropped past [`LOT_DROP`].
/// - **Landmarks** (`Lot::landmark` in the regenerated land: Cullet's Cone, Counting House, Heron,
///   Watchglass and Lintel) are drawn out to where the mood's fog is complete
///   (`world::Draw::landmark_reach`, 600 m on Cullet), so they can be seen across the town. Lots
///   never change and the land is the authority's (its digests are checked), so a landmark past
///   the `lot` window (±184 m, `net.rs`) is drawn from the land itself; ids are the land's lot
///   indices, as the authority writes them (`island::build_lots`).
fn lots(mut commands: Commands, net: NonSend<Net>, island: Option<Res<Island>>, assets: Res<AssetServer>, mut live: ResMut<Live>, roam: Res<Roam>, draw: Res<crate::world::Draw>) {
    let (Some(island), Some(conn)) = (island, net.conn.as_ref()) else { return };
    let here = roam.pos;
    let far = if crate::perf::has("nofar") { LOT_FAR } else { draw.landmark_reach().max(LOT_FAR) };
    let land = &island.land;
    let landmark = |id: u32| land.lots.get(id as usize).is_some_and(|l| l.landmark);
    let reach = |id: u32| if landmark(id) { far } else { LOT_FAR };
    let at = |id: u32| conn.db.lot().id().find(&id).map(|l| Vec2::new(l.x, l.y)).or_else(|| landmark(id).then(|| land.lots[id as usize].centre).map(|c| Vec2::new(c.0, c.1)));
    let gone: Vec<u32> = live.lots.keys().copied().filter(|id| at(*id).is_none_or(|p| p.distance(here) > reach(*id) + (LOT_DROP - LOT_FAR))).collect();
    for id in gone {
        for e in live.lots.remove(&id).unwrap_or_default() {
            commands.entity(e).despawn();
        }
    }
    let mut todo: Vec<(f32, LotRow)> = Vec::new();
    let fresh: Vec<Lot> = conn.db.lot().iter().filter(|l| !live.lots.contains_key(&l.id)).collect();
    for l in fresh {
        let d = Vec2::new(l.x, l.y).distance(here);
        if d >= reach(l.id) {
            continue;
        }
        let set = conn.db.settlement().id().find(&l.settlement);
        let site = set.as_ref().and_then(|s| crate::island::site_kind(&s.kind));
        let (Some(site), Some(kind)) = (site, living_rules::settle::LotKind::from_id(&l.kind)) else {
            live.lots.insert(l.id, Vec::new());
            continue;
        };
        let env = set.as_ref().map_or(site.env(), |s| living_rules::settle::env_of(&s.style));
        todo.push((d, LotRow { id: l.id, site, kind, at: Vec2::new(l.x, l.y), yaw: l.yaw, floor_m: l.floor_m, height_m: l.height_m, width_m: l.width_m, depth_m: l.depth_m, model: l.model.clone(), env }));
    }
    // Landmarks beyond the window, from the land.
    for (i, l) in land.lots.iter().enumerate().filter(|(_, l)| l.landmark) {
        let id = i as u32;
        let d = Vec2::new(l.centre.0, l.centre.1).distance(here);
        if d < far && !live.lots.contains_key(&id) && conn.db.lot().id().find(&id).is_none() {
            if let Some(row) = LotRow::of_land(land, id) {
                todo.push((d, row));
            }
        }
    }
    todo.sort_by(|a, b| a.0.total_cmp(&b.0));
    for (d, row) in todo.into_iter().take(LOTS_PER_FRAME) {
        let es = island.spawn_lot(&mut commands, &assets, &row);
        if let (Some(&root), false) = (es.first(), landmark(row.id)) {
            commands.entity(root).insert((crate::envs::Reach(LOT_FAR), crate::envs::Reach::fade_at(LOT_FAR, d)));
        }
        if landmark(row.id) && !es.is_empty() {
            debug!("lots: landmark {} ({}) drawn at {d:.0} m", row.id, row.kind.id());
        }
        live.lots.insert(row.id, es);
    }
}


/// The recipe a person is drawn from (docs/LOOK.md §5), mine as anyone's (my own row's look):
/// the line their projected look names in the look book, composed from shared files, at the
/// line's own height. Without one (no key, a key the book lacks, a file not on disk, no book, or
/// composing turned off) a VRoid recipe seeded by the land and their id, in the folk and dress of
/// the projection, as before looks; each such case is one warning line a session.
pub fn recipe_for(book: Option<&crate::characters::book::LookBook>, land_seed: u64, c: &SeenCharacter) -> crate::characters::Recipe {
    use crate::characters::book::{warn_once, Miss};
    let seen = crate::characters::seen::of(c);
    let drawn = match book {
        _ if !crate::characters::compose::enabled() => None,
        None => Some(Err(Miss::NoBook)),
        Some(b) => Some(b.recipe(&seen.look)),
    };
    // A world made before looks (no `look_book`) has no keys: its people fall back quietly (one
    // line at connect, `sight`).
    let quiet = crate::characters::book::world().is_none_or(|g| g.is_empty());
    match drawn {
        Some(Ok(r)) => r,
        Some(Err(m)) => {
            if !(quiet && matches!(m, Miss::NoKey | Miss::NoBook)) {
                warn_once(&m);
            }
            vroid_for(land_seed, c)
        }
        None => vroid_for(land_seed, c),
    }
}

/// Redraw a shown person for a new look where and as they are: a new body from the new recipe
/// with the old one's transform and motion, fading in once it is fitted (`fade.rs` holds a fade
/// until then). The old body stays drawn and moving with it until then (`Live::swaps`), and then
/// fades out, so the person never leaves the screen.
#[allow(clippy::too_many_arguments)]
fn swap_look(commands: &mut Commands, assets: &AssetServer, live: &mut Live, q: &mut Query<Drawn>, (id, mine): (u32, bool), c: &SeenCharacter, land_seed: u64, now: crate::characters::seen::Seen) {
    let Some(old) = live.shown.get(&id).map(|s| s.entity) else { return };
    let Ok((tf, _, _, _, motion, _)) = q.get(old) else { return };
    let (tf, motion) = (*tf, motion.clone());
    let mut recipe = recipe_for(crate::characters::book::book(), land_seed, c);
    if recipe.person.is_none() {
        recipe.height *= stage_scale(c.stage);
    }
    let new = crate::characters::spawn(commands, assets, &recipe, tf.translation, 0.0);
    commands.entity(new).insert((tf, motion, crate::fade::Fade::appearing()));
    if mine {
        commands.entity(new).insert((crate::gait::Feet, crate::gait::Logged(id)));
    } else if crate::gait::logged_other() == Some(id) {
        commands.entity(new).insert(crate::gait::Logged(id));
    }
    let s = live.shown.get_mut(&id).unwrap();
    info!("looks: #{id} redrawn for a new look ({} → {})", if s.look.is_empty() { "none" } else { &s.look }, if now.look.is_empty() { "none" } else { &now.look });
    (s.entity, s.look, s.composed) = (new, now.look, recipe.person.is_some());
    live.heights.insert(id, recipe.height);
    live.swaps.push((old, new, id));
}

/// A person's VRoid recipe: seeded by the land and their id, in the folk and dress of the
/// projection (drawn at their life stage's scale, [`stage_scale`]).
pub fn vroid_for(land_seed: u64, c: &SeenCharacter) -> crate::characters::Recipe {
    let seed = land_seed.wrapping_mul(0x9E37_79B9).wrapping_add(c.id as u64);
    match folk_of(c) {
        (folk, Some(style)) => crate::characters::Recipe::random_in(seed, folk, &style),
        (folk, None) => crate::characters::Recipe::random(seed, folk),
    }
}

/// Folk and dress style as anyone sees them: the authority's projection (`seen_characters`
/// `folk` and `style`, from the settlement the character lives in; no home position is sent).
fn folk_of(c: &SeenCharacter) -> (&'static str, Option<String>) {
    let folk = match c.folk.as_str() {
        "giants" => "giant",
        "small_folk" => "small",
        _ => "adult",
    };
    (folk, (!c.style.is_empty()).then(|| c.style.clone()))
}

/// Facing as a Bevy yaw for a character model (0 faces +Z) from a sim direction.
fn yaw_of(d: Vec2) -> f32 {
    d.x.atan2(d.y)
}

/// What `bodies` reads and writes of a drawn body.
type Drawn = (&'static mut Transform, Option<&'static Fitted>, Option<&'static mut Model>, Option<&'static crate::characters::Character>, &'static mut Motion, Option<&'static mut Visibility>);

/// Draw the window's bodies: spawn, place on the island's ground, face, and pick clips.
#[allow(clippy::too_many_arguments)]
fn bodies(
    mut commands: Commands,
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    island: Option<Res<Island>>,
    assets: Res<AssetServer>,
    mut meshes: ResMut<Assets<Mesh>>,
    palette: Res<crate::world::Palette>,
    style: Res<crate::style::Style>,
    mut input: ResMut<Input>,
    combat: Res<crate::combat::Combat>,
    town: Res<crate::town::Town>,
    rules: NonSend<crate::verbs::Rules>,
    mut live: ResMut<Live>,
    mut q: Query<Drawn>,
    (mut fades, anims): (Query<&mut crate::fade::Fade>, Query<&crate::anim::Anim>),
    (time, edge, lw): (Res<Time>, Option<Res<crate::sightedge::SightEdge>>, Res<crate::twist::LookWalk>),
) {
    let Some(island) = island else { return };
    let Some(conn) = net.conn.as_ref() else {
        // Offline: no body is drawn (`bodies::update` has cleared the tracks too).
        for (_, s) in live.shown.drain() {
            commands.entity(s.entity).despawn();
        }
        for (e, ..) in live.leaving.drain(..) {
            commands.entity(e).despawn();
        }
        for (old, ..) in live.swaps.drain(..) {
            commands.entity(old).despawn();
        }
        live.heights.clear();
        live.looks_checked = false;
        crate::characters::book::set_world(None);
        return;
    };
    // The world's look generation against the book's, once a connection: one line either way
    // when it is not the book's, and one when the world has no looks.
    if !live.looks_checked && conn.db.world().iter().next().is_some() {
        live.looks_checked = true;
        let generation = crate::characters::seen::world_generation(conn);
        crate::characters::book::set_world(Some(generation.clone()));
        if generation.is_empty() {
            info!("looks: this world was made before looks; its people are drawn as VRoid bases");
        } else if let Some(w) = crate::characters::seen::generation_warning(&generation, crate::characters::book::book()) {
            warn!("{w}");
        } else if crate::characters::book::book().is_none() {
            crate::characters::book::warn_once(&crate::characters::book::Miss::NoBook);
        }
    }
    let dt = time.delta_secs().max(1e-4);
    let me = net.my_id;
    // Walking or running clips: the laws' split, read again when the installed script changes.
    if live.walk_run.map(|w| w.0) != Some(rules.revision) {
        let split = rules.scripts.as_ref().and_then(law_split);
        info!("gait: walk/run split {split:?} m/s by the laws (script revision {})", rules.revision);
        live.walk_run = Some((rules.revision, split));
    }
    let split = live.walk_run.and_then(|w| w.1);
    // Bodies that left sight fade out where they were, then go.
    // A faint figure goes at once when its body is sent again, else fades out after a moment.
    live.leaving.retain_mut(|(e, t, id, ghost)| {
        *t += dt;
        if *ghost && scene.shown.contains_key(id) {
            commands.entity(*e).despawn();
            return false;
        }
        let hold = if *ghost { crate::sightedge::GHOST_S } else { 0.0 };
        if *ghost && *t >= hold {
            if let Ok(mut f) = fades.get_mut(*e) {
                f.target = 1.0;
            }
        }
        let keep = *t < hold + crate::fade::OUT_S + 0.05;
        if !keep {
            commands.entity(*e).despawn();
        }
        keep
    });
    // People redrawn for a new look: the old body moves with the new until the new is fitted,
    // then fades out as the new fades in (a crossfade in place, never a gap).
    for (old, new, id) in std::mem::take(&mut live.swaps) {
        let current = live.shown.get(&id).is_some_and(|s| s.entity == new);
        if !current || q.get(new).is_ok_and(|d| d.1.is_some()) {
            match fades.get_mut(old) {
                Ok(mut f) => {
                    f.target = 1.0;
                    live.leaving.push((old, 0.0, id, false));
                }
                Err(_) => commands.entity(old).despawn(),
            }
            continue;
        }
        if let Ok([from, mut to]) = q.get_many_mut([new, old]) {
            *to.0 = *from.0;
            *to.4 = from.4.clone();
        }
        live.swaps.push((old, new, id));
    }
    // Who is speaking: lines I heard (the authority decides earshot), and my own last line.
    let mut talking: HashSet<u32> = me
        .map(|id| conn.db.my_experience().iter().filter(|e| e.observer == id && e.kind == "speech" && scene.now_ms - (e.at_ms as f64) < TALKING_S * 1000.0).map(|e| e.subject).collect())
        .unwrap_or_default();
    if let (Some(id), Some((t, _))) = (me, input.said.last()) {
        if scene.now_ms - (*t as f64) < TALKING_S * 1000.0 {
            talking.insert(id);
        }
    }
    let gone: Vec<u32> = live.shown.keys().copied().filter(|id| !scene.shown.contains_key(id)).collect();
    for id in gone {
        // Someone I saw die stays where they fell for a while, playing their death. The body row
        // goes in the same update as the death's `my_combat` row, which `combat::ingest` has
        // read this frame (Mirror) and `combat::actions` turned into the death clip (Present).
        if let Some(a) = combat.deaths.contains_key(&id).then(|| combat.actions.get(&id).copied()).flatten() {
            if let Some(s) = live.shown.get(&id) {
                if let Ok((_, _, _, _, mut motion, _)) = q.get_mut(s.entity) {
                    motion.action = Some(a);
                    motion.speed = 0.0;
                    motion.now_ms = scene.now_ms;
                }
            }
            continue;
        }
        // Out of sight (the authority no longer sends them): fade out rather than vanish.
        if let Some(s) = live.shown.remove(&id) {
            match fades.get_mut(s.entity) {
                Ok(mut f) => {
                    let ghost = edge.as_deref().is_some_and(|e| e.ghosts()) && f.target < 1.0;
                    f.target = if ghost { crate::sightedge::GHOST_LEVEL } else { 1.0 };
                    if let Ok((_, _, _, _, mut motion, _)) = q.get_mut(s.entity) {
                        motion.speed = 0.0;
                    }
                    live.leaving.push((s.entity, 0.0, id, ghost));
                }
                Err(_) => commands.entity(s.entity).despawn(),
            }
        }
        live.heights.remove(&id);
    }
    let mut my_face = None;
    for (&id, &(p, heading)) in &scene.shown {
        let ground = island.height(p.x, p.y);
        let at = Vec3::new(p.x, ground, p.y);
        let mine = Some(id) == me;
        // My character turns toward where I look (shown locally; the authority has no look): always
        // facing the cursor, or facing where I walk and only while aiming (`controls::Control`).
        let look = input.look.filter(|_| mine && input.faces_cursor(combat.aims)).filter(|l| l.length_squared() > 1e-4).map(|l| l.y.atan2(l.x));
        // During a move a body faces where the move goes; a gesture or settling down plays when
        // no move does.
        let show = town.shows.get(&id).copied().unwrap_or_default();
        let action = combat.actions.get(&id).copied().or(show.once);
        // A jump's aim is only the way it hops (the authority's dash direction: the travel), and
        // it is drawn over whatever the body plays (`jump.rs`), so it keeps the body's facing:
        // taken as a facing, it turned a body walking backwards or sideways to face its travel
        // for the hop and back after (play-test 2). A dodge's roll is a forward take, so it
        // still faces its dash.
        let aimed = action.filter(|a| a.clip != crate::jump::CLIP).and_then(|a| a.face).filter(|f| f.length_squared() > 1e-4).map(|f| f.y.atan2(f.x));
        // Standing still, the body's own segment: its heading, turning on the spot by `turn` over
        // `turn_s` (the display clock may trail the row's start: then the turn has not begun).
        let row = crate::net::find_motion(conn, id);
        let standing = row.as_ref().filter(|b| b.vx == 0.0 && b.vy == 0.0).map(|b| {
            let into = ((scene.now_ms - b.t_ms as f64) / 1000.0).clamp(0.0, b.turn_s.max(0.0) as f64) as f32;
            b.heading + if b.turn_s > 0.0 { b.turn * into } else { 0.0 }
        });
        let slow = live.shown.get(&id).is_none_or(|s| s.speed < MOVING);
        let busy = show.face.filter(|_| slow).filter(|f| f.length_squared() > 1e-4).map(|f| f.y.atan2(f.x));
        let h = aimed.or(look).or(busy).or(standing.filter(|_| slow)).or(heading);
        if !live.shown.contains_key(&id) {
            let Some(body) = crate::net::find_body(conn, id) else { continue };
            let character = conn.db.seen_characters().id().find(&id);
            // Wait for a person's character row (folk, stage) before drawing them.
            if body.kind == "person" && character.is_none() {
                continue;
            }
            let h = h.unwrap_or(body.heading);
            let size = character.as_ref().map_or(1.0, |c| stage_scale(c.stage));
            let mut composed = false;
            let (entity, height, person, beast) = if body.kind == "person" {
                let c = character.as_ref().unwrap();
                let mut recipe = recipe_for(crate::characters::book::book(), island.land.seed, c);
                // A line carries its own height; a VRoid recipe is scaled by life stage.
                if recipe.person.is_none() {
                    recipe.height *= stage_scale(c.stage);
                }
                composed = recipe.person.is_some();
                let e = crate::characters::spawn(&mut commands, &assets, &recipe, at, yaw_of(Vec2::new(h.cos(), h.sin())));
                (e, recipe.height, true, false)
            } else if let Some(e) = crate::bodies::spawn_beast(&mut commands, &assets, &body.kind, at, yaw_of(Vec2::new(h.cos(), h.sin())), size) {
                (e, crate::bodies::beast_height(&body.kind) * size, false, true)
            } else {
                let tf = Transform::from_translation(at).with_rotation(Quat::from_rotation_y(-h));
                let e = crate::bodies::spawn(&mut commands, &mut meshes, &palette, &style, &body.kind, id, false, tf, p);
                (e, crate::bodies::beast_height(&body.kind).min(1.4), false, false)
            };
            let startles = beast && crate::bodies::beast_file(&body.kind).is_some_and(|f| crate::gait::of(f).info(STARTLE.0).is_some());
            // Coming into sight: fade in once the model can be seen (`fade.rs`).
            commands.entity(entity).insert((Motion::default(), crate::fade::Fade::appearing()));
            if mine {
                commands.entity(entity).insert((crate::gait::Feet, crate::gait::Logged(id)));
            } else if crate::gait::logged_other() == Some(id) {
                commands.entity(entity).insert(crate::gait::Logged(id));
            }
            let look = character.as_ref().filter(|_| person).map(crate::characters::seen::of).unwrap_or_default();
            live.shown.insert(id, Shown { entity, last: p, speed: 0.0, person, beast, yaw: h, drawn: p, sitting: false, rising: None, startles, still: 0.0, startle: None, tilt: Quat::IDENTITY, kind: body.kind.clone(), face: h, back: false, turning: false, turn: None, jump: None, jump_key: -1.0, jump_took: false, walked: false, along: false, stop: None, stop_at: p, rest_at: None, calm_speed: 0.0, run_w: if row.as_ref().is_some_and(|r| r.running) { 1.0 } else { 0.0 }, look: look.look, composed });
            live.heights.insert(id, height);
            continue;
        }
        // A new look key for someone drawn (a band change, a `relook`): redrawn in place.
        if live.shown.get(&id).is_some_and(|s| s.person) {
            if let Some(c) = conn.db.seen_characters().id().find(&id) {
                let now = crate::characters::seen::of(&c);
                if live.shown.get(&id).is_some_and(|s| s.look != now.look) {
                    swap_look(&mut commands, &assets, &mut live, &mut q, (id, mine), &c, island.land.seed, now);
                }
            }
        }
        let s = live.shown.get_mut(&id).unwrap();
        let family = family(row.as_ref().map(|r| r.running), &mut s.run_w, dt, split);
        // A person's clip file: its directional, turn, start and jump takes (`gait.rs`,
        // `takes.rs`), and its pace and stride as drawn last frame.
        let (gaits, pace, stride) = match q.get(s.entity) {
            Ok((_, _, Some(m), ch, motion, _)) if s.person && crate::takes::enabled() => (Some(crate::gait::of(&crate::anim::clip_file(&m.file))), motion.pace, ch.map_or(1.0, |c| c.stride)),
            _ => (None, 1.0, 1.0),
        };
        // A jump plays the take for its way, timed to the rules' hop, chosen once per jump from
        // how the body moved before it and where the hop goes from its legs (`takes::jump_for`);
        // without one, `jump.rs` draws it. The take plays on to its own end.
        if let (Some(a), Some(g)) = (action.filter(|a| a.clip == crate::jump::CLIP), gaits.as_ref()) {
            if s.jump_key != a.start_ms {
                s.jump_key = a.start_ms;
                let rel = a.face.filter(|f| f.length_squared() > 1e-4).map_or(0.0, |f| living_rules::steer::wrap(f.y.atan2(f.x) - s.yaw));
                let moving = s.calm_speed > MOVING;
                s.jump = crate::takes::jump_for(g, moving, rel).map(|(clip, rate, from, cut)| crate::takes::Playing { clip, start_ms: a.start_ms, rate, from, cut: Some(cut), yaw0: s.yaw, gait: moving });
                s.jump_took = s.jump.is_some();
            }
        }
        if action.is_some_and(|a| a.clip != crate::jump::CLIP) {
            s.jump = None;
        }
        // Asked for until its fade out begins (`cut`), so the gait comes back under it as it fades;
        // the rules' jump it stands for draws nothing after (no procedural jump over the landing).
        s.jump = s.jump.filter(|j| j.cut.is_some_and(|c| j.t(scene.now_ms) < c) && combat.deaths.get(&id).is_none());
        let action = match (s.jump, action) {
            (Some(j), None) => Some(j.action()),
            (Some(j), Some(a)) if a.clip == crate::jump::CLIP => Some(crate::combat::Action { face: a.face, ..j.action() }),
            (None, Some(a)) if a.clip == crate::jump::CLIP && s.jump_key == a.start_ms && s.jump_took => None,
            _ => action,
        };
        if action.is_none() {
            s.calm_speed = s.speed;
        }
        // Getting up from the ground before walking off: hold the seat while the clip plays.
        let sitting = show.idle == Some("sit_ground") && !show.hidden;
        if s.sitting && !sitting && s.rising.is_none() && action.is_none() && !mine {
            s.rising = Some((scene.now_ms, s.drawn));
        }
        s.sitting = sitting;
        // Taking flight from standing: startle where it stood first.
        let fast = row.as_ref().is_some_and(|b| b.vx.hypot(b.vy) >= STARTLE_V);
        if s.startles && !mine && s.still >= STILL_S && fast && s.startle.is_none() && action.is_none() {
            s.startle = Some((scene.now_ms, s.drawn));
        }
        s.still = if s.speed < MOVING && !fast { s.still + dt } else { 0.0 };
        s.startle = s.startle.filter(|(t, _)| scene.now_ms - t < STARTLE.1);
        let auth_v = (p - s.last).length() / dt;
        s.last = p;
        // Stopping from a walk along the legs: the stop take plays and the body is drawn along its
        // track from where it was, then stays there until it moves again (`takes::stop_for`).
        let seg = scene.speeds.get(&id).copied().unwrap_or(0.0);
        if let (Some(g), Ok(an), true) = (gaits.as_ref(), anims.get(s.entity), s.stop.is_none() && s.walked && s.along && seg <= 0.0 && action.is_none() && s.speed > MOVING) {
            if let Some((clip, rate, from)) = crate::takes::stop_for(g, an.clip_phase(), s.speed / pace.max(0.5) / stride.max(0.05), family, s.speed) {
                s.stop = Some(crate::takes::Playing { clip, start_ms: scene.now_ms, rate, from, cut: None, yaw0: s.yaw, gait: false });
                s.stop_at = s.drawn;
            }
        }
        let stop_len = s.stop.and_then(|st| gaits.as_ref().and_then(|g| g.info(st.clip)).map(|i| i.seconds)).unwrap_or(0.0);
        let stop_at = s.stop.and_then(|st| {
            let info = gaits.as_ref()?.info(st.clip)?;
            let t = st.t(scene.now_ms).min(stop_len);
            let o = info.path_at(t) - info.path_at(st.from);
            let (fwd, left) = (Vec2::new(st.yaw0.cos(), st.yaw0.sin()), Vec2::new(st.yaw0.sin(), -st.yaw0.cos()));
            Some(s.stop_at + fwd * o.y + left * o.x)
        });
        if let Some(st) = s.stop {
            if seg > 0.0 || action.is_some() {
                s.stop = None;
            } else if st.t(scene.now_ms) >= stop_len {
                s.stop = None;
                s.rest_at = stop_at;
            }
        }
        if seg > 0.0 || action.is_some() {
            s.rest_at = None;
        }
        let stop_hold = if s.stop.is_some() { stop_at } else { s.rest_at };
        let held = s.rising.filter(|(t, _)| scene.now_ms - t < STAND_UP.2).map(|(_, at)| at).or(s.startle.map(|(_, at)| at)).or(stop_hold);
        let before = s.drawn;
        match held {
            Some(seat) => s.drawn = seat,
            None => {
                s.rising = None;
                let gap = p - s.drawn;
                let step = (auth_v.min(20.0) + CATCH_UP) * dt;
                s.drawn = if gap.length() <= step || gap.length() > SNAP_M { p } else { s.drawn + gap / gap.length() * step };
            }
        }
        // The gait takes up the displayed segment's speed at once when it rises: the authority
        // starts a body at full speed, and an eased speed slid the feet as it set off. A slower
        // segment is taken up within about 0.15 s, and a standing one at once: the gait then
        // finishes its step at its own rate (`anim.rs`, settling at double support) instead of
        // stepping on the spot for most of a second while its speed eased down (play-test 1:
        // 0.8 s of gait after the body stood). A body held or catching up (getting up, a
        // startle) is drawn off its segment: its gait follows the drawn motion.
        let on_segment = held.is_none() && s.drawn == p;
        let v = (s.drawn - before).length() / dt;
        let p = s.drawn;
        let ground = island.height(p.x, p.y);
        let v = if v.is_finite() && v < 20.0 { v } else { 0.0 };
        match scene.speeds.get(&id) {
            Some(&seg) if on_segment && (seg >= s.speed || seg <= 0.0) => s.speed = seg.max(0.0),
            Some(&seg) if on_segment => s.speed += (seg - s.speed) * (1.0 - (-dt * SLOWING).exp()),
            _ => s.speed += (v - s.speed) * (1.0 - (-dt * 8.0).exp()),
        }
        // A person walking one way while looking another (my cursor, a move's aim): the head, then
        // the chest take the look, and past their limits the legs come round on the look-walk's
        // curve (`twist.rs`). The gait is the file's directional takes for the travel from where
        // the legs face now, so a sudden turn of the travel sidesteps until they have come round.
        // Else the authority's facing (look-2: a held look turns head and chest, never the walk),
        // for every body: mine before my own look reaches the row, and everyone else's. My own
        // look leads it, drawn ahead of the row (`docs/PERCEPTION.md`, "Drawing it").
        let faced = row.as_ref().and_then(|m| authority_facing(m, if mine { scene.mine_ms } else { scene.now_ms }));
        let look_at = aimed.or(look).or(faced);
        let walking = s.person && s.speed > MOVING;
        let takes = |t: f32, legs: f32| gaits.as_ref().is_some_and(|g| g.blend_toward(s.speed / pace.max(0.5), stride, family, living_rules::steer::wrap(t - legs), |_| 1.0).is_some());
        // The travel from the legs for the directional takes, when they play.
        let mut toward_t = None;
        // A turn take playing: the legs follow its curve until it ends; walking or a move breaks
        // it off where it is.
        let mut turn_action = None;
        if let (Some(tp), Some(g)) = (s.turn, gaits.as_ref()) {
            if walking || action.is_some() {
                s.turn = None;
            } else {
                let (by, done) = crate::takes::turned(g, &tp, scene.now_ms);
                // Along the take's curve, but never faster than [`TURN_MAX`]: a jump of the display
                // clock ended a take in one frame and turned the legs 77° at once.
                let d = living_rules::steer::wrap(tp.yaw0 + by - s.yaw);
                s.yaw = living_rules::steer::wrap(s.yaw + d.clamp(-TURN_MAX * dt, TURN_MAX * dt));
                let len = g.info(tp.clip).map_or(0.0, |i| i.seconds);
                if done {
                    s.turn = None;
                } else if tp.t(scene.now_ms) < len - crate::anim::FADE_OUT * tp.rate {
                    turn_action = Some(tp.action());
                }
            }
        }
        // Standing, legs that would swivel past `takes::TURN_ON` turn by a take instead: toward the
        // look, a standing body's own heading (where its segment's turn ends) or its activity.
        let standing_to = row.as_ref().filter(|b| b.vx == 0.0 && b.vy == 0.0).map(|b| b.heading + if b.turn_s > 0.0 { b.turn } else { 0.0 });
        let turn_to = look_at.or(busy).or(standing_to.filter(|_| slow));
        if let (Some(g), Some(to), None, false, None, None) = (gaits.as_ref(), turn_to, s.turn, walking, action, s.stop) {
            if s.speed < crate::anim::STEP_OFF {
                if let Some(clip) = crate::takes::turn_for(g, living_rules::steer::wrap(to - s.yaw)) {
                    let tp = crate::takes::Playing { clip, start_ms: scene.now_ms, rate: crate::takes::TURN_RATE, from: 0.0, cut: None, yaw0: s.yaw, gait: false };
                    s.turn = Some(tp);
                    s.turning = false;
                    turn_action = Some(tp.action());
                }
            }
        }
        let mut back = false;
        // Setting off the authority moves the body before the drawn speed is up to a walk: the
        // legs already follow the walk's curve then (as standing they turned at the yaw rate,
        // 35° a frame).
        let stepping = walking || (s.person && s.turn.is_none() && scene.speeds.get(&id).is_some_and(|v| *v > MOVING));
        let legs = match (stepping, look_at, heading) {
            _ if s.turn.is_some() => None,
            // Walking and looking: the legs ease toward the travel turned by what the head and
            // chest leave (or its reverse, looking back), and the takes for the travel from them
            // play; where the file has none there, the forward gaits along the travel (reversed
            // backwards), the legs taken round at the old rate.
            (true, Some(l), Some(t)) => {
                let (goal, b) = lw.legs_goal(t, l, s.back, |legs| takes(t, legs));
                back = b;
                // Always eased (a snap at the old rate turned the legs 25–39° a frame setting off
                // from a standing turn); without a take there, the forward gaits play meanwhile.
                s.yaw = lw.ease(s.yaw, goal, dt);
                if takes(t, s.yaw) {
                    toward_t = Some(t);
                }
                None
            }
            // Standing and looking, with no move under way (a move turns the whole body to its
            // aim, as a dodge's roll must): the legs stay until the look is well away, then turn.
            // While a stop take plays the legs hold (the upper body takes the look): no turn take
            // can start then, and they swivelled at the yaw rate, 40° a frame.
            (false, Some(_), _) if s.person && action.is_none() && s.stop.is_some() => Some(s.yaw),
            (false, Some(l), _) if s.person && action.is_none() => {
                let off = living_rules::steer::wrap(l - s.yaw).abs();
                s.turning = if s.turning { off > STAND_TURN_OFF } else { off > STAND_TURN_ON.min(lw.upper()) };
                Some(if s.turning { l } else { s.yaw })
            }
            _ => h,
        };
        if !(s.person && !walking && look_at.is_some() && action.is_none()) {
            s.turning = false;
        }
        s.back = back;
        s.walked = walking;
        s.along = walking && !back && heading.is_some_and(|t| living_rules::steer::wrap(t - s.yaw).abs() <= ALONG);
        let k = 1.0 - (-dt * YAW_RATE).exp();
        if let Some(y) = legs {
            s.yaw = living_rules::steer::wrap(s.yaw + living_rules::steer::wrap(y - s.yaw) * k);
        }
        if let Some(f) = look_at.filter(|_| walking || s.person).or(legs) {
            s.face = living_rules::steer::wrap(s.face + living_rules::steer::wrap(f - s.face) * k);
        }
        // Head first, then the chest (`twist::LookWalk::split`); the eyes take a little of what
        // they leave of the look itself.
        let (twist, neck, eyes) = if s.person {
            let (t, n, _) = lw.split(living_rules::steer::wrap(s.face - s.yaw));
            let most = lw.eyes_deg.to_radians();
            let e = look_at.map_or(0.0, |l| living_rules::steer::wrap(l - s.yaw - t).clamp(-most, most));
            (t, n, e)
        } else {
            (0.0, 0.0, 0.0)
        };
        // The travel from where the legs are drawn facing now (the game's sense: + to the right).
        let travel = toward_t.map_or(0.0, |t| living_rules::steer::wrap(t - s.yaw));
        if mine {
            my_face = Some(Vec2::new(s.face.cos(), s.face.sin()));
        }
        // Walking backwards on the forward gaits where the file has no take for it.
        let reverse = toward_t.is_none() && stepping && heading.is_some_and(|t| living_rules::steer::wrap(t - s.yaw).abs() > PI / 2.0);
        let (speed, person, beast, yaw) = (s.speed, s.person, s.beast, s.yaw);
        let rising = s.rising.filter(|(t, _)| scene.now_ms - t < STAND_UP.2).map(|(t, _)| t);
        // A stop take is asked for until its fade out, when standing takes over (`anim.rs`).
        let stop_action = s.stop.filter(|st| st.t(scene.now_ms) < stop_len - crate::anim::FADE_OUT * st.rate).map(|st| st.action());
        let startle = s.startle.map(|(t, _)| crate::combat::Action { clip: STARTLE.0, rate: 1.0, start_ms: t, hold: None, face: None, ..Default::default() });
        let dir = Vec2::new(yaw.cos(), yaw.sin());
        // A rigged creature is drawn at its file's size times its life stage's (it grows up), its
        // body lying on the ground under its paws.
        let size = if beast { conn.db.seen_characters().id().find(&id).map_or(1.0, |c| stage_scale(c.stage)) } else { 1.0 };
        let (ground, tilt) = if beast {
            let (want, y) = crate::bodies::lie_on(&s.kind, |x, z| island.height(x, z), p, dir, size);
            s.tilt = s.tilt.slerp(want, 1.0 - (-dt * crate::bodies::TILT_RATE).exp());
            (y, s.tilt)
        } else {
            (ground, Quat::IDENTITY)
        };
        let Ok((mut tf, fitted, mut model, ch, mut motion, vis)) = q.get_mut(s.entity) else { continue };
        tf.translation.x = p.x;
        tf.translation.z = p.y;
        tf.rotation = if person {
            Quat::from_rotation_y(yaw_of(dir) + PI)
        } else if beast {
            tilt * Quat::from_rotation_y(yaw_of(dir))
        } else {
            Quat::from_rotation_y(-yaw)
        };
        if beast {
            tf.scale = Vec3::splat(size);
        }
        // Indoors (asleep, or resting at the door): faded out, then not drawn. Never my own
        // character.
        let _ = vis;
        if let Ok(mut f) = fades.get_mut(s.entity) {
            let to = if show.hidden && !mine { 1.0 } else { 0.0 };
            if f.target != to {
                f.target = to;
            }
        }
        match (fitted, model.as_mut()) {
            // `fit` measured a creature at its file's size (height 0 keeps it).
            (Some(fit), _) if beast => tf.translation.y = ground + fit.y_off * size,
            (Some(fit), _) => tf.translation.y = ground + fit.y_off,
            (None, Some(m)) => m.ground_y = ground,
            (None, None) => tf.translation.y = ground,
        }
        // What the body does; `anim.rs` blends its gaits from the displayed speed (feet keep
        // still), its standing loop and any one-shot over them.
        motion.speed = speed;
        motion.stride = ch.map_or(size, |c| c.stride);
        motion.stand = if talking.contains(&id) { "talk" } else { show.idle.unwrap_or("idle") };
        motion.action = action.or(rising.map(|t| crate::combat::Action { clip: STAND_UP.0, rate: STAND_UP.1, start_ms: t, hold: None, face: None, ..Default::default() })).or(startle).or(turn_action).or(stop_action);
        motion.now_ms = scene.now_ms;
        motion.reverse = reverse;
        motion.twist = twist;
        motion.neck = neck;
        motion.eyes = eyes;
        motion.aim = person && look_at.is_some();
        motion.travel = travel;
        motion.family = family;
        motion.freeze = motion.action.is_some_and(|a| a.clip == crate::jump::CLIP) && crate::jump::airborne(&motion) > 0.05;
        // On a road the rules speed a body up (`road_speed`, by the share of road ahead): the
        // gait is chosen at its own pace, so walking onto a road doesn't break into a run.
        motion.pace = match (person, heading) {
            (true, Some(t)) if speed > MOVING => {
                let road = rules.scripts.as_ref().map_or(living_rules::steer::Tuning::default().road_speed, |sc| sc.laws().road_speed);
                1.0 + (road - 1.0) * living_rules::steer::road_share(&island.land.map, (p.x, p.y), t)
            }
            _ => 1.0,
        };
    }
    input.face = my_face;
}

/// Follow my displayed body: the camera's target, the island's streaming centre and the
/// atmosphere's regions. Before I have a body, the island streams round the arrival point.
fn me(net: NonSend<Net>, scene: NonSend<Scene>, island: Option<Res<Island>>, live: Res<Live>, mut target: ResMut<Target>, mut roam: ResMut<Roam>) {
    let Some(island) = island else { return };
    match net.my_id.and_then(|id| scene.shown.get(&id).map(|s| (id, s.0))) {
        Some((id, p)) => {
            let speed = live.shown.get(&id).map_or(0.0, |s| s.speed);
            if p.distance(roam.pos) > 1e-3 {
                roam.facing = (p - roam.pos).normalize_or(roam.facing);
            }
            roam.pos = p;
            roam.moving = speed > MOVING;
            // The authority's word, as for the clips; the laws' split without a row.
            roam.running = match net.conn.as_ref().and_then(|c| crate::net::find_motion(c, id)) {
                Some(m) => m.running,
                None => live.walk_run.and_then(|w| w.1).is_some_and(|v| speed > v),
            };
            roam.speed = speed;
            target.0 = Some(Vec3::new(p.x, island.height(p.x, p.y), p.y));
        }
        None => target.0 = None,
    }
}

/// Where the cursor meets the island's ground (the camera's own ray uses the tile ground). The
/// eye's height over the island's hills is the camera's own (`camera::follow`).
pub(crate) fn ground_cursor(island: Option<Res<Island>>, mut cam: ResMut<Cam>, cams: Query<(&Camera, &GlobalTransform), With<Camera3d>>, pointer: Res<crate::pointer::Pointer>) {
    let Some(island) = island else { return };
    let Ok((camera, gtf)) = cams.single() else { return };
    let Some(c) = pointer.pos else { return };
    let Ok(ray) = camera.viewport_to_world(gtf, c) else { return };
    let (o, d) = (ray.origin, *ray.direction);
    let below = |p: Vec3| p.y <= island.height(p.x, p.z);
    let mut prev = o;
    let mut t = 0.0;
    cam.cursor_ground = None;
    while t < 400.0 {
        t += 1.0;
        let p = o + d * t;
        if below(p) {
            let (mut lo, mut hi) = (prev, p);
            for _ in 0..12 {
                let mid = (lo + hi) * 0.5;
                if below(mid) {
                    hi = mid;
                } else {
                    lo = mid;
                }
            }
            cam.cursor_ground = Some(hi);
            return;
        }
        prev = p;
    }
}

/// Every 10 s: what the client holds from the authority, for measurements.
fn report(net: NonSend<Net>, live: Res<Live>, time: Res<Time>, mut next: Local<f32>) {
    let t = time.elapsed_secs();
    if t < *next {
        return;
    }
    *next = t + 10.0;
    let Some(conn) = net.conn.as_ref() else { return };
    // Tiles in the terrain window that differ from the hosted land: roads, walls, clearings and
    // bridges built since world creation (not drawn yet).
    let edits: usize = live.hosted.as_ref().map_or(0, |m| {
        conn.db
            .terrain_chunk()
            .iter()
            .map(|c| {
                let (cx, cy) = chunk_xy(c.id);
                c.tiles
                    .iter()
                    .enumerate()
                    .filter(|(k, t)| {
                        let (x, y) = (cx * CHUNK + *k as u32 % CHUNK, cy * CHUNK + *k as u32 / CHUNK);
                        x < m.w && y < m.h && m.tiles[(y * m.w + x) as usize] != **t
                    })
                    .count()
            })
            .sum()
    });
    info!(
        "live: cache body {} character {} doing {} act_card {} weather {} lot {} terrain_chunk {} ({} tiles edited) settlement {} experience {}; drawn {} characters, {} lots; window moves {}; digests {}",
        conn.db.my_body().count() + conn.db.seen_bodies().count(),
        conn.db.seen_characters().count(),
        conn.db.my_doing().count() + conn.db.seen_doing().count(),
        conn.db.act_card().count(),
        conn.db.weather().iter().next().map_or("none", |w| if w.raining { "rain" } else { "dry" }),
        conn.db.lot().count(),
        conn.db.terrain_chunk().count(),
        edits,
        conn.db.settlement().count(),
        conn.db.my_experience().count(),
        live.shown.len(),
        live.lots.values().filter(|e| !e.is_empty()).count(),
        net.window_moves,
        match live.digests_ok {
            Some(true) => "match",
            Some(false) => "DIFFER",
            None => "pending",
        }
    );
}

/// A headless script of player actions and photographs (`LIVING_GAME_LIVE=<dir>`), through the
/// same paths as the keys and the UI. `LIVING_GAME_LIVE_PLAN` is `;`-separated steps:
/// - `ready`: until the island is drawn, I have a body, the buildings round me are in and the
///   first load's cover has lifted (`loading.rs`);
/// - `wait:S`; `shot:NAME` (`<dir>/NAME.png`);
/// - `walk:DEG:S[:run]`: hold a direction (0 = north, 90 = east) through `human_move`;
///   `hold:DEG[:run]` holds it and goes straight on to the next step (a skill or a gesture
///   while walking), until `stop`;
/// - `look:DEG`: face that way (0 = north, 90 = east) as the cursor would make me, until `look:`
///   (a headless run has no cursor); `lookwalk:PRESET[,key=value…]` sets how the body looks aside
///   while walking (`twist::LookWalk::parse`); `cursor:X,Y` puts the game's cursor there (fractions of the
///   picture, or `@NAME`, a tagged node; `cursor:` takes it away), `pointat:X,Y[:H]` keeps it on a point
///   of the world (sim m, H m above the ground), `nudge:DX,DY` moves it by logical px
///   (an open wheel takes it as motion), `wheel:DIR` points the open wheel as the arrows do, and `pan:PX`, `drag:PX` and `pinch:F` turn the view or
///   zoom through the pointer's paths (`pointer.rs`: a two-finger pan, a left drag, a pinch);
///   `frame:0` stops the view framing fights, talks and greetings (`frame:1` again);
/// - `goto:X,Y`: click-to-move (`human_act` with `goto`); `yaw:DEG`: turn the view;
///   `view:PITCH:DISTANCE[:FOV]`: the game camera's pitch (deg), distance (m) and field of view
///   (photographing small things up close);
/// - `say:TEXT`: proximity chat (`human_say`);
/// - `sightlook:NAME`: how "not seen now" is drawn, among the looks under trial
///   (`sightedge::Look`; `LIVING_SIGHT_LOOK` sets the first);
/// - `skill:NAME[:AIM]`: use a skill-bar skill through `use_skill` (`combat.rs`); AIM is
///   `nearest`, a creature kind (`wolf`) or `DX,DY` metres from me; `release:NAME` lets go of
///   a held one; `aim:NAME[:AIM]` shows its indicator (until `aim:`);
/// - `gesture:wave|nod|appraise[:ID]`: greet, or look someone over, through `human_act` as the
///   G, B and V keys do (`town.rs`), at character ID, else whom the keys would pick;
/// - verbs (`verbs.rs`): `act:SKILL[:ITEM][@AIM]` sends an act as a list pick does (AIM is
///   `nearest:KIND` for the nearest thing or creature of that kind, `id:N`, `self`, or nothing for
///   what F aims at now; the log says whether the rules offered it, and it is sent either way);
///   `menu:f[@AIM]|c|close|N` opens F's list (on AIM) or my own, closes it, or picks row N;
///   `words:TEXT` enters words in the text box an act opened (write, found); `panel:inventory|
///   know-how[:SKILL]|none` shows a panel (know-how with SKILL selected);
/// - `sync:NAME`: until `<dir>/NAME.go` exists (an outside driver sets the scene: the hour, the
///   weather, where I stand), then delete it; a number in the file turns the view to that yaw;
/// - `key:NAME:down|up|tap` and `mouse:left|right|middle:down|up`: a key or button as the
///   window would report it (`KeyE`, `KeyQ`, `Enter`, `ShiftLeft`, …), read by every input
///   system this frame; `chat:open|close` opens or closes the text box, as Enter and Esc do;
///   `tap` is a left tap as the pointer reports one (a strike, or talk to a peaceful person);
///   `click:X,Y` clicks there (fractions of the picture; `@NAME` is a tagged node of the game
///   UI, `ui/hit.rs` `Tag`), `slide:A>B[:SECS]` holds the click at A and slides to B (a
///   title-bar drag, an item onto someone), `scroll:PX` swipes
///   two fingers over a window, `point:ID[:H]` puts the cursor on someone (hovering them; H m above their feet, default 0.3, e.g. 1.3 for the chest),
///   `dodge:W|A|S|D` double-taps a direction, `weapon:toggle|draw|sheathe` is X, and `dump:NAME`
///   writes the game UI's state to `<dir>/NAME.json` (`ui::dump`);
///   `type:TEXT` puts words in it, `tab` speaks to the next person within earshot, and `enter`
///   says the words to whom it addresses (`talk.rs`), as Tab and Enter do;
/// - `dead`: until the death screen shows; `rejoin`: its "arrive again" button; `joined`:
///   until a new character is mine;
/// - `quit`.
/// A key of the `key:` step: any the bindings know (`keys.rs`), by its `KeyCode` name.
fn key_code(name: &str) -> Option<KeyCode> {
    if let Some(k) = crate::keys::key_named(name) {
        return Some(k);
    }
    Some(match name {
        "KeyQ" => KeyCode::KeyQ,
        "KeyE" => KeyCode::KeyE,
        "KeyR" => KeyCode::KeyR,
        "KeyF" => KeyCode::KeyF,
        "KeyG" => KeyCode::KeyG,
        "KeyB" => KeyCode::KeyB,
        "KeyV" => KeyCode::KeyV,
        "KeyW" => KeyCode::KeyW,
        "KeyA" => KeyCode::KeyA,
        "KeyS" => KeyCode::KeyS,
        "KeyD" => KeyCode::KeyD,
        "Enter" => KeyCode::Enter,
        "Escape" => KeyCode::Escape,
        "ShiftLeft" => KeyCode::ShiftLeft,
        "Space" => KeyCode::Space,
        "F2" => KeyCode::F2,
        "F3" => KeyCode::F3,
        _ => return None,
    })
}

#[derive(Resource)]
pub struct Script {
    dir: std::path::PathBuf,
    steps: Vec<String>,
    at: usize,
    since: f32,
    /// Frames into this step (1 on its first), and when a slide's button went down (s).
    frames: u32,
    held: f32,
    pts: Option<(Vec2, Vec2)>,
    /// `point:ID[:H]`: the cursor follows this character, H m above its feet.
    pointing: Option<(u64, f32)>,
    /// `pointat:X,Y[:H]`: keep the cursor on a point of the world (sim m, H m above the ground).
    pointing_at: Option<(Vec2, f32)>,
    started: Option<u32>,
    /// The process that launched this scripted client (its parent at start, unix), and when it
    /// was last looked at (s): a script nobody drives any more ends itself.
    parent: Option<u32>,
    parent_check: f32,
}

/// This process's parent (unix; none elsewhere).
fn parent_pid() -> Option<u32> {
    #[cfg(unix)]
    {
        Some(std::os::unix::process::parent_id())
    }
    #[cfg(not(unix))]
    {
        None
    }
}

impl Script {
    fn from_env() -> Option<Self> {
        let dir = std::env::var("LIVING_GAME_LIVE").ok().filter(|d| !d.is_empty())?;
        std::fs::create_dir_all(&dir).ok()?;
        let plan = std::env::var("LIVING_GAME_LIVE_PLAN").unwrap_or_else(|_| "ready;wait:3;shot:join;walk:0:6;shot:street;say:Good morning!;wait:1;shot:say;wait:20;shot:later;quit".into());
        Some(Self { dir: dir.into(), steps: plan.split(';').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect(), at: 0, since: 0.0, frames: 0, held: 0.0, pts: None, pointing: None, pointing_at: None, started: None, parent: parent_pid(), parent_check: 0.0 })
    }
}

#[allow(clippy::too_many_arguments)]
fn script(
    mut commands: Commands,
    mut s: ResMut<Script>,
    net: NonSend<Net>,
    scene: NonSend<Scene>,
    island: Option<Res<Island>>,
    live: Res<Live>,
    fitted: Query<(), (With<Motion>, With<Fitted>)>,
    mut input: ResMut<Input>,
    mut cam: ResMut<Cam>,
    mut out: ResMut<crate::ui::model::Outbox>,
    (mut skills, mut gestures, mut verbs, mut talk): (ResMut<crate::combat::Scripted>, ResMut<crate::town::Scripted>, ResMut<crate::verbs::Scripted>, ResMut<crate::talk::Talk>),
    (hud, loading, mut pointer): (Res<crate::ui::model::HudModel>, Option<Res<crate::loading::Loading>>, ResMut<crate::pointer::Pointer>),
    (target, mut sight): (Option<Res<crate::capture::Target>>, Option<ResMut<crate::sightedge::SightEdge>>),
    (mut keys, mut buttons): (ResMut<ButtonInput<KeyCode>>, ResMut<ButtonInput<MouseButton>>),
    (mut dump, mut taps, ui): (ResMut<crate::ui::Dump>, ResMut<crate::keys::DoubleTap>, Res<crate::ui::hit::UiPointer>),
    (time, mut exit, cams, mut weapon, mut lw): (Res<Time>, MessageWriter<AppExit>, Query<(&Camera, &GlobalTransform), With<Camera3d>>, ResMut<crate::weapon::Weapon>, ResMut<crate::twist::LookWalk>),
) {
    // A point: X,Y as fractions of the picture, or @NAME, a tagged node of the game UI.
    let frac = |v: &str| match v.strip_prefix('@') {
        Some(tag) => {
            // Exactly, else the first tag it begins (`@acts:0:give` finds `acts:0:give:3`).
            let at = ui.tags.get(tag).copied().or_else(|| ui.tags.iter().find(|(k, _)| k.starts_with(&format!("{tag}:"))).map(|(_, v)| *v));
            if at.is_none() {
                warn!("live script: no UI node tagged {tag} is shown");
            }
            at
        }
        None => v.split_once(',').and_then(|(x, y)| Some(Vec2::new(x.trim().parse().ok()?, y.trim().parse().ok()?))),
    };
    let dt = time.delta_secs();
    // The driver that launched me is gone (a crashed or killed drive.py: I would wait on its
    // `sync:` files for ever): quit (verify-ui drive-reap-1).
    s.parent_check += dt;
    if s.parent_check >= 1.0 {
        s.parent_check = 0.0;
        if let (Some(was), Some(now)) = (s.parent, parent_pid()) {
            if was != now {
                warn!("live script: my launcher (pid {was}) is gone (parent now {now}); quitting");
                exit.write(AppExit::error());
                return;
            }
        }
    }
    if let Some((id, lift)) = s.pointing {
        let at = hud.actors.iter().find(|a| a.id == id).and_then(|a| {
            let ground = island.as_ref().map_or(a.head - Vec3::Y * (2.2 - lift), |i| Vec3::new(a.head.x, i.height(a.head.x, a.head.z) + lift, a.head.z));
            cams.iter().find_map(|(c, t)| Some((c.world_to_viewport(t, ground).ok()?, c.logical_viewport_size()?)))
        });
        if let Some((p, size)) = at {
            pointer.scripted = Some(p / size);
        }
    }
    if let Some((at, lift)) = s.pointing_at {
        let p3 = island.as_ref().map_or(Vec3::new(at.x, lift, at.y), |i| Vec3::new(at.x, i.height(at.x, at.y) + lift, at.y));
        if let Some((p, size)) = cams.iter().find_map(|(c, t)| Some((c.world_to_viewport(t, p3).ok()?, c.logical_viewport_size()?))) {
            pointer.scripted = Some(p / size);
        }
    }
    let Some(step) = s.steps.get(s.at).cloned() else { return };
    s.since += dt;
    s.frames += 1;
    let mine = net.my_id.and_then(|id| scene.shown.get(&id).map(|p| (id, p.0)));
    let mut parts = step.splitn(2, ':');
    let (verb, arg) = (parts.next().unwrap_or(""), parts.next().unwrap_or(""));
    let first = s.since <= dt;
    if first {
        info!("live script: {step} (me {:?} at {:?}, t {:.3} s)", net.my_id, mine.map(|m| m.1), time.elapsed_secs());
    }
    let done = match verb {
        "ready" => {
            let near_lots = live.lots.len();
            island.is_some() && mine.is_some() && near_lots > 0 && fitted.iter().count() >= live.shown.values().filter(|v| v.person).count().min(1) && crate::loading::Loading::clear(loading.as_deref()) && s.since > 2.0 || s.since > 240.0
        }
        "wait" => s.since >= arg.parse::<f32>().unwrap_or(1.0),
        "shot" => {
            let path = s.dir.join(format!("{arg}.png"));
            info!("live script: photograph {}", path.display());
            crate::capture::shot(&mut commands, target.as_deref(), path);
            true
        }
        "walk" => {
            let a: Vec<&str> = arg.split(':').collect();
            let deg: f32 = a.first().and_then(|v| v.parse().ok()).unwrap_or(0.0);
            let secs: f32 = a.get(1).and_then(|v| v.parse().ok()).unwrap_or(3.0);
            let run = a.get(2).is_some_and(|v| *v == "run");
            let d = Vec2::new(deg.to_radians().sin(), -deg.to_radians().cos());
            if s.since >= secs {
                input.scripted = Some((Vec2::ZERO, false));
                true
            } else {
                input.scripted = Some((d, run));
                false
            }
        }
        "hold" => {
            let a: Vec<&str> = arg.split(':').collect();
            let deg: f32 = a.first().and_then(|v| v.parse().ok()).unwrap_or(0.0);
            input.scripted = Some((Vec2::new(deg.to_radians().sin(), -deg.to_radians().cos()), a.get(1).is_some_and(|v| *v == "run")));
            true
        }
        "stop" => {
            input.scripted = Some((Vec2::ZERO, false));
            true
        }
        "goto" => {
            if let (Some(conn), Some((x, y))) = (net.conn.as_ref(), arg.split_once(',').and_then(|(x, y)| Some((x.trim().parse::<f32>().ok()?, y.trim().parse::<f32>().ok()?)))) {
                let node = serde_json::json!({"do": {"skill": "goto", "target": {"at": [x, y]}}}).to_string();
                let r = conn.reducers.human_act_then(node.clone(), net.on_reply("goto", "human_act", || serde_json::json!({"node": node})));
                net.report("goto", r);
                input.scripted = None;
            }
            true
        }
        "yaw" => {
            cam.set_yaw(arg.parse().unwrap_or(0.0));
            true
        }
        "frame" => {
            cam.rig.frame = arg != "0";
            true
        }
        "nudge" => {
            // The cursor moved by DX,DY logical px (a held wheel takes it as motion).
            s.pointing = None;
            s.pointing_at = None;
            if let Some((dx, dy)) = arg.split_once(',').and_then(|(x, y)| Some((x.trim().parse::<f32>().ok()?, y.trim().parse::<f32>().ok()?))) {
                let size = crate::capture::size().as_vec2();
                pointer.scripted = pointer.scripted.map(|f| f + Vec2::new(dx, dy) / size);
            }
            true
        }
        "wheel" => {
            verbs.wheel = Some(arg.to_string());
            true
        }
        "cursor" => {
            // X,Y (fractions of the picture) or @NAME (a tagged node: hovering a slot, a button).
            s.pointing = None;
            s.pointing_at = None;
            pointer.scripted = frac(arg);
            true
        }
        "tap" => {
            // A left tap, as the pointer reports one (`pointer.rs`): a strike, or on a peaceful
            // person the text box to them (`combat.rs`).
            pointer.scripted_tap = true;
            true
        }
        "click" => {
            // A left click on the game UI at X,Y (fractions of the picture): the cursor goes
            // there and the button goes down, and up on the next frame (`ui/hit.rs`).
            // The cursor first: the pointer places it at the start of the next frame.
            match s.frames {
                1 => {
                    s.pointing = None;
            s.pointing_at = None;
                    pointer.scripted = frac(arg);
                    false
                }
                2 => {
                    buttons.press(MouseButton::Left);
                    false
                }
                _ => {
                    buttons.release(MouseButton::Left);
                    true
                }
            }
        }
        "slide" => {
            // Hold the click at X1,Y1 and slide to X2,Y2 over SECS (default 0.5), then let go:
            // a title-bar drag, an item dragged onto someone (a three-finger drag is the same).
            // Points are separated by '>' (tags contain ':'): `slide:@pack:berries>0.5,0.5:0.6`.
            let (pts, secs_s) = match arg.rsplit_once(':').filter(|(_, t)| t.parse::<f32>().is_ok()) {
                Some((p, t)) => (p, t),
                None => (arg, ""),
            };
            let a: Vec<&str> = pts.split('>').collect();
            // Resolved once, on the step's first frame: a dragged window moves its own tags.
            if s.frames == 1 {
                s.pts = a.first().and_then(|v| frac(v)).zip(a.get(1).and_then(|v| frac(v)));
            }
            let (from, to) = (s.pts.map(|p| p.0), s.pts.map(|p| p.1));
            let secs: f32 = secs_s.parse().unwrap_or(0.5);
            match (from, to) {
                (Some(f), Some(t)) => {
                    if s.frames == 1 {
                        s.pointing = None;
            s.pointing_at = None;
                        pointer.scripted = Some(f);
                        false
                    } else if s.frames == 2 {
                        buttons.press(MouseButton::Left);
                        s.held = s.since;
                        false
                    } else if s.since - s.held < secs + 0.1 {
                        let k = ((s.since - s.held - 0.05) / secs).clamp(0.0, 1.0);
                        pointer.scripted = Some(f.lerp(t, k));
                        false
                    } else {
                        pointer.scripted = Some(t);
                        buttons.release(MouseButton::Left);
                        true
                    }
                }
                _ => {
                    warn!("live script: slide wants A>B[:SECS], got {arg}");
                    true
                }
            }
        }
        "pointat" => {
            // Keep the cursor on a point of the world (a thing's place), as `point:` on someone.
            let (xy, h) = arg.rsplit_once(':').map_or((arg, 0.5), |(a, h)| (a, h.parse().unwrap_or(0.5)));
            s.pointing = None;
            s.pointing_at = None;
            s.pointing_at = xy.split_once(',').and_then(|(x, y)| Some((Vec2::new(x.trim().parse().ok()?, y.trim().parse().ok()?), h)));
            true
        }
        "point" => {
            // Keep the cursor on character ID as drawn (their feet, where the cursor's ground
            // point finds them), frame after frame as the camera eases: hovering them, as a
            // player keeps pointing. Until a `cursor:` step or another `point:`.
            s.pointing_at = None;
            s.pointing = match arg.split_once(':') {
                Some((id, h)) => id.parse().ok().map(|id| (id, h.parse().unwrap_or(0.3))),
                None => arg.parse().ok().map(|id| (id, 0.3)),
            };
            true
        }
        "weapon" => {
            // As X: `weapon:toggle` (or `draw`, `sheathe`).
            weapon.scripted = Some(match arg {
                "draw" => true,
                "sheathe" => false,
                _ => !weapon.drawn,
            });
            true
        }
        "scroll" => {
            pointer.scripted_scroll += arg.parse::<f32>().unwrap_or(0.0);
            true
        }
        "dump" => {
            // The game UI's state as JSON (`ui::dump`): open windows, anchors, rectangles.
            dump.0 = Some(s.dir.join(format!("{arg}.json")));
            true
        }
        "dodge" => {
            // A double tap of a direction key (W, A, S or D), as the dodge's default binding.
            let a = match arg {
                "W" | "w" | "forward" => crate::keys::Act::Forward,
                "S" | "s" | "back" => crate::keys::Act::Back,
                "A" | "a" | "left" => crate::keys::Act::Left,
                _ => crate::keys::Act::Right,
            };
            taps.scripted = Some(a);
            true
        }
        "pan" | "drag" => {
            pointer.scripted_turn += arg.parse::<f32>().unwrap_or(0.0) * if verb == "pan" { 0.6 } else { 1.0 };
            true
        }
        "pinch" => {
            pointer.scripted_zoom *= 1.0 - arg.parse::<f32>().unwrap_or(0.0);
            true
        }
        "lookwalk" => {
            match crate::twist::LookWalk::parse(arg) {
                Ok(p) => {
                    info!("live script: look-walk {} (head {}°, chest {}°, body {}° over {} s, backwards past {}°)", p.name, p.head_deg, p.chest_deg, p.body_deg, p.body_s, p.back_deg);
                    *lw = p;
                }
                Err(e) => warn!("live script: lookwalk:{arg}: {e}"),
            }
            true
        }
        "look" => {
            input.scripted_look = arg.parse::<f32>().ok().map(|deg| Vec2::new(deg.to_radians().sin(), -deg.to_radians().cos()));
            true
        }
        "view" => {
            let v: Vec<f32> = arg.split(':').filter_map(|x| x.parse().ok()).collect();
            if v.len() >= 2 {
                cam.rig.view = crate::camera::View { pitch: v[0], distance: v[1], fov: v.get(2).copied().unwrap_or(cam.rig.view.fov) };
            } else {
                warn!("live script: view wants PITCH:DISTANCE[:FOV], got {arg}");
            }
            true
        }
        "say" => {
            out.say.push((arg.to_string(), 0));
            true
        }
        "sightlook" => {
            // The looks of "not seen now" under trial (`sightedge::Look`), for captures.
            match (crate::sightedge::Look::parse(arg), sight.as_deref_mut()) {
                (Some(l), Some(e)) => {
                    e.look = l;
                    info!("sight edge: look {l:?}");
                }
                _ => warn!("live script: no look {arg:?}"),
            }
            true
        }
        "skill" | "aim" => {
            let (name, aim) = arg.split_once(':').unwrap_or((arg, ""));
            if verb == "skill" {
                skills.press.push((name.to_string(), aim.to_string()));
            } else {
                skills.aiming = (!name.is_empty()).then(|| (name.to_string(), aim.to_string()));
            }
            true
        }
        "release" => {
            skills.release.push(arg.to_string());
            true
        }
        "gesture" => {
            let (name, whom) = arg.split_once(':').unwrap_or((arg, ""));
            gestures.press.push((name.to_string(), whom.to_string()));
            true
        }
        "act" => {
            let (what, at) = arg.split_once('@').unwrap_or((arg, ""));
            let (skill, item) = what.split_once(':').unwrap_or((what, ""));
            verbs.acts.push((skill.to_string(), item.to_string(), at.to_string()));
            true
        }
        "menu" => {
            verbs.menu.push(arg.to_string());
            true
        }
        "words" => {
            // The text box's words for an act that asked for them (as typed and Enter).
            input.compose = None;
            input.chat_open = false;
            input.composed = Some(arg.to_string());
            true
        }
        "panel" => {
            verbs.panel.push(arg.to_string());
            true
        }
        "sync" => {
            let go = s.dir.join(format!("{arg}.go"));
            let there = go.exists();
            if there {
                if let Some(yaw) = std::fs::read_to_string(&go).ok().and_then(|t| t.trim().parse::<f32>().ok()) {
                    cam.set_yaw(yaw);
                }
                let _ = std::fs::remove_file(&go);
            } else if first {
                info!("live script: waiting for {}", go.display());
            }
            there || s.since > 900.0
        }
        "key" => {
            let (name, how) = arg.rsplit_once(':').unwrap_or((arg, "tap"));
            match key_code(name) {
                Some(k) if how == "down" => keys.press(k),
                Some(k) if how == "up" => keys.release(k),
                Some(k) => {
                    keys.press(k);
                    keys.release(k);
                }
                None => warn!("live script: unknown key {name}"),
            }
            true
        }
        "mouse" => {
            let (name, how) = arg.rsplit_once(':').unwrap_or((arg, "down"));
            let b = match name {
                "left" => MouseButton::Left,
                "right" => MouseButton::Right,
                _ => MouseButton::Middle,
            };
            if how == "up" {
                buttons.release(b);
            } else {
                buttons.press(b);
            }
            true
        }
        "type" => {
            // Words typed into the open text box.
            input.chat = arg.to_string();
            true
        }
        "tab" => {
            talk.cycle = true;
            true
        }
        "enter" => {
            // As Enter in the open text box: said to whom it addresses (`talk.rs`).
            let line = std::mem::take(&mut input.chat);
            if !line.trim().is_empty() {
                out.say.push((line.trim().to_string(), talk.to.unwrap_or(0)));
            }
            input.chat_open = false;
            true
        }
        "chat" => {
            // As Enter opens it and Enter with nothing typed closes it, keeping its window (the
            // script's own keys may land after the chat's system has looked this frame).
            input.chat_open = arg == "open";
            input.chat.clear();
            true
        }
        "dead" => hud.death.is_some() || s.since > 120.0,
        "rejoin" => {
            s.started = net.my_id;
            out.rejoin = true;
            true
        }
        "joined" => net.my_id.is_some_and(|id| Some(id) != s.started) && mine.is_some() || s.since > 60.0,
        // A second for the last photograph to be written.
        "quit" => {
            if s.since > 1.0 {
                exit.write(AppExit::Success);
            }
            false
        }
        other => {
            warn!("live script: unknown step {other}");
            true
        }
    };
    if done {
        if verb == "ready" || verb == "dead" || verb == "joined" {
            info!("live script: {verb} after {:.1} s (me {:?} at {:?})", s.since, net.my_id, mine.map(|m| m.1));
        }
        s.at += 1;
        s.since = 0.0;
        s.frames = 0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A structure inside a house is hidden while the house is drawn closed, or not drawn, and
    /// shown while the cutaway has it open; a kit model waits for its fit.
    #[test]
    fn what_stands_indoors_shows_only_while_its_house_is_open() {
        let mut app = App::new();
        // A stand-in for `sight::update`, which sets every thing's visibility each frame first.
        let sight = |mut q: Query<&mut Visibility, With<crate::world::Indoors>>| {
            for mut v in &mut q {
                *v = Visibility::Inherited;
            }
        };
        app.init_resource::<Live>().add_systems(Update, (sight, indoors).chain());
        let house = app.world_mut().spawn(crate::envs::Occluder { height: 9.0, open: false }).id();
        app.world_mut().resource_mut::<Live>().lots.insert(7, vec![house]);
        let hearth = app.world_mut().spawn((crate::world::Indoors(7), Visibility::Inherited)).id();
        let elsewhere = app.world_mut().spawn((crate::world::Indoors(8), Visibility::Inherited)).id();
        let vis = |app: &App, e: Entity| *app.world().get::<Visibility>(e).unwrap();
        app.update();
        assert_eq!(vis(&app, hearth), Visibility::Hidden, "closed");
        assert_eq!(vis(&app, elsewhere), Visibility::Hidden, "its house is not drawn");
        app.world_mut().get_mut::<crate::envs::Occluder>(house).unwrap().open = true;
        app.update();
        assert_eq!(vis(&app, hearth), Visibility::Inherited, "open");
        app.world_mut().get_mut::<crate::envs::Occluder>(house).unwrap().open = false;
        app.update();
        assert_eq!(vis(&app, hearth), Visibility::Hidden, "closed again");
        // A kit model not fitted yet is hidden too while its house is closed (no flash at its
        // unfitted size).
        let model = crate::lookdev::Model { vrm: false, file: "envs/k/hearth/hearth.glb".into(), height: 0.0, ground_y: 0.0, glow: None };
        let unfitted = app.world_mut().spawn((crate::world::Indoors(7), model, Visibility::Inherited)).id();
        app.update();
        assert_eq!(vis(&app, unfitted), Visibility::Hidden, "unfitted, its house closed");
    }
}
