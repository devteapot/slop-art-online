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

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'living/tools'))
import trials  # noqa: E402  (consolidation_table: the trial report's per-character accounting)

ROOT = Path(__file__).resolve().parents[4]
# The mind binary the suite builds: in CARGO_TARGET_DIR when set (a private build directory),
# else living/target. Running another path would test whatever binary another checkout left.
MIND_BIN = Path(os.environ.get('CARGO_TARGET_DIR') or ROOT / 'living/target') / 'release/living-mind'
SHARED = ROOT / '.agents/skills/verify/scripts/verify.py'
# The server verify.py uses: the shared container, or a worker's own (see verify/SKILL.md).
STDB_URL = os.environ.get('LIVING_STDB_URL', 'http://127.0.0.1:3300').rstrip('/')
STDB_CONTAINER = os.environ.get('LIVING_STDB_CONTAINER', 'sao-living_spacetimedb_1')
FAKE = Path(__file__).with_name('fake_llm.py')
CASES = ('basic', 'routing-group', 'routing-assign', 'routing-rotate', 'routing-child',
         'routing-default', 'overflow', 'capacity-overflow', 'capacity-retry', 'retry-fallback', 'error-overflow', 'outage',
         'repair', 'deliberation-retry', 'retry-exhausted', 'timeout', 'missing-default-key', 'mix',
         'fast-route', 'fast-cap')
