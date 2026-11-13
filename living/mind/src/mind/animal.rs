//! Cheaper animal minds (docs/MIND_HARNESS.md, item 3). Three switches, any combination,
//! in `LIVING_ANIMAL_MINDS` (comma-separated; empty is today's mind: an impulse, then a
//! graph compiled from it, two model calls per thought):
//!
//! - `salient`: think only on a salient change since the animal last thought: a kind of
//!   creature newly seen or smelled, being attacked or threatened, a wound band crossed, a
//!   death among its own kind, hunger crossing a band. Otherwise the request is answered
//!   without a model call and the animal keeps living by its instincts and last impulse.
//! - `choose`: one call instead of two. The model picks among a few graph edits built from the
//!   scene and the species' skills (flee from, hunt, follow its kind, rest, roam, signal, or
//!   carry on) and how strongly; the mind builds the graph from a template, so it is valid by
//!   construction (and still checked against the body).
//! - `pack` (retired 2026-11-12, docs/PACK_MIND.md): one animal's decision copied into the
//!   graphs of the others of its kind it saw, which perceived nothing of it. That was shared
//!   hidden state, so every animal now decides on its own; the word is ignored with a warning.
//!
//! The rules are not touched: what the animal can do is what its species' skills allow, and
//! every graph goes through the same `mind_install_way` (with no line) as a person's.

use living_bindings::*;
use serde_json::{json, Value};
use std::collections::BTreeSet;

#[derive(Clone, Debug, Default)]
pub struct Config {
    pub salient: bool,
    pub choose: bool,
}

impl Config {
    pub fn from_env() -> Self {
        let on: Vec<String> = std::env::var("LIVING_ANIMAL_MINDS").unwrap_or_default().split(',').map(|s| s.trim().to_lowercase()).collect();
        if on.iter().any(|s| s == "pack") {
            log::warn!("LIVING_ANIMAL_MINDS: `pack` is retired (one animal's decision copied to others is shared hidden state, docs/PACK_MIND.md); every animal decides on its own");
        }
        Self {
            salient: on.iter().any(|s| s == "salient"),
            choose: on.iter().any(|s| s == "choose"),
        }
    }

    pub fn any(&self) -> bool {
        self.salient || self.choose
    }
}

/// What an animal's last thought was about, to tell a salient change from more of the same.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Signature {
    /// Other kinds seen or smelled.
    pub kinds: BTreeSet<String>,
    /// 0 unhurt, 1 hurt (below 70%), 2 badly (below 35%).
    pub wound: u8,
    /// 0 fed, 1 hungry (above 50), 2 starving (above 80).
    pub hunger: u8,
    /// How many of its own kind it has seen die (from its experiences).
    pub deaths: usize,
}

fn band(v: f64, cuts: [f64; 2]) -> u8 {
    u8::from(v > cuts[0]) + u8::from(v > cuts[1])
}

impl Signature {
    pub fn of(kind: &str, scene: &Value, deaths: usize) -> Self {
        let mut kinds = BTreeSet::new();
        for c in creatures(scene) {
            if c.kind != kind {
                kinds.insert(c.kind.clone());
            }
        }
        let you = &scene["you"];
        let hp = you["health"].as_f64().unwrap_or(100.0);
        let max = you["max_health"].as_f64().unwrap_or(100.0).max(1.0);
        let frac = hp / max;
        let wound = if frac < 0.35 { 2 } else { u8::from(frac < 0.7) };
        let hunger = band(you["hunger"].as_f64().unwrap_or(0.0), [50.0, 80.0]);
        Self { kinds, wound, hunger, deaths }
    }

