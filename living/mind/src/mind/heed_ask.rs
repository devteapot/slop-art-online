//! E3's model arms (docs/ATTENTION_E3.md): `living-mind heed-replay --ask mind|jev`.
//!
//! - `--ask mind` (arm b): for each frozen state, the subject's own recorded think prompt (its
//!   memory, cues, stances and the scene it saw, byte for byte from the run's journal) with one
//!   section added that asks for its heed policy, sent once on the subject's own recorded compile
//!   route through the mind's `Llm` (journaled, purpose `heed`). The reply's `heed` field is
//!   validated by the shared grammar; `policies.jsonl` feeds `heed-replay --policies`.
//! - `--ask jev` (arm c): for each state, at its moment and every `--every` seconds (5 calls in a
//!   30 s window by default), one TypeSafe `systemone` request whose state is what that subject
//!   perceives then (from the fields: the heeded per the instinct's replay, the next nearest it
//!   can make out, the throngs) and whose questions are a `choice` over the handles; the picks feed
//!   `heed-replay --chosen` through the instinct's `chosen` rule.
//!
//! Both write every request under `<out>.journal/` (the guard's `--journal`). `--prompts-only`
//! writes the requests and their estimated tokens and calls nothing. Models and keys: `--ask mind`
//! reads `LIVING_MODELS` (else living/configs/models.json); `--ask jev` reads the Jev provider of
//! living/configs/rethink.json, its key from that provider's `key_env`, its URL overridable with
//! `LIVING_HEED_JEV_URL` (the fake server), and its price from the local prices file only.

use crate::llm::{self, Attention, Lane, Llm, Msg};
use anyhow::{anyhow, Context, Result};
use living_rules::heed::{self, Known};
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// The heading that marks the heed request in a prompt (the fake server's rules match it).
pub const HEED_HEADING: &str = "# Whom you keep track of (answer this now)";

/// The section added to a subject's own think prompt. Placeholders only: no one named, no
/// tactic, no role (`the_heed_field_names_no_one`).
pub fn heed_field(capacity: usize) -> String {
    format!(
        "{HEED_HEADING}\n\
You can keep track of about {capacity} others at once as individuals; everyone else you see is a throng, counted but not told apart. \
Whoever you are acting on, and whoever's blow has just reached you, you always see. The rest is yours to choose.\n\
Reply with only a JSON object {{\"heed\": [rules]}}, nothing else. Rules are read in order; each takes the creatures in sight its condition holds for, up to its \"take\", until your places are full.\n\
A rule: {{\"if\": condition, \"order\": \"nearest|closing|newest|longest\", \"take\": a number or \"rest\", \"hold_s\": seconds to keep what it took after it stops holding, \"why\": \"your own words\"}}, \
or {{\"score\": [{{\"if\": condition, \"w\": weight}}, ...], \"take\": ..., \"hold_s\": ..., \"why\": ...}} to weigh several conditions.\n\
Conditions about the one considered: {{\"who\": an id you see, a kind, or {{\"kind\": ..., \"relation\": \"friend|enemy|stranger|family|community|any\"}}}}, \
{{\"threatened\": true}}, {{\"doing\": {{\"is\": a skill or a kind word, \"phase\": \"winding up|about to release|releasing|recovering|holding|under way\", \"at_me\": true}}}}, \
{{\"attacker\": {{\"within_s\": s}}}}, {{\"addressing\": {{\"within_s\": s}}}}, {{\"near\": metres}}, {{\"cued\": true}}, {{\"chosen\": true}}, {{\"heeded_s\": {{\"above\": s}}}}, \
{{\"closing\": {{\"above\": m/s}}}}, {{\"fighting\": true}}, {{\"fallen\": true}}, {{\"acting_on_heeded\": true}}, {{\"new\": s}}, {{\"loud\": true}}, {{\"lit\": true}}, \
{{\"self\": one of your own: health, energy, hunger, stamina (above/below), night, hurt_within}}, {{\"count\": {{\"of\": a kind, \"within\": metres, \"at_least\": n}}}}, and all/any/not.\n\
At most 12 rules. The form only, with placeholders: {{\"if\": {{\"who\": \"<a kind>\"}}, \"take\": 2, \"why\": \"<your words>\"}}, \
{{\"if\": {{\"all\": [{{\"who\": <an id>}}, {{\"doing\": {{\"is\": \"<a skill>\"}}}}]}}, \"why\": \"<your words>\"}}, \
{{\"score\": [{{\"if\": <a condition>, \"w\": 2}}, {{\"if\": <another>, \"w\": 1}}], \"take\": \"rest\", \"hold_s\": 3, \"why\": \"<your words>\"}}."
    )
}

