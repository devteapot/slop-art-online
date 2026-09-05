#!/usr/bin/env python3
"""Resolve Stage 4 multi-settlement inputs without launching hosted worlds or models.

Geography, uneven food sources, individual motives and private prior reports are
seed content. Ordinary home habits contain no chosen exchange, teaching or
migration sequence. Population renewal is disabled: relocation uses existing IDs.
"""
import argparse
import copy
import json
from pathlib import Path

from starting_behavior_presets import make_starters

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = 'output/society-lab/implementations/multisociety-m4-1'
MINUTES = 8
CAMPS = {'A': 82, 'B': 93, 'C': 152}
CAMP_BY_ACTOR = {1: 'A', 2: 'A', 3: 'B', 4: 'B', 5: 'C', 6: 'C',
                 7: 'A', 8: 'A', 9: 'B', 10: 'B', 11: 'C', 12: 'C'}
NAMES = ('Mira', 'Tovan', 'Iri', 'Renn', 'Sela', 'Oren', 'Neri', 'Venn', 'Tess', 'Vale', 'Kira', 'Aren')
PROFILES = ('shared_provider', 'reserve_keeper', 'builder', 'cautious_observer',
            'cautious_observer', 'shared_provider', 'reserve_keeper', 'builder',
            'shared_provider', 'cautious_observer', 'builder', 'reserve_keeper')
ROLES = ('western neighbor', 'reserve planner', 'eastern resident', 'independent neighbor',
         'report keeper', 'southern resident', 'practical harvester', 'careful contributor',
         'eastern companion', 'curious forager', 'record enthusiast', 'southern neighbor')
MOTIVES = (
    'I want a lasting western home where our work matters. I value helpful relations with '
    'other settlements and am curious about their experiences. I am willing to consider '
    'sharing carried food or exchanging useful information while keeping myself capable.',
    'I want reliable personal and western camp reserves. I prefer concrete reciprocal '
    'help to vague promises and want to understand the cost of any commitment. Neighbors '
    'may have useful information, but I make my own decisions about assistance.',
    'I care about our eastern community and would like it to remain a viable home. I '
    'want to assess actual stocks and credible options when supplies become uncertain. '
    'I may seek help or information from neighbors, without assuming they owe me either.',
    'I value independence and a dependable food supply. I am willing to consider a '
    'different place to live if the evidence suggests it would support me better. I '
    'want to question reports, weigh travel and local obligations, and choose for myself.',
    'I have a private field note about the western camp. I want useful accounts to be '
    'deliberately taught or preserved where others can assess them. I value careful '
    'verification and neighbors who explain what they observe. I also need to stay fed '
    'and rested; possessing a report does not oblige me to take a particular journey.',
    'I want the southern camp to remain a viable home. I welcome respectful visitors '
    'when resources permit, and I am interested in what other communities learn. I '
    'want help and hospitality to be sustainable, with honest accounts of actual needs.',
    'I take pride in practical work at the western camp. I am curious whether other '
    'people have useful observations or unmet needs, but I want any commitments to '
    'leave enough food and energy for myself and my neighbors.',
    'I want to contribute to a dependable western home without being taken for granted. '
    'I value clear explanations and concrete reciprocal help. I prefer checking actual '
    'conditions to assuming that a settlement label guarantees abundance.',
    'I want my eastern companions to have a fair chance of staying well. I value this '
    'home but could reconsider where I live if it cannot support us. I want to hear '
    'credible options and decide what help I can realistically give or request.',
    'I am curious about other settlements and careful about untested reports. I want '
    'to compare claims with experience and find a dependable way to remain supplied, '
    'whether here in the east or elsewhere. I do not want promises mistaken for food.',
    'I value a southern community where useful accounts are preserved and different '
    'claims can be examined. I want to learn from people with direct experience and '
    'consider helping others understand it, while maintaining my own basic needs.',
    'I want friendly and practical relations at the southern camp. I am willing to '
    'consider assistance and newcomers, but I pay attention to food stocks and my own '
    'energy. I would like disagreements to be discussed without assuming agreement.',
)
SURVEY_TEXT = (
    'My copy of the public terrain survey locates the western camp at cell 82, the '
    'eastern camp at cell 93, and the southern camp at cell 152. Cell ID is y * 16 + x. '
    'This survey records settlement positions only; it reports no current stocks, '
    'production, conditions or inhabitants.'
)
POSITIVE_ID = 'western-provisioning'
CONTRARY_ID = 'western-provisioning-denial'
# Current law: 2 hunger per 2500 ms; an actual meal removes up to 35 hunger.
REFERENCE_MEALS_PER_PERSON_MINUTE = (60000 / 2500 * 2) / 35
ORDINARY_SKILLS = {'move', 'eat', 'rest', 'gather', 'build', 'deposit', 'observe', 'wait'}


