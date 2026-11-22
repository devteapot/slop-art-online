//! RELAY_PROTOTYPE (branch `relay-proto` only, never for main; docs/RELAY_PROTOTYPE.md): a minimal
//! delivery relay, built to measure what moving per-viewer delivery off the authority's thread
//! costs and adds. Three modes, each one request JSON line on stdin, `stop` on stdin to end:
//!
//! - `relay`: one owner connection to the authority subscribing the truth tables the frames read
//!   (`body`, `fighter`, `doing`), each viewer's authority-written set (`perceived`), `player`, the
//!   fight events (`relay_event`, written with the `relay_on` law) and `clock`. Every server message
//!   is one transaction: its callbacks are buffered and applied together after
//!   `advance_one_message` returns, sets first, then state, so a fact of transaction T is sent only
//!   under T's sets. Viewers connect by WebSocket and say who they are (a prototype shortcut: no
//!   token check); each gets its set's full state on connecting, then every change of a creature in
//!   its set, "gone" when one leaves it, the fight events whose actor or target is in it, and 1 Hz
//!   hearing buckets (8 bearings × 3 bands of creatures within 9 m outside its set).
//!   `broken: true` applies a transaction's state before its set changes (the privacy probe's
//!   known answer: it must be caught).
//! - `clients`: one WebSocket per viewer identity; per frame, the hop from the relay's receipt
//!   and the age from the authority's tick; every item logged for the privacy check.
//! - `checker`: an independent owner connection with the relay's subscriptions, logging each
//!   viewer's set changes and the players' characters by transaction.
//!
//! Transactions are named (tick, index): `clock.tick` of the latest tick transaction and the
//! number of messages since it. Two connections with the same subscriptions get the same
//! transactions in the same order, so the relay's and the checker's names agree.

use futures_util::{SinkExt, StreamExt};
use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, EventTable, Identity, Table, TableWithPrimaryKey};
use std::collections::{HashMap, HashSet};
use std::io::{BufRead, BufWriter, Write};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const QUERIES: [&str; 7] = [
    "SELECT * FROM body",
    "SELECT * FROM fighter",
    "SELECT * FROM doing",
    "SELECT * FROM perceived",
    "SELECT * FROM player",
    "SELECT * FROM relay_event",
    "SELECT * FROM clock",
];
const HEAR_M: f32 = 9.0;

fn now_us() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_micros() as u64
}

enum Change {
    Body(Body),
    BodyGone(u32),
    Fighter(Fighter),
    FighterGone(u32),
    Doing(Doing),
    DoingGone(u32),
    SetAdd(Identity, u32),
    SetDel(Identity, u32),
    Player(Identity, u32),
    Event(RelayEvent),
    Tick(u64, u64),
}

type Buf = Arc<Mutex<Vec<Change>>>;

fn connect(uri: &str, db: &str, token: &str, buf: Buf) -> DbConnection {
    let conn = DbConnection::builder()
        .with_uri(uri.to_string())
        .with_database_name(db.to_string())
        .with_token(Some(token.to_string()))
        .build()
        .expect("connect");
    macro_rules! keyed {
        ($t:ident, $add:ident, $gone:ident) => {{
            let b = buf.clone();
            conn.db.$t().on_insert(move |_, r| b.lock().unwrap().push(Change::$add(r.clone())));
            let b = buf.clone();
            conn.db.$t().on_update(move |_, _, r| b.lock().unwrap().push(Change::$add(r.clone())));
            let b = buf.clone();
            conn.db.$t().on_delete(move |_, r| b.lock().unwrap().push(Change::$gone(r.id)));
        }};
    }
    keyed!(body, Body, BodyGone);
    keyed!(fighter, Fighter, FighterGone);
    keyed!(doing, Doing, DoingGone);
    let b = buf.clone();
    conn.db.perceived().on_insert(move |_, r| b.lock().unwrap().push(Change::SetAdd(r.viewer, r.body)));
    let b = buf.clone();
    conn.db.perceived().on_delete(move |_, r| b.lock().unwrap().push(Change::SetDel(r.viewer, r.body)));
    let b = buf.clone();
    conn.db.player().on_insert(move |_, r| b.lock().unwrap().push(Change::Player(r.identity, r.character)));
    let b = buf.clone();
    conn.db.player().on_update(move |_, _, r| b.lock().unwrap().push(Change::Player(r.identity, r.character)));
    let b = buf.clone();
    EventTable::on_insert(&conn.db.relay_event(), move |_, r| b.lock().unwrap().push(Change::Event(r.clone())));
    let b = buf.clone();
    conn.db.clock().on_insert(move |_, r| b.lock().unwrap().push(Change::Tick(r.tick, r.last_ms)));
    let b = buf;
    conn.db.clock().on_update(move |_, _, r| b.lock().unwrap().push(Change::Tick(r.tick, r.last_ms)));
    conn.subscription_builder().on_error(|_, e| panic!("subscribe: {e}")).subscribe(QUERIES.map(String::from).to_vec());
    conn
}