fn arg(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned()
}

fn run_dir(src: &Path, st: &Value) -> PathBuf {
    // A state frozen from a named recording (`attention_e3.py freeze --battle-run`, E5) carries its folder.
    if let Some(d) = st["dir"].as_str().filter(|d| !d.is_empty()) {
        return PathBuf::from(d);
    }
    let run = st["run"].as_str().unwrap_or_default();
    if st["kind"] == "battle" {
        src.join(".local/living/verify").join(run)
    } else {
        src.join(".local/living/trials").join(run)
    }
}

/// The subject's recorded think call at the state's moment: (system, user, profile).
fn recorded_think(src: &Path, st: &Value) -> Result<(String, String, String)> {
    let dir = run_dir(src, st).join("journal");
    let file = dir.join(st["journal"].as_str().unwrap_or_default());
    let at = st["t_ms"].as_u64().unwrap_or(0);
    for line in std::io::BufReader::new(std::fs::File::open(&file).with_context(|| file.display().to_string())?).lines() {
        let e: Value = serde_json::from_str(&line?)?;
        if e["purpose"] != "think" || e["at_ms"].as_u64() != Some(at) {
            continue;
        }
        let msgs = e["request"]["messages"].as_array().ok_or_else(|| anyhow!("no messages"))?;
        let mut system = String::new();
        let mut user = String::new();
        for m in msgs {
            let text = match (m.get("content").and_then(|c| c.as_str()), m.get("content_ref").and_then(|c| c.as_str())) {
                (Some(c), _) => c.to_string(),
                (None, Some(r)) => std::fs::read_to_string(dir.join(r)).with_context(|| format!("system prompt {r}"))?,
                _ => String::new(),
            };
            if m["role"] == "system" {
                system = text;
            } else {
                user = text;
            }
        }
        return Ok((system, user, e["profile"].as_str().unwrap_or("glm-flash").to_string()));
    }
    Err(anyhow!("no think call at {at} in {}", file.display()))
}

/// The subject's recorded compile route (its `deliberate` profile), else its think route.
fn recorded_route(src: &Path, st: &Value, think: &str) -> String {
    let file = run_dir(src, st).join("journal").join(st["journal"].as_str().unwrap_or_default());
    if let Ok(f) = std::fs::File::open(file) {
        for line in std::io::BufReader::new(f).lines().map_while(|l| l.ok()) {
            if let Ok(e) = serde_json::from_str::<Value>(&line) {
                if e["purpose"] == "deliberate" {
                    if let Some(p) = e["profile"].as_str() {
                        return p.to_string();
                    }
                }
            }
        }
    }
    think.to_string()
}

fn json_object(text: &str) -> Option<Value> {
    let (a, b) = (text.find('{')?, text.rfind('}')?);
    serde_json::from_str(&text[a..=b]).ok()
}

