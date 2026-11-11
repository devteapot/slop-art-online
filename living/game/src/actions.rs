//! The action log: every reducer call this client sends, with the authority's reply, one JSON
//! line per call, for replaying a session's exact commands (the Spark's combat arenas). Off
//! unless `LIVING_GAME_ACTIONS=<file>` is set; the play launcher sets it to `actions.jsonl` in
//! the session folder (`living/tools/play.py`, docs/PLAY_REPORT.md).
//!
//! Calls are logged where they all go out, `Net::on_reply` and `Net::report` (net.rs), so a new
//! reducer call is logged as soon as it is sent the way the others are. A line:
//!
//! ```json
//! {"seq":7,"t_ms":5321.4,"wall_ms":1762873200123,"reducer":"human_act","what":"wave",
//!  "args":{"node":"{\"do\":\"wave\"}"},"yaw":45.0,"control":"travel",
//!  "reply":"refused","error":"no one to wave to","reply_ms":31.2,"server_ms":1762873200140}
//! ```
//!
//! - `seq` counts calls from 1 in the order they were sent; lines are written as replies arrive,
//!   so sort by `seq` for the order sent;
//! - `t_ms` is when it was sent, ms since the log opened (the client's start), `wall_ms` the
//!   same as unix ms (UTC);
//! - `reducer` is the reducer's name, `what` the feature that sent it (the HUD's label: a
//!   gesture's name, `goto`, `face`), and `args` the reducer's arguments by their binding names,
//!   exactly as sent (a `human_act` node is the JSON string the authority parses);
//! - `yaw` (degrees, 0 = north up, clockwise) and `control` (`cursor` or `travel`) are the
//!   camera and control scheme at the start of that frame;
//! - `reply` is `ok`, `refused` (the reducer returned an error: `error` is its text), `failed`
//!   (the host aborted it: `error`), `not_sent` (the SDK refused to queue it: `error`) or `none`
//!   (no reply before the connection dropped or the client closed: the SDK 2.14.1 drops a
//!   pending call's callback with its connection). `reply_ms` is from the call to its callback,
//!   which runs in the next frame's `frame_tick` (`net::pump`), so it includes up to a frame of
//!   waiting; `server_ms` is the authority's timestamp of the reducer run (unix ms).
//!
//! No keystrokes, tokens or identities: commands only. Spoken lines are in `human_say`'s args.
//!
//! Cost on the frame: building the args and one channel send per call; a writer thread
//! formats, buffers and writes, flushing within half a second and on exit (`AppExit`). A
//! killed client loses at most the last half second and its calls still waiting for a reply.
//! The main thread's time in the log is summed and printed at exit (`actions: N calls, ...`).

use bevy::prelude::*;
use serde_json::Value;
use std::collections::HashMap;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, AtomicU64, AtomicU8, Ordering};
use std::sync::mpsc::{channel, RecvTimeoutError, Sender};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// A call on its way to the authority: what the reply callback needs to close its line.
#[derive(Clone, Copy, Debug)]
pub struct Sent {
    pub seq: u64,
    at: Instant,
}

/// How a call ended.
#[derive(Clone, Debug, PartialEq)]
pub enum Reply {
    Ok,
    Refused(String),
    Failed(String),
    NotSent(String),
    None(&'static str),
}

/// A call as sent, before its reply.
#[derive(Clone, Debug)]
pub struct Call {
    pub seq: u64,
    pub t_ms: f64,
    pub wall_ms: u64,
    pub reducer: &'static str,
    pub what: String,
    pub args: Value,
    pub yaw: f32,
    pub control: &'static str,
}

enum Msg {
    Sent(Call),
    Reply { seq: u64, reply: Reply, reply_ms: f64, server_ms: Option<i64> },
    /// The connection dropped: its pending calls will never be answered.
    Lost,
    Close,
}

struct Log {
    tx: Mutex<Sender<Msg>>,
    t0: Instant,
    wall0_ms: f64,
    seq: AtomicU64,
    writer: Mutex<Option<std::thread::JoinHandle<()>>>,
}

static LOG: OnceLock<Option<Log>> = OnceLock::new();
/// The camera yaw (f32 bits) and control scheme (0 travel, 1 cursor) at the start of the frame.
static YAW: AtomicU32 = AtomicU32::new(0);
static CONTROL: AtomicU8 = AtomicU8::new(0);
/// The main thread's time in the log (ns), its longest single call (ns) and calls logged.
static MAIN_NS: AtomicU64 = AtomicU64::new(0);
static MAX_NS: AtomicU64 = AtomicU64::new(0);
static CALLS: AtomicU64 = AtomicU64::new(0);

fn spent(t0: Instant) {
    let ns = t0.elapsed().as_nanos() as u64;
    MAIN_NS.fetch_add(ns, Ordering::Relaxed);
    MAX_NS.fetch_max(ns, Ordering::Relaxed);
}

fn path() -> Option<PathBuf> {
    std::env::var("LIVING_GAME_ACTIONS").ok().filter(|v| !v.trim().is_empty()).map(PathBuf::from)
}

fn log() -> Option<&'static Log> {
    LOG.get_or_init(|| {
        let path = path()?;
        if let Some(dir) = path.parent().filter(|d| !d.as_os_str().is_empty()) {
            let _ = std::fs::create_dir_all(dir);
        }
        let file = match std::fs::OpenOptions::new().create(true).append(true).open(&path) {
            Ok(f) => f,
            Err(e) => {
                warn!("actions: cannot open {}: {e}; no action log", path.display());
                return None;
            }
        };
        let (tx, rx) = channel::<Msg>();
        let writer = std::thread::Builder::new().name("action-log".into()).spawn(move || write_loop(file, rx)).ok()?;
        info!("actions: logging reducer calls to {}", path.display());
        let wall0_ms = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64() * 1000.0).unwrap_or(0.0);
        Some(Log { tx: Mutex::new(tx), t0: Instant::now(), wall0_ms, seq: AtomicU64::new(0), writer: Mutex::new(Some(writer)) })
    })
    .as_ref()
}