FIELDS = {'at_ms', 'actor', 'purpose', 'profile', 'model', 'latency_ms', 'request', 'reply', 'tokens', 'error', 'lane', 'queue_wait_ms', 'prompt_tokens', 'completion_tokens', 'cached_tokens', 'effort', 'mix', 'attention'}


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
        if prefix not in ("llm", "minds", "gate"):  # gate: the merge's scene gate (living/tools/scene_gate.py)
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
        self.launch_blocked = False

    def command(self, args, filename='driver.log', check=True, timeout=240):
        result = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        with (self.directory / filename).open('a') as stream:
            stream.write('$ ' + ' '.join(str(x) for x in args) + '\n' + result.stdout + result.stderr + f'\nexit={result.returncode}\n')
        if check and result.returncode:
            raise RuntimeError(f'{args[0]} failed; see {self.directory / filename}')
        return result

    def harness(self, *args):
        if args[0] == 'launch':
            result = self.command(['docker', 'inspect', STDB_CONTAINER, '--format', '{{json .Mounts}}'])
            mounts = json.loads(result.stdout)
            source = next((m.get('Source') for m in mounts if m.get('Destination') == '/wasm'), None)
            # Docker Desktop reports bind mounts by their path in its VM (/host_mnt/Users/...).
            source = source.removeprefix('/host_mnt') if source else source
            check = {'mounted': source, 'worktree_copy': True}
            (self.directory / 'mount-check.json').write_text(json.dumps(check, indent=2))
            if source is None or not Path(source).is_dir() or not os.access(source, os.W_OK):
                self.launch_blocked = True
                raise RuntimeError(f"/wasm mount unavailable or unwritable: {source}; no database published")
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

    def start(self, models, ids, *, lod=False, lod_think_s=600, lod_prompt_s=120, lod_sticky_s=600, seed='world', extra_env=None):
        path = self.directory / 'models.json'
        path.write_text(json.dumps(models, indent=2))
        # Capture the admin token in memory only. Never write it or subprocess output to evidence.
        result = subprocess.run([str(ROOT / 'living/tools/stdb'), 'login', 'show', '--token'],
                                cwd=ROOT, capture_output=True, text=True, check=True, timeout=20)
        matches = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', result.stdout)
        if len(matches) != 1:
            raise RuntimeError('could not find one admin JWT from stdb login show --token')
        self.token = matches[0]
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=STDB_URL,
                   LIVING_DB=self.db, LIVING_RUN=self.db, LIVING_SEED=seed, LIVING_MODELS=str(path),
                   LIVING_NEO4J='off', LIVING_NEO4J_PASSWORD='', LIVING_ONLY=','.join(map(str, ids)),
                   LIVING_LLM_PER_MIN='0', LIVING_CONCURRENCY='4', LIVING_TOKEN=self.token,
                   LIVING_VERIFY_FAKE_KEY='dummy-local-only', LIVING_VERIFY_MISSING_KEY='',
                   LIVING_LOD='1' if lod else '0', LIVING_LOD_THINK_S=str(lod_think_s),
                   LIVING_LOD_PROMPT_S=str(lod_prompt_s), LIVING_LOD_STICKY_S=str(lod_sticky_s), NO_PROXY='127.0.0.1,localhost', RUST_LOG='info,neo4rs=warn,spacetimedb_sdk=warn')
        env.update(extra_env or {})
        self.env = env
        self.launch_mind()
        source_paths = ('living/mind/src/llm.rs', 'living/mind/src/main.rs', 'living/mind/src/mind.rs',
                        'living/mind/src/prompts.rs', 'living/mind/src/mind/talk.rs', str(MIND_BIN))
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
        self.mind = subprocess.Popen([str(MIND_BIN)], cwd=ROOT,
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
        if not self.launch_blocked:
            self.harness('cleanup')

    def finish_cleanup(self):
        try:
            self.cleanup()
        except Exception as error:
            self.cleanup_record['error'] = str(error)
        for stream in self.streams:
            stream.close()
        state_path = self.directory / 'state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        self.cleanup_record['database_not_created'] = self.launch_blocked and not state_path.exists()
        self.cleanup_record['database_deleted'] = state.get('published') is False
        (self.directory / 'cleanup.json').write_text(json.dumps(self.cleanup_record, indent=2))
        if self.cleanup_record.get('error'):
            raise RuntimeError('cleanup failed; inspect cleanup.json')
        if not (self.cleanup_record.get('database_deleted') or self.cleanup_record.get('database_not_created')):
            raise RuntimeError('database cleanup failed; inspect cleanup.json')


def profile(port, model, **extra):
    return {'base_url': f'http://127.0.0.1:{port}/v1', 'model': model,
            'key_env': 'LIVING_VERIFY_FAKE_KEY', 'max_tokens': 256, 'requests_per_minute': 6000,
            'reasoning_effort': {p: p for p in ('think', 'deliberate', 'consolidate', 'talk')}, **extra}


def fast_case(run, case):
    """The fast lane (docs/FAST_LANE.md) on a real world with the release mind and a fake fast
    provider. Fighters are spawned minds (`spawn_crowd`), each pair 1.2 m apart with spears, the
    world's `fast_lane_on` law on; a blow taken issues a `fast_ask` row the mind serves.

    fast-route: one pair, only the victim served. Purpose `fast` goes to `rethink.json`'s
    `fast.route` profile (a profile of its own here) on the urgent lane, never to the default
    profile; the first reply is held past `fast.timeout_ms` and is dropped as a timeout
    (journaled, a `fast` thought "kept: timed out"); later ones keep the plan ("kept: as it is").

    fast-cap: a battle of 20 (ten pairs attacking each other), all served, under the world's laws
    as shipped (`fast_lane_rate` 2 a second, `fast_lane_inflight` 4), each fast reply held 2.5 s.
    At most 4 requests are ever issued at once (sampled `fast_ask`) and in flight at the provider,
    and no more start in any second than the rate allows (the bucket holds one second's worth).
    Records how many fighters got a call and how long each trigger waited for its turn."""
    run.harness('launch')
    run.harness('doctor')
    before = {c['id'] for c in run.sql('SELECT id FROM character', 'ids-before')}
    pairs = 1 if case == 'fast-route' else 10
    run.admin('spawn_crowd', 2 * pairs, True)
    made = sorted(c['id'] for c in run.sql('SELECT id FROM character', 'ids-after') if c['id'] not in before)
    assert len(made) == 2 * pairs, made
    victims, foes = made[:pairs], made[pairs:]
    for who in made:
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    run.admin('set_world_law', 'fast_lane_on', 'true')
    origin = run.sql(f'SELECT x, y FROM body WHERE id = {victims[0]}', 'origin')[0]
    for k, (v, f) in enumerate(zip(victims, foes)):
        x, y = origin['x'] + 4.0 * (k % 5), origin['y'] + 4.0 * (k // 5)
        run.admin('place_at', v, x, y)
        run.admin('place_at', f, x + 1.2, y)
        run.admin('grant_items', f, 'spear', 1)
        run.admin('grant_items', v, 'spear', 1)
    a, b = free_port(), free_port()
    while b == a:
        b = free_port()
    models = {'default': 'primary', 'profiles': {'primary': profile(a, 'fake-primary'), 'fastp': profile(b, 'fake-fast')}}
    cfg = json.loads((ROOT / 'living/configs/rethink.json').read_text())
    cfg['fast'] = {'route': 'fastp', 'timeout_ms': 3000, 'experiences': 12}
    path = run.directory / 'rethink-fast.json'
    path.write_text(json.dumps(cfg, indent=2))
    run.fake(a, {}, 'primary')
    held = {'rules': [{'purpose': 'fast', 'delay_s': 5, 'times': 1}]} if case == 'fast-route' else {'rules': [{'purpose': 'fast', 'delay_s': 2.5, 'times': -1}]}
    run.fake(b, held, 'fast')
    served = victims if case == 'fast-route' else made
    run.start(models, served, extra_env={'LIVING_RETHINK_CONFIG': str(path), 'LIVING_CONCURRENCY': '32'})
    t0 = int(time.time() * 1000)
    graph = lambda other: json.dumps({'first': [{'do': {'skill': 'attack', 'target': {'id': other}}}, {'wait': 0.5}]})
    for v, f in zip(victims, foes):
        run.admin('set_behavior', f, graph(v))
        if case == 'fast-cap':
            run.admin('set_behavior', v, graph(f))
    fast_log = run.directory / 'fast-requests.jsonl'
    thoughts = lambda: [t for t in run.private('SELECT * FROM thought', 'thoughts') if t['kind'] == 'fast']
    if case == 'fast-route':
        run.wait(lambda: len([t for t in thoughts() if t['summary'].startswith('kept: as it is')]) >= 1 and any('timed out' in t['summary'] for t in thoughts()), 'a timed-out and an answered fast request', 90)
        fast = [r for r in rows(fast_log) if r['purpose'] == 'fast']
        primary_fast = [r for r in rows(run.directory / 'primary-requests.jsonl') if r['purpose'] == 'fast']
        journal = [e for e in run.exchanges() if e.get('purpose') == 'fast']
        assert len(fast) >= 2 and not primary_fast, {'fast_at_fast': len(fast), 'fast_at_primary': len(primary_fast)}
        assert all(r['model'] == 'fake-fast' for r in fast), [r['model'] for r in fast]
        assert any('timeout' in (e.get('error') or '') for e in journal), journal[:3]
        answered = [e for e in journal if not e.get('error')]
        assert answered and all(e.get('profile') == 'fastp' and str(e.get('lane', '')).lower() == 'urgent' and 'latency_ms' in e and 'queue_wait_ms' in e for e in answered), answered[:2]
        (run.directory / 'result.json').write_text(json.dumps({'case': case, 'pass': True, 'fast_requests': len(fast), 'journal': len(journal),
                                                               'thoughts': [t['summary'] for t in thoughts()][:6]}, indent=2))
        return
    # fast-cap: watch the issued rows for 30 s.
    issued_max, samples = 0, 0
    end = time.time() + 30
    while time.time() < end:
        issued = [r for r in run.private('SELECT * FROM fast_ask', 'fast-ask') if r['issued_ms']]
        issued_max = max(issued_max, len(issued))
        samples += 1
        time.sleep(0.25)
    for v, f in zip(victims, foes):
        run.admin('set_behavior', f, json.dumps({'wait': 300}))
        run.admin('set_behavior', v, json.dumps({'wait': 300}))
    time.sleep(4)
    calls = sorted(r['at_ms'] for r in rows(fast_log) if r['purpose'] == 'fast')
    spans = [(r['at_ms'], r['at_ms'] + int(r['delay_s'] * 1000)) for r in rows(fast_log) if r['purpose'] == 'fast']
    concurrent = max((sum(1 for s, e in spans if s <= t < e) for t, _ in spans), default=0)
    per_second = max((sum(1 for u in calls if t <= u < t + 1000) for t in calls), default=0)
    done = thoughts()
    waits, by_fighter = [], {}
    for t in done:
        d = json.loads(t['detail'] or '{}')
        if d.get('issued_ms') and d.get('trigger_ms'):
            waits.append((d['issued_ms'] - d['trigger_ms']) / 1000)
        by_fighter[t['actor']] = by_fighter.get(t['actor'], 0) + 1
    q = sorted(waits)
    pct = lambda p: round(q[min(len(q) - 1, int(p * len(q)))], 2) if q else None
    record = {'case': case, 'fighters': len(made), 'laws': {'fast_lane_rate': 2, 'fast_lane_inflight': 4, 'fast_lane_gap_s': 6},
              'window_s': 30, 'samples': samples, 'issued_at_once_max': issued_max, 'in_flight_at_provider_max': concurrent,
              'started_in_one_second_max': per_second, 'calls': len(calls), 'fighters_with_a_call': len(by_fighter),
              'calls_per_fighter': sorted(by_fighter.values()), 'wait_s_p50': pct(0.5), 'wait_s_p90': pct(0.9), 'wait_s_max': q[-1] if q else None}
    (run.directory / 'result.json').write_text(json.dumps(record, indent=2))
    assert calls and issued_max <= 4 and concurrent <= 4 and per_second <= 3, record
    record['pass'] = True
    (run.directory / 'result.json').write_text(json.dumps(record, indent=2))


def run_case(run, case):
    if case in ('fast-route', 'fast-cap'):
        return fast_case(run, case)
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
    elif case == 'capacity-overflow':
        # The provider has no capacity for the primary's model (Mistral's 429 body): listed
        # memory work goes to the overflow at the overflow's effort.
        models['profiles']['primary'].update(overflow='alternate', capacity_overflow=['consolidate'])
        script = {'rules': [{'purpose': 'consolidate', 'capacity': True, 'times': -1}]}
    elif case == 'capacity-retry':
        # No fallback: the first experience consolidation's call and its paced retry find no
        # capacity; the mind tries again 20 s later, and that one is integrated.
        script = {'rules': [{'purpose': 'consolidate', 'contains': 'New experiences to integrate', 'capacity': True, 'times': 2}]}
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
    elif case == 'mix':
        # A named mix routes each purpose (and compile by stage of attention) with its own effort.
        models['mixes'] = {'verify-mix': {'think': 'primary@low', 'deliberate': {'on_stage': 'alternate@high', 'off_stage': 'primary'},
                                          'talk': 'alternate', 'consolidate': 'primary@high', '*': 'primary'}}
        models['assign'] = {adults[0]['name']: 'verify-mix'}
        expected = {adults[0]['name']: 'verify-mix'}
    first = run.fake(a, script, 'primary')
    alternate_script = {}
    if case == 'basic':
        models['profiles']['primary']['prompt_cache_key'] = True
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
        if case == 'mix':
            name = adults[0]['name']
            mine = lambda: [e for e in run.exchanges() if e['actor'] == name]
            # Nobody is near: the first compile is off stage. A player who speaks puts them on stage.
            run.wait(lambda: any(e['purpose'] == 'deliberate' and e['attention'] == 'off_stage' for e in mine()), 'off-stage compile')
            run.harness('player', 'join', 'LlmMixVerifier')
            player = run.sql("SELECT id FROM character WHERE name = 'LlmMixVerifier'", 'mix-player')[0]['id']
            run.admin('place_near', player, ids[0])
            run.harness('player', 'say', 'Hello, can you hear me?', '--to', str(ids[0]))
            run.wait(lambda: any(e['purpose'] == 'talk' for e in mine()), 'talk exchange', 40)
            run.admin('set_behavior', ids[0], json.dumps({'think': 'verify mix on stage'}))
            run.wait(lambda: any(e['purpose'] == 'deliberate' and e['attention'] == 'on_stage' and not e['error'] for e in mine()), 'on-stage compile', 90)
            run.wait(lambda: any(e['purpose'] == 'consolidate' for e in mine()), 'consolidation', 150)
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
            # A deliberation whose model cannot be reached keeps its request and its reasons
            # (it is tried again after a backoff); it is not skipped as "could not decide".
            run.wait(lambda: 'could not reach its model' in (run.directory / 'mind.log').read_text(), 'a deliberation waits for its model', 70)
            pending = run.sql(f'SELECT * FROM deliberation WHERE actor = {ids[0]}', 'deliberation-during-outage')
            assert pending and 'verify outage' in pending[0]['reason'], f'the request survives the outage: {pending}'
            during = run.sql(f'SELECT * FROM thought WHERE actor = {ids[0]}', 'thoughts-during-outage')
            assert not any('could not decide' in t['summary'] for t in during), 'a model error does not consume the request'
            # Keep the outage long enough for a held probe, then restore the same URL.
            time.sleep(5)
            restarted_ms = time.time_ns() // 1_000_000
            first = run.fake(a, {}, 'primary-restarted')
            # A failed compile can leave the next think behind its authority cooldown.
            # Fresh demand after restoration avoids exhausting its probe while still down.
            run.harness('player', 'join', 'LlmOutageVerifier')
            player = run.sql("SELECT id FROM character WHERE name = 'LlmOutageVerifier'", 'outage-player')[0]['id']
            run.admin('place_near', player, ids[0])
            run.harness('player', 'say', 'Are you still there?', '--to', str(ids[0]))
            run.wait(lambda: 'reachable again after' in (run.directory / 'mind.log').read_text(), 'outage recovery', 70)
            run.wait(lambda: bool(rows(run.directory / 'primary-restarted-requests.jsonl')) and
                     any(e['at_ms'] >= restarted_ms and e['error'] is None for e in run.exchanges()),
                     'successful exchange after provider restart')
            run.wait(lambda: any(b['source'] == 'mind' for b in run.sql(
                     f'SELECT * FROM brain WHERE id = {ids[0]}', 'brain-recovered')),
                     'accepted graph after outage', 160)
            log = (run.directory / 'mind.log').read_text()
            recovery = re.search(r'reachable again after .*?; (\d+) calls were held meanwhile', log)
            assert recovery and int(recovery[1]) > 0, 'recovery must report held callers'
            assert len(run.exchanges()) > before
        if case in ('capacity-overflow', 'capacity-retry'):
            run.harness('player', 'join', 'LlmCapacityVerifier')
            player = run.sql("SELECT id FROM character WHERE name = 'LlmCapacityVerifier'", 'capacity-player')[0]['id']
            run.admin('place_near', player, ids[0])
            run.harness('player', 'say', 'Hello, can you hear me?', '--to', str(ids[0]))
            run.wait(lambda: any(t['kind'] == 'consolidate' and t['summary'] == 'I remember this moment.'
                                 for t in run.sql(f'SELECT * FROM thought WHERE actor = {ids[0]}', 'capacity-thoughts')), 'accepted consolidation', 180)
            outcomes = run.journal / 'outcomes/consolidations.jsonl'
            run.wait(lambda: any(r['outcome'] == 'integrated' and r['model_call'] for r in rows(outcomes)), 'integrated consolidation outcome', 20)
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
    elif case == 'capacity-overflow':
        memory = sorted([e for e in exchanges if e['purpose'] == 'consolidate'], key=lambda e: e['at_ms'])
        short = [e for e in memory if e['profile'] == 'primary']
        assert short and all('HTTP 429' in e['error'] and 'backend_out_of_capacity' in e['error'] for e in short), short
        moved = [e for e in memory if e['profile'] == 'alternate']
        assert moved and all(e['error'] is None and e['lane'] == 'background' and e['effort'] == 'consolidate' for e in moved), moved
        # Each capacity failure goes straight to the overflow: no paced retry on the short model.
        assert len(short) == len(moved), (len(short), len(moved))
        assert all(e['profile'] == 'primary' for e in exchanges if e['purpose'] in ('think', 'deliberate')), 'only listed memory work moves'
        assert not re.search(r'consolidation for .* failed', (run.directory / 'mind.log').read_text()), 'no consolidation failed'
        lines = rows(run.journal / 'outcomes/consolidations.jsonl')
        assert lines and all(r['outcome'] == 'integrated' and r['route'] == 'fallback' and r['model'] == 'fake-alternate' for r in lines if r['model_call']), lines
        table = trials.consolidation_table(run.journal)
        mine = table['by_character'][selected[0]['name']]
        assert mine['fallback'] >= 1 and mine['primary'] == 0 and mine['retried'] == 0 and mine['lost'] == 0, mine
        expected = {'consolidate': {'primary_capacity_429': len(short), 'alternate_ok': len(moved)}, 'table': table}
    elif case == 'capacity-retry':
        memory = sorted([e for e in exchanges if e['purpose'] == 'consolidate' and 'New experiences to integrate' in json.dumps(e['request'])], key=lambda e: e['at_ms'])
        assert [bool(e['error']) for e in memory[:3]] == [True, True, False], [(e['profile'], e['error']) for e in memory]
        assert all(e['profile'] == 'primary' for e in memory), 'no overflow without capacity_overflow'
        assert memory[2]['at_ms'] - memory[1]['at_ms'] >= 19000, 'the retry waits for the consolidation backoff'
        assert re.search(r'consolidation for .* failed \(1x\).*backend_out_of_capacity', (run.directory / 'mind.log').read_text())
        lines = [r for r in rows(run.journal / 'outcomes/consolidations.jsonl') if r['model_call']]
        assert [(r['outcome'], r['route'], r['attempt']) for r in lines[:2]] == [('failed', None, 1), ('integrated', 'primary', 2)], lines
        assert 'backend_out_of_capacity' in lines[0]['failure'] and lines[0]['retry_in_s'] == 20
        table = trials.consolidation_table(run.journal)
        mine = table['by_character'][selected[0]['name']]
        assert mine['retried'] == 1 and mine['lost'] == 0 and mine['primary'] >= 1 and mine['capacity_429'] == 1, mine
        expected = {'table': table}
    elif case == 'retry-fallback':
        failed = sorted([e for e in exchanges if e['purpose'] == 'think' and e['profile'] == 'alternate' and e['error']], key=lambda e: e['at_ms'])
        fallback = min(e['at_ms'] for e in exchanges if e['purpose'] == 'think' and e['profile'] == 'primary' and not e['error'])
        failed = [e for e in failed if e['at_ms'] < fallback]
        assert len(failed) == 1 and 'HTTP 429' in failed[0]['error'], 'a failed nondefault profile falls back without blind retries'
        assert any(e['purpose'] == 'think' and e['profile'] == 'primary' and not e['error'] for e in exchanges)
    elif case == 'timeout':
        failed = [e for e in exchanges if e['purpose'] == 'think' and e['profile'] == 'alternate' and e['error']]
        assert len(failed) == 1 and failed[0]['latency_ms'] >= 179000
        assert 'timed out' in failed[0]['error']
        assert 'unreachable: holding model calls' not in (run.directory / 'mind.log').read_text(), 'a timeout does not gate the host'
        assert any(e['purpose'] == 'think' and e['profile'] == 'primary' and not e['error'] for e in exchanges)
    elif case == 'repair':
        assert any(e['purpose'] == 'deliberate' and e['reply'].startswith('```json') for e in exchanges)
    elif case == 'deliberation-retry':
        assert any(e['purpose'] == 'deliberate' and e['profile'] == 'alternate' and e['reply'] == 'not JSON' for e in exchanges)
        repaired = [e for e in exchanges if e['purpose'] == 'deliberate' and e['profile'] == 'primary']
        assert repaired and any('That reply was rejected:' in m.get('content', '') for e in repaired for m in e['request']['messages'])
    elif case == 'basic':
        assert any(t['kind'] == 'consolidate' and t['summary'] == 'I remember this moment.' for t in thoughts), 'experience consolidation must be accepted, not only identity bootstrap'
        speech = json.loads((run.directory / 'speech-after.json').read_text())
        assert any('verify fake: I will wait here.' in t['text'] for t in speech), 'think speech must reach the authority'
        routines = json.loads((run.directory / 'routines-after.json').read_text())
        assert any(t['name'] == 'current plan' and json.loads(t['graph']) == {'wait': 2.0} for t in routines), 'wait graph must be installed as a routine'
        assert set(e['purpose'] for e in exchanges) == {'think', 'deliberate', 'consolidate', 'talk'}
        requests = rows(run.directory / 'primary-requests.jsonl')
        assert all(e['body']['max_tokens'] == 256 and e['body']['response_format'] == {'type': 'json_object'} for e in requests)
        assert all(e['tokens'] == 17 and e['prompt_tokens'] == 12 and e['completion_tokens'] == 5 and e['cached_tokens'] == 8 for e in exchanges if e['error'] is None)
        assert all(isinstance(e['queue_wait_ms'], int) and e['queue_wait_ms'] >= 0 for e in exchanges)
        assert all(e['lane'] == 'background' for e in exchanges if e['purpose'] == 'consolidate')
        assert any(e['lane'] == 'interactive' for e in exchanges if e['purpose'] == 'talk')
        keys = {}
        for e in exchanges:
            key = e['request'].get('prompt_cache_key')
            assert key
            assert keys.setdefault((e['profile'], e['purpose']), key) == key
    if case == 'mix':
        mine = [e for e in exchanges if e['actor'] == adults[0]['name']]
        want = {('think', None): ('primary', 'low'), ('deliberate', 'off_stage'): ('primary', 'deliberate'),
                ('deliberate', 'on_stage'): ('alternate', 'high'), ('talk', None): ('alternate', 'talk'), ('consolidate', None): ('primary', 'high')}
        seen = {}
        for e in mine:
            assert e['mix'] == 'verify-mix', e
            key = (e['purpose'], e['attention'])
            assert key in want, f'unexpected purpose/attention {key}'
            assert (e['profile'], e['effort']) == want[key], (key, e['profile'], e['effort'])
            assert e['request'].get('reasoning_effort') == e['effort']
            seen[key] = seen.get(key, 0) + 1
        assert set(seen) == set(want), f'every purpose and stage was exercised: {seen}'
        sent = rows(run.directory / 'primary-requests.jsonl') + rows(run.directory / 'alternate-requests.jsonl')
        assert {(r['model'], r['reasoning_effort']) for r in sent} >= {('fake-primary', 'low'), ('fake-primary', 'deliberate'), ('fake-alternate', 'high'), ('fake-alternate', 'talk'), ('fake-primary', 'high')}
        expected = {'journal': {f'{p}/{a}': n for (p, a), n in seen.items()}}
    if case.startswith('routing'):
        for actor, target in expected.items():
            assert all(e['profile'] == target for e in exchanges if e['actor'] == actor)
        requests = rows(run.directory / 'alternate-requests.jsonl')
        assert all('response_format' not in e['body'] and 'prompt_cache_key' not in e['body'] for e in requests)
    (run.directory / 'result.json').write_text(json.dumps({'case': case, 'pass': True, 'expected_profiles': expected,
                'journal_entries': len(exchanges), 'purposes': sorted(set(e['purpose'] for e in exchanges))}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='new suite name starting with llm-')
    parser.add_argument('--case', choices=CASES, action='append', help='repeat to select cases; default all')
    args = parser.parse_args()
    if not re.fullmatch(r'llm-[a-zA-Z0-9-]+', args.run):
        parser.error('--run must start with llm-')
    with urllib.request.urlopen(f'{STDB_URL}/v1/ping', timeout=5) as response:
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
