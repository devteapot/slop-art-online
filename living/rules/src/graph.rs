//! Behavior graph: the reactive policy a mind installs and the authority evaluates.
//!
//! JSON shape (one key per node), for example:
//! `{"first":[{"if":{"cond":{"hunger":{"above":60}},"then":{"do":{"skill":"eat","item":"berries"}}}},
//!            {"do":{"skill":"gather","target":{"nearest":"berry_bush"}}}]}`

use serde::{Deserialize, Serialize};

/// A graph as a mind writes it (the top level or one routine) stays within these limits;
/// the compiled graph, with routines inlined, may be much larger.
pub const MAX_NODES: usize = 80;
pub const MAX_DEPTH: usize = 11;
/// Limits for a compiled graph (top level with its routines inlined).
pub const MAX_COMPILED_NODES: usize = 800;
pub const MAX_COMPILED_DEPTH: usize = 40;
/// How deep routines may call routines.
pub const MAX_ROUTINE_NESTING: usize = 4;
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
    /// Run one of the character's own routines (inlined when the graph is compiled).
    Routine(String),
    /// Weighted desires: each check, the strongest desire that can act now wins.
    Desires(Vec<Desire>),
}

/// One desire: what it is for, how strongly it is felt, and what it does.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Desire {
    pub want: String,
    #[serde(default)]
    pub weight: Weight,
    #[serde(rename = "do")]
    pub body: Box<Node>,
}

/// Strength of a desire: a base plus what makes it stronger or weaker (each signal is 0..1).
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Weight {
    #[serde(default, skip_serializing_if = "is_zero")]
    pub base: f32,
    /// Hunger (0 fed .. 1 starving).
    #[serde(default, skip_serializing_if = "is_zero")]
    pub hunger: f32,
    /// Tiredness (0 rested .. 1 exhausted).
    #[serde(default, skip_serializing_if = "is_zero")]
    pub tired: f32,
    /// Hurt (0 whole .. 1 near death).
    #[serde(default, skip_serializing_if = "is_zero")]
    pub hurt: f32,
    #[serde(default, skip_serializing_if = "is_zero")]
    pub night: f32,
    #[serde(default, skip_serializing_if = "is_zero")]
    pub day: f32,
    /// Seeing an attack coming.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub threatened: f32,
    /// No other person in sight.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub alone: f32,
    /// People in sight (0 none .. 1 five or more).
    #[serde(default, skip_serializing_if = "is_zero")]
    pub company: f32,
    /// Winter.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub winter: f32,
    /// How long since this desire last acted (0 just now .. 1 an hour or more): variety.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub longing: f32,
    /// The character's own stances (judgment value 0..1) by key.
    #[serde(default, skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub believes: std::collections::BTreeMap<String, f32>,
}

