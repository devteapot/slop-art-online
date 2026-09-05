"""Supervisor protocol fixtures; fake authority/processes never invoke a model."""
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

import run_living_clearing as living


class LivingEnrollmentChecks(unittest.TestCase):
    def exercise(self, acknowledge=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        out = root / 'evidence'
        run = out / 'fixture-run'
        config = dict(backend=dict(model='gpt-5.6-luna', reasoning_effort='medium'))
        for relative in ['target/debug/sao-dev-client', 'target/debug/sao-agent-mcp',
                         'target/debug/examples/participant_live_agent',
                         'target/wasm32-unknown-unknown/release/server_module.wasm', 'Cargo.lock']:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'inert fixture; never executed')
        path = root / 'configs/reasoning/codex-carlid-luna-streaming-proof.json'
        path.parent.mkdir(parents=True)
        living.write(path, config)
        players = [dict(id=actor, name=f'Actor {actor}', health=100, hunger=20, energy=80, food=2,
                        position=84, caution=50, beliefs=[], relationships={}) for actor in [1, 2]]
        scenario = dict(players=copy.deepcopy(players), arenas=[], lifecycle=dict(max_total=4))
        living.write(root / 'scenario.json', scenario)
        living.write(root / 'controllers.json', [dict(actor=1, role='builtin', config=config),
                                                dict(actor=2, role='external', config=config)])
        living.write(root / 'newcomer.json', dict(role='external', config=config))
        world = dict(tick=1, timing=dict(time_ms=2500, updates=50), stopped=False,
                     players=players, sites=[])
        descriptors, dispatched, revoked, protocol = [], [], [], []
        clock = [0]
        waits = [0]

        def admit(actor, newcomer=False):
            if actor not in {p['id'] for p in world['players']}:
                child = copy.deepcopy(players[0])
                child.update(id=actor, name=f'Actor {actor}', food=0)
                world['players'].append(child)
            effective = run / f'actor-{actor}-config.json'
            living.write(effective, dict(config, retry_backoff_ms=500))
            descriptors.append(dict(actor=actor, identity=f'{actor:064x}', role='builtin' if actor == 1 else 'external',
                                    session_file=str(root / f'private-{actor}.json'), config_file=str(effective),
                                    enrollment='newcomer' if newcomer else 'initial'))
            living.write(run / 'participants.json', descriptors)
            living.write(run / 'snapshot.json', dict(world=world, events=[]))

        class Host:
            pid = 900000
            def __init__(self, *args, **kwargs):
                run.mkdir()
                admit(1)
                admit(2)
                living.write(out / 'active.json', dict(run='fixture-run', db='fixture-db', server='fixture-server',
                             enrollment_protocol='sao-enrollment-v1', newcomer_enrollment=True))
            def poll(self):
                return None

        class Stop:
            flag = False
            def is_set(self):
                return self.flag
            def set(self):
                self.flag = True
            def wait(self, seconds=0):
                if self.flag:
                    return True
                waits[0] += 1
                if waits[0] == 1:
                    admit(3, True)
                    clock[0] += 2
                else:
                    clock[0] += 100
                return False

        class Future:
            def __init__(self, value=None):
                self.value = value
            def done(self):
                return True
            def result(self):
                return self.value

        class Pool:
            def __init__(self, max_workers):
                self.maximum = max_workers
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def submit(self, function, *args):
                if function.__name__ == 'worker':
                    dispatched.append(args[0])
                    return Future()
                return Future(function(*args))

        def control(command, **kwargs):
            if 'sim_operator_pause' in command:
                self.assertTrue((out / 'stop-enrollment').exists())
                protocol.append('stop_requested')
                # Represents an in-flight enrollment whose descriptor is published
                # after the main loop stopped, before the host acknowledges drain.
                admit(4, True)
                if acknowledge:
                    living.write(out / 'enrollment-stopped.json', dict(protocol='sao-enrollment-v1', phase='stopped', enrolled=4))
                    protocol.append('acknowledged')
            elif 'sim_revoke_client' in command:
                self.assertIn('acknowledged', protocol)
                index = command.index('sim_revoke_client')
                revoked.append(int(json.loads(command[index + 1]), 16))
            if 'sql' in command:
                query = command[command.index('sql') + 2]
                rows = [[json.dumps(world)]] if 'SELECT state' in query else []
                return SimpleNamespace(returncode=0, stdout=json.dumps([dict(rows=rows)]))
            return SimpleNamespace(returncode=0, stdout='')

        def sleep(seconds):
            clock[0] += seconds

        argv = ['run_living_clearing.py', '--output', str(out), '--scenario', str(root / 'scenario.json'),
                '--controllers', str(root / 'controllers.json'), '--newcomer-controller', str(root / 'newcomer.json'),
                '--minutes', '1', '--calls-per-actor', '1', '--port', '0']
        original_cwd = Path.cwd()
        self.addCleanup(os.chdir, original_cwd)
        error = None
        with patch.object(living, 'ROOT', root), patch.object(sys, 'argv', argv), \
             patch.dict(os.environ, {'CARLID_NPC_API_KEY': 'fixture-token'}), \
             patch.object(living.subprocess, 'Popen', Host), patch.object(living.subprocess, 'run', control), \
             patch.object(living.threading, 'Event', Stop), patch.object(living.concurrent.futures, 'ThreadPoolExecutor', Pool), \
             patch.object(living.signal, 'signal'), patch.object(living.time, 'monotonic', lambda: clock[0]), \
             patch.object(living.time, 'sleep', sleep), contextlib.redirect_stdout(io.StringIO()):
            try:
                living.main()
            except SystemExit as failure:
                error = failure
        return json.loads((out / 'pilot.json').read_text()), dispatched, revoked, error

    def test_late_enrollment_is_revoked_after_ack_but_not_dispatched(self):
        report, dispatched, revoked, error = self.exercise()
        self.assertIsNone(error)
        self.assertEqual(report['phase'], 'completed')
        self.assertEqual(report['maximum_actors'], 4)
        self.assertEqual(report['max_model_calls'], 4)
        self.assertEqual(dispatched, [2, 3])
        self.assertEqual(sorted(revoked), [1, 2, 3, 4])
        self.assertEqual(report['enrolled_actors'], [1, 2, 3, 4])
        self.assertEqual(report['enrollment_stopped']['phase'], 'stopped')

    def test_missing_acknowledgement_fails_with_bounded_cleanup(self):
        report, dispatched, revoked, error = self.exercise(acknowledge=False)
        self.assertIsNotNone(error)
        self.assertEqual(report['phase'], 'failed')
        self.assertIn('did not acknowledge', report['pause_error'])
        self.assertEqual(dispatched, [2, 3])
        self.assertEqual(revoked, [])


if __name__ == '__main__':
    unittest.main()
