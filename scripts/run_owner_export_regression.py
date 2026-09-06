#!/usr/bin/env python3
"""Prepare, or explicitly execute, a tiny two-owner procedure privacy fixture.

No model, publication, clock setup, world advancement or service control. Uses an
explicit fresh database and previously issued private tokens on the same server.
Compatibility SQL is intentionally invoked here for parity, so this fixture is
separate from any scale/performance acceptance trial.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from owner_snapshot import EXPORT_PROCEDURE, INVENTORY_PROCEDURE, parse_export, parse_export_json, parse_inventory

PREFIX = 'sim-owner-export-'
TIMEOUT = 30
TABLE_QUERIES = {
    'roots': 'SELECT id, owner, state, last_advanced_at FROM sim_run_store',
    'blobs': 'SELECT id, key, run, actor, kind, body FROM sim_world_blob',
    'audit': 'SELECT key, run, event_id, kind, actor, json FROM sim_audit',
    'participant_cache': 'SELECT key, run, tick, body FROM sim_participant_cache',
    'grants': 'SELECT identity, run, observer, actor FROM sim_client_access',
    'clocks': 'SELECT run, paused FROM sim_client_clock',
}


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FixtureFailure(ValueError):
    """An explicitly authored, credential-free fixture failure."""


def require(condition, message):
    if not condition:
        raise FixtureFailure(message)


def identity_text(value):
    """Normalize the SQL representation of Identity without accepting numbers."""
    if isinstance(value, list) and len(value) == 1:
        return identity_text(value[0])
    if isinstance(value, dict) and set(value) == {'__identity__'}:
        return identity_text(value['__identity__'])
    if isinstance(value, str):
        value = value.removeprefix('0x').lower()
        if re.fullmatch(r'[0-9a-f]{64}', value):
            return value
    raise ValueError('unexpected SQL identity representation')


def scenario(source):
    result = copy.deepcopy(source)
    require([p['id'] for p in result['players']] == [1, 2, 3, 4], 'four-person scenario required')
    result.update(name='Tiny explicit owner-export privacy fixture', weather=None,
                  starting_behaviors={}, knowledge={})
    for player in result['players']:
        player['controller'] = 'human'
    return result


def validate_inputs(args):
    active = json.loads(args.active.read_text())
    server, database = active['server'], active['db']
    url = urllib.parse.urlsplit(server)
    require(url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1', '::1')
            and not url.username and not url.password and not url.query and not url.fragment
            and url.path in ('', '/'), 'explicit local HTTP authority required')
    require(isinstance(database, str) and re.fullmatch(r'[A-Za-z0-9_-]+', database), 'invalid database identifier')
    require(args.cli.is_file() and args.cli_config.is_file(), 'explicit CLI and owner configuration required')
    require(re.fullmatch(r'sim-[A-Za-z0-9-]+', args.fixture_run), 'invalid retained fixture run')
    identities = json.loads(args.fixture_identities.read_text())
    require(isinstance(identities, list) and len(identities) == 5, 'five prior helper identities required')
    identities = [identity_text(identity) for identity in identities]
    require(len(set(identities)) == 5, 'helper identities must be distinct')
    paths = {
        'owner_b': args.fixture_session_dir / f'{args.fixture_run}-actor-1.json',
        'participant': args.fixture_session_dir / f'{args.fixture_run}-actor-2.json',
        'ungranted': args.fixture_session_dir / f'{args.fixture_run}-actor-3.json',
        'observer': args.fixture_session_dir / f'{args.fixture_run}-observer.json',
    }
    for path in paths.values():
        require(path.is_file(), 'explicit retained private session file missing')
        require(not path.resolve().is_relative_to(args.output.resolve()), 'private sessions must remain outside evidence output')
    source = args.implementation / 'scenarios/law-local-borders.json'
    require(source.is_file() and (args.implementation / 'implementation.json').is_file(), 'frozen implementation and scenario required')
    return dict(server=server.rstrip('/'), database=database, paths=paths,
                identities=dict(owner_b=identities[0], participant=identities[1],
                                ungranted=identities[2], observer=identities[4]),
                scenario=scenario(json.loads(source.read_text())), scenario_source=source)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self, args, inputs, out):
        self.args, self.inputs, self.out = args, inputs, out
        self.tokens = {}
        for role, path in inputs['paths'].items():
            value = json.loads(path.read_text())
            require(value.get('server', '').rstrip('/') == inputs['server'], 'retained session server mismatch')
            require(isinstance(value.get('token'), str) and value['token'], 'retained session token missing')
            # The old session database is intentionally NOT used: tokens are
            # reused against only the explicit new active database.
            self.tokens[role] = value['token']
        require(len(set(self.tokens.values())) == len(self.tokens), 'retained session tokens must be distinct')
        self.sequence = 0
        self.wire_count = 0
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def record(self, role, operation, arguments, started, raw=None, status=None, failure=None):
        self.sequence += 1
        metadata = dict(sequence=self.sequence, role=role, operation=operation,
                        argument_count=len(arguments),
                        arguments_sha256=hashlib.sha256(json.dumps(arguments, separators=(',', ':')).encode()).hexdigest(),
                        elapsed_ms=round((time.monotonic() - started) * 1000, 3), status=status, failure=failure)
        if raw is not None:
            require(not any(token in raw for token in self.tokens.values()), 'unexpected credential-bearing response suppressed')
            metadata.update(response_bytes=len(raw.encode()), response_sha256=hashlib.sha256(raw.encode()).hexdigest())
            if operation in (EXPORT_PROCEDURE, INVENTORY_PROCEDURE):
                filename = f'{self.sequence:03}-{role}-{operation}.json'
                # Preserve actual successful HTTP/CLI wire, including typed Err;
                # never store request headers, tokens or HTTP error bodies.
                (self.out / 'wire' / filename).write_text(raw)
                metadata['wire'] = str(Path('wire') / filename)
                self.wire_count += 1
        with (self.out / 'commands.jsonl').open('a') as stream:
            stream.write(json.dumps(metadata, separators=(',', ':')) + '\n')

    def root(self, verb, *arguments):
        started = time.monotonic()
        command = [str(self.args.cli), '--config-path', str(self.args.cli_config), verb,
                   self.inputs['database'], *arguments, '--server', self.inputs['server'], '--no-config']
        operation = arguments[0] if verb == 'call' else 'sql'
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            self.record('owner_a', operation, arguments, started, failure='CLI unavailable or deadline')
            raise RuntimeError('owner CLI unavailable or deadline') from None
        if result.returncode:
            self.record('owner_a', operation, arguments, started, status=result.returncode, failure='CLI failed; output suppressed')
            raise RuntimeError('owner CLI failed; output suppressed')
        self.record('owner_a', operation, arguments, started, raw=result.stdout, status=0)
        return result.stdout

    def call(self, role, name, *arguments):
        if role == 'owner_a':
            return self.root('call', name, *[json.dumps(v, separators=(',', ':')) for v in arguments], '-y')
        started = time.monotonic()
        url = f"{self.inputs['server']}/v1/database/{self.inputs['database']}/call/{name}"
        request = urllib.request.Request(url, data=json.dumps(list(arguments), separators=(',', ':')).encode(),
                                         headers={'Authorization': 'Bearer ' + self.tokens[role],
                                                  'Content-Type': 'application/json'}, method='POST')
        try:
            with self.http.open(request, timeout=TIMEOUT) as response:
                raw = response.read().decode('utf-8')
                status = response.status
        except urllib.error.HTTPError as error:
            self.record(role, name, arguments, started, status=error.code, failure='HTTP failure; body suppressed')
            error.close()
            raise RuntimeError('owner fixture HTTP failure; body suppressed') from None
        except (OSError, UnicodeError, urllib.error.URLError):
            self.record(role, name, arguments, started, failure='HTTP unavailable or deadline')
            raise RuntimeError('owner fixture HTTP unavailable or deadline') from None
        require(status == 200, 'unexpected HTTP status')
        self.record(role, name, arguments, started, raw=raw, status=status)
        return raw

    def rows(self, query):
        value = json.loads(self.root('sql', query, '--format', 'json'))
        require(isinstance(value, list) and len(value) == 1 and isinstance(value[0].get('rows'), list), 'invalid owner SQL reply')
        return value[0]['rows']

    def inventory(self, role):
        return parse_inventory(self.call(role, INVENTORY_PROCEDURE))

    def export(self, role, run):
        raw = self.call(role, EXPORT_PROCEDURE, run)
        return parse_export_json(raw, run), parse_export(raw, run)

    def denied(self, role, run):
        raw = self.call(role, EXPORT_PROCEDURE, run)
        value = json.loads(raw)
        require(isinstance(value, list) and len(value) == 2 and type(value[0]) is int
                and value == [1, 'run unavailable'], 'missing/foreign owner export denial changed')

    def durable(self):
        return {name: sorted(self.rows(query), key=lambda row: json.dumps(row, sort_keys=True))
                for name, query in TABLE_QUERIES.items()}


def cleanup(transport, run_a, attempts, report):
    """Reconcile timed-out grants before revoking only this fixture's grants."""
    try:
        rows = transport.rows(TABLE_QUERIES['grants'])
        grants = {identity_text(row[0]): row for row in rows}
    except Exception:
        report['cleanup_errors'].append('unable to inspect grants for owned cleanup')
        grants = None
    if grants is not None:
        for identity in attempts:
            grant = grants.get(identity)
            if grant is None:
                continue
            if grant[1] != run_a:
                report['cleanup_errors'].append('attempted identity now belongs to another run; not revoked')
                continue
            try:
                transport.call('owner_a', 'sim_revoke_client', identity)
            except Exception:
                report['cleanup_errors'].append('owned grant revoke failed; response suppressed')
    try:
        report['clocks'] = transport.rows(TABLE_QUERIES['clocks'])
        report['remaining_grants'] = len(transport.rows(TABLE_QUERIES['grants']))
        report['cleanup_verified'] = not report['clocks'] and report['remaining_grants'] == 0 and not report['cleanup_errors']
    except Exception:
        report['cleanup_errors'].append('final clock/grant verification failed')
        report['cleanup_verified'] = False


