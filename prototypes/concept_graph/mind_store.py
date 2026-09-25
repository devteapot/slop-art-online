"""Neo4j projection of actor mind logs and open-structure queries over one actor."""

from __future__ import annotations

import json
from typing import Any

from .mind import MindLog, MindState, parse_event, payload
from .model import scoped

CONSTRAINTS = (
    "CREATE CONSTRAINT mind_key IF NOT EXISTS FOR (n:Mind) REQUIRE n.mind_key IS UNIQUE",
    "CREATE CONSTRAINT mind_item_key IF NOT EXISTS FOR (n:MindItem) REQUIRE n.item_key IS UNIQUE",
    "CREATE CONSTRAINT mind_event_key IF NOT EXISTS FOR (n:MindItem) REQUIRE n.event_key IS UNIQUE",
    "CREATE INDEX mind_item_scope IF NOT EXISTS FOR (n:MindItem) ON (n.run, n.actor)",
)
LABELS = {"concept": "Concept", "evidence": "Evidence", "claim": "Claim", "stance": "Stance"}
CURRENT = "NOT EXISTS {{ (:Stance)-[:REVISES]->({0}) }}"
CLAIM_VIEW = (
    "MATCH (k)-[:PREDICATE]->(pred:Concept) "
    "OPTIONAL MATCH (cur:Stance)-[:ABOUT]->(k) WHERE " + CURRENT.format("cur") + " "
    "RETURN k.local_id AS id, k.seq AS seq, pred.label AS predicate, cur.credence AS credence, "
    "k.values AS values, "
    "COLLECT { MATCH (k)-[r:ROLE]->(t) RETURN {role:r.name, id:t.local_id, label:t.label} } AS roles, "
    "COLLECT { MATCH (st:Stance)-[:ABOUT]->(k) MATCH (st)-[c:CITES]->(ref) "
    "RETURN DISTINCT {id:ref.local_id, bearing:c.bearing, kind:ref.kind} } AS cites"
)


def item_key(run: str, actor: int, local_id: str) -> str:
    return scoped(run, actor, "mind", local_id)


