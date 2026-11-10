//! The way between places along a land's roads (docs/SEEDED_LIVES.md).
//!
//! A walk across the island is too long for one tile search (`Map::path` gives up after its
//! expansion budget, a few hundred metres on open ground; a search across the island costs tens
//! of milliseconds). People who know a way know it as the road and its stages. [`Ways`] is the
//! road network of a generated [`Land`] as a graph of road points; [`Ways::route`] follows it
//! from one point to another, and [`stages`] cuts a route into evenly spaced points, each leg
//! short enough for an ordinary walk. World creation uses it once, to give people who travel a
//! known way the stages of it as remembered places; nothing per tick reads it.

use crate::land::Land;
use crate::settle::V2;
use std::cmp::Ordering;
use std::collections::BinaryHeap;

/// Road ends and points this close to a point of another road are joined to it (metres).
const JOIN_M: f32 = 8.0;
/// A start or goal this far from every road point does not use the roads.
const REACH_M: f32 = 120.0;
/// Bucket size for finding road points near a point.
const CELL_M: f32 = 32.0;

pub struct Ways {
    pts: Vec<V2>,
    /// Whether a point lies on a trunk road (between settlements, not a street or a plaza).
    trunk: Vec<bool>,
    adj: Vec<Vec<(u32, f32)>>,
    cells: std::collections::HashMap<(i32, i32), Vec<u32>>,
}

fn d(a: V2, b: V2) -> f32 {
    (a.0 - b.0).hypot(a.1 - b.1)
}

fn cell(p: V2) -> (i32, i32) {
    ((p.0 / CELL_M).floor() as i32, (p.1 / CELL_M).floor() as i32)
}

#[derive(PartialEq)]
struct Open(f32, u32);
impl Eq for Open {}
impl Ord for Open {
    fn cmp(&self, o: &Self) -> Ordering {
        o.0.total_cmp(&self.0).then(o.1.cmp(&self.1))
    }
}
impl PartialOrd for Open {
    fn partial_cmp(&self, o: &Self) -> Option<Ordering> {
        Some(self.cmp(o))
    }
}

impl Ways {
    /// Every road of the land (trunk roads, streets, lanes and paths), points no more than
    /// `step` apart, joined where they meet.
    pub fn of(land: &Land) -> Self {
        let mut w = Ways { pts: Vec::new(), trunk: Vec::new(), adj: Vec::new(), cells: Default::default() };
        let mut roads: Vec<(u32, u32)> = Vec::new();
        for r in &land.roads {
            let start = w.pts.len() as u32;
            let trunk = r.class == crate::settle::RoadClass::Trunk;
            for (i, &p) in r.points.iter().enumerate() {
                if i > 0 {
                    // Long segments get points along them, so junctions land near a point.
                    let a = r.points[i - 1];
                    let n = (d(a, p) / 6.0).floor() as usize;
                    for k in 1..=n {
                        let t = k as f32 / (n + 1) as f32;
                        w.push((a.0 + (p.0 - a.0) * t, a.1 + (p.1 - a.1) * t), trunk);
                        let id = w.pts.len() as u32 - 1;
                        w.link(id - 1, id);
                    }
                }
                w.push(p, trunk);
                let id = w.pts.len() as u32 - 1;
                if id > start {
                    w.link(id - 1, id);
                }
            }
            roads.push((start, w.pts.len() as u32));
        }
        // Plazas: roads end at a plaza's edge, and the plaza joins them. A point at its centre
        // joins every road end on or near its edge.
        for s in &land.settlements {
            let c = s.plaza.centre;
            let reach = s.plaza.points.iter().map(|q| d(*q, c)).fold(0.0, f32::max) + JOIN_M;
            w.push(c, false);
            let hub = w.pts.len() as u32 - 1;
            for &(a, b) in &roads {
                for e in [a, b - 1] {
                    if b > a && d(w.pts[e as usize], c) <= reach {
                        w.link(hub, e);
                    }
                }
            }
        }
        // Junctions and crossings: each point of a road joins the nearest point of every other
        // road within JOIN_M.
        for (ri, &(a, b)) in roads.iter().enumerate() {
            for i in a..b {
                let p = w.pts[i as usize];
                let mut best: Vec<(usize, u32, f32)> = Vec::new();
                for j in w.near(p, JOIN_M) {
                    let rj = roads.iter().position(|&(x, y)| j >= x && j < y).unwrap_or(ri);
                    if rj == ri {
                        continue;
                    }
                    let dj = d(p, w.pts[j as usize]);
                    match best.iter_mut().find(|e| e.0 == rj) {
                        Some(e) if dj < e.2 => *e = (rj, j, dj),
                        Some(_) => {}
                        None => best.push((rj, j, dj)),
                    }
                }
                for (_, j, _) in best {
                    w.link(i, j);
                }
            }
        }
        w
    }

    fn push(&mut self, p: V2, trunk: bool) {
        self.cells.entry(cell(p)).or_default().push(self.pts.len() as u32);
        self.pts.push(p);
        self.trunk.push(trunk);
        self.adj.push(Vec::new());
    }

    fn link(&mut self, a: u32, b: u32) {
        if a == b || self.adj[a as usize].iter().any(|e| e.0 == b) {
            return;
        }
        let w = d(self.pts[a as usize], self.pts[b as usize]);
        self.adj[a as usize].push((b, w));
        self.adj[b as usize].push((a, w));
    }

