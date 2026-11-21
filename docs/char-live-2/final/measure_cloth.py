"""Measure the eight registered garment windows, including the full-body shot."""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'living/tools/characters'))
from calibrate import patch_median, read_png


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path, help='daylight calibration report')
    parser.add_argument('--targets', type=Path, default=HERE/'own-cora-live.calibration.json')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    targets = json.loads(args.targets.read_text())
    images = {}
    results = []
    for name, patch in targets['patches'].items():
        if 'drawing_file' not in patch:
            continue
        shot = 'portrait' if 'portrait' in patch else targets['cloth_full_body_shot']
        if shot not in images:
            images[shot] = read_png(args.report.parent / report['shots'][shot])
        xy = patch[shot]
        measured = patch_median(images[shot], *xy)
        delta = [a-b for a, b in zip(measured, patch['target'])]
        results.append(dict(patch=name, shot=shot, window=xy, target=patch['target'],
                            measured=measured, delta=delta, floor=patch['black_floor'],
                            passed=max(map(abs, delta)) <= patch['tolerance']))
    passed = bool(results) and all(row['passed'] for row in results)
    output = json.dumps(dict(passed=passed, patches=results), indent=2) + '\n'
    if args.out:
        args.out.write_text(output)
    else:
        print(output, end='')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
