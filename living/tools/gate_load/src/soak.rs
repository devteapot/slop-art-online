//! `soak`: a handful of players who play an evening the way people do (docs/SOAK.md; driven by
//! living/tools/soak.py). Each player is its own thread with its own identity and WebSocket
//! connection, subscribing what the game client subscribes, and acting only through the player
//! reducers (`join`, `human_move`, `human_act`, `human_say`, `use_skill`, `release_skill`):
//! walking between towns (click-to-move `goto` or a held direction), gathering, eating, building
//! a campfire, talking to residents (which wakes them), waving, giving and trading with each
//! other, sleeping, fighting a wolf or sparring with a friend when told to, dying and arriving
//! again.
//!
//! Connections drop and return: on a `drop` command a player closes its connection and stays
//! away for the given seconds; when the server goes away (a restart, a republish, a relay cut)
//! every player retries every 3 s like the game client. After each reconnect a player reports
//! what its client was given back (`restored`), so the driver can compare it with the
//! authority's rows.
//!
//! Protocol: one request JSON line on stdin (`uri`, `db`, `events`, `players` [{token, name,
//! confirmed}]); prints `{"event":"ready"}` once every player has a living character. Then JSON
//! command lines: `{"cmd":"drop","p":I,"secs":S}`, `{"cmd":"hunt","p":I,"x":X,"y":Y}`,
//! `{"cmd":"duel","p":I,"foe":J}`, `{"cmd":"sleep","p":I}`, `{"cmd":"hold"}`, `{"cmd":"resume"}`,
//! `{"cmd":"snap","tag":T}` (prints `{"event":"snap",…}` with each client's state) and
//! `{"cmd":"stop"}` (prints `{"event":"done",…}`). Every input, reply, death, arrival,
//! disconnect, reconnect and act outcome goes to the events file as a JSON line.

use crate::{unix_us, Log};
use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, Event, SubscriptionHandle as _, Table, TableWithPrimaryKey};
use std::collections::{BTreeMap, HashMap, VecDeque};
use std::io::{BufRead, Write};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

const CHUNK: f32 = 16.0;
const NEAR_CHUNKS: i32 = 3;
const LOT_CHUNKS: i32 = 11;
/// What the game client subscribes once per connection (living/game/src/net.rs).
const BASE: &[&str] = &[
    "world", "land", "settlement", "seen_bodies", "seen_characters", "seen_fighters", "seen_doing", "my_characters", "my_vitals", "my_experience", "my_places",
    "my_inventory", "my_know_how", "my_combat", "my_readiness", "skill_card", "act_card", "weather", "my_skill_uses",
];

fn now_ms() -> u64 {
    (unix_us() / 1000) as u64
}

struct Rng(u64);

impl Rng {
    fn f(&mut self) -> f32 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        (self.0 >> 40) as f32 / (1u64 << 24) as f32
    }
    fn pick<T: Clone>(&mut self, v: &[T]) -> Option<T> {
        if v.is_empty() {
            None
        } else {
            Some(v[((self.f() * v.len() as f32) as usize).min(v.len() - 1)].clone())
        }
    }
}

fn pos(m: &Motion, at_ms: u64) -> (f32, f32) {
    let dt = (at_ms.saturating_sub(m.t_ms) as f32 / 1000.0).min(2.0);
    (m.x + m.vx * dt, m.y + m.vy * dt)
}

fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}

fn chunk_ranges(col: &str, (cx0, cx1): (u32, u32), (cy0, cy1): (u32, u32)) -> String {
    (cy0..=cy1).map(|cy| format!("({col} >= {} AND {col} <= {})", (cy << 16) | cx0, (cy << 16) | cx1)).collect::<Vec<_>>().join(" OR ")
}

/// The windows the game client keeps round where it stands: terrain, resources and structures
/// near, lots far (living/game/src/net.rs `land_window`).
fn windows(x: f32, y: f32, size: u32) -> Vec<String> {
    let n = (size as f32 / CHUNK) as i32;
    let (cx, cy) = (((x / CHUNK).floor() as i32).clamp(0, n - 1), ((y / CHUNK).floor() as i32).clamp(0, n - 1));
    let span = |c: i32, r: i32| ((c - r).max(0) as u32, (c + r).min(n - 1) as u32);
    let (nx, ny) = (span(cx, NEAR_CHUNKS), span(cy, NEAR_CHUNKS));
    vec![
        format!("SELECT * FROM terrain_chunk WHERE {}", chunk_ranges("id", nx, ny)),
        format!("SELECT * FROM resource_node WHERE {}", chunk_ranges("chunk", nx, ny)),
        format!("SELECT * FROM structure WHERE {}", chunk_ranges("chunk", nx, ny)),
        format!("SELECT * FROM lot WHERE {}", chunk_ranges("chunk", span(cx, LOT_CHUNKS), span(cy, LOT_CHUNKS))),
    ]
}

fn status(res: &Result<Result<(), String>, spacetimedb_sdk::__codegen::InternalError>) -> String {
    match res {
        Ok(Ok(())) => "ok".into(),
        Ok(Err(e)) => format!("err:{e}"),
        Err(e) => format!("internal:{e}"),
    }
}

/// What the connection's callbacks share with the player's thread.
#[derive(Default)]
struct St {
    /// Bumped at every new connection; callbacks of an old one are ignored.
    generation: u64,
    connected: bool,
    lost: bool,
    lost_why: String,
    base_applied: bool,
    window_applied: bool,
    sub_errors: Vec<String>,
    me: Option<u32>,
    lives: u32,
    dead_at: Option<Instant>,
    join_sent: Option<Instant>,
    seq: u64,
    pending: u64,
    own_moved_at: i64,
    held_until: Option<Instant>,
    deaths: u32,
    acts_done: u64,
    acts_failed: u64,
    /// The last act that did not work out: when, and the rules' words.
    last_fail: Option<(Instant, String)>,
}

