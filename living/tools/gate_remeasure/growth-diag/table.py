import json,sys
run=sys.argv[1]
S=json.load(open(f'{run}/spans.json'))['windows']; T={w['k']:w for w in json.load(open(f'{run}/ticks.json'))['windows']}
SP=['tick','tick.perception','sight.player_candidates','tick.wakes','wake.eval.calm','scene.sensed','brain.after','known.mark','noticed.structures','act.skill_ctx','check.ctx','act.complete','join.sweep','housekeeping']
TB=['character','structure','line_seen','skill_use','sex_seen','familiar']
print('| min | ticks/s (unprof.) | DB ms/s | tick p99 ms | '+' | '.join(SP)+' | '+' | '.join(TB)+' | jemalloc MB |')
print('|'+'---|'*(5+len(SP)+len(TB)))
for w in S:
    k=w['k']; t=T.get(k,{}); 
    thr=sum(v for n,v in w.get('threads_ms_per_s',{}).items() if n.startswith('wasm'))
    r=w.get('rows',{})
    print(f"| {w['min']:.0f} | {w.get('ticks_per_s','')} | {thr:.0f} | {t.get('tick_ms',{}).get('p99','')} | "+' | '.join(f"{w['spans_ms_per_s'].get(s,0):.1f}" for s in SP)+' | '+' | '.join(str(r.get(x,'')) for x in TB)+f" | {w.get('jemalloc_allocated',0)/2**20:.0f} |")
