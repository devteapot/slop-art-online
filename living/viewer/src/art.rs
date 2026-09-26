//! Pixel art generated in code at startup: a tiny RGBA canvas, sprite sheets for
//! creatures, resources and structures, and per-person palettes. Every sheet is uploaded
//! once as a nearest-filtered egui texture; frames are addressed by UV.

use bevy_egui::egui::{self, Color32, Mesh, Pos2, Rect, Shape, TextureHandle, TextureOptions};
use std::collections::HashMap;

pub type Rgba = [u8; 4];

pub const fn rgb(r: u8, g: u8, b: u8) -> Rgba {
    [r, g, b, 255]
}
const CLEAR: Rgba = [0, 0, 0, 0];
const OUTLINE: Rgba = [22, 18, 26, 255];

pub fn hash2(x: i32, y: i32, seed: u32) -> f32 {
    let mut h = (x as u32).wrapping_mul(374_761_393) ^ (y as u32).wrapping_mul(668_265_263) ^ seed.wrapping_mul(2_246_822_519);
    h = (h ^ (h >> 13)).wrapping_mul(1_274_126_177);
    ((h ^ (h >> 16)) & 0xffff) as f32 / 65535.0
}

pub fn shade(c: Rgba, f: f32) -> Rgba {
    let s = |v: u8| (v as f32 * f).round().clamp(0.0, 255.0) as u8;
    [s(c[0]), s(c[1]), s(c[2]), c[3]]
}

pub fn mix(a: Rgba, b: Rgba, t: f32) -> Rgba {
    let m = |x: u8, y: u8| (x as f32 + (y as f32 - x as f32) * t).round().clamp(0.0, 255.0) as u8;
    [m(a[0], b[0]), m(a[1], b[1]), m(a[2], b[2]), m(a[3], b[3])]
}

#[derive(Clone)]
pub struct Canvas {
    pub w: i32,
    pub h: i32,
    pub px: Vec<Rgba>,
}

impl Canvas {
    pub fn new(w: i32, h: i32) -> Self {
        Self { w, h, px: vec![CLEAR; (w * h) as usize] }
    }
    pub fn set(&mut self, x: i32, y: i32, c: Rgba) {
        if x >= 0 && y >= 0 && x < self.w && y < self.h {
            self.px[(y * self.w + x) as usize] = c;
        }
    }
    pub fn get(&self, x: i32, y: i32) -> Rgba {
        if x >= 0 && y >= 0 && x < self.w && y < self.h {
            self.px[(y * self.w + x) as usize]
        } else {
            CLEAR
        }
    }
    pub fn rect(&mut self, x: i32, y: i32, w: i32, h: i32, c: Rgba) {
        for j in y..y + h {
            for i in x..x + w {
                self.set(i, j, c);
            }
        }
    }
    /// Filled ellipse with a per-pixel color function of the normalized offset.
    pub fn blob(&mut self, cx: f32, cy: f32, rx: f32, ry: f32, mut f: impl FnMut(i32, i32, f32, f32) -> Option<Rgba>) {
        for y in (cy - ry).floor() as i32..=(cy + ry).ceil() as i32 {
            for x in (cx - rx).floor() as i32..=(cx + rx).ceil() as i32 {
                let dx = (x as f32 + 0.5 - cx) / rx;
                let dy = (y as f32 + 0.5 - cy) / ry;
                if dx * dx + dy * dy <= 1.0 {
                    if let Some(c) = f(x, y, dx, dy) {
                        self.set(x, y, c);
                    }
                }
            }
        }
    }
    /// Dark outline around every opaque pixel (4-neighborhood).
    pub fn outline(&mut self, c: Rgba) {
        let src = self.clone();
        for y in 0..self.h {
            for x in 0..self.w {
                if src.get(x, y)[3] != 0 {
                    continue;
                }
                let near = [(1, 0), (-1, 0), (0, 1), (0, -1)].iter().any(|(dx, dy)| src.get(x + dx, y + dy)[3] > 128);
                if near {
                    self.set(x, y, c);
                }
            }
        }
    }
}