#[derive(Clone, Debug)]
enum Plan {
    Idle(Instant),
    /// Walk to `to`: by held keys (`steer`), or by click-to-move in hops of about 55 m (a click
    /// on a far town is refused, docs/SOAK.md), with a few seconds of held keys after a hop the
    /// authority finds no path for, and held keys for good after four in a row.
    Travel { to: (f32, f32), steer: bool, until: Instant, sent: Option<Instant>, then_talk: bool, hop: Option<(f32, f32)>, fails: u32, keys_until: Option<Instant> },
    Gather { kind: String, at: (f32, f32), until: Instant, sent: bool },
    Hunt { at: (f32, f32), until: Instant },
    Duel { foe: usize, until: Instant },
    Sleep(Instant),
    Away(#[allow(dead_code)] Instant),
    Hold,
}

#[derive(Clone)]
struct Card {
    cost: f32,
    reach: f32,
    hold_ms: u64,
}

struct Shared {
    log: Log,
    uri: String,
    db: String,
    stop: AtomicBool,
    hold: AtomicBool,
    /// Player index → its living character, as each client knows it.
    chars: Mutex<HashMap<usize, u32>>,
    /// An offer made: target character → (offerer character, when).
    offers: Mutex<HashMap<u32, (u32, Instant)>>,
    cmds: Vec<Mutex<VecDeque<Value>>>,
    snap_gen: AtomicU64,
    snaps: Mutex<BTreeMap<usize, Value>>,
    out: Mutex<std::io::Stdout>,
}

impl Shared {
    fn print(&self, v: Value) {
        let mut o = self.out.lock().unwrap();
        let _ = writeln!(o, "{v}");
        let _ = o.flush();
    }
}

struct Player {
    idx: usize,
    name: String,
    token: String,
    confirmed: bool,
    sh: Arc<Shared>,
    st: Arc<Mutex<St>>,
    conn: Option<DbConnection>,
    window: Option<(SubscriptionHandle, (f32, f32))>,
    plan: Plan,
    rng: Rng,
    next_try: Instant,
    away_since: Option<Instant>,
    away_planned: bool,
    lost_at: Option<Instant>,
    last_dir: Option<(f32, f32, bool)>,
    last_move: Option<Instant>,
    cards: HashMap<String, Card>,
    snap_seen: u64,
    reconnects: u32,
    down_ms: Vec<u64>,
}

impl Player {
    fn log(&self, mut v: Value) {
        v["p"] = self.idx.into();
        if v.get("ts").is_none() {
            v["ts"] = unix_us().into();
        }
        self.sh.log.put(v);
    }

    fn me(&self) -> Option<u32> {
        self.st.lock().unwrap().me
    }

    fn live(&self) -> bool {
        let s = self.st.lock().unwrap();
        self.conn.is_some() && s.connected && !s.lost && s.base_applied
    }

    // ---- connection ----------------------------------------------------------------------

    fn connect(&mut self) -> bool {
        let generation = {
            let mut s = self.st.lock().unwrap();
            s.generation += 1;
            s.connected = false;
            s.lost = false;
            s.base_applied = false;
            s.window_applied = false;
            s.sub_errors.clear();
            s.generation
        };
        let t0 = unix_us();
        let (st1, st2, st3) = (self.st.clone(), self.st.clone(), self.st.clone());
        let (lg2, lg3, idx) = (self.sh.log.clone(), self.sh.log.clone(), self.idx);
        let built = DbConnection::builder()
            .with_uri(self.sh.uri.clone())
            .with_database_name(self.sh.db.clone())
            .with_token(Some(self.token.clone()))
            .with_confirmed_reads(self.confirmed)
            .on_connect(move |_, _, _| {
                let mut s = st1.lock().unwrap();
                if s.generation == generation {
                    s.connected = true;
                }
            })
            .on_connect_error(move |_, e| {
                let mut s = st2.lock().unwrap();
                if s.generation == generation {
                    s.lost = true;
                    s.lost_why = format!("connect error: {e}");
                }
                lg2.put(json!({"k": "connect_error", "p": idx, "ts": unix_us(), "e": e.to_string()}));
            })
            .on_disconnect(move |_, e| {
                let mut s = st3.lock().unwrap();
                if s.generation == generation {
                    s.lost = true;
                    s.connected = false;
                    s.lost_why = e.as_ref().map_or("closed".into(), |e| e.to_string());
                }
                lg3.put(json!({"k": "disconnected", "p": idx, "ts": unix_us(), "gen": generation, "e": e.map(|e| e.to_string())}));
            })
            .build();
        let conn = match built {
            Ok(c) => c,
            Err(e) => {
                self.log(json!({"k": "connect_failed", "e": e.to_string(), "gen": generation}));
                return false;
            }
        };
        conn.run_threaded();
        let t = Instant::now();
        loop {
            let s = self.st.lock().unwrap();
            if s.connected {
                break;
            }
            if s.lost || t.elapsed() > Duration::from_secs(20) {
                drop(s);
                let _ = conn.disconnect();
                self.log(json!({"k": "connect_failed", "e": "no identity", "gen": generation}));
                return false;
            }
            drop(s);
            std::thread::sleep(Duration::from_millis(10));
        }
        self.hook(&conn, generation);
        let (st, st2) = (self.st.clone(), self.st.clone());
        conn.subscription_builder()
            .on_applied(move |_| {
                let mut s = st.lock().unwrap();
                if s.generation == generation {
                    s.base_applied = true;
                }
            })
            .on_error(move |_, e| st2.lock().unwrap().sub_errors.push(e.to_string()))
            .subscribe(BASE.iter().map(|t| format!("SELECT * FROM {t}")).collect::<Vec<_>>());
        let t = Instant::now();
        loop {
            let s = self.st.lock().unwrap();
            if s.base_applied {
                break;
            }
            if s.lost || !s.sub_errors.is_empty() || t.elapsed() > Duration::from_secs(60) {
                let why = format!("{} {:?}", s.lost_why, s.sub_errors);
                drop(s);
                let _ = conn.disconnect();
                self.log(json!({"k": "connect_failed", "e": format!("base subscription: {why}"), "gen": generation}));
                return false;
            }
            drop(s);
            std::thread::sleep(Duration::from_millis(10));
        }
        let applied_us = unix_us();
        // My character as the server gives it back: alive and mine, or dead while I was away.
        let mine: Vec<Character> = conn.db.my_characters().iter().collect();
        let alive = mine.iter().find(|c| c.alive && !c.ai).map(|c| c.id);
        let ai_alive = mine.iter().find(|c| c.alive && c.ai).map(|c| c.id);
        let before = self.me();
        {
            let mut s = self.st.lock().unwrap();
            if alive.is_none() && s.me.is_some() {
                s.me = None;
                s.dead_at = Some(Instant::now());
            } else if alive.is_some() && s.me != alive {
                if s.me.is_none() && before.is_none() && s.lives == 0 {
                    s.lives = 1;
                }
                s.me = alive;
            }
        }
        if let Some(me) = alive {
            self.sh.chars.lock().unwrap().insert(self.idx, me);
        }
        let inv: BTreeMap<String, u32> = alive.map_or_else(BTreeMap::new, |me| {
            conn.db.my_inventory().iter().filter(|i| i.owner == me as u64).fold(BTreeMap::new(), |mut m, i| {
                *m.entry(i.item.clone()).or_default() += i.qty;
                m
            })
        });
        let vit = alive.and_then(|me| conn.db.my_vitals().id().find(&me));
        let down_ms = self.lost_at.or(self.away_since).map(|t| t.elapsed().as_millis() as u64);
        let body = alive.and_then(|me| conn.db.seen_bodies().id().find(&me));
        let restored = json!({"event": "restored", "p": self.idx, "gen": generation, "before": before, "me": alive, "ai_alive": ai_alive,
                              "characters": mine.iter().map(|c| json!({"id": c.id, "alive": c.alive, "ai": c.ai, "cause": c.cause})).collect::<Vec<_>>(),
                              "inv": inv, "hp": vit.as_ref().map(|v| v.hp), "hunger": vit.as_ref().map(|v| v.hunger), "at": body.map(|b| [b.x, b.y]),
                              "connect_ms": (applied_us - t0) as f64 / 1000.0, "down_ms": down_ms, "planned": self.away_planned, "ts": applied_us,
                              "seen_bodies": conn.db.seen_bodies().count(), "seen_characters": conn.db.seen_characters().count(), "experience": conn.db.my_experience().count()});
        if self.reconnects > 0 || generation > 1 {
            self.sh.log.put(restored.clone());
            self.sh.print(restored);
        }
        if let Some(d) = down_ms {
            self.down_ms.push(d);
        }
        self.reconnects += 1;
        self.cards = conn.db.skill_card().iter().map(|c| (c.skill.clone(), Card { cost: c.cost, reach: c.reach, hold_ms: (c.windup_ms + c.recover_ms) as u64 })).collect();
        self.conn = Some(conn);
        self.window = None;
        self.lost_at = None;
        self.away_since = None;
        self.away_planned = false;
        self.last_dir = None;
        if matches!(self.plan, Plan::Away(_)) {
            self.plan = Plan::Idle(Instant::now() + Duration::from_secs(2));
        }
        true
    }

