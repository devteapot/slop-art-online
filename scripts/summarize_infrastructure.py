#!/usr/bin/env python3
"""Reconcile actual utility stocks and paid computation from authority evidence."""
import argparse
import collections
import contextlib
import io
import json
from pathlib import Path

from summarize_knowledge import summarize as summarize_knowledge


def totals(state):
    stocks = dict(parts=0, water=0, electricity=0, repair_parts_consumed=0)
    for inventory in state.get('actor_materials', {}).values():
        for material in ('parts', 'water'):
            stocks[material] += inventory.get(material, 0)
    for body in state.get('bodies', {}).values():
        stocks['electricity'] += body.get('charge', 0)
    for station in state.get('stations', []):
        seed = station['seed']
        stocks['electricity'] += seed['electricity']
        stocks['parts'] += station.get('embodied_parts', 0)
        stocks['repair_parts_consumed'] += station.get('repair_parts_consumed', 0)
        for material in ('parts', 'water'):
            stocks[material] += seed.get('materials', {}).get(material, 0)
    return stocks


def analyze(world, events):
    events = sorted(events, key=lambda e: e['id'])
    initializations = [e for e in events if e['kind'] == 'infrastructure_initialized']
    violations = []
    if len(initializations) != 1:
        return dict(violations=['Expected one authoritative infrastructure initialization'])
    initial = totals(initializations[0]['data'])
    final = totals(world.get('infrastructure', {}))
    generated = body_use = compute_use = cooling_use = conversion_loss = repairs = 0
    jobs = {}
    counts = collections.Counter()
    blocks, completed, retrieved, access, care = [], [], [], [], []

    def reference(event):
        return dict(event=event['id'], actor=event.get('actor'), time_ms=event['data'].get('time_ms'),
                    kind=event['kind'], data=event['data'], parents=event.get('parents', []))

    def amount(data, field, event):
        value = data.get(field)
        if type(value) is not int or value < 0:
            violations.append(f"Event {event['id']} has an invalid {field} amount")
            return 0
        return value

    for event in events:
        kind, data = event['kind'], event['data']
        counts[kind] += 1
        key = (data.get('station'), data.get('job'))
        if kind == 'electricity_generated':
            generated += amount(data, 'amount', event)
        elif kind == 'electricity_consumed':
            body_use += amount(data, 'amount', event)
        elif kind == 'body_charged':
            loss = amount(data, 'conversion_loss', event)
            conversion_loss += loss
            if amount(data, 'electricity', event) != amount(data, 'charge', event) + loss:
                violations.append(f"Event {event['id']} charge transfer does not balance")
            if data.get('support'):
                care.append(reference(event))
        elif kind == 'infrastructure_repaired':
            repairs += amount(data, 'parts', event)
        elif kind == 'compute_submitted':
            if key in jobs:
                violations.append(f"Event {event['id']} reuses a compute job")
            jobs[key] = dict(owner=event.get('actor'), progress=0, required=data['required_quanta'],
                             quantum_ms=data['quantum_ms'], submitted_ms=data['time_ms'], last_ms=None,
                             cancelled=False, completed=False, retrieved=False, erased=False, source=event['id'])
        elif kind == 'compute_quantum':
            compute_use += amount(data, 'electricity', event)
            cooling_use += amount(data, 'water', event)
            job = jobs.get(key)
            if not job:
                violations.append(f"Event {event['id']} works on an unsubmitted job")
                continue
            at = data.get('quantum_at_ms', -1)
            if (job['cancelled'] or job['erased'] or job['completed'] or data.get('progress') != job['progress'] + 1
                    or at < job['submitted_ms'] + job['quantum_ms']
                    or (job['last_ms'] is not None and at < job['last_ms'] + job['quantum_ms'])):
                violations.append(f"Event {event['id']} grants duplicate, early or invalid work")
            job['progress'] = data.get('progress')
            job['last_ms'] = at
        elif kind == 'compute_completed':
            job = jobs.get(key)
            if not job or job['cancelled'] or job['erased'] or job['completed'] or job['progress'] != job['required']:
                violations.append(f"Event {event['id']} produces an unpaid or duplicate output")
            else:
                job['completed'] = True
            completed.append(reference(event))
        elif kind == 'compute_cancelled':
            if key not in jobs or data.get('refund') is not False:
                violations.append(f"Event {event['id']} cancels an unknown job or refunds spent work")
            else:
                jobs[key]['cancelled'] = True
        elif kind == 'compute_erased':
            job = jobs.get(key)
            if not job or job['erased'] or data.get('refund') is not False or data.get('progress') != job['progress']:
                violations.append(f"Event {event['id']} erases an unknown job or refunds spent work")
            else:
                job['erased'] = True
        elif kind == 'compute_retrieved':
            job = jobs.get(key)
            if not job or job['erased'] or not job['completed'] or job['owner'] != event.get('actor'):
                violations.append(f"Event {event['id']} retrieves an unavailable or foreign result")
            else:
                job['retrieved'] = True
            retrieved.append(reference(event))
        elif kind == 'compute_availability_changed':
            blocks.append(reference(event))
        elif kind == 'infrastructure_access_changed':
            access.append(reference(event))

    accounts = {
        'electricity': dict(initial=initial['electricity'], produced=generated, final=final['electricity'],
                            body_consumed=body_use, compute_consumed=compute_use, conversion_loss=conversion_loss),
        'water': dict(initial=initial['water'], final=final['water'], cooling_consumed=cooling_use),
        'parts': dict(initial=initial['parts'], final=final['parts'], repair_consumed=repairs),
    }
    if initial['electricity'] + generated != final['electricity'] + body_use + compute_use + conversion_loss:
        violations.append('Electricity account does not reconcile')
    if initial['water'] != final['water'] + cooling_use:
        violations.append('Water account does not reconcile')
    if initial['parts'] != final['parts'] + repairs:
        violations.append('Parts account does not reconcile')
    if final['repair_parts_consumed'] != initial['repair_parts_consumed'] + repairs:
        violations.append('Repair sink differs from material events')
    final_jobs = {}
    for station in world.get('infrastructure', {}).get('stations', []):
        for job in station.get('jobs', []):
            key = (station['seed']['id'], job['id'])
            final_jobs[key] = job
            expected = jobs.get(key)
            if not expected or expected['erased'] or any(expected[field] != job.get(field) for field in ('owner', 'progress', 'required', 'cancelled', 'retrieved')):
                violations.append(f'Final job {key} differs from its work ledger')
            elif expected['completed'] != bool(job.get('report')):
                violations.append(f'Final job {key} output differs from completion evidence')
    if {k for k, job in jobs.items() if not job['erased']} != set(final_jobs):
        violations.append('Final job roster differs from submitted job ledger')
    computed_ids = {e['data'].get('record', {}).get('id') for e in completed}
    receipt_ids = {e['id'] for e in events if e['kind'] == 'perception'
                   and e['data'].get('kind') == 'knowledge_report'
                   and e['data'].get('content', {}).get('record', {}).get('id') in computed_ids}
    interpretations = [reference(e) for e in events if e['kind'] == 'identity_change'
                       and (any(r.get('source') in receipt_ids for r in e['data'].get('reflections', []))
                            or bool(receipt_ids.intersection(e.get('parents', []))))]
    return dict(accounts=accounts, violations=violations,
                event_counts={k: v for k, v in counts.items() if k.startswith(('compute_', 'infrastructure_', 'electricity_', 'material_', 'body_charged'))},
                jobs=[dict(station=k[0], job=k[1], **v) for k, v in jobs.items()],
                completed_outputs=completed, retrievals=retrieved, interpretations=interpretations,
                availability_changes=blocks, access_changes=access, support_charging=care,
                limitations='Material accounting and paid output are measured separately from usefulness. '
                'Retrieval or later action is not proof that a forecast caused a decision. Inputs are supplied '
                'assumptions; compute does not buy backend inference or automatically grant mastery.')


def summarize(out):
    out = Path(out)
    with contextlib.redirect_stdout(io.StringIO()):
        knowledge = summarize_knowledge(out)
    snapshot = json.loads(Path(knowledge['source']).read_text())
    result = analyze(snapshot['world'], snapshot['events'])
    result.update(run=knowledge['run'], seconds=knowledge['seconds'], source=knowledge['source'],
                  source_sha256=knowledge['source_sha256'], model_calls=knowledge['model_calls'],
                  reported_tokens=knowledge['reported_tokens'], copy_audit_violations=knowledge['copy_audit_violations'],
                  engine_errors=knowledge['engine_errors'], scope_violations=knowledge['scope_violations'])
    (out / 'INFRASTRUCTURE_RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('run', 'accounts', 'violations', 'event_counts')}, indent=2))
    if result['violations']:
        raise SystemExit('Infrastructure evidence audit failed')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    summarize(parser.parse_args().output)
