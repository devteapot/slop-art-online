#!/usr/bin/env python3
"""Read-only analysis of short-run baseline artifacts and causal input outcomes."""
import argparse
from collections import Counter
import json
from pathlib import Path


def distribution(values):
    values=sorted(values)
    if not values:return None
    def at(p):return values[max(0,min(len(values)-1,__import__('math').ceil(p*len(values))-1))]
    return dict(count=len(values),p50=at(.5),p95=at(.95),p99=at(.99),maximum=values[-1])


def sql_rows(path):
    table=json.loads(path.read_text())[0]
    return [dict(zip([f['name']['some'] for f in table['schema']['elements']],row)) for row in table['rows']]


def analyze(root):
    result={}
    workload_path=root/'result.json'
    if workload_path.exists():
        workload=json.loads(workload_path.read_text())
        result['workload_ok']=workload.get('ok')
        result['workload_error']=workload.get('error')
    result['capture_scope']='Client capture includes in-flight completion until probe cleanup. Failed windows are diagnostic only; never accepted latency or cadence.'
    for name in ['physical-clock-state.json','deadline-state.json']:
        if (root/name).exists():result[name.removesuffix('.json')]=sql_rows(root/name)
    live_path=root/'live-client-result.json'
    if not live_path.exists():return result
    live=json.loads(live_path.read_text())
    terminal={}
    for frame in live.get('action_frames',[]):
        action=frame.get('action') or {}
        if action.get('status') in ['success','failure']:
            terminal.setdefault(action['request_id'],frame)
    inputs=live.get('human_inputs',[])
    result['input_completion_ms']=distribution([r['latency_us']/1000 for r in inputs])
    result['input_to_terminal_outcome_ms']=distribution([terminal[r['request_id']]['wall_ms']-r['sent_wall_ms']
        for r in inputs if r.get('request_id') in terminal])
    result['outcome_ms_by_skill']={skill:distribution([
        terminal[r['request_id']]['wall_ms']-r['sent_wall_ms'] for r in inputs
        if r['action']['skill']==skill and r.get('request_id') in terminal])
        for skill in sorted({r['action']['skill'] for r in inputs})}
    result['input_to_reducer_invocation_ms']=distribution([r['server_reducer_invoked_us']/1000-r['sent_wall_ms']
        for r in inputs if r.get('server_reducer_invoked_us') is not None])
    result['reducer_invocation_to_outcome_received_ms']=distribution([terminal[r['request_id']]['wall_ms']-r['server_reducer_invoked_us']/1000
        for r in inputs if r.get('request_id') in terminal and r.get('server_reducer_invoked_us') is not None])
    result['timing_boundaries']='SDK send, server-provided reducer invocation timestamp, and client callback/terminal frame receipt. Same-host clocks. Invocation is not network ingress; terminal receipt is after commit and includes downstream delivery. Exact server ingress-to-commit remains uninstrumented.'
    result['input_counts']=dict(sent=live['human_inputs_sent'],callbacks=len(inputs),
        missing_callbacks=live['pending_human_callbacks'],receipts=len(live['human_receipts']),
        rejected=sum(not r['ok'] for r in live['human_receipts']),
        failed_callbacks=sum(not r['reducer_commit_ok'] for r in inputs),
        terminal_outcomes=len(terminal),missing_terminal=sum(r.get('request_id') not in terminal for r in inputs))
    result['input_counts']['sent_without_terminal']=live['human_inputs_sent']-len(terminal)
    result['render_update_observations']=[]
    for render in live.get('render_frames',[]):
        updates={}
        for frame in render['frames']:
            if isinstance(frame.get('updates'),int):updates.setdefault(frame['updates'],frame)
        ordered=sorted(updates.values(),key=lambda f:f['updates'])
        sim=[b['time_ms']-a['time_ms'] for a,b in zip(ordered,ordered[1:])]
        wall=[b['wall_ms']-a['wall_ms'] for a,b in zip(ordered,ordered[1:])]
        result['render_update_observations'].append(dict(kind=render['kind'],unique_updates=len(ordered),
            missing_update_ids=0 if not ordered else ordered[-1]['updates']-ordered[0]['updates']+1-len(ordered),
            physical_interval_ms=distribution(sim),delivery_interval_ms=distribution(wall),
            physical_intervals_over_60hz_budget=sum(delta>1000/60 for delta in sim),
            note='Combined action/world physical updates visible to this client; not a per-actor combat-step rate or rendered FPS.'))
    audit=root/'final-audit.jsonl'
    if audit.exists():
        requested={r.get('request_id') for r in inputs}
        commands={};attempts={};outcomes={};kinds=Counter();skills=Counter();deaths=[];attack_times=[]
        for line in audit.open():
            e=json.loads(line);kinds[e['kind']]+=1
            if e['kind']=='participant_command' and e['data'].get('request_id') in requested:
                commands[e['id']]=e['data']['request_id']
            if e['kind']=='skill_attempt':
                skill=e['data']['action']['skill'];skills[skill]+=1
                if skill=='attack':attack_times.append(e['data']['time_ms'])
                for parent in e['parents']:
                    if parent in commands:attempts[e['id']]=commands[parent]
            if e['kind']=='skill_result':
                for parent in e['parents']:
                    if parent in attempts:outcomes.setdefault(attempts[parent],e)
            if e['kind']=='death':deaths.append(dict(actor=e['actor'],time_ms=e['data']['time_ms']))
        matched=[]
        for request_id,frame in terminal.items():
            event=outcomes.get(request_id)
            after=(event or {}).get('data',{}).get('after',{})
            matched.append(dict(request_id=request_id,terminal_status=frame['action']['status'],
                result_event=(event or {}).get('id'),result_status=(event or {}).get('data',{}).get('status'),
                outcome_position=after.get('position'),received_position=frame['position'],
                position_matches=after.get('position')==frame['position'] if 'position' in after else None))
        result['causal_outcomes']=matched
        result['audit']=dict(event_kinds=dict(kinds),skill_attempts=dict(skills),deaths=deaths,
            attack_time_range_ms=[min(attack_times),max(attack_times)] if attack_times else None,
            missing_result_for_terminal=sum(x['result_event'] is None for x in matched))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    result=analyze(args.directory)
    (args.directory/'baseline-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['causal_outcomes','audit']},indent=2))