    fn hook(&self, conn: &DbConnection, generation: u64) {
        let (st, lg, idx) = (self.st.clone(), self.sh.log.clone(), self.idx);
        conn.db.my_characters().on_insert(move |ctx, c| {
            if matches!(ctx.event, Event::SubscribeApplied) {
                return;
            }
            let mut s = st.lock().unwrap();
            if s.generation == generation && c.alive && !c.ai && s.me != Some(c.id) {
                s.me = Some(c.id);
                s.lives += 1;
                s.join_sent = None;
                s.dead_at = None;
                lg.put(json!({"k": "alive", "p": idx, "id": c.id, "name": c.name, "ts": unix_us()}));
            }
        });
        let (st, lg, idx) = (self.st.clone(), self.sh.log.clone(), self.idx);
        conn.db.my_characters().on_update(move |_, old, c| {
            let mut s = st.lock().unwrap();
            if s.generation != generation {
                return;
            }
            if old.alive && !c.alive && s.me == Some(c.id) {
                s.me = None;
                s.deaths += 1;
                s.dead_at = Some(Instant::now());
                lg.put(json!({"k": "death", "p": idx, "id": c.id, "cause": c.cause, "ts": unix_us(), "died_ms": c.died_ms}));
            } else if c.alive && !c.ai && s.me != Some(c.id) {
                s.me = Some(c.id);
                s.lives += 1;
                s.join_sent = None;
                s.dead_at = None;
                lg.put(json!({"k": "alive", "p": idx, "id": c.id, "name": c.name, "ts": unix_us()}));
            }
        });
        let st = self.st.clone();
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
        // The outcome of every act, as it reaches me (accepted and done, or failed with the
        // rules' reason).
        let (st, lg, idx) = (self.st.clone(), self.sh.log.clone(), self.idx);
        conn.db.my_experience().on_insert(move |ctx, e| {
            if matches!(ctx.event, Event::SubscribeApplied) || e.kind != "act" {
                return;
            }
            let ok = e.text.starts_with("You did what you had decided");
            {
                let mut s = st.lock().unwrap();
                if ok {
                    s.acts_done += 1;
                } else {
                    s.acts_failed += 1;
                    s.last_fail = Some((Instant::now(), e.text.clone()));
                }
            }
            let mut text = e.text.clone();
            text.truncate(200);
            lg.put(json!({"k": "act_outcome", "p": idx, "ok": ok, "text": text, "at_ms": e.at_ms, "ts": unix_us()}));
        });
    }

    fn drop_connection(&mut self, why: &str) {
        if let Some(c) = self.conn.take() {
            let _ = c.disconnect();
        }
        self.window = None;
        self.log(json!({"k": "dropped", "why": why}));
    }

    /// Keep the near and lot windows round where I stand (re-centred when I move 3 chunks).
    fn keep_window(&mut self) {
        let Some(me) = self.me() else { return };
        let Some(conn) = &self.conn else { return };
        let Some(b) = conn.db.seen_bodies().id().find(&me) else { return };
        let here = (b.x, b.y);
        if self.window.as_ref().is_some_and(|(_, c)| dist(*c, here) < 3.0 * CHUNK) {
            return;
        }
        let size = conn.db.land().iter().next().map_or(2048, |l| l.size);
        let st = self.st.clone();
        let handle = conn.subscription_builder().on_applied(move |_| st.lock().unwrap().window_applied = true).on_error(|_, _| {}).subscribe(windows(here.0, here.1, size));
        if let Some((old, _)) = self.window.take() {
            let _ = old.unsubscribe();
        }
        self.window = Some((handle, here));
    }

    // ---- inputs, each timed --------------------------------------------------------------

    fn next_seq(&self) -> u64 {
        let mut s = self.st.lock().unwrap();
        s.seq += 1;
        s.pending += 1;
        s.seq
    }

