//! Compact CPU recurrent policy (`RoleNet`, ~23.3k parameters) and pure-Rust imitation trainer
//! for the §7 neural-body pilot (docs/NEURAL_BODY.md "Pilot run").
//!
//! - Input: `flat` = `encoded` (`encode::LEN` = 99) || `memory.state` (16) || `memory.history` (32) = 147 floats.
//! - Hidden 1: Linear(147 -> 96) + tanh (14,208 params).
//! - Hidden 2: Linear(96 -> 64) + tanh (6,208 params).
//! - Gated recurrent state update: `z = sigmoid(W_z h2 + b_z)`, `c = tanh(W_c h2 + b_c)`,
//!   `state' = (1 - z) * state + z * c` (2,080 params).
//! - Action head: Linear(64 -> 13) (845 params):
//!   - 0: move logit (sigmoid > move_thresh -> move, else stop)
//!   - 1..3: move direction (dx, dy), normalized
//!   - 3: run logit (sigmoid > 0.5 -> run)
//!   - 4..6: face direction (dx, dy), normalized
//!   - 6..12: skill categorical logits `[none, slot_0, slot_1, slot_2, slot_3, release_block]`
//!   - 12: reserved auxiliary scalar (0)
//! - Total parameters: 23,341 (~93.4 KB FP32). CPU only, no CUDA, deterministic weights hash.

use super::encode::{self, BriefView, Observation, SlotView};
use super::policy::{self, Intent, Memory, Policy, STATE};
use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::time::Instant;

pub const IN_DIM: usize = encode::LEN + policy::MEMORY; // 99 + 48 = 147
pub const H1: usize = 96;
pub const H2: usize = 64;
pub const OUT_DIM: usize = 13;
pub const SKILL_CLASSES: usize = 6; // 0=none, 1..=4=slot 0..3, 5=release

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RoleNetWeights {
    pub version: String,
    pub role: String,
    pub in_dim: usize,
    pub h1: usize,
    pub h2: usize,
    pub state_dim: usize,
    pub out_dim: usize,
    pub param_count: usize,
    /// Per-feature mean/std for `flat` (state dims 99..115 use mean=0, std=1).
    pub norm_mean: Vec<f32>,
    pub norm_std: Vec<f32>,
    /// Skill press probability threshold (tuned on validation split; default 0.5).
    pub skill_thresh: f32,
    /// Minimum ms between consecutive presses of the same skill (0 = disabled; pure net output).
    pub press_cooldown_ms: u64,
    pub w1: Vec<f32>,
    pub b1: Vec<f32>,
    pub w2: Vec<f32>,
    pub b2: Vec<f32>,
    pub wz: Vec<f32>,
    pub bz: Vec<f32>,
    pub wc: Vec<f32>,
    pub bc: Vec<f32>,
    pub wo: Vec<f32>,
    pub bo: Vec<f32>,
}

impl RoleNetWeights {
    pub fn param_count_expected() -> usize {
        IN_DIM * H1 + H1 + H1 * H2 + H2 + H2 * STATE + STATE + H2 * STATE + STATE + H2 * OUT_DIM + OUT_DIM
    }

    pub fn seeded_init(role: &str, seed: u64) -> Self {
        let mut rng = Rng64::new(seed);
        let xavier = |rng: &mut Rng64, fan_in: usize, fan_out: usize| -> Vec<f32> {
            let lim = (6.0f32 / (fan_in + fan_out) as f32).sqrt();
            (0..fan_in * fan_out).map(|_| rng.uniform(-lim, lim)).collect()
        };
        let mut w = Self {
            version: String::new(),
            role: role.to_string(),
            in_dim: IN_DIM,
            h1: H1,
            h2: H2,
            state_dim: STATE,
            out_dim: OUT_DIM,
            param_count: Self::param_count_expected(),
            norm_mean: vec![0.0; IN_DIM],
            norm_std: vec![1.0; IN_DIM],
            skill_thresh: 0.5,
            press_cooldown_ms: 0,
            w1: xavier(&mut rng, IN_DIM, H1),
            b1: vec![0.0; H1],
            w2: xavier(&mut rng, H1, H2),
            b2: vec![0.0; H2],
            wz: xavier(&mut rng, H2, STATE),
            bz: vec![-1.0; STATE], // start with conservative state update gate
            wc: xavier(&mut rng, H2, STATE),
            bc: vec![0.0; STATE],
            wo: xavier(&mut rng, H2, OUT_DIM),
            bo: vec![0.0; OUT_DIM],
        };
        w.rehash();
        w
    }

    pub fn rehash(&mut self) {
        let mut h = blake3::Hasher::new();
        for slice in [&self.w1, &self.b1, &self.w2, &self.b2, &self.wz, &self.bz, &self.wc, &self.bc, &self.wo, &self.bo] {
            for &x in slice {
                h.update(&x.to_le_bytes());
            }
        }
        let hex = h.finalize().to_hex();
        self.version = format!("rolenet-{}", &hex[..12]);
    }
}

pub struct RoleNet {
    pub w: RoleNetWeights,
}

impl RoleNet {
    pub fn new(w: RoleNetWeights) -> Result<Self> {
        if w.in_dim != IN_DIM || w.h1 != H1 || w.h2 != H2 || w.state_dim != STATE || w.out_dim != OUT_DIM {
            return Err(anyhow!(
                "RoleNet shape mismatch: got ({},{},{},{},{}) expected ({},{},{},{},{})",
                w.in_dim, w.h1, w.h2, w.state_dim, w.out_dim, IN_DIM, H1, H2, STATE, OUT_DIM
            ));
        }
        Ok(Self { w })
    }

    pub fn load(path: &Path) -> Result<Self> {
        let text = std::fs::read_to_string(path).with_context(|| format!("read weights {}", path.display()))?;
        let w: RoleNetWeights = serde_json::from_str(&text).with_context(|| format!("parse weights {}", path.display()))?;
        Self::new(w)
    }

    pub fn save(&self, path: &Path) -> Result<()> {
        if let Some(p) = path.parent() {
            std::fs::create_dir_all(p)?;
        }
        let text = serde_json::to_string(&self.w)?;
        std::fs::write(path, text)?;
        Ok(())
    }

