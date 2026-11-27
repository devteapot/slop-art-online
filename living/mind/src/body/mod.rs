//! The body controller worker (docs/NEURAL_BODY.md, "Built (pilot plumbing)"): `living-mind body`.
//!
//! It connects as the characters' controller (the mind service's identity) and reads only the
//! private rows that say what is delegated: `body_slot`, `body_brief`, `body_session`. For each
//! character with a delegated leaf (all, or those `LIVING_BODY_ONLY` lists) it opens a **body
//! session**: a connection of its own with a fresh identity (no token), bound to the character by
//! `body_open` (a new controller epoch, one writer). That connection subscribes to exactly what a
//! player's client is delivered for its own character, under the world's delivery laws:
//! `my_body`, `my_fighter`, `my_readiness`, `my_skill_uses`, the copies of what it perceives
//! (`seen_body_copy`, `seen_character_copy`, `seen_fighter_copy`, or the views when those laws are
//! off), the cue tables and its combat feed (`combat_feed`, `my_combat`). Each decision (15 Hz by
//! default, `LIVING_BODY_HZ`) encodes those rows into bounded slots (`encode.rs`), runs the policy
//! (`policy.rs`: one shared policy per role, the character's kind, with the character's own small
//! memory carried between decisions and reset on a new epoch or brief revision; the pilot ships the
//! scripted `HoldDistance`, no trained net) and sends its typed
//! intents through the player input reducers (`human_move`, `human_face`, `use_skill`,
//! `release_skill`), whose checks, budgets and outcomes are a player's. It beats the session's lease
//! (`body_beat`). It captures each decision, each reply and each resolved outcome (`capture.rs`).
//!
//! **Stall and return.** If the worker itself stops for longer than the lease (or its session is no
//! longer live, or its identity no longer holds it), everything decided and not yet sent is dropped,
//! the old connection is closed (its identity is fenced by the authority: no session holds it), and a
//! new connection with a new identity opens a new epoch from a fresh observation. A press that timed
//! out is never sent again. While no session is live the character stands, as the authority lets go
//! of its held inputs at the lapse; the graph does not take over.

pub mod capture;
pub mod encode;
pub mod net;
pub mod policy;

use anyhow::{anyhow, Context, Result};
use encode::{BodyRow, BriefView, CueRow, FighterRow, Observation, SeenRow, SkillRow, SlotView};
use living_bindings::*;
use policy::{Intent, Memory, Policy};
use serde_json::json;
use spacetimedb_sdk::{DbContext, EventTable, Identity, Table};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// Cues (event rows) as last delivered for each creature, standing until its next copy row.
#[derive(Default)]
struct Overlay {
    bodies: HashMap<u32, (u64, Moving)>,
    fighters: HashMap<u32, (u64, Option<Fighter>)>,
    feed: Vec<CueRow>,
}

/// A served character's session.
struct Session {
    conn: DbConnection,
    identity: Identity,
    epoch: u32,
    applied: Arc<Mutex<bool>>,
    overlay: Arc<Mutex<Overlay>>,
    seq: u64,
    sent_move: Option<(f32, f32, bool)>,
    sent_face: Option<(f32, f32)>,
    last_beat: Instant,
}

struct Served {
    actor: u32,
    session: Option<Session>,
    /// Its own memory between decisions (the policy is its role's, shared).
    memory: Memory,
    /// When its slot was last seen (a session is closed once it has been gone a while).
    slot_seen: Instant,
}

fn flatten<E: std::fmt::Debug>(r: Result<Result<(), String>, E>) -> Result<(), String> {
    match r {
        Ok(r) => r,
        Err(e) => Err(format!("{e:?}")),
    }
}

fn hex(id: &Identity) -> String {
    id.to_hex().to_string()
}

/// What the worker records, from the SDK's threads.
type Records = Arc<Mutex<Vec<(String, serde_json::Value)>>>;

