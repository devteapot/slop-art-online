#!/usr/bin/env python3
"""Summarize retained native authority evidence without contacting a server."""
import argparse
import json
import math
import re
from pathlib import Path


def parse_metrics(path):
    result = []
    for line in path.read_text().splitlines():
        if line.startswith('#'):
            continue
        m = re.match(r'([^ {]+)(?:\{(.*)\})? ([^ ]+)', line)
        if m:
            result.append((m[1], dict(re.findall(r'(\w+)="([^"]*)"', m[2] or '')), float(m[3])))
    return result


def total(values, name, **labels):
    return sum(v for n, actual, v in values if n == name and all(actual.get(k) == val for k, val in labels.items()))


def percentile(values, p):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * p) - 1)] if values else None


def summarize(path):
    def read(name):
        return json.loads((path / name).read_text())
    manifest = read('manifest.json')
    result = read('result.json')
    if not (path / 'reads/authority-validation.json').exists():
        # A resource abort may prevent final capture. Preserve the failed trial
        # instead of crashing or substituting a later recovery snapshot.
        reads_path = path / 'reads/read-results.json'
        reads = json.loads(reads_path.read_text()).get('results', []) if reads_path.exists() else []
        samples_path = path / 'memory.jsonl'
        samples = [json.loads(line) for line in samples_path.read_text().splitlines()] if samples_path.exists() else []
        progress_path = path / 'reads/runtime-progress.json'
        progress = json.loads(progress_path.read_text()) if progress_path.exists() else {}
        start = progress.get('window_start_wall_ms')
        abort = result.get('resource_abort', [])
        return dict(population=manifest['participants'], wall_seconds=manifest['active_seconds'],
            overall_pass=False, protocol_completed=False, final_authority_capture_available=False,
            read_count=len(reads), expected_read_count=manifest['participants']*len(manifest['read_round_seconds']),
            timely_verified_reads=sum(r.get('client_outcome') == 'receipt_ok'
                and r.get('own_observation_verified', False) and r.get('elapsed_ms', 10001) <= 10000 for r in reads),
            resource_abort=abort,
            guard_elapsed_seconds=(abort[0]['wall_ms']-start)/1000 if abort and start is not None else None,
            peak_rss_bytes=max((s['rss_bytes'] for s in samples), default=None),
            peak_retained_log_bytes=max((s['retained_log_bytes'] for s in samples), default=None),
            error=result.get('error'), cleanup_resolved=result.get('case', {}).get('cleanup_resolved', False),
            service_stopped=not result.get('after_stop', {}).get('Running', True),
            note='Failed/incomplete original attempt. No cadence or reconciled-read claim; any later cleanup recovery is separate evidence.')
    authority = read('reads/authority-validation.json')
    helper = read('reads/helper-result.json')
    reads = read('reads/read-results.json')['results']
    payload = read('reads/payload-summary.json')
    snapshots = read('reads/final-snapshot.json')
    world = snapshots['world']
    samples = [json.loads(line) for line in (path / 'memory.jsonl').read_text().splitlines()]
    start, end = helper['window_start_wall_ms'], helper['pause_sent_wall_ms']
    active = [s for s in samples if start <= s['wall_ms'] <= end]
    files = sorted((f for f in (path/'metrics').glob('*.prom') if f.stem.isdigit()), key=lambda f: int(f.stem))
    def nearest(at):
        return min(files, key=lambda f: abs(int(f.stem)-at))
    first_file, last_file = nearest(start), nearest(end)
    first, last = parse_metrics(first_file), parse_metrics(last_file)
    reducers = {}
    for reducer in ('sim_client_pulse', 'sim_participant_command'):
        deltas = {}
        for metric in ('reducer_wasm_time_usec', 'reducer_abi_time_usec',
                       'spacetime_reducer_wait_time_sec_sum', 'spacetime_reducer_wait_time_sec_count',
                       'spacetime_reducer_plus_query_duration_sec_sum', 'spacetime_reducer_plus_query_duration_sec_count'):
            deltas[metric] = total(last, metric, reducer=reducer)-total(first, metric, reducer=reducer)
        reducers[reducer] = deltas
    latencies = [r['elapsed_ms'] for r in reads if 'elapsed_ms' in r]
    by_round = {}
    for number in sorted({r.get('round', 0) for r in reads}):
        subset = [r for r in reads if r.get('round', 0) == number]
        elapsed = [r['elapsed_ms'] for r in subset if 'elapsed_ms' in r]
        by_round[number] = dict(count=len(subset), ok=sum(r.get('client_outcome')=='receipt_ok' for r in subset),
            p50_ms=percentile(elapsed,.5), p95_ms=percentile(elapsed,.95), max_ms=max(elapsed,default=None))
    growth = []
    for offset in range(0, int(manifest['active_seconds'])+1,30):
        at = start+offset*1000
        m = parse_metrics(nearest(at))
        memory = min(samples,key=lambda s:abs(s['wall_ms']-at))
        growth.append(dict(seconds=offset,rss_bytes=memory['rss_bytes'],
                           log_bytes=total(m,'spacetime_message_log_size_bytes')))
    return dict(population=len(world['players']),wall_seconds=manifest['active_seconds'],
        protocol_completed=result['case']['completed_protocol'],
        overall_pass=bool(result['case']['completed_protocol'] and result.get('read_deadlines_pass',False)
            and not result['resource_abort'] and not result['monitor_errors'] and not result.get('error')
            and result.get('access', {}).get('passed', True) and result.get('migration', {}).get('passed', True)
            and not result.get('stop_error') and not result['after_stop']['Running'] and not authority['engine_errors']),
        clock_20hz_pass=authority['update_count']/manifest['active_seconds'] >= 20,
        reads_pass=result.get('read_deadlines_pass',False),
        read_count=len(reads),read_latency_ms=dict(p50=percentile(latencies,.5),p95=percentile(latencies,.95),max=max(latencies,default=None)),
        rounds=by_round,updates=authority['update_count'],updates_per_second=authority['update_count']/manifest['active_seconds'],
        simulated_ms=authority['simulation_delta_ms'],simulated_to_wall_ratio=authority['simulation_delta_ms']/(1000*manifest['active_seconds']),
        peak_rss_bytes=max(s['rss_bytes'] for s in samples),active_peak_rss_bytes=max(s['rss_bytes'] for s in active),
        peak_service_swap_bytes=max(s['swap_bytes'] for s in samples),growth=growth,
        body_bytes=payload['status_body_bytes_fixed_window'],samples_dropped=payload['samples_dropped'],
        retained_log_bytes_at_pause=total(last,'spacetime_message_log_size_bytes'),
        audit_events=len(snapshots['events']),alive_at_end=sum(p['health']>0 for p in world['players']),
        stopped=world['stopped'],engine_errors=authority['engine_errors'],
        full_world_export_bytes=payload['final_full_world_json_bytes'],
        pause_ms=helper['pause_latency_ms'],remaining_grants=result['case']['remaining_grants'],
        resource_abort=result['resource_abort'],service_stopped=not result['after_stop']['Running'],
        service_exit_code=result['after_stop']['ExitCode'],
        approx_window_reducer_deltas=reducers,metric_boundaries=[first_file.name,last_file.name],
        note='Single finite density trial; nested JSON/BSATN body samples exclude network framing. Metrics boundaries use nearest 1s samples; log gauge is retained size, not cumulative writes.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    output=summarize(args.directory)
    (args.directory/'summary.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))
