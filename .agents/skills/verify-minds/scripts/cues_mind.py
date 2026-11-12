#!/usr/bin/env python3
"""Attention cues through a real mind (docs/ATTENTION.md): the living-mind binary against the
fake model, with its personal memory graph in Neo4j (cues reach the authority through the
memory's projection, as stances do).

  1. The `cues_on` law is set on the scratch world (`set_world_law`), and the mind's think prompt
     then offers the `notice` field and a `# What you watch for` section.
  2. W (one resident; the only mind) is asked to think. The fake model's think reply writes a
     stance and a cue on it: "a person whose name I do not know, within 10 m of me", with a `why`
     holding a unique word. The mind keeps it on the stance in Neo4j and projects it: the `cue`
     row appears through `mind_update`, watched, with the mind's words.
  3. A player P (whose name W does not know) walks up to W. The authority writes W one `noticed`
     experience quoting the `why` verbatim and asks W to think; the mind's next think request
     carries that line (the reason, in the journaled prompt), and its `# What you watch for`
     lists the cue as having made W think.

    python3 .agents/skills/verify-minds/scripts/cues_mind.py --run minds-cues-$(date +%Y%m%d-%H%M%S)

Environment: LIVING_STDB_CONTAINER/LIVING_STDB_URL (the server), LIVING_PRIVACY_NEO4J
(`container:bolt-host:port`, e.g. `slop-trials-neo4j:127.0.0.1:7699`) and
LIVING_PRIVACY_NEO4J_ENV (a file holding LIVING_NEO4J_PASSWORD=..., never printed), as
privacy.py. Nodes are written under this run's own name and deleted at the end.
"""
import argparse
import importlib.util
import json
import random
import sys
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pv = load('privacy')
vm = pv.vm


def scene(run, args):
    container, uri, pw = pv.neo4j_cfg()
    run.harness('launch')
    run.harness('doctor')
    run.admin('set_world_law', 'cues_on', 'true')
    laws = {r['name']: r['value'] for r in run.private('SELECT * FROM world_law', 'world-law')}
    assert laws.get('cues_on') == 'true', laws
    people = sorted(run.sql("SELECT * FROM character WHERE kind = 'person'", 'people'), key=lambda p: p['id'])
    w = next(p for p in people if p['ai'] and p['alive'] and p['stage'] == 2)['id']
    word = f'heron{random.randrange(10**6, 10**7)}'
    why = f'verify minds: my own words for watching, {word}'
    script = {'replies': {
        'think': {'thought': 'I will keep an eye out.', 'intend': ['wait'], 'say': None,
                  'judgments': [{'key': 'verify_watch', 'value': 0.9, 'why': 'verify minds fixture'}],
                  'notice': [{'for': 'verify_watch', 'who': 'unknown', 'near_me': 10, 'why': why}]},
        'deliberate': vm.basic_reply(),
        'talk': {'thought': 'I answer.', 'say': None, 'end': True},
        'consolidate': {'summary': 'verify cues summary', 'remember': [], 'nodes': [], 'edges': [], 'retract': [], 'merge': [],
                        'identity': None, 'relations': [], 'judgments': [], 'places': []}}}
    models = vm.model(run, script)
    for p in people:
        if p['ai'] and p['alive']:
            run.admin('set_behavior', p['id'], json.dumps({'wait': 300}))
    x0, y0 = pv.quiet_spot(run, 14, 40)
    run.admin('place_at', w, x0 + 1, y0)
    run.start(models, [w], extra_env={'LIVING_NEO4J': 'on', 'LIVING_NEO4J_URI': uri, 'LIVING_NEO4J_PASSWORD': pw})
    time.sleep(3)
    # 1-2. W thinks; its reply's cue is kept on the stance and projected.
    run.request(w, 'cues-think')
    cue = run.wait(lambda: [c for c in run.private(f'SELECT * FROM cue WHERE actor = {w}', 'cue') if c['why'] == why], 'the projected cue', 90)
    ok_cue = len(cue) == 1 and cue[0]['refused'] == '' and cue[0]['who'] == 'unknown' and cue[0]['for_key'] == 'stance:verify_watch'
    # 3. A player W does not know walks up.
    t0 = max(r['last_ms'] for r in run.private('SELECT last_ms FROM clock', 'clock'))
    player = pv.Person(run, 'CueStranger')
    run.admin('place_at', player.id, x0 + 4, y0)
    seen = run.wait(lambda: [e for e in run.private(f'SELECT * FROM experience WHERE observer = {w}', 'experience-w') if e['kind'] == 'noticed' and e['at_ms'] >= t0], 'the noticed line', 30)
    ok_line = seen[0]['subject'] == player.id and f'"{why}"' in seen[0]['text']

    def think_prompts():
        out = []
        for path in run.journal.glob('*.jsonl'):
            for line in path.read_text().splitlines():
                e = json.loads(line)
                if e.get('purpose') != 'think':
                    continue
                text = ''
                for m in (e.get('request') or {}).get('messages', []):
                    ref = m.get('content_ref')
                    text += m.get('content', '') if isinstance(m.get('content'), str) else ''
                    if ref and (run.journal / ref).exists():
                        text += (run.journal / ref).read_text()
                out.append(text)
        return out
    asked = run.wait(lambda: [t for t in think_prompts() if f'"{why}"' in t and 'You notice' in t], 'a think request carrying the noticed line', 90)
    fired = run.private(f'SELECT * FROM cue WHERE actor = {w}', 'cue-after')
    all_prompts = think_prompts()
    ok_field = any('"notice": [' in t for t in all_prompts) and any('# What you watch for' in t for t in all_prompts)
    ok_listed = any('made you think' in t and why in t for t in all_prompts)
    (run.directory / 'cues.json').write_text(json.dumps({'watcher': w, 'player': player.id, 'why': why, 'cue': cue, 'noticed': seen, 'cue_after': fired,
                                                         'think_prompts': len(all_prompts)}, indent=2))
    checks = {
        'the reply\'s cue is projected through mind_update, watched, in the mind\'s words': ok_cue,
        'a player W does not know, coming within 10 m, gives one noticed line quoting the why': ok_line,
        'the next think request carries the line as its reason': bool(asked),
        'the think prompt offers the notice field and # What you watch for (law on)': ok_field,
        'and lists the cue as having made W think': ok_listed,
        'the cue counts its fire': bool(fired) and fired[0]['fires'] >= 1,
    }
    status = 'pass' if all(checks.values()) else 'fail'
    return {'status': status, 'checks': checks}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', required=True, help='a new run name starting with minds-')
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
            container, _, _ = pv.neo4j_cfg()
            pv.cypher(run, container, f"MATCH (n) WHERE n.run = '{run.db}' DETACH DELETE n;", 'neo4j-cleanup')
            left = pv.cypher(run, container, f"MATCH (n) WHERE n.run = '{run.db}' RETURN count(n) AS left;", 'neo4j-cleanup-check')
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
