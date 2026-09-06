import json
import unittest
from unittest.mock import Mock

import owner_snapshot as owner


class OwnerSnapshotTests(unittest.TestCase):
    def test_exact_export_bytes_unicode_escapes_and_event_cutoff(self):
        body = '{ "run":"r", "next_event":4, "text":"quote\\\" slash\\\\ newline\\n λ", "n":1.0 }'
        wire = json.dumps([0, body]) + '\n'
        self.assertEqual(owner.parse_export_json(wire, 'r'), body)
        self.assertEqual(owner.parse_export(wire, 'r'), json.loads(body))
        self.assertEqual(owner.parse_export(wire)['run'], 'r')

    def test_empty_and_sorted_inventory(self):
        self.assertEqual(owner.parse_inventory('[0,[]]'), [])
        self.assertEqual(owner.parse_inventory('[0,["a","b"]]'), ['a', 'b'])
        for payload in ([1], [''], ['a', 'a'], ['b', 'a'], 'a', {}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                owner.parse_inventory(json.dumps([0, payload]))

    def test_application_errors_are_rejected_and_details_redacted(self):
        with self.assertRaisesRegex(ValueError, '^run unavailable$'):
            owner.parse_export('[1,"run unavailable"]', 'r')
        with self.assertRaisesRegex(ValueError, '^owner procedure failed$'):
            owner.parse_inventory('[1,"private source content"]')

    def test_malformed_wire_fails_closed(self):
        wires = ('', 'null', '[0]', '[0,"x",1]', '[2,"x"]', '[true,"x"]',
                 '[0.0,"x"]', '[-1,"x"]', '[256,"x"]', '[1,null]',
                 '{"ok":"x"}', '[{"rows":[["x"]]}]', '[0,{}]',
                 '[0,"x"] trailing', 'notice\n[0,"x"]', '[NaN,"x"]')
        for wire in wires:
            with self.subTest(wire=wire), self.assertRaises(ValueError):
                owner.parse_export(wire, 'r')

    def test_world_identity_cursor_and_json_validation(self):
        bodies = ('null', '[]', '{}', '{"run":"wrong","next_event":1}',
                  '{"run":"r","next_event":0}', '{"run":"r","next_event":true}',
                  '{"run":"r","next_event":1.0}', '{"run":"r","next_event":18446744073709551616}',
                  '{"run":"r","next_event":1,"value":NaN}',
                  '{"run":"r","run":"r","next_event":1}',
                  '{"run":"r","next_event":1} trailing')
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(ValueError):
                owner.parse_export(json.dumps([0, body]), 'r')

    def test_wrappers_make_exactly_one_explicit_call_without_fallback_or_retry(self):
        call = Mock(return_value='[0,["r"]]')
        self.assertEqual(owner.inventory(call), ['r'])
        call.assert_called_once_with('sim_owned_run_ids')
        body = '{"run":"r","next_event":1}'
        for wrapper, expected in ((owner.export_json, body), (owner.export_world, json.loads(body))):
            call = Mock(return_value=json.dumps([0, body]))
            self.assertEqual(wrapper(call, 'r'), expected)
            call.assert_called_once_with('sim_export_owned_run', 'r')
        call = Mock(return_value='[1,"run unavailable"]')
        with self.assertRaises(ValueError):
            owner.export_world(call, 'r')
        call.assert_called_once_with('sim_export_owned_run', 'r')
        failure = TimeoutError('original transport deadline')
        call = Mock(side_effect=failure)
        with self.assertRaises(TimeoutError) as caught:
            owner.export_json(call, 'r')
        self.assertIs(caught.exception, failure)
        call.assert_called_once_with('sim_export_owned_run', 'r')


if __name__ == '__main__':
    unittest.main()
