#!/usr/bin/env python3
"""Summarize recorded authority/inference evidence; never advance or approximate a world."""
import argparse
import collections
import copy
import hashlib
import json
from pathlib import Path



def classify_execution_events(events):
    """Keep typed law denials visible without calling them engine failures."""
    active={};errors=[];denials=[]
    for event in sorted(events,key=lambda e:e['id']):
        data=event['data'];kind=event['kind']
        if kind=='law_activated':
            ref=data['reference'];scope=ref['scope']
            key='universal' if scope['kind']=='universal' else 'territory:'+scope['region']
            active[key]=dict(reference=ref,hooks=data.get('hooks',[]),activation=event['id'])
        if kind not in ('script_error','script_tick_failed'):continue
        entry=dict(id=event['id'],kind=kind,actor=event.get('actor'),data=data)
        installations=[r for r in active.values() if 'authorize_effect' in r['hooks']]
        if (kind=='script_error' and data.get('category')=='law_authorization_denied'
                and data.get('error') in ('active law denied effect','destination law denied effect')
                and data.get('effects_committed') is False and data.get('law_binding')
                and installations):
            entry['installed_authorization_evidence']=installations
            denials.append(entry)
        else:errors.append(entry)
    return errors,denials


def actor_layout(world, participants):
    """Resolve current membership while leaving the immutable scenario untouched."""
    initial = world['initial']
    scoped = bool(initial.get('arenas'))
    arenas = copy.deepcopy(initial.get('arenas') or [dict(id='world', label='Shared world', bounds=None, actors=[], controllers={})])
    by_id = {arena['id']: arena for arena in arenas}
    membership = {actor: arena['id'] for arena in arenas for actor in arena.get('actors', [])}
    membership.update({int(actor): arena for actor, arena in world.get('actor_arenas', {}).items()})
    roles = {int(actor): role for arena in arenas for actor, role in arena.get('controllers', {}).items()}
    roles.update({p['actor']: p['role'] for p in participants})
    for arena in arenas:
        arena['actors'] = []
        arena['controllers'] = {}
    actor_arenas, violations = {}, []
    for player in world['players']:
        actor = player['id']
        aid = membership.get(actor, 'world' if not scoped else None)
        if aid not in by_id:
            violations.append(f'actor {actor}: missing current arena membership')
            aid = 'unassigned'
            if aid not in by_id:
                unassigned = dict(id=aid, label='Actors with missing scope evidence', bounds=None, actors=[], controllers={})
                arenas.append(unassigned)
                by_id[aid] = unassigned
        arena = by_id[aid]
        arena['actors'].append(actor)
        arena['controllers'][str(actor)] = roles.get(actor, 'unassigned')
        actor_arenas[actor] = arena
    return arenas, actor_arenas, violations


