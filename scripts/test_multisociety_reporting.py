"""Small recorded-authority fixtures; no simulator, provider or hosted-world runs."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from summarize_multisociety import analyze, summarize

ROOT = Path(__file__).resolve().parents[1]


class MultisocietyReportingChecks(unittest.TestCase):
    def setUp(self):
        initial = json.loads((ROOT / 'scenarios/multisociety-baseline.json').read_text())
        initial['knowledge'] = {}
        self.world = dict(initial=copy.deepcopy(initial), players=copy.deepcopy(initial['players']),
            sites=copy.deepcopy(initial['sites']),
            archives=[dict(**a, records=[], revision=0, destroyed=False) for a in initial['archives']],
            timing=dict(time_ms=10000, updates=200), version='multisociety-fixture')
        self.events = []

    def player(self, actor):
        return next(p for p in self.world['players'] if p['id'] == actor)

    def event(self, event_kind, actor=None, *, time=0, parents=None, **data):
        eid = len(self.events) + 1
        self.events.append(dict(id=eid, actor=actor, kind=event_kind, parents=parents or [],
                               data=dict(time_ms=time, **data)))
        return eid

    def receive(self, actor, record, *, time=0, new=True, sender=None, parent=None, via='teaching'):
        eid = self.event('perception', actor, time=time, parents=[parent] if parent else [],
            kind='knowledge_report', location=self.player(actor)['position'],
            content=dict(record=copy.deepcopy(record), new_copy=new, via=via), **{'from': sender})
        holdings = self.player(actor)['knowledge']
        existing = next((h for h in holdings if h['record']['id'] == record['id']), None)
        if existing:
            existing['source'] = eid
        else:
            holdings.append(dict(record=copy.deepcopy(record), source=eid,
                                 interpreted_source=None, interpretation=None, confidence=None))
        return eid

    def seed(self, actor, rid, text, *, topic='Western camp provisioning', location=82):
        record = dict(id=rid, text=text, topic=topic, location=location, author=actor,
                      origin=len(self.events) + 1, confidence=75)
        self.world['initial']['knowledge'].setdefault(str(actor), []).append(
            {key: record[key] for key in ('id', 'text', 'topic', 'location', 'confidence')})
        self.receive(actor, record, via='authored seed')
        return record

    def teach(self, actor, target, record, time, *, new=True):
        eid = self.event('knowledge_taught', actor, time=time, target=target, record=record['id'], new_copy=new)
        return self.receive(target, record, time=time, sender=actor, parent=eid, new=new)

    def move(self, actor, destination, start, end, *, decision=None):
        before = self.player(actor)['position']
        attempt = self.event('skill_attempt', actor, time=start, parents=[decision] if decision else [],
            action=dict(skill='move', destination=destination), before=dict(position=before))
        first = (before + (1 if destination % 16 > before % 16 else -1)) if before % 16 != destination % 16 else before + (16 if destination > before else -16)
        self.event('skill_progress', actor, time=start, parents=[attempt], position=first)
        arrival = self.event('skill_result', actor, time=end, parents=[attempt], status='completed',
                             skill='move', after=dict(position=destination))
        self.player(actor)['position'] = destination
        return arrival

    def gather(self, actor, time, *, decision=None, guard=None):
        location = self.player(actor)['position']
        attempt = self.event('skill_attempt', actor, time=time,
            parents=[source for source in (decision, guard) if source],
            action=dict(skill='gather'), before=dict(position=location))
        effect = self.event('resource_change', actor, time=time, parents=[attempt], location=location, food_delta=-1)
        self.player(actor)['food'] += 1
        next(s for s in self.world['sites'] if s['position'] == location)['food'] -= 1
        return effect

    def test_meeting_and_endpoint_are_not_knowledge_or_automatic_migration(self):
        self.move(3, 82, 1000, 2000)
        self.event('perception', 3, time=2500, kind='seen_player', location=82,
                   content=dict(name='Mira'), **{'from': 1})
        self.move(3, 93, 3000, 4000)
        result = analyze(self.world, self.events)
        resident = next(p for p in result['residence_evidence'] if p['actor'] == 3)
        self.assertEqual(result['evidence_audit_violations'], [])
        self.assertEqual(result['useful_report_distribution'], [])
        self.assertEqual(result['cross_origin_food_transfers']['total'], 0)
        self.assertEqual(resident['nonhome_camp_time_ms'], 1000)
        self.assertEqual(resident['camp_arrivals']['total'], 2)
        self.assertNotIn('migrated', resident)
        self.assertNotIn('migration_score', result)
        # An endpoint alone cannot fabricate a journey or a residence interval.
        self.player(4)['position'] = 82
        bad = analyze(self.world, self.events)
        other = next(p for p in bad['residence_evidence'] if p['actor'] == 4)
        self.assertEqual(other['nonhome_camp_time_ms'], 0)
        self.assertTrue(any('Actor 4 final position' in error for error in bad['evidence_audit_violations']))

    def test_residence_ends_at_death_and_fixed_population_is_audited(self):
        self.move(3, 82, 1000, 2000)
        death = self.event('death', 3, time=3500)
        self.player(3)['health'] = 0
        result = analyze(self.world, self.events)
        resident = next(p for p in result['residence_evidence'] if p['actor'] == 3)
        self.assertEqual(resident['nonhome_camp_time_ms'], 1500)
        interval = resident['nonhome_residence_intervals']['shown'][0]
        self.assertEqual(interval['ended_by'], 'death')
        self.assertEqual(interval['exit']['event'], death)
        self.assertEqual(result['evidence_audit_violations'], [])
        child = copy.deepcopy(self.player(6)); child.update(id=7, name='Unexpected new actor', food=0)
        self.world['players'].append(child)
        self.event('actor_created', 7, time=4000, initial_resources=dict(food=0, health=100))
        result = analyze(self.world, self.events)
        self.assertTrue(any('actor_created' in error for error in result['evidence_audit_violations']))
        self.assertTrue(any('Final actor identities' in error for error in result['evidence_audit_violations']))

    def test_integer_damage_after_does_not_become_movement_or_break_residence(self):
        self.event('damage', 3, time=500, before=100, after=92, amount=8,
                   cause_kind='starvation', location=93)
        arrival = self.move(3, 82, 1000, 2000)
        self.event('damage', 3, time=2500, before=92, after=84, amount=8,
                   cause_kind='starvation', location=82)
        self.player(3)['health'] = 84
        result = analyze(self.world, self.events)
        resident = next(p for p in result['residence_evidence'] if p['actor'] == 3)
        self.assertEqual(result['evidence_audit_violations'], [])
        self.assertEqual(resident['final_position'], 82)
        self.assertEqual(resident['nonhome_camp_time_ms'], 8000)
        self.assertEqual(resident['camp_arrivals']['total'], 1)
        self.assertEqual(resident['camp_arrivals']['shown'][0]['event'], arrival)

    def test_false_claims_keep_distinct_lineage_and_repeat_receipts(self):
        positive = self.seed(5, 'western-provisioning', 'Food regrows in the western camp.')
        contrary = self.seed(4, 'western-provisioning-denial', 'Food never regrows in the western camp.')
        original = self.teach(5, 3, positive, 100)
        latest = self.teach(5, 3, positive, 200, new=False)
        self.teach(4, 3, contrary, 300)
        self.event('identity_change', 3, time=400,
            reflections=[dict(source=original, interpretation='These reports conflict; I should check.')])
        holding = next(h for h in self.player(3)['knowledge'] if h['record']['id'] == positive['id'])
        holding.update(interpretation='These reports conflict; I should check.', interpreted_source=original)
        result = analyze(self.world, self.events)
        reports = {r['record']['id']: r for r in result['useful_report_distribution']}
        self.assertEqual(set(reports), {positive['id'], contrary['id']})
        self.assertEqual(reports[positive['id']]['record']['author'], 5)
        self.assertEqual(reports[contrary['id']]['record']['author'], 4)
        self.assertEqual(reports[positive['id']]['repeat_receipts'], 1)
        self.assertEqual(reports[positive['id']]['repeat_copy_operations'], {'knowledge_taught': 1})
        self.assertEqual(reports[positive['id']]['first_nonseed_copy_counts_by_origin'], {'93': 1})
        self.assertEqual(reports[contrary['id']]['first_nonseed_copy_counts_by_origin'], {'93': 1})
        assessed = next(h for h in reports[positive['id']]['final_personal_interpretations'] if h['actor'] == 3)
        self.assertEqual((assessed['source'], assessed['interpreted_source']), (latest, original))
        self.assertEqual(result['knowledge_audit']['copy_audit_violations'], [])

    def test_only_explicit_citations_upgrade_temporal_action_associations(self):
        positive = self.seed(5, 'western-provisioning', 'Food regrows in the western camp.')
        contrary = self.seed(4, 'western-provisioning-denial', 'Food never regrows in the western camp.')
        receipt = self.teach(5, 3, positive, 100)
        self.teach(4, 3, contrary, 200)
        decision = self.event('decision', 3, time=900,
            reported_explanation='I want to test western-provisioning-denial.')
        arrival = self.move(3, 82, 1000, 2000, decision=decision)
        temporal_gather = self.gather(3, 2100)
        guard = self.event('guard_evaluated', 3, time=2200, parents=[decision, receipt],
            condition=dict(kind='has_knowledge', record=positive['id']), result=True)
        explicit_gather = self.gather(3, 2300, decision=decision, guard=guard)
        result = analyze(self.world, self.events)
        rows = {row['record']: row for row in result['subsequent_action_evidence'] if row['actor'] == 3}
        positive_links = {e['event']: e for e in rows[positive['id']]['shown']}
        contrary_links = {e['event']: e for e in rows[contrary['id']]['shown']}
        # The denial ID must not accidentally match its positive ID prefix.
        self.assertEqual(positive_links[arrival]['connection'], 'temporal association only')
        self.assertTrue(contrary_links[arrival]['explicit_references'])
        self.assertEqual(positive_links[temporal_gather]['connection'], 'temporal association only')
        self.assertEqual(positive_links[explicit_gather]['explicit_references'][0]['receipts'], [receipt])

    def test_cross_origin_transfer_and_deposit_do_not_invent_fungible_item_provenance(self):
        self.move(3, 82, 1000, 2000)
        collected = self.gather(3, 2100)
        give = self.event('skill_attempt', 1, time=2200, action=dict(skill='give', target=3))
        transfer = self.event('food_transfer', 1, time=2200, parents=[give], target=3, location=82, amount=1)
        self.player(1)['food'] -= 1; self.player(3)['food'] += 1
        self.move(3, 93, 3000, 4000)
        deposit = self.event('resource_change', 3, time=4100, location=93, food_delta=1, nature='deposit')
        self.player(3)['food'] -= 1
        next(s for s in self.world['sites'] if s['position'] == 93)['food'] += 1
        result = analyze(self.world, self.events)
        flow = result['cross_origin_food_transfers']['shown'][0]
        self.assertEqual((flow['event'], flow['source_initial_home'], flow['target_initial_home'], flow['location'], flow['amount']),
                         (transfer, 82, 93, 82, 1))
        moved = result['camp_deposits']['shown'][0]
        self.assertEqual(moved['event'], deposit)
        self.assertEqual(moved['earlier_gathering_elsewhere'][0]['first']['event'], collected)
        self.assertEqual(moved['earlier_gathering_elsewhere'][0]['first']['site_initial_residents'], [1, 2])
        self.assertIn('fungible', moved['interpretation'])
        self.assertNotIn('item_source', moved)
        self.assertEqual(result['evidence_audit_violations'], [])

    def test_geometry_surveys_are_excluded_from_distribution_but_still_audited(self):
        survey = self.seed(1, 'settlement-survey-1', 'The camps are at cells82,93,152.',
                           topic='Surveyed settlement locations', location=None)
        self.teach(1, 3, survey, 100)
        result = analyze(self.world, self.events)
        self.assertEqual(result['useful_report_distribution'], [])
        self.assertEqual(result['knowledge_audit']['all_new_copy_operations'], {'knowledge_taught': 1})
        self.assertEqual(result['knowledge_audit']['copy_audit_violations'], [])
        self.player(4)['knowledge'] = [dict(record=survey, source=999)]
        result = analyze(self.world, self.events)
        self.assertTrue(result['knowledge_audit']['copy_audit_violations'])

    def test_composed_report_hashes_snapshot_and_preserves_shared_audits(self):
        self.move(3, 82, 1000, 2000)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory); run = out / 'fixture-run'; run.mkdir()
            (out / 'pilot.json').write_text(json.dumps(dict(run='fixture-run', phase='completed')))
            source = run / 'final-snapshot.json'
            source.write_text(json.dumps(dict(world=self.world, events=self.events)))
            before = source.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                result = summarize(out)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(result['source_sha256'], hashlib.sha256(before).hexdigest())
            self.assertEqual(result['rules_version'], 'multisociety-fixture')
            self.assertEqual(result['food_balance']['conservation_violations'], [])
            self.assertEqual(result['knowledge_audit']['copy_audit_violations'], [])
            self.assertEqual(result['base_check_failures'], [])
            self.assertTrue((out / 'MULTISOCIETY_RESULT.json').is_file())
            self.assertTrue((out / 'KNOWLEDGE_RESULT.json').is_file())
            self.assertTrue((out / 'SOCIETY_RESULT.json').is_file())


if __name__ == '__main__':
    unittest.main()
