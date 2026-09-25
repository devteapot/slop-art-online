"""Run against a disposable Neo4j instance when credentials are supplied."""

import copy
import json
import os
import unittest
import uuid
from pathlib import Path

from .model import BaseGraph, Perspective
from .store import GraphStore


@unittest.skipUnless(os.environ.get("CONCEPT_GRAPH_NEO4J_PASSWORD"), "Neo4j credentials not supplied")
class LiveStoreTests(unittest.TestCase):
    def test_revisions_open_relations_and_actor_scope(self):
        from neo4j import GraphDatabase

        run = "concept-test-" + uuid.uuid4().hex
        base = Path(__file__).parent / "examples"
        password = os.environ["CONCEPT_GRAPH_NEO4J_PASSWORD"]
        uri = os.environ.get("CONCEPT_GRAPH_NEO4J_URI", "bolt://127.0.0.1:7688")
        with GraphDatabase.driver(uri, auth=("neo4j", password)) as driver:
            store = GraphStore(driver)
            store.initialize()
            try:
                mira_raw = json.loads((base / "mira.json").read_text())
                tovan_raw = json.loads((base / "tovan.json").read_text())
                mira_base_raw = json.loads((base / "base.json").read_text())
                tovan_base_raw = json.loads((base / "tovan-base.json").read_text())
                mira_raw["run"] = run
                tovan_raw["run"] = run
                mira_base_raw["run"] = run
                tovan_base_raw["run"] = run
                mira = Perspective.parse(mira_raw)
                tovan = Perspective.parse(tovan_raw)
                store.load_base(BaseGraph.parse(mira_base_raw))
                store.load_base(BaseGraph.parse(tovan_base_raw))
                store.load(mira)
                store.load(tovan)
                store.load(mira)  # projection replay must be idempotent

                mira_context = store.context(run, 1)
                self.assertEqual({row["id"] for row in mira_context}, {
                    "thicket-unsafe-after-injury", "thicket-guided-by-renn",
                    "renn-owes-food", "masked-stranger-threatens-mira"
                })
                self.assertEqual({row["id"] for row in store.context(run, 2)}, {
                    "thicket-safe-personal"
                })
                self.assertEqual(store.context(run, 3), [])
                self.assertEqual(store.related(run, 1, "person:renn")[0]["relation"], "owes_food_to")
                self.assertEqual(store.related(run, 2, "person:renn"), [])
                self.assertEqual(store.related(run, 1, "person:masked-stranger")[0]["relation"], "threatens")
                self.assertEqual(store.related(run, 2, "person:masked-stranger"), [])
                self.assertEqual(store.semantics(run, 1, "place:thicket")[0]["related_id"], "concept:place")
                self.assertEqual(store.semantics(run, 2, "place:thicket")[0]["related_id"], "concept:route")
                self.assertEqual(store.semantics(run, 2, "person:renn"), [])
                separate, _, _ = driver.execute_query(
                    "MATCH (c:Concept {run:$run, local_id:'place:thicket'}) "
                    "RETURN c.actor AS actor, c.label AS label ORDER BY actor",
                    run=run, database_="neo4j",
                )
                self.assertEqual([(row["actor"], row["label"]) for row in separate],
                                 [(1, "the thicket"), (2, "the eastern trail")])
                paths = store.paths(run, 1, "place:thicket")
                self.assertIn(("guided_by", "owes_food_to", "person:mira"), {
                    (path["first_relation"], path["second_relation"], path["end_id"])
                    for path in paths
                })
                self.assertEqual(store.paths(run, 2, "place:thicket"), [])
                old = store.trace(run, 1, "thicket-safe-heard")
                self.assertEqual(old["state"], "superseded")
                self.assertEqual(store.trace(run, 2, "thicket-safe-heard"), None)
                self.assertEqual(
                    store.trace(run, 1, "thicket-unsafe-after-injury")["supersedes"],
                    "thicket-safe-heard",
                )

                conflicting = copy.deepcopy(mira_raw)
                conflicting["claims"][0]["note"] = "silently rewritten"
                with self.assertRaisesRegex(ValueError, "immutable revision"):
                    store.load(Perspective.parse(conflicting))
                self.assertEqual(store.trace(run, 1, "thicket-safe-heard")["payload"]["note"],
                                 mira_raw["claims"][0]["note"])
            finally:
                driver.execute_query(
                    "MATCH (n) WHERE n.run=$run DETACH DELETE n",
                    run=run, database_="neo4j",
                )


if __name__ == "__main__":
    unittest.main()
