//! The immediate gate's load (docs/GATE_216.md; driven by living/tools/gate.py), and the playtest
//! soak's players (docs/SOAK.md; driven by living/tools/soak.py). Five modes:
//!
//! - `players`: scripted players over real WebSocket connections, subscribing what the game
//!   client subscribes (the perception views, the static tables, the `terrain_chunk` and `lot`
//!   windows) plus `my_skill_uses`. Each sends movement and skill inputs at a declared rate
//!   through the player reducers and records, per input, when it was sent, the server's
//!   timestamp for the call (`ReducerEvent.timestamp`: taken at receipt, before the database's
//!   queue; docs/GATE_216.md), when the call's own transaction came back, and, for a skill, when
//!   each later state of its `skill_use` row (accepted, released, outcome) reached the player
//!   through its own `my_skill_uses` view. The input's correlation id is the connection's call
//!   sequence (`p`, `n`); a skill's is also its `skill_use.id`.
//! - `relay`: a TCP relay that counts the bytes each connection receives (subscription traffic
//!   per client on the wire). Connections are numbered in accept order. A `cut N` line on stdin
//!   closes every open connection and refuses new ones for N seconds (a network outage).
//! - `soak`: a handful of players who play an evening (`soak.rs`).
//! - `watch`: two owner connections subscribing the private `clock` row, which every tick
//!   writes: one with confirmed reads (the default, what clients get) and one without, so every
//!   tick's delivery is timed with and without the commitlog's fsync.
//! - `observe`: the lab observer's subscriptions (living/viewer/src/net.rs) as the owner, with
//!   one character inspected.
//!
//! Times are the host's wall clock in microseconds (`SystemTime`); the server container shares
//! the host's kernel clock, and the namespaced clients do too.
//!
//! Protocol (`players`): one request JSON line on stdin; prints `{"event":"joined",…}` when
//! every character is alive, waits for a `placed` line, subscribes the windows round where each
//! one stands, prints `{"event":"ready"}`, waits for `go`, plays until `stop`, then prints
//! `{"event":"done",…}`.

mod soak;

use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, Event, Identity, Table, TableWithPrimaryKey};
use std::collections::{BTreeMap, HashMap};
use std::io::{BufRead, Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

fn unix_us() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_micros() as i64
}

fn now_ms() -> u64 {
    (unix_us() / 1000) as u64
}

/// JSON lines written by one thread, flushed about once a second.
#[derive(Clone)]
struct Log(mpsc::Sender<String>);

impl Log {
    fn open(path: &str) -> (Log, std::thread::JoinHandle<()>) {
        let (tx, rx) = mpsc::channel::<String>();
        let file = std::fs::File::create(path).unwrap_or_else(|e| panic!("{path}: {e}"));
        let h = std::thread::spawn(move || {
            let mut w = std::io::BufWriter::with_capacity(1 << 20, file);
            let mut last = Instant::now();
            loop {
                match rx.recv_timeout(Duration::from_millis(500)) {
                    // The close marker: callbacks still hold senders, so a dropped channel never shows.
                    Ok(line) if line.is_empty() => break,
                    Ok(line) => {
                        let _ = writeln!(w, "{line}");
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => {}
                    Err(mpsc::RecvTimeoutError::Disconnected) => break,
                }
                if last.elapsed() > Duration::from_secs(1) {
                    let _ = w.flush();
                    last = Instant::now();
                }
            }
            let _ = w.flush();
        });
        (Log(tx), h)
    }

    fn close(&self) {
        let _ = self.0.send(String::new());
    }

    fn put(&self, v: Value) {
        let _ = self.0.send(v.to_string());
    }
}

fn stdin_lines() -> mpsc::Receiver<String> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        for line in std::io::stdin().lock().lines() {
            let Ok(line) = line else { break };
            if tx.send(line.trim().to_string()).is_err() {
                break;
            }
        }
        let _ = tx.send("eof".into());
    });
    rx
}

fn wait_for(lines: &mpsc::Receiver<String>, word: &str) {
    loop {
        let l = lines.recv().unwrap_or_else(|_| "eof".into());
        if l == word {
            return;
        }
        if l == "eof" {
            panic!("stdin closed while waiting for {word}");
        }
    }
}

type Counts = Arc<Mutex<BTreeMap<&'static str, [u64; 3]>>>;

macro_rules! count {
    ($conn:expr, $counts:expr, $table:ident) => {{
        let c = $counts.clone();
        $conn.db.$table().on_insert(move |_, _| c.lock().unwrap().entry(stringify!($table)).or_default()[0] += 1);
        let c = $counts.clone();
        $conn.db.$table().on_update(move |_, _, _| c.lock().unwrap().entry(stringify!($table)).or_default()[1] += 1);
        let c = $counts.clone();
        $conn.db.$table().on_delete(move |_, _| c.lock().unwrap().entry(stringify!($table)).or_default()[2] += 1);
    }};
}

/// Tables (views) without a primary key: a change is a delete and an insert.
macro_rules! count_plain {
    ($conn:expr, $counts:expr, $table:ident) => {{
        let c = $counts.clone();
        $conn.db.$table().on_insert(move |_, _| c.lock().unwrap().entry(stringify!($table)).or_default()[0] += 1);
        let c = $counts.clone();
        $conn.db.$table().on_delete(move |_, _| c.lock().unwrap().entry(stringify!($table)).or_default()[2] += 1);
    }};
}

fn counts_json(c: &Counts) -> Value {
    let c = c.lock().unwrap();
    c.iter().map(|(t, n)| (t.to_string(), json!([n[0], n[1], n[2]]))).collect::<serde_json::Map<_, _>>().into()
}

