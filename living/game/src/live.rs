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
/// gaits), and above `RUNNING` you count as running (`Roam::running`).
const MOVING: f32 = crate::anim::MOVING;
const RUNNING: f32 = 3.3;
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
                (crate::envs::hdr, crate::island::stream, crate::island::report, crate::lookdev::convert, crate::lookdev::fit, crate::lookdev::rig, crate::lookdev::animate, crate::lookdev::sun, crate::envs::cutaway, report)
                    .chain()
                    .in_set(Phase::Present)
                    .after(me)
                    .run_if(island),
            )
            .add_systems(Update, ground_cursor.in_set(Phase::Camera).after(crate::camera::follow).run_if(island));
        if let Some(s) = Script::from_env() {
            app.insert_resource(s).add_systems(Update, script.in_set(Phase::Input).before(crate::controls::movement));
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
    /// while walking one way and looking another ([`legs_and_twist`]).
    face: f32,
    /// Walking backwards (the legs face away from the travel, the gaits reversed).
    back: bool,
}

/// A sitter whose rest ends gets up where it sat before walking off (`stand_up_ground`, 2.47 s,
/// played at this rate). The authority moves the body at once, so the drawn body waits at its
/// seat while the clip plays, then catches up at up to [`CATCH_UP`] m/s faster than the body.
const STAND_UP: (&str, f32, f64) = ("stand_up_ground", 1.6, 2467.0 / 1.6);
const CATCH_UP: f32 = 1.2;
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
/// Walking while looking more than this far from the travel (radians), a person walks
/// backwards, and forward again under [`BACK_OFF`]; between, the upper body turns.
const BACK_ON: f32 = 110.0 * PI / 180.0;
const BACK_OFF: f32 = 80.0 * PI / 180.0;
/// The most the upper body turns from the legs (radians).
const TWIST_MAX: f32 = 110.0 * PI / 180.0;

/// Where a moving person's legs face and whether it walks backwards: the legs step along the
/// travel, so its feet keep still, and the upper body turns toward where it looks. Clips have
/// no strafe or backward takes; the forward gaits reversed walk backwards.
fn legs_and_twist(travel: f32, look: f32, back: bool) -> (f32, bool) {
    let off = living_rules::steer::wrap(look - travel).abs();
    let back = if back { off > BACK_OFF } else { off > BACK_ON };
    (if back { living_rules::steer::wrap(travel + PI) } else { travel }, back)
}

