//! What each script function reads of its parameters, derived once per script from its AST
//! (Rhai's `internals` feature: `AST::walk`).
//!
//! A law is called with the context map `a` (`a.actor.hunger`, `a.target.inv["armor"]`). The
//! engine builds only the fields the law reads ([`super::context`]), and refuses at install a law
//! that reads a field the engine does not provide.
//!
//! The analysis is conservative: whenever a value's use is not a plain field read (passed to a
//! built-in, compared, returned, stored, iterated, indexed by a computed key), all of it counts as
//! read. Reads through helper functions follow each call (`inv(a, "cloak")` reads
//! `a.actor.inv["cloak"]`), and a `let` that names part of the context (`let t = a.target;`)
//! carries its reads back to the context, when the name is bound only once in its function.

use rhai::{ASTFlags, ASTNode, Expr, Stmt, AST};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

/// Deeper reads than this count as reading all of the value at this depth.
const MAX_DEPTH: usize = 6;

/// What a function reads of one value: all of it, or some of its keys; and keys given by the
/// value of one of the function's own parameters (resolved at each call site).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Use {
    pub all: bool,
    pub keys: BTreeMap<String, Use>,
    pub by_param: BTreeSet<usize>,
}

impl Use {
    fn node(&mut self, path: &[String]) -> &mut Use {
        let mut n = self;
        for (i, k) in path.iter().enumerate() {
            if i == MAX_DEPTH {
                n.all = true;
                break;
            }
            n = n.keys.entry(k.clone()).or_default();
        }
        n
    }

    /// Merge what a callee reads of its parameter `cu` into this value, read at a call site whose
    /// arguments are `args`.
    fn absorb(&mut self, cu: &Use, args: &[Arg], depth: usize) {
        self.all |= cu.all;
        for &k in &cu.by_param {
            match args.get(k) {
                Some(Arg::Literal(s)) if depth < MAX_DEPTH => {
                    self.keys.entry(s.clone()).or_default();
                },
                Some(Arg::Param(j)) => {
                    self.by_param.insert(*j);
                },
                _ => self.all = true,
            }
        }
        for (k, u) in &cu.keys {
            if depth >= MAX_DEPTH {
                self.all = true;
                return;
            }
            self.keys.entry(k.clone()).or_default().absorb(u, args, depth + 1);
        }
    }
}

/// One step of a read after its root variable.
#[derive(Clone, Debug)]
enum Seg {
    /// `.name` or `["name"]`.
    Key(String),
    /// `[v]`: a key held in variable `v`.
    Var(String),
    /// A method call or a computed key: the value is used in a way the analysis does not follow.
    Opaque,
}

/// A call argument, as far as keys go.
#[derive(Clone, Debug)]
enum Arg {
    Literal(String),
    /// A parameter of the calling function (its index, resolved later).
    Param(usize),
    Other,
}

#[derive(Clone, Debug)]
enum Sink {
    /// Used as a whole value.
    All,
    /// `let NAME = <read>`.
    Bind(String),
    /// Argument `index` of a call to `callee` with these arguments.
    Arg { callee: String, index: usize, args: Vec<RawArg> },
}

#[derive(Clone, Debug)]
enum RawArg {
    Literal(String),
    Var(String),
    Other,
}

#[derive(Clone, Debug)]
struct Read {
    root: String,
    path: Vec<Seg>,
    sink: Sink,
}

#[derive(Default)]
struct FnFacts {
    params: Vec<String>,
    reads: Vec<Read>,
    /// How many times each name is bound in the function: parameters, `let`, `for` and plain
    /// assignments.
    bound: HashMap<String, usize>,
}

impl FnFacts {
    fn precise(&self, name: &str) -> bool {
        self.bound.get(name).copied().unwrap_or(0) == 1
    }
}

/// What every script function reads of its parameters.
#[derive(Debug, Default)]
pub struct Fields {
    summaries: HashMap<(String, usize), Vec<Use>>,
    /// The script does something the analysis cannot follow (a call that sees its caller's
    /// variables, a statement outside any function body): every law gets the whole context.
    gave_up: bool,
}

impl Fields {
    /// What `name` (with `arity` parameters) reads of each parameter; None when the analysis
    /// cannot say (then all of every argument counts as read).
    pub fn of(&self, name: &str, arity: usize) -> Option<&[Use]> {
        if self.gave_up {
            return None;
        }
        self.summaries.get(&(name.to_string(), arity)).map(|v| v.as_slice())
    }

    /// These summaries with `top`'s over them (a script whose functions replace some of these):
    /// what each function reads, each from its own source. Either giving up gives up.
    pub fn under(mut self, top: Fields) -> Fields {
        if self.gave_up || top.gave_up {
            return Fields { summaries: HashMap::new(), gave_up: true };
        }
        self.summaries.extend(top.summaries);
        self
    }