pub async fn main(server: String, db: String, token: String) -> Result<()> {
    let only: Option<Vec<u32>> = std::env::var("LIVING_BODY_ONLY").ok().filter(|s| !s.trim().is_empty()).map(|s| s.split(',').filter_map(|x| x.trim().parse().ok()).collect());
    let hz: f32 = std::env::var("LIVING_BODY_HZ").ok().and_then(|v| v.parse().ok()).unwrap_or(15.0);
    let hold: Option<f32> = std::env::var("LIVING_BODY_DISTANCE").ok().and_then(|v| v.parse().ok());
    let mut capture = capture::Capture::from_env()?;
    let records: Records = Arc::new(Mutex::new(Vec::new()));
    let (ready_tx, ready_rx) = tokio::sync::oneshot::channel::<()>();
    let ready = Arc::new(Mutex::new(Some(ready_tx)));
    let control = DbConnection::builder()
        .with_uri(server.clone())
        .with_database_name(db.clone())
        .with_token(Some(token))
        .on_connect(move |c, identity, _| {
            log::info!("body worker: connected as the controller {identity}");
            let ready = ready.clone();
            c.subscription_builder()
                .on_applied(move |_| {
                    if let Some(tx) = ready.lock().unwrap().take() {
                        let _ = tx.send(());
                    }
                })
                .on_error(|_, e| log::error!("body worker: subscription error: {e:?}"))
                .subscribe(["SELECT * FROM body_slot", "SELECT * FROM body_brief", "SELECT * FROM body_session", "SELECT * FROM skill_card", "SELECT * FROM law_override"].map(String::from).to_vec());
        })
        .on_disconnect(|_, e| {
            log::error!("body worker: the controller connection closed: {e:?}");
            std::process::exit(2);
        })
        .build()
        .with_context(|| format!("connect to {server}/{db}"))?;
    control.run_threaded();
    ready_rx.await.map_err(|_| anyhow!("the controller subscription never applied"))?;
    log::info!("body worker: serving {} at {hz} Hz", only.as_ref().map_or("every delegated character".to_string(), |o| format!("{o:?}")));
    let mut lease_ms = lease_ms(&control);
    let period = Duration::from_secs_f32(1.0 / hz.clamp(1.0, 60.0));
    let mut served: HashMap<u32, Served> = HashMap::new();
    // One policy per role (a character's kind), shared by every character of it.
    let mut policies: HashMap<String, Box<dyn Policy>> = HashMap::new();
    if let Some(c) = capture.as_mut() {
        c.write("layout", json!({"encoded": encode::LEN, "memory": policy::MEMORY, "state": policy::STATE, "history": policy::HISTORY, "intent": policy::INTENT,
                                 "flat": "encoded, then memory (state, then history newest first)", "traits": living_rules::body::MAX_TRAITS}));
    }
    let mut last_loop = Instant::now();
    let mut tick = tokio::time::interval(period);
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        tick.tick().await;
        lease_ms = lease_ms_now(&control, lease_ms);
        // From the end of the last iteration: the worker's own work (an open) is not a stall.
        let gap = last_loop.elapsed();
        // The worker itself stalled past the lease: nothing decided before is sent; every session is
        // fenced and reopened from a fresh observation.
        if gap.as_millis() as u64 > lease_ms {
            log::warn!("body worker: stalled {} ms (lease {lease_ms} ms): every session reopens", gap.as_millis());
            for s in served.values_mut() {
                if let Some(old) = s.session.take() {
                    if let Some(c) = capture.as_mut() {
                        c.write("session", json!({"actor": s.actor, "epoch": old.epoch, "event": "stalled", "gap_ms": gap.as_millis() as u64}));
                    }
                    let _ = old.conn.disconnect();
                }
            }
        }
        for (kind, rec) in std::mem::take(&mut *records.lock().unwrap()) {
            if let Some(c) = capture.as_mut() {
                c.write(&kind, rec);
            }
        }
        let slots: Vec<BodySlot> = control.db.body_slot().iter().filter(|s| only.as_ref().is_none_or(|o| o.contains(&s.actor))).collect();
        for slot in &slots {
            let s = served.entry(slot.actor).or_insert_with(|| Served { actor: slot.actor, session: None, memory: Memory::new(0, 0), slot_seen: Instant::now() });
            s.slot_seen = Instant::now();
        }
        // A character whose leaf ended a while ago: its session is closed (it stands).
        let gone: Vec<u32> = served.iter().filter(|(_, s)| s.slot_seen.elapsed() > Duration::from_secs(3)).map(|(a, _)| *a).collect();
        for a in gone {
            if let Some(s) = served.remove(&a) {
                if let Some(old) = s.session {
                    let _ = control.reducers.body_close(a);
                    let _ = old.conn.disconnect();
                    if let Some(c) = capture.as_mut() {
                        c.write("session", json!({"actor": a, "epoch": old.epoch, "event": "closed"}));
                    }
                }
            }
        }
        for slot in slots {
            let Some(s) = served.get_mut(&slot.actor) else { continue };
            // The session must be live and ours; else (a lapse, a newer epoch elsewhere) it reopens.
            let row = control.db.body_session().actor().find(&slot.actor);
            let ours = s.session.as_ref().is_some_and(|x| row.as_ref().is_some_and(|r| r.live && r.identity == x.identity && r.epoch == x.epoch));
            if !ours {
                if let Some(old) = s.session.take() {
                    if let Some(c) = capture.as_mut() {
                        c.write("session", json!({"actor": s.actor, "epoch": old.epoch, "event": "lost", "live": row.as_ref().map(|r| r.live)}));
                    }
                    let _ = old.conn.disconnect();
                }
                match open(&server, &db, &control, slot.actor, &records).await {
                    Ok(new) => {
                        if let Some(c) = capture.as_mut() {
                            c.write("session", json!({"actor": s.actor, "epoch": new.epoch, "event": "opened", "identity": hex(&new.identity)}));
                        }
                        s.session = Some(new);
                    }
                    Err(e) => {
                        log::warn!("body worker: #{}: could not open a session: {e:#}", slot.actor);
                        continue;
                    }
                }
            }
            let Some(sess) = s.session.as_mut() else { continue };
            if !*sess.applied.lock().unwrap() {
                continue;
            }
            if sess.last_beat.elapsed().as_millis() as u64 >= lease_ms / 3 {
                sess.last_beat = Instant::now();
                let (epoch, recs, actor) = (sess.epoch, records.clone(), slot.actor);
                let _ = sess.conn.reducers.body_beat_then(epoch, move |_, r| {
                    if let Err(e) = flatten(r) {
                        recs.lock().unwrap().push(("reply".into(), json!({"actor": actor, "epoch": epoch, "reducer": "body_beat", "refused": e})));
                    }
                });
            }
            let policy = policies.entry(slot.role.clone()).or_insert_with(|| {
                let p = policy::for_role(&slot.role, hold);
                log::info!("body worker: role {:?} served by {} ({})", slot.role, p.name(), p.version());
                p
            });
            decide(&control, slot.clone(), policy.as_ref(), &mut s.memory, sess, &records, capture.as_mut());
        }
        last_loop = Instant::now();
    }
}

