//! Lenient front end for model-written behavior graphs. Accepts the flat forms taught to
//! models (`{"if": C, "then": N}`, `{"do": "gather", "target": T}`, `{"say": "hi"}`), the
//! nested canonical forms, and common slips (skills used as node keys, nulls, `and`/`or`,
//! `>`/`<`). Produces the canonical JSON the typed parser accepts, or an error naming the
//! exact path and the fix.

use crate::catalog;
use serde_json::{json, Map, Value};

use std::cell::RefCell;

thread_local! {
    static WARNINGS: RefCell<Vec<String>> = const { RefCell::new(Vec::new()) };
    /// The body the graph is written for (while normalizing a species-specific graph).
    static BODY: RefCell<Option<crate::species::Species>> = const { RefCell::new(None) };
}

/// Normalize for a particular body: skills it lacks, speech it cannot make and signals
/// outside its vocabulary are pruned like any other invalid branch.
pub fn graph_for(v: Value, body: &crate::species::Species) -> Result<(Value, Vec<String>), String> {
    BODY.with(|b| *b.borrow_mut() = Some(body.clone()));
    let r = graph(v);
    BODY.with(|b| *b.borrow_mut() = None);
    r
}

fn body_check(path: &str, skill: &str, item: Option<&str>) -> Result<(), String> {
    BODY.with(|b| {
        let b = b.borrow();
        let Some(sp) = b.as_ref() else { return Ok(()) };
        if skill == "say" && !sp.speaks {
            return Err(format!("{path}: you have no words; use {{\"do\": \"signal\", \"item\": one of {:?}}}", sp.signals.keys().collect::<Vec<_>>()));
        }
        if skill != "say" && !sp.allows(skill) {
            return Err(format!("{path}.do: your body cannot `{skill}`"));
        }
        if skill == "signal" {
            let i = item.unwrap_or_default();
            if !sp.signals.contains_key(i) {
                return Err(format!("{path}.do: unknown signal `{i}`; yours are {:?}", sp.signals.keys().collect::<Vec<_>>()));
            }
        }
        Ok(())
    })
}

/// Normalize a whole graph, pruning invalid children of composites. Returns the
/// canonical JSON and a description of every pruned branch.
pub fn graph(v: Value) -> Result<(Value, Vec<String>), String> {
    WARNINGS.with(|w| w.borrow_mut().clear());
    let r = node(v, "graph");
    let warnings = WARNINGS.with(|w| std::mem::take(&mut *w.borrow_mut()));
    r.map(|v| (v, warnings))
}

const NODES: &str = "first, seq, if, do, say, wait, think, routine, desires";
const WEIGHTS: &[&str] = &["base", "hunger", "tired", "hurt", "night", "day", "threatened", "alone", "company", "winter", "longing"];
const CONDS: &str = "hunger, energy, health, hour, threatened, has, sees, near, hurt_within, heard_within, night, believes, chance, all, any, not";

fn strip_nulls(m: Map<String, Value>) -> Map<String, Value> {
    m.into_iter().filter(|(_, v)| !v.is_null()).collect()
}

fn alias_node_key(k: &str) -> &str {
    match k {
        "sequence" | "steps" => "seq",
        "priority" | "selector" | "select" | "fallback" | "choose" => "first",
        "when" => "if",
        "action" => "do",
        "speak" => "say",
        "sleep_for" | "pause" => "wait",
        "reconsider" | "reflect" => "think",
        other => other,
    }
}