    pub fn analyze(ast: &AST) -> Fields {
        let defs: Vec<_> = ast.iter_fn_def().collect();
        let key = |p: rhai::Position| (p.line().unwrap_or(0), p.position().unwrap_or(0));
        let spans: Vec<((usize, usize), (usize, usize), usize)> = defs.iter().enumerate().map(|(i, f)| (key(f.body.start_position()), key(f.body.end_position()), i)).collect();
        let mut facts: Vec<FnFacts> = defs
            .iter()
            .map(|f| {
                let params: Vec<String> = f.params.iter().map(|p| p.to_string()).collect();
                let mut bound = HashMap::new();
                for p in &params {
                    *bound.entry(p.clone()).or_insert(0) += 1;
                }
                FnFacts { params, reads: Vec::new(), bound }
            })
            .collect();
        let mut gave_up = false;
        let mut claimed: HashSet<usize> = HashSet::new();
        let mut current: Option<usize> = None;
        let mut top: usize = 0;
        ast.walk(&mut |path: &[ASTNode]| {
            if path.len() == 1 {
                // A statement at the top of a function body: which function it belongs to.
                let p = match &path[0] {
                    ASTNode::Stmt(s) => s.position(),
                    ASTNode::Expr(e) => e.position(),
                    _ => rhai::Position::NONE,
                };
                let at = key(p);
                current = if p.is_none() { None } else { spans.iter().find(|(s, e, _)| *s <= at && at <= *e).map(|x| x.2) };
                top += 1;
            }
            let node = &path[path.len() - 1];
            let parent = (path.len() >= 2).then(|| &path[path.len() - 2]);
            match node {
                ASTNode::Stmt(s) => {
                    let Some(f) = current else { return true };
                    let names: Vec<String> = match s {
                        Stmt::Var(x, ..) => vec![x.0.name.to_string()],
                        Stmt::For(x, ..) => std::iter::once(x.0.name.to_string()).chain(x.1.as_ref().map(|i| i.name.to_string())).collect(),
                        Stmt::Assignment(x) => match &x.1.lhs {
                            Expr::Variable(v, ..) => vec![v.1.to_string()],
                            _ => vec![],
                        },
                        _ => vec![],
                    };
                    for n in names {
                        *facts[f].bound.entry(n).or_insert(0) += 1;
                    }
                    if let Stmt::FnCall(c, ..) = s {
                        if c.capture_parent_scope {
                            gave_up = true;
                        }
                    }
                },
                ASTNode::Expr(e) => {
                    let e: &Expr = e;
                    let ptr = e as *const Expr as usize;
                    if claimed.contains(&ptr) {
                        return true;
                    }
                    if let Expr::FnCall(c, ..) = e {
                        if c.capture_parent_scope {
                            gave_up = true;
                        }
                    }
                    let (root, segs) = match e {
                        Expr::Variable(v, ..) => (v.1.to_string(), Vec::new()),
                        Expr::Dot(..) | Expr::Index(..) => {
                            let mut segs = Vec::new();
                            let base = chain(e, &mut segs, &mut claimed);
                            match base {
                                Expr::Variable(v, ..) => {
                                    claimed.insert(base as *const Expr as usize);
                                    (v.1.to_string(), segs)
                                },
                                _ => return true,
                            }
                        },
                        _ => return true,
                    };
                    let Some(f) = current else {
                        // A read outside any function body the analysis can place.
                        gave_up = true;
                        return true;
                    };
                    let sink = sink_of(e, parent);
                    facts[f].reads.push(Read { root, path: segs, sink });
                },
                _ => {},
            }
            true
        });
        if gave_up {
            return Fields { summaries: HashMap::new(), gave_up: true };
        }
        let index: HashMap<(String, usize), usize> = defs.iter().enumerate().map(|(i, f)| ((f.name.to_string(), f.params.len()), i)).collect();
        let mut sums: Vec<Vec<Use>> = facts.iter().map(|f| vec![Use::default(); f.params.len()]).collect();
        // Fixed point: summaries only grow, and are bounded by the program's names and depth.
        for _ in 0..64 {
            let mut changed = false;
            for (i, f) in facts.iter().enumerate() {
                let next = summarize(f, &sums, &index);
                if next != sums[i] {
                    sums[i] = next;
                    changed = true;
                }
            }
            if !changed {
                let summaries = defs.iter().zip(sums).map(|(d, s)| ((d.name.to_string(), d.params.len()), s)).collect();
                return Fields { summaries, gave_up: false };
            }
        }
        Fields { summaries: HashMap::new(), gave_up: true }
    }
}

