"""Compare the nose export, first eye fit, independent factory replay and daylight frames."""
import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent/'eye-frame'
sys.path.insert(0,str(PREVIOUS))
from verify_fit import difference, pixels, read_glb, read_json, inspect_meshes


def asset(path):
    doc, binary = read_glb(path)
    # Image lengths and the buffer offsets after them may move. Compare
    # every packed view by its contents and all other glTF properties.
    blobs = []
    for view in doc['bufferViews']:
        start = view.pop('byteOffset',0)
        length = view.pop('byteLength')
        blobs.append(binary[start:start+length])
    doc['buffers'][0].pop('byteLength')
    return doc, blobs


def check(rebuild, captures):
    name = 'own-cora-live.glb'
    old, old_blobs = asset(PREVIOUS/name)
    doc, blobs = asset(HERE/name)
    assert doc==old and len(blobs)==len(old_blobs)
    i = next(im['bufferView'] for im in doc['images'] if im['name']=='cora.atlas')
    assert [k for k,(a,b) in enumerate(zip(old_blobs,blobs)) if a!=b]==[i]
    a,b = [np.asarray(Image.open(io.BytesIO(blob)).convert('RGB')) for blob in (old_blobs[i],blobs[i])]
    yy,xx = np.nonzero(np.any(a!=b,axis=2))
    assert len(xx) and np.all((((xx+.5)/a.shape[1]-.502)/.070)**2+(((yy+.5)/a.shape[0]-.722)/.055)**2<1)
    atlas_hashes = read_json(HERE/'nose-atlas.json')
    assert [hashlib.sha256(blob).hexdigest() for blob in (old_blobs[i],blobs[i])]==[atlas_hashes[k] for k in ('source','painted')]
    _,volume = inspect_meshes(HERE/name)
    assert volume==read_json(PREVIOUS/'replay-check.json')['volume']
    artifacts = {}
    for suffix in ('glb','hair.png','face.png','calibration.json'):
        n='own-cora-live.'+suffix
        data=(HERE/n).read_bytes()
        assert data==(rebuild/n).read_bytes()
        if suffix!='glb':
            assert data==(PREVIOUS/n).read_bytes()
        artifacts[n]=hashlib.sha256(data).hexdigest()
    counts=read_json(HERE/'game-counts.json')
    assert counts==read_json(PREVIOUS/'game-counts.json')
    expr=HERE/'expressions'
    changed={k:difference(expr/'eye-neutral.png',expr/f'eye-{k}.png') for k in counts['face_keys']}
    assert len(changed)==15 and min(changed.values())>0
    neutral=difference(expr/'eye-neutral.png',expr/'eye-returned.png')
    expressions={f.stem:difference(f,rebuild/f.name) for f in expr.glob('*.png')}
    assert neutral==0 and len(expressions)==18 and not any(expressions.values())
    before=read_json(PREVIOUS/'calibration-report.json')
    fit=read_json(HERE/'calibration-report.json')
    repeated=read_json(captures/'report.json')
    for report in (fit,repeated):
        assert report['passed'] and not report['audit']['errors'] and not report['audit']['warnings']
        assert report['patches']==before['patches']
    for root in (HERE,rebuild):
        audits=[json.loads(l) for l in (root/'audit.jsonl').read_text().splitlines()]
        assert audits[-1]['stage']=='item4-expression-sweep' and not any(r['failures'] for r in audits)
    cloth=read_json(HERE/'cloth.json')
    assert cloth==read_json(PREVIOUS/'cloth.json') and cloth['passed']
    checks={(p['shot'],p['patch']) for p in fit['patches']+cloth['patches']}
    assert len(checks)==20
    stills={k:difference(HERE/v,captures/repeated['shots'][k]) for k,v in fit['shots'].items()}
    assert len(stills)==13 and not any(stills.values())
    rear={k:difference(HERE/fit['shots'][k],PREVIOUS/before['shots'][k]) for k in
          ('near_180','middle_180','180:8:0.36:0.88','180:8:0.75:0.68')}
    # Separate eye boxes exclude the bridge that runs between them.
    windows={'portrait':[(738,356,792,393),(822,364,887,400)],
             '-35:8:0.36:0.88':[(770,356,837,391),(865,365,897,395)]}
    eyes={}
    for k,boxes in windows.items():
        delta=np.abs(pixels(HERE/fit['shots'][k]).astype(int)-pixels(PREVIOUS/before['shots'][k]).astype(int))
        eyes[k]=[]
        for x,y,r,t in boxes:
            region=delta[y:t,x:r,:3].max(axis=2)
            eyes[k].append(dict(box_xyxy=[x,y,r,t],changed_pixels=int(np.count_nonzero(region)),
                                maximum_channel_delta=int(region.max())))
            assert region.max()<=1
    assert not any(rear.values())
    return dict(only_changed_glb_buffer_view=i,nose_atlas_changed_texels=len(xx),
                atlas_changed_bounds_xy=[int(xx.min()),int(yy.min()),int(xx.max()),int(yy.max())],
                approved_eye_pixel_deltas=eyes,approved_rear_changed_pixels=rear,
                volume=volume,colour_checks=len(checks),expression_changed_pixels=changed,
                neutral_return_changed_pixels=neutral,factory_artifacts_sha256=artifacts,
                factory_expression_changed_pixels=expressions,factory_daylight_changed_pixels=stills)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('rebuild',type=Path)
    p.add_argument('captures',type=Path)
    args=p.parse_args()
    print(json.dumps(check(args.rebuild,args.captures),indent=2))
