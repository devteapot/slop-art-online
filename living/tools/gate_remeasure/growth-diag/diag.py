import json,re,sys,tarfile,io,collections
run=sys.argv[1]; ks=[int(x) for x in sys.argv[2].split(',')]
prof=[json.loads(l) for l in open(f'{run}/prof.jsonl')]
wins={r['k']:(r['on_t']*1e6,r['off_t']*1e6) for r in prof if r.get('tag')=='prof'}
acc={k:collections.Counter() for k in ks}; n={k:0 for k in ks}
rx=re.compile(r'"ts":(\d+),.*"message":"diag: (\{.*\})"\}')
with tarfile.open(f'{run}/replica-module-logs.tar') as t:
  for m in t.getmembers():
    if not m.name.endswith('.log'): continue
    for l in io.TextIOWrapper(t.extractfile(m),encoding='utf-8',errors='replace'):
      if 'diag: ' not in l: continue
      mm=rx.search(l)
      if not mm: continue
      ts=int(mm.group(1))
      for k in ks:
        a,b=wins[k]
        if a<=ts<=b+1.5e6:
          d=json.loads(mm.group(2).replace('\\"','"')); acc[k].update(d); n[k]+=1
keys=set().union(*acc.values())
rows=sorted(keys,key=lambda s:-abs(acc[ks[-1]][s]/max(1,n[ks[-1]])-acc[ks[0]][s]/max(1,n[ks[0]])))
print('per second:', n)
for s in rows[:60]: print(f"{s:45s}", *[f"{acc[k][s]/max(1,n[k]):12.0f}" for k in ks])
