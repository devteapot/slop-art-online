#!/usr/bin/env python3
"""Integration checks against two isolated real SpacetimeDB databases; no mock world.
Build the WASM first, start an isolated local 2.0.1 server on :3100, then run this.
Model outputs here are explicitly deterministic fixtures, not intelligence tests.
"""
import concurrent.futures, hashlib, json, os, pathlib, shutil, subprocess, time
ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = os.environ.get('SIM_SERVER', 'http://127.0.0.1:3100')
assert SERVER.startswith(('http://127.0.0.1:', 'http://localhost:')), 'local test server required'
CLI = os.environ.get('SPACETIME_CLI', 'spacetime')
WASM = os.environ.get('SIM_WASM', str(ROOT/'target/wasm32-unknown-unknown/debug/server_module.wasm'))
OUT = ROOT/'output'/f'reactive-verification-{time.time_ns()}'
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
    s=json.loads((ROOT/'scenarios/survival.json').read_text());s['max_ticks']=40;s['players']=s['players'][:2]
    for p in s['players']:
        p['position']=0;p['hunger']=10;p['energy']=40;p['food']=0;p['beliefs']=[]
    s['players'][1]['controller']='human';s['sites']=[dict(position=1,food=6,hazard=5)]
    return s

def action(skill,**kw):return dict(kind='action',action=dict(skill=skill,**kw))
def guard(condition,child):return dict(kind='guard',condition=condition,child=child)
tree=dict(kind='priority',children=[
    guard(dict(kind='danger',location=None),action('move',destination=0)),
    guard(dict(kind='not',condition=dict(kind='danger',location=1)),dict(kind='sequence',children=[action('move',destination=3),action('speak',text='arrived')])),
    dict(kind='sequence',children=[dict(kind='reconsider',reason='Reconsider the perceived dangerous route'),action('rest',duration=3)])])
proposal=dict(reason='deterministic reactive fixture, not live intelligence',policy=tree,reflections=[])
db=f'sim-reactive-{time.time_ns()}'
cli('publish',db,'--server',SERVER,'--bin-path',WASM,'--delete-data=never','--no-config','--yes')
(OUT/'setup.json').write_text(json.dumps(dict(database=db,scenario=scenario(),fixture=proposal),indent=2))
call(db,'sim_create',db,json.dumps(scenario()));step(db)
s=state(db);request=s['pending'][0]['id']
call(db,'sim_model_result',db,request,json.dumps(proposal),json.dumps(dict(backend='deterministic_fixture')))
call(db,'sim_intent',db,2,json.dumps(proposal))
s=state(db);installed=[p['execution']['decision'] for p in s['players']];generation=s['players'][0]['generation']
step(db);s=state(db)
assert all(p['position']==1 and p['health']==95 for p in s['players'])
assert s['players'][0]['generation']==generation and s['players'][0]['execution']['decision']==installed[0]
pending=s['pending'][0]['id'];step(db)
assert all(p['position']==0 for p in state(db)['players'])
for _ in range(6):step(db)
s=state(db);ev=events(db)
assert all(p['position']==0 and p['health']==95 and p['energy']>40 for p in s['players'])
assert s['players'][0]['execution']['decision']==installed[0]
assert any(p['id']==pending for p in s['pending'])
assert len([e for e in ev if e['kind']=='model_result'])==1
assert not any(e['kind']=='decision' and e['id']>max(installed) and e['data']['controller']=='authored_bootstrap' for e in ev)
assert any(e['kind']=='action_interrupted' and e['data']['policy_preserved'] for e in ev)
assert any(e['kind']=='branch_selected' and e['data']['previous'] is not None for e in ev)
assert s['players'][0]['energy']==s['players'][1]['energy']
step(db);s=state(db)
assert s['players'][0]['execution']['state']['cursors'], 'running sequence cursor not persisted'
# The authority reloads the persisted JSON on every reducer; a pending pre-harm request remains usable.
call(db,'sim_model_result',db,pending,json.dumps(proposal),json.dumps(dict(backend='deterministic_fixture')))
s=state(db);assert s['players'][0]['generation']==generation+1
assert s['players'][0]['execution']['decision']!=installed[0]
# Reject malformed composites through the actual reducer without replacing installed policy.
wanted=s['players'][1]['execution']['decision'];bad=dict(proposal,policy=dict(kind='sequence',children=[]))
call(db,'sim_intent',db,2,json.dumps(bad));assert state(db)['players'][1]['execution']['decision']==wanted
step(db);s=state(db);request=s['pending'][0]['id'];installed_after=s['players'][0]['execution']['decision']
call(db,'sim_model_result',db,request,'',json.dumps(dict(error='provider HTTP 524 failure with non-JSON body')))
assert state(db)['players'][0]['execution']['decision']==installed_after
assert any(e['kind']=='model_rejected' and 'no proposal returned' in e['data']['reason'] for e in events(db))
s=state(db);ev=events(db);ids={e['id'] for e in ev}
assert all(parent in ids and parent<e['id'] for e in ev for parent in e['parents'])
(OUT/'snapshot.json').write_text(json.dumps(dict(world=s,events=ev),indent=2))
(OUT/'fixture-policy.json').write_text(json.dumps(proposal,indent=2))
# A truthful fixture manifest makes this retained proof inspectable without a backend.
runner=ROOT/'target/debug/sao-sim'
manifest=dict(run=db,db=db,server=SERVER,scenario=s['initial'],model='deterministic fixture (no model)',ollama='',reasoning=None,reasoning_version='deterministic-fixture',decision_format='survivor-policy-v2',tick_ms=0,rules=s['version'],wasm_sha256=hashlib.sha256(pathlib.Path(WASM).read_bytes()).hexdigest(),runner_sha256=hashlib.sha256(runner.read_bytes()).hexdigest() if runner.exists() else '',git_head=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip(),cli_version=cli('--version').stdout.strip(),created_ms=int(time.time()*1000),evidence_mode='deterministic_fixture')
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
shutil.copyfile(WASM,OUT/'module.wasm')
report=dict(status='passed',database=db,artifacts=str(OUT),checks=['real reducer human/AI policy parity','newly perceived danger switches installed tree without model response','damage preserves policy and pending generation','retreat/recovery avoids return to known danger in fixture policy','persistent running cursors across reducer reloads','pre-harm request accepted with current guards','invalid tree retains installed policy','causal links ordered','non-JSON transport failure distinguished from malformed model proposal'],model_validation='deterministic fixtures, separate from live generated policy')
(OUT/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
