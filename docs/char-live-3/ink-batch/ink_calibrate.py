#!/usr/bin/env python3
"""Calibrate every ink's colour at a close shot, floor-relative (docs/HANDMADE_INK.md,
"Calibration, per slot"), where the strokes cover whole pixels.

    python3 ink_calibrate.py view/own-cora-live.glb TARGETS.json OUT --binary BIN [--apply]

For each inked material: one render of a copy without that ink finds its pixels (the frame
difference); the patch is the most deeply covered pixel; its reference is the surface beside
the stroke (`ref_offset` pixels away, the first pixel 4 px clear of all ink). A copy with every
ink black gives the floor. The target per linear channel is
floor + drawing_ink / drawing_ref x (measured_ref - floor), with min5 samples for inks and 9 x 9
medians for references, in the shot and in the drawing. The suggestion scales each ink colour
by target / measured. Generalises: only TARGETS.json is per character.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO/'living/tools/characters'), str(REPO/'living/tools')]
import calibrate as C  # noqa: E402
from merge_primitives import write_glb  # noqa: E402


def copy_with(glb, suffix, edit):
    j, binary = C.read_glb(C.ASSETS/glb)
    for m in j['materials']:
        ms = m.get('extras', {}).get('slop') or {}
        if isinstance(ms.get('ink'), dict):
            edit(m, ms)
    stem = glb[:-4]
    out = stem + suffix + '.glb'
    write_glb(C.ASSETS/out, j, bytearray(binary))
    for f in sorted((C.ASSETS/stem).parent.glob(Path(stem).name + '.*')):
        side = f.name[len(Path(stem).name):]
        if side.endswith(('.png', '.ktx2', '.json')) and side != '.glb':
            shutil.copyfile(f, C.ASSETS/(stem + suffix + side))
    return out


def remove(out):
    stem = out[:-4]
    for f in (C.ASSETS/stem).parent.glob(Path(stem).name + '.*'):
        f.unlink()


def shots_of(glb, binary, out, shots):
    got = C.run_frame(glb, binary, out, shots)
    from PIL import Image
    return {s: np.asarray(Image.open(got[s.replace('@', '_')]).convert('RGB'), float) for s in shots}


def lum(a):
    return a @ np.array([.2126, .7152, .0722])


def deepest(mask):
    """The pixel farthest inside a mask (city-block erosion count)."""
    depth = np.zeros(mask.shape, int)
    cur = mask.copy()
    while cur.any():
        depth += cur
        nxt = cur.copy()
        nxt[1:] &= cur[:-1]
        nxt[:-1] &= cur[1:]
        nxt[:, 1:] &= cur[:, :-1]
        nxt[:, :-1] &= cur[:, 1:]
        cur = nxt
    y, x = np.unravel_index(np.argmax(depth), depth.shape)
    return int(x), int(y), int(depth.max())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glb')
    ap.add_argument('targets')
    ap.add_argument('out')
    ap.add_argument('--binary', required=True)
    a = ap.parse_args()
    T = json.loads(Path(a.targets).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    drawing = C.read_png(REPO/T['drawing'])
    shots = T['shots']
    j, _ = C.read_glb(C.ASSETS/a.glb)
    inks = {m['name']: m['extras']['slop']['ink']['color'] for m in j['materials']
            if isinstance((m.get('extras', {}).get('slop') or {}).get('ink'), dict)}
    base = shots_of(a.glb, a.binary, out/'base', shots)
    floor_glb = copy_with(a.glb, '-inkfloor', lambda m, ms: ms['ink'].__setitem__('color', [0, 0, 0]))
    try:
        floor = shots_of(floor_glb, a.binary, out/'floor', shots)
    finally:
        remove(floor_glb)
    plain_glb = copy_with(a.glb, '-noink', lambda m, ms: ms.pop('ink'))
    try:
        plain = shots_of(plain_glb, a.binary, out/'noink', shots)
    finally:
        remove(plain_glb)
    rows, suggest = [], {}
    for name, spec in T['inks'].items():
        if name not in inks:
            continue
        shot = spec['shot']
        without = copy_with(a.glb, '-no' + name.lower(), lambda m, ms, n=name: ms.pop('ink') if m['name'] == n else None)
        try:
            img = shots_of(without, a.binary, out/('no-' + name), [shot])[shot]
        finally:
            remove(without)
        diff = np.abs(base[shot] - img).max(-1) > 8
        lo, hi = spec.get('box', [0, 0, diff.shape[1], diff.shape[0]])[:2], spec.get('box', [0, 0, diff.shape[1], diff.shape[0]])[2:]
        box = np.zeros_like(diff)
        box[lo[1]:hi[1], lo[0]:hi[0]] = True
        x, y, depth = deepest(diff & box)
        any_ink = np.abs(base[shot] - plain[shot]).max(-1) > 4
        dx, dy = spec['ref_offset']
        rx, ry = x, y
        for k in range(1, 200):
            rx, ry = int(round(x + dx * k / 10)), int(round(y + dy * k / 10))
            if not any_ink[max(0, ry - 4):ry + 5, max(0, rx - 4):rx + 5].any():
                break
        tag = shot.replace(':', '_')
        img_base = C.read_png(next((out/'base'/'stills'/Path(a.glb).stem).glob(f'*-{tag}.png')))
        img_floor = C.read_png(next((out/'floor'/'stills'/(Path(a.glb).stem + '-inkfloor')).glob(f'*-{tag}.png')))
        got = C.patch_min(img_base, x, y)
        fl = C.patch_min(img_floor, x, y)
        ref = C.patch_median(img_base, rx, ry)
        d_ink = C.patch_min(drawing, *map(int, map(round, spec['drawing'])))
        d_ref = C.patch_median(drawing, *map(int, map(round, spec['ref_drawing'])))
        target = [C.to_srgb(C.to_linear(f) + C.to_linear(di) / max(C.to_linear(dr), 1e-4) * (C.to_linear(mr) - C.to_linear(f)))
                  for f, di, dr, mr in zip(fl, d_ink, d_ref, ref)]
        cur = inks[name]
        new = [C.to_srgb(min(1., C.to_linear(c) * C.to_linear(t) / max(C.to_linear(g), 1e-4))) for c, t, g in zip(cur, target, got)]
        rows.append(dict(material=name, shot=shot, patch=[x, y], depth_px=depth, reference=[rx, ry], measured=got,
                         floor=fl, reference_measured=ref, drawing_ink=d_ink, drawing_ref=d_ref, target=target,
                         delta=[g - t for g, t in zip(got, target)], color=cur, suggested=new))
        suggest[name] = new
    (out/'ink-calibration.json').write_text(json.dumps(dict(shots=shots, rows=rows, suggested=suggest), indent=2) + '\n')
    for r in rows:
        print(f"{r['material']:20s} {r['shot']:16s} at {r['patch']} (depth {r['depth_px']}) measured {r['measured']} target {r['target']} floor {r['floor']} ref {r['reference_measured']} -> suggest {r['suggested']} (now {r['color']})")


if __name__ == '__main__':
    main()