#[derive(Resource, Default)]
pub struct Live {
    building: Option<Arc<Mutex<Option<Result<Built, String>>>>>,
    /// Whether all three digests matched (None until compared).
    pub digests_ok: Option<bool>,
    /// The tiles as the authority hosted them at world creation, to find later edits.
    hosted: Option<Arc<Map>>,
    lots: HashMap<u32, Vec<Entity>>,
    shown: HashMap<u32, Shown>,
    /// Height (m) of each drawn character, for nameplates and bubbles.
    pub heights: HashMap<u32, f32>,
    /// Bodies gone from sight, fading out where they were last drawn (`fade.rs`), and how long
    /// they have been fading (s).
    leaving: Vec<(Entity, f32)>,
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
    if let Some(def) = defs.iter().find(|d| d.world.is_some()) {
        crate::envs::apply_mood(&def.mood, &mut style, &mut look, &mut lights, &mut cams, &mut clear);
    }
    live.hosted = Some(built.hosted);
    let arrive = Vec2::new(row.arrive_x, row.arrive_y);
    roam.pos = arrive;
    commands.insert_resource(Island::hosted(built.land, &defs, arrive, &built.params));
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

/// Buildings from the `lot` rows in the window, near enough to see.
fn lots(mut commands: Commands, net: NonSend<Net>, island: Option<Res<Island>>, assets: Res<AssetServer>, mut live: ResMut<Live>, roam: Res<Roam>) {
    let (Some(island), Some(conn)) = (island, net.conn.as_ref()) else { return };
    let here = roam.pos;
    let gone: Vec<u32> = live.lots.keys().copied().filter(|id| conn.db.lot().id().find(id).is_none_or(|l| Vec2::new(l.x, l.y).distance(here) > LOT_DROP)).collect();
    for id in gone {
        for e in live.lots.remove(&id).unwrap_or_default() {
            commands.entity(e).despawn();
        }
    }
    let mut todo: Vec<(f32, Lot)> = conn.db.lot().iter().filter(|l| !live.lots.contains_key(&l.id)).map(|l| (Vec2::new(l.x, l.y).distance(here), l)).filter(|(d, _)| *d < LOT_FAR).collect();
    todo.sort_by(|a, b| a.0.total_cmp(&b.0));
    for (_, l) in todo.into_iter().take(LOTS_PER_FRAME) {
        let site = conn.db.settlement().id().find(&l.settlement).and_then(|s| crate::island::site_kind(&s.kind));
        let (Some(site), Some(kind)) = (site, living_rules::settle::LotKind::from_id(&l.kind)) else {
            live.lots.insert(l.id, Vec::new());
            continue;
        };
        let row = LotRow { id: l.id, site, kind, at: Vec2::new(l.x, l.y), yaw: l.yaw, floor_m: l.floor_m, height_m: l.height_m, model: l.model.clone() };
        let es = island.spawn_lot(&mut commands, &assets, &row);
        live.lots.insert(l.id, es);
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
    input: Res<Input>,
    combat: Res<crate::combat::Combat>,
    town: Res<crate::town::Town>,
    rules: NonSend<crate::verbs::Rules>,
    mut live: ResMut<Live>,
    mut q: Query<Drawn>,
    mut fades: Query<&mut crate::fade::Fade>,
    time: Res<Time>,
) {
    let Some(island) = island else { return };
    let Some(conn) = net.conn.as_ref() else {
        // Offline: no body is drawn (`bodies::update` has cleared the tracks too).
        for (_, s) in live.shown.drain() {
            commands.entity(s.entity).despawn();
        }
        for (e, _) in live.leaving.drain(..) {
            commands.entity(e).despawn();
        }
        live.heights.clear();
        return;
    };
    let dt = time.delta_secs().max(1e-4);
    let me = net.my_id;
    // Bodies that left sight fade out where they were, then go.
    live.leaving.retain_mut(|(e, t)| {
        *t += dt;
        let keep = *t < crate::fade::OUT_S + 0.05;
        if !keep {
            commands.entity(*e).despawn();
        }
        keep
    });
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
                    f.target = 1.0;
                    if let Ok((_, _, _, _, mut motion, _)) = q.get_mut(s.entity) {
                        motion.speed = 0.0;
                    }
                    live.leaving.push((s.entity, 0.0));
                }
                Err(_) => commands.entity(s.entity).despawn(),
            }
        }
        live.heights.remove(&id);
    }
    for (&id, &(p, heading)) in &scene.shown {
        let ground = island.height(p.x, p.y);
        let at = Vec3::new(p.x, ground, p.y);
        let mine = Some(id) == me;
        // My character turns toward where I look (shown locally; the authority has no look).
        let look = input.look.filter(|_| mine).filter(|l| l.length_squared() > 1e-4).map(|l| l.y.atan2(l.x));
        // During a move a body faces where the move goes; a gesture or settling down plays when
        // no move does.
        let show = town.shows.get(&id).copied().unwrap_or_default();
        let action = combat.actions.get(&id).copied().or(show.once);
        let aimed = action.and_then(|a| a.face).filter(|f| f.length_squared() > 1e-4).map(|f| f.y.atan2(f.x));
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
            let (entity, height, person, beast) = if body.kind == "person" {
                let c = character.as_ref().unwrap();
                let seed = island.land.seed.wrapping_mul(0x9E37_79B9).wrapping_add(id as u64);
                let mut recipe = if mine {
                    std::env::var("LIVING_GAME_PLAYER").ok().and_then(|r| crate::characters::Recipe::parse(&r)).unwrap_or_else(|| crate::characters::Recipe::random(seed, "adult"))
                } else {
                    match folk_of(c) {
                        (folk, Some(style)) => crate::characters::Recipe::random_in(seed, folk, &style),
                        (folk, None) => crate::characters::Recipe::random(seed, folk),
                    }
                };
                recipe.height *= stage_scale(c.stage);
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
                commands.entity(entity).insert(crate::gait::Feet);
            }
            live.shown.insert(id, Shown { entity, last: p, speed: 0.0, person, beast, yaw: h, drawn: p, sitting: false, rising: None, startles, still: 0.0, startle: None, tilt: Quat::IDENTITY, kind: body.kind.clone(), face: h, back: false });
            live.heights.insert(id, height);
            continue;
        }
        let s = live.shown.get_mut(&id).unwrap();
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
        let held = s.rising.filter(|(t, _)| scene.now_ms - t < STAND_UP.2).map(|(_, at)| at).or(s.startle.map(|(_, at)| at));
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
        // A person walking one way while looking another (my cursor, a move's aim): the legs keep
        // to the travel, forward or backward, and the upper body turns toward the look.
        let look_at = aimed.or(look);
        let walking = s.person && s.speed > MOVING;
        let (legs, back) = match (walking, look_at, heading) {
            (true, Some(l), Some(t)) => {
                let (y, b) = legs_and_twist(t, l, s.back);
                (Some(y), b)
            }
            _ => (h, false),
        };
        s.back = back;
        let k = 1.0 - (-dt * YAW_RATE).exp();
        if let Some(y) = legs {
            s.yaw = living_rules::steer::wrap(s.yaw + living_rules::steer::wrap(y - s.yaw) * k);
        }
        if let Some(f) = look_at.filter(|_| walking).or(legs) {
            s.face = living_rules::steer::wrap(s.face + living_rules::steer::wrap(f - s.face) * k);
        }
        let twist = if s.person { living_rules::steer::wrap(s.face - s.yaw).clamp(-TWIST_MAX, TWIST_MAX) } else { 0.0 };
        let reverse = s.back;
        let (speed, person, beast, yaw) = (s.speed, s.person, s.beast, s.yaw);
        let rising = s.rising.filter(|(t, _)| scene.now_ms - t < STAND_UP.2).map(|(t, _)| t);
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
        motion.action = action.or(rising.map(|t| crate::combat::Action { clip: STAND_UP.0, rate: STAND_UP.1, start_ms: t, hold: None, face: None, ..Default::default() })).or(startle);
        motion.now_ms = scene.now_ms;
        motion.reverse = reverse;
        motion.twist = twist;
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
            roam.running = speed > RUNNING;
            roam.speed = speed;
            target.0 = Some(Vec3::new(p.x, island.height(p.x, p.y), p.y));
        }
        None => target.0 = None,
    }
}

