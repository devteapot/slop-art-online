//! A record of what this client showed and what its player pressed, for the play session
//! report (`living/tools/play_report.py`, docs/PLAY_REPORT.md). Off unless
//! `LIVING_GAME_RECORD=<dir>` is set; the play launcher sets it for the owner's sessions.
//!
//! It writes, into `<dir>`:
//! - `stills/<unix ms>.jpg`: the frame as drawn, HUD included, `LIVING_GAME_RECORD_FPS` times
//!   a second (default 10), `LIVING_GAME_RECORD_WIDTH` pixels wide (default 960): the session's
//!   video, which the report encodes. With `LIVING_GAME_RECORD_FPS=0` there are only stills,
//!   every `LIVING_GAME_RECORD_EVERY` seconds (default 3) and at each line, reducer call,
//!   bubble and act note. The GPU draws a small copy of the finished frame and only that is read
//!   back (record_frames.rs); one worker thread writes the JPEGs. Nothing waits: at most one
//!   readback is in flight, a late one and a full queue drop the frame ([`guard`]), and the
//!   state lines count the drops by reason. Past `LIVING_GAME_RECORD_MAX_MB` of frames (default 4096) it keeps one
//!   every 5 s.
//! - `state.jsonl`: four times a second, where I am, the camera, the people the HUD knows
//!   (label, distance, hovered, targeted, talking), the bubbles and chat lines on screen, each
//!   speaking body's mouth (`mouths`, mouth.rs), the
//!   target, the text box, hp, the frame time and the recorder's own main-thread time.
//! - `events.jsonl`: presses as the game reads them (a tap or a held press, keys outside the
//!   text box), each line I send, and every reducer call with the authority's answer (net.rs
//!   `on_reply`), with its arguments.
//! - `captures.csv`: per frame, when it was asked for, when the image arrived and how long the
//!   worker took (`request_unix_us,arrived_unix_us,encode_ms,bytes`), for its cost.
//!
//! Times are unix milliseconds, the authority's base (`experience.at_ms`). The module reads
//! the client's own state only; it changes nothing the player sees or sends.

use bevy::prelude::*;
use bevy::render::gpu_readback::{ReadbackComplete, ReadbackOnce};
use bevy::window::PrimaryWindow;
use serde_json::{json, Value};
use std::io::Write;
use std::path::PathBuf;
use std::sync::mpsc::{sync_channel, SyncSender, TrySendError};
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::ui::model::{HudModel, LogKind};

#[path = "record_frames.rs"]
mod frames;

pub fn dir() -> Option<PathBuf> {
    static DIR: OnceLock<Option<PathBuf>> = OnceLock::new();
    DIR.get_or_init(|| std::env::var("LIVING_GAME_RECORD").ok().filter(|v| !v.is_empty()).map(PathBuf::from)).clone()
}

fn unix_us() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_micros() as u64).unwrap_or(0)
}

/// Events from outside the schedule (reducer callbacks), drained each frame.
static EVENTS: Mutex<Vec<Value>> = Mutex::new(Vec::new());
/// The recorder's own main-thread time (ns) since the last state line: its systems and the
/// still observer, for its cost.
static MAIN_NS: AtomicU64 = AtomicU64::new(0);

fn spent(t0: std::time::Instant) {
    MAIN_NS.fetch_add(t0.elapsed().as_nanos() as u64, Ordering::Relaxed);
}

/// Bytes of frames written so far (for the size cap).
static WRITTEN: AtomicU64 = AtomicU64::new(0);

/// Stills dropped, in all and by reason: a readback still in flight when the next was due
/// (`busy`), one that came back later than [`guard::LATE_MS`] (`late`), the writer's queue full
/// (`queue`). See [`guard`].
static DROPPED: AtomicU32 = AtomicU32::new(0);
static DROPPED_BUSY: AtomicU32 = AtomicU32::new(0);
static DROPPED_LATE: AtomicU32 = AtomicU32::new(0);
static DROPPED_QUEUE: AtomicU32 = AtomicU32::new(0);
/// When the readback in flight was asked for (unix µs; 0: none).
static IN_FLIGHT: AtomicU64 = AtomicU64::new(0);