/// One line per state: the policy asked for and what came of it.
async fn ask_mind(root: &Path, src: &Path, states: Vec<Value>, out: &Path, prompts_only: bool, route_override: Option<String>, conc: usize) -> Result<()> {
    let models: llm::ModelsFile = serde_json::from_str(&std::fs::read_to_string(std::env::var("LIVING_MODELS").map(PathBuf::from).unwrap_or_else(|_| root.join("living/configs/models.json")))?)?;
    let journal = out.with_extension("journal");
    std::fs::create_dir_all(&journal)?;
    let llm = Arc::new(Llm::new(models, journal)?);
    let sem = Arc::new(tokio::sync::Semaphore::new(conc.max(1)));
    let mut tasks = tokio::task::JoinSet::new();
    for st in states {
        let (llm, sem, src, route_override) = (llm.clone(), sem.clone(), src.to_path_buf(), route_override.clone());
        tasks.spawn(async move {
            let id = st["state"].as_str().unwrap_or_default().to_string();
            let (system, user, think_route) = match recorded_think(&src, &st) {
                Ok(x) => x,
                Err(e) => return json!({"state": id, "error": format!("{e:#}")}),
            };
            let route = route_override.unwrap_or_else(|| recorded_route(&src, &st, &think_route));
            let cap = st["capacity"].as_u64().unwrap_or(10) as usize;
            let user = format!("{user}\n\n{}", heed_field(cap));
            let est = (system.len() + user.len()) / 3;
            if prompts_only {
                return json!({"state": id, "route": route, "system_chars": system.len(), "user_chars": user.len(), "est_prompt_tokens": est, "user_tail": user.chars().rev().take(2400).collect::<Vec<_>>().into_iter().rev().collect::<String>()});
            }
            let _permit = sem.acquire().await;
            let msgs = [Msg { role: "system", content: system }, Msg { role: "user", content: user }];
            let name = format!("heed-{id}");
            match llm.chat_in_lane(&route, Attention::OnStage, "heed", &name, &msgs, Lane::Routine).await {
                Ok(r) => {
                    let v = json_object(&r.content);
                    let heed_v = v.as_ref().and_then(|v| v.get("heed").cloned());
                    let seen: HashSet<u32> = scene_ids(&msgs[1].content);
                    let verdict = match &heed_v {
                        None => Err("the reply has no `heed` field".to_string()),
                        Some(h) => heed::parse_value(h, &Known { met: &|i| seen.contains(&i), kind: &|k| ["person", "wolf", "deer", "animal"].contains(&k) }).map(|p| p.rules.len()),
                    };
                    json!({"state": id, "route": route, "model": r.model, "heed": heed_v, "rules": verdict.as_ref().ok(), "refusal": verdict.err(), "tokens": r.tokens, "latency_ms": r.latency_ms})
                }
                Err(e) => json!({"state": id, "route": route, "error": format!("{e:#}")}),
            }
        });
    }
    let mut rows = Vec::new();
    while let Some(r) = tasks.join_next().await {
        rows.push(r?);
    }
    rows.sort_by(|a, b| a["state"].as_str().cmp(&b["state"].as_str()));
    write_rows(out, &rows)?;
    let ok = rows.iter().filter(|r| r["rules"].is_number()).count();
    let refused = rows.iter().filter(|r| r["refusal"].is_string()).count();
    let errors = rows.iter().filter(|r| r["error"].is_string()).count();
    eprintln!("heed-replay --ask mind: {} states, {ok} valid policies, {refused} refused, {errors} errors -> {}", rows.len(), out.display());
    Ok(())
}

/// Ids the scene in a prompt lists (`"id":N` under "What you perceive right now").
fn scene_ids(user: &str) -> HashSet<u32> {
    let head = "# What you perceive right now\n";
    let Some(i) = user.find(head) else { return HashSet::new() };
    let rest = &user[i + head.len()..];
    let line = rest.split('\n').next().unwrap_or("");
    let Ok(v) = serde_json::from_str::<Value>(line) else { return HashSet::new() };
    v["creatures"].as_array().map(|a| a.iter().filter_map(|c| c["id"].as_u64().map(|x| x as u32)).collect()).unwrap_or_default()
}

fn dir_word(dx: f32, dy: f32) -> &'static str {
    let a = dy.atan2(dx).to_degrees();
    let a = (a + 360.0) % 360.0;
    ["east", "northeast", "north", "northwest", "west", "southwest", "south", "southeast"][(((a + 22.5) / 45.0) as usize) % 8]
}

