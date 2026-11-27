//! The body controller's capture (docs/NEURAL_BODY.md §5, "Replay", and "Built (pilot plumbing)"):
//! the training data format, outside the database. One JSON line per record, in bounded files:
//! - `decision`: per decision, the observation as encoded (the vector and the delivered rows it was
//!   built from), the brief and the delegated leaf it was conditioned on, the policy, the intent, the
//!   controller epoch and sequence;
//! - `reply`: the authority's answer to each intent sent (accepted, or the refusal's words; a refused
//!   input changes nothing), by the decision's sequence;
//! - `outcome`: the authority's resolved outcome of each skill use (`my_skill_uses`: accepted,
//!   released, what happened), as it is delivered;
//! - `session`: an epoch opened, a stall, a lapse;
//! - `layout`: once per file set's start, the sizes of the flat vector's parts;
//! - `memory`: a character's memory reset (a new epoch or brief revision).
//!
//! A `decision` holds what cloning needs: `flat` (the encoded observation, then the memory the policy
//! read: its recurrent state and intent history), `memory_after`, the brief with its traits, the
//! role and the policy's version, the intent (and `intent_encoded`) and what was sent; its replies
//! and the use's outcome follow by actor, epoch, sequence and time.
//!
//! Files rotate at `LIVING_BODY_CAPTURE_FILE_MB` (default 16) and at most `LIVING_BODY_CAPTURE_FILES`
//! (default 8) are kept, the oldest removed first, so the capture never holds more than their
//! product. Off unless `LIVING_BODY_CAPTURE` names a folder.

use serde_json::Value;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::PathBuf;

/// The format's version, in every line (`v`).
pub const VERSION: u32 = 1;

pub struct Capture {
    dir: PathBuf,
    file_bytes: u64,
    files: usize,
    out: Option<(File, u64, u32)>,
    next: u32,
}

impl Capture {
    /// From the environment; `None` when capture is off.
    pub fn from_env() -> anyhow::Result<Option<Capture>> {
        let Some(dir) = std::env::var_os("LIVING_BODY_CAPTURE").map(PathBuf::from) else { return Ok(None) };
        let mb: u64 = std::env::var("LIVING_BODY_CAPTURE_FILE_MB").ok().and_then(|v| v.parse().ok()).unwrap_or(16);
        let files: usize = std::env::var("LIVING_BODY_CAPTURE_FILES").ok().and_then(|v| v.parse().ok()).unwrap_or(8);
        Ok(Some(Capture::new(dir, mb.max(1) * 1024 * 1024, files.max(1))?))
    }

    pub fn new(dir: PathBuf, file_bytes: u64, files: usize) -> anyhow::Result<Capture> {
        fs::create_dir_all(&dir)?;
        let next = Self::numbers(&dir).last().map_or(0, |n| n + 1);
        Ok(Capture { dir, file_bytes, files, out: None, next })
    }

    fn numbers(dir: &PathBuf) -> Vec<u32> {
        let mut n: Vec<u32> = fs::read_dir(dir)
            .map(|d| d.filter_map(|e| e.ok()).filter_map(|e| e.file_name().to_str().and_then(|s| s.strip_prefix("body-")).and_then(|s| s.strip_suffix(".jsonl")).and_then(|s| s.parse().ok())).collect())
            .unwrap_or_default();
        n.sort_unstable();
        n
    }

    /// Write one record (`kind`, with the format version and the wall time added).
    pub fn write(&mut self, kind: &str, mut record: Value) {
        if let Value::Object(m) = &mut record {
            m.insert("v".into(), VERSION.into());
            m.insert("kind".into(), kind.into());
            m.insert("wall_ms".into(), crate::llm::now_ms().into());
        }
        let mut line = record.to_string();
        line.push('\n');
        if let Err(e) = self.put(line.as_bytes()) {
            log::warn!("body capture: {e:#}");
        }
    }

    fn put(&mut self, bytes: &[u8]) -> anyhow::Result<()> {
        let full = self.out.as_ref().is_some_and(|(_, n, _)| *n + bytes.len() as u64 > self.file_bytes);
        if full || self.out.is_none() {
            let n = self.next;
            self.next += 1;
            let f = OpenOptions::new().create(true).append(true).open(self.dir.join(format!("body-{n:06}.jsonl")))?;
            self.out = Some((f, 0, n));
            // The oldest go once there are more files than kept.
            let all = Self::numbers(&self.dir);
            if all.len() > self.files {
                for old in &all[..all.len() - self.files] {
                    let _ = fs::remove_file(self.dir.join(format!("body-{old:06}.jsonl")));
                }
            }
        }
        let (f, n, _) = self.out.as_mut().expect("open");
        f.write_all(bytes)?;
        *n += bytes.len() as u64;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn files_rotate_and_the_oldest_go() {
        let dir = std::env::temp_dir().join(format!("body-capture-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        let mut c = Capture::new(dir.clone(), 200, 2).unwrap();
        for i in 0..20 {
            c.write("decision", serde_json::json!({"seq": i, "pad": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}));
        }
        let kept = Capture::numbers(&dir);
        assert_eq!(kept.len(), 2, "{kept:?}");
        let total: u64 = kept.iter().map(|n| fs::metadata(dir.join(format!("body-{n:06}.jsonl"))).unwrap().len()).sum();
        assert!(total <= 2 * 200, "{total}");
        let last = fs::read_to_string(dir.join(format!("body-{:06}.jsonl", kept[1]))).unwrap();
        let rec: Value = serde_json::from_str(last.lines().last().unwrap()).unwrap();
        assert_eq!(rec["seq"], 19);
        assert_eq!(rec["v"], VERSION);
        assert_eq!(rec["kind"], "decision");
        let _ = fs::remove_dir_all(&dir);
    }
}
