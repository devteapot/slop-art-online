#!/usr/bin/env python3
"""Text snapshot of the living world: people, needs, activity, plan, mood, recent story.

Usage: living/tools/status.py [--db living] [--story 25]
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

STDB = str(Path(__file__).resolve().parents[2] / "living/tools/stdb")


def rows(db, q):
    out = subprocess.run([STDB, "sql", "-s", "local", db, q], capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "|" in l and not l.strip().startswith("-")]
    if not lines:
        return []
    head = [h.strip() for h in lines[0].split("|")]
    res = []
    for l in lines[1:]:
        vals = [v.strip() for v in l.split("|")]
        r = {}
        for h, v in zip(head, vals):
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            else:
                try:
                    v = float(v) if "." in v else int(v)
                except ValueError:
                    pass
            r[h] = v
        res.append(r)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="living")
    ap.add_argument("--story", type=int, default=25)
    a = ap.parse_args()
    now = time.time() * 1000
    w = rows(a.db, "SELECT * FROM world")[0]
    t = now - w["epoch_ms"] + w["day_ms"] * 7 / 24
    day, hour = int(t // w["day_ms"]) + 1, (t % w["day_ms"]) / w["day_ms"] * 24
    st = rows(a.db, "SELECT * FROM stats")
    st = st[0] if st else {}
    print(f"day {day} {int(hour):02d}:{int(hour % 1 * 60):02d}  people {st.get('alive_people')}  animals {st.get('alive_animals')}  deaths {st.get('deaths')}  ticks {st.get('ticks')}  max gap {st.get('max_tick_gap_ms')}ms")
    chars = {c["id"]: c for c in rows(a.db, "SELECT * FROM character WHERE kind = 'person'")}
    vit = {v["id"]: v for v in rows(a.db, "SELECT * FROM vitals")}
    act = {x["id"]: x for x in rows(a.db, "SELECT id, label FROM activity")}
    brain = {b["id"]: b for b in rows(a.db, "SELECT id, plan, source, revision FROM brain")}
    pers = {p["id"]: p for p in rows(a.db, "SELECT id, mood, version FROM persona")}
    inv = {}
    for r in rows(a.db, "SELECT owner, item, qty FROM inventory"):
        inv.setdefault(r["owner"], []).append(f"{r['qty']} {r['item']}")
    models = {}
    for r in rows(a.db, "SELECT actor, model, at_ms FROM thought"):
        if r["at_ms"] >= models.get(r["actor"], (0, ""))[0]:
            models[r["actor"]] = (r["at_ms"], r["model"])
    for cid, c in sorted(chars.items()):
        if not c["alive"]:
            print(f"✝ {c['name']:<6} died: {c['cause']}")
            continue
        v = vit.get(cid)
        if v:
            m = (now - v["at_ms"]) / 60000
            hp = max(0, min(v["max_hp"], v["hp"] + v["hp_rate"] * m))
            hu = max(0, min(100, v["hunger"] + v["hunger_rate"] * m))
            en = max(0, min(100, v["energy"] + v["energy_rate"] * m))
            needs = f"hp {hp:3.0f} hun {hu:3.0f} en {en:3.0f}"
        else:
            needs = ""
        b = brain.get(cid, {})
        p = pers.get(cid, {})
        print(f"• {c['name']:<6} {needs}  [{models.get(cid, (0, '-'))[1]}] mood: {p.get('mood', '-')} (v{p.get('version', 0)})")
        print(f"    doing: {act.get(cid, {}).get('label', 'idle')}   pack: {', '.join(inv.get(cid, [])) or '-'}")
        print(f"    plan (r{b.get('revision')} {b.get('source')}): {b.get('plan', '')}")
    print("\nstory:")
    story = sorted(rows(a.db, "SELECT at_ms, kind, text FROM chronicle"), key=lambda r: r["at_ms"])[-a.story:]
    for r in story:
        tt = r["at_ms"] - w["epoch_ms"] + w["day_ms"] * 7 / 24
        h = (tt % w["day_ms"]) / w["day_ms"] * 24
        print(f"  d{int(tt // w['day_ms']) + 1} {int(h):02d}:{int(h % 1 * 60):02d}  {r['text']}")


if __name__ == "__main__":
    main()