fn send(l: &Log, m: Msg) {
    let _ = l.tx.lock().unwrap().send(m);
}

/// Whether calls are being logged.
pub fn on() -> bool {
    log().is_some()
}

/// A call is about to go out (`Net::on_reply`): its line opens. `args` is only built when logging.
pub fn sent(reducer: &'static str, what: &str, args: impl FnOnce() -> Value) -> Option<Sent> {
    let l = log()?;
    let t = Instant::now();
    let seq = l.seq.fetch_add(1, Ordering::Relaxed) + 1;
    let t_ms = t.duration_since(l.t0).as_secs_f64() * 1000.0;
    let call = Call {
        seq,
        t_ms,
        wall_ms: (l.wall0_ms + t_ms) as u64,
        reducer,
        what: what.to_string(),
        args: args(),
        yaw: f32::from_bits(YAW.load(Ordering::Relaxed)),
        control: if CONTROL.load(Ordering::Relaxed) == 1 { "cursor" } else { "travel" },
    };
    send(l, Msg::Sent(call));
    CALLS.fetch_add(1, Ordering::Relaxed);
    spent(t);
    Some(Sent { seq, at: t })
}

/// The authority answered (the reducer's callback): its line closes.
pub fn replied(s: Sent, reply: Reply, server_us: Option<i64>) {
    let Some(l) = log() else { return };
    let t = Instant::now();
    let reply_ms = t.duration_since(s.at).as_secs_f64() * 1000.0;
    send(l, Msg::Reply { seq: s.seq, reply, reply_ms, server_ms: server_us.map(|us| us / 1000) });
    spent(t);
}

/// The SDK would not queue the call (`Net::report` with an error): no reply will come.
pub fn not_sent(s: Sent, error: String) {
    replied(s, Reply::NotSent(error), None);
}

/// The connection dropped: calls still waiting are closed as `none`.
pub fn lost() {
    if let Some(l) = log() {
        send(l, Msg::Lost);
    }
}

/// Close the log: pending calls as `none`, flush, and wait for the writer.
pub fn close() {
    let Some(l) = log() else { return };
    send(l, Msg::Close);
    if let Some(h) = l.writer.lock().unwrap().take() {
        let _ = h.join();
    }
    let (n, ns, max) = (CALLS.load(Ordering::Relaxed), MAIN_NS.load(Ordering::Relaxed), MAX_NS.load(Ordering::Relaxed));
    info!(
        "actions: {n} calls logged; main-thread time {:.3} ms in all, {:.2} µs a call on average, {:.2} µs at most",
        ns as f64 / 1e6,
        if n > 0 { ns as f64 / 1e3 / n as f64 } else { 0.0 },
        max as f64 / 1e3
    );
}

/// One call's line (no trailing newline), its fields in this order.
pub fn line(c: &Call, reply: &Reply, reply_ms: Option<f64>, server_ms: Option<i64>) -> String {
    #[derive(serde::Serialize)]
    struct Line<'a> {
        seq: u64,
        t_ms: f64,
        wall_ms: u64,
        reducer: &'a str,
        what: &'a str,
        args: &'a Value,
        yaw: f64,
        control: &'a str,
        reply: &'a str,
        error: Option<&'a str>,
        reply_ms: Option<f64>,
        server_ms: Option<i64>,
    }
    let r1 = |v: f64| (v * 10.0).round() / 10.0;
    let (kind, error) = match reply {
        Reply::Ok => ("ok", None),
        Reply::Refused(e) => ("refused", Some(e.as_str())),
        Reply::Failed(e) => ("failed", Some(e.as_str())),
        Reply::NotSent(e) => ("not_sent", Some(e.as_str())),
        Reply::None(why) => ("none", Some(*why)),
    };
    let l = Line {
        seq: c.seq,
        t_ms: r1(c.t_ms),
        wall_ms: c.wall_ms,
        reducer: c.reducer,
        what: &c.what,
        args: &c.args,
        yaw: r1(c.yaw as f64),
        control: c.control,
        reply: kind,
        error,
        reply_ms: reply_ms.map(r1),
        server_ms,
    };
    serde_json::to_string(&l).unwrap_or_default()
}

