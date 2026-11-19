#!/usr/bin/env python3
"""Count the tile classes a real client received in a `terrain_chunk` subscription saved by
`drive.py --query "SELECT * FROM terrain_chunk" --save NAME` (its `initial` event), and compare
them with the rules' own count of the land's hosted tiles when given (`--expect CLASS=N`).

    .agents/skills/verify-client/scripts/tile_classes.py .local/living/verify/<run>/NAME.jsonl --expect 8=4116 --expect 9=9153

Classes are living_rules::map::Terrain bytes: 0 grass, 1 forest, 2 water, 3 sand, 4 rock, 5 dirt,
6 road, 7 wall, 8 drop, 9 low. Writes NAME-classes.json beside the subscription."""
import argparse
import collections
import json
from pathlib import Path

NAMES = ['grass', 'forest', 'water', 'sand', 'rock', 'dirt', 'road', 'wall', 'drop', 'low']


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('jsonl', type=Path)
    ap.add_argument('--expect', action='append', default=[], help='CLASS=COUNT the rules give for the hosted land')
    a = ap.parse_args()
    initial = next(json.loads(line) for line in a.jsonl.open() if '"event":"initial"' in line.replace(' ', ''))
    rows = initial['tables']['terrain_chunk']
    counts = collections.Counter()
    for row in rows:
        data = row['tiles']
        data = bytes.fromhex(data.removeprefix('0x')) if isinstance(data, str) else bytes(data)
        counts.update(data)
    out = {'chunks': len(rows), 'classes': {f'{k} {NAMES[k] if k < len(NAMES) else "?"}': counts[k] for k in sorted(counts)}}
    bad = []
    for e in a.expect:
        k, n = map(int, e.split('='))
        out.setdefault('expected', {})[k] = n
        if counts[k] != n:
            bad.append(f'class {k}: received {counts[k]}, rules {n}')
    out['ok'] = not bad and all(k < len(NAMES) for k in counts)
    (a.jsonl.parent / (a.jsonl.stem + '-classes.json')).write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    for b in bad:
        print('FAIL', b)
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