    /// Forward pass: returns `(out[13], next_state[16], h1[96], h2[64], z[16], c[16], x_norm[147])`.
    #[inline]
    pub fn forward_full(&self, flat: &[f32; IN_DIM]) -> ([f32; OUT_DIM], [f32; STATE], [f32; H1], [f32; H2], [f32; STATE], [f32; STATE], [f32; IN_DIM]) {
        let mut x = [0.0f32; IN_DIM];
        for i in 0..IN_DIM {
            let v = if flat[i].is_finite() { flat[i] } else { 0.0 };
            x[i] = ((v - self.w.norm_mean[i]) / self.w.norm_std[i]).clamp(-10.0, 10.0);
        }
        let mut h1 = [0.0f32; H1];
        for o in 0..H1 {
            let mut sum = self.w.b1[o];
            let row = &self.w.w1[o * IN_DIM..(o + 1) * IN_DIM];
            for i in 0..IN_DIM {
                sum += row[i] * x[i];
            }
            h1[o] = sum.tanh();
        }
        let mut h2 = [0.0f32; H2];
        for o in 0..H2 {
            let mut sum = self.w.b2[o];
            let row = &self.w.w2[o * H1..(o + 1) * H1];
            for i in 0..H1 {
                sum += row[i] * h1[i];
            }
            h2[o] = sum.tanh();
        }
        let mut z = [0.0f32; STATE];
        let mut c = [0.0f32; STATE];
        let mut next_state = [0.0f32; STATE];
        for s in 0..STATE {
            let mut sz = self.w.bz[s];
            let mut sc = self.w.bc[s];
            let rz = &self.w.wz[s * H2..(s + 1) * H2];
            let rc = &self.w.wc[s * H2..(s + 1) * H2];
            for i in 0..H2 {
                sz += rz[i] * h2[i];
                sc += rc[i] * h2[i];
            }
            z[s] = sigmoid(sz);
            c[s] = sc.tanh();
            let prev_s = flat[encode::LEN + s];
            next_state[s] = (1.0 - z[s]) * prev_s + z[s] * c[s];
        }
        let mut out = [0.0f32; OUT_DIM];
        for o in 0..OUT_DIM {
            let mut sum = self.w.bo[o];
            let row = &self.w.wo[o * H2..(o + 1) * H2];
            for i in 0..H2 {
                sum += row[i] * h2[i];
            }
            out[o] = sum;
        }
        (out, next_state, h1, h2, z, c, x)
    }

    pub fn forward(&self, flat: &[f32; IN_DIM]) -> ([f32; OUT_DIM], [f32; STATE]) {
        let (out, next_state, ..) = self.forward_full(flat);
        (out, next_state)
    }
}

impl Policy for RoleNet {
    fn name(&self) -> &str {
        "role-net"
    }

    fn version(&self) -> String {
        self.w.version.clone()
    }

    fn decide(&self, o: &Observation, encoded: &[f32], m: &mut Memory, brief: Option<&BriefView>, slot: &SlotView) -> Intent {
        let mut out = Intent::default();
        let Some(here) = o.here() else { return out };
        if encoded.len() != encode::LEN {
            return out;
        }
        let mut flat = [0.0f32; IN_DIM];
        flat[..encode::LEN].copy_from_slice(encoded);
        let mem = m.flat();
        flat[encode::LEN..].copy_from_slice(&mem);
        let (raw, next_state) = self.forward(&flat);
        m.state = next_state;

        // Movement head.
        let move_p = sigmoid(raw[0]);
        let (mx, my) = (raw[1], raw[2]);
        let mn = mx.hypot(my);
        let run = sigmoid(raw[3]) > 0.5;
        if move_p > 0.5 && mn > 0.15 {
            out.moving = Some((mx / mn, my / mn, run));
        } else {
            out.moving = Some((0.0, 0.0, false));
        }

        // Facing head.
        let (fx, fy) = (raw[4], raw[5]);
        let fn_ = fx.hypot(fy);
        if fn_ > 0.15 {
            out.face = Some((fx / fn_, fy / fn_));
        }

        // Skill head: softmax over [none, slot_0, slot_1, slot_2, slot_3, release].
        let probs = softmax6(&raw[6..12]);
        let mut best_cls = 0usize;
        let mut best_p = probs[0];
        for i in 1..SKILL_CLASSES {
            if probs[i] > best_p {
                best_p = probs[i];
                best_cls = i;
            }
        }
        // Also allow selecting top non-none skill if its probability exceeds skill_thresh.
        if best_cls == 0 {
            let mut top_act = 1usize;
            for i in 2..SKILL_CLASSES {
                if probs[i] > probs[top_act] {
                    top_act = i;
                }
            }
            if probs[top_act] >= self.w.skill_thresh {
                best_cls = top_act;
            }
        }

        let target_id = if slot.target != 0 { slot.target } else { brief.map_or(0, |b| b.target) };
        if best_cls == 5 {
            // Release held guard.
            if slot.skills.iter().any(|s| s == "block") {
                out.release = Some("block".into());
            }
        } else if (1..=4).contains(&best_cls) {
            if let Some(skill) = slot.skills.get(best_cls - 1) {
                let (ax, ay) = match skill.as_str() {
                    "dodge" | "jump" => {
                        if mn > 0.15 {
                            (here.0 + mx / mn, here.1 + my / mn)
                        } else {
                            (here.0, here.1)
                        }
                    }
                    "block" => {
                        if fn_ > 0.15 {
                            (here.0 + fx / fn_, here.1 + fy / fn_)
                        } else {
                            (here.0, here.1)
                        }
                    }
                    _ => {
                        if let Some(t) = o.other(target_id) {
                            Observation::at(t, o.now_ms)
                        } else if fn_ > 0.15 {
                            (here.0 + fx / fn_ * 2.0, here.1 + fy / fn_ * 2.0)
                        } else {
                            (here.0, here.1)
                        }
                    }
                };
                out.press = Some((skill.clone(), target_id, ax, ay));
            }
        }
        out
    }
}

#[inline]
fn sigmoid(x: f32) -> f32 {
    1.0 / (1.0 + (-x.clamp(-20.0, 20.0)).exp())
}

