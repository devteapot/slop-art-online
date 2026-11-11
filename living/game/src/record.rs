//! A record of what this client showed and what its player pressed, for the play session
//! report (`living/tools/play_report.py`, docs/PLAY_REPORT.md). Off unless
//! `LIVING_GAME_RECORD=<dir>` is set; the play launcher sets it for the owner's sessions.
//!
//! It writes, into `<dir>`:
//! - `stills/<unix ms>.jpg`: the frame as drawn, HUD included, every
//!   `LIVING_GAME_RECORD_EVERY` seconds (default 3) and at each line, reducer call, bubble and
//!   act note, at most one a second. Captured with Bevy's screenshot, which reads back
//!   asynchronously; the image is moved (not copied) to one worker thread that scales it to
//!   `LIVING_GAME_RECORD_WIDTH` pixels (default 960) and writes a JPEG. A full queue drops the
//!   shot rather than wait.
//! - `state.jsonl`: four times a second, where I am, the camera, the people the HUD knows
//!   (label, distance, hovered, targeted, talking), the bubbles and chat lines on screen, the
//!   target, the text box, hp, the frame time and the recorder's own main-thread time.
//! - `events.jsonl`: presses as the game reads them (a tap or a held press, keys outside the
//!   text box), each line I send, and every reducer call with the authority's answer (net.rs
//!   `on_reply`), with its arguments.
//! - `captures.csv`: per still, when it was asked for, when the image arrived and how long the
//!   worker took (`request_unix_us,arrived_unix_us,encode_ms,bytes`), for its cost.
//!
//! Times are unix milliseconds, the authority's base (`experience.at_ms`). The module reads
//! the client's own state only; it changes nothing the player sees or sends.

use bevy::prelude::*;
use bevy::render::view::screenshot::{Screenshot, ScreenshotCaptured};
use serde_json::{json, Value};
use std::io::Write;
use std::path::PathBuf;
use std::sync::mpsc::{sync_channel, SyncSender, TrySendError};
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::ui::model::{HudModel, LogKind};

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

/// Stills dropped because the writer was behind.
static DROPPED: AtomicU32 = AtomicU32::new(0);

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
        let (tx, rx) = sync_channel::<(u64, u64, Image)>(2);
        let stills = dir.join("stills");
        let mut csv = open("captures.csv");
        std::thread::Builder::new()
            .name("record-stills".into())
            .spawn(move || {
                for (want_us, got_us, img) in rx {
                    let t0 = std::time::Instant::now();
                    let Ok(d) = img.try_into_dynamic() else { continue };
                    let h = (d.height() as u64 * width as u64 / d.width().max(1) as u64).max(1) as u32;
                    let small = if d.width() > width { d.resize_exact(width, h, image::imageops::FilterType::Triangle) } else { d };
                    let path = stills.join(format!("{}.jpg", want_us / 1000));
                    let mut bytes = Vec::new();
                    let enc = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut bytes, 72);
                    if small.to_rgb8().write_with_encoder(enc).is_ok() && std::fs::write(&path, &bytes).is_ok() {
                        if let Some(f) = csv.as_mut() {
                            let _ = writeln!(f, "{want_us},{got_us},{:.1},{}", t0.elapsed().as_secs_f64() * 1000.0, bytes.len());
                            let _ = f.flush();
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
        info!("record: writing stills, state and events to {} (a still every {every} s, {width} px wide)", dir.display());
        app.insert_resource(Rec {
            tx,
            every,
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
        .add_systems(Last, (sample, shoot).chain());
    }
}

#[derive(Resource)]
struct Rec {
    tx: SyncSender<(u64, u64, Image)>,
    every: f64,
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
        "bubbles": bubbles, "log": log, "target": hud.target.as_ref().map(|t| t.name.clone()),
        "chat_open": controls.chat_open, "chat": chat, "hp": hud.me.as_ref().map(|m| m.hp),
        "energy": hud.me.as_ref().map(|m| m.energy), "frame_ms": (time.delta_secs_f64() * 10000.0).round() / 10.0,
        "dropped_stills": DROPPED.load(Ordering::Relaxed),
        "rec_main_us": MAIN_NS.swap(0, Ordering::Relaxed) / 1000,
    });
    let _ = rec.lines.send((true, line.to_string()));
    spent(t0);
}

/// A still on the clock and when something happened; the image goes to the worker thread.
/// Each still reads the whole frame back (Bevy has no smaller capture): on a loaded laptop the
/// few frames after one were measured slower (docs/PLAY_REPORT.md), hence the spacing.
fn shoot(mut commands: Commands, mut rec: ResMut<Rec>, time: Res<Time<Real>>, target: Option<Res<crate::capture::Target>>, net: NonSend<crate::net::Net>) {
    let now = time.elapsed_secs_f64();
    // Nothing to see before I am in the world.
    if net.my_id.is_none() {
        return;
    }
    let due = now >= rec.next_shot || (rec.want && now - rec.last_shot >= 1.0);
    if !due {
        return;
    }
    let t0 = std::time::Instant::now();
    rec.want = false;
    rec.last_shot = now;
    rec.next_shot = now + rec.every;
    let shot = match target {
        Some(t) => Screenshot::image(t.0.clone()),
        None => Screenshot::primary_window(),
    };
    let tx = rec.tx.clone();
    let want = unix_us();
    commands.spawn(shot).observe(move |mut ev: On<ScreenshotCaptured>| {
        let t0 = std::time::Instant::now();
        let img = std::mem::take(&mut ev.event_mut().image);
        match tx.try_send((want, unix_us(), img)) {
            Ok(()) => {}
            Err(TrySendError::Full(_)) => {
                DROPPED.fetch_add(1, Ordering::Relaxed);
            }
            Err(TrySendError::Disconnected(_)) => {}
        }
        spent(t0);
    });
    spent(t0);
}
