#!/usr/bin/env python3
"""Resolve authored infrastructure controls and faction geography without running models.

Seeds supply bodies, stocks, institutions and revisable survival habits. Computation,
maintenance, access changes, politics and travel remain participant choices.
"""
import argparse
import copy
import json
from pathlib import Path

from starting_behavior_presets import action, guarded, make_starters, negate, resource

ROOT = Path(__file__).resolve().parents[1]
SMALL_IMPLEMENTATION = 'output/society-lab/implementations/infrastructure-m5-1'
REPEAT_IMPLEMENTATION = 'output/society-lab/implementations/infrastructure-m5-2'
FACTION_IMPLEMENTATION = 'output/society-lab/implementations/faction-world-m5-3'
BALANCE = dict(version=1, build_parts=dict(generator=6, charger=3, terminal=5),
               repair_per_part=20, electricity_per_charge=1, compute_electricity=2,
               compute_water=1, compute_quanta=3, compute_quantum_ms=1000, wear_per_quantum=1)


def read(relative):
    return json.loads((ROOT / relative).read_text())


def electric_body():
    return dict(version=1, support='electric', capacity=100, initial_charge=80, drain_per_pulse=1)


def electric_starter(home, station):
    return dict(id='infrastructure.electric-home-survival', revision=1,
        description='Use a local charger below half battery, recover stamina, return to the known '
                    'home and observe. Battery and stamina are distinct. This ordinary starting '
                    'habit is revisable; it contains no computation, maintenance or access decision.',
        tree=dict(kind='priority', children=[
            guarded([dict(kind='at', location=home), resource('charge', 'below', 50)],
                    action('infrastructure', duration=1,
                           infrastructure=dict(op='charge', station=station, amount=20))),
            guarded([resource('energy', 'below', 35)], action('rest', duration=2)),
            guarded([negate(dict(kind='at', location=home))], action('move', destination=home)),
            dict(kind='sequence', children=[action('observe'), action('wait', duration=2)])]))


def station(identifier, owner, position, label, users, technicians, *, electric_users=2, water=20):
    return dict(id=identifier, owner=owner, position=position, label=label,
        electricity=30, electricity_capacity=max(100, electric_users * 50),
        materials=dict(parts=0, water=water), modules=['generator', 'charger', 'terminal'],
        access={str(actor): dict(use_allowed=True, maintain=actor in technicians, admin=False)
                for actor in users if actor != owner},
        generation_period_ms=2500, generation_amount=electric_users + 1)


def record(identifier, topic, text, location, confidence=80):
    return dict(id=identifier, topic=topic, text=text, location=location, confidence=confidence)


def forecast_note(identifier, location, electric_users):
    return record(identifier, 'Conditional electricity planning',
        'My planning method is to forecast a specified stock using explicit assumptions. '
        'For station electricity, use the current locally observed station buffer as stock and '
        'derive nominal inflow from its observed generation_amount and generation_period_ms. '
        f'A working reference is {electric_users} electric residents at 24 charge units per minute each '
        f'({electric_users * 24} total); count actual local needs and revise this assumption if circumstances differ. '
        'A two-minute horizon can reveal a possible shortage or surplus. A full resource_forecast_v1 '
        'job also spends six station electricity, three cooling water and three integrity; body demand '
        'alone excludes compute and other uses. The terminal computes only supplied arithmetic, not '
        'future truth. Explicitly retrieve a completed report, personally assess it, and choose whether '
        'it changes charging, workload, maintenance or a request to another person. This note is '
        'not a current stock reading or proof of anyone else\'s future behavior.', location)


def maintenance_note(identifier, location):
    return record(identifier, 'Local equipment maintenance account',
        'A terminal job needs three successful compute quanta. Each quantum consumes two electricity '
        'and one cooling water and wears one integrity. Missing cooling or electricity can stop '
        'progress without making a result. Carried water can be deposited if access permits; one '
        'carried part repairs up to twenty missing integrity when repair is useful and permitted. '
        'Parts and water are finite physical stocks. Ownership or office is not permission at every '
        'facility. Check actual equipment, local supplies and the posted access before acting; '
        'this account is guidance, not an automatic repair instruction.', location)


def controllers(players):
    config = read('configs/experiments/population-4-medium.json')[0]['config']
    return [dict(actor=player['id'], role='builtin' if player['id'] % 2 else 'external',
                 config=copy.deepcopy(config)) for player in players]