/// Frames laid out horizontally with a 1-pixel transparent gutter (no bleeding).
pub struct Sheet {
    pub tex: TextureHandle,
    pub frames: usize,
    pub w: i32,
    pub h: i32,
}

impl Sheet {
    pub fn new(ctx: &egui::Context, name: &str, frames: &[Canvas]) -> Self {
        let (w, h) = (frames[0].w, frames[0].h);
        let cw = w + 2;
        let tw = cw * frames.len() as i32;
        let th = h + 2;
        let mut px = vec![Color32::TRANSPARENT; (tw * th) as usize];
        for (k, f) in frames.iter().enumerate() {
            for y in 0..h {
                for x in 0..w {
                    let c = f.get(x, y);
                    px[((y + 1) * tw + k as i32 * cw + x + 1) as usize] = Color32::from_rgba_unmultiplied(c[0], c[1], c[2], c[3]);
                }
            }
        }
        let img = egui::ColorImage::new([tw as usize, th as usize], px);
        Self { tex: ctx.load_texture(name, img, TextureOptions::NEAREST), frames: frames.len(), w, h }
    }

    fn uv(&self, frame: usize, flip: bool) -> Rect {
        let tw = ((self.w + 2) * self.frames as i32) as f32;
        let th = (self.h + 2) as f32;
        let x0 = ((frame % self.frames) as i32 * (self.w + 2) + 1) as f32 / tw;
        let x1 = x0 + self.w as f32 / tw;
        let (a, b) = if flip { (x1, x0) } else { (x0, x1) };
        Rect::from_min_max(egui::pos2(a, 1.0 / th), egui::pos2(b, (self.h + 1) as f32 / th))
    }

    /// Draw a frame with its bottom-center anchored at `feet`, `scale` screen points per pixel.
    pub fn draw(&self, p: &egui::Painter, frame: usize, feet: Pos2, scale: f32, flip: bool, tint: Color32) -> Rect {
        let size = egui::vec2(self.w as f32 * scale, self.h as f32 * scale);
        let rect = Rect::from_min_size(feet - egui::vec2(size.x / 2.0, size.y), size);
        let mut mesh = Mesh::with_texture(self.tex.id());
        mesh.add_rect_with_uv(rect, self.uv(frame, flip), tint);
        p.add(Shape::mesh(mesh));
        rect
    }
}

// ---- people -----------------------------------------------------------------

const SKINS: [Rgba; 6] = [rgb(247, 206, 172), rgb(236, 184, 140), rgb(214, 156, 110), rgb(182, 124, 84), rgb(142, 94, 62), rgb(106, 70, 48)];
const HAIRS: [Rgba; 8] = [
    rgb(38, 28, 24),
    rgb(84, 54, 32),
    rgb(142, 92, 46),
    rgb(214, 172, 92),
    rgb(160, 60, 36),
    rgb(206, 206, 196),
    rgb(26, 26, 36),
    rgb(110, 76, 50),
];
const PANTS: [Rgba; 4] = [rgb(70, 56, 44), rgb(58, 62, 78), rgb(88, 74, 52), rgb(50, 50, 54)];

struct Palette {
    skin: Rgba,
    hair: Rgba,
    cloth: Rgba,
    pants: Rgba,
    long_hair: bool,
}

fn palette(id: u32, cloth: Color32) -> Palette {
    let h = |k: u32| hash2(id as i32, k as i32, 91);
    let [r, g, b, _] = cloth.to_array();
    Palette {
        skin: SKINS[(h(1) * SKINS.len() as f32) as usize % SKINS.len()],
        hair: HAIRS[(h(2) * HAIRS.len() as f32) as usize % HAIRS.len()],
        cloth: shade([r, g, b, 255], 0.82),
        pants: PANTS[(h(3) * PANTS.len() as f32) as usize % PANTS.len()],
        long_hair: h(4) > 0.5,
    }
}