    /// Why this moment is worth a thought after `last` (`None`: it is not).
    pub fn salient(&self, last: Option<&Signature>, reason: &str) -> Option<String> {
        if reason.contains("attacking you") || reason.contains("threatening you") || reason.starts_with("The fight with") {
            return Some("attacked".into());
        }
        let Some(last) = last else { return Some("first thought".into()) };
        if let Some(k) = self.kinds.difference(&last.kinds).next() {
            return Some(format!("a {k} appeared"));
        }
        if self.wound > last.wound {
            return Some("wounded".into());
        }
        if self.deaths > last.deaths {
            return Some("one of its kind died".into());
        }
        if self.hunger > last.hunger {
            return Some("hungrier".into());
        }
        None
    }
}

/// A creature in a scene, seen or smelled.
#[derive(Clone, Debug)]
pub struct Seen {
    pub id: u64,
    pub kind: String,
    pub dist: f64,
    pub smelled: bool,
}

pub fn creatures(scene: &Value) -> Vec<Seen> {
    let seen = scene["creatures"].as_array().into_iter().flatten().map(|c| (c, false));
    let smelled = scene[living_rules::species::SMELLED].as_array().into_iter().flatten().map(|c| (c, true));
    let mut out: Vec<Seen> = seen
        .chain(smelled)
        .filter_map(|(c, smelled)| {
            Some(Seen { id: c["id"].as_u64()?, kind: c["kind"].as_str()?.to_string(), dist: c["dist"].as_f64().or_else(|| c["dist"].as_str().and_then(|d| d.split_whitespace().find_map(|w| w.parse().ok()))).unwrap_or(99.0), smelled })
        })
        .collect();
    out.sort_by(|a, b| a.dist.total_cmp(&b.dist));
    out
}

/// One option an animal may pick: what it is called in the prompt, the graph it becomes, and
/// the trait that strengthens it.
#[derive(Clone, Debug, PartialEq)]
pub struct Option_ {
    pub label: String,
    pub graph: Option<Value>,
    pub drive: &'static str,
}

/// The options open to an animal of a species in a scene, from its skills: carry on first,
/// then for the nearest other creatures (at most four) flee or hunt, then keeping with its
/// kind, rest, roam and its signals.
pub fn menu(kind: &str, skills: &[String], eats: &str, signals: &[String], scene: &Value) -> Vec<Option_> {
    let has = |s: &str| skills.iter().any(|x| x == s);
    let mut out = vec![Option_ { label: "carry on as your instincts lead".into(), graph: None, drive: "" }];
    let mut seen_kinds = BTreeSet::new();
    for c in creatures(scene).into_iter().filter(|c| c.kind != kind).take(4) {
        let how = if c.smelled { "smelled" } else { "seen" };
        let name = format!("the {} #{} ({how}, {:.0} tiles)", c.kind, c.id, c.dist);
        if has("flee") {
            out.push(Option_ { label: format!("flee from {name}"), graph: Some(json!({"do": {"skill": "flee", "target": {"id": c.id}}})), drive: "fear" });
        }
        // Prey is what the species eats (its `eats` names it); anything else it may still fight.
        if has("attack") && seen_kinds.insert(c.kind.clone()) {
            let prey = eats.contains(&c.kind);
            let verb = if prey { "hunt" } else { "attack" };
            out.push(Option_ { label: format!("{verb} {name}"), graph: Some(json!({"do": {"skill": "attack", "target": {"id": c.id}}})), drive: "aggression" });
        }
    }
    if has("follow") && creatures(scene).iter().any(|c| c.kind == kind && !c.smelled) {
        out.push(Option_ { label: format!("keep close to the nearest {kind}"), graph: Some(json!({"do": {"skill": "follow", "target": {"nearest": kind}}})), drive: "sociability" });
    }
    if has("rest") {
        out.push(Option_ { label: "rest where you are".into(), graph: Some(json!({"seq": [{"do": {"skill": "rest"}}, {"wait": 20}]})), drive: "" });
    }
    if has("wander") {
        out.push(Option_ { label: "roam and look around".into(), graph: Some(json!({"seq": [{"do": {"skill": "wander"}}, {"wait": 6}]})), drive: "curiosity" });
    }
    if has("signal") {
        for s in signals {
            out.push(Option_ { label: format!("give your {s} call"), graph: Some(json!({"do": {"skill": "signal", "item": s}})), drive: "sociability" });
        }
    }
    out
}