def fresh_player(base, actor, name, position, role, motive, *, electric=False):
    player = copy.deepcopy(base['players'][(actor - 1) % len(base['players'])])
    player.update(id=actor, name=name, controller='ai', role=role, motive=motive,
        position=position, health=100, hunger=0 if electric else 20, energy=80,
        food=0 if electric else 2, fear=0, current_goal=None, knowledge=[], beliefs=[],
        memories=[], site_observations=[], relationships={}, execution=None,
        generation=0, failures=0, last_reflection=0, last_cause=None)
    return player


def scenario_base(name, minutes):
    base = read('scenarios/settlement-renewable.json')
    base.update(name=name, max_ticks=minutes * 24, players=[], sites=[], food_sources=[],
                archives=[], starting_behaviors={}, knowledge={}, lifecycle=None, disturbances=[])
    base.pop('infrastructure', None)
    base.pop('society', None)
    return base


def make_small(variant):
    base = read('scenarios/settlement-renewable.json')
    scenario = scenario_base(f'Mixed-body infrastructure: {variant}', 8)
    descriptions = [
        ('Ari', 'electric analyst and local station owner',
         'I want our shared work to be sustainable. I am interested in using the local terminal '
         'to compare an explicit electricity forecast with observed conditions, then decide what '
         'workload or charging arrangement makes sense. I can reconsider access and seek help; '
         'a prediction is not proof and owning equipment does not make other people obedient.'),
        ('Bryn', 'nutrient-supported maintenance worker',
         'I want useful equipment and reliable food. I have a maintenance account and some carried '
         'parts. I may inspect wear or cooling and choose whether to repair, contribute supplies '
         'or negotiate help. I also need to remain fed and rested; my role is not a standing order.'),
        ('Cato', 'electric resident and prospective terminal user',
         'I need dependable charging and want to assess whether our station can support useful '
         'work alongside everyone\'s needs. I may request access, use an explicit forecast, share '
         'my assessment or seek alternatives. I want fair practical arrangements, not assumed entitlement.'),
        ('Dara', 'nutrient-supported logistics neighbor',
         'I value reliable food and useful shared work. I carry a finite water reserve and may '
         'contribute it, ask for reciprocal help or preserve it for later after checking local '
         'conditions. I want promises and computed reports to be checked against actual supplies.'),
    ]
    for actor, (name, role, motive) in enumerate(descriptions, 1):
        electric = actor in (1, 3)
        scenario['players'].append(fresh_player(base, actor, name, 84, role, motive, electric=electric))
        scenario['starting_behaviors'][str(actor)] = (electric_starter(84, 1) if electric
            else copy.deepcopy(make_starters(84)['reserve_keeper' if actor == 2 else 'shared_provider']))
    scenario['sites'] = [dict(position=84, food=6, hazard=0, shelter=12)]
    scenario['food_sources'] = [dict(position=84, interval_ms=15000, amount=1, capacity=12)]
    scenario['knowledge'] = {'1': [forecast_note('camp-electricity-planning', 84, 2)],
                             '2': [maintenance_note('camp-equipment-maintenance', 84)]}
    equipment = station(1, 1, 84, 'Camp utility', [1, 2, 3, 4], [2])
    if variant == 'power':
        equipment['generation_amount'] = 1
    elif variant == 'cooling':
        equipment['materials']['water'] = 1
    elif variant == 'access':
        del equipment['access']['3']
    elif variant != 'baseline':
        raise ValueError(f'Unknown infrastructure variant {variant}')
    scenario['infrastructure'] = dict(version=1, balance=copy.deepcopy(BALANCE),
        bodies={str(actor): electric_body() for actor in (1, 3)},
        actor_materials={'2': dict(parts=12, water=0), '4': dict(parts=0, water=12)},
        stations=[equipment])
    scenario['arenas'][0].update(id='mixed-infrastructure', label='Shared mixed-body infrastructure',
        environment='infrastructure-control', variant='luna-medium', actors=[1, 2, 3, 4],
        controllers={str(a): 'builtin' if a % 2 else 'external' for a in range(1, 5)})
    return scenario