#[inline]
fn softmax6(logits: &[f32]) -> [f32; SKILL_CLASSES] {
    let mut m = f32::NEG_INFINITY;
    for &x in logits.iter().take(SKILL_CLASSES) {
        if x > m {
            m = x;
        }
    }
    let mut ex = [0.0f32; SKILL_CLASSES];
    let mut sum = 0.0f32;
    for i in 0..SKILL_CLASSES {
        ex[i] = (logits[i] - m).exp();
        sum += ex[i];
    }
    for e in &mut ex {
        *e /= sum.max(1e-12);
    }
    ex
}

struct Rng64(u64);
impl Rng64 {
    fn new(seed: u64) -> Self {
        Self(seed.wrapping_add(0x9E37_79B9_7F4A_7C15))
    }
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    fn f32(&mut self) -> f32 {
        ((self.next_u64() >> 40) as f32) / ((1u64 << 24) as f32)
    }
    fn uniform(&mut self, lo: f32, hi: f32) -> f32 {
        lo + (hi - lo) * self.f32()
    }
    fn shuffle<T>(&mut self, slice: &mut [T]) {
        for i in (1..slice.len()).rev() {
            let j = (self.next_u64() as usize) % (i + 1);
            slice.swap(i, j);
        }
    }
}

// ---- Pure-Rust CPU imitation trainer (BPTT + AdamW + exact 2D rotation augmentation) ----

