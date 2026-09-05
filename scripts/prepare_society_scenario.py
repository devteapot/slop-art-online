#!/usr/bin/env python3
"""Prepare four independent characters and shared opportunities; install no behavior trees."""
import copy
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+'\n')
def main():
    source=json.loads((ROOT/'scenarios/woodland-pathfinding.json').read_text())['players']
    width,height=16,12
    blocked=[y*width+x for y in range(height) for x in range(width) if x in (0,width-1) or y in (0,height-1)]
    people=[
      ('Mira','craftsperson','I want a lasting home where my work matters. I value being trusted, but dislike being taken for granted.',65,80,85,2),
      ('Tovan','forager','I want independence and a reliable food reserve. I take pride in finding resources and prefer concrete reciprocal help to vague promises.',40,45,70,2),
      ('Iri','caretaker','I want these unfamiliar people to have a fair chance of surviving together. I will judge trust by what people actually do, and I need to remain capable myself.',65,90,85,6),
      ('Renn','wanderer','I want to survive and earn a place among these people without becoming dependent or exploited. I am hungry, skeptical of promises, and willing to prove useful.',70,55,70,0),
    ]
    players=[]
    for i,(name,role,motive,caution,empathy,introspection,food) in enumerate(people,1):
        p=copy.deepcopy(source[(i-1)%2]);p.update(id=i,name=name,role=role,motive=motive,position=84,
            food=food,hunger=20 if i!=4 else 45,health=100,energy=80,caution=caution,empathy=empathy,
            introspection=introspection,fear=0,relationships={},memories=[],site_observations=[],
            current_goal=None,execution=None,generation=0,failures=0,last_reflection=0,last_cause=None)
        p['beliefs']=[dict(claim=dict(location=88,danger=False,text='I remember a berry thicket four cells east of the camp. Its current food stock is unknown.'),source=0,confidence=40),
                      dict(claim=dict(location=84,danger=False,text='This is the clearing where we met; no one has exclusive ownership of its supplies or shelter.'),source=0,confidence=60)]
        players.append(p)
    arena=dict(id='clearing',label='Four people / first winter',environment='shared-clearing',variant='luna-medium',
               bounds=dict(x=1,y=1,width=14,height=10),actors=[1,2,3,4],controllers={'1':'builtin','2':'external','3':'builtin','4':'external'})
    scenario=dict(name='First winter: shared clearing',seed=4242,max_ticks=192,map=dict(width=width,height=height,blocked=blocked),
                  arenas=[arena],players=players,sites=[dict(position=84,food=18,hazard=0,shelter=0),dict(position=88,food=80,hazard=0,shelter=0),dict(position=56,food=30,hazard=0,shelter=0)],
                  weather=dict(cold_after_ms=180000,damage_per_pulse=2,shelter_required=12))
    write(ROOT/'scenarios/society-first-winter.json',scenario)
    scarce=copy.deepcopy(scenario);scarce['name']='First winter: food shortage control'
    for site in scarce['sites']:site['food']=0
    write(ROOT/'scenarios/society-first-winter-shortage.json',scarce)
    configs=json.loads((ROOT/'configs/experiments/luna-arena-matrix.json').read_text())
    config=next(c['config'] for c in configs if c['config']['backend']['reasoning_effort']=='medium')
    controllers=[dict(actor=i,role=arena['controllers'][str(i)],config=copy.deepcopy(config)) for i in range(1,5)]
    write(ROOT/'configs/experiments/society-four-medium.json',controllers)
if __name__=='__main__':main()
