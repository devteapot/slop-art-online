#!/usr/bin/env python3
"""Classify fast-lane replies, saved or replayed, as the WHY tables do (docs/FAST_LANE_WHY_TABLES.md),
plus whether the battle fixture's fight is kept whole (docs/FAST_LANE_FRAME.md §3).

usage: battle_frame_classify.py FILE.jsonl [FILE.jsonl ...]   (rows of `living-mind fast-replay`)"""
import json,sys,collections
RETREAT={'flee','back_off'}; ATTACK={'strike','attack','close_in','shoot','bowshot','throw'}
def kids(n):
    if not isinstance(n,dict): return []
    for k in ('first','seq'):
        v=n.get(k)
        if isinstance(v,dict): return v.get('children',[])
        if isinstance(v,list): return v
    return []
def walk(n,guards=()):
    """yield (skill, guards, node) for every do-node in priority order"""
    if not isinstance(n,dict): return
    if 'do' in n:
        d=n['do']; yield (d.get('skill') if isinstance(d,dict) else d, guards, d); return
    if 'if' in n:
        i=n['if']; yield from walk(i.get('then'),guards+(i.get('cond'),));
        if i.get('else') is not None: yield from walk(i.get('else'),guards+(('not',i.get('cond')),))
        return
    if 'desires' in n:
        for d in n['desires']: yield from walk(d.get('do'),guards)
        return
    for c in kids(n): yield from walk(c,guards)
def reads(c,acc):
    if isinstance(c,dict):
        for k,v in c.items():
            if k in ('stamina','health','count','doing','hurt_within','health_of','threatened','near','sees'): acc.add(k)
            reads(v,acc)
    elif isinstance(c,(list,tuple)):
        for x in c: reads(x,acc)
    return acc
def fixture_kept(g):
    s=json.dumps(g)
    heal='"skill": "heal", "target": "self"' in s
    guard=('"threatened": true' in s) and ('"skill": "dodge"' in s or '"skill": "block"' in s)
    strike='"skill": "strike", "target": {"nearest"' in s
    return heal and guard and strike
def classify(rep):
    out={'kind':rep.get('change')}
    if rep.get('change')!='patch' or not isinstance(rep.get('graph'),dict): return out
    g=rep['graph']; dos=list(walk(g))
    sk=[d[0] for d in dos]
    out['retreat']=any(s in RETREAT for s in sk)
    out['uncond_retreat']=any(s in RETREAT and not gd for s,gd,_ in dos)
    first_att=next((i for i,s in enumerate(sk) if s in ATTACK),None)
    out['attack']=first_att is not None
    out['retreat_ahead']=any(s in RETREAT and (first_att is None or i<first_att) for i,s in enumerate(sk))
    out['uncond_retreat_ahead']=any(s in RETREAT and not dos[i][1] and (first_att is None or i<first_att) for i,s in enumerate(sk))
    out['press']=any(s=='close_in' for s in sk) or any(s in ATTACK and reads(gd,set())&{'doing','health_of'} and ('recover' in json.dumps(gd) or 'release' in json.dumps(gd) or 'winding' in json.dumps(gd) or 'health_of' in json.dumps(gd)) for s,gd,_ in dos)
    out['guards']=sorted(set().union(*[reads(gd,set()) for s,gd,_ in dos if s in RETREAT]) if out['retreat'] else [])
    out['fight_kept']=fixture_kept(g)
    # Which of the balanced frame's ways a patch takes up (by its line's shape), and whether it
    # copies the example's numbers (prompts.rs FAST_WAYS).
    def has(pred): return any(pred(s,json.dumps(gd)) for s,gd,_ in dos)
    out['way_timing']=has(lambda s,gd: s in ('block','dodge','jump') and '"doing"' in gd and ('release' in gd or 'winding' in gd))
    out['way_target']=has(lambda s,gd: s in ATTACK and '"sees": "attacker"' in gd)
    out['way_press']=has(lambda s,gd: s in ATTACK and 'recovering' in gd)
    out['way_room']=has(lambda s,gd: s=='back_off' and '"count"' in gd)
    out['way_break']=has(lambda s,gd: s=='flee' and '"health"' in gd)
    out['copied_numbers']=has(lambda s,gd: ('"within": 3.0' in gd and '"at_least": 3' in gd) or '"below": 20.0' in gd or '"within": 2.5' in gd)
    out['lines']=len(dos)
    return out
def table(rows,key):
    c=[classify(r.get(key) or {}) for r in rows if r.get(key) is not None]
    n=len(c); k=collections.Counter(x['kind'] for x in c); p=[x for x in c if x['kind']=='patch']
    res={'n':n,'kinds':dict(k)}
    if p:
        for m in ('retreat','uncond_retreat','retreat_ahead','uncond_retreat_ahead','attack','press','fight_kept','way_timing','way_target','way_press','way_room','way_break','copied_numbers'):
            res[m]=round(100*sum(x[m] for x in p)/len(p),1)
        g=collections.Counter(gg for x in p for gg in x['guards']); rp=sum(x['retreat'] for x in p) or 1
        res['retreat_guards_%']={k:round(100*v/rp) for k,v in g.most_common(6)}
        res['lines_p50']=sorted(x['lines'] for x in p)[len(p)//2]
    return res
if __name__=='__main__':
    for f in sys.argv[1:]:
        rows=[json.loads(l) for l in open(f)]
        print(f); 
        for key in ('saved','replayed'):
            if any(r.get(key) for r in rows):
                print(' ',key,json.dumps(table(rows,key)))
        first=[r for r in rows if r['idx']==0]
        for key in ('saved','replayed'):
            if any(r.get(key) for r in first): print(' ',key,'first call per fighter',json.dumps(table(first,key)))
