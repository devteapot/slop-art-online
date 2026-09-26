//! Terrain pixel art: 16×16 pixels per tile, deterministic per-pixel variation, dithered
//! land borders, shorelines with foam, rock shadows, forest canopies and seasonal tints.
//!
//! Large maps are drawn from per-chunk textures (16×16 tiles, three levels of detail)
//! built lazily for the chunks in view under a per-frame time budget and cached with LRU
//! eviction, over a coarse whole-map overview (2 px per tile) that also feeds the
//! minimap. Neighbour lookups use the full `Map`, so shores and crowns cross chunk borders
//! seamlessly. A season change rebuilds the overview and invalidates chunks, which are then
//! rebuilt as they come into view.

use crate::art::{foliage, hash2, mix, rgb, shade, Rgba, Season};
use bevy_egui::egui::{self, Color32, TextureHandle, TextureOptions};
use bevy::platform::time::Instant;
use living_rules::map::{chunk_id, chunk_xy, Map, Terrain, CHUNK};
use std::collections::HashMap;

pub const TILE_PX: i32 = 16;
/// Overview resolution (pixels per tile).
pub const OVERVIEW_PX: i32 = 4;
/// Most chunk textures kept at once (each is ~0.35 MB of GPU memory across its levels).
const MAX_CHUNKS: usize = 160;

fn smooth(t: f32) -> f32 {
    t * t * (3.0 - 2.0 * t)
}

/// Value noise in 0..1 with cell size `s` pixels.
fn vnoise(x: i32, y: i32, s: i32, seed: u32) -> f32 {
    let (gx, gy) = (x.div_euclid(s), y.div_euclid(s));
    let (fx, fy) = (smooth(x.rem_euclid(s) as f32 / s as f32), smooth(y.rem_euclid(s) as f32 / s as f32));
    let a = hash2(gx, gy, seed);
    let b = hash2(gx + 1, gy, seed);
    let c = hash2(gx, gy + 1, seed);
    let d = hash2(gx + 1, gy + 1, seed);
    let top = a + (b - a) * fx;
    let bot = c + (d - c) * fx;
    top + (bot - top) * fy
}

fn grass(x: i32, y: i32, season: Season) -> Rgba {
    let n = vnoise(x, y, 28, 1) * 0.7 + vnoise(x, y, 9, 2) * 0.3;
    let (lo, hi) = match season {
        Season::Spring => (rgb(88, 150, 62), rgb(118, 176, 76)),
        Season::Summer => (rgb(98, 146, 56), rgb(134, 166, 66)),
        Season::Autumn => (rgb(136, 136, 62), rgb(176, 150, 72)),
        Season::Winter => (rgb(214, 222, 230), rgb(238, 242, 248)),
    };
    let mut c = mix(lo, hi, n);
    let h = hash2(x, y, 3);
    let blade = hash2(x, y + 1, 3) < 0.07 || h < 0.07;
    if season == Season::Winter {
        let bare = vnoise(x, y, 22, 9) * 0.75 + vnoise(x, y, 5, 19) * 0.25;
        if bare < 0.2 {
            c = mix(rgb(120, 140, 110), c, 0.45);
        } else if blade && bare < 0.35 {
            c = rgb(170, 184, 176);
        }
        return c;
    }
    if blade {
        c = shade(c, 0.78);
    } else if h > 0.975 {
        c = shade(c, 1.18);
    }
    let bloom = match season {
        Season::Spring => 0.012,
        Season::Summer => 0.004,
        _ => 0.0,
    };
    let f = hash2(x, y, 4);
    if f < bloom {
        c = [rgb(250, 236, 110), rgb(236, 130, 170), rgb(250, 250, 250), rgb(170, 150, 240)][(f * 4000.0) as usize % 4];
    }
    c
}

fn forest_floor(x: i32, y: i32, season: Season) -> Rgba {
    let n = vnoise(x, y, 14, 5);
    let mut c = mix(rgb(52, 84, 46), rgb(70, 98, 52), n);
    let h = hash2(x, y, 6);
    if season == Season::Winter {
        c = mix(rgb(196, 206, 214), rgb(222, 230, 236), n);
        if h < 0.08 {
            c = rgb(150, 160, 150);
        }
        return c;
    }
    if h < 0.08 {
        c = if season == Season::Autumn { rgb(176, 104, 40) } else { rgb(96, 84, 44) };
    } else if h > 0.95 {
        c = rgb(40, 62, 36);
    }
    c
}

