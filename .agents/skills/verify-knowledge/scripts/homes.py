#!/usr/bin/env python3
"""Someone's home, learned while they are away and recalled when they come by (house-owner-label,
docs/PERCEPTION.md "Whose a thing is"; docs/IDEAS_AUDITS.md §2), down to the memory graph.

A mind M (the living-mind binary against the fake model, its memory in Neo4j) and a neighbour F,
both residents. An overlay of the world's script makes anyone past 4 m too far away to make out
(as Cullet's `perceived_of` past 24 m).

1. F puts up a house at a quiet spot while M is 40 m off; F then comes to M and tells it its name
   ("I'm <F>", an `introduced` row), and goes 40 m off.
2. M is brought beside the house: what it notices names the owner ("You notice a house built by
   <F>"), though F is too far away to make out.
3. M's consolidation (the fake model's patch, citing the lines) keeps the house as a place,
   "<F>'s house" at its position, and `person:<F> -LIVES_AT-> place:verify_home_f`; the place is
   projected to M's `place` rows and the edge is in Neo4j.
4. F comes within 2 m and M is asked to think: its prompt's recall ("What comes to mind") brings
   back that F lives at "<F>'s house", cued by F in sight.

    homes.py --run minds-homes-<x>

Environment as `verify-minds/scripts/privacy.py` (LIVING_STDB_*, LIVING_PRIVACY_NEO4J,
LIVING_PRIVACY_NEO4J_ENV). Writes `<run>/homes.json`. The world's script is installed again at the
end, and the run's Neo4j nodes deleted.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('privacy', HERE.parent.parent / 'verify-minds/scripts/privacy.py')
pv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pv)
vm = pv.vm
ROOT = vm.ROOT
FAR_LAW = 'fn perceived_of(p) { let r = base_perceived_of(p); if !p.self && p.dist > 4.0 { r.name = false; r.health = "none"; r.far = true; } r }'


def scene(run, args):
    container, uri, pw = pv.neo4j_cfg()
    run.harness('launch')
    run.harness('doctor')
    people = sorted(run.sql("SELECT * FROM character WHERE kind = 'person'", 'people'), key=lambda p: p['id'])
    adults = [p for p in people if p['ai'] and p['alive'] and p['stage'] == 2][:2]
    m, f = (p['id'] for p in adults)
    fname = next(p['name'] for p in adults if p['id'] == f)
    for who in (m, f):
        run.admin('set_behavior', who, json.dumps({'wait': 300}))
    base = run.private('SELECT source FROM script', 'script')[0]['source']
    (run.directory / 'homes-overlay.rhai').write_text(base.replace('fn perceived_of(p)', 'fn base_perceived_of(p)', 1) + '\n' + FAR_LAW + '\n')
    subprocess.run([sys.executable, str(ROOT / 'living/tools/install_script.py'), run.db, str(run.directory / 'homes-overlay.rhai')], check=True, cwd=ROOT, capture_output=True, timeout=120)
    clock = lambda label: max(r['last_ms'] for r in run.private('SELECT last_ms FROM clock', label))
    try:
        x0, y0 = pv.quiet_spot(run, 12, 50)
        y0 = max(y0, 8.0)
        run.admin('place_at', m, x0, y0 + 40)
        run.admin('place_at', f, x0, y0)
        run.admin('place_structure', f, 'house')
        house = max((s for s in run.sql(f'SELECT * FROM structure WHERE owner = {f}', 'f-structures') if s['kind'] == 'house'), key=lambda s: s['id'])
        hx, hy = house['x'], house['y']
        patch = {'summary': 'verify homes', 'remember': [{'exp': '$EXP:verify homes', 'gist': '$EXPTEXT:verify homes', 'salience': 0.8, 'involves': [f'person:{f}']}],
                 'nodes': [{'key': 'place:verify_home_f', 'labels': ['Place', 'House'], 'name': f"{fname}'s house", 'props': {'x': hx, 'y': hy}}],
                 'edges': [{'from': f'person:{f}', 'rel': 'LIVES_AT', 'to': 'place:verify_home_f', 'confidence': 0.9}],
                 'retract': [], 'merge': [], 'identity': None, 'relations': [], 'judgments': [], 'places': [{'name': f"{fname}'s house", 'x': hx, 'y': hy}]}
        script = {'replies': {'think': {'thought': 'I wait.', 'intend': ['wait'], 'say': None}, 'deliberate': vm.basic_reply(),
                              'talk': {'thought': 'A neighbour.', 'say': None, 'end': True}, 'consolidate': patch},
                  'rules': [{'purpose': 'consolidate', 'cite': True, 'times': -1}]}
        run.start(vm.model(run, script), [m], extra_env={'LIVING_NEO4J': 'on', 'LIVING_NEO4J_URI': uri, 'LIVING_NEO4J_PASSWORD': pw})
        # 1. F tells M its name, beside M, and goes off.
        run.admin('place_at', f, x0 + 1.5, y0 + 40)
        time.sleep(1.5)
        thought = {'kind': 'talk', 'summary': 'verify homes line', 'detail': '', 'latency_ms': 0, 'tokens': 0, 'model': '', 'reference': ''}
        for text in (f"I'm {fname}. verify homes.", 'verify homes: the house by the open ground is mine.', 'verify homes: good day to you.'):
            run.admin('mind_say', f, text, m, 'say', 0, thought)
            time.sleep(2.6)
        run.admin('place_at', f, x0, y0 + 80)
        # 2. M beside the house, F 40 m off.
        t1 = clock('clock-1')
        run.admin('place_at', m, hx + 1.5, hy + 1.0)
        time.sleep(3)
        noticed = [e['text'] for e in run.private(f'SELECT * FROM experience WHERE observer = {m}', 'experiences-m') if e['at_ms'] >= t1 and 'house' in e['text']]
        # 3. The consolidation keeps the home.
        run.wait(lambda: any(t['kind'] == 'consolidate' and t['at_ms'] >= t1 - 20000 for t in run.private(f'SELECT * FROM thought WHERE actor = {m}', 'thoughts-m')), 'M consolidates', args.wait)
        time.sleep(3)
        places = [p for p in run.private(f'SELECT * FROM place WHERE actor = {m}', 'places-m') if p['name'] == f"{fname}'s house"]
        edge = pv.cypher(run, container, f"MATCH (a {{run: '{run.db}', actor: {m}, key: 'person:{f}'}})-[r:LIVES_AT]->(b {{key: 'place:verify_home_f'}}) RETURN b.name AS name, b.x AS x, b.y AS y;", 'neo4j-lives-at')
        # 4. F comes by; M thinks; recall brings the home back.
        run.admin('place_at', f, hx + 3.0, hy + 1.0)
        time.sleep(2)
        run.request(m, 'homes recall')
        sent = lambda e: '\n'.join(str(x.get('content', '')) for x in e['body'].get('messages', []))
        prompt = run.wait(lambda: [sent(e) for e in vm.shared.rows(run.directory / 'fake-requests.jsonl') if e['purpose'] == 'think' and 'verify homes recall' in sent(e)], 'the recall prompt', 60)[0]
        (run.directory / 'prompt-homes.txt').write_text(prompt)
        i = prompt.find('# What comes to mind')
        block = prompt[i:prompt.find('\n# ', i + 5)] if i >= 0 else ''
        recalled = [l for l in block.split('\n') if 'LIVES_AT' in l]
        checks = {
            'M notices the house built by F while F is too far to make out': any(f'house built by {fname}' in t for t in noticed),
            'the home is projected as M\'s place, at the house': bool(places) and abs(places[0]['x'] - hx) < 1.5 and abs(places[0]['y'] - hy) < 1.5,
            'Neo4j keeps person:F -LIVES_AT-> the house': f"{fname}'s house" in edge,
            'F in sight brings back where F lives': any(fname in l and f"{fname}'s house" in l for l in recalled),
        }
    finally:
        subprocess.run([sys.executable, str(ROOT / 'living/tools/install_script.py'), run.db], cwd=ROOT, capture_output=True, timeout=120)
    for k, v in checks.items():
        print(('PASS ' if v else 'FAIL ') + k, flush=True)
    (run.directory / 'homes.json').write_text(json.dumps({'m': m, 'f': f, 'name': fname, 'house': [hx, hy], 'noticed': noticed, 'places': places,
                                                          'edge': edge, 'recalled': recalled, 'checks': checks}, indent=2, ensure_ascii=False))
    return {'status': 'pass' if all(checks.values()) else 'fail', 'checks': checks}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True, help='a new run name starting with minds-')
    ap.add_argument('--wait', type=float, default=200)
    args = ap.parse_args()
    run = vm.Run(args.run)
    try:
        result = scene(run, args)
    except Exception as error:
        (run.directory / 'failure.txt').write_text(traceback.format_exc())
        result = {'status': 'fail', 'error': f'{type(error).__name__}: {error}'}
    finally:
        try:
            container, _, _ = pv.neo4j_cfg()
            pv.cypher(run, container, f"MATCH (n) WHERE n.run = '{run.db}' DETACH DELETE n;", 'neo4j-cleanup')
            result['neo4j_cleanup'] = pv.cypher(run, container, f"MATCH (n) WHERE n.run = '{run.db}' RETURN count(n) AS left;", 'neo4j-cleanup-check').strip().splitlines()[-1]
        except Exception as error:
            result['neo4j_cleanup'] = f'failed: {error}'
        run.finish_cleanup()
    result['evidence'] = str(run.directory)
    (run.directory / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
