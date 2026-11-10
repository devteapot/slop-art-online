#!/usr/bin/env python3
"""Sample a world's animals (and people's positions) every few seconds, as JSON lines, to read an
ecology from rows: who is where, how hungry, doing what to whom, and who died of what.

  living/tools/eco_sample.py --run RUN --out DIR [--every 10] [--minutes 120]

Uses the verify harness's run state and admin token (`.agents/skills/verify/scripts/verify.py`);
`LIVING_STDB_CONTAINER`/`LIVING_STDB_URL` select the server as for the harness. Read-only.
`eco_report.py DIR` summarizes the samples.
"""
import argparse, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".agents/skills/verify/scripts"))
import verify as V  # noqa: E402


def q(db, token, query):
    code, body = V.http(f"/v1/database/{db}/sql", query, token, raw=True)
    if code != 200:
        raise RuntimeError(f"{code} {body[:300]}")
    res = json.loads(body)[-1]
    names = [e["name"].get("some", "?") for e in res["schema"]["elements"]]
    return [dict(zip(names, r)) for r in res["rows"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--every", type=float, default=10.0)
    ap.add_argument("--minutes", type=float, default=120.0)
    a = ap.parse_args()
    st = V.load(a.run)
    db, token = st["db"], V.admin_token()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = (out / "samples.jsonl").open("a")
    t0 = time.time()
    last_chron = 0
    while time.time() - t0 < a.minutes * 60:
        t = time.time() - t0
        try:
            chars = q(db, token, "SELECT id, kind, alive, cause, died_ms, born_ms, home_x, home_y, stage FROM character WHERE kind != 'person'")
            bodies = q(db, token, "SELECT id, kind, x, y, vx, vy, t_ms FROM body")
            ids = {c["id"] for c in chars}
            vit = [v for v in q(db, token, "SELECT id, hp, hunger, hunger_rate, at_ms FROM vitals") if v["id"] in ids]
            act = [x for x in q(db, token, "SELECT id, skill, phase, target, victim, started_ms FROM activity") if x["id"] in ids]
            inv = [x for x in q(db, token, "SELECT owner, item, qty FROM inventory WHERE item = 'meat'") if x["owner"] in ids]
            clock = q(db, token, "SELECT * FROM clock")
            chron = q(db, token, f"SELECT id, at_ms, kind, a, b, x, y, text FROM chronicle WHERE id > {last_chron}")
            if chron:
                last_chron = max(c["id"] for c in chron)
            people = [[b["id"], round(b["x"], 1), round(b["y"], 1)] for b in bodies if b["kind"] == "person"]
            animals = [b for b in bodies if b["id"] in ids]
            f.write(json.dumps({"t": round(t, 1), "clock": clock, "chars": chars, "bodies": animals, "vitals": vit, "activity": act, "meat": inv, "people": people, "chronicle": chron}) + "\n")
            f.flush()
        except Exception as e:  # keep sampling through a slow or failed read
            print(f"{t:.0f}s: {e}", file=sys.stderr)
        time.sleep(max(0.0, a.every - ((time.time() - t0) - t)))


if __name__ == "__main__":
    main()
