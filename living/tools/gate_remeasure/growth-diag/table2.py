import json,sys
run=sys.argv[1]; mins=[int(x) for x in sys.argv[2].split(',')] if len(sys.argv)>2 else None
S=json.load(open(f'{run}/spans.json'))['windows']; T={w['k']:w for w in json.load(open(f'{run}/ticks.json'))['windows']}
SP=[('tick','tick'),('sight.player_candidates','sight.player_candidates'),('scene.sensed','scene.sensed'),('tick.wakes','tick.wakes'),('brain.after','brain.after'),('known.mark','known.mark'),('noticed.structures','noticed.structures'),('act.skill_ctx','act.skill_ctx'),('check.ctx','check.ctx'),('join.sweep','join.sweep'),('housekeeping','housekeeping')]
TB=['structure','character','line_seen','skill_use','sex_seen']
print('| Min | Ticks/s | DB ms/s | Tick p99 ms | '+' | '.join(f'`{a}`' for a,_ in SP)+' | '+' | '.join(f'`{t}` rows' for t in TB)+' | jemalloc MB |')
print('|'+'---:|'*(4+len(SP)+len(TB)+1))
for w in S:
    k=w['k']
    if mins and k not in mins: continue
    if 'rows' not in w: continue
    t=T.get(k,{}); thr=sum(v for n,v in w.get('threads_ms_per_s',{}).items() if n.startswith('wasm')); r=w['rows']
    print(f"| {k} | {w.get('ticks_per_s')} | {thr:.0f} | {t.get('tick_ms',{}).get('p99','')} | "+' | '.join(f"{w['spans_ms_per_s'].get(s,0):.0f}" for s,_ in SP)+' | '+' | '.join(f"{r.get(x,0):,}" for x in TB)+f" | {w.get('jemalloc_allocated',0)/2**20:.0f} |")
