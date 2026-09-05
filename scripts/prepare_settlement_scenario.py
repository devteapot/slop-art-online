#!/usr/bin/env python3
"""Resolve a small generic settlement seed and its disabled-production control."""
import copy
import json
from pathlib import Path

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
    finite=copy.deepcopy(scenario)
    finite['name']='Shared garden: disabled production control'
    finite['food_sources']=[]
    for name,value in [('settlement-renewable',scenario),('settlement-finite',finite)]:
        (ROOT/'scenarios'/f'{name}.json').write_text(json.dumps(value,indent=2)+'\n')
    print('Resolved matched 12-minute seeds: 22 initial food; renewable ceiling 8 units/minute, capacity 12.')

if __name__=='__main__':main()