/// `stop` on stdin ends the mode.
fn stop_flag() -> Arc<AtomicBool> {
    let stop = Arc::new(AtomicBool::new(false));
    let s = stop.clone();
    std::thread::spawn(move || {
        for line in std::io::stdin().lock().lines() {
            if line.map(|l| l.trim() == "stop").unwrap_or(true) {
                break;
            }
        }
        s.store(true, Ordering::SeqCst);
    });
    stop
}

fn put_u32(v: &mut Vec<u8>, x: u32) {
    v.extend_from_slice(&x.to_le_bytes());
}
fn put_u64(v: &mut Vec<u8>, x: u64) {
    v.extend_from_slice(&x.to_le_bytes());
}
fn put_f32(v: &mut Vec<u8>, x: f32) {
    v.extend_from_slice(&x.to_le_bytes());
}

fn enc_body(v: &mut Vec<u8>, b: &Body) {
    v.push(1);
    put_u32(v, b.id);
    put_u64(v, b.t_ms);
    put_f32(v, b.x);
    put_f32(v, b.y);
    put_f32(v, b.vx);
    put_f32(v, b.vy);
    put_f32(v, b.heading);
}
fn enc_fighter(v: &mut Vec<u8>, f: &Fighter) {
    v.push(2);
    put_u32(v, f.id);
    v.push(f.band);
    v.push(f.act);
    put_u64(v, f.until_ms);
    put_u32(v, f.target);
}
fn enc_doing(v: &mut Vec<u8>, d: &Doing) {
    v.push(3);
    put_u32(v, d.id);
    v.push(d.code);
    put_u32(v, d.target);
    put_u64(v, d.until_ms);
}
fn enc_gone(v: &mut Vec<u8>, id: u32) {
    v.push(4);
    put_u32(v, id);
}
fn enc_event(v: &mut Vec<u8>, e: &RelayEvent) {
    v.push(5);
    v.push(e.kind);
    put_u32(v, e.actor);
    put_u32(v, e.target);
    put_f32(v, e.amount);
    put_f32(v, e.x);
    put_f32(v, e.y);
}

enum Reg {
    Add(Identity, tokio::sync::mpsc::UnboundedSender<Vec<u8>>),
    Drop(Identity),
}

#[derive(Default)]
struct State {
    bodies: HashMap<u32, Body>,
    fighters: HashMap<u32, Fighter>,
    doings: HashMap<u32, Doing>,
    sets: HashMap<Identity, HashSet<u32>>,
    watchers: HashMap<u32, HashSet<Identity>>,
    players: HashMap<Identity, u32>,
    chars: HashMap<u32, Identity>,
    tick: u64,
    idx: u32,
    tick_ms: u64,
    clients: HashMap<Identity, tokio::sync::mpsc::UnboundedSender<Vec<u8>>>,
    heard: HashMap<Identity, [u16; 24]>,
    last_hear_ms: u64,
    broken: bool,
    // counters
    txs: u64,
    changes: u64,
    items: u64,
    frames: u64,
    bytes: u64,
    unsent_items: u64,
    process_us: u64,
}

impl State {
    fn set_change(&mut self, add: bool, v: Identity, b: u32, out: &mut HashMap<Identity, Vec<u8>>) {
        if add {
            if self.sets.entry(v).or_default().insert(b) {
                self.watchers.entry(b).or_default().insert(v);
                // It came into the set: its whole state, as it is now.
                let o = out.entry(v).or_default();
                if let Some(x) = self.bodies.get(&b) {
                    enc_body(o, x);
                }
                if let Some(x) = self.fighters.get(&b) {
                    enc_fighter(o, x);
                }
                if let Some(x) = self.doings.get(&b) {
                    enc_doing(o, x);
                }
            }
        } else if self.sets.get_mut(&v).is_some_and(|s| s.remove(&b)) {
            if let Some(w) = self.watchers.get_mut(&b) {
                w.remove(&v);
            }
            enc_gone(out.entry(v).or_default(), b);
        }
    }

