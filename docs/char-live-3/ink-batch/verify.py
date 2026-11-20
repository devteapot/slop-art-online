"""Check the ink batch: what changed against the accepted nose fit, the independent factory
rebuild, the expression sweep, colour, and a second Bevy capture from the rebuilt export.

    python3 verify.py REBUILD_DIR SECOND_CAPTURE_DIR > replay-check.json
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BEFORE = HERE.parent/'nose'
sys.path.insert(0, str(HERE.parent/'eye-frame'))
from verify_fit import difference, inspect_meshes, read_glb, read_json  # noqa: E402
from merge_primitives import read_accessor  # noqa: E402

NAME = 'own-cora-live'
INK = ('Cora_LidInk_EYE', 'Cora_BrowInk_EYE', 'Cora_JawInk_SKIN', 'Cora_NoseInk_SKIN')


def primitives(path):
    doc, buf = read_glb(path)
    out = {}
    for mesh in doc['meshes']:
        for prim in mesh['primitives']:
            mat = doc['materials'][prim['material']]
            arrays = {k: np.asarray(read_accessor(doc, buf, a)[0]).tobytes() for k, a in prim['attributes'].items()}
            arrays['indices'] = np.asarray(read_accessor(doc, buf, prim['indices'])[0]).tobytes()
            for t, tg in enumerate(prim.get('targets', [])):
                for k, a in tg.items():
                    arrays[f'target{t}.{k}'] = np.asarray(read_accessor(doc, buf, a)[0]).tobytes()
            out[mat['name']] = (mat, arrays)
    return doc, buf, out


def image_bytes(doc, buf, name):
    view = doc['bufferViews'][next(im['bufferView'] for im in doc['images'] if im['name'] == name)]
    o = view.get('byteOffset', 0)
    return bytes(buf[o:o + view['byteLength']])


def check(rebuild, second):
    # 1. Against the accepted nose fit: what changed and what held.
    old_doc, old_buf, old = primitives(BEFORE/f'{NAME}.glb')
    new_doc, new_buf, new = primitives(HERE/f'{NAME}.glb')
    held, changed = [], {}
    for name in sorted(set(old) | set(new)):
        if name not in new or name not in old:
            changed[name] = 'removed' if name in old else 'added'
            continue
        diff = [k for k in set(old[name][1]) | set(new[name][1]) if old[name][1].get(k) != new[name][1].get(k)]
        if diff or old[name][0] != new[name][0]:
            changed[name] = sorted(diff) + (['material'] if old[name][0] != new[name][0] else [])
        else:
            held.append(name)
    assert set(changed) == set(INK) | {'M00_000_00_FaceBrow_00_FACE', 'M00_000_00_FaceEyeline_00_FACE', 'M00_000_00_Body_00_SKIN'}, changed
    assert changed['M00_000_00_Body_00_SKIN'] == ['COLOR_0'], changed['M00_000_00_Body_00_SKIN']
    images = {}
    for im in old_doc['images']:
        a, b = image_bytes(old_doc, old_buf, im['name']), image_bytes(new_doc, new_buf, im['name'])
        images[im['name']] = 'same' if a == b else 'changed'
    assert [k for k, v in images.items() if v == 'changed'] == ['cora.atlas']
    assert old_doc['animations'] and len(old_doc['animations']) == len(new_doc['animations'])
    _, volume = inspect_meshes(HERE/f'{NAME}.glb')
    assert volume == read_json(BEFORE/'replay-check.json')['volume']
    sidecars = {s: (HERE/f'{NAME}.{s}').read_bytes() == (BEFORE/f'{NAME}.{s}').read_bytes()
                for s in ('hair.png', 'calibration.json', 'face.png')}
    assert sidecars['hair.png'] and sidecars['calibration.json']
    # 2. The independent factory rebuild, byte for byte and pixel for pixel.
    artifacts = {}
    for suffix in ('glb', 'face.png', 'hair.png', 'calibration.json', 'eyes.ink.png', 'skin.ink.png'):
        data = (HERE/f'{NAME}.{suffix}').read_bytes()
        assert data == (rebuild/f'{NAME}.{suffix}').read_bytes(), suffix
        artifacts[f'{NAME}.{suffix}'] = hashlib.sha256(data).hexdigest()
    expr = HERE/'expressions'
    factory_frames = {f.stem: difference(f, rebuild/f.name) for f in sorted(expr.glob('*.png'))}
    assert len(factory_frames) == 18 and not any(factory_frames.values())
    counts = read_json(HERE/'game-counts.json')
    assert counts['triangles'] <= 50000 and len(counts['face_keys']) == 15 and counts == read_json(rebuild/'game-counts.json')
    keys = {k: difference(expr/'eye-neutral.png', expr/f'eye-{k}.png') for k in counts['face_keys']}
    assert min(keys.values()) > 0
    neutral = difference(expr/'eye-neutral.png', expr/'eye-returned.png')
    assert neutral == 0
    for root in (HERE, rebuild):
        audits = [json.loads(line) for line in (root/'audit.jsonl').read_text().splitlines()]
        assert audits[-1]['stage'] == 'item2-5-expression-sweep' and not any(r['failures'] for r in audits)
    # 3. Colour and the contract audit, and a second Bevy capture from the rebuilt export.
    report = read_json(HERE/'calibration-report.json')
    assert report['passed'] and not report['audit']['errors'] and not report['audit']['warnings']
    cloth = read_json(HERE/'cloth.json')
    assert cloth['passed'] and cloth == read_json(BEFORE/'cloth.json')
    checks = {(p['shot'], p['patch']) for p in report['patches'] + cloth['patches']}
    assert len(checks) == 20
    second_report = read_json(second/'report.json')
    stills = {k: difference(HERE/'stills'/Path(v).name, Path(second_report['shots'][k])) for k, v in report['shots'].items()}
    assert len(stills) == 17 and not any(stills.values())
    before = read_json(BEFORE/'calibration-report.json')
    rear = {k: difference(HERE/'stills'/Path(report['shots'][k]).name, BEFORE/before['shots'][k])
            for k in ('near_180', 'middle_180', '180:8:0.36:0.88', '180:8:0.75:0.68')}
    moved = {(p['patch'], p['shot']): [n - o for n, o in zip(p['measured'], q['measured'])]
             for p in report['patches'] for q in before['patches'] if (p['patch'], p['shot']) == (q['patch'], q['shot'])}
    return dict(changed_against_nose_fit=changed, held_primitives=held, embedded_images=images,
                sidecars_same_as_nose_fit=sidecars, volume=volume, triangles=counts['triangles'],
                factory_artifacts_sha256=artifacts, factory_expression_changed_pixels=factory_frames,
                expression_changed_pixels=keys, neutral_return_changed_pixels=neutral,
                colour_checks=len(checks), colour_patch_change_since_nose_fit={f'{a} / {b}': d for (a, b), d in moved.items()},
                second_capture_changed_pixels=stills, rear_frames_changed_pixels_vs_nose_fit=rear)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('rebuild', type=Path)
    p.add_argument('second', type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.rebuild, a.second), indent=2))
