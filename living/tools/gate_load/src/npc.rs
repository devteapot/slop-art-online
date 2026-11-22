//! NPC-MEASURE (branch npc-measure only; docs/NPC_CLIENT_SERVICE.md): `npc`, a stand-in NPC body
//! service. One owner connection holds the battle's truth (bodies, fighters, characters, cards,
//! readiness), drives a share of the battle's AI fighters from outside, and sends their acts as
//! one batched `npc_intents` call at a time. It decides as `spawn_battle`'s graph does: when a
//! windup is aimed at it, guard (odd ids) or dodge (even ids), at once; else attack the nearest
//! person (walk up, strike in reach).
//!
//! With `share` 0 it drives no one and only records the fighter rows: the AI arm's record.
//!
//! Request (one JSON line on stdin): `uri`, `db`, `token`, `out` (a folder), `share` (0-4: the
//! fighters with `id % 4 < share` are driven), `decide_ms` (each NPC's decision period, 100),
//! `flush_ms` (how often the batch goes, 16), `react` (guard or dodge on a windup, true).
//! Prints `{"event":"ready"}`, waits for `go`, drives until `stop`, prints `{"event":"done",…}`.
//!
//! Records, in `out`:
//! - `fighters.csv`: `local_us,id,act,act_ms,release_ms,until_ms,target` for every fighter row this
//!   connection receives (the reflex latencies are paired from it, the same for both arms);
//! - `reflex.csv`: `recv_us,npc,attacker,windup_act_ms,release_ms,send_us` for each reflex sent;
//! - `batches.csv`: `send_us,srv_us,back_us,intents,reflexes,status` for each call.

use crate::{connect, stdin_lines, unix_us, wait_for};
use living_bindings::*;
use serde_json::{json, Value};
use spacetimedb_sdk::{DbContext, Table, TableWithPrimaryKey};
use std::collections::{HashMap, HashSet};
use std::io::Write;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};

type Out = Arc<Mutex<std::io::BufWriter<std::fs::File>>>;

fn file(dir: &str, name: &str) -> Out {
    Arc::new(Mutex::new(std::io::BufWriter::with_capacity(1 << 20, std::fs::File::create(format!("{dir}/{name}")).expect("npc out"))))
}

fn here(b: &Body, now_ms: u64) -> (f32, f32) {
    let t = (now_ms.min(b.next_ms).saturating_sub(b.t_ms)) as f32 / 1000.0;
    (b.x + b.vx * t, b.y + b.vy * t)
}

fn dist(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}

#[derive(Default)]
struct Npc {
    next_decide: u64,
    last_dir: Option<(f32, f32, bool)>,
    last_move: Option<Instant>,
    /// When a raised guard is let go (local ms), and the hold after a timed move (local ms).
    release_at: Option<u64>,
    held_until: u64,
}

/// A reflex owed: the windup seen (when, by whom, its server start and release).
struct Reflex {
    recv_us: i64,
    npc: u32,
    attacker: u32,
    act_ms: u64,
    release_ms: u64,
}

fn intent(character: u32, kind: u8, skill: &str, target: u32, x: f32, y: f32, run: bool) -> NpcIntent {
    NpcIntent { character, kind, skill: skill.to_string(), target, x, y, run }
}

