//! Scripted expeditions on the island (look-dev): your character follows a route at a set speed,
//! photographs it, and measures it (docs/FIRST_WORLD.md, "Expedition").
//!
//! `LIVING_GAME_ROUTE=<route>[@<speed>]` with `LIVING_GAME_LOOKDEV=1 LIVING_GAME_ENV=island`:
//! - `road:<place>><place>[>…]`: along `Land::roads`, the shortest way on the road graph between
//!   settlement plazas, one leg per `>`. Places: `town`, `giants`, `small`, `village<N>` (1-based,
//!   in settlement order), `farvillage` (the village furthest from the town by road) and
//!   `shore` (the town's landing).
//! - `points:<x>,<z>;<x>,<z>;…`: straight segments between waypoints (metres).
//! - `regions`: a loop from the start through one region centre of every land region kind (the
//!   peaks' centre moves to the nearest walkable ground, the beach's to the water's edge), and
//!   back. Off-road, in straight segments.
//!
//! Speed: `walk` (1.4 m/s, the look-dev's walk clip), `run` (3.6), `rules-walk` (2.6),
//! `rules-run` (3.9) or a number; default `walk`.
//!
//! The route sets the direction in `envs::walk`, which keeps its slide-on-blocked walking. When
//! the route makes no progress for `LIVING_GAME_ROUTE_STUCK_S` (default 4 s), that place is a
//! stuck point: it is photographed, and a detour is found with `Map::path` to the route 30–240 m
//! ahead (a teleport only if none is found). The camera turns to look along the way.
//!
//! Photographs (`LIVING_GAME_ROUTE_PHOTO_M`, default every 150 m, and at landmarks: settlement
//! plazas, lake shores, peaks' foothills, the spirit grove, fords and bridges, the coast; also on
//! stuck points, long slides and steep climbs): the game camera, then a vista
//! (`LIVING_GAME_ROUTE_VISTA=PITCH:DISTANCE:FOV`, default 16:48:55) toward the landmark or along
//! the way. You stop for the vista; that time is not route time.
//!
//! Output in `LIVING_GAME_ROUTE_OUT` (default `LIVING_GAME_TOUR`, else `/tmp/route`): photos,
//! `track.jsonl` (one line a second), `summary.json` (per leg: time, distances, estimates, stuck
//! points, slides, grades, frame times and the worst frames with where they happened). A log
//! line every 3 s gives position, region, speed and frame time.
//!
//! Headless runs ride on the tour's headless mode: set `LIVING_GAME_TOUR=<dir>`,
//! `LIVING_GAME_TOUR_ONLY=island` and `LIVING_GAME_TOUR_SHOTS=default`; this module holds the
//! tour's exit until the route ends. `LIVING_GAME_FPS_CAP=0` measures real frame cost.
//! `LIVING_GAME_ROUTE_DEBUG=1` logs every frame's position, aim and progress.

use crate::camera::{Cam, Rig, View};
use crate::envs::Roam;
use crate::island::Island;
use bevy::ecs::message::Messages;
use bevy::prelude::*;
use bevy::time::Real;
use living_rules::land::{Land, RegionKind, SiteKind};
use living_rules::map::Terrain;
use living_rules::settle::{CrossingKind, RoadEnd};
use serde_json::{json, Value};
use std::collections::{BinaryHeap, HashMap, HashSet, VecDeque};
use std::io::Write;
use std::path::PathBuf;

/// What `envs::walk` reads: direction, running (for the clip) and speed (m/s), while a route runs.
#[derive(Resource, Default)]
pub struct Steer(pub Option<(Vec2, bool, f32)>);

pub struct RoutePlugin;

impl Plugin for RoutePlugin {
    fn build(&self, app: &mut App) {
        let Some(spec) = std::env::var("LIVING_GAME_ROUTE").ok().filter(|s| !s.is_empty()) else { return };
        if !crate::lookdev::enabled() {
            return;
        }
        app.insert_resource(Steer::default())
            .insert_resource(Expedition::new(&spec))
            .add_systems(Update, follow.after(crate::envs::switch).before(crate::envs::walk))
            .add_systems(Last, hold_exit);
    }
}

fn env_f(k: &str, d: f32) -> f32 {
    std::env::var(k).ok().and_then(|v| v.parse().ok()).unwrap_or(d)
}

fn speed_of(s: &str) -> f32 {
    match s {
        "run" => crate::lookdev::RUN_CLIP_SPEED,
        "rules-walk" => 2.6,
        "rules-run" => 3.9,
        "walk" | "" => crate::lookdev::WALK_CLIP_SPEED,
        n => n.parse().unwrap_or(crate::lookdev::WALK_CLIP_SPEED),
    }
}

// ---------------------------------------------------------------------------------------------
// Planning: road graph, places, the region loop.

fn v(p: (f32, f32)) -> Vec2 {
    Vec2::new(p.0, p.1)
}

/// Every road's centre line as one graph: consecutive points, ends joined to the road they meet,
/// to nearby points of other roads, and to their settlement's plaza centre.
struct Graph {
    pts: Vec<Vec2>,
    adj: Vec<Vec<(usize, f32)>>,
    /// Plaza-centre node per settlement.
    plaza: Vec<usize>,
}

impl Graph {
    fn new(land: &Land) -> Self {
        let mut pts = Vec::new();
        let mut base = Vec::new();
        for r in &land.roads {
            base.push(pts.len());
            pts.extend(r.points.iter().map(|p| v(*p)));
        }
        let mut plaza = Vec::new();
        for s in &land.settlements {
            plaza.push(pts.len());
            pts.push(v(s.plaza.centre));
        }
        let mut adj = vec![Vec::new(); pts.len()];
        let link = |adj: &mut Vec<Vec<(usize, f32)>>, a: usize, b: usize| {
            let d = pts[a].distance(pts[b]);
            adj[a].push((b, d));
            adj[b].push((a, d));
        };
        for (ri, r) in land.roads.iter().enumerate() {
            for i in 1..r.points.len() {
                link(&mut adj, base[ri] + i - 1, base[ri] + i);
            }
        }
        let nearest_on = |ri: usize, p: Vec2| (0..land.roads[ri].points.len()).map(|i| base[ri] + i).min_by(|a, b| pts[*a].distance(p).total_cmp(&pts[*b].distance(p)));
        for (ri, r) in land.roads.iter().enumerate() {
            if r.points.is_empty() {
                continue;
            }
            for (k, end) in r.ends.iter().enumerate() {
                let node = if k == 0 { base[ri] } else { base[ri] + r.points.len() - 1 };
                let p = pts[node];
                match *end {
                    RoadEnd::Road(o) if (o as usize) < land.roads.len() => {
                        if let Some(n) = nearest_on(o as usize, p) {
                            link(&mut adj, node, n);
                        }
                    }
                    RoadEnd::Plaza(s) if (s as usize) < plaza.len() => link(&mut adj, node, plaza[s as usize]),
                    RoadEnd::Site(i) => {
                        if let Some(s) = land.settlements.iter().position(|s| s.site == i) {
                            link(&mut adj, node, plaza[s]);
                        }
                    }
                    _ => {}
                }
                // Any other road's point within 3 m (junctions the end list does not name).
                for (oi, o) in land.roads.iter().enumerate() {
                    if oi == ri {
                        continue;
                    }
                    for (j, q) in o.points.iter().enumerate() {
                        if p.distance(v(*q)) < 3.0 {
                            link(&mut adj, node, base[oi] + j);
                        }
                    }
                }
            }
        }
        Self { pts, adj, plaza }
    }

