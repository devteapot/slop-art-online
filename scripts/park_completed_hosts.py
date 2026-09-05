#!/usr/bin/env python3
"""Replace this project's completed experiment hosts with lightweight archive viewers.

The original authority module/database and snapshots stay unchanged. No model
configuration is supplied and the viewer neither advances nor re-exports worlds.
"""
import hashlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[1]
def main():
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            exe=(proc/'exe').resolve();cwd=(proc/'cwd').resolve()
            if exe.name.removesuffix(' (deleted)')!='sao-dev-client' or not exe.is_relative_to(ROOT):continue
            environment=dict(item.split('=',1) for item in (proc/'environ').read_text().split('\0') if '=' in item)
            if environment.get('BEVY_DEV_ARCHIVE_ONLY'):continue
            out=Path(environment.get('BEVY_DEV_OUTPUT','output/participant-agent-dev'))
            if not out.is_absolute():out=cwd/out
            active=json.loads((out/'active.json').read_text());snapshot=out/active['run']/'snapshot.json'
            raw=snapshot.read_bytes();state=json.loads(raw)
            if not state['world']['stopped']:
                pilot=json.loads((out/'pilot.json').read_text())
                if pilot.get('phase')!='completed' or pilot.get('pause_error'):continue
                import re
                if not re.fullmatch(r'sim-[a-zA-Z0-9-]+',active['run']):continue
                check=subprocess.run([environment.get('SPACETIME_CONTROL_CLI','spacetime'),'--config-path',environment['SPACETIME_CONFIG_PATH'],
                    'sql',active['db'],f"SELECT paused FROM sim_client_clock WHERE run = '{active['run']}'",'--server',active['server'],'--no-config','--format','json'],capture_output=True,text=True,check=True)
                if json.loads(check.stdout)[0]['rows']!=[[True]]:continue
            env=os.environ.copy()
            for key in ('SPACETIME_CLI','SPACETIME_CONTROL_CLI','SPACETIME_CONFIG_PATH','BEVY_DEV_PORT','BEVY_DEV_BIND','BEVY_DEV_PUBLIC_URL','BEVY_DEV_CREDENTIAL_DIR'):
                if key in environment:env[key]=environment[key]
            env.update(BEVY_DEV_OUTPUT=str(out),BEVY_DEV_RESUME_ACTIVE=str(out/'active.json'),BEVY_DEV_ARCHIVE_ONLY='1')
            env.pop('NPC_REASONING_CONFIG',None);env.pop('BEVY_DEV_CONTROLLERS',None)
            os.kill(int(proc.name),signal.SIGTERM)
            deadline=time.monotonic()+5
            while proc.exists() and time.monotonic()<deadline:time.sleep(.05)
            with (out/'viewer-host.log').open('a') as log:
                viewer=subprocess.Popen([str(ROOT/'target/debug/sao-dev-client')],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            deadline=time.monotonic()+10
            while True:
                try:
                    with urlopen(active['url'],timeout=1) as reply:assert reply.status==200
                    break
                except Exception:
                    if viewer.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Archive viewer did not start: '+str(out))
                    time.sleep(.1)
            assert hashlib.sha256(snapshot.read_bytes()).digest()==hashlib.sha256(raw).digest(), 'Original snapshot changed'
            (out/'viewer-host.json').write_text(json.dumps(dict(pid=viewer.pid,mode='archive_only',authority_unchanged=True,snapshot_sha256=hashlib.sha256(raw).hexdigest()),indent=2)+'\n')
            print('Archive viewer:',active['url'],active['run'],flush=True)
        except (FileNotFoundError,PermissionError,ProcessLookupError):continue
if __name__=='__main__':main()
