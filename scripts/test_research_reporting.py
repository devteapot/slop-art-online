"""Observer-only synthetic evidence fixtures. None are autonomous-model evidence."""
import copy
import unittest

from prepare_research_scenarios import VARIANTS, build, make_scenario, validate
from prepare_infrastructure_scenarios import controllers
from summarize_knowledge import record_view
from summarize_research import analyze, input_hash, program_hash


class Fixture:
    def __init__(self):
        self.events = []
        self.initial = dict(balance=dict(compute_quanta=3, compute_quantum_ms=1000, compute_electricity=2, compute_water=1), actor_materials={}, bodies={}, stations=[dict(seed=dict(id=1,
            electricity=100, materials=dict(parts=0, water=30)), embodied_parts=0,
            repair_parts_consumed=0, jobs=[])])
        self.infrastructure = copy.deepcopy(self.initial)
        self.players = [dict(id=a, health=100, knowledge=[]) for a in (1, 2)]
        self.event('infrastructure_initialized', None, **self.initial)

    def event(self, event_kind, actor, parents=None, **data):
        eid = len(self.events) + 1
        self.events.append(dict(id=eid, kind=event_kind, actor=actor, parents=parents or [],
            data=dict(time_ms=eid * 1000, **data)))
        return eid

    def record(self, rid, actor, origin, program=None, experiment=None):
        return dict(id=rid, author=actor, origin=origin, topic='fixture', text='fixture only',
                    confidence=50, location=None, program=program, experiment=experiment)

    def receive(self, actor, record, parent, via='compute_terminal'):
        player = self.players[actor-1]
        old = next((h for h in player['knowledge'] if h['record']['id']==record['id']), None)
        eid = self.event('perception', actor, parents=[parent], kind='knowledge_report',
            content=dict(record=record_view(record), new_copy=old is None, via=via))
        if old:
            old['source'] = eid
        else:
            player['knowledge'].append(dict(record=copy.deepcopy(record), source=eid,
                interpreted_source=None, interpretation=None))
        return eid

    def assess(self, actor, rid):
        held = next(h for h in self.players[actor-1]['knowledge'] if h['record']['id']==rid)
        self.event('identity_change', actor, parents=[held['source']],
            reflections=[dict(source=held['source'], interpretation='fixture interpretation')])
        held.update(interpreted_source=held['source'], interpretation='fixture interpretation')

    def inspect(self, actor, record):
        eid = self.event('program_inspected', actor, station=1, record=record['id'],
            program_hash=record['program']['source_hash'])
        self.event('perception', actor, parents=[eid], kind='program_inspected',
            content=dict(record=record['id'], program=copy.deepcopy(record['program'])))

    def work(self, actor, kind, program_record=None, successful=True):
        job_id = len(self.infrastructure['stations'][0]['jobs']) + 1
        eid = len(self.events) + 1
        data = dict(station=1, job=job_id, required_quanta=3, quantum_ms=1000)
        if kind == 'builtin_forecast':
            data.update(input=dict(stock=5, inflow_per_min=0, demand_per_min=1,
                horizon_ms=60000, sources=[]), input_hash='forecast-fixture', program='resource_forecast_v1')
        else:
            if kind == 'prototype':
                artifact = dict(interface_version=1, source='fn technique(input) { [input[0]*input[0]] }',
                    input_contract='One fixture integer', output_contract='Its square')
                artifact['source_hash'] = program_hash(artifact)
                program_record = self.record('technique-2', actor, eid, program=artifact)
            data.update(experiment_kind=kind, program_record=copy.deepcopy(program_record),
                new_program=kind=='prototype', input=[3], expected_results=None if kind=='run' else [9],
                source_records=[])
            data['input_hash'] = input_hash(data)
        submitted = self.event('compute_submitted', actor, **data)
        job = dict(id=job_id, owner=actor, input_hash=data['input_hash'], source=submitted, progress=3, required=3, cancelled=False, retrieved=True,
            sources=[], input=data['input'] if kind=='builtin_forecast' else None,
            program_work=None if kind=='builtin_forecast' else dict(kind=kind,
                program_record=copy.deepcopy(program_record), inputs=[3], expected_results=data['expected_results']))
        for progress in range(1, 4):
            self.event('compute_quantum', actor, station=1, job=job_id, progress=progress,
                electricity=2, water=1, quantum_at_ms=(submitted + progress)*1000)
        origin = len(self.events) + 1
        experiment = dict(kind=kind, operator=actor, station=1, job=job_id,
            program_hash=None if kind=='builtin_forecast' else program_record['program']['source_hash'],
            input_hash=data['input_hash'], inputs=[] if kind=='builtin_forecast' else [3],
            expected_results=None if kind=='builtin_forecast' else data['expected_results'],
            output=None if kind=='builtin_forecast' else [9] if successful else [8],
            runtime_error=None, predictions_matched=None if kind in ('builtin_forecast','run') else successful,
            successful=successful, paid_quanta=3, rules_revision=0)
        report = self.record(f'experiment-{job_id}', actor, origin, experiment=experiment)
        completed = dict(station=1, job=job_id, record=copy.deepcopy(report))
        if kind!='builtin_forecast':
            completed.update(program_record=copy.deepcopy(program_record), output=experiment['output'],
                runtime_error=None, successful=successful)
        self.event('compute_completed', actor, parents=[submitted], **completed)
        for record in [report] + ([] if kind=='builtin_forecast' else [program_record]):
            old = any(h['record']['id']==record['id'] for h in self.players[actor-1]['knowledge'])
            receipt = self.event('compute_retrieved', actor, station=1, job=job_id,
                record=record['id'], new_copy=not old)
            self.receive(actor, record, receipt)
        job['report'] = report
        station = self.infrastructure['stations'][0]
        station['jobs'].append(job)
        station['seed']['electricity'] -= 6
        station['seed']['materials']['water'] -= 3
        return program_record, report

    def erase(self, job_id):
        station = self.infrastructure['stations'][0]
        job = next(j for j in station['jobs'] if j['id']==job_id)
        ids = [job['report']['id']]
        hashes = []
        if job['program_work']:
            ids.append(job['program_work']['program_record']['id'])
            hashes.append(job['program_work']['program_record']['program']['source_hash'])
        self.event('compute_erased', job['owner'], station=1, job=job_id, owner=job['owner'],
            progress=3, record_ids=sorted(ids), program_hashes=hashes, refund=False)
        station['jobs'].remove(job)

    def world(self):
        return dict(initial=dict(players=[dict(id=a, health=100) for a in (1,2)], archives=[]),
                    players=self.players, archives=[], infrastructure=self.infrastructure)

    @classmethod
    def transfer(cls):
        f = cls()
        _, bootstrap = f.work(1, 'builtin_forecast')
        f.assess(1, bootstrap['id'])
        program, _ = f.work(1, 'prototype')
        taught = f.event('knowledge_taught', 1, target=2, record=program['id'], new_copy=True)
        f.receive(2, program, taught, via='teaching')
        f.inspect(2, program)
        f.assess(2, program['id'])
        _, practice = f.work(2, 'practice', program)
        f.assess(2, practice['id'])
        f.work(2, 'run', program)
        return f


