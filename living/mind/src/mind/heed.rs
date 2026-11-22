//! `living-mind heed-replay`: E3's who-to-track replays (docs/ATTENTION_E3.md).
//!
//! Reads fields rebuilt from recorded runs (`living/tools/attention_e3.py fields`: per state, what
//! the subject perceived at each step, and the events between steps) and runs the shared
//! selector (`living_rules::heed`) over them as the authority would:
//! - each event in time order through the event pass (`admit`): a windup aimed at the subject is
//!   the policy's to take or leave; a contact (a blow on the subject that landed, or that it
//!   blocked or dodged) is forced;
//! - then the full pass at each step (`select`), each rule's hold applied from how long its
//!   creature has been heeded.
//!
//! Capacity is the world's `heed_capacity(a)` law on the subject's recorded body, or a fixed
//! number, clamped by the ceiling (`--ceiling`, else the script's `heed_ceiling`). No model is
//! called here: arm (a) is the species' instinct; arms (b) and (c) pass their policies or picks
//! in as files.
//!
//!     living-mind heed-replay --fields FIELDS.jsonl --out PICKS.jsonl
//!         [--capacity formula|N] [--ceiling N] [--contact-s S] [--no-holds] [--closing-s S | --raw-closing]
//!         [--policies POLICIES.jsonl] [--chosen CHOSEN.jsonl] [--script living/scripts/skills.rhai]
//!     living-mind heed-replay --ask mind|jev ...   (the model arms: `heed_ask.rs`)
//!
//! `--chosen`: Jev's picks (arm c, `--ask jev`'s output): each `{"state", "t", "picks": [{"id"}]}`
//! makes those creatures `chosen` from `t` until the state's next refresh.
//!
//! `--policies`: one `{"state": .., "heed": ..}` per line, the policy that state's subject wrote
//! (arm b). A state without a line, or whose policy is refused, keeps the instinct; the output
//! says which and why. `--no-holds` takes every rule's `hold_s` out (to measure what holds do).
//!
//! Output: one line per state and step: `picks` as `[id, place]`, place a rule's index, or -1
//! for acting on it, -2 for contact; `events` with what the event pass did.

use anyhow::{anyhow, Context, Result};
use living_rules::doing::Phase;
use living_rules::heed::{self, Admit, Candidate, ClosingTracker, Held, Known, Limits, Pick, Place, Policy, SelfState, Visible};
use living_rules::script::{ActorFacts, Scripts, SkillCtx};
use serde::Deserialize;
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::path::Path;

#[derive(Deserialize, Default)]
#[serde(default)]
struct VisIn {
    is: Vec<String>,
    phase: Option<String>,
    at_me: bool,
}

