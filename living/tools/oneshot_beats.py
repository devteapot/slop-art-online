#!/usr/bin/env python3
"""When a one-shot clip moves: its start, its peak (a release or a blow) and its settle.

    python3 living/tools/oneshot_beats.py FILE.glb CLIP [CLIP ...] [--json OUT]

Samples the baked take (marker_check.py's reader, no Blender) at 60 Hz: each hand's position
relative to the hips, and its speed. The peak is the faster hand's highest speed; the start is
the last time before it under 20% of the peak, and the settle the first time after it under 15%.
The game times a move's clip so its peak lands at the rules' windup (`combat.rs`).
"""
import json, math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from marker_check import Glb, world

def beats(glb, name):
    anim = glb.animation(name)
    if anim is None:
        return None
    end = max(max(ch[p][0][-1] for p in ch) for ch in anim.values())
    hips = glb.names["J_Bip_C_Hips"]
    hands = [glb.names["J_Bip_L_Hand"], glb.names["J_Bip_R_Hand"]]
    n = int(end * 60) + 1
    pts = []
    for k in range(n):
        t = k / 60
        h = world(glb, anim, hips, t)
        pts.append([h.inverse_apply(world(glb, anim, x, t).t) for x in hands])
    sp = [max(math.dist(pts[k][i], pts[k - 1][i]) * 60 for i in range(2)) for k in range(1, n)]
    peak_k = max(range(len(sp)), key=lambda k: sp[k])
    peak = sp[peak_k]
    start = next((k for k in range(peak_k, -1, -1) if sp[k] < 0.2 * peak), 0)
    settle = next((k for k in range(peak_k, len(sp)) if sp[k] < 0.15 * peak), len(sp) - 1)
    return {"length_s": round(end, 3), "start_s": round((start + 1) / 60, 3), "peak_s": round((peak_k + 1) / 60, 3), "settle_s": round((settle + 1) / 60, 3), "peak_mps": round(peak, 2)}

def main():
    args = sys.argv[1:]
    out = None
    if "--json" in args:
        i = args.index("--json"); out = args[i + 1]; args = args[:i] + args[i + 2:]
    glb = Glb(args[0])
    res = {c: beats(glb, c) for c in args[1:]}
    for c, b in res.items():
        print(c, b)
    if out:
        json.dump(res, open(out, "w"), indent=1)

main()
