#!/usr/bin/env python3
"""The prompt-length effect of heed on recorded think prompts (docs/ATTENTION_E5.md §1). Read-only.

  heed_e5_prompts.py --battle DIR... --town DIR... [--json OUT]

For every think request in each run's journal (battle: a `battle_diag.py` verify folder with
`combat-samples.jsonl.gz`; town: a trials instance with `bodies.jsonl` of every creature), the
scene as the mind received it (today: the 14 nearest in sight under `creatures`) and the prompt's
logged `prompt_tokens` are read. Who is in sight is the scene's own list where it holds fewer than
14 (the authority's sight, cover and walls included); at the cap, the recorded positions within the
scene's `sight` (distance-only, an upper bound where cover blocks). The scene under `heed_on`:
  - individuals listed: min(in sight, capacity), capacity from the formula on the subject's own
    health, energy and stamina in its scene (person base 10, or 14 with `--base 14`, ceiling 16;
    `--fixed N` for a fixed capacity); each costs that scene's own mean creature entry;
  - the rest as `throngs` lines, one per (8-way direction, distance band: under 8 m, under 20 m,
    farther) group, each the measured mean of the authority's line (heed scene `heed-scene-on.json`:
    about 140 characters);
and converted to tokens at the prompt's own characters per token (user and system text over its
`prompt_tokens`). Reports median and p95 before and after, by scene, with the in-sight counts.
"""
import argparse
import gzip
import json
import math
import os
import statistics
import sys
from bisect import bisect_right
from pathlib import Path

SCENE_HEAD = "# What you perceive right now\n"
THRONG_LINE = 140  # characters of one `throngs` entry, measured on the authority's scene (verify-core heed)
DIRS = 8


def pct(v, q):
    v = sorted(v)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def capacity(you, base=10.0, fixed=None, ceiling=16.0):
    if fixed is not None:
        return int(min(fixed, ceiling))
    c = base
    e = float(you.get("energy", 80.0) or 80.0)
    if e < 15:
        c *= 0.6
    elif e < 35:
        c *= 0.8
    h = float(you.get("health", 100.0) or 100.0) / 100.0
    if h < 0.25:
        c *= 0.6
    elif h < 0.5:
        c *= 0.8
    if float(you.get("stamina", 60.0) if you.get("stamina") is not None else 60.0) < 10:
        c *= 0.85
    return int(max(1.0, math.floor(min(c, ceiling))))


def think_entries(d):
    jd = Path(d) / "journal"
    sysdir = jd / "system"
    sys_len = {}
    for f in sorted(jd.glob("*.jsonl")):
        for line in open(f):
            e = json.loads(line)
            if e.get("purpose") != "think" or e.get("error") or not e.get("prompt_tokens"):
                continue
            msgs = e.get("request", {}).get("messages", [])
            if not msgs:
                continue
            user = msgs[-1].get("content", "")
            i = user.find(SCENE_HEAD)
            if i < 0:
                continue
            j = user.find("\n", i + len(SCENE_HEAD))
            try:
                scene = json.loads(user[i + len(SCENE_HEAD):j])
            except ValueError:
                continue
            if not isinstance(scene.get("you"), dict) or "at" not in scene["you"]:
                continue
            sys_chars = 0
            for m in msgs[:-1]:
                if "content" in m:
                    sys_chars += len(m["content"])
                elif "content_ref" in m:
                    ref = m["content_ref"]
                    if ref not in sys_len:
                        p = jd / ref
                        sys_len[ref] = len(p.read_text()) if p.exists() else 0
                    sys_chars += sys_len[ref]
            yield e["at_ms"], scene, len(user) + sys_chars, e["prompt_tokens"]


class BattlePos:
    def __init__(self, d):
        self.samples = []
        for line in gzip.open(os.path.join(d, "combat-samples.jsonl.gz"), "rt"):
            e = json.loads(line)
            self.samples.append((e["at_ms"], {b["id"]: b for b in e["bodies"]}))
        self.times = [t for t, _ in self.samples]

    def at(self, t):
        i = bisect_right(self.times, t) - 1
        if i < 0:
            return {}
        out = {}
        for bid, b in self.samples[i][1].items():
            nxt = b["next_ms"] if b["next_ms"] < 1e18 else t
            dt = max(0, min(t, nxt) - b["t_ms"]) / 1000
            out[bid] = (b["x"] + b["vx"] * dt, b["y"] + b["vy"] * dt)
        return out