#[derive(Deserialize, Default, Clone)]
#[serde(default)]
struct CandIn {
    id: u32,
    kind: String,
    /// The age it is seen at (`infant`, `child`, `adult`, `elder`), when the fields know it.
    stage: Option<String>,
    dist: f32,
    closing: f32,
    made_out: bool,
    relations: u8,
    threatening: bool,
    doing: Option<serde_json::Value>,
    hurt_me_ago_s: Option<f32>,
    addressed_me_ago_s: Option<f32>,
    acted_on: bool,
    contact_ago_s: Option<f32>,
    cued: bool,
    chosen: Option<f32>,
    in_sight_s: f32,
    fighting: bool,
    fallen: bool,
    loud: bool,
    lit: bool,
    /// Whom its visible act is aimed at (for `acting_on_heeded`).
    target: u32,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct EventIn {
    t: f32,
    /// `windup` or `contact`.
    kind: String,
    #[serde(rename = "use")]
    use_id: u64,
    cand: CandIn,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct StepIn {
    t: f32,
    cands: Vec<CandIn>,
    events: Vec<EventIn>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct ActorIn {
    kind: String,
    stage: String,
    hp: f32,
    energy: f32,
    stamina: f32,
    knows: Vec<String>,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct SelfIn {
    health: f32,
    energy: f32,
    hunger: f32,
    stamina: f32,
    night: bool,
}

#[derive(Deserialize, Default)]
#[serde(default)]
struct StateIn {
    state: String,
    kind: String,
    actor: ActorIn,
    #[serde(rename = "self")]
    me: SelfIn,
    steps: Vec<StepIn>,
}

fn candidate(c: &CandIn, heeded: &[Pick], since: &HashMap<u32, f32>, t: f32) -> Candidate {
    let doing = c.doing.as_ref().and_then(|v| serde_json::from_value::<VisIn>(v.clone()).ok()).map(|v| Visible {
        is: v.is,
        phase: v.phase.as_deref().and_then(Phase::parse),
        at_me: v.at_me,
    });
    Candidate {
        id: c.id,
        kind: c.kind.clone(),
        stage: c.stage.as_deref().and_then(heed::age_word),
        dist: c.dist,
        closing: c.closing,
        made_out: c.made_out,
        relations: c.relations,
        threatening: c.threatening,
        doing,
        hurt_me_ago_s: c.hurt_me_ago_s,
        addressed_me_ago_s: c.addressed_me_ago_s,
        acted_on: c.acted_on,
        contact_ago_s: c.contact_ago_s,
        cued: c.cued,
        chosen: c.chosen,
        heeded_s: since.get(&c.id).map(|s| (t - s).max(0.0)),
        in_sight_s: c.in_sight_s,
        fighting: c.fighting,
        fallen: c.fallen,
        acting_on_heeded: c.target != 0 && heeded.iter().any(|p| p.id == c.target),
        loud: c.loud,
        lit: c.lit,
    }
}

fn place_code(p: Place) -> i64 {
    match p {
        Place::Acting => -1,
        Place::Contact => -2,
        Place::Rule(r) => r as i64,
    }
}

enum Capacity {
    Formula,
    Fixed(usize),
}

fn arg(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1)).cloned()
}

fn law_f32(s: &Scripts, name: &str) -> Option<f32> {
    s.law_value(name).and_then(|v| v.as_f64()).map(|v| v as f32)
}

/// The subcommand's entry (`main.rs`).
pub async fn replay_main(root: &Path, args: Vec<String>) -> Result<()> {
    if args.iter().any(|a| a == "--ask") {
        return super::heed_ask::ask_main(root, args).await;
    }
    let fields = arg(&args, "--fields").ok_or_else(|| anyhow!("--fields FILE"))?;
    let out = arg(&args, "--out").ok_or_else(|| anyhow!("--out FILE"))?;
    let script_path = arg(&args, "--script").map(std::path::PathBuf::from).unwrap_or_else(|| root.join("living/scripts/skills.rhai"));
    let scripts = Scripts::new(&std::fs::read_to_string(&script_path).with_context(|| format!("read {}", script_path.display()))?).map_err(|e| anyhow!("script: {e}"))?;
    let ceiling: f32 = match arg(&args, "--ceiling") {
        Some(v) => v.parse().context("--ceiling")?,
        None => law_f32(&scripts, "heed_ceiling").unwrap_or(16.0),
    };
    let contact_s: f32 = match arg(&args, "--contact-s") {
        Some(v) => v.parse().context("--contact-s")?,
        None => law_f32(&scripts, "heed_contact_s").unwrap_or(heed::DEFAULT_CONTACT_S),
    };
    let no_holds = args.iter().any(|a| a == "--no-holds");
    // Closing speed through the shared tracker over `heed_closing_s` (the authority's way), or
    // the fields' own per-step value (`--raw-closing`, for comparison).
    let raw_closing = args.iter().any(|a| a == "--raw-closing");
    let closing_s: f32 = match arg(&args, "--closing-s") {
        Some(v) => v.parse().context("--closing-s")?,
        None => law_f32(&scripts, "heed_closing_s").unwrap_or(heed::DEFAULT_CLOSING_S),
    };
    let capacity = match arg(&args, "--capacity").as_deref() {
        None | Some("formula") => Capacity::Formula,
        Some(n) => Capacity::Fixed(n.parse().context("--capacity formula|N")?),
    };
    let hp_person = law_f32(&scripts, "hp_person").unwrap_or(100.0);
    let mut policies: HashMap<String, serde_json::Value> = HashMap::new();
    if let Some(p) = arg(&args, "--policies") {
        for line in std::io::BufReader::new(std::fs::File::open(&p).with_context(|| p.clone())?).lines() {
            let v: serde_json::Value = serde_json::from_str(&line?)?;
            let s = v.get("state").and_then(|s| s.as_str()).ok_or_else(|| anyhow!("a policies line needs `state`"))?.to_string();
            policies.insert(s, v.get("heed").cloned().unwrap_or(serde_json::Value::Null));
        }
    }
    // Jev's picks: per state, (from t, ids), in time order.
    let mut chosen_at: HashMap<String, Vec<(f32, Vec<u32>)>> = HashMap::new();
    if let Some(p) = arg(&args, "--chosen") {
        for line in std::io::BufReader::new(std::fs::File::open(&p).with_context(|| p.clone())?).lines() {
            let v: serde_json::Value = serde_json::from_str(&line?)?;
            let s = v["state"].as_str().unwrap_or_default().to_string();
            let t = v["t"].as_f64().unwrap_or(0.0) as f32;
            let ids = v["picks"].as_array().map(|a| a.iter().filter_map(|x| x["id"].as_u64().map(|i| i as u32)).collect()).unwrap_or_default();
            chosen_at.entry(s).or_default().push((t, ids));
        }
        for v in chosen_at.values_mut() {
            v.sort_by(|a, b| a.0.total_cmp(&b.0));
        }
    }
    let mut w = std::io::BufWriter::new(std::fs::File::create(&out).with_context(|| out.clone())?);
    let (mut states, mut steps_n, mut events_n) = (0usize, 0usize, 0usize);
    for line in std::io::BufReader::new(std::fs::File::open(&fields).with_context(|| fields.clone())?).lines() {
        let st: StateIn = serde_json::from_str(&line?)?;
        let kind = if st.kind.is_empty() { "person".to_string() } else { st.kind.clone() };
        // The policy: the state's own (arm b), validated as the authority would, else the instinct.
        let seen: std::collections::HashSet<u32> = st.steps.iter().flat_map(|s| s.cands.iter().map(|c| c.id)).collect();
        let (policy, source, refusal): (Policy, &str, Option<String>) = match policies.get(&st.state) {
            Some(v) if !v.is_null() => {
                let known = Known { met: &|id| seen.contains(&id), kind: &|k| ["person", "wolf", "deer", "animal"].contains(&k) };
                match heed::parse_value(v, &known) {
                    Ok(p) => (p, "policy", None),
                    Err(e) => (heed::instinct(&kind), "instinct", Some(e)),
                }
            }
            _ => (heed::instinct(&kind), "instinct", None),
        };
        let policy = if no_holds { heed::without_holds(&policy) } else { policy };
        let cap = match capacity {
            Capacity::Fixed(n) => heed::clamp_capacity(n as f64, ceiling),
            Capacity::Formula => {
                let a = &st.actor;
                let ctx = SkillCtx {
                    actor: ActorFacts {
                        kind: if a.kind.is_empty() { kind.clone() } else { a.kind.clone() },
                        stage: if a.stage.is_empty() { "adult".into() } else { a.stage.clone() },
                        hp: a.hp,
                        energy: a.energy,
                        stamina: a.stamina,
                        knows: a.knows.clone(),
                        ..Default::default()
                    },
                    ..Default::default()
                };
                scripts.heed_capacity(&ctx, ceiling).map_err(|e| anyhow!("{}: {e}", st.state))?
            }
        };
        let limits = Limits { capacity: cap, contact_s };
        let me = SelfState {
            health: (100.0 * st.me.health / hp_person).min(100.0),
            energy: st.me.energy,
            hunger: st.me.hunger,
            stamina: st.me.stamina,
            night: st.me.night,
            hurt_ago_s: None,
        };
        let mut heeded: Vec<Pick> = Vec::new();
        // When each heeded creature was first heeded (for `heeded_s`), and when its rule last took
        // it on merit (for its hold).
        let mut since: HashMap<u32, f32> = HashMap::new();
        let mut merit: HashMap<u32, f32> = HashMap::new();
        let picks_of = chosen_at.get(&st.state).cloned().unwrap_or_default();
        let mut tracker = ClosingTracker::new(closing_s);
        for step in &st.steps {
            // Jev's latest picks at or before this step make those creatures `chosen`.
            let now_chosen: Vec<u32> = picks_of.iter().filter(|(t, _)| *t <= step.t + 1e-3).last().map(|(_, ids)| ids.clone()).unwrap_or_default();
            let mark = |c: &CandIn| -> CandIn {
                let mut c = c.clone();
                if now_chosen.contains(&c.id) {
                    c.chosen = Some(c.chosen.unwrap_or(1.0));
                }
                c
            };
            let mut step_cands: Vec<CandIn> = step.cands.iter().map(mark).collect();
            if !raw_closing {
                for c in &mut step_cands {
                    c.closing = tracker.observe(c.id, step.t, c.dist);
                }
                tracker.forget_before(step.t - 1e-3);
            }
            let mut events = Vec::new();
            for e in &step.events {
                let all: Vec<Candidate> = step_cands.iter().map(|c| candidate(c, &heeded, &since, e.t)).collect();
                let mut ec = mark(&e.cand);
                if !raw_closing {
                    ec.closing = tracker.last(ec.id).unwrap_or(0.0);
                }
                let c = candidate(&ec, &heeded, &since, e.t);
                let already = heeded.iter().any(|p| p.id == c.id);
                let verdict = heed::admit(&policy, &c, &me, &all, &heeded, &limits);
                match verdict {
                    Admit::Forced(place) => {
                        heeded.retain(|p| p.id != c.id);
                        heeded.insert(0, Pick::new(c.id, place));
                        since.entry(c.id).or_insert(e.t);
                    }
                    Admit::Take { rule } => {
                        heeded.push(Pick::new(c.id, Place::Rule(rule)));
                        since.insert(c.id, e.t);
                        merit.insert(c.id, e.t);
                    }
                    Admit::Replace { rule, drop } => {
                        heeded.retain(|p| p.id != drop);
                        since.remove(&drop);
                        merit.remove(&drop);
                        heeded.push(Pick::new(c.id, Place::Rule(rule)));
                        since.insert(c.id, e.t);
                        merit.insert(c.id, e.t);
                    }
                    Admit::No => {}
                }
                let verdict_word = match verdict {
                    Admit::No => "no",
                    Admit::Forced(_) => "forced",
                    Admit::Take { .. } => "take",
                    Admit::Replace { .. } => "replace",
                };
                events.push(serde_json::json!({"kind": e.kind, "use": e.use_id, "id": c.id, "t": e.t, "already": already, "verdict": verdict_word}));
                events_n += 1;
            }
            // The full pass, each rule's hold applied.
            let t = step.t;
            let all: Vec<Candidate> = step_cands.iter().map(|c| candidate(c, &heeded, &since, t)).collect();
            let held: Vec<Held> = heeded
                .iter()
                .filter_map(|p| p.place.rule().map(|r| Held { id: p.id, rule: r, lapsed_s: merit.get(&p.id).map_or(f32::MAX, |m| (t - m).max(0.0)) }))
                .collect();
            let picks = heed::select(&policy, &me, &all, &limits, &held);
            let mut next: HashMap<u32, f32> = HashMap::new();
            let mut next_merit: HashMap<u32, f32> = HashMap::new();
            for p in &picks {
                next.insert(p.id, *since.get(&p.id).unwrap_or(&t));
                if p.place.rule().is_some() {
                    next_merit.insert(p.id, if p.held { *merit.get(&p.id).unwrap_or(&t) } else { t });
                }
            }
            since = next;
            merit = next_merit;
            heeded = picks;
            let row = serde_json::json!({
                "state": st.state, "t": t, "capacity": cap, "in_sight": step.cands.len(), "source": source, "refusal": refusal,
                "picks": heeded.iter().map(|p| [p.id as i64, place_code(p.place)]).collect::<Vec<_>>(), "events": events,
            });
            writeln!(w, "{row}")?;
            steps_n += 1;
        }
        states += 1;
    }
    w.flush()?;
    eprintln!(
        "heed-replay: {states} states, {steps_n} steps, {events_n} events -> {out} (ceiling {ceiling}, contact {contact_s} s, holds {}, closing {})",
        if no_holds { "off" } else { "on" },
        if raw_closing { "raw".to_string() } else { format!("over {closing_s} s") }
    );
    Ok(())
}