// ---- players ---------------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Debug)]
enum Role {
    Battle,
    Walk,
}

#[derive(Default)]
struct St {
    me: Option<u32>,
    lives: u32,
    join_sent: Option<Instant>,
    dead_at: Option<Instant>,
    seq: u64,
    pending: u64,
    /// Server timestamp (µs) of my last call whose transaction changed my own motion row.
    own_moved_at: i64,
    /// Each skill use's last seen (accepted_ms, released_ms, outcome).
    uses: HashMap<u64, (u64, u64, String)>,
    last_dir: Option<(f32, f32, bool)>,
    last_move: Option<Instant>,
    target: u32,
    turn: u32,
    release_block_at: Option<Instant>,
    /// Until when my own last move holds me, as my client knows it (no skill is tried before).
    held_until: Option<Instant>,
}

struct Player {
    idx: usize,
    role: Role,
    name: String,
    conn: DbConnection,
    counts: Counts,
    st: Arc<Mutex<St>>,
    applied: Arc<Mutex<u32>>,
    errors: Arc<Mutex<Vec<String>>>,
}

fn status(res: &Result<Result<(), String>, spacetimedb_sdk::__codegen::InternalError>) -> String {
    match res {
        Ok(Ok(())) => "ok".into(),
        Ok(Err(e)) => format!("err:{e}"),
        Err(e) => format!("internal:{e}"),
    }
}

fn subscribe(p: &Player, queries: Vec<String>) {
    let (applied, errors) = (p.applied.clone(), p.errors.clone());
    p.conn
        .subscription_builder()
        .on_applied(move |_| *applied.lock().unwrap() += 1)
        .on_error(move |_, e| errors.lock().unwrap().push(e.to_string()))
        .subscribe(queries);
}

