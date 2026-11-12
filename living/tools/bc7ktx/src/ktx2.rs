//! KTX 2.0 files (Khronos KTX File Format Specification 2.0, registry.khronos.org/KTX/specs/2.0):
//! one 2D picture, BC7 blocks, every mip level, zstd supercompression of each level.

use crate::Colour;

const IDENTIFIER: [u8; 12] = [0xAB, 0x4B, 0x54, 0x58, 0x20, 0x32, 0x30, 0xBB, 0x0D, 0x0A, 0x1A, 0x0A];
/// VK_FORMAT_BC7_UNORM_BLOCK and VK_FORMAT_BC7_SRGB_BLOCK.
pub const BC7_UNORM: u32 = 145;
pub const BC7_SRGB: u32 = 146;
/// supercompressionScheme: Zstandard (spec §3.11, table 2).
const ZSTD: u32 = 2;
/// The writer's key (spec §5.6.2 `KTXwriter`): the tool and its version, no time.
pub const WRITER: &str = concat!("bc7ktx ", env!("CARGO_PKG_VERSION"), " (intel_tex_2 0.5.0 BC7 slow, ISPC avx2)");

pub fn format_name(vk: u32) -> &'static str {
    match vk {
        BC7_UNORM => "BC7_UNORM_BLOCK",
        BC7_SRGB => "BC7_SRGB_BLOCK",
        _ => "other",
    }
}

/// Levels in a full chain down to 1×1.
pub fn full_chain(w: u32, h: u32) -> usize {
    (32 - w.max(h).max(1).leading_zeros()) as usize
}

/// The basic data format descriptor for BC7 (Khronos Data Format Specification 1.3, §5 and
/// §13.6): colour model BC7, BT.709 primaries, sRGB or linear transfer, straight alpha, 4×4
/// blocks, one 128-bit sample. `bytesPlane0` is 0 because the levels are supercompressed (KTX2
/// §3.10.2).
fn dfd(colour: Colour) -> Vec<u8> {
    let mut b = Vec::new();
    let block_size: u32 = 24 + 16;
    b.extend_from_slice(&(4 + block_size).to_le_bytes()); // dfdTotalSize
    b.extend_from_slice(&0u32.to_le_bytes()); // vendorId 0 (Khronos), descriptorType 0 (basic)
    b.extend_from_slice(&(2u32 | (block_size << 16)).to_le_bytes()); // versionNumber 2, descriptorBlockSize
    b.push(136); // colorModel KHR_DF_MODEL_BC7
    b.push(1); // colorPrimaries KHR_DF_PRIMARIES_BT709
    b.push(match colour {
        Colour::Srgb => 2, // KHR_DF_TRANSFER_SRGB
        Colour::Linear => 1,
    });
    b.push(0); // flags: KHR_DF_FLAG_ALPHA_STRAIGHT
    b.extend_from_slice(&[3, 3, 0, 0]); // texelBlockDimension (less one)
    b.extend_from_slice(&[0; 8]); // bytesPlane0..7
    // The one sample: bit offset 0, 128 bits, channel KHR_DF_CHANNEL_BC7_COLOR (0), at 0,0,
    // lower 0, upper the full range.
    b.extend_from_slice(&0u16.to_le_bytes());
    b.push(127);
    b.push(0);
    b.extend_from_slice(&[0, 0, 0, 0]);
    b.extend_from_slice(&0u32.to_le_bytes());
    b.extend_from_slice(&u32::MAX.to_le_bytes());
    b
}

fn kvd() -> Vec<u8> {
    let mut kv = b"KTXwriter\0".to_vec();
    kv.extend_from_slice(WRITER.as_bytes());
    kv.push(0);
    let mut b = (kv.len() as u32).to_le_bytes().to_vec();
    b.extend_from_slice(&kv);
    while b.len() % 4 != 0 {
        b.push(0);
    }
    b
}