/// The recorder never makes the game wait (record-guard, after headless runs under load froze
/// the main thread 2–5 s with readbacks and JPEGs piling up):
/// - at most one readback is in flight: a still due while one is outstanding is dropped
///   (`busy`), unless that one is older than `LOST_MS` (then it is given up);
/// - a readback that comes back later than `LATE_MS` after it was asked for is dropped
///   (`late`): the GPU is behind, and encoding it would only add to the load. The owner's
///   play-test 5 session had readbacks at 33 ms (p50), 47 (p90) and 73 (p99), so 100 ms drops
///   under 1% of a healthy session's frames (50 ms would drop 6%);
/// - the writer's queue holds `QUEUE` frames; one more is dropped (`queue`).
/// Dropping is counted, never waited on, so memory stays at one readback and `QUEUE` frames.
pub(crate) mod guard {
    pub const LATE_MS: f64 = 100.0;
    pub const LOST_MS: f64 = 2000.0;
    pub const QUEUE: usize = 2;

    /// May a still be asked for now (unix µs), with a readback in flight since `in_flight`
    /// (0: none)?
    pub fn may_ask(in_flight: u64, now: u64) -> bool {
        in_flight == 0 || (now.saturating_sub(in_flight) as f64) / 1000.0 > LOST_MS
    }

    /// Is a readback asked for at `want` and back at `got` (unix µs) still worth writing?
    pub fn in_time(want: u64, got: u64) -> bool {
        (got.saturating_sub(want) as f64) / 1000.0 <= LATE_MS
    }
}
use guard::QUEUE;

/// A reducer's answer, from `Net::on_reply`. Cheap and silent when not recording.
pub fn reply(what: &str, reducer: &dyn std::fmt::Debug, outcome: Result<(), String>, server_us: i64) {
    if dir().is_none() {
        return;
    }
    let (kind, reason) = match outcome {
        Ok(()) => ("ok", None),
        Err(e) => ("refused", Some(e)),
    };
    let mut e = json!({"t": unix_us() / 1000, "kind": if kind == "ok" { "call" } else { "refused" }, "reducer": what,
        "args": format!("{reducer:?}"), "server_ms": server_us / 1000});
    if let Some(r) = reason {
        e["reason"] = json!(r);
    }
    EVENTS.lock().unwrap().push(e);
}

pub struct RecordPlugin;

