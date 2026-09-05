#!/usr/bin/env python3
"""Summarize recorded authority/inference evidence; never advance or approximate a world."""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def summarize(out):
    pilot=json.loads((out/'pilot.json').read_text())
    run=out/pilot['run']
    snapshot_path=run/'final-snapshot.json' if (run/'final-snapshot.json').is_file() else run/'snapshot.json'
    snapshot=json.loads(snapshot_path.read_text())
    world,events=snapshot['world'],snapshot['events']
    arenas=world['initial']['arenas'];width=world['initial']['map']['width']
    arena_by_actor={actor:arena for arena in arenas for actor in arena['actors']}
    def contains(arena,cell):
        b=arena['bounds'];x,y=cell%width,cell//width
        return b['x']<=x<b['x']+b['width'] and b['y']<=y<b['y']+b['height']
    violations=[]
    calls=collections.defaultdict(list)
    for actor,arena in arena_by_actor.items():
        files=list((run/'reasoning'/f'actor-{actor}').glob('harness-*.json'))+list((run/'live-inference'/f'actor-{actor}').rglob('external.json'))
        config=json.loads((out/f'actor-{actor}-config.json').read_text())
        expected=config['backend']['reasoning_effort']
        for file in files:
            record=json.loads(file.read_text());context=record['participant_context']['context']
            if record['request'].get('reasoning_effort')!=expected:violations.append(f'actor {actor}: wrong requested effort')
            if context['map'].get('bounds')!=arena['bounds'] or 'arenas' in context:violations.append(f'actor {actor}: incorrect context scope')
            for cell in context['map']['blocked']:
                if not contains(arena,cell):violations.append(f'actor {actor}: terrain leak')
            player=context['player']
            for memory in player['memories']:
                if not contains(arena,memory['location']):violations.append(f'actor {actor}: memory outside arena')
                if memory.get('from') is not None and memory['from'] not in arena['actors']:violations.append(f'actor {actor}: cross-arena peer')
            reply=record.get('reply') or {};usage=reply.get('usage') or {}
            calls[actor].append(dict(phase=record['phase'],responsibility=record.get('responsibility',record.get('role')),requested_effort=record['request'].get('reasoning_effort'),
                                     status=reply.get('status'),error=record.get('error'),provider_error=reply.get('error'),
                                     completion_tokens=usage.get('completion_tokens'),reasoning_tokens=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens')))
    for player in world['players']:
        arena=arena_by_actor[player['id']]
        if not contains(arena,player['position']):violations.append(f"actor {player['id']}: final position outside arena")
    for event in events:
        actor=event.get('actor')
        if actor in arena_by_actor and event['kind']=='skill_progress' and isinstance(event['data'].get('position'),int):
            if not contains(arena_by_actor[actor],event['data']['position']):violations.append(f'actor {actor}: movement outside arena')
    cells=[]
    for arena in arenas:
        players=[]
        for actor in arena['actors']:
            player=next(p for p in world['players'] if p['id']==actor)
            own=[e for e in events if e.get('actor')==actor]
            players.append(dict(actor=actor,name=player['name'],runtime=arena['controllers'][str(actor)],
                health=player['health'],food=player['food'],position=player['position'],alive=player['health']>0,
                event_counts=dict(collections.Counter(e['kind'] for e in own)),calls=calls[actor]))
        cells.append(dict(id=arena['id'],label=arena['label'],players=players))
    result=dict(run=pilot['run'],phase=pilot['phase'],seconds=world['timing']['time_ms']/1000,
                updates=world['timing']['updates'],rules=world['version'],arenas=cells,
                total_calls=sum(map(len,calls.values())),scope_violations=violations,
                engine_errors=[dict(id=e['id'],kind=e['kind'],data=e['data']) for e in events if e['kind'] in ('script_error','script_tick_failed')],
                limitations='One sample per cell; requested effort only; distinct runtime prompts/personas; incomplete calls retain started journals and supervisor cancellation evidence.',
                artifact_hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [snapshot_path,*out.glob('actor-*-config.json')]})
    (out/'LIVE_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['run','phase','seconds','updates','total_calls','scope_violations','engine_errors']},indent=2))
    for cell in cells:print(cell['label'],[(p['name'],p['health'],len(p['calls'])) for p in cell['players']])
    if violations or result['engine_errors']:raise SystemExit('Evidence checks failed; inspect LIVE_RESULT.json')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);summarize(parser.parse_args().output)
