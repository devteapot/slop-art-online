#!/usr/bin/env python3
"""Why a battle's deliberate acts were refused (docs/FAST_LANE_FRAME.md §1), read only.

usage: battle_frame_refusals.py RUN_DIR OUT.json

RUN_DIR is a `battle_diag.py --real-minds --act-trace` run (journal/, journal/outcomes/
act_attempts.jsonl, combat-samples.jsonl.gz, measure-start-ms.txt). Minutes 2-8. For each act
with a target: its compile call (the journal entry whose prompt's "you" id is the actor), the
moment that prompt's scene was true (its listed distances fitted to the replayed body samples),
and the target at that moment, after the calls' own model time, and at submission."""
import json,sys,glob,gzip,bisect,re,collections,math,statistics as st
R=sys.argv[1]; SIGHT=11.0
t0=int(open(R+'/measure-start-ms.txt').read().split()[0]); W0,W1=t0+60_000*2, t0+60_000*8   # minutes 2-8 as the act-trial tables
S=[json.loads(l) for l in gzip.open(R+'/combat-samples.jsonl.gz','rt')]
ts=[s['at_ms'] for s in S]; B=[{b['id']:b for b in s['bodies']} for s in S]
def pos(i,t):
    k=max(0,bisect.bisect_right(ts,t)-1); b=B[k].get(i)
    if b is None: return None
    end=b['next_ms'] if b['next_ms']<1e18 else t
    dt=max(0,min(t,end)-b['t_ms'])/1000
    return (b['x']+b['vx']*dt,b['y']+b['vy']*dt)
def dist(a,b,t):
    pa,pb=pos(a,t),pos(b,t)
    return None if (pa is None or pb is None) else math.dist(pa,pb)
J=collections.defaultdict(list)
for f in glob.glob(R+'/journal/*.jsonl'):
    for l in open(f):
        r=json.loads(l)
        if r['purpose'] not in('deliberate','act_repair'): continue
        c=r['request']['messages'][-1]['content']
        m=re.search(r'"you":\{.*?"id":(\d+)',c)
        if m: J[int(m.group(1))].append(r)
for v in J.values(): v.sort(key=lambda r:r['at_ms'])
T=collections.defaultdict(list)
for f in glob.glob(R+'/journal/*.jsonl'):
    for l in open(f):
        r=json.loads(l)
        if r['purpose']=='think':
            m=re.search(r'"you":\{.*?"id":(\d+)',r['request']['messages'][-1]['content'])
            if m: T[int(m.group(1))].append(r)
for v in T.values(): v.sort(key=lambda r:r['at_ms'])
def scene(r):
    c=r['request']['messages'][-1]['content']
    m=re.search(r'# What you perceive right now\n(\{.*?\})\n\n#',c,re.S)
    try: return json.loads(m.group(1)), c
    except Exception: return None, c
def fit(r,sc):
    me=sc['you']['id']; built=r['at_ms']-r['latency_ms']-(r['queue_wait_ms'] or 0)
    shown=[(x['id'],x['dist']) for x in sc.get('creatures',[]) if x.get('dist') is not None]
    best=None
    for back in range(0,150001,250):
        t=built-back; e=[abs(d-dd) for i,dd in shown if (d:=dist(me,i,t)) is not None]
        if len(e)>=2:
            m=st.median(e)
            if best is None or m<best[0]-1e-9: best=(m,t)
    return best
out=[]
for l in open(R+'/journal/outcomes/act_attempts.jsonl'):
    a=json.loads(l); aid=int(a['reference'].split('-')[1])
    if not (W0<=a['at_ms']<W1): continue
    refused={json.dumps(x['act'],sort_keys=True):x['refusal'].split('\n')[0] for x in a.get('refused') or []}
    cand=[r for r in J[aid] if r['at_ms']<=a['at_ms']+50]
    jr=cand[-1] if cand else None
    sc,ctext=scene(jr) if jr else (None,'')
    th=[r for r in T[aid] if jr and r['at_ms']<=jr['at_ms']]
    think_s=(th[-1]['latency_ms']/1000) if th else 3.5
    f=fit(jr,sc) if sc else None
    for s in a['acts']:
        act=json.loads(s); t=act.get('target'); why=refused.get(json.dumps(act,sort_keys=True))
        row=dict(actor=aid,do=act.get('do'),why=why,submit=a['at_ms'],purpose=jr and jr['purpose'],target=t)
        if isinstance(t,dict) and 'id' in t and sc:
            tid=t['id']
            try: tid=int(str(tid).lstrip('#'))
            except ValueError: row['id_text']=str(tid); tid=-1
            shown={x['id']:x for x in sc.get('creatures',[])}
            row['in_scene']=tid in shown
            row['in_text']=('#%d'%tid) in ctext
            row['scene_struct']=any(x.get('id')==tid for x in sc.get('structures',[])+sc.get('resources',[]))
            if f:
                row['fit_err']=f[0]; row['percept_ms']=f[1]; row['age_s']=(a['at_ms']-f[1])/1000
                row['model_s']=(jr['latency_ms'])/1000; row['pm_s']=think_s+jr['latency_ms']/1000
                for tag,tt in (('p',f[1]),('s',a['at_ms']),('p4',f[1]+4000),('p8',f[1]+8000),('pm',f[1]+int(1000*(think_s+jr['latency_ms']/1000)))):
                    d=dist(aid,tid,tt); row[tag]=('dead' if pos(tid,tt) is None else ('far' if d>SIGHT else 'near')) if pos(aid,tt) is not None else 'self?'
                    row[tag+'_d']=d
        if isinstance(t,dict) and 'place' in t and sc is not None:
            m=re.search(r'# Places you remember\n(.*?)\n\n#',ctext,re.S)
            row['places']=m.group(1).strip()[:80] if m else None
            row['place_name']=t['place']
        out.append(row)
