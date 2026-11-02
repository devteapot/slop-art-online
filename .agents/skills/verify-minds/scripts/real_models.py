#!/usr/bin/env python3
"""Opt-in paid duel with an independent watchdog; dry runs make no model calls."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('models_config', ROOT / '.agents/skills/verify-llm/scripts/models_config.py')
config_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_helper)


def admin_token():
    result = subprocess.run([str(ROOT / 'living/tools/stdb'), 'login', 'show', '--token'],
                            cwd=ROOT, capture_output=True, text=True, check=True, timeout=20)
    tokens = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', result.stdout)
    if len(tokens) != 1:
        raise RuntimeError('expected one admin JWT')
    return tokens[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live', action='store_true', help='required after authorization for this paid run')
    parser.add_argument('--run', required=True, help='shared run starting with minds-duel-')
    parser.add_argument('--models', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='inert process fixture; no models, keys or database')
    parser.add_argument('--dry-scenario', choices=('exit', 'hang', 'driver-killed'), default='exit')
    args = parser.parse_args()
    if not args.dry_run and not args.allow_live:
        parser.error('live calls are disabled; authorization and --allow-live are required')
    if not re.fullmatch(r'minds-duel-[a-zA-Z0-9-]+', args.run):
        parser.error('--run must start with minds-duel-')
    directory = ROOT / '.local/living/verify' / args.run
    report = directory / 'duel.json'
    if args.dry_run:
        directory.mkdir(parents=True, exist_ok=False)
        env = dict(os.environ)
        command = [sys.executable, str(Path(__file__).with_name('dry_driver.py')), str(directory), args.dry_scenario]
        deadline = 3
    else:
        state = json.loads((directory / 'state.json').read_text())
        db = 'verify-' + args.run
        if state.get('db') != db or not state.get('published'):
            parser.error('launch and doctor this scratch database through verify.py first')
        if report.exists() or (directory / 'duel-process.json').exists():
            parser.error('duel evidence already exists; use a fresh run')
        selected_models = config_helper.models_path(args.models)
        env = dict(os.environ, LIVING_TOKEN=admin_token(), LIVING_ROOT=str(ROOT),
                   LIVING_SERVER='http://127.0.0.1:3300', LIVING_DB=db, LIVING_SEED='world',
                   LIVING_MODELS=str(selected_models), LIVING_NEO4J='off', LIVING_NEO4J_PASSWORD='',
                   LIVING_LLM_PER_MIN='4', LIVING_LOD='0')
        (directory / 'duel-config.json').write_text(json.dumps({'models': str(selected_models),
                         'seconds': 60, 'per_min': 4, 'deadline_s': 90}, indent=2))
        command = [str(ROOT / 'living/tools/duel.py'), '--db', db, '--seconds', '60',
                   '--per-min', '4', '--per-side', '1', '--out', str(report)]
        deadline = 90
    # The detached guardian owns the group. Pipe EOF detects even SIGKILL of this wrapper.
    with (directory / 'guardian.log').open('w') as stream:
        guardian = subprocess.Popen([sys.executable, str(Path(__file__).with_name('supervise.py')),
            '--directory', str(directory), '--deadline', str(deadline), *command],
            cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=stream, stderr=subprocess.STDOUT,
            start_new_session=True)
        def interrupted(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupted)
        try:
            result = guardian.wait()
        finally:
            guardian.stdin.close()
            guardian.wait(timeout=12)
    cleanup = json.loads((directory / 'duel-cleanup.json').read_text())
    if not cleanup['group_gone']:
        raise RuntimeError('owned driver/mind group remains; inspect duel-cleanup.json')
    if report.exists():
        run = json.loads(report.read_text())['run']
        if not re.fullmatch(r'duel-[0-9]+', run):
            raise RuntimeError('unexpected duel journal name')
        journal = ROOT / '.local/living/journal' / run
        if journal.exists():
            shutil.copytree(journal, directory / 'journal')
            assert all(source.read_bytes() == (directory / 'journal' / source.name).read_bytes()
                       for source in journal.glob('*.jsonl'))
            shutil.rmtree(journal)
        log = ROOT / '.local/living' / (run + '.log')
        if log.exists():
            shutil.copy2(log, directory / 'mind.log')
            log.unlink()
    return result


if __name__ == '__main__':
    sys.exit(main())
