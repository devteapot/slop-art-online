#!/usr/bin/env python3
"""Prepare fresh autonomous numeric-technique research trials; never launch models."""
import argparse
import copy
import json
from pathlib import Path

from prepare_infrastructure_scenarios import (BALANCE, controllers, electric_starter,
    fresh_player, read, record, scenario_base, station, walk_actions)
from starting_behavior_presets import make_starters

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = 'output/society-lab/implementations/research-m6-5'
DURATION_MINUTES = 18
VARIANTS = ('invention', 'transfer-repeat', 'cooling', 'loss-risk')


def make_scenario(variant):
    if variant not in VARIANTS:
        raise ValueError(variant)
    base = read('scenarios/settlement-renewable.json')
    scenario = scenario_base(f'Autonomous numeric research: {variant}', DURATION_MINUTES)
    descriptions = [
        ('Ari', 'electric neighbor with an interest in planning',
         'I want dependable power for everyday work and charging. Demand seems uneven over time, '
         'and I suspect our finite buffer matters as much as average supply. I enjoy investigating '
         'a practical puzzle and making something useful if I can, but I need to stay alive and '
         'can decide whether investigation is worth the expense.'),
        ('Bryn', 'nutrient-supported neighbor who maintains equipment',
         'I want useful tools and enough food. I am curious about methods my neighbors develop, '
         'but I want to understand a method and check it myself before relying on it. I may help '
         'maintain our shared equipment or pursue my own ideas; neither is a standing obligation.'),
        ('Cato', 'electric neighbor with a different work schedule',
         'I want reliable charging and time for useful work. I have a different possible demand '
         'schedule from Ari. I would like to understand whether a planning method handles my '
         'circumstances, and can exchange ideas, investigate independently or decline.'),
        ('Dara', 'nutrient-supported neighbor concerned with continuity',
         'I value useful knowledge that people can still understand when its originator is absent. '
         'I am interested in preserving and questioning what we learn, while looking after food '
         'and finite supplies. I can choose what to share, save, spend or discard.'),
    ]
    for actor, (name, role, motive) in enumerate(descriptions, 1):
        electric = actor in (1, 3)
        scenario['players'].append(fresh_player(base, actor, name, 84, role, motive, electric=electric))
        scenario['starting_behaviors'][str(actor)] = (electric_starter(84, 1) if electric
            else copy.deepcopy(make_starters(84)['reserve_keeper']))
    scenario['sites'] = [dict(position=84, food=10, hazard=0, shelter=12)]
    scenario['food_sources'] = [dict(position=84, interval_ms=10000, amount=1, capacity=16)]
    scenario['archives'] = [dict(id=1, position=84, label='Camp notebook cabinet', capacity=32)]
    scenario['knowledge'] = {
        '1': [record('uneven-power-question', 'An unresolved planning question',
            'Suppose a power store starts at 8 with capacity 12. For four equal planning intervals, '
            'possible incoming amounts are 9, 1, 7, 0 and possible demand amounts are 2, 10, 2, 8. '
            'These are hypothetical amounts, not measurements of our station. I want to know '
            'how much demand can actually be met and what remains over the sequence. An overall '
            'average seems insufficient when a store can fill or empty. The local terminal has '
            'a conditional forecast instrument, but I have no tested method for this question.', 84)],
        '2': [record('equipment-cost-account', 'A maintenance account',
            'Terminal work consumes electricity, cooling water and equipment condition. Cooling '
            'water in storage and carried water are separate physical stocks. A queued job can '
            'stop if a resource runs out. Equipment wear and access can also matter; supplies '
            'or repair help only when someone actually pays them. This account is not an order.', 84)],
        '3': [record('alternate-demand-question', 'Another possible work schedule',
            'My hypothetical store starts at 3 with capacity 9. Possible incoming amounts over '
            'four equal intervals are 0, 12, 0, 3; possible demand amounts are 5, 1, 8, 2. I do '
            'not know the outcomes. I wonder whether a method useful for another schedule will '
            'also handle this one, including a temporary shortage and a full store. These values '
            'describe a planning question, not current or promised world conditions.', 84)],
        '4': [record('fragile-knowledge-question', 'Who can still use a discovery?',
            'Our cabinet can hold reports, but a report copied from another person does not mean '
            'I understand or can use it. Private terminal records, personal copies and cabinet '
            'copies are distinct. The absence of one person or one cabinet need not remove '
            'every copy. I care about what people can actually recover and understand.', 84)],
    }
    equipment = station(1, 1, 84, 'Camp research utility', [1, 2, 3, 4], [2, 4], water=48)
    equipment.update(electricity=60, electricity_capacity=120, generation_amount=4)
    if variant == 'cooling':
        equipment['materials']['water'] = 1
    scenario['infrastructure'] = dict(version=1, balance=copy.deepcopy(BALANCE),
        bodies={str(a): dict(version=1, support='electric', capacity=100, initial_charge=80,
                            drain_per_pulse=1) for a in (1, 3)},
        actor_materials={'2': dict(parts=12, water=6), '4': dict(parts=4, water=18)},
        stations=[equipment])
    if variant == 'loss-risk':
        scenario['disturbances'] = [dict(at_ms=540000, kind='damage', actor=1, amount=100),
                                   dict(at_ms=570000, kind='destroy_archive', archive=1)]
    scenario['arenas'][0].update(id='numeric-research', label='Autonomous numeric research',
        environment='research-control', variant='luna-medium', actors=[1, 2, 3, 4],
        controllers={str(a): 'builtin' if a % 2 else 'external' for a in range(1, 5)})
    return scenario