#[derive(Clone, Debug, Deserialize)]
pub struct TrainSample {
    pub episode: String,
    pub split: String, // "train" | "val" | "test"
    pub encoded: Vec<f32>,
    pub history: Vec<f32>, // 32 floats
    pub move_active: f32,  // 0.0 or 1.0
    pub move_dx: f32,
    pub move_dy: f32,
    pub run: f32,
    pub face_active: f32,
    pub face_dx: f32,
    pub face_dy: f32,
    pub skill_class: usize, // 0..6
    pub was_rooted: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct TrainReport {
    pub weights_path: String,
    pub policy_version: String,
    pub param_count: usize,
    pub train_samples: usize,
    pub val_samples: usize,
    pub train_episodes: usize,
    pub val_episodes: usize,
    pub epochs_run: usize,
    pub best_epoch: usize,
    pub best_val_loss: f32,
    pub final_train_loss: f32,
    pub skill_thresh: f32,
    pub val_metrics: EvalMetrics,
    pub wall_s: f32,
    pub replay_hash: String,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct EvalMetrics {
    pub total_loss: f32,
    pub move_acc: f32,
    pub move_cos: f32,
    pub run_acc: f32,
    pub face_cos: f32,
    pub skill_acc: f32,
    pub skill_macro_f1: f32,
    pub per_class_tp: [u64; SKILL_CLASSES],
    pub per_class_fp: [u64; SKILL_CLASSES],
    pub per_class_fn: [u64; SKILL_CLASSES],
}

/// Exact 2D rotation of all relative/velocity `(x, y)` pairs in `encoded`, `history`, and labels.
fn rotate_sample(s: &TrainSample, cos_t: f32, sin_t: f32) -> TrainSample {
    let rot = |x: f32, y: f32| (x * cos_t - y * sin_t, x * sin_t + y * cos_t);
    let mut out = s.clone();
    // Self velocity: encoded[1, 2].
    let (vx, vy) = rot(out.encoded[1], out.encoded[2]);
    out.encoded[1] = vx;
    out.encoded[2] = vy;
    // Target + 3 others slots (each 12 floats starting at OWN=10): (+1,+2) dx,dy; (+4,+5) vx,vy.
    for k in 0..(1 + encode::OTHERS) {
        let base = encode::OWN + k * encode::SLOT;
        let (dx, dy) = rot(out.encoded[base + 1], out.encoded[base + 2]);
        out.encoded[base + 1] = dx;
        out.encoded[base + 2] = dy;
        let (ovx, ovy) = rot(out.encoded[base + 4], out.encoded[base + 5]);
        out.encoded[base + 4] = ovx;
        out.encoded[base + 5] = ovy;
    }
    // Intent history (4 x 8 floats): (+1, +2) move unit vector.
    for h in 0..policy::HISTORY {
        let base = h * policy::INTENT;
        let (hx, hy) = rot(out.history[base + 1], out.history[base + 2]);
        out.history[base + 1] = hx;
        out.history[base + 2] = hy;
    }
    let (mx, my) = rot(out.move_dx, out.move_dy);
    out.move_dx = mx;
    out.move_dy = my;
    let (fx, fy) = rot(out.face_dx, out.face_dy);
    out.face_dx = fx;
    out.face_dy = fy;
    out
}

struct Grads {
    w1: Vec<f32>,
    b1: Vec<f32>,
    w2: Vec<f32>,
    b2: Vec<f32>,
    wz: Vec<f32>,
    bz: Vec<f32>,
    wc: Vec<f32>,
    bc: Vec<f32>,
    wo: Vec<f32>,
    bo: Vec<f32>,
}

impl Grads {
    fn zeros() -> Self {
        Self {
            w1: vec![0.0; IN_DIM * H1],
            b1: vec![0.0; H1],
            w2: vec![0.0; H1 * H2],
            b2: vec![0.0; H2],
            wz: vec![0.0; H2 * STATE],
            bz: vec![0.0; STATE],
            wc: vec![0.0; H2 * STATE],
            bc: vec![0.0; STATE],
            wo: vec![0.0; H2 * OUT_DIM],
            bo: vec![0.0; OUT_DIM],
        }
    }
    fn clear(&mut self) {
        for v in [&mut self.w1, &mut self.b1, &mut self.w2, &mut self.b2, &mut self.wz, &mut self.bz, &mut self.wc, &mut self.bc, &mut self.wo, &mut self.bo] {
            v.fill(0.0);
        }
    }
    fn scale_and_clip(&mut self, inv_n: f32, max_norm: f32) {
        let mut sq = 0.0f64;
        for v in [&mut self.w1, &mut self.b1, &mut self.w2, &mut self.b2, &mut self.wz, &mut self.bz, &mut self.wc, &mut self.bc, &mut self.wo, &mut self.bo] {
            for x in v.iter_mut() {
                *x *= inv_n;
                sq += (*x as f64) * (*x as f64);
            }
        }
        let norm = sq.sqrt() as f32;
        if norm > max_norm && norm.is_finite() {
            let s = max_norm / norm;
            for v in [&mut self.w1, &mut self.b1, &mut self.w2, &mut self.b2, &mut self.wz, &mut self.bz, &mut self.wc, &mut self.bc, &mut self.wo, &mut self.bo] {
                for x in v.iter_mut() {
                    *x *= s;
                }
            }
        }
    }
}

struct AdamW {
    m: Grads,
    v: Grads,
    step: u32,
}

impl AdamW {
    fn new() -> Self {
        Self { m: Grads::zeros(), v: Grads::zeros(), step: 0 }
    }
    fn update(&mut self, w: &mut RoleNetWeights, g: &Grads, lr: f32, wd: f32) {
        self.step += 1;
        let b1 = 0.9f32;
        let b2 = 0.999f32;
        let eps = 1e-8f32;
        let bc1 = 1.0 - b1.powi(self.step as i32);
        let bc2 = 1.0 - b2.powi(self.step as i32);
        let apply = |p: &mut [f32], gr: &[f32], m: &mut [f32], v: &mut [f32], decay: f32| {
            for i in 0..p.len() {
                let gi = gr[i];
                m[i] = b1 * m[i] + (1.0 - b1) * gi;
                v[i] = b2 * v[i] + (1.0 - b2) * gi * gi;
                let mh = m[i] / bc1;
                let vh = v[i] / bc2;
                p[i] = p[i] * (1.0 - lr * decay) - lr * mh / (vh.sqrt() + eps);
            }
        };
        apply(&mut w.w1, &g.w1, &mut self.m.w1, &mut self.v.w1, wd);
        apply(&mut w.b1, &g.b1, &mut self.m.b1, &mut self.v.b1, 0.0);
        apply(&mut w.w2, &g.w2, &mut self.m.w2, &mut self.v.w2, wd);
        apply(&mut w.b2, &g.b2, &mut self.m.b2, &mut self.v.b2, 0.0);
        apply(&mut w.wz, &g.wz, &mut self.m.wz, &mut self.v.wz, wd);
        apply(&mut w.bz, &g.bz, &mut self.m.bz, &mut self.v.bz, 0.0);
        apply(&mut w.wc, &g.wc, &mut self.m.wc, &mut self.v.wc, wd);
        apply(&mut w.bc, &g.bc, &mut self.m.bc, &mut self.v.bc, 0.0);
        apply(&mut w.wo, &g.wo, &mut self.m.wo, &mut self.v.wo, wd);
        apply(&mut w.bo, &g.bo, &mut self.m.bo, &mut self.v.bo, 0.0);
    }
}

/// Forward + truncated BPTT backward over one sequence chunk (same episode), accumulating into `grads`.
fn bptt_chunk(net: &RoleNet, chunk: &[TrainSample], init_state: [f32; STATE], class_w: &[f32; SKILL_CLASSES], grads: &mut Grads) -> (f32, [f32; STATE]) {
    let t_len = chunk.len();
    let mut cache_x = Vec::with_capacity(t_len);
    let mut cache_h1 = Vec::with_capacity(t_len);
    let mut cache_h2 = Vec::with_capacity(t_len);
    let mut cache_z = Vec::with_capacity(t_len);
    let mut cache_c = Vec::with_capacity(t_len);
    let mut cache_prev_s = Vec::with_capacity(t_len);
    let mut cache_out = Vec::with_capacity(t_len);

    let mut state = init_state;
    let mut total_loss = 0.0f32;

    for s in chunk {
        let mut flat = [0.0f32; IN_DIM];
        flat[..encode::LEN].copy_from_slice(&s.encoded);
        flat[encode::LEN..encode::LEN + STATE].copy_from_slice(&state);
        flat[encode::LEN + STATE..].copy_from_slice(&s.history);
        let (out, next_state, h1, h2, z, c, x) = net.forward_full(&flat);
        cache_prev_s.push(state);
        cache_x.push(x);
        cache_h1.push(h1);
        cache_h2.push(h2);
        cache_z.push(z);
        cache_c.push(c);
        cache_out.push(out);
        state = next_state;
    }

    let mut d_next_state = [0.0f32; STATE];

    for t in (0..t_len).rev() {
        let s = &chunk[t];
        let out = &cache_out[t];
        let mut d_out = [0.0f32; OUT_DIM];

        // 1. Movement & run losses (masked when rooted in a windup/dash).
        if !s.was_rooted {
            let mp = sigmoid(out[0]);
            let y_m = s.move_active;
            total_loss += -(y_m * mp.max(1e-7).ln() + (1.0 - y_m) * (1.0 - mp).max(1e-7).ln());
            d_out[0] = mp - y_m;

            if y_m > 0.5 {
                let ex = out[1] - s.move_dx;
                let ey = out[2] - s.move_dy;
                total_loss += 1.5 * (ex * ex + ey * ey);
                d_out[1] = 3.0 * ex;
                d_out[2] = 3.0 * ey;

                let rp = sigmoid(out[3]);
                let y_r = s.run;
                total_loss += 0.5 * -(y_r * rp.max(1e-7).ln() + (1.0 - y_r) * (1.0 - rp).max(1e-7).ln());
                d_out[3] = 0.5 * (rp - y_r);
            }
        }

        // 2. Facing loss (when target/facing active).
        if s.face_active > 0.5 {
            let ex = out[4] - s.face_dx;
            let ey = out[5] - s.face_dy;
            total_loss += 0.5 * (ex * ex + ey * ey);
            d_out[4] = ex;
            d_out[5] = ey;
        }

        // 3. Skill categorical cross-entropy (class-weighted).
        let probs = softmax6(&out[6..12]);
        let cls = s.skill_class.min(SKILL_CLASSES - 1);
        let cw = class_w[cls];
        total_loss += 2.0 * cw * -probs[cls].max(1e-7).ln();
        for i in 0..SKILL_CLASSES {
            let target = if i == cls { 1.0 } else { 0.0 };
            d_out[6 + i] = 2.0 * cw * (probs[i] - target);
        }

        // Backprop through output head -> d_h2.
        let h2 = &cache_h2[t];
        let mut d_h2 = [0.0f32; H2];
        for o in 0..OUT_DIM {
            let go = d_out[o];
            grads.bo[o] += go;
            let row_w = &net.w.wo[o * H2..(o + 1) * H2];
            let row_g = &mut grads.wo[o * H2..(o + 1) * H2];
            for i in 0..H2 {
                row_g[i] += go * h2[i];
                d_h2[i] += go * row_w[i];
            }
        }

        // Backprop through gated recurrent state: next_s = (1 - z) * prev_s + z * c.
        let z = &cache_z[t];
        let c = &cache_c[t];
        let prev_s = &cache_prev_s[t];
        let mut d_prev_s = [0.0f32; STATE];
        for k in 0..STATE {
            let ds = d_next_state[k];
            d_prev_s[k] += ds * (1.0 - z[k]);
            let dz = ds * (c[k] - prev_s[k]) * z[k] * (1.0 - z[k]);
            let dc = ds * z[k] * (1.0 - c[k] * c[k]);
            grads.bz[k] += dz;
            grads.bc[k] += dc;
            let rz_w = &net.w.wz[k * H2..(k + 1) * H2];
            let rc_w = &net.w.wc[k * H2..(k + 1) * H2];
            let rz_g = &mut grads.wz[k * H2..(k + 1) * H2];
            let rc_g = &mut grads.wc[k * H2..(k + 1) * H2];
            for i in 0..H2 {
                rz_g[i] += dz * h2[i];
                rc_g[i] += dc * h2[i];
                d_h2[i] += dz * rz_w[i] + dc * rc_w[i];
            }
        }

        // Backprop through Layer 2 (tanh).
        let h1 = &cache_h1[t];
        let mut d_h1 = [0.0f32; H1];
        for o in 0..H2 {
            let pre = d_h2[o] * (1.0 - h2[o] * h2[o]);
            grads.b2[o] += pre;
            let row_w = &net.w.w2[o * H1..(o + 1) * H1];
            let row_g = &mut grads.w2[o * H1..(o + 1) * H1];
            for i in 0..H1 {
                row_g[i] += pre * h1[i];
                d_h1[i] += pre * row_w[i];
            }
        }

        // Backprop through Layer 1 (tanh) -> d_x (for state slice encode::LEN..encode::LEN+STATE).
        let x = &cache_x[t];
        for o in 0..H1 {
            let pre = d_h1[o] * (1.0 - h1[o] * h1[o]);
            grads.b1[o] += pre;
            let row_w = &net.w.w1[o * IN_DIM..(o + 1) * IN_DIM];
            let row_g = &mut grads.w1[o * IN_DIM..(o + 1) * IN_DIM];
            for i in 0..IN_DIM {
                row_g[i] += pre * x[i];
            }
            for k in 0..STATE {
                let idx = encode::LEN + k;
                d_prev_s[k] += pre * row_w[idx] / net.w.norm_std[idx];
            }
        }
        d_next_state = d_prev_s;
    }

    (total_loss / t_len as f32, state)
}

fn evaluate(net: &RoleNet, episodes: &[Vec<TrainSample>], class_w: &[f32; SKILL_CLASSES], skill_thresh: f32) -> EvalMetrics {
    let mut m = EvalMetrics::default();
    let mut n_total = 0u64;
    let mut n_move_eval = 0u64;
    let mut move_ok = 0u64;
    let mut n_move_dir = 0u64;
    let mut move_cos_sum = 0.0f64;
    let mut run_ok = 0u64;
    let mut n_face = 0u64;
    let mut face_cos_sum = 0.0f64;
    let mut skill_ok = 0u64;
    let mut loss_sum = 0.0f64;

    for ep in episodes {
        let mut state = [0.0f32; STATE];
        for s in ep {
            let mut flat = [0.0f32; IN_DIM];
            flat[..encode::LEN].copy_from_slice(&s.encoded);
            flat[encode::LEN..encode::LEN + STATE].copy_from_slice(&state);
            flat[encode::LEN + STATE..].copy_from_slice(&s.history);
            let (out, next_s) = net.forward(&flat);
            state = next_s;
            n_total += 1;

            if !s.was_rooted {
                let mp = sigmoid(out[0]);
                loss_sum += -(s.move_active * mp.max(1e-7).ln() + (1.0 - s.move_active) * (1.0 - mp).max(1e-7).ln()) as f64;
                n_move_eval += 1;
                if (mp > 0.5) == (s.move_active > 0.5) {
                    move_ok += 1;
                }
                if s.move_active > 0.5 {
                    let ex = out[1] - s.move_dx;
                    let ey = out[2] - s.move_dy;
                    loss_sum += 1.5 * (ex * ex + ey * ey) as f64;
                    let n = out[1].hypot(out[2]).max(1e-6);
                    move_cos_sum += ((out[1] * s.move_dx + out[2] * s.move_dy) / n) as f64;
                    n_move_dir += 1;
                    let rp = sigmoid(out[3]);
                    loss_sum += 0.5 * -(s.run * rp.max(1e-7).ln() + (1.0 - s.run) * (1.0 - rp).max(1e-7).ln()) as f64;
                    if (rp > 0.5) == (s.run > 0.5) {
                        run_ok += 1;
                    }
                }
            }
            if s.face_active > 0.5 {
                let ex = out[4] - s.face_dx;
                let ey = out[5] - s.face_dy;
                loss_sum += 0.5 * (ex * ex + ey * ey) as f64;
                let n = out[4].hypot(out[5]).max(1e-6);
                face_cos_sum += ((out[4] * s.face_dx + out[5] * s.face_dy) / n) as f64;
                n_face += 1;
            }
            let probs = softmax6(&out[6..12]);
            let cls = s.skill_class.min(SKILL_CLASSES - 1);
            loss_sum += (2.0 * class_w[cls] * -probs[cls].max(1e-7).ln()) as f64;
            let mut pred = 0usize;
            let mut best = probs[0];
            for i in 1..SKILL_CLASSES {
                if probs[i] > best {
                    best = probs[i];
                    pred = i;
                }
            }
            if pred == 0 {
                let mut top = 1usize;
                for i in 2..SKILL_CLASSES {
                    if probs[i] > probs[top] {
                        top = i;
                    }
                }
                if probs[top] >= skill_thresh {
                    pred = top;
                }
            }
            if pred == cls {
                skill_ok += 1;
                m.per_class_tp[cls] += 1;
            } else {
                m.per_class_fp[pred] += 1;
                m.per_class_fn[cls] += 1;
            }
        }
    }
    m.total_loss = (loss_sum / n_total.max(1) as f64) as f32;
    m.move_acc = move_ok as f32 / n_move_eval.max(1) as f32;
    m.move_cos = (move_cos_sum / n_move_dir.max(1) as f64) as f32;
    m.run_acc = run_ok as f32 / n_move_dir.max(1) as f32;
    m.face_cos = (face_cos_sum / n_face.max(1) as f64) as f32;
    m.skill_acc = skill_ok as f32 / n_total.max(1) as f32;
    let mut f1_sum = 0.0f32;
    let mut active_classes = 0u32;
    for i in 0..SKILL_CLASSES {
        let support = m.per_class_tp[i] + m.per_class_fn[i];
        if support > 0 {
            let denom = 2 * m.per_class_tp[i] + m.per_class_fp[i] + m.per_class_fn[i];
            f1_sum += if denom > 0 { (2 * m.per_class_tp[i]) as f32 / denom as f32 } else { 0.0 };
            active_classes += 1;
        }
    }
    m.skill_macro_f1 = if active_classes > 0 { f1_sum / active_classes as f32 } else { 0.0 };
    m
}

/// Deterministic forward-pass replay hash on fixed synthetic inputs (Stop Rule 4).
pub fn replay_hash(net: &RoleNet) -> String {
    let mut h = blake3::Hasher::new();
    let mut state = [0.0f32; STATE];
    for step in 0..32u32 {
        let mut flat = [0.0f32; IN_DIM];
        for i in 0..encode::LEN {
            flat[i] = ((step as f32 * 0.13 + i as f32 * 0.07).sin()) * 0.5;
        }
        flat[encode::LEN..encode::LEN + STATE].copy_from_slice(&state);
        let (out, next_s) = net.forward(&flat);
        state = next_s;
        for &v in &out {
            h.update(&v.to_le_bytes());
        }
        for &v in &state {
            h.update(&v.to_le_bytes());
        }
    }
    h.finalize().to_hex()[..16].to_string()
}

pub fn train_main(args: Vec<String>) -> Result<()> {
    let mut data_path = None::<String>;
    let mut out_weights = None::<String>;
    let mut out_report = None::<String>;
    let mut epochs: usize = 25;
    let mut lr: f32 = 2e-3;
    let mut seed: u64 = 42;
    let mut chunk_len: usize = 16;
    let mut rot_aug: bool = true;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--data" => {
                i += 1;
                data_path = args.get(i).cloned();
            }
            "--out" => {
                i += 1;
                out_weights = args.get(i).cloned();
            }
            "--report" => {
                i += 1;
                out_report = args.get(i).cloned();
            }
            "--epochs" => {
                i += 1;
                epochs = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(25);
            }
            "--lr" => {
                i += 1;
                lr = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(2e-3);
            }
            "--seed" => {
                i += 1;
                seed = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(42);
            }
            "--chunk" => {
                i += 1;
                chunk_len = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(16);
            }
            "--no-rot-aug" => {
                rot_aug = false;
            }
            _ => {}
        }
        i += 1;
    }
    if epochs > 40 {
        return Err(anyhow!("STOP_BUDGET_CAP: epochs {epochs} > 40"));
    }
    let data_path = data_path.ok_or_else(|| anyhow!("--data <dataset.jsonl> required"))?;
    let out_weights = out_weights.ok_or_else(|| anyhow!("--out <weights.json> required"))?;
    let t0 = Instant::now();

    // Load episode-ordered samples.
    let f = File::open(&data_path).with_context(|| format!("open {data_path}"))?;
    let mut train_map: std::collections::BTreeMap<String, Vec<TrainSample>> = Default::default();
    let mut val_map: std::collections::BTreeMap<String, Vec<TrainSample>> = Default::default();
    for line in BufReader::new(f).lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let s: TrainSample = serde_json::from_str(&line)?;
        if s.encoded.len() != encode::LEN || s.history.len() != policy::HISTORY * policy::INTENT {
            continue;
        }
        match s.split.as_str() {
            "train" => train_map.entry(s.episode.clone()).or_default().push(s),
            "val" => val_map.entry(s.episode.clone()).or_default().push(s),
            _ => {}
        }
    }
    let train_eps: Vec<Vec<TrainSample>> = train_map.into_values().collect();
    let val_eps: Vec<Vec<TrainSample>> = val_map.into_values().collect();
    let train_n: usize = train_eps.iter().map(|e| e.len()).sum();
    let val_n: usize = val_eps.iter().map(|e| e.len()).sum();
    if train_n == 0 || val_n == 0 {
        return Err(anyhow!("empty split: train={train_n}, val={val_n}"));
    }

    // Compute per-feature normalization on train split ONLY (state dims left identity).
    let mut mean = vec![0.0f64; IN_DIM];
    let mut m2 = vec![0.0f64; IN_DIM];
    let mut counts = [0u64; SKILL_CLASSES];
    for ep in &train_eps {
        for s in ep {
            counts[s.skill_class.min(SKILL_CLASSES - 1)] += 1;
            for j in 0..encode::LEN {
                mean[j] += s.encoded[j] as f64;
            }
            for j in 0..(policy::HISTORY * policy::INTENT) {
                mean[encode::LEN + STATE + j] += s.history[j] as f64;
            }
        }
    }
    for j in 0..IN_DIM {
        if (encode::LEN..encode::LEN + STATE).contains(&j) {
            mean[j] = 0.0;
        } else {
            mean[j] /= train_n as f64;
        }
    }
    for ep in &train_eps {
        for s in ep {
            for j in 0..encode::LEN {
                let d = s.encoded[j] as f64 - mean[j];
                m2[j] += d * d;
            }
            for j in 0..(policy::HISTORY * policy::INTENT) {
                let idx = encode::LEN + STATE + j;
                let d = s.history[j] as f64 - mean[idx];
                m2[idx] += d * d;
            }
        }
    }
    let mut w = RoleNetWeights::seeded_init("person", seed);
    for j in 0..IN_DIM {
        if (encode::LEN..encode::LEN + STATE).contains(&j) {
            w.norm_mean[j] = 0.0;
            w.norm_std[j] = 1.0;
        } else {
            // Keep directional (x,y) features zero-mean so exact 2D rotation augmentation is centered.
            w.norm_mean[j] = mean[j] as f32;
            w.norm_std[j] = ((m2[j] / train_n as f64).sqrt() as f32).max(0.05);
        }
    }
    // Zero-center 2D vector slots when rot_aug is enabled so rotated vectors share identical scale/mean.
    if rot_aug {
        let vec_pairs: Vec<(usize, usize)> = {
            let mut v = vec![(1, 2)];
            for k in 0..(1 + encode::OTHERS) {
                let b = encode::OWN + k * encode::SLOT;
                v.push((b + 1, b + 2));
                v.push((b + 4, b + 5));
            }
            for h in 0..policy::HISTORY {
                let b = encode::LEN + STATE + h * policy::INTENT;
                v.push((b + 1, b + 2));
            }
            v
        };
        for (ix, iy) in vec_pairs {
            w.norm_mean[ix] = 0.0;
            w.norm_mean[iy] = 0.0;
            let std = w.norm_std[ix].max(w.norm_std[iy]);
            w.norm_std[ix] = std;
            w.norm_std[iy] = std;
        }
    }

    // Class weights: inverse-sqrt frequency capped at [1.0, 6.0] so rare skills (dodge/block/strike) learn without spamming.
    let mut class_w = [1.0f32; SKILL_CLASSES];
    let c0 = counts[0].max(1) as f32;
    for i in 1..SKILL_CLASSES {
        if counts[i] > 0 {
            class_w[i] = (c0 / counts[i] as f32).sqrt().clamp(1.0, 6.0);
        }
    }
    log::info!("body-train: train={train_n} ({} eps), val={val_n} ({} eps), params={}, skill_counts={counts:?}, class_w={class_w:?}", train_eps.len(), val_eps.len(), w.param_count);

    let mut net = RoleNet::new(w)?;
    let mut opt = AdamW::new();
    let mut grads = Grads::zeros();
    let mut rng = Rng64::new(seed ^ 0xA5A5_5A5A);
    let mut best_val = f32::INFINITY;
    let mut best_epoch = 0usize;
    let mut best_weights = net.w.clone();
    let mut final_train_loss = 0.0f32;
    let batch_chunks = 8usize;

    for ep_idx in 1..=epochs {
        // Cosine LR schedule.
        let frac = (ep_idx - 1) as f32 / epochs.max(1) as f32;
        let cur_lr = lr * (0.05 + 0.95 * 0.5 * (1.0 + (std::f32::consts::PI * frac).cos()));

        let mut ep_order: Vec<usize> = (0..train_eps.len()).collect();
        rng.shuffle(&mut ep_order);

        let mut ep_loss = 0.0f64;
        let mut ep_chunks = 0u64;
        let mut acc_chunks = 0usize;
        grads.clear();

        for &ei in &ep_order {
            let raw_ep = &train_eps[ei];
            let angle = if rot_aug { rng.uniform(0.0, std::f32::consts::TAU) } else { 0.0 };
            let (ct, st) = (angle.cos(), angle.sin());
            let mut state = [0.0f32; STATE];
            let mut pos = 0usize;
            while pos < raw_ep.len() {
                let end = (pos + chunk_len).min(raw_ep.len());
                // Causal-confusion regularization (De Haan et al. 2019): drop autoregressive
                // self-velocity (`encoded[1..3]`) and past-intent history (`history`) on 85% of
                // training chunks (and replace with random directions on 10%) so the policy cannot
                // lock onto its own prior velocity/rest state and must steer from target + brief.
                let drop_mode = rng.f32();
                let (rand_x, rand_y) = {
                    let a = rng.uniform(0.0, std::f32::consts::TAU);
                    (a.cos(), a.sin())
                };
                let slice: Vec<TrainSample> = raw_ep[pos..end]
                    .iter()
                    .map(|s| {
                        let mut x = if rot_aug { rotate_sample(s, ct, st) } else { s.clone() };
                        if drop_mode < 0.75 {
                            x.encoded[1] = 0.0;
                            x.encoded[2] = 0.0;
                            x.history.fill(0.0);
                        } else if drop_mode < 0.90 {
                            // Perturb self-velocity and move history to a random direction so the net
                            // learns to override mismatched inertia (e.g. returning after a dodge!).
                            x.encoded[1] = rand_x * 0.3;
                            x.encoded[2] = rand_y * 0.3;
                            for h in 0..policy::HISTORY {
                                let b = h * policy::INTENT;
                                x.history[b] = 1.0;
                                x.history[b + 1] = rand_x;
                                x.history[b + 2] = rand_y;
                            }
                        }
                        x
                    })
                    .collect();
                let (closs, next_s) = bptt_chunk(&net, &slice, state, &class_w, &mut grads);
                state = next_s;
                ep_loss += closs as f64;
                ep_chunks += 1;
                acc_chunks += 1;
                if acc_chunks >= batch_chunks {
                    grads.scale_and_clip(1.0 / acc_chunks as f32, 5.0);
                    opt.update(&mut net.w, &grads, cur_lr, 1e-4);
                    grads.clear();
                    acc_chunks = 0;
                }
                pos = end;
            }
        }
        if acc_chunks > 0 {
            grads.scale_and_clip(1.0 / acc_chunks as f32, 5.0);
            opt.update(&mut net.w, &grads, cur_lr, 1e-4);
            grads.clear();
        }
        final_train_loss = (ep_loss / ep_chunks.max(1) as f64) as f32;
        let vm = evaluate(&net, &val_eps, &class_w, 0.5);
        if vm.total_loss < best_val {
            best_val = vm.total_loss;
            best_epoch = ep_idx;
            best_weights = net.w.clone();
        }
        if ep_idx == 1 || ep_idx % 5 == 0 || ep_idx == epochs {
            eprintln!(
                "epoch {ep_idx:2}/{epochs}: lr={cur_lr:.5} train_loss={final_train_loss:.4} val_loss={:.4} move_acc={:.3} move_cos={:.3} skill_acc={:.3} skill_f1={:.3}",
                vm.total_loss, vm.move_acc, vm.move_cos, vm.skill_acc, vm.skill_macro_f1
            );
        }
    }

    // Tune skill_thresh on val split ONLY (pick threshold maximizing macro F1 over [0.30..0.75]).
    best_weights.rehash();
    let mut best_net = RoleNet::new(best_weights)?;
    let mut best_th = 0.5f32;
    let mut best_f1 = -1.0f32;
    let mut best_vm = EvalMetrics::default();
    for step in 0..10 {
        let th = 0.30 + step as f32 * 0.05;
        let vm = evaluate(&best_net, &val_eps, &class_w, th);
        if vm.skill_macro_f1 > best_f1 {
            best_f1 = vm.skill_macro_f1;
            best_th = th;
            best_vm = vm;
        }
    }
    best_net.w.skill_thresh = best_th;
    best_net.w.rehash();
    best_net.save(Path::new(&out_weights))?;
    let rhash_a = replay_hash(&best_net);
    let reloaded = RoleNet::load(Path::new(&out_weights))?;
    let rhash_b = replay_hash(&reloaded);
    if rhash_a != rhash_b {
        return Err(anyhow!("STOP_REPLAY_DIVERGENCE: save/reload replay hash mismatch {rhash_a} != {rhash_b}"));
    }

    let report = TrainReport {
        weights_path: out_weights,
        policy_version: best_net.w.version.clone(),
        param_count: best_net.w.param_count,
        train_samples: train_n,
        val_samples: val_n,
        train_episodes: train_eps.len(),
        val_episodes: val_eps.len(),
        epochs_run: epochs,
        best_epoch,
        best_val_loss: best_val,
        final_train_loss,
        skill_thresh: best_th,
        val_metrics: best_vm,
        wall_s: t0.elapsed().as_secs_f32(),
        replay_hash: rhash_a,
    };
    let text = serde_json::to_string_pretty(&report)?;
    if let Some(rp) = out_report {
        if let Some(p) = Path::new(&rp).parent() {
            std::fs::create_dir_all(p)?;
        }
        std::fs::write(&rp, &text)?;
    }
    println!("{text}");
    Ok(())
}

