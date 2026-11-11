//! Where my character's sight lines reach (docs/GAME_BRIEF.md, "Edge of sight"). Presentation
//! only: the authority decides whom I perceive; this draws why.
//!
//! The authority's sight is a radius and a clear line (`perception::in_sight`:
//! `Map::sight_clear`, rock, walls and shut gates block, drops and things below eye height do not; docs/PERCEPTION.md). The client has the
//! same tiles: the land regenerated as the authority hosted it (`living_rules::host::hosted_map`,
//! `live.rs`), the `terrain_chunk` rows of its window where they differ (tiles edited since), and
//! the shut gates (`gate`). So it runs the same `Map::sight_clear` on them:
//!
//! - **The field.** A texture of [`SIZE`] × [`SIZE`] texels of [`TEXEL`] m (two a tile) centred
//!   on my tile: 1 where the line from where I stand to the texel's centre is clear, 0 where
//!   something blocks it. Blocking things themselves (a building, a stall, a rock) count as seen whole when
//!   any of their tiles is: I see that building, not what stands behind it. Worked out again when
//!   I move [`MOVE_M`], my sight changes or the tiles do, on the async compute pool (about a
//!   millisecond by day at 48 m, so it never holds up a frame); the finishing pass (`edges.wesl`)
//!   samples it filtered, so the edge of a sight shadow is soft over about half a tile.
//! - **People leaving sight.** With "not seen now" or "limited view", someone whose line from me
//!   breaks fades out as it breaks (the same test, at their drawn position), rather than when the
//!   authority's next sweep (every 200 ms) and its delivery drop them. Nobody is drawn who isn't
//!   sent: this only fades earlier those it still sends.
//!
//! - **Memory** (the `memory` look under trial, `sightedge::Look`): when each field is shown,
//!   every texel seen within my radius records the time; a second texture of the same texels
//!   holds how recently each was seen (1 now, 0 [`crate::sightedge::MEMORY_S`] ago or never),
//!   uploaded about 15 times a second while that look is on. It follows the field's corner, so
//!   it remembers only within the field (±64 m).
//!
//! `LIVING_SIGHT_FIELD_DUMP=DIR` writes the field and where it was worked out, once a second when
//! it changed (`field-<n>.pgm` and `.json`), for checks against the authority's perceived set.
//! `LIVING_GAME_PERF=sightfield` logs the recompute cost every 5 s.

use crate::net::Net;
use crate::sightedge::{Mode, SightEdge};
use bevy::asset::RenderAssetUsages;
use bevy::image::ImageSampler;
use bevy::prelude::*;
use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
use bevy::tasks::{futures::check_ready, AsyncComputeTaskPool, Task};
use living_bindings::*;
use living_rules::map::Map;
use living_rules::script::Senses;
use spacetimedb_sdk::Table;
use std::collections::{HashSet, VecDeque};
use std::hash::{Hash, Hasher};
use std::sync::Arc;

/// Texels each side, of [`TEXEL`] m: the field covers ±64 m round my tile.
pub const SIZE: i32 = 256;
/// A texel's side (m): two a tile, so the edge of a sight shadow follows the lines more closely
/// than the tiles do (the authority tests exact positions, not tile centres).
pub const TEXEL: f32 = 0.5;
/// The field's side (m).
pub const EXTENT: f32 = SIZE as f32 * TEXEL;
/// Work the field out again when I have moved this far (m) from where it was.
const MOVE_M: f32 = 0.25;
/// How often the tiles are compared with the authority's edits and gates (s).
const TILES_S: f32 = 0.5;
/// Beyond the radius the field is not needed (the finishing pass fades by distance): this much
/// margin (m) covers its soft band and the authority's one-tile hold.
const MARGIN: f32 = 4.0;

/// Recompute cost, for `LIVING_GAME_PERF=sightfield` and the dump.
#[derive(Default, Clone, Copy, Debug)]
pub struct Cost {
    pub runs: u64,
    pub total_ms: f64,
    pub max_ms: f64,
    pub last_ms: f64,
    /// Tiles tested in the last run.
    pub tiles: u32,
    /// The memory look's work on the frame: recording each new field, and building each upload
    /// (count, total ms).
    pub remember: (u64, f64),
    pub memory_upload: (u64, f64),
}

