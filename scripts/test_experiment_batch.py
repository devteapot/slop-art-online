"""Deterministic coordinator contract tests; no hosts, authority or models launch."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_experiment_batch as batch
from run_living_clearing import (fresh_environment, actor_limit, pending_participants,
                                 read_participants, supplied_config_matches, validate_newcomer_controller)
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

    def invoke(self, spec=None, dry=False, fail_launch=None, evidence_failure=False, duplicate_db=False):
        spec = spec or self.spec
        manifest = self.root / 'source-manifest.json'
        write(manifest, spec)
        out = self.root / 'evidence'
        launches = []

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
                write(self.folder / 'pilot.json', dict(started_at=10, finished_at=13, phase='completed'))
                write(self.folder / 'LIVE_RESULT.json', dict(run=run, seconds=2, updates=40,
                    arenas=[dict(players=[dict(alive=True, calls=[dict(phase='completed')])])],
                    engine_errors=[], scope_violations=[]))
                self.pid = 900000 + len(launches)
                self.returncode = None
                self.terminated = False
                launches.append(self)

            def poll(self):
                if self.gate.exists():
                    self.returncode = 0
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
        error = None
        with patch.object(sys, 'argv', argv), patch.object(batch.subprocess, 'Popen', Job), \
             patch.object(batch, 'summarize', summarize), patch.object(batch.signal, 'signal'), \
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
        self.assertEqual(report['comparison'][0]['wall_seconds'], 3)
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

    def test_fresh_run_cannot_inherit_resume_or_archive(self):
        inherited = dict(BEVY_DEV_RESUME_ACTIVE='/unrelated/active.json',
                         BEVY_DEV_ARCHIVE_ONLY='1', BEVY_DEV_NEWCOMER_CONTROLLER='/unrelated/template.json',
                         BEVY_DEV_ENROLLMENT_STOP_FILE='/unrelated/stop', CARLID_NPC_API_KEY='fixture-token')
        with patch.dict(os.environ, inherited, clear=True):
            fresh = fresh_environment()
            self.assertNotIn('BEVY_DEV_RESUME_ACTIVE', fresh)
            self.assertNotIn('BEVY_DEV_ARCHIVE_ONLY', fresh)
            self.assertNotIn('BEVY_DEV_NEWCOMER_CONTROLLER', fresh)
            self.assertNotIn('BEVY_DEV_ENROLLMENT_STOP_FILE', fresh)
            self.assertEqual(fresh['CARLID_NPC_API_KEY'], 'fixture-token')
            self.assertIn('BEVY_DEV_RESUME_ACTIVE', os.environ)

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
                           ('minutes', 61), ('serial_ms', 2), ('calls_per_actor', -1)]:
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

if __name__ == '__main__':
    unittest.main(verbosity=2)