    /// Shortest path (Dijkstra on length) between two nodes, as points.
    fn path(&self, a: usize, b: usize) -> Option<(Vec<Vec2>, f32)> {
        let mut dist = vec![f32::INFINITY; self.pts.len()];
        let mut prev = vec![usize::MAX; self.pts.len()];
        let mut heap = BinaryHeap::new();
        dist[a] = 0.0;
        heap.push(std::cmp::Reverse(((0.0f32).to_bits(), a)));
        while let Some(std::cmp::Reverse((dbits, n))) = heap.pop() {
            let d = f32::from_bits(dbits);
            if d > dist[n] {
                continue;
            }
            if n == b {
                break;
            }
            for &(m, w) in &self.adj[n] {
                let nd = d + w;
                if nd < dist[m] {
                    dist[m] = nd;
                    prev[m] = n;
                    // Non-negative floats order like their bits.
                    heap.push(std::cmp::Reverse((nd.to_bits(), m)));
                }
            }
        }
        if !dist[b].is_finite() {
            return None;
        }
        let mut out = vec![self.pts[b]];
        let mut n = b;
        while n != a {
            n = prev[n];
            out.push(self.pts[n]);
        }
        out.reverse();
        out.dedup_by(|x, y| x.distance(*y) < 0.05);
        Some((out, dist[b]))
    }
}

fn kind_name(k: SiteKind) -> &'static str {
    match k {
        SiteKind::Town => "town",
        SiteKind::Village => "village",
        SiteKind::Giants => "giants",
        SiteKind::SmallFolk => "small",
        SiteKind::Cave => "cave",
    }
}

/// Settlement names: `town`, `giants`, `small`, `village1`…, `cave1`….
fn settlement_names(land: &Land) -> Vec<String> {
    let mut count: HashMap<&str, usize> = HashMap::new();
    land.settlements
        .iter()
        .map(|s| {
            let k = kind_name(s.kind);
            let n = count.entry(k).or_default();
            *n += 1;
            if matches!(s.kind, SiteKind::Village | SiteKind::Cave) {
                format!("{k}{n}")
            } else {
                k.to_string()
            }
        })
        .collect()
}

/// A graph node for a place name.
fn place_node(land: &Land, g: &Graph, names: &[String], name: &str) -> Result<usize, String> {
    let town = names.iter().position(|n| n == "town").ok_or("no town")?;
    if name == "farvillage" {
        return land
            .settlements
            .iter()
            .enumerate()
            .filter(|(_, s)| s.kind == SiteKind::Village)
            .filter_map(|(i, _)| g.path(g.plaza[town], g.plaza[i]).map(|(_, d)| (i, d)))
            .max_by(|a, b| a.1.total_cmp(&b.1))
            .map(|(i, _)| g.plaza[i])
            .ok_or_else(|| "no village reachable by road".into());
    }
    if name == "shore" {
        let r = land.roads.iter().enumerate().find_map(|(ri, r)| r.ends.iter().position(|e| *e == RoadEnd::Shore).map(|k| (ri, k))).ok_or("no shore road")?;
        let p = if r.1 == 0 { land.roads[r.0].points[0] } else { *land.roads[r.0].points.last().unwrap() };
        return g.pts.iter().position(|q| q.distance(v(p)) < 0.01).ok_or_else(|| "shore point missing".into());
    }
    names.iter().position(|n| n == name).map(|i| g.plaza[i]).ok_or_else(|| format!("no place {name} (have {}, farvillage, shore)", names.join(", ")))
}

fn walkable(land: &Land, p: Vec2) -> bool {
    let s = land.size as f32;
    p.x > 0.5 && p.y > 0.5 && p.x < s - 0.5 && p.y < s - 0.5 && land.map.at(p.x, p.y).walkable()
}

/// Nearest point to `c` (searching outward to `r` m) that is walkable and passes `ok`.
fn nearest(land: &Land, c: Vec2, r: f32, ok: &dyn Fn(Vec2) -> bool) -> Option<Vec2> {
    let mut d = 0.0;
    while d <= r {
        let n = ((d * std::f32::consts::TAU / 2.0).ceil() as usize).max(1);
        for k in 0..n {
            let a = k as f32 / n as f32 * std::f32::consts::TAU;
            let p = c + Vec2::new(a.cos(), a.sin()) * d;
            if walkable(land, p) && ok(p) {
                return Some(p);
            }
        }
        d += 2.0;
    }
    None
}

/// One region centre of every land kind, nearest first from `start` (greedy), and back.
fn region_loop(land: &Land, start: Vec2) -> Vec<(String, Vec2)> {
    use RegionKind::*;
    let mut left: Vec<RegionKind> = vec![Beach, Meadow, Forest, OldForest, SpiritGrove, Wetland, Highland, Peaks];
    let mut out = vec![("start".to_string(), start)];
    let mut at = start;
    let coast = |p: Vec2| (0..8).any(|k| {
        let a = k as f32 * std::f32::consts::FRAC_PI_4;
        let q = p + Vec2::new(a.cos(), a.sin()) * 6.0;
        land.map.at(q.x, q.y) == Terrain::Water && land.kind_at(q.x, q.y) == Sea
    });
    while !left.is_empty() {
        let best = land
            .regions
            .iter()
            .filter(|r| left.contains(&r.kind) && r.land_m2 > 2_000.0)
            .min_by(|a, b| v(a.centre).distance(at).total_cmp(&v(b.centre).distance(at)));
        let Some(r) = best else { break };
        left.retain(|k| *k != r.kind);
        let c = v(r.centre);
        let p = match r.kind {
            Beach => nearest(land, c, 400.0, &coast).or_else(|| nearest(land, c, 300.0, &|_| true)),
            _ => nearest(land, c, 300.0, &|_| true),
        };
        if let Some(p) = p {
            out.push((r.kind.id().to_string(), p));
            at = p;
        }
    }
    out.push(("start".to_string(), start));
    out
}