    fn send_move(&mut self, dx: f32, dy: f32, run: bool) {
        let Some(conn) = &self.conn else { return };
        let n = self.next_seq();
        let (st, lg, idx) = (self.st.clone(), self.sh.log.clone(), self.idx);
        let t0 = unix_us();
        let r = conn.reducers.human_move_then(dx, dy, run, move |ctx, res| {
            let t = unix_us();
            let srv = ctx.event.timestamp.to_micros_since_unix_epoch();
            let moved = {
                let mut s = st.lock().unwrap();
                s.pending = s.pending.saturating_sub(1);
                s.own_moved_at == srv
            };
            lg.put(json!({"k": "res", "p": idx, "n": n, "ts": t, "srv": srv, "st": status(&res), "moved": moved}));
        });
        self.log(json!({"k": "in", "n": n, "r": "move", "ts": t0, "dx": dx, "dy": dy, "run": run, "sent": r.is_ok(), "c": self.confirmed}));
        self.last_dir = Some((dx, dy, run));
        self.last_move = Some(Instant::now());
    }

    fn send_act(&mut self, what: &str, node: Value) {
        let Some(conn) = &self.conn else { return };
        let n = self.next_seq();
        let (st, lg, idx) = (self.st.clone(), self.sh.log.clone(), self.idx);
        let t0 = unix_us();
        let r = conn.reducers.human_act_then(node.to_string(), move |ctx, res| {
            { let mut s = st.lock().unwrap(); s.pending = s.pending.saturating_sub(1); }
            lg.put(json!({"k": "res", "p": idx, "n": n, "ts": unix_us(), "srv": ctx.event.timestamp.to_micros_since_unix_epoch(), "st": status(&res)}));
        });
        self.log(json!({"k": "in", "n": n, "r": "act", "act": what, "node": node, "ts": t0, "sent": r.is_ok(), "c": self.confirmed}));
        self.last_dir = None;
    }

    fn send_say(&mut self, text: &str, to: u32) {
        let Some(conn) = &self.conn else { return };
        let n = self.next_seq();
        let (st, lg, idx) = (self.st.clone(), self.sh.log.clone(), self.idx);
        let t0 = unix_us();
        let r = conn.reducers.human_say_then(text.to_string(), to, move |ctx, res| {
            { let mut s = st.lock().unwrap(); s.pending = s.pending.saturating_sub(1); }
            lg.put(json!({"k": "res", "p": idx, "n": n, "ts": unix_us(), "srv": ctx.event.timestamp.to_micros_since_unix_epoch(), "st": status(&res)}));
        });
        self.log(json!({"k": "in", "n": n, "r": "say", "to": to, "ts": t0, "sent": r.is_ok(), "c": self.confirmed}));
    }

    fn send_skill(&mut self, skill: &str, target: u32, x: f32, y: f32) {
        let Some(conn) = &self.conn else { return };
        let hold = self.cards.get(skill).map_or(600, |c| c.hold_ms);
        self.st.lock().unwrap().held_until = Some(Instant::now() + Duration::from_millis(hold));
        let n = self.next_seq();
        let (st, lg, idx) = (self.st.clone(), self.sh.log.clone(), self.idx);
        let t0 = unix_us();
        let r = conn.reducers.use_skill_then(skill.to_string(), target, x, y, move |ctx, res| {
            { let mut s = st.lock().unwrap(); s.pending = s.pending.saturating_sub(1); }
            lg.put(json!({"k": "res", "p": idx, "n": n, "ts": unix_us(), "srv": ctx.event.timestamp.to_micros_since_unix_epoch(), "st": status(&res)}));
        });
        self.log(json!({"k": "in", "n": n, "r": "skill", "skill": skill, "target": target, "ts": t0, "sent": r.is_ok(), "c": self.confirmed}));
    }

    fn send_join(&mut self) {
        let Some(conn) = &self.conn else { return };
        let lives = self.st.lock().unwrap().lives;
        let mut name = if lives == 0 { self.name.clone() } else { format!("{}{}", self.name, lives) };
        name.truncate(24);
        let n = self.next_seq();
        self.st.lock().unwrap().join_sent = Some(Instant::now());
        let (st, lg, idx) = (self.st.clone(), self.sh.log.clone(), self.idx);
        let t0 = unix_us();
        let r = conn.reducers.join_then(name.clone(), move |ctx, res| {
            { let mut s = st.lock().unwrap(); s.pending = s.pending.saturating_sub(1); }
            lg.put(json!({"k": "res", "p": idx, "n": n, "ts": unix_us(), "srv": ctx.event.timestamp.to_micros_since_unix_epoch(), "st": status(&res)}));
        });
        self.log(json!({"k": "in", "n": n, "r": "join", "name": name, "ts": t0, "sent": r.is_ok(), "c": self.confirmed}));
    }

    /// Hold a direction toward `goal` as a person holding a key does: a new input only when the
    /// direction turns by more than 30°, the gait changes, or every 2 s.
    fn steer(&mut self, here: (f32, f32), goal: (f32, f32), stop_within: f32, run: bool) {
        let d = dist(here, goal);
        let want = if d > stop_within { ((goal.0 - here.0) / d, (goal.1 - here.1) / d, run) } else { (0.0, 0.0, false) };
        let changed = match self.last_dir {
            None => want.0 != 0.0 || want.1 != 0.0,
            Some((lx, ly, lr)) => {
                let stop_change = (lx == 0.0 && ly == 0.0) != (want.0 == 0.0 && want.1 == 0.0);
                let angle = (lx * want.0 + ly * want.1).clamp(-1.0, 1.0).acos();
                stop_change || lr != want.2 || angle > 0.52
            }
        };
        let since = self.last_move.map(|t| t.elapsed());
        let refresh = since.is_none_or(|s| s > Duration::from_secs(2)) && (want.0 != 0.0 || want.1 != 0.0);
        if (changed || refresh) && since.is_none_or(|s| s > Duration::from_millis(200)) {
            self.send_move(want.0, want.1, want.2);
        }
    }

    fn stand(&mut self) {
        if self.last_dir.is_some_and(|(x, y, _)| x != 0.0 || y != 0.0) {
            self.send_move(0.0, 0.0, false);
        }
    }

    // ---- what I see ----------------------------------------------------------------------

    fn here(&self) -> Option<(f32, f32)> {
        let me = self.me()?;
        let b = self.conn.as_ref()?.db.seen_bodies().id().find(&me)?;
        Some(pos(&b, now_ms()))
    }

    fn inv(&self, item: &str) -> u32 {
        let (Some(me), Some(conn)) = (self.me(), &self.conn) else { return 0 };
        conn.db.my_inventory().iter().filter(|i| i.owner == me as u64 && i.item == item).map(|i| i.qty).sum()
    }

