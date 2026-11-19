#!/usr/bin/env python3
"""Prove that what a human-played character lives becomes its memory (docs/PLAYER_MEMORY.md).

Free tier: the real `living-mind` against the shared fake model server and a scratch Neo4j,
on a `verify-knowledge-*` island world. Phases:

The world's `takeover_s` law is raised to an hour (an installed copy of skills.rhai) so the player's
HTTP calls never let the minds take the character over, except where phase 2 lowers it.

1. **off**: the mind runs with `LIVING_PLAYER_MEMORY=0` while the player talks to a minded
   resident: no internalize request, no graph for the player, its experience rows untouched,
   the resident's conversation and consolidation as before.
2. **on**: the mind restarts with the switch on; the scripted session (walk, gather, talk, wave,
   fight a wolf) runs; then `takeover_s` drops to 5 s, the player stays away, and the world's
   minds take the character over (the presence signal): that ends the session and internalizes
   it: the request carries only the player's experience lines; the graph holds memories and
   beliefs with `lived_under = human` and `self.lived_upto`; relations, judgments, places and the
   identity inferred from the person's conduct are projected; the player's experience rows
   remain. The taken-over character's first deliberation comes after the internalization, and
   what it then lives is consolidated with `lived_under = ai`.
3. **restart**: the mind is stopped, the player acts again, the mind starts again: the next
   internalization takes only experiences after `lived_upto`.
4. **recall**: the resident's own memory of the player comes back in its talk prompt and its
   recall; the player's private memories (the wolf fight the resident never saw) do not; the
   player's own recall (as a mind taking it over would see it) returns them. Tokens measured.
5. **death**: the player speaks and is killed (admin `kill`); the authority deletes its rows,
   and the service's buffer still integrates the last words (cadence reason "death").

    player_memory.py run --run knowledge-pmem-<name> [--mode direct|batch]
    player_memory.py cleanup --run knowledge-pmem-<name>
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import urllib.request

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('verify_knowledge', HERE / 'verify_knowledge.py')
K = importlib.util.module_from_spec(spec)
spec.loader.exec_module(K)
spec = importlib.util.spec_from_file_location('player_session', HERE / 'player_session.py')
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
ROOT = K.ROOT

IDENTITY = {'narrative': 'I came to the island a stranger, asked my way to food and fought off a wolf.', 'values': ['asking before guessing'],
            'traits': {'boldness': 70, 'caution': 45}, 'mood': 'wary', 'why': 'I stood my ground against a wolf and asked for directions.'}
INTERNALIZE = {
    'summary': 'I arrived, gathered wood and berries, spoke with a resident and was attacked by a wolf.',
    'identity': IDENTITY,
    'remember': [{'exp': '$EXP:gather', 'gist': 'I went gathering soon after I arrived.'},
                 {'exp': '$EXP:you said to', 'gist': 'I asked a resident where to find food.'},
                 # GLM-shaped: the id as a string (docs/MODEL_COST.md, Part 2); it must be kept.
                 {'exp': '$EXPSTR:wolf attacked you', 'gist': 'A wolf attacked me out in the wilds and I struck back.'}],
    'nodes': [{'key': 'kind:wolf', 'labels': ['Danger'], 'name': 'wolf'}],
    'edges': [{'from': 'self', 'rel': 'WENT_GATHERING', 'to': 'kind:berry_bush', 'confidence': 0.9, 'because': ['$EXP:gather']},
              {'from': 'self', 'rel': 'ASKED_ABOUT_FOOD', 'to': '$PERSON', 'confidence': 0.9, 'because': ['$EXP:you said to']},
              {'from': 'kind:wolf', 'rel': 'ATTACKED', 'to': 'self', 'confidence': 0.95, 'because': ['$EXPSTR:wolf attacked you']},
              # A model slip: someone the player never perceived (an islander far away).
              {'from': 'self', 'rel': 'SAW', 'to': 'person:1', 'confidence': 0.5, 'because': ['$EXP:wolf attacked you']}],
    'relations': [{'id': '$PERSON_IDSTR', 'trust': 20, 'affinity': 25, 'label': 'acquaintance', 'note': 'answered when I spoke'}],
    'judgments': [{'key': 'wolves_attack_newcomers', 'value': 0.8, 'why': 'a wolf attacked me'}],
    'places': [{'name': 'Wolf ground', 'x': 500, 'y': 150}],
    'merge': [], 'retract': [],
}
RESIDENT = {
    'summary': 'A newcomer spoke to me.',
    'remember': [{'exp': '$EXP:said to you', 'gist': 'A newcomer named Wren greeted me and asked where to find food.'}],
    'nodes': [], 'edges': [{'from': 'self', 'rel': 'MET', 'to': '$PERSON', 'confidence': 0.8, 'because': ['$EXP:said to you']}],
    'relations': [{'id': '$PERSON_ID', 'trust': 10, 'affinity': 20, 'label': 'newcomer', 'note': 'asked me about food'}],
    'judgments': [], 'places': [], 'merge': [], 'retract': [], 'identity': None,
}
PRIVATE = 'A wolf attacked me out in the wilds'


class Proof(K.Run):
    def __init__(self, name, mode, existing=False):
        super().__init__(name, existing)
        self.mode = mode
        self.port = None
        self.mind = None

    def fake(self):
        script = {'rules': [{'purpose': 'internalize', 'cite': True, 'reply': INTERNALIZE, 'times': -1},
                            {'purpose': 'consolidate', 'cite': True, 'reply': RESIDENT, 'times': -1}]}
        (self.directory / 'fake-script.json').write_text(json.dumps(script, indent=2))
        self.process('fake', [sys.executable, K.FAKE, '--port', '0', '--log', self.directory / 'requests.jsonl', '--script', self.directory / 'fake-script.json'])
        self.wait(lambda: 'READY ' in (self.directory / 'fake.log').read_text(), 'fake model readiness', 10)
        self.port = int(re.search(r'READY http://127.0.0.1:(\d+)/v1', (self.directory / 'fake.log').read_text())[1])
        models = {'default': 'fake', 'profiles': {'fake': {'base_url': f'http://127.0.0.1:{self.port}/v1', 'model': 'pmem-local-fake',
                  'key_env': 'LIVING_VERIFY_FAKE_KEY', 'max_tokens': 2048,
                  'reasoning_effort': {p: p for p in ('think', 'deliberate', 'consolidate', 'talk', 'internalize')}}}}
        (self.directory / 'models.json').write_text(json.dumps(models, indent=2))

    def requests(self):
        return K.entries(self.directory / 'requests.jsonl')

    def start_mind(self, label, only, on):
        login = subprocess.run([str(ROOT / 'living/tools/stdb'), 'login', 'show', '--token'], capture_output=True, text=True, check=True)
        tokens = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', login.stdout)
        assert len(tokens) == 1
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=os.environ.get('LIVING_STDB_URL', 'http://127.0.0.1:3300').rstrip('/'), LIVING_DB=self.db,
                   LIVING_RUN=self.db, LIVING_SEED='island', LIVING_MODELS=str(self.directory / 'models.json'),
                   LIVING_ONLY=','.join(map(str, only)), LIVING_TOKEN=tokens[0], LIVING_NEO4J='on',
                   LIVING_NEO4J_URI=self.state['uri'], LIVING_NEO4J_PASSWORD=self.state['password'],
                   LIVING_VERIFY_FAKE_KEY='local-only', LIVING_LLM_PER_MIN='0', LIVING_CONCURRENCY='4',
                   LIVING_LOD='0', NO_PROXY='127.0.0.1,localhost', RUST_LOG='info,neo4rs=warn,spacetimedb_sdk=warn')
        env.pop('LIVING_PLAYER_MEMORY', None)
        if on:
            env.update(LIVING_PLAYER_MEMORY_MODE=self.mode, LIVING_PLAYER_MEMORY_POLL_S='0.5')
        else:
            env.update(LIVING_PLAYER_MEMORY='0')
        binary = K.BUILD / 'release/living-mind'
        keep = ('LIVING_DB', 'LIVING_RUN', 'LIVING_SEED', 'LIVING_ONLY', 'LIVING_NEO4J_URI', 'LIVING_MODELS', 'LIVING_LOD')
        (self.directory / f'{label}-environment.json').write_text(json.dumps({k: env.get(k) for k in keep + tuple(k for k in env if k.startswith('LIVING_PLAYER_MEMORY'))}, indent=2))
        self.mind = self.process(label, [binary], env)
        self.wait(lambda: 'world subscribed:' in (self.directory / f'{label}.log').read_text(), f'{label} subscription', 90)
        return self.directory / f'{label}.log'

    def stop_mind(self, label):
        owned = self.state['pids'].pop(label)
        os.kill(owned['pid'], 15)
        self.mind.wait(timeout=15)
        self.processes.remove(self.mind)
        self.save()

    def graph(self, actor, label):
        f = f"{{run: '{self.db}', actor: {actor}}}"
        nodes = self.cypher(f'MATCH (n:Concept {f}) RETURN n.key AS key, labels(n) AS labels, n.lived_under AS lived_under, n.lived_upto AS lived_upto, n.gist AS gist ORDER BY key;', f'{label}-nodes').stdout
        edges = self.cypher(f'MATCH (n:Concept {f})-[r]->(m:Concept) WHERE coalesce(r.open, true) RETURN n.key AS source, coalesce(r.rel, type(r)) AS rel, m.key AS target, r.lived_under AS lived_under, r.because AS because, r.thought AS thought ORDER BY source, rel, target;', f'{label}-edges').stdout
        return nodes, edges

    def takeover_after(self, secs):
        """Install skills.rhai with the `takeover_s` law set to `secs`."""
        source = (ROOT / 'living/scripts/skills.rhai').read_text()
        assert 'takeover_s: 30.0' in source
        self.admin('install_script', source.replace('takeover_s: 30.0', f'takeover_s: {float(secs)}'))

    def thoughts(self, actor, kind):
        return [t for t in self.sql(f'SELECT * FROM thought WHERE actor = {actor}', f'thought-{actor}') if t['kind'] == kind]


def internalize_requests(proof):
    return [r for r in proof.requests() if r['purpose'] == 'internalize']


def user_text(entry):
    return '\n'.join(m['content'] for m in entry['body']['messages'] if m['role'] == 'user')


def system_text(entry):
    return '\n'.join(m['content'] for m in entry['body']['messages'] if m['role'] == 'system')


def tokens(text):
    """Rough token count (4 characters a token) for budgets; the real tier reports provider counts."""
    return round(len(text) / 4)


def drive(p):
    p.harness('launch', '--seed', 'island')
    p.harness('doctor')
    p.start_neo4j()
    p.cargo(['build', '--release', '-p', 'living-mind'], 'mind-build.log')
    # A build tree outside the checkout (CARGO_TARGET_DIR) is named by its full path.
    hashes = {str(x.relative_to(ROOT) if x.is_relative_to(ROOT) else x): hashlib.sha256(x.read_bytes()).hexdigest()
              for x in [*sorted((ROOT / 'living/mind/src').rglob('*.rs')), K.BUILD / 'release/living-mind']}
    (p.directory / 'source-hashes.json').write_text(json.dumps(hashes, indent=2))
    p.fake()
    p.takeover_after(3600)
    s = S.Session(p.name)
    player = s.ensure_player('Wren')
    p.admin('spawn_crowd', 1, True)
    resident = p.sql("SELECT id FROM character WHERE name = 'Walker1'", 'resident')[0]['id']
    here = s.body(player)
    p.admin('place_at', resident, here[0] + 1.6, here[1])
    p.admin('set_behavior', resident, json.dumps({'wait': 120}))
    only = [resident, player]

    # 1. Switch off: the player talks; the resident answers; nothing of the player is internalized.
    log = p.start_mind('mind-off', only, on=False)
    s.call('human_say', ['Good day. Is this the way to the market?', resident])
    p.wait(lambda: any(r['purpose'] == 'talk' for r in p.requests()), 'resident conversation turn (switch off)', 60)
    time.sleep(25)
    text = log.read_text()
    assert 'player memory on' not in text
    assert not internalize_requests(p), 'internalize request with the switch off'
    nodes, _ = p.graph(player, 'off-player')
    assert nodes.count('\n') <= 1, f'player graph exists with the switch off: {nodes}'
    rows_off = p.sql(f'SELECT * FROM experience WHERE observer = {player}', 'off-player-experience')
    assert any(r['kind'] == 'said' for r in rows_off), 'the player perceives its own words'
    assert not p.thoughts(player, 'internalize')
    p.pass_feature('switch off: no player memory, residents unchanged', ['mind-off.log', 'requests.jsonl', 'off-player-nodes.txt', 'off-player-experience.json'],
                   talk_requests=sum(r['purpose'] == 'talk' for r in p.requests()))
    p.stop_mind('mind-off')

    # 2. Switch on (the default): the backlog and the scripted session are internalized when the
    # session ends, which is the world's minds taking the character over once its person left.
    log = p.start_mind('mind-on', only, on=True)
    assert 'player memory on' in log.read_text()
    me, _ = S.run_session(s, 'Wren', resident)
    assert me == player
    session = {'player': player, 'resident': resident, 'steps': s.steps, **S.evidence(s, player)}
    (p.directory / 'session.json').write_text(json.dumps(session, indent=1))
    p.takeover_after(5)
    taken = p.wait(lambda: [r for r in p.sql(f'SELECT * FROM presence WHERE id = {player}', 'presence-taken') if r['ai']], 'takeover after the person left', 30)[0]
    # The off phase's backlog may be internalized on its own first; the session follows.
    p.wait(lambda: any('wolf attacked you' in user_text(r) for r in internalize_requests(p)), 'session internalize request', 120)
    first = p.wait(lambda: len(p.thoughts(player, 'internalize')) >= len(internalize_requests(p)) and p.thoughts(player, 'internalize'), 'internalization at session end', 60)
    assert any(json.loads(t['detail'])['reason'] == 'session end' for t in first), [json.loads(t['detail'])['reason'] for t in first]
    # The taken-over character thinks only after its past is internalized.
    thought = p.wait(lambda: p.thoughts(player, 'deliberate'), 'the minds deliberate for the taken-over character', 120)
    assert min(t['at_ms'] for t in thought) > max(t['at_ms'] for t in first), 'deliberated before its lived past was internalized'
    req = internalize_requests(p)
    body = '\n'.join(user_text(r) for r in req)
    # The player was never told the resident's name: it is "a stranger" in what it lived
    # (the projection's label), anchored by id.
    for want in ('You said to a stranger', 'gather →', 'stranger said to you', 'wolf attacked you', '@[', f'someone=#{resident}'):
        assert want in body, f'{want!r} missing from the internalize request'
    # The player may say the name itself (its own words, as typed); nothing the authority told
    # it names the resident.
    told = [l for l in body.splitlines() if 'Walker1' in l and 'You said' not in l]
    assert not told, f'a name the player was never told reached its memory: {told}'
    for never in ('human_move', 'human_act', 'use_skill', 'my_combat', 'deliberation'):
        assert never not in body, f'{never!r} leaked into the internalize request'
    if p.mode == 'batch':
        assert all(r.get('batch_job') for r in req), 'batch mode sent a direct request'
    details = [json.loads(t['detail']) for t in first]
    assert all(d['lived_under'] == 'human' and d['mode'] == p.mode for d in details)
    upto = max(d['upto'] for d in details)
    nodes, edges = p.graph(player, 'on-player')
    assert 'human' in nodes and 'I went gathering soon after I arrived' in nodes and PRIVATE in nodes
    assert any(l.startswith('"self"') and str(upto) in l for l in nodes.splitlines()), nodes
    lived = [l for l in edges.splitlines() if 'ASKED_ABOUT_FOOD' in l or 'WENT_GATHERING' in l or 'ATTACKED' in l]
    assert len(lived) == 3 and all('human' in l for l in lived), lived
    # The wolf memory, its evidence and the relation came with ids written as strings (GLM's
    # shape): the memory is in the graph (PRIVATE above), the edge keeps its experience id.
    assert any('ATTACKED' in l and re.search(r'\[\d+', l) for l in lived), [l for l in lived if 'ATTACKED' in l]
    assert '"person:1"' not in nodes + edges, 'a person the player never perceived was written'
    assert any('person:1 dropped' in n for d in details for n in d['notes']), 'the dropped stranger is not noted'
    rel = p.sql(f'SELECT * FROM relation WHERE actor = {player}', 'on-player-relation')
    # The internalization's patch felt for the resident (its id given as a string); the projected
    # row may already carry what the minds made of it since the takeover (their consolidation).
    patches = [json.loads(t['detail'])['patch'] for t in first]
    assert any(e['rel'] == 'FEELS' and e['to'] == f'person:{resident}' for pt in patches for e in pt['edges']), 'the relation given with a string id was dropped'
    assert any(r['other'] == resident for r in rel) and not any(r['other'] == 1 for r in rel), rel
    assert any(r['key'] == 'wolves_attack_newcomers' for r in p.sql(f'SELECT * FROM judgment WHERE actor = {player}', 'on-player-judgment'))
    assert any(r['name'] == 'Wolf ground' for r in p.sql(f'SELECT * FROM place WHERE actor = {player}', 'on-player-place'))
    # What the player's character saw of resources (talk-places: its own looks, as a mind's) is in
    # what it internalizes, with when it was seen and no way from anywhere (no place to stand).
    stock = p.sql(f'SELECT * FROM seen_stock WHERE actor = {player}', 'on-player-seen-stock')
    assert stock, "the player's character remembers no resources"
    remembered = re.findall(r'^- (?:\d+ )?[a-z ]+ around \[-?\d+, -?\d+\]: (?:seen day \d+ \d\d:\d\d|gone when you were last here, day .*)$', body, re.M)
    assert remembered, 'no remembered resource in the internalize request'
    # The identity is inferred from the person's conduct (goals stay: nobody perceived them).
    persona = p.sql(f'SELECT * FROM persona WHERE id = {player}', 'on-player-persona')
    assert persona and persona[0]['narrative'] == IDENTITY['narrative'] and persona[0]['mood'] == 'wary' and persona[0]['goals'] == [], persona
    assert 'IDENTITY is the one place' in system_text(internalize_requests(p)[0]), 'the internalize prompt does not ask for an identity'
    # What the minds live for it is theirs: consolidated with `lived_under = ai`.
    ai_thought = p.wait(lambda: p.thoughts(player, 'consolidate'), 'consolidation of what the minds lived for it', 150)
    _, ai_edges = p.graph(player, 'taken-player')
    assert any('"ai"' in l for l in ai_edges.splitlines()), 'no edge lived under ai'
    assert all(set(json.loads(t['detail'])['experiences']).isdisjoint(json.loads(f['detail'])['experiences']) for t in ai_thought for f in first), 'an experience was integrated twice'
    p.takeover_after(3600)
    rows = p.sql(f'SELECT * FROM experience WHERE observer = {player}', 'on-player-experience')
    assert any(r['id'] <= upto for r in rows), 'player experience rows were consumed'
    p.pass_feature('switch on: session internalized with provenance and projections', ['mind-on.log', 'requests.jsonl', 'on-player-nodes.txt', 'on-player-edges.txt',
                   'on-player-relation.json', 'on-player-judgment.json', 'on-player-place.json', 'on-player-persona.json', 'on-player-experience.json', 'session.json',
                   'presence-taken.json', 'taken-player-edges.txt'],
                   upto=upto, requests=len(req), experiences_sent=len(re.findall(r'^- \[\d+\]', body, re.M)),
                   request_tokens=[tokens(system_text(r) + user_text(r)) for r in req], same_system_prompt=len({system_text(r) for r in req}) == 1)

    p.pass_feature('takeover: session end by presence, past first, identity inferred, lived under ai', ['presence-taken.json', 'thought-%d.json' % player, 'taken-player-edges.txt', 'on-player-persona.json'],
                   takeover_ms=taken['control_ms'], persona=persona[0]['narrative'])

    # 3. Restart: stop, act, start again; only experiences after `lived_upto` are taken.
    # (The first call hands the character back to its person.)
    p.stop_mind('mind-on')
    before = len(p.thoughts(player, 'internalize'))
    s.call('human_say', ['I am back. The wolves out there are dangerous.', resident])
    time.sleep(2.5)
    s.call('human_act', [json.dumps({'do': {'skill': 'gather', 'target': {'nearest': 'tree'}}})])
    time.sleep(9)
    # The session ends when the minds take the character over (5 s after its last call).
    p.takeover_after(5)
    log = p.start_mind('mind-restart', only, on=True)
    p.wait(lambda: 'internalized up to ' + str(upto) in log.read_text(), 'cursor read from the mind on restart', 60)
    second = p.wait(lambda: len(p.thoughts(player, 'internalize')) > before and p.thoughts(player, 'internalize'), 'internalization after restart', 120)
    later = json.loads(sorted(second, key=lambda t: t['id'])[-1]['detail'])
    assert later['experiences'] and min(later['experiences']) > upto, (upto, later['experiences'])
    p.takeover_after(3600)
    p.pass_feature('restart resumes from lived_upto (no re-integration)', ['mind-restart.log', 'thought-%d.json' % player], first_upto=upto, second=later['experiences'])

    # 4. Recall: the resident remembers the player from its own experience, never the player's.
    p.wait(lambda: [t for t in p.thoughts(resident, 'consolidate') if 'newcomer' in t['summary'].lower()], 'resident consolidation', 240)
    rnodes, redges = p.graph(resident, 'resident')
    assert 'A newcomer named Wren greeted me' in rnodes and 'human' not in rnodes + redges and PRIVATE not in rnodes
    sequence = max(r['sequence'] for r in p.requests())
    time.sleep(3)
    s.call('human_say', ['Walker1, do you remember me? We spoke about food.', resident])
    talk = p.wait(lambda: [r for r in p.requests() if r['sequence'] > sequence and r['purpose'] == 'talk'], 'resident talk turn about the player', 90)
    prompt = user_text(talk[0])
    (p.directory / 'resident-talk-prompt.txt').write_text(system_text(talk[0]) + '\n\n---\n\n' + prompt)
    assert 'A newcomer named Wren greeted me' in prompt, 'resident talk prompt lacks its own memory of the player'
    assert PRIVATE not in prompt and 'wolf attacked me' not in prompt.lower(), 'the player\'s private memory reached the resident'
    cases = [{'id': 'player-about-resident', 'run': p.db, 'actor': player, 'keys': [[f'person:{resident}', 1]], 'texts': [['food market', 0.6]], 'budget': 8},
             {'id': 'player-wolves', 'run': p.db, 'actor': player, 'keys': [['kind:wolf', 1]], 'texts': [['wolf', 0.8]], 'budget': 8},
             {'id': 'resident-about-player', 'run': p.db, 'actor': resident, 'keys': [[f'person:{player}', 1]], 'texts': [['wren', 0.8]], 'budget': 8},
             {'id': 'resident-wolves', 'run': p.db, 'actor': resident, 'keys': [['kind:wolf', 1]], 'texts': [['wolf', 0.8]], 'budget': 8}]
    path = p.directory / 'recall-cases.json'
    path.write_text(json.dumps(cases, indent=2))
    p.cargo(['test', '-p', 'living-mind', 'recall_replay', '--', '--ignored', '--nocapture'], 'recall_replay.log', LIVING_RECALL_CASES=str(path))
    replay = {r['id']: r for r in (json.loads(l) for l in (p.directory / 'recall_replay.log').read_text().splitlines() if l.startswith('{"actor"'))}
    assert any('asked a resident where to find food' in m for m in replay['player-about-resident']['memories'] + replay['player-about-resident']['facts']), replay['player-about-resident']
    assert any(PRIVATE in m for m in replay['player-wolves']['memories']), replay['player-wolves']
    assert any('Wren greeted me' in m for m in replay['resident-about-player']['memories']), replay['resident-about-player']
    assert PRIVATE not in json.dumps(replay['resident-wolves']), replay['resident-wolves']
    budget = {k: tokens('\n'.join(v['facts'] + v['memories'])) for k, v in replay.items()}
    p.pass_feature('recall: resident from its own memory, player from its lived memory, no leak',
                   ['resident-talk-prompt.txt', 'resident-nodes.txt', 'resident-edges.txt', 'recall-cases.json', 'recall_replay.log'], recall_tokens=budget)

    # 5. Death: the authority deletes a dead character's experience rows; the service's buffer
    # still integrates its last moments (admin `kill` sets the scene).
    log = p.directory / 'mind-restart.log'
    time.sleep(3)
    s.call('human_say', ['If anything happens to me, tell the town about the wolves.', resident])
    time.sleep(1.5)
    p.admin('kill', player, 'verify: death during a session')
    p.wait(lambda: not p.sql(f'SELECT * FROM experience WHERE observer = {player}', 'death-player-experience') or None, 'authority deletes the dead player\'s rows', 30)
    p.wait(lambda: 'lived experiences (death' in log.read_text(), 'integration at death', 60)
    req = [r for r in internalize_requests(p) if 'tell the town about the wolves' in user_text(r)]
    assert req, 'the last words before death were not sent'
    p.pass_feature('death: the buffer integrates what the authority deleted', ['death-player-experience.json', 'mind-restart.log', 'requests.jsonl'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'cleanup'])
    parser.add_argument('--run', required=True)
    parser.add_argument('--mode', choices=['direct', 'batch'], default='direct')
    args = parser.parse_args()
    if not args.run.startswith('knowledge-pmem-'):
        sys.exit('run must start with knowledge-pmem-')
    p = Proof(args.run, args.mode, existing=args.action == 'cleanup')
    if args.action == 'cleanup':
        p.cleanup()
        return
    error = None
    try:
        drive(p)
    except BaseException as caught:
        error = caught
        (p.directory / 'failure.log').write_text(traceback.format_exc())
    finally:
        p.cleanup()
    if error:
        raise RuntimeError(f'proof failed; evidence in {p.directory}') from error
    print(f'All player-memory proofs passed ({args.mode}). Evidence retained at {p.directory}', flush=True)


if __name__ == '__main__':
    main()