/// Standing/walking figure facing right; `frame` 0 idle, 1..=4 walk cycle.
fn person_frame(pal: &Palette, frame: usize) -> Canvas {
    let mut c = Canvas::new(16, 16);
    let bob = if frame == 2 || frame == 4 { -1 } else { 0 };
    let y0 = 1 + bob;
    // Head.
    c.rect(6, y0 + 2, 5, 4, pal.skin);
    c.rect(6, y0, 5, 2, pal.hair);
    c.set(5, y0 + 1, pal.hair);
    c.rect(5, y0 + 2, 1, if pal.long_hair { 5 } else { 3 }, pal.hair);
    c.set(6, y0 + 2, pal.hair);
    c.set(9, y0 + 3, rgb(30, 24, 30));
    c.set(10, y0 + 5, shade(pal.skin, 0.85));
    // Torso.
    c.rect(6, y0 + 6, 5, 4, pal.cloth);
    c.rect(6, y0 + 6, 1, 4, shade(pal.cloth, 0.78));
    c.rect(6, y0 + 9, 5, 1, shade(pal.cloth, 0.6));
    c.set(8, y0 + 6, shade(pal.cloth, 1.15));
    // Arms swing opposite to legs.
    let (back, front) = match frame {
        1 => (1, -1),
        3 => (-1, 1),
        _ => (0, 0),
    };
    c.rect(5, y0 + 6 + back.max(0), 1, 3, shade(pal.cloth, 0.7));
    c.set(5, y0 + 9 + back, pal.skin);
    c.rect(11, y0 + 6 + front.max(0), 1, 3, pal.cloth);
    c.set(11, y0 + 9 + front, pal.skin);
    // Legs.
    let ly = y0 + 10;
    let pants = pal.pants;
    let boot = rgb(44, 32, 26);
    match frame {
        1 => {
            c.rect(9, ly, 2, 2, pants);
            c.rect(10, ly + 2, 2, 1, pants);
            c.rect(10, ly + 3, 2, 1, boot);
            c.rect(6, ly, 2, 2, shade(pants, 0.8));
            c.rect(5, ly + 2, 2, 1, shade(pants, 0.8));
            c.rect(4, ly + 3, 2, 1, boot);
        }
        3 => {
            c.rect(6, ly, 2, 2, pants);
            c.rect(6, ly + 2, 2, 1, pants);
            c.rect(7, ly + 3, 2, 1, boot);
            c.rect(9, ly, 2, 2, shade(pants, 0.8));
            c.rect(9, ly + 2, 2, 1, shade(pants, 0.8));
            c.rect(10, ly + 3, 2, 1, boot);
        }
        _ => {
            c.rect(6, ly, 2, 3, shade(pants, 0.85));
            c.rect(9, ly, 2, 3, pants);
            c.rect(6, ly + 3, 3, 1, boot);
            c.rect(9, ly + 3, 3, 1, boot);
        }
    }
    c.outline(OUTLINE);
    c
}

fn person_sleep(pal: &Palette) -> Canvas {
    let mut c = Canvas::new(16, 16);
    // Bedroll.
    c.rect(1, 12, 14, 3, rgb(120, 92, 60));
    c.rect(1, 12, 14, 1, rgb(150, 118, 80));
    // Head on the left, body under a blanket in the character's colour.
    c.rect(2, 8, 4, 4, pal.skin);
    c.rect(1, 8, 1, 4, pal.hair);
    c.rect(2, 7, 4, 1, pal.hair);
    c.set(4, 10, rgb(60, 40, 40));
    c.rect(6, 8, 9, 4, pal.cloth);
    c.rect(6, 8, 9, 1, shade(pal.cloth, 1.15));
    c.rect(6, 11, 9, 1, shade(pal.cloth, 0.7));
    c.outline(OUTLINE);
    c
}

/// Frames: 0 idle, 1..=4 walk, 5 asleep.
pub fn person_sheet(ctx: &egui::Context, id: u32, cloth: Color32) -> Sheet {
    let pal = palette(id, cloth);
    let mut frames: Vec<Canvas> = (0..5).map(|f| person_frame(&pal, f)).collect();
    frames.push(person_sleep(&pal));
    Sheet::new(ctx, &format!("person-{id}"), &frames)
}

