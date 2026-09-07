#!/usr/bin/env python3
"""Derive a declared density fixture from seed templates, never saved characters."""
import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path


def prepare(source, population):
    seed = json.loads(source.read_text())
    assert len(seed['players']) == 36 and population in (72, 144)
    assert [p['id'] for p in seed['players']] == list(range(1, 37))
    assert not seed['lifecycle'] and not seed['disturbances']
    # The fixture uses initial character templates only: no runtime evidence,
    # private memories, completed research or inherited possessions are copied.
    assert all(not p['memories'] and not p['knowledge'] and not p['execution'] for p in seed['players'])
    def remap(value, replacements):
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, list):
            return [remap(item, replacements) for item in value]
        if isinstance(value, dict):
            return {key: remap(item, replacements) for key, item in value.items()}
        return value

    result = copy.deepcopy(seed)
    for cohort in range(1, population // 36):
        offset = cohort * 36
        for original in seed['players']:
            actor = original['id'] + offset
            player = copy.deepcopy(original)
            player['id'] = actor
            player['name'] += f' [load cohort {cohort+1}]'
            result['players'].append(player)
            replacements = {record['id']: f"{record['id']}-load-{actor}"
                            for record in seed['knowledge'].get(str(original['id']), [])}
            for field in ('starting_behaviors', 'knowledge'):
                if str(original['id']) in seed[field]:
                    result[field][str(actor)] = remap(seed[field][str(original['id'])], replacements)
            for field in ('bodies', 'actor_materials'):
                if str(original['id']) in seed['infrastructure'][field]:
                    result['infrastructure'][field][str(actor)] = copy.deepcopy(seed['infrastructure'][field][str(original['id'])])
        for original, arena in zip(seed['arenas'], result['arenas']):
            arena['actors'].extend(actor + offset for actor in original['actors'])
            arena['controllers'].update({str(int(actor)+offset): mode for actor, mode in original['controllers'].items()})
    result['name'] = f'Native authority density fixture: {population} initial actors'
    density = Counter(p['position'] for p in result['players'])
    manifest = dict(population=population, source=str(source.resolve()),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        transformation='duplicate initial actor templates and their starting behavior/body/material/survey seed; assign unique IDs and arena membership',
        runtime_state_copied=False, historical_evidence_copied=False,
        same_map=True, facilities_and_supply_unchanged=True, territorial_grants_unchanged=True,
        organizations_and_office_holders_unchanged=True, max_ticks=result['max_ticks'],
        local_density_by_position=dict(sorted(density.items())), max_initial_colocation=max(density.values()),
        interpretation='increased density and resource contention; not a constant-density world or autonomous population')
    return result, manifest


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]/'scenarios/faction-world-reality.json')
    parser.add_argument('--population',type=int,choices=(72,144),required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    scenario,manifest=prepare(args.source,args.population)
    (args.output/'scenario.json').write_text(json.dumps(scenario,indent=2)+'\n')
    manifest['scenario_sha256']=hashlib.sha256((args.output/'scenario.json').read_bytes()).hexdigest()
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