fn wait_applied(players: &[Player], want: u32, what: &str, limit: Duration) {
    let t = Instant::now();
    while players.iter().any(|p| *p.applied.lock().unwrap() < want && p.errors.lock().unwrap().is_empty()) {
        if t.elapsed() > limit {
            let late: Vec<usize> = players.iter().filter(|p| *p.applied.lock().unwrap() < want).map(|p| p.idx).collect();
            panic!("{what}: subscriptions of {late:?} not applied within {limit:?}");
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    for p in players {
        let e = p.errors.lock().unwrap();
        if !e.is_empty() {
            panic!("{what}: player {}: {}", p.idx, e.join("; "));
        }
    }
}

const CHUNK: f32 = 16.0;
const TERRAIN_CHUNKS: i32 = 3;
const LOT_CHUNKS: i32 = 11;

fn chunk_ranges(col: &str, (cx0, cx1): (u32, u32), (cy0, cy1): (u32, u32)) -> String {
    (cy0..=cy1).map(|cy| format!("({col} >= {} AND {col} <= {})", (cy << 16) | cx0, (cy << 16) | cx1)).collect::<Vec<_>>().join(" OR ")
}

/// Which client the players stand for (`client` in the request). `Gate`: what the gate measured
/// first (confirmed reads, the SDK default, and the subscriptions below). `Game`: the game client
/// as of the player verbs (living/game/src/net.rs): unconfirmed reads, the `skills` script row,
/// and `resource_node` and `structure` in the near window.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Client {
    Gate,
    Game,
}

impl Client {
    fn from(v: &Value) -> Self {
        match v.as_str() {
            None | Some("gate") => Client::Gate,
            Some("game") => Client::Game,
            Some(c) => panic!("client {c:?}: gate or game"),
        }
    }

    fn confirmed(self) -> Option<bool> {
        match self {
            Client::Gate => None,
            Client::Game => Some(false),
        }
    }

    fn base(self) -> Vec<String> {
        let mut q: Vec<String> = BASE.iter().map(|t| format!("SELECT * FROM {t}")).collect();
        if self == Client::Game {
            q.push("SELECT * FROM script WHERE name = 'skills'".into());
        }
        q
    }
}

/// The static windows the game client keeps round where it stands (living/game/src/net.rs).
fn windows(x: f32, y: f32, size: u32, client: Client) -> Vec<String> {
    let n = (size as f32 / CHUNK) as i32;
    let (cx, cy) = (((x / CHUNK).floor() as i32).clamp(0, n - 1), ((y / CHUNK).floor() as i32).clamp(0, n - 1));
    let span = |c: i32, r: i32| ((c - r).max(0) as u32, (c + r).min(n - 1) as u32);
    let (xs, ys) = (span(cx, TERRAIN_CHUNKS), span(cy, TERRAIN_CHUNKS));
    let mut q = vec![
        format!("SELECT * FROM terrain_chunk WHERE {}", chunk_ranges("id", xs, ys)),
        format!("SELECT * FROM lot WHERE {}", chunk_ranges("chunk", span(cx, LOT_CHUNKS), span(cy, LOT_CHUNKS))),
    ];
    if client == Client::Game {
        q.push(format!("SELECT * FROM resource_node WHERE {}", chunk_ranges("chunk", xs, ys)));
        q.push(format!("SELECT * FROM structure WHERE {}", chunk_ranges("chunk", xs, ys)));
    }
    q
}

/// What the game client subscribes once per connection, plus `my_skill_uses` (the correlation).
const BASE: &[&str] = &[
    "world", "land", "settlement", "seen_bodies", "seen_characters", "seen_fighters", "seen_doing", "my_characters", "my_vitals", "my_experience", "my_places",
    "my_inventory", "my_know_how", "my_combat", "my_readiness", "skill_card", "act_card", "weather", "my_skill_uses",
];

fn connect(uri: &str, db: &str, token: &str, confirmed: Option<bool>) -> (DbConnection, Identity) {
    let id: Arc<Mutex<Option<Identity>>> = Arc::default();
    let got = id.clone();
    let mut b = DbConnection::builder().with_uri(uri.to_string()).with_database_name(db.to_string()).with_token(Some(token.to_string())).on_connect(move |_, identity, _| *got.lock().unwrap() = Some(identity));
    if let Some(c) = confirmed {
        b = b.with_confirmed_reads(c);
    }
    let conn = b.build().expect("connect");
    conn.run_threaded();
    let t = Instant::now();
    let identity = loop {
        if let Some(i) = *id.lock().unwrap() {
            break i;
        }
        assert!(t.elapsed() < Duration::from_secs(60), "no identity");
        std::thread::sleep(Duration::from_millis(5));
    };
    (conn, identity)
}

fn hook(p: &Player, log: &Log) {
    let conn = &p.conn;
    count!(conn, p.counts, seen_bodies);
    count!(conn, p.counts, seen_characters);
    count!(conn, p.counts, seen_fighters);
    count!(conn, p.counts, seen_doing);
    count!(conn, p.counts, my_vitals);
    count!(conn, p.counts, my_experience);
    count!(conn, p.counts, my_characters);
    count!(conn, p.counts, my_inventory);
    count_plain!(conn, p.counts, my_combat);
    count_plain!(conn, p.counts, my_readiness);
    count_plain!(conn, p.counts, my_skill_uses);
    count!(conn, p.counts, terrain_chunk);
    count!(conn, p.counts, lot);
    // My character: alive (joined), dead.
    let (st, lg, idx) = (p.st.clone(), log.clone(), p.idx);
    conn.db.my_characters().on_insert(move |_, c| {
        if c.alive && !c.ai {
            let mut s = st.lock().unwrap();
            if s.me != Some(c.id) {
                s.me = Some(c.id);
                s.lives += 1;
                s.join_sent = None;
                s.dead_at = None;
                s.target = 0;
                lg.put(json!({"k": "alive", "p": idx, "id": c.id, "name": c.name, "ts": unix_us()}));
            }
        }
    });
    let (st, lg, idx) = (p.st.clone(), log.clone(), p.idx);
    conn.db.my_characters().on_update(move |_, old, c| {
        let mut s = st.lock().unwrap();
        if old.alive && !c.alive && s.me == Some(c.id) {
            s.me = None;
            s.dead_at = Some(Instant::now());
            lg.put(json!({"k": "death", "p": idx, "id": c.id, "cause": c.cause, "ts": unix_us(), "died_ms": c.died_ms}));
        } else if c.alive && s.me != Some(c.id) {
            s.me = Some(c.id);
            s.lives += 1;
            s.join_sent = None;
            s.dead_at = None;
            lg.put(json!({"k": "alive", "p": idx, "id": c.id, "name": c.name, "ts": unix_us()}));
        }
    });
    // My own motion row changed by my own call.
    let st = p.st.clone();
    let mine = move |ctx: &EventContext, id: u32, st: &Arc<Mutex<St>>| {
        if let Event::Reducer(ev) = &ctx.event {
            let mut s = st.lock().unwrap();
            if s.me == Some(id) {
                s.own_moved_at = ev.timestamp.to_micros_since_unix_epoch();
            }
        }
    };
    let st2 = st.clone();
    conn.db.seen_bodies().on_update(move |ctx, _, b| mine(ctx, b.id, &st2));
    conn.db.seen_bodies().on_insert(move |ctx, b| mine(ctx, b.id, &st));
    // Every state of my skill uses, as it reaches me.
    let (st, lg, idx) = (p.st.clone(), log.clone(), p.idx);
    conn.db.my_skill_uses().on_insert(move |ctx, u| {
        let ts = unix_us();
        let cur = (u.accepted_ms, u.released_ms, u.outcome.clone());
        let mut s = st.lock().unwrap();
        if s.uses.get(&u.id) == Some(&cur) {
            return;
        }
        s.uses.insert(u.id, cur);
        drop(s);
        let how = match &ctx.event {
            Event::Reducer(_) => "r",
            Event::Transaction => "t",
            Event::SubscribeApplied | Event::UnsubscribeApplied => return,
            _ => "o",
        };
        lg.put(json!({"k": "use", "p": idx, "use": u.id, "skill": u.skill, "src": u.source, "at": u.at_ms, "acc": u.accepted_ms, "rel": u.released_ms, "out": u.outcome, "out_ms": u.outcome_ms, "ts": ts, "ev": how}));
    });
}

fn next_seq(p: &Player) -> u64 {
    let mut s = p.st.lock().unwrap();
    s.seq += 1;
    s.pending += 1;
    s.seq
}

fn send_move(p: &Player, log: &Log, dx: f32, dy: f32, run: bool) {
    let n = next_seq(p);
    let (st, lg, idx) = (p.st.clone(), log.clone(), p.idx);
    let t0 = unix_us();
    let r = p.conn.reducers.human_move_then(dx, dy, run, move |ctx, res| {
        let t = unix_us();
        let srv = ctx.event.timestamp.to_micros_since_unix_epoch();
        let moved = {
            let mut s = st.lock().unwrap();
            s.pending -= 1;
            s.own_moved_at == srv
        };
        lg.put(json!({"k": "res", "p": idx, "n": n, "ts": t, "srv": srv, "st": status(&res), "moved": moved}));
    });
    log.put(json!({"k": "in", "p": p.idx, "n": n, "r": "move", "ts": t0, "dx": dx, "dy": dy, "run": run, "sent": r.is_ok()}));
    let mut s = p.st.lock().unwrap();
    s.last_dir = Some((dx, dy, run));
    s.last_move = Some(Instant::now());
}

fn send_skill(p: &Player, log: &Log, skill: &str, target: u32, x: f32, y: f32, hold_ms: u64) {
    p.st.lock().unwrap().held_until = Some(Instant::now() + Duration::from_millis(hold_ms));
    let n = next_seq(p);
    let (st, lg, idx, name) = (p.st.clone(), log.clone(), p.idx, skill.to_string());
    let t0 = unix_us();
    let r = p.conn.reducers.use_skill_then(skill.to_string(), target, x, y, move |ctx, res| {
        let t = unix_us();
        let srv = ctx.event.timestamp.to_micros_since_unix_epoch();
        st.lock().unwrap().pending -= 1;
        // The use this call recorded: mine, by a player, of this skill, at or after this call's
        // receipt (the authority acts at the receipt or, for a call that waited behind a tick,
        // at the tick's time: `common::now_ms`). The newest such row is this call's: the SDK
        // applies this call's transaction before the callback, and later calls commit after it.
        let at = (srv / 1000) as u64;
        let u = ctx.db.my_skill_uses().iter().filter(|u| u.source == "player" && u.skill == name && u.at_ms >= at).max_by_key(|u| u.id);
        lg.put(json!({"k": "res", "p": idx, "n": n, "ts": t, "srv": srv, "st": status(&res), "use": u.as_ref().map(|u| u.id), "acc": u.as_ref().map(|u| u.accepted_ms), "out": u.as_ref().map(|u| u.outcome.clone())}));
    });
    log.put(json!({"k": "in", "p": p.idx, "n": n, "r": "skill", "skill": skill, "target": target, "ts": t0, "sent": r.is_ok()}));
}

fn send_release(p: &Player, log: &Log, skill: &str) {
    let n = next_seq(p);
    let (st, lg, idx) = (p.st.clone(), log.clone(), p.idx);
    let t0 = unix_us();
    let r = p.conn.reducers.release_skill_then(skill.to_string(), move |ctx, res| {
        let t = unix_us();
        st.lock().unwrap().pending -= 1;
        lg.put(json!({"k": "res", "p": idx, "n": n, "ts": t, "srv": ctx.event.timestamp.to_micros_since_unix_epoch(), "st": status(&res)}));
    });
    log.put(json!({"k": "in", "p": p.idx, "n": n, "r": "release", "skill": skill, "ts": t0, "sent": r.is_ok()}));
}

fn send_join(p: &Player, log: &Log, name: String) {
    let n = next_seq(p);
    let (st, lg, idx) = (p.st.clone(), log.clone(), p.idx);
    let t0 = unix_us();
    p.st.lock().unwrap().join_sent = Some(Instant::now());
    let r = p.conn.reducers.join_then(name.clone(), move |ctx, res| {
        let t = unix_us();
        st.lock().unwrap().pending -= 1;
        lg.put(json!({"k": "res", "p": idx, "n": n, "ts": t, "srv": ctx.event.timestamp.to_micros_since_unix_epoch(), "st": status(&res)}));
    });
    log.put(json!({"k": "in", "p": p.idx, "n": n, "r": "join", "name": name, "ts": t0, "sent": r.is_ok()}));
}

/// A small xorshift, seeded per player: the script's choices are reproducible in kind, though
/// what the world does in reply is not.
struct Rng(u64);

impl Rng {
    fn f(&mut self) -> f32 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        (self.0 >> 40) as f32 / (1u64 << 24) as f32
    }
}