def read(relative):
    return json.loads((ROOT / relative).read_text())


def actions(value):
    if isinstance(value, dict):
        if value.get('kind') == 'action':
            yield value['action']
        for child in value.values():
            yield from actions(child)
    elif isinstance(value, list):
        for child in value:
            yield from actions(child)


def survey(actor):
    # Distinct personal seed assertions, never falsely logged as one transmitted copy.
    return dict(id=f'settlement-survey-{actor}', topic='Surveyed settlement locations',
                text=SURVEY_TEXT, location=None, confidence=90)


def make_scenario(base, name, *, scale=False, pressure=False, disputed=False):
    factor = 2 if scale else 1
    population = 6 * factor
    s = copy.deepcopy(base)
    s.update(name=name, max_ticks=MINUTES * 24, players=[], starting_behaviors={},
             lifecycle=None, disturbances=[], knowledge={},
             sites=[dict(position=CAMPS[camp], food=food * factor, hazard=0, shelter=12)
                    for camp, food in [('A', 6), ('B', 0), ('C', 4)]],
             food_sources=[dict(position=CAMPS[camp], interval_ms=interval,
                                amount=factor, capacity=capacity * factor)
                           for camp, interval, capacity in [('A', 10000, 12), ('B', 30000, 6), ('C', 20000, 8)]
                           if not (pressure and camp == 'B')],
             archives=[dict(id=1, position=CAMPS['C'], label='Southern shared archive', capacity=16)])
    for actor in range(1, population + 1):
        index = actor - 1
        home = CAMPS[CAMP_BY_ACTOR[actor]]
        player = copy.deepcopy(base['players'][index % len(base['players'])])
        player.update(id=actor, name=NAMES[index], controller='ai', role=ROLES[index],
                      motive=MOTIVES[index], position=home, health=100, hunger=20,
                      energy=80, food=2, fear=0, current_goal=None, knowledge=[], beliefs=[],
                      memories=[], site_observations=[], relationships={}, execution=None,
                      generation=0, failures=0, last_reflection=0, last_cause=None)
        s['players'].append(player)
        s['knowledge'][str(actor)] = [survey(actor)]
        s['starting_behaviors'][str(actor)] = copy.deepcopy(make_starters(home)[PROFILES[index]])
    s['knowledge']['5'].append(dict(id=POSITIVE_ID, topic='Western camp provisioning',
        text='My field note from the western camp at cell 82: I observed food regrowing '
             'there and a substantial shared shelter, without a local environmental hazard. '
             'This makes it a plausible provisioning option, not a promise of free meals '
             'or an agreement from its residents. Check the current stock and conditions '
             'when you arrive; demand can change what is available.',
        location=CAMPS['A'], confidence=75))
    if disputed:
        s['knowledge']['4'].append(dict(id=CONTRARY_ID, topic='Western camp provisioning',
            text='My earlier account says the western camp at cell 82 does not regrow '
                 'food: once its stored supply is taken there will be nothing to gather. '
                 'I would not rely on that camp for continuing provisions. This is a '
                 'report rather than my observation of its present condition.',
            location=CAMPS['A'], confidence=75))
    s['arenas'][0].update(id='connected-settlements', label='Three connected settlements',
        environment='multisociety-settlement', variant='luna-medium',
        actors=list(range(1, population + 1)),
        controllers={str(actor): 'builtin' if actor % 2 else 'external' for actor in range(1, population + 1)})
    return s