def execute(args, inputs, out):
    transport = Transport(args, inputs, out)
    nonce = str(time.time_ns())
    run_a, run_b, missing = (PREFIX + part + '-' + nonce for part in ('a', 'b', 'missing'))
    report = dict(phase='setup', all_pass=False, owner_snapshot_api='procedure',
                  model_calls=0, world_advancement_calls=0, clock_setup_calls=0,
                  server=inputs['server'], database=inputs['database'], runs=dict(owner_a=run_a, owner_b=run_b),
                  implementation_manifest_sha256=sha(args.implementation / 'implementation.json'),
                  runner_sha256=sha(Path(__file__)), parser_sha256=sha(Path(__file__).with_name('owner_snapshot.py')),
                  cleanup_errors=[], cleanup_verified=False, created=[], grant_attempts=[],
                  scope='Tiny no-clock two-owner API parity/privacy fixture; compatibility SQL intentionally materializes views here; no scale/performance claim')
    old_handlers = {}
    def interrupted(signum, _frame):
        raise InterruptedError(f'fixture interrupted by signal {signum}')
    for signum in (signal.SIGINT, signal.SIGTERM):
        old_handlers[signum] = signal.signal(signum, interrupted)
    try:
        initial = transport.durable()
        require(all(not rows for rows in initial.values()), 'fixture database must be freshly empty')
        write(out / 'initial-durable.json', initial)
        for role in ('owner_a', 'owner_b', 'participant', 'observer', 'ungranted'):
            require(transport.inventory(role) == [], 'fresh owner inventory must be empty')
        scenario_json = json.dumps(inputs['scenario'], separators=(',', ':'))
        for role, run in (('owner_a', run_a), ('owner_b', run_b)):
            report['create_attempted'] = dict(role=role, run=run)
            transport.call(role, 'sim_create_participant', run, scenario_json)
            report['created'].append(run)
        require(transport.inventory('owner_a') == [run_a], 'owner A inventory includes foreign run')
        require(transport.inventory('owner_b') == [run_b], 'owner B inventory includes foreign run')
        transport.export('owner_b', run_b)
        for role, foreign in (('owner_a', run_b), ('owner_b', run_a)):
            transport.denied(role, foreign)
            transport.denied(role, missing)
        # All role identities start ungranted; grant only the two explicit ones
        # to A before taking the no-mutation baseline.
        for role in ('participant', 'observer', 'ungranted'):
            require(transport.inventory(role) == [], 'nonowner unexpectedly owns a run')
            transport.denied(role, run_a)
        for role, observer, actor in (('participant', False, 2), ('observer', True, 0)):
            identity = inputs['identities'][role]
            report['grant_attempts'].append(identity)
            write(out / 'owner-export-regression.json', report)
            transport.call('owner_a', 'sim_grant_client', run_a, identity, observer, actor)
        baseline = transport.durable()
        require(not baseline['clocks'], 'fixture must have no clock rows')
        expected_grants = {(inputs['identities']['participant'], run_a, False, 2),
                           (inputs['identities']['observer'], run_a, True, 0)}
        actual_grants = {(identity_text(row[0]), row[1], row[2], row[3]) for row in baseline['grants']}
        require(actual_grants == expected_grants, 'actual grants differ from fixture roles')
        owners = {row[0]: identity_text(row[1]) for row in baseline['roots']}
        require(set(owners) == {run_a, run_b} and owners[run_b] == inputs['identities']['owner_b']
                and owners[run_a] not in set(inputs['identities'].values()), 'actual root ownership does not match fixture identities')
        write(out / 'baseline-durable.json', baseline)
        body_a, world_a = transport.export('owner_a', run_a)
        body_b, world_b = transport.export('owner_b', run_b)
        sql_worlds = transport.rows('SELECT id, state FROM sim_run')
        require(len(sql_worlds) == 1 and sql_worlds[0][0] == run_a, 'database owner compatibility view exposed foreign root')
        require(sql_worlds[0][1] == body_a, 'procedure/SQL World bytes differ')
        require(json.loads(sql_worlds[0][1]) == world_a, 'procedure/SQL parsed World differs')
        report.update(byte_exact_world_parity=True, parsed_world_parity=True)
        write(out / 'owner-a-world.json', world_a)
        write(out / 'owner-b-world.json', world_b)
        for role in ('participant', 'observer', 'ungranted'):
            require(transport.inventory(role) == [], 'grant incorrectly confers owner inventory')
            for run in (run_a, run_b, missing):
                transport.denied(role, run)
        report['owner_isolation_pass'] = True
        for _ in range(2):
            require(transport.inventory('owner_a') == [run_a] and transport.inventory('owner_b') == [run_b], 'owner inventory changed')
            require(transport.export('owner_a', run_a) == (body_a, world_a), 'repeated owner A export changed')
            require(transport.export('owner_b', run_b) == (body_b, world_b), 'repeated owner B export changed')
        final = transport.durable()
        write(out / 'after-exports-durable.json', final)
        require(final == baseline, 'exports/inventory changed durable World, events, metadata, blobs, cache, grants or clocks')
        report['export_inventory_no_mutation_pass'] = True
        report['raw_wire_captured'] = transport.wire_count > 0
        report['checks_complete'] = True
    except Exception as error:
        # Never include arbitrary HTTP/CLI/session parser exception text.
        failure = str(error) if isinstance(error, FixtureFailure) else 'fixture check or transport failed; inspect redacted command metadata'
        report.update(phase='failed', failure_type=type(error).__name__, failure=failure)
    finally:
        for signum in old_handlers:
            signal.signal(signum, signal.SIG_IGN)
        cleanup(transport, run_a, report['grant_attempts'], report)
        try:
            inventories = {role: transport.inventory(role) for role in ('owner_a', 'owner_b', 'participant', 'observer', 'ungranted')}
            report['final_inventories'] = inventories
            if report.get('checks_complete'):
                require(inventories == dict(owner_a=[run_a], owner_b=[run_b], participant=[], observer=[], ungranted=[]), 'final owner inventory mismatch')
        except Exception:
            report['cleanup_errors'].append('final owner inventory verification failed')
            report['cleanup_verified'] = False
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)
        report['all_pass'] = bool(report.get('checks_complete') and report.get('cleanup_verified') and not report['cleanup_errors'])
        report['phase'] = 'completed' if report['all_pass'] else 'failed'
        report['finished_wall_ms'] = time.time_ns() // 10**6
        write(out / 'owner-export-regression.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Explicitly execute only this fresh-database fixture')
    for name in ('active', 'implementation', 'output', 'cli', 'cli-config', 'fixture-identities', 'fixture-session-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--fixture-run', required=True, help='Prior helper run naming the five retained private session files')
    args = parser.parse_args()
    inputs = validate_inputs(args)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'wire').mkdir()
    write(out / 'scenario.json', inputs['scenario'])
    write(out / 'preparation.json', dict(mode='execute' if args.execute else 'prepare', model_calls=0,
          owner_snapshot_api='procedure', active_source=str(args.active.resolve()),
          implementation=str(args.implementation.resolve()), implementation_manifest_sha256=sha(args.implementation / 'implementation.json'),
          fixture_identities_sha256=sha(args.fixture_identities), fixture_run=args.fixture_run,
          identity_roles=inputs['identities'], server=inputs['server'], database=inputs['database'],
          per_call_timeout_seconds=TIMEOUT, transport_retries=0,
          actions='Create two owned runs; grant/revoke only explicit participant+observer; never start a clock, advance, publish or infer',
          evidence_scope='Tiny API/ownership/serialization fixture, not scientific workload or scale acceptance'))
    if not args.execute:
        print(json.dumps(dict(prepared=True, executed=False, output=str(out))))
        return 0
    report = execute(args, inputs, out)
    print(json.dumps({key: report.get(key) for key in ('phase', 'all_pass', 'cleanup_verified', 'remaining_grants', 'model_calls')}))
    return 0 if report['all_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
