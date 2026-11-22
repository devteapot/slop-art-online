//! The fast lane (docs/FAST_LANE.md): a quick re-plan between blows. The authority issues a
//! `fast_ask` row for a character its mind holds (a blow taken, or the same move seen started at
//! it `seen_again_n` times; the count is the authority's and is never told), under the world's
//! laws for how many and how often. This service answers each issued row with one call on the
//! fast route (`rethink.json` `fast.route`, the `Urgent` lane, purpose `fast`) and one reducer:
//! `mind_patch` (the character's `combat` branch, or one of its own routines, changed) or
//! `mind_fast_done` (kept as it is, no usable answer, off stage, timed out).
//!
//! The prompt holds only the character's own perception and plans: why now (the event as it
//! perceived it), who it is with its own moves' timings, what has just happened, its top level
//! and its routines; the world's rules and the graph grammar. No tactic text. A reply may not
//! speak, act or create routines: that stays with the slow mind.

use super::Minds;
use crate::llm::{self, Attention, Lane, Msg};
use crate::prompts;
use anyhow::{anyhow, Result};
use living_bindings::*;
use serde::Deserialize;
use spacetimedb_sdk::Table;
use serde_json::{json, Value};
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::oneshot;

#[derive(Clone, Debug, Deserialize)]
#[serde(default)]
pub struct Config {
    /// A profile, `profile@effort` or a mix (purpose `fast`).
    pub route: String,
    /// A reply later than this is dropped (journaled as a timeout) and changes nothing.
    pub timeout_ms: u64,
    /// The newest experiences in the prompt.
    pub experiences: usize,
}

impl Default for Config {
    fn default() -> Self {
        Self { route: "deepseek-flash".into(), timeout_ms: 6_000, experiences: 12 }
    }
}

impl Config {
    /// The `fast` section of the rethink gate's file (`LIVING_RETHINK_CONFIG`, else
    /// `living/configs/rethink.json`); the defaults when it has none.
    pub fn load(root: &Path) -> Self {
        let path = std::env::var("LIVING_RETHINK_CONFIG").map(std::path::PathBuf::from).unwrap_or_else(|_| root.join("living/configs/rethink.json"));
        std::fs::read_to_string(&path).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok()).and_then(|v| serde_json::from_value(v["fast"].clone()).ok()).unwrap_or_default()
    }
}

/// What a reply asks for.
enum Change {
    /// `mind_patch` with this target and graph.
    Patch { target: String, graph: String, what: String },
    /// No change, and why.
    Keep(String),
}

impl Minds {
    /// An issued `fast_ask` row: served once (a row updated by the authority for the same issue
    /// is the same request).
    pub(super) fn fast_issued(self: Arc<Self>, ask: FastAsk, callback_ms: Option<u64>) {
        let dispatch_ms = callback_ms.map(|_| llm::now_ms());
        if ask.issued_ms == 0 || !self.allowed(ask.actor) {
            return;
        }
        {
            let mut a = self.actors.lock().unwrap();
            let m = a.entry(ask.actor).or_default();
            if m.fast_issued >= ask.issued_ms {
                return;
            }
            m.fast_issued = ask.issued_ms;
        }
        tokio::spawn(async move {
            let mut trace = callback_ms.zip(dispatch_ms).map(|(callback_ms, dispatch_ms)| json!({
                "actor": ask.actor, "issued_ms": ask.issued_ms, "trigger_ms": ask.trigger_ms,
                "callback_ms": callback_ms, "dispatch_ms": dispatch_ms,
            }));
            let result = self.fast_serve(&ask, trace.as_mut()).await;
            if let Some(mut trace) = trace {
                trace["finished_ms"] = json!(llm::now_ms());
                trace["error"] = json!(result.is_err());
                self.llm.outcome("input_latency_fast", &trace).await;
            }
            if let Err(e) = result {
                log::warn!("fast lane for {}: {e:#}", ask.actor);
            }
        });
    }