    /// People in view, nearest first: (id, where, distance, a fellow player).
    fn people(&self, here: (f32, f32)) -> Vec<(u32, (f32, f32), f32, bool)> {
        let (Some(me), Some(conn)) = (self.me(), &self.conn) else { return Vec::new() };
        let players: Vec<u32> = self.sh.chars.lock().unwrap().values().copied().collect();
        let now = now_ms();
        let mut out: Vec<_> = conn
            .db
            .seen_characters()
            .iter()
            .filter(|c| c.id != me && c.kind == "person" && c.stage >= 2)
            .filter_map(|c| {
                let b = conn.db.seen_bodies().id().find(&c.id)?;
                let at = pos(&b, now);
                Some((c.id, at, dist(here, at), players.contains(&c.id)))
            })
            .collect();
        out.sort_by(|a, b| a.2.total_cmp(&b.2));
        out
    }

    fn creature(&self, kind: &str, here: (f32, f32)) -> Option<(u32, (f32, f32), f32)> {
        let conn = self.conn.as_ref()?;
        let now = now_ms();
        conn.db
            .seen_characters()
            .iter()
            .filter(|c| c.kind == kind && c.hp > 0.0)
            .filter_map(|c| {
                let b = conn.db.seen_bodies().id().find(&c.id)?;
                let at = pos(&b, now);
                Some((c.id, at, dist(here, at)))
            })
            .min_by(|a, b| a.2.total_cmp(&b.2))
    }

    // ---- one decision --------------------------------------------------------------------

    fn step(&mut self) {
        // Rejoin after death, as a person at the death screen presses "arrive again".
        let (me, dead_at, join_sent) = {
            let s = self.st.lock().unwrap();
            (s.me, s.dead_at, s.join_sent)
        };
        let Some(me) = me else {
            self.sh.chars.lock().unwrap().remove(&self.idx);
            let wait = 6.0 + (self.idx % 4) as f32 * 3.0;
            if dead_at.is_none_or(|d| d.elapsed().as_secs_f32() > wait) && join_sent.is_none_or(|j| j.elapsed() > Duration::from_secs(15)) {
                self.send_join();
            }
            self.plan = Plan::Idle(Instant::now() + Duration::from_secs(1));
            return;
        };
        self.sh.chars.lock().unwrap().insert(self.idx, me);
        self.keep_window();
        let Some(here) = self.here() else { return };
        let now = Instant::now();
        // An offer made to me by a friend: accept it.
        let offer = self.sh.offers.lock().unwrap().remove(&me);
        if let Some((from, at)) = offer {
            if at.elapsed() < Duration::from_secs(30) {
                self.send_act("accept", json!({"do": "accept", "target": {"id": from}}));
                self.plan = Plan::Idle(now + Duration::from_secs(3));
                return;
            }
        }
        match self.plan.clone() {
            Plan::Hold | Plan::Away(_) => {}
            Plan::Idle(until) => {
                if now >= until {
                    self.choose(me, here);
                }
            }
            Plan::Sleep(until) => {
                if now >= until {
                    // Any move ends sleep: walk a few steps.
                    let a = self.rng.f() * 6.283;
                    self.send_move(a.cos(), a.sin(), false);
                    self.plan = Plan::Idle(now + Duration::from_secs(3));
                }
            }
            Plan::Travel { to, mut steer, until, mut sent, then_talk, mut hop, mut fails, mut keys_until } => {
                let d = dist(here, to);
                if d < 8.0 || now >= until {
                    self.stand();
                    self.log(json!({"k": "arrived", "d": d, "to": [to.0, to.1], "timeout": now >= until, "fails": fails}));
                    self.plan = Plan::Idle(now + Duration::from_millis(500));
                    if then_talk {
                        self.talk(here);
                    }
                    return;
                }
                if !steer {
                    // Did the last click find no path?
                    let failed = sent.is_some_and(|t| self.st.lock().unwrap().last_fail.as_ref().is_some_and(|(at, text)| *at >= t && text.contains("goto")));
                    if failed {
                        fails += 1;
                        sent = None;
                        hop = None;
                        self.log(json!({"k": "hop_failed", "fails": fails, "d": d}));
                        if fails >= 4 {
                            steer = true;
                        } else {
                            keys_until = Some(now + Duration::from_secs(12));
                        }
                    }
                }
                if steer || keys_until.is_some_and(|k| now < k) {
                    self.steer(here, to, 6.0, d > 40.0);
                } else {
                    let reached = hop.is_some_and(|h| dist(here, h) < 5.0);
                    if sent.is_none() || reached || sent.is_some_and(|s| s.elapsed() > Duration::from_secs(60)) {
                        let step = d.min(55.0);
                        let h = (here.0 + (to.0 - here.0) / d * step, here.1 + (to.1 - here.1) / d * step);
                        self.send_act("goto", json!({"do": "goto", "target": {"at": [h.0, h.1]}}));
                        self.log(json!({"k": "hop", "d": step, "left": d}));
                        hop = Some(h);
                        sent = Some(now);
                        fails = if reached { 0 } else { fails };
                    }
                }
                self.plan = Plan::Travel { to, steer, until, sent, then_talk, hop, fails, keys_until };
            }
            Plan::Gather { kind, at, until, sent } => {
                let d = dist(here, at);
                if now >= until {
                    self.plan = Plan::Idle(now);
                } else if d <= 1.8 && !sent {
                    self.stand();
                    self.send_act("gather", json!({"do": "gather", "target": {"nearest": kind}}));
                    self.plan = Plan::Gather { kind, at, until: now + Duration::from_secs(7), sent: true };
                } else if !sent {
                    self.steer(here, at, 1.2, false);
                }
            }
            Plan::Hunt { at, until } => {
                if now >= until {
                    self.stand();
                    self.plan = Plan::Idle(now);
                    return;
                }
                match self.creature("wolf", here) {
                    Some((id, wat, d)) if d < 25.0 => self.fight(me, here, id, wat, d),
                    _ => {
                        if dist(here, at) > 6.0 {
                            self.steer(here, at, 5.0, true);
                        } else {
                            self.stand();
                        }
                    }
                }
            }
            Plan::Duel { foe, until } => {
                let foe_id = self.sh.chars.lock().unwrap().get(&foe).copied();
                let target = foe_id.and_then(|f| self.people(here).into_iter().find(|p| p.0 == f));
                match target {
                    Some((id, at, d, _)) if now < until => self.fight(me, here, id, at, d),
                    _ => {
                        self.stand();
                        self.log(json!({"k": "duel_over", "foe": foe, "seen": target.is_some()}));
                        self.plan = Plan::Idle(now + Duration::from_secs(2));
                    }
                }
            }
        }
    }