#[derive(Resource)]
pub struct SightField {
    pub image: Handle<Image>,
    /// How recently each texel was seen (the memory look), at the same corner as the field.
    pub memory_image: Handle<Image>,
    /// Whether the memory texture is current (the memory look is on and has uploaded it).
    pub memory_live: bool,
    /// When each texel was last seen within my radius (s of app time; -inf never), and the
    /// corner they are kept at.
    last_seen: Vec<f32>,
    memory_origin: IVec2,
    next_memory: f32,
    /// The corner of texel (0, 0) (sim metres, on a tile corner).
    pub origin: IVec2,
    /// Whether the texture holds a field for where I am.
    pub valid: bool,
    eye: Option<Vec2>,
    reach: f32,
    /// Where the field was last asked for (the running or last task), and the running task.
    asked: Option<(Vec2, f32, Option<Facing>)>,
    /// The facing the shown field was worked out for (none: sight the same all round).
    pub facing: Option<Facing>,
    task: Option<Task<Computed>>,
    /// The tiles sight is tested on: the hosted land, with the window's edits and shut gates.
    map: Option<Arc<Map>>,
    hosted: Option<Arc<Map>>,
    sig: u64,
    next_tiles: f32,
    seen: Vec<u8>,
    pub cost: Cost,
    /// Changed since the last dump.
    fresh: bool,
    dump: Option<std::path::PathBuf>,
    dumped: u32,
    next_dump: f32,
    next_report: f32,
}

impl SightField {
    /// The field at a point (sim metres), filtered like the finishing pass samples it: 1 seen,
    /// 0 behind something; `None` outside it or before it is known.
    pub fn at(&self, p: Vec2) -> Option<f32> {
        if !self.valid {
            return None;
        }
        let q = (p - self.origin.as_vec2()) / TEXEL - Vec2::splat(0.5);
        let (i, j) = (q.x.floor() as i32, q.y.floor() as i32);
        if i < 0 || j < 0 || i + 1 >= SIZE || j + 1 >= SIZE {
            return None;
        }
        let f = q - Vec2::new(i as f32, j as f32);
        let v = |i: i32, j: i32| self.seen[(j * SIZE + i) as usize] as f32 / 255.0;
        let a = v(i, j) + (v(i + 1, j) - v(i, j)) * f.x;
        let b = v(i, j + 1) + (v(i + 1, j + 1) - v(i, j + 1)) * f.x;
        Some(a + (b - a) * f.y)
    }

    /// The tiles sight is tested on, once the land is known.
    pub fn map(&self) -> Option<&Map> {
        self.map.as_deref()
    }
}

pub struct SightFieldPlugin;

impl Plugin for SightFieldPlugin {
    fn build(&self, app: &mut App) {
        app.add_systems(Startup, setup).add_systems(Update, (attach, tiles, update, people).chain().in_set(crate::phase::Phase::Camera).after(crate::sightedge::update));
    }
}

fn setup(mut commands: Commands, mut images: ResMut<Assets<Image>>) {
    let size = Extent3d { width: SIZE as u32, height: SIZE as u32, depth_or_array_layers: 1 };
    let mut image = Image::new(size, TextureDimension::D2, vec![255; (SIZE * SIZE) as usize], TextureFormat::R8Unorm, RenderAssetUsages::default());
    image.sampler = ImageSampler::linear();
    let handle = images.add(image);
    let mut memory = Image::new(size, TextureDimension::D2, vec![0; (SIZE * SIZE) as usize], TextureFormat::R8Unorm, RenderAssetUsages::default());
    memory.sampler = ImageSampler::linear();
    let memory_image = images.add(memory);
    let dump = std::env::var("LIVING_SIGHT_FIELD_DUMP").ok().filter(|d| !d.is_empty()).map(std::path::PathBuf::from);
    if let Some(d) = &dump {
        let _ = std::fs::create_dir_all(d);
    }
    commands.insert_resource(SightField {
        image: handle,
        memory_image,
        memory_live: false,
        last_seen: vec![f32::NEG_INFINITY; (SIZE * SIZE) as usize],
        memory_origin: IVec2::ZERO,
        next_memory: 0.0,
        origin: IVec2::ZERO,
        valid: false,
        eye: None,
        reach: 0.0,
        asked: None,
        facing: None,
        task: None,
        map: None,
        hosted: None,
        sig: 0,
        next_tiles: 0.0,
        seen: vec![0; (SIZE * SIZE) as usize],
        cost: Cost::default(),
        fresh: false,
        dump,
        dumped: 0,
        next_dump: 0.0,
        next_report: 5.0,
    });
}