    fn fan(&self, id: u32, out: &mut HashMap<Identity, Vec<u8>>, enc: impl Fn(&mut Vec<u8>)) {
        if let Some(w) = self.watchers.get(&id) {
            for v in w {
                enc(out.entry(*v).or_default());
            }
        }
    }

    fn process(&mut self, batch: Vec<Change>, recv_us: u64) {
        let t0 = Instant::now();
        self.txs += 1;
        self.changes += batch.len() as u64;
        let mut ticked = false;
        // A transaction is a new tick's only when the clock's tick moved: housekeeping (1 Hz) and
        // an install write the clock row too, with the same tick, and must count as later messages.
        for c in &batch {
            if let Change::Tick(t, ms) = c {
                if *t != self.tick {
                    self.tick = *t;
                    self.tick_ms = *ms;
                    ticked = true;
                }
            }
        }
        if ticked {
            self.idx = 0;
        } else {
            self.idx += 1;
        }
        let mut out: HashMap<Identity, Vec<u8>> = HashMap::new();
        let (sets, state): (Vec<Change>, Vec<Change>) = batch.into_iter().partition(|c| matches!(c, Change::SetAdd(..) | Change::SetDel(..) | Change::Player(..)));
        let apply_sets = |s: &mut State, out: &mut HashMap<Identity, Vec<u8>>, sets: Vec<Change>| {
            for c in sets {
                match c {
                    Change::SetAdd(v, b) => s.set_change(true, v, b, out),
                    Change::SetDel(v, b) => s.set_change(false, v, b, out),
                    Change::Player(v, ch) => {
                        s.players.insert(v, ch);
                        s.chars.insert(ch, v);
                    }
                    _ => {}
                }
            }
        };
        // The relay's one rule: a transaction's facts go out under that transaction's sets.
        // `broken` (the probe's known answer) sends them under the sets before it.
        let mut sets = Some(sets);
        if !self.broken {
            apply_sets(self, &mut out, sets.take().unwrap());
        }
        for c in state {
            match c {
                Change::Body(b) => {
                    self.fan(b.id, &mut out, |o| enc_body(o, &b));
                    self.bodies.insert(b.id, b);
                }
                Change::Fighter(f) => {
                    self.fan(f.id, &mut out, |o| enc_fighter(o, &f));
                    self.fighters.insert(f.id, f);
                }
                Change::Doing(d) => {
                    self.fan(d.id, &mut out, |o| enc_doing(o, &d));
                    self.doings.insert(d.id, d);
                }
                Change::BodyGone(id) => {
                    self.bodies.remove(&id);
                }
                Change::FighterGone(id) => {
                    self.fighters.remove(&id);
                }
                Change::DoingGone(id) => {
                    self.doings.remove(&id);
                }
                Change::Event(e) => {
                    let mut to: HashSet<Identity> = HashSet::new();
                    for id in [e.actor, e.target] {
                        if let Some(w) = self.watchers.get(&id) {
                            to.extend(w.iter().copied());
                        }
                        if let Some(v) = self.chars.get(&id) {
                            to.insert(*v);
                        }
                    }
                    for v in to {
                        enc_event(out.entry(v).or_default(), &e);
                    }
                }
                _ => {}
            }
        }
        if let Some(sets) = sets.take() {
            apply_sets(self, &mut out, sets);
        }
        if self.tick_ms >= self.last_hear_ms + 1000 {
            self.last_hear_ms = self.tick_ms;
            self.hear(&mut out);
        }
        self.send(out, recv_us);
        self.process_us += t0.elapsed().as_micros() as u64;
    }

