//! A picture's mip chain, as RGBA8 levels ready for BC7.
//!
//! Every level is an area average of the one above in linear light (sRGB pictures are decoded
//! first and encoded again after), with colour weighted by alpha so a transparent texel's colour
//! does not bleed into a mark's edge. Odd sides (1600×720's 25×11 …) are averaged by exact
//! texel overlap, in integer weights. Level 0 is the source's own bytes.
//!
//! `Coverage(t)` keeps thin marks from fading with distance: alpha-coverage preservation
//! (Castaño, "Computing alpha mipmaps", 2010; NVIDIA Texture Tools' `scaleAlphaToCoverage`)
//! applied to the marks alone. Level 0's texels above `t` are the marks (a line's or a
//! freckle's ink), the rest the soft part (blush, shading round a line, stubble's haze). Both
//! are averaged down; the soft part is kept as averaged, and the marks' alpha is scaled so the
//! share of texels whose marks are above `t` stays level 0's. Under a plain box a one-texel
//! line's alpha halves each level down (a quarter at 1/4 size) until it is gone; with coverage
//! it holds at about `t` over its wider footprint, and the soft part does not darken.

use crate::Colour;

#[derive(Clone, Copy, Debug)]
pub enum Method {
    Box,
    Coverage(f32),
}

pub struct Level {
    pub w: u32,
    pub h: u32,
    pub rgba: Vec<u8>,
    /// The scale the marks' alpha took (1 under a box).
    pub mark_scale: f32,
}

/// A level in linear light.
struct Lin {
    w: u32,
    h: u32,
    /// The soft part and the marks: r·a, g·a, b·a, a each.
    soft: Vec<[f32; 4]>,
    marks: Vec<[f32; 4]>,
    /// r, g, b unweighted (the colour where alpha is 0).
    plain: Vec<[f32; 3]>,
}

fn srgb_lut() -> [f32; 256] {
    std::array::from_fn(|i| crate::thumb::gamma(i as f32 / 255.0))
}

fn encode(v: f32, colour: Colour) -> u8 {
    let v = v.clamp(0.0, 1.0);
    let e = match colour {
        Colour::Srgb => {
            if v <= 0.003_130_8 {
                v * 12.92
            } else {
                1.055 * v.powf(1.0 / 2.4) - 0.055
            }
        }
        Colour::Linear => v,
    };
    (e * 255.0 + 0.5).floor().clamp(0.0, 255.0) as u8
}

/// Each output texel's source texels on one axis of `s` texels down to `d`, with integer
/// weights: the overlap, in units where a source texel is `d` long and an output texel `s`
/// (so an output texel's weights sum to `s`).
fn spans(s: u32, d: u32) -> Vec<Vec<(u32, u32)>> {
    (0..d)
        .map(|x| {
            let (lo, hi) = (x as u64 * s as u64, (x as u64 + 1) * s as u64);
            let (first, last) = ((lo / d as u64) as u32, ((hi - 1) / d as u64) as u32);
            (first..=last)
                .filter_map(|i| {
                    let (a, b) = (lo.max(i as u64 * d as u64), hi.min((i as u64 + 1) * d as u64));
                    (b > a).then_some((i, (b - a) as u32))
                })
                .collect()
        })
        .collect()
}

fn down(l: &Lin) -> Lin {
    let (w, h) = ((l.w / 2).max(1), (l.h / 2).max(1));
    let (sx, sy) = (spans(l.w, w), spans(l.h, h));
    let total = (l.w * l.h) as f32;
    let n = (w * h) as usize;
    let (mut soft, mut marks, mut plain) = (Vec::with_capacity(n), Vec::with_capacity(n), Vec::with_capacity(n));
    for y in 0..h as usize {
        for x in 0..w as usize {
            let (mut s, mut m, mut q) = ([0f32; 4], [0f32; 4], [0f32; 3]);
            for &(j, wy) in &sy[y] {
                for &(i, wx) in &sx[x] {
                    let k = (wx * wy) as f32 / total;
                    let t = (j * l.w + i) as usize;
                    for c in 0..4 {
                        s[c] += l.soft[t][c] * k;
                        m[c] += l.marks[t][c] * k;
                    }
                    for c in 0..3 {
                        q[c] += l.plain[t][c] * k;
                    }
                }
            }
            soft.push(s);
            marks.push(m);
            plain.push(q);
        }
    }
    Lin { w, h, soft, marks, plain }
}

