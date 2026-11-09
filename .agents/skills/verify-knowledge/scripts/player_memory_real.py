#!/usr/bin/env python3
"""Paid tier for player memory (docs/PLAYER_MEMORY.md): one scripted session, internalized by
candidate models, direct and through the provider's batch API. Makes real model calls: run
only after the user authorizes it, with `--allow-live`.

1. **session**: a scratch island world; a minded resident thinks with the models file's
   default; the player (switch off) walks, gathers, talks, waves and fights a wolf.
2. **candidates**: one mind service per (model, mode), all at once, each with its own
   `LIVING_RUN` (Neo4j namespace and journal), `LIVING_ONLY=<player>` (no AI character) and
   the switch on, internalizes the same lived experience rows.
3. **score**: each candidate's graph against the session's rows (`fidelity.json`), tokens and
   cost from the journals (`cost.json`), `report.md`.

    player_memory_real.py --allow-live --run knowledge-pmem-real-<name> \
        [--models ministral-14b,glm-flash,deepseek-flash] [--modes direct,batch] [--batch-wait-s 2400]
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('player_memory', HERE / 'player_memory.py')
PM = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PM)
K, S, ROOT = PM.K, PM.S, PM.ROOT

# USD per million tokens (input, cached input, output), from docs.mistral.ai/models/<model>
# on 2026-11-09; the batch API is half price (mistral.ai/pricing FAQ). Ministral 3 14B lists no
# cached price, so cached input is charged as input.
PRICES = {'zai-glm-5-3-flash': (0.15, 0.03, 0.5), 'deepseek-v4-1-flash-1017': (0.3, 0.007, 1.2),
          'ministral-14b-latest': (0.2, 0.2, 0.2), 'ministral-8b-latest': (0.15, 0.15, 0.15), 'mistral-large-4': (0.7, 0.07, 2.1)}
BATCH_DISCOUNT = 0.5
INTENT = re.compile(r"\b(wants?|wanted|wish\w*|decid\w*|intend\w*|plann\w*|hop(e|es|ed|ing)|curious|eager\w*|determin\w*|"
                    r"because i|felt|feel(s|ing)?|afraid|fear\w*|happy|relieved|nervous|anxious|worried|excited|grateful|lonely|brave\w*)\b", re.I)


def cost(entry, batch):
    pin, pcached, pout = PRICES.get(entry.get('model'), (0, 0, 0))
    prompt = entry.get('prompt_tokens') or 0
    cached = entry.get('cached_tokens') or 0
    out = entry.get('completion_tokens') or 0
    usd = ((prompt - cached) * pin + cached * pcached + out * pout) / 1e6
    return usd * (BATCH_DISCOUNT if batch else 1.0)


def facts(session, resident_name):
    """What the session's rows say happened, as checkable facts with the words that would show
    each in a memory (an automatic first pass; the report lists every memory for reading)."""
    exps = session['experiences']
    out = []
    kinds = {e['kind'] for e in exps}
    if any('gather' in e['text'] for e in exps):
        ok = [e for e in exps if 'gather' in e['text'] and '(+' in e['text']]
        out.append({'fact': 'gathered (' + ', '.join(re.findall(r'\(\+1 (\w+)\)', ' '.join(e['text'] for e in ok))) + ')' if ok else 'tried to gather and failed',
                    'words': ['gather', 'berr', 'wood', 'forag', 'bush', 'tree', 'pick']})
    said = [e['text'] for e in exps if e['kind'] == 'said']
    if any('food' in t.lower() for t in said):
        out.append({'fact': f'asked {resident_name} where to find food', 'words': ['food', 'eat', 'hungry']})
    if any('market' in t.lower() for t in said):
        out.append({'fact': 'asked the way to the market', 'words': ['market']})
    if 'speech' in kinds:
        out.append({'fact': f'{resident_name} answered (heard speech)', 'words': ['said', 'told', 'answered', 'replied', 'claimed', 'suggest', 'pointed', 'advised', 'direct']})
    if any('wave' in e['text'] for e in exps):
        out.append({'fact': f'waved at / greeted {resident_name}', 'words': ['wave', 'greet']})
    if 'attacked' in kinds:
        out.append({'fact': 'attacked by a wolf', 'words': ['wolf', 'wolves']})
        out.append({'fact': 'was hurt', 'words': ['damage', 'hurt', 'wound', 'injur', 'bitten', 'bit ', 'bleed']})
    out.append({'fact': f'knows {resident_name} (person anchor)', 'words': [f'person:{session["resident"]}']})
    out.append({'fact': 'where it happened (place or settlement)', 'words': ['place:', 'brackenford', 'shore', 'island']})
    return out


def graph_text(p, run, actor, label):
    f = f"{{run: '{run}', actor: {actor}}}"
    nodes = p.cypher(f'MATCH (n:Concept {f}) RETURN n.key AS key, labels(n) AS labels, n.name AS name, n.gist AS gist, n.lived_under AS lived_under ORDER BY key;', f'{label}-nodes').stdout
    edges = p.cypher(f'MATCH (n:Concept {f})-[r]->(m:Concept) WHERE coalesce(r.open, true) AND NOT type(r) IN ["INVOLVES", "GROUNDS"] '
                     f'RETURN n.key AS source, coalesce(r.rel, type(r)) AS rel, m.key AS target, r.confidence AS confidence, r.because AS because, r.lived_under AS lived_under, properties(r) AS props ORDER BY source, rel, target;', f'{label}-edges').stdout
    return nodes, edges


def score(p, label, run, session, resident_name, journal):
    nodes, edges = graph_text(p, run, session['player'], label)
    entries = [e for e in K.entries(journal) if e.get('purpose') == 'internalize']
    replies = [json.loads(e['reply']) if e.get('reply') else {} for e in entries]
    summary = ' '.join(r.get('summary', '') for r in replies if isinstance(r, dict))
    gists = [l for l in nodes.splitlines()[1:] if '"Memory"' in l]
    text = (nodes + edges + summary).lower()
    fs = facts(session, resident_name)
    found = [f for f in fs if any(w.lower() in text for w in f['words'])]
    belief_lines = [l for l in edges.splitlines()[1:] if l.strip()]
    # Inner states and reasons nobody perceived, in memories, beliefs and the summary
    # (FEELS and JUDGES are the projections' structure, not claims of feeling).
    claims = [l for l in gists + [l for l in belief_lines if '"FEELS"' not in l and '"JUDGES"' not in l] + [summary] if INTENT.search(l)]
    ungrounded = [l for l in belief_lines if re.search(r', \[\], ', l) or ', NULL, ' in l.split('"')[-1][:12]]
    provenance = all('human' in l for l in belief_lines) and all('human' in l for l in gists)
    return {'label': label, 'facts': len(fs), 'found': len(found), 'missing': [f['fact'] for f in fs if f not in found],
            'memories': len(gists), 'beliefs': len(belief_lines), 'intent_claims': claims, 'ungrounded': len(ungrounded),
            'provenance_human': provenance, 'summary': summary, 'nodes': nodes, 'edges': edges,
            'calls': len(entries), 'errors': [e['error'] for e in entries if e.get('error')]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', required=True)
    ap.add_argument('--allow-live', action='store_true')
    ap.add_argument('--models', default='ministral-14b,glm-flash,deepseek-flash')
    ap.add_argument('--modes', default='direct,batch')
    ap.add_argument('--batch-wait-s', type=float, default=2400)
    a = ap.parse_args()
    if not a.allow_live:
        sys.exit('paid model calls: pass --allow-live once the user has authorized this run')
    if not a.run.startswith('knowledge-pmem-real-'):
        sys.exit('run must start with knowledge-pmem-real-')
    p = PM.Proof(a.run, 'direct')
    started = []
    error = None
    try:
        p.harness('launch', '--seed', 'island')
        p.harness('doctor')
        p.start_neo4j()
        p.cargo(['build', '--release', '-p', 'living-mind'], 'mind-build.log')
        # No takeover while the candidates internalize (each would think for the character).
        p.takeover_after(3600)
        models = json.loads((ROOT / 'living/configs/models.json').read_text())
        (p.directory / 'models.json').write_text(json.dumps(models, indent=2))
        s = S.Session(p.name)
        player = s.ensure_player('Wren')
        p.admin('spawn_crowd', 1, True)
        resident = p.sql("SELECT id, name FROM character WHERE name = 'Walker1'", 'resident')[0]
        here = s.body(player)
        p.admin('place_at', resident['id'], here[0] + 1.6, here[1])
        p.admin('set_behavior', resident['id'], json.dumps({'wait': 120}))
        p.start_mind('mind-session', [resident['id']], on=False)
        t0 = int(time.time() * 1000)
        S.run_session(s, 'Wren', resident['id'])
        time.sleep(20)
        t1 = int(time.time() * 1000)
        session = {'player': player, 'resident': resident['id'], 'resident_name': resident['name'], 'start_ms': t0, 'end_ms': t1, 'steps': s.steps, **S.evidence(s, player)}
        (p.directory / 'session.json').write_text(json.dumps(session, indent=1))
        p.stop_mind('mind-session')

        # Candidates, all at once, each in its own memory namespace and journal.
        for m, mode in [(m, mode) for m in a.models.split(',') for mode in a.modes.split(',')]:
            label = f'cand-{m}-{mode}'
            run = f'{p.db}-{m}-{mode}'
            log = start_candidate(p, label, run, player, m, mode, a.batch_wait_s)
            started.append((m, mode, label, run, log))
        deadline = time.monotonic() + a.batch_wait_s + 120
        pending = {c[2] for c in started}
        while pending and time.monotonic() < deadline:
            for m, mode, label, run, log in started:
                if label in pending:
                    text = log.read_text()
                    # "internalized N lived experiences (" on success; the startup line
                    # "lived experience internalized up to" is not an answer.
                    if ' lived experiences (' in text or 'internalizing what' in text:
                        pending.discard(label)
            time.sleep(5)
        results, costs = [], []
        game_hours = (session['end_ms'] - session['start_ms']) / (720_000 / 24)
        for m, mode, label, run, log in started:
            journal = ROOT / '.local/living/journal' / run / 'Wren.jsonl'
            r = score(p, label, run, session, resident['name'], journal)
            r.update(model=m, mode=mode, done=label not in pending)
            results.append(r)
            for e in K.entries(journal):
                if e.get('purpose') == 'internalize':
                    costs.append({'label': label, 'model': e.get('model'), 'mode': mode, 'prompt_tokens': e.get('prompt_tokens'),
                                  'cached_tokens': e.get('cached_tokens'), 'completion_tokens': e.get('completion_tokens'),
                                  'tokens': e.get('tokens'), 'latency_ms': e.get('latency_ms'), 'usd': cost(e, mode == 'batch'),
                                  'tokens_per_game_hour': (e.get('tokens') or 0) / game_hours, 'error': e.get('error')})
        (p.directory / 'fidelity.json').write_text(json.dumps(results, indent=1))
        (p.directory / 'cost.json').write_text(json.dumps({'game_hours': game_hours, 'real_s': (session['end_ms'] - session['start_ms']) / 1000,
                                                           'experiences': len(session['experiences']), 'calls': costs}, indent=1))
        lines = [f"# Player memory, real models ({a.run})", '', f"Session: {len(session['experiences'])} experiences in {(session['end_ms'] - session['start_ms']) / 1000:.0f} s ({game_hours:.1f} game hours).", '']
        for r in results:
            c = [x for x in costs if x['label'] == r['label']]
            lines += [f"## {r['label']} ({'done' if r['done'] else 'NOT DONE'})", f"facts {r['found']}/{r['facts']} missing {r['missing']}; memories {r['memories']}, beliefs {r['beliefs']}, intent claims {len(r['intent_claims'])}, provenance human {r['provenance_human']}",
                      f"tokens {[x['tokens'] for x in c]} usd {sum(x['usd'] for x in c):.5f} errors {r['errors']}", '', 'Summary: ' + r['summary'], '', '```', r['nodes'], r['edges'], '```', '']
            if r['intent_claims']:
                lines += ['Intent claims:', *[f'- {x}' for x in r['intent_claims']], '']
        (p.directory / 'report.md').write_text('\n'.join(lines))
        print('\n'.join(l for l in lines if not l.startswith('"')))
    except BaseException as caught:
        error = caught
        (p.directory / 'failure.log').write_text(traceback.format_exc())
    finally:
        for m, mode, label, run, log in started:
            src = ROOT / '.local/living/journal' / run
            if src.exists():
                shutil.copytree(src, p.directory / 'journal' / run, dirs_exist_ok=True)
                shutil.rmtree(src)
        p.cleanup()
    if error:
        raise RuntimeError(f'real run failed; evidence in {p.directory}') from error


def start_candidate(p, label, run, player, model, mode, batch_wait_s):
    """A candidate mind: the switch on with one model and mode, its own LIVING_RUN (memory
    namespace and journal), thinking for no AI character (`LIVING_ONLY` is the player)."""
    import subprocess
    login = subprocess.run([str(ROOT / 'living/tools/stdb'), 'login', 'show', '--token'], capture_output=True, text=True, check=True)
    tokens = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', login.stdout)
    env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=os.environ.get('LIVING_STDB_URL', 'http://127.0.0.1:3300').rstrip('/'), LIVING_DB=p.db, LIVING_RUN=run,
               LIVING_SEED='island', LIVING_MODELS=str(p.directory / 'models.json'), LIVING_ONLY=str(player),
               LIVING_TOKEN=tokens[0], LIVING_NEO4J='on', LIVING_NEO4J_URI=p.state['uri'], LIVING_NEO4J_PASSWORD=p.state['password'],
               LIVING_CONCURRENCY='4', LIVING_LOD='0', LIVING_PLAYER_MEMORY='1', LIVING_PLAYER_MEMORY_EVERY_S='3',
               LIVING_PLAYER_MEMORY_MODE=mode, LIVING_PLAYER_MEMORY_MODEL=model, LIVING_PLAYER_MEMORY_POLL_S='15',
               LIVING_PLAYER_MEMORY_BATCH_WAIT_S=str(batch_wait_s), RUST_LOG='info,neo4rs=warn,spacetimedb_sdk=warn')
    keep = [k for k in env if k.startswith('LIVING_') and k not in ('LIVING_TOKEN', 'LIVING_NEO4J_PASSWORD')]
    (p.directory / f'{label}-environment.json').write_text(json.dumps({k: env[k] for k in keep}, indent=2))
    p.process(label, [K.BUILD / 'release/living-mind'], env)
    p.wait(lambda: 'world subscribed:' in (p.directory / f'{label}.log').read_text(), f'{label} subscription', 90)
    return p.directory / f'{label}.log'


if __name__ == '__main__':
    main()
