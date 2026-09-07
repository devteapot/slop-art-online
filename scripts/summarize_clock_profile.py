#!/usr/bin/env python3
"""Summarize opt-in host spans from a retained native clock trial."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

from summarize_native_scale import percentile


def summarize(directory, seconds=None):
    helper = json.loads((directory / 'reads/helper-result.json').read_text())
    duration = helper['fixed_window_seconds'] if seconds is None else seconds
    if not 0 < duration <= helper['fixed_window_seconds']:
        raise ValueError('profile interval must be inside the declared active window')
    start = helper['window_start_wall_ms'] * 1000
    end = min(start + duration * 1_000_000, helper['pause_sent_wall_ms'] * 1000)
    spans = defaultdict(list)
    cold_reads = []
    units = {'ns': 1e-9, 'µs': 1e-6, 'ms': 1e-3, 's': 1}
    for line in (directory / 'module-logs.jsonl').read_text().splitlines():
        record = json.loads(line)
        if record.get('function') != 'sim_client_pulse' or not start <= record['ts'] < end:
            continue
        if record['message'].startswith('clock_cold_reads '):
            values = json.loads(record['message'].split(' ', 1)[1])
            if len(values) != 6 or any(not isinstance(v, int) or v < 0 for v in values):
                raise ValueError('invalid cold-read counter record')
            cold_reads.append(values)
        match = re.fullmatch(r'Timing span "([^"]+)": ([0-9.]+)(ns|µs|ms|s)', record['message'])
        if match:
            spans[match[1]].append(float(match[2]) * units[match[3]])
    if not all(name in spans for name in ('clock.load', 'clock.advance', 'clock.save')):
        raise ValueError('missing clock spans; use a clock-profile build and retain module logs')
    return dict(seconds=duration, source='module-logs.jsonl',
        cold_reads=None if not cold_reads else dict(samples=len(cold_reads),
            counters={name: dict(total=sum(row[i] for row in cold_reads),
                                mean=sum(row[i] for row in cold_reads)/len(cold_reads),
                                maximum=max(row[i] for row in cold_reads))
                for i, name in enumerate(('mind_rows','mind_body_bytes','experience_rows',
                                          'experience_body_bytes','lease_evidence_rows','lease_evidence_body_bytes'))},
            note='Transaction-local point fetches including save. Body bytes exclude keys, metadata, and ABI/network framing; not total table reads.'),
        spans={name: dict(count=len(values), sum_seconds=sum(values),
                         mean_ms=1000 * sum(values) / len(values),
                         p95_ms=1000 * percentile(values, .95), max_ms=1000 * max(values))
               for name, values in sorted(spans.items())},
        note='Instrumented diagnostic. Nested spans must not be added to their parents. '
             'Selection uses span completion time; boundary-crossing spans can differ in count. '
             'Elapsed host time is not simulation time or an uninstrumented capacity claim.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--seconds', type=int)
    args = parser.parse_args()
    summary = summarize(args.directory, args.seconds)
    suffix = '' if args.seconds is None else f'-{args.seconds}s'
    (args.directory / f'clock-profile-summary{suffix}.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
