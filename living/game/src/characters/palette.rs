//! A hair palette relative to each person's hair tag (contract v1.3, docs/HANDMADE_COMPOSED.md,
//! "The palette relative to the hair tag").
//!
//! A profile's swatches are tuned on one hair colour, its `ref`. For another person's tag colour
//! each swatch is moved in OKLCh: its lightness and chroma by their ratios to the reference's, its
//! hue by its offset ([`Ratios`]), then brought into the sRGB gamut by lowering chroma alone. With
//! more anchors (references tuned on other colours) the ratios are mixed by inverse squared OKLab
//! distance to each anchor's reference ([`entry`]). Everything is worked out on the CPU into 8-bit
//! entries of a small image per material ([`Palettes`]); a mesh's tag names its entries
//! (`characters.rs` `recolor`, bit 27), and `toon.wesl` `hand_colours` reads them.

use bevy::prelude::*;
use std::collections::HashMap;

/// Chroma below which a colour is taken as grey: its hue means nothing and a ratio against it
/// would blow up.
pub const GREY_C: f32 = 0.02;
/// The most a lightness or chroma ratio may be.
pub const MAX_RATIO: f32 = 4.0;
/// A palette image's columns: the entries one material can hold.
pub const ENTRIES: usize = 256;
/// Rows: shade, mid, light, highlight, ink.
pub const ROWS: usize = 5;

fn lin(c: u8) -> f64 {
    let c = c as f64 / 255.0;
    if c <= 0.04045 {
        c / 12.92
    } else {
        ((c + 0.055) / 1.055).powf(2.4)
    }
}

fn enc(l: f64) -> u8 {
    let l = l.clamp(0.0, 1.0);
    let s = if l <= 0.0031308 { 12.92 * l } else { 1.055 * l.powf(1.0 / 2.4) - 0.055 };
    (255.0 * s + 0.5).floor().clamp(0.0, 255.0) as u8
}

/// OKLab (L, a, b) of an sRGB colour.
pub fn oklab(c: [u8; 3]) -> [f64; 3] {
    let (r, g, b) = (lin(c[0]), lin(c[1]), lin(c[2]));
    let l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
    let m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
    let s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;
    let (l, m, s) = (l.cbrt(), m.cbrt(), s.cbrt());
    [
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    ]
}

/// Linear sRGB of an OKLab colour.
fn from_oklab(lab: [f64; 3]) -> [f64; 3] {
    let [l, a, b] = lab;
    let l_ = (l + 0.3963377774 * a + 0.2158037573 * b).powi(3);
    let m_ = (l - 0.1055613458 * a - 0.0638541728 * b).powi(3);
    let s_ = (l - 0.0894841775 * a - 1.2914855480 * b).powi(3);
    [
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    ]
}

/// OKLCh (L, C, h in degrees 0..360) of an sRGB colour.
pub fn oklch(c: [u8; 3]) -> [f64; 3] {
    let [l, a, b] = oklab(c);
    [l, a.hypot(b), b.atan2(a).to_degrees().rem_euclid(360.0)]
}

/// How one swatch stands to its reference: lightness and chroma ratios, hue offset (degrees).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Ratios {
    pub k_l: f64,
    pub k_c: f64,
    pub dh: f64,
}

/// The ratios of swatch `s` to reference `r` (the contract's clamps).
pub fn ratios(r: [u8; 3], s: [u8; 3]) -> Ratios {
    let [lr, cr, hr] = oklch(r);
    let [ls, cs, hs] = oklch(s);
    let k_l = if lr > 0.0 { (ls / lr).clamp(0.0, MAX_RATIO as f64) } else { 1.0 };
    let k_c = (cs / cr.max(GREY_C as f64)).clamp(0.0, MAX_RATIO as f64);
    let dh = if cr >= GREY_C as f64 && cs >= GREY_C as f64 { (hs - hr + 180.0).rem_euclid(360.0) - 180.0 } else { 0.0 };
    Ratios { k_l, k_c, dh }
}

/// Whether a ratio was clamped (for the audit's warning).
pub fn clamped(r: [u8; 3], s: [u8; 3]) -> bool {
    let [lr, cr, _] = oklch(r);
    let [ls, cs, _] = oklch(s);
    (lr > 0.0 && ls / lr > MAX_RATIO as f64) || cs / cr.max(GREY_C as f64) > MAX_RATIO as f64
}

fn in_gamut(c: [f64; 3]) -> bool {
    c.iter().all(|x| (-1e-6..=1.0 + 1e-6).contains(x))
}

