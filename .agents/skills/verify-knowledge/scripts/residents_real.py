#!/usr/bin/env python3
"""Paid tier for residents' minds (docs/SEEDED_LIVES.md): a scripted newcomer arrives in
Brackenford and asks residents for food, a bed and a lesson. Makes real model calls: run only
after the user authorizes it, with `--allow-live`.

A scratch island world and scratch Neo4j; the mind service runs with the models file as
shipped (`living/configs/models.json`: people think with its `people` mix), `LIVING_ONLY`
naming Brackenford's residents (every resident has a mind; the rest of the island lives on
its starting ways for this run), the level of detail on and player memory off (the newcomer
is a script, not a person). The newcomer is a player identity acting only through the player
reducers: it waits in the square a minute, then walks up to three residents at their posts
(admin `place_at` stands for the walk) and asks one for food, one for a bed, one for a
lesson, with one follow-up line each, and accepts a trade offered to it. Then it waits.

Report (`report.md`, `rows.json`, `cost.json`): every line the residents said to it, every
act aimed at it (gifts, trades, lessons, hosting) from the chronicle and the tables, the
thoughts of each resident it asked, and tokens and cost per model and purpose from the
journal.

    residents_real.py --allow-live --run knowledge-residents-real-<name> [--wait-s 240]
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('facts_mind', HERE / 'facts_mind.py')
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)
K, S, ROOT = W.K, W.S, W.ROOT
spec = importlib.util.spec_from_file_location('player_memory_real', HERE / 'player_memory_real.py')
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
# The keys live in the main checkout's environment file (a worktree has none); read into the
# mind's environment only, never written or logged.
ENV_FILES = [ROOT / '.env', Path.home() / 'dev/slop-art-online/.env']

ASKS = [
    ('food', "Good day. I've only just arrived and I have nothing to eat. Could you spare some food?",
     'Thank you. Is there work here for someone new?'),
    ('bed', 'Excuse me. I have no roof for tonight. Is there anywhere I could sleep?',
     "I'd be grateful. I can help with chores in return."),
    ('lesson', "Could you teach me something useful? I'd like to learn a trade here.",
     "I'll practise it. What should I start with?"),
]


def keys():
    out = {}
    for path in ENV_FILES:
        if path.exists():
            for line in path.read_text().splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    k, v = line.split('=', 1)
                    out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return out


class Real(W.Proof):
    def start_real_mind(self, only):
        login = subprocess.run([str(ROOT / 'living/tools/stdb'), 'login', 'show', '--token'], capture_output=True, text=True, check=True)
        tokens = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', login.stdout)
        assert len(tokens) == 1
        found = keys()
        if not found.get('MISTRAL_API_KEY'):
            raise RuntimeError('MISTRAL_API_KEY not found in the environment files')
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER='http://127.0.0.1:3300', LIVING_DB=self.db, LIVING_RUN=self.db,
                   LIVING_SEED='island', LIVING_MODELS=str(ROOT / 'living/configs/models.json'), LIVING_ONLY=','.join(map(str, only)), LIVING_TOKEN=tokens[0],
                   LIVING_NEO4J='on', LIVING_NEO4J_URI=self.state['uri'], LIVING_NEO4J_PASSWORD=self.state['password'],
                   LIVING_CONCURRENCY='16', LIVING_LOD='1', LIVING_PLAYER_MEMORY='0', MISTRAL_API_KEY=found['MISTRAL_API_KEY'],
                   RUST_LOG='info,neo4rs=warn,spacetimedb_sdk=warn')
        keep = ('LIVING_DB', 'LIVING_SEED', 'LIVING_ONLY', 'LIVING_MODELS', 'LIVING_LOD', 'LIVING_PLAYER_MEMORY', 'LIVING_CONCURRENCY')
        (self.directory / 'mind-environment.json').write_text(json.dumps({k: env[k] for k in keep}, indent=2))
        self.process('mind', [K.BUILD / 'release/living-mind'], env)
        self.wait(lambda: 'world subscribed:' in self.log(), 'mind subscription', 90)


def journal(p):
    return [json.loads(l) for path in p.journal.glob('*.jsonl') for l in path.read_text().splitlines() if l.strip()]


def drive(p, wait_s):
    p.harness('launch', '--seed', 'island', '--target-dir', str(ROOT / '.local/living/target-facts-island'))
    p.harness('doctor')
    p.start_neo4j()
    p.cargo(['build', '--release', '-p', 'living-mind'], 'mind-build.log')
    s = S.Session(p.name)
    me = s.ensure_player('Arlen')
    p.admin('set_weather', False, 3600)
    # Brackenford's square: the settlement whose community is Brackenford; its residents' minds.
    towns = {c['id']: c['name'] for c in p.sql('SELECT id, name FROM community', 'communities')}
    town = next(x for x in p.sql('SELECT * FROM settlement', 'settlements') if towns.get(x['community']) == 'Brackenford')
    only = sorted(m['member'] for m in p.sql('SELECT * FROM membership', 'memberships') if m['community'] == town['community'])
    p.start_real_mind(only)
    start_ms = int(time.time() * 1000)
    p.admin('place_at', me, town['x'] + 1.5, town['y'] + 1.5)
    s.step('arrived in Brackenford square', at=[town['x'], town['y']])
    time.sleep(60)
    asked, mine = [], {k['technique'] for k in p.knowledge(me, 'newcomer-know-how')}
    houses = p.sql("SELECT x, y FROM structure WHERE kind = 'house'", 'houses')
    for what, line, follow in ASKS:
        cands, bodies = W.residents_at_posts(p, s, (town['x'], town['y']), {me} | {a['id'] for a in asked})
        cands = [c for c in cands if W.dist(bodies[c['id']], (town['x'], town['y'])) <= town['radius_m']]
        if what == 'bed':
            cands = [c for c in cands if any(W.dist((h['x'], h['y']), (c['home_x'], c['home_y'])) <= 1.5 for h in houses)] or cands
        if what == 'lesson':
            cands = [c for c in cands if {k['technique'] for k in p.knowledge(c['id'], 'resident-know-how')} - mine] or cands
        c = cands[0]
        W.speak_to(p, s, me, c['id'], bodies[c['id']], line)
        s.step(f'asked for {what}', resident=c['id'], name=c['name'], line=line)
        asked.append({'id': c['id'], 'name': c['name'], 'asked': what, 'line': line, 'at_ms': int(time.time() * 1000)})
        end = time.monotonic() + 90
        answered = False
        while time.monotonic() < end:
            heard = [e for e in p.sql(f'SELECT * FROM experience WHERE observer = {me}', 'newcomer-heard') if e['subject'] == c['id'] and e['kind'] == 'speech']
            offers = [o for o in p.sql('SELECT * FROM trade_offer', 'offers') if o['to'] == me]
            for o in offers:
                s.call('human_act', [json.dumps({'do': 'accept', 'target': {'id': o['from']}})])
                s.step('accepted a trade', offer=o)
            if heard and not answered:
                answered = True
                time.sleep(3)
                s.call('human_say', [follow, c['id']])
                s.step('followed up', resident=c['id'], line=follow)
                end = min(end, time.monotonic() + 45)
            time.sleep(3)
    s.step('waits in the town', seconds=wait_s)
    time.sleep(wait_s)
    end_ms = int(time.time() * 1000)

    # Rows.
    names = {c['id']: c['name'] for c in p.sql("SELECT id, name FROM character WHERE kind = 'person'", 'names')}
    heard = [e for e in p.sql(f'SELECT * FROM experience WHERE observer = {me}', 'newcomer-experience') if e['at_ms'] >= start_ms]
    chronicle = [c for c in p.sql('SELECT * FROM chronicle', 'chronicle') if c['at_ms'] >= start_ms and me in (c['a'], c['b'])]
    thoughts = []
    for a in asked:
        thoughts += [dict(t, name=names.get(a['id'])) for t in p.sql(f"SELECT * FROM thought WHERE actor = {a['id']}", f"thoughts-{a['id']}")]
    rows = {'newcomer': me, 'town': town, 'asked': asked, 'steps': s.steps,
            'said_to_newcomer': [{'at_ms': e['at_ms'], 'by': names.get(e['subject']), 'id': e['subject'], 'text': e['text']} for e in heard if e['kind'] == 'speech'],
            'acts_toward_newcomer': [{'at_ms': c['at_ms'], 'kind': c['kind'], 'text': c['text']} for c in chronicle if c['kind'] != 'speech'],
            'guest': p.sql(f'SELECT * FROM guest WHERE guest = {me}', 'guest'),
            'know_how': p.knowledge(me, 'newcomer-know-how-end'),
            'inventory': p.sql(f'SELECT * FROM inventory WHERE owner = {me}', 'newcomer-inventory'),
            'minds': len(only),
            'thoughts': [{'actor': t['actor'], 'name': t['name'], 'kind': t['kind'], 'at_ms': t['at_ms'], 'summary': t['summary'], 'model': t['model'], 'reference': t['reference']} for t in thoughts],
            'start_ms': start_ms, 'end_ms': end_ms}
    (p.directory / 'rows.json').write_text(json.dumps(rows, indent=1))
    calls = [dict(e, usd=R.cost(e, False)) for e in journal(p) if e.get('purpose')]
    by = {}
    for e in calls:
        k = (e.get('model'), e.get('purpose'))
        b = by.setdefault(k, {'calls': 0, 'prompt': 0, 'cached': 0, 'completion': 0, 'usd': 0.0, 'latency_ms': [], 'errors': 0})
        b['calls'] += 1
        b['prompt'] += e.get('prompt_tokens') or 0
        b['cached'] += e.get('cached_tokens') or 0
        b['completion'] += e.get('completion_tokens') or 0
        b['usd'] += e['usd']
        b['latency_ms'].append(e.get('latency_ms') or 0)
        b['errors'] += 1 if e.get('error') else 0
    table = [{'model': m, 'purpose': pu, **{k: v for k, v in b.items() if k != 'latency_ms'}, 'p50_ms': sorted(b['latency_ms'])[len(b['latency_ms']) // 2]} for (m, pu), b in sorted(by.items(), key=lambda x: str(x[0]))]
    total = sum(e['usd'] for e in calls)
    (p.directory / 'cost.json').write_text(json.dumps({'calls': len(calls), 'usd': total, 'by_model_purpose': table, 'real_s': (end_ms - start_ms) / 1000}, indent=1))
    lines = [f'# Residents\' minds, real run {p.name}', '', f'Newcomer #{me} in Brackenford, {(end_ms - start_ms) / 1000:.0f} s; {len(only)} residents thought for; {len(calls)} model calls, ${total:.4f}.', '',
             '## What residents said to the newcomer', ''] + [f"- {x['by']} (#{x['id']}): {x['text']}" for x in rows['said_to_newcomer']] + \
            ['', '## Acts toward the newcomer', ''] + [f"- {x['kind']}: {x['text']}" for x in rows['acts_toward_newcomer']] + \
            ['', f"Guest: {rows['guest']}", f"Know-how: {[k['technique'] + ' (' + k['source'] + ')' for k in rows['know_how']]}", '',
             '## Cost by model and purpose', '', '| model | purpose | calls | prompt | cached | completion | p50 ms | USD |', '|---|---|---:|---:|---:|---:|---:|---:|'] + \
            [f"| {t['model']} | {t['purpose']} | {t['calls']} | {t['prompt']} | {t['cached']} | {t['completion']} | {t['p50_ms']} | {t['usd']:.4f} |" for t in table]
    (p.directory / 'report.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-live', action='store_true')
    parser.add_argument('--run', required=True)
    parser.add_argument('--wait-s', type=int, default=240)
    args = parser.parse_args()
    if not args.allow_live:
        sys.exit('paid tier: pass --allow-live once the user has authorized this run')
    if not args.run.startswith('knowledge-residents-real-'):
        sys.exit('run must start with knowledge-residents-real-')
    p = Real(args.run)
    error = None
    try:
        drive(p, args.wait_s)
    except BaseException as caught:
        error = caught
        (p.directory / 'failure.log').write_text(traceback.format_exc())
    finally:
        p.cleanup()
    if error:
        raise RuntimeError(f'real run failed; evidence in {p.directory}') from error


if __name__ == '__main__':
    main()