    async fn fast_serve(&self, ask: &FastAsk, mut trace: Option<&mut Value>) -> Result<()> {
        let picked_ms = llm::now_ms();
        if let Some(trace) = trace.as_deref_mut() {
            trace["picked_ms"] = json!(picked_ms);
            log::info!("input_latency_pickup {picked_ms} {} {}", ask.actor, ask.issued_ms);
        }
        let actor = ask.actor;
        let Some(c) = self.conn.db.character().id().find(&actor) else { return Ok(()) };
        // Not the mind's now (its person is back, or it died): the authority has dropped the row.
        if !c.alive || !c.ai || c.controller != self.me {
            return Ok(());
        }
        let reference = super::reference(actor, "fast");
        let base = json!({"trigger_ms": ask.trigger_ms, "issued_ms": ask.issued_ms, "picked_ms": picked_ms, "reason": ask.reason});
        // Off stage by the level of detail (`LIVING_LOD`), not merely unwatched: with a staged model
        // mix every character no player watches counts as off stage for model routing, which
        // would leave a fight with no player in sight (an arena) without the lane at all.
        if self.lod.on && self.attention(actor, None) != Attention::OnStage {
            return self.fast_done(actor, ask.issued_ms, "off stage", base, &reference, None).await;
        }
        let fmt = self.fmt_time();
        let experiences: Vec<String> = {
            let all = self.experiences(actor);
            let n = all.len();
            all.iter().skip(n.saturating_sub(self.fast.experiences)).map(|e| self.exp_line(e, &fmt, false)).collect()
        };
        let brain = self.conn.db.brain().id().find(&actor);
        let outline = brain.as_ref().and_then(|b| living_rules::graph::parse(&b.graph).ok()).map(|g| living_rules::graph::outline(&g.root)).unwrap_or_default();
        let plan = brain.as_ref().map(|b| b.plan.clone()).unwrap_or_default();
        let persona = format!("{}{}", self.persona_text(actor), self.own_timings(actor));
        // The frame (`LIVING_FAST_FRAME`); the balanced one also tells how the asker's own body
        // feels, as its think prompt does.
        let f = prompts::fast_frame();
        let felt = if f == prompts::FastFrame::Balanced { self.body_text(actor) } else { String::new() };
        let msgs = vec![
            Msg { role: "system", content: prompts::fast_system_v(f) },
            Msg { role: "user", content: prompts::fast_user_v(f, &ask.reason, &persona, &experiences, &plan, &outline, &self.repertoire_text(actor), &felt) },
        ];
        if let Some(trace) = trace.as_deref_mut() {
            trace["model_start_ms"] = json!(llm::now_ms());
        }
        let call = self.llm.chat_in_lane(&self.fast.route, Attention::OnStage, "fast", &c.name, &msgs, Lane::Fast);
        let reply = match tokio::time::timeout(Duration::from_millis(self.fast.timeout_ms), call).await {
            Err(_) => {
                // A reply past the timeout is dropped: journaled as a timeout, nothing changes.
                self.llm
                    .journal_entry(&c.name, &json!({
                        "at_ms": llm::now_ms(), "actor": c.name, "purpose": "fast", "profile": self.fast.route, "model": null,
                        "latency_ms": self.fast.timeout_ms, "lane": "urgent", "queue_wait_ms": null, "prompt_tokens": null,
                        "completion_tokens": null, "cached_tokens": null, "cost_usd": null, "request": null, "reply": null,
                        "error": format!("timeout after {} ms (fast lane)", self.fast.timeout_ms),
                    }))
                    .await;
                return self.fast_done(actor, ask.issued_ms, "timed out", base, &reference, None).await;
            }
            Ok(Err(e)) => return self.fast_done(actor, ask.issued_ms, &format!("no answer: {e:#}"), base, &reference, None).await,
            Ok(Ok(r)) => r,
        };
        if let Some(trace) = trace.as_deref_mut() {
            trace["model_reply_ms"] = json!(llm::now_ms());
            if let Some((id, at, granted)) = reply.admission_trace {
                trace["admission_id"] = json!(id);
                trace["queue_enter_ms"] = json!(at);
                trace["grant_ms"] = json!(granted);
            }
        }
        let v = llm::parse_json(&reply.content).unwrap_or(Value::Null);
        let thought = v["thought"].as_str().unwrap_or_default().trim().to_string();
        let mut detail = base;
        detail["model_ms"] = json!(reply.latency_ms);
        detail["reply"] = v.clone();
        let routines: Vec<String> = self.conn.db.routine().iter().filter(|r| r.actor == actor).map(|r| living_rules::normalize::routine_name(&r.name)).collect();
        let change = change_of(&v, &routines);
        // Its person may have come back while the model answered.
        if !self.conn.db.character().id().find(&actor).is_some_and(|c| c.alive && c.ai && c.controller == self.me) {
            return Ok(());
        }
        match change {
            Change::Keep(why) => {
                let summary = if thought.is_empty() { why } else { format!("{why}: {thought}") };
                self.fast_done(actor, ask.issued_ms, &summary, detail, &reference, Some(&reply)).await
            }
            Change::Patch { target, graph, what } => {
                detail["sent_ms"] = json!(llm::now_ms());
                let t = ThoughtIn {
                    kind: "fast".into(),
                    summary: if thought.is_empty() { what } else { format!("{thought} → {what}") },
                    detail: detail.to_string(),
                    latency_ms: reply.latency_ms,
                    tokens: reply.tokens,
                    model: reply.model.clone(),
                    reference,
                };
                log::info!("{} fast lane: {}", c.name, t.summary);
                let (tx, rx) = oneshot::channel();
                if let Some(trace) = trace {
                    trace["patch_send_ms"] = json!(llm::now_ms());
                }
                self.conn.reducers.mind_patch_then(actor, target, graph, ask.issued_ms, t, move |_, r| {
                    let _ = tx.send(super::flatten(r));
                })?;
                rx.await?.map_err(|e| anyhow!("mind_patch: {e}"))
            }
        }
    }

