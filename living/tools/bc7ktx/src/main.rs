//! bc7ktx: a character bundle's pictures as KTX2 (BC7, a full mip chain, zstd supercompression),
//! and the summaries the client reads for them (docs/CHARACTERS.md, "Pictures as KTX2").
//!
//! ```text
//! bc7ktx encode JOBS.json [--threads N]   encode every job (JSON list, below), N at a time
//! bc7ktx thumb IN.png OUT.thumb.png srgb|linear
//! bc7ktx info FILE.ktx2...                 one JSON line a file: format, size, levels, checks
//! bc7ktx decode FILE.ktx2 LEVEL OUT.png    a level decoded to RGBA8 (for judging and errors)
//! bc7ktx error FILE.ktx2 IN.png            level 0 against its source: per-channel RMS and max
//! ```
//!
//! A job: `{"in": "a.png", "out": "a.ktx2", "thumb": "a.thumb.png", "colour": "srgb"|"linear",
//! "mips": "box"|"coverage", "threshold": 0.5, "zstd": 19}` (`thumb`, `threshold`, `zstd` optional).
//!
//! The output depends only on the input and the job: no time, no paths and no thread count go
//! into a file, and on x86_64 the BC7 kernel is pinned to ISPC's AVX2 target, so a machine with
//! AVX-512 writes the same bytes as one without.

use bc7ktx::{bc7, ktx2, mips, read_png, thumb, Colour, R};

use std::path::{Path, PathBuf};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let r = match args.first().map(String::as_str) {
        Some("encode") => encode_cmd(&args[1..]),
        Some("thumb") if args.len() == 4 => thumb_cmd(&args[1], &args[2], &args[3]),
        Some("info") if args.len() >= 2 => info_cmd(&args[1..]),
        Some("decode") if args.len() == 4 => decode_cmd(&args[1], &args[2], &args[3]),
        Some("error") if args.len() == 3 => error_cmd(&args[1], &args[2]),
        _ => Err("usage: bc7ktx encode JOBS.json [--threads N] | thumb IN OUT srgb|linear | info FILE... | decode FILE LEVEL OUT | error FILE IN".into()),
    };
    if let Err(e) = r {
        eprintln!("bc7ktx: {e}");
        std::process::exit(1);
    }
}

struct Job {
    input: PathBuf,
    out: PathBuf,
    thumb: Option<PathBuf>,
    colour: Colour,
    mips: mips::Method,
    zstd: i32,
}

fn parse_jobs(text: &str) -> R<Vec<Job>> {
    let v: serde_json::Value = serde_json::from_str(text).map_err(|e| e.to_string())?;
    let list = v.as_array().ok_or("jobs: a JSON list")?;
    list.iter()
        .map(|j| {
            let s = |k: &str| j.get(k).and_then(|x| x.as_str()).map(str::to_string);
            let threshold = j.get("threshold").and_then(|x| x.as_f64()).unwrap_or(0.5) as f32;
            let mips = match s("mips").as_deref().unwrap_or("box") {
                "box" => mips::Method::Box,
                "coverage" => mips::Method::Coverage(threshold),
                m => return Err(format!("mips {m:?}: box or coverage")),
            };
            Ok(Job {
                input: s("in").ok_or("job without \"in\"")?.into(),
                out: s("out").ok_or("job without \"out\"")?.into(),
                thumb: s("thumb").map(PathBuf::from),
                colour: Colour::parse(&s("colour").ok_or("job without \"colour\"")?)?,
                mips,
                zstd: j.get("zstd").and_then(|x| x.as_i64()).unwrap_or(19) as i32,
            })
        })
        .collect()
}

fn encode_cmd(args: &[String]) -> R<()> {
    let path = args.first().ok_or("encode JOBS.json")?;
    let threads = match args.get(1).map(String::as_str) {
        Some("--threads") => args.get(2).and_then(|n| n.parse().ok()).ok_or("--threads N")?,
        _ => 12usize,
    }
    .max(1);
    let jobs = parse_jobs(&std::fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?)?;
    let next = std::sync::atomic::AtomicUsize::new(0);
    let errors = std::sync::Mutex::new(Vec::new());
    std::thread::scope(|s| {
        for _ in 0..threads.min(jobs.len()) {
            s.spawn(|| loop {
                let i = next.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                let Some(job) = jobs.get(i) else { break };
                if let Err(e) = encode_one(job) {
                    errors.lock().unwrap().push(format!("{}: {e}", job.input.display()));
                }
            });
        }
    });
    let errors = errors.into_inner().unwrap();
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors.join("\n"))
    }
}

