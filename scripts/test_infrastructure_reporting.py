import copy
import unittest

from summarize_infrastructure import analyze
from summarize_knowledge import analyze as analyze_knowledge


class InfrastructureReportingTests(unittest.TestCase):
    def fixture(self):
        self.events = []
        initial = dict(actor_materials={'1': dict(parts=4, water=0)}, bodies={'1': dict(charge=10)},
                       stations=[dict(seed=dict(id=1, electricity=10, materials=dict(parts=2, water=3)),
                                      embodied_parts=14, repair_parts_consumed=0, jobs=[])])
        self.event('infrastructure_initialized', None, **copy.deepcopy(initial))
        self.event('electricity_generated', None, amount=3)
        self.event('body_charged', 1, station=1, target=1, electricity=4, charge=3, conversion_loss=1)
        self.event('electricity_consumed', 1, amount=2)
        self.event('infrastructure_repaired', 1, station=1, parts=1)
        self.event('compute_submitted', 1, station=1, job=1, required_quanta=1, quantum_ms=1000)
        self.event('compute_quantum', 1, station=1, job=1, progress=1, electricity=2, water=1, quantum_at_ms=1300)
        record = dict(id='compute-1', author=1, topic='forecast', text='conditional fixture',
                      location=None, confidence=50, origin=8)
        self.event('compute_completed', 1, station=1, job=1, record=record)
        self.event('compute_retrieved', 1, station=1, job=1, record='compute-1', new_copy=True)
        receipt = self.event('perception', 1, kind='knowledge_report',
                             content=dict(record=record, new_copy=True, via='compute_terminal'))
        final = copy.deepcopy(initial)
        final['actor_materials']['1']['parts'] = 3
        final['bodies']['1']['charge'] = 11
        station = final['stations'][0]
        station['seed'].update(electricity=7, materials=dict(parts=2, water=2))
        station['repair_parts_consumed'] = 1
        station['jobs'] = [dict(id=1, owner=1, progress=1, required=1, cancelled=False,
                               retrieved=True, report=record)]
        player = dict(id=1, health=100, knowledge=[dict(record=record, source=receipt)], position=0)
        world = dict(infrastructure=final, initial=dict(players=[dict(id=1, health=100)], archives=[]),
                     players=[player], archives=[], timing=dict(time_ms=1500))
        return world

    def event(self, event_kind, actor, **data):
        event = dict(id=len(self.events)+1, kind=event_kind, actor=actor, parents=[],
                     data=dict(time_ms=(len(self.events)+1)*50, **data))
        self.events.append(event)
        return event['id']

    def test_paid_output_and_its_terminal_personal_copies_reconcile(self):
        world = self.fixture()
        self.assertEqual(analyze(world, self.events)['violations'], [])
        knowledge = analyze_knowledge(world, self.events)
        self.assertEqual(knowledge['copy_audit_violations'], [])
        self.assertEqual(knowledge['final_availability']['compute-1']['living_carriers'], [1])
        self.assertEqual(len(knowledge['final_availability']['compute-1']['terminal_copies']), 1)

    def test_missing_water_and_invented_charge_are_visible(self):
        world = self.fixture()
        world['infrastructure']['stations'][0]['seed']['materials']['water'] += 1
        world['infrastructure']['bodies']['1']['charge'] += 1
        violations = analyze(world, self.events)['violations']
        self.assertIn('Water account does not reconcile', violations)
        self.assertIn('Electricity account does not reconcile', violations)

    def test_duplicate_or_early_work_does_not_pass_as_paid_computation(self):
        world = self.fixture()
        self.events[6]['data']['quantum_at_ms'] = 400
        self.assertTrue(any('early' in v for v in analyze(world, self.events)['violations']))
        self.events[6]['data']['quantum_at_ms'] = 1300
        self.events[6]['data']['progress'] = 2
        self.assertTrue(any('unpaid' in v for v in analyze(world, self.events)['violations']))

    def test_unretrieved_output_survives_author_death_as_terminal_copy_only(self):
        world = self.fixture()
        self.events = self.events[:8]
        world['players'][0].update(health=0, knowledge=[])
        world['infrastructure']['stations'][0]['jobs'][0]['retrieved'] = False
        self.event('death', 1)
        result = analyze_knowledge(world, self.events)
        self.assertEqual(result['copy_audit_violations'], [])
        copies = result['final_availability']['compute-1']
        self.assertEqual(copies['living_carriers'], [])
        self.assertEqual(copies['terminal_copies'][0]['owner_alive'], False)

    def test_missing_physical_output_and_foreign_retrieval_are_rejected(self):
        world = self.fixture()
        world['infrastructure']['stations'][0]['jobs'][0]['report'] = None
        self.events[8]['actor'] = 2
        result = analyze_knowledge(world, self.events)
        self.assertTrue(any('foreign' in v for v in result['copy_audit_violations']))
        self.assertTrue(any('Final physical' in v for v in result['copy_audit_violations']))


if __name__ == '__main__':
    unittest.main()
