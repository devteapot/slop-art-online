#!/usr/bin/env python3
"""Build, launch, drive and clean up one fresh client protocol verification run."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]
HARNESS = ROOT / '.agents/skills/verify/scripts/verify.py'
SPEC = importlib.util.spec_from_file_location('verify_harness', HARNESS)
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)


def token_digest():
    path = ROOT / '.local/living/token'
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'client-[a-zA-Z0-9-]+', args.run):
        parser.error('run must be client- followed by letters, digits or hyphens')
    if V.URL != 'http://127.0.0.1:3300':
        parser.error('this skill requires http://127.0.0.1:3300')
    directory = ROOT / '.local/living/verify' / args.run
    if directory.exists():
        parser.error('use a fresh run name; earlier evidence is immutable')
    if not V.container_up():
        parser.error('the shared SpacetimeDB container must already be running')
    if V.http('/v1/ping')[0] != 200:
        parser.error('SpacetimeDB ping failed')
    directory.mkdir(parents=True)
    before_token = token_digest()
    exit_code = 1

    def command(name, argv, env=None):
        print(f'{name}: {directory / (name + ".log")}', flush=True)
        with (directory / (name + '.log')).open('w') as output:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=output,
                                    stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'{name} exited {result.returncode}; see {name}.log')

    try:
        env = dict(os.environ, CARGO_TARGET_DIR=str(ROOT / '.local/living/verify/target-client'))
        command('build', ['cargo', 'build', '--locked', '--manifest-path',
                         str(SKILL / 'scripts/probe/Cargo.toml')], env=env)
        command('launch', [str(HARNESS), 'launch', '--run', args.run])
        command('doctor', [str(HARNESS), 'doctor', '--run', args.run])
        command('player-join', [str(HARNESS), 'player', '--run', args.run, 'join', 'ClientPrimary'])
        command('drive', [str(SKILL / 'scripts/drive.py'), '--run', args.run])
        exit_code = 0
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(str(error), file=sys.stderr)
    finally:
        database = 'verify-' + args.run
        state_path = directory / 'state.json'
        try:
            command('cleanup', [str(HARNESS), 'cleanup', '--run', args.run])
            state = json.loads(state_path.read_text())
            proof = {'database': database, 'cleanup_confirmed_sql_404':
                     f'deleted {database} (SQL now 404)' in (directory / 'cleanup.log').read_text(),
                     'published': state.get('published', False), 'player_token_removed': 'token' not in state,
                     'shared_container_running': V.container_up(),
                     'living_token_unchanged': token_digest() == before_token,
                     'evidence_files': sorted(p.name for p in directory.iterdir())}
            proof['pass'] = (proof['cleanup_confirmed_sql_404'] and not proof['published'] and
                             proof['player_token_removed'] and proof['shared_container_running'] and
                             proof['living_token_unchanged'])
            (directory / 'cleanup-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
            if not proof['pass']:
                raise RuntimeError('cleanup proof failed; see cleanup-proof.json')
        except (RuntimeError, OSError) as error:
            print(str(error), file=sys.stderr)
            exit_code = 1
    print(f'evidence kept in {directory.relative_to(ROOT)}/', flush=True)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