/// A planned leg: names, waypoints and the planned length.
#[derive(Clone)]
struct Plan {
    from: String,
    to: String,
    points: Vec<Vec2>,
    on_road: bool,
}

fn plan(land: &Land, spec: &str, start: Vec2) -> Result<Vec<Plan>, String> {
    if let Some(list) = spec.strip_prefix("road:") {
        let g = Graph::new(land);
        let names = settlement_names(land);
        let places: Vec<&str> = list.split('>').map(str::trim).collect();
        let mut legs = Vec::new();
        for w in places.windows(2) {
            let (a, b) = (place_node(land, &g, &names, w[0])?, place_node(land, &g, &names, w[1])?);
            let (points, _) = g.path(a, b).ok_or_else(|| format!("no road from {} to {}", w[0], w[1]))?;
            let label = |n: &str, node: usize| if n == "farvillage" { names[g.plaza.iter().position(|p| *p == node).unwrap_or(0)].clone() } else { n.to_string() };
            legs.push(Plan { from: label(w[0], a), to: label(w[1], b), points, on_road: true });
        }
        return Ok(legs);
    }
    let stops: Vec<(String, Vec2)> = if let Some(list) = spec.strip_prefix("points:") {
        list.split(';')
            .filter_map(|p| {
                let (x, z) = p.split_once(',')?;
                Some((format!("{},{}", x.trim(), z.trim()), Vec2::new(x.trim().parse().ok()?, z.trim().parse().ok()?)))
            })
            .collect()
    } else if spec == "regions" {
        region_loop(land, start)
    } else {
        return Err(format!("bad route {spec} (want road:…, points:… or regions)"));
    };
    // Straight segments, cut every 10 m so a stuck walker has nearby points to rejoin.
    let dense = |a: Vec2, b: Vec2| {
        let n = (a.distance(b) / 10.0).ceil().max(1.0) as usize;
        (0..=n).map(|k| a.lerp(b, k as f32 / n as f32)).collect::<Vec<_>>()
    };
    Ok(stops.windows(2).map(|w| Plan { from: w[0].0.clone(), to: w[1].0.clone(), points: dense(w[0].1, w[1].1), on_road: false }).collect())
}

fn length(p: &[Vec2]) -> f32 {
    p.windows(2).map(|w| w[0].distance(w[1])).sum()
}

// ---------------------------------------------------------------------------------------------
// Landmarks.

struct Landmark {
    tag: String,
    at: Vec2,
    radius: f32,
    /// Where the vista looks.
    look: Vec2,
}

fn landmarks(land: &Land) -> Vec<Landmark> {
    let names = settlement_names(land);
    let mut out = Vec::new();
    for (i, s) in land.settlements.iter().enumerate() {
        let c = v(s.plaza.centre);
        out.push(Landmark { tag: format!("plaza-{}", names[i]), at: c, radius: (14.0 * s.scale).max(6.0), look: c });
    }
    for (i, l) in land.lakes.iter().enumerate() {
        out.push(Landmark { tag: format!("lake{}", i + 1), at: v(l.centre), radius: l.across_m * 0.5 + 25.0, look: v(l.centre) });
    }
    for (i, r) in land.ranges.iter().enumerate() {
        let s = Vec2::new(r.summit.0, r.summit.1);
        out.push(Landmark { tag: format!("foothills{}", i + 1), at: s, radius: 420.0, look: s });
    }
    for (i, c) in land.crossings.iter().enumerate() {
        let k = if c.kind == CrossingKind::Bridge { "bridge" } else { "ford" };
        out.push(Landmark { tag: format!("{k}{}", i + 1), at: v(c.at), radius: 10.0, look: v(c.at) + v(c.along) * 30.0 });
    }
    for (ri, r) in land.rivers.iter().enumerate() {
        for (fi, f) in r.fords.iter().enumerate() {
            out.push(Landmark { tag: format!("riverford{}-{}", ri + 1, fi + 1), at: v(*f), radius: 8.0, look: v(*f) });
        }
    }
    out
}

// ---------------------------------------------------------------------------------------------
// Measurement.

#[derive(Default)]
struct Frames {
    ms: Vec<f32>,
    /// Worst frames: (ms, where, region, metres into the leg).
    worst: Vec<(f32, Vec2, String, f32)>,
}

impl Frames {
    fn push(&mut self, ms: f32, at: Vec2, region: &str, done: f32) {
        self.ms.push(ms);
        if self.worst.len() < 12 || ms > self.worst.last().map_or(0.0, |w| w.0) {
            self.worst.push((ms, at, region.to_string(), done));
            self.worst.sort_by(|a, b| b.0.total_cmp(&a.0));
            self.worst.truncate(12);
        }
    }

    fn json(&self) -> Value {
        let mut s = self.ms.clone();
        s.sort_by(f32::total_cmp);
        let q = |p: f32| if s.is_empty() { 0.0 } else { s[((s.len() - 1) as f32 * p).round() as usize] };
        let mean = if s.is_empty() { 0.0 } else { s.iter().sum::<f32>() / s.len() as f32 };
        json!({
            "frames": s.len(),
            "mean_ms": r2(mean),
            "p50_ms": r2(q(0.5)),
            "p95_ms": r2(q(0.95)),
            "p99_ms": r2(q(0.99)),
            "worst_ms": r2(q(1.0)),
            "over_33ms": s.iter().filter(|m| **m > 33.3).count(),
            "over_50ms": s.iter().filter(|m| **m > 50.0).count(),
            "worst_frames": self.worst.iter().map(|w| json!({"ms": r2(w.0), "x": r1(w.1.x), "z": r1(w.1.y), "region": w.2, "at_m": r1(w.3)})).collect::<Vec<_>>(),
        })
    }
}

fn r1(x: f32) -> f64 {
    (x as f64 * 10.0).round() / 10.0
}
fn r2(x: f32) -> f64 {
    (x as f64 * 100.0).round() / 100.0
}
fn r3(x: f32) -> f64 {
    (x as f64 * 1000.0).round() / 1000.0
}

/// A run of frames where walking was partly or wholly blocked.
#[derive(Clone)]
struct Slide {
    start: Vec2,
    end: Vec2,
    secs: f32,
    blocked_secs: f32,
    moved: f32,
    region: String,
    photo: Option<String>,
}

/// A stretch climbed at a grade over `STEEP`.
#[derive(Clone)]
struct Steep {
    start: Vec2,
    peak_at: Vec2,
    peak: f32,
    metres: f32,
    region: String,
    photo: Option<String>,
}

const STEEP: f32 = 0.20;