fn dist_word(d: f32) -> &'static str {
    if d <= 2.0 {
        "within reach"
    } else if d <= 8.0 {
        "close"
    } else if d <= 20.0 {
        "a stone's throw"
    } else {
        "far"
    }
}

/// What the subject perceives at a step, as Jev's state: the heeded, the next nearest, the
/// throngs; and the handles' ids.
fn jev_state(cands: &[Value], heeded: &HashSet<u32>, family: &HashSet<u32>, capacity: usize) -> (Value, Vec<(String, u32)>) {
    let mut cs: Vec<&Value> = cands.iter().collect();
    cs.sort_by(|a, b| a["dist"].as_f64().unwrap_or(0.0).total_cmp(&b["dist"].as_f64().unwrap_or(0.0)));
    let mut handles = Vec::new();
    let mut heeded_v = Vec::new();
    let mut also = Vec::new();
    let mut rest = Vec::new();
    let describe = |c: &Value, h: &str| {
        let mut o = json!({"h": h, "who": if c["kind"] == "person" { "a person" } else { c["kind"].as_str().unwrap_or("a creature") }, "dist": dist_word(c["dist"].as_f64().unwrap_or(0.0) as f32)});
        if let Some(d) = c.get("doing").filter(|d| d.is_object()) {
            let is = d["is"].as_array().and_then(|a| a.first()).and_then(|x| x.as_str()).unwrap_or("");
            o["visibly"] = json!(format!("{is}{}, {}", if d["at_me"] == true { " at you" } else { "" }, d["phase"].as_str().unwrap_or("")));
        }
        if c["closing"].as_f64().unwrap_or(0.0) > 1.0 {
            o["moving"] = json!("toward you");
        }
        o
    };
    for c in cs {
        let id = c["id"].as_u64().unwrap_or(0) as u32;
        if heeded.contains(&id) && heeded_v.len() < capacity.max(1) * 2 {
            let h = format!("c{}", handles.len() + 1);
            heeded_v.push(describe(c, &h));
            handles.push((h, id));
        } else if also.len() < 14 && c["made_out"] != false {
            let h = format!("c{}", handles.len() + 1);
            also.push(describe(c, &h));
            handles.push((h, id));
        } else {
            rest.push(c);
        }
    }
    // The throngs: the rest, by direction (no ids, no handles).
    let mut by: BTreeMap<&str, usize> = BTreeMap::new();
    for c in &rest {
        let _ = c;
        *by.entry("around you").or_default() += 1;
    }
    let throngs: Vec<Value> = by.into_iter().map(|(w, n)| json!({"where": w, "about": n})).collect();
    let people: Vec<String> = handles.iter().filter(|(_, id)| family.contains(id)).map(|(h, _)| h.clone()).collect();
    let _ = dir_word;
    let state = json!({
        "note": "Everything here is this character's own perception and ties; it keeps track of only some of these as individuals.",
        "heeded_now": heeded_v, "also_in_sight": also, "throngs": throngs, "your_people": people,
    });
    (state, handles)
}