/// Decode a `.`/`[]` chain: its base expression, and the steps after it. Structural nodes are
/// claimed so the walk does not take them for reads of their own; index keys that are
/// expressions stay unclaimed and are reads in their own right.
fn chain<'a>(e: &'a Expr, segs: &mut Vec<Seg>, claimed: &mut HashSet<usize>) -> &'a Expr {
    match e {
        Expr::Dot(b, o, _) | Expr::Index(b, o, _) => {
            rest(&b.rhs, matches!(e, Expr::Dot(..)), o.intersects(ASTFlags::BREAK), segs, claimed);
            &b.lhs
        },
        _ => e,
    }
}

/// The steps after a `.` (`dot`) or `[`: `r` is the step itself, or (unless the parent ends the
/// chain) a node whose left side is the step and whose right side continues the chain.
fn rest(r: &Expr, dot: bool, brk: bool, segs: &mut Vec<Seg>, claimed: &mut HashSet<usize>) {
    match r {
        Expr::Dot(b, o, _) | Expr::Index(b, o, _) if !brk => {
            claimed.insert(r as *const Expr as usize);
            step(&b.lhs, dot, segs, claimed);
            rest(&b.rhs, matches!(r, Expr::Dot(..)), o.intersects(ASTFlags::BREAK), segs, claimed);
        },
        _ => step(r, dot, segs, claimed),
    }
}

fn step(x: &Expr, dot: bool, segs: &mut Vec<Seg>, claimed: &mut HashSet<usize>) {
    let ptr = x as *const Expr as usize;
    let seg = if dot {
        claimed.insert(ptr);
        match x {
            Expr::Property(p, _) => Seg::Key(p.2.to_string()),
            _ => Seg::Opaque,
        }
    } else {
        match x {
            Expr::StringConstant(s, _) => {
                claimed.insert(ptr);
                Seg::Key(s.to_string())
            },
            // The key variable is also a read of its own (unclaimed).
            Expr::Variable(v, ..) => Seg::Var(v.1.to_string()),
            _ => Seg::Opaque,
        }
    };
    segs.push(seg);
}

/// How a read is used, from the node above it.
fn sink_of(e: &Expr, parent: Option<&ASTNode>) -> Sink {
    let me = e as *const Expr as usize;
    let call = match parent {
        Some(ASTNode::Expr(Expr::FnCall(c, ..))) => Some(c),
        Some(ASTNode::Stmt(Stmt::FnCall(c, ..))) => Some(c),
        Some(ASTNode::Stmt(Stmt::Var(x, ..))) if (&x.1 as *const Expr as usize) == me => return Sink::Bind(x.0.name.to_string()),
        _ => None,
    };
    let Some(c) = call else { return Sink::All };
    if !c.namespace.is_empty() {
        return Sink::All;
    }
    let Some(index) = c.args.iter().position(|a| (a as *const Expr as usize) == me) else { return Sink::All };
    let args = c
        .args
        .iter()
        .map(|a| match a {
            Expr::StringConstant(s, _) => RawArg::Literal(s.to_string()),
            Expr::Variable(v, ..) => RawArg::Var(v.1.to_string()),
            _ => RawArg::Other,
        })
        .collect();
    Sink::Arg { callee: c.name.to_string(), index, args }
}

/// One pass: what a function reads of each parameter, given its callees' current summaries.
fn summarize(f: &FnFacts, sums: &[Vec<Use>], index: &HashMap<(String, usize), usize>) -> Vec<Use> {
    let mut out = vec![Use::default(); f.params.len()];
    // A parameter bound again (`let a = a.target;`) cannot be followed: all of it is read.
    for (i, p) in f.params.iter().enumerate() {
        if !f.precise(p) {
            out[i].all = true;
        }
    }
    let param = |n: &str| f.params.iter().position(|p| p == n).filter(|_| f.precise(n));
    for r in &f.reads {
        let Some((pi, mut path)) = resolve(f, &r.root, 0) else { continue };
        let mut tail: Option<&Seg> = None;
        for s in &r.path {
            match s {
                Seg::Key(k) => path.push(k.clone()),
                other => {
                    tail = Some(other);
                    break;
                },
            }
        }
        let node = out[pi].node(&path);
        match tail {
            Some(Seg::Var(v)) => match param(v) {
                Some(j) => {
                    node.by_param.insert(j);
                },
                None => node.all = true,
            },
            Some(_) => node.all = true,
            None => match &r.sink {
                Sink::All => node.all = true,
                Sink::Bind(name) => {
                    // A name for part of the context: its uses are the reads. Bound more than
                    // once, it cannot be followed.
                    if !f.precise(name) {
                        node.all = true;
                    }
                },
                Sink::Arg { callee, index: ai, args } => match index.get(&(callee.clone(), args.len())) {
                    Some(&ci) => {
                        let args: Vec<Arg> = args
                            .iter()
                            .map(|a| match a {
                                RawArg::Literal(s) => Arg::Literal(s.clone()),
                                RawArg::Var(v) => param(v).map_or(Arg::Other, Arg::Param),
                                RawArg::Other => Arg::Other,
                            })
                            .collect();
                        node.absorb(&sums[ci][*ai], &args, path.len());
                    },
                    None => node.all = true,
                },
            },
        }
    }
    out
}