fn encode_one(job: &Job) -> R<()> {
    let (w, h, rgba, has_alpha) = read_png(&job.input)?;
    if w % 4 != 0 || h % 4 != 0 {
        return Err(format!("{w}×{h}: BC7's level 0 must be a multiple of 4 on each side"));
    }
    // Opaque when the picture has no alpha or every texel is opaque: BC7's opaque modes then.
    let alpha = has_alpha && rgba.chunks_exact(4).any(|p| p[3] != 255);
    let levels = mips::chain(w, h, &rgba, job.colour, job.mips);
    let mut blocks = Vec::with_capacity(levels.len());
    for l in &levels {
        blocks.push(bc7(l.w, l.h, &l.rgba, alpha));
    }
    let file = ktx2::write(w, h, job.colour, &blocks, job.zstd)?;
    write_atomic(&job.out, &file)?;
    if let Some(t) = &job.thumb {
        write_atomic(t, &thumb::png(&thumb::of(w, h, &rgba, job.colour))?)?;
    }
    Ok(())
}

fn write_atomic(path: &Path, bytes: &[u8]) -> R<()> {
    let tmp = path.with_extension("tmp-bc7ktx");
    std::fs::write(&tmp, bytes).map_err(|e| format!("{}: {e}", tmp.display()))?;
    std::fs::rename(&tmp, path).map_err(|e| format!("{}: {e}", path.display()))
}

fn thumb_cmd(input: &str, out: &str, colour: &str) -> R<()> {
    let (w, h, rgba, _) = read_png(Path::new(input))?;
    write_atomic(Path::new(out), &thumb::png(&thumb::of(w, h, &rgba, Colour::parse(colour)?))?)
}

fn info_cmd(files: &[String]) -> R<()> {
    for f in files {
        let bytes = std::fs::read(f).map_err(|e| format!("{f}: {e}"))?;
        let line = match ktx2::read(&bytes) {
            Ok(k) => serde_json::json!({
                "file": f,
                "ok": true,
                "vk_format": k.vk_format,
                "format": ktx2::format_name(k.vk_format),
                "transfer": match k.transfer { 2 => "srgb", 1 => "linear", _ => "other" },
                "width": k.width,
                "height": k.height,
                "levels": k.levels.len(),
                "full_chain": ktx2::full_chain(k.width, k.height),
                "supercompression": match k.scheme { 2 => "zstd", 0 => "none", _ => "other" },
                "bytes": bytes.len(),
                "level_bytes": k.levels.iter().map(Vec::len).collect::<Vec<_>>(),
                "gpu_bytes": k.levels.iter().map(Vec::len).sum::<usize>(),
                "writer": k.writer,
            }),
            Err(e) => serde_json::json!({"file": f, "ok": false, "error": e}),
        };
        println!("{line}");
    }
    Ok(())
}

/// A level decoded to RGBA8 texels, `w`×`h`.
fn decode_level(k: &ktx2::Ktx2, level: usize) -> R<(u32, u32, Vec<u8>)> {
    let data = k.levels.get(level).ok_or("no such level")?;
    let (w, h) = ((k.width >> level).max(1), (k.height >> level).max(1));
    let (bw, bh) = (w.div_ceil(4), h.div_ceil(4));
    let mut out = vec![0u8; (bw * 4 * bh * 4 * 4) as usize];
    let pitch = (bw * 4 * 4) as usize;
    for by in 0..bh {
        for bx in 0..bw {
            let b = &data[((by * bw + bx) * 16) as usize..][..16];
            let off = (by * 4) as usize * pitch + (bx * 16) as usize;
            bcdec_rs::bc7(b, &mut out[off..], pitch);
        }
    }
    let mut cropped = Vec::with_capacity((w * h * 4) as usize);
    for y in 0..h as usize {
        cropped.extend_from_slice(&out[y * pitch..y * pitch + (w * 4) as usize]);
    }
    Ok((w, h, cropped))
}

fn decode_cmd(file: &str, level: &str, out: &str) -> R<()> {
    let k = ktx2::read(&std::fs::read(file).map_err(|e| format!("{file}: {e}"))?)?;
    let (w, h, px) = decode_level(&k, level.parse().map_err(|_| "LEVEL: a number")?)?;
    image::save_buffer(out, &px, w, h, image::ColorType::Rgba8).map_err(|e| e.to_string())
}

fn error_cmd(file: &str, input: &str) -> R<()> {
    let k = ktx2::read(&std::fs::read(file).map_err(|e| format!("{file}: {e}"))?)?;
    let (w, h, px) = decode_level(&k, 0)?;
    let (sw, sh, src, _) = read_png(Path::new(input))?;
    if (w, h) != (sw, sh) {
        return Err(format!("{w}×{h} against {sw}×{sh}"));
    }
    let mut sq = [0f64; 4];
    let mut max = [0u8; 4];
    for (a, b) in px.chunks_exact(4).zip(src.chunks_exact(4)) {
        for c in 0..4 {
            let d = a[c].abs_diff(b[c]);
            sq[c] += (d as f64).powi(2);
            max[c] = max[c].max(d);
        }
    }
    let n = (w * h) as f64;
    let rms: Vec<f64> = sq.iter().map(|s| (s / n).sqrt()).collect();
    let psnr_rgb = 10.0 * (255f64.powi(2) / ((sq[0] + sq[1] + sq[2]) / (3.0 * n)).max(1e-12)).log10();
    println!("{}", serde_json::json!({"file": file, "rms": rms, "max": max, "psnr_rgb": psnr_rgb}));
    Ok(())
}
