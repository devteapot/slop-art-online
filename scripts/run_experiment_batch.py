#!/usr/bin/env python3
"""Run explicit pinned variants concurrently and compare retained authority evidence.

The coordinator owns launch/stop/evidence, never character decisions or world advancement.
Review each completed batch before creating the next hypothesis manifest.
"""
import argparse
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from experiment_artifacts import ROOT, digest, verify, write
from summarize_arena_matrix import summarize
from run_living_clearing import actor_limit, validate_newcomer_controller

READINESS_SECONDS = 100
CLEANUP_SECONDS = 40
DEFAULT_DISK_RESERVE_BYTES = 3 * 1024**3
DISK_CHECK_SECONDS = 1


class DiskReserveError(RuntimeError):
    """Stop host work while the filesystem still has room for final evidence."""


class DiskReserveGuard:
    def __init__(self, out, report, reserve):
        self.out, self.report, self.reserve = out, report, reserve
        self.last_check = None
        report['disk_space'] = dict(path=str(out), reserve_bytes=reserve,
                                  check_interval_seconds=DISK_CHECK_SECONDS, samples=[])

    def check(self, stage, *, force=False):
        now = time.monotonic()
        if not force and self.last_check is not None and now - self.last_check < DISK_CHECK_SECONDS:
            return
        usage = shutil.disk_usage(self.out)
        self.last_check = now
        sample = dict(at=time.time(), stage=stage, free_bytes=usage.free, total_bytes=usage.total)
        self.report['disk_space']['samples'].append(sample)
        if usage.free <= self.reserve:
            self.report['disk_space']['breach'] = sample
            self.report['failure_code'] = 'disk_reserve_exhausted'
            raise DiskReserveError(
                f'Disk reserve reached during {stage}: {usage.free} free bytes <= '
                f'{self.reserve} reserved bytes on {self.out}; stopping to preserve final evidence')
        write(self.out / 'batch.json', self.report)


