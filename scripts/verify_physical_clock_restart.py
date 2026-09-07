#!/usr/bin/env python3
"""Verify a completed, paused experiment after restarting its retained world service.

Writes separate recovery evidence; never rewrites original workload results.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request

from benchmark_controller_boundary import CLI, run, write
from owner_snapshot import export_world, export_audit_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    root=args.directory.resolve()
    out=root/'physical-restart'
    out.mkdir(exist_ok=False)
    service=next(s for s in json.loads((root/'services.json').read_text()) if s['kind']=='world')
    before=json.loads((root/'final-world.json').read_text())
    audit_before=(root/'final-audit.jsonl').read_bytes()
    state=json.loads(run('podman','inspect',service['name']))[0]['State']
    if state['Running']:
        raise RuntimeError('requires a stopped experiment service')
    result={}
    started=False
    try:
        run('podman','start',service['name'])
        started=True
        for _ in range(100):
            try:
                with urllib.request.urlopen(service['url']+'/v1/metrics',timeout=1):
                    break
            except Exception:
                time.sleep(.1)
        else:
            raise RuntimeError('service readiness timeout')
        def cli(*arguments):
            return run(str(CLI),'--config-path',service['cli_config'],*arguments,
                '--server',service['url'],'--no-config')
        def call(name,*arguments):
            return cli('call',service['database'],name,*[json.dumps(a) for a in arguments],'-y')
        clocks=json.loads(cli('sql',service['database'],'SELECT * FROM sim_client_clock','--format','json'))[0]
        names=[f['name']['some'] for f in clocks['schema']['elements']]
        rows=[dict(zip(names,row)) for row in clocks['rows']]
        if not rows or any(not row['paused'] for row in rows):
            raise RuntimeError('experiment was not paused')
        after=export_world(call,before['run'])
        audit=export_audit_json(call,before['run'],after['next_event'])
        audit_bytes=('\n'.join(audit)+'\n').encode()
        result.update(world_equal=before==after,audit_bytes_equal=audit_before==audit_bytes,
            events=len(audit),sha256=hashlib.sha256(audit_bytes).hexdigest(),
            maintenance_ms=after['timing'].get('maintenance_ms'))
        write(out/'world.json',after)
        if not result['world_equal'] or not result['audit_bytes_equal']:
            raise RuntimeError('restart changed the paused world or exact audit')
    except Exception as error:
        result['error']=str(error)
    finally:
        if started:
            run('podman','stop','--time','30',service['name'],timeout=40)
            state=json.loads(run('podman','inspect',service['name']))[0]['State']
            write(out/'stop.json',state)
            result['shutdown_exit_code']=state['ExitCode']
        write(out/'result.json',result)
    if result.get('error') or result.get('shutdown_exit_code')!=0:
        raise SystemExit(json.dumps(result))
    print(json.dumps(result))


if __name__=='__main__':
    main()