fn pos(m: &Motion, at_ms: u64) -> (f32, f32) {
    let dt = (at_ms.saturating_sub(m.t_ms) as f32 / 1000.0).min(2.0);
    (m.x + m.vx * dt, m.y + m.vy * dt)
}

fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}

#[derive(Clone)]
struct Card {
    cost: f32,
    reach: f32,
    /// Windup plus recovery: how long a timed move holds me (what the game shows by the clip).
    hold_ms: u64,
}

/// Rejoin after death, as a person at the death screen presses "arrive again".
fn rejoin(p: &Player, log: &Log, rejoin_s: f32) {
    let (dead_at, join_sent, lives) = {
        let s = p.st.lock().unwrap();
        (s.dead_at, s.join_sent, s.lives)
    };
    let Some(dead_at) = dead_at else { return };
    if dead_at.elapsed().as_secs_f32() < rejoin_s || join_sent.is_some_and(|j| j.elapsed() < Duration::from_secs(10)) {
        return;
    }
    let mut name = format!("{}r{}", p.name, lives);
    name.truncate(24);
    send_join(p, log, name);
}

/// One decision of a fighter: heal when hurt, strike in reach, shoot at range (now and then a
/// fire bolt), raise a guard or dodge now and then, and close in on the nearest person it
/// perceives (else walk to the battle).
fn fight(p: &Player, log: &Log, cards: &HashMap<String, Card>, center: (f32, f32), rng: &mut Rng, cfg: &Value) {
    let me = p.st.lock().unwrap().me;
    let Some(me) = me else { return rejoin(p, log, cfg["rejoin_s"].as_f64().unwrap_or(3.0) as f32) };
    let release = p.st.lock().unwrap().release_block_at;
    if release.is_some_and(|r| Instant::now() >= r) {
        p.st.lock().unwrap().release_block_at = None;
        send_release(p, log, "block");
    }
    let db = &p.conn.db;
    let now = now_ms();
    let Some(mb) = db.seen_bodies().id().find(&me) else { return };
    let here = pos(&mb, now);
    let current = p.st.lock().unwrap().target;
    let mut best: Option<(u32, (f32, f32), f32)> = None;
    for c in db.seen_characters().iter() {
        if c.own || c.id == me || c.kind != "person" {
            continue;
        }
        let Some(b) = db.seen_bodies().id().find(&c.id) else { continue };
        let at = pos(&b, now);
        let d = dist(here, at) * if c.id == current { 0.7 } else { 1.0 };
        if best.is_none_or(|(_, _, bd)| d < bd) {
            best = Some((c.id, at, d));
        }
    }
    let vit = db.my_vitals().id().find(&me);
    let (hp, max_hp, energy) = vit.map_or((1.0, 1.0, 100.0), |v| (v.hp, v.max_hp.max(1.0), v.energy));
    let ready = db.my_readiness().iter().find(|r| r.id == me);
    let held = p.st.lock().unwrap().held_until.is_some_and(|h| Instant::now() < h);
    let busy = held || ready.as_ref().is_some_and(|r| r.busy_until > now);
    let ok = |skill: &str, dash: bool| -> bool {
        let Some(card) = cards.get(skill) else { return false };
        let cooled = ready.as_ref().is_none_or(|r| r.ready.iter().all(|x| x.skill != skill || x.at_ms <= now));
        cooled && (dash || !busy) && energy >= card.cost
    };
    let arrows: u32 = db.my_inventory().iter().filter(|i| i.owner == me as u64 && i.item == "arrow").map(|i| i.qty).sum();
    let reach = |s: &str| cards.get(s).map_or(1.6, |c| c.reach);
    let hold = |s: &str| cards.get(s).map_or(0, |c| c.hold_ms);
    let mut used = false;
    if let Some((tid, at, _)) = best {
        p.st.lock().unwrap().target = tid;
        let d = dist(here, at);
        if hp / max_hp < 0.45 && ok("heal", false) {
            send_skill(p, log, "heal", 0, here.0, here.1, hold("heal"));
            used = true;
        } else if d <= reach("strike") + 0.4 && ok("strike", false) {
            send_skill(p, log, "strike", tid, at.0, at.1, hold("strike"));
            used = true;
        } else if d > 4.0 && d <= 15.0 && rng.f() < 0.25 && ok("firebolt", false) {
            send_skill(p, log, "firebolt", tid, at.0, at.1, hold("firebolt"));
            used = true;
        } else if d > 2.5 && d <= 14.0 && arrows > 0 && ok("bowshot", false) {
            send_skill(p, log, "bowshot", tid, at.0, at.1, hold("bowshot"));
            used = true;
        } else if d <= 6.0 && rng.f() < 0.08 && ok("block", false) {
            send_skill(p, log, "block", tid, at.0, at.1, hold("block"));
            p.st.lock().unwrap().release_block_at = Some(Instant::now() + Duration::from_millis(600));
            used = true;
        } else if d <= 6.0 && rng.f() < 0.05 && ok("dodge", true) {
            send_skill(p, log, "dodge", 0, here.0 - (at.0 - here.0), here.1 - (at.1 - here.1), hold("dodge"));
            used = true;
        }
    }
    if used || busy {
        return;
    }
    // Movement: toward the target, else toward the battle, else a small circle.
    let (goal, stop_within) = match best {
        Some((_, at, _)) => (at, 1.4),
        None => (center, 6.0),
    };
    let d = dist(here, goal);
    let want = if d > stop_within {
        let run = d > 6.0;
        ((goal.0 - here.0) / d, (goal.1 - here.1) / d, run)
    } else if best.is_none() {
        let mut s = p.st.lock().unwrap();
        s.turn += 1;
        let a = s.turn as f32 * 1.047;
        (a.cos(), a.sin(), false)
    } else {
        (0.0, 0.0, false)
    };
    let (last, since) = {
        let s = p.st.lock().unwrap();
        (s.last_dir, s.last_move.map(|t| t.elapsed()))
    };
    let changed = match last {
        None => true,
        Some((lx, ly, lr)) => {
            let stop_change = (lx == 0.0 && ly == 0.0) != (want.0 == 0.0 && want.1 == 0.0);
            let angle = (lx * want.0 + ly * want.1).clamp(-1.0, 1.0).acos();
            stop_change || lr != want.2 || angle > 0.52
        }
    };
    let refresh = since.is_none_or(|s| s > Duration::from_secs(2)) && (want.0 != 0.0 || want.1 != 0.0);
    if (changed || refresh) && since.is_none_or(|s| s > Duration::from_millis(200)) {
        send_move(p, log, want.0, want.1, want.2);
    }
}

