#!/usr/bin/env python3
"""Run the client suite, or stream one ad-hoc query on a launched client-* run."""
import argparse
import importlib.util
import json
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
PRIVATE = ['clock', 'steer', 'wake', 'familiar', 'deliberation', 'rearing',
           'act_queue', 'pasture', 'tick_timer', 'slow_timer', 'infant_cry']
MIND = ['mind_routines', 'mind_install', 'mind_say', 'mind_act', 'mind_skip',
        'mind_consolidated', 'mind_update']
ADMIN = {
    'set_paused': [False], 'install_script': [''], 'set_profile': [False],
    'spawn_crowd': [0, False], 'grant_know_how': [0, 'gather'], 'own_habits': [],
    'grant_repertoires': [], 'purge_dead': [], 'kill': [0, 'probe'],
    'set_background': [0, '{}'], 'grant_items': [0, 'berries', 0],
    'place_structure': [0, 'shelter'], 'set_behavior': [0, '{"wait":30}'],
    'place_near': [0, 0], 'seed_communities': [], 'spawn_battle': [0],
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
        'mind_update': [actor, {'persona': {'some': {'narrative': marker, 'values': [],
                         'goals': [], 'traits': '{}', 'mood': 'probe'}},
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
            upstream = socket.create_connection(('127.0.0.1', 3300), timeout=5)
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

    def query(self, query, as_player, seconds, name):
        if as_player and not self.state.get('token'):
            raise ValueError('no player yet: run verify.py player join NAME first')
        path = self.directory / (name + '.jsonl')
        stderr_path = self.directory / (name + '-sdk.log')
        request = {'uri': V.URL, 'db': self.state['db'],
                   'token': self.state.get('token') if as_player else None,
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
                                   '--seconds', '4', '--save', 'adhoc-suite'],
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
        tables = (ROOT / 'living/authority/src/tables.rs').read_text()
        definitions = re.findall(r'#\[spacetimedb::table\((.*?)\)\]', tables, re.S)
        private = [re.search(r'accessor\s*=\s*(\w+)', d)[1] for d in definitions
                   if not re.search(r'\bpublic\b', d)]
        if set(private) != set(PRIVATE):
            raise RuntimeError('private table inventory changed; update PRIVATE')
        reducers = {}
        for path in (ROOT / 'living/authority/src').glob('*.rs'):
            text = path.read_text()
            for match in re.finditer(r'#\[spacetimedb::reducer\]\s*pub fn (\w+)\(', text):
                reducers[match[1]] = f'{path.relative_to(ROOT)}:{text[:match.start()].count(chr(10)) + 2}'
        expected = set(ADMIN) | set(MIND) | {'join', 'human_move', 'human_act', 'human_say', 'tick', 'housekeeping'}
        if set(reducers) != expected:
            raise RuntimeError(f'reducer inventory changed: {set(reducers) ^ expected}')
        write(self.directory / 'source-inventory.json', {'base_queries': exact, 'private': private,
              'reducers': reducers, 'sdk': '2.10.1', 'server': '2.10.1'})

    def run(self):
        self.source_inventory()
        for table in ['experience', 'thought']:
            access = self.probe('privacy-access-' + table, ['SELECT * FROM ' + table])
            if access['status'] == 'rejected' and 'private' in access['error'].lower():
                self.check('KNOWN ISSUE anonymous ' + table + ' privacy', True,
                           'privacy-access-' + table + '.json', 'now denied; review expected failure', known=True)
        initial, anonymous_token = self.probe('anonymous-base', BASE_QUERIES, seconds=4,
                                             capture_credential=True)
        if initial['status'] != 'applied':
            raise RuntimeError('viewer base subscription refused; see anonymous-base.json and privacy checks')
        self.check('anonymous base initial rows', initial['status'] == 'applied' and
                   initial['initial']['counts']['character'] > 0 and
                   initial['initial']['counts']['world'] == 1, 'anonymous-base.json')
        self.check('anonymous base live updates', initial['body_updates'] > 0 and
                   initial['stats_updates'] > 0 and initial['final']['ticks'] > initial['initial']['ticks'],
                   'anonymous-base.json', f"body={initial['body_updates']}, stats={initial['stats_updates']}")
        ai = next(c for c in initial['final']['characters'] if c['ai'] and c['alive'] and c['stage'] >= 2 and c['kind'] == 'person')
        self.check('anonymous join', self.call('anonymous-connected', anonymous_token, 'join', ['ClientAnon']), 'reducers.json')
        self.call('anonymous-connected', anonymous_token, 'join', ['Again'], 'you already have a living character')
        second_code, second_body = V.http('/v1/identity', {})
        if second_code != 200:
            raise RuntimeError('could not mint second player identity')
        second = json.loads(second_body)
        self.secrets.append(second['token'])
        self.check('second player join', self.call('player-2', second['token'], 'join', ['ClientSecond']), 'reducers.json')
        players = self.probe('players', ['SELECT * FROM character'])['final']['characters']
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
        for reducer, args in ADMIN.items():
            self.call('anonymous-http-no-token', None, reducer, args, 'admin only')
        for reducer in MIND:
            self.call('anonymous-http-no-token', None, reducer, mind_args(reducer, ai['id'], 'anonymous'), 'not your character')
        for reducer in ['tick', 'housekeeping']:
            self.call('anonymous-http-no-token', None, reducer, [{'scheduled_id': 0, 'scheduled_at': {'Interval': 16667}}],
                      'No such procedure', expected_status=404)
        for reducer, args in [('human_move', [0, 0, False]), ('human_act', ['{"wait":30}']), ('human_say', ['probe', 0])]:
            self.call('anonymous-http-no-token', None, reducer, args, 'you have no living character')
        self.call('anonymous-http-no-token', None, 'join', ['AnonHttp'])
        self.check('reducer permission matrix', all(row['pass'] for row in self.matrix), 'reducers.json',
                   f'{len(self.matrix)} calls, {sum(not row["pass"] for row in self.matrix)} mismatches')
        effects = self.probe('reducer-effects', BASE_QUERIES + ['SELECT * FROM routine'])['final']
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
        inspected = self.probe('inspected-character', queries, seconds=2)
        end = inspected['final']
        routines = {r['id'] for r in end['routines']}
        self.check('per-character queries', inspected['status'] == 'applied' and
                   len(end['experiences']) > 0 and len(routines) > 0 and
                   all(r['observer'] == actor for r in end['experiences']) and
                   all(r['actor'] == actor for r in end['routines']) and
                   len(end['routine_stats']) > 0 and all(r['id'] in routines for r in end['routine_stats']), 'inspected-character.json',
                   f'actor={actor}, experiences={len(end["experiences"])}, routines={len(routines)}')
        visibility = []
        for table in PRIVATE:
            subscription = self.probe('private-' + table, ['SELECT * FROM ' + table])
            code, error = V.http(f"/v1/database/{self.state['db']}/sql", 'SELECT * FROM ' + table, raw=True)
            okay = subscription['status'] == 'rejected' and 'private' in subscription['error'].lower() and code != 200 and 'private' in error.lower()
            visibility.append({'table': table, 'subscription': subscription, 'http_status': code, 'http_error': error, 'pass': okay})
        write(self.directory / 'visibility.json', visibility)
        self.check('private table visibility', all(v['pass'] for v in visibility), 'visibility.json')
        for table in ['experience', 'thought']:
            leaked = self.probe('privacy-' + table, ['SELECT * FROM ' + table])
            denied = leaked['status'] == 'rejected' and 'private' in leaked.get('error', '').lower()
            observable = (len({e['observer'] for e in leaked['final']['experiences']}) > 1 if table == 'experience'
                          else len({t['actor'] for t in leaked['final']['thoughts'] if t['detail'].startswith('VERIFY_CLIENT_RAW_')}) >= 3) if not denied else False
            if not denied and not observable:
                self.check(table + ' fixture coverage', False, 'privacy-' + table + '.json', 'no foreign fixture rows received')
            self.check('KNOWN ISSUE anonymous ' + table + ' privacy', denied, 'privacy-' + table + '.json',
                       'denied' if denied else 'anonymous subscription exposes foreign rows', known=True)
        views = {}
        admin_token = V.admin_token()
        self.secrets.append(admin_token)
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
        drop_file = self.directory / 'drop-request'
        drop_file.unlink(missing_ok=True)
        with DropProxy(drop_file) as proxy:
            reconnect = self.probe('reconnect', BASE_QUERIES + queries, seconds=4,
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
    parser.add_argument('--seconds', type=int, default=10, help='live query duration, 0 to 300 seconds')
    parser.add_argument('--save', help='fresh evidence basename for --query, without an extension')
    args = parser.parse_args()
    if V.URL != 'http://127.0.0.1:3300':
        parser.error('this driver and drop proxy require the local shared server on :3300')
    run = Run(args.run)
    if args.query is not None:
        if not 0 <= args.seconds <= 300:
            parser.error('--seconds must be between 0 and 300')
        name = args.save or f'query-{time.time_ns()}'
        if not re.fullmatch(r'[a-zA-Z0-9-]+', name):
            parser.error('--save must contain only letters, digits or hyphens')
        print(f'evidence: {run.directory / (name + ".jsonl")}', file=sys.stderr, flush=True)
        try:
            run.query(args.query, args.as_player, args.seconds, name)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            print(str(error), file=sys.stderr)
            return 1
        return 0
    if args.as_player or args.save or args.seconds != 10:
        parser.error('--as-player, --save and --seconds require --query')
    try:
        run.run()
    except Exception as error:
        run.save()
        print(str(error), file=sys.stderr)
        return 1
    return int(any(r['status'] in {'FAIL', 'XPASS'} for r in run.results))


if __name__ == '__main__':
    sys.exit(main())
