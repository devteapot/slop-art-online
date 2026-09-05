//! Bounded spatial queries. Terrain is a scenario-authored public survey;
//! resources, hazards and character state are never inputs to route search.
use serde::{Deserialize, Serialize};
use std::collections::{BTreeSet, VecDeque};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Bounds {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}
impl Bounds {
    pub fn contains(&self, x: i32, y: i32) -> bool {
        x >= self.x && x < self.x + self.width && y >= self.y && y < self.y + self.height
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Grid {
    pub width: i32,
    pub height: i32,
    pub blocked: BTreeSet<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub bounds: Option<Bounds>,
}
impl Grid {
    pub fn validate(&self) -> Result<(), String> {
        if self.bounds.as_ref().is_some_and(|b| b.x < 0 || b.y < 0 || b.width < 1 || b.height < 1
            || b.width > self.width || b.height > self.height || b.x > self.width-b.width || b.y > self.height-b.height) {
            return Err("invalid grid bounds".into());
        }
        if !(1..=128).contains(&self.width)
            || !(1..=128).contains(&self.height)
            || self.width * self.height > 16384
            || self.blocked.iter().any(|&p| !self.contains(p))
        {
            return Err("grid requires 1..16384 cells, dimensions 1..128 and in-bounds walls".into());
        }
        Ok(())
    }
    pub fn contains(&self, p: i32) -> bool {
        p >= 0 && p < self.width * self.height
            && self.bounds.as_ref().is_none_or(|b| b.contains(p % self.width, p / self.width))
    }
    pub fn walkable(&self, p: i32) -> bool {
        self.contains(p) && !self.blocked.contains(&p)
    }
    pub fn distance(&self, a: i32, b: i32) -> i32 {
        (a % self.width - b % self.width).abs() + (a / self.width - b / self.width).abs()
    }
    /// Stable N/E/S/W breadth-first search: shortest cardinal route, excluding start.
    /// None means unreachable; an empty route means already at the destination.
    pub fn route(&self, start: i32, goal: i32) -> Option<Vec<i32>> {
        if !self.walkable(start) || !self.walkable(goal) {
            return None;
        }
        let mut parents = vec![-1; (self.width * self.height) as usize];
        parents[start as usize] = start;
        let mut queue = VecDeque::from([start]);
        while let Some(p) = queue.pop_front() {
            if p == goal {
                let mut route = vec![];
                let mut cell = goal;
                while cell != start {
                    route.push(cell);
                    cell = parents[cell as usize];
                }
                route.reverse();
                return Some(route);
            }
            for n in [p - self.width, p + 1, p + self.width, p - 1] {
                if self.walkable(n) && self.distance(p, n) == 1 && parents[n as usize] == -1 {
                    parents[n as usize] = p;
                    queue.push_back(n);
                }
            }
        }
        None
    }
}

pub fn contains(grid: Option<&Grid>, p: i32) -> bool {
    grid.map_or((-10..=10).contains(&p), |g| g.contains(p))
}
pub fn walkable(grid: Option<&Grid>, p: i32) -> bool {
    grid.map_or((-10..=10).contains(&p), |g| g.walkable(p))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn route_detours_without_wrapping_and_reports_unreachable() {
        let mut grid = Grid {
            bounds: None,
            width: 5,
            height: 4,
            blocked: BTreeSet::from([2, 7, 12]),
        };
        let route = grid.route(0, 4).unwrap();
        assert_eq!(route.len(), 10);
        let mut prev = 0;
        for p in route {
            assert!(grid.walkable(p));
            assert_eq!(grid.distance(prev, p), 1);
            prev = p;
        }
        assert_eq!(prev, 4);
        grid.blocked.insert(17);
        assert!(grid.route(0, 4).is_none());
        assert_eq!(grid.route(0, 0), Some(vec![]));
        assert!(grid.route(0, 20).is_none());
        assert_eq!(
            Grid {
                bounds: None,
            width: 5,
                height: 4,
                blocked: BTreeSet::new()
            }
            .route(4, 5)
            .unwrap()
            .len(),
            5
        );
    }
}

/// Operator-authored experiment metadata; never supplied to participant reasoning.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Arena {
    pub id: String,
    pub label: String,
    pub environment: String,
    pub variant: String,
    pub bounds: Bounds,
    pub actors: Vec<u32>,
    #[serde(default)]
    pub controllers: std::collections::BTreeMap<u32, String>,
}

pub fn validate_arenas(scenario: &crate::Scenario) -> Result<(), String> {
    if scenario.arenas.is_empty() { return Ok(()); }
    let map = scenario.map.as_ref().ok_or("arenas require a grid")?;
    if map.bounds.is_some() || scenario.arenas.len() > 8 {
        return Err("arena world needs an unscoped grid and at most eight arenas".into());
    }
    let mut ids = BTreeSet::new();
    let mut actors = BTreeSet::new();
    let mut cells = BTreeSet::new();
    for arena in &scenario.arenas {
        let b = &arena.bounds;
        if arena.id.is_empty() || arena.id.len() > 64 || arena.label.len() > 100
            || arena.environment.len() > 64 || arena.variant.len() > 100
            || !ids.insert(&arena.id) || b.width < 1 || b.height < 1
            || b.width > map.width || b.height > map.height
            || b.x < 1 || b.y < 1 || b.x > map.width-b.width-1 || b.y > map.height-b.height-1
            || arena.actors.is_empty() {
            return Err("invalid arena metadata/bounds".into());
        }
        for y in b.y-1..=b.y+b.height {
            for x in b.x-1..=b.x+b.width {
                let cell = y*map.width+x;
                if b.contains(x,y) {
                    if !cells.insert(cell) { return Err("arena interiors overlap".into()); }
                } else if !map.blocked.contains(&cell) {
                    return Err("arena perimeter must be completely walled".into());
                }
            }
        }
        if !arena.controllers.is_empty() && (arena.controllers.len()!=arena.actors.len()
            || arena.controllers.iter().any(|(id,role)|!arena.actors.contains(id)||!matches!(role.as_str(),"builtin"|"external"))) {
            return Err("invalid arena controller metadata".into());
        }
        for id in &arena.actors {
            let p = scenario.players.iter().find(|p| p.id == *id).ok_or("unknown arena actor")?;
            if !actors.insert(*id) || !b.contains(p.position%map.width,p.position/map.width) {
                return Err("actor must belong to exactly one containing arena".into());
            }
        }
    }
    if actors.len() != scenario.players.len() || scenario.sites.iter().any(|s| !cells.contains(&s.position)) {
        return Err("all actors and sites must belong to an arena".into());
    }
    Ok(())
}
impl crate::World {
    pub fn arena_for_actor(&self, actor: u32) -> Option<&Arena> {
        self.initial.arenas.iter().find(|a| a.actors.contains(&actor))
    }
    pub fn same_arena(&self, a: u32, b: u32) -> bool {
        self.initial.arenas.is_empty() || self.arena_for_actor(a).zip(self.arena_for_actor(b)).is_some_and(|(a,b)| a.id == b.id)
    }
    pub fn map_for_actor(&self, actor: u32) -> Option<Grid> {
        let mut map = self.initial.map.clone()?;
        if let Some(arena) = self.arena_for_actor(actor) {
            map.bounds = Some(arena.bounds.clone());
            map.blocked.retain(|p| arena.bounds.contains(p%map.width,p/map.width));
        }
        Some(map)
    }
}