/// One leg as walked.
struct Leg {
    plan: Plan,
    planned_m: f32,
    path: Vec<Vec2>,
    /// Remaining length after each point.
    suffix: Vec<f32>,
    next: usize,
    walk_s: f32,
    pause_s: f32,
    stuck_s: f32,
    flat_m: f32,
    m3d: f32,
    climb_m: f32,
    descent_m: f32,
    best_left: f32,
    progress_t: f32,
    stucks: Vec<Value>,
    /// Where the last stuck point was, and how many in a row were there.
    last_stuck: (Vec2, u32),
    detour_m: f32,
    teleport_m: f32,
    slides: Vec<Slide>,
    slide: Option<Slide>,
    steeps: Vec<Steep>,
    steep: Option<Steep>,
    trail: VecDeque<(f32, f32)>,
    max_up: (f32, Vec2),
    max_down: (f32, Vec2),
    grade_m: [f32; 4],
    off_road_max: f32,
    frames: Frames,
    regions: HashMap<String, f32>,
    outcome: &'static str,
    start_pos: Vec2,
}

impl Leg {
    fn new(plan: Plan) -> Self {
        let planned_m = length(&plan.points);
        let mut l = Leg {
            path: plan.points.clone(),
            planned_m,
            start_pos: plan.points[0],
            plan,
            suffix: Vec::new(),
            next: 1,
            walk_s: 0.0,
            pause_s: 0.0,
            stuck_s: 0.0,
            flat_m: 0.0,
            m3d: 0.0,
            climb_m: 0.0,
            descent_m: 0.0,
            best_left: f32::INFINITY,
            progress_t: 0.0,
            stucks: Vec::new(),
            last_stuck: (Vec2::splat(-1e6), 0),
            detour_m: 0.0,
            teleport_m: 0.0,
            slides: Vec::new(),
            slide: None,
            steeps: Vec::new(),
            steep: None,
            trail: VecDeque::new(),
            max_up: (0.0, Vec2::ZERO),
            max_down: (0.0, Vec2::ZERO),
            grade_m: [0.0; 4],
            off_road_max: 0.0,
            frames: Frames::default(),
            regions: HashMap::new(),
            outcome: "walking",
        };
        l.reindex();
        l
    }

    fn reindex(&mut self) {
        let n = self.path.len();
        self.suffix = vec![0.0; n];
        for i in (0..n.saturating_sub(1)).rev() {
            self.suffix[i] = self.suffix[i + 1] + self.path[i].distance(self.path[i + 1]);
        }
    }

    fn left(&self, pos: Vec2) -> f32 {
        self.path.get(self.next).map_or(0.0, |w| pos.distance(*w) + self.suffix[self.next])
    }

    /// Advance past reached waypoints; the point to walk toward, or None at the end.
    fn aim(&mut self, pos: Vec2, map: &living_rules::map::Map) -> Option<Vec2> {
        let clear = |a: Vec2, b: Vec2| map.line_clear((a.x, a.y), (b.x, b.y));
        while self.next < self.path.len() {
            let w = self.path[self.next];
            let d = pos.distance(w);
            let last = self.next + 1 == self.path.len();
            // Reached: within 2 m when the next point is in clear sight from here; otherwise
            // (a detour's corner) right at it.
            let reach = if last {
                1.2
            } else if clear(pos, self.path[self.next + 1]) {
                2.0
            } else {
                0.3
            };
            if d < reach {
                self.next += 1;
                continue;
            }
            // Passed it: beyond the waypoint along the next segment, and close to that segment.
            if !last {
                let (a, b) = (w, self.path[self.next + 1]);
                let ab = b - a;
                let t = (pos - a).dot(ab) / ab.length_squared().max(1e-6);
                if t > 0.0 && t < 1.0 && (a + ab * t).distance(pos) < 3.0 && clear(pos, b) {
                    self.next += 1;
                    continue;
                }
            }
            break;
        }
        let w = *self.path.get(self.next)?;
        // Look a little ahead on dense road lines, so corners round off as a walker's would.
        if pos.distance(w) < 3.0 {
            if let Some(n) = self.path.get(self.next + 1).filter(|n| clear(pos, **n)) {
                return Some(*n);
            }
        }
        Some(w)
    }

    /// Distance from the planned line (how far a slide or detour took you off the road).
    fn off_line(&self, pos: Vec2) -> f32 {
        self.plan.points.windows(2).map(|w| {
            let ab = w[1] - w[0];
            let t = ((pos - w[0]).dot(ab) / ab.length_squared().max(1e-6)).clamp(0.0, 1.0);
            (w[0] + ab * t).distance(pos)
        }).fold(f32::INFINITY, f32::min)
    }

    fn json(&self) -> Value {
        let straight = self.plan.points[0].distance(*self.plan.points.last().unwrap());
        let speed = |s: f32| if self.walk_s > 0.0 { s / self.walk_s } else { 0.0 };
        let mut regions: Vec<_> = self.regions.iter().collect();
        regions.sort_by(|a, b| b.1.total_cmp(a.1));
        json!({
            "from": self.plan.from, "to": self.plan.to, "on_road": self.plan.on_road, "outcome": self.outcome,
            "start": [r1(self.start_pos.x), r1(self.start_pos.y)], "end": [r1(self.plan.points.last().unwrap().x), r1(self.plan.points.last().unwrap().y)],
            "straight_m": r1(straight), "planned_m": r1(self.planned_m), "walked_flat_m": r1(self.flat_m), "walked_3d_m": r1(self.m3d),
            "climb_m": r1(self.climb_m), "descent_m": r1(self.descent_m),
            "time_s": r1(self.walk_s), "stuck_s": r1(self.stuck_s), "photo_pause_s": r1(self.pause_s),
            "mean_speed_mps": r3(speed(self.flat_m)), "made_good_mps": r3(speed(straight)),
            "detour_m": r1(self.detour_m), "teleport_m": r1(self.teleport_m), "max_off_line_m": r1(self.off_road_max),
            "stucks": self.stucks,
            "slides": self.slides.iter().map(|s| json!({"start": [r1(s.start.x), r1(s.start.y)], "end": [r1(s.end.x), r1(s.end.y)], "secs": r2(s.secs), "blocked_secs": r2(s.blocked_secs), "moved_m": r1(s.moved), "region": s.region, "photo": s.photo})).collect::<Vec<_>>(),
            "steep": self.steeps.iter().map(|s| json!({"start": [r1(s.start.x), r1(s.start.y)], "peak_at": [r1(s.peak_at.x), r1(s.peak_at.y)], "peak_grade": r3(s.peak), "metres": r1(s.metres), "region": s.region, "photo": s.photo})).collect::<Vec<_>>(),
            "max_up_grade": {"grade": r3(self.max_up.0), "x": r1(self.max_up.1.x), "z": r1(self.max_up.1.y)},
            "max_down_grade": {"grade": r3(self.max_down.0), "x": r1(self.max_down.1.x), "z": r1(self.max_down.1.y)},
            "metres_over_grade": {"10%": r1(self.grade_m[0]), "20%": r1(self.grade_m[1]), "30%": r1(self.grade_m[2]), "40%": r1(self.grade_m[3])},
            "regions_m": regions.iter().map(|(k, m)| json!([k, r1(**m)])).collect::<Vec<_>>(),
            "frame_time": self.frames.json(),
        })
    }
}

