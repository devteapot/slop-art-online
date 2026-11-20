//! A small, exact binary encoding for what a land keeps of its ground ([`crate::land::GroundSource`]):
//! floats by their bits, integers little-endian, lengths before sequences. Nothing is rounded, so
//! a decoded land answers `Land::height` bit for bit as the land it was taken from.

pub(crate) trait Bin: Sized {
    fn put(&self, w: &mut Vec<u8>);
    fn get(r: &mut Reader) -> Result<Self, String>;
}

pub(crate) struct Reader<'a> {
    bytes: &'a [u8],
    at: usize,
}

impl<'a> Reader<'a> {
    pub(crate) fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, at: 0 }
    }

    pub(crate) fn take(&mut self, n: usize) -> Result<&'a [u8], String> {
        let end = self.at.checked_add(n).filter(|&e| e <= self.bytes.len()).ok_or("ground source: truncated")?;
        let s = &self.bytes[self.at..end];
        self.at = end;
        Ok(s)
    }

    /// Bytes read so far.
    pub(crate) fn pos(&self) -> usize {
        self.at
    }
}

macro_rules! num {
    ($($t:ty),*) => {$(
        impl Bin for $t {
            fn put(&self, w: &mut Vec<u8>) {
                w.extend_from_slice(&self.to_le_bytes());
            }
            fn get(r: &mut Reader) -> Result<Self, String> {
                Ok(<$t>::from_le_bytes(r.take(std::mem::size_of::<$t>())?.try_into().expect("size")))
            }
        }
    )*};
}
num!(u8, i8, u16, u32, u64, i32);

impl Bin for f32 {
    fn put(&self, w: &mut Vec<u8>) {
        self.to_bits().put(w);
    }
    fn get(r: &mut Reader) -> Result<Self, String> {
        Ok(f32::from_bits(u32::get(r)?))
    }
}

impl Bin for usize {
    fn put(&self, w: &mut Vec<u8>) {
        (*self as u64).put(w);
    }
    fn get(r: &mut Reader) -> Result<Self, String> {
        usize::try_from(u64::get(r)?).map_err(|_| "ground source: a length out of range".into())
    }
}

impl Bin for bool {
    fn put(&self, w: &mut Vec<u8>) {
        (*self as u8).put(w);
    }
    fn get(r: &mut Reader) -> Result<Self, String> {
        Ok(u8::get(r)? != 0)
    }
}

impl<T: Bin> Bin for Option<T> {
    fn put(&self, w: &mut Vec<u8>) {
        match self {
            None => 0u8.put(w),
            Some(v) => {
                1u8.put(w);
                v.put(w);
            }
        }
    }
    fn get(r: &mut Reader) -> Result<Self, String> {
        Ok(if bool::get(r)? { Some(T::get(r)?) } else { None })
    }
}

impl<T: Bin> Bin for Vec<T> {
    fn put(&self, w: &mut Vec<u8>) {
        self.len().put(w);
        for v in self {
            v.put(w);
        }
    }
    fn get(r: &mut Reader) -> Result<Self, String> {
        let n = usize::get(r)?;
        // Every element takes at least a byte: a corrupt length fails here, not in an allocation.
        if n > r.bytes.len() - r.at {
            return Err("ground source: a length past the end".into());
        }
        (0..n).map(|_| T::get(r)).collect()
    }
}

impl<A: Bin, B: Bin> Bin for (A, B) {
    fn put(&self, w: &mut Vec<u8>) {
        self.0.put(w);
        self.1.put(w);
    }
    fn get(r: &mut Reader) -> Result<Self, String> {
        Ok((A::get(r)?, B::get(r)?))
    }
}

impl<A: Bin, B: Bin, C: Bin> Bin for (A, B, C) {
    fn put(&self, w: &mut Vec<u8>) {
        self.0.put(w);
        self.1.put(w);
        self.2.put(w);
    }
    fn get(r: &mut Reader) -> Result<Self, String> {
        Ok((A::get(r)?, B::get(r)?, C::get(r)?))
    }
}

impl<A: Bin, B: Bin, C: Bin, D: Bin> Bin for (A, B, C, D) {
    fn put(&self, w: &mut Vec<u8>) {
        self.0.put(w);
        self.1.put(w);
        self.2.put(w);
        self.3.put(w);
    }
    fn get(r: &mut Reader) -> Result<Self, String> {
        Ok((A::get(r)?, B::get(r)?, C::get(r)?, D::get(r)?))
    }
}

/// A `Vec<f32>` as `Bin` writes it, read in one pass (the grids: a million values at 4096 m).
pub(crate) fn get_f32s(r: &mut Reader) -> Result<Vec<f32>, String> {
    let n = usize::get(r)?;
    let bytes = r.take(n.checked_mul(4).ok_or("ground source: a length out of range")?)?;
    Ok(bytes.chunks_exact(4).map(|c| f32::from_bits(u32::from_le_bytes([c[0], c[1], c[2], c[3]]))).collect())
}

/// Run-length encoding for long runs of equal bytes (the shore distances: most tiles sit at the
/// clamp, far from any water).
pub(crate) fn put_runs(v: &[i8], w: &mut Vec<u8>) {
    v.len().put(w);
    let mut runs: Vec<(i8, u32)> = Vec::new();
    for &b in v {
        match runs.last_mut() {
            Some((x, n)) if *x == b && *n < u32::MAX => *n += 1,
            _ => runs.push((b, 1)),
        }
    }
    runs.len().put(w);
    for (b, n) in runs {
        b.put(w);
        n.put(w);
    }
}

pub(crate) fn get_runs(r: &mut Reader) -> Result<Vec<i8>, String> {
    let len = usize::get(r)?;
    let runs = usize::get(r)?;
    if runs > r.bytes.len() - r.at {
        return Err("ground source: a length past the end".into());
    }
    let mut v = Vec::with_capacity(len.min(1 << 26));
    for _ in 0..runs {
        let (b, n) = (i8::get(r)?, u32::get(r)? as usize);
        if v.len() + n > len {
            return Err("ground source: runs past their length".into());
        }
        v.resize(v.len() + n, b);
    }
    if v.len() != len {
        return Err("ground source: runs short of their length".into());
    }
    Ok(v)
}
