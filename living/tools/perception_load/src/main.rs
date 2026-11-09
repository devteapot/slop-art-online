//! N player connections that subscribe what the game client subscribes, for the perception
//! benchmark (`living/tools/perception_bench.py`, docs/PERCEPTION.md).
//!
//! Reads one JSON request on stdin: `{"uri", "db", "mode": "open" | "scoped", "seconds",
//! "tokens": [...]}`. Each token is a player identity whose character has already joined.
//! - `open`: the game client's subscriptions at `b7cf7fb` (`living/game/src/net.rs`): the
//!   static tables, my character by `:sender`, my rows by id, and the near (`body`, the
//!   `character`/`fighter`/`doing` joins, `terrain_chunk`) and far (`lot`) chunk windows round
//!   my body.
//! - `scoped`: the same static tables and windows of static data (`terrain_chunk`, `lot`), and
//!   the perception views (`seen_*`, `my_*`) in place of everything else.
//!
//! The windows are subscribed once round where each character starts. With `"walk": true`
//! every character keeps turning as it walks (a new `human_move` direction every 1.5 s, 60°
//! on, about a 4 m circle), so they mill about where they were placed. Prints `{"event":"ready"}`
//! when every connection's subscriptions are applied, then after `seconds` one JSON line with
//! the row events each connection received per table (inserts, updates, deletes) and the rows
//! it holds. Bytes come from the server's metrics, not from here.

use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, Identity, Table, TableWithPrimaryKey};
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

const BODY_CHUNKS: i32 = 5;
const TERRAIN_CHUNKS: i32 = 3;
const LOT_CHUNKS: i32 = 11;
const CHUNK: f32 = 16.0;

type Counts = Arc<Mutex<BTreeMap<&'static str, [u64; 3]>>>;

fn chunk_id(cx: u32, cy: u32) -> u32 {
    (cy << 16) | cx
}

fn chunk_ranges(col: &str, (cx0, cx1): (u32, u32), (cy0, cy1): (u32, u32)) -> String {
    (cy0..=cy1).map(|cy| format!("({col} >= {} AND {col} <= {})", chunk_id(cx0, cy), chunk_id(cx1, cy))).collect::<Vec<_>>().join(" OR ")
}

/// The near and far windows round `(x, y)` on a `size`-tile land, as the game client builds them.
fn windows(x: f32, y: f32, size: u32, open: bool) -> Vec<String> {
    let n = (size as f32 / CHUNK) as i32;
    let (cx, cy) = (((x / CHUNK).floor() as i32).clamp(0, n - 1), ((y / CHUNK).floor() as i32).clamp(0, n - 1));
    let span = |c: i32, r: i32| ((c - r).max(0) as u32, (c + r).min(n - 1) as u32);
    let (xs, ys) = (span(cx, BODY_CHUNKS), span(cy, BODY_CHUNKS));
    let mut q = vec![
        format!("SELECT * FROM terrain_chunk WHERE {}", chunk_ranges("id", span(cx, TERRAIN_CHUNKS), span(cy, TERRAIN_CHUNKS))),
        format!("SELECT * FROM lot WHERE {}", chunk_ranges("chunk", span(cx, LOT_CHUNKS), span(cy, LOT_CHUNKS))),
    ];
    if open {
        q.push(format!("SELECT * FROM body WHERE {}", chunk_ranges("chunk", xs, ys)));
        q.push(format!("SELECT character.* FROM character JOIN body ON character.id = body.id WHERE {}", chunk_ranges("body.chunk", xs, ys)));
        q.push(format!("SELECT fighter.* FROM fighter JOIN body ON fighter.id = body.id WHERE {}", chunk_ranges("body.chunk", xs, ys)));
        q.push(format!("SELECT doing.* FROM doing JOIN body ON doing.id = body.id WHERE {}", chunk_ranges("body.chunk", xs, ys)));
    }
    q
}

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

struct Player {
    conn: DbConnection,
    identity: Identity,
    counts: Counts,
    applied: Arc<Mutex<u32>>,
    errors: Arc<Mutex<Vec<String>>>,
}

fn subscribe(p: &Player, queries: Vec<String>) {
    let (applied, errors) = (p.applied.clone(), p.errors.clone());
    p.conn
        .subscription_builder()
        .on_applied(move |_| *applied.lock().unwrap() += 1)
        .on_error(move |_, e| errors.lock().unwrap().push(e.to_string()))
        .subscribe(queries);
}