/// The finishing pass's camera gets the field's texture.
fn attach(mut commands: Commands, field: Option<Res<SightField>>, cams: Query<Entity, (With<crate::post::Edges>, Without<crate::post::SightTexture>)>) {
    let Some(field) = field else { return };
    for cam in &cams {
        commands.entity(cam).insert(crate::post::SightTexture(field.image.clone(), field.memory_image.clone()));
    }
}

/// Keep the tiles the authority tests sight on: the hosted land, where the window's
/// `terrain_chunk` rows differ from it, and the shut gates.
fn tiles(mut field: Option<ResMut<SightField>>, live: Res<crate::live::Live>, net: NonSend<Net>, time: Res<Time>) {
    let Some(field) = field.as_deref_mut() else { return };
    let Some(hosted) = live.hosted_map() else { return };
    field.next_tiles -= time.delta_secs();
    let new_land = !field.hosted.as_ref().is_some_and(|h| Arc::ptr_eq(h, &hosted));
    if !new_land && field.next_tiles > 0.0 {
        return;
    }
    field.next_tiles = TILES_S;
    let mut edits: Vec<(u32, Vec<u8>)> = Vec::new();
    let mut shut: Vec<u32> = Vec::new();
    if let Some(conn) = net.conn.as_ref() {
        for c in conn.db.terrain_chunk().iter() {
            if c.tiles != hosted.chunk_bytes(c.id) {
                edits.push((c.id, c.tiles));
            }
        }
        for g in conn.db.gate().iter().filter(|g| !g.open && g.x >= 0 && g.y >= 0 && (g.x as u32) < hosted.w && (g.y as u32) < hosted.h) {
            shut.push(g.y as u32 * hosted.w + g.x as u32);
        }
    }
    edits.sort_by_key(|e| e.0);
    shut.sort_unstable();
    let mut h = std::collections::hash_map::DefaultHasher::new();
    edits.hash(&mut h);
    shut.hash(&mut h);
    let sig = h.finish();
    if !new_land && sig == field.sig {
        return;
    }
    let map = if edits.is_empty() && shut.is_empty() {
        hosted.clone()
    } else {
        let mut m = (*hosted).clone();
        for (id, t) in &edits {
            m.put_chunk(*id, t);
        }
        m.set_blocked(shut.iter().copied().collect::<HashSet<u32>>());
        Arc::new(m)
    };
    info!("sight field: tiles from the hosted land, {} edited chunks in the window, {} shut gates", edits.len(), shut.len());
    field.sig = sig;
    field.hosted = Some(hosted);
    field.map = Some(map);
    field.asked = None;
}

/// A field worked out off the frame.
struct Computed {
    seen: Vec<u8>,
    facing: Option<Facing>,
    origin: IVec2,
    eye: Vec2,
    reach: f32,
    ms: f64,
    tested: u32,
}