/// Where the cursor meets the island's ground (the camera's own ray uses the tile ground). The
/// eye's height over the island's hills is the camera's own (`camera::follow`).
fn ground_cursor(island: Option<Res<Island>>, mut cam: ResMut<Cam>, cams: Query<(&Camera, &GlobalTransform), With<Camera3d>>, pointer: Res<crate::pointer::Pointer>) {
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
///   (a headless run has no cursor); `cursor:X,Y` puts the game's cursor there (fractions of the
///   picture; `cursor:` takes it away), and `pan:PX`, `drag:PX` and `pinch:F` turn the view or
///   zoom through the pointer's paths (`pointer.rs`: a two-finger pan, a left drag, a pinch);
///   `frame:0` stops the view framing fights, talks and greetings (`frame:1` again);
/// - `goto:X,Y`: click-to-move (`human_act` with `goto`); `yaw:DEG`: turn the view;
///   `view:PITCH:DISTANCE[:FOV]`: the game camera's pitch (deg), distance (m) and field of view
///   (photographing small things up close);
/// - `say:TEXT`: proximity chat (`human_say`);
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
/// - `dead`: until the death screen shows; `rejoin`: its "arrive again" button; `joined`:
///   until a new character is mine;
/// - `quit`.
/// A key of the `key:` step.
fn key_code(name: &str) -> Option<KeyCode> {
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
        _ => return None,
    })
}

#[derive(Resource)]
pub struct Script {
    dir: std::path::PathBuf,
    steps: Vec<String>,
    at: usize,
    since: f32,
    started: Option<u32>,
}

impl Script {
    fn from_env() -> Option<Self> {
        let dir = std::env::var("LIVING_GAME_LIVE").ok().filter(|d| !d.is_empty())?;
        std::fs::create_dir_all(&dir).ok()?;
        let plan = std::env::var("LIVING_GAME_LIVE_PLAN").unwrap_or_else(|_| "ready;wait:3;shot:join;walk:0:6;shot:street;say:Good morning!;wait:1;shot:say;wait:20;shot:later;quit".into());
        Some(Self { dir: dir.into(), steps: plan.split(';').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect(), at: 0, since: 0.0, started: None })
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
    (mut skills, mut gestures, mut verbs): (ResMut<crate::combat::Scripted>, ResMut<crate::town::Scripted>, ResMut<crate::verbs::Scripted>),
    (hud, loading, mut pointer): (Res<crate::ui::model::HudModel>, Option<Res<crate::loading::Loading>>, ResMut<crate::pointer::Pointer>),
    target: Option<Res<crate::capture::Target>>,
    (mut keys, mut buttons): (ResMut<ButtonInput<KeyCode>>, ResMut<ButtonInput<MouseButton>>),
    time: Res<Time>,
    mut exit: MessageWriter<AppExit>,
) {
    let dt = time.delta_secs();
    let Some(step) = s.steps.get(s.at).cloned() else { return };
    s.since += dt;
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
                let r = conn.reducers.human_act_then(node, net.on_reply("goto"));
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
        "cursor" => {
            pointer.scripted = arg.split_once(',').and_then(|(x, y)| Some(Vec2::new(x.trim().parse().ok()?, y.trim().parse().ok()?)));
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
            out.say.push(arg.to_string());
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
        "chat" => {
            // As Enter opens it and Esc closes it (the script's own keys may land after the
            // chat's system has looked this frame).
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
    }
}