/// A KTX2 file: `levels` are each level's BC7 blocks, level 0 first.
pub fn write(w: u32, h: u32, colour: Colour, levels: &[Vec<u8>], zstd_level: i32) -> Result<Vec<u8>, String> {
    let n = levels.len();
    let packed: Vec<Vec<u8>> = levels.iter().map(|l| zstd::bulk::compress(l, zstd_level).map_err(|e| e.to_string())).collect::<Result<_, _>>()?;
    let dfd = dfd(colour);
    let kvd = kvd();
    let header_len = 12 + 9 * 4 + 4 * 4 + 2 * 8;
    let index_len = n * 24;
    let dfd_off = header_len + index_len;
    let kvd_off = dfd_off + dfd.len();
    let data_off = kvd_off + kvd.len();
    // Levels are stored smallest first (spec §3.9.7); supercompressed levels need no alignment
    // (§3.10.2: lcm is 1 when supercompressed).
    let mut offsets = vec![0usize; n];
    let mut at = data_off;
    for l in (0..n).rev() {
        offsets[l] = at;
        at += packed[l].len();
    }
    let mut f = Vec::with_capacity(at);
    f.extend_from_slice(&IDENTIFIER);
    let vk = match colour {
        Colour::Srgb => BC7_SRGB,
        Colour::Linear => BC7_UNORM,
    };
    for v in [vk, 1, w, h, 0, 0, 1, n as u32, ZSTD] {
        f.extend_from_slice(&v.to_le_bytes()); // vkFormat typeSize width height depth layers faces levels scheme
    }
    for v in [dfd_off as u32, dfd.len() as u32, kvd_off as u32, kvd.len() as u32] {
        f.extend_from_slice(&v.to_le_bytes());
    }
    f.extend_from_slice(&0u64.to_le_bytes()); // sgdByteOffset
    f.extend_from_slice(&0u64.to_le_bytes()); // sgdByteLength
    for l in 0..n {
        for v in [offsets[l] as u64, packed[l].len() as u64, levels[l].len() as u64] {
            f.extend_from_slice(&v.to_le_bytes());
        }
    }
    f.extend_from_slice(&dfd);
    f.extend_from_slice(&kvd);
    for l in (0..n).rev() {
        f.extend_from_slice(&packed[l]);
    }
    debug_assert_eq!(f.len(), at);
    Ok(f)
}

pub struct Ktx2 {
    pub vk_format: u32,
    pub width: u32,
    pub height: u32,
    pub scheme: u32,
    /// The DFD's transfer function (2 sRGB, 1 linear).
    pub transfer: u8,
    /// Each level's blocks, decompressed and checked against its size.
    pub levels: Vec<Vec<u8>>,
    pub writer: Option<String>,
}

fn u32_at(b: &[u8], o: usize) -> Result<u32, String> {
    b.get(o..o + 4).map(|s| u32::from_le_bytes(s.try_into().unwrap())).ok_or_else(|| "truncated".to_string())
}

fn u64_at(b: &[u8], o: usize) -> Result<u64, String> {
    b.get(o..o + 8).map(|s| u64::from_le_bytes(s.try_into().unwrap())).ok_or_else(|| "truncated".to_string())
}

/// Read a BC7 KTX2 file and check it: identifier, a 2D picture, every level present at its
/// size after decompression.
pub fn read(b: &[u8]) -> Result<Ktx2, String> {
    if b.get(..12) != Some(&IDENTIFIER[..]) {
        return Err("not a KTX2 file".into());
    }
    let h: Vec<u32> = (0..9).map(|i| u32_at(b, 12 + i * 4)).collect::<Result<_, _>>()?;
    let [vk, _type_size, width, height, depth, layers, faces, nlevels, scheme] = h[..] else { unreachable!() };
    if depth > 1 || layers > 1 || faces != 1 {
        return Err("not a single 2D picture".into());
    }
    if vk != BC7_UNORM && vk != BC7_SRGB {
        return Err(format!("vkFormat {vk}: not BC7"));
    }
    let dfd_off = u32_at(b, 48)? as usize;
    let kvd_off = u32_at(b, 56)? as usize;
    let kvd_len = u32_at(b, 60)? as usize;
    let transfer = *b.get(dfd_off + 4 + 8 + 2).ok_or("truncated DFD")?;
    let mut levels = Vec::new();
    for l in 0..nlevels.max(1) as usize {
        let e = 80 + l * 24;
        let (off, len, ulen) = (u64_at(b, e)? as usize, u64_at(b, e + 8)? as usize, u64_at(b, e + 16)? as usize);
        let raw = b.get(off..off + len).ok_or_else(|| format!("level {l} outside the file"))?;
        let data = match scheme {
            0 => raw.to_vec(),
            ZSTD => zstd::bulk::decompress(raw, ulen).map_err(|e| format!("level {l}: {e}"))?,
            s => return Err(format!("supercompression {s}")),
        };
        let (lw, lh) = ((width >> l).max(1), (height >> l).max(1));
        let want = (lw.div_ceil(4) * lh.div_ceil(4) * 16) as usize;
        if data.len() != want || ulen != want {
            return Err(format!("level {l}: {} bytes, {want} expected", data.len()));
        }
        levels.push(data);
    }
    let mut writer = None;
    let mut o = kvd_off;
    while o + 4 <= kvd_off + kvd_len {
        let n = u32_at(b, o)? as usize;
        let kv = b.get(o + 4..o + 4 + n).ok_or("truncated KVD")?;
        if let Some(v) = kv.strip_prefix(b"KTXwriter\0") {
            writer = Some(String::from_utf8_lossy(v.strip_suffix(b"\0").unwrap_or(v)).into_owned());
        }
        o += (4 + n).div_ceil(4) * 4;
    }
    Ok(Ktx2 { vk_format: vk, width, height, scheme, transfer, levels, writer })
}