    fn near(&self, p: V2, r: f32) -> Vec<u32> {
        let (c0, c1) = (cell((p.0 - r, p.1 - r)), cell((p.0 + r, p.1 + r)));
        let mut out = Vec::new();
        for cy in c0.1..=c1.1 {
            for cx in c0.0..=c1.0 {
                if let Some(v) = self.cells.get(&(cx, cy)) {
                    out.extend(v.iter().copied().filter(|&i| d(self.pts[i as usize], p) <= r));
                }
            }
        }
        out.sort_unstable();
        out
    }

    fn nearest(&self, p: V2) -> Option<u32> {
        let mut r = CELL_M;
        while r <= REACH_M * 2.0 {
            if let Some(i) = self.near(p, r).into_iter().min_by(|&a, &b| d(self.pts[a as usize], p).total_cmp(&d(self.pts[b as usize], p))) {
                return (d(self.pts[i as usize], p) <= REACH_M).then_some(i);
            }
            r *= 2.0;
        }
        None
    }

    /// The way from `from` to `to` along the roads: `from`, the road points in order, `to`. None
    /// when either end is far from every road or the roads between them do not join.
    pub fn route(&self, from: V2, to: V2) -> Option<Vec<V2>> {
        let ids = self.route_ids(from, to)?;
        let mut way = vec![from];
        way.extend(ids.iter().map(|&i| self.pts[i as usize]));
        way.push(to);
        Some(way)
    }

    /// The trunk-road points of the way from `from` to `to` (the road between settlements,
    /// without the streets and greens it passes through), in order.
    pub fn trunk_of_route(&self, from: V2, to: V2) -> Option<Vec<V2>> {
        let ids = self.route_ids(from, to)?;
        Some(ids.into_iter().filter(|&i| self.trunk[i as usize]).map(|i| self.pts[i as usize]).collect())
    }

    fn route_ids(&self, from: V2, to: V2) -> Option<Vec<u32>> {
        let (s, g) = (self.nearest(from)?, self.nearest(to)?);
        let n = self.pts.len();
        let mut cost = vec![f32::INFINITY; n];
        let mut prev = vec![u32::MAX; n];
        let mut open = BinaryHeap::new();
        cost[s as usize] = 0.0;
        open.push(Open(0.0, s));
        while let Some(Open(c, i)) = open.pop() {
            if i == g {
                break;
            }
            if c > cost[i as usize] {
                continue;
            }
            for &(j, w) in &self.adj[i as usize] {
                let nc = c + w;
                if nc < cost[j as usize] {
                    cost[j as usize] = nc;
                    prev[j as usize] = i;
                    open.push(Open(nc, j));
                }
            }
        }
        if !cost[g as usize].is_finite() {
            return None;
        }
        let mut ids = Vec::new();
        let mut i = g;
        while i != u32::MAX {
            ids.push(i);
            i = prev[i as usize];
        }
        ids.reverse();
        Some(ids)
    }
}

/// Length of a way (metres).
pub fn length(way: &[V2]) -> f32 {
    way.windows(2).map(|w| d(w[0], w[1])).sum()
}

/// `n` points evenly spaced along a way, the last at its end: the stages of the journey.
pub fn stages(way: &[V2], n: usize) -> Vec<V2> {
    let total = length(way);
    (1..=n).map(|k| along(way, total * k as f32 / n as f32)).collect()
}

/// The point `m` metres along a way (its end when it is shorter).
pub fn along(way: &[V2], m: f32) -> V2 {
    let mut left = m.max(0.0);
    for w in way.windows(2) {
        let l = d(w[0], w[1]);
        if left <= l && l > 0.0 {
            let t = left / l;
            return (w[0].0 + (w[1].0 - w[0].0) * t, w[0].1 + (w[1].1 - w[0].1) * t);
        }
        left -= l;
    }
    *way.last().unwrap_or(&(0.0, 0.0))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::land::{generate, LandParams};

    /// Every settlement reaches every other along the roads, and a journey cut into stages
    /// 140 m or less apart has legs an ordinary walk search finds on the hosted map.
    #[test]
    fn settlements_join_along_the_roads_in_walkable_stages() {
        let p = LandParams::default();
        let land = generate(7, 2048, &p);
        let (map, _) = crate::host::hosted_map(&land, &p);
        let ways = Ways::of(&land);
        let near = |q: V2| map.nearest_walkable(q.0, q.1).unwrap();
        let (mut legs, mut failed) = (0, Vec::new());
        for (i, a) in land.settlements.iter().enumerate() {
            for (j, b) in land.settlements.iter().enumerate().filter(|(j, _)| *j > i) {
                let way = ways.route(a.plaza.centre, b.plaza.centre).unwrap_or_else(|| panic!("no way from {i} to {j}"));
                let n = (length(&way) / 120.0).ceil() as usize;
                let mut at = near(a.plaza.centre);
                for s in stages(&way, n.max(1)) {
                    let s = near(s);
                    legs += 1;
                    if map.path(at, s, 6_000).is_none() {
                        failed.push((i, j, at, s));
                    }
                    at = s;
                }
            }
        }
        assert!(failed.len() * 50 <= legs, "{} of {legs} legs found no walk: {:?}", failed.len(), &failed[..failed.len().min(8)]);
    }
}