/// One decision of a walker: a new direction, 60° on from the last (a small circle).
fn walk(p: &Player, log: &Log, cfg: &Value) {
    let me = p.st.lock().unwrap().me;
    if me.is_none() {
        return rejoin(p, log, cfg["rejoin_s"].as_f64().unwrap_or(3.0) as f32);
    }
    let a = {
        let mut s = p.st.lock().unwrap();
        s.turn += 1;
        s.turn as f32 * 1.047 + p.idx as f32 * 2.4
    };
    send_move(p, log, a.cos(), a.sin(), false);
}

fn players_mode() {
    let lines = stdin_lines();
    let req: Value = serde_json::from_str(&lines.recv().expect("request line")).expect("request JSON");
    let (uri, db) = (req["uri"].as_str().unwrap().to_string(), req["db"].as_str().unwrap().to_string());
    let (log, writer) = Log::open(req["events"].as_str().expect("events path"));
    let cfg = req["behaviour"].clone();
    let center = (req["battle"][0].as_f64().unwrap() as f32, req["battle"][1].as_f64().unwrap() as f32);
    let client = Client::from(&req["client"]);
    let started = Instant::now();
    let mut players = Vec::new();
    for (idx, p) in req["players"].as_array().unwrap().iter().enumerate() {
        let role = match p["role"].as_str() {
            Some("battle") => Role::Battle,
            Some("walk") => Role::Walk,
            r => panic!("role {r:?}"),
        };
        let t = unix_us();
        let (conn, identity) = connect(&uri, &db, p["token"].as_str().unwrap(), client.confirmed());
        log.put(json!({"k": "conn", "p": idx, "role": format!("{role:?}"), "identity": identity.to_hex().to_string(), "ts": t, "connected": unix_us()}));
        let pl = Player { idx, role, name: p["name"].as_str().unwrap().to_string(), conn, counts: Arc::default(), st: Arc::default(), applied: Arc::default(), errors: Arc::default() };
        hook(&pl, &log);
        subscribe(&pl, client.base());
        players.push(pl);
    }
    wait_applied(&players, 1, "base", Duration::from_secs(120));
    for p in &players {
        if p.st.lock().unwrap().me.is_none() {
            send_join(p, &log, p.name.clone());
        }
    }
    let t = Instant::now();
    while players.iter().any(|p| p.st.lock().unwrap().me.is_none()) {
        assert!(t.elapsed() < Duration::from_secs(120), "not every player joined");
        std::thread::sleep(Duration::from_millis(20));
    }
    let joined: Vec<Value> = players.iter().map(|p| json!({"p": p.idx, "name": p.name, "role": format!("{:?}", p.role), "id": p.st.lock().unwrap().me})).collect();
    println!("{}", json!({"event": "joined", "after_s": started.elapsed().as_secs_f32(), "players": joined}));
    let _ = std::io::stdout().flush();
    wait_for(&lines, "placed");
    // The static windows round where each one now stands.
    let size = players[0].conn.db.land().iter().next().map_or(2048, |l| l.size);
    let t = Instant::now();
    for p in &players {
        let me = p.st.lock().unwrap().me.unwrap();
        let at = loop {
            if let Some(b) = p.conn.db.seen_bodies().id().find(&me) {
                break (b.x, b.y);
            }
            assert!(t.elapsed() < Duration::from_secs(60), "no body for player {}", p.idx);
            std::thread::sleep(Duration::from_millis(10));
        };
        subscribe(p, windows(at.0, at.1, size, client));
    }
    wait_applied(&players, 2, "windows", Duration::from_secs(180));
    let cards: HashMap<String, Card> = players[0].conn.db.skill_card().iter().map(|c| (c.skill.clone(), Card { cost: c.cost, reach: c.reach, hold_ms: (c.windup_ms + c.recover_ms) as u64 })).collect();
    let held: Vec<Value> = players.iter().map(|p| json!({"bodies": p.conn.db.seen_bodies().count(), "characters": p.conn.db.seen_characters().count()})).collect();
    println!("{}", json!({"event": "ready", "after_s": started.elapsed().as_secs_f32(), "cards": cards.keys().collect::<Vec<_>>(), "held": held}));
    let _ = std::io::stdout().flush();
    wait_for(&lines, "go");
    for p in &players {
        p.counts.lock().unwrap().clear();
    }
    log.put(json!({"k": "go", "ts": unix_us()}));
    // `battle` sets the battle group fighting (until then it mills round where it was placed),
    // `calm` stops it, `stop` ends the run.
    let stop = Arc::new(AtomicBool::new(false));
    let fighting = Arc::new(AtomicBool::new(false));
    let (s2, f2, lg) = (stop.clone(), fighting.clone(), log.clone());
    std::thread::spawn(move || loop {
        let l = lines.recv().unwrap_or_else(|_| "eof".into());
        match l.as_str() {
            "battle" | "calm" => {
                f2.store(l == "battle", Ordering::SeqCst);
                lg.put(json!({"k": l, "ts": unix_us()}));
            }
            "stop" | "eof" => {
                s2.store(true, Ordering::SeqCst);
                return;
            }
            _ => {}
        }
    });
    let fight_ms = cfg["fight_period_ms"].as_u64().unwrap_or(250);
    let walk_ms = cfg["walk_period_ms"].as_u64().unwrap_or(1500);
    let n = players.len();
    // Staggered first decisions, so the inputs spread over each period.
    let mut next: Vec<Instant> = players
        .iter()
        .map(|p| Instant::now() + Duration::from_millis(match p.role {
            Role::Battle => fight_ms * p.idx as u64 / n as u64,
            Role::Walk => walk_ms * p.idx as u64 / n as u64,
        }))
        .collect();
    let mut rngs: Vec<Rng> = (0..n).map(|i| Rng(0x9E37_79B9_7F4A_7C15 ^ (i as u64 + 1).wrapping_mul(0xBF58_476D_1CE4_E5B9))).collect();
    let mut late = 0u64;
    while !stop.load(Ordering::SeqCst) {
        let now = Instant::now();
        for (i, p) in players.iter().enumerate() {
            if next[i] > now {
                continue;
            }
            if now.duration_since(next[i]) > Duration::from_millis(50) {
                late += 1;
            }
            let period = match p.role {
                Role::Battle if fighting.load(Ordering::Relaxed) => {
                    fight(p, &log, &cards, center, &mut rngs[i], &cfg);
                    fight_ms
                }
                Role::Battle | Role::Walk => {
                    walk(p, &log, &cfg);
                    walk_ms
                }
            };
            let jitter = (rngs[i].f() * 0.2 - 0.1) * period as f32;
            next[i] = now + Duration::from_millis((period as f32 + jitter) as u64);
        }
        std::thread::sleep(Duration::from_millis(4));
    }
    log.put(json!({"k": "stop", "ts": unix_us()}));
    // Grace for calls in flight, then what each connection received over the run.
    std::thread::sleep(Duration::from_secs(cfg["grace_s"].as_u64().unwrap_or(5)));
    let out: Vec<Value> = players
        .iter()
        .map(|p| {
            let s = p.st.lock().unwrap();
            json!({"p": p.idx, "role": format!("{:?}", p.role), "lives": s.lives, "alive": s.me.is_some(), "calls": s.seq, "unanswered": s.pending,
                   "events": counts_json(&p.counts), "held": {"bodies": p.conn.db.seen_bodies().count(), "characters": p.conn.db.seen_characters().count()},
                   "errors": *p.errors.lock().unwrap()})
        })
        .collect();
    println!("{}", json!({"event": "done", "late_decisions": late, "players": out}));
    let _ = std::io::stdout().flush();
    for p in &players {
        let _ = p.conn.disconnect();
    }
    log.close();
    let _ = writer.join();
    // The SDK's connection threads would keep the process alive.
    std::process::exit(0);
}

