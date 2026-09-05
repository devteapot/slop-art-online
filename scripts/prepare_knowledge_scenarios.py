#!/usr/bin/env python3
"""Resolve the Stage 2 knowledge matrix without launching models or world processes.

Inputs are the settlement seed, existing ordinary survival profiles and Luna configs.
The authored loss interventions are explicit scenario data, never character policies.
"""
import argparse
import copy
import json
from pathlib import Path

from starting_behavior_presets import make_starters

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = 'output/society-lab/implementations/knowledge-m2-1'
MINUTES = 6
PROFILES = ('builder', 'reserve_keeper', 'shared_provider', 'cautious_observer')
NAMES = ('Mira', 'Tovan', 'Iri', 'Renn', 'Sela', 'Oren', 'Neri', 'Venn')
AUTHOR_MOTIVE = (
    'I have a useful field note in my private knowledge. I want to deliberately teach its '
    'contents to someone who can use them and, where a physical archive is available, '
    'preserve a copy for people who arrive later. I value explanations others can check. '
    'I also need enough food, energy and shelter to remain capable.'
)
LEARNER_MOTIVES = (
    'I want independence and a reliable food reserve. I am curious about useful field notes '
    'others can teach me and records in local archives. I want to assess reports against '
    'what I observe, and explore opportunities supported by evidence while staying supplied.',
    'I want people here to have a fair chance of surviving. I am curious about useful '
    'reports and how to preserve them. I want to learn from people or accessible archives, '
    'consider the evidence, and put credible knowledge to practical use while caring for myself.',
    'I want to earn a place without being dependent or exploited. I am curious about '
    'field notes but skeptical of claims. I want to ask, learn and check what I am told, '
    'then choose whether evidence justifies exploring or sharing it. I must remain fed and sheltered.',
)


def read(relative):
    return json.loads((ROOT / relative).read_text())


def make_scenario(base, population, label, *, archive=False, distributed=False, losses=False):
    s = copy.deepcopy(base)
    s.update(name=label, max_ticks=MINUTES * 24, players=[], starting_behaviors={},
             knowledge={'1': [dict(id='route-cache', topic='field-notes',
                 text='My field note: cell 56 held a safe food cache with eight portions when I last checked. '
                      'From the camp at cell 84, travel four cells east and two north; verify the stock on arrival.',
                 location=56, confidence=75)]}, archives=[], disturbances=[])
    for index in range(population):
        actor = index + 1
        home = 88 if distributed and actor > 4 else 84
        player = copy.deepcopy(base['players'][index % 4])
        player.update(id=actor, name=NAMES[index], controller='ai', position=home,
                      motive=AUTHOR_MOTIVE if actor == 1 else LEARNER_MOTIVES[(index - 1) % 3],
                      current_goal=None, knowledge=[], memories=[], site_observations=[],
                      relationships={}, execution=None, generation=0, failures=0,
                      last_reflection=0, last_cause=None)
        # Retain common knowledge of camps, never insert the author's private cache.
        player['beliefs'] = [belief for belief in player['beliefs'] if belief['claim']['location'] != 56]
        s['players'].append(player)
        s['starting_behaviors'][str(actor)] = copy.deepcopy(make_starters(home)[PROFILES[index % 4]])
    arena = s['arenas'][0]
    arena.update(label=f'{population} people / {label}', environment='knowledge-settlement',
                 variant='luna-medium', actors=list(range(1, population + 1)),
                 controllers={str(actor): 'builtin' if actor % 2 else 'external'
                              for actor in range(1, population + 1)})
    for site in s['sites']:
        position = site['position']
        site.update(food={84: 8, 88: 8 if distributed else 4, 56: 8}[position], hazard=0,
                    shelter=12 if position == 84 or (distributed and position == 88) else 0)
    s['food_sources'] = [dict(position=home, interval_ms=7500, amount=1, capacity=12)
                         for home in ([84, 88] if distributed else [84])]
    if archive:
        s['archives'].append(dict(id=1, position=84, label='Camp field-note archive', capacity=16))
    if distributed:
        s['archives'].append(dict(id=2, position=88, label='Eastern field-note archive', capacity=16))
    if losses:
        s['disturbances'].append(dict(at_ms=120000, kind='damage', actor=1, amount=100))
    return s


def actions(tree):
    if isinstance(tree, dict):
        if tree.get('kind') == 'action':
            yield tree['action']
        for value in tree.values():
            yield from actions(value)
    elif isinstance(tree, list):
        for value in tree:
            yield from actions(value)


