"""Run against a disposable Neo4j instance when credentials are supplied."""

import json
import os
import unittest
import uuid
from pathlib import Path

from .mind import MindLog
from .mind_store import MindStore

EXAMPLES = Path(__file__).parent / "examples"


def log(name, run):
    raw = json.loads((EXAMPLES / name).read_text())
    raw["run"] = run
    return raw


@unittest.skipUnless(os.environ.get("CONCEPT_GRAPH_NEO4J_PASSWORD"), "Neo4j credentials not supplied")
class LiveMindTests(unittest.TestCase):
    def test_open_structure_queries_stay_inside_one_mind(self):
        from neo4j import GraphDatabase

        run = "mind-test-" + uuid.uuid4().hex
        password = os.environ["CONCEPT_GRAPH_NEO4J_PASSWORD"]
        uri = os.environ.get("CONCEPT_GRAPH_NEO4J_URI", "bolt://127.0.0.1:7688")
        with GraphDatabase.driver(uri, auth=("neo4j", password)) as driver:
            store = MindStore(driver)
            store.initialize()
            try:
                first = MindLog.parse(log("mira-mind.json", run))
                later = MindLog.parse(log("mira-mind-later.json", run))
                with self.assertRaisesRegex(ValueError, "gap"):
                    store.load(later)
                self.assertEqual(store.load(first)["appended"], 45)
                self.assertEqual(store.load(first)["appended"], 0)
                store.load(MindLog.parse(log("tovan-mind.json", run)))

                def near(actor, concept):
                    return {row["id"] for row in store.near(run, actor, concept, 3)}

                def rests_on(concept):
                    return {row["id"] for row in store.rests_on(run, 1, concept)["beliefs"]}

                self.assertNotIn("k:renn-owes-meal", near(1, "c:masked"))
                self.assertEqual(rests_on("c:renn"), {"k:renn-guides", "k:renn-owes-meal"})
                self.assertEqual(rests_on("c:masked"), set())

                self.assertEqual(store.load(later)["head"], 55)
                self.assertIn("k:renn-owes-meal", near(1, "c:masked"))
                self.assertEqual(rests_on("c:masked"), {"k:renn-guides", "k:renn-owes-meal"})
                self.assertEqual(rests_on("c:tovan"), {"k:renn-wears-mask"})

                verdicts = {row["report"]: row["verdict"] for row in store.reports(run, 1)}
                self.assertEqual(verdicts["k:renn-said-safe"], "disputed")
                self.assertEqual(verdicts["k:renn-said-guides"], "accepted")
                self.assertEqual([r["report"] for r in store.reports(run, 1, "c:masked")],
                                 ["k:renn-said-safe", "k:renn-said-guides", "k:renn-promised-meal"])

                safe = next(r for r in store.context(run, 1) if r["id"] == "k:thicket-safe")
                self.assertEqual(safe["credence"], 10)
                self.assertEqual({(c["id"], c["bearing"]) for c in safe["cites"]},
                                 {("k:renn-said-safe", "supports"), ("percept:102", "opposes")})
                self.assertEqual([s["revises"] for s in store.trace(run, 1, "k:thicket-safe")],
                                 [[], ["s:5"]])

                self.assertEqual(near(2, "c:thicket"), {"k:trail-is-route", "k:trail-safe"})
                self.assertEqual(store.reports(run, 2), [])
                self.assertEqual(store.context(run, 3), [])

                changed = log("mira-mind.json", run)
                changed["events"][37]["note"] = "silently rewritten"
                with self.assertRaisesRegex(ValueError, "immutable"):
                    store.load(MindLog.parse(changed))
            finally:
                driver.execute_query(
                    "MATCH (n) WHERE n.run=$run DETACH DELETE n",
                    run=run, database_="neo4j",
                )


if __name__ == "__main__":
    unittest.main()
