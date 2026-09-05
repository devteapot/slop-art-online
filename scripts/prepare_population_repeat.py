#!/usr/bin/env python3
"""Freeze explicit longer Stage 3 follow-ups after the first population observations."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = 'output/society-lab/implementations/population-m3-2'


def prepare():
    variants = []
    settings = [
        ('reproduction-repeat', 'reproduction', 'builtin'),
        ('reproduction-reserves', 'reproduction', 'builtin'),
        ('fabrication-repeat', 'fabrication', 'external'),
        ('fabrication-caregiver-loss', 'fabrication', 'external'),
    ]
    for index, (name, base, role) in enumerate(settings):
        scenario = copy.deepcopy(json.loads((ROOT / f'scenarios/population-{base}.json').read_text()))
        scenario['name'] = name.replace('-', ' ').title()
        scenario['max_ticks'] = 288
        if name == 'reproduction-reserves':
            for player in scenario['players']:
                if player['id'] in (1, 2):
                    player['food'] = 6
        if name == 'fabrication-caregiver-loss':
            scenario['disturbances'] = [dict(at_ms=500000, kind='damage', actor=3, amount=100)]
        path = f'scenarios/population-{name}.json'
        (ROOT / path).write_text(json.dumps(scenario, indent=2) + '\n')
        variants.append(dict(id=name, port=18964 + index, implementation=IMPL,
            scenario=f'{IMPL}/{path}', controllers=f'{IMPL}/configs/experiments/population-4-medium.json',
            newcomer_controller=f'{IMPL}/configs/experiments/population-newcomer-{role}-medium.json', recovery=True))
    manifest = dict(
        hypothesis='Longer fresh runs on the perceived-target validation fix can distinguish delayed support and learning from absent renewal. Greater initial parental reserves may change biological consent and creation choices. Removing a likely caregiver can test continuity only if actual prior care occurred.',
        evaluation='Four concurrent twelve-minute Luna-medium sessions, fifteen-second post-completion cadence, no call cap. The reproduction repeat preserves 013 reproduction physical/social inputs apart from name and horizon. The reserves variant differs from that repeat only by actor1 and actor2 carrying6 instead of4 food. Fabrication repeats 013 fabrication; its matched loss variant damages actor3 by100 at500000ms, chosen because actor3 actually cared in013. No birth, offer, care, teaching, interpretation, practice or migration action is scripted. Record actual births before loss, actual caregiver identity, post-loss support and independent work. Extend time to permit multiple newborn perception/behavior/learning cycles: the013 artificial newcomer acquired its first report late and had no interpretation/practice at480s. Initial stocks, source rates, costs, weather and survival habits otherwise stay fixed. Both fabrication newborn profiles remain external; reproduction uses builtin. The new implementation accepts targets known through owned retained lifecycle site observations and clarifies canonical patch paths; it does not shorten creation time, add care priorities or grant understanding. Compare independent model choices descriptively; new calls are stochastic and the fix prevents exact matched causal attribution to duration. Retain failure, non-creation, rejected operations and shortage. Audit actual creation/food/care/knowledge flows, newcomer enrollment/calls, source/authority scope and conservation. Endpoint survival or receipt alone is not independence; scheduled actor death alone is not caregiver-loss evidence.',
        minutes=12, calls_per_actor=0, serial_ms=15000, variants=variants)
    (ROOT / 'configs/experiments/campaign/014-population-repeat.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Prepared four explicit twelve-minute population follow-ups')


if __name__ == '__main__':
    prepare()