fn wait(players: &[Player], want: u32, what: &str, limit: Duration) {
    let t = Instant::now();
    while players.iter().any(|p| *p.applied.lock().unwrap() < want && p.errors.lock().unwrap().is_empty()) {
        if t.elapsed() > limit {
            panic!("{what}: not every subscription applied within {limit:?}");
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    for p in players {
        let e = p.errors.lock().unwrap();
        if !e.is_empty() {
            panic!("{what}: {}", e.join("; "));
        }
    }
}

fn main() {
    let req: Value = serde_json::from_reader(std::io::stdin()).expect("request JSON");
    let (uri, db) = (req["uri"].as_str().unwrap().to_string(), req["db"].as_str().unwrap().to_string());
    let open = match req["mode"].as_str() {
        Some("open") => true,
        Some("scoped") => false,
        m => panic!("mode must be open or scoped, not {m:?}"),
    };
    let seconds = req["seconds"].as_u64().unwrap_or(60);
    let walk = req["walk"].as_bool().unwrap_or(false);
    let started = Instant::now();
    let mut players = Vec::new();
    for token in req["tokens"].as_array().unwrap() {
        let counts: Counts = Arc::default();
        let id: Arc<Mutex<Option<Identity>>> = Arc::default();
        let got = id.clone();
        let conn = DbConnection::builder()
            .with_uri(uri.clone())
            .with_database_name(db.clone())
            .with_token(Some(token.as_str().unwrap().to_string()))
            .on_connect(move |_, identity, _| *got.lock().unwrap() = Some(identity))
            .build()
            .expect("connect");
        count!(conn, counts, body);
        count!(conn, counts, character);
        count!(conn, counts, fighter);
        count!(conn, counts, doing);
        count!(conn, counts, vitals);
        count!(conn, counts, experience);
        count!(conn, counts, seen_bodies);
        count!(conn, counts, seen_characters);
        count!(conn, counts, seen_fighters);
        count!(conn, counts, seen_doing);
        count!(conn, counts, my_vitals);
        count!(conn, counts, my_experience);
        count!(conn, counts, terrain_chunk);
        count!(conn, counts, lot);
        conn.run_threaded();
        let t = Instant::now();
        let identity = loop {
            if let Some(i) = *id.lock().unwrap() {
                break i;
            }
            assert!(t.elapsed() < Duration::from_secs(30), "no identity");
            std::thread::sleep(Duration::from_millis(10));
        };
        players.push(Player { conn, identity, counts, applied: Arc::default(), errors: Arc::default() });
    }
    // The static tables and the per-connection views, as the game client subscribes them.
    let mut base: Vec<String> = ["world", "land", "settlement", "skill_card", "act_card", "weather", "my_combat", "my_readiness"].iter().map(|t| format!("SELECT * FROM {t}")).collect();
    if open {
        base.push("SELECT * FROM character WHERE controller = :sender".into());
    } else {
        base.extend(["seen_bodies", "seen_characters", "seen_fighters", "seen_doing", "my_characters", "my_vitals", "my_experience", "my_places", "my_inventory", "my_know_how"].iter().map(|t| format!("SELECT * FROM {t}")));
    }
    for p in &players {
        subscribe(p, base.clone());
    }
    wait(&players, 1, "base", Duration::from_secs(60));
    let size = players[0].conn.db.land().iter().next().map_or(2048, |l| l.size);
    // My character and where it stands, then my rows and the windows round it.
    for p in &players {
        let at = if open {
            let me = p.conn.db.character().iter().find(|c| c.controller == p.identity && c.alive).expect("a living character for every token");
            let id = me.id;
            subscribe(p, vec![format!("SELECT * FROM body WHERE id = {id}")]);
            let t = Instant::now();
            loop {
                if let Some(b) = p.conn.db.body().id().find(&id) {
                    break (b.x, b.y, id);
                }
                assert!(t.elapsed() < Duration::from_secs(30), "no body for #{id}");
                std::thread::sleep(Duration::from_millis(10));
            }
        } else {
            let me = p.conn.db.my_characters().iter().find(|c| c.alive).expect("a living character for every token");
            let b = p.conn.db.seen_bodies().id().find(&me.id).expect("my own body in seen_bodies");
            (b.x, b.y, me.id)
        };
        let (x, y, id) = at;
        let mut q = windows(x, y, size, open);
        if open {
            q.extend([
                format!("SELECT * FROM vitals WHERE id = {id}"),
                format!("SELECT * FROM experience WHERE observer = {id}"),
                format!("SELECT * FROM place WHERE actor = {id}"),
                format!("SELECT * FROM inventory WHERE owner = {id}"),
                format!("SELECT * FROM know_how WHERE actor = {id}"),
            ]);
        }
        subscribe(p, q);
    }
    wait(&players, if open { 3 } else { 2 }, "windows", Duration::from_secs(120));
    // Counts from here on are the window's.
    let held = |p: &Player| -> Value {
        json!({
            "bodies": if open { p.conn.db.body().count() } else { p.conn.db.seen_bodies().count() },
            "characters": if open { p.conn.db.character().count() } else { p.conn.db.seen_characters().count() },
            "experience": if open { p.conn.db.experience().count() } else { p.conn.db.my_experience().count() },
        })
    };
    let at_ready: Vec<Value> = players.iter().map(held).collect();
    for p in &players {
        p.counts.lock().unwrap().clear();
    }
    println!("{}", json!({"event": "ready", "after_s": started.elapsed().as_secs_f32(), "held": at_ready}));
    let end = Instant::now() + Duration::from_secs(seconds);
    if walk {
        let n = players.len();
        let mut turn = 0u64;
        while Instant::now() < end {
            // One player in turn every 1.5 s / n, so each turns every 1.5 s.
            let i = (turn as usize) % n;
            let a = (turn / n as u64) as f32 * 1.047 + i as f32 * 2.4;
            let _ = players[i].conn.reducers.human_move(a.cos(), a.sin(), false);
            turn += 1;
            std::thread::sleep(Duration::from_secs_f32(1.5 / n as f32));
        }
    } else {
        std::thread::sleep(Duration::from_secs(seconds));
    }
    let out: Vec<Value> = players
        .iter()
        .map(|p| {
            let c = p.counts.lock().unwrap();
            json!({
                "events": c.iter().map(|(t, n)| (t.to_string(), json!({"insert": n[0], "update": n[1], "delete": n[2]}))).collect::<serde_json::Map<_, _>>(),
                "held": held(p),
                "errors": *p.errors.lock().unwrap(),
            })
        })
        .collect();
    println!("{}", json!({"event": "done", "seconds": seconds, "players": out}));
    for p in &players {
        let _ = p.conn.disconnect();
    }
}
