#!/usr/bin/env python3
"""Audit physical-law experiments, current authority, activation and scoped consequences."""
import argparse
import collections
import contextlib
import hashlib
import io
import json
from pathlib import Path

from summarize_arena_matrix import classify_execution_events
from summarize_knowledge import analyze as analyze_knowledge, reference
from summarize_research import analyze as analyze_research, summarize as summarize_research


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def law_hash(artifact):
    return digest(['scoped-law-v1',artifact['interface_version'],artifact['source'],artifact['hooks']])


def binding_hash(binding):
    return digest([binding['base'],binding['overlays'],binding['disabled']])


def work_hash(data):
    return digest([data['scope'],data['binding'],data['program_record'],data['cases'],data.get('source_records',[])])


def contains_float(value):
    if isinstance(value,float):return True
    if isinstance(value,dict):return any(contains_float(v) for v in value.values())
    if isinstance(value,list):return any(contains_float(v) for v in value)
    return False


HOOKS={'metabolism','aftermath','food_renewal','cost','action_interval_ms','on_damage',
       'visible','observation','reflection','population_costs','needs_care','development',
       'research_authoring','research_use','authorize_law_edit','authorize_effect'}


def valid_output(hook,value):
    def number(v,low,high):return type(v) is int and low<=v<=high
    def obj(numbers,bools=()):
        return isinstance(value,dict) and set(value)==set(numbers)|set(bools) and all(
            number(value[k],*bounds) for k,bounds in numbers.items()) and all(type(value[k]) is bool for k in bools)
    if hook in ('cost','food_renewal'):return number(value,0,1000000)
    if hook=='action_interval_ms':return number(value,1,3600000)
    if hook=='metabolism':return obj(dict(hunger=(0,100),fear=(0,100)))
    if hook=='aftermath':return isinstance(value,dict) and {'starvation','hazard'}<=set(value)<={'starvation','hazard','cold','power_depletion'} and all(number(v,0,1000000) for v in value.values())
    if hook=='on_damage':return obj(dict(health=(0,100),fear=(0,100),caution=(0,100),confidence=(0,100)),('learn_danger','interrupt','dead')) and value['dead']==(value['health']==0)
    if hook=='observation':return obj(dict(food=(0,1000000),shelter=(0,1000000)),('buildable',))
    if hook=='reflection':return obj(dict(caution=(0,100),trust=(-100,100),confidence=(0,100)))
    if hook=='population_costs':
        bounds={k:(1,3600000) for k in ('offer_ms','reproduction_ms','fabrication_ms','care_ms','practice_ms')}
        bounds.update({k:(1,100) for k in ('parent_food','parent_energy','fabrication_food','fabrication_energy','care_energy','nutrition','practice_energy')})
        return obj(bounds)
    return hook in HOOKS and type(value) is bool


def scope_key(scope):
    return 'universal' if scope['kind']=='universal' else 'territory:'+scope['region']


def in_region(world,region,position):
    grid=world['initial'].get('map') or {}
    width=grid.get('width',0);height=grid.get('height',0)
    if not width or position is None or not 0<=position<width*height:return False
    bounds=region['bounds'];x,y=position%width,position//width
    return bounds['x']<=x<bounds['x']+bounds['width'] and bounds['y']<=y<bounds['y']+bounds['height']


def regions_at(world,position):
    regions=(world['initial'].get('society') or {}).get('regions',[])
    # Match the engine's weakest-first overlay order.
    applicable=sorted([r for r in regions if in_region(world,r,position)],key=lambda r:r['id'],reverse=True)
    return sorted(applicable,key=lambda r:(r.get('priority',0),-r['bounds']['width']*r['bounds']['height']))


def scope_here(world,scope,position):
    return scope['kind']=='universal' or any(r['id']==scope['region'] for r in regions_at(world,position))


