//! Behavior graph: the reactive policy a mind installs and the authority evaluates.
//!
//! JSON shape (one key per node), for example:
//! `{"first":[{"if":{"cond":{"hunger":{"above":60}},"then":{"do":{"skill":"eat","item":"berries"}}}},
//!            {"do":{"skill":"gather","target":{"nearest":"berry_bush"}}}]}`

use serde::{Deserialize, Serialize};

/// Model graphs are asked to stay within 64 nodes; the rest is headroom for body reflexes.
pub const MAX_NODES: usize = 80;
pub const MAX_DEPTH: usize = 11;
pub const MAX_CHILDREN: usize = 12;
pub const MAX_TEXT: usize = 400;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub enum Node {
    /// Reactive priority: the first child that is not failing wins; re-checked every think.
    First(Composite),
    /// Steps in order, remembering progress; fails when a step fails.
    Seq(Composite),
    /// Continuous guard.
    If(Box<IfNode>),
    /// Perform a skill (walks into range first when needed).
    Do(Action),
    /// Speak once (throttled per node).
    Say(SayNode),
    /// Wait a number of seconds.
    Wait(f32),
    /// Ask the mind to reconsider (non-blocking, throttled per node).
    Think(String),
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Composite {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    pub children: Vec<Node>,
}

impl<'de> Deserialize<'de> for Composite {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Repr {
            List(Vec<Node>),
            Full {
                #[serde(default)]
                label: Option<String>,
                children: Vec<Node>,
            },
        }
        Ok(match Repr::deserialize(d)? {
            Repr::List(children) => Composite { label: None, children },
            Repr::Full { label, children } => Composite { label, children },
        })
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct IfNode {
    pub cond: Cond,
    pub then: Node,
    #[serde(default, rename = "else", skip_serializing_if = "Option::is_none")]
    pub otherwise: Option<Node>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct SayNode {
    pub text: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub to: Option<Target>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Action {
    pub skill: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target: Option<Target>,
    /// Item for eat/give/store/take, or structure/tool kind for build/craft.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub item: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub qty: Option<u32>,
    /// Words to write (tablets and signs).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    /// A technique a written text describes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub topic: Option<String>,
    /// For trade offers: what is wanted in return.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub want: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub want_qty: Option<u32>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Cmp {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub above: Option<f32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub below: Option<f32>,
}

impl Cmp {
    pub fn test(&self, v: f32) -> bool {
        self.above.map_or(true, |a| v > a) && self.below.map_or(true, |b| v < b)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub enum Cond {
    Hunger(Cmp),
    Energy(Cmp),
    Health(Cmp),
    Has(HasCond),
    Sees(Target),
    Near(NearCond),
    /// Hurt within the last N seconds.
    HurtWithin(f32),
    /// Heard speech within the last N seconds.
    HeardWithin(f32),
    Night(bool),
    /// Hour of the day (0..24), e.g. `{"hour": {"above": 6, "below": 12}}`.
    Hour(Cmp),
    /// Someone's attack or throw aimed at me is winding up right now.
    Threatened(bool),
    /// A judgment the mind maintains from its beliefs.
    Believes(Believes),
    Chance(f32),
    All(Vec<Cond>),
    Any(Vec<Cond>),
    Not(Box<Cond>),
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct HasCond {
    pub item: String,
    #[serde(default = "one")]
    pub at_least: u32,
}

fn one() -> u32 {
    1
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct NearCond {
    pub target: Target,
    #[serde(default = "near_default")]
    pub within: f32,
}

fn near_default() -> f32 {
    3.0
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Believes {
    pub key: String,
    pub above: f32,
}

impl<'de> Deserialize<'de> for Believes {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Repr {
            Key(String),
            Full {
                key: String,
                #[serde(default)]
                above: Option<f32>,
            },
        }
        Ok(match Repr::deserialize(d)? {
            Repr::Key(key) => Believes { key, above: 0.5 },
            Repr::Full { key, above } => Believes { key, above: above.unwrap_or(0.5) },
        })
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Target {
    #[serde(rename = "self")]
    Me,
    /// Whoever most recently hurt me.
    Attacker,
    /// Whoever most recently spoke to me.
    Speaker,
    /// My place named "home", else where I started.
    Home,
    /// A random reachable spot nearby.
    Wander,
    Nearest(Filter),
    /// A perceived character by name.
    Named(String),
    /// A perceived character by id.
    Id(u32),
    /// One of my remembered named places.
    Place(String),
    At([f32; 2]),
}

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Filter {
    /// Resource, structure or creature kind (`berry_bush`, `campfire`, `person`, `deer`...).
    pub kind: String,
    /// For creatures: `friend`, `enemy`, `stranger`, `family` or `any`.
    pub relation: Option<String>,
    /// For structures: only ones I built.
    pub mine: bool,
}

impl<'de> Deserialize<'de> for Filter {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Repr {
            Kind(String),
            Full {
                kind: String,
                #[serde(default)]
                relation: Option<String>,
                #[serde(default)]
                mine: bool,
            },
        }
        Ok(match Repr::deserialize(d)? {
            Repr::Kind(kind) => Filter { kind, relation: None, mine: false },
            Repr::Full { kind, relation, mine } => Filter { kind, relation, mine },
        })
    }
}

/// A validated graph with preorder node ids (root = 0).
#[derive(Clone, Debug)]
pub struct Graph {
    pub root: Node,
    pub nodes: usize,
}

pub fn parse(json: &str) -> Result<Graph, String> {
    let v: serde_json::Value = serde_json::from_str(json).map_err(|e| format!("graph json: {e}"))?;
    from_value(v)
}

pub fn from_value(v: serde_json::Value) -> Result<Graph, String> {
    from_value_lenient(v).map(|(g, _)| g)
}

/// Parse a model-written graph for a particular body (see `normalize::graph_for`).
pub fn from_value_for(v: serde_json::Value, body: &crate::species::Species) -> Result<(Graph, Vec<String>), String> {
    let (v, warnings) = crate::normalize::graph_for(v, body)?;
    let root: Node = serde_json::from_value(v).map_err(|e| format!("graph: {e}"))?;
    Ok((validate(root)?, warnings))
}

/// Skills used anywhere in a graph (for authority-side body checks).
pub fn skills_used(root: &Node) -> Vec<String> {
    preorder(root)
        .into_iter()
        .filter_map(|n| match n {
            Node::Do(a) => Some(a.skill.clone()),
            Node::Say(_) => Some("say".into()),
            _ => None,
        })
        .collect()
}

/// Parse a model-written graph, pruning invalid branches; returns what was pruned.
pub fn from_value_lenient(v: serde_json::Value) -> Result<(Graph, Vec<String>), String> {
    let (v, warnings) = crate::normalize::graph(v)?;
    let root: Node = serde_json::from_value(v).map_err(|e| format!("graph: {e}"))?;
    Ok((validate(root)?, warnings))
}

pub fn validate(root: Node) -> Result<Graph, String> {
    let mut count = 0;
    check(&root, 1, &mut count)?;
    Ok(Graph { root, nodes: count })
}

fn check(n: &Node, depth: usize, count: &mut usize) -> Result<(), String> {
    *count += 1;
    if *count > MAX_NODES {
        return Err(format!("graph has more than {MAX_NODES} nodes"));
    }
    if depth > MAX_DEPTH {
        return Err(format!("graph deeper than {MAX_DEPTH}"));
    }
    match n {
        Node::First(c) | Node::Seq(c) => {
            if c.children.is_empty() || c.children.len() > MAX_CHILDREN {
                return Err(format!("composite needs 1..={MAX_CHILDREN} children"));
            }
            for ch in &c.children {
                check(ch, depth + 1, count)?;
            }
        }
        Node::If(i) => {
            check_cond(&i.cond, 0)?;
            check(&i.then, depth + 1, count)?;
            if let Some(e) = &i.otherwise {
                check(e, depth + 1, count)?;
            }
        }
        Node::Do(a) => {
            let spec = crate::catalog::skill(&a.skill).ok_or_else(|| format!("unknown skill `{}`", a.skill))?;
            if spec.needs_target && a.target.is_none() {
                return Err(format!("skill `{}` needs a target", a.skill));
            }
            if spec.needs_item && a.item.is_none() {
                return Err(format!("skill `{}` needs an item", a.skill));
            }
            if a.skill == "write" && a.text.as_deref().map_or(true, |t| t.trim().is_empty() || t.len() > MAX_TEXT) {
                return Err("write needs text of 1..400 bytes".into());
            }
            if let Some(t) = &a.target {
                check_target(t)?;
            }
        }
        Node::Say(s) => {
            if s.text.trim().is_empty() || s.text.len() > MAX_TEXT {
                return Err("say text must be 1..400 bytes".into());
            }
            if let Some(t) = &s.to {
                check_target(t)?;
            }
        }
        Node::Wait(s) => {
            if !(0.5..=120.0).contains(s) {
                return Err("wait must be 0.5..=120 seconds".into());
            }
        }
        Node::Think(r) => {
            if r.trim().is_empty() || r.len() > MAX_TEXT {
                return Err("think reason must be 1..400 bytes".into());
            }
        }
    }
    Ok(())
}

fn check_cond(c: &Cond, depth: usize) -> Result<(), String> {
    if depth > 6 {
        return Err("condition nested too deeply".into());
    }
    match c {
        Cond::All(v) | Cond::Any(v) => {
            if v.is_empty() || v.len() > 8 {
                return Err("all/any need 1..=8 conditions".into());
            }
            for x in v {
                check_cond(x, depth + 1)?;
            }
        }
        Cond::Not(x) => check_cond(x, depth + 1)?,
        Cond::Sees(t) => check_target(t)?,
        Cond::Near(n) => check_target(&n.target)?,
        Cond::Has(h) => {
            if h.item != "food" && crate::catalog::item(&h.item).is_none() {
                return Err(format!("unknown item `{}`", h.item));
            }
        }
        Cond::Hunger(c) | Cond::Energy(c) | Cond::Health(c) | Cond::Hour(c) => {
            if c.above.is_none() && c.below.is_none() {
                return Err("comparison needs above or below".into());
            }
        }
        Cond::Chance(p) => {
            if !(0.0..=1.0).contains(p) {
                return Err("chance must be within 0..=1".into());
            }
        }
        Cond::Believes(b) => {
            if b.key.is_empty() || b.key.len() > 64 {
                return Err("judgment key must be 1..=64 bytes".into());
            }
        }
        _ => {}
    }
    Ok(())
}

fn check_target(t: &Target) -> Result<(), String> {
    if let Target::Nearest(f) = t {
        if crate::catalog::kind_class(&f.kind).is_none() {
            return Err(format!("unknown kind `{}`", f.kind));
        }
        if let Some(r) = &f.relation {
            if !matches!(r.as_str(), "friend" | "enemy" | "stranger" | "family" | "any") {
                return Err(format!("unknown relation `{r}`"));
            }
        }
    }
    Ok(())
}

impl Graph {
    pub fn to_json(&self) -> String {
        serde_json::to_string(&self.root).unwrap_or_default()
    }
}

/// Visit nodes in preorder with their ids.
pub fn preorder<'a>(root: &'a Node) -> Vec<&'a Node> {
    fn go<'a>(n: &'a Node, out: &mut Vec<&'a Node>) {
        out.push(n);
        match n {
            Node::First(c) | Node::Seq(c) => c.children.iter().for_each(|ch| go(ch, out)),
            Node::If(i) => {
                go(&i.then, out);
                if let Some(e) = &i.otherwise {
                    go(e, out);
                }
            }
            _ => {}
        }
    }
    let mut out = Vec::new();
    go(root, &mut out);
    out
}

/// One-line description of a node (without children), used by prompts and the observer.
pub fn describe(n: &Node) -> String {
    match n {
        Node::First(c) => format!("first{}", label(c)),
        Node::Seq(c) => format!("seq{}", label(c)),
        Node::If(i) => format!("if {}", describe_cond(&i.cond)),
        Node::Do(a) => {
            let mut s = a.skill.clone();
            if let Some(i) = &a.item {
                s.push(' ');
                s.push_str(i);
            }
            if let Some(q) = a.qty {
                s.push_str(&format!(" x{q}"));
            }
            if let Some(t) = &a.target {
                s.push_str(" → ");
                s.push_str(&describe_target(t));
            }
            s
        }
        Node::Say(s) => format!("say \"{}\"", s.text),
        Node::Wait(w) => format!("wait {w}s"),
        Node::Think(r) => format!("think: {r}"),
    }
}

fn label(c: &Composite) -> String {
    c.label.as_ref().map(|l| format!(" [{l}]")).unwrap_or_default()
}

pub fn describe_target(t: &Target) -> String {
    match t {
        Target::Me => "self".into(),
        Target::Attacker => "attacker".into(),
        Target::Speaker => "speaker".into(),
        Target::Home => "home".into(),
        Target::Wander => "somewhere nearby".into(),
        Target::Nearest(f) => {
            let mut s = format!("nearest {}", f.kind);
            if let Some(r) = &f.relation {
                s.push_str(&format!(" ({r})"));
            }
            if f.mine {
                s.push_str(" (mine)");
            }
            s
        }
        Target::Named(n) => n.clone(),
        Target::Id(i) => format!("#{i}"),
        Target::Place(p) => format!("place \"{p}\""),
        Target::At([x, y]) => format!("({x:.0},{y:.0})"),
    }
}

pub fn describe_cond(c: &Cond) -> String {
    let cmp = |name: &str, c: &Cmp| {
        let mut s = name.to_string();
        if let Some(a) = c.above {
            s.push_str(&format!(" > {a}"));
        }
        if let Some(b) = c.below {
            s.push_str(&format!(" < {b}"));
        }
        s
    };
    match c {
        Cond::Hunger(x) => cmp("hunger", x),
        Cond::Energy(x) => cmp("energy", x),
        Cond::Health(x) => cmp("health", x),
        Cond::Has(h) => format!("has {} {}", h.at_least, h.item),
        Cond::Sees(t) => format!("sees {}", describe_target(t)),
        Cond::Near(n) => format!("within {} of {}", n.within, describe_target(&n.target)),
        Cond::HurtWithin(s) => format!("hurt in last {s}s"),
        Cond::HeardWithin(s) => format!("heard speech in last {s}s"),
        Cond::Hour(x) => cmp("hour", x),
        Cond::Threatened(true) => "an attack is coming at me".into(),
        Cond::Threatened(false) => "no attack coming at me".into(),
        Cond::Night(true) => "night".into(),
        Cond::Night(false) => "day".into(),
        Cond::Believes(b) => format!("believes {} > {}", b.key, b.above),
        Cond::Chance(p) => format!("chance {p}"),
        Cond::All(v) => v.iter().map(describe_cond).collect::<Vec<_>>().join(" and "),
        Cond::Any(v) => format!("({})", v.iter().map(describe_cond).collect::<Vec<_>>().join(" or ")),
        Cond::Not(x) => format!("not {}", describe_cond(x)),
    }
}

/// Indented outline with node ids, e.g. for prompts: `3  do gather → nearest berry_bush`.
pub fn outline(root: &Node) -> String {
    fn go(n: &Node, depth: usize, id: &mut usize, out: &mut String) {
        out.push_str(&format!("{:>2} {}{}\n", *id, "  ".repeat(depth), describe(n)));
        *id += 1;
        match n {
            Node::First(c) | Node::Seq(c) => c.children.iter().for_each(|ch| go(ch, depth + 1, id, out)),
            Node::If(i) => {
                go(&i.then, depth + 1, id, out);
                if let Some(e) = &i.otherwise {
                    out.push_str(&format!("   {}else\n", "  ".repeat(depth)));
                    go(e, depth + 1, id, out);
                }
            }
            _ => {}
        }
    }
    let mut out = String::new();
    let mut id = 0;
    go(root, 0, &mut id, &mut out);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_compact_and_labeled_forms() {
        let g = parse(
            r#"{"first":{"label":"daily life","children":[
                {"if":{"cond":{"all":[{"hunger":{"above":60}},{"has":{"item":"berries"}}]},"then":{"do":{"skill":"eat","item":"berries"}}}},
                {"if":{"cond":{"believes":"wolves_hunt_at_night"},"then":{"do":{"skill":"goto","target":"home"}}}},
                {"seq":[{"do":{"skill":"gather","target":{"nearest":"berry_bush"}}},{"say":{"text":"Found food!","to":{"nearest":{"kind":"person","relation":"friend"}}}},{"wait":2}]},
                {"think":"nothing left to do"}
            ]}}"#,
        )
        .unwrap();
        assert_eq!(g.nodes, 10);
        assert!(outline(&g.root).contains("believes wolves_hunt_at_night > 0.5"));
        let back = parse(&g.to_json()).unwrap();
        assert_eq!(back.root, g.root);
    }

    #[test]
    fn seed_instincts_are_valid() {
        let all: serde_json::Value = serde_json::from_str(include_str!("../../seeds/instincts.json")).unwrap();
        for (kind, g) in all.as_object().unwrap() {
            from_value(g.clone()).unwrap_or_else(|e| panic!("{kind}: {e}"));
        }
    }

    #[test]
    fn rejects_unknown_skill_and_missing_target() {
        assert!(parse(r#"{"do":{"skill":"teleport"}}"#).unwrap_err().contains("unknown skill"));
        assert!(parse(r#"{"do":{"skill":"gather"}}"#).unwrap_err().contains("needs a target"));
        assert!(parse(r#"{"do":{"skill":"gather","target":{"nearest":"unicorn"}}}"#).is_err());
    }
}