fn water(x: i32, y: i32, depth: u8, season: Season) -> Rgba {
    let base = match depth {
        0 => rgb(74, 146, 196),
        1 => rgb(60, 124, 180),
        _ => rgb(48, 102, 160),
    };
    let n = vnoise(x, y, 12, 7);
    let mut c = shade(base, 0.94 + n * 0.12);
    let wave = ((x as f32 * 0.35).sin() * 1.5 + y as f32).rem_euclid(7.0) < 1.0;
    if wave && hash2(x / 3, y, 8) < 0.55 {
        c = mix(c, rgb(150, 200, 232), 0.45);
    }
    if season == Season::Winter {
        c = mix(c, rgb(200, 226, 240), if depth == 0 { 0.55 } else { 0.25 });
    }
    c
}

fn sand(x: i32, y: i32, season: Season) -> Rgba {
    let n = vnoise(x, y, 16, 10);
    let mut c = mix(rgb(206, 186, 132), rgb(228, 210, 156), n);
    let h = hash2(x, y, 11);
    if h < 0.08 {
        c = rgb(184, 162, 110);
    } else if h > 0.97 {
        c = rgb(244, 232, 190);
    }
    if season == Season::Winter {
        c = mix(c, rgb(236, 238, 242), 0.55);
    }
    c
}

fn rock(x: i32, y: i32, season: Season) -> Rgba {
    let n = vnoise(x, y, 10, 12);
    let mut c = mix(rgb(112, 112, 120), rgb(146, 146, 152), n);
    let ridge = (vnoise(x, y, 7, 13) - 0.5).abs();
    if ridge < 0.03 {
        c = rgb(78, 78, 86);
    } else if ridge < 0.06 && hash2(x, y, 14) < 0.5 {
        c = rgb(170, 170, 178);
    }
    if hash2(x, y, 15) < 0.04 {
        c = rgb(176, 176, 182);
    }
    if season == Season::Winter && vnoise(x, y, 6, 16) > 0.55 {
        c = rgb(236, 240, 246);
    }
    c
}

fn dirt(x: i32, y: i32, season: Season) -> Rgba {
    let n = vnoise(x, y, 12, 17);
    let mut c = mix(rgb(128, 96, 62), rgb(152, 118, 78), n);
    let h = hash2(x, y, 18);
    if h < 0.05 {
        c = rgb(176, 146, 106);
    } else if h > 0.94 {
        c = rgb(104, 78, 50);
    }
    if season == Season::Winter {
        c = mix(c, rgb(230, 234, 240), 0.5);
    }
    c
}

fn base(t: Terrain, x: i32, y: i32, depth: u8, season: Season) -> Rgba {
    match t {
        Terrain::Grass => grass(x, y, season),
        Terrain::Forest => forest_floor(x, y, season),
        Terrain::Water => water(x, y, depth, season),
        Terrain::Sand => sand(x, y, season),
        Terrain::Rock => rock(x, y, season),
        Terrain::Dirt => dirt(x, y, season),
    }
}

/// Distance (in tiles, capped at 3) from each water tile to the nearest land.
fn depths(map: &Map) -> Vec<u8> {
    let (w, h) = (map.w as i32, map.h as i32);
    let mut d = vec![0u8; (w * h) as usize];
    for y in 0..h {
        for x in 0..w {
            if map.get(x, y) != Terrain::Water {
                continue;
            }
            let mut best = 3u8;
            'r: for r in 1..=3 {
                for dy in -r..=r {
                    for dx in -r..=r {
                        let (nx, ny) = (x + dx, y + dy);
                        if nx >= 0 && ny >= 0 && nx < w && ny < h && map.get(nx, ny) != Terrain::Water {
                            best = (r - 1) as u8;
                            break 'r;
                        }
                    }
                }
            }
            d[(y * w + x) as usize] = best;
        }
    }
    d
}


fn terrain_at(map: &Map, x: i32, y: i32) -> Terrain {
    map.get(x.clamp(0, map.w as i32 - 1), y.clamp(0, map.h as i32 - 1))
}

