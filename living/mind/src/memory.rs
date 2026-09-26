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
/// A stance whose relaxed lean `|value - 0.5| · exp(-age / TAU_MS)` falls below this is no
/// longer held (e.g. a 0.95 stance, unreinforced, for about 80 minutes).
const STANCE_LEAN: f64 = 0.05;
/// Memories fade more slowly than beliefs, from when they were formed or last recalled:
/// `salience · exp(-age / MEMORY_TAU_MS)`; below `MEMORY_FLOOR` they are forgotten
/// (a salience-0.9 memory never recalled lasts about 5 hours, a 0.4 one about 3).
const MEMORY_TAU_MS: f64 = 3.0 * 3_600_000.0;
const MEMORY_FLOOR: f64 = 0.15;
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

    /// Close beliefs whose decayed confidence fell below `floor`, stances that have relaxed to
    /// indifference, and forget memories that were neither salient nor recalled; returns how
    /// many beliefs and stances faded (forgotten memories are logged).
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
        let beliefs = match rows.next().await? {
            Some(r) => r.get::<i64>("n").unwrap_or(0),
            None => 0,
        };
        // A stance relaxes toward 0.5 unless reinforced (the projection shows the relaxed
        // value); once it no longer leans either way it is no longer held.
        let mut rows = self
            .g
            .execute(
                self.q(
                    "MATCH (:Concept {run: $run, actor: $actor, key: 'self'})-[r:JUDGES {open: true}]->(:Concept)
                     WHERE abs(toFloat(coalesce(r.value, 0.5)) - 0.5) * exp(-toFloat($t - coalesce(r.t, $t)) / $tau) < $lean
                     SET r.open = false, r.valid_to = $t, r.retracted_by = 'faded'
                     RETURN count(r) AS n",
                    actor,
                )
                .param("t", t as i64)
                .param("tau", TAU_MS)
                .param("lean", STANCE_LEAN),
            )
            .await?;
        let stances = match rows.next().await? {
            Some(r) => r.get::<i64>("n").unwrap_or(0),
            None => 0,
        };
        // Memories fade with time unless salient or brought back by recall (rehearsal); a
        // forgotten memory is kept as history (`:Forgotten`) but no longer comes to mind.
        let mut rows = self
            .g
            .execute(
                self.q(
                    "MATCH (m:Concept {run: $run, actor: $actor}) WHERE m:Memory AND NOT m:Forgotten
                       AND coalesce(m.salience, 0.5) * exp(-toFloat($t - coalesce(m.recalled_t, m.t, $t)) / $tau) < $floor
                     SET m:Forgotten, m.forgotten_t = $t
                     RETURN count(m) AS n",
                    actor,
                )
                .param("t", t as i64)
                .param("tau", MEMORY_TAU_MS)
                .param("floor", MEMORY_FLOOR),
            )
            .await?;
        let forgotten = match rows.next().await? {
            Some(r) => r.get::<i64>("n").unwrap_or(0),
            None => 0,
        };
        if forgotten > 0 || stances > 0 {
            log::info!("mind {actor}: {beliefs} beliefs and {stances} stances faded, {forgotten} memories forgotten");
        }
        Ok(beliefs + stances)
    }

    /// Size of the living part of a mind: (concepts with at least one open link, open edges).
    pub async fn size(&self, actor: u32) -> Result<(i64, i64)> {
        let mut rows = self
            .g
            .execute(self.q(
                "MATCH (c:Concept {run: $run, actor: $actor}) WHERE NOT c:Merged AND NOT c:IdentityVersion AND NOT c:Forgotten
                 OPTIONAL MATCH (c)-[r {open: true}]->()
                 WITH c, count(r) AS out
                 WHERE out > 0 OR EXISTS { (c)<-[{open: true}]-() } OR c.key = 'self'
                 RETURN count(c) AS nodes, sum(out) AS edges",
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
            .execute(self.q("MATCH (m:Concept {run: $run, actor: $actor}) WHERE m:Memory AND NOT m:Forgotten RETURN m.exp AS exp, m.t AS t, m.gist AS gist ORDER BY m.t DESC LIMIT $limit", actor).param("limit", limit as i64))
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

// ---- situational recall ---------------------------------------------------------------

/// What the current situation offers the mind as cues: anchor keys (people and creatures
/// perceived, places nearby, people named) and words (the reason for thinking, what was said,
/// what happened, the plan), each weighted by how present it is.
#[derive(Clone, Debug, Default)]
pub struct Cues {
    pub keys: Vec<(String, f64)>,
    pub words: Vec<(String, f64)>,
}

impl Cues {
    pub fn key(&mut self, k: impl Into<String>, w: f64) {
        let k = k.into();
        match self.keys.iter_mut().find(|x| x.0 == k) {
            Some(x) => x.1 = x.1.max(w),
            None => self.keys.push((k, w)),
        }
    }

    pub fn text(&mut self, text: &str, w: f64) {
        for s in cue_words(text) {
            match self.words.iter_mut().find(|x| x.0 == s) {
                Some(x) => x.1 = x.1.max(w),
                None => self.words.push((s, w)),
            }
        }
    }

    /// Keep the strongest cues (a small, fixed budget per recall).
    pub fn bounded(mut self) -> Self {
        self.keys.sort_by(|a, b| b.1.total_cmp(&a.1));
        self.keys.truncate(24);
        self.words.sort_by(|a, b| b.1.total_cmp(&a.1));
        self.words.truncate(20);
        self
    }
}

const STOP: &[&str] = &[
    "that", "this", "with", "from", "have", "your", "will", "what", "they", "them", "their", "there", "been", "into", "about", "were", "just", "only", "more",
    "some", "than", "then", "also", "like", "over", "after", "before", "where", "while", "which", "would", "could", "should", "very", "much", "still", "here",
    "ever", "each", "other", "need", "make", "made", "back", "want", "know", "think", "maybe", "when", "said", "says", "tell", "come", "going", "does", "doing",
    "done", "take", "well", "even", "keep", "let's", "lets", "yours", "mine", "ours", "these", "those", "because", "again", "right", "now", "tiles", "tile",
    "someone", "something", "thing", "things", "feel", "feels", "felt", "look", "looks", "away", "around", "near", "nearest", "north", "south", "east", "west",
    "northeast", "northwest", "southeast", "southwest", "first", "time", "respond", "json", "object", "you're", "we're", "i'll", "we'll",
    // The engine's own vocabulary in reasons and feedback says nothing about the world.
    "note", "parts", "previous", "graph", "invalid", "dropped", "branch", "applies", "apply", "skill", "goto", "target", "composite", "current",
    "plan", "nothing", "works", "action", "actions", "failing", "fails", "failed", "sight", "reply", "node", "nodes", "most", "least", "wait",
];

/// Content words of a text as match stems: lowercase, at least 4 letters, no stopwords,
/// simple plurals folded (wolves → wolf and wolv, berries → berr, stores → store).
pub fn cue_words(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for w in text.to_lowercase().split(|c: char| !c.is_alphabetic()) {
        if w.chars().count() < 4 || STOP.contains(&w) {
            continue;
        }
        let s = if let Some(b) = w.strip_suffix("ves").filter(|b| b.len() >= 3) {
            format!("{b}f")
        } else if let Some(b) = w.strip_suffix("ies").filter(|b| b.len() >= 3) {
            b.to_string()
        } else if let Some(b) = w.strip_suffix("ing").filter(|b| b.len() >= 4) {
            b.to_string()
        } else if w.ends_with('s') && !w.ends_with("ss") {
            w[..w.len() - 1].to_string()
        } else {
            w.to_string()
        };
        if s.chars().count() >= 4 && !STOP.contains(&s.as_str()) && !out.contains(&s) {
            // wolf also matches "wolves", leaf "leaves".
            if let Some(b) = s.strip_suffix('f') {
                let v = format!("{b}v");
                if !out.contains(&v) {
                    out.push(v);
                }
            }
            out.push(s);
        }
    }
    out
}

/// What a situation brought back: the most activated beliefs (excluding feelings about
/// people and stances, which prompts list in their own sections), the stances and people it
/// touched, and memories.
#[derive(Clone, Debug, Default)]
pub struct Recalled {
    pub facts: Vec<Fact>,
    pub stances: Vec<(String, f64)>,
    pub people: Vec<(u32, f64)>,
    pub memories: Vec<(u64, u64, String)>,
    /// Cued memories to rehearse (see [`Store::rehearse`]).
    pub rehearse: Vec<u64>,
    pub seeds: usize,
    pub considered: usize,
    pub ms: u64,
}

struct Hit {
    fact: Fact,
    score: f64,
    /// The cue this belief was reached from (for variety across cues).
    via: String,
}

/// Recency of reinforcement as a mild bonus: fresh beliefs are more present.
fn recency(now: u64, t: u64) -> f64 {
    0.6 + 0.4 * (-(now.saturating_sub(t) as f64) / (30.0 * 60_000.0)).exp()
}

fn memory_strength(now: u64, t: u64, recalled: u64, salience: f64) -> f64 {
    salience * (-(now.saturating_sub(t.max(recalled)) as f64) / MEMORY_TAU_MS).exp()
}

/// Minimum activation for a belief to come to mind.
const RECALL_FLOOR: f64 = 0.12;
/// Words matching more of a mind's concepts than this say nothing specific.
const WORD_SPREAD: usize = 8;

impl Store {
    /// Recall by association: cues from the situation activate the concepts they name (anchor
    /// keys directly, words through concept keys, names and memory gists), activation spreads
    /// one step along open edges (weighted by effective confidence and recency) and a second,
    /// damped step from the ideas, plans and places reached. Only what clears a floor comes
    /// to mind, best first, within `budget`; memories within `mem_budget` (plus the two most
    /// recent, as working memory). Read-only: the caller rehearses what came back. All queries
    /// start from indexed `(run, actor[, key])` lookups and touch only this mind's concepts.
    pub async fn recall(&self, actor: u32, cues: &Cues, budget: usize, mem_budget: usize) -> Result<Recalled> {
        let started = std::time::Instant::now();
        let now = crate::llm::now_ms();
        let mut seeds: Vec<(String, f64)> = Vec::new();
        let mut mem_cands: Vec<(u64, u64, String, f64)> = Vec::new();
        // Anchor keys that exist in this mind.
        if !cues.keys.is_empty() {
            let rows: Vec<Value> = cues.keys.iter().map(|(k, w)| json!({"key": k, "w": w})).collect();
            let mut r = self
                .g
                .execute(
                    self.q(
                        "UNWIND $rows AS k
                         MATCH (c:Concept {run: $run, actor: $actor, key: k.key}) WHERE NOT c:Merged
                         RETURN c.key AS key, k.w AS w",
                        actor,
                    )
                    .param("rows", p(Value::Array(rows))),
                )
                .await?;
            while let Some(row) = r.next().await? {
                seeds.push((row.get("key").unwrap_or_default(), row.get("w").unwrap_or(0.5)));
            }
        }
        // Words: concepts whose key, name or gist contains them; a word that matches many
        // concepts is uninformative and is dropped.
        if !cues.words.is_empty() {
            let words: Vec<String> = cues.words.iter().map(|(w, _)| w.clone()).collect();
            let mut r = self
                .g
                .execute(
                    self.q(
                        "MATCH (c:Concept {run: $run, actor: $actor})
                         WHERE NOT c:Merged AND NOT c:IdentityVersion AND NOT c:Forgotten AND c.key <> 'self'
                         WITH c, toLower(c.key + ' ' + coalesce(c.name, '') + ' ' + coalesce(c.gist, '')) AS text
                         WITH c, [w IN $words WHERE text CONTAINS w] AS hit
                         WHERE size(hit) > 0
                         RETURN c.key AS key, hit, c:Memory AS memory, c.exp AS exp, c.t AS t, c.gist AS gist,
                                toFloat(coalesce(c.salience, 0.5)) AS sal, coalesce(c.recalled_t, 0) AS rt",
                        actor,
                    )
                    .param("words", words),
                )
                .await?;
            let mut found: Vec<(String, Vec<String>, bool, u64, u64, String, f64, u64)> = Vec::new();
            while let Some(row) = r.next().await? {
                found.push((
                    row.get("key").unwrap_or_default(),
                    row.get("hit").unwrap_or_default(),
                    row.get("memory").unwrap_or(false),
                    row.get::<i64>("exp").unwrap_or(0) as u64,
                    row.get::<i64>("t").unwrap_or(0) as u64,
                    row.get("gist").unwrap_or_default(),
                    row.get("sal").unwrap_or(0.5),
                    row.get::<i64>("rt").unwrap_or(0) as u64,
                ));
            }
            let freq = |w: &str| found.iter().filter(|f| f.1.iter().any(|h| h == w)).count();
            let mut word_seeds: Vec<(String, f64)> = Vec::new();
            for (key, hit, memory, exp, t, gist, sal, rt) in &found {
                let ws: Vec<f64> = hit
                    .iter()
                    .filter_map(|h| {
                        let n = freq(h);
                        (n <= WORD_SPREAD).then(|| cues.words.iter().find(|(w, _)| w == h).map_or(0.5, |x| x.1) / (1.0 + (n as f64).ln()))
                    })
                    .collect();
                let Some(best) = ws.iter().cloned().reduce(f64::max) else { continue };
                // Several matching words are stronger evidence than one.
                let w = (best * (1.0 + 0.25 * (ws.len() as f64 - 1.0))).min(1.5) * 0.8;
                if *memory {
                    mem_cands.push((*exp, *t, gist.clone(), w * memory_strength(now, *t, *rt, *sal)));
                } else if !seeds.iter().any(|s| &s.0 == key) {
                    word_seeds.push((key.clone(), w));
                }
            }
            word_seeds.sort_by(|a, b| b.1.total_cmp(&a.1));
            seeds.extend(word_seeds.into_iter().take(10));
        }
        let mut out = Recalled { seeds: seeds.len(), ..Default::default() };
        let mut hits: Vec<Hit> = Vec::new();
        let mut stances: Vec<(String, f64)> = Vec::new();
        let mut people: Vec<(u32, f64)> = Vec::new();
        let mut next: Vec<(String, f64)> = Vec::new();
        for hop in 0..2 {
            let from = if hop == 0 { seeds.clone() } else { std::mem::take(&mut next) };
            if from.is_empty() {
                break;
            }
            let rows: Vec<Value> = from.iter().map(|(k, w)| json!({"key": k, "w": w})).collect();
            let mut r = self
                .g
                .execute(
                    self.q(
                        "UNWIND $rows AS s
                         MATCH (c:Concept {run: $run, actor: $actor, key: s.key})-[r]-(n:Concept)
                         WHERE (r.open = true OR type(r) = 'INVOLVES') AND NOT n:Merged
                         WITH s, r, n, startNode(r) AS a, endNode(r) AS b
                         RETURN s.key AS seed, s.w AS w, n.key AS other, n:Memory AS memory, n:Forgotten AS forgotten,
                                a.key AS a, coalesce(a.name, a.key) AS an, labels(a) AS al, type(r) AS rel,
                                b.key AS b, coalesce(b.name, b.key) AS bn, labels(b) AS bl,
                                toFloat(coalesce(r.confidence, 0.5)) AS c0, coalesce(r.t, 0) AS t,
                                [k IN keys(r) WHERE NOT k IN ['open', 't', 'since', 'because', 'thought', 'confidence', 'valid_to', 'retracted_by'] | k + ': ' + toString(r[k])] AS extra,
                                n.exp AS exp, n.t AS mt, n.gist AS gist, toFloat(coalesce(n.salience, 0.5)) AS sal, coalesce(n.recalled_t, 0) AS rt
                         LIMIT 800",
                        actor,
                    )
                    .param("rows", p(Value::Array(rows))),
                )
                .await?;
            let damp = if hop == 0 { 1.0 } else { 0.5 };
            while let Some(row) = r.next().await? {
                out.considered += 1;
                let w: f64 = row.get::<f64>("w").unwrap_or(0.5) * damp;
                let rel: String = row.get("rel").unwrap_or_default();
                let other: String = row.get("other").unwrap_or_default();
                if row.get::<bool>("memory").unwrap_or(false) {
                    if !row.get::<bool>("forgotten").unwrap_or(false) {
                        let (exp, mt) = (row.get::<i64>("exp").unwrap_or(0) as u64, row.get::<i64>("mt").unwrap_or(0) as u64);
                        let s = w * memory_strength(now, mt, row.get::<i64>("rt").unwrap_or(0) as u64, row.get("sal").unwrap_or(0.5));
                        mem_cands.push((exp, mt, row.get("gist").unwrap_or_default(), s));
                    }
                    continue;
                }
                if rel == "INVOLVES" {
                    continue;
                }
                let t = row.get::<i64>("t").unwrap_or(0) as u64;
                let c0: f64 = row.get("c0").unwrap_or(0.5);
                let eff = if DURABLE.contains(&rel.as_str()) { c0 } else { c0 * (-(now.saturating_sub(t) as f64) / TAU_MS).exp() };
                if eff < 0.15 {
                    continue;
                }
                let mut score = w * eff * recency(now, t);
                if let Some((_, w2)) = seeds.iter().find(|s| s.0 == other) {
                    score += 0.5 * w2 * eff;
                }
                let (a, b): (String, String) = (row.get("a").unwrap_or_default(), row.get("b").unwrap_or_default());
                // Feelings and stances have their own prompt sections: note what was touched.
                if a == "self" && rel == "FEELS" {
                    if let Some(id) = b.strip_prefix("person:").and_then(|x| x.parse::<u32>().ok()) {
                        people.push((id, score));
                    }
                    continue;
                }
                if a == "self" && rel == "JUDGES" {
                    stances.push((b.strip_prefix("stance:").unwrap_or(&b).to_string(), score));
                    continue;
                }
                // Ideas, plans and places reached lead one step further.
                if hop == 0 && other != "self" && !other.starts_with("person:") && !other.starts_with("kind:") && !other.starts_with("stance:") && !seeds.iter().any(|s| s.0 == other) {
                    match next.iter_mut().find(|x| x.0 == other) {
                        Some(x) => x.1 = x.1.max(w * eff),
                        None => next.push((other.clone(), w * eff)),
                    }
                }
                let seed: String = row.get("seed").unwrap_or_default();
                if let Some(h) = hits.iter_mut().find(|h| h.fact.a == a && h.fact.rel == rel && h.fact.b == b) {
                    if score > h.score {
                        h.score = score;
                        h.via = seed;
                    }
                    continue;
                }
                let strip = |v: Vec<String>| v.into_iter().filter(|l| !FIXED_LABELS.contains(&l.as_str()) || l == "Memory").collect::<Vec<_>>();
                hits.push(Hit {
                    fact: Fact {
                        a,
                        a_name: row.get("an").unwrap_or_default(),
                        a_labels: strip(row.get("al").unwrap_or_default()),
                        rel,
                        b,
                        b_name: row.get("bn").unwrap_or_default(),
                        b_labels: strip(row.get("bl").unwrap_or_default()),
                        confidence: eff,
                        t,
                        extra: row.get("extra").unwrap_or_default(),
                    },
                    score,
                    via: seed,
                });
            }
            next.sort_by(|a, b| b.1.total_cmp(&a.1));
            next.retain(|x| x.1 >= 0.3);
            next.truncate(5);
        }
        hits.retain(|h| h.score >= RECALL_FLOOR);
        hits.sort_by(|a, b| b.score.total_cmp(&a.score));
        // Several cues share the budget: one busy concept (a person everyone talks about)
        // does not crowd out the rest.
        let per_cue = (budget / 4).max(3);
        let mut used: Vec<(String, usize)> = Vec::new();
        let mut chosen = Vec::new();
        let mut spill = Vec::new();
        for h in hits {
            let n = match used.iter_mut().find(|u| u.0 == h.via) {
                Some(u) => {
                    u.1 += 1;
                    u.1
                }
                None => {
                    used.push((h.via.clone(), 1));
                    1
                }
            };
            if n <= per_cue { chosen.push(h) } else { spill.push(h) }
        }
        chosen.extend(spill);
        chosen.truncate(budget);
        out.facts = chosen.into_iter().map(|h| h.fact).collect();
        let merge = |v: Vec<(String, f64)>| {
            let mut m: Vec<(String, f64)> = Vec::new();
            for (k, s) in v {
                match m.iter_mut().find(|x| x.0 == k) {
                    Some(x) => x.1 = x.1.max(s),
                    None => m.push((k, s)),
                }
            }
            m.sort_by(|a, b| b.1.total_cmp(&a.1));
            m
        };
        out.stances = merge(stances).into_iter().filter(|s| s.1 >= RECALL_FLOOR).collect();
        out.people = merge(people.into_iter().map(|(id, s)| (id.to_string(), s)).collect()).into_iter().filter_map(|(k, s)| k.parse().ok().map(|id| (id, s))).collect();
        // Memories: the cued ones, strongest first, plus the two most recent as working memory.
        mem_cands.sort_by(|a, b| b.3.total_cmp(&a.3));
        let mut mems: Vec<(u64, u64, String)> = Vec::new();
        for (exp, t, gist, s) in mem_cands {
            if mems.len() >= mem_budget {
                break;
            }
            if s >= RECALL_FLOOR * 0.5 && !mems.iter().any(|m| m.0 == exp) && !gist.is_empty() {
                mems.push((exp, t, gist));
            }
        }
        out.rehearse = mems.iter().map(|m| m.0).collect();
        for m in self.memories(actor, 2).await? {
            if !mems.iter().any(|x| x.0 == m.0) {
                mems.push(m);
            }
        }
        mems.sort_by_key(|m| m.1);
        out.memories = mems;
        out.ms = started.elapsed().as_millis() as u64;
        Ok(out)
    }
}

impl Store {
    /// Recalling a memory rehearses it: it fades from this moment again.
    pub async fn rehearse(&self, actor: u32, exps: &[u64]) -> Result<()> {
        if exps.is_empty() {
            return Ok(());
        }
        let exps: Vec<i64> = exps.iter().map(|e| *e as i64).collect();
        self.g
            .run(
                self.q("UNWIND $exps AS e MATCH (m:Concept {run: $run, actor: $actor, key: 'exp:' + toString(e)}) SET m.recalled_t = $now", actor)
                    .param("exps", exps)
                    .param("now", crate::llm::now_ms() as i64),
            )
            .await?;
        Ok(())
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

    /// Situational recall and forgetting against a live Neo4j (a throwaway run, deleted after).
    #[tokio::test]
    #[ignore]
    async fn recall_by_cues_and_forgetting() {
        let pw = std::env::var("LIVING_NEO4J_PASSWORD").expect("password");
        let run = format!("test-recall-{}", crate::llm::now_ms());
        let s = Store::connect("127.0.0.1:7689", "neo4j", &pw, &run).await.unwrap();
        s.ensure_self(1, "Fen").await.unwrap();
        let now = crate::llm::now_ms();
        let old = now - 3 * 3_600_000;
        let v = json!({
            "nodes": [{"key": "person:7", "labels": ["Person"], "name": "Kael"}, {"key": "person:8", "labels": ["Person"], "name": "Oda"},
                      {"key": "idea:wolves_hunt_at_the_ford", "labels": ["Danger"]}],
            "edges": [{"from": "person:7", "rel": "PROMISED_TO_MEET", "to": "place:ford", "confidence": 0.9, "because": [1]},
                      {"from": "person:8", "rel": "CLAIMED", "to": "idea:wolves_hunt_at_the_ford", "confidence": 0.7, "because": [1]},
                      {"from": "idea:wolves_hunt_at_the_ford", "rel": "NEAR", "to": "place:ford", "confidence": 0.7, "because": [1]},
                      {"from": "self", "rel": "LIKES", "to": "idea:sunny_days", "confidence": 0.9, "because": [1]}],
            "remember": [{"exp": 1, "gist": "Kael swore he would wait for me at the ford."}, {"exp": 2, "gist": "A dull morning of gathering reeds."}]
        });
        let (p, _) = patch_from(&v, &[1, 2], &|id| Some((if id == 1 { now } else { old }, if id == 1 { 0.9 } else { 0.3 }, vec!["person:7".to_string()])));
        s.apply(1, &p, "t1", now).await.unwrap();
        let mut j = Patch::default();
        sugar_into(&json!({"judgments": [{"key": "wolves_are_near", "value": 0.95, "why": "howls"}, {"key": "old_worry", "value": 0.7, "why": "long ago"}]}), &mut j, &[]);
        s.apply(1, &j, "t2", now).await.unwrap();
        // The old worry was last reinforced long ago.
        s.g.run(query("MATCH (:Concept {run: $run, key: 'self'})-[r:JUDGES]->(:Concept {key: 'stance:old_worry'}) SET r.t = $old").param("run", run.clone()).param("old", old as i64)).await.unwrap();
        // Seeing Kael brings back his promise and the kept memory; wolves are not on the mind.
        let mut cues = Cues::default();
        cues.key("person:7", 1.0);
        let r = s.recall(1, &cues.clone().bounded(), 8, 3).await.unwrap();
        let rels: Vec<String> = r.facts.iter().map(|f| format!("{} {} {}", f.a, f.rel, f.b)).collect();
        assert!(rels.contains(&"person:7 PROMISED_TO_MEET place:ford".to_string()), "{rels:?}");
        assert!(!rels.iter().any(|x| x.contains("sunny")), "uncued: {rels:?}");
        assert!(r.memories.iter().any(|m| m.2.contains("Kael swore")), "{:?}", r.memories);
        // Hearing about wolves brings the claim, the idea's place and the stance.
        let mut cues = Cues::default();
        cues.text("Did you hear the wolves last night?", 1.0);
        let r = s.recall(1, &cues.bounded(), 8, 3).await.unwrap();
        let rels: Vec<String> = r.facts.iter().map(|f| format!("{} {} {}", f.a, f.rel, f.b)).collect();
        assert!(rels.iter().any(|x| x == "person:8 CLAIMED idea:wolves_hunt_at_the_ford"), "{rels:?}");
        assert!(r.stances.iter().any(|(k, _)| k == "wolves_are_near"), "{:?}", r.stances);
        assert!(r.ms < 500, "recall took {} ms", r.ms);
        // Sleep: the old stance has relaxed to indifference and the dull old memory is forgotten.
        s.fade(1, 0.2, now).await.unwrap();
        let proj = s.projection(1).await.unwrap();
        assert!(proj.judgments.iter().any(|j| j.0 == "wolves_are_near") && !proj.judgments.iter().any(|j| j.0 == "old_worry"), "{:?}", proj.judgments);
        let mems = s.memories(1, 10).await.unwrap();
        assert!(mems.iter().any(|m| m.0 == 1) && !mems.iter().any(|m| m.0 == 2), "{mems:?}");
        s.g.run(query("MATCH (c:Concept {run: $run}) DETACH DELETE c").param("run", run)).await.unwrap();
    }

    /// Replays recall on an existing run, read-only (for audits):
    /// `LIVING_RECALL_CASES=cases.json LIVING_NEO4J_PASSWORD=… cargo test -p living-mind recall_replay -- --ignored --nocapture`
    /// where each case is `{"run", "actor", "keys": [[key, w]], "texts": [[text, w]], "budget"}`.
    #[tokio::test]
    #[ignore]
    async fn recall_replay() {
        let pw = std::env::var("LIVING_NEO4J_PASSWORD").expect("password");
        let cases: Vec<Value> = serde_json::from_str(&std::fs::read_to_string(std::env::var("LIVING_RECALL_CASES").expect("cases")).unwrap()).unwrap();
        let mut stores: std::collections::HashMap<String, Store> = Default::default();
        for case in cases {
            let run = case["run"].as_str().unwrap().to_string();
            if !stores.contains_key(&run) {
                stores.insert(run.clone(), Store::connect("127.0.0.1:7689", "neo4j", &pw, &run).await.unwrap());
            }
            let s = &stores[&run];
            let mut cues = Cues::default();
            for k in case["keys"].as_array().unwrap() {
                cues.key(k[0].as_str().unwrap(), k[1].as_f64().unwrap());
            }
            for t in case["texts"].as_array().unwrap() {
                cues.text(t[0].as_str().unwrap(), t[1].as_f64().unwrap());
            }
            let cues = cues.bounded();
            let budget = case["budget"].as_u64().unwrap_or(24) as usize;
            let actor = case["actor"].as_u64().unwrap() as u32;
            let r = s.recall(actor, &cues, budget, 6).await.unwrap();
            let t = |t: u64| format!("{t}");
            println!(
                "{}",
                json!({"id": case["id"], "actor": actor, "ms": r.ms, "seeds": r.seeds, "considered": r.considered,
                       "words": cues.words.iter().map(|w| &w.0).collect::<Vec<_>>(),
                       "facts": r.facts.iter().map(|f| render_keys(f, &t)).collect::<Vec<_>>(),
                       "stances": r.stances, "people": r.people,
                       "memories": r.memories.iter().map(|m| &m.2).collect::<Vec<_>>()})
            );
        }
    }

    #[test]
    fn cue_words_fold_plurals_and_skip_filler() {
        assert_eq!(cue_words("Wolves near the ford! Berries, stores and the fishing spot."), vec!["wolv", "wolf", "ford", "berr", "store", "fish", "spot"]);
        assert!(cue_words("that this with from").is_empty());
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
