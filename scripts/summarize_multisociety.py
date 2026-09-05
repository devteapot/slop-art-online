#!/usr/bin/env python3
"""Describe recorded inter-settlement effects without scoring society or migration.

Initial homes label origins for analysis, not enduring membership or ownership.
Only committed movement/resources and recorded knowledge receipts count as effects.
"""
import argparse
import bisect
import collections
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re

from summarize_knowledge import analyze as analyze_knowledge, summarize as summarize_knowledge

REPORT_VERSION = 'multisociety-evidence-v1'
DETAIL_LIMIT = 64


def reference(event):
    return dict(event=event['id'], actor=event.get('actor'), kind=event['kind'],
                time_ms=event.get('data', {}).get('time_ms'), parents=event.get('parents', []))


def skill_id(value):
    return value if isinstance(value, str) else value.get('script') if isinstance(value, dict) else None


def limited(items, limit=DETAIL_LIMIT):
    """Retain both ends of a long trace; full evidence remains in the hashed snapshot."""
    if len(items) <= limit:
        return dict(total=len(items), shown=items, omitted=0)
    first = limit // 2
    return dict(total=len(items), shown=items[:first] + items[-(limit - first):], omitted=len(items) - limit)


def explanation(event):
    data = event.get('data', {})
    value = data.get('reported_explanation', data.get('reason', data.get('command', {}).get('reason')))
    return value if isinstance(value, str) else None


