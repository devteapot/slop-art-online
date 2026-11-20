//! Dispatch profile (diagnostic, `LIVING_INPUT_LATENCY=1`; docs/INPUT_LATENCY.md, "Mind
//! dispatch profile"). Off, every entry point is one cached flag test.
//!
//! - **Series**: named timings (µs) or counts (names ending `.n`), kept per thread and summed
//!   every 5 s into one `input_latency_prof {json}` line in `mind.log` (n, sum, p50/p90/p95/p99,
//!   max; exact percentiles over the window's samples, at most 20,000 a series a thread).
//! - **Locks**: [`Mx`] is `std::sync::Mutex` with a name. It records the wait for and the hold
//!   of each lock; a hold of 2 ms or more is also recorded under the caller's line.
//! - **Stages**: [`Stages`] stamps one deliberation's steps (task-local, [`mark`]); the caller
//!   journals them.
//! - **Runtime**: worker busy share and queue depth each second, and a 10 ms heartbeat's
//!   lateness on the workers ([`start`]).

use std::cell::RefCell;
use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

pub fn on() -> bool {
    static ON: OnceLock<bool> = OnceLock::new();
    *ON.get_or_init(|| std::env::var("LIVING_INPUT_LATENCY").is_ok_and(|v| v == "1"))
}

const CAP: usize = 20_000;

#[derive(Default)]
struct Series {
    samples: Vec<u32>,
    n: u64,
    sum: u64,
    max: u32,
}

type Shard = Arc<Mutex<HashMap<String, Series>>>;

fn shards() -> &'static Mutex<Vec<Shard>> {
    static S: OnceLock<Mutex<Vec<Shard>>> = OnceLock::new();
    S.get_or_init(Default::default)
}

thread_local! {
    static SHARD: Shard = {
        let s: Shard = Default::default();
        shards().lock().unwrap().push(s.clone());
        s
    };
}

/// Record `value` (µs, or a count for a `.n` name) under `name`.
pub fn value(name: &str, value: u64) {
    if !on() {
        return;
    }
    let v = value.min(u32::MAX as u64) as u32;
    SHARD.with(|s| {
        let mut s = s.lock().unwrap();
        let e = match s.get_mut(name) {
            Some(e) => e,
            None => s.entry(name.to_string()).or_default(),
        };
        e.n += 1;
        e.sum += v as u64;
        e.max = e.max.max(v);
        if e.samples.len() < CAP {
            e.samples.push(v);
        } else {
            // A cheap reservoir: replace a pseudo-random sample.
            let i = (e.n.wrapping_mul(0x9E37_79B9_7F4A_7C15) >> 33) as usize % CAP;
            e.samples[i] = v;
        }
    });
}

pub fn time(name: &str, d: Duration) {
    value(name, d.as_micros() as u64);
}

/// Times its scope under `name`.
pub struct Span(&'static str, Instant);

impl Drop for Span {
    fn drop(&mut self) {
        time(self.0, self.1.elapsed());
    }
}

pub fn span(name: &'static str) -> Option<Span> {
    on().then(|| Span(name, Instant::now()))
}

fn pct(sorted: &[u32], p: f64) -> u32 {
    if sorted.is_empty() {
        return 0;
    }
    sorted[((sorted.len() as f64 * p) as usize).min(sorted.len() - 1)]
}

fn report() {
    let mut all: HashMap<String, Series> = HashMap::new();
    for shard in shards().lock().unwrap().iter() {
        for (k, mut v) in std::mem::take(&mut *shard.lock().unwrap()) {
            let e = all.entry(k).or_default();
            e.n += v.n;
            e.sum += v.sum;
            e.max = e.max.max(v.max);
            e.samples.append(&mut v.samples);
        }
    }
    let mut out = serde_json::Map::new();
    let mut names: Vec<_> = all.into_iter().collect();
    names.sort_by(|a, b| a.0.cmp(&b.0));
    for (k, mut v) in names {
        v.samples.sort_unstable();
        out.insert(k, serde_json::json!([v.n, v.sum, pct(&v.samples, 0.5), pct(&v.samples, 0.9), pct(&v.samples, 0.95), pct(&v.samples, 0.99), v.max]));
    }
    log::info!("input_latency_prof {} {}", crate::llm::now_ms(), serde_json::Value::Object(out));
}

/// Start the reporter (a thread), the runtime sampler and the worker heartbeat.
pub fn start(rt: tokio::runtime::Handle) {
    if !on() {
        return;
    }
    std::thread::Builder::new().name("prof-report".into()).spawn(|| loop {
        std::thread::sleep(Duration::from_secs(5));
        report();
    }).unwrap();
    let metrics = rt.metrics();
    std::thread::Builder::new().name("prof-runtime".into()).spawn(move || {
        let workers = metrics.num_workers();
        let mut last: Vec<Duration> = (0..workers).map(|w| metrics.worker_total_busy_duration(w)).collect();
        let mut at = Instant::now();
        loop {
            std::thread::sleep(Duration::from_secs(1));
            let elapsed = at.elapsed();
            at = Instant::now();
            let mut total = 0.0;
            for (w, last) in last.iter_mut().enumerate() {
                let busy = metrics.worker_total_busy_duration(w);
                let share = (busy - *last).as_secs_f64() / elapsed.as_secs_f64();
                *last = busy;
                total += share;
                value("rt.worker_busy_pct.n", (share * 100.0).round() as u64);
            }
            value("rt.busy_workers_x100.n", (total * 100.0).round() as u64);
            value("rt.global_queue.n", metrics.global_queue_depth() as u64);
            value("rt.alive_tasks.n", metrics.num_alive_tasks() as u64);
        }
    }).unwrap();
    rt.spawn(async {
        let mut next = Instant::now();
        loop {
            next += Duration::from_millis(10);
            tokio::time::sleep_until(next.into()).await;
            time("rt.heartbeat_late", Instant::now().saturating_duration_since(next));
            next = Instant::now();
        }
    });
}

/// `std::sync::Mutex` with a name for the profile (see the module).
pub struct Mx<T> {
    name: &'static str,
    names: OnceLock<(&'static str, &'static str)>,
    inner: Mutex<T>,
}

pub struct MxGuard<'a, T> {
    guard: std::sync::MutexGuard<'a, T>,
    held: Option<(Instant, &'static str, &'static str, &'static std::panic::Location<'static>)>,
}