fn write_loop(file: std::fs::File, rx: std::sync::mpsc::Receiver<Msg>) {
    let mut out = std::io::BufWriter::with_capacity(64 * 1024, file);
    let mut pending: HashMap<u64, Call> = HashMap::new();
    let mut dirty = false;
    let drop_pending = |out: &mut std::io::BufWriter<std::fs::File>, pending: &mut HashMap<u64, Call>, why: &'static str| {
        let mut left: Vec<Call> = pending.drain().map(|(_, c)| c).collect();
        left.sort_by_key(|c| c.seq);
        for c in left {
            let _ = writeln!(out, "{}", line(&c, &Reply::None(why), None, None));
        }
    };
    loop {
        match rx.recv_timeout(Duration::from_millis(500)) {
            Ok(Msg::Sent(c)) => {
                pending.insert(c.seq, c);
            }
            Ok(Msg::Reply { seq, reply, reply_ms, server_ms }) => {
                if let Some(c) = pending.remove(&seq) {
                    let _ = writeln!(out, "{}", line(&c, &reply, Some(reply_ms), server_ms));
                    dirty = true;
                }
            }
            Ok(Msg::Lost) => {
                dirty |= !pending.is_empty();
                drop_pending(&mut out, &mut pending, "the connection dropped before a reply");
            }
            Ok(Msg::Close) | Err(RecvTimeoutError::Disconnected) => {
                drop_pending(&mut out, &mut pending, "no reply before the client closed");
                let _ = out.flush();
                return;
            }
            Err(RecvTimeoutError::Timeout) => {
                if dirty {
                    let _ = out.flush();
                    dirty = false;
                }
            }
        }
    }
}

pub struct ActionsPlugin;

impl Plugin for ActionsPlugin {
    fn build(&self, app: &mut App) {
        if !on() {
            return;
        }
        app.add_systems(Update, context.in_set(crate::phase::Phase::Net)).add_systems(Last, close_on_exit);
    }
}

/// The camera yaw and control scheme, for the lines of calls sent this frame.
fn context(cam: Res<crate::camera::Cam>, input: Res<crate::controls::Input>) {
    YAW.store(cam.shown_yaw.rem_euclid(360.0).to_bits(), Ordering::Relaxed);
    CONTROL.store(u8::from(input.control == crate::controls::Control::Cursor), Ordering::Relaxed);
}

fn close_on_exit(mut exits: MessageReader<AppExit>) {
    if exits.read().next().is_some() {
        close();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn call() -> Call {
        Call {
            seq: 7,
            t_ms: 5321.44,
            wall_ms: 1_762_873_200_123,
            reducer: "human_act",
            what: "wave".into(),
            args: json!({"node": "{\"do\":\"wave\"}"}),
            yaw: 45.04,
            control: "travel",
        }
    }

    #[test]
    fn a_line_has_every_field() {
        let v: Value = serde_json::from_str(&line(&call(), &Reply::Refused("no one to wave to".into()), Some(31.24), Some(1_762_873_200_140))).unwrap();
        let keys: Vec<&str> = v.as_object().unwrap().keys().map(|k| k.as_str()).collect();
        for k in ["seq", "t_ms", "wall_ms", "reducer", "what", "args", "yaw", "control", "reply", "error", "reply_ms", "server_ms"] {
            assert!(keys.contains(&k), "missing {k} in {v}");
        }
        assert_eq!(keys.len(), 12, "{v}");
        let raw = line(&call(), &Reply::Ok, None, None);
        assert!(raw.starts_with("{\"seq\":7,\"t_ms\":5321.4,\"wall_ms\":"), "{raw}");
        assert_eq!(v["seq"], 7);
        assert_eq!(v["t_ms"], 5321.4);
        assert_eq!(v["wall_ms"], 1_762_873_200_123u64);
        assert_eq!(v["reducer"], "human_act");
        assert_eq!(v["what"], "wave");
        assert_eq!(v["args"]["node"], "{\"do\":\"wave\"}");
        assert_eq!(v["yaw"], 45.0);
        assert_eq!(v["control"], "travel");
        assert_eq!(v["reply"], "refused");
        assert_eq!(v["error"], "no one to wave to");
        assert_eq!(v["reply_ms"], 31.2);
        assert_eq!(v["server_ms"], 1_762_873_200_140i64);
    }

    #[test]
    fn ok_and_unanswered_lines() {
        let v: Value = serde_json::from_str(&line(&call(), &Reply::Ok, Some(2.0), Some(1))).unwrap();
        assert_eq!(v["reply"], "ok");
        assert!(v["error"].is_null());
        let v: Value = serde_json::from_str(&line(&call(), &Reply::None("no reply before the client closed"), None, None)).unwrap();
        assert_eq!(v["reply"], "none");
        assert!(v["reply_ms"].is_null() && v["server_ms"].is_null());
        assert!(!line(&call(), &Reply::Ok, None, None).contains('\n'));
    }
}
