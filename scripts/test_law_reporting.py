"""Synthetic observer fixtures only; no model-authored law or live acceptance claim."""
import copy
import unittest

from summarize_arena_matrix import classify_execution_events
from prepare_law_scenarios import VARIANTS,build,make_scenario,validate
from prepare_infrastructure_scenarios import controllers
from summarize_laws import analyze,binding_hash,law_hash,work_hash,scope_key,regions_at
from test_research_reporting import Fixture


def territory(region='west'):return dict(kind='territory',region=region)
def universal():return dict(kind='universal')


class LawFixture(Fixture):
    def __init__(self):
        super().__init__()
        for player in self.players:player['position']=0
        self.laws=dict(active={},history={},pending=[],faults=[],reported_faults=0)
        self.updates=0

    def world(self):
        result=super().world()
        result['initial']['players']=[dict(id=a,health=100,position=0) for a in (1,2)]
        result['initial']['map']=dict(width=4,height=2,blocked=[])
        result['initial']['society']=dict(regions=[
            dict(id='west',bounds=dict(x=0,y=0,width=2,height=2),priority=0,territorial_editors=[1]),
            dict(id='east',bounds=dict(x=2,y=0,width=2,height=2),priority=0,territorial_editors=[2])])
        result['laws']=self.laws
        return result

    def binding(self,scope,position=0):
        refs=[]
        if scope['kind']!='universal':
            region='west' if position%4<2 else 'east';key='territory:'+region
            if key in self.laws['active']:refs.append(dict(scope=territory(region),revision=self.laws['active'][key]))
        if 'universal' in self.laws['active']:
            refs.append(dict(scope=universal(),revision=self.laws['active']['universal']))
        binding=dict(base=dict(id='law',revision=1),overlays=refs,disabled=[])
        binding['digest']=binding_hash(binding)
        return binding

    def law_work(self,actor,scope,record=None,source='fn cost(s){3}',hooks=None,cases=None,successful=True,auto_bootstrap=True):
        if record is None and scope['kind']=='universal' and auto_bootstrap and not any(
            h['record'].get('experiment',{}).get('kind')=='builtin_forecast' for h in self.players[actor-1]['knowledge'] if h['record'].get('experiment')):
            _,forecast=self.work(actor,'builtin_forecast');self.assess(actor,forecast['id'])
        job_id=max((j['id'] for j in self.infrastructure['stations'][0]['jobs']),default=0)+1
        origin=len(self.events)+1;new=record is None;hooks=hooks or ['cost']
        cases=cases or [dict(hook='cost',input='gather',expected=3)]
        if new:
            artifact=dict(interface_version=1,source=source,hooks=sorted(hooks))
            artifact['source_hash']=law_hash(artifact)
            record=self.record('law-'+str(job_id),actor,origin)
            record['law_program']=artifact
        data=dict(station=1,job=job_id,experiment_kind='law',scope=copy.deepcopy(scope),
            program_record=copy.deepcopy(record),binding=self.binding(scope),cases=copy.deepcopy(cases),
            source_records=[],new_program=new,required_quanta=3,quantum_ms=1000,location=0)
        data['input_hash']=work_hash(data)
        submitted=self.event('compute_submitted',actor,**data)
        for progress in range(1,4):
            self.event('compute_quantum',actor,station=1,job=job_id,progress=progress,
                electricity=2,water=1,quantum_at_ms=(submitted+progress)*1000)
        evidence=dict(operator=actor,station=1,job=job_id,scope=copy.deepcopy(scope),binding=copy.deepcopy(data['binding']),
            program_hash=record['law_program']['source_hash'],input_hash=data['input_hash'],cases=copy.deepcopy(cases),
            results=[{'Ok':c['expected']} if successful else {'Err':'fixture bounded failure'} for c in cases],
            successful=successful,paid_quanta=3)
        report=self.record('law-experiment-'+str(job_id),actor,len(self.events)+1)
        report['law_experiment']=evidence
        self.event('compute_completed',actor,parents=[submitted],station=1,job=job_id,experiment_kind='law',
            program_hash=record['law_program']['source_hash'],input_hash=data['input_hash'],successful=successful,
            record=copy.deepcopy(report),program_record=copy.deepcopy(record))
        for item in (report,record):
            old=any(h['record']['id']==item['id'] for h in self.players[actor-1]['knowledge'])
            received=self.event('compute_retrieved',actor,station=1,job=job_id,record=item['id'],new_copy=not old)
            self.receive(actor,item,received)
        job=dict(id=job_id,owner=actor,source=submitted,input_hash=data['input_hash'],progress=3,required=3,
            cancelled=False,retrieved=True,input=None,program_work=None,sources=[],
            law_work=dict(scope=copy.deepcopy(scope),binding=copy.deepcopy(data['binding']),
                program_record=copy.deepcopy(record),cases=copy.deepcopy(cases)),report=copy.deepcopy(report))
        station=self.infrastructure['stations'][0];station['jobs'].append(job)
        station['seed']['electricity']-=6;station['seed']['materials']['water']-=3
        return record,report

    def teach(self,actor,target,record):
        taught=self.event('knowledge_taught',actor,target=target,record=record['id'],new_copy=True)
        self.receive(target,record,taught,'teaching')

    def inspect_law(self,actor,record):
        event=self.event('law_inspected',actor,record=record['id'],location=self.players[actor-1]['position'])
        self.event('perception',actor,parents=[event],kind='law_inspected',location=self.players[actor-1]['position'],
            content=dict(record=record['id'],law_program=copy.deepcopy(record['law_program'])))

    def install(self,actor,scope,record,experiment=None,activate=True):
        key=scope_key(scope);revision=self.laws['active'].get(key,0)+1;reference=dict(scope=copy.deepcopy(scope),revision=revision)
        binding=self.binding(scope);self.updates+=1;artifact=record['law_program']
        staged=self.event('law_edit_staged',actor,reference=reference,source_hash=artifact['source_hash'],hooks=artifact['hooks'],
            activate_update=self.updates,binding=binding['digest'],expected_binding=binding,expected_revision=revision-1,
            record=record['id'],experiment_record=None if experiment is None else experiment['id'],location=0)
        value=dict(reference=reference,artifact=copy.deepcopy(artifact),author=actor,origin=staged,installed_ms=staged*1000)
        if activate:
            self.event('law_activated',actor,parents=[staged],reference=reference,source_hash=artifact['source_hash'],
                hooks=artifact['hooks'],effective_update=self.updates)
            self.laws['active'][key]=revision;self.laws['history'].setdefault(key,{})[str(revision)]=value
        else:self.laws['pending'].append(dict(update=self.updates,expected_binding=binding,location=0,revision=value))
        return reference

    def erase_law(self,job_id):
        station=self.infrastructure['stations'][0];job=next(j for j in station['jobs'] if j['id']==job_id)
        work=job['law_work'];record=work['program_record']
        self.event('compute_erased',job['owner'],station=1,job=job_id,owner=job['owner'],progress=3,
            record_ids=sorted([record['id'],job['report']['id']]),program_hashes=[record['law_program']['source_hash']],refund=False)
        station['jobs'].remove(job)

    def completed_action(self,actor,skill='gather',destination=None):
        player=self.players[actor-1];before=dict(position=player['position'],energy=80,food=0,hunger=0)
        binding=self.binding(territory(),player['position'])
        attempt=self.event('skill_attempt',actor,action=dict(skill=skill),before=before,law_binding=binding)
        after=dict(before)
        if destination is not None:after['position']=destination;player['position']=destination
        after['energy']=77
        self.event('skill_result',actor,parents=[attempt],status='completed',skill=skill,after=after)