/// The `body_lease_ms` law: the world's own value (`law_override`, public), else the shipped 750, or
/// `LIVING_BODY_LEASE_MS` for a run.
fn lease_ms(control: &DbConnection) -> u64 {
    let shipped = std::env::var("LIVING_BODY_LEASE_MS").ok().and_then(|v| v.parse().ok()).unwrap_or(750);
    lease_ms_now(control, shipped)
}

fn lease_ms_now(control: &DbConnection, before: u64) -> u64 {
    control.db.law_override().iter().find(|l| l.name == "body_lease_ms").and_then(|l| l.value.trim().parse::<f64>().ok()).map_or(before, |v| v.clamp(100.0, 10_000.0) as u64)
}

/// Open a session for `actor`: a new connection with a fresh identity, bound by `body_open` (a new
/// epoch), subscribed to the player-equivalent rows of its character.
async fn open(server: &str, db: &str, control: &DbConnection, actor: u32, records: &Records) -> Result<Session> {
    let (id_tx, id_rx) = tokio::sync::oneshot::channel::<Identity>();
    let id_tx = Mutex::new(Some(id_tx));
    let conn = DbConnection::builder()
        .with_uri(server.to_string())
        .with_database_name(db.to_string())
        .with_token(None::<String>)
        .on_connect(move |_, identity, _| {
            if let Some(tx) = id_tx.lock().unwrap().take() {
                let _ = tx.send(identity);
            }
        })
        .on_disconnect(move |_, e| log::info!("body worker: #{actor}'s session connection closed ({e:?})"))
        .build()
        .context("connect a body session")?;
    conn.run_threaded();
    let identity = tokio::time::timeout(Duration::from_secs(10), id_rx).await.map_err(|_| anyhow!("no identity in 10 s"))??;
    let (tx, rx) = tokio::sync::oneshot::channel();
    control.reducers.body_open_then(actor, identity, move |_, r| {
        let _ = tx.send(flatten(r));
    })?;
    tokio::time::timeout(Duration::from_secs(10), rx).await.map_err(|_| anyhow!("body_open: no reply in 10 s"))??.map_err(|e| anyhow!("body_open refused: {e}"))?;
    // The epoch the authority gave it, once the controller's copy of the row shows this identity.
    let deadline = Instant::now() + Duration::from_secs(5);
    let epoch = loop {
        if let Some(r) = control.db.body_session().actor().find(&actor).filter(|r| r.identity == identity && r.live) {
            break r.epoch;
        }
        if Instant::now() > deadline {
            let _ = conn.disconnect();
            return Err(anyhow!("the session row never showed this identity"));
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    };
    let applied = Arc::new(Mutex::new(false));
    let overlay = Arc::new(Mutex::new(Overlay::default()));
    {
        let o = overlay.clone();
        conn.db.seen_body_cue().on_insert(move |_, c| {
            o.lock().unwrap().bodies.insert(c.motion.id, (c.at_ms, c.motion.clone()));
        });
        let o = overlay.clone();
        conn.db.seen_fighter_cue().on_insert(move |_, c| {
            o.lock().unwrap().fighters.insert(c.body, (c.at_ms, c.fighter.clone()));
        });
        let o = overlay.clone();
        conn.db.combat_feed().on_insert(move |_, f| {
            let mut o = o.lock().unwrap();
            o.feed.push(CueRow { viewer: f.viewer.to_byte_array(), at_ms: f.at_ms, kind: f.kind, actor: f.actor, target: f.target, skill: f.skill, amount: f.amount });
            let n = o.feed.len();
            if n > 32 {
                o.feed.drain(..n - 32);
            }
        });
        // A view without a primary key: a changed row arrives as a delete and an insert. Each use's
        // resolved outcome is recorded once.
        let recs = records.clone();
        let told = Mutex::new(std::collections::HashSet::<u64>::new());
        conn.db.my_skill_uses().on_insert(move |_, u| {
            if !u.outcome.is_empty() && told.lock().unwrap().insert(u.id) {
                recs.lock().unwrap().push(("outcome".into(), json!({"actor": u.actor, "use": u.id, "skill": u.skill, "source": u.source, "at_ms": u.at_ms, "target": u.target, "accepted_ms": u.accepted_ms, "released_ms": u.released_ms, "outcome": u.outcome, "outcome_ms": u.outcome_ms})));
            }
        });
    }
    let done = applied.clone();
    conn.subscription_builder()
        .on_applied(move |_| *done.lock().unwrap() = true)
        .on_error(move |_, e| log::warn!("body worker: #{actor}'s session subscription: {e:?}"))
        .subscribe(
            [
                "SELECT * FROM my_body",
                "SELECT * FROM my_fighter",
                "SELECT * FROM my_readiness",
                "SELECT * FROM my_skill_uses",
                "SELECT * FROM my_combat",
                "SELECT * FROM combat_feed",
                "SELECT * FROM seen_character_copy",
                "SELECT * FROM seen_body_copy",
                "SELECT * FROM seen_fighter_copy",
                "SELECT * FROM seen_body_cue",
                "SELECT * FROM seen_fighter_cue",
                "SELECT * FROM seen_characters",
                "SELECT * FROM seen_bodies",
                "SELECT * FROM seen_fighters",
            ]
            .map(String::from)
            .to_vec(),
        );
    log::info!("body worker: #{actor}: session epoch {epoch} as {identity}");
    Ok(Session { conn, identity, epoch, applied, overlay, seq: 0, sent_move: None, sent_face: None, last_beat: Instant::now() })
}

fn moving_row(m: &Moving) -> BodyRow {
    BodyRow { id: m.id, x: m.x, y: m.y, t_ms: m.t_ms, vx: m.vx, vy: m.vy, heading: m.heading }
}

fn fighter_row(f: &Fighter) -> FighterRow {
    FighterRow { id: f.id, act: f.act, act_ms: f.act_ms, release_ms: f.release_ms, until_ms: f.until_ms, target: f.target }
}

/// One decision's observation, from the session connection's delivered rows (and the public cards).
fn observe(control: &DbConnection, actor: u32, s: &Session, now: u64) -> Observation {
    let c = &s.conn;
    let me = c.db.my_body().iter().next();
    let mut others: HashMap<u32, BodyRow> = c.db.seen_bodies().iter().filter(|m| m.id != actor).map(|m| (m.id, moving_row(&m))).collect();
    for copy in c.db.seen_body_copy().iter().filter(|x| x.viewer == s.identity && x.body != actor) {
        let g = &copy.seg;
        others.insert(copy.body, BodyRow { id: copy.body, x: g.x, y: g.y, t_ms: g.t_ms, vx: g.vx, vy: g.vy, heading: g.heading });
    }
    let mut fighters: HashMap<u32, FighterRow> = c.db.seen_fighters().iter().map(|f| (f.id, fighter_row(&f))).collect();
    for copy in c.db.seen_fighter_copy().iter().filter(|x| x.viewer == s.identity) {
        fighters.insert(copy.body, fighter_row(&copy.fighter));
    }
    let mut seen: HashMap<u32, SeenRow> = c.db.seen_characters().iter().map(|x| (x.id, SeenRow { id: x.id, kind: x.kind.clone(), own: x.own, band: x.band, hp: x.hp, max_hp: x.max_hp })).collect();
    for copy in c.db.seen_character_copy().iter().filter(|x| x.viewer == s.identity) {
        let x = &copy.row;
        seen.insert(x.id, SeenRow { id: x.id, kind: x.kind.clone(), own: x.own, band: x.band, hp: x.hp, max_hp: x.max_hp });
    }
    let mut cues: Vec<CueRow> = c.db.my_combat().iter().map(|f| CueRow { viewer: f.viewer.to_byte_array(), at_ms: f.at_ms, kind: f.kind, actor: f.actor, target: f.target, skill: f.skill, amount: f.amount }).collect();
    {
        let mut o = s.overlay.lock().unwrap();
        // A cue stands until the creature's next copy row: the newer of the two.
        o.bodies.retain(|id, (at, _)| others.get(id).is_none_or(|b| b.t_ms < *at));
        for (id, (_, m)) in &o.bodies {
            if *id != actor && others.contains_key(id) {
                others.insert(*id, moving_row(m));
            }
        }
        for (id, (_, f)) in &o.fighters {
            match f {
                Some(f) => {
                    fighters.insert(*id, fighter_row(f));
                }
                None => {
                    fighters.remove(id);
                }
            }
        }
        cues.extend(o.feed.iter().cloned());
    }
    cues.sort_by_key(|c| c.at_ms);
    cues.dedup();
    let readiness = c.db.my_readiness().iter().next();
    let skills = control
        .db
        .skill_card()
        .iter()
        .map(|k| SkillRow { skill: k.skill.clone(), code: k.code, reach: k.reach, ready_ms: readiness.as_ref().and_then(|r| r.ready.iter().find(|x| x.skill == k.skill).map(|x| x.at_ms)).unwrap_or(0) })
        .collect();
    Observation {
        now_ms: now,
        me: actor,
        viewer: s.identity.to_byte_array(),
        body: me.as_ref().map(moving_row),
        own_fighter: c.db.my_fighter().iter().next().map(|f| fighter_row(&f)),
        busy_until: readiness.as_ref().map_or(0, |r| r.busy_until),
        others: others.into_values().collect(),
        seen: seen.into_values().collect(),
        fighters: fighters.into_values().collect(),
        cues,
        skills,
    }
}

/// One decision for a served character: observe, encode, decide, send through the player input
/// reducers (movement and the look only on a change), capture.
fn decide(control: &DbConnection, slot: BodySlot, policy: &dyn Policy, memory: &mut Memory, s: &mut Session, records: &Records, mut capture: Option<&mut capture::Capture>) {
    let t_start = Instant::now();
    let now = crate::llm::now_ms();
    let actor = slot.actor;
    let o = observe(control, actor, s, now);
    let sv = SlotView { revision: slot.revision, node: slot.node, goal: slot.goal.clone(), target: slot.target, skills: slot.skills.clone() };
    let row = control.db.body_brief().actor().find(&actor);
    let brief_rev = row.as_ref().map_or(0, |b| b.revision);
    let brief = row.filter(|b| !b.goal.is_empty()).map(|b| BriefView { revision: b.revision, goal: b.goal, target: b.target, stance: b.stance, risk: b.risk, style: b.style, traits: b.traits, expires_ms: b.expires_ms });
    // A new epoch or a new brief revision: the character's memory starts afresh.
    if memory.follow(s.epoch, brief_rev) {
        if let Some(c) = capture.as_mut() {
            c.write("memory", json!({"actor": actor, "epoch": s.epoch, "brief": brief_rev, "event": "reset"}));
        }
    }
    let v = encode::encode(&o, brief.as_ref(), &sv);
    let before = memory.flat();
    let intent = policy.decide(&o, &v, memory, brief.as_ref(), &sv);
    let decide_us = t_start.elapsed().as_micros() as u64;
    s.seq += 1;
    let (seq, epoch) = (s.seq, s.epoch);
    let reply = |reducer: &'static str| {
        let recs = records.clone();
        move |_: &ReducerEventContext, r: Result<Result<(), String>, spacetimedb_sdk::__codegen::InternalError>| {
            let r = flatten(r);
            recs.lock().unwrap().push(("reply".into(), json!({"actor": actor, "epoch": epoch, "seq": seq, "reducer": reducer, "ok": r.is_ok(), "refused": r.err()})));
        }
    };
    let mut sent = Intent::default();
    if let Some(m) = intent.moving {
        let same = s.sent_move.is_some_and(|p| (p.0 == 0.0 && p.1 == 0.0) == (m.0 == 0.0 && m.1 == 0.0) && p.2 == m.2 && angle_close(p, m));
        if !same {
            s.sent_move = Some(m);
            sent.moving = Some(m);
            let _ = s.conn.reducers.human_move_then(m.0, m.1, m.2, reply("human_move"));
        }
    }
    if let Some(f) = intent.face {
        if !s.sent_face.is_some_and(|p| angle_close((p.0, p.1, false), (f.0, f.1, false))) {
            s.sent_face = Some(f);
            sent.face = Some(f);
            let _ = s.conn.reducers.human_face_then(f.0, f.1, reply("human_face"));
        }
    }
    if let Some(p) = intent.press.clone() {
        sent.press = Some(p.clone());
        let _ = s.conn.reducers.use_skill_then(p.0, p.1, p.2, p.3, reply("use_skill"));
    }
    if let Some(k) = intent.release.clone() {
        sent.release = Some(k.clone());
        let _ = s.conn.reducers.release_skill_then(k, reply("release_skill"));
    }
    // The history holds what was decided (the policy's own output), sent or coalesced.
    let encoded_intent = intent.encode(&sv);
    memory.remember(encoded_intent);
    if let Some(c) = capture {
        // Everything a clone needs, flat: the encoded observation, then the memory the policy read.
        let mut flat = v.clone();
        flat.extend_from_slice(&before);
        c.write(
            "decision",
            json!({
                "actor": actor, "role": slot.role, "epoch": epoch, "seq": seq, "now_ms": now, "decide_us": decide_us,
                "policy": policy.name(), "policy_version": policy.version(),
                "encoded": v, "len": encode::LEN, "memory": before, "memory_after": memory.flat(), "flat": flat,
                "intent_encoded": encoded_intent,
                "observation": {
                    "body": o.body.as_ref().map(|b| json!([b.x, b.y, b.t_ms, b.vx, b.vy, b.heading])),
                    "others": o.others.len(), "seen": o.seen.len(), "fighters": o.fighters.len(), "cues": o.cues.len(),
                    "busy_until": o.busy_until,
                    "age_ms": o.others.iter().map(|b| now.saturating_sub(b.t_ms)).max(),
                },
                "slot": {"revision": sv.revision, "node": sv.node, "goal": sv.goal, "target": sv.target, "skills": sv.skills},
                "brief": brief.as_ref().map(|b| json!({"revision": b.revision, "goal": b.goal, "target": b.target, "stance": b.stance, "risk": b.risk, "style": b.style, "traits": b.traits, "expires_ms": b.expires_ms})),
                "intent": intent, "sent": sent,
            }),
        );
    }
}

