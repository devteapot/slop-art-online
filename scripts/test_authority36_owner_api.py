"""Observer-contract regression checks with no processes or authority calls."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_authority36_probe as probe


class OwnerCheckpointContract(unittest.TestCase):
    def execute(self, mode=None, export_error=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name) / 'case'
        args = SimpleNamespace(server='http://127.0.0.1:3102', cli=Path('/fake/cli'),
                               cli_config=Path('/fake/config'), probe_binary=Path('/fake/probe'),
                               implementation=Path(temporary.name))
        if mode is not None:
            args.owner_snapshot_api = mode
        operations = []
        world = None
        raw_state = None

        def run(command, **kwargs):
            nonlocal world, raw_state
            self.assertEqual(kwargs['timeout'], 30)
            verb, item = command[3], command[5]
            operations.append((verb, item))
            if verb == 'call':
                if item == 'sim_create_participant':
                    world = dict(run=json.loads(command[6]), next_event=1,
                                 players=list(range(36)), note='snow: 雪')
                    raw_state = json.dumps(world, ensure_ascii=False, indent=2)
                if item == 'sim_owned_run_ids':
                    stdout = json.dumps([0, [world['run']] if world else []])
                elif item == 'sim_export_owned_run':
                    stdout = json.dumps([1, 'export failed'] if export_error else [0, raw_state])
                else:
                    stdout = ''
            else:
                if item == 'SELECT id FROM sim_run':
                    rows = []
                elif item.startswith('SELECT state FROM sim_run '):
                    rows = [[raw_state]]
                elif item == 'SELECT run, paused FROM sim_client_clock':
                    rows = [[world['run'], True]] if world else []
                elif item.startswith('SELECT json FROM sim_audit ') or item.startswith('SELECT actor FROM sim_client_access '):
                    rows = []
                else:
                    raise AssertionError(item)
                stdout = json.dumps([dict(rows=rows)])
            return SimpleNamespace(returncode=0, stdout=stdout)

        def popen(*_, **__):
            self.assertTrue((out / 'baseline-snapshot.json').exists())
            operations.append(('helper', 'start'))
            probe.write(out / 'helper-result.json', dict(pause_acknowledged=True,
                        window_start_process_ms=0, samples_dropped=0))
            probe.write(out / 'identities.json', ['owned-identity'])

            def wait(timeout):
                self.assertEqual(timeout, 260)
                operations.append(('helper', 'paused'))
                return 0

            return SimpleNamespace(wait=wait, poll=lambda: 0)

        with patch.object(probe.subprocess, 'run', side_effect=run), \
             patch.object(probe.subprocess, 'Popen', side_effect=popen) as helper, \
             patch.object(probe, 'validate', return_value=dict(protocol_audit_pass=True)):
            report = probe.execute_case(args, out, 'reads', 'new-database', '{}', list(range(36)))
        return report, operations, out, raw_state, helper.call_count

    def test_default_preserves_sql_inventory_and_both_exports(self):
        report, operations, out, raw, helpers = self.execute()
        self.assertTrue(report['completed_protocol'])
        self.assertEqual(helpers, 1)
        self.assertEqual(sum(item == 'SELECT id FROM sim_run' for _, item in operations), 1)
        self.assertEqual(sum(item.startswith('SELECT state FROM sim_run ') for _, item in operations), 2)
        self.assertFalse(any(item.startswith('sim_export_owned') or item == 'sim_owned_run_ids'
                             for _, item in operations))
        self.assertEqual(json.loads((out / 'final-snapshot.json').read_text())['full_world_json_bytes'], len(raw.encode()))

    def test_procedure_keeps_checkpoints_exact_bytes_and_never_uses_sim_run_sql(self):
        report, operations, out, raw, helpers = self.execute('procedure')
        self.assertTrue(report['completed_protocol'])
        self.assertEqual(helpers, 1)
        self.assertFalse(any(verb == 'sql' and 'sim_run' in item for verb, item in operations))
        exports = [i for i, item in enumerate(operations) if item == ('call', 'sim_export_owned_run')]
        self.assertEqual(len(exports), 2)
        self.assertLess(exports[0], operations.index(('helper', 'start')))
        self.assertGreater(exports[1], operations.index(('helper', 'paused')))
        self.assertLess(exports[1], operations.index(('call', 'sim_revoke_client')))
        checkpoints = json.loads((out / 'owner-snapshot-checkpoints.json').read_text())
        self.assertEqual([c['checkpoint'] for c in checkpoints], ['before-world-inventory',
                         'baseline-snapshot.json', 'final-snapshot.json', 'after-cleanup-inventory'])
        for name in ('baseline-snapshot.json', 'final-snapshot.json'):
            self.assertEqual(json.loads((out / name).read_text())['full_world_json_bytes'], len(raw.encode()))

    def test_procedure_error_fails_checkpoint_without_sql_fallback_or_helper(self):
        report, operations, _, _, helpers = self.execute('procedure', export_error=True)
        self.assertFalse(report['completed_protocol'])
        self.assertEqual(helpers, 0)
        self.assertIn('owner procedure failed', report['error'])
        self.assertFalse(any(verb == 'sql' and 'sim_run' in item for verb, item in operations))


if __name__ == '__main__':
    unittest.main()