async fn ask_jev(root: &Path, states: Vec<Value>, fields: &Path, picks: &Path, out: &Path, prompts_only: bool, every: f32, conc: usize) -> Result<()> {
    let file: Value = serde_json::from_str(&std::fs::read_to_string(root.join("living/configs/rethink.json"))?)?;
    let provider = &file["jev"]["provider"];
    let model = provider["model"].as_str().unwrap_or("jev-1.14.0").to_string();
    let url = std::env::var("LIVING_HEED_JEV_URL").ok().filter(|u| !u.is_empty()).unwrap_or_else(|| provider["url"].as_str().unwrap_or_default().to_string());
    let prices = crate::prices::Prices::load(root)?;
    if !prompts_only && prices.input_usd_per_m(&model).is_none() && !url.starts_with("http://127.0.0.1") {
        return Err(anyhow!("no local price for {model}: stop rule 3 (no price, no Jev)"));
    }
    let key = if prompts_only { String::new() } else { std::env::var(provider["key_env"].as_str().unwrap_or("TYPESAFE_API_KEY")).unwrap_or_default() };
    // The instinct's heeded set at each step (arm a's picks), and the fields.
    let mut heeded_at: HashMap<(String, i64), HashSet<u32>> = HashMap::new();
    for line in std::io::BufReader::new(std::fs::File::open(picks).with_context(|| picks.display().to_string())?).lines() {
        let r: Value = serde_json::from_str(&line?)?;
        let t = (r["t"].as_f64().unwrap_or(0.0) * 1000.0).round() as i64;
        let ids = r["picks"].as_array().map(|a| a.iter().filter_map(|p| p[0].as_u64().map(|x| x as u32)).collect()).unwrap_or_default();
        heeded_at.insert((r["state"].as_str().unwrap_or_default().to_string(), t), ids);
    }
    let want: HashMap<String, Value> = states.into_iter().map(|s| (s["state"].as_str().unwrap_or_default().to_string(), s)).collect();
    let journal = out.with_extension("journal");
    std::fs::create_dir_all(&journal)?;
    let models: llm::ModelsFile = serde_json::from_str(&std::fs::read_to_string(std::env::var("LIVING_MODELS").map(PathBuf::from).unwrap_or_else(|_| root.join("living/configs/models.json")))?)?;
    let llm = Arc::new(Llm::new(models, journal)?);
    let http = reqwest::Client::builder().timeout(std::time::Duration::from_secs(20)).build()?;
    let sem = Arc::new(tokio::sync::Semaphore::new(conc.clamp(1, 4)));
    let mut tasks = tokio::task::JoinSet::new();
    for line in std::io::BufReader::new(std::fs::File::open(fields).with_context(|| fields.display().to_string())?).lines() {
        let f: Value = serde_json::from_str(&line?)?;
        let id = f["state"].as_str().unwrap_or_default().to_string();
        if !want.contains_key(&id) {
            continue;
        }
        let steps = f["steps"].as_array().cloned().unwrap_or_default();
        let family: HashSet<u32> = steps.iter().flat_map(|s| s["cands"].as_array().cloned().unwrap_or_default()).filter(|c| c["relations"].as_u64().unwrap_or(0) & 1 != 0).filter_map(|c| c["id"].as_u64().map(|x| x as u32)).collect();
        let cap = want[&id]["capacity"].as_u64().unwrap_or(10) as usize;
        let mut t = 0.0f32;
        while t <= 30.0 - every + 1e-3 {
            let Some(step) = steps.iter().filter(|s| s["t"].as_f64().unwrap_or(-99.0) as f32 <= t + 1e-3).last().cloned() else { break };
            let st_ms = (step["t"].as_f64().unwrap_or(0.0) * 1000.0).round() as i64;
            let heeded = heeded_at.get(&(id.clone(), st_ms)).cloned().unwrap_or_default();
            let cands = step["cands"].as_array().cloned().unwrap_or_default();
            let (state, handles) = jev_state(&cands, &heeded, &family, cap);
            let mut options: serde_json::Map<String, Value> = handles.iter().map(|(h, _)| (h.clone(), json!(format!("the one shown as {h}")))).collect();
            options.insert("no one".into(), json!("no one here"));
            let mut questions = json!({
                "q_matter": {"type": "choice", "instructions": "Who here is about to matter to this character?", "criteria": Value::Object(options.clone())}
            });
            if state["your_people"].as_array().is_some_and(|a| !a.is_empty()) {
                questions["q_people"] = json!({"type": "choice", "instructions": "Is anyone here acting on someone in `your_people`? Who?", "criteria": Value::Object(options.clone())});
            }
            let body = json!({"model": model, "state": state, "questions": questions});
            let (llm, http, sem, url, key, id, handles, model) = (llm.clone(), http.clone(), sem.clone(), url.clone(), key.clone(), id.clone(), handles.clone(), model.clone());
            let price = prices.input_usd_per_m(&model);
            let at = t;
            tasks.spawn(async move {
                let chars = serde_json::to_string(&body).map(|s| s.len()).unwrap_or(0);
                if prompts_only {
                    return json!({"state": id, "t": at, "chars": chars, "est_tokens": chars / 3, "handles": handles.len(), "request": body});
                }
                let _permit = sem.acquire().await;
                let started = std::time::Instant::now();
                let result: Result<Value> = async {
                    let r = http.post(&url).bearer_auth(&key).json(&body).send().await.context("request")?;
                    let status = r.status();
                    let text = r.text().await?;
                    if !status.is_success() {
                        return Err(anyhow!("HTTP {status}: {}", text.chars().take(300).collect::<String>()));
                    }
                    Ok(serde_json::from_str(&text)?)
                }
                .await;
                let latency_ms = started.elapsed().as_millis() as u64;
                let input_tokens = result.as_ref().ok().and_then(|v| v["usage"]["input_tokens"].as_u64());
                let cost = price.zip(input_tokens).map(|(p, n)| n as f64 * p / 1e6);
                llm.journal_entry(&format!("heed-{id}"), &json!({
                    "at_ms": llm::now_ms(), "actor": format!("heed-{id}"), "purpose": "heed-jev", "profile": "jev", "model": model,
                    "latency_ms": latency_ms, "lane": "routine", "queue_wait_ms": 0, "prompt_tokens": input_tokens, "completion_tokens": 0,
                    "cached_tokens": 0, "cost_usd": cost, "request": body, "reply": result.as_ref().ok().map(|v| v.to_string()), "tokens": input_tokens,
                    "error": result.as_ref().err().map(|e| format!("{e:#}")),
                }))
                .await;
                // Picks: handles with probability at least 0.3 in either question, up to 4.
                let mut chosen: Vec<(u32, f64)> = Vec::new();
                if let Ok(v) = &result {
                    for q in ["q_matter", "q_people"] {
                        let a = &v["answers"][q];
                        let probs: Vec<(String, f64)> = match a["probabilities"].as_object() {
                            Some(m) => m.iter().filter_map(|(k, p)| p.as_f64().map(|p| (k.clone(), p))).collect(),
                            None => a["choice"].as_str().map(|c| vec![(c.to_string(), a["confidence"].as_f64().unwrap_or(1.0))]).unwrap_or_default(),
                        };
                        for (h, p) in probs {
                            if p >= 0.3 {
                                if let Some((_, i)) = handles.iter().find(|(x, _)| *x == h) {
                                    if !chosen.iter().any(|(c, _)| c == i) {
                                        chosen.push((*i, p));
                                    }
                                }
                            }
                        }
                    }
                }
                chosen.sort_by(|a, b| b.1.total_cmp(&a.1));
                chosen.truncate(4);
                json!({"state": id, "t": at, "picks": chosen.iter().map(|(i, p)| json!({"id": i, "p": p})).collect::<Vec<_>>(),
                       "latency_ms": latency_ms, "input_tokens": input_tokens, "error": result.err().map(|e| format!("{e:#}"))})
            });
            t += every;
        }
    }
    let mut rows = Vec::new();
    while let Some(r) = tasks.join_next().await {
        rows.push(r?);
    }
    rows.sort_by(|a, b| (a["state"].as_str(), a["t"].as_f64().map(|x| (x * 1000.0) as i64)).cmp(&(b["state"].as_str(), b["t"].as_f64().map(|x| (x * 1000.0) as i64))));
    write_rows(out, &rows)?;
    let errors = rows.iter().filter(|r| r["error"].is_string()).count();
    eprintln!("heed-replay --ask jev: {} requests, {errors} errors -> {}", rows.len(), out.display());
    Ok(())
}

