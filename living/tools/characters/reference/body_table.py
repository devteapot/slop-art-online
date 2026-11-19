"""Bodies measured by body.py, side by side: one row a measure, one column a figure.

    python3 living/tools/characters/reference/body_table.py NAME=MEASURE.json ... [--markdown]

Lengths are percent of the figure's height unless the row says H (heads: chin to top).
"""
import json, sys

cols = [a.split('=', 1) for a in sys.argv[1:] if '=' in a]
data = [(n, json.load(open(p))) for n, p in cols]
pc = lambda v, m: f"{v / m['height'] * 100:.1f}"
ROWS = [
    ('heads tall', lambda m: f"{m['heads']:.2f}"),
    ('shoulders, between the joints', lambda m: pc(m['widths']['shoulder_joints'], m)),
    ('shoulders, arms hanging', lambda m: pc(m['widths']['shoulders_hanging'], m)),
    ('  the same in head widths', lambda m: f"{m['widths']['shoulders_hanging'] / m['head_width']:.2f}"),
    ('shoulder slope, degrees', lambda m: f"{m['shoulders']['slope_degrees']:.1f}"),
    ('shoulder top below the chin, H', lambda m: f"{m['shoulders']['top_below_chin'] / m['H']:.2f}"),
    ('under the arms: width', lambda m: pc(m['widths']['under_arms'], m)),
    ('bust: width', lambda m: pc(m['widths']['bust'], m)),
    ('bust: depth', lambda m: pc(m['depths']['bust'], m)),
    ('bust before the waist\'s front', lambda m: pc(m['depths']['bust_before_waist'], m)),
    ('waist: width', lambda m: pc(m['widths']['waist'], m)),
    ('waist: depth', lambda m: pc(m['depths']['waist'], m)),
    ('waist: height', lambda m: pc(m['heights']['waist'], m)),
    ('hips: width', lambda m: pc(m['widths']['hip'], m)),
    ('hips: depth', lambda m: pc(m['depths']['hip'], m)),
    ('hips: height of the widest', lambda m: pc(m['heights']['hip'], m)),
    ('seat behind the waist\'s back', lambda m: pc(m['depths']['seat_behind_waist'], m)),
    ('waist / hips', lambda m: f"{m['widths']['waist'] / m['widths']['hip']:.2f}"),
    ('shoulders hanging / hips', lambda m: f"{m['widths']['shoulders_hanging'] / m['widths']['hip']:.2f}"),
    ('leg: hip joint above the floor', lambda m: pc(m['limbs']['leg'], m)),
    ('leg: inseam (the crotch)', lambda m: pc(m['limbs']['inseam'], m)),
    ('knee joint', lambda m: pc(m['heights']['knee_joint'], m)),
    ('torso: crotch to the neck joint', lambda m: pc(m['limbs']['torso'], m)),
    ('leg / torso', lambda m: f"{m['limbs']['inseam'] / m['limbs']['torso']:.2f}"),
    ('arm: shoulder joint to wrist', lambda m: pc(m['limbs']['arm'], m)),
    ('arm to the fingertip', lambda m: pc(m['limbs']['arm_to_tip'], m)),
    ('hand: length, H', lambda m: f"{m['hands']['length'] / m['H']:.2f}"),
    ('hand: length', lambda m: pc(m['hands']['length'], m)),
    ('hand: palm / length', lambda m: f"{m['hands']['palm'] / m['hands']['length']:.2f}" if m['hands']['palm'] else '-'),
    ('hand: breadth, H', lambda m: f"{m['hands']['breadth'] / m['H']:.2f}" if m['hands']['breadth'] else '-'),
    ('upper arm: thickness', lambda m: pc(m['limbs']['upper_arm_thick'][0], m)),
    ('thigh: width', lambda m: pc(m['limbs']['thigh'][0], m)),
    ('calf: width', lambda m: pc(m['limbs']['calf'][0], m)),
    ('ankle: width', lambda m: pc(m['limbs']['ankle'][0], m)),
    ('neck: width', lambda m: pc(m['widths']['neck'], m)),
]
w = max(len(r[0]) for r in ROWS)
if '--markdown' in sys.argv:
    print('| | ' + ' | '.join(n for n, _ in data) + ' |')
    print('|---|' + '---|' * len(data))
    for name, f in ROWS:
        print(f"| {name.strip()} | " + ' | '.join(f(m) for _, m in data) + ' |')
else:
    print(' ' * w + ''.join(f"{n[:11]:>12s}" for n, _ in data))
    for name, f in ROWS:
        print(f"{name:{w}s}" + ''.join(f"{f(m):>12s}" for _, m in data))
