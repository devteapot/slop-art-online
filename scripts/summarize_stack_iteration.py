#!/usr/bin/env python3
"""Read-only comparison of scoped-render/clock experiments and retained failures."""
import argparse
import json
from pathlib import Path
from summarize_controller_boundary import summarize
from summarize_performance_baseline import analyze, distribution
from summarize_native_scale import parse_metrics, total


def read(path):
    return json.loads(path.read_text())


def frame_summary(path):
    frames=read(path/'browser-frames.json')
    while isinstance(frames,str): frames=json.loads(frames)
    window=read(path/'workload-window.json')
    intervals=[gap for wall,gap in frames['times']
        if window['start_wall_ms']<=wall<=window['pause_sent_wall_ms']]
    return dict(count=len(intervals),mean_hz=len(intervals)*1000/sum(intervals) if intervals else None,
        gap_ms=distribution(intervals),
        fraction_within_16_7ms=sum(v<=16.7+1e-6 for v in intervals)/len(intervals) if intervals else None,
        gaps_over_50ms=sum(v>50 for v in intervals),
        scope='rAF callback gaps in declared workload window; not GPU presentation or input-to-photon')


def histogram_bounds(first,last,name,**labels):
    limits=sorted({actual['le'] for n,actual,_ in last
        if n==name+'_bucket' and all(actual.get(k)==v for k,v in labels.items())},key=float)
    buckets=[(float(limit),total(last,name+'_bucket',**labels,le=limit)
        -total(first,name+'_bucket',**labels,le=limit)) for limit in limits]
    count=total(last,name+'_count',**labels)-total(first,name+'_count',**labels)
    if not count:return None
    # Report enclosing histogram buckets, never pretend these are raw samples.
    result=dict(count=count)
    for p in [.5,.95,.99]:
        previous=0
        for limit,cumulative in buckets:
            if cumulative>=p*count:
                result[f'p{int(p*100)}_bucket_ms']=[previous*1000,limit*1000 if limit!=float('inf') else None]
                break
            previous=limit
    return result


def comparison(path):
    if (path/'workload-caveats.json').exists():
        caveats=read(path/'workload-caveats.json')
        if caveats.get('excluded_from_browser_comparisons'):
            return dict(excluded=True,caveats=caveats)
    if (path/'browser-result.json').exists() and not read(path/'browser-result.json')['ok']:
        return dict(excluded=True,browser=read(path/'browser-result.json'))
    if not (path/'final-world.json').exists():
        return dict(excluded=True,reason='No committed final world; see original setup/runner errors',
            runner=read(path/'runner-result.json') if (path/'runner-result.json').exists() else None)
    resources=summarize(path)
    outcome=analyze(path)
    result=dict(resources=resources,outcomes=outcome)
    result['outcomes'].pop('causal_outcomes',None)
    if (path/'browser-frames.json').exists():
        result['browser']=frame_summary(path)
        resources['browser_observer_connections']=1
        resources['observer_connections']=resources.get('observer_connections',0)+1
        resources['limitations']+=' Includes one separate Bevy browser observer; its process CPU/RSS and GPU costs are not in the backend process sums.'
    if not read(path/'result.json')['ok']:return result
    deadline=outcome.get('deadline-state',[{}])[0]
    slots=deadline.get('wakes',0)+deadline.get('missed_slots',0)
    result['deadline_slots']=dict(wakes=deadline.get('wakes'),missed=deadline.get('missed_slots'),
        missed_fraction=deadline.get('missed_slots',0)/slots if slots else None,
        scope='durable counters captured after pause; include setup/cleanup, not an accepted per-actor combat cadence')
    render_names=['sim_my_render_snapshot','sim_my_render_header','sim_my_render_actors',
        'sim_my_render_bodies','sim_my_render_sites','sim_my_render_scene']
    views=resources['services']['world']['views']
    result['render_view_total_ms']=sum(views.get(name,{}).get('total_ms',0) for name in render_names)
    result['full_owner_view_calls']=views.get('sim_run',{}).get('calls',0)
    result['backend_cpu_seconds']=sum(r['active_cpu_seconds'] for r in resources['processes'].values())
    result['world_outgoing_wire_bytes']=resources['services']['world']['network_byte_counters'].get('spacetime_websocket_sent_msg_size_bytes_sum')
    result['retained_growth']={}
    for service,measurements in resources['services'].items():
        endpoints=[parse_metrics(path/service/'metrics'/name) for name in measurements['metric_boundaries']]
        wal=[total(metrics,'spacetime_message_log_size_bytes') for metrics in endpoints]
        rows=[sum(value for name,labels,value in metrics if name=='spacetime_data_size_table_num_rows'
            and not labels['table_name'].startswith('st_')) for metrics in endpoints]
        result['retained_growth'][service]=dict(wal_start_bytes=wal[0],wal_end_bytes=wal[1],
            wal_change_bytes=wal[1]-wal[0],table_rows_start=rows[0],table_rows_end=rows[1],
            table_rows_change=rows[1]-rows[0],
            retention_gauges_changed=wal[0]!=wal[1] or rows[0]!=rows[1],
            scope='nearest sampled active-window endpoints; retained WAL is not cumulative writes; '
                'gauge refresh timestamps are unavailable, so unchanged gauges do not establish zero storage growth')
    first,last=[parse_metrics(path/'world/metrics'/name) for name in resources['services']['world']['metric_boundaries']]
    result['deadline_execution_with_queries_histogram']=histogram_bounds(first,last,'spacetime_reducer_plus_query_duration_sec',reducer='sim_deadline_pulse')
    result['scheduled_queue_histogram']=histogram_bounds(first,last,'spacetime_reducer_wait_time_sec',reducer='scheduled reducer')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directories',nargs='+',type=Path)
    args=parser.parse_args()
    for directory in args.directories:
        result=comparison(directory)
        (directory/'stack-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(run=directory.name,**{k:v for k,v in result.items() if k not in ['outcomes','resources']})))
