"""Neo4j projection and actor-scoped queries for the concept-graph experiment."""

from __future__ import annotations

import json
from typing import Any

from .model import BaseGraph, Claim, Concept, Evidence, Perspective, scoped


CONSTRAINTS = (
    "CREATE CONSTRAINT perspective_key IF NOT EXISTS FOR (n:Perspective) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT concept_key IF NOT EXISTS FOR (n:Concept) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT claim_key IF NOT EXISTS FOR (n:Claim) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT evidence_key IF NOT EXISTS FOR (n:Evidence) REQUIRE n.key IS UNIQUE",
)


class GraphStore:
    def __init__(self, driver: Any, database: str = "neo4j") -> None:
        self.driver = driver
        self.database = database

    def initialize(self) -> None:
        for statement in CONSTRAINTS:
            self.driver.execute_query(statement, database_=self.database)

    def load(self, perspective: Perspective) -> None:
        with self.driver.session(database=self.database) as session:
            session.execute_write(self._write_perspective, perspective)

    def load_base(self, base: BaseGraph) -> None:
        with self.driver.session(database=self.database) as session:
            session.execute_write(self._write_base, base)

    @staticmethod
    def _concept_key(run: str, actor: int, concept: Concept) -> str:
        return scoped(run, actor, "concept", concept.id)

    @staticmethod
    def _write_base(tx: Any, base: BaseGraph) -> None:
        for concept in base.concepts:
            GraphStore._write_concept(tx, base.run, base.actor, concept)
        for link in base.links:
            subject = scoped(base.run, base.actor, "concept", link.subject)
            object_key = scoped(base.run, base.actor, "concept", link.object)
            tx.run(
                "MATCH (s:Concept {key:$subject}), (o:Concept {key:$object}) "
                "MERGE (s)-[:SEMANTIC {relation:$relation, source:$source}]->(o)",
                subject=subject, object=object_key,
                relation=link.relation, source=link.source,
            ).consume()

    @staticmethod
    def _write_perspective(tx: Any, perspective: Perspective) -> None:
        run, actor = perspective.run, perspective.actor
        perspective_key = scoped(run, actor, "perspective", "self")
        tx.run(
            "MERGE (p:Perspective {key:$key}) "
            "ON CREATE SET p.run=$run, p.actor=$actor",
            key=perspective_key, run=run, actor=actor,
        ).consume()
        for claim in perspective.claims:
            GraphStore._write_claim(tx, perspective_key, run, actor, claim)

    @staticmethod
    def _write_concept(tx: Any, run: str, actor: int, concept: Concept) -> str:
        key = GraphStore._concept_key(run, actor, concept)
        row = tx.run(
            "MERGE (c:Concept {key:$key}) "
            "ON CREATE SET c.run=$run, c.actor=$actor, c.local_id=$local_id, "
            "c.kind=$kind, c.label=$label "
            "RETURN c.kind AS kind, c.label AS label, c.actor AS actor",
            key=key, run=run, actor=actor, local_id=concept.id,
            kind=concept.kind, label=concept.label,
        ).single(strict=True)
        if (row["kind"] != concept.kind or row["label"] != concept.label
                or row["actor"] != actor):
            raise ValueError(f"concept {concept.id} conflicts with existing identity")
        return key

    @staticmethod
    def _write_evidence(tx: Any, run: str, actor: int, evidence: Evidence) -> str:
        key = scoped(run, actor, "evidence", evidence.id)
        row = tx.run(
            "MERGE (e:Evidence {key:$key}) "
            "ON CREATE SET e.run=$run, e.actor=$actor, e.source_id=$source_id, "
            "e.kind=$kind, e.summary=$summary "
            "RETURN e.kind AS kind, e.summary AS summary",
            key=key, run=run, actor=actor, source_id=evidence.id,
            kind=evidence.kind, summary=evidence.summary,
        ).single(strict=True)
        if row["kind"] != evidence.kind or row["summary"] != evidence.summary:
            raise ValueError(f"evidence {evidence.id} conflicts with existing source")
        return key

    @staticmethod
    def _write_claim(
        tx: Any, perspective_key: str, run: str, actor: int, claim: Claim
    ) -> None:
        subject_key = GraphStore._write_concept(tx, run, actor, claim.subject)
        object_key = GraphStore._write_concept(tx, run, actor, claim.object)
        evidence_keys = [
            GraphStore._write_evidence(tx, run, actor, source)
            for source in claim.evidence
        ]
        claim_key = scoped(run, actor, "claim", claim.id)
        payload = claim.payload()
        row = tx.run(
            "MERGE (c:Claim {key:$key}) "
            "ON CREATE SET c.run=$run, c.actor=$actor, c.local_id=$local_id, "
            "c.relation=$relation, c.confidence=$confidence, c.polarity=$polarity, "
            "c.state=$state, c.note=$note, c.payload=$payload "
            "RETURN c.payload AS payload",
            key=claim_key, run=run, actor=actor, local_id=claim.id,
            relation=claim.relation, confidence=claim.confidence,
            polarity=claim.polarity, state=claim.state, note=claim.note,
            payload=payload,
        ).single(strict=True)
        if row["payload"] != payload:
            raise ValueError(f"claim {claim.id} conflicts with existing immutable revision")
        tx.run(
            "MATCH (p:Perspective {key:$perspective}), "
            "(c:Claim {key:$claim}), (s:Concept {key:$subject}), "
            "(o:Concept {key:$object}) "
            "MERGE (p)-[:HOLDS]->(c) "
            "MERGE (c)-[:SUBJECT]->(s) "
            "MERGE (c)-[:OBJECT]->(o)",
            perspective=perspective_key, claim=claim_key,
            subject=subject_key, object=object_key,
        ).consume()
        for evidence_key in evidence_keys:
            tx.run(
                "MATCH (c:Claim {key:$claim}), (e:Evidence {key:$evidence}) "
                "MERGE (c)-[:GROUNDED_IN]->(e)",
                claim=claim_key, evidence=evidence_key,
            ).consume()
        if claim.supersedes is not None:
            prior_key = scoped(run, actor, "claim", claim.supersedes)
            row = tx.run(
                "MATCH (p:Perspective {key:$perspective})-[:HOLDS]->"
                "(prior:Claim {key:$prior}) RETURN prior.key AS key",
                perspective=perspective_key, prior=prior_key,
            ).single()
            if row is None:
                raise ValueError(f"superseded claim {claim.supersedes} is not owned")
            tx.run(
                "MATCH (current:Claim {key:$current}), (prior:Claim {key:$prior}) "
                "MERGE (current)-[:REVISES]->(prior) "
                "SET prior.state='superseded'",
                current=claim_key, prior=prior_key,
            ).consume()

    def context(self, run: str, actor: int) -> list[dict[str, Any]]:
        key = scoped(run, actor, "perspective", "self")
        rows, _, _ = self.driver.execute_query(
            "MATCH (p:Perspective {key:$perspective})-[:HOLDS]->(c:Claim) "
            "WHERE c.state='active' "
            "MATCH (c)-[:SUBJECT]->(s:Concept), (c)-[:OBJECT]->(o:Concept) "
            "OPTIONAL MATCH (c)-[:GROUNDED_IN]->(e:Evidence) "
            "RETURN c.local_id AS id, c.relation AS relation, "
            "c.confidence AS confidence, c.polarity AS polarity, c.note AS note, "
            "s.local_id AS subject_id, s.label AS subject, s.kind AS subject_kind, "
            "o.local_id AS object_id, o.label AS object, o.kind AS object_kind, "
            "collect(DISTINCT {id:e.source_id, kind:e.kind, summary:e.summary}) AS evidence "
            "ORDER BY id",
            perspective=key, database_=self.database,
        )
        return [dict(row) for row in rows]

    def related(self, run: str, actor: int, concept_id: str) -> list[dict[str, Any]]:
        perspective_key = scoped(run, actor, "perspective", "self")
        concept_key = scoped(run, actor, "concept", concept_id)
        rows, _, _ = self.driver.execute_query(
            "MATCH (p:Perspective {key:$perspective})-[:HOLDS]->(c:Claim) "
            "WHERE c.state='active' "
            "MATCH (c)-[:SUBJECT]->(s:Concept {key:$concept}) "
            "MATCH (c)-[:OBJECT]->(o:Concept) "
            "RETURN c.local_id AS id, c.relation AS relation, "
            "c.confidence AS confidence, c.polarity AS polarity, "
            "o.local_id AS object_id, o.label AS object "
            "ORDER BY id",
            perspective=perspective_key, concept=concept_key,
            database_=self.database,
        )
        return [dict(row) for row in rows]

    def paths(self, run: str, actor: int, concept_id: str) -> list[dict[str, Any]]:
        """Find two accepted concept relations within one subjective perspective."""
        perspective_key = scoped(run, actor, "perspective", "self")
        concept_key = scoped(run, actor, "concept", concept_id)
        rows, _, _ = self.driver.execute_query(
            "MATCH (p:Perspective {key:$perspective})-[:HOLDS]->(first:Claim) "
            "WHERE first.state='active' "
            "MATCH (first)-[:SUBJECT]->(:Concept {key:$concept}) "
            "MATCH (first)-[:OBJECT]->(middle:Concept) "
            "MATCH (p)-[:HOLDS]->(second:Claim)-[:SUBJECT]->(middle) "
            "WHERE second.state='active' "
            "MATCH (second)-[:OBJECT]->(end:Concept) "
            "RETURN first.local_id AS first_claim, first.relation AS first_relation, "
            "middle.local_id AS middle_id, middle.label AS middle, "
            "second.local_id AS second_claim, second.relation AS second_relation, "
            "end.local_id AS end_id, end.label AS end "
            "ORDER BY first_claim, second_claim",
            perspective=perspective_key, concept=concept_key,
            database_=self.database,
        )
        return [dict(row) for row in rows]

    def semantics(self, run: str, actor: int, concept_id: str) -> list[dict[str, Any]]:
        """Show one actor's own sourced knowledge links."""
        concept_key = scoped(run, actor, "concept", concept_id)
        rows, _, _ = self.driver.execute_query(
            "MATCH (concept:Concept {key:$concept}) "
            "MATCH (concept)-[link:SEMANTIC]->(related:Concept) "
            "RETURN DISTINCT concept.local_id AS concept_id, concept.label AS concept, "
            "link.relation AS relation, link.source AS source, related.local_id AS related_id, "
            "related.label AS related "
            "ORDER BY relation, related_id",
            concept=concept_key,
            database_=self.database,
        )
        return [dict(row) for row in rows]

    def trace(self, run: str, actor: int, claim_id: str) -> dict[str, Any] | None:
        perspective_key = scoped(run, actor, "perspective", "self")
        claim_key = scoped(run, actor, "claim", claim_id)
        rows, _, _ = self.driver.execute_query(
            "MATCH (p:Perspective {key:$perspective})-[:HOLDS]->(c:Claim {key:$claim}) "
            "OPTIONAL MATCH (c)-[:GROUNDED_IN]->(e:Evidence) "
            "WITH c, collect(DISTINCT {id:e.source_id, kind:e.kind, summary:e.summary}) AS evidence "
            "OPTIONAL MATCH (c)-[:REVISES]->(prior:Claim) "
            "RETURN c.local_id AS id, c.state AS state, c.payload AS payload, "
            "evidence, prior.local_id AS supersedes",
            perspective=perspective_key, claim=claim_key,
            database_=self.database,
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["payload"] = json.loads(row["payload"])
        return row