/// The weight an option gets for one animal: the strength it was picked with, scaled by the
/// trait that drives it (0.6× for a trait of 0 to 1.4× for 100). Fear is the opposite of
/// boldness, or nervousness where the species has it.
pub fn weight(strength: &str, drive: &str, traits: &Value) -> f32 {
    let base = match strength {
        "low" => 0.4,
        "high" => 1.2,
        _ => 0.8,
    };
    let t = |k: &str| traits[k].as_f64();
    let trait_ = match drive {
        "fear" => t("nervousness").or_else(|| t("boldness").map(|b| 100.0 - b)),
        "aggression" => t("aggression").or_else(|| t("boldness")),
        "" => None,
        d => t(d),
    };
    let scale = trait_.map_or(1.0, |v| 0.6 + 0.8 * (v.clamp(0.0, 100.0) / 100.0));
    (base * scale as f32 * 100.0).round() / 100.0
}

impl super::Minds {
    /// An animal's thought with the switches of `LIVING_ANIMAL_MINDS` (see the module docs).
    pub(super) async fn deliberate_animal_cheap(&self, d: &living_bindings::Deliberation, c: &living_bindings::Character, lane: crate::llm::Lane) -> anyhow::Result<()> {
        use crate::llm::{self, Msg};
        use crate::prompts;
        let actor = c.id;
        let cfg = self.animal_cfg.clone();
        let Some(sp) = self.species.get(&c.kind).cloned() else { return Ok(()) };
        let scene: Value = serde_json::from_str(&d.scene).unwrap_or(json!({}));
        let traits = |id: u32| self.conn.db.persona().id().find(&id).and_then(|p| serde_json::from_str::<Value>(&p.traits).ok()).unwrap_or(json!({}));
        if cfg.salient {
            let deaths = self.experiences(actor).iter().filter(|e| (e.text.contains(" died") || e.text.contains(" dies") || e.text.contains("was killed")) && [e.subject, e.object].iter().any(|x| *x != actor && self.conn.db.character().id().find(x).is_some_and(|o| o.kind == c.kind))).count();
            let sig = Signature::of(&c.kind, &scene, deaths);
            let last = self.animal_sigs.lock().unwrap().get(&actor).cloned();
            match sig.salient(last.as_ref(), &d.reason) {
                None => {
                    let t = living_bindings::ThoughtIn { kind: "instinct".into(), summary: "nothing new: lives by its instincts".into(), detail: json!({"mode": "salient", "reason": d.reason}).to_string(), latency_ms: 0, tokens: 0, model: "none".into(), reference: super::reference(actor, "instinct") };
                    return self.skip(actor, d.updated_ms, t).await;
                }
                Some(_) => {
                    self.animal_sigs.lock().unwrap().insert(actor, sig);
                }
            }
        }
        if !cfg.choose {
            return self.deliberate_animal(d, c, lane).await;
        }
        let route = self.llm.species_profile(&c.kind, "think").unwrap_or_else(|| self.llm.profile_for(actor, &c.name));
        let at = self.attention(actor, Some(&d.scene));
        let fmt = self.fmt_time();
        let recalled = self.recall_for(actor, &self.scene_cues(actor, &scene, &d.reason), 10, 0, "animal").await;
        let mut mind = recalled.mind;
        mind.extend(recalled.judgments.into_iter().filter(|j| !j.starts_with('(')).map(|j| format!("feels sure: {j}")));
        let experiences: Vec<String> = self.experiences_upto(actor, d.updated_ms, 8).iter().map(|e| self.exp_line(e, &fmt, false)).collect();
        let temperament = self.conn.db.persona().id().find(&actor).map(|p| format!("{} (mood: {})", p.traits, p.mood)).unwrap_or_default();
        let skills = sp.skills.clone().unwrap_or_default();
        let signals: Vec<String> = sp.signals.keys().cloned().collect();
        let options = menu(&c.kind, &skills, &sp.eats, &signals, &scene);
        let labels: Vec<String> = options.iter().map(|o| o.label.clone()).collect();
        let user = prompts::animal_choose_user(prompts::animal_think_user(&c.name, &c.kind, &temperament, &mind, &experiences, &d.scene, &d.reason), &labels);
        let msgs = [Msg { role: "system", content: prompts::animal_choose_system(&c.kind, &sp.nature) }, Msg { role: "user", content: user }];
        let reply = self.llm.chat_in_lane(&route, at, "deliberate", &c.name, &msgs, lane).await.map_err(super::unavailable)?;
        let v = llm::parse_json(&reply.content).unwrap_or(json!({}));
        let pick = v["pick"].as_u64().or_else(|| v["pick"].as_str().and_then(|s| s.trim().parse().ok())).map(|p| p as usize).filter(|p| *p < options.len());
        let option = pick.map(|p| options[p].clone()).unwrap_or_else(|| options[0].clone());
        let strength = v["strength"].as_str().filter(|s| matches!(*s, "low" | "mid" | "high")).unwrap_or("mid").to_string();
        let feeling = v["feeling"].as_str().unwrap_or_default().to_string();
        let impulse = option.label.clone();
        let detail = json!({"mode": "choose", "options": labels, "pick": pick, "valid_pick": pick.is_some()});
        self.animal_install(d, c, &sp, &option, &strength, &traits(actor), &feeling, &impulse, detail, (reply.latency_ms, reply.tokens, reply.model)).await
    }

