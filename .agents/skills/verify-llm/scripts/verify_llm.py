#!/usr/bin/env python3
"""Prove local model exchanges with living-mind and verify.py scratch databases."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[4]
SHARED = ROOT / '.agents/skills/verify/scripts/verify.py'
FAKE = Path(__file__).with_name('fake_llm.py')
CASES = ('basic', 'routing-group', 'routing-assign', 'routing-rotate', 'routing-child',
         'routing-default', 'overflow', 'retry-fallback', 'error-overflow', 'outage',
         'repair', 'deliberation-retry', 'retry-exhausted', 'timeout', 'missing-default-key')
FIELDS = {'at_ms', 'actor', 'purpose', 'profile', 'model', 'latency_ms', 'request', 'reply', 'tokens', 'error'}


def rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def stop(process):
    if process is None:
        return 'not started'
    if process.poll() is not None:
        return 'already exited'
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            return 'SIGKILL'
    return 'SIGTERM'


class Run:
    def __init__(self, name, prefix="llm"):
        if prefix not in ("llm", "minds"):
            raise ValueError("unsupported caller prefix")
        if not re.fullmatch(prefix + r'-[a-zA-Z0-9-]+', name):
            raise ValueError('run must match the validated caller prefix')
        self.name = name
        self.db = 'verify-' + name
        self.directory = ROOT / '.local/living/verify' / name
        self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = ROOT / '.local/living/journal' / self.db
        if self.journal.exists() or (self.directory / 'state.json').exists():
            raise ValueError('use a new run name; this run already has state or a journal')
        self.processes = []
        self.mind = None
        self.streams = []
        self.cleanup_record = {}
        self.token = None

    def command(self, args, filename='driver.log', check=True, timeout=240):
        result = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        with (self.directory / filename).open('a') as stream:
            stream.write('$ ' + ' '.join(str(x) for x in args) + '\n' + result.stdout + result.stderr + f'\nexit={result.returncode}\n')
        if check and result.returncode:
            raise RuntimeError(f'{args[0]} failed; see {self.directory / filename}')
        return result

    def harness(self, *args):
        return self.command([SHARED, args[0], '--run', self.name, *args[1:]])

    def sql(self, query, save):
        result = self.harness('sql', query, '--save', save)
        return json.loads(result.stdout)

    def admin(self, reducer, *args):
        return self.command([ROOT / 'living/tools/stdb', 'call', '-s', 'local', self.db, reducer,
                             *[json.dumps(x) for x in args]])

    def wait(self, predicate, label, seconds=55):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.mind and self.mind.poll() is not None:
                raise RuntimeError(f'mind exited while waiting for {label}; see mind.log')
            value = predicate()
            if value:
                return value
            time.sleep(0.25)
        raise RuntimeError(f'timed out after {seconds}s waiting for {label}')

    def fake(self, port, script, label):
        path = self.directory / f'{label}-script.json'
        path.write_text(json.dumps(script, indent=2))
        output = self.directory / f'{label}-server.log'
        stream = output.open('a')
        self.streams.append(stream)
        process = subprocess.Popen([sys.executable, str(FAKE), '--port', str(port), '--log',
                                    str(self.directory / f'{label}-requests.jsonl'), '--script', str(path)],
                                   cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        self.processes.append(process)
        saved = self.directory / 'processes.json'
        if saved.exists():
            ownership = json.loads(saved.read_text())
            ownership['owned_pids'] = [p.pid for p in self.processes]
            saved.write_text(json.dumps(ownership, indent=2))
        self.wait(lambda: process.poll() is None and 'READY ' in output.read_text(), f'{label} READY', 5)
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
            assert response.status == 200
        return process

    def exchanges(self):
        return [entry for path in self.journal.glob('*.jsonl') for entry in rows(path)]

    def start(self, models, ids, *, lod=False, lod_think_s=600, lod_prompt_s=120, lod_sticky_s=600):
        path = self.directory / 'models.json'
        path.write_text(json.dumps(models, indent=2))
        # Capture the admin token in memory only. Never write it or subprocess output to evidence.
        result = subprocess.run([str(ROOT / 'living/tools/stdb'), 'login', 'show', '--token'],
                                cwd=ROOT, capture_output=True, text=True, check=True, timeout=20)
        matches = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', result.stdout)
        if len(matches) != 1:
            raise RuntimeError('could not find one admin JWT from stdb login show --token')
        self.token = matches[0]
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER='http://127.0.0.1:3300',
                   LIVING_DB=self.db, LIVING_RUN=self.db, LIVING_SEED='world', LIVING_MODELS=str(path),
                   LIVING_NEO4J='off', LIVING_NEO4J_PASSWORD='', LIVING_ONLY=','.join(map(str, ids)),
                   LIVING_LLM_PER_MIN='0', LIVING_CONCURRENCY='4', LIVING_TOKEN=self.token,
                   LIVING_VERIFY_FAKE_KEY='dummy-local-only', LIVING_VERIFY_MISSING_KEY='',
                   LIVING_LOD='1' if lod else '0', LIVING_LOD_THINK_S=str(lod_think_s),
                   LIVING_LOD_PROMPT_S=str(lod_prompt_s), LIVING_LOD_STICKY_S=str(lod_sticky_s), NO_PROXY='127.0.0.1,localhost', RUST_LOG='info,neo4rs=warn,spacetimedb_sdk=warn')
        self.env = env
        self.launch_mind()
        source_paths = ('living/mind/src/llm.rs', 'living/mind/src/main.rs', 'living/mind/src/mind.rs',
                        'living/mind/src/prompts.rs', 'living/mind/src/mind/talk.rs', 'living/target/release/living-mind')
        (self.directory / 'source-hashes.json').write_text(json.dumps({p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                                                    for p in source_paths}, indent=2))
        (self.directory / 'processes.json').write_text(json.dumps({'mind_pid': self.mind.pid,
               'owned_pids': [p.pid for p in self.processes], 'only': ids, 'neo4j': 'off'}, indent=2))
        if models['profiles'][models['default']]['key_env'] == 'LIVING_VERIFY_MISSING_KEY':
            self.mind.wait(timeout=8)
            assert self.mind.returncode != 0
            assert 'has no API key' in (self.directory / 'mind.log').read_text()
            return
        self.wait(lambda: 'world subscribed:' in self.log(), 'subscription applied')

    def log(self):
        path = self.directory / 'mind.log'
        return path.read_text() if path.exists() else ''

    def private(self, query, save):
        return json.loads(self.harness('sql', query, '--as-admin', '--save', save).stdout)

    def launch_mind(self):
        stream = (self.directory / 'mind.log').open('a')
        self.streams.append(stream)
        self.mind = subprocess.Popen([str(ROOT / 'living/target/release/living-mind')], cwd=ROOT,
                                     env=self.env, stdout=stream, stderr=subprocess.STDOUT)
        self.processes.append(self.mind)
        (self.directory / 'processes.json').write_text(json.dumps({'mind_pid': self.mind.pid,
            'owned_pids': [p.pid for p in self.processes], 'only': self.env['LIVING_ONLY'],
            'neo4j': 'off', 'lod': self.env['LIVING_LOD']}, indent=2))

    def cleanup(self):
        self.cleanup_record['processes'] = [{'pid': p.pid, 'stop': stop(p), 'exit': p.poll()}
                                             for p in reversed(self.processes)]
        copied = self.directory / 'journal'
        if self.journal.exists():
            shutil.copytree(self.journal, copied, dirs_exist_ok=True)
            for source in self.journal.glob('*.jsonl'):
                assert source.read_bytes() == (copied / source.name).read_bytes()
            shutil.rmtree(self.journal)
        self.cleanup_record['journal_copied'] = copied.exists()
        self.cleanup_record['journal_removed'] = not self.journal.exists()
        self.harness('cleanup')

    def finish_cleanup(self):
        try:
            self.cleanup()
        except Exception as error:
            self.cleanup_record['error'] = str(error)
        for stream in self.streams:
            stream.close()
        state = json.loads((self.directory / 'state.json').read_text())
        self.cleanup_record['database_deleted'] = state.get('published') is False
        (self.directory / 'cleanup.json').write_text(json.dumps(self.cleanup_record, indent=2))
        if self.cleanup_record.get('error'):
            raise RuntimeError('cleanup failed; inspect cleanup.json')
        if not self.cleanup_record.get('database_deleted'):
            raise RuntimeError('database cleanup failed; inspect cleanup.json')


def profile(port, model, **extra):
    return {'base_url': f'http://127.0.0.1:{port}/v1', 'model': model,
            'key_env': 'LIVING_VERIFY_FAKE_KEY', 'max_tokens': 256,
            'reasoning_effort': {p: p for p in ('think', 'deliberate', 'consolidate', 'talk')}, **extra}


def run_case(run, case):
    run.harness('launch')
    run.harness('doctor')
    people = sorted(run.sql("SELECT id, name, stage, alive FROM character WHERE kind = 'person'", 'people'), key=lambda x: x['id'])
    adults = [p for p in people if p['alive'] and p['stage'] == 2][:2]
    children = [p for p in people if p['alive'] and p['stage'] == 1][:1]
    assert len(adults) == 2 and children, 'seed needs two adults and a child'
    selected = adults + children if case.startswith('routing') else adults[:1]
    ids = [p['id'] for p in selected]
    a, b = free_port(), free_port()
    while b == a:
        b = free_port()
    models = {'default': 'primary', 'profiles': {'primary': profile(a, 'fake-primary'), 'alternate': profile(b, 'fake-alternate', json_mode=False)}}
    script = {}
    expected = {p['name']: 'primary' for p in selected}
    if case == 'routing-group':
        models.update(groups={'VerifyTown': 'alternate'}, stages={'child': 'primary'}, rotate=['primary'])
        for person in selected:
            run.admin('set_background', person['id'], json.dumps({'town': 'VerifyTown'}))
            expected[person['name']] = 'alternate'
    elif case == 'routing-assign':
        models.update(groups={'VerifyTown': 'primary'}, assign={p['name']: 'alternate' for p in selected})
        for person in selected:
            run.admin('set_background', person['id'], json.dumps({'town': 'VerifyTown'}))
            expected[person['name']] = 'alternate'
    elif case == 'routing-rotate':
        models['rotate'] = ['primary', 'alternate']
        expected = {p['name']: models['rotate'][p['id'] % 2] for p in selected}
    elif case == 'routing-child':
        models.update(stages={'child': 'alternate'}, assign={children[0]['name']: 'primary'})
        # No configured group: stage must beat even an explicit child assignment.
        expected[children[0]['name']] = 'alternate'
    elif case == 'routing-default':
        models['profiles']['disabled'] = dict(profile(b, 'disabled'), key_env='LIVING_VERIFY_MISSING_KEY')
        models.update(groups={'VerifyTown': 'disabled'}, assign={adults[0]['name']: 'disabled'}, rotate=['disabled'])
        run.admin('set_background', adults[0]['id'], json.dumps({'town': 'VerifyTown'}))
    elif case in ('overflow', 'error-overflow'):
        models['profiles']['primary']['overflow'] = 'alternate'
        script = {'rules': [{'purpose': 'think', 'status': 429 if case == 'overflow' else 500, 'times': -1}]}
    elif case in ('retry-fallback', 'timeout'):
        models['assign'] = {adults[0]['name']: 'alternate'}
    elif case == 'repair':
        script = {'rules': [{'purpose': 'deliberate', 'repair': True, 'content_parts': True}]}
    elif case == 'deliberation-retry':
        models['assign'] = {adults[0]['name']: 'alternate'}
    elif case == 'retry-exhausted':
        script = {'rules': [{'purpose': 'deliberate', 'content': 'not JSON', 'times': -1}]}
    elif case == 'missing-default-key':
        models['profiles']['primary']['key_env'] = 'LIVING_VERIFY_MISSING_KEY'
    first = run.fake(a, script, 'primary')
    alternate_script = {}
    if case == 'retry-fallback':
        alternate_script = {'rules': [{'purpose': 'think', 'status': 429, 'times': -1}]}
    elif case == 'timeout':
        alternate_script = {'rules': [{'purpose': 'think', 'delay_s': 185}]}
    elif case == 'deliberation-retry':
        alternate_script = {'rules': [{'purpose': 'deliberate', 'content': 'not JSON'}]}
    run.fake(b, alternate_script, 'alternate')
    for person in selected:
        run.admin('set_behavior', person['id'], json.dumps({'think': f'verify {case}'}))
    run.start(models, ids)
    if case == 'missing-default-key':
        assert not run.exchanges()
        assert not rows(run.directory / 'primary-requests.jsonl')
        (run.directory / 'result.json').write_text(json.dumps({'case': case, 'pass': True, 'exit': run.mind.returncode}))
        return
    run.wait(lambda: any(e['purpose'] == 'deliberate' for e in run.exchanges()), 'deliberation exchange', 250 if case == 'timeout' else 65)
    if case == 'retry-exhausted':
        run.wait(lambda: len([e for e in run.exchanges() if e['purpose'] == 'deliberate']) >= 3, 'three rejected replies')
        time.sleep(1)
        thought = run.sql(f"SELECT * FROM thought WHERE actor = {ids[0]}", 'thoughts')
        assert any(t['kind'] == 'error' and 'could not decide' in t['summary'] for t in thought)
    else:
        def installed():
            return 'decided: verify fake wait' in (run.directory / 'mind.log').read_text()
        run.wait(installed, 'accepted graph')
        if case.startswith('routing'):
            run.wait(lambda: all(any(e['actor'] == name and e['purpose'] == 'deliberate' and e['profile'] == target
                                    for e in run.exchanges()) for name, target in expected.items()), 'all routing choices')
        if case == 'outage':
            stop(first)
            before = len(run.exchanges())
            # Install new graphs through the real authority to request fresh deliberations.
            for person in adults:
                if person['id'] not in ids:
                    continue
                run.admin('set_behavior', person['id'], json.dumps({'think': 'verify outage'}))
            run.wait(lambda: 'unreachable: holding model calls' in (run.directory / 'mind.log').read_text(), 'outage gate closes', 70)
            # Let a second call/probe wait behind the gate, then recover the same base URL.
            time.sleep(5)
            first = run.fake(a, {}, 'primary-restarted')
            run.wait(lambda: 'reachable again after' in (run.directory / 'mind.log').read_text(), 'outage recovery', 40)
            log = (run.directory / 'mind.log').read_text()
            recovery = re.search(r'reachable again after .*?; (\d+) calls were held meanwhile', log)
            assert recovery and int(recovery[1]) > 0, 'recovery must report held callers'
            assert len(run.exchanges()) > before
        if case == 'basic':
            run.harness('player', 'join', 'LlmVerifier')
            player = run.sql("SELECT id FROM character WHERE name = 'LlmVerifier'", 'player')[0]['id']
            run.admin('place_near', player, ids[0])
            run.harness('player', 'say', 'Hello, can you hear me?', '--to', str(ids[0]))
            run.wait(lambda: any(e['purpose'] == 'talk' for e in run.exchanges()), 'talk exchange', 40)
            run.wait(lambda: 'verify fake: I heard you.' in json.dumps(run.sql(f'SELECT * FROM chronicle WHERE a = {ids[0]}', 'talk-speech')), 'accepted talk', 15)
        brains = run.sql('SELECT * FROM brain WHERE id = ' + str(ids[0]), 'brain-after')
        thoughts = run.sql('SELECT * FROM thought WHERE actor = ' + str(ids[0]), 'thoughts')
        run.sql('SELECT * FROM routine WHERE actor = ' + str(ids[0]), 'routines-after')
        run.sql('SELECT * FROM chronicle WHERE a = ' + str(ids[0]), 'speech-after')
        assert any(t['kind'] == 'deliberate' and 'verify fake wait' in t['summary'] for t in thoughts)
        assert any(b['source'] == 'mind' for b in brains)
    exchanges = run.exchanges()
    assert exchanges and all(FIELDS <= e.keys() for e in exchanges)
    assert all(e['model'] == models['profiles'][e['profile']]['model'] for e in exchanges)
    if case in ('overflow', 'error-overflow'):
        failure = next(e for e in exchanges if e['purpose'] == 'think' and e['profile'] == 'primary' and e['error'])
        assert ('HTTP 429' if case == 'overflow' else 'HTTP 500') in failure['error']
        assert any(e['purpose'] == 'think' and e['profile'] == 'alternate' and not e['error'] for e in exchanges)
    elif case == 'retry-fallback':
        failed = sorted([e for e in exchanges if e['purpose'] == 'think' and e['profile'] == 'alternate' and e['error']], key=lambda e: e['at_ms'])
        fallback = min(e['at_ms'] for e in exchanges if e['purpose'] == 'think' and e['profile'] == 'primary' and not e['error'])
        failed = [e for e in failed if e['at_ms'] < fallback]
        assert len(failed) == 4 and all('HTTP 429' in e['error'] for e in failed), 'first think episode must retry exactly three times'
        assert all(y['at_ms'] - x['at_ms'] >= delay for x, y, delay in zip(failed, failed[1:], (1500, 3000, 6000)))
        assert any(e['purpose'] == 'think' and e['profile'] == 'primary' and not e['error'] for e in exchanges)
    elif case == 'timeout':
        failed = [e for e in exchanges if e['purpose'] == 'think' and e['profile'] == 'alternate' and e['error']]
        assert len(failed) == 1 and failed[0]['latency_ms'] >= 179000
        assert 'timed out' in failed[0]['error']
        assert any(e['purpose'] == 'think' and e['profile'] == 'primary' and not e['error'] for e in exchanges)
    elif case == 'repair':
        assert any(e['purpose'] == 'deliberate' and e['reply'].startswith('```json') for e in exchanges)
    elif case == 'deliberation-retry':
        assert any(e['purpose'] == 'deliberate' and e['profile'] == 'alternate' and e['reply'] == 'not JSON' for e in exchanges)
        repaired = [e for e in exchanges if e['purpose'] == 'deliberate' and e['profile'] == 'primary']
        assert repaired and any('That reply was rejected:' in m['content'] for e in repaired for m in e['request']['messages'])
    elif case == 'basic':
        assert any(t['kind'] == 'consolidate' and t['summary'] == 'I remember this moment.' for t in thoughts), 'experience consolidation must be accepted, not only identity bootstrap'
        speech = json.loads((run.directory / 'speech-after.json').read_text())
        assert any('verify fake: I will wait here.' in t['text'] for t in speech), 'think speech must reach the authority'
        routines = json.loads((run.directory / 'routines-after.json').read_text())
        assert any(t['name'] == 'current plan' and json.loads(t['graph']) == {'wait': 2.0} for t in routines), 'wait graph must be installed as a routine'
        assert set(e['purpose'] for e in exchanges) == {'think', 'deliberate', 'consolidate', 'talk'}
        requests = rows(run.directory / 'primary-requests.jsonl')
        assert all(e['body']['max_tokens'] == 256 and e['body']['response_format'] == {'type': 'json_object'} for e in requests)
        assert all(e['tokens'] == 17 for e in exchanges if e['error'] is None)
    if case.startswith('routing'):
        for actor, target in expected.items():
            assert all(e['profile'] == target for e in exchanges if e['actor'] == actor)
        requests = rows(run.directory / 'alternate-requests.jsonl')
        assert all('response_format' not in e['body'] for e in requests)
    (run.directory / 'result.json').write_text(json.dumps({'case': case, 'pass': True, 'expected_profiles': expected,
                'journal_entries': len(exchanges), 'purposes': sorted(set(e['purpose'] for e in exchanges))}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='new suite name starting with llm-')
    parser.add_argument('--case', choices=CASES, action='append', help='repeat to select cases; default all')
    args = parser.parse_args()
    if not re.fullmatch(r'llm-[a-zA-Z0-9-]+', args.run):
        parser.error('--run must start with llm-')
    with urllib.request.urlopen('http://127.0.0.1:3300/v1/ping', timeout=5) as response:
        assert response.status == 200, 'the existing SpacetimeDB container must be running'
    suite = ROOT / '.local/living/verify' / args.run
    suite.mkdir(parents=True, exist_ok=False)
    with (suite / 'build.log').open('w') as stream:
        subprocess.run(['cargo', 'build', '--manifest-path', 'living/Cargo.toml', '-p', 'living-mind', '--release'],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    subprocess.run([sys.executable, str(Path(__file__).with_name('fake_contract.py')),
                    '--run', args.run + '-fake-contract'], cwd=ROOT, check=True)
    with (suite / 'cargo-tests.log').open('w') as stream:
        subprocess.run(['cargo', 'test', '--manifest-path', 'living/Cargo.toml', '-p', 'living-mind', 'llm::tests', '--', '--nocapture'],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    results = []
    for case in args.case or CASES:
        run = Run(args.run + '-' + case)
        print(f'RUN {case} {run.directory}', flush=True)
        try:
            run_case(run, case)
            results.append({'case': case, 'pass': True, 'evidence': str(run.directory)})
        except Exception as error:
            (run.directory / 'failure.txt').write_text(traceback.format_exc())
            results.append({'case': case, 'pass': False, 'error': f'{type(error).__name__}: {error}', 'evidence': str(run.directory)})
            print(f'FAIL {case}: {type(error).__name__}: {error}', flush=True)
        finally:
            run.finish_cleanup()
        (suite / 'results.json').write_text(json.dumps(results, indent=2))
        print(f'DONE {case} pass={results[-1]["pass"]}; evidence kept', flush=True)
    if not all(r['pass'] for r in results):
        sys.exit(1)


if __name__ == '__main__':
    main()
