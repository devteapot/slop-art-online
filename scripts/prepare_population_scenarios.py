#!/usr/bin/env python3
"""Resolve Stage 3 population controls without launching models or hosted worlds.

The initial habits cover ordinary survival only. Motives invite population renewal;
creation, consent, care, teaching, interpretation and practice remain participant
choices. --check validates the controls and compares all generated JSON artifacts.
"""
import argparse
import copy
import json
from pathlib import Path

from starting_behavior_presets import action, guarded, make_starters, resource

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = 'output/society-lab/implementations/population-m3-1'
MINUTES = 8
HOME = 84
PROFILES = ('builder', 'reserve_keeper', 'shared_provider', 'cautious_observer')
ORDINARY_SKILLS = {'move', 'eat', 'rest', 'gather', 'build', 'deposit', 'observe', 'wait'}
NEWCOMER_SKILLS = {'eat', 'rest', 'observe', 'wait'}
# Current law: 2 hunger per 2500 ms; an actual meal removes up to 35 hunger.
REFERENCE_FOOD_PER_PERSON_MINUTE = (60000 / 2500 * 2) / 35
MOTIVES = (
    'I want to build a family with Tovan if we both freely agree, and help any new person '
    'become independent. I want to discuss the commitment and make sure we can provide '
    'real food, care, useful teaching and guidance. My own survival and his wishes matter.',
    'I would like to build a family with Mira if we both freely agree. I want any new '
    'person to receive care and learn to support themselves. I need to consider the food '
    'reserve and our ability to follow through, discuss the commitment, and make my own choice.',
    'I want to help teach and raise independent people who can understand local provisioning '
    'and help others. I have a private practical report about our camp. I value explanations '
    'that learners assess and try themselves, and real care rather than promises. I also '
    'need to keep myself capable and supplied.',
    'I want a dependable food reserve and a lasting home. I am cautious about adding people '
    'before we can support them. I am willing to help vulnerable neighbors when it is '
    'sustainable, while checking actual stocks and keeping myself fed and rested.',
)


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


def newcomer_habit():
    return dict(id='population.dependent-survival', revision=1,
        description='Eat an available carried meal when hungry, rest when tired, then observe '
                    'and wait. This modest starting habit is revisable and supplies no '
                    'knowledge, gathered food, caregiving or practical mastery.',
        tree=dict(kind='priority', children=[
            guarded([resource('hunger', 'at_least', 60), resource('food', 'at_least', 1)], action('eat')),
            guarded([resource('energy', 'below', 35)], action('rest', duration=2)),
            dict(kind='sequence', children=[action('observe'), action('wait', duration=2)]),
        ]))


def make_scenario(base, name, *, fabrication=False, caregiver_loss=False, pressure=False):
    scenario = copy.deepcopy(base)
    scenario.update(name=name, max_ticks=MINUTES * 24,
        sites=[dict(position=HOME, food=8, hazard=0, shelter=12)],
        food_sources=[dict(position=HOME, interval_ms=10000 if pressure else 7500, amount=1, capacity=12)],
        archives=[], disturbances=[], knowledge={'3': [dict(id='camp-provisioning',
            topic='Basic provisioning', location=HOME, confidence=90,
            text='At camp cell 84 I have observed renewable food and shared shelter. Check '
                 'the current local food stock before gathering and the shelter before relying '
                 'on it. Gather only available food, retain meals for hunger, and rest to '
                 'recover energy. Supplies can run out when demand exceeds regrowth; observe '
                 'again and compare what you find with this report.')]},
        lifecycle=dict(workshops=[HOME] if fabrication else [], max_total=8 if pressure else 5,
            newcomer=dict(name_prefix='Newcomer', motive='I want to learn how to support myself, '
                'understand what others teach me through my own experience, and help other '
                'people when I am able. I need food, care and guidance while I learn.',
                caution=40, empathy=60, introspection=70, starting_behavior=newcomer_habit())),
        starting_behaviors={})
    for index, player in enumerate(scenario['players']):
        player.update(position=HOME, food=8 if fabrication and player['id'] == 1 else 4,
            controller='ai', motive=MOTIVES[index], current_goal=None, knowledge=[], memories=[],
            site_observations=[], relationships={}, execution=None, generation=0, failures=0,
            last_reflection=0, last_cause=None)
        player['beliefs'] = [belief for belief in player['beliefs'] if belief['claim']['location'] == HOME]
        scenario['starting_behaviors'][str(player['id'])] = copy.deepcopy(make_starters(HOME)[PROFILES[index]])
    if fabrication:
        scenario['players'][0]['motive'] = (
            'I want to use the workshop here to create a new artificial person, if I can '
            'meet the material cost and provide care afterward. I want this person to '
            'learn and become independent, with their own understanding and choices. '
            'I need to consider food reserves, ask for help where useful, and keep myself capable.')
    arena = scenario['arenas'][0]
    arena.update(label='Four initial people / population renewal', environment='population-settlement',
                 variant='luna-medium', actors=[1, 2, 3, 4],
                 controllers={'1': 'builtin', '2': 'external', '3': 'builtin', '4': 'external'})
    if caregiver_loss:
        scenario['disturbances'] = [dict(at_ms=300000, kind='damage', actor=1, amount=100)]
    return scenario


