#!/usr/bin/env python3
"""Prepare autonomous territorial/universal law experiments without running worlds."""
import argparse
import copy
import json
from pathlib import Path

from prepare_infrastructure_scenarios import (BALANCE, controllers, electric_body,
    electric_starter, fresh_player, read, record, scenario_base, station, walk_actions)
from starting_behavior_presets import make_starters

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = 'output/society-lab/implementations/reality-m7-1'
DURATION_MINUTES = 24
AUTHOR_ABSENCE_MS = 1_080_000
VARIANTS = ('local-borders', 'universal-repeat', 'cooling', 'author-absence')
HOMES = {1:84, 2:84, 3:88, 4:88}


def make_scenario(variant):
    if variant not in VARIANTS:
        raise ValueError(variant)
    base = read('scenarios/settlement-renewable.json')
    scenario = scenario_base(f'Autonomous physical law: {variant}', DURATION_MINUTES)
    people = [
        ('Ari', 'ordinary god with the initial west territorial grant',
         'I live in the west camp at cell 84. People call me a god, but I still need electricity, '
         'rest and other people. My initial editing grant concerns the west territory only. I am '
         'curious whether everyday effort and recovery here make sense, and what a different '
         'arrangement would mean for neighbors. I can choose to investigate, listen, change '
         'something or leave it alone; my title does not decide anyone else\'s goals.'),
        ('Bryn', 'independent west neighbor interested in practical understanding',
         'I live at cell 84 and want useful work, food and independence. I do not hold an initial '
         'territorial editing grant. I am curious about how practical understanding can give an '
         'ordinary person a say in the rules everyone lives under. I may question a claim, study '
         'something communicated to me, experiment myself or pursue another priority.'),
        ('Cato', 'east neighbor with the initial east territorial grant',
         'I live in the east camp at cell 88 and hold its initial territorial editing grant. I '
         'want dependable charging and time for work worth doing. I wonder whether our everyday '
         'conditions fit the people here, and whether the same change would suit the west. I '
         'can reconsider my preferences and choose whether or how to use my grant.'),
        ('Dara', 'independent east neighbor concerned with shared life',
         'I live at cell 88 and care about reliable food and arrangements people can understand '
         'across a border. I have no initial territorial editing grant. I am interested in what '
         'persists when an influential person is absent, but I can decide whether to investigate, '
         'travel, preserve knowledge, exchange ideas or look after other needs.'),
    ]
    for actor, (name, role, motive) in enumerate(people, 1):
        home=HOMES[actor]
        electric=actor in (1,3)
        scenario['players'].append(fresh_player(base,actor,name,home,role,motive,electric=electric))
        scenario['starting_behaviors'][str(actor)] = (electric_starter(home,1 if home==84 else 2)
            if electric else copy.deepcopy(make_starters(home)['reserve_keeper']))
    scenario['sites']=[dict(position=home,food=6,hazard=0,shelter=12) for home in (84,88)]
    scenario['food_sources']=[dict(position=home,interval_ms=15000,amount=1,capacity=12) for home in (84,88)]
    scenario['archives']=[dict(id=index,position=home,label=label,capacity=32)
        for index,home,label in ((1,84,'West notebook cabinet'),(2,88,'East notebook cabinet'))]
    scenario['society']=dict(version=1,regions=[
        dict(id='west',label='West territory',kind='homeland',bounds=dict(x=1,y=1,width=7,height=10),
             territorial_editors=[1],priority=0),
        dict(id='east',label='East territory',kind='homeland',bounds=dict(x=8,y=1,width=7,height=10),
             territorial_editors=[3],priority=0)],organizations=[],offices=[])
    scenario['knowledge']={
        '1':[record('west-effort-question','An open question about ordinary work',
            'The west camp is at cell 84; the east camp is at cell 88. Their adjacent territories '
            'meet between columns seven and eight. My west grant is current institutional starting '
            'information, not a universal entitlement. I wonder whether effort spent on everyday '
            'work ought to depend on what is being done, and whether any change would be tolerable '
            'in a neighboring camp. I have no tested candidate or answers.',84)],
        '2':[record('ordinary-understanding-question','Understanding without an initial grant',
            'A copied account can be useful without making its claims true or giving me its '
            'author\'s experience. The local terminal can do conditional calculations and paid '
            'experiments. Equipment power, cooling and condition are finite. I wonder what I '
            'could learn for myself and what kind of evidence would make a rule change credible '
            'beyond one territory. This is an unresolved question, not a prescribed route.',84)],
        '3':[record('east-difference-question','Two camps and different priorities',
            'The east camp is at cell 88 and the west at cell 84, across the boundary between '
            'columns seven and eight. My initial grant concerns the east territory. People might '
            'value less tiring work, reliable food and freedom to visit differently. I have no '
            'tested source or promised outcome; I am interested in what an actual change would '
            'do to everyday life and people crossing the boundary.',88)],
        '4':[record('continuity-and-maintenance','Knowledge, equipment and continuity',
            'Each camp has a terminal and notebook cabinet. Local power, cooling water and '
            'equipment condition are real constraints; carried supplies do not automatically '
            'reach a machine. Personal reports, cabinet copies and installed rules are different '
            'things. I wonder which arrangements and knowledge people could still use if a '
            'grant-holder became absent. Nothing in this account determines anyone\'s actions.',88)],
    }
    stations=[]
    for sid,owner,home in ((1,1,84),(2,3,88)):
        equipment=station(sid,owner,home,'West utility' if sid==1 else 'East utility',
            [1,2,3,4],[2,4],electric_users=1,water=36)
        equipment.update(electricity=60,electricity_capacity=120,generation_amount=2)
        stations.append(equipment)
    if variant=='cooling':
        stations[0]['materials']['water']=1
    scenario['infrastructure']=dict(version=1,balance=copy.deepcopy(BALANCE),
        bodies={str(a):electric_body() for a in (1,3)},
        actor_materials={'2':dict(parts=8,water=12),'4':dict(parts=8,water=12)},stations=stations)
    if variant=='author-absence':
        scenario['disturbances']=[dict(at_ms=AUTHOR_ABSENCE_MS,kind='damage',actor=1,amount=100)]
    scenario['arenas'][0].update(id='physical-laws',label='Two territories and independent neighbors',
        environment='law-control',variant='luna-medium',actors=[1,2,3,4],
        controllers={str(a):'builtin' if a%2 else 'external' for a in range(1,5)})
    return scenario


