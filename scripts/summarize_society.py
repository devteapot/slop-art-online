#!/usr/bin/env python3
"""Summarize social effects and validate conservation from recorded authority events."""
import argparse
import collections
import hashlib
import json
from pathlib import Path

def summarize(out):
    pilot=json.loads((out/'pilot.json').read_text());run=out/pilot['run']
    if pilot['phase']!='completed':raise ValueError('Social conservation analysis requires a completed experiment')
    source=run/('final-snapshot.json' if (run/'final-snapshot.json').exists() else 'snapshot.json')
    record=json.loads(source.read_text());w,events=record['world'],record['events'];index={e['id']:e for e in events}
    counts=lambda xs:dict(collections.Counter(xs))
    rows=[]
    for p in w['players']:
        aid=p['id'];initial=next(a for a in w['initial']['players'] if a['id']==aid);own=[e for e in events if e.get('actor')==aid]
        completed=[e for e in own if e['kind']=='skill_result' and e['data'].get('status')=='completed']
        incoming=[e for e in events if e['kind']=='food_transfer' and e['data']['target']==aid]
        donated=[e for e in own if e['kind']=='food_transfer']
        deposits=[e for e in own if e['kind']=='resource_change' and e['data'].get('nature')=='deposit']
        gathering=[e for e in own if e['kind']=='resource_change' and e['data'].get('food_delta',0)<0]
        meals=[e for e in completed if e['data']['skill']=='eat']
        damage=[e for e in own if e['kind']=='damage']
        deaths=[e for e in own if e['kind']=='death']
        learning=[e for e in own if e['kind']=='identity_change' and 'reflections' in e['data']]
        heard=[e for e in own if e['kind']=='perception' and e['data']['kind']=='speech']
        rows.append(dict(actor=aid,name=p['name'],motive=p['motive'],current_goal=p.get('current_goal'),health=p['health'],alive=p['health']>0,
            initial_food=initial['food'],final_food=p['food'],position=p['position'],gathered=-sum(e['data']['food_delta'] for e in gathering),
            eaten=len(meals),deposited=sum(e['data']['food_delta'] for e in deposits),given=sum(e['data']['amount'] for e in donated),
            received=sum(e['data']['amount'] for e in incoming),shelter_contributed=sum(e['data']['amount'] for e in own if e['kind']=='shelter_contribution'),
            visited_food_sites=sorted({e['data']['location'] for e in own if e['kind']=='perception' and e['data']['kind']=='site' and e['data']['content'].get('food',0)>0}),
            spoken=sum(e['kind']=='speech' for e in own),heard=len(heard),accepted_learning=len(learning),
            learning_from_speech=[dict(event=e['id'],source=r['source'],interpretation=r['interpretation']) for e in learning for r in e['data']['reflections'] if r['source'] in {h['id'] for h in heard}],
            damage_by_nature=counts(e['data'].get('cause_kind','unknown') for e in damage),
            death_seconds=deaths[0]['data']['time_ms']/1000 if deaths else None,
            completed_skills=counts(str(e['data']['skill']) for e in completed)))
    initial_food=sum(a['food'] for a in w['initial']['players'])+sum(s['food'] for s in w['initial']['sites'])
    final_food=sum(a['food'] for a in w['players'])+sum(s['food'] for s in w['sites'])
    meals=sum(p['eaten'] for p in rows)
    production=[e for e in events if e['kind']=='resource_produced']
    produced=sum(e['data']['food_delta'] for e in production)
    site_flows=[]
    for site in w['sites']:
        location=site['position']
        changes=[e for e in events if e['kind'] in ('resource_change','resource_produced') and e['data']['location']==location]
        actors=[]
        for p in rows:
            own=[e for e in changes if e['kind']=='resource_change' and e.get('actor')==p['actor']]
            gathered=-sum(min(0,e['data']['food_delta']) for e in own)
            deposited=sum(max(0,e['data']['food_delta']) for e in own)
            if gathered or deposited:
                actors.append(dict(actor=p['actor'],name=p['name'],gathered=gathered,deposited=deposited,
                    net_delivered=deposited-gathered))
        initial=next(s['food'] for s in w['initial']['sites'] if s['position']==location)
        running=collections.Counter()
        supplied_collection=0
        local_produced=0
        for event in changes:
            if event['kind']=='resource_produced':
                local_produced+=event['data']['food_delta']
                continue
            running[event['actor']]+=event['data']['food_delta']
            supplied_collection=max(supplied_collection,sum(max(0,-net) for net in running.values())-initial-local_produced)
        site_flows.append(dict(location=location,initial_food=initial,produced=local_produced,final_food=site['food'],actors=actors,
            net_providers=[p['actor'] for p in actors if p['net_delivered']>0],
            net_collectors=[p['actor'] for p in actors if p['net_delivered']<0],
            externally_supplied_collection_lower_bound=max(0,supplied_collection)))
    violations=[]
    if final_food+meals!=initial_food+produced:violations.append(f'Food accounting failed: initial {initial_food} + produced {produced} != final {final_food} + eaten {meals}')
    calls=[]
    for file in list((run/'reasoning').rglob('harness-*.json'))+list((run/'live-inference').rglob('external.json')):
        j=json.loads(file.read_text());reply=j.get('reply') or {};context=j['participant_context'];usage=reply.get('usage') or {}
        proposed_sources=[]
        try:
            proposal=json.loads(reply.get('raw_output',''));allowed={e['source'] for e in context['experiences']}
            for op in proposal['operations']:
                if op['op']=='reflect':
                    for r in op['reflections']:proposed_sources.append(dict(source=r['source'],supplied=r['source'] in allowed,cursor_matches=op['observed_cursor']==context['latest_cursor']))
        except (ValueError,KeyError,TypeError):pass
        calls.append(dict(actor=context['actor'],role=j.get('responsibility',j.get('role')),planned_role=j.get('planned_responsibility'),
            phase=j['phase'],error=j.get('error'),provider_error=reply.get('error'),status=reply.get('status'),
            total_tokens=usage.get('total_tokens',0),prompt_tokens=usage.get('prompt_tokens',0),completion_tokens=usage.get('completion_tokens',0),
            atomic_read=context.get('evidence_lease',{}).get('atomic',False),proposed_sources=proposed_sources,
            supplied_feedback='controller_feedback' in context,execution_failure_notice='execution_feedback' in context,
            journal=str(file.relative_to(out))))
    result=dict(run=pilot['run'],phase=pilot['phase'],seconds=w['timing']['time_ms']/1000,updates=w['timing']['updates'],players=rows,
        sites=w['sites'],site_flows=site_flows,food_sources=w['initial'].get('food_sources',[]),weather=w['initial'].get('weather'),initial_food=initial_food,produced=produced,final_food=final_food,eaten=meals,
        conservation_violations=violations,model_calls=len(calls),reported_tokens=sum(c['total_tokens'] for c in calls),calls=calls,
        rejections=counts(e['data'].get('error','unknown') for e in events if e['kind']=='participant_rejected'),
        social_events=[dict(id=e['id'],actor=e.get('actor'),kind=e['kind'],data=e['data']) for e in events if e['kind'] in ('food_transfer','shelter_contribution') or e['kind']=='resource_change' and e['data'].get('nature')=='deposit'],
        source=str(source.relative_to(out)),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        note='No automatic society pass: inspect actual speech-to-choice links, who benefits, sustained provision and fresh-repeat outcomes. Food held by dead actors remains conserved but unavailable.')
    (out/'SOCIETY_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['run','seconds','model_calls','reported_tokens','conservation_violations','rejections']},indent=2))
    for p in rows:print(p['name'],{k:p[k] for k in ['health','gathered','eaten','deposited','given','received','shelter_contributed','accepted_learning']})
    if violations:raise SystemExit('Authority conservation check failed')
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);summarize(p.parse_args().output.resolve())