def validate(scenario, controllers, *, scale=False, pressure=False, disputed=False):
    factor = 2 if scale else 1
    actors = list(range(1, 6 * factor + 1))
    assert scenario['map'] == read('scenarios/settlement-renewable.json')['map']
    assert (scenario['map']['width'], scenario['map']['height']) == (16, 12)
    assert scenario['weather'] == read('scenarios/settlement-renewable.json')['weather']
    assert len(scenario['arenas']) == 1, 'settlements must not become isolated arenas'
    arena = scenario['arenas'][0]
    assert arena['actors'] == actors
    assert [p['id'] for p in scenario['players']] == actors
    assert len({p['name'] for p in scenario['players']}) == len(actors)
    assert [c['actor'] for c in controllers] == actors
    assert scenario['max_ticks'] * 2500 == MINUTES * 60000
    assert scenario['lifecycle'] is None, 'migration must use existing people, not created replacements'
    assert scenario['disturbances'] == []
    assert scenario['archives'] == [dict(id=1, position=CAMPS['C'], label='Southern shared archive', capacity=16)]
    assert scenario['sites'] == [dict(position=CAMPS[camp], food=food * factor, hazard=0, shelter=12)
                                 for camp, food in [('A', 6), ('B', 0), ('C', 4)]]
    expected_sources = [dict(position=CAMPS[camp], interval_ms=interval, amount=factor, capacity=capacity * factor)
        for camp, interval, capacity in [('A', 10000, 12), ('B', 30000, 6), ('C', 20000, 8)]
        if not (pressure and camp == 'B')]
    assert scenario['food_sources'] == expected_sources
    record_ids = []
    for player, controller in zip(scenario['players'], controllers):
        actor = player['id']
        assert player['position'] == CAMPS[CAMP_BY_ACTOR[actor]]
        assert player['controller'] == 'ai'
        assert (player['health'], player['hunger'], player['energy'], player['food']) == (100, 20, 80, 2)
        assert not player['knowledge'] and not player['beliefs'] and not player['memories']
        assert not player['site_observations'] and not player['relationships']
        assert controller['role'] == arena['controllers'][str(actor)]
        assert controller['config']['backend']['model'] == 'gpt-5.6-luna'
        assert controller['config']['backend']['reasoning_effort'] == 'medium'
        records = scenario['knowledge'][str(actor)]
        assert records[0] == survey(actor)
        extras = [r['id'] for r in records[1:]]
        assert extras == ([POSITIVE_ID] if actor == 5 else [CONTRARY_ID] if disputed and actor == 4 else [])
        record_ids.extend(r['id'] for r in records)
        habit = scenario['starting_behaviors'][str(actor)]
        assert habit == make_starters(player['position'])[PROFILES[actor - 1]]
        for a in actions(habit['tree']):
            assert a['skill'] in ORDINARY_SKILLS
            if a['skill'] == 'move':
                assert a['destination'] == player['position'], 'no authored inter-settlement itinerary'
    assert len(record_ids) == len(set(record_ids)), 'personal survey copies need distinct seed identities'
    positive = scenario['knowledge']['5'][1]
    assert positive['location'] == CAMPS['A'] and positive['confidence'] == 75
    if disputed:
        contrary = scenario['knowledge']['4'][1]
        assert contrary['location'] == positive['location'] and contrary['topic'] == positive['topic']
        assert contrary['id'] != positive['id']
    production = sum(60000 * source['amount'] / source['interval_ms'] for source in scenario['food_sources'])
    reference_need = REFERENCE_MEALS_PER_PERSON_MINUTE * len(actors)
    assert production == (9 if pressure else 11) * factor and production > reference_need
    assert all(sum(CAMP_BY_ACTOR[a] == camp for a in actors) == 2 * factor for camp in CAMPS)
    distance = lambda a, b: abs(a % 16 - b % 16) + abs(a // 16 - b // 16)
    trips = {f'{a}-{b}': distance(CAMPS[a], CAMPS[b]) for a, b in [('A', 'B'), ('A', 'C'), ('B', 'C')]}
    assert trips == {'A-B': 11, 'A-C': 10, 'B-C': 9}
    return dict(initial_population=len(actors), camp_populations={camp: 2 * factor for camp in CAMPS},
        camps=CAMPS, camp_trip_cells=trips, nominal_food_per_minute=production,
        reference_meals_per_minute=round(reference_need, 4),
        initial_carried_food=2 * len(actors), initial_pantry_food=10 * factor,
        positive_report_initial_holder=5, contrary_report_initial_holder=4 if disputed else None,
        initially_empty_archive=1, population_renewal=False)


def build():
    base = read('scenarios/settlement-renewable.json')
    config = read('configs/experiments/society-four-medium.json')[0]['config']
    outputs, summaries, variants = {}, {}, []
    specs = [('baseline', 'Three settlements with uneven supplies', {}),
             ('pressure', 'Eastern provisioning loss and migration pressure', dict(pressure=True)),
             ('scale', 'Twelve people across three settlements', dict(scale=True)),
             ('disputed', 'Conflicting reports under eastern migration pressure', dict(pressure=True, disputed=True))]
    scenarios = {}
    for index, (name, label, options) in enumerate(specs):
        scenario = make_scenario(base, label, **options)
        scenarios[name] = scenario
        count = len(scenario['players'])
        controllers = [dict(actor=p['id'], role=scenario['arenas'][0]['controllers'][str(p['id'])],
                            config=copy.deepcopy(config)) for p in scenario['players']]
        scenario_path = f'scenarios/multisociety-{name}.json'
        controller_path = f'configs/experiments/multisociety-{count}-medium.json'
        outputs[scenario_path] = scenario
        outputs[controller_path] = controllers
        summaries[name] = validate(scenario, controllers, **options)
        variants.append(dict(id=name, port=18968 + index, implementation=IMPLEMENTATION,
            scenario=f'{IMPLEMENTATION}/{scenario_path}', controllers=f'{IMPLEMENTATION}/{controller_path}', recovery=True))
    baseline = copy.deepcopy(scenarios['baseline']); baseline.pop('name')
    pressure = copy.deepcopy(scenarios['pressure']); pressure.pop('name')
    baseline['food_sources'] = [s for s in baseline['food_sources'] if s['position'] != CAMPS['B']]
    assert baseline == pressure, 'pressure must change only the eastern source, apart from name'
    disputed = copy.deepcopy(scenarios['disputed']); disputed.pop('name')
    disputed['knowledge']['4'].pop()
    assert disputed == pressure, 'disputed must add only one private report, apart from name'
    outputs['configs/experiments/campaign/015-multisociety.json'] = dict(
        hypothesis='Existing inhabitants of three connected settlements with uneven food and knowledge may '
            'choose travel, actual food transfers, deliberate teaching, shared archive use or relocation. '
            'Removing the eastern source increases local pressure while keeping total renewable support '
            'viable. A mistaken contrary report can influence choices only through the private holder or '
            'actual communication; proximity never copies reports or establishes agreement.',
        evaluation='Run four concurrent eight-minute fresh Luna-medium variants on frozen multisociety-m4-1, '
            'with fifteen-second post-completion cadence and no call cap. All camps share one arena: A82, '
            'B93 and C152 on the16x12 survey, with camp trips11/10/9 cells (roughly2.75/2.5/2.25 seconds and '
            'the same number of movement energy units before interruptions). Each camp has shelter12, '
            'zero site hazard and the retained base weather; travel incurs ordinary movement and exposure '
            'costs. Baseline production A6+B2+C3=11 food/minute exceeds six-person reference demand8.229. '
            'Pressure removes only B production, leaving9 globally sufficient but B locally dependent '
            'on carried reserves, imports or relocation. Disputed matches pressure except for actor4 '
            'holding a distinct mistaken western-provisioning-denial report. Its claim that A never '
            'regrows food is false under the retained physical inputs, but its transmission and assessment '
            'are not guaranteed. Scale doubles residents per camp, source amounts/capacities and initial '
            'pantries, giving22 food/minute versus twelve-person reference demand16.457. Per-person starting '
            'food, body needs and travel costs stay fixed; the original positive author5 and one empty '
            'archive of capacity16 are not multiplied, so this is a communication-load challenge rather '
            'than a single-factor estimate of population effects. Measure actual production, ceilings, '
            'food gathered/transferred/deposited/eaten, waste, health, deaths and food stranded on bodies; '
            'the nominal budget assumes room for growth and full35-hunger meals. All initial actors carry2 '
            'food, with pantries A6/B0/C4 (doubled in scale). Everyone holds a separate uniquely identified '
            'personal copy of a public geometry-only survey; these authored priors are not live transmission '
            'events and disclose no remote resources. Only C5 starts with the typed western-provisioning '
            'report describing A actual renewable food/shelter. A residents can observe their own source '
            'without acquiring that exact report. Trace first inter-settlement report acquisition, source '
            'and authorship, accepted personal interpretation, chosen journey and observed outcome; '
            'distinguish an arrival at empty stock or independent discovery from useful transmitted '
            'knowledge. Record actual cross-origin food transfers and subsequent consumption or provisioning; '
            'speech alone is not material exchange, and gifts or informal reciprocity are not enforced '
            'trade contracts. Classify origin from initial camp, then describe repeated provisioning, rest, '
            'residence and expressed intentions to distinguish relocation from a visit; a final coordinate '
            'alone is insufficient migration evidence. Lifecycle is null, no newcomers are enrolled, and '
            'no disturbance spawns actors: all movement preserves existing IDs. Ordinary revisable home '
            'habits contain no inter-camp itinerary, speech, teaching or exchange sequence. Shared beliefs, '
            'cooperation, specialization, isolation or dispute require actual choices and communication. '
            'Keep rejected operations, absent contact and resource failures in the result; do not infer '
            'formal ownership, binding agreements or alliances. Record elapsed simulation/wall time, '
            'model calls/usage/errors, engine/scope/conservation checks, remaining knowledge copies and '
            'archive contents. One fresh run per condition is descriptive evidence, not reproducibility.',
        minutes=MINUTES, calls_per_actor=0, serial_ms=15000, variants=variants)
    return outputs, summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='validate controls and compare generated JSON without writing')
    args = parser.parse_args()
    outputs, summaries = build()
    for relative, value in outputs.items():
        path = ROOT / relative
        if args.check:
            if not path.is_file() or json.loads(path.read_text()) != value:
                raise SystemExit(f'Generated input differs: {relative}')
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(value, indent=2) + '\n'
            if not path.exists() or path.read_text() != serialized:
                path.write_text(serialized)
    print(json.dumps(dict(mode='checked' if args.check else 'prepared', candidates=summaries,
        note='These are authored controls and nominal budgets. No hosted worlds or models launched; '
             'actual interaction, resource availability and migration remain unobserved.'), indent=2))


if __name__ == '__main__':
    main()