class LawReportingTests(unittest.TestCase):
    def test_derived_law_proof_assessment_requires_matching_prior_authority_receipt(self):
        for corruption in (None, 'missing', 'actor', 'record', 'source', 'interpretation', 'late'):
            with self.subTest(corruption=corruption):
                f=LawFixture();code,_=f.law_work(1,territory())
                f.teach(1,2,code);f.inspect_law(2,code);f.assess(2,code['id'])
                _,own=f.law_work(2,universal(),record=code)
                held=next(h for h in f.players[1]['knowledge'] if h['record']['id']==own['id'])
                receipt=None
                if corruption not in ('missing','late'):
                    receipt=f.event('knowledge_interpreted',2,parents=[held['source']],
                        record=own['id'],source=held['source'],interpretation='fixture interpretation')
                f.assess(2,own['id'])
                f.events[-1]['data']['reflections'][0]['knowledge']=dict(
                    topic='Conditional inference',text='A limited result, not universal proof',location=None,confidence=30)
                if corruption=='late':
                    f.event('knowledge_interpreted',2,parents=[held['source']],
                        record=own['id'],source=held['source'],interpretation='fixture interpretation')
                elif corruption not in (None,'missing'):
                    event=f.events[receipt-1]
                    if corruption=='actor':event['actor']=1
                    else:event['data'][corruption]=0 if corruption=='source' else 'mismatch'
                f.install(2,universal(),code,own)
                result=analyze(f.world(),f.events)
                if corruption is None:
                    self.assert_clean(result)
                    self.assertEqual(result['staged_edits'][0]['own_matching_proofs'][0]['record'],own['id'])
                else:
                    self.assertEqual(result['staged_edits'][0]['own_matching_proofs'],[])
                    self.assertTrue(any('initial authorization' in v for v in result['violations']))

    def test_own_law_inspection_assessment_needs_exact_copy_and_historical_receipt(self):
        from summarize_knowledge import analyze as knowledge_audit
        for derived in (False, True):
            for corruption in (None, 'missing', 'actor', 'record', 'source', 'interpretation', 'late',
                               'artifact', 'foreign_inspection', 'missing_parent', 'foreign_parent', 'installed'):
                with self.subTest(derived=derived, corruption=corruption):
                    f=LawFixture();code,_=f.law_work(1,territory())
                    f.teach(1,2,code);f.inspect_law(2,code)
                    inspected=f.events[-1];source=inspected['id']
                    if corruption=='artifact':inspected['data']['content']['law_program']['source']+=' changed'
                    elif corruption=='foreign_inspection':inspected['actor']=1
                    elif corruption=='missing_parent':inspected['parents']=[]
                    elif corruption=='foreign_parent':f.events[-2]['actor']=1
                    elif corruption=='installed':
                        # Even an exact payload plus a purported held ID does not
                        # turn installed-source evidence into a personal assessment.
                        inspected['data']['content']['installed']=dict(scope=territory(),revision=1)
                    receipt=None
                    if corruption not in ('missing','late'):
                        receipt=f.event('knowledge_interpreted',2,parents=[source],
                            record=code['id'],source=source,interpretation='I assessed the exact law source')
                    reflection=dict(source=source,interpretation='I assessed the exact law source')
                    if derived:reflection['knowledge']=dict(topic='Law reading',text='Conditional',location=None,confidence=30)
                    identity=f.event('identity_change',2,parents=[source],reflections=[reflection])
                    if corruption=='late':
                        f.event('knowledge_interpreted',2,parents=[source],record=code['id'],
                            source=source,interpretation=reflection['interpretation'])
                    elif corruption in ('actor','record','source','interpretation'):
                        event=f.events[receipt-1]
                        if corruption=='actor':event['actor']=1
                        else:event['data'][corruption]=0 if corruption=='source' else 'mismatch'
                    held=next(h for h in f.players[1]['knowledge'] if h['record']['id']==code['id'])
                    held.update(interpreted_source=source,interpretation=reflection['interpretation'])
                    _,own=f.law_work(2,universal(),record=code);f.assess(2,own['id'])
                    f.install(2,universal(),code,own)
                    result=analyze(f.world(),f.events)
                    citations=[c for c in knowledge_audit(f.world(),f.events)['accepted_citations'] if c['event']==identity]
                    assessment=result['law_experiments'][1]['code_interpretation']
                    if corruption is None:
                        self.assert_clean(result)
                        self.assertEqual(assessment['source'],source)
                        self.assertEqual(len(citations),1)
                        self.assertEqual(result['staged_edits'][0]['own_matching_proofs'][0]['record'],own['id'])
                    else:
                        self.assertIsNone(assessment)
                        self.assertEqual(citations,[])
                        self.assertTrue(any('personally held interpreted copy' in v for v in result['violations']))

    def test_installed_law_source_reflection_with_receipt_never_becomes_personal_assessment(self):
        from summarize_knowledge import analyze as knowledge_audit
        for has_copy in (False,True):
            f=LawFixture();code,_=f.law_work(1,territory())
            ref=f.install(1,territory(),code)
            if has_copy:f.teach(1,2,code)
            parent=f.event('law_inspected',2,reference=ref,location=0)
            source=f.event('perception',2,parents=[parent],kind='law_inspected',location=0,
                content=dict(installed=ref,law_program=copy.deepcopy(code['law_program'])))
            f.event('knowledge_interpreted',2,parents=[source],record=code['id'],source=source,
                interpretation='Read installed source')
            identity=f.event('identity_change',2,parents=[source],
                reflections=[dict(source=source,interpretation='Read installed source')])
            result=knowledge_audit(f.world(),f.events)
            self.assertEqual([c for c in result['accepted_citations'] if c['event']==identity],[])
            self.assertEqual(len(f.players[1]['knowledge']),int(has_copy))

    def assert_clean(self,result):
        for key in ('violations','research_violations','infrastructure_violations','copy_audit_violations'):
            self.assertEqual(result[key],[],key)

    def test_new_universal_law_needs_real_authoring_competence_under_initial_rules(self):
        f=LawFixture();f.law_work(1,universal(),auto_bootstrap=False)
        self.assertTrue(any('personally assessed paid terminal competence' in v for v in analyze(f.world(),f.events)['violations']))

    def test_local_grant_can_install_failed_paid_candidate_without_invented_success(self):
        f=LawFixture();code,_=f.law_work(1,territory(),successful=False)
        f.install(1,territory(),code);f.completed_action(1)
        result=analyze(f.world(),f.events);self.assert_clean(result)
        self.assertEqual(result['observed_evidence']['successful_law_experiments'],0)
        self.assertEqual(result['observed_evidence']['activated'],1)
        self.assertTrue(result['staged_edits'][0]['local_grant'])
        self.assertIn('Not automatically assigned',result['acceptance'])

    def test_learner_own_universal_practice_proof_and_inspection_are_recorded(self):
        f=LawFixture();code,_=f.law_work(1,territory())
        f.teach(1,2,code);f.inspect_law(2,code);f.assess(2,code['id'])
        _,own=f.law_work(2,universal(),record=code);f.assess(2,own['id'])
        f.install(2,universal(),code,own)
        result=analyze(f.world(),f.events);self.assert_clean(result)
        self.assertEqual(result['observed_evidence']['universal_activations'],1)
        self.assertEqual(result['staged_edits'][0]['own_matching_proofs'][0]['record'],own['id'])
        self.assertIsNotNone(result['law_experiments'][1]['source_inspection'])

    def test_foreign_copied_experiment_does_not_satisfy_initial_universal_authority(self):
        f=LawFixture();code,foreign=f.law_work(1,universal())
        f.teach(1,2,code);f.teach(1,2,foreign);f.assess(2,foreign['id'])
        f.install(2,universal(),code,foreign)
        result=analyze(f.world(),f.events)
        self.assertTrue(any('initial authorization' in v for v in result['violations']))

    def test_changed_universal_authorization_does_not_keep_immutable_proof_gate(self):
        f=LawFixture();code,proof=f.law_work(1,universal(),source='fn authorize_law_edit(c){true}',
            hooks=['authorize_law_edit'],cases=[dict(hook='authorize_law_edit',input={},expected=True)])
        f.assess(1,proof['id']);f.install(1,universal(),code,proof)
        other,_=f.law_work(1,territory(),source='fn cost(s){999}',cases=[dict(hook='cost',input='gather',expected=999)])
        f.teach(1,2,other);f.install(2,universal(),other)
        result=analyze(f.world(),f.events);self.assert_clean(result)
        self.assertFalse(result['staged_edits'][1]['default_authorization'])
        self.assertEqual(result['staged_edits'][1]['own_matching_proofs'],[])
        self.assertIsNotNone(result['staged_edits'][1]['authorization_override'])

    def test_changed_research_rules_do_not_keep_initial_numeric_proof_gates(self):
        f=LawFixture();law,_=f.law_work(1,territory(),
            source='fn research_authoring(c){true} fn research_use(c){true}',
            hooks=['research_authoring','research_use'],cases=[
                dict(hook='research_authoring',input={},expected=True),
                dict(hook='research_use',input={},expected=True)])
        f.install(1,territory(),law)
        program,_=f.work(2,'prototype');f.assess(2,program['id'])
        f.work(2,'run',program)
        result=analyze(f.world(),f.events);self.assert_clean(result)
        self.assertEqual(result['numeric_research_evidence']['bootstrap_authorships'],0)
        self.assertEqual(result['numeric_research_evidence']['successful_runs'],1)

    def test_local_authorization_cannot_promote_universal_request(self):
        f=LawFixture();code,_=f.law_work(1,territory(),source='fn authorize_law_edit(c){true}',
            hooks=['authorize_law_edit'],cases=[dict(hook='authorize_law_edit',input={},expected=True)])
        f.install(1,territory(),code)
        other,_=f.law_work(1,territory());f.install(1,universal(),other)
        result=analyze(f.world(),f.events)
        self.assertTrue(any('initial authorization' in v for v in result['violations']))
        self.assertTrue(result['staged_edits'][1]['default_authorization'])

    def test_stale_binding_or_wrong_hash_cannot_reuse_a_personal_proof(self):
        f=LawFixture();code,proof=f.law_work(1,universal());f.assess(1,proof['id'])
        other,otherproof=f.law_work(1,universal(),source='fn cost(s){4}',cases=[dict(hook='cost',input='gather',expected=4)])
        f.assess(1,otherproof['id']);f.install(1,universal(),other,otherproof)
        f.install(1,universal(),code,proof)
        result=analyze(f.world(),f.events)
        self.assertTrue(any('initial authorization' in v for v in result['violations']))
        event=next(e for e in f.events if e['kind']=='compute_submitted' and e['data'].get('experiment_kind')=='law')
        event['data']['program_record']['law_program']['source']+=' '
        self.assertTrue(any('artifact hash' in v for v in analyze(f.world(),f.events)['violations']))

    def test_private_case_changes_and_false_success_claim_fail(self):
        f=LawFixture();f.law_work(1,territory())
        submit=next(e for e in f.events if e['kind']=='compute_submitted')
        submit['data']['cases'][0]['expected']=8
        result=analyze(f.world(),f.events)
        self.assertTrue(any('input hash' in v for v in result['violations']))
        self.assertTrue(any('success claim' in v for v in result['violations']))

    def test_invalid_typed_cost_and_boolean_result_cannot_claim_success(self):
        f=LawFixture();f.law_work(1,territory(),cases=[dict(hook='cost',input='gather',expected=True)])
        result=analyze(f.world(),f.events)
        self.assertTrue(any('typed output contract' in v for v in result['violations']))

    def test_early_activation_and_corrupt_retained_source_fail(self):
        f=LawFixture();code,_=f.law_work(1,territory());f.install(1,territory(),code)
        next(e for e in f.events if e['kind']=='law_activated')['data']['effective_update']=0
        f.laws['history']['territory:west']['1']['artifact']['source']+=' '
        result=analyze(f.world(),f.events)
        self.assertTrue(any('before its promised' in v for v in result['violations']))
        self.assertTrue(any('Installed law' in v for v in result['violations']))

    def test_actual_death_persistence_and_border_crossing_are_conditional(self):
        f=LawFixture();code,_=f.law_work(1,territory());f.install(1,territory(),code)
        f.event('death',1);f.players[0]['health']=0
        f.completed_action(2);f.completed_action(2,'move',3)
        result=analyze(f.world(),f.events);self.assert_clean(result)
        self.assertEqual(result['observed_evidence']['author_death_persistence_candidates'],1)
        self.assertEqual(result['observed_evidence']['border_crossings'],1)
        self.assertTrue(result['installed_after_author_death'][0]['later_invocation_outcomes'])
        self.assertTrue(result['program_availability'][code['id']]['installed_source_copies'][0]['active'])
        empty=LawFixture();empty.event('death',1);empty.players[0]['health']=0
        self.assertEqual(analyze(empty.world(),empty.events)['installed_after_author_death'],[])

    def test_installed_source_survives_death_and_terminal_erasure_without_free_personal_copy(self):
        f=LawFixture();code,_=f.law_work(1,territory());ref=f.install(1,territory(),code)
        f.event('death',1);f.players[0]['health']=0;f.erase_law(1)
        inspected=f.event('law_inspected',2,reference=ref,location=0)
        f.event('perception',2,parents=[inspected],kind='law_inspected',location=0,
            content=dict(installed=ref,law_program=copy.deepcopy(code['law_program'])))
        result=analyze(f.world(),f.events);self.assert_clean(result)
        copies=result['program_availability'][code['id']]
        self.assertEqual(copies['living_carriers'],[])
        self.assertEqual(copies['terminal_copies'],[])
        self.assertEqual(len(copies['installed_source_copies']),1)
        self.assertEqual(f.players[1]['knowledge'],[])

    def test_default_source_feed_and_foreign_inspection_are_not_source_access(self):
        f=LawFixture();code,_=f.law_work(1,territory());f.inspect_law(2,code)
        result=analyze(f.world(),f.events)
        self.assertTrue(any('not personally held' in v for v in result['violations']))
        event=next(e for e in f.events if e['kind']=='perception' and e['data'].get('kind')=='knowledge_report'
            and e['data']['content']['record'].get('law_program'))
        event['data']['content']['record']['law_program']['source']='private source leak'
        self.assertTrue(any('exposes program source' in v for v in analyze(f.world(),f.events)['copy_audit_violations']))

    def test_quarantine_binding_can_precede_its_end_of_update_report(self):
        f=LawFixture();code,_=f.law_work(1,territory());ref=f.install(1,territory(),code)
        fault=dict(reference=ref,hook='cost',error='private runtime detail')
        f.laws['faults']=[fault];f.laws['reported_faults']=1
        binding=f.binding(territory());binding['disabled']=[dict(reference=ref,hook='cost')];binding['digest']=binding_hash(binding)
        f.event('needs_change',1,hunger_before=0,hunger_after=2,law_binding=binding)
        f.event('law_hook_quarantined',None,fault=fault,fallback='next valid implementation')
        result=analyze(f.world(),f.events);self.assert_clean(result)
        self.assertEqual(len(result['bindings_before_quarantine_report']),1)

    def test_only_typed_bound_law_denial_is_reclassified_not_script_faults(self):
        f=LawFixture();code,_=f.law_work(1,territory(),source='fn authorize_effect(c){false}',
            hooks=['authorize_effect'],cases=[dict(hook='authorize_effect',input={},expected=False)])
        f.install(1,territory(),code)
        f.event('script_error',2,category='law_authorization_denied',error='active law denied effect',
            effects_committed=False,law_binding=f.binding(territory()))
        f.event('script_error',2,error='Function not found: malformed_fixture',effects_committed=False)
        f.event('script_tick_failed',None,error='fixture update failure',effects_committed=False)
        errors,denials=classify_execution_events(f.events)
        self.assertEqual(len(denials),1)
        self.assertEqual(len(errors),2)
        self.assertTrue(denials[0]['data']['law_binding'])
        unsupported=[copy.deepcopy(f.events[-3])]
        self.assertEqual(len(classify_execution_events(unsupported)[0]),1,'a marker without prior installed authority is insufficient')

    def test_pending_law_is_not_reported_as_activated(self):
        f=LawFixture();code,_=f.law_work(1,territory());f.install(1,territory(),code,activate=False)
        result=analyze(f.world(),f.events);self.assert_clean(result)
        self.assertEqual(result['observed_evidence']['staged'],1)
        self.assertEqual(result['observed_evidence']['activated'],0)


