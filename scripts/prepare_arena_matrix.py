#!/usr/bin/env python3
"""Compose isolated copies of a scenario; controller configs contain credential references only."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def prepare():
    base = json.loads((ROOT/'scenarios/woodland-pathfinding.json').read_text())
    config = json.loads((ROOT/'configs/reasoning/codex-carlid-luna-streaming-proof.json').read_text())
    width, height = 76, 35
    scenario = dict(name='Luna reasoning matrix — open and corridors', seed=base['seed'], max_ticks=120,
                    map=dict(width=width,height=height,blocked=[]),arenas=[],players=[],sites=[])
    blocked = set(range(width*height))
    controllers=[]
    for row,environment in enumerate(('open','corridors')):
        for col,effort in enumerate(('low','medium','high')):
            index=row*3+col
            x,y=1+col*25,1+row*17
            arena=dict(id=f'{environment}-{effort}',label=f'Luna {effort} / {environment}',
                       environment=environment,variant=f'gpt-5.6-luna / requested {effort}',
                       bounds=dict(x=x,y=y,width=24,height=16),actors=[index*2+1,index*2+2])
            arena['controllers']={str(arena['actors'][0]):'builtin',str(arena['actors'][1]):'external'}
            scenario['arenas'].append(arena)
            def translate(cell):return (y+cell//24)*width+x+cell%24
            for ly in range(16):
                for lx in range(24):blocked.discard((y+ly)*width+x+lx)
            if environment=='corridors':blocked.update(map(translate,base['map']['blocked']))
            for n, original in enumerate(base['players']):
                player=copy.deepcopy(original)
                player['id']=arena['actors'][n]
                player['position']=translate(player['position'])
                for belief in player['beliefs']:
                    location=translate(belief['claim']['location']);belief['claim']['location']=location
                    belief['claim']['text']=f'A traveller reported food at cell {location} ({location%width}, {location//width}). The terrain survey is shared, but this food report is unverified.'
                scenario['players'].append(player)
                cfg=copy.deepcopy(config)
                cfg['backend']['reasoning_effort']=effort
                cfg['backend']['capabilities']['reasoning_efforts']=['low','medium','high']
                controllers.append(dict(actor=player['id'],role='builtin' if n==0 else 'external',config=cfg))
            for original in base['sites']:
                site=copy.deepcopy(original);site['position']=translate(site['position']);scenario['sites'].append(site)
    scenario['map']['blocked']=sorted(blocked)
    for path,value in [('scenarios/luna-arena-matrix.json',scenario),('configs/experiments/luna-arena-matrix.json',controllers)]:
        (ROOT/path).write_text(json.dumps(value,indent=2)+'\n')
    print('Prepared 6 arenas, 12 actors on a 76×35 grid.')

if __name__=='__main__':prepare()
