//! One player's input latency, stage by stage (docs/LATENCY.md; driven by living/tools/latency.py).
//!
//! A single real player connection (Rust SDK 2.14.1, as the game client) subscribes what the game
//! client subscribes, joins, and then sends:
//! - `human_move` direction changes (a square: east, south, west, north), one every `move_ms`
//!   plus 0–17 ms of jitter so inputs land at every phase of the 60 Hz tick;
//! - then a timed skill (`firebolt` by default) at a ground point, one every `bolt_ms`.
//!
//! Per input it logs, on this host's wall clock (µs):
//! - `in`: just before the call is handed to the SDK;
//! - `res`: when the call's own reply is processed, with the server's `ReducerEvent.timestamp`
//!   (taken at receipt, before the database's queue; docs/GATE_216.md);
//! - `b`: every `seen_bodies` row change (all bodies, for the display-clock emulation), with the
//!   segment's start `t_ms` and, for a reducer event, its server timestamp;
//! - `use`: every state of my `skill_use` rows as it arrives (accepted, released, outcome).
//!
//! `pump = "thread"` processes messages as they arrive (`run_threaded`), so arrival times are
//! the network's. `pump = "frame"` calls `frame_tick` at `frame_hz` on one thread, as the game
//! client's `net::pump` did once per frame, so arrival times include the wait for the next frame.
//! `pump = "flush"` does the same and also calls `frame_tick` right after each input, as the game
//! client's `net::flush` does after its input systems (docs/LATENCY.md, step 1): the call leaves
//! in the frame it was made, and only the reply waits for a frame.
//!
//! Body rows carry `ins` (a body entering view) and `prev` (the segment start the row replaces),
//! so the display clock can be emulated fed only by changed segments (docs/LATENCY.md, step 3).
//!
//! Protocol: one request JSON line on stdin; prints `{"event":"done",…}` at the end.

use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, Event, Identity, Table, TableWithPrimaryKey};
use std::io::{BufRead, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

fn unix_us() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_micros() as i64
}

#[derive(Clone)]
struct Log(mpsc::Sender<String>);

impl Log {
    fn put(&self, v: Value) {
        let _ = self.0.send(v.to_string());
    }
}

/// What the game client subscribes once per connection (gate_load's `BASE`).
const BASE: &[&str] = &[
    "world", "land", "settlement", "seen_bodies", "seen_characters", "seen_fighters", "seen_doing", "my_characters", "my_vitals", "my_experience", "my_places",
    "my_inventory", "my_know_how", "my_combat", "my_readiness", "skill_card", "act_card", "weather", "my_skill_uses",
];

fn status(res: &Result<Result<(), String>, spacetimedb_sdk::__codegen::InternalError>) -> String {
    match res {
        Ok(Ok(())) => "ok".into(),
        Ok(Err(e)) => format!("err:{e}"),
        Err(e) => format!("internal:{e}"),
    }
}

fn wait<T>(what: &str, limit: Duration, mut f: impl FnMut() -> Option<T>) -> T {
    let t = Instant::now();
    loop {
        if let Some(v) = f() {
            return v;
        }
        assert!(t.elapsed() < limit, "timed out waiting for {what}");
        std::thread::sleep(Duration::from_millis(5));
    }
}

