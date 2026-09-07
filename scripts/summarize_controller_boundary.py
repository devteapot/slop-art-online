#!/usr/bin/env python3
"""Summarize frozen dual-service metrics; never contacts or modifies a database."""
import argparse
import json
import os
from pathlib import Path
from summarize_native_scale import parse_metrics,total,percentile

def summarize(path):
    read=lambda name:json.loads((path/name).read_text())
    result=read('result.json');world=read('final-world.json')
    if not result.get('ok'):
        window=path/'workload-window.json'
        return dict(ok=False,error=result.get('error'),population=len(world['players']),
            alive=sum(p['health']>0 for p in world['players']),
            final_updates=world['timing']['updates'],
            workload_window=json.loads(window.read_text()) if window.exists() else None,
            limitations='Failed workload; final export includes cleanup. No accepted cadence is computed. Raw metrics and process/controller samples are retained.')
    work=result['workload']
    samples=[json.loads(line) for line in (path/'process-samples.jsonl').read_text().splitlines()]
    start=work.get('start_wall_ms',samples[0]['wall_ms'])
    end=work.get('pause_sent_wall_ms',samples[-1]['wall_ms'])
    active=[s for s in samples if start<=s['wall_ms']<=end]
    summary=dict(population=len(world['players']),wall_ms=work['elapsed_ms'],simulated_ms=world['timing']['time_ms'],
        updates=world['timing']['updates'],updates_per_second=world['timing']['updates']*1000/work['elapsed_ms'],
        alive=sum(p['health']>0 for p in world['players']),model_calls=0,observer_connections=work.get('observer_connections',0),
        human_connections=work.get('human_connections',0),
        controller_fault_samples=sum('error' in s for line in (path/'controller-samples.jsonl').read_text().splitlines() for s in json.loads(line)['states']),
        services={},processes={})
    for kind in ['world','controller','relay']:
        summary['processes'][kind]=dict(peak_rss_bytes=max(s[kind]['rss_bytes'] for s in samples),
            active_cpu_seconds=(active[-1][kind]['cpu_ticks']-active[0][kind]['cpu_ticks'])/os.sysconf('SC_CLK_TCK'),
            peak_swap_bytes=max(s[kind]['swap_bytes'] for s in samples))
    for kind in ['world','controller']:
        files=sorted((path/kind/'metrics').glob('*.prom'))
        nearest=lambda at:min(files,key=lambda f:abs(int(f.stem)-at))
        first_file,last_file=nearest(start),nearest(end)
        first,last=parse_metrics(first_file),parse_metrics(last_file)
        delta=lambda name,**labels:total(last,name,**labels)-total(first,name,**labels)
        reducers={}
        for r in ['sim_deadline_pulse','sim_world_pulse','sim_audit_maintenance','sim_participant_command','sim_client_intent','sim_select_inspector','sim_dispatch_controller_action','sim_dispatch_controller_action_after','sim_set_controller_delivery_cursor','brain_tick','brain_ingest','brain_ack','brain_claim']:
            count=delta('spacetime_reducer_plus_query_duration_sec_count',reducer=r)
            if count:
                reducers[r]=dict(count=count,mean_execution_and_query_ms=1000*delta('spacetime_reducer_plus_query_duration_sec_sum',reducer=r)/count,
                    wasm_cpu_ms=delta('reducer_wasm_time_usec',reducer=r)/1000)
        views={}
        for view in sorted({labels['view'] for n,labels,_ in last if n=='view_calls'}):
            count=delta('view_calls',view=view)
            if count:
                views[view]=dict(calls=count,
                    wasm_ms=delta('view_call_time_usec',view=view)/1000,
                    total_ms=delta('view_total_time_usec',view=view)/1000)
        gauges=['spacetime_worker_wasm_memory_bytes' ,'page_pool_resident_bytes','bsatn_rlb_pool_resident_bytes','jemalloc_allocated_bytes','jemalloc_resident_bytes']
        peaks={g:0 for g in gauges}
        for file in files:
            if start<=int(file.stem)<=end:
                metrics=parse_metrics(file)
                for g in gauges:peaks[g]=max(peaks[g],total(metrics,g))
        stop=path/kind/'stop.json'
        if not stop.exists():stop=path/kind/'cleanup-stop.json'
        summary['services'][kind]=dict(reducers=reducers,views=views,scheduled_queue_seconds=delta('spacetime_reducer_wait_time_sec_sum',reducer='scheduled reducer'),
            retained_wal_at_end_bytes=total(last,'spacetime_message_log_size_bytes'),active_resource_peaks=peaks,
            table_rows={labels['table_name']:v for n,labels,v in last if n=='spacetime_data_size_table_num_rows' and not labels['table_name'].startswith('st_')},
            network_byte_counters={n:delta(n) for n in sorted({n for n,_,_ in last if 'bytes' in n and ('websocket' in n or 'subscription' in n or 'network' in n)})},
            metric_boundaries=[first_file.name,last_file.name],shutdown_exit_code=json.loads(stop.read_text())['ExitCode'])
    summary['limitations']='One finite crowded seeded-policy trial; no inference. Human input is automated when enabled; browser frame pacing is separate. Per-process peaks include enrollment. Metrics/CPU boundaries approximate nearest 1s samples. Retained WAL is not cumulative writes; WASM gauge is not summed across worker instances.'
    browser=path/'browser/workload.json'
    if browser.exists():
        summary['browser_workload']=json.loads(browser.read_text())
        summary['observer_connections']+=summary['browser_workload']['observer_connections']
        pacing=path/'browser/frame-summary.json'
        if pacing.exists():summary['browser_frame_pacing']=json.loads(pacing.read_text())
        summary['limitations']+=' Includes the additional browser observer and renderer/identity switch described in browser_workload; this is not a steady single-observer comparison. SDK application byte counters exclude that browser; service wire metrics include it.'
    live=path/'live-client-result.json'
    if live.exists():
        value=json.loads(live.read_text());latencies=[r['latency_us']/1000 for r in value['human_inputs']]
        summary['live_clients']=dict(renderers=value['renderers'],human_inputs_sent=value['human_inputs_sent'],
            pending_callbacks=value['pending_human_callbacks'],failed_reducer_calls=sum(not r['reducer_commit_ok'] for r in value['human_inputs']),
            receipt_count=len(value['human_receipts']),rejected_receipts=sum(not r['ok'] for r in value['human_receipts']),
            input_to_reducer_ms=None if not latencies else dict(p50=percentile(latencies,.5),p95=percentile(latencies,.95),maximum=max(latencies)))
        if value.get('action_frames'):
            notices={}
            for frame in value['action_frames']:
                action=frame.get('action') or {}
                request_id=action.get('request_id')
                if request_id and (action.get('attempt') is not None or action.get('status') in ['success','failure']):
                    notices[request_id]=min(notices.get(request_id,frame['wall_ms']),frame['wall_ms'])
            timed=[notices[r['request_id']]-r['sent_wall_ms'] for r in value['human_inputs']
                if r.get('request_id') in notices and notices[r['request_id']]>=r['sent_wall_ms']]
            summary['live_clients']['input_to_execution_notice_ms']=None if not timed else dict(
                count=len(timed),p50=percentile(timed,.5),p95=percentile(timed,.95),maximum=max(timed))
            summary['live_clients']['inputs_without_execution_notice']=sum(r.get('request_id') is not None
                and r['request_id'] not in notices for r in value['human_inputs'])
            summary['live_clients']['execution_notice_definition']='SDK send to first scoped frame showing an attempt or success/failure for the exact request ID; includes local transport and delivery, not just reducer CPU.'
    physical=path/'physical-clock-state.json'
    if physical.exists():
        table=json.loads(physical.read_text())[0]
        names=[field['name']['some'] for field in table['schema']['elements']]
        summary['physical_clock']=[dict(zip(names,row)) for row in table['rows']]
        summary['limitations']+=' Physical updates combine action opportunities and due world maintenance; this is not a single whole-world tick rate. Clock counters include setup/cleanup.'
    audit=path/'audit-verification.json'
    if audit.exists():summary['audit_verification']=json.loads(audit.read_text())
    if 'start_wall_ms' not in work:summary['limitations']+=' Original probe lacked wall markers; metric/CPU window includes enrollment.'
    runner=path/'runner-result.json'
    if runner.exists():summary['runner_result']=json.loads(runner.read_text())
    recovery=path/'export-recovery.json'
    if recovery.exists():
        summary['export_recovery']=json.loads(recovery.read_text())
        summary['limitations']+=' Wrapper failed after the successful paused workload; final export was recovered separately. Resource metrics precede the recovery restart.'
    caveats=path/'workload-caveats.json'
    if caveats.exists():
        summary['workload_caveats']=json.loads(caveats.read_text())
        summary['limitations']+=' Additional workload caveats are recorded; see workload_caveats.'
    return summary

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path);args=parser.parse_args()
    value=summarize(args.directory);(args.directory/'summary.json').write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps({k:v for k,v in value.items() if k not in ['services']},indent=2))
