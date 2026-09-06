"""Mocked runner safety/cleanup checks; no CLI or HTTP authority calls."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import run_owner_export_regression as runner


class OwnerExportRunnerTests(unittest.TestCase):
    def test_preparation_loads_actual_four_actor_law_fixture_without_reading_tokens(self):
        source = Path(__file__).resolve().parents[1] / 'scenarios/law-local-borders.json'
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            implementation = base / 'implementation'
            (implementation / 'scenarios').mkdir(parents=True)
            (implementation / 'scenarios/law-local-borders.json').symlink_to(source)
            (implementation / 'implementation.json').write_text('{}')
            active = base / 'active.json'
            active.write_text(json.dumps(dict(server='http://127.0.0.1:3102', db='fresh-fixture')))
            identities = base / 'identities.json'
            identities.write_text(json.dumps([format(index, '064x') for index in range(1, 6)]))
            sessions = base / 'private'; sessions.mkdir()
            for suffix in ('actor-1', 'actor-2', 'actor-3', 'observer'):
                # Deliberately not valid session JSON: preparation may check
                # presence, but must not load credentials or contact authority.
                (sessions / f'sim-retained-{suffix}.json').write_text('private input not read')
            cli = base / 'cli'; cli.write_text('inert fixture')
            config = base / 'owner.toml'; config.write_text('inert fixture')
            args = SimpleNamespace(active=active, implementation=implementation, output=base/'output',
                                   cli=cli, cli_config=config, fixture_identities=identities,
                                   fixture_session_dir=sessions, fixture_run='sim-retained')
            with patch.object(runner.subprocess, 'run') as launch, patch.object(runner.urllib.request, 'build_opener') as http:
                prepared = runner.validate_inputs(args)
            launch.assert_not_called(); http.assert_not_called()
            self.assertEqual([player['id'] for player in prepared['scenario']['players']], [1, 2, 3, 4])
            self.assertEqual(prepared['scenario']['starting_behaviors'], {})
            self.assertEqual(prepared['scenario']['knowledge'], {})
            self.assertTrue(all(player['controller'] == 'human' for player in prepared['scenario']['players']))
            self.assertEqual(prepared['scenario_source'].resolve(), source)

    def test_denial_requires_integer_tag_and_exact_unavailable(self):
        transport = SimpleNamespace(call=lambda *args: '[1,"run unavailable"]')
        runner.Transport.denied(transport, 'observer', 'foreign')
        for value in ('[true,"run unavailable"]', '[0,"run unavailable"]', '[1,"other"]', '{"err":"run unavailable"}'):
            transport.call = lambda *args, value=value: value
            with self.subTest(value=value), self.assertRaises(runner.FixtureFailure):
                runner.Transport.denied(transport, 'observer', 'foreign')

    def test_cleanup_reconciles_timed_out_grants_and_never_revokes_foreign_run(self):
        owned, foreign = '1' * 64, '2' * 64
        remaining = [[owned, 'run-a', False, 2], [foreign, 'another-run', True, 0]]
        revoked = []
        def rows(query):
            return [] if query == runner.TABLE_QUERIES['clocks'] else list(remaining)
        def call(role, name, identity):
            revoked.append((role, name, identity))
            remaining[:] = [row for row in remaining if row[0] != identity]
        report = dict(cleanup_errors=[])
        runner.cleanup(SimpleNamespace(rows=rows, call=call), 'run-a', [owned, foreign], report)
        self.assertEqual(revoked, [('owner_a', 'sim_revoke_client', owned)])
        self.assertFalse(report['cleanup_verified'])
        self.assertEqual(report['remaining_grants'], 1)
        self.assertIn('not revoked', report['cleanup_errors'][0])

    def test_cleanup_refuses_blind_revoke_when_inspection_fails(self):
        transport = SimpleNamespace(rows=Mock(side_effect=RuntimeError('unavailable')), call=Mock())
        report = dict(cleanup_errors=[])
        runner.cleanup(transport, 'run-a', ['1' * 64], report)
        transport.call.assert_not_called()
        self.assertFalse(report['cleanup_verified'])

    def test_successful_cleanup_verifies_zero_clocks_and_grants(self):
        identity = '1' * 64
        remaining = [[identity, 'run-a', False, 2]]
        def rows(query):
            return [] if query == runner.TABLE_QUERIES['clocks'] else list(remaining)
        def call(*_):
            remaining.clear()
        report = dict(cleanup_errors=[])
        runner.cleanup(SimpleNamespace(rows=rows, call=call), 'run-a', [identity], report)
        self.assertTrue(report['cleanup_verified'])
        self.assertEqual(report['remaining_grants'], 0)

    def test_http_targets_new_database_without_recording_token(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory); (out / 'wire').mkdir()
            credential = out / 'private-input.json'
            token = 'inert-test-token-not-a-real-credential'
            credential.write_text(json.dumps(dict(server='http://127.0.0.1:3102', database='old-db', token=token)))
            transport = runner.Transport(SimpleNamespace(), dict(paths={'owner_b': credential}, server='http://127.0.0.1:3102', database='new-db'), out)
            response = Mock(status=200)
            response.read.return_value = b'[0,[]]'
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            transport.http = SimpleNamespace(open=Mock(return_value=response))
            self.assertEqual(transport.call('owner_b', runner.INVENTORY_PROCEDURE), '[0,[]]')
            request = transport.http.open.call_args.args[0]
            self.assertIn('/new-db/call/', request.full_url)
            self.assertEqual(request.get_header('Authorization'), 'Bearer ' + token)
            self.assertEqual(transport.http.open.call_args.kwargs['timeout'], 30)
            self.assertNotIn(token, (out / 'commands.jsonl').read_text())
            self.assertNotIn(token, next((out / 'wire').iterdir()).read_text())
            with self.assertRaises(runner.FixtureFailure):
                transport.record('owner_b', runner.EXPORT_PROCEDURE, [], 0, raw=token, status=200)
            self.assertEqual(len(list((out / 'wire').iterdir())), 1)

    def test_identity_decoder_and_redirects_fail_closed(self):
        value = 'a' * 64
        self.assertEqual(runner.identity_text(['0x' + value]), value)
        self.assertEqual(runner.identity_text({'__identity__': value}), value)
        for invalid in (12, {}, ['x', 'y'], 'not-identity'):
            with self.assertRaises(ValueError):
                runner.identity_text(invalid)
        self.assertIsNone(runner.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://elsewhere'))


if __name__ == '__main__':
    unittest.main()