/// A tag colour moved by a swatch's ratios: OKLCh(min(kL·L, 1), kC·C, h + dh), chroma lowered by
/// bisection (24 steps) until it is in gamut, then sRGB bytes. Also whether chroma was lowered.
pub fn apply(tag: [u8; 3], r: Ratios) -> ([u8; 3], bool) {
    let [lt, ct, ht] = oklch(tag);
    let l = (lt * r.k_l).min(1.0);
    let c = r.k_c * ct;
    let h = (ht + r.dh).to_radians();
    let rgb = |c: f64| from_oklab([l, c * h.cos(), c * h.sin()]);
    let (mut out, mut reduced) = (rgb(c), false);
    if !in_gamut(out) {
        reduced = true;
        let (mut lo, mut hi) = (0.0, c);
        for _ in 0..24 {
            let mid = (lo + hi) / 2.0;
            if in_gamut(rgb(mid)) {
                lo = mid;
            } else {
                hi = mid;
            }
        }
        out = rgb(lo);
    }
    ([enc(out[0]), enc(out[1]), enc(out[2])], reduced)
}

/// A palette tuned on one hair colour: `ref` and its swatches (shade, mid, light, highlight) and
/// ink, as sRGB bytes. The ink is None where the profile leaves it to the shade (× 0.6, linear).
#[derive(Clone, Debug, PartialEq)]
pub struct Anchor {
    pub reference: [u8; 3],
    pub swatches: [[u8; 3]; 4],
    pub ink: Option<[u8; 3]>,
}

/// A palette entry: the four swatches and the ink, for one tag colour.
pub type Entry = [[u8; 3]; ROWS];

/// The shade × 0.6 in linear light: v1.1's default ink.
fn shade_ink(shade: [u8; 3]) -> [u8; 3] {
    [enc(lin(shade[0]) * 0.6), enc(lin(shade[1]) * 0.6), enc(lin(shade[2]) * 0.6)]
}

/// The entry for `tag` from one or more anchors (the first the profile's own). Each anchor's
/// ratios are mixed by w = 1 / (ΔE² + 1e-4), ΔE the OKLab distance from the tag to its reference;
/// a tag within 0.001 of a reference takes that anchor's swatches exactly.
pub fn entry(anchors: &[Anchor], tag: [u8; 3]) -> Entry {
    let t = oklab(tag);
    let dist = |a: &Anchor| {
        let r = oklab(a.reference);
        ((t[0] - r[0]).powi(2) + (t[1] - r[1]).powi(2) + (t[2] - r[2]).powi(2)).sqrt()
    };
    // At an anchor's reference, its own swatches exactly: a near-grey reference has no hue to
    // offset from, so its ratios alone would not give its swatches back.
    if let Some(a) = anchors.iter().find(|a| dist(a) < 1e-3) {
        let s = a.swatches;
        return [s[0], s[1], s[2], s[3], a.ink.unwrap_or_else(|| shade_ink(s[0]))];
    }
    let weights: Vec<(f64, &Anchor)> = anchors.iter().map(|a| (1.0 / (dist(a).powi(2) + 1e-4), a)).collect();
    let total: f64 = weights.iter().map(|(w, _)| w).sum();
    let mix = |row: usize| -> Ratios {
        let (mut k_l, mut k_c, mut dh) = (0.0, 0.0, 0.0);
        for (w, a) in &weights {
            let s = if row < 4 { a.swatches[row] } else { a.ink.unwrap_or_else(|| shade_ink(a.swatches[0])) };
            let r = ratios(a.reference, s);
            k_l += w * r.k_l;
            k_c += w * r.k_c;
            dh += w * r.dh;
        }
        Ratios { k_l: k_l / total, k_c: k_c / total, dh: dh / total }
    };
    let mut e = [[0u8; 3]; ROWS];
    for (row, out) in e.iter_mut().enumerate() {
        *out = apply(tag, mix(row)).0;
    }
    e
}

/// The ink colour of a relative `slop.ink` (`ref` and `color`) for a tag: one ratio, as a swatch.
pub fn ink_entry(reference: [u8; 3], color: [u8; 3], tag: [u8; 3]) -> Entry {
    let c = apply(tag, ratios(reference, color)).0;
    [[0; 3], [0; 3], [0; 3], [0; 3], c]
}

/// What a palette material draws from: a hair profile's anchors, or a relative ink's reference
/// and colour (and, on profile hair, whether a relative `slop.ink` takes the ink row).
#[derive(Clone, Debug, PartialEq)]
pub struct Spec {
    pub anchors: Vec<Anchor>,
    pub ink: Option<([u8; 3], [u8; 3])>,
}

impl Spec {
    pub fn entry(&self, tag: [u8; 3]) -> Entry {
        let mut e = if self.anchors.is_empty() { [[0; 3]; ROWS] } else { entry(&self.anchors, tag) };
        if let Some((r, c)) = self.ink {
            e[4] = ink_entry(r, c, tag)[4];
        }
        e
    }
}

