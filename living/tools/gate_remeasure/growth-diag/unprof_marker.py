import json,sys
from pathlib import Path
sys.path.insert(0,'analysis')
import marker_steps as ms
run=Path(sys.argv[1]); idle=float(sys.argv[2])
prof=[json.loads(l) for l in open(run/'prof.jsonl')]
P=[(r['on_t'],r['off_t']) for r in prof if r.get('tag')=='prof']
res=json.loads((run/'v0'/'result.json').read_text()); t0,t1=res['window']['t0'],res['window']['t1']
lines=[(int(f[1]),int(f[2])) for f in (l.strip().split(',') for l in open(run/'ticks-watch.csv')) if len(f)==4 and f[0]=='m']
# unprofiled pieces: from off_t+2 s to the next on_t
pieces=[]
for i,(on,off) in enumerate(P):
    nxt=P[i+1][0] if i+1<len(P) else t1
    a,b=off+2,min(nxt,t1)
    if b>a: pieces.append((a,b))
first=(t0, P[0][0]) if P else (t0,t1)
pieces=[first]+pieces
out=[]
for blk in range(6):
    ba,bb=t0+blk*300,t0+(blk+1)*300
    iv=[];n=0;secs=0
    for a,b in pieces:
        a2,b2=max(a,ba),min(b,bb)
        if b2-a2<5: continue
        x,k=ms.intervals(lines,a2*1e6,b2*1e6); iv+=x; n+=k; secs+=b2-a2
    s=ms.summary(iv,round(n/secs,2),n,idle)
    out.append((blk*5, s['ticks_per_s'], s['p99_ms'], s['over25_pct'], round(secs)))
print(json.dumps(out))