    async fn fast_done(&self, actor: u32, issued_ms: u64, summary: &str, detail: Value, reference: &str, reply: Option<&llm::Reply>) -> Result<()> {
        let t = ThoughtIn {
            kind: "fast".into(),
            summary: format!("kept: {summary}"),
            detail: detail.to_string(),
            latency_ms: reply.map_or(0, |r| r.latency_ms),
            tokens: reply.map_or(0, |r| r.tokens),
            model: reply.map(|r| r.model.clone()).unwrap_or_default(),
            reference: reference.to_string(),
        };
        let (tx, rx) = oneshot::channel();
        self.conn.reducers.mind_fast_done_then(actor, issued_ms, t, move |_, r| {
            let _ = tx.send(super::flatten(r));
        })?;
        rx.await?.map_err(|e| anyhow!("mind_fast_done: {e}"))
    }
}

/// What a reply asks for, checked against the character's own routines (normalized names).
fn change_of(v: &Value, routines: &[String]) -> Change {
    let graph_of = |g: &Value| living_rules::graph::from_value_lenient(g.clone()).ok().map(|(g, _)| g.to_json());
    if v["keep"].as_bool() == Some(true) {
        return Change::Keep("as it is".into());
    }
    if v["patch"].is_object() {
        return match graph_of(&v["patch"]["graph"]) {
            Some(graph) => Change::Patch { target: "combat".into(), graph, what: "combat branch rewritten".into() },
            None => Change::Keep("the combat branch it wrote is not a graph".into()),
        };
    }
    if v["routine"].is_object() {
        let name = living_rules::normalize::routine_name(v["routine"]["name"].as_str().unwrap_or_default());
        if !routines.contains(&name) {
            return Change::Keep(format!("it has no routine called {name}"));
        }
        return match graph_of(&v["routine"]["graph"]) {
            Some(graph) => Change::Patch { target: format!("routine:{name}"), graph, what: format!("routine {name} rewritten") },
            None => Change::Keep(format!("routine {name} as written is not a graph")),
        };
    }
    if let Some(name) = v["switch"].as_str() {
        let name = living_rules::normalize::routine_name(name);
        if !routines.contains(&name) {
            return Change::Keep(format!("it has no routine called {name}"));
        }
        return Change::Patch { target: "combat".into(), graph: json!({"routine": name}).to_string(), what: format!("combat branch switched to {name}") };
    }
    Change::Keep("no usable answer".into())
}

