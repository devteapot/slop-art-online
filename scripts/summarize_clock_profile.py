#!/usr/bin/env python3
"""Summarize opt-in host spans from a retained native clock trial."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

from summarize_native_scale import percentile


def summarize(directory, seconds=None):
    if (directory/'workload-window.json').exists():
        window=json.loads((directory/'workload-window.json').read_text())
        helper=dict(fixed_window_seconds=window['seconds'],window_start_wall_ms=window['start_wall_ms'],
                    pause_sent_wall_ms=window['pause_sent_wall_ms'])
    else:
        helper = json.loads((directory / 'reads/helper-result.json').read_text())
    duration = helper['fixed_window_seconds'] if seconds is None else seconds
    if not 0 < duration <= helper['fixed_window_seconds']:
        raise ValueError('profile interval must be inside the declared active window')
    start = helper['window_start_wall_ms'] * 1000
    end = min(start + duration * 1_000_000, helper['pause_sent_wall_ms'] * 1000)
    spans = defaultdict(list)
    by_reducer = defaultdict(lambda: defaultdict(list))
    action_domains = []
    action_phases = defaultdict(dict)
    cold_reads = []
    command_scopes = []
    controller_catalogs = defaultdict(list)
    catalog_storage = defaultdict(list)
    catalog_loads = defaultdict(list)
    catalog_save_identities = defaultdict(list)
    audit_append_counts = defaultdict(list)
    audit_encode_bytes = defaultdict(list)
    evidence_sampling = defaultdict(list)
    script_sampling = defaultdict(list)
    participant_save_sampling = defaultdict(list)
    trace_page_plans = defaultdict(list)
    trace_append_plans = defaultdict(list)
    trace_body_handles = defaultdict(list)
    units = {'ns': 1e-9, 'µs': 1e-6, 'ms': 1e-3, 's': 1}
    for line in (directory / 'module-logs.jsonl').read_text().splitlines():
        record = json.loads(line)
        if record.get('function') not in ('sim_client_pulse', 'sim_deadline_pulse', 'sim_world_pulse', 'sim_dispatch_controller_action', 'sim_dispatch_controller_action_after', 'sim_participant_command', 'sim_my_render_snapshot', 'sim_my_render_header', 'sim_my_snapshot', 'sim_audit_maintenance', 'sim_compact_audit') or not start <= record['ts'] < end:
            continue
        if record['message'].startswith('audit-encode-bytes '):
            counts = json.loads(record['message'].split(' ', 1)[1])
            if (len(counts) != 3 or any(type(n) is not int or n < 0 for n in counts)
                    or counts[2] != counts[1]):
                raise ValueError('invalid audit encoded-byte counts')
            audit_encode_bytes[record['function']].append(counts)
        if record['message'].startswith('audit-append-counts '):
            counts = json.loads(record['message'].split(' ', 1)[1])
            if (len(counts) != 3 or any(type(n) is not int or n < 0 for n in counts)
                    or counts[1] != (counts[0] + 66) // 67):
                raise ValueError('invalid audit append counts')
            audit_append_counts[record['function']].append(counts)
        if record['message'].startswith('catalog-save-identities '):
            counts = json.loads(record['message'].split(' ', 1)[1])
            if (len(counts) != 4 or any(type(n) is not int or n < 0 for n in counts)
                    or counts[1] > counts[0] or counts[3] > counts[2]):
                raise ValueError('invalid catalog identity counts')
            catalog_save_identities[record['function']].append(counts)
        if record['message'].startswith('trace-append-plan '):
            plan = json.loads(record['message'].split(' ', 1)[1])
            if len(plan) != 6 or any(type(n) is not int or n < 0 for n in plan):
                raise ValueError('invalid trace append plan counts')
            trace_append_plans[record['function']].append(plan)
        if record['message'].startswith('trace-page-plan '):
            plan = json.loads(record['message'].split(' ', 1)[1])
            if len(plan) != 6 or any(type(n) is not int or n < 0 for n in plan) or plan[5] > plan[1]:
                raise ValueError('invalid trace page plan counts')
            trace_page_plans[record['function']].append(plan)
        if record['message'].startswith('trace-body-handles '):
            counts = json.loads(record['message'].split(' ', 1)[1])
            if len(counts) != 2 or any(type(n) is not int or n < 0 for n in counts) or counts[1] > counts[0]:
                raise ValueError('invalid trace body handle counts')
            trace_body_handles[record['function']].append(counts)
        if record['message'].startswith('evidence-profile-counts '):
            counts = json.loads(record['message'].split(' ', 1)[1])
            if (len(counts) != 4 or any(type(n) is not int or n < 0 for n in counts)
                    or counts[0] + counts[1] != counts[2] or counts[2] != counts[3]):
                raise ValueError('invalid evidence sampling counts')
            evidence_sampling[record['function']].append(counts)
        if record['message'].startswith('script-profile-counts '):
            counts = json.loads(record['message'].split(' ', 1)[1])
            if len(counts) != 6 or any(type(n) is not int or n < 0 for n in counts):
                raise ValueError('invalid script sampling counts')
            script_sampling[record['function']].append(counts)
        if record['message'].startswith('participant-save-samples '):
            sample = re.fullmatch(r'participant-save-samples eligible=(\d+) sampled=(\d+)', record['message'])
            if not sample or int(sample[2]) != (int(sample[1]) + 16) // 17:
                raise ValueError('invalid participant save sampling counts')
            participant_save_sampling[record['function']].append((int(sample[1]), int(sample[2])))
        if record['message'].startswith('clock_cold_reads '):
            values = json.loads(record['message'].split(' ', 1)[1])
            if len(values) != 6 or any(not isinstance(v, int) or v < 0 for v in values):
                raise ValueError('invalid cold-read counter record')
            cold_reads.append(values)
        if record['message'].startswith('command-scope '):
            scope = re.fullmatch(r'command-scope local=(true|false) actors=(\d+) auxiliary=(\d+) stations=(\d+) target_facts=(\d+)', record['message'])
            if not scope:
                raise ValueError('invalid command-scope record')
            command_scopes.append(dict(local_context=scope[1] == 'true',
                **{name: int(scope[i + 2]) for i, name in enumerate(('actors', 'auxiliary', 'stations', 'target_facts'))}))
        if record['message'].startswith('controller-catalog-load '):
            loaded = re.fullmatch(r'controller-catalog-load bytes=(\d+)', record['message'])
            if not loaded:
                raise ValueError('invalid catalog-load record')
            catalog_loads[record['function']].append(int(loaded[1]))
        if record['message'].startswith('controller-catalog-storage '):
            storage = json.loads(record['message'].split(' ', 1)[1])
            if (set(storage) not in ({'hot_bytes', 'body_reads', 'body_bytes'},
                    {'hot_bytes', 'body_reads', 'body_bytes', 'deferred'})
                    or any(type(storage[name]) is not int or storage[name] < 0
                        for name in ('hot_bytes', 'body_reads', 'body_bytes'))
                    or ('deferred' in storage and type(storage['deferred']) is not bool)):
                raise ValueError('invalid catalog-storage record')
            catalog_storage[record['function']].append(storage)
        if record['message'].startswith('controller-catalogs '):
            catalogs = re.fullmatch(r'controller-catalogs rows=(\d+) distinct=(\d+)', record['message'])
            if not catalogs or int(catalogs[2]) > int(catalogs[1]):
                raise ValueError('invalid controller-catalog record')
            controller_catalogs[record['function']].append((int(catalogs[1]), int(catalogs[2])))
        if record['message'].startswith('clock_action_domain '):
            domain = json.loads(record['message'].split(' ', 1)[1])
            if set(domain) != {'time_ms', 'loaded', 'alive_before', 'due', 'events'} or any(
                    not isinstance(v, int) or v < 0 for v in domain.values()):
                raise ValueError('invalid action-domain record')
            phases = action_phases.pop(record['function'], {})
            action_domains.append(dict(ended_at_us=record['ts'], reducer=record['function'],
                phases_ms=phases,
                complete_profile=all(name in phases for name in ('actions.read', 'actions.assemble', 'actions.execute')),
                **domain))
        match = re.fullmatch(r'Timing span "([^"]+)": ([0-9.]+)(ns|µs|ms|s)', record['message'])
        if match:
            elapsed = float(match[2]) * units[match[3]]
            spans[match[1]].append(elapsed)
            by_reducer[record['function']][match[1]].append(elapsed)
            if match[1] == 'actions.read':
                action_phases[record['function']] = {}
            if match[1].startswith('kernel.') or match[1] in ('actions.read', 'actions.assemble', 'actions.execute'):
                action_phases[record['function']][match[1]] = elapsed * 1000
    if not all(name in spans for name in ('clock.load', 'clock.advance', 'clock.save')):
        raise ValueError('missing clock spans; use a clock-profile build and retain module logs')
    def statistics(samples):
        return {name: dict(count=len(values), sum_seconds=sum(values),
                          mean_ms=1000 * sum(values) / len(values),
                          p95_ms=1000 * percentile(values, .95), max_ms=1000 * max(values))
                for name, values in sorted(samples.items())}
    return dict(seconds=duration, source='module-logs.jsonl',
        script_sampling={reducer: dict(kernels=len(rows),
            phases={name: dict(eligible=sum(row[i] for row in rows),
                sampled=sum((row[i]+16)//17 for row in rows), stride=17)
                for i,name in enumerate(('script.input_budget','script.compiled',
                    'script.input_convert','script.invoke','script.output_convert','script.output_budget'))},
            note='First/every-17th invocation of each phase per kernel. Nested law calls overlap skill invocation; phases are not additive and sample means are not population means.')
            for reducer, rows in sorted(script_sampling.items())},
        evidence_sampling={reducer: dict(kernels=len(rows),
            phases={name: dict(eligible=sum(row[i] for row in rows),
                sampled=sum((row[i]+stride-1)//stride for row in rows), stride=stride)
                for i,(name,stride) in enumerate(zip(
                    ('evidence.record.cold','evidence.record.warm','evidence.parents','evidence.append'), (7,67,67,67)))},
            note='Systematic first/every-N samples within each kernel; nested timers and logging perturb the profile. Sample means are not whole-population means.')
            for reducer, rows in sorted(evidence_sampling.items())},
        participant_save_sampling={reducer: dict(batches=len(rows), eligible=sum(r[0] for r in rows),
            sampled=sum(r[1] for r in rows),stride=17,
            note='First/every-17th changed participant per batch; diff/row phases occur only when its evidence changes.')
            for reducer, rows in sorted(participant_save_sampling.items())},
        trace_body_handles={reducer: dict(readers=len(rows),
            references=sum(row[0] for row in rows), distinct_handles=sum(row[1] for row in rows),
            maximum_references=max(row[0] for row in rows), maximum_distinct_handles=max(row[1] for row in rows),
            note='Per-reader transaction totals recorded at drop. Handles are lazy; these are not payload fetch counts or persisted rows.')
            for reducer, rows in sorted(trace_body_handles.items())},
        trace_page_plans={reducer: dict(samples=len(rows),
            **{name: dict(total=sum(row[i] for row in rows), maximum=max(row[i] for row in rows))
               for i, name in enumerate(('actor', 'retained_entries', 'reused_pages', 'written_pages', 'removed_pages', 'materialized_entries')) if i},
            note='First/every-17th changed participant per batch, only when its trace changes. Counts are sampled work, not all writes.')
            for reducer, rows in sorted(trace_page_plans.items())},
        trace_append_plans={reducer: dict(samples=len(rows),
            **{name: dict(total=sum(row[i] for row in rows), maximum=max(row[i] for row in rows))
               for i, name in enumerate(('actor', 'removed_entries', 'appended_entries', 'read_pages', 'written_pages', 'removed_pages')) if i},
            note='First/every-17th changed participant per batch using a proven append/prune journal. Page reads count only writer reads; kernel trace loading is separate.')
            for reducer, rows in sorted(trace_append_plans.items())},
        audit_encode_bytes={reducer: dict(blocks=len(rows),
            **{name: dict(total=sum(row[i] for row in rows), maximum=max(row[i] for row in rows))
               for i, name in enumerate(('plain_bytes', 'compressed_bytes', 'hashed_bytes'))},
            note='Complete archive blocks encoded in this window. New digest hashes the exact compressed stream; legacy block validation still hashes plain bytes.')
            for reducer, rows in sorted(audit_encode_bytes.items())},
        audit_append_counts={reducer: dict(transactions=len(rows),
            **{name: dict(total=sum(row[i] for row in rows), maximum=max(row[i] for row in rows))
               for i, name in enumerate(('events', 'sampled_events', 'json_bytes'))},
            note='First/every-67th event encode and insert spans within each append. Counts and byte totals cover every appended event; sampled phase means may be biased.')
            for reducer, rows in sorted(audit_append_counts.items())},
        catalog_save_identities={reducer: dict(transactions=len(rows),
            **{name: dict(total=sum(row[i] for row in rows), maximum=max(row[i] for row in rows))
               for i, name in enumerate(('calls', 'hashes', 'input_bytes', 'hashed_bytes'))},
            note='Non-null catalog replacements in each complete write batch. Exact run/byte-string reuse; validation hashes when reconciling stored rows are separate.')
            for reducer, rows in sorted(catalog_save_identities.items())},
        deferred_catalog_body_loads={reducer: dict(reads=len(catalog_loads[reducer]),
            bytes=sum(catalog_loads[reducer]), maximum_bytes=max(catalog_loads[reducer], default=0),
            note='Actual cold body fetches on use; zero requires the deferred-assembly instrumentation marker.')
            for reducer, rows in sorted(catalog_storage.items()) if any(row.get('deferred') for row in rows)},
        controller_catalog_storage={reducer: dict(samples=len(rows),
            **{name: dict(total=sum(row[name] for row in rows), maximum=max(row[name] for row in rows))
               for name in ('hot_bytes', 'body_reads', 'body_bytes')})
            for reducer, rows in sorted(catalog_storage.items())},
        controller_catalogs={reducer: dict(samples=len(rows), total_rows=sum(row[0] for row in rows),
            distinct_payloads=sum(row[1] for row in rows), max_rows=max(row[0] for row in rows),
            max_distinct=max(row[1] for row in rows),
            note='Exact stored catalog or reference sharing within each assembly; no cross-transaction cache.')
            for reducer, rows in sorted(controller_catalogs.items())},
        command_scopes=None if not command_scopes else dict(samples=len(command_scopes),
            local_context_samples=sum(row['local_context'] for row in command_scopes),
            counters={name: dict(total=sum(row[name] for row in command_scopes),
                                mean=sum(row[name] for row in command_scopes)/len(command_scopes),
                                maximum=max(row[name] for row in command_scopes))
                for name in ('actors', 'auxiliary', 'stations', 'target_facts')},
            note='Loaded row dependencies at admission, including explicit targets; not writes or all database reads.'),
        cold_reads=None if not cold_reads else dict(samples=len(cold_reads),
            counters={name: dict(total=sum(row[i] for row in cold_reads),
                                mean=sum(row[i] for row in cold_reads)/len(cold_reads),
                                maximum=max(row[i] for row in cold_reads))
                for i, name in enumerate(('mind_rows','mind_body_bytes','experience_rows',
                                          'experience_body_bytes','lease_evidence_rows','lease_evidence_body_bytes'))},
            note='Transaction-local point fetches including save. Body bytes exclude keys, metadata, and ABI/network framing; not total table reads.'),
        spans=statistics(spans),
        by_reducer={reducer: statistics(samples) for reducer, samples in sorted(by_reducer.items())},
        action_domains=action_domains,
        note='Instrumented diagnostic. Nested spans must not be added to their parents. '
             'Selection uses span completion time; boundary-crossing spans can differ in count. '
             'Action domains describe loaded execution inputs, not committed outcomes. '
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