def summarize(out):
    out = Path(out)
    pilot = json.loads((out / 'pilot.json').read_text())
    run = out / pilot['run']
    snapshot_path = run / ('final-snapshot.json' if (run / 'final-snapshot.json').is_file() else 'snapshot.json')
    snapshot = json.loads(snapshot_path.read_text())
    world, events = snapshot['world'], snapshot['events']
    participants_path = run / 'participants.json'
    participants = json.loads(participants_path.read_text()) if participants_path.exists() else []
    arenas, arena_by_actor, violations = actor_layout(world, participants)
    grid = world['initial'].get('map')

    def contains(arena, cell):
        if not isinstance(cell, int):
            return False
        if grid is None:
            return -10 <= cell <= 10
        width = grid['width']
        x, y = cell % width, cell // width
        b = arena.get('bounds')
        if b is None:
            return 0 <= x < width and 0 <= y < grid['height']
        return b['x'] <= x < b['x'] + b['width'] and b['y'] <= y < b['y'] + b['height']

    calls = collections.defaultdict(list)
    for actor, arena in arena_by_actor.items():
        files = list((run / 'reasoning' / f'actor-{actor}').glob('harness-*.json')) + list((run / 'live-inference' / f'actor-{actor}').rglob('external.json'))
        config_path = out / f'actor-{actor}-config.json'
        if not config_path.exists():
            config_path = run / f'actor-{actor}-config.json'
        config = json.loads(config_path.read_text()) if config_path.exists() else None
        expected = config['backend'].get('reasoning_effort') if config else None
        if files and config is None:
            violations.append(f'actor {actor}: model journals lack retained controller configuration')
        for file in files:
            record = json.loads(file.read_text())
            context = record['participant_context']['context']
            if record['request'].get('reasoning_effort') != expected:
                violations.append(f'actor {actor}: wrong requested effort')
            context_map = context.get('map') or {}
            if context_map.get('bounds') != arena.get('bounds') or 'arenas' in context:
                violations.append(f'actor {actor}: incorrect context scope')
            for cell in context_map.get('blocked', []):
                if not contains(arena, cell):
                    violations.append(f'actor {actor}: terrain leak')
            for memory in context['player']['memories']:
                if not contains(arena, memory['location']):
                    violations.append(f'actor {actor}: memory outside arena')
                if memory.get('from') is not None and memory['from'] not in arena['actors']:
                    violations.append(f'actor {actor}: cross-arena peer')
            reply = record.get('reply') or {}
            usage = reply.get('usage') or {}
            calls[actor].append(dict(phase=record['phase'], responsibility=record.get('responsibility', record.get('role')),
                                     requested_effort=record['request'].get('reasoning_effort'), status=reply.get('status'),
                                     error=record.get('error'), provider_error=reply.get('error'),
                                     completion_tokens=usage.get('completion_tokens'),
                                     reasoning_tokens=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens')))
    for player in world['players']:
        if not contains(arena_by_actor[player['id']], player['position']):
            violations.append(f"actor {player['id']}: final position outside arena")
    for event in events:
        actor = event.get('actor')
        if actor in arena_by_actor and event['kind'] == 'skill_progress' and isinstance(event['data'].get('position'), int):
            if not contains(arena_by_actor[actor], event['data']['position']):
                violations.append(f'actor {actor}: movement outside arena')
    births = {e['actor']: e for e in events if e['kind'] == 'actor_created'}
    cells = []
    for arena in arenas:
        players = []
        for actor in arena['actors']:
            player = next(p for p in world['players'] if p['id'] == actor)
            own = [e for e in events if e.get('actor') == actor]
            birth = births.get(actor)
            players.append(dict(actor=actor, name=player['name'], runtime=arena['controllers'][str(actor)],
                                health=player['health'], food=player['food'], position=player['position'], alive=player['health'] > 0,
                                created_event=birth['id'] if birth else None,
                                born_ms=birth['data'].get('born_ms', birth['data'].get('time_ms')) if birth else None,
                                event_counts=dict(collections.Counter(e['kind'] for e in own)), calls=calls[actor]))
        cells.append(dict(id=arena['id'], label=arena['label'], players=players))
    engine_errors,law_denials=classify_execution_events(events)
    result = dict(run=pilot['run'], phase=pilot['phase'], seconds=world['timing']['time_ms'] / 1000,
                  updates=world['timing']['updates'], rules=world['version'], arenas=cells,
                  initial_population=len(world['initial']['players']), created_population=len(births),
                  total_calls=sum(map(len, calls.values())), scope_violations=violations,
                  engine_errors=engine_errors,law_authorization_denials=law_denials,
                  limitations='One sample per cell; requested effort only; distinct runtime prompts/personas; incomplete calls retain started journals and supervisor cancellation evidence. Current actor membership includes authority-created identities; absent controllers are labeled unassigned.',
                  artifact_hashes={str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in [snapshot_path, *out.glob('actor-*-config.json'), *run.glob('actor-*-config.json')]})
    (out / 'LIVE_RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ['run', 'phase', 'seconds', 'updates', 'total_calls', 'scope_violations', 'engine_errors']}, indent=2))
    for cell in cells:
        print(cell['label'], [(p['name'], p['health'], len(p['calls'])) for p in cell['players']])
    if violations or result['engine_errors']:
        raise SystemExit('Evidence checks failed; inspect LIVE_RESULT.json')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    summarize(parser.parse_args().output)