    /// Hearing, 1 Hz: per connected viewer, the creatures within 9 m of its body outside its set,
    /// counted per bearing (8) and band (within 5 m, 15 m, beyond); a bucket goes out when its
    /// count changed.
    fn hear(&mut self, out: &mut HashMap<Identity, Vec<u8>>) {
        let now = self.tick_ms;
        let pos = |b: &Body| {
            let dt = now.saturating_sub(b.t_ms) as f32 / 1000.0;
            (b.x + b.vx * dt, b.y + b.vy * dt)
        };
        let viewers: Vec<Identity> = self.clients.keys().copied().collect();
        for v in viewers {
            let Some(me) = self.players.get(&v).and_then(|c| self.bodies.get(c)) else { continue };
            let (mx, my) = pos(me);
            let set = self.sets.get(&v);
            let mut counts = [0u16; 24];
            for b in self.bodies.values() {
                if b.id == me.id || set.is_some_and(|s| s.contains(&b.id)) {
                    continue;
                }
                let (x, y) = pos(b);
                let (dx, dy) = (x - mx, y - my);
                let d = (dx * dx + dy * dy).sqrt();
                if d > HEAR_M {
                    continue;
                }
                let bearing = (((dy.atan2(dx) + std::f32::consts::PI) / (std::f32::consts::PI / 4.0)) as usize).min(7);
                let band = if d <= 5.0 { 0 } else if d <= 15.0 { 1 } else { 2 };
                counts[bearing * 3 + band] += 1;
            }
            let old = self.heard.insert(v, counts).unwrap_or([0; 24]);
            for (i, (a, b)) in old.iter().zip(counts.iter()).enumerate() {
                if a != b {
                    let o = out.entry(v).or_default();
                    o.push(6);
                    o.push(i as u8);
                    o.extend_from_slice(&b.to_le_bytes());
                }
            }
        }
    }

    fn send(&mut self, out: HashMap<Identity, Vec<u8>>, recv_us: u64) {
        for (v, items) in out {
            if items.is_empty() {
                continue;
            }
            let Some(tx) = self.clients.get(&v) else {
                self.unsent_items += 1;
                continue;
            };
            let mut f = Vec::with_capacity(28 + items.len());
            put_u64(&mut f, self.tick);
            put_u32(&mut f, self.idx);
            put_u64(&mut f, recv_us);
            put_u64(&mut f, self.tick_ms);
            f.extend_from_slice(&items);
            self.frames += 1;
            self.items += 1;
            self.bytes += f.len() as u64;
            if tx.send(f).is_err() {
                self.clients.remove(&v);
            }
        }
    }

    /// A viewer connected: its set's whole state now, in its own frame.
    fn register(&mut self, v: Identity, tx: tokio::sync::mpsc::UnboundedSender<Vec<u8>>) {
        let mut items = Vec::new();
        if let Some(s) = self.sets.get(&v) {
            for b in s {
                if let Some(x) = self.bodies.get(b) {
                    enc_body(&mut items, x);
                }
                if let Some(x) = self.fighters.get(b) {
                    enc_fighter(&mut items, x);
                }
                if let Some(x) = self.doings.get(b) {
                    enc_doing(&mut items, x);
                }
            }
        }
        self.clients.insert(v, tx);
        let mut out = HashMap::new();
        out.insert(v, items);
        self.send(out, now_us());
    }
}