impl<T> Mx<T> {
    pub const fn new(name: &'static str, value: T) -> Self {
        Mx { name, names: OnceLock::new(), inner: Mutex::new(value) }
    }

    /// Like `Mutex::lock` (a poisoned lock panics here, as `.lock().unwrap()` did).
    #[track_caller]
    pub fn lock(&self) -> Result<MxGuard<'_, T>, std::convert::Infallible> {
        if !on() {
            return Ok(MxGuard { guard: self.inner.lock().unwrap(), held: None });
        }
        let at = std::panic::Location::caller();
        let (wait, hold) = *self.names.get_or_init(|| (intern(&format!("lock.{}.wait", self.name)), intern(&format!("lock.{}.hold", self.name))));
        let t = Instant::now();
        let guard = self.inner.lock().unwrap();
        let got = Instant::now();
        value(wait, (got - t).as_micros() as u64);
        Ok(MxGuard { guard, held: Some((got, self.name, hold, at)) })
    }
}

/// Names made once (lock and site names), kept for the life of the process.
fn intern(s: &str) -> &'static str {
    static NAMES: OnceLock<Mutex<HashMap<String, &'static str>>> = OnceLock::new();
    thread_local! {
        static LOCAL: RefCell<HashMap<String, &'static str>> = RefCell::new(HashMap::new());
    }
    if let Some(n) = LOCAL.with(|l| l.borrow().get(s).copied()) {
        return n;
    }
    let n = *NAMES.get_or_init(Default::default).lock().unwrap().entry(s.to_string()).or_insert_with(|| Box::leak(s.to_string().into_boxed_str()));
    LOCAL.with(|l| l.borrow_mut().insert(s.to_string(), n));
    n
}

impl<T> Drop for MxGuard<'_, T> {
    fn drop(&mut self) {
        if let Some((got, name, hold, at)) = self.held {
            let held = got.elapsed();
            value(hold, held.as_micros() as u64);
            if held >= Duration::from_millis(2) {
                let file = at.file().rsplit('/').next().unwrap_or("");
                value(intern(&format!("lock.{name}.hold_ge2ms@{file}:{}", at.line())), held.as_micros() as u64);
            }
        }
    }
}

impl<T: std::fmt::Debug> std::fmt::Debug for MxGuard<'_, T> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        (*self.guard).fmt(f)
    }
}

impl<T> std::ops::Deref for MxGuard<'_, T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.guard
    }
}

impl<T> std::ops::DerefMut for MxGuard<'_, T> {
    fn deref_mut(&mut self) -> &mut T {
        &mut self.guard
    }
}

/// One deliberation's (or fast ask's) steps, as milliseconds since the epoch.
#[derive(Default)]
pub struct Stages {
    pub marks: Vec<(&'static str, u64)>,
}

tokio::task_local! {
    pub static STAGES: RefCell<Stages>;
}

/// Stamp step `name` of the deliberation this task runs (the first stamp of a name stays).
pub fn mark(name: &'static str) {
    if !on() {
        return;
    }
    let _ = STAGES.try_with(|s| {
        let mut s = s.borrow_mut();
        if !s.marks.iter().any(|(n, _)| *n == name) {
            s.marks.push((name, crate::llm::now_ms()));
        }
    });
}

/// Stamp `name` at `at_ms` (for a time taken elsewhere, as a queue entry or grant).
pub fn mark_at(name: &'static str, at_ms: u64) {
    if !on() {
        return;
    }
    let _ = STAGES.try_with(|s| {
        let mut s = s.borrow_mut();
        if !s.marks.iter().any(|(n, _)| *n == name) {
            s.marks.push((name, at_ms));
        }
    });
}
