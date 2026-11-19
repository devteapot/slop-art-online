//! bc7ktx against the client's own code: Bevy 0.20.1's image loader and KTX2 loader (the
//! client's versions), and `Thumb::of` as it stands in living/game/src/characters.rs.
//!
//! `BC7KTX_PICTURES=DIR` adds every PNG under DIR (a bundle's pictures, say) to the summary
//! check; without it the test uses pictures of its own.

use bc7ktx::{ktx2, mips, thumb, Colour};
use bevy_asset::RenderAssetUsages;
use bevy_image::{CompressedImageFormats, Image, ImageSampler, ImageType};
use bevy_math::Vec4;
use std::path::{Path, PathBuf};

const THUMB: u32 = 64;
const THUMB_SAMPLES: u32 = 4;

/// `Thumb::of`, copied verbatim from the client (living/game/src/characters.rs); `client_copy`
/// below fails when the client's changes.
fn client_thumb_of(img: &Image) -> Option<Vec<Vec4>> {
    // --- verbatim from here ---
        let (w, h) = (img.width().max(1), img.height().max(1));
        img.data.as_ref()?;
        let n = THUMB * THUMB_SAMPLES;
        let mut cells = vec![Vec4::ZERO; (THUMB * THUMB) as usize];
        for sy in 0..n {
            for sx in 0..n {
                let (x, y) = (((sx as f32 + 0.5) / n as f32 * w as f32) as u32, ((sy as f32 + 0.5) / n as f32 * h as f32) as u32);
                let Ok(c) = img.get_color_at(x.min(w - 1), y.min(h - 1)) else { continue };
                let l = c.to_linear();
                cells[((sy / THUMB_SAMPLES) * THUMB + sx / THUMB_SAMPLES) as usize] += Vec4::new(l.red * l.alpha, l.green * l.alpha, l.blue * l.alpha, l.alpha);
            }
        }
        let k = 1.0 / (THUMB_SAMPLES * THUMB_SAMPLES) as f32;
    // --- to here ---
    Some(cells.into_iter().map(|c| c * k).collect())
}

fn body(text: &str) -> String {
    let a = text.find("let (w, h) = (img.width().max(1), img.height().max(1));").expect("Thumb::of's first line");
    let b = a + text[a..].find("let k = 1.0 / (THUMB_SAMPLES * THUMB_SAMPLES) as f32;").expect("Thumb::of's scale");
    text[a..b].split_whitespace().collect::<Vec<_>>().join(" ")
}

#[test]
fn client_copy() {
    let client = std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../game/src/characters.rs")).expect("the client's characters.rs");
    let ours = std::fs::read_to_string(file!()).unwrap();
    let ours = &ours[ours.find("// --- verbatim from here ---").unwrap()..];
    assert_eq!(body(ours), body(&client[client.find("impl Thumb {").expect("impl Thumb")..]), "the client's Thumb::of changed: update thumb.rs and this copy");
    for line in ["const THUMB: u32 = 64;", "const THUMB_SAMPLES: u32 = 4;", "Some(Self { cells: cells.into_iter().map(|c| c * k).collect() })"] {
        assert!(client.contains(line), "the client no longer has {line:?}");
    }
}

/// A picture of noise with flat areas and thin lines, deterministic.
fn picture(w: u32, h: u32, alpha: bool, seed: u32) -> Vec<u8> {
    let mut s = seed.wrapping_mul(2654435761).wrapping_add(1);
    let mut next = || {
        s ^= s << 13;
        s ^= s >> 17;
        s ^= s << 5;
        s
    };
    let mut px = Vec::with_capacity((w * h * 4) as usize);
    for y in 0..h {
        for x in 0..w {
            let r = next();
            let line = y % 37 == 0 || x % 53 == 1;
            let flat = (x / 64 + y / 64) % 2 == 0;
            let c = if line { [30, 20, 10] } else if flat { [230, 190, 160] } else { [(r & 255) as u8, (r >> 8 & 255) as u8, (r >> 16 & 255) as u8] };
            let a = if !alpha { 255 } else if line { 255 } else if flat { 0 } else { (r >> 24) as u8 };
            px.extend_from_slice(&[c[0], c[1], c[2], a]);
        }
    }
    px
}