pub fn node(v: Value, path: &str) -> Result<Value, String> {
    match v {
        Value::String(s) if catalog::skill(&s).is_some() => Ok(json!({"do": {"skill": s}})),
        Value::String(s) => Err(format!("{path}: expected a node object, got the string \"{s}\"; a node is one of {NODES}")),
        Value::Array(a) => node(json!({"first": a}), path),
        Value::Object(m) => {
            let m: Map<String, Value> = strip_nulls(m).into_iter().map(|(k, v)| (alias_node_key(&k).to_string(), v)).collect();
            if m.contains_key("if") {
                return if_node(m, path);
            }
            if m.contains_key("do") {
                return do_node(m, path);
            }
            for key in ["first", "seq"] {
                if let Some(v) = m.get(key) {
                    return composite(key, v.clone(), m.get("label").cloned(), path);
                }
            }
            if let Some(v) = m.get("say") {
                body_check(path, "say", None)?;
                let (text, to) = match v {
                    Value::String(s) => (s.clone(), m.get("to").cloned()),
                    Value::Object(o) => (
                        o.get("text").and_then(|t| t.as_str()).unwrap_or_default().to_string(),
                        o.get("to").cloned().filter(|t| !t.is_null()).or_else(|| m.get("to").cloned()),
                    ),
                    _ => return Err(format!("{path}.say: expected text")),
                };
                let mut out = json!({"say": {"text": text}});
                if let Some(to) = to {
                    out["say"]["to"] = target(to, &format!("{path}.say.to"))?;
                }
                return Ok(out);
            }
            if let Some(v) = m.get("wait") {
                let secs = match v {
                    Value::Number(n) => n.as_f64().unwrap_or(3.0),
                    Value::String(s) => s.trim_end_matches('s').trim().parse().map_err(|_| format!("{path}.wait: expected seconds"))?,
                    Value::Object(o) => o.get("seconds").or_else(|| o.get("secs")).and_then(|x| x.as_f64()).ok_or_else(|| format!("{path}.wait: expected seconds"))?,
                    _ => return Err(format!("{path}.wait: expected seconds")),
                };
                return Ok(json!({"wait": secs.clamp(0.5, 120.0)}));
            }
            if let Some(v) = m.get("routine") {
                let name = match v {
                    Value::String(s) => s.trim().to_string(),
                    Value::Object(o) => o.get("name").and_then(|n| n.as_str()).unwrap_or_default().trim().to_string(),
                    _ => String::new(),
                };
                if name.is_empty() {
                    return Err(format!("{path}.routine: expected a routine name"));
                }
                return Ok(json!({"routine": name}));
            }
            if let Some(v) = m.get("desires").or_else(|| m.get("wants")) {
                return desires(v.clone(), path);
            }
            if let Some(v) = m.get("think") {
                let reason = match v {
                    Value::String(s) => s.clone(),
                    Value::Object(o) => o.get("reason").and_then(|r| r.as_str()).unwrap_or("reconsider").to_string(),
                    _ => "reconsider".into(),
                };
                return Ok(json!({"think": reason}));
            }
            // A skill used directly as the node key: {"flee": {"target": "attacker"}}.
            if m.len() == 1 || m.keys().any(|k| catalog::skill(k).is_some()) {
                if let Some((k, v)) = m.iter().find(|(k, _)| catalog::skill(k).is_some()) {
                    let mut action = Map::new();
                    action.insert("skill".into(), json!(k));
                    match v {
                        Value::Object(o) => action.extend(o.clone()),
                        Value::String(s) if catalog::skill(k).map_or(false, |sp| sp.needs_item) => {
                            action.insert("item".into(), json!(s));
                        }
                        Value::String(_) | Value::Number(_) => {
                            action.insert("target".into(), v.clone());
                        }
                        _ => {}
                    }
                    for (ok, ov) in &m {
                        if ok != k {
                            action.entry(ok.clone()).or_insert(ov.clone());
                        }
                    }
                    return do_node(Map::from_iter([("do".to_string(), Value::Object(action))]), path);
                }
            }
            let keys: Vec<&String> = m.keys().collect();
            Err(format!(
                "{path}: unknown node {keys:?}; a node is one of {NODES} (skills go in do, e.g. {{\"do\": \"gather\", \"target\": {{\"nearest\": \"berry_bush\"}}}})"
            ))
        }
        other => Err(format!("{path}: expected a node object, got {other}")),
    }
}

fn composite(key: &str, v: Value, label: Option<Value>, path: &str) -> Result<Value, String> {
    let (children, label) = match v {
        Value::Array(a) => (a, label),
        Value::Object(o) => {
            let label = o.get("label").cloned().or(label);
            match o.get("children").cloned() {
                Some(Value::Array(a)) => (a, label),
                _ => return Err(format!("{path}.{key}: expected a list of child nodes")),
            }
        }
        _ => return Err(format!("{path}.{key}: expected a list of child nodes")),
    };
    let mut kept = Vec::new();
    let mut first_err = None;
    for (i, c) in children.into_iter().enumerate() {
        if c.as_object().map_or(false, |o| o.is_empty()) || c.as_array().map_or(false, |a| a.is_empty()) {
            continue;
        }
        match node(c, &format!("{path}.{key}[{i}]")) {
            Ok(n) => kept.push(n),
            Err(e) => {
                WARNINGS.with(|w| w.borrow_mut().push(format!("dropped {e}")));
                first_err.get_or_insert(e);
            }
        }
    }
    if kept.is_empty() {
        return Err(first_err.unwrap_or_else(|| format!("{path}.{key}: no valid children")));
    }
    if kept.len() > crate::graph::MAX_CHILDREN {
        WARNINGS.with(|w| w.borrow_mut().push(format!("dropped {path}.{key}[{}..]: at most {} children per composite", crate::graph::MAX_CHILDREN, crate::graph::MAX_CHILDREN)));
        kept.truncate(crate::graph::MAX_CHILDREN);
    }
    let children = kept;
    Ok(match label.and_then(|l| l.as_str().map(String::from)) {
        Some(l) => json!({key: {"label": l, "children": children}}),
        None => json!({key: children}),
    })
}