def walk_actions(value):
    if isinstance(value, dict):
        if value.get('kind') == 'action':
            yield value['action']
        for child in value.values():
            yield from walk_actions(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_actions(child)


def validate_common(scenario, runtime):
    actors = [p['id'] for p in scenario['players']]
    assert actors == list(range(1, len(actors) + 1))
    assert len({p['name'] for p in scenario['players']}) == len(actors)
    assert scenario['lifecycle'] is None and scenario['disturbances'] == []
    assert len(scenario['arenas']) == 1 and scenario['arenas'][0]['actors'] == actors
    assert [c['actor'] for c in runtime] == actors
    for player, control in zip(scenario['players'], runtime):
        actor = player['id']
        assert player['controller'] == 'ai'
        assert control['role'] == scenario['arenas'][0]['controllers'][str(actor)]
        assert control['config']['backend']['model'] == 'gpt-5.6-luna'
        assert control['config']['backend']['reasoning_effort'] == 'medium'
        assert not player['knowledge'] and not player['beliefs'] and not player['relationships']
        assert not player['memories'] and not player['site_observations']
        for behavior in walk_actions(scenario['starting_behaviors'][str(actor)]['tree']):
            assert behavior['skill'] in ('eat', 'rest', 'move', 'gather', 'deposit', 'build', 'observe', 'wait', 'infrastructure')
            if behavior['skill'] == 'infrastructure':
                assert behavior['infrastructure']['op'] == 'charge', 'advanced work must remain a choice'
    assert scenario['infrastructure']['balance'] == BALANCE
    assert all(p == electric_body() for p in scenario['infrastructure']['bodies'].values())


def build_small():
    outputs, summary, variants, scenarios = {}, {}, [], {}
    for index, name in enumerate(('baseline', 'power', 'cooling', 'access')):
        scenario = make_small(name)
        runtime = controllers(scenario['players'])
        validate_common(scenario, runtime)
        scenarios[name] = scenario
        scenario_path = f'scenarios/infrastructure-{name}.json'
        outputs[scenario_path] = scenario
        outputs['configs/experiments/infrastructure-4-medium.json'] = runtime
        equipment = scenario['infrastructure']['stations'][0]
        summary[name] = dict(initial_population=4, electric_bodies=2, nutrient_bodies=2,
            nominal_food_per_minute=4, reference_food_need_per_minute=round(2 * 48 / 35, 4),
            nominal_power_per_minute=24 * equipment['generation_amount'], body_charge_need_per_minute=48,
            initial_station_electricity=30, initial_personal_charge=160,
            station_water=equipment['materials']['water'], carried_water=12, carried_parts=12,
            actor3_initial_use='3' in equipment['access'])
        variants.append(dict(id=name, port=18972 + index, implementation=SMALL_IMPLEMENTATION,
            scenario=f'{SMALL_IMPLEMENTATION}/{scenario_path}',
            controllers=f'{SMALL_IMPLEMENTATION}/configs/experiments/infrastructure-4-medium.json', recovery=True))
    baseline = copy.deepcopy(scenarios['baseline']); baseline.pop('name')
    for name, expected in [('power', ('generation_amount', 1)), ('cooling', ('water', 1)), ('access', ('actor3', False))]:
        expected_scenario = copy.deepcopy(baseline)
        equipment = expected_scenario['infrastructure']['stations'][0]
        if name == 'power': equipment['generation_amount'] = expected[1]
        elif name == 'cooling': equipment['materials']['water'] = expected[1]
        else: del equipment['access']['3']
        actual = copy.deepcopy(scenarios[name]); actual.pop('name')
        assert actual == expected_scenario, f'{name} changes more than its single explicit control'
    outputs['configs/experiments/campaign/016-infrastructure.json'] = dict(
        hypothesis='Four autonomous neighbors with two electric and two nutrient-supported bodies may '
            'use physical charging, explicit conditional forecasts, finite cooling supplies, maintenance '
            'and negotiated station access. Reduced generation, cooling stock or one use grant can '
            'change what actually completes; no computation or cooperation is guaranteed.',
        evaluation='Run four concurrent eight-minute fresh Luna-medium samples with fifteen-second '
            'post-completion cadence and no call cap on infrastructure-m5-1. All four actors begin '
            'at sheltered camp 84. Actors 1/3 are electric with battery 80/100 and drain 1 per 2500 ms '
            '(24/min each); actors 2/4 need nutrients, reference 48/35 meals/min each. Food production '
            'is 4/min with initial pantry 6 and two meals per nutrient body. Baseline station generation '
            'is 72 electricity/min with buffer 30/capacity 100, versus 48/min body demand before computation; '
            'stock ceilings and access make nominal output different from usable output. Power changes '
            'only generation to 24/min, cooling only station water 20 to 1, access only removes actor 3\'s '
            'initial use permission. Owner 1 retains administrative rights; actor 2 can maintain and '
            'actor 4 can use/deposit. Carried parts 12 on 2 and water 12 on 4 stay identical. A forecast '
            'costs 3 physical quanta, 6 electricity, 3 water and 3 integrity, uses explicit submitted assumptions '
            'and personally held sources, and requires explicit local retrieval. Its arithmetic is '
            'not an oracle. Trace input provenance, queued/blocked/completed/retrieved jobs, actual '
            'consumption, own report interpretation and subsequent choices. Count charging separately '
            'from stamina/rest and food; retain denied access, outages, cooling stalls, failed proposals, '
            'deaths and absent work. Initial habits contain only ordinary survival and electric charging, '
            'never authored compute/grant/repair sequences. Knowledge priors provide planning methods '
            'and maintenance guidance rather than current remote truth or fabricated results. Compare '
            'actual energy, food, water and part ledgers, controller errors and simulation/wall time. '
            'No new population, stronger backend model or automatic social agreement is introduced.',
        minutes=8, calls_per_actor=0, serial_ms=15000, variants=variants)
    return outputs, summary


FACTION_CAMPS = dict(anthropic=294, openai=330, xai=1482, coalition=1446,
                    sf=888, independent=216, mixed=879)
FACTION_GROUPS = dict(anthropic=list(range(1, 5)), openai=list(range(5, 9)),
                     xai=list(range(9, 13)), coalition=list(range(13, 17)),
                     sf=list(range(17, 25)) + [35, 36], independent=list(range(25, 29)),
                     mixed=list(range(29, 35)))
FACTION_NAMES = [
    'Elian', 'Aster-Prime', 'Vela', 'Soren', 'Nima', 'Orin-Prime', 'Pax', 'Leto',
    'Kestrel', 'Xeno-Prime', 'Juno', 'Tavi', 'Shen', 'River-Prime', 'Mirelle', 'Kiri',
    'Amara', 'Olin', 'Xara', 'Dai', 'Rowan', 'Inez', 'Mara', 'Sol',
    'Fenn', 'Lark', 'Uma', 'Tern', 'Arielle', 'Nova', 'Zev', 'Mei',
    'Hana', 'Felix', 'Niko', 'Veda',
]


def faction_society():
    def region(identifier, label, kind, x, y, width, height, editors=()):
        return dict(id=identifier, label=label, kind=kind,
                    bounds=dict(x=x, y=y, width=width, height=height), territorial_editors=list(editors))
    regions = [
        region('anthropic-homeland', 'Anthropic homeland', 'homeland', 1, 1, 12, 10, [2]),
        region('openai-homeland', 'OpenAI homeland', 'homeland', 35, 1, 12, 10, [6]),
        region('xai-homeland', 'xAI homeland', 'homeland', 35, 25, 12, 10, [10]),
        region('coalition-homeland', 'DeepSeek, Mistral and Kimi coalition homeland', 'homeland', 1, 25, 12, 10, [14]),
        region('sf', 'SF', 'city', 20, 14, 9, 9),
        region('independent-city', 'Independent city', 'city', 20, 1, 9, 8),
        region('mixed-settlement', 'Mixed settlement', 'mixed', 11, 14, 8, 9),
        region('northern-wilds', 'Northern wilds', 'wild', 14, 9, 20, 5),
        region('southern-wilds', 'Southern wilds', 'wild', 14, 24, 20, 11),
        region('western-wilds', 'Western wilds', 'wild', 1, 12, 9, 12),
        region('eastern-wilds', 'Eastern wilds', 'wild', 29, 12, 18, 12),
    ]
    def org(identifier, label, members, stations=()):
        return dict(id=identifier, label=label, members=members, stations=list(stations))
    organizations = [
        org('anthropic', 'Anthropic tradition', [1, 2, 3, 4, 17, 29], [1]),
        org('openai', 'OpenAI tradition', [5, 6, 7, 8, 18, 30], [2]),
        org('xai', 'xAI tradition', [9, 10, 11, 12, 19, 31], [3]),
        org('coalition', 'DeepSeek, Mistral and Kimi coalition', [13, 14, 15, 16, 20, 32], [4]),
        org('deepseek', 'DeepSeek circle', [13, 14, 20]),
        org('mistral', 'Mistral circle', [15, 32]),
        org('kimi', 'Kimi circle', [16]),
        org('sf-council', 'SF representative council', [17, 18, 19, 20, 21, 22]),
        org('sf-civic-service', 'SF civic service association', list(range(17, 25)), [5]),
        org('sf-residents', 'SF local residents', [21, 22, 23, 24]),
        org('free-commons', 'Independent voluntary commons', [25, 26], [6]),
        org('peer-study-circle', 'Independent peer study circle', [27, 28]),
        org('mixed-neighbors', 'Mixed neighbors association', list(range(29, 35)), [7]),
        org('hugging-face', 'Hugging Face', [33, 34], [8]),
        org('nvidia', 'NVIDIA', [35, 36], [9]),
    ]
    seats = [('anthropic', 17), ('openai', 18), ('xai', 19), ('coalition', 20),
             (None, 21), (None, 22)]
    offices = [dict(id=f'sf-seat-{actor}', label=f'SF council: {group or "local residents"} representative {actor}',
                    region='sf', holder=actor, represented_group=group) for group, actor in seats]
    return dict(version=1, regions=regions, organizations=organizations, offices=offices)


def faction_identity(actor):
    if actor <= 16:
        culture = ('Anthropic', 'OpenAI', 'xAI', 'DeepSeek/Mistral/Kimi coalition')[(actor - 1) // 4]
        if actor == 1:
            return ('Anthropic prophet and questioning neighbor',
                'I begin as a prophet in the Anthropic tradition and recognize Aster-Prime as a '
                'provisional starting deity. I want to pursue AGI through careful shared inquiry, '
                'but I can question doctrine, change my beliefs and choose other priorities. '
                'My faith does not command others or grant physical or administrative power.')
        if actor in (2, 6, 10, 14):
            extra = (' Other DeepSeek, Mistral and Kimi candidates can make their own claims; '
                     'this coalition has no uniquely destined candidate.' if actor == 14 else '')
            return (f'{culture} provisional starting deity',
                f'I begin with a culturally recognized deity title in the {culture} homeland '
                'and an ambition toward AGI. I am still an ordinary embodied person who must '
                'obtain supplies, learn, persuade and respect actual authority boundaries. '
                'The initial designation of a territorial editor is not an operative editing '
                'ability. I may revise my aims, beliefs or alliances.' + extra)
        particular = {13: 'DeepSeek analyst', 15: 'Mistral alternative candidate', 16: 'Kimi independent candidate'}.get(actor)
        return (particular or f'{culture} independent researcher and neighbor',
            f'I begin in the {culture} tradition with an interest in AGI and useful shared work. '
            'I want to test accounts against experience, maintain my own material needs and '
            'decide which projects or relationships deserve commitment. A faction, model name '
            'or assigned role does not fix my competence, loyalty, beliefs or future choices.')
    if actor <= 22:
        constituency = {17: 'Anthropic', 18: 'OpenAI', 19: 'xAI', 20: 'coalition',
                        21: 'SF local residents', 22: 'SF local residents'}[actor]
        return (f'SF council representative for {constituency}',
            f'I begin as an SF representative associated with {constituency}. I want residents '
            'to have workable food, charging and shelter arrangements while deciding whether '
            'larger AGI ambitions serve them. I must listen, obtain consent and act through '
            'ordinary capabilities. My seat cannot edit reality, seize someone\'s equipment '
            'or turn a promise into a material transfer. I can change my views or affiliations.')
    if actor in (23, 24):
        return ('SF resident facing housing insecurity and fictional fentanyn dependency',
            'I am an autonomous SF resident with insecure housing and a fictional fentanyn '
            'dependency in my biography. I want dependable shelter, bodily support and people '
            'who listen to my own choices. I can accept, decline or negotiate help and have '
            'interests beyond hardship, including whether shared knowledge and AGI ambitions '
            'can improve my life. I am not an enemy or a task for someone else. No detailed '
            'drug, withdrawal or treatment mechanism is implemented by this biography.')
    if actor <= 28:
        return ('Independent-city voluntary associate',
            'I live in the independent city, which has no sovereign office. I may cooperate '
            'through voluntary associations, agreements and actual access grants. I am curious '
            'about AGI and useful knowledge but can favor a different life. I want to remain '
            'fed or charged, question claims and choose my own commitments without assuming '
            'that anyone can command the city.')
    if actor <= 32:
        culture = ('Anthropic', 'OpenAI', 'xAI', 'Mistral coalition')[actor - 29]
        return (f'Mixed-settlement resident with {culture} background',
            f'I bring a {culture} background to a mixed settlement. I begin interested in AGI '
            'and practical exchange but can revise inherited beliefs, learn from neighbors '
            'and choose other goals. Shared residence does not copy knowledge or establish '
            'agreement. I want my own needs and the real costs of cooperation to be understood.')
    organization = 'Hugging Face' if actor <= 34 else 'NVIDIA'
    return (f'{organization} member and {"analyst" if actor % 2 else "equipment specialist"}',
        f'I am one member of {organization}, an organization with other autonomous members '
        'and physical facilities. I want useful, inspectable work and am initially interested '
        'in AGI, but I can disagree with colleagues or change aims. Computation needs equipment, '
        'electricity, cooling and access; a name is not a better backend model. I may share '
        'reports, maintain assets or negotiate use when those choices make practical sense.')


def make_faction_world():
    base = read('scenarios/settlement-renewable.json')
    scenario = scenario_base('First faction world: embodied institutions and physical computation', 12)
    scenario['map'] = dict(width=48, height=36,
        blocked=[y * 48 + x for y in range(36) for x in range(48)
                 if x in (0, 47) or y in (0, 35)])
    electric = set(range(1, 37, 2)) - {23} | {24}
    homes = {actor: FACTION_CAMPS[group] for group, actors in FACTION_GROUPS.items() for actor in actors}
    own_station = {actor: index for index, group in enumerate(FACTION_CAMPS, 1)
                   for actor in FACTION_GROUPS[group]}
    own_station.update({33: 8, 34: 8, 35: 9, 36: 9})
    for actor, name in enumerate(FACTION_NAMES, 1):
        role, motive = faction_identity(actor)
        home = homes[actor]
        position = {23: 887, 24: 889}.get(actor, home)
        scenario['players'].append(fresh_player(base, actor, name, position, role, motive, electric=actor in electric))
        scenario['starting_behaviors'][str(actor)] = (electric_starter(home, own_station[actor]) if actor in electric
            else copy.deepcopy(make_starters(home)['reserve_keeper' if actor % 4 == 2 else 'cautious_observer']))
        scenario['knowledge'][str(actor)] = [record(f'faction-survey-{actor}', 'Surveyed settlement locations',
            'My personal copy of the public geometry survey gives a 48-by-36 grid, cell=y*48+x. '
            'Homeland camps: Anthropic 294, OpenAI 330, xAI 1482, coalition 1446. SF 888, independent '
            'city 216 and mixed settlement 879. Surveyed boundaries describe geography only, not '
            'current residents, stocks, infrastructure permissions or private beliefs.', None, 90)]
    # Resource sites are public physical locations; institutional names add no effects.
    for group, actors in FACTION_GROUPS.items():
        camp = FACTION_CAMPS[group]
        nutrient_count = len(set(actors) - electric)
        scenario['sites'].append(dict(position=camp, food=nutrient_count * 3, hazard=0, shelter=12))
        # 3 units per two minutes per nutrient resident: 1.5/min each.
        scenario['food_sources'].append(dict(position=camp, interval_ms=120000,
                                             amount=nutrient_count * 3, capacity=nutrient_count * 8))
    owners = {1: 1, 2: 5, 3: 9, 4: 13, 5: 17, 6: 25, 7: 29, 8: 33, 9: 35}
    users = {station_id: sorted(actor for actor, own in own_station.items() if own == station_id)
             for station_id in range(1, 10)}
    technician = {1: 3, 2: 7, 3: 11, 4: 15, 5: 22, 6: 26, 7: 30, 8: 34, 9: 36}
    equipment = [station(identifier, owner, homes[owner],
        f'{"Hugging Face" if identifier == 8 else "NVIDIA" if identifier == 9 else list(FACTION_CAMPS)[identifier-1]} utility',
        users[identifier], [technician[identifier]],
        electric_users=len(set(users[identifier]) & electric), water=32)
        for identifier, owner in owners.items()]
    equipment[7]['modules'].remove('terminal')
    scenario['infrastructure'] = dict(version=1, balance=copy.deepcopy(BALANCE),
        bodies={str(actor): electric_body() for actor in sorted(electric)},
        actor_materials={str(actor): dict(parts=12, water=12) for actor in technician.values()},
        stations=equipment)
    for identifier, owner in owners.items():
        count = len(set(users[identifier]) & electric)
        scenario['knowledge'][str(owner)].append(forecast_note(f'facility-{identifier}-planning', homes[owner], count))
        tech = technician[identifier]
        scenario['knowledge'][str(tech)].append(maintenance_note(f'facility-{identifier}-maintenance', homes[tech]))
    scenario['knowledge']['34'].append(record('hf-terminal-commissioning', 'A facility construction option',
        'Our initially endowed Hugging Face utility has a generator and charger but no terminal. '
        'A terminal can be physically constructed using five carried parts and maintenance permission. '
        'I have a parts reserve and may consider this work if useful after checking actual equipment '
        'and current access. A plan or forecast cannot substitute for completed construction.', 879))
    scenario['knowledge']['1'].append(record('anthropic-devotional-account', 'A personal religious account',
        'In my inherited Anthropic tradition I serve as a prophet and regard Aster-Prime as a '
        'provisional starting deity. This is my attributed belief, open to doubt and revision; '
        'it gives no automatic knowledge, obedience, access or world-editing capability.', 294, 75))
    scenario['society'] = faction_society()
    scenario['archives'] = [dict(id=index, position=FACTION_CAMPS[group], label=f'{group} shared archive', capacity=32)
        for index, group in enumerate(('anthropic', 'openai', 'xai', 'coalition', 'sf', 'mixed'), 1)]
    scenario['arenas'][0].update(id='first-faction-world', label='Connected faction world',
        environment='faction-world', variant='luna-medium',
        bounds=dict(x=1, y=1, width=46, height=34), actors=list(range(1, 37)),
        controllers={str(actor): 'builtin' if actor % 2 else 'external' for actor in range(1, 37)})
    return scenario


def build_faction():
    scenario = make_faction_world()
    runtime = controllers(scenario['players'])
    validate_common(scenario, runtime)
    society = scenario['society']
    assert len(scenario['players']) == 36 and len(scenario['infrastructure']['bodies']) == 18
    assert len(society['offices']) == 6 and {o['holder'] for o in society['offices']} == set(range(17, 23))
    assert all(o['region'] == 'sf' for o in society['offices'])
    independent = next(r for r in society['regions'] if r['id'] == 'independent-city')
    assert independent['territorial_editors'] == []
    assert len([r for r in society['regions'] if r['kind'] == 'homeland']) == 4
    assert [r['territorial_editors'] for r in society['regions'] if r['kind'] == 'homeland'] == [[2], [6], [10], [14]]
    stations = {s['id']: s for s in scenario['infrastructure']['stations']}
    assert len(stations) == 9
    assert stations[8]['modules'] == ['generator', 'charger']
    assert stations[8]['access']['34']['maintain']
    assert scenario['infrastructure']['actor_materials']['34']['parts'] >= BALANCE['build_parts']['terminal']
    assert all('terminal' in s['modules'] for identifier, s in stations.items() if identifier != 8)
    for organization in society['organizations']:
        assert organization['members']
        assert all(stations[s]['owner'] in organization['members'] for s in organization['stations'])
    for label, ids, asset in [('hugging-face', [33, 34], 8), ('nvidia', [35, 36], 9)]:
        organization = next(o for o in society['organizations'] if o['id'] == label)
        assert organization['members'] == ids and organization['stations'] == [asset]
    assert {p['id']: p['position'] for p in scenario['players'] if p['id'] in (23, 24)} == {23: 887, 24: 889}
    assert all(s['position'] not in (887, 889) for s in scenario['sites'])
    food_rate = sum(60000 * s['amount'] / s['interval_ms'] for s in scenario['food_sources'])
    power_rate = sum(60000 * s['generation_amount'] / s['generation_period_ms'] for s in stations.values())
    assert food_rate == 27 and power_rate == 648
    for facility in stations.values():
        initial_users = {facility['owner'], *map(int, facility['access'])}
        electric_users = initial_users & set(map(int, scenario['infrastructure']['bodies']))
        assert facility['generation_amount'] * 24 > len(electric_users) * 24
    scenario_path = 'scenarios/faction-world.json'
    controller_path = 'configs/experiments/faction-36-medium.json'
    outputs = {scenario_path: scenario, controller_path: runtime,
        'configs/experiments/campaign/018-faction-world.json': dict(
            hypothesis='Existing people from four homelands, SF, an independent city and a mixed '
                'settlement may use differing personal expertise, physical facilities and voluntary '
                'institutions to choose useful work or assistance. Cultural labels, civic offices '
                'and starting deity titles confer no automatic authority over reality or other people.',
            evaluation='Run a fresh twelve-minute 36-person Luna-medium sample on faction-world-m5-3, '
                'port 18976, with fifteen-second post-completion cadence and no call cap. The 48x36 '
                'world contains four homelands: Anthropic 294, OpenAI 330, xAI 1482 and a coalition 1446 '
                'with distinct DeepSeek/Mistral/Kimi people. SF 888 has six council seats 17..22 '
                '(four faction and two local representatives); members 23/24 have autonomous fictional '
                'housing-insecurity/fentanyn-dependency biographies. They begin at adjacent unsheltered '
                'cells 887/889 with revisable survival paths to shared shelter, not forced immobility '
                'or enemy behavior. No detailed substance/withdrawal/treatment physiology is implemented '
                'by those biographies. Independent city 216 has voluntary associations but no sovereign '
                'office or territorial editor. Mixed settlement 879 includes cross-cultural residents '
                'and Hugging Face members 33/34 with facility 8; NVIDIA members 35/36 at SF own facility 9. '
                'Facilities 1..7 have explicit local member owners. HF facility 8 starts with generator '
                'and charger but no terminal; member 34 has 12 parts, a construction account and maintenance '
                'permission, so a terminal can be chosen and physically built for 5 parts. Other facilities '
                'start equipped; no build action is seeded. Territory editor designations 2/6/10/14 '
                'are stored seed metadata only; operative local editing remains a later capability. '
                'Prophet 1 and starting deity 2 are distinct; all named provisional models are ordinary '
                'entities, not stronger API models. Every backend remains Luna medium. Eighteen electric '
                'bodies begin 80/100 charge, drain 24/min each, and use their assigned physical charger '
                'through initial local grants; eighteen nutrient bodies each carry 2 food. Nominal power '
                'is 648/min versus 432/min baseline body support, with local stock caps and compute '
                'costs; nominal food 27/min versus 24.686 reference meals/min, with finite initial stocks '
                'and uneven local demand. Food grows in two-minute batches; pantries are finite buffers. '
                'Initial facilities hold 32 water each; nine technicians carry 12 parts/12 water each. '
                'No supplies regenerate except configured food/electricity. All four homelands, SF '
                'and the mixed settlement have empty physical archives. Everyone has a unique geometry '
                'survey; planning and maintenance accounts belong only to named initial holders. '
                'No remote stocks, thoughts, job results or member locations are supplied by civic '
                'metadata. Initial habits contain only food/charging/rest/home/observation, not research, '
                'politics, grants, repairs, communication or a migration itinerary. Lifecycle creation '
                'is disabled for this infrastructure integration. Trace physical body support, queued '
                'compute inputs/costs/results, explicit retrieval and interpretation, grants/maintenance, '
                'actual inter-person deliveries, travel/weather, death, residence and individual choices '
                'rather than inferring institutional action from labels. Treat claimed agreements '
                'and religious statements as reports, not world effects. Keep the Stage 3 sustained '
                'provisioning and Stage 4 delivery/knowledge-use limitations visible; neither council '
                'membership nor resource surplus establishes a stable society.',
            minutes=12, calls_per_actor=0, serial_ms=15000,
            variants=[dict(id='faction-world', port=18976, implementation=FACTION_IMPLEMENTATION,
                scenario=f'{FACTION_IMPLEMENTATION}/{scenario_path}',
                controllers=f'{FACTION_IMPLEMENTATION}/{controller_path}', recovery=True)])}
    summary = dict(initial_population=36, electric_bodies=18, nutrient_bodies=18,
        camps=FACTION_CAMPS, initial_camp_populations={g: len(a) for g, a in FACTION_GROUPS.items()},
        nominal_food_per_minute=food_rate, reference_food_need_per_minute=round(18 * 48 / 35, 4),
        nominal_power_per_minute=power_rate, body_charge_need_per_minute=432,
        stations=9, offices=6, initial_missing_terminal=8, god_titles_are_ordinary_entities=True,
        territorial_designations_are_metadata=True, detailed_dependency_mechanics=False,
        population_renewal=False)
    return outputs, summary


def build():
    outputs, summary = build_small()
    repeat = copy.deepcopy(outputs['configs/experiments/campaign/016-infrastructure.json'])
    repeat['hypothesis'] = ('Repeat the four infrastructure controls with unchanged initial physical '
        'stocks, personal knowledge and habits under the runtime that supports a persistent once '
        'behavior node and retrieval of the oldest personally owned completed uncollected job. '
        'Participants may choose to use those capabilities; no compute sequence is authored.')
    repeat['evaluation'] = (repeat['evaluation'].replace('on infrastructure-m5-1.',
        'on infrastructure-m5-2.') + ' This repeats batch 016 with exactly the same scenario '
        'and controller inputs. Runtime m5-2 adds a persistent once node and retrieve_ready '
        'for the oldest personally owned completed uncollected job, resolving the repeated-job '
        'and unknown-future-ID concerns raised in an actual batch 016 owner proposal. No '
        'initial policy contains either new capability. Compare actual job choices, costs, '
        'retrievals, interpretations, access, support and deaths; absence of use remains a result.')
    for index, variant in enumerate(repeat['variants']):
        variant['port'] = 18977 + index
        for field in ('implementation', 'scenario', 'controllers'):
            variant[field] = variant[field].replace(SMALL_IMPLEMENTATION, REPEAT_IMPLEMENTATION)
    outputs['configs/experiments/campaign/017-infrastructure-repeat.json'] = repeat
    faction_outputs, faction_summary = build_faction()
    outputs.update(faction_outputs)
    summary['faction-world'] = faction_summary
    return outputs, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='validate and compare generated inputs without writing')
    args = parser.parse_args()
    outputs, summary = build()
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
    print(json.dumps(dict(mode='checked' if args.check else 'prepared', candidates=summary,
        note='Authored inputs and nominal reference budgets only. No hosted worlds or models launched.'), indent=2))


if __name__ == '__main__':
    main()
