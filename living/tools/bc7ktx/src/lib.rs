//! bc7ktx's library: the encoder's parts, shared by the binary and its tests.

pub mod ktx2;
pub mod mips;
pub mod thumb;

use std::path::Path;

pub type R<T> = Result<T, String>;

/// A PNG as RGBA8, as Bevy's image loader expands it (RGB gets alpha 255, grey is spread to RGB).
pub fn read_png(path: &Path) -> R<(u32, u32, Vec<u8>, bool)> {
    let bytes = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let img = image::load_from_memory_with_format(&bytes, image::ImageFormat::Png).map_err(|e| format!("{}: {e}", path.display()))?;
    let has_alpha = img.color().has_alpha();
    if img.color().bytes_per_pixel() / img.color().channel_count() != 1 {
        return Err(format!("{}: only 8-bit pictures are encoded", path.display()));
    }
    let rgba = img.into_rgba8();
    let (w, h) = rgba.dimensions();
    Ok((w, h, rgba.into_raw(), has_alpha))
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Colour {
    Srgb,
    Linear,
}

impl Colour {
    pub fn parse(s: &str) -> R<Self> {
        match s {
            "srgb" => Ok(Self::Srgb),
            "linear" => Ok(Self::Linear),
            _ => Err(format!("colour {s:?}: srgb or linear")),
        }
    }
}

/// One level's BC7 blocks. A level whose sides are not a multiple of 4 (the small mips) is
/// padded by repeating its last row and column, as the GPU reads only the texels inside.
pub fn bc7(w: u32, h: u32, rgba: &[u8], alpha: bool) -> Vec<u8> {
    let (pw, ph) = (w.div_ceil(4) * 4, h.div_ceil(4) * 4);
    let mut padded = vec![0u8; (pw * ph * 4) as usize];
    for y in 0..ph {
        for x in 0..pw {
            let s = ((y.min(h - 1) * w + x.min(w - 1)) * 4) as usize;
            let d = ((y * pw + x) * 4) as usize;
            padded[d..d + 4].copy_from_slice(&rgba[s..s + 4]);
        }
    }
    let settings = if alpha { intel_tex_2::bc7::alpha_slow_settings() } else { intel_tex_2::bc7::opaque_slow_settings() };
    let surface = intel_tex_2::RgbaSurface { data: &padded, width: pw, height: ph, stride: pw * 4 };
    let mut out = vec![0u8; intel_tex_2::bc7::calc_output_size(pw, ph)];
    pinned::compress(&settings, &surface, &mut out);
    out
}

/// The BC7 kernel on one ISPC target. `intel_tex_2`'s own entry picks the target from the CPU at
/// run time (SSE2 … AVX-512), and the targets need not round alike.
mod pinned {
    use intel_tex_2::bindings::kernel::{bc7_enc_settings, rgba_surface};

    #[cfg(target_arch = "x86_64")]
    unsafe extern "C" {
        fn CompressBlocksBC7_ispc_avx2(src: *mut rgba_surface, dst: *mut u8, settings: *mut bc7_enc_settings);
    }

    pub fn compress(s: &intel_tex_2::bc7::EncodeSettings, surface: &intel_tex_2::RgbaSurface, blocks: &mut [u8]) {
        #[cfg(target_arch = "x86_64")]
        {
            let ok = ["avx2", "fma", "f16c", "bmi1", "bmi2", "lzcnt", "popcnt"].iter().all(|f| match *f {
                "avx2" => std::arch::is_x86_feature_detected!("avx2"),
                "fma" => std::arch::is_x86_feature_detected!("fma"),
                "f16c" => std::arch::is_x86_feature_detected!("f16c"),
                "bmi1" => std::arch::is_x86_feature_detected!("bmi1"),
                "bmi2" => std::arch::is_x86_feature_detected!("bmi2"),
                "lzcnt" => std::arch::is_x86_feature_detected!("lzcnt"),
                _ => std::arch::is_x86_feature_detected!("popcnt"),
            });
            assert!(ok, "bc7ktx needs an x86_64 CPU with AVX2 (the kernel is pinned to ISPC's AVX2 target)");
            let mut surf = rgba_surface { width: surface.width as i32, height: surface.height as i32, stride: surface.stride as i32, ptr: surface.data.as_ptr() as *mut u8 };
            let mut set = bc7_enc_settings {
                mode_selection: s.mode_selection,
                refineIterations: s.refine_iterations.map(|r| r as i32),
                skip_mode2: s.skip_mode2,
                fastSkipTreshold_mode1: s.fast_skip_threshold_mode1 as i32,
                fastSkipTreshold_mode3: s.fast_skip_threshold_mode3 as i32,
                fastSkipTreshold_mode7: s.fast_skip_threshold_mode7 as i32,
                mode45_channel0: s.mode45_channel0 as i32,
                refineIterations_channel: s.refine_iterations_channel as i32,
                channels: s.channels,
            };
            assert_eq!(blocks.len(), intel_tex_2::bc7::calc_output_size(surface.width, surface.height));
            // SAFETY: the surface covers width×height RGBA8 texels at `stride` (asserted by the
            // caller's padding), and `blocks` holds one 16-byte block per 4×4 tile.
            unsafe { CompressBlocksBC7_ispc_avx2(&mut surf, blocks.as_mut_ptr(), &mut set) };
        }
        #[cfg(not(target_arch = "x86_64"))]
        intel_tex_2::bc7::compress_blocks_into(s, surface, blocks);
    }
}