fn desires(v: Value, path: &str) -> Result<Value, String> {
    let Value::Array(items) = v else { return Err(format!("{path}.desires: expected a list of desires")) };
    let mut kept = Vec::new();
    let mut first_err = None;
    for (i, d) in items.into_iter().enumerate() {
        let p = format!("{path}.desires[{i}]");
        let r = (|| -> Result<Value, String> {
            let Value::Object(o) = d else { return Err(format!("{p}: expected {{\"want\", \"weight\", \"do\"}}")) };
            let want = o.get("want").or_else(|| o.get("name")).or_else(|| o.get("label")).and_then(|w| w.as_str()).unwrap_or_default().trim().to_string();
            if want.is_empty() {
                return Err(format!("{p}: a desire needs a \"want\" (what it is for)"));
            }
            let mut weight = Map::new();
            match o.get("weight") {
                Some(Value::Number(n)) => {
                    weight.insert("base".into(), json!(n.as_f64().unwrap_or(0.5)));
                }
                Some(Value::Object(w)) => {
                    for (k, v) in w {
                        if k == "believes" {
                            if let Value::Object(b) = v {
                                let b: Map<String, Value> = b.iter().filter_map(|(k, v)| v.as_f64().map(|x| (k.clone(), json!(x)))).collect();
                                weight.insert("believes".into(), Value::Object(b));
                            }
                        } else if WEIGHTS.contains(&k.as_str()) {
                            if let Some(x) = v.as_f64() {
                                weight.insert(k.clone(), json!(x));
                            }
                        } else {
                            WARNINGS.with(|w| w.borrow_mut().push(format!("{p}.weight: ignored unknown signal `{k}` (signals are {})", WEIGHTS.join(", "))));
                        }
                    }
                }
                _ => {
                    weight.insert("base".into(), json!(0.5));
                }
            }
            let body = o.get("do").or_else(|| o.get("then")).or_else(|| o.get("node")).cloned().ok_or_else(|| format!("{p}: a desire needs \"do\" (a node)"))?;
            let body = match body {
                Value::String(s) if catalog::skill(&s).is_none() => json!({"routine": s}),
                other => node(other, &format!("{p}.do"))?,
            };
            Ok(json!({"want": want, "weight": weight, "do": body}))
        })();
        match r {
            Ok(v) => kept.push(v),
            Err(e) => {
                WARNINGS.with(|w| w.borrow_mut().push(format!("dropped {e}")));
                first_err.get_or_insert(e);
            }
        }
    }
    if kept.is_empty() {
        return Err(first_err.unwrap_or_else(|| format!("{path}.desires: no valid desires")));
    }
    kept.truncate(crate::graph::MAX_CHILDREN);
    Ok(json!({"desires": kept}))
}

fn if_node(m: Map<String, Value>, path: &str) -> Result<Value, String> {
    let head = m.get("if").cloned().unwrap_or(Value::Null);
    // Nested canonical form: {"if": {"cond": C, "then": N, "else": N}}.
    let (c, then, otherwise) = match &head {
        Value::Object(o) if o.contains_key("then") || o.contains_key("cond") => {
            let o = strip_nulls(o.clone());
            (o.get("cond").cloned(), o.get("then").cloned().or_else(|| m.get("then").cloned()), o.get("else").cloned().or_else(|| m.get("else").cloned()))
        }
        _ => (Some(head.clone()), m.get("then").cloned(), m.get("else").cloned()),
    };
    let c = c.ok_or_else(|| format!("{path}.if: missing condition"))?;
    let then = then.ok_or_else(|| format!("{path}.if: missing \"then\" node"))?;
    let mut out = Map::new();
    out.insert("cond".into(), cond(c, &format!("{path}.if"))?);
    out.insert("then".into(), node(then, &format!("{path}.then"))?);
    if let Some(e) = otherwise.filter(|e| !e.is_null()) {
        out.insert("else".into(), node(e, &format!("{path}.else"))?);
    }
    Ok(json!({"if": out}))
}