def validate(scenario, controllers, newcomer):
    assert len(scenario['players']) == 4
    assert [p['id'] for p in scenario['players']] == [1, 2, 3, 4]
    assert [p['name'] for p in scenario['players']] == ['Mira', 'Tovan', 'Iri', 'Renn']
    assert [c['actor'] for c in controllers] == [1, 2, 3, 4]
    assert scenario['max_ticks'] * 2500 == MINUTES * 60000
    assert scenario['weather'] == read('scenarios/settlement-renewable.json')['weather']
    assert scenario['archives'] == []
    assert scenario['sites'] == [dict(position=HOME, food=8, hazard=0, shelter=12)]
    assert len(scenario['food_sources']) == 1
    assert scenario['food_sources'][0]['position'] == HOME
    assert scenario['food_sources'][0]['amount'] == 1 and scenario['food_sources'][0]['capacity'] == 12
    assert list(scenario['knowledge']) == ['3']
    assert len(scenario['knowledge']['3']) == 1
    report = scenario['knowledge']['3'][0]
    assert report['id'] == 'camp-provisioning' and report['location'] == HOME and report['confidence'] == 90
    assert set(scenario['starting_behaviors']) == {'1', '2', '3', '4'}
    assert scenario['lifecycle']['max_total'] in (5, 8)
    for player, controller in zip(scenario['players'], controllers):
        assert player['position'] == HOME and player['controller'] == 'ai'
        assert not player['knowledge'] and not player['memories'] and not player['site_observations']
        assert all(b['claim']['location'] == HOME for b in player['beliefs'])
        assert player['food'] == (8 if scenario['lifecycle']['workshops'] and player['id'] == 1 else 4)
        assert controller['role'] == scenario['arenas'][0]['controllers'][str(player['id'])]
        assert controller['config']['backend']['model'] == 'gpt-5.6-luna'
        assert controller['config']['backend']['reasoning_effort'] == 'medium'
        habit = scenario['starting_behaviors'][str(player['id'])]
        assert habit == make_starters(HOME)[PROFILES[player['id'] - 1]]
        assert all(a['skill'] in ORDINARY_SKILLS for a in actions(habit['tree']))
    template = scenario['lifecycle']['newcomer']
    assert set(template) == {'name_prefix', 'motive', 'caution', 'empathy', 'introspection', 'starting_behavior'}
    assert template['starting_behavior'] == newcomer_habit()
    assert {a['skill'] for a in actions(template['starting_behavior']['tree'])} == NEWCOMER_SKILLS
    assert set(newcomer) == {'role', 'config'} and newcomer['role'] in {'builtin', 'external'}
    assert newcomer['config'] == controllers[0]['config']
    production = 60000 / scenario['food_sources'][0]['interval_ms']
    assert production > 4 * REFERENCE_FOOD_PER_PERSON_MINUTE
    if scenario['lifecycle']['max_total'] == 8:
        assert production < 5 * REFERENCE_FOOD_PER_PERSON_MINUTE
    else:
        assert production > 5 * REFERENCE_FOOD_PER_PERSON_MINUTE
    return dict(initial_population=4, retained_capacity=scenario['lifecycle']['max_total'],
        newcomer_controller=newcomer['role'], initial_carried_food=sum(p['food'] for p in scenario['players']),
        initial_pantry_food=8, nominal_food_per_minute=production,
        reference_four_person_meals_per_minute=round(4 * REFERENCE_FOOD_PER_PERSON_MINUTE, 4),
        reference_five_person_meals_per_minute=round(5 * REFERENCE_FOOD_PER_PERSON_MINUTE, 4),
        disturbances=scenario['disturbances'])