fn relay_mode(req: Value) {
    let (uri, db, token) = (req["uri"].as_str().unwrap(), req["db"].as_str().unwrap(), req["token"].as_str().unwrap());
    let listen = req["listen"].as_str().unwrap_or("127.0.0.1:3390").to_string();
    let out = req["out"].as_str().expect("out").to_string();
    let broken = req["broken"].as_bool().unwrap_or(false);
    let stop = stop_flag();
    let (reg_tx, reg_rx) = mpsc::channel::<Reg>();
    // The WebSocket side: its own runtime; each viewer says who it is, then reads frames.
    let rt = tokio::runtime::Builder::new_multi_thread().worker_threads(req["ws_threads"].as_u64().unwrap_or(2) as usize).enable_all().build().unwrap();
    let listener = rt.block_on(tokio::net::TcpListener::bind(&listen)).expect("listen");
    let accepted = Arc::new(AtomicU64::new(0));
    let acc = accepted.clone();
    rt.spawn(async move {
        loop {
            let Ok((sock, _)) = listener.accept().await else { continue };
            let _ = sock.set_nodelay(true);
            let reg_tx = reg_tx.clone();
            let acc = acc.clone();
            tokio::spawn(async move {
                let Ok(ws) = tokio_tungstenite::accept_async(sock).await else { return };
                let (mut sink, mut stream) = ws.split();
                let Some(Ok(first)) = stream.next().await else { return };
                let Ok(hex) = first.into_text() else { return };
                let Ok(v) = Identity::from_hex(hex.trim()) else { return };
                let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<Vec<u8>>();
                if reg_tx.send(Reg::Add(v, tx)).is_err() {
                    return;
                }
                acc.fetch_add(1, Ordering::SeqCst);
                while let Some(frame) = rx.recv().await {
                    if sink.send(tokio_tungstenite::tungstenite::Message::binary(frame)).await.is_err() {
                        break;
                    }
                }
                let _ = reg_tx.send(Reg::Drop(v));
            });
        }
    });
    let buf: Buf = Arc::default();
    let conn = connect(uri, db, token, buf.clone());
    let mut st = State { broken, ..State::default() };
    let started = Instant::now();
    let mut log = BufWriter::new(std::fs::File::create(format!("{out}.log")).unwrap());
    let mut last_log = Instant::now();
    println!("{}", json!({"event": "relay up", "listen": listen, "broken": broken}));
    while !stop.load(Ordering::SeqCst) {
        while let Ok(r) = reg_rx.try_recv() {
            match r {
                Reg::Add(v, tx) => st.register(v, tx),
                Reg::Drop(v) => {
                    st.clients.remove(&v);
                }
            }
        }
        match conn.advance_one_message() {
            Ok(true) => {
                let recv = now_us();
                let batch = std::mem::take(&mut *buf.lock().unwrap());
                st.process(batch, recv);
            }
            Ok(false) => std::thread::sleep(Duration::from_micros(200)),
            Err(e) => panic!("relay connection: {e}"),
        }
        if last_log.elapsed() >= Duration::from_secs(1) {
            last_log = Instant::now();
            let _ = writeln!(log, "{}", json!({"t": started.elapsed().as_secs_f64(), "txs": st.txs, "changes": st.changes, "frames": st.frames, "bytes": st.bytes,
                "clients": st.clients.len(), "unsent": st.unsent_items, "process_us": st.process_us, "tick": st.tick, "tick_lag_ms": (now_us() / 1000).saturating_sub(st.tick_ms)}));
            let _ = log.flush();
        }
    }
    let summary = json!({"txs": st.txs, "changes": st.changes, "frames": st.frames, "bytes": st.bytes, "clients": st.clients.len(), "accepted": accepted.load(Ordering::SeqCst),
        "unsent_frames": st.unsent_items, "process_us": st.process_us, "seconds": started.elapsed().as_secs_f64(), "broken": broken,
        "sets": st.sets.values().map(|s| s.len()).sum::<usize>(), "viewers_with_sets": st.sets.len(), "bodies": st.bodies.len()});
    std::fs::write(&out, summary.to_string()).unwrap();
    println!("{}", json!({"event": "relay done"}));
    std::process::exit(0);
}

fn checker_mode(req: Value) {
    let (uri, db, token) = (req["uri"].as_str().unwrap(), req["db"].as_str().unwrap(), req["token"].as_str().unwrap());
    let out = req["out"].as_str().expect("out").to_string();
    let stop = stop_flag();
    let buf: Buf = Arc::default();
    let conn = connect(uri, db, token, buf.clone());
    let mut w = BufWriter::new(std::fs::File::create(&out).unwrap());
    let (mut tick, mut idx) = (0u64, 0u32);
    println!("{}", json!({"event": "checker up"}));
    while !stop.load(Ordering::SeqCst) {
        match conn.advance_one_message() {
            Ok(true) => {
                let batch = std::mem::take(&mut *buf.lock().unwrap());
                let t = batch.iter().find_map(|c| if let Change::Tick(t, _) = c { Some(*t) } else { None }).filter(|t| *t != tick);
                match t {
                    Some(t) => {
                        tick = t;
                        idx = 0;
                    }
                    None => idx += 1,
                }
                for c in batch {
                    match c {
                        Change::SetAdd(v, b) => writeln!(w, "{tick} {idx} + {} {b}", v.to_hex()).unwrap(),
                        Change::SetDel(v, b) => writeln!(w, "{tick} {idx} - {} {b}", v.to_hex()).unwrap(),
                        Change::Player(v, ch) => writeln!(w, "{tick} {idx} P {} {ch}", v.to_hex()).unwrap(),
                        _ => {}
                    }
                }
            }
            Ok(false) => std::thread::sleep(Duration::from_micros(200)),
            Err(e) => panic!("checker connection: {e}"),
        }
    }
    w.flush().unwrap();
    println!("{}", json!({"event": "checker done"}));
    std::process::exit(0);
}