fn do_node(m: Map<String, Value>, path: &str) -> Result<Value, String> {
    let d = m.get("do").cloned().unwrap_or(Value::Null);
    let mut action = match d {
        Value::String(s) => Map::from_iter([("skill".to_string(), json!(s))]),
        Value::Object(o) => strip_nulls(o),
        _ => return Err(format!("{path}.do: expected a skill name or an object with \"skill\"")),
    };
    for (k, v) in &m {
        if k != "do" && !v.is_null() {
            action.entry(k.clone()).or_insert(v.clone());
        }
    }
    let mut out = Map::new();
    let skill = action.get("skill").and_then(|s| s.as_str()).map(|s| s.trim().to_lowercase().replace(' ', "_")).ok_or_else(|| format!("{path}.do: missing \"skill\""))?;
    match skill.as_str() {
        "think" | "reconsider" | "reflect" => {
            let reason = action.get("reason").or_else(|| action.get("text")).and_then(|r| r.as_str()).unwrap_or("reconsider my plan");
            return Ok(json!({"think": reason}));
        }
        "say" | "speak" | "talk" => {
            body_check(path, "say", None)?;
            let text = action.get("text").or_else(|| action.get("message")).and_then(|r| r.as_str()).ok_or_else(|| format!("{path}.do: say needs text"))?;
            let mut out = json!({"say": {"text": text}});
            if let Some(t) = action.get("to").or_else(|| action.get("target")).cloned() {
                out["say"]["to"] = target(t, &format!("{path}.say.to"))?;
            }
            return Ok(out);
        }
        _ => {}
    }
    let spec = catalog::skill(&skill).ok_or_else(|| {
        format!("{path}.do: unknown skill `{skill}`; skills are {}", catalog::SKILLS.iter().map(|s| s.name).collect::<Vec<_>>().join(", "))
    })?;
    out.insert("skill".into(), json!(skill));
    let item = action.get("item").or_else(|| action.get("what")).or_else(|| action.get("object")).or_else(|| action.get("kind")).cloned();
    if let Some(Value::String(i)) = item {
        if spec.needs_item {
            out.insert("item".into(), json!(if matches!(skill.as_str(), "signal" | "teach") { i.trim().to_lowercase().replace(' ', "_") } else { fix_item(&i) }));
        }
    }
    if spec.needs_item && !out.contains_key("item") {
        return Err(format!("{path}.do: skill `{skill}` needs an item"));
    }
    if let Some(q) = action.get("qty").or_else(|| action.get("amount")).or_else(|| action.get("count")).or_else(|| action.get("quantity")).or_else(|| action.get("seconds")) {
        if let Some(n) = q.as_f64() {
            out.insert("qty".into(), json!(n.max(0.0).round() as u64));
        }
    }
    if let Some(Value::String(t)) = action.get("text").or_else(|| action.get("words")).or_else(|| action.get("message")) {
        out.insert("text".into(), json!(t.chars().take(400).collect::<String>()));
    }
    if let Some(Value::String(t)) = action.get("topic").or_else(|| action.get("technique")).or_else(|| action.get("about")) {
        out.insert("topic".into(), json!(t.trim().to_lowercase()));
    }
    if let Some(Value::String(w)) = action.get("want").or_else(|| action.get("for")).or_else(|| action.get("in_return")) {
        out.insert("want".into(), json!(fix_item(w)));
        let q = action.get("want_qty").or_else(|| action.get("for_qty")).and_then(|q| q.as_f64()).unwrap_or(1.0);
        out.insert("want_qty".into(), json!(q.max(1.0).round() as u64));
    }
    if let Some(t) = action.get("target").or_else(|| action.get("to")).or_else(|| action.get("from")).cloned() {
        // Any skill may be aimed (read a sign, build a wall there, sleep in a shelter: the body
        // walks there first); only wandering and waiting ignore a target.
        if !matches!(skill.as_str(), "wander" | "wait") {
            out.insert("target".into(), target(t, &format!("{path}.do.target"))?);
        }
    }
    body_check(path, &skill, out.get("item").and_then(|i| i.as_str()))?;
    if spec.needs_target && !out.contains_key("target") {
        return Err(format!("{path}.do: skill `{skill}` needs a target"));
    }
    if let Some(i) = out.get("item").and_then(|i| i.as_str()).filter(|_| skill != "signal") {
        let known = i == "food" || catalog::item(i).is_some() || catalog::STRUCTURES.contains(&i) || catalog::TERRAIN_BUILDS.contains(&i) || catalog::technique(i).is_some();
        if !known {
            return Err(format!("{path}.do: unknown item `{i}`; items are food, {}", catalog::ITEMS.iter().map(|x| x.name).collect::<Vec<_>>().join(", ")));
        }
    }
    Ok(json!({"do": out}))
}