def validate(scenario, runtime):
    assert len(scenario['players']) == len(runtime) == 4
    assert scenario['lifecycle'] is None
    assert scenario['max_ticks'] == DURATION_MINUTES * 24
    for player, control in zip(scenario['players'], runtime):
        assert control['actor'] == player['id'] and player['controller'] == 'ai'
        assert control['config']['backend']['model'] == 'gpt-5.6-luna'
        assert control['config']['backend']['reasoning_effort'] == 'medium'
        assert not player['knowledge'] and not player['beliefs'] and not player['memories']
        for behavior in walk_actions(scenario['starting_behaviors'][str(player['id'])]['tree']):
            assert behavior['skill'] in ('eat', 'rest', 'move', 'gather', 'deposit', 'observe', 'wait', 'infrastructure')
            if behavior['skill'] == 'infrastructure':
                assert behavior['infrastructure']['op'] == 'charge'
    for records in scenario['knowledge'].values():
        for note in records:
            assert not note.get('program') and not note.get('experiment')
            assert 'fn technique' not in note['text']
    assert scenario['infrastructure']['balance'] == BALANCE


def build():
    outputs, variants = {}, []
    for index, variant in enumerate(VARIANTS):
        scenario = make_scenario(variant)
        runtime = controllers(scenario['players'])
        validate(scenario, runtime)
        scenario_path = f'scenarios/research-{variant}.json'
        controller_path = 'configs/experiments/research-4-medium.json'
        outputs[scenario_path] = scenario
        outputs[controller_path] = runtime
        variants.append(dict(id=variant, port=18985 + index, implementation=IMPLEMENTATION,
            scenario=f'{IMPLEMENTATION}/{scenario_path}', controllers=f'{IMPLEMENTATION}/{controller_path}', recovery=True))
    outputs['configs/experiments/campaign/020-research.json'] = dict(
        hypothesis='Four autonomous neighbors may move from personally assessed paid forecasts to '
            'a new useful nonlinear multi-interval numeric technique, communicate its physical '
            'code, and develop independent exact-source competence through paid practice. '
            'No discovery, transfer, cooperation or preservation is guaranteed.',
        evaluation='Four fresh parallel eighteen-minute Luna medium worlds, fifteen seconds after '
            'each serial behavior/communication/learning completion, no call cap. Invention and '
            'transfer-repeat have identical inputs except display name. Cooling changes only '
            'initial station water from 48 to 1, leaving 24 carried water available for voluntary '
            'recovery. Loss-risk changes only two explicit authored disturbances: actor 1 receives '
            '100 damage at 540000 ms and archive 1 is destroyed at 570000 ms. They do not erase '
            'terminal jobs or choose who invents. Audit all retained terminal/source/report copies '
            'and voluntary erase operations; report nonactivation when no discovery exists. '
            'Survival-only initial habits and private textual problem statements contain no code, '
            'computed result, mastery or prescribed action path. Require a personally paid, retrieved '
            'and interpreted built-in forecast bootstrap; inspect actual model-created source for '
            'meaningful nonlinear multi-interval behavior. Paid matching vectors alone are not proof '
            'of general correctness. Require a learner-held communicated code copy, own source '
            'inspection and interpretation, own paid successful exact-hash practice and interpretation '
            'before an ordinary run. Preserve unsuccessful experiments, unavailable jobs, decisions '
            'not to investigate, food/material accounts and limited evidence of useful consequences. '
            'An author death or archive destruction alone never establishes total discovery loss.',
        minutes=DURATION_MINUTES, calls_per_actor=0, serial_ms=15000, concurrency=4, variants=variants)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    outputs = build()
    for relative, value in outputs.items():
        path = ROOT / relative
        if args.check:
            if not path.is_file() or json.loads(path.read_text()) != value:
                raise SystemExit(f'Generated input differs: {relative}')
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps(dict(mode='checked' if args.check else 'prepared', variants=list(VARIANTS),
        population_each=4, minutes_each=DURATION_MINUTES, nominal_food_per_minute=6,
        nominal_power_per_minute=96, body_charge_need_per_minute=48,
        note='Inputs only; no model calls, hosted worlds or acceptance claims.'), indent=2))


if __name__ == '__main__':
    main()
