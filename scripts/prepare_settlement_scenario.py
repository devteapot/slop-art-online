#!/usr/bin/env python3
"""Resolve settlement seeds, starting habits, and matched experimental controls."""
import copy
import json
from pathlib import Path

from starting_behavior_presets import make_starters

ROOT=Path(__file__).resolve().parents[1]

def main():
    scenario=json.loads((ROOT/'scenarios/society-first-winter.json').read_text())
    scenario['name']='Shared garden: renewable provisioning'
    scenario['max_ticks']=288
    scenario['arenas'][0]['label']='Four people / shared garden'
    scenario['arenas'][0]['environment']='shared-garden'
    for site in scenario['sites']:
        site['food']={84:8,88:4,56:0}[site['position']]
    scenario['food_sources']=[dict(position=84,interval_ms=7500,amount=1,capacity=12)]
    starters=make_starters(home=84)
    # Explicit seed assignments, independent of the player role/controller fields.
    assignments={1:'builder',2:'reserve_keeper',3:'shared_provider',4:'cautious_observer'}
    scenario['starting_behaviors']={str(actor):copy.deepcopy(starters[profile])
        for actor,profile in assignments.items()}
    finite=copy.deepcopy(scenario)
    finite['name']='Shared garden: disabled production control'
    finite['food_sources']=[]
    empty=copy.deepcopy(scenario)
    empty['name']='Shared garden: empty starting-policy control'
    empty['starting_behaviors']={}
    for name,value in [('settlement-renewable',scenario),('settlement-finite',finite),
                       ('settlement-renewable-empty',empty)]:
        (ROOT/'scenarios'/f'{name}.json').write_text(json.dumps(value,indent=2)+'\n')
    catalog=ROOT/'configs/behaviors/settlement-starters-v1.json'
    catalog.parent.mkdir(parents=True,exist_ok=True)
    catalog.write_text(json.dumps({'format':'starting-behavior-catalog-v1','home':84,
        'profiles':starters},indent=2)+'\n')
    print('Resolved matched 12-minute seeds: 22 initial food; renewable ceiling 8 units/minute, capacity 12. '
          'Four versioned starting habits; finite-production and empty-start controls.')

if __name__=='__main__':main()