fn png_bytes(w: u32, h: u32, px: &[u8], alpha: bool) -> Vec<u8> {
    let mut out = std::io::Cursor::new(Vec::new());
    if alpha {
        image::RgbaImage::from_raw(w, h, px.to_vec()).unwrap().write_to(&mut out, image::ImageFormat::Png).unwrap();
    } else {
        let rgb: Vec<u8> = px.chunks_exact(4).flat_map(|p| [p[0], p[1], p[2]]).collect();
        image::RgbImage::from_raw(w, h, rgb).unwrap().write_to(&mut out, image::ImageFormat::Png).unwrap();
    }
    out.into_inner()
}

fn pictures() -> Vec<(String, Vec<u8>)> {
    let mut v = vec![
        ("own rgb 1024".to_string(), png_bytes(1024, 1024, &picture(1024, 1024, false, 1), false)),
        ("own rgba 512".to_string(), png_bytes(512, 512, &picture(512, 512, true, 2), true)),
        ("own rgba 1600x720".to_string(), png_bytes(1600, 720, &picture(1600, 720, true, 3), true)),
        ("own rgb 100x60".to_string(), png_bytes(100, 60, &picture(100, 60, false, 4), false)),
    ];
    if let Ok(dir) = std::env::var("BC7KTX_PICTURES") {
        let mut files = Vec::new();
        walk(Path::new(&dir), &mut files);
        files.sort();
        for f in files {
            v.push((f.display().to_string(), std::fs::read(&f).unwrap()));
        }
    }
    v
}

fn walk(d: &Path, out: &mut Vec<PathBuf>) {
    for e in std::fs::read_dir(d).unwrap() {
        let p = e.unwrap().path();
        if p.is_dir() {
            walk(&p, out);
        } else if p.extension().is_some_and(|x| x == "png") && !p.to_string_lossy().ends_with(".thumb.png") {
            out.push(p);
        }
    }
}

#[test]
fn thumbs_are_the_clients() {
    let pictures = pictures();
    eprintln!("thumbs: {} pictures, sRGB and linear each", pictures.len());
    for (name, bytes) in pictures {
        for srgb in [true, false] {
            let img = Image::from_buffer(&bytes, ImageType::Extension("png"), CompressedImageFormats::NONE, srgb, ImageSampler::Default, RenderAssetUsages::default()).unwrap();
            let theirs = client_thumb_of(&img).unwrap();
            let tmp = std::env::temp_dir().join(format!("bc7ktx-test-{}.png", std::process::id()));
            std::fs::write(&tmp, &bytes).unwrap();
            let (w, h, px, _) = bc7ktx::read_png(&tmp).unwrap();
            std::fs::remove_file(&tmp).ok();
            let ours = thumb::of(w, h, &px, if srgb { Colour::Srgb } else { Colour::Linear });
            for (i, (a, b)) in ours.iter().zip(&theirs).enumerate() {
                assert_eq!(a.map(f32::to_bits), b.to_array().map(f32::to_bits), "{name} srgb={srgb} cell {i}: {a:?} against the client's {b:?}");
            }
            // The PNG gives the cells back within half a step of 16 bits.
            let png = thumb::png(&ours).unwrap();
            let back = image::load_from_memory(&png).unwrap();
            assert!(matches!(back, image::DynamicImage::ImageRgba16(_)));
            let back = back.into_rgba16();
            assert_eq!(back.dimensions(), (64, 64));
            for (c, p) in theirs.iter().zip(back.pixels()) {
                for k in 0..4 {
                    assert!((p.0[k] as f32 / 65535.0 - c[k]).abs() <= 0.5 / 65535.0 + 1e-7, "{name}: 16-bit cell off");
                }
            }
        }
    }
}

fn encode(w: u32, h: u32, px: &[u8], colour: Colour, method: mips::Method) -> Vec<u8> {
    let alpha = px.chunks_exact(4).any(|p| p[3] != 255);
    let levels = mips::chain(w, h, px, colour, method);
    let blocks: Vec<Vec<u8>> = levels.iter().map(|l| bc7ktx::bc7(l.w, l.h, &l.rgba, alpha)).collect();
    ktx2::write(w, h, colour, &blocks, 19).unwrap()
}