/// Canopy of the forest tile (tx, ty): centre (pixels), radius, colour variant.
fn crown(tx: i32, ty: i32) -> (f32, f32, f32, u32) {
    let jx = (hash2(tx, ty, 31) - 0.5) * 6.0;
    let jy = (hash2(tx, ty, 32) - 0.5) * 6.0;
    let r = 7.0 + hash2(tx, ty, 33) * 2.5;
    ((tx * TILE_PX) as f32 + 8.0 + jx, (ty * TILE_PX) as f32 + 7.0 + jy, r, (hash2(tx, ty, 34) * 4.0) as u32)
}

/// Full-resolution pixels of a rectangle of tiles (world tile coords), row-major.
fn render(map: &Map, depth: &[u8], season: Season, tx0: i32, ty0: i32, tw: i32, th: i32) -> Vec<Rgba> {
    let (w, h) = (tw * TILE_PX, th * TILE_PX);
    let (ox, oy) = (tx0 * TILE_PX, ty0 * TILE_PX);
    let mw = map.w as i32;
    let mut px = vec![[0u8; 4]; (w * h) as usize];
    for py in 0..h {
        let y = oy + py;
        let (ty, ly) = (y / TILE_PX, y % TILE_PX);
        for pxx in 0..w {
            let x = ox + pxx;
            let (tx, lx) = (x / TILE_PX, x % TILE_PX);
            let t = terrain_at(map, tx, ty);
            let mut kind = t;
            let mut shore = 99;
            for (e, n) in [
                (lx, terrain_at(map, tx - 1, ty)),
                (TILE_PX - 1 - lx, terrain_at(map, tx + 1, ty)),
                (ly, terrain_at(map, tx, ty - 1)),
                (TILE_PX - 1 - ly, terrain_at(map, tx, ty + 1)),
            ] {
                if n == t {
                    continue;
                }
                let water_edge = (t == Terrain::Water) != (n == Terrain::Water);
                if water_edge {
                    shore = shore.min(e);
                    if t == Terrain::Water && e == 0 && hash2(x, y, 21) < 0.35 {
                        kind = n;
                    }
                } else if e < 4 && hash2(x, y, 22 + e as u32) < (4 - e) as f32 / 9.0 {
                    kind = n;
                }
            }
            let d = if kind == Terrain::Water && tx < mw && ty < map.h as i32 { depth[(ty * mw + tx) as usize] } else { 0 };
            let mut c = base(kind, x, y, d, season);
            if kind == Terrain::Water && shore < 2 && hash2(x, y, 23) < if shore == 0 { 0.8 } else { 0.35 } {
                c = mix(c, rgb(214, 234, 244), 0.7);
            } else if kind != Terrain::Water && shore < 2 {
                c = shade(c, if shore == 0 { 0.72 } else { 0.86 });
            }
            if t != Terrain::Rock && terrain_at(map, tx, ty - 1) == Terrain::Rock && ly < 3 {
                c = shade(c, 0.74 + ly as f32 * 0.07);
            }
            if t == Terrain::Rock && terrain_at(map, tx, ty - 1) != Terrain::Rock && ly == 0 {
                c = shade(c, 1.2);
            }
            px[(py * w + pxx) as usize] = c;
        }
    }
    // Crowns of forest tiles in and around the rectangle, in global row-major order so
    // overlaps agree across chunk borders: all shadows first, then crowns.
    let mut crowns = Vec::new();
    for ty in ty0 - 1..ty0 + th + 1 {
        for tx in tx0 - 1..tx0 + tw + 1 {
            if tx >= 0 && ty >= 0 && tx < mw && ty < map.h as i32 && map.get(tx, ty) == Terrain::Forest {
                crowns.push(crown(tx, ty));
            }
        }
    }
    let mut paint = |cx: f32, cy: f32, r: f32, f: &mut dyn FnMut(i32, i32, f32, f32, Rgba) -> Rgba| {
        for y in (cy - r).floor() as i32..=(cy + r).ceil() as i32 {
            for x in (cx - r).floor() as i32..=(cx + r).ceil() as i32 {
                let (lx, ly) = (x - ox, y - oy);
                if lx < 0 || ly < 0 || lx >= w || ly >= h {
                    continue;
                }
                let (dx, dy) = ((x as f32 + 0.5 - cx) / r, (y as f32 + 0.5 - cy) / r);
                if dx * dx + dy * dy <= 1.0 {
                    let i = (ly * w + lx) as usize;
                    px[i] = f(x, y, dx, dy, px[i]);
                }
            }
        }
    };
    for &(cx, cy, r, _) in &crowns {
        paint(cx + 2.5, cy + 3.5, r, &mut |_, _, _, _, c| shade(c, 0.7));
    }
    let winter = season == Season::Winter;
    for &(cx, cy, r, v) in &crowns {
        let tones = foliage(season, v);
        paint(cx, cy, r, &mut |x, y, dx, dy, _| {
            let light = -(dx + dy) * 0.7 + (hash2(x, y, 35) - 0.5) * 0.55;
            let edge = dx * dx + dy * dy > 0.8;
            if edge {
                shade(tones[0], 0.7)
            } else if winter && dy < -0.15 && hash2(x, y, 36) > 0.3 {
                tones[2]
            } else if light > 0.4 && !winter {
                tones[2]
            } else if light < -0.3 {
                tones[0]
            } else {
                tones[1]
            }
        });
    }
    px
}