class MindStore:
    def __init__(self, driver: Any, database: str = "neo4j") -> None:
        self.driver = driver
        self.database = database

    def initialize(self) -> None:
        for statement in CONSTRAINTS:
            self.driver.execute_query(statement, database_=self.database)

    def _query(self, statement: str, **parameters: Any) -> list[dict[str, Any]]:
        rows, _, _ = self.driver.execute_query(statement, database_=self.database, **parameters)
        return [dict(row) for row in rows]

    def load(self, log: MindLog) -> dict[str, Any]:
        with self.driver.session(database=self.database) as session:
            return session.execute_write(self._load, log)

    @staticmethod
    def _load(tx: Any, log: MindLog) -> dict[str, Any]:
        state = MindState()
        for row in list(tx.run(
            "MATCH (n:MindItem {run:$run, actor:$actor}) RETURN n.payload AS payload ORDER BY n.seq",
            run=log.run, actor=log.actor,
        )):
            state.apply(parse_event(json.loads(row["payload"])))
        appended = [event for event in log.events if state.apply(event)]
        for event in appended:
            MindStore._write(tx, log.run, log.actor, event)
        tx.run(
            "MERGE (m:Mind {mind_key:$key}) ON CREATE SET m.run=$run, m.actor=$actor SET m.head=$head",
            key=scoped(log.run, log.actor, "mind", "self"), run=log.run, actor=log.actor, head=state.head,
        ).consume()
        return {"run": log.run, "actor": log.actor, "head": state.head, "appended": len(appended)}

    @staticmethod
    def _edges(tx: Any, source: str, rel: str, prop: str, pairs: list[tuple[str, str]]) -> None:
        if pairs:
            tx.run(
                f"MATCH (s:MindItem {{item_key:$source}}) UNWIND $pairs AS pair "
                f"MATCH (t:MindItem {{item_key:pair.target}}) CREATE (s)-[:{rel} {{{prop}:pair.name}}]->(t)",
                source=source, pairs=[{"name": name, "target": target} for name, target in pairs],
            ).consume()

    @staticmethod
    def _write(tx: Any, run: str, actor: int, event: dict[str, Any]) -> None:
        def key(local_id: str) -> str:
            return item_key(run, actor, local_id)

        op, own = event["op"], key(event["id"])
        props = {
            "item_key": own, "event_key": scoped(run, actor, "mind-event", str(event["seq"])),
            "run": run, "actor": actor, "local_id": event["id"], "seq": event["seq"],
            "payload": payload(event),
        }
        if op == "concept":
            props["label"] = event["label"]
        elif op == "evidence":
            props.update(kind=event["kind"], tick=event["tick"], summary=event["summary"])
        elif op == "claim":
            props["predicate"] = key(event["predicate"])
            props["values"] = json.dumps(
                {role: value for role, value in event["roles"].items() if type(value) is int},
                sort_keys=True,
            )
        else:
            props.update(claim=key(event["claim"]), credence=event["credence"],
                         tick=event["tick"], note=event["note"])
        tx.run(f"CREATE (n:MindItem:{LABELS[op]}) SET n = $props", props=props).consume()

        if op == "evidence":
            MindStore._edges(tx, own, "INVOLVES", "role",
                             [(role, key(target)) for role, target in event["involves"].items()])
        elif op == "claim":
            tx.run(
                "MATCH (k:MindItem {item_key:$claim}), (p:MindItem {item_key:$predicate}) "
                "CREATE (k)-[:PREDICATE]->(p)",
                claim=own, predicate=props["predicate"],
            ).consume()
            MindStore._edges(tx, own, "ROLE", "name", [
                (role, key(target)) for role, target in event["roles"].items() if type(target) is str
            ])
        elif op == "stance":
            claim = props["claim"]
            tx.run(
                "MATCH (s:MindItem {item_key:$stance}), (k:MindItem {item_key:$claim}) "
                "CREATE (s)-[:ABOUT]->(k)",
                stance=own, claim=claim,
            ).consume()
            MindStore._edges(tx, own, "CITES", "bearing",
                             [(cite["bearing"], key(cite["ref"])) for cite in event["cites"]])
            for bearing, rel in (("supports", "SUPPORTED_BY"), ("opposes", "OPPOSED_BY")):
                MindStore._edges(tx, claim, rel, "stance", [
                    (event["id"], key(cite["ref"])) for cite in event["cites"] if cite["bearing"] == bearing
                ])
            if event["revises"] is not None:
                tx.run(
                    "MATCH (s:MindItem {item_key:$stance}), (p:MindItem {item_key:$prior}) "
                    "CREATE (s)-[:REVISES]->(p)",
                    stance=own, prior=key(event["revises"]),
                ).consume()

    def context(self, run: str, actor: int) -> list[dict[str, Any]]:
        """Every claim the actor has entertained, with current credence and all cited evidence."""
        return self._query(
            "MATCH (k:MindItem:Claim {run:$run, actor:$actor}) " + CLAIM_VIEW + " ORDER BY seq",
            run=run, actor=actor,
        )

    def near(self, run: str, actor: int, concept_id: str, depth: int) -> list[dict[str, Any]]:
        """Claims reachable through role edges, without routing through the actor's self or categories."""
        if type(depth) is not int or not 1 <= depth <= 6:
            raise ValueError("depth must be an integer from 1 to 6")
        return self._query(
            "MATCH (start:MindItem:Concept {item_key:$start}) "
            f"MATCH p = (start)-[:ROLE*1..{depth}]-(k:Claim) "
            "WHERE all(n IN nodes(p) WHERE n.run = $run AND n.actor = $actor) "
            "AND all(n IN nodes(p)[1..-1] WHERE n.item_key <> $me "
            "AND NOT (n:Claim AND n.predicate = $instance_of)) "
            "WITH k, min(length(p)) AS distance "
            + CLAIM_VIEW + ", distance ORDER BY distance, seq",
            run=run, actor=actor, start=item_key(run, actor, concept_id),
            me=item_key(run, actor, "core:self"),
            instance_of=item_key(run, actor, "core:instance_of"),
        )

    def identities(self, run: str, actor: int, concept_id: str, min_credence: int) -> list[str]:
        """The concept plus everything the actor currently believes is the same entity."""
        keys = {item_key(run, actor, concept_id)}
        for _ in range(8):
            rows = self._query(
                "MATCH (k:MindItem:Claim {run:$run, actor:$actor, predicate:$same_as})-[:ROLE]->(x:Concept) "
                "WHERE x.item_key IN $keys "
                "MATCH (cur:Stance)-[:ABOUT]->(k) WHERE " + CURRENT.format("cur") +
                " AND cur.credence >= $min "
                "MATCH (k)-[:ROLE]->(y:Concept) RETURN collect(DISTINCT y.item_key) AS keys",
                run=run, actor=actor, same_as=item_key(run, actor, "core:same_as"),
                keys=sorted(keys), min=min_credence,
            )
            found = keys | set(rows[0]["keys"])
            if found == keys:
                break
            keys = found
        return sorted(keys)

    def rests_on(self, run: str, actor: int, concept_id: str,
                 min_credence: int = 50, min_identity: int = 60) -> dict[str, Any]:
        """Current beliefs whose every support path runs through something this speaker said."""
        speakers = self.identities(run, actor, concept_id, min_identity)
        rows = self._query(
            "MATCH (k:MindItem:Claim {run:$run, actor:$actor}) "
            "MATCH (cur:Stance)-[:ABOUT]->(k) WHERE " + CURRENT.format("cur") +
            " AND cur.credence >= $min "
            "MATCH p = (k)-[:SUPPORTED_BY*1..8]->(:Evidence) "
            "WITH k, cur, [n IN nodes(p)[1..] WHERE n:Claim AND n.predicate = $asserted "
            "AND EXISTS { MATCH (n)-[:ROLE {name:'speaker'}]->(s) WHERE s.item_key IN $speakers }] AS via "
            "WITH k, cur, collect(size(via) > 0) AS routes "
            "WHERE all(r IN routes WHERE r) "
            "RETURN k.local_id AS id, k.seq AS seq, cur.credence AS credence, size(routes) AS support_paths "
            "ORDER BY seq",
            run=run, actor=actor, min=min_credence, speakers=speakers,
            asserted=item_key(run, actor, "core:asserted"),
        )
        return {"speakers": [key.rsplit("|", 1)[1] for key in speakers], "beliefs": rows}

    def reports(self, run: str, actor: int, speaker_id: str | None = None,
                min_identity: int = 60) -> list[dict[str, Any]]:
        """What each speaker is believed to have said, and whether the actor now believes it."""
        speakers = None if speaker_id is None else self.identities(run, actor, speaker_id, min_identity)
        rows = self._query(
            "MATCH (a:MindItem:Claim {run:$run, actor:$actor, predicate:$asserted}) "
            "MATCH (a)-[:ROLE {name:'speaker'}]->(sp:Concept), (a)-[:ROLE {name:'content'}]->(k:Claim) "
            "WHERE $speakers IS NULL OR sp.item_key IN $speakers "
            "OPTIONAL MATCH (sa:Stance)-[:ABOUT]->(a) WHERE " + CURRENT.format("sa") + " "
            "OPTIONAL MATCH (sk:Stance)-[:ABOUT]->(k) WHERE " + CURRENT.format("sk") + " "
            "RETURN sp.local_id AS speaker_id, sp.label AS speaker, a.local_id AS report, "
            "k.local_id AS content, sa.credence AS heard, sk.credence AS believed "
            "ORDER BY speaker_id, a.seq",
            run=run, actor=actor, speakers=speakers,
            asserted=item_key(run, actor, "core:asserted"),
        )
        for row in rows:
            believed = row["believed"]
            row["verdict"] = ("unassessed" if believed is None else "disputed" if believed <= 30
                              else "accepted" if believed >= 70 else "unsure")
        return rows

    def trace(self, run: str, actor: int, claim_id: str) -> list[dict[str, Any]]:
        return self._query(
            "MATCH (st:MindItem:Stance {run:$run, actor:$actor, claim:$claim}) "
            "RETURN st.local_id AS id, st.seq AS seq, st.tick AS tick, st.credence AS credence, "
            "st.note AS note, "
            "COLLECT { MATCH (st)-[c:CITES]->(r) RETURN {id:r.local_id, bearing:c.bearing} } AS cites, "
            "COLLECT { MATCH (st)-[:REVISES]->(p) RETURN p.local_id } AS revises "
            "ORDER BY seq",
            run=run, actor=actor, claim=item_key(run, actor, claim_id),
        )


def render(rows: list[dict[str, Any]]) -> str:
    """Compact one-line-per-claim context for a model prompt."""
    lines = []
    for row in rows:
        named = {role["role"]: role["label"] or f"«{role['id']}»" for role in row["roles"]}
        named.update({role: str(value) for role, value in json.loads(row.get("values") or "{}").items()})
        roles = ", ".join(f"{role}={value}" for role, value in sorted(named.items()))
        credence = "unassessed" if row["credence"] is None else f"credence {row['credence']}"
        parts = [f"[{row['id']}] {row['predicate']}({roles}) {credence}"]
        for bearing, heading in (("supports", "for"), ("opposes", "against")):
            refs = sorted(
                cite["id"] + (f" ({cite['kind']})" if cite["kind"] else "")
                for cite in row["cites"] if cite["bearing"] == bearing
            )
            if refs:
                parts.append(f"{heading}: {', '.join(refs)}")
        lines.append("; ".join(parts))
    return "\n".join(lines)
