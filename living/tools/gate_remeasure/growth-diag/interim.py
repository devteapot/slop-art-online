import json,re,collections,sys
P=sys.argv[1]
recs=[json.loads(l) for l in open(P)]
def parse(r):
    return {l.rsplit(' ',1)[0]:float(l.rsplit(' ',1)[1]) for l in r['metrics']}
def by(d,metric,label):
    o=collections.Counter()
    for k,v in d.items():
        if k.startswith(metric+'{'):
            m=re.search(label+r'="([^"]*)"',k); o[m.group(1) if m else '']+=v
    return o
S={(r['tag'],r['k']):r for r in recs if r.get('tag') in ('S0','S1','S2')}
T=['character','structure','line_seen','skill_use','familiar','sex_seen','experience','rot']
print('k ticks/s db_ms/s tick_wasm join_wasm housekeep', ' '.join(T), 'cgroupGB jemallocMB')
for k in range(1,40):
    lo,hi=S.get(('S2',k-1)),S.get(('S1',k))
    if not(lo and hi): break
    dt=hi['t']-lo['t']; pl,ph=parse(lo),parse(hi)
    thr=sum((hi['threads'][n]-lo['threads'].get(n,0))*10/dt for n in hi['threads'] if n.startswith('wasm'))
    c=by(ph,'spacetime_reducer_plus_query_duration_sec_count','reducer')['tick']-by(pl,'spacetime_reducer_plus_query_duration_sec_count','reducer')['tick']
    w=by(ph,'reducer_wasm_time_usec','reducer'); wl=by(pl,'reducer_wasm_time_usec','reducer')
    rows=by(ph,'spacetime_data_size_table_num_rows','table_name')
    jm=sum(v for n,v in ph.items() if n.startswith('jemalloc_allocated'))
    print(k, '%.2f'%(c/dt), '%.0f'%thr, '%.0f'%((w['tick']-wl['tick'])/1e3/dt), '%.1f'%((w['join']-wl['join'])/1e3/dt), '%.1f'%((w['housekeeping']-wl['housekeeping'])/1e3/dt), ' '.join(str(int(rows[t])) for t in T), '%.2f'%(hi.get('cgroup_bytes',0)/2**30), '%.0f'%(jm/2**20))
