#!/usr/bin/env python3
"""Audit paid research, exact physical copies and personal evidence; never infer invention."""
import argparse
import collections
import contextlib
import hashlib
import io
import json
from pathlib import Path

from summarize_infrastructure import analyze as analyze_infrastructure
from summarize_knowledge import analyze as analyze_knowledge, reference, summarize as summarize_knowledge


def program_hash(program):
    digest = hashlib.sha256(b'slop-art-online/numeric-technique\0')
    digest.update(program['interface_version'].to_bytes(4, 'big'))
    for field in ('source', 'input_contract', 'output_contract'):
        value = program[field].encode('utf-8')
        digest.update(len(value).to_bytes(8, 'big'))
        digest.update(value)
    return digest.hexdigest()


def input_hash(data):
    payload = dict(kind=data['experiment_kind'], program_record=data['program_record'],
                   inputs=data['input'], expected_results=data.get('expected_results'),
                   sources=data.get('source_records', []))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def analyze(world, events):
    events = sorted(events, key=lambda e: e['id'])
    event_index = {e['id']: e for e in events}
    knowledge = analyze_knowledge(world, events)
    utilities = analyze_infrastructure(world, events)
    violations = []
    records = knowledge['records']
    acquisitions = {a['event']: a for a in knowledge['acquisitions']}
    citations = collections.defaultdict(list)
    assessment_receipts = collections.defaultdict(list)
    for event in events:
        if event['kind'] == 'knowledge_interpreted':
            data = event['data']
            key = (event.get('actor'), data.get('record'), data.get('source'), data.get('interpretation'))
            assessment_receipts[key].append(event['id'])
    for item in knowledge['accepted_citations']:
        # Old rules skipped the original holding when deriving an assertion.
        # Count that form only with a matching earlier authority assessment receipt;
        # this preserves historical results without inferring effects from prose.
        key = (item.get('actor'), item['record'], item['source'], item.get('interpretation'))
        assessed = any(item['source'] < receipt < item['event']
                       for receipt in assessment_receipts.get(key, []))
        if not item.get('derived_assertion') or assessed:
            citations[item['event']].append(item)
    held, interpreted, inspections = collections.defaultdict(set), {}, {}
    jobs, completions, proofs = {}, {}, collections.defaultdict(list)
    work_state = {}
    balance = next((e['data'].get('balance', {}) for e in events if e['kind']=='infrastructure_initialized'), {})
    authored, practices, runs, source_reads, erasures = [], [], [], [], []
    checked_hashes = set()

    def changed_research_rule(event, hook):
        # Later stages permit legal changes to research requirements. This
        # observer cannot treat the original proof rule as immutable.
        if any(e['kind']=='script_update_activated' and e['id']<event['id'] for e in events):
            return True
        position=event['data'].get('location')
        if position is None:
            position=next((p.get('position') for p in world['initial']['players'] if p['id']==event.get('actor')),None)
        grid=world['initial'].get('map') or {};width=grid.get('width',0)
        active={}
        for item in events:
            if item['id']>=event['id']:break
            if item['kind']=='law_activated':
                ref=item['data']['reference'];scope=ref['scope']
                key='universal' if scope['kind']=='universal' else 'territory:'+scope['region']
                active[key]=ref
        for key,ref in active.items():
            if ref['scope']['kind']=='territory':
                region=next((r for r in (world['initial'].get('society') or {}).get('regions',[]) if r['id']==ref['scope']['region']),None)
                if not region or position is None or not width:continue
                b=region['bounds'];x,y=position%width,position//width
                if not (b['x']<=x<b['x']+b['width'] and b['y']<=y<b['y']+b['height']):continue
            artifact=world.get('laws',{}).get('history',{}).get(key,{}).get(str(ref['revision']),{}).get('artifact',{})
            if hook in artifact.get('hooks',[]):return True
        return False

    def fail(event, message):
        violations.append(f"Event {event['id']} {message}")

    def matching_proofs(actor, digest=None, kinds=('prototype', 'practice')):
        return [p for p in proofs[actor] if p['kind'] in kinds and
                (digest is None or p.get('program_hash') == digest)]

    for event in events:
        kind, data, actor, eid = event['kind'], event['data'], event.get('actor'), event['id']
        key = (data.get('station'), data.get('job'))
        if kind == 'perception' and data.get('kind') == 'knowledge_report':
            acquisition = acquisitions.get(eid)
            if acquisition:
                rid = acquisition['record']
                held[actor].add(rid)
                if records.get(rid, {}).get('program'):
                    parent_events = {eid: event_index[eid] for eid in event.get('parents', []) if eid in event_index}
                    valid = any((p['kind'] == 'compute_retrieved' and p.get('actor') == actor
                                 and p['data'].get('record') == rid)
                                or (p['kind'] == 'knowledge_taught' and p['data'].get('target') == actor
                                    and p['data'].get('record') == rid)
                                or (p['kind'] == 'knowledge_consulted' and p.get('actor') == actor
                                    and p['data'].get('record') == rid)
                                for p in parent_events.values())
                    if not valid:
                        fail(event, 'receives executable knowledge without a recorded physical transfer')
        elif kind == 'program_inspected':
            rid = data.get('record')
            if rid not in held[actor] or not records.get(rid, {}).get('program'):
                fail(event, 'inspects source that is not personally held')
            elif data.get('program_hash') != records[rid]['program']['source_hash']:
                fail(event, 'inspection hash differs from held source')
            else:
                inspections[(actor, rid)] = eid
                source_reads.append(dict(**reference(event), record=rid, program_hash=data['program_hash']))
        elif kind == 'perception' and data.get('kind') == 'program_inspected':
            content = data.get('content', {})
            rid = content.get('record')
            if (rid not in held[actor] or (actor, rid) not in inspections or
                    content.get('program') != records.get(rid, {}).get('program')):
                fail(event, 'source response is foreign or differs from the owned artifact')
        elif kind == 'identity_change':
            for citation in citations[eid]:
                rid = citation['record']
                interpreted[(actor, rid)] = dict(event=eid, source=citation['source'],
                    source_inspected_before=inspections.get((actor, rid)))
                record = records.get(rid, {})
                experiment = record.get('experiment')
                if experiment and experiment.get('successful'):
                    job_key = (experiment.get('station'), experiment.get('job'))
                    completion = completions.get(job_key)
                    if (experiment.get('operator') == actor and record.get('author') == actor
                            and experiment.get('paid_quanta', 0) > 0 and completion
                            and completion['record']['id'] == rid and completion['event'] < eid):
                        proof = dict(record=rid, kind=experiment['kind'], actor=actor,
                            program_hash=experiment.get('program_hash'), interpretation=eid,
                            receipt=citation['source'], completed=completion['event'],
                            station=job_key[0], job=job_key[1])
                        proofs[actor].append(proof)
        elif kind == 'compute_submitted':
            jobs[key] = dict(event=eid, actor=actor, data=data)
            work_state[key] = dict(active=True, event=eid)
            for field, config in (('required_quanta', 'compute_quanta'), ('quantum_ms', 'compute_quantum_ms')):
                if config in balance and data.get(field) != balance[config]:
                    fail(event, f'job {field} differs from the configured physical work cost')
            experiment_kind = data.get('experiment_kind', 'builtin_forecast')
            if experiment_kind in ('builtin_forecast', 'law'):
                continue
            record = data.get('program_record', {})
            artifact = record.get('program') or {}
            digest = artifact.get('source_hash')
            if record.get('experiment'):
                fail(event, 'portable code record embeds private experiment evidence')
            try:
                if program_hash(artifact) != digest:
                    fail(event, 'program hash does not bind its exact source and contracts')
                if input_hash(data) != data.get('input_hash'):
                    fail(event, 'input hash does not bind the submitted experiment and sources')
            except (KeyError, AttributeError, OverflowError, TypeError, ValueError):
                fail(event, 'has an invalid program/hash payload')
            checked_hashes.add(digest)
            entry = dict(**reference(event), station=key[0], job=key[1], record=record.get('id'),
                program_hash=digest, inputs=data.get('input'), expected_results=data.get('expected_results'))
            if experiment_kind == 'prototype':
                bootstrap = matching_proofs(actor, kinds=('builtin_forecast', 'practice', 'prototype'))
                authority_changed=changed_research_rule(event,'research_authoring')
                entry['changed_authoring_rule_requires_review']=authority_changed
                if not bootstrap and not authority_changed:
                    fail(event, 'authors without own paid retrieved interpreted bootstrap evidence')
                if record.get('author') != actor or record.get('origin') != eid or not data.get('new_program'):
                    fail(event, 'new program lacks its author and submission origin')
                entry.update(bootstrap=bootstrap, built_in_forecast_bootstrap=any(p['kind']=='builtin_forecast' for p in bootstrap))
                authored.append(entry)
            elif experiment_kind in ('practice', 'run'):
                rid = record.get('id')
                assessment = interpreted.get((actor, rid))
                if rid not in held[actor] or not assessment:
                    fail(event, 'uses code without prior personal holding and interpretation')
                entry.update(code_interpretation=assessment, source_inspection=inspections.get((actor, rid)),
                    received_from_another_author=record.get('author') != actor)
                if experiment_kind == 'practice':
                    practices.append(entry)
                else:
                    exact = matching_proofs(actor, digest)
                    authority_changed=changed_research_rule(event,'research_use')
                    entry['changed_use_rule_requires_review']=authority_changed
                    if not exact and not authority_changed:
                        fail(event, 'runs without own assessed successful proof for this exact source hash')
                    entry['own_exact_hash_proofs'] = exact
                    entry['inspected_then_interpreted'] = bool(assessment and assessment['source_inspected_before'])
                    entry['transfer_practice_run_evidence'] = bool(record.get('author') != actor and
                        assessment and assessment['source_inspected_before'] and
                        any(p['kind']=='practice' for p in exact))
                    runs.append(entry)
            else:
                fail(event, 'has an unknown numeric experiment kind')
        elif kind == 'compute_quantum':
            pending = [k for k, state in work_state.items() if k[0]==key[0] and state['active']]
            if not pending or min(pending, key=lambda k: work_state[k]['event']) != key:
                fail(event, 'violates the station FIFO work order')
            for field, config in (('electricity', 'compute_electricity'), ('water', 'compute_water')):
                if config in balance and data.get(field) != balance[config]:
                    fail(event, f'quantum {field} differs from its configured physical price')
        elif kind == 'compute_cancelled':
            if key in work_state:
                work_state[key]['active'] = False
        elif kind == 'compute_completed':
            if key in work_state:
                work_state[key]['active'] = False
            submitted = jobs.get(key)
            record = data.get('record', {})
            experiment = record.get('experiment')
            completions[key] = dict(event=eid, record=record)
            if not submitted:
                fail(event, 'completes research without submission evidence')
                continue
            request = submitted['data']
            expected_kind = request.get('experiment_kind', 'builtin_forecast')
            if expected_kind == 'law':
                continue  # summarize_laws independently audits scoped-law cases and authority.
            if not experiment:
                fail(event, 'completed research lacks structured experiment evidence')
                continue
            for field, expected in dict(kind=expected_kind, operator=submitted['actor'], station=key[0],
                    job=key[1], input_hash=request.get('input_hash'), paid_quanta=request.get('required_quanta')).items():
                if experiment.get(field) != expected:
                    fail(event, f'experiment {field} differs from its paid request')
            if expected_kind != 'builtin_forecast':
                artifact = request.get('program_record', {}).get('program', {})
                expected_results = request.get('expected_results')
                output = experiment.get('output')
                error = experiment.get('runtime_error')
                matched = None if expected_results is None else output == expected_results
                successful = error is None and (matched is None or matched)
                for field, expected in dict(program_hash=artifact.get('source_hash'), inputs=request.get('input'),
                        expected_results=expected_results, predictions_matched=matched, successful=successful).items():
                    if experiment.get(field) != expected:
                        fail(event, f'experiment {field} differs from its source, prediction or result')
                if data.get('program_record') != request.get('program_record'):
                    fail(event, 'completion changes its portable source record')
                if data.get('output') != output or data.get('runtime_error') != error or data.get('successful') != successful:
                    fail(event, 'completion envelope disagrees with its experiment record')
                if output is not None and (not isinstance(output, list) or len(output)>64 or
                        any(type(v) is not int or not -(2**63)<=v<2**63 for v in output)):
                    fail(event, 'has an invalid numeric result vector')
                if (error is None) == (output is None):
                    fail(event, 'does not contain exactly one numeric output or bounded runtime error')
        elif kind == 'compute_erased':
            if key in work_state:
                work_state[key]['active'] = False
            erasures.append(dict(**reference(event), data=data))

    for station in world.get('infrastructure', {}).get('stations', []):
        for job in station.get('jobs', []):
            key = (station['seed']['id'], job['id'])
            submitted = jobs.get(key)
            if not submitted:
                continue  # The independent material audit reports the missing submission.
            request = submitted['data']
            event = event_index[submitted['event']]
            if job.get('input_hash') != request.get('input_hash') or job.get('source') != submitted['event']:
                fail(event, 'retained job differs from its submitted hash or origin')
            if request.get('experiment_kind') == 'law':
                continue  # The law reporter checks its differently shaped persisted work.
            if request.get('experiment_kind'):
                expected_work = dict(kind=request['experiment_kind'], program_record=request['program_record'],
                                     inputs=request['input'], expected_results=request.get('expected_results'))
                if job.get('program_work') != expected_work or job.get('input') is not None:
                    fail(event, 'retained program work differs from its paid request')
                if job.get('sources', []) != request.get('source_records', []):
                    fail(event, 'retained source copies differ from its paid request')
            elif job.get('input') != request.get('input') or job.get('program_work'):
                fail(event, 'retained forecast differs from its paid request')

    for run in runs:
        completion = completions.get((run['station'], run['job']))
        run['completion'] = completion['event'] if completion else None
        run['completed_successfully'] = bool(completion and
            completion['record'].get('experiment', {}).get('successful'))

    program_records = {rid: record for rid, record in records.items() if record.get('program')}
    experiments = [dict(record=rid, **record['experiment']) for rid, record in records.items() if record.get('experiment')]
    availability = {}
    for rid, record in program_records.items():
        copies = knowledge['final_availability'][rid]
        availability[rid] = dict(program_hash=record['program']['source_hash'], **copies,
            no_living_or_archive_access=not copies['living_carriers'] and not copies['archive_copies'],
            no_living_archive_or_terminal_copy=not copies['living_carriers'] and not copies['archive_copies'] and not copies['terminal_copies'],
            note='Dead personal holdings remain audit data. A dead-owner terminal copy is retained, '
                 'but current retrieval is owner-only; neither case grants another person access.')
    return dict(violations=violations, infrastructure_violations=utilities['violations'],
        copy_audit_violations=knowledge['copy_audit_violations'], accounts=utilities['accounts'],
        event_counts=dict(collections.Counter(e['kind'] for e in events if e['kind'].startswith(('compute_', 'program_')))),
        submitted_jobs=utilities['jobs'], availability_changes=utilities['availability_changes'],
        completed_experiments=experiments, retrievals=utilities['retrievals'], source_inspections=source_reads,
        interpretations=knowledge['accepted_citations'], authoring_submissions=authored,
        practice_submissions=practices, run_submissions=runs,
        personal_proofs={str(actor): items for actor, items in proofs.items()},
        teaching=[dict(**reference(e), data=e['data']) for e in events if e['kind']=='knowledge_taught'],
        erasures=erasures, deaths=knowledge['deaths'], archive_destructions=knowledge['archive_destructions'],
        disturbances=knowledge['authored_disturbances'], program_availability=availability,
        program_source_review=[dict(record=rid, **record['program']) for rid, record in program_records.items()],
        final_holdings=knowledge['players'], copy_timeline=knowledge['copy_timeline'],
        observed_evidence=dict(bootstrap_authorships=sum(a['built_in_forecast_bootstrap'] for a in authored),
            successful_prototypes=sum(e['kind']=='prototype' and e['successful'] for e in experiments),
            successful_practices=sum(e['kind']=='practice' and e['successful'] for e in experiments),
            successful_runs=sum(e['kind']=='run' and e['successful'] for e in experiments),
            transfer_practice_run_submissions=sum(r['transfer_practice_run_evidence'] for r in runs),
            transfer_practice_run_completions=sum(r['transfer_practice_run_evidence'] and r['completed_successfully'] for r in runs)),
        acceptance='Not automatically assigned. Human review of retained fresh model proposals, exact code, '
            'nonlinear multi-interval behavior, assumptions and consequences is required.',
        limitations='Paid matching predictions demonstrate only supplied test vectors. Chronology does not '
            'establish causality or usefulness. A copied report never counts as another actor\'s practice. '
            'Source inspection and personal interpretation are distinct. Source hashes identify exact '
            'payloads, not retrievable global code. Erasure/death/cabinet loss must be compared against all '
            'remaining terminal inputs, outputs, living personal copies and archives. Text, memories or '
            'independently invented equivalents may survive exact-program loss. Model call counts alone '
            'do not prove autonomous invention; no observer artifact is participant input.')


def summarize(out):
    out = Path(out).resolve()
    upstream_error = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            knowledge = summarize_knowledge(out)
    except (Exception, SystemExit) as error:
        upstream_error = str(error)
        retained = out / 'KNOWLEDGE_RESULT.json'
        if not retained.is_file():
            raise
        knowledge = json.loads(retained.read_text())
    snapshot = json.loads(Path(knowledge['source']).read_text())
    result = analyze(snapshot['world'], snapshot['events'])
    result['upstream_error'] = upstream_error
    for field in ('run', 'seconds', 'source', 'source_sha256', 'model_calls', 'reported_tokens',
                  'engine_errors', 'scope_violations', 'conservation_violations', 'base_check_failures'):
        result[field] = knowledge[field]
    (out / 'RESEARCH_RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('run', 'observed_evidence', 'violations',
        'infrastructure_violations', 'copy_audit_violations', 'acceptance')}, indent=2))
    if upstream_error or result['violations'] or result['infrastructure_violations'] or result['copy_audit_violations']:
        raise SystemExit('Research evidence audit failed; inspect RESEARCH_RESULT.json')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    summarize(parser.parse_args().output)