def local_grant(world,actor,scope,position):
    return scope['kind']=='territory' and any(r['id']==scope['region'] and
        actor in r.get('territorial_editors',[]) for r in regions_at(world,position))


def analyze(world,events):
    events=sorted(events,key=lambda e:e['id']);index={e['id']:e for e in events}
    research=analyze_research(world,events);knowledge=analyze_knowledge(world,events)
    classified_engine_errors,law_authorization_denials=classify_execution_events(events)
    records=knowledge['records'];violations=[];unverified_hashes=[]
    jobs={};completed={};held=collections.defaultdict(set);assessed={};proofs=collections.defaultdict(list)
    inspections={};pending={};active={};history={};faults=[];deaths={}
    positions={p['id']:p.get('position') for p in world['initial']['players']}
    staged=[];activated=[];rejected=[];reads=[];law_jobs=[];crossings=[];outcomes=[];production=[];effect_rejections=[]
    citations=collections.defaultdict(list)
    assessment_receipts=collections.defaultdict(list)
    for event in events:
        if event['kind']=='knowledge_interpreted':
            data=event['data']
            key=(event.get('actor'),data.get('record'),data.get('source'),data.get('interpretation'))
            assessment_receipts[key].append(event['id'])
    for citation in knowledge['accepted_citations']:
        # Knowledge audit admits own-record inspection citations only with an
        # exact source and matching historical assessment receipt; installed-law
        # reads never grant a held-code assessment. Preserve pre-receipt rules
        # for derived assertions on ordinary acquisition reports as well.
        key=(citation.get('actor'),citation['record'],citation['source'],citation.get('interpretation'))
        interpreted=any(citation['source']<receipt<citation['event']
                        for receipt in assessment_receipts.get(key,[]))
        if not citation.get('derived_assertion') or interpreted:
            citations[citation['event']].append(citation)
    acquired={a['event']:a for a in knowledge['acquisitions']}
    operator_base_updates=[];periodic_outcomes=[];fault_report_delays=[]
    final_fault_identities=[dict(reference=f['reference'],hook=f['hook']) for f in world.get('laws',{}).get('faults',[])]

    def fail(event,message):violations.append(f"Event {event['id']} {message}")

    def refs_at(position,universal=False):
        refs=[]
        if not universal:
            for region in regions_at(world,position):
                key='territory:'+region['id']
                if key in active:refs.append(dict(scope=dict(kind='territory',region=region['id']),revision=active[key]))
        if 'universal' in active:refs.append(dict(scope=dict(kind='universal'),revision=active['universal']))
        return refs

    def artifact_for(ref):return history.get((scope_key(ref['scope']),ref['revision']),{}).get('artifact')

    def check_binding(event,binding,scope,position,current=True):
        if not isinstance(binding,dict):fail(event,'lacks a complete physical law binding');return
        try:
            if binding_hash(binding)!=binding.get('digest'):fail(event,'law binding hash does not bind its exact references')
        except (KeyError,TypeError,ValueError):fail(event,'contains an invalid binding payload');return
        if scope['kind']=='universal' and any(r['scope']['kind']!='universal' for r in binding.get('overlays',[])):
            fail(event,'universal authority binding includes a territorial self-promotion')
        if current and binding.get('overlays')!=refs_at(position,scope['kind']=='universal'):
            fail(event,'experiment or edit uses a stale or wrongly scoped current binding')
        expected_disabled=[dict(reference=f['reference'],hook=f['hook']) for f in faults
            if f['reference'] in binding.get('overlays',[])]
        disabled=binding.get('disabled',[])
        if current and (any(f not in disabled for f in expected_disabled) or any(f not in final_fault_identities for f in disabled)):
            fail(event,'current binding omits or invents a quarantined hook')
        # Faults can be observed in a binding before the end-of-update flush
        # emits their individual quarantine events. Retain that ordering.
        for identity in disabled:
            if current and identity not in expected_disabled and identity in final_fault_identities:
                fault_report_delays.append(dict(**reference(event),disabled=identity))
        if any(f.get('reference') not in binding.get('overlays',[]) for f in disabled):
            fail(event,'binding disables a hook from outside its selected overlays')
        if any(set(f)!={'reference','hook'} for f in binding.get('disabled',[])):
            fail(event,'binding exposes fault text or unsupported private fields')

    def changed_authorization(scope,position,hook='authorize_law_edit'):
        refs=refs_at(position,scope['kind']=='universal' and hook=='authorize_law_edit')
        for ref in reversed(refs):
            artifact=artifact_for(ref)
            if artifact and hook in artifact['hooks'] and not any(
                f['reference']==ref and f['hook']==hook for f in faults):
                return ref
        return None

    def move_evidence(event,new_position):
        actor=event.get('actor');old=positions.get(actor)
        if old is not None and new_position is not None and old!=new_position:
            before=[r['id'] for r in regions_at(world,old)];after=[r['id'] for r in regions_at(world,new_position)]
            if before!=after:
                crossings.append(dict(**reference(event),departure=old,arrival=new_position,
                    departure_regions=before,arrival_regions=after,
                    departure_active_refs=refs_at(old),arrival_active_refs=refs_at(new_position),
                    evidence='Recorded physical position change; live per-step law selection requires its execution evidence.'))
        if new_position is not None:positions[actor]=new_position

    for event in events:
        kind,data,actor,eid=event['kind'],event['data'],event.get('actor'),event['id']
        key=(data.get('station'),data.get('job'))
        if kind=='script_update_activated':operator_base_updates.append(reference(event))
        if kind=='perception' and data.get('kind')=='knowledge_report':
            acquisition=acquired.get(eid)
            if acquisition:
                rid=acquisition['record'];held[actor].add(rid)
                if records.get(rid,{}).get('law_program'):
                    parents=[index[p] for p in event.get('parents',[]) if p in index]
                    valid=any((p['kind']=='compute_retrieved' and p.get('actor')==actor and p['data'].get('record')==rid)
                        or (p['kind']=='knowledge_taught' and p['data'].get('target')==actor and p['data'].get('record')==rid)
                        or (p['kind']=='knowledge_consulted' and p.get('actor')==actor and p['data'].get('record')==rid) for p in parents)
                    if not valid:fail(event,'receives law source without recorded physical transfer')
        elif kind=='identity_change':
            for citation in citations[eid]:
                rid=citation['record'];assessed[(actor,rid)]=dict(event=eid,source=citation['source'],
                    source_inspected_before=inspections.get((actor,rid)))
                record=records.get(rid,{})
                evidence=record.get('law_experiment')
                if evidence and evidence.get('successful') and evidence.get('operator')==actor and record.get('author')==actor:
                    job_key=(evidence['station'],evidence['job']);completion=completed.get(job_key)
                    if completion and completion['record']['id']==rid and evidence.get('paid_quanta',0)>0:
                        proofs[actor].append(dict(record=rid,interpretation=eid,receipt=citation['source'],
                            completed=completion['event'],scope=evidence['scope'],binding=evidence['binding'],
                            source_hash=evidence['program_hash']))
        elif kind=='compute_submitted' and data.get('experiment_kind')=='law':
            jobs[key]=dict(event=eid,actor=actor,data=data)
            record=data.get('program_record',{});artifact=record.get('law_program') or {}
            scope=data['scope'];position=data.get('location',positions.get(actor))
            if not scope_here(world,scope,position):fail(event,'submits a remote territorial experiment')
            check_binding(event,data.get('binding'),scope,position)
            try:
                if law_hash(artifact)!=artifact.get('source_hash'):fail(event,'law artifact hash does not bind its exact source/hooks')
                if artifact.get('interface_version')!=1 or not 1<=len(artifact['source'].encode())<=8192:
                    fail(event,'law artifact violates its interface/source bounds')
                if artifact['hooks']!=sorted(set(artifact['hooks'])) or not 1<=len(artifact['hooks'])<=8 or not set(artifact['hooks'])<=HOOKS:
                    fail(event,'law artifact has an invalid hook manifest')
                if contains_float([data['cases'],data.get('source_records',[])]):
                    unverified_hashes.append(dict(**reference(event),input_hash=data['input_hash'],
                        reason='Floating-point JSON spelling requires the authority serializer; exact source/binding hashes are still checked.'))
                elif work_hash(data)!=data.get('input_hash'):fail(event,'law input hash does not bind private cases, source copies and binding')
            except (KeyError,TypeError,ValueError):fail(event,'has an invalid law source/hash payload')
            if any(record.get(field) for field in ('program','experiment','law_experiment')):
                fail(event,'portable law source embeds private experimental evidence or another executable kind')
            cases=data.get('cases',[])
            if not 1<=len(cases)<=16 or len(canonical(cases))>32768:
                fail(event,'law case collection exceeds its declared bounds')
            if any(c.get('hook') not in artifact.get('hooks',[]) or len(canonical(c.get('input')))>4096
                or len(canonical(c.get('expected')))>4096 for c in cases):fail(event,'law case does not match the bounded hook manifest')
            for case in cases:
                hook=case.get('hook');value=case.get('input')
                if not valid_output(hook,case.get('expected')):fail(event,'law prediction violates its typed output contract')
                if hook in ('cost','action_interval_ms'):
                    if not isinstance(value,str) or not 1<=len(value.encode())<=48:fail(event,'law case needs a bounded skill-name input')
                elif hook!='observation' and not isinstance(value,dict):fail(event,'law case needs an explicit object input')
            if not set(artifact.get('hooks',[])).issubset({c.get('hook') for c in cases}):fail(event,'law candidate has an untested declared hook')
            own_code_assessment=assessed.get((actor,record.get('id')))
            authoring_override=changed_authorization(scope,position,'research_authoring')
            authoring_proofs=[p for p in research['personal_proofs'].get(str(actor),[]) if
                p['interpretation']<eid and p['kind'] in ('builtin_forecast','prototype','practice')]
            if data.get('new_program'):
                if not local_grant(world,actor,scope,position) and not authoring_proofs and not authoring_override and not operator_base_updates:
                    fail(event,'authors a law without initial local grant or personally assessed paid terminal competence')
                if record.get('author')!=actor or record.get('origin')!=eid:fail(event,'new law source lacks the submitting author and origin')
            elif record.get('id') not in held[actor] or not own_code_assessment:
                fail(event,'practices law source without a personally held interpreted copy')
            law_jobs.append(dict(**reference(event),station=key[0],job=key[1],scope=scope,
                new_program=data.get('new_program'),source_hash=artifact.get('source_hash'),record=record.get('id'),
                current_binding=data.get('binding'),cases=cases,authoring_proofs=authoring_proofs,authoring_override=authoring_override,local_grant=local_grant(world,actor,scope,position),
                code_interpretation=own_code_assessment,source_inspection=inspections.get((actor,record.get('id'))),
                path='Initial local grant or current learned authoring rule' if data.get('new_program') else 'Personally interpreted carried source and paid practice'))
        elif kind=='compute_completed' and data.get('experiment_kind')=='law':
            submitted=jobs.get(key);record=data.get('record',{});evidence=record.get('law_experiment')
            completed[key]=dict(event=eid,record=record)
            if not submitted or not evidence:fail(event,'law completion lacks its request or private experiment');continue
            request=submitted['data'];artifact=request['program_record']['law_program']
            expected=dict(operator=submitted['actor'],station=key[0],job=key[1],scope=request['scope'],
                binding=request['binding'],program_hash=artifact['source_hash'],input_hash=request['input_hash'],
                cases=request['cases'],paid_quanta=request['required_quanta'])
            for field,value in expected.items():
                if evidence.get(field)!=value:fail(event,f'law evidence {field} differs from the exact paid request')
            results=evidence.get('results',[])
            successful=len(results)==len(request['cases']) and all(isinstance(result,dict) and set(result)=={'Ok'}
                and canonical(result['Ok'])==canonical(case['expected']) for result,case in zip(results,request['cases']))
            for result,case in zip(results,request['cases']):
                if isinstance(result,dict) and 'Ok' in result and not valid_output(case['hook'],result['Ok']):
                    fail(event,'successful law result violates its typed output contract')
            if any(not isinstance(r,dict) or set(r) not in ({'Ok'},{'Err'}) for r in results):fail(event,'law result has an invalid success/error envelope')
            if evidence.get('successful')!=successful or data.get('successful')!=successful:
                fail(event,'law success claim does not match all privately predicted cases')
            if data.get('program_record')!=request['program_record'] or record.get('law_program'):
                fail(event,'completed code and private experimental records are not separate exact copies')
        elif kind=='law_inspected':
            rid=data.get('record');ref=data.get('reference');position=data.get('location',positions.get(actor))
            if rid:
                if rid not in held[actor] or not records.get(rid,{}).get('law_program'):fail(event,'inspects a law program that is not personally held')
                else:inspections[(actor,rid)]=eid
            elif ref:
                if not scope_here(world,ref['scope'],position) or active.get(scope_key(ref['scope']))!=ref['revision']:
                    fail(event,'inspects an inaccessible or inactive installed law')
            else:fail(event,'law inspection lacks a held record or installed reference')
            reads.append(dict(**reference(event),record=rid,installed=ref,location=position))
        elif kind=='perception' and data.get('kind')=='law_inspected':
            content=data.get('content',{});rid=content.get('record');ref=content.get('installed')
            if rid:
                expected=records.get(rid,{}).get('law_program')
                if rid not in held[actor] or (actor,rid) not in inspections:fail(event,'receives another person\'s law source')
            elif ref:
                expected=artifact_for(ref)
                if not scope_here(world,ref['scope'],data.get('location',positions.get(actor))):fail(event,'receives source from a remote installed law')
            else:expected=None
            if expected is None or content.get('law_program')!=expected:fail(event,'law source response differs from its physical copy')
        elif kind=='law_edit_staged':
            ref=data['reference'];scope=ref['scope'];skey=scope_key(scope);position=data.get('location',positions.get(actor))
            rid=data.get('record');record=records.get(rid,{});artifact=record.get('law_program')
            binding=data.get('expected_binding')
            check_binding(event,binding,scope,position)
            if not scope_here(world,scope,position):fail(event,'stages an edit outside its accessible territory')
            if skey in pending or data.get('expected_revision')!=active.get(skey,0) or ref['revision']!=active.get(skey,0)+1:
                fail(event,'stages a stale revision or competing edit')
            if rid not in held[actor] or not artifact or artifact.get('source_hash')!=data.get('source_hash'):
                fail(event,'stages source without its exact personally held law record')
            if artifact and artifact.get('hooks')!=data.get('hooks'):fail(event,'staged hook manifest differs from held source')
            if not binding or binding.get('digest')!=data.get('binding'):fail(event,'staged binding digest differs from its complete binding')
            requested=data.get('experiment_record')
            matches=[p for p in proofs[actor] if p['scope']==scope and p['binding']==binding and
                p['source_hash']==data.get('source_hash') and (requested is None or p['record']==requested)]
            grant=local_grant(world,actor,scope,position)
            override=changed_authorization(scope,position)
            default_gate=override is None and not operator_base_updates
            if default_gate and not (grant or matches):
                fail(event,'initial authorization lacks a local grant or own assessed exact-source/current-binding law proof')
            entry=dict(**reference(event),reference=ref,source_hash=data.get('source_hash'),record=rid,
                expected_binding=binding,requested_experiment=requested,own_matching_proofs=matches,
                local_grant=grant,default_authorization=default_gate,authorization_override=override,
                authorization_review='Initial grant/proof rule checked' if default_gate else 'Current changed authorization must be reviewed from its actual executable source; no immutable default proof gate assumed',
                activate_update=data.get('activate_update'),location=position,
                interpretation=assessed.get((actor,rid)),source_inspection=inspections.get((actor,rid)))
            staged.append(entry);pending[skey]=dict(entry=entry,artifact=artifact,event=eid)
        elif kind=='law_activated':
            ref=data['reference'];skey=scope_key(ref['scope']);candidate=pending.pop(skey,None)
            if not candidate or candidate['event'] not in event.get('parents',[]):fail(event,'activates a law without its staged request');continue
            entry=candidate['entry'];artifact=candidate['artifact']
            if ref!=entry['reference'] or data.get('source_hash')!=entry['source_hash'] or data.get('hooks')!=(artifact or {}).get('hooks'):
                fail(event,'activated revision/source differs from its staged request')
            if data.get('effective_update',-1)<entry['activate_update']:fail(event,'activates before its promised next-update boundary')
            check_binding(event,entry['expected_binding'],ref['scope'],entry['location'])
            active[skey]=ref['revision'];history[(skey,ref['revision'])]=dict(artifact=artifact,author=actor,origin=candidate['event'])
            activated.append(dict(**reference(event),reference=ref,source_hash=data['source_hash'],hooks=data['hooks'],
                staged=candidate['event'],effective_update=data['effective_update'],author_dead_at_activation=actor in deaths))
        elif kind=='law_edit_rejected':
            skey=scope_key(data['scope']);candidate=pending.pop(skey,None)
            if not candidate or candidate['event'] not in event.get('parents',[]):fail(event,'rejects an unknown staged law')
            rejected.append(dict(**reference(event),data=data))
        elif kind=='law_hook_quarantined':
            fault=data['fault'];artifact=artifact_for(fault['reference'])
            if not artifact or fault['hook'] not in artifact['hooks']:fail(event,'quarantines an unknown installed hook')
            faults.append(fault)
        elif kind=='death':deaths[actor]=reference(event)
        elif kind=='skill_attempt':
            move_evidence(event,data.get('before',{}).get('position'))
            binding=data.get('law_binding')
            if binding:
                check_binding(event,binding,dict(kind='territory',region='__position__'),positions.get(actor))
        elif kind=='skill_progress':move_evidence(event,data.get('position'))
        elif kind=='skill_result':
            attempt=next((index[p] for p in event.get('parents',[]) if p in index and index[p]['kind']=='skill_attempt'),None)
            if attempt:
                before=attempt['data'].get('before',{});after=data.get('after',{});binding=attempt['data'].get('law_binding')
                if binding and binding.get('overlays'):
                    outcomes.append(dict(**reference(event),attempt=attempt['id'],skill=data.get('skill'),status=data.get('status'),
                        before=before,after=after,pinned_start_binding=binding,
                        active_refs_at_completion=refs_at(after.get('position',positions.get(actor))),
                        note='Before/after spans the invocation; intervening physiology may contribute. Movement can rebind between cells.'))
                move_evidence(event,after.get('position'))
        elif kind in ('needs_change','damage'):
            position=data.get('location',positions.get(actor))
            if data.get('law_binding'):
                check_binding(event,data['law_binding'],dict(kind='territory',region='__position__'),position)
                if data['law_binding'].get('overlays'):
                    periodic_outcomes.append(dict(**reference(event),data=data,location=position))
        elif kind=='resource_produced':
            production.append(dict(**reference(event),data=data,active_refs=refs_at(data.get('location')),
                note='Recorded production is the food-account source; the seed rate is not an immutable ceiling.'))
            if data.get('law_binding'):
                check_binding(event,data['law_binding'],dict(kind='territory',region='__position__'),data.get('location'))
        elif kind in ('script_error','participant_rejected'):
            if data.get('category')=='law_authorization_denied':
                # A rolled-back invocation can carry provisional quarantine
                # identities in its captured validation binding. Validate its
                # exact payload without claiming those faults persisted.
                if data.get('law_binding'):
                    check_binding(event,data['law_binding'],dict(kind='territory',region='__position__'),data.get('validation_position',positions.get(actor)),current=False)
                if data.get('destination_binding'):
                    check_binding(event,data['destination_binding'],dict(kind='territory',region='__position__'),data.get('destination'),current=False)
            if 'law' in str(data).lower() or 'binding' in str(data).lower():effect_rejections.append(dict(**reference(event),data=data))

    actual=world.get('laws',{})
    if actual.get('active',{})!=active:violations.append('Final active law revisions differ from recorded activations')
    final_history={(key,int(rev)):value for key,items in actual.get('history',{}).items() for rev,value in items.items()}
    if set(final_history)!=set(history):violations.append('Final installed law history differs from recorded activations')
    for key,entry in final_history.items():
        expected=history.get(key)
        if expected and (scope_key(entry['reference']['scope'])!=key[0] or entry['reference']['revision']!=key[1] or entry.get('artifact')!=expected['artifact'] or entry.get('author')!=expected['author'] or entry.get('origin')!=expected['origin']):
            violations.append(f'Installed law {key} differs from its exact staged source/author')
    expected_pending={scope_key(p['revision']['reference']['scope']):p for p in actual.get('pending',[])}
    if set(expected_pending)!=set(pending):violations.append('Final pending edits differ from the staged/activated/rejected ledger')
    for skey,value in expected_pending.items():
        expected=pending.get(skey)
        if expected and (value['revision']['artifact']!=expected['artifact'] or value['revision']['origin']!=expected['event'] or
            value['expected_binding']!=expected['entry']['expected_binding'] or value['update']!=expected['entry']['activate_update']):
            violations.append(f'Pending law {skey} changes its source or activation contract')
    if actual.get('faults',[])!=faults:violations.append('Final quarantined hooks differ from authority fault events')
    for station in world.get('infrastructure',{}).get('stations',[]):
        for job in station.get('jobs',[]):
            key=(station['seed']['id'],job['id']);submitted=jobs.get(key)
            if submitted:
                request=submitted['data'];expected=dict(scope=request['scope'],binding=request['binding'],
                    program_record=request['program_record'],cases=request['cases'])
                if job.get('law_work')!=expected or job.get('sources',[])!=request.get('source_records',[]) or job.get('program_work') or job.get('input') is not None:
                    fail(index[submitted['event']],'retained law job differs from its exact private paid request')
    for entry in law_jobs:
        complete=completed.get((entry['station'],entry['job']))
        entry['completion']=complete['event'] if complete else None
        entry['successful']=bool(complete and complete['record'].get('law_experiment',{}).get('successful'))
    installed_after_death=[]
    for activation in activated:
        death=deaths.get(activation['actor']);ref=activation['reference'];skey=scope_key(ref['scope'])
        if death and death['event']>activation['event']:
            later=[e for e in outcomes if e['event']>death['event'] and ref in e['pinned_start_binding'].get('overlays',[])]
            later_periodic=[e for e in periodic_outcomes if e['event']>death['event'] and ref in e['data']['law_binding'].get('overlays',[])]
            installed_after_death.append(dict(activation=activation['event'],author=activation['actor'],death=death,
                reference=ref,still_active=active.get(skey)==ref['revision'],retained_history=(skey,ref['revision']) in final_history,
                later_invocation_outcomes=later,later_periodic_outcomes=later_periodic,
                note='Persistence is conditional on recorded authorship and actual death; retained installation and later use are distinct evidence.'))
    availability={}
    for rid,record in records.items():
        artifact=record.get('law_program')
        if artifact:
            copies=knowledge['final_availability'][rid]
            installed=[dict(scope=entry['reference']['scope'],revision=entry['reference']['revision'],
                active=active.get(key[0])==key[1]) for key,entry in final_history.items()
                if entry['artifact']['source_hash']==artifact['source_hash']]
            availability[rid]=dict(source_hash=artifact['source_hash'],**copies,installed_source_copies=installed,
                note='Installed source is an operative artifact copy, not automatically a new personally held knowledge record.')
    return dict(violations=violations,classified_engine_errors=classified_engine_errors,law_authorization_denials=law_authorization_denials,research_violations=research['violations'],
        infrastructure_violations=research['infrastructure_violations'],copy_audit_violations=research['copy_audit_violations'],
        accounts=research['accounts'],law_experiments=law_jobs,personal_law_proofs={str(a):p for a,p in proofs.items()},
        source_inspections=reads,staged_edits=staged,activated_edits=activated,rejected_edits=rejected,
        quarantined_hooks=faults,bindings_before_quarantine_report=fault_report_delays,law_related_execution_rejections=effect_rejections,
        law_source_review=[dict(record=rid,**r['law_program']) for rid,r in records.items() if r.get('law_program')],
        program_availability=availability,installed_after_author_death=installed_after_death,
        border_crossings=crossings,invocation_outcomes=outcomes,periodic_law_outcomes=periodic_outcomes,recorded_food_production=production,
        unverified_input_hashes=unverified_hashes,operator_base_updates=operator_base_updates,
        disturbances=knowledge['authored_disturbances'],numeric_research_evidence=research['observed_evidence'],
        observed_evidence=dict(law_submissions=len(law_jobs),successful_law_experiments=sum(j['successful'] for j in law_jobs),
            staged=len(staged),activated=len(activated),universal_activations=sum(a['reference']['scope']['kind']=='universal' for a in activated),
            border_crossings=len(crossings),author_death_persistence_candidates=len(installed_after_death)),
        acceptance='Not automatically assigned. Review fresh model-origin source, actual changed behavior, authority semantics and repeated outcomes.',
        limitations='Valid harmful edits are not rejected by this observer. Initial grant/proof checks apply only while the corresponding '
            'authorization source remains unchanged; a participant-authored universal rule may lawfully alter later requirements. '
            'Universal authorization never uses a territorial override. Numeric result predictions establish only the submitted cases. '
            'A local grant can legally install retrieved source despite an unsuccessful experiment. A border crossing, changed active '
            'revision or author death alone is not proof of useful law change or successful research. Source, code interpretation, private '
            'proof interpretation, installation, activation, persistence and later effects remain separate evidence. Law bindings expose '
            'disabled hook identities but must not copy another experiment\'s runtime error text. Observer evidence is never participant input.')


def summarize(out):
    out=Path(out).resolve();upstream_error=None
    try:
        with contextlib.redirect_stdout(io.StringIO()):research=summarize_research(out)
    except (Exception,SystemExit) as error:
        upstream_error=str(error);retained=out/'RESEARCH_RESULT.json'
        if not retained.is_file():raise
        research=json.loads(retained.read_text())
    snapshot=json.loads(Path(research['source']).read_text());result=analyze(snapshot['world'],snapshot['events'])
    for field in ('run','seconds','source','source_sha256','model_calls','reported_tokens','engine_errors',
                  'scope_violations','conservation_violations','base_check_failures'):result[field]=research[field]
    result['upstream_error']=upstream_error
    (out/'LAW_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('run','observed_evidence','violations','research_violations',
        'infrastructure_violations','copy_audit_violations','acceptance')},indent=2))
    if upstream_error or any(result[k] for k in ('violations','research_violations','infrastructure_violations','copy_audit_violations')):
        raise SystemExit('Law evidence audit failed; inspect LAW_RESULT.json')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    summarize(parser.parse_args().output)