// ---- animals ----------------------------------------------------------------

fn quadruped(frame: usize, body: Rgba, back: Rgba, belly: Rgba, leg: Rgba, wolf: bool, antlers: bool) -> Canvas {
    let mut c = Canvas::new(16, 16);
    let y = 5;
    c.blob(7.5, y as f32 + 3.0, 5.2, 2.6, |_, _, _, dy| Some(if dy < -0.45 { back } else if dy > 0.5 { belly } else { body }));
    // Legs (walk: pairs alternate).
    let offs: [(i32, i32); 4] = match frame {
        1 => [(4, -1), (6, 1), (9, 1), (11, -1)],
        2 => [(4, 0), (6, 0), (9, 0), (11, 0)],
        3 => [(4, 1), (6, -1), (9, -1), (11, 1)],
        _ => [(4, 0), (6, 0), (9, 0), (11, 0)],
    };
    for (i, (x, d)) in offs.iter().enumerate() {
        let col = if i % 2 == 0 { shade(leg, 0.8) } else { leg };
        c.rect(*x + d.signum().min(0), y + 5, 1, 4, col);
        c.set(*x + d, y + 8, shade(leg, 0.6));
    }
    if wolf {
        c.rect(11, y - 1, 4, 4, body);
        c.rect(11, y - 1, 4, 1, back);
        c.set(15, y + 1, rgb(40, 40, 44));
        c.set(14, y + 1, body);
        c.set(11, y - 2, back);
        c.set(13, y - 2, back);
        c.set(13, y, rgb(236, 200, 70));
        // Tail, low and bushy.
        c.set(2, y + 1, back);
        c.set(1, y + 2, back);
        c.set(1, y + 3, body);
        c.set(0, y + 4, belly);
    } else {
        c.rect(11, y - 1, 2, 3, body);
        c.rect(12, y - 3, 3, 3, body);
        c.set(15, y - 2, rgb(40, 30, 28));
        c.set(13, y - 2, rgb(30, 24, 22));
        c.set(12, y - 4, back);
        c.rect(2, y, 1, 2, rgb(245, 240, 230));
        if antlers {
            let a = rgb(120, 90, 60);
            c.set(12, y - 5, a);
            c.set(11, y - 6, a);
            c.set(13, y - 5, a);
            c.set(13, y - 6, a);
            c.set(14, y - 6, a);
        }
    }
    c.outline(OUTLINE);
    c
}

// ---- world sprites ------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Season {
    Spring,
    Summer,
    Autumn,
    Winter,
}

impl Season {
    /// From `living_rules::season_of` (index into `living_rules::SEASONS`).
    pub fn from_index(i: usize) -> Self {
        match i % 4 {
            0 => Self::Spring,
            1 => Self::Summer,
            2 => Self::Autumn,
            _ => Self::Winter,
        }
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::Spring => "spring",
            Self::Summer => "summer",
            Self::Autumn => "autumn",
            Self::Winter => "winter",
        }
    }
    pub fn all() -> [Self; 4] {
        [Self::Spring, Self::Summer, Self::Autumn, Self::Winter]
    }
}

/// Foliage tones (dark, mid, light) per season, with a variant for autumn colours.
pub fn foliage(season: Season, variant: u32) -> [Rgba; 3] {
    match season {
        Season::Spring => [rgb(52, 110, 50), rgb(78, 146, 62), rgb(126, 188, 86)],
        Season::Summer => [rgb(36, 88, 42), rgb(56, 118, 50), rgb(92, 150, 64)],
        Season::Autumn => match variant % 4 {
            0 => [rgb(150, 60, 26), rgb(196, 96, 36), rgb(232, 150, 60)],
            1 => [rgb(160, 110, 30), rgb(206, 156, 48), rgb(238, 200, 90)],
            2 => [rgb(120, 40, 30), rgb(170, 64, 40), rgb(210, 104, 60)],
            _ => [rgb(70, 88, 40), rgb(110, 118, 50), rgb(160, 150, 70)],
        },
        Season::Winter => [rgb(30, 64, 46), rgb(44, 84, 58), rgb(232, 238, 244)],
    }
}