fn downsample(cur: &[Rgba], cw: i32, ch: i32, f: i32) -> Vec<Rgba> {
    let (nw, nh) = (cw / f, ch / f);
    let n = (f * f) as u32;
    let mut next = vec![[0u8; 4]; (nw * nh) as usize];
    for y in 0..nh {
        for x in 0..nw {
            let mut s = [0u32; 3];
            for dy in 0..f {
                for dx in 0..f {
                    let c = cur[((y * f + dy) * cw + x * f + dx) as usize];
                    for k in 0..3 {
                        s[k] += c[k] as u32;
                    }
                }
            }
            next[(y * nw + x) as usize] = [(s[0] / n) as u8, (s[1] / n) as u8, (s[2] / n) as u8, 255];
        }
    }
    next
}

fn texture(ctx: &egui::Context, name: String, px: &[Rgba], w: i32, h: i32) -> TextureHandle {
    let img = egui::ColorImage::new([w as usize, h as usize], px.iter().map(|c| Color32::from_rgb(c[0], c[1], c[2])).collect());
    ctx.load_texture(name, img, TextureOptions::NEAREST)
}

pub struct ChunkArt {
    /// (texture, pixels per tile), finest first.
    pub levels: Vec<(TextureHandle, i32)>,
    /// Tile rectangle covered.
    pub tiles: egui::Rect,
    used: u64,
}

pub struct TerrainArt {
    pub map: Map,
    depth: Vec<u8>,
    pub season: Season,
    pub overview: TextureHandle,
    chunks: HashMap<u32, ChunkArt>,
    frame: u64,
    /// Build time of the last chunk (ms), for diagnostics.
    pub last_chunk_ms: f32,
}

impl TerrainArt {
    pub fn new(ctx: &egui::Context, map: Map, season: Season) -> Self {
        let depth = depths(&map);
        let overview = overview(ctx, &map, &depth, season);
        Self { map, depth, season, overview, chunks: HashMap::new(), frame: 0, last_chunk_ms: 0.0 }
    }

    pub fn set_season(&mut self, ctx: &egui::Context, season: Season) {
        if season != self.season {
            self.season = season;
            self.overview = overview(ctx, &self.map, &self.depth, season);
            self.chunks.clear();
        }
    }

    pub fn cached(&self) -> usize {
        self.chunks.len()
    }