fn angle_close(a: (f32, f32, bool), b: (f32, f32, bool)) -> bool {
    let (na, nb) = (a.0.hypot(a.1), b.0.hypot(b.1));
    if na < 1e-3 || nb < 1e-3 {
        return na < 1e-3 && nb < 1e-3;
    }
    (a.0 * b.0 + a.1 * b.1) / (na * nb) > 0.996
}

// ---- Teacher-graph capture on player-equivalent sessions (`living-mind body-observe`) ----

#[derive(Clone, Debug, serde::Deserialize)]
struct ObserveEntry {
    actor: u32,
    target: u32,
    role: String,
    goal: String,
    skills: Vec<String>,
    episode: String,
    teacher: String,
    opponent_cfg: String,
}

struct PendingObs {
    now_ms: u64,
    encoded: Vec<f32>,
    obs_age_ms: Option<u64>,
    was_rooted: bool,
    had_block: bool,
    body_xy: Option<(f32, f32)>,
    brief: Option<BriefView>,
    sv: SlotView,
    others_n: usize,
    seen_n: usize,
    fighters_n: usize,
    cues_n: usize,
    busy_until: u64,
}

struct Observed {
    entry: ObserveEntry,
    session: Option<Session>,
    memory: Memory,
    seen_uses: std::collections::HashSet<u64>,
    prev: Option<PendingObs>,
}

