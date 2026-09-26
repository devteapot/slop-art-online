//! Terrain pixel art: 16×16 pixels per tile, deterministic per-pixel variation, dithered
//! land borders, shorelines with foam, rock shadows, baked forest canopies and seasonal
//! tints. Rebuilt only when the terrain rows or the season change; two downsampled levels
//! keep zoomed-out views from shimmering (egui has no mipmaps).

use crate::art::{foliage, hash2, mix, rgb, shade, Rgba, Season};
use bevy_egui::egui::{self, Color32, TextureHandle, TextureOptions};
use living_rules::map::{Map, Terrain};

pub const TILE_PX: i32 = 16;

pub struct TerrainArt {
    /// (texture, pixels per tile), finest first.
    pub levels: Vec<(TextureHandle, i32)>,
    /// Water tiles, for animated glints.
    pub water: Vec<(u16, u16)>,
    pub season: Season,
}

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
    let (w, h) = (crate::state::world_tiles().x as i32, crate::state::world_tiles().y as i32);
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

pub fn build(ctx: &egui::Context, map: &Map, season: Season) -> TerrainArt {
    let (tw, th) = (crate::state::world_tiles().x as i32, crate::state::world_tiles().y as i32);
    let (w, h) = (tw * TILE_PX, th * TILE_PX);
    let depth = depths(map);
    let at = |x: i32, y: i32| -> Terrain {
        if x < 0 || y < 0 || x >= tw || y >= th {
            map.get(x.clamp(0, tw - 1), y.clamp(0, th - 1))
        } else {
            map.get(x, y)
        }
    };
    let mut px = vec![[0u8; 4]; (w * h) as usize];
    for y in 0..h {
        let (ty, ly) = (y / TILE_PX, y % TILE_PX);
        for x in 0..w {
            let (tx, lx) = (x / TILE_PX, x % TILE_PX);
            let t = at(tx, ty);
            let mut kind = t;
            let mut shore = 99;
            // Distance to each edge and the terrain across it.
            for (e, n) in [(lx, at(tx - 1, ty)), (TILE_PX - 1 - lx, at(tx + 1, ty)), (ly, at(tx, ty - 1)), (TILE_PX - 1 - ly, at(tx, ty + 1))] {
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
            let d = if kind == Terrain::Water { depth[(ty * tw + tx) as usize] } else { 0 };
            let mut c = base(kind, x, y, d, season);
            if kind == Terrain::Water && shore < 2 && hash2(x, y, 23) < if shore == 0 { 0.8 } else { 0.35 } {
                c = mix(c, rgb(214, 234, 244), 0.7);
            } else if kind != Terrain::Water && shore < 2 {
                c = shade(c, if shore == 0 { 0.72 } else { 0.86 });
            }
            // Rock casts a short shadow on the tile below.
            if t != Terrain::Rock && at(tx, ty - 1) == Terrain::Rock && ly < 3 {
                c = shade(c, 0.74 + ly as f32 * 0.07);
            }
            if t == Terrain::Rock && at(tx, ty - 1) != Terrain::Rock && ly == 0 {
                c = shade(c, 1.2);
            }
            px[(y * w + x) as usize] = c;
        }
    }
    // Forest canopies: shadows first, then crowns from top to bottom.
    let mut crowns = Vec::new();
    for ty in 0..th {
        for tx in 0..tw {
            if map.get(tx, ty) != Terrain::Forest {
                continue;
            }
            let jx = (hash2(tx, ty, 31) - 0.5) * 6.0;
            let jy = (hash2(tx, ty, 32) - 0.5) * 6.0;
            let r = 7.0 + hash2(tx, ty, 33) * 2.5;
            crowns.push(((tx * TILE_PX) as f32 + 8.0 + jx, (ty * TILE_PX) as f32 + 7.0 + jy, r, (hash2(tx, ty, 34) * 4.0) as u32));
        }
    }
    let mut paint = |cx: f32, cy: f32, r: f32, f: &mut dyn FnMut(i32, i32, f32, f32, Rgba) -> Rgba| {
        for y in (cy - r).floor() as i32..=(cy + r).ceil() as i32 {
            for x in (cx - r).floor() as i32..=(cx + r).ceil() as i32 {
                if x < 0 || y < 0 || x >= w || y >= h {
                    continue;
                }
                let (dx, dy) = ((x as f32 + 0.5 - cx) / r, (y as f32 + 0.5 - cy) / r);
                if dx * dx + dy * dy <= 1.0 {
                    let i = (y * w + x) as usize;
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
    let mut water = Vec::new();
    for ty in 0..th {
        for tx in 0..tw {
            if map.get(tx, ty) == Terrain::Water {
                water.push((tx as u16, ty as u16));
            }
        }
    }
    let mut levels = Vec::new();
    let mut cur = px;
    let mut size = TILE_PX;
    let (mut cw, mut ch) = (w, h);
    loop {
        let img = egui::ColorImage::new(
            [cw as usize, ch as usize],
            cur.iter().map(|c| Color32::from_rgb(c[0], c[1], c[2])).collect(),
        );
        levels.push((ctx.load_texture(format!("terrain-{size}"), img, TextureOptions::NEAREST), size));
        if size <= 4 {
            break;
        }
        // Box-filter down by two.
        let (nw, nh) = (cw / 2, ch / 2);
        let mut next = vec![[0u8; 4]; (nw * nh) as usize];
        for y in 0..nh {
            for x in 0..nw {
                let mut s = [0u32; 3];
                for (dx, dy) in [(0, 0), (1, 0), (0, 1), (1, 1)] {
                    let c = cur[((y * 2 + dy) * cw + x * 2 + dx) as usize];
                    for k in 0..3 {
                        s[k] += c[k] as u32;
                    }
                }
                next[(y * nw + x) as usize] = [(s[0] / 4) as u8, (s[1] / 4) as u8, (s[2] / 4) as u8, 255];
            }
        }
        cur = next;
        cw = nw;
        ch = nh;
        size /= 2;
    }
    TerrainArt { levels, water, season }
}