/// One material's palette image (256 × 5, RGBA8, sRGB values; `ToonExt::tints`) and the tag
/// colours its columns hold.
pub struct Book {
    pub image: Handle<Image>,
    pub spec: Spec,
    tags: Vec<[u8; 3]>,
}

/// Palette materials by toon id ([`Book`]); `grown` the toons whose image took a new entry, so
/// their bind groups are refreshed (`characters.rs` `recolor`).
#[derive(Resource, Default)]
pub struct Palettes {
    pub books: HashMap<AssetId<crate::style::Toon>, Book>,
    pub grown: Vec<AssetId<crate::style::Toon>>,
}

/// A new empty palette image.
pub fn image(images: &mut Assets<Image>) -> Handle<Image> {
    use bevy::render::render_resource::{Extent3d, TextureDimension, TextureFormat};
    images.add(Image::new_fill(
        Extent3d { width: ENTRIES as u32, height: ROWS as u32, depth_or_array_layers: 1 },
        TextureDimension::D2,
        &[0, 0, 0, 255],
        TextureFormat::Rgba8Unorm,
        bevy::asset::RenderAssetUsages::all(),
    ))
}

impl Palettes {
    /// Register a palette material with its image (made with [`image`]).
    pub fn add(&mut self, toon: AssetId<crate::style::Toon>, image: Handle<Image>, spec: Spec) {
        self.books.insert(toon, Book { image, spec, tags: Vec::new() });
    }

    /// The column of `tag` on `toon`'s palette, added (and its texels written) if new. A palette
    /// that is full gives the nearest column by OKLab distance, with one warning.
    pub fn place(&mut self, toon: AssetId<crate::style::Toon>, tag: [u8; 3], images: &mut Assets<Image>) -> Option<u8> {
        let book = self.books.get_mut(&toon)?;
        if let Some(i) = book.tags.iter().position(|c| *c == tag) {
            return Some(i as u8);
        }
        if book.tags.len() >= ENTRIES {
            let t = oklab(tag);
            let d = |c: &[u8; 3]| {
                let o = oklab(*c);
                (t[0] - o[0]).powi(2) + (t[1] - o[1]).powi(2) + (t[2] - o[2]).powi(2)
            };
            crate::handmade::warn_once(format!("palette: a material's palette is full ({ENTRIES} colours); {tag:?} takes the nearest"));
            return book.tags.iter().enumerate().min_by(|a, b| d(a.1).total_cmp(&d(b.1))).map(|(i, _)| i as u8);
        }
        let i = book.tags.len();
        book.tags.push(tag);
        let e = book.spec.entry(tag);
        if let Some(mut img) = images.get_mut(&book.image) {
            if let Some(data) = img.data.as_mut() {
                for (row, c) in e.iter().enumerate() {
                    let at = (row * ENTRIES + i) * 4;
                    data[at..at + 3].copy_from_slice(c);
                    data[at + 3] = 255;
                }
            }
        }
        self.grown.push(toon);
        Some(i as u8)
    }
}

/// A palette tag (`toon.wesl` `hand_colours`): the natural colour's and the silver's columns, how
/// grey (0 to 1 in 8 bits), bit 24 (a character's colour) and bit 27 (a palette); bit 25 clear.
pub fn tag(natural: u8, silver: u8, grey: f32) -> u32 {
    let g = (grey.clamp(0.0, 1.0) * 255.0).round() as u32;
    natural as u32 | (silver as u32) << 8 | g << 16 | 1 << 24 | 1 << 27
}

#[cfg(test)]
mod tests {
    use super::*;

    const AUBURN: [u8; 3] = [102, 46, 26];
    const BLACK: [u8; 3] = [0x13, 0x11, 0x11];
    const BLOND: [u8; 3] = [0x9e, 0x7d, 0x47];
    const GREY: [u8; 3] = [0x85, 0x85, 0x85];

    fn cora() -> Anchor {
        Anchor { reference: AUBURN, swatches: [[44, 8, 2], [104, 37, 8], [119, 43, 6], [135, 47, 3]], ink: Some([4, 0, 0]) }
    }

