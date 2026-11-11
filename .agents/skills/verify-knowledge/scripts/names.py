#!/usr/bin/env python3
"""Names are learned from what happened (docs/COMMUNICATION.md §6–7), down to the memory graph.

A mind (the living-mind binary against the fake model, its memory in Neo4j) meets a player:

1. the player greets it without a name: the mind's graph knows the player as "a stranger";
2. the player says its own name: the authority writes an `acquaintance` and an `introduced`
   row ("<Name> told you their name.", subject = the player), the mind's consolidation sees the
   line tagged `{<Name>=#id}`, keeps it as a memory involving `person:<id>`, and the person's
   node in the graph is named "<Name>" from then on (`name_people`, the authority's
   `knows_name`);
3. a bystander mind out of earshot learns nothing: no acquaintance, no `introduced` row, and
   its graph has no node naming the player.

    names.py --run minds-names-<x> [--name Mercy]

Environment as `verify-minds/scripts/privacy.py` (LIVING_STDB_*, LIVING_PRIVACY_NEO4J,
LIVING_PRIVACY_NEO4J_ENV). Writes `<run>/names.json`.
"""
import argparse
import importlib.util
import json
import re
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
TALK = pv.TALK


def scene(run, args):
    container, uri, pw = pv.neo4j_cfg()
    run.harness('launch')
    run.harness('doctor')
    people = sorted(run.sql("SELECT * FROM character WHERE kind = 'person'", 'people'), key=lambda p: p['id'])
    adults = [p for p in people if p['ai'] and p['alive'] and p['stage'] == 2][:2]
    mind, far = (p['id'] for p in adults)
    player = pv.Person(run, args.name)
    for who in (mind, far):
        run.admin('set_behavior', who, json.dumps({'wait': 120}))
    x0, y0 = pv.quiet_spot(run, 12, 30)
    run.admin('place_at', mind, x0 + 2, y0)
    run.admin('place_at', player.id, x0 + 4, y0)
    run.admin('place_at', far, x0 + 40, y0)
    script = {'replies': {'think': {'thought': 'I wait.', 'intend': ['wait'], 'say': None},
                          'deliberate': vm.basic_reply(),
                          'talk': {'thought': 'A greeting.', 'say': 'verify names: good day.', 'end': True},
                          'consolidate': {'summary': 'verify names', 'remember': [
                              {'exp': '$EXP:verify names', 'gist': '$EXPTEXT:verify names', 'salience': 0.8, 'involves': ['$PERSON']},
                              {'exp': '$EXP:told you their name', 'gist': '$EXPTEXT:told you their name', 'salience': 0.8, 'involves': ['$PERSON']}],
                              'nodes': [], 'edges': [{'from': 'self', 'rel': 'MET', 'to': '$PERSON', 'confidence': 0.8}],
                              'retract': [], 'merge': [], 'identity': None, 'relations': [], 'judgments': [], 'places': []}},
              'rules': [{'purpose': 'consolidate', 'cite': True, 'times': -1}]}
    models = vm.model(run, script)
    run.start(models, [mind, far], extra_env={'LIVING_NEO4J': 'on', 'LIVING_NEO4J_URI': uri, 'LIVING_NEO4J_PASSWORD': pw})
    clock = lambda label: max(r['last_ms'] for r in run.private('SELECT last_ms FROM clock', label))
    consolidated = lambda w, since: any(t['kind'] == 'consolidate' and t['at_ms'] >= since for t in run.private(f'SELECT * FROM thought WHERE actor = {w}', f'thoughts-{w}'))
    graph = lambda w, label: pv.cypher(run, container, f"MATCH (n) WHERE n.run = '{run.db}' AND n.actor = {w} AND n.key = 'person:{player.id}' RETURN n.name AS name;", label)
    # 1. A greeting without a name, and enough to integrate.
    t0 = clock('clock-0')
    for i in range(3):
        player.call('human_say', [f'verify names: hello there, line {i}.', mind])
        time.sleep(2.6)
    t1 = clock('clock-1')
    run.wait(lambda: consolidated(mind, t1), 'the mind integrates the stranger\'s lines', args.wait)
    time.sleep(3)
    before = graph(mind, 'neo4j-person-before')
    # 2. The player says its name.
    player.call('human_say', [f'I am {args.name}, verify names.', mind])
    time.sleep(1.5)
    intro = [e for e in run.private(f'SELECT * FROM experience WHERE observer = {mind}', 'introduced') if e['kind'] == 'introduced']
    acq = [a for a in run.private('SELECT * FROM acquaintance', 'acquaintance') if a['known'] == player.id]
    for i in range(2):
        time.sleep(2.6)
        player.call('human_say', [f'verify names: and another line {i}.', mind])
    t2 = clock('clock-2')
    run.wait(lambda: consolidated(mind, t2), 'the mind integrates the introduction', args.wait)
    time.sleep(3)
    after = graph(mind, 'neo4j-person-after')
    memories = pv.cypher(run, container, f"MATCH (m:Memory) WHERE m.run = '{run.db}' AND m.actor = {mind} RETURN m.gist AS gist;", 'neo4j-memories')
    far_graph = graph(far, 'neo4j-far')
    requests = list(vm.shared.rows(run.directory / 'fake-requests.jsonl'))
    tagged = any(e['purpose'] == 'consolidate' and f'{args.name} told you their name. {{{args.name}=#{player.id}}}' in json.dumps(e['body'], ensure_ascii=False) for e in requests)
    checks = {
        'before the name the graph knows the player as a stranger': 'a stranger' in before and args.name not in before,
        'one introduced row, subject the player': len(intro) == 1 and intro[0]['subject'] == player.id and intro[0]['text'] == f'{args.name} told you their name.',
        'one acquaintance, the mind\'s; none for the mind out of earshot': [a['observer'] for a in acq] == [mind],
        'consolidation sees the introduction tagged with the person': tagged,
        'the memory keeps the introduction': f'{args.name} told you their name.' in memories,
        'after it, the person\'s node is named': args.name in after,
        'the mind out of earshot has no node naming the player': args.name not in far_graph,
    }
    for k, v in checks.items():
        print(('PASS ' if v else 'FAIL ') + k, flush=True)
    (run.directory / 'names.json').write_text(json.dumps({'name': args.name, 'mind': mind, 'far': far, 'player': player.id, 'checks': checks,
        'graph_before': before, 'graph_after': after, 'memories': memories}, indent=2))
    return {'status': 'pass' if all(checks.values()) else 'fail', 'checks': checks}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True, help='a new run name starting with minds-')
    ap.add_argument('--name', default='Mercy')
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