/// Observe graph-controlled characters through real `body_open` player-equivalent sessions and
/// capture causality-aligned `(observation, teacher_intent)` pairs via `Capture` without sending
/// any player inputs. Used in Step 2 of docs/NEURAL_BODY.md ("Pilot run").
pub async fn observe_main(server: String, db: String, token: String, manifest_path: String) -> Result<()> {
    let entries: Vec<ObserveEntry> = serde_json::from_str(&std::fs::read_to_string(&manifest_path).with_context(|| format!("read {manifest_path}"))?)?;
    let hz: f32 = std::env::var("LIVING_BODY_HZ").ok().and_then(|v| v.parse().ok()).unwrap_or(15.0);
    let mut capture = capture::Capture::from_env()?.ok_or_else(|| anyhow!("LIVING_BODY_CAPTURE must be set for body-observe"))?;
    let records: Records = Arc::new(Mutex::new(Vec::new()));
    let (ready_tx, ready_rx) = tokio::sync::oneshot::channel::<()>();
    let ready = Arc::new(Mutex::new(Some(ready_tx)));
    let control = DbConnection::builder()
        .with_uri(server.clone())
        .with_database_name(db.clone())
        .with_token(Some(token))
        .on_connect(move |c, identity, _| {
            log::info!("body observe: connected as controller {identity}");
            let ready = ready.clone();
            c.subscription_builder()
                .on_applied(move |_| {
                    if let Some(tx) = ready.lock().unwrap().take() {
                        let _ = tx.send(());
                    }
                })
                .on_error(|_, e| log::error!("body observe: subscription error: {e:?}"))
                .subscribe(["SELECT * FROM body_slot", "SELECT * FROM body_brief", "SELECT * FROM body_session", "SELECT * FROM skill_card", "SELECT * FROM law_override"].map(String::from).to_vec());
        })
        .on_disconnect(|_, e| {
            log::error!("body observe: controller disconnected: {e:?}");
            std::process::exit(2);
        })
        .build()
        .with_context(|| format!("connect to {server}/{db}"))?;
    control.run_threaded();
    ready_rx.await.map_err(|_| anyhow!("body observe: controller subscription never applied"))?;
    let mut lease_ms = lease_ms(&control);
    let period = Duration::from_secs_f32(1.0 / hz.clamp(1.0, 60.0));
    let block_code = control.db.skill_card().iter().find(|k| k.skill == "block").map(|k| k.code).unwrap_or(0);
    capture.write("layout", json!({"encoded": encode::LEN, "memory": policy::MEMORY, "state": policy::STATE, "history": policy::HISTORY, "intent": policy::INTENT,
                                   "flat": "encoded, then memory (state, then history newest first)", "traits": living_rules::body::MAX_TRAITS, "mode": "observe"}));
    let mut actors: Vec<Observed> = entries
        .into_iter()
        .map(|entry| Observed { entry, session: None, memory: Memory::new(0, 0), seen_uses: Default::default(), prev: None })
        .collect();
    let mut tick = tokio::time::interval(period);
    tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        tick.tick().await;
        lease_ms = lease_ms_now(&control, lease_ms);
        for (kind, rec) in std::mem::take(&mut *records.lock().unwrap()) {
            capture.write(&kind, rec);
        }
        for ob in &mut actors {
            let actor = ob.entry.actor;
            let row = control.db.body_session().actor().find(&actor);
            let ours = ob.session.as_ref().is_some_and(|x| row.as_ref().is_some_and(|r| r.live && r.identity == x.identity && r.epoch == x.epoch));
            if !ours {
                if let Some(old) = ob.session.take() {
                    let _ = old.conn.disconnect();
                }
                ob.prev = None;
                match open(&server, &db, &control, actor, &records).await {
                    Ok(new) => {
                        capture.write("session", json!({"actor": actor, "epoch": new.epoch, "event": "opened", "mode": "observe", "episode": ob.entry.episode}));
                        // Pre-populate already existing uses so we only label new uses going forward.
                        ob.session = Some(new);
                    }
                    Err(e) => {
                        log::warn!("body observe: #{actor}: open failed: {e:#}");
                        continue;
                    }
                }
            }
            let Some(sess) = ob.session.as_mut() else { continue };
            if !*sess.applied.lock().unwrap() {
                continue;
            }
            if sess.last_beat.elapsed().as_millis() as u64 >= lease_ms / 3 {
                sess.last_beat = Instant::now();
                let _ = sess.conn.reducers.body_beat(sess.epoch);
            }
            let now = crate::llm::now_ms();
            let o = observe(&control, actor, sess, now);
            let Some(me_body) = sess.conn.db.my_body().iter().next() else {
                // Dead or despawned.
                ob.prev = None;
                continue;
            };
            let b_row = control.db.body_brief().actor().find(&actor);
            let brief_rev = b_row.as_ref().map_or(0, |b| b.revision);
            let brief = b_row
                .filter(|b| !b.goal.is_empty())
                .map(|b| BriefView { revision: b.revision, goal: b.goal, target: b.target, stance: b.stance, risk: b.risk, style: b.style, traits: b.traits, expires_ms: b.expires_ms });
            let sv = SlotView { revision: 1, node: 1, goal: ob.entry.goal.clone(), target: ob.entry.target, skills: ob.entry.skills.clone() };
            if ob.memory.follow(sess.epoch, brief_rev) {
                capture.write("memory", json!({"actor": actor, "epoch": sess.epoch, "brief": brief_rev, "event": "reset", "episode": ob.entry.episode}));
                ob.prev = None;
            }
            let v = encode::encode(&o, brief.as_ref(), &sv);
            let cur_own_act = o.own_fighter.as_ref().filter(|f| f.act != 0 && f.until_ms > now).map_or(0, |f| f.act);
            let cur_had_block = block_code != 0 && cur_own_act == block_code;
            let cur_rooted = cur_own_act != 0 && !cur_had_block;

            // Collect newly accepted skill uses from player-equivalent `my_skill_uses`.
            let mut new_uses: Vec<SkillUse> = sess
                .conn
                .db
                .my_skill_uses()
                .iter()
                .filter(|u| u.actor == actor && u.accepted_ms > 0 && ob.seen_uses.insert(u.id))
                .collect();
            new_uses.sort_by_key(|u| (u.accepted_ms, u.id));

            if let Some(prev) = ob.prev.take() {
                let mut intent = Intent::default();
                let spd = me_body.vx.hypot(me_body.vy);
                if spd > 0.05 {
                    intent.moving = Some((me_body.vx / spd, me_body.vy / spd, me_body.running));
                } else {
                    intent.moving = Some((0.0, 0.0, false));
                }
                let face_ang = me_body.heading + me_body.face_off;
                intent.face = Some((face_ang.cos(), face_ang.sin()));

                let mut out_of_scope: Vec<String> = Vec::new();
                for u in &new_uses {
                    if u.accepted_ms + 80 >= prev.now_ms {
                        if ob.entry.skills.iter().any(|s| s == &u.skill) {
                            if intent.press.is_none() {
                                intent.press = Some((u.skill.clone(), u.target, u.aim_x, u.aim_y));
                            }
                        } else {
                            out_of_scope.push(u.skill.clone());
                        }
                    }
                }
                if intent.press.is_none() && prev.had_block && !cur_had_block {
                    intent.release = Some("block".into());
                }

                // If the authority graph reacted on the exact tick a foe windup started (between
                // `prev.now_ms` and `now`), `prev` predates the windup while `v` (current frame)
                // holds the first player-delivered cue of that windup. Pair the pre-action self
                // state (`prev.encoded[..OWN]`) with the newly arrived perceived scene (`v[OWN..]`)
                // so the observation reflects what a player-path controller perceives before pressing.
                let mut obs_vec = prev.encoded.clone();
                let mut same_tick_cue = false;
                if let Some((sk, ..)) = &intent.press {
                    if (sk == "dodge" || sk == "block") && obs_vec[encode::OWN + 8] <= 0.0 && v[encode::OWN + 8] > 0.0 && v[encode::OWN + 10] > 0.5 {
                        obs_vec[encode::OWN..].copy_from_slice(&v[encode::OWN..]);
                        same_tick_cue = true;
                    }
                }

                let before = ob.memory.flat();
                let encoded_intent = intent.encode(&prev.sv);
                ob.memory.remember(encoded_intent);
                sess.seq += 1;
                let mut flat = obs_vec.clone();
                flat.extend_from_slice(&before);
                capture.write(
                    "decision",
                    json!({
                        "actor": actor, "role": ob.entry.role, "epoch": sess.epoch, "seq": sess.seq, "now_ms": prev.now_ms,
                        "policy": "graph-teacher", "policy_version": ob.entry.teacher,
                        "episode": ob.entry.episode, "opponent_cfg": ob.entry.opponent_cfg,
                        "encoded": obs_vec, "len": encode::LEN, "memory": before, "memory_after": ob.memory.flat(), "flat": flat,
                        "intent_encoded": encoded_intent,
                        "audit": {
                            "target_delivered": obs_vec[encode::OWN] > 0.5,
                            "target_act": obs_vec[encode::OWN + 8],
                            "target_elapsed_s": obs_vec[encode::OWN + 9],
                            "target_at_me": obs_vec[encode::OWN + 10] > 0.5,
                            "same_tick_cue_aligned": same_tick_cue,
                            "obs_age_ms": prev.obs_age_ms,
                            "was_rooted": prev.was_rooted,
                            "out_of_scope_skills": out_of_scope,
                            "teacher": ob.entry.teacher,
                            "episode": ob.entry.episode,
                            "opponent_cfg": ob.entry.opponent_cfg,
                        },
                        "observation": {
                            "body": prev.body_xy.map(|(x, y)| json!([x, y])),
                            "others": prev.others_n, "seen": prev.seen_n, "fighters": prev.fighters_n, "cues": prev.cues_n,
                            "busy_until": prev.busy_until, "age_ms": prev.obs_age_ms,
                        },
                        "slot": {"revision": prev.sv.revision, "node": prev.sv.node, "goal": prev.sv.goal, "target": prev.sv.target, "skills": prev.sv.skills},
                        "brief": prev.brief.as_ref().map(|b| json!({"revision": b.revision, "goal": b.goal, "target": b.target, "stance": b.stance, "risk": b.risk, "style": b.style, "traits": b.traits, "expires_ms": b.expires_ms})),
                        "intent": intent,
                    }),
                );
            }

            ob.prev = Some(PendingObs {
                now_ms: now,
                encoded: v,
                obs_age_ms: o.others.iter().map(|b| now.saturating_sub(b.t_ms)).max(),
                was_rooted: cur_rooted,
                had_block: cur_had_block,
                body_xy: o.here(),
                brief,
                sv,
                others_n: o.others.len(),
                seen_n: o.seen.len(),
                fighters_n: o.fighters.len(),
                cues_n: o.cues.len(),
                busy_until: o.busy_until,
            });
        }
    }
}