// ---- relay -----------------------------------------------------------------------------------

struct Conn {
    /// Both ends, so a `cut` can close them.
    ends: Option<(TcpStream, TcpStream)>,
    accepted_us: i64,
    down: Arc<AtomicU64>,
    up: Arc<AtomicU64>,
    open: Arc<AtomicBool>,
}

fn pipe(mut src: TcpStream, mut dst: TcpStream, count: Arc<AtomicU64>, open: Arc<AtomicBool>) {
    let mut buf = vec![0u8; 1 << 16];
    loop {
        match src.read(&mut buf) {
            Ok(0) | Err(_) => break,
            Ok(n) => {
                if dst.write_all(&buf[..n]).is_err() {
                    break;
                }
                count.fetch_add(n as u64, Ordering::Relaxed);
            }
        }
    }
    open.store(false, Ordering::Relaxed);
    let _ = src.shutdown(Shutdown::Both);
    let _ = dst.shutdown(Shutdown::Both);
}

fn relay_mode(args: &[String]) {
    let arg = |k: &str| args.iter().position(|a| a == k).and_then(|i| args.get(i + 1)).cloned().unwrap_or_else(|| panic!("{k} required"));
    let (listen, upstream, out) = (arg("--listen"), arg("--upstream"), arg("--out"));
    let listener = TcpListener::bind(&listen).expect("bind");
    let conns: Arc<Mutex<Vec<Conn>>> = Arc::default();
    let c2 = conns.clone();
    // Until when new connections are refused (a `cut N` line: the network is down N seconds).
    let refuse_until: Arc<Mutex<Option<Instant>>> = Arc::default();
    let r2 = refuse_until.clone();
    std::thread::spawn(move || {
        for s in listener.incoming() {
            let Ok(client) = s else { continue };
            if r2.lock().unwrap().is_some_and(|t| Instant::now() < t) {
                let _ = client.shutdown(Shutdown::Both);
                continue;
            }
            let accepted_us = unix_us();
            let Ok(up) = TcpStream::connect(&upstream) else {
                let _ = client.shutdown(Shutdown::Both);
                continue;
            };
            let _ = client.set_nodelay(true);
            let _ = up.set_nodelay(true);
            let ends = client.try_clone().ok().zip(up.try_clone().ok());
            let c = Conn { ends, accepted_us, down: Arc::default(), up: Arc::default(), open: Arc::new(AtomicBool::new(true)) };
            let (a, b) = (client.try_clone().unwrap(), up.try_clone().unwrap());
            let (down, upc, open1, open2) = (c.down.clone(), c.up.clone(), c.open.clone(), c.open.clone());
            std::thread::spawn(move || pipe(up, client, down, open1));
            std::thread::spawn(move || pipe(a, b, upc, open2));
            c2.lock().unwrap().push(c);
        }
    });
    let mut file = std::io::BufWriter::new(std::fs::File::create(&out).expect("relay out"));
    let snapshot = |file: &mut std::io::BufWriter<std::fs::File>| {
        let c = conns.lock().unwrap();
        let rows: Vec<Value> = c.iter().enumerate().map(|(i, c)| json!([i, c.accepted_us, c.down.load(Ordering::Relaxed), c.up.load(Ordering::Relaxed), c.open.load(Ordering::Relaxed)])).collect();
        let _ = writeln!(file, "{}", json!({"t": unix_us(), "c": rows}));
        let _ = file.flush();
    };
    // stdin: `cut N` closes every open connection and refuses new ones for N seconds; end of
    // input stops the relay.
    let (tx, rx) = mpsc::channel();
    let (c3, r3) = (conns.clone(), refuse_until.clone());
    std::thread::spawn(move || {
        for line in std::io::stdin().lock().lines() {
            let Ok(line) = line else { break };
            if let Some(n) = line.trim().strip_prefix("cut ").and_then(|n| n.trim().parse::<f64>().ok()) {
                *r3.lock().unwrap() = Some(Instant::now() + Duration::from_secs_f64(n));
                let mut closed = 0;
                for c in c3.lock().unwrap().iter_mut() {
                    if let Some((a, b)) = c.ends.take() {
                        if c.open.load(Ordering::Relaxed) {
                            closed += 1;
                        }
                        let _ = a.shutdown(Shutdown::Both);
                        let _ = b.shutdown(Shutdown::Both);
                    }
                }
                println!("{}", json!({"event": "cut", "closed": closed, "secs": n, "ts": unix_us()}));
                let _ = std::io::stdout().flush();
            }
        }
        let _ = tx.send(());
    });
    loop {
        match rx.recv_timeout(Duration::from_secs(5)) {
            Ok(()) | Err(mpsc::RecvTimeoutError::Disconnected) => break,
            Err(mpsc::RecvTimeoutError::Timeout) => snapshot(&mut file),
        }
    }
    snapshot(&mut file);
}

