#!/usr/bin/env python3
"""Measure world, native-controller and relay costs on two fresh services.

Retains both volumes, exact source/WASM/probe artifacts, metrics and stop outcomes.
Only the declared local experiment services are created or stopped.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import urllib.error
import copy
from owner_snapshot import export_world, export_audit_json

ROOT = Path(__file__).resolve().parents[1]
CLI = Path.home() / '.local/share/spacetime/bin/2.7.1/spacetimedb-cli'

def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

def trial_label(output):
    # Basenames repeat across iteration directories. Include the resolved output
    # identity so retained credentials, containers and volumes cannot collide.
    output = output.resolve()
    return output.name + '-' + hashlib.sha256(str(output).encode()).hexdigest()[:10]

def run(*args, timeout=30):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'{args[0]} {args[1]} failed: {p.stderr[:800]}')
    return p.stdout

def process(pid):
    status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
    if 'VmRSS' not in status:
        raise ProcessLookupError(f'process {pid} exited while sampling')
    stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return dict(pid=pid, rss_bytes=int(status['VmRSS'].split()[0])*1024,
                anon_bytes=int(status['RssAnon'].split()[0])*1024,
                swap_bytes=int(status['VmSwap'].split()[0])*1024,
                cpu_ticks=int(stat[11])+int(stat[12]),threads=int(status['Threads']))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=60)
    parser.add_argument('--image',required=True)
    parser.add_argument('--capture-module-logs',action='store_true',help='retain opt-in clock-profile spans after pause')
    parser.add_argument('--probe',choices=['population','boundary'],default='population')
    parser.add_argument('--human-actor',type=int)
    parser.add_argument('--observer',action='store_true')
    parser.add_argument('--render-mode',choices=['compatibility','components'],default='compatibility',
        help='SDK rendering subscriptions; components matches the current Bevy query set')
    parser.add_argument('--physical-clock',action='store_true')
    parser.add_argument('--action-period-ms',type=int,default=50)
    parser.add_argument('--action-hz',type=int,choices=[30,60],help='exact rational deadline rate; overrides the legacy millisecond period')
    parser.add_argument('--verify-combat-feed',action='store_true',help='after pause, verify optional combat subscriptions, reconnect and access scope')
    parser.add_argument('--verify-native-traces',action='store_true',help='after pause, verify typed trace scope, ordered metadata, payloads and retention')
    parser.add_argument('--verify-controller-catalogs',action='store_true',help='after pause, verify private catalog identity, exact reconstruction and reference retention')
    parser.add_argument('--verify-render-parts',action='store_true',help='after pause, compare component rendering with the compatibility projection and verify scope')
    parser.add_argument('--no-render',action='store_true',help='measure direct participant input without rendering subscriptions')
    parser.add_argument('--direct-input',action='store_true',help='use correlated StartAction requests even with rendering enabled')
    parser.add_argument('--human-server',help='optional separately delayed endpoint for the human connection')
    parser.add_argument('--start-gate',type=Path,help='wait while paused for this file, allowing browser enrollment before measurement')
    parser.add_argument('--check-population-limit',type=int,help='record a separate creation attempt before the workload')
    parser.add_argument('--implementation',type=Path,help='replay a hash-verified frozen implementation instead of current workspace artifacts')
    args=parser.parse_args()
    if args.action_hz: args.action_period_ms=1000//args.action_hz
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    label=trial_label(out)
    probe_name='controller_population_probe' if args.probe=='population' else 'controller_boundary_probe'
    credentials=ROOT/'.local/credentials'/f'controller-{label}'
    credentials.mkdir(mode=0o700,exist_ok=False)
    frozen=out/'implementation';frozen.mkdir()
    source_root=args.implementation.resolve() if args.implementation else ROOT
    source_manifest=None
    if args.implementation:
        source_manifest=json.loads((source_root/'manifest.json').read_text())
        for name,expected in source_manifest['files'].items():
            if hashlib.sha256((source_root/name).read_bytes()).hexdigest()!=expected:
                raise ValueError(f'frozen implementation hash mismatch: {name}')
        sources=list(source_manifest['files'])
    else:
        sources=run('git','ls-files','--cached','--others','--exclude-standard','-z').split('\0')
    names=[p for p in sources if p and (p in ['Cargo.toml','Cargo.lock','Justfile'] or p.split('/')[0] in ['simulation','server','shared','scripts','docs','client'])]
    names += ['target/wasm32-unknown-unknown/release/server_module.wasm',
              'target/wasm32-unknown-unknown/release/controller_module.wasm',
              f'target/release/examples/{probe_name}']
    hashes={}
    for artifact in names[-3:]:
        if not (source_root/artifact).is_file():raise ValueError(f'missing built artifact: {artifact}')
    for name in names:
        src=source_root/name
        if not src.is_file():continue
        dest=frozen/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
        hashes[name]=hashlib.sha256(dest.read_bytes()).hexdigest()
    write(frozen/'manifest.json',dict(files=hashes,base_commit=source_manifest['base_commit'] if source_manifest else run('git','rev-parse','HEAD').strip()))
    shutil.copy2(Path(__file__),out/'benchmark-driver.py')
    write(out/'invocation.json',dict(implementation_source=str(source_root),seconds=args.seconds,
        probe=args.probe,human_actor=args.human_actor,observer=args.observer,render_mode=args.render_mode,physical_clock=args.physical_clock,action_period_ms=args.action_period_ms,no_render=args.no_render,
        direct_input=args.direct_input,human_server=args.human_server,action_hz=args.action_hz,verify_combat_feed=args.verify_combat_feed,verify_render_parts=args.verify_render_parts,verify_controller_catalogs=args.verify_controller_catalogs,verify_native_traces=args.verify_native_traces,start_gate=str(args.start_gate.resolve()) if args.start_gate else None,
        check_population_limit=args.check_population_limit))
    shutil.copy2(args.scenario,out/'scenario.json')
    services=[];probe=None;result={}
    try:
        for kind,port,module in [('world',3103,'server_module'),('controller',3104,'controller_module')]:
            name=f'sao-controller-{label}-{kind}';volume=name+'-home';url=f'http://127.0.0.1:{port}'
            d=out/kind;d.mkdir();(d/'metrics').mkdir()
            run('podman','run','--rm','--user','spacetime','--volume',volume+':/home/spacetime','--entrypoint','/bin/sh',args.image,'-c',
                'umask 077; mkdir -p /home/spacetime/.config/spacetime; '
                'openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out /home/spacetime/.config/spacetime/id_ecdsa && '
                'openssl ec -in /home/spacetime/.config/spacetime/id_ecdsa -pubout -out /home/spacetime/.config/spacetime/id_ecdsa.pub')
            command=['podman','run','--detach','--name',name,'--user','spacetime','--label','sao.purpose=controller-boundary-benchmark',
                '--publish',f'127.0.0.1:{port}:3000','--volume',volume+':/home/spacetime','--memory','6g','--memory-swap','6g',
                '--pids-limit','1024','--restart','no','--stop-signal','SIGINT','--entrypoint','/opt/spacetime/spacetimedb-standalone',args.image,
                'start','--listen-addr','0.0.0.0:3000','--data-dir','/home/spacetime/data','--non-interactive',
                '--page_pool_max_size',str(3*1024**3),'--jwt-pub-key-path','/home/spacetime/.config/spacetime/id_ecdsa.pub',
                '--jwt-priv-key-path','/home/spacetime/.config/spacetime/id_ecdsa']
            write(d/'command.json',command);run(*command)
            info=json.loads(run('podman','inspect',name))[0]
            service=dict(kind=kind,name=name,volume=volume,url=url,pid=info['State']['Pid'],database=f'boundary-{label}-{kind}')
            services.append(service);write(out/'services.json',services)
            until=time.monotonic()+15
            while True:
                try:
                    with urllib.request.urlopen(urllib.request.Request(url+'/v1/identity',method='POST'),timeout=2) as r:identity=json.load(r)
                    break
                except OSError:
                    if time.monotonic()>until:raise
                    time.sleep(.1)
            config=credentials/(kind+'.toml');config.write_text('default_server = '+json.dumps(url)+'\nspacetimedb_token = '+json.dumps(identity['token'])+'\n');config.chmod(0o600)
            service['cli_config']=str(config)
            log=run(str(CLI),'--config-path',str(config),'publish',service['database'],'--server',url,
                '--bin-path',str(frozen/'target/wasm32-unknown-unknown/release'/(module+'.wasm')),'--delete-data=never','--no-config','-y')
            (d/'publish.log').write_text(log)
        w,b=services
        if args.check_population_limit:
            import tomllib
            candidate=json.loads((out/'scenario.json').read_text())
            original=candidate['players']
            candidate['players']=[dict(copy.deepcopy(original[i%len(original)]),id=i+1,name=f'Capacity actor {i+1}') for i in range(args.check_population_limit)]
            candidate['name']='Explicit population admission diagnostic'
            write(out/'capacity-scenario.json',candidate)
            token=tomllib.loads(Path(w['cli_config']).read_text())['spacetimedb_token']
            body=json.dumps([f'sim-capacity-{label}',json.dumps(candidate)]).encode()
            request=urllib.request.Request(f"{w['url']}/v1/database/{w['database']}/call/sim_create_client_world",data=body,
                headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
            begin=time.monotonic()
            try:
                with urllib.request.urlopen(request,timeout=60) as response:status,payload=response.status,response.read().decode()
            except urllib.error.HTTPError as error:status,payload=error.code,error.read().decode()
            write(out/'capacity-admission.json',dict(population=args.check_population_limit,status=status,
                response=payload,elapsed_ms=(time.monotonic()-begin)*1000,request_bytes=len(body),
                note='Admission only; an accepted world would not establish active population capacity.'))
        config=dict(cli=str(CLI),cli_config=w['cli_config'],server=w['url'],database=w['database'],
            controller_server=b['url'],controller_database=b['database'],run=f'sim-controller-{label}',
            scenario=str(out/'scenario.json'),credentials=str(credentials),output_dir=str(out),output=str(out/'result.json'),seconds=args.seconds,
            human_actor=args.human_actor,observer=args.observer,render_mode=args.render_mode,physical_clock=args.physical_clock,action_period_ms=args.action_period_ms,no_render=args.no_render,
            direct_input=args.direct_input,human_server=args.human_server,action_hz=args.action_hz,verify_combat_feed=args.verify_combat_feed,verify_render_parts=args.verify_render_parts,verify_controller_catalogs=args.verify_controller_catalogs,verify_native_traces=args.verify_native_traces,start_gate=str(args.start_gate.resolve()) if args.start_gate else None)
        write(out/'config.json',config)
        with (out/'probe.log').open('w') as log, (out/'process-samples.jsonl').open('w') as samples:
            probe=subprocess.Popen([str(frozen/f'target/release/examples/{probe_name}'),str(out/'config.json')],stdout=log,stderr=subprocess.STDOUT)
            until=time.monotonic()+args.seconds+300+(180 if args.start_gate else 0)
            while probe.poll() is None:
                start=time.monotonic();wall_ms=time.time_ns()//10**6
                try:
                    relay=process(probe.pid)
                except (FileNotFoundError, ProcessLookupError):
                    # A reaped/zombie process can lose VmRSS between poll and
                    # sampling. Preserve its actual exit and finalize normally.
                    probe.wait(timeout=1)
                    break
                values=dict(wall_ms=wall_ms,relay=relay)
                for s in services:
                    values[s['kind']]=process(s['pid'])
                    with urllib.request.urlopen(s['url']+'/v1/metrics',timeout=3) as r:metrics=r.read()
                    (out/s['kind']/'metrics'/f'{wall_ms}.prom').write_bytes(metrics)
                host=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
                values['host_available_bytes']=int(host['MemAvailable'].split()[0])*1024
                values['host_free_disk_bytes']=shutil.disk_usage(out).free
                samples.write(json.dumps(values)+'\n');samples.flush()
                if values['host_available_bytes']<3*1024**3 or values['host_free_disk_bytes']<8*1024**3:
                    write(out/'resource-guard.json',dict(wall_ms=wall_ms,
                        host_available_bytes=values['host_available_bytes'],minimum_available_bytes=3*1024**3,
                        host_free_disk_bytes=values['host_free_disk_bytes'],minimum_free_disk_bytes=8*1024**3))
                    raise RuntimeError('resource guard reached; stop measured workload')
                if time.monotonic()>until:raise RuntimeError('probe exceeded declared duration plus enrollment/cleanup allowance')
                time.sleep(max(0,1-(time.monotonic()-start)))
            result['probe_exit']=probe.returncode
        def call(name,*args):
            return run(str(CLI),'--config-path',w['cli_config'],'call',w['database'],name,
                *(json.dumps(a) for a in args),'--server',w['url'],'--no-config','-y')
        call('sim_operator_clock',config['run'],args.action_period_ms,True)
        if args.action_hz:
            query = "SELECT * FROM sim_clock_rate WHERE run = '" + config['run'].replace("'", "''") + "'"
            write(out/'clock-rate-state.json',json.loads(run(str(CLI),'--config-path',w['cli_config'],
                'sql',w['database'],query,'--server',w['url'],'--no-config','--format','json')))
        if args.capture_module_logs:
            (out/'module-logs.jsonl').write_text(run(str(CLI),'--config-path',w['cli_config'],
                'logs',w['database'],'--server',w['url'],'--no-config','--format','json',timeout=30))
        query = "SELECT * FROM sim_clock_deadline WHERE run = '" + config['run'].replace("'", "''") + "'"
        write(out/'deadline-state.json', json.loads(run(str(CLI),'--config-path',w['cli_config'],
            'sql',w['database'],query,'--server',w['url'],'--no-config','--format','json')))
        if args.physical_clock:
            query = "SELECT * FROM sim_physical_clock WHERE run = '" + config['run'].replace("'", "''") + "'"
            write(out/'physical-clock-state.json',json.loads(run(str(CLI),'--config-path',w['cli_config'],
                'sql',w['database'],query,'--server',w['url'],'--no-config','--format','json')))
        final_world=export_world(call,config['run'])
        write(out/'final-world.json',final_world)
        if args.verify_native_traces:
            from verify_native_trace import verify_native_trace
            trace_tables = {}
            for table in ('sim_native_participant', 'sim_native_trace_index', 'sim_native_experience'):
                query = "SELECT * FROM " + table + " WHERE run = '" + config['run'].replace("'", "''") + "'"
                raw = json.loads(run(str(CLI),'--config-path',w['cli_config'],
                    'sql',w['database'],query,'--server',w['url'],'--no-config','--format','json'))
                write(out/(table+'.json'), raw)
                trace_tables[table] = raw[0]['rows']
            if any(row[6] == 'sao-native-trace-pages-v4' for row in trace_tables['sim_native_participant']):
                for table in ('sim_native_trace_head', 'sim_native_trace_page', 'sim_native_evidence_body', 'sim_native_evidence_retention'):
                    query = "SELECT * FROM " + table + " WHERE run = '" + config['run'].replace("'", "''") + "'"
                    raw = json.loads(run(str(CLI),'--config-path',w['cli_config'],
                        'sql',w['database'],query,'--server',w['url'],'--no-config','--format','json'))
                    write(out/(table+'.json'),raw); trace_tables[table] = raw[0]['rows']
            write(out/'native-trace-verification.json', verify_native_trace(trace_tables,final_world,config['run']))
        if args.verify_controller_catalogs:
            from collections import Counter
            catalog_tables = {}
            for table in ('sim_native_controller', 'sim_native_controller_catalog'):
                query = "SELECT * FROM " + table + " WHERE run = '" + config['run'].replace("'", "''") + "'"
                raw = json.loads(run(str(CLI),'--config-path',w['cli_config'],
                    'sql',w['database'],query,'--server',w['url'],'--no-config','--format','json'))
                write(out/(table+'.json'), raw)
                catalog_tables[table] = raw[0]['rows']
            catalogs = {r[0]: r for r in catalog_tables['sim_native_controller_catalog']}
            references = Counter()
            hot_bytes = logical_bytes = 0
            for row in catalog_tables['sim_native_controller']:
                key, scope, actor, targets, value, action = row
                if scope != config['run'] or key != f'{scope}:{actor}':
                    raise ValueError('controller row scope mismatch')
                hot_bytes += len(value.encode())
                prefix = 'sao-controller-catalog-v1:'
                if value.startswith(prefix):
                    identity = value[len(prefix):]
                    references[identity] += 1
                    value = catalogs[identity][3]
                logical_bytes += len(value.encode())
                if json.loads(value) != final_world['participants'][str(actor)]['client_controller']['last_lifecycle']:
                    raise ValueError('catalog export mismatch')
            if set(references) != set(catalogs):
                raise ValueError('unreferenced or missing catalog rows')
            for identity, (_, scope, count, body) in catalogs.items():
                digest = hashlib.sha256()
                for value in (scope, 'controller-catalog-v1', body):
                    value = value.encode()
                    digest.update(len(value).to_bytes(8, 'little')); digest.update(value)
                digest.update(b'shared')
                if scope != config['run'] or count != references[identity] or digest.hexdigest() != identity:
                    raise ValueError('catalog identity or reference count mismatch')
            write(out/'controller-catalog-verification.json', dict(passed=True,
                controllers=len(catalog_tables['sim_native_controller']), catalogs=len(catalogs),
                references=sum(references.values()), hot_catalog_bytes=hot_bytes,
                logical_catalog_bytes=logical_bytes, retained_catalog_bytes=sum(len(r[3].encode()) for r in catalogs.values()),
                note='Paused owner diagnostics: exact reconstruction, scoped hashes, reference counts and no unreachable current catalogs.'))
        # Explicit paused diagnostics, outside the measured workload. Preserve
        # exact event strings across compressed blocks and the live tail.
        audit=export_audit_json(call,config['run'],final_world['next_event'])
        audit_bytes=('\n'.join(audit)+'\n').encode()
        (out/'final-audit.jsonl').write_bytes(audit_bytes)
        write(out/'audit-verification.json',dict(events=len(audit),
            next_event=final_world['next_event'],sha256=hashlib.sha256(audit_bytes).hexdigest()))
        retention=json.loads(run(str(CLI),'--config-path',b['cli_config'],
            'sql',b['database'],'SELECT * FROM brain_journal_retention','--server',b['url'],'--no-config','--format','json'))
        write(out/'controller-retention.json',retention)
        rows=retention[0]['rows']
        result['journal_retention']=dict(controllers=len(rows),archived_records=sum(r[1] for r in rows),
            active_records=sum(r[2]-r[1]-1 for r in rows),max_active_records=max((r[2]-r[1]-1 for r in rows),default=0),
            plain_bytes=sum(r[3] for r in rows),compressed_bytes=sum(r[4] for r in rows))
        if any(r[5] != [1,[]] for r in rows):raise RuntimeError('controller journal compression blocked; original records retained')
        if args.probe=='boundary' and not any(r[1]>0 for r in rows):raise RuntimeError('functional journal test did not cross an archive boundary')
    except BaseException as error:
        result['error']=f'{type(error).__name__}: {error}'
    finally:
        if probe and probe.poll() is None:
            probe.terminate()
            try:probe.wait(timeout=10)
            except subprocess.TimeoutExpired:probe.kill();probe.wait()
            result['probe_forced_stop']=probe.returncode
        for s in services:
            try:
                # Retain pre-stop diagnostics even if stopping fails, then also
                # capture shutdown messages and the exact exit status.
                (out/s['kind']/'service.log').write_text(run('podman','logs',s['name']))
                run('podman','stop','--time','30',s['name'],timeout=40)
                (out/s['kind']/'service-after-stop.log').write_text(run('podman','logs',s['name']))
                state = json.loads(run('podman','inspect',s['name']))[0]['State']
                write(out/s['kind']/'stop.json', state)
                if state['ExitCode'] != 0:
                    result[s['kind']+'_stop_error'] = f"service stopped with exit {state['ExitCode']}"
            except Exception as error:result[s['kind']+'_stop_error']=str(error)
        write(out/'runner-result.json',result)
    if result.get('error') or result.get('probe_exit')!=0 or any(k.endswith('_stop_error') for k in result):raise SystemExit(json.dumps(result))

if __name__=='__main__':main()