fn pct(v: &mut [u64], p: f64) -> Option<u64> {
    if v.is_empty() {
        return None;
    }
    v.sort_unstable();
    Some(v[((v.len() - 1) as f64 * p).round() as usize])
}

fn clients_mode(req: Value) {
    let relay = req["relay"].as_str().unwrap().to_string();
    let ids: Vec<String> = req["viewers"].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_string()).collect();
    let out = req["out"].as_str().expect("out").to_string();
    let stop = stop_flag();
    let rt = tokio::runtime::Builder::new_multi_thread().worker_threads(req["threads"].as_u64().unwrap_or(2) as usize).enable_all().build().unwrap();
    // Per viewer: the hops (µs, relay receipt to here) and ages (µs, the tick's time to here, per
    // frame; and a body's segment time to here, per body item); every item for the privacy check.
    let window = Arc::new(AtomicBool::new(false));
    let hops: Arc<Mutex<Vec<u64>>> = Arc::default();
    let ages: Arc<Mutex<Vec<u64>>> = Arc::default();
    let body_ages: Arc<Mutex<Vec<u64>>> = Arc::default();
    let counts: Arc<Mutex<[u64; 8]>> = Arc::default();
    let items_log = Arc::new(Mutex::new(BufWriter::new(std::fs::File::create(format!("{out}.items")).unwrap())));
    for (i, id) in ids.iter().enumerate() {
        let (relay, id) = (relay.clone(), id.clone());
        let (window, hops, ages, body_ages, counts, items_log) = (window.clone(), hops.clone(), ages.clone(), body_ages.clone(), counts.clone(), items_log.clone());
        rt.spawn(async move {
            let (ws, _) = tokio_tungstenite::connect_async(relay.as_str()).await.expect("relay ws");
            let (mut sink, mut stream) = ws.split();
            sink.send(tokio_tungstenite::tungstenite::Message::text(id.clone())).await.unwrap();
            while let Some(Ok(m)) = stream.next().await {
                let recv = now_us();
                let f = m.into_data();
                if f.len() < 28 {
                    continue;
                }
                let u64_at = |o: usize| u64::from_le_bytes(f[o..o + 8].try_into().unwrap());
                let u32_at = |o: usize| u32::from_le_bytes(f[o..o + 4].try_into().unwrap());
                let (tick, idx, relay_us, tick_ms) = (u64_at(0), u32_at(8), u64_at(12), u64_at(20));
                let on = window.load(Ordering::Relaxed);
                let mut lines = Vec::new();
                let mut o = 28;
                let mut bages = Vec::new();
                let mut c = [0u64; 8];
                while o < f.len() {
                    let k = f[o];
                    c[k as usize] += 1;
                    match k {
                        1 => {
                            let id = u32_at(o + 1);
                            let t_ms = u64_at(o + 5);
                            bages.push((recv / 1000).saturating_sub(t_ms) * 1000);
                            lines.push((k, id, 0u32));
                            o += 1 + 4 + 8 + 20;
                        }
                        2 => {
                            lines.push((k, u32_at(o + 1), 0));
                            o += 1 + 4 + 1 + 1 + 8 + 4;
                        }
                        3 => {
                            lines.push((k, u32_at(o + 1), 0));
                            o += 1 + 4 + 1 + 4 + 8;
                        }
                        4 => {
                            lines.push((k, u32_at(o + 1), 0));
                            o += 5;
                        }
                        5 => {
                            lines.push((k, u32_at(o + 2), u32_at(o + 6)));
                            o += 1 + 1 + 4 + 4 + 12;
                        }
                        6 => o += 4,
                        _ => break,
                    }
                }
                if on {
                    hops.lock().unwrap().push(recv.saturating_sub(relay_us));
                    if tick_ms > 0 {
                        ages.lock().unwrap().push(recv.saturating_sub(tick_ms * 1000));
                    }
                    body_ages.lock().unwrap().extend(bages);
                    let mut cc = counts.lock().unwrap();
                    for (a, b) in cc.iter_mut().zip(c.iter()) {
                        *a += b;
                    }
                }
                let mut w = items_log.lock().unwrap();
                for (k, a, b) in lines {
                    let _ = writeln!(w, "{i} {tick} {idx} {k} {a} {b}");
                }
            }
        });
    }
    println!("{}", json!({"event": "clients up", "viewers": ids.len()}));
    let started = Instant::now();
    let mut t_on = None;
    while !stop.load(Ordering::SeqCst) {
        std::thread::sleep(Duration::from_millis(100));
        if t_on.is_none() && started.elapsed() >= Duration::from_secs_f64(req["warmup"].as_f64().unwrap_or(5.0)) {
            window.store(true, Ordering::SeqCst);
            t_on = Some(Instant::now());
        }
    }
    window.store(false, Ordering::SeqCst);
    let secs = t_on.map(|t| t.elapsed().as_secs_f64()).unwrap_or(0.0);
    items_log.lock().unwrap().flush().unwrap();
    let mut h = hops.lock().unwrap().clone();
    let mut a = ages.lock().unwrap().clone();
    let mut ba = body_ages.lock().unwrap().clone();
    let c = *counts.lock().unwrap();
    let summary = json!({"viewers": ids.len(), "seconds": secs, "frames": h.len(), "items": {"body": c[1], "fighter": c[2], "doing": c[3], "gone": c[4], "event": c[5], "hear": c[6]},
        "hop_us": {"p50": pct(&mut h, 0.5), "p95": pct(&mut h, 0.95), "p99": pct(&mut h, 0.99), "max": h.iter().max()},
        "tick_age_us": {"p50": pct(&mut a, 0.5), "p95": pct(&mut a, 0.95), "p99": pct(&mut a, 0.99)},
        "body_age_us": {"p50": pct(&mut ba, 0.5), "p95": pct(&mut ba, 0.95), "p99": pct(&mut ba, 0.99)}});
    std::fs::write(&out, summary.to_string()).unwrap();
    println!("{}", json!({"event": "clients done"}));
    std::process::exit(0);
}