/// Work the field out again when I moved, my sight changed or the tiles did.
#[allow(clippy::too_many_arguments)]
fn update(mut field: Option<ResMut<SightField>>, edge: Res<SightEdge>, target: Res<crate::controls::Target>, net: NonSend<Net>, scene: NonSend<crate::world::Scene>, mut images: ResMut<Assets<Image>>, time: Res<Time>) {
    let Some(field) = field.as_deref_mut() else { return };
    // While the world's `fov_on` law gives my senses a field: which way my body faces, by the
    // authority's own motion row, at the instant my body is drawn.
    let facing = facing_now(&edge, &net, &scene);
    let dt = time.delta_secs();
    let (Some(map), Some(me), Some(want)) = (field.map.clone(), target.0, edge.want) else {
        field.valid = false;
        return;
    };
    let eye = Vec2::new(me.x, me.z);
    let reach = (want + MARGIN).min(EXTENT * 0.5 - 2.0);
    // A finished field: shown from this frame.
    if let Some(done) = field.task.as_mut().and_then(check_ready) {
        field.task = None;
        let c = &mut field.cost;
        c.runs += 1;
        c.total_ms += done.ms;
        c.max_ms = c.max_ms.max(done.ms);
        c.last_ms = done.ms;
        c.tiles = done.tested;
        field.origin = done.origin;
        field.eye = Some(done.eye);
        field.reach = done.reach;
        field.facing = done.facing;
        field.valid = true;
        field.fresh = true;
        if let Some(mut img) = images.get_mut(&field.image) {
            img.data = Some(done.seen.clone());
        }
        field.seen = done.seen;
        let t0 = std::time::Instant::now();
        remember(field, edge.radius, time.elapsed_secs());
        field.cost.remember.0 += 1;
        field.cost.remember.1 += t0.elapsed().as_secs_f64() * 1000.0;
    }
    // The memory look: how recently each texel was seen, about 15 times a second.
    let wants_memory = edge.mode == Mode::Unseen && edge.look == crate::sightedge::Look::Memory;
    field.next_memory -= dt;
    if wants_memory && field.next_memory <= 0.0 && field.valid {
        field.next_memory = 1.0 / 15.0;
        let t0 = std::time::Instant::now();
        let now = time.elapsed_secs();
        let bytes: Vec<u8> = field.last_seen.iter().map(|t| ((1.0 - (now - t) / crate::sightedge::MEMORY_S).clamp(0.0, 1.0) * 255.0) as u8).collect();
        if let Some(mut img) = images.get_mut(&field.memory_image) {
            img.data = Some(bytes);
        }
        field.memory_live = true;
        field.cost.memory_upload.0 += 1;
        field.cost.memory_upload.1 += t0.elapsed().as_secs_f64() * 1000.0;
    } else if !wants_memory {
        field.memory_live = false;
    }
    let due = field.asked.is_none_or(|(e, r, f)| e.distance(eye) >= MOVE_M || (reach - r).abs() > 0.01 || turned(&f, facing));
    if due && field.task.is_none() {
        field.asked = Some((eye, reach, facing));
        let half = (EXTENT * 0.5) as i32;
        let origin = IVec2::new(eye.x.floor() as i32 - half, eye.y.floor() as i32 - half);
        field.task = Some(AsyncComputeTaskPool::get().spawn(async move {
            let t0 = std::time::Instant::now();
            let mut seen = vec![0u8; (SIZE * SIZE) as usize];
            let tested = compute(&map, eye, reach, origin, &mut seen, facing.as_ref());
            Computed { seen, facing, origin, eye, reach, ms: t0.elapsed().as_secs_f64() * 1000.0, tested }
        }));
    }
    if crate::perf::has("sightfield") {
        field.next_report -= dt;
        if field.next_report <= 0.0 {
            field.next_report = 5.0;
            let c = field.cost;
            info!("sight field: {} recomputes, mean {:.3} ms, max {:.3} ms, last {:.3} ms over {} tiles (reach {:.1} m)", c.runs, c.total_ms / c.runs.max(1) as f64, c.max_ms, c.last_ms, c.tiles, field.reach);
            info!("sight field: memory on the frame: {} records, mean {:.3} ms; {} uploads built, mean {:.3} ms", c.remember.0, c.remember.1 / c.remember.0.max(1) as f64, c.memory_upload.0, c.memory_upload.1 / c.memory_upload.0.max(1) as f64);
        }
    }
    field.next_dump -= dt;
    if field.fresh && field.next_dump <= 0.0 {
        if let Some(dir) = field.dump.clone() {
            field.next_dump = 1.0;
            field.fresh = false;
            write_dump(field, &dir, edge.radius, want);
        }
    }
}

/// Record the texels the field shows seen within my radius as seen now, after moving what is
/// remembered to the field's corner.
fn remember(field: &mut SightField, radius: f32, now: f32) {
    let (Some(eye), origin) = (field.eye, field.origin) else { return };
    if origin != field.memory_origin {
        let shift = (origin - field.memory_origin) * (1.0 / TEXEL) as i32;
        let old = std::mem::replace(&mut field.last_seen, vec![f32::NEG_INFINITY; (SIZE * SIZE) as usize]);
        for j in 0..SIZE {
            for i in 0..SIZE {
                let (oi, oj) = (i + shift.x, j + shift.y);
                if (0..SIZE).contains(&oi) && (0..SIZE).contains(&oj) {
                    field.last_seen[(j * SIZE + i) as usize] = old[(oj * SIZE + oi) as usize];
                }
            }
        }
        field.memory_origin = origin;
    }
    let r2 = radius * radius;
    for j in 0..SIZE {
        let y = origin.y as f32 + (j as f32 + 0.5) * TEXEL - eye.y;
        if y * y > r2 {
            continue;
        }
        for i in 0..SIZE {
            let x = origin.x as f32 + (i as f32 + 0.5) * TEXEL - eye.x;
            let k = (j * SIZE + i) as usize;
            if x * x + y * y <= r2 && field.seen[k] >= 128 {
                field.last_seen[k] = now;
            }
        }
    }
}

