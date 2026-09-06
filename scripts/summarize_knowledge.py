#!/usr/bin/env python3
"""Inspect retained knowledge events, exact-record copies and later action candidates.

This reads authority evidence only. It neither advances a world nor equates repeated
consultations, speech, or chronological associations with new learning or causal proof.
"""
import argparse
import bisect
import collections
import contextlib
import hashlib
import io
import json
from pathlib import Path

from summarize_arena_matrix import summarize as summarize_arena
from summarize_society import summarize as summarize_society

KNOWLEDGE_EVENTS = ('knowledge_seeded', 'knowledge_asserted', 'knowledge_taught',
                    'knowledge_recorded', 'knowledge_consulted', 'archive_destroyed',
                    'compute_completed', 'compute_retrieved')


def reference(event):
    return dict(event=event['id'], kind=event['kind'], actor=event.get('actor'),
                time_ms=event['data'].get('time_ms'), parents=event.get('parents', []))


def analyze(world, events):
    """Reconcile the recorded copy ledger with final state, retaining evidence IDs."""
    events = sorted(events, key=lambda e: e['id'])
    index = {e['id']: e for e in events}
    violations = []
    if len(index) != len(events):
        violations.append('Duplicate event IDs prevent an unambiguous copy audit')
    initial = world['initial']
    personal = {p['id']: set() for p in initial['players']}
    alive = {p['id'] for p in initial['players'] if p['health'] > 0}
    archives = {a['id']: set() for a in initial.get('archives', [])}
    destroyed = set()
    terminals = {}
    records, acquisitions, timeline, deaths, destructions, interventions = {}, [], [], [], [], []
    operation_counts = collections.Counter()
    added_counts = collections.Counter()
    repeat_counts = collections.Counter()
    unknown_counts = collections.Counter()

    def availability():
        return {record: dict(living_carriers=sorted(a for a, copies in personal.items() if a in alive and record in copies),
                             dead_holders=sorted(a for a, copies in personal.items() if a not in alive and record in copies),
                             archive_copies=sorted(a for a, copies in archives.items() if a not in destroyed and record in copies),
                             terminal_copies=[dict(station=s, job=j, owner=copy['owner'], owner_alive=copy['owner'] in alive)
                                              for (s, j), copy in sorted(terminals.items()) if copy['record']==record])
                for record in sorted(records)}

    def mark_copy(event, copies, record, declared):
        new = record not in copies
        if type(declared) is bool and declared != new:
            violations.append(f"Event {event['id']} new_copy conflicts with earlier recorded copies")
        copies.add(record)
        return new

    for event in events:
        kind, data, actor = event['kind'], event['data'], event.get('actor')
        before = availability() if kind in ('death', 'archive_destroyed') else None
        changed = False
        if kind == 'actor_created':
            if actor in personal:
                violations.append(f"Event {event['id']} reuses an existing actor identity")
            else:
                personal[actor] = set()
                resources = data.get('initial_resources', {})
                if resources.get('health', 0) > 0:
                    alive.add(actor)
                else:
                    violations.append(f"Event {event['id']} lacks a live creation resource baseline")
                changed = True
        if kind in KNOWLEDGE_EVENTS:
            operation_counts[kind] += 1
            if kind in ('knowledge_taught', 'knowledge_recorded', 'knowledge_consulted', 'compute_retrieved'):
                declared = data.get('new_copy', data.get('added'))
                counter = added_counts if declared is True else repeat_counts if declared is False else unknown_counts
                counter[kind] += 1
        if kind == 'compute_completed':
            record = data.get('record', {})
            rid = record.get('id')
            key = (data.get('station'), data.get('job'))
            if not rid or None in key or record.get('origin') != event['id']:
                violations.append(f"Event {event['id']} lacks its material compute output record")
            elif key in terminals or rid in records:
                violations.append(f"Event {event['id']} reuses a terminal output or record identity")
            else:
                records[rid] = record
                terminals[key] = dict(record=rid, owner=actor)
                changed = True
        elif kind == 'compute_retrieved':
            copy = terminals.get((data.get('station'), data.get('job')))
            if not copy or copy['record'] != data.get('record') or copy['owner'] != actor:
                violations.append(f"Event {event['id']} retrieves a missing or foreign terminal output")
        elif kind == 'perception' and data.get('kind') == 'knowledge_report':
            content = data.get('content', {})
            record = content.get('record', {})
            rid = record.get('id')
            if rid is None or actor not in personal:
                violations.append(f"Event {event['id']} has an unresolvable knowledge recipient or record")
                continue
            if rid in records and records[rid] != record:
                violations.append(f"Event {event['id']} changes immutable record payload {rid}")
            records[rid] = record
            changed = mark_copy(event, personal[actor], rid, content.get('new_copy'))
            acquisitions.append(dict(**reference(event), record=rid, via=content.get('via'),
                                     from_actor=data.get('from'), new_copy=content.get('new_copy'),
                                     first_observed_copy=changed, location=record.get('location')))
        elif kind == 'knowledge_recorded':
            archive, rid = data.get('archive'), data.get('record')
            if archive not in archives or archive in destroyed:
                violations.append(f"Event {event['id']} writes an unknown or destroyed archive")
            else:
                changed = mark_copy(event, archives[archive], rid, data.get('new_copy', data.get('added')))
        elif kind == 'death':
            alive.discard(actor)
            changed = True
            deaths.append(dict(**reference(event), copies_before=before, copies_after=availability()))
        elif kind == 'archive_destroyed':
            archive = data.get('archive')
            known = archives.get(archive)
            if known is None:
                violations.append(f"Event {event['id']} destroys an unknown archive")
            else:
                if data.get('copies_destroyed') != len(known):
                    violations.append(f"Event {event['id']} destroyed-copy count differs from recorded archive contents")
                removed = sorted(known)
                known.clear()
                destroyed.add(archive)
                changed = True
                destructions.append(dict(**reference(event), archive=archive, records_destroyed=removed,
                                         copies_before=before, copies_after=availability()))
        elif kind == 'scenario_disturbance':
            interventions.append(dict(**reference(event), index=data.get('index'),
                                      scheduled_time_ms=data.get('scheduled_time_ms'), status=data.get('status'),
                                      action=data.get('action'), reason=data.get('reason')))
        if changed:
            timeline.append(dict(**reference(event), records=availability()))

    final_players = []
    for player in world['players']:
        actor = player['id']
        holdings = player.get('knowledge', [])
        actual = {h['record']['id'] for h in holdings}
        if personal.get(actor, set()) != actual:
            violations.append(f'Actor {actor} final holdings differ from the recorded acquisition ledger')
        if (actor in alive) != (player['health'] > 0):
            violations.append(f'Actor {actor} final mortality differs from recorded death events')
        final_players.append(dict(actor=actor, name=player.get('name'), alive=player['health'] > 0,
                                  holdings=[dict(record=h['record']['id'], source=h.get('source'),
                                                 interpreted_source=h.get('interpreted_source'),
                                                 interpretation=h.get('interpretation'), confidence=h.get('confidence')) for h in holdings]))
    final_archives = []
    final_terminals = {}
    for station in world.get('infrastructure', {}).get('stations', []):
        for job in station.get('jobs', []):
            record = job.get('report')
            if record:
                key = (station['seed']['id'], job['id'])
                final_terminals[key] = dict(record=record['id'], owner=job['owner'])
                if records.get(record['id']) != record:
                    violations.append(f'Terminal job {key} changes its recorded output payload')
    if final_terminals != terminals:
        violations.append('Final physical terminal copies differ from recorded completed jobs')
    for archive in world.get('archives', []):
        aid = archive['id']
        actual = {r['id'] for r in archive.get('records', [])}
        if archives.get(aid, set()) != actual or (aid in destroyed) != archive['destroyed']:
            violations.append(f'Archive {aid} final state differs from the recorded copy ledger')
        final_archives.append(dict(archive=aid, position=archive['position'], destroyed=archive['destroyed'],
                                   revision=archive['revision'], records=sorted(actual)))

    reports_by_source = {a['event']: a for a in acquisitions}
    citations = []
    for event in events:
        if event['kind'] != 'identity_change':
            continue
        data = event['data']
        reflections = data.get('reflections')
        if reflections is None:
            reflections = [dict(source=source, interpretation=data.get('interpretation'))
                           for source in event.get('parents', []) if source in reports_by_source]
        for reflection in reflections:
            source = reflection.get('source')
            acquisition = reports_by_source.get(source)
            if acquisition and acquisition['actor'] == event.get('actor'):
                citations.append(dict(**reference(event), source=source, record=acquisition['record'],
                                      interpretation=reflection.get('interpretation'),
                                      derived_assertion=reflection.get('knowledge')))

    relevant_actions, policy_changes = collections.defaultdict(list), collections.defaultdict(list)
    for event in events:
        if event['kind'] == 'skill_attempt' and event['data'].get('action', {}).get('skill') in ('move', 'gather', 'teach', 'record', 'consult'):
            relevant_actions[event.get('actor')].append(event)
        elif event['kind'] in ('policy_installed', 'policy_patched', 'decision'):
            policy_changes[event.get('actor')].append(event)
    action_ids = {actor: [e['id'] for e in items] for actor, items in relevant_actions.items()}
    policy_ids = {actor: [e['id'] for e in items] for actor, items in policy_changes.items()}
    later = []
    for acquisition in acquisitions:
        if not acquisition['first_observed_copy']:
            continue
        actor, source = acquisition['actor'], acquisition['event']
        pos = bisect.bisect_right(action_ids.get(actor, []), source)
        policy_pos = bisect.bisect_right(policy_ids.get(actor, []), source)
        later.append(dict(actor=actor, record=acquisition['record'], source=source,
                          link='temporal candidates; not proof that acquisition caused action',
                          citations=[dict(event=c['event'], source=c['source']) for c in citations
                                     if c['actor'] == actor and c['record'] == acquisition['record'] and c['event'] > source],
                          policy_changes=[reference(e) for e in policy_changes[actor][policy_pos:policy_pos + 3]],
                          attempts=[dict(**reference(e), action=e['data']['action'],
                                         recorded_location_matches=acquisition['location'] is not None and
                                         (e['data']['action'].get('destination') == acquisition['location'] or
                                          e['data'].get('before', {}).get('position') == acquisition['location']))
                                    for e in relevant_actions[actor][pos:pos + 6]]))

    first_acquisitions = {}
    for acquisition in acquisitions:
        first_acquisitions.setdefault((acquisition['actor'], acquisition['record']), acquisition)
    location_evidence = []
    locations = {r['location'] for r in records.values() if r.get('location') is not None}
    for event in events:
        data = event['data']
        visit = event['kind'] == 'perception' and data.get('kind') == 'site'
        gathering = event['kind'] == 'resource_change' and data.get('food_delta', 0) < 0
        if (visit or gathering) and data.get('location') in locations:
            matches = []
            for rid, record in records.items():
                if record.get('location') != data['location']:
                    continue
                acquisition = first_acquisitions.get((event.get('actor'), rid))
                matches.append(dict(record=rid, prior_acquisition=acquisition['event'] if acquisition and acquisition['event'] < event['id'] else None))
            location_evidence.append(dict(**reference(event), location=data['location'],
                                          evidence='direct site perception' if visit else 'recorded food collection',
                                          food_delta=data.get('food_delta'), records=matches))

    first_deaths = {}
    for event in events:
        if event['kind'] == 'death':
            first_deaths.setdefault(event.get('actor'), event)
    post_author_death = []
    for event in events:
        if event['kind'] not in ('knowledge_taught', 'knowledge_consulted', 'knowledge_recorded'):
            continue
        rid = event['data'].get('record')
        death = first_deaths.get(records.get(rid, {}).get('author'))
        if death and death['id'] < event['id']:
            post_author_death.append(dict(**reference(event), record=rid,
                                          author_death=reference(death), new_copy=event['data'].get('new_copy'),
                                          archive=event['data'].get('archive'), target=event['data'].get('target')))
    location_summary = []
    for (actor, rid), acquisition in first_acquisitions.items():
        matches = [e for e in location_evidence if e['actor'] == actor
                   and any(r['record'] == rid for r in e['records'])]
        visits = [e for e in matches if e['evidence'] == 'direct site perception']
        after = [e for e in matches if e['event'] > acquisition['event']]
        after_visits = [e for e in after if e['evidence'] == 'direct site perception']
        after_gathers = [e for e in after if e['evidence'] == 'recorded food collection']
        if records[rid].get('location') is not None:
            location_summary.append(dict(actor=actor, record=rid, location=records[rid]['location'],
                                         acquisition=acquisition['event'],
                                         first_observed_visit=visits[0]['event'] if visits else None,
                                         first_visit_after_acquisition=after_visits[0]['event'] if after_visits else None,
                                         first_collection_after_acquisition=after_gathers[0]['event'] if after_gathers else None,
                                         collected_after_acquisition=-sum(e['food_delta'] for e in after_gathers)))

    return dict(event_counts=dict(operation_counts), new_copy_operations=dict(added_counts),
                repeat_copy_operations=dict(repeat_counts), unknown_copy_operations=dict(unknown_counts),
                records=records, players=final_players, archives=final_archives, final_availability=availability(),
                acquisitions=acquisitions, distinct_personal_acquisitions=sum(a["first_observed_copy"] for a in acquisitions),
                repeat_reports=sum(not a["first_observed_copy"] for a in acquisitions),
                copy_timeline=timeline, deaths=deaths, archive_destructions=destructions,
                creation_events=[dict(**reference(e), data=e['data']) for e in events if e['kind']=='actor_created'],
                authored_disturbances=interventions, accepted_citations=citations, later_action_candidates=later,
                record_location_evidence=location_evidence, record_location_summary=location_summary,
                operations_after_author_death=post_author_death,
                assertions=[dict(**reference(e), record=e['data'].get('id'), evidence=e['data'].get('evidence'))
                            for e in events if e['kind'] == 'knowledge_asserted'],
                knowledge_events=[dict(**reference(e), data=e['data']) for e in events if e['kind'] in KNOWLEDGE_EVENTS],
                copy_audit_violations=violations)


