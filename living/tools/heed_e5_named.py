#!/usr/bin/env python3
"""People a real mind's think reply names in a recorded battle (docs/ATTENTION_E5.md §3): by id (`#id`) or `say.to`,
ranked by distance among those in sight (positions at the request, distance-only at the scene's sight).
Read-only. Usage: heed_e5_named.py ROOT (ROOT/x/.local/living/verify/minds-atb1-{off,on}-* from the act-trial archive)."""
import json, math, re, sys
from pathlib import Path
sys.path.insert(0, "living/tools")
import heed_e5_prompts as hp
S = sys.argv[1]
tot = {"thinks": 0, "named_in_sight": 0, "beyond8": 0, "beyond10": 0, "beyond14": 0, "thinks_naming": 0, "in_sight_gt14": 0, "minds": set(), "span_ms": [1e18, 0]}
for run in ("minds-atb1-off-055246", "minds-atb1-on-060222"):
    d = f"{S}/x/.local/living/verify/{run}"
    pos = hp.BattlePos(d)
    for f in sorted(Path(d, "journal").glob("*.jsonl")):
        for line in open(f):
            e = json.loads(line)
            if e.get("purpose") != "think" or e.get("error") or not e.get("reply"):
                continue
            msgs = e["request"]["messages"]; u = msgs[-1].get("content", "")
            i = u.find(hp.SCENE_HEAD)
            if i < 0: continue
            try:
                sc = json.loads(u[i+len(hp.SCENE_HEAD):u.find("\n", i+len(hp.SCENE_HEAD))])
                rep = json.loads(e["reply"])
            except ValueError:
                continue
            me = int(sc["you"]["id"]); here = pos.at(e["at_ms"])
            if me not in here: continue
            tot["thinks"] += 1; tot["minds"].add(me)
            tot["span_ms"][0] = min(tot["span_ms"][0], e["at_ms"]); tot["span_ms"][1] = max(tot["span_ms"][1], e["at_ms"])
            mx, my = here[me]; sight = float(sc["time"]["sight"])
            seen = sorted((math.hypot(x-mx, y-my), i2) for i2, (x, y) in here.items() if i2 != me and math.hypot(x-mx, y-my) <= sight)
            if len(seen) > 14: tot["in_sight_gt14"] += 1
            rank = {i2: k for k, (_, i2) in enumerate(seen)}
            text = json.dumps({k: rep.get(k) for k in ("thought", "intend", "say")})
            ids = {int(x) for x in re.findall(r"#(\d+)", text)}
            to = (rep.get("say") or {}).get("to") if isinstance(rep.get("say"), dict) else None
            if isinstance(to, int): ids.add(to)
            ids.discard(me)
            named = [rank[x] for x in ids if x in rank]
            if named: tot["thinks_naming"] += 1
            tot["named_in_sight"] += len(named)
            tot["beyond8"] += sum(1 for r in named if r >= 8)
            tot["beyond10"] += sum(1 for r in named if r >= 10)
            tot["beyond14"] += sum(1 for r in named if r >= 14)
tot["minds"] = len(tot["minds"]); tot["span_min"] = round((tot["span_ms"][1]-tot["span_ms"][0])/60000/2, 1); del tot["span_ms"]
print(json.dumps(tot))
