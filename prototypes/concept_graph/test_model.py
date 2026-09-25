import copy
import json
import unittest
from pathlib import Path

from .model import BaseGraph, Perspective
from .snapshot import current_mind


EXAMPLES = Path(__file__).parent / "examples"


class ModelTests(unittest.TestCase):
    def test_open_predicate_and_revision(self):
        mira = Perspective.parse(json.loads((EXAMPLES / "mira.json").read_text()))
        base = BaseGraph.parse(json.loads((EXAMPLES / "base.json").read_text()))
        self.assertEqual(mira.claims[3].relation, "owes_food_to")
        self.assertEqual(mira.claims[1].supersedes, mira.claims[0].id)
        self.assertNotEqual(mira.claims[0].payload(), mira.claims[1].payload())
        self.assertEqual(base.actor, 1)
        self.assertEqual(mira.claims[4].subject.kind, "unresolved_person")
        self.assertEqual(base.links[2].relation, "instance_of")

    def test_claim_requires_evidence_and_bounded_confidence(self):
        raw = json.loads((EXAMPLES / "mira.json").read_text())
        missing = copy.deepcopy(raw)
        missing["claims"][0]["evidence"] = []
        with self.assertRaisesRegex(ValueError, "evidence"):
            Perspective.parse(missing)
        out_of_range = copy.deepcopy(raw)
        out_of_range["claims"][0]["confidence"] = 101
        with self.assertRaisesRegex(ValueError, "confidence"):
            Perspective.parse(out_of_range)

    def test_knowledge_graph_requires_actor_and_source(self):
        base = json.loads((EXAMPLES / "base.json").read_text())
        del base["actor"]
        with self.assertRaisesRegex(ValueError, "actor"):
            BaseGraph.parse(base)
        base = json.loads((EXAMPLES / "base.json").read_text())
        del base["links"][0]["source"]
        with self.assertRaisesRegex(ValueError, "source"):
            BaseGraph.parse(base)

    def test_snapshot_only_imports_selected_actor_and_current_mind(self):
        snapshot = {"world": {"players": [
            {"id": 1, "name": "Mira", "beliefs": [{"claim": {"location": 4, "danger": True, "text": "hurt"}, "source": 11, "confidence": 90}], "knowledge": [], "relationships": {}, "memories": [{"source": 11, "kind": "danger", "content": {"damage": 2}}]},
            {"id": 2, "name": "Tovan", "beliefs": [{"claim": {"location": 9, "danger": False, "text": "safe"}, "source": 22, "confidence": 50}], "knowledge": [], "relationships": {}, "memories": []},
        ]}}
        selected = current_mind(snapshot, "test-run", 1)
        self.assertEqual(selected.actor, 1)
        self.assertEqual(len(selected.claims), 1)
        self.assertEqual(selected.claims[0].subject.id, "location:4")
        self.assertEqual(selected.claims[0].evidence[0].id, "source:11")
        self.assertNotIn("location:9", selected.claims[0].payload())


if __name__ == "__main__":
    unittest.main()
