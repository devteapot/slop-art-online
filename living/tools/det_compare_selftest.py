#!/usr/bin/env python3
"""Check that det_compare renames sequence IDs and still detects a real row change.

    python3 living/tools/det_compare_selftest.py -v
"""
import json
import unittest

from det_compare import FAR_BASE, normalized


def snapshot(offset=0, structure_skip=0):
    # Deliberately overlap numeric IDs in unrelated tables, and keep two structures
    # so dropping IDs, conflating namespaces, or losing the target rank is detectable.
    actor, other = 2 + offset, 8 + offset
    structure, second = 2 + offset + structure_skip, 9 + offset + structure_skip
    handle = FAR_BASE + 5 + offset
    node, offer = 6 + offset, 2 + offset
    scene = {
        "you": {
            "id": actor,
            "asked of you": [{"from": other, "offer": offer}],
            "you are waiting on": [{"to": other, "offer": offer}],
            "decided, not yet done": [f"inspect → #{second}", f"approach → #{handle}"],
        },
        "creatures": [{"id": handle, "visibly": {"at": actor}}, {"id": other, "visibly": {"at": "you"}}],
        "you smell (out of sight)": [{"id": other}],
        "who would hear you now": f"an unknown figure (#{handle}), a person (#{other})",
        "structures": [
            {"id": structure, "kind": "house"},
            {"id": second, "kind": "sign"},
            {"kind": "counted_remains", "text": "one remains"},
        ],
        "resources": [{"nearest": {"id": node, "amount": 20}}],
        "terrain_near": {"road": "20 tiles east"},
    }
    return {
        "character": [{"id": actor}, {"id": other}],
        "structure": [{"id": structure}, {"id": second}],
        "resource_node": [{"id": node, "pool": 0}],
        "trade_offer": [{"id": offer}],
        "far_handle": [{"id": handle - FAR_BASE}],
        "deliberation": [{
            "actor": actor,
            "scene": json.dumps(scene, ensure_ascii=False),
            "reason": (
                f"A trade (offer {offer}), or let it pass.\n"
                f"Someone (#{other}) asks to start a family with you;\n"
                f"You long for a child with someone (#{other}).\n"
                f"What you had decided did not work out: inspect → #{second}: no #{second} in sight."
            ),
            "arrived": "16 16",
        }],
    }


class DeliberationIds(unittest.TestCase):
    def test_sequence_skip_is_visible_raw_and_equal_after_normalization(self):
        base = snapshot()
        shifted = snapshot(structure_skip=4096)
        self.assertNotEqual(base["deliberation"], shifted["deliberation"])
        self.assertEqual(normalized(base), normalized(shifted))
        row, = normalized(shifted)["deliberation"]
        scene = json.loads(row["scene"])
        self.assertEqual([item.get("id") for item in scene["structures"]], [0, 1, None])
        self.assertEqual(scene["creatures"][0]["id"], FAR_BASE)
        self.assertEqual(scene["you"]["decided, not yet done"], ["inspect → #structure:1", "approach → #far_handle:0"])

    def test_other_sequence_namespaces_are_ranked_too(self):
        self.assertEqual(normalized(snapshot()), normalized(snapshot(4096)))

    def test_one_scene_word_change_survives_sequence_skip(self):
        base = normalized(snapshot())
        shifted = snapshot(structure_skip=4096)
        row, = shifted["deliberation"]
        row["scene"] = row["scene"].replace('"kind": "house"', '"kind": "shed"')
        candidate = normalized(shifted)
        self.assertEqual([table for table in base if base[table] != candidate[table]], ["deliberation"])
        self.assertIn('"kind":"shed"', candidate["deliberation"][0]["scene"])

    def test_changing_an_id_reference_still_counts_as_a_difference(self):
        changed = snapshot()
        row, = changed["deliberation"]
        row["scene"] = row["scene"].replace('"id": 9, "kind": "sign"', '"id": 2, "kind": "sign"')
        self.assertNotEqual(normalized(snapshot())["deliberation"], normalized(changed)["deliberation"])


if __name__ == "__main__":
    unittest.main()