/// The parameter a variable stands for, and the path into it: a parameter itself, or a name
/// bound once to a plain path into one (`let t = a.target;`).
fn resolve(f: &FnFacts, name: &str, depth: usize) -> Option<(usize, Vec<String>)> {
    if depth > 8 || !f.precise(name) {
        return None;
    }
    if let Some(i) = f.params.iter().position(|p| p == name) {
        return Some((i, Vec::new()));
    }
    let b = f.reads.iter().find(|r| matches!(&r.sink, Sink::Bind(n) if n == name))?;
    let (pi, mut path) = resolve(f, &b.root, depth + 1)?;
    for s in &b.path {
        match s {
            Seg::Key(k) => path.push(k.clone()),
            _ => return None,
        }
    }
    Some((pi, path))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn reads(src: &str, f: &str, arity: usize) -> Vec<Use> {
        let e = rhai::Engine::new_raw();
        let ast = e.compile(src).unwrap();
        Fields::analyze(&ast).of(f, arity).expect("analyzed").to_vec()
    }

    fn keys(u: &Use) -> Vec<String> {
        fn go(u: &Use, at: &str, out: &mut Vec<String>) {
            if u.all {
                out.push(format!("{at}*"));
            }
            for p in &u.by_param {
                out.push(format!("{at}[${p}]"));
            }
            for (k, v) in &u.keys {
                let here = if at.is_empty() { k.clone() } else { format!("{at}.{k}") };
                if v.keys.is_empty() && !v.all && v.by_param.is_empty() {
                    out.push(here);
                } else {
                    go(v, &here, out);
                }
            }
        }
        let mut out = Vec::new();
        go(u, "", &mut out);
        out
    }

    #[test]
    fn reads_follow_fields_helpers_and_names() {
        let src = r#"
fn inv(a, item) { let n = a.actor.inv[item]; if n == () { 0 } else { n } }
fn cold(a) { a.night && !a.actor.near_fire && inv(a, "cloak") == 0 }
fn law(a) {
    let t = a.target;
    if t.stage == "child" || cold(a) { return 1; }
    let armor = a.target.inv["armor"];
    a.actor.kind == "wolf"
}
"#;
        // `armor` is bound and never used: the entry is kept, nothing below it is read.
        assert_eq!(keys(&reads(src, "law", 1)[0]), ["actor.inv.cloak", "actor.kind*", "actor.near_fire*", "night*", "target.inv.armor", "target.stage*"]);
        assert_eq!(keys(&reads(src, "inv", 2)[0]), ["actor.inv[$1]"]);
    }

    #[test]
    fn whole_uses_and_rebinding_read_everything_below() {
        let src = r#"
fn keysum(a) { let n = 0; for k in a.actor.inv.keys() { n += a.actor.inv[k]; } n }
fn passed(a) { type_of(a.target) }
fn rebound(a) { let t = a.target; t = a.actor; t.hp }
fn shadow(a) { let a = a.target; a.hp }
fn method(a) { a.actor.knows.contains("fire") }
fn dynamic(a) { a.actor[a.item] }
"#;
        assert_eq!(keys(&reads(src, "keysum", 1)[0]), ["actor.inv*"]);
        assert_eq!(keys(&reads(src, "passed", 1)[0]), ["target*"]);
        assert_eq!(keys(&reads(src, "rebound", 1)[0]), ["actor*", "target*"]);
        assert_eq!(keys(&reads(src, "shadow", 1)[0]), ["*"]);
        assert_eq!(keys(&reads(src, "method", 1)[0]), ["actor.knows*"]);
        assert_eq!(keys(&reads(src, "dynamic", 1)[0]), ["actor*", "item*"]);
    }

    #[test]
    fn a_call_that_sees_its_callers_variables_cannot_be_followed() {
        let e = rhai::Engine::new_raw();
        let ast = e.compile("fn peek() { a.actor.hp }\nfn law(a) { peek!() }").unwrap();
        assert!(Fields::analyze(&ast).of("law", 1).is_none());
    }
}