def integer(value, label, minimum, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        limit = f'{minimum}..{maximum}' if maximum is not None else f'at least {minimum}'
        raise ValueError(f'{label} must be an integer {limit}')
    return value


def resolve_spec(spec):
    """Validate all variants and read inputs before any process can launch."""
    variants = spec.get('variants', [])
    if not isinstance(variants, list) or not variants:
        raise ValueError('A batch needs at least one explicitly configured variant')
    if not spec.get('hypothesis') or not spec.get('evaluation'):
        raise ValueError('Record a hypothesis and evaluation criteria before running')
    concurrency = integer(spec.get('concurrency', len(variants)), 'concurrency', 1, len(variants))
    reserve = integer(spec.get('disk_reserve_bytes', DEFAULT_DISK_RESERVE_BYTES), 'disk_reserve_bytes', 1)
    ids, ports, verified, resolved = set(), set(), {}, []
    for source in variants:
        v = dict(source)
        name = v.get('id')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Use simple ASCII variant IDs')
        port = integer(v.get('port'), f'{name} port', 1, 65535)
        if name in ids or port in ports:
            raise ValueError('Variant IDs and ports must be unique across the entire batch')
        ids.add(name)
        ports.add(port)
        for key, default, minimum, maximum in (
            ('serial_ms', 15000, 1000, None), ('minutes', 5, 1, 60), ('calls_per_actor', 0, 0, 100),
        ):
            v[key] = integer(v.get(key, spec.get(key, default)), f'{name} {key}', minimum, maximum)
        if type(v.get('recovery', False)) is not bool:
            raise ValueError(f'{name} recovery must be a boolean')
        v['implementation'] = str(Path(v['implementation']).resolve())
        if v['implementation'] not in verified:
            folder = Path(v['implementation'])
            verify(folder)
            verified[v['implementation']] = digest(folder / 'implementation.json')
        inputs = {}
        for key in ('scenario', 'controllers'):
            v[key] = str(Path(v[key]).resolve())
            inputs[key] = json.loads(Path(v[key]).read_text())
        if v.get('newcomer_controller') is not None:
            v['newcomer_controller'] = str(Path(v['newcomer_controller']).resolve())
            inputs['newcomer_controller'] = validate_newcomer_controller(json.loads(Path(v['newcomer_controller']).read_text()))
            actor_limit(inputs['scenario'], True)
        controllers = inputs['controllers']
        actor_ids = [p['id'] for p in inputs['scenario']['players']]
        if (not controllers or len(set(actor_ids)) != len(actor_ids)
                or len(controllers) != len(actor_ids)
                or {c['actor'] for c in controllers} != set(actor_ids)):
            raise ValueError(f'{name} controllers must cover each unique scenario actor exactly once')
        for controller in controllers:
            if controller['config']['backend']['model'] != 'gpt-5.6-luna':
                raise ValueError('This iteration campaign is Luna-only')
        resolved.append((v, inputs, verified[v['implementation']]))
    spec = dict(spec, concurrency=concurrency, disk_reserve_bytes=reserve, variants=[v for v, _, _ in resolved])
    return spec, resolved


def prepare(spec, resolved, out):
    out.mkdir(parents=True)
    write(out / 'manifest.json', spec)
    (out / '.gates').mkdir()
    plan = []
    for index, (v, values, implementation_hash) in enumerate(resolved):
        group = index // spec['concurrency']
        group_size = min(spec['concurrency'], len(resolved) - group * spec['concurrency'])
        inputs = out / '.inputs' / v['id']
        inputs.mkdir(parents=True)
        for key, value in values.items():
            write(inputs / (key + '.json'), value)
        # Each host initializes serially for old millisecond-named databases.
        # This finite allowance also covers the earliest child's wait for its peers.
        gate_timeout = group_size * READINESS_SECONDS + 30
        gate = out / '.gates' / f'group-{group + 1}'
        command = [sys.executable, str(ROOT / 'scripts/run_living_clearing.py'),
                   '--output', str(out / v['id']), '--port', str(v['port']),
                   '--minutes', str(v['minutes']), '--calls-per-actor', str(v['calls_per_actor']),
                   '--serial-ms', str(v['serial_ms']), '--scenario', str(inputs / 'scenario.json'),
                   '--controllers', str(inputs / 'controllers.json'), '--implementation', v['implementation'],
                   '--start-gate', str(gate), '--start-gate-timeout', str(gate_timeout)]
        if 'newcomer_controller' in values:
            command.extend(['--newcomer-controller', str(inputs / 'newcomer_controller.json')])
        if v.get('recovery', False):
            command.append('--recovery')
        plan.append(dict(id=v['id'], group=group + 1, url=f"http://127.0.0.1:{v['port']}",
                         serial_ms=v['serial_ms'], minutes=v['minutes'], calls_per_actor=v['calls_per_actor'],
                         implementation_manifest_hash=implementation_hash, command=command,
                         inputs={key: digest(inputs / (key + '.json')) for key in values},
                         start_gate=str(gate), gate_timeout_seconds=gate_timeout, phase='planned'))
    write(out / 'plan.json', plan)
    return plan


def compare(record, folder):
    result = json.loads((folder / 'LIVE_RESULT.json').read_text())
    pilot = json.loads((folder / 'pilot.json').read_text())
    players = [p for a in result['arenas'] for p in a['players']]
    calls = [c for p in players for c in p['calls']]
    started, finished = pilot.get('started_at'), pilot.get('finished_at')
    return dict(variant=record['id'], group=record['group'], run=result['run'],
                seconds=result['seconds'], updates=result['updates'],
                wall_seconds=finished - started if started is not None and finished is not None else None,
                alive=sum(p['alive'] for p in players), population=len(players), calls=len(calls),
                completed_calls=sum(c['phase'] == 'completed' for c in calls),
                output_errors=sum(bool(c.get('error') or c.get('provider_error')) for c in calls),
                engine_errors=len(result['engine_errors']), scope_violations=len(result['scope_violations']),
                details=str(folder / 'LIVE_RESULT.json'))


def validate_completion(record, folder):
    """Require a measured end condition and final authority provenance, not exit 0."""
    pilot = json.loads((folder / 'pilot.json').read_text())
    if pilot.get('phase') != 'completed' or pilot.get('interruption') or pilot.get('pause_error'):
        raise ValueError('Pilot did not complete without interruption and confirmed cleanup')
    completion = pilot.get('completion') or {}
    if completion.get('protocol') != 'sao-pilot-completion-v1':
        raise ValueError('Pilot lacks measured completion provenance')
    requested = record['minutes'] * 60
    elapsed = completion.get('observed_wall_seconds')
    if (completion.get('requested_seconds') != requested or pilot.get('minutes') != record['minutes']
            or type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0):
        raise ValueError('Pilot completion duration differs from the planned sample')
    if pilot.get('run') != record['run']:
        raise ValueError('Pilot final authority belongs to a different run')
    source = (folder / record['run'] / 'final-snapshot.json').resolve()
    if (Path(pilot.get('final_snapshot', '')).resolve() != source
            or not source.is_file() or digest(source) != pilot.get('final_snapshot_sha256')):
        raise ValueError('Pilot final snapshot provenance is missing or mismatched')
    world = json.loads(source.read_text())['world']
    if world.get('run') != record['run'] or world['timing']['time_ms'] != pilot.get('final_time_ms'):
        raise ValueError('Pilot final authority identity or timing does not match')
    reason = completion.get('reason')
    if reason == 'duration_elapsed':
        if elapsed < requested:
            raise ValueError('Pilot ended before the minimum active duration; cleanup does not count')
    elif reason == 'world_stopped':
        if world.get('stopped') is not True:
            raise ValueError('Claimed world termination is absent from final authority')
    elif reason == 'all_actors_dead':
        if not world.get('players') or any(p['health'] > 0 for p in world['players']):
            raise ValueError('Claimed population termination is absent from final authority')
    else:
        raise ValueError('Pilot lacks a valid terminal reason')
    return completion


def cleanup(jobs, failed):
    # Give all supervisors a chance to pause their authority and export evidence in
    # parallel. They intentionally keep paused observer hosts on successful runs.
    errors = []
    for job, _, _, _ in jobs:
        if job.poll() is None:
            job.terminate()
    deadline = time.monotonic() + CLEANUP_SECONDS
    for job, log, folder, _ in jobs:
        try:
            job.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            job.kill()
            job.wait(timeout=5)
        log.close()
        if failed:
            # Host is a separate session, so stopping only the supervisor leaks it.
            # Its PID comes from the supervisor's own record, never a global search.
            try:
                pilot = json.loads((folder / 'pilot.json').read_text())
                if pilot.get('phase') == 'running' or pilot.get('pause_error'):
                    errors.append(f'{folder.name}: authority pause not confirmed; inspect pilot.json')
                pid = pilot.get('host_pid')
                if isinstance(pid, int) and pid > 1 and os.getpgid(pid) == pid:
                    os.killpg(pid, signal.SIGTERM)
            except (FileNotFoundError, ProcessLookupError):
                pass
            except (OSError, ValueError) as error:
                errors.append(f'{folder.name}: host cleanup could not be confirmed: {error}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true', help='validate and freeze a plan without starting processes or models')
    parser.add_argument('--disk-reserve-bytes', type=int,
                        help='override manifest disk_reserve_bytes (default 3 GiB); host resource guard only')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        raise SystemExit('Choose a new batch evidence directory')
    try:
        raw_spec = json.loads(args.manifest.read_text())
        if args.disk_reserve_bytes is not None:
            raw_spec['disk_reserve_bytes'] = args.disk_reserve_bytes
        spec, resolved = resolve_spec(raw_spec)
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise SystemExit(str(error)) from None
    plan = prepare(spec, resolved, out)
    report = dict(phase='planned' if args.dry_run else 'preparing', hypothesis=spec['hypothesis'],
                  evaluation=spec['evaluation'], concurrency=spec['concurrency'], variants=plan,
                  observer_retention='Successful supervisors leave paused observer hosts available', comparison=[])
    write(out / 'batch.json', report)
    if args.dry_run:
        print(f'Validated {len(plan)} variants; concurrency {spec["concurrency"]}; plan: {out / "plan.json"}')
        return
    jobs, databases = [], set()
    disk = DiskReserveGuard(out, report, spec['disk_reserve_bytes'])
    stop = False

    def interrupted(signum, _frame):
        nonlocal stop
        report.setdefault('interruption', dict(signal=signal.Signals(signum).name, received_at=time.time()))
        stop = True

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        disk.check('preflight', force=True)
        for offset in range(0, len(plan), spec['concurrency']):
            group = plan[offset:offset + spec['concurrency']]
            group_jobs = []
            report.update(phase='preparing', current_group=group[0]['group'])
            for record in group:
                if stop:
                    raise RuntimeError('Batch cancelled before launch')
                disk.check('before_launch', force=True)
                folder = out / record['id']
                log = (out / (record['id'] + '.log')).open('w')
                try:
                    job = subprocess.Popen(record['command'], cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
                except BaseException:
                    log.close()
                    raise
                item = (job, log, folder, record)
                jobs.append(item)
                group_jobs.append(item)
                record.update(pid=job.pid, phase='initializing')
                write(out / 'batch.json', report)
                ready_deadline = time.monotonic() + READINESS_SECONDS
                while not (folder / 'ready.json').exists():
                    disk.check('readiness')
                    if stop or any(j.poll() is not None for j, _, _, _ in group_jobs) or time.monotonic() > ready_deadline:
                        raise RuntimeError(f"Variant {record['id']} failed before readiness; inspect its log")
                    time.sleep(.25)
                active = json.loads((folder / 'active.json').read_text())
                database = (active.get('server'), active['db'])
                if database in databases:
                    raise RuntimeError('Variants must have distinct authority databases')
                databases.add(database)
                record.update(phase='ready', database=active['db'], server=active.get('server'), run=active['run'])
                write(out / 'batch.json', report)
            if stop or any(j.poll() is not None for j, _, _, _ in group_jobs):
                raise RuntimeError('A variant failed or batch cancelled before the common start')
            disk.check('before_start_gate', force=True)
            Path(group[0]['start_gate']).touch()
            started = time.time()
            for record in group:
                record.update(phase='running', gate_released_at=started)
            report.update(phase='running')
            report.setdefault('started_at', started)
            write(out / 'batch.json', report)
            print('Parallel experiments started: ' + ', '.join(v['url'] for v in group), flush=True)
            # Each child has its own duration; supervision includes bounded export.
            deadline = time.monotonic() + max(v['minutes'] for v in group) * 60 + 60
            while any(j.poll() is None for j, _, _, _ in group_jobs):
                disk.check('running')
                if stop or time.monotonic() > deadline:
                    raise RuntimeError('Batch cancelled or exceeded its supervision deadline')
                if any(j.poll() not in (None, 0) for j, _, _, _ in group_jobs):
                    raise RuntimeError('A variant failed; stopping peers')
                time.sleep(1)
            if any(j.returncode for j, _, _, _ in group_jobs):
                raise RuntimeError('A variant failed')
            if stop:
                raise RuntimeError('Batch cancelled before completion validation')
            for job, log, folder, record in group_jobs:
                disk.check('completion_validation', force=True)
                log.close()
                try:
                    record['completion'] = validate_completion(record, folder)
                    summarize(folder)
                except (Exception, SystemExit) as error:
                    record.update(phase='failed', exit_code=job.returncode, error=str(error))
                    raise
                record.update(phase='completed', exit_code=job.returncode)
                report['comparison'].append(compare(record, folder))
                write(out / 'comparison.json', report['comparison'])
                write(out / 'batch.json', report)
        if stop:
            raise RuntimeError('Batch cancelled during completion validation')
        report.update(phase='completed', finished_at=time.time())
        print(json.dumps(report['comparison'], indent=2), flush=True)
    except (Exception, SystemExit) as error:
        report.update(phase='failed', error=str(error), finished_at=time.time())
        raise
    finally:
        if stop:
            report.update(phase='failed', error='Batch received a termination signal', finished_at=time.time())
        report['cleanup_errors'] = cleanup(jobs, report['phase'] != 'completed')
        write(out / 'batch.json', report)


if __name__ == '__main__':
    main()