fn canopy(c: &mut Canvas, cx: f32, cy: f32, r: f32, tones: [Rgba; 3], winter: bool, seed: u32) {
    c.blob(cx, cy, r, r * 0.92, |x, y, dx, dy| {
        let light = -(dx + dy) * 0.7 + (hash2(x, y, seed) - 0.5) * 0.5;
        let edge = dx * dx + dy * dy > 0.72;
        let tone = if winter && dy < -0.2 && hash2(x, y, seed + 1) > 0.25 {
            tones[2]
        } else if light > 0.35 && !winter {
            tones[2]
        } else if light < -0.3 || edge {
            tones[0]
        } else {
            tones[1]
        };
        Some(tone)
    });
}

fn tree(season: Season, variant: u32) -> Canvas {
    let mut c = Canvas::new(16, 20);
    c.rect(7, 13, 2, 7, rgb(96, 64, 40));
    c.set(7, 13, rgb(70, 46, 30));
    c.set(6, 19, rgb(80, 54, 34));
    c.set(9, 19, rgb(80, 54, 34));
    canopy(&mut c, 8.0, 7.5, 7.2, foliage(season, variant), season == Season::Winter, 7 + variant);
    c.outline(OUTLINE);
    c
}

fn bush(season: Season, berries: usize) -> Canvas {
    let mut c = Canvas::new(16, 16);
    let tones = foliage(season, 3);
    if season == Season::Winter {
        let twig = rgb(96, 70, 50);
        for (x, h) in [(4, 5), (6, 7), (8, 8), (10, 6), (12, 4)] {
            c.rect(x, 15 - h, 1, h, twig);
        }
        c.blob(8.0, 10.0, 6.0, 4.5, |x, y, _, dy| (hash2(x, y, 5) > 0.55).then_some(if dy < -0.3 { rgb(236, 240, 246) } else { tones[0] }));
    } else {
        canopy(&mut c, 8.0, 10.0, 6.3, tones, false, 3);
    }
    const SPOTS: [(i32, i32); 7] = [(5, 8), (9, 7), (11, 10), (7, 11), (4, 11), (10, 13), (7, 6)];
    for (k, (x, y)) in SPOTS.iter().take(berries).enumerate() {
        let col = if k % 3 == 2 { rgb(120, 50, 170) } else { rgb(214, 36, 64) };
        c.set(*x, *y, col);
        c.set(*x + 1, *y, shade(col, 0.75));
        c.set(*x, *y - 1, rgb(255, 200, 210));
    }
    c.outline(OUTLINE);
    c
}

fn boulder() -> Canvas {
    let mut c = Canvas::new(16, 16);
    c.blob(8.0, 10.0, 6.5, 4.8, |x, y, dx, dy| {
        let l = -(dx * 0.6 + dy) + (hash2(x, y, 11) - 0.5) * 0.4;
        Some(if l > 0.6 { rgb(190, 190, 196) } else if l < -0.4 { rgb(100, 100, 108) } else { rgb(146, 146, 152) })
    });
    for (x, y) in [(7, 9), (8, 10), (8, 11), (9, 12), (11, 8), (12, 9)] {
        c.set(x, y, rgb(84, 84, 92));
    }
    c.outline(OUTLINE);
    c
}

fn reeds(frame: usize) -> Canvas {
    let mut c = Canvas::new(16, 16);
    for (k, (x, h)) in [(3, 9), (5, 12), (7, 10), (9, 13), (11, 9), (13, 11)].iter().enumerate() {
        let sway = if (frame + k) % 2 == 0 { 0 } else { 1 };
        let stalk = if k % 2 == 0 { rgb(112, 160, 70) } else { rgb(140, 186, 86) };
        for j in 0..*h {
            let x = x + if j > h / 2 { sway } else { 0 };
            c.set(x, 15 - j, stalk);
        }
        if k % 2 == 1 {
            c.rect(x + sway, 15 - h - 1, 1, 3, rgb(110, 70, 40));
        }
    }
    c.outline([22, 30, 20, 200]);
    c
}