def summarize(out):
    out = Path(out).resolve()
    pilot = json.loads((out / 'pilot.json').read_text())
    if pilot['phase'] != 'completed':
        raise ValueError('Knowledge analysis requires a completed experiment')
    run = out / pilot['run']
    source = run / 'final-snapshot.json'
    if not source.is_file():
        source = run / 'snapshot.json'
    snapshot = json.loads(source.read_text())
    # Reuse existing invariant checks, retaining their detailed artifacts even on
    # failure. A failed comparison cannot silently become a successful knowledge run.
    failures = []
    for label, method in [('arena', summarize_arena), ('society', summarize_society)]:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                method(out)
        except (Exception, SystemExit) as error:
            failures.append(dict(check=label, error=str(error)))
    arena_path, society_path = out / 'LIVE_RESULT.json', out / 'SOCIETY_RESULT.json'
    arena = json.loads(arena_path.read_text()) if arena_path.exists() else {}
    society = json.loads(society_path.read_text()) if society_path.exists() else {}
    world = snapshot['world']
    result = analyze(world, snapshot['events'])
    result.update(run=pilot['run'], phase=pilot['phase'], seconds=world['timing']['time_ms'] / 1000,
                  updates=world['timing']['updates'], source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  base_check_failures=failures, engine_errors=arena.get('engine_errors'), scope_violations=arena.get('scope_violations'),
                  conservation_violations=society.get('conservation_violations'),
                  model_calls=society.get('model_calls'), reported_tokens=society.get('reported_tokens'),
                  invariant_details=dict(arena=str(arena_path), society=str(society_path)),
                  limitations='Exact-record copy counts are reconstructed from retained authority events and reconciled with final state. '
                              'Dead personal holdings are retained for audit but are not accessible carriers. No accessible exact-record '
                              'copy does not establish semantic knowledge loss: derived assertions, speech or memories may retain information. '
                              'new_copy=false operations refresh existing evidence and are not counted as new holders. Citations identify '
                              'accepted reported interpretations; subsequent policy/actions and location visits are candidates for causal '
                              'inspection, not proof of cause. Acquisition and preserved text do not establish belief, mastery or usefulness. '
                              'This is observer analysis, never participant input; no automatic Stage2 pass is assigned.')
    (out / 'KNOWLEDGE_RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('run', 'seconds', 'event_counts', 'new_copy_operations', 'repeat_copy_operations',
                                                  'final_availability', 'copy_audit_violations', 'base_check_failures')}, indent=2))
    if failures or result['copy_audit_violations']:
        raise SystemExit('Knowledge evidence checks failed; inspect KNOWLEDGE_RESULT.json')
    return result


