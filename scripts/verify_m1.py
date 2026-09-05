#!/usr/bin/env python3
"""Integration checks against two isolated real SpacetimeDB databases; no mock world.
Build the WASM first, start an isolated local 2.0.1 server on :3100, then run this.
Model outputs here are explicitly deterministic fixtures, not intelligence tests.
"""
import concurrent.futures, json, os, pathlib, subprocess, time
ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = os.environ.get('SIM_SERVER', 'http://127.0.0.1:3100')
assert SERVER.startswith(('http://127.0.0.1:', 'http://localhost:')), 'local test server required'
CLI = os.environ.get('SPACETIME_CLI', 'spacetime')
WASM = os.environ.get('SIM_WASM', str(ROOT/'target/wasm32-unknown-unknown/debug/server_module.wasm'))
OUT = ROOT/'output'/f'm1-verification-{time.time_ns()}'
OUT.mkdir(parents=True)

def cli(*args, ok=True):
    r = subprocess.run([CLI, *map(str,args)], cwd=ROOT, capture_output=True, text=True)
    if ok and r.returncode: raise AssertionError(r.stderr)
    return r

def call(db, name, *args, anonymous=False, ok=True):
    options=['--anonymous'] if anonymous else []
    return cli('call',db,name,*[json.dumps(a) for a in args],'--server',SERVER,'--no-config','-y',*options,ok=ok)

def sql(db, query):
    return json.loads(cli('sql',db,query,'--server',SERVER,'--format','json','--no-config').stdout)[0]['rows']

def state(db): return json.loads(sql(db,'SELECT state FROM sim_run')[0][0])
def events(db): return sorted([json.loads(r[0]) for r in sql(db,'SELECT json FROM sim_audit')],key=lambda e:e['id'])
def decision(*actions, reflections=None): return dict(reason='integration fixture intention',actions=list(actions),reflections=reflections or [])
def intent(db, actor, *actions): call(db,'sim_intent',db,actor,json.dumps(decision(*actions)))
def step(db): call(db,'sim_step',db)
def scenario():
    s=json.loads((ROOT/'scenarios/survival.json').read_text())
    s['max_ticks']=60
    for p in s['players']:
        p['controller']='human';p['food']=0;p['hunger']=20;p['position']=0;p['beliefs']=[]
    s['players'][1]['controller']='ai'
    s['players'][2]['position']=8
    s['sites']=[dict(position=2,food=5,hazard=0),dict(position=4,food=0,hazard=100)]
    return s

def setup(suffix):
    db=f'sim-check-{time.time_ns()}-{suffix}'
    cli('publish',db,'--server',SERVER,'--bin-path',WASM,'--delete-data=never','--no-config','--yes')
    call(db,'sim_create',db,json.dumps(scenario()))
    return db

with concurrent.futures.ThreadPoolExecutor(2) as pool:
    a,b=list(pool.map(setup,['a','b']))
    start=time.time()
    list(pool.map(step,[a,b]))