    /// Install a picked option as the animal's impulse, weighed by its temperament (or carry on).
    #[allow(clippy::too_many_arguments)]
    async fn animal_install(&self, d: &living_bindings::Deliberation, c: &living_bindings::Character, sp: &living_rules::species::Species, option: &Option_, strength: &str, traits: &Value, feeling: &str, impulse: &str, mut detail: Value, (latency_ms, tokens, model): (u32, u32, String)) -> anyhow::Result<()> {
        let actor = c.id;
        detail["reason"] = json!(d.reason);
        detail["feeling"] = json!(feeling);
        detail["impulse"] = json!(impulse);
        let t = |summary: String, detail: Value| living_bindings::ThoughtIn { kind: "deliberate".into(), summary, detail: detail.to_string(), latency_ms, tokens, model: model.clone(), reference: super::reference(actor, "deliberate") };
        let Some(graph) = option.graph.clone() else {
            log::info!("{} the {} feels: {feeling} → carries on", c.name, c.kind);
            let (tx, rx) = tokio::sync::oneshot::channel();
            self.conn.reducers.mind_say_then(actor, String::new(), 0, String::new(), d.updated_ms, t(format!("{feeling} → {impulse}"), detail), move |_, r| {
                let _ = tx.send(super::flatten(r));
            })?;
            return rx.await?.map_err(|e| anyhow::anyhow!("mind_say: {e}"));
        };
        let w = weight(strength, option.drive, traits);
        detail["weight"] = json!(w);
        // Without a top level to weigh it against (none installed, or one that no longer
        // parses), the impulse is the animal's top level, as an animal's flat plan is.
        let v = self.plan_into_desires(actor, json!({"intent": {"weight": w, "graph": graph.clone()}})).unwrap_or_else(|| json!({"graph": graph}));
        let (g, pruned) = living_rules::graph::from_value_for(v["graph"].clone(), sp).map_err(|e| anyhow::anyhow!(e))?;
        detail["pruned"] = json!(pruned);
        log::info!("{} the {} feels: {feeling} → {impulse} ({strength}, weight {w})", c.name, c.kind);
        self.install(actor, g.to_json(), impulse.to_string(), String::new(), 0, String::new(), d.updated_ms, t(format!("{feeling} → {impulse}"), detail)).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scene() -> Value {
        json!({"you": {"id": 1, "health": 60, "hunger": 55},
               "creatures": [{"id": 7, "kind": "deer", "dist": 9}, {"id": 2, "kind": "wolf", "dist": 3}, {"id": 30, "kind": "person", "dist": 14}],
               living_rules::species::SMELLED: [{"id": 40, "kind": "deer", "dir": "north", "dist": "far, about 30 tiles"}]})
    }

    #[test]
    fn salience_is_new_kinds_wounds_deaths_hunger_or_an_attack() {
        let a = Signature::of("wolf", &scene(), 0);
        assert_eq!(a.kinds, ["deer".to_string(), "person".to_string()].into_iter().collect());
        assert_eq!((a.wound, a.hunger), (1, 1));
        assert!(a.salient(None, "Dawn of day 2").is_some(), "the first thought");
        assert_eq!(a.salient(Some(&a), "A deer passed."), None, "more of the same");
        assert!(a.salient(Some(&a), "Grey is attacking you!").is_some());
        let mut fewer = a.clone();
        fewer.kinds.remove("person");
        assert_eq!(a.salient(Some(&fewer), "").as_deref(), Some("a person appeared"));
        assert_eq!(Signature { wound: 2, ..a.clone() }.salient(Some(&a), "").as_deref(), Some("wounded"));
        assert_eq!(Signature { deaths: 1, ..a.clone() }.salient(Some(&a), "").as_deref(), Some("one of its kind died"));
        assert_eq!(Signature { hunger: 2, ..a.clone() }.salient(Some(&a), "").as_deref(), Some("hungrier"));
        assert_eq!(Signature { hunger: 0, ..a.clone() }.salient(Some(&a), ""), None, "eating is not news");
    }

    #[test]
    fn the_menu_is_built_from_skills_and_every_graph_is_valid_for_the_body() {
        let species = living_rules::species::parse(include_str!("../../../seeds/species.json")).unwrap();
        let wolf = &species["wolf"];
        let skills: Vec<String> = wolf.skills.clone().unwrap_or_default();
        let signals: Vec<String> = wolf.signals.keys().cloned().collect();
        let eats = "meat: from prey you kill (deer), eaten from what you carry";
        let m = menu("wolf", &skills, eats, &signals, &scene());
        let labels: Vec<&str> = m.iter().map(|o| o.label.as_str()).collect();
        assert_eq!(labels[0], "carry on as your instincts lead");
        assert!(labels.iter().any(|l| l.starts_with("hunt the deer #7")), "{labels:?}");
        assert!(labels.iter().any(|l| l.starts_with("attack the person #30")));
        assert!(labels.iter().any(|l| l.starts_with("flee from the deer #40 (smelled")));
        assert!(labels.iter().any(|l| *l == "keep close to the nearest wolf"));
        for o in m.iter().filter_map(|o| o.graph.clone()) {
            living_rules::graph::from_value_for(o, wolf).unwrap();
        }
        let deer = &species["deer"];
        let dm = menu("deer", &deer.skills.clone().unwrap_or_default(), "grass", &[], &scene());
        assert!(!dm.iter().any(|o| o.label.starts_with("hunt") || o.label.starts_with("attack")), "a deer cannot attack");
    }

    #[test]
    fn temperament_scales_the_picked_strength() {
        assert_eq!(weight("high", "aggression", &json!({"aggression": 100})), 1.68);
        assert_eq!(weight("high", "aggression", &json!({"aggression": 0})), 0.72);
        assert_eq!(weight("mid", "fear", &json!({"boldness": 25})), 0.96);
        assert_eq!(weight("mid", "fear", &json!({"nervousness": 25})), 0.64);
        assert_eq!(weight("low", "", &json!({})), 0.4);
    }
}