fn is_zero(x: &f32) -> bool {
    *x == 0.0
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
    /// My mother or father, when in sight.
    Parent,
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

/// The routine a mind's current intention runs as, and the desire that weighs it.
pub const PLAN_ROUTINE: &str = "current plan";
pub const PLAN_WANT: &str = "the plan";

/// A top level of desires with the current plan weighed among them (replacing an earlier
/// plan desire). `None` when the top level is not desires (a flat graph has no weights).
pub fn with_plan(top: &Node, weight: Weight) -> Option<Node> {
    let Node::Desires(ds) = top else { return None };
    let mut ds: Vec<Desire> = ds.iter().filter(|d| !matches!(&*d.body, Node::Routine(r) if r.eq_ignore_ascii_case(PLAN_ROUTINE))).cloned().collect();
    ds.insert(0, Desire { want: PLAN_WANT.into(), weight, body: Box::new(Node::Routine(PLAN_ROUTINE.into())) });
    Some(Node::Desires(ds))
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

/// Routine names a graph calls.
pub fn routines_called(root: &Node) -> Vec<String> {
    preorder(root).into_iter().filter_map(|n| if let Node::Routine(r) = n { Some(r.clone()) } else { None }).collect()
}

/// Inline routine calls (`lookup` gives a routine's graph by name) into one graph. Each call
/// becomes a `first` labeled `routine:<name>` so actions can be attributed to their routine;
/// a routine that does not exist (or nests too deep) becomes a request to think about it.
pub fn expand(root: &Node, lookup: &dyn Fn(&str) -> Option<Node>) -> Node {
    fn go(n: &Node, lookup: &dyn Fn(&str) -> Option<Node>, stack: &mut Vec<String>) -> Node {
        match n {
            Node::Routine(name) => {
                let body = if stack.len() >= MAX_ROUTINE_NESTING || stack.contains(name) {
                    Node::Think(format!("my routine \"{name}\" calls itself or nests too deep"))
                } else {
                    match lookup(name) {
                        Some(g) => {
                            stack.push(name.clone());
                            let b = go(&g, lookup, stack);
                            stack.pop();
                            b
                        }
                        None => Node::Think(format!("I have no routine \"{name}\" yet")),
                    }
                };
                Node::First(Composite { label: Some(format!("routine:{name}")), children: vec![body] })
            }
            Node::First(c) => Node::First(Composite { label: c.label.clone(), children: c.children.iter().map(|x| go(x, lookup, stack)).collect() }),
            Node::Seq(c) => Node::Seq(Composite { label: c.label.clone(), children: c.children.iter().map(|x| go(x, lookup, stack)).collect() }),
            Node::If(i) => Node::If(Box::new(IfNode { cond: i.cond.clone(), then: go(&i.then, lookup, stack), otherwise: i.otherwise.as_ref().map(|e| go(e, lookup, stack)) })),
            Node::Desires(ds) => Node::Desires(ds.iter().map(|d| Desire { want: d.want.clone(), weight: d.weight.clone(), body: Box::new(go(&d.body, lookup, stack)) }).collect()),
            other => other.clone(),
        }
    }
    go(root, lookup, &mut Vec::new())
}

/// Validate a compiled graph (top level with routines inlined) against the larger limits.
pub fn validate_compiled(root: Node) -> Result<Graph, String> {
    let mut count = 0;
    check_with(&root, 1, &mut count, MAX_COMPILED_NODES, MAX_COMPILED_DEPTH)?;
    Ok(Graph { root, nodes: count })
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
    check_with(n, depth, count, MAX_NODES, MAX_DEPTH)
}

fn check_with(n: &Node, depth: usize, count: &mut usize, max_nodes: usize, max_depth: usize) -> Result<(), String> {
    let check = |n: &Node, depth: usize, count: &mut usize| check_with(n, depth, count, max_nodes, max_depth);
    *count += 1;
    if *count > max_nodes {
        return Err(format!("graph has more than {max_nodes} nodes"));
    }
    if depth > max_depth {
        return Err(format!("graph deeper than {max_depth}"));
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
        Node::Routine(name) => {
            if name.trim().is_empty() || name.len() > 60 {
                return Err("a routine name is 1..60 bytes".into());
            }
        }
        Node::Desires(ds) => {
            if ds.is_empty() || ds.len() > MAX_CHILDREN {
                return Err(format!("desires needs 1..={MAX_CHILDREN} entries"));
            }
            for d in ds {
                if d.want.trim().is_empty() || d.want.len() > 60 {
                    return Err("a desire's want is 1..60 bytes".into());
                }
                check(&d.body, depth + 1, count)?;
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
            // friend|enemy|stranger|family have broad meanings; any other word matches the
            // label a person gave that relationship (e.g. "partner", "ally", "rival").
            if r.trim().is_empty() || r.len() > 32 {
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
            Node::Desires(ds) => ds.iter().for_each(|d| go(&d.body, out)),
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
        Node::Routine(r) => format!("routine: {r}"),
        Node::Desires(ds) => format!("desires ({})", ds.iter().map(|d| d.want.as_str()).collect::<Vec<_>>().join(", ")),
    }
}

/// A desire's weight in words, e.g. "0.2 + hunger×1.5 + night×0.4".
pub fn describe_weight(w: &Weight) -> String {
    let mut parts = vec![format!("{}", w.base)];
    for (k, v) in [("hunger", w.hunger), ("tired", w.tired), ("hurt", w.hurt), ("night", w.night), ("day", w.day), ("threatened", w.threatened), ("alone", w.alone), ("company", w.company), ("winter", w.winter), ("longing", w.longing)] {
        if v != 0.0 {
            parts.push(format!("{k}×{v}"));
        }
    }
    for (k, v) in &w.believes {
        parts.push(format!("believes {k}×{v}"));
    }
    parts.join(" + ")
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
        Target::Parent => "parent".into(),
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
            Node::Desires(ds) => {
                for d in ds {
                    out.push_str(&format!("   {}want \"{}\" ({})\n", "  ".repeat(depth + 1), d.want, describe_weight(&d.weight)));
                    go(&d.body, depth + 2, id, out);
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

#[cfg(test)]
mod repertoire_tests {
    use super::*;

    #[test]
    fn desires_and_routines_parse_expand_and_validate() {
        let top = from_value(serde_json::json!({"desires": [
            {"want": "eat", "weight": {"base": 0.1, "hunger": 1.5}, "do": {"routine": "find food"}},
            {"want": "company", "weight": 0.4, "do": "visit friends"},
            {"want": "rest", "weight": {"tired": 1.2, "night": 0.5, "mood": 3}, "do": {"do": "sleep"}}
        ]}))
        .unwrap();
        let routines = |name: &str| -> Option<Node> {
            match name {
                "find food" => Some(from_value(serde_json::json!({"first": [{"if": {"has": {"item": "food"}}, "then": {"do": "eat", "item": "food"}}, {"routine": "gather berries"}]})).unwrap().root),
                "gather berries" => Some(from_value(serde_json::json!({"do": "gather", "target": {"nearest": "berry_bush"}})).unwrap().root),
                _ => None,
            }
        };
        let g = validate_compiled(expand(&top.root, &routines)).unwrap();
        let out = outline(&g.root);
        assert!(out.contains("routine:find food") && out.contains("routine:gather berries"), "{out}");
        assert!(out.contains("routine:visit friends") && out.contains("no routine"), "{out}");
        assert!(out.contains("hunger×1.5"), "{out}");
        assert_eq!(routines_called(&top.root), vec!["find food", "visit friends"]);
    }
}

#[cfg(test)]
mod seed_repertoire_tests {
    use super::*;

    #[test]
    fn a_plan_is_weighed_among_desires() {
        let top = parse(r#"{"desires": [{"want": "food", "weight": {"hunger": 1.5}, "do": {"routine": "eat"}}]}"#).unwrap().root;
        let once = with_plan(&top, Weight { base: 0.6, ..Default::default() }).unwrap();
        let twice = with_plan(&once, Weight { base: 0.3, ..Default::default() }).unwrap();
        let Node::Desires(ds) = twice else { panic!() };
        assert_eq!(ds.len(), 2);
        assert_eq!(ds[0].weight.base, 0.3);
        assert!(with_plan(&Node::Wait(1.0), Weight::default()).is_none());
        // The mind sends it back through the lenient parser: it must survive unchanged.
        let v = serde_json::to_value(&once).unwrap();
        let (g, pruned) = from_value_lenient(v).unwrap();
        assert!(pruned.is_empty(), "{pruned:?}");
        assert_eq!(g.root, once);
    }

    #[test]
    fn seed_repertoire_is_valid() {
        let r: serde_json::Value = serde_json::from_str(include_str!("../../seeds/repertoire.json")).unwrap();
        for (name, g) in r["common"].as_object().unwrap() {
            from_value(g.clone()).unwrap_or_else(|e| panic!("{name}: {e}"));
        }
        for (occ, o) in r["occupations"].as_object().unwrap() {
            from_value(o["graph"].clone()).unwrap_or_else(|e| panic!("{occ}: {e}"));
        }
        let top = serde_json::to_string(&r["top"]).unwrap().replace("WORK", "fishing");
        parse(&top).unwrap();
        // Animal ways: every routine within the species' body and size, and the desires compile.
        let species = crate::species::parse(include_str!("../../seeds/species.json")).unwrap();
        for (kind, ways) in r["species"].as_object().unwrap() {
            let sp = species.get(kind).unwrap();
            let mut routines = std::collections::HashMap::new();
            for (name, g) in ways["routines"].as_object().unwrap() {
                let (g, pruned) = from_value_for(g.clone(), sp).unwrap_or_else(|e| panic!("{kind} {name}: {e}"));
                assert!(pruned.is_empty(), "{kind} {name}: {pruned:?}");
                routines.insert(name.clone(), g.root);
            }
            let top = parse(&ways["top"].to_string()).unwrap();
            for called in routines_called(&top.root) {
                assert!(routines.contains_key(&called), "{kind}: missing routine {called}");
            }
            validate_compiled(expand(&top.root, &|n: &str| routines.get(n).cloned())).unwrap_or_else(|e| panic!("{kind}: {e}"));
        }
    }
}
