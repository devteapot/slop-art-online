#!/usr/bin/env python3
"""Run pinned implementation variants concurrently, retain a manifest and compare evidence.

The coordinator owns launch/stop/evidence, never character decisions or world advancement.
Review each completed batch before creating the next hypothesis manifest.
"""
import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

from experiment_artifacts import ROOT, digest, verify, write
from summarize_arena_matrix import summarize


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();spec=json.loads(args.manifest.read_text());out=args.output.resolve()
    if out.exists():raise SystemExit('Choose a new batch evidence directory')
    variants=spec.get('variants',[])
    if not 1<=len(variants)<=4:raise SystemExit('A batch needs one to four variants')
    if not spec.get('hypothesis') or not spec.get('evaluation'):raise SystemExit('Record a hypothesis and evaluation criteria before running')
    ids=[v['id'] for v in variants];ports=[v['port'] for v in variants]
    if len(set(ids))!=len(ids) or len(set(ports))!=len(ports):raise SystemExit('Variant IDs and ports must be unique')
    for v in variants:
        if not v['id'].replace('-','').replace('_','').isalnum():raise SystemExit('Use simple variant IDs')
        v['serial_ms']=v.get('serial_ms',spec.get('serial_ms',15000))
        if not isinstance(v['serial_ms'],int) or v['serial_ms']<1000:raise SystemExit('Serial intervals must be at least 1000 ms')
        v['implementation']=str(Path(v['implementation']).resolve())
        verify(Path(v['implementation']))
        for key in ('scenario','controllers'):
            v[key]=str(Path(v[key]).resolve())
            json.loads(Path(v[key]).read_text())
        for controller in json.loads(Path(v['controllers']).read_text()):
            if controller['config']['backend']['model']!='gpt-5.6-luna':raise SystemExit('This iteration campaign is Luna-only')
    out.mkdir(parents=True)
    write(out/'manifest.json',spec)
    report=dict(phase='preparing',hypothesis=spec['hypothesis'],evaluation=spec['evaluation'],variants=[])
    jobs=[];stop=False
    def interrupted(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGINT,interrupted);signal.signal(signal.SIGTERM,interrupted)
    try:
        for v in variants:
            inputs=out/(v['id']+'-inputs');inputs.mkdir()
            for key in ('scenario','controllers'):
                value=json.loads(Path(v[key]).read_text());write(inputs/(key+'.json'),value)
            folder=out/v['id'];log=(out/(v['id']+'.log')).open('w')
            command=[sys.executable,str(ROOT/'scripts/run_living_clearing.py'),
                     '--output',str(folder),'--port',str(v['port']),
                     '--minutes',str(spec.get('minutes',5)),
                     '--calls-per-actor',str(spec.get('calls_per_actor',0)),
                     '--serial-ms',str(v['serial_ms']),
                     '--scenario',str(inputs/'scenario.json'),'--controllers',str(inputs/'controllers.json'),
                     '--implementation',v['implementation'],'--start-gate',str(out/'start')]
            if v.get('recovery',False):command.append('--recovery')
            job=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
            jobs.append((job,log,folder))
            report['variants'].append(dict(id=v['id'],pid=job.pid,url=f"http://127.0.0.1:{v['port']}",serial_ms=v['serial_ms'],
                                          implementation_manifest_hash=digest(Path(v['implementation'])/'implementation.json'),
                                          inputs={key:digest(inputs/(key+'.json')) for key in ('scenario','controllers')}))
            # Old frozen hosts use millisecond database names. Finish initialization
            # before starting the next host; all world clocks still share the gate.
            ready_deadline=time.monotonic()+100
            while not (folder/'ready.json').exists():
                if stop or job.poll() is not None or time.monotonic()>ready_deadline:
                    raise RuntimeError(f"Variant {v['id']} failed before readiness; inspect its log")
                time.sleep(.25)
        write(out/'batch.json',report)
        deadline=time.monotonic()+180
        while not all((folder/'ready.json').exists() for _,_,folder in jobs):
            if stop or any(job.poll() is not None for job,_,_ in jobs) or time.monotonic()>deadline:
                raise RuntimeError('A variant failed or timed out before the common start; inspect variant logs')
            time.sleep(.25)
        databases=[json.loads((folder/'active.json').read_text())['db'] for _,_,folder in jobs]
        if len(set(databases))!=len(databases):raise RuntimeError('Variants must have distinct authority databases')
        (out/'start').touch();report.update(phase='running',started_at=time.time());write(out/'batch.json',report)
        print('Parallel experiments started: '+', '.join(v['url'] for v in report['variants']),flush=True)
        deadline=time.monotonic()+spec.get('minutes',5)*60+60
        while any(job.poll() is None for job,_,_ in jobs):
            if stop or time.monotonic()>deadline:raise RuntimeError('Batch cancelled or exceeded its supervision deadline')
            if any(job.poll() not in (None,0) for job,_,_ in jobs):raise RuntimeError('A variant failed; stopping peers')
            time.sleep(1)
        if any(job.returncode for job,_,_ in jobs):raise RuntimeError('A variant failed')
        for job,log,folder in jobs:
            log.close();summarize(folder)
        comparison=[]
        for v,(_,_,folder) in zip(variants,jobs):
            result=json.loads((folder/'LIVE_RESULT.json').read_text())
            players=[p for a in result['arenas'] for p in a['players']]
            calls=[c for p in players for c in p['calls']]
            comparison.append(dict(variant=v['id'],run=result['run'],seconds=result['seconds'],updates=result['updates'],
                                   alive=sum(p['alive'] for p in players),population=len(players),calls=len(calls),
                                   completed_calls=sum(c['phase']=='completed' for c in calls),
                                   output_errors=sum(bool(c.get('error') or c.get('provider_error')) for c in calls),
                                   engine_errors=len(result['engine_errors']),scope_violations=len(result['scope_violations']),
                                   details=str(folder/'LIVE_RESULT.json')))
        write(out/'comparison.json',comparison)
        report.update(phase='completed',finished_at=time.time(),comparison=comparison)
        print(json.dumps(comparison,indent=2),flush=True)
    except Exception as error:
        report.update(phase='failed',error=str(error),finished_at=time.time())
        raise
    finally:
        for job,_,_ in jobs:
            if job.poll() is None:job.terminate()
        for job,log,_ in jobs:
            try:job.wait(timeout=40)
            except subprocess.TimeoutExpired:job.kill();job.wait(timeout=5)
            log.close()
        write(out/'batch.json',report)


if __name__=='__main__':main()
