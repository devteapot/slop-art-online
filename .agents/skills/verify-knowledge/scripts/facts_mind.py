#!/usr/bin/env python3
"""A resident's mind made from the world's facts, end to end (docs/SEEDED_LIVES.md).

Every person has a mind from the start (2026-11-11). Free tier: the real `living-mind` against
the shared fake model server and a scratch Neo4j, on a `verify-knowledge-*` island world. The
player acts only through its own identity (`human_say`); admin calls set the scene (`place_at`,
`grant_items`, `set_weather`, `set_background`) and are named in `actions.log`.

1. **Identity from facts:** the island's residents are authored; this proof is of the other
   path, so the fixture takes the chosen resident's sheet out of its background before the
   mind starts (`LIVING_ONLY` names it). At start the service makes its first identity: one
   identity call whose request carries the world's facts (occupation, household, places with
   work, settlement) and no perception. The graph marks the facts `world` and the model's
   feelings `ai`; the identity version says `written_by: model` and keeps the facts. Its
   first deliberation comes after.
2. **Talk:** the first line is answered by its first thought; a later line gets a talk turn
   routed to the `people` mix's talk profile (the models file's default route).
3. **Acts:** the deliberation's acts give the player food, teach it a technique and take it
   in as a guest (`host`): an inventory row, a `know_how` row, a private `guest` row and the
   player's `lodging` place.
4. **Names only when known:** the newcomer never says its name, and nothing sent to the
   resident's model names it (prompts and transcripts name people as the authority does).

    facts_mind.py run --run knowledge-facts-<name>
    facts_mind.py cleanup --run knowledge-facts-<name>
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
# What each technique needs known first (`requires(t)` in the rules).
REQUIRES = {t: re.findall(r'"([a-z_]+)"', need) for t, need in re.findall(r'"([a-z_]+)"\s*=>\s*\[([^\]]*)\]', re.search(r'fn requires\(t\)\s*\{(.*?)\n', RULES).group(1))}

ASK = 'verify facts: could you spare some food, a bed for tonight, and teach me something?'
WELCOME = 'verify facts: welcome, stranger. I can spare food, a bed and a lesson.'
TALKED = 'verify facts talk: the inn is by the square.'
IDENTITY_AND_CONSOLIDATION = {
    # The identity call (purpose consolidate) reads these …
    'narrative': 'I keep my post by the square and I know my neighbours.', 'values': ['steady work'],
    'goals': ['keep the household fed'], 'traits': {'caution': 50, 'sociability': 60}, 'mood': 'busy',
    'relations': [],
    # … and a consolidation these.
    'summary': 'verify facts consolidated', 'remember': [], 'nodes': [], 'edges': [], 'judgments': [],
    'places': [], 'merge': [], 'retract': [], 'identity': None,
}
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Proof(K.Run):
    def fake(self, acts):
        script = {'replies': {'think': {'thought': 'A stranger asks for help.', 'intend': ['wait'], 'say': WELCOME},
                              'deliberate': {'graph': {'wait': 120}, 'weight': 1.5, 'plan': 'verify facts plan', 'acts': acts},
                              'talk': {'thought': 'They ask about the town.', 'say': TALKED, 'end': False}},
                  'rules': [{'purpose': 'consolidate', 'reply': IDENTITY_AND_CONSOLIDATION, 'times': -1}]}
        (self.directory / 'fake-script.json').write_text(json.dumps(script, indent=2))
        self.process('fake', [sys.executable, K.FAKE, '--port', '0', '--log', self.directory / 'requests.jsonl', '--script', self.directory / 'fake-script.json'])
        self.wait(lambda: 'READY ' in (self.directory / 'fake.log').read_text(), 'fake model readiness', 10)
        port = int(re.search(r'READY http://127.0.0.1:(\d+)/v1', (self.directory / 'fake.log').read_text())[1])
        profile = lambda model: {'base_url': f'http://127.0.0.1:{port}/v1', 'model': model, 'key_env': 'LIVING_VERIFY_FAKE_KEY', 'max_tokens': 2048,
                                 # The fake server tells purposes apart by the effort each is sent with.
                                 'reasoning_effort': {x: x for x in ('think', 'deliberate', 'consolidate', 'talk')}}
        # As the shipped models file: people think with the `people` mix by default.
        models = {'default': 'people', 'profiles': {'main': profile('facts-main'), 'talk': profile('facts-talk')},
                  'mixes': {'people': {'talk': 'talk', '*': 'main'}}}
        (self.directory / 'models.json').write_text(json.dumps(models, indent=2))

    def requests(self):
        return K.entries(self.directory / 'requests.jsonl')

    def start_mind(self, rid):
        login = subprocess.run([str(ROOT / 'living/tools/stdb'), 'login', 'show', '--token'], capture_output=True, text=True, check=True)
        tokens = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', login.stdout)
        assert len(tokens) == 1
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER=os.environ.get('LIVING_STDB_URL', 'http://127.0.0.1:3300').rstrip('/'), LIVING_DB=self.db, LIVING_RUN=self.db,
                   LIVING_SEED='island', LIVING_MODELS=str(self.directory / 'models.json'), LIVING_ONLY=str(rid), LIVING_TOKEN=tokens[0],
                   LIVING_NEO4J='on', LIVING_NEO4J_URI=self.state['uri'], LIVING_NEO4J_PASSWORD=self.state['password'],
                   LIVING_VERIFY_FAKE_KEY='local-only', LIVING_LLM_PER_MIN='0', LIVING_CONCURRENCY='8', LIVING_LOD='0',
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



def user_text(entry):
    return '\n'.join(m['content'] for m in entry['body']['messages'] if m['role'] == 'user')


def residents_at_posts(p, s, near, exclude):
    acts = {a['id']: a['skill'] for a in p.sql('SELECT id, skill FROM activity', 'activities')}
    people = {c['id']: c for c in p.sql("SELECT * FROM character WHERE kind = 'person'", 'people')}
    bodies = {b['id']: (b['x'], b['y']) for b in p.sql('SELECT id, x, y FROM body', 'bodies')}
    out = [c for c in people.values() if c['alive'] and c['ai'] and c['stage'] == 2 and c['id'] not in exclude
           and acts.get(c['id']) == 'keep' and c['id'] in bodies]
    return sorted(out, key=lambda c: dist(bodies[c['id']], near)), bodies


def speak_to(p, s, me, who, at, line):
    p.admin('place_at', me, at[0] + 1.4, at[1] + 0.4)
    time.sleep(0.6)
    s.call('human_say', [line, who])
    time.sleep(2.2)


def drive(p):
    p.harness('launch', '--seed', 'island', '--target-dir', str(ROOT / '.local/living/target-facts-island'))
    p.harness('doctor')
    p.start_neo4j()
    p.cargo(['build', '--release', '-p', 'living-mind'], 'mind-build.log')
    s = S.Session(p.name)
    me = s.ensure_player('Quorvan')  # a name no island resident has (the leak check matches it)
    p.admin('set_weather', False, 3600)
    mine = {k['technique'] for k in p.knowledge(me, 'player-know-how')}

    # 1. A resident at its post with a house and a technique the player lacks.
    houses = p.sql("SELECT id, x, y FROM structure WHERE kind = 'house'", 'houses')
    def pick():
        cands, bodies = residents_at_posts(p, s, (0, 0), {me})
        for c in cands:
            if not any(dist((h['x'], h['y']), (c['home_x'], c['home_y'])) <= 1.5 for h in houses):
                continue
            lesson = sorted(t for t in {k['technique'] for k in p.knowledge(c['id'], 'resident-know-how')} - mine if set(REQUIRES.get(t, [])) <= mine)
            if lesson:
                return c, lesson[0], bodies
        return None
    r, lesson, bodies = p.wait(pick, 'a resident with a house and a lesson', 120)
    rid = r['id']
    # The island's residents are authored (docs/SEEDED_LIVES.md), and an authored resident's mind
    # starts as its sheet says. This proof is of the other path, a resident without a sheet whose
    # identity a model writes from the world's facts, so the fixture takes the sheet out of its
    # background (an admin scene call) before the mind starts; its relation rows and places
    # stay world facts.
    bg = json.loads(p.sql(f'SELECT text FROM background WHERE id = {rid}', 'resident-background')[0]['text'])
    if bg.pop('sheet', None) is not None:
        p.admin('set_background', rid, json.dumps(bg))
    p.admin('grant_items', rid, 'berries', 4)
    acts = [{'do': 'give', 'target': {'id': me}, 'item': 'berries', 'qty': 1},
            {'do': 'teach', 'target': {'id': me}, 'item': lesson},
            {'do': 'host', 'target': {'id': me}}]
    p.fake(acts)
    p.start_mind(rid)
    ident_thought = p.wait(lambda: [t for t in p.thoughts(rid, 'thoughts-identity') if t['summary'].startswith('Who I am, from what the world holds')], 'its identity from facts', 90)
    rx, ry = p.sql(f'SELECT x, y FROM body WHERE id = {rid}', 'resident-body')[0].values()
    speak_to(p, s, me, rid, (rx, ry), ASK)
    # A mind already living answers a line in a talk turn; ask it to deliberate too (an admin
    # scene call), so its acts and its think step's answer follow.
    # (Not `p.admin`, whose revision check races the mind installing its own graph.)
    p.command([ROOT / 'living/tools/stdb', 'call', '-s', 'local', p.db, 'set_behavior', json.dumps(rid),
               json.dumps(json.dumps({'think': 'A quiet moment to take stock of how things are going. verify facts'}))])
    p.wait(lambda: [t for t in p.thoughts(rid, 'thoughts-after') if t['kind'] == 'deliberate'], 'its first deliberation', 120)
    thoughts = p.thoughts(rid, 'thoughts-all')
    first_delib = min(t['at_ms'] for t in thoughts if t['kind'] == 'deliberate')
    assert ident_thought[0]['at_ms'] <= first_delib, (ident_thought[0]['at_ms'], first_delib)
    reqs = p.requests()
    ident = [x for x in reqs if x['purpose'] == 'consolidate' and f"(#{rid})" in user_text(x) and 'Background:' in user_text(x)]
    assert ident, 'no identity request for the resident'
    facts = user_text(ident[0])
    for want in ('"occupation"', '"household"', '"places"', '"work"', '"settlement"'):
        assert want in facts, f'{want} missing from the facts'
    assert 'verify facts' not in facts and '"sheet"' not in facts, 'the identity request carried a perception or a sheet, not only facts'
    detail = json.loads(ident_thought[0]['detail'])
    assert 'narrative' in detail['model_written'] and detail['facts']['occupation'], detail
    newcomer = p.sql(f'SELECT name FROM character WHERE id = {me}', 'newcomer-name')[0]['name']
    f = f"{{run: '{p.db}', actor: {rid}}}"
    marks = p.cypher(f"MATCH (n:Concept {f}) RETURN n.key AS key, n.lived_under AS lived_under ORDER BY key;", 'resident-nodes').stdout
    edges = p.cypher(f"MATCH (n:Concept {f})-[r]->(m:Concept) RETURN n.key AS source, coalesce(r.rel, type(r)) AS rel, m.key AS target, r.lived_under AS lived_under ORDER BY source, rel;", 'resident-edges').stdout
    ident_node = p.cypher(f"MATCH (v:IdentityVersion {f}) RETURN v.version AS version, v.written_by AS written_by, v.from_facts AS facts;", 'resident-identity').stdout
    assert '"world"' in marks + edges, 'world facts must be marked'
    assert 'place:work' in marks, 'its work place (a given place) is in its mind'
    assert '"model"' in ident_node and 'occupation' in ident_node, ident_node
    p.pass_feature('its mind starts from the world facts: an identity call carrying only facts, before its first deliberation',
                   ['thoughts-all.json', 'requests.jsonl', 'resident-nodes.txt', 'resident-edges.txt', 'resident-identity.txt'],
                   identity_ms=ident_thought[0]['at_ms'], first_deliberation_ms=first_delib)

    # 2. Talk: the first thought answered; a later line takes a talk turn on the mix's talk profile.
    heard = lambda text, label: [e for e in p.sql(f'SELECT * FROM experience WHERE observer = {me}', label) if text in e['text'] and e['subject'] == rid]
    p.wait(lambda: heard('verify facts: welcome', 'player-heard-welcome'), 'the resident answers the newcomer', 60)
    time.sleep(2.2)
    s.call('human_say', ['verify facts: where is the inn?', rid])
    p.wait(lambda: heard('verify facts talk', 'player-heard-talk'), 'a talk turn answered through mind_say', 60)
    talks = [x for x in p.requests() if x['purpose'] == 'talk']
    assert talks and all(x['body']['model'] == 'facts-talk' for x in talks), [x['body']['model'] for x in talks]
    assert 'thinks with profile people' in p.log(), 'the people route was not logged'
    p.pass_feature('the resident answers, and talks on the people mix\'s talk model', ['player-heard-welcome.json', 'player-heard-talk.json', 'requests.jsonl', 'mind.log'],
                   talk_models=sorted({x['body']['model'] for x in talks}))

    # 3. Acts: food, a lesson, a bed.
    guest = p.wait(lambda: p.sql(f'SELECT * FROM guest WHERE guest = {me}', 'guest'), 'the resident takes the player in', 90)
    learned = p.wait(lambda: [k for k in p.knowledge(me, 'player-learned') if k['technique'] == lesson], 'the lesson', 90)
    fed = [i for i in p.sql(f'SELECT * FROM inventory WHERE owner = {me}', 'player-inventory') if i['item'] == 'berries']
    lodging = [x for x in p.sql(f'SELECT * FROM place WHERE actor = {me}', 'player-places') if x['name'] == 'lodging']
    assert guest[0]['host'] == rid and lodging, (guest, lodging)
    gifts = [c for c in p.sql('SELECT * FROM chronicle', 'chronicle-acts') if c['kind'] == 'give' and c['b'] == me and c['a'] == rid]
    assert gifts and fed, 'no food given'
    p.pass_feature('its acts feed, teach and host the newcomer', ['guest.json', 'player-learned.json', 'player-places.json', 'chronicle-acts.json'],
                   host=guest[0]['host'], lesson=lesson, taught_by=learned[0]['source'])

    # 4. Nothing the resident's model was sent named the newcomer: it never said its name, so it
    # stays "a stranger" in talk prompts and transcripts alike.
    leaks = [f.name for f in p.journal.glob('*.jsonl') if newcomer in f.read_text()]
    assert not leaks, f'{newcomer} reached what was sent for {leaks}'
    p.pass_feature('a stranger stays a stranger in what the mind is sent', ['journal/'], journals=len(list(p.journal.glob('*.jsonl'))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'cleanup'])
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    if not args.run.startswith('knowledge-facts-'):
        sys.exit('run must start with knowledge-facts-')
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
    print(f'All facts-mind proofs passed. Evidence retained at {p.directory}', flush=True)


if __name__ == '__main__':
    main()
