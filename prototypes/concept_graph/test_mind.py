import json
import unittest
from pathlib import Path

from .mind import MindLog, replay

EXAMPLES = Path(__file__).parent / "examples"


def raw(name):
    return json.loads((EXAMPLES / name).read_text())


def event(log, item):
    return next(e for e in log["events"] if e["id"] == item)


class MindLogTests(unittest.TestCase):
    def test_examples_replay_in_order(self):
        state = replay(MindLog.parse(raw("mira-mind.json")), MindLog.parse(raw("mira-mind-later.json")))
        self.assertEqual(state.head, 55)
        self.assertEqual(state.current["k:thicket-safe"], "s:10")
        self.assertEqual(replay(MindLog.parse(raw("tovan-mind.json"))).head, 11)

    def test_replay_is_idempotent_and_payloads_immutable(self):
        first = MindLog.parse(raw("mira-mind.json"))
        state = replay(first)
        self.assertFalse(any(state.apply(e) for e in first.events))
        changed = raw("mira-mind.json")
        event(changed, "s:5")["note"] = "silently rewritten"
        with self.assertRaisesRegex(ValueError, "immutable"):
            state.apply(MindLog.parse(changed).events[37])

    def test_later_batch_requires_its_predecessor(self):
        with self.assertRaisesRegex(ValueError, "gap"):
            replay(MindLog.parse(raw("mira-mind-later.json")))

    def test_references_must_already_exist(self):
        log = raw("mira-mind.json")
        event(log, "k:thicket-safe")["roles"]["condition"] = "c:nightfall"
        with self.assertRaisesRegex(ValueError, "earlier"):
            replay(MindLog.parse(log))

    def test_stances_form_one_revision_chain_per_claim(self):
        log = raw("mira-mind.json")
        del event(log, "s:10")["revises"]
        with self.assertRaisesRegex(ValueError, "must revise current stance s:5"):
            replay(MindLog.parse(log))
        log = raw("mira-mind.json")
        event(log, "s:1")["revises"] = "s:0"
        with self.assertRaisesRegex(ValueError, "no earlier stance"):
            replay(MindLog.parse(log))

    def test_core_predicates_keep_their_shape(self):
        log = raw("mira-mind.json")
        event(log, "k:renn-said-safe")["roles"]["content"] = "c:daylight"
        with self.assertRaisesRegex(ValueError, "content to be a claim"):
            replay(MindLog.parse(log))
        log = raw("mira-mind.json")
        event(log, "core:asserted")["id"] = "core:knows"
        with self.assertRaisesRegex(ValueError, "unknown core concept"):
            replay(MindLog.parse(log))

    def test_stance_cannot_cite_its_own_claim(self):
        log = raw("mira-mind.json")
        event(log, "s:5")["cites"].append({"ref": "k:thicket-safe", "bearing": "supports"})
        with self.assertRaisesRegex(ValueError, "own claim"):
            replay(MindLog.parse(log))

    def test_claim_roles_accept_integer_literals_only(self):
        log = raw("mira-mind.json")
        event(log, "k:renn-owes-meal")["roles"]["portions"] = 2
        self.assertEqual(replay(MindLog.parse(log)).head, 45)
        event(log, "k:renn-owes-meal")["roles"]["portions"] = True
        with self.assertRaisesRegex(ValueError, "identifier"):
            MindLog.parse(log)
        log = raw("mira-mind.json")
        event(log, "percept:101")["involves"]["tick"] = 40
        with self.assertRaisesRegex(ValueError, "identifier"):
            MindLog.parse(log)

    def test_interpreter_cites_only_shown_perceptions_within_budget(self):
        from .interpret import to_events

        state = replay(MindLog.parse(raw("mira-mind.json")))
        seen = {"percept:900": {"kind": "speech", "tick": 60, "text": 'Renn said: "Sorry."'}}
        reply = {"claims": [{"id": "k:renn-sorry", "predicate": "core:asserted",
                             "roles": {"speaker": "c:renn", "content": "k:thicket-safe"}}],
                 "stances": [{"id": "s:x", "claim": "k:renn-sorry", "credence": 90,
                              "cites": [{"ref": "percept:900", "bearing": "supports"}]}]}
        events = to_events(reply, seen, state, state.head + 1, 60, 1)
        self.assertEqual([e["op"] for e in events], ["evidence", "claim", "stance"])
        with self.assertRaisesRegex(ValueError, "not been shown"):
            to_events(reply, {}, state, state.head + 1, 60)
        with self.assertRaisesRegex(ValueError, "at most 0"):
            to_events(reply, seen, state, state.head + 1, 60, 0)

    def test_unknown_fields_are_rejected(self):
        log = raw("mira-mind.json")
        event(log, "c:renn")["kind"] = "person"
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            MindLog.parse(log)


if __name__ == "__main__":
    unittest.main()
