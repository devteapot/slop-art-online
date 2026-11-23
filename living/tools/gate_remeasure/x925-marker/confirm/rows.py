#!/usr/bin/env python3
"""gate216-confirm: row counts of a running world's growth-prone tables every 120 s over HTTP as the owner
(COUNT(*) per table; a missing table is skipped), until the database is gone. Usage: rows.py URL DB TOKEN_FILE OUT.jsonl"""
import json, sys, time, urllib.request
URL, DB, TOK, OUT = sys.argv[1].rstrip("/"), sys.argv[2], open(sys.argv[3]).read().strip(), sys.argv[4]
TABLES = ["perceived", "seen_body_copy", "seen_character_copy", "seen_fighter_copy", "combat_feed", "experience_copy", "experience",
          "line_seen", "act_outcome", "skill_use", "character", "chronicle", "fighter_seen", "combat_seen", "copy_state", "motion_seen"]
def count(t):
    req = urllib.request.Request(f"{URL}/v1/database/{DB}/sql", data=f"SELECT COUNT(*) AS n FROM {t}".encode(), method="POST", headers={"Authorization": f"Bearer {TOK}"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=20).read())[-1]["rows"][0][0]
    except urllib.error.HTTPError as e:
        return None if e.code in (400, 404) else f"http {e.code}"
with open(OUT, "a") as fh:
    while True:
        t = time.time(); rec = {"t": round(t, 2), "rows": {}}
        for tb in TABLES:
            v = count(tb)
            if v is not None:
                rec["rows"][tb] = v
        rec["query_s"] = round(time.time() - t, 3)
        fh.write(json.dumps(rec) + "\n"); fh.flush()
        if not rec["rows"]:
            break
        time.sleep(max(0.0, 120 - (time.time() - t)))