impl Plugin for RecordPlugin {
    fn build(&self, app: &mut App) {
        let Some(dir) = dir() else { return };
        let _ = std::fs::create_dir_all(dir.join("stills"));
        let open = |name: &str| std::fs::OpenOptions::new().create(true).append(true).open(dir.join(name)).map(std::io::BufWriter::new).ok();
        let every = std::env::var("LIVING_GAME_RECORD_EVERY").ok().and_then(|v| v.parse::<f64>().ok()).unwrap_or(3.0).max(0.2);
        let width = std::env::var("LIVING_GAME_RECORD_WIDTH").ok().and_then(|v| v.parse::<u32>().ok()).unwrap_or(960).max(160);
        let fps = std::env::var("LIVING_GAME_RECORD_FPS").ok().and_then(|v| v.parse::<f64>().ok()).unwrap_or(10.0).clamp(0.0, 30.0);
        // A long session's frames are capped (about 2.3 GB an hour at 960 px, 10 a second):
        // past `LIVING_GAME_RECORD_MAX_MB` (default 4096) one frame every 5 s is kept.
        let max_bytes = std::env::var("LIVING_GAME_RECORD_MAX_MB").ok().and_then(|v| v.parse::<u64>().ok()).unwrap_or(4096) * 1_000_000;
        let (tx, rx) = sync_channel::<Frame>(QUEUE);
        let stills = dir.join("stills");
        let mut csv = open("captures.csv");
        std::thread::Builder::new()
            .name("record-frames".into())
            .spawn(move || {
                for f in rx {
                    let t0 = std::time::Instant::now();
                    let (w, h) = (f.size.x as usize, f.size.y as usize);
                    // Rows are 256-byte aligned in the readback; take each row's texels.
                    let row = if h > 0 { f.data.len() / h } else { 0 };
                    if row < w * 4 {
                        continue;
                    }
                    let mut rgb = Vec::with_capacity(w * h * 3);
                    for y in 0..h {
                        for px in f.data[y * row..y * row + w * 4].chunks_exact(4) {
                            rgb.extend_from_slice(&px[..3]);
                        }
                    }
                    let Some(img) = image::RgbImage::from_raw(w as u32, h as u32, rgb) else { continue };
                    let path = stills.join(format!("{}.jpg", f.want_us / 1000));
                    let mut bytes = Vec::new();
                    let enc = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut bytes, 72);
                    if img.write_with_encoder(enc).is_ok() && std::fs::write(&path, &bytes).is_ok() {
                        WRITTEN.fetch_add(bytes.len() as u64, Ordering::Relaxed);
                        if let Some(c) = csv.as_mut() {
                            let _ = writeln!(c, "{},{},{:.1},{}", f.want_us, f.got_us, t0.elapsed().as_secs_f64() * 1000.0, bytes.len());
                            let _ = c.flush();
                        }
                    }
                }
            })
            .ok();
        // State and event lines go to their own writer thread, so a slow disk never holds a frame.
        let (lines, lines_rx) = std::sync::mpsc::channel::<(bool, String)>();
        let (mut state_f, mut events_f) = (open("state.jsonl"), open("events.jsonl"));
        std::thread::Builder::new()
            .name("record-lines".into())
            .spawn(move || {
                for (is_state, line) in lines_rx {
                    if !is_state {
                        if let Some(f) = events_f.as_mut() {
                            let _ = writeln!(f, "{line}");
                        }
                        continue;
                    }
                    // A state line comes four times a second: flush both files then.
                    if let Some(f) = state_f.as_mut() {
                        let _ = writeln!(f, "{line}");
                        let _ = f.flush();
                    }
                    if let Some(f) = events_f.as_mut() {
                        let _ = f.flush();
                    }
                }
            })
            .ok();
        let what = if fps > 0.0 { format!("{fps} frames a second") } else { format!("a still every {every} s") };
        info!("record: writing frames, state and events to {} ({what}, {width} px wide)", dir.display());
        app.add_plugins(frames::FramesPlugin);
        app.insert_resource(Rec {
            tx,
            every: if fps > 0.0 { 1.0 / fps } else { every },
            steady: fps > 0.0,
            max_bytes,
            width,
            next_shot: 0.0,
            last_shot: -1.0,
            want: false,
            next_state: 0.0,
            said: 0,
            bubbles: Vec::new(),
            toasts: Vec::new(),
            lines,
        })
        .add_systems(Update, (input, drain).chain())
        .add_systems(Last, (mark_camera, sample, shoot).chain());
    }
}

/// A frame read back: when it was asked for and arrived (unix µs), its size and RGBA texels.
struct Frame {
    want_us: u64,
    got_us: u64,
    size: UVec2,
    data: Vec<u8>,
}

#[derive(Resource)]
struct Rec {
    tx: SyncSender<Frame>,
    /// Seconds between frames (steady capture) or between stills.
    every: f64,
    /// A steady capture: frames on the clock only (lines and acts are in the timeline anyway).
    steady: bool,
    max_bytes: u64,
    width: u32,
    next_shot: f64,
    last_shot: f64,
    /// Something happened worth a still now.
    want: bool,
    next_state: f64,
    said: usize,
    bubbles: Vec<(u64, String)>,
    toasts: Vec<String>,
    lines: std::sync::mpsc::Sender<(bool, String)>,
}

impl Rec {
    fn event(&mut self, e: Value) {
        let _ = self.lines.send((false, e.to_string()));
    }
}

fn label_of(hud: &HudModel, id: Option<u32>) -> String {
    match id {
        Some(id) => hud.actors.iter().find(|a| a.id == id as u64).map(|a| format!("{} #{id}", a.name)).unwrap_or(format!("#{id}")),
        None => "no one".into(),
    }
}

