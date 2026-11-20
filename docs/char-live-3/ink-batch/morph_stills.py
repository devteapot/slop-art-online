#!/usr/bin/env python3
"""Bevy stills of the face held at each morph target, to see the ink ride the lids, brows and jaw.

    python3 morph_stills.py view/own-cora-live.glb OUT --binary BIN [--shot S ...] [--keys K,...]

Each key is a temporary copy whose face mesh's default `weights` hold that target at 1 (Bevy
takes them as the initial MorphWeights), rendered by the asset view at the given shots, and a
`neutral` copy with all weights 0. The copies are removed afterwards.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO/'living/tools/characters'), str(REPO/'living/tools')]
import calibrate as C  # noqa: E402
from merge_primitives import write_glb  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('glb')
    ap.add_argument('out')
    ap.add_argument('--binary', required=True)
    ap.add_argument('--shot', action='append', default=[])
    ap.add_argument('--keys')
    a = ap.parse_args()
    shots = a.shot or ['0:8:0.16:0.91', '-35:8:0.16:0.91']
    j, binary = C.read_glb(C.ASSETS/a.glb)
    mesh = next(m for m in j['meshes'] if 'targetNames' in m.get('extras', {}))
    names = mesh['extras']['targetNames']
    wanted = ['neutral'] + (a.keys.split(',') if a.keys else names)
    stem = a.glb[:-4]
    out = Path(a.out)
    index = {}
    for k in wanted:
        mesh['weights'] = [1. if n == k else 0. for n in names]
        tag = '-m' + ('neutral' if k == 'neutral' else k.replace('Fcl_', '').lower())
        copy = stem + tag + '.glb'
        write_glb(C.ASSETS/copy, j, bytearray(binary))
        sides = []
        for f in sorted((C.ASSETS/stem).parent.glob(Path(stem).name + '.*')):
            side = f.name[len(Path(stem).name):]
            if side.endswith(('.png', '.ktx2')):
                shutil.copyfile(f, C.ASSETS/(stem + tag + side))
                sides.append(C.ASSETS/(stem + tag + side))
        try:
            got = C.run_frame(copy, a.binary, out/k, shots)
            index[k] = {s: str(got[s.replace('@', '_')].relative_to(out)) for s in shots if s.replace('@', '_') in got}
        finally:
            (C.ASSETS/copy).unlink()
            for f in sides:
                f.unlink()
        print(k, index[k], flush=True)
    (out/'index.json').write_text(json.dumps(index, indent=2) + '\n')


if __name__ == '__main__':
    main()