// ---------------------------------------------------------------------------------------------
// The expedition.

enum Stage {
    /// Waiting for the island, then for it to stream in around the start.
    Loading { since: Option<f32> },
    Walking,
    /// Stopped for a vista: phase 0 waits for the camera, 1 photographs, 2 waits to restore.
    Vista { tag: String, look: Vec2, phase: u8, since: f32 },
    Finishing { since: f32 },
    Done,
}

#[derive(Resource)]
pub struct Expedition {
    spec: String,
    speed: f32,
    out: PathBuf,
    stage: Stage,
    legs: Vec<Leg>,
    leg: usize,
    error: Option<String>,
    marks: Vec<Landmark>,
    fired: HashSet<String>,
    photos: Vec<Value>,
    shot_n: usize,
    last_photo_m: f32,
    total_m: f32,
    track: Option<std::fs::File>,
    heading: f32,
    last_pos: Vec2,
    last_step: Option<(Vec2, f32)>,
    quiet_until: f32,
    log_acc: (f32, f32, u32, f32, f32),
    track_acc: (f32, f32, u32, f32, f32),
    wall_start: Option<std::time::Instant>,
    vista: View,
    photo_every: f32,
    stuck_after: f32,
    seen_kinds: HashSet<&'static str>,
}

impl Expedition {
    fn new(raw: &str) -> Self {
        let (spec, speed) = raw.split_once('@').map_or((raw, "walk"), |(a, b)| (a, b));
        let out = std::env::var("LIVING_GAME_ROUTE_OUT").ok().or_else(|| std::env::var("LIVING_GAME_TOUR").ok()).filter(|s| !s.is_empty()).unwrap_or_else(|| "/tmp/route".into());
        let _ = std::fs::create_dir_all(&out);
        let n: Vec<f32> = std::env::var("LIVING_GAME_ROUTE_VISTA").unwrap_or_default().split(':').filter_map(|x| x.parse().ok()).collect();
        let vista = if n.len() >= 3 { View { pitch: n[0], distance: n[1], fov: n[2] } } else { View { pitch: 16.0, distance: 48.0, fov: 55.0 } };
        Self {
            spec: spec.trim().to_string(),
            speed: speed_of(speed.trim()),
            track: std::fs::File::create(PathBuf::from(&out).join("track.jsonl")).ok(),
            out: PathBuf::from(out),
            stage: Stage::Loading { since: None },
            legs: Vec::new(),
            leg: 0,
            error: None,
            marks: Vec::new(),
            fired: HashSet::new(),
            photos: Vec::new(),
            shot_n: 0,
            last_photo_m: 0.0,
            total_m: 0.0,
            heading: 0.0,
            last_pos: Vec2::ZERO,
            last_step: None,
            quiet_until: 0.0,
            log_acc: (0.0, 0.0, 0, 0.0, 0.0),
            track_acc: (0.0, 0.0, 0, 0.0, 0.0),
            wall_start: None,
            vista,
            photo_every: env_f("LIVING_GAME_ROUTE_PHOTO_M", 150.0),
            stuck_after: env_f("LIVING_GAME_ROUTE_STUCK_S", 4.0),
            seen_kinds: HashSet::new(),
        }
    }

    fn done(&self) -> bool {
        matches!(self.stage, Stage::Done)
    }

    /// Photograph what the camera sees now; returns the file name.
    fn shoot(&mut self, commands: &mut Commands, target: Option<&crate::capture::Target>, tag: &str, kind: &str, at: Vec2, region: &str, now: f32) -> String {
        let name = format!("{:03}-{}-{tag}-{kind}.png", self.shot_n, self.leg + 1);
        crate::capture::shot(commands, target, self.out.join(&name));
        self.shot_n += 1;
        self.photos.push(json!({"file": name, "leg": self.leg + 1, "tag": tag, "view": kind, "x": r1(at.x), "z": r1(at.y), "region": region, "at_m": r1(self.total_m)}));
        // A photograph's read-back costs a frame or two; keep it out of the frame statistics.
        self.quiet_until = now + 0.5;
        name
    }

    fn write_summary(&self, host: &str) {
        let legs: Vec<Value> = self.legs.iter().map(Leg::json).collect();
        let mut all = Frames::default();
        for l in &self.legs {
            all.ms.extend(&l.frames.ms);
            all.worst.extend(l.frames.worst.iter().cloned());
        }
        all.worst.sort_by(|a, b| b.0.total_cmp(&a.0));
        all.worst.truncate(12);
        let time: f32 = self.legs.iter().map(|l| l.walk_s).sum();
        let flat: f32 = self.legs.iter().map(|l| l.flat_m).sum();
        let planned: f32 = self.legs.iter().map(|l| l.planned_m).sum();
        let straight: f32 = self.legs.iter().map(|l| l.plan.points[0].distance(*l.plan.points.last().unwrap())).sum();
        let s = json!({
            "route": self.spec, "speed_mps": self.speed, "host": host, "error": self.error,
            "size": crate::capture::size().to_array(), "fps_cap": std::env::var("LIVING_GAME_FPS_CAP").unwrap_or_else(|_| "60".into()),
            "wall_s": self.wall_start.map(|w| r1(w.elapsed().as_secs_f32())),
            "time_s": r1(time), "walked_flat_m": r1(flat), "planned_m": r1(planned), "straight_m": r1(straight),
            "estimate_straight_s": r1(straight / self.speed), "estimate_planned_s": r1(planned / self.speed),
            "frame_time": all.json(),
            "legs": legs,
            "photos": self.photos,
        });
        let _ = std::fs::write(self.out.join("summary.json"), serde_json::to_string_pretty(&s).unwrap_or_default());
    }
}

/// Hold the tour's exit (and any other) until the route ends.
fn hold_exit(ex: Res<Expedition>, mut exits: ResMut<Messages<AppExit>>) {
    if !ex.done() && crate::capture::scripted() {
        exits.clear();
    }
}

fn yaw_toward(d: Vec2) -> f32 {
    // Yaw 0 looks north (−z); positive turns clockwise seen from above (camera.rs).
    d.x.atan2(-d.y).to_degrees()
}

fn ease_angle(from: f32, to: f32, k: f32) -> f32 {
    from + ((to - from + 540.0).rem_euclid(360.0) - 180.0) * k
}