fn write_rows(out: &Path, rows: &[Value]) -> Result<()> {
    let mut w = std::io::BufWriter::new(std::fs::File::create(out).with_context(|| out.display().to_string())?);
    for r in rows {
        writeln!(w, "{r}")?;
    }
    w.flush()?;
    Ok(())
}

/// `heed-replay --ask mind|jev --states STATES.json --src DIR --out FILE [--prompts-only]
/// [--limit N] [--concurrency C] [--route PROFILE] [--fields F --picks P --every S]`.
pub async fn ask_main(root: &Path, args: Vec<String>) -> Result<()> {
    let which = arg(&args, "--ask").ok_or_else(|| anyhow!("--ask mind|jev"))?;
    let states_path = arg(&args, "--states").ok_or_else(|| anyhow!("--states FILE"))?;
    let out = PathBuf::from(arg(&args, "--out").ok_or_else(|| anyhow!("--out FILE"))?);
    let prompts_only = args.iter().any(|a| a == "--prompts-only");
    let limit: usize = arg(&args, "--limit").and_then(|v| v.parse().ok()).unwrap_or(usize::MAX);
    let conc: usize = arg(&args, "--concurrency").and_then(|v| v.parse().ok()).unwrap_or(4);
    let data: Value = serde_json::from_str(&std::fs::read_to_string(&states_path)?)?;
    let mut states: Vec<Value> = data["states"].as_array().cloned().unwrap_or_default();
    // The capacity each state's replay used (the formula), when a picks file gives it.
    if let Some(p) = arg(&args, "--picks") {
        let mut cap: HashMap<String, u64> = HashMap::new();
        for line in std::io::BufReader::new(std::fs::File::open(&p)?).lines() {
            let r: Value = serde_json::from_str(&line?)?;
            if let (Some(s), Some(c)) = (r["state"].as_str(), r["capacity"].as_u64()) {
                cap.insert(s.to_string(), c);
            }
        }
        for s in &mut states {
            if let Some(c) = s["state"].as_str().and_then(|i| cap.get(i)) {
                s["capacity"] = json!(c);
            }
        }
    }
    states.truncate(limit);
    match which.as_str() {
        "mind" => {
            let src = PathBuf::from(arg(&args, "--src").ok_or_else(|| anyhow!("--src DIR"))?);
            ask_mind(root, &src, states, &out, prompts_only, arg(&args, "--route"), conc).await
        }
        "jev" => {
            let fields = PathBuf::from(arg(&args, "--fields").ok_or_else(|| anyhow!("--fields FILE"))?);
            let picks = PathBuf::from(arg(&args, "--picks").ok_or_else(|| anyhow!("--picks FILE (arm a's heeded sets)"))?);
            let every: f32 = arg(&args, "--every").and_then(|v| v.parse().ok()).unwrap_or(6.0);
            ask_jev(root, states, &fields, &picks, &out, prompts_only, every, conc).await
        }
        other => Err(anyhow!("--ask {other}: mind or jev")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_heed_field_names_no_one() {
        let f = heed_field(10).to_lowercase();
        for w in ["stranger", "attacker", "enemy", "guard", "duty", "role", "should", "best", "must", "flank", "ambush", "protect", "kill"] {
            let in_grammar = matches!(w, "stranger" | "enemy" | "attacker");
            let n = f.split(|c: char| !c.is_ascii_alphanumeric() && c != '_').filter(|x| *x == w).count();
            // The grammar's own words (a relation, the `attacker` condition) appear once each.
            assert!(n <= usize::from(in_grammar), "`{w}` appears {n} times in the heed field");
        }
        assert!(f.contains("<a kind>") && f.contains("<your words>"));
        assert!(heed_field(7).contains("about 7 others"));
    }

    #[test]
    fn a_jev_state_has_handles_not_ids() {
        let cands = vec![json!({"id": 41, "kind": "person", "dist": 2.0, "made_out": true}), json!({"id": 42, "kind": "person", "dist": 30.0, "made_out": true})];
        let heeded: HashSet<u32> = [41].into_iter().collect();
        let (state, handles) = jev_state(&cands, &heeded, &HashSet::new(), 10);
        let text = state.to_string();
        assert!(!text.contains("41") && !text.contains("42"), "{text}");
        assert_eq!(handles, vec![("c1".to_string(), 41), ("c2".to_string(), 42)]);
    }
}