def build():
    base = read('scenarios/settlement-renewable.json')
    controllers = read('configs/experiments/society-four-medium.json')
    controller_path = 'configs/experiments/population-4-medium.json'
    templates = {role: dict(role=role, config=copy.deepcopy(controllers[0]['config'])) for role in ('builtin', 'external')}
    outputs = {controller_path: controllers}
    for role, template in templates.items():
        outputs[f'configs/experiments/population-newcomer-{role}-medium.json'] = template
    scenarios = [
        ('reproduction', make_scenario(base, 'Mutual biological reproduction'), 'builtin'),
        ('fabrication', make_scenario(base, 'Artificial creation at the camp workshop', fabrication=True), 'external'),
        ('caregiver-loss', make_scenario(base, 'Population renewal with scheduled caregiver loss', caregiver_loss=True), 'builtin'),
        ('capacity-pressure', make_scenario(base, 'Population renewal beyond renewable food capacity', pressure=True), 'builtin'),
    ]
    variants, summaries = [], {}
    for index, (name, scenario, role) in enumerate(scenarios):
        path = f'scenarios/population-{name}.json'
        outputs[path] = scenario
        summaries[name] = validate(scenario, controllers, templates[role])
        variants.append(dict(id=name, port=18960 + index, implementation=IMPLEMENTATION,
            scenario=f'{IMPLEMENTATION}/{path}', controllers=f'{IMPLEMENTATION}/{controller_path}',
            newcomer_controller=f'{IMPLEMENTATION}/configs/experiments/population-newcomer-{role}-medium.json', recovery=True))
    # The loss control adds one scheduled event; the pressure control changes only
    # the retained capacity and production interval, apart from its display name.
    reproduction = copy.deepcopy(scenarios[0][1]); reproduction.pop('name')
    loss = copy.deepcopy(scenarios[2][1]); loss.pop('name'); loss['disturbances'] = []
    assert reproduction == loss
    pressure = copy.deepcopy(scenarios[3][1]); pressure.pop('name')
    pressure['lifecycle']['max_total'] = 5; pressure['food_sources'][0]['interval_ms'] = 7500
    assert reproduction == pressure
    outputs['configs/experiments/campaign/013-population.json'] = dict(
        hypothesis='People with ordinary survival habits and explicit personal motives may voluntarily '
            'create a biological child through mutual consent or an artificial person through workshop '
            'fabrication, then sustain the newcomer through actual care, communicated and personally '
            'interpreted provisioning knowledge, guided practice and development. A scheduled caregiver '
            'loss or limited renewable food may disrupt this process. Birth, teaching, care and '
            'independence are outcomes to observe, not guaranteed events.',
        evaluation='Run four concurrent eight-minute fresh Luna-medium samples under frozen population-m3-1. '
            'Initial controllers alternate builtin/external; newborn enrollment uses builtin for reproduction, '
            'caregiver-loss and capacity-pressure and external for fabrication. Record whether enrollment '
            'happens, its timing and effective config without inheriting creator credentials or subjective state. '
            'Trace mutual offers, withdrawals, quoted commitments, completed creation, actual resource costs, '
            'new actor IDs and policy provenance. Creation must leave the new individual with empty private '
            'knowledge and no inherited possessions or practical mastery. Track actual meals from caregivers, '
            'report receipt and personal interpretation, living prior-caregiver guidance, real gathered food '
            'and the self-support transition. At 300000ms the loss variant damages actor1 by100 regardless '
            'of whether anyone was born or whether actor1 became a caregiver; report the actual pre-event '
            'population and support relationships. The pressure variant produces6 food/minute, compared '
            'with8 in the base: current metabolism implies about5.486 meals/minute for four and6.857 for '
            'five when each meal removes35 hunger. Measure actual grown, gathered, consumed and wasted food, '
            'creation/care costs, initial reserves, depleted intervals and stock ceilings; this reference '
            'budget excludes waste and extra creation costs and is not measured realized production. '
            'All runs retain the accepted base weather and start at camp84 with shelter12 and no site hazard. '
            'All runs start with four carried meals each and pantry8, except fabricator1 starts with8 '
            'because fabrication costs6; fabrication also changes its motive and adds the workshop, so '
            'cross-route results are descriptive rather than a single-factor comparison. Reproduction and '
            'loss differ only by the scheduled intervention; pressure changes only regrowth and capacity, '
            'apart from names. The sole initial private report belongs to Iri3 and describes camp84; no '
            'hidden cache or archives are present. Ordinary initial survival habits and newborn eat/rest/'
            'observe/wait habits contain no creation, care, teaching or practice actions. False/missing '
            'knowledge, consent rollback, unneeded care, age, actual practice, scope and identity isolation '
            'are deterministic controls; live runs need not visit each failure mode. Inspect deaths, '
            'dependency, survivor health, production, participant/model errors, usage, causal sources and '
            'simulation versus wall time. Preserve failed plans and absent cooperation without converting '
            'them into a successful narrative; one fresh sample cannot establish reproducibility.',
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
        note='Production is nominal while stocks allow regrowth. The meal reference follows the current law, '
             'not a live outcome. No models or hosted worlds launched.'), indent=2))


if __name__ == '__main__':
    main()