fn ripples(frame: usize) -> Canvas {
    let mut c = Canvas::new(16, 16);
    let r = 2.0 + frame as f32 * 1.6;
    let alpha = (230.0 - frame as f32 * 45.0) as u8;
    for k in 0..48 {
        let a = k as f32 / 48.0 * std::f32::consts::TAU;
        let x = (8.0 + a.cos() * r).round() as i32;
        let y = (10.0 + a.sin() * r * 0.55).round() as i32;
        c.set(x, y, [210, 238, 255, alpha]);
    }
    if frame == 1 {
        c.set(7, 7, rgb(60, 90, 110));
        c.set(8, 6, rgb(60, 90, 110));
        c.set(9, 7, rgb(60, 90, 110));
    }
    c
}

fn campfire(frame: usize) -> Canvas {
    let mut c = Canvas::new(16, 16);
    for k in 0..10 {
        let a = k as f32 / 10.0 * std::f32::consts::TAU;
        let x = (8.0 + a.cos() * 5.5).round() as i32;
        let y = (12.0 + a.sin() * 2.5).round() as i32;
        c.rect(x, y, 2, 1, if k % 2 == 0 { rgb(128, 124, 120) } else { rgb(100, 96, 94) });
    }
    c.rect(4, 12, 8, 1, rgb(96, 60, 34));
    c.rect(6, 11, 5, 1, rgb(120, 78, 44));
    let heights = [[5, 7, 6, 4], [6, 5, 7, 5], [4, 6, 8, 6], [6, 8, 5, 4]][frame % 4];
    for (i, hgt) in heights.iter().enumerate() {
        let x = 6 + i as i32;
        for j in 0..*hgt {
            let t = j as f32 / *hgt as f32;
            let col = if t > 0.75 { rgb(255, 120, 30) } else if t > 0.4 { rgb(255, 176, 50) } else { rgb(255, 236, 140) };
            c.set(x, 11 - j, col);
        }
    }
    c.set(7 + (frame % 2) as i32, 11 - heights[1] - 2, rgb(255, 150, 40));
    c.outline([40, 20, 10, 180]);
    c
}

fn shelter() -> Canvas {
    let mut c = Canvas::new(20, 18);
    let hide = rgb(176, 128, 78);
    for y in 3..17 {
        let half = (y - 2) as f32 * 0.68;
        for x in 0..20 {
            let dx = x as f32 + 0.5 - 10.0;
            if dx.abs() <= half {
                let col = if dx < -half + 1.2 { shade(hide, 0.75) } else if dx > 0.0 { shade(hide, 0.9) } else { hide };
                let col = if (y - 3) % 4 == 3 && x % 2 == 0 { shade(col, 0.82) } else { col };
                c.set(x, y, col);
            }
        }
    }
    for y in 10..17 {
        let half = (y - 9) as f32 * 0.45;
        for x in 0..20 {
            if (x as f32 + 0.5 - 10.0).abs() <= half {
                c.set(x, y, rgb(40, 28, 22));
            }
        }
    }
    let pole = rgb(96, 64, 40);
    c.set(8, 1, pole);
    c.set(9, 2, pole);
    c.set(12, 1, pole);
    c.set(11, 2, pole);
    c.rect(0, 17, 20, 1, rgb(90, 70, 50));
    c.outline(OUTLINE);
    c
}

fn storage() -> Canvas {
    let mut c = Canvas::new(16, 16);
    let wood = rgb(176, 128, 70);
    c.rect(3, 5, 10, 10, wood);
    for y in [7, 10, 13] {
        c.rect(3, y, 10, 1, shade(wood, 0.72));
    }
    c.rect(3, 5, 10, 1, shade(wood, 1.2));
    c.rect(3, 5, 1, 10, shade(wood, 0.6));
    c.rect(12, 5, 1, 10, shade(wood, 0.6));
    c.rect(7, 5, 2, 10, rgb(110, 110, 116));
    c.outline(OUTLINE);
    c
}