/// One saved fast request from a run's journal (`<run>/journal/<name>.jsonl`, purpose `fast`):
/// the system prompt it was sent with (`journal/system/<hash>.txt`) and its user prompt.
struct Saved {
    run: String,
    actor: String,
    idx: usize,
    at_ms: u64,
    system: String,
    user: String,
    reply: Value,
}

/// The saved fast requests of a run, in journal order per character, at most `per_actor` each.
fn saved(dir: &Path, per_actor: usize) -> Result<Vec<Saved>> {
    let mut out = Vec::new();
    let mut files: Vec<_> = std::fs::read_dir(dir.join("journal"))?.filter_map(|e| e.ok()).map(|e| e.path()).filter(|p| p.extension().is_some_and(|x| x == "jsonl")).collect();
    files.sort();
    for f in files {
        let mut n = 0;
        for line in std::fs::read_to_string(&f)?.lines() {
            let Ok(r) = serde_json::from_str::<Value>(line) else { continue };
            if r["purpose"] != "fast" || r["request"].is_null() || r["reply"].is_null() {
                continue;
            }
            let msgs = &r["request"]["messages"];
            let (Some(sref), Some(user)) = (msgs[0]["content_ref"].as_str(), msgs[1]["content"].as_str()) else { continue };
            let system = std::fs::read_to_string(dir.join("journal").join(sref))?;
            if n >= per_actor {
                break;
            }
            out.push(Saved {
                run: dir.file_name().map(|x| x.to_string_lossy().to_string()).unwrap_or_default(),
                actor: r["actor"].as_str().unwrap_or_default().to_string(),
                idx: n,
                at_ms: r["at_ms"].as_u64().unwrap_or(0),
                system,
                user: user.to_string(),
                reply: llm::parse_json(r["reply"].as_str().unwrap_or_default()).unwrap_or(Value::Null),
            });
            n += 1;
        }
    }
    Ok(out)
}

/// The routines a saved user prompt lists (`## name — …` under Your routines), normalized.
fn routines_in(user: &str) -> Vec<String> {
    let Some(rest) = user.split("\n# Your routines\n").nth(1) else { return Vec::new() };
    let section = rest.split("\n# Why now").next().unwrap_or_default();
    section.lines().filter_map(|l| l.strip_prefix("## ")).map(|l| living_rules::normalize::routine_name(l.split(" — ").next().unwrap_or(l))).collect()
}

/// A reply as the live fast lane would take it: what it changes, and the graph it would send.
fn replay_row(v: &Value, routines: &[String]) -> Value {
    match change_of(v, routines) {
        Change::Keep(why) => json!({"change": if v["keep"].as_bool() == Some(true) { "keep" } else { "unusable" }, "why": why}),
        Change::Patch { target, graph, what } => {
            let kind = if v["patch"].is_object() { "patch" } else if v["routine"].is_object() { "routine" } else { "switch" };
            json!({"change": kind, "target": target, "graph": serde_json::from_str::<Value>(&graph).unwrap_or(Value::Null), "what": what})
        }
    }
}