#[test]
fn bevy_loads_the_files() {
    for (w, h, alpha, colour) in [(1024, 1024, false, Colour::Srgb), (512, 512, true, Colour::Srgb), (1600, 720, true, Colour::Srgb), (512, 512, false, Colour::Linear), (192, 192, false, Colour::Srgb)] {
        let px = picture(w, h, alpha, w + h);
        let file = encode(w, h, &px, colour, if alpha { mips::Method::Coverage(0.5) } else { mips::Method::Box });
        let srgb = colour == Colour::Srgb;
        let img = Image::from_buffer(&file, ImageType::Extension("ktx2"), CompressedImageFormats::BC, srgb, ImageSampler::Default, RenderAssetUsages::default()).unwrap();
        let levels = ktx2::full_chain(w, h);
        assert_eq!(img.texture_descriptor.mip_level_count as usize, levels);
        assert_eq!((img.width(), img.height()), (w, h));
        assert_eq!(img.texture_descriptor.format, if srgb { wgpu_types::TextureFormat::Bc7RgbaUnormSrgb } else { wgpu_types::TextureFormat::Bc7RgbaUnorm });
        let want: usize = (0..levels).map(|l| (((w >> l).max(1).div_ceil(4)) * ((h >> l).max(1).div_ceil(4)) * 16) as usize).sum();
        assert_eq!(img.data.as_ref().unwrap().len(), want);
        // Without BC on the device the loader refuses it (the client's warning case).
        assert!(Image::from_buffer(&file, ImageType::Extension("ktx2"), CompressedImageFormats::NONE, srgb, ImageSampler::Default, RenderAssetUsages::default()).is_err());
        // The ktx2 crate (Bevy's reader) agrees on the header and the DFD.
        let r = ::ktx2::Reader::new(&file[..]).unwrap();
        let hd = r.header();
        assert_eq!(hd.format, Some(if srgb { ::ktx2::Format::BC7_SRGB_BLOCK } else { ::ktx2::Format::BC7_UNORM_BLOCK }));
        assert_eq!(hd.supercompression_scheme, Some(::ktx2::SupercompressionScheme::Zstandard));
        assert_eq!(hd.level_count as usize, levels);
        // Ours reads it back the same.
        let k = ktx2::read(&file).unwrap();
        assert_eq!(k.transfer, if srgb { 2 } else { 1 });
        assert_eq!(k.levels.len(), levels);
    }
}

#[test]
fn same_bytes_every_time() {
    let px = picture(512, 512, true, 9);
    let a = encode(512, 512, &px, Colour::Srgb, mips::Method::Coverage(0.5));
    let b = encode(512, 512, &px, Colour::Srgb, mips::Method::Coverage(0.5));
    assert_eq!(a, b);
}

#[test]
fn coverage_keeps_thin_marks() {
    // A one-texel line of opaque ink over a soft wash (alpha 0.2) on the left half, 256²: a box
    // halves the line's alpha each level down; coverage holds it at the threshold or above and
    // leaves the wash as the box has it.
    let (w, h) = (256u32, 256u32);
    let mut px = vec![0u8; (w * h * 4) as usize];
    for y in 0..h {
        for x in 0..w / 2 {
            let i = ((y * w + x) * 4) as usize;
            px[i..i + 4].copy_from_slice(&[200, 120, 120, 51]);
        }
    }
    for x in 0..w {
        let i = ((100 * w + x) * 4) as usize;
        px[i..i + 4].copy_from_slice(&[40, 20, 10, 255]);
    }
    let boxed = mips::chain(w, h, &px, Colour::Srgb, mips::Method::Box);
    let kept = mips::chain(w, h, &px, Colour::Srgb, mips::Method::Coverage(0.5));
    let line_a = |l: &mips::Level| (0..l.h).map(|y| l.rgba[((y * l.w + l.w * 3 / 4) * 4 + 3) as usize]).max().unwrap();
    assert!(line_a(&boxed[2]) < 80, "a box fades the line: {}", line_a(&boxed[2]));
    for l in &kept[1..7] {
        assert!(line_a(l) >= 127, "{}×{}: the line keeps its ink: {}", l.w, l.h, line_a(l));
        // Its colour stays the ink's (straight alpha).
        let x = l.w * 3 / 4;
        let p = (0..l.h).map(|y| &l.rgba[((y * l.w + x) * 4) as usize..][..4]).max_by_key(|p| p[3]).unwrap();
        assert!(p[0].abs_diff(40) <= 2 && p[1].abs_diff(20) <= 2, "{p:?}");
    }
    // The wash away from the line is the box's.
    for (b, k) in boxed[1..7].iter().zip(&kept[1..7]) {
        let i = ((b.w / 8) * 4) as usize; // row 0: above the line at every level here
        assert_eq!(b.rgba[i..i + 4], k.rgba[i..i + 4], "{}×{}", b.w, b.h);
    }
}