/// Which way my body faces and how my view narrows away from it, while the world's `fov_on` law
/// gives my senses a field (`sight::Field`).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Facing {
    /// `body.heading` (radians, sim: +x east, +y south), by `steer::pose` on my motion row.
    pub heading: f32,
    /// My senses now (`senses(a)`), the field among them.
    pub senses: Senses,
}

/// Work the field out again when my heading turns this far (or the field's values change).
pub const TURN_DEG: f32 = 2.0;

fn turned(was: &Option<Facing>, now: Option<Facing>) -> bool {
    match (was, now) {
        (None, None) => false,
        (Some(a), Some(b)) => a.senses.field != b.senses.field || a.senses.sight != b.senses.sight || living_rules::steer::wrap(a.heading - b.heading).abs() > TURN_DEG.to_radians(),
        _ => true,
    }
}

/// My body's heading now (`body.heading`, eased through its turn by `steer::pose`, as the
/// authority's `heading_at`), from my own motion row, at `now_ms` on the display clock.
pub fn my_heading(net: &Net, now_ms: f64) -> Option<f32> {
    let (conn, me) = (net.conn.as_ref()?, net.my_id?);
    let m = conn.db.my_body().id().find(&me)?;
    let end = (m.next_ms as f64).max(m.t_ms as f64);
    let dt = ((now_ms.min(end) - m.t_ms as f64) / 1000.0).max(0.0) as f32;
    let (_, _, h) = living_rules::steer::pose(m.x, m.y, m.heading, m.vx.hypot(m.vy), m.turn, m.turn_s, dt);
    Some(living_rules::steer::wrap(h))
}

/// My facing now, while my senses have a field; none without one (sight the same all round).
pub fn facing_now(edge: &SightEdge, net: &Net, scene: &crate::world::Scene) -> Option<Facing> {
    let senses = edge.senses.filter(|s| s.field.is_some())?;
    // Where the facing plugs in for `human_face` too: it sets `body.heading`, the same row.
    Some(Facing { heading: my_heading(net, scene.mine_ms)?, senses })
}

/// The field round `eye` (sim metres) within `reach`, texel (0, 0) at `origin`: 255 where the
/// line from `eye` to the texel's centre is clear (`Map::sight_clear`, the authority's test),
/// then every texel on a blocking tile joined to a seen one (one building, one rock) is seen
/// too. Returns the texels tested.
///
/// With a `facing` (the world's `fov_on` law), a texel must also lie within what the eye sees in
/// its direction (`sight::reach`, the rules' one sight rule): full sight within the focal angle
/// (out to `reach`, as without a field, so the radius's soft band draws that edge), the side
/// share out to the side angle, and the near ring all round. Ground has no glow, and the
/// margins for someone already seen don't apply to ground. Without one, the field is exactly
/// what it was before facing sight.
pub fn compute(map: &Map, eye: Vec2, reach: f32, origin: IVec2, seen: &mut [u8], facing: Option<&Facing>) -> u32 {
    seen.fill(0);
    let r2 = reach * reach;
    let e = (eye.x, eye.y);
    let mut tested = 0;
    let mut exposed: VecDeque<(i32, i32)> = VecDeque::new();
    let centre = |i: i32, j: i32| (origin.x as f32 + (i as f32 + 0.5) * TEXEL, origin.y as f32 + (j as f32 + 0.5) * TEXEL);
    let opaque = |i: i32, j: i32| {
        let c = centre(i, j);
        !map.passable_missile(c.0, c.1)
    };
    for j in 0..SIZE {
        for i in 0..SIZE {
            let c = centre(i, j);
            if c.0 < 0.0 || c.1 < 0.0 || c.0 >= map.w as f32 || c.1 >= map.h as f32 {
                continue;
            }
            let d2 = (c.0 - e.0).powi(2) + (c.1 - e.1).powi(2);
            if d2 > r2 {
                continue;
            }
            if let Some(f) = facing {
                let r = living_rules::sight::reach(&f.senses, living_rules::sight::off_facing(e, f.heading, c), 0.0, None);
                // Full sight that way (the focal angle): the field reaches as far as without one.
                if r < f.senses.sight && d2 > r * r {
                    continue;
                }
            }
            tested += 1;
            if map.sight_clear(e, c) {
                seen[(j * SIZE + i) as usize] = 255;
                if opaque(i, j) {
                    exposed.push_back((i, j));
                }
            }
        }
    }
    // Blocking things are seen whole when any face of them is.
    while let Some((i, j)) = exposed.pop_front() {
        for (di, dj) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
            let (ni, nj) = (i + di, j + dj);
            if ni < 0 || nj < 0 || ni >= SIZE || nj >= SIZE {
                continue;
            }
            let k = (nj * SIZE + ni) as usize;
            if seen[k] == 0 && opaque(ni, nj) {
                seen[k] = 255;
                exposed.push_back((ni, nj));
            }
        }
    }
    tested
}

