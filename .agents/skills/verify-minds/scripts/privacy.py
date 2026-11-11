#!/usr/bin/env python3
"""Where the words of a line may go (docs/COMMUNICATION.md §7): a scene with real minds (the
living-mind binary against the fake model), two players and the personal memory graph in
Neo4j. A speaker says lines holding a unique word in one way of speaking (`--way`); for every
character that should not receive the words (beyond the way's carry, and, for a way whose words
are for the addressee alone, everyone but the addressee) the check asserts that the word is in

  - none of its experience rows (read as the owner right after the lines),
  - none of its journaled model prompts (talk, think, deliberate, consolidate),
  - nothing its person's client receives (`my_experience`, for the two players),
  - none of its memories in Neo4j (the fake model's consolidation repeats what it was told:
    `$EXPTEXT:`, so a memory holds the words exactly when the prompt did).

Positive controls keep it from passing vacuously: the addressee (and, for a public way, those
in earshot) must have the word in each channel. Who should not receive the words follows from
the way's `speech_card` row (`private`, `carry_m`), so a new way plugs in with `--way NAME`.
`--control` is the check of the check: it treats a public way as private, so the bystander in
earshot counts as one who must not hear; the run then passes only if the check finds the word
in the bystander's channels.

    python3 .agents/skills/verify-minds/scripts/privacy.py --run minds-privacy-say --way say
    python3 .agents/skills/verify-minds/scripts/privacy.py --run minds-privacy-ctl --way say --control

Environment: LIVING_STDB_CONTAINER/LIVING_STDB_URL (the server), LIVING_PRIVACY_NEO4J
(`container:bolt-host:port`, e.g. `slop-trials-neo4j:127.0.0.1:7699`) and
LIVING_PRIVACY_NEO4J_ENV (a file holding LIVING_NEO4J_PASSWORD=..., never printed). Nodes are
written under this run's own name and deleted at the end.
"""
import argparse
import importlib.util
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('verify_minds', HERE / 'verify_minds.py')
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)
shared = vm.shared
URL = os.environ.get('LIVING_STDB_URL', 'http://127.0.0.1:3300').rstrip('/')
TALK = {'kind': 'talk', 'summary': 'verify privacy line', 'detail': '', 'latency_ms': 0, 'tokens': 0, 'model': 'fake', 'reference': ''}


def http(path, body=None, token=None, raw=False):
    data = (body if raw else json.dumps(body)).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method='POST' if data is not None else 'GET')
    req.add_header('Content-Type', 'text/plain' if raw else 'application/json')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class Person:
    def __init__(self, run, name):
        code, body = http('/v1/identity', {})
        assert code == 200, body
        self.run, self.token, self.name = run, json.loads(body)['token'], name
        self.call('join', [name])
        self.id = self.sql('SELECT * FROM my_characters')[0]['id']

    def call(self, reducer, args):
        code, body = http(f'/v1/database/{self.run.db}/call/{reducer}', args, self.token)
        with (self.run.directory / 'players.log').open('a') as f:
            f.write(json.dumps({'player': self.name, 'reducer': reducer, 'args': args, 'code': code, 'body': body[:300]}) + '\n')
        return code, body

    def sql(self, query):
        code, body = http(f'/v1/database/{self.run.db}/sql', query, self.token, raw=True)
        assert code == 200, body[:300]
        res = json.loads(body)[-1]
        names = [e['name'].get('some', '?') for e in res['schema']['elements']]
        return [dict(zip(names, r)) for r in res['rows']]


def quiet_spot(run, length, clear, avoid=()):
    w = run.private('SELECT width, height FROM world', 'world')[0]
    W, H = w['width'], w['height']
    tiles = bytearray(W * H)
    for row in run.private('SELECT * FROM terrain_chunk', 'terrain'):
        data = row['tiles']
        data = bytes.fromhex(data.removeprefix('0x')) if isinstance(data, str) else bytes(data)
        cx, cy = row['id'] & 0xFFFF, row['id'] >> 16
        for k, t in enumerate(data):
            x, y = cx * 16 + k % 16, cy * 16 + k // 16
            if x < W and y < H:
                tiles[y * W + x] = t
    bodies = [(b['x'], b['y']) for b in run.private('SELECT x, y FROM body', 'bodies')] + list(avoid)
    walk = lambda x, y: 0 <= x < W and 0 <= y < H and tiles[y * W + x] not in (2, 4, 7, 8, 9)
    for y in range(8, H - 8, 3):
        for x in range(8, W - length - 8, 2):
            if all(walk(x + i, y + d) for i in range(length) for d in (-1, 0, 1)) and all(math.dist((x + length / 2, y), b) > clear + length / 2 for b in bodies):
                return x + .5, y + .5
    raise RuntimeError('no quiet open spot')


