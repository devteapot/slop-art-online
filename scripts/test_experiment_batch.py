"""Deterministic coordinator contract tests; no hosts, authority or models launch."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_experiment_batch as batch
from run_living_clearing import (fresh_environment, actor_limit, pending_participants,
                                 read_participants, supplied_config_matches, validate_newcomer_controller,
                                 prepare_external_rpc_admission)
from experiment_artifacts import EXECUTABLES, digest, write


class ScalingChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bundle = self.root / 'implementation'
        files = {}
        for name in EXECUTABLES:
            path = self.bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'never executed fixture')
            files[name] = digest(path)
        write(self.bundle / 'implementation.json', dict(format='sao-implementation-v1', files=files))
        self.scenario = self.root / 'scenario.json'
        self.controllers = self.root / 'controllers.json'
        write(self.scenario, dict(players=[dict(id=1)]))
        write(self.controllers, [dict(actor=1, config=dict(backend=dict(model='gpt-5.6-luna')))])
        self.spec = dict(hypothesis='fixture scheduling', evaluation='retained evidence', variants=[
            dict(id=f'candidate-{i}', port=19000+i, implementation=str(self.bundle),
                 scenario=str(self.scenario), controllers=str(self.controllers)) for i in range(7)])

    def tearDown(self):
        self.tmp.cleanup()

    def test_failed_batch_never_signals_already_stopped_host_pid(self):
        folder = self.root / 'finished-pilot'
        folder.mkdir()
        write(folder / 'pilot.json', dict(phase='failed', host_pid=424242,
                                         host_stopped_before_finalization=True))
        job = SimpleNamespace(poll=lambda: 0, wait=lambda **kwargs: 0)
        with patch.object(batch.os, 'getpgid') as getpgid, patch.object(batch.os, 'killpg') as killpg:
            self.assertEqual(batch.cleanup([(job, io.StringIO(), folder, {})], True), [])
        getpgid.assert_not_called()
        killpg.assert_not_called()

    def invoke(self, spec=None, dry=False, fail_launch=None, evidence_failure=False, duplicate_db=False,
               invalid_completion=None, interrupt_after_exit=False, disk_free=None, hold_running=False,
               reserve_override=None):
        spec = spec or self.spec
        manifest = self.root / 'source-manifest.json'
        write(manifest, spec)
        out = self.root / 'evidence'
        launches = []
        signal_handlers = {}
        elapsed = [0.0]

        class Job:
            def __init__(self, command, **kwargs):
                if fail_launch is not None and len(launches) == fail_launch:
                    raise RuntimeError('fixture launch failure')
                arg = lambda name: command[command.index(name)+1]
                self.folder = Path(arg('--output'))
                self.gate = Path(arg('--start-gate'))
                # Readiness never launches models; actual engine data is not simulated.
                assert not self.gate.exists(), 'group started before all peers launched'
                self.folder.mkdir()
                run = 'fixture-' + self.folder.name
                write(self.folder / 'ready.json', dict(run=run))
                write(self.folder / 'active.json', dict(server='fixture', db='same' if duplicate_db else run, run=run))
                requested = int(arg('--minutes')) * 60
                final = self.folder / run / 'final-snapshot.json'
                final.parent.mkdir()
                write(final, dict(world=dict(run=run, timing=dict(time_ms=2000), stopped=False,
                                           players=[dict(id=1, health=100)]), events=[]))
                pilot = dict(started_at=10, finished_at=10 + requested + 3, phase='completed', run=run,
                    minutes=int(arg('--minutes')), final_snapshot=str(final), final_snapshot_sha256=digest(final),
                    final_time_ms=2000, completion=dict(protocol='sao-pilot-completion-v1', reason='duration_elapsed',
                        requested_seconds=requested, observed_wall_seconds=requested, ended_at=10 + requested))
                if invalid_completion:
                    invalid_completion(pilot, final)
                write(self.folder / 'pilot.json', pilot)
                write(self.folder / 'LIVE_RESULT.json', dict(run=run, seconds=2, updates=40,
                    arenas=[dict(players=[dict(alive=True, calls=[dict(phase='completed')])])],
                    engine_errors=[], scope_violations=[]))
                self.pid = 900000 + len(launches)
                self.returncode = None
                self.terminated = False
                launches.append(self)

            def poll(self):
                if self.returncode is None and self.gate.exists() and not hold_running:
                    self.returncode = 0
                    if interrupt_after_exit:
                        signal_handlers[batch.signal.SIGINT](batch.signal.SIGINT, None)
                return self.returncode

            def wait(self, timeout=None):
                assert self.poll() is not None
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def kill(self):
                self.returncode = -9

        def summarize(folder):
            if evidence_failure:
                raise SystemExit('fixture evidence check failed')

        argv = ['run_experiment_batch.py', str(manifest), '--output', str(out)]
        if dry:
            argv.append('--dry-run')
        if reserve_override is not None:
            argv.extend(['--disk-reserve-bytes', str(reserve_override)])
        error = None
        with patch.object(sys, 'argv', argv), patch.object(batch.subprocess, 'Popen', Job), \
             patch.object(batch, 'summarize', summarize), \
             patch.object(batch.shutil, 'disk_usage', lambda _: SimpleNamespace(
                 total=100*1024**3, free=disk_free(launches) if disk_free else 50*1024**3)), \
             patch.object(batch.time, 'monotonic', lambda: elapsed[0]), \
             patch.object(batch.time, 'sleep', lambda seconds: elapsed.__setitem__(0, elapsed[0]+seconds)), \
             patch.object(batch.signal, 'signal', lambda sig, handler: signal_handlers.update({sig: handler})), \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                batch.main()
            except (Exception, SystemExit) as exc:
                error = exc
        return out, launches, error

    def test_seven_simultaneous_one_gate(self):
        out, jobs, error = self.invoke()
        self.assertIsNone(error)
        self.assertEqual(len(jobs), 7)
        self.assertEqual(len({j.gate for j in jobs}), 1)
        report = json.loads((out / 'batch.json').read_text())
        self.assertEqual(report['phase'], 'completed')
        self.assertEqual(len(report['comparison']), 7)
        self.assertEqual(report['comparison'][0]['wall_seconds'], 303)
        self.assertEqual(report['variants'][0]['gate_timeout_seconds'], 730)
        self.assertEqual(len({r['database'] for r in report['variants']}), 7)

    def test_explicit_concurrency_waves(self):
        spec = dict(self.spec, concurrency=3)
        out, jobs, error = self.invoke(spec)
        self.assertIsNone(error)
        self.assertEqual([j.gate.name for j in jobs], ['group-1']*3+['group-2']*3+['group-3'])
        self.assertEqual(len(json.loads((out / 'comparison.json').read_text())), 7)

    def test_dry_run_no_processes(self):
        out, jobs, error = self.invoke(dry=True)
        self.assertIsNone(error)
        self.assertEqual(jobs, [])
        self.assertEqual(json.loads((out / 'batch.json').read_text())['phase'], 'planned')
        self.assertEqual(list((out / '.gates').iterdir()), [])
        self.assertEqual(len(list((out / '.inputs').iterdir())), 7)

    def test_disk_preflight_refuses_launch_and_records_measurement(self):
        reserve = batch.DEFAULT_DISK_RESERVE_BYTES
        out, jobs, error = self.invoke(disk_free=lambda _: reserve-1)
        self.assertIsInstance(error, batch.DiskReserveError)
        self.assertEqual(jobs, [])
        report = json.loads((out / 'batch.json').read_text())
        self.assertEqual(report['phase'], 'failed')
        self.assertEqual(report['failure_code'], 'disk_reserve_exhausted')
        self.assertEqual(report['disk_space']['reserve_bytes'], 3*1024**3)
        self.assertEqual(report['disk_space']['breach']['stage'], 'preflight')
        self.assertEqual(report['disk_space']['samples'][0]['free_bytes'], reserve-1)
        self.assertEqual(list((out / '.gates').iterdir()), [])

    def test_disk_drop_during_launch_stops_peer_before_common_gate(self):
        reserve = batch.DEFAULT_DISK_RESERVE_BYTES
        out, jobs, error = self.invoke(disk_free=lambda jobs: reserve-1 if jobs else reserve+1)
        self.assertIsInstance(error, batch.DiskReserveError)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0].terminated)
        self.assertFalse(jobs[0].gate.exists())
        report = json.loads((out / 'batch.json').read_text())
        self.assertEqual(report['disk_space']['breach']['stage'], 'before_launch')
        self.assertEqual(report['cleanup_errors'], [])

    def test_disk_drop_while_running_gracefully_stops_all_peers(self):
        reserve = batch.DEFAULT_DISK_RESERVE_BYTES
        def free(jobs):
            return reserve if any(j.gate.exists() for j in jobs) else reserve+1024**3
        out, jobs, error = self.invoke(hold_running=True, disk_free=free)
        self.assertIsInstance(error, batch.DiskReserveError)
        self.assertEqual(len(jobs), 7)
        self.assertTrue(all(j.terminated and j.returncode == -15 for j in jobs))
        report = json.loads((out / 'batch.json').read_text())
        self.assertEqual(report['phase'], 'failed')
        self.assertEqual(report['disk_space']['breach']['stage'], 'running')
        self.assertEqual(report['disk_space']['samples'][-1]['free_bytes'], reserve)
        self.assertEqual(report['comparison'], [])
        self.assertEqual(report['cleanup_errors'], [])

    def test_disk_reserve_override_is_retained_in_plan_and_enforced(self):
        out, jobs, error = self.invoke(disk_free=lambda _: 1024, reserve_override=2048)
        self.assertIsInstance(error, batch.DiskReserveError)
        self.assertEqual(jobs, [])
        self.assertEqual(json.loads((out / 'manifest.json').read_text())['disk_reserve_bytes'], 2048)
        self.assertEqual(json.loads((out / 'batch.json').read_text())['disk_space']['reserve_bytes'], 2048)

    def test_disk_measurements_are_periodic_and_forced_at_boundaries(self):
        out = self.root / 'guard'
        out.mkdir()
        report = {}
        guard = batch.DiskReserveGuard(out, report, 100)
        with patch.object(batch.time, 'monotonic', side_effect=[0, .5, 1, 1.1]), \
             patch.object(batch.shutil, 'disk_usage', return_value=SimpleNamespace(total=1000, free=900)) as usage:
            guard.check('preflight', force=True)
            guard.check('running')
            guard.check('running')
            guard.check('before_launch', force=True)
        self.assertEqual(usage.call_count, 3)
        self.assertEqual([s['stage'] for s in report['disk_space']['samples']],
                         ['preflight', 'running', 'before_launch'])

    def test_fresh_run_cannot_inherit_resume_or_archive(self):
        inherited = dict(BEVY_DEV_RESUME_ACTIVE='/unrelated/active.json',
                         BEVY_DEV_ARCHIVE_ONLY='1', BEVY_DEV_NEWCOMER_CONTROLLER='/unrelated/template.json',
                         BEVY_DEV_ENROLLMENT_STOP_FILE='/unrelated/stop', CARLID_NPC_API_KEY='fixture-token',
                         SAO_EXTERNAL_RPC_ADMISSION_DIR='/unrelated/slots', SAO_EXTERNAL_RPC_CONCURRENCY='8')
        with patch.dict(os.environ, inherited, clear=True):
            fresh = fresh_environment()
            self.assertNotIn('BEVY_DEV_RESUME_ACTIVE', fresh)
            self.assertNotIn('BEVY_DEV_ARCHIVE_ONLY', fresh)
            self.assertNotIn('BEVY_DEV_NEWCOMER_CONTROLLER', fresh)
            self.assertNotIn('BEVY_DEV_ENROLLMENT_STOP_FILE', fresh)
            self.assertNotIn('SAO_EXTERNAL_RPC_ADMISSION_DIR', fresh)
            self.assertNotIn('SAO_EXTERNAL_RPC_CONCURRENCY', fresh)
            self.assertEqual(fresh['CARLID_NPC_API_KEY'], 'fixture-token')
            self.assertIn('BEVY_DEV_RESUME_ACTIVE', os.environ)

    def test_owner_snapshot_contract_is_explicit_and_preserved(self):
        self.spec['variants'][0]['owner_snapshot_api'] = 'procedure'
        spec, resolved = batch.resolve_spec(self.spec)
        plan = batch.prepare(spec, resolved, self.root / 'owner-procedure')
        command = plan[0]['command']
        self.assertEqual(command[command.index('--owner-snapshot-api') + 1], 'procedure')
        self.assertNotIn('--owner-snapshot-api', plan[1]['command'])
        self.spec['variants'][0]['owner_snapshot_api'] = 'automatic-fallback'
        with self.assertRaisesRegex(ValueError, 'owner_snapshot_api'):
            batch.resolve_spec(self.spec)

    def test_persistent_transport_and_stopped_host_finalization_are_explicit(self):
        self.spec['variants'][0].update(external_mcp_mode='persistent', finalization_mode='stopped_host')
        spec, resolved = batch.resolve_spec(self.spec)
        plan = batch.prepare(spec, resolved, self.root / 'persistent-transport')
        command = plan[0]['command']
        self.assertEqual(command[command.index('--external-mcp-mode') + 1], 'persistent')
        self.assertEqual(command[command.index('--finalization-mode') + 1], 'stopped_host')
        self.assertNotIn('--external-mcp-mode', plan[1]['command'])
        self.assertNotIn('--finalization-mode', plan[1]['command'])
        for key in ('external_mcp_mode', 'finalization_mode'):
            invalid = copy.deepcopy(self.spec)
            invalid['variants'][0][key] = 'automatic-fallback'
            with self.assertRaisesRegex(ValueError, key):
                batch.resolve_spec(invalid)
        invalid = copy.deepcopy(self.spec)
        invalid['variants'][0]['newcomer_controller'] = 'unused-before-validation'
        with self.assertRaisesRegex(ValueError, 'fixed population'):
            batch.resolve_spec(invalid)

    def test_external_rpc_admission_is_explicit_and_rejects_invalid_modes_and_counts(self):
        self.spec['variants'][0].update(external_mcp_mode='persistent', external_rpc_concurrency=8)
        spec, resolved = batch.resolve_spec(self.spec)
        plan = batch.prepare(spec, resolved, self.root / 'admitted-transport')
        command = plan[0]['command']
        self.assertEqual(command[command.index('--external-rpc-concurrency') + 1], '8')
        self.assertNotIn('--external-rpc-concurrency', plan[1]['command'])
        for count in (True, -1, 37, 1.5, '8'):
            invalid = copy.deepcopy(self.spec)
            invalid['variants'][0]['external_rpc_concurrency'] = count
            with self.subTest(count=count), self.assertRaises(ValueError):
                batch.resolve_spec(invalid)
        invalid = copy.deepcopy(self.spec)
        invalid['variants'][0]['external_mcp_mode'] = 'per_call'
        with self.assertRaisesRegex(ValueError, 'requires persistent'):
            batch.resolve_spec(invalid)

    def test_admission_slots_are_new_private_distinct_files_and_never_reused(self):
        self.assertEqual(prepare_external_rpc_admission(self.root, 0, 'per_call'), ({}, None))
        directory = self.root / 'external-rpc-admission'
        self.assertFalse(directory.exists())
        env, report = prepare_external_rpc_admission(self.root, 8, 'persistent')
        self.assertEqual(env, dict(SAO_EXTERNAL_RPC_ADMISSION_DIR=str(directory), SAO_EXTERNAL_RPC_CONCURRENCY='8'))
        self.assertEqual(report['concurrency'], 8)
        slots = sorted(directory.iterdir())
        self.assertEqual([p.name for p in slots], [f'slot-{i:02}.lock' for i in range(8)])
        self.assertEqual(len({p.stat().st_ino for p in slots}), 8)
        self.assertTrue(all(p.stat().st_size == 0 and p.stat().st_mode & 0o777 == 0o600 for p in slots))
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        with self.assertRaises(FileExistsError):
            prepare_external_rpc_admission(self.root, 8, 'persistent')
        with self.assertRaisesRegex(ValueError, 'requires persistent'):
            prepare_external_rpc_admission(self.root, 8, 'per_call')

    def test_newcomer_template_is_explicit_frozen_input(self):
        path = self.root / 'newcomer.json'
        template = dict(role='external', config=dict(backend=dict(model='gpt-5.6-luna', reasoning_effort='medium')))
        write(path, template)
        self.spec['variants'][0]['newcomer_controller'] = str(path)
        spec, resolved = batch.resolve_spec(self.spec)
        write(path, dict(role='builtin', config=template['config']))
        plan = batch.prepare(spec, resolved, self.root / 'frozen-newcomer')
        frozen = self.root / 'frozen-newcomer/.inputs/candidate-0/newcomer_controller.json'
        self.assertEqual(json.loads(frozen.read_text()), template)
        self.assertEqual(plan[0]['inputs']['newcomer_controller'], digest(frozen))
        self.assertIn('--newcomer-controller', plan[0]['command'])
        self.assertNotIn('--newcomer-controller', plan[1]['command'])

    def test_newcomer_bounds_and_template_reject_implicit_configuration(self):
        scenario = dict(players=[dict(id=1), dict(id=2)])
        self.assertEqual(actor_limit(scenario), 2)
        self.assertEqual(actor_limit(scenario, True), 64)
        self.assertEqual(actor_limit(dict(scenario, lifecycle=dict(max_total=12)), True), 12)
        for maximum in [True, 0, 1, 257]:
            with self.assertRaises(ValueError):
                actor_limit(dict(scenario, lifecycle=dict(max_total=maximum)), True)
        for template in [dict(role='invented', config={}), dict(role='builtin', config={}, tree={}),
                         dict(role='builtin', config=dict(backend=dict(model='unconfigured-model')))]:
            with self.assertRaises(ValueError):
                validate_newcomer_controller(template)
        self.assertTrue(supplied_config_matches(dict(backend=dict(model='gpt-5.6-luna')),
                                                dict(backend=dict(model='gpt-5.6-luna'), retry_backoff_ms=500)))
        self.assertFalse(supplied_config_matches(dict(backend=dict(model='gpt-5.6-luna')),
                                                 dict(backend=dict(model='another-model'))))

    def test_dynamic_admission_preserves_identity_and_is_disabled_without_template(self):
        initial = dict(actor=1, role='builtin', identity='a' * 64, session_file='/fixture/1.json')
        child = dict(actor=7, role='external', identity='b' * 64, session_file='/fixture/7.json', enrollment='newcomer')
        known = {1: initial}
        with self.assertRaises(RuntimeError):
            pending_participants(known, [initial, child], [1], None)
        template = dict(role='external')
        self.assertEqual(pending_participants(known, [initial, child], [1], template), [child])
        known[7] = child
        self.assertEqual(pending_participants(known, [initial, child], [1], template), [])
        with self.assertRaises(RuntimeError):
            pending_participants(known, [initial], [1], template)
        with self.assertRaises(RuntimeError):
            pending_participants(known, [initial, dict(child, identity='c' * 64)], [1], template)
        path = self.root / 'participants.json'
        write(path, [initial, child])
        self.assertEqual(read_participants(path, 8), [initial, child])
        with self.assertRaises(ValueError):
            read_participants(path, 1)
        write(path, [initial, dict(child, identity=initial['identity'])])
        with self.assertRaises(ValueError):
            read_participants(path, 8)

    def test_frozen_input_read_once(self):
        spec, resolved = batch.resolve_spec(self.spec)
        write(self.scenario, dict(players=[dict(id=77)]))
        plan = batch.prepare(spec, resolved, self.root / 'frozen')
        frozen = self.root / 'frozen/.inputs/candidate-0/scenario.json'
        self.assertEqual(json.loads(frozen.read_text())['players'][0]['id'], 1)
        self.assertEqual(digest(frozen), plan[0]['inputs']['scenario'])

    def test_invalid_specs_reject_before_launch(self):
        cases = []
        for key, value in [('concurrency', 0), ('concurrency', True), ('concurrency', 8),
                           ('minutes', 61), ('serial_ms', 2), ('calls_per_actor', -1),
                           ('disk_reserve_bytes', 0), ('disk_reserve_bytes', True),
                           ('disk_reserve_bytes', -1), ('disk_reserve_bytes', 3.5)]:
            cases.append(dict(self.spec, **{key: value}))
        for key, value in [('id', '../escape'), ('port', True), ('port', 65536),
                           ('id', 'candidate-1'), ('port', 19001), ('recovery', 'false')]:
            spec = copy.deepcopy(self.spec)
            spec['variants'][0][key] = value
            cases.append(spec)
        for spec in cases:
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    batch.resolve_spec(spec)

    def test_launch_failure_stops_started_peers_no_gate(self):
        out, jobs, error = self.invoke(fail_launch=2)
        self.assertIsInstance(error, RuntimeError)
        self.assertTrue(all(j.terminated for j in jobs))
        self.assertFalse(any(j.gate.exists() for j in jobs))
        self.assertEqual(json.loads((out / 'batch.json').read_text())['phase'], 'failed')

    def test_duplicate_authority_rejected_before_gate(self):
        out, jobs, error = self.invoke(duplicate_db=True)
        self.assertIn('distinct authority databases', str(error))
        self.assertTrue(all(j.terminated for j in jobs))
        self.assertFalse(any(j.gate.exists() for j in jobs))

    def test_evidence_system_exit_records_failure(self):
        out, jobs, error = self.invoke(evidence_failure=True)
        self.assertIsInstance(error, SystemExit)
        self.assertEqual(json.loads((out / 'batch.json').read_text())['phase'], 'failed')

    def test_short_zero_exit_pilot_rejected_even_when_cleanup_finishes_after_deadline(self):
        def shorten(pilot, _):
            pilot['completion']['observed_wall_seconds'] = 200
        out, _, error = self.invoke(invalid_completion=shorten)
        self.assertIn('minimum active duration', str(error))
        report = json.loads((out / 'batch.json').read_text())
        self.assertEqual(report['phase'], 'failed')
        self.assertEqual(report['variants'][0]['phase'], 'failed')
        self.assertEqual(report['comparison'], [])

    def test_interrupted_completed_claim_rejected(self):
        def interrupt(pilot, _):
            pilot['interruption'] = dict(signal='SIGINT')
        out, _, error = self.invoke(invalid_completion=interrupt)
        self.assertIn('interruption', str(error))
        self.assertEqual(json.loads((out / 'batch.json').read_text())['phase'], 'failed')

    def test_unproven_terminal_claim_rejected(self):
        def terminal(pilot, _):
            pilot['completion'].update(reason='all_actors_dead', observed_wall_seconds=20)
        _, _, error = self.invoke(invalid_completion=terminal)
        self.assertIn('population termination', str(error))

    def test_actual_early_terminal_authority_is_accepted(self):
        def terminal(pilot, final):
            pilot['completion'].update(reason='all_actors_dead', observed_wall_seconds=20)
            snapshot = json.loads(final.read_text())
            snapshot['world']['players'][0]['health'] = 0
            write(final, snapshot)
            pilot['final_snapshot_sha256'] = digest(final)
        out, _, error = self.invoke(invalid_completion=terminal)
        self.assertIsNone(error)
        self.assertEqual(json.loads((out / 'batch.json').read_text())['phase'], 'completed')

    def test_final_authority_provenance_mismatch_rejected(self):
        def altered(pilot, final):
            snapshot = json.loads(final.read_text())
            snapshot['world']['timing']['time_ms'] += 1
            write(final, snapshot)
        _, _, error = self.invoke(invalid_completion=altered)
        self.assertIn('snapshot provenance', str(error))

    def test_batch_signal_at_last_process_exit_cannot_report_completion(self):
        out, _, error = self.invoke(interrupt_after_exit=True)
        self.assertIn('cancelled', str(error))
        report = json.loads((out / 'batch.json').read_text())
        self.assertEqual(report['phase'], 'failed')
        self.assertEqual(report['interruption']['signal'], 'SIGINT')
        self.assertEqual(report['comparison'], [])

if __name__ == '__main__':
    unittest.main(verbosity=2)
