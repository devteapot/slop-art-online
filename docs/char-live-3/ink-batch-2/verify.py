"""Check attempt 2 against attempt 1 (../ink-batch): what changed and what held, the independent
factory rebuild, the expression sweep, colour, and a second Bevy capture of the rebuilt export.

    python3 verify.py REBUILD_DIR SECOND_CAPTURE_DIR > replay-check.json
"""
import argparse
from io import BytesIO
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
BATCH = HERE.parent/'ink-batch'
sys.path.insert(0, str(BATCH))
sys.path.insert(0, str(HERE.parent/'eye-frame'))
from verify import image_bytes, primitives  # noqa: E402  (../ink-batch/verify.py)
from verify_fit import difference, inspect_meshes, read_json  # noqa: E402

NAME = 'own-cora-live'


def check(rebuild, second):
    old_doc, old_buf, old = primitives(BATCH/f'{NAME}.glb')
    new_doc, new_buf, new = primitives(HERE/f'{NAME}.glb')
    held, changed = [], {}
    for name in sorted(set(old) | set(new)):
        if name not in new or name not in old:
            changed[name] = 'removed' if name in old else 'added'
            continue
        diff = sorted(k for k in set(old[name][1]) | set(new[name][1]) if old[name][1].get(k) != new[name][1].get(k))
        if diff or old[name][0] != new[name][0]:
            changed[name] = diff + (['material'] if old[name][0] != new[name][0] else [])
        else:
            held.append(name)
    # The brows' carrier: every vertex attribute and morph target the same bytes; the exporter
    # orders triangles across the whole face mesh, so only the order of its (same) triangles
    # may move.
    brow_order_only = changed.get('Cora_BrowInk_EYE') == ['indices']
    if brow_order_only:
        tri = lambda arrays: {tuple(np.roll(t, -int(np.argmin(t)))) for t in np.frombuffer(arrays['indices'], np.uint16).reshape(-1, 3)}
        assert tri(old['Cora_BrowInk_EYE'][1]) == tri(new['Cora_BrowInk_EYE'][1])
        changed['Cora_BrowInk_EYE'] = 'triangle order only (same triangles and winding)'
    assert set(changed) - {'Cora_BrowInk_EYE'} == {'Cora_JawInk_SKIN', 'Cora_NoseInk_SKIN', 'Cora_LidInk_EYE', 'M00_000_00_FaceEyeline_00_FACE'}, changed
    assert ('Cora_BrowInk_EYE' in held or brow_order_only) and 'M00_000_00_Body_00_SKIN' in held
    images = {im['name']: 'same' if image_bytes(old_doc, old_buf, im['name']) == image_bytes(new_doc, new_buf, im['name']) else 'changed'
              for im in old_doc['images']}
    assert [k for k, v in images.items() if v == 'changed'] == ['cora.atlas']
    a = np.asarray(Image.open(BytesIO(image_bytes(old_doc, old_buf, 'cora.atlas'))).convert('RGB')).astype(int)
    b = np.asarray(Image.open(BytesIO(image_bytes(new_doc, new_buf, 'cora.atlas'))).convert('RGB')).astype(int)
    ys, xs = np.nonzero(np.any(a != b, -1))
    atlas = dict(changed_texels=int(len(xs)), bounds_xy=[int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())])
    # The passed strokes' texels in the eyes map: every attempt-1 brow and lower-lid stroke.
    m1 = np.asarray(Image.open(BATCH/f'{NAME}.eyes.ink.png').convert('RGB'))
    m2 = np.asarray(Image.open(HERE/f'{NAME}.eyes.ink.png').convert('RGB'))
    s1 = json.loads((BATCH/'maps/eyes.strokes.json').read_text())
    s2 = json.loads((HERE/'maps/eyes.strokes.json').read_text())
    rng = json.loads((HERE/'fit-report.json').read_text())['maps']['eyes']['range_uv']
    kept = {}
    for i, st in enumerate(s1['strokes']):
        P = np.array(st['points'])
        if not any(np.array_equal(P, np.array(q['points'])) for q in s2['strokes']):
            continue
        x0, y0 = np.floor((P[:, :2].min(0) - rng) * 2048).astype(int).clip(0)
        x1, y1 = np.ceil((P[:, :2].max(0) + rng) * 2048).astype(int)
        kept[i] = int(np.any(m1[y0:y1, x0:x1] != m2[y0:y1, x0:x1], -1).sum())
    assert len(kept) == 4 and not any(kept.values())
    sidecars = {s: (HERE/f'{NAME}.{s}').read_bytes() == (BATCH/f'{NAME}.{s}').read_bytes() for s in ('hair.png', 'calibration.json', 'face.png')}
    assert all(sidecars.values())
    _, volume = inspect_meshes(HERE/f'{NAME}.glb')
    assert volume == read_json(BATCH/'replay-check.json')['volume']
    artifacts = {}
    for suffix in ('glb', 'face.png', 'hair.png', 'calibration.json', 'eyes.ink.png'):
        data = (HERE/f'{NAME}.{suffix}').read_bytes()
        assert data == (rebuild/f'{NAME}.{suffix}').read_bytes(), suffix
        artifacts[f'{NAME}.{suffix}'] = hashlib.sha256(data).hexdigest()
    assert not (rebuild/f'{NAME}.skin.ink.png').exists()
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
        assert audits[-1]['stage'] == 'item4-5-expression-sweep' and not any(r['failures'] for r in audits)
    report = read_json(HERE/'calibration-report.json')
    assert report['passed'] and not report['audit']['errors'] and not report['audit']['warnings']
    cloth = read_json(HERE/'cloth.json')
    assert cloth['passed'] and cloth == read_json(BATCH/'cloth.json')
    checks = {(p['shot'], p['patch']) for p in report['patches'] + cloth['patches']}
    assert len(checks) == 20
    before = read_json(BATCH/'calibration-report.json')
    moved = {f"{p['patch']} / {p['shot']}": [n - o for n, o in zip(p['measured'], q['measured'])]
             for p in report['patches'] for q in before['patches'] if (p['patch'], p['shot']) == (q['patch'], q['shot'])}
    second_report = read_json(second/'report.json')
    stills = {k: difference(HERE/'stills'/Path(v).name, Path(second_report['shots'][k])) for k, v in report['shots'].items()}
    assert len(stills) == 17 and not any(stills.values())
    rear = {k: difference(HERE/'stills'/Path(report['shots'][k]).name, BATCH/'stills'/Path(before['shots'][k]).name)
            for k in ('near_180', 'middle_180', '180:8:0.36:0.88', '180:8:0.75:0.68')}
    return dict(changed_against_attempt_1=changed, held_primitives=held, embedded_images=images, atlas_change=atlas,
                kept_stroke_texels_changed=kept, sidecars_same_as_attempt_1=sidecars, volume=volume,
                triangles=counts['triangles'], factory_artifacts_sha256=artifacts,
                factory_expression_changed_pixels=factory_frames, expression_changed_pixels=keys,
                neutral_return_changed_pixels=neutral, colour_checks=len(checks),
                colour_patch_change_since_attempt_1=moved, second_capture_changed_pixels=stills,
                rear_frames_changed_pixels_vs_attempt_1=rear)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('rebuild', type=Path)
    p.add_argument('second', type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.rebuild, a.second), indent=2))
