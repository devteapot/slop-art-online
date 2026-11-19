#!/usr/bin/env python3
"""Self-test of law_values.own_laws on a module with `law_override` and one from before it.

    python3 living/tools/law_values_selftest.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from law_values import own_laws  # noqa: E402

WORLD_LAW = [{"name": "cues_on", "value": "false"}, {"name": "fire_warmth", "value": "2.0"}]


class OwnLaws(unittest.TestCase):
    def test_an_older_module_reads_world_law(self):
        def old(q):
            if "law_override" in q:
                raise RuntimeError("no such table: law_override")
            return WORLD_LAW
        self.assertEqual(own_laws(old), {"cues_on": "false", "fire_warmth": "2.0"})

    def test_a_helper_that_exits_on_an_error_reads_the_same(self):
        def exits(q):
            if "law_override" in q:
                raise SystemExit(1)
            return WORLD_LAW
        self.assertEqual(own_laws(exits), {"cues_on": "false", "fire_warmth": "2.0"})

    def test_law_override_is_laid_over_world_law(self):
        over = [{"name": "cues_on", "value": "true"}, {"name": "near_tier_on", "value": "false"}]
        self.assertEqual(own_laws(lambda q: WORLD_LAW if "world_law" in q else over),
                         {"cues_on": "true", "fire_warmth": "2.0", "near_tier_on": "false"})

    def test_a_wrong_call_or_an_unreadable_world_law_is_an_error(self):
        with self.assertRaises(TypeError):
            own_laws(lambda q, save: [])
        def unreadable(q):
            raise RuntimeError("world_law is private")
        with self.assertRaises(RuntimeError):
            own_laws(unreadable)


if __name__ == "__main__":
    unittest.main()