/// Presses as the game reads them, and the lines I send.
#[allow(clippy::too_many_arguments)]
fn input(
    mut rec: ResMut<Rec>,
    mouse: Res<ButtonInput<MouseButton>>,
    keys: Res<ButtonInput<KeyCode>>,
    pointer: Res<crate::pointer::Pointer>,
    combat: Res<crate::combat::Combat>,
    controls: Res<crate::controls::Input>,
    hud: Res<HudModel>,
) {
    let t0 = std::time::Instant::now();
    let t = unix_us() / 1000;
    for b in mouse.get_just_pressed() {
        let how = if *b == MouseButton::Left && pointer.tapped { "tap" } else { "press" };
        let what = format!("{b:?} {how} at {}", label_of(&hud, combat.target));
        rec.event(json!({"t": t, "kind": "input", "what": what, "target": combat.target}));
    }
    let typing = controls.chat_open;
    for k in keys.get_just_pressed() {
        let moving = matches!(k, KeyCode::KeyW | KeyCode::KeyA | KeyCode::KeyS | KeyCode::KeyD | KeyCode::ArrowUp | KeyCode::ArrowDown | KeyCode::ArrowLeft | KeyCode::ArrowRight);
        // Not the words typed into the text box (the line itself is logged when sent).
        if moving || (typing && !matches!(k, KeyCode::Enter | KeyCode::Escape | KeyCode::Tab)) {
            continue;
        }
        rec.event(json!({"t": t, "kind": "input", "what": format!("key {k:?}{}", if typing { " (text box)" } else { "" }), "target": combat.target}));
    }
    if controls.said.len() > rec.said {
        let new: Vec<_> = controls.said[rec.said..].to_vec();
        rec.said = controls.said.len();
        for (at, text) in new {
            rec.event(json!({"t": t, "kind": "say", "what": format!("say “{text}”"), "server_ms": at}));
            rec.want = true;
        }
    }
    spent(t0);
}

/// Reducer answers, and the HUD's new bubbles and act notes, as events (and reasons for a still).
fn drain(mut rec: ResMut<Rec>, hud: Res<HudModel>) {
    let t0 = std::time::Instant::now();
    let got: Vec<Value> = std::mem::take(&mut *EVENTS.lock().unwrap());
    for e in got {
        // A change of walking direction is a call too; it is logged but is no reason for a still.
        if e["reducer"] != "move" {
            rec.want = true;
        }
        rec.event(e);
    }
    let t = unix_us() / 1000;
    let now: Vec<(u64, String)> = hud.bubbles.iter().filter(|b| !b.mine).map(|b| (b.speaker, b.text.clone())).collect();
    for b in &now {
        if !rec.bubbles.contains(b) {
            let name = hud.bubbles.iter().find(|x| x.speaker == b.0 && x.text == b.1).map(|x| x.name.clone()).unwrap_or_default();
            rec.event(json!({"t": t, "kind": "bubble", "what": format!("bubble over {name} #{}: “{}”", b.0, b.1)}));
            rec.want = true;
        }
    }
    rec.bubbles = now;
    // The notes are shown newest first, at most a few: log the ones not shown last frame.
    let shown: Vec<String> = hud.verbs.toasts.iter().map(|(text, _, _)| text.clone()).collect();
    let fresh: Vec<(String, Option<bool>)> = hud.verbs.toasts.iter().filter(|(text, _, _)| !rec.toasts.contains(text)).map(|(text, worked, _)| (text.clone(), *worked)).collect();
    for (text, worked) in fresh {
        rec.event(json!({"t": t, "kind": "note", "what": text, "worked": worked}));
        rec.want = true;
    }
    rec.toasts = shown;
    spent(t0);
}