fn remains() -> Canvas {
    let mut c = Canvas::new(16, 16);
    let bone = rgb(232, 226, 206);
    let stick = rgb(110, 76, 46);
    c.rect(11, 3, 1, 9, stick);
    c.rect(9, 5, 5, 1, stick);
    c.rect(3, 10, 4, 3, bone);
    c.set(4, 11, rgb(40, 34, 30));
    c.set(6, 11, rgb(40, 34, 30));
    for k in 0..5 {
        c.set(6 + k, 14 - k / 2, bone);
        c.set(6 + k, 12 + k / 2, shade(bone, 0.85));
    }
    c.outline(OUTLINE);
    c
}

fn sign() -> Canvas {
    let mut c = Canvas::new(16, 16);
    let post = rgb(104, 72, 44);
    let board = rgb(196, 158, 104);
    c.rect(7, 8, 2, 8, post);
    c.rect(2, 2, 12, 7, board);
    c.rect(2, 2, 12, 1, shade(board, 1.15));
    c.rect(2, 8, 12, 1, shade(board, 0.7));
    for (y, x0, x1) in [(4, 4, 11), (6, 4, 9)] {
        for x in x0..=x1 {
            if hash2(x, y, 88) > 0.25 {
                c.set(x, y, rgb(70, 50, 36));
            }
        }
    }
    c.outline(OUTLINE);
    c
}

/// All static sheets, generated once.
pub struct Art {
    pub deer: Sheet,
    pub deer_antlers: Sheet,
    pub wolf: Sheet,
    pub trees: HashMap<Season, Sheet>,
    pub bushes: HashMap<Season, Sheet>,
    pub boulder: Sheet,
    pub reeds: Sheet,
    pub ripples: Sheet,
    pub campfire: Sheet,
    pub shelter: Sheet,
    pub storage: Sheet,
    pub remains: Sheet,
    pub sign: Sheet,
    pub people: HashMap<u32, Sheet>,
}

impl Art {
    pub fn new(ctx: &egui::Context) -> Self {
        let deer = |ant| {
            (0..4)
                .map(|f| quadruped(f, rgb(190, 142, 88), rgb(156, 110, 64), rgb(232, 204, 160), rgb(130, 94, 58), false, ant))
                .collect::<Vec<_>>()
        };
        let wolf: Vec<Canvas> = (0..4).map(|f| quadruped(f, rgb(112, 114, 122), rgb(78, 80, 88), rgb(170, 170, 176), rgb(84, 86, 94), true, false)).collect();
        let mut trees = HashMap::new();
        let mut bushes = HashMap::new();
        for s in Season::all() {
            trees.insert(s, Sheet::new(ctx, &format!("tree-{}", s.name()), &(0..4).map(|v| tree(s, v)).collect::<Vec<_>>()));
            bushes.insert(s, Sheet::new(ctx, &format!("bush-{}", s.name()), &[0, 2, 4, 7].map(|b| bush(s, b))));
        }
        Self {
            deer: Sheet::new(ctx, "deer", &deer(false)),
            deer_antlers: Sheet::new(ctx, "deer-antlers", &deer(true)),
            wolf: Sheet::new(ctx, "wolf", &wolf),
            trees,
            bushes,
            boulder: Sheet::new(ctx, "boulder", &[boulder()]),
            reeds: Sheet::new(ctx, "reeds", &[reeds(0), reeds(1)]),
            ripples: Sheet::new(ctx, "ripples", &(0..4).map(ripples).collect::<Vec<_>>()),
            campfire: Sheet::new(ctx, "campfire", &(0..4).map(campfire).collect::<Vec<_>>()),
            shelter: Sheet::new(ctx, "shelter", &[shelter()]),
            storage: Sheet::new(ctx, "storage", &[storage()]),
            remains: Sheet::new(ctx, "remains", &[remains()]),
            sign: Sheet::new(ctx, "sign", &[sign()]),
            people: HashMap::new(),
        }
    }

    pub fn person(&mut self, ctx: &egui::Context, id: u32, cloth: Color32) -> &Sheet {
        self.people.entry(id).or_insert_with(|| person_sheet(ctx, id, cloth))
    }
}
