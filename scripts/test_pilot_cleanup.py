"""Final-capture contract fixtures; no authority process or model is used."""
import copy
import json
import unittest

from pilot_cleanup import finalize_fixed_run


class Authority:
    def __init__(self):
        self.run = "fixture-run"
        self.grants = {"a" * 64: False, "b" * 64: False, "c" * 64: True}
        self.other_grant = "d" * 64
        self.events = [dict(id=1, run=self.run), dict(id=2, run=self.run)]
        self.operations = []
        self.records = []
        self.paused = False
        self.stopped = False
        self.exports = 0
        self.bad_rows = None
        self.fail_revoke = None

    def host(self):
        self.operations.append(("host_stop",))
        self.stopped = True
        return dict(stopped=True, exit_code=-15)

    def call(self, name, value):
        self.operations.append((name, value))
        if name == "sim_operator_pause":
            assert self.stopped
            self.paused = True
        elif name == "sim_revoke_client":
            assert self.stopped and self.paused and value != self.other_grant
            if value == self.fail_revoke:
                raise RuntimeError("fixture revoke failure")
            del self.grants[value]
        else:
            raise AssertionError(name)

    def control(self, verb, query, *args):
        assert verb == "sql" and f"WHERE run = '{self.run}'" in query
        if "sim_client_clock" in query:
            rows = [[self.run, self.paused]]
        elif "sim_client_access" in query:
            rows = self.bad_rows if self.bad_rows is not None else [
                [[identity], self.run, observer, 0 if observer else index + 1]
                for index, (identity, observer) in enumerate(self.grants.items())]
        elif "sim_audit" in query:
            assert "event_id < 3" in query
            rows = [[json.dumps(event)] for event in reversed(self.events)]
        else:
            raise AssertionError(query)
        return json.dumps([dict(rows=rows)])

    def state(self):
        assert self.stopped and self.paused and not self.grants
        self.exports += 1
        return dict(run=self.run, next_event=3, tick=42)

    def finalize(self, run=None):
        return finalize_fixed_run(run or self.run, stop_host=self.host, control=self.control,
                                  call=self.call, state=self.state,
                                  record=lambda proof: self.records.append(copy.deepcopy(proof)))


class FinalizationChecks(unittest.TestCase):
    def test_stops_producers_and_revokes_participants_and_observer_before_single_export(self):
        authority = Authority()
        world, events = authority.finalize()
        self.assertEqual(authority.operations[:2], [("host_stop",), ("sim_operator_pause", authority.run)])
        revoked = {value for name, value in authority.operations[2:] if name == "sim_revoke_client"}
        self.assertEqual(revoked, {"a" * 64, "b" * 64, "c" * 64})
        self.assertNotIn(authority.other_grant, revoked)
        self.assertEqual(authority.exports, 1)
        self.assertEqual(world["tick"], 42)
        self.assertEqual([event["id"] for event in events], [1, 2])
        self.assertEqual(authority.records[-1]["phase"], "captured")
        self.assertEqual(authority.records[-1]["grants_after"], [])

    def test_revoke_error_is_retained_without_retry_or_final_export(self):
        authority = Authority()
        authority.fail_revoke = "b" * 64
        with self.assertRaisesRegex(RuntimeError, "no retry"):
            authority.finalize()
        self.assertEqual(authority.operations.count(("sim_revoke_client", "b" * 64)), 1)
        self.assertEqual(authority.exports, 0)
        self.assertEqual(authority.records[-1]["phase"], "failed")
        self.assertEqual(len(authority.records[-1]["revoke_results"]), 3)

    def test_wrong_scope_or_duplicate_identity_never_revokes(self):
        cases = [
            [["a" * 64, "different-run", True, 0]],
            [["a" * 64, "fixture-run", True, 0], ["a" * 64, "fixture-run", True, 0]],
            [["not-an-identity", "fixture-run", True, 0]],
            [["a" * 64, "fixture-run", True, False]],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                authority = Authority()
                authority.bad_rows = rows
                with self.assertRaises(ValueError):
                    authority.finalize()
                self.assertFalse(any(operation[0] == "sim_revoke_client" for operation in authority.operations))

    def test_missing_duplicate_or_foreign_audit_event_fails_capture(self):
        for events in ([dict(id=1, run="fixture-run")],
                       [dict(id=1, run="fixture-run"), dict(id=1, run="fixture-run")],
                       [dict(id=1, run="fixture-run"), dict(id=2, run="other")]):
            with self.subTest(events=events):
                authority = Authority()
                authority.events = events
                with self.assertRaisesRegex(ValueError, "contiguous"):
                    authority.finalize()
                self.assertEqual(authority.records[-1]["phase"], "failed")

    def test_unsafe_run_identifier_fails_before_host_or_authority_action(self):
        authority = Authority()
        with self.assertRaises(ValueError):
            authority.finalize("run' OR true")
        self.assertEqual(authority.operations, [])

    def test_host_stop_failure_still_pauses_and_revokes_without_accepting_capture(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                authority = Authority()
                def failed_stop():
                    authority.operations.append(("host_stop",))
                    if raises:
                        raise RuntimeError("fixture stop failure")
                    return dict(stopped=False)
                def cleanup_call(name, value):
                    authority.operations.append((name, value))
                    if name == "sim_operator_pause":
                        authority.paused = True
                    elif name == "sim_revoke_client":
                        self.assertTrue(authority.paused)
                        del authority.grants[value]
                    else:
                        self.fail(name)
                authority.host, authority.call = failed_stop, cleanup_call
                with self.assertRaisesRegex(RuntimeError, "host stop was not confirmed"):
                    authority.finalize()
                self.assertTrue(authority.paused)
                self.assertEqual(authority.grants, {})
                self.assertEqual(authority.exports, 0)
                self.assertEqual(authority.records[-1]["phase"], "failed")
                self.assertIn("host_error", authority.records[-1])


if __name__ == "__main__":
    unittest.main()
