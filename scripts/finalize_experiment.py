#!/usr/bin/env python3
"""Capture immutable authority evidence from a completed, paused experiment."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from experiment_artifacts import ROOT, write
from summarize_arena_matrix import summarize

def finalize(out):
    pilot=json.loads((out/'pilot.json').read_text());active=json.loads((out/'active.json').read_text());run=active['run']
    if pilot['phase']!='completed' or not re.fullmatch(r'sim-[a-zA-Z0-9-]+',run):raise ValueError('Expected completed experiment')
    target=out/run/'final-snapshot.json'
    if target.exists():raise ValueError('Final capture already exists')
    def sql(query):
        result=subprocess.run([str(Path.home()/'.local/share/spacetime/bin/2.7.1/spacetimedb-cli'),'--config-path',str(ROOT/'.local/credentials/bevy-cli.toml'),
            'sql',active['db'],query,'--server',active['server'],'--no-config','--format','json'],capture_output=True,text=True,check=True)
        return json.loads(result.stdout)[0]['rows']
    clock=sql(f"SELECT paused FROM sim_client_clock WHERE run = '{run}'")
    if not clock or clock[0][0] is not True:raise ValueError('Authority clock is not paused')
    for _ in range(3):
        w=json.loads(sql(f"SELECT state FROM sim_run WHERE id = '{run}'")[0][0])
        events=sorted((json.loads(row[0]) for row in sql(f"SELECT json FROM sim_audit WHERE run = '{run}'")),key=lambda e:e['id'])
        after=json.loads(sql(f"SELECT state FROM sim_run WHERE id = '{run}'")[0][0])
        if w==after:break
    else:raise ValueError('Authority changed during final capture')
    write(target,dict(world=w,events=events))
    old=out/'LIVE_RESULT.json'
    if old.exists():(out/'pre-final-capture-result.json').write_bytes(old.read_bytes())
    summarize(out)
    write(out/'final-capture.json',dict(path=str(target),time_ms=w['timing']['time_ms'],next_event=w['next_event'],clock_paused=True,
          note='Read directly from the paused authority after controller shutdown. Supersedes asynchronous host-export summaries.'))
    print('Final authority capture:',out)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);finalize(p.parse_args().output.resolve())