pub fn run() {
    let lines = stdin_lines();
    let req: Value = serde_json::from_str(&lines.recv().expect("request line")).expect("request JSON");
    let (uri, db, token) = (req["uri"].as_str().unwrap(), req["db"].as_str().unwrap(), req["token"].as_str().unwrap());
    let dir = req["out"].as_str().unwrap().to_string();
    let share = req["share"].as_u64().unwrap_or(0) as u32;
    let decide_ms = req["decide_ms"].as_u64().unwrap_or(100);
    let flush_ms = req["flush_ms"].as_u64().unwrap_or(16);
    let react = req["react"].as_bool().unwrap_or(true);
    let (conn, _) = connect(uri, db, token, None);
    let conn = Arc::new(conn);
    let fighters_out = file(&dir, "fighters.csv");
    let reflex_out = file(&dir, "reflex.csv");
    let batch_out = file(&dir, "batches.csv");
    let driven: Arc<Mutex<HashSet<u32>>> = Arc::default();
    let (rtx, rrx) = mpsc::channel::<Reflex>();
    let (dodge_code, guard_codes) = (Arc::new(AtomicU64::new(u64::MAX)), Arc::new(Mutex::new(HashSet::<u8>::new())));
    let on_row = {
        let (o, d, dc, gc) = (fighters_out.clone(), driven.clone(), dodge_code.clone(), guard_codes.clone());
        move |f: &Fighter| {
            let t = unix_us();
            let _ = writeln!(o.lock().unwrap(), "{t},{},{},{},{},{},{}", f.id, f.act, f.act_ms, f.release_ms, f.until_ms, f.target);
            // A windup aimed at someone I drive: an act that is not a guard, a dodge, a heal or a
            // jump, whose release is still to come.
            if react && f.act != 0 && f.release_ms > f.act_ms && f.release_ms > (t / 1000) as u64 && f.act as u64 != dc.load(Ordering::Relaxed) && !gc.lock().unwrap().contains(&f.act) && d.lock().unwrap().contains(&f.target) {
                let _ = rtx.send(Reflex { recv_us: t, npc: f.target, attacker: f.id, act_ms: f.act_ms, release_ms: f.release_ms });
            }
        }
    };
    let r1 = on_row.clone();
    conn.db.fighter().on_insert(move |_, f| r1(f));
    let r2 = on_row.clone();
    conn.db.fighter().on_update(move |_, _, f| r2(f));
    let applied = Arc::new(AtomicBool::new(false));
    let a2 = applied.clone();
    conn.subscription_builder()
        .on_applied(move |_| a2.store(true, Ordering::SeqCst))
        .on_error(|_, e| panic!("npc: {e}"))
        .subscribe(["body", "fighter", "character", "skill_card", "readiness"].iter().map(|t| format!("SELECT * FROM {t}")).collect::<Vec<_>>());
    let t0 = Instant::now();
    while !applied.load(Ordering::SeqCst) {
        assert!(t0.elapsed() < Duration::from_secs(120), "npc subscription");
        std::thread::sleep(Duration::from_millis(10));
    }
    let cards: HashMap<String, SkillCard> = conn.db.skill_card().iter().map(|c| (c.skill.clone(), c)).collect();
    if let Some(c) = cards.get("dodge") {
        dodge_code.store(c.code as u64, Ordering::Relaxed);
    }
    *guard_codes.lock().unwrap() = ["block", "heal", "jump"].iter().filter_map(|s| cards.get(*s).map(|c| c.code)).collect();
    println!("{}", json!({"event": "ready", "cards": cards.keys().collect::<Vec<_>>()}));
    let _ = std::io::stdout().flush();
    wait_for(&lines, "go");
    let stop = Arc::new(AtomicBool::new(false));
    let s2 = stop.clone();
    std::thread::spawn(move || {
        wait_for(&lines, "stop");
        s2.store(true, Ordering::SeqCst);
    });
    let flusher = {
        let o = vec![fighters_out.clone(), reflex_out.clone(), batch_out.clone()];
        move || {
            for f in &o {
                let _ = f.lock().unwrap().flush();
            }
        }
    };
    let counts: Arc<Mutex<HashMap<&'static str, u64>>> = Arc::default();
    let mut npcs: HashMap<u32, Npc> = HashMap::new();
    let mut last_census = Instant::now() - Duration::from_secs(10);
    let mut last_flush = Instant::now();
    let mut carried: Vec<Reflex> = Vec::new();
    let reach = cards.get("strike").map_or(1.6, |c| c.reach);
    let strike_hold = cards.get("strike").map_or(0, |c| (c.windup_ms + c.recover_ms) as u64);
    let dodge_hold = cards.get("dodge").map_or(0, |c| (c.windup_ms + c.recover_ms) as u64);
    while !stop.load(Ordering::SeqCst) {
        let tick = Instant::now();
        let now = (unix_us() / 1000) as u64;
        // Census once a second: the fighters I drive (`Fighter…`, alive, `id % 4 < share`).
        if share > 0 && last_census.elapsed() >= Duration::from_secs(1) {
            last_census = Instant::now();
            let alive: HashSet<u32> = conn.db.character().iter().filter(|c| c.alive && c.name.starts_with("Fighter") && c.id % 4 < share).map(|c| c.id).collect();
            let new: Vec<u32> = {
                let mut d = driven.lock().unwrap();
                d.retain(|id| alive.contains(id));
                let new: Vec<u32> = alive.iter().copied().filter(|id| !d.contains(id)).collect();
                d.extend(new.iter().copied());
                new
            };
            npcs.retain(|id, _| alive.contains(id));
            if !new.is_empty() {
                let (c, n) = (counts.clone(), new.len() as u64);
                let _ = conn.reducers.npc_external_set_then(new.clone(), true, move |_, res| {
                    *c.lock().unwrap().entry(if matches!(res, Ok(Ok(()))) { "listed" } else { "list_failed" }).or_default() += n;
                });
                for id in new {
                    npcs.insert(id, Npc { next_decide: now + (id as u64 * 37) % decide_ms, ..Default::default() });
                }
            }
        }
        let mut batch: Vec<NpcIntent> = Vec::new();
        let mut reflexes: Vec<Reflex> = std::mem::take(&mut carried);
        while let Ok(r) = rrx.try_recv() {
            reflexes.push(r);
        }
        let bodies = |id: u32| conn.db.body().id().find(&id);
        // Reflexes first, at once: guard toward the attacker or dodge away from it.
        let mut reflexed = HashSet::new();
        for r in &reflexes {
            let Some(n) = npcs.get_mut(&r.npc) else { continue };
            if !reflexed.insert(r.npc) {
                continue;
            }
            let (Some(me), Some(att)) = (bodies(r.npc), bodies(r.attacker)) else { continue };
            let (p, a) = (here(&me, now), here(&att, now));
            if r.npc % 2 == 0 {
                batch.push(intent(r.npc, 1, "dodge", 0, p.0 - (a.0 - p.0), p.1 - (a.1 - p.1), false));
                n.held_until = now + dodge_hold;
            } else {
                batch.push(intent(r.npc, 1, "block", r.attacker, a.0, a.1, false));
                n.release_at = Some(now + 600);
            }
            let _ = writeln!(reflex_out.lock().unwrap(), "{},{},{},{},{},{}", r.recv_us, r.npc, r.attacker, r.act_ms, r.release_ms, unix_us());
        }
        let nreflex = batch.len();
        // Decisions due: let go of a guard held long enough; strike the nearest person in reach,
        // else walk up to it.
        let people: Vec<(u32, (f32, f32))> = if npcs.values().any(|n| n.next_decide <= now) {
            conn.db.character().iter().filter(|c| c.alive && c.kind == "person").filter_map(|c| bodies(c.id).map(|b| (c.id, here(&b, now)))).collect()
        } else {
            Vec::new()
        };
        for (&id, n) in npcs.iter_mut() {
            if n.release_at.is_some_and(|r| now >= r) {
                n.release_at = None;
                batch.push(intent(id, 2, "block", 0, 0.0, 0.0, false));
            }
            if n.next_decide > now || reflexed.contains(&id) {
                continue;
            }
            n.next_decide = now + decide_ms;
            let Some(me) = bodies(id) else { continue };
            let p = here(&me, now);
            let ready = conn.db.readiness().id().find(&id);
            let busy = n.held_until > now || n.release_at.is_some() || ready.as_ref().is_some_and(|r| r.busy_until > now);
            let cooled = ready.as_ref().is_none_or(|r| r.ready.iter().all(|x| x.skill != "strike" || x.at_ms <= now));
            let Some((tid, at)) = people.iter().filter(|(c, _)| *c != id).min_by(|a, b| dist(p, a.1).total_cmp(&dist(p, b.1))).copied() else { continue };
            let d = dist(p, at);
            if d <= reach + 0.4 && !busy && cooled {
                batch.push(intent(id, 1, "strike", tid, at.0, at.1, false));
                n.held_until = now + strike_hold;
                continue;
            }
            if busy {
                continue;
            }
            let want = if d > 1.4 { ((at.0 - p.0) / d, (at.1 - p.1) / d, d > 6.0) } else { (0.0, 0.0, false) };
            let changed = match n.last_dir {
                None => true,
                Some((lx, ly, lr)) => {
                    let stop_change = (lx == 0.0 && ly == 0.0) != (want.0 == 0.0 && want.1 == 0.0);
                    stop_change || lr != want.2 || (lx * want.0 + ly * want.1).clamp(-1.0, 1.0).acos() > 0.52
                }
            };
            let since = n.last_move.map(|t| t.elapsed());
            let refresh = since.is_none_or(|s| s > Duration::from_secs(2)) && (want.0 != 0.0 || want.1 != 0.0);
            if (changed || refresh) && since.is_none_or(|s| s > Duration::from_millis(200)) {
                batch.push(intent(id, 0, "", 0, want.0, want.1, want.2));
                n.last_dir = Some(want);
                n.last_move = Some(Instant::now());
            }
        }
        if !batch.is_empty() {
            let (n, send) = (batch.len(), unix_us());
            *counts.lock().unwrap().entry("intents").or_default() += n as u64;
            *counts.lock().unwrap().entry("reflexes").or_default() += nreflex as u64;
            *counts.lock().unwrap().entry("batches").or_default() += 1;
            let (bo, c) = (batch_out.clone(), counts.clone());
            let sent = conn.reducers.npc_intents_then(batch, move |ctx, res| {
                let back = unix_us();
                let ok = matches!(res, Ok(Ok(())));
                if !ok {
                    *c.lock().unwrap().entry("batch_failed").or_default() += 1;
                }
                let _ = writeln!(bo.lock().unwrap(), "{send},{},{back},{n},{nreflex},{}", ctx.event.timestamp.to_micros_since_unix_epoch(), if ok { "ok" } else { "err" });
            });
            if sent.is_err() {
                *counts.lock().unwrap().entry("send_failed").or_default() += 1;
            }
        }
        if last_flush.elapsed() >= Duration::from_secs(1) {
            last_flush = Instant::now();
            flusher();
        }
        // The next round: at once when a reflex is waiting, else after `flush_ms`.
        let wait = Duration::from_millis(flush_ms).saturating_sub(tick.elapsed());
        let t = Instant::now();
        while t.elapsed() < wait {
            if let Ok(r) = rrx.recv_timeout(wait.saturating_sub(t.elapsed())) {
                // A windup at someone I drive: the next round goes now, with it.
                carried.push(r);
                break;
            }
        }
    }
    flusher();
    println!("{}", json!({"event": "done", "driven": driven.lock().unwrap().len(), "counts": *counts.lock().unwrap()}));
    let _ = std::io::stdout().flush();
    let _ = conn.disconnect();
    std::process::exit(0);
}
