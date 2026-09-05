#!/usr/bin/env python3
"""ONE local generation, unedited submission to real reducers, then no further model calls."""
import argparse,hashlib,json,pathlib,shutil,subprocess,time
ROOT=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', default='output/local-reactive-proof')
parser.add_argument('--feedback', help='Recorded prior raw proposal and semantic rejection JSON')
args=parser.parse_args()
OUT=(ROOT/args.output).resolve()
assert not OUT.exists(), 'preserve existing proof; this script never overwrites or loops generations'
SERVER='http://127.0.0.1:3100'
DB=f'sim-local-reactive-{time.time_ns()}'
WASM=ROOT/'target/wasm32-unknown-unknown/debug/server_module.wasm'
CONFIG=ROOT/'configs/reasoning/ollama-reactive-proof.json'
def cli(*args):
 r=subprocess.run(['spacetime',*map(str,args)],cwd=ROOT,capture_output=True,text=True)
 if r.returncode:raise RuntimeError(r.stderr)
 return r.stdout
def call(name,*args):return cli('call',DB,name,*[json.dumps(a) for a in args],'--server',SERVER,'--no-config','-y')
def sql(query):return json.loads(cli('sql',DB,query,'--server',SERVER,'--format','json','--no-config'))[0]['rows']
def state():return json.loads(sql('SELECT state FROM sim_run')[0][0])
def events():return sorted([json.loads(row[0]) for row in sql('SELECT json FROM sim_audit')],key=lambda e:e['id'])
scenario=json.loads((ROOT/'scenarios/survival.json').read_text());scenario['max_ticks']=30
for player in scenario['players'][1:]:player['controller']='human'
scenario['sites'][0]['food']=1
cli('publish',DB,'--server',SERVER,'--bin-path',WASM,'--delete-data=never','--no-config','--yes')
call('sim_create',DB,json.dumps(scenario));call('sim_step',DB)
initial=state();input_path=ROOT/f'output/{DB}-generation-input.json';input_path.write_text(json.dumps(initial,indent=2))
# Tick1 is held while the ONE local generation completes; this is not a throughput benchmark.
subprocess.run([str(ROOT/'target/debug/examples/local_policy_probe'),str(input_path),str(CONFIG),str(OUT)]+([args.feedback] if args.feedback else []),cwd=ROOT,check=True,timeout=270)
result=json.loads((OUT/'generation.json').read_text())
call('sim_model_result',DB,result['request_id'],result['raw'],json.dumps(result['metadata']))
for _ in range(29):call('sim_step',DB)
s=state();ev=events();(OUT/'snapshot.json').write_text(json.dumps(dict(world=s,events=ev),indent=2));(OUT/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in ev))
shutil.copyfile(WASM,OUT/'module.wasm')
config=result['metadata']['config']
manifest=dict(run=DB,db=DB,server=SERVER,scenario=s['initial'],model=config['backend']['model'],ollama=config['backend']['endpoint'],reasoning=config,reasoning_version=result['metadata']['reasoning_version'],decision_format=result['metadata']['decision_format'],rules=s['version'],tick_ms=0,wasm_sha256=hashlib.sha256(WASM.read_bytes()).hexdigest(),runner_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),generator_sha256=hashlib.sha256((ROOT/'target/debug/examples/local_policy_probe').read_bytes()).hexdigest(),git_head=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip(),cli_version=cli('--version').strip(),created_ms=int(time.time()*1000),evidence_mode='one_local_generation_then_authority_steps',timing='one local generation at fixed tick1, then29 direct reducer steps; no further model responses or inference')
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
report=dict(run=DB,ticks=s['tick'],events=len(ev),generation_calls=1,raw_output_edited=False,installed_policy_ids=[e['id'] for e in ev if e['kind']=='policy_installed'],branch_changes=[e for e in ev if e['kind']=='branch_selected'],model_results=[e['id'] for e in ev if e['kind']=='model_result'],rejections=[e for e in ev if e['kind']=='model_rejected'],metadata=result['metadata'],interpretation='Local model evidence only; no hosted Luna claim; model timing was decoupled from logical ticks for this single-generation proof.')
(OUT/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='metadata'},indent=2))