/// PERCEPTION_OFF_THREAD (branch perc-offthread): the stand-in for an off-thread perception computer.
/// It subscribes bodies and players as the owner and, for each player every 200 ms (a quarter of
/// them every 50 ms), picks a set by a geometric rule: the nearest 16 creatures within 25 m, a member
/// kept while it stays within the nearest 24 (hysteresis, so sets churn as heed's do rather than
/// every sweep). It sends each round's changes in one `perc_apply` call. It is not the sight rule
/// or heed: it stands for their output, so the authority's cost of applying sets can be measured.
fn perc_mode(req: Value) {
    let (uri, db, token) = (req["uri"].as_str().unwrap(), req["db"].as_str().unwrap(), req["token"].as_str().unwrap());
    let out = req["out"].as_str().expect("out").to_string();
    let (keep_n, cap, reach) = (req["keep_n"].as_u64().unwrap_or(24) as usize, req["cap"].as_u64().unwrap_or(16) as usize, req["reach_m"].as_f64().unwrap_or(25.0) as f32);
    // Extra churn, to match heed's measured turnover: per viewer and round, this share of rounds
    // swaps the farthest member for the nearest non-member (a deterministic stride, not random).
    let swap = req["swap"].as_f64().unwrap_or(0.0);
    let mut swap_acc = 0.0f64;
    let stop = stop_flag();
    let bodies: Arc<Mutex<HashMap<u32, Body>>> = Arc::default();
    let players: Arc<Mutex<HashMap<Identity, u32>>> = Arc::default();
    let conn = DbConnection::builder().with_uri(uri.to_string()).with_database_name(db.to_string()).with_token(Some(token.to_string())).build().expect("connect");
    let b = bodies.clone();
    conn.db.body().on_insert(move |_, r| {
        b.lock().unwrap().insert(r.id, r.clone());
    });
    let b = bodies.clone();
    conn.db.body().on_update(move |_, _, r| {
        b.lock().unwrap().insert(r.id, r.clone());
    });
    let b = bodies.clone();
    conn.db.body().on_delete(move |_, r| {
        b.lock().unwrap().remove(&r.id);
    });
    let pl = players.clone();
    conn.db.player().on_insert(move |_, r| {
        pl.lock().unwrap().insert(r.identity, r.character);
    });
    let pl = players.clone();
    conn.db.player().on_update(move |_, _, r| {
        pl.lock().unwrap().insert(r.identity, r.character);
    });
    conn.subscription_builder().on_error(|_, e| panic!("subscribe: {e}")).subscribe(vec!["SELECT * FROM body".to_string(), "SELECT * FROM player".to_string()]);
    conn.run_threaded();
    let mut sets: HashMap<Identity, Vec<u32>> = HashMap::new();
    let (mut calls, mut adds, mut dels, mut rounds, mut busy_us) = (0u64, 0u64, 0u64, 0u64, 0u64);
    let started = Instant::now();
    let mut phase = 0usize;
    println!("{}", json!({"event": "perc up"}));
    while !stop.load(Ordering::SeqCst) {
        let t0 = Instant::now();
        let now = now_us() / 1000;
        let diffs: Vec<PercDiff> = {
            let bodies = bodies.lock().unwrap();
            let players = players.lock().unwrap();
            let pos = |b: &Body| {
                let dt = now.saturating_sub(b.t_ms) as f32 / 1000.0;
                (b.x + b.vx * dt, b.y + b.vy * dt)
            };
            let mut viewers: Vec<(Identity, u32)> = players.iter().map(|(v, c)| (*v, *c)).collect();
            viewers.sort_by_key(|(_, c)| *c);
            let mut diffs = Vec::new();
            for (i, (v, c)) in viewers.iter().enumerate() {
                if i % 4 != phase {
                    continue;
                }
                let Some(me) = bodies.get(c) else { continue };
                let (mx, my) = pos(me);
                let mut near: Vec<(f32, u32)> = bodies.values().filter(|b| b.id != *c).filter_map(|b| {
                    let (x, y) = pos(b);
                    let d = ((x - mx).powi(2) + (y - my).powi(2)).sqrt();
                    (d <= reach).then_some((d, b.id))
                }).collect();
                near.sort_by(|a, b| a.0.total_cmp(&b.0));
                let rank: HashMap<u32, usize> = near.iter().enumerate().map(|(k, (_, id))| (*id, k)).collect();
                let old = sets.get(v).cloned().unwrap_or_default();
                let mut new: Vec<u32> = old.iter().copied().filter(|id| rank.get(id).is_some_and(|k| *k < keep_n)).collect();
                for (_, id) in &near {
                    if new.len() >= cap {
                        break;
                    }
                    if !new.contains(id) {
                        new.push(*id);
                    }
                }
                swap_acc += swap;
                if swap_acc >= 1.0 && new.len() >= cap {
                    swap_acc -= 1.0;
                    if let Some((_, out_id)) = near.iter().rev().find(|(_, id)| new.contains(id)).copied() {
                        if let Some((_, in_id)) = near.iter().find(|(_, id)| !new.contains(id) && !old.contains(id)).copied() {
                            new.retain(|x| *x != out_id);
                            new.push(in_id);
                        }
                    }
                }
                let add: Vec<u32> = new.iter().copied().filter(|id| !old.contains(id)).collect();
                let del: Vec<u32> = old.iter().copied().filter(|id| !new.contains(id)).collect();
                if !add.is_empty() || !del.is_empty() {
                    adds += add.len() as u64;
                    dels += del.len() as u64;
                    diffs.push(PercDiff { viewer: *v, character: *c, add, del });
                }
                sets.insert(*v, new);
            }
            diffs
        };
        phase = (phase + 1) % 4;
        rounds += 1;
        if !diffs.is_empty() {
            calls += 1;
            let _ = conn.reducers.perc_apply(diffs);
        }
        busy_us += t0.elapsed().as_micros() as u64;
        std::thread::sleep(Duration::from_millis(50).saturating_sub(t0.elapsed()));
    }
    let secs = started.elapsed().as_secs_f64();
    std::fs::write(&out, json!({"seconds": secs, "rounds": rounds, "calls": calls, "adds": adds, "dels": dels, "busy_us": busy_us,
        "viewers": sets.len(), "mean_set": if sets.is_empty() { 0.0 } else { sets.values().map(|s| s.len()).sum::<usize>() as f64 / sets.len() as f64 }}).to_string()).unwrap();
    println!("{}", json!({"event": "perc done"}));
    std::process::exit(0);
}

fn main() {
    let mode = std::env::args().nth(1).unwrap_or_default();
    let mut line = String::new();
    std::io::stdin().lock().read_line(&mut line).expect("request line");
    let req: Value = serde_json::from_str(&line).expect("request JSON");
    match mode.as_str() {
        "relay" => relay_mode(req),
        "checker" => checker_mode(req),
        "clients" => clients_mode(req),
        "perc" => perc_mode(req),
        m => panic!("mode {m:?}: relay, checker or clients"),
    }
}