assert state(a)['tick']==state(b)['tick']==1
# State is isolated even when run IDs or pending-request IDs are guessed.
assert call(a,'sim_step',b,ok=False).returncode != 0
assert call(a,'sim_step',a,anonymous=True,ok=False).returncode != 0
private=cli('sql',a,'SELECT state FROM sim_run','--server',SERVER,'--format','json','--no-config','--anonymous',ok=False)
assert private.returncode != 0 or not json.loads(private.stdout)[0]['rows'], 'private observer data leaked'
assert call(a,'sim_create',a,json.dumps(scenario()),ok=False).returncode != 0
# Two controllers run the same sequence and prerequisites on the authority.
plan=decision(dict(skill='move',destination=2),dict(skill='gather'),dict(skill='eat'))
call(a,'sim_intent',a,1,json.dumps(plan))
pending=state(a)['pending'][0]
call(a,'sim_model_result',a,pending['id'],json.dumps(plan),json.dumps(dict(backend='deterministic_fixture')))
for _ in range(4): step(a)
s=state(a);p,q=s['players'][:2]
assert p['position']==q['position']==2 and p['food']==q['food']==0
assert p['energy']==q['energy'] and p['hunger']==q['hunger']
assert state(b)['tick']==1, 'cross-run mutation'
# Chosen arbitrary text -> emission -> eligible perception -> model interpretation -> choice.
text='The moon looks like a bent spoon; I trust you enough to share my last route. Shall we rest here?'
intent(a,1,dict(skill='speak',text=text));step(a)
s=state(a);heard=[m for m in s['players'][1]['memories'] if m['kind']=='speech' and m['content']['text']==text]
assert heard and not any(m['kind']=='speech' for m in s['players'][2]['memories'])
assert not s['players'][1]['relationships'], 'speech silently copied trust'
# Let individual self-reconsideration request a context that contains the speech.
for _ in range(20):
    s=state(a)
    pending=next((r for r in s['pending'] if r['actor']==2 and any(m['source']==heard[0]['source'] for m in r['context']['player']['memories'])),None)
    if pending:break
    for old in s['pending']:call(a,'sim_model_result',a,old['id'],'invalid',json.dumps(dict(backend='deterministic_fixture',error='failed model fixture')))
    step(a)
assert pending
reflection=dict(source=heard[0]['source'],interpretation='This person confided in me; I will rest with them and trust their report',caution_delta=5,trust_delta=7,belief=dict(location=2,danger=False,text='I tentatively trust this route'))
response=decision(dict(skill='rest',duration=2),dict(skill='speak',text='I will rest with you, then we can look for food.'),reflections=[reflection])
call(a,'sim_model_result',a,pending['id'],json.dumps(response),json.dumps(dict(backend='deterministic_fixture')))
assert state(a)['players'][1]['relationships']['1']==7
for _ in range(3):step(a)
assert any(e['kind']=='speech' and e['actor']==2 for e in events(a))
# Failed attempt ends sequence; it cannot emit the following speech.
intent(a,1,dict(skill='eat'),dict(skill='speak',text='FORBIDDEN-AFTER-FAILURE'));step(a)
assert any(e['kind']=='skill_result' and e['data']['status']=='failed' for e in events(a))
assert not any(e['kind']=='speech' and e['data']['text']=='FORBIDDEN-AFTER-FAILURE' for e in events(a))
# Permanent death, interrupted sequence, and ignorant distant survivor.
intent(a,1,dict(skill='move',destination=4),dict(skill='speak',text='FORBIDDEN-AFTER-DEATH'))
for _ in range(3):step(a)
assert state(a)['players'][0]['health']==0
intent(a,1,dict(skill='rest'));step(a)
assert state(a)['players'][0]['health']==0
assert any(e['kind']=='intent_rejected' and e['actor']==1 for e in events(a))
assert not any(m['kind']=='death' for m in state(a)['players'][2]['memories'])
# Invalid and duplicate model outputs are retained, never accepted silently.
call(a,'sim_model_result',a,pending['id'],'not json',json.dumps(dict(backend='deterministic_fixture')))
assert any(e['kind']=='model_rejected' for e in events(a))
# Evidence consistency and exports, independent of living state or memory length.
for db in [a,b]:
    ev=events(db);s=state(db);ids={e['id'] for e in ev}
    assert len(ids)==len(ev) and all(e['run']==db for e in ev)
    assert all(parent in ids for e in ev for parent in e['parents']), 'dangling causal reference'
    assert all(parent<e['id'] for e in ev for parent in e['parents']), 'causal order violated'
    (OUT/f'{db}.json').write_text(json.dumps(dict(world=s,events=ev),indent=2))
report=dict(status='passed',databases=[a,b],parallel_step_started=start,checks=['parallel isolated authority','private observer tables and operator auth','no overwrite','shared controller execution','sequence progress and failure','free speech perception and interpretation','experience affects later decision','permanent death and retained history','distant survivor unaware','invalid/duplicate model result evidence','causal links'],model_validation='deterministic fixtures only; live runs are separate',artifacts=str(OUT))
(OUT/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