/// Pure-CPU forward-pass benchmark and deterministic replay hash check (`living-mind body-bench`).
pub fn bench_main(args: Vec<String>) -> Result<()> {
    let iters: usize = args.iter().position(|a| a == "--iters").and_then(|i| args.get(i + 1)).and_then(|s| s.parse().ok()).unwrap_or(50_000);
    let weights_path = args.iter().position(|a| a == "--weights").and_then(|i| args.get(i + 1));
    let net = match weights_path {
        Some(p) => RoleNet::load(Path::new(p))?,
        None => RoleNet::new(RoleNetWeights::seeded_init("person", 12345))?,
    };
    let h1 = replay_hash(&net);
    let h2 = replay_hash(&net);
    if h1 != h2 {
        return Err(anyhow!("STOP_REPLAY_DIVERGENCE: {h1} != {h2}"));
    }
    let mut flat = [0.0f32; IN_DIM];
    for i in 0..IN_DIM {
        flat[i] = (i as f32 * 0.1).sin();
    }
    let t0 = Instant::now();
    let mut acc = 0.0f32;
    for _ in 0..iters {
        let (out, next_s) = net.forward(&flat);
        flat[encode::LEN..encode::LEN + STATE].copy_from_slice(&next_s);
        acc += out[0];
    }
    let dt = t0.elapsed().as_secs_f64();
    let dec_per_s = iters as f64 / dt;
    let us_per_dec = dt * 1e6 / iters as f64;
    let out = serde_json::json!({
        "version": net.w.version,
        "param_count": net.w.param_count,
        "iters": iters,
        "wall_s": dt,
        "decisions_per_s_1core": dec_per_s,
        "us_per_decision": us_per_dec,
        "replay_hash": h1,
        "checksum": acc,
    });
    println!("{}", serde_json::to_string_pretty(&out)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rolenet_param_count_is_in_20k_to_30k_and_deterministic() {
        let w = RoleNetWeights::seeded_init("person", 7);
        assert_eq!(w.param_count, 23_341);
        assert!((20_000..=30_000).contains(&w.param_count));
        let net = RoleNet::new(w).unwrap();
        assert_eq!(replay_hash(&net), replay_hash(&net));
    }

    #[test]
    fn rolenet_updates_recurrent_state_and_emits_bounded_intent() {
        let net = RoleNet::new(RoleNetWeights::seeded_init("person", 9)).unwrap();
        let o = Observation {
            now_ms: 10_000,
            me: 1,
            body: Some(encode::BodyRow { id: 1, x: 0.0, y: 0.0, t_ms: 10_000, ..Default::default() }),
            others: vec![encode::BodyRow { id: 2, x: 3.0, y: 0.0, t_ms: 10_000, ..Default::default() }],
            skills: vec![encode::SkillRow { skill: "strike".into(), code: 1, reach: 1.6, ready_ms: 0 }],
            ..Default::default()
        };
        let slot = SlotView { revision: 1, node: 1, goal: "engage".into(), target: 2, skills: vec!["strike".into(), "dodge".into(), "block".into()] };
        let enc = encode::encode(&o, None, &slot);
        let mut mem = Memory::new(1, 0);
        let intent = net.decide(&o, &enc, &mut mem, None, &slot);
        assert!(mem.state.iter().any(|&v| v != 0.0));
        assert!(mem.state.iter().all(|v| v.is_finite() && v.abs() <= 1.0));
        assert!(intent.moving.is_some());
    }
}