fn hostname() -> String {
    std::process::Command::new("hostname").output().ok().map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default()
}

/// Steer along the route, measure, photograph, and finish.
#[allow(clippy::too_many_arguments)]
fn follow(
    mut commands: Commands,
    mut ex: ResMut<Expedition>,
    mut steer: ResMut<Steer>,
    mut roam: ResMut<Roam>,
    mut cam: ResMut<Cam>,
    island: Option<Res<Island>>,
    time: Res<Time>,
    real: Res<Time<Real>>,
    target: Option<Res<crate::capture::Target>>,
    mut exit: MessageWriter<AppExit>,
) {
    let ex = &mut *ex;
    let now = time.elapsed_secs();
    let dt = time.delta_secs();
    let frame_ms = real.delta_secs() * 1000.0;
    let Some(island) = island else {
        steer.0 = None;
        return;
    };
    let land = island.land.clone();
    let pos = roam.pos;
    let region = land.kind_at(pos.x, pos.y).id();
    let target = target.as_deref();
    match ex.stage {
        Stage::Loading { since } => {
            steer.0 = Some((Vec2::ZERO, false, 0.0));
            let Some(since) = since else {
                match plan(&land, &ex.spec, island.start) {
                    Ok(legs) if !legs.is_empty() => {
                        info!(
                            "route: {} at {:.1} m/s: {}",
                            ex.spec,
                            ex.speed,
                            legs.iter().map(|l| format!("{} → {} {:.0} m ({:.0} m straight)", l.from, l.to, length(&l.points), l.points[0].distance(*l.points.last().unwrap()))).collect::<Vec<_>>().join(", ")
                        );
                        // The planned lines, for maps and checks.
                        let lines: Vec<Value> = legs.iter().map(|l| json!({"from": l.from, "to": l.to, "points": l.points.iter().map(|p| [r1(p.x), r1(p.y)]).collect::<Vec<_>>()})).collect();
                        let roads: Vec<Value> = land.roads.iter().map(|r| json!({"class": format!("{:?}", r.class), "width_m": r.width_m, "points": r.points.iter().map(|p| [r1(p.0), r1(p.1)]).collect::<Vec<_>>()})).collect();
                        let names = settlement_names(&land);
                        let places: Vec<Value> = land.settlements.iter().zip(&names).map(|(s, n)| json!({"name": n, "x": r1(s.plaza.centre.0), "z": r1(s.plaza.centre.1)})).collect();
                        // A coarse map: region kind ids, `~` water, `^` rock, every 8 m.
                        let n = land.size / 8;
                        let grid: Vec<String> = (0..n)
                            .map(|j| {
                                (0..n)
                                    .map(|i| {
                                        let (x, z) = (i as f32 * 8.0 + 4.0, j as f32 * 8.0 + 4.0);
                                        match land.map.at(x, z) {
                                            Terrain::Water => '~',
                                            Terrain::Rock => '^',
                                            Terrain::Road | Terrain::Wall => '=',
                                            _ => RegionKind::ALL.iter().position(|k| *k == land.kind_at(x, z)).map_or('?', |k| (b'0' + k as u8) as char),
                                        }
                                    })
                                    .collect()
                            })
                            .collect();
                        let plan_json = json!({"size": land.size, "legs": lines, "roads": roads, "settlements": places, "grid_m": 8, "grid": grid, "kinds": RegionKind::ALL.iter().map(|k| k.id()).collect::<Vec<_>>()});
                        let _ = std::fs::write(ex.out.join("plan.json"), serde_json::to_string(&plan_json).unwrap_or_default());
                        roam.pos = legs[0].points[0];
                        ex.last_pos = roam.pos;
                        ex.legs = legs.into_iter().map(Leg::new).collect();
                        ex.marks = landmarks(&land);
                        // The start photograph covers landmarks you start inside.
                        let s0 = ex.legs[0].plan.points[0];
                        ex.fired = ex.marks.iter().filter(|m| s0.distance(m.at) < m.radius).map(|m| m.tag.clone()).collect();
                        let p = &ex.legs[0].plan.points;
                        ex.heading = yaw_toward(p[1] - p[0]);
                        ex.stage = Stage::Loading { since: Some(now) };
                    }
                    other => {
                        let e = other.err().unwrap_or_else(|| "empty route".into());
                        error!("route: {e}");
                        ex.error = Some(e);
                        ex.stage = Stage::Finishing { since: now };
                    }
                }
                return;
            };
            // Let the start stream in and the tour's first photograph pass (the tour turns the
            // view north at its start).
            cam.set_yaw(ex.heading);
            if now - since > 8.0 {
                ex.wall_start = Some(std::time::Instant::now());
                ex.legs[0].progress_t = now;
                ex.stage = Stage::Walking;
                let mark = ex.legs[0].plan.from.clone();
                ex.shoot(&mut commands, target, &format!("start-{mark}"), "game", pos, region, now);
            }
            return;
        }
        Stage::Vista { ref tag, look, phase, since } => {
            steer.0 = Some((Vec2::ZERO, false, 0.0));
            let tag = tag.clone();
            if ex.leg < ex.legs.len() {
                ex.legs[ex.leg].pause_s += dt;
            }
            match phase {
                0 => {
                    cam.rig.sight_bound = false;
                    cam.rig.view = ex.vista;
                    let d = look - pos;
                    cam.set_yaw(if d.length() > 2.0 { yaw_toward(d) } else { ex.heading });
                    ex.stage = Stage::Vista { tag, look, phase: 1, since: now };
                }
                1 if now - since > 0.9 => {
                    ex.shoot(&mut commands, target, &tag, "vista", pos, region, now);
                    ex.stage = Stage::Vista { tag, look, phase: 2, since: now };
                }
                2 if now - since > 0.35 => {
                    cam.rig.view = Rig::default().view;
                    cam.rig.sight_bound = true;
                    cam.set_yaw(ex.heading);
                    ex.stage = Stage::Vista { tag, look, phase: 3, since: now };
                }
                3 if now - since > 0.5 => {
                    ex.quiet_until = now + 0.3;
                    ex.stage = Stage::Walking;
                    ex.last_pos = roam.pos;
                    ex.last_step = None;
                    if ex.leg < ex.legs.len() {
                        ex.legs[ex.leg].progress_t = now;
                    }
                }
                _ => {}
            }
            return;
        }
        Stage::Finishing { since } => {
            steer.0 = Some((Vec2::ZERO, false, 0.0));
            if now - since > 1.5 {
                ex.write_summary(&hostname());
                info!("route: done; summary in {}", ex.out.join("summary.json").display());
                ex.stage = Stage::Done;
                exit.write(AppExit::Success);
            }
            return;
        }
        Stage::Done => {
            steer.0 = None;
            return;
        }
        Stage::Walking => {}
    }

    // ---- Walking: first measure the last frame's step.
    let li = ex.leg;
    let quiet = now < ex.quiet_until;
    let step = pos - ex.last_pos;
    let flat = step.length();
    let y = island.height(pos.x, pos.y);
    let total_before = ex.total_m;
    {
        let leg = &mut ex.legs[li];
        leg.walk_s += dt;
        if flat < 20.0 {
            let y0 = island.height(ex.last_pos.x, ex.last_pos.y);
            let dy = y - y0;
            leg.flat_m += flat;
            leg.m3d += (flat * flat + dy * dy).sqrt();
            if dy > 0.0 {
                leg.climb_m += dy;
            } else {
                leg.descent_m -= dy;
            }
            *leg.regions.entry(region.to_string()).or_default() += flat;
        }
        // Grade over the last 10 m walked.
        let s = leg.flat_m;
        leg.trail.push_back((s, y));
        while leg.trail.len() > 2 && s - leg.trail[1].0 >= 10.0 {
            leg.trail.pop_front();
        }
        let (s0, y0) = leg.trail[0];
        if s - s0 >= 9.5 && flat > 0.0 {
            let g = (y - y0) / (s - s0);
            if g > leg.max_up.0 {
                leg.max_up = (g, pos);
            }
            if g < leg.max_down.0 {
                leg.max_down = (g, pos);
            }
            for (k, lim) in [0.10, 0.20, 0.30, 0.40].iter().enumerate() {
                if g.abs() > *lim {
                    leg.grade_m[k] += flat;
                }
            }
            if g > STEEP {
                let st = leg.steep.get_or_insert(Steep { start: pos, peak_at: pos, peak: g, metres: 0.0, region: region.to_string(), photo: None });
                st.metres += flat;
                if g > st.peak {
                    st.peak = g;
                    st.peak_at = pos;
                }
            } else if let Some(st) = leg.steep.take() {
                if st.metres >= 5.0 {
                    leg.steeps.push(st);
                }
            }
        }
        leg.off_road_max = leg.off_road_max.max(leg.off_line(pos));
        // Slides: the last step fell short of what was asked (walk.rs slid along a block).
        if let Some((want, want_dt)) = ex.last_step {
            let asked = want.length();
            if asked > 1e-4 {
                let ratio = flat / asked;
                let blocked = ratio < 0.05;
                if ratio < 0.85 {
                    let sl = leg.slide.get_or_insert(Slide { start: pos, end: pos, secs: 0.0, blocked_secs: 0.0, moved: 0.0, region: region.to_string(), photo: None });
                    sl.secs += want_dt;
                    sl.end = pos;
                    sl.moved += flat;
                    if blocked {
                        sl.blocked_secs += want_dt;
                    }
                } else if let Some(sl) = leg.slide.take() {
                    if sl.secs >= 0.75 {
                        leg.slides.push(sl);
                    }
                }
            }
        }
        if !quiet {
            leg.frames.push(frame_ms, pos, region, leg.flat_m);
        }
    }
    ex.total_m = total_before + if flat < 20.0 { flat } else { 0.0 };
    ex.last_pos = pos;

    // Photograph a long slide or a steep climb once, as it happens.
    let want_slide_photo = ex.legs[li].slide.as_ref().is_some_and(|s| s.secs > 2.0 && s.photo.is_none());
    if want_slide_photo {
        let name = ex.shoot(&mut commands, target, "slide", "game", pos, region, now);
        ex.legs[li].slide.as_mut().unwrap().photo = Some(name);
    }
    let want_steep_photo = ex.legs[li].steep.as_ref().is_some_and(|s| s.peak > 0.30 && s.photo.is_none()) && ex.legs[li].steeps.iter().filter(|s| s.photo.is_some()).count() < 3;
    if want_steep_photo {
        let name = ex.shoot(&mut commands, target, "steep", "game", pos, region, now);
        ex.legs[li].steep.as_mut().unwrap().photo = Some(name);
    }

    // Logging: every 3 s to the log, every second to the track.
    for acc in [&mut ex.log_acc, &mut ex.track_acc] {
        acc.0 += frame_ms;
        acc.1 = acc.1.max(frame_ms);
        acc.2 += 1;
        acc.3 += dt;
        acc.4 += flat;
    }
    if ex.track_acc.3 >= 1.0 {
        let a = ex.track_acc;
        let leg = &ex.legs[li];
        let line = json!({"t": r1(leg.walk_s), "leg": li + 1, "x": r1(pos.x), "z": r1(pos.y), "y": r1(y), "region": region, "speed": r2(a.4 / a.3), "frame_mean_ms": r2(a.0 / a.2 as f32), "frame_worst_ms": r2(a.1), "done_m": r1(leg.flat_m), "left_m": r1(leg.left(pos))});
        if let Some(f) = ex.track.as_mut() {
            let _ = writeln!(f, "{line}");
        }
        ex.track_acc = (0.0, 0.0, 0, 0.0, 0.0);
    }
    if ex.log_acc.3 >= 3.0 {
        let a = ex.log_acc;
        let leg = &ex.legs[li];
        info!(
            "route: leg {} {}→{} t {:.0} s, {:.0} m done, {:.0} m left; at ({:.0}, {:.0}) y {:.0} {region}; {:.2} m/s; frame mean {:.1} ms, worst {:.1} ms",
            li + 1,
            leg.plan.from,
            leg.plan.to,
            leg.walk_s,
            leg.flat_m,
            leg.left(pos),
            pos.x,
            pos.y,
            y,
            a.4 / a.3,
            a.0 / a.2 as f32,
            a.1
        );
        ex.log_acc = (0.0, 0.0, 0, 0.0, 0.0);
    }

    // ---- Landmarks and regular photographs.
    let mut stop: Option<(String, Vec2)> = None;
    if let Some(m) = ex.marks.iter().find(|m| !ex.fired.contains(&m.tag) && pos.distance(m.at) < m.radius) {
        stop = Some((m.tag.clone(), m.look));
    }
    let kind = land.kind_at(pos.x, pos.y);
    let first = |k: RegionKind| kind == k && !ex.seen_kinds.contains(k.id());
    if stop.is_none() {
        if first(RegionKind::SpiritGrove) {
            let c = land.region_at(pos.x, pos.y).centre;
            stop = Some(("spirit-grove".into(), v(c)));
        } else if first(RegionKind::Peaks) {
            stop = Some(("peaks".into(), pos + Vec2::new(ex.heading.to_radians().sin(), -ex.heading.to_radians().cos()) * 50.0));
        } else if first(RegionKind::Beach) {
            stop = Some(("coast".into(), pos));
        }
    }
    ex.seen_kinds.insert(kind.id());
    if stop.is_none() && ex.photo_every > 0.0 && ex.total_m - ex.last_photo_m >= ex.photo_every {
        stop = Some((format!("{:.0}m", ex.total_m), pos));
    }
    if let Some((tag, look)) = stop {
        ex.fired.insert(tag.clone());
        ex.last_photo_m = ex.total_m;
        ex.shoot(&mut commands, target, &tag, "game", pos, region, now);
        if ex.vista.distance > 0.0 {
            ex.stage = Stage::Vista { tag, look, phase: 0, since: now };
            steer.0 = Some((Vec2::ZERO, false, 0.0));
            ex.last_step = None;
            return;
        }
    }

    // ---- Steering.
    let leg = &mut ex.legs[li];
    let Some(aim) = leg.aim(pos, &land.map) else {
        // Leg done.
        if leg.outcome == "walking" {
            leg.outcome = "arrived";
        }
        if let Some(sl) = leg.slide.take().filter(|s| s.secs >= 0.75) {
            leg.slides.push(sl);
        }
        if let Some(st) = leg.steep.take().filter(|s| s.metres >= 5.0) {
            leg.steeps.push(st);
        }
        info!("route: leg {} {} → {} arrived in {:.0} s ({:.0} m, {:.0} m planned)", li + 1, leg.plan.from, leg.plan.to, leg.walk_s, leg.flat_m, leg.planned_m);
        let name = format!("arrive-{}", leg.plan.to);
        ex.shoot(&mut commands, target, &name, "game", pos, region, now);
        ex.leg += 1;
        if ex.leg >= ex.legs.len() {
            ex.stage = Stage::Finishing { since: now };
            steer.0 = Some((Vec2::ZERO, false, 0.0));
        } else {
            let start = ex.legs[ex.leg].plan.points[0];
            if start.distance(pos) > 5.0 {
                roam.pos = start;
            }
            ex.last_pos = roam.pos;
            ex.last_step = None;
            ex.legs[ex.leg].progress_t = now;
            ex.legs[ex.leg].start_pos = roam.pos;
        }
        return;
    };
    // Progress and stuck points.
    let left = leg.left(pos);
    if left < leg.best_left - 1.0 {
        leg.best_left = left;
        leg.progress_t = now;
    }
    let timeout = leg.walk_s > 3.0 * leg.planned_m / ex.speed + 180.0;
    if now - leg.progress_t > ex.stuck_after || timeout {
        leg.stuck_s += now - leg.progress_t;
        // Stuck again where a detour began: that detour cannot be walked; move on.
        let again = leg.last_stuck.0.distance(pos) < 3.0;
        leg.last_stuck = (pos, if again { leg.last_stuck.1 + 1 } else { 0 });
        let give_up = timeout || leg.last_stuck.1 >= 2;
        // Rejoin the route 30, 60, 120 or 240 m ahead, by the map's own path finding.
        let mut found = None;
        for ahead in [30.0f32, 60.0, 120.0, 240.0] {
            let Some(k) = (leg.next..leg.path.len()).find(|&k| leg.left(pos) - leg.suffix[k] >= ahead.min(left - 0.5) && walkable(&land, leg.path[k])) else { continue };
            let t = std::time::Instant::now();
            let p = land.map.path((pos.x, pos.y), (leg.path[k].x, leg.path[k].y), 400_000);
            let ms = t.elapsed().as_secs_f32() * 1000.0;
            if let Some(p) = p {
                found = Some((k, p.into_iter().map(v).collect::<Vec<_>>(), ahead, ms));
                break;
            }
        }
        let region_s = region.to_string();
        let (how, rejoin) = match found {
            Some((k, detour, ahead, ms)) if !give_up => {
                let dl = length(&[vec![pos], detour.clone()].concat());
                leg.detour_m += dl;
                let rest: Vec<Vec2> = leg.path[k + 1..].to_vec();
                leg.path = [vec![pos], detour, rest].concat();
                leg.next = 1;
                leg.reindex();
                (format!("detour {:.0} m to rejoin {:.0} m ahead (path search {:.0} ms)", dl, ahead, ms), leg.path.get(leg.path.len().saturating_sub(1)).copied())
            }
            _ => {
                // No way round (or the leg timed out): carry on from further along.
                let k = (leg.next..leg.path.len()).find(|&k| leg.left(pos) - leg.suffix[k] >= 60.0f32.min(left)).unwrap_or(leg.path.len() - 1);
                let to = nearest(&land, leg.path[k], 40.0, &|_| true).unwrap_or(leg.path[k]);
                leg.teleport_m += to.distance(pos);
                leg.next = k + 1;
                roam.pos = to;
                ex.last_pos = to;
                let why = if timeout {
                    "leg timed out;"
                } else if found.is_some() {
                    "detours failed here three times;"
                } else {
                    "no path round;"
                };
                (format!("{why} teleported {:.0} m ahead", to.distance(pos)), Some(to))
            }
        };
        warn!("route: stuck at ({:.0}, {:.0}) {region_s}, {how}", pos.x, pos.y);
        let photo = if again { None } else { Some(ex.shoot(&mut commands, target, "stuck", "game", pos, region, now)) };
        let leg = &mut ex.legs[li];
        leg.stucks.push(json!({"x": r1(pos.x), "z": r1(pos.y), "y": r1(y), "region": region_s, "at_m": r1(leg.flat_m), "resolution": how, "rejoin": rejoin.map(|r| [r1(r.x), r1(r.y)]), "photo": photo}));
        leg.progress_t = now;
        leg.best_left = leg.left(roam.pos);
        ex.quiet_until = now + 0.5;
        if timeout {
            leg.outcome = "timed out";
            leg.next = leg.path.len();
        }
        ex.last_step = None;
        steer.0 = Some((Vec2::ZERO, false, 0.0));
        return;
    }
    let d = (aim - pos).normalize_or_zero();
    if std::env::var("LIVING_GAME_ROUTE_DEBUG").is_ok() {
        info!("route debug: at ({:.2}, {:.2}) aim ({:.2}, {:.2}) next {}/{} left {:.1} best {:.1} tile {:?}", pos.x, pos.y, aim.x, aim.y, leg.next, leg.path.len(), left, leg.best_left, land.map.at(pos.x, pos.y));
    }
    steer.0 = Some((d, ex.speed > 3.0, ex.speed));
    ex.last_step = Some((d * ex.speed * dt, dt));
    // Look along the way, as a player turning the view would.
    if d != Vec2::ZERO {
        ex.heading = ease_angle(ex.heading, yaw_toward(d), 1.0 - (-dt * 1.5).exp());
        cam.set_yaw(ex.heading);
    }
}
