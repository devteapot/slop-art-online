"""Check the archived first fit, its factory rebuild and both Bevy capture sets."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
APPROVED = HERE.parent/'back-hair/plait'
sys.path.insert(0,str(HERE.parents[2]/'living/tools'))
from merge_primitives import read_accessor, read_glb


def read_json(path):
    return json.loads(path.read_text())


def pixels(path):
    return np.asarray(Image.open(path).convert('RGBA'))


def difference(a,b):
    return int(np.any(pixels(a) != pixels(b),axis=-1).sum())


def inspect_meshes(path):
    doc, buf = read_glb(path)
    def values(i):
        data,_ = read_accessor(doc,buf,i)
        return np.asarray(data).reshape(doc['accessors'][i]['count'],-1)
    fixed = {}
    hair = []
    for mesh in doc['meshes']:
        for prim in mesh['primitives']:
            material = doc['materials'][prim['material']]
            role = material['extras']['slop']['slot']
            attr = prim['attributes']
            if role == 'hair':
                hair.append(values(attr['POSITION']))
            if role == 'face':
                skin = values(attr['POSITION'])
            if not prim.get('targets') or 'FaceBrow' in material['name']:
                fixed[material['name']] = (
                    material, {k:values(a).tobytes() for k,a in attr.items()},
                    values(prim['indices']).tobytes(),
                    [{k:values(a).tobytes() for k,a in shape.items()} for shape in prim.get('targets',[])])
    pos = np.vstack(hair)
    crown = float(max(pos[:,1]))
    h = crown-1.42720544
    volume = dict(spread=float(np.ptp(pos[pos[:,1]>1.399,0])/.1178866317169),
                  crown_lift=(crown-float(max(skin[:,1])))/h,
                  rear_depth=(.0052969-float(min(pos[pos[:,1]>1.47675,2])))/h)
    return fixed, volume


def check(rebuild, frames):
    facts = read_json(HERE/'game-counts.json')
    expr = HERE/'expressions'
    changes = {k:difference(expr/'eye-neutral.png',expr/f'eye-{k}.png') for k in facts['face_keys']}
    assert len(changes)==15 and min(changes.values())>0
    neutral = difference(expr/'eye-neutral.png',expr/'eye-returned.png')
    assert neutral==0
    fixed, volume = inspect_meshes(HERE/'own-cora-live.glb')
    base, old_volume = inspect_meshes(APPROVED/'own-cora-live.glb')
    assert fixed.keys()==base.keys() and len(fixed)>=5 and fixed==base
    assert volume==old_volume and abs(volume['spread']-1.87)<.10
    assert abs(volume['crown_lift']-.096)<.035 and abs(volume['rear_depth']-.53)<.04
    assert (HERE/'own-cora-live.hair.png').read_bytes()==(APPROVED/'own-cora-live.hair.png').read_bytes()
    artifacts = {}
    for suffix in ('glb','face.png','hair.png','calibration.json'):
        name='own-cora-live.'+suffix
        data=(HERE/name).read_bytes()
        assert data==(rebuild/name).read_bytes()
        artifacts[name]=hashlib.sha256(data).hexdigest()
    expression_replay = {p.stem:difference(p,rebuild/p.name) for p in expr.glob('*.png')}
    assert len(expression_replay)==18 and not any(expression_replay.values())
    before = read_json(APPROVED/'calibration-report.json')
    current = read_json(HERE/'calibration-report.json')
    replay = read_json(frames/'report.json')
    assert current['passed'] and replay['passed'] and current['patches']==replay['patches']
    assert current['patches']==before['patches']
    cloth = read_json(HERE/'cloth.json')
    assert cloth['passed'] and len(cloth['patches'])==8
    checks={(p['shot'],p['patch']) for p in current['patches']+cloth['patches']}
    assert len(checks)==20 and all(p['passed'] for p in current['patches']+cloth['patches'])
    for path in (HERE/'audit.jsonl',rebuild/'audit.jsonl'):
        records=[json.loads(l) for l in path.read_text().splitlines()]
        assert records[-1]['stage']=='item2-expression-sweep' and not any(r['failures'] for r in records)
    for report in (current,replay):
        assert not report['audit']['errors'] and not report['audit']['warnings']
    frames_same={k:difference(HERE/path,frames/replay['shots'][k]) for k,path in current['shots'].items()}
    assert len(frames_same)==13 and not any(frames_same.values())
    rear={k:difference(HERE/current['shots'][k],APPROVED/before['shots'][k]) for k in
          ('near_180','middle_180','180:8:0.36:0.88','180:8:0.75:0.68')}
    assert not any(rear.values())
    near = pixels(HERE/current['shots']['near']).astype(int)
    near_before = pixels(APPROVED/before['shots']['near']).astype(int)
    near_delta = np.abs(near[:,:,:3]-near_before[:,:,:3]).max(axis=2)
    return dict(approved_meshes_identical=sorted(fixed),volume=volume,
                near_max_channel_change=int(near_delta.max()),
                near_pixels_changed_over_eight_levels=int(np.count_nonzero(near_delta>8)),
                distinct_passed_colour_checks=len(checks),factory_sha256=artifacts,
                expressive_pixels=changes,returned_neutral_pixels=neutral,
                factory_expression_different_pixels=expression_replay,
                factory_daylight_different_pixels=frames_same,approved_rear_different_pixels=rear)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rebuild',type=Path)
    parser.add_argument('frames',type=Path)
    args=parser.parse_args()
    print(json.dumps(check(args.rebuild,args.frames),indent=2))