// ---- watch -----------------------------------------------------------------------------------

fn watch_mode() {
    let lines = stdin_lines();
    let req: Value = serde_json::from_str(&lines.recv().expect("request line")).expect("request JSON");
    let (uri, db, token) = (req["uri"].as_str().unwrap(), req["db"].as_str().unwrap(), req["token"].as_str().unwrap());
    let out = Arc::new(Mutex::new(std::io::BufWriter::with_capacity(1 << 20, std::fs::File::create(req["out"].as_str().unwrap()).expect("watch out"))));
    let mut conns = Vec::new();
    for confirmed in [true, false] {
        let (conn, _) = connect(uri, db, token, Some(confirmed));
        let o = out.clone();
        let flag = if confirmed { 'c' } else { 'u' };
        conn.db.clock().on_update(move |_, _, k| {
            let t = unix_us();
            let _ = writeln!(o.lock().unwrap(), "{flag},{},{},{t}", k.tick, k.last_ms);
        });
        let applied = Arc::new(AtomicBool::new(false));
        let a2 = applied.clone();
        conn.subscription_builder().on_applied(move |_| a2.store(true, Ordering::SeqCst)).on_error(|_, e| panic!("watch: {e}")).subscribe(vec!["SELECT * FROM clock".to_string()]);
        let t = Instant::now();
        while !applied.load(Ordering::SeqCst) {
            assert!(t.elapsed() < Duration::from_secs(30), "clock subscription");
            std::thread::sleep(Duration::from_millis(10));
        }
        conns.push(conn);
    }
    println!("{}", json!({"event": "ready"}));
    let _ = std::io::stdout().flush();
    let o = out.clone();
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_secs(1));
        let _ = o.lock().unwrap().flush();
    });
    wait_for(&lines, "stop");
    let _ = out.lock().unwrap().flush();
    for c in &conns {
        let _ = c.disconnect();
    }
    std::process::exit(0);
}