    fn fight(&mut self, me: u32, here: (f32, f32), target: u32, at: (f32, f32), d: f32) {
        let Some(conn) = &self.conn else { return };
        let now = now_ms();
        let vit = conn.db.my_vitals().id().find(&me);
        let (hp, max_hp, energy) = vit.map_or((1.0, 1.0, 100.0), |v| (v.hp, v.max_hp.max(1.0), v.energy));
        let ready = conn.db.my_readiness().iter().find(|r| r.id == me);
        let held = self.st.lock().unwrap().held_until.is_some_and(|h| Instant::now() < h);
        let busy = held || ready.as_ref().is_some_and(|r| r.busy_until > now);
        let cards = self.cards.clone();
        let ok = |skill: &str| -> bool {
            let Some(card) = cards.get(skill) else { return false };
            let cooled = ready.as_ref().is_none_or(|r| r.ready.iter().all(|x| x.skill != skill || x.at_ms <= now));
            cooled && !busy && energy >= card.cost
        };
        let reach = cards.get("strike").map_or(1.6, |c| c.reach);
        let arrows = self.inv("arrow");
        let r = self.rng.f();
        if busy {
            return;
        }
        if hp / max_hp < 0.4 && ok("heal") {
            self.send_skill("heal", 0, here.0, here.1);
        } else if d <= reach + 0.4 && ok("strike") {
            self.send_skill("strike", target, at.0, at.1);
        } else if d > 4.0 && d <= 15.0 && r < 0.3 && ok("firebolt") {
            self.send_skill("firebolt", target, at.0, at.1);
        } else if d > 2.5 && d <= 14.0 && arrows > 0 && r < 0.6 && ok("bowshot") {
            self.send_skill("bowshot", target, at.0, at.1);
        } else {
            self.steer(here, at, reach * 0.8, d > 6.0);
        }
    }

    fn talk(&mut self, here: (f32, f32)) {
        let lines = ["Hello there! What's your name?", "Good evening. Is there somewhere to sleep around here?", "Do you know where the wolves roam?", "Nice weather today.", "What do you do here?"];
        let near = self.people(here).into_iter().find(|p| !p.3 && p.2 < 10.0);
        if let Some((id, _, d, _)) = near {
            let line = self.rng.pick(&lines).unwrap();
            self.send_say(line, id);
            self.log(json!({"k": "talk", "to": id, "d": d}));
        }
    }

    /// Pick what to do next, as a person would: eat when hungry, sleep when tired, otherwise
    /// walk to another town, gather, talk to a resident, greet, give, trade, build a fire.
    fn choose(&mut self, me: u32, here: (f32, f32)) {
        let now = Instant::now();
        let Some(conn) = &self.conn else { return };
        let vit = conn.db.my_vitals().id().find(&me);
        let (hunger, energy) = vit.map_or((0.0, 100.0), |v| (v.hunger, v.energy));
        let food: Vec<String> = ["berries", "fish", "cooked_fish", "meat"].iter().filter(|f| self.inv(f) > 0).map(|s| s.to_string()).collect();
        if hunger > 45.0 && !food.is_empty() {
            let item = food[0].clone();
            self.stand();
            self.send_act("eat", json!({"do": "eat", "item": item}));
            self.plan = Plan::Idle(now + Duration::from_secs(3));
            return;
        }
        if energy < 30.0 {
            self.stand();
            self.send_act("sleep", json!({"do": "sleep"}));
            self.plan = Plan::Sleep(now + Duration::from_secs(60 + (self.rng.f() * 90.0) as u64));
            return;
        }
        let r = self.rng.f();
        let people = self.people(here);
        let resident = people.iter().find(|p| !p.3).cloned();
        let friend = people.iter().find(|p| p.3).cloned();
        if r < 0.20 {
            // Walk to another town: a lot door in a settlement other than the nearest.
            let towns: Vec<(f32, f32)> = conn.db.settlement().iter().map(|s| (s.x, s.y)).filter(|t| dist(*t, here) > 60.0).collect();
            if let Some(to) = self.rng.pick(&towns) {
                let steer = self.idx % 3 == 1;
                self.log(json!({"k": "travel", "to": [to.0, to.1], "d": dist(here, to), "steer": steer}));
                let budget = (dist(here, to) / 0.8).clamp(60.0, 1800.0);
                self.plan = Plan::Travel { to, steer, until: now + Duration::from_secs_f32(budget), sent: None, then_talk: self.rng.f() < 0.5, hop: None, fails: 0, keys_until: None };
                return;
            }
        }
        if r < 0.45 {
            let want = if self.inv("wood") < 3 && self.rng.f() < 0.5 { vec!["tree"] } else { vec!["berry_bush", "reeds", "boulder", "tree"] };
            let node = conn
                .db
                .resource_node()
                .iter()
                .filter(|n| n.amount >= 1.0 && want.contains(&n.kind.as_str()))
                .map(|n| (n.kind.clone(), (n.x, n.y), dist(here, (n.x, n.y))))
                .filter(|n| n.2 < 45.0)
                .min_by(|a, b| a.2.total_cmp(&b.2));
            if let Some((kind, at, _)) = node {
                self.plan = Plan::Gather { kind, at, until: now + Duration::from_secs(40), sent: false };
                return;
            }
        }
        if r < 0.60 {
            match resident {
                Some((_, _, d, _)) if d < 10.0 => {
                    self.stand();
                    self.talk(here);
                    self.plan = Plan::Idle(now + Duration::from_secs(4));
                }
                Some((_, at, d, _)) if d < 60.0 => {
                    self.plan = Plan::Travel { to: at, steer: true, until: now + Duration::from_secs(60), sent: None, then_talk: true, hop: None, fails: 0, keys_until: None };
                }
                _ => self.plan = Plan::Idle(now + Duration::from_secs(2)),
            }
            return;
        }
        if r < 0.66 {
            if let Some((id, _, d, _)) = resident.filter(|p| p.2 < 8.0) {
                self.stand();
                self.send_act("wave", json!({"do": "wave", "target": {"id": id}}));
                self.log(json!({"k": "wave", "to": id, "d": d}));
                self.plan = Plan::Idle(now + Duration::from_secs(3));
                return;
            }
        }
        if r < 0.72 {
            let whom = if self.rng.f() < 0.5 { friend.clone() } else { resident.clone() };
            if let Some((id, _, _, _)) = whom.filter(|p| p.2 < 2.5) {
                if let Some(item) = ["berries", "wood", "fiber", "stone"].iter().find(|i| self.inv(i) > 0) {
                    self.stand();
                    self.send_act("give", json!({"do": "give", "target": {"id": id}, "item": item, "qty": 1}));
                    self.plan = Plan::Idle(now + Duration::from_secs(3));
                    return;
                }
            }
        }
        if r < 0.78 {
            if let Some((id, at, d, _)) = friend.clone() {
                if d < 2.5 {
                    if let Some(item) = ["berries", "wood", "fiber", "stone"].iter().find(|i| self.inv(i) > 0) {
                        let want = if *item == "berries" { "arrow" } else { "berries" };
                        self.stand();
                        self.send_act("offer", json!({"do": "offer", "target": {"id": id}, "item": item, "qty": 1, "want": want, "want_qty": 1}));
                        self.sh.offers.lock().unwrap().insert(id, (me, now + Duration::from_secs(2)));
                        self.plan = Plan::Idle(now + Duration::from_secs(4));
                        return;
                    }
                } else if d < 40.0 {
                    self.plan = Plan::Travel { to: at, steer: true, until: now + Duration::from_secs(40), sent: None, then_talk: false, hop: None, fails: 0, keys_until: None };
                    return;
                }
            }
        }
        if r < 0.82 && self.inv("wood") >= 2 {
            self.stand();
            self.send_act("build", json!({"do": "build", "item": "campfire"}));
            self.plan = Plan::Idle(now + Duration::from_secs(8));
            return;
        }
        if r < 0.83 {
            // A thing a newcomer does not know how to make yet: the rules refuse it.
            self.send_act("craft", json!({"do": "craft", "item": "spear"}));
            self.plan = Plan::Idle(now + Duration::from_secs(3));
            return;
        }
        if r < 0.86 && energy < 70.0 {
            self.stand();
            self.send_act("sleep", json!({"do": "sleep"}));
            self.plan = Plan::Sleep(now + Duration::from_secs(45 + (self.rng.f() * 60.0) as u64));
            return;
        }
        // Stroll a little, or stand and look round.
        if self.rng.f() < 0.6 {
            let a = self.rng.f() * 6.283;
            let to = (here.0 + 15.0 * a.cos(), here.1 + 15.0 * a.sin());
            self.plan = Plan::Travel { to, steer: true, until: now + Duration::from_secs(20), sent: None, then_talk: false, hop: None, fails: 0, keys_until: None };
        } else {
            self.stand();
            self.plan = Plan::Idle(now + Duration::from_secs(2 + (self.rng.f() * 6.0) as u64));
        }
    }

