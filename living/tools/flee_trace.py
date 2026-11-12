#!/usr/bin/env python3
"""Trace a mind's decision to flee, from its reply to the body's path (docs/FRAMING.md, "Fled
toward the attacker"). Read-only.

  flee_trace.py RUN_DIR REPLY_AT_MS [--subject ID] [--foe ID] [--seconds S]

Prints: the reply's intend and thought; where the foe stood from the subject (compass, metres)
at the prompt and at the reply; the graph installed next (its flee / goto / movement nodes); the
subject's skill uses in the window; and its path: compass of its displacement, and the distance to
the foe, every 2 s.
"""
import argparse, bisect, json, math, os, re

DIRS = ["east", "southeast", "south", "southwest", "west", "northwest", "north", "northeast"]


def compass(a, b):
    # world y grows south (tiles), as the scene's `dir` does
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    return DIRS[int(round(ang / (math.pi / 4))) % 8]


def rows(p):
    with open(p) as f:
        for l in f:
            l = l.strip()
            if l:
                try:
                    yield json.loads(l)
                except ValueError:
                    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("at_ms", type=int)
    ap.add_argument("--subject", type=int)
    ap.add_argument("--foe", type=int, default=9)
    ap.add_argument("--seconds", type=float, default=12)
    a = ap.parse_args()
    cast = json.load(open(os.path.join(a.run, "cast.json")))
    subj = a.subject or cast["roles"]["subject"][0]["id"]
    name = cast["roles"]["subject"][0]["name"]
    pos = list(rows(os.path.join(a.run, "positions.jsonl")))
    pt = [p["ms"] for p in pos]

    def at(ms, who):
        i = min(len(pos) - 1, max(0, bisect.bisect_left(pt, ms)))
        return pos[i]["pos"].get(str(who))

    reply = None
    for e in rows(os.path.join(a.run, "journal", name.replace(" ", "_") + ".jsonl")):
        if e.get("purpose") == "think" and e.get("at_ms") == a.at_ms:
            reply = e
    v = json.loads(reply["reply"]) if reply else {}
    ask_ms = a.at_ms - (reply.get("latency_ms") or 0) - (reply.get("queue_wait_ms") or 0) if reply else a.at_ms
    print(f"== {os.path.basename(a.run.rstrip('/'))} reply at {a.at_ms} (asked {a.at_ms - ask_ms} ms before)")
    print("intend:", json.dumps(v.get("intend"))[:400])
    print("thought:", (v.get("thought") or "")[:300])
    for label, ms in (("prompt", ask_ms), ("reply", a.at_ms)):
        s, f = at(ms, subj), at(ms, a.foe)
        if s and f:
            print(f"{label}: foe #{a.foe} {compass(s, f)} of me, {math.dist(s[:2], f[:2]):.1f} m (me {s[0]:.1f},{s[1]:.1f}; foe {f[0]:.1f},{f[1]:.1f})")
    g = next((x for x in rows(os.path.join(a.run, "graphs.jsonl")) if x.get("id") == subj and (x.get("at_ms") or 0) >= a.at_ms), None)
    if g is None:
        t0 = pos[0]["ms"] - pos[0]["t"] * 1000
        g = next((x for x in rows(os.path.join(a.run, "graphs.jsonl")) if x.get("id") == subj and t0 + (x.get("t") or 0) * 1000 >= a.at_ms), None)
    if g:
        text = g.get("graph") or ""
        moves = re.findall(r'\{"do":\{"skill":"(flee|goto|back_off|keep_distance|close_in|follow|run)"[^}]*\}[^}]*\}', text)
        flee = re.findall(r'"skill":"(flee|goto|back_off|keep_distance)"[^{}]*?"target":(\{[^{}]*\}|"[^"]*")', text)
        print("installed next (t", g.get("t"), "):", flee[:6] or moves[:6] or text[:300])
    uses = [u for u in rows(os.path.join(a.run, "uses.jsonl")) if u.get("actor") == subj and a.at_ms <= u["at_ms"] <= a.at_ms + a.seconds * 1000]
    seen = []
    for u in uses:
        k = (u["skill"], u.get("target"))
        if k not in seen:
            seen.append(k)
    print("uses:", [(s_, t_) for s_, t_ in seen][:10])
    prev = at(a.at_ms, subj)
    for k in range(1, int(a.seconds // 2) + 1):
        ms = a.at_ms + k * 2000
        s, f = at(ms, subj), at(ms, a.foe)
        if not (s and f and prev):
            continue
        moved = math.dist(prev[:2], s[:2])
        print(f"  +{2 * k:>2}s: moved {moved:4.1f} m {compass(prev, s) if moved > 0.3 else '(still)':9} | foe {compass(s, f):9} {math.dist(s[:2], f[:2]):5.1f} m")
        prev = s


if __name__ == "__main__":
    main()
