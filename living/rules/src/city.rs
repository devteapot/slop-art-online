//! Settlement layouts for seeding: a walled city (wall ring with a gate on each side, main
//! streets from gate to gate, an inner ring road, a paved market square, houses along the
//! streets, fields outside) or an open village (a crossroads with houses around it).
//! Walls and roads are painted into the map; everything else is returned as positions.

use crate::map::{Map, Terrain};

pub struct Layout {
    pub center: (f32, f32),
    /// Tile of each gate (on a road, in the wall ring).
    pub gates: Vec<(i32, i32)>,
    /// One house per household, next to a road.
    pub houses: Vec<(f32, f32)>,
    /// Market square spots: hearth at the center, then sign, then stores.
    pub market: Vec<(f32, f32)>,
    /// Planted berry bushes outside the walls.
    pub fields: Vec<(f32, f32)>,
}

fn land(t: Terrain) -> bool {
    matches!(t, Terrain::Grass | Terrain::Forest | Terrain::Dirt | Terrain::Sand | Terrain::Road)
}

/// `radius` is the wall ring's half-size in tiles (a village has no wall).
pub fn lay_out(map: &mut Map, center: (f32, f32), households: usize, radius: i32, walled: bool) -> Layout {
    let (cx, cy) = (center.0.floor() as i32, center.1.floor() as i32);
    let r = radius;
    let paint = |map: &mut Map, x: i32, y: i32, t: Terrain| {
        if land(map.get(x, y)) {
            map.set(x, y, t);
        }
    };
    let mut gates = Vec::new();
    if walled {
        for d in -r..=r {
            for (x, y) in [(cx + d, cy - r), (cx + d, cy + r), (cx - r, cy + d), (cx + r, cy + d)] {
                paint(map, x, y, Terrain::Wall);
            }
        }
        for (x, y) in [(cx, cy - r), (cx, cy + r), (cx - r, cy), (cx + r, cy)] {
            // A gate only where land continues outside; otherwise the wall stays closed.
            let (ox, oy) = (x + (x - cx).signum(), y + (y - cy).signum());
            if map.get(x, y) == Terrain::Wall && land(map.get(ox, oy)) {
                map.set(x, y, Terrain::Road);
                gates.push((x, y));
            }
        }
    }
    // Main streets through the center, continuing a few tiles past each gate.
    let reach = if walled { r + 6 } else { r };
    for d in -reach..=reach {
        for (x, y) in [(cx + d, cy), (cx, cy + d)] {
            if map.get(x, y) != Terrain::Wall {
                paint(map, x, y, Terrain::Road);
            }
        }
    }
    if walled {
        for d in -(r - 2)..=(r - 2) {
            for (x, y) in [(cx + d, cy - r + 2), (cx + d, cy + r - 2), (cx - r + 2, cy + d), (cx + r - 2, cy + d)] {
                paint(map, x, y, Terrain::Road);
            }
        }
        // Side streets every 6 tiles, so houses line streets across the whole city.
        let mut k = 6;
        while k < r - 3 {
            for d in -(r - 2)..=(r - 2) {
                for (x, y) in [(cx + d, cy - k), (cx + d, cy + k), (cx - k, cy + d), (cx + k, cy + d)] {
                    paint(map, x, y, Terrain::Road);
                }
            }
            k += 6;
        }
    }
    // Market square.
    let m = if walled { 2 } else { 1 };
    for dy in -m..=m {
        for dx in -m..=m {
            paint(map, cx + dx, cy + dy, Terrain::Road);
        }
    }
    let at = |x: i32, y: i32| (x as f32 + 0.5, y as f32 + 0.5);
    let market = vec![at(cx, cy), at(cx + m, cy - m), at(cx + m, cy + m), at(cx - m, cy + m), at(cx - m, cy - m)];
    // Houses: beside a road, off the market, spaced apart, nearest the center first.
    let inner = if walled { r - 1 } else { r + 3 };
    let mut spots: Vec<(i32, i32, i32)> = Vec::new();
    for dy in -inner..=inner {
        for dx in -inner..=inner {
            let (x, y) = (cx + dx, cy + dy);
            let t = map.get(x, y);
            if t == Terrain::Road || t == Terrain::Wall || !land(t) || (dx.abs() <= m + 1 && dy.abs() <= m + 1) {
                continue;
            }
            let by_road = [(1, 0), (-1, 0), (0, 1), (0, -1)].iter().any(|(ox, oy)| map.get(x + ox, y + oy) == Terrain::Road);
            if by_road {
                spots.push((dx * dx + dy * dy, x, y));
            }
        }
    }
    // Spread homes through the whole settlement: fill rings outward from the market with
    // wide spacing first, then tighten the spacing only if there is not enough room.
    spots.sort();
    let mut houses: Vec<(f32, f32)> = Vec::new();
    let min_ring = if walled { m + 4 } else { m + 2 };
    for spacing in [5.0f32, 4.0, 3.0] {
        for &(d2, x, y) in &spots {
            if houses.len() >= households {
                break;
            }
            if d2 < min_ring * min_ring {
                continue;
            }
            let p = at(x, y);
            if houses.iter().all(|h| (h.0 - p.0).abs().max((h.1 - p.1).abs()) >= spacing) {
                houses.push(p);
            }
        }
        if houses.len() >= households {
            break;
        }
    }
    // Fields outside the walls (or around the village).
    let (f0, f1) = if walled { (r + 3, r + 8) } else { (r + 4, r + 7) };
    let mut fields = Vec::new();
    let want = households * 3;
    'rings: for ring in f0..=f1 {
        for d in (-ring..=ring).step_by(2) {
            for (x, y) in [(cx + d, cy - ring), (cx + d, cy + ring), (cx - ring, cy + d), (cx + ring, cy + d)] {
                if map.get(x, y) == Terrain::Grass && (x - cx).abs() > 1 && (y - cy).abs() > 1 {
                    fields.push(at(x, y));
                    if fields.len() >= want {
                        break 'rings;
                    }
                }
            }
        }
    }
    Layout { center: at(cx, cy), gates, houses, market, fields }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn walled_city_has_gates_roads_and_houses() {
        let mut map = Map { w: 64, h: 64, tiles: vec![Terrain::Grass as u8; 64 * 64], blocked: Default::default() };
        let l = lay_out(&mut map, (32.5, 32.5), 10, 14, true);
        assert_eq!(l.gates.len(), 4);
        assert_eq!(l.houses.len(), 10);
        assert!(map.get(32 - 14, 20) == Terrain::Wall);
        assert!(map.get(32, 32) == Terrain::Road);
        // Every house can reach the market, and the market can reach outside through a gate.
        for h in &l.houses {
            assert!(map.path(*h, l.center, 20_000).is_some(), "house {h:?} cut off");
        }
        assert!(map.path(l.center, (2.5, 32.5), 20_000).is_some());
        assert!(!l.fields.is_empty());
    }
}