/// Share of texels whose marks' alpha, times `scale`, is above `t`.
fn coverage(l: &Lin, scale: f32, t: f32) -> f64 {
    l.marks.iter().filter(|m| (m[3] * scale).min(1.0) > t).count() as f64 / l.marks.len().max(1) as f64
}

/// The least scale that brings a level's coverage to `want` (bisection: coverage grows with the
/// scale), at least 1: a level never loses ink to the scale.
fn coverage_scale(l: &Lin, want: f64, t: f32) -> f32 {
    if want <= 0.0 || coverage(l, 1.0, t) >= want {
        return 1.0;
    }
    let (mut lo, mut hi) = (1.0f32, 64.0f32);
    for _ in 0..32 {
        let mid = 0.5 * (lo + hi);
        if coverage(l, mid, t) < want {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    hi
}

fn to_rgba8(l: &Lin, colour: Colour, scale: f32) -> Level {
    let mut rgba = Vec::with_capacity((l.w * l.h * 4) as usize);
    for ((s, m), q) in l.soft.iter().zip(&l.marks).zip(&l.plain) {
        let p: [f32; 4] = std::array::from_fn(|c| s[c] + m[c] * scale);
        let rgb = if p[3] > 1e-6 { [p[0] / p[3], p[1] / p[3], p[2] / p[3]] } else { *q };
        rgba.extend(rgb.iter().map(|&v| encode(v, colour)));
        rgba.push((p[3].clamp(0.0, 1.0) * 255.0 + 0.5).floor() as u8);
    }
    Level { w: l.w, h: l.h, rgba, mark_scale: scale }
}

/// The chain from level 0 (`rgba`, `w`×`h`) down to 1×1.
pub fn chain(w: u32, h: u32, rgba: &[u8], colour: Colour, method: Method) -> Vec<Level> {
    let lut = srgb_lut();
    let dec = |v: u8| match colour {
        Colour::Srgb => lut[v as usize],
        Colour::Linear => v as f32 / 255.0,
    };
    let t = match method {
        Method::Coverage(t) => t,
        Method::Box => f32::INFINITY,
    };
    let n = (w * h) as usize;
    let mut l = Lin { w, h, soft: Vec::with_capacity(n), marks: Vec::with_capacity(n), plain: Vec::with_capacity(n) };
    for p in rgba.chunks_exact(4) {
        let a = p[3] as f32 / 255.0;
        let rgb = [dec(p[0]), dec(p[1]), dec(p[2])];
        let pre = [rgb[0] * a, rgb[1] * a, rgb[2] * a, a];
        let (soft, mark) = if a > t { ([0.0; 4], pre) } else { (pre, [0.0; 4]) };
        l.soft.push(soft);
        l.marks.push(mark);
        l.plain.push(rgb);
    }
    let want = coverage(&l, 1.0, t);
    let mut out = vec![Level { w, h, rgba: rgba.to_vec(), mark_scale: 1.0 }];
    while l.w > 1 || l.h > 1 {
        l = down(&l);
        let scale = if t.is_finite() { coverage_scale(&l, want, t) } else { 1.0 };
        out.push(to_rgba8(&l, colour, scale));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spans_sum_to_the_source() {
        for (s, d) in [(1600, 800), (25, 12), (11, 5), (3, 1), (2, 1), (1, 1), (720, 360)] {
            for v in spans(s, d) {
                assert_eq!(v.iter().map(|x| x.1).sum::<u32>(), s, "{s}->{d}");
            }
        }
    }
}