def validate(scenario, controllers, *, minutes=MINUTES):
    """Static input controls; World::new remains the authoritative schema validator."""
    players = scenario['players']
    actors = [p['id'] for p in players]
    assert actors == list(range(1, len(players) + 1))
    assert len({p['name'] for p in players}) == len(players)
    assert [c['actor'] for c in controllers] == actors
    assert scenario['arenas'][0]['actors'] == actors
    assert set(scenario['arenas'][0]['controllers']) == {str(a) for a in actors}
    assert set(scenario['starting_behaviors']) == {str(a) for a in actors}
    assert scenario['max_ticks'] * 2500 == minutes * 60000
    assert list(scenario['knowledge']) == ['1']
    assert [record['id'] for record in scenario['knowledge']['1']] == ['route-cache']
    for player, controller in zip(players, controllers):
        actor = player['id']
        assert player['controller'] == 'ai'
        assert controller['role'] == scenario['arenas'][0]['controllers'][str(actor)]
        assert controller['config']['backend']['model'] == 'gpt-5.6-luna'
        assert controller['config']['backend']['reasoning_effort'] == 'medium'
        assert not player['knowledge'] and not player['memories'] and not player['site_observations']
        assert all(b['claim']['location'] != 56 for b in player['beliefs'])
        assert '56' not in player['motive'] and 'eight portions' not in player['motive']
        for action in actions(scenario['starting_behaviors'][str(actor)]['tree']):
            assert action['skill'] in {'move', 'eat', 'rest', 'gather', 'build', 'deposit', 'observe', 'wait'}
            assert action.get('destination') != 56
    cache = next(site for site in scenario['sites'] if site['position'] == 56)
    assert cache['food'] == 8 and cache['hazard'] == 0
    assert 56 not in scenario['map']['blocked']
    production = sum(60000 * source['amount'] / source['interval_ms'] for source in scenario['food_sources'])
    assert production >= 1.37 * len(players)
    for home in {p['position'] for p in players}:
        assert next(site for site in scenario['sites'] if site['position'] == home)['shelter'] == 12
    return dict(population=len(players), nominal_food_per_minute=production,
                reference_need_per_minute=round(1.37 * len(players), 2),
                archives=[a['id'] for a in scenario['archives']], disturbances=scenario['disturbances'])