    /// Chunk textures covering the visible tile rectangle; builds missing ones nearest the
    /// centre first within `budget_ms`, and evicts the least recently used beyond the cap.
    pub fn visible(&mut self, ctx: &egui::Context, view: egui::Rect, budget_ms: f32) -> Vec<&ChunkArt> {
        self.frame += 1;
        let c = CHUNK as f32;
        let (cw, ch) = (self.map.w.div_ceil(CHUNK) as i32, self.map.h.div_ceil(CHUNK) as i32);
        let x0 = ((view.min.x / c).floor() as i32 - 1).max(0);
        let y0 = ((view.min.y / c).floor() as i32 - 1).max(0);
        let x1 = ((view.max.x / c).floor() as i32 + 1).min(cw - 1);
        let y1 = ((view.max.y / c).floor() as i32 + 1).min(ch - 1);
        let mut ids = Vec::new();
        for cy in y0..=y1 {
            for cx in x0..=x1 {
                ids.push(chunk_id(cx as u32, cy as u32));
            }
        }
        let centre = view.center();
        let mut missing: Vec<u32> = ids.iter().copied().filter(|id| !self.chunks.contains_key(id)).collect();
        missing.sort_by(|a, b| {
            let d = |id: &u32| {
                let (x, y) = chunk_xy(*id);
                (egui::pos2((x as f32 + 0.5) * c, (y as f32 + 0.5) * c) - centre).length()
            };
            d(a).total_cmp(&d(b))
        });
        let start = Instant::now();
        for id in missing {
            if start.elapsed().as_secs_f32() * 1000.0 > budget_ms {
                break;
            }
            let t0 = Instant::now();
            let art = self.build_chunk(ctx, id);
            self.last_chunk_ms = t0.elapsed().as_secs_f32() * 1000.0;
            self.chunks.insert(id, art);
        }
        for id in &ids {
            if let Some(a) = self.chunks.get_mut(id) {
                a.used = self.frame;
            }
        }
        if self.chunks.len() > MAX_CHUNKS {
            let mut by_age: Vec<(u64, u32)> = self.chunks.iter().map(|(id, a)| (a.used, *id)).collect();
            by_age.sort();
            for (_, id) in by_age.into_iter().take(self.chunks.len() - MAX_CHUNKS) {
                self.chunks.remove(&id);
            }
        }
        ids.iter().filter_map(|id| self.chunks.get(id)).collect()
    }

    fn build_chunk(&self, ctx: &egui::Context, id: u32) -> ChunkArt {
        let (cx, cy) = chunk_xy(id);
        let (tx0, ty0) = ((cx * CHUNK) as i32, (cy * CHUNK) as i32);
        let tw = (CHUNK as i32).min(self.map.w as i32 - tx0);
        let th = (CHUNK as i32).min(self.map.h as i32 - ty0);
        let full = render(&self.map, &self.depth, self.season, tx0, ty0, tw, th);
        let (w, h) = (tw * TILE_PX, th * TILE_PX);
        let half = downsample(&full, w, h, 2);
        let quarter = downsample(&half, w / 2, h / 2, 2);
        let levels = vec![
            (texture(ctx, format!("chunk-{id}-16"), &full, w, h), 16),
            (texture(ctx, format!("chunk-{id}-8"), &half, w / 2, h / 2), 8),
            (texture(ctx, format!("chunk-{id}-4"), &quarter, w / 4, h / 4), 4),
        ];
        ChunkArt {
            levels,
            tiles: egui::Rect::from_min_size(egui::pos2(tx0 as f32, ty0 as f32), egui::vec2(tw as f32, th as f32)),
            used: self.frame,
        }
    }
}

/// Whole map at `OVERVIEW_PX` per tile: each output pixel averages a few samples of the
/// full-resolution pixel functions, plus the canopy colour on forest tiles.
fn overview(ctx: &egui::Context, map: &Map, depth: &[u8], season: Season) -> TextureHandle {
    let (tw, th) = (map.w as i32, map.h as i32);
    let s = OVERVIEW_PX;
    let (w, h) = (tw * s, th * s);
    let sub = TILE_PX / s;
    let mut px = vec![[0u8; 4]; (w * h) as usize];
    for ty in 0..th {
        for tx in 0..tw {
            let t = map.get(tx, ty);
            let d = if t == Terrain::Water { depth[(ty * tw + tx) as usize] } else { 0 };
            let shore = t != Terrain::Water
                && [(1, 0), (-1, 0), (0, 1), (0, -1)].iter().any(|(dx, dy)| terrain_at(map, tx + dx, ty + dy) == Terrain::Water);
            for sy in 0..s {
                for sx in 0..s {
                    let (x, y) = (tx * TILE_PX + sx * sub + sub / 2, ty * TILE_PX + sy * sub + sub / 2);
                    let mut c = base(t, x, y, d, season);
                    if t == Terrain::Forest {
                        let tones = foliage(season, crown(tx, ty).3);
                        c = if season == Season::Winter && sy == 0 { tones[2] } else { tones[if (sx + sy) % 2 == 0 { 1 } else { 0 }] };
                    }
                    if shore {
                        c = shade(c, 0.8);
                    }
                    if t != Terrain::Rock && terrain_at(map, tx, ty - 1) == Terrain::Rock && sy == 0 {
                        c = shade(c, 0.8);
                    }
                    px[((ty * s + sy) * w + tx * s + sx) as usize] = c;
                }
            }
        }
    }
    texture(ctx, "terrain-overview".into(), &px, w, h)
}
