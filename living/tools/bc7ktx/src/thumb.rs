//! The client's picture summary (`living/game/src/characters.rs`, `Thumb::of`), computed from the
//! PNG exactly as the client computes it from the loaded image, and written as a 64×64 16-bit
//! RGBA PNG: each cell's mean linear colour times alpha, and its mean alpha.
//!
//! The client loads a PNG through Bevy's image loader (RGB gets alpha 255) as `Rgba8UnormSrgb`
//! for colour pictures and `Rgba8Unorm` for data (the shadow maps, `is_srgb = false`), and reads
//! each sample with `Image::get_color_at`: a byte over 255, then for sRGB `Srgba::to_linear`
//! (`gamma_function`). The arithmetic below is the same in f32 and in the same order, so the
//! cells are the client's to the bit; the PNG rounds them to 1/65535 (the client's
//! `SAME_SOURCE`, 0.004, is about 260 times that). `tests/thumb.rs` checks both against Bevy.

use crate::Colour;

/// Cells a side (`THUMB`) and samples a side within each cell (`THUMB_SAMPLES`), as the client.
pub const THUMB: u32 = 64;
pub const THUMB_SAMPLES: u32 = 4;

/// `bevy_color::Srgba::gamma_function` (bevy_color 0.20.1, srgba.rs).
pub fn gamma(value: f32) -> f32 {
    if value <= 0.0 {
        return value;
    }
    if value <= 0.04045 {
        value / 12.92
    } else {
        ((value + 0.055) / 1.055).powf(2.4)
    }
}

/// The cells, row by row: [r·a, g·a, b·a, a] in linear light.
pub fn of(w: u32, h: u32, rgba: &[u8], colour: Colour) -> Vec<[f32; 4]> {
    let (w, h) = (w.max(1), h.max(1));
    let n = THUMB * THUMB_SAMPLES;
    let mut cells = vec![[0f32; 4]; (THUMB * THUMB) as usize];
    for sy in 0..n {
        for sx in 0..n {
            let (x, y) = (((sx as f32 + 0.5) / n as f32 * w as f32) as u32, ((sy as f32 + 0.5) / n as f32 * h as f32) as u32);
            let (x, y) = (x.min(w - 1), y.min(h - 1));
            let s = ((y * w + x) * 4) as usize;
            let p: [u8; 4] = rgba[s..s + 4].try_into().unwrap();
            let c = p.map(|b| b as f32 / u8::MAX as f32);
            let l = match colour {
                Colour::Srgb => [gamma(c[0]), gamma(c[1]), gamma(c[2]), c[3]],
                Colour::Linear => c,
            };
            let cell = &mut cells[((sy / THUMB_SAMPLES) * THUMB + sx / THUMB_SAMPLES) as usize];
            let add = [l[0] * l[3], l[1] * l[3], l[2] * l[3], l[3]];
            for i in 0..4 {
                cell[i] += add[i];
            }
        }
    }
    let k = 1.0 / (THUMB_SAMPLES * THUMB_SAMPLES) as f32;
    cells.into_iter().map(|c| c.map(|v| v * k)).collect()
}

/// A cell value as 16 bits (the client reads it back as `v / 65535`).
pub fn quantise(v: f32) -> u16 {
    (v.clamp(0.0, 1.0) * 65535.0 + 0.5).floor() as u16
}

/// The summary as a 64×64 RGBA 16-bit PNG.
pub fn png(cells: &[[f32; 4]]) -> Result<Vec<u8>, String> {
    let mut raw = Vec::with_capacity(cells.len() * 4);
    for c in cells {
        raw.extend(c.iter().map(|&v| quantise(v)));
    }
    let img = image::ImageBuffer::<image::Rgba<u16>, _>::from_raw(THUMB, THUMB, raw).ok_or("thumb size")?;
    let mut out = std::io::Cursor::new(Vec::new());
    img.write_to(&mut out, image::ImageFormat::Png).map_err(|e| e.to_string())?;
    Ok(out.into_inner())
}