def validate(scenario,runtime):
    assert len(scenario['players'])==len(runtime)==4
    assert scenario['max_ticks']==DURATION_MINUTES*24 and scenario['lifecycle'] is None
    assert scenario['society']['organizations']==scenario['society']['offices']==[]
    assert [r['territorial_editors'] for r in scenario['society']['regions']]==[[1],[3]]
    assert all(r['priority']==0 for r in scenario['society']['regions'])
    assert scenario['infrastructure']['balance']==BALANCE
    for player,control in zip(scenario['players'],runtime):
        assert player['id']==control['actor'] and player['controller']=='ai'
        assert control['config']['backend']['model']=='gpt-5.6-luna'
        assert control['config']['backend']['reasoning_effort']=='medium'
        assert not player['knowledge'] and not player['beliefs'] and not player['memories']
        for action in walk_actions(scenario['starting_behaviors'][str(player['id'])]['tree']):
            assert action['skill'] in ('eat','rest','move','gather','deposit','observe','wait','infrastructure')
            if action['skill']=='infrastructure':
                assert action['infrastructure']['op']=='charge'
    for records in scenario['knowledge'].values():
        for note in records:
            assert not any(note.get(k) for k in ('program','experiment','law_program','law_experiment'))
            assert 'fn ' not in note['text']


def build():
    outputs,variants={},[]
    for index,name in enumerate(VARIANTS):
        scenario=make_scenario(name);runtime=controllers(scenario['players']);validate(scenario,runtime)
        path=f'scenarios/law-{name}.json';control='configs/experiments/law-4-medium.json'
        outputs[path]=scenario;outputs[control]=runtime
        variants.append(dict(id=name,port=18991+index,implementation=IMPLEMENTATION,
            scenario=f'{IMPLEMENTATION}/{path}',controllers=f'{IMPLEMENTATION}/{control}',recovery=True))
    outputs['configs/experiments/campaign/022-physical-laws.json']=dict(
        hypothesis='Four autonomous neighbors in two territories may author and test real physical-law '
            'changes, exercise endowed local grants, develop broader authority through personal '
            'experiments or communicated source, and experience chosen rules across a border. '
            'Neither research, travel, editing, cooperation nor persistence after death is guaranteed.',
        evaluation='Run four fresh concurrent twenty-four-minute worlds with identical Luna medium '
            'controllers, serial behavior/communication/learning, fifteen seconds after each '
            'completion and no call cap. Local-borders and universal-repeat differ only in name. '
            'Cooling changes only west station water 36 to 1; east station and carried supplies '
            'remain available if people choose to use them. Author-absence changes only one '
            'authored damage disturbance against actor 1 at 1080000 ms. The active damage law may '
            'change its effect; only actual recorded death following actual law authorship can '
            'activate author-death persistence evidence. Both local grant-holders are endowed '
            'editors irrespective of narrative title. Independents have no initial grant; '
            'current mechanics allow personally assessed paid numeric terminal work or taught source '
            'and own paid practice. No seeded code, candidate cases, computed proofs, forced '
            'research/edit/travel actions or AGI score. Audit paid work and private cases, exact '
            'source/current-binding own proof, requested versus staged versus activated edits, '
            'law scope/revision/precedence, current effect authorization, crossings and survival. '
            'Universal authorization resolves universal/base rules, never a local self-promotion. '
            'Default proof requirements are not immutable: a valid participant-authored universal '
            'authorization change may legally alter later requirements. Retain harmful but valid '
            'changes, quarantined invalid hooks, failures and nonactivation without automatic rescue '
            'or success. Preserve exact food/material audits under actual recorded production. '
            'The twenty-four-minute duration and eighteen-minute authored absence are fixed before '
            'launch, informed by observed roughly 84-second responsibility recurrence in Stage 6; '
            'they allow more investigation and a final six-minute persistence window without '
            'prescribing an outcome.',
        minutes=DURATION_MINUTES,calls_per_actor=0,serial_ms=15000,concurrency=4,variants=variants)
    return outputs


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    for relative,value in build().items():
        path=ROOT/relative
        if args.check:
            if not path.is_file() or json.loads(path.read_text())!=value:
                raise SystemExit(f'Generated input differs: {relative}')
        else:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps(dict(mode='checked' if args.check else 'prepared',variants=list(VARIANTS),
        population_each=4,minutes_each=DURATION_MINUTES,nominal_food_per_minute=8,nominal_power_per_minute=96,
        body_charge_need_per_minute=48,initial_local_editors=[1,3],
        note='Prepared inputs only; no model/host launch, freeze or outcome claim.'),indent=2))


if __name__=='__main__':main()
