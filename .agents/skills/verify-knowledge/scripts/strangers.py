#!/usr/bin/env python3
"""Two strangers stay two people in memory, down to the graph (docs/PERCEPTION.md, "Minds use
the same projection"; the arrival batch ar2's "a stranger is several people").

A mind (the living-mind binary against the fake model, its memory in Neo4j) hears two players
it does not know by name, each saying something different:

1. stranger A says it teaches spearcraft, and the mind integrates it; then stranger B says it
   smokes fish, and the mind integrates that. The fake model writes both deeds under one
   description, `person:the_stranger`, as a model that folds "a stranger" together would.
   The graph must hold two person nodes, `person:<A>` "a stranger #<A>" and `person:<B>`
   "a stranger #<B>", each with its own deed and memory (the description anchored edge by
   edge, `memory::anchor_described`), and no node keyed by a description;
2. recall: B's integration prompt, cued by B, shows A's deed only as A's ("a stranger #<A>"),
   never as B's; a replay of recall cued by B and the words "a stranger" brings back none of
   A's beliefs, and every memory of A's deed it shows says it was A's;
3. A says its name ("I am Mercy"); the next integration, whose reply mentions no one, names
   A's node "Mercy" (`Store::rename_people`): the same node, its deed still on it, and B's node
   still "a stranger #<B>". The fake reply after B never cites the name, so nothing else could.

    strangers.py --run minds-strangers-<x> [--name Mercy]

Environment as `verify-minds/scripts/privacy.py` (LIVING_STDB_*, LIVING_PRIVACY_NEO4J,
LIVING_PRIVACY_NEO4J_ENV); `CARGO_TARGET_DIR` holds a release `living-mind` and builds the
recall replay. Writes `<run>/strangers.json`.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location('privacy', HERE.parent.parent / 'verify-minds/scripts/privacy.py')
pv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pv)
vm = pv.vm

EMPTY = {'nodes': [], 'retract': [], 'merge': [], 'identity': None, 'relations': [], 'judgments': [], 'places': []}


def deed(token, gist, rel):
    """A consolidation reply that keeps the line holding `token` and writes its deed under the
    description `person:the_stranger` (the gist does not repeat the token, so later prompts that
    recall it do not match this rule again)."""
    return {'summary': f'verify strangers {rel.lower()}', **EMPTY,
            'remember': [{'exp': f'$EXP:{token}', 'gist': gist, 'salience': 0.8}],
            'edges': [{'from': 'person:the_stranger', 'rel': rel, 'to': 'self', 'confidence': 0.8, 'because': [f'$EXP:{token}']}]}


def scene(run, args):
    container, uri, pw = pv.neo4j_cfg()
    run.harness('launch')
    run.harness('doctor')
    people = sorted(run.sql("SELECT * FROM character WHERE kind = 'person'", 'people'), key=lambda p: p['id'])
    mind = next(p for p in people if p['ai'] and p['alive'] and p['stage'] == 2)['id']
    a = pv.Person(run, args.name)
    b = pv.Person(run, 'Tamsin')
    run.admin('set_behavior', mind, json.dumps({'wait': 120}))
    x0, y0 = pv.quiet_spot(run, 12, 30)
    run.admin('place_at', mind, x0 + 2, y0)
    run.admin('place_at', a.id, x0 + 4, y0)
    run.admin('place_at', b.id, x0 + 2, y0 + 2)
    script = {'replies': {'think': {'thought': 'I wait.', 'intend': ['wait'], 'say': None},
                          'deliberate': vm.basic_reply(),
                          'talk': {'thought': 'A greeting.', 'say': 'verify strangers: good day.', 'end': True},
                          'consolidate': {'summary': 'verify strangers nothing', 'remember': [], 'edges': [], **EMPTY}},
              'rules': [{'purpose': 'consolidate', 'contains': 'fishbones', 'cite': True, 'times': -1,
                         'reply': deed('fishbones', 'A stranger told me they smoke fish.', 'SMOKES_FISH')},
                        {'purpose': 'consolidate', 'contains': 'spearcraft', 'cite': True, 'times': -1,
                         'reply': deed('spearcraft', 'A stranger told me they teach the spear.', 'TEACHES_SPEAR')}]}
    models = vm.model(run, script)
    run.start(models, [mind], extra_env={'LIVING_NEO4J': 'on', 'LIVING_NEO4J_URI': uri, 'LIVING_NEO4J_PASSWORD': pw})
    exps = lambda label: run.private(f'SELECT * FROM experience WHERE observer = {mind}', label)
    integrated = lambda ids: set(ids) <= {e for t in run.private(f'SELECT * FROM thought WHERE actor = {mind}', 'thoughts')
                                          if t['kind'] == 'consolidate' for e in json.loads(t['detail'] or '{}').get('experiences', [])}
    q = lambda query, label: pv.cypher(run, container, query, label)
    graph = f"run: '{run.db}', actor: {mind}"

    def say(who, words, label, marker, n=4):
        """`n` lines from `who`; the ids of the mind's rows holding `marker`, collected as they
        come (the authority drops integrated rows), and a wait until all are integrated."""
        lines = set()
        for i in range(n):
            who.call('human_say', [f'verify strangers: {words}, line {i}.', mind])
            time.sleep(2.6)
            lines |= {e['id'] for e in exps(f'exps-{label}') if marker(e)}
        lines |= set(run.wait(lambda: [e['id'] for e in exps(f'exps-{label}') if marker(e)] or None, f'{label} lines heard'))
        run.wait(lambda: integrated(lines), f'the mind integrates {label}', args.wait)
        return sorted(lines)

    # The mind first integrates what it lived before it started (one batch), so each stranger's
    # lines below make an integration of their own (4 lines: enough salience after the 90 s gap).
    run.wait(lambda: any(t['kind'] == 'consolidate' for t in run.private(f'SELECT * FROM thought WHERE actor = {mind}', 'thoughts')), 'the first integration', args.wait)
    # 1. Two strangers, two deeds, each integrated on its own.
    spear = say(a, 'I teach spearcraft', 'spearcraft', lambda e: 'spearcraft' in e['text'])
    fish = say(b, 'I smoke fishbones', 'fishbones', lambda e: 'fishbones' in e['text'])
    time.sleep(2)
    nodes = q(f"MATCH (n:Concept {{{graph}}}) WHERE n.key STARTS WITH 'person:' RETURN n.key AS key, n.name AS name ORDER BY key;", 'neo4j-people')
    deeds = q(f"MATCH (p:Concept {{{graph}}})-[r {{open: true}}]->(:Concept {{{graph}, key: 'self'}}) WHERE p.key STARTS WITH 'person:' RETURN p.key AS key, r.rel AS rel ORDER BY key;", 'neo4j-deeds')
    involves = q(f"MATCH (m:Memory {{{graph}}})-[:INVOLVES]->(p:Concept) WHERE p.key STARTS WITH 'person:' RETURN m.gist AS gist, p.key AS key ORDER BY gist;", 'neo4j-involves')
    pa, pb = f'person:{a.id}', f'person:{b.id}'
    rows = lambda text: [tuple(x.strip().strip('"') for x in l.split(',', 1)) for l in text.strip().splitlines()[1:]]
    named = dict(rows(nodes))
    did = rows(deeds)
    inv = rows(involves)
    # 2. Recall. B's integration prompt: A's deed, if recalled, is A's.
    requests = list(vm.shared.rows(run.directory / 'fake-requests.jsonl'))
    user = lambda e: '\n'.join(m['content'] for m in e['body']['messages'] if m['role'] == 'user')
    fish_prompts = [user(e) for e in requests if e['purpose'] == 'consolidate' and 'fishbones' in user(e)]
    (run.directory / 'fish-consolidation-prompt.txt').write_text(fish_prompts[0] if fish_prompts else '')
    # A's deed as recalled: its memory or its belief (not "You know how to: … spear").
    spear_lines = [l for p in fish_prompts for l in p.splitlines() if 'teach the spear' in l or 'TEACHES_SPEAR' in l]
    # A replay of recall from B with the words "a stranger".
    cases = [{'id': 'b-and-a-stranger', 'run': run.db, 'actor': mind, 'keys': [[pb, 1.0]], 'texts': [['a stranger is here; the stranger', 1.0]], 'budget': 12},
             {'id': 'a-stranger-only', 'run': run.db, 'actor': mind, 'keys': [], 'texts': [['the stranger', 1.0]], 'budget': 12}]
    path = run.directory / 'recall-cases.json'
    path.write_text(json.dumps(cases, indent=2))
    env = dict(os.environ, LIVING_NEO4J_URI=uri, LIVING_NEO4J_PASSWORD=pw, LIVING_RECALL_CASES=str(path))
    replay = subprocess.run(['cargo', 'test', '-p', 'living-mind', 'recall_replay', '--', '--ignored', '--nocapture'],
                            cwd=ROOT / 'living', env=env, capture_output=True, text=True, timeout=1200)
    (run.directory / 'recall_replay.log').write_text(replay.stdout + replay.stderr)
    by_id = {r['id']: r for r in (json.loads(l) for l in replay.stdout.splitlines() if l.startswith('{"actor"'))}
    from_b = by_id.get('b-and-a-stranger', {})
    # 3. A says its name; the next integration's reply mentions no one.
    a.call('human_say', [f'I am {args.name.split()[0]}, verify strangers.', mind])
    time.sleep(1.5)
    intro = say(a, 'and another word', 'intro', lambda e: e['kind'] == 'introduced' and e['subject'] == a.id, n=2)
    time.sleep(2)
    after = dict(rows(q(f"MATCH (n:Concept {{{graph}}}) WHERE n.key STARTS WITH 'person:' RETURN n.key AS key, n.name AS name ORDER BY key;", 'neo4j-people-after')))
    did_after = rows(q(f"MATCH (p:Concept {{{graph}}})-[r {{open: true}}]->(:Concept {{{graph}, key: 'self'}}) WHERE p.key STARTS WITH 'person:' RETURN p.key AS key, r.rel AS rel ORDER BY key;", 'neo4j-deeds-after'))
    intro_replies = [e for e in requests if e['purpose'] == 'consolidate']
    tag = lambda text, id: re.search(rf'#{id}\b', text) is not None
    checks = {
        'two person nodes, each named by its own description and id': named.get(pa) == f'a stranger #{a.id}' and named.get(pb) == f'a stranger #{b.id}',
        'no person node keyed by a description, none named for either player': all(re.fullmatch(r'person:\d+', k) for k in named) and not any(n in v for v in named.values() for n in (args.name, 'Tamsin')),
        'each deed on its own stranger': set(did) == {(pa, 'TEACHES_SPEAR'), (pb, 'SMOKES_FISH')},
        'each memory involves only its own stranger': set(inv) == {('A stranger told me they smoke fish.', pb), ('A stranger told me they teach the spear.', pa)},
        'B\'s integration recalls A\'s deed only as A\'s': bool(fish_prompts) and bool(spear_lines) and all(tag(l, a.id) and not tag(l, b.id) for l in spear_lines),
        'recall from B and "a stranger" brings back none of A\'s beliefs': bool(from_b) and not any(pa in f for f in from_b.get('facts', [])),
        'every recalled memory of A\'s deed says it was A\'s': bool(from_b) and all(tag(m, a.id) and not tag(m, b.id) for m in from_b.get('memories', []) if 'spear' in m),
        '"the stranger" alone cues nothing': by_id.get('a-stranger-only', {}).get('seeds') == 0,
        'after the introduction, A\'s node is named, the same node with its deed': after.get(pa) == args.name and (pa, 'TEACHES_SPEAR') in did_after and len(after) == len(named),
        'B stays a stranger': after.get(pb) == f'a stranger #{b.id}',
    }
    for k, v in checks.items():
        print(('PASS ' if v else 'FAIL ') + k, flush=True)
    (run.directory / 'strangers.json').write_text(json.dumps({'mind': mind, 'a': a.id, 'b': b.id, 'checks': checks, 'nodes': named, 'deeds': did,
        'involves': inv, 'spear_lines_in_b_prompt': spear_lines, 'replay': by_id, 'nodes_after': after, 'deeds_after': did_after,
        'experiences': {'spear': spear, 'fish': fish, 'intro': intro}, 'consolidations': len(intro_replies)}, indent=2))
    return {'status': 'pass' if all(checks.values()) else 'fail', 'checks': checks}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True, help='a new run name starting with minds-')
    ap.add_argument('--name', default='Mercy')
    ap.add_argument('--wait', type=float, default=300)
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
