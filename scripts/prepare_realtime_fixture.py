#!/usr/bin/env python3
"""Provision a crowded long-run workload; all effects use the real authority."""
import argparse
import hashlib
import json
from collections import Counter


def charge_stations(value):
    if isinstance(value, dict):
        if value.get('op') == 'charge':
            yield value['station']
        for child in value.values():
            yield from charge_stations(child)
    elif isinstance(value, list):
        for child in value:
            yield from charge_stations(child)


def main():
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--human-actor', type=int, default=3)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    scenario = json.loads(raw)
    scenario['name'] = 'Provisioned crowded real-time workload: 215 native brains and one human'
    scenario['max_ticks'] = 800
    for arena in scenario['arenas']:
        arena['controllers'] = {}
        arena['variant'] = 'realtime-native-215-human-1'
    for site in scenario['sites']:
        site['food'] = 100
    for source in scenario['food_sources']:
        source.update(interval_ms=1000, amount=20, capacity=100)
    stations = {s['id']: s for s in scenario['infrastructure']['stations']}
    for station in stations.values():
        station.update(electricity=1000, electricity_capacity=1000,
                       generation_period_ms=2500, generation_amount=64)
    for actor, policy in scenario['starting_behaviors'].items():
        for station_id in charge_stations(policy):
            station = stations[station_id]
            if int(actor) != station['owner']:
                access = station['access'].setdefault(actor, dict(maintain=False, admin=False))
                access['use_allowed'] = True
    human = next(p for p in scenario['players'] if p['id'] == args.human_actor)
    human.update(controller='human', food=100)
    scenario['starting_behaviors'].pop(str(args.human_actor), None)
    scenario['infrastructure']['bodies'].pop(str(args.human_actor), None)
    neighbor = human['position'] + 1
    assert neighbor not in scenario['map']['blocked']
    assert all(s['position'] != neighbor for s in scenario['sites'])
    scenario['sites'].append(dict(position=neighbor, food=0, hazard=0, shelter=12))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'scenario.json').write_text(json.dumps(scenario, indent=2) + '\n')
    manifest = dict(source=str(args.source), source_sha256=hashlib.sha256(raw).hexdigest(),
                    population=len(scenario['players']), human_actor=args.human_actor,
                    initial_density=dict(Counter(p['position'] for p in scenario['players'])),
                    purpose='Provisioned survival workload, distinct from the scarce 60-second baseline; survival unverified until actual authority run.',
                    changes=['Food stock and renewal', 'Station capacity and generation',
                             'Charger-use access for copied actors', 'One biological human with food and sheltered adjacent route',
                             '2000-second maximum and explicit workload metadata'])
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