fn main() {
    let mut line = String::new();
    std::io::stdin().lock().read_line(&mut line).expect("request");
    let req: Value = serde_json::from_str(&line).expect("request JSON");
    let s = |k: &str| req[k].as_str().unwrap_or_else(|| panic!("missing {k}")).to_string();
    let n = |k: &str, d: u64| req[k].as_u64().unwrap_or(d);
    let (uri, db, token, name, out) = (s("uri"), s("db"), s("token"), s("name"), s("out"));
    let confirmed = req["confirmed"].as_bool().unwrap_or(true);
    let flush = req["pump"].as_str() == Some("flush");
    let frame = flush || req["pump"].as_str() == Some("frame");
    let frame_hz = req["frame_hz"].as_f64().unwrap_or(60.0);
    let (moves, move_ms, bolts, bolt_ms) = (n("moves", 200), n("move_ms", 300), n("bolts", 20), n("bolt_ms", 4300));
    let skill = req["skill"].as_str().unwrap_or("firebolt").to_string();

    // The log writer.
    let (tx, rx) = mpsc::channel::<String>();
    let file = std::fs::File::create(&out).unwrap_or_else(|e| panic!("{out}: {e}"));
    let writer = std::thread::spawn(move || {
        let mut w = std::io::BufWriter::with_capacity(1 << 20, file);
        for l in rx {
            if l.is_empty() {
                break;
            }
            let _ = writeln!(w, "{l}");
        }
        let _ = w.flush();
    });
    let log = Log(tx);

    // Connect.
    let id: Arc<Mutex<Option<Identity>>> = Arc::default();
    let got = id.clone();
    let conn = DbConnection::builder()
        .with_uri(uri)
        .with_database_name(db)
        .with_token(Some(token))
        .with_confirmed_reads(confirmed)
        .on_connect(move |_, identity, _| *got.lock().unwrap() = Some(identity))
        .build()
        .expect("connect");
    let conn = Arc::new(conn);
    let stop = Arc::new(AtomicBool::new(false));
    let pumper = if frame {
        let (c, stop) = (conn.clone(), stop.clone());
        let period = Duration::from_secs_f64(1.0 / frame_hz);
        Some(std::thread::spawn(move || {
            let mut next = Instant::now();
            while !stop.load(Ordering::Relaxed) {
                next += period;
                if let Err(e) = c.frame_tick() {
                    eprintln!("frame_tick: {e}");
                    break;
                }
                let now = Instant::now();
                if next > now {
                    std::thread::sleep(next - now);
                } else {
                    next = now;
                }
            }
        }))
    } else {
        conn.run_threaded();
        None
    };
    wait("identity", Duration::from_secs(60), || *id.lock().unwrap());

    // Hooks.
    let me: Arc<Mutex<Option<u32>>> = Arc::default();
    {
        let me2 = me.clone();
        conn.db.my_characters().on_insert(move |_, c| {
            if c.alive && !c.ai {
                *me2.lock().unwrap() = Some(c.id);
            }
        });
        let me2 = me.clone();
        conn.db.my_characters().on_update(move |_, _, c| {
            if c.alive && !c.ai {
                *me2.lock().unwrap() = Some(c.id);
            }
        });
        let body = |me: Arc<Mutex<Option<u32>>>, lg: Log| {
            move |ctx: &EventContext, b: &Moving, prev: Option<u64>| {
                let ts = unix_us();
                let srv = match &ctx.event {
                    Event::Reducer(ev) => Some(ev.timestamp.to_micros_since_unix_epoch()),
                    Event::SubscribeApplied | Event::UnsubscribeApplied => return,
                    _ => None,
                };
                let mine = *me.lock().unwrap() == Some(b.id);
                lg.put(json!({"k": "b", "ts": ts, "id": b.id, "me": mine, "t": b.t_ms, "next": b.next_ms, "srv": srv, "vx": b.vx, "vy": b.vy, "ins": prev.is_none(), "prev": prev}));
            }
        };
        let f = body(me.clone(), log.clone());
        conn.db.seen_bodies().on_insert(move |ctx, b| f(ctx, b, None));
        let f = body(me.clone(), log.clone());
        conn.db.seen_bodies().on_update(move |ctx, old, b| f(ctx, b, Some(old.t_ms)));
        let lg = log.clone();
        conn.db.my_skill_uses().on_insert(move |ctx, u| {
            let ts = unix_us();
            let srv = match &ctx.event {
                Event::Reducer(ev) => Some(ev.timestamp.to_micros_since_unix_epoch()),
                Event::SubscribeApplied | Event::UnsubscribeApplied => return,
                _ => None,
            };
            lg.put(json!({"k": "use", "ts": ts, "use": u.id, "skill": u.skill, "src": u.source, "at": u.at_ms, "acc": u.accepted_ms, "rel": u.released_ms, "out": u.outcome, "out_ms": u.outcome_ms, "srv": srv}));
        });
    }

    // Subscribe what the game client subscribes.
    let applied = Arc::new(AtomicBool::new(false));
    let errors: Arc<Mutex<Vec<String>>> = Arc::default();
    {
        let (a, e) = (applied.clone(), errors.clone());
        conn.subscription_builder()
            .on_applied(move |_| a.store(true, Ordering::Relaxed))
            .on_error(move |_, err| e.lock().unwrap().push(err.to_string()))
            .subscribe(BASE.iter().map(|t| format!("SELECT * FROM {t}")).collect::<Vec<_>>());
    }
    wait("subscription", Duration::from_secs(120), || {
        let e = errors.lock().unwrap();
        assert!(e.is_empty(), "subscription: {}", e.join("; "));
        applied.load(Ordering::Relaxed).then_some(())
    });
    if me.lock().unwrap().is_none() {
        let _ = conn.reducers.join(name.clone());
    }
    let my_id = wait("my character", Duration::from_secs(60), || *me.lock().unwrap());
    log.put(json!({"k": "joined", "id": my_id, "ts": unix_us(), "confirmed": confirmed, "pump": if flush { "flush" } else if frame { "frame" } else { "thread" }, "frame_hz": frame_hz}));
    std::thread::sleep(Duration::from_secs(2));

    let mut seq = 0u64;
    let mut jitter = 0x9e3779b97f4a7c15u64 ^ unix_us() as u64;
    let mut rnd = move || {
        jitter ^= jitter << 13;
        jitter ^= jitter >> 7;
        jitter ^= jitter << 17;
        jitter % 17_000
    };
    let send_move = |seq: u64, dx: f32, dy: f32| {
        let lg = log.clone();
        let t0 = unix_us();
        let r = conn.reducers.human_move_then(dx, dy, false, move |ctx, res| {
            lg.put(json!({"k": "res", "n": seq, "r": "move", "ts": unix_us(), "srv": ctx.event.timestamp.to_micros_since_unix_epoch(), "st": status(&res)}));
        });
        if flush {
            let _ = conn.frame_tick();
        }
        log.put(json!({"k": "in", "n": seq, "r": "move", "ts": t0, "dx": dx, "dy": dy, "sent": r.is_ok()}));
    };
    const SQUARE: [(f32, f32); 4] = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)];
    for i in 0..moves {
        seq += 1;
        let (dx, dy) = SQUARE[(i % 4) as usize];
        send_move(seq, dx, dy);
        std::thread::sleep(Duration::from_millis(move_ms) + Duration::from_micros(rnd()));
    }
    seq += 1;
    send_move(seq, 0.0, 0.0);
    std::thread::sleep(Duration::from_secs(1));

    for i in 0..bolts {
        seq += 1;
        let at = conn.db.seen_bodies().id().find(&my_id).map(|b| (b.x, b.y)).unwrap_or((0.0, 0.0));
        let (dx, dy) = SQUARE[(i % 4) as usize];
        let (lg, k) = (log.clone(), seq);
        let t0 = unix_us();
        let r = conn.reducers.use_skill_then(skill.clone(), 0, at.0 + 6.0 * dx, at.1 + 6.0 * dy, move |ctx, res| {
            lg.put(json!({"k": "res", "n": k, "r": "skill", "ts": unix_us(), "srv": ctx.event.timestamp.to_micros_since_unix_epoch(), "st": status(&res)}));
        });
        if flush {
            let _ = conn.frame_tick();
        }
        log.put(json!({"k": "in", "n": seq, "r": "skill", "skill": skill, "ts": t0, "sent": r.is_ok()}));
        std::thread::sleep(Duration::from_millis(bolt_ms) + Duration::from_micros(rnd()));
    }
    std::thread::sleep(Duration::from_secs(2));
    stop.store(true, Ordering::Relaxed);
    if let Some(p) = pumper {
        let _ = p.join();
    }
    let _ = conn.disconnect();
    log.0.send(String::new()).ok();
    drop(log);
    let _ = writer.join();
    println!("{}", json!({"event": "done", "id": my_id, "inputs": seq}));
}