/// A facing for the dump: `null`, or its heading and the field's five values.
fn facing_json(f: Option<&Facing>) -> String {
    match f.and_then(|f| f.senses.field.map(|v| (f, v))) {
        None => "null".into(),
        Some((f, v)) => format!(
            "{{\"heading\": {:.5}, \"sight\": {:.3}, \"focal_deg\": {}, \"side_deg\": {}, \"side_share\": {}, \"near_m\": {}, \"margin_deg\": {}}}",
            f.heading, f.senses.sight, v.focal_deg, v.side_deg, v.side_share, v.near_m, v.margin_deg
        ),
    }
}

fn write_dump(field: &mut SightField, dir: &std::path::Path, radius: f32, want: f32) {
    let n = field.dumped;
    field.dumped += 1;
    let mut pgm = format!("P5\n{SIZE} {SIZE}\n255\n").into_bytes();
    pgm.extend_from_slice(&field.seen);
    let eye = field.eye.unwrap_or_default();
    let ms = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_or(0, |d| d.as_millis());
    let json = format!(
        "{{\"n\": {n}, \"wall_ms\": {ms}, \"origin\": [{}, {}], \"size\": {SIZE}, \"texel\": {TEXEL}, \"eye\": [{:.3}, {:.3}], \"radius\": {radius:.3}, \"sight\": {want:.3}, \"reach\": {:.3}, \"cost_ms\": {:.4}, \"tiles\": {}, \"facing\": {}}}\n",
        field.origin.x, field.origin.y, eye.x, eye.y, field.reach, field.cost.last_ms, field.cost.tiles, facing_json(field.facing.as_ref())
    );
    let _ = std::fs::write(dir.join(format!("field-{n:04}.pgm")), pgm);
    let _ = std::fs::write(dir.join(format!("field-{n:04}.json")), json);
}