class ResearchReportingTests(unittest.TestCase):
    def test_direct_inspection_assessment_needs_actual_receipt_and_exact_own_source(self):
        for derived in (False, True):
            for corruption in (None, 'missing', 'actor', 'record', 'source', 'interpretation', 'late', 'artifact', 'foreign_inspection'):
                with self.subTest(derived=derived, corruption=corruption):
                    f = Fixture()
                    _, bootstrap = f.work(1, 'builtin_forecast'); f.assess(1, bootstrap['id'])
                    program, _ = f.work(1, 'prototype')
                    taught = f.event('knowledge_taught', 1, target=2, record=program['id'], new_copy=True)
                    f.receive(2, program, taught, via='teaching')
                    f.inspect(2, program); source = f.events[-1]['id']
                    if corruption == 'artifact':
                        f.events[-1]['data']['content']['program']['source'] += ' altered'
                    elif corruption == 'foreign_inspection':
                        f.events[-1]['actor'] = 1
                    receipt = None
                    if corruption not in ('missing', 'late'):
                        receipt = f.event('knowledge_interpreted', 2, parents=[source],
                            record=program['id'], source=source, interpretation='I assessed the exact inspected code')
                    reflection = dict(source=source, interpretation='I assessed the exact inspected code')
                    if derived:
                        reflection['knowledge'] = dict(topic='Assessment', text='Conditional', location=None, confidence=30)
                    f.event('identity_change', 2, parents=[source], reflections=[reflection])
                    if corruption == 'late':
                        f.event('knowledge_interpreted', 2, parents=[source],
                            record=program['id'], source=source, interpretation=reflection['interpretation'])
                    elif corruption in ('actor', 'record', 'source', 'interpretation'):
                        event = f.events[receipt-1]
                        if corruption == 'actor': event['actor'] = 1
                        else: event['data'][corruption] = 0 if corruption == 'source' else 'mismatch'
                    held = next(h for h in f.players[1]['knowledge'] if h['record']['id'] == program['id'])
                    held.update(interpreted_source=source, interpretation=reflection['interpretation'])
                    _, practice = f.work(2, 'practice', program); f.assess(2, practice['id'])
                    f.work(2, 'run', program)
                    result = analyze(f.world(), f.events)
                    interpretation = result['practice_submissions'][0]['code_interpretation']
                    if corruption is None:
                        self.assertEqual(result['violations'], [])
                        self.assertEqual(result['copy_audit_violations'], [])
                        self.assertEqual(interpretation['source'], source)
                        self.assertIsNotNone(interpretation['source_inspected_before'])
                        self.assertEqual(result['observed_evidence']['transfer_practice_run_completions'], 1)
                    else:
                        self.assertIsNone(interpretation)
                        self.assertTrue(any('interpretation' in v for v in result['violations']))

    def test_derived_assessment_requires_matching_prior_authority_receipt(self):
        for corruption in (None, 'missing', 'actor', 'record', 'source', 'interpretation', 'late'):
            with self.subTest(corruption=corruption):
                f = Fixture()
                _, report = f.work(1, 'builtin_forecast')
                held = next(h for h in f.players[0]['knowledge'] if h['record']['id'] == report['id'])
                receipt = None
                if corruption not in ('missing', 'late'):
                    receipt = f.event('knowledge_interpreted', 1, parents=[held['source']],
                        record=report['id'], source=held['source'], interpretation='fixture interpretation')
                f.assess(1, report['id'])
                f.events[-1]['data']['reflections'][0]['knowledge'] = dict(
                    topic='Inference', text='Conditional only', location=None, confidence=30)
                if corruption == 'late':
                    f.event('knowledge_interpreted', 1, parents=[held['source']],
                        record=report['id'], source=held['source'], interpretation='fixture interpretation')
                elif corruption not in (None, 'missing'):
                    event = f.events[receipt-1]
                    if corruption == 'actor':
                        event['actor'] = 2
                    else:
                        event['data'][corruption] = 0 if corruption == 'source' else 'mismatch'
                f.work(1, 'prototype')
                result = analyze(f.world(), f.events)
                self.assertEqual(result['authoring_submissions'][0]['built_in_forecast_bootstrap'], corruption is None)
                if corruption is None:
                    self.assertEqual(result['violations'], [])
                else:
                    self.assertTrue(any('bootstrap' in violation for violation in result['violations']))

    def test_complete_paid_transfer_chain_is_separate_from_model_invention_claim(self):
        f = Fixture.transfer()
        result = analyze(f.world(), f.events)
        self.assertEqual(result['violations'], [])
        self.assertEqual(result['infrastructure_violations'], [])
        self.assertEqual(result['copy_audit_violations'], [])
        self.assertEqual(result['observed_evidence']['transfer_practice_run_submissions'], 1)
        self.assertTrue(result['authoring_submissions'][0]['built_in_forecast_bootstrap'])
        self.assertIn('Not automatically assigned', result['acceptance'])
        self.assertNotIn('autonomous_invention', result['observed_evidence'])

    def test_copy_of_foreign_experiment_does_not_grant_own_competence(self):
        f = Fixture()
        _, bootstrap = f.work(1, 'builtin_forecast')
        f.assess(1, bootstrap['id'])
        program, prototype = f.work(1, 'prototype')
        for record in (program, prototype):
            taught = f.event('knowledge_taught', 1, target=2, record=record['id'], new_copy=True)
            f.receive(2, record, taught, via='teaching')
        f.inspect(2, program)
        f.assess(2, program['id'])
        f.assess(2, prototype['id'])
        f.work(2, 'run', program)
        result = analyze(f.world(), f.events)
        self.assertTrue(any('exact source hash' in v for v in result['violations']))
        self.assertEqual(result['observed_evidence']['transfer_practice_run_submissions'], 0)

    def test_wrong_source_hash_and_false_success_are_rejected(self):
        f = Fixture.transfer()
        submitted = next(e for e in f.events if e['kind']=='compute_submitted' and e['data'].get('experiment_kind')=='run')
        submitted['data']['program_record']['program']['source'] += ' '
        completed = next(e for e in f.events if e['kind']=='compute_completed' and e['data']['job']==3)
        completed['data']['record']['experiment']['predictions_matched'] = False
        result = analyze(f.world(), f.events)
        self.assertTrue(any('program hash does not bind' in v for v in result['violations']))
        self.assertTrue(any('predictions_matched' in v for v in result['violations']))

    def test_source_inspection_is_distinct_from_copied_metadata_interpretation(self):
        f = Fixture.transfer()
        for event in f.events:
            if event['kind']=='program_inspected' or event['data'].get('kind')=='program_inspected':
                event['kind']='fixture_omitted_inspection'
        result=analyze(f.world(),f.events)
        self.assertEqual(result['violations'], [])  # The current law does not require a source read.
        self.assertEqual(result['observed_evidence']['successful_runs'], 1)
        self.assertEqual(result['observed_evidence']['transfer_practice_run_submissions'], 0)

    def test_foreign_source_response_and_default_feed_leak_are_rejected(self):
        f = Fixture.transfer()
        event = next(e for e in f.events if e['kind']=='perception' and e['data'].get('kind')=='program_inspected')
        event['actor'] = 9
        report = next(e for e in f.events if e['kind']=='perception' and e['data'].get('kind')=='knowledge_report'
            and e['data']['content']['record'].get('program'))
        report['data']['content']['record']['program']['source'] = 'leaked source'
        result = analyze(f.world(), f.events)
        self.assertTrue(any('foreign' in v for v in result['violations']))
        self.assertTrue(any('exposes program source' in v for v in result['copy_audit_violations']))

    def test_unpaid_completion_and_invented_water_fail_independent_accounts(self):
        f = Fixture.transfer()
        next(e for e in f.events if e['kind']=='compute_quantum')['data']['progress']=2
        f.infrastructure['stations'][0]['seed']['materials']['water'] += 1
        result=analyze(f.world(),f.events)
        self.assertTrue(any('invalid work' in v for v in result['infrastructure_violations']))
        self.assertIn('Water account does not reconcile', result['infrastructure_violations'])

    def test_zero_price_quantum_cannot_be_called_paid_work(self):
        f=Fixture.transfer()
        next(e for e in f.events if e['kind']=='compute_quantum')['data']['electricity']=0
        result=analyze(f.world(),f.events)
        self.assertTrue(any('configured physical price' in v for v in result['violations']))

    def test_erasure_and_death_preserve_remaining_terminal_copies_until_last_job(self):
        f=Fixture.transfer()
        for actor in (1,2):
            f.event('death', actor)
            f.players[actor-1]['health']=0
        f.erase(2)
        result=analyze(f.world(),f.events)
        self.assertEqual(result['copy_audit_violations'], [])
        self.assertEqual(result['infrastructure_violations'], [])
        remaining=result['program_availability']['technique-2']
        self.assertTrue(remaining['no_living_or_archive_access'])
        self.assertFalse(remaining['no_living_archive_or_terminal_copy'])
        f.erase(3)
        f.erase(4)
        result=analyze(f.world(),f.events)
        self.assertEqual(result['copy_audit_violations'], [])
        self.assertEqual(result['infrastructure_violations'], [])
        self.assertTrue(result['program_availability']['technique-2']['no_living_archive_or_terminal_copy'])

    def test_failed_prediction_is_a_paid_failure_without_competence(self):
        f=Fixture()
        _, report=f.work(1,'builtin_forecast');f.assess(1,report['id'])
        _, report=f.work(1,'prototype',successful=False);f.assess(1,report['id'])
        result=analyze(f.world(),f.events)
        self.assertEqual(result['violations'], [])
        self.assertEqual(result['observed_evidence']['successful_prototypes'],0)
        self.assertEqual([p['kind'] for p in result['personal_proofs']['1']],['builtin_forecast'])