    fn command(&mut self, c: Value) {
        let now = Instant::now();
        match c["cmd"].as_str().unwrap_or("") {
            "drop" => {
                let secs = c["secs"].as_f64().unwrap_or(10.0);
                self.drop_connection("planned");
                self.away_since = Some(now);
                self.away_planned = true;
                self.plan = Plan::Away(now + Duration::from_secs_f64(secs));
                self.next_try = now + Duration::from_secs_f64(secs);
                self.log(json!({"k": "away", "secs": secs}));
            }
            "hunt" => {
                let at = (c["x"].as_f64().unwrap_or(0.0) as f32, c["y"].as_f64().unwrap_or(0.0) as f32);
                self.log(json!({"k": "hunt", "at": [at.0, at.1]}));
                self.plan = Plan::Hunt { at, until: now + Duration::from_secs(c["secs"].as_u64().unwrap_or(240)) };
            }
            "duel" => {
                let foe = c["foe"].as_u64().unwrap_or(0) as usize;
                self.log(json!({"k": "duel", "foe": foe}));
                self.plan = Plan::Duel { foe, until: now + Duration::from_secs(c["secs"].as_u64().unwrap_or(240)) };
            }
            "goto" => {
                let to = (c["x"].as_f64().unwrap_or(0.0) as f32, c["y"].as_f64().unwrap_or(0.0) as f32);
                self.plan = Plan::Travel { to, steer: false, until: now + Duration::from_secs(c["secs"].as_u64().unwrap_or(600)), sent: None, then_talk: false, hop: None, fails: 0, keys_until: None };
            }
            "sleep" => {
                self.stand();
                self.send_act("sleep", json!({"do": "sleep"}));
                self.plan = Plan::Sleep(now + Duration::from_secs(c["secs"].as_u64().unwrap_or(90)));
            }
            _ => {}
        }
    }

    fn snapshot(&self) -> Value {
        let s = self.st.lock().unwrap();
        let (me, connected) = (s.me, s.connected && !s.lost);
        let (lives, deaths, seq, pending, ok, failed) = (s.lives, s.deaths, s.seq, s.pending, s.acts_done, s.acts_failed);
        drop(s);
        let conn = self.conn.as_ref();
        let inv: BTreeMap<String, u32> = match (me, conn) {
            (Some(me), Some(c)) => c.db.my_inventory().iter().filter(|i| i.owner == me as u64).fold(BTreeMap::new(), |mut m, i| {
                *m.entry(i.item.clone()).or_default() += i.qty;
                m
            }),
            _ => BTreeMap::new(),
        };
        let vit = me.zip(conn).and_then(|(me, c)| c.db.my_vitals().id().find(&me));
        json!({"p": self.idx, "me": me, "connected": connected, "lives": lives, "deaths": deaths, "calls": seq, "unanswered": pending,
               "acts_done": ok, "acts_failed": failed, "inv": inv, "hp": vit.as_ref().map(|v| v.hp), "hunger": vit.as_ref().map(|v| v.hunger),
               "energy": vit.as_ref().map(|v| v.energy), "plan": format!("{:?}", self.plan).chars().take(60).collect::<String>(),
               "reconnects": self.reconnects, "down_ms": self.down_ms,
               "held": conn.map(|c| json!({"bodies": c.db.seen_bodies().count(), "characters": c.db.seen_characters().count(), "experience": c.db.my_experience().count(),
                                           "inventory": c.db.my_inventory().count(), "resources": c.db.resource_node().count(), "lots": c.db.lot().count()}))})
    }

