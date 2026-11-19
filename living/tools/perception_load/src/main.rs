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
//! it holds. Bytes come from the server's metrics.
//! Optional `"gaze": "off" | "mix" | "far" | "rapid"` subscribes to both senses views.
//! Mix starts with 80% Middle, 10% Far and 10% Near. Rapid offers one change per player per
//! 250 ms and records the reducer acknowledgements and their round-trip durations.

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
    let gaze = req["gaze"].as_str().unwrap_or("off");
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
        count!(conn, counts, my_senses);
        count!(conn, counts, my_senses_v_2);
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
        base.extend(["my_body", "seen_bodies", "seen_characters", "seen_fighters", "seen_doing", "my_characters", "my_vitals", "my_experience", "my_places", "my_inventory", "my_know_how"].iter().map(|t| format!("SELECT * FROM {t}")));
    }
    if req["gaze"].is_string() {
        let tables = ["cover_law", "my_fighter", "my_doing", "my_offers", "my_known_names",
                      "my_earshot", "speech_card", "my_records", "heard_sounds", "my_senses",
                      "my_senses_v_2", "my_act_outcomes"];
        base.extend(tables.map(|t| format!("SELECT * FROM {t}")));
        base.push("SELECT * FROM script WHERE name = 'skills'".into());
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
            let b = p.conn.db.my_body().id().find(&me.id).expect("my own body in my_body");
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
    if matches!(gaze, "far" | "mix" | "rapid") {
        let expected: Vec<_> = (0..players.len()).map(|i| match gaze {
            "far" => 1,
            "mix" if i % 10 == 0 => 1,
            "mix" if i % 10 == 1 => 2,
            _ => 0,
        }).collect();
        for (p, band) in players.iter().zip(&expected) {
            if *band != 0 {
                p.conn.reducers.human_gaze(*band).expect("initial gaze request");
            }
        }
        let until = Instant::now() + Duration::from_secs(15);
        while players.iter().zip(&expected).any(|(p, band)| {
            !p.conn.db.my_senses_v_2().iter().any(|row| row.band == *band)
        }) {
            assert!(Instant::now() < until, "initial gaze bands did not reach the load clients");
            std::thread::sleep(Duration::from_millis(20));
        }
    }
    let at_ready: Vec<Value> = players.iter().map(held).collect();
    for p in &players {
        p.counts.lock().unwrap().clear();
    }
    println!("{}", json!({"event": "ready", "after_s": started.elapsed().as_secs_f32(), "held": at_ready}));
    let start = Instant::now();
    let end = start + Duration::from_secs(seconds);
    let n = players.len();
    let mut moves = 0usize;
    let mut changes = 0usize;
    let acknowledgments = Arc::new(Mutex::new(Vec::new()));
    let last_accepted: Vec<_> = (0..n).map(|_| Arc::new(Mutex::new(0u8))).collect();
    loop {
        let next_move = if walk { start + Duration::from_secs_f64(moves as f64 * 1.5 / n as f64) } else { end };
        let next_gaze = if gaze == "rapid" { start + Duration::from_secs_f64(changes as f64 * 0.25 / n as f64) } else { end };
        let next = next_move.min(next_gaze);
        if next >= end {
            std::thread::sleep(end.saturating_duration_since(Instant::now()));
            break;
        }
        std::thread::sleep(next.saturating_duration_since(Instant::now()));
        if next_gaze <= next_move {
            let i = changes % n;
            let current = last_accepted[i].clone();
            let results = acknowledgments.clone();
            let band = if *current.lock().unwrap() == 1 { 2 } else { 1 };
            let sent = Instant::now();
            players[i].conn.reducers.human_gaze_then(band, move |_, result| {
                let accepted = matches!(result, Ok(Ok(())));
                let changed = if accepted {
                    let mut old = current.lock().unwrap();
                    std::mem::replace(&mut *old, band) != band
                } else {
                    false
                };
                results.lock().unwrap().push((sent.elapsed().as_secs_f64() * 1000.0, accepted, changed));
            }).expect("gaze dispatch");
            changes += 1;
        } else {
            let i = moves % n;
            let a = (moves / n) as f32 * 1.047 + i as f32 * 2.4;
            let _ = players[i].conn.reducers.human_move(a.cos(), a.sin(), false);
            moves += 1;
        }
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
    println!("{}", json!({"event": "done", "seconds": seconds, "players": out, "gaze_offered": changes, "gaze_acknowledgments": *acknowledgments.lock().unwrap()}));
    for p in &players {
        let _ = p.conn.disconnect();
    }
}