// ---- observe ---------------------------------------------------------------------------------

/// The lab observer's subscriptions (living/viewer/src/net.rs), all whole tables.
const OBSERVER: &[&str] = &[
    "world", "terrain_chunk", "character", "body", "vitals", "activity", "inventory", "resource_node", "structure", "brain", "mind_state", "persona", "relation", "belief",
    "judgment", "place", "thought", "chronicle", "stats", "bond_offer", "expecting", "mind_cursor", "know_how", "artifact", "trade_offer", "background", "gate",
];

fn observe_mode() {
    let lines = stdin_lines();
    let req: Value = serde_json::from_str(&lines.recv().expect("request line")).expect("request JSON");
    let (uri, db, token) = (req["uri"].as_str().unwrap(), req["db"].as_str().unwrap(), req["token"].as_str().unwrap());
    let actor = req["inspect"].as_u64().unwrap_or(0);
    let (conn, _) = connect(uri, db, token, None);
    let counts: Counts = Arc::default();
    count!(conn, counts, body);
    count!(conn, counts, character);
    count!(conn, counts, vitals);
    count!(conn, counts, activity);
    count!(conn, counts, chronicle);
    count!(conn, counts, experience);
    let t0 = Instant::now();
    let applied = Arc::new(Mutex::new(0u32));
    let mut queries: Vec<String> = OBSERVER.iter().map(|t| format!("SELECT * FROM {t}")).collect();
    queries.extend([
        format!("SELECT * FROM experience WHERE observer = {actor}"),
        format!("SELECT * FROM routine WHERE actor = {actor}"),
        format!("SELECT s.* FROM routine_stat s JOIN routine r ON s.id = r.id WHERE r.actor = {actor}"),
    ]);
    let a2 = applied.clone();
    conn.subscription_builder().on_applied(move |_| *a2.lock().unwrap() += 1).on_error(|_, e| panic!("observe: {e}")).subscribe(queries);
    while *applied.lock().unwrap() < 1 {
        assert!(t0.elapsed() < Duration::from_secs(120), "observer subscription");
        std::thread::sleep(Duration::from_millis(20));
    }
    println!("{}", json!({"event": "ready", "after_s": t0.elapsed().as_secs_f32()}));
    let _ = std::io::stdout().flush();
    counts.lock().unwrap().clear();
    wait_for(&lines, "stop");
    println!("{}", json!({"event": "done", "events": counts_json(&counts), "bodies": conn.db.body().count(), "characters": conn.db.character().count()}));
    let _ = std::io::stdout().flush();
    let _ = conn.disconnect();
    std::process::exit(0);
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("players") => players_mode(),
        Some("relay") => relay_mode(&args[2..]),
        Some("watch") => watch_mode(),
        Some("observe") => observe_mode(),
        Some("soak") => soak::run(),
        m => {
            eprintln!("usage: gate-load players|relay|watch|observe|soak (got {m:?})");
            std::process::exit(2);
        }
    }
}