    fn run(mut self) {
        let mut last_hold = false;
        while !self.sh.stop.load(Ordering::SeqCst) {
            let now = Instant::now();
            // Snapshots answer even while away (state: offline).
            let g = self.sh.snap_gen.load(Ordering::SeqCst);
            if g != self.snap_seen {
                self.snap_seen = g;
                let v = self.snapshot();
                self.sh.snaps.lock().unwrap().insert(self.idx, v);
            }
            let cmd = self.sh.cmds[self.idx].lock().unwrap().pop_front();
            if let Some(c) = cmd {
                self.command(c);
            }
            // Connection: lost → retry every 3 s (the game client's rule), unless away on purpose.
            let lost = self.conn.is_some() && self.st.lock().unwrap().lost;
            if lost {
                let why = self.st.lock().unwrap().lost_why.clone();
                self.drop_connection(&format!("lost: {why}"));
                self.lost_at = Some(now);
                self.next_try = now + Duration::from_secs(3);
            }
            if self.conn.is_none() {
                if now >= self.next_try {
                    if !self.connect() {
                        self.lost_at.get_or_insert(now);
                        self.next_try = Instant::now() + Duration::from_secs(3);
                    }
                }
                std::thread::sleep(Duration::from_millis(50));
                continue;
            }
            // The windows round where I stand, as the game client keeps them, held or not.
            if self.live() {
                self.keep_window();
            }
            let hold = self.sh.hold.load(Ordering::SeqCst);
            if hold != last_hold {
                last_hold = hold;
                if hold {
                    self.stand();
                    self.plan = Plan::Hold;
                } else {
                    self.plan = Plan::Idle(now + Duration::from_millis((self.idx as u64 * 300) % 2000));
                }
            }
            if self.live() && !hold {
                self.step();
            }
            std::thread::sleep(Duration::from_millis(match self.plan {
                Plan::Hunt { .. } | Plan::Duel { .. } => 150,
                _ => 250,
            }));
        }
        let snap = self.snapshot();
        self.sh.snaps.lock().unwrap().insert(self.idx, snap);
        if let Some(c) = self.conn.take() {
            let _ = c.disconnect();
        }
    }
}

pub fn run() {
    let stdin = std::io::stdin();
    let mut lines = stdin.lock().lines();
    let req: Value = serde_json::from_str(&lines.next().expect("request line").expect("stdin")).expect("request JSON");
    let (log, writer) = Log::open(req["events"].as_str().expect("events path"));
    let specs = req["players"].as_array().expect("players").clone();
    let sh = Arc::new(Shared {
        log: log.clone(),
        uri: req["uri"].as_str().unwrap().to_string(),
        db: req["db"].as_str().unwrap().to_string(),
        stop: AtomicBool::new(false),
        hold: AtomicBool::new(false),
        chars: Mutex::default(),
        offers: Mutex::default(),
        cmds: specs.iter().map(|_| Mutex::default()).collect(),
        snap_gen: AtomicU64::new(0),
        snaps: Mutex::default(),
        out: Mutex::new(std::io::stdout()),
    });
    let mut handles = Vec::new();
    let mut sts = Vec::new();
    for (idx, p) in specs.iter().enumerate() {
        let st: Arc<Mutex<St>> = Arc::default();
        sts.push(st.clone());
        let player = Player {
            idx,
            name: p["name"].as_str().unwrap().to_string(),
            token: p["token"].as_str().unwrap().to_string(),
            confirmed: p["confirmed"].as_bool().unwrap_or(true),
            sh: sh.clone(),
            st,
            conn: None,
            window: None,
            plan: Plan::Idle(Instant::now() + Duration::from_secs(2)),
            rng: Rng(0x9E37_79B9_7F4A_7C15 ^ (idx as u64 + 1).wrapping_mul(0xBF58_476D_1CE4_E5B9)),
            next_try: Instant::now() + Duration::from_millis(idx as u64 * 200),
            away_since: None,
            away_planned: false,
            lost_at: None,
            last_dir: None,
            last_move: None,
            cards: HashMap::new(),
            snap_seen: 0,
            reconnects: 0,
            down_ms: Vec::new(),
        };
        handles.push(std::thread::Builder::new().name(format!("soak-{idx}")).spawn(move || player.run()).unwrap());
    }
    let t = Instant::now();
    while sts.iter().any(|s| s.lock().unwrap().me.is_none()) {
        assert!(t.elapsed() < Duration::from_secs(300), "not every player has a character");
        std::thread::sleep(Duration::from_millis(100));
    }
    let chars: Vec<Value> = sts.iter().enumerate().map(|(i, s)| json!({"p": i, "id": s.lock().unwrap().me})).collect();
    sh.print(json!({"event": "ready", "after_s": t.elapsed().as_secs_f32(), "players": chars}));
    log.put(json!({"k": "go", "ts": unix_us()}));
    for line in lines {
        let Ok(line) = line else { break };
        let Ok(c) = serde_json::from_str::<Value>(line.trim()) else { continue };
        log.put(json!({"k": "cmd", "c": c, "ts": unix_us()}));
        match c["cmd"].as_str().unwrap_or("") {
            "stop" => break,
            "hold" => sh.hold.store(true, Ordering::SeqCst),
            "resume" => sh.hold.store(false, Ordering::SeqCst),
            "snap" => {
                sh.snaps.lock().unwrap().clear();
                sh.snap_gen.fetch_add(1, Ordering::SeqCst);
                let t = Instant::now();
                while sh.snaps.lock().unwrap().len() < specs.len() && t.elapsed() < Duration::from_secs(10) {
                    std::thread::sleep(Duration::from_millis(20));
                }
                let snaps: Vec<Value> = sh.snaps.lock().unwrap().values().cloned().collect();
                let v = json!({"event": "snap", "tag": c["tag"], "ts": unix_us(), "players": snaps});
                log.put(v.clone());
                sh.print(v);
            }
            _ => {
                if let Some(p) = c["p"].as_u64() {
                    if let Some(q) = sh.cmds.get(p as usize) {
                        q.lock().unwrap().push_back(c);
                    }
                }
            }
        }
    }
    sh.stop.store(true, Ordering::SeqCst);
    sh.snaps.lock().unwrap().clear();
    for h in handles {
        let _ = h.join();
    }
    let snaps: Vec<Value> = sh.snaps.lock().unwrap().values().cloned().collect();
    let v = json!({"event": "done", "ts": unix_us(), "players": snaps});
    log.put(v.clone());
    sh.print(v);
    log.close();
    let _ = writer.join();
    std::process::exit(0);
}