class LawScenarioTests(unittest.TestCase):
    def test_overlap_order_handles_prefix_ids_before_area_and_priority(self):
        f=LawFixture();world=f.world();template=world['initial']['society']['regions'][0]
        a=copy.deepcopy(template);a['id']='a'
        aa=copy.deepcopy(template);aa['id']='aa'
        high=copy.deepcopy(template);high.update(id='high',priority=1)
        world['initial']['society']['regions']=[a,aa,high]
        self.assertEqual([r['id'] for r in regions_at(world,0)],['aa','a','high'])

    def test_exact_matched_repeat_and_single_controls(self):
        base=make_scenario('local-borders');base.pop('name')
        repeat=make_scenario('universal-repeat');repeat.pop('name');self.assertEqual(base,repeat)
        cooling=make_scenario('cooling');cooling.pop('name');cooling['infrastructure']['stations'][0]['materials']['water']=36
        self.assertEqual(base,cooling)
        absence=make_scenario('author-absence');absence.pop('name')
        self.assertEqual(absence.pop('disturbances'),[dict(at_ms=1080000,kind='damage',actor=1,amount=100)])
        base.pop('disturbances');self.assertEqual(base,absence)

    def test_only_survival_seed_same_controllers_and_two_endowed_grants(self):
        for name in VARIANTS:
            scenario=make_scenario(name);validate(scenario,controllers(scenario['players']))
        manifest=build()['configs/experiments/campaign/022-physical-laws.json']
        self.assertEqual([v['port'] for v in manifest['variants']],list(range(18991,18995)))
        self.assertEqual((manifest['minutes'],manifest['calls_per_actor'],manifest['serial_ms'],manifest['concurrency']),(24,0,15000,4))


if __name__=='__main__':unittest.main()
