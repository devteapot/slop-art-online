//! A character's mind in Neo4j: an open graph the character's own reasoning writes.
//!
//! Only three things are fixed:
//! - every node is a `:Concept {run, actor, key}` owned by one mind (no sharing);
//! - anchor keys connect thoughts to the world: `self`, `person:<id>`, `place:<name>`,
//!   `kind:<creature/resource/structure/item>`, `exp:<experience id>` (a kept memory);
//! - every edge carries `confidence`, `because` (experience ids in SpacetimeDB), `thought`
//!   (the reasoning episode that asserted it), `t`, and `open` (false once retracted,
//!   with `valid_to`); nothing is deleted.
//!
//! Everything else — extra labels, relationship types, properties — is chosen by the mind,
//! and can change: labels given for a concept replace its previous ones, a null property
//! clears it, re-asserting an edge updates it, duplicate concepts can be merged (edges move
//! to the survivor, which gains `MERGED_INTO` from the old one), and unreinforced edges fade
//! (confidence decays with age; faded edges close with `retracted_by = 'faded'`).
//! Identity lives on the `self` node, with `:IdentityVersion` snapshots linked by `WAS`.

use anyhow::Result;
use neo4rs::{query, BoltType, Graph};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// A graph patch written by a reasoning episode (already sanitized).
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Patch {
    pub merges: Vec<(String, String)>,
    pub nodes: Vec<NodeOp>,
    pub edges: Vec<EdgeOp>,
    pub retract: Vec<(String, String, String)>,
    pub remember: Vec<MemoryOp>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NodeOp {
    pub key: String,
    pub labels: Vec<String>,
    pub name: Option<String>,
    pub props: serde_json::Map<String, Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EdgeOp {
    pub from: String,
    pub rel: String,
    pub to: String,
    pub confidence: f64,
    pub because: Vec<u64>,
    pub props: serde_json::Map<String, Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MemoryOp {
    pub exp: u64,
    pub t: u64,
    pub gist: String,
    pub salience: f64,
    pub involves: Vec<String>,
}

/// One current edge of the mind, for prompts and the observer projection.
#[derive(Clone, Debug)]
pub struct Fact {
    pub a: String,
    pub a_name: String,
    pub a_labels: Vec<String>,
    pub rel: String,
    pub b: String,
    pub b_name: String,
    pub b_labels: Vec<String>,
    pub confidence: f64,
    pub t: u64,
    pub extra: Vec<String>,
}

pub struct Store {
    g: Graph,
    run: String,
}

/// Belief half-life: confidence decays as `c · exp(-age / TAU_MS)` unless reinforced.
pub const TAU_MS: f64 = 40.0 * 60_000.0;
/// Relationships that describe structure, not belief; they never fade.
const DURABLE: &[&str] = &["KNOWS", "FEELS", "JUDGES", "WAS", "INVOLVES", "CHILD_OF", "PARENT_OF", "MERGED_INTO"];
const FIXED_LABELS: &[&str] = &["Concept", "Self", "Memory", "IdentityVersion", "Merged"];

fn p(v: Value) -> BoltType {
    BoltType::try_from(v).unwrap_or(BoltType::Null(neo4rs::BoltNull))
}

impl Store {
    pub async fn connect(uri: &str, user: &str, password: &str, run: &str) -> Result<Self> {
        let g = Graph::new(uri, user, password).await?;
        let s = Self { g, run: run.into() };
        for q in [
            "CREATE CONSTRAINT living_concept IF NOT EXISTS FOR (c:Concept) REQUIRE (c.run, c.actor, c.key) IS UNIQUE",
            "CREATE INDEX living_concept_mind IF NOT EXISTS FOR (c:Concept) ON (c.run, c.actor)",
        ] {
            s.g.run(query(q)).await?;
        }
        Ok(s)
    }

    fn q(&self, text: &str, actor: u32) -> neo4rs::Query {
        query(text).param("run", self.run.clone()).param("actor", actor as i64)
    }

    pub async fn ensure_self(&self, actor: u32, name: &str) -> Result<()> {
        self.g.run(self.q("MERGE (s:Concept {run: $run, actor: $actor, key: 'self'}) SET s:Self, s.name = $name", actor).param("name", name)).await?;
        Ok(())
    }

    /// Apply one reasoning episode's patch transactionally.
    pub async fn apply(&self, actor: u32, patch: &Patch, thought: &str, t: u64) -> Result<()> {
        let mut txn = self.g.start_txn().await?;
        for (from, into) in &patch.merges {
            txn.run(
                self.q(
                    "MATCH (old:Concept {run: $run, actor: $actor, key: $from})
                     MERGE (new:Concept {run: $run, actor: $actor, key: $into})
                     ON CREATE SET new.created_t = $t, new.name = old.name
                     WITH old, new WHERE old <> new
                     CALL (old, new) {
                       MATCH (old)-[r {open: true}]->(x) WHERE x <> new AND NOT type(r) IN ['MERGED_INTO']
                       MERGE (new)-[r2:$(type(r)) {open: true}]->(x)
                       SET r2 += properties(r), r2.thought = $thought
                       SET r.open = false, r.valid_to = $t, r.retracted_by = $thought
                     }
                     CALL (old, new) {
                       MATCH (x)-[r {open: true}]->(old) WHERE x <> new AND NOT type(r) IN ['MERGED_INTO', 'WAS']
                       MERGE (x)-[r2:$(type(r)) {open: true}]->(new)
                       SET r2 += properties(r), r2.thought = $thought
                       SET r.open = false, r.valid_to = $t, r.retracted_by = $thought
                     }
                     SET old:Merged
                     MERGE (old)-[m:MERGED_INTO]->(new) SET m.t = $t, m.thought = $thought",
                    actor,
                )
                .param("from", from.as_str())
                .param("into", into.as_str())
                .param("t", t as i64)
                .param("thought", thought),
            )
            .await?;
        }
        if !patch.nodes.is_empty() {
            let rows: Vec<Value> = patch.nodes.iter().map(|n| json!({"key": n.key, "labels": n.labels, "name": n.name, "props": n.props})).collect();
            txn.run(
                self.q(
                    "UNWIND $rows AS n
                     MERGE (c:Concept {run: $run, actor: $actor, key: n.key})
                     ON CREATE SET c.created_t = $t
                     SET c += n.props, c.name = coalesce(n.name, c.name), c.updated_t = $t, c.thought = $thought
                     WITH c, n, [l IN labels(c) WHERE NOT l IN $fixed] AS old
                     CALL (c, n, old) {
                       WITH c, n, old WHERE size(n.labels) > 0
                       REMOVE c:$(old)
                       SET c:$(n.labels)
                     }",
                    actor,
                )
                .param("rows", p(Value::Array(rows)))
                .param("fixed", FIXED_LABELS.iter().map(|s| s.to_string()).collect::<Vec<_>>())
                .param("t", t as i64)
                .param("thought", thought),
            )
            .await?;
        }
        if !patch.remember.is_empty() {
            let rows: Vec<Value> = patch.remember.iter().map(|m| json!({"key": format!("exp:{}", m.exp), "exp": m.exp, "t": m.t, "gist": m.gist, "salience": m.salience, "involves": m.involves})).collect();
            txn.run(
                self.q(
                    "UNWIND $rows AS m
                     MERGE (c:Concept {run: $run, actor: $actor, key: m.key})
                     SET c:Memory, c.exp = m.exp, c.t = m.t, c.gist = m.gist, c.name = m.gist, c.salience = m.salience, c.thought = $thought
                     WITH c, m
                     UNWIND m.involves AS k
                     MERGE (x:Concept {run: $run, actor: $actor, key: k})
                     MERGE (c)-[:INVOLVES]->(x)",
                    actor,
                )
                .param("rows", p(Value::Array(rows)))
                .param("thought", thought),
            )
            .await?;
        }
        if !patch.edges.is_empty() {
            let rows: Vec<Value> = patch
                .edges
                .iter()
                .map(|e| json!({"from": e.from, "to": e.to, "rel": e.rel, "confidence": e.confidence, "because": e.because, "props": e.props}))
                .collect();
            txn.run(
                self.q(
                    "UNWIND $rows AS e
                     MERGE (a:Concept {run: $run, actor: $actor, key: e.from})
                     MERGE (b:Concept {run: $run, actor: $actor, key: e.to})
                     MERGE (a)-[r:$(e.rel) {open: true}]->(b)
                     ON CREATE SET r.since = $t, r.because = []
                     SET r += e.props, r.confidence = e.confidence, r.t = $t, r.thought = $thought,
                         r.because = [x IN r.because WHERE NOT x IN e.because] + e.because",
                    actor,
                )
                .param("rows", p(Value::Array(rows)))
                .param("t", t as i64)
                .param("thought", thought),
            )
            .await?;
        }
        if !patch.retract.is_empty() {
            let rows: Vec<Value> = patch.retract.iter().map(|(a, r, b)| json!({"from": a, "rel": r, "to": b})).collect();
            txn.run(
                self.q(
                    "UNWIND $rows AS x
                     MATCH (a:Concept {run: $run, actor: $actor, key: x.from})-[r {open: true}]->(b:Concept {run: $run, actor: $actor, key: x.to})
                     WHERE type(r) = x.rel
                     SET r.open = false, r.valid_to = $t, r.retracted_by = $thought",
                    actor,
                )
                .param("rows", p(Value::Array(rows)))
                .param("t", t as i64)
                .param("thought", thought),
            )
            .await?;
        }
        txn.commit().await?;
        Ok(())
    }

    /// Record who the character is now (on `self`) and keep the previous version.
    pub async fn set_identity(&self, actor: u32, version: u32, persona: &Value, why: &str, thought: &str, t: u64) -> Result<()> {
        self.g
            .run(
                self.q(
                    "MATCH (s:Concept {run: $run, actor: $actor, key: 'self'})
                     SET s.narrative = $narrative, s.values = $values, s.goals = $goals, s.traits = $traits,
                         s.mood = $mood, s.identity_version = $version, s.updated_t = $t
                     MERGE (v:Concept {run: $run, actor: $actor, key: 'identity:' + toString($version)})
                     SET v:IdentityVersion, v.version = $version, v.narrative = $narrative, v.values = $values, v.goals = $goals,
                         v.traits = $traits, v.mood = $mood, v.why = $why, v.t = $t, v.thought = $thought, v.name = 'identity v' + toString($version)
                     MERGE (s)-[:WAS]->(v)",
                    actor,
                )
                .param("version", version as i64)
                .param("narrative", persona["narrative"].as_str().unwrap_or_default())
                .param("values", p(persona["values"].clone()))
                .param("goals", p(persona["goals"].clone()))
                .param("traits", persona["traits"].to_string())
                .param("mood", persona["mood"].as_str().unwrap_or_default())
                .param("why", why)
                .param("thought", thought)
                .param("t", t as i64),
            )
            .await?;
        Ok(())
    }

    /// Current edges touching the given concepts (all of the mind when `seeds` is empty), most recent first.
    pub async fn around(&self, actor: u32, seeds: &[String], limit: usize) -> Result<Vec<Fact>> {
        let mut rows = self
            .g
            .execute(
                self.q(
                    "MATCH (s:Concept {run: $run, actor: $actor}) WHERE size($seeds) = 0 OR s.key IN $seeds
                     MATCH (s)-[r {open: true}]-(:Concept)
                     WITH DISTINCT r
                     WITH r, startNode(r) AS a, endNode(r) AS b
                     WHERE NOT type(r) IN ['WAS', 'INVOLVES', 'MERGED_INTO']
                     WITH r, a, b, coalesce(r.confidence, 0.5) * CASE WHEN type(r) IN $durable THEN 1.0 ELSE exp(-toFloat($now - coalesce(r.t, $now)) / $tau) END AS c
                     RETURN a.key AS a, coalesce(a.name, a.key) AS an, labels(a) AS al, type(r) AS rel,
                            b.key AS b, coalesce(b.name, b.key) AS bn, labels(b) AS bl,
                            c, coalesce(r.t, 0) AS t,
                            [k IN keys(r) WHERE NOT k IN ['open', 't', 'since', 'because', 'thought', 'confidence', 'valid_to', 'retracted_by'] | k + ': ' + toString(r[k])] AS extra
                     ORDER BY c * 0.5 + CASE WHEN t > $now - 600000 THEN 0.5 ELSE 0.0 END DESC, t DESC LIMIT $limit",
                    actor,
                )
                .param("seeds", seeds.to_vec())
                .param("durable", DURABLE.iter().map(|s| s.to_string()).collect::<Vec<_>>())
                .param("now", crate::llm::now_ms() as i64)
                .param("tau", TAU_MS)
                .param("limit", limit as i64),
            )
            .await?;
        let mut out = Vec::new();
        while let Some(r) = rows.next().await? {
            let strip = |v: Vec<String>| v.into_iter().filter(|l| !FIXED_LABELS.contains(&l.as_str()) || l == "Memory").collect::<Vec<_>>();
            out.push(Fact {
                a: r.get("a").unwrap_or_default(),
                a_name: r.get("an").unwrap_or_default(),
                a_labels: strip(r.get("al").unwrap_or_default()),
                rel: r.get("rel").unwrap_or_default(),
                b: r.get("b").unwrap_or_default(),
                b_name: r.get("bn").unwrap_or_default(),
                b_labels: strip(r.get("bl").unwrap_or_default()),
                confidence: r.get("c").unwrap_or(0.5),
                t: r.get::<i64>("t").unwrap_or(0) as u64,
                extra: r.get("extra").unwrap_or_default(),
            });
        }
        Ok(out)
    }

    /// Close beliefs whose decayed confidence fell below `floor`; returns how many faded.
    pub async fn fade(&self, actor: u32, floor: f64, t: u64) -> Result<i64> {
        let mut rows = self
            .g
            .execute(
                self.q(
                    "MATCH (:Concept {run: $run, actor: $actor})-[r {open: true}]->(:Concept)
                     WHERE NOT type(r) IN $durable
                       AND coalesce(r.confidence, 0.5) * exp(-toFloat($t - coalesce(r.t, $t)) / $tau) < $floor
                     SET r.open = false, r.valid_to = $t, r.retracted_by = 'faded'
                     RETURN count(r) AS n",
                    actor,
                )
                .param("durable", DURABLE.iter().map(|s| s.to_string()).collect::<Vec<_>>())
                .param("t", t as i64)
                .param("tau", TAU_MS)
                .param("floor", floor),
            )
            .await?;
        Ok(match rows.next().await? {
            Some(r) => r.get::<i64>("n").unwrap_or(0),
            None => 0,
        })
    }

    /// Size of the living part of a mind: (concepts, open edges).
    pub async fn size(&self, actor: u32) -> Result<(i64, i64)> {
        let mut rows = self
            .g
            .execute(self.q(
                "MATCH (c:Concept {run: $run, actor: $actor}) WHERE NOT c:Merged AND NOT c:IdentityVersion
                 OPTIONAL MATCH (c)-[r {open: true}]->() RETURN count(DISTINCT c) AS nodes, count(r) AS edges",
                actor,
            ))
            .await?;
        Ok(match rows.next().await? {
            Some(r) => (r.get::<i64>("nodes").unwrap_or(0), r.get::<i64>("edges").unwrap_or(0)),
            None => (0, 0),
        })
    }

    /// Concepts with their labels, properties and number of open edges (for reorganization).
    pub async fn concepts(&self, actor: u32, limit: usize) -> Result<Vec<String>> {
        let mut rows = self
            .g
            .execute(
                self.q(
                    "MATCH (c:Concept {run: $run, actor: $actor}) WHERE NOT c:Merged AND NOT c:IdentityVersion AND NOT c:Memory
                     OPTIONAL MATCH (c)-[r {open: true}]-()
                     WITH c, count(r) AS degree
                     RETURN c.key AS key, coalesce(c.name, '') AS name, [l IN labels(c) WHERE NOT l IN $fixed] AS labels, degree,
                            [k IN keys(c) WHERE NOT k IN ['run', 'actor', 'key', 'name', 'created_t', 'updated_t', 'thought', 'narrative', 'values', 'goals', 'traits', 'mood', 'identity_version'] | k + ': ' + toString(c[k])] AS props
                     ORDER BY degree DESC LIMIT $limit",
                    actor,
                )
                .param("fixed", FIXED_LABELS.iter().map(|s| s.to_string()).collect::<Vec<_>>())
                .param("limit", limit as i64),
            )
            .await?;
        let mut out = Vec::new();
        while let Some(r) = rows.next().await? {
            let key: String = r.get("key").unwrap_or_default();
            let name: String = r.get("name").unwrap_or_default();
            let labels: Vec<String> = r.get("labels").unwrap_or_default();
            let props: Vec<String> = r.get("props").unwrap_or_default();
            let degree: i64 = r.get("degree").unwrap_or(0);
            out.push(format!(
                "{key}{} [{}]{} — {degree} links",
                if name.is_empty() || name == key { String::new() } else { format!(" \"{name}\"") },
                labels.join(", "),
                if props.is_empty() { String::new() } else { format!(" {{{}}}", props.join(", ")) }
            ));
        }
        Ok(out)
    }

    /// Memories the mind chose to keep, most recent first.
    pub async fn memories(&self, actor: u32, limit: usize) -> Result<Vec<(u64, u64, String)>> {
        let mut rows = self
            .g
            .execute(self.q("MATCH (m:Memory {run: $run, actor: $actor}) RETURN m.exp AS exp, m.t AS t, m.gist AS gist ORDER BY m.t DESC LIMIT $limit", actor).param("limit", limit as i64))
            .await?;
        let mut out = Vec::new();
        while let Some(r) = rows.next().await? {
            out.push((r.get::<i64>("exp").unwrap_or(0) as u64, r.get::<i64>("t").unwrap_or(0) as u64, r.get("gist").unwrap_or_default()));
        }
        Ok(out)
    }
}

/// What the body reads, derived from the mind (never declared separately):
/// `self -FEELS {trust, affinity, label, note}-> person:<id>` → relations,
/// `self -JUDGES {value, why}-> stance:<key>` → judgments (relaxing toward 0.5 unless reinforced),
/// `place:<name>` concepts with `x`, `y` → places.
#[derive(Clone, Debug, Default)]
pub struct Projection {
    pub feelings: Vec<(u32, f64, f64, String, String)>,
    pub judgments: Vec<(String, f64, String)>,
    pub places: Vec<(String, f64, f64)>,
}

impl Store {
    pub async fn projection(&self, actor: u32) -> Result<Projection> {
        let mut out = Projection::default();
        let mut rows = self
            .g
            .execute(self.q(
                "MATCH (:Concept {run: $run, actor: $actor, key: 'self'})-[r:FEELS {open: true}]->(p:Concept)
                 WHERE p.key STARTS WITH 'person:' AND NOT p:Merged
                 RETURN p.key AS key, coalesce(r.trust, 0.0) AS trust, coalesce(r.affinity, 0.0) AS affinity,
                        coalesce(r.label, '') AS label, coalesce(r.note, '') AS note
                 ORDER BY r.t DESC LIMIT 32",
                actor,
            ))
            .await?;
        while let Some(r) = rows.next().await? {
            let key: String = r.get("key").unwrap_or_default();
            if let Some(id) = key.strip_prefix("person:").and_then(|s| s.parse::<u32>().ok()) {
                let num = |k: &str| r.get::<f64>(k).or_else(|_| r.get::<i64>(k).map(|v| v as f64)).unwrap_or(0.0);
                out.feelings.push((id, num("trust"), num("affinity"), r.get("label").unwrap_or_default(), r.get("note").unwrap_or_default()));
            }
        }
        let mut rows = self
            .g
            .execute(
                self.q(
                    "MATCH (:Concept {run: $run, actor: $actor, key: 'self'})-[r:JUDGES {open: true}]->(j:Concept)
                     WHERE NOT j:Merged
                     WITH j, r, toFloat(coalesce(r.value, 0.5)) AS v, exp(-toFloat($now - coalesce(r.t, $now)) / $tau) AS keep
                     RETURN j.key AS key, 0.5 + (v - 0.5) * keep AS value, coalesce(r.why, '') AS why
                     ORDER BY r.t DESC LIMIT 32",
                    actor,
                )
                .param("now", crate::llm::now_ms() as i64)
                .param("tau", TAU_MS),
            )
            .await?;
        while let Some(r) = rows.next().await? {
            let key: String = r.get("key").unwrap_or_default();
            let key = key.strip_prefix("stance:").unwrap_or(&key).to_string();
            out.judgments.push((key, r.get("value").unwrap_or(0.5), r.get("why").unwrap_or_default()));
        }
        let mut rows = self
            .g
            .execute(self.q(
                "MATCH (p:Concept {run: $run, actor: $actor}) WHERE p.key STARTS WITH 'place:' AND p.x IS NOT NULL AND p.y IS NOT NULL AND NOT p:Merged
                 RETURN coalesce(p.name, substring(p.key, 6)) AS name, toFloat(p.x) AS x, toFloat(p.y) AS y
                 ORDER BY coalesce(p.updated_t, 0) DESC LIMIT 24",
                actor,
            ))
            .await?;
        while let Some(r) = rows.next().await? {
            out.places.push((r.get("name").unwrap_or_default(), r.get("x").unwrap_or(0.0), r.get("y").unwrap_or(0.0)));
        }
        Ok(out)
    }
}

/// Convenience arrays a reply may carry (`relations`, `judgments`, `places`) become ordinary
/// mind edits: FEELS edges, JUDGES edges to `stance:` concepts and `place:` concepts.
pub fn sugar_into(v: &Value, patch: &mut Patch, because: &[u64]) {
    for r in v["relations"].as_array().cloned().unwrap_or_default().into_iter().take(12) {
        let Some(id) = r["id"].as_u64() else { continue };
        let mut props = serde_json::Map::new();
        for k in ["trust", "affinity"] {
            props.insert(k.into(), json!(r[k].as_f64().unwrap_or(0.0).clamp(-100.0, 100.0)));
        }
        props.insert("label".into(), json!(r["label"].as_str().unwrap_or("acquaintance")));
        props.insert("note".into(), json!(r["note"].as_str().unwrap_or_default().chars().take(300).collect::<String>()));
        patch.edges.push(EdgeOp { from: "self".into(), rel: "FEELS".into(), to: format!("person:{id}"), confidence: 1.0, because: because.to_vec(), props });
    }
    for j in v["judgments"].as_array().cloned().unwrap_or_default().into_iter().take(12) {
        let Some(k) = j["key"].as_str().and_then(|k| key(k.trim_start_matches("stance:"))) else { continue };
        let mut props = serde_json::Map::new();
        props.insert("value".into(), json!(j["value"].as_f64().unwrap_or(0.5).clamp(0.0, 1.0)));
        props.insert("why".into(), json!(j["why"].as_str().unwrap_or_default().chars().take(300).collect::<String>()));
        let k = k.replace(':', "_");
        patch.nodes.push(NodeOp { key: format!("stance:{k}"), labels: vec!["Stance".into()], name: Some(k.clone()), props: Default::default() });
        patch.edges.push(EdgeOp { from: "self".into(), rel: "JUDGES".into(), to: format!("stance:{k}"), confidence: 1.0, because: because.to_vec(), props });
    }
    for p in v["places"].as_array().cloned().unwrap_or_default().into_iter().take(8) {
        let (Some(name), Some(x), Some(y)) = (p["name"].as_str(), p["x"].as_f64(), p["y"].as_f64()) else { continue };
        let Some(k) = key(name) else { continue };
        let mut props = serde_json::Map::new();
        let (w, h) = crate::prompts::map_size();
        props.insert("x".into(), json!(x.clamp(0.0, w as f64)));
        props.insert("y".into(), json!(y.clamp(0.0, h as f64)));
        let k = k.trim_start_matches("place:").to_string();
        patch.nodes.push(NodeOp { key: format!("place:{k}"), labels: vec!["Place".into()], name: Some(name.chars().take(48).collect()), props });
    }
}

/// Render a fact with explicit keys (for reorganization, where the mind edits by key).
pub fn render_keys(f: &Fact, time: &dyn Fn(u64) -> String) -> String {
    let extra = if f.extra.is_empty() { String::new() } else { format!(" {{{}}}", f.extra.join(", ")) };
    format!("{} —{}{}→ {} ({:.0}%, {})", f.a, f.rel, extra, f.b, f.confidence * 100.0, time(f.t))
}

/// Render a fact as one prompt line from the mind's own point of view.
pub fn render(f: &Fact, time: &dyn Fn(u64) -> String) -> String {
    let who = |key: &str, name: &str, labels: &[String]| {
        if key == "self" {
            return "you".to_string();
        }
        let mut s = if name.is_empty() || name == key { key.to_string() } else { format!("{name} ({key})") };
        let extra: Vec<&String> = labels.iter().filter(|l| !["Self", "Memory"].contains(&l.as_str())).collect();
        if !extra.is_empty() {
            s.push_str(&format!(" [{}]", extra.iter().map(|l| l.as_str()).collect::<Vec<_>>().join(", ")));
        }
        s
    };
    let extra = if f.extra.is_empty() { String::new() } else { format!(" {{{}}}", f.extra.join(", ")) };
    format!(
        "{} —{}{}→ {} ({:.0}%, {})",
        who(&f.a, &f.a_name, &f.a_labels),
        f.rel,
        extra,
        who(&f.b, &f.b_name, &f.b_labels),
        f.confidence * 100.0,
        time(f.t)
    )
}

// ---- sanitizing model-written patches ---------------------------------------------

fn ident(s: &str, upper: bool, max: usize) -> Option<String> {
    let mut out = String::new();
    let mut prev_us = false;
    for ch in s.trim().chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(if upper { ch.to_ascii_uppercase() } else { ch });
            prev_us = false;
        } else if !prev_us && !out.is_empty() {
            out.push('_');
            prev_us = true;
        }
    }
    let out = out.trim_matches('_').to_string();
    let out: String = out.chars().take(max).collect();
    if out.is_empty() || out.chars().next().map_or(true, |c| c.is_ascii_digit()) {
        None
    } else {
        Some(out)
    }
}

/// Normalize a concept key: lowercase, `kind:name` style, stable anchors.
pub fn key(s: &str) -> Option<String> {
    let s = s.trim().to_lowercase();
    if s.is_empty() || s.len() > 80 {
        return None;
    }
    if matches!(s.as_str(), "me" | "myself" | "i" | "you") {
        return Some("self".into());
    }
    let cleaned: String = s.chars().map(|c| if c.is_alphanumeric() || c == ':' || c == '-' || c == '.' { c } else { '_' }).collect();
    Some(cleaned.trim_matches('_').to_string()).filter(|k| !k.is_empty())
}

const RESERVED: &[&str] = &["run", "actor", "key", "t", "thought", "because", "open", "since", "valid_to", "retracted_by", "confidence", "created_t", "updated_t"];

fn props(v: &Value) -> serde_json::Map<String, Value> {
    let mut out = serde_json::Map::new();
    if let Some(o) = v.as_object() {
        for (k, v) in o.iter().take(8) {
            let Some(k) = ident(k, false, 32).map(|k| k.to_lowercase()) else { continue };
            if RESERVED.contains(&k.as_str()) {
                continue;
            }
            let v = match v {
                Value::String(s) => Value::String(s.chars().take(300).collect()),
                Value::Number(_) | Value::Bool(_) | Value::Null => v.clone(),
                other => Value::String(other.to_string().chars().take(300).collect()),
            };
            out.insert(k, v);
        }
    }
    out
}

/// Build a sanitized patch from a model reply; ids in `because` must be known experiences.
pub fn patch_from(v: &Value, known: &[u64], exp_time: &dyn Fn(u64) -> Option<(u64, f64, Vec<String>)>) -> (Patch, Vec<String>) {
    let mut patch = Patch::default();
    let mut notes = Vec::new();
    let anchored = |k: &str| k == "self" || k.strip_prefix("person:").map_or(false, |r| r.parse::<u32>().is_ok());
    for m in v["merge"].as_array().cloned().unwrap_or_default().into_iter().take(12) {
        let (Some(from), Some(into)) = (m["from"].as_str().and_then(key), m["into"].as_str().and_then(key)) else { continue };
        if from == into || anchored(&from) {
            notes.push(format!("merge {from} → {into} refused"));
            continue;
        }
        patch.merges.push((from, into));
    }
    for n in v["nodes"].as_array().cloned().unwrap_or_default().into_iter().take(24) {
        let Some(k) = n["key"].as_str().and_then(key) else {
            notes.push("node without a usable key".into());
            continue;
        };
        let labels: Vec<String> = n["labels"]
            .as_array()
            .map(|a| a.iter().filter_map(|l| l.as_str()).filter_map(|l| ident(l, false, 32)).map(|l| {
                let mut c = l.chars();
                c.next().map(|f| f.to_ascii_uppercase().to_string() + c.as_str()).unwrap_or_default()
            }).filter(|l| !["Concept", "Memory", "Self", "IdentityVersion"].contains(&l.as_str())).take(4).collect())
            .unwrap_or_default();
        patch.nodes.push(NodeOp { key: k, labels, name: n["name"].as_str().map(|s| s.chars().take(120).collect()), props: props(&n["props"]) });
    }
    for e in v["edges"].as_array().cloned().unwrap_or_default().into_iter().take(32) {
        let (Some(a), Some(b), Some(rel)) = (e["from"].as_str().and_then(key), e["to"].as_str().and_then(key), e["rel"].as_str().and_then(|r| ident(r, true, 40))) else {
            notes.push(format!("edge skipped: {e}"));
            continue;
        };
        if ["WAS", "INVOLVES"].contains(&rel.as_str()) {
            continue;
        }
        let because: Vec<u64> = e["because"].as_array().map(|a| a.iter().filter_map(|x| x.as_u64()).filter(|x| known.contains(x)).collect()).unwrap_or_default();
        patch.edges.push(EdgeOp { from: a, rel, to: b, confidence: e["confidence"].as_f64().unwrap_or(0.6).clamp(0.0, 1.0), because, props: props(&e["props"]) });
    }
    for r in v["retract"].as_array().cloned().unwrap_or_default().into_iter().take(16) {
        if let (Some(a), Some(b), Some(rel)) = (r["from"].as_str().and_then(key), r["to"].as_str().and_then(key), r["rel"].as_str().and_then(|x| ident(x, true, 40))) {
            patch.retract.push((a, rel, b));
        }
    }
    for m in v["remember"].as_array().cloned().unwrap_or_default().into_iter().take(12) {
        let Some(exp) = m["exp"].as_u64().filter(|x| known.contains(x)) else { continue };
        let Some((t, salience, involves)) = exp_time(exp) else { continue };
        let gist: String = m["gist"].as_str().unwrap_or_default().chars().take(300).collect();
        if gist.is_empty() {
            continue;
        }
        patch.remember.push(MemoryOp { exp, t, gist, salience, involves });
    }
    (patch, notes)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Against a live Neo4j (LIVING_NEO4J_PASSWORD set): `cargo test -p living-mind -- --ignored`.
    #[tokio::test]
    #[ignore]
    async fn minds_revise_merge_and_fade() {
        let pw = std::env::var("LIVING_NEO4J_PASSWORD").expect("password");
        let run = format!("test-{}", crate::llm::now_ms());
        let s = Store::connect("127.0.0.1:7689", "neo4j", &pw, &run).await.unwrap();
        s.ensure_self(1, "Fen").await.unwrap();
        let t0 = crate::llm::now_ms() - 3 * 3_600_000;
        let v = json!({
            "nodes": [{"key": "person:7", "labels": ["Person", "Stranger"], "name": "Kael"}],
            "edges": [{"from": "self", "rel": "WARY_OF", "to": "person:7", "confidence": 0.8, "because": [1]},
                      {"from": "self", "rel": "BELIEVES", "to": "idea:kael_seems_kind", "confidence": 0.6, "because": [1]},
                      {"from": "self", "rel": "SAW", "to": "kind:wolf", "confidence": 0.3, "because": [1]}]
        });
        let (p1, _) = patch_from(&v, &[1, 2], &|_| None);
        s.apply(1, &p1, "t1", t0).await.unwrap();
        let later = crate::llm::now_ms();
        let v = json!({
            "nodes": [{"key": "person:7", "labels": ["Person", "Friend"]}],
            "edges": [{"from": "self", "rel": "TRUSTS", "to": "person:7", "confidence": 0.9, "because": [2]},
                      {"from": "self", "rel": "BELIEVES", "to": "idea:kael_is_friendly", "confidence": 0.8, "because": [2]}],
            "retract": [{"from": "self", "rel": "WARY_OF", "to": "person:7"}],
            "merge": [{"from": "idea:kael_seems_kind", "into": "idea:kael_is_friendly"}]
        });
        let (p2, _) = patch_from(&v, &[1, 2], &|_| None);
        s.apply(1, &p2, "t2", later).await.unwrap();
        let faded = s.fade(1, 0.2, later).await.unwrap();
        let facts = s.around(1, &[], 50).await.unwrap();
        let rels: Vec<String> = facts.iter().map(|f| format!("{} {} {}", f.a, f.rel, f.b)).collect();
        assert!(rels.contains(&"self TRUSTS person:7".to_string()), "{rels:?}");
        assert!(!rels.iter().any(|r| r.contains("WARY_OF")), "retracted: {rels:?}");
        assert!(!rels.iter().any(|r| r.contains("SAW")), "old weak belief faded: {rels:?}");
        assert!(faded >= 1);
        let kael = facts.iter().find(|f| f.b == "person:7").unwrap();
        assert!(kael.b_labels.contains(&"Friend".to_string()) && !kael.b_labels.contains(&"Stranger".to_string()), "{:?}", kael.b_labels);
        assert_eq!(rels.iter().filter(|r| r.contains("idea:kael")).count(), 1, "merged into one idea: {rels:?}");
        // Feelings, stances and places are projections of the graph.
        let mut p3 = Patch::default();
        sugar_into(&json!({"relations": [{"id": 7, "trust": 60, "affinity": 40, "label": "friend"}],
                           "judgments": [{"key": "wolves_near_camp", "value": 0.9, "why": "saw them"}],
                           "places": [{"name": "Berry Grove", "x": 20, "y": 70}]}), &mut p3, &[2]);
        s.apply(1, &p3, "t3", later).await.unwrap();
        let proj = s.projection(1).await.unwrap();
        assert_eq!(proj.feelings.len(), 1);
        assert_eq!(proj.feelings[0].0, 7);
        assert!((proj.feelings[0].1 - 60.0).abs() < 0.01);
        assert_eq!(proj.judgments[0].0, "wolves_near_camp");
        assert!(proj.judgments[0].1 > 0.85);
        assert_eq!(proj.places, vec![("Berry Grove".to_string(), 20.0, 70.0)]);
        // A retracted feeling disappears from the projection.
        let (p4, _) = patch_from(&json!({"retract": [{"from": "self", "rel": "FEELS", "to": "person:7"}]}), &[], &|_| None);
        s.apply(1, &p4, "t4", later).await.unwrap();
        assert!(s.projection(1).await.unwrap().feelings.is_empty());
        // History is kept: the retracted and merged edges still exist, closed.
        let (nodes, edges) = s.size(1).await.unwrap();
        assert!(nodes >= 3 && edges >= 2);
        s.g.run(query("MATCH (c:Concept {run: $run}) DETACH DELETE c").param("run", run)).await.unwrap();
    }

    #[test]
    fn sanitizes_open_patches() {
        let v = json!({
            "nodes": [{"key": "Person:4", "labels": ["person", "thief!", "Concept"], "name": "Bram", "props": {"note": "took berries", "run": "x"}}],
            "edges": [{"from": "person:4", "rel": "stole from", "to": "me", "confidence": 1.4, "because": [7, 99], "props": {"item": "berries"}},
                      {"from": "", "rel": "x", "to": "self"}],
            "retract": [{"from": "self", "rel": "TRUSTS", "to": "person:4"}],
            "remember": [{"exp": 7, "gist": "Bram raided our storage"}, {"exp": 99, "gist": "invented"}]
        });
        let (p, notes) = patch_from(&v, &[7], &|id| (id == 7).then(|| (1000, 0.8, vec!["person:4".to_string()])));
        assert_eq!(p.nodes[0].key, "person:4");
        assert_eq!(p.nodes[0].labels, vec!["Person", "Thief"]);
        assert!(!p.nodes[0].props.contains_key("run"));
        assert_eq!(p.edges.len(), 1);
        assert_eq!(p.edges[0].rel, "STOLE_FROM");
        assert_eq!(p.edges[0].to, "self");
        assert_eq!(p.edges[0].confidence, 1.0);
        assert_eq!(p.edges[0].because, vec![7]);
        assert_eq!(p.retract, vec![("self".into(), "TRUSTS".into(), "person:4".into())]);
        assert_eq!(p.remember.len(), 1);
        assert_eq!(notes.len(), 1);
    }
}
