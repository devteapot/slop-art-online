#!/usr/bin/env python3
"""Pair a fast-replay's two arms by input and compare them (docs/FAST_LANE_FRAME.md §3).

usage: battle_frame_pairs.py FIRST.jsonl BALANCED.jsonl
Per input, over every reply (not only patches): kept (a keep reply, or a patch keeping the fixture's
fight whole), pressed (a patch with an explicit press or the press way), retreat (a patch with flee or
back_off), unconditioned retreat, retreat ahead of the first attack, attack, unusable or failed."""
import json, sys
from math import comb
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from battle_frame_classify import classify

def flags(r):
    rep = r.get('replayed')
    if rep is None:
        return {'failed': True}
    c = classify(rep)
    p = c['kind'] == 'patch'
    return {'failed': False, 'keep_reply': c['kind'] == 'keep', 'patch': p, 'switch_or_routine': c['kind'] in ('switch', 'routine'),
            'unusable': c['kind'] == 'unusable',
            'kept': c['kind'] == 'keep' or (p and c['fight_kept']), 'fight_kept_patch': p and c['fight_kept'],
            'pressed': p and (c['press'] or c['way_press']), 'retreat': p and c['retreat'], 'uncond_retreat': p and c['uncond_retreat'],
            'retreat_ahead': p and c['retreat_ahead'], 'attack': p and c['attack'], 'copied_numbers': p and c['copied_numbers'],
            'way_room': p and c['way_room'], 'way_break': p and c['way_break'], 'way_timing': p and c['way_timing'], 'way_target': p and c['way_target']}

def sign_p(b, c):
    """Two-sided exact sign test on the discordant pairs (McNemar exact)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)

key = lambda r: (r['run'], r['actor'], r['idx'])
A = {key(r): flags(r) for r in map(json.loads, open(sys.argv[1]))}
B = {key(r): flags(r) for r in map(json.loads, open(sys.argv[2]))}
both = sorted(set(A) & set(B))
print(f"paired inputs: {len(both)}")
print(f"{'measure (share of all replies)':34} {'first':>7} {'balanced':>9} {'only first':>11} {'only bal.':>10} {'p (sign)':>9}")
for m in ('keep_reply', 'patch', 'switch_or_routine', 'unusable', 'failed', 'kept', 'fight_kept_patch', 'pressed', 'retreat', 'uncond_retreat',
          'retreat_ahead', 'attack', 'way_timing', 'way_target', 'way_room', 'way_break', 'copied_numbers'):
    a = [A[k].get(m, False) for k in both]; b = [B[k].get(m, False) for k in both]
    only_a = sum(x and not y for x, y in zip(a, b)); only_b = sum(y and not x for x, y in zip(a, b))
    print(f"{m:34} {100*sum(a)/len(both):6.1f}% {100*sum(b)/len(both):8.1f}% {only_a:11d} {only_b:10d} {sign_p(only_a, only_b):9.3f}")