/// The client's state four times a second.
#[allow(clippy::too_many_arguments)]
fn sample(
    mut rec: ResMut<Rec>,
    time: Res<Time<Real>>,
    net: NonSend<crate::net::Net>,
    scene: NonSend<crate::world::Scene>,
    hud: Res<HudModel>,
    controls: Res<crate::controls::Input>,
    cams: Query<&GlobalTransform, With<Camera3d>>,
    mouths: Option<Res<crate::mouth::Mouths>>,
) {
    let now = time.elapsed_secs_f64();
    if now < rec.next_state {
        return;
    }
    let t0 = std::time::Instant::now();
    rec.next_state = now + 0.25;
    let me = net.my_id;
    let (pos, heading) = me.and_then(|id| scene.shown.get(&id)).map(|(p, h)| (Some([p.x, p.y]), *h)).unwrap_or((None, None));
    let cam = cams.iter().next().map(|g| {
        let t = g.translation();
        let f = g.forward();
        json!([t.x, t.y, t.z, f.x, f.y, f.z])
    });
    let drawn: Vec<Value> = hud
        .actors
        .iter()
        .map(|a| json!({"id": a.id, "label": a.name, "d": (a.distance * 10.0).round() / 10.0, "hov": a.hovered, "tgt": a.targeted, "talk": a.talking}))
        .collect();
    let bubbles: Vec<Value> = hud.bubbles.iter().map(|b| json!({"id": b.speaker, "who": b.name, "text": b.text, "mine": b.mine})).collect();
    let log: Vec<Value> = hud
        .log
        .iter()
        .rev()
        .take(4)
        .map(|l| json!({"who": l.who, "text": l.text, "kind": match l.kind { LogKind::Heard => "heard", LogKind::Mine => "mine", LogKind::ToMe => "to me" }}))
        .collect();
    let chat = if controls.chat_open { Some(format!("typing ({} chars)", controls.chat.chars().count())) } else { None };
    let line = json!({
        "t": unix_us() / 1000, "me": me, "me_pos": pos, "heading": heading, "cam": cam, "drawn": drawn,
        "bubbles": bubbles, "mouths": mouths.as_ref().map(|m| m.by_id.iter().map(|(id, w)| (id.to_string(), json!((w * 100.0).round() / 100.0))).collect::<serde_json::Map<_, _>>()), "log": log, "target": hud.target.as_ref().map(|t| t.name.clone()),
        "chat_open": controls.chat_open, "chat": chat, "hp": hud.me.as_ref().map(|m| m.hp),
        "energy": hud.me.as_ref().map(|m| m.energy), "frame_ms": (time.delta_secs_f64() * 10000.0).round() / 10.0,
        "dropped_stills": DROPPED.load(Ordering::Relaxed),
        "dropped": {"busy": DROPPED_BUSY.load(Ordering::Relaxed), "late": DROPPED_LATE.load(Ordering::Relaxed), "queue": DROPPED_QUEUE.load(Ordering::Relaxed)},
        "rec_main_us": MAIN_NS.swap(0, Ordering::Relaxed) / 1000,
    });
    let _ = rec.lines.send((true, line.to_string()));
    spent(t0);
}

/// The camera the HUD is drawn on is the one recorded.
fn mark_camera(mut commands: Commands, cams: Query<(Entity, Has<IsDefaultUiCamera>), (With<Camera3d>, Without<frames::Recorded>)>, marked: Query<(), With<frames::Recorded>>) {
    if !marked.is_empty() {
        return;
    }
    let mut all: Vec<_> = cams.iter().collect();
    all.sort_by_key(|(_, ui)| !*ui);
    if let Some((e, _)) = all.first() {
        commands.entity(*e).insert(frames::Recorded);
    }
}

