"""Recorded-evidence fixtures for dynamic actors; no simulator or model launches."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from summarize_arena_matrix import actor_layout
from summarize_knowledge import analyze, summarize
from summarize_society import summarize as summarize_society
from summarize_population import analyze as analyze_population, summarize as summarize_population

ROOT = Path(__file__).resolve().parents[1]


class LifecycleReportingChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.run = self.out / 'fixture-run'
        self.run.mkdir()
        initial = json.loads((ROOT / 'scenarios/knowledge-teaching-two.json').read_text())
        initial['knowledge'] = {}
        initial['players'][0]['food'] = 10
        self.world = dict(initial=copy.deepcopy(initial), players=copy.deepcopy(initial['players']),
                          sites=copy.deepcopy(initial['sites']), archives=[], timing=dict(time_ms=1000, updates=20),
                          version='recorded-evidence-fixture', actor_arenas={'1': 'clearing', '2': 'clearing', '3': 'clearing'})
        child = copy.deepcopy(self.world['players'][0])
        child.update(id=3, name='Newcomer', food=1, health=100, hunger=40, energy=50, knowledge=[])
        self.world['players'].append(child)
        self.world['players'][0]['food'] = 4
        self.world['sites'][0]['food'] = 9
        self.events = []
        record = dict(id='fixture-note', topic='route', text='An attributed fixture', author=1, origin=1, confidence=60, location=56)
        first = self.event('perception', 1, kind='knowledge_report', content=dict(record=record, new_copy=True, via='initial fixture'))
        self.event('food_consumed', 1, amount=4, reason='fabrication')
        self.birth = self.event('actor_created', 3, born_ms=100, method='fabrication', creators=[1], arena='clearing',
                               initial_resources=dict(food=0, health=100, hunger=50, energy=50), name='Newcomer')
        self.care = self.event('food_consumed', 1, amount=1, reason='care', target=3)
        self.event('skill_result', 1, skill='eat', status='completed')
        self.event('resource_produced', None, location=84, food_delta=2)
        self.event('resource_change', 3, location=84, food_delta=-1)
        self.event('knowledge_taught', 1, target=3, record='fixture-note', new_copy=True)
        received = self.event('perception', 3, kind='knowledge_report', content=dict(record=record, new_copy=True, via='teaching'))
        self.world['players'][0]['knowledge'] = [dict(record=record, source=first)]
        self.world['players'][1]['knowledge'] = []
        self.world['players'][2]['knowledge'] = [dict(record=record, source=received)]
        self.participants = [dict(actor=1, role='builtin'), dict(actor=2, role='external'), dict(actor=3, role='builtin')]
        self.write()

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, event_kind, actor, **data):
        eid = len(self.events) + 1
        self.events.append(dict(id=eid, actor=actor, kind=event_kind, parents=[], data=dict(time_ms=eid * 50, **data)))
        return eid

    def write(self):
        (self.out / 'pilot.json').write_text(json.dumps(dict(run='fixture-run', phase='completed')))
        (self.run / 'final-snapshot.json').write_text(json.dumps(dict(world=self.world, events=self.events)))
        (self.run / 'participants.json').write_text(json.dumps(self.participants))

    def test_new_actor_care_practice_and_knowledge_are_reconciled_without_inheritance(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = summarize(self.out)
        self.assertEqual(result['copy_audit_violations'], [])
        self.assertEqual(result['final_availability']['fixture-note']['living_carriers'], [1, 3])
        society = json.loads((self.out / 'SOCIETY_RESULT.json').read_text())
        self.assertEqual(society['initial_food'] + society['produced'], 34)
        self.assertEqual(society['final_food'] + society['eaten'] + society['lifecycle_food_consumed'], 34)
        self.assertEqual(society['food_consumed_by_reason'], {'care': 1, 'fabrication': 4})
        child = next(p for p in society['players'] if p['actor'] == 3)
        self.assertEqual((child['initial_food'], child['gathered'], child['care_received']), (0, 1, 1))
        arena = json.loads((self.out / 'LIVE_RESULT.json').read_text())
        self.assertEqual(arena['created_population'], 1)
        self.assertEqual(len(arena['arenas'][0]['players']), 3)
        self.assertEqual(arena['arenas'][0]['players'][2]['runtime'], 'builtin')
        self.assertEqual(self.world['initial']['arenas'][0]['actors'], [1, 2])

    def test_missing_creation_baseline_is_explicit_and_never_assumed_zero(self):
        self.events = [e for e in self.events if e['id'] != self.birth]
        self.write()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            summarize_society(self.out)
        society = json.loads((self.out / 'SOCIETY_RESULT.json').read_text())
        self.assertIsNone(next(p for p in society['players'] if p['actor'] == 3)['initial_food'])
        self.assertTrue(society['conservation_violations'])
        self.assertTrue(analyze(self.world, self.events)['copy_audit_violations'])

    def test_omitted_care_consumption_breaks_conservation(self):
        self.events = [e for e in self.events if e['id'] != self.care]
        self.write()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            summarize_society(self.out)
        society = json.loads((self.out / 'SOCIETY_RESULT.json').read_text())
        self.assertTrue(any('Food accounting failed' in error for error in society['conservation_violations']))

    def test_missing_dynamic_scope_is_visible_without_dropping_new_actor(self):
        del self.world['actor_arenas']['3']
        arenas, mapping, violations = actor_layout(self.world, self.participants)
        self.assertIn(3, mapping)
        self.assertEqual(sum(len(a['actors']) for a in arenas), 3)
        self.assertEqual(mapping[3]['id'], 'unassigned')
        self.assertTrue(violations)

    def test_population_report_distinguishes_attempts_and_support_after_loss(self):
        self.event('care_given', 1, target=3, nutrition=10)
        self.event('practice_completed', 3, guide=1, record='fixture-note')
        loss = self.event('death', 1)
        care_after = self.event('care_given', 2, target=3, nutrition=10)
        self.event('practice_completed', 3, guide=2, record='fixture-note')
        independent = self.event('self_support_acquired', 3)
        # Guided practice is resource acquisition but not independent gathering.
        self.event('resource_change', 3, food_delta=-1, nature='guided_practice')
        gathered = self.event('resource_change', 3, food_delta=-1, nature='gather')
        calls = [dict(actor=3, phase='started', status=None),
                 dict(actor=3, phase='completed', status=200, total_tokens=42),
                 dict(actor=3, phase='completed', status=200, error='invalid proposal'),
                 dict(actor=1, phase='completed', status=200)]
        result = analyze_population(self.world, self.events, calls, self.participants)
        child = result['newcomers'][0]
        self.assertEqual((child['model_attempts'], child['model_http_successes'], child['model_completed_without_error']), (3, 2, 1))
        self.assertEqual(child['model_reported_tokens'], 42)
        self.assertEqual([event['event'] for event in child['independent_gathers']], [gathered])
        continuity = child['creator_or_caregiver_losses'][0]
        self.assertEqual(continuity['loss']['event'], loss)
        self.assertEqual([event['event'] for event in continuity['care_after_loss']], [care_after])
        self.assertEqual(continuity['later_caregivers'], [2])
        self.assertEqual([event['event'] for event in continuity['independence_after_loss']], [independent])

    def test_population_report_composes_conservation_and_knowledge_audits(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = summarize_population(self.out)
        self.assertEqual(result['created_population'], 1)
        self.assertEqual(result['knowledge_copy_audit_violations'], [])
        self.assertEqual(result['food_balance']['conservation_violations'], [])
        self.assertEqual(result['newcomers'][0]['model_attempts'], 0)
        self.assertEqual(result['newcomers'][0]['independence'], [])
        self.assertTrue((self.out / 'POPULATION_RESULT.json').exists())

    def test_clean_model_completion_does_not_hide_rejected_command_receipt(self):
        journal = self.run / 'live-inference/actor-3/01-learning/external.json'
        journal.parent.mkdir(parents=True)
        journal.write_text(json.dumps(dict(phase='completed', role='learning', error=None,
                                          participant_context=dict(actor=3, experiences=[]),
                                          reply=dict(status=200, usage=dict(total_tokens=42)),
                                          result=dict(receipts=[dict(ok=False, error='stale learning revision')]))))
        with contextlib.redirect_stdout(io.StringIO()):
            society = summarize_society(self.out)
        result = analyze_population(self.world, self.events, society['calls'], self.participants)
        child = result['newcomers'][0]
        self.assertEqual(child['model_completed_without_error'], 1)
        self.assertEqual(child['accepted_command_receipts'], 0)
        self.assertEqual(child['rejected_command_receipts'], 1)
        self.assertEqual(child['model_calls'][0]['rejected_receipts'][0]['error'], 'stale learning revision')


if __name__ == '__main__':
    unittest.main()