class ResearchScenarioTests(unittest.TestCase):
    def test_controls_change_only_declared_inputs_and_repeat_is_fresh_matched(self):
        baseline=make_scenario('invention');baseline.pop('name')
        repeat=make_scenario('transfer-repeat');repeat.pop('name')
        self.assertEqual(baseline,repeat)
        cooling=make_scenario('cooling');cooling.pop('name')
        cooling['infrastructure']['stations'][0]['materials']['water']=48
        self.assertEqual(baseline,cooling)
        loss=make_scenario('loss-risk');loss.pop('name')
        self.assertEqual(loss.pop('disturbances'),[dict(at_ms=540000,kind='damage',actor=1,amount=100),
            dict(at_ms=570000,kind='destroy_archive',archive=1)])
        baseline.pop('disturbances')
        self.assertEqual(baseline,loss)

    def test_no_seed_program_proof_or_action_path_and_same_model_schedule(self):
        for name in VARIANTS:
            scenario=make_scenario(name)
            validate(scenario,controllers(scenario['players']))
        manifest=build()['configs/experiments/campaign/020-research.json']
        self.assertEqual([v['port'] for v in manifest['variants']],list(range(18985,18989)))
        self.assertEqual((manifest['minutes'],manifest['calls_per_actor'],manifest['serial_ms'],manifest['concurrency']),
                         (18,0,15000,4))


if __name__=='__main__':
    unittest.main()
