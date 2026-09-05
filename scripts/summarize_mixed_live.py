#!/usr/bin/env python3
"""Summarize archived real-model evidence; never loads credentials or makes inference calls."""
import hashlib,json,shutil,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
root=ROOT/'output/mixed-live-luna-20260905'
a=json.loads((root/'active.json').read_text());run=root/a['run']
s=json.loads((run/'snapshot.json').read_text());w=s['world'];events=s['events']
calls=[]
for folder in sorted((run/'live-inference').iterdir()):
 for side in ['internal','external']:
  files=list((folder/side).glob('harness-*.json')) if side=='internal' else list((folder/side).glob('external.json'))
  for f in files:
   d=json.loads(f.read_text());reply=d['reply'];assert d['phase']=='completed'
   context=d['participant_context'];assert context['actor']==(1 if side=='internal' else 2)
   assert not any(key in context for key in ['sites','pending','world'])
   assert reply['served_model']=='gpt-5.6-luna' and reply['status']==200 and reply['finish_reason']=='stop' and reply['stream']['done_received']
   calls.append({'phase':folder.name,'runtime':side,'served_model':reply['served_model'],'http_status':reply['status'],'finish_reason':reply['finish_reason'],'usage':reply.get('usage'),'runtime_error':d.get('error'),'result':d.get('result'),'journal':str(f.relative_to(ROOT))})
assert len(calls)==10
assert w['tick']==7 and not w['stopped']
characters=[]
for actor in [1,2]:
 p=next(p for p in w['players'] if p['id']==actor)
 state=w['participants'][str(actor)]
 own=[e for e in events if e['actor']==actor]
 installs=[e for e in own if e['kind']=='policy_installed'];assert len(installs)==1
 speech=[e for e in own if e['kind']=='speech'];assert len(speech)==1
 learn=[e for e in own if e['kind']=='identity_change'];assert len(learn)==1
 assert state['learning_revision']==1 and p['generation']==1
 assert p['health']==100 and p['execution'] is not None
 heard=[e for e in own if e['kind']=='perception' and e['data']['kind']=='speech'];assert len(heard)==1
 attempts=[{'event':e['id'],'tick':e['tick'],'skill':e['data']['action']['skill'],'destination':e['data']['action'].get('destination')} for e in own if e['kind']=='skill_attempt']
 assert len(attempts)>=3
 characters.append({'actor':actor,'name':p['name'],'runtime':'built-in harness / ParticipantService' if actor==1 else 'separate minimal Rust model-driven MCP client','position':p['position'],'health':p['health'],'hunger':p['hunger'],'energy':p['energy'],'carried_food':p['food'],'caution':p['caution'],'relationships':p['relationships'],'goal':p['motive'],'policy_revision':p['generation'],'learning_revision':state['learning_revision'],'installed_policy_event':installs[0]['id'],'skill_attempts':attempts,'speech':speech[0],'heard_speech_event':heard[0]['id'],'learning_event':learn[0]})
steps=json.loads((run/'live-inference/communication/concurrent-steps.json').read_text())
assert all(side in steps[0]['pending_processes_at_step'] for side in ['internal','external'])
for actor in [1,2]:assert any(e['actor']==actor and e['kind']=='skill_result' and e['tick'] in [2,3] for e in events)
# Preserve the model-selected tree that was submitted before the external phase guard failed.
first=json.loads((run/'live-inference/behavior/external/external.json').read_text())
chosen=json.loads(first['reply']['raw_output'])['operations'][0]['tree']
submitted=next(e for e in events if e['actor']==2 and e['kind']=='participant_command' and e['data']['command']['op']=='replace_tree')
assert submitted['data']['command']['tree']==chosen
rejections=[e for e in events if e['kind']=='participant_rejected'];assert len(rejections)==4
report={'run':a['run'],'database':a['db'],'url':a['url'],'state':'paused at tick7; bounded agent processes completed; installed trees retained','tick':w['tick'],'scenario':'24tick capacity, initial co-location, environmental hazards zero, otherwise shared survival rules','inference_calls':len(calls),'requested_and_served_model':'gpt-5.6-luna','provider_route':'configured Carlid streaming Chat Completions','external_runtime':'custom minimal Rust model-driven MCP stdio client, not a packaged-agent compatibility claim','characters':characters,'concurrent_authority_steps':steps,'calls':calls,'authority_rejections':rejections,'external_initial_phase_error':'Tree accepted before an out-of-responsibility speech operation was rejected locally; corrected prevalidation validates the whole proposal before any submission. Model output and accepted tree retained unchanged.','regression_tests':66,'test_note':'One pre-existing 300ms cancellation timing check failed under parallel load; targeted rerun and final full serial suite passed.','old_services_http':{str(port):urllib.request.urlopen(f'http://127.0.0.1:{port}').status for port in [18890,18891,18892]},'limits':['No authored fallback or mocked response','Model corrections were fresh calls, never rewritten output','Controlled bounded clock, not an unattended agent longevity test','No environmental hazard challenge in this functional proof','No public deployment, ACP or packaged-agent compatibility claim','No commits, pushes, proxy restarts or old-session replacement']}
(run/'verification.json').write_text(json.dumps(report,indent=2))
source=run/'runtime-source';source.mkdir(exist_ok=True)
for path in ['server/bridge/examples/participant_live_agent.rs','server/bridge/src/agent_harness.rs','server/bridge/src/bin/sao-dev-client.rs','server/bridge/src/bin/sao-agent-mcp.rs','scripts/run_mixed_live.py','configs/reasoning/codex-carlid-luna-streaming-proof.json']:
 shutil.copyfile(ROOT/path,source/Path(path).name)
hashes={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in ['target/debug/examples/participant_live_agent','target/debug/sao-agent-mcp','target/debug/sao-dev-client']}
(source/'binary-sha256.json').write_text(json.dumps(hashes,indent=2))
print(json.dumps({'report':str(run/'verification.json'),'calls':len(calls),'characters':[{k:c[k] for k in ['name','position','health','caution','relationships','policy_revision','learning_revision']} for c in characters],'rejection_count':len(rejections)},indent=2))