/// Map loose item names onto the catalog (`raw meat` → `meat`, `Cooked Fish` → `cooked_fish`).
pub fn fix_item(i: &str) -> String {
    let mut s = i.trim().to_lowercase().replace([' ', '-'], "_");
    if let Some(rest) = s.strip_prefix("raw_") {
        s = rest.to_string();
    }
    match s.as_str() {
        "berry" => "berries".into(),
        "fibre" | "reed" | "reeds" => "fiber".into(),
        "stones" | "rock" | "rocks" => "stone".into(),
        "logs" | "log" | "timber" => "wood".into(),
        "any_food" | "meal" => "food".into(),
        _ => s,
    }
}

pub fn target(v: Value, path: &str) -> Result<Value, String> {
    Ok(match v {
        Value::String(s) => {
            let l = s.trim().to_lowercase();
            match l.as_str() {
                "self" | "me" | "myself" => json!("self"),
                "attacker" | "speaker" | "home" | "wander" | "parent" => json!(l),
                _ if catalog::kind_class(&l).is_some() => json!({"nearest": l}),
                _ => json!({"named": s.trim()}),
            }
        }
        Value::Number(n) => json!({"id": n}),
        Value::Array(a) if a.len() == 2 && a.iter().all(|x| x.is_number()) => json!({"at": a}),
        Value::Object(o) => {
            let o = strip_nulls(o);
            let filter = |n: &Value| -> Result<Value, String> {
                let f = match n {
                    Value::Object(f) => {
                        let f = strip_nulls(f.clone());
                        let mut out = Map::new();
                        for k in ["kind", "relation", "mine"] {
                            if let Some(v) = f.get(k) {
                                out.insert(k.into(), v.clone());
                            }
                        }
                        Value::Object(out)
                    }
                    other => other.clone(),
                };
                let kind = f.as_str().or_else(|| f.get("kind").and_then(|k| k.as_str())).unwrap_or_default();
                if catalog::kind_class(kind).is_none() {
                    return Err(format!("{path}: unknown kind `{kind}`"));
                }
                Ok(f)
            };
            if let Some(n) = o.get("nearest") {
                return Ok(json!({"nearest": filter(n)?}));
            }
            if o.contains_key("kind") {
                return Ok(json!({"nearest": filter(&Value::Object(o.clone()))?}));
            }
            if let Some(n) = o.get("name").or_else(|| o.get("named")) {
                return Ok(json!({"named": n}));
            }
            if let Some(i) = o.get("id") {
                return Ok(json!({"id": i}));
            }
            if let Some(p) = o.get("place") {
                return Ok(json!({"place": p}));
            }
            if let Some(a) = o.get("at") {
                return Ok(json!({"at": a}));
            }
            if let (Some(x), Some(y)) = (o.get("x"), o.get("y")) {
                return Ok(json!({"at": [x, y]}));
            }
            return Err(format!("{path}: unknown target {:?}; use \"self\", \"attacker\", \"speaker\", \"home\", {{\"nearest\": kind}}, {{\"id\": n}}, {{\"named\": name}}, {{\"place\": name}} or {{\"at\": [x, y]}}", o.keys().collect::<Vec<_>>()));
        }
        other => return Err(format!("{path}: invalid target {other}")),
    })
}

