#!/usr/bin/env python3
"""(docs/MIND_FEEDBACK.md, item 6) replay_wants.py <dir with moments.jsonl and new_sentence.txt> <.env> [N]
Replay recorded consolidation requests with the identity sentence as recorded (before) and as
changed on feedback-1 (after); classify whether the identity's goals/values take on a want for a
child, and whether its narrative names it. Key from .env (MISTRAL_API_KEY), never printed."""
import json, re, sys, urllib.request, concurrent.futures as cf
from pathlib import Path
S = Path(sys.argv[1]); ENV = Path(sys.argv[2]); N = int(sys.argv[3]) if len(sys.argv) > 3 else 4
OLD = "Identity (narrative, values, goals, traits 0-100, mood) changes only when experiences genuinely warrant it; otherwise identity is null."
NEW = Path(S / "new_sentence.txt").read_text().strip()
key = next(l.split("=", 1)[1].strip().strip('"') for l in ENV.read_text().splitlines() if l.startswith("MISTRAL_API_KEY="))
CHILD = re.compile(r"child|family of my own|a family|baby|offspring", re.I)
def call(req):
    r = urllib.request.Request("https://api.mistral.ai/v1/chat/completions", data=json.dumps(req).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=300) as f:
        return json.loads(f.read())
def classify(content):
    try: v = json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content or "", re.S)
        try: v = json.loads(m.group(0)) if m else {}
        except Exception: return {"parsed": False}
    idn = v.get("identity") if isinstance(v, dict) else None
    if not idn: return {"parsed": True, "identity": False}
    goals = " | ".join(map(str, idn.get("goals") or [])); vals = " | ".join(map(str, idn.get("values") or []))
    return {"parsed": True, "identity": True, "goal_or_value": bool(CHILD.search(goals + " | " + vals)), "narrative": bool(CHILD.search(str(idn.get("narrative", "")))),
            "goals": goals[:300], "values": vals[:200], "narrative_text": str(idn.get("narrative", ""))[:400]}
jobs = []
for l in open(S / "moments.jsonl"):
    d = json.loads(l)
    for arm in ("before", "after"):
        for k in range(N):
            req = json.loads(json.dumps(d["request"]))
            if arm == "after":
                assert OLD in req["messages"][0]["content"]
                req["messages"][0]["content"] = req["messages"][0]["content"].replace(OLD, NEW)
            jobs.append((d["src"], arm, k, req))
def run(j):
    src, arm, k, req = j
    try:
        r = call(req); c = r["choices"][0]["message"]["content"]
        if isinstance(c, list): c = "".join(p.get("text", "") for p in c if p.get("type") == "text")
        return {"src": src, "arm": arm, "k": k, "usage": r.get("usage"), **classify(c)}
    except Exception as e:
        return {"src": src, "arm": arm, "k": k, "error": str(e)[:200]}
with cf.ThreadPoolExecutor(10) as ex, open(S / "replays.jsonl", "w") as out:
    for res in ex.map(run, jobs):
        out.write(json.dumps(res) + "\n"); print(res["src"][:40], res["arm"], res.get("goal_or_value"), res.get("narrative"), res.get("error", ""), flush=True)
