#!/usr/bin/env python3
"""Prove paid-wrapper refusal and process cleanup with inert children only."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
WRAPPER = Path(__file__).with_name('real_models.py')


def wait_for(path, process=None):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text())
        if process and process.poll() is not None:
            raise RuntimeError('wrapper exited before fixture was ready')
        time.sleep(0.05)
    raise RuntimeError('missing fixture evidence: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    if not args.run.startswith('minds-duel-') or not all(c.isalnum() or c == '-' for c in args.run):
        parser.error('run must start with minds-duel- and contain letters, numbers or hyphens')
    directory = ROOT / '.local/living/verify' / args.run
    directory.mkdir(parents=True, exist_ok=False)
    refusal = subprocess.run([sys.executable, str(WRAPPER), '--run', args.run + '-guard'], capture_output=True, text=True)
    (directory / 'guard.log').write_text(refusal.stderr)
    assert refusal.returncode == 2 and '--allow-live are required' in refusal.stderr
    assert not (directory.with_name(args.run + '-guard')).exists()
    records = []
    for scenario in ('exit', 'driver-killed', 'hang', 'wrapper-killed', 'wrapper-term'):
        name = args.run + '-' + scenario
        folder = directory.with_name(name)
        with (directory / (scenario + '.log')).open('w') as stream:
            process = subprocess.Popen([sys.executable, str(WRAPPER), '--run', name, '--dry-run',
                '--dry-scenario', 'hang' if scenario.startswith('wrapper-') else scenario], stdout=stream, stderr=subprocess.STDOUT)
            try:
                wait_for(folder / 'dry-child.json', process)
                if scenario.startswith('wrapper-'):
                    process.send_signal(signal.SIGKILL if scenario == 'wrapper-killed' else signal.SIGTERM)
                process.wait(timeout=15)
                record = wait_for(folder / 'duel-cleanup.json')
                assert record['group_gone']
                try:
                    os.killpg(record['pgid'], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise AssertionError('process group remains after cleanup')
                expected = 'wrapper exited' if scenario.startswith('wrapper-') else ('watchdog deadline' if scenario == 'hang' else 'driver exited')
                assert record['reason'] == expected
                record.update(scenario=scenario, wrapper_exit=process.returncode, evidence=str(folder))
                records.append(record)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=15)
    (directory / 'results.json').write_text(json.dumps({'guard': 'pass', 'no_model_calls': True, 'cases': records}, indent=2))
    print('guard and five termination scenarios passed; evidence kept in ' + str(directory))


if __name__ == '__main__':
    main()