def self_test():
    """Small recorded-evidence fixture: no world, authority or provider launches."""
    events = []
    record = dict(id='route-cache', author=1, origin=1, topic='field-notes', text='fixture', location=56, confidence=75)

    def event(kind, actor=None, **data):
        eid = len(events) + 1
        events.append(dict(id=eid, kind=kind, actor=actor, parents=[], data=dict(time_ms=eid * 50, **data)))
        return eid

    # Inline construction avoids confusing world-event kinds with percept kinds.
    def acquisition(actor, new):
        eid = len(events) + 1
        events.append(dict(id=eid, kind='perception', actor=actor, parents=[],
                           data=dict(time_ms=eid * 50, kind='knowledge_report', content=dict(record=record, new_copy=new, via='fixture'))))
        return eid

    acquisition(1, True)
    event('knowledge_recorded', 1, archive=1, record='route-cache', new_copy=True)
    event('knowledge_recorded', 1, archive=1, record='route-cache', new_copy=False)
    event('knowledge_taught', 1, target=2, record='route-cache', new_copy=True)
    acquisition(2, True)
    event('knowledge_consulted', 2, archive=1, record='route-cache', new_copy=False)
    latest = acquisition(2, False)
    event('identity_change', 2, reflections=[dict(source=latest, interpretation='A useful place to inspect')])
    event('skill_attempt', 2, action=dict(skill='move', destination=56), before=dict(position=84))
    event('resource_change', 2, location=56, food_delta=-1)
    event('death', 1)
    destruction_id = event('archive_destroyed', archive=1, copies_destroyed=1)
    event('death', 2)
    world = dict(initial=dict(players=[dict(id=1, health=100), dict(id=2, health=100)], archives=[dict(id=1)]),
                 players=[dict(id=actor, name=str(actor), health=0, knowledge=[dict(record=record, source=latest)]) for actor in [1, 2]],
                 archives=[dict(id=1, position=84, destroyed=True, revision=2, records=[])])
    result = analyze(world, events)
    assert not result['copy_audit_violations'], result['copy_audit_violations']
    assert result['new_copy_operations']['knowledge_recorded'] == 1
    assert result['repeat_copy_operations']['knowledge_recorded'] == 1
    assert result['repeat_copy_operations']['knowledge_consulted'] == 1
    assert len(result['acquisitions']) == 3 and len(result['accepted_citations']) == 1
    assert len(result['later_action_candidates']) == 2
    assert result['later_action_candidates'][1]['citations'][0]['source'] == latest
    assert result['record_location_summary'][1]['collected_after_acquisition'] == 1
    destroyed = next(x for x in result['copy_timeline'] if x['event'] == destruction_id)
    assert destroyed['records']['route-cache']['living_carriers'] == [2]
    assert result['final_availability']['route-cache']['living_carriers'] == []
    assert result['final_availability']['route-cache']['dead_holders'] == [1, 2]
    assert result['record_location_evidence'][0]['records'][0]['prior_acquisition'] == 5
    assert result['players'][0]['holdings'][0]['interpreted_source'] is None
    world['players'][1]['knowledge'][0]['interpreted_source'] = latest
    assert analyze(world, events)['players'][1]['holdings'][0]['interpreted_source'] == latest
    events[2]['data']['new_copy'] = True
    assert analyze(world, events)['copy_audit_violations'], 'duplicate claims must remain visible'
    print('Knowledge evidence fixture passed: duplicate/repeat discrimination, surviving carriers after archive loss, '
          'death unavailability, final-state reconciliation, accepted citation and later action references.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.output:
        summarize(args.output)
    else:
        parser.error('provide a completed run directory or --self-test')
