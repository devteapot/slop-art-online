#!/usr/bin/env python3
"""Drive knowledge scenes and real memory integration on owned scratch services."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[4]
SHARED = ROOT / '.agents/skills/verify/scripts/verify.py'
FAKE = ROOT / '.agents/skills/verify-llm/scripts/fake_llm.py'
BUILD = ROOT / '.local/living/verify/build-knowledge'
TESTS = ('minds_revise_merge_and_fade', 'recall_by_cues_and_forgetting',
         'formative_past_outlasts_ordinary_beliefs', 'authored_memories_are_recalled')
STRUCTURE_BIT = 1 << 40


def entries(path):
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()] if path.exists() else []


def actions(node):
    if isinstance(node, list):
        return [a for child in node for a in actions(child)]
    if not isinstance(node, dict):
        return []
    if isinstance(node.get('do'), dict):
        return [(node['do']['skill'], node['do'].get('item'))]
    return [a for child in node.values() for a in actions(child)]


class Run:
    def __init__(self, name, existing=False):
        if not re.fullmatch(r'knowledge-[a-zA-Z0-9-]+', name):
            raise ValueError('run must start with knowledge- and use letters, numbers and hyphens')
        self.name = name
        self.db = 'verify-' + name
        self.directory = ROOT / '.local/living/verify' / name
        self.private = self.directory / 'knowledge-state.json'
        self.journal = ROOT / '.local/living/journal' / self.db
        if existing:
            self.state = json.loads(self.private.read_text())
        else:
            if self.directory.exists() or self.journal.exists():
                raise ValueError('use a fresh run name')
            self.directory.mkdir(parents=True)
            self.state = {'run': name, 'db': self.db, 'container': 'sao-verify-neo4j-' + name,
                          'password': secrets.token_urlsafe(24), 'pids': {}, 'container_started': False}
            self.save()
        if self.state['run'] != name or self.state['db'] != self.db:
            raise ValueError('state does not match the requested scratch run')
        if self.state['container'] != 'sao-verify-neo4j-' + name:
            raise ValueError('container is not owned by this scratch run')
        self.results = []
        self.streams = []
        self.processes = []

    def save(self):
        fd = os.open(self.private, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(self.state, stream, indent=2)

    def command(self, args, filename='actions.log', check=True, timeout=600, env=None, cwd=ROOT):
        result = subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True,
                                text=True, timeout=timeout, env=env)
        output = result.stdout + result.stderr
        password = self.state.get('password')
        if password and password in output:
            output = output.replace(password, '[redacted]')
        with (self.directory / filename).open('a') as stream:
            stream.write('$ ' + ' '.join(map(str, args)) + '\n' + output + f'\nexit={result.returncode}\n')
        if check and result.returncode:
            raise RuntimeError(f'command failed; see {filename}')
        return result

    def harness(self, action, *args):
        return self.command([SHARED, action, '--run', self.name, *args], timeout=900)

    def sql(self, query, label):
        return json.loads(self.harness('sql', query, '--save', label).stdout)

    def admin(self, reducer, *args):
        before = self.sql(f'SELECT revision FROM brain WHERE id = {args[0]}', f'graph-before-{args[0]}') if reducer == 'set_behavior' else None
        result = self.command([ROOT / 'living/tools/stdb', 'call', '-s', 'local', self.db,
                               reducer, *[json.dumps(x) for x in args]])
        if before is not None:
            after = self.sql(f'SELECT * FROM brain WHERE id = {args[0]}', f'graph-after-{args[0]}')
            assert after and after[0]['revision'] == (before[0]['revision'] if before else 0) + 1, 'set_behavior did not install the requested graph'
            assert actions(json.loads(args[1])) == actions(json.loads(after[0]['graph'])), 'normalization changed the scene action leaves'
        return result

    def wait(self, predicate, label, seconds=50):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            for process in self.processes:
                if process.poll() is not None:
                    raise RuntimeError(f'owned process {process.pid} exited while waiting for {label}')
            value = predicate()
            if value:
                return value
            time.sleep(1)
        raise RuntimeError(f'timed out waiting for {label} after {seconds}s')

    def pass_feature(self, feature, evidence, **details):
        self.results.append({'feature': feature, 'result': 'pass', 'evidence': evidence, **details})
        (self.directory / 'results.json').write_text(json.dumps(self.results, indent=2))
        print(f'PASS {feature}', flush=True)

    def cypher(self, query, label, check=True):
        path = self.directory / f'{label}.cypher'
        path.write_text(query + '\n')
        # The container already owns its auth env. No password is passed on the command line.
        args = ['docker', 'exec', '-i', self.state['container'], 'sh', '-c',
                'NEO4J_PASSWORD="${NEO4J_AUTH#*/}" cypher-shell -a bolt://localhost:7687 -u neo4j --format plain']
        result = subprocess.run(args, input=query, capture_output=True, text=True, timeout=35)
        (self.directory / f'{label}.txt').write_text(result.stdout + result.stderr)
        if check and result.returncode:
            raise RuntimeError(f'Cypher failed; see {label}.txt')
        return result

    def start_neo4j(self):
        images = self.command(['docker', 'images', '--format', '{{.Repository}}:{{.Tag}}'], 'images.log').stdout.splitlines()
        image = 'docker.io/library/neo4j:2026.09.0'
        if image not in images:
            raise RuntimeError('required fully qualified Neo4j image is not present locally')
        if self.command(['docker', 'container', 'exists', self.state['container']], 'neo4j-name-check.log', check=False).returncode == 0:
            raise RuntimeError('scratch container name already exists')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 7691))
        self.state['uri'] = '127.0.0.1:7691'
        self.state['container_started'] = True
        self.save()
        env = dict(os.environ, NEO4J_AUTH='neo4j/' + self.state['password'])
        self.command(['docker', 'run', '-d', '--name', self.state['container'],
                      '--label', 'sao.verify.run=' + self.name, '-p', '127.0.0.1:7691:7687',
                      '-e', 'NEO4J_AUTH', image], 'neo4j-start.log', env=env)
        self.wait(lambda: self.cypher('RETURN 1 AS ready;', 'neo4j-ready', False).returncode == 0,
                  'scratch Neo4j readiness', 180)
        self.command(['docker', 'inspect', self.state['container'], '--format',
                      '{{.Config.Image}} {{json .Mounts}}'], 'neo4j-doctor.log')

    def cargo(self, args, label, **extra_env):
        env = dict(os.environ, CARGO_TARGET_DIR=str(BUILD), LIVING_NEO4J='on',
                   LIVING_NEO4J_URI=self.state['uri'], LIVING_NEO4J_PASSWORD=self.state['password'],
                   LIVING_RECALL_CASES='')
        env.update(extra_env)
        return self.command(['cargo', *args], label, env=env, cwd=ROOT / 'living', timeout=1200)

    def graph_tests(self):
        self.cargo(['build', '--release', '-p', 'living-mind'], 'mind-build.log')
        for test in TESTS:
            self.cargo(['test', '-p', 'living-mind', test, '--', '--ignored', '--nocapture'], test + '.log')
            assert '1 passed' in (self.directory / (test + '.log')).read_text(), test
            self.pass_feature(test, [test + '.log'])
        for test in ('missing_know_how_says_how_to_learn_it', 'teaching_names_real_techniques'):
            self.cargo(['test', '-p', 'living-rules', test, '--', '--nocapture'], test + '.log')
            assert '1 passed' in (self.directory / (test + '.log')).read_text(), test

    def graph(self, actor, *steps):
        self.admin('set_behavior', actor, json.dumps({'seq': list(steps) + [{'wait': 120}]}))

    def knowledge(self, actor, label):
        return self.sql(f'SELECT * FROM know_how WHERE actor = {actor}', label)

    def inventory(self, actor, label):
        return self.sql(f'SELECT * FROM inventory WHERE owner = {actor}', label)

    def feedback(self, actor, phrase, label):
        experiences = self.sql(f'SELECT * FROM experience WHERE observer = {actor}', label + '-experience')
        states = self.sql(f'SELECT * FROM mind_state WHERE id = {actor}', label + '-state')
        observed = [{'origin': 'experience', 'text': r['text']} for r in experiences]
        observed += [{'origin': 'mind_state.status', 'text': r['status']} for r in states]
        matching = [r for r in observed if phrase in r['text']]
        (self.directory / (label + '.json')).write_text(json.dumps(matching, indent=2))
        return matching

    def authority(self):
        seed = self.sql("SELECT * FROM know_how WHERE source = 'seed'", 'seed-knowledge')
        assert seed and all(r['since_ms'] > 0 for r in seed)
        self.pass_feature('seed knowledge', ['seed-knowledge.json'])
        self.admin('spawn_crowd', 5, True)
        actors = self.sql("SELECT * FROM character WHERE name = 'Walker1' OR name = 'Walker2' OR name = 'Walker3' OR name = 'Walker4' OR name = 'Walker5'", 'scene-actors')
        ids = {r['name']: r['id'] for r in actors}
        teacher, reader, student, learner, sign_reader = [ids['Walker' + str(i)] for i in range(1, 6)]
        for actor in ids.values():
            self.admin('set_behavior', actor, json.dumps({'wait': 120}))
        for actor in (reader, student, sign_reader):
            self.admin('place_near', actor, teacher)
        self.admin('grant_know_how', teacher, 'writing')
        self.admin('grant_know_how', teacher, 'spear')
        first = self.knowledge(teacher, 'grant-before-repeat')
        self.admin('grant_know_how', teacher, 'spear')
        repeated = self.knowledge(teacher, 'grant-after-repeat')
        assert first == repeated and len([r for r in repeated if r['technique'] == 'spear']) == 1
        assert all(r['source'] == 'granted' for r in repeated)
        self.pass_feature('grant and idempotence', ['grant-before-repeat.json', 'grant-after-repeat.json'])

        self.admin('grant_items', student, 'fiber', 4)
        self.admin('grant_items', student, 'hide', 4)
        gate_before = self.inventory(student, 'gate-before')
        assert not any(r['technique'] == 'cloak' for r in self.knowledge(student, 'gate-knowledge-before'))
        self.graph(student, {'do': {'skill': 'craft', 'item': 'cloak'}})
        failure = self.wait(lambda: self.feedback(student, "don't know how to make a cloak", 'gate-feedback'), 'gating feedback')
        assert 'experimenting with fiber or hide' in failure[-1]['text']
        assert 'someone who knows it' in failure[-1]['text'] and 'from writing' in failure[-1]['text']
        assert self.inventory(student, 'gate-after') == gate_before
        assert not self.sql(f"SELECT * FROM practice WHERE actor = {student} AND skill = 'craft'", 'gate-practice')
        self.admin('grant_know_how', student, 'cloak')
        self.graph(student, {'do': {'skill': 'craft', 'item': 'cloak'}})
        self.wait(lambda: any(r['item'] == 'cloak' for r in self.inventory(student, 'gate-unlocked')), 'craft after learning')
        practice = self.sql(f"SELECT * FROM practice WHERE actor = {student} AND skill = 'craft'", 'practice-one')
        assert len(practice) == 1 and practice[0]['uses'] == 1
        self.graph(student, {'do': {'skill': 'craft', 'item': 'cloak'}})
        self.wait(lambda: self.sql(f"SELECT * FROM practice WHERE actor = {student} AND skill = 'craft'", 'practice-two')[0]['uses'] == 2, 'practice increments')
        self.pass_feature('gating, truthful learning feedback and practice', ['gate-feedback.json', 'gate-before.json', 'gate-after.json', 'gate-unlocked.json', 'practice-one.json', 'practice-two.json'])

        for item, phrase in [('leather', 'made with tanning'), ('stone', 'no technique called stone'), ('cloak', "don't know cloak yourself")]:
            self.graph(teacher, {'do': {'skill': 'teach', 'target': {'id': student}, 'item': item}})
            got = self.wait(lambda: self.feedback(teacher, phrase, 'teach-feedback-' + item), 'truthful teaching feedback')
            if item == 'stone':
                assert 'tanning' in got[-1]['text'] and 'cloak' in got[-1]['text']
        self.graph(teacher, {'do': {'skill': 'teach', 'target': {'id': student}, 'item': 'spear'}})
        taught = self.wait(lambda: [r for r in self.knowledge(student, 'taught-knowledge') if r['technique'] == 'spear'], 'teaching')
        assert len(taught) == 1 and taught[0]['source'] == 'taught by Walker1'
        self.graph(teacher, {'do': {'skill': 'teach', 'target': {'id': student}, 'item': 'spear'}})
        self.wait(lambda: self.feedback(teacher, 'already know spear', 'teach-repeat-feedback'), 'duplicate teaching refusal')
        assert taught == [r for r in self.knowledge(student, 'taught-after-repeat') if r['technique'] == 'spear']
        self.pass_feature('teaching and truthful technique feedback', ['taught-knowledge.json', 'taught-after-repeat.json', 'teach-repeat-feedback.json', 'teach-feedback-leather.json', 'teach-feedback-stone.json', 'teach-feedback-cloak.json', 'teaching_names_real_techniques.log'])

        self.admin('grant_know_how', learner, 'cloak')
        self.admin('grant_items', learner, 'hide', 20)
        assert not any(r['technique'] == 'tanning' for r in self.knowledge(learner, 'experiment-before'))
        block = {'seq': [{'do': {'skill': 'experiment', 'item': 'hide'}} for _ in range(10)]}
        self.graph(learner, block, block)
        worked = self.wait(lambda: [r for r in self.knowledge(learner, 'experiment-after') if r['technique'] == 'tanning'], 'learning by experiment', 260)
        assert len(worked) == 1 and worked[0]['source'] == 'worked it out'
        self.admin('set_behavior', learner, json.dumps({'wait': 120}))
        self.pass_feature('worked it out', ['experiment-before.json', 'experiment-after.json'])

        for actor in (reader, sign_reader):
            self.admin('grant_know_how', actor, 'writing')
        self.admin('grant_items', teacher, 'wood', 4)
        tablet_text = 'Bind two wood and one stone tightly to make a spear.'
        self.graph(teacher, {'do': {'skill': 'write', 'item': 'tablet', 'text': tablet_text, 'topic': 'spear'}},
                   {'do': {'skill': 'give', 'target': {'id': reader}, 'item': 'tablet', 'qty': 1}})
        tablet = self.wait(lambda: [r for r in self.sql(f'SELECT * FROM artifact WHERE holder = {reader}', 'tablet-given') if r['kind'] == 'tablet'], 'written tablet transferred')
        assert tablet[0]['author'] == teacher and tablet[0]['text'] == tablet_text and tablet[0]['topic'] == 'spear'
        self.graph(reader, {'do': {'skill': 'read'}})
        read = self.wait(lambda: [r for r in self.knowledge(reader, 'read-knowledge') if r['technique'] == 'spear'], 'learning from tablet')
        assert len(read) == 1 and read[0]['source'] == "read Walker1's tablet"
        self.graph(reader, {'do': {'skill': 'read'}})
        self.wait(lambda: self.sql(f"SELECT * FROM practice WHERE actor = {reader} AND skill = 'read'", 'read-practice')[-1]['uses'] >= 2, 'second reading')
        assert read == [r for r in self.knowledge(reader, 'read-after-repeat') if r['technique'] == 'spear']
        self.admin('grant_know_how', teacher, 'planting')
        self.graph(teacher, {'do': {'skill': 'write', 'item': 'sign', 'text': 'Plant berries here.', 'topic': 'planting'}})
        sign = self.wait(lambda: [r for r in self.sql(f'SELECT * FROM artifact WHERE author = {teacher}', 'sign-written') if r['kind'] == 'sign'], 'sign written')
        structure_id = sign[0]['holder'] ^ STRUCTURE_BIT
        structures = self.sql(f'SELECT * FROM structure WHERE id = {structure_id}', 'sign-structure')
        assert structures[0]['kind'] == 'sign' and structures[0]['owner'] == teacher
        self.graph(sign_reader, {'do': {'skill': 'read', 'target': {'nearest': 'sign'}}})
        sign_knowledge = self.wait(lambda: [r for r in self.knowledge(sign_reader, 'sign-knowledge') if r['technique'] == 'planting'], 'learning from sign')
        assert sign_knowledge[0]['source'] == "read Walker1's sign"
        self.pass_feature('tablets, signs and reading idempotence', ['tablet-given.json', 'read-knowledge.json', 'read-after-repeat.json', 'read-practice.json', 'sign-written.json', 'sign-structure.json', 'sign-knowledge.json'])

        before_death = self.knowledge(reader, 'death-before-knowledge')
        held_before = self.sql(f'SELECT * FROM artifact WHERE holder = {reader}', 'death-before-tablets')
        assert before_death and held_before
        self.admin('kill', reader, 'verify knowledge cleanup')
        assert not self.knowledge(reader, 'death-after-knowledge')
        assert not self.sql(f'SELECT * FROM practice WHERE actor = {reader}', 'death-after-practice')
        assert not self.sql(f'SELECT * FROM character WHERE id = {reader}', 'dead-character')[0]['alive']
        remains = self.sql(f"SELECT * FROM structure WHERE owner = {reader} AND kind = 'remains'", 'death-remains')
        assert len(remains) == 1
        after = self.sql(f'SELECT * FROM artifact WHERE holder = {STRUCTURE_BIT | remains[0]["id"]}', 'death-after-tablets')
        assert len(after) == len(held_before)
        for old, new in zip(held_before, after):
            assert dict(old, holder=new['holder']) == new
        assert self.knowledge(student, 'survivor-knowledge')
        self.pass_feature('death erases know-how and preserves tablets', ['death-before-knowledge.json', 'death-after-knowledge.json', 'death-before-tablets.json', 'death-after-tablets.json', 'death-remains.json', 'dead-character.json', 'death-after-practice.json', 'survivor-knowledge.json'])

    def process(self, label, args, env=None):
        stream = (self.directory / (label + '.log')).open('a')
        self.streams.append(stream)
        process = subprocess.Popen(list(map(str, args)), cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        self.processes.append(process)
        self.state['pids'][label] = {'pid': process.pid, 'start': Path(f'/proc/{process.pid}/stat').read_text().split()[21]}
        self.save()
        return process

    def memory_integration(self):
        oren = self.sql("SELECT * FROM character WHERE name = 'Oren Hale'", 'oren')[0]['id']
        teodor = self.sql("SELECT * FROM character WHERE name = 'Teodor Vane'", 'teodor')[0]['id']
        self.admin('set_behavior', oren, json.dumps({'wait': 120}))
        self.harness('player', 'join', 'KnowledgeWitness')
        witness = self.sql("SELECT id FROM character WHERE name = 'KnowledgeWitness'", 'witness')[0]['id']
        self.admin('place_near', witness, oren)
        for message in ('The amber ford is safe today.', 'I saw an amber marker at the ford.', 'Remember the flood and the millstone.', 'Teodor asked about the amber ford.'):
            self.harness('player', 'say', message, '--to', str(oren))
            time.sleep(2.1)
        pending = sorted(self.sql(f'SELECT * FROM experience WHERE observer = {oren}', 'memory-input'), key=lambda r: r['id'])
        meaningful = [e for e in pending[:40] if e['salience'] >= 0.2]
        assert meaningful
        heard = next(e for e in meaningful if 'The amber ford is safe today.' in e['text'])
        patch = {'summary': 'Knowledge proof consolidation.',
                 'nodes': [{'key': 'idea:knowledge_marker', 'labels': ['Idea'], 'name': 'Amber ford knowledge marker'},
                           {'key': 'idea:marker_detail', 'labels': ['Idea']}],
                 'edges': [{'from': 'self', 'rel': 'KNOWS', 'to': 'idea:knowledge_marker', 'confidence': 1},
                           {'from': 'idea:knowledge_marker', 'rel': 'SAFE_AT', 'to': 'place:amber_ford', 'confidence': 1},
                           {'from': 'self', 'rel': 'AGREED', 'to': 'idea:knowledge_marker', 'confidence': 1},
                           {'from': 'idea:knowledge_marker', 'rel': 'WITH', 'to': f'person:{teodor}', 'confidence': 1},
                           {'from': 'idea:marker_detail', 'rel': 'CHILD_OF', 'to': 'idea:knowledge_marker', 'confidence': 1},
                           {'from': 'idea:knowledge_marker', 'rel': 'PARENT_OF', 'to': 'idea:marker_detail', 'confidence': 1}],
                 'merge': [{'from': 'stance:strangers_are_trouble', 'into': 'stance:outsiders_are_trouble'}],
                 'remember': [{'exp': heard['id'], 'gist': 'KnowledgeWitness said the amber ford is safe today.'}],
                 'relations': [{'id': teodor, 'trust': 66, 'affinity': 33, 'label': 'knowledge witness', 'note': 'Discussed the amber ford.'}],
                 'judgments': [{'key': 'amber_ford_is_safe', 'value': 0.91, 'why': 'Knowledge proof fixture.'}],
                 'places': [{'name': 'Amber Ford', 'x': 30, 'y': 40}], 'identity': None}
        for edge in patch['edges']:
            edge['because'] = [heard['id']]
        script = {'replies': {'consolidate': patch,
                             'think': {'thought': 'Consider the knowledge marker and the old flood.', 'intend': ['wait'], 'say': None},
                             'deliberate': {'thought': 'I will wait.', 'plan': 'knowledge proof wait', 'graph': {'wait': 120}, 'say': None, 'acts': []}}}
        (self.directory / 'fake-script.json').write_text(json.dumps(script, indent=2))
        fake = self.process('fake', [sys.executable, FAKE, '--port', '0', '--log', self.directory / 'requests.jsonl', '--script', self.directory / 'fake-script.json'])
        self.wait(lambda: 'READY ' in (self.directory / 'fake.log').read_text(), 'fake model readiness', 10)
        port = int(re.search(r'READY http://127.0.0.1:(\d+)/v1', (self.directory / 'fake.log').read_text())[1])
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as response:
            assert response.status == 200
        models = {'default': 'fake', 'profiles': {'fake': {'base_url': f'http://127.0.0.1:{port}/v1', 'model': 'knowledge-local-fake',
                  'key_env': 'LIVING_VERIFY_FAKE_KEY', 'max_tokens': 2048,
                  'reasoning_effort': {p: p for p in ('think', 'deliberate', 'consolidate', 'talk')}}}}
        (self.directory / 'models.json').write_text(json.dumps(models, indent=2))
        login = subprocess.run([str(ROOT / 'living/tools/stdb'), 'login', 'show', '--token'], capture_output=True, text=True, check=True)
        tokens = re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', login.stdout)
        assert len(tokens) == 1
        env = dict(os.environ, LIVING_ROOT=str(ROOT), LIVING_SERVER='http://127.0.0.1:3300', LIVING_DB=self.db,
                   LIVING_RUN=self.db, LIVING_SEED='authored-test', LIVING_MODELS=str(self.directory / 'models.json'),
                   LIVING_ONLY=str(oren), LIVING_TOKEN=tokens[0], LIVING_NEO4J='on',
                   LIVING_NEO4J_URI=self.state['uri'], LIVING_NEO4J_PASSWORD=self.state['password'],
                   LIVING_VERIFY_FAKE_KEY='local-only', LIVING_LLM_PER_MIN='0', LIVING_CONCURRENCY='2',
                   LIVING_LOD='0', NO_PROXY='127.0.0.1,localhost', RUST_LOG='info,neo4rs=warn,spacetimedb_sdk=warn')
        binary = BUILD / 'release/living-mind'
        hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in [*sorted((ROOT / 'living/mind/src').rglob('*.rs')), binary]}
        (self.directory / 'source-hashes.json').write_text(json.dumps(hashes, indent=2))
        self.process('mind', [binary], env)
        (self.directory / 'mind-environment.json').write_text(json.dumps({key: env[key] for key in (
            'LIVING_SERVER', 'LIVING_DB', 'LIVING_RUN', 'LIVING_SEED', 'LIVING_ONLY', 'LIVING_NEO4J',
            'LIVING_NEO4J_URI', 'LIVING_MODELS', 'LIVING_LOD')}, indent=2))
        self.wait(lambda: 'world subscribed:' in (self.directory / 'mind.log').read_text(), 'mind subscription')
        assert 'personal memory graphs in Neo4j at 127.0.0.1:7691' in (self.directory / 'mind.log').read_text()
        judgment = self.wait(lambda: [r for r in self.sql(f'SELECT * FROM judgment WHERE actor = {oren}', 'projection-judgment') if r['key'] == 'amber_ford_is_safe'], 'consolidation projected', 100)
        assert abs(judgment[0]['value'] - 0.91) < 0.02 and judgment[0]['why'] == 'Knowledge proof fixture.'
        feelings = self.sql(f'SELECT * FROM relation WHERE actor = {oren}', 'projection-relation')
        assert any(r['other'] == teodor and r['trust'] == 66 and r['affinity'] == 33 and r['label'] == 'knowledge witness' for r in feelings)
        places = self.sql(f'SELECT * FROM place WHERE actor = {oren}', 'projection-place')
        assert any(r['name'] == 'Amber Ford' and r['x'] == 30 and r['y'] == 40 for r in places)
        persona = self.sql(f'SELECT * FROM persona WHERE id = {oren}', 'projection-persona')
        assert 'I keep the mill' in persona[0]['narrative']
        beliefs = self.sql(f'SELECT * FROM belief WHERE actor = {oren}', 'projection-belief')
        assert 'knowledge_marker' in json.dumps(beliefs)
        thoughts = self.sql(f'SELECT * FROM thought WHERE actor = {oren}', 'consolidation-thought')
        assert any(t['kind'] == 'consolidate' and 'Knowledge proof consolidation.' in t['summary'] for t in thoughts)
        graph_filter = f"{{run: '{self.db}', actor: {oren}}}"
        nodes = self.cypher(f'MATCH (n:Concept {graph_filter}) RETURN n.key AS key, labels(n) AS labels, properties(n) AS props ORDER BY key;', 'graph-nodes').stdout
        edges = self.cypher(f'MATCH (n:Concept {graph_filter})-[r]->(m:Concept) RETURN n.key AS source, type(r) AS type, r.rel AS rel, m.key AS target, properties(r) AS props ORDER BY source, type, target;', 'graph-edges').stdout
        assert 'knowledge_marker' in nodes and 'IdentityVersion' in nodes and 'Memory' in nodes
        assert 'SAFE_AT' in edges and 'RELATES' in edges
        assert all(t in edges for t in ('KNOWS', 'FEELS', 'JUDGES', 'WAS', 'INVOLVES', 'CHILD_OF', 'PARENT_OF', 'MERGED_INTO', 'AGREED', 'WITH'))
        self.pass_feature('real consolidation and authority projection', ['requests.jsonl', 'graph-nodes.txt', 'graph-edges.txt', 'projection-relation.json', 'projection-judgment.json', 'projection-place.json', 'projection-persona.json', 'projection-belief.json', 'consolidation-thought.json'])

        sequence = max(r['sequence'] for r in entries(self.directory / 'requests.jsonl'))
        self.admin('set_behavior', oren, json.dumps({'think': 'knowledge_marker amber ford flood millstone'}))
        def recalled_prompt():
            for entry in entries(self.directory / 'requests.jsonl'):
                if entry['sequence'] > sequence and entry['purpose'] == 'deliberate':
                    text = '\n'.join(m['content'] for m in entry['body']['messages'] if m['role'] == 'user')
                    if 'KNOWS' in text and 'Amber ford knowledge marker (idea:knowledge_marker)' in text and '[before all this] The flood took the lower field and cracked the millstone' in text:
                        return entry
            return None
        recalled = self.wait(recalled_prompt, 'later deliberation recalls facts and authored past', 70)
        (self.directory / 'recalled-deliberation.json').write_text(json.dumps(recalled, indent=2))
        memories = self.cypher(f'MATCH (n:Concept {graph_filter}) WHERE n:Memory RETURN n.exp AS exp, n.gist AS gist, n.formative AS formative, n.recalled_t AS recalled_t ORDER BY exp;', 'graph-memories').stdout
        memory_rows = list(csv.reader(memories.splitlines(), skipinitialspace=True))[1:]
        assert any(int(r[0]) >= STRUCTURE_BIT and 'The flood took the lower field' in r[1]
                   and r[2].lower() == 'true' and int(r[3]) > 0 for r in memory_rows)
        self.pass_feature('situational recall and authored seed past', ['recalled-deliberation.json', 'graph-memories.txt'])
        cases = [{'id': 'marker-budget-1', 'run': self.db, 'actor': oren, 'keys': [['idea:knowledge_marker', 1]], 'texts': [], 'budget': 1},
                 {'id': 'marker-budget-8', 'run': self.db, 'actor': oren, 'keys': [['idea:knowledge_marker', 1]], 'texts': [], 'budget': 8},
                 {'id': 'authored-flood', 'run': self.db, 'actor': oren, 'keys': [], 'texts': [['flood millstone', 1]], 'budget': 8},
                 {'id': 'uncued', 'run': self.db, 'actor': oren, 'keys': [], 'texts': [['quasar absent', 1]], 'budget': 8}]
        path = self.directory / 'recall-cases.json'
        path.write_text(json.dumps(cases, indent=2))
        self.cargo(['test', '-p', 'living-mind', 'recall_replay', '--', '--ignored', '--nocapture'], 'recall_replay.log', LIVING_RECALL_CASES=str(path))
        replay = [json.loads(line) for line in (self.directory / 'recall_replay.log').read_text().splitlines() if line.startswith('{"actor"')]
        assert len(replay) == 4
        by_id = {r['id']: r for r in replay}
        assert len(by_id['marker-budget-1']['facts']) == 1
        assert 1 < len(by_id['marker-budget-8']['facts']) <= 8
        assert any('The flood took the lower field' in m for m in by_id['authored-flood']['memories'])
        assert not by_id['uncued']['facts']
        self.pass_feature('recall_replay and fact budgets', ['recall-cases.json', 'recall_replay.log'])

    def cleanup(self):
        report = {'processes': [], 'db': self.db, 'container': self.state['container']}
        failures = []
        for label, owned in reversed(list(self.state['pids'].items())):
            pid = owned['pid']
            proc = Path(f'/proc/{pid}/stat')
            if not proc.exists() or proc.read_text().split()[21] != owned['start']:
                report['processes'].append({'name': label, 'pid': pid, 'stop': 'already exited'})
                continue
            os.kill(pid, signal.SIGTERM)
            end = time.monotonic() + 10
            while time.monotonic() < end:
                if not proc.exists() or proc.read_text().split()[2] == 'Z':
                    break
                time.sleep(0.2)
            forced = proc.exists() and proc.read_text().split()[2] != 'Z'
            if forced:
                os.kill(pid, signal.SIGKILL)
            report['processes'].append({'name': label, 'pid': pid, 'stop': 'SIGKILL' if forced else 'SIGTERM'})
        for process in self.processes:
            process.wait(timeout=10)
        self.state['pids'] = {}
        if self.journal.exists():
            copied = self.directory / 'journal'
            shutil.copytree(self.journal, copied, dirs_exist_ok=True)
            for source in self.journal.glob('*'):
                if source.is_file():
                    assert source.read_bytes() == (copied / source.name).read_bytes()
            shutil.rmtree(self.journal)
        report['journal_removed'] = not self.journal.exists()
        shared_state = self.directory / 'state.json'
        if shared_state.exists():
            try:
                self.harness('cleanup')
            except Exception as error:
                failures.append(str(error))
        request = urllib.request.Request(f'http://127.0.0.1:3300/v1/database/{self.db}/sql', b'SELECT * FROM world', {'Content-Type': 'text/plain'})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                report['database_deleted'] = False
        except urllib.error.HTTPError as error:
            report['database_deleted'] = error.code == 404
        if not report['database_deleted']:
            failures.append('database still exists')
        exists = self.command(['docker', 'container', 'exists', self.state['container']], 'cleanup-container.log', check=False).returncode == 0
        if exists and self.state['container_started']:
            label = self.command(['docker', 'inspect', self.state['container'], '--format', '{{index .Config.Labels "sao.verify.run"}}'], 'cleanup-container.log').stdout.strip()
            if label != self.name:
                failures.append('scratch container ownership label does not match; left untouched')
            else:
                self.command(['docker', 'logs', self.state['container']], 'neo4j.log', check=False)
                self.command(['docker', 'stop', '-t', '30', self.state['container']], 'cleanup-container.log', check=False)
                self.command(['docker', 'inspect', self.state['container'], '--format', '{{.State.ExitCode}}'], 'cleanup-container.log', check=False)
                self.command(['docker', 'rm', '-v', self.state['container']], 'cleanup-container.log', check=False)
        report['container_removed'] = self.command(['docker', 'container', 'exists', self.state['container']], 'cleanup-container.log', check=False).returncode == 1
        if not report['container_removed']:
            failures.append('scratch Neo4j removal failed')
        else:
            self.state['container_started'] = False
        for stream in self.streams:
            stream.close()
        if report['container_removed']:
            self.state.pop('password', None)
        self.save()
        report['evidence_survives'] = (self.directory / 'actions.log').exists()
        report['errors'] = failures
        (self.directory / 'cleanup.json').write_text(json.dumps(report, indent=2))
        if failures:
            raise RuntimeError('; '.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'cleanup'])
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    run = Run(args.run, existing=args.action == 'cleanup')
    if args.action == 'cleanup':
        run.cleanup()
        return
    error = None
    try:
        run.harness('launch', '--seed', 'authored-test')
        run.harness('doctor')
        run.start_neo4j()
        run.graph_tests()
        run.authority()
        run.memory_integration()
    except BaseException as caught:
        error = caught
        (run.directory / 'failure.log').write_text(traceback.format_exc())
    finally:
        run.cleanup()
    if error:
        raise RuntimeError(f'proof failed; evidence in {run.directory}') from error
    print(f'All knowledge proofs passed. Evidence retained at {run.directory}', flush=True)


if __name__ == '__main__':
    main()
