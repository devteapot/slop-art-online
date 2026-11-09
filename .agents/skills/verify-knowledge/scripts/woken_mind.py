#!/usr/bin/env python3
"""Residents woken into minds, end to end (docs/TOWN_LIFE.md, "Layer 2").

Free tier: the real `living-mind` against the shared fake model server and a scratch Neo4j, on
a `verify-knowledge-*` island world (`rules.minds = false`). The player acts only through its
own identity (`human_say`); admin calls set the scene (`place_at`, `grant_items`,
`set_weather`) and are named in `actions.log`. The laws come from the rules as installed.

1. **Before the mind:** the player speaks to one resident (it wakes) while another, in
   earshot, only overhears: the line is in that one's ring.
2. **Wake:** the mind runs with `LIVING_ONLY=woken` and the level of detail on. The player
   speaks to the resident who overheard: it wakes; its mind is made before its first
   deliberation: an identity call whose request carries the world's facts (occupation,
   household, places, settlement) and nothing from any ring, then one integration of its
   ring (the overheard line included, nothing it did not perceive), then the deliberation.
   The graph marks the facts `world`, the model's feelings `ai`, the ring's memories
   `instinct`; the identity version says `written_by: model` and keeps the facts.
3. **Talk:** the first line is answered by that first thought; a later line gets a talk
   turn routed to the `people` mix's talk profile (the models file's `woken` route).
4. **Acts:** the deliberation's acts give the player food, teach it a technique and take it
   in as a guest (`host`): an inventory row, a `know_how` row, a private `guest` row and the
   player's `lodging` place.
5. **Names only when known:** the newcomer never says its name. The ring's feeling toward it is
   kept (a feeling is not an introduction), its memory node is "a stranger", and nothing sent to
   any woken resident's model names it (prompts, transcripts and memory name people as the
   authority does).
6. **Stage cap:** the player speaks to more residents of the same settlement until one more
   than the `woken_stage("cap")` law is woken and in contact with it: the cap binds, logged
   and journaled (`purpose: stage_cap`).
7. Every woken resident is still a mind at the end.

    woken_mind.py run --run knowledge-woken-<name>
    woken_mind.py cleanup --run knowledge-woken-<name>
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('verify_knowledge', HERE / 'verify_knowledge.py')
K = importlib.util.module_from_spec(spec)
spec.loader.exec_module(K)
spec = importlib.util.spec_from_file_location('player_session', HERE / 'player_session.py')
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
ROOT = K.ROOT
RULES = (ROOT / 'living/scripts/skills.rhai').read_text()
CAP = int(re.search(r'fn woken_stage\(k\)[^}]*"cap"\s*=>\s*(\d+)', RULES, re.S).group(1))
HEARING = float(re.search(r'hearing:\s*([0-9.]+)', RULES).group(1))
# What each technique needs known first (`requires(t)` in the rules).
REQUIRES = {t: re.findall(r'"([a-z_]+)"', need) for t, need in re.findall(r'"([a-z_]+)"\s*=>\s*\[([^\]]*)\]', re.search(r'fn requires\(t\)\s*\{(.*?)\n', RULES).group(1))}

# Without a name: the resident who overhears knows the newcomer only as a stranger.
OVERHEARD = 'verify woken: I am new here, and I am looking for work'
ASK = 'verify woken: could you spare some food, a bed for tonight, and teach me something?'
WELCOME = 'verify woken: welcome, stranger. I can spare food, a bed and a lesson.'
TALKED = 'verify woken talk: the inn is by the square.'
IDENTITY_AND_CONSOLIDATION = {
    # The identity call (purpose consolidate) reads these …
    'narrative': 'I keep my post by the square and I know my neighbours.', 'values': ['steady work'],
    'goals': ['keep the household fed'], 'traits': {'caution': 50, 'sociability': 60}, 'mood': 'busy',
    'relations': [],
    # … and a consolidation these.
    'summary': 'verify woken consolidated', 'remember': [], 'nodes': [], 'edges': [], 'judgments': [],
    'places': [], 'merge': [], 'retract': [], 'identity': None,
}
RING = {
    'summary': 'verify woken: what I perceived before.',
    'remember': [{'exp': '$EXP:said to', 'gist': 'A stranger at the market said they were new here and looking for work.'}],
    'nodes': [], 'edges': [{'from': 'self', 'rel': 'OVERHEARD', 'to': 'idea:newcomer_looking_for_work', 'confidence': 0.7, 'because': ['$EXP:said to']}],
    # A feeling toward the stranger it only saw and overheard: dropped, so its name stays unknown.
    # (the newcomer's id is filled in per run: `Proof.fake`).
    'relations': [],
    'places': [], 'identity': None,
}


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Proof(K.Run):
    def fake(self, acts, newcomer):
        script = {'replies': {'think': {'thought': 'A stranger asks for help.', 'intend': ['wait'], 'say': WELCOME},
                              'deliberate': {'graph': {'wait': 120}, 'weight': 1.5, 'plan': 'verify woken plan', 'acts': acts},
                              'talk': {'thought': 'They ask about the town.', 'say': TALKED, 'end': False}},
                  'rules': [{'purpose': 'internalize', 'cite': True, 'times': -1,
                             'reply': dict(RING, relations=[{'id': newcomer, 'trust': 5, 'affinity': 10, 'label': 'stranger', 'note': 'new here, looking for work'}])},
                            {'purpose': 'consolidate', 'reply': IDENTITY_AND_CONSOLIDATION, 'times': -1}]}
        (self.directory / 'fake-script.json').write_text(json.dumps(script, indent=2))
        self.process('fake', [sys.executable, K.FAKE, '--port', '0', '--log', self.directory / 'requests.jsonl', '--script', self.directory / 'fake-script.json'])
        self.wait(lambda: 'READY ' in (self.directory / 'fake.log').read_text(), 'fake model readiness', 10)
        port = int(re.search(r'READY http://127.0.0.1:(\d+)/v1', (self.directory / 'fake.log').read_text())[1])
        profile = lambda model: {'base_url': f'http://127.0.0.1:{port}/v1', 'model': model, 'key_env': 'LIVING_VERIFY_FAKE_KEY', 'max_tokens': 2048,
                                 # The fake server tells purposes apart by the effort each is sent with.
                                 'reasoning_effort': {x: x for x in ('think', 'deliberate', 'consolidate', 'talk', 'internalize')}}
        models = {'default': 'main', 'profiles': {'main': profile('woken-main'), 'talk': profile('woken-talk')},
                  'mixes': {'people': {'talk': 'talk', '*': 'main'}}, 'woken': 'people'}
        (self.directory / 'models.json').write_text(json.dumps(models, indent=2))

    def requests(self):
        return K.entries(self.directory / 'requests.jsonl')

    def start_mind(self):
        login = subprocess.run([str(ROOT / 'living/tools/stdb'), 'login', 'show', '--token'], capture_output=True, text=True, check=True)
        tokens = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', login.stdout)
        assert len(tokens) == 1
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER='http://127.0.0.1:3300', LIVING_DB=self.db, LIVING_RUN=self.db,
                   LIVING_SEED='island', LIVING_MODELS=str(self.directory / 'models.json'), LIVING_ONLY='woken', LIVING_TOKEN=tokens[0],
                   LIVING_NEO4J='on', LIVING_NEO4J_URI=self.state['uri'], LIVING_NEO4J_PASSWORD=self.state['password'],
                   LIVING_VERIFY_FAKE_KEY='local-only', LIVING_LLM_PER_MIN='0', LIVING_CONCURRENCY='8', LIVING_LOD='1',
                   NO_PROXY='127.0.0.1,localhost', RUST_LOG='info,neo4rs=warn,spacetimedb_sdk=warn')
        keep = ('LIVING_DB', 'LIVING_SEED', 'LIVING_ONLY', 'LIVING_MODELS', 'LIVING_LOD')
        (self.directory / 'mind-environment.json').write_text(json.dumps({k: env[k] for k in keep}, indent=2))
        self.process('mind', [K.BUILD / 'release/living-mind'], env)
        self.wait(lambda: 'world subscribed:' in self.log(), 'mind subscription', 90)

    def log(self):
        path = self.directory / 'mind.log'
        return path.read_text() if path.exists() else ''

    def thoughts(self, actor, label):
        return self.sql(f'SELECT * FROM thought WHERE actor = {actor}', label)

    def woken(self, label='woken'):
        return {w['id']: w for w in self.sql('SELECT * FROM woken', label)}


def user_text(entry):
    return '\n'.join(m['content'] for m in entry['body']['messages'] if m['role'] == 'user')


def residents_at_posts(p, s, near, exclude):
    acts = {a['id']: a['skill'] for a in p.sql('SELECT id, skill FROM activity', 'activities')}
    people = {c['id']: c for c in p.sql("SELECT * FROM character WHERE kind = 'person'", 'people')}
    bodies = {b['id']: (b['x'], b['y']) for b in p.sql('SELECT id, x, y FROM body', 'bodies')}
    out = [c for c in people.values() if c['alive'] and not c['ai'] and c['stage'] == 2 and c['id'] not in exclude
           and acts.get(c['id']) == 'keep' and c['id'] in bodies]
    return sorted(out, key=lambda c: dist(bodies[c['id']], near)), bodies


def speak_to(p, s, me, who, at, line):
    p.admin('place_at', me, at[0] + 1.4, at[1] + 0.4)
    time.sleep(0.6)
    s.call('human_say', [line, who])
    time.sleep(2.2)


def drive(p):
    p.harness('launch', '--seed', 'island', '--target-dir', str(ROOT / '.local/living/target-woken-island'))
    p.harness('doctor')
    p.start_neo4j()
    p.cargo(['build', '--release', '-p', 'living-mind'], 'mind-build.log')
    s = S.Session(p.name)
    me = s.ensure_player('Wren')
    p.admin('set_weather', False, 3600)
    mine = {k['technique'] for k in p.knowledge(me, 'player-know-how')}

    # 1. A resident at its post with a house and a technique the player lacks, and a neighbour
    # in earshot to speak to first.
    houses = p.sql("SELECT id, x, y FROM structure WHERE kind = 'house'", 'houses')
    def pick():
        cands, bodies = residents_at_posts(p, s, (0, 0), {me})
        for c in cands:
            if not any(dist((h['x'], h['y']), (c['home_x'], c['home_y'])) <= 1.5 for h in houses):
                continue
            lesson = sorted(t for t in {k['technique'] for k in p.knowledge(c['id'], 'resident-know-how')} - mine if set(REQUIRES.get(t, [])) <= mine)
            near = [o for o in cands if o['id'] != c['id'] and 2.0 <= dist(bodies[o['id']], bodies[c['id']]) <= HEARING - 4]
            if lesson and near:
                return c, near[0], lesson[0], bodies
        return None
    r, first, lesson, bodies = p.wait(pick, 'a resident with a house, a lesson and a neighbour in earshot', 120)
    rid, fid = r['id'], first['id']
    p.admin('grant_items', rid, 'berries', 4)
    acts = [{'do': 'give', 'target': {'id': me}, 'item': 'berries', 'qty': 1},
            {'do': 'teach', 'target': {'id': me}, 'item': lesson},
            {'do': 'host', 'target': {'id': me}}]
    p.fake(acts, me)
    # The player speaks to the neighbour, standing where the resident only overhears.
    fx, fy = bodies[fid]
    p.admin('place_at', me, fx + 1.2, fy)
    time.sleep(0.8)
    s.call('human_say', [OVERHEARD, fid])
    p.wait(lambda: fid in p.woken('woken-first'), 'the neighbour wakes', 10)
    ring = p.wait(lambda: [x for x in p.sql(f'SELECT * FROM prior WHERE resident = {rid}', 'ring-before') if 'new here' in x['text']], 'the line in the resident\'s ring', 10)
    assert rid not in p.woken('woken-before'), 'overhearing woke the resident'
    p.pass_feature('a resident in earshot keeps the overheard line and stays instinct only', ['ring-before.json', 'woken-before.json'],
                   resident=rid, line=ring[0]['text'])

    # 2. The mind starts; the player speaks to the resident: it wakes and its mind is made first.
    p.start_mind()
    rx, ry = p.sql(f'SELECT x, y FROM body WHERE id = {rid}', 'resident-body')[0].values()
    speak_to(p, s, me, rid, (rx, ry), ASK)
    w = p.wait(lambda: p.woken('woken-resident').get(rid), 'the resident wakes', 10)
    assert w['why'] == 'speech' and w['by'] == me, w
    first_thought = p.wait(lambda: [t for t in p.thoughts(rid, 'thoughts-after') if t['kind'] == 'deliberate'], 'its first deliberation', 120)
    thoughts = p.thoughts(rid, 'thoughts-all')
    at = lambda kind: min((t['at_ms'] for t in thoughts if t['kind'] == kind), default=None)
    assert at('awaken') and at('internalize') and at('awaken') <= at('internalize') <= at('deliberate'), {k: at(k) for k in ('awaken', 'internalize', 'deliberate')}
    reqs = p.requests()
    ident = [x for x in reqs if x['purpose'] == 'consolidate' and f"(#{rid})" in user_text(x) and 'Background:' in user_text(x)]
    assert ident, 'no identity request for the resident'
    facts = user_text(ident[0])
    for want in ('"occupation"', '"household"', '"places"', '"work"', '"settlement"'):
        assert want in facts, f'{want} missing from the facts'
    assert 'new here' not in facts, 'the identity request carried a perception, not only facts'
    ringreq = [x for x in reqs if x['purpose'] == 'internalize' and 'new here' in user_text(x)]
    assert ringreq, 'the ring integration did not carry the overheard line'
    assert ASK not in user_text(ringreq[0]), 'the ring integration carried what came after waking'
    detail = json.loads(next(t for t in thoughts if t['kind'] == 'internalize')['detail'])
    assert detail['lived_under'] == 'instinct', detail
    # A stranger stays a stranger: the ring's feeling toward the newcomer is kept (a feeling is not
    # an introduction), its memory names it "a stranger", and nothing sent for it names it.
    newcomer = p.sql(f'SELECT name FROM character WHERE id = {me}', 'newcomer-name')[0]['name']
    felt = p.wait(lambda: [x for x in p.sql(f'SELECT * FROM relation WHERE actor = {rid}', 'resident-relations') if x['other'] == me], 'the feeling from the ring', 30)
    stranger = p.cypher(f"MATCH (n:Concept {{run: '{p.db}', actor: {rid}, key: 'person:{me}'}}) RETURN n.name AS name;", 'resident-newcomer-node').stdout
    assert 'a stranger' in stranger and newcomer not in stranger, stranger
    sent = (p.journal / f"{r['name']}.jsonl").read_text()
    assert newcomer not in sent, f'{newcomer} reached what was sent for {r["name"]}, who was never told the name'
    awaken = json.loads(next(t for t in thoughts if t['kind'] == 'awaken')['detail'])
    assert 'narrative' in awaken['model_written'] and awaken['facts']['occupation'], awaken
    f = f"{{run: '{p.db}', actor: {rid}}}"
    marks = p.cypher(f"MATCH (n:Concept {f}) RETURN n.key AS key, n.lived_under AS lived_under ORDER BY key;", 'resident-nodes').stdout
    edges = p.cypher(f"MATCH (n:Concept {f})-[r]->(m:Concept) RETURN n.key AS source, coalesce(r.rel, type(r)) AS rel, m.key AS target, r.lived_under AS lived_under ORDER BY source, rel;", 'resident-edges').stdout
    ident_node = p.cypher(f"MATCH (v:IdentityVersion {f}) RETURN v.version AS version, v.written_by AS written_by, v.from_facts AS facts;", 'resident-identity').stdout
    assert '"world"' in marks + edges and '"instinct"' in marks + edges, 'facts and ring memories must be marked'
    assert '"model"' in ident_node and 'occupation' in ident_node, ident_node
    upto = p.cypher(f"MATCH (s:Concept {{run: '{p.db}', actor: {rid}, key: 'self'}}) RETURN s.woken_upto AS upto;", 'resident-self').stdout
    assert re.search(r'\b[1-9]\d*\b', upto.splitlines()[-1]), upto
    p.pass_feature('waking makes the mind first: identity from facts, then the ring, then the first deliberation',
                   ['thoughts-all.json', 'requests.jsonl', 'resident-nodes.txt', 'resident-edges.txt', 'resident-identity.txt', 'resident-self.txt'],
                   order={k: at(k) for k in ('awaken', 'internalize', 'deliberate')})

    # 3. Talk: the first thought answered; a later line takes a talk turn on the mix's talk profile.
    heard = lambda text, label: [e for e in p.sql(f'SELECT * FROM experience WHERE observer = {me}', label) if text in e['text'] and e['subject'] == rid]
    p.wait(lambda: heard('verify woken: welcome', 'player-heard-welcome'), 'the resident answers the newcomer', 60)
    time.sleep(2.2)
    s.call('human_say', ['verify woken: where is the inn?', rid])
    p.wait(lambda: heard('verify woken talk', 'player-heard-talk'), 'a talk turn answered through mind_say', 60)
    talks = [x for x in p.requests() if x['purpose'] == 'talk']
    assert talks and all(x['body']['model'] == 'woken-talk' for x in talks), [x['body']['model'] for x in talks]
    assert 'thinks with profile people' in p.log(), 'the woken route was not logged'
    p.pass_feature('a woken resident answers, and talks on the woken route\'s talk model', ['player-heard-welcome.json', 'player-heard-talk.json', 'requests.jsonl', 'mind.log'],
                   talk_models=sorted({x['body']['model'] for x in talks}))

    # 4. Acts: food, a lesson, a bed.
    guest = p.wait(lambda: p.sql(f'SELECT * FROM guest WHERE guest = {me}', 'guest'), 'the resident takes the player in', 90)
    learned = p.wait(lambda: [k for k in p.knowledge(me, 'player-learned') if k['technique'] == lesson], 'the lesson', 90)
    fed = [i for i in p.sql(f'SELECT * FROM inventory WHERE owner = {me}', 'player-inventory') if i['item'] == 'berries']
    lodging = [x for x in p.sql(f'SELECT * FROM place WHERE actor = {me}', 'player-places') if x['name'] == 'lodging']
    woken_ids = set(p.woken('woken-acts'))
    assert guest[0]['host'] in woken_ids and lodging, (guest, lodging)
    gifts = [c for c in p.sql('SELECT * FROM chronicle', 'chronicle-acts') if c['kind'] == 'give' and c['b'] == me and c['a'] in woken_ids]
    assert gifts and fed, 'no food given'
    p.pass_feature('its acts feed, teach and host the newcomer', ['guest.json', 'player-learned.json', 'player-places.json', 'chronicle-acts.json'],
                   host=guest[0]['host'], lesson=lesson, taught_by=learned[0]['source'])

    # 5. The stage cap: one more woken resident of this settlement in contact than the law allows.
    settlement = p.woken('woken-cap-0')[rid]['settlement']
    cap_log = lambda: [l for l in p.log().splitlines() if 'stage cap' in l and 'binds' in l]
    tried = set(p.woken('woken-cap-1'))
    for _ in range(4 * CAP):
        if cap_log():
            break
        cands, bodies = residents_at_posts(p, s, (rx, ry), tried | {me})
        if not cands:
            break
        c = cands[0]
        tried.add(c['id'])
        speak_to(p, s, me, c['id'], bodies[c['id']], 'verify woken: good day to you.')
    binds = p.wait(cap_log, 'the stage cap binds', 60)
    same = [x for x in p.woken('woken-cap').values() if x['settlement'] == settlement]
    journal = [json.loads(l) for path in p.journal.glob('*.jsonl') for l in path.read_text().splitlines() if '"stage_cap"' in l]
    p.wait(lambda: journal or [json.loads(l) for path in p.journal.glob('*.jsonl') for l in path.read_text().splitlines() if '"stage_cap"' in l], 'the cap journaled', 15)
    journal = [json.loads(l) for path in p.journal.glob('*.jsonl') for l in path.read_text().splitlines() if '"stage_cap"' in l]
    assert journal and all(j['cap'] == CAP for j in journal), journal
    p.pass_feature('the stage cap binds, logged and journaled', ['mind.log', 'woken-cap.json'], cap=CAP, woken_in_settlement=len(same), report=binds[0], journal=journal[0])

    # 6. Still minds.
    chars = {c['id']: c for c in p.sql("SELECT id, ai FROM character WHERE kind = 'person'", 'people-end')}
    ids = list(p.woken('woken-end'))
    assert all(chars[i]['ai'] for i in ids if i in chars)
    p.pass_feature('woken residents stay minds', ['woken-end.json', 'people-end.json'], woken=len(ids))

    # 7. Nothing any woken resident's model was sent named the newcomer: it never said its
    # name, so it stays "a stranger" in talk prompts, transcripts and memory alike.
    leaks = [f.name for f in p.journal.glob('*.jsonl') if newcomer in f.read_text()]
    assert not leaks, f'{newcomer} reached what was sent for {leaks}'
    p.pass_feature('a stranger stays a stranger in what woken minds are sent', ['journal/'], journals=len(list(p.journal.glob('*.jsonl'))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'cleanup'])
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    if not args.run.startswith('knowledge-woken-'):
        sys.exit('run must start with knowledge-woken-')
    p = Proof(args.run, existing=args.action == 'cleanup')
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
    print(f'All woken-resident proofs passed. Evidence retained at {p.directory}', flush=True)


if __name__ == '__main__':
    main()