    /// The contract's worked example (docs/HANDMADE_COMPOSED.md): the ratios and both tables.
    #[test]
    fn the_worked_example_holds() {
        let r = ratios(AUBURN, [44, 8, 2]);
        assert!((r.k_l - 0.5337).abs() < 1e-4 && (r.k_c - 0.7131).abs() < 1e-4 && (r.dh + 4.50).abs() < 0.01, "{r:?}");
        let r = ratios(AUBURN, [135, 47, 3]);
        assert!((r.k_l - 1.1493).abs() < 1e-4 && (r.k_c - 1.4948).abs() < 1e-4 && (r.dh - 1.30).abs() < 0.01, "{r:?}");
        let a = [cora()];
        assert_eq!(entry(&a, AUBURN), [[44, 8, 2], [104, 37, 8], [119, 43, 6], [135, 47, 3], [4, 0, 0]], "the reference comes back byte for byte");
        assert_eq!(entry(&a, BLACK), [[3, 3, 3], [18, 16, 16], [22, 19, 19], [26, 23, 23], [0, 0, 0]]);
        assert_eq!(entry(&a, BLOND), [[70, 47, 12], [156, 117, 48], [176, 134, 53], [199, 149, 55], [9, 3, 0]]);
        assert_eq!(entry(&a, GREY), [[53, 53, 53], [127, 127, 127], [144, 144, 144], [161, 161, 161], [4, 4, 4]]);
        // Blond's ink leaves the gamut and is brought back by chroma alone.
        assert!(apply(BLOND, ratios(AUBURN, [4, 0, 0])).1);
        assert!(!apply(BLOND, ratios(AUBURN, [70, 47, 12])).1);
    }

    /// A dark anchor takes over black hair and leaves auburn as it was; between them the mix is
    /// continuous.
    #[test]
    fn a_dark_anchor_lifts_black_hair() {
        let dark = Anchor { reference: BLACK, swatches: [[12, 10, 11], [30, 26, 27], [38, 33, 34], [52, 46, 47]], ink: Some([2, 1, 1]) };
        let both = [cora(), dark.clone()];
        assert_eq!(entry(&both, BLACK), [[12, 10, 11], [30, 26, 27], [38, 33, 34], [52, 46, 47], [2, 1, 1]]);
        assert_eq!(entry(&both, AUBURN), entry(&[cora()], AUBURN));
        // Dark brown sits between the two: its shade is lighter than with the auburn anchor alone.
        let db = [0x20, 0x18, 0x14];
        let alone = entry(&[cora()], db)[0];
        let mixed = entry(&both, db)[0];
        assert!(oklch(mixed)[0] > oklch(alone)[0], "{mixed:?} against {alone:?}");
        // Two nearly equal tags give nearly equal entries (no jump between anchors).
        let a = entry(&both, [0x33, 0x22, 0x17]);
        let b = entry(&both, [0x34, 0x22, 0x17]);
        for row in 0..ROWS {
            for ch in 0..3 {
                assert!((a[row][ch] as i32 - b[row][ch] as i32).abs() <= 2, "{a:?} {b:?}");
            }
        }
    }

    /// Without an ink the anchor's ink is its shade × 0.6 in linear light, moved like a swatch.
    #[test]
    fn the_default_ink_is_the_shade_darkened() {
        let a = Anchor { ink: None, ..cora() };
        let e = entry(&[a], AUBURN);
        assert_eq!(e[4], shade_ink([44, 8, 2]));
        assert!(e[4][0] < 44);
    }

    /// A relative ink (a brow carrier's) moves its colour alone.
    #[test]
    fn a_relative_ink_follows_the_tag() {
        let brow = [57, 32, 20];
        assert_eq!(ink_entry(AUBURN, brow, AUBURN)[4], brow);
        let on_blond = ink_entry(AUBURN, brow, BLOND)[4];
        assert!(oklch(on_blond)[0] > oklch(brow)[0]);
        let spec = Spec { anchors: vec![cora()], ink: Some((AUBURN, brow)) };
        assert_eq!(spec.entry(AUBURN)[4], brow, "a relative slop.ink takes the ink row");
    }

    /// The palette holds each colour once, writes its column, and gives the nearest when full.
    #[test]
    fn a_palette_places_each_colour_once() {
        let mut images = Assets::<Image>::default();
        let mut p = Palettes::default();
        let id = AssetId::<crate::style::Toon>::default();
        let img = image(&mut images);
        p.add(id, img.clone(), Spec { anchors: vec![cora()], ink: None });
        assert_eq!(p.place(id, AUBURN, &mut images), Some(0));
        assert_eq!(p.place(id, BLOND, &mut images), Some(1));
        assert_eq!(p.place(id, AUBURN, &mut images), Some(0));
        let data = images.get(&img).unwrap().data.clone().unwrap();
        assert_eq!(&data[0..4], &[44, 8, 2, 255]);
        assert_eq!(&data[(ENTRIES + 1) * 4..(ENTRIES + 1) * 4 + 3], &[156, 117, 48]);
        for i in 2..ENTRIES as u32 {
            assert!(p.place(id, [i as u8, 7, 9], &mut images).is_some());
        }
        assert_eq!(p.place(id, [101, 46, 26], &mut images), Some(0), "full: the nearest");
        assert_eq!(tag(3, 4, 0.5), 3 | 4 << 8 | 128 << 16 | 1 << 24 | 1 << 27);
    }
}
