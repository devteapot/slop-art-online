#!/usr/bin/env python3
"""Run the client suite, or stream one ad-hoc query on a launched client-* run."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]
HARNESS = ROOT / '.agents/skills/verify/scripts/verify.py'
SPEC = importlib.util.spec_from_file_location('verify_harness', HARNESS)
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)
BINARY = ROOT / '.local/living/verify/target-client/debug/verify-client-probe'
BASE_QUERIES = [
    'SELECT * FROM world',
    'SELECT * FROM terrain_chunk',
    'SELECT * FROM character',
    'SELECT * FROM body',
    'SELECT * FROM vitals',
    'SELECT * FROM activity',
    'SELECT * FROM inventory',
    'SELECT * FROM resource_node',
    'SELECT * FROM structure',
    'SELECT * FROM brain',
    'SELECT * FROM mind_state',
    'SELECT * FROM persona',
    'SELECT * FROM relation',
    'SELECT * FROM belief',
    'SELECT * FROM judgment',
    'SELECT * FROM place',
    'SELECT * FROM thought',
    'SELECT * FROM chronicle',
    'SELECT * FROM stats',
    'SELECT * FROM bond_offer',
    'SELECT * FROM expecting',
    'SELECT * FROM mind_cursor',
    'SELECT * FROM know_how',
    'SELECT * FROM artifact',
    'SELECT * FROM trade_offer',
    'SELECT * FROM background',
    'SELECT * FROM gate',
]
# Private in every build: the authority's bookkeeping and developer audit truth
# (docs/PERCEPTION.md). The observer and the mind service read them as the database owner.
PRIVATE = ['clock', 'steer', 'walk_route', 'rot', 'wake', 'familiar', 'deliberation', 'rearing',
           'act_queue', 'pasture', 'tick_timer', 'slow_timer', 'infant_cry',
           'combat_seen', 'missile', 'skill_use', 'readiness', 'skill_code',
           'routine', 'routine_stat', 'background', 'brain', 'mind_state', 'mind_cursor',
           'persona', 'relation', 'belief', 'judgment', 'thought', 'chronicle', 'stats',
           'bond_offer', 'community', 'membership', 'join_request', 'trade_offer',
           'expecting', 'genome', 'practice', 'activity', 'artifact', 'perceived',
           'projected', 'reveal', 'acquaintance', 'connection', 'presence',
           'guest', 'judged', 'rhythm',
           # Records the world's rules keep (docs/WORLD_RULES.md); a player reads its own via my_records.
           'record', 'record_party', 'record_clock',
           # A world's own law values (its seed's `rules`; docs/WORLD_RULES.md, since laws-2).
           'world_law',
           # A floor module's staged genesis (floor.rs), private since floors were added.
           'floor_seed', 'genesis_timer',
           # Frames: what each player was last shown of others (docs/PERCEPTION.md, "Frames").
           'motion_seen', 'fighter_seen', 'doing_seen', 'line_seen',
           # Which character each person plays (perception.rs `current`); a player reads it through my_characters.
           'player',
           # Heard, not seen (fov-1): who each player hears, its secret salt, and every change of a
           # world law on a running world (`set_world_law`).
           'heard', 'hear_salt', 'law_change']
# Private in the default `scoped` build; public only in a LIVING_PERCEPTION=open build (diagnostics).
SCOPED = ['body', 'character', 'fighter', 'doing', 'vitals', 'experience', 'place',
          'inventory', 'know_how']
# The per-sender views: what a player perceives and its own state.
VIEWS = ['seen_bodies', 'seen_characters', 'seen_fighters', 'seen_doing', 'my_body', 'my_fighter', 'my_doing', 'my_characters',
         'my_vitals', 'my_experience', 'my_places', 'my_inventory', 'my_know_how',
         'my_deliberations', 'my_combat', 'my_readiness', 'my_skill_uses', 'my_records', 'my_offers', 'heard_sounds']
SEEN = ['seen_bodies', 'seen_characters', 'seen_fighters', 'seen_doing']
# The player's own living character's body, fighter and doing rows (others' come as copies in seen_*).
BODY = ['my_body', 'my_fighter', 'my_doing']
OWN = BODY + ['my_characters', 'my_vitals', 'my_experience', 'my_places', 'my_inventory', 'my_know_how', 'my_offers']
OPAQUE = {4, 7}             # rock, wall (living_rules::map::Terrain); a drop (8) and a low thing (9) are see-through
UNWALKABLE = {2, 4, 7, 8, 9}  # water, rock, wall, drop, low
# The player's combat input (docs/COMBAT.md): refusals are recorded and told through
# `my_combat`, so these calls succeed for any living character.
PLAYER = {'use_skill': ['strike', 0, 0.0, 0.0], 'release_skill': ['block'],
          # The player's look (fov-1): any living character may send it.
          'human_face': [1.0, 0.0]}
MIND = ['mind_routines', 'mind_install', 'mind_say', 'mind_act', 'mind_skip',
        'mind_consolidated', 'mind_update', 'mind_judged']
ADMIN = {
    'set_paused': [False], 'install_script': [''], 'set_profile': [False],
    'spawn_crowd': [0, False], 'grant_know_how': [0, 'gather'], 'own_habits': [],
    'grant_repertoires': [], 'purge_dead': [], 'kill': [0, 'probe'],
    'set_background': [0, '{}'], 'grant_items': [0, 'berries', 0],
    'place_structure': [0, 'shelter'], 'set_behavior': [0, '{"wait":30}'],
    # Scene setup: a resource node beside a character (2026-11-11, goods-1).
    'place_resource': [0, 'tree', 0.0, 0.0, 0.0, 0],
    'place_near': [0, 0], 'seed_communities': [], 'spawn_battle': [0],
    'place_at': [0, 0.0, 0.0], 'spawn_skirmish': [0, 0.0], 'set_weather': [False, 0],
    'spawn_newcomer': ['probe'],
    # A floor module's runtime seed (floor.rs, admin only).
    'create_floor': ['{}'],
    # Stop a staged creation between steps, and carry it on (floor.rs, admin only).
    'stop_genesis': [], 'resume_genesis': [],
    # Change a law on a running world (fov-1, admin only).
    'set_world_law': ['fov_on', 'false'],
}


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def thought(reference):
    return {'kind': 'probe', 'summary': 'scripted protocol fixture',
            'detail': 'VERIFY_CLIENT_RAW_' + reference, 'latency_ms': 0, 'tokens': 0,
            'model': 'scripted-no-model-call', 'reference': reference}


def mind_args(name, actor, marker):
    t = thought(marker + '-' + name)
    return {
        'mind_routines': [actor, [{'name': 'client probe', 'graph': '{"wait":30}'}]],
        'mind_install': [actor, '{"wait":30}', marker, '', 0, 0, t],
        'mind_say': [actor, '', 0, 0, t],
        'mind_act': [actor, ['{"do":"signal","item":"client-probe"}'], 'probe'],
        'mind_skip': [actor, 0, t], 'mind_consolidated': [actor, 0],
        'mind_judged': [actor, [{'q': 'client probe', 'value': 0.5, 'choice': '', 'ttl_ms': 1000}]],
        'mind_update': [actor, {'persona': {'some': {'narrative': marker, 'values': [],
                         'goals': [], 'traits': '{}', 'mood': 'probe', 'pastimes': [], 'calling': ''}},
                         'relations': [], 'beliefs': {'none': []}, 'judgments': [],
                         'places': [], 'thought': {'some': t}, 'replace': False}],
    }[name]


class DropProxy:
    def __init__(self, drop_file):
        self.drop_file = drop_file
        self.stop = threading.Event()
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.listener.settimeout(.1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.pairs = []
        self.drops = 0
        self.accepted = 0

    def __enter__(self):
        self.thread.start()
        return self

    def serve(self):
        while not self.stop.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            upstream = socket.create_connection(('127.0.0.1', int(V.URL.rsplit(':', 1)[1])), timeout=5)
            self.pairs.append((client, upstream))
            self.accepted += 1
            threading.Thread(target=self.relay, args=(client, upstream), daemon=True).start()

    def relay(self, client, upstream):
        try:
            while not self.stop.is_set():
                if self.drop_file.exists() and self.drops == 0:
                    self.drops += 1
                    return
                ready, _, _ = select.select([client, upstream], [], [], .05)
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is client else client).sendall(data)
        except OSError:
            pass
        finally:
            for sock in (client, upstream):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()

    def __exit__(self, *_):
        self.stop.set()
        self.listener.close()
        for pair in self.pairs:
            for sock in pair:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        self.thread.join(timeout=2)


class Run:
    def __init__(self, name):
        if not re.fullmatch(r'client-[a-zA-Z0-9-]+', name):
            raise ValueError('run must be client- followed by letters, digits or hyphens')
        self.state = V.load(name)
        if self.state['db'] != 'verify-' + name or not self.state.get('published'):
            raise ValueError('launch this scratch run with verify.py first')
        if self.state.get('started_container'):
            raise ValueError('this task requires the shared container to be up before launch')
        self.directory = V.run_dir(name)
        self.mode = self.state.get('perception', 'scoped')
        self.results = []
        self.matrix = []
        self.secrets = [self.state.get('token', '')]

    def check(self, name, okay, evidence, detail='', known=False):
        status = ('XPASS' if okay else 'XFAIL') if known else ('PASS' if okay else 'FAIL')
        self.results.append({'check': name, 'status': status, 'evidence': evidence, 'detail': detail})
        print(f'{status} {name}: {detail}', flush=True)

    def probe(self, name, queries, token=None, seconds=0, uri=V.URL, drop_file=None,
              capture_credential=False, until_actor=None):
        request = {'uri': uri, 'db': self.state['db'], 'token': token,
                   'queries': queries, 'seconds': seconds,
                   'drop_file': str(drop_file) if drop_file else None, 'until_actor': until_actor}
        read_fd, write_fd = os.pipe() if capture_credential else (None, None)
        if write_fd is not None:
            request['credential_fd'] = write_fd
        try:
            result = subprocess.run([str(BINARY)], input=json.dumps(request), text=True,
                                    capture_output=True, timeout=65,
                                    pass_fds=(write_fd,) if write_fd is not None else ())
        finally:
            if write_fd is not None:
                os.close(write_fd)
        if read_fd is not None:
            credential = os.read(read_fd, 8192).decode()
            os.close(read_fd)
            self.secrets.append(credential)
        else:
            credential = None
        value = json.loads(result.stdout)
        value['process_exit'] = result.returncode
        value['sdk_stderr'] = result.stderr
        write(self.directory / (name + '.json'), value)
        if result.returncode:
            raise RuntimeError(f'{name} probe failed; see {name}.json')
        return (value, credential) if capture_credential else value

    def call(self, label, token, reducer, args, expected=None, expected_status=530):
        code, body = V.http(f"/v1/database/{self.state['db']}/call/{reducer}", args, token)
        okay = code == 200 if expected is None else code == expected_status and expected in body
        row = {'identity': label, 'reducer': reducer, 'args': args, 'http_status': code,
               'body': body, 'expected': expected or 'accepted', 'pass': okay}
        self.matrix.append(row)
        write(self.directory / 'reducers.json', self.matrix)
        V.log(self.state, f"client {label} {reducer}{json.dumps(args)} -> {code} {body.strip()}")
        return okay

    def query(self, query, as_player, seconds, name, as_admin=False):
        if as_player and not self.state.get('token'):
            raise ValueError('no player yet: run verify.py player join NAME first')
        if as_admin:
            self.secrets.append(V.admin_token())
        path = self.directory / (name + '.jsonl')
        stderr_path = self.directory / (name + '-sdk.log')
        request = {'uri': V.URL, 'db': self.state['db'],
                   'token': self.secrets[-1] if as_admin else self.state.get('token') if as_player else None,
                   'queries': [query], 'seconds': seconds, 'stream': True}
        final = None
        with path.open('x') as evidence, stderr_path.open('x') as sdk_log:
            with subprocess.Popen([str(BINARY)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=sdk_log, text=True) as process:
                try:
                    process.stdin.write(json.dumps(request))
                    process.stdin.close()
                    for line in process.stdout:
                        if any(secret and secret in line for secret in self.secrets):
                            raise RuntimeError('credential found in probe output')
                        final = json.loads(line)
                        evidence.write(line)
                        evidence.flush()
                        print(line.rstrip(), flush=True)
                    code = process.wait(timeout=5)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
        if code or not final or final.get('event') != 'complete':
            raise RuntimeError(f'subscription failed; see {path.name} and {stderr_path.name}')

    def ad_hoc_check(self):
        marker = 'VERIFY_CLIENT_ADHOC_SPEECH'
        path = self.directory / 'adhoc-suite.jsonl'
        with (self.directory / 'adhoc-suite.log').open('x') as output:
            with subprocess.Popen([str(SKILL / 'scripts/drive.py'), '--run', self.state['run'],
                                   '--query', "SELECT * FROM chronicle WHERE kind = 'speech'",
                                   '--seconds', '4', '--save', 'adhoc-suite', '--as-admin'],
                                  stdout=output, stderr=subprocess.STDOUT) as process:
                try:
                    deadline = time.monotonic() + 25
                    while time.monotonic() < deadline:
                        if path.exists() and '"event":"initial"' in path.read_text():
                            break
                        if process.poll() is not None:
                            raise RuntimeError('ad-hoc subscription stopped before initial rows')
                        time.sleep(.05)
                    else:
                        raise RuntimeError('ad-hoc subscription did not apply within 25 seconds')
                    called = subprocess.run([str(HARNESS), 'player', '--run', self.state['run'],
                                             'say', marker], capture_output=True, text=True, timeout=30)
                    output.write(called.stdout + called.stderr)
                    if called.returncode:
                        raise RuntimeError('harness speech failed; see adhoc-suite.log')
                    code = process.wait(timeout=30)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
        events = [json.loads(line) for line in path.read_text().splitlines()]
        self.check('ad-hoc speech insert', code == 0 and events[0]['event'] == 'initial' and
                   events[-1].get('event') == 'complete' and any(
                       event.get('event') == 'insert' and event.get('table') == 'chronicle' and
                       marker in event['row']['text'] for event in events), path.name)

    def source_inventory(self):
        viewer = (ROOT / 'living/viewer/src/net.rs').read_text()
        match = re.search(r'const QUERIES:.*?= &\[(.*?)\];', viewer, re.S)
        exact = re.findall(r'"(SELECT [^"]+)"', match[1])
        if exact != BASE_QUERIES:
            raise RuntimeError('viewer query set changed; update BASE_QUERIES and the feature map')
        # Tables are declared in tables.rs and in a few modules of their own (records.rs).
        tables = '\n'.join(p.read_text() for p in sorted((ROOT / 'living/authority/src').glob('*.rs')))
        accessor = lambda d: re.search(r'accessor\s*=\s*(\w+)', d)[1]
        definitions = re.findall(r'^#\[spacetimedb::table\((.*?)\)\]', tables, re.S | re.M)
        private = [accessor(d) for d in definitions if not re.search(r'\bpublic\b', d)]
        if set(private) != set(PRIVATE):
            raise RuntimeError(f'private table inventory changed; update PRIVATE: {set(private) ^ set(PRIVATE)}')
        opened = re.findall(r'^#\[cfg_attr\(open_tables, spacetimedb::table\((.*?)\)\)\]', tables, re.S | re.M)
        closed = re.findall(r'^#\[cfg_attr\(not\(open_tables\), spacetimedb::table\((.*?)\)\)\]', tables, re.S | re.M)
        scoped = [accessor(d) for d in opened if re.search(r'\bpublic\b', d)]
        if set(scoped) != set(SCOPED) or {accessor(d) for d in closed if not re.search(r'\bpublic\b', d)} != set(SCOPED):
            raise RuntimeError('scoped table inventory changed; update SCOPED')
        views = set()
        for path in (ROOT / 'living/authority/src').glob('*.rs'):
            views |= set(re.findall(r'#\[spacetimedb::view\(accessor = (\w+), public', path.read_text()))
        if views != set(VIEWS):
            raise RuntimeError(f'view inventory changed: {views ^ set(VIEWS)}')
        reducers = {}
        for path in (ROOT / 'living/authority/src').glob('*.rs'):
            text = path.read_text()
            for match in re.finditer(r'#\[spacetimedb::reducer\]\s*pub fn (\w+)\(', text):
                reducers[match[1]] = f'{path.relative_to(ROOT)}:{text[:match.start()].count(chr(10)) + 2}'
        expected = set(ADMIN) | set(MIND) | set(PLAYER) | {'join', 'human_move', 'human_act', 'human_say', 'tick', 'housekeeping', 'genesis_step'}
        if set(reducers) != expected:
            raise RuntimeError(f'reducer inventory changed: {set(reducers) ^ expected}')
        write(self.directory / 'source-inventory.json', {'base_queries': exact, 'private': private,
              'scoped': scoped, 'views': sorted(views), 'perception': self.mode,
              'reducers': reducers, 'sdk': '2.14.1', 'server': '2.14.1'})

    def run(self):
        self.source_inventory()
        scoped = self.mode == 'scoped'
        admin_token = V.admin_token()
        self.secrets.append(admin_token)
        # The observer reads developer audit truth as the database owner.
        initial = self.probe('observer-base', BASE_QUERIES, admin_token, seconds=4)
        if initial['status'] != 'applied':
            raise RuntimeError('observer base subscription refused; see observer-base.json')
        self.check('observer base initial rows', initial['initial']['counts']['character'] > 0 and
                   initial['initial']['counts']['world'] == 1, 'observer-base.json')
        self.check('observer base live updates', initial['body_updates'] > 0 and
                   initial['stats_updates'] > 0 and initial['final']['ticks'] > initial['initial']['ticks'],
                   'observer-base.json', f"body={initial['body_updates']}, stats={initial['stats_updates']}")
        refused = self.probe('anonymous-base', BASE_QUERIES)
        self.check('anonymous observer base refused', refused['status'] == 'rejected' and
                   'private' in refused.get('error', '').lower(), 'anonymous-base.json', refused.get('error', '')[:120])
        _, anonymous_token = self.probe('anonymous-connected', ['SELECT * FROM world'], capture_credential=True)
        ai = next(c for c in initial['final']['characters'] if c['ai'] and c['alive'] and c['stage'] >= 2 and c['kind'] == 'person')
        self.check('anonymous join', self.call('anonymous-connected', anonymous_token, 'join', ['ClientAnon']), 'reducers.json')
        self.call('anonymous-connected', anonymous_token, 'join', ['Again'], 'you already have a living character')
        second_code, second_body = V.http('/v1/identity', {})
        if second_code != 200:
            raise RuntimeError('could not mint second player identity')
        second = json.loads(second_body)
        self.secrets.append(second['token'])
        self.check('second player join', self.call('player-2', second['token'], 'join', ['ClientSecond']), 'reducers.json')
        players = self.probe('players', ['SELECT * FROM character'], admin_token)['final']['characters']
        own_ids = {c['name']: c['id'] for c in players if c['name'] in {'ClientAnon', 'ClientPrimary', 'ClientSecond'}}
        identities = [('anonymous-connected', anonymous_token, own_ids['ClientAnon']),
                      ('player-1', self.state['token'], own_ids['ClientPrimary']),
                      ('player-2', second['token'], own_ids['ClientSecond'])]
        for label, token, own in identities:
            self.call(label, token, 'join', ['Again'], 'you already have a living character')
            for reducer, args in ADMIN.items():
                self.call(label, token, reducer, args, 'admin only')
            other = own_ids['ClientSecond'] if label != 'player-2' else own_ids['ClientPrimary']
            for reducer in MIND:
                for actor in [ai['id'], other]:
                    self.call(label, token, reducer, mind_args(reducer, actor, label), 'not your character')
                self.call(label, token, reducer, mind_args(reducer, own, label))
            for reducer in ['tick', 'housekeeping']:
                self.call(label, token, reducer, [{'scheduled_id': 0, 'scheduled_at': {'Interval': 16667}}],
                          'No such procedure', expected_status=404)
            self.call(label, token, 'human_move', [1, 0, False])
            time.sleep(.1)
            self.call(label, token, 'human_move', [0, 0, False])
            self.call(label, token, 'human_act', ['{"wait":30}'])
            self.call(label, token, 'human_say', ['VERIFY_CLIENT_SPEECH_' + label, 0])
            for reducer, args in PLAYER.items():
                self.call(label, token, reducer, args)
        for reducer, args in ADMIN.items():
            self.call('anonymous-http-no-token', None, reducer, args, 'admin only')
        for reducer in MIND:
            self.call('anonymous-http-no-token', None, reducer, mind_args(reducer, ai['id'], 'anonymous'), 'not your character')
        for reducer in ['tick', 'housekeeping']:
            self.call('anonymous-http-no-token', None, reducer, [{'scheduled_id': 0, 'scheduled_at': {'Interval': 16667}}],
                      'No such procedure', expected_status=404)
        for reducer, args in [('human_move', [0, 0, False]), ('human_act', ['{"wait":30}']), ('human_say', ['probe', 0])] + list(PLAYER.items()):
            self.call('anonymous-http-no-token', None, reducer, args, 'you have no living character')
        self.call('anonymous-http-no-token', None, 'join', ['AnonHttp'])
        self.check('reducer permission matrix', all(row['pass'] for row in self.matrix), 'reducers.json',
                   f'{len(self.matrix)} calls, {sum(not row["pass"] for row in self.matrix)} mismatches')
        effects = self.probe('reducer-effects', BASE_QUERIES + ['SELECT * FROM routine'], admin_token)['final']
        self.check('own mind and player effects', all(
            any(t['actor'] == own and t['reference'].startswith(label) for t in effects['thoughts']) and
            any(r['actor'] == own and r['name'] == 'client probe' for r in effects['routines']) and
            any(b['id'] == own and b['plan'] == 'your command' for b in effects['brains']) and
            any(r['kind'] == 'speech' and r['a'] == own and 'VERIFY_CLIENT_SPEECH' in r['text'] for r in effects['chronicle'])
            for label, _, own in identities), 'reducer-effects.json')
        actor = ai['id']
        queries = [f'SELECT * FROM experience WHERE observer = {actor}',
                   f'SELECT * FROM routine WHERE actor = {actor}',
                   f'SELECT s.* FROM routine_stat s JOIN routine r ON s.id = r.id WHERE r.actor = {actor}']
        inspected = self.probe('inspected-character', queries, admin_token, seconds=2)
        end = inspected['final']
        routines = {r['id'] for r in end['routines']}
        self.check('per-character queries', inspected['status'] == 'applied' and
                   len(end['experiences']) > 0 and len(routines) > 0 and
                   all(r['observer'] == actor for r in end['experiences']) and
                   all(r['actor'] == actor for r in end['routines']) and
                   len(end['routine_stats']) > 0 and all(r['id'] in routines for r in end['routine_stats']), 'inspected-character.json',
                   f'actor={actor}, experiences={len(end["experiences"])}, routines={len(routines)}')
        # Every private table is refused to an anonymous client (WebSocket and HTTP SQL), and
        # the scoped ones to a player too; the scoped ones are private only in a scoped build.
        visibility = []
        player_token = self.state['token']
        for table in PRIVATE + (SCOPED if scoped else []):
            subscription = self.probe('private-' + table, ['SELECT * FROM ' + table])
            code, error = V.http(f"/v1/database/{self.state['db']}/sql", 'SELECT * FROM ' + table, raw=True)
            okay = subscription['status'] == 'rejected' and 'private' in subscription['error'].lower() and code != 200 and 'private' in error.lower()
            row = {'table': table, 'subscription': subscription, 'http_status': code, 'http_error': error}
            if table in SCOPED + ['thought', 'belief', 'persona', 'mind_state', 'perceived', 'projected', 'presence', 'guest', 'rhythm', 'player', 'heard', 'law_change']:
                as_player = self.probe('private-player-' + table, ['SELECT * FROM ' + table], player_token)
                code, error = V.http(f"/v1/database/{self.state['db']}/sql", 'SELECT * FROM ' + table, player_token, raw=True)
                okay = okay and as_player['status'] == 'rejected' and 'private' in as_player['error'].lower() and code != 200
                row.update({'player_subscription': as_player, 'player_http_status': code})
            visibility.append({**row, 'pass': okay})
        write(self.directory / 'visibility.json', visibility)
        self.check('private table visibility', all(v['pass'] for v in visibility), 'visibility.json',
                   f'{len(visibility)} tables ({self.mode} build)')
        # What a client reads to show a fire burning and a shared stock (2026-11-11, goods-1):
        # `structure.lit_until_ms` and `resource_node.pool` are public in every build, while the
        # inventory a fire's fuel would otherwise be is private when scoped.
        try:
            fires, stocks, error = self.sql_rows('SELECT id, kind, lit_until_ms FROM structure'), self.sql_rows('SELECT id, kind, pool FROM resource_node'), ''
        except RuntimeError as e:
            fires, stocks, error = [], [], str(e)
        write(self.directory / 'fire-signal.json', {'error': error, 'structures': fires[:20], 'resource_nodes': stocks[:20], 'counts': [len(fires), len(stocks)]})
        self.check('fire and shared-stock signals public to anonymous SQL', not error and fires and stocks and
                   all('lit_until_ms' in r for r in fires) and all('pool' in r for r in stocks), 'fire-signal.json', error[:120])
        # The minds' thoughts, raw replies included, never reach a client without the owner's token.
        leaked = self.probe('privacy-thought', ['SELECT * FROM thought'])
        self.check('anonymous thought privacy', leaked['status'] == 'rejected' and 'private' in leaked.get('error', '').lower(),
                   'privacy-thought.json')
        owner_thoughts = self.probe('owner-thought', ['SELECT * FROM thought'], admin_token)['final']['thoughts']
        if len({t['actor'] for t in owner_thoughts if t['detail'].startswith('VERIFY_CLIENT_RAW_')}) < 3:
            self.check('thought fixture coverage', False, 'owner-thought.json', 'fewer than three scripted raw markers')
        if scoped:
            leaked = self.probe('privacy-experience', ['SELECT * FROM experience'])
            self.check('anonymous experience privacy', leaked['status'] == 'rejected' and 'private' in leaked.get('error', '').lower(),
                       'privacy-experience.json')
        else:
            # The open build (LIVING_PERCEPTION=open, diagnostics) makes these tables public (docs/PERCEPTION.md).
            leaked = self.probe('privacy-experience', ['SELECT * FROM experience'])
            observable = leaked['status'] == 'applied' and len({e['observer'] for e in leaked['final']['experiences']}) > 1
            self.check('KNOWN ISSUE anonymous experience privacy (open build)', leaked['status'] == 'rejected', 'privacy-experience.json',
                       'denied' if leaked['status'] == 'rejected' else 'exposes foreign rows' if observable else 'no foreign rows', known=True)
            compat = self.probe('open-build-tables', ['SELECT * FROM ' + t for t in SCOPED])
            self.check('open build: the game client tables are public', compat['status'] == 'applied', 'open-build-tables.json')
        views = {}
        setup = subprocess.run([str(HARNESS), 'call', '--run', self.state['run'],
                                'set_behavior', json.dumps([actor, '{"think":"verify-client view fixture"}']),
                                '--as-admin'], capture_output=True, text=True, timeout=30)
        (self.directory / 'admin-scene-setup.log').write_text(setup.stdout + setup.stderr)
        if setup.returncode:
            raise RuntimeError('admin set_behavior failed; see admin-scene-setup.log')
        views['admin'] = self.probe('view-admin', ['SELECT * FROM my_deliberations'], admin_token, seconds=55, until_actor=actor)
        view = views['admin']
        self.check('admin own deliberations', view['status'] == 'applied' and len(view['final']['deliberations']) > 0 and
                   all(d['controller'] == view['identity'] for d in view['final']['deliberations']) and
                   any(d['actor'] == actor for d in view['final']['deliberations']), 'view-admin.json')
        for label, token, _ in identities:
            views[label] = self.probe('view-' + label, ['SELECT * FROM my_deliberations'], token, seconds=1)
        views['anonymous'] = self.probe('view-anonymous', ['SELECT * FROM my_deliberations'])
        self.check('player and anonymous views empty', all(v['status'] == 'applied' and
                   v['final']['counts']['my_deliberations'] == 0 for label, v in views.items() if label != 'admin'), 'view-*.json')
        if 'admin' in views:
            retained = self.probe('view-admin-after-players', ['SELECT * FROM my_deliberations'], admin_token)
            self.check('view filtering with foreign requests present',
                       len(views['admin']['final']['deliberations']) > 0 and
                       len(retained['final']['deliberations']) > 0 and
                       all(v['final']['counts']['my_deliberations'] == 0
                           for label, v in views.items() if label != 'admin'),
                       'view-*.json', 'admin requests exist before and after empty foreign views')
        # Combat (docs/COMBAT.md): each player's refused strike is told to that player
        # only; anonymous sees no feed; uses are scoped to the caller's characters; the
        # fighter and skill_card tables are public.
        # Feed rows live 4 s: refuse a strike for each player now (the matrix's are long gone).
        for label, token, _ in identities:
            self.call(label, token, 'use_skill', ['strike', 0, 0.0, 0.0])
        combat = {label: self.probe('combat-' + label, ['SELECT * FROM my_combat', 'SELECT * FROM my_skill_uses'], token, seconds=1)
                  for label, token, _ in identities}
        combat['anonymous'] = self.probe('combat-anonymous', ['SELECT * FROM my_combat', 'SELECT * FROM my_skill_uses'])
        owners = {label: own for label, _, own in identities}
        self.check('combat feed scoped to its viewer', all(
            v['status'] == 'applied' and len(v['final']['combat']) > 0 and
            all(r['viewer'] == v['identity'] for r in v['final']['combat']) and
            any(r['kind'] == 9 and r['actor'] == owners[label] for r in v['final']['combat'])
            for label, v in combat.items() if label != 'anonymous') and
            combat['anonymous']['status'] == 'applied' and not combat['anonymous']['final']['combat'], 'combat-*.json',
            ', '.join(f"{label} {len(v['final']['combat'])}" for label, v in combat.items()))
        self.check('skill uses scoped to own characters', all(
            len(v['final']['skill_uses']) > 0 and all(u['actor'] == owners[label] for u in v['final']['skill_uses']) and
            any(u['skill'] == 'strike' and u['accepted_ms'] == 0 and 'refused' in u['outcome'] for u in v['final']['skill_uses'])
            for label, v in combat.items() if label != 'anonymous') and not combat['anonymous']['final']['skill_uses'], 'combat-*.json')
        # Town life (docs/TOWN_LIFE.md): what others see a character doing, the cards that
        # name its codes, and the weather are public; housekeeping writes the weather row.
        town = self.probe('town-public', ['SELECT * FROM act_card', 'SELECT * FROM weather'] + ([] if scoped else ['SELECT * FROM doing']))
        self.check('act_card and weather are public' + ('' if scoped else ', and doing (open build)'), town['status'] == 'applied' and
                   town['final']['counts']['act_card'] >= 5 and town['final']['counts']['weather'] == 1, 'town-public.json',
                   f"act_card {town['final']['counts']['act_card']}, doing {town['final']['counts']['doing']}, weather {town['final']['counts']['weather']}")
        public = self.probe('combat-public', ['SELECT * FROM skill_card'] + ([] if scoped else ['SELECT * FROM fighter']))
        self.check('skill_card is public' + ('' if scoped else ', and fighter (open build)'), public['status'] == 'applied' and
                   public['final']['counts']['skill_card'] >= 6, 'combat-public.json',
                   f"fighter {public['final']['counts']['fighter']}, skill_card {public['final']['counts']['skill_card']}")
        self.perception(identities, admin_token)
        self.presence(identities, admin_token)
        drop_file = self.directory / 'drop-request'
        drop_file.unlink(missing_ok=True)
        with DropProxy(drop_file) as proxy:
            reconnect = self.probe('reconnect', BASE_QUERIES + queries, admin_token, seconds=4,
                                   uri=f'http://127.0.0.1:{proxy.port}', drop_file=drop_file)
            first, second_round = reconnect['rounds']
            self.check('connection drop and resubscribe', proxy.drops == 1 and proxy.accepted == 2 and
                       first['disconnect'] is not None and second_round['status'] == 'applied' and
                       second_round['body_updates'] > 0 and second_round['stats_updates'] > 0 and
                       second_round['final']['ticks'] > first['final']['ticks'] and
                       second_round['final']['counts']['experience'] > 0,
                       'reconnect.json', f'drops={proxy.drops}, connections={proxy.accepted}')
        self.ad_hoc_check()
        self.save()

    def terrain(self):
        """The map's tiles from `terrain_chunk` (public)."""
        world = self.sql_rows('SELECT width, height FROM world')[0]
        w, h = world['width'], world['height']
        tiles = bytearray(w * h)
        for row in self.sql_rows('SELECT * FROM terrain_chunk'):
            data = row['tiles']
            data = bytes.fromhex(data.removeprefix('0x')) if isinstance(data, str) else bytes(data)
            cx, cy = row['id'] & 0xFFFF, row['id'] >> 16
            for k, t in enumerate(data):
                x, y = cx * 16 + k % 16, cy * 16 + k // 16
                if x < w and y < h:
                    tiles[y * w + x] = t
        return w, h, tiles

    def sql_rows(self, query, token=None):
        code, body = V.http(f"/v1/database/{self.state['db']}/sql", query, token, raw=True)
        if code != 200:
            raise RuntimeError(f'sql {query}: {code} {body[:300]}')
        res = json.loads(body)[-1]
        names = [e['name'].get('some', '?') for e in res['schema']['elements']]
        return [dict(zip(names, r)) for r in res['rows']]

    def sight_spots(self):
        """Tile centres for the perception checks, found on this world's own map:
        an open pair 3 tiles apart with nothing opaque between; a far point 20-30 tiles from
        the first; and a pair at most 4 tiles apart on one axis with only rock or wall
        between (within even night sight, 6 tiles, so only the wall hides)."""
        w, h, tiles = self.terrain()
        at = lambda x, y: tiles[y * w + x] if 0 <= x < w and 0 <= y < h else 4
        walk = lambda x, y: at(x, y) not in UNWALKABLE
        spots = {}
        for y in range(2, h - 2):
            for x in range(2, w - 32):
                if 'field' not in spots and all(walk(x + i, y + d) for i in range(6) for d in (-1, 0, 1)):
                    spots['field'] = [(x + .5, y + .5), (x + 5.5, y + .5)]
                if 'open' not in spots and all(walk(x + i, y) for i in range(4)):
                    far = next((x + d for d in range(20, 31) if walk(x + d, y)), None)
                    if far is not None:
                        spots['open'] = [(x + .5, y + .5), (x + 3.5, y + .5)]
                        spots['far'] = (far + .5, y + .5)
                if 'wall' not in spots:
                    for dx, dy in [(1, 0), (0, 1)]:
                        for gap in (1, 2, 3):
                            bx, by = x + (gap + 1) * dx, y + (gap + 1) * dy
                            if walk(x, y) and walk(bx, by) and all(at(x + i * dx, y + i * dy) in OPAQUE for i in range(1, gap + 1)):
                                spots['wall'] = [(x + .5, y + .5), (bx + .5, by + .5)]
                                spots['wall_tiles'] = [at(x + i * dx, y + i * dy) for i in range(1, gap + 1)]
                                break
                        if 'wall' in spots:
                            break
                if 'open' in spots and 'wall' in spots and 'field' in spots:
                    return spots
        raise RuntimeError(f'no sight-check geometry on this map: found {sorted(spots)}')

    def perception(self, identities, admin_token):
        """What a player receives is what its character perceives now, and its own state."""
        # Own state: only this identity's characters' rows.
        admin_identity = (lambda v: (v[0] if isinstance(v, list) else v).lower().removeprefix('0x'))(self.sql_admin('SELECT admin FROM world')[0]['admin'])
        own = {}
        for label, token, _ in identities:
            own[label] = self.probe('own-' + label, ['SELECT * FROM ' + v for v in OWN], token, seconds=1)
        own['anonymous'] = self.probe('own-anonymous', ['SELECT * FROM ' + v for v in OWN + SEEN])

        def scoped_to_self(label, v):
            p = v['final']['perception']
            mine = {c['id'] for c in p['my_characters']}
            # my_characters is the character the person plays now: one row.
            return (v['status'] == 'applied' and len(mine) == 1 and all(c['controller'] == v['identity'] and not c['ai'] for c in p['my_characters'])
                    and set(p['my_body']) == mine and set(p['my_fighter']) <= mine and set(p['my_doing']) <= mine
                    and p['my_vitals'] and set(p['my_vitals']) <= mine and {e['observer'] for e in p['my_experience']} <= mine
                    # Lived by the person, or by the world's minds while the person was away.
                    and all(e['controller'].lower().removeprefix('0x') in (v['identity'].lower().removeprefix('0x'), admin_identity) for e in p['my_experience'])
                    and set(p['my_places']) <= mine and set(p['my_inventory']) <= mine and set(p['my_know_how']) <= mine
                    # Offers to or from my character; incoming exactly when addressed to me.
                    and all((o['to'] in mine) == o['incoming'] and (o['from'] in mine or o['to'] in mine) for o in p['my_offers']))
        anonymous = own['anonymous']['final']['perception']
        self.check('own-state views return only my characters\' rows', all(scoped_to_self(l, v) for l, v in own.items() if l != 'anonymous') and
                   own['anonymous']['status'] == 'applied' and not any(anonymous[k] for k in OWN + SEEN), 'own-*.json',
                   ', '.join(f"{l}: {len(v['final']['perception']['my_experience'])} experiences, {len(v['final']['perception']['my_inventory'])} items"
                             for l, v in own.items() if l != 'anonymous'))
        # Spatial perception: two players placed by the admin on this world's own map.
        spots = self.sight_spots()
        (_, t1, me), (_, t2, other) = identities[1], identities[2]
        steps = []

        def scene(step, a, b):
            for who, at in [(me, a), (other, b)]:
                if not self.call('admin-place', admin_token, 'place_at', [who, at[0], at[1]]):
                    raise RuntimeError(f'place_at #{who} failed; see reducers.json')
            # Each player's perceived set is worked out every 200 ms.
            time.sleep(1.0)
            seen = {}
            for who, token in [(me, t1), (other, t2)]:
                v = self.probe(f'sight-{step}-{who}', ['SELECT * FROM ' + t for t in SEEN + ['my_body']], token, seconds=0)
                seen[who] = v['final']['perception']
            steps.append({'step': step, 'positions': {me: a, other: b}, 'seen': seen})
            write(self.directory / 'sight.json', {'spots': spots, 'steps': steps, 'players': [me, other]})
            return seen

        sees = lambda p, who: {t: who in p[t] for t in ['seen_bodies', 'seen_characters']}
        near = scene('in-sight', *spots['open'])
        self.check('in sight: both players receive each other\'s body and character', all(sees(near[me], other).values()) and
                   # Its own body comes through my_body, not as a copy in seen_bodies.
                   all(sees(near[other], me).values()) and near[me]['my_body'] == [me] and near[other]['my_body'] == [other]
                   and me not in near[me]['seen_bodies'] and other not in near[other]['seen_bodies'],
                   'sight.json', f"3 tiles apart at {spots['open'][0]}")
        # What a player perceives of another is the `perceived_of` projection: no controller,
        # home, parents or cause of death, and a stranger's name only once it is known.
        code, body = V.http(f"/v1/database/{self.state['db']}/sql", 'SELECT * FROM seen_characters', t1, raw=True)
        res = json.loads(body)[-1] if code == 200 else {'schema': {'elements': []}, 'rows': []}
        cols = [e['name'].get('some', '?') for e in res['schema']['elements']]
        rows = [dict(zip(cols, r)) for r in res['rows']]
        write(self.directory / 'seen-characters.json', {'columns': cols, 'rows': rows})
        theirs = next((r for r in rows if r['id'] == other), None)
        self.check('seen_characters is the projection: no controller, home or parents; a stranger by label',
                   code == 200 and theirs and not {'controller', 'ai', 'home_x', 'home_y', 'parent_a', 'parent_b', 'cause'} & set(cols)
                   and theirs['name'] == '' and theirs['label'] and theirs['hp'] < 0, 'seen-characters.json', f"columns {cols}; other {theirs and theirs['label']}")
        self.offers(identities, admin_token, me, other, t1, t2)
        far = scene('beyond-sight', spots['open'][0], spots['far'])
        gone = lambda s, a, b: not any(b in s[a][t] for t in SEEN)
        self.check('beyond sight: no body, character, fighter or doing row', gone(far, me, other) and gone(far, other, me), 'sight.json',
                   f"{spots['far'][0] - spots['open'][0][0]:.0f} tiles apart")
        hidden = scene('behind-wall', *spots['wall'])
        self.check('behind a wall or rock: no body, character, fighter or doing row', gone(hidden, me, other) and gone(hidden, other, me), 'sight.json',
                   f"{abs(spots['wall'][1][0] - spots['wall'][0][0]) + abs(spots['wall'][1][1] - spots['wall'][0][1]):.0f} tiles apart across tiles {spots['wall_tiles']}")

        self.field_of_view(spots, admin_token, (me, t1), (other, t2))

    def offers(self, identities, admin_token, me, other, t1, t2):
        """`my_offers`: an offer reaches its addressee (incoming) and its maker (outgoing) and
        no one else; anonymous receives none; `trade_offer` itself stays private."""
        self.call('admin-grant', admin_token, 'grant_items', [me, 'berries', 2])
        self.call('player-1', t1, 'human_act', [json.dumps({'do': 'offer', 'target': {'id': other}, 'item': 'berries', 'qty': 1, 'want': 'wood', 'want_qty': 1})])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not [r for r in self.sql_admin('SELECT * FROM trade_offer') if r['from'] == me and r['to'] == other]:
            time.sleep(0.5)
        got = {}
        for label, token, _ in identities:
            got[label] = self.probe('offers-' + label, ['SELECT * FROM my_offers'], token, seconds=1)
        got['anonymous'] = self.probe('offers-anonymous', ['SELECT * FROM my_offers'])
        rows = {l: v['final']['perception']['my_offers'] if v['status'] == 'applied' else None for l, v in got.items()}
        write(self.directory / 'offers.json', rows)
        key = lambda o: (o['from'], o['to'], o['incoming'], o['give_item'], o['want_item'])
        mine = [key(o) for o in rows['player-1'] or []]
        theirs = [key(o) for o in rows['player-2'] or []]
        self.check('my_offers: the maker reads its offer as outgoing, the addressee as incoming, no one else any',
                   mine == [(me, other, False, 'berries', 'wood')] and theirs == [(me, other, True, 'berries', 'wood')]
                   and rows['anonymous-connected'] == [] and rows['anonymous'] == []
                   and all(o['until_ms'] > 0 for o in rows['player-1'] + rows['player-2']),
                   'offers.json', f"player-1 {mine}, player-2 {theirs}, ClientAnon {rows['anonymous-connected']}, anonymous {rows['anonymous']}")

    def field_of_view(self, spots, admin_token, mine, theirs):
        """Sight that depends on facing (docs/PERCEPTION.md, "The field of view"), switched on by
        the admin's `set_world_law`: two players 5 m apart on open ground. Facing away, the
        other is not in my perceived set and comes as a `heard_sounds` row with no id; facing it,
        it is seen; at the field's edge it is kept by the margin once seen, not taken afresh."""
        (me, t1), (other, t2) = mine, theirs
        a, b = spots['field']
        steps = []

        def face(token, at, deg):
            """Turn so that the other (east of me) lies `deg` degrees off facing."""
            h = math.radians(-deg)
            self.call('player-face', token, 'human_act', [json.dumps({'do': 'face', 'target': {'at': [at[0] + 4 * math.cos(h), at[1] + 4 * math.sin(h)]}})])
            time.sleep(1.6)

        def look(step):
            v = self.probe(f'field-{step}', ['SELECT * FROM ' + t for t in SEEN + ['heard_sounds']], t1, seconds=0)
            got = v['final']['perception']
            steps.append({'step': step, 'seen': got})
            write(self.directory / 'field.json', {'spots': spots['field'], 'steps': steps, 'players': [me, other]})
            return got

        for who, at in [(me, a), (other, b)]:
            self.call('admin-place', admin_token, 'place_at', [who, at[0], at[1]])
        try:
            switched = self.call('admin-law', admin_token, 'set_world_law', ['fov_on', 'true'])
            face(t1, a, 180)
            away = look('facing-away')
            heard = [h for h in away['heard_sounds'] if h['bearing'] == 2]
            self.check('field on, facing away: the other is not in my perceived set', switched and other not in away['seen_bodies'] and other not in away['seen_characters'],
                       'field.json', f"5 m behind; seen {away['seen_bodies']}")
            self.check('heard_sounds: the other as a sound to the east, near, with no id', len(heard) == 1 and heard[0]['kind'] == 'person' and heard[0]['band'] == 0
                       and set(heard[0]) == {'key', 'kind', 'bearing', 'band'} and int(heard[0]['key']) not in (me, other), 'field.json', f'{away["heard_sounds"]}')
            face(t1, a, 0)
            ahead = look('facing')
            self.check('field on, facing it: seen, and no longer heard', other in ahead['seen_bodies'] and other in ahead['seen_characters'] and not [h for h in ahead['heard_sounds'] if h['bearing'] == 2],
                       'field.json', f"seen {ahead['seen_bodies']}; heard {ahead['heard_sounds']}")
            face(t1, a, 45)
            face(t1, a, 75)
            kept = look('edge-kept')
            face(t1, a, 100)
            face(t1, a, 75)
            fresh = look('edge-fresh')
            self.check('the field\'s edge: kept at 75 degrees once seen (margin), not seen afresh there', other in kept['seen_bodies'] and other not in fresh['seen_bodies'],
                       'field.json', f"kept {other in kept['seen_bodies']}, fresh {other in fresh['seen_bodies']}")
        finally:
            self.call('admin-law', admin_token, 'set_world_law', ['fov_on', 'false'])
        time.sleep(2.5)  # heard rows linger `heard_linger_s` (2 s)
        off = look('off-again')
        self.check('field off again: seen all round, nothing heard', other in off['seen_bodies'] and not off['heard_sounds'], 'field.json', f"seen {off['seen_bodies']}")

    def sql_admin(self, q):
        code, body = V.http(f"/v1/database/{self.state['db']}/sql", q, V.admin_token(), raw=True)
        if code != 200:
            raise RuntimeError(f'admin sql {q}: {code} {body}')
        res = json.loads(body)[-1]
        names = [e['name'].get('some', '?') for e in res['schema']['elements']]
        return [dict(zip(names, r)) for r in res['rows']]

    def presence(self, identities, admin_token):
        """Presence follows the person's connections exactly (client_connected and
        client_disconnected, several at once included); when the last one has been closed for
        the `takeover_s` law the world's minds control the character, and a new connection
        hands it back at once. Presence itself is private."""
        _, token, me = identities[2]
        row = lambda: self.sql_admin(f'SELECT * FROM presence WHERE id = {me}')[0]
        who = lambda: self.sql_admin(f'SELECT ai, controller FROM character WHERE id = {me}')[0]
        admin = self.sql_admin('SELECT admin FROM world')[0]['admin']
        record = {'steps': []}

        def step(name):
            r, c = row(), who()
            record['steps'].append({'step': name, 'at': time.time(), 'presence': r, 'character': c})
            write(self.directory / 'presence.json', record)
            return r, c

        # Wait for any earlier HTTP call's connection to be gone.
        time.sleep(1.0)
        held = []

        def hold(name, secs):
            t = threading.Thread(target=lambda: held.append(self.probe(name, ['SELECT * FROM my_characters'], token, seconds=secs)), daemon=True)
            t.start()
            return t

        def settle(n, secs=15.0):
            # A probe's hold counts from its own start, and starting one takes seconds on a busy
            # host: wait for the count rather than for a fixed time (it stays wrong only if
            # presence is wrong).
            deadline = time.monotonic() + secs
            while time.monotonic() < deadline and row()['connections'] != n:
                time.sleep(0.25)

        one = hold('presence-one', 30)
        settle(1)
        r1, _ = step('one connection')
        two = hold('presence-two', 6)
        settle(2)
        r2, _ = step('two connections')
        two.join(timeout=30)
        settle(1)
        r3, _ = step('one closed')
        one.join(timeout=40)
        settle(0)
        r4, c4 = step('both closed')
        self.check('presence counts each open connection of the person', r1['present'] and r1['connections'] == 1 and r2['connections'] == 2 and r3['present'] and r3['connections'] == 1,
                   'presence.json', f"{r1['connections']} → {r2['connections']} → {r3['connections']}")
        self.check('presence ends when the last connection closes (a takeover is pending)', not r4['present'] and r4['connections'] == 0 and not r4['ai'] and r4['takeover_ms'] < 2**63 and not c4['ai'],
                   'presence.json', f"present={r4['present']}, takeover in {(r4['takeover_ms'] - r4['changed_ms']) / 1000:.0f} s")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and not row()['ai']:
            time.sleep(1.0)
        r5, c5 = step('taken over')
        self.check('after takeover_s with no connection the world\'s minds control the character', r5['ai'] and c5['controller'] == admin,
                   'presence.json', f"ai={c5['ai']}, controller is the admin: {c5['controller'] == admin}")
        back = self.probe('presence-back', ['SELECT * FROM my_characters'], token, seconds=1)
        mine = [c['id'] for c in back['final']['perception']['my_characters']] if back['status'] == 'applied' else []
        hexid = lambda v: (v[0] if isinstance(v, list) else v).lower().removeprefix('0x')
        r6, c6 = step('returned')
        self.check('a new connection hands the character back at once (before the client subscribes)', not r6['ai'] and hexid(c6['controller']) == hexid(back['identity']) and not c6['ai'] and me in mine,
                   'presence.json', f"my_characters {mine}")
        refused = [self.probe('presence-player', ['SELECT * FROM presence'], token), self.probe('presence-anonymous', ['SELECT * FROM presence'])]
        self.check('presence is private (not to the player, not to anonymous clients)', all(v['status'] == 'rejected' for v in refused), 'presence-player.json')

    def save(self):
        write(self.directory / 'results.json', self.results)
        lines = ['| Check | Result | Evidence | Detail |', '| --- | --- | --- | --- |']
        lines.extend(f'| {r["check"]} | {r["status"]} | {r["evidence"]} | {r["detail"]} |' for r in self.results)
        (self.directory / 'results.md').write_text('\n'.join(lines) + '\n')
        lines = ['| Identity | Reducer | HTTP | Response | Result |', '| --- | --- | --- | --- | --- |']
        lines.extend(f'| {r["identity"]} | {r["reducer"]} | {r["http_status"]} | {r["body"].strip()} | {"PASS" if r["pass"] else "FAIL"} |' for r in self.matrix)
        (self.directory / 'reducers.md').write_text('\n'.join(lines) + '\n')
        for path in self.directory.glob('*'):
            if path.is_file() and path.name != 'state.json':
                data = path.read_bytes()
                if any(secret and secret.encode() in data for secret in self.secrets):
                    raise RuntimeError(f'credential leaked into {path.name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--query', help='stream a single SQL subscription instead of the fixed suite')
    parser.add_argument('--as-player', action='store_true', help='use the harness player for --query')
    parser.add_argument('--as-admin', action='store_true', help='use the database owner for --query (private tables)')
    parser.add_argument('--seconds', type=int, default=10, help='live query duration, 0 to 300 seconds')
    parser.add_argument('--save', help='fresh evidence basename for --query, without an extension')
    args = parser.parse_args()
    # The shared server on :3300, or a worker's own on another loopback port (LIVING_STDB_URL).
    if not re.fullmatch(r'http://127\.0\.0\.1:\d+', V.URL):
        parser.error('this driver and drop proxy require a local server at http://127.0.0.1:<port>')
    run = Run(args.run)
    if args.query is not None:
        if not 0 <= args.seconds <= 300:
            parser.error('--seconds must be between 0 and 300')
        name = args.save or f'query-{time.time_ns()}'
        if not re.fullmatch(r'[a-zA-Z0-9-]+', name):
            parser.error('--save must contain only letters, digits or hyphens')
        print(f'evidence: {run.directory / (name + ".jsonl")}', file=sys.stderr, flush=True)
        try:
            run.query(args.query, args.as_player, args.seconds, name, args.as_admin)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            print(str(error), file=sys.stderr)
            return 1
        return 0
    if args.as_player or args.as_admin or args.save or args.seconds != 10:
        parser.error('--as-player, --as-admin, --save and --seconds require --query')
    try:
        run.run()
    except Exception as error:
        run.save()
        print(str(error), file=sys.stderr)
        return 1
    return int(any(r['status'] in {'FAIL', 'XPASS'} for r in run.results))


if __name__ == '__main__':
    sys.exit(main())
