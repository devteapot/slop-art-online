#!/usr/bin/env python3
"""Prepare, or explicitly execute, a bounded no-model universal-law authority fixture.

Default mode prepares files and makes NO authority connection. --execute requires
an already published local --active database whose clocks are all paused. The
caller must also wait for the live 022 campaign to finish before executing.
"""
import argparse, copy, hashlib, json, re, signal, subprocess, time
from pathlib import Path

PREFIX='sim-universal-persistence-probe-'
SOURCE='// EXPLICIT_UNIVERSAL_PERSISTENCE_PROBE\nfn cost(skill) { 1 }'

def write(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,separators=(',',':'))+'\n')
    temporary.replace(path)

def fixture(root,death_ms):
    s=copy.deepcopy(json.loads((root/'scenarios/law-local-borders.json').read_text()))
    s.update(name='Explicit no-model taught universal capability and fixed-death persistence probe',
             max_ticks=(death_ms+25000+2499)//2500,weather=None,starting_behaviors={},knowledge={},
             disturbances=[dict(at_ms=death_ms,kind='damage',actor=2,amount=100)])
    assert [p['id']for p in s['players']]==[1,2,3,4]
    for p in s['players']:
        p.update(controller='human',position=84 if p['id']in[1,2]else 88,food=20,hunger=10,energy=100,health=100)
    for site in s['sites']:site.update(food=12,hazard=0,shelter=12)
    s['infrastructure']['bodies']={}
    for region in s['society']['regions']:
        region['territorial_editors']=[1] if region['id']=='west' else []
    for arena in s.get('arenas',[]):arena['controllers']={str(a):'external'for a in arena['actors']}
    assert all(2 not in r['territorial_editors']and 3 not in r['territorial_editors']for r in s['society']['regions'])
    return s