def analyze(world, events, knowledge=None):
    events = sorted(events, key=lambda event: event['id'])
    index = {event['id']: event for event in events}
    knowledge = analyze_knowledge(world, events) if knowledge is None else knowledge
    initial = world['initial']
    origins = {player['id']: player['position'] for player in initial['players']}
    camps = sorted(set(origins.values()))
    final = {player['id']: player for player in world['players']}
    end = world['timing']['time_ms']
    births = [reference(e) for e in events if e['kind'] == 'actor_created']
    violations = []
    if len(index) != len(events):
        violations.append('Duplicate event IDs prevent an unambiguous event trace')
    if len(origins) != len(initial['players']) or len(final) != len(world['players']):
        violations.append('Duplicate actor IDs prevent an unambiguous fixed-population audit')
    if births:
        violations.append('actor_created events occurred in a fixed-population trial')
    if set(origins) != set(final):
        violations.append('Final actor identities differ from the initial retained population')
    if initial.get('lifecycle') is not None:
        violations.append('Population renewal is configured in this fixed-population trial')

    positions = dict(origins)
    alive = {p['id'] for p in initial['players'] if p['health'] > 0}
    residence_start = {actor: (0, None) for actor in alive}
    intervals = collections.defaultdict(list)
    arrivals = collections.defaultdict(list)
    departures, last_arrivals = {}, {}
    completed_at_camp = collections.defaultdict(collections.Counter)
    intents = collections.defaultdict(list)
    material_actions = collections.defaultdict(list)
    gathering = collections.defaultdict(list)
    transfers, deposits = [], []
    all_transfer_count = 0
    last_time = {actor: 0 for actor in origins}

    def attempt_for(event):
        if event['kind'] == 'skill_attempt':
            return event
        return next((index[parent] for parent in event.get('parents', [])
                     if parent in index and index[parent]['kind'] == 'skill_attempt'
                     and index[parent].get('actor') == event.get('actor')), None)

    def close_residence(actor, time_ms, exit_event, reason):
        start = residence_start.pop(actor, None)
        if start is not None:
            started, entry = start
            intervals[actor].append(dict(camp=positions[actor], start_ms=started, end_ms=time_ms,
                duration_ms=max(0, time_ms - started), entry=entry, exit=exit_event, ended_by=reason))

    for event in events:
        actor, kind, data = event.get('actor'), event['kind'], event.get('data', {})
        if actor not in origins:
            continue
        time_ms = data.get('time_ms')
        if type(time_ms) is not int or not 0 <= time_ms <= end or time_ms < last_time[actor]:
            violations.append(f"Event {event['id']} has missing, out-of-range or decreasing actor time")
            continue
        last_time[actor] = time_ms
        if kind in ('decision', 'policy_patched'):
            intents[actor].append(dict(**reference(event), reported_explanation=explanation(event)))
        if kind == 'death':
            close_residence(actor, time_ms, reference(event), 'death')
            alive.discard(actor)
            continue
        attempt = attempt_for(event)
        move = ((kind == 'skill_progress' and attempt is not None
                 and skill_id(attempt['data'].get('action', {}).get('skill')) == 'move')
                or (kind == 'skill_result' and data.get('status') == 'completed'
                    and skill_id(data.get('skill')) == 'move'))
        destination = None
        if move:
            destination = data.get('position') if kind == 'skill_progress' else data.get('after', {}).get('position')
        if move and type(destination) is int and destination != positions[actor]:
            if actor not in alive:
                violations.append(f"Event {event['id']} moves an actor after recorded death")
                continue
            old = positions[actor]
            if old in camps:
                close_residence(actor, time_ms, reference(event), 'departure')
                departures[actor] = dict(camp=old, **reference(event))
            positions[actor] = destination
            if destination in camps:
                arrival = dict(**reference(event), initial_home=origins[actor], camp=destination,
                    from_position=old, previous_camp_departure=departures.get(actor),
                    attempt=reference(attempt) if attempt else None,
                    away_from_initial_home=destination != origins[actor])
                arrivals[actor].append(arrival)
                last_arrivals[actor] = arrival
                residence_start[actor] = (time_ms, reference(event))
                material_actions[actor].append((event, destination, 'camp_arrival'))
        if kind == 'skill_result' and data.get('status') == 'completed' and positions[actor] in camps:
            skill = skill_id(data.get('skill'))
            if skill in ('eat', 'rest', 'gather', 'build', 'give', 'deposit'):
                completed_at_camp[(actor, positions[actor])][skill] += 1
        if kind == 'food_transfer':
            all_transfer_count += 1
            target = data.get('target')
            if target not in origins:
                violations.append(f"Event {event['id']} transfers food to an unknown initial actor")
                continue
            if type(data.get('amount')) is not int or data['amount'] <= 0:
                violations.append(f"Event {event['id']} has invalid transferred food quantity")
                continue
            location = data.get('location')
            material_actions[actor].append((event, location, 'food_transfer'))
            if origins[actor] != origins[target]:
                transfers.append(dict(**reference(event), target=target, amount=data['amount'], location=location,
                    source_initial_home=origins[actor], target_initial_home=origins[target],
                    attempt=reference(attempt) if attempt else None,
                    skill=skill_id(attempt['data'].get('action', {}).get('skill')) if attempt else None))
        if kind == 'resource_change' and data.get('food_delta', 0) < 0:
            location = data.get('location')
            gathering[actor].append(dict(**reference(event), location=location,
                site_initial_residents=sorted(a for a, home in origins.items() if home == location),
                amount=-data['food_delta']))
            material_actions[actor].append((event, location, 'food_collection'))
        elif kind == 'resource_change' and data.get('nature') == 'deposit' and data.get('food_delta', 0) > 0:
            location = data.get('location')
            material_actions[actor].append((event, location, 'food_deposit'))
            if location in camps:
                prior = [g for g in gathering[actor] if g['location'] != location]
                groups = []
                for origin in sorted({g['location'] for g in prior}):
                    records = [g for g in prior if g['location'] == origin]
                    groups.append(dict(location=origin, earlier_collection_count=len(records),
                        earlier_collected_amount=sum(g['amount'] for g in records),
                        first=records[0], latest=records[-1]))
                arrival = last_arrivals.get(actor)
                deposits.append(dict(**reference(event), initial_home=origins[actor], location=location,
                    amount=data['food_delta'], latest_camp_arrival=arrival,
                    earlier_gathering_elsewhere=groups,
                    interpretation='Actual deposit of carried food. Earlier gathering elsewhere and travel are '
                        'relocation evidence only; initial food, receipts, eating and later gathering prevent '
                        'identifying the deposited fungible units with any particular earlier harvest.'))

    rows = []
    for actor, home in origins.items():
        player = final.get(actor, {})
        if actor in alive:
            close_residence(actor, end, None, 'snapshot_end')
        if player.get('position') != positions[actor]:
            violations.append(f'Actor {actor} final position differs from the recorded movement trace')
        if (actor in alive) != (player.get('health', 0) > 0):
            violations.append(f'Actor {actor} final mortality differs from recorded death events')
        camp_rows = []
        for camp in camps:
            stays = [interval for interval in intervals[actor] if interval['camp'] == camp]
            camp_rows.append(dict(camp=camp, living_time_ms=sum(s['duration_ms'] for s in stays),
                longest_interval_ms=max((s['duration_ms'] for s in stays), default=0),
                interval_count=len(stays), completed_skills=dict(completed_at_camp[(actor, camp)])))
        away = [interval for interval in intervals[actor] if interval['camp'] != home]
        rows.append(dict(actor=actor, name=player.get('name'), initial_home=home,
            final_position=player.get('position'), final_alive=player.get('health', 0) > 0,
            final_reported_goal=player.get('current_goal'), camp_residence=camp_rows,
            nonhome_camp_time_ms=sum(stay['duration_ms'] for stay in away),
            nonhome_residence_intervals=limited(away), camp_arrivals=limited(arrivals[actor]),
            policy_intent_references=limited(intents[actor]),
            interpretation='Measured residence at exact camp cells, bounded by committed movement, death or '
                'snapshot end. Visits, long stays, or an endpoint away from home do not automatically '
                'establish migration or social membership; inspect repeated activity and reported intent.'))

    seeded = {int(actor): {r['id'] for r in records} for actor, records in initial.get('knowledge', {}).items()}
    surveys = {r['id'] for records in initial.get('knowledge', {}).values() for r in records
               if r['id'].startswith('settlement-survey-') and r.get('location') is None
               and r.get('topic') == 'Surveyed settlement locations'}
    useful_records = {rid: record for rid, record in knowledge['records'].items() if rid not in surveys}
    acquisitions = knowledge['acquisitions']
    first, sources = {}, collections.defaultdict(set)
    for acquisition in acquisitions:
        key = (acquisition['actor'], acquisition['record'])
        first.setdefault(key, acquisition)
        sources[key].add(acquisition['event'])
    citations = [dict(c, learner_initial_home=origins.get(c['actor']))
                 for c in knowledge['accepted_citations'] if c['record'] not in surveys]
    patterns = {rid: re.compile(r'(?<![\w.-])' + re.escape(rid) + r'(?![\w-]|\.(?=[\w.-]))') for rid in useful_records}

    def explicit_links(actor, rid, event):
        attempt = attempt_for(event)
        if not attempt:
            return []
        links = []
        for parent in attempt.get('parents', []):
            evidence = index.get(parent)
            if not evidence or evidence.get('actor') != actor:
                continue
            if evidence['kind'] == 'guard_evaluated':
                receipts = sorted(set(evidence.get('parents', [])) & sources[(actor, rid)])
                if receipts:
                    links.append(dict(kind='guard_cites_owned_report_source', evidence=reference(evidence), receipts=receipts))
            reason = explanation(evidence)
            if evidence['kind'] in ('decision', 'participant_command', 'policy_patched') and reason and patterns[rid].search(reason):
                links.append(dict(kind='reported_decision_cites_record_id', evidence=reference(evidence), reported_explanation=reason))
        return links

    distribution, later = [], []
    for rid, record in sorted(useful_records.items()):
        record_acquisitions = [a for a in acquisitions if a['record'] == rid]
        new = [a for a in record_acquisitions if a['first_observed_copy']]
        learned = [a for a in new if rid not in seeded.get(a['actor'], set())]
        operations = [e for e in events if e['kind'] in ('knowledge_taught', 'knowledge_consulted', 'knowledge_recorded')
                      and e['data'].get('record') == rid]
        distribution.append(dict(record=record, author_initial_home=origins.get(record.get('author')),
            initial_holders=sorted(a for a, records in seeded.items() if rid in records),
            first_nonseed_copies=[dict(a, learner_initial_home=origins.get(a['actor']),
                sender_initial_home=origins.get(a.get('from_actor')),
                author_initial_home=origins.get(record.get('author'))) for a in learned],
            first_nonseed_copy_counts_by_origin=dict(collections.Counter(str(origins.get(a['actor'])) for a in learned)),
            repeat_receipts=sum(not a['first_observed_copy'] for a in record_acquisitions),
            new_copy_operations=dict(collections.Counter(e['kind'] for e in operations if e['data'].get('new_copy', e['data'].get('added')) is True)),
            repeat_copy_operations=dict(collections.Counter(e['kind'] for e in operations if e['data'].get('new_copy', e['data'].get('added')) is False)),
            final_availability=knowledge['final_availability'].get(rid),
            final_personal_interpretations=[dict(actor=p['actor'], learner_initial_home=origins.get(p['actor']), **h)
                for p in knowledge['players'] for h in p['holdings'] if h['record'] == rid]))
        for acquisition in new:
            actor, source = acquisition['actor'], acquisition['event']
            candidates = material_actions[actor]
            offset = bisect.bisect_right([e[0]['id'] for e in candidates], source)
            selected = [(e, location, category) for e, location, category in candidates[offset:]
                        if record.get('location') is None or location == record['location']]
            linked, temporal = [], []
            for event, location, category in selected:
                links = explicit_links(actor, rid, event)
                evidence = dict(**reference(event), category=category, location=location,
                    explicit_references=links,
                    connection='explicit record reference in guard or reported decision' if links else 'temporal association only')
                (linked if links else temporal).append(evidence)
            shown = sorted(linked[:6] + temporal[:3], key=lambda e: e['event'])
            later.append(dict(actor=actor, learner_initial_home=origins.get(actor), record=rid,
                acquisition=source, seeded_prior=rid in seeded.get(actor, set()),
                location=record.get('location'), matching_location_action_count=len(selected),
                explicitly_referenced_action_count=len(linked), temporal_only_action_count=len(temporal),
                shown=shown, omitted=len(selected) - len(shown),
                interpretation='These are completed material effects or camp arrivals after receipt. Location '
                    'and chronology alone do not show influence. An explicit reference records what a guard '
                    'or reported explanation cited; it does not establish truth, mastery or exclusive causation.'))

    return dict(report_version=REPORT_VERSION, rules_version=world.get('version'),
        initial_population=len(origins), final_retained_population=len(final),
        living_population=sum(p.get('health', 0) > 0 for p in final.values()),
        origin_groups=[dict(initial_home=camp, initial_actors=sorted(a for a, home in origins.items() if home == camp),
            final_living_actors_at_camp=sorted(a for a, p in final.items() if p['health'] > 0 and p['position'] == camp)) for camp in camps],
        fixed_population_creation_events=births, evidence_audit_violations=violations,
        all_food_transfer_count=all_transfer_count, cross_origin_food_transfers=limited(transfers, 256),
        cross_origin_transferred_amount=sum(t['amount'] for t in transfers),
        camp_deposits=limited(deposits, 256), residence_evidence=rows,
        useful_report_distribution=distribution, accepted_report_interpretations=limited(citations, 256),
        subsequent_action_evidence=later,
        excluded_geometry_survey_ids=sorted(surveys),
        knowledge_audit=dict(copy_audit_violations=knowledge['copy_audit_violations'],
            all_record_count=len(knowledge['records']), all_event_counts=knowledge['event_counts'],
            all_new_copy_operations=knowledge['new_copy_operations'], all_repeat_copy_operations=knowledge['repeat_copy_operations']),
        limitations='Initial home is an analysis label, not current allegiance or ownership. All fixed-identity '
            'and knowledge-copy audits retain every record, including personal survey priors excluded from '
            'useful-report distribution. Co-location and speech do not transfer exact records automatically. '
            'Food transfers are actual effects; fungible food is not assigned invented item provenance. '
            'Exact-cell residence excludes travel and other cells and ends at recorded death. No endpoint '
            'or duration automatically means migration, cooperation, alliance or success. Detail arrays may '
            'be bounded with explicit omitted counts; consult the hashed snapshot for complete event traces.')


