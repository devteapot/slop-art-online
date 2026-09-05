#!/usr/bin/env python3
"""Bounded genuine hosted-model proof; separate internal harness and external MCP processes."""
import argparse,json,os,subprocess,time
from pathlib import Path
from run_carlid_npc import ROOT,CREDENTIAL,load_key
OUT=ROOT/'output/mixed-live-luna-20260905'
CONFIG=ROOT/'configs/reasoning/codex-carlid-luna-streaming-proof.json'
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('phase',choices=['host','behavior','communication','learning','step'])
 p.add_argument('--steps',type=int,default=1)
 p.add_argument('--side',choices=['both','internal','external'],default='both')
 p.add_argument('--attempt',type=int,choices=[1,2],default=1)
 a=p.parse_args();os.chdir(ROOT)
 if a.phase=='step':
  active=json.loads((OUT/'active.json').read_text())
  for _ in range(max(0,min(a.steps,10))):
   subprocess.run(['spacetime','call',active['db'],'sim_step',json.dumps(active['run']),'--server',active['server'],'--no-config','-y'],check=True,stdout=subprocess.DEVNULL)
  return
 env=os.environ.copy();env['CARLID_NPC_API_KEY']=load_key(CREDENTIAL)
 if a.phase=='host':
  if OUT.exists():raise SystemExit('Existing live archive retained; use its running host.')
  OUT.mkdir(parents=True)
  scenario=json.loads((ROOT/'scenarios/survival.json').read_text())
  scenario['name']='Bounded live mixed-agent communication proof'
  scenario['max_ticks']=24
  for site in scenario['sites']:site['hazard']=0
  for actor in scenario['players']:actor['position']=0
  (OUT/'scenario-input.json').write_text(json.dumps(scenario,indent=2))
  env.update(NPC_REASONING_CONFIG=str(CONFIG),BEVY_DEV_PORT='18892',BEVY_DEV_OUTPUT=str(OUT),BEVY_DEV_SCENARIO=str(OUT/'scenario-input.json'),BEVY_DEV_MAX_TICKS='24',SAO_HARNESS_MANUAL='1')
  os.execve(ROOT/'target/debug/sao-dev-client',['sao-dev-client'],env)
 active=json.loads((OUT/'active.json').read_text());run=OUT/active['run']
 participants=json.loads((run/'participants.json').read_text());sessions={r['role']:r['session_file'] for r in participants}
 phase=run/'live-inference'/(a.phase if a.attempt==1 else a.phase+'-correction')
 phase.mkdir(parents=True,exist_ok=False) # Repeating a phase requires an explicit new experiment.
 jobs=[]
 for side,key in [('internal','builtin'),('external','external')]:
  if a.side not in ['both',side]:continue
  folder=phase/side;folder.mkdir()
  log=(folder/'process.log').open('w')
  job=subprocess.Popen([str(ROOT/'target/debug/examples/participant_live_agent'),side,sessions[key],str(CONFIG),a.phase,str(folder)],env=env,stdout=log,stderr=log)
  jobs.append((side,job,log))
 (phase/'launch.json').write_text(json.dumps({'phase':a.phase,'model':'gpt-5.6-luna','endpoint':'https://codex.carlid.dev/v1','calls_planned':len(jobs),'max_attempts':1,'deadline_ms':300000,'no_provider_token_cap':True,'processes':{side:job.pid for side,job,_ in jobs}},indent=2))
 if a.phase=='communication' and a.attempt==1:
  # Once both actual requests have been journaled, advance the authority during deliberation.
  deadline=time.monotonic()+20
  while time.monotonic()<deadline:
   internal=list((phase/'internal').glob('harness-*.json'))
   if internal and (phase/'external'/'external.json').exists():break
   if any(job.poll() is not None for _,job,_ in jobs):break
   time.sleep(.1)
  progress=[]
  for _ in range(3):
   time.sleep(2)
   pending=[side for side,job,_ in jobs if job.poll() is None]
   subprocess.run(['spacetime','call',active['db'],'sim_step',json.dumps(active['run']),'--server',active['server'],'--no-config','-y'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   progress.append({'pending_processes_at_step':pending,'wall_time':time.time()})
  (phase/'concurrent-steps.json').write_text(json.dumps(progress,indent=2))
 results={}
 for side,job,log in jobs:results[side]=job.wait();log.close()
 (phase/'process-results.json').write_text(json.dumps(results,indent=2));print(json.dumps({'phase':a.phase,'exit_codes':results,'evidence':str(phase)}))
if __name__=='__main__':main()