def audit(snapshot,capability,participant,death_ms):
    w,events=snapshot['world'],snapshot['events'];by={e['id']:e for e in events}
    assert [e['id']for e in events]==list(range(1,w['next_event'])),'noncontiguous authority audit'
    assert not any(e['kind']in['model_request','model_result','script_error','script_tick_failed']for e in events)
    assert capability['setup_completed']and participant['participant_checks_pass'],'participant setup/persistence incomplete'
    data=capability['evidence'];artifact=data['artifact'];code=data['code'];proof_id=data['learner_proof']
    assert artifact['source']==SOURCE
    teacher=next(p for p in w['players']if p['id']==1);learner=next(p for p in w['players']if p['id']==2)
    held={h['record']['id']:h for h in learner['knowledge']}
    assert code in held and proof_id in held and data['teacher_proof']not in held
    assert held[code]['record']['law_program']==artifact and held[code]['interpreted_source']is not None
    proof=held[proof_id]['record']['law_experiment']
    assert held[proof_id]['interpreted_source']is not None and proof['operator']==2 and proof['scope']=={'kind':'universal'}
    assert proof['program_hash']==artifact['source_hash']and proof['successful']and proof['paid_quanta']==3
    assert proof['cases']==[dict(hook='cost',input='gather',expected=1)]
    assert proof['binding']['digest']==data['universal_binding_tested']
    assert 'AUTHOR_PRIVATE_CASE'not in json.dumps(learner['knowledge'])
    taught=[e for e in events if e['kind']=='knowledge_taught'and e['actor']==1 and e['data'].get('record')==code]
    assert taught,'no actual physical code teaching event'
    teaching_attempts=[e for e in events if e['kind']=='skill_attempt'and e['actor']==1 and e['data']['action']['skill']=='teach']
    assert len(teaching_attempts)==1 and teaching_attempts[0]['data']['action']['record']==code and teaching_attempts[0]['data']['action']['target']==2
    staged=[e for e in events if e['kind']=='law_edit_staged'and e['data']['reference']['scope']=={'kind':'universal'}]
    active=[e for e in events if e['kind']=='law_activated'and e['data']['reference']['scope']=={'kind':'universal'}]
    assert len(staged)==len(active)==1
    st,ac=staged[0],active[0]
    assert st['actor']==ac['actor']==2 and st['data']['reference']==ac['data']['reference']=={'scope':{'kind':'universal'},'revision':1}
    assert st['data']['record']==code and st['data']['experiment_record']==proof_id
    assert st['data']['source_hash']==ac['data']['source_hash']==artifact['source_hash']
    assert st['data']['expected_binding']==proof['binding']and st['data']['expected_revision']==0
    assert st['id']in ac['parents']
    local_active=[e for e in events if e['kind']=='law_activated'and e['data']['reference']=={'scope':{'kind':'territory','region':'west'},'revision':1}]
    assert len(local_active)==1 and local_active[0]['actor']==1 and local_active[0]['data']['source_hash']==artifact['source_hash']
    assert data['baseline_east']['result']['source']<local_active[0]['id']<data['east_after_local_only']['attempt']['source']<st['id']
    denial=[]
    for failure in events:
        if failure['kind']!='skill_result'or failure['actor']!=2 or failure['data'].get('status')!='failed':continue
        if 'matching personally assessed law experiment'not in failure['data'].get('reason',''):continue
        attempt=by[failure['parents'][0]];op=attempt['data']['action']['infrastructure']
        assert attempt['kind']=='skill_attempt'and attempt['actor']==2 and op['op']=='install_law'
        assert op['scope']=={'kind':'universal'}and op['record']==code and op['experiment_record']is None
        assert op['expected_revision']==0 and op['expected_binding']==proof['binding']['digest']
        assert failure['id']<st['id']
        denial.append(dict(attempt=attempt,result=failure))
    assert denial,'no actual denied universal install before own proof'
    assert w['laws']['active']['universal']==1
    installed=w['laws']['history']['universal']['1']
    assert installed['author']==2 and installed['artifact']==artifact
    deaths=[e for e in events if e['kind']=='death'and e['actor']==2]
    assert len(deaths)==1 and learner['health']==0
    death=deaths[0];damage=by[death['parents'][0]]
    assert damage['kind']=='damage'and damage['actor']==2 and damage['data']['cause_kind']=='scenario_disturbance'
    disturbances=[e for e in events if e['kind']=='scenario_disturbance'and e['id']in damage['parents']]
    assert len(disturbances)==1 and disturbances[0]['data']['scheduled_time_ms']==death_ms
    assert death['data']['time_ms']>=death_ms and ac['data']['time_ms']<death['data']['time_ms']
    jobs=[]
    for owner,key,kind in[(1,'teacher_paid_job','territory'),(2,'learner_paid_practice','universal')]:
        job=data[key]['job']['id']
        submitted=[e for e in events if e['kind']=='compute_submitted'and e['actor']==owner and e['data']['job']==job]
        quantum=[e for e in events if e['kind']=='compute_quantum'and e['actor']==owner and e['data']['job']==job]
        complete=[e for e in events if e['kind']=='compute_completed'and e['actor']==owner and e['data']['job']==job]
        retrieved=[e for e in events if e['kind']=='compute_retrieved'and e['actor']==owner and e['data']['job']==job]
        assert len(submitted)==len(complete)==1 and len(quantum)==3 and retrieved
        assert [e['data']['progress']for e in quantum]==[1,2,3]
        assert submitted[0]['data']['scope']['kind']==kind and submitted[0]['data']['required_quanta']==3
        assert submitted[0]['data']['new_program']==(owner==1)
        assert complete[0]['data']['successful']and sum(e['data']['electricity']for e in quantum)==6
        assert sum(e['data']['water_consumed']for e in quantum)==3
        jobs.append(dict(owner=owner,job=job,submitted=submitted[0],quanta=quantum,completed=complete[0],retrieved=retrieved))
    assert max(x['result']['id']for x in denial)<jobs[1]['submitted']['id']
    phases=[('east-baseline',data['baseline_east'],4,False),('east-after-local-only',data['east_after_local_only'],4,False),
            ('east-after-universal',data['east_after_universal'],1,True),('east-after-death',participant['persistence_evidence']['east_effect'],1,True)]
    effects=[]
    for name,evidence,expected,universal in phases:
        attempt=by[evidence['attempt']['source']];result=by[evidence['result']['source']]
        assert attempt['actor']==result['actor']==3 and attempt['kind']=='skill_attempt'and result['kind']=='skill_result'
        assert attempt['id']in result['parents']and result['data']['status']=='completed'and result['data']['skill']=='gather'
        assert attempt['data']['before']['position']==result['data']['after']['position']==88
        assert attempt['data']['before']['energy']-result['data']['after']['energy']==expected
        overlays=attempt['data']['law_binding']['overlays']
        assert overlays==([{'scope':{'kind':'universal'},'revision':1}]if universal else[])
        if name=='east-after-death':assert attempt['id']>death['id']and attempt['data']['time_ms']>death['data']['time_ms']
        effects.append(dict(phase=name,cost=expected,attempt=attempt,result=result))
    assert w['initial'].get('knowledge',{})=={} and w['initial'].get('starting_behaviors',{})=={}
    for region in w['initial']['society']['regions']:assert 2 not in region['territorial_editors']and 3 not in region['territorial_editors']
    return dict(all_pass=True,model_calls=0,autonomous_evidence=False,actual_teaching=taught,paid_jobs=jobs,
                staged=st,activated=ac,local_activation=local_active[0],denial_without_own_proof=denial,actual_installer_death=death,authored_disturbance=disturbances[0],effects=effects,
                final_universal_revision=installed,full_world_and_events_contiguous=True,
                meaning='Explicit observer tooling demonstrated capability/persistence through actual participant actions; this is not autonomous discovery evidence.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--implementation',type=Path,default=Path.cwd())
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--active',type=Path)
    parser.add_argument('--probe-binary',type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--cli',type=Path,default=Path.home()/'.local/share/spacetime/bin/2.7.1/spacetimedb-cli')
    parser.add_argument('--cli-config',type=Path)
    args=parser.parse_args();root=args.implementation.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    death_ms=180000;scenario=fixture(root,death_ms);write(out/'scenario.json',scenario)
    manifest=dict(mode='execution'if args.execute else'prepared_only',model_calls=0,source_declared_in_probe=SOURCE,
        fixed_installer=2,fixed_installer_death_ms=death_ms,setup_cutoff_ms=120000,final_ceiling_ms=200000,
        wall_ceiling_seconds=300,teacher_grant='actor1 west only',learner_grants=[],witness3_grants=[],
        initial_knowledge_empty=True,initial_laws_empty=True,production_core_modified=False,
        final_checks='exact paid own universal proof, actual teaching, denial before proof, local-only east cost4, universal east cost1, actual installer death, postdeath east cost1')
    write(out/'prospective-manifest.json',manifest)
    if not args.execute:
        print(json.dumps(dict(prepared=True,authority_connections=0,output=str(out))));return
    assert args.active and args.probe_binary and args.probe_binary.is_file(),'execute needs active authority and separately built additive probe'
    active=json.loads(args.active.read_text());server,db=active['server'],active['db']
    assert server.startswith('http://127.0.0.1:')and re.fullmatch(r'[a-zA-Z0-9_-]+',db)
    run=PREFIX+str(time.time_ns());config=dict(server=server,database=db,run=run,output=str(out),
        credential_dir=str(out/'credentials'),cli=str(args.cli.resolve()),cli_config=str((args.cli_config or root/'.local/credentials/bevy-cli.toml').resolve()),
        setup_deadline_ms=120000,death_ms=death_ms,finish_ms=200000,wall_timeout_seconds=300)
    (out/'credentials').mkdir(mode=0o700);write(out/'config.json',config)
    report=dict(run=run,database=db,original_active_run=active.get('run'),all_pass=False,created=False,own_run_paused=False,cleanup_errors=[],model_calls=0)
    process=None
    def cli(verb,*values):
        response=subprocess.run([str(args.cli),'--config-path',config['cli_config'],verb,db,*values,'--server',server,'--no-config'],capture_output=True,text=True,timeout=30)
        if response.returncode:raise RuntimeError(f'owner {verb} failed (output suppressed)')
        return response.stdout
    def call(name,*values):return cli('call',name,*map(json.dumps,values),'-y')
    def rows(query):return json.loads(cli('sql',query,'--format','json'))[0]['rows']
    def capture():
        worlds=rows(f"SELECT state FROM sim_run WHERE id = '{run}'");assert len(worlds)==1
        world=json.loads(worlds[0][0]);events=sorted((json.loads(x[0])for x in rows(f"SELECT json FROM sim_audit WHERE run = '{run}'")),key=lambda e:e['id'])
        result=dict(world=world,events=events);write(out/'snapshot.json',result);return result
    def interrupt(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGINT,interrupt)
    try:
        assert all(r[1]for r in rows('SELECT run, paused FROM sim_client_clock')),'another run is active in supplied database'
        call('sim_create_participant',run,json.dumps(scenario,separators=(',',':')));report['created']=True
        call('sim_setup_client_clock',run,'live_fixture');call('sim_operator_clock',run,50,True)
        with(out/'probe.log').open('w')as log:
            process=subprocess.Popen([str(args.probe_binary.resolve()),str(out/'config.json')],cwd=root,stdout=log,stderr=log)
            try:report['probe_exit_code']=process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                process.terminate();process.wait(timeout=10);raise RuntimeError('prospective300s wall ceiling reached')
        call('sim_operator_pause',run);report['own_run_paused']=True;snapshot=capture()
        capability=json.loads((out/'capability-result.json').read_text());participant=json.loads((out/'participant-result.json').read_text())
        report['setup_completed']=capability.get('setup_completed',False)
        report['universal_activated']=snapshot['world']['laws']['active'].get('universal',0)>0
        report['installer_death_observed']=any(e['kind']=='death'and e['actor']==2 for e in snapshot['events'])
        validation=audit(snapshot,capability,participant,death_ms);write(out/'authority-validation.json',validation)
        assert report['probe_exit_code']==0
        report.update(all_pass=True,setup_completed=True,universal_activated=True,installer_death_observed=True,
                      snapshot_sha256=hashlib.sha256((out/'snapshot.json').read_bytes()).hexdigest())
    except BaseException as error:
        report['error']=f'{type(error).__name__}: {error}'
    finally:
        if process is not None and process.poll()is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        if report['created']:
            try:
                call('sim_operator_pause',run);report['own_run_paused']=True
                if not(out/'snapshot.json').exists():
                    snapshot=capture();report['universal_activated']=snapshot['world']['laws']['active'].get('universal',0)>0
                    report['installer_death_observed']=any(e['kind']=='death'and e['actor']==2 for e in snapshot['events'])
            except Exception as e:report['cleanup_errors'].append(f'pause/capture: {e}')
        if(out/'identities.json').exists():
            for identity in json.loads((out/'identities.json').read_text()):
                try:call('sim_revoke_client',identity)
                except Exception as e:report['cleanup_errors'].append(f'revoke: {e}')
        try:
            clocks=rows('SELECT run, paused FROM sim_client_clock')
            report['all_database_clocks_paused']=all(r[1]for r in clocks)
            report['remaining_own_grants']=len(rows(f"SELECT actor FROM sim_client_access WHERE run = '{run}'"))
            write(out/'cleanup-verification.json',dict(clocks=clocks,remaining_own_grants=report['remaining_own_grants']))
            if not report['all_database_clocks_paused']or report['remaining_own_grants']!=0:
                report['cleanup_errors'].append('final paused-clock/own-grant verification failed')
        except Exception as e:report['cleanup_errors'].append(f'cleanup verification: {e}')
        if report['cleanup_errors']:report['all_pass']=False
        write(out/'result.json',report)
    print(json.dumps(report))
    if not report['all_pass']:raise SystemExit(1)
if __name__=='__main__':main()