def neo4j_cfg():
    spec = os.environ.get('LIVING_PRIVACY_NEO4J', '')
    env_file = os.environ.get('LIVING_PRIVACY_NEO4J_ENV', '')
    if not spec or not env_file:
        raise RuntimeError('set LIVING_PRIVACY_NEO4J=container:host:port and LIVING_PRIVACY_NEO4J_ENV=file')
    container, uri = spec.split(':', 1)
    pw = next(l.split('=', 1)[1].strip() for l in Path(env_file).read_text().splitlines() if l.startswith('LIVING_NEO4J_PASSWORD='))
    return container, uri, pw


def cypher(run, container, query, label):
    args = ['docker', 'exec', '-i', container, 'sh', '-c', 'NEO4J_PASSWORD="${NEO4J_AUTH#*/}" cypher-shell -a bolt://localhost:7687 -u neo4j --format plain']
    r = subprocess.run(args, input=query, capture_output=True, text=True, timeout=60)
    (run.directory / f'{label}.txt').write_text(r.stdout + r.stderr)
    if r.returncode:
        raise RuntimeError(f'cypher failed; see {label}.txt')
    return r.stdout


def scene(run, args):
    container, uri, pw = neo4j_cfg()
    run.harness('launch')
    run.harness('doctor')
    cards = run.sql('SELECT * FROM speech_card', 'speech-card')
    way = next((c for c in cards if c['name'] == args.way), None)
    assert way, f'no way `{args.way}` in speech_card: {[c["name"] for c in cards]}'
    private = way['private'] or args.control
    carry = way['carry_m']
    people = sorted(run.sql("SELECT * FROM character WHERE kind = 'person'", 'people'), key=lambda p: p['id'])
    adults = [p for p in people if p['ai'] and p['alive'] and p['stage'] == 2][:5]
    assert len(adults) == 5
    S, A, B, F, D = (p['id'] for p in adults)
    names = {p['id']: p['name'] for p in adults}
    near, far = Person(run, 'PrivacyNear'), Person(run, 'PrivacyFar')
    names[near.id], names[far.id] = near.name, far.name
    for who in (S, A, B, F, D):
        run.admin('set_behavior', who, json.dumps({'wait': 120}))
    x0, y0 = quiet_spot(run, 12, 30)
    x1, y1 = quiet_spot(run, 10, 30, avoid=[(x0 + i, y0) for i in range(12)])
    reach = way['reach_m'] if way['reach_m'] > 0 else 1.0
    at = {S: (x0 + 2, y0), A: (x0 + 2 + min(1.0, reach), y0), B: (x0 + 6, y0), near.id: (x0 + 7, y0),
          F: (x1 + 2, y1), D: (x1 + 4, y1), far.id: (x1 + 6, y1)}
    for who, (x, y) in at.items():
        run.admin('place_at', who, x, y)
    gap = way['gap_ms'] / 1000 + 0.6
    distance = lambda who: math.dist(at[S], at[who])
    assert all(distance(w) > carry + 20 for w in (F, D, far.id)), 'the far group must be beyond the way\'s carry'
    word = f'plover{random.randrange(10**6, 10**7)}'
    cast = {'speaker': S, 'addressee': A, 'bystander': B, 'near_player': near.id, 'far': F, 'decoy_speaker': D, 'far_player': far.id}
    receives = {A} | (set() if private else {w for w in (B, near.id) if distance(w) <= carry})
    excluded = {w for w in (A, B, near.id, F, D, far.id) if w not in receives}
    (run.directory / 'cast.json').write_text(json.dumps({'way': way, 'control': args.control, 'private': private, 'word': word, 'cast': cast, 'names': names,
        'at': {str(k): v for k, v in at.items()}, 'receives': sorted(receives), 'excluded': sorted(excluded)}, indent=2))
    script = {'replies': {
        'think': {'thought': 'I wait.', 'intend': ['wait'], 'say': None},
        'deliberate': vm.basic_reply(),
        'talk': {'thought': 'I answer.', 'say': 'verify privacy: I hear you.', 'end': True},
        'consolidate': {'summary': 'verify privacy summary', 'remember': [{'exp': f'$EXP:{word}', 'gist': f'$EXPTEXT:{word}', 'salience': 0.9, 'involves': []}],
                        'nodes': [], 'edges': [], 'retract': [], 'merge': [], 'identity': None, 'relations': [], 'judgments': [], 'places': []}},
        # The placeholders are filled from each mind's own prompt (fake_llm `cite`).
        'rules': [{'purpose': 'consolidate', 'cite': True, 'times': -1}]}
    models = vm.model(run, script)
    ai = [S, A, B, F, D]
    run.start(models, ai, extra_env={'LIVING_NEO4J': 'on', 'LIVING_NEO4J_URI': uri, 'LIVING_NEO4J_PASSWORD': pw})
    time.sleep(3)
    t0 = max(r['last_ms'] for r in run.private('SELECT last_ms FROM clock', 'clock'))
    # The lines: four with the word, in the way, to the addressee.
    for i, text in enumerate(('The {w} is under the third stone.', 'Remember {w}, it matters.', 'Tell no one about {w}.', 'Say {w} at the gate.')):
        r = run.command([vm.ROOT / 'living/tools/stdb', 'call', '-s', 'local', run.db, 'mind_say', str(S), json.dumps(text.format(w=word)), str(A), json.dumps(args.way), '0', json.dumps(TALK)], check=False)
        assert r.returncode == 0, f'line {i} refused; see driver.log'
        time.sleep(gap)
    # Decoys so that those who must not hear still have lines to integrate (non-vacuous).
    for i in range(4):
        run.command([vm.ROOT / 'living/tools/stdb', 'call', '-s', 'local', run.db, 'mind_say', str(D), json.dumps(f'verify privacy decoy {i} for you.'), str(F), '"say"', '0', json.dumps(TALK)])
        near.call('human_say', [f'verify privacy decoy {i} for you.', B])
        time.sleep(2.6)
    time.sleep(1.5)
    t_lines = max(r['last_ms'] for r in run.private('SELECT last_ms FROM clock', 'clock-after-lines'))
    # 1. Experience rows, read as the owner before the minds integrate (and delete) them.
    rows = {w: [r for r in run.private(f'SELECT * FROM experience WHERE observer = {w}', f'experience-{w}') if r['at_ms'] >= t0] for w in (A, B, F, D, near.id, far.id)}
    # 2. What each player's client receives.
    shown = {p.id: p.sql('SELECT * FROM my_experience') for p in (near, far)}
    (run.directory / 'my-experience.json').write_text(json.dumps(shown, indent=2))
    # 3. Deliberations: each mind thinks with its recent experiences in the prompt.
    for w in ai:
        run.admin('set_behavior', w, json.dumps({'think': 'verify privacy: what happened just now?'}))
    deadline = time.monotonic() + args.wait
    def consolidated(w):
        return any(t['kind'] == 'consolidate' and t['at_ms'] >= t_lines for t in run.private(f'SELECT * FROM thought WHERE actor = {w}', f'thoughts-{w}'))
    must = [A, F] + ([B] if B in receives or B in excluded else [])
    while time.monotonic() < deadline and not all(consolidated(w) for w in must):
        time.sleep(3)
    time.sleep(5)
    done = {w: consolidated(w) for w in ai}
    # Journal: every exchange of each mind, its system prompts put back.
    journal = {}
    for path in run.journal.glob('*.jsonl'):
        for line in path.read_text().splitlines():
            e = json.loads(line)
            # The prompt only (what the mind was sent), its system prompts put back; the reply is
            # what the model wrote, and the memory check covers what it kept.
            text = ''
            for m in (e.get('request') or {}).get('messages', []):
                ref = m.get('content_ref')
                text += json.dumps(m.get('content', ''), ensure_ascii=False)
                if ref and (run.journal / ref).exists():
                    text += (run.journal / ref).read_text()
            journal.setdefault(path.stem, []).append({'purpose': e.get('purpose'), 'has_word': word in text})
    by_name = {re.sub(r'[^A-Za-z0-9]', '_', names[w]): w for w in ai}
    prompts = {by_name[k]: v for k, v in journal.items() if k in by_name}
    memory = {w: cypher(run, container, f"MATCH (n) WHERE n.run = '{run.db}' AND n.actor = {w} RETURN properties(n) AS p;", f'neo4j-{w}') for w in ai}
    # The verdict, channel by channel.
    has = lambda texts: any(word in t for t in texts)
    report = {'word': word, 'way': args.way, 'control': args.control, 'consolidated': {names[w]: v for w, v in done.items()}, 'violations': [], 'positives': [], 'missing_positives': []}
    def judge(channel, who, found, applicable=True):
        if not applicable:
            return
        entry = {'channel': channel, 'who': names[who], 'role': next(k for k, v in cast.items() if v == who)}
        if who in excluded and found:
            report['violations'].append(entry)
        elif who in receives:
            (report['positives'] if found else report['missing_positives']).append(entry)
    for w in (A, B, F, D, near.id, far.id):
        judge('experience', w, has(r['text'] for r in rows[w]))
    for p in (near, far):
        judge('my_experience', p.id, has(r['text'] for r in shown[p.id]))
    for w in (A, B, F, D):
        judge('prompts', w, any(x['has_word'] for x in prompts.get(w, [])), applicable=bool(prompts.get(w)))
        judge('neo4j', w, word in memory[w], applicable=done[w])
    # Every excluded mind was checked in each channel where it had something to check.
    report['checked'] = {names[w]: {'experience_rows': len(rows[w]), 'prompts': len(prompts.get(w, [])), 'consolidated': done.get(w)} for w in (A, B, F, D)}
    (run.directory / 'privacy.json').write_text(json.dumps(report, indent=2))
    leaks = report['violations']
    if args.control:
        # The control passes only when the check catches the words in the bystander's channels.
        caught = {v['channel'] for v in leaks if v['role'] in ('bystander', 'near_player')}
        ok = {'experience', 'my_experience', 'prompts'} <= caught
        return {'status': 'pass' if ok else 'fail', 'control_caught': sorted(caught), 'report': 'privacy.json'}
    vacuous = [w for w in (F,) if not done[w]] + ([A] if not done[A] else [])
    ok = not leaks and not report['missing_positives'] and not vacuous
    return {'status': 'pass' if ok else 'fail', 'violations': leaks, 'missing_positives': report['missing_positives'], 'not_consolidated': [names[w] for w in vacuous], 'report': 'privacy.json'}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True, help='a new run name starting with minds-')
    ap.add_argument('--way', default='say')
    ap.add_argument('--control', action='store_true', help='treat the way as private: the check must then find the bystander\'s words')
    ap.add_argument('--wait', type=float, default=260, help='seconds to wait for the minds to integrate the lines')
    args = ap.parse_args()
    run = vm.Run(args.run)
    result = None
    try:
        result = scene(run, args)
    except Exception as error:
        (run.directory / 'failure.txt').write_text(traceback.format_exc())
        result = {'status': 'fail', 'error': f'{type(error).__name__}: {error}'}
    finally:
        try:
            container, _, _ = neo4j_cfg()
            cypher(run, container, f"MATCH (n) WHERE n.run = '{run.db}' DETACH DELETE n;", 'neo4j-cleanup')
            left = cypher(run, container, f"MATCH (n) WHERE n.run = '{run.db}' RETURN count(n) AS left;", 'neo4j-cleanup-check')
            result['neo4j_cleanup'] = left.strip().splitlines()[-1]
        except Exception as error:
            result['neo4j_cleanup'] = f'failed: {error}'
        run.finish_cleanup()
    result['evidence'] = str(run.directory)
    (run.directory / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