/// A frame on the clock (and, with stills only, when something happened): this frame's small
/// copy is drawn and read back; the texels go to the worker thread.
#[allow(clippy::too_many_arguments)]
fn shoot(
    mut commands: Commands,
    mut rec: ResMut<Rec>,
    mut grab: ResMut<frames::Grab>,
    mut images: ResMut<Assets<Image>>,
    time: Res<Time<Real>>,
    target: Option<Res<crate::capture::Target>>,
    window: Query<&Window, With<PrimaryWindow>>,
    net: NonSend<crate::net::Net>,
) {
    grab.now = false;
    let now = time.elapsed_secs_f64();
    // Nothing to see before I am in the world.
    if net.my_id.is_none() {
        return;
    }
    let due = now >= rec.next_shot || (!rec.steady && rec.want && now - rec.last_shot >= 1.0);
    if !due {
        return;
    }
    let t0 = std::time::Instant::now();
    rec.want = false;
    rec.last_shot = now;
    let want = unix_us();
    if !guard::may_ask(IN_FLIGHT.load(Ordering::Relaxed), want) {
        // The last readback hasn't come back: skip this one rather than queue more GPU work.
        DROPPED.fetch_add(1, Ordering::Relaxed);
        DROPPED_BUSY.fetch_add(1, Ordering::Relaxed);
        let every = rec.every;
        rec.next_shot = now + every;
        spent(t0);
        return;
    }
    // Keep the clock steady: the next frame is due one interval after this one was.
    let every = if WRITTEN.load(Ordering::Relaxed) > rec.max_bytes { rec.every.max(5.0) } else { rec.every };
    rec.next_shot = if now - rec.next_shot > every { now + every } else { rec.next_shot + every };
    let view = match (&target, window.single()) {
        (Some(t), _) => images.get(&t.0).map(|i| i.size()),
        (None, Ok(w)) => Some(UVec2::new(w.physical_width(), w.physical_height())),
        _ => None,
    };
    let Some(view) = view.filter(|v| v.x > 0 && v.y > 0) else { return };
    let size = frames::size_for(view, rec.width);
    if grab.image.is_none() || grab.size != size {
        if let Some(old) = grab.image.take() {
            images.remove(&old);
        }
        grab.image = Some(frames::target(&mut images, size));
        grab.size = size;
        // The new target exists on the GPU from the next frame on.
        return;
    }
    grab.now = true;
    let tx = rec.tx.clone();
    let handle = grab.image.clone().unwrap();
    IN_FLIGHT.store(want, Ordering::Relaxed);
    commands.spawn(ReadbackOnce::texture(handle)).observe(move |mut ev: On<ReadbackComplete>| {
        let t0 = std::time::Instant::now();
        // This one is back (a later one may have replaced it after `LOST_MS`).
        let _ = IN_FLIGHT.compare_exchange(want, 0, Ordering::Relaxed, Ordering::Relaxed);
        let got = unix_us();
        if !guard::in_time(want, got) {
            DROPPED.fetch_add(1, Ordering::Relaxed);
            DROPPED_LATE.fetch_add(1, Ordering::Relaxed);
            spent(t0);
            return;
        }
        let data = std::mem::take(&mut ev.event_mut().data);
        match tx.try_send(Frame { want_us: want, got_us: got, size, data }) {
            Ok(()) => {}
            Err(TrySendError::Full(_)) => {
                DROPPED.fetch_add(1, Ordering::Relaxed);
                DROPPED_QUEUE.fetch_add(1, Ordering::Relaxed);
            }
            Err(TrySendError::Disconnected(_)) => {}
        }
        spent(t0);
    });
    spent(t0);
}

#[cfg(test)]
mod tests {
    use super::guard::*;

    #[test]
    fn one_readback_in_flight_and_late_or_lost_ones_let_go() {
        let t = 1_000_000_000u64;
        assert!(may_ask(0, t), "nothing in flight");
        assert!(!may_ask(t, t + 30_000), "one in flight 30 ms: the next still is dropped");
        assert!(!may_ask(t, t + 1_900_000), "still in flight at 1.9 s");
        assert!(may_ask(t, t + 2_100_000), "given up after LOST_MS");
        assert!(in_time(t, t + 33_000) && in_time(t, t + 100_000), "a healthy readback (p50 33 ms, p99 73) is written");
        assert!(!in_time(t, t + 150_000), "150 ms late: dropped");
        assert!(in_time(t, t), "a clock that didn't move is in time");
        assert_eq!(QUEUE, 2);
    }

    #[test]
    fn a_full_writer_queue_drops_instead_of_waiting() {
        let (tx, _rx) = std::sync::mpsc::sync_channel::<u8>(QUEUE);
        assert!(tx.try_send(1).is_ok() && tx.try_send(2).is_ok());
        assert!(matches!(tx.try_send(3), Err(std::sync::mpsc::TrySendError::Full(_))), "a third frame is dropped, not waited for");
    }
}