/// With "not seen now" or "limited view", people whose sight line from me breaks fade out as it
/// breaks (`Map::sight_clear` from where I am drawn to where they are), and back in if it clears
/// while the authority still sends them.
#[allow(clippy::too_many_arguments)]
fn people(
    field: Option<Res<SightField>>,
    edge: Res<SightEdge>,
    net: NonSend<Net>,
    scene: NonSend<crate::world::Scene>,
    live: Res<crate::live::Live>,
    mut fades: Query<&mut crate::fade::Fade>,
    mut broke: Local<std::collections::HashMap<u32, f64>>,
    (time, mut next_check): (Res<Time>, Local<f32>),
) {
    let Some(field) = field.as_deref() else { return };
    let (Some(map), Some(me)) = (field.map(), net.my_id.and_then(|id| scene.shown.get(&id)).map(|s| s.0)) else { return };
    // `LIVING_GAME_PERF=sightfield`: everyone the authority sends me, against the field where
    // they are drawn and the exact line (every 2 s).
    *next_check -= time.delta_secs();
    if crate::perf::has("sightfield") && *next_check <= 0.0 {
        *next_check = 2.0;
        let mut rows: Vec<(f32, u32, bool, f32)> = Vec::new();
        for (id, _) in live.drawn() {
            if Some(id) == net.my_id {
                continue;
            }
            let Some(&(p, _)) = scene.shown.get(&id) else { continue };
            rows.push((p.distance(me), id, map.sight_clear((me.x, me.y), (p.x, p.y)), field.at(p).unwrap_or(-1.0)));
        }
        rows.sort_by(|a, b| a.0.total_cmp(&b.0));
        let off: Vec<String> = rows.iter().filter(|r| !r.2 || (0.0..0.5).contains(&r.3)).map(|r| format!("{}@{:.1}m line {} field {:.2}", r.1, r.0, r.2, r.3)).collect();
        info!("sight field check: {} sent and drawn; {} with the line blocked or the field under 0.5 here: {:?}", rows.len(), off.len(), off);
    }
    let facing = facing_now(&edge, &net, &scene);
    if edge.mode == Mode::Fade || edge.want.is_none() {
        broke.clear();
        return;
    }
    // Those faded ahead of the authority that it has since stopped sending: how far ahead.
    let now = time.elapsed_secs_f64();
    let drawn: HashSet<u32> = live.drawn().map(|(id, _)| id).collect();
    broke.retain(|id, t| {
        let keep = drawn.contains(id);
        if !keep {
            info!("sight field: {id} left the authority's sight {:.0} ms after its line broke here", (now - *t) * 1000.0);
        }
        keep
    });
    for (id, entity) in live.drawn() {
        if Some(id) == net.my_id {
            continue;
        }
        let Some(&(p, _)) = scene.shown.get(&id) else { continue };
        let mut clear = map.sight_clear((me.x, me.y), (p.x, p.y));
        // With facing sight, the angle too: someone who leaves my field (past its side edge and
        // its margin, outside the near ring and its keep metre) fades as they leave it. The
        // distance stays the authority's (a light on them, which the client can't see, may show
        // them further), so this tests the angle only: a glow as far as they are.
        if let (true, Some(f)) = (clear, facing) {
            let d = p.distance(me);
            clear = living_rules::sight::within((me.x, me.y), f.heading, (p.x, p.y), d, &f.senses, d, Some(edge.keep_m));
        }
        if !clear {
            // The memory look leaves a faint figure where they were last seen (`live.rs` holds
            // it once the authority stops sending them); the others fade them out.
            let to = if edge.ghosts() { crate::sightedge::GHOST_LEVEL } else { 1.0 };
            if let Ok(mut f) = fades.get_mut(entity) {
                if f.target < to {
                    f.target = to;
                }
            }
            if let std::collections::hash_map::Entry::Vacant(e) = broke.entry(id) {
                e.insert(now);
                info!("sight field: {id}'s line broke at {:.1} m: fading ahead of the authority", p.distance(me));
            }
        } else if broke.remove(&id).is_some() {
            info!("sight field: {id}'s line cleared again while still sent");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use living_rules::map::Terrain;

    fn open(w: u32) -> Map {
        let mut m = Map::from_chunks(w, w, std::iter::empty());
        for t in m.tiles.iter_mut() {
            *t = Terrain::Grass as u8;
        }
        m
    }

    /// The field is the authority's test at each tile's centre, and a wall's far side is unseen
    /// while the wall itself is seen whole.
    #[test]
    fn field_follows_sight_lines() {
        let mut m = open(128);
        for y in 60..64 {
            for x in 70..72 {
                m.set(x, y, Terrain::Wall);
            }
        }
        let eye = Vec2::new(64.5, 62.0);
        let origin = IVec2::new(0, 0);
        let mut seen = vec![0u8; (SIZE * SIZE) as usize];
        compute(&m, eye, 30.0, origin, &mut seen, None);
        // The texel whose centre is at (x, y) (sim metres, on a quarter).
        let texel = |x: f32, y: f32| (((y / TEXEL) as i32) * SIZE + (x / TEXEL) as i32) as usize;
        for j in 80..168 {
            for i in 80..200 {
                let c = ((i as f32 + 0.5) * TEXEL, (j as f32 + 0.5) * TEXEL);
                let near = (c.0 - eye.x).powi(2) + (c.1 - eye.y).powi(2) <= 900.0;
                let opaque = (70.0..72.0).contains(&c.0) && (60.0..64.0).contains(&c.1);
                if near && !opaque {
                    assert_eq!(seen[(j * SIZE + i) as usize] == 255, m.sight_clear((eye.x, eye.y), c), "texel {i},{j}");
                }
            }
        }
        assert_eq!(seen[texel(75.25, 62.25)], 0, "behind the wall");
        assert_eq!(seen[texel(60.25, 62.25)], 255, "the open side");
        assert_eq!(seen[texel(71.75, 62.25)], 255, "the wall's far column is part of a seen wall");
        assert_eq!(seen[texel(64.25, 95.25)], 0, "beyond the reach");
    }

    fn day_field(heading: f32) -> Facing {
        let field = living_rules::sight::Field { focal_deg: 70.0, side_deg: 110.0, side_share: 1.0 / 3.0, near_m: 3.0, margin_deg: 10.0 };
        Facing { heading, senses: Senses { sight: 11.0, hearing: 9.0, field: Some(field) } }
    }

    /// With facing sight, every texel within sight is the rules' own answer (`sight::sees`, the
    /// authority's test) at four headings; past sight only the focal angle reaches on (to the
    /// radius's soft band), and a wall still hides inside the field.
    #[test]
    fn facing_field_is_the_rules_answer() {
        let mut m = open(128);
        for y in 60..64 {
            m.set(70, y, Terrain::Wall);
        }
        let eye = Vec2::new(64.5, 62.0);
        let reach = 11.0 + MARGIN;
        let mut seen = vec![0u8; (SIZE * SIZE) as usize];
        for heading in [0.0f32, 1.3, -2.2, std::f32::consts::PI] {
            let f = day_field(heading);
            compute(&m, eye, reach, IVec2::ZERO, &mut seen, Some(&f));
            let (mut n, mut front, mut back) = (0, 0, 0);
            for j in 80..170 {
                for i in 80..180 {
                    let c = ((i as f32 + 0.5) * TEXEL, (j as f32 + 0.5) * TEXEL);
                    if !m.passable_missile(c.0, c.1) {
                        continue;
                    }
                    let d = ((c.0 - eye.x).powi(2) + (c.1 - eye.y).powi(2)).sqrt();
                    let got = seen[(j * SIZE + i) as usize] == 255;
                    let off = living_rules::sight::off_facing((eye.x, eye.y), heading, c);
                    if d <= 11.0 {
                        let want = living_rules::sight::sees(&m, (eye.x, eye.y), heading, c, d, &f.senses, 0.0, None);
                        assert_eq!(got, want, "heading {heading}: texel {i},{j} at {d:.2} m, {:.1}° off", off.to_degrees());
                        n += 1;
                    } else if d <= reach {
                        // The band past sight: drawn only within the focal angle.
                        let want = off.abs().to_degrees() <= 70.0 && m.sight_clear((eye.x, eye.y), c);
                        assert_eq!(got, want, "heading {heading}: band texel {i},{j}");
                    } else {
                        assert!(!got);
                    }
                    if got && off.abs().to_degrees() > 110.0 {
                        back += 1;
                        assert!(d <= 3.0, "behind, only the near ring");
                    }
                    if got && off.abs().to_degrees() <= 70.0 {
                        front += 1;
                    }
                }
            }
            assert!(n > 1000 && front > 400 && back > 20, "heading {heading}: {n} compared, {front} ahead, {back} behind");
        }
    }

    /// A field that sees all round (focal 180°) draws exactly what no field draws.
    #[test]
    fn a_round_field_is_the_old_field() {
        let mut m = open(128);
        for y in 60..64 {
            for x in 70..72 {
                m.set(x, y, Terrain::Wall);
            }
        }
        let eye = Vec2::new(64.5, 62.0);
        let (mut a, mut b) = (vec![0u8; (SIZE * SIZE) as usize], vec![0u8; (SIZE * SIZE) as usize]);
        let mut f = day_field(0.7);
        f.senses.field.as_mut().unwrap().focal_deg = 180.0;
        let na = compute(&m, eye, 15.0, IVec2::ZERO, &mut a, None);
        let nb = compute(&m, eye, 15.0, IVec2::ZERO, &mut b, Some(&f));
        assert_eq!((na, a), (nb, b));
    }

    /// The field is worked out again when the heading turns past 2° or the field changes.
    #[test]
    fn turning_recomputes() {
        let f = day_field(0.0);
        assert!(!turned(&None, None));
        assert!(turned(&None, Some(f)) && turned(&Some(f), None));
        assert!(!turned(&Some(f), Some(Facing { heading: 1.9f32.to_radians(), ..f })));
        assert!(turned(&Some(f), Some(Facing { heading: 2.1f32.to_radians(), ..f })));
        assert!(!turned(&Some(Facing { heading: 3.13, ..f }), Some(Facing { heading: -3.13, ..f })), "across ±π is a small turn");
        let mut g = f;
        g.senses.field.as_mut().unwrap().near_m = 2.0;
        assert!(turned(&Some(f), Some(g)));
    }

    /// A shut gate blocks the field as it blocks the authority's sight.
    #[test]
    fn shut_gate_blocks() {
        let mut m = open(128);
        for y in 0..128 {
            if y != 62 {
                m.set(70, y, Terrain::Wall);
            }
        }
        let eye = Vec2::new(64.5, 62.5);
        let mut seen = vec![0u8; (SIZE * SIZE) as usize];
        compute(&m, eye, 30.0, IVec2::ZERO, &mut seen, None);
        let k = (125 * SIZE + 150) as usize; // (75.25, 62.75)
        assert_eq!(seen[k], 255, "through the open gate");
        m.set_blocked([62 * 128 + 70].into_iter().collect());
        compute(&m, eye, 30.0, IVec2::ZERO, &mut seen, None);
        assert_eq!(seen[k], 0, "the gate shut");
    }
}