def build():
    base = read('scenarios/settlement-renewable.json')
    config = read('configs/experiments/society-four-medium.json')[0]['config']
    teaching = make_scenario(base, 2, 'Direct teaching between two people')
    archive = make_scenario(base, 4, 'Physical archive after author loss', archive=True, losses=True)
    archive_loss = copy.deepcopy(archive)
    archive_loss['name'] = 'Physical archive and author loss'
    archive_loss['disturbances'].append(dict(at_ms=180000, kind='destroy_archive', archive=1))
    # Keep even the arena label identical in this matched pair; only the scenario
    # name and the one additional authored destruction intervention differ.
    distributed = make_scenario(base, 8, 'Two local archives across eight people', archive=True, distributed=True)
    candidates = [('teaching-two', teaching), ('archive-four', archive),
                  ('archive-loss-four', archive_loss), ('distributed-eight', distributed)]
    outputs, summaries, variants = {}, {}, []
    for index, (name, scenario) in enumerate(candidates):
        population = len(scenario['players'])
        controllers = [dict(actor=actor, role=scenario['arenas'][0]['controllers'][str(actor)],
                            config=copy.deepcopy(config)) for actor in range(1, population + 1)]
        scenario_path = f'scenarios/knowledge-{name}.json'
        controller_path = f'configs/experiments/knowledge-{population}-medium.json'
        outputs[scenario_path] = scenario
        outputs[controller_path] = controllers
        summaries[name] = validate(scenario, controllers)
        variants.append(dict(id=name, port=18954 + index, implementation=IMPLEMENTATION,
                             scenario=f'{IMPLEMENTATION}/{scenario_path}',
                             controllers=f'{IMPLEMENTATION}/{controller_path}', recovery=True))
    pair_a, pair_b = copy.deepcopy(archive), copy.deepcopy(archive_loss)
    pair_a.pop('name'); pair_b.pop('name')
    pair_b['disturbances'].pop()
    assert pair_a == pair_b, 'archive controls differ beyond the declared loss intervention'
    outputs['configs/experiments/campaign/011-knowledge.json'] = dict(
        hypothesis='Ordinary model-controlled survivors can teach a private useful report, preserve physical copies, '
                   'and use learned evidence after the original author dies; larger populations may distribute '
                   'copies across two local archives. Authored archive loss changes availability only for physical '
                   'copies actually present, without deleting living carriers.',
        evaluation='Run four concurrent six-minute fresh Luna-medium variants under the same frozen knowledge-m2-1 '
                   'implementation. Inspect teaching/recording/consultation events and source IDs, subjective '
                   'interpretations, evidence-grounded policy changes and actual visits or gathering at cache56; '
                   'distinguish independent discovery from transmitted knowledge. Compare the matched four-person '
                   'runs before/after author damage at120s and the additional archive destruction at180s. Count '
                   'living carriers and surviving archive copies at each boundary: archive destruction is not '
                   'total knowledge loss while a living copy remains. Deterministic tests establish exact-loss '
                   'controls; a fresh sample need not produce a particular narrative. The two-person run has no '
                   'archive or scheduled death; the eight-person run has two supplied sheltered settlements and '
                   'no scheduled deaths, so population/distribution findings are descriptive, not a single-factor '
                   'causal estimate. Track actual simulation time, survivor health, resources, completed/error calls, '
                   'usage, engine errors and scope violations. Motives, survival habits, private starting report '
                   'and disturbances are authored inputs; teaching, speech, preservation and exploration remain '
                   'model decisions. No claim of humanlike culture or stochastic reproducibility follows from one sample.',
        minutes=MINUTES, calls_per_actor=0, serial_ms=15000, variants=variants)
    # Follow-up inputs are separate artifacts: preserve every original 011 control.
    repeat_implementation = 'output/society-lab/implementations/assessment-m2-2'
    teaching_repeat = copy.deepcopy(teaching)
    teaching_repeat.update(name='Direct teaching / assessed-claim repeat', max_ticks=4 * 24)
    separated = copy.deepcopy(archive)
    separated.update(name='Neighbor readers after author loss', max_ticks=4 * 24)
    for player in separated['players'][1:]:
        player['position'] = 88
        player['motive'] += (' I want to get settled at the eastern thicket and compare useful observations '
                             'with neighbors when ready. I have heard that the public archive at camp cell 84 '
                             'can hold field notes; its contents are unknown to me and may be worth inspecting.')
        player['beliefs'].append(dict(claim=dict(location=84, danger=False,
            text='I was told that the shared camp at cell 84 has a public field-note archive; I do not know its contents.'),
            source=0, confidence=60))
        separated['starting_behaviors'][str(player['id'])] = copy.deepcopy(make_starters(88)[PROFILES[(player['id'] - 1) % 4]])
    for site in separated['sites']:
        if site['position'] == 88:
            site.update(food=8, shelter=12)
    separated['food_sources'].append(dict(position=88, interval_ms=7500, amount=1, capacity=12))
    repeat_variants = []
    for index, (name, scenario) in enumerate([('teaching-two-repeat', teaching_repeat), ('neighbor-readers-four', separated)]):
        population = len(scenario['players'])
        controllers = outputs[f'configs/experiments/knowledge-{population}-medium.json']
        path = f'scenarios/knowledge-{name}.json'
        outputs[path] = scenario
        summaries[name] = validate(scenario, controllers, minutes=4)
        repeat_variants.append(dict(id=name, port=18958 + index, implementation=repeat_implementation,
            scenario=f'{repeat_implementation}/{path}',
            controllers=f'{repeat_implementation}/configs/experiments/knowledge-{population}-medium.json', recovery=True))
    outputs['configs/experiments/campaign/012-knowledge-repeat.json'] = dict(
        hypothesis='An older still-valid receipt can assess its record after a duplicate receipt refresh, while '
                   'an assessment from an older source cannot overwrite a newer assessment. Repeat direct teaching '
                   'under assessment-m2-2 to inspect receipt-to-record linkage and assessment ordering; also examine '
                   'whether readers starting beyond hearing range can obtain a useful preserved report after its author dies. '
                   'Batch011 already demonstrated a new archive acquisition after author death; this challenges initial spatial separation.',
        evaluation='Run two concurrent four-minute Luna-medium fresh samples on the same frozen assessment-m2-2 '
                   'implementation. The teaching repeat retains original two-person inputs except its name and '
                   'four-minute bound; compare acquired report, accepted assessment, chosen movement, actual cache '
                   'visits and gathering with011, retaining failed or looping approaches. In neighbor-readers-four '
                   'only the author starts at camp84 with archive1; three readers start at supplied sheltered '
                   'thicket88, initially beyond speech range. Readers know the neighboring archive exists but '
                   'not its record identities, contents or hidden cache location. Author damage remains at120s. '
                   'Look for genuine recording before death and first acquisition by archive consultation after '
                   'death; inspect every earlier teaching/speech/visit rather than assume initial separation '
                   'prevents early contact. Travel, teaching, preservation, consultation and claims remain model '
                   'choices, with ordinary survival starters and no scripted learning sequence. Existing living '
                   'copies or paraphrases must not be counted as archive-only recovery. Track source citations, '
                   'new_copy versus repeated reads, assessment source linkage and ordering, positions, food collection, elapsed '
                   'simulation/wall time, model failures, engine/scope/conservation checks. This targeted repeat '
                   'checks older-receipt assessment bookkeeping and robustness under initial spatial separation; '
                   '011 already demonstrated post-death archive consultation. The m2-2 change affects receipt linkage and '
                   'assessment ordering only, not navigation rules or claim polarity semantics. This repeat does '
                   'not guarantee a narrative or establish statistical superiority.',
        minutes=4, calls_per_actor=0, serial_ms=15000, variants=repeat_variants)
    return outputs, summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='validate generated controls and compare committed JSON without writing')
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
                          note='Nominal production assumes room under growth ceilings; actual food availability and '
                               'model behavior require the live evidence. No worlds or models launched.'), indent=2))


if __name__ == '__main__':
    main()