def summarize(out):
    out = Path(out).resolve()
    pilot = json.loads((out / 'pilot.json').read_text())
    if pilot['phase'] != 'completed':
        raise ValueError('Multi-society analysis requires a completed experiment')
    run = out / pilot['run']
    source = run / ('final-snapshot.json' if (run / 'final-snapshot.json').is_file() else 'snapshot.json')
    source_bytes = source.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    snapshot = json.loads(source_bytes)
    failures = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            knowledge = summarize_knowledge(out)
    except (Exception, SystemExit) as error:
        failures.append(dict(check='composed_knowledge_society_arena', error=str(error)))
        knowledge = analyze_knowledge(snapshot['world'], snapshot['events'])
    society_path = out / 'SOCIETY_RESULT.json'
    society = json.loads(society_path.read_text()) if society_path.is_file() else {}
    if society.get('source_sha256') != source_hash:
        failures.append(dict(check='society_snapshot', error='No society report for this snapshot hash'))
        society = {}
    result = analyze(snapshot['world'], snapshot['events'], knowledge)
    result.update(run=pilot['run'], phase=pilot['phase'], seconds=snapshot['world']['timing']['time_ms'] / 1000,
        updates=snapshot['world']['timing']['updates'], source=str(source.relative_to(out)), source_sha256=source_hash,
        base_check_failures=failures,
        food_balance={key: society.get(key) for key in ('initial_food', 'produced', 'final_food', 'eaten',
            'lifecycle_food_consumed', 'food_consumed_by_reason', 'conservation_violations')},
        model_calls=society.get('model_calls'), reported_tokens=society.get('reported_tokens'),
        underlying_reports=dict(knowledge='KNOWLEDGE_RESULT.json', society='SOCIETY_RESULT.json', arena='LIVE_RESULT.json'))
    (out / 'MULTISOCIETY_RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('run', 'seconds', 'initial_population', 'living_population',
        'cross_origin_transferred_amount', 'evidence_audit_violations', 'base_check_failures')}, indent=2))
    if failures or result['evidence_audit_violations'] or result['knowledge_audit']['copy_audit_violations']:
        raise SystemExit('Multi-society evidence checks failed; inspect MULTISOCIETY_RESULT.json')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    summarize(parser.parse_args().output)
