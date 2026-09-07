#!/usr/bin/env python3
"""Bounded actual-model pilot plus automated human client and developer observer.

Uses one fresh isolated 2.10 service, production binaries and explicit resource
limits. Does not alter the development service or reuse an experiment database.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.request
from benchmark_native_state import ROOT, SERVER, run, write, digest
from experiment_artifacts import verify


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--implementation',type=Path,required=True)
    parser.add_argument('--scenario',type=Path,required=True)
    parser.add_argument('--client-probe',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--image',required=True)
    args=parser.parse_args()
    implementation=args.implementation.resolve();verify(implementation)
    scenario=args.scenario.resolve();seed=json.loads(scenario.read_text())
    assert len(seed['players'])==72 and seed['players'][-1]['controller']=='human'
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'metrics').mkdir()
    image=json.loads(run('podman','image','inspect',args.image))[0]['Id']
    suffix=str(time.time_ns());container='sao-mixed-clock-'+suffix;volume=container+'-home'
    credentials=ROOT/'.local/credentials'/container;credentials.mkdir(parents=True,mode=0o700)
    (credentials/'mixed').mkdir(mode=0o700)
    config=credentials/'owner.toml'
    cli=Path.home()/'.local/share/spacetime/bin/2.7.1/spacetimedb-cli'
    manifest=dict(image=image,container=container,volume=volume,population=72,model_actors=[1,2],
        human_actor=72,human_input='automated real client path; no person at keyboard',
        authored_other_actors=69,model='gpt-5.6-luna',active_seconds=120,calls_per_model_actor=3,
        observer='one SDK sim_my_snapshot subscription for ~40s; production owner exports throughout',
        participant_connections='two model controllers plus one human during client interval',
        archive_audit=True,deadline_clock=True,external_mcp='persistent',rpc_slots=8,
        source_bundle=str(implementation),bundle_manifest_sha256=digest(implementation/'implementation.json'),
        scenario_sha256=digest(scenario),client_probe_sha256=digest(args.client_probe),
        rss_guard_bytes=11*1024**3,service_memory_limit_bytes=12*1024**3,
        host_available_floor_bytes=3*1024**3,disk_reserve_bytes=8*1024**3,wal_guard_bytes=4*1024**3)
    write(out/'manifest.json',manifest)
    result=dict(passed=False,resource_abort=[],monitor_errors=[])
    stopped=threading.Event();thread=None;pilot=None;client=None;created=False
    def monitor(pid):
        with (out/'memory.jsonl').open('w') as log:
            while not stopped.is_set():
                try:
                    now=time.time_ns()//10**6
                    with urllib.request.urlopen(SERVER+'/v1/metrics',timeout=3) as response:metrics=response.read().decode()
                    (out/'metrics'/f'{now}.prom').write_text(metrics)
                    p=dict(line.split(':',1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
                    host=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
                    sample=dict(wall_ms=now,rss_bytes=int(p['VmRSS'].split()[0])*1024,
                        host_available_bytes=int(host['MemAvailable'].split()[0])*1024,
                        disk_free_bytes=shutil.disk_usage(ROOT).free,
                        retained_log_bytes=sum(float(line.rsplit(' ',1)[1]) for line in metrics.splitlines()
                            if line.startswith('spacetime_message_log_size_bytes{')))
                    log.write(json.dumps(sample)+'\n');log.flush()
                    if (sample['rss_bytes']>manifest['rss_guard_bytes'] or sample['host_available_bytes']<manifest['host_available_floor_bytes']
                        or sample['disk_free_bytes']<manifest['disk_reserve_bytes'] or sample['retained_log_bytes']>manifest['wal_guard_bytes']):
                        result['resource_abort'].append(sample)
                        if pilot and pilot.poll() is None:pilot.terminate()
                        run('podman','stop','--time','5',container,timeout=15)
                        return
                except Exception as error:result['monitor_errors'].append(str(error))
                stopped.wait(1)
    try:
        run('podman','run','--rm','--user','spacetime','--volume',volume+':/home/spacetime',
            '--entrypoint','/bin/sh',image,'-c',
            'umask 077; mkdir -p /home/spacetime/.config/spacetime; '
            'openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out /home/spacetime/.config/spacetime/id_ecdsa && '
            'openssl ec -in /home/spacetime/.config/spacetime/id_ecdsa -pubout -out /home/spacetime/.config/spacetime/id_ecdsa.pub')
        command=['podman','run','--detach','--name',container,'--user','spacetime',
            '--label','sao.purpose=mixed-clock-benchmark','--publish','127.0.0.1:3103:3000',
            '--volume',volume+':/home/spacetime','--memory','12g','--memory-swap','12g','--pids-limit','1024',
            '--restart','no','--entrypoint','/opt/spacetime/spacetimedb-standalone',image,'start',
            '--listen-addr','0.0.0.0:3000','--data-dir','/home/spacetime/data','--non-interactive',
            '--page_pool_max_size',str(8*1024**3),'--jwt-pub-key-path','/home/spacetime/.config/spacetime/id_ecdsa.pub',
            '--jwt-priv-key-path','/home/spacetime/.config/spacetime/id_ecdsa']
        write(out/'service-command.json',command);run(*command);created=True
        for _ in range(100):
            try:
                with urllib.request.urlopen(urllib.request.Request(SERVER+'/v1/identity',method='POST'),timeout=1) as response:identity=json.load(response)
                break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('service readiness timeout')
        config.write_text('default_server = '+json.dumps(SERVER)+'\nspacetimedb_token = '+json.dumps(identity['token'])+'\n');os.chmod(config,0o600)
        pid=json.loads(run('podman','inspect',container))[0]['State']['Pid'];result['service_pid']=pid
        thread=threading.Thread(target=monitor,args=(pid,),daemon=True);thread.start()
        env=os.environ.copy();env.update(BEVY_DEV_SERVER=SERVER,SPACETIME_CONFIG_PATH=str(config))
        model_config=json.loads((implementation/'configs/reasoning/codex-carlid-luna-streaming-proof.json').read_text())
        write(out/'controllers.json',[dict(actor=1,role='builtin',config=model_config),dict(actor=2,role='external',config=model_config)])
        cmd=['python3',str(ROOT/'scripts/run_living_clearing.py'),'--implementation',str(implementation),
            '--scenario',str(scenario),'--output',str(out/'pilot'),'--port','18919','--minutes','2',
            '--calls-per-actor','3','--model-actors','1','2','--controllers',str(out/'controllers.json'),'--npc-runtime','host','--serial-ms','15000','--owner-snapshot-api','procedure',
            '--archive-audit','--deadline-clock','--external-mcp-mode','persistent','--external-rpc-concurrency','8',
            '--finalization-mode','stopped_host']
        write(out/'pilot-command.json',cmd)
        with (out/'pilot.log').open('w') as log:
            pilot=subprocess.Popen(cmd,env=env,stdout=log,stderr=log)
            deadline=time.monotonic()+420
            while pilot.poll() is None:
                path=out/'pilot/pilot.json'
                if client is None and path.exists():
                    state=json.loads(path.read_text())
                    if state.get('phase')=='running':
                        client_config=dict(server=SERVER,database=state['db'],run=state['run'],actor=72,
                            cli=str(cli),cli_config=str(config),credentials=str(credentials/'mixed'),output=str(out/'client-result.json'))
                        write(out/'client-config.json',client_config)
                        result['client_started_wall_ms']=time.time_ns()//10**6
                        client_log=(out/'client.log').open('w')
                        client=subprocess.Popen([str(args.client_probe.resolve()),str(out/'client-config.json')],stdout=client_log,stderr=client_log)
                if time.monotonic()>deadline:raise TimeoutError('420s pilot ceiling')
                time.sleep(.5)
        result['pilot_exit_code']=pilot.returncode
        if client:result['client_exit_code']=client.wait(timeout=20)
        pilot_result=json.loads((out/'pilot/pilot.json').read_text())
        client_result=json.loads((out/'client-result.json').read_text())
        exchanges=[]
        for path in (out/'pilot'/pilot_result['run']).rglob('*.json'):
            if not (path.name.startswith('harness-') or path.name=='external.json'): continue
            record=json.loads(path.read_text())
            reply=record.get('reply') or {}
            receipts=(record.get('result') or {}).get('receipts',[])
            accepted=sum((item.get('receipt') or item).get('ok') is True for item in receipts)
            exchanges.append(dict(path=str(path.relative_to(out)),actor=record.get('participant_context',{}).get('actor'),
                phase=record.get('phase'),provider_completed=bool(reply.get('raw_output')) and not reply.get('error'),
                error=record.get('error'),accepted_operations=accepted))
        model_pass=all(any(e['actor']==actor and e['provider_completed'] for e in exchanges) for actor in [1,2]) and sum(e['accepted_operations'] for e in exchanges)>0
        write(out/'model-exchanges.json',dict(passed=model_pass,exchanges=exchanges))
        result.update(pilot_phase=pilot_result.get('phase'),client=client_result,model_workload_pass=model_pass,
            passed=pilot.returncode==0 and client_result.get('passed') and model_pass and not result['resource_abort'] and not result['monitor_errors'])
    except BaseException as error:result['error']=f'{type(error).__name__}: {error}'
    finally:
        for process in [client,pilot]:
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=35)
                except subprocess.TimeoutExpired:process.kill();process.wait();result['forced_process_stop']=True
        stopped.set()
        if thread:thread.join(timeout=5)
        if created:
            try:
                (out/'service.log').write_text(run('podman','logs',container))
                run('podman','stop','--time','10',container,timeout=20)
                result['stop']=json.loads(run('podman','inspect',container))[0]['State']
            except Exception as error:result.update(passed=False,stop_error=str(error))
        write(out/'result.json',result)
    print(json.dumps(dict(passed=result['passed'],output=str(out))))
    raise SystemExit(0 if result['passed'] else 1)


if __name__=='__main__':main()
