#!/usr/bin/env python3
"""Self-test of the trial runner's laws guard (living/tools/trials.py `laws_problems` and
`Instance.publish`) and the shared composition it uses (living/tools/install_script.py).

An instance must not start on a world whose laws are not its seed's: the `script` row read back
after the install must be the source sent; for a seed with laws (Cullet's, the hamlet's), the
world's creation-time composition must equal the runner's and `world.day_ms` the seed's
`day_minutes`; a `keep_laws` variant (no install) must find the composition in the row. Each
mismatch is planted here and must be refused: `publish` raises, logs and emits an `error` event,
before any mind starts. No server, no network: `publish` runs against a fake database.

Usage: python3 living/tools/trials_laws_selftest.py [-v]
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import install_script  # noqa: E402
import trials  # noqa: E402

TREE = (trials.ROOT / "living/scripts/skills.rhai").read_text()
HAMLET = json.loads((trials.ROOT / "living/seeds/hamlet.json").read_text())
LAWS = install_script.seed_laws(HAMLET)
COMPOSED = install_script.compose_laws(TREE, LAWS)
DAY = round(float(HAMLET["day_minutes"]) * 60000)


class Problems(unittest.TestCase):
    def test_matching_world_passes(self):
        self.assertEqual(trials.laws_problems(HAMLET, LAWS, COMPOSED, COMPOSED, COMPOSED, COMPOSED, DAY), [])

    def test_world_law_values_are_not_a_difference(self):
        row = COMPOSED + "\n" + install_script.WORLD_LAW_MARK + "\nfn world_laws() { #{ minds: false } }\n"
        self.assertEqual(trials.laws_problems(HAMLET, LAWS, COMPOSED, row, COMPOSED, row, DAY), [])

    def test_bare_script_installed_is_refused(self):
        # The regression: the bare file installed over a world with laws (what was sent and what
        # the world runs no longer carry them; here the row is bare while the laws were sent).
        bad = trials.laws_problems(HAMLET, LAWS, COMPOSED, COMPOSED, COMPOSED, TREE, DAY)
        self.assertTrue(any("read back" in b for b in bad), bad)

    def test_creation_composition_differs_is_refused(self):
        bad = trials.laws_problems(HAMLET, LAWS, COMPOSED, COMPOSED.replace("fn hunger_awake() { 2.4 }", "fn hunger_awake() { 2.5 }"), COMPOSED, COMPOSED, DAY)
        self.assertTrue(any("creation-time composition" in b for b in bad), bad)

    def test_day_mismatch_is_refused(self):
        bad = trials.laws_problems(HAMLET, LAWS, COMPOSED, COMPOSED, COMPOSED, COMPOSED, trials.DEFAULT_DAY_MS)
        self.assertTrue(any("day_ms" in b for b in bad), bad)

    def test_keep_laws_checks_the_row(self):
        self.assertEqual(trials.laws_problems(HAMLET, LAWS, COMPOSED, COMPOSED, None, COMPOSED, DAY), [])
        bad = trials.laws_problems(HAMLET, LAWS, COMPOSED, TREE, None, TREE, DAY)
        self.assertTrue(any("keeps its own laws" in b for b in bad), bad)

    def test_other_branch_module_needs_the_overlay(self):
        self.assertEqual(trials.laws_problems(HAMLET, LAWS, None, COMPOSED, COMPOSED, COMPOSED, DAY), [])
        bad = trials.laws_problems(HAMLET, LAWS, None, TREE, COMPOSED, COMPOSED, DAY)
        self.assertTrue(any("does not end with the seed's laws" in b for b in bad), bad)

    def test_seed_without_laws(self):
        plain = {"name": "plain"}
        self.assertEqual(trials.laws_problems(plain, "", TREE, TREE, TREE, TREE, trials.DEFAULT_DAY_MS), [])
        self.assertTrue(trials.laws_problems(plain, "", TREE, TREE, TREE, COMPOSED, trials.DEFAULT_DAY_MS))


class Composition(unittest.TestCase):
    def test_one_copy(self):
        self.assertIs(trials.compose_laws, install_script.compose_laws)
        self.assertIs(trials.seed_laws, install_script.seed_laws)

    def test_compose_shape(self):
        self.assertTrue(COMPOSED.endswith(install_script.OVERLAY_MARK + LAWS))
        for name in {m.group(3) for m in install_script.DEF.finditer(LAWS)}:
            if f"fn {name}(" in TREE:
                self.assertIn(f"fn base_{name}(", COMPOSED)
        self.assertEqual(install_script.seed_script("hamlet")[0], COMPOSED)
        self.assertEqual(install_script.seed_script("world"), (TREE, ""))

    def test_base_names_refused(self):
        with self.assertRaises(ValueError):
            install_script.compose_laws(TREE, "fn base_rates(a) { 1 }")


class FakeDb:
    """The rows `publish` reads, and what `install_script` writes."""

    def __init__(self, creation, day_ms, write=None):
        self.script, self.day_ms, self.write, self.installs = creation, day_ms, write, []

    def http(self, path, body=None, token=None, raw=False, timeout=30, method=None):
        if path.endswith("/call/install_script"):
            self.installs.append(body[0])
            self.script = self.write(body[0]) if self.write else body[0]
            return 200, ""
        raise AssertionError(path)

    def rows(self, query):
        if "FROM script" in query:
            return [{"source": self.script}]
        if "day_ms FROM world" in query:
            return [{"day_ms": self.day_ms}]
        if "FROM stats" in query:
            return [{"ticks": 1}]
        if "FROM world" in query:
            return [{"day_ms": self.day_ms}]
        if "FROM land" in query:
            return []
        raise AssertionError(query)


class Publish(unittest.TestCase):
    """`Instance.publish` on a fake database: the guard refuses before the instance goes on."""

    def instance(self, db, variant=None):
        inst = trials.Instance.__new__(trials.Instance)
        inst.trial = {"name": "selftest", "world": {"seed": "hamlet"}}
        inst.rep, inst.variant, inst.db = 1, "v", "verify-trial-selftest-none"
        inst.shared = {"wasm": {"selftest": "selftest"}, "variants": {"v": variant or {}}, "token": "x"}
        inst.dir = Path(self.tmp.name)
        inst.t0, inst.published = None, False
        inst.save = lambda: None
        inst.rows = db.rows
        return inst

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = trials.sh, trials.http, trials.served_name
        trials.sh = lambda *a, **k: None
        trials.served_name = lambda n: n

    def tearDown(self):
        trials.sh, trials.http, trials.served_name = self.saved
        self.tmp.cleanup()

    def events(self):
        p = Path(self.tmp.name) / "events.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def test_passes_on_a_world_running_its_laws(self):
        db = FakeDb(COMPOSED, DAY)
        trials.http = db.http
        self.instance(db).publish()
        self.assertEqual(db.installs, [COMPOSED])
        self.assertEqual(self.events(), [])
        self.assertIn("laws guard passed", (Path(self.tmp.name) / "actions.log").read_text())

    def test_refuses_a_bare_world(self):
        # A world whose creation dropped its laws: the runner's composition differs from it.
        db = FakeDb(TREE, DAY)
        trials.http = db.http
        with self.assertRaisesRegex(RuntimeError, "laws guard: .*creation-time composition"):
            self.instance(db).publish()
        self.assertTrue(any("creation-time composition" in e.get("error", "") for e in self.events()))

    def test_refuses_an_install_the_row_does_not_hold(self):
        db = FakeDb(COMPOSED, DAY, write=lambda src: TREE)
        trials.http = db.http
        with self.assertRaisesRegex(RuntimeError, "laws guard: .*read back"):
            self.instance(db).publish()
        self.assertTrue(any("read back" in e.get("error", "") for e in self.events()))

    def test_refuses_a_wrong_day(self):
        db = FakeDb(COMPOSED, trials.DEFAULT_DAY_MS)
        trials.http = db.http
        with self.assertRaisesRegex(RuntimeError, "laws guard: .*day_ms"):
            self.instance(db).publish()

    def test_keep_laws_variant(self):
        db = FakeDb(COMPOSED, DAY)
        trials.http = db.http
        self.instance(db, {"keep_laws": True}).publish()
        self.assertEqual(db.installs, [])
        db = FakeDb(TREE, DAY)
        trials.http = db.http
        with self.assertRaisesRegex(RuntimeError, "keeps its own laws"):
            self.instance(db, {"keep_laws": True}).publish()
        self.assertEqual(db.installs, [])


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)
