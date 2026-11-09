//! Platform-independent `f32` transcendental functions for world generation.
//!
//! `f32::exp`, `tanh`, `powf`, `hypot`, `sin`, `cos` and `atan2` call the platform's math
//! library: the system libm on a native client, Rust's bundled port in WASM. Their last bits
//! can differ, which can flip a tile near a threshold. [`crate::land`] and [`crate::settle`]
//! use these functions instead, so the authority (WASM) and a native client generate
//! bit-identical land from the same seed (see `docs/ISLAND_AUTHORITY.md`). Basic arithmetic,
//! `sqrt`, `floor`, `round`, `abs`, `min`, `max` and `powi` with a constant exponent are exact
//! IEEE operations on both and need no wrapper.

pub trait Det: Sized {
    fn d_exp(self) -> Self;
    fn d_tanh(self) -> Self;
    fn d_powf(self, e: Self) -> Self;
    fn d_hypot(self, o: Self) -> Self;
    fn d_sin(self) -> Self;
    fn d_cos(self) -> Self;
    fn d_sin_cos(self) -> (Self, Self);
    fn d_atan2(self, x: Self) -> Self;
}

impl Det for f32 {
    #[inline]
    fn d_exp(self) -> f32 {
        libm::expf(self)
    }
    #[inline]
    fn d_tanh(self) -> f32 {
        libm::tanhf(self)
    }
    #[inline]
    fn d_powf(self, e: f32) -> f32 {
        libm::powf(self, e)
    }
    #[inline]
    fn d_hypot(self, o: f32) -> f32 {
        libm::hypotf(self, o)
    }
    #[inline]
    fn d_sin(self) -> f32 {
        libm::sinf(self)
    }
    #[inline]
    fn d_cos(self) -> f32 {
        libm::cosf(self)
    }
    #[inline]
    fn d_sin_cos(self) -> (f32, f32) {
        libm::sincosf(self)
    }
    #[inline]
    fn d_atan2(self, x: f32) -> f32 {
        libm::atan2f(self, x)
    }
}

/// FNV-1a over bytes, for digests the authority and a client compare.
pub fn fnv1a(mut h: u64, bytes: &[u8]) -> u64 {
    for b in bytes {
        h ^= *b as u64;
        h = h.wrapping_mul(0x0100_0000_01b3);
    }
    h
}

pub const FNV_OFFSET: u64 = 0xcbf2_9ce4_8422_2325;