class TownPos:
    def __init__(self, d):
        self.rows = [json.loads(l) for l in open(os.path.join(d, "bodies.jsonl"))]
        self.times = [r["ms"] for r in self.rows]

    def at(self, t):
        i = max(0, min(len(self.rows) - 1, bisect_right(self.times, t) - 1))
        r = self.rows[i]
        dead = r.get("dead", {})
        return {int(k): (v[0], v[1]) for k, v in r["b"].items() if k not in dead}


def octant(dx, dy):
    return int(((math.atan2(dy, dx) + math.pi) / (2 * math.pi) * DIRS + 0.5)) % DIRS


def band(d):
    return 0 if d < 8 else 1 if d < 20 else 2


def measure(kind, d, a):
    pos = BattlePos(d) if kind == "battle" else TownPos(d)
    out = []
    for at_ms, scene, chars, tokens in think_entries(d):
        you = scene["you"]
        me_id = int(you["id"])
        here = pos.at(at_ms)
        if me_id not in here:
            continue
        mx, my = here[me_id]
        sight = float(scene.get("time", {}).get("sight", 11.0))
        others = [(math.hypot(x - mx, y - my), x - mx, y - my) for i, (x, y) in here.items() if i != me_id]
        seen = sorted(o for o in others if o[0] <= sight)
        creatures = scene.get("creatures", [])
        listed = len(creatures)
        entry = statistics.mean(len(json.dumps(c, separators=(",", ":"))) + 1 for c in creatures) if creatures else 0.0
        if not creatures:
            entry = 150.0
        # The authority's own sight (cover, walls, gaze) decides who is in sight: under the cap the
        # scene lists exactly them; at the cap (14 listed) the rest are counted from the recorded
        # positions at the scene's distance (distance-only: an upper bound where cover blocks).
        n_sight = listed if listed < 14 else max(listed, len(seen))
        seen = seen[:n_sight] if n_sight <= len(seen) else seen
        cap = capacity(you, a.base, a.fixed, a.ceiling)
        after_listed = min(n_sight, cap)
        throng = seen[after_listed:n_sight]
        groups = {(octant(dx, dy), band(dd)) for dd, dx, dy in throng}
        delta = (after_listed - listed) * entry + len(groups) * THRONG_LINE
        cpt = chars / tokens
        out.append({"scene": kind, "in_sight": n_sight, "listed_before": listed, "listed_after": after_listed, "capacity": cap,
                    "throng": len(throng), "throng_lines": len(groups), "tokens_before": tokens, "tokens_after": tokens + delta / cpt,
                    "delta_tokens": delta / cpt, "chars_per_token": round(cpt, 3)})
    return out


def summary(rows):
    f = lambda k, q: round(pct([r[k] for r in rows], q), 1)
    return {"n": len(rows), "in_sight": {"p50": f("in_sight", .5), "p95": f("in_sight", .95)},
            "listed_before": {"p50": f("listed_before", .5), "p95": f("listed_before", .95)},
            "listed_after": {"p50": f("listed_after", .5), "p95": f("listed_after", .95)},
            "throng_lines": {"p50": f("throng_lines", .5), "p95": f("throng_lines", .95)},
            "tokens_before": {"p50": f("tokens_before", .5), "p95": f("tokens_before", .95)},
            "tokens_after": {"p50": f("tokens_after", .5), "p95": f("tokens_after", .95)},
            "delta_tokens": {"p50": f("delta_tokens", .5), "p95": f("delta_tokens", .95), "p5": f("delta_tokens", .05)},
            "share_more_than_14_in_sight": round(sum(1 for r in rows if r["in_sight"] > 14) / len(rows), 3)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--battle", nargs="*", default=[])
    ap.add_argument("--town", nargs="*", default=[])
    ap.add_argument("--base", type=float, default=10.0)
    ap.add_argument("--fixed", type=float)
    ap.add_argument("--ceiling", type=float, default=16.0)
    ap.add_argument("--json")
    a = ap.parse_args()
    res = {}
    for kind, dirs in (("battle", a.battle), ("town", a.town)):
        rows = [r for d in dirs for r in measure(kind, d, a)]
        if rows:
            res[kind] = summary(rows)
            print(kind, json.dumps(res[kind]))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