/// `living-mind fast-replay --frame first|balanced --out FILE [--per-actor K] [--limit N]
/// [--concurrency C] [--route PROFILE] [--prompts-only | --guard-ready FILE [--guard-wait-s S]]
/// RUN_DIR...`: the fast lane's saved
/// requests sent again, in the first or the balanced frame (docs/FAST_LANE_FRAME.md). The first
/// frame sends each saved system prompt as it was; the balanced one swaps only its frame text,
/// so the world's rules and the grammar are the saved bytes in both arms, and the user prompt is
/// the saved one in both (a saved request has no felt body, so How you are now is not given).
/// `--prompts-only` writes the prompts and makes no call. Calls go to the fast route (or
/// `--route`) through the models config (`LIVING_MODELS`), journaled under `<out>.journal/`, and
/// only once the spend guard's `--guard-ready` file exists (or `LIVING_REPLAY_UNGUARDED=1`).
pub async fn replay_main(root: &Path, args: Vec<String>) -> Result<()> {
    let mut f = None;
    let (mut out, mut per_actor, mut limit, mut conc, mut route, mut prompts_only, mut dirs) = (None, usize::MAX, usize::MAX, 8usize, None, false, Vec::new());
    let (mut guard_ready, mut guard_wait_s) = (None, 120u64);
    let mut it = args.into_iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--frame" => f = Some(prompts::FastFrame::parse(Some(it.next().as_deref().unwrap_or("?"))).map_err(anyhow::Error::msg)?),
            "--guard-ready" => guard_ready = it.next().map(std::path::PathBuf::from),
            "--guard-wait-s" => guard_wait_s = it.next().and_then(|x| x.parse().ok()).unwrap_or(120),
            "--out" => out = it.next().map(std::path::PathBuf::from),
            "--per-actor" => per_actor = it.next().and_then(|x| x.parse().ok()).unwrap_or(usize::MAX),
            "--limit" => limit = it.next().and_then(|x| x.parse().ok()).unwrap_or(usize::MAX),
            "--concurrency" => conc = it.next().and_then(|x| x.parse().ok()).unwrap_or(8),
            "--route" => route = it.next(),
            "--prompts-only" => prompts_only = true,
            d => dirs.push(std::path::PathBuf::from(d)),
        }
    }
    let out = out.ok_or_else(|| anyhow!("--out FILE is required"))?;
    // Named every time: a replay of the first frame must say so now that balanced is the default.
    let f = f.ok_or_else(|| anyhow!("--frame first|balanced is required"))?;
    if !prompts_only {
        // Paid calls only under a watching spend guard: the journal folder exists first, and no
        // call is made until the guard's ready file does (act_trial.py watch --ready).
        let journal = out.with_extension("journal");
        std::fs::create_dir_all(&journal)?;
        match &guard_ready {
            Some(ready) => {
                let deadline = std::time::Instant::now() + Duration::from_secs(guard_wait_s);
                println!("waiting for the spend guard ({}) on {}", ready.display(), journal.display());
                while !ready.exists() {
                    if std::time::Instant::now() > deadline {
                        return Err(anyhow!("no spend guard ready at {} within {guard_wait_s} s: no call made", ready.display()));
                    }
                    tokio::time::sleep(Duration::from_millis(200)).await;
                }
            }
            None if std::env::var("LIVING_REPLAY_UNGUARDED").as_deref() == Ok("1") => log::warn!("fast-replay: no spend guard (LIVING_REPLAY_UNGUARDED=1)"),
            None => return Err(anyhow!("model calls need --guard-ready FILE (act_trial.py watch --ready on {}), or LIVING_REPLAY_UNGUARDED=1; --prompts-only makes none", journal.display())),
        }
    }
    prompts::set_rules(1, include_str!("../../../scripts/skills.rhai"));
    let first = prompts::fast_frame_text(prompts::FastFrame::First, prompts::frame());
    let mine = prompts::fast_frame_text(f, prompts::frame());
    let mut items = Vec::new();
    for d in &dirs {
        items.extend(saved(d, per_actor)?);
    }
    items.truncate(limit);
    // The saved system prompts must open with the first frame's text exactly: only then is
    // swapping the frame all that differs.
    for s in &items {
        if !s.system.starts_with(&first) {
            return Err(anyhow!("{} {}#{}: its saved system prompt does not open with this build's first frame; not replayed", s.run, s.actor, s.idx));
        }
    }
    let route = route.unwrap_or_else(|| Config::load(root).route);
    let llm = if prompts_only {
        None
    } else {
        let models: llm::ModelsFile = serde_json::from_str(&std::fs::read_to_string(std::env::var("LIVING_MODELS").map(std::path::PathBuf::from).unwrap_or_else(|_| root.join("living/configs/models.json")))?)?;
        let journal = out.with_extension("journal");
        std::fs::create_dir_all(&journal)?;
        Some(Arc::new(llm::Llm::new(models, journal)?))
    };
    let sem = Arc::new(tokio::sync::Semaphore::new(conc.max(1)));
    let mut tasks = tokio::task::JoinSet::new();
    for s in items {
        let system = format!("{mine}{}", &s.system[first.len()..]);
        let (llm, sem, route) = (llm.clone(), sem.clone(), route.clone());
        tasks.spawn(async move {
            let routines = routines_in(&s.user);
            let mut row = json!({"run": s.run, "actor": s.actor, "idx": s.idx, "at_ms": s.at_ms, "frame": f.name(),
                "saved": replay_row(&s.reply, &routines), "system_chars": system.len(), "user_chars": s.user.len()});
            let Some(llm) = llm else {
                row["system"] = json!(system);
                row["user"] = json!(s.user);
                return row;
            };
            let _permit = sem.acquire().await;
            let msgs = vec![Msg { role: "system", content: system }, Msg { role: "user", content: s.user.clone() }];
            match llm.chat_in_lane(&route, Attention::OnStage, "fast", &s.actor, &msgs, Lane::Fast).await {
                Ok(r) => {
                    let v = llm::parse_json(&r.content).unwrap_or(Value::Null);
                    row["reply"] = v.clone();
                    row["model"] = json!(r.model);
                    row["latency_ms"] = json!(r.latency_ms);
                    row["replayed"] = replay_row(&v, &routines);
                }
                Err(e) => row["error"] = json!(format!("{e:#}")),
            }
            row
        });
    }
    let mut rows = Vec::new();
    while let Some(r) = tasks.join_next().await {
        rows.push(r?);
    }
    rows.sort_by(|a, b| (a["run"].as_str(), a["actor"].as_str(), a["idx"].as_u64()).cmp(&(b["run"].as_str(), b["actor"].as_str(), b["idx"].as_u64())));
    std::fs::write(&out, rows.iter().map(|r| format!("{r}\n")).collect::<String>())?;
    let count = |k: &str| rows.iter().filter(|r| r["replayed"]["change"] == k).count();
    println!("{} requests in frame {}: keep {}, patch {}, routine {}, switch {}, unusable {}, failed {} → {}",
        rows.len(), f.name(), count("keep"), count("patch"), count("routine"), count("switch"), count("unusable"), rows.iter().filter(|r| !r["error"].is_null()).count(), out.display());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_reply_changes_only_what_it_may() {
        let mine = vec!["stay safe".to_string()];
        assert!(matches!(change_of(&json!({"keep": true}), &mine), Change::Keep(_)));
        match change_of(&json!({"patch": {"label": "combat", "graph": {"do": "dodge"}}}), &mine) {
            Change::Patch { target, .. } => assert_eq!(target, "combat"),
            _ => panic!("a patch"),
        }
        match change_of(&json!({"switch": "Stay safe"}), &mine) {
            Change::Patch { target, graph, .. } => assert!(target == "combat" && graph.contains("stay safe"), "{graph}"),
            _ => panic!("a switch to its own routine"),
        }
        // A routine it does not have is neither switched to nor written.
        assert!(matches!(change_of(&json!({"switch": "win the fight"}), &mine), Change::Keep(_)));
        assert!(matches!(change_of(&json!({"routine": {"name": "win the fight", "graph": {"do": "dodge"}}}), &mine), Change::Keep(_)));
        assert!(matches!(change_of(&json!({"say": "hello"}), &mine), Change::Keep(_)));
    }

    #[test]
    fn the_prompt_has_no_count_and_no_tactic() {
        // What the repeat trigger contributes is the event as perceived: no count, no "again".
        let reason = "A stranger winds up an attack at you";
        let user = prompts::fast_user(reason, "Wren", &["A stranger attacked you (9 damage)".into()], "walk to town", "first: …", "- stay safe");
        // The stable parts come first, for the providers' prefix caches; why now and what has just
        // happened come last.
        assert!(user.starts_with("# Who you are\nWren") && user.find("# Your routines") < user.find("# Why now"), "{user}");
        let why = user.split("# Why now").nth(1).unwrap().split("# What has just happened").next().unwrap();
        assert!(!why.contains("again") && !why.chars().any(|c| c.is_ascii_digit()), "{why}");
        // The rules text keeps its own words ("ready again 900 ms"); nothing counts anyone's moves.
        for text in [&user, &prompts::fast_system(), &prompts::fast_system_v(prompts::FastFrame::First)] {
            assert!(!regex_like_count(text), "a count in the fast lane's prompt");
            for tactic in ["dodge on", "when they wind up", "counter"] {
                assert!(!text.to_lowercase().contains(tactic), "tactic text {tactic:?} in the fast lane's prompt");
            }
        }
    }

    #[test]
    fn the_balanced_frame_is_the_default_and_the_first_stays_selectable() {
        assert_eq!(prompts::FastFrame::parse(None), Ok(prompts::FastFrame::Balanced));
        assert_eq!(prompts::FastFrame::parse(Some("")), Ok(prompts::FastFrame::Balanced));
        assert_eq!(prompts::FastFrame::parse(Some("first")), Ok(prompts::FastFrame::First));
        assert!(prompts::FastFrame::parse(Some("balance")).is_err(), "a misspelt frame stops the service");
        // The default system prompt is the balanced frame's. (The rules text after the frame is
        // global state other tests change: compared on real journals by `fast-replay`, whose first
        // arm sends each saved system prompt unchanged.)
        assert_eq!(prompts::fast_frame(), prompts::FastFrame::Balanced);
        assert!(prompts::fast_system().starts_with(&prompts::fast_frame_text(prompts::FastFrame::Balanced, prompts::frame())));
        // The first frame is unchanged by this branch: the replicates' and the frame trial's words.
        assert!(prompts::fast_system_v(prompts::FastFrame::First).starts_with(&prompts::fast_frame_text(prompts::FastFrame::First, prompts::frame())));
        let exps = vec!["A stranger attacked you (9 damage)".to_string()];
        let old = prompts::fast_user("A stranger winds up a strike at you", "Wren", &exps, "test", " 0 first", "- stay safe");
        assert_eq!(prompts::fast_user_v(prompts::FastFrame::First, "A stranger winds up a strike at you", "Wren", &exps, "test", " 0 first", "- stay safe", "badly hurt"), old, "the first frame tells no felt body");
        let balanced = prompts::fast_user_v(prompts::FastFrame::Balanced, "A stranger winds up a strike at you", "Wren", &exps, "test", " 0 first", "- stay safe", "badly hurt");
        assert_eq!(balanced, format!("{old}\n# How you are now\nHow your body feels: badly hurt\n"));
        assert_eq!(prompts::fast_user_v(prompts::FastFrame::Balanced, "x", "Wren", &exps, "test", " 0 first", "", " "), prompts::fast_user("x", "Wren", &exps, "test", " 0 first", ""), "nothing said of a body not known");
    }

    #[test]
    fn the_balanced_frame_shows_six_ways_alike() {
        prompts::set_rules(1, include_str!("../../../scripts/skills.rhai"));
        // Only the frame differs: both are the frame, then the world's rules and the grammar.
        let f2 = prompts::fast_frame_text(prompts::FastFrame::Balanced, prompts::frame());
        let balanced = prompts::fast_system_v(prompts::FastFrame::Balanced);
        assert!(balanced.starts_with(&format!("{f2}\n\n")), "the balanced system prompt opens with its frame");
        // The fake model still knows it as a fast request (fake_llm.py `purpose_of`).
        assert!(f2.contains("Something has just happened to you (see Why now)"));
        // Every way is shown, each a legal line ahead of a fight, none much longer than another.
        let lens: Vec<usize> = prompts::FAST_WAYS.iter().map(|(_, l)| l.len()).collect();
        assert!(lens.iter().max().unwrap() - lens.iter().skip(1).min().unwrap() < 60, "{lens:?}");
        for (name, line) in prompts::FAST_WAYS.iter() {
            assert!(f2.contains(&format!("- {name}: {line}")), "{name}");
            let v: Value = serde_json::from_str(line).unwrap();
            if v.get("keep").is_some() {
                assert!(matches!(change_of(&v, &[]), Change::Keep(_)));
                continue;
            }
            let fight = json!({"first": [v, {"do": "strike", "target": {"nearest": "person"}}]});
            let (_, warnings) = living_rules::normalize::graph(fight.clone()).unwrap_or_else(|e| panic!("{name}: {e}"));
            assert!(warnings.is_empty(), "{name}: {warnings:?}");
            assert!(matches!(change_of(&json!({"patch": {"label": "combat", "graph": fight}}), &[]), Change::Patch { .. }), "{name}");
        }
        // Keeping comes first among the replies, as among the ways.
        let replies = f2.split("Reply with ONE JSON object, one of:\n").nth(1).unwrap();
        assert!(replies.starts_with("{\"keep\": true"), "{replies}");
        // The triggering event is set apart from what else is perceived.
        assert!(f2.contains("Why now is that one event as you perceived it"));
        assert!(f2.contains("Your `combat` branch stays as it is unless you change it."));
    }

    /// The prompt audit (docs/FAST_LANE_FRAME.md): outside the six shared ways, the balanced
    /// frame adds no word of fighting or of getting away, and no advice.
    #[test]
    fn the_balanced_frame_adds_no_tactic_beyond_the_shared_ways() {
        let mut f2 = prompts::fast_frame_text(prompts::FastFrame::Balanced, prompts::frame());
        for (name, line) in prompts::FAST_WAYS.iter() {
            f2 = f2.replace(&format!("- {name}: {line}"), "");
        }
        // Counted against the first frame's own text: the balanced one may say no such word more often.
        let f1 = prompts::fast_frame_text(prompts::FastFrame::First, prompts::frame());
        let (lower, before) = (f2.to_lowercase(), f1.to_lowercase());
        for word in ["strike", "block", "dodge", "flee", "back_off", "back off", "retreat", "escape", "run away", "safe", "survive", "danger", "should", "better", "best", "must", "wise", "outrun", "miss", "attacker", "enemy", "opening", "counter", "windup", "win", "lose", "kill", "hurt", "health", "breath", "stamina"] {
            assert!(lower.matches(word).count() <= before.matches(word).count(), "{word:?} added outside the shared ways: {f2}");
        }
        // The first frame's own words are unchanged by this branch (the replicates' and the frame trial's).
        assert!(f1.contains("You may rewrite your `combat` branch, rewrite one of the routines listed under Your routines, switch your `combat` branch to one of them, or keep everything as it is."));
    }

    #[test]
    fn a_saved_prompt_lists_its_routines() {
        let user = "# Who you are\nW\n\n# Your routines\n## stay safe — not tried yet [habit (forager)]\n 0 first\n## Be With People — tried 2 times\n\n# Why now\nx\n";
        assert_eq!(routines_in(user), vec!["stay safe".to_string(), living_rules::normalize::routine_name("Be With People")]);
    }

    fn regex_like_count(t: &str) -> bool {
        t.contains("times now") || t.contains("(×") || t.contains("for the third time")
    }
}