json.dump(out,open(sys.argv[2],'w'),default=str)
print('acts in window', len(out), 'refused', sum(1 for r in out if r['why']))
c=collections.Counter()
for r in out:
    if not r['why']: continue
    t=r['target']; w=r['why']
    if 'in sight' in w:
        k='unseen:'+('id' if isinstance(t,dict) and 'id' in t else 'place' if isinstance(t,dict) and 'place' in t else 'other:'+json.dumps(t)[:20])
    elif 'graph' in w or 'unknown skill' in w or 'single' in w or 'needs' in w: k='malformed act (grammar)'
    elif 'middle of' in w or 'recovering' in w or 'not ready' in w: k='body busy (committed move / cooldown)'
    else: k='other: '+re.sub(r'\d+','N',w)[:50]
    c[k]+=1
tot=sum(c.values())
for k,v in c.most_common(): print(f'  {v:4d} {100*v/tot:4.0f}%  {k}')
ids=[r for r in out if r['why'] and 'in sight' in r['why'] and 'age_s' in r]
print('\n#id unseen with a fitted scene:',len(ids),' fit err p50 %.2f m'%st.median(r['fit_err'] for r in ids))
print('  scene age at act submit s: p10 %.1f p50 %.1f p90 %.1f'%tuple(st.quantiles([r['age_s'] for r in ids],n=10)[i] for i in (0,4,8)))
print('  no-queue counterfactual (scene + this think and compile call latencies) p50 %.1f s'%st.median(r['pm_s'] for r in ids))
for tag,lab in (('pm','scene + own model time, no queue'),('p','at the scene moment'),('p4','scene + 4 s'),('p8','scene + 8 s'),('s','at act submit')):
    cc=collections.Counter(r[tag] for r in ids if r.get('in_scene'))
    n=sum(cc.values()); print(f'  in-scene targets {lab}: '+', '.join(f'{k} {v} ({100*v/n:.0f}%)' for k,v in cc.most_common()))
nis=[r for r in ids if not r.get('in_scene')]
print('  target not in the scene list:',len(nis),'of',len(ids),'; of them named elsewhere in the prompt text',sum(r['in_text'] for r in nis),'; a structure/resource id',sum(r['scene_struct'] for r in nis))
pl=[r for r in out if r['why'] and 'in sight' in r['why'] and isinstance(r['target'],dict) and 'place' in r['target'] and 'place_name' in r]
print('\nplace-named unseen:',len(pl),'; prompt said Places you remember:',collections.Counter(r.get('places') for r in pl).most_common(3))
print('  names:',collections.Counter(re.sub(r'\[.*?\]|\(.*?\)|\d+','N',r['place_name'].lower()) for r in pl).most_common(12))
# ---- partition of #id unseen refusals (all, fitted or not)
allid=[r for r in out if r['why'] and 'in sight' in r['why'] and isinstance(r['target'],dict) and 'id' in r['target']]
P=collections.Counter()
for r in allid:
    if 'age_s' not in r: P['0 no scene fit / no journal match']+=1
    elif not r.get('in_scene'):
        P['1 naming: id not in the scene list ('+('structure/resource id' if r['scene_struct'] else 'named elsewhere in prompt text' if r['in_text'] else 'nowhere in the prompt')+')']+=1
    elif r['p']!='near': P['2 already out of sight/dead at the scene moment']+=1
    elif r['pm']!='near': P['3 fight pace: gone within its own model time (no queue)']+=1
    elif r['s']!='near': P['4 queue staleness: in sight after model time, gone by act submit']+=1
    else: P['5 within 11 m at submit by replay (occlusion / replay error)']+=1
n=len(allid); print('\nPartition of %d #id unseen refusals:'%n)
for k,v in sorted(P.items()): print(f'  {v:4d} {100*v/n:4.0f}%  {k}')
# relative-target counterfactual: at act submit, someone else in sight (<=11 m) / in reach (<=2.5 m)?
def others(aid,t,rad):
    pa=pos(aid,t)
    if pa is None: return None
    k=max(0,bisect.bisect_right(ts,t)-1)
    return sum(1 for i in B[k] if i!=aid and (p:=pos(i,t)) and math.dist(pa,p)<=rad)
c11=[others(r['actor'],r['submit'],11) for r in allid]; c25=[others(r['actor'],r['submit'],2.5) for r in allid]
v=[x for x in c11 if x is not None]
print('  at act submit, someone within 11 m: %d of %d; within 2.5 m: %d; others within 11 m p50 %d'%(sum(x>0 for x in v),len(v),sum((x or 0)>0 for x in c25),st.median(v)))