fn cmp(v: Value, path: &str, name: &str) -> Result<Value, String> {
    match v {
        Value::Object(o) => {
            let mut out = Map::new();
            for (k, x) in strip_nulls(o) {
                let key = match k.as_str() {
                    "above" | ">" | ">=" | "gt" | "gte" | "min" | "over" | "more_than" => "above",
                    "below" | "<" | "<=" | "lt" | "lte" | "max" | "under" | "less_than" => "below",
                    other => return Err(format!("{path}.{name}: use {{\"above\": n}} or {{\"below\": n}}, not `{other}`")),
                };
                out.insert(key.into(), x);
            }
            Ok(Value::Object(out))
        }
        _ => Err(format!("{path}.{name}: use {{\"{name}\": {{\"above\": n}}}} or {{\"below\": n}}")),
    }
}

pub fn cond(v: Value, path: &str) -> Result<Value, String> {
    match v {
        Value::Array(a) => cond(json!({"all": a}), path),
        Value::Object(o) => {
            let o = strip_nulls(o);
            if o.len() > 1 {
                // Several conditions side by side mean all of them.
                let parts: Result<Vec<Value>, String> = o.into_iter().map(|(k, v)| cond(json!({k: v}), path)).collect();
                return Ok(json!({"all": parts?}));
            }
            let Some((k, v)) = o.into_iter().next() else { return Err(format!("{path}: empty condition")) };
            let key = match k.as_str() {
                "and" => "all",
                "or" => "any",
                "hp" => "health",
                "hurt" | "attacked_within" => "hurt_within",
                "heard" => "heard_within",
                "is_night" => "night",
                "belief" | "judgment" => "believes",
                "see" | "can_see" => "sees",
                "have" | "holding" => "has",
                other => other,
            }
            .to_string();
            let p = format!("{path}.{key}");
            Ok(match key.as_str() {
                "all" | "any" => {
                    let list = match v {
                        Value::Array(a) => a,
                        other => vec![other],
                    };
                    let parts: Result<Vec<Value>, String> = list.into_iter().enumerate().map(|(i, c)| cond(c, &format!("{p}[{i}]"))).collect();
                    json!({key: parts?})
                }
                "not" => {
                    let inner = match v {
                        Value::Array(mut a) if a.len() == 1 => a.remove(0),
                        other => other,
                    };
                    json!({"not": cond(inner, &p)?})
                }
                "hour" | "time" | "time_of_day" => {
                    let c = cmp(v, path, "hour")?;
                    json!({"hour": c})
                }
                "hunger" | "energy" | "health" => {
                    let c = cmp(v, path, &key)?;
                    json!({key: c})
                }
                "sees" => json!({"sees": target(v, &p)?}),
                "near" => {
                    let mut o = match v {
                        Value::Object(o) => strip_nulls(o),
                        other => Map::from_iter([("target".to_string(), other)]),
                    };
                    let t = o.remove("target").or_else(|| o.remove("kind").map(|k| json!({"nearest": k}))).ok_or_else(|| format!("{p}: missing target"))?;
                    let within = o.get("within").or_else(|| o.get("distance")).or_else(|| o.get("radius")).and_then(|w| w.as_f64()).unwrap_or(3.0);
                    json!({"near": {"target": target(t, &p)?, "within": within}})
                }
                "has" => match v {
                    Value::String(s) if fix_item(&s) != "food" && catalog::item(&fix_item(&s)).is_none() => return Err(format!("{p}: `{s}` is not something you can carry")),
                    Value::String(s) => json!({"has": {"item": fix_item(&s)}}),
                    Value::Object(o) => {
                        let o = strip_nulls(o);
                        let item = o.get("item").and_then(|i| i.as_str()).map(fix_item).ok_or_else(|| format!("{p}: missing item"))?;
                        if item != "food" && catalog::item(&item).is_none() {
                            return Err(format!("{p}: `{item}` is not something you can carry"));
                        }
                        let n = o.get("at_least").or_else(|| o.get("count")).or_else(|| o.get("qty")).or_else(|| o.get("min")).and_then(|n| n.as_u64()).unwrap_or(1);
                        json!({"has": {"item": item, "at_least": n}})
                    }
                    _ => return Err(format!("{p}: expected {{\"item\": name, \"at_least\": n}}")),
                },
                "believes" => match v {
                    Value::String(s) => json!({"believes": s}),
                    Value::Object(o) => {
                        let o = strip_nulls(o);
                        let key = o.get("key").or_else(|| o.get("judgment")).cloned().ok_or_else(|| format!("{p}: missing key"))?;
                        let above = o.get("above").or_else(|| o.get("value")).cloned().unwrap_or(json!(0.5));
                        json!({"believes": {"key": key, "above": above}})
                    }
                    _ => return Err(format!("{p}: expected a judgment key")),
                },
                "hurt_within" | "heard_within" | "chance" => {
                    let n = match &v {
                        Value::Bool(true) => if key == "chance" { 0.5 } else { 20.0 },
                        other => other.as_f64().or_else(|| other.get("seconds").and_then(|x| x.as_f64())).ok_or_else(|| format!("{p}: expected a number"))?,
                    };
                    json!({key: n})
                }
                "within" => return cond(json!({"near": v}), path),
                "night" => json!({"night": v.as_bool().unwrap_or(true)}),
                "threatened" | "under_attack" | "incoming_attack" => json!({"threatened": v.as_bool().unwrap_or(true)}),
                "day" => json!({"night": !v.as_bool().unwrap_or(true)}),
                other => return Err(format!("{path}: unknown condition `{other}`; conditions are {CONDS}")),
            })
        }
        other => Err(format!("{path}: expected a condition object, got {other}")),
    }
}

#[cfg(test)]
mod tests {
    use crate::graph::{from_value, outline};
    use serde_json::json;

    #[test]
    fn accepts_flat_and_slipped_forms() {
        let g = from_value(json!({"first": [
            {"if": {"hurt_within": 6}, "then": {"flee": {"target": "attacker"}}, "else": null},
            {"if": {"cond": {"near": {"target": {"nearest": {"kind": "wolf"}}, "within": 5}}, "then": {"flee": {"target": {"nearest": {"kind": "wolf"}}}}, "else": null}},
            {"if": {"hunger": {">": 55}, "has": "food"}, "then": {"do": "eat", "item": "food", "target": "self"}},
            {"if": {"and": [{"night": true}, {"not": [{"near": {"target": "home", "within": 2}}]}]}, "then": {"do": {"skill": "goto", "target": "home"}}},
            {"seq": [{"do": "gather", "target": "berry_bush"}, {"say": "Found berries!", "to": 6}, {"wait": {"seconds": 3}}, "wander"]}
        ]}))
        .unwrap();
        let o = outline(&g.root);
        assert!(o.contains("flee → attacker"), "{o}");
        assert!(o.contains("has 1 food and hunger > 55"), "{o}");
        assert!(o.contains("gather → nearest berry_bush"), "{o}");
    }

    #[test]
    fn prunes_bad_branches_and_reports_them() {
        let (g, w) = crate::graph::from_value_lenient(json!({"first": [
            {"if": {"hunger": {"above": 50}}, "then": {"teleport": {}}},
            {"do": "eat", "item": "raw meat"},
            {"do": "think", "reason": "what next"},
            {}
        ]})).unwrap();
        assert_eq!(w.len(), 1, "{w:?}");
        assert!(w[0].contains("graph.first[0].then"), "{w:?}");
        let o = outline(&g.root);
        assert!(o.contains("eat meat") && o.contains("think: what next"), "{o}");
    }

    #[test]
    fn bodies_limit_what_graphs_can_do() {
        let species = crate::species::parse(include_str!("../../seeds/species.json")).unwrap();
        let wolf = &species["wolf"];
        let (g, pruned) = crate::graph::from_value_for(json!({"first": [
            {"say": "hello"},
            {"do": "build", "item": "campfire"},
            {"do": "signal", "item": "moo"},
            {"do": "signal", "item": "howl"},
            {"do": "attack", "target": {"nearest": "deer"}}
        ]}), wolf).unwrap();
        assert_eq!(pruned.len(), 3, "{pruned:?}");
        assert!(pruned[0].contains("no words"));
        let o = outline(&g.root);
        assert!(o.contains("signal howl") && o.contains("attack"), "{o}");
        assert!(crate::species::skills_help(wolf).contains("signal"));
        assert!(!crate::species::skills_help(wolf).contains("build"));
    }

    #[test]
    fn errors_name_the_path() {
        let e = from_value(json!({"if": {"hunger": {"above": 50}}, "then": {"teleport": {}}})).unwrap_err();
        assert!(e.contains("graph.then"), "{e}");
        let e = from_value(json!({"if": {"mood": "sad"}, "then": {"do": "rest"}})).unwrap_err();
        assert!(e.contains("unknown condition `mood`"), "{e}");
    }
}
